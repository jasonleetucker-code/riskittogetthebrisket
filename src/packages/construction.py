"""Canonical package-construction substrate (V1-36 / C3-PKG-01).

WHAT THIS OWNS, AND WHAT IT DELIBERATELY DOES NOT
─────────────────────────────────────────────────
Four products recommend trades and they answer four different questions:

* ``src/trade/finder.py`` — arbitrage between our board and the retail market
* ``src/trade/suggestions.py`` — roster-aware sell-high / buy-low / consolidate
* ``src/trade/angle.py`` — "how do I get player X"
* ``src/roster_intel/packages.py`` — a counterparty Pareto frontier

Their OBJECTIVES, scoring functions, filters, endpoints and recommendation
policies are genuinely different and are NOT unified here.  Forcing four
products through one algorithm to satisfy the word "one" would be the wrong
correction.

What they had no business owning four times over is the MECHANICS of building
a package, and until 2026-08-18 they did.  Measured across the four:

============================  =========================================
mechanic                      state before this module
============================  =========================================
dedup identity                ``finder`` keyed on **display names**;
                              ``roster_intel`` keyed on **asset ids**.
                              The name-keyed one collapses two assets
                              that share a board row — exactly the
                              class C1-U3 exists to prevent.
truncation                    three strategies: a bare ``[:30]`` slice
                              (SILENT), ``max_candidates_per_stage``
                              (reported), ``per_team_limit`` (reported)
legality                      1 of 4 had any hook at all
side construction             four hand-rolled ``combinations`` /
                              nested-loop enumerations
self-trade prevention         name sets, id sets, and a seed-name set
value known/unknown           four different thresholds and three
                              different treatments of "unpriced"
============================  =========================================

So this module owns exactly those mechanics and nothing else.  It computes no
score, ranks nothing, and has no opinion about which package is good.

THE RULES IT ENFORCES
─────────────────────
**One dedup identity.**  :func:`package_key` keys on canonical asset ids and
falls back to a name only when an id is absent — and records that it did, so a
name-keyed package is visible rather than assumed equivalent to an id-keyed
one.  Two assets sharing a display name are two assets.

**Truncation is never silent.**  Every bound reports what it dropped through
:class:`EnumerationReport`.  A caller that shows "no trades found" when the
truth is "we stopped looking" is the failure this replaces.

**Missing is never zero.**  An asset the board declined to price is
``value_known=False``.  It is not worth 0, it is not silently dropped, and the
policy decides whether it may take part — but the count of what was excluded is
always reported.

**Asymmetry is allowed and bounded.**  A trade need not have equal counts.
``max_side_difference`` (default 1) admits 2-for-1 and 3-for-2 while refusing
the degenerate 5-for-1 shapes that come from unbounded enumeration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence

__all__ = [
    "EligibilityPolicy",
    "EnumerationReport",
    "PackageAsset",
    "MAX_PLAYER_COUNT_DIFFERENCE",
    "PackageShape",
    "SidePair",
    "adapt_assets",
    "by_value_desc",
    "enumerate_packages",
    "enumerate_sides",
    "package_key",
    "player_count",
    "side_key",
    "topology_is_allowed",
]


# ── The normalized asset view ────────────────────────────────────────


class _HasTradeFields(Protocol):
    name: str
    position: str


@dataclass(frozen=True)
class PackageAsset:
    """One tradeable asset, as the substrate sees it.

    Products keep their own richer asset types; this is the projection the
    construction mechanics need, and nothing else.  ``source`` carries the
    caller's original object so a product can score what it enumerated without
    a second lookup.
    """

    asset_id: str
    name: str
    position: str
    #: ``None`` when the board declined to price the asset.  NOT zero.
    value: float | None
    source: Any = None

    @property
    def value_known(self) -> bool:
        return self.value is not None

    @property
    def is_pick(self) -> bool:
        return self.position.strip().upper() == "PICK"

    @property
    def key(self) -> str:
        """Identity for dedup and self-trade checks.

        Prefers the canonical asset id.  A name is a LAST resort and is marked,
        because two assets can share a display name (a manager holding his own
        2027 1st and one acquired from another team hold two assets against one
        board row) and collapsing them is a real defect, not a rounding error.
        """
        aid = (self.asset_id or "").strip().lower()
        if aid:
            return f"id:{aid}"
        return f"name:{(self.name or '').strip().lower()}"

    @property
    def key_is_name_fallback(self) -> bool:
        return not (self.asset_id or "").strip()


def adapt_assets(
    assets: Iterable[Any],
    *,
    id_of: Callable[[Any], str] | None = None,
    name_of: Callable[[Any], str] | None = None,
    position_of: Callable[[Any], str] | None = None,
    value_of: Callable[[Any], float | None] | None = None,
) -> list[PackageAsset]:
    """Project a product's own asset objects into :class:`PackageAsset`.

    The accessors default to the attribute names this repo's trade types
    already use, so most callers pass nothing.  A product with a different
    shape supplies the one accessor that differs rather than a whole adapter
    class.
    """

    def _default_id(a: Any) -> str:
        for attr in ("asset_id", "player_id", "playerId", "canonical_asset_id"):
            got = getattr(a, attr, None)
            if got:
                return str(got)
        return ""

    def _default_name(a: Any) -> str:
        return str(getattr(a, "name", "") or "")

    def _default_position(a: Any) -> str:
        return str(getattr(a, "position", "") or "")

    def _default_value(a: Any) -> float | None:
        for attr in ("display_value", "model_value", "board_value", "value"):
            got = getattr(a, attr, None)
            if isinstance(got, (int, float)) and not isinstance(got, bool) and got > 0:
                return float(got)
        return None

    get_id = id_of or _default_id
    get_name = name_of or _default_name
    get_pos = position_of or _default_position
    get_val = value_of or _default_value

    return [
        PackageAsset(
            asset_id=get_id(a),
            name=get_name(a),
            position=get_pos(a),
            value=get_val(a),
            source=a,
        )
        for a in assets
    ]


# ── Identity ─────────────────────────────────────────────────────────


def by_value_desc(asset: PackageAsset) -> tuple[int, float]:
    """Default pool ordering: most valuable first, unpriced LAST.

    Written as a two-part key rather than ``-(value or 0)`` because the
    coercion would be a decision-path fabrication: the pool order decides what
    survives truncation, and "we could not price this" is not "this is worth
    nothing".  Unpriced assets sort last by an explicit rule instead.
    """
    return (0 if asset.value_known else 1, -(asset.value if asset.value_known else 0.0))


def side_key(side: Sequence[PackageAsset]) -> tuple[str, ...]:
    """Order-independent identity for one side of a trade."""
    return tuple(sorted(a.key for a in side))


def package_key(
    send: Sequence[PackageAsset],
    receive: Sequence[PackageAsset],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """THE dedup identity for a package.

    Directional: giving A for B is not the same proposal as giving B for A.
    """
    return (side_key(send), side_key(receive))


# ── Eligibility ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class EligibilityPolicy:
    """Which assets may take part in a package at all.

    This is the BASIC gate — "is this a coherent tradeable asset" — not the
    product's quality filter.  ``finder``'s market gate, ``suggestions``'
    top-150 board gate and ``roster_intel``'s cornerstone rule all stay where
    they are: they are objectives, not mechanics.
    """

    #: Assets below this are roster clog for every product.  ``None`` disables.
    min_value: float | None = None
    #: Whether an asset the board declined to price may take part.  Default
    #: False: a package containing an asset nobody can price cannot be scored,
    #: and admitting it would force every product to invent a value.
    allow_unknown_value: bool = False
    #: Require a position.  Positionless rows are placeholders in this repo.
    require_position: bool = True
    #: Exclude by identity key (already in the trade, on the wrong roster, …).
    excluded_keys: frozenset[str] = frozenset()

    def admits(self, asset: PackageAsset) -> bool:
        if asset.key in self.excluded_keys:
            return False
        if self.require_position and not asset.position.strip():
            return False
        if not asset.value_known:
            return self.allow_unknown_value
        if self.min_value is not None and (asset.value or 0.0) < self.min_value:
            return False
        return True


# ── Shapes ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PackageShape:
    """How many assets each side may contribute."""

    send: int
    receive: int

    def __post_init__(self) -> None:
        if self.send < 1 or self.receive < 1:
            raise ValueError("a package must have at least one asset on each side")


#: C3-TOPO-01 — the owner's bound on generated-trade topology.
#:
#: ``abs(players_A - players_B) <= 1``.  1v1, 2v1, 1v2, 3v2 and 2v3 are
#: allowed; 3v1, 1v3, 4v2 and 2v4 are not.  This SUPERSEDES the earlier
#: exact-equal-player-count rule (#841/#842 supersession).
MAX_PLAYER_COUNT_DIFFERENCE = 1


def player_count(side: Sequence[PackageAsset]) -> int:
    """How many PLAYERS a side contributes.  Picks are not players.

    The distinction is the whole content of C3-TOPO-01: a manager reads
    "three-for-one" as a lopsided offer whether or not a pick rides along, and
    reads "two players plus a pick for two players" as even.  Counting assets
    instead would call the first even and the second lopsided.
    """

    return sum(1 for asset in side if not asset.is_pick)


def topology_is_allowed(
    send: Sequence[PackageAsset],
    receive: Sequence[PackageAsset],
    *,
    max_difference: int = MAX_PLAYER_COUNT_DIFFERENCE,
) -> bool:
    """Whether this package's player counts are close enough to propose.

    A GENERATED-trade rule.  It deliberately does not apply to a trade a user
    typed in — the simulator answers the question it was asked, and refusing to
    evaluate a legal 3-for-1 because a generator would not have proposed it is
    the ``_check_legality`` mistake in a different costume.
    """

    return abs(player_count(send) - player_count(receive)) <= max_difference


def _default_shapes(max_per_side: int, max_side_difference: int) -> list[PackageShape]:
    """Every shape up to ``max_per_side`` within the asymmetry bound.

    Asymmetry is ALLOWED — a trade does not have to be equal-count, and
    refusing 2-for-1 to keep the arithmetic tidy returns nonsense packages.
    It is BOUNDED because unbounded enumeration produces 5-for-1 shapes that
    no manager would consider and that swamp the search budget.
    """
    shapes: list[PackageShape] = []
    for send in range(1, max_per_side + 1):
        for receive in range(1, max_per_side + 1):
            if abs(send - receive) <= max_side_difference:
                shapes.append(PackageShape(send, receive))
    shapes.sort(key=lambda s: (s.send + s.receive, s.send, s.receive))
    return shapes


# ── Enumeration ──────────────────────────────────────────────────────


@dataclass
class EnumerationReport:
    """What the enumeration did, including what it refused to look at.

    Published so a caller never has to guess whether an empty result means
    "nothing qualified" or "we stopped looking".  ``finder``'s bare ``[:30]``
    slice reported neither.
    """

    our_pool_size: int = 0
    their_pool_size: int = 0
    our_excluded_ineligible: int = 0
    their_excluded_ineligible: int = 0
    our_excluded_unpriced: int = 0
    their_excluded_unpriced: int = 0
    our_truncated_to: int | None = None
    their_truncated_to: int | None = None
    shapes: list[str] = field(default_factory=list)
    emitted: int = 0
    duplicates_suppressed: int = 0
    budget_exhausted: bool = False
    name_keyed_assets: int = 0
    #: C3-TOPO-01 refusals.  Reported rather than silent: "no 3-for-1 came
    #: back" and "3-for-1 is not a shape we propose" are different answers.
    topology_rejected: int = 0

    @property
    def truncated(self) -> bool:
        return bool(
            self.our_truncated_to is not None
            or self.their_truncated_to is not None
            or self.budget_exhausted
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ourPoolSize": self.our_pool_size,
            "theirPoolSize": self.their_pool_size,
            "ourExcludedIneligible": self.our_excluded_ineligible,
            "theirExcludedIneligible": self.their_excluded_ineligible,
            "ourExcludedUnpriced": self.our_excluded_unpriced,
            "theirExcludedUnpriced": self.their_excluded_unpriced,
            "topologyRejected": self.topology_rejected,
            "ourTruncatedTo": self.our_truncated_to,
            "theirTruncatedTo": self.their_truncated_to,
            "shapes": list(self.shapes),
            "emitted": self.emitted,
            "duplicatesSuppressed": self.duplicates_suppressed,
            "budgetExhausted": self.budget_exhausted,
            "truncated": self.truncated,
            # Assets that had no canonical id and fell back to a name key.
            # Non-zero means the dedup identity is weaker for those rows.
            "nameKeyedAssets": self.name_keyed_assets,
        }


@dataclass(frozen=True)
class SidePair:
    """One enumerated package, before any product has scored it."""

    send: tuple[PackageAsset, ...]
    receive: tuple[PackageAsset, ...]

    @property
    def key(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return package_key(self.send, self.receive)

    def sources(self) -> tuple[list[Any], list[Any]]:
        """The caller's original objects, for scoring."""
        return ([a.source for a in self.send], [a.source for a in self.receive])


