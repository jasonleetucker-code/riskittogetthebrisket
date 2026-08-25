"""Trade suggestion engine v2.

Given a roster, canonical values, and league context, generates actionable
trade suggestions: sell-high, buy-low, consolidation, positional upgrades.

v2 adds:
- Market-disagreement signals (source CV, edge detection)
- Opponent-aware filtering (bilateral roster fit when league rosters provided)

Design principles:
- Deterministic: same inputs → same outputs
- Roster-aware: understands positional surplus and need
- Value-aware: uses canonical display values for fairness
- League-aware: understands league format context
- Signal-honest: only flags edges when supported by data

The engine does NOT modify any internal canonical values or calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from src.canonical.calibration import to_display_value
from src.packages import PackageAsset, adapt_assets, side_key
from src.trade.ktc_va import adjusted_pair_totals
from src.utils.name_clean import normalize_position as _norm_pos  # noqa: F401 — see _norm_pos shim removal below (audit S2)
from src.ros.lineup import configured_slot_eligibility, resolve_starter_slots, slot_demand


# ── Configuration ────────────────────────────────────────────────────

# Starter demand per position in default SF/TEP/IDP (effective starters per
# team).  Aligned with the live dynasty_main lineup (config/leagues/registry
# rosterSettings, corrected 2026-07-26 per docs/league-intelligence/
# SETTINGS_AUDIT.md): QB1 RB2 WR3 TE2 FLEX2 SFLEX1 K1 DL3 LB3 DB3, no
# IDP_FLEX.  K is deliberately absent — kickers are not tradeable assets in
# the suggestion engine (they carry no dynasty value on the board).
DEFAULT_STARTER_NEEDS: dict[str, int] = {
    "QB": 2,  # 1 QB + ~1 SFLEX
    "RB": 3,  # 2 RB + ~1 FLEX
    "WR": 4,  # 3 WR + ~1 FLEX
    "TE": 2,  # 2 TE
    "DL": 3,  # 3 DL (fixed slots; league has no IDP_FLEX)
    "LB": 3,  # 3 LB
    "DB": 3,  # 3 DB
}

# Slots that carry no dynasty trade demand.  ``K`` is deliberately
# absent from the constant above and must stay absent from the derived
# version: kickers carry no board value, so a "need" for one can never
# be met or traded for.  ``BN``/``IR``/``TAXI`` are not lineup slots.
_NON_DEMAND_SLOTS: frozenset[str] = frozenset({"K", "DEF", "BN", "IR", "TAXI"})


def starter_needs_for_league(league_key: str | None = None) -> dict[str, int]:
    """Effective starter demand per position for one league.

    ``DEFAULT_STARTER_NEEDS`` above is not a slot count — it is a demand
    model: base slots PLUS a hand-allocation of the flex slots, because
    a superflex league genuinely wants a second startable QB even though
    only one QB slot exists.  That model was correct and hardcoded, which
    made it silently wrong for any other league.  The two live leagues
    share a scoring profile but not a lineup (``dynasty_main`` starts
    2 TE and 9 IDP; ``dynasty_new`` starts 1 TE and no IDP), and starter
    counts are leagueKey-scoped per CLAUDE.md.

    The allocation rule, stated once so it is auditable:

    * every fixed positional slot contributes 1 to its own position;
    * each ``SFLEX``/``SUPER_FLEX`` slot contributes 1 to ``QB`` — it is
      the reason the format is called superflex;
    * each ``FLEX`` slot contributes 1, round-robin over the league's
      own ``flexEligible`` list in ``RB``, ``WR``, ``TE`` order;
    * each ``IDP_FLEX`` slot contributes 1, round-robin over
      ``idpFlexEligible``;
    * ``K``/``DEF`` contribute nothing — see ``_NON_DEMAND_SLOTS``.

    Since C2-U1 the first four bullets ARE
    ``src/ros/lineup.py::slot_demand(...).flex_priority`` — a declared
    variant of the one slot-demand contract, not a fifth private model.
    Only the last bullet is this engine's own policy, because "a kicker
    is not a dynasty need" is a trade judgment rather than a lineup fact.

    Applied to ``dynasty_main`` this reproduces ``DEFAULT_STARTER_NEEDS``
    exactly, so the live league's suggestions are unchanged; pinned by
    ``tests/league_intel/test_registry_consumers.py``.

    Falls back to ``DEFAULT_STARTER_NEEDS`` when the registry has
    nothing to say — an unknown key, or no roster settings — rather than
    returning an empty demand map, which would read as "this roster
    needs nobody" and silence every surplus/need suggestion.
    """
    settings: dict[str, Any] = {}
    try:
        from src.api.league_registry import get_league_roster_settings

        settings = get_league_roster_settings(league_key) or {}
    except Exception:  # noqa: BLE001 — registry is optional for this module
        settings = {}
    slots, _source = resolve_starter_slots(roster_settings=settings)
    if not slots:
        return dict(DEFAULT_STARTER_NEEDS)

    # The one resolver, not a local two-entry copy.  The retired map here
    # omitted ``sflexEligible`` entirely, so a league that narrows its
    # Superflex was measured against the declared default — and C2-U1's
    # ``configured_slot_eligibility`` docstring names this very module as the
    # "two-entry variant" it exists to replace.
    demand = slot_demand(
        slots, eligibility_overrides=configured_slot_eligibility(settings)
    ).flex_priority
    needs = {pos: n for pos, n in demand.items() if pos not in _NON_DEMAND_SLOTS}
    return needs or dict(DEFAULT_STARTER_NEEDS)


# Minimum display value to consider a player "rosterable" (not a throw-in).
#
# ⚠ INERT ON THE CURRENT BOARD, twice over.  Measured on the pinned
# 2026-07-30 contract:
#
#   * the board's structural floor is **757** — every row the pipeline
#     prices lands above it, and unpriced rows are already dropped by
#     the ``cv_int <= 0`` guard in ``_players_from_contract``, so this
#     removes **0 of 812**;
#   * every call site below runs AFTER ``BOARD_TOP_N_FILTER`` (150), and
#     the 150th row is worth **3,217** — a 6.4x margin.
#
# So the "not a throw-in" gate this names is really enforced by
# ``BOARD_TOP_N_FILTER``.  Kept rather than deleted: it is a cheap
# defensive floor across 14 call sites, and the board's floor is a
# property of today's sources rather than a guarantee.
#
# But it is NOT a free dial.  Anything above ~900 starts removing real
# players (900 -> 31 rows, 1200 -> 124, 1500 -> 292), so raising it
# "since it does nothing anyway" would silently cut suggestions.  Pinned
# by ``tests/trade/test_actionability_floors.py``.
#
# Contrast ``MIN_ACTIONABLE_VALUE`` below, which is NOT inert: at 2,000
# it suppresses 477 of the 812 priced rows and is doing real work.
MIN_RELEVANT_VALUE = 500

# Fairness band: how close two trade sides need to be (display scale).
# NOTE (2026-07-25 audit F-7): this scale (even <256 / lean <769 /
# stretch ≥769, see _fairness_label) is INDEPENDENT of the trade
# page's verdict bands (350/900/1800 in frontend/lib/trade-logic.js)
# — the two surfaces intentionally use different vocabularies and the
# old "~1 Lean verdict worth" comment here was wrong.  769's origin
# is undocumented legacy tuning; change it only with before/after
# suggestion-volume measurement.
FAIRNESS_TOLERANCE = 769

# How many suggestions per category
MAX_SUGGESTIONS_PER_TYPE = 8

# Consolidation: the upgrade target must be worth at least this fraction
# of the combined depth pieces
CONSOLIDATION_MIN_UPGRADE_RATIO = 0.70

# Max overpay ratio for consolidation "stretch" trades to survive filtering.
# A stretch consolidation is kept if gap / give_total ≤ this value — i.e.,
# you're overpaying by at most 30% of what you send out.  This lets through
# realistic "2 depth pieces for 1 starter" packages while still blocking
# absurd overpays.
CONSOLIDATION_MAX_OVERPAY_RATIO = 0.30

# Positional upgrades: when searching surplus positions for a sweetener,
# allow up to this multiple of FAIRNESS_TOLERANCE.  Surplus depth is
# expendable, so slightly wider tolerance is acceptable.
UPGRADE_SWEETENER_SURPLUS_MULTIPLIER = 2.0

# ── Quality filter thresholds ────────────────────────────────────────
# These control post-ranking deduplication and noise suppression.

# Max times a single give-player can appear across ALL categories combined.
# Prevents "Breece Hall fatigue" — seeing the same outgoing player 7 times.
# Lowered from 3→2 after audit showed 52.5% of suggestions were repetitive.
MAX_GIVE_PLAYER_APPEARANCES = 2

# Max suggestions per receive-target within a single category.
# Prevents consolidation from showing 6 different pairs all targeting Bijan.
MAX_RECEIVE_TARGET_PER_CATEGORY = 2

# Max low-confidence suggestions per category.
# Low-conf ideas are speculative; cap keeps the feed actionable.
MAX_LOW_CONFIDENCE_PER_CATEGORY = 2

# Minimum display value for BOTH sides of a trade to be "actionable".
# Swapping two depth pieces worth < 2000 each isn't worth negotiating.
MIN_ACTIONABLE_VALUE = 2000

# Suppress 1-for-1 suggestions where the gap admits the trade needs sweeteners.
# If abs(gap) exceeds this and the engine attached balancers, it's really a
# package deal masquerading as a 1-for-1.
MAX_GAP_FOR_1FOR1 = 400

# Market-disagreement thresholds
HIGH_DISPERSION_CV = 0.12  # CV above this = sources disagree meaningfully
LOW_DISPERSION_CV = 0.04  # CV below this = strong consensus

# ── Board quality gate ──────────────────────────────────────────────
# Hard filter: only players ranked inside the top-N of OUR OWN blended
# board are eligible for trade suggestions.  Players outside this
# threshold are excluded as targets, give-side pieces, throw-ins, and
# balancers.  Set to 0 to disable.
#
# WS-J F-4: this was called ``KTC_TOP_N_FILTER`` and its helper was
# called ``_assign_ktc_ranks``, but no KTC value was ever read here.
# ``_assign_board_ranks`` enumerates the pool after it has been sorted
# by ``display_value``, so the rank has always been our blended-board
# rank.  The docstring additionally claimed "players without KTC data
# get ktc_rank=None", which never happened — every player got an int.
#
# The gate itself is sound and is deliberately NOT unified with
# ``finder.py``'s.  The two engines ask different questions:
#
#   finder.py      finds arbitrage between our board and the retail
#                  market, so it MUST anchor on a real market value
#                  (KTC for offense, IDPTradeCalc for IDP) — the
#                  market number is load-bearing in its arithmetic.
#   suggestions.py filters for asset QUALITY ("don't propose trading
#                  roster clog"), which our own blended board answers
#                  directly and for every asset class, including IDP
#                  and picks that no single retail board covers.
#
# Sharing one definition would force this engine to depend on retail
# coverage it does not need, and would reintroduce the offense-only
# blind spot F-3 just removed.  So: renamed to say what it does, not
# merged.
BOARD_TOP_N_FILTER = 150

# Deprecated alias — this gate never consulted KTC.
KTC_TOP_N_FILTER = BOARD_TOP_N_FILTER


# ── Data structures ─────────────────────────────────────────────────

_IDP_BASE_POSITIONS = frozenset({"DL", "LB", "DB"})


@dataclass
class PlayerAsset:
    """A player or pick with canonical values."""

    name: str
    position: str
    display_value: int
    calibrated_value: int
    source_count: int = 0
    team: str = ""
    rookie: bool = False
    years_exp: int | None = None
    universe: str = ""
    dispersion_cv: float | None = None
    board_rank: int | None = None  # 1-based rank on OUR blended board

    @property
    def ktc_rank(self) -> int | None:
        """Deprecated alias — this was never a KTC rank (WS-J F-4)."""
        return self.board_rank


def _identity_key(name: str) -> str:
    """This file's per-asset identity, routed through the C3-PKG-01 owner
    (``src.packages.PackageAsset.key``) instead of a hand-rolled
    normalization (V1-36).

    ``PlayerAsset`` carries no stable asset id — there is nothing here to
    join on except a display name — so every call resolves through the
    owner's own name-fallback branch (``PackageAsset.key_is_name_fallback``)
    exactly as ``finder.py``/``angle.py``'s callers do today when their
    asset objects likewise carry no id. That is the SAME limitation this
    file had before migrating: this change makes the normalization formula
    single-owner, not more identity-resolving than the inputs allow.

    Every membership/dedup check in this module — pool-name join, sendable
    view, C3-CON-01 blocked set, roster/exclude sets used by the four
    generators and the balancer helpers — must call this one function
    rather than its own ``.lower()``/``.strip()`` variant, so a name
    compared on one side of a check is always keyed identically to the
    name compared on the other side.
    """
    return PackageAsset(asset_id="", name=name or "", position="", value=None).key


def _side_identity(assets: "list[PlayerAsset]") -> tuple[str, ...]:
    """Identity of ONE side of a candidate package, from the C3-PKG-01 owner
    (``src.packages.side_key``) — order-independent, per-asset-canonical.

    This module had three hand-rolled side keys before V1-36, each spelled
    differently and each subtly weaker than the owner's:
    ``s.receive[0].name`` (first asset only, so a 2-asset receive side was
    keyed by half of itself), ``f"{p1.name}|{p2.name}"`` (ORDER-dependent,
    so the same unordered pair could key two ways), and
    ``"|".join(sorted(p.name ...))`` (sorted, but on raw display names).
    Routing all three through one owner is the whole of what C3-PKG-01 asks
    of this file at the side level.

    ``adapt_assets`` reads ``.name`` / ``.position`` / ``.display_value``,
    which ``PlayerAsset`` already carries, so no adapter class is needed and
    no second representation is introduced.
    """
    return side_key(adapt_assets(assets))


#: ``src.packages.package_key`` — the WHOLE-package (both-sides) identity —
#: deliberately has no call site in this module, and that is a measured
#: statement rather than an oversight.  ``package_key(send, receive)`` is
#: literally ``(side_key(send), side_key(receive))``, and every dedup this
#: file actually performs is SINGLE-SIDED: buy-low buckets by its receive
#: side, consolidation by its give pair, the quality pass by its receive
#: side.  There is no cross-category "have I already proposed this exact
#: give-for-receive package" check anywhere in the pipeline today.  Adding
#: one would suppress suggestions that currently ship — a behaviour change,
#: not an identity canonicalisation — so V1-36 consumes the owner's
#: ``side_key`` at all four real sites and leaves the composite unused
#: rather than inventing a consumer for it.  Recorded for Claude 5: whether
#: duplicate packages SHOULD be collapsed across categories is a product
#: question this unit is not authorised to answer.


@dataclass
class RosterAnalysis:
    """Positional analysis of a roster."""

    roster_size: int
    by_position: dict[str, list[PlayerAsset]]
    surplus_positions: list[str]
    need_positions: list[str]
    starter_counts: dict[str, int]  # above-replacement count
    depth_counts: dict[str, int]  # below-replacement count
    #: The same rooms with C3-CON-01-constrained assets removed.
    #:
    #: A SECOND view rather than a filtered ``by_position``, and the distinction
    #: is load-bearing.  A protected player still occupies a roster spot and
    #: still counts toward positional depth: dropping him from the ANALYSIS
    #: would make the team look thinner than it is, move it into
    #: ``need_positions`` it does not need, and change what every generator
    #: thinks it should go and get.  He is excluded from what we may OFFER, and
    #: from nothing else — which is §2.2 stated as a data shape.
    sendable_by_position: dict[str, list[PlayerAsset]] = field(default_factory=dict)
    #: Lowercased names of the assets we may send, for the per-asset checks
    #: that cannot draw from a room (``weakest_starter``, sweeteners).
    sendable_keys: frozenset[str] = frozenset()
    #: ``[(asset, reason), ...]`` — why the sendable view is shorter.
    constrained_out: tuple[tuple[PlayerAsset, str], ...] = ()
    #: Whether a constraint set was consulted at all.  "Nothing is protected"
    #: and "nobody asked" are different claims and this keeps them apart.
    constraints_applied: bool = False
    #: The starter-demand model this analysis was computed with (W30-F006 /
    #: V1-25).  ``analyze_roster`` stores the LEAGUE'S resolved needs here so
    #: every downstream consumer — the four generators, ``rank_score``, the
    #: balancer-candidate picker — reads the same lineup the rooms were split
    #: with.  ``DEFAULT_STARTER_NEEDS`` (dynasty_main's demand) is the
    #: FALLBACK default only: reading the module constant directly inside a
    #: generator is the hardcode that told the 1-TE league to keep its TE2.
    starter_needs: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_STARTER_NEEDS))

    def __post_init__(self) -> None:
        """An analysis built without constraints has consulted none.

        The sendable view then MIRRORS the full rooms, and that default is
        deliberate rather than convenient.  Defaulting the other way — empty,
        so nothing is sendable — reads as fail-closed and is not: it silently
        returns zero suggestions for any caller that constructs this dataclass
        directly, which is a shorter list with no explanation, the failure §4
        forbids.  Fail-closed belongs at the OWNER, where ``UNRESOLVED``
        expresses "we could not check"; this object cannot tell the difference
        and must not pretend to.  ``constraints_applied`` records which
        happened, and ``analyze_roster`` — the only production constructor —
        always supplies the real answer.
        """
        if not self.constraints_applied and not self.sendable_by_position:
            object.__setattr__(self, "sendable_by_position", dict(self.by_position))
            object.__setattr__(
                self,
                "sendable_keys",
                frozenset(
                    _identity_key(p.name) for room in self.by_position.values() for p in room
                ),
            )

    def sendable(self, position: str) -> list[PlayerAsset]:
        """The room's assets we may put on the outgoing side."""
        return self.sendable_by_position.get(position, [])

    def can_send(self, asset: PlayerAsset) -> bool:
        return _identity_key(asset.name) in self.sendable_keys


