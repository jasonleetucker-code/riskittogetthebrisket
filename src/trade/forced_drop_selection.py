"""Which player a trade forces a full roster to release, and what that costs.

CANDIDATE FIX, gated by ``forced_drop_cheapest_legal`` (default OFF).  Owner
decision 2026-10-20 §2 (``docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md``);
full record ``docs/trade/FORCED_DROP_FIX_2026-10-20.md``.  With the flag OFF
nothing here runs and every served output is byte-identical to the incumbent
(``tests/trade/test_forced_drop_flag_off_identity.py``).

The defect (``docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md`` §5)
─────────────────────────────────────────────────────────────────────────
The incumbent SELECTS the cut by Effective Cut Cost, ``max(0, base - waiver) x
scarcity`` (``src/draft/displacement.py``), which is 0 for every player at or
below his position's waiver level — on a full roster, the whole tail — so the
choice among them falls to name order.  It then CHARGES the cut at its full
``base x scarcity`` (``ForcedDrop.release_cost``).  Selection and charge measure
different quantities: the cut is whoever sorts first alphabetically, priced at
everything he is worth, while a cheaper legal cut — often the filler the trade
just delivered — goes unused.

The rule (``RULE_ID``)
──────────────────────
1. **One quantity selects and charges.**  A release is charged
   ``c(p) = base(p) x scarcity(pos)`` — exactly the incumbent's
   ``release_cost``, including its ``assumedWaiver`` base for an unpriced
   player — and the cut set is the LINEUP-LEGAL set of the required size with
   the smallest total ``c``.  Built by the canonical cut ladder
   (``build_cut_ladder`` through ``pool_cut_ladder``) with ``order_key = c`` —
   the same lineup guard, so greedy is exact (transversal-matroid dual; any
   weight order).  Ties break on player id, never on name.
2. **Package consistency — receive-and-release is "not received".**  When the
   caller holds the trade's package (``PackageSides``), a just-acquired piece is
   never charged its raw value: releasing it REMOVES it from the package, which
   is re-scored through the one dispatch
   (``src/valuation_math/package_model.adjusted_pair_totals``).  Its charge is
   the package credit forgone, ``gap(package) - gap(package without it)``.  The
   cut set maximises the receiver's net,
   ``gap(package without J) - sum c(existing cuts)``, over every subset ``J`` of
   the acquired pieces (completed cheapest-legal from the existing roster).
   No piece is both credited by the package and charged as a release.
   Without a package (a caller that publishes no package net) an acquired piece
   is a candidate at its raw ``c`` and labelled ``release_value_no_package``.
3. **Unpriced is never silently zero.**  An unpriced player keeps the
   repository's one documented ceiling, the position's waiver level
   (``assumedWaiver``; ``displacement.effective_cut_cost``), for selection AND
   charge — and the Trade Finder now counts it too (the incumbent's
   ``forced_drop_cost`` excluded it as a labelled lower bound while the War Room
   charged it).  Under rule 1 an unpriced player is released only when no
   priced legal alternative — including the incoming filler — is cheaper, so
   the assumed value can never push a charge above a real, priced option.
   This holds for an INCOMING piece the package never credited (unpriced or
   unresolved) too: it forgoes no package credit, so it is charged its own
   ``c`` at the ``assumedWaiver`` ceiling (``release_value_uncredited``) —
   never 0, which would make an identity-join miss the free first cut.
4. **Marginal to the trade.**  ``forced_drop_cost`` charges
   ``max(0, cost(post-trade cleanup) - cost(pre-trade cleanup))``: a roster
   already over the cap owes its own cleanup whether or not it trades.  The
   signed difference is published separately (``forcedDropMarginal``); the
   clamp is labelled ``conservative_clamp``.

Two selection MODES (``SELECTION_MODE``; an owner decision, see the record §3a)
───────────────────────────────────────────────────────────────────────────────
* ``package_consistent`` (V5, the default) — the cut set MINIMISES the charge of
  rule 2 (an acquired piece at its package credit forgone, an existing player
  at ``c``).  Trade-consistent, but the two candidate kinds are compared in
  different units, so it can release a more valuable incoming player and keep
  a less valuable existing one when the package credits the incoming piece
  below its own value.
* ``roster_rational`` (V5-R) — the cut set is the cheapest legal set by ``c``
  across existing AND incoming players alike (one unit, the true cheapest
  roster cut); THEN an acquired cut is charged its package credit forgone and
  an existing cut ``c``.  No double counting either way; V5-R's charge is never
  below V5's (V5 minimises it).

Perfect Draft (``/api/draft/roster-context``) shares ``build_cut_ladder`` and is
NOT changed: it passes no ``order_key``.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.draft.displacement import RosterAsset, effective_cut_cost
from src.ros.lineup import RosterPlayer
from src.valuation_math.package_model import adjusted_pair_totals

__all__ = [
    "FLAG",
    "MODE_PACKAGE_CONSISTENT",
    "MODE_ROSTER_RATIONAL",
    "RULE_ID",
    "RULE_ID_ROSTER_RATIONAL",
    "SELECTION_MODE",
    "PackageSides",
    "Selection",
    "enabled",
    "package_sides",
    "release_charge",
    "rule_id",
    "select_forced_drops",
    "cleanup_cost",
    "cleanup_selection",
]

FLAG = "forced_drop_cheapest_legal"
RULE_ID = "cheapest_legal_package_consistent_v1"
RULE_ID_ROSTER_RATIONAL = "cheapest_legal_roster_rational_v1"

MODE_PACKAGE_CONSISTENT = "package_consistent"
MODE_ROSTER_RATIONAL = "roster_rational"

#: Which cut set the flag selects — a sub-option of ``forced_drop_cheapest_legal``
#: and an OWNER DECISION (``docs/trade/FORCED_DROP_FIX_2026-10-20.md`` §3a).
#: Deliberately a reviewed constant rather than an environment read: switching
#: it changes served verdicts and is a code change with its own evidence.
SELECTION_MODE = MODE_PACKAGE_CONSISTENT

_RULE_BY_MODE = {
    MODE_PACKAGE_CONSISTENT: RULE_ID,
    MODE_ROSTER_RATIONAL: RULE_ID_ROSTER_RATIONAL,
}

#: Acquired-subset enumeration bound.  A trade delivers a handful of players
#: (the finder's widest shape is 3), so this never binds in practice; past it
#: the package step is skipped WITH a note rather than silently truncated.
MAX_PACKAGE_SUBSETS = 64

#: Per-drop ``chargeBasis``.  ``release_value*`` = the player's own ``c``
#: (``base x scarcity``); ``package_credit_forgone`` = the credit the trade's
#: package gave a just-acquired piece — NOT that player's value (a UI that
#: says "worth N" must read this).
CHARGE_RELEASE = "release_value"
CHARGE_PACKAGE = "package_credit_forgone"
CHARGE_NO_PACKAGE = "release_value_no_package"
CHARGE_UNCREDITED = "release_value_uncredited"


def rule_id(mode: str | None = None) -> str:
    """The published rule id of ``mode`` (default: :data:`SELECTION_MODE`)."""
    return _RULE_BY_MODE[mode or SELECTION_MODE]


def enabled() -> bool:
    """``True`` only when the flag is explicitly ON.  An unreadable registry is
    OFF — the incumbent path — never the candidate."""
    try:
        from src.api.feature_flags import is_enabled  # noqa: PLC0415

        # A literal, not ``FLAG``: the reachability audit reads call sites.
        return bool(is_enabled("forced_drop_cheapest_legal"))
    except Exception:  # noqa: BLE001
        return False


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) and v > 0 else None


# ── The package, from the receiving team's side ──────────────────────


@dataclass(frozen=True)
class PackageSides:
    """The trade's package in canonical value, as the receiving team sees it.

    ``sending`` — every priced value the team SENDS (players and picks).
    ``receiving`` — ``(key, value)`` per piece the team RECEIVES: ``key`` is the
    normalised incoming PLAYER label (``None`` for a pick, which occupies no
    spot and is never released), ``value`` is ``None`` when the package did not
    credit the piece (unpriced or unresolved — MISSING IS NEVER ZERO, so it is
    not in the package math at all).
    """

    sending: tuple[float, ...]
    receiving: tuple[tuple[str | None, float | None], ...]

    def gap(self, removed: Mapping[str, int] | None = None) -> float:
        """``receiving_adjusted - sending_adjusted`` with ``removed`` incoming
        players (by multiplicity) taken out — the same quantity
        ``analyze_trade.equity_verdict`` publishes as ``vaAdjustedGap``."""
        pending = Counter(dict(removed or {}))
        kept: list[float] = []
        for key, value in self.receiving:
            if key is not None and pending.get(key, 0) > 0:
                pending[key] -= 1
                continue
            if value is not None:
                kept.append(value)
        send_adj, recv_adj, _sv, _rv = adjusted_pair_totals(list(self.sending), kept)
        return float(recv_adj) - float(send_adj)

    def player_keys(self) -> Counter:
        return Counter(k for k, _v in self.receiving if k is not None)


def package_sides(
    sending: Iterable[Any],
    receiving: Iterable[Any],
    *,
    value_of: Callable[[Any], Any],
    is_player: Callable[[Any], bool],
    label_of: Callable[[Any], Any],
    uncredited_labels: Iterable[Any] = (),
) -> PackageSides:
    """Build :class:`PackageSides` from a caller's resolved assets.

    ``value_of`` must return the value the caller's OWN package math uses (the
    market lens's priced value, the finder's board value), or ``None`` when that
    math leaves the asset out.  ``uncredited_labels`` names incoming players the
    caller could not resolve at all; they are listed with no value so a release
    of one is recognised as "not credited" rather than as a label mismatch.
    """
    send = tuple(v for v in (_positive(value_of(a)) for a in sending) if v is not None)
    recv: list[tuple[str | None, float | None]] = []
    for a in receiving:
        recv.append((_norm(label_of(a)) if is_player(a) else None, _positive(value_of(a))))
    for label in uncredited_labels:
        if _norm(label):
            recv.append((_norm(label), None))
    return PackageSides(sending=send, receiving=tuple(recv))


def _is_pick_asset(a: Any) -> bool:
    flag = getattr(a, "is_pick", None)
    if isinstance(flag, bool):
        return flag
    return str(getattr(a, "position", "") or "").strip().upper() == "PICK"


def board_package(give: Iterable[Any], receive: Iterable[Any]) -> PackageSides | None:
    """A GENERATED trade's package on our board (``model_value``), from the
    requesting team's side — the Trade Finder and Best Offers candidates.

    ``None`` unless flag ``forced_drop_cheapest_legal`` is ON.  The forced-drop
    cost is a board-value cost, so the package an acquired release is netted out
    of is the board-value package — the same quantity the War Room's market lens
    scores.  Labels are the asset ``name``, exactly what
    ``roster_capacity.player_names_only`` hands the capacity owner.
    """
    if not enabled():
        return None
    return package_sides(
        give,
        receive,
        value_of=lambda a: getattr(a, "model_value", None),
        is_player=lambda a: not _is_pick_asset(a),
        label_of=lambda a: getattr(a, "name", None),
    )


# ── The charge ────────────────────────────────────────────────────────


def release_charge(
    asset: RosterAsset,
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, Any] | None,
) -> tuple[float, float, float, str, float, float]:
    """``(charge, ecc, base, basis, waiver, mult)``.

    ``charge = base x mult`` — the incumbent ``ForcedDrop.release_cost``,
    unchanged, including ``base = waiver`` (``assumedWaiver``) for an unpriced
    player.  What changes under the flag is that the cut is SELECTED by it.
    """
    ecc, base, basis, waiver, mult = effective_cut_cost(asset, waiver_values, scarcity)
    return float(base) * float(mult), ecc, base, basis, waiver, mult


# ── Selection ─────────────────────────────────────────────────────────


@dataclass
class Selected:
    asset: RosterAsset
    acquired: bool
    charge: float
    charge_basis: str
    ecc: float
    base: float
    value_basis: str
    waiver: float
    mult: float


@dataclass
class Selection:
    drops: list[Selected] = field(default_factory=list)
    exhausted: bool = False
    package_applied: bool = False
    notes: list[str] = field(default_factory=list)
    mode: str = MODE_PACKAGE_CONSISTENT

    @property
    def total(self) -> float:
        return float(sum(d.charge for d in self.drops))


def _ladder_ids(
    assets: Sequence[RosterAsset],
    *,
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, Any] | None,
    slot_eligibility: Mapping[str, Any] | None,
    rungs: int,
    key: Callable[[RosterAsset], Any],
    candidates: set[str] | None,
) -> list[str]:
    """Rung ids from the ONE cut ladder (``pool_cut_ladder`` ->
    ``build_cut_ladder``), ordered by ``key`` and limited to ``candidates``."""
    from src.roster_intel import pool_cut_ladder  # noqa: PLC0415

    if rungs <= 0:
        return []
    ladder = pool_cut_ladder(
        [
            RosterPlayer(
                player_id=a.player_id,
                canonical_name=a.name,
                position=a.position,
                ros_value=a.board_value,
                injured=a.injured,
                bye=a.bye,
                fantasy_positions=a.fantasy_positions,
            )
            for a in assets
        ],
        list(starter_slots),
        waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
        max_rungs=rungs,
        order_key=key,
        candidate_ids=candidates,
    )
    return [r.player_id for r in ladder.rungs]


def select_forced_drops(
    existing: Sequence[RosterAsset],
    incoming: Sequence[RosterAsset],
    incoming_labels: Sequence[str],
    *,
    drops_needed: int,
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, Any] | None,
    slot_eligibility: Mapping[str, Any] | None,
    package: PackageSides | None = None,
    mode: str | None = None,
) -> Selection:
    """The receiver's cheapest legal cleanup of the post-trade roster.

    ``existing`` is the surviving pre-trade roster, ``incoming`` the acquired
    players with ``incoming_labels`` the caller's label for each (what the
    package is keyed by).  Pure; deterministic; independent of roster order and
    of player names (ties break on player id).  ``mode`` (default
    :data:`SELECTION_MODE`) picks V5 or V5-R; it matters only when a package
    is supplied and a just-acquired player is a candidate.
    """
    mode = mode or SELECTION_MODE
    if mode not in _RULE_BY_MODE:
        raise ValueError(f"unknown forced-drop selection mode: {mode!r}")
    sel = Selection(mode=mode)
    d = int(drops_needed)
    if d <= 0:
        return sel

    # Internal ids are POSITIONAL so two entries sharing an id (a colliding
    # pair, or a player both rostered and incoming) are two candidates; the
    # order key reads the ORIGINAL id, so the choice does not depend on input
    # order.
    pool: list[RosterAsset] = []
    meta: dict[str, tuple[int, bool, float, float, float, str, float, float, str]] = {}
    for i, (asset, acquired) in enumerate(
        [*((a, False) for a in existing), *((a, True) for a in incoming)]
    ):
        internal = f"{i:05d}\x1f{asset.player_id}"
        charge, ecc, base, basis, waiver, mult = release_charge(asset, waiver_values, scarcity)
        meta[internal] = (
            i,
            acquired,
            charge,
            ecc,
            base,
            basis,
            waiver,
            mult,
            _norm(asset.player_id),
        )
        pool.append(replace(asset, player_id=internal))
    by_internal = {a.player_id: a for a in pool}
    originals = [*existing, *incoming]
    n_existing = len(existing)
    labels = {
        f"{n_existing + j:05d}\x1f{a.player_id}": _norm(incoming_labels[j])
        if j < len(incoming_labels)
        else _norm(a.name)
        for j, a in enumerate(incoming)
    }

    def cost_key(a: RosterAsset) -> tuple:
        m = meta[a.player_id]
        return (m[2], m[8], a.position or "", m[0])

    common = dict(
        starter_slots=starter_slots,
        waiver_values=waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
    )

    def make(internal: str, charge: float, basis: str) -> Selected:
        m = meta[internal]
        return Selected(
            asset=originals[m[0]],
            acquired=m[1],
            charge=charge,
            charge_basis=basis,
            ecc=m[3],
            base=m[4],
            value_basis=m[5],
            waiver=m[6],
            mult=m[7],
        )

    acquired_ids = [pid for pid in by_internal if meta[pid][1]]
    existing_ids = {pid for pid in by_internal if not meta[pid][1]}

    package_ok = package is not None and bool(acquired_ids)
    if package is not None and acquired_ids:
        have = package.player_keys()
        need = Counter(labels[pid] for pid in acquired_ids)
        if any(have.get(k, 0) < n for k, n in need.items()):
            package_ok = False
            sel.notes.append(
                "the trade's package does not name every incoming player, so a "
                "just-acquired release is charged its raw release cost instead of "
                "being removed from the package"
            )
        n_subsets = sum(
            math.comb(len(acquired_ids), j) for j in range(0, min(d, len(acquired_ids)) + 1)
        )
        if package_ok and mode == MODE_PACKAGE_CONSISTENT and n_subsets > MAX_PACKAGE_SUBSETS:
            package_ok = False
            sel.notes.append(
                f"{len(acquired_ids)} incoming players exceed the package-consistent "
                "search bound; acquired releases are charged their raw release cost"
            )

    if package_ok:
        assert package is not None
        base_gap = package.gap()
        # Which acquired pieces the package CREDITED: the k-th incoming player
        # with a label is the k-th package entry with that label (the package
        # removes by label and multiplicity).  An uncredited piece (unpriced or
        # unresolved — the package math left it out) forgoes no credit when
        # released, so it is charged its own ``c`` at the ``assumedWaiver``
        # ceiling — never 0 (an identity-join miss must not be a free cut).
        credited_by_label: dict[str, list[bool]] = {}
        for k, v in package.receiving:
            if k is not None:
                credited_by_label.setdefault(k, []).append(v is not None)
        seen: Counter = Counter()
        uncredited: set[str] = set()
        for pid in acquired_ids:
            lab = labels[pid]
            flags = credited_by_label.get(lab, [])
            if seen[lab] < len(flags) and not flags[seen[lab]]:
                uncredited.add(pid)
            seen[lab] += 1

        def charge_of(J: Sequence[str], rest: Sequence[str]) -> float:
            removed = Counter(labels[pid] for pid in J)
            credit = base_gap - package.gap(removed) if J else 0.0
            own = sum(meta[pid][2] for pid in J if pid in uncredited)
            return credit + own + sum(meta[pid][2] for pid in rest)

        def finish(J: Sequence[str], rest: Sequence[str]) -> Selection:
            # Attribute the joint credit across the released acquired pieces
            # by sequential removal, most valuable first; the shares sum
            # exactly to the joint credit (no piece is counted twice).  An
            # uncredited piece adds its own ``c`` to its share.
            shares: list[Selected] = []
            removed: Counter = Counter()
            prev = base_gap
            for pid in sorted(J, key=lambda p: (-(meta[p][4]), meta[p][8], meta[p][0])):
                removed[labels[pid]] += 1
                now = package.gap(removed)
                if pid in uncredited:
                    shares.append(make(pid, (prev - now) + meta[pid][2], CHARGE_UNCREDITED))
                else:
                    shares.append(make(pid, prev - now, CHARGE_PACKAGE))
                prev = now
            drops = [*shares, *(make(pid, meta[pid][2], CHARGE_RELEASE) for pid in rest)]
            sel.drops = sorted(drops, key=lambda s: (s.charge, _norm(s.asset.player_id)))
            sel.package_applied = True
            return sel

        if mode == MODE_ROSTER_RATIONAL:
            # V5-R: the cut SET is the cheapest legal set by ``c`` over the
            # whole post-trade pool (existing and incoming in one unit); the
            # CHARGE then nets an acquired cut out of the package.
            rungs = _ladder_ids(pool, rungs=d, key=cost_key, candidates=None, **common)
            if len(rungs) == d:
                J = [pid for pid in rungs if meta[pid][1]]
                return finish(J, [pid for pid in rungs if not meta[pid][1]])
        else:
            best: tuple | None = None
            ordered_acq = sorted(acquired_ids, key=lambda pid: cost_key(by_internal[pid]))
            for j in range(0, min(d, len(ordered_acq)) + 1):
                for J in itertools.combinations(ordered_acq, j):
                    jset = set(J)

                    def key(a: RosterAsset, _j=jset) -> tuple:
                        return (0 if a.player_id in _j else 1, *cost_key(a))

                    rungs = _ladder_ids(
                        pool, rungs=d, key=key, candidates=jset | existing_ids, **common
                    )
                    if set(rungs[: len(J)]) != jset:
                        continue  # releasing J itself breaks the lineup
                    if len(rungs) < d:
                        continue  # no complete legal cleanup with this J
                    rest = rungs[len(J) :]
                    total = charge_of(J, rest)
                    tie = tuple(sorted(meta[pid][8] for pid in rungs))
                    cand = (round(total, 9), len(J), tie, J, rest)
                    if best is None or cand[:3] < best[:3]:
                        best = cand
            if best is not None:
                return finish(best[3], best[4])
        sel.notes.append(
            "no complete lineup-legal cleanup exists with the package step; "
            "falling back to the cheapest legal releases available"
        )

    rungs = _ladder_ids(pool, rungs=d, key=cost_key, candidates=None, **common)
    sel.drops = [
        make(pid, meta[pid][2], CHARGE_NO_PACKAGE if meta[pid][1] else CHARGE_RELEASE)
        for pid in rungs
    ]
    sel.exhausted = len(sel.drops) < d
    return sel


def cleanup_selection(
    roster: Sequence[RosterAsset],
    drops_needed: int,
    *,
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, Any] | None,
    slot_eligibility: Mapping[str, Any] | None,
) -> Selection:
    """The cheapest legal cleanup of ``roster`` alone — what an
    already-over-limit roster owes whether or not it trades (no incoming
    players, so both modes agree)."""
    return select_forced_drops(
        roster,
        (),
        (),
        drops_needed=drops_needed,
        starter_slots=starter_slots,
        waiver_values=waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
    )


def cleanup_cost(
    roster: Sequence[RosterAsset],
    drops_needed: int,
    *,
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, Any] | None,
    slot_eligibility: Mapping[str, Any] | None,
) -> tuple[float, bool]:
    """``(cost, exhausted)`` of :func:`cleanup_selection`."""
    sel = cleanup_selection(
        roster,
        drops_needed,
        starter_slots=starter_slots,
        waiver_values=waiver_values,
        scarcity=scarcity,
        slot_eligibility=slot_eligibility,
    )
    return sel.total, sel.exhausted
