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

#: The canonical value scale, imported rather than restated.
#: ``DISPLAY_SCALE_MAX`` is the numerator of the Hill family the board is
#: built from (``V(p) = 9999 / (1 + (p/c)^s)``), i.e. its ASYMPTOTE — so
#: it is the one owner of "how high a canonical value can go", and both
#: the published ``methodology.formula`` block and the contract validator
#: read it from here.  A second literal would be a second scale.
from src.canonical.player_valuation import (  # noqa: E402  — grouped with its sibling
    DISPLAY_SCALE_MAX as _CANONICAL_VALUE_MAX,
    DISPLAY_SCALE_MIN as _CANONICAL_VALUE_MIN,
)
from src.data_models.contracts import utc_now_iso
from src.ros import lineup as lineup_owner

#: C1-U6-D1 — the single owner of the slot↔tier tables.  This module is a
#: CONSUMER: it must never restate a tier range (audit 2026-08-17).
from src.picks import site_pick_map as _site_pick_map

#: B11 — the single owner of "how good is the evidence behind this value".
#: This module ASSEMBLES the evidence; it decides no confidence level.
from src.api.confidence import (  # noqa: E402  — grouped with its siblings
    CONFIDENCE_BASES,
    FamilyEvidence,
    assess_confidence,
    assess_pick_confidence,
    degrade_for_quarantine,
    gate_parameter as _confidence_gate_parameter,
)

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

#: Legacy field names still emitted alongside their honest replacements, and
#: the version at which they stop being emitted.  C1-U5 (`C1-CONF-01`).
#:
#: Kept for the deprecation window because a rolling deploy can serve an old
#: bundle a new payload and vice versa, and because ``exports/archive/*.zip``
#: is immutable evidence written under the old spellings — archive readers stay
#: bilingual permanently, which is a different lifetime from these aliases.
#: An alias is a temporary promise to writers; bilingual reading is a permanent
#: property of a reader of immutable history.
DEPRECATED_FIELD_ALIASES: tuple[dict[str, str], ...] = (
    {
        "field": "identityConfidence",
        "replacedBy": "identityResolutionConfidence",
        "reason": "grades source-row-to-player RESOLUTION, not evidence quality",
        "since": "2026-08-17",
        "removeAfterContractVersion": "2026-03-10.v3",
    },
    {
        "field": "identityMethod",
        "replacedBy": "identityResolutionMethod",
        "reason": "travels with identityConfidence; renaming one and not the other splits a pair",
        "since": "2026-08-17",
        "removeAfterContractVersion": "2026-03-10.v3",
    },
    {
        "field": "marketConfidence",
        "replacedBy": "marketBreadthAgreementIndex",
        "reason": (
            "a bounded site-count x dispersion blend measured to span [0.3252, 0.59375] "
            "on the live board — it never reaches the top 40% of the 0-1 scale its name implied"
        ),
        "since": "2026-08-17",
        "removeAfterContractVersion": "2026-03-10.v3",
    },
)

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
    "idpShowCombined",
}

# All source signal keys — used to detect which source(s) a player has
_ALL_SIGNAL_KEYS = _OFFENSE_SIGNAL_KEYS | _IDP_SIGNAL_KEYS

# ── Confidence: RETIRED HERE, OWNED BY src/api/confidence.py (B11) ──────────
#
# There used to be four constants at this spot — ``_CONFIDENCE_PERCENTILE_
# HIGH/MEDIUM`` (0.08 / 0.20) and an absolute-ordinal fallback pair
# (30 / 80) — bucketing a row on ``max(percentile) − min(percentile)``
# across its contributing sources, behind an ``n >= 2`` count gate.
#
# Deleted rather than re-tuned.  A range can only preserve or narrow when
# an observation is removed, so under "narrower ⇒ more confident"
# **deleting evidence promoted a row**.  PR #833 recorded the failed
# repair: re-basing the same statistic onto independent evidence moved 60
# rows the WRONG way (A.J. Brown medium → high) purely because collapsing
# his FantasyPros family removed one endpoint.  The input population was
# never the defect; the statistic was, and a threshold pair around it
# could not be anything but a different-sized version of the same bug.
#
# ``src/api/confidence.py`` owns the replacement outright — five axes over
# B10 provider families, combined by bottleneck, parameterised from
# ``config/confidence/gate_v1.json``.  ``sourceRankPercentileSpread`` is
# still computed and still published: it remains a useful diagnostic and
# it still drives ``hasSourceDisagreement``.  It no longer decides
# confidence.
#
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
#   "blend_integrity_violation"     — blended value fell OUTSIDE the range of
#                                     its own source contributions, which is
#                                     structurally impossible under correct
#                                     operation (stamped by
#                                     ``_detect_blend_integrity_violations``)
#
# The legacy ``near_name_value_mismatch`` flag was retired (see
# ``_validate_and_quarantine_rows`` Check 3 for rationale).  It used to
# fire here but the underlying rule produced only false positives.
#
# ``blend_integrity_violation`` is quarantine-level for the same reason
# the others are: the row's value cannot be trusted as an ordinary
# canonical number.  It is deliberately NOT accompanied by a correction —
# the retired market corridor coerced such rows toward a plausible value
# and thereby destroyed the evidence of the fault.  Quarantine is how this
# codebase already says "present but not consumable"; that is the whole
# mechanism, and no second one was invented for this detector.
_QUARANTINE_FLAGS = {
    "duplicate_canonical_identity",
    "position_source_contradiction",
    "unsupported_position",
    "no_valid_source_values",
    "blend_integrity_violation",
}

# CSV export paths for source enrichment (relative to repo root).
#
# Each entry is either:
#   * a plain string path — legacy "name,value" CSV, higher is better
#   * a dict { path, signal } — "value" for name,value CSVs, "rank" for
#     name,rank CSVs (lower is better, stamped as a synthetic monotonic
#     value via _RANK_TO_SYNTHETIC_VALUE so the downstream descending
#     sort in _compute_unified_rankings produces the correct ordinal)
# ── Provider-ID column resolution (W06-F009) ─────────────────────────
#
# A vendor CSV that ships a Sleeper player id gives ID-grade identity,
# which survives the vendor/Sleeper name drift that breaks a name join
# ("Kenneth Gainwell" vs "Kenny Gainwell").  The loader used to find that
# column by testing the header against a hand-maintained tuple of literal
# spellings, which failed closed: ``dynastyNerdsSfTep.csv`` ships
# ``SleeperId`` — a spelling nobody had added — so all 294 of its rows
# carried no id and the source joined by name only, silently.
#
# The root cause is the enumerated-literal list, not the missing entry.
# Columns are matched on a NORMALIZED token (casefold, drop separators)
# so every reasonable spelling of the same field resolves, while a
# different field does not: ``sleeper_id_source`` normalizes to
# ``sleeperidsource`` and is correctly ignored.  Being conservative here
# is the point — attaching the wrong id is a confident wrong match, which
# is worse than the miss it replaces.
#
# Measured at the time of the repair: the ID join recovers **0 rows** on
# the live board (the name cascade already resolved 293 of 294 and the
# two agreed on all 290 overlaps, zero contradictions).  This buys
# resilience, not match rate.
_SLEEPER_ID_TOKENS: frozenset[str] = frozenset(
    {
        "sleeperid",
        "sleeperplayerid",
    }
)


def _normalize_header_token(column: object) -> str:
    """Casefold a CSV header and drop separators, for token matching.

    ``"Sleeper Id"``, ``"sleeper_id"``, ``"SleeperId"`` and
    ``"sleeper-id"`` all become ``"sleeperid"``.  Anything carrying extra
    words keeps them, so it will not collide with a bare field name.
    """
    s = str(column or "").strip().lower()
    return "".join(ch for ch in s if ch.isalnum())


def _pick_provider_id(csvrow: dict[str, Any], tokens: frozenset[str]) -> str:
    """First non-empty value whose header normalizes into ``tokens``.

    Iteration order follows the row's own key order, so a CSV carrying two
    accepted spellings resolves deterministically to the first one rather
    than to whichever the set happened to yield.
    """
    if not isinstance(csvrow, dict):
        return ""
    for key, value in csvrow.items():
        if value in (None, ""):
            continue
        if _normalize_header_token(key) in tokens:
            return str(value)
    return ""


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
    # The IDP Show (Adamidp) — OWNER DECISION 2026-08-20: the provider
    # family's SOLE voting board is now the COMBINED offense+IDP Top-700
    # board (theidpshow.com/p/combined-idp-offense-dynasty-rankings-...),
    # not the older IDP-only board at idpShow.csv.  Both are Substack-
    # hosted, served from an embedded Datawrapper iframe, fetched by
    # ``scripts/fetch_idpshow.py`` (``--combined`` selects this one,
    # picking the WIDEST of the article's chart embeds by measured row
    # count — see ``_pick_widest_chart`` — because the combined article
    # embeds a 250-row excerpt ahead of the real ~665-700 row board).
    # Signal=rank: the chart's TRADE VALUE column is draft-pick-
    # equivalent text ("1st + 2nd"), not numeric, so the rank column is
    # the ordinal signal.  Registered ``is_cross_market=True`` below
    # (unlike the retired idpShow.csv) because this board's rank is
    # ALREADY a native combined offense+IDP ordinal — Bijan Robinson #1,
    # Josh Allen #2 — so it needs no shared-market crosswalk through
    # another source's ladder; see the registry entry's comment below
    # for the full rationale.
    #
    # The old ``idpShow.csv`` (IDP-only, ~350 rows) remains ACQUIRED
    # (the fetch script's default, no-flag path still writes it, and the
    # prod timer still refreshes it — see
    # ``deploy/idpshow_fetch_and_push.sh``) but is deliberately left
    # UNREGISTERED here — the same acquired-but-not-a-ranking-source
    # posture ``draftSharksRosSf.csv`` already has (see the
    # ``draftSharks`` entry below).  An unregistered CSV cannot vote:
    # ``_enrich_from_source_csvs`` only reads keys present in this dict,
    # so removing the entry is a structural guarantee, not a policy
    # flag that could be silently re-enabled.  Never register a second
    # ``idpShow*`` key alongside this one — same-provider double
    # counting is forbidden by the correlation-group rules this
    # registry enforces elsewhere (see ``correlation_group`` on the
    # ``idpShowCombined`` entry, and
    # ``tests/api/test_idpshow_combined_source.py::
    # TestExactlyOneVotingIdpShowKey``).
    "idpShowCombined": {
        "path": "CSVs/site_raw/idpShowCombined.csv",
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
# AUDIT F-18 (2026-08-18).  Every budget here is a bound on how stale the
# FETCH may be, because that is what the signal measures:
# ``_build_source_timestamps`` prefers ``data/scrape_state/<key>_last_success``,
# which is written on fetch success, and falls back to CSV mtime only when no
# stamp exists.  It is NOT a bound on how often the vendor publishes — mtime
# and a success stamp cannot observe that.
#
# Seven entries used to be 168h or 720h, each justified in-comment by the
# vendor's editorial cadence, while carrying a fetch-success stamp that
# measured 1.1-1.7h old.  A 720h budget was ~400x the observed fetch interval,
# so any of them could have stopped fetching for a month while every row
# resting on it kept claiming current evidence — audit finding F-6's failure
# mode with the confidence gate blind to it.
#
# They are now 24, which is not a new number: it is what
# ``config/source_staleness.json`` gives them and what
# ``scheduled-refresh.yml``'s own "Assert DLF freshness" step already enforces
# (``THRESHOLD_HOURS=24``, commented "same threshold the email alert engine
# uses").  Deliberately NOT the 6h of the #532 correction below: that
# derivation was made for CI 2-hourly fetchers and three of these run
# production-side, so 24 is the value two existing owners already state and
# needs no new derivation of mine.
#
# The relation is pinned by
# ``tests/api/test_freshness_budget_not_laxer_than_alerts.py``: this map may
# never be laxer than the alert engine, because the board must not count
# evidence as current after the operator has been told it is stale.
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
    "flockFantasySf": 24,
    # Flock Fantasy rookie board: fetched on the 2-hourly refresh like
    # the vet board, so it shares the same fetch-success budget.  (It was
    # 168h, justified by how often the experts re-rank — F-18.)
    "flockFantasySfRookies": 24,
    "dlfIdp": 24,
    "dlfSf": 24,
    # Yahoo / Justin Boone: the CHART refreshes ~monthly, but the fetcher
    # runs on the 2-hourly refresh and stamps on success, so 24h bounds the
    # thing we can actually observe.  The fetcher emits its own stale-article
    # warning for the publication question.  (Was 720h — F-18.)
    "yahooBoone": 24,
    # FantasyPros / Pat Fitzmaurice Dynasty Trade Value Chart: the ARTICLE
    # is monthly; the fetch is 2-hourly and stamped, and this budget bounds
    # the fetch.  (Was 720h — F-18.)
    "fantasyProsFitzmaurice": 24,
    # The IDP Show (Adamidp): a lapsed hand-minted cookie is exactly what
    # this should surface, and 24h matches config/source_staleness.json,
    # which also flags idpShow SOFT with a 72h escalation — so a re-mint
    # chore stays quiet for a day without the budget hiding a dead fetcher
    # for a month.  (Was 720h — F-18.)  Tracked even though this key is
    # UNREGISTERED (retired from voting 2026-08-20 — see the
    # ``idpShowCombined`` registry entry) because the same prod timer
    # still refreshes ``idpShow.csv`` and a silently-dead fetcher on an
    # acquired-but-inert file is still worth surfacing.
    "idpShow": 24,
    # The IDP Show COMBINED board — same paywalled cookie, same timer
    # (deploy/idpshow_fetch_and_push.sh runs the fetcher twice, once
    # per board), so the same 24h budget applies.  This is now the
    # PROVIDER FAMILY'S SOLE VOTING KEY (Task 1/2, 2026-08-20).
    "idpShowCombined": 24,
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
    # ``ktcSfTep`` — KTC's SF/TE++ sub-board, and the single most
    # load-bearing offense input on the board: the only ``is_retail``
    # source, the TE basis every non-TEP TE row is converted ONTO
    # (ADR-015), half the pick anchor set, and the head of the ``ktc``
    # correlation group.  It had NO floor until audit finding F-10
    # (2026-08-18), so it could fall to zero rows in total silence.
    #
    # Measured, with the TE++ board removed and the base ``ktc`` CSV left
    # intact — the exact failure ``_ktc_extract_tep``'s docstring records
    # (a KTC payload shape change makes the extractor return ``None`` and
    # write an empty ktcSfTep.csv, while ktc.csv is fine): the contract
    # validated ``ok=True``, ``sourceHealthErrors=[]``, coverageAudit
    # reported zero deficits — and 444 of 468 comparable offense rows
    # moved, median |Δ| 804, max 8405.  Both CI lanes passed.
    #
    # 400 is not a new number: it is ~80% of the 501-row live baseline
    # (this file's stated policy) AND the floor already carried by
    # ``ktc``, the twin board produced from the same KTC API payload with
    # an identical 501-row count.  Guarding the voting board more loosely
    # than the display-only one is what created the gap.
    "ktcSfTep": 400,
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
    # The IDP Show (IDP-only) floor is REMOVED, not kept, as of
    # 2026-08-20 — see the ``idpShowCombined`` registry entry.  This
    # dict's floor gate reads ``canonicalSiteValues`` population for
    # every key in ``set(get_ranking_source_keys()) | set(row_floors)``
    # (``_compute_unified_rankings``'s per-source row-count-floor
    # block), and an UNREGISTERED source can never populate that column
    # — the entry would trip ``source_missing:idpShow`` as a permanent,
    # unfixable hard error rather than surface a real fetch problem.
    # The file is still fetched and its own acquisition floor
    # (``_IDPSHOW_ROW_FLOOR`` in ``scripts/fetch_idpshow.py``) still
    # guards the fetch itself; this contract-level gate is specifically
    # about VOTING coverage, which an unregistered source structurally
    # cannot have.
    #
    # The IDP Show COMBINED board (665 raw rows / 662 distinct names
    # at the 2026-08-20 acquisition).  A cross-source proxy match
    # (normalized-name overlap against the ktc.csv + idpTradeCalc.csv
    # union, 928 distinct names) found 653/662 (98.6%) — NOT the true
    # Sleeper-pool canonicalization rate (that universe is broader and
    # more IDP-deep than Sleeper's own roster, so it overstates true
    # match odds), but a real, measured floor for "did the fetch/parse
    # come back intact" rather than a fabricated 700.  Floor set well
    # below the measured proxy match so genuine vendor churn (a few
    # dozen players added/dropped week to week) doesn't trip it, while
    # a truncated fetch — e.g. picking the 250-row excerpt chart again
    # instead of the widest one — still does.
    "idpShowCombined": 450,
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
# Sub-endpoints known to flip to partial without impacting the primary
# ranking data, reported as warnings rather than errors.  Critical
# failures use the full source names (``KTC``, ``IDPTradeCalc``,
# ``DLF``, ``DynastyNerds``) and bypass this allowlist entirely.
#
# DELIBERATELY EMPTY since 2026-08-18.  Its only two members were
# ``KTC_TradeDB`` and ``KTC_WaiverDB``, which were retired along with the
# rest of the dead KTC crowd path — they had reported partial on every
# run for months, and because they were allowlisted, that permanent
# failure was never once surfaced as anything a human had to look at.
#
# An entry here silences a source forever.  Add one only as a recorded
# decision about a source that is genuinely secondary, never to quiet a
# noisy check — the alternative is what this list just taught us.
TOLERABLE_PARTIAL_SOURCES: frozenset[str] = frozenset()

# Primary sources whose partial/failed state should flip contractHealth.
_CRITICAL_PRIMARY_SOURCES: tuple[str, ...] = (
    "KTC",
    "IDPTradeCalc",
    "DLF",
    "DynastyNerds",
)


def critical_primary_for_run_source(run_source: str) -> str | None:
    """The critical primary source a scraper RUN name reports for, or ``None``.

    The scraper's run registries name a source by its transport, not only
    by its identity — ``source_enabled_map`` in ``Dynasty Scraper.py``
    reads ``SITES.get("DLF")`` and registers the result as
    ``"DLF_LocalCSV"`` — so the name that reaches
    ``sourceRunSummary.failedSources`` is the primary source name,
    optionally qualified with an underscore suffix (``DLF_LocalCSV``,
    historically ``KTC_TradeDB`` / ``KTC_WaiverDB``).  Matching run names
    against :data:`_CRITICAL_PRIMARY_SOURCES` verbatim therefore could not
    fire for DLF at all: a DLF failure arrived as ``DLF_LocalCSV``, matched
    nothing, and fell through to the ``partial_run_unknown`` WARNING for
    one of the four sources this file declares critical (audit F-17 /
    V1-80).

    This is the ONE derivation rule from run name to critical primary —
    exact match, or ``<primary>_<qualifier>`` — deliberately NOT a fourth
    hand-maintained name list (F-17 rules that out as the defect, not the
    fix).  ``IDPTradeCalc`` keeps its historical bare-prefix match so any
    unqualified sub-endpoint name it ever emitted stays critical.

    The qualifier separator is ``_`` because that is the scraper's own
    naming convention; run names whose primary is NOT critical resolve to
    ``None`` and stay warnings (``DraftSharks_IDP``, ``FantasyPros_IDP``).
    """
    for primary in _CRITICAL_PRIMARY_SOURCES:
        if run_source == primary or run_source.startswith(primary + "_"):
            return primary
    if run_source.startswith("IDPTradeCalc"):
        return "IDPTradeCalc"
    return None


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
from src.bridges.assess import assess_bridges  # noqa: E402
from src.bridges.states import QUALIFIED as BRIDGE_QUALIFIED  # noqa: E402
from src.bridges.ladder import build_bridge_ladder  # noqa: E402
from src.bridges.registry import load_bridge_descriptors  # noqa: E402
from src.sources.acquisition_state import UNAVAILABLE as ACQ_UNAVAILABLE  # noqa: E402
from src.sources.acquisition_state import AcquisitionOutcome  # noqa: E402
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
# ── Game type — C1-SRC-02 ────────────────────────────────────────────
#
# **This is a dynasty product, and dynasty eligibility is PROVEN per
# endpoint rather than inferred from the provider.**  A site that
# publishes dynasty content is not globally "dynasty": FantasyCalc's
# same endpoint serves redraft on a different flag, FantasyPros exposes
# dynasty and weekly as distinct URLs, and DraftSharks publishes ROS
# boards alongside its dynasty ones.
#
# Recorded as a manifest row (`C1-SRC-02`) that read COMPLETE while no
# field, no gate and no test existed — the property was true of the
# registered 21 only because each was hand-verified in a COMMENT.  A
# convention that a new entry can silently violate is not a guarantee,
# so the vocabulary and the import-time gate below are the first
# executable form of it.
#
# ``docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`` §1.1: "Only
# ``DYNASTY`` observations are eligible ... ``UNKNOWN/UNVERIFIED`` fails
# closed and must not be silently accepted."  Non-dynasty values are
# representable ON PURPOSE — a board we have identified as redraft is a
# different fact from one nobody has checked, and quarantining the first
# is only possible if it can be named.
GAME_TYPE_DYNASTY = "DYNASTY"

#: Closed set.  ``UNKNOWN`` is the default an unproven feed must carry,
#: and is exactly what the gate refuses — "missing is never zero, and
#: unverified is never dynasty".
GAME_TYPES: frozenset[str] = frozenset(
    {
        GAME_TYPE_DYNASTY,
        "REDRAFT",
        "REST_OF_SEASON",
        "WEEKLY",
        "BEST_BALL",
        "KEEPER",
        "UNKNOWN",
    }
)


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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "keeptradecut.com dynasty rankings; the SF/TE++ board is served from the same "
            "dynasty per-player payload (superflexValues) — KTC's redraft product is a "
            "separate site section and is not fetched"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "idptradecalculator.com dynasty value pool; the calculator is dynasty-only (it "
            "prices future rookie picks, which a redraft calculator does not)"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "dynastyleaguefootball.com Dynasty Superflex expert-consensus board — DLF's "
            "product name and board header both state Dynasty"
        ),
        "correlation_group": "dlf",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "DLF Dynasty Rookie Superflex — a rookie board only exists as a dynasty product"
        ),
        "correlation_group": "dlf",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "DLF Dynasty IDP full-board expert consensus; board header states Dynasty"
        ),
        "correlation_group": "dlf",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "DLF Dynasty Rookie IDP — rookie-only defensive board, a dynasty-only product"
        ),
        "correlation_group": "dlf",
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
        # The IDP Show (Adamidp) — OWNER DECISION 2026-08-20: this
        # provider family's SOLE voting key.  Substack-hosted, served
        # from an embedded Datawrapper iframe, fetched by
        # ``scripts/fetch_idpshow.py --combined`` (which picks the
        # WIDEST chart in the article — see ``_pick_widest_chart`` —
        # because the combined post embeds a 250-row excerpt ahead of
        # the real ~665-700 row board; taking the first embed by
        # document order silently ingested the excerpt, PR #1008).
        # 665 rows / 662 distinct names at the 2026-08-20 acquisition,
        # Bijan Robinson #1 / Josh Allen #2 — i.e. the rank is ALREADY
        # a native COMBINED offense+IDP ordinal, not an IDP-only rank
        # that needs translating onto someone else's ladder.
        #
        # This is why ``is_cross_market=True`` + ``scope=overall_idp``
        # + ``extra_scopes=[overall_offense]`` (the same pattern
        # IDPTradeCalc and DraftSharks use below) is the right registry
        # shape and ``needs_shared_market_translation=False``: the
        # dormant Phase 1c ``csv_rank_cross_market_keys`` pre-pass in
        # ``_compute_unified_rankings`` — written for exactly "any
        # future rank-signal cross-market source" — restores this
        # board's own combined CSV rank instead of the generic
        # per-scope dense re-rank, and routes it to the GLOBAL Hill
        # master via ``rank_coordinates.native_pool_for_source``.  The
        # evidence stays ORDINAL throughout: nothing here manufactures
        # a cardinal 0-9999 vendor value out of a rank column, and this
        # source is deliberately NOT declared in
        # ``config/bridges/bridges_v1.json`` — it seeds no OTHER
        # specialist's shared-market ladder (dlfIdp / fantasyProsIdp
        # keep crosswalking through idpTradeCalc + draftSharks exactly
        # as before; this source simply stops needing that ladder for
        # its OWN vote).
        #
        # The OLDER idpShow.csv (IDP-only, ~350 rows,
        # needs_shared_market_translation=True, translated through
        # idpTradeCalc's ladder) is RETIRED from voting as of this
        # entry — see ``_SOURCE_CSV_PATHS`` for where it is now
        # unregistered.  Never register a second ``idpShow*`` key: see
        # ``tests/api/test_idpshow_combined_source.py::
        # TestExactlyOneVotingIdpShowKey`` for the structural guard.
        #
        # Includes rookie prospects (the board is a full combined
        # dynasty board, not an IDP-only excerpt), so
        # ``excludes_rookies=False``.
        "key": "idpShowCombined",
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "theidpshow.com/p/combined-idp-offense-dynasty-rankings-fantasy-football — "
            "the endpoint path itself is the dynasty board, and the publisher's "
            "redraft/weekly output lives at separate posts that are not fetched"
        ),
        "display_name": "The IDP Show — Combined (Adamidp)",
        "column_label": "IDP Show Combined",
        "correlation_group": "idpShow",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "extra_scopes": [SOURCE_SCOPE_OVERALL_OFFENSE],
        "position_group": None,
        # Measured floor, not the vendor's own "Top 700" marketing
        # figure — see the ``idpShowCombined`` row-floor comment above
        # for the full rationale (Task 7: never hardcode 700).
        "depth": 450,
        "weight": 1.0,
        "is_backbone": False,
        "is_cross_market": True,
        "needs_shared_market_translation": False,
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "dynastynerds.com/dynasty-rankings/sf-tep/ — dynasty rankings section; Nerds' "
            "redraft content is a different route"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "api.fantasycalc.com/values/current fetched with isDynasty=true; the same "
            "endpoint serves redraft when that flag is false, so the flag is the proof"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "otcffb.com/api/trade-values?format=sf — OTC publishes dynasty trade values; "
            "the format parameter selects superflex, not game type"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "fantasy-navigator-latest.onrender.com/ranks?platform=sf — Fantasy Navigator's "
            "dynasty board"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "Play for Keeps pfk_dynasty_rankings Supabase table — the table name is the product"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "dynasty-daddy.com/api/v1/player/all/today — Dynasty Daddy is a dynasty-only product"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "fantasypros.com/nfl/rankings/dynasty-superflex.php — FantasyPros exposes "
            "dynasty and redraft as distinct URLs; this is the dynasty one"
        ),
        "correlation_group": "fantasyPros",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "fantasypros.com/nfl/rankings/dynasty-idp.php — the dynasty IDP URL, distinct "
            "from FantasyPros' weekly IDP route"
        ),
        "correlation_group": "fantasyPros",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "FantasyPros Pat Fitzmaurice DYNASTY trade value chart — the chart is titled "
            "Dynasty and is published separately from his redraft chart"
        ),
        "correlation_group": "fantasyPros",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": ("flockfantasy.com dynasty superflex expert consensus"),
        "correlation_group": "flockFantasy",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "Flock Fantasy dynasty superflex ROOKIE board — a rookie board is a "
            "dynasty-only product"
        ),
        "correlation_group": "flockFantasy",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "Yahoo / Justin Boone DYNASTY trade value charts — published as dynasty, "
            "separate from his redraft rankings"
        ),
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "draftsharks.com/dynasty-rankings/te-premium-superflex — the dynasty-rankings "
            "route; DS's ROS boards are a different route and are deliberately NOT "
            "registered (see draftSharksRosSf.csv, unregistered)"
        ),
        "correlation_group": "draftSharks",
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
        # C1-SRC-02: DYNASTY is PROVEN per endpoint, never inferred from the
        # provider being one we otherwise trust.  UNKNOWN fails closed.
        "game_type": GAME_TYPE_DYNASTY,
        "game_type_evidence": (
            "same draftsharks.com dynasty-rankings page as draftSharks, IDP slice of the one DOM"
        ),
        "correlation_group": "draftSharks",
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
    "chris brazzell": "source_gap:idpTradeCalc+dlfSf — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
    "mike washington": "source_gap:idpTradeCalc+dlfSf — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
    "omar cooper": "source_gap:idpTradeCalc+dlfSf — deep KTC prospect not yet in IDPTC Sheet3 / DLF SF",
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
    "brenen thompson": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep — deep WR only ranked by FantasyPros dynasty SF",
    "eric mcalister": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep — deep WR only ranked by FantasyPros dynasty SF",
    "roman hemby": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep — deep RB only ranked by FantasyPros dynasty SF",
    # ── Offense: Flock-Fantasy-SF-only (not listed by other offense sources) ──
    # Deep-board veterans that Flock Fantasy's expert consensus ranks but
    # no other source currently carries.
    "adam thielen": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep+fantasyPros — veteran WR only ranked by Flock Fantasy SF",
    "zonovan knight": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep+fantasyPros — veteran RB only ranked by Flock Fantasy SF",
    "riley nowakowski": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep+flockFantasy — deep TE only ranked by FantasyPros SF",
    "rj maryland": "source_gap:ktc+idpTradeCalc+dlfSf+dynastyNerdsSfTep+flockFantasy — deep TE only ranked by FantasyPros SF",
    "ashton gillotte": "source_gap:dlfIdp+fantasyProsIdp — DL only ranked by IDPTradeCalc",
    "christian harris": "source_gap:dlfIdp+fantasyProsIdp — LB only ranked by IDPTradeCalc",
    "josh newton": "source_gap:dlfIdp+fantasyProsIdp — DB only ranked by IDPTradeCalc",
    "noah sewell": "source_gap:dlfIdp+fantasyProsIdp — LB only ranked by IDPTradeCalc",
    # ── IDP: DLF-Rookie-IDP-only (rookie prospects only in DLF rookie board) ──
    # Current-class IDP rookies that only DLF Rookie IDP has
    # evaluated.  IDPTradeCalc hasn't added them yet.  (This note used
    # to name FootballGuys too; those boards were retired and the
    # explanation outlived them — see F-8.)
    "aj haulcy": "rookie_source_gap:idpTradeCalc — 2026 DB rookie only ranked by DLF Rookie IDP",
    "shavon revel": "source_gap:idpTradeCalc+dlfIdp+fantasyProsIdp — 2026 DB rookie only ranked by DraftSharks",
    "kamari ramsey": "rookie_source_gap:idpTradeCalc+draftSharksIdp — 2026 DB rookie only ranked by DLF Rookie IDP",
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