@dataclass
class TradeSuggestion:
    """A single trade suggestion."""

    type: str  # "sell_high", "buy_low", "consolidation", "positional_upgrade"
    give: list[PlayerAsset]
    receive: list[PlayerAsset]
    give_total: int  # display value
    receive_total: int
    gap: int
    fairness: str  # "even", "lean", "stretch"
    rationale: str
    why_this_helps: str
    confidence: str  # "high", "medium", "low"
    strategy: str  # "contender", "rebuilder", "neutral"


# ── Market-disagreement helpers ──────────────────────────────────────


def _compute_cv(values: list[float]) -> float | None:
    """Coefficient of variation: std / mean. None if < 2 values or mean is 0."""
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    if mean <= 0:
        return None
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(var) / mean


def _edge_for_suggestion(s: TradeSuggestion) -> tuple[str | None, str | None]:
    """Determine if a suggestion has a market edge signal.

    Returns (edge_type, explanation) or (None, None).
    Edge types: "market_discount", "market_premium", "high_dispersion"
    """
    give_cvs = [p.dispersion_cv for p in s.give if p.dispersion_cv is not None]
    recv_cvs = [p.dispersion_cv for p in s.receive if p.dispersion_cv is not None]

    # High dispersion on the receive side = potential buy-low (market hasn't settled)
    if recv_cvs and max(recv_cvs) >= HIGH_DISPERSION_CV:
        target = max(s.receive, key=lambda p: p.dispersion_cv or 0)
        if s.gap < 0:  # I'm getting more value than I'm giving
            return (
                "market_discount",
                f"Sources disagree on {target.name} (CV {target.dispersion_cv:.0%}) — "
                f"potential buy-low if the higher sources are right.",
            )
        return (
            "high_dispersion",
            f"Sources disagree on {target.name} (CV {target.dispersion_cv:.0%}) — "
            f"value is less certain than usual.",
        )

    # Low dispersion on what I'm giving, high on what I'm getting
    if give_cvs and recv_cvs:
        give_avg_cv = sum(give_cvs) / len(give_cvs)
        recv_avg_cv = sum(recv_cvs) / len(recv_cvs)
        if give_avg_cv <= LOW_DISPERSION_CV and recv_avg_cv >= HIGH_DISPERSION_CV * 0.8:
            return (
                "market_premium",
                "You're moving a consensus-stable asset for one where sources disagree — "
                "your side has lower pricing risk.",
            )

    # High dispersion on what I'm giving = potential sell-high
    if give_cvs and max(give_cvs) >= HIGH_DISPERSION_CV:
        seller = max(s.give, key=lambda p: p.dispersion_cv or 0)
        if s.gap > 0:
            return (
                "market_premium",
                f"Sources disagree on {seller.name} (CV {seller.dispersion_cv:.0%}) — "
                f"selling before the market corrects down could be smart.",
            )

    return (None, None)


