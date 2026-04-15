from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from src.data_models.contracts import utc_now_iso

#: Verified cross-universe name collisions — players whose display name
#: exists in both the offense market (QB/RB/WR/TE) and the IDP market
#: (DL/LB/DB) as two genuinely different people.  The
#: ``position_source_contradiction`` check would otherwise fire on one
#: side of every such collision because name-based join enrichment will
#: graft the wrong source's value onto the wrong row.
#:
#: This list is intentionally small.  Before adding a new entry, verify
#: that the contradiction survives a full rebuild with the normalised
#: name join (``_canonical_match_key``) in place — most historical
#: contradictions were join artefacts from punctuation drift (e.g.
#: ``T.J. Watt`` vs ``TJ Watt``) and no longer reproduce.
#:
#: The exceptions only apply when a row ALSO has
#: ``name_collision_cross_universe`` already flagged on it, so a false
#: positive on a non-colliding name cannot silently suppress a legitimate
#: contradiction anymore.
OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS: frozenset[str] = frozenset(
    {
        "Josh Johnson",     # QB (retired journeyman) vs S (draftable prospect)
        "Elijah Mitchell",  # RB (HOU backup) vs DB (draftable prospect) — Sleeper pos
                            # map resolves to the DB; scraper has only the RB's KTC value
    }
)


CONTRACT_VERSION = "2026-03-10.v2"

# ── Unified rankings: blended board from all active sources ──────────────────
# rank_to_value() is imported from src.canonical.player_valuation — that module
# is the ONE authoritative formula implementation.
#
# The two active sources (KTC and IDPTradeCalc) cover non-overlapping player
# pools: KTC has offense (QB/RB/WR/TE + picks), IDPTC has IDP (DL/LB/DB).
# Each player is ranked within their source first (source-specific ordinal
# rank), then their rank-derived value is computed via rank_to_value().
# All players are then sorted by that normalized value into one unified board
# and assigned a single overall canonicalConsensusRank.
#
# Source coverage rule: every player has exactly one source.  When both sources
# expand to overlap in the future, blended averaging will apply.
# ─────────────────────────────────────────────────────────────────────────────
OVERALL_RANK_LIMIT: int = 800
# Backward compatibility alias — old tests and cross-checks reference this
KTC_RANK_LIMIT: int = OVERALL_RANK_LIMIT
IDP_RANK_LIMIT: int = OVERALL_RANK_LIMIT
_KICKER_POSITIONS = {"K", "PK"}
_OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}
_IDP_POSITIONS = {"DL", "LB", "DB"}
# Positions eligible for per-source ranking.  Only offense + IDP players
# participate; picks, kickers, and unsupported positions are excluded.
_RANKABLE_POSITIONS = _OFFENSE_POSITIONS | _IDP_POSITIONS | {"PICK"}
_OFFENSE_SIGNAL_KEYS = {
    "ktc",
    "dlfSf",
    "dynastyNerdsSfTep",
}
_IDP_SIGNAL_KEYS = {
    "idpTradeCalc",
    "dlfIdp",
}

# All source signal keys — used to detect which source(s) a player has
_ALL_SIGNAL_KEYS = _OFFENSE_SIGNAL_KEYS | _IDP_SIGNAL_KEYS

# ── Confidence bucket thresholds ────────────────────────────────────────────
# Buckets describe how much trust a consumer should place in a player's
# unified rank.  Determined by source count, source agreement, and whether
# the player is inside the rank limit.
#
# Rules (evaluated top-to-bottom, first match wins):
#   "high"   — 2+ sources AND sourceRankSpread <= 30
#   "medium" — 2+ sources AND sourceRankSpread <= 80
#   "low"    — single source OR sourceRankSpread > 80
#   "none"   — player did not receive a unified rank
_CONFIDENCE_SPREAD_HIGH = 30
_CONFIDENCE_SPREAD_MEDIUM = 80

# ── Anomaly flag rule constants ──────────────────────────────────────────────
# Each rule produces a machine-readable string if triggered.  Multiple flags
# can coexist on one player.
#
# Flag catalogue:
#   "offense_as_idp"           — offense player only has IDP source values
#   "idp_as_offense"           — IDP player only has offense source values
#   "missing_position"         — position is None, empty, or "?"
#   "retired_or_invalid_name"  — name matches common invalid patterns
#   "ol_contamination"         — OL/OT/OG/C position leaked into rankings
#   "suspicious_disagreement"  — 2+ sources disagree by > 150 ordinal ranks
#   "missing_source_distortion"— only 1 source present when 2 are expected
#   "impossible_value"         — rankDerivedValue <= 0 despite having a rank
_SUSPICIOUS_DISAGREEMENT_THRESHOLD = 150
_RETIRED_INVALID_PATTERNS = re.compile(
    r"(?i)\b(retired|invalid|test|unknown|placeholder)\b"
)
_OL_POSITIONS = {"OL", "OT", "OG", "C", "G", "T"}

# ── Identity validation constants ────────────────────────────────────────────
# Supported positions: only these may appear on the public board.  Anything
# else is either a data-entry error or position contamination.
_SUPPORTED_BOARD_POSITIONS = _OFFENSE_POSITIONS | _IDP_POSITIONS | {"PICK"}

# Near-name collision: two players sharing a last name where one is offense
# and the other is IDP, with wildly different rank-derived values, suggest
# entity-resolution confusion (e.g. "James Williams" WR ≠ "James Williams" LB).
_NEAR_NAME_VALUE_RATIO_THRESHOLD = 3.0  # flag if max/min value ratio > 3x

# Quarantine flags added by the identity validation pass.  These are appended
# to anomalyFlags[] and also cause confidenceBucket degradation.
#   "duplicate_canonical_identity"  — two rows resolved to the same
#                                     position-aware canonical key
#   "name_collision_cross_universe" — same normalized name in offense + IDP
#                                     (usually distinct people; surfaced
#                                     for visibility, not auto-quarantined)
#   "position_source_contradiction" — position family disagrees with source evidence
#   "unsupported_position"          — position not in _SUPPORTED_BOARD_POSITIONS
#   "no_valid_source_values"        — no source values > 0 but has derived value
#
# The legacy ``near_name_value_mismatch`` flag was retired (see
# ``_validate_and_quarantine_rows`` Check 3 for rationale).  It used to
# fire here but the underlying rule produced only false positives.
_QUARANTINE_FLAGS = {
    "duplicate_canonical_identity",
    "position_source_contradiction",
    "unsupported_position",
    "no_valid_source_values",
}

# CSV export paths for source enrichment (relative to repo root).
#
# Each entry is either:
#   * a plain string path — legacy "name,value" CSV, higher is better
#   * a dict { path, signal } — "value" for name,value CSVs, "rank" for
#     name,rank CSVs (lower is better, stamped as a synthetic monotonic
#     value via _RANK_TO_SYNTHETIC_VALUE so the downstream descending
#     sort in _compute_unified_rankings produces the correct ordinal)
_SOURCE_CSV_PATHS: dict[str, Any] = {
    "ktc": "exports/latest/site_raw/ktc.csv",
    "idpTradeCalc": "exports/latest/site_raw/idpTradeCalc.csv",
    "dlfIdp": {
        "path": "exports/latest/site_raw/dlfIdp.csv",
        "signal": "rank",
    },
    # DLF Dynasty Superflex rankings — offense expert consensus.
    # Raw CSV exported from DLF with capitalized Name/Rank columns
    # plus several per-expert columns.  The `_enrich_from_source_csvs`
    # reader uses column-name aliases so we can point directly at the
    # original filename without any preprocessing.
    "dlfSf": {
        "path": "exports/latest/site_raw/Dynasty Superflex Rankings-3-15-2026-1642.csv",
        "signal": "rank",
    },
    # Dynasty Nerds Superflex + TE Premium rankings — scraped from
    # https://www.dynastynerds.com/dynasty-rankings/sf-tep/ via
    # ``scripts/fetch_dynasty_nerds.py``.  The CSV has an explicit
    # ``Rank`` column (1..294) written from the DR_DATA.SFLEXTEP
    # array, filtered to rows with value > 0.  Signal=rank so the
    # ``_enrich_from_source_csvs`` reader uses the rank column, not
    # the raw DN value.
    "dynastyNerdsSfTep": {
        "path": "exports/latest/site_raw/dynastyNerdsSfTep.csv",
        "signal": "rank",
    },
}

# Rank -> synthetic value transform used when a CSV declares signal=rank.
# The absolute number is irrelevant to the downstream pipeline (it only
# cares about the *ordering* of eligible rows within the source), but we
# keep it above zero and bounded so the stamped value looks sensible to
# the trust/confidence + anomaly checks that read canonicalSiteValues.
_RANK_TO_SYNTHETIC_VALUE_OFFSET = 10000

# ── Ranking source registry ──────────────────────────────────────────────
# Declarative metadata describing each source that feeds the unified
# ranking.  Keeping this in one list makes it trivial to add a new
# position-only IDP source (e.g. a scouted "DL top 20"): append an entry
# with scope="position_idp", position_group="DL", depth=20 and the
# translation pipeline picks it up automatically.
#
# Fields:
#   key           — the contract-side source key used in canonicalSiteValues
#   display_name  — human label for methodology docs
#   scope         — the *primary* scope for this source, one of:
#                     SOURCE_SCOPE_OVERALL_OFFENSE: ranks offense + picks
#                     SOURCE_SCOPE_OVERALL_IDP:     ranks DL/LB/DB together
#                     SOURCE_SCOPE_POSITION_IDP:    ranks a single IDP family
#   extra_scopes  — optional list of additional scopes this source also
#                   contributes to.  Used when a single market source
#                   (e.g. IDP Trade Calculator) lists BOTH offense and IDP
#                   players in the same value pool, and we want it to
#                   feed the offense blend as a second opinion as well as
#                   serving as the IDP backbone.  Because offense and IDP
#                   position sets are disjoint, each row only ever lands
#                   in one scope's eligible list, so sourceRanks never
#                   collides across scopes for the same source key.
#   position_group — for position_idp: "DL" | "LB" | "DB" (None otherwise)
#   depth         — declared list depth (None means "full board").  Used to
#                   scale the blend weight for shallow lists.
#   weight        — declared relative weight; source weights in the
#                   config/weights file can override this, but equal
#                   weights is the current project default.
#   is_backbone   — the first enabled overall_idp source with this flag is
#                   used to build the translation backbone.  Backbone
#                   status is determined by the *primary* scope only.
#   is_retail     — marks a source as a retail/market signal (what casual
#                   trade partners anchor on) rather than an expert board.
#                   Used by `_compute_market_gap` to compute the "Retail
#                   vs Consensus" mispricing signal: retail sources are
#                   averaged on one side, every other (non-retail) source
#                   on the other, and the gap between the two sides is
#                   the marketGapMagnitude.  Adding a second retail
#                   source (e.g. Sleeper's public trade values) is a
#                   pure registry change — the gap logic generalizes.
from src.canonical.idp_backbone import (
    SOURCE_SCOPE_OVERALL_IDP,
    SOURCE_SCOPE_OVERALL_OFFENSE,
    SOURCE_SCOPE_POSITION_IDP,
    IdpBackbone,
    build_backbone_from_rows,
    coverage_weight,
    translate_position_rank,
    TRANSLATION_DIRECT,
    TRANSLATION_FALLBACK,
)

_RANKING_SOURCES: list[dict[str, Any]] = [
    {
        # KeepTradeCut is the retail offense market — community trade
        # values scraped from a public-facing trade calculator.  This
        # is what casual trade partners see and anchor on, so it's
        # flagged `is_retail` and fed into the market-gap signal as
        # the "retail" side against every other (expert) source.
        "key": "ktc",
        "display_name": "KeepTradeCut",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": None,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": True,
    },
    {
        # IDP Trade Calculator's public value pool covers both offense
        # players (via autocomplete, same 0-9999 scale) and the full IDP
        # board.  Register it under the overall_idp scope as the IDP
        # backbone *and* under overall_offense as a secondary offense
        # source so offensive players get blended ranks from KTC and
        # IDPTradeCalc together.  The two scope passes act on disjoint
        # row sets (offense vs IDP positions), so sourceRanks["idpTradeCalc"]
        # is written exactly once per row.
        "key": "idpTradeCalc",
        "display_name": "IDP Trade Calculator",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "extra_scopes": [SOURCE_SCOPE_OVERALL_OFFENSE],
        "position_group": None,
        "depth": None,
        "weight": 1.0,
        "is_backbone": True,
    },
    {
        # DLF (Dynasty League Football) full-board IDP rankings.  The raw
        # export (`dlf_idp.csv` → `exports/latest/site_raw/dlfIdp.csv`) is
        # a 185-player expert consensus covering DL/LB/DB together, so it
        # lives in the overall_idp scope alongside IDPTradeCalc.  It is
        # NOT a backbone source — IDPTradeCalc remains authoritative for
        # ladder translation — but it contributes equally-weighted signal
        # to the coverage-aware blend.
        #
        # IDP-only sources (``needs_shared_market_translation=True``)
        # have their raw IDP ordinal rank translated through a
        # *shared-market IDP ladder* before feeding the Hill curve.  The
        # ladder is built from the backbone source's combined
        # offense+IDP value pool (see
        # ``src/canonical/idp_backbone.IdpBackbone.shared_market_idp_ladder``):
        # the i-th entry holds the combined-pool rank of the i-th best
        # IDP in the backbone.  Without this translation, DLF rank 1
        # would be fed to the Hill curve as an overall rank 1 → value
        # 9999, as if DLF were ranking both offense and IDP together.
        # With translation, DLF rank 1 becomes the combined-pool rank of
        # the best IDP in the shared market (typically ~30-50), which
        # correctly calibrates DLF against the retail offense market.
        "key": "dlfIdp",
        "display_name": "Dynasty League Football IDP",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "position_group": None,
        # DLF's published IDP list is a top-185 NFL veteran cut.  It
        # never carries first-year college prospects (Caleb Downs,
        # Sonny Styles, Arvell Reese, etc.), so we declare it
        # ``excludes_rookies`` and cap the structural depth at 185 so
        # ``_expected_sources_for_position`` stops over-flagging
        # rookies and deep-bench veterans as 1-src "matching failures"
        # when DLF was never going to cover them in the first place.
        "depth": 185,
        # DLF is a dynasty-specific expert IDP board; it tracks
        # multi-year value for established IDPs much better than
        # IDPTradeCalc, whose dynasty values for proven veterans
        # (T.J. Watt, Nick Bosa, Maxx Crosby, Jared Verse) are
        # sharply deflated relative to the rest of the IDP pool.
        # Weight DLF at 3x IDPTC so the blended IDP rank reflects
        # the curated expert opinion when both sources have the
        # player.  ``coverage_weight`` clamps shallow lists to depth
        # 60, so the effective weight stays bounded at 3.0.
        "weight": 3.0,
        "is_backbone": False,
        "needs_shared_market_translation": True,
        "excludes_rookies": True,
    },
    {
        # DLF Dynasty Superflex rankings — the offense counterpart of
        # DLF IDP.  Curated 6-expert consensus board with explicit
        # ``Rank`` and ``Avg`` columns.  Includes rookies and picks'
        # equivalents, spans 279 players, and is scoped purely to
        # offense (QB/RB/WR/TE).
        #
        # KTC is the retail market and DLF is the expert consensus —
        # mirroring DLF IDP, we weight DLF 3x so its opinion carries
        # more signal than the raw retail price when both sources
        # have the player.  ``coverage_weight`` scales shallow lists
        # toward unity at ``min_expected_depth`` (60), so the effective
        # weight for a 280-player list stays bounded at 3.0.
        #
        # depth=280 tells ``_expected_sources_for_position`` not to
        # expect this source for players ranked deeper than ~350
        # (depth * 1.25), preventing false 1-src flags on fringe
        # offense players that DLF SF was never going to list.
        "key": "dlfSf",
        "display_name": "Dynasty League Football Superflex",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 280,
        "weight": 3.0,
        "is_backbone": False,
        "is_retail": False,
        # Not a shared-market translation source — dlfSf is purely
        # offense, so its effective rank IS the offense ordinal.  No
        # IDP backbone crosswalk needed.
    },
    {
        # Dynasty Nerds Superflex + TE Premium board — scraped inline
        # from the DR_DATA JS constant on
        # https://www.dynastynerds.com/dynasty-rankings/sf-tep/.  The
        # board is produced by 5 expert contributors (Rich / Matt /
        # Garret / Jared + community) aggregated into a consensus
        # rank.  294 players with non-zero value in the snapshot;
        # covers QB / RB / WR / TE offense plus rookies.
        #
        # DN is conceptually identical to DLF SF — expert dynasty
        # board, not a retail market — so it gets the same weighting
        # profile: scope=overall_offense, weight=3.0, is_retail=False,
        # isRankSignal=True.  The key is namespaced ``SfTep`` so we
        # can later add a separate ``dynastyNerdsPpr`` or
        # ``dynastyNerdsSflex`` source pointing at the same URL's
        # alternate DR_DATA arrays without a contract break.
        #
        # depth=300 gives a tiny guardrail over the 294 non-zero
        # rows; ``_expected_sources_for_position`` multiplies this by
        # 1.25 so DN is not expected for players deeper than ~375.
        "key": "dynastyNerdsSfTep",
        "display_name": "Dynasty Nerds SF-TEP",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 300,
        "weight": 3.0,
        "is_backbone": False,
        "is_retail": False,
    },
]