def _source_freshness_flags() -> dict[str, bool | None]:
    """Per-source ``fresh?`` for the B11 confidence gate.

    Tri-state, reduced from the same ``staleness`` string the payload's
    ``dataFreshness.sourceTimestamps`` block publishes, so confidence and
    the freshness panel cannot disagree about whether a source is
    current:

      ``True``   inside its declared ``maxAgeHours`` budget
      ``False``  measured, and past it
      ``None``   could not be observed — a CSV we never found, or a
                 source with no path registered at all

    ``None`` is not ``False`` and neither is ``True``: an unmeasurable
    source must not read like one we measured and found current.  The
    gate counts only ``True`` toward the freshness share and reports the
    unknowns separately.

    Costs one ``os.stat`` per registered source, so callers resolve it
    ONCE per build and pass the map down — never per row.
    """
    flags: dict[str, bool | None] = {}
    for key, entry in _build_source_timestamps().items():
        staleness = str((entry or {}).get("staleness") or "")
        if staleness == "fresh":
            flags[key] = True
        elif staleness == "stale":
            flags[key] = False
        else:
            flags[key] = None
    return flags


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
            # C1-SRC-02: exported so a consumer can CHECK the claim
            # rather than trust the registry silently.
            "gameType": src.get("game_type"),
            "gameTypeEvidence": src.get("game_type_evidence"),
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


#: Registry position of each source key, which IS the declared
#: precedence inside a correlation group.  It already encodes the right
#: heads without a second list to keep in step: ``ktcSfTep`` is
#: registered before ``fantasyNavigatorSf`` (the board before the
#: republisher), ``fantasyProsSf`` before ``fantasyProsFitzmaurice``
#: (the consensus panel before the expert inside it), and every vendor's
#: main board before its rookie-specialty board.
def _source_precedence(key: str) -> int:
    for i, src in enumerate(_RANKING_SOURCES):
        if str(src.get("key") or "") == key:
            return i
    return len(_RANKING_SOURCES)