# ── Core engine ──────────────────────────────────────────────────────
# ``_norm_pos`` is now imported from ``src.utils.name_clean`` (audit
# S2); callers that previously relied on the local ``str`` signature
# get the same behavior plus null-tolerance — strict callers who pass
# a non-empty string see no change.


def build_asset_pool(
    asset_dict_payload: dict[str, Any],
    *,
    board_top_n: int | None = None,
    ktc_top_n: int | None = None,
) -> list[PlayerAsset]:
    """Convert an asset-dict payload into ``PlayerAsset`` objects.

    Retained as a thin back-compat entry point for tests and tooling
    that still pass payloads shaped like ``{"assets": [...]}``.
    Production ``/api/trade/suggestions`` uses
    :func:`build_asset_pool_from_contract` instead; see its docstring
    for the field mapping from the live ``playersArray`` contract.

    Args:
        asset_dict_payload: Dict with an ``assets`` list where each
            entry has ``display_name``, ``calibrated_value``,
            ``display_value`` (optional), ``metadata`` (position/team/
            rookie/years_exp), ``source_values``, and ``universe``.
        board_top_n: Only include players ranked inside the top N of
            our blended board. Set to 0 to disable the filter.
        ktc_top_n: Deprecated alias for ``board_top_n`` — this gate
            never consulted KTC (WS-J F-4).
    """
    if board_top_n is None:
        board_top_n = BOARD_TOP_N_FILTER if ktc_top_n is None else ktc_top_n
    assets = asset_dict_payload.get("assets", [])
    pool: list[PlayerAsset] = []
    for a in assets:
        name = str(a.get("display_name", "")).strip()
        if not name:
            continue
        cv = a.get("calibrated_value")
        dv = a.get("display_value")
        if cv is None:
            continue
        if dv is None:
            dv = to_display_value(cv)
        meta = a.get("metadata", {}) or {}
        pos = _norm_pos(str(meta.get("position", "") or ""))

        # Compute source dispersion CV
        source_values = a.get("source_values", {})
        sv_list = (
            [float(v) for v in source_values.values() if v is not None]
            if isinstance(source_values, dict)
            else []
        )
        dispersion = _compute_cv(sv_list)

        pool.append(
            PlayerAsset(
                name=name,
                position=pos,
                display_value=int(dv),
                calibrated_value=int(cv),
                source_count=len(sv_list),
                team=str(meta.get("team", "") or ""),
                rookie=bool(meta.get("rookie", False)),
                years_exp=meta.get("years_exp"),
                universe=str(a.get("universe", "")),
                dispersion_cv=round(dispersion, 4) if dispersion is not None else None,
            )
        )
    pool.sort(key=lambda x: -x.display_value)

    # ── Compute blended-board rank and apply the top-N filter ──────
    pool = _assign_board_ranks(pool)
    if board_top_n > 0:
        pool = _apply_board_top_n_filter(pool, board_top_n)

    return pool


# ──────────────────────────────────────────────────────────────────────
# Contract-native asset pool
# ──────────────────────────────────────────────────────────────────────


def _universe_from_row(row: dict[str, Any]) -> str:
    """Derive the asset's universe label from the live contract row.

    Matches the labels the legacy canonical snapshot used so downstream
    consumers (roster analysis, suggestion categories) see the same
    universe strings.
    """
    if row.get("assetClass") == "pick":
        return "picks"
    pos = _norm_pos(str(row.get("position") or ""))
    is_rookie = bool(row.get("rookie"))
    if pos in {"DL", "LB", "DB"}:
        return "idp_rookie" if is_rookie else "idp_vet"
    return "offense_rookie" if is_rookie else "offense_vet"


def _effective_source_keys(
    row: dict[str, Any],
    site_values: dict[str, Any],
) -> set[str] | None:
    """Return the post-Hampel source-key allowlist for ``row``.

    Resolution order:

    1. ``effectiveSourceRanks`` — the canonical post-Hampel rank map the
       live contract stamps (the same set marketGapDirection /
       confidenceBucket / anomaly flags are computed from).
    2. ``canonicalSiteValues`` keys minus ``droppedSources`` — a
       transitional fallback for contracts that carry the dropped list
       but no effective-rank map.
    3. ``None`` — legacy contracts without any Hampel stamps; caller
       should use every key in ``canonicalSiteValues``.
    """
    effective_ranks = row.get("effectiveSourceRanks")
    if isinstance(effective_ranks, dict) and effective_ranks:
        return set(effective_ranks.keys())
    dropped = row.get("droppedSources")
    if isinstance(dropped, list) and dropped and isinstance(site_values, dict):
        return set(site_values.keys()) - set(dropped)
    return None


def build_asset_pool_from_contract(
    contract: dict[str, Any],
    *,
    board_top_n: int | None = None,
    ktc_top_n: int | None = None,
) -> list[PlayerAsset]:
    """Primary pool builder — maps the live contract ``playersArray``
    to ``PlayerAsset`` objects for the trade-suggestion engine.

    Called by ``/api/trade/suggestions`` with the live
    ``latest_contract_data`` so suggestions sort + fairness-check on
    the same calibrated values the public ``/api/data`` contract
    serves.  Emits the same ``PlayerAsset`` shape as the legacy
    asset-dict path (see :func:`build_asset_pool`) so downstream
    consumers (roster analysis, sell/buy categories, balancer search)
    are unchanged.

    Mapping:

    =========================   ==================================================
    ``PlayerAsset`` field       Source in ``contract``
    =========================   ==================================================
    ``name``                    ``row["canonicalName"]``
    ``position``                ``row["position"]`` (normalised)
    ``display_value``           ``row["rankDerivedValue"]``
    ``calibrated_value``        same (live values are already calibrated)
    ``source_count``            post-Hampel effective source count (see below)
    ``team``                    ``row["team"]``
    ``rookie``                  ``row["rookie"]``
    ``years_exp``               ``contract["players"][legacyRef]["_yearsExp"]``
    ``universe``                derived from ``assetClass`` + position + rookie
    ``dispersion_cv``           CV of post-Hampel ``canonicalSiteValues`` (values > 0)
    =========================   ==================================================

    Only rows with a positive ``rankDerivedValue`` are included; rows
    that fell off the Phase 4 ``OVERALL_RANK_LIMIT`` cap or that have
    no calibrated value are filtered out, matching the canonical-
    snapshot filter that required ``calibrated_value`` to be present.

    Per-source reads respect the Hampel filter the live contract
    applies at ingest.  ``effectiveSourceRanks`` is the canonical
    post-Hampel rank map; ``droppedSources`` lists the source keys
    Hampel rejected as outliers.  Both ``source_count`` and
    ``dispersion_cv`` are computed from the *effective* subset so
    suggestion confidence tiers and market-edge signals see the same
    readings ``marketGapDirection`` and ``confidenceBucket`` do.
    Legacy contracts without Hampel stamps fall back to the raw
    ``canonicalSiteValues`` set.

    ``board_top_n`` gates on our blended board; ``ktc_top_n`` is a
    deprecated alias, since this gate never consulted KTC (WS-J F-4).
    """
    if board_top_n is None:
        board_top_n = BOARD_TOP_N_FILTER if ktc_top_n is None else ktc_top_n
    players_array = contract.get("playersArray") or []
    legacy_players = contract.get("players") or {}

    pool: list[PlayerAsset] = []
    for row in players_array:
        name = str(row.get("canonicalName") or row.get("displayName") or "").strip()
        if not name:
            continue
        # Every row reads the consensus rankDerivedValue.  The former
        # ``apply_scoring_fit`` toggle read ``idpScoringFitAdjustedValue``
        # here, but NO code path ever produced that field (2026-07-25
        # calculation audit, finding F-1) — the toggle was a silent
        # no-op and has been removed rather than left as a dead
        # promise.  If league-scoring fit is ever wired for real, the
        # producer belongs in the contract build, not here.
        cv: Any = row.get("rankDerivedValue")
        if cv is None:
            continue
        try:
            cv_int = int(cv)
        except (TypeError, ValueError):
            continue
        if cv_int <= 0:
            continue

        pos = _norm_pos(str(row.get("position") or ""))
        team = str(row.get("team") or "")

        # Source values for dispersion CV + source_count.  Prefer the
        # post-Hampel effective source set so the engine's confidence
        # tier and market-edge signals match marketGapDirection /
        # confidenceBucket (which the contract computes from the same
        # filtered set).  Fall back to the raw site-values keys for
        # legacy contracts that pre-date the Hampel stamps.
        #
        # Per-source magnitude: prefer ``sourceRankMeta[key]
        # .valueContribution`` — the 9,999-scale value that actually
        # enters the blend — over the raw ``canonicalSiteValues`` slot.
        # Rank-signal sources (DLF, Dynasty Daddy, Yahoo Boone, FC/OTC
        # since PR #530, ...) stamp a synthetic rank ENCODING
        # (``999900 - rank*100`` bookkeeping numbers) into
        # canonicalSiteValues; mixing those with native 0-9999 values
        # made the CV read scale mismatch as source disagreement and
        # could hang false ``high_dispersion`` edges on suggestions.
        # Raw slots remain the fallback for legacy contracts without
        # the meta stamp (their value-based slots are true values).
        site_values = row.get("canonicalSiteValues") or {}
        source_meta = row.get("sourceRankMeta")
        if not isinstance(source_meta, dict):
            source_meta = {}
        effective_keys = _effective_source_keys(row, site_values)
        sv_list: list[float] = []
        if isinstance(site_values, dict):
            for key, v in site_values.items():
                if effective_keys is not None and key not in effective_keys:
                    continue
                meta = source_meta.get(key)
                contrib = meta.get("valueContribution") if isinstance(meta, dict) else None
                candidate = contrib if isinstance(contrib, (int, float)) and contrib > 0 else v
                try:
                    f = float(candidate) if candidate is not None else 0.0
                except (TypeError, ValueError):
                    continue
                if f > 0:
                    sv_list.append(f)
        dispersion = _compute_cv(sv_list)

        # years_exp lives on the legacy players dict, not on the
        # playersArray row.  Look it up via the row's legacyRef.
        years_exp: int | None = None
        legacy_ref = row.get("legacyRef") or name
        legacy_entry = legacy_players.get(legacy_ref)
        if isinstance(legacy_entry, dict):
            raw_yrs = legacy_entry.get("_yearsExp")
            if raw_yrs is not None:
                try:
                    years_exp = int(raw_yrs)
                except (TypeError, ValueError):
                    years_exp = None

        pool.append(
            PlayerAsset(
                name=name,
                position=pos,
                display_value=cv_int,
                calibrated_value=cv_int,
                source_count=len(sv_list),
                team=team,
                rookie=bool(row.get("rookie")),
                years_exp=years_exp,
                universe=_universe_from_row(row),
                dispersion_cv=round(dispersion, 4) if dispersion is not None else None,
            )
        )
    pool.sort(key=lambda x: -x.display_value)

    # ── Compute blended-board rank and apply the top-N filter ──────
    pool = _assign_board_ranks(pool)
    if board_top_n > 0:
        pool = _apply_board_top_n_filter(pool, board_top_n)

    return pool


