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
from dataclasses import dataclass
from typing import Any

from src.canonical.calibration import to_display_value
from src.trade.ktc_va import adjusted_pair_totals
from src.utils.name_clean import normalize_position as _norm_pos  # noqa: F401 — see _norm_pos shim removal below (audit S2)


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

# Order flex slots are handed out in when converting a lineup to
# effective demand.  RB before WR before TE matches how the constant
# above was hand-derived, and is what makes the derivation reproduce it.
_FLEX_ALLOCATION_ORDER: tuple[str, ...] = ("RB", "WR", "TE")

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

    Applied to ``dynasty_main`` this reproduces ``DEFAULT_STARTER_NEEDS``
    exactly, so the live league's suggestions are unchanged; pinned by
    ``tests/league_intel/test_registry_consumers.py``.

    Falls back to ``DEFAULT_STARTER_NEEDS`` when the registry has
    nothing to say — an unknown key, or no roster settings — rather than
    returning an empty demand map, which would read as "this roster
    needs nobody" and silence every surplus/need suggestion.
    """
    starters: dict[str, Any] = {}
    flex_eligible: list[str] = []
    idp_flex_eligible: list[str] = []
    try:
        from src.api.league_registry import get_league_roster_settings

        settings = get_league_roster_settings(league_key) or {}
        starters = dict(settings.get("starters") or {})
        flex_eligible = list(settings.get("flexEligible") or [])
        idp_flex_eligible = list(settings.get("idpFlexEligible") or [])
    except Exception:  # noqa: BLE001 — registry is optional for this module
        starters = {}
    if not starters:
        return dict(DEFAULT_STARTER_NEEDS)

    needs: dict[str, int] = {}

    def _add(position: str, count: int = 1) -> None:
        pos = str(position).upper()
        if pos in _NON_DEMAND_SLOTS:
            return
        needs[pos] = needs.get(pos, 0) + count

    def _round_robin(count: int, eligible: list[str], order: tuple[str, ...]) -> None:
        pool = [p for p in order if p in {str(e).upper() for e in eligible}]
        if not pool:
            return
        for i in range(int(count)):
            _add(pool[i % len(pool)])

    flex_count = 0
    sflex_count = 0
    idp_flex_count = 0
    for slot, count in starters.items():
        key = str(slot).upper()
        n = int(count or 0)
        if n <= 0:
            continue
        if key in ("FLEX", "WR_RB_FLEX", "REC_FLEX"):
            flex_count += n
        elif key in ("SFLEX", "SUPER_FLEX", "SUPERFLEX"):
            sflex_count += n
        elif key == "IDP_FLEX":
            idp_flex_count += n
        else:
            _add(key, n)

    # Superflex is a QB slot in everything but name.
    if sflex_count:
        _add("QB", sflex_count)
    _round_robin(flex_count, flex_eligible, _FLEX_ALLOCATION_ORDER)
    _round_robin(idp_flex_count, idp_flex_eligible, ("DL", "LB", "DB"))

    return needs or dict(DEFAULT_STARTER_NEEDS)


# Minimum display value to consider a player "rosterable" (not a throw-in)
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
    offense_only_value: int | None = None  # display_value excluding IDP sources

    @property
    def ktc_rank(self) -> int | None:
        """Deprecated alias — this was never a KTC rank (WS-J F-4)."""
        return self.board_rank


@dataclass
class RosterAnalysis:
    """Positional analysis of a roster."""

    roster_size: int
    by_position: dict[str, list[PlayerAsset]]
    surplus_positions: list[str]
    need_positions: list[str]
    starter_counts: dict[str, int]  # above-replacement count
    depth_counts: dict[str, int]  # below-replacement count


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

        oo_rdv = row.get("offenseOnlyRankDerivedValue")
        oo_int: int | None = None
        if isinstance(oo_rdv, (int, float)) and oo_rdv > 0:
            oo_int = int(oo_rdv)

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
                offense_only_value=oo_int,
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
) -> RosterAnalysis:
    """Analyze a roster for positional surplus and need."""
    needs = starter_needs or DEFAULT_STARTER_NEEDS

    pool_by_name: dict[str, PlayerAsset] = {}
    for a in asset_pool:
        key = a.name.lower().strip()
        if key not in pool_by_name or a.display_value > pool_by_name[key].display_value:
            pool_by_name[key] = a

    by_position: dict[str, list[PlayerAsset]] = {}
    matched = 0
    for rn in roster_names:
        key = rn.lower().strip()
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

    return RosterAnalysis(
        roster_size=matched,
        by_position=by_position,
        surplus_positions=surplus_positions,
        need_positions=need_positions,
        starter_counts=starter_counts,
        depth_counts=depth_counts,
    )


def _eff_val(p: PlayerAsset, offense_only: bool) -> int:
    """Return the effective value for a player in the context of a trade.

    When ``offense_only`` is True and the player carries a pre-computed
    offense-only value, that value is returned.  This ensures trades
    with no IDP players are not influenced by IDP source calibration.
    """
    if offense_only and p.offense_only_value is not None:
        return p.offense_only_value
    return p.display_value


def _trade_is_idp_free(give: list[PlayerAsset], receive: list[PlayerAsset]) -> bool:
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
                needed = DEFAULT_STARTER_NEEDS.get(p.position, 1)
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
                needed = DEFAULT_STARTER_NEEDS.get(p.position, 1)
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
    pool_by_name: dict[str, PlayerAsset] = {}
    for a in asset_pool:
        pool_by_name[a.name.lower().strip()] = a

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
        return f"Strong bilateral fit: {fitting_teams[0]} needs {', '.join(give_positions)} and could deal."
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
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        sell_candidates = [p for p in players[need:] if p.display_value >= MIN_RELEVANT_VALUE]
        if not sell_candidates:
            continue

        for sell in sell_candidates[:3]:
            for need_pos in roster.need_positions:
                # Pre-compute oo so target filtering and sorting use the same
                # value scale as the gap calculation below.
                trade_oo = (
                    sell.position not in _IDP_BASE_POSITIONS and need_pos not in _IDP_BASE_POSITIONS
                )
                sell_ev = _eff_val(sell, trade_oo)
                targets = [
                    a
                    for a in asset_pool
                    if a.position == need_pos
                    and a.name.lower() not in roster_names_set
                    and _eff_val(a, trade_oo) >= MIN_RELEVANT_VALUE
                    and abs(_eff_val(a, trade_oo) - sell_ev) < FAIRNESS_TOLERANCE
                ]
                if not targets:
                    continue
                targets.sort(key=lambda t: abs(_eff_val(t, trade_oo) - sell_ev))
                target = targets[0]
                oo = _trade_is_idp_free([sell], [target])
                give_val = _eff_val(sell, oo)
                recv_val = _eff_val(target, oo)
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
        pos_oo = need_pos not in _IDP_BASE_POSITIONS
        current = roster.by_position.get(need_pos, [])
        current_best = _eff_val(current[0], pos_oo) if current else 0
        target_floor = max(MIN_RELEVANT_VALUE, current_best)

        targets = [
            a
            for a in asset_pool
            if a.position == need_pos
            and a.name.lower() not in roster_names_set
            and _eff_val(a, pos_oo) > target_floor
        ]
        if not targets:
            continue

        for target in targets[:5]:
            for surplus_pos in roster.surplus_positions:
                depth = roster.by_position.get(surplus_pos, [])
                need = DEFAULT_STARTER_NEEDS.get(surplus_pos, 1)
                tradeable = [p for p in depth[need:] if p.display_value >= MIN_RELEVANT_VALUE]
                for sell in tradeable[:2]:
                    oo = _trade_is_idp_free([sell], [target])
                    give_val = _eff_val(sell, oo)
                    recv_val = _eff_val(target, oo)
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

    # Deduplicate by receive target (keep tightest gap)
    seen: dict[str, TradeSuggestion] = {}
    for s in suggestions:
        key = s.receive[0].name
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
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        for p in players[need:]:
            if p.display_value >= MIN_RELEVANT_VALUE:
                tradeable.append(p)

    tradeable.sort(key=lambda x: -x.display_value)
    if len(tradeable) < 2:
        return []

    tried: set[str] = set()
    for i in range(min(len(tradeable), 6)):
        for j in range(i + 1, min(len(tradeable), 8)):
            p1, p2 = tradeable[i], tradeable[j]
            pair_key = f"{p1.name}|{p2.name}"
            if pair_key in tried:
                continue
            tried.add(pair_key)

            # Pre-compute oo from the give side so range filtering and
            # sorting use the same value scale as the final gap calc.
            pair_oo = _trade_is_idp_free([p1, p2], [])
            combined = _eff_val(p1, pair_oo) + _eff_val(p2, pair_oo)
            min_target = int(combined * CONSOLIDATION_MIN_UPGRADE_RATIO)
            max_target = combined + FAIRNESS_TOLERANCE
            give_max = max(_eff_val(p1, pair_oo), _eff_val(p2, pair_oo))

            for prefer_need in [True, False]:
                targets = [
                    a
                    for a in asset_pool
                    if a.name.lower() not in roster_names_set
                    and min_target <= _eff_val(a, pair_oo) <= max_target
                    and _eff_val(a, pair_oo) > give_max
                    # When the give pair is offense-only, restrict to offense
                    # targets so pair_oo matches the final oo (no scale flip).
                    and (not pair_oo or a.position not in _IDP_BASE_POSITIONS)
                    and (not prefer_need or a.position in roster.need_positions)
                ]
                if not targets:
                    continue
                # Pick the closest-value target (smallest gap) rather than
                # the most expensive one.  This produces fairer packages.
                targets.sort(key=lambda t: abs(combined - _eff_val(t, pair_oo)))
                target = targets[0]
                oo = _trade_is_idp_free([p1, p2], [target])
                give_p1, give_p2 = _eff_val(p1, oo), _eff_val(p2, oo)
                give_total = give_p1 + give_p2
                recv_total = _eff_val(target, oo)
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

    for pos in DEFAULT_STARTER_NEEDS:
        players = roster.by_position.get(pos, [])
        if len(players) < 2:
            continue
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        if need < 1:
            continue

        starters = players[:need]
        # pos is always an offense position in DEFAULT_STARTER_NEEDS; using
        # pos_oo=True means IDP sweeteners fall back to display_value safely.
        pos_oo = pos not in _IDP_BASE_POSITIONS
        depth = [p for p in players[need:] if _eff_val(p, pos_oo) >= MIN_RELEVANT_VALUE]
        if not starters or not depth:
            continue

        weakest_starter = starters[-1]
        ws_ev = _eff_val(weakest_starter, pos_oo)
        upgrade_floor = ws_ev + 500

        targets = [
            a
            for a in asset_pool
            if a.position == pos
            and a.name.lower() not in roster_names_set
            and _eff_val(a, pos_oo) >= upgrade_floor
        ]
        if not targets:
            continue

        targets.sort(key=lambda t: _eff_val(t, pos_oo))  # closest upgrade first
        for target in targets[:5]:
            gap_needed = _eff_val(target, pos_oo) - ws_ev
            sweeteners = [
                p
                for p in depth
                if p.name != weakest_starter.name
                and abs(_eff_val(p, pos_oo) - gap_needed) < FAIRNESS_TOLERANCE
            ]
            if not sweeteners:
                # Widen tolerance for surplus-position sweeteners — these
                # are expendable depth the user can afford to overpay with.
                surplus_tol = int(FAIRNESS_TOLERANCE * UPGRADE_SWEETENER_SURPLUS_MULTIPLIER)
                for sp in roster.surplus_positions:
                    sp_depth = roster.by_position.get(sp, [])
                    sp_need = DEFAULT_STARTER_NEEDS.get(sp, 1)
                    for p in sp_depth[sp_need:]:
                        sp_ev = _eff_val(p, pos_oo)
                        if sp_ev >= MIN_RELEVANT_VALUE and abs(sp_ev - gap_needed) < surplus_tol:
                            sweeteners.append(p)
            if not sweeteners:
                continue

            sweeteners.sort(key=lambda s: abs(_eff_val(s, pos_oo) - gap_needed))
            sweetener = sweeteners[0]
            oo = _trade_is_idp_free([weakest_starter, sweetener], [target])
            give_ws = _eff_val(weakest_starter, oo)
            give_sw = _eff_val(sweetener, oo)
            give_total = give_ws + give_sw
            recv_total = _eff_val(target, oo)
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
    gap: int,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
    exclude_names: set[str],
    roster: RosterAnalysis | None = None,
) -> tuple[list[PlayerAsset], str]:
    """Find realistic balancer add-ons for a near-there trade.

    Direction-aware:
    - gap < 0 (user underpays): search user's roster for expendable add-ons.
    - gap > 0 (user overpays): search global pool for what opponent could add.

    Returns (balancers, side) where side is "you_add" or "they_add".
    """
    if abs(gap) < 256:
        return ([], "")
    target_value = abs(gap)
    side = "you_add" if gap < 0 else "they_add"

    if gap < 0 and roster is not None:
        # User needs to sweeten — search THEIR roster for expendable depth
        candidates = _roster_balancer_candidates(
            target_value,
            roster,
            exclude_names,
        )
    else:
        # Opponent needs to sweeten — search global pool
        candidates = _pool_balancer_candidates(
            target_value,
            asset_pool,
            roster_names_set,
            exclude_names,
        )

    candidates.sort(
        key=lambda c: (
            0 if (roster and c.position in roster.surplus_positions) else 1,
            abs(c.display_value - target_value),
            c.name,
        )
    )
    return (candidates[:MAX_BALANCERS], side)


def _roster_balancer_candidates(
    target_value: int,
    roster: RosterAnalysis,
    exclude_names: set[str],
) -> list[PlayerAsset]:
    """Find expendable depth pieces from the user's roster."""
    candidates: list[PlayerAsset] = []

    # Prefer surplus-position depth, then any non-starter depth
    for pos in list(roster.surplus_positions) + list(DEFAULT_STARTER_NEEDS.keys()):
        players = roster.by_position.get(pos, [])
        need = DEFAULT_STARTER_NEEDS.get(pos, 1)
        for p in players[need:]:
            if (
                p.name.lower() not in exclude_names
                and p.position  # skip positionless
                and p.display_value >= MIN_RELEVANT_VALUE
                and abs(p.display_value - target_value) < target_value * 0.5
            ):
                if not any(c.name == p.name for c in candidates):
                    candidates.append(p)
    return candidates