def collapse_to_independent_families(
    pairs: "list[tuple[str, float, bool]]",
) -> "tuple[list[tuple[str, float, bool]], dict[str, str]]":
    """One vote per provider family — a SELECTION, never an average.

    ``pairs`` is ``(source_key, value, is_anchor_source)`` for the
    sources that survived Hampel on one row.  Returns the surviving
    pairs plus ``{superseded_key: winning_key}`` for provenance.

    WHY SELECTION AND NOT AVERAGING
    --------------------------------
    A correlation group is a binary assertion: *these are not
    independent votes*.  Averaging a family's members quietly re-admits
    the derived one at 50% — which for ``fantasyProsFitzmaurice`` inside
    the ``fantasyProsSf`` consensus is exactly the nested-consensus
    prohibition, and for ``fantasyNavigatorSf`` inside ``ktc`` re-admits
    a republication of the anchor at half weight.  Averaging also
    manufactures a number no source published.

    Part of the intra-family spread is our own encoding artifact rather
    than two opinions: ``ktcSfTep`` votes value-direct
    (``raw / site_max x 9999``) while ``fantasyNavigatorSf`` votes
    rank -> percentile -> Hill, so averaging them averages an encoding
    difference into the board's anchor.

    If a family member genuinely carries independent signal, the repair
    is to UNDECLARE the group, not to half-count it.

    Precedence is registry order (``_source_precedence``), and only
    among members actually present on this row — so an IDP row where
    ``dlfSf`` is out of scope is decided by ``dlfIdp``, and a rookie row
    carrying both the main and rookie board is decided by the main one,
    matching the vendor's current opinion rather than a pre-draft
    artifact.
    """
    best: dict[str, tuple[int, tuple[str, float, bool]]] = {}
    for key, value, is_anchor in pairs:
        group = correlation_group_for(key)
        rank = _source_precedence(key)
        current = best.get(group)
        if current is None or rank < current[0]:
            best[group] = (rank, (key, value, is_anchor))

    winners = {group: entry for group, (_r, entry) in best.items()}
    winning_keys = {entry[0] for entry in winners.values()}
    superseded = {
        key: winners[correlation_group_for(key)][0]
        for key, _v, _a in pairs
        if key not in winning_keys
    }
    # Preserve the caller's ordering; only membership changes.
    kept = [pair for pair in pairs if pair[0] in winning_keys]
    return kept, superseded


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
#     ``needs_shared_market_translation`` — today ``dlfIdp`` and
#     ``fantasyProsIdp`` (``idpShowCombined`` is registered
#     ``is_cross_market`` instead — its own rank is already a combined
#     offense+IDP ordinal and needs no crosswalk; see its registry entry) —
#     rank players within the IDP class only.
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
    # Mirrors the bridge selection in ``_compute_unified_rankings``: does any
    # QUALIFIED cross-position bridge still have BOTH of its halves?
    #
    # This used to ask "does any surviving overall_idp source carry
    # is_backbone", and the class immediately below in
    # ``tests/consensus_edge/test_fair_value.py`` existed because that gate
    # could be satisfied by a one-line registry edit while the board stayed
    # broken.  It reads the bridge registry now, so a label cannot lift it —
    # and because a bridge is a FAMILY, losing one half of a two-key vendor
    # correctly costs that bridge.
    #
    # It remains a DECLARATION: it reports what the registry claims, and
    # ``shared_market_crosswalk_failed`` remains the measurement that should
    # decide.  A declared bridge can still fail to be capable on a given
    # board, which is why both exist.
    #
    # This used to carry a comment promising that "registering a second
    # IDP backbone lifts this guard automatically instead of leaving a
    # hardcoded refusal behind", which read as a feature and is in fact
    # the hazard.  ``is_backbone`` is a LABEL: setting it True on any of
    # the five other IDP sources empties ``assetClasses`` while the board
    # stays at median 1.224 / max 3.478.  Measured, not argued —
    # ``tests/consensus_edge/test_fair_value.py`` pins it.
    if not any(
        d.comparability == BRIDGE_QUALIFIED and all(k in surviving for k in d.keys)
        for d in load_bridge_descriptors()
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


#: Custom Mix (user source weighting) is disabled: it recomputed the
#: board through the canonical pipeline and returned it under
#: ``rankDerivedValue``, so two devices with different localStorage held
#: two canonical values for one player.  A module constant rather than an
#: env flag because this is a product decision with a written rationale,
#: not an operational toggle — and because a test can assert on it.
_SOURCE_OVERRIDES_DISABLED: bool = True


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

    # CUSTOM MIX DISABLED 2026-08-14 — one canonical board.
    #
    # Closed HERE, at the one function every override body passes
    # through, rather than at the route: the client no longer sends
    # overrides, but a stale bundle or a direct caller still can, and a
    # user-weighted board returned under ``rankDerivedValue`` (which is
    # in ``_DELTA_PLAYER_FIELDS``) is a second canonical truth however it
    # was requested.
    #
    # The request is answered, not refused — the endpoint still serves
    # the canonical board with the league-derived TE premium applied, and
    # says in ``warnings`` why the weights were ignored. Refusing would
    # break /rankings for anyone whose device still posts a stored mix.
    if _SOURCE_OVERRIDES_DISABLED:
        warnings.append(
            "custom source weighting is disabled; serving the canonical "
            "consensus board (see docs/valuation/"
            "LEAGUE_AWARE_METHODOLOGY_REJECTION.md)"
        )
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

    THE SIDES ARE FAMILIES, NOT KEYS (B10-T3a).  The split used to be
    taken over the ``is_retail`` keys alone — today just ``ktcSfTep`` —
    which put ``fantasyNavigatorSf`` on the CONSENSUS side.  It is not
    another opinion: the registry declares it ``correlation_group:
    "ktc"`` and its own comment says it republishes KTC-derived numbers.
    So on 437 live rows the retail market was being compared against a
    consensus that contains retail, and the disagreement it reported was
    partly retail disagreeing with itself.

    Reclassified rather than dropped: it is retail-DERIVED evidence, so
    it informs the retail estimate.  Discarding it would throw away a
    real observation to fix a bookkeeping error.  Measured effect of the
    move: 364 rows change magnitude (median 0.055, p90 0.148, max 0.545)
    and **72 flip direction** — the published signal was pointing the
    wrong way on those.

    `retail_keys` is an optional override for tests; when None the set is
    derived from `_RANKING_SOURCES` via `_retail_source_keys()` and then
    expanded across correlation groups.  A caller passing an explicit set
    is taken at its word and NOT expanded — the tests that pass one are
    constructing a specific split on purpose.
    """
    if retail_keys is None:
        retail_keys = frozenset(expand_correlation_groups(_retail_source_keys()))

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
        # C1-U5: these grade how confidently a SOURCE ROW resolved to this
        # player — join quality, not evidence quality. Published beside
        # ``confidenceBucket`` under a name a reader cannot tell apart from
        # it, which is the confusion this rename removes. Legacy keys keep
        # their exact values for the deprecation window declared in
        # ``meta.deprecations``.
        row["identityResolutionConfidence"] = ic_score
        row["identityResolutionMethod"] = ic_method
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
                bucket, label, basis = degrade_for_quarantine(current_bucket)
                row["confidenceBucket"] = bucket
                row["confidenceLabel"] = label
                row["confidenceBasis"] = basis
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
    "identityResolutionConfidence",
    "identityResolutionMethod",
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

# C1-ID-01 CUTOVER: summary of the most recent contract-build CSV-join,
# now decided solely by src/identity/resolution.match_row_to_source_entry.
# Written by _enrich_from_source_csvs, stamped into the contract payload as
# ``identityJoin`` by build_api_data_contract.  Before the cutover this held
# a legacy-vs-engine comparison; the gate it existed for passed at 24,024 of
# 24,024 decisions and the inline cascade was then deleted.
_LAST_CONTRACT_JOIN_SUMMARY: dict | None = None

# Written by _compute_unified_rankings, stamped into the contract payload as
# ``crossPositionBridges`` by build_api_data_contract.  Lane 8: names every
# declared bridge's state (including PENDING / UNAVAILABLE / STALE — a failed
# or withheld bridge stays represented here rather than disappearing), which
# bridges actually contributed to the shared-market ladder, and the withheld
# vote count per source.  ``None`` before any board is built.
_LAST_CROSS_POSITION_BRIDGE_SUMMARY: dict | None = None

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
                    sid = _pick_provider_id(csvrow, _SLEEPER_ID_TOKENS).strip()
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
                    sid = _pick_provider_id(csvrow, _SLEEPER_ID_TOKENS).strip()
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

    # C1-ID-01 CUTOVER: the canonical owner decides every (row, source)
    # join.  The inline cascade that used to live in the row loop is
    # DELETED — no flag, no fallback — after its transcription was proven
    # identical on 24,024 of 24,024 live decisions.
    from src.identity import resolution as _identity_resolution  # noqa: PLC0415

    _join_decisions = 0
    _join_matched = 0
    # Cross-position-group name collisions withheld from voting (never a
    # false attribution) — keyed by source, valued by the colliding
    # canonical-match keys.  See the ``else`` branch below.
    _withheld_ambiguous_names: dict[str, list[str]] = {}

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
                # Multiple DISTINCT canonical players share this
                # normalized name across different position groups —
                # e.g. Justin Jefferson the Minnesota WR and Justin
                # Jefferson the Cleveland LB (issue #1011).  This is a
                # different situation from the ``len(row_groups) <= 1``
                # branch above (one real person, possibly listed twice
                # by the CSV — e.g. Travis Hunter's two-way listing,
                # which stays fully voting there): here two REAL,
                # DIFFERENT people are colliding on one name, and
                # attaching either CSV entry to the wrong one is not a
                # missing vote, it is a WRONG one.
                #
                # WITHHOLD rather than replicate.  This function has no
                # per-CSV-row position captured in ``csv_lookup`` (the
                # tuple is name/value/rank/native/sleeperId only) to
                # split the entries by group, and even a source's OWN
                # claimed position column cannot be trusted to do it
                # safely here: measured 2026-08-20, the IDP Show
                # combined board itself mislabels the Minnesota WR's
                # row "LB" (its true position), which is exactly the
                # signal a position-based split would have to trust.
                # Vendor TEAM — the other candidate disambiguator — is
                # not published by this CSV at all.
                #
                # So: no ``per_source`` entry is written for any of the
                # colliding groups.  ``match_row_to_source_entry`` then
                # finds no ``{cname}::{grp}`` key for ANY of the
                # colliding canonical rows and returns no match — the
                # source contributes NOTHING for this name (not a zero;
                # the row's ``canonicalSiteValues`` simply carries no
                # key for this source, the same "missing" state a row
                # this source never covered would have).  Only the
                # colliding names are affected; every other row from
                # this CSV still joins and votes normally.
                _withheld_ambiguous_names.setdefault(source_key, []).append(cname)
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
            decision = _identity_resolution.match_row_to_source_entry(
                row_player_id=row.get("playerId"),
                row_name=str(row.get("canonicalName") or row.get("displayName") or ""),
                row_position=row.get("position"),
                per_source=per_source,
                sid_index=sid_index,
                row_groups_by_key=row_groups_by_key,
                canonical_match_key=_canonical_match_key,
                position_group=canonical_position_group,
            )
            _join_decisions += 1
            entry = None
            if decision.via == "sleeper_id":
                # Rows stamp the Sleeper id as ``playerId`` (mapped
                # from the legacy ``_sleeperId``).
                row_sid = str(row.get("playerId") or "").strip()
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
            elif decision.entry_key:
                entry = per_source.get(decision.entry_key)
            if not entry:
                continue
            _join_matched += 1
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

    global _LAST_CONTRACT_JOIN_SUMMARY
    _LAST_CONTRACT_JOIN_SUMMARY = {
        "site": "contract_csv_join",
        "policy": _identity_resolution.CONTRACT_CSV_JOIN_V1,
        "decidedBy": "src.identity.resolution.match_row_to_source_entry",
        "legacyCascadeRetired": True,
        "decisions": _join_decisions,
        "matched": _join_matched,
        # Names withheld because they collide across DIFFERENT canonical
        # players' position groups (issue #1011) — never attached to the
        # wrong person, never a false zero.  Per-source so a golden-board
        # diff can name exactly which players a source's vote is missing
        # for and why.
        "withheldForCrossGroupNameCollision": {
            source_key: sorted(set(names))
            for source_key, names in _withheld_ambiguous_names.items()
        },
        "withheldForCrossGroupNameCollisionCount": sum(
            len(set(names)) for names in _withheld_ambiguous_names.values()
        ),
    }

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

# Board pick-name grammar — OWNED by the canonical pick-identity module
# (C1-ID-02, ``src/identity/picks.py``); imported back here so the
# pipeline's acceptance bounds cannot drift from the owner's.  The
# local names survive for the pipeline's many call sites.
from src.identity.picks import (  # noqa: E402
    BOARD_TIER_RE as _PICK_TIER_RE,
    is_pick_name as _owner_is_pick_name,
    parse_board_slot_name as _owner_parse_board_slot_name,
    parse_board_tier_name as _owner_parse_board_tier_name,
    pick_year_from_name as _owner_pick_year_from_name,
    round_suffix as _round_suffix,
)

# Pick year discount is loaded once per build from
# config/weights/pick_year_discount.json.  See the file header for the
# config schema.  Cached at module level so a build that processes
# multiple snapshots only reads the file once.
_PICK_YEAR_DISCOUNT_CACHE: dict[str, Any] | None = None


_TIER_ORDER: tuple[str, ...] = ("early", "mid", "late")


def _pava_non_increasing(values: list[float]) -> list[float]:
    """Pool-adjacent-violators projection onto the non-increasing cone.

    The least-squares closest non-increasing sequence, equal weights.
    Standard isotonic regression; pooling replaces a violating run with
    its mean.
    """
    blocks: list[list[float]] = []  # [sum, count]
    for value in values:
        blocks.append([float(value), 1.0])
        while len(blocks) > 1 and (blocks[-2][0] / blocks[-2][1]) < (blocks[-1][0] / blocks[-1][1]):
            total, count = blocks.pop()
            blocks[-1][0] += total
            blocks[-1][1] += count
    out: list[float] = []
    for total, count in blocks:
        out.extend([total / count] * int(count))
    return out


def _project_tier_steps_monotone(cells: dict[str, float]) -> dict[str, float]:
    """Constrain the year-step surface so it cannot invert tier ordering.

    **F-1.** Each ``<tier>.<round>`` cell is an independently measured
    same-day vendor ratio, and the ratios RISE with tier — a late pick
    decays less year-over-year than an early one.  That compresses the
    Early-Late spread, and nothing stopped the compression before it
    CROSSED.  On 2029 it crossed in six of six rounds: ``2029 Mid 1st``
    priced 3676 against ``2029 Early 1st`` at 3593, so the trade
    calculator booked a gain for downgrading, and ``/rankings`` published
    the mid first ABOVE the early first.

    Within a round the step is projected onto the non-increasing cone by
    isotonic regression.  Two properties make this the constraint rather
    than a patch:

    * it acts on the DERIVATION SURFACE, not on output values — no clamp
      sits downstream of the blend;
    * a constant ratio applied to a strictly ordered template year yields
      a strictly ordered derived year, so pooling can never produce a
      TIE in value space.  Ordering is preserved **by construction**, for
      every source and every template, with no epsilon.

    Cells that already comply are returned unchanged, so the projection
    is the identity wherever the measured surface is already consistent.

    Classification stays **PRIOR** with the rest of
    ``derivedYearModel``: the 2-out->3-out extrapolation was already
    untestable on current evidence, and constraining it does not make it
    measured.  The unprojected surface is preserved under
    ``yearStepByTierRoundMeasured`` so the evidence is not overwritten by
    the model built from it.
    """
    if not cells:
        return {}
    rounds: set[int] = set()
    for key in cells:
        tier, _, rnd = str(key).partition(".")
        if tier in _TIER_ORDER and rnd.isdigit():
            rounds.add(int(rnd))

    projected = dict(cells)
    for rnd in sorted(rounds):
        keys = [f"{tier}.{rnd}" for tier in _TIER_ORDER]
        if not all(k in cells for k in keys):
            continue  # a partial round is left exactly as measured
        fitted = _pava_non_increasing([float(cells[k]) for k in keys])
        for key, value in zip(keys, fitted):
            projected[key] = round(value, 6)
    return projected


def _load_pick_year_discount() -> dict[str, Any]:
    """Load and cache the canonical future-pick derivation config.

    Returns a dict shaped like::

        {
            "currentDraftYear": 2027 | None,   # explicit override
            "rolloverMonth": 5,
            "rolloverDay": 15,
            "horizonYears": 3,                 # MECHANICAL: current+3 (TC-19)
            "yearStepByTierRound": {"early.1": 0.7138, ...},
            "yearStepByRound": {"1": 0.8078, ...},
            "yearStepFallback": 0.8407,
            "roundStepByRound": {"5": 0.929, "6": 0.916},
        }

    C1-U6 replaced the retired ``offsetDiscounts`` decay curve
    (1.00/0.82/0.66/0.53, audit V-12/C-11: an uncalibrated prior applied
    to a cloned price) with the measured vendor year-step families —
    see the config file's own notes and
    ``docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md``.  Every parameter is
    classification PRIOR (measured-anchored) per
    ``docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`` §3.1.

    If the config file is missing or malformed, falls back to built-in
    defaults (the shipped priors) so the pipeline stays robust on
    stripped-down test environments.
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
        "horizonYears": 3,
        "yearStepByTierRound": {},
        "yearStepByRound": {},
        "yearStepFallback": 0.84,
        "roundStepByRound": {"5": 0.93, "6": 0.92},
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
            if loaded.get("horizonYears") is not None:
                cfg["horizonYears"] = max(0, int(loaded["horizonYears"]))
            year_model = loaded.get("derivedYearModel") or {}
            if isinstance(year_model, dict):
                cells = year_model.get("stepByTierRound") or {}
                if isinstance(cells, dict):
                    cfg["yearStepByTierRound"] = {
                        str(k).lower(): float(v) for k, v in cells.items()
                    }
                rounds = year_model.get("stepByRound") or {}
                if isinstance(rounds, dict):
                    cfg["yearStepByRound"] = {str(int(k)): float(v) for k, v in rounds.items()}
                if year_model.get("stepFallback") is not None:
                    cfg["yearStepFallback"] = float(year_model["stepFallback"])
            round_model = loaded.get("derivedRoundModel") or {}
            if isinstance(round_model, dict):
                rounds = round_model.get("stepByRound") or {}
                if isinstance(rounds, dict):
                    cfg["roundStepByRound"] = {str(int(k)): float(v) for k, v in rounds.items()}
    except (OSError, ValueError, TypeError):
        # Stick with the built-in defaults — never block the build on
        # a missing/malformed pick-derivation config.
        pass

    # F-1: the measured surface is EVIDENCE and is kept; what the
    # derivation consumes is that surface projected onto the cone where
    # it cannot invert tier ordering.  Keeping both means a future
    # recalibration compares against what was measured, not against what
    # was constrained.
    measured = dict(cfg["yearStepByTierRound"])
    cfg["yearStepByTierRoundMeasured"] = measured
    cfg["yearStepByTierRound"] = _project_tier_steps_monotone(measured)

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

# Per-build derivation record for the pick rows synthesized by
# ``_inject_far_future_pick_sources`` (canonical match key →
# {"factor", "basisYear", "basisName", "family", "classification"}).
#
# Its KEYS are also the synthetic-name set: these rows are legitimately
# single-source (no vendor prices picks that far out), so the
# single-source safety gate allowlists them.  Until 2026-08-16 the same
# information was kept twice — a ``set`` and a ``dict`` populated side by
# side — and both were MODULE GLOBALS reset at the top of each injection.
#
# That was a real concurrency defect on a live endpoint, not a style
# preference (C1-U6 follow-up 8).  ``POST /api/rankings/overrides``
# rebuilds the board per request; two overlapping builds in one process
# shared the globals, so build B could reset them mid-way through build
# A's provenance stamping and A would publish a derived pick row with no
# derivation record — or, worse, with B's.  It also made the tests set
# and restore process state to exercise a pure function.
#
# The map is now created by the injection, returned to the caller, and
# threaded explicitly to the three passes that read it.  There is no
# process-global derivation state left, so builds cannot see each
# other's, in any interleaving.
_EMPTY_PICK_DERIVATIONS: dict[str, dict[str, Any]] = {}
_FAR_FUTURE_ALLOWLIST_REASON = (
    "synthetic_far_future_tier:no vendor prices picks this far out; "
    "derived from the nearest published year via the measured vendor "
    "year-step (config derivedYearModel, classification PRIOR; "
    "auto-pivots when sources publish this year)"
)


def derive_current_draft_year_from_names(names: Any) -> int | None:
    """Lowest year carrying a SLOT-specific pick label, or ``None``.

    The lowest such year is the active draft — older classes have been
    drafted out of the source boards, further-out classes only have
    generic Early/Mid/Late tiers.

    THE grammar-independent form of the rule (2026-08-16).  It used to
    match one hard-coded regex for ``YYYY Pick R.SS`` — the contract's own
    row names — which meant the SCRAPER, whose vendor anchors are keyed
    ``"2026 1.01"``, could not ask this question and hard-coded ``2026``
    and ``(2027, 2028)`` instead (C1-U6 follow-up 1).  That is a circular
    pin: the contract's "self-rolling" current year is DERIVED from the
    scrape, so a stale literal upstream freezes the whole board at the
    next class rollover while every downstream year claims to self-roll.
    Parsing runs through the C1-U3 pick-identity owner, which already
    knows every label grammar in the repository, so there is exactly one
    rule and exactly one grammar authority.

    Verified equivalent on the live payload: identical answer (2026) to
    the retired regex on contract row names, and it additionally answers
    on the scraper's anchor grammar, where the regex returned ``None``.
    """
    from src.identity.picks import parse_pick_label

    best: int | None = None
    try:
        iterator = iter(names)
    except TypeError:
        return None
    for nm in iterator:
        parsed = parse_pick_label(str(nm))
        if parsed is None or parsed.slot is None or parsed.year is None:
            continue
        year = int(parsed.year)
        if best is None or year < best:
            best = year
    return best


def derive_future_tier_years_from_names(names: Any, current_year: int) -> list[int]:
    """Years strictly after ``current_year`` that carry generic TIER labels.

    The other half of the same question, and the other scraper literal:
    which future classes do the vendors actually publish tiers for.  Data
    says ``[2027, 2028]`` today — the two years the scraper hard-codes —
    and it rolls on its own when a vendor adds a year.
    """
    from src.identity.picks import parse_pick_label

    years: set[int] = set()
    try:
        iterator = iter(names)
    except TypeError:
        return []
    for nm in iterator:
        parsed = parse_pick_label(str(nm))
        if parsed is None or parsed.year is None or parsed.slot is not None:
            continue
        year = int(parsed.year)
        if year > int(current_year):
            years.add(year)
    return sorted(years)


def _derive_current_draft_year_from_names(names: Any) -> int | None:
    """Deprecated private alias — call the public name."""
    return derive_current_draft_year_from_names(names)


def set_observed_current_draft_year(year: int | None) -> None:
    """Record the data-derived active draft year for this build.

    Called once at the top of :func:`build_api_data_contract` from the
    raw scrape's slot-pick names so every downstream consumer
    (discount, rookie anchor, synthetic tether) agrees on one year.
    """
    global _OBSERVED_CURRENT_DRAFT_YEAR
    _OBSERVED_CURRENT_DRAFT_YEAR = int(year) if year else None


def _year_step_for(tier: str | None, round_num: int | None, cfg: dict[str, Any]) -> float:
    """The measured one-year vendor step for a (tier, round) cell.

    Lookup order: ``yearStepByTierRound["<tier>.<round>"]`` →
    ``yearStepByRound["<round>"]`` → ``yearStepFallback``.  Every value
    is classification PRIOR (measured-anchored) — see the config file
    and ``docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md``.  Clamped to
    (0.05, 1.0]: a step above 1.0 or near 0 is a pathological parameter,
    not a valid derivation.
    """
    step = None
    if tier is not None and round_num is not None:
        step = (cfg.get("yearStepByTierRound") or {}).get(f"{str(tier).lower()}.{int(round_num)}")
    if step is None and round_num is not None:
        step = (cfg.get("yearStepByRound") or {}).get(str(int(round_num)))
    if step is None:
        step = cfg.get("yearStepFallback")
    try:
        step_f = float(step)
    except (TypeError, ValueError):
        step_f = 0.84
    return max(0.05, min(1.0, step_f))


def _inject_far_future_pick_sources(
    players_by_name: dict[str, Any],
    current_year: int,
) -> int:
    """Seed raw source entries for far-future pick years the vendors
    don't publish yet, out to the product horizon
    (``current_year + horizonYears``, e.g. 2029 when the active draft is
    2026 — TC-19 / manifest C1-PICK-01; the horizon self-rolls).

    KTC/IDPTC only price two future years.  The user trades picks
    further out than that, so for any missing year we derive the nearest
    *published* future year's generic-tier raw entries (Early/Mid/Late ×
    rounds) under the new year's names, **stepping every per-source
    value down by the measured vendor year-step for its (tier, round)
    cell at derivation time** (compounding ``step ** gap`` across a
    multi-year gap).  The derived entries then ride the **entire**
    normal pipeline exactly like the real future-tier picks — blended,
    ranked, legacy-mirrored, and surfaced in the app view — and because
    the step is applied to the source values themselves, the published
    value, the per-source display values, and the pick-confidence
    inputs all carry ONE consistent derivation (closing the RED-4
    anchor asymmetry, where a clone presented the template year's
    vendor numbers verbatim against a separately-discounted model
    value).

    This replaced the retired verbatim-clone + Phase 3a ``× 0.53``
    composition (audit V-12/C-11): the offset-from-current multiplier
    family was never calibrated, and the challenger evaluation measured
    it ~37% below every observed vendor year-step cell
    (``scripts/calibrate_pick_year_step.py``).

    Real source rows always win: a year that already has any generic
    tier entry is left untouched, so the moment vendors publish e.g.
    2029 this no-ops for that year ("pivot when sources add them").

    POPULATION NOTE (V1-132 / audit F-34): this function sees the RAW
    payload only, where just the in-JSON pick markets carry values —
    ``ktcSfTep``'s pick values arrive through the later CSV enrichment.
    :func:`_complete_synthetic_pick_sources_from_enrichment` runs after
    that enrichment and extends this same derivation to the enriched
    per-source evidence, so the horizon year blends both pick markets.

    Returns the per-build derivation map (canonical match key → record).
    Its length is the number of synthetic raw entries added, and its keys
    are the synthetic-name set the single-source gate allowlists.  It is
    deliberately RETURNED rather than stored on the module: see
    ``_EMPTY_PICK_DERIVATIONS`` for the concurrency defect that caused.
    """
    derivations: dict[str, dict[str, Any]] = {}
    cfg = _load_pick_year_discount()
    try:
        horizon = max(0, int(cfg.get("horizonYears") or 3))
    except (TypeError, ValueError):
        horizon = 3
    target_year = current_year + horizon
    if target_year <= current_year:
        return derivations

    years_with_tiers: set[int] = set()
    for key in list(players_by_name.keys()):
        m = _PICK_TIER_RE.match(str(key).strip())
        if m:
            years_with_tiers.add(int(m.group(1)))
    if not years_with_tiers:
        return derivations

    added = 0
    for year in range(current_year + 1, target_year + 1):
        # Deferral to real source rows is PER CELL, not per year.
        #
        # AUDIT F-30 (second half).  This used to skip the whole year on
        # ``if year in years_with_tiers`` — but the per-cell guard below
        # (``new_name in players_by_name``) already defers to every real row,
        # so the year-level skip added nothing except a failure mode: a vendor
        # publishing PART of a horizon year made the injection defer for the
        # cells it did NOT publish as well, and nothing else creates those rows.
        # The completion rung cannot repair it either — completion reprices
        # rows that exist, and these never came into existence.
        #
        # Measured on the real payload with only the horizon year's round-1
        # tiers published: 15 tier rows absent, 5 generic rows unbuilt, 20
        # census errors — with the earlier future year fully priced the whole
        # time.  Same shape as the incident that skipped a production deploy.
        #
        # Removing the year-level skip is INERT whenever a year is wholly
        # absent (every cell is synthesized, as before) or wholly published
        # (every cell defers, as before).  It changes behaviour only in the
        # partial case, which is the case that was broken.
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
            tier, rnd = m.group(2), int(m.group(3))
            gap = year - template_year
            factor = _year_step_for(tier, rnd, cfg) ** gap
            derived: dict[str, Any] = {}
            for k, v in entry.items():
                if str(k).startswith("_"):
                    # The pipeline recomputes every cached/derived field.
                    continue
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                    derived[k] = round(float(v) * factor, 1)
                else:
                    derived[k] = v
            players_by_name[new_name] = derived
            # Store the canonical match key (what the single-source
            # gate keys ``allowlistReason`` lookups on), not the raw
            # display name.
            match_key = _canonical_match_key(new_name)
            derivations[match_key] = {
                "factor": round(factor, 4),
                "basisYear": template_year,
                "basisName": key,
                "family": "measured_vendor_year_step_v1",
                "classification": "PRIOR",
            }
            added += 1
        years_with_tiers.add(year)
    return derivations


def _complete_synthetic_pick_sources_from_enrichment(
    players_array: list[dict[str, Any]],
    synthetic_pick_derivations: Mapping[str, dict[str, Any]],
) -> int:
    """Extend the far-future derivation to CSV-enriched source evidence.

    AUDIT F-34 (V1-132).  :func:`_inject_far_future_pick_sources` clones
    the template year's entry out of ``players_by_name`` — the RAW
    scraper payload — and that population is strictly poorer than the
    one the canonical board blends for the same template year:
    ``ktcSfTep``'s pick values arrive through the LATER
    ``_enrich_from_source_csvs`` pass, which the injection structurally
    cannot see.  So the published years (both pick markets on every tier
    row) blended two markets while the horizon year blended
    ``idpTradeCalc`` alone on all twelve tier cells — a single-vendor
    dependency on exactly the rows with the least direct evidence.

    The injection cannot simply move after the enrichment: it must run
    against ``players_by_name`` BEFORE ``players_array`` is derived so
    the synthetic rows exist as rows (and as legacy dict entries) at
    all, and the enrichment loop itself needs those rows to exist to
    stamp anything.  The pipeline's own structure — rows built once,
    then enriched in place — therefore supports the converse ordering:
    hand the injection's derivation the enriched evidence, in place, per
    synthetic row.

    Same derivation, wider population — nothing about the model changes:

      * a source key present (positive) on the TEMPLATE row but absent
        on the synthetic row is filled with ``template × step ** gap``,
        the identical ``derivedYearModel`` cell step and compounding the
        injection applies to the raw per-source values (through the one
        shared :func:`_year_step_for`);
      * a value the injection already stepped at the raw layer is left
        alone — never re-stepped, never overwritten;
      * a source the template row does not carry stays MISSING
        (C1-U6-D1: a year a source did not publish is the key's
        absence), so a source publishing no picks contributes nothing;
      * provenance is untouched — the rows keep their
        ``derived_year_step`` record; nothing here can promote a
        derivation to ``direct_market_blend``.

    Chained templates are processed in ascending target-year order so a
    horizon two years past the last published year (whose template is
    itself synthetic) reads its template's completed values.

    In practice the enrichment-only pick sources are the value-signal
    pick markets — today exactly ``ktcSfTep`` — but the rule is the
    injection's own (every positive per-source value on the template),
    not a source list to keep in step.

    Returns the number of per-source values stamped.  Runs immediately
    after ``_enrich_from_source_csvs`` in :func:`build_api_data_contract`
    and mutates only the synthetic rows' ``canonicalSiteValues``;
    ``_compute_unified_rankings`` recomputes ``sourceCount`` /
    ``sourcePresence`` from those, and the backbone's synthetic-row
    exclusion (C1-U6 follow-up 2) already keeps every value written here
    out of the cross-market ladder.
    """
    if not synthetic_pick_derivations:
        return 0
    cfg = _load_pick_year_discount()
    rows_by_key: dict[str, dict[str, Any]] = {}
    for row in players_array:
        if not isinstance(row, dict) or row.get("assetClass") != "pick":
            continue
        key = _canonical_match_key(str(row.get("canonicalName") or ""))
        if key:
            rows_by_key[key] = row

    def _target_year(item: tuple[str, dict[str, Any]]) -> int:
        row = rows_by_key.get(item[0])
        if isinstance(row, dict):
            m = _PICK_TIER_RE.match(str(row.get("canonicalName") or "").strip())
            if m:
                return int(m.group(1))
        return 0

    stamped = 0
    for match_key, record in sorted(synthetic_pick_derivations.items(), key=_target_year):
        row = rows_by_key.get(match_key)
        if not isinstance(row, dict):
            continue
        template = rows_by_key.get(_canonical_match_key(str(record.get("basisName") or "")))
        if not isinstance(template, dict):
            continue
        m = _PICK_TIER_RE.match(str(row.get("canonicalName") or "").strip())
        if not m:
            continue
        year, tier, rnd = int(m.group(1)), m.group(2), int(m.group(3))
        try:
            basis_year = int(record["basisYear"])
        except (KeyError, TypeError, ValueError):
            # No recorded basis year -> REFUSE to derive.  ``or 0`` here
            # would fabricate gap = year - 0 and drive step**gap to ~0,
            # stamping a 0.0 that reads as a real value — missing is
            # never zero, and never a fabricated basis either.
            continue
        gap = year - basis_year
        if gap <= 0:
            continue
        factor = _year_step_for(tier, rnd, cfg) ** gap
        template_sites = template.get("canonicalSiteValues")
        row_sites = row.get("canonicalSiteValues")
        if not isinstance(template_sites, dict) or not isinstance(row_sites, dict):
            continue
        for source_key, template_value in template_sites.items():
            t_num = _safe_num(template_value)
            if t_num is None or t_num <= 0:
                continue  # the template does not carry it → MISSING stays missing
            existing = _safe_num(row_sites.get(source_key))
            if existing is not None and existing > 0:
                continue  # already derived at injection — never re-stepped
            row_sites[source_key] = round(float(t_num) * factor, 1)
            stamped += 1
    return stamped


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

    **This function answers a PRESENT-TENSE question.**  Steps 1 and 2
    describe which draft is current *now* and are deliberately
    clock-independent, so passing a historical ``today`` does NOT make
    this an as-of resolver — the override or the observed year still
    wins.  For "which draft was current on some past date", call
    :func:`rookie_draft_year_on`, which is step 3 on its own.
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
    return rookie_draft_year_on(today)


def rookie_draft_year_on(day: date) -> int:
    """Which rookie draft was current on ``day`` — the AS-OF form.

    Step 3 of :func:`current_rookie_draft_year`, factored out so a
    historical caller has one to call.  The configured
    ``(rolloverMonth, rolloverDay)`` boundary is applied to the given
    date and nothing else is consulted: the ``currentDraftYear`` override
    and the observed-year self-roll both describe the PRESENT, and
    applying either to a past instant would re-grade an old event under
    today's clock.

    Extracted for ``src/acquisition``'s at-the-time cost basis
    (``C3-REPLAY-01`` class).  It lives here rather than there because a
    second copy of the rollover rule is a second answer — the first cut
    of that consumer reimplemented it and silently dropped the config
    override.
    """
    cfg = _load_pick_year_discount()
    roll_m = int(cfg.get("rolloverMonth") or 5)
    roll_d = int(cfg.get("rolloverDay") or 15)
    if (day.month, day.day) >= (roll_m, roll_d):
        return day.year + 1
    return day.year


def _pick_year_from_name(name: str) -> int | None:
    """Extract the 4-digit year from a pick canonical name, or None.

    Handles all three pick name formats: ``2026 Pick 1.06``,
    ``2026 Early 1st``, ``2026 Round 1``, etc.  Delegates to the
    canonical pick-identity owner (C1-ID-02).
    """
    return _owner_pick_year_from_name(name)


# RETIRED (C1-U6): ``_pick_year_discount_for`` — the offset-from-current
# multiplier family (offsetDiscounts 1.00/0.82/0.66/0.53 + fallbackBase
# 0.80).  Audit V-12/C-11 measured its one live entry (offset 3 → 0.53,
# applied to a verbatim 2028 clone) ~37% below every observed vendor
# year-step cell.  Synthetic-year derivation now happens at injection
# via :func:`_year_step_for` (measured per-cell steps, classification
# PRIOR); vendor-priced years were already exempt (T-3/C-2) and stay
# exempt.  Deleted rather than left unreferenced so no seam remains to
# re-thread by accident.


def _parse_pick_slot(name: str) -> tuple[int, int, int] | None:
    """Return (year, round, slot) for a slot-specific pick name.

    Returns None for tier-only rows like "2026 Early 1st".  Delegates
    to the canonical pick-identity owner (C1-ID-02).
    """
    return _owner_parse_board_slot_name(name)


def _parse_pick_tier(name: str) -> tuple[int, str, int] | None:
    """Return (year, tier, round) for a generic tier pick name.

    Returns None for slot-specific rows like "2026 Pick 1.06".
    Delegates to the canonical pick-identity owner (C1-ID-02).
    """
    return _owner_parse_board_tier_name(name)


# ── Blend-integrity detection ───────────────────────────────────────────
# This section used to be headed "Market-anchor corridor clamp" and to
# document designated per-asset-class market anchors.  Both the heading
# and the anchor design are gone with the corridor (#794/#795/#796):
# nothing here reads an anchor, and the check below does not "keep a
# player within a corridor" of anything.  It asks one structural
# question — did a blended value land outside the range of its own
# contributions — and answers it without changing any value.
#: Numerical-precision allowance for the blend-integrity check, NOT a
#: policy band.
#:
#: The check asks whether a blended value fell outside the range of its own
#: contributions, which is impossible under correct operation. The only
#: slack it needs is for float representation and the integer rounding the
#: contributions are stamped with. It is emphatically not a "how much
#: disagreement do we tolerate" dial: measured across 5,931 IDP rows on 17
#: independent historical days, the violation count is **0 at every
#: tolerance from 0% to 10%**, so no policy slack is doing any work and
#: none is offered.
#:
#: The retired market corridor had exactly that kind of dial, re-derived
#: from the board it policed. Reintroducing one here would recreate
#: W02-F016.
_BLEND_HULL_EPSILON: float = 1e-9

# The two quantities the hull check compares are INTEGERS quantized from
# floats by two different rules, and the allowance below is the exact
# worst-case skew of that quantization — numerical precision, not policy:
#
# * ``rankDerivedValue`` is ``int(norm_val)`` — truncation, so the
#   published integer sits as much as (just under) 1.0 BELOW the float
#   blend and never above it;
# * each ``sourceRankMeta[*].valueContribution`` stamp is
#   ``int(round(value))`` — within 0.5 of its float contribution in
#   either direction.
#
# A float blend sitting exactly on the hull floor can therefore publish
# up to 1.5 below the stamped minimum (1.0 truncation + 0.5 stamp
# rounding), and up to 0.5 above the stamped maximum (stamp rounding
# only — truncation never raises a value). Anything outside THOSE bounds
# is a genuine impossibility. Measured incident, 2026-08-25 ("2027 Mid
# 2nd"): votes 3459.692 (ktc 3459 x 9999/9997) and 3460.0 (idpTradeCalc
# 3460/9999 x 9999), float blend ~3459.85 inside the true hull, published
# ``int()`` -> 3459, stamps ``int(round())`` -> [3460, 3460] — flagged as
# "below" a hull the blend never left. The 2026-08-22 "2027 Late 1st"
# transient (#1063) is the same class: it fires whenever the two pick
# markets nearly agree at a rounding boundary, and "self-corrects" when
# the next scrape moves either value a hair.
_BLEND_HULL_QUANTIZATION_BELOW: float = 1.5
_BLEND_HULL_QUANTIZATION_ABOVE: float = 0.5


def _detect_blend_integrity_violations(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Detect blended values that are STRUCTURALLY IMPOSSIBLE, and abstain.

    Replaces the market-corridor clamp (W02-F015/F016/F017, #794/#795/#796).
    Detects, stamps, and deliberately **does not alter any value**.

    The invariant
    ─────────────

    A weighted blend of source contributions cannot lie outside
    ``[min, max]`` of those contributions. Ordinary market disagreement —
    however violent — can never violate it; only a pipeline, routing or
    calibration fault can. That is exactly the distinction the corridor's
    stated purpose required and its implementation could not make.

    Why the corridor was removed rather than retuned
    ────────────────────────────────────────────────

    Its band was a P90 of the drift distribution of the board it was
    policing, so it clamped the worst ~10% of *whatever* it was handed.
    Measured over 17 independent historical days / 5,931 IDP rows the
    trigger rate never left 8.7-9.2%, and scaling every IDP value by 10x
    fired the identical rows at the identical rate — a board-wide error
    was invisible to it. Its anchor was also a voter in the blend it
    corrected, on 539 of 539 clamped rows.

    And it caught nothing upstream did not already handle. Injecting
    anomalies into the SOURCE CSVs and rebuilding the whole pipeline, the
    corridor fired on 0 of 6 victims in every scenario: a single source at
    x5 or x20 is absorbed by the Hampel filter plus the count-aware blend
    (<=1.7% movement), and an anchor source at x5 is caught outright by
    the declared-range check (0.0% movement). Correlated multi-source
    anomalies do get through (up to 48%), but the corridor missed those
    too — and so does this detector, because sources agreeing on something
    wrong is indistinguishable from disagreement at the blend. That gap is
    pre-existing and named rather than papered over.

    Why ABSTAIN rather than clamp
    ─────────────────────────────

    If a value here is impossible under correct operation, coercing it to
    the nearest boundary would turn pipeline corruption into a clean,
    plausible-looking number. The row is marked instead, so the failure
    stays visible. There is no tolerance dial: the check is exact up to
    the representation of its inputs, and both allowances are
    numerical-precision, NOT policy bands — measured across 5,931
    historical rows the violation count is 0 at every tolerance from 0%
    to 10%, so no policy slack is doing any work.

    "Representation of its inputs" is doing real work in that sentence,
    and this check got it wrong until 2026-08-25: the two quantities
    compared here are integers quantized from floats by DIFFERENT rules
    (``rankDerivedValue`` truncates; the ``valueContribution`` stamps
    round), so a float blend genuinely inside its hull can publish up to
    1.5 below the stamped minimum and 0.5 above the stamped maximum.
    ``_BLEND_HULL_EPSILON`` alone manufactured a "violation" out of that
    skew whenever the stamped hull was under a unit wide — see the
    derivation and the measured 2027 Mid 2nd incident at
    ``_BLEND_HULL_QUANTIZATION_BELOW``. The additive allowance covers
    exactly the quantization worst case and nothing else: a fault that
    moves a value by even two units past the hull still fires.

    Rows resting on fewer than two contributions are skipped: a hull needs
    two points, and "missing" is not "violating".
    """
    for row in players_array:
        if not row.get("canonicalConsensusRank"):
            continue
        meta = row.get("sourceRankMeta")
        if not isinstance(meta, dict):
            continue
        contributions: dict[str, float] = {}
        for source_key, m in meta.items():
            if not isinstance(m, dict):
                continue
            raw = m.get("valueContribution")
            # Missing is not zero. A source that stamped no contribution
            # is absent from the hull rather than pinned to its floor —
            # coercing ``None`` to 0.0 here would invent a lower bound of
            # zero and make every real value look "inside" it.
            if raw is None:
                continue
            try:
                c = float(raw)
            except (TypeError, ValueError):
                continue
            if c > 0:
                contributions[str(source_key)] = c
        if len(contributions) < 2:
            continue
        try:
            value = float(row.get("rankDerivedValue") or 0.0)
        except (TypeError, ValueError):
            continue
        if value <= 0:
            continue

        lo, hi = min(contributions.values()), max(contributions.values())
        lo_bound = lo * (1.0 - _BLEND_HULL_EPSILON) - _BLEND_HULL_QUANTIZATION_BELOW
        hi_bound = hi * (1.0 + _BLEND_HULL_EPSILON) + _BLEND_HULL_QUANTIZATION_ABOVE
        if lo_bound <= value <= hi_bound:
            continue

        stamp = {
            "detected": True,
            "reason": "blend_outside_contribution_hull",
            "value": int(round(value)),
            "contributionMin": int(round(lo)),
            "contributionMax": int(round(hi)),
            "sourceCount": len(contributions),
            "direction": "above" if value > hi else "below",
            # The value is NOT altered. This is a pipeline-integrity
            # signal, not a correction.
            "valueAltered": False,
        }
        row["blendIntegrityViolation"] = stamp

        # Abstention, expressed through the channel the platform already
        # routes on.  ``blendIntegrityViolation`` above is a rich
        # diagnostic that nothing reads; ``anomalyFlags`` is what
        # ``_validate_and_quarantine_rows`` consults, and the flag is in
        # ``_QUARANTINE_FLAGS``, so the row comes out of that pass
        # ``quarantined`` with a degraded confidence bucket.  Consensus
        # Edge then Withholds it, BDVM skips it, and /edge drops it —
        # all pre-existing behaviour for quarantined rows.
        #
        # Without this the detector would be diagnostics only: the value
        # is proven impossible and would still be consumed as an ordinary
        # canonical number by everything downstream.
        flags = list(row.get("anomalyFlags") or [])
        if "blend_integrity_violation" not in flags:
            flags.append("blend_integrity_violation")
        row["anomalyFlags"] = flags

        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["blendIntegrityViolation"] = dict(stamp)


# ── Rank change — derived from the temporal ledger (C1-HIST-03) ────────
# ``rankChange`` is a DERIVED quantity, not mutable state.  It is the
# difference between a row's current ``canonicalConsensusRank`` and the
# same asset's rank on the latest canonical-board date STRICTLY BEFORE
# this board's own date, read from the temporal ledger
# (``src/history`` — the one owner of as-of history).
#
# This replaces the retired single-slot cache
# ``data/snapshots/ranks_last.json``, which made rankChange
# non-deterministic by construction: every non-override build (server
# scrape promotions, startup priming, the two daily offline recorder
# scripts, and — W03-F010 — even a stock ``/rankings`` override
# request) rewrote the baseline, so build N+1 diffed against build N's
# own output and two back-to-back builds of identical inputs disagreed
# on 740 rows (B-audit residual H).  It was also keyed by bare
# ``canonicalName``, so cross-universe same-name players fabricated
# movement for each other.  Both defects are pinned in
# ``tests/history/test_temporal_red.py`` and closed by
# ``tests/history/test_temporal_ledger.py``.
#
# Determinism properties of the derivation:
#   * same board + same ledger → same stamps, however many times the
#     build runs (a rebuild has no side effect here — nothing writes);
#   * the comparator is a DATED observation (latest ledger date before
#     the board date), never the previous build's output — recording
#     today's board cannot change today's comparator because the
#     lookup is strictly-before;
#   * keys are the canonical asset namespace (``player:<id>`` /
#     ``name:<canonical>::<group>`` / ``mpick:*``), so the collision
#     class is unrepresentable;
#   * no prior board date, no ledger, or a lookup failure → ``None``
#     ("no historical comparator"), NEVER 0.
#
# Rollback: ``RISKIT_FEATURE_LEDGER_RANK_CHANGE=0`` stamps ``None``
# everywhere (honest missing).  It deliberately does NOT resurrect the
# retired cache — a rollback must not reintroduce the defect.


def _stamp_rank_changes(
    rows: list[dict[str, Any]],
    *,
    board_date: str | None = None,
    ledger_path: "Path | None" = None,
) -> None:
    """Stamp ``rankChange`` (positive = moved up) on each ranked row,
    derived from the temporal ledger's previous board date.

    ``board_date`` is the board's own UTC date claim (the raw
    payload's ``date``); when absent, today-UTC.  Read-only: this
    function writes nothing anywhere, on any build kind — recording
    into the ledger happens only at the fresh-scrape promotion site in
    ``server.py``.
    """
    # AUDIT F-24 — this gate is INVISIBLE to every operator surface, and
    # registering it is BLOCKED rather than forgotten.
    #
    # Read straight from the environment and defaulted ON, it appears in
    # neither ``feature_flags.snapshot()`` nor ``effective_flags()`` nor
    # ``/api/status``, and ``test_feature_flag_reachability.py`` cannot see
    # it either.  The rollback lever CLAUDE.md documents is real; the
    # inventory that would tell an operator it exists is not.
    #
    # F-24 CLOSED 2026-08-25 (V1-87).  The paragraph above records why the
    # flag could not be registered without a measurement, and the
    # measurement now exists: Lane 4 on-box run 32843495391 (deployed
    # ``8537aa4c2``, ledger present, 37 recorded board dates) measured ON
    # deriving a non-null ``rankChange`` for 743 of 749 ranked rows on the
    # 2026-08-25 board (comparator 2026-08-24) against a structurally
    # all-None OFF.  The flag is registered in ``feature_flags._DEFAULTS``
    # carrying that blast radius, classified ``value_moving_on``, and this
    # site now reads through the ONE registry owner rather than the
    # environment directly — so /api/status, ``snapshot()`` and the
    # reachability test finally see the rollback lever CLAUDE.md documents.
    # Registry reads are cached per process (same convention as
    # ``bdvm_engine``); tests that flip the env mid-process call
    # ``feature_flags.reload()``.
    from src.api import feature_flags as _feature_flags

    previous: dict[str, tuple[str, int]] = {}
    _history_keys = None
    if _feature_flags.is_enabled("ledger_rank_change"):
        # Every src.history touch — the keys import included — sits
        # inside one guard: a history failure (or the rollback flag)
        # must not break the contract build, and the degraded stamp is
        # "no comparator" (None), never a wrong number.
        try:
            from src.history import asof as _asof
            from src.history import keys as _history_keys  # noqa: F811

            if not board_date:
                board_date = datetime.now(timezone.utc).date().isoformat()
            previous = _asof.previous_board_ranks(before_date=board_date, path=ledger_path)
        except Exception:
            previous = {}

    for row in rows:
        rank = row.get("canonicalConsensusRank")
        try:
            cur_rank = int(rank) if rank is not None else None
        except (TypeError, ValueError):
            cur_rank = None
        if cur_rank is None or _history_keys is None:
            row["rankChange"] = None
            continue
        keyed = _history_keys.asset_key_for_contract_row(row)
        prev = previous.get(keyed[0]) if keyed else None
        if prev is not None and prev[1] > 0:
            # Positive = moved UP (prev rank higher number, now lower
            # number).  A player at prev=50 who's now at 40 moved up
            # 10; change = 10.
            row["rankChange"] = prev[1] - cur_rank
        else:
            row["rankChange"] = None


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


def _family_evidence_for_row(
    *,
    row: dict[str, Any],
    effective_source_ranks: dict[str, Any],
    effective_source_meta: dict[str, dict[str, Any]],
    src_by_key: dict[str, dict[str, Any]],
    family_by_key: dict[str, str],
    fresh_by_source: dict[str, bool | None],
) -> list["FamilyEvidence"]:
    """Assemble the B11 gate's per-family evidence for one row.

    ONE assembly, TWO callers: the ranked path and the off-cap player
    value pass (#1101).  Extracted rather than transcribed, because a
    second copy of this block would be a second confidence methodology —
    ``src/api/confidence.py`` owns what the levels MEAN and this owns
    what evidence it is shown, and both halves need exactly one owner.

    Decides no level.  Every judgement below is about what a source
    contribution IS, not about how good it is.
    """
    row_is_te = str(row.get("position") or "").strip().upper() == "TE"
    evidence: list[FamilyEvidence] = []
    for skey in effective_source_ranks:
        smeta = effective_source_meta.get(skey) or {}
        # Family-superseded members are not independent evidence;
        # B10-T3b already excluded them from the blend.
        if smeta.get("contributedToBlend") is False:
            continue
        method = str(smeta.get("method") or "")
        src_def = src_by_key.get(skey, {})
        evidence.append(
            FamilyEvidence(
                family=family_by_key.get(skey, skey),
                source_key=skey,
                value_contribution=smeta.get("valueContribution"),
                fresh=fresh_by_source.get(skey),
                # ADR-015 lifts a non-TEP source's TE row onto the
                # TE++ basis the board is anchored on.  A measured
                # conversion, not a native observation.
                format_native=(not row_is_te) or bool(src_def.get("is_tep_premium")),
                # An approximating translation — rookie ladder or
                # backbone fallback — is a guess at where the
                # source would have placed the player.
                directly_observed=(
                    method != TRANSLATION_FALLBACK
                    and not method.startswith("rookie_ladder_translation")
                ),
            )
        )
    return evidence


def _restate_confidence_after_override(
    players_array: list[dict[str, Any]],
    confidence_inputs: dict[int, tuple[list[FamilyEvidence], set[str]]],
    pre_override_values: dict[int, Any],
) -> list[str]:
    """Re-run the confidence gate on rows a post-blend override moved.

    The gate's agreement axis compares each family's contribution to the
    PUBLISHED value, so a stamp taken before an override describes a
    number the row no longer carries.  Rather than special-casing the one
    override that exists today, this asks the general question — did
    ``rankDerivedValue`` change since the gate ran? — so any future
    post-blend pass is covered by construction.

    Returns the canonical names it re-stated, for the caller's log.
    """
    restated: list[str] = []
    for row_idx, (evidence, eligible) in confidence_inputs.items():
        row = players_array[row_idx]
        current = row.get("rankDerivedValue")
        if current == pre_override_values.get(row_idx):
            continue
        assessment = assess_confidence(
            evidence,
            eligible_families=eligible,
            consensus_value=current,
        )
        row["confidenceBucket"] = assessment.overall
        row["confidenceLabel"] = assessment.label
        row["confidenceBasis"] = "evidence_gate"
        row["confidenceAxes"] = dict(assessment.axes)
        row["confidenceReasons"] = list(assessment.reasons)
        restated.append(str(row.get("canonicalName") or row.get("displayName") or row_idx))
    return restated


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

    from src.canonical.tail_policy import TAIL_SATURATION_RANK  # noqa: PLC0415

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
            # The rank past which the coordinate stops resolving. Stamped
            # so the frontend explorer renders the SAME domain the board
            # is priced on, rather than transcribing a second tail rule —
            # a divergence W30-F023 already produced once, with the chart
            # extrapolating smoothly while serving saturated at 500.
            # ``None`` means "saturate at ``referenceN``" (pre-B4).
            "saturationRank": TAIL_SATURATION_RANK,
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
        "provenance": _hill_master_provenance(),
    }


def _hill_master_provenance() -> dict[str, Any]:
    """Model provenance stamp for the Hill scope masters (V1-21 / W04-F011).

    W04-F011: "Derived values carry no model version, param-set id or
    as-of stamp — /api/data serves values with nothing recording which
    champion produced them."  ``src/model_registry/`` already exists and
    already records exactly that (see its package docstring), but by
    design "does not change what any live endpoint returns" — nothing
    under ``src/api`` ever read it.  This is the read-only stamp that
    closes that gap, reusing the SAME ``modelVersion`` / ``paramSetId`` /
    ``asOf`` vocabulary ``src/bdvm`` and ``src/consensus_edge`` already
    established (see ``src/consensus_edge/params.py``'s own docstring:
    "a second [convention] would be a drift risk, not a feature") rather
    than inventing a fourth.

    Never computes a value and never changes what the board prices — the
    champion pointer is consulted for its METADATA only.  Truthful, not
    merely present: a version number is stamped ONLY when the live
    constants byte-match the recorded champion's params exactly.  Any
    divergence — constants hand-edited without a promote()+apply() cycle,
    a registry file that fails to load, a model with no champion — is
    reported ``status: "unverified"``/``"unavailable"`` with the reason
    named, never coerced onto the nearest-looking version.  A fallback
    (unverified) state is a DIFFERENT status than a verified one; neither
    is ever silently upgraded into the other.
    """
    import hashlib  # noqa: PLC0415

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
    from src.model_registry import ModelRegistry, RegistryError  # noqa: PLC0415

    live_params = {
        "HILL_GLOBAL_PERCENTILE_C": float(HILL_GLOBAL_PERCENTILE_C),
        "HILL_GLOBAL_PERCENTILE_S": float(HILL_GLOBAL_PERCENTILE_S),
        "HILL_PERCENTILE_C": float(HILL_PERCENTILE_C),
        "HILL_PERCENTILE_S": float(HILL_PERCENTILE_S),
        "IDP_HILL_PERCENTILE_C": float(IDP_HILL_PERCENTILE_C),
        "IDP_HILL_PERCENTILE_S": float(IDP_HILL_PERCENTILE_S),
        "HILL_ROOKIE_PERCENTILE_C": float(HILL_ROOKIE_PERCENTILE_C),
        "HILL_ROOKIE_PERCENTILE_S": float(HILL_ROOKIE_PERCENTILE_S),
    }

    try:
        registry = ModelRegistry.load("hill_scope_masters")
    except (RegistryError, OSError, ValueError, KeyError, TypeError) as exc:
        # Broad on purpose: a malformed/corrupt registry file (bad JSON,
        # a missing required key) must degrade this stamp to UNAVAILABLE,
        # never crash the whole /api/data build over a diagnostic field.
        return {
            "status": "unavailable",
            "modelVersion": None,
            "paramSetId": None,
            "asOf": None,
            "reason": f"model registry unreadable: {exc}",
        }

    if not registry.has_champion:
        return {
            "status": "unavailable",
            "modelVersion": None,
            "paramSetId": None,
            "asOf": None,
            "reason": "hill_scope_masters registry has no champion",
        }

    champion = registry.champion
    champion_params = {str(k): float(v) for k, v in champion.params.items()}
    matches = champion_params.keys() == live_params.keys() and all(
        abs(champion_params[k] - v) < 1e-9 for k, v in live_params.items()
    )

    if not matches:
        return {
            "status": "unverified",
            "modelVersion": None,
            "paramSetId": None,
            "asOf": None,
            "reason": (
                "live constants in player_valuation.py do not match registry "
                f"champion v{champion.version}'s recorded params — promote()/"
                "apply() may be out of sync with what is actually committed"
            ),
        }

    digest = hashlib.sha256(
        json.dumps(champion_params, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return {
        "status": "verified_champion",
        "modelVersion": champion.version,
        "paramSetId": f"hill_scope_masters:{digest}",
        "asOf": champion.promoted_at or champion.fitted_at,
        "fittedAt": champion.fitted_at,
        "producer": champion.producer,
        "qualified": champion.qualified,
        "confidence": champion.confidence,
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


def _validate_source_game_types_invariant(
    sources: list[dict[str, Any]] | None = None,
) -> None:
    """Module-import safety rail: **every voting source must be PROVEN
    dynasty** (``C1-SRC-02``).

    Refuses, with the offending keys named:

    * a source declaring no ``game_type`` at all — silence is not
      consent, and defaulting an unlabelled feed to DYNASTY is the exact
      inference the spec forbids;
    * a ``game_type`` outside :data:`GAME_TYPES`;
    * any value other than ``DYNASTY`` — including ``UNKNOWN``, which is
      the whole point: *unverified is never dynasty*;
    * a declaration with no ``game_type_evidence``, because a label
      nobody can re-check is the comment this replaced.

    Raising at IMPORT is deliberate. The alternative — filtering the
    offender out of the blend — would let a redraft board sit in the
    registry looking registered while quietly not voting, and the next
    reader would have to run the pipeline to find out which sources are
    real. A registry that cannot be trusted by reading it is the
    condition this unit exists to end.

    ``sources`` is injectable so the gate can be exercised against a
    rogue entry without mutating the live registry.
    """
    registry = _RANKING_SOURCES if sources is None else sources

    undeclared: list[str] = []
    unknown_value: list[tuple[str, Any]] = []
    not_dynasty: list[tuple[str, Any]] = []
    unevidenced: list[str] = []

    for src in registry:
        key = str(src.get("key") or "<unnamed>")
        declared = src.get("game_type")
        if not declared:
            undeclared.append(key)
            continue
        if declared not in GAME_TYPES:
            unknown_value.append((key, declared))
            continue
        if declared != GAME_TYPE_DYNASTY:
            not_dynasty.append((key, declared))
            continue
        if not str(src.get("game_type_evidence") or "").strip():
            unevidenced.append(key)

    problems: list[str] = []
    if undeclared:
        problems.append(
            f"declare no game_type: {undeclared}. A source that votes on dynasty value "
            f"without saying it IS dynasty is trusted for who published it."
        )
    if unknown_value:
        problems.append(
            f"declare a game_type outside GAME_TYPES: {unknown_value}. Valid: {sorted(GAME_TYPES)}"
        )
    if not_dynasty:
        problems.append(
            f"are not DYNASTY: {not_dynasty}. This is a dynasty product; a redraft, ROS, "
            f"weekly, best-ball or UNVERIFIED board may not price a dynasty asset. "
            f"Archive it if you want the data, but do not register it for voting."
        )
    if unevidenced:
        problems.append(
            f"declare DYNASTY with no game_type_evidence: {unevidenced}. Record HOW it "
            f"was established — endpoint semantics, an explicit provider label, a page "
            f"control — so the claim is re-checkable."
        )

    if problems:
        raise ValueError("C1-SRC-02 game-type gate: " + " | ".join(problems))


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
_validate_source_game_types_invariant()
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
    # DERIVED from the pick-map owner, not restated (audit 2026-08-17).
    # This was a literal ``{"Early": 2, "Mid": 6, "Late": 10}`` — a
    # fourth hand-written copy of the same 12-team tier ranges, sitting a
    # few thousand lines from the owner that defines them.  It agreed,
    # which is exactly why it survived: a second owner that disagrees
    # gets found, a second owner that agrees does not.
    #
    # Verified an EXACT identity before the swap: the owner's centres are
    # 2.5 / 6.5 / 10.5 and Python's banker's rounding takes those to
    # 2 / 6 / 10 — the literal's own values, unchanged.
    _tier_ranges = _site_pick_map.slot_tier_ranges(12)
    tier_centre_slot = {
        tier.capitalize(): round((lo + hi) / 2) for tier, (lo, hi) in _tier_ranges.items()
    }
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
        # The value is cleared two lines up, so this row is genuinely unpriced —
        # a different statement from "priced, but nothing assessed it".
        row["confidenceBasis"] = "unpriced"
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
        # C1-U5: when this pass prices a row that neither assessment pass
        # reached, it owns the confidence statement too — otherwise the row
        # keeps the constructor's placeholder and reads as "unranked and
        # therefore unconfident" when the truth is "tethered to a real
        # rookie value, with no pick market of its own". Measured: 24 rows,
        # all round-5/6 slots, which are the ones no pick market prices.
        #
        # Scoped to UNASSESSED rows deliberately. This pass anchors all 72
        # current-year slots, and the other 48 were already assessed by the
        # dispersion rule. Restamping those would downgrade real pick-market
        # confidence to a derivation label — a methodology change, not a
        # naming migration, and out of scope for C1-U5. That the tether
        # overwrites a value whose confidence was measured from the pick
        # market is a real question; it is recorded as a follow-up rather
        # than decided quietly here.
        if not row.get("confidenceBasis") or row.get("confidenceBasis") in (
            "unpriced",
            "no_evidence",
        ):
            row["confidenceBucket"] = "low"
            row["confidenceLabel"] = (
                "Low — tethered to the rookie at this slot (no direct pick market)"
            )
            row["confidenceBasis"] = "derived_rookie_tether"
            row["confidenceAxes"] = None
            row["confidenceReasons"] = None
        anchored += 1
    return anchored


# ``_compute_pick_confidence`` lived here until C1-U5 and was imported BACK
# into ``src/api/confidence.py`` — the declared canonical owner reaching into
# its own consumer.  The rule now lives at the owner as
# ``confidence._pick_confidence_from_values``, arithmetic unchanged.  Call
# ``confidence.assess_pick_confidence`` instead; do not re-add a pick
# confidence rule to this module.


def _apply_pick_year_discount_to_blend(
    row_normalized: list[tuple[float, int]],
    players_array: list[dict[str, Any]],
    synthetic_pick_derivations: Mapping[str, dict[str, Any]] | None = None,
) -> tuple[list[tuple[float, int]], dict[int, float]]:
    """Stamp the effective year-derivation factor on synthetic-year picks.

    **C1-U6: this pass no longer changes any value.**  The measured
    vendor year-step is applied to the cloned per-source values AT
    INJECTION (:func:`_inject_far_future_pick_sources`), so the blend
    already carries the derived level and multiplying here again would
    double-count.  What survives is the transparency stamp:
    ``pickYearDiscount`` = the net factor the row's source values were
    stepped by, read by ``_stamp_pick_value_projections`` (which inverts
    it into the on-draft projection), the delta payload and the
    frontend.  The returned per-row map keeps the audit shape.

    ONLY SYNTHESISED YEARS carry a factor (audit finding T-3/C-2,
    2026-08-04).  A vendor-priced year needs no correction — the price
    already encodes the term structure: both ingested pick markets
    price the next class ABOVE the imminent one (+26% at round 1), so
    composing any decay onto real prices published 2027 firsts 18% and
    2028 firsts 34% BELOW what both markets agreed, biasing every trade
    involving future capital the same way (sell futures cheap, buy
    futures expensive).  ``synthetic_pick_derivations`` is exactly the
    synthesized set (the map ``_inject_far_future_pick_sources``
    returned for THIS build), so it is the gate — pinned by
    ``tests/api/test_pick_year_discount_gate.py``.

    Audit V-12/C-11 (the uncalibrated 0.53-on-a-clone prior this pass
    used to apply) is CLOSED by the injection-time measured year-step —
    challenger record in ``docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md``.
    """
    derivations = synthetic_pick_derivations or _EMPTY_PICK_DERIVATIONS
    stamped: dict[int, float] = {}
    for _value, row_idx in row_normalized:
        row = players_array[row_idx]
        if row.get("assetClass") != "pick":
            continue
        cname = row.get("canonicalName") or ""
        derivation = derivations.get(_canonical_match_key(cname))
        if derivation is None:
            # Vendor-priced year: the market already priced the year.
            continue
        factor = derivation.get("factor")
        if isinstance(factor, (int, float)) and 0 < float(factor) < 1.0:
            stamped[row_idx] = float(factor)
            row["pickYearDiscount"] = round(float(factor), 4)
    return row_normalized, stamped


def _build_generic_pick_row(name: str, value: int) -> dict[str, Any]:
    """A standard-shaped, rank-less board row for a generic-grade pick.

    Mirrors ``_derive_player_row``'s field template (same defaults, same
    trust/transparency keys) so downstream passes — values-bundle sync,
    validation shape checks, legacy mirror, app view — need no special
    case.  Deliberately NO rank, NO tier, NO source votes: the tier rows
    stay the ranked market representation; the generic row is the
    valuation representation of an unrealized league pick
    (``market_resolution``'s ``unknown_slot`` basis).
    """
    return {
        "playerId": None,
        "canonicalName": name,
        "displayName": name,
        "position": "PICK",
        "team": None,
        "age": None,
        "yearsExp": None,
        "rookie": False,
        "assetClass": "pick",
        "values": {
            "overall": None,
            "finalAdjusted": None,
            "displayValue": None,
            "rawComposite": None,
        },
        "canonicalSiteValues": {},
        "rawSourceValues": {},
        "sourceCount": 0,
        "sourcePresence": {},
        "marketConfidence": None,
        "marketBreadthAgreementIndex": None,
        "marketBreadthScore": None,
        "marketAgreementScore": None,
        "marketDispersionCV": None,
        "legacyRef": name,
        "confidenceBucket": "low",
        "confidenceLabel": "Low — derived from tier values (no direct market row)",
        "confidenceBasis": "derived_tier_values",
        "confidenceAxes": None,
        "confidenceReasons": None,
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
        "idpBackboneFallback": False,
        "droppedSources": [],
        "effectiveSourceRanks": {},
        "effectiveSourceCount": 0,
        "independentSourceCount": 0,
        "sourceRanks": {},
        "sourceRankMeta": {},
        "sourceOriginalRanks": {},
        "sourceNativeValues": {},
        "canonicalConsensusRank": None,
        "canonicalTierId": None,
        "canonicalPercentile": None,
        "rankChange": None,
        "quarantined": False,
        "marketGapDirection": None,
        "marketGapMagnitude": None,
        "marketGapValueRatio": None,
        "identityConfidence": None,
        "identityMethod": None,
        "identityResolutionConfidence": None,
        "identityResolutionMethod": None,
        "rankDerivedValue": int(value),
    }


def _complete_future_pick_values(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
    current_year: int,
    synthetic_pick_derivations: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Guarantee a finite canonical value for every valid future pick
    through the horizon, and stamp provenance on EVERY pick row (C1-U6,
    manifest C1-PICK-01).

    Runs after the rookie tether and before the draft-day projections,
    so it sees final values for everything the blend and the tether
    priced.  Three derivations, strict priority (direct evidence always
    outranks a derivation — a row that already carries a finite value is
    never touched):

    1. **Round-step** (``derivedRoundModel``, classification PRIOR) —
       future-year tier rows in rounds no vendor prices (5-6; both pick
       markets stop at round 4) derive from the same year+tier's nearest
       priced lower round: ``value(R) = value(R-1) × roundStep(R)``.
       The steps are the served canonical board's own tethered
       rookie-market round ladder (measured stable across the archive);
       the assumption that the current class's tail structure carries to
       future classes is named in the config.

    2. **Uniform-tier EV** (``genericGradeModel``, classification
       PRIOR) — a rank-less generic-grade row (``"2027 Round 1"``) per
       future year × round, valued at the unweighted mean of the
       year+round's three tier values.  This is the board row for
       ``market_resolution``'s ``unknown_slot`` basis — the honest
       representation of a league pick whose slot does not exist yet.
       Identity fabricates nothing (C1-U3 frozen): the tier rows stay
       untouched, and C1-U7 replaces the uniform assumption with real
       owned-pick distributions.

    3. **Provenance** — every pick row gets ``pickValueProvenance``
       naming which evidence class produced its number:
       ``direct_market_blend`` / ``rookie_pool_tether`` /
       ``derived_year_step`` / ``derived_round_step`` /
       ``derived_uniform_tier_ev`` / ``alias_suppressed`` /
       ``unavailable`` (with a reason — never 0, never a fabricated
       value).

    Returns ``{canonicalName: value}`` for rows this pass derived
    (audit/test hook).
    """
    cfg = _load_pick_year_discount()
    try:
        horizon = max(0, int(cfg.get("horizonYears") or 3))
    except (TypeError, ValueError):
        horizon = 3
    round_steps = cfg.get("roundStepByRound") or {}

    def _finite_value(row: dict[str, Any] | None) -> float | None:
        if not isinstance(row, dict):
            return None
        v = row.get("rankDerivedValue")
        if (
            isinstance(v, (int, float))
            and not isinstance(v, bool)
            and math.isfinite(float(v))
            and v > 0
        ):
            return float(v)
        return None

    by_name: dict[str, dict[str, Any]] = {}
    for row in players_array:
        if row.get("assetClass") == "pick":
            by_name[str(row.get("canonicalName") or "")] = row

    future_years = range(current_year + 1, current_year + horizon + 1)
    derived: dict[str, int] = {}

    # ── 0. Year-step completion for unpriced future tier rows ──
    #
    # AUDIT F-30.  The horizon guarantee must not depend on WHICH raw
    # vendor keys happened to survive a given scrape.
    #
    # ``_inject_far_future_pick_sources`` seeds the synthetic far-future rows by
    # cloning the template year's entry out of ``players_by_name`` — the RAW
    # scraper payload — and that population is strictly poorer than the one the
    # canonical board uses for the same template year: ``ktcSfTep``'s pick
    # values arrive through the LATER CSV enrichment, which correctly carries no
    # far-future year to enrich a synthetic row with.  Since V1-132 (F-34) the
    # post-enrichment ``_complete_synthetic_pick_sources_from_enrichment`` pass
    # steps the TEMPLATE row's enriched values onto the synthetic rows, so a
    # synthetic row normally votes on both pick markets — but that pass can
    # only widen what the template row carries.  When the template's evidence
    # itself thins out (in-JSON AND CSV), a synthetic row is still left with no
    # voting source at all.  No voter means no rank, no rank means no
    # ``rankDerivedValue``.
    #
    # Measured 2026-08-18: the 17:11Z scrape's in-JSON ``idpTradeCalc`` pick
    # values collapsed to the round-1 tiers while BOTH vendor CSVs stayed
    # complete (36 ``ktcSfTep`` + 84 ``idpTradeCalc`` pick rows).  Every 2029 row
    # in rounds 2-6 blended to ``None`` and the census failed 20 cells on a board
    # whose evidence was intact — and it skipped a production deploy.
    #
    # **The basis is searched, not remembered.**  An earlier revision of this
    # pass completed a row from the derivation record ``_inject_far_future_pick_sources``
    # had stored, which repaired the observed incident but inherited the
    # injection's own precondition: the injection **no-ops for a year that
    # already carries any tier row**, so a PARTIALLY published horizon year
    # records nothing and the rung could not fire.  That is the shape a vendor
    # publishing part of the horizon produces, and it fails the census exactly
    # as the original incident did.  So this searches the board for the nearest
    # priced EARLIER FUTURE year instead, which subsumes the recorded-derivation
    # case and covers the partial one.  (Found by lane 7 in #916; its measured
    # comparison is in the F-30 entry.)
    #
    #     value(Y, tier, round) = value(Ybasis, tier, round)
    #                             × yearStep(tier, round) ** (Y − Ybasis)
    #
    # Same approved ``derivedYearModel`` family and the same measured per-cell
    # steps as the injection, through the one shared ``_year_step_for``.  What
    # differs is the BASIS QUANTITY — the published board value rather than the
    # template year's raw per-source values — which is precisely what makes the
    # guarantee independent of the raw key set, and why the provenance says so
    # via ``appliedTo``.
    #
    # DOMAIN is the config's own measured surface (rounds 1-4 today).  Rounds it
    # publishes no cell for would fall to ``yearStepFallback``, an unmeasured
    # number for those rounds — they take the round-step rung below instead,
    # which is anchored on measured round ratios.
    #
    # Runs BEFORE the round-step rung so a year-stepped round 4 can serve as the
    # basis for rounds 5-6.  Nothing is keyed to a particular year: the horizon
    # self-rolls with ``current_year``.
    year_step_rounds: set[int] = set()
    for _cell in cfg.get("yearStepByTierRound") or {}:
        _, _, _cell_round = str(_cell).partition(".")
        if _cell_round.isdigit():
            year_step_rounds.add(int(_cell_round))
    for _cell in cfg.get("yearStepByRound") or {}:
        if str(_cell).isdigit():
            year_step_rounds.add(int(_cell))
    for year in future_years:
        for tier in ("Early", "Mid", "Late"):
            for rnd in sorted(year_step_rounds):
                name = f"{year} {tier} {_round_suffix(rnd)}"
                row = by_name.get(name)
                # Direct evidence outranks derivation absolutely, and is never
                # relabelled as derived.
                if row is None or _finite_value(row) is not None:
                    continue
                # Nearest priced EARLIER **future** year.  Never the current
                # draft year: its rows are rookie-pool-tethered slot picks, a
                # different quantity, and vendor-priced years take no year
                # discount at all (T-3/C-2).
                basis_name: str | None = None
                basis_year: int | None = None
                basis_value: float | None = None
                for cand_year in range(year - 1, current_year, -1):
                    cand_name = f"{cand_year} {tier} {_round_suffix(rnd)}"
                    cand_value = _finite_value(by_name.get(cand_name))
                    if cand_value is not None:
                        basis_name, basis_year, basis_value = cand_name, cand_year, cand_value
                        break
                if basis_value is None or basis_year is None:
                    # No future evidence to step from.  The row stays unpriced
                    # and is reported ``unavailable`` with a reason below —
                    # never 0, never a fabricated number.
                    continue
                gap = year - basis_year
                factor = _year_step_for(tier, rnd, cfg) ** gap
                value = int(round(basis_value * factor))
                if value <= 0:
                    continue
                row["rankDerivedValue"] = value
                row["confidenceBucket"] = "low"
                row["confidenceLabel"] = (
                    "Low — derived from the nearest priced future year (no market row)"
                )
                row["confidenceBasis"] = "derived_year_step"
                row["confidenceAxes"] = None
                row["confidenceReasons"] = None
                row["pickYearDiscount"] = round(factor, 4)
                row["pickValueProvenance"] = {
                    "class": "derived_year_step",
                    "family": "measured_vendor_year_step_v1",
                    "classification": "PRIOR",
                    "basis": basis_name,
                    "basisYear": basis_year,
                    "factor": round(factor, 4),
                    # WHICH quantity the factor multiplied.  The injection-time
                    # derivation of the SAME family steps the template year's
                    # per-SOURCE values; this one steps the template year's
                    # published board value.  Same model, different basis
                    # quantity — and stepping-then-blending is not
                    # blending-then-stepping, so two stamps of one model that
                    # are not interchangeable must not read identically.
                    "appliedTo": "canonical_board_value",
                }
                derived[name] = value
                legacy = players_by_name.get(row.get("legacyRef") or name)
                if isinstance(legacy, dict):
                    legacy["rankDerivedValue"] = value

    # ── 1. Round-step completion for unpriced future tier rows ──
    for year in future_years:
        for tier in ("Early", "Mid", "Late"):
            for rnd in range(2, 7):
                name = f"{year} {tier} {_round_suffix(rnd)}"
                row = by_name.get(name)
                if row is None or _finite_value(row) is not None:
                    continue
                step = round_steps.get(str(rnd))
                if step is None:
                    continue  # only vendor-uncovered rounds carry a configured step
                basis_name = f"{year} {tier} {_round_suffix(rnd - 1)}"
                basis_row = by_name.get(basis_name)
                basis_value = _finite_value(basis_row)
                if basis_value is None:
                    continue
                try:
                    step_f = max(0.05, min(1.0, float(step)))
                except (TypeError, ValueError):
                    continue
                value = int(round(basis_value * step_f))
                if value <= 0:
                    continue
                row["rankDerivedValue"] = value
                row["confidenceBucket"] = "low"
                row["confidenceLabel"] = "Low — derived from the same year's nearest priced round"
                row["confidenceBasis"] = "derived_round_step"
                row["confidenceAxes"] = None
                row["confidenceReasons"] = None
                prov: dict[str, Any] = {
                    "class": "derived_round_step",
                    "family": "canonical_rookie_ladder_round_step_v1",
                    "classification": "PRIOR",
                    "basis": basis_name,
                    "factor": round(step_f, 4),
                }
                basis_year_stamp = basis_row.get("pickYearDiscount") if basis_row else None
                if isinstance(basis_year_stamp, (int, float)):
                    row["pickYearDiscount"] = round(float(basis_year_stamp), 4)
                    prov["yearStepFactor"] = round(float(basis_year_stamp), 4)
                    # WHAT the factor is relative to (2026-08-16, C1-U6
                    # follow-up 9).  ``yearStepFactor`` alone reads as
                    # "the step from the current draft year", and it is
                    # not: this row inherits the year factor of its
                    # round-4 basis, which itself steps from a TEMPLATE
                    # year.  Naming the basis is the difference between a
                    # reproducible stamp and a plausible one; no value
                    # changes.
                    # Read the basis year from the BUILD's derivation map,
                    # not from the basis row's provenance: this pass runs
                    # before the pass that stamps it, so the row would
                    # answer None and the stamp would silently omit the
                    # one fact it exists to carry.
                    basis_derivation = (synthetic_pick_derivations or _EMPTY_PICK_DERIVATIONS).get(
                        _canonical_match_key(basis_name)
                    )
                    if isinstance(basis_derivation, dict) and basis_derivation.get("basisYear"):
                        prov["yearStepBasisYear"] = basis_derivation["basisYear"]
                    prov["yearStepInheritedFrom"] = basis_name
                row["pickValueProvenance"] = prov
                derived[name] = value
                legacy = players_by_name.get(row.get("legacyRef") or name)
                if isinstance(legacy, dict):
                    legacy["rankDerivedValue"] = value

    # ── 2. Generic-grade rows (uniform-tier EV) ──
    for year in future_years:
        for rnd in range(1, 7):
            tiers = [
                by_name.get(f"{year} {t} {_round_suffix(rnd)}") for t in ("Early", "Mid", "Late")
            ]
            tier_values = [_finite_value(t) for t in tiers]
            priced = [v for v in tier_values if v is not None]
            name = f"{year} Round {rnd}"
            existing = by_name.get(name)
            if existing is not None and _finite_value(existing) is not None:
                continue  # a real source row for the generic grade wins
            if len(priced) < 3:
                continue  # derive only from a complete tier set
            value = int(round(sum(priced) / len(priced)))
            if value <= 0:
                continue
            if existing is None:
                row = _build_generic_pick_row(name, value)
                players_array.append(row)
                by_name[name] = row
            else:
                row = existing
                row["rankDerivedValue"] = value
                row["confidenceBucket"] = "low"
                row["confidenceLabel"] = "Low — derived from tier values (no direct market row)"
                row["confidenceBasis"] = "derived_tier_values"
            prov = {
                "class": "derived_uniform_tier_ev",
                "family": "uniform_tier_ev_v1",
                "classification": "PRIOR",
                "basis": [f"{year} {t} {_round_suffix(rnd)}" for t in ("Early", "Mid", "Late")],
            }
            year_stamps = [
                t.get("pickYearDiscount")
                for t in tiers
                if isinstance(t, dict) and isinstance(t.get("pickYearDiscount"), (int, float))
            ]
            if len(year_stamps) == 3:
                net = round(sum(float(v) for v in year_stamps) / 3.0, 4)
                row["pickYearDiscount"] = net
                prov["yearStepFactor"] = net
                # A generic row's factor is the MEAN of its three tier
                # factors, not a step this row itself took.  Say so
                # (follow-up 9): the tiers can carry different factors,
                # and a reader who assumes a single step cannot
                # reproduce this number from any one of them.
                prov["yearStepFactorIsMeanOfBasis"] = True
                derivations_map = synthetic_pick_derivations or _EMPTY_PICK_DERIVATIONS
                basis_years = {
                    (
                        derivations_map.get(_canonical_match_key(str(t.get("canonicalName") or "")))
                        or {}
                    ).get("basisYear")
                    for t in tiers
                    if isinstance(t, dict)
                }
                basis_years.discard(None)
                if len(basis_years) == 1:
                    prov["yearStepBasisYear"] = basis_years.pop()
            row["pickValueProvenance"] = prov
            derived[name] = value
            legacy = players_by_name.get(name)
            if not isinstance(legacy, dict):
                legacy = {}
                players_by_name[name] = legacy
            legacy["rankDerivedValue"] = value
            legacy["_canonicalConsensusRank"] = None
            legacy["sourceCount"] = 0

    # ── 3. Provenance on every remaining pick row ──
    for row in players_array:
        if row.get("assetClass") != "pick" or row.get("pickValueProvenance"):
            continue
        cname = str(row.get("canonicalName") or "")
        if row.get("pickGenericSuppressed"):
            row["pickValueProvenance"] = {
                "class": "alias_suppressed",
                "basis": row.get("pickAliasFor"),
            }
            continue
        if row.get("pickRookieAnchor"):
            row["pickValueProvenance"] = {
                "class": "rookie_pool_tether",
                "basis": row.get("pickRookieAnchor"),
            }
            continue
        derivation = (synthetic_pick_derivations or _EMPTY_PICK_DERIVATIONS).get(
            _canonical_match_key(cname)
        )
        # A derivation ENTRY is not a derived VALUE.  The injection records one
        # for every synthetic row it seeds, including rows whose cloned sources
        # then failed to blend — and stamping ``derived_year_step`` on a row
        # carrying no value claims a derivation that produced no number, which
        # reads as an explained row and is not one (audit F-30).  Require the
        # value; a valueless row falls through to ``unavailable`` with a reason.
        if derivation is not None and _finite_value(row) is not None:
            row["pickValueProvenance"] = {
                "class": "derived_year_step",
                "family": derivation.get("family"),
                "classification": derivation.get("classification"),
                "basis": derivation.get("basisName"),
                "basisYear": derivation.get("basisYear"),
                "factor": derivation.get("factor"),
            }
            continue
        if _finite_value(row) is not None:
            row["pickValueProvenance"] = {"class": "direct_market_blend"}
        else:
            row["pickValueProvenance"] = {
                "class": "unavailable",
                "reason": "no_market_evidence_and_no_derivation_basis",
            }
    return derived


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
    board_date: str | None = None,
    synthetic_pick_derivations: Mapping[str, dict[str, Any]] | None = None,
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

    # Per-BUILD synthetic-pick derivations, supplied by the caller that
    # ran ``_inject_far_future_pick_sources`` on this payload.  Never a
    # module global (see ``_EMPTY_PICK_DERIVATIONS``): two overlapping
    # override builds in one process must not be able to see each
    # other's.  Empty is a legitimate state — a build whose sources
    # already publish every horizon year synthesizes nothing.
    synthetic_pick_derivation_map: Mapping[str, dict[str, Any]] = (
        synthetic_pick_derivations or _EMPTY_PICK_DERIVATIONS
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
    # ``correlation_group_for`` scans the registry, and the B11 gate asks
    # per (row, source).  Resolved once here over the WHOLE registry —
    # not just the active subset — so a key that survives in cached data
    # after its source is disabled still resolves to its own family.
    family_by_key: dict[str, str] = {
        str(s.get("key") or ""): correlation_group_for(str(s.get("key") or ""))
        for s in _RANKING_SOURCES
    }

    # ── Phase 0: Build IDP backbone from the designated backbone source ──
    # The first enabled source with scope=overall_idp and is_backbone=True
    # wins.  With no backbone source the ladder is empty and every
    # crosswalk-dependent source falls back to treating its raw rank as a
    # synthetic overall rank, with a caution flag on the per-source meta.
    #
    # WHICH sources that actually affects, measured rather than assumed:
    # the ``needs_shared_market_translation`` ones — today ``dlfIdp`` and
    # ``fantasyProsIdp`` (``idpShowCombined`` no longer crosswalks through
    # this backbone as of 2026-08-20 — it is registered ``is_cross_market``
    # and reads its own native combined rank instead; the 235-row figure in
    # the dated table below predates that change and describes the retired
    # ``idpShow`` key).  The
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
    #
    # Lane 8: the ladder is now built by the CROSS-POSITION BRIDGE OWNER
    # (``src/bridges``) from every QUALIFIED bridge that measures capable on
    # this board, not from the first source carrying ``is_backbone``.  That
    # flag is a label — it can be moved onto a source that cannot seed a
    # ladder, satisfying the guard while leaving the board broken
    # (``tests/consensus_edge/test_fair_value.py::TestTheGuardIsACapabilityNotAFlag``)
    # — and it is no longer read here.  Capability is measured; a bridge is a
    # FAMILY, so a vendor whose offense and IDP halves sit under two registry
    # keys (Draft Sharks) can seed a ladder for the first time.
    #
    # With ONE usable bridge the combined ladder is the incumbent ladder,
    # integer for integer, so the healthy board cannot move merely because a
    # second bridge became possible.
    backbone_source_key: str | None = None
    if True:
        # ── Derived rows are not this vendor's evidence ──────────────
        #
        # The backbone answers ONE question: at which positions in THIS
        # VENDOR'S OWN published value pool do IDP players sit?  Its
        # answer is then used to translate OTHER sources' ranks.  A
        # synthetic far-future pick row is not published by the vendor —
        # it is our own PRIOR-classified derivation, written into
        # ``canonicalSiteValues`` under the vendor's key at injection so
        # that the row can be blended.  Leaving it in the ladder lets a
        # derived prior act as market evidence about other rows, and
        # closes a feedback loop: our derived pick value shifts the
        # crosswalk, which shifts IDP players' translated votes, which
        # shifts the blend.  Signal independence forbids exactly that
        # (C1-U6 follow-up 2).
        #
        # The boundary is deliberate and narrow.  Being ON the board —
        # and therefore in the board's own ordering — is the product
        # decision that far-future picks exist and are priced, and that
        # is unchanged.  What is withdrawn is the claim that a vendor
        # OBSERVED them.  Vendor-published pick rows stay in the pool;
        # they are real observations on the vendor's own scale.
        backbone_rows = players_array
        if synthetic_pick_derivation_map:
            backbone_rows = [
                r
                for r in players_array
                if not (
                    isinstance(r, dict)
                    and _canonical_match_key(str(r.get("canonicalName") or ""))
                    in synthetic_pick_derivation_map
                )
            ]
        # ── Bridge assessment ───────────────────────────────────────
        # A bridge whose source is switched off by an override is
        # UNAVAILABLE, not merely uncovered: ``canonicalSiteValues``
        # still carries a disabled source's numbers, so measuring
        # capability alone would let a source the caller excluded keep
        # translating.
        bridge_offense_positions = frozenset(_OFFENSE_POSITIONS | {"PICK"})
        bridge_idp_positions = frozenset(_IDP_POSITIONS)
        bridge_descriptors = load_bridge_descriptors()
        bridge_acquisition = {
            key: AcquisitionOutcome(
                source_key=key,
                state=ACQ_UNAVAILABLE,
                reason="source is not active for this build",
            )
            for d in bridge_descriptors
            for key in d.keys
            if key not in active_keys
        }
        bridge_assessments = assess_bridges(
            bridge_descriptors,
            backbone_rows,
            offense_positions=bridge_offense_positions,
            idp_positions=bridge_idp_positions,
            acquisition=bridge_acquisition,
        )
        from src.api import feature_flags as _feature_flags  # noqa: PLC0415

        bridge_ladder = build_bridge_ladder(
            bridge_assessments,
            backbone_rows,
            offense_positions=bridge_offense_positions,
            idp_positions=bridge_idp_positions,
            # Off by default: admitting a second bridge is a methodology
            # change with measured board movement, and it is separable from
            # the withholding repair, which is unconditional.
            limit=None if _feature_flags.is_enabled("multi_bridge_ladder") else 1,
        )

        # ``backbone`` survives for the PER-POSITION ladders the dormant
        # ``position_idp`` branch reads, and for the depth stamped in
        # ``sourceRankMeta``.
        #
        # It is deliberately NOT gated on bridge capability.  A per-position
        # ladder ("DL3 sits at overall-IDP rank 5") is an ordering WITHIN the
        # IDP class; it carries no claim about offense and needs no
        # cross-position evidence.  Only the shared-market ladder below is a
        # cross-position statement, and only it is gated.  Collapsing the two
        # would refuse an intra-IDP translation for want of evidence it never
        # needed.
        usable_bridges = [a for a in bridge_assessments if a.usable]
        if usable_bridges:
            backbone_source_key = usable_bridges[0].descriptor.idp_keys[0]
        else:
            for _d in bridge_descriptors:
                _seed = next((k for k in _d.idp_keys if k in active_keys), None)
                if _seed:
                    backbone_source_key = _seed
                    break
        if backbone_source_key:
            backbone = build_backbone_from_rows(
                backbone_rows,
                source_key=backbone_source_key,
                idp_positions=_IDP_POSITIONS,
                offense_positions=_OFFENSE_POSITIONS | {"PICK"},
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
    # {sourceKey: rows whose vote was withheld for want of a usable bridge}.
    # Reported on the contract; never silently zero.
    withheld_no_bridge: dict[str, int] = {}
    # row_eligible_families[row_idx] = every provider family that COULD
    # have covered this row.  Filled in Phase 3 beside softFallbackCount
    # (same eligibility test) and read by the B11 confidence gate.
    row_eligible_families: dict[int, set[str]] = {}
    # The gate's inputs, kept per row so a post-blend override that moves
    # a value can re-state the confidence that describes it.
    row_confidence_inputs: dict[int, tuple[list[FamilyEvidence], set[str]]] = {}
    # For backbone assertion: remember the actual ladder depth used
    backbone_depth = backbone.depth
    # The combined ladder from every usable bridge.  EMPTY means no bridge
    # could be qualified, and an empty ladder is a refusal, not a degenerate
    # ladder — see the withholding branch in Phase 1.
    shared_market_ladder = list(bridge_ladder.ladder)
    shared_market_depth = bridge_ladder.reference_depth

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
                else:
                    # ── Lane 8: WITHHOLD, never pass the raw rank through ──
                    #
                    # A source flagged ``needs_shared_market_translation``
                    # ranks players within the IDP class only.  With no usable
                    # ladder, ``translate_position_rank`` returns the raw rank,
                    # and recording it here is the defect this lane exists to
                    # remove: the vote then asserts that IDP #1 is asset #1.
                    # Measured with ``idpTradeCalc`` excluded, that was 661
                    # votes on untranslated ranks and a top IDP published at
                    # 9,999 — because ``percentile_to_value`` short-circuits an
                    # effective rank of 1 to ``DISPLAY_SCALE_MAX`` exactly.
                    #
                    # A specialist board genuinely does not know where its #1
                    # sits against offense, so the honest answer is to cast no
                    # vote rather than to cast a fabricated one.  The row keeps
                    # every source that CAN be translated; if that leaves it
                    # with too few, the existing single-source haircut and the
                    # confidence gate describe it truthfully.
                    withheld_no_bridge.setdefault(source_key, 0)
                    withheld_no_bridge[source_key] += 1
                    continue
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
                    contribution_path = "rank_hill"
                    fallback_reason = (
                        "source_suppressed"
                        if source_key in value_range_suppressed
                        else "value_out_of_declared_range"
                    )
                elif raw_f > 0.0 and site_max > 0.0:
                    value = raw_f / site_max * 9999.0
                    contribution_path = "value_direct"
                    fallback_reason = None
                else:
                    # Fall back to the Hill path if the raw value is
                    # missing/invalid — should be rare, but protects
                    # against malformed site data dropping a source's
                    # vote to zero silently.
                    value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
                    contribution_path = "rank_hill"
                    fallback_reason = (
                        "value_missing_or_nonpositive" if raw_f <= 0.0 else "no_site_maximum"
                    )
            else:
                value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
                contribution_path = "rank_hill"
                fallback_reason = None
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
            # RECORDED from the branch above, never re-derived here. The
            # previous expression asked a different question than the
            # serving branch did — it tested only "is this a value source
            # with a positive site max", ignoring all three conditions
            # that actually route a row to the Hill path (source
            # suppressed, value out of declared range, value
            # missing/non-positive). A row taking the fallback was
            # therefore stamped ``value_direct`` while being priced by the
            # curve, and no fallback could ever be stamped ``rank_hill``
            # while the source had any in-range row at all.
            #
            # That made the field unusable for the question it exists to
            # answer, and it silently invalidated any measurement gated on
            # it: B4's fallback-traffic count read this stamp, so its zero
            # was structurally unreachable rather than observed. (Measured
            # directly on the same pin, the true fallback count is also
            # zero — the reported number was right, the evidence for it
            # was not.)
            meta["valueContributionPath"] = contribution_path
            if fallback_reason is not None:
                # Why a value-direct source was priced by the curve. This
                # is a live branch with no live traffic, so without a
                # reason stamped the first real occurrence would be
                # indistinguishable from a rank-only source's normal vote.
                meta["valueDirectFallbackReason"] = fallback_reason
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

        # ── One vote per provider family (B10-T3b) ──
        #
        # Runs AFTER Hampel deliberately: Hampel's verdicts are about
        # whether a source got THIS player wrong, and it should judge
        # the raw observation set.  Collapsing first would change
        # rejection decisions about unrelated sources.
        #
        # A SELECTION, never an average — see
        # ``collapse_to_independent_families``.  ``_source_precedence``
        # is registry order, which already declares the heads.
        surviving = [(k, v, a) for k, v, a in all_value_pairs if k not in set(hampel_dropped_keys)]
        family_kept, family_superseded = collapse_to_independent_families(surviving)
        if family_superseded:
            kept_keys = {k for k, _v, _a in family_kept}
            all_values = [v for k, v, _a in family_kept]
            cross_market_values = [v for k, v, a in family_kept if a]
            subgroup_values = [v for k, v, a in family_kept if not a]
            all_weights = [blend_weight_by_source.get(k, 1.0) for k, _v, _a in family_kept]
            cross_market_weights = [
                blend_weight_by_source.get(k, 1.0) for k, _v, a in family_kept if a
            ]
            subgroup_weights = [
                blend_weight_by_source.get(k, 1.0) for k, _v, a in family_kept if not a
            ]
            for sk, winner in family_superseded.items():
                meta = row_source_meta[row_idx].get(sk, {})
                # The observation is kept and still readable — it did not
                # vote, which is a different statement from it not existing.
                meta["contributedToBlend"] = False
                meta["supersededBy"] = winner
            del kept_keys

        # Three counts, named for what they each mean.  ``sourceCount``
        # (stamped elsewhere) stays the raw matched-key count, because it
        # answers a COVERAGE question — "did the scrape reach this row".
        # These two answer independence questions and must not be
        # conflated with it.
        players_array[row_idx]["effectiveSourceCount"] = len(surviving)
        players_array[row_idx]["independentSourceCount"] = len(family_kept)

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
        # The COVERAGE DENOMINATOR for B11 confidence: every provider
        # family that could have covered this row, whether or not it did.
        # Seeded from the families that actually voted so the covered set
        # is a subset by construction, then widened by the eligibility
        # test below — which is the same test ``softFallbackCount`` uses,
        # walked once for both answers.
        #
        # Denominating coverage on what COULD have spoken rather than on
        # what did is what stops deleting evidence from reading as a
        # tidier panel: an eligible family that stops covering a row is
        # missing evidence for as long as it stays eligible.
        eligible_families: set[str] = {family_by_key.get(k, k) for k in source_ranks}
        for src in active_sources:
            skey = str(src.get("key") or "")
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
            eligible_families.add(family_by_key.get(skey, skey))
            if skey in source_ranks:
                continue
            fallback_count += 1

        players_array[row_idx]["softFallbackCount"] = fallback_count
        row_eligible_families[row_idx] = eligible_families

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
        row_normalized, players_array, synthetic_pick_derivation_map
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
        if allowlist_reason is None and cname in synthetic_pick_derivation_map:
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

    # One stat pass for the whole board.  The B11 gate asks per row.
    fresh_by_source = _source_freshness_flags()

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
        # STANDING on the canonical board — 0-100, 100 = best (B9b).
        #
        # Published here because this is where the ranked pool exists.
        # A consumer holding one row cannot compute it, and one holding a
        # truncated board would compute a standing within the part it
        # received and call it a percentile.  It is the scale-stable
        # companion to ``rankDerivedValue``: a value means nothing
        # without the distribution behind it, which is the defect class
        # B9b exists to close.
        row["canonicalPercentile"] = (
            round(100.0 * (total_ranked - overall_rank) / (total_ranked - 1), 4)
            if total_ranked > 1
            else 100.0
        )

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
        # Family-aware since B11 — see ``assess_pick_confidence``.
        if row.get("assetClass") == "pick":
            basis = "pick_dispersion"
            is_slot_specific = _parse_pick_slot(row.get("canonicalName") or "") is not None
            bucket, label = assess_pick_confidence(
                row.get("canonicalSiteValues") or {},
                is_slot_specific=is_slot_specific,
            )
            row["confidenceAxes"] = None
            row["confidenceReasons"] = None
        else:
            # ── B11: the multi-axis gate ──
            #
            # The retired rule was ``max(percentile) − min(percentile)``
            # behind an ``n >= 2`` count gate.  A range can only narrow
            # when an observation is removed, so "narrower ⇒ more
            # confident" meant deleting evidence promoted a row — the
            # failure #833 recorded and could not fix by feeding the same
            # statistic a better population.
            #
            # ``src/api/confidence.py`` owns the replacement outright:
            # five axes over B10 family HEADS, combined by bottleneck.
            # Everything this loop does here is ASSEMBLE the evidence —
            # no level is decided in this file.
            evidence = _family_evidence_for_row(
                row=row,
                effective_source_ranks=effective_source_ranks,
                effective_source_meta=effective_source_meta,
                src_by_key=src_by_key,
                family_by_key=family_by_key,
                fresh_by_source=fresh_by_source,
            )
            # Kept so a LATER post-blend override that moves this row's
            # value can re-state its confidence against the value that
            # actually shipped.  See ``_restate_confidence_after_override``.
            row_confidence_inputs[row_idx] = (
                evidence,
                row_eligible_families.get(row_idx, set()),
            )
            basis = "evidence_gate"
            assessment = assess_confidence(
                evidence,
                eligible_families=row_eligible_families.get(row_idx, set()),
                consensus_value=derived,
            )
            bucket = assessment.overall
            label = assessment.label
            row["confidenceAxes"] = dict(assessment.axes)
            row["confidenceReasons"] = list(assessment.reasons)
            # ``assessment.metrics`` is deliberately NOT stamped.  It is
            # the arithmetic behind the reasons, and the reasons already
            # carry the numbers a reader needs ("11 of 12 families price
            # within 15% of the published value").  Publishing both cost
            # +220 KB raw / +15 KB gzip per contract for a block nothing
            # renders, on the payload CLAUDE.md's performance rules name
            # first.  It stays on the assessment object for tests and
            # in-process auditors.
        row["confidenceBucket"] = bucket
        row["confidenceLabel"] = label
        row["confidenceBasis"] = basis

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

    # ── Phase 4b': off-cap VALUE stamping (C1-U6 RED-1; #1101) ──
    #
    # ``OVERALL_RANK_LIMIT`` is a RANK concept: the board publishes 800
    # ranked rows.  It is NOT a claim that the 801st asset is worthless,
    # and #1101 separates the two questions outright:
    #
    #   A. canonical VALUE availability   — does this asset have a price?
    #   B. canonical TOP-BOARD membership — does it get a rank and tier?
    #
    # The cap answers B and only B.  So every row past it that VOTED —
    # a pick, or a player carrying at least one matched trusted dynasty
    # source and a positive canonical blend — keeps the value the
    # pipeline has ALREADY computed for it.  Value only: no rank, no
    # tier, no percentile, no standing.  A row here legitimately
    # publishes ``rankDerivedValue > 0`` beside
    # ``canonicalConsensusRank: None`` / ``canonicalTierId: None``, and
    # that pairing is the intended shape, not an inconsistency.
    #
    # The pick half landed first (manifest C1-PICK-01: "every valid pick
    # through 2029 has a finite canonical value"), mirroring the posture
    # the rookie-anchor pass already took for current-year slot picks.
    # The PLAYER half is #1101: measured on the 2026-08-25 board, 186
    # players past the cap carried real source ranks and a positive
    # blend (155..1186) and published ``rankDerivedValue: None`` — Trey
    # Lance among them, with 8 sources and a blend of 1102.  A rank cap
    # withholding a rank is top-board policy; a rank cap erasing a
    # measured value is evidence loss.
    #
    # ``row_normalized`` is built from ``row_source_ranks``, so ARRIVING
    # here is itself the evidence gate: a row nothing matched never
    # enters this list and stays unpriced.  MISSING IS NEVER ZERO — and
    # never ``DISPLAY_SCALE_MIN`` either.  Nothing below invents a value
    # for a row that has none; it publishes the one already computed.
    for norm_val, row_idx in row_normalized[OVERALL_RANK_LIMIT:]:
        row = players_array[row_idx]
        if norm_val <= 0:
            # No positive canonical evidence to publish.  Leave the row
            # unpriced rather than floor it up to 1 — a floor is what a
            # real value is held ABOVE, not what a missing one becomes.
            continue
        # The canonical scale's own minimum, from the scale's owner
        # (``player_valuation.DISPLAY_SCALE_MIN``); no second literal is
        # declared here.  The ranked path's ``int(norm_val)`` truncates,
        # so a blend of 0.6 — real evidence, genuinely tiny — would
        # otherwise be published as exactly the 0 this pass exists to
        # stop manufacturing.
        #
        # Stated plainly: on the live board this floor is DEFENSIVE and
        # binds nothing.  The Hill tail puts the deepest off-cap blend at
        # 155, three orders of magnitude clear of it.  It is here because
        # the correct rule is "positive evidence publishes at least the
        # scale minimum", not because a row was measured needing it — and
        # a floor that only appears once something has already been
        # rounded to zero is a floor added too late.
        derived = max(_CANONICAL_VALUE_MIN, int(norm_val))

        if row.get("assetClass") == "pick":
            row["rankDerivedValue"] = derived
            row["offCapPickValue"] = True
            is_slot_specific = _parse_pick_slot(row.get("canonicalName") or "") is not None
            bucket, label = assess_pick_confidence(
                row.get("canonicalSiteValues") or {},
                is_slot_specific=is_slot_specific,
            )
            row["confidenceBucket"] = bucket
            row["confidenceLabel"] = label
            row["confidenceBasis"] = "pick_dispersion"
            row["confidenceAxes"] = None
            row["confidenceReasons"] = None
        else:
            source_ranks = row_source_ranks.get(row_idx) or {}
            if not source_ranks:
                # Unreachable by construction (see above); kept as the
                # structural guard that says so, because the day the
                # blend loop's input widens, this is the line that must
                # refuse rather than the one that prices a stranger.
                continue
            source_meta = row_source_meta.get(row_idx, {})
            dropped_set = set(row.get("droppedSources") or [])
            effective_source_ranks = {k: v for k, v in source_ranks.items() if k not in dropped_set}
            effective_source_meta = {k: v for k, v in source_meta.items() if k not in dropped_set}
            row["rankDerivedValue"] = derived
            row["offCapPlayerValue"] = True
            # Publish the post-Hampel set the assessment below was read
            # from.  Leaving the template's ``{}`` on a row that now
            # carries a price would assert "no source survived" about a
            # row priced by the survivors.
            row["effectiveSourceRanks"] = effective_source_ranks
            # Confidence comes from the SAME owner and the SAME evidence
            # assembly the ranked path uses — no off-cap methodology, and
            # nothing here promotes a row for being priced.  Whatever the
            # gate returns is what ships: on the live board these rows
            # answer ``low``, because coverage/agreement are genuinely
            # thin this deep, which is the truthful answer rather than a
            # flattering one.
            evidence = _family_evidence_for_row(
                row=row,
                effective_source_ranks=effective_source_ranks,
                effective_source_meta=effective_source_meta,
                src_by_key=src_by_key,
                family_by_key=family_by_key,
                fresh_by_source=fresh_by_source,
            )
            # Registered so a LATER post-blend override that moves this
            # row's value re-states its confidence against the number
            # that actually shipped, exactly as for a ranked row.
            row_confidence_inputs[row_idx] = (
                evidence,
                row_eligible_families.get(row_idx, set()),
            )
            assessment = assess_confidence(
                evidence,
                eligible_families=row_eligible_families.get(row_idx, set()),
                consensus_value=derived,
            )
            row["confidenceBucket"] = assessment.overall
            row["confidenceLabel"] = assessment.label
            row["confidenceBasis"] = "evidence_gate"
            row["confidenceAxes"] = dict(assessment.axes)
            row["confidenceReasons"] = list(assessment.reasons)

        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["rankDerivedValue"] = derived

    # ── Phase 4c: removed ──
    # The IDP calibration post-pass (a Lab-configured per-bucket
    # multiplier applied to DL/LB/DB rows) has been retired.  The
    # live ``rankDerivedValue`` is now the canonical-pipeline output
    # with no post-blend adjustment on IDPs.  The prior
    # ``rankDerivedValueUncalibrated`` / ``canonicalConsensusRankUncalibrated``
    # snapshots are no longer stamped — downstream consumers fall
    # back to the live rank and value, which are the single source
    # of truth for every position.

    # Blend-integrity detection: flag any row whose blended value fell
    # OUTSIDE the range of its own source contributions.  That is
    # structurally impossible under correct operation, so it is a
    # pipeline-integrity signal rather than a disagreement to be corrected
    # — the row is stamped, quarantined, and its value is left alone.
    # See ``_detect_blend_integrity_violations``.
    #
    # WHERE this sits, precisely.  It runs after the blend and the
    # count-aware aggregation, and BEFORE the two-way-player boost
    # immediately below and the Phase 5 pick passes further down.  This
    # comment used to claim it ran "after all value-moving passes", which
    # is simply false.
    #
    # The placement is chosen on what the invariant MEANS, not on a
    # measured difference.  The invariant says a *blend* cannot leave the
    # range of the contributions it was blended from; the later stages are
    # deliberate OVERRIDES that replace the blended value with a number
    # computed from a different population (the alt-position family's
    # implied value; the merged rookie pool's value), so the invariant
    # does not describe their output and asking it there is a category
    # error.
    #
    # Measured on the live board, both placements currently flag ZERO
    # rows, so this is not a false-positive rate anyone has observed —
    # Travis Hunter's boosted 4758 lands inside his own (2538, 5637) hull,
    # and every ranked pick with two contributions sits inside its hull
    # too.  Stating that plainly rather than claiming the later placement
    # "would" misfire, which the evidence does not show.
    #
    # This replaced the market-anchor corridor clamp (#794/#795/#796).
    # The clamp coerced values toward a "market anchor" that was itself a
    # voter in the blend it corrected, using a band re-derived from the
    # same board, so it clamped a fixed ~9% of rows whether the board was
    # healthy or catastrophically broken.
    #
    # ``suppress_market_corridor_clamp`` keeps its name for the one
    # caller that passes it (``src/consensus_edge/fair_value.py``), whose
    # requirement was "do not pull my board back toward a market anchor".
    # That requirement is now satisfied unconditionally — nothing here
    # reads an anchor or changes a value — so the flag only suppresses
    # the diagnostic stamp.
    if not suppress_market_corridor_clamp:
        _detect_blend_integrity_violations(players_array, players_by_name)

    # Two-way player boost: a tiny override table that rescues players
    # whose Sleeper single-position classification excludes them from
    # the IDP blend (Travis Hunter — WR in Sleeper, CB on the field,
    # ranked #1 by IDP Show / top-50 by FBG IDP / etc).  For each
    # entry, compute the alt-family's implied value from the already-
    # loaded IDP source synthetic ranks and replace rankDerivedValue
    # with max(offense_value, alt_family_value).
    pre_override_values = {
        row_idx: players_array[row_idx].get("rankDerivedValue") for row_idx in row_confidence_inputs
    }
    _apply_two_way_player_boost(players_array, players_by_name)
    # ── Confidence describes the value that SHIPPED (B11) ──
    #
    # The gate's agreement axis asks how many families price within a
    # material relative gap of ``rankDerivedValue``.  Every post-blend
    # OVERRIDE therefore invalidates the answer it was given, because the
    # override replaces the blended number with one computed from a
    # different population — and no source published the result.
    #
    # Found on Travis Hunter, the whole of ``_TWO_WAY_PLAYERS``: the boost
    # lifts him from the offense blend's ~2,900 to 4,758 (the alt-family
    # value), leaving all eleven of his families 24-56% BELOW the
    # published value while the row still claimed high agreement.  The
    # retired percentile-spread rule never touched the value, so this
    # coupling is new with the gate and is fixed here rather than left as
    # a stale stamp.
    #
    # Written as a general guard over "did the value move", not as a
    # special case for the boost table, so a future override inherits it.
    _restate_confidence_after_override(players_array, row_confidence_inputs, pre_override_values)

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

    # 2b') Complete future-pick values through the horizon (C1-U6,
    #      manifest C1-PICK-01): round-step derivation for the rounds no
    #      vendor prices (5-6), rank-less generic-grade rows for
    #      ``market_resolution``'s unknown-slot basis, and
    #      ``pickValueProvenance`` on every pick row.  Direct market
    #      evidence always outranks a derivation — rows the blend or the
    #      tether priced are never touched.
    _complete_future_pick_values(
        players_array, players_by_name, _anchor_year, synthetic_pick_derivation_map
    )

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

    # Rank-change vs the previous BOARD DATE, derived read-only from
    # the temporal ledger (src/history).  Identical on every rebuild of
    # the same board — override and delta builds included, which is
    # what closed W03-F010 (any request used to be able to clobber the
    # old snapshot baseline; there is no baseline to clobber now).
    _stamp_rank_changes(
        tiered_rows,
        board_date=board_date,
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

    global _LAST_CROSS_POSITION_BRIDGE_SUMMARY
    _LAST_CROSS_POSITION_BRIDGE_SUMMARY = {
        "bridges": [a.to_dict() for a in bridge_assessments],
        "ladder": bridge_ladder.to_dict(),
        # Per source key: how many votes were withheld for want of a usable
        # bridge, rather than passed through untranslated (Lane 8's repair).
        # Never silently absent — an empty dict IS the honest "0 withheld".
        "withheldNoBridge": dict(withheld_no_bridge),
        "multiBridgeLadderEnabled": _feature_flags.is_enabled("multi_bridge_ladder"),
    }

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
    """Delegates to the canonical pick-identity owner (C1-ID-02)."""
    return _owner_is_pick_name(name)


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
        # C1-U5: a bounded ``site_score*0.65 + cv_score*0.35`` blend of
        # source COUNT and DISPERSION, measured on the live board to span
        # [0.3252, 0.59375] — it never reaches the top 40% of the 0-1 scale
        # its old name implied. Renamed to what it measures, with the two
        # halves the scraper already computes now published instead of
        # discarded, and the ceiling stamped so the number cannot be read
        # as a confidence.
        "marketBreadthAgreementIndex": _safe_num(p_data.get("_marketConfidence")),
        "marketBreadthScore": _safe_num(p_data.get("_marketBreadthScore")),
        "marketAgreementScore": _safe_num(p_data.get("_marketAgreementScore")),
        "marketConfidence": _safe_num(p_data.get("_marketConfidence")),
        "marketDispersionCV": _safe_num(p_data.get("_marketDispersionCV")),
        "legacyRef": canonical_name,
        # Trust/transparency defaults — overwritten by _compute_unified_rankings
        # for players that receive a unified rank.
        # The owner decides what an unassessed row says. This default is
        # what 24 PRICED rows wore before C1-U5, because
        # ``_anchor_current_year_picks_to_rookies`` priced them after both
        # assessment passes had skipped them and wrote no confidence field.
        "confidenceBucket": "none",
        "confidenceLabel": "None — unranked",
        "confidenceBasis": "unpriced",
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
        "identityResolutionConfidence": 0.70,
        "identityResolutionMethod": "name_only",
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
    # The map is BUILD-SCOPED: created here, handed to the pipeline, and
    # dropped when this build ends.  Nothing is stored on the module, so
    # concurrent override builds cannot cross-contaminate (follow-up 8).
    synthetic_pick_derivations = _inject_far_future_pick_sources(
        players_by_name, current_rookie_draft_year()
    )

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

    # V1-132 / audit F-34: the far-future injection above ran against the
    # RAW payload, where only the in-JSON pick markets exist; the CSV
    # enrichment has now put ``ktcSfTep``'s pick values on the template
    # year's rows.  Extend the SAME derivation (same cell step, same
    # compounding, same provenance) to that enriched evidence so the
    # horizon year blends both pick markets like every published year.
    _complete_synthetic_pick_sources_from_enrichment(players_array, synthetic_pick_derivations)

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

    # ONE CANONICAL BOARD.  There used to be a pre-pass here that ran
    # ``_compute_unified_rankings`` a SECOND time with every IDP-scoped
    # source disabled and stamped the result as
    # ``offenseOnlyRankDerivedValue``, which the trade engines then
    # substituted whenever a trade happened to contain no defender.
    #
    # It was a second canonical board: same function, same scale, and on
    # the 2026-08-14 contract 491 of the 507 comparable rows disagreed
    # with canonical by up to 21.87%.  The disagreement was not confined
    # to defenders — PICKS moved most (2026 Pick 2.06: 3,224 → 2,519),
    # which is what shows the mechanism was never "exclude IDP
    # calibration from IDP-free trades".  Disabling a source changes the
    # count-aware blend, the Hampel filter, the single-source haircut and
    # the pick anchor set for EVERY row, because ``idpTradeCalc`` is a
    # full-roster calculator that prices offense and picks too.
    #
    # Removed rather than deprecated: leaving a ready-made second
    # canonical board on every row is what let three separate engines
    # wire it into ``displayValue`` / ``modelValue`` without anyone
    # deciding to.  An IDP-free view filters the asset universe or names
    # its lens; it does not reprice the assets.  See W29-F001 / W29-F002
    # and ``tests/api/test_one_canonical_value_per_asset.py``.
    #
    # Also removes a full second run of the ranking pipeline from every
    # non-delta contract build.

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
        # The board's own UTC date claim — the rankChange derivation's
        # comparison anchor (latest ledger date strictly before it).
        board_date=str(raw_payload.get("date") or "") or None,
        synthetic_pick_derivations=synthetic_pick_derivations,
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
            # Published from the same constants the validator enforces, so
            # the contract cannot advertise a range the board is not held
            # to (B9a).
            "scaleMin": _CANONICAL_VALUE_MIN,
            "scaleMax": _CANONICAL_VALUE_MAX,
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
        # What the LIVE path actually decides on (B11).
        #
        # Published from the gate's OWN parameters and axis list, not
        # restated.  The previous version of this block described a rule
        # the code had already stopped using — the absolute-ordinal
        # "sourceRankSpread <= 30 / <= 80" — and so contradicted the
        # published bucket on 251 of 788 rows, 31.9% of the field.
        # Deriving the description from the same file that decides is
        # what stops that recurring.
        "confidenceGate": {
            "owner": "src/api/confidence.py",
            "unitOfEvidence": (
                "the B10 provider family (correlation group), never the source "
                "key: a second observation from an already-represented family "
                "is not an input to any axis"
            ),
            "combination": (
                "BOTTLENECK — the overall level is the weakest axis.  Nothing "
                "averages, so a large source count cannot compensate for stale, "
                "inapplicable, thin or disagreeing evidence"
            ),
            "axes": {
                "independence": (
                    f"how many independent families voted; high at "
                    f"{int(_confidence_gate_parameter('INDEPENDENCE_HIGH_FAMILIES'))}+, "
                    f"medium at "
                    f"{int(_confidence_gate_parameter('INDEPENDENCE_MEDIUM_FAMILIES'))}+"
                ),
                "coverage": (
                    "share of the ELIGIBLE families that actually covered this "
                    "asset — the denominator is what could have spoken, so a "
                    "family that stops covering a row registers as missing "
                    "evidence rather than as a tidier panel"
                ),
                "freshness": (
                    "share of contributing families inside their declared "
                    "maxAgeHours budget; unknown freshness is not fresh"
                ),
                "applicability": (
                    "share of contributing families that reached this asset "
                    "without an approximating translation.  Degraded one level "
                    "when most of the evidence needed ADR-015's TE-premium "
                    "basis conversion — a measured correction, so it costs a "
                    "level rather than the axis"
                ),
                "agreement": (
                    f"share of contributing families pricing within "
                    f"{_confidence_gate_parameter('AGREEMENT_VALUE_RATIO')} "
                    "relative of rankDerivedValue, using the same symmetric "
                    "mean normalisation as marketGapValueRatio"
                ),
            },
            "shareLadder": {
                "high": _confidence_gate_parameter("EVIDENCE_SHARE_HIGH"),
                "medium": _confidence_gate_parameter("EVIDENCE_SHARE_MEDIUM"),
            },
            "none": "no evidence family covers this asset",
            "perRowFields": [
                "confidenceBucket",
                "confidenceLabel",
                "confidenceAxes",
                "confidenceReasons",
            ],
            "picks": (
                "picks keep their own coefficient-of-variation rule "
                "(assess_pick_confidence) because rank spread on picks is "
                "dominated by the flat-value regions in R3-R6 — but it is "
                "family-aware, so two members of one provider cast one vote"
            ),
            "retired": (
                "max(percentile) - min(percentile) bucketed at 0.08 / 0.20.  A "
                "range can only narrow when an observation is removed, so "
                "deleting evidence promoted a row (#833).  "
                "sourceRankPercentileSpread is still published as a diagnostic "
                "and still drives hasSourceDisagreement; it no longer decides "
                "confidence"
            ),
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
        # C1-U5: the contract states its own deprecations, machine-readably.
        #
        # ``CONTRACT_VERSION`` deliberately does NOT bump here: this change is
        # ADDITIVE — every legacy key still carries its exact former value —
        # and a version bump for an additive change trains consumers to ignore
        # version bumps. It bumps when the aliases are REMOVED, which is the
        # breaking half.
        #
        # This block is what a removal is checked against, and what
        # ``tests/api/test_confidence_rename_aliases.py`` pins in three
        # directions at once: declaring an alias that is not emitted, emitting
        # one that is not declared, and either drifting from the frozen literal
        # all fail. An undeclared alias is how a "temporary" dual-write becomes
        # permanent.
        "deprecations": DEPRECATED_FIELD_ALIASES,
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
        # C1-ID-01: which owner decided this build's source-CSV joins.  The
        # scraper site's twin artifact is data/scrape_state/identity_dual_read.json.
        "identityJoin": _LAST_CONTRACT_JOIN_SUMMARY,
        "hillCurves": _build_hill_curves_block(),
        # Lane 8: every declared bridge's state, which contributed to the
        # shared-market ladder, and the per-source withheld-vote count.  A
        # bridge that is PENDING / UNAVAILABLE / STALE is named here rather
        # than silently absent from the board it did not translate.
        "crossPositionBridges": _LAST_CROSS_POSITION_BRIDGE_SUMMARY,
    }
    # Drop internal-only provenance markers before materializing the
    # contract so they don't leak into the public payload.
    for row in players_array:
        row.pop("_positionFromSleeperOnly", None)
    stamp_optimal_lineups(contract_payload)
    return contract_payload


def roster_pool_key(teams: list[Any], index: int, team: Any) -> str:
    """UNIQUE identity for one team's roster pool, shared by every consumer.

    ``ownerId`` alone is not an identity.  ``Dynasty Scraper.py`` writes
    ``str(owner_id) if owner_id else ""`` and ``sleeper_overlay`` writes
    ``str(r.get("owner_id") or "")``, so Sleeper's ``owner_id: null`` — an
    unclaimed or orphaned roster, which the scraper's own comment anticipates —
    arrives as ``""`` for EVERY such team.  Keying a dict on that silently
    collapses them, and the survivor's roster is then published as the others'
    ``optimalLineup`` with ``available: true``.  A chimera presented as fact is
    worse than a refusal; ``src/api/gameplan.py`` already excludes an empty
    ownerId rather than merging on it.

    So: the ownerId is the key only when it is non-empty AND unambiguous across
    this team list.  Otherwise the key is positional, which is unique by
    construction.  The function is PURE in ``(teams, index, team)``, which is
    what lets the builder and every consumer derive the same key from the same
    list without threading state — and the index must be taken with
    ``enumerate(teams)`` BEFORE any ``isinstance`` skip, or the two desync on a
    malformed entry.
    """
    if isinstance(team, dict):
        owner_id = str(team.get("ownerId") or "").strip()
        if owner_id:
            same = sum(
                1
                for other in teams
                if isinstance(other, dict) and str(other.get("ownerId") or "").strip() == owner_id
            )
            if same == 1:
                return owner_id
    return f"__roster_{index}"


def contract_slot_eligibility(contract: Mapping[str, Any] | None) -> dict[str, tuple[str, ...]]:
    """This contract's league's CONFIGURED flex eligibility, or ``{}``.

    The PLUMBING half — contract → registry → the rule.  The rule itself
    is ``lineup.configured_slot_eligibility``, which is the slot-rules
    owner; this only knows how to find the settings.

    Separate from :func:`contract_roster_pools` rather than bolted onto
    its return, because that tuple has twelve unpack sites and widening
    it would churn every one of them to thread a value most do not want.
    Cheap to call: the registry read is cached.

    ``{}`` means "not configured", so the DECLARED defaults apply.  Both
    live leagues currently configure exactly the defaults, which is why
    threading this is a measured no-op today — and why it must be
    threaded anyway, since the day one of them narrows a flex, every
    surface that skipped it seats a player the league does not allow.
    """
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_league_roster_settings,
        )

        settings = get_league_roster_settings(
            str(((contract or {}).get("meta") or {}).get("leagueKey") or "") or None
        )
    except Exception:  # noqa: BLE001 — the registry is optional here
        return {}
    return lineup_owner.configured_slot_eligibility(settings)


def contract_roster_pools(
    contract: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, list[Any]], list[str], str | None]:
    """THE contract → per-team ``RosterPlayer`` pool builder.

    Returns ``({rosterPoolKey: pool}, slots, slot_source)`` — see
    :func:`roster_pool_key` for why that key is not simply ``ownerId``.

    Extracted from :func:`stamp_optimal_lineups`, which was its only
    caller and is now one of two — the other being roster intelligence.
    One builder means the lineup stamp and the roster chain cannot
    disagree about who is on a roster or what a player is worth.

    **Full membership, canonical value, unpriced preserved.**
    Membership is ``sleeper.teams[].players`` — every rostered player,
    not a filtered subset — and the value is ``rankDerivedValue``, the
    canonical 1-9999 dynasty board.  A rostered player the board did
    not price gets ``ros_value=None``, so the solver excludes them and
    reports them in ``unpriced_ids`` rather than seating a real player
    who merely looks worthless.

    That combination is why this is the right source for roster
    intelligence and the ROS team-strength snapshot is not.  That
    snapshot carries ``rosValue`` — "a normalized log-rank index on
    0-100, not points, and not projection-aware"
    (``src/ros/aggregate.py``) — a REST-OF-SEASON PRODUCTION quantity,
    while ``MASTER_PRODUCT_PLAN`` §4.1 says Team Strength "is not Power
    Ranking, Playoff Odds, or ROS production".  It also COERCES every
    unmatched row to ``ros_value=0.0`` before writing
    (``ros/team_strength.py``), so unpriced roster membership arrives
    indistinguishable from a real zero.  (Corrected 2026-08-19: this
    said the writer DROPPED those rows.  It does not — it appends them
    at 0.0, and its own comment names that as a deliberate
    missing-is-zero boundary.  The consequence for a consumer is the
    same, but a coercion and a deletion need different repairs, so the
    description matters.)  Two separate defects, one source; the
    contract has neither.

    ``rows`` supplies the value source explicitly for the same reason
    :func:`stamp_optimal_lineups` takes it: some payload views strip
    ``playersArray``, and reading a reduced view would price every
    player as UNKNOWN.
    """
    sleeper = contract.get("sleeper")
    if not isinstance(sleeper, dict):
        return {}, [], None
    teams = sleeper.get("teams")
    if not isinstance(teams, list) or not teams:
        return {}, [], None

    # THE truth ladder, not just its first rung: live host
    # ``rosterPositions`` → registry ``starters`` → refuse.  Reading only
    # the first rung made the second unreachable from the ONLY producer
    # of the lineup stamp, so ``slotSource: "registry_starters"`` was a
    # state the server had no code path to emit while the frontend
    # rendered a message for it — and a partial Sleeper fetch (lineup
    # endpoint times out, rosters succeed) would have refused a lineup
    # the registry could answer.
    registry_settings: dict[str, Any] | None = None
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_league_roster_settings,
        )

        registry_settings = get_league_roster_settings(
            str((contract.get("meta") or {}).get("leagueKey") or "") or None
        )
    except Exception:  # noqa: BLE001 — the registry is optional here
        registry_settings = None
    slots, slot_source = lineup_owner.resolve_starter_slots(
        roster_positions=sleeper.get("rosterPositions"),
        roster_settings=registry_settings,
    )

    positions = sleeper.get("positions") if isinstance(sleeper.get("positions"), dict) else {}
    eligibility = (
        sleeper.get("fantasyPositions") if isinstance(sleeper.get("fantasyPositions"), dict) else {}
    )
    value_by_name: dict[str, float | None] = {}
    for row in (rows if rows is not None else contract.get("playersArray")) or []:
        if row.get("assetClass") == "pick":
            continue
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                value_by_name.setdefault(str(key), row.get("rankDerivedValue"))

    pools: dict[str, list[Any]] = {}
    for index, team in enumerate(teams):
        if not isinstance(team, dict):
            continue
        pool: list[Any] = []
        for name in team.get("players") or []:
            key = str(name)
            raw = value_by_name.get(key)
            pool.append(
                lineup_owner.RosterPlayer(
                    player_id=key,
                    canonical_name=key,
                    # ``lineup_position`` is the ONE vocabulary a slot is
                    # named in — the frontend's ``lineupPosition`` twin.
                    position=lineup_owner.lineup_position(str(positions.get(key) or "")),
                    # Unpriced stays unpriced.  A player the board
                    # declined to price must not win a starting slot over
                    # one it did.
                    ros_value=None if raw is None else float(raw),
                    fantasy_positions=tuple(
                        lineup_owner.lineup_position(str(fp))
                        for fp in (eligibility.get(key) or ())
                        if str(fp).strip()
                    ),
                )
            )
        pools[roster_pool_key(teams, index, team)] = pool
    return pools, list(slots), slot_source


def stamp_optimal_lineups(
    contract: dict[str, Any],
    *,
    rows: list[dict[str, Any]] | None = None,
) -> None:
    """Stamp each team's optimal starting lineup onto ``sleeper.teams``.

    **The server assigns; the client renders** (C2-U1).  This is the
    same posture ``canonicalConsensusRank`` already establishes for
    ranks, and for the same reason: ``frontend/lib/starter-slots.js``
    was an independent two-pass greedy that reproduced Sleeper's own
    awarded lineup on 5 of 10 real team-weeks.  Correct eligibility data
    would not have fixed it — 16.13 of its 50.14 missing points were the
    ALGORITHM — so the repair is to stop computing the answer in two
    places, not to ship better inputs to the wrong one.

    League-scoped by construction: it hangs off ``sleeper.teams``, which
    ``LEAGUE_SPECIFIC_SLEEPER_FIELDS`` already governs, so a shared-
    rankings response with ``sleeper: null`` carries no lineup either.

    Degrades, never raises.  A team we cannot solve gets
    ``available: false`` with a reason, because "we do not know this
    league's lineup" and "this team starts nobody" must not render the
    same.

    **Call this again after anything replaces ``sleeper.teams``.**
    ``/api/data`` splices a live Sleeper overlay over the baked block
    (``server.py``), and the overlay rebuilds ``teams`` from scratch —
    so the stamp taken at build time is discarded on the normal serving
    path unless it is re-taken.  Re-solving rather than copying is the
    correct repair, and not merely the convenient one: the overlay's
    rosters are FRESHER, so a copied lineup could start a player who was
    dropped ten minutes ago.

    ``rows`` supplies the value source explicitly, because some payload
    views strip ``playersArray`` (``server.py`` pops it for the runtime
    view) and reading a reduced view would price every player as
    UNKNOWN.  Values are scoring-profile scoped and identical between
    the baked contract and any view of it, so passing the baked rows is
    correct as well as safe.

    **Never mutates the team dicts it is given.**  It writes a new list
    of shallow copies, because the overlay's teams come out of a shared
    15-minute cache and stamping them in place would leak one league's
    lineup into every later request that hit the same entry.
    """
    sleeper = contract.get("sleeper")
    if not isinstance(sleeper, dict):
        return
    teams = sleeper.get("teams")
    if not isinstance(teams, list) or not teams:
        return

    # ONE pool builder, shared with roster intelligence — see
    # :func:`contract_roster_pools`.  The slot truth ladder, the
    # position/eligibility vocabulary and the unpriced-stays-unpriced
    # rule all live there, so this stamp and the roster chain cannot
    # drift apart.
    pools, slots, slot_source = contract_roster_pools(contract, rows=rows)
    # The league's OWN flex rules, not the declared defaults.  A no-op on
    # both live leagues today (they configure exactly the defaults) and
    # not a no-op the day either narrows one.
    eligibility = contract_slot_eligibility(contract) or None

    stamped: list[Any] = []
    for index, original in enumerate(teams):
        if not isinstance(original, dict):
            stamped.append(original)
            continue
        # Copy-on-write: see the docstring.  The overlay's teams are
        # shared cache entries.
        team = dict(original)
        stamped.append(team)
        if not slots:
            team["optimalLineup"] = {
                "available": False,
                "reason": "no_starter_slots",
                "slotSource": None,
            }
            continue
        pool = pools.get(roster_pool_key(teams, index, original), [])
        try:
            solved = lineup_owner.assign_lineup(pool, slots, slot_eligibility=eligibility)
        except Exception:  # noqa: BLE001 — an optional stamp must not fail a build
            team["optimalLineup"] = {
                "available": False,
                "reason": "solver_error",
                "slotSource": slot_source,
            }
            continue
        team["optimalLineup"] = {
            "available": True,
            "slotSource": slot_source,
            "slots": list(solved.slots),
            "assignments": [
                {"slotIndex": i, "slot": solved.slots[i], "player": p.player_id}
                for i, p in sorted(solved.assignments.items())
            ],
            "starters": sorted(solved.starter_ids),
            "bench": sorted(solved.bench_ids(pool)),
            # Neither started nor benched: a third state, because folding
            # "we have no read on this player" into the bench is the same
            # missing-is-zero error one layer up.
            "unpriced": sorted(solved.unpriced_ids),
            "unfilledSlots": solved.unfilled_slots,
        }

    sleeper["teams"] = stamped


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
    # Override-sensitive for the same reason the two fields above are:
    # a standing is a function of the board, and re-weighting sources
    # re-orders it.  Omitting it would merge an overridden rank and
    # value onto the DEFAULT board's percentile — a row disagreeing with
    # itself, which is the defect class B9 closes.
    "canonicalPercentile",
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
    # Override-sensitive because disabling a source removes a family
    # (and re-weighting to 0 removes it entirely).  Absent from this
    # list until B11 despite landing with B10-T3b — a delta merge left
    # the DEFAULT board's independence counts sitting next to an
    # overridden rank, which is the same self-disagreement
    # ``canonicalPercentile`` was added here to prevent.
    "effectiveSourceCount",
    "independentSourceCount",
    "confidenceBucket",
    "confidenceLabel",
    # The gate's reasoning travels with its verdict.  A bucket without
    # its axes is the "score = 0.7134" the B11 ruling rejects, and a
    # delta that refreshed the bucket while leaving the axes behind
    # would publish an explanation of a board the row is no longer on.
    "confidenceAxes",
    "confidenceReasons",
    "marketGapDirection",
    "marketGapMagnitude",
    "marketGapValueRatio",
    "anomalyFlags",
    "canonicalTierId",
    "marketConfidence",
    "marketBreadthAgreementIndex",
    "marketBreadthScore",
    "marketAgreementScore",
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
    # C1-U6: which evidence class produced the pick's value.  Override-
    # sensitive because toggling a source can flip a row between a
    # direct blend and a derivation (or to honestly unavailable), and a
    # stale provenance block would describe a board the row is no
    # longer on.
    "pickValueProvenance",
)


def build_rankings_delta_payload(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
    tep_native_multiplier: float | None = None,
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

    # NO league-adjusted composition.  This used to multiply per-player
    # factors into ``rankDerivedValue`` here so the endpoint could serve
    # a board that was both re-weighted and league-adjusted.  #822
    # rejected that methodology for promotion to canonical and ruled it
    # may not own a canonical field; B9a closed this last path, where the
    # ±25% bound sat on the FACTOR and never on the PRODUCT, so canonical
    # values left their declared 1-9999 range (measured: 10,160 on the
    # real factor set, 12,471 at the cap).  See
    # ``tests/api/test_canonical_value_scale_contract.py``.

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


#: Contract-health errors whose CAUSE is an external source, not this
#: repository's code.  The distinction is not cosmetic — it decides which
#: CI lane may be made red by the condition.
#:
#: WHY THIS EXISTS.  On 2026-08-16 a single KTC scrape timed out (300 s
#: against a 39-run baseline of ~18.8 s).  ``validate_api_data_contract``
#: correctly returned ``ok: False`` on ``partial_run_critical:KTC``, and a
#: deterministic unit test that asserted ``ok is True`` as a *precondition*
#: therefore failed — turning a provider timeout into a red hard gate on
#: every open pull request, including ones that touched no source code.
#: The signal was right; the consumer could not tell the two kinds of
#: failure apart because the report did not distinguish them.
#:
#: THE BOUNDARY.  An error is source-health iff it can flip purely because
#: an upstream provider returned less data than usual, with this
#: repository's code byte-identical.  Everything else — schema shape, rank
#: invariants, the 1..9999 scale, blend-hull integrity, the pick
#: completeness census — is a statement about OUR code given whatever
#: payload arrived, and stays in the deterministic lane.
#:
#: Matched as prefixes because these error strings carry the offending
#: source key / count after a colon.
_SOURCE_HEALTH_ERROR_KINDS: tuple[str, ...] = (
    # The scraper itself reported a failed/timed-out critical source.
    "partial_run_critical:",
    # A registered source contributed zero non-zero values to the board.
    "source_missing:",
    # Fewer pick rows than the floor: the pick markets did not deliver.
    "pick_count_below_floor:",
    "pickAnchors missing from payload",
    "pickAnchors is empty",
    # The IDP pool collapsed — an availability statement about the IDP
    # markets, not a claim about our aggregation code.
    "implausibly small IDP pool in playersArray",
)


def _is_source_health_error(message: str) -> bool:
    """True when ``message`` is caused by upstream data availability.

    NOT ``pick_completeness_census:…:missing_or_unpriced``, and that is
    deliberate — ``tests/api/test_contract_health_lanes.py::TestTheTaxonomyItself``
    parametrizes it as a statement about OUR code.  Audit F-30 moved it here and
    was wrong to: the census asserts that our derivation prices every pick
    through the horizon given whatever anchors arrived, so an unpriced pick is a
    gap in the derivation, not a vendor's absence.  See the F-30 entry.
    """
    text = str(message)
    return any(text.startswith(kind) for kind in _SOURCE_HEALTH_ERROR_KINDS)


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
            "sourceHealthErrors": [],
            "structuralErrors": ["payload is not an object"],
            "sourceHealthOk": True,
            "structurallyOk": False,
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

    # ── Blend integrity: a hard error, and scanned over the WHOLE array ──
    # An out-of-hull value is structurally impossible under correct
    # operation, so a board carrying one is not a board to publish — this
    # is what makes ``scripts/validate_api_contract.py`` (the "API data
    # contract check" CI step) exit non-zero, and what stamps
    # ``contractHealth.ok = False`` on the served payload.
    #
    # Deliberately an ERROR rather than a warning or the soft ``degraded``
    # flag: the CI gate keys on ``ok`` and ignores warnings entirely, so
    # anything softer would be a note nobody acts on.
    #
    # And deliberately NOT bounded by the ``[:1000]`` slice the loop above
    # uses. That cap is a cost control for per-row shape checks on a
    # ~1,094-row board, but the corridor this replaced did its work at
    # ranks 691-740 and the board runs deeper than the cap — a prefix scan
    # would miss violations exactly where they are most likely.
    integrity_violations = [
        str(r.get("displayName") or r.get("canonicalName") or f"index {i}")
        for i, r in enumerate(players_array)
        if isinstance(r, dict) and isinstance(r.get("blendIntegrityViolation"), dict)
    ]
    if integrity_violations:
        errors.append(
            f"blend_integrity_violation:{len(integrity_violations)} row(s) hold a value "
            f"outside the range of their own source contributions "
            f"({', '.join(integrity_violations[:6])}"
            f"{', …' if len(integrity_violations) > 6 else ''})"
        )

    # ── Scale contract (B9a) ──
    #
    # ``methodology.formula`` PUBLISHES ``scaleMin: 1`` / ``scaleMax: 9999``,
    # and the expression it publishes clamps to that range — but nothing
    # verified the board honoured it.  9,999 is the Hill ASYMPTOTE, so a
    # canonical value above it is not an unusually good asset; it is a
    # number the curve that defines the scale cannot produce.
    #
    # It was reachable.  ``POST /api/rankings/overrides?view=delta`` with
    # ``valuation_mode: "leagueAdjusted"`` multiplied a per-position factor
    # into ``rankDerivedValue`` with the ±25% bound on the FACTOR and never
    # on the PRODUCT — 10,160 on the real factor set, 12,471 at the cap.
    # That path is gone; this is what makes its return visible instead of
    # silent, whatever future code introduces it.
    #
    # An ERROR, not a warning, for the same reason blend integrity is one:
    # ``scripts/validate_api_contract.py`` gates on ``ok`` and ignores
    # warnings.  Whole array, not the ``[:1000]`` prefix the shape checks
    # use — the top of the board is exactly where a ceiling breach lands.
    # The ALIASES are checked too: ``values.*`` are exact copies of the
    # canonical value, so an alias out of range is the same defect wearing
    # a different field name.
    out_of_scale: list[str] = []
    for i, row in enumerate(players_array):
        if not isinstance(row, dict):
            continue
        label = str(row.get("displayName") or row.get("canonicalName") or f"index {i}")
        candidates = [("rankDerivedValue", row.get("rankDerivedValue"))]
        row_values = row.get("values")
        if isinstance(row_values, dict):
            candidates.extend(
                (f"values.{k}", row_values.get(k))
                for k in ("overall", "finalAdjusted", "displayValue")
            )
        for field, value in candidates:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not (_CANONICAL_VALUE_MIN <= value <= _CANONICAL_VALUE_MAX):
                out_of_scale.append(f"{label}.{field}={value}")
    if out_of_scale:
        errors.append(
            f"canonical_value_out_of_scale:{len(out_of_scale)} value(s) outside "
            f"{_CANONICAL_VALUE_MIN}..{_CANONICAL_VALUE_MAX} "
            f"({', '.join(out_of_scale[:6])}"
            f"{', …' if len(out_of_scale) > 6 else ''})"
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
        # "Is it GONE?" and "is it THIN?" are different questions, and only the
        # second needs a calibrated number.  The population for the first is the
        # REGISTRY — every source we are entitled to expect a vote from — union
        # the keys that declare a floor, so ``ktc`` keeps its guard: it carries
        # a floor and the KTC pick market (60 pick rows ``ktcSfTep`` does not
        # cover) while not being a blend voter.
        #
        # Driving the zero check off ``row_floors`` alone made absence of a
        # THRESHOLD mean absence of a CHECK.  Measured 2026-08-18 (audit F-15),
        # with F-10's ``ktcSfTep`` floor already in place: 8 of 21 registered
        # voters could fall to zero rows with ``ok=True`` and an empty
        # source-health lane — fantasyProsSf (474 live rows), pfkDynasty (472),
        # fantasyNavigatorSf (454), otcffbSf (447), fantasyCalc (388),
        # dlfRookieSf (112), flockFantasySfRookies (76), dlfRookieIdp (29).
        # Three of those omissions carried an explicit "floors intentionally NOT
        # set yet … add once live canonical match counts are observed" note from
        # 2026-07-25; the counts now exist and the entries were never added.
        #
        # Zero is not a legitimate state for a registered source: across the
        # tracked git history of all eight CSVs (up to 60 commits each) none has
        # ever been empty, minimums ranging 29-758 rows.  Should one ever
        # acquire a legitimate empty state it gets an explicit reasoned
        # declaration, never a silent omission.
        watched_keys = set(get_ranking_source_keys()) | set(row_floors)
        source_nonzero_counts: dict[str, int] = {k: 0 for k in watched_keys}
        for row in players_array:
            if not isinstance(row, dict):
                continue
            sites_map = row.get("canonicalSiteValues")
            if not isinstance(sites_map, dict):
                continue
            for src_key in watched_keys:
                val = _to_int_or_none(sites_map.get(src_key))
                if val is not None and val > 0:
                    source_nonzero_counts[src_key] += 1

        # ``sorted`` so the emitted order is a property of the population rather
        # than of a config file's key order.
        for src_key in sorted(watched_keys):
            count = source_nonzero_counts.get(src_key, 0)
            threshold = row_floors.get(src_key)
            if count == 0:
                errors.append(f"source_missing:{src_key}")
                any_source_missing = True
            elif threshold is not None and count < threshold:
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

        # ── C1-PICK-01 completeness census (C1-U6) ──────────────────
        # Every valid pick through the horizon must publish a finite
        # canonical value with provenance: all tier + generic rows for
        # every future year on the board (rounds 1-6), no pick anywhere
        # at 0 or NaN, and no zero-as-missing.  An ERROR, not a warning
        # — the CI gate keys on ``ok`` and ignores warnings (same
        # posture as the blend-integrity scan).  Alias-suppressed
        # current-year tiers are the one deliberate valueless state and
        # must say so via provenance.
        # C1-U5: a priced row must say what decided its confidence.
        #
        # Structural, not advisory. The defect this closes was a pass that
        # priced 24 rows and wrote no confidence field, so they shipped
        # wearing the row constructor's "None — unranked" placeholder — a
        # label asserting the row was unranked and therefore unconfident,
        # when the truth was that nothing had ever assessed it. Requiring a
        # basis on every priced row makes that state unrepresentable rather
        # than merely discouraged: the next pass that prices a row without
        # saying why fails the build instead of shipping quietly.
        #
        # Scanned over the WHOLE array, not a prefix — the board runs
        # deeper than the per-row shape checks' 1000-row cap, and the
        # measured population sat at ranks past it.
        for row in players_array:
            if not isinstance(row, dict):
                continue
            v = row.get("rankDerivedValue")
            if not (isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) > 0):
                continue
            basis = row.get("confidenceBasis")
            nm = str(row.get("canonicalName") or row.get("displayName") or "?")
            if not basis:
                errors.append(f"confidence_basis_missing:{nm}")
            elif basis not in CONFIDENCE_BASES:
                errors.append(f"confidence_basis_unknown:{nm}:{basis}")
            elif basis in ("unpriced", "no_evidence"):
                # A priced row claiming it has no value, or that nothing
                # looked at it, is the exact contradiction this guards.
                errors.append(f"confidence_basis_contradicts_value:{nm}:{basis}")

        pick_rows_by_name: dict[str, dict[str, Any]] = {}
        tier_years: set[int] = set()
        for row in players_array:
            if not isinstance(row, dict) or row.get("assetClass") != "pick":
                continue
            nm = str(row.get("canonicalName") or "")
            pick_rows_by_name[nm] = row
            v = row.get("rankDerivedValue")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if not math.isfinite(float(v)):
                    errors.append(f"pick_value_not_finite:{nm}")
                elif float(v) == 0:
                    errors.append(f"pick_value_zero_as_missing:{nm}")
            parsed_tier = _parse_pick_tier(nm)
            if parsed_tier is not None:
                tier_years.add(parsed_tier[0])
        if tier_years:
            # Anchor on the contract's own stamped draft year — never on
            # min(tier_years), where one stale past-year tier row would
            # drag the anchor back and fail the census over the anchor
            # year's deliberately alias-suppressed tiers (final-review
            # hardening).  Fallback for payloads without the stamp.
            stamped_year = payload.get("currentDraftYear")
            census_current = (
                int(stamped_year)
                if isinstance(stamped_year, (int, float)) and stamped_year
                else min(tier_years)
            )
            # The horizon range is UNCONDITIONAL (final-review
            # hardening): a scrape that lost the entire future horizon
            # (no future tier years at all, so the injection had no
            # template) must fail THIS census, not just the coarse
            # pick-count floor — wholesale absence is the exact
            # C1-PICK-01 regression class the gate exists for.
            try:
                census_horizon = max(0, int(_load_pick_year_discount().get("horizonYears") or 3))
            except (TypeError, ValueError):
                census_horizon = 3
            for census_year in range(census_current + 1, census_current + census_horizon + 1):
                for census_round in range(1, 7):
                    names = [
                        f"{census_year} {t} {_round_suffix(census_round)}"
                        for t in ("Early", "Mid", "Late")
                    ] + [f"{census_year} Round {census_round}"]
                    for nm in names:
                        row = pick_rows_by_name.get(nm)
                        v = row.get("rankDerivedValue") if isinstance(row, dict) else None
                        ok_value = (
                            isinstance(v, (int, float))
                            and not isinstance(v, bool)
                            and math.isfinite(float(v))
                            and float(v) > 0
                        )
                        if row is None or not ok_value:
                            errors.append(f"pick_completeness_census:{nm}:missing_or_unpriced")
                        elif not isinstance(row.get("pickValueProvenance"), dict):
                            errors.append(f"pick_completeness_census:{nm}:no_provenance")

                    # F-1: an EARLIER pick must be worth MORE than a later
                    # one.  The census above proves every cell is finite,
                    # priced and provenanced — it said nothing about ORDER,
                    # and for six of eighteen cells the order was wrong:
                    # ``2029 Mid 1st`` published 3676 against ``2029 Early
                    # 1st`` at 3593, so the trade calculator booked a gain
                    # for downgrading and /rankings ranked the mid first
                    # ABOVE the early first.  A finite, provenanced,
                    # correctly-scaled, wrongly-ordered board passed every
                    # other check in this function.
                    tier_values = []
                    for tier_name in ("Early", "Mid", "Late"):
                        tier_row = pick_rows_by_name.get(
                            f"{census_year} {tier_name} {_round_suffix(census_round)}"
                        )
                        tv = (
                            tier_row.get("rankDerivedValue") if isinstance(tier_row, dict) else None
                        )
                        tier_values.append(
                            float(tv)
                            if isinstance(tv, (int, float))
                            and not isinstance(tv, bool)
                            and math.isfinite(float(tv))
                            else None
                        )
                    if all(v is not None for v in tier_values) and not (
                        tier_values[0] > tier_values[1] > tier_values[2]
                    ):
                        errors.append(
                            "pick_tier_ordering:"
                            f"{census_year}:r{census_round}:"
                            f"early={tier_values[0]:.0f},mid={tier_values[1]:.0f},"
                            f"late={tier_values[2]:.0f}"
                        )

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
    # We now promote critical partials to errors and leave allowlisted
    # partials (``TOLERABLE_PARTIAL_SOURCES``) as warnings.
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
                # Critical match: the run name resolves to a critical
                # primary source (exact, or ``<primary>_<qualifier>`` —
                # the scraper reports DLF as ``DLF_LocalCSV``; F-17).
                if critical_primary_for_run_source(src) is not None:
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
    source_health_errors = [e for e in errors if _is_source_health_error(e)]
    structural_errors = [e for e in errors if not _is_source_health_error(e)]
    return {
        "ok": ok,
        "status": status,
        "errors": errors[:200],
        "warnings": warnings[:200],
        "errorCount": len(errors),
        "warningCount": len(warnings),
        # ── Lane partition (stabilization 2026-08-16) ────────────────────
        # ``ok`` is unchanged and still means "every check passed"; these
        # two lists say WHICH KIND of check failed, so a consumer can ask
        # the question it actually has.  See ``_SOURCE_HEALTH_ERROR_KINDS``
        # for why the boundary sits where it does.
        "sourceHealthErrors": source_health_errors[:200],
        "structuralErrors": structural_errors[:200],
        "sourceHealthOk": not source_health_errors,
        "structurallyOk": not structural_errors,
        "checkedAt": utc_now_iso(),
        "contractVersion": str(payload.get("contractVersion") or CONTRACT_VERSION),
        "playerCount": len(players_array),
    }