def _assign_board_ranks(pool: list[PlayerAsset]) -> list[PlayerAsset]:
    """Assign each player its 1-based rank on OUR blended board.

    The caller sorts ``pool`` by ``display_value`` descending before
    calling this, so rank ``i + 1`` IS the blended-board rank.  Every
    player receives a rank; there is no null case.

    WS-J F-4: this used to be ``_assign_ktc_ranks`` and claimed to rank
    by KTC value, with players lacking KTC coverage getting ``None``.
    Neither was true — no KTC value was read and no player ever got
    ``None``.  Renamed to describe what it actually computes.
    """
    for i, p in enumerate(pool):
        p.board_rank = i + 1
    return pool


# Deprecated alias.
_assign_ktc_ranks = _assign_board_ranks


def _apply_board_top_n_filter(
    pool: list[PlayerAsset],
    top_n: int,
) -> list[PlayerAsset]:
    """Remove players ranked outside the top N of our blended board.

    This is a hard quality filter — not a soft preference.  Players
    outside the threshold are excluded from suggestions as primary
    targets, secondary targets, value fillers, and throw-ins.

    Precondition: ``pool`` has been through :func:`_assign_board_ranks`,
    so every player carries an int rank.  Passing an unranked pool is a
    caller bug and raises ``TypeError`` rather than silently filtering
    everything out.

    WS-J F-5: the predicate used to be
    ``p.ktc_rank is not None and p.ktc_rank <= top_n``.  The null check
    could never be False — ``_assign_board_ranks`` assigns an int to
    every player — so it was a vacuous guard implying a null case that
    does not exist, and it would have turned a caller bug into an
    empty result set.  Dropped in favour of the stated precondition.
    """
    return [p for p in pool if p.board_rank <= top_n]  # type: ignore[operator]


# Deprecated alias.
_apply_ktc_top_n_filter = _apply_board_top_n_filter


def analyze_roster(
    roster_names: list[str],
    asset_pool: list[PlayerAsset],
    starter_needs: dict[str, int] | None = None,
    *,
    constraints: Any | None = None,
) -> RosterAnalysis:
    """Analyze a roster for positional surplus and need.

    ``constraints`` (``src.trade.constraints.TradeConstraints``) is resolved
    into ``sendable_by_position`` and changes NOTHING else about the analysis.
    A protected player is still counted, still fills a starting slot and still
    makes his position a surplus — he is only withheld from what we may offer.
    """
    needs = starter_needs or DEFAULT_STARTER_NEEDS

    pool_by_name: dict[str, PlayerAsset] = {}
    for a in asset_pool:
        key = _identity_key(a.name)
        if key not in pool_by_name or a.display_value > pool_by_name[key].display_value:
            pool_by_name[key] = a

    by_position: dict[str, list[PlayerAsset]] = {}
    matched = 0
    for rn in roster_names:
        key = _identity_key(rn)
        a = pool_by_name.get(key)
        if a is None:
            continue
        matched += 1
        by_position.setdefault(a.position, []).append(a)

    for pos in by_position:
        by_position[pos].sort(key=lambda x: -x.display_value)

    surplus_positions: list[str] = []
    need_positions: list[str] = []
    starter_counts: dict[str, int] = {}
    depth_counts: dict[str, int] = {}

    for pos, need in needs.items():
        players = by_position.get(pos, [])
        relevant = [p for p in players if p.display_value >= MIN_RELEVANT_VALUE]
        starters = relevant[:need]
        depth = relevant[need:]
        starter_counts[pos] = len(starters)
        depth_counts[pos] = len(depth)
        if len(starters) < need:
            need_positions.append(pos)
        if len(depth) >= 2:
            surplus_positions.append(pos)

    # C3-CON-01, resolved ONCE for the whole module.  Every generator draws
    # its outgoing candidates from the sendable view, so there is one call to
    # the owner rather than one per generator — §2.3 forbids page-local copies,
    # and five copies inside one file is still five.
    from src.trade.constraints import blocked_outgoing  # noqa: PLC0415

    everyone = [p for room in by_position.values() for p in room]
    blocked = blocked_outgoing(everyone, constraints)
    blocked_names = {_identity_key(a.name) for a, _r in blocked}
    sendable_by_position = {
        pos: [p for p in room if _identity_key(p.name) not in blocked_names]
        for pos, room in by_position.items()
    }
    sendable_keys = frozenset(
        _identity_key(p.name) for room in sendable_by_position.values() for p in room
    )

    return RosterAnalysis(
        roster_size=matched,
        by_position=by_position,
        surplus_positions=surplus_positions,
        need_positions=need_positions,
        starter_counts=starter_counts,
        depth_counts=depth_counts,
        sendable_by_position=sendable_by_position,
        sendable_keys=sendable_keys,
        constrained_out=tuple(blocked),
        constraints_applied=True,
        starter_needs=dict(needs),
    )


def _trade_is_idp_free(give: list[PlayerAsset], receive: list[PlayerAsset]) -> bool:
    """Whether a proposed trade contains no IDP asset.

    A UNIVERSE predicate only.  It decides which assets are eligible to
    be offered — see the consolidation search, which will not offer an
    IDP target into an all-offense pair.  It must never decide what an
    asset is WORTH: ``_eff_val`` used to consult it and return a second,
    IDP-disabled board value instead of ``display_value``, which made
    one player worth two different numbers in one league on one day
    (W29-F001).
    """
    return all(p.position not in _IDP_BASE_POSITIONS for p in [*give, *receive])


def _va_gap(give_vals: list[int], recv_vals: list[int]) -> int:
    """Trade gap after KTC's Value Adjustment.

    The trade analyzer applies KTC's VA before computing its
    "Major gap" verdict (frontend/lib/trade-logic.js, backed by the
    same src.trade.ktc_va port).  Suggestions must use the identical
    math or they propose packages that look even on raw totals but
    show a major gap once loaded into the builder — e.g. 2-for-1
    consolidations where KTC's quantity discount inflates the
    single-stud side.  Callers MUST pass the individual piece values
    (not a pre-summed total) so the per-piece discount actually
    triggers; for genuine 1-for-1s KTC suppresses VA, so the result
    equals the raw difference.
    """
    give_adj, recv_adj, _, _ = adjusted_pair_totals(give_vals, recv_vals)
    return int(round(give_adj - recv_adj))


def _fairness_label(gap: int) -> str:
    a = abs(gap)
    if a < 256:
        return "even"
    if a < 769:
        return "lean"
    return "stretch"


def _strategy_for_player(player: PlayerAsset) -> str:
    if player.rookie or (player.years_exp is not None and player.years_exp <= 2):
        return "rebuilder"
    if player.years_exp is not None and player.years_exp >= 8:
        return "contender"
    return "neutral"


def _confidence_from_sources(source_count: int) -> str:
    if source_count >= 6:
        return "high"
    if source_count >= 3:
        return "medium"
    return "low"


# ── Ranking score ────────────────────────────────────────────────────
#
# Formula (deterministic, additive, all terms visible):
#
#   rank_score = base_value
#              + fairness_bonus
#              + confidence_bonus
#              + need_severity_bonus
#              + edge_bonus
#              + opponent_fit_bonus
#
# base_value:         min(give_total, receive_total) / 1000
#                     Normalizes to ~1–10 range.  Bigger trades score higher,
#                     but this is only one factor.
#
# fairness_bonus:     +3 (even)  |  +1 (lean)  |  0 (stretch)
#                     Even trades are far more actionable.
#
# confidence_bonus:   +2 (high)  |  +1 (medium)  |  0 (low)
#                     High source consensus = more trustworthy suggestion.
#
# need_severity_bonus: +2 if the receive position has 0 starters on roster
#                      +1 if below starter threshold
#                      Filling a gaping hole > marginal depth swap.
#
# edge_bonus:         +1.5 (market_discount)  |  +1 (market_premium)  |
#                     +0.5 (high_dispersion)
#                     Market disagreement that favors the user.
#
# opponent_fit_bonus: +1.5 if opponent_fit text present
#                     A real trade partner exists.
#
# Tiebreaker: abs(gap) ascending (tighter trades first), then alphabetical
# give-side name for full determinism.

_FAIRNESS_RANK_BONUS = {"even": 3.0, "lean": 1.0, "stretch": 0.0}
_CONFIDENCE_RANK_BONUS = {"high": 2.0, "medium": 1.0, "low": 0.0}
_EDGE_RANK_BONUS = {"market_discount": 1.5, "market_premium": 1.0, "high_dispersion": 0.5}