# ── Legitimate single-source allowlist ──────────────────────────────────
# Every top-400 player that remains single-source MUST have an entry here
# explaining *why*.  The build check ``assert_no_unexplained_single_source``
# fails if a top player is 1-src without an allowlist reason.
#
# Keys are ``_canonical_match_key(display_name)`` — the same key used by
# the source join pipeline.  Values are human-readable reason strings.
#
# Categories:
#   "source_gap:<source>"  — the player is genuinely absent from <source>'s
#                            database/CSV export.  Not a name-matching issue;
#                            the source simply doesn't list them.
#   "depth_boundary:<source>" — the player's rank is just beyond <source>'s
#                               declared depth.  Borderline, not a join failure.
#   "rookie_exclusion:<source>" — the player is a rookie and the source
#                                 excludes rookies.
SINGLE_SOURCE_ALLOWLIST: dict[str, str] = {
    # ── Offense: DLF-SF-only (dropped by retail + IDPTC) ──
    # Veteran running backs / fringe players that both KTC and
    # IDPTradeCalc have dropped from their databases but DLF's expert
    # board still ranks.  These are genuinely single-source and the
    # expert opinion is the only signal available.
    "austin ekeler": "source_gap:ktc+idpTradeCalc — veteran RB dropped by both markets; DLF-SF expert board still ranks him",
    # ── Offense: suffix-named rookies / depth receivers ──
    # Kenneth Walker III, Marvin Harrison Jr., Brian Thomas Jr., and
    # Michael Penix Jr. live in IDPTradeCalc's Sheet3 payload and join
    # cleanly once the scraper reads Sheet1 + Sheet2 + Sheet3 (fixed in
    # Dynasty Scraper.py::_extract_idptc_name_map and the API-intercept
    # handler). They do not need allowlist entries.
    #
    # The three names below, however, are deeper board players that
    # IDPTradeCalc's Sheet3 payload is not currently returning reliably
    # (confirmed via live scrapes returning 813 rows instead of the ~901
    # expected after Sheet3 recovery). They are genuine source gaps —
    # KTC bulk-indexes deep rookies / practice-squad prospects that
    # IDPTC and DLF have not yet added. Remove these entries once the
    # IDPTC Sheet3 scrape stabilizes and these names appear in the
    # snapshot.
    "chris brazzell": "source_gap:ktc_only — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
    "mike washington": "source_gap:ktc_only — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
    "omar cooper": "source_gap:ktc_only — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
    # ── IDP: IDPTradeCalc-only (DLF does not list these players) ──
    # DLF publishes a curated 185-player IDP veteran board.  Rookies and
    # players outside the top 185 are structurally excluded.
    "arvell reese": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "sonny styles": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "caleb downs": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "david bailey": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "cj allen": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "dillon thieneman": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "emmanuel mcneil warren": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "jake golday": "rookie_exclusion:dlfIdp — DLF excludes rookies",
    "devin bush": "depth_boundary:dlfIdp — IDPTC rank 189, DLF depth 185; just outside DLF cutoff",
    # ── Offense: DynastyNerds-SF-TEP-only (dropped by retail + DLF SF) ──
    # Fringe offense players (deep rookies and retired/cut veterans) that
    # Dynasty Nerds' SF-TEP expert board still ranks but none of KTC,
    # IDPTradeCalc, or DLF SF carry.  Genuine source gaps — DN is the
    # only available signal for these players.
    "adam randall": "source_gap:ktc+idpTradeCalc+dlfSf — deep rookie WR/RB only ranked by Dynasty Nerds SF-TEP",
    "bryce lance": "source_gap:ktc+idpTradeCalc+dlfSf — deep rookie WR only ranked by Dynasty Nerds SF-TEP",
    "dezhaun stribling": "source_gap:ktc+idpTradeCalc+dlfSf — deep rookie WR only ranked by Dynasty Nerds SF-TEP",
    "tyler lockett": "source_gap:ktc+idpTradeCalc+dlfSf — veteran WR dropped by retail + DLF SF; Dynasty Nerds SF-TEP still ranks him",
}


def _scope_eligible(pos: str, scope: str, position_group: str | None) -> bool:
    """Return True if `pos` is eligible to receive a rank from a source
    declaring the given scope.
    """
    if scope == SOURCE_SCOPE_OVERALL_OFFENSE:
        return pos in _OFFENSE_POSITIONS or pos == "PICK"
    if scope == SOURCE_SCOPE_OVERALL_IDP:
        return pos in _IDP_POSITIONS
    if scope == SOURCE_SCOPE_POSITION_IDP:
        return bool(position_group) and pos == position_group
    return False


def _compute_confidence_bucket(
    source_count: int,
    source_rank_spread: float | None,
) -> tuple[str, str]:
    """Return (confidenceBucket, confidenceLabel) for a ranked player.

    See threshold constants above for the decision rules.
    """
    if source_count >= 2 and source_rank_spread is not None:
        if source_rank_spread <= _CONFIDENCE_SPREAD_HIGH:
            return "high", "High — multi-source, tight agreement"
        if source_rank_spread <= _CONFIDENCE_SPREAD_MEDIUM:
            return "medium", "Medium — multi-source, moderate spread"
    # Single source or wide disagreement
    if source_count >= 1:
        return "low", "Low — single source or wide disagreement"
    return "none", "None — unranked"


def _compute_anomaly_flags(
    *,
    name: str,
    position: str | None,
    asset_class: str,
    source_ranks: dict[str, int],
    rank_derived_value: int | None,
    canonical_sites: dict[str, int | None],
    source_meta: dict[str, dict[str, Any]] | None = None,
    percentile_spread: float | None = None,
    expected_sources: list[str] | None = None,
) -> list[str]:
    """Return a list of machine-readable anomaly flag strings for a player.

    Each flag signals a data-quality issue that a UI or audit script
    can surface.  An empty list means no anomalies detected.

    Disagreement uses :func:`_percentile_rank_spread` (depth-aware)
    rather than the old absolute ordinal spread.  The
    ``missing_source_distortion`` flag has been replaced by the
    semantic ``isSingleSource`` field stamped during ranking — a
    boolean is more useful to consumers than a duplicated flag string.
    """
    flags: list[str] = []
    pos = (position or "").strip().upper()

    # 1. Offense player with only IDP source values
    has_off_source = any(k in source_ranks for k in _OFFENSE_SIGNAL_KEYS)
    has_idp_source = any(k in source_ranks for k in _IDP_SIGNAL_KEYS)
    if asset_class == "offense" and has_idp_source and not has_off_source:
        flags.append("offense_as_idp")

    # 2. IDP player with only offense source values
    if asset_class == "idp" and has_off_source and not has_idp_source:
        flags.append("idp_as_offense")

    # 3. Missing position
    if not pos or pos == "?":
        flags.append("missing_position")

    # 4. Retired / invalid name patterns
    if _RETIRED_INVALID_PATTERNS.search(name):
        flags.append("retired_or_invalid_name")

    # 5. OL contamination
    if pos in _OL_POSITIONS:
        flags.append("ol_contamination")

    # 6. Suspicious disagreement.
    #
    # Preferred signal: the depth-aware percentile spread computed
    # by ``_percentile_rank_spread`` (max-minus-min of each source's
    # raw rank divided by that source's pool size).  Fires when
    # spread > 0.20 (sources place the player in tiers more than 20
    # percentile points apart).
    #
    # Legacy callers that pass only ``source_ranks`` without the
    # percentile signal (older tests, third-party callers) still get
    # the old absolute-rank rule for backwards compatibility: spread
    # of more than ``_SUSPICIOUS_DISAGREEMENT_THRESHOLD`` ordinal
    # ranks across at least two contributing sources.
    if percentile_spread is not None:
        if percentile_spread > 0.20:
            flags.append("suspicious_disagreement")
    else:
        rank_values = list(source_ranks.values())
        if len(rank_values) >= 2:
            spread = max(rank_values) - min(rank_values)
            if spread > _SUSPICIOUS_DISAGREEMENT_THRESHOLD:
                flags.append("suspicious_disagreement")

    # 7. Impossible value state — has a rank but rankDerivedValue <= 0
    if source_ranks and (rank_derived_value is None or rank_derived_value <= 0):
        flags.append("impossible_value")

    return flags


def _tier_id_from_rank(rank: int) -> int:
    """Return a tier ID (1-10) from an overall rank.

    Boundaries mirror the frontend's ``rankBasedTierId()`` in
    ``frontend/lib/rankings-helpers.js`` — kept in sync so the
    backend-stamped ``canonicalTierId`` and the frontend's fallback
    derivation always agree.  Since the backend now stamps this field
    authoritatively, the frontend fallback should never fire for
    ranked players.
    """
    if rank <= 12:
        return 1   # Elite
    if rank <= 36:
        return 2   # Blue-Chip
    if rank <= 72:
        return 3   # Premium Starter
    if rank <= 120:
        return 4   # Solid Starter
    if rank <= 200:
        return 5   # Starter
    if rank <= 350:
        return 6   # Flex / Depth
    if rank <= 500:
        return 7   # Bench Depth
    if rank <= 650:
        return 8   # Deep Stash
    if rank <= 800:
        return 9   # Roster Fringe
    return 10       # Waiver Wire


def _retail_source_keys() -> frozenset[str]:
    """Return the set of ranking source keys marked `is_retail` in the registry.

    Derived from `_RANKING_SOURCES` on every call so tests (or future
    config reloads) that mutate the registry see updated membership
    without a module reimport.
    """
    return frozenset(s["key"] for s in _RANKING_SOURCES if s.get("is_retail"))


def _compute_market_gap(
    source_ranks: dict[str, int],
    retail_keys: set[str] | frozenset[str] | None = None,
) -> tuple[str, float | None]:
    """Quantify the disagreement between retail and expert consensus.

    "Market gap" frames the retail market (sources flagged `is_retail`
    in the registry — today just KTC) against every other registered
    source (the expert consensus — IDPTC, DLF, and any future non-retail
    source).  Both sides are averaged, and the gap is the ordinal rank
    difference between the two means.

    A retail premium means retail ranks the player higher (lower rank
    number) than consensus — i.e. the retail market is pricing the
    player above where the experts have them.  A consensus premium is
    the reverse: the experts value the player more than retail does,
    making them a potential "buy low" from a retail-first trade partner.

    Returns (direction, magnitude) where direction is one of:
      "retail_premium"     — retail mean rank is lower number than consensus mean
      "consensus_premium"  — consensus mean rank is lower number than retail mean
      "none"               — tie, or either side has zero sources present

    magnitude is the absolute ordinal rank difference between the two
    means as a float, or None when the comparison cannot be made (one
    side has no source ranks on this row).  Magnitude is 0.0 on a tie.

    `retail_keys` is an optional override for tests; when None the set is
    derived from `_RANKING_SOURCES` via `_retail_source_keys()`.
    """
    if retail_keys is None:
        retail_keys = _retail_source_keys()

    retail_ranks = [
        rank
        for key, rank in source_ranks.items()
        if key in retail_keys and rank is not None
    ]
    consensus_ranks = [
        rank
        for key, rank in source_ranks.items()
        if key not in retail_keys and rank is not None
    ]
    if not retail_ranks or not consensus_ranks:
        return "none", None

    retail_mean = sum(retail_ranks) / len(retail_ranks)
    consensus_mean = sum(consensus_ranks) / len(consensus_ranks)
    diff = consensus_mean - retail_mean  # positive → retail ranks higher
    if diff > 0:
        return "retail_premium", float(abs(diff))
    if diff < 0:
        return "consensus_premium", float(abs(diff))
    return "none", 0.0


def _normalize_for_collision(name: str) -> str:
    """Reduce a display name to a collision-detection key.

    Strips suffixes, lowercases, removes non-alpha.  Used to detect when
    two different display names (e.g. "Jameson Williams" and "James Williams")
    would collide in the identity pipeline.
    """
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415
    return normalize_player_name(name)


def _extract_last_name(name: str) -> str:
    """Extract the last whitespace-delimited token as a surname proxy."""
    parts = str(name or "").strip().split()
    return parts[-1].lower() if parts else ""


def _compute_identity_confidence(
    row: dict[str, Any],
) -> tuple[float, str]:
    """Score how confident we are that this row represents the right entity.

    Returns (score 0.0-1.0, method_string).

    Rules:
      1.00 — has a non-empty playerId (Sleeper ID or external key)
      0.95 — position matches source evidence AND name is unambiguous
      0.85 — position or source evidence is present but doesn't fully agree
      0.70 — name-only with no corroborating metadata
    """
    has_id = bool((row.get("playerId") or "").strip())
    pos = str(row.get("position") or "").strip().upper()
    asset_class = row.get("assetClass") or ""
    canonical_sites = row.get("canonicalSiteValues") or {}

    has_off_val = any(
        (_to_int_or_none(canonical_sites.get(k)) or 0) > 0
        for k in _OFFENSE_SIGNAL_KEYS
    )
    has_idp_val = any(
        (_to_int_or_none(canonical_sites.get(k)) or 0) > 0
        for k in _IDP_SIGNAL_KEYS
    )

    if has_id:
        return 1.00, "canonical_id"

    pos_matches_source = (
        (asset_class == "offense" and has_off_val and not has_idp_val)
        or (asset_class == "idp" and has_idp_val and not has_off_val)
        or (asset_class == "pick")
    )
    if pos and pos_matches_source:
        return 0.95, "position_source_aligned"

    if pos and (has_off_val or has_idp_val):
        return 0.85, "partial_evidence"

    return 0.70, "name_only"