def enumerate_sides(
    assets: Iterable[Any],
    sizes: Sequence[int],
    *,
    policy: EligibilityPolicy | None = None,
    required: Sequence[Any] = (),
    pool_limit: int | None = None,
    max_sides: int | None = None,
    rank_key: Callable[[PackageAsset], Any] | None = None,
    adapt: bool = True,
) -> tuple[Iterator[tuple[PackageAsset, ...]], EnumerationReport]:
    """Enumerate ONE side of a trade.

    The primitive underneath :func:`enumerate_packages`, and the shape
    ``src/trade/angle.py`` actually needs: there the OTHER side is fixed (the
    player you are trying to acquire, or the seed you insist on including) and
    only the counter-package is enumerated.  Angle had two hand-rolled copies
    of this, one of them with its own seed/filler split.

    ``required`` assets appear in every emitted side and do not count against
    ``policy`` — a caller that has already decided an asset is in the package
    is not asking whether it is eligible.  They DO count against ``sizes``, so
    asking for 2-asset sides with one required asset enumerates one filler.
    """
    policy = policy or EligibilityPolicy()
    report = EnumerationReport()

    pool = adapt_assets(assets) if adapt else list(assets)
    fixed = tuple(adapt_assets(required) if adapt else list(required))
    report.our_pool_size = len(pool)
    report.name_keyed_assets = sum(1 for a in (*pool, *fixed) if a.key_is_name_fallback)

    fixed_keys = {a.key for a in fixed}
    pool = [a for a in pool if a.key not in fixed_keys]
    pool = _eligible(pool, policy, report, ours=True)

    order = rank_key or by_value_desc
    pool.sort(key=order)
    if pool_limit is not None and pool_limit > 0 and len(pool) > pool_limit:
        report.our_truncated_to = pool_limit
        pool = pool[:pool_limit]

    wanted = sorted({int(n) for n in sizes if int(n) >= 1})
    report.shapes = [f"{n}-asset" for n in wanted]

    def _iter() -> Iterator[tuple[PackageAsset, ...]]:
        seen: set[tuple[str, ...]] = set()
        for size in wanted:
            free = size - len(fixed)
            if free < 0:
                continue  # cannot fit the required assets in a side this small
            if free > len(pool):
                continue
            for fillers in combinations(pool, free):
                if max_sides is not None and report.emitted >= max_sides:
                    report.budget_exhausted = True
                    return
                side = (*fixed, *fillers)
                key = side_key(side)
                if len(set(key)) != len(side):
                    continue  # the same asset twice
                if key in seen:
                    report.duplicates_suppressed += 1
                    continue
                seen.add(key)
                report.emitted += 1
                yield side

    return _iter(), report