def rank_score(
    s: TradeSuggestion,
    roster: RosterAnalysis | None = None,
) -> float:
    """Compute an explainable ranking score for a suggestion.

    Higher = better.  Deterministic for identical inputs.
    """
    # 1. Base value: normalized trade magnitude
    base = min(s.give_total, s.receive_total) / 1000.0

    # 2. Fairness bonus
    fair = _FAIRNESS_RANK_BONUS.get(s.fairness, 0.0)

    # 3. Confidence bonus
    conf = _CONFIDENCE_RANK_BONUS.get(s.confidence, 0.0)

    # 4. Need severity bonus
    need_sev = 0.0
    if roster is not None:
        for p in s.receive:
            if p.position in roster.need_positions:
                starter_ct = roster.starter_counts.get(p.position, 0)
                needed = roster.starter_needs.get(p.position, 1)
                if starter_ct == 0:
                    need_sev = max(need_sev, 2.0)
                elif starter_ct < needed:
                    need_sev = max(need_sev, 1.0)

    # 5. Edge bonus (from __dict__ annotation set post-construction)
    edge = s.__dict__.get("edge")
    edge_b = _EDGE_RANK_BONUS.get(edge, 0.0) if edge else 0.0

    # 6. Opponent-fit bonus
    opp_fit = 1.5 if s.__dict__.get("opponent_fit") else 0.0

    # 7. Roster-fit penalty: receiving an asset at a saturated position
    # is bench bloat in dynasty, even if equity is positive.  Mirrors
    # the team_impact module's overflow penalty in the trade simulator.
    overflow_penalty = 0.0
    if roster is not None:
        for p in s.receive:
            if p.position in roster.surplus_positions:
                overflow_penalty += 1.0

    return base + fair + conf + need_sev + edge_b + opp_fit - overflow_penalty


def rank_score_breakdown(
    s: TradeSuggestion,
    roster: RosterAnalysis | None = None,
) -> dict[str, float]:
    """Return the individual components of rank_score for debugging."""
    base = min(s.give_total, s.receive_total) / 1000.0
    fair = _FAIRNESS_RANK_BONUS.get(s.fairness, 0.0)
    conf = _CONFIDENCE_RANK_BONUS.get(s.confidence, 0.0)

    need_sev = 0.0
    if roster is not None:
        for p in s.receive:
            if p.position in roster.need_positions:
                starter_ct = roster.starter_counts.get(p.position, 0)
                needed = roster.starter_needs.get(p.position, 1)
                if starter_ct == 0:
                    need_sev = max(need_sev, 2.0)
                elif starter_ct < needed:
                    need_sev = max(need_sev, 1.0)

    edge = s.__dict__.get("edge")
    edge_b = _EDGE_RANK_BONUS.get(edge, 0.0) if edge else 0.0
    opp_fit = 1.5 if s.__dict__.get("opponent_fit") else 0.0

    overflow_penalty = 0.0
    if roster is not None:
        for p in s.receive:
            if p.position in roster.surplus_positions:
                overflow_penalty += 1.0

    return {
        "base_value": round(base, 2),
        "fairness": round(fair, 2),
        "confidence": round(conf, 2),
        "need_severity": round(need_sev, 2),
        "edge": round(edge_b, 2),
        "opponent_fit": round(opp_fit, 2),
        "overflow_penalty": round(-overflow_penalty, 2),
        "total": round(base + fair + conf + need_sev + edge_b + opp_fit - overflow_penalty, 2),
    }


def _rank_sort_key(s: TradeSuggestion, roster: RosterAnalysis | None = None):
    """Sort key: higher score first, then tighter gap, then alphabetical."""
    score = rank_score(s, roster)
    # Negate score for descending; abs(gap) ascending; alphabetical give name
    give_name = s.give[0].name if s.give else ""
    return (-score, abs(s.gap), give_name)


# ── Opponent-aware helpers ───────────────────────────────────────────


def _analyze_opponent_rosters(
    league_rosters: list[dict[str, Any]],
    asset_pool: list[PlayerAsset],
) -> dict[str, RosterAnalysis]:
    """Analyze all opponent rosters for need/surplus."""
    result: dict[str, RosterAnalysis] = {}
    for roster_entry in league_rosters:
        team_name = str(roster_entry.get("team_name", roster_entry.get("owner", ""))).strip()
        if not team_name:
            continue
        players = roster_entry.get("players", [])
        if not isinstance(players, list) or not players:
            continue
        analysis = analyze_roster(players, asset_pool)
        result[team_name] = analysis
    return result


def _opponent_fit_label(
    suggestion: TradeSuggestion,
    opponent_analyses: dict[str, RosterAnalysis],
) -> str | None:
    """Find which opponents would benefit from the player I'm giving away.

    Returns a human-readable fit description or None.
    """
    give_positions = {p.position for p in suggestion.give}
    receive_positions = {p.position for p in suggestion.receive}

    fitting_teams: list[str] = []
    for team_name, analysis in opponent_analyses.items():
        # Opponent needs what I'm giving
        opp_needs_my_give = any(pos in analysis.need_positions for pos in give_positions)
        # Opponent has surplus at what I'm receiving (they can afford to trade it)
        opp_surplus_my_recv = any(pos in analysis.surplus_positions for pos in receive_positions)

        if opp_needs_my_give and opp_surplus_my_recv:
            fitting_teams.append(team_name)
        elif opp_needs_my_give:
            fitting_teams.append(team_name)

    if not fitting_teams:
        return None
    if len(fitting_teams) == 1:
        # sorted(): ``give_positions`` is a set, and joining a set puts the
        # process's hash seed into an API response — measured: four distinct
        # labels for one suggestion across PYTHONHASHSEED 0/1/7/42.
        return (
            f"Strong bilateral fit: {fitting_teams[0]} needs "
            f"{', '.join(sorted(give_positions))} and could deal."
        )
    return f"Potential trade partners ({len(fitting_teams)}): {', '.join(fitting_teams[:3])}"


# ── Suggestion generators ───────────────────────────────────────────