def _pool_balancer_candidates(
    target_value: int,
    asset_pool: list[PlayerAsset],
    roster_names_set: set[str],
    exclude_names: set[str],
) -> list[PlayerAsset]:
    """Find realistic balancer candidates from the global asset pool."""
    return [
        a
        for a in asset_pool
        if a.name.lower() not in roster_names_set
        and a.name.lower() not in exclude_names
        and a.position  # skip positionless / placeholder entries
        and a.display_value >= MIN_RELEVANT_VALUE
        and abs(a.display_value - target_value) < target_value * 0.4
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
        recv_counts: dict[str, int] = {}
        filtered: list[TradeSuggestion] = []
        for s in suggs:
            recv_key = "|".join(sorted(p.name for p in s.receive))
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
                would_exceed = any(
                    give_counts.get(p.name, 0) >= MAX_GIVE_PLAYER_APPEARANCES for p in s.give
                )
                if would_exceed:
                    continue
                for p in s.give:
                    give_counts[p.name] = give_counts.get(p.name, 0) + 1
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

    roster = analyze_roster(roster_names, pool, starter_needs)
    roster_set = {n.lower().strip() for n in roster_names}

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

        # Balancers for non-even trades
        if s.fairness != "even":
            exclude = {p.name.lower() for p in s.give + s.receive}
            bals, side = _find_balancers(s.gap, pool, roster_set, exclude, roster)
            s.__dict__["balancers"] = bals
            s.__dict__["balancer_side"] = side

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
            "starterNeeds": starter_needs or DEFAULT_STARTER_NEEDS,
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


def _serialize_player(p: PlayerAsset, *, offense_only: bool = False) -> dict[str, Any]:
    dv = (
        p.offense_only_value
        if offense_only and p.offense_only_value is not None
        else p.display_value
    )
    result: dict[str, Any] = {
        "name": p.name,
        "position": p.position,
        "displayValue": dv,
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
    oo = _trade_is_idp_free(s.give, s.receive)
    result: dict[str, Any] = {
        "type": s.type,
        "give": [_serialize_player(p, offense_only=oo) for p in s.give],
        "receive": [_serialize_player(p, offense_only=oo) for p in s.receive],
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
        result["suggestedBalancers"] = [_serialize_player(b, offense_only=oo) for b in balancers]
        bal_side = s.__dict__.get("balancer_side", "")
        if bal_side:
            result["balancerSide"] = bal_side
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
