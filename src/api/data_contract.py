from __future__ import annotations

import bisect
from copy import deepcopy
import json
import logging
import math
import os
import re
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.canonical.player_valuation import (
    PERCENTILE_REFERENCE_N as _CANONICAL_PERCENTILE_REFERENCE_N,
)
from src.data_models.contracts import utc_now_iso

_LOGGER = logging.getLogger(__name__)

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
        "Josh Johnson",  # QB (retired journeyman) vs S (draftable prospect)
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
    "ktcSfTep",
    "dlfSf",
    "dynastyNerdsSfTep",
    "yahooBoone",
    "fantasyProsFitzmaurice",
}
_IDP_SIGNAL_KEYS = {
    "idpTradeCalc",
    "dlfIdp",
    "fantasyProsIdp",
    "idpShow",
}

# All source signal keys — used to detect which source(s) a player has
_ALL_SIGNAL_KEYS = _OFFENSE_SIGNAL_KEYS | _IDP_SIGNAL_KEYS

# ── Confidence bucket thresholds ────────────────────────────────────────────
# Buckets describe how much trust a consumer should place in a player's
# unified rank.  Determined by source count and source agreement.
#
# Agreement is measured in *percentile* space rather than absolute
# ordinal ranks so IDP players aren't unfairly bucketed as "low" just
# because IDP sources have smaller pools.  Example: an IDP with ranks
# [52, 62, 148, 151, 1] across sources has an absolute spread of 150
# (far above the legacy 80 threshold), but a percentile spread of
# ~0.16 because each rank lives inside a much smaller pool — the
# sources are actually in broad tier-agreement.  The offense-only
# absolute thresholds used to fire "low" on well-covered IDP rows.
#
# Rules (evaluated top-to-bottom, first match wins):
#   "high"   — 2+ sources AND percentileSpread <= 0.08   (within 8%)
#   "medium" — 2+ sources AND percentileSpread <= 0.20   (within 20%)
#   "low"    — single source, OR percentileSpread > 0.20, OR no
#              percentile signal and absolute spread > 80
#   "none"   — player did not receive a unified rank
#
# The 0.20 medium ceiling aligns with the
# ``suspicious_disagreement`` flag threshold — anything worse than
# 20% percentile spread is by definition widely-disagreed coverage,
# which is exactly the "low" bucket.
_CONFIDENCE_PERCENTILE_HIGH = 0.08
_CONFIDENCE_PERCENTILE_MEDIUM = 0.20
# Legacy absolute-ordinal fallback for callers that don't pass a
# percentile spread (older tests, third-party consumers).  Kept at
# the pre-fix thresholds so their existing expectations still hold.
_CONFIDENCE_SPREAD_HIGH = 30
_CONFIDENCE_SPREAD_MEDIUM = 80

# ── Trimmed percentile spread ────────────────────────────────────────────────
# With this many sources or more, ``_percentile_rank_spread`` ignores the
# single most extreme percentile on EACH side before taking max-minus-min.
#
# Rationale (2026-07-25 caution-saturation audit): the raw max-minus-min
# statistic grows mechanically with source count — with 12 sources the
# spread is defined entirely by the single most optimistic and single
# most pessimistic voice, so one straggler flags the row.  The 0.10 /
# 0.20 disagreement thresholds were tuned when top players carried 4-6
# sources; after the May-July source additions they carry ~12, and the
# flags saturated: 72% of the top-200 board carried "wide disagreement"
# (rows with >=3 sources flagged ~90% of the time, rising WITH coverage
# — more data was reading as less confidence).  Trimming one voice per
# side restores the intended semantics: a caution requires two
# independent sources on each wing to genuinely split on the player.
# Measured on the 2026-07-25 live board, top-200 disagreement drops
# 143 -> ~40 rows and suspicious_disagreement 82 -> ~15.
#
# n >= 5 so trimming never reduces the statistic below a 3-source
# core; below that the untrimmed range is still the right measure.
_PERCENTILE_SPREAD_TRIM_MIN_N = 5

# ── Depth-aware disagreement allowance ──────────────────────────────────────
# Even after trimming, expected spread grows with rank depth — on the
# 2026-07-25 board the MEDIAN trimmed spread is 0.068 inside the top
# 100 but 0.30 at ranks 201-400.  Two structural reasons: (1) sources
# genuinely order deep players near-randomly (that's where the market
# hasn't converged), and (2) pool-size normalisation makes identical
# ordinal placements read as different percentiles when source depths
# differ (rank 66 in a 280-pool = 0.24 vs rank 44 in a 500-pool =
# 0.09).  A flat threshold therefore either saturates the deep board
# or never fires at the top.
#
# The caution/anomaly thresholds get a linear allowance equal to the
# player's own consensus percentile (rank / ranked-pool-size), capped:
# flag only the spread IN EXCESS of what is typical at that depth.
# Confidence buckets deliberately do NOT get the allowance — they
# describe absolute trust in the row's value, and a deep player with
# 0.30 spread is genuinely less certain no matter how normal that is
# for its neighbourhood.
_DISAGREEMENT_BASE_THRESHOLD = 0.10  # hasSourceDisagreement (caution label)
_SUSPICIOUS_PCT_BASE_THRESHOLD = 0.20  # suspicious_disagreement (anomaly flag)
_DISAGREEMENT_DEPTH_ALLOWANCE_CAP = 0.25


def _disagreement_depth_allowance(consensus_percentile: float | None) -> float:
    """Linear depth allowance added to both disagreement thresholds.

    ``consensus_percentile`` is the player's unified rank divided by
    the ranked pool size (0..1); the allowance equals it, capped at
    ``_DISAGREEMENT_DEPTH_ALLOWANCE_CAP`` so the flags can still fire
    on the deep board's true pathologies.
    """
    if consensus_percentile is None:
        return 0.0
    return min(max(float(consensus_percentile), 0.0), _DISAGREEMENT_DEPTH_ALLOWANCE_CAP)


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

# ── Per-player Hampel outlier rejection ──────────────────────────────────────
# Before aggregating per-source values into a player's blended rank, run a
# Hampel filter across that player's source values: drop any source whose
# value sits more than ``_HAMPEL_K`` median-absolute-deviations from the
# median of the others.  This catches the "FootballGuys is way off on this
# one player" case without dropping the whole source globally.
#
# Guards (see ``_hampel_filter_per_player``):
#   * ``len(values) < _HAMPEL_MIN_N`` → no filtering (median + MAD too
#     unstable to identify outliers reliably below 4 sources)
#   * MAD == 0 → no filtering (perfect agreement; nothing is an outlier)
#   * Filter would leave fewer than 2 surviving sources → no filtering
#   * Pick rows skip Hampel entirely (KTC's per-slot synthetic values
#     create artificial agreement that the statistic mis-reads)
#
# K=2.75 sits between the textbook conservative K=3 (≈3σ for normal data)
# and the more aggressive K=2.5; tuned for our typical n=4–8 source coverage
# where a single mis-categorised or stale value can shift the consensus by
# 500–1500 Hill points.
#
# ``_HAMPEL_MIN_THRESHOLD`` is an absolute floor on ``K · MAD`` in Hill-value
# units (the 0–9999 scale on which all per-source contributions live).  Without
# it, a tight cluster like [4950, 5000, 5025, 5050, 5100] (MAD=25, K·MAD=68.75)
# would call values ±75 from the median "outliers" — nonsense at this scale.
#
# 1000 is roughly 10% of the full Hill range.  The previous 500-point floor
# (5%) was empirically too tight: with KTC + ktcSfTep + IDPTC + dynastyDaddySf
# all riding the value-direct path from a shared market, the four typically
# cluster within 50–150 Hill points on most rows (MAD ≪ 200), pulling the
# median onto that cluster and making the K·MAD term collapse to the floor.
# The rank-Hill sources (whose curve produces a ~2000-point spread between
# adjacent rank decades at the steep top of the Hill) then sit outside the
# 500-point floor on routine disagreements and get dropped.  The 2026-04-27
# weekly audit caught this as 18% / 25% / 25% drop rates on dlfSf /
# dlfRookieSf / flockFantasySfRookies — none of which is a broken source,
# all of which the prior PR #215/216 regressions (dynastyDaddySf 61%,
# yahooBoone 47%, fantasyProsFitzmaurice 19%) cleared at the bigger floor.
# A source within 1000 Hill points of the rest of the field is in genuine
# consensus regardless of how tight the value-direct bulk happens to be.
_HAMPEL_K = 2.75
_HAMPEL_MIN_N = 4
_HAMPEL_MIN_THRESHOLD = 1000.0

_RETIRED_INVALID_PATTERNS = re.compile(r"(?i)\b(retired|invalid|test|unknown|placeholder)\b")
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
    "ktc": "CSVs/site_raw/ktc.csv",
    # KeepTradeCut Superflex + TE Premium (level 2 / "TE++") sub-board.
    # Sourced from the same scrape as ``ktc`` — the per-player API
    # response carries ``superflexValues.tepp`` alongside the base SF
    # value, so a single Dynasty Scraper run produces both CSVs.
    # Standard ``name,value`` shape on the same 0-9999 scale; signal
    # defaults to "value".
    "ktcSfTep": "CSVs/site_raw/ktcSfTep.csv",
    "idpTradeCalc": "CSVs/site_raw/idpTradeCalc.csv",
    "dlfIdp": {
        "path": "CSVs/site_raw/dlfIdp.csv",
        "signal": "rank",
    },
    # The IDP Show (Adamidp) — Substack-hosted IDP rankings article
    # at theidpshow.com/p/idp-dynasty-rankings.  The actual rankings
    # are served from an embedded Datawrapper iframe whose
    # dataset.csv is publicly accessible.  Fetched by
    # ``scripts/fetch_idpshow.py`` which authenticates into the
    # paywalled article (via cookie-dump session), extracts the
    # current chart ID from the iframe src, and downloads the
    # dataset.  Signal=rank — the chart includes a TRADE VALUE
    # column but it's draft-pick-equivalent text ("1st + 2nd",
    # "3rd", etc.), not numeric, so we use the OVR column as the
    # rank signal.  ~420 rows covering ED/IDL/LB/S/CB.
    "idpShow": {
        "path": "CSVs/site_raw/idpShow.csv",
        "signal": "rank",
    },
    # DLF Dynasty Superflex rankings — offense expert consensus.
    # Auto-refreshed by ``scripts/fetch_dlf.py`` on each scheduled
    # run, which POSTs credentials to DLF's wp-login, fetches the
    # member-gated table, and writes a ``name,rank`` CSV preferring
    # the expert-consensus Avg column over the nominal Rank column.
    "dlfSf": {
        "path": "CSVs/site_raw/dlfSf.csv",
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
        "path": "CSVs/site_raw/dynastyNerdsSfTep.csv",
        "signal": "rank",
    },
    # FantasyPros Dynasty Superflex rankings — scraped from
    # https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php
    # via ``scripts/fetch_fantasypros_offense.py``.  The CSV has an
    # explicit ``Rank`` column written from the ecrData players array,
    # filtered to offensive positions (QB/RB/WR/TE).  Signal=rank so
    # the ``_enrich_from_source_csvs`` reader uses the rank column.
    "fantasyProsSf": {
        "path": "CSVs/site_raw/fantasyProsSf.csv",
        "signal": "rank",
    },
    # FantasyPros Dynasty IDP rankings — scraped from the four dynasty
    # IDP pages (combined + DL + LB + DB) via
    # ``scripts/fetch_fantasypros_idp.py``.  The combined IDP page is
    # authoritative for overall cross-position ordering; individual
    # DL/LB/DB pages are used only as depth extension via monotone
    # piecewise-linear anchor curves fit from the overlap.  Final
    # effective overall ranks are written to the CSV as
    # ``effectiveRank``, and the fetch script aliases it to a ``Rank``
    # column via the _RANK_ALIASES + _NAME_ALIASES handshake below so
    # the standard rank-signal path picks it up.
    "fantasyProsIdp": {
        "path": "CSVs/site_raw/fantasyProsIdp.csv",
        "signal": "rank",
    },
    # FantasyCalc dynasty Superflex trade values — fetched from the
    # public JSON API at https://api.fantasycalc.com/values/current
    # (?isDynasty=true&numQbs=2&numTeams=12&ppr=1) via
    # ``scripts/fetch_fantasycalc.py``.  Same crowd-sourced board
    # that powers https://www.fantasycalc.com/dynasty-rankings.  We
    # filter to offensive positions (QB/RB/WR/TE) and write a
    # ``name,value,rank`` CSV.  Signal=value — FantasyCalc's value
    # distribution is well-spread (no display ceiling like Dynasty
    # Daddy or Yahoo Boone).  Picks (position "PICK") are dropped here
    # and tethered to rookie values in a dedicated downstream phase.
    # Standard SF scoring — values are NOT TE-premium native, so the
    # frontend ``tepMultiplier`` boost applies on top of the blended
    # contribution (registry entry sets ``is_tep_premium=False``).
    #
    # Signal=rank (2026-07-25): added 2026-05-13 on the value-direct
    # path under the "well-spread distribution" rationale, but the
    # weekly Hampel audit flagged it EVERY week from its first Monday
    # on the board (54.9% on 2026-05-18 → 56-58% through July).  The
    # problem is the opposite of the Dynasty Daddy display-ceiling
    # case: FantasyCalc's crowd values decay much *faster* down the
    # board than the KTC-anchored Hill consensus (at consensus rank ~8
    # FC contributes ~7,200 against a ~9,000 median — a 1,800+ point
    # gap on row after row), so value-direct normalisation put it
    # outside the Hampel window on half its rows and its vote was
    # simply discarded.  Routing through the rank-signal path feeds
    # its ordinal rank into the OFFENSE-scope Hill curve, matching the
    # consensus decay shape while preserving FantasyCalc's ordering —
    # the same conversion that fixed dynastyDaddySf (61% → 0%),
    # yahooBoone (47% → ~2%), and fantasyProsFitzmaurice (19% → ~0%).
    # The ``value`` column is preserved via ``sourceNativeValues`` for
    # audit / display / trade-finder use (``canonicalSiteValues``
    # carries the synthetic rank encoding, not the crowd value).
    "fantasyCalc": {
        "path": "CSVs/site_raw/fantasyCalc.csv",
        "signal": "rank",
    },
    # OTC Fantasy Football Superflex trade-derived values — fetched
    # from https://otcffb.com/api/trade-values?format=sf via
    # ``scripts/fetch_otcffb.py``.  Public JSON, no auth.  ~471
    # offensive players with a 0-100 value scale (Bijan=100), derived
    # from OTCFFB's tracked league trades (354k+ trades observed).
    # Independent signal from KTC / FantasyCalc — same crowd-sourced
    # spirit as FantasyCalc but pulled from a different community.
    # Standard SF scoring — not TE-premium native, so the frontend
    # ``tepMultiplier`` boost applies.
    #
    # Signal=rank (2026-07-25): same story and same fix as
    # ``fantasyCalc`` above — added 2026-05-15 as value-direct,
    # Hampel-flagged every week since (55.6% on 2026-05-18 climbing to
    # 80-86% by July, the worst in the registry).  OTCFFB's trade-
    # derived 0-100 values decay even faster than FantasyCalc's (79%
    # of top value by rank 7 vs KTC's ~90% at rank 8), so the value-
    # direct path made it a systematic low outlier on most of the
    # board and four of every five of its votes were discarded.  The
    # ``value`` column is preserved via ``sourceNativeValues`` for
    # audit / display.
    "otcffbSf": {
        "path": "CSVs/site_raw/otcffbSf.csv",
        "signal": "rank",
    },
    # Dynasty Daddy Superflex trade values — fetched from
    # https://dynasty-daddy.com/api/v1/player/all/today?market=14
    # via ``scripts/fetch_dynasty_daddy.py``.  The API returns crowd-
    # sourced SF trade values for ~641 players; we filter to offensive
    # positions (QB/RB/WR/TE) and write a ``name,value,rank`` CSV.
    #
    # Signal=rank (2026-04-22): Dynasty Daddy's top values cluster at
    # a display ceiling of 10,200 — the top three players (Ja'Marr
    # Chase, Jahmyr Gibbs, Josh Allen) are all tied at 10,200 with
    # Jaxon Smith-Njigba and Bijan Robinson just below.  The previous
    # ``value-direct`` path mapped all of these to 9,999 after
    # normalisation, collapsing their relative order and tripping the
    # Hampel filter on 61% of rows (the worst in the registry — see
    # ``scripts/audit_dropped_sources.py`` output 2026-04-22).
    # Routing through the rank-signal path instead uses DynastyDaddy's
    # value-ordered rank as the signal, restoring the relative
    # ordering the value cap destroys.  The ``value`` column is
    # preserved via ``sourceNativeValues`` for audit / display.
    "dynastyDaddySf": {
        "path": "CSVs/site_raw/dynastyDaddySf.csv",
        "signal": "rank",
    },
    # Flock Fantasy Dynasty Superflex rankings — expert consensus from
    # https://flockfantasy.com via JSON API (?format=superflex).
    # Multi-expert averaged ranks (~368 offensive players after
    # filtering).  Signal=rank so the ``_enrich_from_source_csvs``
    # reader uses the rank column, not a value column.
    "flockFantasySf": {
        "path": "CSVs/site_raw/flockFantasySf.csv",
        "signal": "rank",
    },
    # Flock Fantasy Dynasty Superflex ROOKIE rankings — fetched from
    # https://api.flockfantasy.com/rankings?format=PROSPECTS_SF via
    # ``scripts/fetch_flock_fantasy_rookies.py``.  Same multi-expert
    # averaged-rank shape as ``flockFantasySf`` but scoped to the
    # current incoming rookie class only (~95 prospects).  Signal=rank
    # — registered as ``needs_rookie_translation=True`` so the
    # within-class rank is crosswalked through KTC's offense rookie
    # ladder before the Hill curve, mirroring ``dlfRookieSf``.
    "flockFantasySfRookies": {
        "path": "CSVs/site_raw/flockFantasySfRookies.csv",
        "signal": "rank",
    },
    # Yahoo / Justin Boone dynasty trade value charts — scraped from
    # sports.yahoo.com via ``scripts/fetch_yahoo_boone.py``.  The
    # scraper combines Boone's QB (2QB column), RB, WR, and TE
    # (TE-Prem. column) charts into one cross-positional pool and
    # writes BOTH a competition rank and Boone's published trade
    # value (0-~141 scale where Boone's top player = 141) to the CSV
    # columns ``rank`` and ``boone_value``.
    #
    # Signal=rank (2026-04-22): Boone's published value column (0-~141
    # range) has a compressed top — values 141, 130, 122, 115, 110,
    # 110, 109 for the top seven players.  The previous ``value-direct``
    # normalisation mapped all seven into a narrow 9400-9999 band,
    # which the per-player Hampel filter (see
    # ``_hampel_filter_per_player``) then correctly rejected against
    # KTC/IDPTC's more differentiated value curves — yahooBoone hit a
    # 47% drop rate in the live audit (see
    # ``scripts/audit_dropped_sources.py``).  Routing Boone through
    # the rank-signal path instead feeds his ordinal rank into the
    # shared Hill curve, which gives each rank position a
    # differentiated value just like DLF's rank-signal sources.  The
    # published ``boone_value`` column is preserved via
    # ``sourceNativeValues`` so the raw number remains visible, it
    # just no longer participates in the blend directly.
    "yahooBoone": {
        "path": "CSVs/site_raw/yahooBoone.csv",
        "signal": "rank",
    },
    # FantasyPros Dynasty Trade Value Chart — Pat Fitzmaurice's
    # monthly article-based chart.  Fetched by
    # ``scripts/fetch_fantasypros_fitzmaurice.py`` which resolves
    # the date-rotating article URL, parses the four embedded
    # Datawrapper iframes (QB/RB/WR/TE), and writes per-position
    # values on a 0-~101 scale plus a global 1-indexed rank.
    #
    # Signal=rank (2026-04-22, restored): Fitzmaurice's value scale
    # hits its ceiling hard — the top dozen+ players cluster between
    # 80 and 101 with many ties, which the ``value-direct`` path
    # collapsed into a narrow top band and the Hampel filter then
    # correctly rejected against differentiated sources like KTC.
    # PR #216 originally moved this to rank-signal (19% → 1.7% drop
    # rate); the subsequent PR #218 merge silently reverted the flag
    # back to ``value`` while leaving the rest of the scaffolding
    # intact.  The live audit re-caught the 19% drop rate and this
    # restores the PR #216 state.  Same template as dynastyDaddySf
    # and yahooBoone above.
    "fantasyProsFitzmaurice": {
        "path": "CSVs/site_raw/fantasyProsFitzmaurice.csv",
        "signal": "rank",
    },
    # DLF Dynasty Rookie Superflex rankings — 6-expert consensus of the
    # current rookie class only (no veterans).  Raw CSV exported from
    # DLF with Rank, Avg, Pos, Name, Team, Age, expert columns.  Signal=
    # rank (the ``Avg`` column wins over ``Rank`` via _RANK_ALIASES).
    #
    # The source's within-source rank 1 needs rookie-class translation
    # (``needs_rookie_translation=True``) so DLF's #1 rookie doesn't
    # get mapped to overall rank 1 → value 9999 at the Hill curve.
    # Translation anchors each within-source rank to the corresponding
    # rookie's position on KTC's ladder (offense) or IDPTC's ladder
    # (IDP), preserving DLF's ORDERING while inheriting the reference
    # source's SCALE.
    "dlfRookieSf": {
        "path": "CSVs/site_raw/dlfRookieSf.csv",
        "signal": "rank",
    },
    # DLF Dynasty Rookie IDP rankings — same shape as the SF rookie
    # export but for DL/LB/DB prospects.  IDP rookie translation uses
    # the IDPTC IDP ladder.  Also auto-refreshed by
    # ``scripts/fetch_dlf.py``.
    "dlfRookieIdp": {
        "path": "CSVs/site_raw/dlfRookieIdp.csv",
        "signal": "rank",
    },
    # DraftSharks dynasty rankings — split into offense + IDP CSVs
    # by scripts/fetch_draftsharks.py.  The scraper reads the single
    # offense-combined DOM (where every player has a cross-universe
    # ``3D Value +`` on the same scale — e.g. Carson Schwesinger =
    # 44 at overall rank 36 among all positions) and writes two
    # files filtered by position family.  Both CSVs therefore share
    # the same raw value scale but describe separate pools, which
    # lets the blend treat DraftSharks as two independent sources
    # (one offense, one IDP) instead of a single cross-scope source
    # like IDPTradeCalc.
    "draftSharks": {
        "path": "CSVs/site_raw/draftSharksSf.csv",
        "signal": "value",
    },
    "draftSharksIdp": {
        "path": "CSVs/site_raw/draftSharksIdp.csv",
        "signal": "value",
    },
    # Fantasy Navigator superflex dynasty values — public unauthenticated
    # JSON API (https://fantasy-navigator-latest.onrender.com/ranks
    # ?platform=sf) fetched by ``scripts/fetch_fantasynavigator.py``
    # (filters to roster_type=sf_value + rank_type=dynasty, offense
    # positions, ~800 rows).  Signal=rank from day one: FN's values are
    # KTC-derived (rows carry ``ktc_player_id``), i.e. a KTC-adjacent
    # decay shape — exactly the profile that put fantasyCalc/otcffbSf
    # outside the Hampel window on the value-direct path.  The vendor
    # value column is preserved via ``sourceNativeValues`` for
    # display / audit.
    "fantasyNavigatorSf": {
        "path": "CSVs/site_raw/fantasyNavigatorSf.csv",
        "signal": "rank",
    },
    # Play for Keeps Dynasty master board — PFK's own hand-maintained
    # dynasty rankings read from their public Supabase PostgREST table
    # (``pfk_dynasty_rankings``, anonymous publishable-key read — the
    # same access their site gives any visitor) via
    # ``scripts/fetch_pfk.py`` (~500 offense rows; pick rows dropped,
    # they tether to rookie values downstream).  A genuinely
    # independent human signal (their ``pfk_ktc_values`` table is just
    # a KTC mirror we already ingest).  Signal=rank — the 0-9999 value
    # scale is hand-shaped and unvalidated against our consensus decay,
    # so the ordinal rank is the safe vote; the native value is
    # preserved via ``sourceNativeValues``.
    "pfkDynasty": {
        "path": "CSVs/site_raw/pfkDynasty.csv",
        "signal": "rank",
    },
}

# Rank -> synthetic value transform used when a CSV declares signal=rank.
# The absolute number is irrelevant to the downstream pipeline (it only
# cares about the *ordering* of eligible rows within the source), but we
# keep it above zero and bounded so the stamped value looks sensible to
# the trust/confidence + anomaly checks that read canonicalSiteValues.
_RANK_TO_SYNTHETIC_VALUE_OFFSET = 10000

# ── Source freshness windows ─────────────────────────────────────────────
# Per-source staleness budget in hours.  A CSV whose mtime is older than
# maxAgeHours is flagged as ``stale`` in dataFreshness.sourceTimestamps.
# ktc/idpTradeCalc/dynastyNerdsSfTep refresh daily via the scheduled
# scraper; DLF SF and DLF IDP are static-ish exports refreshed ~monthly
# by hand.
_SOURCE_MAX_AGE_HOURS: dict[str, int] = {
    "ktc": 6,
    # KTC TE++ (level 2) sub-board is sourced from the same scrape as
    # ``ktc``, so it shares the 6-hour staleness budget.
    "ktcSfTep": 6,
    "idpTradeCalc": 6,
    "dynastyNerdsSfTep": 6,
    "fantasyProsIdp": 6,
    "dynastyDaddySf": 6,
    # FantasyCalc public JSON API refreshes continuously as crowd
    # votes come in; the scheduled fetcher runs on the standard 3-hour
    # refresh cadence, so the same 6-hour freshness budget as ktc /
    # dynastyDaddySf applies.
    "fantasyCalc": 6,
    # OTCFFB public JSON API refreshes as community trades roll in; the
    # scheduled fetcher runs every 2 hours so the same 6-hour budget as
    # the other trade-derived sources applies.
    "otcffbSf": 6,
    "flockFantasySf": 168,
    # Flock Fantasy rookie board updates as experts refresh ranks
    # through the offseason; same 1-week window as the vet board.
    "flockFantasySfRookies": 168,
    "dlfIdp": 720,
    "dlfSf": 720,
    # Yahoo / Justin Boone trade value charts refresh ~monthly, so
    # allow a 30-day window; the fetcher also emits its own stale-
    # article warning if Yahoo's redirect chain ever stops resolving.
    "yahooBoone": 720,
    # FantasyPros / Pat Fitzmaurice Dynasty Trade Value Chart:
    # refreshes monthly as a new FP article.  30-day window.
    "fantasyProsFitzmaurice": 720,
    # The IDP Show (Adamidp): Substack article updated periodically;
    # give a 30-day freshness budget — staler than that and we
    # probably need a fresh cookie dump or the article is stale.
    "idpShow": 720,
    # DraftSharks SF + IDP CSVs are written by scripts/fetch_draftsharks.py
    # on every scheduled-refresh tick (3-hour cadence), so the same
    # 6-hour freshness budget as ktc / idpTradeCalc applies.
    "draftSharks": 6,
    "draftSharksIdp": 6,
    # Fantasy Navigator + PFK are fetched by scheduled 2-hour API
    # fetchers that rewrite the CSV on every SUCCESSFUL run — so mtime
    # measures fetch success, not the vendors' editorial cadence, and
    # the budget must match the other API-fetched sources (fantasyCalc
    # / otcffbSf / dynastyDaddySf): 6 hours ≈ three missed cycles.
    # (An earlier 720h/168h pair conflated this with how often the
    # vendors PUBLISH — which mtime cannot observe; Codex review on
    # PR #532.)
    "fantasyNavigatorSf": 6,
    "pfkDynasty": 6,
}

# ── Per-source row-count floors ───────────────────────────────────────────
# Embedded defaults; overridable via ``config/weights/source_row_floors.json``.
# Floors are set at ~80% of the current live baseline so a scrape
# regression that drops a source below its floor trips a warning.  A
# source with zero non-zero values is a hard error (``source_missing``).
_DEFAULT_SOURCE_ROW_FLOORS: dict[str, int] = {
    "ktc": 400,
    "idpTradeCalc": 700,
    "dlfIdp": 150,
    "dlfSf": 240,
    "dynastyNerdsSfTep": 230,
    # FantasyPros dynasty IDP: combined board + 3 individual boards
    # yield ~100 total rows (70 combined + 30 extension).  Floor at
    # ~75% of live baseline so a scrape regression trips a warning.
    "fantasyProsIdp": 75,
    "dynastyDaddySf": 250,
    # ``fantasyCalc``: floor intentionally NOT set here yet.  The
    # fetcher in scripts/fetch_fantasycalc.py was added 2026-05-13;
    # floors per the comment policy above are pinned at ~80% of the
    # *current live baseline*, and the source has no live baseline
    # until the next scheduled-refresh cycle generates the first CSV.
    # Add an entry here (target ~340 — ~75% of the 2026-03-25
    # historical 458-row snapshot) once a stable baseline is observed
    # in production.
    "flockFantasySf": 250,
    # Yahoo / Justin Boone charts: a complete QB+RB+WR+TE board is
    # ~450 raw rows that canonicalize to ~425 matches against the
    # Sleeper pool (this floor is checked against canonical matches,
    # not raw rows).  Boone is scraped as four independent per-position
    # seed URLs; one silently dropping out (dead redirect / changed
    # table) removes ~80-90 matches — losing TE alone drops the count
    # to ~344.  scripts/fetch_yahoo_boone now fails loudly and
    # preserves the last-good CSV in that case (``_YB_ROW_COUNT_FLOOR``
    # 400 + per-position ``_YB_MIN_ROWS_PER_POSITION`` 30), so this
    # contract floor is the second line of defence, not the first.
    # Re-pinned 400 -> 360 (2026-07-25): the live canonical-match count
    # drifted to ~380 (raw rows still clear the scraper's 400-raw floor;
    # the Sleeper-pool match rate slipped with player churn).  360 still
    # trips on the failure this floor exists for — a whole position
    # dropping out lands at ~344.  At 400 this check was red for weeks,
    # which also hard-blocked the weekly Hill-curve refit workflow.
    "yahooBoone": 360,
    # FantasyPros / Pat Fitzmaurice: QB (50) + RB (~88) + WR (~115) +
    # TE (~46) ≈ 299 rows at the April 2026 baseline.  Floor at ~75%.
    "fantasyProsFitzmaurice": 225,
    # The IDP Show: the CSV has ~419 rows but only ~200 canonicalize
    # against the Sleeper player pool (the source goes deep into
    # camp-body / backup IDPs that Sleeper doesn't enumerate).  Floor
    # at 150 covers ~75% of the realistic match rate — a partial
    # fetch or column-drop regression would trip this warning.
    "idpShow": 150,
    # DraftSharks: the scraper ingests 461 offense / 389 IDP rows,
    # but canonical-name matches against the Sleeper player pool
    # yield a smaller count because DS's deeper rows are prospects
    # not yet listed in Sleeper (e.g. rookies / deep practice-squad
    # LBs).  Live match counts are ~237 offense and ~108 IDP at
    # the April 2026 baseline.  Floors at ~80% of those match
    # counts so scraper regressions trip a warning.
    "draftSharks": 190,
    "draftSharksIdp": 85,
    # ``fantasyNavigatorSf`` / ``pfkDynasty``: floors intentionally NOT
    # set yet — same policy as the ``fantasyCalc`` note above.  Floors
    # pin at ~75-80% of the live canonical-match baseline, which does
    # not exist until a few scheduled-refresh cycles have run.  Raw-row
    # baselines at integration (2026-07-25): FN ~799 sf-dynasty rows,
    # PFK ~496 offense rows (fetcher-level floors 200 / 120 guard the
    # raw side in the meantime).  Add entries here once live canonical
    # match counts are observed.
}


_SOURCE_ROW_FLOORS_CACHE: dict[str, Any] = {"mtime": None, "value": None}


def _load_source_row_floors() -> dict[str, int]:
    """Load per-source row-count floors from config with fallback defaults."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg_path = repo_root / "config" / "weights" / "source_row_floors.json"
    current_mtime: float | None = None
    if cfg_path.exists():
        try:
            current_mtime = cfg_path.stat().st_mtime
        except OSError:
            current_mtime = None
    cached_mtime = _SOURCE_ROW_FLOORS_CACHE.get("mtime")
    cached_value = _SOURCE_ROW_FLOORS_CACHE.get("value")
    if isinstance(cached_value, dict) and cached_mtime == current_mtime:
        return dict(cached_value)
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
            floors = cfg.get("floors") if isinstance(cfg, dict) else None
            if isinstance(floors, dict):
                merged = dict(_DEFAULT_SOURCE_ROW_FLOORS)
                for key, val in floors.items():
                    try:
                        merged[str(key)] = int(val)
                    except (TypeError, ValueError):
                        continue
                _SOURCE_ROW_FLOORS_CACHE["mtime"] = current_mtime
                _SOURCE_ROW_FLOORS_CACHE["value"] = merged
                return dict(merged)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("Failed to load source_row_floors.json (%s); using defaults", exc)
    default = dict(_DEFAULT_SOURCE_ROW_FLOORS)
    _SOURCE_ROW_FLOORS_CACHE["mtime"] = current_mtime
    _SOURCE_ROW_FLOORS_CACHE["value"] = default
    return dict(default)


# ── Pick-count floor ─────────────────────────────────────────────────────
# Minimum draft-pick count on the board.  Live currently carries 126
# (4 years × multiple slots each).  Floor set to 80% baseline so an
# ingestion bug that silently drops half the picks trips an error.
_PICK_COUNT_FLOOR: int = 100

# ── Payload-size regression floor ───────────────────────────────────────
# Minimum raw-JSON byte length of the contract payload.  The April 9
# regression shipped a 770KB payload after a heavy-field pruning bug;
# the live baseline is ~4.6MB.  Floor set to 2MB (under half baseline)
# so deliberate optimizations still pass while catastrophic shrinks trip
# a warning + degraded status.
_PAYLOAD_SIZE_FLOOR_BYTES: int = 2_000_000

# ── Top-50 per-source coverage floors ────────────────────────────────────
# Embedded defaults; overridable via
# ``config/weights/top50_coverage_floors.json``.  A source that drops
# below its floor in the top-50 slice of its asset class (offense / idp)
# trips a warning and marks the build as degraded.  This catches silent
# regressions where a source still passes the row-count floor but loses
# coverage on the premium tier specifically.
_DEFAULT_TOP50_COVERAGE_FLOORS: dict[str, dict[str, int]] = {
    "offense": {
        "ktc": 48,
        "idpTradeCalc": 48,
        "dlfSf": 42,
        "dynastyNerdsSfTep": 45,
    },
    "idp": {
        "idpTradeCalc": 48,
        "dlfIdp": 38,
        # FantasyPros dynasty IDP only carries 70 combined + 30
        # extension players so its top-50 coverage is bounded by the
        # combined-board size.  Floor at 33 — DraftSharks rejoining
        # the blend nudged the top-50 IDP slice enough to shift a
        # couple of FP-not-listed players into the top 50.
        "fantasyProsIdp": 33,
    },
}


_TOP50_COVERAGE_FLOORS_CACHE: dict[str, Any] = {"mtime": None, "value": None}


def _load_top50_coverage_floors() -> dict[str, dict[str, int]]:
    """Load top-50 per-source coverage floors from config with defaults."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg_path = repo_root / "config" / "weights" / "top50_coverage_floors.json"
    current_mtime: float | None = None
    if cfg_path.exists():
        try:
            current_mtime = cfg_path.stat().st_mtime
        except OSError:
            current_mtime = None
    cached_mtime = _TOP50_COVERAGE_FLOORS_CACHE.get("mtime")
    cached_value = _TOP50_COVERAGE_FLOORS_CACHE.get("value")
    if isinstance(cached_value, dict) and cached_mtime == current_mtime:
        return {k: dict(v) for k, v in cached_value.items()}
    merged: dict[str, dict[str, int]] = {
        k: dict(v) for k, v in _DEFAULT_TOP50_COVERAGE_FLOORS.items()
    }
    if cfg_path.exists():
        try:
            with cfg_path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to load top50_coverage_floors.json (%s); using defaults",
                exc,
            )
            _TOP50_COVERAGE_FLOORS_CACHE["mtime"] = current_mtime
            _TOP50_COVERAGE_FLOORS_CACHE["value"] = merged
            return {k: dict(v) for k, v in merged.items()}
        if isinstance(cfg, dict):
            for bucket in ("offense", "idp"):
                bucket_cfg = cfg.get(bucket)
                if not isinstance(bucket_cfg, dict):
                    continue
                for src_key, val in bucket_cfg.items():
                    try:
                        merged[bucket][str(src_key)] = int(val)
                    except (TypeError, ValueError):
                        continue
    _TOP50_COVERAGE_FLOORS_CACHE["mtime"] = current_mtime
    _TOP50_COVERAGE_FLOORS_CACHE["value"] = merged
    return {k: dict(v) for k, v in merged.items()}


def assert_payload_size_floor(
    contract_payload: dict[str, Any],
    *,
    floor_bytes: int = _PAYLOAD_SIZE_FLOOR_BYTES,
) -> tuple[int, bool]:
    """Serialize ``contract_payload`` and compare length against floor.

    Returns ``(byte_length, passed)`` where ``passed`` is True when the
    serialized payload is at least ``floor_bytes``.  Side-effect free —
    callers decide whether to warn, log, or flip status.
    """
    raw = json.dumps(contract_payload, ensure_ascii=False, separators=(",", ":"))
    size = len(raw.encode("utf-8"))
    return size, size >= floor_bytes


# ── Partial-run cross-wire: tolerable partials allowlist ─────────────────
# Sub-endpoints that are known to flip to partial without impacting the
# primary ranking data.  KTC_TradeDB and KTC_WaiverDB are *sub-endpoints*
# of the KTC source: KTC itself still returns its full 500-row board; the
# partial flag refers to secondary trade-DB / waiver-DB endpoints that
# only feed retail metadata, not ranks.  Treat as warnings rather than
# errors.  Truly critical failures use the full source names (``KTC``,
# ``IDPTradeCalc``, ``DLF``, ``DynastyNerds``) which bypass the allowlist.
TOLERABLE_PARTIAL_SOURCES: frozenset[str] = frozenset(
    {
        "KTC_TradeDB",
        "KTC_WaiverDB",
    }
)

# Primary sources whose partial/failed state should flip contractHealth.
_CRITICAL_PRIMARY_SOURCES: tuple[str, ...] = (
    "KTC",
    "IDPTradeCalc",
    "DLF",
    "DynastyNerds",
)


def _build_source_timestamps() -> dict[str, dict[str, Any]]:
    """Return per-source freshness block with mtimes + staleness flags.

    Iterates every entry in :data:`_SOURCE_CSV_PATHS`, stats the CSV, and
    computes an ISO8601 mtime, an age in hours, and a ``fresh``/``stale``
    flag based on :data:`_SOURCE_MAX_AGE_HOURS`.  Missing files return
    ``None`` for mtime rather than the empty string the legacy code used,
    so downstream can tell "no data yet" from "found it, here's when".

    Freshness prefers the ``data/scrape_state/{key}_last_success``
    stamp over CSV mtime, mirroring ``server._per_source_freshness()``:
    the stamp is written on every SUCCESSFUL fetcher run regardless of
    whether the CSV content changed, while ``git checkout``/``git
    pull`` never rewrite byte-identical files — so a vendor whose
    board is static between publishes (Fitzmaurice, Yahoo Boone, FN's
    monthly snapshots) has a frozen CSV mtime that would false-flag
    ``stale`` under fetch-success budgets despite green 2h fetches
    (Codex review on PR #532).  The CSV must still exist — a stamp
    without data is reported ``missing``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    state_dir = repo_root / "data" / "scrape_state"
    now = datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for source_key, cfg in _SOURCE_CSV_PATHS.items():
        if isinstance(cfg, str):
            csv_rel = cfg
        elif isinstance(cfg, dict):
            csv_rel = str(cfg.get("path") or "")
        else:
            csv_rel = ""
        max_age = int(_SOURCE_MAX_AGE_HOURS.get(source_key, 6))
        entry: dict[str, Any] = {
            "mtime": None,
            "ageHours": None,
            "maxAgeHours": max_age,
            "staleness": "unknown",
            "path": csv_rel or None,
        }
        if csv_rel:
            csv_path = repo_root / csv_rel
            try:
                st = os.stat(csv_path)
            except (FileNotFoundError, OSError):
                entry["staleness"] = "missing"
            else:
                last_epoch = st.st_mtime
                try:
                    stamp_text = (state_dir / f"{source_key}_last_success").read_text().strip()
                    if stamp_text:
                        last_epoch = float(stamp_text)
                except (OSError, ValueError):
                    pass
                mtime_dt = datetime.fromtimestamp(last_epoch, tz=timezone.utc)
                age_hours = (now - mtime_dt).total_seconds() / 3600.0
                entry["mtime"] = mtime_dt.isoformat()
                entry["ageHours"] = round(age_hours, 3)
                entry["staleness"] = "fresh" if age_hours < max_age else "stale"
        out[source_key] = entry
    return out


# ── Ranking source registry ──────────────────────────────────────────────
# Declarative metadata describing each source that feeds the unified
# ranking.  Keeping this in one list is meant to make it trivial to add
# a new position-only IDP source (e.g. a scouted "DL top 20"): append an
# entry with scope="position_idp", position_group="DL", depth=20 and the
# translation pipeline picks it up.
#
# UNEXERCISED, and worth knowing before relying on it: no source has
# ever carried scope="position_idp", so that path has never run against
# real data.  "Picks it up automatically" describes code that exists,
# not a route anything has travelled — treat the first such registration
# as a change to be measured, not a config edit.
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
from src.canonical.idp_backbone import (  # noqa: E402
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
from src.canonical.rank_coordinates import (  # noqa: E402
    RANK_POOL_IDP,
    RANK_POOL_SHARED_MARKET,
    curve_for_pool,
    native_pool_for_source,
)

# ── Source weight policy ─────────────────────────────────────────────
# Every registered source is declared with ``weight = 1.0``.  All six
# sources (2 retail/backbone + 4 expert boards) contribute equally to
# the coverage-aware Hill-curve blend.  Earlier revisions boosted the
# four expert boards to ``weight = 3.0``, but that was a silent
# override that never surfaced in the settings page and quietly tilted
# every ranking toward expert consensus.  Keep the weights at 1.0 so
# the settings page, frontend registry, and backend all agree on a
# single canonical value.  Mirror any future change here in
# ``frontend/lib/dynasty-data.js::RANKING_SOURCES``.
_RANKING_SOURCES: list[dict[str, Any]] = [
    {
        # KeepTradeCut Superflex + TE Premium board.  KTC publishes both
        # a standard SF view and a TE++ sub-board from the same per-
        # player API payload (``superflexValues.value`` and
        # ``superflexValues.tepp`` level 2) — one scrape produces both.
        # Historically we registered both as separate blend sources,
        # which double-counted KTC's signal: for non-TE rows the two
        # values are identical, and for TE rows the TEP-correction step
        # converged them both onto the league's actual TEP anyway.
        # 2026-04-28: dropped the standard ``ktc`` blend vote and
        # promoted ``ktcSfTep`` to the canonical retail source.  The
        # standard ``ktc`` CSV still loads into ``canonicalSiteValues``
        # (free side-effect of the same scrape) so the KTC arbitrage
        # finder + per-source winner row on /trade can keep displaying
        # both values side-by-side.  Only the blend vote was removed.
        "key": "ktcSfTep",
        "display_name": "KeepTradeCut SF-TE++",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": None,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": True,
        "is_tep_premium": True,
        # Head of the ``ktc`` correlation group — see
        # ``_CORRELATION_GROUPS``.  ``fantasyNavigatorSf`` republishes
        # KTC-derived numbers, so the two are not independent votes and
        # must leave the blend together when a caller wants a board that
        # does not contain KTC.
        "correlation_group": "ktc",
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
        # IDPTC is the retail IDP authority and the backbone source.
        # The old weight=2.0 dated to when IDPTC was the SOLE IDP
        # anchor; now that DraftSharks SF+IDP and FootballGuys SF+IDP
        # are also cross-market anchors (see ``is_cross_market``), no
        # single source gets an explicit multiplier in the blend.
        # The ``weight`` field is still honoured as a user-override
        # knob on ``/settings`` but in the live blend every source
        # contributes with one equal vote.
        "weight": 1.0,
        "is_backbone": True,
        # Cross-market anchor source (2026-04-20): IDPTC prices both
        # offense and IDP on a single combined-pool scale, so its
        # per-player value is a direct cross-market signal.  Along
        # with DraftSharks (via combined rank pre-pass) and
        # FootballGuys (via the scraper's preserved combined rank),
        # IDPTC contributes to the anchor value on IDP + pick rows;
        # ``anchor_value`` = mean of every ``is_cross_market=True``
        # source's contribution.  See the blend loop in
        # ``_compute_unified_rankings`` for the exact math.
        "is_cross_market": True,
        # IDPTradeCalc is scraped with TEP=True (see Dynasty Scraper.py),
        # pulling ``value_sftep`` rather than the vanilla SF column.
        # That means the raw values are already a TE-premium board, so
        # we treat IDPTC like the other TEP-native sources (Yahoo Boone,
        # FP Fitzmaurice, DN SfTep) — only the small 1.10× nudge toward
        # the operator's TE++ baseline, never the full non-TEP 1.15×.
        "is_tep_premium": True,
    },
    {
        # DLF Dynasty Superflex rankings — the offense counterpart of
        # DLF IDP.  Curated 6-expert consensus board with explicit
        # ``Rank`` and ``Avg`` columns.  Includes rookies and picks'
        # equivalents, spans 279 players, and is scoped purely to
        # offense (QB/RB/WR/TE).
        #
        # Weight normalized to 1.0 — see the registry note at the
        # top of this list.  depth=280 still tells
        # ``_expected_sources_for_position`` not to expect this
        # source for players ranked deeper than ~350 (depth * 1.25),
        # preventing false 1-src flags on fringe offense players
        # that DLF SF was never going to list.
        "key": "dlfSf",
        "display_name": "Dynasty League Football Superflex",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 280,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        # Not a shared-market translation source — dlfSf is purely
        # offense, so its effective rank IS the offense ordinal.  No
        # IDP backbone crosswalk needed.
        #
        # DLF Superflex is a standard SF expert consensus board, not
        # TE-premium.  The raw CSV columns (Rank / Avg / Pos / Name /
        # 6 expert columns) carry no TEP indicator.  The frontend
        # ``settings.tepMultiplier`` boost applies to its blended
        # contribution.  Mirrored in frontend/lib/dynasty-data.js.
        "is_tep_premium": False,
    },
    {
        # DLF Dynasty Rookie Superflex — rookies-only offensive board
        # (QB/RB/WR/TE).  DLF expert consensus ranks the current
        # incoming class; ~50 prospects per export.  Declared as an
        # ``overall_offense`` source but with
        # ``needs_rookie_translation=True`` so the within-source rank
        # is crosswalked through a *rookie ladder* before the Hill
        # curve.  The ladder is built from KTC's current ranks on
        # offense rookie rows: ladder[k] = KTC's rank for the (k+1)th
        # rookie in KTC's order.  This means DLF rookie #1 gets the
        # Hill-value KTC would give to its own top rookie, preserving
        # DLF's ORDER while inheriting KTC's SCALE.  Pre-NFL-draft
        # prospects not in KTC fall past the ladder's tail and
        # extrapolate via the translation helper.
        #
        # depth=50 reflects the typical rookie-class size; coverage
        # weight scales contribution down so the rookie board never
        # overwhelms the veteran-rich retail/expert blend.
        "key": "dlfRookieSf",
        "display_name": "Dynasty League Football Rookie SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 50,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "needs_rookie_translation": True,
        # Rookie source BY DEFINITION contains only rookies, so
        # ``excludes_rookies=False`` is correct — but even more:
        # veteran rows will never match this source's CSV, so the
        # source stamp is effectively rookie+pick-only.  The pick
        # nudge is wired via synthetic "2026 Pick R.SS" rows that
        # the conversion step appends to the CSV so the source's
        # Hill value flows into pick rankDerivedValue directly.
        "excludes_rookies": False,
    },
    {
        # DLF (Dynasty League Football) full-board IDP rankings.  The raw
        # export (`dlf_idp.csv` → `CSVs/site_raw/dlfIdp.csv`) is
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
        # Weight normalized to 1.0 so every registered source
        # contributes equally to the blended rank.  The previous 3.0
        # boost silently elevated expert IDP boards over the retail
        # backbone without surfacing in settings; see the registry
        # note at the top of this list.
        "weight": 1.0,
        "is_backbone": False,
        "needs_shared_market_translation": True,
        "excludes_rookies": True,
        # IDP values have no TE-premium dimension — declared
        # explicitly False so the registry-completeness test can
        # enforce that every source states its TEP posture.
        "is_tep_premium": False,
    },
    {
        # DLF Dynasty Rookie IDP — rookie-only defensive board
        # (DE/DT/EDGE/LB/CB/S).  Analogous to dlfRookieSf but
        # translated against IDPTC's ladder.  depth=50 matches the
        # typical export size.
        "key": "dlfRookieIdp",
        "display_name": "Dynasty League Football Rookie IDP",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "position_group": None,
        "depth": 50,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "needs_shared_market_translation": False,
        "needs_rookie_translation": True,
        "excludes_rookies": False,
        # IDP values have no TE-premium dimension — declared
        # explicitly False so the registry-completeness test can
        # enforce that every source states its TEP posture.
        "is_tep_premium": False,
    },
    {
        # The IDP Show (Adamidp) — Substack-hosted full IDP rankings
        # board published at theidpshow.com/p/idp-dynasty-rankings.
        # Data is served from an embedded Datawrapper iframe whose
        # dataset.csv is fetched by ``scripts/fetch_idpshow.py``.
        # ~420 rows covering ED/IDL/LB/S/CB.  Unlike DLF IDP this
        # board DOES include rookie prospects (Arvell Reese, Sonny
        # Styles, etc.), so ``excludes_rookies=False``.
        #
        # Rank-only signal — the source's TRADE VALUE column is
        # draft-pick-equivalent text ("1st + 2nd", "3rd") rather
        # than a numeric scale, so we use the OVR column as the
        # rank and let the shared-market translator convert to the
        # combined-pool for Hill-curve input.
        "key": "idpShow",
        "display_name": "The IDP Show (Adamidp)",
        "column_label": "IDP Show",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "position_group": None,
        "depth": 420,
        "weight": 1.0,
        "is_backbone": False,
        "needs_shared_market_translation": True,
        "excludes_rookies": False,
        # IDP values have no TE-premium dimension — declared
        # explicitly False so the registry-completeness test can
        # enforce that every source states its TEP posture.
        "is_tep_premium": False,
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
        # Weight normalized to 1.0 — see the registry note at the
        # top of this list.  The key is namespaced ``SfTep`` so we
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
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        # Dynasty Nerds SF-TEP IS a TE-premium native board.  The URL
        # slug is /dynasty-rankings/sf-tep/ and the inline DR_DATA
        # carries the SFLEXTEP array which already bakes TE premium
        # into each player's rank.  The frontend surfaces this flag
        # as a "TEP NATIVE" badge so users know the global
        # ``settings.tepMultiplier`` boost is compensating for the
        # OTHER (non-TEP) sources in the blend, not this one.
        "is_tep_premium": True,
    },
    {
        # FantasyCalc Dynasty Superflex trade values — crowd-sourced
        # community values fetched from the public JSON API at
        # https://api.fantasycalc.com/values/current
        # (?isDynasty=true&numQbs=2&numTeams=12&ppr=1) via
        # ``scripts/fetch_fantasycalc.py``.  Same board that powers
        # https://www.fantasycalc.com/dynasty-rankings.  The API
        # returns ~450+ offensive players (QB/RB/WR/TE) plus picks;
        # the fetcher filters to offense-only and writes a
        # ``name,value,rank`` CSV (picks are tethered to rookie
        # values in a dedicated downstream phase, not via this CSV).
        #
        # Weight normalized to 1.0 — see the registry note at the top
        # of this list.  depth=450 reflects the typical offensive-only
        # count (~458 rows in the 2026-03-25 historical snapshot);
        # ``_expected_sources_for_position`` multiplies this by 1.25
        # so FantasyCalc is not expected for players ranked deeper
        # than ~562.
        #
        # FantasyCalc's crowd values are standard Superflex (numQbs=2)
        # but DO NOT bake in TE-premium pricing — there's no
        # ``teBonus`` knob on the API that meaningfully tracks our
        # TE++ league, and crowd voting on the underlying board is
        # standard SF.  Declared ``is_tep_premium=False`` so the
        # frontend ``settings.tepMultiplier`` boost applies to its
        # blended contribution like Dynasty Daddy SF or FlockFantasy.
        "key": "fantasyCalc",
        "display_name": "FantasyCalc Dynasty SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 450,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # OTC Fantasy Football Superflex trade-derived values — fetched
        # from https://otcffb.com/api/trade-values?format=sf via
        # ``scripts/fetch_otcffb.py``.  Public JSON, no auth.  ~471
        # offensive players covering QB/RB/WR/TE with a 0-100 value
        # scale derived from OTCFFB's tracked league trades.
        #
        # Conservative starting weight of 1.0 matches the other crowd-
        # sourced trade boards (FantasyCalc, Dynasty Daddy).  depth=460
        # reflects the typical offensive count just under playerCount.
        # OTCFFB is standard Superflex — no TE premium baked in — so
        # the frontend ``settings.tepMultiplier`` boost applies to its
        # blended contribution.
        "key": "otcffbSf",
        "display_name": "OTC Fantasy Football SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 460,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # Fantasy Navigator superflex dynasty board — public JSON API
        # (fantasy-navigator-latest.onrender.com/ranks?platform=sf)
        # fetched by ``scripts/fetch_fantasynavigator.py``.  ~800
        # offensive rows after filtering to sf_value + dynasty.
        #
        # CORRELATION CAVEAT: FN's values are KTC-derived (every row
        # carries a ``ktc_player_id`` and the site credits KeepTradeCut
        # as a data source), so this vote is partially correlated with
        # ``ktcSfTep``.  The count-aware blend and per-player Hampel
        # filter tolerate correlated sources; documented here so nobody
        # reads FN agreement with KTC as independent confirmation.
        #
        # Standard SF scoring — FN does NOT bake in TE-premium pricing
        # (user-confirmed 2026-07-25), so ``is_tep_premium=False`` and
        # the frontend ``settings.tepMultiplier`` boost applies to its
        # blended contribution.  depth=460 ≈ the live CANONICAL-MATCH
        # count (468 of 799 raw rows at integration — FN's deep rows
        # are prospects/camp bodies outside the Sleeper pool);
        # ``_expected_sources_for_position`` multiplies by 1.25.
        # Pinning depth to raw rows (780) would stamp "expected but
        # did not match" on ~500 rows — the item-10 noise class.
        "key": "fantasyNavigatorSf",
        "display_name": "Fantasy Navigator SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 460,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
        # Member of the ``ktc`` correlation group.  The CORRELATION
        # CAVEAT above is no longer only a comment: it is now machine
        # readable, so a caller asking for a KTC-free board actually
        # gets one.  Measured 2026-08-04 on the live payload: excluding
        # ``ktcSfTep`` alone still left 440 rows carrying an FN vote.
        "correlation_group": "ktc",
    },
    {
        # Play for Keeps Dynasty master board — PFK's hand-maintained
        # dynasty rankings from their public Supabase table
        # (``pfk_dynasty_rankings``) via ``scripts/fetch_pfk.py``.
        # ~496 offensive players (picks dropped by the fetcher).  Rows
        # carry ``sleeper_player_id``, giving ID-grade identity in the
        # CSV for future ID-based matching.
        #
        # A genuinely independent human signal — PFK's own analysts'
        # board, distinct from their KTC mirror table.  Standard SF
        # scoring — PFK does NOT account for TE premium (user-confirmed
        # 2026-07-25), so ``is_tep_premium=False`` and the frontend
        # ``settings.tepMultiplier`` boost applies.  depth=460 ≈ the
        # live canonical-match count (472 of 496 offensive rows at
        # integration).
        "key": "pfkDynasty",
        "display_name": "Play for Keeps Dynasty",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 460,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # Dynasty Daddy Superflex trade values — crowd-sourced community
        # values fetched from the public JSON API at
        # https://dynasty-daddy.com/api/v1/player/all/today?market=14
        # via ``scripts/fetch_dynasty_daddy.py``.  Market 14 is the SF/
        # dynasty format.  The API returns ~641 players; after filtering
        # to offensive positions (QB/RB/WR/TE) ~400+ remain.
        #
        # Weight normalized to 1.0 — see the registry note at the top
        # of this list.  depth=320 reflects the typical offensive-only
        # count (~323 players with positive sf_trade_value);
        # ``_expected_sources_for_position`` multiplies this by 1.25 so
        # DD SF is not expected for players ranked deeper than ~400.
        #
        # Dynasty Daddy's SF trade values are standard SF scoring — no
        # TE premium baked in.  The frontend ``settings.tepMultiplier``
        # boost applies to its blended contribution.
        "key": "dynastyDaddySf",
        "display_name": "Dynasty Daddy Superflex",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 320,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # FantasyPros Dynasty Superflex rankings — offense expert
        # consensus scraped from
        # https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php
        # via ``scripts/fetch_fantasypros_offense.py``.  The page
        # inlines an ``ecrData = {...}`` JS constant containing a flat
        # ``players`` array with consensus ECR ranks covering QB/RB/WR/TE.
        # No Playwright required — a plain ``requests.get`` with a
        # browser UA returns the full payload.
        #
        # Weight normalized to 1.0 — see the registry note at the top
        # of this list.  depth=250 reflects the typical board size
        # (~250-300 offensive players); ``_expected_sources_for_position``
        # multiplies this by 1.25 so FP SF is not expected for players
        # ranked deeper than ~312.
        #
        # FantasyPros' dynasty superflex board is a standard SF
        # consensus — no TE premium baked in.  The frontend
        # ``settings.tepMultiplier`` boost applies to its blended
        # contribution.
        "key": "fantasyProsSf",
        "display_name": "FantasyPros Dynasty Superflex",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 250,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
    },
    {
        # FantasyPros Dynasty IDP expert consensus.  Scraped from
        # https://www.fantasypros.com/nfl/rankings/dynasty-idp.php
        # (combined IDP board = authoritative overall ordering) and
        # extended via three individual family pages
        # (dynasty-dl / dynasty-lb / dynasty-db) through monotone
        # piecewise-linear anchor curves fit on the overlap.  See
        # ``scripts/fetch_fantasypros_idp.py`` for the full derivation.
        #
        # Weight normalized to 1.0 — see the registry note at the
        # top of this list.  ``needs_shared_market_translation=True``
        # still applies: IDP ranks are translated through the
        # backbone ladder before feeding the Hill curve.
        # FantasyPros' dynasty IDP board is smaller than DLF's
        # (~100 players vs 185) so ``depth=100`` tells
        # ``_expected_sources_for_position`` not to expect this
        # source for players ranked deeper than ~125 (depth * 1.25).
        "key": "fantasyProsIdp",
        "display_name": "FantasyPros Dynasty IDP",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "position_group": None,
        "depth": 100,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "needs_shared_market_translation": True,
        # The FantasyPros dynasty IDP board is a curated veteran
        # list — like DLF IDP, it does not list first-year college
        # prospects (Caleb Downs, Sonny Styles, Arvell Reese, etc.).
        # Declare ``excludes_rookies`` so
        # ``_expected_sources_for_position`` stops counting FP as an
        # expected source for rookies and the structural-1-src
        # detection still fires for DLF+FP-excluded rookies.
        "excludes_rookies": True,
        # IDP values have no TE-premium dimension — declared
        # explicitly False so the registry-completeness test can
        # enforce that every source states its TEP posture.
        "is_tep_premium": False,
    },
    {
        # FantasyPros / Pat Fitzmaurice Dynasty Trade Value Chart —
        # monthly offense board covering QB/RB/WR/TE.  Fetched by
        # ``scripts/fetch_fantasypros_fitzmaurice.py`` which:
        #   1. resolves the month-rotating article URL (falls back
        #      3 months if the current-month update isn't published yet),
        #   2. parses the four embedded Datawrapper iframes for
        #      QB / RB / WR / TE,
        #   3. fetches each chart's dataset.csv and picks the league-
        #      appropriate value column: ``SF Value`` for QB (Superflex),
        #      ``Trade Value`` for RB/WR, ``TEP Value`` for TE (TE-Premium).
        # Result: ~300 combined rows with a top-of-pool value of ~101
        # (SF-adjusted QB).  Signal=value so the blend's value-direct
        # branch scales Fitzmaurice's top to 9999 and every other row
        # linearly.  Cross-position separation is preserved (e.g. top
        # QB at SF value 101 beats top WR at 88, scaling to 9999 vs
        # 8712 on the 9999 scale).
        #
        # depth=350 reflects the published row count; coverage_weight
        # keeps full weight for rows within depth and degrades past.
        # Like yahooBoone, this is a TEP-native source: it applies the
        # TE premium directly via the TEP Value column, so the global
        # TEP multiplier MUST NOT compound.
        "key": "fantasyProsFitzmaurice",
        "display_name": "FantasyPros / Pat Fitzmaurice SF-TEP",
        "column_label": "Fitzmaurice",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 350,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": True,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # Flock Fantasy Dynasty Superflex rankings — expert consensus
        # from https://flockfantasy.com.  Multi-expert averaged ranks.
        # Standard SF — no TE premium baked in.  The frontend
        # `settings.tepMultiplier` boost applies to its blended
        # contribution for TE-position players.
        "key": "flockFantasySf",
        "display_name": "Flock Fantasy Superflex",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 370,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # Flock Fantasy Dynasty Superflex Rookie/Prospect rankings —
        # multi-expert averaged ranks of the current incoming rookie
        # class only (~95 QB/RB/WR/TE prospects).  Fetched from the
        # PROSPECTS_SF endpoint by ``scripts/fetch_flock_fantasy_rookies.py``.
        # Same shape and translation behaviour as ``dlfRookieSf``: the
        # within-class rank is crosswalked through KTC's offense rookie
        # ladder so Flock's #1 rookie inherits KTC's scale-for-top-rookie
        # rather than being mapped to overall #1 = 9999.
        #
        # depth=50 mirrors ``dlfRookieSf``; coverage weight scales the
        # rookie board's contribution down so it never overwhelms the
        # veteran-rich blend.  Pick nudging is intentionally NOT wired
        # for this source — ``dlfRookieSf`` already stamps synthetic
        # "2026 Pick R.SS" rows to drive pick values, and the cross-
        # rookie pick tethering pass (Phase 11) blends Flock's rookie
        # values into picks via the merged rookie pool.
        "key": "flockFantasySfRookies",
        "display_name": "Flock Fantasy Rookie SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 50,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "needs_rookie_translation": True,
        "excludes_rookies": False,
    },
    {
        # Yahoo / Justin Boone Dynasty Trade Value Charts — monthly
        # offense board covering QB/RB/WR/TE.  Fetched by
        # ``scripts/fetch_yahoo_boone.py``, which hits a seed URL per
        # position and follows Yahoo's 308 redirects to the newest live
        # article in each series.  The scraper pulls the 2QB column for
        # QBs and the TE-premium column for TEs, which matches our
        # Superflex + TEP league scoring — so the source is declared
        # ``is_tep_premium=True``.  Roughly 500 combined rows.
        #
        # Value signal (2026-04-21): the scraper writes Boone's
        # published trade value in ``boone_value`` (0-~141 scale) plus a
        # cross-position competition rank in ``rank``.  The blend reads
        # ``boone_value`` via the value-direct branch, scaling linearly
        # so Boone's top player contributes 9999 — preserving his
        # published value structure (e.g. how much further QBs lead WRs)
        # rather than collapsing to rank-only ordinal info.  The UI
        # continues to render Boone's published rank via
        # ``sourceOriginalRanks.yahooBoone`` (the value-signal CSV
        # loader now also picks up the ``rank`` column so this audit
        # stamp survives the switch).
        #
        # depth=500 mirrors the live row count; ``_expected_sources_for_position``
        # multiplies this by 1.25 so YAHOO_BOONE is not expected for
        # players ranked deeper than ~625.
        "key": "yahooBoone",
        "display_name": "Yahoo / Justin Boone SF-TEP",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        "depth": 500,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": True,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # DraftSharks offense dynasty board (QB/RB/WR/TE).  The
        # scraper splits DS's single offense-combined DOM by
        # position family, so this source is the SF slice of the
        # ~874-row universe.  461 rows at the April 2026 baseline
        # (QB=39, RB=73, WR=103, TE=35 visible + hidden depth
        # prospects below the default DS position-filter cutoff).
        # Value signal off the ``3D Value +`` column; the blend
        # normalises via Hill curve over within-source rank so the
        # 0-100 absolute scale is irrelevant.  DraftSharks IS scraped
        # from the TE-PREMIUM superflex board —
        # ``scripts/fetch_draftsharks.py`` ``RANKINGS_URL`` =
        # ``https://www.draftsharks.com/dynasty-rankings/te-premium-superflex``,
        # read under the TE++ league's ``3D Value +`` (and the legacy
        # ``Dynasty Scraper.py`` header agrees: "DraftSharks — TEP
        # url").  Its raw values therefore ALREADY bake in TE premium,
        # so it is TEP-native like KTC SF-TE++ / DN SF-TEP / Yahoo
        # Boone / FP Fitzmaurice / IDPTC: declared
        # ``is_tep_premium=True`` so TE rows get only the small 1.10×
        # native nudge, never the 1.15× non-TEP boost.  (Before
        # 2026-05-16 this was mis-flagged False, double-counting TE
        # premium for DS — its already-TEP TE values got the larger
        # non-TEP multiplier — which inflated every TE's DS
        # contribution and pushed top TEs like Brock Bowers too high.)
        "key": "draftSharks",
        "display_name": "Draft Sharks Dynasty",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "extra_scopes": [],
        "position_group": None,
        "depth": 500,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": True,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
        # DraftSharks SF and IDP are split across two CSVs but share
        # one cross-market value scale — DS's top offense player is
        # at 3D Value+ 100 while the top IDP is 44, representing DS's
        # own ~56% offense-vs-IDP premium.  ``ds_combined_rank_partner``
        # tells the blend to merge this source's raw values with its
        # partner's for ranking purposes and route both through the
        # GLOBAL Hill master.  This preserves DS's native cross-market
        # ratio, which would otherwise be erased by per-CSV
        # normalization, and handles DS's negative values
        # (roughly half the CSV) by sorting them to the tail of the
        # combined ladder where the Hill tail produces low values.
        "ds_combined_rank_partner": "draftSharksIdp",
        # Contributes to the multi-source cross-market anchor
        # (alongside IDPTC and FootballGuys).  See IDPTC entry above
        # for the blend math.
        "is_cross_market": True,
    },
    {
        # DraftSharks IDP dynasty board (DL/LB/DB).  Mirror of the
        # ``draftSharks`` offense entry — same scraper scrapes a
        # single page and writes two CSVs; the IDP CSV carries
        # every DL/LB/DB with their cross-universe ``3D Value +``
        # (e.g. Carson Schwesinger at value 44 as IDP rank 1, NOT
        # the IDP-only-page rescaled 81).  389 rows at the April
        # 2026 baseline.  depth=400 because IDP depth in the DS
        # export is smaller than offense.
        "key": "draftSharksIdp",
        "display_name": "Draft Sharks IDP Dynasty",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "extra_scopes": [],
        "position_group": None,
        "depth": 400,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
        # See the ``draftSharks`` entry above for the combined-rank
        # rationale — both sources merge their raw values into a
        # single cross-market rank list that feeds the GLOBAL Hill
        # master.
        "ds_combined_rank_partner": "draftSharks",
        "is_cross_market": True,
    },
]


# ── Derived registry field: is_rank_signal ──────────────────────────────
# Whether a source's vote travels the rank → percentile → Hill path
# (vs the value-direct path).  Derived from the SAME ``signal`` field
# ``_SOURCE_CSV_PATHS`` declares so the two can never drift — before
# this (2026-07-25 calculation audit, F-8) the registry never set the
# field, ``get_ranking_source_registry`` exported ``isRankSignal:
# false`` for every source, and the frontend hand-maintained its own
# copy (which was wrong for fantasyCalc/otcffbSf until PR #530).  The
# parity check now compares the field, so a frontend mismatch fails
# ``tests/api/test_source_registry_parity.py`` at PR time.
for _src in _RANKING_SOURCES:
    _cfg = _SOURCE_CSV_PATHS.get(str(_src.get("key") or ""))
    if isinstance(_cfg, dict):
        _signal = str(_cfg.get("signal") or "value").lower()
    else:
        _signal = "value"
    _src["is_rank_signal"] = _signal == "rank"
del _src, _cfg, _signal


def rank_signal_source_keys() -> frozenset[str]:
    """Source keys whose ``canonicalSiteValues`` slot holds a SYNTHETIC
    RANK ENCODING (``999900 − rank×100`` bookkeeping numbers), NOT a
    value.

    ⚠ Any consumer doing arithmetic over ``canonicalSiteValues`` MUST
    either skip these keys or read ``sourceRankMeta[key]
    .valueContribution`` instead — mixing the six-digit encodings with
    native 0-9999 values has produced two real bugs (trade dispersion
    CV; rankings copy/export — both fixed in PR #530).  See the
    2026-07-25 calculation audit, finding F-3.
    """
    return frozenset(str(s.get("key") or "") for s in _RANKING_SOURCES if s.get("is_rank_signal"))


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
    "dani dennis sutton": "rookie_exclusion:dlfIdp — DLF excludes rookies",
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
    # ── IDP: FantasyPros-IDP-only (not listed by idpTradeCalc or DLF IDP) ──
    # FantasyPros' curated dynasty IDP board includes several
    # role/depth players that neither IDPTradeCalc nor DLF IDP
    # currently rank.  They land inside the top-400 unified board
    # via FP's combined-page rank alone.
    "jack gibbens": "source_gap:idpTradeCalc+dlfIdp — LB only ranked by FantasyPros dynasty IDP",
    "malachi moore": "source_gap:idpTradeCalc+dlfIdp — CB only ranked by FantasyPros dynasty IDP",
    # ── Offense: FantasyPros-SF-only (not listed by other offense sources) ──
    # Deep-board prospects that FantasyPros dynasty superflex ranks but
    # neither KTC, IDPTradeCalc, DLF SF, nor Dynasty Nerds carry.
    "brenen thompson": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds — deep WR only ranked by FantasyPros dynasty SF",
    "eric mcalister": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds — deep WR only ranked by FantasyPros dynasty SF",
    "roman hemby": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds — deep RB only ranked by FantasyPros dynasty SF",
    # ── Offense: Flock-Fantasy-SF-only (not listed by other offense sources) ──
    # Deep-board veterans that Flock Fantasy's expert consensus ranks but
    # no other source currently carries.
    "adam thielen": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+fantasyPros — veteran WR only ranked by Flock Fantasy SF",
    "zonovan knight": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+fantasyPros — veteran RB only ranked by Flock Fantasy SF",
    "riley nowakowski": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+flock — deep TE only ranked by FantasyPros SF",
    "rj maryland": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+flock — deep TE only ranked by FantasyPros SF",
    # ── IDP: FootballGuys-IDP-only (not listed by other IDP sources) ──
    # Veteran / free-agent LBs that FootballGuys' 3-expert IDP board
    # ranks as deep dynasty holds even though IDPTradeCalc and the
    # other IDP boards have dropped them.  Genuine source gaps.
    "lavonte david": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp — 36yo FA veteran LB only ranked by FootballGuys IDP",
    "jordan davis": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp — DL only ranked by FootballGuys IDP",
    "marlon humphrey": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp — DB veteran only ranked by FootballGuys IDP",
    "mike jackson": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp — DB veteran only ranked by FootballGuys IDP",
    # ── IDP: IDPTradeCalc-only (not listed by other IDP sources) ──
    # Depth IDP players that only IDPTradeCalc's combined pool lists;
    # DLF / FP / FBG expert boards haven't added them (yet).  After
    # the 2026 IDP Hill refit to IDPTC's curve, several of these
    # elevated into the top 400.
    "ashton gillotte": "source_gap:dlfIdp+fantasyProsIdp+footballGuysIdp — DL only ranked by IDPTradeCalc",
    "christian harris": "source_gap:dlfIdp+fantasyProsIdp+footballGuysIdp — LB only ranked by IDPTradeCalc",
    "josh newton": "source_gap:dlfIdp+fantasyProsIdp+footballGuysIdp — DB only ranked by IDPTradeCalc",
    "noah sewell": "source_gap:dlfIdp+fantasyProsIdp+footballGuysIdp — LB only ranked by IDPTradeCalc",
    # ── IDP: DLF-Rookie-IDP-only (rookie prospects only in DLF rookie board) ──
    # Current-class IDP rookies that only DLF Rookie IDP has
    # evaluated.  IDPTC and FBG haven't added them yet.
    "aj haulcy": "rookie_source_gap:idpTradeCalc+footballGuysIdp — 2026 DB rookie only ranked by DLF Rookie IDP",
    "shavon revel": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp+footballGuysIdp — 2026 DB rookie only ranked by DraftSharks",
    "kamari ramsey": "rookie_source_gap:idpTradeCalc+draftSharksIdp+footballGuysIdp — 2026 DB rookie only ranked by DLF Rookie IDP",
    # ── Deep-board FootballGuys-only coverage (2026-04-20 scraper
    # upgrade).  FBG's combined cross-market ordering pulled these
    # deep-roster DBs / veteran DL / fringe RBs+WRs into the top-400
    # board; they're genuine FBG-only picks that every other source
    # either ranks outside its published depth or has dropped. ──
    "dane belton": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — deep veteran DB only ranked by FootballGuys",
    "daron bland": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran CB only ranked by FootballGuys IDP",
    "dee alford": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — deep nickel CB only ranked by FootballGuys IDP",
    "emmanuel henderson": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+fantasyPros+flock — deep WR only ranked by FootballGuys SF",
    "isaiah pola mao": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran safety only ranked by FootballGuys IDP",
    "jadeveon clowney": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran DL only ranked by FootballGuys IDP",
    "jamel dean": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran CB only ranked by FootballGuys IDP",
    "jaylen watson": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran CB only ranked by FootballGuys IDP",
    "kentrel bullock": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds — deep RB only ranked by FootballGuys SF",
    "nahshon wright": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — deep CB only ranked by FootballGuys IDP",
    "rahsul faison": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds+fantasyPros+flock — deep RB only ranked by FootballGuys SF",
    "upton stout": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — deep CB only ranked by FootballGuys IDP",
    "zavion thomas": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerds — deep WR only ranked by FootballGuys SF",
    "zyon mccollum": "source_gap:idpTradeCalc+draftSharksIdp+dlfIdp — veteran CB only ranked by FootballGuys IDP",
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
    percentile_spread: float | None = None,
) -> tuple[str, str]:
    """Return (confidenceBucket, confidenceLabel) for a ranked player.

    When ``percentile_spread`` is supplied (the normal path via
    :func:`_compute_unified_rankings`), buckets are decided off the
    percentile signal so IDP players with small source pools are
    judged on the same agreement scale as offense players with
    large pools.  Falls back to the legacy absolute-ordinal spread
    for callers that only have ``source_rank_spread`` handy.

    See threshold constants above for the decision rules.
    """
    if source_count >= 2:
        if percentile_spread is not None:
            if percentile_spread <= _CONFIDENCE_PERCENTILE_HIGH:
                return "high", "High — multi-source, tight agreement"
            if percentile_spread <= _CONFIDENCE_PERCENTILE_MEDIUM:
                return "medium", "Medium — multi-source, moderate spread"
        elif source_rank_spread is not None:
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
    disagreement_allowance: float = 0.0,
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
    # raw rank divided by that source's pool size, trimmed of the
    # single most extreme source per side at 5+ sources).  Fires when
    # spread > 0.20 (sources place the player in tiers more than 20
    # percentile points apart).
    #
    # Legacy callers that pass only ``source_ranks`` without the
    # percentile signal (older tests, third-party callers) still get
    # the old absolute-rank rule for backwards compatibility: spread
    # of more than ``_SUSPICIOUS_DISAGREEMENT_THRESHOLD`` ordinal
    # ranks across at least two contributing sources.
    if percentile_spread is not None:
        if percentile_spread > _SUSPICIOUS_PCT_BASE_THRESHOLD + disagreement_allowance:
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


def _compute_value_based_tier_ids(
    tiered_rows: list[dict[str, Any]],
) -> list[int]:
    """Return gap-based tier IDs aligned with ``tiered_rows``.

    Runs the canonical engine's ``detect_tiers`` (rolling-median gap
    normalization, see ``src/canonical/player_valuation.py``) over the
    compacted ``rankDerivedValue`` series.  Tier 1 is the best (top of
    board); tier IDs increase at each natural value cliff detected by
    the rolling-median gap analyzer.

    ``detect_tiers`` expects an ascending series whose adjacent
    positive gaps correspond to "moving away from the best."  Values
    are descending (best first), so we feed ``-value`` as the series;
    gaps then come out as positive value drops from row i to row i+1,
    which is exactly what the gap detector is designed for.

    No cap is applied — every mathematically-detected tier flows
    through verbatim, since the frontend renders them as generic
    "Tier N" labels rather than a fixed vocabulary.
    """
    if not tiered_rows:
        return []

    from src.canonical.player_valuation import detect_tiers  # noqa: PLC0415

    series = [-float(r.get("rankDerivedValue") or 0) for r in tiered_rows]
    player_ids = [str(r.get("canonicalName") or "") for r in tiered_rows]
    tier_ids, _gaps, _scores, _boundaries = detect_tiers(series, player_ids)
    return tier_ids


def _tier_id_from_rank(rank: int) -> int:
    """Return a numeric tier ID (1-10) from an overall rank.

    Boundaries mirror the frontend's ``rankBasedTierId()`` in
    ``frontend/lib/rankings-helpers.js``.  Used as the Phase 4 initial
    stamp and as the frontend-fallback mirror; the authoritative tier
    assignment for ranked rows comes from
    ``_compute_value_based_tier_ids`` (gap-based detection) in the
    Phase 5 compact pass, which overwrites this value before the
    contract is returned.
    """
    if rank <= 12:
        return 1
    if rank <= 36:
        return 2
    if rank <= 72:
        return 3
    if rank <= 120:
        return 4
    if rank <= 200:
        return 5
    if rank <= 350:
        return 6
    if rank <= 500:
        return 7
    if rank <= 650:
        return 8
    if rank <= 800:
        return 9
    return 10


def compact_ranks_and_tiers(
    rows: list[dict[str, Any]],
    *,
    anchor_year: int,
    copy_rows: bool = False,
) -> list[dict[str, Any]]:
    """Assign contiguous ranks + gap-based tiers from ``rankDerivedValue``.

    **The one ranker.** Extracted from the Phase 5 compact pass so the
    league-adjusted overlay can re-rank an adjusted board without
    reimplementing it.  A second ranker is exactly what the
    "no secondary ranker anywhere in the stack" rule exists to prevent —
    two implementations drift, and the one that drifts is the one nobody
    is looking at.

    Sorts by ``rankDerivedValue`` descending with the prior
    ``canonicalConsensusRank`` as tiebreaker, so rows whose values were
    not mutated keep their existing relative order.

    Current-year slot picks (e.g. "2026 Pick 1.06") are deliberately
    skipped: they carry a real value but must NOT consume a rank slot,
    because they are a proxy for the corresponding rookie and would
    otherwise push every player below them down one. Their rank and tier
    are cleared; the row itself stays on the board. Tier-generic picks
    ("2026 Early 1st") take ordinary slots.

    Args:
        rows: every candidate row. Only rows with a truthy
            ``canonicalConsensusRank`` are considered — that set is
            already the contiguous 1..N board, so a permutation of it is
            automatically unique and contiguous.
        anchor_year: current rookie draft year, for the slot-pick skip.
        copy_rows: shallow-copy before mutating. **The overlay path must
            pass True.** ``latest_contract_data`` is a shared module
            global; mutating its rows to build one league's overlay would
            permanently overwrite the board every other request reads.

    Returns the ranked, compacted rows in rank order — i.e. exactly the
    rows that received a tier, with anchor slot picks excluded.
    """
    candidates = [r for r in rows if r.get("canonicalConsensusRank")]
    if copy_rows:
        candidates = [dict(r) for r in candidates]

    ranked_rows = sorted(
        candidates,
        key=lambda r: (
            -int(r.get("rankDerivedValue") or 0),
            int(r["canonicalConsensusRank"]),
        ),
    )

    tiered_rows: list[dict[str, Any]] = []
    new_rank = 0
    for r in ranked_rows:
        is_anchor_slot_pick = False
        if r.get("assetClass") == "pick":
            parsed = _parse_pick_slot(r.get("canonicalName") or "")
            if parsed is not None and parsed[0] == anchor_year:
                is_anchor_slot_pick = True
        if is_anchor_slot_pick:
            r["canonicalConsensusRank"] = None
            r["canonicalTierId"] = None
            continue
        new_rank += 1
        if r.get("canonicalConsensusRank") != new_rank:
            r["canonicalConsensusRank"] = new_rank
        tiered_rows.append(r)

    # Gap-based tier detection on the blended value series.  Tiers land
    # where the per-player value gap is unusually large relative to the
    # local rolling-median gap: a 400-point drop from rank 12->13 is a
    # boundary; a 3-point drop from 312->313 is not.
    for r, tier_id in zip(tiered_rows, _compute_value_based_tier_ids(tiered_rows)):
        r["canonicalTierId"] = tier_id

    return tiered_rows


def _retail_source_keys() -> frozenset[str]:
    """Return the set of ranking source keys marked `is_retail` in the registry.

    Derived from `_RANKING_SOURCES` on every call so tests (or future
    config reloads) that mutate the registry see updated membership
    without a module reimport.
    """
    return frozenset(s["key"] for s in _RANKING_SOURCES if s.get("is_retail"))


# ── Public source registry surface ──────────────────────────────────────
# These helpers expose the canonical ranking-source registry to
# external callers (server.py, tests, scripts) so they never have to
# reach into the private ``_RANKING_SOURCES`` list or duplicate its
# shape.  The registry is the single source of truth for source
# metadata (weight, scope, depth, retail/backbone flags, display
# labels); anywhere else that needs that data should route through
# ``get_ranking_source_registry()``.


def get_ranking_source_registry() -> list[dict[str, Any]]:
    """Return a deep copy of the canonical ranking source registry.

    Shape is a list of dicts mirroring ``_RANKING_SOURCES`` with
    camelCase field names matching the frontend JS registry in
    ``frontend/lib/dynasty-data.js``.  Callers should treat the
    returned structure as read-only — it's a deep copy of the
    authoritative registry.  Mirrors the canonical frontend registry
    in ``frontend/lib/dynasty-data.js::RANKING_SOURCES`` —
    ``assert_ranking_source_registry_parity()`` keeps the two in
    lockstep.
    """
    out: list[dict[str, Any]] = []
    for src in _RANKING_SOURCES:
        entry: dict[str, Any] = {
            "key": str(src.get("key") or ""),
            "displayName": str(src.get("display_name") or ""),
            "columnLabel": str(src.get("column_label") or src.get("display_name") or ""),
            "scope": str(src.get("scope") or ""),
            "extraScopes": list(src.get("extra_scopes") or []),
            "positionGroup": src.get("position_group"),
            "depth": src.get("depth"),
            "weight": float(src.get("weight") or 0.0),
            "isBackbone": bool(src.get("is_backbone")),
            "isRetail": bool(src.get("is_retail")),
            "isTepPremium": bool(src.get("is_tep_premium")),
            "isRankSignal": bool(src.get("is_rank_signal")),
            "needsSharedMarketTranslation": bool(src.get("needs_shared_market_translation")),
            "excludesRookies": bool(src.get("excludes_rookies")),
            # Undeclared groups resolve to the source's own key, so the
            # field is never null and consumers never have to encode the
            # "no group means independent" rule themselves.
            "correlationGroup": str(src.get("correlation_group") or src.get("key") or ""),
        }
        out.append(entry)
    return out


def get_ranking_source_keys() -> list[str]:
    """Return the ordered list of registered ranking source keys."""
    return [str(s.get("key") or "") for s in _RANKING_SOURCES]


# ── Correlation groups ──────────────────────────────────────────────────
# Two sources are in the same correlation group when their votes are NOT
# independent — one republishes, mirrors, or is derived from the other.
# A source with no declared group is its own group of one.
#
# This exists because "number of agreeing sources" is the blend's main
# confidence signal, and a derived source inflates that count without
# adding evidence.  The blend itself tolerates the correlation (the
# count-aware aggregation plus the per-player Hampel filter are robust to
# it), so the default board is unchanged and this metadata is inert
# there.  What it enables is the one question the blend cannot answer:
# "what is this player worth according to sources that are independent of
# X?" — which is precisely the question a buy/sell signal comparing our
# board against market source X has to ask, or it is comparing X to
# itself.  See ``src/consensus_edge/fair_value.py``.
#
# Declared groups today:
#   ktc — ``ktcSfTep`` (the board itself) + ``fantasyNavigatorSf``
#         (every FN row carries a ``ktc_player_id`` and the site credits
#         KeepTradeCut as a data source).


def correlation_group_for(key: str) -> str:
    """Return the correlation-group id for ``key``.

    Sources without a declared group are independent, so they get a
    singleton group named after themselves.  That makes the "expand a
    set of keys to everything correlated with it" operation total — no
    caller has to special-case the undeclared majority.
    """
    for src in _RANKING_SOURCES:
        if str(src.get("key") or "") == key:
            return str(src.get("correlation_group") or key)
    return key


def expand_correlation_groups(keys: Iterable[str]) -> set[str]:
    """Expand ``keys`` to every registered source correlated with them.

    ``expand_correlation_groups(["ktcSfTep"])`` returns
    ``{"ktcSfTep", "fantasyNavigatorSf"}``.  Unknown keys pass through
    unchanged rather than raising: a caller naming a source that has
    since been retired should get a board without it, not an exception.
    """
    wanted = {str(k) for k in keys if str(k)}
    groups = {correlation_group_for(k) for k in wanted}
    out = set(wanted)
    for src in _RANKING_SOURCES:
        key = str(src.get("key") or "")
        if str(src.get("correlation_group") or key) in groups:
            out.add(key)
    return out


# ── Scale dependencies ───────────────────────────────────────────────
# Some sources do not merely CONTRIBUTE a vote — they define the scale
# other votes are expressed in.  Removing one of those does not shrink
# the evidence behind a value, it changes what the number means, and the
# result still looks like an ordinary board.
#
# Two such dependencies exist today, and both are declarative rather
# than inferred, so this list is the single place they are written down:
#
#   * The IDP shared-market crosswalk.  Sources flagged
#     ``needs_shared_market_translation`` — today ``dlfIdp``, ``idpShow``
#     and ``fantasyProsIdp`` — rank players within the IDP class only.
#     The backbone's shared-market ladder crosswalks that within-class
#     ordinal into the combined offense+IDP rank space.  With no backbone
#     the ladder is empty and ``translate_position_rank`` returns the raw
#     rank as ``TRANSLATION_FALLBACK``, so IDP #1 votes as if he were
#     asset #1.
#   * The rookie ladders.  ``needs_rookie_translation`` sources rank
#     within the rookie class; the ladder crosswalks rookie #1 into the
#     combined rank the reference source gives ITS #1 rookie.  With no
#     reference the pipeline falls back to the untranslated rank, so
#     rookie #1 is scored as asset #1.
#
# CORRECTION (2026-08-04).  This block used to name ``position_idp``
# sources ranking within DL / LB / DB as the first mechanism.  That is a
# dead branch: NO registered source carries the ``position_idp`` scope,
# and a census of every ``sourceRankMeta`` stamp across the 973-row live
# board returns ``overall_offense: 5772, overall_idp: 965`` and zero
# ``position_idp``.  The per-position ladders are still built at
# ``_compute_unified_rankings`` and never read.  The measured symptom was
# always real; the explanation named the wrong crosswalk, and it had been
# copied into five other files.
#
# Both fallbacks are correct for the default board, where an absent
# source is one we never scraped.  They are wrong for a board built by
# deliberately excluding a source (``consensus_edge.fair_value``), which
# is why that caller has to be able to ask this question structurally
# instead of discovering it as a wrong number.
ROOKIE_LADDER_PAIRS: tuple[tuple[str, str, set[str]], ...] = (
    ("dlfRookieSf", "ktcSfTep", _OFFENSE_POSITIONS),
    ("dlfRookieIdp", "idpTradeCalc", _IDP_POSITIONS),
    ("flockFantasySfRookies", "ktcSfTep", _OFFENSE_POSITIONS),
)

SCALE_LOST_IDP_BACKBONE = "idp_backbone_excluded"
SCALE_LOST_ROOKIE_LADDER = "rookie_ladder_reference_excluded"


def scale_integrity_lost(excluded_keys: Iterable[str]) -> dict[str, dict[str, str]]:
    """Which rows lose their VALUE SCALE if ``excluded_keys`` leave the blend.

    This is a different question from correlation leakage.  Correlation
    asks "does the excluded source's opinion still reach the result?";
    this asks "is the result still denominated in the same units?".  A
    board can be perfectly free of a source's influence and still be
    unusable because that source was what made the numbers comparable.

    ``excluded_keys`` is expanded through the correlation groups first,
    matching what :func:`expand_correlation_groups` does for the board
    build itself, so a caller cannot pass one and check the other.

    Returns::

        {
          "assetClasses": {"idp": SCALE_LOST_IDP_BACKBONE},
          "sources":      {"dlfRookieSf": SCALE_LOST_ROOKIE_LADDER, ...},
        }

    ``assetClasses`` keys are ``assetClass`` values as stamped on
    contract rows.  ``sources`` names ranking sources whose vote is on a
    broken scale — a caller decides a row is affected by intersecting
    these keys with the row's own ``sourceRanks``, which is narrower and
    more honest than guessing at a rookie flag.

    Empty dicts mean the exclusion costs evidence but not meaning.

    **This is a DECLARATION, not a measurement, and it must not be the
    only gate.**  It reports what the registry claims; use
    :func:`shared_market_crosswalk_failed` on the board itself to find
    out what happened.  The difference is not academic — see that
    function's docstring for the one-line registry edit that satisfies
    this check while leaving the board exactly as broken.
    """
    excluded = expand_correlation_groups(excluded_keys)
    surviving = {
        str(s.get("key") or "") for s in _RANKING_SOURCES if str(s.get("key") or "") not in excluded
    }

    asset_classes: dict[str, str] = {}
    # Mirrors the backbone selection in ``_compute_unified_rankings``:
    # primary scope overall_idp AND is_backbone.
    #
    # This used to carry a comment promising that "registering a second
    # IDP backbone lifts this guard automatically instead of leaving a
    # hardcoded refusal behind", which read as a feature and is in fact
    # the hazard.  ``is_backbone`` is a LABEL: setting it True on any of
    # the five other IDP sources empties ``assetClasses`` while the board
    # stays at median 1.224 / max 3.478.  Measured, not argued —
    # ``tests/consensus_edge/test_fair_value.py`` pins it.
    if not any(
        str(s.get("key") or "") in surviving
        and s.get("scope") == SOURCE_SCOPE_OVERALL_IDP
        and s.get("is_backbone")
        for s in _RANKING_SOURCES
    ):
        asset_classes["idp"] = SCALE_LOST_IDP_BACKBONE

    sources: dict[str, str] = {}
    for rookie_key, ref_key, _universe in ROOKIE_LADDER_PAIRS:
        if rookie_key in surviving and ref_key not in surviving:
            sources[rookie_key] = SCALE_LOST_ROOKIE_LADDER

    return {"assetClasses": asset_classes, "sources": sources}


def shared_market_crosswalk_failed(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Which sources voted on an UNTRANSLATED within-class rank, per source.

    The measured counterpart to :func:`scale_integrity_lost`, and the one
    that should decide.  A source flagged ``needs_shared_market_translation``
    ranks players within the IDP class only; the backbone's shared-market
    ladder lifts that ordinal into the combined offense+IDP rank space and
    stamps ``method: "exact"``.  With no usable ladder,
    ``translate_position_rank`` returns the raw rank and stamps
    ``TRANSLATION_FALLBACK`` — the vote then says IDP #1 is asset #1.

    So this reads what the board DID rather than what the registry
    promised.  Measured on the 2026-08-03 payload:

    ==========================  ==================  ==================
    source                      default board       idpTradeCalc gone
    ==========================  ==================  ==================
    ``dlfIdp``                  exact    135        fallback   159
    ``idpShow``                 exact    215        fallback   235
    ``fantasyProsIdp``          exact    151        fallback   177
    ``draftSharksIdp``          combined 215        combined   243
    ==========================  ==================  ==================

    **Why the registry check alone is not enough.**  The backbone is
    selected by the ``is_backbone`` flag, and that flag is a label rather
    than a capability.  ``build_backbone_from_rows`` can only seed a
    shared-market ladder from a source whose OWN value column spans both
    pools, and ``idpTradeCalc`` is the only key that does (529 positive
    offense + 258 positive IDP).  ``draftSharksIdp`` looks like a
    candidate — it is registered ``is_cross_market`` — but carries 0
    positive offense values under its own key; its offense half lives
    under the separate ``draftSharks`` key.  Setting ``is_backbone=True``
    on it yields the identity ladder ``[1, 2, 3, …]``, which is precisely
    the fallback: the refusal lifts and the board is bit-for-bit the
    broken one.  ``draftSharksIdp`` itself is unaffected either way —
    it needs no crosswalk and stays on ``ds_combined_cross_market``.

    Note the *depth* of a ladder is NOT a usable capability test either:
    ``dlfIdp`` (163 > 162) and ``idpShow`` (247 > 245) both clear a
    depth comparison while producing identity ladders.  Only "the ladder
    does not start at 1" separates them (``idpTradeCalc`` starts at 30).

    Returns ``{sourceKey: rowsVotedOnUntranslatedRank}``, empty when
    every crosswalk-dependent source was translated (or none voted).
    """
    needs_translation = {
        str(s.get("key") or "")
        for s in _RANKING_SOURCES
        if s.get("needs_shared_market_translation")
    }
    failed: dict[str, int] = {}
    for row in rows or []:
        meta_by_source = row.get("sourceRankMeta")
        if not isinstance(meta_by_source, dict):
            continue
        for key, meta in meta_by_source.items():
            if key not in needs_translation or not isinstance(meta, dict):
                continue
            if meta.get("method") == TRANSLATION_FALLBACK:
                failed[str(key)] = failed.get(str(key), 0) + 1
    return failed


# Top-level keys in the override POST body that are NOT per-source
# override entries.  These are routed to their own typed helpers
# (e.g. ``normalize_tep_multiplier``) and must be skipped by the
# per-source override parser so they don't emit "unknown source"
# warnings.  Keep in lockstep with the server route and the frontend
# POST body builders.
_RESERVED_OVERRIDE_BODY_KEYS: frozenset[str] = frozenset(
    {
        "tep_multiplier",
        "tepMultiplier",
        "tep_native_multiplier",
        "tepNativeMultiplier",
        "enabled_sources",
        "enabledSources",
        "weights",
    }
)


def normalize_tep_multiplier(raw: Any) -> float | None:
    """Extract + clamp a TEP multiplier from a POST override body.

    Accepts a raw request body dict.  Returns:

      * ``None`` when no ``tep_multiplier`` / ``tepMultiplier`` key is
        present in the body — signals "user did not override, fall
        back to the league-derived default".  ``build_api_data_contract``
        and ``build_rankings_delta_payload`` both treat ``None`` as
        "derive from Sleeper" via :func:`_derive_tep_multiplier_from_league`.
      * A ``float`` clamped to ``[1.0, 1.5]`` (matching the slider's
        UI bounds) when the key IS present and parses as a finite
        number.  The clamped value is what the
        pipeline applies verbatim (no derivation layered on top).
      * ``None`` when the key is present but unparseable / infinite —
        treated the same as "absent" so a garbled body falls back to
        the league-derived default rather than silently becoming 1.0.

    The key lookup accepts both ``tep_multiplier`` (snake_case, the
    canonical API spelling) and ``tepMultiplier`` (camelCase, the
    JS-native spelling some callers may emit).
    """
    import math

    if not isinstance(raw, dict):
        return None
    for key in ("tep_multiplier", "tepMultiplier"):
        if key in raw:
            try:
                v = float(raw[key])
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v):
                return None
            return max(1.0, min(1.5, v))
    return None


def normalize_tep_native_multiplier(raw: Any) -> float | None:
    """Extract + clamp the TEP-native multiplier from a POST override body.

    Mirrors :func:`normalize_tep_multiplier` but for the parallel knob
    that controls the boost applied to TEP-native sources (DN SF-TEP,
    Yahoo Boone, FP Fitzmaurice).  Returns ``None`` when the key is
    absent / unparseable so the pipeline falls back to the hardcoded
    default (``_TE_BLANKET_NATIVE_MULTIPLIER`` = 1.10).
    """
    import math

    if not isinstance(raw, dict):
        return None
    for key in ("tep_native_multiplier", "tepNativeMultiplier"):
        if key in raw:
            try:
                v = float(raw[key])
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v):
                return None
            return max(1.0, min(1.5, v))
    return None


def normalize_source_overrides(
    raw: Any,
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Normalize and validate a user-supplied source override payload.

    Accepts the two shapes emitted by the frontend:

      * legacy ``siteWeights``-style map:
          ``{"ktc": {"include": True, "weight": 1.0}, ...}``
      * explicit request body:
          ``{"enabled_sources": [...], "weights": {...}}``
          ``{"enabledSources": [...], "weights": {...}}``

    Either shape may carry a top-level ``tep_multiplier`` /
    ``tepMultiplier`` field alongside the source entries.  That field
    is extracted separately by :func:`normalize_tep_multiplier` and
    silently ignored by this function — having it present does NOT
    cause the body to be rejected or warn, even when no source
    overrides are present.

    Returns a tuple of ``(normalized_overrides, warnings)`` where:

      * ``normalized_overrides`` is a dict keyed by registered source
        key.  Unknown keys are dropped and recorded in warnings.
        Each value is a dict with optional ``include`` (bool) and
        ``weight`` (non-negative finite float).  Missing/invalid
        fields are dropped so the override silently inherits the
        registry default for that field.
      * ``warnings`` is a list of human-readable strings describing
        any invalid or ignored input.  The caller may surface these
        in the API response under the ``warnings`` key.

    The function never raises for malformed input — it silently drops
    invalid entries and returns any valid portion so a partial
    override payload still produces a deterministic response.
    """
    import math

    warnings: list[str] = []
    valid_keys = set(get_ranking_source_keys())
    out: dict[str, dict[str, Any]] = {}

    if raw is None:
        return out, warnings
    if not isinstance(raw, dict):
        warnings.append(f"Top-level overrides must be an object; got {type(raw).__name__}")
        return out, warnings

    # ── Explicit request body: {"enabled_sources": [...], "weights": {...}} ──
    explicit_enabled = raw.get("enabled_sources")
    if explicit_enabled is None:
        explicit_enabled = raw.get("enabledSources")
    explicit_weights = raw.get("weights")

    if explicit_enabled is not None or isinstance(explicit_weights, dict):
        if explicit_enabled is not None:
            if not isinstance(explicit_enabled, (list, tuple, set)):
                warnings.append("enabled_sources must be a list of source keys; ignoring")
                enabled_set: set[str] = valid_keys
            else:
                enabled_set = set()
                for key in explicit_enabled:
                    k = str(key)
                    if k in valid_keys:
                        enabled_set.add(k)
                    else:
                        warnings.append(f"enabled_sources: unknown source '{k}' (ignored)")
        else:
            enabled_set = set(valid_keys)

        for key in valid_keys:
            entry: dict[str, Any] = {}
            if key not in enabled_set:
                entry["include"] = False
            out[key] = entry

        if isinstance(explicit_weights, dict):
            for key, value in explicit_weights.items():
                k = str(key)
                if k not in valid_keys:
                    warnings.append(f"weights: unknown source '{k}' (ignored)")
                    continue
                try:
                    w = float(value)
                except (TypeError, ValueError):
                    warnings.append(f"weights[{k}]: value '{value}' is not a number (ignored)")
                    continue
                if not math.isfinite(w) or w < 0:
                    warnings.append(f"weights[{k}]: value {w} is not non-negative finite (ignored)")
                    continue
                out.setdefault(k, {})["weight"] = w

        out = {k: v for k, v in out.items() if v}
        return out, warnings

    # ── Legacy siteWeights-style map ──
    for key, value in raw.items():
        k = str(key)
        if k in _RESERVED_OVERRIDE_BODY_KEYS:
            # Reserved top-level knobs (e.g. tep_multiplier) are
            # routed to dedicated normalizers, not per-source entries.
            continue
        if k not in valid_keys:
            warnings.append(f"Unknown source '{k}' (ignored)")
            continue
        if not isinstance(value, dict):
            warnings.append(f"Override for '{k}' must be an object; got {type(value).__name__}")
            continue
        entry = {}
        if "include" in value:
            include = value.get("include")
            if isinstance(include, bool):
                entry["include"] = include
            else:
                warnings.append(
                    f"Override '{k}'.include must be boolean; got {type(include).__name__}"
                )
        if "weight" in value:
            try:
                w = float(value.get("weight"))
            except (TypeError, ValueError):
                warnings.append(f"Override '{k}'.weight must be a number (ignored)")
            else:
                if math.isfinite(w) and w >= 0:
                    entry["weight"] = w
                else:
                    warnings.append(f"Override '{k}'.weight must be non-negative finite (ignored)")
        if entry:
            out[k] = entry
    return out, warnings


def _summarize_source_overrides(
    source_overrides: dict[str, dict[str, Any]] | None,
    *,
    tep_multiplier: float = 1.0,
    tep_multiplier_derived: float = 1.0,
    tep_multiplier_source: str = "default",
    tep_native_multiplier: float = 1.0,
    tep_native_multiplier_derived: float = 1.0,
    tep_native_multiplier_source: str = "default",
    tep_native_correction: float = 1.0,
) -> dict[str, Any]:
    """Produce the ``rankingsOverride`` contract summary block.

    The block carries:
      * ``isCustomized`` — True when at least one override actually
        diverges from the registry default, OR the effective
        ``tep_multiplier`` diverges from the league-derived default.
      * ``enabledSources`` — ordered list of source keys that were
        enabled in the effective configuration.
      * ``weights`` — dict mapping source key → effective declared
        weight (registry default OR override).
      * ``defaults`` — dict mapping source key → registry default
        weight, so the frontend can show "customized: 0.5 vs
        default 1.0" without re-fetching the registry.
      * ``received`` — the raw normalized override map the pipeline
        was given, for debugging.
      * ``tepMultiplier`` — effective (clamped) TE-premium multiplier
        that was applied during the blend.
      * ``tepMultiplierDefault`` — the league-derived default the
        frontend should treat as "auto" / unchecked.  Equals
        ``tep_multiplier_derived`` so the slider shows the right
        baseline when the user has not overridden.
      * ``tepMultiplierDerived`` — the raw TE-premium value derived
        from the operator's Sleeper ``bonus_rec_te`` (redundant with
        ``tepMultiplierDefault`` but kept as an explicit channel so
        the frontend never confuses derivation with fallback).
      * ``tepMultiplierSource`` — one of ``"derived"`` (came from
        Sleeper), ``"explicit"`` (user slider override), or
        ``"default"`` (fallback when the Sleeper fetch failed and no
        override was sent).  The frontend uses this to label the
        slider state ("Auto from league" vs "Custom override").
    """
    import math

    normalized = source_overrides or {}
    is_customized = False
    enabled_sources: list[str] = []
    effective_weights: dict[str, float] = {}
    default_weights: dict[str, float] = {}
    for src in _RANKING_SOURCES:
        key = str(src.get("key") or "")
        if not key:
            continue
        default_weight = float(src.get("weight") or 0.0)
        default_weights[key] = default_weight
        ov = normalized.get(key) or {}
        include = ov.get("include")
        enabled = include is not False
        if enabled:
            enabled_sources.append(key)
        if include is False:
            is_customized = True
        weight_override = ov.get("weight")
        if weight_override is not None:
            try:
                w = float(weight_override)
            except (TypeError, ValueError):
                w = default_weight
            if math.isfinite(w) and w >= 0:
                effective_weights[key] = w
                if w != default_weight:
                    is_customized = True
            else:
                effective_weights[key] = default_weight
        else:
            effective_weights[key] = default_weight

    # Clamp the TEP multiplier to the same [1.0, 1.5] range the
    # ``normalize_tep_multiplier`` ingress and the /settings slider
    # enforce, so a non-normalize caller (direct ``build_api_data_contract``
    # invocation, malformed body, etc.) can't pump TE values off the
    # board through the summary stamp.  Live derivations land at the
    # hardcoded default 1.15; the wider [1.0, 2.0] range that historically
    # accommodated ``_derive_tep_multiplier_from_league`` outputs is no
    # longer needed (that derivation is no longer wired into the live
    # build_api_data_contract path — see line ~7190).
    try:
        tep_eff = float(tep_multiplier)
    except (TypeError, ValueError):
        tep_eff = 1.0
    if not math.isfinite(tep_eff):
        tep_eff = 1.0
    tep_eff = max(1.0, min(1.5, tep_eff))

    try:
        tep_derived = float(tep_multiplier_derived)
    except (TypeError, ValueError):
        tep_derived = 1.0
    if not math.isfinite(tep_derived):
        tep_derived = 1.0
    tep_derived = max(1.0, min(1.5, tep_derived))

    # isCustomized flips only when the user-facing effective value
    # diverges from the league-derived baseline.  A league with
    # bonus_rec_te=0.5 (derived TEP=1.15) that lands on tep_eff=1.15
    # is NOT customized — the user just accepted the auto value.
    # Customization only fires when they explicitly drag the slider
    # to something else.
    if abs(tep_eff - tep_derived) > 1e-6:
        is_customized = True

    # TEP-native: clamp + customization check, mirroring the non-TEP
    # multiplier above.  Same [1.0, 1.5] range as the
    # ``normalize_tep_native_multiplier`` ingress.
    try:
        tep_native_eff = float(tep_native_multiplier)
    except (TypeError, ValueError):
        tep_native_eff = 1.0
    if not math.isfinite(tep_native_eff):
        tep_native_eff = 1.0
    tep_native_eff = max(1.0, min(1.5, tep_native_eff))

    try:
        tep_native_derived = float(tep_native_multiplier_derived)
    except (TypeError, ValueError):
        tep_native_derived = 1.0
    if not math.isfinite(tep_native_derived):
        tep_native_derived = 1.0
    tep_native_derived = max(1.0, min(1.5, tep_native_derived))

    if abs(tep_native_eff - tep_native_derived) > 1e-6:
        is_customized = True

    # Clamp the TEP-native correction for display purposes only; the
    # pipeline already consumed it as-is during the blend.
    try:
        tep_native_corr = float(tep_native_correction)
    except (TypeError, ValueError):
        tep_native_corr = 1.0
    if not math.isfinite(tep_native_corr):
        tep_native_corr = 1.0

    # Reverse-derive the Sleeper ``bonus_rec_te`` value so the
    # frontend can show it alongside the multiplier on /settings —
    # ``derived = 1.0 + bonus * _TEP_DERIVATION_SLOPE`` (see
    # ``_derive_tep_multiplier_from_league``), so
    # ``bonus = (derived - 1.0) / _TEP_DERIVATION_SLOPE``.
    if _TEP_DERIVATION_SLOPE > 0:
        bonus_rec_te = max(0.0, (tep_derived - 1.0) / _TEP_DERIVATION_SLOPE)
    else:
        bonus_rec_te = 0.0

    return {
        "isCustomized": is_customized,
        "enabledSources": enabled_sources,
        "weights": effective_weights,
        "defaults": default_weights,
        "received": dict(normalized),
        "tepMultiplier": round(tep_eff, 4),
        "tepMultiplierDefault": round(tep_derived, 4),
        "tepMultiplierDerived": round(tep_derived, 4),
        "tepMultiplierSource": str(tep_multiplier_source or "default"),
        "tepNativeMultiplier": round(tep_native_eff, 4),
        "tepNativeMultiplierDefault": round(tep_native_derived, 4),
        "tepNativeMultiplierDerived": round(tep_native_derived, 4),
        "tepNativeMultiplierSource": str(tep_native_multiplier_source or "default"),
        "tepNativeCorrection": round(tep_native_corr, 4),
        # Underlying Sleeper TE-bonus value driving the derivation.
        # Empty / non-TEP leagues return 0.0; standard "TEP-1.5" is 0.5.
        "bonusRecTe": round(bonus_rec_te, 3),
    }


def assert_ranking_source_registry_parity(
    frontend_registry: list[dict[str, Any]],
) -> list[str]:
    """Verify the frontend JS registry matches the Python one.

    Returns a list of human-readable mismatch descriptions.  An empty
    list means the two registries are in full agreement on keys,
    declared weights, scopes, retail/backbone/TEP flags, and ordering.
    """
    errors: list[str] = []
    py_registry = get_ranking_source_registry()
    py_keys = [s["key"] for s in py_registry]
    js_keys = [str(s.get("key") or "") for s in (frontend_registry or [])]
    if py_keys != js_keys:
        errors.append(f"Registry key order/mismatch:\n  python: {py_keys}\n  frontend: {js_keys}")
        return errors

    for py, js in zip(py_registry, frontend_registry):
        key = py["key"]
        for field in (
            "scope",
            "extraScopes",
            "positionGroup",
            "depth",
            "weight",
            "isBackbone",
            "isRetail",
            "isTepPremium",
            # Derived from _SOURCE_CSV_PATHS signal (audit F-8) — the
            # field that controls value-vs-rank display semantics was
            # exactly the one the parity check used to skip.
            "isRankSignal",
            # Which sources are non-independent.  Checked here because a
            # frontend that disagrees about correlation would show a
            # source count the backend considers inflated.
            "correlationGroup",
        ):
            py_val = py.get(field)
            js_val = js.get(field)
            if field == "correlationGroup":
                # Both sides may omit the field for an independent
                # source; the singleton default is the source's own key.
                # Normalising here means the frontend only declares a
                # group where one genuinely exists, so the mirror does
                # not carry 19 lines of restated default that could
                # drift.
                py_val = str(py_val or key)
                js_val = str(js_val or key)
            if field == "extraScopes":
                py_val = list(py_val or [])
                js_val = list(js_val or [])
            if field == "weight":
                if float(py_val or 0) != float(js_val or 0):
                    errors.append(f"{key}.weight: python={py_val} frontend={js_val}")
                continue
            if py_val != js_val:
                errors.append(f"{key}.{field}: python={py_val} frontend={js_val}")
    return errors


def _source_is_enabled(
    src: dict[str, Any],
    source_overrides: dict[str, dict[str, Any]] | None,
) -> bool:
    """True if a registered source is active under the override map."""
    if not source_overrides:
        return True
    ov = source_overrides.get(src.get("key") or "") or {}
    return ov.get("include") is not False


def _effective_source_weight(
    src: dict[str, Any],
    source_overrides: dict[str, dict[str, Any]] | None,
) -> float:
    """Return the effective declared weight for a source under an override map."""
    default = float(src.get("weight") or 0.0)
    if not source_overrides:
        return default
    ov = source_overrides.get(src.get("key") or "") or {}
    w = ov.get("weight")
    if w is None:
        return default
    try:
        w = float(w)
    except (TypeError, ValueError):
        return default
    import math as _m

    if not _m.isfinite(w) or w < 0:
        return default
    return w


def _anchor_key_sets(
    active_sources: list[dict[str, Any]],
) -> tuple[set[str], set[str]]:
    """Return ``(cross_market_keys, pick_anchor_keys)`` for the blend.

    Anchor membership requires a POSITIVE effective weight: a source
    the user left enabled but slid to weight 0 must not anchor
    anything (Codex review on PR #530 — the membership-only check
    promoted zero-weight KTC into the pick anchor at full peer
    strength).  ``pick_anchor_keys`` additionally includes ktcSfTep —
    the deepest pick market ingested — so on PICK rows the two real
    pick markets (KTC + IDPTC) average as peers instead of KTC riding
    in the α=0.10 subgroup (2026-07-25 calculation audit, F-2).

    NOTE on weights (updated 2026-07-29 audit): subgroup/flat votes
    are weighted by each source's DECLARED weight (all 1.0 by registry
    default → equal voice; user overrides scale a source's vote — see
    ``weighted_count_aware_mean_median_blend``).  A weight-0 source
    does not vote anywhere: ``_active_sources`` drops it before the
    blend ever sees it.
    """
    positively_weighted: set[str] = set()
    for s in active_sources:
        try:
            w = float(s.get("weight") or 0.0)
        except (TypeError, ValueError):
            w = 0.0
        if w > 0:
            positively_weighted.add(str(s.get("key") or ""))
    cross_market = {
        str(s.get("key") or "")
        for s in active_sources
        if s.get("is_cross_market") and str(s.get("key") or "") in positively_weighted
    }
    pick_anchor = cross_market | ({"ktcSfTep"} & positively_weighted)
    return cross_market, pick_anchor


def _active_sources(
    source_overrides: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return a filtered list of _RANKING_SOURCES with overrides applied.

    Disabled sources are dropped entirely.  Weight overrides produce a
    shallow copy of the source dict with the ``weight`` field
    replaced.  Sources that inherit their defaults are passed through
    by reference so the hot path does not pay a copy tax when no
    overrides are in play.

    A NON-POSITIVE effective weight also drops the source (Codex
    review on PR #530): "enabled with weight 0" has exactly one
    coherent meaning: no vote.  Before this, a weight-0 source kept
    voting at full strength in the subgroup/flat blend (and, until
    the prior commit, anchoring).  Registry defaults are all 1.0, so
    this only affects explicit user overrides.

    Weight semantics (2026-07-29 audit): a POSITIVE override weight is
    now genuinely applied — the count-aware blend multiplies each
    source's vote by its declared weight (see
    ``weighted_count_aware_mean_median_blend``).  With every weight at
    the 1.0 registry default the blend is exactly the historical
    unweighted equal-voice blend.
    """
    if not source_overrides:
        return list(_RANKING_SOURCES)
    out: list[dict[str, Any]] = []
    for src in _RANKING_SOURCES:
        if not _source_is_enabled(src, source_overrides):
            continue
        ov = source_overrides.get(src.get("key") or "") or {}
        if "weight" in ov:
            eff_weight = _effective_source_weight(src, source_overrides)
            if eff_weight <= 0:
                continue
            copy = dict(src)
            copy["weight"] = eff_weight
            out.append(copy)
        else:
            out.append(src)
    return out


def _compute_market_gap(
    source_ranks: dict[str, int],
    source_meta: dict[str, dict] | None = None,
    retail_keys: set[str] | frozenset[str] | None = None,
) -> tuple[str, float | None]:
    """Quantify the disagreement between retail and expert consensus.

    "Market gap" frames the retail market (sources flagged `is_retail`
    in the registry — today just KTC) against every other registered
    source (the expert consensus — IDPTC, DLF, and any future non-retail
    source).  Both sides are averaged in VALUE space and the gap is their
    RELATIVE difference.

    Measured in ordinal ranks until 2026-08-05, which was wrong in a way
    that looked plausible: the sides are drawn from pools of very unequal
    depth (ktcSfTep 473 rows, idpTradeCalc 901, dlfSf 278), so
    differencing their mean ordinals measured pool depth and format basis
    rather than opinion.  On the live board the median signed gap by
    position was TE +40.7 ranks against QB -18.3, RB -9.3 and WR -6.0 —
    every position negative and TE alone hugely positive, which is not 15
    independent boards agreeing about tight ends.  In value space the same
    medians are QB +0.008, TE +0.084, WR +0.110, RB +0.112.

    ``valueContribution`` is the right currency because it is what the
    blend itself compares sources in: post-ladder, common-scaled 0-9999,
    and after ADR-015's ``convert_te_value`` has been applied — which is
    exactly the correction the rank-space gap never saw.

    A retail premium means retail ranks the player higher (lower rank
    number) than consensus — i.e. the retail market is pricing the
    player above where the experts have them.  A consensus premium is
    the reverse: the experts value the player more than retail does,
    making them a potential "buy low" from a retail-first trade partner.

    Returns (direction, magnitude) where direction is one of:
      "retail_premium"     — retail mean rank is lower number than consensus mean
      "consensus_premium"  — consensus mean rank is lower number than retail mean
      "none"               — tie, or either side has zero sources present

    magnitude is the absolute RELATIVE gap in value space — 0.25 means
    one side prices the player 25% above the other — or None when the
    comparison cannot be made (one side has no priced source on this row,
    or no value stamps were supplied).  Magnitude is 0.0 on a tie.

    `retail_keys` is an optional override for tests; when None the set is
    derived from `_RANKING_SOURCES` via `_retail_source_keys()`.
    """
    if retail_keys is None:
        retail_keys = _retail_source_keys()

    meta = source_meta or {}
    retail_values: list[float] = []
    consensus_values: list[float] = []
    for key in source_ranks:
        raw = (meta.get(key) or {}).get("valueContribution")
        if not isinstance(raw, (int, float)):
            continue
        (retail_values if key in retail_keys else consensus_values).append(float(raw))

    if not retail_values or not consensus_values:
        # Either a side is absent, or the caller passed no value stamps.
        # Both mean "cannot compare" — say so rather than silently
        # dropping back to the ordinal arithmetic this replaced.
        return "none", None

    retail_mean = sum(retail_values) / len(retail_values)
    consensus_mean = sum(consensus_values) / len(consensus_values)
    scale = (retail_mean + consensus_mean) / 2.0
    if scale <= 0:
        return "none", None

    # Positive → retail VALUES the player above consensus.  Note this
    # inverts the sense of the old rank comparison, where retail ranking
    # him "higher" meant a LOWER mean rank number.
    ratio = (retail_mean - consensus_mean) / scale
    if ratio > 0:
        return "retail_premium", float(abs(ratio))
    if ratio < 0:
        return "consensus_premium", float(abs(ratio))
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
        (_to_int_or_none(canonical_sites.get(k)) or 0) > 0 for k in _OFFENSE_SIGNAL_KEYS
    )
    has_idp_val = any((_to_int_or_none(canonical_sites.get(k)) or 0) > 0 for k in _IDP_SIGNAL_KEYS)

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
        names_involved = sorted({str(players_array[i].get("canonicalName") or "") for i in indices})
        duplicate_identity_pairs.append(
            {
                "canonicalKey": posaware,
                "names": names_involved,
            }
        )
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
            collision_pairs.append(
                {
                    "normalizedName": norm,
                    "names": names_involved,
                    "assetClasses": list(asset_classes),
                }
            )
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
        canonical_sites = row.get("canonicalSiteValues") or {}

        has_off_val = any(
            (_to_int_or_none(canonical_sites.get(k)) or 0) > 0 for k in _OFFENSE_SIGNAL_KEYS
        )
        has_idp_val = any(
            (_to_int_or_none(canonical_sites.get(k)) or 0) > 0 for k in _IDP_SIGNAL_KEYS
        )

        current_flags = row.get("anomalyFlags") or []
        has_collision = "name_collision_cross_universe" in current_flags
        name = row.get("canonicalName") or ""
        is_known_collision = has_collision and name in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS

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
        has_any_source = any((_to_int_or_none(v) or 0) > 0 for v in canonical_sites.values())
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
                row["confidenceLabel"] = "Low — quarantined due to identity/data-quality flags"
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
    "marketGapValueRatio",
    "identityConfidence",
    "identityMethod",
    "quarantined",
    "sourceAudit",
    "sourceOriginalRanks",
    # Native vendor values for rank-signal sources (parallel map to
    # sourceOriginalRanks).  Without mirroring, the default view=app
    # payload (which strips playersArray) would never carry them.
    "sourceNativeValues",
    "canonicalTierId",
    # ``rankChange`` is stamped by ``_stamp_rank_changes`` at the end
    # of ``_compute_unified_rankings`` but only onto the playersArray.
    # Without mirroring, the runtime ``view=app`` (which strips
    # playersArray) ships a legacy dict with zero rankChange fields,
    # which is why ``RankChangeGlyph`` had nothing to render on the
    # default /rankings path for every row (2026-04-22 audit).
    "rankChange",
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


def _strip_mismatched_family_tags(players_array: list[dict[str, Any]]) -> None:
    """Clear position tags set ONLY from the sleeper map when the final
    canonicalSiteValues contradict the family.

    Runs AFTER :func:`_enrich_from_source_csvs` so it sees the full set
    of per-source signals that ended up attached to each row. Only
    targets rows marked ``_positionFromSleeperOnly`` by
    :func:`_derive_player_row` — rows whose position was supplied by an
    adapter (explicit source-level tag) are left alone so the existing
    contamination flaggers can raise ``position_source_contradiction``
    for them. This narrow scope specifically unblocks the sleeper-map
    name-collision case (DJ Turner WR vs DJ Turner II CB collapsing to
    the same clean_name key) without masking real contamination.

    Mutates rows in place. When a mismatch is detected, the position is
    cleared — downstream validators treat unpositioned rows as offense,
    which is safe for the "row has only offensive signals" case.
    """
    for row in players_array:
        if not row.get("_positionFromSleeperOnly"):
            continue
        pos = str(row.get("position") or "").strip().upper()
        if not pos:
            continue
        canonical_sites = row.get("canonicalSiteValues") or {}
        if not isinstance(canonical_sites, dict):
            continue
        has_off = any(
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _OFFENSE_SIGNAL_KEYS
        )
        has_idp = any(
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _IDP_SIGNAL_KEYS
        )
        if pos in _IDP_POSITIONS and has_off and not has_idp:
            row["position"] = None
            row["assetClass"] = "offense"
        elif pos in _OFFENSE_POSITIONS and has_idp and not has_off:
            row["position"] = None
            row["assetClass"] = "offense"


# mtime-keyed caches for source CSV parses.  The parsed lookups are pure
# functions of file contents, so any rebuild that happens before the CSV
# is re-scraped can skip the parse entirely.  Cache key is the absolute
# csv path string; the value is a 3-tuple of (mtime, csv_lookup, schema_err).
_SOURCE_CSV_PARSE_CACHE: dict[
    str, tuple[float, dict[str, list[tuple[str, int, float | None]]], dict[str, str] | None]
] = {}
_FP_META_CSV_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


def _parse_source_csv_cached(
    csv_path: Path,
    source_key: str,
    signal: str,
    csv_rel: str,
) -> tuple[dict[str, list[tuple[str, int, float | None]]], dict[str, str] | None]:
    """Parse a source CSV with mtime-keyed caching.

    Returns ``(csv_lookup, schema_error_dict_or_None)``.  The schema
    error, when present, is a dict suitable for ``parse_errors.append``.
    """
    import csv as _csv  # noqa: PLC0415

    try:
        current_mtime = csv_path.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    cache_key = str(csv_path)
    cached = _SOURCE_CSV_PARSE_CACHE.get(cache_key)
    if cached and cached[0] == current_mtime:
        return cached[1], cached[2]

    csv_lookup: dict[str, list[tuple[str, int, float | None]]] = {}
    schema_err: dict[str, str] | None = None

    _NAME_ALIASES = ("name", "Name", "player", "Player", "player_name", "PlayerName")
    # DLF raw CSV exports carry both ``Rank`` (ordinal) and ``Avg``
    # (expert-consensus average — fractional like 1.17, 2.83, 3.00).
    # ``Avg`` preserves the underlying consensus fidelity (near-ties
    # vs clear separation), so we prefer it when present.  Other
    # sources without an ``Avg`` column fall through to ``rank`` /
    # ``Rank`` as before.
    _RANK_ALIASES = (
        "Avg",
        "avg",
        "rank",
        "Rank",
        "overall_rank",
        "OverallRank",
        "effectiveRank",
    )
    # ``3D Value +`` is DraftSharks' normalised 0-100 value column (top
    # player = 100, decimals preserved).  ``boone_value`` is Yahoo /
    # Justin Boone's published trade value (0-~141 integer scale).
    # Conventional aliases are placed first so more generic columns
    # win when multiple are present.
    _VALUE_ALIASES = (
        "value",
        "Value",
        "trade_value",
        "TradeValue",
        "3D Value +",
        "boone_value",
    )
    # Optional Sleeper player-id column (today only pfkDynasty emits
    # one).  When present it gives ID-grade identity that survives
    # vendor/Sleeper name-spelling drift ("Kenneth Gainwell" vs
    # "Kenny Gainwell") — the enrichment tries the ID join before the
    # canonical-name cascade (Codex review on PR #532).
    _SLEEPER_ID_ALIASES = ("sleeper_id", "sleeperId", "sleeper_player_id")

    def _pick(csvrow: dict[str, Any], aliases: tuple[str, ...]) -> str:
        for k in aliases:
            if k in csvrow and csvrow[k] not in (None, ""):
                return str(csvrow[k])
        return ""

    # ── Schema probe for DLF / FantasyPros sources ───────────────────
    if source_key in ("dlfSf", "dlfIdp", "fantasyProsIdp", "fantasyProsSf"):
        try:
            with csv_path.open("r", encoding="utf-8-sig") as f_probe:
                header_line = f_probe.readline().strip()
        except Exception as exc:  # noqa: BLE001
            header_line = ""
            _LOGGER.warning(
                "Schema probe: failed to read header for %s: %s",
                source_key,
                exc,
            )
        if source_key == "dlfSf":
            # Historical schema (manual DLF export): capitalized
            # ``Rank,Avg,Pos,Name,Team,Age,<expert cols>,Value,Follow``.
            # New schema (``scripts/fetch_dlf.py``): lowercase
            # ``name,rank`` — already preferred-Avg-over-Rank at the
            # fetcher, so the loader just reads the two columns.
            # Accept either shape via the token set so we don't need a
            # migration window where one side is stale.
            expected_tokens = ("Rank", "Avg", "Name", "Player", "name", "rank")
        elif source_key == "fantasyProsIdp":
            expected_tokens = (
                "effectiveRank",
                "derivationMethod",
                "family",
                "name",
            )
        elif source_key == "fantasyProsSf":
            expected_tokens = ("Rank", "name", "position")
        else:  # dlfIdp
            expected_tokens = ("name", "Name", "Player", "rank", "Rank")
        if not any(tok in header_line for tok in expected_tokens):
            schema_err = {
                "source": source_key,
                "path": str(csv_rel),
                "error": "schema_mismatch",
                "header": header_line[:200],
            }
            _LOGGER.warning(
                "Schema probe: %s header mismatch (%s); skipping rows",
                source_key,
                header_line[:120],
            )
            _SOURCE_CSV_PARSE_CACHE[cache_key] = (current_mtime, csv_lookup, schema_err)
            return csv_lookup, schema_err

    try:
        with csv_path.open("r", encoding="utf-8-sig") as f:
            for csvrow in _csv.DictReader(f):
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
                    synthetic = int(
                        round((_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100) - (rank_val * 100))
                    )
                    if synthetic <= 0:
                        continue
                    # Rank-signal CSVs usually still carry the vendor's
                    # native value column (FantasyCalc crowd value, OTC
                    # 0-100, PFK 0-9999, ...).  Preserve it so the UI /
                    # exports can show the real number instead of the
                    # synthetic rank encoding — ``canonicalSiteValues``
                    # keeps the synthetic (the ordering machinery), the
                    # native lands in ``sourceNativeValues``.
                    native_raw = _pick(csvrow, _VALUE_ALIASES)
                    native_val: float | None = None
                    if native_raw != "":
                        try:
                            nv = float(str(native_raw).strip())
                            if nv > 0:
                                native_val = nv
                        except (TypeError, ValueError):
                            native_val = None
                    sid = _pick(csvrow, _SLEEPER_ID_ALIASES).strip()
                    csv_lookup.setdefault(key, []).append(
                        (name, synthetic, rank_val, native_val, sid or None)
                    )
                else:
                    val = _pick(csvrow, _VALUE_ALIASES)
                    if not val:
                        continue
                    # Value-signal CSVs often carry a rank column too
                    # (e.g. yahooBoone emits name,pos,rank,boone_value).
                    # Preserve it so ``sourceOriginalRanks[source_key]``
                    # stamps for the UI just like the rank-signal
                    # branch does.  Missing/invalid → None (harmless).
                    # nativeValue is None for value-signal sources —
                    # their ``canonicalSiteValues`` slot already IS the
                    # native number.
                    rank_raw = _pick(csvrow, _RANK_ALIASES)
                    orig_rank: float | None = None
                    if rank_raw != "":
                        try:
                            rv = float(str(rank_raw).strip())
                            if rv > 0:
                                orig_rank = rv
                        except (TypeError, ValueError):
                            orig_rank = None
                    sid = _pick(csvrow, _SLEEPER_ID_ALIASES).strip()
                    try:
                        csv_lookup.setdefault(key, []).append(
                            (name, int(float(val)), orig_rank, None, sid or None)
                        )
                    except (ValueError, TypeError):
                        continue
    except Exception as exc:  # noqa: BLE001
        schema_err = {
            "source": source_key,
            "path": str(csv_rel),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _LOGGER.warning(
            "Failed to parse source CSV %s (%s): %s",
            source_key,
            csv_rel,
            exc,
        )
        # Don't cache parse failures — next rebuild retries.
        return csv_lookup, schema_err

    _SOURCE_CSV_PARSE_CACHE[cache_key] = (current_mtime, csv_lookup, schema_err)
    return csv_lookup, schema_err


def _parse_fp_meta_csv_cached(fp_path: Path) -> dict[str, dict[str, Any]]:
    """Parse FantasyPros IDP metadata CSV with mtime-keyed caching."""
    import csv as _csv  # noqa: PLC0415

    try:
        current_mtime = fp_path.stat().st_mtime
    except OSError:
        current_mtime = 0.0
    cache_key = str(fp_path)
    cached = _FP_META_CSV_CACHE.get(cache_key)
    if cached and cached[0] == current_mtime:
        return cached[1]

    fp_meta_lookup: dict[str, dict[str, Any]] = {}
    with fp_path.open("r", encoding="utf-8-sig") as f:
        for row_csv in _csv.DictReader(f):
            nm = str(row_csv.get("name") or "").strip()
            if not nm:
                continue
            key = _canonical_match_key(nm)
            if not key:
                continue
            try:
                orig_r = int(float(row_csv.get("originalRank") or 0))
            except (TypeError, ValueError):
                orig_r = 0
            try:
                eff_r = int(float(row_csv.get("effectiveRank") or 0))
            except (TypeError, ValueError):
                eff_r = 0
            try:
                norm_v = int(float(row_csv.get("normalizedValue") or 0))
            except (TypeError, ValueError):
                norm_v = 0
            fp_meta_lookup[key] = {
                "fantasyProsIdpOriginalRank": orig_r,
                "fantasyProsIdpEffectiveRank": eff_r,
                "fantasyProsIdpDerivationMethod": str(
                    row_csv.get("derivationMethod") or ""
                ).strip(),
                "fantasyProsIdpFamily": str(row_csv.get("family") or "").strip(),
                "fantasyProsIdpNormalizedValue": norm_v,
                "fantasyProsIdpMatchedSourceName": str(
                    row_csv.get("matchedSourceName") or nm
                ).strip(),
            }
    _FP_META_CSV_CACHE[cache_key] = (current_mtime, fp_meta_lookup)
    return fp_meta_lookup


def _enrich_from_source_csvs(
    players_array: list[dict[str, Any]],
    *,
    parse_errors: list[dict[str, str]] | None = None,
    csv_root: "Path | None" = None,
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
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    csv_index: dict[str, dict[str, dict[str, Any]]] = {}

    # DraftSharks (offense + IDP) publish a cross-market 0-100 ``3D
    # Value +`` scale that goes negative past ~rank 200 — the CSV
    # rows below that threshold carry legitimate negative values
    # (e.g. Emmanuel McNeil-Warren IDP rank 362 → -25).  Other
    # value-signal sources (KTC, IDPTC, DynastyNerds, Boone) only
    # emit non-negative values, so we keep the ``val > 0`` guard
    # for them and only relax it for the DS combined-rank sources.
    # Without this carve-out every negatively-valued DS row is
    # silently dropped from ``canonicalSiteValues``, which means
    # the downstream DS combined-rank pre-pass never sees those
    # players and they show up with zero DS coverage on the board.
    ds_combined_rank_keys = _DS_COMBINED_RANK_KEYS

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

    # ``csv_root`` lets a caller point the same loader at a different
    # tree of source CSVs.  The one caller is the historical panel
    # builder (``src/consensus_edge/panel.py``), which materialises the
    # CSVs as they stood on a past date out of git and needs TODAY's
    # pipeline to read THAT date's inputs.  Defaults to the repo, so the
    # live path is untouched.
    if csv_root is not None:
        repo = Path(csv_root)

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
            if parse_errors is not None:
                parse_errors.append(
                    {
                        "source": source_key,
                        "path": str(csv_rel),
                        "error": "file_not_found",
                    }
                )
                _LOGGER.warning("Source CSV missing for %s: %s", source_key, csv_rel)
            continue

        csv_lookup, schema_err = _parse_source_csv_cached(csv_path, source_key, signal, csv_rel)
        if schema_err is not None:
            if parse_errors is not None:
                parse_errors.append(schema_err)
            continue

        if not csv_lookup:
            continue

        # ── Rookie source → synthetic pick-slot stamps ──
        # dlfRookieSf ranks rookies; user-visible rookie picks
        # (2026 1.01, 1.02, ..., 6.12) should inherit the rookie
        # source's value at the matching ordinal so the blend pulls
        # pick values toward the DLF rookie-class consensus.  We
        # preserve the CSV's natural ordering by synthetic value
        # (same as the blend's Phase 1 sort) and append pick
        # entries into csv_lookup so the existing enrichment +
        # rank-signal path handles them uniformly.  Only wired for
        # dlfRookieSf because most rookie draft picks go to
        # offensive prospects; IDP rookie rank is far less
        # predictive of what a 1st-round pick lands on.
        if source_key == "dlfRookieSf":
            csv_lookup = {k: list(v) for k, v in csv_lookup.items()}
            _flat = [(t[0], t[1], t[2]) for entries in csv_lookup.values() for t in entries]
            _flat.sort(key=lambda t: (-t[1], str(t[0]).lower()))
            _dlf_league_size = _resolve_league_roster_count()
            _dlf_pick_year = current_rookie_draft_year()
            for _rookie_idx, (_disp, _syn, _rnk) in enumerate(_flat):
                rookie_rank = _rookie_idx + 1
                if rookie_rank > _dlf_league_size * _ROOKIE_ANCHOR_ROUNDS:
                    break
                _rnd = (rookie_rank - 1) // _dlf_league_size + 1
                _slot = (rookie_rank - 1) % _dlf_league_size + 1
                _pick_name = f"{_dlf_pick_year} Pick {_rnd}.{_slot:02d}"
                _pick_key = _canonical_match_key(_pick_name)
                if not _pick_key:
                    continue
                csv_lookup.setdefault(_pick_key, []).append(
                    (_pick_name, _syn, float(rookie_rank), None, None)
                )

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
                best_name, best_val, best_orig_rank, best_native, best_sid = entries_sorted[0]
                per_source[f"{cname}::{grp}"] = {
                    "value": best_val,
                    "originalRank": best_orig_rank,
                    "nativeValue": best_native,
                    "sleeperId": best_sid,
                    "displayName": best_name,
                    "ambiguous": len(entries) > 1,
                    "candidates": [t[0] for t in entries],
                }
            else:
                # Multiple position groups share this canonical key.
                # Without per-CSV-row position info we can't tell which
                # entry belongs to which group, so we replicate the
                # best entry across both groups but flag it as ambiguous
                # so the row audit can downgrade trust.
                entries_sorted = sorted(entries, key=lambda t: -t[1])
                best_name, best_val, best_orig_rank, best_native, best_sid = entries_sorted[0]
                for grp in row_groups:
                    per_source[f"{cname}::{grp}"] = {
                        "value": best_val,
                        "originalRank": best_orig_rank,
                        "nativeValue": best_native,
                        "sleeperId": best_sid,
                        "displayName": best_name,
                        "ambiguous": True,
                        "candidates": [t[0] for t in entries],
                        "groupCollision": sorted(row_groups),
                    }
        csv_index[source_key] = per_source

        # Sleeper-ID join index (sources whose CSV carries a
        # sleeper_id column — today only pfkDynasty).  ID-grade
        # identity survives vendor/Sleeper name-spelling drift that
        # breaks the canonical-name cascade ("Kenneth Gainwell" in the
        # PFK CSV vs Sleeper's "Kenny Gainwell" produce different
        # canonical keys and silently dropped the vote — Codex review
        # on PR #532).  Tried FIRST in the row loop below.
        sid_index: dict[str, dict[str, Any]] = {}
        for _entry in per_source.values():
            _sid = _entry.get("sleeperId")
            if _sid:
                sid_index[str(_sid)] = _entry

        # Enrich missing values onto each row using the position-aware
        # key cascade.
        for row in players_array:
            csv_vals = row.get("canonicalSiteValues")
            if not isinstance(csv_vals, dict):
                continue
            existing = _safe_num(csv_vals.get(source_key))
            # Rows that already carry a real value skip VALUE
            # enrichment, but the CSV entry is still resolved so the
            # display metadata (originalRank / nativeValue) stamps
            # either way — an already-populated slot (scraper payload,
            # or a rebuild over a previously-enriched payload) must
            # not leave the tooltips without the vendor's native
            # number (Codex review on PR #532 round 7).  For DS
            # combined-rank sources any non-None number counts (their
            # scale goes negative, so "already stamped" is any
            # finite value); for everyone else we require > 0 so a
            # stale zero doesn't block the enrichment from re-running.
            value_present = existing is not None and (
                existing > 0 or (source_key in ds_combined_rank_keys and existing <= 0)
            )
            entry = None
            if sid_index:
                # Rows stamp the Sleeper id as ``playerId`` (mapped
                # from the legacy ``_sleeperId``).
                row_sid = str(row.get("playerId") or "").strip()
                if row_sid:
                    entry = sid_index.get(row_sid)
                if entry is not None:
                    # Mirror the ID match into the name-keyed audit
                    # index under the ROW's canonical key — the
                    # source-audit lookup is name-keyed, so without
                    # this alias an ID-only match (Kenneth vs Kenny
                    # Gainwell) enriches the vote but the audit panel
                    # misreports it as ``via: scraper_payload`` (Codex
                    # review on PR #532 round 5).  ``per_source`` is
                    # the same dict csv_index already references, so
                    # the alias is visible to the audit pass.
                    audit_nm = str(row.get("canonicalName") or row.get("displayName") or "")
                    audit_cname = _canonical_match_key(audit_nm)
                    if audit_cname:
                        audit_grp = canonical_position_group(row.get("position"))
                        per_source.setdefault(
                            f"{audit_cname}::{audit_grp}",
                            {**entry, "matchedVia": "sleeper_id"},
                        )
            if entry is None:
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
            if value_present:
                # Metadata-only stamping: never overwrite the existing
                # contribution, just make sure the display fields are
                # populated.
                orig_rank = entry.get("originalRank")
                if orig_rank is not None:
                    row.setdefault("sourceOriginalRanks", {}).setdefault(
                        source_key, round(float(orig_rank), 2)
                    )
                native_val = entry.get("nativeValue")
                if native_val is not None:
                    row.setdefault("sourceNativeValues", {}).setdefault(
                        source_key, round(float(native_val), 2)
                    )
                continue
            val = entry.get("value")
            # DS combined-rank sources accept negative values (their
            # ``3D Value +`` scale goes negative past ~rank 200, and
            # those rows are real — they just sort to the tail of the
            # combined cross-market ladder); every other value-signal
            # source requires > 0 to distinguish "ranked" from
            # "missing/zero".
            negatives_allowed = source_key in ds_combined_rank_keys
            accept = val is not None and (val > 0 if not negatives_allowed else True)
            if accept:
                csv_vals[source_key] = val
                # For rank-signal sources, preserve the original CSV rank
                # so the frontend can display it instead of the meaningless
                # synthetic value.
                orig_rank = entry.get("originalRank")
                if orig_rank is not None:
                    orig_ranks = row.setdefault("sourceOriginalRanks", {})
                    orig_ranks[source_key] = round(float(orig_rank), 2)
                # ... and the vendor's native value (rank-signal sources
                # only; value-signal sources' canonicalSiteValues slot is
                # already the native number).  Roadmap item 7: rank and
                # value stay separate data points.
                native_val = entry.get("nativeValue")
                if native_val is not None:
                    natives = row.setdefault("sourceNativeValues", {})
                    natives[source_key] = round(float(native_val), 2)

    # ── FantasyPros IDP metadata stamp ──────────────────────────────
    # The generic rank-signal enrichment only stamps the effective
    # rank into ``sourceOriginalRanks[fantasyProsIdp]``.  FantasyPros
    # IDP rows carry additional per-player diagnostics — originalRank,
    # derivationMethod, family, normalizedValue, matchedSourceName —
    # that we store as flat ``fantasyProsIdp*`` fields on the row for
    # audit + frontend display.  We re-read the CSV once here (a 100
    # row file) so the metadata path is fully decoupled from the
    # generic enrichment above and a future refactor of one cannot
    # silently break the other.
    fp_cfg = _SOURCE_CSV_PATHS.get("fantasyProsIdp")
    fp_rel = fp_cfg.get("path") if isinstance(fp_cfg, dict) else (fp_cfg or "")
    if fp_rel:
        fp_path = repo / fp_rel
        if fp_path.exists():
            try:
                fp_meta_lookup = _parse_fp_meta_csv_cached(fp_path)
                for row in players_array:
                    nm = str(row.get("canonicalName") or row.get("displayName") or "")
                    if not nm:
                        continue
                    key = _canonical_match_key(nm)
                    if not key:
                        continue
                    meta = fp_meta_lookup.get(key)
                    if meta is None:
                        continue
                    # Only stamp FP metadata on rows that actually
                    # received a FantasyPros enrichment value — the
                    # generic loop above already validated the
                    # name/position match cascade.
                    csv_vals = row.get("canonicalSiteValues")
                    if not isinstance(csv_vals, dict):
                        continue
                    if not csv_vals.get("fantasyProsIdp"):
                        continue
                    for k, v in meta.items():
                        row[k] = v
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("FantasyPros IDP metadata stamp failed: %s", exc)

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
        # Rookie-translation sources rank the CURRENT rookie class
        # only, so they are structurally expected for rookies alone —
        # never for veterans and never for pick rows.
        #
        # * Veterans (2026-07-25, Colston Loveland report): a
        #   second-year player is inside these sources' scope+depth
        #   window, so without this guard every vet near the top of
        #   the board showed "DLF RK / Flock RK: Expected but did not
        #   match" on the Source Audit panel — a structural
        #   impossibility misreported as a matching failure.
        # * Picks: ``dlfRookieSf`` does stamp synthetic ``2026 Pick
        #   R.SS`` entries into ``canonicalSiteValues`` for display,
        #   but the Phase 1 ordinal pass deliberately excludes picks
        #   (picks get their final value from the rookie-anchor pass,
        #   not from a per-source rookie rank).
        if src.get("needs_rookie_translation") and (not is_rookie or pos_up == "PICK"):
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

    The spread is the max-minus-min of those percentiles in 0..1 —
    TRIMMED when ``_PERCENTILE_SPREAD_TRIM_MIN_N`` or more sources
    contribute: the single most extreme percentile on each side is
    ignored, so a lone straggler source cannot flag an otherwise-tight
    consensus (see the constant's docstring for the saturation audit
    that motivated this).  Returns ``None`` if fewer than two sources
    contributed.
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
    if len(pcts) >= _PERCENTILE_SPREAD_TRIM_MIN_N:
        pcts_sorted = sorted(pcts)
        return float(pcts_sorted[-2] - pcts_sorted[1])
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
_PICK_TIER_RE = re.compile(r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(st|nd|rd|th)$", re.I)

# Pick year discount is loaded once per build from
# config/weights/pick_year_discount.json.  See the file header for the
# config schema.  Cached at module level so a build that processes
# multiple snapshots only reads the file once.
_PICK_YEAR_DISCOUNT_CACHE: dict[str, Any] | None = None


def _load_pick_year_discount() -> dict[str, Any]:
    """Load and cache the pick year discount config.

    Returns a dict shaped like::

        {
            "currentDraftYear": 2027 | None,   # explicit override
            "rolloverMonth": 5,
            "rolloverDay": 15,
            "offsetDiscounts": {"0": 1.0, "1": 0.82, ...},
            "discounts": {"2026": 1.0, ...},   # legacy absolute, optional
            "baselineYear": 2026,              # legacy, optional
            "fallbackBase": 0.80,
        }

    The schema is OFFSET-from-current-draft-year so it never goes stale.
    The legacy absolute-year ``baselineYear``/``discounts`` keys are
    still read for backward compatibility when ``offsetDiscounts`` is
    absent.

    If the config file is missing or malformed, falls back to a built-in
    default (offset 0 = no discount, fallbackBase=0.80).  This keeps the
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
        "currentDraftYear": None,
        "rolloverMonth": 5,
        "rolloverDay": 15,
        "offsetDiscounts": {},
        "discounts": {},
        "baselineYear": None,
        "fallbackBase": 0.80,
    }
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            loaded = _json.load(f)
        if isinstance(loaded, dict):
            override = loaded.get("currentDraftYear")
            cfg["currentDraftYear"] = int(override) if override else None
            if loaded.get("rolloverMonth") is not None:
                cfg["rolloverMonth"] = int(loaded["rolloverMonth"])
            if loaded.get("rolloverDay") is not None:
                cfg["rolloverDay"] = int(loaded["rolloverDay"])
            raw_offsets = loaded.get("offsetDiscounts") or {}
            if isinstance(raw_offsets, dict):
                cfg["offsetDiscounts"] = {str(int(k)): float(v) for k, v in raw_offsets.items()}
            # Legacy absolute-year schema (back-compat only).
            base = loaded.get("baselineYear")
            cfg["baselineYear"] = int(base) if base else None
            raw_discounts = loaded.get("discounts") or {}
            if isinstance(raw_discounts, dict):
                cfg["discounts"] = {str(k): float(v) for k, v in raw_discounts.items()}
            cfg["fallbackBase"] = float(loaded.get("fallbackBase") or 0.80)
    except (OSError, ValueError, TypeError):
        # Stick with the built-in default — never block the build on
        # a missing/malformed pick-discount config.
        pass

    _PICK_YEAR_DISCOUNT_CACHE = cfg
    return cfg


# Set per-build from the raw scrape (see
# ``set_observed_current_draft_year``).  The year that still carries
# slot-specific ``YYYY Pick R.SS`` rows IS, by definition, the active
# rookie draft: vendors publish full slots for the next class and only
# generic tiers for further-out years.  This makes "current draft year"
# self-rolling — it advances the instant the data sources roll, with no
# config edit and no stale baseline.
_OBSERVED_CURRENT_DRAFT_YEAR: int | None = None

# Canonical names of pick rows synthesized by
# ``_inject_far_future_pick_sources`` for this build.  These are
# legitimately single-source (no vendor prices picks that far out), so
# the single-source safety gate allowlists them by name.
_SYNTHETIC_FAR_FUTURE_PICK_NAMES: set[str] = set()
_FAR_FUTURE_ALLOWLIST_REASON = (
    "synthetic_far_future_tier:no vendor prices picks this far out; "
    "cloned from the nearest published year and year-discounted "
    "(auto-pivots when sources publish this year)"
)

_PICK_SLOT_NAME_RE = re.compile(r"^\s*(20\d{2})\s+Pick\s+[1-6]\.\d{1,2}\s*$", re.I)


def _derive_current_draft_year_from_names(names: Any) -> int | None:
    """Lowest year with a slot-specific ``YYYY Pick R.SS`` name, or None.

    The lowest such year is the active draft — older classes have been
    drafted out of the source boards, further-out classes only have
    generic Early/Mid/Late tiers.
    """
    best: int | None = None
    try:
        iterator = iter(names)
    except TypeError:
        return None
    for nm in iterator:
        m = _PICK_SLOT_NAME_RE.match(str(nm))
        if not m:
            continue
        yr = int(m.group(1))
        if best is None or yr < best:
            best = yr
    return best


def set_observed_current_draft_year(year: int | None) -> None:
    """Record the data-derived active draft year for this build.

    Called once at the top of :func:`build_api_data_contract` from the
    raw scrape's slot-pick names so every downstream consumer
    (discount, rookie anchor, synthetic tether) agrees on one year.
    """
    global _OBSERVED_CURRENT_DRAFT_YEAR
    _OBSERVED_CURRENT_DRAFT_YEAR = int(year) if year else None


def _inject_far_future_pick_sources(
    players_by_name: dict[str, Any],
    current_year: int,
) -> int:
    """Seed raw source entries for far-future pick years the vendors
    don't publish yet, out to the deepest configured discount offset
    (``current_year + max(offsetDiscounts)``, e.g. 2029 when the active
    draft is 2026).

    KTC/DLF/etc. only price two future years.  The user trades picks
    further out than that, so for any missing year we clone the nearest
    *published* future year's generic-tier raw entries (Early/Mid/Late ×
    rounds) under the new year's names, copying only the per-source
    value keys.  These then ride the **entire** normal pipeline exactly
    like the real future-tier picks — blended, year-discounted (the
    extra year out is handled automatically by
    :func:`_pick_year_discount_for`), ranked, legacy-mirrored, and
    surfaced in the app view — with no special-casing downstream.

    Real source rows always win: a year that already has any generic
    tier entry is left untouched, so the moment vendors publish e.g.
    2029 this no-ops for that year ("pivot when sources add them").

    Returns the number of synthetic raw entries added.
    """
    global _SYNTHETIC_FAR_FUTURE_PICK_NAMES
    _SYNTHETIC_FAR_FUTURE_PICK_NAMES = set()
    cfg = _load_pick_year_discount()
    offsets = cfg.get("offsetDiscounts") or {}
    try:
        max_offset = max(int(k) for k in offsets) if offsets else 3
    except (TypeError, ValueError):
        max_offset = 3
    target_year = current_year + max(max_offset, 0)
    if target_year <= current_year:
        return 0

    years_with_tiers: set[int] = set()
    for key in list(players_by_name.keys()):
        m = _PICK_TIER_RE.match(str(key).strip())
        if m:
            years_with_tiers.add(int(m.group(1)))
    if not years_with_tiers:
        return 0

    added = 0
    for year in range(current_year + 1, target_year + 1):
        if year in years_with_tiers:
            continue  # real source rows exist — defer to them.
        template_year = next(
            (y for y in sorted(years_with_tiers, reverse=True) if y < year and y > current_year),
            None,
        )
        if template_year is None:
            continue
        for key in list(players_by_name.keys()):
            m = _PICK_TIER_RE.match(str(key).strip())
            if not m or int(m.group(1)) != template_year:
                continue
            new_name = key.replace(str(template_year), str(year), 1)
            if not new_name or new_name in players_by_name:
                continue
            entry = players_by_name[key]
            if not isinstance(entry, dict):
                continue
            # Copy only the per-source value keys; the pipeline
            # recomputes every ``_``-prefixed cached/derived field, and
            # the year-discount step steps this year down on its own.
            players_by_name[new_name] = {
                k: v for k, v in entry.items() if not str(k).startswith("_")
            }
            # Store the canonical match key (what the single-source
            # gate keys ``allowlistReason`` lookups on), not the raw
            # display name.
            _SYNTHETIC_FAR_FUTURE_PICK_NAMES.add(_canonical_match_key(new_name))
            added += 1
        years_with_tiers.add(year)
    return added


def current_rookie_draft_year(today: date | None = None) -> int:
    """Return the year of the upcoming/current rookie draft (offset 0).

    Single source of truth for "which rookie draft is the no-discount
    baseline".  Resolution order:

      1. ``currentDraftYear`` config override, if set (manual lever;
         ``null`` disables it).
      2. else the data-derived value recorded by
         :func:`set_observed_current_draft_year` — the lowest year that
         still has slot-specific ``YYYY Pick R.SS`` rows in the scrape.
         Self-rolls when the sources advance; no config edit, no stale
         baseline, board stays internally consistent.
      3. else a date-derived fallback (calendar year rolled to
         ``year + 1`` once *today* is on/after the configured
         ``(rolloverMonth, rolloverDay)`` boundary).  Only hit on a
         cold start with no scrape available, or in tests.

    ``today`` is injectable for deterministic tests.
    """
    cfg = _load_pick_year_discount()
    override = cfg.get("currentDraftYear")
    if override:
        try:
            return int(override)
        except (TypeError, ValueError):
            pass
    if _OBSERVED_CURRENT_DRAFT_YEAR:
        return _OBSERVED_CURRENT_DRAFT_YEAR
    if today is None:
        today = datetime.now(timezone.utc).date()
    roll_m = int(cfg.get("rolloverMonth") or 5)
    roll_d = int(cfg.get("rolloverDay") or 15)
    if (today.month, today.day) >= (roll_m, roll_d):
        return today.year + 1
    return today.year


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


def _pick_year_discount_for(
    year: int | None,
    cfg: dict[str, Any],
    *,
    current_draft_year: int | None = None,
) -> float:
    """Return the multiplicative discount for a pick year.

    Resolution (offset = ``year - current_draft_year``):

      * offset <= 0 (the upcoming/current draft or earlier) -> 1.0.
      * ``cfg['offsetDiscounts'][str(offset)]`` if present -> that value.
      * else legacy absolute ``cfg['discounts'][str(year)]`` if present
        (back-compat only) -> that value.
      * else ``fallbackBase ** offset``.

    ``current_draft_year`` is injectable for deterministic tests; it
    defaults to :func:`current_rookie_draft_year`.
    """
    if year is None:
        return 1.0
    if current_draft_year is None:
        current_draft_year = current_rookie_draft_year()
    offset = int(year) - int(current_draft_year)
    if offset <= 0:
        return 1.0
    fallback_base = float(cfg.get("fallbackBase") or 0.80)

    offset_discounts = cfg.get("offsetDiscounts") or {}
    raw = offset_discounts.get(str(offset))
    if raw is None:
        # Legacy absolute-year schema fallback (back-compat).
        raw = (cfg.get("discounts") or {}).get(str(year))
    if raw is not None:
        try:
            return max(0.05, min(1.0, float(raw)))
        except (TypeError, ValueError):
            pass
    return max(0.05, fallback_base**offset)


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


# ── Market-anchor corridor clamp ────────────────────────────────────────
# Designated PRIMARY market anchor sources per asset class.  KTC and
# IDPTC are the deepest retail value boards, so they define "market
# reality" for each universe.  Other sources can move the final value
# within the corridor — they just can't pull a player into a rank
# that contradicts market at a pathological level.
_MARKET_ANCHOR_BY_ASSET_CLASS: dict[str, str] = {
    "offense": "ktcSfTep",
    "idp": "idpTradeCalc",
}

# Fallback anchor chain per asset class.  When the primary anchor
# (KTC / IDPTC) doesn't list a player — common for deep prospects or
# freshly-drafted rookies — we fall through to additional value-based
# sources, then finally to a MEDIAN of valueContributions across all
# scope-eligible sources that DID list them.  Without this chain,
# Shavon-Revel-style single-source-only IDPs escape the clamp
# entirely and the IDP calibration's 3-4× DB bucket multipliers can
# inflate a 1500-point uncalibrated value into a top-50 finish.
_MARKET_ANCHOR_FALLBACKS: dict[str, list[str]] = {
    "offense": [
        "ktcSfTep",
        "idpTradeCalc",
        "dynastyDaddySf",
        "fantasyProsFitzmaurice",
        "yahooBoone",
    ],
    "idp": ["idpTradeCalc", "dlfIdp", "idpShow", "fantasyProsIdp"],
}

# Percentile at which we declare a drift "too extreme" and clamp it.
# 0.90 means: the worst 10% of drifts (relative to the market anchor)
# inside each confidence bucket get pulled back to the edge of that
# bucket's natural drift distribution.  Everything inside the top 90%
# of natural drifts is untouched.  Chosen over an arbitrary fixed
# percent so the band width adapts as the board's source set evolves.
_MARKET_CORRIDOR_PERCENTILE: float = 0.90
# Minimum sample per confidence bucket before we trust its own P90;
# below this we fall back to the overall board P90 so a tiny bucket
# can't get an unrepresentative band.
_MARKET_CORRIDOR_MIN_BUCKET_N: int = 30

# Hard ceiling on the corridor band per asset class.  The dynamic
# bucket-P90 still controls clamp behaviour for normal cases; this
# cap is a safety rail that prevents a wide bucket distribution from
# letting truly-extreme outliers escape the clamp entirely.
#
# IDP cap is 0.15 (±15% of IDPTradeCalc): IDPTC is the retail IDP
# market, so blended values that drift further than that aren't
# tradeable in real leagues regardless of how many other sources
# disagree.  Cases like a Vikings LB priced at 1,900 internal vs
# 3,600 on IDPTC (47% drift) clamp to the band edge (3,060) instead
# of riding through on a wide bucket P90.  Offense has no cap
# because offense rows are not clamped at all (see
# ``_apply_market_corridor_clamp`` — the clamp only contains the
# IDP calibration runaway; offense has no calibration post-pass).
_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS: dict[str, float] = {
    "idp": 0.15,
}


def _market_anchor_value_for_row(row: dict[str, Any]) -> float | None:
    """Return the primary market-anchor source value (KTC for offense,
    IDPTC for IDP) as a raw native-scale value, or None if missing.

    Kept for backwards-compat of call sites that only care about the
    canonical primary anchor.  The clamp pipeline uses
    :func:`_market_anchor_for_row` instead, which returns both value
    and source identity and falls back through the anchor chain.
    """
    sites = row.get("canonicalSiteValues")
    if not isinstance(sites, dict):
        return None
    asset_class = str(row.get("assetClass") or "")
    source_key = _MARKET_ANCHOR_BY_ASSET_CLASS.get(asset_class)
    if not source_key:
        return None
    raw = sites.get(source_key)
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return v


def _market_anchor_for_row(
    row: dict[str, Any],
) -> tuple[float | None, str | None]:
    """Return ``(anchor_value, anchor_source)`` for the corridor clamp.

    Resolution order:
      1. Primary anchor (KTC for offense, IDPTC for IDP) read from
         ``canonicalSiteValues`` as a native-scale value.  If the
         source is value-based, we also cross-check
         ``sourceRankMeta[source].valueContribution`` so the clamp
         math stays on the 0-9,999 scale.
      2. Secondary anchors from ``_MARKET_ANCHOR_FALLBACKS`` — the
         first source in the chain that has a ``valueContribution``
         on the row wins.
      3. Median of ``valueContribution`` across every source in the
         fallback chain that actually stamped a contribution.  This
         handles the "Shavon Revel" case: IDPTC didn't list him,
         but IDP Show did — pegging him to the single source's
         9,999-scale contribution is safer than no clamp at all,
         because unclamped the calibration's DB bucket multiplier
         can 4x him and he lands top-50 on pure single-source noise.

    Returns ``(None, None)`` when no source contributed at all —
    the caller should skip the clamp for that player.
    """
    asset_class = str(row.get("assetClass") or "")
    chain = _MARKET_ANCHOR_FALLBACKS.get(asset_class) or []
    if not chain:
        return None, None
    sites = row.get("canonicalSiteValues") or {}
    meta = row.get("sourceRankMeta") or {}
    if not isinstance(sites, dict):
        sites = {}
    if not isinstance(meta, dict):
        meta = {}

    # Stage 1+2: try each source in chain order, use its
    # ``valueContribution`` if present (always 0-9,999 scaled), else
    # fall back to the native ``canonicalSiteValues`` entry for the
    # primary anchor only (since that's guaranteed to be a value-based
    # source on a 0-9,999 scale).
    primary = _MARKET_ANCHOR_BY_ASSET_CLASS.get(asset_class)
    for source_key in chain:
        src_meta = meta.get(source_key)
        vc: float | None = None
        if isinstance(src_meta, dict):
            raw_vc = src_meta.get("valueContribution")
            try:
                vc_f = float(raw_vc) if raw_vc is not None else 0.0
            except (TypeError, ValueError):
                vc_f = 0.0
            if vc_f > 0:
                vc = vc_f
        if vc is None and source_key == primary:
            raw_site = sites.get(source_key)
            try:
                v_f = float(raw_site) if raw_site is not None else 0.0
            except (TypeError, ValueError):
                v_f = 0.0
            if v_f > 0:
                vc = v_f
        if vc is not None:
            return vc, source_key

    # Stage 3: median of per-source valueContribution across whatever
    # sources in the chain stamped a contribution.  Strictly
    # informational (labelled with a synthetic source key for audit).
    contributions: list[float] = []
    for source_key in chain:
        src_meta = meta.get(source_key)
        if not isinstance(src_meta, dict):
            continue
        raw_vc = src_meta.get("valueContribution")
        try:
            vc_f = float(raw_vc) if raw_vc is not None else 0.0
        except (TypeError, ValueError):
            vc_f = 0.0
        if vc_f > 0:
            contributions.append(vc_f)
    if len(contributions) >= 2:
        contributions.sort()
        n = len(contributions)
        med = (
            contributions[n // 2]
            if n % 2 == 1
            else (contributions[n // 2 - 1] + contributions[n // 2]) / 2.0
        )
        return med, f"median_of_{n}"
    if len(contributions) == 1:
        return contributions[0], "single_source_fallback"
    return None, None


def _percentile(sorted_vals: list[float], p: float) -> float:
    """Nearest-rank percentile on a pre-sorted list."""
    if not sorted_vals:
        return 0.0
    idx = int(round((len(sorted_vals) - 1) * max(0.0, min(1.0, p))))
    return float(sorted_vals[idx])


def _apply_market_corridor_clamp(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Clamp blended values that have drifted further from the market
    anchor than the 90th percentile of natural drift within each
    confidence bucket.

    Rationale: with 19 sources, extreme disagreements (e.g. FG + DS
    pricing an elite edge on their combined offense+IDP pool at rank
    300, while IDPTC + DLF IDP + IDP Show + FP IDP price him top-10)
    can pull a player's final rank hundreds of slots from where the
    market anchor alone would place him.  The clamp leaves the blend
    alone for players whose drift sits inside the naturally-observed
    distribution, but pulls back the tail outliers to the edge of
    that distribution.

    Band width is empirical — P90 of ``|final - market| / market``
    computed within each confidence bucket on THIS board build.
    Buckets with fewer than _MARKET_CORRIDOR_MIN_BUCKET_N players
    fall back to the overall board P90 so small-sample noise can't
    set an unrepresentative band.

    Stamps ``marketCorridorClamp`` on every clamped row so the UI
    and audit code can see original value, clamped value, anchor,
    direction, and which source provided the anchor.

    Offense is exempt.  The corridor clamp exists solely to contain
    the IDP calibration post-pass's 3-4x DB-bucket multipliers (the
    Shavon-Revel / Vikings-LB runaway).  The offense path has no
    post-blend calibration, so anchoring offense to KTC (which bakes
    in its own TE-premium) only fights the league TE-premium
    multiplier: a non-TEP single source + the 1.25x TE boost would
    drift past the KTC band and get clamped straight back, silently
    cancelling the premium.  Offense values are the pure blend
    output; only IDP rows are clamped.
    """
    # Gather drift values per confidence bucket.
    by_bucket: dict[str, list[float]] = {}
    overall: list[float] = []
    drifts: list[tuple[dict[str, Any], float, float, str]] = []
    for row in players_array:
        if not row.get("canonicalConsensusRank"):
            continue
        if str(row.get("assetClass") or "") == "offense":
            continue
        anchor, anchor_source = _market_anchor_for_row(row)
        if anchor is None:
            continue
        try:
            value = float(row.get("rankDerivedValue") or 0.0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue
        drift = abs(value - anchor) / anchor
        bucket = str(row.get("confidenceBucket") or "low")
        by_bucket.setdefault(bucket, []).append(drift)
        overall.append(drift)
        drifts.append((row, value, anchor, anchor_source or ""))

    if not overall:
        return

    # ── The per-bucket empirical band vs the cap ──────────────────
    #
    # This computes a P90 drift band per confidence bucket; the cap
    # below (``_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS``) then reduces
    # it.  On the live board the cap wins EVERY time — measured on the
    # pinned 2026-07-30 contract, all 128 clamped rows carry
    # ``bandPct: 0.15`` and ``cappedByMaxBand: True``, because the
    # empirical bands run ~3.3x the cap (high 0.523 n=29, low 0.513
    # n=174, medium 0.481 n=91, overall 0.510).
    #
    # That is NOT the same as the arithmetic being dead, and the
    # difference is worth stating because the first pass of this audit
    # got it wrong.  The percentile block is live machinery that the
    # current board's unusually wide IDP drift happens to dominate — on
    # a tighter board it binds immediately.  Verified rather than
    # assumed: a synthetic fixture with narrower disagreement produces
    # ``bandPct: 0.0217, cappedByMaxBand: False``.
    #
    # So the dominance is a property of today's market data, not of
    # this code, and it is deliberately NOT pinned by a test — such a
    # test would assert a fact about IDP drift and go red the first
    # time the sources agree more closely, which is noise rather than
    # signal.
    #
    # Whether 0.15 is the right cap is a live calibration question
    # (it decides every clamp today) and belongs in
    # ``docs/open-modeling-decisions.md``, not in a silent re-tune here:
    # moving it moves real IDP values.
    overall_sorted = sorted(overall)
    overall_p90 = _percentile(overall_sorted, _MARKET_CORRIDOR_PERCENTILE)
    bucket_bands: dict[str, float] = {}
    for bucket, vals in by_bucket.items():
        if len(vals) >= _MARKET_CORRIDOR_MIN_BUCKET_N:
            bucket_bands[bucket] = _percentile(sorted(vals), _MARKET_CORRIDOR_PERCENTILE)
        else:
            bucket_bands[bucket] = overall_p90

    # Apply clamps.
    for row, value, anchor, source_key in drifts:
        bucket = str(row.get("confidenceBucket") or "low")
        band = bucket_bands.get(bucket, overall_p90)
        asset_class = str(row.get("assetClass") or "")
        max_band = _MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS.get(asset_class)
        capped_by_max = False
        if max_band is not None and band > max_band:
            band = max_band
            capped_by_max = True
        drift = abs(value - anchor) / anchor
        if drift <= band:
            continue
        # Clamp to the band edge, preserving direction.
        if value > anchor:
            clamped_f = anchor * (1.0 + band)
            direction = "down"
        else:
            clamped_f = anchor * (1.0 - band)
            direction = "up"
        clamped_int = int(round(clamped_f))
        if clamped_int <= 0:
            continue
        row["rankDerivedValue"] = clamped_int
        row["marketCorridorClamp"] = {
            "applied": True,
            "originalValue": int(round(value)),
            "clampedValue": clamped_int,
            "marketAnchor": int(round(anchor)),
            "marketSource": source_key,
            "bandPct": round(band, 4),
            "percentile": _MARKET_CORRIDOR_PERCENTILE,
            "confidenceBucket": bucket,
            "direction": direction,
            "cappedByMaxBand": capped_by_max,
            "maxBandPct": max_band,
        }
        # Mirror onto the legacy dict payload so the delta + full
        # contract views both see the clamped value.
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["rankDerivedValue"] = clamped_int
                pdata["marketCorridorClamp"] = dict(row["marketCorridorClamp"])


# ── Rank-change snapshot ────────────────────────────────────────────────
# Persists the last board's ranks so we can stamp per-player movement
# deltas on each subsequent build.  Stored as a small JSON file at
# ``data/snapshots/ranks_last.json``: ``{name: rank, ...}``.  Missing
# file = first run; nothing is stamped.  The snapshot is rewritten at
# the end of each non-delta build so the next build can diff against
# it.  Deltas: +N means the player moved UP N ranks since the last
# build; -N means down; None = newly ranked or previously unranked.
_RANK_SNAPSHOT_PATH: "Path | None" = None


def _get_rank_snapshot_path() -> "Path":
    from pathlib import Path as _Path

    global _RANK_SNAPSHOT_PATH
    if _RANK_SNAPSHOT_PATH is None:
        _RANK_SNAPSHOT_PATH = (
            _Path(__file__).resolve().parents[2] / "data" / "snapshots" / "ranks_last.json"
        )
    return _RANK_SNAPSHOT_PATH


def _stamp_rank_changes(
    rows: list[dict[str, Any]],
    *,
    write_snapshot: bool = True,
) -> None:
    """Diff each row's canonicalConsensusRank against the last-saved
    snapshot and stamp ``rankChange`` (positive = moved up).
    Optionally rewrite the snapshot file with the current ranks.

    ``write_snapshot=False`` is used on override / delta-payload
    builds so a user toggling sources on /settings doesn't clobber
    the canonical-board snapshot the scheduled scrape writes.  Reads
    always happen so the stamp is available on every build.
    """
    import json as _json

    snap_path = _get_rank_snapshot_path()
    previous: dict[str, int] = {}
    try:
        if snap_path.exists():
            previous = _json.loads(snap_path.read_text()) or {}
    except Exception:
        previous = {}

    current: dict[str, int] = {}
    for row in rows:
        name = str(row.get("canonicalName") or "")
        rank = row.get("canonicalConsensusRank")
        if not name or rank is None:
            continue
        try:
            cur_rank = int(rank)
        except (TypeError, ValueError):
            continue
        current[name] = cur_rank
        prev = previous.get(name)
        if isinstance(prev, int) and prev > 0:
            # Positive = moved UP (prev rank higher number, now lower
            # number).  A player at prev=50 who's now at 40 moved up
            # 10; change = 10.
            row["rankChange"] = prev - cur_rank
        else:
            row["rankChange"] = None

    if not write_snapshot:
        return
    try:
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(_json.dumps(current, separators=(",", ":")))
    except Exception:
        # Snapshot write failure is non-fatal — next build just
        # lacks diff data, exactly like first-run.
        pass


# ── Two-way player override ─────────────────────────────────────────────
# Canonical-name → alt-position-family mapping for players whose
# Sleeper classification undersells their real fantasy value because
# they're playable at BOTH an offense AND an IDP slot.  The classic
# case is Travis Hunter (listed WR in Sleeper, plays CB for the Jags;
# IDP-specialist sources rank him #1 among corners but he's invisible
# to the IDP blend because he sits in the offense pool).  For each
# entry we compute what his value WOULD be if he were classed under
# the alt-family (pulling ranks from the source's canonicalSiteValues
# synthetic entries) and use the maximum of that vs his offense-pool
# blend.  Sleeper's position is preserved for display + roster purposes.
#
# Scope: the boost ONLY helps when the player's Sleeper position
# places them outside a scope where their source coverage lives.
# Offense-classed with IDP source coverage is the canonical case.
# LB-classed rookies ranked as DE on IDP Show (Arvell Reese, David
# Bailey — audited 2026-04-21) are NOT in scope because they're
# already in the IDP pool and those sources already contribute to
# their blend via the IDP scope gate — no coverage is being missed.
# Edge rushers like Parsons / Watt / Burns are already classed DL
# in Sleeper so they flow through the correct bucket directly.
#
# Audit result (2026-04-21): Travis Hunter is the only player on
# the current board where offense-pool classification actively
# loses IDP-source coverage.  Other offense-classed players with
# IDP-source entries (Justin Madubuike, Milton Williams, etc.) are
# name collisions or low-signal cases and don't warrant a boost.
_TWO_WAY_PLAYERS: dict[str, str] = {
    # Travis Hunter — CU / JAX corner-WR two-way player.  Listed WR.
    "Travis Hunter": "DB",
}


def _apply_two_way_player_boost(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """For players in ``_TWO_WAY_PLAYERS``, compute what their value
    would be under the alt-position family and use max(offense, alt)
    as the final ``rankDerivedValue``.

    Most of the work is already done by the upstream CSV loader —
    when a source includes a two-way player under its IDP universe,
    the loader writes a synthetic rank-encoded value into
    ``canonicalSiteValues[source_key]`` even when the scope gate
    would later reject that contribution.  We pull those entries
    back out here and translate them onto the board's own scale.

    Stamps ``twoWayPlayerBoost`` on every boosted row with offense
    value, alt-family value, and max-of-two so the UI can surface
    the dual-value reality.

    WHY THE RANK PATH USES A LADDER AND NOT A DIRECT HILL
    ====================================================
    Until 2026-08-04 the rank branch did
    ``percentile_to_value((rank - 1) / (_PERCENTILE_REFERENCE_N - 1))``
    on the *raw within-source* ordinal.  That is a category error, and
    an expensive one.  ``_PERCENTILE_REFERENCE_N`` is a COMBINED-pool
    denominator: rank 5 in that coordinate system means "5th most
    valuable asset on the whole board".  But ``idpShow`` rank 5 means
    "5th best IDP", and the pipeline knows this — it deliberately
    leaves these sources ``None`` in ``effectiveSourceRanks`` for an
    offense-classed row, because the scope gate excludes them.  The
    boost reached around that gate and fed the untranslated ordinal
    straight into the combined-pool curve.

    Measured on the 2026-07-30 board, for the one player this affects:

        idpShow  rank 5   ->  9304   (the whole board's #1 is 9999)
        dlfIdp   rank 45  ->  4832
        idpTradeCalc      ->  5637   (a real value, already correct)
        mean              ->  6591   <- shipped, rank 31

    9304 is refuted directly by the board it claims to live on: the
    *actual* ``idpShow`` #1 (Aidan Hutchinson) is worth 6362, and #2-#4
    are 5876 / 5875 / 4803.  A top-5 IDP is worth ~4.8k-6.4k.  Nothing
    could disagree with the 9304 because no test asserted any part of
    this — the whole stage had one stamped audit field and no guard.

    So rank-signal sources now translate through a LADDER, the same
    shape ``_translate_via_ladder`` uses for rookie sources: collect
    (source rank, board value) over the real players of the alt family,
    sort by source rank, and interpolate.  That answers the only
    question worth asking — "what is a player this source ranks k-th
    actually worth on OUR board" — empirically, with no curve
    assumption at all.  Value-based sources (``idpTradeCalc``) are
    already on a directly comparable scale (CLAUDE.md's cross-market
    note: median value ratio 1.000 against KTC) and are untouched.

    Aggregation is ``count_aware_mean_median_blend`` — the pipeline's
    own step-9 combiner — rather than the plain mean this used before,
    so a two-way player's alt value is blended by the same rule as
    every other multi-source number on the board.

    WHAT THIS IS NOT
    ================
    It is still ``max(primary, alt)``.  In an IDP league that starts
    both WR and DB, a dual-eligible player's *production* is arguably
    additive — Sleeper scores a rostered player off their full stat
    line whatever slot they occupy, and this league pays for both
    (3 DB slots, live ``idp_*`` scoring).  That is a FUNDAMENTAL
    argument, and it belongs in BDVM, which already folds a two-way
    player's two stat lines into one projection record.  Encoding it
    here would mean inventing a premium on the market board with no
    market evidence behind it.  Market board reports the market; the
    /rankings Fund-gap column is where the disagreement shows up.
    """
    if not _TWO_WAY_PLAYERS:
        return

    # Collect IDP signal sources (the ones that could contribute to
    # an alt-family value for an offense-classed player).
    idp_source_keys = {
        str(s.get("key") or "")
        for s in _RANKING_SOURCES
        if s.get("scope") == SOURCE_SCOPE_OVERALL_IDP
    }
    # Same for offense sources — used when the alt-family is offense.
    offense_source_keys = {
        str(s.get("key") or "")
        for s in _RANKING_SOURCES
        if s.get("scope") == SOURCE_SCOPE_OVERALL_OFFENSE
    }

    alt_asset_class_for_family = {True: "idp", False: "offense"}

    def _build_alt_ladder(source_key: str, want_idp: bool) -> list[tuple[float, float]]:
        """(source rank, board value) pairs over the REAL players of the
        alt family, sorted by source rank.

        This is the empirical answer to "what is a player this source
        ranks k-th actually worth on our board", so it needs no curve
        and no percentile denominator — the board supplies both.
        """
        want_class = alt_asset_class_for_family[want_idp]
        pairs: list[tuple[float, float]] = []
        for r in players_array:
            if r.get("assetClass") != want_class:
                continue
            src_rank = (r.get("sourceOriginalRanks") or {}).get(source_key)
            board_value = r.get("rankDerivedValue")
            if src_rank is None or not board_value:
                continue
            try:
                pairs.append((float(src_rank), float(board_value)))
            except (TypeError, ValueError):
                continue
        pairs.sort()
        return pairs

    def _translate_rank_via_alt_ladder(
        rank: float, ladder: list[tuple[float, float]]
    ) -> float | None:
        """Linear interpolation of ``rank`` through the ladder.

        Clamps at both ends rather than extrapolating: past the ladder's
        depth we have no evidence, and inventing one is how the stage
        produced a 9304 in the first place.
        """
        if len(ladder) < 3:
            # Too little coverage to translate honestly.  Dropping the
            # source is correct — the alternative is the untranslated
            # ordinal, which is the defect.
            return None
        xs = [x for x, _ in ladder]
        ys = [y for _, y in ladder]
        if rank <= xs[0]:
            return ys[0]
        if rank >= xs[-1]:
            return ys[-1]
        i = bisect.bisect_left(xs, rank)
        x0, x1 = xs[i - 1], xs[i]
        y0, y1 = ys[i - 1], ys[i]
        if x1 <= x0:
            return y0
        return y0 + (y1 - y0) * ((rank - x0) / (x1 - x0))

    for row in players_array:
        name = str(row.get("canonicalName") or "")
        if name not in _TWO_WAY_PLAYERS:
            continue
        alt_family = _TWO_WAY_PLAYERS[name]
        alt_is_idp = alt_family in _IDP_POSITIONS
        candidate_keys = idp_source_keys if alt_is_idp else offense_source_keys
        site_values = row.get("canonicalSiteValues") or {}
        if not isinstance(site_values, dict):
            continue

        # Decode synthetic rank-encoded values back to ordinals.
        # The loader writes ``_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100
        # - rank * 100`` for rank-signal sources, so
        # ``rank = (offset * 100 - synthetic) / 100``.
        alt_source_values: list[float] = []
        used_sources: list[str] = []
        for key in candidate_keys:
            raw = site_values.get(key)
            try:
                syn = float(raw) if raw is not None else 0.0
            except (TypeError, ValueError):
                continue
            if syn <= 0:
                continue
            # Reverse the synthetic → rank encoding.  Small-positive
            # ``syn`` values (e.g. DraftSharks' raw 14 on a 0-100
            # scale) are VALUE-BASED source contributions; we skip
            # the rank decode path for those and use the value
            # directly, normalising by the source's native top
            # value for alt-family scale coherence.
            if syn < _RANK_TO_SYNTHETIC_VALUE_OFFSET * 50:
                # Native-value source: rank ≈ 1 if the raw is near
                # the source's top.  We approximate by scaling the
                # raw to a 0-9999 frame using the max value of the
                # source across the whole board.
                max_native = 0.0
                for r in players_array:
                    sv = (r.get("canonicalSiteValues") or {}).get(key)
                    try:
                        sv_f = float(sv) if sv is not None else 0.0
                    except (TypeError, ValueError):
                        continue
                    if sv_f > max_native:
                        max_native = sv_f
                if max_native > 0:
                    alt_source_values.append(syn / max_native * 9999.0)
                    used_sources.append(key)
                continue
            rank = int(round((_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100 - syn) / 100))
            if rank <= 0:
                continue
            # Ladder translation, NOT a direct Hill.  See the docstring:
            # this rank lives in the source's own within-family
            # coordinate system, and the combined-pool curve would read
            # it as a board-wide rank.  The ladder maps it onto the
            # board empirically instead.
            alt_val = _translate_rank_via_alt_ladder(
                float(rank), _build_alt_ladder(key, alt_is_idp)
            )
            if alt_val is not None and alt_val > 0:
                alt_source_values.append(alt_val)
                used_sources.append(key)

        if not alt_source_values:
            continue
        alt_value, _alt_mad = count_aware_mean_median_blend(alt_source_values)
        current_value = float(row.get("rankDerivedValue") or 0.0)
        if alt_value <= current_value:
            # Offense-pool blend already beats the alt-family value;
            # no boost needed.  Still stamp the audit so the UI can
            # show "no boost applied".
            row["twoWayPlayerBoost"] = {
                "applied": False,
                "altFamily": alt_family,
                "altFamilyValue": int(round(alt_value)),
                "primaryFamilyValue": int(round(current_value)),
                "sourcesConsidered": sorted(used_sources),
            }
            continue
        boosted = int(round(alt_value))
        row["rankDerivedValue"] = boosted
        row["twoWayPlayerBoost"] = {
            "applied": True,
            "altFamily": alt_family,
            "altFamilyValue": boosted,
            "primaryFamilyValue": int(round(current_value)),
            "sourcesConsidered": sorted(used_sources),
        }
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["rankDerivedValue"] = boosted
                pdata["twoWayPlayerBoost"] = dict(row["twoWayPlayerBoost"])


_DISPLAY_SCALE_MAX: int = 9999

# Reference pool size for percentile-to-value normalization under the
# Final Framework.  Per-source effective ranks (post-ladder) are
# normalized against this fixed denominator so every source's value
# contribution lives in the same combined-pool coordinate system.  500
# aligns with KTC's native pool, the retail market's natural scale;
# deeper ranks asymptote to the Hill's long tail.
#
# ALIAS, not a second declaration.  The reference population is owned by
# ``src/canonical/player_valuation`` along with the rank→percentile
# mapping itself, because fitting and holdout evaluation need the same
# number and a local copy is how they drifted apart (W30-F008).  The
# name survives for the many call sites that already read it.
_PERCENTILE_REFERENCE_N: int = _CANONICAL_PERCENTILE_REFERENCE_N


def _build_hill_curves_block() -> dict[str, dict[str, Any]]:
    """Stamp the four scope-level master Hill curves onto the contract.

    Mirrors the constants in ``src/canonical/player_valuation.py`` and
    the routing in ``_curve_for_source``.  Each entry carries:
        - ``c`` / ``s`` — raw percentile-form constants:
            V(p) = 9999 / (1 + (p / c)^s),  p = (rank − 1) / (N − 1)
        - ``referenceN`` — the denominator used to map rank → percentile
          (= ``_PERCENTILE_REFERENCE_N`` for GLOBAL/OFFENSE/IDP; rookie
          sources were historically fit against a rookie-only slice but
          the ROOKIE master is currently fit-only and not routed — see
          ``_curve_for_source`` — so we stamp the same reference N for
          consistency).
        - ``midpoint`` / ``slope`` — rank-form equivalents for callers
          (e.g. the frontend HillCurveExplorer) that evaluate in rank
          space: V(r) = 9999 / (1 + ((r − 1) / midpoint)^slope).
          ``midpoint = c * (referenceN − 1)``, ``slope = s``.
        - ``label`` — short human label for chart legends.
        - ``routed`` — whether the live ``_curve_for_source`` routing
          currently uses this curve.  ROOKIE is fit by the monthly
          refit workflow but not routed today.
    """
    from src.canonical.player_valuation import (  # noqa: PLC0415
        HILL_GLOBAL_PERCENTILE_C,
        HILL_GLOBAL_PERCENTILE_S,
        HILL_PERCENTILE_C,
        HILL_PERCENTILE_S,
        HILL_ROOKIE_PERCENTILE_C,
        HILL_ROOKIE_PERCENTILE_S,
        IDP_HILL_PERCENTILE_C,
        IDP_HILL_PERCENTILE_S,
    )

    ref_n = _PERCENTILE_REFERENCE_N
    denom = max(1, ref_n - 1)

    def _entry(key: str, label: str, c: float, s: float, routed: bool) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "c": float(c),
            "s": float(s),
            "referenceN": ref_n,
            "midpoint": round(float(c) * denom, 4),
            "slope": round(float(s), 4),
            "routed": routed,
        }

    return {
        "global": _entry(
            "global", "Global", HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S, True
        ),
        "offense": _entry("offense", "Offense", HILL_PERCENTILE_C, HILL_PERCENTILE_S, True),
        "idp": _entry("idp", "IDP", IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S, True),
        "rookie": _entry(
            "rookie", "Rookie", HILL_ROOKIE_PERCENTILE_C, HILL_ROOKIE_PERCENTILE_S, False
        ),
    }


# Final Framework step 8: subgroup shrinkage factor.
#
#     Final = Anchor + α · (SubgroupBlend − Anchor)
#
# The anchor is the global offense+defense source (IDPTC) — it
# determines each player's universal baseline value.  The subgroup is
# the trimmed mean-median of every other source that ranks the
# player.  α controls how much the subgroup is allowed to move the
# final value away from the anchor:
#
#   α = 0.0  → pure anchor (subgroup ignored)
#   α = 1.0  → pure subgroup (anchor ignored)
#   α intermediate → anchor-baseline with subgroup adjustment
#
# Originally tuned to α=0.30 in the PR 3 standalone sweep.  A 2D joint
# backtest over the α × λ grid after PR 4 (see
# ``reports/alpha_lambda_joint_backtest_full.md``) showed the true
# stability optimum sits at α=0 — the degenerate "ignore the 15 other
# sources, use IDPTC alone" solution — because any subgroup voice
# introduces day-to-day variance.
#
# α=0 is product-bad (it violates the declared "market consensus
# fit" optimization target in ``docs/architecture/optimization-target.md``;
# our values should reflect multi-source consensus, not a single
# source).  We pick the cheapest non-degenerate joint point
# (α=0.10, λ=0.10, VW 0.299) — the subgroup keeps 10% voice over the
# anchor baseline, which preserves meaningful multi-source signal
# while staying near the stability frontier (~2× worse than the
# degenerate optimum, tied for best among cells with α ≥ 0.10).
_ALPHA_SHRINKAGE: float = 0.10

# Final Framework step 6: volatility penalty weight.  Applied as
# ``final = center − λ·MAD`` where MAD is the mean absolute deviation
# of the trimmed source values around the trimmed mean.  A principled
# single constant, replacing the removed ±8% z-score stack.
#
# λ = 0.0 is a strict no-op (center value passes through unchanged).
# Larger λ penalizes high-disagreement players more.  MAD is in value-
# units (0-9999 scale), so λ=0.5 subtracts half the MAD from each
# player's value — a player with trimmed source values spanning
# {8000, 8500, 9000} has MAD ≈ 333 → penalty ≈ 167.
#
# Value chosen via ``scripts/backtest_mad_lambda.py`` against the 25
# daily snapshots in ``data/`` (see ``reports/mad_lambda_backtest_full.md``).
# Originally tuned to λ=0.5 in PR 2 (pre-hierarchical, pre-fallback).
# Joint 2D α × λ backtest after the full framework shipped (see
# ``reports/alpha_lambda_joint_backtest_full.md``) placed the optimum
# at λ=0.10 for the non-degenerate α=0.10 operating point.  At α=0.10,
# λ={0.05, 0.10} are tied on the value-weighted metric (VW 0.299);
# λ=0.10 is preferred because it imposes slightly more penalty on
# high-disagreement players (the whole point of the MAD step)
# without measurable stability cost.
# **Retired 2026-04-20 (Final Framework override):** the count-aware
# mean-median blend (drop max+min at n≥5, untrimmed at n=3-4) is
# already a disagreement-damping mechanism on offense rows, and the
# anchor + α-shrinkage hierarchical blend is already damping on IDP /
# pick rows.  Keeping λ·MAD on top stacks two penalties on the same
# signal (spread between sources) and hides the real movement when a
# board shifts.  Setting λ=0 keeps the ``sourceSpread`` diagnostic
# stamp (useful on the frontend value-chain panel) but applies zero
# penalty to ``rankDerivedValue``.  If a new non-duplicative
# conservatism layer is ever needed, reinstate it here with a fresh
# backtest.
_MAD_PENALTY_LAMBDA: float = 0.0

# Single-source confidence haircut.  A player whose blended value rests
# on a single contributing source (after Hampel filtering) has no
# corroboration — one list can place a player anywhere with zero
# cross-checks, which was producing inflated, untrustworthy values
# (and "weird" waiver/board entries).  Such a row keeps its place in
# the database (it may still be a real rostered player) but its
# ``rankDerivedValue`` is multiplied by this factor — a heavy haircut
# so the low confidence is reflected in the number itself, not just
# the confidence bucket.  Applied to the pre-sort blended value so the
# board rank and the displayed value stay consistent.  Picks are
# exempt: they ride their own CV-based confidence path and a single
# value-source (KTC per-slot synth) is structurally normal for them.
_SINGLE_SOURCE_VALUE_RETENTION: float = 0.30

# Registry of sources whose raw per-player CSV value should be used
# as a **direct normalized vote** in the Phase 2-3 blend, instead of
# being re-modelled through the Hill/scope-master curve.  The user's
# Final Framework override (2026-04-20) is: value-based sites feed
# their real dollar-equivalent values straight into the aggregation;
# rank-only sites continue through rank → percentile → Hill.
#
# For a source's direct vote we take
# ``canonicalSiteValues[key] / site_max × 9999`` so every site's top
# player contributes 9999 and relative shape is preserved.
#
# Excluded on purpose: ``draftSharks`` and ``draftSharksIdp``.  DS
# publishes offense and IDP on one cross-market scale (top offense
# player = 100 3D Value+; top IDP = 44), but the CSVs are split by
# position family and the scale goes negative for ~50% of rows (211
# SF, 252 IDP).  Direct per-CSV normalization would both erase DS's
# native offense/IDP ratio and mis-handle negatives.  Instead, the
# blend merges the two CSVs into one cross-market rank list (see
# ``ds_combined_rank_partner`` in the registry) and routes that
# combined rank through the GLOBAL Hill master — the same curve
# IDPTC's anchor contribution uses.
# ── DraftSharks combined-rank exemption ─────────────────────────────────
# Derived from the registry at import time.  These sources publish a
# cross-market ``3D Value +`` scale that legitimately goes negative
# past ~rank 200 (the CSV tail), so the enrichment + Phase 1 ordinal
# gates relax their strict ``val > 0`` check for them.  Keeping this
# as a module-level set (rather than recomputing it inside each gate)
# avoids hot-path repetition and keeps the two gates in lockstep —
# if someone adds a new negative-scale source to the registry they
# only have to flip ``ds_combined_rank_partner``.
_DS_COMBINED_RANK_KEYS: frozenset[str] = frozenset(
    str(src.get("key") or "") for src in _RANKING_SOURCES if src.get("ds_combined_rank_partner")
)


_VALUE_BASED_SOURCES: frozenset[str] = frozenset(
    {
        # ``ktcSfTep`` carries native 0-9999 values from KTC's TE+ sub-board.
        # Standard ``ktc`` was retired from the blend 2026-04-28 (its values
        # are still loaded into canonicalSiteValues for the arbitrage finder
        # + per-source winner display, but it no longer votes).
        "ktcSfTep",
        "idpTradeCalc",
        # ``dynastyDaddySf``, ``yahooBoone``, and ``fantasyProsFitzmaurice``
        # were moved to the rank-signal path 2026-04-22 after the Hampel
        # audit flagged 61% / 47% / 19% drop rates respectively — all three
        # have compressed top-of-curve value distributions (DynastyDaddy's
        # 10,200 cap with top 3 tied; Boone's 141 top with seven players
        # ≥110; Fitzmaurice's 0-101 scale with the top dozen bunched
        # 80-101) that the value-direct rescaling preserved unfaithfully.
        # See their ``_SOURCE_CSV_PATHS`` entries above for the full
        # rationale.  Fitzmaurice was reverted by an accidental PR #218
        # merge and restored here.
        #
        # ``fantasyCalc`` and ``otcffbSf`` followed the same road
        # 2026-07-25 — added as value-direct in May under a "well-spread
        # distribution" rationale, but their crowd/trade value curves
        # decay far faster than the KTC-anchored consensus, and the
        # weekly Hampel audit flagged both every single week they were
        # live (fantasyCalc 55-58%, otcffbSf 56% climbing to 86%).
        # Their ``_SOURCE_CSV_PATHS`` entries carry the full analysis.
    }
)


# ── D-1: out-of-range guard for the value-direct path ──────────────────
#
# The value-direct branch computes ``raw / site_max * 9999`` where
# ``site_max`` was an UNBOUNDED ``max()`` across every player.  One
# corrupt row therefore rescaled the entire board: a single
# ``ktcSfTep=99990`` (an extra digit — the most plausible scrape glitch
# on a 4-digit board) deflates EVERY other player by 45.3%, measured
# through ``build_api_data_contract`` on a 120-player board.  ``950000``
# gives 49.5%.  Ordering is preserved, so the damage is invisible:
# the board still looks correctly sorted, at roughly half value.
#
# ``_safe_num`` already blocks inf/nan/strings.  Nothing validated the
# declared numeric RANGE, which is the gap this closes.
#
# Policy (operator decision, 2026-07-27) — "B with a C escalation":
#
#   B. A single out-of-range row is dropped from the value-direct path
#      for that source only.  It falls through to the existing Hill
#      fallback, exactly as a missing value already does, so the player
#      keeps a vote and every other player is untouched.
#
#   C. If more than ``_VALUE_RANGE_ESCALATION_FRACTION`` of a source's
#      rows are out of range, that is not a glitch — it means the
#      vendor changed their scale.  Silently dropping most of a source
#      would be worse than either failing or passing, so the whole
#      source is suppressed from the value-direct path (it still votes
#      via rank→Hill) and the run is stamped for the operator.
#
# The ceiling is PER SOURCE, deliberately, not a global 9999.  Sources
# publish on their own native scales — ``dynastyNerdsSfTep`` tops out at
# 10256 today — so a hardcoded 9999 would be wrong the moment a
# differently-scaled board joins ``_VALUE_BASED_SOURCES``.  Only sources
# listed here are range-checked; anything else keeps prior behaviour.
_VALUE_SOURCE_DECLARED_MAX: dict[str, float] = {
    # KTC's TE+ sub-board and IDPTradeCalc both publish a native 0-9999
    # scale whose top asset is exactly 9999.  Verified against the live
    # board 2026-07-27: ktcSfTep max 9999 (Josh Allen), idpTradeCalc max
    # 9999 (Bijan Robinson), zero out-of-range rows on either.
    "ktcSfTep": 9999.0,
    "idpTradeCalc": 9999.0,
}

# Above this fraction of out-of-range rows, treat it as a scale change
# rather than a glitch and suppress the source (escalation C).
_VALUE_RANGE_ESCALATION_FRACTION: float = 0.02

# ...but never escalate on an underpowered sample.  Escalation C is a
# claim about the SOURCE ("its scale changed"), and a fraction computed
# over a handful of rows cannot support that claim: on a 4-row fixture a
# single glitch is 25% and would suppress a healthy source outright.
# Real boards carry 400-900 rows, where one bad row is ~0.2%.  Below
# this count we always take policy B (drop the row) regardless of the
# fraction.  Same discipline as ORCHESTRATION.md §2b — do not conclude
# from a sample that cannot distinguish the hypotheses.
_VALUE_RANGE_ESCALATION_MIN_ROWS: int = 50


def _partition_value_source_ranges(
    players_array: list[dict[str, Any]],
) -> tuple[dict[str, float], set[str], dict[str, dict[str, int]]]:
    """Compute per-source max over IN-RANGE values only, plus the D-1 verdicts.

    Returns ``(value_source_max, suppressed_sources, diagnostics)``:

    * ``value_source_max`` — max observed value per source, computed
      **excluding** out-of-range rows so one bad row cannot inflate the
      divisor and deflate the board.
    * ``suppressed_sources`` — sources whose out-of-range fraction
      exceeded ``_VALUE_RANGE_ESCALATION_FRACTION`` (escalation C).
    * ``diagnostics`` — per-source ``{"total", "outOfRange"}`` counts so
      the condition is observable rather than silent.
    """
    totals: dict[str, int] = {}
    out_of_range: dict[str, int] = {}
    value_source_max: dict[str, float] = {}

    for row in players_array:
        canonical_site_values = row.get("canonicalSiteValues") or {}
        if not isinstance(canonical_site_values, dict):
            continue
        for key in _VALUE_BASED_SOURCES:
            raw = canonical_site_values.get(key)
            if raw is None:
                continue
            try:
                raw_f = float(raw)
            except (TypeError, ValueError):
                continue
            totals[key] = totals.get(key, 0) + 1
            ceiling = _VALUE_SOURCE_DECLARED_MAX.get(key)
            if ceiling is not None and (raw_f < 0.0 or raw_f > ceiling):
                out_of_range[key] = out_of_range.get(key, 0) + 1
                continue
            if raw_f > value_source_max.get(key, 0.0):
                value_source_max[key] = raw_f

    suppressed: set[str] = set()
    diagnostics: dict[str, dict[str, int]] = {}
    for key, total in totals.items():
        bad = out_of_range.get(key, 0)
        diagnostics[key] = {"total": total, "outOfRange": bad}
        if (
            bad
            and total >= _VALUE_RANGE_ESCALATION_MIN_ROWS
            and (bad / total) > _VALUE_RANGE_ESCALATION_FRACTION
        ):
            suppressed.add(key)
            logging.error(
                "D-1 escalation: %s has %d/%d values outside its declared "
                "0-%s range (>%.0f%%) — suppressing its value-direct vote "
                "for this build; the source's scale has likely changed.",
                key,
                bad,
                total,
                _VALUE_SOURCE_DECLARED_MAX.get(key),
                _VALUE_RANGE_ESCALATION_FRACTION * 100.0,
            )
        elif bad:
            logging.warning(
                "D-1: dropped %d/%d out-of-range %s value(s) from the "
                "value-direct path; those rows fall back to rank->Hill.",
                bad,
                total,
                key,
            )
    return value_source_max, suppressed, diagnostics


def _value_is_in_declared_range(source_key: str, raw_f: float) -> bool:
    """True when ``raw_f`` sits inside ``source_key``'s declared range."""
    ceiling = _VALUE_SOURCE_DECLARED_MAX.get(source_key)
    if ceiling is None:
        return True
    return 0.0 <= raw_f <= ceiling


def _validate_value_based_sources_invariant() -> None:
    """Module-import safety rail: every source registered for VOTING
    in ``_RANKING_SOURCES`` whose CSV signal is ``value`` must either
    appear in ``_VALUE_BASED_SOURCES`` OR declare
    ``ds_combined_rank_partner`` (the cross-market ranking carve-out).

    Display-only loads (sources in ``_SOURCE_CSV_PATHS`` but NOT in
    ``_RANKING_SOURCES``) are exempt — they're read into
    ``canonicalSiteValues`` for trade-finder / per-source winner
    display only, and never enter the blend.  Standard ``ktc`` is the
    canonical example after the 2026-04-28 supersession.

    This guards against a new value source silently going through the
    Hill curve because someone forgot to add it to
    ``_VALUE_BASED_SOURCES``.
    """
    voting_keys: set[str] = {str(src.get("key") or "") for src in _RANKING_SOURCES}

    value_signal_keys: set[str] = set()
    for key, cfg in _SOURCE_CSV_PATHS.items():
        if key not in voting_keys:
            # Display-only load — bypass the value-path requirement.
            continue
        if isinstance(cfg, str):
            signal = "value"  # default for plain string entries
        elif isinstance(cfg, dict):
            signal = str(cfg.get("signal") or "value").lower()
        else:
            continue
        if signal == "value":
            value_signal_keys.add(key)

    combined_rank_exempt: set[str] = {
        src["key"] for src in _RANKING_SOURCES if src.get("ds_combined_rank_partner")
    }

    missing = value_signal_keys - _VALUE_BASED_SOURCES - combined_rank_exempt
    if missing:
        raise RuntimeError(
            f"Source(s) {sorted(missing)} have CSV signal=value in "
            f"_SOURCE_CSV_PATHS but are not in _VALUE_BASED_SOURCES "
            f"and do not declare ds_combined_rank_partner.  This means "
            f"they would silently go through the Hill curve instead of "
            f"voting with their raw values.  Either add them to "
            f"_VALUE_BASED_SOURCES or declare the cross-market "
            f"partner flag; see the ``draftSharks`` registry entry "
            f"for the carve-out pattern."
        )


# Fire the safety rail at import time — misconfigured registries
# fail the server boot rather than silently routing a value source
# through the Hill curve.
_validate_value_based_sources_invariant()


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
        row["confidenceLabel"] = "None — generic tier suppressed in favor of slot-specific picks"
        row["pickGenericSuppressed"] = True
        # Drop quarantine / single-source flags so the suppressed row
        # cannot accidentally trip the launch-readiness 1-src gate.
        row["isSingleSource"] = False
        row["isStructurallySingleSource"] = False
        row["anomalyFlags"] = []
        # Preserve the alias on the row itself for direct UI lookups.
        row["pickAliasFor"] = alias_target

    return aliases


# Rookie anchor: slot-specific picks in the current rookie-draft year are
# pinned to the top-N merged (offense + IDP) rookies so pick values in the
# rankings and trade calculator match the rookies they will become.
#
# League-size default: pick (round, slot) → rookie rank = (round-1)*N + slot,
# where N = the operator's Sleeper league roster count.  Resolved at runtime
# via :func:`_resolve_league_context`; the constant below is the fallback
# when the Sleeper fetch is unavailable (offline, bad league id, etc.).
# Only affects rows consumed via /api/data (rankings + trade calculator).
# /api/draft-capital is served by a separate code path (server.py::_fetch_draft_capital)
# that reads from the draft spreadsheet and is untouched by this pass.
_ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT = 12
_ROOKIE_ANCHOR_ROUNDS = 6

# TE-premium derivation from Sleeper ``bonus_rec_te``.
#
# Sleeper exposes the per-reception TE bonus as ``bonus_rec_te`` under
# the league's ``scoring_settings``.  A "TEP 1.5" league has bonus 0.5
# (TEs get 1.5 per reception vs the 1.0 the league awards everyone).
#
# The TE-premium value boost applied to non-TEP-native sources during
# the blend is derived linearly from that bonus:
#
#     tep_multiplier = 1.0 + bonus_rec_te * _TEP_DERIVATION_SLOPE
#
# The slope 0.30 is calibrated so the standard TEP-1.5 setup
# (bonus_rec_te == 0.5) lands at 1.15, which was the historical
# frontend default and represents a ~15% TE value bump.  Sleeper
# leagues without any TE bonus (bonus_rec_te == 0) derive tep == 1.0,
# which is a no-op on the blend — the canonical "clean" board.
#
# The derived value is clamped to the same [1.0, 2.0] range as the
# manual override so a misconfigured bonus (e.g. 3.0 per rec) can't
# pump TE values off the board.  Callers who pass an explicit float
# for ``tep_multiplier`` bypass the derivation entirely.
_TEP_DERIVATION_SLOPE = 0.30
_TEP_DERIVED_CLAMP_MIN = 1.0
_TEP_DERIVED_CLAMP_MAX = 2.0

# TEP-native source correction.
#
# TEP-native sources (Dynasty Nerds SF-TEP, Yahoo/Justin Boone SF-TEP)
# already bake a TE-premium boost into their raw rankings.  The
# non-TEP sources in the blend are value-corrected via
# ``tep_multiplier`` so their TE contributions match the league's
# actual scoring.  TEP-native sources were historically untouched,
# which is correct when the league matches the industry-standard
# TEP-1.5 assumption (``bonus_rec_te == 0.5`` → native multiplier
# 1.15).  But in a non-TEP league — or any league whose ``bonus_rec_te``
# diverges from 0.5 — TEP-native sources silently bias TE rankings
# in the opposite direction:
#
#   * Non-TEP league (bonus 0.0): native 1.15 baked in; league wants
#     1.00.  TEP-native sources over-price TEs by ~15%.
#   * Operator's league (bonus 0.31): native 1.15; league wants 1.093.
#     TEP-native sources over-price TEs by ~5%.
#   * Heavy-TEP league (bonus 1.0): native 1.15; league wants 1.30.
#     TEP-native sources UNDER-price TEs by ~13%.
#
# The correction factor ``tep_native_correction = tep_multiplier_effective
# / _TEP_NATIVE_ASSUMED_MULTIPLIER`` is applied to TEP-native source
# contributions for TE rows only, symmetric to the tep_multiplier
# applied to non-TEP sources.  Together they normalize every source
# to the league's actual TEP before the blend.
#
# The 1.15 assumption is the industry standard for "TEP-1.5" — the
# shape most TEP boards publish by default.  If a source's actual
# bake is known to differ (e.g. a hypothetical TEP-2.0 native board),
# the per-source registry entry could override this, but today we
# have no such source so a single module-level constant suffices.
_TEP_NATIVE_ASSUMED_MULTIPLIER: float = 1.15

# Blanket TE-value multipliers.  KTC is the canonical TE++ retail signal
# and is left untouched; every other source's TE values are scaled at
# blend time to align with KTC's TE++ baseline:
#
#   * TEP-native sources (KTC SfTep, IDPTC, DN SfTep, Yahoo Boone, FP
#     Fitzmaurice) — the source already publishes a TE-premium board,
#     so a small additional ``1.10×`` brings them up toward our league's
#     TE++ scoring.  This factor is hardcoded.
#   * Non-TEP sources (DLF, FBG, FP consensus, Flock, etc.) — no TEP
#     bake at all, so they need a larger boost.  The factor defaults
#     to ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` (1.15, below) but is
#     operator-tunable from ``/settings`` via the "TE Premium" slider;
#     the slider value flows through ``tep_multiplier`` on
#     POST /api/rankings/overrides and overrides the default for the
#     duration of that request.
#
# KTC is exempt regardless: both ``ktc`` (standard SF) and ``ktcSfTep``
# (KTC TE++) skip both factors.  ktc is mathematically
# ``is_tep_premium=False`` and would normally pick up the non-TEP
# multiplier; the exemption set below short-circuits that.
#
# ── CORRECTION 2026-07-26 (LI-7 / ADR-009).  READ BEFORE TUNING. ──
#
# This constant previously carried the justification:
#
#     "Sleeper's API does not expose bonus_rec_te for these leagues
#      (always 0.0), so the 'non-TEP fallback' is in practice the
#      platform default and must reflect TEP-1.5, not a generic 1.25."
#
# That inference is WRONG and is retracted.  ``bonus_rec_te: 0.0`` is
# not unexposed data — it is a real, exposed zero.  The API reports the
# key faithfully; the primary league simply grants TEs no scoring
# premium in 2026.
#
# Proven empirically, not argued.  Running an identical receiving line
# through the deterministic scorer (``src/league_intel/scorer.py``,
# golden-validated to 0.011 against 1,415 host-awarded player-weeks):
#
#     2026 rates:  TE 21.55  vs  WR 21.55   → premium ×1.000
#     2025 rates:  TE 25.05  vs  WR 21.55   → premium ×1.162
#
# 2025 had ``bonus_rec_te 0.35`` / ``bonus_fd_te 1.35``; 2026 has
# ``bonus_rec_te 0.0`` / ``bonus_fd_te 1.0`` (identical to WR).  The
# commissioner removed the premium.  So on the SCORING axis this 1.15
# boost now prices a premium the league does not grant.
#
# The constant is deliberately LEFT AT 1.15 anyway — changing it moves
# live consensus values on the default board for every league sharing
# this scoring profile, which is a product decision, not a code one.
# Two things partly justify keeping it: TE demand here is structural
# (2 dedicated TE slots; measured starter demand exactly 2.00/team,
# and TE never wins a FLEX — see LI-5), and other leagues on this
# profile may still run a scoring premium.
#
# What must NOT happen: a league-adjusted TE correction computed on
# top of this multiplier.  That would double-count.  The LI-7 residual
# is netted against what this blend already embeds — see
# ``docs/league-intelligence/DECISIONS.md`` ADR-009 and the
# non-duplication test in ``tests/league_intel/``.
_TE_BLANKET_NON_NATIVE_MULTIPLIER: float = 1.15
_TE_BLANKET_NATIVE_MULTIPLIER: float = 1.10
_TE_BLANKET_KTC_EXEMPT_KEYS: frozenset[str] = frozenset({"ktc", "ktcSfTep"})

# ── WIRED 2026-07-27: the flat multiplier is now a measured curve ─────
#
# ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` above is retained as the FALLBACK
# and as the operator slider's default.  The live default path for
# non-TEP sources is now ``te_premium.convert_te_value(value,
# from_basis="base", to_basis=_BOARD_TE_BASIS)`` — KTC's own measured
# base → TE++ uplift, fitted from the two boards this repo already
# scrapes (``CSVs/site_raw/ktc.csv`` vs ``ktcSfTep.csv``, 73 paired TEs,
# R² 0.941 in log space).
#
# WHY THIS IS NOT A SECOND PREMIUM.  The blend anchors on ``ktcSfTep``,
# which IS KTC's TE++ board, and every non-TEP source's TE contribution
# was ALREADY being scaled to align with it.  What changes is only the
# magnitude of that existing alignment.  1.15 matched nothing observed
# anywhere in the data: KTC's smallest actual uplift is 1.209 and it
# reaches 2.053 down the board, so every tight end was under-lifted.
# The double-count guard is unaffected — KTC stays exempt, and
# ``convert_te_value`` is a no-op when ``from_basis == to_basis``, so
# asking to put a TE++ board on TE++ cannot move it.
#
# WHY THE TARGET BASIS IS A CONSTANT AND NOT THE LEAGUE'S.
# ``te_premium.measure_te_demand`` answers "which basis does THIS league
# need?" from roster structure — and that is a LEAGUE property, while
# this board is SCORING-PROFILE scoped and shared.  Measured on the live
# registry: ``dynasty_main`` (2 mandatory TEs) wants ``tepp`` and
# ``dynasty_new`` (1 TE) wants ``base``, and the two share the
# ``superflex_tep15_ppr1`` profile.  Threading league demand in here
# would let one league's roster shape reprice the other's board — the
# exact collapse CLAUDE.md's core split exists to prevent.  So the blend
# does Axis A only (align every source onto the basis the board is
# already anchored on) and Axis B belongs in the league-scoped overlay,
# ``src/league_intel/publish.py``, where ``tePremium`` is a named
# inactive axis.
#
# The operator's ``/settings`` TE-premium slider still wins: an explicit
# ``tep_multiplier`` bypasses the curve entirely, because a number the
# operator typed is a decision, not a measurement to be overruled.
#
# TEP-native sources keep the flat 1.10.  ``convert_te_value`` refuses
# any pair other than base <-> tepp — only those two KTC boards are
# published, so an intermediate "tep -> tepp" uplift would be invented
# rather than measured, and it raises instead of interpolating.
_BOARD_TE_BASIS: str = "tepp"
_TE_SOURCE_DEFAULT_BASIS: str = "base"

# Where the TE lift stops being linear and starts being squashed toward
# the scale ceiling.  See ``_te_lift_under_ceiling``.
_TE_LIFT_SOFT_KNEE: float = 9900.0


def _te_lift_under_ceiling(lifted: float, *, knee: float = _TE_LIFT_SOFT_KNEE) -> float:
    """Bring a lifted TE contribution under the 9,999 ceiling WITHOUT
    collapsing distinct votes onto it.

    Math audit 2026-07-30, finding C4.

    The TE premium is a value ratio measured on KTC's own two boards, and
    it is sound: across all 72 tight ends paired on both boards, applying
    it reproduces KTC's true TE++ ratio to a mean absolute error of 0.090.
    The problem is the ceiling.  A source's contribution is ``Hill(rank)``,
    and the Hill master is far steeper at the top than KTC's real value
    distribution — KTC ranks Brock Bowers 8th and values him 8153, while
    Hill maps rank 8 to 9076.  Lifting 9076 by 1.209 gives 10975, and
    ``min(..., 9999)`` then threw the overflow away.

    Measured on the live source CSVs, that clamp made six sources'
    top-TE votes IDENTICAL — fantasyCalc, pfkDynasty and dynastyDaddySf
    (rank 8), idpTradeCalc and dynastyNerdsSfTep (rank 7), otcffbSf
    (rank 14) all contributed exactly 9999.  Each was then casting the
    same vote for a tight end as for the #1 overall player, and the
    disagreement they actually published was erased rather than applied.
    Offense rows are exempt from the market-corridor clamp, so nothing
    downstream contained it either.

    A hard clamp is the wrong tool because it is not injective.  This is
    the same bound expressed as a strictly increasing map, so distinct
    inputs stay distinct:

        v <= knee      ->  v                       (exactly unchanged)
        v >  knee      ->  9999 - (9999 - knee) * exp(-(v - knee) / (9999 - knee))

    Continuous and C1 at the knee (both value and slope are 1:1 there),
    asymptotic to 9999 from below, and never reaching it — so a lifted
    tight end can approach the top asset on its source's board but never
    displace it.  That matches what KTC's own TE++ board does: Bowers
    lands 5th at 9859, not 1st.

    A REJECTED ALTERNATIVE, recorded because it was tried and measured:
    applying the premium as a RANK shift before the Hill call, fitted
    from the same paired boards (``scripts/audit/fit_ktc_te_rank_shift.py``,
    Bowers 8 -> 5, McBride 17 -> 8).  It is bounded by construction and
    cannot saturate, which is attractive.  But pushing a rank shift
    through the Hill curve does not recover the measured VALUE ratio,
    because the curve's shape is not KTC's value distribution: mean
    absolute error against KTC's own ratio was 0.175 versus 0.090 for the
    value-space conversion, and it was worse across the whole deep half
    of the board (at KTC base rank 496 the true ratio is 2.045; value
    space gives 1.633, rank space 1.122).  The value space is where the
    premium was measured and where it belongs; only the ceiling needed
    fixing.  The fitter is kept as the record of that measurement.

    Only the top ~1% of the scale is touched: below ``knee`` this is the
    identity, so every number the previous implementation produced below
    9900 is bit-for-bit unchanged.

    REACHABLE DOMAIN.  The largest lift this pipeline can produce is the
    scale ceiling times the uplift curve's floor, 9999 x 1.2092 = 12093:
    the curve is DECREASING in value, so the biggest contributions take
    the smallest multiplier, and the deep tight ends that take the 2.053
    ceiling multiplier start from small Hill values.  With a 99-wide span
    the squash stays strictly increasing in float64 out to ~12440, which
    covers that domain with margin.  Past ~12440 the exponential
    underflows and the map goes flat — so the result is additionally held
    one representable step below the ceiling, which keeps the "cannot
    displace the top asset" guarantee true even for an input this
    pipeline cannot currently generate.
    """
    v = float(lifted)
    ceiling = float(_DISPLAY_SCALE_MAX)
    if v <= knee:
        return v
    span = ceiling - knee
    if span <= 0:
        return min(v, ceiling)
    return min(ceiling - span * math.exp(-(v - knee) / span), ceiling - 1e-9)


# Cached Sleeper league context.  Populated on first call via the
# Sleeper /v1/league/{id} endpoint using ``SLEEPER_LEAGUE_ID`` from
# the env.  Stores the full resolved payload (roster count, TE-bonus,
# scoring format hash) so every pipeline knob can reference the same
# snapshot without a second HTTP round-trip.
# Refresh every hour so a mid-season league expansion (rare) or a
# switch to a different league eventually propagates without a restart.
_LEAGUE_CONTEXT_CACHE: dict[str, Any] = {
    "context": None,
    "fetched_at": 0.0,
}
_LEAGUE_CONTEXT_CACHE_TTL_SECONDS = 3600

# Back-compat alias — older revisions referenced the roster-only
# cache dict by this name.  Keeping the symbol (as a view of the new
# cache) avoids ImportError on any test helper that may patch it.
_LEAGUE_ROSTER_CACHE: dict[str, Any] = _LEAGUE_CONTEXT_CACHE
_LEAGUE_ROSTER_CACHE_TTL_SECONDS = _LEAGUE_CONTEXT_CACHE_TTL_SECONDS


def _resolve_league_context(
    default_roster_count: int = _ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT,
) -> dict[str, Any]:
    """Return the operator's Sleeper league context as a dict.

    Resolves the league ID **registry-first** —
    ``league_registry.get_sleeper_league_id()`` reads
    ``config/leagues/registry.json`` — and only falls back to the
    ``SLEEPER_LEAGUE_ID`` env var when the registry yields nothing
    (broken/absent registry module or no league configured).  Then
    fetches ``total_rosters`` + ``scoring_settings`` from Sleeper,
    cached for an hour.  Returns a dict with keys:

      * ``roster_count`` (int) — number of rosters in the league; the
        rookie-pick anchor uses this as N in ``(round-1)*N + slot``.
      * ``bonus_rec_te`` (float) — Sleeper's per-reception TE bonus
        (0.0 for leagues with no TE premium, 0.5 for standard TEP-1.5,
        1.0 for TEP-2.0, etc.).
      * ``fetched_from_sleeper`` (bool) — True when the dict reflects
        a live Sleeper fetch, False when it's a fallback dict.

    Returns a fallback dict (``roster_count=default``, ``bonus_rec_te=0.0``,
    ``fetched_from_sleeper=False``) if no league resolves at all, the
    fetch fails, or Sleeper returns an unusable payload — so the
    pipeline still produces output on a cold start / offline machine.

    Public helper so tests can patch it; no side effects beyond
    the cache fill.
    """
    import time as _time
    import urllib.request

    now = _time.time()
    cached = _LEAGUE_CONTEXT_CACHE.get("context")
    fetched_at = float(_LEAGUE_CONTEXT_CACHE.get("fetched_at") or 0.0)
    if isinstance(cached, dict) and cached.get("roster_count"):
        if (now - fetched_at) < _LEAGUE_CONTEXT_CACHE_TTL_SECONDS:
            return dict(cached)

    fallback: dict[str, Any] = {
        "roster_count": int(default_roster_count),
        "bonus_rec_te": 0.0,
        "fetched_from_sleeper": False,
    }

    # Resolve via the league registry first (reads registry.json when
    # present, falls back to the SLEEPER_LEAGUE_ID env var).  The
    # env-var fallback is what keeps existing deployments working
    # without touching config files.
    try:
        from src.api import league_registry as _league_registry  # local import avoids a cycle

        league_id = (_league_registry.get_sleeper_league_id() or "").strip()
    except Exception:  # noqa: BLE001 — if the registry module is broken, fall back to env var
        league_id = ""
    if not league_id:
        league_id = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
    if not league_id:
        # No league configured — return the fallback without populating
        # the cache so a later SLEEPER_LEAGUE_ID env change takes
        # effect on the next call.
        return fallback

    try:
        url = f"https://api.sleeper.app/v1/league/{league_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "dynasty-trade-calc"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.load(resp)
        size = int(data.get("total_rosters") or 0)
        scoring = data.get("scoring_settings") or {}
        if not isinstance(scoring, dict):
            scoring = {}
        try:
            bonus_rec_te = float(scoring.get("bonus_rec_te") or 0.0)
        except (TypeError, ValueError):
            bonus_rec_te = 0.0
        if not math.isfinite(bonus_rec_te) or bonus_rec_te < 0:
            bonus_rec_te = 0.0
        if size > 0:
            context = {
                "roster_count": size,
                "bonus_rec_te": bonus_rec_te,
                "fetched_from_sleeper": True,
            }
            _LEAGUE_CONTEXT_CACHE["context"] = context
            _LEAGUE_CONTEXT_CACHE["fetched_at"] = now
            # Back-compat: mirror roster count under the legacy key so
            # any caller that inspects the cache directly (tests) can
            # still see ``cache["size"]``.
            _LEAGUE_CONTEXT_CACHE["size"] = size
            return dict(context)
    except Exception:  # noqa: BLE001 — any failure falls back to default
        pass
    return fallback


def _resolve_league_roster_count(default: int = _ROOKIE_ANCHOR_LEAGUE_SIZE_DEFAULT) -> int:
    """Return the operator's Sleeper league roster count.

    Thin wrapper over :func:`_resolve_league_context` kept for
    backwards-compatibility with callers that only need the roster
    count (rookie pick anchor, DLF league-size gate).  New code
    should prefer ``_resolve_league_context()`` directly.
    """
    return int(_resolve_league_context(default).get("roster_count") or default)


def _derive_tep_multiplier_from_league(
    context: dict[str, Any] | None = None,
) -> float:
    """Derive the effective TE-premium multiplier from the league context.

    ``context`` is the dict returned by :func:`_resolve_league_context`;
    when ``None`` the function resolves it itself (same 1h cache).

    Formula: ``1.0 + bonus_rec_te * _TEP_DERIVATION_SLOPE``, clamped
    to ``[_TEP_DERIVED_CLAMP_MIN, _TEP_DERIVED_CLAMP_MAX]``.

    Returns ``1.0`` (a no-op on the blend) for any league with no TE
    bonus, and also when the Sleeper fetch fails — the pipeline falls
    back to the canonical "clean" board rather than silently
    inheriting a boost from a prior deployment.
    """
    ctx = context if isinstance(context, dict) else _resolve_league_context()
    try:
        bonus = float(ctx.get("bonus_rec_te") or 0.0)
    except (TypeError, ValueError):
        bonus = 0.0
    if not math.isfinite(bonus) or bonus < 0:
        bonus = 0.0
    derived = 1.0 + bonus * _TEP_DERIVATION_SLOPE
    if not math.isfinite(derived):
        return 1.0
    return max(_TEP_DERIVED_CLAMP_MIN, min(_TEP_DERIVED_CLAMP_MAX, derived))


def _anchor_current_year_picks_to_rookies(
    players_array: list[dict[str, Any]],
    anchor_year: int,
) -> int:
    """Override ``rankDerivedValue`` on slot-specific picks in ``anchor_year``
    so each pick inherits the value of its corresponding rookie.

    Rookie ordering is a merged list of offense + IDP rookies sorted by
    value descending.  Pick (round, slot) maps 1-indexed to rookie
    position = ``(round - 1) * N + slot`` where ``N`` is the operator's
    Sleeper league roster count (resolved via
    :func:`_resolve_league_roster_count`; falls back to 12 when the
    league configuration isn't available).

    To cover all ``_ROOKIE_ANCHOR_ROUNDS * N`` picks (e.g. 72 for a
    12-team league × 6 rounds), the pool includes rookies BEYOND the
    top-``OVERALL_RANK_LIMIT`` cut — they're sourced from
    ``_blendedValueUncapped`` when ``rankDerivedValue`` is zero.  This
    covers deep rookies whose values the Hill blend computed but who
    didn't survive the board cap; without it rounds 5 and 6 of the
    current-year pick board would run out of tether targets around slot
    53 and stamp ``rankDerivedValue=0`` on picks 5.06-6.12.

    Returns the number of picks anchored.  Callers are responsible for
    re-sorting the board by ``rankDerivedValue`` afterward so rank/value
    monotonicity (``assert_ranking_coherence``) is preserved.
    """
    league_size = _resolve_league_roster_count()

    def _rookie_pool_value(row: dict[str, Any]) -> int:
        primary = int(row.get("rankDerivedValue") or 0)
        if primary > 0:
            return primary
        return int(row.get("_blendedValueUncapped") or 0)

    rookies = [
        r
        for r in players_array
        if r.get("assetClass") != "pick" and bool(r.get("rookie")) and _rookie_pool_value(r) > 0
    ]
    if not rookies:
        return 0
    rookies.sort(
        key=lambda r: (
            -_rookie_pool_value(r),
            int(r.get("canonicalConsensusRank") or 99999),
        )
    )

    anchored = 0
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        parsed = _parse_pick_slot(row.get("canonicalName") or "")
        if parsed is None:
            continue
        year, rnd, slot = parsed
        if year != anchor_year:
            continue
        if not (1 <= rnd <= _ROOKIE_ANCHOR_ROUNDS):
            continue
        if not (1 <= slot <= league_size):
            continue
        idx = (rnd - 1) * league_size + (slot - 1)
        if idx >= len(rookies):
            continue
        anchor = rookies[idx]
        anchor_val = _rookie_pool_value(anchor)
        if anchor_val <= 0:
            continue
        # Anchor regardless of whether the pick itself survived the
        # Phase 4 OVERALL_RANK_LIMIT cap.  Picks lose their rank in
        # the Phase 5 compact pass anyway (they're proxies for the
        # corresponding rookie, not independent rank slots), so the
        # meaningful question is "does a matching rookie exist?".
        # Gating on the pick's own canonicalConsensusRank would leave
        # tail R4 picks unvalued whenever the cap tightens — e.g. when
        # an IDP Hill curve fit nudges a few deep IDP players up past
        # the cutoff, squeezing tail R4 picks off the bottom.
        row["rankDerivedValue"] = anchor_val
        row["pickRookieAnchor"] = anchor.get("canonicalName")
        anchored += 1
    return anchored


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
    for key in (
        "ktcSfTep",
        "idpTradeCalc",
        "dlfSf",
        "dynastyNerdsSfTep",
        "dlfIdp",
        "fantasyProsIdp",
    ):
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

    # KTC slot values on specific slots are partial evidence (the
    # underlying KTC pick board is the same whether we read its
    # standard or TE+ flavor — picks aren't TE-position-sensitive).
    effective_count = 0.0
    for key, _v in raw_values:
        if key == "ktcSfTep" and is_slot_specific:
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

    ONLY SYNTHESISED YEARS ARE DISCOUNTED (audit finding T-3/C-2,
    2026-08-04).  The discount used to apply to every future-year pick,
    including the years the vendors publish a real per-slot price for.
    That double-counts, and in the WRONG DIRECTION: both ingested pick
    markets price the next class ABOVE the imminent one, because the
    unknown class carries option value while the imminent one is priced
    to known prospects.  Measured on the 2026-08-04 boards::

        ktcSfTep      2026 Early 1st 5595 | 2027 7061 | 2028 5122
        idpTradeCalc  2026 Early 1st 5554 | 2027 7052 | 2028 5034

    The market term structure is +26% from 2026 to 2027 and then down;
    ``offsetDiscounts`` assumes a smooth 1.00/0.82/0.66/0.53 decay.
    Multiplying one onto the other published 2027 firsts 18% and 2028
    firsts 34% BELOW what both markets agreed on, which biased every
    trade involving future capital the same way: sell futures cheap,
    buy futures expensive.

    A vendor-priced year needs no correction — the price already
    encodes the term structure.  What DOES need the step-down is a year
    this pipeline invented by cloning a nearer year's values
    (``_inject_far_future_pick_sources``), because that clone carries
    the nearer year's price verbatim.  ``_SYNTHETIC_FAR_FUTURE_PICK_NAMES``
    is exactly that set, so it is the gate.

    NOTE this does not close audit finding V-12/C-11: for a synthesised
    year the multiplier is still an uncalibrated prior applied to a
    cloned price.  It closes only the double-count on real years.
    """
    cfg = _load_pick_year_discount()
    cdy = current_rookie_draft_year()
    discount_applied: dict[int, float] = {}
    out: list[tuple[float, int]] = []
    for value, row_idx in row_normalized:
        row = players_array[row_idx]
        if row.get("assetClass") == "pick":
            cname = row.get("canonicalName") or ""
            if _canonical_match_key(cname) not in _SYNTHETIC_FAR_FUTURE_PICK_NAMES:
                # Vendor-priced year: the market already priced the year.
                out.append((value, row_idx))
                continue
            year = _pick_year_from_name(cname)
            mult = _pick_year_discount_for(year, cfg, current_draft_year=cdy)
            if mult != 1.0:
                value = value * mult
                discount_applied[row_idx] = mult
                # Stamp on row for transparency
                row["pickYearDiscount"] = round(mult, 4)
        out.append((value, row_idx))
    return out, discount_applied


def _stamp_pick_value_projections(
    players_array: list[dict[str, Any]],
) -> None:
    """Stamp draft-day value projections on every pick row.

    The pick year discount (``config/weights/pick_year_discount.json``)
    deflates future-year picks below their on-draft equivalent — a
    2027 1st today is 82% of a 2026 1.01 because of one year of
    uncertainty + opportunity cost.  As the draft approaches, that
    discount unwinds: when 2027 becomes the baseline year, the same
    pick will be valued at 100% of a 1.01.

    This pass projects the on-draft value by inverting the discount:

        projected = rankDerivedValue / pickYearDiscount

    Stamps on each pick row:

      * ``pickProjectedDraftValue``     (int) — value at its own draft
      * ``pickProjectedDraftYear``      (int) — the year the pick is drafted
      * ``pickProjectedDraftValueGain`` (int) — projected − today (always ≥ 0)
      * ``pickProjectedDraftValueGainPct`` (int) — gain as percent of today

    Current-year picks (2026 baseline) project to their current value
    with zero gain — the discount is already 1.0, the pick is *at*
    its draft already.

    Tier-generic picks (e.g. ``2026 Early 1st``) get a projection too;
    the year is extracted from the name regardless of slot specificity.

    Run AFTER ``_anchor_current_year_picks_to_rookies`` so the
    projection sees the final ``rankDerivedValue`` (post-discount and
    post-rookie-anchor) for current-year slot picks.
    """
    for row in players_array:
        if row.get("assetClass") != "pick":
            continue
        rdv = row.get("rankDerivedValue")
        if not isinstance(rdv, (int, float)) or rdv <= 0:
            continue
        year = _pick_year_from_name(row.get("canonicalName") or "")
        if year is None:
            continue
        # ``pickYearDiscount`` is only stamped when the multiplier
        # diverges from 1.0; current-year picks land here with no
        # stamp and an effective discount of 1.0.
        try:
            discount = float(row.get("pickYearDiscount") or 1.0)
        except (TypeError, ValueError):
            discount = 1.0
        if discount <= 0 or discount > 1.0:
            discount = 1.0
        projected = int(round(float(rdv) / discount))
        gain = max(0, projected - int(rdv))
        gain_pct = int(round((gain / float(rdv)) * 100)) if rdv > 0 else 0
        row["pickProjectedDraftValue"] = projected
        row["pickProjectedDraftYear"] = int(year)
        row["pickProjectedDraftValueGain"] = gain
        row["pickProjectedDraftValueGainPct"] = gain_pct


def _hampel_filter_per_player(
    pairs: list[tuple[str, float]],
    *,
    k: float = _HAMPEL_K,
    min_n: int = _HAMPEL_MIN_N,
    min_threshold: float = _HAMPEL_MIN_THRESHOLD,
) -> tuple[list[tuple[str, float]], list[str]]:
    """Per-player Hampel outlier filter.

    Drops ``(source_key, value)`` pairs whose value deviates from the
    median by more than ``max(k · MAD, min_threshold)``.  Returns
    ``(kept_pairs, dropped_keys)`` with original ordering preserved.

    Safety guards (see module-level ``_HAMPEL_K`` docstring for the
    full rationale):
      * ``len(pairs) < min_n`` → return (pairs, []); median/MAD too
        unstable below 4 points to pick out an outlier reliably.
      * ``min_threshold`` floor on ``k · MAD`` — tight clusters like
        [4950, 5000, 5025, 5050, 5100] should not call values ±75 from
        the median "outliers" just because MAD happens to be small.
        The floor also handles the tied-cluster case where MAD is
        exactly zero (e.g. [9999, 9999, 9999, 2000]): the bulk agrees,
        MAD=0, but the lone 2000 is still 7999 from the median and
        exceeds the 500-Hill-point floor, so the outlier is correctly
        dropped — perfect agreement (all values identical) yields zero
        deviations and trivially keeps everything.
      * Filtering would leave fewer than 2 surviving pairs → return
        (pairs, []); never collapse a player to a single source via
        outlier rejection.

    MAD here is the *median* absolute deviation (the textbook Hampel
    statistic) — distinct from the *mean* absolute deviation that
    ``count_aware_mean_median_blend`` returns as its second tuple
    element for downstream λ·MAD penalty work.
    """
    n = len(pairs)
    if n < min_n:
        return list(pairs), []
    sorted_vals = sorted(v for _, v in pairs)
    if n % 2 == 1:
        median = float(sorted_vals[n // 2])
    else:
        median = (sorted_vals[n // 2 - 1] + sorted_vals[n // 2]) / 2.0
    deviations = sorted(abs(v - median) for _, v in pairs)
    if n % 2 == 1:
        mad = float(deviations[n // 2])
    else:
        mad = (deviations[n // 2 - 1] + deviations[n // 2]) / 2.0
    threshold = max(k * mad, min_threshold)
    kept: list[tuple[str, float]] = []
    dropped_keys: list[str] = []
    for sk, val in pairs:
        if abs(val - median) > threshold:
            dropped_keys.append(sk)
        else:
            kept.append((sk, val))
    if len(kept) < 2:
        return list(pairs), []
    return kept, dropped_keys


def count_aware_mean_median_blend(
    values: list[float],
) -> tuple[float, float | None]:
    """Framework step 9: count-aware mean-median blend.

    Returns (center, mad).  MAD is ``None`` for n=1.

    Rules by source count (updated 2026-04-20):

      n == 1   → passthrough (the single value)
      n == 2   → mean; MAD = half-range (= MAD of 2 around mean)
      n == 3-4 → UNTRIMMED mean-median blend
                 center = (mean + median) / 2
                 MAD computed over the full set
      n ≥ 5    → trimmed mean-median (drop one max + one min)
                 center = (trimmed_mean + trimmed_median) / 2
                 MAD computed over the trimmed set

    The prior implementation trimmed at n≥3 which over-compressed
    sparse IDP / rookie groups (n=3 collapsed to a single surviving
    source; n=4 to two).  The updated rule preserves robustness for
    high-coverage players (n≥5) while avoiding degenerate collapse
    for sparse coverage.
    """
    if not values:
        return 0.0, None
    sorted_vals = sorted(values)
    k = len(sorted_vals)
    if k == 1:
        return sorted_vals[0], None
    if k == 2:
        center = (sorted_vals[0] + sorted_vals[1]) / 2.0
        mad_val = abs(sorted_vals[0] - sorted_vals[1]) / 2.0
        return center, mad_val
    used = sorted_vals[1:-1] if k >= 5 else sorted_vals
    u_mean = sum(used) / len(used)
    m = len(used)
    if m % 2 == 1:
        u_median = float(used[m // 2])
    else:
        u_median = (used[m // 2 - 1] + used[m // 2]) / 2.0
    center = (u_mean + u_median) / 2.0
    mad_val = sum(abs(v - u_mean) for v in used) / len(used)
    return center, mad_val


def _weighted_median_sorted(pairs: list[tuple[float, float]], total_weight: float) -> float:
    """Weighted median over ``(value, weight)`` pairs pre-sorted by value.

    Standard cumulative-weight definition with midpoint interpolation
    on an exact half split: the smallest value whose cumulative weight
    reaches half the total; when the cumulative weight lands exactly on
    the half point, average with the next value.  With equal weights
    this reproduces the ordinary median (odd n → middle element, even
    n → mean of the two middle elements).
    """
    half = total_weight / 2.0
    cum = 0.0
    eps = 1e-12 * max(total_weight, 1.0)
    for i, (v, w) in enumerate(pairs):
        cum += w
        if cum > half + eps:
            return v
        if abs(cum - half) <= eps:
            if i + 1 < len(pairs):
                return (v + pairs[i + 1][0]) / 2.0
            return v
    return pairs[-1][0]


def weighted_count_aware_mean_median_blend(
    values: list[float],
    weights: list[float],
) -> tuple[float, float | None]:
    """Weighted variant of :func:`count_aware_mean_median_blend`.

    ``weights`` are the per-source DECLARED blend weights (registry
    defaults are all 1.0; user overrides arrive via
    ``POST /api/rankings/overrides``).  When every weight is equal —
    the default board and any uniform slider setting — this delegates
    to the unweighted blend, so the default output is bit-for-bit
    identical to the historical pipeline.

    With unequal weights the same count-aware shape applies, computed
    on weighted statistics:

      n == 1   → passthrough
      n == 2   → weighted mean; MAD = weighted abs deviation
      n == 3-4 → (weighted mean + weighted median) / 2, untrimmed
      n ≥ 5    → drop the single min / max OBSERVATION, then
                 (weighted mean + weighted median) / 2 over the rest

    Trimming stays observation-based (one max + one min by value,
    regardless of weight): the robustness rule targets extreme values,
    and keeping it observation-based preserves exact equal-weight
    parity with the unweighted blend.  Degenerate inputs (mismatched
    lengths, non-positive total weight) fall back to the unweighted
    blend rather than failing — a malformed override must never take
    down the board.
    """
    if not values:
        return 0.0, None
    if len(weights) != len(values):
        return count_aware_mean_median_blend(values)
    ws = [max(0.0, float(w)) for w in weights]
    if max(ws) - min(ws) <= 1e-9:
        # Equal weights (including the all-1.0 default): exact parity.
        return count_aware_mean_median_blend(values)
    pairs = sorted(zip(values, ws))
    k = len(pairs)
    if k == 1:
        return pairs[0][0], None
    used = pairs[1:-1] if k >= 5 else pairs
    total_w = sum(w for _, w in used)
    if total_w <= 0:
        return count_aware_mean_median_blend(values)
    w_mean = sum(v * w for v, w in used) / total_w
    if k == 2:
        center = w_mean
        mad_val = sum(abs(v - center) * w for v, w in used) / total_w
        return center, mad_val
    w_median = _weighted_median_sorted(used, total_w)
    center = (w_mean + w_median) / 2.0
    mad_val = sum(abs(v - w_mean) * w for v, w in used) / total_w
    return center, mad_val


def _compute_unified_rankings(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
    csv_index: dict[str, dict[str, dict[str, Any]]] | None = None,
    *,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
    tep_native_multiplier: float | None = None,
    tep_native_correction: float = 1.0,
    tep_multiplier_is_override: bool = False,
    suppress_market_corridor_clamp: bool = False,
) -> dict[str, str]:
    """Compute a single unified ranking across all sources and positions.

    Architecture
    ────────────
    Ranking is scope-aware.  Each registered source in ``_RANKING_SOURCES``
    declares one of three scopes:

      * overall_offense — ranks across QB/RB/WR/TE + picks
      * overall_idp     — ranks across DL/LB/DB together
      * position_idp    — ranks within a single IDP family (DL, LB, or DB)
                          — **scaffolding; no registered source uses it**

    ``position_idp`` is machinery that has never run.  No entry in
    ``_RANKING_SOURCES`` declares the scope, and a census of every
    ``sourceRankMeta`` stamp across the live board returns
    ``overall_offense: 5772, overall_idp: 965`` and **zero**
    ``position_idp``.  The per-position ladders below are still built and
    never read.  It is described here in the present tense because it
    would work if a source were registered — but "would work" and "does"
    are different claims, and this docstring made the second one.

    Were such a source registered, the raw positional rank would be
    translated through an IDP backbone (built from the best available
    overall_idp source) into a synthetic overall-IDP rank, so shallow
    top-20 lists could not pretend to be top-20 overall.  Note the
    branch is backbone-dependent, which is the same dependency
    ``consensus_edge.fair_value`` refuses on — see ADR-025.

    Per-source blending uses a coverage-aware weighted mean: shallow
    sources with small declared depth contribute less than deep full-board
    sources with identical declared weight.

    Source overrides
    ────────────────
    ``source_overrides`` (optional) is a dict of per-source user
    settings: ``{key: {"include": bool, "weight": float}}``.  Disabled
    sources are filtered out of every phase.  Overridden weights
    replace the registry-declared weight in the coverage-aware blend.
    When None / empty the pipeline is byte-for-byte identical to the
    default canonical run.

    TE Premium (``tep_multiplier`` + ``tep_native_multiplier``)
    ───────────────────────────────────────────────────────────
    League-wide TE premium normalization.  Applied as value-level
    multipliers during the Phase 2-3 blend to TE rows ONLY, in two
    independent passes (KTC / ktcSfTep exempt from both — KTC's TE++
    board is the canonical reference everyone else aligns to):

      * Sources flagged ``is_tep_premium=False`` (DLF, FantasyPros,
        Flock, etc.) price TEs for a standard league, so their TE
        contributions are lifted onto the basis this board is anchored
        on.  Since 2026-07-27 that lift is KTC's own MEASURED base →
        TE++ uplift curve
        (``src/league_intel/te_premium.convert_te_value``), which is
        rank-dependent: 1.209 at the top of the board rising toward
        2.05 down it.  The flat
        ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` = 1.15 remains as the
        fallback and as the operator slider's default, and an explicit
        ``tep_multiplier`` (slider, clamped [1.0, 1.5]) bypasses the
        curve.  ``RISKIT_FEATURE_TE_BASIS_CONVERSION=0`` restores the
        flat path.  See the ``_BOARD_TE_BASIS`` comment block for why
        the target basis is a constant rather than the league's own
        measured TE demand.
      * Sources flagged ``is_tep_premium=True`` (Dynasty Nerds
        SF-TEP, IDPTC) have their TE contributions multiplied by
        ``tep_native_multiplier`` (default
        ``_TE_BLANKET_NATIVE_MULTIPLIER`` = 1.10) — a smaller nudge
        from their already-TEP baseline up to our TE++ scoring.

    NOTE (2026-07-25 audit F-5): the earlier ratio-correction design
    (``tep_native_correction = tep_multiplier / 1.15``) is retired —
    the parameter is still accepted for backwards compatibility but
    acknowledged-unused; the two multipliers above are independent.

    Non-TE positions are untouched by either multiplier.  Boosted
    values clamp to the 9,999 scale ceiling.

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
    # The scope-master constants themselves are no longer named here —
    # ``rank_coordinates.curve_for_pool`` is the single place that maps
    # a coordinate pool to its ``(c, s)`` pair, so a second copy of the
    # mapping in this function is exactly the drift W02-F001 was.
    from src.canonical.player_valuation import (  # noqa: PLC0415
        percentile_to_value,
        rank_to_percentile,
    )

    # Updated framework (steps 5-6): route each rank to the master fit
    # on the population that rank counts within.
    #   shared offense+IDP pool → GLOBAL master
    #   offense (+ picks) pool  → OFFENSE master
    #   IDP-only pool           → IDP master
    #
    # The pool is stamped on the per-(row, source) meta by whichever
    # Phase-1 pass last established the effective rank, and
    # ``src/canonical/rank_coordinates.py`` owns the mapping.  It is
    # deliberately NOT re-derived from the source definition here: this
    # function used to read ``is_cross_market`` / ``scope`` off the
    # registry, which describes the source's NATIVE coordinates and
    # says nothing about the crosswalks the pipeline ran in between.
    # Sources flagged ``needs_shared_market_translation`` arrive with a
    # combined-market rank and were priced on the IDP slice anyway
    # (W02-F001), as did every IDP rookie rank translated through
    # ``idpTradeCalc``'s ladder in Phase 1d.
    #
    # ``needs_rookie_translation`` and the ROOKIE master used to gate
    # rookie-only sources through their own Hill curve fit against
    # rookie slices.  Retired 2026-04-21: rookie-only sources now go
    # through the Phase 1d ladder translation, so by the time they reach
    # this function their rank belongs to the reference ladder's pool.
    def _curve_for_rank(src_def: dict, meta: dict | None) -> tuple[float, float]:
        pool = str((meta or {}).get("rankCoordinatePool") or "")
        if not pool:
            # No pass claimed this rank.  Fall back to the source's
            # declared native pool rather than to a curve: that is the
            # honest reading of "nothing translated it", and it keeps a
            # future pass that forgets to stamp from silently landing on
            # GLOBAL for everything.
            pool = native_pool_for_source(src_def)
        return curve_for_pool(pool)

    # All sources (including rookie-only ones after Phase 1d ladder
    # translation) use the fixed combined-pool reference denominator.
    def _percentile_denom_for_source(src_def: dict, source_key: str) -> int:
        return _PERCENTILE_REFERENCE_N

    # Resolve the non-TEP-source TE multiplier.  ``None`` means the
    # caller did not supply a slider override, so use the operator's
    # default (``_TE_BLANKET_NON_NATIVE_MULTIPLIER``, 1.15 — the
    # platform's TEP-1.5 leagues; see the constant's docstring).  An
    # explicit float comes from the ``/settings`` "TE Premium" input
    # via :func:`normalize_tep_multiplier`, which clamps to [1.0, 1.5].
    # The TEP-native default (1.10) is operator-tunable too via
    # :func:`normalize_tep_native_multiplier`; KTC stays exempt.
    _ = tep_native_correction  # acknowledged-unused, kept for backwards-compat
    effective_non_tep_multiplier: float = (
        float(tep_multiplier) if tep_multiplier is not None else _TE_BLANKET_NON_NATIVE_MULTIPLIER
    )
    effective_native_multiplier: float = (
        float(tep_native_multiplier)
        if tep_native_multiplier is not None
        else _TE_BLANKET_NATIVE_MULTIPLIER
    )

    # Axis A — TE basis conversion (see the ``_BOARD_TE_BASIS`` block).
    # Active only when the flag is on AND the operator has not typed an
    # explicit slider value; a number the operator chose is a decision,
    # not a measurement to overrule.  Resolved ONCE here rather than per
    # row: this decides which of two branches the hot loop takes, and
    # re-deciding it 20,000 times would be both slow and a place for the
    # two paths to disagree.
    # ``tep_multiplier`` is NEVER None here — the caller always resolves
    # it to the operator's slider value, the Sleeper-derived value, or
    # the 1.15 default before calling.  So "did the operator choose a
    # number?" has to arrive as its own flag; testing the value for None
    # would gate on a condition that can never be true, which is exactly
    # the defect class §6.15 catalogues.
    #
    # The DERIVED value does not block the curve, deliberately.  It comes
    # from ``bonus_rec_te`` — the scoring axis ADR-009 retracted, and
    # which reads 0.0 for this league in 2026.  The basis question is
    # structural (how many TEs must be started), not a scoring key.
    te_basis_conversion = False
    _convert_te_value = None
    if not tep_multiplier_is_override:
        try:
            from src.api import feature_flags  # noqa: PLC0415

            if feature_flags.is_enabled("te_basis_conversion"):
                from src.league_intel.te_premium import (  # noqa: PLC0415
                    convert_te_value as _convert_te_value,
                )
                from src.league_intel.te_premium import load_tep_curve  # noqa: PLC0415

                # Warm the memoized curve outside the loop and prove the
                # conversion is callable before committing the hot path
                # to it — a lazily-discovered ImportError mid-blend would
                # take out the whole board.
                load_tep_curve()
                _convert_te_value(1000.0, from_basis="base", to_basis=_BOARD_TE_BASIS)
                te_basis_conversion = True
        except Exception as exc:  # noqa: BLE001
            # Degrade to the flat multiplier rather than serving no
            # board.  Loud, because a silent fallback here is
            # indistinguishable from the feature working.
            logging.warning(
                "TE basis conversion unavailable (%r); falling back to the flat "
                "%.2f multiplier for non-TEP sources",
                exc,
                _TE_BLANKET_NON_NATIVE_MULTIPLIER,
            )
            te_basis_conversion = False

    # Build the active source list honoring user-supplied overrides.
    # This is the only place ranks + weights are gated, so downstream
    # loops iterate `active_sources` instead of the raw registry.
    active_sources = _active_sources(source_overrides)
    active_keys = {str(s.get("key") or "") for s in active_sources}
    # Hoisted above Phase 1: the coordinate-pool bookkeeping in the
    # translation passes needs to look a source definition up by key.
    src_by_key: dict[str, dict[str, Any]] = {s["key"]: s for s in active_sources}

    # ── Phase 0: Build IDP backbone from the designated backbone source ──
    # The first enabled source with scope=overall_idp and is_backbone=True
    # wins.  With no backbone source the ladder is empty and every
    # crosswalk-dependent source falls back to treating its raw rank as a
    # synthetic overall rank, with a caution flag on the per-source meta.
    #
    # WHICH sources that actually affects, measured rather than assumed:
    # the ``needs_shared_market_translation`` ones — today ``dlfIdp``,
    # ``idpShow`` and ``fantasyProsIdp``, which flip method ``exact`` →
    # ``fallback`` on 159 / 235 / 177 rows of the live board.  The
    # ``position_idp`` branch below is ALSO backbone-dependent and is
    # currently dead: no registered source carries that scope, and a
    # census of every ``sourceRankMeta`` stamp across the 973-row live
    # board returns zero of them.  The facility works and is kept; it
    # simply has no users, so do not reach for it when explaining an
    # observed IDP scale problem.  See ``scale_integrity_lost`` and
    # ``shared_market_crosswalk_failed``.
    #
    # The backbone also carries a *shared-market IDP ladder* — the
    # combined offense+IDP ranks at which IDP entries appear in the
    # backbone source's value pool.  Non-backbone overall_idp sources
    # flagged with ``needs_shared_market_translation`` (e.g. DLF) use
    # this ladder as a crosswalk so their IDP-only rank 1 is translated
    # to the combined-pool rank of the best IDP, not treated as if it
    # were the overall rank 1 of the shared offense+IDP board.
    backbone_source_key: str | None = None
    for src in active_sources:
        if src["scope"] == SOURCE_SCOPE_OVERALL_IDP and src.get("is_backbone"):
            backbone_source_key = src["key"]
            break
    if backbone_source_key:
        # Only seed the shared-market ladder when the backbone source
        # actually prices both offense + IDP on a shared scale; this is
        # detected by the registry declaring offense in extra_scopes.
        backbone_src_def = next(
            (s for s in active_sources if s["key"] == backbone_source_key),
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

    # ── Rookie-translation ladders (built lazily on demand) ──
    # Sources flagged ``needs_rookie_translation=True`` (dlfRookieSf /
    # dlfRookieIdp / flockFantasySfRookies) rank the current rookie
    # class only.  Their raw
    # within-source rank 1 would otherwise be fed to the Hill curve
    # as if the #1 rookie were the #1 overall player — inflating every
    # rookie to value ~9999.  We crosswalk through a rookie ladder
    # built from a reference source's existing rank on real rookie
    # rows: ladder[k-1] = reference source's rank for the k-th best
    # rookie in the reference source's ORDER.  DLF's ORDER is
    # preserved via its own Phase 1 ordinal sort; only the SCALE
    # comes from the reference ladder.  Offense rookies anchor to
    # KTC; IDP rookies anchor to IDPTC (the IDP backbone).
    # NOTE: a SECOND, shadowed ``_build_rookie_ladder`` used to sit here,
    # together with the ``rookie_ladder_cache`` dict that was its only
    # consumer.  Both were dead — the sole call site is below, after the
    # surviving definition — and dead in a way that was a live hazard
    # rather than merely untidy: the two signatures were
    # ``(reference_src_key: str, idp: bool)`` and
    # ``(reference_source: str, universe_positions: set[str])``, so a
    # careless de-duplication would pass a set where a bool was expected.
    # Every non-empty set is truthy, so that mistake would silently route
    # offense rookies through the IDP ladder instead of raising.
    # Removal verified inert: the default board is byte-identical.
    for src in active_sources:
        source_key: str = src["key"]
        position_group: str | None = src.get("position_group")
        primary_scope: str = src["scope"]
        needs_shared_market = bool(src.get("needs_shared_market_translation")) and not src.get(
            "is_backbone"
        )
        needs_rookie_xlate = bool(src.get("needs_rookie_translation"))
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
        all_scopes: list[str] = [primary_scope] + list(src.get("extra_scopes") or [])

        # Gather eligible (value, row_idx, scope_for_row, tiebreak_name) tuples.
        # A row is eligible if any of the source's declared scopes accept
        # its position.  Offense and IDP position sets are disjoint, so
        # each row belongs to exactly one scope for a given source.
        eligible: list[tuple[float, int, str, str]] = []
        for idx, row in enumerate(players_array):
            pos = str(row.get("position") or "").strip().upper()
            if pos not in _RANKABLE_POSITIONS:
                continue
            # Rookie-only sources (dlfRookieSf) stamp synthetic
            # ``2026 Pick R.SS`` rows at CSV enrichment time so each
            # pick slot inherits the matched rookie's value (see the
            # ``Rookie source → synthetic pick-slot stamps`` block in
            # ``_enrich_from_source_csvs``).  Including those picks in
            # this Phase 1 ordinal sort interleaves them with the
            # rookies they tether to — each (rookie, pick) pair shares
            # a synthetic value, so dense-skip ranking gives them the
            # same rawRank.  That doubles every rookie's within-source
            # rank (rookie at CSV row k ⇒ rawRank 2k-1 instead of k),
            # which the Phase 1d rookie-ladder translation then maps
            # to a far deeper combined-pool rank than intended,
            # collapsing the rookie's Hill contribution and tripping
            # the per-player Hampel filter (audit caught dlfRookieSf
            # at 25% drop rate, 2026-04-27).  Picks get their final
            # value from the Phase 11 pick-anchor pass which reads the
            # rookie's blended ``rankDerivedValue`` directly, so
            # excluding them here costs nothing downstream.
            if needs_rookie_xlate and row.get("assetClass") == "pick":
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
            # DS combined-rank sources publish a cross-market scale
            # that goes negative past ~rank 200 (and can legitimately
            # hit zero).  Let those rows through so Phase 1 ordinal
            # sort places them at the tail of the pool — the DS
            # combined-rank pre-pass then re-ranks them in the merged
            # offense+IDP pool via the GLOBAL Hill master.  Every
            # other value-signal source treats ``val <= 0`` as
            # "unranked / missing" because their scales are strictly
            # non-negative.
            if val is None:
                continue
            if val <= 0 and source_key not in _DS_COMBINED_RANK_KEYS:
                continue
            tiebreak_name = str(row.get("canonicalName") or row.get("displayName") or "").lower()
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

        for rank_idx, (val, row_idx, row_scope, _name) in enumerate(eligible):
            # Dense ranking: tied values share the same rank.
            # e.g. values [10200, 10200, 10200, 10200, 9500] → ranks [1, 1, 1, 1, 5]
            if rank_idx == 0 or val != eligible[rank_idx - 1][0]:
                current_dense_rank = rank_idx + 1
            raw_rank = current_dense_rank

            # ── Self-correcting rookie exclusion ──
            # Sources flagged ``excludes_rookies=True`` (DLF IDP,
            # FantasyPros IDP today) are veteran-focused boards whose
            # rookie entries historically live at the deep tail of
            # the pool — placeholder filler rather than real
            # evaluations.  Stamping those placeholder ranks onto
            # rookie rows drags the blend down even though the board
            # doesn't really have an opinion.
            #
            # Rule (dynamic, not a hard flag): if the rookie's rank
            # inside THIS source's pool is in the bottom 20% of the
            # source's actual ranked depth, skip the contribution.
            # If the source starts ranking the rookie in its top 80%
            # (i.e. evaluating the player seriously), the stamp is
            # trusted again automatically.  No code change required
            # when DLF or FP start covering rookies properly — the
            # gate lifts on its own.
            row = players_array[row_idx]
            if src.get("excludes_rookies") and bool(row.get("rookie")):
                _pool_size = source_pool_sizes.get(source_key, 0)
                if _pool_size > 0 and raw_rank > _pool_size * 0.80:
                    continue

            # Translate to effective overall-style rank based on scope.
            # position_idp sources (shallow positional lists like DL-only)
            # still get backbone translation.  overall_* scopes — including
            # the cross-universe combined pool — pass through directly
            # unless the source is an IDP-only expert board that opts in
            # to the shared-market crosswalk (e.g. DLF).
            #
            # Each branch also records which COORDINATE POOL the
            # resulting rank counts within — see
            # ``src/canonical/rank_coordinates.py``.  That is what
            # Phase 2-3 routes the Hill curve on, so it has to record
            # what happened rather than what the registry promised: a
            # crosswalk that fell back left an IDP-local ordinal behind
            # and must keep the IDP master (W02-F001).
            ladder_depth_meta: int | None = None
            backbone_depth_meta: int | None = None
            native_pool = native_pool_for_source(src)
            rank_pool = native_pool
            if row_scope == SOURCE_SCOPE_POSITION_IDP and position_group:
                ladder = backbone.ladder_for(position_group)
                effective_rank, method = translate_position_rank(raw_rank, ladder)
                ladder_depth_meta = len(ladder)
                backbone_depth_meta = backbone_depth
                # ``ladder_for`` is numbered over IDP entries only, so a
                # successful lift lands in IDP-overall space — as does
                # the untranslated within-position fallback.
                rank_pool = RANK_POOL_IDP
            elif needs_shared_market and row_scope == SOURCE_SCOPE_OVERALL_IDP:
                # Crosswalk an IDP-only expert board's raw IDP ordinal
                # into the backbone source's combined offense+IDP rank
                # space.  The framework's step 2 percentile normalization
                # runs in this combined coordinate — see Phase 3.
                effective_rank, method = translate_position_rank(raw_rank, shared_market_ladder)
                ladder_depth_meta = len(shared_market_ladder)
                backbone_depth_meta = shared_market_depth
                if method != TRANSLATION_FALLBACK:
                    rank_pool = RANK_POOL_SHARED_MARKET
            elif needs_rookie_xlate:
                # Updated framework: rookie sources skip the ladder.
                # The ROOKIE master curve + native-N percentile
                # denominator together encode rookie-relative value
                # decay — no reference-source crosswalk needed.
                effective_rank = raw_rank
                method = TRANSLATION_DIRECT
                # Phase 1d re-stamps the pool when it translates through
                # a reference ladder.  Left alone, this rank is still a
                # within-class ordinal and keeps the source's native
                # pool — the pre-existing behaviour, tracked separately
                # as ``scale_integrity_lost``.
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
                # The OUTCOME, not the registry's intent.  This used to
                # read ``needs_shared_market and row_scope == overall_idp``
                # and so stamped True on rows whose crosswalk had fallen
                # back to the raw rank — a provenance field that lied in
                # exactly the case where provenance mattered.
                "sharedMarketTranslated": bool(
                    needs_shared_market
                    and row_scope == SOURCE_SCOPE_OVERALL_IDP
                    and method != TRANSLATION_FALLBACK
                ),
                "rankCoordinatePool": rank_pool,
            }

    # ── Phase 1b: DraftSharks cross-market combined ranking ──
    # DS publishes offense and IDP on one cross-market scale (top
    # offense = 100 3D Value+; top IDP = 44), but the CSVs are split
    # by position family.  Per-CSV ranking treats DS as two separate
    # sources, which erases DS's native ~56% offense premium.  We
    # fix that here: gather the raw DS values from BOTH sources'
    # players into one list, sort descending (negative values — ~50%
    # of the CSV — sort to the tail where the Hill curve produces
    # naturally low contributions), and overwrite each row's
    # effective rank for both DS sources with the combined-pool
    # rank.  Both sources then feed the GLOBAL Hill master via
    # ``_curve_for_source`` (the ``ds_combined_rank_partner`` flag
    # routes them there, same curve IDPTC's anchor contribution
    # uses).
    ds_partner_map: dict[str, str] = {
        str(s.get("key") or ""): str(s.get("ds_combined_rank_partner") or "")
        for s in active_sources
        if s.get("ds_combined_rank_partner")
    }
    if ds_partner_map:
        # Collect (raw_value, row_idx, source_key) for every covered
        # DS source entry across both halves of the pool.
        ds_pairs: list[tuple[float, int, str]] = []
        for row_idx, row in enumerate(players_array):
            csv_vals = row.get("canonicalSiteValues") or {}
            if not isinstance(csv_vals, dict):
                continue
            for skey in ds_partner_map:
                if skey not in row_source_ranks.get(row_idx, {}):
                    # Source didn't cover this row — leave it alone;
                    # it'll be counted via softFallbackCount.
                    continue
                raw = csv_vals.get(skey)
                try:
                    v = float(raw) if raw is not None else None
                except (TypeError, ValueError):
                    v = None
                if v is None:
                    continue
                ds_pairs.append((v, row_idx, skey))
        # Descending by raw value — top DS player (highest 3D Value+)
        # gets combined rank 1; DS-negative-value players sort to the
        # tail.  Stable tiebreak on (row_idx, skey) for determinism.
        ds_pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
        # The combined pool is only genuinely cross-market when BOTH
        # halves contributed rows.  With one partner disabled by an
        # override the "combined" pool is a single family, and the
        # re-ranked ordinal is exactly the within-family one — so it
        # takes that family's master, not GLOBAL.  On the default board
        # both halves are present and this resolves to shared market.
        ds_pools = {
            native_pool_for_source(src_by_key.get(skey, {})) for _v, _row_idx, skey in ds_pairs
        }
        ds_scopes = {
            str((src_by_key.get(skey) or {}).get("scope") or "") for _v, _row_idx, skey in ds_pairs
        }
        ds_combined_pool = (
            RANK_POOL_SHARED_MARKET
            if len(ds_scopes) > 1
            else (next(iter(ds_pools)) if len(ds_pools) == 1 else RANK_POOL_SHARED_MARKET)
        )
        for combined_rank, (_v, row_idx, skey) in enumerate(ds_pairs, start=1):
            row_source_ranks[row_idx][skey] = combined_rank
            meta = row_source_meta.setdefault(row_idx, {}).setdefault(skey, {})
            meta["rawRank"] = meta.get("rawRank", combined_rank)
            meta["effectiveRank"] = combined_rank
            meta["method"] = "ds_combined_cross_market"
            meta["rankCoordinatePool"] = ds_combined_pool

    # ── Phase 1c: FootballGuys cross-market combined rank restoration ──
    # FBG's CSVs natively carry the cross-market combined rank (Jack
    # Campbell at CSV rank 19 — first IDP in FBG's mixed offense+IDP
    # ordering).  Phase 1 dense-re-ranks each source's coverage 1..N
    # within-source, which clobbers that combined rank back to
    # within-family ordinals (Campbell = FG IDP rank 1).  This block
    # RESTORES the CSV rank by reversing the synthetic-value encoding
    # from the CSV enrichment reader:
    #   synthetic = (_RANK_TO_SYNTHETIC_VALUE_OFFSET * 100) − (rank * 100)
    # So ``csv_rank = _RANK_TO_SYNTHETIC_VALUE_OFFSET − (synthetic / 100)``.
    # Every ``is_cross_market=True`` source that carries a rank signal
    # natively (i.e. NOT routed through the DS combined-rank pre-pass
    # above) falls into this bucket.
    #
    # DORMANT AS OF 2026-07-29 (audit): this set is currently EMPTY and
    # the block below never executes.  All three cross-market sources
    # are excluded by construction — ``draftSharks`` / ``draftSharksIdp``
    # are ``ds_combined_rank_partner`` (handled by the pre-pass above)
    # and ``idpTradeCalc`` is value-direct.  The only members it ever
    # had were FootballGuys SF + FootballGuys IDP, which are no longer
    # registered sources.
    #
    # KEPT, not deleted: the logic is generic rather than FBG-specific,
    # it is guarded by the emptiness check so it costs nothing, and it
    # would correctly auto-activate for any future rank-signal
    # cross-market source.  The comment is what was misleading — it
    # named FBG as a current member long after the source was removed.
    csv_rank_cross_market_keys: set[str] = {
        str(s.get("key") or "")
        for s in active_sources
        if s.get("is_cross_market")
        and not s.get("ds_combined_rank_partner")
        # IDPTC is cross-market but value-direct, so no rank override
        # is needed — its direct-vote path reads canonicalSiteValues
        # raw values, not the effective rank.
        and str(s.get("key") or "") not in _VALUE_BASED_SOURCES
    }
    if csv_rank_cross_market_keys:
        for row_idx, row in enumerate(players_array):
            csv_vals = row.get("canonicalSiteValues") or {}
            if not isinstance(csv_vals, dict):
                continue
            for skey in csv_rank_cross_market_keys:
                if skey not in row_source_ranks.get(row_idx, {}):
                    continue
                synthetic = csv_vals.get(skey)
                if synthetic is None:
                    continue
                try:
                    syn_f = float(synthetic)
                except (TypeError, ValueError):
                    continue
                # Reverse the encoding to recover the original CSV rank.
                csv_rank = int(round(_RANK_TO_SYNTHETIC_VALUE_OFFSET - (syn_f / 100.0)))
                if csv_rank <= 0:
                    continue
                row_source_ranks[row_idx][skey] = csv_rank
                meta = row_source_meta.setdefault(row_idx, {}).setdefault(skey, {})
                meta["rawRank"] = meta.get("rawRank", csv_rank)
                meta["effectiveRank"] = csv_rank
                meta["method"] = "csv_combined_cross_market"
                # The restored CSV rank IS the source's native combined
                # offense+IDP rank — that is what makes this block
                # cross-market-only.
                meta["rankCoordinatePool"] = RANK_POOL_SHARED_MARKET

    # ── Phase 1d: Rookie-ladder translation ──
    # DLF Rookie SF / DLF Rookie IDP publish rookie-only boards (~50
    # rookies, within-class ranks 1..N).  Treated naively, DLF's #1
    # rookie ends up at percentile 0 on the ROOKIE Hill master,
    # producing a contribution of 9999 — i.e. "the #1 rookie is as
    # valuable as the #1 player overall", which is wrong.  In reality
    # the top rookie sits around overall rank 25-30 in the combined
    # market (per KTC/IDPTC's combined boards).
    #
    # This pre-pass (Fix B from the 2026-04-21 audit) translates each
    # rookie-source rank to a combined-pool rank via the reference
    # ladder:
    #
    #   * ``dlfRookieSf`` (offense rookies) → KTC ladder:
    #     DLF's #1 rookie → the rank KTC gives its #1 rookie.
    #     DLF's #2 rookie → KTC's #2 rookie-slot rank.  Etc.
    #
    #   * ``dlfRookieIdp`` (IDP rookies) → IDPTC ladder:
    #     DLF's #1 IDP rookie → IDPTC's top-rookie rank, etc.
    #
    #   * ``flockFantasySfRookies`` (offense rookies) → KTC ladder:
    #     same shape as dlfRookieSf — Flock's class-only ranks anchor
    #     to KTC's offense rookie ladder.
    #
    # Preserves each rookie source's within-class ORDERING while
    # calibrating the top-rookie's market value to the reference
    # source's opinion.  After this translation, the rookie source's
    # ``effective_rank`` is a combined-pool rank and the downstream
    # Hill conversion uses the OFFENSE/IDP master (not a special
    # ROOKIE master), which is what we want now that ranks are in
    # combined-pool space.
    #
    # Rookies past the reference ladder's depth are extrapolated
    # using the slope of the last ~10 ladder entries.
    def _build_rookie_ladder(reference_source: str, universe_positions: set[str]) -> list[int]:
        """Collect the reference source's ranks for every rookie in
        the relevant universe, sorted ascending (best rookie first).
        ``ladder[k - 1]`` is the combined-pool rank that the k-th
        rookie should translate to.
        """
        out: list[int] = []
        for idx, row in enumerate(players_array):
            if not bool(row.get("rookie")):
                continue
            pos = str(row.get("position") or "").upper()
            if pos not in universe_positions:
                continue
            ref_rank = row_source_ranks.get(idx, {}).get(reference_source)
            if ref_rank is None:
                continue
            try:
                out.append(int(ref_rank))
            except (TypeError, ValueError):
                continue
        out.sort()
        return out

    def _translate_via_ladder(rookie_rank: int, ladder: list[int]) -> int:
        """Map a within-class rookie rank k to the ladder's k-th
        entry.  Extrapolate past the ladder's depth using the slope
        across the last 10 entries (floor slope to 1.0 so ranks
        strictly increase).
        """
        if not ladder:
            return rookie_rank
        if 1 <= rookie_rank <= len(ladder):
            return ladder[rookie_rank - 1]
        # Past the ladder — linear extrapolation using the tail slope.
        tail_n = min(10, len(ladder))
        if tail_n < 2:
            slope = 1.0
        else:
            tail_start = ladder[len(ladder) - tail_n]
            tail_end = ladder[-1]
            slope = max(1.0, (tail_end - tail_start) / (tail_n - 1))
        extrapolated = ladder[-1] + int(round((rookie_rank - len(ladder)) * slope))
        return max(1, extrapolated)

    # Pair each rookie source with its reference ladder.  If the
    # reference source isn't active or has no rookie coverage, the
    # fallback is to leave the rookie source's rank untranslated
    # (it'll go through the Hill path with its within-class rank,
    # which is the pre-fix behaviour — safer than silently breaking).
    #
    # That fallback is safe on the DEFAULT board, where a missing
    # reference means a source we never had.  It is NOT safe on a board
    # built by deliberately excluding the reference — see
    # ``scale_integrity_lost``, which is the module-level declaration of
    # exactly this dependency.
    for rookie_key, ref_key, universe in ROOKIE_LADDER_PAIRS:
        if rookie_key not in active_keys or ref_key not in active_keys:
            continue
        ladder = _build_rookie_ladder(ref_key, universe)
        if len(ladder) < 3:
            # Not enough rookie coverage on the reference source to
            # translate reliably; skip and let the rookie source flow
            # through the normal Hill path below.
            continue
        # The ladder's entries ARE the reference source's effective
        # ranks, so a translated rookie rank lands in whatever pool the
        # reference occupies — offense for ``ktcSfTep``, shared market
        # for ``idpTradeCalc``.  That second case is the reason
        # W02-F001 is a translation problem rather than an IDP-source
        # one: no source flagged ``needs_shared_market_translation`` is
        # involved and the rank still arrives in combined coordinates.
        ref_pools = {
            str(meta_by_source[ref_key].get("rankCoordinatePool") or "")
            for meta_by_source in row_source_meta.values()
            if ref_key in meta_by_source and meta_by_source[ref_key].get("rankCoordinatePool")
        }
        ladder_pool = (
            ref_pools.pop()
            if len(ref_pools) == 1
            else native_pool_for_source(src_by_key.get(ref_key, {}))
        )
        for row_idx, rk_dict in row_source_ranks.items():
            if rookie_key not in rk_dict:
                continue
            orig = rk_dict[rookie_key]
            try:
                orig_int = int(orig)
            except (TypeError, ValueError):
                continue
            translated = _translate_via_ladder(orig_int, ladder)
            rk_dict[rookie_key] = translated
            meta = row_source_meta.setdefault(row_idx, {}).setdefault(rookie_key, {})
            meta["effectiveRank"] = translated
            meta["method"] = f"rookie_ladder_translation_via_{ref_key}"
            meta["rankCoordinatePool"] = ladder_pool

    # ── Phase 2-3: Normalized value (Hill curve) + robust blend ──
    # Look up each source's weight / depth once.  ``src_by_key`` itself
    # is built above Phase 1 — the translation passes need it too.

    # Declared blend weight per source (2026-07-29).  Registry defaults
    # are all 1.0, so the default board blends every covered source
    # with equal voice — bit-for-bit identical to the historical
    # unweighted pipeline (the weighted helper delegates to the
    # unweighted one when all weights are equal).  A user weight
    # override (``_active_sources`` copies the effective weight onto
    # the source dict) scales that source's vote in the count-aware
    # mean-median blend.  Weight ≤ 0 sources were already dropped by
    # ``_active_sources``.  NOTE: this is the DECLARED weight only —
    # the depth-based ``coverage_weight`` factor stays a stamped
    # diagnostic (``sourceRankMeta.effectiveWeight``) and is NOT
    # applied here; wiring it in would down-weight the three depth-50
    # rookie sources and change the default board.
    blend_weight_by_source: dict[str, float] = {
        str(s.get("key") or ""): max(0.0, float(s.get("weight") or 1.0)) for s in active_sources
    }

    # Cache which source keys are NOT TEP-native (non-TEP sources) and
    # which ARE TEP-native.  Both get a value-level correction on TE
    # rows during the Phase 2-3 blend, but with different multipliers:
    # non-TEP sources get boosted by ``tep_multiplier`` to the league
    # TEP; TEP-native sources get corrected by ``tep_native_correction``
    # away from their baked-in industry-standard 1.15 toward the
    # league's actual TEP.  Reading ``is_tep_premium`` off the
    # registry once avoids per-player dict lookups in the hot blend loop.
    tep_boosted_source_keys: set[str] = {
        str(s.get("key") or "") for s in active_sources if not bool(s.get("is_tep_premium"))
    }
    tep_native_source_keys: set[str] = {
        str(s.get("key") or "") for s in active_sources if bool(s.get("is_tep_premium"))
    }

    # Identify every cross-market source (2026-04-20 multi-anchor
    # upgrade).  Formerly a single ``is_anchor=True`` source (IDPTC)
    # with ~90% weight on IDP/pick rows; now every source flagged
    # ``is_cross_market=True`` — IDPTC, DraftSharks SF, DraftSharks
    # IDP, FootballGuys SF, FootballGuys IDP — contributes to the
    # anchor via a simple mean of their per-player value
    # contributions.  Each source prices offense and IDP on ONE
    # combined scale (IDPTC natively; DS via the combined-rank
    # pre-pass; FBG via the scraper's preserved combined rank), so
    # averaging their values is a straightforward cross-market
    # consensus.  Subgroup = every other source, α=0.10 against the
    # averaged anchor.  See the hierarchical-blend block further
    # down for the math.
    cross_market_keys, pick_anchor_keys = _anchor_key_sets(active_sources)

    # Final Framework override (2026-04-20): value-based sources vote
    # with their raw site values, normalized so each site's top player
    # contributes 9999.  Pre-compute each source's max observed value
    # from ``canonicalSiteValues`` across the full player set so a
    # single pass handles every row in the blend loop below.  We walk
    # ``canonicalSiteValues`` (not ``maxValues``) because the top-level
    # ``maxValues`` dict only tracks ktc + idpTradeCalc today; the other
    # value-based sources (dynastyDaddySf, draftSharks, draftSharksIdp)
    # carry their real values only inside the per-player dict.
    #
    # D-1: the max is computed over IN-RANGE values only, and a source
    # whose out-of-range fraction exceeds the escalation threshold is
    # suppressed from the value-direct path entirely.  See
    # ``_partition_value_source_ranges`` for the policy and the measured
    # failure it prevents.
    # ``_value_range_diagnostics`` is intentionally unused here: the
    # per-source counts reach operators through the WARNING/ERROR logs
    # emitted inside the helper, and reach CI through direct unit tests
    # on ``_partition_value_source_ranges``.  Threading them into the
    # return would change this function's published contract
    # (``dict[str, str]``) for a diagnostic, which is not worth it.
    (
        value_source_max,
        value_range_suppressed,
        _value_range_diagnostics,
    ) = _partition_value_source_ranges(players_array)

    _trimmed_mean_median = count_aware_mean_median_blend
    _weighted_trimmed_mean_median = weighted_count_aware_mean_median_blend

    row_normalized: list[tuple[float, int]] = []  # (blended_value, row_idx)
    for row_idx, source_ranks in row_source_ranks.items():
        row_pos = str(players_array[row_idx].get("position") or "").strip().upper()
        row_is_te = row_pos == "TE"
        row_is_pick = players_array[row_idx].get("assetClass") == "pick"

        # Framework step 2–3: for each source, compute
        # percentile-to-value using the source's scope-appropriate
        # master curve (updated framework step 5-6):
        #   - cross-market sources (IDPTC, DS SF/IDP, FG SF/IDP) →
        #     GLOBAL master (IDPTC uses value-direct, DS + FG use the
        #     combined rank → Hill path)
        #   - offense-scope sources       → OFFENSE master
        #   - IDP-scope sources           → IDP master
        # Then split contributions into cross-market anchor
        # contributions vs subgroup per step 7.
        cross_market_values: list[float] = []
        subgroup_values: list[float] = []
        all_values: list[float] = []  # full set for MAD diagnostic
        # Parallel per-source declared weights for the three lists
        # above (all 1.0 unless the user overrode a slider).
        cross_market_weights: list[float] = []
        subgroup_weights: list[float] = []
        all_weights: list[float] = []
        # Parallel (source_key, value, is_anchor) tracking so the
        # per-player Hampel filter below can identify which sources
        # produced which values and rebuild the three lists from the
        # surviving subset.
        all_value_pairs: list[tuple[str, float, bool]] = []

        canonical_site_values = players_array[row_idx].get("canonicalSiteValues") or {}
        if not isinstance(canonical_site_values, dict):
            canonical_site_values = {}

        for source_key, eff_rank in source_ranks.items():
            src_def = src_by_key.get(source_key, {})
            # Branch on source type:
            #   - value-based sources (KTC, IDPTC, DD-SF, DraftSharks):
            #     use the raw site value directly, normalized so that
            #     each site's top player contributes 9999.  This is the
            #     Final Framework override (2026-04-20) — real dollar-
            #     equivalent values bypass the Hill curve entirely.
            #   - rank-only sources: keep the rank → percentile → Hill
            #     pipeline using the master fit on the population this
            #     rank counts within (see ``_curve_for_rank``).
            #
            # Hill + percentile fields in the per-source meta are still
            # computed for diagnostic completeness even on the value-
            # based branch.  ``valueContribution`` always reflects the
            # value that actually enters aggregation.
            rank_meta = row_source_meta.get(row_idx, {}).get(source_key)
            hill_c, hill_s = _curve_for_rank(src_def, rank_meta)
            denom = _percentile_denom_for_source(src_def, source_key)

            # Canonical coordinate owner — the same mapping the fit and
            # the holdout use. Recomputing it inline here is what let
            # serving drift onto a different denominator than training
            # (audit finding W30-F008).
            p = rank_to_percentile(float(eff_rank), reference_n=denom)

            if source_key in _VALUE_BASED_SOURCES:
                raw_v = canonical_site_values.get(source_key)
                try:
                    raw_f = float(raw_v) if raw_v is not None else 0.0
                except (TypeError, ValueError):
                    raw_f = 0.0
                site_max = value_source_max.get(source_key, 0.0)
                # D-1 (policy B): an out-of-range value is not trustworthy
                # for THIS row, so it takes the same fallback a missing
                # value already takes.  D-1 (policy C): if the whole
                # source was suppressed, no row uses the value-direct
                # path for it.
                in_range = _value_is_in_declared_range(source_key, raw_f)
                if source_key in value_range_suppressed or not in_range:
                    value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
                elif raw_f > 0.0 and site_max > 0.0:
                    value = raw_f / site_max * 9999.0
                else:
                    # Fall back to the Hill path if the raw value is
                    # missing/invalid — should be rare, but protects
                    # against malformed site data dropping a source's
                    # vote to zero silently.
                    value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
            else:
                value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
            tep_applied = False
            tep_native_corrected = False
            # Blanket TE-value multipliers (see the constants block
            # near ``_TE_BLANKET_NON_NATIVE_MULTIPLIER``).  Non-TEP
            # sources scale by ``effective_non_tep_multiplier`` (the
            # operator's slider value, default 1.15).  TEP-native
            # sources scale by the hardcoded 1.10×.  KTC is exempt
            # because its TE++ board is already the canonical reference
            # we're aligning everyone else to.
            #
            # The boosted value is clamped to the 9,999 scale ceiling
            # that bounds every other position's contribution (the
            # value-direct path is ``raw / site_max * 9999`` and the
            # Hill max is ~9,999).  Without the clamp an elite TE's
            # boosted contribution exceeds 9,999, structurally letting
            # one TE out-value the consensus #1 overall — the premium
            # must reposition TEs *within* the scale, not break it.
            # DOUBLE-COUNT GUARD — do not restructure this without
            # reading the note (audit finding F, corrected 2026-07-27).
            #
            # Exactly one multiplier may reach a TE row:
            #   * KTC (``ktcSfTep``) is EXEMPT — it already publishes the
            #     TE++ board that is the alignment target. Lifting it
            #     would double-count.
            #   * every other source takes the if/elif below, which is
            #     mutually exclusive by construction.
            #
            # The league is a TWO-TIGHT-END league (roster_positions
            # carries ``TE, TE``, and TE is FLEX/SFLEX eligible), which
            # is what KTC's TE++ setting targets. That structural demand
            # — not any scoring key — is why the TE++ basis is correct
            # here. ``bonus_rec_te`` is 0.0 and that is irrelevant to it.
            #
            # Any future league-level TE adjustment must select a target
            # BASIS (see ``src/league_intel/te_premium.py``) rather than
            # multiply a factor in on top of this alignment.
            #
            # WIRED 2026-07-27: the non-TEP branch now does exactly that.
            # ``convert_te_value`` moves the contribution from the basis
            # a standard board sits on ("base") to the basis this board
            # is anchored on ("tepp", i.e. ktcSfTep), using KTC's own
            # measured uplift instead of a flat 1.15 that matched nothing
            # in the data. Read the ``_BOARD_TE_BASIS`` block before
            # touching this — in particular why the target is a constant
            # and not the league's own measured demand.
            #
            # The conversion is idempotent by construction (a second
            # call sees from == to), so this cannot compound even if the
            # branch is somehow reached twice. That property is the
            # double-count guard, and it is why the API takes two bases
            # rather than returning a multiplier.
            tep_basis_uplift: float | None = None
            if row_is_te and source_key not in _TE_BLANKET_KTC_EXEMPT_KEYS:
                if source_key in tep_boosted_source_keys:
                    pre_te_value = value
                    if te_basis_conversion:
                        value = _te_lift_under_ceiling(
                            float(
                                _convert_te_value(
                                    value,
                                    from_basis=_TE_SOURCE_DEFAULT_BASIS,
                                    to_basis=_BOARD_TE_BASIS,
                                )
                            )
                        )
                        if pre_te_value > 0:
                            tep_basis_uplift = value / pre_te_value
                    else:
                        value = _te_lift_under_ceiling(value * effective_non_tep_multiplier)
                    tep_applied = True
                elif source_key in tep_native_source_keys:
                    # Unchanged: only base <-> tepp is measured, so a
                    # TEP-native board has no conversion to make without
                    # inventing an intermediate uplift.
                    value = _te_lift_under_ceiling(value * effective_native_multiplier)
                    tep_native_corrected = True
            all_values.append(value)
            src_blend_weight = blend_weight_by_source.get(source_key, 1.0)
            all_weights.append(src_blend_weight)
            # Pick rows use the widened anchor set (KTC joins IDPTC as
            # a peer pick market — audit F-2); player rows keep the
            # cross-market-only anchor membership.
            anchor_keys = pick_anchor_keys if row_is_pick else cross_market_keys
            is_anchor_source = source_key in anchor_keys
            all_value_pairs.append((source_key, value, is_anchor_source))
            if is_anchor_source:
                cross_market_values.append(value)
                cross_market_weights.append(src_blend_weight)
            else:
                subgroup_values.append(value)
                subgroup_weights.append(src_blend_weight)
            # Per-source audit stamps.
            meta = row_source_meta[row_idx].get(source_key, {})
            declared_weight = float(src_def.get("weight") or 1.0)
            effective_weight = coverage_weight(declared_weight, src_def.get("depth"))
            meta["percentile"] = round(p, 6)
            meta["valueContribution"] = int(round(value))
            meta["valueContributionPath"] = (
                "value_direct"
                if source_key in _VALUE_BASED_SOURCES
                and value_source_max.get(source_key, 0.0) > 0.0
                else "rank_hill"
            )
            # ``effectiveWeight`` is the depth-scaled coverage
            # DIAGNOSTIC (declared × min(1, depth/60)) — stamped for
            # transparency, never applied to the blend.
            # ``appliedWeight`` is the declared weight the count-aware
            # blend actually multiplies this source's vote by
            # (registry default 1.0; user overrides move it).
            meta["effectiveWeight"] = round(effective_weight, 4)
            meta["appliedWeight"] = round(src_blend_weight, 4)
            meta["isAnchor"] = is_anchor_source
            if tep_applied:
                meta["tepBoostApplied"] = True
                if tep_basis_uplift is not None:
                    # Stamped so the change is auditable per player per
                    # source: which bases were used and what uplift they
                    # actually produced at this value. Without it a
                    # rank-dependent curve is indistinguishable from a
                    # flat constant by looking at the payload.
                    meta["tepBasisFrom"] = _TE_SOURCE_DEFAULT_BASIS
                    meta["tepBasisTo"] = _BOARD_TE_BASIS
                    meta["tepMultiplier"] = round(tep_basis_uplift, 4)
                else:
                    meta["tepMultiplier"] = round(effective_non_tep_multiplier, 4)
            if tep_native_corrected:
                meta["tepNativeCorrectionApplied"] = True
                meta["tepNativeCorrection"] = round(effective_native_multiplier, 4)

        # ── Per-player Hampel outlier rejection (K=2.75) ──
        # Drop source values that sit more than 2.75 MADs from the
        # median of this player's source values — catches the "this
        # one source got this one player wildly wrong" case before it
        # pulls the consensus around.  See ``_hampel_filter_per_player``
        # for guard rules (n>=4, MAD>0, >=2 survivors required).
        # Picks bypass: KTC's per-slot synthetic values create
        # artificial agreement that the Hampel statistic mis-reads as
        # outliers across the synthetic vs. real-source values.
        hampel_dropped_keys: list[str] = []
        if not row_is_pick and len(all_value_pairs) >= _HAMPEL_MIN_N:
            kept_pairs, hampel_dropped_keys = _hampel_filter_per_player(
                [(k, v) for k, v, _ in all_value_pairs], k=_HAMPEL_K
            )
            if hampel_dropped_keys:
                kept_set = {k for k, _ in kept_pairs}
                all_values = [v for k, v, _ in all_value_pairs if k in kept_set]
                cross_market_values = [v for k, v, a in all_value_pairs if k in kept_set and a]
                subgroup_values = [v for k, v, a in all_value_pairs if k in kept_set and not a]
                all_weights = [
                    blend_weight_by_source.get(k, 1.0)
                    for k, _v, _a in all_value_pairs
                    if k in kept_set
                ]
                cross_market_weights = [
                    blend_weight_by_source.get(k, 1.0)
                    for k, _v, a in all_value_pairs
                    if k in kept_set and a
                ]
                subgroup_weights = [
                    blend_weight_by_source.get(k, 1.0)
                    for k, _v, a in all_value_pairs
                    if k in kept_set and not a
                ]
                for sk in hampel_dropped_keys:
                    meta = row_source_meta[row_idx].get(sk, {})
                    meta["hampelDropped"] = True
        players_array[row_idx]["droppedSources"] = list(hampel_dropped_keys)

        # Coverage diagnostic (2026-04-20 override): soft-fallback
        # values used to be injected into the blend as "just past the
        # published list" Hill values for every scope-eligible source
        # that DIDN'T rank the player.  That polluted the count-aware
        # trim — only one fallback got dropped at n≥5 and any
        # remaining fallback dragged the mean down by several hundred
        # points (Chase at rank #5 with sf=2 lost ~600 points).
        #
        # The blend now uses covered sources only; ``softFallbackCount``
        # below is retained purely as a transparency metric so the
        # frontend / audits can surface "how many eligible sources
        # didn't rank this player" without that signal touching the
        # math.
        fallback_count = 0
        for src in active_sources:
            skey = str(src.get("key") or "")
            if skey in source_ranks:
                continue
            # Rookie-translation sources are deliberately excluded from
            # picks in the Phase 1 ordinal pass (see the matching skip
            # earlier in this function and ``_expected_sources_for_position``).
            # Counting them as a soft fallback for picks would inflate
            # ``softFallbackCount`` with a coverage gap that was
            # intentional, not a real matching failure.
            if row_is_pick and src.get("needs_rookie_translation"):
                continue
            src_scopes: list[str] = [src["scope"]] + list(src.get("extra_scopes") or [])
            eligible = any(
                _scope_eligible(row_pos, scope, src.get("position_group")) for scope in src_scopes
            )
            if not eligible:
                continue
            if source_pool_sizes.get(skey, 0) <= 0:
                continue
            fallback_count += 1

        players_array[row_idx]["softFallbackCount"] = fallback_count

        # Framework step 5 + 7–8.  Gating rule (2026-04-20):
        #   - IDP rows: keep the anchor/subgroup split.  IDPTC is the
        #     only source that prices offense and IDP on one combined
        #     scale, so using it as an anchor + α-shrunk subgroup
        #     adjustment gives IDPs a cross-market baseline that the
        #     IDP-only sources can't supply on their own.
        #   - Pick rows: keep the anchor/subgroup split too.  Picks
        #     attract many soft-fallback values from offense sources
        #     that do not rank picks (dlfSf, dynastyNerdsSfTep,
        #     fantasyPros, flockFantasy, …); flat-blending dilutes the
        #     real anchor + real covered sources with ≥7 dead-last
        #     fallback values and collapses the generic-tier picks
        #     (2027 Early/Mid/Late) out of the top-800 ranked board.
        #   - Offense rows (QB/RB/WR/TE): flat count-aware mean-median
        #     across ALL contributing values (anchor included).  The
        #     offense subgroup already has many independent sources
        #     (KTC, DynastyDaddy, DynastyNerds, DLF, FantasyPros, …)
        #     to form a stable consensus; using IDPTC as a hard anchor
        #     with α=0.10 over-weighted it vs. the other sources and
        #     caused ordering glitches (e.g. Drake Maye < Smith-Njigba
        #     where the offense consensus had Maye higher).
        use_hierarchical_blend = row_is_pick or (row_pos in _IDP_POSITIONS)
        # Cross-market anchor value: count-aware mean-median across
        # every covered cross-market source (IDPTC via value-direct;
        # DS + FG via their combined cross-market rank → GLOBAL
        # Hill).  n=1 passthrough, n=2 mean, n=3-4 untrimmed
        # (mean+median)/2, n≥5 trimmed.  Using the count-aware blend
        # here instead of a bare mean damps single-source outliers
        # (e.g. FG's combined rank was 304 for Micah Parsons vs 43
        # for IDPTC / 89 for DS — bare mean pulled his anchor
        # ~15% below reality; the mean+median blend keeps the
        # outlier's influence to ~half that).  Matches the exact
        # aggregation rule the subgroup uses on the other side of
        # the α-shrinkage combine.
        if cross_market_values:
            anchor_value, _ = _weighted_trimmed_mean_median(
                cross_market_values, cross_market_weights
            )
        else:
            anchor_value = None

        subgroup_center: float | None
        if subgroup_values:
            subgroup_center, _ = _weighted_trimmed_mean_median(subgroup_values, subgroup_weights)
        else:
            subgroup_center = None

        subgroup_delta: float | None = None
        if use_hierarchical_blend:
            if anchor_value is not None and subgroup_center is not None:
                subgroup_delta = subgroup_center - anchor_value
                center_value = anchor_value + _ALPHA_SHRINKAGE * subgroup_delta
            elif anchor_value is not None:
                center_value = anchor_value
            elif subgroup_center is not None:
                center_value = subgroup_center
            else:
                center_value = 0.0
        else:
            # Offense (QB/RB/WR/TE): flat blend over all_values (every
            # covered source votes at its declared weight — equal
            # voice at the all-1.0 registry default — including
            # cross-market ones).  No α-shrinkage against a single
            # anchor.
            if all_values:
                flat_center, _ = _weighted_trimmed_mean_median(all_values, all_weights)
                center_value = flat_center
            else:
                center_value = 0.0

        # Framework step 6: MAD across ALL contributing sources.
        # Deliberately UNWEIGHTED: ``sourceSpread`` is a disagreement
        # diagnostic over the covered sources' values; a user's weight
        # slider should not make the sources look like they agree more
        # or less than they do.
        _, source_mad = _trimmed_mean_median(all_values)

        if source_mad is not None and _MAD_PENALTY_LAMBDA > 0 and not row_is_pick:
            mad_penalty = min(center_value, _MAD_PENALTY_LAMBDA * source_mad)
        else:
            mad_penalty = 0.0

        blended_value = max(0.0, center_value - mad_penalty)

        # Stamp the uncapped blended value on every row.  ``rankDerivedValue``
        # is only set for rows that survive the top-``OVERALL_RANK_LIMIT``
        # sort; deep rookies (e.g. 2026 rookie class beyond the DLF top-60)
        # fall out of that cap and lose their ``rankDerivedValue``.  Pick
        # tethering needs them back — all 72 of a given year's slot picks
        # must tether to a distinct rookie — so we keep the pre-cap blend
        # value on every row in a separate field that's read only by the
        # rookie-anchor pass.
        players_array[row_idx]["_blendedValueUncapped"] = (
            int(round(blended_value)) if blended_value > 0 else 0
        )

        hill_value_spread = statistics.stdev(all_values) if len(all_values) >= 2 else None

        # Stamp anchor/subgroup diagnostics so the frontend value-chain
        # panel can surface the framework's hierarchical shape
        # (anchor + α·subgroup) transparently.
        players_array[row_idx]["anchorValue"] = (
            int(round(anchor_value)) if anchor_value is not None else None
        )
        players_array[row_idx]["subgroupBlendValue"] = (
            int(round(subgroup_center)) if subgroup_center is not None else None
        )
        players_array[row_idx]["subgroupDelta"] = (
            int(round(subgroup_delta)) if subgroup_delta is not None else None
        )
        # alphaShrinkage stamp: IDP + pick rows carry the live module
        # constant (they exercise the hierarchical anchor+α·subgroup
        # path); offense rows carry 0.0 to signal "flat blend, no
        # shrinkage applied".
        players_array[row_idx]["alphaShrinkage"] = (
            round(_ALPHA_SHRINKAGE, 4) if use_hierarchical_blend else 0.0
        )

        # Stamp source-spread diagnostic on every row.  ``sourceSpread``
        # is the mean absolute deviation of per-source value
        # contributions around the (trimmed) center — a pure
        # transparency metric that lets the frontend value-chain
        # panel show how much the sources actually disagreed on this
        # player.  It has been renamed from the old ``sourceMAD``
        # field for clarity: with λ·MAD retired (2026-04-20) this
        # number is a spread statistic, not a penalty input.
        #
        # ``madPenaltyApplied`` is kept stamped as ``None`` because
        # frontend builds still read the key; once every frontend
        # consumer drops the reference, this stamp can go too.
        players_array[row_idx]["sourceSpread"] = (
            round(source_mad, 2) if source_mad is not None else None
        )
        players_array[row_idx]["madPenaltyApplied"] = (
            round(mad_penalty, 2) if mad_penalty > 0 else None
        )

        players_array[row_idx]["hillValueSpread"] = (
            round(hill_value_spread, 2) if hill_value_spread is not None else None
        )

        # Single-source confidence haircut.  ``all_values`` is the
        # post-Hampel set of contributing source values; len <= 1 means
        # the blend rests on one uncorroborated source.  Apply the
        # heavy retention factor to the value that feeds the sort so
        # both the board rank and ``rankDerivedValue`` reflect the low
        # confidence.  ``_blendedValueUncapped`` (stamped above) is
        # re-stamped with the same haircut: the rookie-anchor pass'
        # ``_rookie_pool_value`` reads the haircut ``rankDerivedValue``
        # for ranked rookies but falls back to ``_blendedValueUncapped``
        # for rookies past ``OVERALL_RANK_LIMIT``; leaving the fallback
        # unpenalized would let an unranked single-source rookie sort
        # and price picks on its full uncorroborated value while a
        # ranked single-source rookie is held to 30%.
        if not row_is_pick and len(all_values) <= 1:
            blended_value *= _SINGLE_SOURCE_VALUE_RETENTION
            players_array[row_idx]["_blendedValueUncapped"] = (
                int(round(blended_value)) if blended_value > 0 else 0
            )
            players_array[row_idx]["singleSourceValuePenaltyApplied"] = True

        row_normalized.append((blended_value, row_idx))

    # ── Phase 3a: Pick year discount (gated to picks) ──
    # Apply the multiplicative future-year discount BEFORE the global
    # sort so 2027/2028 picks naturally drift to lower positions in
    # the final ladder. Player rows are untouched.
    row_normalized, _pick_year_discounts = _apply_pick_year_discount_to_blend(
        row_normalized, players_array
    )

    # ── Phase 4: Unified sort and overall rank assignment ──
    row_normalized.sort(key=lambda t: (-t[0], players_array[t[1]].get("canonicalName", "").lower()))

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
        # ``sourcePresence[k]`` is True when source ``k`` covered this
        # row.  DS combined-rank sources use a cross-market scale that
        # goes negative past ~rank 200 (the tail of the CSV); those
        # rows are still ranked by DS, so any non-None DS value counts
        # as coverage.  Every other value-signal source treats ``<= 0``
        # as "unranked / missing."  Keeping this in lockstep with the
        # enrichment + Phase 1 gates is the whole point of
        # ``_DS_COMBINED_RANK_KEYS``.
        row["sourcePresence"] = {
            k: (v is not None if k in _DS_COMBINED_RANK_KEYS else (v is not None and v > 0))
            for k, v in canonical_sites.items()
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
                    # ``sleeper_id`` when the enrichment matched via the
                    # CSV's Sleeper-ID column instead of the canonical
                    # name (see the sid_index alias in
                    # ``_enrich_from_source_csvs``).
                    "via": entry.get("matchedVia") or "csv_enrich",
                }
                native = entry.get("nativeValue")
                if native is not None:
                    matched_details[sk]["nativeValue"] = native

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
        if allowlist_reason is None and cname in _SYNTHETIC_FAR_FUTURE_PICK_NAMES:
            allowlist_reason = _FAR_FUTURE_ALLOWLIST_REASON
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
        row["isSingleSource"] = len(source_ranks) == 1 and len(expected_keys) > 1
        row["isStructurallySingleSource"] = len(source_ranks) == 1 and len(expected_keys) <= 1

    # Ranked pool size for the depth-aware disagreement allowance —
    # the denominator of a row's consensus percentile.
    total_ranked = min(len(row_normalized), OVERALL_RANK_LIMIT)

    for overall_idx, (norm_val, row_idx) in enumerate(row_normalized[:OVERALL_RANK_LIMIT]):
        row = players_array[row_idx]
        overall_rank = overall_idx + 1
        derived = int(norm_val)
        source_ranks = row_source_ranks.get(row_idx, {})
        source_meta = row_source_meta.get(row_idx, {})

        # ── Core ranking fields ──
        # ``sourceRanks`` / ``sourceRankMeta`` / ``sourceCount`` reflect
        # *matched* sources end-to-end so audit consumers still see
        # which sources covered this player.  Trust/spread/confidence/
        # anomaly computations below use the post-Hampel subset so a
        # single rejected outlier source doesn't fire a false
        # disagreement flag on an otherwise-tight consensus.
        row["sourceRanks"] = source_ranks
        row["sourceRankMeta"] = source_meta
        row["rankDerivedValue"] = derived
        row["canonicalConsensusRank"] = overall_rank
        row["canonicalTierId"] = _tier_id_from_rank(overall_rank)
        row["sourceCount"] = len(source_ranks)

        dropped_set = set(row.get("droppedSources") or [])
        effective_source_ranks = {k: v for k, v in source_ranks.items() if k not in dropped_set}
        effective_source_meta = {k: v for k, v in source_meta.items() if k not in dropped_set}
        # Publish the post-Hampel rank map so frontend display helpers
        # (frontend/lib/display-helpers.js::marketEdge / marketGapLabel)
        # compute retail-vs-consensus on the same set the backend used
        # for marketGapDirection / confidence / anomaly flags.  Without
        # this, the same player could show conflicting edge signals
        # across UI surfaces after a Hampel drop.
        row["effectiveSourceRanks"] = effective_source_ranks
        rank_values = list(effective_source_ranks.values())

        # Caution flag when any IDP source required fallback translation
        used_fallback = any(m.get("method") == TRANSLATION_FALLBACK for m in source_meta.values())
        row["idpBackboneFallback"] = used_fallback

        # ── Trust/transparency fields (effective rank space) ──
        blended_source_rank = sum(rank_values) / len(rank_values) if rank_values else None
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
        # source's auto-detected pool size — trimmed of the single
        # most extreme source on each side once 5+ sources contribute
        # (see ``_PERCENTILE_SPREAD_TRIM_MIN_N``), so one straggler
        # can't flag a 12-source consensus.
        percentile_spread = _percentile_rank_spread(
            effective_source_ranks, effective_source_meta, source_pool_sizes
        )
        row["sourceRankPercentileSpread"] = (
            round(percentile_spread, 4) if percentile_spread is not None else None
        )

        # Preserve the semantic 1-src flag stamped in Phase 4a; do
        # not collapse it back to ``len(source_ranks) == 1`` here.
        # Disagreement uses the trimmed percentile spread plus a
        # depth allowance (see ``_disagreement_depth_allowance``):
        # only spread in excess of what is typical at this rank depth
        # earns the caution.
        depth_allowance = _disagreement_depth_allowance(
            overall_rank / float(total_ranked) if total_ranked else None
        )
        row["hasSourceDisagreement"] = (
            percentile_spread is not None
            and percentile_spread > _DISAGREEMENT_BASE_THRESHOLD + depth_allowance
        )

        gap_dir, gap_ratio = _compute_market_gap(
            effective_source_ranks,
            source_meta=row.get("sourceRankMeta") or {},
        )
        row["marketGapDirection"] = gap_dir
        # NEW FIELD, not a redefinition.  ``marketGapMagnitude`` was an
        # ordinal rank difference; this is a relative gap in value space.
        # Writing the new number under the old name would silently change
        # the units of a published field and of every row already recorded
        # in the board-history store.
        row["marketGapValueRatio"] = gap_ratio
        # Retired with the rank-space computation it came from.  Kept as an
        # explicit None so consumers see "no longer computed" rather than a
        # missing key that could read as "not applicable to this row".
        row["marketGapMagnitude"] = None

        # Picks get their own confidence logic (CV-based on raw values),
        # because rank-spread is dominated by flat-value regions in
        # R3-R6 and KTC's per-slot synth bleeds in as fake agreement.
        if row.get("assetClass") == "pick":
            is_slot_specific = _parse_pick_slot(row.get("canonicalName") or "") is not None
            bucket, label = _compute_pick_confidence(
                row.get("canonicalSiteValues") or {},
                is_slot_specific=is_slot_specific,
            )
        else:
            bucket, label = _compute_confidence_bucket(
                len(effective_source_ranks),
                source_rank_spread,
                percentile_spread=percentile_spread,
            )
        row["confidenceBucket"] = bucket
        row["confidenceLabel"] = label

        audit = row.get("sourceAudit") or {}
        row["anomalyFlags"] = _compute_anomaly_flags(
            name=row.get("canonicalName") or row.get("displayName") or "",
            position=row.get("position"),
            asset_class=row.get("assetClass") or "",
            source_ranks=effective_source_ranks,
            source_meta=effective_source_meta,
            rank_derived_value=derived,
            canonical_sites=row.get("canonicalSiteValues") or {},
            percentile_spread=percentile_spread,
            expected_sources=list(audit.get("expectedSources") or []),
            disagreement_allowance=depth_allowance,
        )

        # Backward compatibility: set ktcRank / idpRank if applicable.
        # ktcRank and idpRank carry the *effective* rank consumers are
        # used to.  Standard ``ktc`` was removed from the blend
        # 2026-04-28 in favor of ``ktcSfTep`` (the TE+ board uses the
        # same KTC scrape; for non-TE rows the rank ordering matches
        # ``ktc`` exactly), so ``ktcRank`` now reflects the ktcSfTep
        # ordinal rank — preserving the field name consumers know.
        if "ktcSfTep" in source_ranks:
            row["ktcRank"] = source_ranks["ktcSfTep"]
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
                if "ktcSfTep" in source_ranks:
                    pdata["ktcRank"] = source_ranks["ktcSfTep"]
                if "idpTradeCalc" in source_ranks:
                    pdata["idpRank"] = source_ranks["idpTradeCalc"]

    # ── Phase 4c: removed ──
    # The IDP calibration post-pass (a Lab-configured per-bucket
    # multiplier applied to DL/LB/DB rows) has been retired.  The
    # live ``rankDerivedValue`` is now the canonical-pipeline output
    # with no post-blend adjustment on IDPs.  The prior
    # ``rankDerivedValueUncalibrated`` / ``canonicalConsensusRankUncalibrated``
    # snapshots are no longer stamped — downstream consumers fall
    # back to the live rank and value, which are the single source
    # of truth for every position.

    # Market-anchor corridor clamp: after all value-moving passes,
    # clamp players whose blended value has drifted further from the
    # market anchor (KTC for offense, IDPTC for IDP) than the P90 of
    # natural drift inside their confidence bucket.  Leaves 90% of
    # the board untouched — only the tail outliers where one or two
    # sources have pulled a player far from the retail-market consensus
    # get pulled back to the band edge.  See
    # ``_apply_market_corridor_clamp`` for the design rationale.
    #
    # ``suppress_market_corridor_clamp`` exists for exactly one caller:
    # a board built to be INDEPENDENT of a market anchor (see
    # ``src/consensus_edge/fair_value.py``).  The clamp reads the anchor
    # out of ``canonicalSiteValues``, not out of the vote, so dropping a
    # source from the blend does NOT stop the clamp pulling values back
    # toward it — measured 2026-08-04 on the live payload: with
    # ``idpTradeCalc`` excluded from voting, 101 IDP rows were still
    # clamped toward idpTradeCalc, mean shift 552 points.  A fair value
    # that has been pulled back toward the price it is about to be
    # compared against is not a fair value.
    #
    # Default False: the live board is byte-identical to before.
    if not suppress_market_corridor_clamp:
        _apply_market_corridor_clamp(players_array, players_by_name)

    # Two-way player boost: a tiny override table that rescues players
    # whose Sleeper single-position classification excludes them from
    # the IDP blend (Travis Hunter — WR in Sleeper, CB on the field,
    # ranked #1 by IDP Show / top-50 by FBG IDP / etc).  For each
    # entry, compute the alt-family's implied value from the already-
    # loaded IDP source synthetic ranks and replace rankDerivedValue
    # with max(offense_value, alt_family_value).
    _apply_two_way_player_boost(players_array, players_by_name)

    # Offense calibration is deliberately never applied to live values.
    # The offense market is already priced by the blend of KTC / DLF /
    # IDPTC / etc.  VOR bucket multipliers produced absurd artefacts
    # (QB bucket cliffs, Mahomes-at-half-value-of-QB1) so the live
    # pipeline intentionally has no offense post-pass.  The IDP
    # calibration lab still writes ``offense_multipliers`` /
    # ``offense_anchors`` into the promoted config as an analytical
    # reference; ``tests/api/test_single_curve_live.py::
    # TestOffenseHasNoCalibrationLayer`` fails if that reference ever
    # starts mutating live values.

    # (Phase 4d — volatility compression — intentionally removed as
    # part of the Final Framework transition.  A principled
    # MAD-based volatility penalty with a fitted ``λ`` weight will
    # reappear in a later PR once backtested.  The old ±8%
    # compress/boost + 75-pt monotonicity cap was a heuristic stack
    # sitting on top of the Hill curve and has been removed
    # outright — see docs/architecture/live-value-pipeline-trace.md.)

    # ── Phase 5: Pick refinement passes (gated to picks) ──
    # 1) Reassign (rank, value) tuples within each (year, round) bucket
    #    so slot-specific picks 1.01..1.12 are strictly monotonic in
    #    slot order.  This corrects KTC's _estimate_slot_from_tier
    #    inversions without disturbing global rank/value monotonicity.
    _reassign_pick_slot_order(players_array)

    # 2) Suppress generic Early/Mid/Late tier rows for years that have
    #    specific slots, returning a {generic_name: slot_alias} map.
    pick_aliases = _suppress_generic_pick_tiers_when_slots_exist(players_array)

    # 2b) Anchor current-year slot picks to merged offense+IDP rookies.
    #     Pick (round, slot) inherits the rankDerivedValue of the rookie
    #     at position (round-1)*N + slot in the merged rookie list, where
    #     N is the operator's Sleeper league roster count resolved via
    #     ``_resolve_league_context`` (falls back to 12 when the Sleeper
    #     fetch is unavailable).  The compact-ranks pass below re-sorts
    #     by value so coherence holds.
    _anchor_year = current_rookie_draft_year()
    _anchor_current_year_picks_to_rookies(players_array, _anchor_year)

    # 2c) Stamp draft-day value projections on every pick row.
    #     Inverts the year-discount so the frontend can show "this
    #     2027 pick is worth ~5,800 today, projected ~7,000 at the
    #     2027 draft (▲21%)" — operationalises the package-now-or-
    #     wait decision the user has to make on every offseason
    #     trade involving forward picks.  Runs AFTER the anchor pass
    #     so current-year slot picks project off their final rookie-
    #     tethered ``rankDerivedValue``.
    _stamp_pick_value_projections(players_array)

    # 2a) Compact ranks after suppression/anchor so the ranked board is
    #     still contiguous 1..N and value-monotonic.  Sort primarily by
    #     rankDerivedValue desc so anchored picks naturally bubble to the
    #     neighborhood of their rookie target; fall back to the existing
    #     canonicalConsensusRank to preserve the prior Phase-4 ordering
    #     for all rows whose values were not mutated.  Tier IDs are
    #     re-derived after compaction via gap-based detection on the
    #     blended ``rankDerivedValue`` series (see below).
    # Extracted to ``compact_ranks_and_tiers`` so the league-adjusted
    # overlay re-ranks through the SAME code rather than a second
    # implementation.  In-place here (copy_rows=False): these are the
    # canonical board's own rows and the pipeline owns them.  The overlay
    # passes copy_rows=True — see that function's docstring for why.
    tiered_rows = compact_ranks_and_tiers(
        players_array,
        anchor_year=_anchor_year,
        copy_rows=False,
    )

    # Rank-change vs previous scrape.  Stamps ``rankChange`` on
    # each row from the persisted snapshot; writes the current ranks
    # back only when this is the canonical board build (no source
    # overrides — override paths shouldn't clobber the snapshot that
    # the scheduled scrape maintains).
    _stamp_rank_changes(
        tiered_rows,
        write_snapshot=not source_overrides,
    )

    # ── Post-compaction disagreement re-stamp ──
    # The depth-aware allowance was computed in Phase 4 from the
    # PROVISIONAL rank/pool-size, but the compact pass above just
    # suppressed generic picks, cleared anchor slot-pick ranks, and
    # re-sequenced every surviving ``canonicalConsensusRank``.  A row
    # sitting near either disagreement threshold could otherwise
    # publish ``hasSourceDisagreement`` / ``suspicious_disagreement``
    # keyed to a rank the public board no longer shows.  Recompute
    # both flags from the FINAL rank and final ranked-pool size using
    # the stamped trimmed spread — same formula, final inputs.
    final_total = len(tiered_rows)
    for r in tiered_rows:
        ps = r.get("sourceRankPercentileSpread")
        rk = r.get("canonicalConsensusRank")
        if not isinstance(ps, (int, float)) or not isinstance(rk, int) or final_total <= 0:
            continue
        allowance = _disagreement_depth_allowance(rk / float(final_total))
        r["hasSourceDisagreement"] = ps > _DISAGREEMENT_BASE_THRESHOLD + allowance
        suspicious = ps > _SUSPICIOUS_PCT_BASE_THRESHOLD + allowance
        flags = list(r.get("anomalyFlags") or [])
        has_flag = "suspicious_disagreement" in flags
        if suspicious and not has_flag:
            flags.append("suspicious_disagreement")
            r["anomalyFlags"] = flags
        elif not suspicious and has_flag:
            r["anomalyFlags"] = [f for f in flags if f != "suspicious_disagreement"]

    # (Phase 5b — value re-flattening — intentionally removed.) The
    # pre-sort ``rankDerivedValue`` is a weighted blend of per-source
    # Hill-curve values plus any calibration multiplier, which
    # encodes fractional-rank consensus (e.g. Josh Allen at source
    # ranks [1,1,1,2,1] ⇒ blended ~9976 ≈ Hill(1.2)) rather than a
    # raw integer-rank snap. Re-flattening to ``rank_to_value(int
    # rank)`` threw that nuance away. Sort order is still enforced
    # by the Phase 5 re-sort above, so values are monotonic with
    # ranks even without the Hill-curve anchor here.

    # 2c) Mirror the post-anchor rank back into the legacy players_by_name
    #     dict for every ranked row — not just picks.  The runtime view
    #     (/api/data?view=app) strips playersArray, so the frontend reads
    #     ``_canonicalConsensusRank`` from the legacy dict.  When the
    #     compact-ranks pass above re-sorts by rankDerivedValue, non-pick
    #     rows can shift (e.g. a rookie-anchored pick bubbles up past a
    #     bench player, pushing the bench player's rank down by one).  The
    #     pick-only mirror below handles pick-specific flags, so keep it
    #     focused on picks; this pass syncs the ranked-row baseline.
    for row in players_array:
        if row.get("assetClass") == "pick":
            continue
        legacy_ref = row.get("legacyRef")
        if not legacy_ref or legacy_ref not in players_by_name:
            continue
        pdata = players_by_name[legacy_ref]
        if not isinstance(pdata, dict):
            continue
        rk = row.get("canonicalConsensusRank")
        if rk is not None:
            pdata["_canonicalConsensusRank"] = rk
        tid = row.get("canonicalTierId")
        if tid is not None:
            pdata["canonicalTierId"] = tid

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
        is_suppressed = bool(row.get("pickGenericSuppressed"))

        if is_suppressed:
            # Suppressed generic tier (e.g. "2026 Early 1st" hidden when
            # slot-specific picks exist) — clear BOTH rank and value
            # on the legacy mirror too.
            pdata["rankDerivedValue"] = None
            pdata["_canonicalConsensusRank"] = None
        else:
            # Mirror whatever value the pick row carries.  Anchored
            # slot picks may have ``rankDerivedValue`` set even though
            # ``canonicalConsensusRank`` is None (the Phase 5 compact
            # pass clears slot-pick ranks; off-cap picks never had one
            # to begin with).  Clearing the legacy value when the rank
            # is None would silently drop the rookie-anchored value
            # for clients reading from the runtime view, which strips
            # playersArray and uses the legacy dict.
            if rdv is not None:
                pdata["rankDerivedValue"] = rdv
            if rk is not None:
                pdata["_canonicalConsensusRank"] = rk
            else:
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
        if row.get("pickRookieAnchor"):
            pdata["pickRookieAnchor"] = row["pickRookieAnchor"]

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
    # Thin pass-through to the canonical helper; kept as a local
    # name so existing call sites (line 6749+) don't need to change.
    # Audit S2 consolidated the previous inline POSITION_ALIASES.get
    # idiom.
    from src.utils.name_clean import normalize_position

    return normalize_position(pos)


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


# Sources whose 0-9999 published board is the user-meaningful value
# (e.g. KTC publishes its dynasty rankings publicly on
# keeptradecut.com — users compare popup chips to the website
# directly).  After the 2026-05 TEP split (PR #406), the scraper-
# side ×1.15 is gone and ``ktcSfTep`` is in
# ``_TE_BLANKET_KTC_EXEMPT_KEYS``, so ``canonicalSiteValues.ktcSfTep``
# now equals the raw scrape verbatim for both TE and non-TE rows.
# ``rawSourceValues`` is preserved as a parallel read path: the popup
# chip render and per-player source-history chart read from it first,
# which keeps display robust against any future divergence between
# the canonical pipeline and the raw scrape.  Mirrors
# ``_RAW_VALUE_PREFERRED_KEYS`` in ``src/api/source_history.py``.
_RAW_VALUE_PREFERRED_KEYS: frozenset[str] = frozenset({"ktcSfTep"})


def _raw_source_values(p_data: dict[str, Any]) -> dict[str, int]:
    """Extract raw scrape values for sources where the source's own
    published board is the meaningful display number.  Only includes
    keys that have a positive integer raw value at the top level of
    ``p_data`` — missing keys are omitted so the frontend can branch
    on presence cleanly.
    """
    out: dict[str, int] = {}
    for key in _RAW_VALUE_PREFERRED_KEYS:
        raw = _to_int_or_none(p_data.get(key))
        if raw is not None and raw > 0:
            out[key] = raw
    return out


def _player_value_bundle(p_data: dict[str, Any]) -> dict[str, int | None]:
    """Seed the per-row ``values`` bundle.

    SCALE CONTRACT (math audit 2026-07-30, finding H1).  Two scales meet
    in this bundle and they are NOT interchangeable:

    * ``rawComposite`` is the **legacy scraper composite** — a separate
      pipeline in ``Dynasty Scraper.py`` that runs ~1.131x the canonical
      board (measured; ``BOARD_TO_COMPOSITE_K = 0.875`` in
      ``src/trade/finder.py``).  It is the UI's explicit "Raw" value mode
      and its name says what it is.
    * ``overall`` / ``finalAdjusted`` / ``displayValue`` are **board**
      values.  ``build_api_data_contract`` stamps ``rankDerivedValue``
      into all three once the blend has run.

    They used to be seeded from the composite and then *overwritten* by
    the board only when ``rankDerivedValue > 0``.  On a real payload that
    left 270 rows — every suppressed generic pick tier among them —
    carrying a composite-scale number under a board-scale name, with
    nothing marking the difference.  Consumers that fall back down the
    chain (public trade grading, the frontend's ``values.full``, the
    league-adjusted overlay) then summed the two scales together.

    So they are seeded ``None`` instead.  A row the board declined to
    price now reads as *unpriced* rather than as priced-on-another-scale,
    which is the honest answer and the one every consumer can branch on.
    """
    raw = _to_int_or_none(
        p_data.get("_rawComposite", p_data.get("_rawMarketValue", p_data.get("_composite")))
    )
    return {
        # Board scale — filled in by ``build_api_data_contract`` from
        # ``rankDerivedValue``.  Never seeded from the composite.
        "overall": None,
        "finalAdjusted": None,
        "displayValue": None,
        # Composite scale — honestly named, and the only key that carries
        # it.  Do NOT add it to a fallback chain that otherwise reads
        # board values.
        "rawComposite": raw,
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
        _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _OFFENSE_SIGNAL_KEYS
    )
    has_idp_signal = any(
        _to_int_or_none(canonical_sites.get(k)) not in (None, 0) for k in _IDP_SIGNAL_KEYS
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
    elif not pos_from_player and pos_from_sleeper:
        # Signal-based guardrail: when the player's adapter data has no position
        # but the sleeper map contradicts the source signals, drop the
        # sleeper-supplied position. This catches name collisions across
        # universes (e.g. DJ Turner WR vs DJ Turner II CB both clean to the
        # same key) where the sleeper map overwrote one with the other's
        # position. Tagging the row with the wrong family would break the
        # offense→IDP validator downstream.
        sleeper_is_off = pos_from_sleeper in _OFFENSE_POSITIONS
        sleeper_is_idp = pos_from_sleeper in _IDP_POSITIONS
        if sleeper_is_idp and has_off_signal and not has_idp_signal:
            pos = ""
        elif sleeper_is_off and has_idp_signal and not has_off_signal:
            pos = ""

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

    # Track when the final position was sourced ONLY from the sleeper map
    # (no adapter-supplied position). This lets the post-enrichment
    # guardrail distinguish sleeper-map name collisions (strip) from
    # legitimate adapter-vs-signal contradictions (flag). Trimmed off
    # the row before the contract is materialized externally.
    position_from_sleeper_only = bool(
        pos and not is_pick and not pos_from_player and pos_from_sleeper
    )

    return {
        "playerId": str(p_data.get("_sleeperId") or "").strip() or None,
        "canonicalName": canonical_name,
        "displayName": canonical_name,
        "position": pos or None,
        "_positionFromSleeperOnly": position_from_sleeper_only,
        # NFL team abbreviation ("FA" for matched free agents), stamped
        # by the scraper's metadata pass from the Sleeper players blob
        # (2026-07-26 — previously scaffolded but never written; the
        # search/filter system needs it).
        "team": p_data.get("team") if isinstance(p_data.get("team"), str) else None,
        # Age: scaffolded for future use.  Populated when source data includes
        # age_raw (e.g. DLF CSV adapter).  Currently null for most players
        # because the scraper bridge does not supply age.
        "age": _to_int_or_none(p_data.get("age")) or _to_int_or_none(p_data.get("age_raw")),
        # NFL years of experience from the Sleeper blob (rookie = 0).
        # The legacy dict has carried ``_yearsExp`` since the rookie
        # visibility pass; the row previously exposed only its
        # ``rookie`` derivative — the experience-bucket filter needs
        # the number itself.
        "yearsExp": _to_int_or_none(p_data.get("_yearsExp")),
        # Two upstream rookie signals: ``_formatFitRookie`` is set by
        # the canonical pipeline's format-fit pass and is None for
        # rows that haven't been through it.  ``_isRookie`` is the
        # scraper's direct flag, set when the player has zero NFL
        # years of experience.  Use whichever is positive so the
        # contract layer can rely on a single boolean.
        "rookie": bool(p_data.get("_formatFitRookie") or p_data.get("_isRookie")),
        "assetClass": "pick" if is_pick else ("idp" if pos in {"DL", "LB", "DB"} else "offense"),
        "values": values,
        "canonicalSiteValues": canonical_sites,
        # Raw 0-9999 scrape values for sources where the published
        # board is the user-meaningful display number (see
        # ``_RAW_VALUE_PREFERRED_KEYS``).  The popup chip render reads
        # this map first for these keys so the displayed number matches
        # the source's website (KTC TE++ at keeptradecut.com).  Post
        # the 2026-05 TEP split (PR #406), this stamp equals the
        # corresponding ``canonicalSiteValues`` entry — the parallel
        # path remains as a robustness guarantee against future
        # canonical-pipeline corrections.  Sparse by design — only
        # present for the listed keys.
        "rawSourceValues": _raw_source_values(p_data),
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
        "hillValueSpread": None,
        "sourceSpread": None,
        "madPenaltyApplied": None,
        "anchorValue": None,
        "subgroupBlendValue": None,
        "subgroupDelta": None,
        "alphaShrinkage": None,
        "softFallbackCount": 0,
        "droppedSources": [],
        "effectiveSourceRanks": {},
        "marketGapDirection": "none",
        "marketGapMagnitude": None,
        "marketGapValueRatio": None,
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
        # Native vendor values for rank-signal sources (FantasyCalc
        # crowd value, OTC 0-100, PFK 0-9999, ...) — the real number
        # behind the synthetic encoding in canonicalSiteValues.
        "sourceNativeValues": {},
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
            k
            for k in pdata
            if k in _LEGACY_LAM_PLAYER_FIELDS
            or any(k.startswith(prefix) for prefix in _LEGACY_LAM_PLAYER_PREFIXES)
        ]
        for k in keys_to_remove:
            del pdata[k]


def build_api_data_contract(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
    tep_native_multiplier: float | None = None,
    suppress_market_corridor_clamp: bool = False,
    csv_root: "Path | None" = None,
    _for_delta: bool = False,
) -> dict[str, Any]:
    """Build a full API data contract payload from a raw scraper bundle.

    ``source_overrides`` (optional) is forwarded to
    :func:`_compute_unified_rankings` to enable user-settings-driven
    re-rankings.  When ``None``, the default canonical board is
    built.  The presence of overrides is stamped onto the returned
    contract under the ``rankingsOverride`` key so downstream
    consumers can tell an override response from the baseline
    response without guessing.

    ``tep_multiplier`` is the league-wide TE premium boost, applied
    value-level inside the canonical blend (see
    ``_compute_unified_rankings`` docstring).  Three modes:

      * ``None`` + Sleeper league context with ``bonus_rec_te > 0`` —
        auto-derive the multiplier via
        :func:`_derive_tep_multiplier_from_league`.  TEP-1.5
        (``bonus_rec_te == 0.5``) → ``1.15``; TEP-2.0
        (``bonus_rec_te == 1.0``) → ``1.30``.  Stamped as
        ``rankingsOverride.tepMultiplierSource = "derived"``.
      * ``None`` + no Sleeper context (cold start, offline, registry
        miss) OR non-TEP league (``bonus_rec_te == 0``) — fall back
        to the hardcoded ``_TE_BLANKET_NON_NATIVE_MULTIPLIER``
        (1.15).  Stamped as ``tepMultiplierSource = "default"``.
      * an explicit ``float`` — use the caller's value verbatim (the
        contract-summary stamp clamps to ``[1.0, 1.5]``, matching the
        API-ingress ``normalize_tep_multiplier`` and the /settings
        slider).  Used by the override endpoint when the user moves
        the TEP slider.  Stamped as ``tepMultiplierSource = "override"``.

    The /settings page reads ``rankingsOverride.tepMultiplierDerived``
    to render the "Auto" baseline next to the slider, so users in a
    TEP-1.5 league see the slider default at 1.15 (their league's
    actual setting) rather than the generic 1.25 fallback.

    ``_for_delta`` (internal) skips work that only feeds fields the
    delta payload discards (trust-mirror into legacy players dict,
    valueAuthority summary).  ``build_rankings_delta_payload`` sets
    this to ``True`` so overrides round-trips don't pay for output
    blocks the wire shape drops.
    """
    # TEP inputs: two parallel knobs control the per-bucket TE boost,
    # both operator-tunable and both falling back to hardcoded
    # defaults when ``None``.
    #
    #   * ``tep_multiplier``        — non-TEP sources (default 1.15,
    #     ``_TE_BLANKET_NON_NATIVE_MULTIPLIER``)
    #   * ``tep_native_multiplier`` — TEP-native sources (default 1.10,
    #     ``_TE_BLANKET_NATIVE_MULTIPLIER``)
    #
    # Each is clamped to [1.0, 1.5] at the normalize layer.  KTC
    # variants stay exempt regardless — see
    # ``_TE_BLANKET_KTC_EXEMPT_KEYS``.
    # Resolve league context once, then use it for both TEP derivation
    # and the roster-count / logging consumers further down.
    league_context = _resolve_league_context()

    # Auto-derive ``tep_multiplier_derived`` from the league's
    # ``bonus_rec_te`` when Sleeper actually returned scoring data AND
    # the league has a positive TE bonus.  Otherwise fall back to the
    # hardcoded ``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` (1.15) so cold-
    # start, offline, and non-TEP leagues keep predictable behavior.
    #
    # Examples:
    #   * TEP-1.5 league (bonus_rec_te=0.5) → derived 1.15
    #   * TEP-2.0 league (bonus_rec_te=1.0) → derived 1.30
    #   * Non-TEP / no Sleeper context       → derived 1.25 (default)
    #
    # When the operator hasn't explicitly overridden via the slider
    # (``tep_multiplier=None``), the derived value becomes the
    # effective multiplier and the summary stamps the source as
    # ``"derived"`` so the frontend can label the slider state
    # ("Auto from league" vs "Custom override").
    try:
        sleeper_bonus = float(league_context.get("bonus_rec_te") or 0.0)
    except (TypeError, ValueError):
        sleeper_bonus = 0.0
    sleeper_real = bool(league_context.get("fetched_from_sleeper"))
    if sleeper_real and sleeper_bonus > 0.0:
        tep_multiplier_derived = _derive_tep_multiplier_from_league(league_context)
        tep_default_source: str = "derived"
    else:
        tep_multiplier_derived = _TE_BLANKET_NON_NATIVE_MULTIPLIER
        tep_default_source = "default"

    if tep_multiplier is None:
        tep_multiplier_effective = tep_multiplier_derived
        tep_multiplier_source = tep_default_source
    else:
        tep_multiplier_effective = float(tep_multiplier)
        tep_multiplier_source = "override"

    if tep_native_multiplier is None:
        tep_native_multiplier_effective = _TE_BLANKET_NATIVE_MULTIPLIER
        tep_native_multiplier_source = "default"
    else:
        tep_native_multiplier_effective = float(tep_native_multiplier)
        tep_native_multiplier_source = "override"
    tep_native_multiplier_derived = _TE_BLANKET_NATIVE_MULTIPLIER

    # TEP-native correction retired: TEP-native sources are now scaled
    # via ``tep_native_multiplier_effective`` inside
    # ``_compute_unified_rankings``; this field is the identity at
    # this layer.
    tep_native_correction = 1.0

    # Two-level copy of raw_payload: shallow at the top, one-deep for
    # the ``players`` dict so per-player mutations stay isolated.  Full
    # ``deepcopy`` of a 3MB payload was 70+ms per call; this lands at
    # ~20ms because we skip the fanout into ``sites``, ``sleeper``, and
    # every site-per-player record (none of which this function ever
    # mutates).  Documented mutation sites are scalar assignments on
    # the player dict and one mutation on the nested
    # ``_canonicalSiteValues`` dict — both isolated by shallow-copying
    # each player's nested dicts/lists.
    src_payload = raw_payload or {}
    base: dict[str, Any] = dict(src_payload)
    src_players = src_payload.get("players") if isinstance(src_payload, dict) else None
    if not isinstance(src_players, dict):
        players_by_name = {}
    else:
        players_by_name = {}
        for _name, _pdata in src_players.items():
            if not isinstance(_pdata, dict):
                players_by_name[_name] = _pdata
                continue
            _copy: dict[str, Any] = {}
            for _k, _v in _pdata.items():
                if isinstance(_v, dict):
                    _copy[_k] = dict(_v)
                elif isinstance(_v, list):
                    _copy[_k] = list(_v)
                else:
                    _copy[_k] = _v
            players_by_name[_name] = _copy
    base["players"] = players_by_name

    # Derive the active rookie draft year from the scrape's own
    # slot-pick names so the discount, rookie-anchor, and synthetic
    # tether passes all key off one self-rolling value (see
    # ``current_rookie_draft_year``).
    set_observed_current_draft_year(_derive_current_draft_year_from_names(players_by_name.keys()))

    # Seed raw entries for far-future pick years the vendors don't
    # price yet (e.g. 2029) so they ride the normal pipeline like the
    # real future tiers.  No-ops the moment sources publish that year.
    _inject_far_future_pick_sources(players_by_name, current_rookie_draft_year())

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
    source_parse_errors: list[dict[str, str]] = []
    csv_index = _enrich_from_source_csvs(
        players_array, parse_errors=source_parse_errors, csv_root=csv_root
    )

    # Post-enrichment position guardrail: CSV enrichment happens AFTER
    # _derive_player_row, so the in-row guardrail there runs against an
    # empty canonicalSiteValues and can't detect offense/IDP mismatches
    # driven by CSV signals. Re-check here with populated values and
    # strip the wrong-family tag rather than letting the contract
    # validator fail the whole rebuild. Typical case: DJ Turner (WR)
    # inherits a DB tag from a sleeper-map name collision with DJ Turner
    # II (CB), then the KTC/FootballGuys CSVs add offensive values to
    # the DB-tagged row.
    _strip_mismatched_family_tags(players_array)

    # Pre-pass: compute offense-only values by disabling all IDP-scoped
    # sources.  The result is stored as ``offenseOnlyRankDerivedValue``
    # on each row and used by trade evaluation endpoints when none of
    # the players in a trade are IDP (DL/LB/DB).  The main pass below
    # then overwrites ``rankDerivedValue`` with the full-source board.
    # Skipped on delta/override builds since those don't feed the
    # trade evaluation path.
    if not source_overrides and not _for_delta:
        _idp_off_overrides: dict[str, dict[str, Any]] = {
            src["key"]: {"include": False}
            for src in _RANKING_SOURCES
            if src.get("scope") in (SOURCE_SCOPE_OVERALL_IDP, SOURCE_SCOPE_POSITION_IDP)
        }
        if _idp_off_overrides:
            # Use shallow copies of both rows and legacy dicts so the
            # pre-pass never stamps canonicalConsensusRank /
            # sourceRankMeta / _canonicalConsensusRank etc. onto the
            # originals.  The main pass below must see unmodified state.
            _pa_copy = [dict(r) for r in players_array]
            _pbn_copy = {
                k: dict(v) if isinstance(v, dict) else v for k, v in players_by_name.items()
            }
            _compute_unified_rankings(
                _pa_copy,
                _pbn_copy,
                csv_index=csv_index,
                source_overrides=_idp_off_overrides,
                tep_multiplier=tep_multiplier_effective,
                tep_native_multiplier=tep_native_multiplier_effective,
                tep_native_correction=tep_native_correction,
                tep_multiplier_is_override=(tep_multiplier_source == "override"),
            )
            for _orig, _copy in zip(players_array, _pa_copy):
                _rdv = _copy.get("rankDerivedValue")
                if isinstance(_rdv, (int, float)) and _rdv > 0:
                    _orig["offenseOnlyRankDerivedValue"] = int(_rdv)

    # Compute unified rankings: all sources, all positions, one board.
    # The CSV index lets the ranker stamp a per-row ``sourceAudit``
    # block describing which CSV row matched each player and why.
    # ``source_overrides`` threads user settings (per-source include /
    # weight knobs) into the same canonical pipeline — there is no
    # secondary ranker anywhere in the stack.  ``tep_multiplier`` is
    # threaded through the same path so TE premium is a
    # backend-authoritative adjustment baked into every ``rankDerivedValue``
    # stamp before the delta / full contract is materialized.
    pick_aliases = _compute_unified_rankings(
        players_array,
        players_by_name,
        csv_index=csv_index,
        source_overrides=source_overrides,
        tep_multiplier=tep_multiplier_effective,
        tep_native_multiplier=tep_native_multiplier_effective,
        tep_native_correction=tep_native_correction,
        tep_multiplier_is_override=(tep_multiplier_source == "override"),
        suppress_market_corridor_clamp=suppress_market_corridor_clamp,
    )

    # Stamp rankDerivedValue into the values bundle so every page uses the
    # same number.  ``_player_value_bundle`` seeds these three keys ``None``
    # (see its SCALE CONTRACT docstring), so a row the blend declined to
    # price keeps ``None`` here and reads as *unpriced* — it does NOT fall
    # back to the legacy scraper composite, which runs on a different
    # scale and would be indistinguishable from a board value.
    #
    # ``values.rawComposite`` still carries the composite, under a name
    # that says so.  It is the UI's explicit "Raw" value mode and must
    # never be spliced into a chain that otherwise reads board values.
    unpriced_rows = 0
    for row in players_array:
        rdv = row.get("rankDerivedValue")
        vals = row.get("values")
        if not isinstance(vals, dict):
            continue
        if rdv is not None and rdv > 0:
            vals["overall"] = rdv
            vals["finalAdjusted"] = rdv
            vals["displayValue"] = rdv
        else:
            unpriced_rows += 1

    # ── Identity validation and quarantine pass ──
    # Runs AFTER rankings are computed so anomalyFlags and confidence can be
    # degraded for suspicious rows.  Does NOT remove rows — quarantined rows
    # remain in the array with quarantined=True and degraded confidenceBucket.
    validation_summary = _validate_and_quarantine_rows(players_array)

    # ── Mirror trust fields to legacy players dict ──
    # The runtime view strips playersArray for payload size.  The frontend
    # falls back to the legacy `players` dict and reads trust fields via
    # `r.raw?.field`.  This pass copies all post-quarantine trust fields
    # so they survive the runtime view.  Skipped on the delta path — the
    # delta payload drops the legacy ``players`` dict entirely.
    if not _for_delta:
        _mirror_trust_to_legacy(players_array, players_by_name)
        # Mirror offenseOnlyRankDerivedValue to the legacy players dict so
        # the trade finder (which reads from the players dict) can use it.
        for _row in players_array:
            _ordv = _row.get("offenseOnlyRankDerivedValue")
            if not isinstance(_ordv, int):
                continue
            _legacy_ref = _row.get("legacyRef")
            if not _legacy_ref or _legacy_ref not in players_by_name:
                continue
            _pdata = players_by_name[_legacy_ref]
            if isinstance(_pdata, dict):
                _pdata["_offenseOnlyFinalAdjusted"] = _ordv

    data_source = data_source or {}
    generated_at = utc_now_iso()

    # ── Payload-level dataFreshness ──
    # sourceTimestamps reads the on-disk mtime for every CSV in
    # _SOURCE_CSV_PATHS and derives a per-source staleness flag from
    # _SOURCE_MAX_AGE_HOURS.  The legacy single-entry shape
    # {ktc: "", idpTradeCalc: ""} was reading dead fields on data_source
    # that the scraper bridge never writes; this replaces it with real,
    # source-by-source freshness data that covers all 5 active sources.
    source_timestamps = _build_source_timestamps()
    _fresh_counts = sum(1 for v in source_timestamps.values() if v.get("staleness") == "fresh")
    _stale_counts = sum(1 for v in source_timestamps.values() if v.get("staleness") == "stale")
    _missing_counts = sum(1 for v in source_timestamps.values() if v.get("staleness") == "missing")
    if _missing_counts > 0:
        _overall_staleness = "missing"
    elif _stale_counts > 0:
        _overall_staleness = "stale"
    elif _fresh_counts > 0:
        _overall_staleness = "fresh"
    else:
        _overall_staleness = "unknown"
    data_freshness: dict[str, Any] = {
        "generatedAt": generated_at,
        "sourceTimestamps": source_timestamps,
        "staleness": _overall_staleness,
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
                "isTepPremium": bool(src.get("is_tep_premium")),
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
            # Corrected 2026-07-29 audit: this block previously
            # published the retired rank-form curve (midpoint 45 /
            # slope 1.10) that no live code path used — the live
            # conversion is the percentile-form Hill curve routed
            # through the scope masters stamped in the ``hillCurves``
            # contract block.
            "name": "Hill curve (percentile form, scope masters)",
            "expression": (
                "p = clamp((rank-1)/(referenceN-1), 0, 1); "
                "value = clamp(9999/(1 + (p/c)^s), 1, 9999)"
            ),
            "referenceN": _PERCENTILE_REFERENCE_N,
            "scopeMasters": "see the hillCurves contract block for per-scope (c, s)",
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
                    "DIAGNOSTIC ONLY: effective_weight = declared_weight * "
                    "min(1, depth / min_full_depth), stamped per source as "
                    "sourceRankMeta.effectiveWeight.  It is never applied to "
                    "the blend — applying it would down-weight the depth-50 "
                    "rookie sources and change the default board."
                ),
                "minFullDepth": 60,
            },
        },
        "blendWeights": {
            "description": (
                "The count-aware mean-median blend multiplies each covered "
                "source's vote by its declared weight "
                "(sourceRankMeta.appliedWeight).  Registry defaults are all "
                "1.0, so the default board gives every covered source an "
                "equal voice; user weight overrides "
                "(POST /api/rankings/overrides) scale a source's vote, and "
                "weight 0 removes the source entirely."
            ),
        },
        # What the LIVE path actually decides on.
        #
        # This block published the legacy absolute-ordinal rule
        # ("sourceRankSpread <= 30 / <= 80") long after
        # ``_compute_unified_rankings`` switched to the percentile
        # signal, so 251 of the 788 bucketed rows on the pinned
        # 2026-07-30 contract — 31.9% — carried a bucket that
        # contradicted the rule published beside them.  Anyone applying
        # the published rule to the published spread got a different
        # answer than the board, on a third of the field.
        #
        # The absolute rule is not dead — it is the fallback for callers
        # that hold only ``source_rank_spread`` — so it is published
        # too, labelled as the fallback rather than as the rule.
        "confidenceBuckets": {
            "high": (
                f"2+ sources, sourceRankPercentileSpread <= " f"{_CONFIDENCE_PERCENTILE_HIGH}"
            ),
            "medium": (
                f"2+ sources, sourceRankPercentileSpread <= " f"{_CONFIDENCE_PERCENTILE_MEDIUM}"
            ),
            "low": (
                f"single source, or sourceRankPercentileSpread > "
                f"{_CONFIDENCE_PERCENTILE_MEDIUM}"
            ),
            "none": "player did not receive a unified rank",
            "signal": "sourceRankPercentileSpread",
            "fallbackRule": {
                "appliesWhen": (
                    "caller supplied only sourceRankSpread (absolute ordinal); "
                    "NOT the live /api/data path"
                ),
                "high": f"2+ sources, sourceRankSpread <= {_CONFIDENCE_SPREAD_HIGH}",
                "medium": f"2+ sources, sourceRankSpread <= {_CONFIDENCE_SPREAD_MEDIUM}",
                "low": f"single source or sourceRankSpread > {_CONFIDENCE_SPREAD_MEDIUM}",
            },
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

    # ── Rankings override summary ──
    # Always produced, even for the default (no-override) response,
    # so downstream consumers (frontend hooks, audit tooling, tests)
    # can hydrate a consistent shape without branching on presence.
    rankings_override = _summarize_source_overrides(
        source_overrides,
        tep_multiplier=tep_multiplier_effective,
        tep_multiplier_derived=tep_multiplier_derived,
        tep_multiplier_source=tep_multiplier_source,
        tep_native_multiplier=tep_native_multiplier_effective,
        tep_native_multiplier_derived=tep_native_multiplier_derived,
        tep_native_multiplier_source=tep_native_multiplier_source,
        tep_native_correction=tep_native_correction,
    )

    contract_payload: dict[str, Any] = {
        **base,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": generated_at,
        # The resolved active rookie-draft year (offset-0, no-penalty
        # class).  Self-rolls with the scrape; serialized so frontend
        # calculators don't carry their own stale copy.
        "currentDraftYear": current_rookie_draft_year(),
        "playersArray": players_array,
        "playerCount": len(players_array),
        # How many rows the blend declined to price.  Those rows carry
        # ``values.overall/finalAdjusted/displayValue = None`` rather than
        # a legacy-composite number on a different scale (math audit H1),
        # so a consumer that silently drops them is visibly dropping a
        # known quantity instead of an invisible one.  Mirrors the
        # ``metadata.assetsUnpricedByBoard`` convention in
        # ``src/trade/finder.py``.
        "rowsUnpricedByBoard": unpriced_rows,
        "valueAuthority": (None if _for_delta else _build_value_authority_summary(players_array)),
        "dataSource": {
            "type": str(data_source.get("type") or ""),
            "path": str(data_source.get("path") or ""),
            "loadedAt": str(data_source.get("loadedAt") or ""),
        },
        "dataFreshness": data_freshness,
        "methodology": methodology,
        "rankingsOverride": rankings_override,
        "anomalySummary": {
            "totalFlagged": total_flagged,
            "flagCounts": anomaly_counts,
        },
        "validationSummary": validation_summary,
        "pickAliases": pick_aliases or {},
        "sourceParseErrors": source_parse_errors,
        "hillCurves": _build_hill_curves_block(),
    }
    # Drop internal-only provenance markers before materializing the
    # contract so they don't leak into the public payload.
    for row in players_array:
        row.pop("_positionFromSleeperOnly", None)
    return contract_payload


# ── Rankings override delta contract ──────────────────────────────────
# Fields on each `playersArray` row that respond to source overrides.
# Anything an override change can mutate — the ranking, the blended
# value, the per-source stamps, the confidence block, and the market
# gap — is listed here.  Anything NOT listed (identity, team, age,
# rookie flag, assetClass, raw site values, identity quality) is
# invariant under an override change and already present on the
# frontend's cached base payload, so the delta merge path can leave
# those fields alone.
_DELTA_PLAYER_FIELDS: tuple[str, ...] = (
    "canonicalConsensusRank",
    "rankDerivedValue",
    "sourceRanks",
    "sourceRankMeta",
    "sourceOriginalRanks",
    "blendedSourceRank",
    "sourceCount",
    "sourceRankSpread",
    "sourceRankPercentileSpread",
    "hillValueSpread",
    "sourceSpread",
    "madPenaltyApplied",
    "anchorValue",
    "subgroupBlendValue",
    "subgroupDelta",
    "alphaShrinkage",
    "softFallbackCount",
    "droppedSources",
    "effectiveSourceRanks",
    "isSingleSource",
    "isStructurallySingleSource",
    "hasSourceDisagreement",
    "confidenceBucket",
    "confidenceLabel",
    "marketGapDirection",
    "marketGapMagnitude",
    "marketGapValueRatio",
    "anomalyFlags",
    "canonicalTierId",
    "marketConfidence",
    "values",
    "idpBackboneFallback",
    "canonicalSiteValues",
    "quarantined",
    "ktcRank",
    "idpRank",
    # Pick-specific stamps.  ``pickYearDiscount`` and
    # ``pickProjectedDraft*`` derive directly from the post-blend
    # ``rankDerivedValue`` — when an override changes the blend, the
    # projection has to update on the same response so the popup's
    # "projected at draft" line stays in sync with the value bar
    # next to it.  Non-pick rows leave these undefined; the frontend
    # branches on ``assetClass === "pick"`` before reading them.
    "pickYearDiscount",
    "pickProjectedDraftValue",
    "pickProjectedDraftYear",
    "pickProjectedDraftValueGain",
    "pickProjectedDraftValueGainPct",
)


def apply_valuation_factors(
    rows: list[dict[str, Any]],
    factors: Mapping[str, float] | None,
    *,
    anchor_year: int | None = None,
) -> int:
    """Multiply ``rankDerivedValue`` by a per-player factor and re-rank.

    Mutates ``rows`` IN PLACE and returns how many rows were re-valued.
    Callers must therefore own ``rows`` — never hand this
    ``latest_contract_data``'s list.  ``build_rankings_delta_payload``
    owns a freshly-built contract, which is why it can.

    This exists so the rankings-override endpoint can serve a board that
    is BOTH re-weighted and league-adjusted.  The client cannot compose
    those two: the overlay's ranks are the ranks of
    ``default_consensus x factor``, while the correct answer is the rank
    of ``overridden_consensus x factor`` — a board the server had never
    computed.  Computing it here is the fix that unblocks the
    combination rather than continuing to refuse it.

    Ranking goes through :func:`compact_ranks_and_tiers`, the one
    ranker, so an adjusted board is ranked by exactly the same rules as
    the default one.
    """
    if not factors:
        return 0
    moved = 0
    for row in rows:
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        factor = factors.get(name)
        base = row.get("rankDerivedValue")
        if factor and isinstance(base, (int, float)) and base > 0:
            row["rankDerivedValue"] = int(round(float(base) * float(factor)))
            moved += 1
    if not moved:
        return 0
    compact_ranks_and_tiers(
        rows,
        anchor_year=anchor_year if anchor_year is not None else current_rookie_draft_year(),
        copy_rows=False,
    )
    return moved


def build_rankings_delta_payload(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
    tep_native_multiplier: float | None = None,
    valuation_factors: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build a compact delta contract for the rankings-override endpoint.

    Runs the full pipeline via ``build_api_data_contract`` and then
    extracts only the override-sensitive fields per player, keyed by
    ``displayName``.  The frontend merges each delta entry onto its
    cached base ``/api/data?view=app`` contract by that key.

    ``tep_multiplier`` follows the same two-mode contract as
    :func:`build_api_data_contract`: ``None`` derives from the Sleeper
    league context; a ``float`` is used verbatim (after clamping).

    The delta drops the legacy ``players`` dict, ``sleeper``,
    ``methodology``, ``poolAudit``, and the full ``playersArray``,
    shrinking the wire payload from ~4MB (full) to ~1.25MB
    (uncompressed) / ~100KB (gzipped).  When gzip is available at the
    transport layer the compounded savings are ~40x on this endpoint.

    Shape:

        {
            "contractVersion": "...",
            "generatedAt": "...",
            "mode": "delta",
            "rankingsOverride": {isCustomized, enabledSources, ...},
            "rankingsDelta": {
                "playerKey": "displayName",
                "players": [
                    {"id": "Josh Allen", "canonicalConsensusRank": 1, ...},
                    ...
                ],
                "activePlayerIds": ["Josh Allen", ...],
            },
            ...
        }
    """
    full = build_api_data_contract(
        raw_payload,
        data_source=data_source,
        source_overrides=source_overrides,
        tep_multiplier=tep_multiplier,
        tep_native_multiplier=tep_native_multiplier,
        _for_delta=True,
    )

    # League-adjusted composition.  Applied AFTER the override pipeline
    # has produced the re-weighted board, so the factors land on the
    # user's own consensus values and the re-rank is over that board —
    # not over the default one.  ``full`` is freshly built and owned by
    # this call, so mutating its rows is safe.
    valuation_adjusted_count = 0
    if valuation_factors:
        valuation_adjusted_count = apply_valuation_factors(
            full.get("playersArray") or [],
            valuation_factors,
        )

    delta_players: list[dict[str, Any]] = []
    active_ids: list[str] = []
    for row in full.get("playersArray") or []:
        player_id = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if not player_id:
            continue
        entry: dict[str, Any] = {"id": player_id}
        for field in _DELTA_PLAYER_FIELDS:
            if field in row:
                entry[field] = row[field]
        delta_players.append(entry)
        if row.get("canonicalConsensusRank"):
            active_ids.append(player_id)

    payload: dict[str, Any] = {
        "contractVersion": full.get("contractVersion"),
        "generatedAt": full.get("generatedAt"),
        "currentDraftYear": full.get("currentDraftYear"),
        "date": full.get("date"),
        "scrapeTimestamp": full.get("scrapeTimestamp"),
        "mode": "delta",
        "rankingsOverride": full.get("rankingsOverride"),
        "rankingsDelta": {
            "playerKey": "displayName",
            "players": delta_players,
            "activePlayerIds": active_ids,
        },
        "anomalySummary": full.get("anomalySummary"),
        "dataFreshness": full.get("dataFreshness"),
        "dataSource": full.get("dataSource"),
        "playerCount": full.get("playerCount"),
    }
    if valuation_factors is not None:
        # Stamped whether or not anything moved.  "the lens was applied
        # and moved nothing" and "the lens was never applied" are
        # different states, and a client that cannot tell them apart
        # will render one as the other.
        payload["valuationAdjustment"] = {
            "applied": True,
            "adjustedCount": valuation_adjusted_count,
            "factorCount": len(valuation_factors),
        }
    warnings = full.get("warnings")
    if warnings:
        payload["warnings"] = list(warnings)
    return payload


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
    """Return a list of top-N players that are single-source WITH a
    matching failure but no allowlist reason.

    Only rows whose sourceAudit reason is
    ``matching_failure_other_sources_eligible`` are candidates — i.e.,
    at least one additional source was EXPECTED to cover this player
    but didn't.  ``structurally_single_source`` rows (no other source
    was expected, typically because the player sits outside shallow
    sources' depth/scope) are benign and not flagged here.

    Each entry in the returned list is a dict with:
      - canonicalName, position, rank, matchedSources, reason

    An empty list means every flagged 1-src player in the top N is
    either fixed or explicitly justified in ``SINGLE_SOURCE_ALLOWLIST``.
    """
    # Quarantine flags that represent identity / join regressions this
    # gate is specifically designed to surface — never skip rows that
    # carry any of these even when the same row also carries
    # ``no_valid_source_values``.  Mirrors ``_QUARANTINE_FLAGS`` minus
    # the transient no-value bucket; kept as a local literal so this
    # public helper doesn't take a hidden module-private dependency.
    _REGRESSION_QUARANTINE_FLAGS = (
        "duplicate_canonical_identity",
        "position_source_contradiction",
        "unsupported_position",
    )
    unexplained: list[dict[str, Any]] = []
    for row in players_array:
        rank = row.get("canonicalConsensusRank")
        if rank is None or rank > rank_limit:
            continue
        # Skip rows quarantined PURELY for ``no_valid_source_values``
        # (i.e. carrying that flag and none of the regression flags
        # above).  Those are fringe rookies / IDPs whose CSV stamps
        # round to zero across every source; they trip
        # ``isSingleSource`` the moment the daily refresh nudges their
        # consensus rank into the top-N cap, even though the
        # quarantine gate (``test_quarantined_under_threshold``)
        # already surfaces the same row.
        #
        # Membership-only check (``"no_valid_source_values" in flags``)
        # would let a mixed-flag row — quarantined for both
        # no-value AND a real identity regression — silently slip
        # through this gate.  Codex PR #357 P1 review caught that;
        # the exclusive check below preserves the cascade
        # suppression while keeping the join-regression intent.
        anomaly_flags = row.get("anomalyFlags") or []
        if (
            row.get("quarantined")
            and "no_valid_source_values" in anomaly_flags
            and not any(f in anomaly_flags for f in _REGRESSION_QUARANTINE_FLAGS)
        ):
            continue
        audit = row.get("sourceAudit") or {}
        if audit.get("reason") != "matching_failure_other_sources_eligible":
            # Structurally single-source plays are benign — no other
            # source was expected to cover them (e.g. IDPTC-only deep
            # veteran DLs past DLF/FP/FBG IDP's published cuts).  The
            # framework's soft fallback still pulls them toward the
            # market via the other sources' "just past the published
            # list" values, so they're not actually single-opinion
            # picks.
            continue
        if audit.get("allowlistReason"):
            continue
        unexplained.append(
            {
                "canonicalName": row.get("canonicalName"),
                "position": row.get("position"),
                "rank": rank,
                "matchedSources": audit.get("matchedSources", []),
                "reason": audit.get("reason"),
            }
        )
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
            errors.append(f"#{rank} {name}: has rank but no rankDerivedValue")

        # Check 2: no duplicate ranks
        if rank in seen_ranks:
            errors.append(f"#{rank} {name}: duplicate rank (also assigned to {seen_ranks[rank]})")
        seen_ranks[rank] = name

        # Check 3: monotonic rank (strictly increasing)
        if prev_rank is not None and rank <= prev_rank:
            errors.append(
                f"#{rank} {name}: rank not strictly increasing (prev #{prev_rank} {prev_name})"
            )

        # Check 4: value monotonically decreasing with rank
        if prev_value is not None and value is not None and prev_value > 0 and value > prev_value:
            errors.append(
                f"#{rank} {name}: value {value} > prev value {prev_value} "
                f"(#{prev_rank} {prev_name}) — rank/value order divergence"
            )

        # Check 5: tier non-decreasing
        if prev_tier is not None and tier is not None and tier < prev_tier:
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
    degraded = False  # Soft-fail flag: non-fatal issues that still merit a degraded status
    below_floor_count = 0
    any_source_missing = False

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
            is_known_collision = name in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS
            if len(players_array) >= 250 and (has_collision or is_known_collision):
                pass
            else:
                errors.append(
                    f"playersArray offense→IDP mismatch: {name or '<unknown>'} tagged {pos} "
                    "with offensive-only source signal(s)"
                )

        if name:
            norm = _canonical_match_key(name) or re.sub(r"[^a-z0-9]+", "", str(name).lower())
            normalized_pos_by_name.setdefault(norm, set()).add(pos or "?")

    for norm_name, poses in normalized_pos_by_name.items():
        cleaned = {p for p in poses if p and p != "?"}
        has_off = bool(cleaned & _OFFENSE_POSITIONS)
        has_idp = bool(cleaned & _IDP_POSITIONS)
        if has_off and has_idp:
            errors.append(
                f"possible offense/IDP name collision detected for normalized name '{norm_name}'"
            )

    if len(players_array) >= 250 and idp_count < 25:
        errors.append(
            f"implausibly small IDP pool in playersArray: {idp_count}/{len(players_array)} "
            "(expected at least 25 when full board is present)"
        )

    # ── Per-source row-count floors ─────────────────────────────────────
    # Count non-zero canonicalSiteValues per source and compare against a
    # tunable floor loaded from config/weights/source_row_floors.json.
    # A source at zero is a hard error (source_missing); below floor is a
    # warning (source_below_floor).  If 2+ sources fall below floor OR any
    # source is missing, we flip the overall status to degraded.
    if len(players_array) >= 250:
        row_floors = _load_source_row_floors()
        source_nonzero_counts: dict[str, int] = {k: 0 for k in row_floors}
        for row in players_array:
            if not isinstance(row, dict):
                continue
            sites_map = row.get("canonicalSiteValues")
            if not isinstance(sites_map, dict):
                continue
            for src_key in row_floors:
                val = _to_int_or_none(sites_map.get(src_key))
                if val is not None and val > 0:
                    source_nonzero_counts[src_key] += 1

        for src_key, threshold in row_floors.items():
            count = source_nonzero_counts.get(src_key, 0)
            if count == 0:
                errors.append(f"source_missing:{src_key}")
                any_source_missing = True
            elif count < threshold:
                warnings.append(f"source_below_floor:{src_key}:{count}:{threshold}")
                below_floor_count += 1

        if any_source_missing or below_floor_count >= 2:
            degraded = True

    # ── Pick-count floor ────────────────────────────────────────────────
    # Count draft picks on the board and error if below floor.  Live
    # carries ~126 picks; floor is 100 (≈80% baseline) per the audit
    # recommendation.  Missing pickAnchors is also an error.
    if len(players_array) >= 250:
        pick_count = sum(
            1 for row in players_array if isinstance(row, dict) and row.get("assetClass") == "pick"
        )
        if pick_count < _PICK_COUNT_FLOOR:
            errors.append(f"pick_count_below_floor:{pick_count}:{_PICK_COUNT_FLOOR}")
        pick_anchors = payload.get("pickAnchors")
        if pick_anchors is None:
            errors.append("pickAnchors missing from payload")
        elif isinstance(pick_anchors, dict) and not pick_anchors:
            errors.append("pickAnchors is empty")

    # ── Top-50 per-source coverage floors ───────────────────────────────
    # Sort each asset class (offense / idp) by values.overall desc and
    # take the first 50 rows.  For each configured source + bucket,
    # count non-zero canonicalSiteValues entries.  Below floor = warning
    # + degraded; too few rows to even check = warning (but not
    # degraded — the row-count floor already covers that).
    if len(players_array) >= 250:
        coverage_floors = _load_top50_coverage_floors()

        def _overall_val(r: dict[str, Any]) -> float:
            # Rank on the board value directly.  This used to read
            # ``values.overall``, which was the board value for priced rows
            # but the legacy scraper composite for unpriced ones — so the
            # "top 50" could be ordered across two scales (math audit H1).
            # ``values.overall`` now mirrors ``rankDerivedValue`` exactly,
            # but reading the source of truth makes that independent of the
            # mirroring step rather than dependent on it.
            try:
                return float(r.get("rankDerivedValue") or 0)
            except (TypeError, ValueError):
                return 0.0

        for bucket, src_floors in coverage_floors.items():
            bucket_rows = [
                r for r in players_array if isinstance(r, dict) and r.get("assetClass") == bucket
            ]
            if len(bucket_rows) < 50:
                warnings.append(f"top50_coverage_insufficient_rows:{bucket}:{len(bucket_rows)}")
                continue
            bucket_rows.sort(key=lambda r: -_overall_val(r))
            top_slice = bucket_rows[:50]
            for src_key, floor in src_floors.items():
                count = 0
                for r in top_slice:
                    sites_map = r.get("canonicalSiteValues")
                    if not isinstance(sites_map, dict):
                        continue
                    val = _to_int_or_none(sites_map.get(src_key))
                    if val is not None and val > 0:
                        count += 1
                if count < floor:
                    warnings.append(
                        f"top50_coverage_below_floor:{bucket}:{src_key}:{count}:{floor}"
                    )
                    degraded = True

    # ── Payload-size regression floor ───────────────────────────────────
    # Serialize the validated payload and compare against the 2MB floor.
    # Below floor = warning + degraded.  Guards against the April 9
    # 4.6MB → 770KB regression where a heavy-field pruning bug shipped
    # a catastrophically small but otherwise valid contract.
    #
    # Gated by len(players_array) >= 250 so minimal-payload unit tests
    # (with 1-10 synthetic players) don't trip the floor.  A 2MB floor
    # only makes sense on a full production board.
    if len(players_array) >= 250:
        try:
            size_bytes, size_ok = assert_payload_size_floor(payload)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"payload_size_probe_failed:{type(exc).__name__}")
        else:
            if not size_ok:
                warnings.append(
                    f"payload_size_below_floor:{size_bytes}:{_PAYLOAD_SIZE_FLOOR_BYTES}"
                )
                degraded = True

    # ── sourceParseErrors surfaced from _enrich_from_source_csvs ────────
    parse_errors_list = payload.get("sourceParseErrors")
    if isinstance(parse_errors_list, list) and parse_errors_list:
        for perr in parse_errors_list[:50]:
            if not isinstance(perr, dict):
                continue
            warnings.append(
                f"source_parse_error:{perr.get('source', '?')}:{perr.get('error', '?')}"
            )
        degraded = True

    # ── Cross-wire sourceRunSummary.partialRun into contractHealth ──────
    # The scraper reports partial/failed sources in
    # settings.sourceRunSummary.  Historically those were invisible to the
    # contract health check, so a prod build could have
    # partialSources=['KTC_TradeDB'] while contractHealth said "healthy".
    # We now promote critical partials to errors and leave tolerable
    # partials (KTC_TradeDB / KTC_WaiverDB) as warnings.
    settings_block = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    run_summary = (
        settings_block.get("sourceRunSummary") if isinstance(settings_block, dict) else None
    )
    if isinstance(run_summary, dict):
        overall_status = run_summary.get("overallStatus")
        is_partial_run = bool(run_summary.get("partialRun")) or overall_status == "partial"
        if is_partial_run:
            partial_sources_list = run_summary.get("partialSources") or []
            failed_sources_list = run_summary.get("failedSources") or []
            timed_out_sources_list = run_summary.get("timedOutSources") or []
            all_degraded_sources: list[str] = []
            for lst in (partial_sources_list, failed_sources_list, timed_out_sources_list):
                if isinstance(lst, list):
                    all_degraded_sources.extend(str(s) for s in lst if s)

            for src in all_degraded_sources:
                if src in TOLERABLE_PARTIAL_SOURCES:
                    warnings.append(f"partial_run_tolerable:{src}")
                    continue
                # Critical match: exact name of a primary source, or a
                # prefix match for IDPTradeCalc's sub-endpoints.
                is_critical = src in _CRITICAL_PRIMARY_SOURCES or src.startswith("IDPTradeCalc")
                if is_critical:
                    errors.append(f"partial_run_critical:{src}")
                else:
                    warnings.append(f"partial_run_unknown:{src}")

    if not players_array:
        warnings.append("playersArray is empty")
    if not site_keys:
        warnings.append("sites is empty or missing keys")

    ok = len(errors) == 0
    if not ok:
        status = "invalid"
    elif degraded:
        status = "degraded"
    else:
        status = "healthy"
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