def _generate_sell_high(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    suggestions: list[TradeSuggestion] = []

    for pos in roster.surplus_positions:
        players = roster.by_position.get(pos, [])
        if len(players) < 2:
            continue
        need = roster.starter_needs.get(pos, 1)
        # Depth is measured on the FULL room (a protected player is still
        # depth); the candidates we may offer come from the sendable view.
        sell_candidates = [
            p
            for p in players[need:]
            if p.display_value >= MIN_RELEVANT_VALUE and roster.can_send(p)
        ]
        if not sell_candidates:
            continue

        for sell in sell_candidates[:3]:
            for need_pos in roster.need_positions:
                sell_ev = sell.display_value
                targets = [
                    a
                    for a in asset_pool
                    if a.position == need_pos
                    and _identity_key(a.name) not in roster_names_set
                    and a.display_value >= MIN_RELEVANT_VALUE
                    and abs(a.display_value - sell_ev) < FAIRNESS_TOLERANCE
                ]
                if not targets:
                    continue
                targets.sort(key=lambda t: abs(t.display_value - sell_ev))
                target = targets[0]
                give_val = sell.display_value
                recv_val = target.display_value
                gap = _va_gap([give_val], [recv_val])
                suggestions.append(
                    TradeSuggestion(
                        type="sell_high",
                        give=[sell],
                        receive=[target],
                        give_total=give_val,
                        receive_total=recv_val,
                        gap=gap,
                        fairness=_fairness_label(gap),
                        rationale=f"You have {pos} surplus ({len(players)} rostered, need {need}). "
                        f"Move {sell.name} for a {need_pos} upgrade.",
                        why_this_helps=f"Converts {pos} depth into a {need_pos} you actually need.",
                        confidence=_confidence_from_sources(
                            min(sell.source_count, target.source_count)
                        ),
                        strategy=_strategy_for_player(sell),
                    )
                )

    # Preliminary sort by value; final ranking applied in generate_suggestions()
    suggestions.sort(key=lambda s: -min(s.give_total, s.receive_total))
    return suggestions


def _generate_buy_low(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    suggestions: list[TradeSuggestion] = []

    for need_pos in roster.need_positions:
        # Pre-compute target-side oo from need_pos so candidate gating
        # uses the same value scale as the final gap calculation.
        current = roster.by_position.get(need_pos, [])
        current_best = current[0].display_value if current else 0
        target_floor = max(MIN_RELEVANT_VALUE, current_best)

        targets = [
            a
            for a in asset_pool
            if a.position == need_pos
            and _identity_key(a.name) not in roster_names_set
            and a.display_value > target_floor
        ]
        if not targets:
            continue

        for target in targets[:5]:
            for surplus_pos in roster.surplus_positions:
                depth = roster.by_position.get(surplus_pos, [])
                need = roster.starter_needs.get(surplus_pos, 1)
                tradeable = [
                    p
                    for p in depth[need:]
                    if p.display_value >= MIN_RELEVANT_VALUE and roster.can_send(p)
                ]
                for sell in tradeable[:2]:
                    give_val = sell.display_value
                    recv_val = target.display_value
                    gap = _va_gap([give_val], [recv_val])
                    if abs(gap) < FAIRNESS_TOLERANCE:
                        suggestions.append(
                            TradeSuggestion(
                                type="buy_low",
                                give=[sell],
                                receive=[target],
                                give_total=give_val,
                                receive_total=recv_val,
                                gap=gap,
                                fairness=_fairness_label(gap),
                                rationale=f"Target {target.name} ({need_pos}) fills your roster need. "
                                f"You can afford to trade {sell.name} from {surplus_pos} surplus.",
                                why_this_helps=f"Adds a starter-caliber {need_pos} without weakening "
                                f"your {surplus_pos} starting lineup.",
                                confidence=_confidence_from_sources(
                                    min(sell.source_count, target.source_count)
                                ),
                                strategy="neutral",
                            )
                        )

    # Deduplicate by receive target (keep tightest gap).
    #
    # The tightest-gap SELECTION RULE is unchanged — only the key it is
    # bucketed by is now the canonical side identity (V1-36) instead of
    # ``s.receive[0].name``, which keyed a side by its first asset alone.
    seen: dict[tuple[str, ...], TradeSuggestion] = {}
    for s in suggestions:
        key = _side_identity(s.receive)
        if key not in seen or abs(s.gap) < abs(seen[key].gap):
            seen[key] = s
    # Preliminary sort by value; final ranking applied in generate_suggestions()
    result = sorted(seen.values(), key=lambda s: -s.receive_total)
    return result


def _generate_consolidation(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    suggestions: list[TradeSuggestion] = []

    tradeable: list[PlayerAsset] = []
    for pos in roster.surplus_positions:
        players = roster.by_position.get(pos, [])
        need = roster.starter_needs.get(pos, 1)
        for p in players[need:]:
            if p.display_value >= MIN_RELEVANT_VALUE and roster.can_send(p):
                tradeable.append(p)

    tradeable.sort(key=lambda x: -x.display_value)
    if len(tradeable) < 2:
        return []

    tried: set[tuple[str, ...]] = set()
    for i in range(min(len(tradeable), 6)):
        for j in range(i + 1, min(len(tradeable), 8)):
            p1, p2 = tradeable[i], tradeable[j]
            # Canonical give-side identity (V1-36).  The retired
            # ``f"{p1.name}|{p2.name}"`` was ORDER-dependent, so it could key
            # one unordered pair two ways; the owner's side key sorts.  The
            # pair-enumeration bounds (6 x 8) and every downstream product
            # rule are untouched.
            pair_key = _side_identity([p1, p2])
            if pair_key in tried:
                continue
            tried.add(pair_key)

            # A UNIVERSE restriction, not a value one.  Its original
            # justification — keeping the target on the same value scale
            # as the give side — died with the offense-only board: there
            # is one scale now, so nothing can flip.  It is kept because
            # dropping it would start offering IDP consolidation targets
            # for all-offense pairs, which is a recommendation-surface
            # product decision and not a B9a correctness fix.  Recorded
            # in the deferred ledger for owner decision.
            pair_is_offense_only = _trade_is_idp_free([p1, p2], [])
            combined = p1.display_value + p2.display_value
            min_target = int(combined * CONSOLIDATION_MIN_UPGRADE_RATIO)
            max_target = combined + FAIRNESS_TOLERANCE
            give_max = max(p1.display_value, p2.display_value)

            for prefer_need in [True, False]:
                targets = [
                    a
                    for a in asset_pool
                    if _identity_key(a.name) not in roster_names_set
                    and min_target <= a.display_value <= max_target
                    and a.display_value > give_max
                    and (not pair_is_offense_only or a.position not in _IDP_BASE_POSITIONS)
                    and (not prefer_need or a.position in roster.need_positions)
                ]
                if not targets:
                    continue
                # Pick the closest-value target (smallest gap) rather than
                # the most expensive one.  This produces fairer packages.
                targets.sort(key=lambda t: abs(combined - t.display_value))
                target = targets[0]
                give_p1, give_p2 = p1.display_value, p2.display_value
                give_total = give_p1 + give_p2
                recv_total = target.display_value
                gap = _va_gap([give_p1, give_p2], [recv_total])
                pos_note = (
                    f" at a position of need ({target.position})"
                    if target.position in roster.need_positions
                    else ""
                )
                suggestions.append(
                    TradeSuggestion(
                        type="consolidation",
                        give=[p1, p2],
                        receive=[target],
                        give_total=give_total,
                        receive_total=recv_total,
                        gap=gap,
                        fairness=_fairness_label(gap),
                        rationale=f"Package {p1.name} + {p2.name} into {target.name}{pos_note}. "
                        f"Turns two depth pieces into one difference-maker.",
                        why_this_helps=f"Upgrades roster quality by condensing {p1.position}/{p2.position} "
                        f"depth into a higher-tier asset.",
                        confidence=_confidence_from_sources(target.source_count),
                        strategy="contender" if target.display_value >= 7000 else "neutral",
                    )
                )
                break

    # Preliminary sort; final ranking applied in generate_suggestions()
    suggestions.sort(key=lambda s: -s.receive_total)
    return suggestions


def _generate_positional_upgrades(
    roster: RosterAnalysis,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
) -> list[TradeSuggestion]:
    suggestions: list[TradeSuggestion] = []

    for pos in roster.starter_needs:
        players = roster.by_position.get(pos, [])
        if len(players) < 2:
            continue
        need = roster.starter_needs.get(pos, 1)
        if need < 1:
            continue

        starters = players[:need]
        depth = [
            p
            for p in players[need:]
            if p.display_value >= MIN_RELEVANT_VALUE and roster.can_send(p)
        ]
        if not starters or not depth:
            continue

        weakest_starter = starters[-1]
        # The weakest starter is identified on the FULL room — that is who he
        # is — and then checked.  Promoting the next-weakest into the role
        # would publish a false claim about the roster to route around a
        # protection; there is simply no upgrade suggestion at this position.
        if not roster.can_send(weakest_starter):
            continue
        ws_ev = weakest_starter.display_value
        upgrade_floor = ws_ev + 500

        targets = [
            a
            for a in asset_pool
            if a.position == pos
            and _identity_key(a.name) not in roster_names_set
            and a.display_value >= upgrade_floor
        ]
        if not targets:
            continue

        targets.sort(key=lambda t: t.display_value)  # closest upgrade first
        for target in targets[:5]:
            gap_needed = target.display_value - ws_ev
            sweeteners = [
                p
                for p in depth
                if p.name != weakest_starter.name
                and abs(p.display_value - gap_needed) < FAIRNESS_TOLERANCE
            ]
            if not sweeteners:
                # Widen tolerance for surplus-position sweeteners — these
                # are expendable depth the user can afford to overpay with.
                surplus_tol = int(FAIRNESS_TOLERANCE * UPGRADE_SWEETENER_SURPLUS_MULTIPLIER)
                for sp in roster.surplus_positions:
                    sp_depth = roster.by_position.get(sp, [])
                    sp_need = roster.starter_needs.get(sp, 1)
                    for p in sp_depth[sp_need:]:
                        sp_ev = p.display_value
                        if sp_ev >= MIN_RELEVANT_VALUE and abs(sp_ev - gap_needed) < surplus_tol:
                            sweeteners.append(p)
            if not sweeteners:
                continue

            sweeteners.sort(key=lambda s: abs(s.display_value - gap_needed))
            sweetener = sweeteners[0]
            give_ws = weakest_starter.display_value
            give_sw = sweetener.display_value
            give_total = give_ws + give_sw
            recv_total = target.display_value
            gap = _va_gap([give_ws, give_sw], [recv_total])

            if abs(gap) > FAIRNESS_TOLERANCE * 1.5:
                continue

            suggestions.append(
                TradeSuggestion(
                    type="positional_upgrade",
                    give=[weakest_starter, sweetener],
                    receive=[target],
                    give_total=give_total,
                    receive_total=recv_total,
                    gap=gap,
                    fairness=_fairness_label(gap),
                    rationale=f"Upgrade {pos} starter: move {weakest_starter.name} + {sweetener.name} "
                    f"for {target.name}.",
                    why_this_helps=f"Replaces your {pos}{need} with a higher-caliber {pos} starter.",
                    confidence=_confidence_from_sources(target.source_count),
                    strategy="contender",
                )
            )

    # Preliminary sort; final ranking applied in generate_suggestions()
    suggestions.sort(key=lambda s: -s.receive_total)
    return suggestions


def _find_balancers(
    suggestion: TradeSuggestion,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
    exclude_names: set[str],
    roster: RosterAnalysis | None = None,
) -> tuple[list[PlayerAsset], str, list[int]]:
    """Find add-ons that actually close a near-there trade's gap.

    Direction-aware:
    - gap < 0 (user underpays): search user's roster for expendable add-ons.
    - gap > 0 (user overpays): search global pool for what opponent could add.

    Returns ``(balancers, side, residual_gaps)`` where ``side`` is
    ``"you_add"`` or ``"they_add"`` and ``residual_gaps[i]`` is the gap
    that would REMAIN after adding ``balancers[i]`` — same sign
    convention as ``suggestion.gap``.

    ──────────────────────────────────────────────────────────────────
    Why this simulates instead of matching a value (defect #800)
    ──────────────────────────────────────────────────────────────────
    ``suggestion.gap`` is :func:`_va_gap` — the gap AFTER KTC's Value
    Adjustment, which is the number the verdict and the trade page both
    show.  This function used to rank candidates by
    ``abs(candidate.display_value - abs(gap))``: a **raw** player value
    matched against an **adjusted** target.

    That arithmetic is only valid if adding a piece worth ``V`` moves
    the adjusted gap by ``V``, and it does not.  VA is a function of
    BOTH sides' complete value arrays, so adding a piece re-runs
    :func:`src.trade.ktc_va.ktc_adjust_package` from scratch — the piece
    count changes, the progressive-nerf ladder shifts, the recipient
    side can flip, and the 1-v-1 / 3.3% display gates snap on or off.

    Measured on the equivalent frontend path over 4,000 synthetic
    two-side trades where a near-even landing WAS reachable from the
    candidate pool: the value-matching rule missed it 43.2% of the time,
    and in 701 of those cases it handed the lead to the other side.

    So every candidate is scored by re-running ``_va_gap`` with the
    candidate added to the side that needs to sweeten, and the ranking
    key is the residual that actually remains.  A candidate that does
    not shrink the gap is not a balancer and is dropped.
    """

    gap = int(suggestion.gap)
    if abs(gap) < 256:
        return ([], "", [])
    side = "you_add" if gap < 0 else "they_add"

    if gap < 0 and roster is not None:
        # User needs to sweeten — search THEIR roster for expendable depth
        candidates = _roster_balancer_candidates(roster, exclude_names)
    else:
        # Opponent needs to sweeten — search global pool
        candidates = _pool_balancer_candidates(
            asset_pool,
            roster_names_set,
            exclude_names,
        )
    if not candidates:
        return ([], side, [])

    give_values = [int(p.display_value) for p in suggestion.give]
    receive_values = [int(p.display_value) for p in suggestion.receive]

    def _residual(candidate: PlayerAsset) -> int:
        """Gap remaining once ``candidate`` joins the sweetening side."""

        value = int(candidate.display_value)
        if side == "you_add":
            return _va_gap([*give_values, value], receive_values)
        return _va_gap(give_values, [*receive_values, value])

    scored: list[tuple[int, PlayerAsset]] = []
    for candidate in candidates:
        residual = _residual(candidate)
        # A "balancer" that leaves the trade no closer than it started
        # is not a balancer.  MISSING IS NEVER ZERO applies here too:
        # an unpriced candidate cannot be shown to close anything, so it
        # never reaches this loop (``display_value`` gates the pools).
        if abs(residual) >= abs(gap):
            continue
        scored.append((residual, candidate))

    if not scored:
        return ([], side, [])

    scored.sort(
        key=lambda item: (
            0 if (roster and item[1].position in roster.surplus_positions) else 1,
            abs(item[0]),
            item[1].name,
        )
    )
    chosen = scored[:MAX_BALANCERS]
    return ([c for _, c in chosen], side, [r for r, _ in chosen])


def _roster_balancer_candidates(
    roster: RosterAnalysis,
    exclude_names: set[str],
) -> list[PlayerAsset]:
    """Expendable depth pieces from the user's roster.

    ELIGIBILITY only — which players it would be reasonable to add.  How
    well any of them closes the gap is :func:`_find_balancers`' question,
    and it is answered by simulation rather than by a value-proximity
    band (defect #800).
    """
    candidates: list[PlayerAsset] = []

    # Prefer surplus-position depth, then any non-starter depth
    for pos in list(roster.surplus_positions) + list(roster.starter_needs.keys()):
        players = roster.by_position.get(pos, [])
        need = roster.starter_needs.get(pos, 1)
        for p in players[need:]:
            # The equalizer is spec §2.3's "trade equalizers / counteroffer
            # suggestions" bullet: it puts a FURTHER outgoing asset into the
            # package after the base suggestion is built, so it is a generating
            # surface in its own right and consumes the same owner.
            if not roster.can_send(p):
                continue
            if (
                _identity_key(p.name) not in exclude_names
                and p.position  # skip positionless
                and p.display_value >= MIN_RELEVANT_VALUE
            ):
                if not any(_identity_key(c.name) == _identity_key(p.name) for c in candidates):
                    candidates.append(p)
    return candidates


def _pool_balancer_candidates(
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
    exclude_names: set[str],
) -> list[PlayerAsset]:
    """Realistic balancer candidates from the global asset pool.

    ELIGIBILITY only — see :func:`_roster_balancer_candidates`.
    """
    return [
        a
        for a in asset_pool
        if _identity_key(a.name) not in roster_names_set
        and _identity_key(a.name) not in exclude_names
        and a.position  # skip positionless / placeholder entries
        and a.display_value >= MIN_RELEVANT_VALUE
    ]


# Maximum balancers to suggest per trade
MAX_BALANCERS = 2


# ── Quality filter ───────────────────────────────────────────────────


def _apply_quality_filters(
    categories: dict[str, list[TradeSuggestion]],
) -> dict[str, list[TradeSuggestion]]:
    """Post-ranking quality pass.  Deterministic, operates on already-ranked lists.

    Filters applied in order:
    1. Per-category: suppress consolidation stretches (fairness == "stretch")
    2. Per-category: cap receive-target repetition
    3. Per-category: cap low-confidence suggestions
    4. Suppress fair-but-weak trades (both sides below MIN_ACTIONABLE_VALUE)
    5. Suppress same-tier swaps (1-for-1 same-position within 500 value)
    6. Suppress near-miss 1-for-1s that need packaging (gap > MAX_GAP_FOR_1FOR1 with balancers)
    7. Cross-category: cap give-player appearances globally

    Each filter preserves the existing rank order — it only removes, never reorders.
    """
    # ── 1. Suppress unrealistic consolidation stretches ────────────
    # Allow stretch consolidations where the VA-adjusted gap is ≤30%
    # of the give total — these are plausible "package for upgrade"
    # deals.  The magnitude is bounded in both directions: a package
    # that lands hugely in the user's favour after VA (a single elite
    # for two depth pieces) is just as unrealistic as a big overpay —
    # no opponent accepts either.
    if "consolidation" in categories:
        categories["consolidation"] = [
            s
            for s in categories["consolidation"]
            if s.fairness != "stretch"
            or (s.give_total > 0 and abs(s.gap) / s.give_total <= CONSOLIDATION_MAX_OVERPAY_RATIO)
        ]

    # ── 2. Cap receive-target repetition per category ────────────────
    for cat_name, suggs in categories.items():
        recv_counts: dict[tuple[str, ...], int] = {}
        filtered: list[TradeSuggestion] = []
        for s in suggs:
            # Canonical receive-side identity (V1-36); the cap itself
            # (MAX_RECEIVE_TARGET_PER_CATEGORY) is unchanged.
            recv_key = _side_identity(s.receive)
            recv_counts[recv_key] = recv_counts.get(recv_key, 0) + 1
            if recv_counts[recv_key] <= MAX_RECEIVE_TARGET_PER_CATEGORY:
                filtered.append(s)
        categories[cat_name] = filtered

    # ── 3. Cap low-confidence suggestions per category ───────────────
    for cat_name, suggs in categories.items():
        low_count = 0
        filtered = []
        for s in suggs:
            if s.confidence == "low":
                low_count += 1
                if low_count > MAX_LOW_CONFIDENCE_PER_CATEGORY:
                    continue
            filtered.append(s)
        categories[cat_name] = filtered

    # ── 4. Suppress fair-but-weak trades ─────────────────────────────
    # Both sides below MIN_ACTIONABLE_VALUE = not worth the conversation.
    for cat_name, suggs in categories.items():
        categories[cat_name] = [
            s
            for s in suggs
            if not all(p.display_value < MIN_ACTIONABLE_VALUE for p in s.give + s.receive)
        ]

    # ── 5. Suppress same-tier swaps ──────────────────────────────────
    # 1-for-1 trades at the same position within 500 display value
    # offer no strategic benefit — just lateral movement.
    for cat_name, suggs in categories.items():
        categories[cat_name] = [
            s
            for s in suggs
            if not (
                len(s.give) == 1
                and len(s.receive) == 1
                and s.give[0].position == s.receive[0].position
                and abs(s.give[0].display_value - s.receive[0].display_value) < 500
            )
        ]

    # ── 6. Suppress near-miss 1-for-1s that need packaging ──────────
    # If the engine attached balancers and gap > MAX_GAP_FOR_1FOR1,
    # the suggestion is really a package deal.  Showing it as a 1-for-1
    # is misleading.
    for cat_name, suggs in categories.items():
        categories[cat_name] = [
            s
            for s in suggs
            if not (
                len(s.give) == 1
                and len(s.receive) == 1
                and abs(s.gap) > MAX_GAP_FOR_1FOR1
                and s.__dict__.get("balancers")
            )
        ]

    # ── 7. Cross-category give-player cap ────────────────────────────
    # Two separate budgets:
    #   (a) 1-for-1 categories (sell_high, buy_low) share one counter.
    #   (b) Package categories (consolidation, positional_upgrade) share
    #       a separate counter.
    # This prevents sell_high from consuming all appearances of surplus
    # depth players, leaving no room for package deals that use the same
    # players in a fundamentally different trade structure.
    _cap_group = [
        ["sell_high", "buy_low"],
        ["consolidation", "positional_upgrade"],
    ]
    for group in _cap_group:
        give_counts: dict[str, int] = {}
        for cat_name in group:
            suggs = categories.get(cat_name, [])
            filtered = []
            for s in suggs:
                # Check if ANY give-player would exceed the cap
                # Per-asset identity from the owner (V1-36); the cap itself
                # (MAX_GIVE_PLAYER_APPEARANCES) and the two-budget grouping
                # above are unchanged.
                would_exceed = any(
                    give_counts.get(_identity_key(p.name), 0) >= MAX_GIVE_PLAYER_APPEARANCES
                    for p in s.give
                )
                if would_exceed:
                    continue
                for p in s.give:
                    gk = _identity_key(p.name)
                    give_counts[gk] = give_counts.get(gk, 0) + 1
                filtered.append(s)
            categories[cat_name] = filtered

    return categories


# ── Main entry point ─────────────────────────────────────────────────


def _rookies_eligible_today() -> bool:
    """Return False between Feb 1 and May 11 of each year — the
    pre-draft window when rookie names in the consensus board are
    just placeholders (the actual class hasn't been drafted yet) and
    suggesting them would surface speculative names rather than
    actionable trade targets.

    May 11 was chosen as the consistent cutoff since the NFL Draft
    runs late April / early May; the week-after gives the dust time
    to settle on rookie team assignments + fantasy market values.

    From May 12 onward through Jan 31, rookies are real players with
    real values — eligible for suggestions like any other asset.
    """
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    m, d = today.month, today.day
    # Pre-draft window: Feb 1 through May 11 (inclusive).
    if m == 2 or m == 3 or m == 4:
        return False
    if m == 5 and d <= 11:
        return False
    return True


def generate_suggestions_from_pool(
    roster_names: list[str],
    pool: list[PlayerAsset],
    *,
    starter_needs: dict[str, int] | None = None,
    max_per_type: int = MAX_SUGGESTIONS_PER_TYPE,
    league_rosters: list[dict[str, Any]] | None = None,
    board_top_n: int | None = None,
    ktc_top_n: int | None = None,
    capacity_context: Any | None = None,
    constraints: Any | None = None,
) -> dict[str, Any]:
    """Generate trade suggestions against a pre-built asset pool.

    This is the pool-native entry point — it skips asset-pool
    construction so the caller controls where the pool comes from.
    Used by ``/api/trade/suggestions`` in ``server.py`` to source the
    pool directly from the live contract via
    :func:`build_asset_pool_from_contract`.

    ``board_top_n`` is informational-only here (reported in metadata) —
    the pool is expected to have already had the top-N filter applied
    by the caller.  ``ktc_top_n`` is a deprecated alias; this gate
    never consulted KTC (WS-J F-4).

    ``capacity_context`` (``src.trade.roster_capacity.CapacityContext``) turns
    on the roster-capacity read.  Every suggestion then carries what it would
    cost in forced releases — and **nothing is filtered out**.  On a full
    58-man roster a legality filter would silently shorten these lists, and a
    proposal that vanishes is invisible rather than explained; that is the same
    failure mode as a balancer that does not say where it lands.  Refusing
    over-cap packages is right for ``roster_intel.packages``, which is choosing
    what to put on a Pareto frontier — a different question.
    """
    if board_top_n is None:
        board_top_n = BOARD_TOP_N_FILTER if ktc_top_n is None else ktc_top_n
    # Pre-draft rookie suppression (Feb 1 - May 11): rookies in the
    # consensus board are placeholders during this window — the
    # class hasn't been drafted, fantasy values are speculative.
    # Suggesting them produces names like "2026 Rookie EDGE" rather
    # than actionable trade targets.  Filter the pool down to
    # non-rookies; the assets stay in the user's roster (so the
    # roster analysis is correct), they just can't appear as trade
    # TARGETS.  Re-enabled May 12 each year.
    if not _rookies_eligible_today():
        pool = [p for p in pool if not p.rookie]

    roster = analyze_roster(roster_names, pool, starter_needs, constraints=constraints)
    if roster.roster_size and not roster.sendable_keys:
        # Every asset we could offer is protected or excluded.  Say so rather
        # than returning four empty categories, which reads as "nothing to
        # suggest" — the failure §4 forbids by name.
        return {
            **{c: [] for c in ("sell_high", "buy_low", "consolidation", "positional_upgrade")},
            "warnings": [
                "Every asset on your roster is protected or excluded from outgoing "
                "recommendations, so no suggestion could be generated."
            ],
            "metadata": {
                "rosterMatched": roster.roster_size,
                "rosterProvided": len(roster_names),
                "constraintsBlockedOutgoing": len(roster.constrained_out),
                "constraintsBlockedReasons": sorted({r for _a, r in roster.constrained_out}),
                "noResultReason": "all_outgoing_assets_constrained",
            },
        }
    roster_set = {_identity_key(n) for n in roster_names}

    sell_high = _generate_sell_high(roster, pool, roster_set)
    buy_low = _generate_buy_low(roster, pool, roster_set)
    consolidation = _generate_consolidation(roster, pool, roster_set)
    upgrades = _generate_positional_upgrades(roster, pool, roster_set)

    # Phase 3: Opponent-aware analysis (if league rosters provided)
    opponent_analyses: dict[str, RosterAnalysis] = {}
    if league_rosters:
        opponent_analyses = _analyze_opponent_rosters(league_rosters, pool)

    # Enrich all suggestions with edge signals, balancers, opponent fit
    all_unranked = sell_high + buy_low + consolidation + upgrades
    for s in all_unranked:
        # Phase 2: Market-disagreement edge
        edge, explanation = _edge_for_suggestion(s)
        s.__dict__["edge"] = edge
        s.__dict__["edge_explanation"] = explanation

        # What this trade costs in roster spots.  Attached, never filtered.
        if capacity_context is not None:
            from src.trade.roster_capacity import (  # noqa: PLC0415
                assess_roster_capacity,
                player_names_only,
            )

            try:
                s.__dict__["roster_capacity"] = assess_roster_capacity(
                    capacity_context,
                    incoming_players=player_names_only(s.receive),
                    outgoing_players=player_names_only(s.give),
                )
            except Exception:  # noqa: BLE001 — an optional read never drops a suggestion
                s.__dict__["roster_capacity"] = None

        # Balancers for non-even trades
        if s.fairness != "even":
            exclude = {_identity_key(p.name) for p in s.give + s.receive}
            bals, side, residuals = _find_balancers(s, pool, roster_set, exclude, roster)
            s.__dict__["balancers"] = bals
            s.__dict__["balancer_side"] = side
            s.__dict__["balancer_residuals"] = residuals

        # Phase 3: Opponent fit
        if opponent_analyses:
            s.__dict__["opponent_fit"] = _opponent_fit_label(s, opponent_analyses)

    # Phase 4: Deterministic ranking — applied AFTER enrichment so edge
    # and opponent-fit bonuses affect ordering.
    def sort_key(s):
        return _rank_sort_key(s, roster)

    sell_high.sort(key=sort_key)
    buy_low.sort(key=sort_key)
    consolidation.sort(key=sort_key)
    upgrades.sort(key=sort_key)

    # Phase 5: Quality filters — deduplication and noise suppression.
    # Applied AFTER ranking so we keep the best-ranked instances.
    filtered = _apply_quality_filters(
        {
            "sell_high": sell_high,
            "buy_low": buy_low,
            "consolidation": consolidation,
            "positional_upgrade": upgrades,
        }
    )
    sell_high = filtered["sell_high"]
    buy_low = filtered["buy_low"]
    consolidation = filtered["consolidation"]
    upgrades = filtered["positional_upgrade"]

    # Enforce per-category caps after filtering
    sell_high = sell_high[:max_per_type]
    buy_low = buy_low[:max_per_type]
    consolidation = consolidation[:max_per_type]
    upgrades = upgrades[:max_per_type]

    all_suggestions = sell_high + buy_low + consolidation + upgrades

    return {
        "rosterAnalysis": _serialize_roster(roster),
        "sellHigh": [_serialize_suggestion(s, roster) for s in sell_high],
        "buyLow": [_serialize_suggestion(s, roster) for s in buy_low],
        "consolidation": [_serialize_suggestion(s, roster) for s in consolidation],
        "positionalUpgrades": [_serialize_suggestion(s, roster) for s in upgrades],
        "totalSuggestions": len(all_suggestions),
        "metadata": {
            "assetPoolSize": len(pool),
            "boardTopNFilter": board_top_n,
            # Deprecated alias — this gate never consulted KTC.
            "ktcTopNFilter": board_top_n,
            "rosterMatched": roster.roster_size,
            "rosterProvided": len(roster_names),
            # C3-CON-01.  Published because a shorter list with no explanation
            # reads as "no trades exist" rather than "you protect these".
            "constraintsBlockedOutgoing": len(roster.constrained_out),
            "constraintsBlockedReasons": sorted({r for _a, r in roster.constrained_out}),
            "starterNeeds": roster.starter_needs,
            "opponentRostersProvided": len(league_rosters) if league_rosters else 0,
            "opponentRostersAnalyzed": len(opponent_analyses),
        },
    }


def generate_suggestions(
    roster_names: list[str],
    asset_dict_payload: dict[str, Any],
    *,
    starter_needs: dict[str, int] | None = None,
    max_per_type: int = MAX_SUGGESTIONS_PER_TYPE,
    league_rosters: list[dict[str, Any]] | None = None,
    board_top_n: int | None = None,
    ktc_top_n: int | None = None,
) -> dict[str, Any]:
    """Asset-dict entry point (legacy back-compat).

    Preserved for tests and tooling that still pass a payload shaped
    like ``{"assets": [...]}``.  Production ``/api/trade/suggestions``
    uses :func:`generate_suggestions_from_pool` with a pool built
    directly from the live contract via
    :func:`build_asset_pool_from_contract`.

    ``ktc_top_n`` is a deprecated alias for ``board_top_n``; this gate
    never consulted KTC (WS-J F-4).
    """
    if board_top_n is None:
        board_top_n = BOARD_TOP_N_FILTER if ktc_top_n is None else ktc_top_n
    pool = build_asset_pool(asset_dict_payload, board_top_n=board_top_n)
    return generate_suggestions_from_pool(
        roster_names=roster_names,
        pool=pool,
        starter_needs=starter_needs,
        max_per_type=max_per_type,
        league_rosters=league_rosters,
        board_top_n=board_top_n,
    )


# ── Serializers ──────────────────────────────────────────────────────


def _serialize_player(p: PlayerAsset) -> dict[str, Any]:
    """``displayValue`` is the canonical board value, always.

    It used to carry a second, IDP-disabled board whenever the trade
    contained no defender — two value concepts under one canonical field
    name, with nothing on the wire saying which was which (W29-F001).
    """
    result: dict[str, Any] = {
        "name": p.name,
        "position": p.position,
        "displayValue": p.display_value,
        "team": p.team,
        "rookie": p.rookie,
    }
    if p.dispersion_cv is not None:
        result["dispersionCV"] = p.dispersion_cv
    if p.board_rank is not None:
        result["boardRank"] = p.board_rank
        # Deprecated alias — never a KTC rank (WS-J F-4).
        result["ktcRank"] = p.board_rank
    return result


def _serialize_suggestion(
    s: TradeSuggestion, roster: RosterAnalysis | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": s.type,
        "give": [_serialize_player(p) for p in s.give],
        "receive": [_serialize_player(p) for p in s.receive],
        "giveTotal": s.give_total,
        "receiveTotal": s.receive_total,
        "gap": s.gap,
        "fairness": s.fairness,
        "rationale": s.rationale,
        "whyThisHelps": s.why_this_helps,
        "confidence": s.confidence,
        "strategy": s.strategy,
    }
    # Rank score breakdown (explainability)
    result["rankScore"] = rank_score_breakdown(s, roster)
    balancers = s.__dict__.get("balancers", [])
    if balancers:
        result["suggestedBalancers"] = [_serialize_player(b) for b in balancers]
        bal_side = s.__dict__.get("balancer_side", "")
        if bal_side:
            result["balancerSide"] = bal_side
        # The gap that would REMAIN after each balancer, in the same
        # sign convention as ``gap``.  Published because a suggestion
        # that says "add this to balance" without saying what it lands
        # on is unfalsifiable (defect #800).
        residuals = s.__dict__.get("balancer_residuals", [])
        if residuals:
            result["balancerResidualGaps"] = [int(r) for r in residuals]
    capacity = s.__dict__.get("roster_capacity")
    if capacity is not None:
        result["rosterCapacity"] = capacity.to_dict()
    edge = s.__dict__.get("edge")
    if edge:
        result["edge"] = edge
        result["edgeExplanation"] = s.__dict__.get("edge_explanation", "")
    opponent_fit = s.__dict__.get("opponent_fit")
    if opponent_fit:
        result["opponentFit"] = opponent_fit
    return result


def _serialize_roster(r: RosterAnalysis) -> dict[str, Any]:
    return {
        "rosterSize": r.roster_size,
        "surplusPositions": r.surplus_positions,
        "needPositions": r.need_positions,
        "starterCounts": r.starter_counts,
        "depthCounts": r.depth_counts,
        "byPosition": {
            pos: [_serialize_player(p) for p in players] for pos, players in r.by_position.items()
        },
    }