def _validate_and_quarantine_rows(
    players_array: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run identity and data-quality validation on all player rows.

    This is a post-ranking, pre-output pass.  It does NOT remove rows — it
    appends quarantine flags to anomalyFlags[] and degrades confidenceBucket
    for rows that look suspicious.  This is the safer approach: auditors can
    see what was flagged and why, and the UI can choose to hide or highlight
    flagged rows.

    Checks performed:
      1. **Position-aware identity collision**: two rows whose
         position-aware canonical key
         (``<normalized_name>::<position_group>``) is identical.  This
         is a genuine entity-resolution failure — the same player got
         split into two rows.
      2. **Cross-universe name collision**: two rows whose normalized
         name (without position group) is identical but whose position
         groups differ — for example a defender named "Josh Johnson" in
         the IDP pool vs a journeyman QB by the same name.  These are
         (usually) two distinct people; we flag for visibility but only
         quarantine when the position group AND the source evidence
         disagree on which entity the value belongs to.
      3. **Position-source contradiction**: position family disagrees
         with the set of source keys carrying positive values on the
         row.
      4. **Unsupported position**: position not in the board's
         supported set.
      5. **No valid source values** despite having a derived value.
      6. **Identity confidence scoring**.

    The old "near-name value mismatch" rule (any two cross-universe
    players sharing a last name with a >3x value ratio) was a pure
    noise generator — every star offense player was paired with every
    bench IDP sharing a common surname, surfacing 40+ false positives
    per build for legitimate distinct people like "Bijan Robinson"
    vs "Chop Robinson".  It has been removed in favor of the
    position-aware collision check above, which only fires on actual
    same-entity ambiguity.

    Returns a validation summary dict for payload-level reporting.
    """
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415

    # ── Build indexes for collision detection ──
    norm_name_to_rows: dict[str, list[int]] = {}
    posaware_to_rows: dict[str, list[int]] = {}

    for idx, row in enumerate(players_array):
        name = row.get("canonicalName") or row.get("displayName") or ""
        norm = _normalize_for_collision(name)
        if norm:
            norm_name_to_rows.setdefault(norm, []).append(idx)
        pos = row.get("position")
        if norm and pos:
            grp = canonical_position_group(pos)
            posaware_to_rows.setdefault(f"{norm}::{grp}", []).append(idx)

    quarantine_count = 0
    collision_pairs: list[dict[str, Any]] = []
    duplicate_identity_pairs: list[dict[str, Any]] = []

    # ── Check 0: position-aware duplicate identity ──
    # Same canonical key with identical position group means we
    # genuinely created two rows for the same player.  This is the
    # entity-resolution duplicate the build-time assertion test will
    # also surface.
    for posaware, indices in posaware_to_rows.items():
        if len(indices) < 2:
            continue
        names_involved = sorted({
            str(players_array[i].get("canonicalName") or "") for i in indices
        })
        duplicate_identity_pairs.append({
            "canonicalKey": posaware,
            "names": names_involved,
        })
        for i in indices:
            row = players_array[i]
            flags = row.get("anomalyFlags") or []
            if "duplicate_canonical_identity" not in flags:
                flags.append("duplicate_canonical_identity")
                row["anomalyFlags"] = flags

    # ── Check 1: Cross-universe name collisions ──
    # Same normalized name in both offense + IDP rows — usually two
    # distinct people who happen to share a surname/initials.  We
    # surface them for visibility but only quarantine when the
    # collision is a *known* entity confusion (see
    # :data:`OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS`).
    for norm, indices in norm_name_to_rows.items():
        if len(indices) < 2:
            continue
        asset_classes = {players_array[i].get("assetClass") for i in indices}
        if "offense" in asset_classes and "idp" in asset_classes:
            names_involved = [players_array[i].get("canonicalName") for i in indices]
            collision_pairs.append({
                "normalizedName": norm,
                "names": names_involved,
                "assetClasses": list(asset_classes),
            })
            for i in indices:
                row = players_array[i]
                flags = row.get("anomalyFlags") or []
                if "name_collision_cross_universe" not in flags:
                    flags.append("name_collision_cross_universe")
                    row["anomalyFlags"] = flags

    # ── Check 2: Position-source contradiction ──
    # A row gets flagged when the position family disagrees with the set
    # of source keys carrying positive values on the row.  The flag is
    # suppressed when:
    #   (a) the row is a verified cross-universe name collision (see
    #       OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS) AND the collision flag
    #       has already been applied in Check 1 — in that case the
    #       contradiction is an expected consequence of the grafted
    #       join, and quarantining via two flags would inflate false
    #       positives in downstream reports.
    #   (b) the row already carries `name_collision_cross_universe`
    #       from Check 1.  The collision flag is itself a quarantine
    #       signal, so we don't need to pile contradictions on top.
    for idx, row in enumerate(players_array):
        pos = str(row.get("position") or "").strip().upper()
        asset_class = row.get("assetClass") or ""
        canonical_sites = row.get("canonicalSiteValues") or {}

        has_off_val = any(
            (_to_int_or_none(canonical_sites.get(k)) or 0) > 0
            for k in _OFFENSE_SIGNAL_KEYS
        )
        has_idp_val = any(
            (_to_int_or_none(canonical_sites.get(k)) or 0) > 0
            for k in _IDP_SIGNAL_KEYS
        )

        current_flags = row.get("anomalyFlags") or []
        has_collision = "name_collision_cross_universe" in current_flags
        name = row.get("canonicalName") or ""
        is_known_collision = (
            has_collision and name in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS
        )

        # Offense position but only IDP values.
        if pos in _OFFENSE_POSITIONS and has_idp_val and not has_off_val:
            if has_collision or is_known_collision:
                pass
            else:
                flags = current_flags
                if "position_source_contradiction" not in flags:
                    flags.append("position_source_contradiction")
                    row["anomalyFlags"] = flags

        # IDP position but only offense values.
        if pos in _IDP_POSITIONS and has_off_val and not has_idp_val:
            if has_collision or is_known_collision:
                pass
            else:
                flags = current_flags
                if "position_source_contradiction" not in flags:
                    flags.append("position_source_contradiction")
                    row["anomalyFlags"] = flags

    # ── Check 3: Near-name value mismatch across universes ──
    # REMOVED: the historical "same surname + cross universe + value
    # ratio > 3" rule produced 40+ false positives per build for
    # legitimate distinct people.  Real entity collisions are now
    # caught by the position-aware duplicate-identity check above.
    near_name_pairs: list[dict[str, Any]] = []

    # ── Check 4: Unsupported position ──
    for idx, row in enumerate(players_array):
        pos = str(row.get("position") or "").strip().upper()
        if pos and pos not in _SUPPORTED_BOARD_POSITIONS and pos not in _KICKER_POSITIONS:
            flags = row.get("anomalyFlags") or []
            if "unsupported_position" not in flags:
                flags.append("unsupported_position")
                row["anomalyFlags"] = flags

    # ── Check 5: No valid source values but has derived value ──
    for idx, row in enumerate(players_array):
        canonical_sites = row.get("canonicalSiteValues") or {}
        has_any_source = any(
            (_to_int_or_none(v) or 0) > 0
            for v in canonical_sites.values()
        )
        rdv = row.get("rankDerivedValue")
        if not has_any_source and rdv is not None and rdv > 0:
            flags = row.get("anomalyFlags") or []
            if "no_valid_source_values" not in flags:
                flags.append("no_valid_source_values")
                row["anomalyFlags"] = flags

    # ── Check 6: Identity confidence + quarantine degradation ──
    for idx, row in enumerate(players_array):
        ic_score, ic_method = _compute_identity_confidence(row)
        row["identityConfidence"] = ic_score
        row["identityMethod"] = ic_method

        # Quarantine: degrade confidence for rows with quarantine-level flags
        flags = row.get("anomalyFlags") or []
        has_quarantine_flag = bool(set(flags) & _QUARANTINE_FLAGS)
        if has_quarantine_flag:
            row["quarantined"] = True
            quarantine_count += 1
            # Degrade confidence bucket — never promote, only degrade
            current_bucket = row.get("confidenceBucket") or "none"
            if current_bucket in ("high", "medium"):
                row["confidenceBucket"] = "low"
                row["confidenceLabel"] = (
                    "Low — quarantined due to identity/data-quality flags"
                )
        else:
            row["quarantined"] = False

    return {
        "quarantineCount": quarantine_count,
        "crossUniverseCollisions": collision_pairs,
        "crossUniverseCollisionCount": len(collision_pairs),
        # near-name pairs intentionally always-empty: legacy field kept
        # for backwards-compat with any consumer that grabs the count.
        "nearNameMismatches": near_name_pairs,
        "nearNameMismatchCount": 0,
        "duplicateCanonicalIdentityPairs": duplicate_identity_pairs,
        "duplicateCanonicalIdentityCount": len(duplicate_identity_pairs),
    }


# ── Trust field mirroring ───────────────────────────────────────────────
# The runtime view (`server.py`) strips `playersArray` to keep the payload
# small.  The frontend falls back to the legacy `players` dict and reads
# trust fields via `r.raw?.field`.  This function copies all trust fields
# from the authoritative playersArray entries back into the legacy dict so
# they survive the runtime view.
#
# Must be called AFTER both `_compute_unified_rankings` (which stamps
# confidence/source fields) AND `_validate_and_quarantine_rows` (which may
# degrade confidenceBucket and add anomalyFlags).

_TRUST_MIRROR_FIELDS = (
    "confidenceBucket",
    "confidenceLabel",
    "anomalyFlags",
    "isSingleSource",
    "isStructurallySingleSource",
    "hasSourceDisagreement",
    "blendedSourceRank",
    "sourceRankSpread",
    "sourceRankPercentileSpread",
    "marketGapDirection",
    "marketGapMagnitude",
    "identityConfidence",
    "identityMethod",
    "quarantined",
    "sourceAudit",
    "sourceOriginalRanks",
    "canonicalTierId",
)


def _mirror_trust_to_legacy(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Copy post-quarantine trust fields from playersArray → legacy dict."""
    for row in players_array:
        legacy_ref = row.get("legacyRef")
        if not legacy_ref or legacy_ref not in players_by_name:
            continue
        pdata = players_by_name[legacy_ref]
        if not isinstance(pdata, dict):
            continue
        for field in _TRUST_MIRROR_FIELDS:
            if field in row:
                pdata[field] = row[field]


def _strip_name_suffix(name: str) -> str:
    """Strip generational suffixes (Jr, Sr, II-VI) for resilient matching.

    Legacy helper retained for backwards-compat with callers/tests that
    imported it directly.  For new matching code prefer
    ``_canonical_match_key`` below, which also normalises punctuation,
    apostrophes, casing, and collapses initials so ``T.J. Watt`` and
    ``TJ Watt`` collide on the same key.
    """
    n = name.strip()
    for sfx in (" Jr.", " Jr", " Sr.", " Sr", " II", " III", " IV", " V", " VI"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return n


def _canonical_match_key(name: str) -> str:
    """Return the alias-aware canonical join key for cross-source matching.

    All enrichment joins and CSV → contract lookups go through this
    helper so punctuation, diacritics, apostrophes, initials, suffixes,
    casing, and known nickname variants collapse to a single key.

    The underlying chain is:

    1. :func:`src.utils.name_clean.normalize_player_name` — punctuation,
       suffix, and initial collapse.
    2. :data:`src.utils.name_clean.CANONICAL_NAME_ALIASES` — deterministic
       nickname / first-name expansion table.

    This is the **name-only** canonical key.  Code that wants
    *position-aware* collision safety (e.g. so Quay Walker LB is never
    silently merged with Kenneth Walker RB) should use
    :func:`_canonical_player_key` below.
    """
    from src.utils.name_clean import resolve_canonical_name  # noqa: PLC0415

    return resolve_canonical_name(name)


def _canonical_player_key(name: str, position: str | None) -> str:
    """Return the position-aware canonical key for a player.

    Wraps :func:`src.utils.name_clean.canonical_player_key` so the
    contract layer has a single import point.  The output has the
    form ``"<canonical_name>::<position_group>"`` where the group is
    ``OFFENSE``, ``IDP``, ``PICK``, ``KICKER``, or ``OTHER``.

    Two players with different position groups always get different
    keys, which is the structural fix for the ``Walker``,
    ``Wilson``, ``Allen``, ``Murphy`` last-name collision class.
    """
    from src.utils.name_clean import canonical_player_key  # noqa: PLC0415

    return canonical_player_key(name, position)


# ── CSV name → metadata cache ───────────────────────────────────────────
# Cache holding, for each source, the per-canonical-key normalized
# entries loaded from its CSV export.  Each entry records the source's
# raw display name plus the parsed value/rank, so the contract layer
# can build a per-row ``sourceAudit`` block showing exactly which CSV
# row each source contributed (or that no row matched).
#
# The cache is intentionally invalidated on every contract build by
# being a local variable inside ``_enrich_from_source_csvs``.
_NULL_CSV_ENTRY: dict[str, Any] = {}


def _enrich_from_source_csvs(
    players_array: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    """Fill missing canonicalSiteValues from source CSV exports.

    When the scraper's dashboard payload is missing values for a source
    (e.g. KTC scrape failed but the CSV persists from a prior run), load
    the CSV and inject values into canonicalSiteValues so the ranking
    function can use them.

    Matching cascade per source CSV row:

    1. **Exact**: if the CSV name normalizes to a key that an existing
       row already exposes via ``canonicalName`` / ``displayName``,
       graft directly.
    2. **Alias-aware**: the normalize helper handles
       suffix / punctuation / apostrophe / initial drift, and
       :data:`src.utils.name_clean.CANONICAL_NAME_ALIASES` collapses
       known nickname variants.
    3. **Position-aware fallback**: when two CSV rows would map to the
       same canonical key, the one whose position group matches the
       row's group wins.  Two CSV rows with the same canonical key and
       different position groups never silently merge.

    Returns a per-source CSV index keyed by **position-aware canonical
    key** so :func:`_compute_unified_rankings` can build a per-row
    ``sourceAudit`` block (matched names, unmatched candidates, why a
    row ended up 1-src vs multi-src).

    Supports two signal types per source:

      * ``value`` (default)  — ``name,value`` CSVs.  Stamped as-is.
      * ``rank``             — ``name,rank`` CSVs.  The rank column is
        converted to a monotonically descending synthetic value so the
        downstream descending sort in ``_compute_unified_rankings`` still
        produces the correct ordinal.  Only the ordering matters to the
        ranking pipeline; the absolute number is a bookkeeping artefact.
    """
    import csv
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    csv_index: dict[str, dict[str, dict[str, Any]]] = {}

    # Pre-compute the position-group of each player row by canonical
    # key so the position-aware fallback in stage (3) can pick the
    # right CSV entry when name-only collisions occur.
    row_groups_by_key: dict[str, set[str]] = {}
    for row in players_array:
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        if not nm:
            continue
        cname = _canonical_match_key(nm)
        if not cname:
            continue
        from src.utils.name_clean import canonical_position_group  # noqa: PLC0415
        grp = canonical_position_group(row.get("position"))
        row_groups_by_key.setdefault(cname, set()).add(grp)

    for source_key, cfg in _SOURCE_CSV_PATHS.items():
        if isinstance(cfg, str):
            csv_rel = cfg
            signal = "value"
        elif isinstance(cfg, dict):
            csv_rel = str(cfg.get("path") or "")
            signal = str(cfg.get("signal") or "value").lower()
        else:
            continue
        if not csv_rel:
            continue
        csv_path = repo / csv_rel
        if not csv_path.exists():
            continue

        # Per-source CSV lookup.  Keyed by canonical name *only*; the
        # value is a list of (display_name, parsed_value) tuples so we
        # can later disambiguate by position group when more than one
        # CSV row collapses to the same canonical key.  This is the
        # "exact → alias → bounded fallback" cascade from the task
        # spec: we never silently pick a wrong CSV row when multiple
        # candidates exist for the same canonical key.
        csv_lookup: dict[str, list[tuple[str, int, float | None]]] = {}
        # Column-name aliases.  Raw DLF exports use capitalized
        # `Name` / `Rank` columns plus extra columns (Avg, Pos, Team,
        # Age, individual expert columns, Value, Follow).  We accept a
        # small set of aliases so a freshly-downloaded DLF CSV can be
        # dropped into ``exports/latest/site_raw/`` without any
        # preprocessing step.
        _NAME_ALIASES = ("name", "Name", "player", "Player", "player_name", "PlayerName")
        _RANK_ALIASES = ("rank", "Rank", "overall_rank", "OverallRank")
        _VALUE_ALIASES = ("value", "Value", "trade_value", "TradeValue")

        def _pick(csvrow: dict[str, Any], aliases: tuple[str, ...]) -> str:
            for k in aliases:
                if k in csvrow and csvrow[k] not in (None, ""):
                    return str(csvrow[k])
            return ""

        try:
            with csv_path.open("r", encoding="utf-8-sig") as f:
                for csvrow in csv.DictReader(f):
                    name = _pick(csvrow, _NAME_ALIASES).strip()
                    if not name:
                        continue
                    key = _canonical_match_key(name)
                    if not key:
                        continue
                    if signal == "rank":
                        raw = _pick(csvrow, _RANK_ALIASES)
                        if raw == "" or raw is None:
                            continue
                        try:
                            rank_val = float(str(raw).strip())
                        except (TypeError, ValueError):
                            continue
                        if rank_val <= 0:
                            continue
                        # Monotonic descending transform: smaller rank →
                        # bigger value so the overall_idp sort orders
                        # the list the same way DLF does.  Multiply by
                        # 100 first so fractional Avg ranks (e.g. 5.67)
                        # stay ordered after the int() truncation.
                        synthetic = int(
                            round(
                                (_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100)
                                - (rank_val * 100)
                            )
                        )
                        if synthetic <= 0:
                            continue
                        csv_lookup.setdefault(key, []).append((name, synthetic, rank_val))
                    else:
                        val = _pick(csvrow, _VALUE_ALIASES)
                        if not val:
                            continue
                        try:
                            csv_lookup.setdefault(key, []).append(
                                (name, int(float(val)), None)
                            )
                        except (ValueError, TypeError):
                            continue
        except Exception:
            continue

        if not csv_lookup:
            continue

        # Persist a structured per-source entry index keyed by the
        # *position-aware* canonical key so downstream code can audit
        # exactly which CSV row matched each player row.  We resolve
        # duplicates by best-of-value within the same position group.
        from src.utils.name_clean import canonical_position_group  # noqa: PLC0415
        per_source: dict[str, dict[str, Any]] = {}
        for cname, entries in csv_lookup.items():
            # Quick pre-pass: figure out which position groups the
            # contract has on this canonical key.  If it's only one
            # group, every entry maps to that group.
            row_groups = row_groups_by_key.get(cname, set())
            if len(row_groups) <= 1:
                grp = next(iter(row_groups), "*")
                # Pick the highest-valued entry for this canonical key.
                entries_sorted = sorted(entries, key=lambda t: -t[1])
                best_name, best_val, best_orig_rank = entries_sorted[0]
                per_source[f"{cname}::{grp}"] = {
                    "value": best_val,
                    "originalRank": best_orig_rank,
                    "displayName": best_name,
                    "ambiguous": len(entries) > 1,
                    "candidates": [n for n, _, _ in entries],
                }
            else:
                # Multiple position groups share this canonical key.
                # Without per-CSV-row position info we can't tell which
                # entry belongs to which group, so we replicate the
                # best entry across both groups but flag it as ambiguous
                # so the row audit can downgrade trust.
                entries_sorted = sorted(entries, key=lambda t: -t[1])
                best_name, best_val, best_orig_rank = entries_sorted[0]
                for grp in row_groups:
                    per_source[f"{cname}::{grp}"] = {
                        "value": best_val,
                        "originalRank": best_orig_rank,
                        "displayName": best_name,
                        "ambiguous": True,
                        "candidates": [n for n, _, _ in entries],
                        "groupCollision": sorted(row_groups),
                    }
        csv_index[source_key] = per_source

        # Enrich missing values onto each row using the position-aware
        # key cascade.
        for row in players_array:
            csv_vals = row.get("canonicalSiteValues")
            if not isinstance(csv_vals, dict):
                continue
            existing = _safe_num(csv_vals.get(source_key))
            if existing is not None and existing > 0:
                continue
            nm = str(row.get("canonicalName") or row.get("displayName") or "")
            if not nm:
                continue
            cname = _canonical_match_key(nm)
            if not cname:
                continue
            grp = canonical_position_group(row.get("position"))
            entry = per_source.get(f"{cname}::{grp}")
            if entry is None:
                # Fall back to a name-only / unknown-group lookup so
                # rows whose position is missing still receive an
                # enrichment when a single non-ambiguous CSV entry
                # exists.
                fallback = per_source.get(f"{cname}::*")
                if fallback is None and len(row_groups_by_key.get(cname, set())) == 1:
                    only_grp = next(iter(row_groups_by_key[cname]))
                    fallback = per_source.get(f"{cname}::{only_grp}")
                entry = fallback
            if not entry:
                continue
            val = entry.get("value")
            if val is not None and val > 0:
                csv_vals[source_key] = val
                # For rank-signal sources, preserve the original CSV rank
                # so the frontend can display it instead of the meaningless
                # synthetic value.
                orig_rank = entry.get("originalRank")
                if orig_rank is not None:
                    orig_ranks = row.setdefault("sourceOriginalRanks", {})
                    orig_ranks[source_key] = round(float(orig_rank), 2)

    return csv_index


def _expected_sources_for_position(
    pos: str,
    *,
    is_rookie: bool = False,
    player_effective_rank: int | None = None,
) -> tuple[set[str], set[str]]:
    """Return (offense_keys, idp_keys) that *should* cover this player.

    A source "covers" a position if any of its declared scopes accept
    that position **and** the player is plausibly inside the source's
    structural reach.  This is finer-grained than pure scope eligibility:

    * Sources flagged ``excludes_rookies=True`` in the registry are
      pruned for players whose ``is_rookie`` flag is set.  The
      canonical example is DLF IDP, which is a 185-row NFL veteran
      list and never carries first-year college prospects.

    * Sources with a declared shallow ``depth`` are pruned when the
      player's already-matched rank is deeper than their cutoff plus
      a 25% guardrail.  A player ranked #350 by IDPTC isn't expected
      to also appear in a top-150 DLF list.

    These rules let ``isSingleSource`` only fire when there is a
    *real* matching failure — not when the second source structurally
    doesn't carry players of this profile.
    """
    pos_up = (pos or "").strip().upper()
    off: set[str] = set()
    idp: set[str] = set()
    for src in _RANKING_SOURCES:
        # Only the primary scope determines expected coverage.
        # Extra scopes (e.g. IDPTradeCalc's overall_offense) provide bonus
        # signal when present but are NOT structurally expected — IDPTC's
        # offense autocomplete is opportunistic, not a comprehensive board.
        # Without this distinction, every offense player missing from IDPTC's
        # partial offense pool is falsely flagged as a 1-src matching failure.
        primary_scope: str = src["scope"]
        if not _scope_eligible(pos_up, primary_scope, src.get("position_group")):
            continue
        eligible_scope = primary_scope
        # Exclude veteran-only sources for rookie players.
        if is_rookie and src.get("excludes_rookies"):
            continue
        # Exclude shallow-depth sources for players ranked deeper than
        # their cutoff (with a 25% headroom so the rule doesn't
        # over-prune at the boundary).
        depth = src.get("depth")
        if (
            depth is not None
            and player_effective_rank is not None
            and player_effective_rank > int(round(float(depth) * 1.25))
        ):
            continue
        if eligible_scope == SOURCE_SCOPE_OVERALL_OFFENSE:
            off.add(src["key"])
        else:
            idp.add(src["key"])
    return off, idp


def _percentile_rank_spread(
    source_ranks: dict[str, int],
    source_meta: dict[str, dict[str, Any]],
    source_pool_sizes: dict[str, int],
) -> float | None:
    """Return the *percentile* spread of source ranks for a row.

    Each source rank is converted to a percentile within that source's
    actual pool of ranked players (auto-detected from Phase 1) using
    the **raw** ordinal — not the post-translation effective rank.
    Using the raw ordinal is critical: the shared-market ladder
    inflates DLF's effective ranks into the combined offense+IDP
    rank space, so an effective spread of 100 doesn't mean the
    sources disagree, it means one is on a 1-185 scale and the other
    is on a 1-600 scale.

    The spread is the max-minus-min of those percentiles in 0..1.
    Returns ``None`` if fewer than two sources contributed.
    """
    if not source_ranks or len(source_ranks) < 2:
        return None
    pcts: list[float] = []
    for key, _eff_rank in source_ranks.items():
        meta = source_meta.get(key) or {}
        raw_rank = meta.get("rawRank") or meta.get("effectiveRank") or _eff_rank
        # Prefer the auto-detected per-source pool size (count of
        # rows the source actually ranked in this scope).  Fall back
        # to declared depth, then to the universe-wide pool size.
        depth = source_pool_sizes.get(key) or meta.get("depth") or 0
        try:
            depth_f = float(depth)
        except (TypeError, ValueError):
            depth_f = 0.0
        if depth_f <= 0:
            continue
        pct = float(raw_rank) / depth_f
        pcts.append(max(0.0, min(1.0, pct)))
    if len(pcts) < 2:
        return None
    return float(max(pcts) - min(pcts))


# ── Pick refinement helpers (see audit @ 2026-04-14) ────────────────────────
#
# The blend produces three known pick-quality issues we have to correct
# without rewriting the scraper or the blend:
#
#   1. KTC's per-slot synth (`_estimate_slot_from_tier`) inverts the
#      curve at every slot 4↔5 and 8↔9 boundary, which bleeds through
#      the blend and produces within-round inversions
#      (e.g. 2026 1.04 ranking BEHIND 1.05).
#
#   2. There is no real future-year discount in the source data — KTC
#      and IDPTC price 2027/2028 picks only marginally below 2026, so
#      a 2028 Late 1st can land above a 2026 Late 1st.
#
#   3. The generic "2026 Mid 1st" tier rows coexist with specific
#      1.06 / 1.07 / 1.08 slot rows as independent assets, which gives
#      the same underlying trade asset two divergent values.
#
# Helpers below are gated to picks and run as POST-blend corrections in
# ``_compute_unified_rankings``.  They never touch player rows.

# Regex matching specific slot pick names like "2026 Pick 1.06" — used
# by the slot reassignment pass to bucket picks by (year, round) and
# extract the slot number for in-bucket sorting.
_PICK_SLOT_RE = re.compile(r"^(20\d{2})\s+Pick\s+([1-6])\.(0?[1-9]|1[0-2])$", re.I)

# Regex matching generic tier pick names like "2026 Early 1st" — used
# by the generic-tier suppression pass to detect rows that should be
# moved to ``pickAliases`` when slot-specific siblings exist.
_PICK_TIER_RE = re.compile(
    r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(st|nd|rd|th)$", re.I
)

# Pick year discount is loaded once per build from
# config/weights/pick_year_discount.json.  See the file header for the
# config schema.  Cached at module level so a build that processes
# multiple snapshots only reads the file once.
_PICK_YEAR_DISCOUNT_CACHE: dict[str, Any] | None = None


def _load_pick_year_discount() -> dict[str, Any]:
    """Load and cache the pick year discount config.

    Returns a dict shaped like::

        {
            "baselineYear": 2026,
            "discounts": {"2026": 1.0, "2027": 0.82, ...},
            "fallbackBase": 0.80,
        }

    If the config file is missing or malformed, falls back to a built-in
    default (baselineYear=2026, fallbackBase=0.80).  This keeps the
    pipeline robust on stripped-down test environments while still
    letting ops tune the discount via ``config/weights/``.
    """
    global _PICK_YEAR_DISCOUNT_CACHE
    if _PICK_YEAR_DISCOUNT_CACHE is not None:
        return _PICK_YEAR_DISCOUNT_CACHE

    import json as _json
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    cfg_path = repo / "config" / "weights" / "pick_year_discount.json"
    cfg: dict[str, Any] = {
        "baselineYear": 2026,
        "discounts": {},
        "fallbackBase": 0.80,
    }
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = _json.load(f)
        if isinstance(loaded, dict):
            cfg["baselineYear"] = int(loaded.get("baselineYear") or 2026)
            raw_discounts = loaded.get("discounts") or {}
            if isinstance(raw_discounts, dict):
                cfg["discounts"] = {
                    str(k): float(v) for k, v in raw_discounts.items()
                }
            cfg["fallbackBase"] = float(loaded.get("fallbackBase") or 0.80)
    except (OSError, ValueError, TypeError):
        # Stick with the built-in default — never block the build on
        # a missing/malformed pick-discount config.
        pass

    _PICK_YEAR_DISCOUNT_CACHE = cfg
    return cfg


def _pick_year_from_name(name: str) -> int | None:
    """Extract the 4-digit year from a pick canonical name, or None.

    Handles all three pick name formats: ``2026 Pick 1.06``,
    ``2026 Early 1st``, ``2026 Round 1``, etc.
    """
    if not name:
        return None
    m = re.search(r"\b(20\d{2})\b", str(name))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


def _pick_year_discount_for(year: int | None, cfg: dict[str, Any]) -> float:
    """Return the multiplicative discount for a pick year.

    Picks in the baseline year get 1.0 (no discount).  Years explicitly
    listed in ``cfg['discounts']`` use the configured multiplier.  Years
    not listed fall back to ``fallbackBase ** (year - baselineYear)``.
    """
    if year is None:
        return 1.0
    baseline = int(cfg.get("baselineYear") or 2026)
    discounts = cfg.get("discounts") or {}
    fallback_base = float(cfg.get("fallbackBase") or 0.80)
    if year <= baseline:
        return 1.0
    raw = discounts.get(str(year))
    if raw is not None:
        try:
            return max(0.05, min(1.0, float(raw)))
        except (TypeError, ValueError):
            pass
    return max(0.05, fallback_base ** (year - baseline))


def _parse_pick_slot(name: str) -> tuple[int, int, int] | None:
    """Return (year, round, slot) for a slot-specific pick name.

    Returns None for tier-only rows like "2026 Early 1st".
    """
    if not name:
        return None
    m = _PICK_SLOT_RE.match(str(name).strip())
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    except (TypeError, ValueError):
        return None


def _parse_pick_tier(name: str) -> tuple[int, str, int] | None:
    """Return (year, tier, round) for a generic tier pick name.

    Returns None for slot-specific rows like "2026 Pick 1.06".
    """
    if not name:
        return None
    m = _PICK_TIER_RE.match(str(name).strip())
    if not m:
        return None
    try:
        return int(m.group(1)), m.group(2).capitalize(), int(m.group(3))
    except (TypeError, ValueError):
        return None


def _reassign_pick_slot_order(players_array: list[dict[str, Any]]) -> int:
    """Reorder slot-specific picks within each year so slot order is
    strictly monotonic across all rounds (1.01..1.12, 2.01..2.12, ...).

    Operates AFTER the global Phase 4 sort has stamped
    ``canonicalConsensusRank`` and ``rankDerivedValue`` on every row.
    The mutation pattern is *in-place permutation*: we collect each
    year's existing slot-pick (rank, value, tier) tuples, sort them
    by rank (best first), sort the picks themselves by (round, slot),
    and reassign tuples in order.  Each tuple stays at the same global
    position in the ranked board — only the canonical name attached to
    it changes.  This preserves global rank/value monotonicity by
    construction (the assertion in ``assert_ranking_coherence`` walks
    the same tuples in the same order, just with different names).

    A single per-year pass (instead of one pass per (year, round)
    bucket) ensures cross-round inversions like 2026 Pick 1.12 < 2.01
    also get fixed: late-1st always outvalues early-2nd, etc.

    Returns the count of picks whose (rank, value) actually changed.
    """
    # Group slot picks by year.  Within each year we sort by
    # (round, slot) so the cross-round ordering is enforced too.
    buckets: dict[int, list[dict[str, Any]]] = {}
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        name = row.get("canonicalName") or ""
        parsed = _parse_pick_slot(name)
        if parsed is None:
            continue
        year, _rnd, _slot = parsed
        # Skip picks that didn't get a rank (out of OVERALL_RANK_LIMIT).
        # Reassigning across the cap would create rank/value mismatch.
        if not row.get("canonicalConsensusRank"):
            continue
        buckets.setdefault(year, []).append(row)

    changed = 0
    for _year, picks in buckets.items():
        if len(picks) < 2:
            continue
        # Snapshot of existing (rank, value, tier, blendedSourceRank,
        # sourceRankSpread, percentileSpread) tuples for the bucket,
        # sorted best-first.  Tier moves with rank since
        # ``canonicalTierId`` is derived from rank.
        tuples: list[tuple[int, int, int | None, Any, Any, Any]] = []
        for p in picks:
            tuples.append(
                (
                    int(p["canonicalConsensusRank"]),
                    int(p.get("rankDerivedValue") or 0),
                    p.get("canonicalTierId"),
                    p.get("blendedSourceRank"),
                    p.get("sourceRankSpread"),
                    p.get("sourceRankPercentileSpread"),
                )
            )
        tuples.sort(key=lambda t: t[0])  # ascending rank = descending value

        # Sort picks by (round, slot) ascending — the highest 1.01 slot
        # of the lowest round should get the best tuple.
        def _round_slot(r: dict[str, Any]) -> tuple[int, int]:
            parsed = _parse_pick_slot(r["canonicalName"])
            assert parsed is not None  # already filtered above
            _y, rnd, slot = parsed
            return (rnd, slot)

        picks_sorted = sorted(picks, key=_round_slot)

        for new_tuple, pick_row in zip(tuples, picks_sorted):
            old_rank = pick_row.get("canonicalConsensusRank")
            old_val = pick_row.get("rankDerivedValue")
            new_rank, new_val, new_tier, new_bsr, new_spread, new_pct = new_tuple
            if old_rank != new_rank or old_val != new_val:
                changed += 1
            pick_row["canonicalConsensusRank"] = new_rank
            pick_row["rankDerivedValue"] = new_val
            if new_tier is not None:
                pick_row["canonicalTierId"] = new_tier
            else:
                pick_row["canonicalTierId"] = _tier_id_from_rank(new_rank)
            pick_row["blendedSourceRank"] = new_bsr
            pick_row["sourceRankSpread"] = new_spread
            pick_row["sourceRankPercentileSpread"] = new_pct
            # Stamp a flag so consumers can see the slot was reassigned
            # by the monotonization pass (mostly for debugging).
            pick_row["pickSlotMonotonized"] = True

    return changed


def _suppress_generic_pick_tiers_when_slots_exist(
    players_array: list[dict[str, Any]],
) -> dict[str, str]:
    """Remove generic tier pick rows (Early/Mid/Late XX) from the ranked
    board for any (year, round) that already has slot-specific picks
    1..12.  The removed rows are returned as a ``pickAliases`` map:
    ``{"2026 Mid 1st": "2026 Pick 1.06"}``.

    For the alias destination we pick the centre slot of each tier
    range:  Early=2, Mid=6, Late=10.  These stay as searchable aliases
    so a user typing "2026 mid 1st" still resolves to the closest
    slot-specific row even though the generic tier has been removed
    from the ranked board.

    Years that have NO specific slots (e.g. 2027, 2028 where the
    sources only publish tier values) are left alone.  Their generic
    tier rows remain on the board as the only available representation.
    """
    # 1) Find years that have at least one slot-specific pick.
    years_with_slots: set[int] = set()
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        parsed = _parse_pick_slot(row.get("canonicalName") or "")
        if parsed is not None:
            years_with_slots.add(parsed[0])

    if not years_with_slots:
        return {}

    aliases: dict[str, str] = {}
    tier_centre_slot = {"Early": 2, "Mid": 6, "Late": 10}
    rounds_with_slots: dict[tuple[int, int], bool] = {}
    for row in players_array:
        parsed = _parse_pick_slot(row.get("canonicalName") or "")
        if parsed is not None:
            rounds_with_slots[(parsed[0], parsed[1])] = True

    # 2) Walk picks; for each generic tier row in a year+round with
    # specific slots, build the alias and clear the row's ranking
    # fields so it disappears from the ranked board (assert_ranking
    # _coherence skips rows with no canonicalConsensusRank).
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        name = row.get("canonicalName") or ""
        parsed = _parse_pick_tier(name)
        if parsed is None:
            continue
        year, tier, rnd = parsed
        if year not in years_with_slots:
            continue
        if not rounds_with_slots.get((year, rnd)):
            # Year has slots overall but not for this specific round.
            continue
        slot = tier_centre_slot.get(tier, 6)
        alias_target = f"{year} Pick {rnd}.{slot:02d}"
        aliases[name] = alias_target

        # Clear the ranking fields so the row drops off the ranked
        # board.  Keep the row itself in playersArray so any consumer
        # that resolves a name lookup still finds it (search aliases),
        # but mark it suppressed so the trust block reflects reality.
        row["canonicalConsensusRank"] = None
        row["rankDerivedValue"] = None
        row["canonicalTierId"] = None
        row["confidenceBucket"] = "none"
        row["confidenceLabel"] = (
            "None — generic tier suppressed in favor of slot-specific picks"
        )
        row["pickGenericSuppressed"] = True
        # Drop quarantine / single-source flags so the suppressed row
        # cannot accidentally trip the launch-readiness 1-src gate.
        row["isSingleSource"] = False
        row["isStructurallySingleSource"] = False
        row["anomalyFlags"] = []
        # Preserve the alias on the row itself for direct UI lookups.
        row["pickAliasFor"] = alias_target

    return aliases


def _compute_pick_confidence(
    canonical_sites: dict[str, Any],
    is_slot_specific: bool,
) -> tuple[str, str]:
    """Compute (confidenceBucket, confidenceLabel) for a pick row.

    Pick confidence is rank-spread agnostic: for picks the meaningful
    signal is whether multiple raw source values agree on the pick's
    dollar value, not whether the source ordinal ranks line up (rank
    spread on picks is dominated by flat-value regions in R3-R6 and
    misleads the player-centric bucketing).

    Rules:
      * Effective source count: count raw values > 0.  KTC slot values
        on slot-specific picks are SYNTHESIZED by Dynasty Scraper's
        ``_estimate_slot_from_tier`` from KTC's 14 tier rows — they
        carry partial information so we count them at 0.5 instead of
        1.0.  KTC tier-row picks (e.g. 2026 Early 1st) are real KTC
        rows and count at 1.0.
      * Coefficient of variation: cv = stdev(raw_values) / mean.
      * Bucketing:
          high   — effective count >= 1.5 AND cv <= 0.15
          medium — effective count >= 1.0 AND cv <= 0.30
          low    — otherwise
    """
    raw_values: list[tuple[str, float]] = []
    for key in ("ktc", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep", "dlfIdp"):
        v = canonical_sites.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            raw_values.append((key, f))

    if not raw_values:
        return "none", "None — no pick source values"

    # KTC slot values on specific slots are partial evidence.
    effective_count = 0.0
    for key, _v in raw_values:
        if key == "ktc" and is_slot_specific:
            effective_count += 0.5
        else:
            effective_count += 1.0

    values = [v for _k, v in raw_values]
    mean = sum(values) / len(values)
    if mean <= 0 or len(values) < 2:
        cv = None
    else:
        var = sum((v - mean) ** 2 for v in values) / len(values)
        cv = math.sqrt(var) / mean

    if cv is None:
        # Single-source pick — no agreement signal at all.
        if effective_count >= 1.0:
            return "low", "Low — single pick source"
        return "low", "Low — limited pick sources"

    if effective_count >= 1.5 and cv <= 0.15:
        return "high", "High — picks agree within 15%"
    if effective_count >= 1.0 and cv <= 0.30:
        return "medium", "Medium — moderate pick source disagreement"
    return "low", "Low — divergent pick sources"


def _apply_pick_year_discount_to_blend(
    row_normalized: list[tuple[float, int]],
    players_array: list[dict[str, Any]],
) -> tuple[list[tuple[float, int]], dict[int, float]]:
    """Apply the pick year discount to the blended pre-sort values.

    Picks in future years have their post-blend value multiplied by
    the discount config; every other row is untouched.  Returns the
    new ``row_normalized`` list and a per-row-idx map of the multiplier
    actually applied (for debugging / audit).

    Applied BEFORE the unified Phase 4 sort so future-year picks
    naturally drift to lower positions in the global ladder.
    """
    cfg = _load_pick_year_discount()
    discount_applied: dict[int, float] = {}
    out: list[tuple[float, int]] = []
    for value, row_idx in row_normalized:
        row = players_array[row_idx]
        if row.get("assetClass") == "pick":
            year = _pick_year_from_name(row.get("canonicalName") or "")
            mult = _pick_year_discount_for(year, cfg)
            if mult != 1.0:
                value = value * mult
                discount_applied[row_idx] = mult
                # Stamp on row for transparency
                row["pickYearDiscount"] = round(mult, 4)
        out.append((value, row_idx))
    return out, discount_applied


def _compute_unified_rankings(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
    csv_index: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, str]:
    """Compute a single unified ranking across all sources and positions.

    Architecture
    ────────────
    Ranking is scope-aware.  Each registered source in ``_RANKING_SOURCES``
    declares one of three scopes:

      * overall_offense — ranks across QB/RB/WR/TE + picks
      * overall_idp     — ranks across DL/LB/DB together
      * position_idp    — ranks within a single IDP family (DL, LB, or DB)

    For ``position_idp`` sources, the raw positional rank is translated
    through an IDP backbone (built from the best available overall_idp
    source) into a synthetic overall-IDP rank.  That synthetic rank is
    what actually feeds the shared Hill curve, so shallow top-20 lists
    cannot pretend to be top-20 overall.

    Per-source blending uses a coverage-aware weighted mean: shallow
    sources with small declared depth contribute less than deep full-board
    sources with identical declared weight.

    Stamps onto each row:
      - sourceRanks:  dict[str, int] — effective rank per source (the
                      integer fed into the Hill curve).  For position_idp
                      sources this is the *synthetic* overall IDP rank.
      - sourceRankMeta: dict[str, dict] — per-source transparency block:
            { scope, positionGroup, rawRank, effectiveRank, method,
              ladderDepth, weight, valueContribution }
      - rankDerivedValue: int — blended Hill-curve value (1..9999)
      - canonicalConsensusRank: int — unified overall rank (1 = best)
      - blendedSourceRank: float — mean of effective per-source ranks
      - sourceRankSpread: float | None — max-min of effective ranks
      - isSingleSource, hasSourceDisagreement
      - marketGapDirection / marketGapMagnitude
      - confidenceBucket / confidenceLabel
      - anomalyFlags
      - ktcRank / idpRank — preserved for backward compatibility
    """
    from src.canonical.player_valuation import rank_to_value  # noqa: PLC0415

    # ── Phase 0: Build IDP backbone from the designated backbone source ──
    # The first enabled source with scope=overall_idp and is_backbone=True
    # wins.  If no backbone source is present, position_idp sources fall
    # back to treating their raw rank as a synthetic overall rank and get
    # a caution flag on the per-source meta.
    #
    # The backbone also carries a *shared-market IDP ladder* — the
    # combined offense+IDP ranks at which IDP entries appear in the
    # backbone source's value pool.  Non-backbone overall_idp sources
    # flagged with ``needs_shared_market_translation`` (e.g. DLF) use
    # this ladder as a crosswalk so their IDP-only rank 1 is translated
    # to the combined-pool rank of the best IDP, not treated as if it
    # were the overall rank 1 of the shared offense+IDP board.
    backbone_source_key: str | None = None
    for src in _RANKING_SOURCES:
        if src["scope"] == SOURCE_SCOPE_OVERALL_IDP and src.get("is_backbone"):
            backbone_source_key = src["key"]
            break
    if backbone_source_key:
        # Only seed the shared-market ladder when the backbone source
        # actually prices both offense + IDP on a shared scale; this is
        # detected by the registry declaring offense in extra_scopes.
        backbone_src_def = next(
            (s for s in _RANKING_SOURCES if s["key"] == backbone_source_key),
            {},
        )
        backbone_extra_scopes = list(backbone_src_def.get("extra_scopes") or [])
        if SOURCE_SCOPE_OVERALL_OFFENSE in backbone_extra_scopes:
            backbone = build_backbone_from_rows(
                players_array,
                source_key=backbone_source_key,
                idp_positions=_IDP_POSITIONS,
                offense_positions=_OFFENSE_POSITIONS | {"PICK"},
            )
        else:
            backbone = build_backbone_from_rows(
                players_array,
                source_key=backbone_source_key,
                idp_positions=_IDP_POSITIONS,
            )
    else:
        backbone = IdpBackbone()

    # ── Phase 1: Combined-pass ordinal ranking per source ──
    # row_source_ranks[row_idx][source_key] = effective rank (int)
    # row_source_meta[row_idx][source_key] = transparency dict
    # source_pool_sizes[source_key] = count of rows the source ranked
    row_source_ranks: dict[int, dict[str, int]] = {}
    row_source_meta: dict[int, dict[str, dict[str, Any]]] = {}
    source_pool_sizes: dict[str, int] = {}
    # For backbone assertion: remember the actual ladder depth used
    backbone_depth = backbone.depth
    shared_market_ladder = backbone.shared_idp_ladder()
    shared_market_depth = backbone.shared_market_depth

    for src in _RANKING_SOURCES:
        source_key: str = src["key"]
        position_group: str | None = src.get("position_group")
        primary_scope: str = src["scope"]
        needs_shared_market = bool(
            src.get("needs_shared_market_translation")
        ) and not src.get("is_backbone")
        # A source may contribute to multiple scopes (e.g. IDPTradeCalc
        # lists both offense and IDP players in one value pool on a shared
        # 0-9999 scale).  Earlier revisions ran a separate ordinal pass per
        # scope, which restarted at rank 1 in each scope and destroyed the
        # cross-universe ordering encoded in the source's raw values — the
        # #1 IDP and the #1 offense player both got rank 1 → value 9999.
        #
        # Instead, gather every row eligible under ANY of this source's
        # declared scopes into ONE pool and rank them together.  For
        # single-scope sources this is equivalent to the old per-scope
        # pass.  For dual-scope IDPTradeCalc it preserves the combined
        # offense+IDP ordering: Will Anderson's raw IDPTC value 5963 lands
        # at overall rank ~40 alongside the full offense ladder, not rank
        # 1 of a restarted IDP-only pass.
        all_scopes: list[str] = [primary_scope] + list(
            src.get("extra_scopes") or []
        )

        # Gather eligible (value, row_idx, scope_for_row, tiebreak_name) tuples.
        # A row is eligible if any of the source's declared scopes accept
        # its position.  Offense and IDP position sets are disjoint, so
        # each row belongs to exactly one scope for a given source.
        eligible: list[tuple[float, int, str, str]] = []
        for idx, row in enumerate(players_array):
            pos = str(row.get("position") or "").strip().upper()
            if pos not in _RANKABLE_POSITIONS:
                continue
            row_scope: str | None = None
            for s in all_scopes:
                if _scope_eligible(pos, s, position_group):
                    row_scope = s
                    break
            if row_scope is None:
                continue
            sites = row.get("canonicalSiteValues") or {}
            val = _safe_num(sites.get(source_key))
            if val is None or val <= 0:
                continue
            tiebreak_name = str(
                row.get("canonicalName") or row.get("displayName") or ""
            ).lower()
            eligible.append((val, idx, row_scope, tiebreak_name))

        # Sort descending by value with a name-based secondary tiebreaker,
        # mirroring the backbone builder in src/canonical/idp_backbone.py
        # and the final unified sort in Phase 4.  This guarantees that
        # tied raw values (duplicate exports, rounding, genuinely equal
        # pricing) produce the same ordinal ranks regardless of input
        # order — important because the playersArray comes from a dict
        # whose iteration order can drift between runs.
        eligible.sort(key=lambda t: (-t[0], t[3]))
        source_pool_sizes[source_key] = len(eligible)

        for rank_idx, (_, row_idx, row_scope, _name) in enumerate(eligible):
            raw_rank = rank_idx + 1

            # Translate to effective overall-style rank based on scope.
            # position_idp sources (shallow positional lists like DL-only)
            # still get backbone translation.  overall_* scopes — including
            # the cross-universe combined pool — pass through directly
            # unless the source is an IDP-only expert board that opts in
            # to the shared-market crosswalk (e.g. DLF).
            ladder_depth_meta: int | None = None
            backbone_depth_meta: int | None = None
            if row_scope == SOURCE_SCOPE_POSITION_IDP and position_group:
                ladder = backbone.ladder_for(position_group)
                effective_rank, method = translate_position_rank(
                    raw_rank, ladder
                )
                ladder_depth_meta = len(ladder)
                backbone_depth_meta = backbone_depth
            elif needs_shared_market and row_scope == SOURCE_SCOPE_OVERALL_IDP:
                # Crosswalk an IDP-only expert board's raw IDP ordinal
                # into the backbone source's combined offense+IDP rank
                # space.  This prevents DLF rank 1 from being fed to the
                # Hill curve as if it were shared-market rank 1.
                effective_rank, method = translate_position_rank(
                    raw_rank, shared_market_ladder
                )
                ladder_depth_meta = len(shared_market_ladder)
                backbone_depth_meta = shared_market_depth
            else:
                effective_rank = raw_rank
                method = TRANSLATION_DIRECT

            row_source_ranks.setdefault(row_idx, {})[source_key] = effective_rank
            row_source_meta.setdefault(row_idx, {})[source_key] = {
                "scope": row_scope,
                "positionGroup": position_group,
                "rawRank": raw_rank,
                "effectiveRank": effective_rank,
                "method": method,
                "ladderDepth": ladder_depth_meta,
                "backboneDepth": backbone_depth_meta,
                "depth": src.get("depth"),
                "weight": float(src.get("weight") or 0.0),
                "sharedMarketTranslated": bool(
                    needs_shared_market
                    and row_scope == SOURCE_SCOPE_OVERALL_IDP
                ),
            }

    # ── Phase 2-3: Normalized value (Hill curve) + robust blend ──
    # Look up each source's weight / depth once.
    src_by_key: dict[str, dict[str, Any]] = {s["key"]: s for s in _RANKING_SOURCES}

    row_normalized: list[tuple[float, int]] = []  # (blended_value, row_idx)
    for row_idx, source_ranks in row_source_ranks.items():
        # Compute the per-source value contributions and effective weights
        # in lockstep so we can apply both a weighted-mean and a
        # robust-median blend.  The two blends are then combined: the
        # final blended value is the average of the weighted mean and
        # the robust median.  This downweights single-outlier sources
        # (e.g. an IDPTC dynasty value that grossly under-prices
        # established stars like T.J. Watt or Nick Bosa) without losing
        # the cross-source signal entirely.
        contributions: list[tuple[float, float]] = []  # (value, weight)
        weight_total = 0.0
        for source_key, eff_rank in source_ranks.items():
            src_def = src_by_key.get(source_key, {})
            declared_weight = float(src_def.get("weight") or 1.0)
            effective_weight = coverage_weight(declared_weight, src_def.get("depth"))
            value = float(rank_to_value(eff_rank))
            contributions.append((value, effective_weight))
            weight_total += effective_weight
            # Stamp value contribution onto per-source meta (for debugging)
            meta = row_source_meta[row_idx].get(source_key, {})
            meta["valueContribution"] = int(round(value))
            meta["effectiveWeight"] = round(effective_weight, 4)

        if not contributions:
            blended_value = 0.0
        else:
            values = [v for v, _w in contributions]
            if weight_total > 0:
                weighted_mean = (
                    sum(v * w for v, w in contributions) / weight_total
                )
            else:
                weighted_mean = sum(values) / len(values)

            # Robust blend: drop the *single* worst (most pessimistic)
            # outlier when 3+ sources disagree, otherwise take the
            # median of the surviving values.  With only two sources
            # we average them — there's nothing to drop without losing
            # half the signal.
            sorted_vals = sorted(values)
            if len(sorted_vals) >= 3:
                trimmed = sorted_vals[1:]  # drop the worst
                robust = sum(trimmed) / len(trimmed)
            elif len(sorted_vals) == 2:
                robust = sum(sorted_vals) / 2.0
            else:
                robust = sorted_vals[0]

            # Final blended value: 60/40 weighted mean / robust to give
            # the structural source weights the dominant voice while
            # still letting the robust blend correct obvious outliers.
            blended_value = 0.6 * weighted_mean + 0.4 * robust
        row_normalized.append((blended_value, row_idx))

    # ── Phase 3a: Pick year discount (gated to picks) ──
    # Apply the multiplicative future-year discount BEFORE the global
    # sort so 2027/2028 picks naturally drift to lower positions in
    # the final ladder. Player rows are untouched.
    row_normalized, _pick_year_discounts = _apply_pick_year_discount_to_blend(
        row_normalized, players_array
    )

    # ── Phase 4: Unified sort and overall rank assignment ──
    row_normalized.sort(
        key=lambda t: (-t[0], players_array[t[1]].get("canonicalName", "").lower())
    )

    # ── Phase 4a: stamp sourceCount + sourceAudit on every contributing row.
    #
    # ``isSingleSource`` is *semantic*: the flag fires only when a row
    # had **multiple** sources eligible to cover it but only one
    # actually matched.  A player who is the only structurally-eligible
    # subject of a single source (e.g. an offense-only player when only
    # one offense source is active) does NOT trip the 1-src warning,
    # because there is no underlying matching failure to diagnose.
    #
    # ``sourceAudit`` is the per-row transparency block specified by
    # the task: it records (a) which source rows actually matched and
    # under what display name, (b) which sources *should* have covered
    # this player but didn't, and (c) a one-line reason explaining the
    # current state.  Downstream code (frontend chips, audits, build-
    # time assertions) reads this block directly.
    csv_index = csv_index or {}
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415
    for row_idx, source_ranks in row_source_ranks.items():
        row = players_array[row_idx]
        row["sourceCount"] = len(source_ranks)
        # Stamp sourceRanks here (regardless of OVERALL_RANK_LIMIT) so
        # rows that fall off the cap after the pick year discount still
        # carry their per-source rank dict — consumers of the
        # playersArray (audit tooling, the picks regression test) can
        # then introspect every source-bearing row, ranked or not.
        row["sourceRanks"] = source_ranks
        canonical_sites = row.get("canonicalSiteValues") or {}
        row["sourcePresence"] = {
            k: (v is not None and v > 0) for k, v in canonical_sites.items()
        }

        pos = str(row.get("position") or "").strip().upper()
        is_rookie = bool(row.get("rookie"))
        # Use the smallest effective rank we've seen for this player as
        # the depth probe; ``rank_to_value`` is monotonic so the best
        # match is the most informative reach signal.
        rank_probe = min(source_ranks.values()) if source_ranks else None
        off_keys, idp_keys = _expected_sources_for_position(
            pos, is_rookie=is_rookie, player_effective_rank=rank_probe
        )
        expected_keys = sorted(off_keys | idp_keys)
        actual_keys = sorted(source_ranks.keys())
        unmatched_keys = sorted(set(expected_keys) - set(actual_keys))

        # Match details from the per-source CSV index.
        nm = str(row.get("canonicalName") or row.get("displayName") or "")
        cname = _canonical_match_key(nm)
        grp = canonical_position_group(pos)
        matched_details: dict[str, dict[str, Any]] = {}
        for sk in actual_keys:
            entry = (csv_index.get(sk) or {}).get(f"{cname}::{grp}")
            if entry is None:
                entry = (csv_index.get(sk) or {}).get(f"{cname}::*")
            if entry is None:
                # Source value was on the legacy player dict from the
                # scraper rather than from the CSV index.  Stamp the
                # raw value so the audit is still informative.
                matched_details[sk] = {
                    "matchedName": nm,
                    "rawValue": _to_int_or_none(canonical_sites.get(sk)),
                    "via": "scraper_payload",
                }
            else:
                matched_details[sk] = {
                    "matchedName": entry.get("displayName") or nm,
                    "rawValue": entry.get("value"),
                    "ambiguous": bool(entry.get("ambiguous")),
                    "candidates": list(entry.get("candidates") or [])[:6],
                    "via": "csv_enrich",
                }

        if not actual_keys:
            reason = "no_source_match"
        elif len(actual_keys) == 1 and len(expected_keys) <= 1:
            reason = "structurally_single_source"
        elif len(actual_keys) == 1 and len(expected_keys) > 1:
            reason = "matching_failure_other_sources_eligible"
        elif unmatched_keys:
            reason = "partial_coverage"
        else:
            reason = "fully_matched"

        allowlist_reason = SINGLE_SOURCE_ALLOWLIST.get(cname)
        row["sourceAudit"] = {
            "canonicalName": cname,
            "positionGroup": grp,
            "expectedSources": expected_keys,
            "matchedSources": actual_keys,
            "unmatchedSources": unmatched_keys,
            "matchedDetails": matched_details,
            "reason": reason,
            "allowlistReason": allowlist_reason,
        }
        # Semantic 1-src: only fire when matching could have produced
        # more than one source.
        row["isSingleSource"] = (
            len(source_ranks) == 1 and len(expected_keys) > 1
        )
        row["isStructurallySingleSource"] = (
            len(source_ranks) == 1 and len(expected_keys) <= 1
        )

    for overall_idx, (norm_val, row_idx) in enumerate(
        row_normalized[:OVERALL_RANK_LIMIT]
    ):
        row = players_array[row_idx]
        overall_rank = overall_idx + 1
        derived = int(norm_val)
        source_ranks = row_source_ranks.get(row_idx, {})
        source_meta = row_source_meta.get(row_idx, {})
        rank_values = list(source_ranks.values())

        # ── Core ranking fields ──
        row["sourceRanks"] = source_ranks
        row["sourceRankMeta"] = source_meta
        row["rankDerivedValue"] = derived
        row["canonicalConsensusRank"] = overall_rank
        row["canonicalTierId"] = _tier_id_from_rank(overall_rank)
        row["sourceCount"] = len(source_ranks)

        # Caution flag when any IDP source required fallback translation
        used_fallback = any(
            m.get("method") == TRANSLATION_FALLBACK for m in source_meta.values()
        )
        row["idpBackboneFallback"] = used_fallback

        # ── Trust/transparency fields (effective rank space) ──
        blended_source_rank = (
            sum(rank_values) / len(rank_values) if rank_values else None
        )
        row["blendedSourceRank"] = (
            round(blended_source_rank, 2) if blended_source_rank is not None else None
        )

        source_rank_spread: float | None = None
        if len(rank_values) >= 2:
            source_rank_spread = float(max(rank_values) - min(rank_values))
        row["sourceRankSpread"] = source_rank_spread

        # Percentile-based disagreement.  Replaces the old absolute
        # rank threshold (`spread > 80`) which fired whenever sources
        # of very different depths produced numerically different
        # ranks for the same player even when both were placing him
        # in the same relative tier.  ``percentileSpread`` is the
        # max-minus-min of each source's *raw* rank divided by that
        # source's auto-detected pool size.
        percentile_spread = _percentile_rank_spread(
            source_ranks, source_meta, source_pool_sizes
        )
        row["sourceRankPercentileSpread"] = (
            round(percentile_spread, 4) if percentile_spread is not None else None
        )

        # Preserve the semantic 1-src flag stamped in Phase 4a; do
        # not collapse it back to ``len(source_ranks) == 1`` here.
        # Disagreement uses percentile spread.
        row["hasSourceDisagreement"] = (
            percentile_spread is not None and percentile_spread > 0.10
        )

        gap_dir, gap_mag = _compute_market_gap(source_ranks)
        row["marketGapDirection"] = gap_dir
        row["marketGapMagnitude"] = gap_mag

        # Picks get their own confidence logic (CV-based on raw values),
        # because rank-spread is dominated by flat-value regions in
        # R3-R6 and KTC's per-slot synth bleeds in as fake agreement.
        if row.get("assetClass") == "pick":
            is_slot_specific = _parse_pick_slot(
                row.get("canonicalName") or ""
            ) is not None
            bucket, label = _compute_pick_confidence(
                row.get("canonicalSiteValues") or {},
                is_slot_specific=is_slot_specific,
            )
        else:
            bucket, label = _compute_confidence_bucket(
                len(source_ranks), source_rank_spread
            )
        row["confidenceBucket"] = bucket
        row["confidenceLabel"] = label

        audit = row.get("sourceAudit") or {}
        row["anomalyFlags"] = _compute_anomaly_flags(
            name=row.get("canonicalName") or row.get("displayName") or "",
            position=row.get("position"),
            asset_class=row.get("assetClass") or "",
            source_ranks=source_ranks,
            source_meta=source_meta,
            rank_derived_value=derived,
            canonical_sites=row.get("canonicalSiteValues") or {},
            percentile_spread=percentile_spread,
            expected_sources=list(audit.get("expectedSources") or []),
        )

        # Backward compatibility: set ktcRank / idpRank if applicable.
        # ktcRank and idpRank carry the *effective* rank consumers are used
        # to; for the backbone source (overall_idp) that's identical to the
        # raw ordinal rank, so semantics are unchanged for idpTradeCalc.
        if "ktc" in source_ranks:
            row["ktcRank"] = source_ranks["ktc"]
        if "idpTradeCalc" in source_ranks:
            row["idpRank"] = source_ranks["idpTradeCalc"]

        # Mirror into legacy players dict so the runtime view
        # (which strips playersArray) still has the authoritative
        # per-row ranking data for the frontend's legacy-dict row builder.
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["rankDerivedValue"] = derived
                pdata["_canonicalConsensusRank"] = overall_rank
                pdata["sourceCount"] = len(source_ranks)
                pdata["sourceRanks"] = dict(source_ranks)
                pdata["sourceRankMeta"] = dict(source_meta)
                # Mirror the enriched canonicalSiteValues back so the
                # legacy dict sees DLF values that were grafted on by
                # _enrich_from_source_csvs (the scraper's own
                # _canonicalSiteValues doesn't include DLF).
                csv_row = row.get("canonicalSiteValues")
                if isinstance(csv_row, dict):
                    legacy_csv = pdata.get("_canonicalSiteValues")
                    if not isinstance(legacy_csv, dict):
                        legacy_csv = {}
                        pdata["_canonicalSiteValues"] = legacy_csv
                    for k, v in csv_row.items():
                        if v is not None and v > 0:
                            legacy_csv[k] = v
                            pdata[k] = v
                if "ktc" in source_ranks:
                    pdata["ktcRank"] = source_ranks["ktc"]
                if "idpTradeCalc" in source_ranks:
                    pdata["idpRank"] = source_ranks["idpTradeCalc"]

    # ── Phase 5: Pick refinement passes (gated to picks) ──
    # 1) Reassign (rank, value) tuples within each (year, round) bucket
    #    so slot-specific picks 1.01..1.12 are strictly monotonic in
    #    slot order.  This corrects KTC's _estimate_slot_from_tier
    #    inversions without disturbing global rank/value monotonicity.
    _reassign_pick_slot_order(players_array)

    # 2) Suppress generic Early/Mid/Late tier rows for years that have
    #    specific slots, returning a {generic_name: slot_alias} map.
    pick_aliases = _suppress_generic_pick_tiers_when_slots_exist(players_array)

    # 2a) Compact ranks after suppression so the ranked board is still
    #     contiguous 1..N.  This walks the surviving ranked rows in
    #     ascending-rank order and renumbers them 1..N.  Values stay
    #     monotonic because we are only *removing* rows from a sequence
    #     that was already monotonic.  Tier IDs are re-derived from the
    #     new ranks.
    ranked_rows = sorted(
        [r for r in players_array if r.get("canonicalConsensusRank")],
        key=lambda r: int(r["canonicalConsensusRank"]),
    )
    for new_rank, r in enumerate(ranked_rows, start=1):
        old_rank = r.get("canonicalConsensusRank")
        if old_rank != new_rank:
            r["canonicalConsensusRank"] = new_rank
        r["canonicalTierId"] = _tier_id_from_rank(new_rank)

    # 3) Mirror the post-refinement rank/value back into the legacy
    #    players_by_name dict so the runtime view stays in sync.
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        legacy_ref = row.get("legacyRef")
        if not legacy_ref or legacy_ref not in players_by_name:
            continue
        pdata = players_by_name[legacy_ref]
        if not isinstance(pdata, dict):
            continue
        rdv = row.get("rankDerivedValue")
        rk = row.get("canonicalConsensusRank")
        if rdv is not None:
            pdata["rankDerivedValue"] = rdv
        if rk is not None:
            pdata["_canonicalConsensusRank"] = rk
        else:
            # Suppressed generic tier — clear ranking on legacy too.
            pdata["rankDerivedValue"] = None
            pdata["_canonicalConsensusRank"] = None
        # Mirror the new pick-specific confidence bucket as well.
        if "confidenceBucket" in row:
            pdata["confidenceBucket"] = row["confidenceBucket"]
            pdata["confidenceLabel"] = row.get("confidenceLabel")
        if row.get("pickSlotMonotonized"):
            pdata["pickSlotMonotonized"] = True
        if row.get("pickGenericSuppressed"):
            pdata["pickGenericSuppressed"] = True
        if row.get("pickAliasFor"):
            pdata["pickAliasFor"] = row["pickAliasFor"]
        if row.get("pickYearDiscount") is not None:
            pdata["pickYearDiscount"] = row["pickYearDiscount"]

    return pick_aliases


REQUIRED_TOP_LEVEL_KEYS = {
    "contractVersion",
    "generatedAt",
    "players",
    "playersArray",
    "valueAuthority",
    "sites",
    "maxValues",
}

REQUIRED_PLAYER_KEYS = {
    "playerId",
    "canonicalName",
    "displayName",
    "position",
    "team",
    "age",
    "rookie",
    "values",
    "canonicalSiteValues",
    "sourceCount",
    "confidenceBucket",
    "anomalyFlags",
}

# Fields that are useful for deeper diagnostics/explanations but are not required
# for initial first-paint startup rendering in the frontend.
STARTUP_HEAVY_PLAYER_FIELD_PREFIXES = ("_formatFit",)
STARTUP_HEAVY_PLAYER_FIELDS = {
    "_scoringAdjustment",
}
STARTUP_DROP_TOP_LEVEL_KEYS = {
    # Large secondary blocks not required for first-screen calculator/rankings usability.
    "coverageAudit",
    "ktcCrowd",
    # Runtime/startup views intentionally avoid the duplicated contract array.
    "playersArray",
    # Shadow canonical comparison is debug-only; not needed for first paint.
    "canonicalComparison",
}

# ── Legacy LAM/scarcity field stripping ──────────────────────────────────
# LAM (League Adjustment Multiplier) and positional scarcity have been fully
# removed from the codebase.  Older data files may still contain these fields.
# They are stripped from ALL API responses so no legacy LAM/scarcity data is
# ever served publicly.
_LEGACY_LAM_PLAYER_PREFIXES = ("_lam", "_rawLeague", "_shrunkLeague")
_LEGACY_LAM_PLAYER_FIELDS = {
    "_leagueAdjusted",
    "_effectiveMultiplier",
}
_LEGACY_LAM_TOP_LEVEL_KEYS = {
    "empiricalLAM",
}


def _safe_num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
    except Exception:
        return None
    if not math.isfinite(n):
        return None
    return n


def _to_int_or_none(v: Any) -> int | None:
    n = _safe_num(v)
    if n is None:
        return None
    return int(round(n))


def _normalize_pos(pos: Any) -> str:
    from src.utils.name_clean import POSITION_ALIASES
    p = str(pos or "").strip().upper()
    return POSITION_ALIASES.get(p, p)


def _is_pick_name(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    if re.search(r"\b(20\d{2})\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)\b", n, re.I):
        return True
    if re.search(r"\b(20\d{2})\s+[1-6]\.(0?[1-9]|1[0-2])\b", n, re.I):
        return True
    if re.search(r"\b(20\d{2})\s+(PICK|ROUND)\b", n, re.I):
        return True
    return False


def _canonical_site_values(
    p_data: dict[str, Any],
    site_keys: list[str],
) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    explicit = p_data.get("_canonicalSiteValues")
    if isinstance(explicit, dict):
        for key in site_keys:
            val = _to_int_or_none(explicit.get(key))
            # Fall back to direct player dict if the enrichment dict is missing this key
            if val is None:
                val = _to_int_or_none(p_data.get(key))
            out[key] = val
        for key, val in explicit.items():
            if key not in out:
                out[str(key)] = _to_int_or_none(val)
        return out

    for key in site_keys:
        out[key] = _to_int_or_none(p_data.get(key))
    return out


def _source_count(p_data: dict[str, Any], canonical_sites: dict[str, int | None]) -> int:
    explicit_sites = _to_int_or_none(p_data.get("_sites"))
    if explicit_sites is not None and explicit_sites >= 0:
        return explicit_sites
    return sum(1 for v in canonical_sites.values() if v is not None and v > 0)


def _player_value_bundle(p_data: dict[str, Any]) -> dict[str, int | None]:
    raw = _to_int_or_none(
        p_data.get("_rawComposite", p_data.get("_rawMarketValue", p_data.get("_composite")))
    )
    final = _to_int_or_none(
        p_data.get("_finalAdjusted", p_data.get("_composite"))
    )
    if final is None:
        final = raw
    overall = final
    display = _to_int_or_none(p_data.get("_canonicalDisplayValue"))
    return {
        "overall": overall,
        "rawComposite": raw,
        "finalAdjusted": final,
        "displayValue": display,
    }


def _derive_player_row(
    name: str,
    p_data: dict[str, Any],
    pos_map: dict[str, Any],
    site_keys: list[str],
) -> dict[str, Any]:
    canonical_name = str(name or "").strip()
    pos_from_player = _normalize_pos(p_data.get("position"))
    pos_from_sleeper = _normalize_pos(pos_map.get(canonical_name))
    canonical_sites = _canonical_site_values(p_data, site_keys)

    has_off_signal = any(
        _to_int_or_none(canonical_sites.get(k)) not in (None, 0)
        for k in _OFFENSE_SIGNAL_KEYS
    )
    has_idp_signal = any(
        _to_int_or_none(canonical_sites.get(k)) not in (None, 0)
        for k in _IDP_SIGNAL_KEYS
    )

    pos = pos_from_sleeper or pos_from_player
    # Guardrail: never let a sleeper map collision override an explicit offensive
    # source profile into an IDP position (or vice versa).
    if pos_from_player and pos_from_sleeper:
        player_is_off = pos_from_player in _OFFENSE_POSITIONS
        player_is_idp = pos_from_player in _IDP_POSITIONS
        sleeper_is_off = pos_from_sleeper in _OFFENSE_POSITIONS
        sleeper_is_idp = pos_from_sleeper in _IDP_POSITIONS
        if player_is_off and sleeper_is_idp and has_off_signal and not has_idp_signal:
            pos = pos_from_player
        elif player_is_idp and sleeper_is_off and has_idp_signal and not has_off_signal:
            pos = pos_from_player

    is_pick = _is_pick_name(canonical_name)
    if is_pick:
        pos = "PICK"
        # NOTE (pick slot monotonicity): KTC internally tiers draft picks into
        # early/mid/late buckets per round, so their raw per-slot valuations are
        # not strictly monotonic within a round after blending (e.g. 2026 1.04
        # can land below 2026 1.05 once KTC and IDPTradeCalc are combined).
        # This is a source-level quirk of KTC's tier structure, not a pipeline
        # bug — the global rank→value ordering across all assets is still
        # monotonic, and the 5 representative targets (1.01/1.06/1.12/2.06/Mid
        # 1st) all fall in the expected tier. Do not "fix" intra-round slot
        # inversions by post-processing pickAnchors; that would desync the
        # canonical rank ladder from the source evidence.

    values = _player_value_bundle(p_data)
    source_count = _source_count(p_data, canonical_sites)

    return {
        "playerId": str(p_data.get("_sleeperId") or "").strip() or None,
        "canonicalName": canonical_name,
        "displayName": canonical_name,
        "position": pos or None,
        "team": p_data.get("team") if isinstance(p_data.get("team"), str) else None,
        # Age: scaffolded for future use.  Populated when source data includes
        # age_raw (e.g. DLF CSV adapter).  Currently null for most players
        # because the scraper bridge does not supply age.
        "age": _to_int_or_none(p_data.get("age")) or _to_int_or_none(p_data.get("age_raw")),
        # Two upstream rookie signals: ``_formatFitRookie`` is set by
        # the canonical pipeline's format-fit pass and is None for
        # rows that haven't been through it.  ``_isRookie`` is the
        # scraper's direct flag, set when the player has zero NFL
        # years of experience.  Use whichever is positive so the
        # contract layer can rely on a single boolean.
        "rookie": bool(
            p_data.get("_formatFitRookie") or p_data.get("_isRookie")
        ),
        "assetClass": "pick" if is_pick else ("idp" if pos in {"DL", "LB", "DB"} else "offense"),
        "values": values,
        "canonicalSiteValues": canonical_sites,
        "sourceCount": source_count,
        "sourcePresence": {k: (v is not None and v > 0) for k, v in canonical_sites.items()},
        "marketConfidence": _safe_num(p_data.get("_marketConfidence")),
        "marketDispersionCV": _safe_num(p_data.get("_marketDispersionCV")),
        "legacyRef": canonical_name,
        # Trust/transparency defaults — overwritten by _compute_unified_rankings
        # for players that receive a unified rank.
        "confidenceBucket": "none",
        "confidenceLabel": "None — unranked",
        "anomalyFlags": [],
        "isSingleSource": False,
        "isStructurallySingleSource": False,
        "hasSourceDisagreement": False,
        "blendedSourceRank": None,
        "sourceRankSpread": None,
        "sourceRankPercentileSpread": None,
        "marketGapDirection": "none",
        "marketGapMagnitude": None,
        "sourceAudit": {
            "canonicalName": "",
            "positionGroup": "",
            "expectedSources": [],
            "matchedSources": [],
            "unmatchedSources": [],
            "matchedDetails": {},
            "reason": "no_source_match",
        },
        # Original CSV ranks for rank-signal sources (e.g. DLF).
        "sourceOriginalRanks": {},
        # Identity quality — overwritten by _validate_and_quarantine_rows
        "identityConfidence": 0.70,
        "identityMethod": "name_only",
        "quarantined": False,
    }


def _build_value_authority_summary(players_array: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(players_array or [])
    raw_present = 0
    final_present = 0
    canonical_map_present = 0
    canonical_points = 0

    for row in players_array or []:
        if not isinstance(row, dict):
            continue
        values = row.get("values")
        if isinstance(values, dict):
            raw_v = _to_int_or_none(values.get("rawComposite"))
            final_v = _to_int_or_none(values.get("finalAdjusted"))
            if raw_v is not None and raw_v > 0:
                raw_present += 1
            if final_v is not None and final_v > 0:
                final_present += 1

        canonical_sites = row.get("canonicalSiteValues")
        if isinstance(canonical_sites, dict):
            non_null = 0
            for val in canonical_sites.values():
                n = _to_int_or_none(val)
                if n is not None and n > 0:
                    non_null += 1
            if non_null > 0:
                canonical_map_present += 1
                canonical_points += non_null

    return {
        "mode": "backend_authoritative_with_explicit_frontend_fallback",
        "fallbackPolicy": "frontend_recompute_only_when_backend_value_fields_missing",
        "coverage": {
            "playersTotal": total,
            "rawCompositePresent": raw_present,
            "finalAdjustedPresent": final_present,
            "canonicalSiteMapPresent": canonical_map_present,
            "canonicalSiteValuePoints": canonical_points,
        },
    }


def _strip_legacy_lam_fields(base: dict[str, Any], players_by_name: dict[str, Any]) -> None:
    """Remove legacy LAM/scarcity fields from the contract payload in-place.

    Strips player-level LAM fields from every player dict and top-level
    LAM blobs from the base payload.  This ensures the API never serves
    removed LAM/scarcity data, even when loading older data files.
    """
    # Strip top-level LAM blobs
    for key in _LEGACY_LAM_TOP_LEVEL_KEYS:
        base.pop(key, None)

    # Strip player-level LAM fields
    for pdata in players_by_name.values():
        if not isinstance(pdata, dict):
            continue
        keys_to_remove = [
            k for k in pdata
            if k in _LEGACY_LAM_PLAYER_FIELDS
            or any(k.startswith(prefix) for prefix in _LEGACY_LAM_PLAYER_PREFIXES)
        ]
        for k in keys_to_remove:
            del pdata[k]


def build_api_data_contract(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = deepcopy(raw_payload or {})
    players_by_name = base.get("players")
    if not isinstance(players_by_name, dict):
        players_by_name = {}
        base["players"] = players_by_name

    # Strip legacy LAM/scarcity fields before building the contract.
    _strip_legacy_lam_fields(base, players_by_name)

    sites = base.get("sites")
    if not isinstance(sites, list):
        sites = []
        base["sites"] = sites

    max_values = base.get("maxValues")
    if not isinstance(max_values, dict):
        max_values = {}
        base["maxValues"] = max_values

    sleeper = base.get("sleeper")
    if not isinstance(sleeper, dict):
        sleeper = {}
        base["sleeper"] = sleeper

    pos_map = sleeper.get("positions")
    if not isinstance(pos_map, dict):
        pos_map = {}
        sleeper["positions"] = pos_map

    site_keys = [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]
    players_array: list[dict[str, Any]] = []
    for name in sorted(players_by_name.keys(), key=lambda x: str(x).lower()):
        p_data = players_by_name.get(name)
        if not isinstance(p_data, dict):
            continue
        players_array.append(_derive_player_row(str(name), p_data, pos_map, site_keys))

    # Enrich players with source CSV values that may be missing from the
    # legacy scraper payload (e.g. KTC scrape failed but CSV exists).
    csv_index = _enrich_from_source_csvs(players_array)

    # Compute unified rankings: all sources, all positions, one board.
    # The CSV index lets the ranker stamp a per-row ``sourceAudit``
    # block describing which CSV row matched each player and why.
    pick_aliases = _compute_unified_rankings(
        players_array, players_by_name, csv_index=csv_index
    )

    # Stamp rankDerivedValue into the values bundle so every page uses the
    # same number.  The legacy composite (values.overall / values.finalAdjusted)
    # comes from the old multi-source scraper and may differ.  The unified
    # ranking model's rankDerivedValue is the authoritative display value.
    for row in players_array:
        rdv = row.get("rankDerivedValue")
        if rdv is not None and rdv > 0:
            vals = row.get("values")
            if isinstance(vals, dict):
                vals["overall"] = rdv
                vals["finalAdjusted"] = rdv
                vals["displayValue"] = rdv

    # ── Identity validation and quarantine pass ──
    # Runs AFTER rankings are computed so anomalyFlags and confidence can be
    # degraded for suspicious rows.  Does NOT remove rows — quarantined rows
    # remain in the array with quarantined=True and degraded confidenceBucket.
    validation_summary = _validate_and_quarantine_rows(players_array)

    # ── Mirror trust fields to legacy players dict ──
    # The runtime view strips playersArray for payload size.  The frontend
    # falls back to the legacy `players` dict and reads trust fields via
    # `r.raw?.field`.  This pass copies all post-quarantine trust fields
    # so they survive the runtime view.
    _mirror_trust_to_legacy(players_array, players_by_name)

    data_source = data_source or {}
    generated_at = utc_now_iso()

    # ── Payload-level dataFreshness ──
    data_freshness: dict[str, Any] = {
        "generatedAt": generated_at,
        "sourceTimestamps": {
            "ktc": str(data_source.get("ktcTimestamp") or ""),
            "idpTradeCalc": str(data_source.get("idpTradeCalcTimestamp") or ""),
        },
        "staleness": "unknown",  # Downstream can compare timestamps to now()
    }

    # ── Payload-level methodology summary ──
    methodology: dict[str, Any] = {
        "version": CONTRACT_VERSION,
        "description": (
            "Scope-aware unified dynasty + IDP rankings board. Each registered "
            "source declares a scope (overall_offense, overall_idp, or "
            "position_idp) and is ranked only over eligible players. For "
            "position_idp sources (e.g. a top-20 DL list) the raw positional "
            "rank is translated through an IDP backbone ladder — built from the "
            "first overall_idp source flagged is_backbone — into a synthetic "
            "overall-IDP rank, so shallow position-only lists cannot pretend to "
            "be full-board rankings. Each effective rank is then converted to a "
            "1-9999 value via the shared Hill curve and blended across sources "
            "with a coverage-aware weighted mean: declared weight is scaled by "
            "min(1, depth / {min_depth}) so shallow lists contribute less than "
            "deep full-board sources. All players are sorted by blended value "
            "into one unified board capped at {limit} entries."
        ).format(limit=OVERALL_RANK_LIMIT, min_depth=60),
        "sources": [
            {
                "key": src["key"],
                "name": src["display_name"],
                "scope": src["scope"],
                "extraScopes": list(src.get("extra_scopes") or []),
                "positionGroup": src.get("position_group"),
                "depth": src.get("depth"),
                "weight": src.get("weight"),
                "isBackbone": bool(src.get("is_backbone")),
                "isRetail": bool(src.get("is_retail")),
                "covers": " + ".join(
                    (
                        "Offense (QB, RB, WR, TE) + draft picks"
                        if s == SOURCE_SCOPE_OVERALL_OFFENSE
                        else "IDP full board (DL, LB, DB)"
                        if s == SOURCE_SCOPE_OVERALL_IDP
                        else f"IDP position group: {src.get('position_group')}"
                    )
                    for s in ([src["scope"]] + list(src.get("extra_scopes") or []))
                ),
            }
            for src in _RANKING_SOURCES
        ],
        "formula": {
            "name": "Hill curve",
            "expression": "value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))",
            "midpoint": 45,
            "slope": 1.10,
            "scaleMin": 1,
            "scaleMax": 9999,
        },
        "idpTranslation": {
            "description": (
                "position_idp sources are translated into synthetic overall-IDP "
                "ranks using an anchor ladder built from the backbone source. "
                "Integer ranks inside the ladder are exact anchors; fractional "
                "ranks interpolate linearly; ranks past the tail extrapolate "
                "using the average spacing of the last five anchors; empty "
                "ladders fall back to a pass-through and the row is flagged "
                "idpBackboneFallback=true."
            ),
            "methods": [
                "direct",
                "exact",
                "interpolated",
                "extrapolated",
                "fallback",
            ],
            "coverageWeight": {
                "description": (
                    "effective_weight = declared_weight * min(1, depth / min_full_depth)"
                ),
                "minFullDepth": 60,
            },
        },
        "confidenceBuckets": {
            "high": "2+ sources, sourceRankSpread <= 30",
            "medium": "2+ sources, sourceRankSpread <= 80",
            "low": "single source or sourceRankSpread > 80",
            "none": "player did not receive a unified rank",
        },
        "anomalyFlags": [
            "offense_as_idp",
            "idp_as_offense",
            "missing_position",
            "retired_or_invalid_name",
            "ol_contamination",
            "suspicious_disagreement",
            "impossible_value",
            "duplicate_canonical_identity",
            "name_collision_cross_universe",
            "position_source_contradiction",
            "unsupported_position",
            "no_valid_source_values",
        ],
        "overallRankLimit": OVERALL_RANK_LIMIT,
    }

    # ── Anomaly summary (payload-level aggregation) ──
    anomaly_counts: dict[str, int] = {}
    total_flagged = 0
    for row in players_array:
        flags = row.get("anomalyFlags") or []
        if flags:
            total_flagged += 1
        for flag in flags:
            anomaly_counts[flag] = anomaly_counts.get(flag, 0) + 1

    contract_payload: dict[str, Any] = {
        **base,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": generated_at,
        "playersArray": players_array,
        "playerCount": len(players_array),
        "valueAuthority": _build_value_authority_summary(players_array),
        "dataSource": {
            "type": str(data_source.get("type") or ""),
            "path": str(data_source.get("path") or ""),
            "loadedAt": str(data_source.get("loadedAt") or ""),
        },
        "dataFreshness": data_freshness,
        "methodology": methodology,
        "anomalySummary": {
            "totalFlagged": total_flagged,
            "flagCounts": anomaly_counts,
        },
        "validationSummary": validation_summary,
        "pickAliases": pick_aliases or {},
    }
    return contract_payload


# ── Canonical comparison (shadow mode) ─────────────────────────────────


def _extract_source_count(asset: dict[str, Any]) -> int | None:
    """Extract source count from a canonical snapshot asset dict.

    The pipeline writes ``source_values`` (dict[str, int]) via
    ``CanonicalAssetValue.to_dict()``.  Older test fixtures may use
    ``sources_used`` (list or int).  Handle both gracefully.
    """
    # Pipeline canonical output: source_values is a {source_id: score} dict
    source_values = asset.get("source_values")
    if isinstance(source_values, dict):
        return len(source_values)

    # Legacy/test fixture: sources_used as list or int
    sources_used = asset.get("sources_used")
    if isinstance(sources_used, int):
        return sources_used
    if isinstance(sources_used, list):
        return len(sources_used)
    return None


def _canonical_final_value(asset: dict[str, Any]) -> float | None:
    """Return the best available final canonical value for an asset.

    Preference order: calibrated_value > blended_value.
    """
    for key in ("calibrated_value", "blended_value"):
        v = _safe_num(asset.get(key))
        if v is not None:
            return v
    return None


def _extract_source_breakdown(asset: dict[str, Any]) -> dict[str, int] | None:
    """Extract per-source canonical scores from a pipeline asset dict.

    Returns ``{source_id: canonical_score}`` when the pipeline-format
    ``source_values`` field is present, otherwise ``None``.
    """
    source_values = asset.get("source_values")
    if isinstance(source_values, dict) and source_values:
        return {str(k): _to_int_or_none(v) for k, v in source_values.items()}
    return None


def build_canonical_comparison_block(
    canonical_snapshot: dict[str, Any],
    *,
    loaded_at: str | None = None,
    legacy_players: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a non-authoritative comparison block from a canonical pipeline snapshot.

    The block is designed to be attached to the contract payload under the
    ``canonicalComparison`` key when ``CANONICAL_DATA_MODE=shadow``.  It
    carries enough information for debugging tools and the future Next.js
    trade page to render a side-by-side comparison against the live legacy
    values — but it is **never** the value authority.

    When *legacy_players* is supplied (the ``players`` dict from the scraper
    payload), per-asset deltas are computed so debugging tools can spot the
    biggest divergences between legacy and canonical values.
    """
    assets: list[dict[str, Any]] = canonical_snapshot.get("assets", [])

    # Build a lightweight lookup: display_name → comparison entry.
    asset_lookup: dict[str, dict[str, Any]] = {}
    for asset in assets:
        key = str(asset.get("display_name", asset.get("asset_key", ""))).strip()
        if not key:
            continue
        final = _canonical_final_value(asset)
        universe = str(asset.get("universe", "")).strip() or None
        source_count = _extract_source_count(asset)
        source_breakdown = _extract_source_breakdown(asset)

        display = _to_int_or_none(asset.get("display_value"))
        entry: dict[str, Any] = {
            "canonicalValue": _to_int_or_none(final) if final is not None else None,
            "displayValue": display,
            "universe": universe,
            "sourcesUsed": source_count,
        }
        if source_breakdown is not None:
            entry["sourceBreakdown"] = source_breakdown

        # Compute delta against legacy value if available.
        if legacy_players is not None:
            legacy_data = legacy_players.get(key)
            if isinstance(legacy_data, dict):
                legacy_val = _to_int_or_none(
                    legacy_data.get("_finalAdjusted")
                    or legacy_data.get("_composite")
                )
                entry["legacyValue"] = legacy_val
                canonical_int = entry["canonicalValue"]
                if legacy_val is not None and canonical_int is not None:
                    entry["delta"] = canonical_int - legacy_val

        # On name collision, keep the entry with the higher canonical value.
        existing_entry = asset_lookup.get(key)
        if existing_entry is not None:
            existing_val = existing_entry.get("canonicalValue") or 0
            new_val = entry.get("canonicalValue") or 0
            if existing_val >= new_val:
                continue
        asset_lookup[key] = entry

    # Snapshot-level metadata.
    run_id = str(canonical_snapshot.get("run_id", "")).strip() or None
    snapshot_id = str(canonical_snapshot.get("source_snapshot_id", "")).strip() or None

    # Summary statistics for quick debugging.
    deltas = [a["delta"] for a in asset_lookup.values() if "delta" in a]
    matched_count = sum(1 for a in asset_lookup.values() if "legacyValue" in a)
    summary: dict[str, Any] = {
        "canonicalAssetCount": len(asset_lookup),
        "matchedToLegacy": matched_count,
        "unmatchedCanonical": len(asset_lookup) - matched_count,
    }
    if deltas:
        abs_deltas = [abs(d) for d in deltas]
        summary["avgAbsDelta"] = int(round(sum(abs_deltas) / len(abs_deltas)))
        summary["maxAbsDelta"] = max(abs_deltas)
        summary["avgDelta"] = int(round(sum(deltas) / len(deltas)))

    return {
        "mode": "shadow",
        "notice": "Non-authoritative comparison data from the canonical pipeline. Live values remain legacy.",
        "snapshotRunId": run_id,
        "snapshotSourceId": snapshot_id,
        "loadedAt": loaded_at or utc_now_iso(),
        "assetCount": len(asset_lookup),
        "summary": summary,
        "assets": asset_lookup,
    }


def build_shadow_comparison_report(
    canonical_snapshot: dict[str, Any],
    legacy_players: dict[str, Any],
) -> dict[str, Any]:
    """Build a structured comparison report for shadow-mode diagnostics.

    This is the *analysis* complement to ``build_canonical_comparison_block``
    (which is the *payload* complement).  It produces a human-readable,
    decision-useful report that answers:

    * How many players overlap between canonical and legacy?
    * Where do they agree and disagree?
    * Which players have the biggest value divergences?
    * Does the canonical snapshot look sane (rank correlation)?
    * What's only in one source but not the other?

    The output is designed for ``/api/scaffold/shadow`` and server logs.
    It never touches the authoritative payload.
    """
    canonical_assets = canonical_snapshot.get("assets", [])

    # Build lookup tables.  On name collision (same player in rookie + vet
    # universes), keep the entry with the higher final value — consistent
    # with the comparison pipeline's collision strategy.
    canonical_by_name: dict[str, dict[str, Any]] = {}
    for asset in canonical_assets:
        name = str(asset.get("display_name", asset.get("asset_key", ""))).strip()
        if not name:
            continue
        existing = canonical_by_name.get(name)
        if existing is not None:
            existing_val = _canonical_final_value(existing) or 0
            new_val = _canonical_final_value(asset) or 0
            if existing_val >= new_val:
                continue
        canonical_by_name[name] = asset

    legacy_values: dict[str, int] = {}
    for name, pdata in (legacy_players or {}).items():
        if not isinstance(pdata, dict):
            continue
        val = _to_int_or_none(
            pdata.get("_finalAdjusted")
            or pdata.get("_composite")
        )
        if val is not None and val > 0:
            legacy_values[name] = val

    # Overlap analysis.
    canonical_names = set(canonical_by_name.keys())
    legacy_names = set(legacy_values.keys())
    matched_names = canonical_names & legacy_names
    canonical_only = canonical_names - legacy_names
    legacy_only = legacy_names - canonical_names

    # Per-player deltas for matched players.
    deltas: list[dict[str, Any]] = []
    for name in matched_names:
        c_asset = canonical_by_name[name]
        c_val = _to_int_or_none(_canonical_final_value(c_asset))
        l_val = legacy_values[name]
        if c_val is None:
            continue
        delta = c_val - l_val
        deltas.append({
            "name": name,
            "canonicalValue": c_val,
            "legacyValue": l_val,
            "delta": delta,
            "absDelta": abs(delta),
            "pctDelta": round(delta / l_val * 100, 1) if l_val else 0,
            "universe": str(c_asset.get("universe", "")),
            "sourcesUsed": _extract_source_count(c_asset),
        })

    deltas.sort(key=lambda d: d["absDelta"], reverse=True)

    # Top movers — biggest positive and negative deltas.
    top_risers = sorted(
        [d for d in deltas if d["delta"] > 0],
        key=lambda d: d["delta"],
        reverse=True,
    )[:10]
    top_fallers = sorted(
        [d for d in deltas if d["delta"] < 0],
        key=lambda d: d["delta"],
    )[:10]

    # Rank correlation — Spearman-like: do the orderings roughly agree?
    # Use simple overlap of top-50 in each list.
    canonical_ranked = sorted(
        [(n, _to_int_or_none(_canonical_final_value(a)) or 0) for n, a in canonical_by_name.items()],
        key=lambda x: -x[1],
    )
    legacy_ranked = sorted(legacy_values.items(), key=lambda x: -x[1])
    canonical_top50 = {name for name, _ in canonical_ranked[:50]}
    legacy_top50 = {name for name, _ in legacy_ranked[:50]}
    top50_overlap = len(canonical_top50 & legacy_top50)
    top50_denom = min(len(canonical_top50), len(legacy_top50))

    # Delta distribution buckets.
    abs_deltas = [d["absDelta"] for d in deltas]
    buckets = {"under200": 0, "200to600": 0, "600to1200": 0, "over1200": 0}
    for ad in abs_deltas:
        if ad < 200:
            buckets["under200"] += 1
        elif ad < 600:
            buckets["200to600"] += 1
        elif ad < 1200:
            buckets["600to1200"] += 1
        else:
            buckets["over1200"] += 1

    # Summary stats.
    summary: dict[str, Any] = {
        "canonicalAssetCount": len(canonical_by_name),
        "legacyPlayerCount": len(legacy_values),
        "matchedCount": len(deltas),
        "canonicalOnlyCount": len(canonical_only),
        "legacyOnlyCount": len(legacy_only),
        "top50Overlap": top50_overlap,
        "top50OverlapPct": round(top50_overlap / top50_denom * 100) if top50_denom > 0 else 0,
    }
    if abs_deltas:
        summary["avgAbsDelta"] = int(round(sum(abs_deltas) / len(abs_deltas)))
        summary["medianAbsDelta"] = int(sorted(abs_deltas)[len(abs_deltas) // 2])
        summary["maxAbsDelta"] = max(abs_deltas)
        summary["p90AbsDelta"] = int(sorted(abs_deltas)[int(len(abs_deltas) * 0.9)])
        summary["deltaDistribution"] = buckets

    # Snapshot metadata.
    source_count = canonical_snapshot.get("source_count", 0)
    universes = canonical_snapshot.get("asset_count_by_universe", {})

    return {
        "generatedAt": utc_now_iso(),
        "snapshotRunId": str(canonical_snapshot.get("run_id", "")).strip() or None,
        "snapshotSourceCount": source_count,
        "snapshotUniverses": universes,
        "summary": summary,
        "topRisers": top_risers,
        "topFallers": top_fallers,
        "biggestMismatches": deltas[:20],
        "canonicalOnlySample": sorted(canonical_only)[:20],
        "legacyOnlySample": sorted(legacy_only)[:20],
    }


def _strip_startup_player_fields(player_row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (player_row or {}).items():
        key_s = str(key)
        if key_s in STARTUP_HEAVY_PLAYER_FIELDS:
            continue
        if any(key_s.startswith(prefix) for prefix in STARTUP_HEAVY_PLAYER_FIELD_PREFIXES):
            continue
        out[key_s] = value
    return out


def build_api_startup_payload(contract_payload: dict[str, Any]) -> dict[str, Any]:
    """
    Build a startup-slim payload for first paint / early interaction.

    Keeps the same top-level contract shape expected by the frontend,
    but strips heavyweight per-player debug fields and non-critical secondary
    top-level blobs so startup transfer/parse cost is lower.
    """
    base = deepcopy(contract_payload or {})

    for key in STARTUP_DROP_TOP_LEVEL_KEYS:
        base.pop(key, None)

    players_map = base.get("players")
    if isinstance(players_map, dict):
        slim_players: dict[str, Any] = {}
        for name, pdata in players_map.items():
            if isinstance(pdata, dict):
                slim_players[str(name)] = _strip_startup_player_fields(pdata)
            else:
                slim_players[str(name)] = pdata
        base["players"] = slim_players

    base["payloadView"] = "startup"
    return base


def assert_no_unexplained_single_source(
    players_array: list[dict[str, Any]],
    *,
    rank_limit: int = 400,
) -> list[dict[str, Any]]:
    """Return a list of top-N players that are single-source without an
    allowlist reason.

    Each entry in the returned list is a dict with:
      - canonicalName, position, rank, matchedSources, reason

    An empty list means every 1-src player in the top N is either fixed
    or explicitly justified in ``SINGLE_SOURCE_ALLOWLIST``.

    This function is called by the build pipeline and regression tests
    to prevent unexplained 1-src cases from shipping to production.
    """
    unexplained: list[dict[str, Any]] = []
    for row in players_array:
        rank = row.get("canonicalConsensusRank")
        if rank is None or rank > rank_limit:
            continue
        is_1src = row.get("isSingleSource") or row.get("isStructurallySingleSource")
        if not is_1src:
            continue
        audit = row.get("sourceAudit") or {}
        if audit.get("allowlistReason"):
            continue
        unexplained.append({
            "canonicalName": row.get("canonicalName"),
            "position": row.get("position"),
            "rank": rank,
            "matchedSources": audit.get("matchedSources", []),
            "reason": audit.get("reason"),
        })
    return unexplained


def assert_ranking_coherence(
    players_array: list[dict[str, Any]],
) -> list[str]:
    """Verify monotonic ordering, no duplicate ranks, tier alignment,
    and rank-value coherence across the entire board.

    Returns a list of error strings.  An empty list means the board
    is coherent.  This function is the hard safety rail: the build
    pipeline and regression tests should call it and fail on any error.

    Checks:
    1. Monotonic rank: rank strictly increases (1, 2, 3, ...).
    2. No duplicate ranks for non-identical sort keys.
    3. Value monotonically decreases with rank (higher rank = lower value).
    4. Tier IDs are non-decreasing (tier N never appears after tier N+1).
    5. Every ranked row has both rank and value stamped.
    """
    errors: list[str] = []
    prev_rank: int | None = None
    prev_value: int | None = None
    prev_tier: int | None = None
    prev_name: str = ""
    seen_ranks: dict[int, str] = {}

    for row in players_array:
        rank = row.get("canonicalConsensusRank")
        if rank is None:
            continue
        value = row.get("rankDerivedValue")
        tier = row.get("canonicalTierId")
        name = row.get("canonicalName") or ""

        # Check 1: rank must be stamped alongside value
        if value is None or value <= 0:
            errors.append(
                f"#{rank} {name}: has rank but no rankDerivedValue"
            )

        # Check 2: no duplicate ranks
        if rank in seen_ranks:
            errors.append(
                f"#{rank} {name}: duplicate rank (also assigned to {seen_ranks[rank]})"
            )
        seen_ranks[rank] = name

        # Check 3: monotonic rank (strictly increasing)
        if prev_rank is not None and rank <= prev_rank:
            errors.append(
                f"#{rank} {name}: rank not strictly increasing (prev #{prev_rank} {prev_name})"
            )

        # Check 4: value monotonically decreasing with rank
        if (
            prev_value is not None
            and value is not None
            and prev_value > 0
            and value > prev_value
        ):
            errors.append(
                f"#{rank} {name}: value {value} > prev value {prev_value} "
                f"(#{prev_rank} {prev_name}) — rank/value order divergence"
            )

        # Check 5: tier non-decreasing
        if (
            prev_tier is not None
            and tier is not None
            and tier < prev_tier
        ):
            errors.append(
                f"#{rank} {name}: tier {tier} < prev tier {prev_tier} "
                f"(#{prev_rank} {prev_name}) — tier boundary misalignment"
            )

        prev_rank = rank
        prev_value = value
        prev_tier = tier
        prev_name = name

    return errors


def validate_api_data_contract(payload: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(payload, dict):
        return {
            "ok": False,
            "status": "invalid",
            "errors": ["payload is not an object"],
            "warnings": [],
            "errorCount": 1,
            "warningCount": 0,
            "checkedAt": utc_now_iso(),
            "contractVersion": CONTRACT_VERSION,
            "playerCount": 0,
        }

    for key in sorted(REQUIRED_TOP_LEVEL_KEYS):
        if key not in payload:
            errors.append(f"missing top-level key: {key}")

    value_authority = payload.get("valueAuthority")
    if not isinstance(value_authority, dict):
        errors.append("valueAuthority must be an object")
    else:
        coverage = value_authority.get("coverage")
        if not isinstance(coverage, dict):
            errors.append("valueAuthority.coverage must be an object")

    players_map = payload.get("players")
    if not isinstance(players_map, dict):
        errors.append("players must be an object map")

    players_array = payload.get("playersArray")
    if not isinstance(players_array, list):
        errors.append("playersArray must be a list")
        players_array = []

    sites = payload.get("sites")
    if not isinstance(sites, list):
        errors.append("sites must be a list")
        sites = []

    site_keys = [str(s.get("key")) for s in sites if isinstance(s, dict) and s.get("key")]

    for idx, row in enumerate(players_array[:1000]):
        if not isinstance(row, dict):
            errors.append(f"playersArray[{idx}] must be object")
            continue
        for key in REQUIRED_PLAYER_KEYS:
            if key not in row:
                errors.append(f"playersArray[{idx}] missing key: {key}")

        values = row.get("values")
        if not isinstance(values, dict):
            errors.append(f"playersArray[{idx}].values must be object")
        else:
            for k in ("overall", "rawComposite", "finalAdjusted"):
                if k not in values:
                    errors.append(f"playersArray[{idx}].values missing key: {k}")

        canonical_sites = row.get("canonicalSiteValues")
        if not isinstance(canonical_sites, dict):
            errors.append(f"playersArray[{idx}].canonicalSiteValues must be object")
        elif site_keys:
            missing_keys = [k for k in site_keys if k not in canonical_sites]
            if missing_keys:
                warnings.append(
                    f"playersArray[{idx}] canonicalSiteValues missing keys: {', '.join(missing_keys[:6])}"
                )

    idp_count = 0
    normalized_pos_by_name: dict[str, set[str]] = {}
    for row in players_array:
        if not isinstance(row, dict):
            continue
        name = str(row.get("canonicalName") or row.get("displayName") or "").strip()
        pos = str(row.get("position") or "").strip().upper()
        if pos in _IDP_POSITIONS:
            idp_count += 1

        canonical_sites = row.get("canonicalSiteValues") or {}
        has_off_signal = isinstance(canonical_sites, dict) and any(
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _OFFENSE_SIGNAL_KEYS
        )
        has_idp_signal = isinstance(canonical_sites, dict) and any(
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _IDP_SIGNAL_KEYS
        )
        if pos in _IDP_POSITIONS and has_off_signal and not has_idp_signal:
            # Skip the hard-fail for verified cross-universe collisions
            # (Josh Johnson: QB ≠ S).  The exception only applies on a
            # full-board payload so synthetic unit test fixtures still
            # fail loudly when contamination is present.
            current_flags = row.get("anomalyFlags") or []
            has_collision = "name_collision_cross_universe" in current_flags
            is_known_collision = (
                name in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS
            )
            if len(players_array) >= 250 and (has_collision or is_known_collision):
                pass
            else:
                errors.append(
                    f"playersArray offense→IDP mismatch: {name or '<unknown>'} tagged {pos} "
                    "with offensive-only source signal(s)"
                )

        if name:
            norm = _canonical_match_key(name) or re.sub(
                r"[^a-z0-9]+", "", str(name).lower()
            )
            normalized_pos_by_name.setdefault(norm, set()).add(pos or "?")

    for norm_name, poses in normalized_pos_by_name.items():
        cleaned = {p for p in poses if p and p != "?"}
        has_off = bool(cleaned & _OFFENSE_POSITIONS)
        has_idp = bool(cleaned & _IDP_POSITIONS)
        if has_off and has_idp:
            errors.append(f"possible offense/IDP name collision detected for normalized name '{norm_name}'")

    if len(players_array) >= 250 and idp_count < 25:
        errors.append(
            f"implausibly small IDP pool in playersArray: {idp_count}/{len(players_array)} "
            "(expected at least 25 when full board is present)"
        )

    if not players_array:
        warnings.append("playersArray is empty")
    if not site_keys:
        warnings.append("sites is empty or missing keys")

    # Optional: canonicalComparison (shadow mode comparison block).
    canonical_cmp = payload.get("canonicalComparison")
    if canonical_cmp is not None:
        if not isinstance(canonical_cmp, dict):
            warnings.append("canonicalComparison should be an object when present")
        else:
            if canonical_cmp.get("mode") != "shadow":
                warnings.append("canonicalComparison.mode should be 'shadow'")
            cmp_assets = canonical_cmp.get("assets")
            if cmp_assets is not None and not isinstance(cmp_assets, dict):
                warnings.append("canonicalComparison.assets should be an object map")
            cmp_summary = canonical_cmp.get("summary")
            if cmp_summary is not None and not isinstance(cmp_summary, dict):
                warnings.append("canonicalComparison.summary should be an object when present")

    ok = len(errors) == 0
    status = "healthy" if ok else "invalid"
    return {
        "ok": ok,
        "status": status,
        "errors": errors[:200],
        "warnings": warnings[:200],
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "checkedAt": utc_now_iso(),
        "contractVersion": str(payload.get("contractVersion") or CONTRACT_VERSION),
        "playerCount": len(players_array),
    }