def _eligible(
    assets: Sequence[PackageAsset],
    policy: EligibilityPolicy,
    report: EnumerationReport,
    *,
    ours: bool,
) -> list[PackageAsset]:
    kept: list[PackageAsset] = []
    ineligible = 0
    unpriced = 0
    for asset in assets:
        if not asset.value_known and not policy.allow_unknown_value:
            unpriced += 1
            continue
        if not policy.admits(asset):
            ineligible += 1
            continue
        kept.append(asset)
    if ours:
        report.our_excluded_ineligible = ineligible
        report.our_excluded_unpriced = unpriced
    else:
        report.their_excluded_ineligible = ineligible
        report.their_excluded_unpriced = unpriced
    return kept


def enumerate_packages(
    our_assets: Iterable[Any],
    their_assets: Iterable[Any],
    *,
    policy: EligibilityPolicy | None = None,
    shapes: Sequence[PackageShape] | None = None,
    max_per_side: int = 2,
    max_side_difference: int = 1,
    enforce_topology: bool = True,
    max_player_difference: int = MAX_PLAYER_COUNT_DIFFERENCE,
    pool_limit: int | None = None,
    max_packages: int | None = None,
    rank_key: Callable[[PackageAsset], Any] | None = None,
    adapt: bool = True,
) -> tuple[Iterator[SidePair], EnumerationReport]:
    """Enumerate every legal package shape between two pools.

    Returns ``(packages, report)``.  The iterator is lazy so a product can stop
    early; the report is filled in as it goes and is only complete once the
    iterator is exhausted — except for the pool-level counts, which are final
    immediately.

    This owns mechanics ONLY.  It does not score, rank by quality, or decide
    which package is good; ``rank_key`` orders the POOLS so that a truncation
    keeps the assets a product cares about, and defaults to descending value.
    """
    policy = policy or EligibilityPolicy()
    report = EnumerationReport()

    ours = adapt_assets(our_assets) if adapt else list(our_assets)
    theirs = adapt_assets(their_assets) if adapt else list(their_assets)
    report.our_pool_size = len(ours)
    report.their_pool_size = len(theirs)
    report.name_keyed_assets = sum(1 for a in (*ours, *theirs) if a.key_is_name_fallback)

    ours = _eligible(ours, policy, report, ours=True)
    theirs = _eligible(theirs, policy, report, ours=False)

    order = rank_key or by_value_desc
    ours.sort(key=order)
    theirs.sort(key=order)

    if pool_limit is not None and pool_limit > 0:
        if len(ours) > pool_limit:
            report.our_truncated_to = pool_limit
            ours = ours[:pool_limit]
        if len(theirs) > pool_limit:
            report.their_truncated_to = pool_limit
            theirs = theirs[:pool_limit]

    plan = list(shapes) if shapes else _default_shapes(max_per_side, max_side_difference)
    report.shapes = [f"{s.send}-for-{s.receive}" for s in plan]

    def _iter() -> Iterator[SidePair]:
        seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
        for shape in plan:
            if len(ours) < shape.send or len(theirs) < shape.receive:
                continue
            for send in combinations(ours, shape.send):
                send_keys = {a.key for a in send}
                if len(send_keys) != len(send):
                    continue  # the same asset twice on one side
                for receive in combinations(theirs, shape.receive):
                    if max_packages is not None and report.emitted >= max_packages:
                        report.budget_exhausted = True
                        return
                    receive_keys = {a.key for a in receive}
                    if len(receive_keys) != len(receive):
                        continue
                    if send_keys & receive_keys:
                        continue  # self-trade: the same asset on both sides
                    if enforce_topology and not topology_is_allowed(
                        send, receive, max_difference=max_player_difference
                    ):
                        report.topology_rejected += 1
                        continue
                    pair = SidePair(send=send, receive=receive)
                    if pair.key in seen:
                        report.duplicates_suppressed += 1
                        continue
                    seen.add(pair.key)
                    report.emitted += 1
                    yield pair

    return _iter(), report
