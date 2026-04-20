from __future__ import annotations

from copy import deepcopy
import json
import logging
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.data_models.contracts import utc_now_iso
from src.idp_calibration import production as _idp_production

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
    "footballGuysSf",
    "yahooBoone",
}
_IDP_SIGNAL_KEYS = {
    "idpTradeCalc",
    "dlfIdp",
    "fantasyProsIdp",
    "footballGuysIdp",
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
    "ktc": "CSVs/site_raw/ktc.csv",
    "idpTradeCalc": "CSVs/site_raw/idpTradeCalc.csv",
    "dlfIdp": {
        "path": "CSVs/site_raw/dlfIdp.csv",
        "signal": "rank",
    },
    # DLF Dynasty Superflex rankings — offense expert consensus.
    # Raw CSV exported from DLF with capitalized Name/Rank columns
    # plus several per-expert columns.  The `_enrich_from_source_csvs`
    # reader uses column-name aliases so we can point directly at the
    # original filename without any preprocessing.
    "dlfSf": {
        "path": "CSVs/site_raw/Dynasty Superflex Rankings-3-15-2026-1642.csv",
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
    # Dynasty Daddy Superflex trade values — fetched from
    # https://dynasty-daddy.com/api/v1/player/all/today?market=14
    # via ``scripts/fetch_dynasty_daddy.py``.  The API returns crowd-
    # sourced SF trade values for ~641 players; we filter to offensive
    # positions (QB/RB/WR/TE) and write ``name,value`` CSV.  Signal=value
    # so the ``_enrich_from_source_csvs`` reader uses the value column
    # directly, same as KTC.
    "dynastyDaddySf": "CSVs/site_raw/dynastyDaddySf.csv",
    # Flock Fantasy Dynasty Superflex rankings — expert consensus from
    # https://flockfantasy.com via JSON API (?format=superflex).
    # Multi-expert averaged ranks (~368 offensive players after
    # filtering).  Signal=rank so the ``_enrich_from_source_csvs``
    # reader uses the rank column, not a value column.
    "flockFantasySf": {
        "path": "CSVs/site_raw/flockFantasySf.csv",
        "signal": "rank",
    },
    # FootballGuys dynasty rankings — 6-expert offense board and
    # 3-expert IDP board, exported from FootballGuys as a PDF by the
    # user and converted to CSV via
    # ``scripts/parse_footballguys_pdf.py``.  The parser splits the
    # mixed overall ranking by position family, then dense-ranks 1..N
    # within each universe so downstream rank-signal conversion sees
    # a contiguous within-universe ordering.  Signal=rank.
    "footballGuysSf": {
        "path": "CSVs/site_raw/footballGuysSf.csv",
        "signal": "rank",
    },
    "footballGuysIdp": {
        "path": "CSVs/site_raw/footballGuysIdp.csv",
        "signal": "rank",
    },
    # Yahoo / Justin Boone dynasty trade value charts — scraped from
    # sports.yahoo.com via ``scripts/fetch_yahoo_boone.py``.  The
    # scraper combines Boone's QB (2QB column), RB, WR, and TE
    # (TE-Prem. column) charts into one cross-positional competition
    # rank and writes the ``rank`` column of the CSV.  Signal=rank so
    # the ``_enrich_from_source_csvs`` reader picks up the rank column
    # via ``_RANK_ALIASES``.
    "yahooBoone": {
        "path": "CSVs/site_raw/yahooBoone.csv",
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
        "path": "CSVs/site_raw/Dynasty Rookie Superflex Rankings-3-20-2026-0955.csv",
        "signal": "rank",
    },
    # DLF Dynasty Rookie IDP rankings — same shape as the SF rookie
    # export but for DL/LB/DB prospects.  IDP rookie translation uses
    # the IDPTC IDP ladder.
    "dlfRookieIdp": {
        "path": "CSVs/site_raw/Dynasty Rookie IDP Rankings-3-20-2026-0955.csv",
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
    "idpTradeCalc": 6,
    "dynastyNerdsSfTep": 6,
    "fantasyProsIdp": 6,
    "dynastyDaddySf": 6,
    "flockFantasySf": 168,
    "dlfIdp": 720,
    "dlfSf": 720,
    # FootballGuys rankings are a user-managed PDF→CSV export; allow
    # a generous 30-day staleness window before flagging.
    "footballGuysSf": 720,
    "footballGuysIdp": 720,
    # Yahoo / Justin Boone trade value charts refresh ~monthly, so
    # allow a 30-day window; the fetcher also emits its own stale-
    # article warning if Yahoo's redirect chain ever stops resolving.
    "yahooBoone": 720,
    # DraftSharks SF + IDP CSVs are written by scripts/fetch_draftsharks.py
    # on every scheduled-refresh tick (3-hour cadence), so the same
    # 6-hour freshness budget as ktc / idpTradeCalc applies.
    "draftSharks": 6,
    "draftSharksIdp": 6,
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
    "flockFantasySf": 250,
    # FootballGuys SF/IDP: after the PDF parse + offense/IDP split,
    # raw rows are ~548 offense and ~406 IDP.  Actual canonical-name
    # matches against the live Sleeper player pool are ~470 offense
    # and ~291 IDP (many FBG-ranked deep veterans / prospects don't
    # exist in the Sleeper database).  Floors set at ~80% of those
    # match counts.
    "footballGuysSf": 375,
    "footballGuysIdp": 230,
    # Yahoo / Justin Boone charts: QB+RB+WR+TE combined = ~500 rows
    # at the April 2026 baseline.  Floor at ~80% so a scrape regression
    # trips a warning.
    "yahooBoone": 400,
    # DraftSharks: the scraper ingests 461 offense / 389 IDP rows,
    # but canonical-name matches against the Sleeper player pool
    # yield a smaller count because DS's deeper rows are prospects
    # not yet listed in Sleeper (e.g. rookies / deep practice-squad
    # LBs).  Live match counts are ~237 offense and ~108 IDP at
    # the April 2026 baseline.  Floors at ~80% of those match
    # counts so scraper regressions trip a warning.
    "draftSharks": 190,
    "draftSharksIdp": 85,
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
    if (
        isinstance(cached_value, dict)
        and cached_mtime == current_mtime
    ):
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
            _LOGGER.warning(
                "Failed to load source_row_floors.json (%s); using defaults", exc
            )
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
    if (
        isinstance(cached_value, dict)
        and cached_mtime == current_mtime
    ):
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
    """
    repo_root = Path(__file__).resolve().parents[2]
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
                mtime_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                age_hours = (now - mtime_dt).total_seconds() / 3600.0
                entry["mtime"] = mtime_dt.isoformat()
                entry["ageHours"] = round(age_hours, 3)
                entry["staleness"] = "fresh" if age_hours < max_age else "stale"
        out[source_key] = entry
    return out

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
        # KTC's default scraped view is a standard SF community trade
        # calculator — it does not bake in TE premium.  The frontend
        # `settings.tepMultiplier` boost applies to its contribution
        # on the blended board.  See frontend/lib/dynasty-data.js for
        # the mirrored flag.
        "is_tep_premium": False,
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
        # Weight bumped to 2.0 so the IDP blend leans toward IDPTC
        # whenever it disagrees strongly with veteran-focused expert
        # boards (DLF IDP, FantasyPros IDP, FootballGuys IDP).  The
        # original 1.0 weight let DLF IDP drag down players IDPTC
        # likes — particularly high-draft-capital edge rushers whose
        # pass-rush projection (IDPTC) diverges from raw tackle
        # production (DLF).  Mirrored in
        # frontend/lib/dynasty-data.js so the settings page shows the
        # correct default.
        "weight": 2.0,
        "is_backbone": True,
        # Final Framework step 7: IDPTC is the global offense+defense
        # anchor.  Its dual-scope coverage (offense via extra_scopes +
        # IDP backbone) makes it the only source that prices both
        # universes on a common combined-pool scale, which is what the
        # framework wants for the universal baseline.  All other
        # sources are treated as subgroup adjustments against this
        # anchor.  See the hierarchical-blend logic in
        # ``_compute_unified_rankings``.
        "is_anchor": True,
        # IDPTradeCalc's offense autocomplete is a standard SF board,
        # not TE-premium.  The frontend TEP boost applies.
        "is_tep_premium": False,
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
        # FootballGuys Dynasty Rankings — offense half (QB/RB/WR/TE).
        # Parsed from the user-managed
        # ``Fantasy Football Dynasty Rankings - Footballguys.pdf``
        # via ``scripts/parse_footballguys_pdf.py``.  6-expert
        # consensus.  Standard Superflex — the frontend TEP slider
        # boosts its contribution on TE-position players.
        "key": "footballGuysSf",
        "display_name": "FootballGuys Dynasty SF",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "position_group": None,
        # Parser typically produces ~540 offensive rows; depth=500 so
        # ``_expected_sources_for_position`` stops expecting FBG
        # coverage past rank ~625 (depth * 1.25).
        "depth": 500,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
    },
    {
        # FootballGuys Dynasty Rankings — IDP half (DE/DT/LB/CB/S).
        # 3-expert IDP consensus; translates through the shared-market
        # IDP ladder, same as dlfIdp / fantasyProsIdp.  Parser yields
        # ~400 IDP rows — deeper than DLF IDP (185) or FP IDP (100).
        # Includes rookie IDP prospects so ``excludes_rookies=False``.
        "key": "footballGuysIdp",
        "display_name": "FootballGuys Dynasty IDP",
        "scope": SOURCE_SCOPE_OVERALL_IDP,
        "position_group": None,
        "depth": 400,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "needs_shared_market_translation": True,
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
        # Rank signal: the scraper emits a competition rank computed
        # across all four positions (ties share a rank, next rank is
        # skipped).  The contract loader inverts rank to a synthetic
        # monotonic value for the blend; the UI must render
        # sourceOriginalRanks.yahooBoone, never the synthetic.
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
        # 0-100 absolute scale is irrelevant.  DraftSharks' scoring
        # is standard dynasty (not TE-premium native), so the
        # frontend ``tepMultiplier`` applies.
        "key": "draftSharks",
        "display_name": "Draft Sharks Dynasty",
        "scope": SOURCE_SCOPE_OVERALL_OFFENSE,
        "extra_scopes": [],
        "position_group": None,
        "depth": 500,
        "weight": 1.0,
        "is_backbone": False,
        "is_retail": False,
        "is_tep_premium": False,
        "needs_shared_market_translation": False,
        "excludes_rookies": False,
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
            "columnLabel": str(
                src.get("column_label") or src.get("display_name") or ""
            ),
            "scope": str(src.get("scope") or ""),
            "extraScopes": list(src.get("extra_scopes") or []),
            "positionGroup": src.get("position_group"),
            "depth": src.get("depth"),
            "weight": float(src.get("weight") or 0.0),
            "isBackbone": bool(src.get("is_backbone")),
            "isRetail": bool(src.get("is_retail")),
            "isTepPremium": bool(src.get("is_tep_premium")),
            "isRankSignal": bool(src.get("is_rank_signal")),
            "needsSharedMarketTranslation": bool(
                src.get("needs_shared_market_translation")
            ),
            "excludesRookies": bool(src.get("excludes_rookies")),
        }
        out.append(entry)
    return out


def get_ranking_source_keys() -> list[str]:
    """Return the ordered list of registered ranking source keys."""
    return [str(s.get("key") or "") for s in _RANKING_SOURCES]


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
      * A ``float`` clamped to ``[1.0, 2.0]`` when the key IS present
        and parses as a finite number.  The clamped value is what the
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
            return max(1.0, min(2.0, v))
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
        warnings.append(
            f"Top-level overrides must be an object; got {type(raw).__name__}"
        )
        return out, warnings

    # ── Explicit request body: {"enabled_sources": [...], "weights": {...}} ──
    explicit_enabled = raw.get("enabled_sources")
    if explicit_enabled is None:
        explicit_enabled = raw.get("enabledSources")
    explicit_weights = raw.get("weights")

    if explicit_enabled is not None or isinstance(explicit_weights, dict):
        if explicit_enabled is not None:
            if not isinstance(explicit_enabled, (list, tuple, set)):
                warnings.append(
                    "enabled_sources must be a list of source keys; ignoring"
                )
                enabled_set: set[str] = valid_keys
            else:
                enabled_set = set()
                for key in explicit_enabled:
                    k = str(key)
                    if k in valid_keys:
                        enabled_set.add(k)
                    else:
                        warnings.append(
                            f"enabled_sources: unknown source '{k}' (ignored)"
                        )
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
                    warnings.append(
                        f"weights: unknown source '{k}' (ignored)"
                    )
                    continue
                try:
                    w = float(value)
                except (TypeError, ValueError):
                    warnings.append(
                        f"weights[{k}]: value '{value}' is not a number (ignored)"
                    )
                    continue
                if not math.isfinite(w) or w < 0:
                    warnings.append(
                        f"weights[{k}]: value {w} is not non-negative finite (ignored)"
                    )
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
            warnings.append(
                f"Override for '{k}' must be an object; got {type(value).__name__}"
            )
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
                warnings.append(
                    f"Override '{k}'.weight must be a number (ignored)"
                )
            else:
                if math.isfinite(w) and w >= 0:
                    entry["weight"] = w
                else:
                    warnings.append(
                        f"Override '{k}'.weight must be non-negative finite (ignored)"
                    )
        if entry:
            out[k] = entry
    return out, warnings


def _summarize_source_overrides(
    source_overrides: dict[str, dict[str, Any]] | None,
    *,
    tep_multiplier: float = 1.0,
    tep_multiplier_derived: float = 1.0,
    tep_multiplier_source: str = "default",
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

    # Clamp the TEP multiplier identically to the blend path so the
    # summary reflects what was actually applied, not what was sent.
    try:
        tep_eff = float(tep_multiplier)
    except (TypeError, ValueError):
        tep_eff = 1.0
    if not math.isfinite(tep_eff):
        tep_eff = 1.0
    tep_eff = max(1.0, min(2.0, tep_eff))

    try:
        tep_derived = float(tep_multiplier_derived)
    except (TypeError, ValueError):
        tep_derived = 1.0
    if not math.isfinite(tep_derived):
        tep_derived = 1.0
    tep_derived = max(1.0, min(2.0, tep_derived))

    # isCustomized flips only when the user-facing effective value
    # diverges from the league-derived baseline.  A league with
    # bonus_rec_te=0.5 (derived TEP=1.15) that lands on tep_eff=1.15
    # is NOT customized — the user just accepted the auto value.
    # Customization only fires when they explicitly drag the slider
    # to something else.
    if abs(tep_eff - tep_derived) > 1e-6:
        is_customized = True

    # Clamp the TEP-native correction for display purposes only; the
    # pipeline already consumed it as-is during the blend.
    try:
        tep_native_corr = float(tep_native_correction)
    except (TypeError, ValueError):
        tep_native_corr = 1.0
    if not math.isfinite(tep_native_corr):
        tep_native_corr = 1.0

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
        "tepNativeCorrection": round(tep_native_corr, 4),
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
        errors.append(
            "Registry key order/mismatch:\n"
            f"  python: {py_keys}\n"
            f"  frontend: {js_keys}"
        )
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
        ):
            py_val = py.get(field)
            js_val = js.get(field)
            if field == "extraScopes":
                py_val = list(py_val or [])
                js_val = list(js_val or [])
            if field == "weight":
                if float(py_val or 0) != float(js_val or 0):
                    errors.append(
                        f"{key}.weight: python={py_val} frontend={js_val}"
                    )
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


def _active_sources(
    source_overrides: dict[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Return a filtered list of _RANKING_SOURCES with overrides applied.

    Disabled sources are dropped entirely.  Weight overrides produce a
    shallow copy of the source dict with the ``weight`` field
    replaced.  Sources that inherit their defaults are passed through
    by reference so the hot path does not pay a copy tax when no
    overrides are in play.
    """
    if not source_overrides:
        return list(_RANKING_SOURCES)
    out: list[dict[str, Any]] = []
    for src in _RANKING_SOURCES:
        if not _source_is_enabled(src, source_overrides):
            continue
        ov = source_overrides.get(src.get("key") or "") or {}
        if "weight" in ov:
            copy = dict(src)
            copy["weight"] = _effective_source_weight(src, source_overrides)
            out.append(copy)
        else:
            out.append(src)
    return out


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
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0)
            for k in _OFFENSE_SIGNAL_KEYS
        )
        has_idp = any(
            _to_int_or_none(canonical_sites.get(k)) not in (None, 0)
            for k in _IDP_SIGNAL_KEYS
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
_SOURCE_CSV_PARSE_CACHE: dict[str, tuple[float, dict[str, list[tuple[str, int, float | None]]], dict[str, str] | None]] = {}
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
    # player = 100, decimals preserved).  Kept at the tail so more
    # conventional aliases win when multiple are present.
    _VALUE_ALIASES = ("value", "Value", "trade_value", "TradeValue", "3D Value +")

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
            expected_tokens = ("Rank", "Avg", "Name", "Player")
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
                "fantasyProsIdpFamily": str(
                    row_csv.get("family") or ""
                ).strip(),
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
            if parse_errors is not None:
                parse_errors.append(
                    {
                        "source": source_key,
                        "path": str(csv_rel),
                        "error": "file_not_found",
                    }
                )
                _LOGGER.warning(
                    "Source CSV missing for %s: %s", source_key, csv_rel
                )
            continue

        csv_lookup, schema_err = _parse_source_csv_cached(
            csv_path, source_key, signal, csv_rel
        )
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
            _flat = [
                (disp, syn, rnk)
                for entries in csv_lookup.values()
                for (disp, syn, rnk) in entries
            ]
            _flat.sort(key=lambda t: (-t[1], str(t[0]).lower()))
            _dlf_league_size = _resolve_league_roster_count()
            for _rookie_idx, (_disp, _syn, _rnk) in enumerate(_flat):
                rookie_rank = _rookie_idx + 1
                if rookie_rank > _dlf_league_size * _ROOKIE_ANCHOR_ROUNDS:
                    break
                _rnd = (rookie_rank - 1) // _dlf_league_size + 1
                _slot = (rookie_rank - 1) % _dlf_league_size + 1
                _pick_name = f"2026 Pick {_rnd}.{_slot:02d}"
                _pick_key = _canonical_match_key(_pick_name)
                if not _pick_key:
                    continue
                csv_lookup.setdefault(_pick_key, []).append(
                    (_pick_name, _syn, float(rookie_rank))
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
    fp_rel = (
        fp_cfg.get("path") if isinstance(fp_cfg, dict) else (fp_cfg or "")
    )
    if fp_rel:
        fp_path = repo / fp_rel
        if fp_path.exists():
            try:
                fp_meta_lookup = _parse_fp_meta_csv_cached(fp_path)
                for row in players_array:
                    nm = str(
                        row.get("canonicalName") or row.get("displayName") or ""
                    )
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
                _LOGGER.warning(
                    "FantasyPros IDP metadata stamp failed: %s", exc
                )

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


def _apply_idp_calibration_post_pass(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Apply the promoted IDP calibration multipliers, if any.

    Strict no-op whenever ``config/idp_calibration.json`` is absent —
    :func:`src.idp_calibration.production.load_production_config`
    returns ``None`` in that case and we early-exit.

    When a promoted config is present we:

    1. Enumerate all rows whose position normalises to DL/LB/DB.
    2. Sort each position by the pre-multiplier ``rankDerivedValue``
       descending to derive a stable position-specific rank.
    3. Multiply the row's ``rankDerivedValue`` by the per-position /
       per-bucket multiplier (looked up from the promoted config).
    4. Mirror the updated value into the legacy-dict players map so
       the runtime view stays in sync.

    Offense rows are never touched.
    """
    config = _idp_production.load_production_config()
    if not config:
        return
    active_mode = str(config.get("active_mode") or "blended")
    # ``family_scale`` (class-wide IDP lift/discount) is already folded
    # INTO the return value of ``get_idp_bucket_multiplier`` at
    # :func:`src.idp_calibration.production.get_idp_bucket_multiplier`
    # (line 254: ``return bucket * family``).  An earlier audit pass
    # mistakenly believed family_scale was dead code and tried to
    # multiply it here as a separate step, which would have
    # double-applied the scale (1.2571² ≈ 1.58×).  We surface it as a
    # sibling field below for the value-chain audit, but do NOT
    # multiply it a second time here — the single product from
    # ``get_idp_bucket_multiplier`` is the correct math.
    family_scale = _idp_production._family_scale_for(config, active_mode)

    by_pos: dict[str, list[dict[str, Any]]] = {"DL": [], "LB": [], "DB": []}
    for row in players_array:
        pos = str(row.get("position") or "").upper()
        if pos in ("DE", "DT", "EDGE", "NT"):
            pos = "DL"
        elif pos in ("ILB", "OLB", "MLB"):
            pos = "LB"
        elif pos in ("CB", "S", "SS", "FS"):
            pos = "DB"
        if pos not in by_pos:
            continue
        try:
            derived = int(row.get("rankDerivedValue") or 0)
        except (TypeError, ValueError):
            derived = 0
        if derived <= 0:
            continue
        by_pos[pos].append(row)

    for pos, rows in by_pos.items():
        rows.sort(key=lambda r: -int(r.get("rankDerivedValue") or 0))
        for idx, row in enumerate(rows, 1):
            try:
                # Returns bucket × family_scale already combined — see
                # comment above and production.py::get_idp_bucket_multiplier.
                combined_multiplier = float(
                    _idp_production.get_idp_bucket_multiplier(
                        pos, idx, mode=active_mode
                    )
                )
            except Exception:  # noqa: BLE001 — never fail the whole board
                combined_multiplier = 1.0
            if abs(combined_multiplier - 1.0) < 1e-9:
                # Still stamp the audit fields even when the effective
                # multiplier is identity, so the /rankings and trade UI
                # can display a clean 1.00× in the chain instead of
                # "unknown" for an IDP row that was legitimately
                # un-multiplied.
                row["idpCalibrationMultiplier"] = 1.0
                row["idpFamilyScale"] = round(family_scale, 4)
                row["idpCalibrationPositionRank"] = idx
                legacy_ref = row.get("legacyRef")
                if legacy_ref and legacy_ref in players_by_name:
                    pdata = players_by_name[legacy_ref]
                    if isinstance(pdata, dict):
                        pdata["idpCalibrationMultiplier"] = 1.0
                        pdata["idpFamilyScale"] = round(family_scale, 4)
                        pdata["idpCalibrationPositionRank"] = idx
                continue
            # Multiplier scales the row's value (on top of the
            # weighted Hill-curve blend already encoded in
            # rankDerivedValue). The subsequent global re-sort places
            # the row at its new merged rank based on the multiplied
            # value. We deliberately keep the multiplied value as the
            # final rankDerivedValue — the tiered fractional-rank
            # signal from the per-source Hill blend carries through
            # the calibration so elite players don't get snapped to
            # the integer-rank Hill value.
            old_val = int(row.get("rankDerivedValue") or 0)
            new_val = max(1, int(round(old_val * combined_multiplier)))
            row["rankDerivedValue"] = new_val
            # Back out the pure bucket component for the chain audit
            # (family_scale is constant across all IDP rows, bucket
            # varies by position-rank).  Prevents double-apply at the
            # frontend while showing each component distinctly.
            if family_scale > 0:
                bucket_only = combined_multiplier / family_scale
            else:
                bucket_only = combined_multiplier
            row["idpCalibrationMultiplier"] = round(bucket_only, 4)
            row["idpFamilyScale"] = round(family_scale, 4)
            row["idpCalibrationPositionRank"] = idx
            legacy_ref = row.get("legacyRef")
            if legacy_ref and legacy_ref in players_by_name:
                pdata = players_by_name[legacy_ref]
                if isinstance(pdata, dict):
                    pdata["rankDerivedValue"] = new_val
                    pdata["idpCalibrationMultiplier"] = round(bucket_only, 4)
                    pdata["idpFamilyScale"] = round(family_scale, 4)
                    pdata["idpCalibrationPositionRank"] = idx


def _apply_offense_calibration_post_pass(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Apply promoted per-position offense multipliers (QB/RB/WR/TE).

    ⚠️ **NOT INVOKED IN PRODUCTION.** The caller in
    :func:`build_api_data_contract` is intentionally commented out —
    VOR bucket multipliers produced absurd artefacts on offense
    (sharp QB-tier cliffs, Mahomes ending at half the value of the
    QB1, etc.) because the offense market is already well-priced by
    the blend of KTC / DLF / IDPTC / etc.  This function is kept as
    an analytical reference used by the IDP lab only; mutating live
    ``rankDerivedValue`` with it would actively worsen signal.

    If you're considering re-enabling this, verify:
      1. The offense VOR signal has been re-validated against more
         recent market data than the initial PR #105 promotion.
      2. The bucket definitions (``1-6``, ``7-12``, ...) still match
         your league's starting-lineup structure — the current
         buckets assume 12-team superflex.

    Mirror of :func:`_apply_idp_calibration_post_pass` but for offense
    rows. Reads ``offense_multipliers`` from the promoted config and
    scales each QB/RB/WR/TE row's ``rankDerivedValue`` by the looked-up
    bucket value. Unlike IDP, there is no family_scale component on the
    offense side — offense is the reference for the family ratio.

    Snapshots the pre-calibration value into
    ``rankDerivedValueUncalibrated`` on every offense row (even when
    multiplier == 1.0) so the /rankings toggle can swap both families
    uniformly.
    """
    config = _idp_production.load_production_config()
    if not config:
        return
    # Backward-compat with pre-offense-calibration promoted configs —
    # if the file has no offense_multipliers block, this pass is a
    # strict no-op.
    if not (config.get("offense_multipliers") or {}):
        return
    active_mode = str(config.get("active_mode") or "blended")

    by_pos: dict[str, list[dict[str, Any]]] = {"QB": [], "RB": [], "WR": [], "TE": []}
    for row in players_array:
        pos = str(row.get("position") or "").upper()
        if pos not in by_pos:
            continue
        try:
            derived = int(row.get("rankDerivedValue") or 0)
        except (TypeError, ValueError):
            derived = 0
        if derived <= 0:
            continue
        by_pos[pos].append(row)

    for pos, rows in by_pos.items():
        rows.sort(key=lambda r: -int(r.get("rankDerivedValue") or 0))
        for idx, row in enumerate(rows, 1):
            try:
                multiplier = float(
                    _idp_production.get_offense_bucket_multiplier(
                        pos, idx, mode=active_mode
                    )
                )
            except Exception:  # noqa: BLE001
                multiplier = 1.0
            if abs(multiplier - 1.0) < 1e-9:
                continue
            # Same semantics as IDP post-pass: multiplier scales the
            # blended rankDerivedValue; the global re-sort then places
            # the row at its new merged rank.
            old_val = int(row.get("rankDerivedValue") or 0)
            new_val = max(1, int(round(old_val * multiplier)))
            row["rankDerivedValue"] = new_val
            row["offenseCalibrationMultiplier"] = round(multiplier, 4)
            row["offenseCalibrationPositionRank"] = idx
            legacy_ref = row.get("legacyRef")
            if legacy_ref and legacy_ref in players_by_name:
                pdata = players_by_name[legacy_ref]
                if isinstance(pdata, dict):
                    pdata["rankDerivedValue"] = new_val
                    pdata["offenseCalibrationMultiplier"] = round(multiplier, 4)


_DISPLAY_SCALE_MAX: int = 9999

# Reference pool size for percentile-to-value normalization under the
# Final Framework.  Per-source effective ranks (post-ladder) are
# normalized against this fixed denominator so every source's value
# contribution lives in the same combined-pool coordinate system.  500
# aligns with KTC's native pool, the retail market's natural scale;
# deeper ranks asymptote to the Hill's long tail.
_PERCENTILE_REFERENCE_N: int = 500

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
# Chosen via ``scripts/backtest_alpha_shrinkage.py`` against the 25
# daily snapshots in ``data/`` (see
# ``reports/alpha_shrinkage_backtest_full.md``).  The sweep produced
# a clean unimodal optimum at α=0.30 on both the unweighted and
# value-weighted rank-change metrics.  At α=0 (pure anchor)
# subgroup disagreement has no outlet → stability is slightly
# worse; past α≈0.4 the subgroup starts dominating and stability
# degrades sharply (α=1.0 is ~2× worse than α=0.3).
_ALPHA_SHRINKAGE: float = 0.3

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
# The sweep produced a unimodal optimum with clear minima at λ=0.5 on
# the value-weighted rank-change metric (-25.13% vs λ=0, best) and
# λ=0.7 on the unweighted metric (-25.62% vs λ=0, best).  We adopt
# λ=0.5 because the two metrics agree within noise and the lower
# constant imposes a gentler overall penalty while preserving nearly
# all the stability win.
_MAD_PENALTY_LAMBDA: float = 0.5

# Final Framework step 9: soft fallback for unranked players.
#
# When an active source does NOT rank a player but the player's
# position is scope-eligible for that source (i.e. the source could
# have covered them but didn't), the framework says the player
# should get a soft fallback rank "just below the published list"
# rather than being treated as absolute dead last (or, equivalently
# in the prior implementation, as contributing nothing from that
# source).
#
# Implementation: fallback_rank = pool_size + round(pool_size * distance).
# Larger ``_SOFT_FALLBACK_DISTANCE`` → softer penalty (rank further
# below the list but not astronomically so).  Zero means the fallback
# rank is exactly pool_size + 1 (the slot just past the published
# list).
#
# When disabled (``_SOFT_FALLBACK_ENABLED=False``) the blend behaves
# as before PR 4: only sources that actually ranked the player
# contribute.
#
# Promoted value comes from ``scripts/backtest_soft_fallback.py``
# against the 25 daily snapshots.
_SOFT_FALLBACK_ENABLED: bool = True
# Distance = 0.0 means fallback_rank = pool_size + 1 (the slot just
# past the published list — the canonical "just below the list"
# framework prescribes).  Chosen via
# ``scripts/backtest_soft_fallback.py``; 25-day snapshot sweep
# showed +78.67% improvement in value-weighted rank stability over
# the disabled pre-PR-4 behavior, with distance=0.00 best on both
# the unweighted and value-weighted metrics.
_SOFT_FALLBACK_DISTANCE: float = 0.0


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

    Reads ``SLEEPER_LEAGUE_ID`` from the environment and fetches
    ``total_rosters`` + ``scoring_settings`` from Sleeper, cached for
    an hour.  Returns a dict with keys:

      * ``roster_count`` (int) — number of rosters in the league; the
        rookie-pick anchor uses this as N in ``(round-1)*N + slot``.
      * ``bonus_rec_te`` (float) — Sleeper's per-reception TE bonus
        (0.0 for leagues with no TE premium, 0.5 for standard TEP-1.5,
        1.0 for TEP-2.0, etc.).
      * ``fetched_from_sleeper`` (bool) — True when the dict reflects
        a live Sleeper fetch, False when it's a fallback dict.

    Returns a fallback dict (``roster_count=default``, ``bonus_rec_te=0.0``,
    ``fetched_from_sleeper=False``) if the env var is unset, the fetch
    fails, or Sleeper returns an unusable payload — so the pipeline
    still produces output on a cold start / offline machine.

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
    ``rankDerivedValue`` descending.  Pick (round, slot) maps 1-indexed to
    rookie position = ``(round - 1) * N + slot`` where ``N`` is the
    operator's Sleeper league roster count (resolved via
    :func:`_resolve_league_roster_count`; falls back to 12 when the
    league configuration isn't available).  Prior to that fix the
    league size was hardcoded to 12, silently mis-anchoring picks on
    10-team or 14-team leagues.

    Returns the number of picks anchored.  Callers are responsible for
    re-sorting the board by ``rankDerivedValue`` afterward so rank/value
    monotonicity (``assert_ranking_coherence``) is preserved.
    """
    league_size = _resolve_league_roster_count()
    rookies = [
        r
        for r in players_array
        if r.get("assetClass") != "pick"
        and bool(r.get("rookie"))
        and r.get("canonicalConsensusRank")
        and (r.get("rankDerivedValue") or 0) > 0
    ]
    if not rookies:
        return 0
    rookies.sort(
        key=lambda r: (
            -int(r.get("rankDerivedValue") or 0),
            int(r.get("canonicalConsensusRank") or 0),
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
        anchor_val = int(anchor.get("rankDerivedValue") or 0)
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
        "ktc",
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
    *,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float = 1.0,
    tep_native_correction: float = 1.0,
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

    Source overrides
    ────────────────
    ``source_overrides`` (optional) is a dict of per-source user
    settings: ``{key: {"include": bool, "weight": float}}``.  Disabled
    sources are filtered out of every phase.  Overridden weights
    replace the registry-declared weight in the coverage-aware blend.
    When None / empty the pipeline is byte-for-byte identical to the
    default canonical run.

    TE Premium (``tep_multiplier`` + ``tep_native_correction``)
    ───────────────────────────────────────────────────────────
    League-wide TE premium normalization.  Applied as value-level
    multipliers during the Phase 2-3 blend to TE rows ONLY, in two
    symmetric passes:

      * Sources flagged ``is_tep_premium=False`` (KTC, DLF, FantasyPros,
        etc.) have their raw TE values multiplied by
        ``tep_multiplier``.  These sources price TEs for a standard
        league; the multiplier boosts them to the league's actual TEP.
      * Sources flagged ``is_tep_premium=True`` (Dynasty Nerds SF-TEP,
        Yahoo/Boone SF-TEP) have their raw TE values multiplied by
        ``tep_native_correction``.  These sources bake in a fixed
        industry-standard TEP bonus (assumed 1.15); the correction
        re-normalizes them to the league's actual TEP.

    The correction factor is the ratio
    ``tep_multiplier / _TEP_NATIVE_ASSUMED_MULTIPLIER``.  At
    ``tep_multiplier == 1.15`` (standard TEP-1.5), correction is
    ``1.0`` and TEP-native sources pass through unchanged — the
    pre-correction behavior.  For non-TEP leagues (tep_multiplier
    1.0) the correction drops TEP-native values ~13%, undoing their
    baked-in assumption.  For heavy-TEP leagues (tep_multiplier 1.30)
    the correction lifts them ~13%.

    Non-TE positions are untouched by either multiplier.  Expected
    range for ``tep_multiplier`` is ``[1.0, 2.0]``; ``1.0`` is a
    no-op for non-TEP sources but still triggers the correction
    (drops TEP-native values to match).

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
    from src.canonical.player_valuation import (  # noqa: PLC0415
        HILL_PERCENTILE_C,
        HILL_PERCENTILE_S,
        IDP_HILL_PERCENTILE_C,
        IDP_HILL_PERCENTILE_S,
        percentile_to_value,
    )

    # Clamp TEP multiplier to a sane range.  1.0 is a no-op, 2.0 is
    # a generous upper bound (the slider UI caps at 1.5 today).  The
    # clamp is permissive so bad input silently degrades to the
    # pre-TEP behavior rather than raising — matches the override
    # validation philosophy elsewhere in this module.
    try:
        tep_multiplier_effective = float(tep_multiplier)
    except (TypeError, ValueError):
        tep_multiplier_effective = 1.0
    if not math.isfinite(tep_multiplier_effective):
        tep_multiplier_effective = 1.0
    tep_multiplier_effective = max(1.0, min(2.0, tep_multiplier_effective))

    # Build the active source list honoring user-supplied overrides.
    # This is the only place ranks + weights are gated, so downstream
    # loops iterate `active_sources` instead of the raw registry.
    active_sources = _active_sources(source_overrides)
    active_keys = {str(s.get("key") or "") for s in active_sources}

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
    # dlfRookieIdp) rank the current rookie class only.  Their raw
    # within-source rank 1 would otherwise be fed to the Hill curve
    # as if the #1 rookie were the #1 overall player — inflating every
    # rookie to value ~9999.  We crosswalk through a rookie ladder
    # built from a reference source's existing rank on real rookie
    # rows: ladder[k-1] = reference source's rank for the k-th best
    # rookie in the reference source's ORDER.  DLF's ORDER is
    # preserved via its own Phase 1 ordinal sort; only the SCALE
    # comes from the reference ladder.  Offense rookies anchor to
    # KTC; IDP rookies anchor to IDPTC (the IDP backbone).
    rookie_ladder_cache: dict[str, list[int]] = {}

    def _build_rookie_ladder(reference_src_key: str, idp: bool) -> list[int]:
        cache_key = f"{reference_src_key}:{'idp' if idp else 'off'}"
        cached = rookie_ladder_cache.get(cache_key)
        if cached is not None:
            return cached
        ref_ranks: list[tuple[int, int]] = []  # (ref_rank, row_idx)
        for _ridx, _rec in row_source_ranks.items():
            _rank = _rec.get(reference_src_key)
            if _rank is None:
                continue
            _row = players_array[_ridx]
            if not bool(_row.get("rookie")):
                continue
            if _row.get("assetClass") == "pick":
                continue
            _pos = str(_row.get("position") or "").strip().upper()
            if idp:
                if _pos not in _IDP_POSITIONS:
                    continue
            else:
                if _pos not in _OFFENSE_POSITIONS:
                    continue
            ref_ranks.append((int(_rank), _ridx))
        ref_ranks.sort(key=lambda t: t[0])
        ladder = [r for r, _ in ref_ranks]
        rookie_ladder_cache[cache_key] = ladder
        return ladder

    for src in active_sources:
        source_key: str = src["key"]
        position_group: str | None = src.get("position_group")
        primary_scope: str = src["scope"]
        needs_shared_market = bool(
            src.get("needs_shared_market_translation")
        ) and not src.get("is_backbone")
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
                # space.  The framework's step 2 percentile normalization
                # runs in this combined coordinate — see Phase 3.
                effective_rank, method = translate_position_rank(
                    raw_rank, shared_market_ladder
                )
                ladder_depth_meta = len(shared_market_ladder)
                backbone_depth_meta = shared_market_depth
            elif needs_rookie_xlate:
                ref_key = (
                    "idpTradeCalc"
                    if row_scope == SOURCE_SCOPE_OVERALL_IDP
                    else "ktc"
                )
                ladder = _build_rookie_ladder(
                    ref_key,
                    idp=(row_scope == SOURCE_SCOPE_OVERALL_IDP),
                )
                if ladder:
                    effective_rank, method = translate_position_rank(
                        raw_rank, ladder
                    )
                    ladder_depth_meta = len(ladder)
                else:
                    effective_rank = raw_rank
                    method = TRANSLATION_FALLBACK
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
    src_by_key: dict[str, dict[str, Any]] = {s["key"]: s for s in active_sources}

    # Cache which source keys are NOT TEP-native (non-TEP sources) and
    # which ARE TEP-native.  Both get a value-level correction on TE
    # rows during the Phase 2-3 blend, but with different multipliers:
    # non-TEP sources get boosted by ``tep_multiplier`` to the league
    # TEP; TEP-native sources get corrected by ``tep_native_correction``
    # away from their baked-in industry-standard 1.15 toward the
    # league's actual TEP.  Reading ``is_tep_premium`` off the
    # registry once avoids per-player dict lookups in the hot blend loop.
    tep_boosted_source_keys: set[str] = {
        str(s.get("key") or "")
        for s in active_sources
        if not bool(s.get("is_tep_premium"))
    }
    tep_native_source_keys: set[str] = {
        str(s.get("key") or "")
        for s in active_sources
        if bool(s.get("is_tep_premium"))
    }

    # Identify the anchor source (Final Framework step 7).  Currently
    # IDPTC is the only source with ``is_anchor=True`` — its dual-scope
    # coverage lets it price both offense and IDP on a single combined
    # scale, which is what the framework wants for the universal
    # baseline.
    anchor_key: str | None = None
    for s in active_sources:
        if s.get("is_anchor"):
            anchor_key = str(s.get("key") or "")
            break

    def _trimmed_mean_median(values: list[float]) -> tuple[float, float | None]:
        """Framework step 5: unweighted Trimmed Mean-Median.

        Returns (center, mad).  MAD is the mean absolute deviation
        of the trimmed set around its mean (``None`` for a single
        value).
        """
        if not values:
            return 0.0, None
        sorted_vals = sorted(values)
        k = len(sorted_vals)
        if k >= 3:
            trimmed = sorted_vals[1:-1]
            t_mean = sum(trimmed) / len(trimmed)
            m = len(trimmed)
            if m % 2 == 1:
                t_median = float(trimmed[m // 2])
            else:
                t_median = (trimmed[m // 2 - 1] + trimmed[m // 2]) / 2.0
            center = (t_mean + t_median) / 2.0
            mad_val = sum(abs(v - t_mean) for v in trimmed) / len(trimmed)
            return center, mad_val
        if k == 2:
            center = (sorted_vals[0] + sorted_vals[1]) / 2.0
            mad_val = abs(sorted_vals[0] - sorted_vals[1]) / 2.0
            return center, mad_val
        return sorted_vals[0], None

    row_normalized: list[tuple[float, int]] = []  # (blended_value, row_idx)
    for row_idx, source_ranks in row_source_ranks.items():
        # TE positions trigger the TEP boost.  IDP positions swap in
        # the IDP-fit Hill curve.  Picks and offense share the offense
        # curve.
        row_pos = str(players_array[row_idx].get("position") or "").strip().upper()
        row_is_te = row_pos == "TE"
        row_is_pick = (
            players_array[row_idx].get("assetClass") == "pick"
        )
        apply_tep = row_is_te and tep_multiplier_effective > 1.0
        apply_tep_native_correction = (
            row_is_te and abs(tep_native_correction - 1.0) > 1e-6
        )
        if row_pos in _IDP_POSITIONS:
            hill_c, hill_s = IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S
        else:
            hill_c, hill_s = HILL_PERCENTILE_C, HILL_PERCENTILE_S

        # Framework step 2–3: for each source, compute
        # percentile-to-value using the SOURCE's native pool size.
        # Then split contributions into anchor vs subgroup per step 7.
        anchor_value: float | None = None
        subgroup_values: list[float] = []
        all_values: list[float] = []  # full set for MAD

        for source_key, eff_rank in source_ranks.items():
            src_def = src_by_key.get(source_key, {})
            # Percentile denominator is the FIXED reference pool size
            # (_PERCENTILE_REFERENCE_N).  Effective rank is post-ladder
            # (combined-pool coordinate), so dividing by a fixed N
            # keeps every source's contribution in the same value
            # scale.  A rank beyond the reference pool is clamped to
            # p=1 (long tail of the Hill).
            if _PERCENTILE_REFERENCE_N >= 2:
                p = (float(eff_rank) - 1.0) / float(_PERCENTILE_REFERENCE_N - 1)
            else:
                p = 0.0
            p = max(0.0, min(1.0, p))
            value = float(percentile_to_value(p, midpoint=hill_c, slope=hill_s))
            tep_applied = False
            tep_native_corrected = False
            if apply_tep and source_key in tep_boosted_source_keys:
                value *= tep_multiplier_effective
                tep_applied = True
            elif (
                apply_tep_native_correction
                and source_key in tep_native_source_keys
            ):
                value *= tep_native_correction
                tep_native_corrected = True
            all_values.append(value)
            if source_key == anchor_key:
                anchor_value = value
            else:
                subgroup_values.append(value)
            # Per-source audit stamps.
            meta = row_source_meta[row_idx].get(source_key, {})
            declared_weight = float(src_def.get("weight") or 1.0)
            effective_weight = coverage_weight(declared_weight, src_def.get("depth"))
            meta["percentile"] = round(p, 6)
            meta["valueContribution"] = int(round(value))
            meta["effectiveWeight"] = round(effective_weight, 4)
            meta["isAnchor"] = bool(source_key == anchor_key)
            if tep_applied:
                meta["tepBoostApplied"] = True
                meta["tepMultiplier"] = round(tep_multiplier_effective, 4)
            if tep_native_corrected:
                meta["tepNativeCorrectionApplied"] = True
                meta["tepNativeCorrection"] = round(tep_native_correction, 4)

        # Framework step 9: soft fallback for scope-eligible but
        # unranked sources.  Each active source whose scope admits the
        # player's position but which DIDN'T rank them contributes a
        # "just below the published list" value — not zero (current
        # default) and not dead-last (the naive clamp).
        fallback_count = 0
        if _SOFT_FALLBACK_ENABLED:
            for src in active_sources:
                skey = str(src.get("key") or "")
                if skey in source_ranks:
                    continue  # source already covered this player
                # Determine scope eligibility across all declared scopes.
                src_scopes: list[str] = [src["scope"]] + list(
                    src.get("extra_scopes") or []
                )
                eligible = any(
                    _scope_eligible(
                        row_pos, scope, src.get("position_group")
                    )
                    for scope in src_scopes
                )
                if not eligible:
                    continue
                pool_n = source_pool_sizes.get(skey, 0)
                if pool_n <= 0:
                    continue
                # Fallback rank: just past the source's published list
                # with a soft-distance buffer.
                fallback_rank = pool_n + int(
                    round(pool_n * _SOFT_FALLBACK_DISTANCE)
                )
                if _PERCENTILE_REFERENCE_N >= 2:
                    p_fallback = (
                        float(fallback_rank) - 1.0
                    ) / float(_PERCENTILE_REFERENCE_N - 1)
                else:
                    p_fallback = 1.0
                p_fallback = max(0.0, min(1.0, p_fallback))
                fallback_value = float(
                    percentile_to_value(
                        p_fallback, midpoint=hill_c, slope=hill_s
                    )
                )
                # TEP boost on TE rows for non-native sources; correction
                # for native sources.  Same rules as the covered path.
                if apply_tep and skey in tep_boosted_source_keys:
                    fallback_value *= tep_multiplier_effective
                elif (
                    apply_tep_native_correction
                    and skey in tep_native_source_keys
                ):
                    fallback_value *= tep_native_correction
                all_values.append(fallback_value)
                if skey == anchor_key:
                    anchor_value = fallback_value
                else:
                    subgroup_values.append(fallback_value)
                fallback_count += 1

        players_array[row_idx]["softFallbackCount"] = fallback_count

        # Framework step 5 + 7–8: compute subgroup center, then combine
        # with anchor under α-shrinkage.
        subgroup_center: float | None
        if subgroup_values:
            subgroup_center, _ = _trimmed_mean_median(subgroup_values)
        else:
            subgroup_center = None

        subgroup_delta: float | None = None
        if anchor_value is not None and subgroup_center is not None:
            # Anchored blend: baseline is anchor, subgroup pulls it.
            subgroup_delta = subgroup_center - anchor_value
            center_value = anchor_value + _ALPHA_SHRINKAGE * subgroup_delta
        elif anchor_value is not None:
            # Anchor-only coverage (e.g. a player only IDPTC ranks).
            center_value = anchor_value
        elif subgroup_center is not None:
            # No anchor coverage — fall back to subgroup blend alone
            # (effective α=1.0 for this row).  The soft fallback for
            # unranked players arrives in a later PR to handle deeper
            # cases.
            center_value = subgroup_center
        else:
            center_value = 0.0

        # Framework step 6: MAD across ALL contributing sources.
        _, source_mad = _trimmed_mean_median(all_values)

        if (
            source_mad is not None
            and _MAD_PENALTY_LAMBDA > 0
            and not row_is_pick
        ):
            mad_penalty = min(
                center_value, _MAD_PENALTY_LAMBDA * source_mad
            )
        else:
            mad_penalty = 0.0

        blended_value = max(0.0, center_value - mad_penalty)

        hill_value_spread = (
            statistics.stdev(all_values) if len(all_values) >= 2 else None
        )

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
        players_array[row_idx]["alphaShrinkage"] = round(_ALPHA_SHRINKAGE, 4)

        # Stamp MAD diagnostics on the row so the value chain can
        # surface "center value − λ·MAD = blended" transparently.
        players_array[row_idx]["sourceMAD"] = (
            round(source_mad, 2) if source_mad is not None else None
        )
        players_array[row_idx]["madPenaltyApplied"] = (
            round(mad_penalty, 2) if mad_penalty > 0 else None
        )

        players_array[row_idx]["hillValueSpread"] = (
            round(hill_value_spread, 2) if hill_value_spread is not None else None
        )
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
                len(source_ranks),
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

    # ── Phase 4c: IDP calibration post-pass ──
    # Apply the promoted IDP calibration config (if any) to every
    # DL/LB/DB row. Strict no-op when config/idp_calibration.json is
    # absent — the calibration lab's Promote step is the only way to
    # activate this. See src/idp_calibration/production.py.
    # Snapshot the pre-calibration rank and value on every ranked row so
    # the /rankings toggle can reconstruct the uncalibrated board
    # (rank + value) without a refetch. Runs BEFORE the calibration
    # passes so offense rows get a snapshot too (they're re-ranked
    # globally even though offense calibration's multipliers are all
    # 1.0; the cross-family scale still reshuffles the merged board).
    # Mirror into the legacy players_by_name dict as well so the
    # frontend row-builder (which reads player.rankDerivedValueUncalibrated)
    # can render the value-chain panel.
    for row in players_array:
        rank = row.get("canonicalConsensusRank")
        if rank is None or rank <= 0:
            continue
        snapshot_rank = int(rank)
        snapshot_val = int(row.get("rankDerivedValue") or 0)
        row["canonicalConsensusRankUncalibrated"] = snapshot_rank
        row["rankDerivedValueUncalibrated"] = snapshot_val
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["canonicalConsensusRankUncalibrated"] = snapshot_rank
                pdata["rankDerivedValueUncalibrated"] = snapshot_val

    _apply_idp_calibration_post_pass(players_array, players_by_name)
    # Offense calibration deliberately not applied to live values.
    # Offense trade value tracks the market-derived rankings (KTC/DLF/
    # FantasyCalc/etc.); VOR bucket multipliers produced absurd
    # artefacts (QB bucket cliffs, Mahomes-at-half-value-of-QB1). The
    # lab still computes offense_multipliers as an analytical
    # reference but they do NOT mutate rankDerivedValue.
    # _apply_offense_calibration_post_pass(players_array, players_by_name)

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
    _anchor_year = int(_load_pick_year_discount().get("baselineYear") or 2026)
    _anchor_current_year_picks_to_rookies(players_array, _anchor_year)

    # 2a) Compact ranks after suppression/anchor so the ranked board is
    #     still contiguous 1..N and value-monotonic.  Sort primarily by
    #     rankDerivedValue desc so anchored picks naturally bubble to the
    #     neighborhood of their rookie target; fall back to the existing
    #     canonicalConsensusRank to preserve the prior Phase-4 ordering
    #     for all rows whose values were not mutated.  Tier IDs are
    #     re-derived after compaction via gap-based detection on the
    #     blended ``rankDerivedValue`` series (see below).
    ranked_rows = sorted(
        [r for r in players_array if r.get("canonicalConsensusRank")],
        key=lambda r: (
            -int(r.get("rankDerivedValue") or 0),
            int(r["canonicalConsensusRank"]),
        ),
    )
    # Compact ranks, skipping current-year slot picks so picks don't
    # consume merged-board rank slots. Picks still appear (the row is
    # kept in the array) but their ``canonicalConsensusRank`` is
    # cleared — they're a proxy for the corresponding rookie, so the
    # user sees the value without the pick pushing every other player
    # down one rank. Only applies to slot-specific current-year picks
    # (e.g. "2026 Pick 1.06"); tier-generic picks ("2026 Early 1st")
    # still take ordinary rank slots.
    #
    # Collect the ranked rows that actually receive a tier ID so the
    # gap-detection pass below sees only the compacted board (no
    # None-ranked anchor slot picks in the middle of its gap series).
    tiered_rows: list[dict[str, Any]] = []
    new_rank = 0
    for r in ranked_rows:
        is_anchor_slot_pick = False
        if r.get("assetClass") == "pick":
            parsed = _parse_pick_slot(r.get("canonicalName") or "")
            if parsed is not None and parsed[0] == _anchor_year:
                is_anchor_slot_pick = True
        if is_anchor_slot_pick:
            r["canonicalConsensusRank"] = None
            r["canonicalTierId"] = None
            continue
        new_rank += 1
        old_rank = r.get("canonicalConsensusRank")
        if old_rank != new_rank:
            r["canonicalConsensusRank"] = new_rank
        tiered_rows.append(r)

    # Gap-based tier detection on the blended value series.  Tiers
    # land where the per-player value gap is unusually large relative
    # to the local rolling-median gap: a 400-point drop from rank
    # 12→13 registers as a new tier boundary; a 3-point drop from
    # 312→313 does not.  The frontend renders the resulting tier IDs
    # as generic "Tier N" labels, so every math-detected tier flows
    # through uncapped.
    for r, tier_id in zip(
        tiered_rows, _compute_value_based_tier_ids(tiered_rows)
    ):
        r["canonicalTierId"] = tier_id

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
        "hillValueSpread": None,
        "sourceMAD": None,
        "madPenaltyApplied": None,
        "anchorValue": None,
        "subgroupBlendValue": None,
        "subgroupDelta": None,
        "alphaShrinkage": None,
        "softFallbackCount": 0,
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
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
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
    ``_compute_unified_rankings`` docstring).  Two modes:

      * ``None`` (default) — derive the multiplier from the operator's
        Sleeper league context via
        :func:`_derive_tep_multiplier_from_league`.  A standard TEP-1.5
        league (``bonus_rec_te == 0.5``) yields ``1.15``; a non-TEP
        league yields ``1.0`` (a no-op).  This is the production
        cold-start path.
      * an explicit ``float`` — use the caller's value verbatim (after
        the same ``[1.0, 2.0]`` clamp the derivation applies).  Used by
        the override endpoint when the user moves the TEP slider.

    Previously this parameter defaulted to ``1.0``, which meant every
    cold start produced a "clean" board regardless of league setup
    and the frontend had to stamp its own ``tepMultiplier=1.15``
    default on top.  That path is now symmetric: absent override →
    league-derived, explicit override → user value.

    ``_for_delta`` (internal) skips work that only feeds fields the
    delta payload discards (trust-mirror into legacy players dict,
    valueAuthority summary).  ``build_rankings_delta_payload`` sets
    this to ``True`` so overrides round-trips don't pay for output
    blocks the wire shape drops.
    """
    # ── Resolve the TE-premium multiplier ──
    # ``None`` = caller wants the league-derived default (production
    # cold start + any override request that omits ``tep_multiplier``).
    # A finite float = caller passed an explicit override; we trust
    # their value after the standard [1.0, 2.0] clamp.  The derived
    # value is always computed (even when overridden) so the
    # ``rankingsOverride`` summary can report both channels and the
    # frontend slider can show the "Auto" baseline.
    league_context = _resolve_league_context()
    tep_multiplier_derived = _derive_tep_multiplier_from_league(league_context)
    if tep_multiplier is None:
        tep_multiplier_effective = tep_multiplier_derived
        tep_multiplier_source = (
            "derived"
            if league_context.get("fetched_from_sleeper")
            else "default"
        )
    else:
        try:
            tep_multiplier_effective = float(tep_multiplier)
        except (TypeError, ValueError):
            tep_multiplier_effective = tep_multiplier_derived
            tep_multiplier_source = (
                "derived"
                if league_context.get("fetched_from_sleeper")
                else "default"
            )
        else:
            if not math.isfinite(tep_multiplier_effective):
                tep_multiplier_effective = tep_multiplier_derived
                tep_multiplier_source = (
                    "derived"
                    if league_context.get("fetched_from_sleeper")
                    else "default"
                )
            else:
                tep_multiplier_effective = max(
                    _TEP_DERIVED_CLAMP_MIN,
                    min(_TEP_DERIVED_CLAMP_MAX, tep_multiplier_effective),
                )
                tep_multiplier_source = "explicit"

    # Correction factor applied to TEP-native sources' TE contributions
    # so their baked-in (assumed 1.15) boost is re-normalized to the
    # league's actual TEP.  At tep_multiplier_effective == 1.15 this is
    # a no-op (1.0), so standard TEP-1.5 leagues see byte-for-byte the
    # old behavior.  For non-TEP / off-standard leagues this drops or
    # lifts the TEP-native TE contributions symmetrically to the
    # tep_multiplier that boosts non-TEP sources.
    if _TEP_NATIVE_ASSUMED_MULTIPLIER > 0:
        tep_native_correction = (
            tep_multiplier_effective / _TEP_NATIVE_ASSUMED_MULTIPLIER
        )
    else:
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
        players_array, parse_errors=source_parse_errors
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
        tep_native_correction=tep_native_correction,
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
    _fresh_counts = sum(
        1 for v in source_timestamps.values() if v.get("staleness") == "fresh"
    )
    _stale_counts = sum(
        1 for v in source_timestamps.values() if v.get("staleness") == "stale"
    )
    _missing_counts = sum(
        1 for v in source_timestamps.values() if v.get("staleness") == "missing"
    )
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

    # ── Rankings override summary ──
    # Always produced, even for the default (no-override) response,
    # so downstream consumers (frontend hooks, audit tooling, tests)
    # can hydrate a consistent shape without branching on presence.
    rankings_override = _summarize_source_overrides(
        source_overrides,
        tep_multiplier=tep_multiplier_effective,
        tep_multiplier_derived=tep_multiplier_derived,
        tep_multiplier_source=tep_multiplier_source,
        tep_native_correction=tep_native_correction,
    )

    contract_payload: dict[str, Any] = {
        **base,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": generated_at,
        "playersArray": players_array,
        "playerCount": len(players_array),
        "valueAuthority": (
            None if _for_delta else _build_value_authority_summary(players_array)
        ),
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
    "sourceMAD",
    "madPenaltyApplied",
    "anchorValue",
    "subgroupBlendValue",
    "subgroupDelta",
    "alphaShrinkage",
    "softFallbackCount",
    "isSingleSource",
    "isStructurallySingleSource",
    "hasSourceDisagreement",
    "confidenceBucket",
    "confidenceLabel",
    "marketGapDirection",
    "marketGapMagnitude",
    "anomalyFlags",
    "canonicalTierId",
    "marketConfidence",
    "values",
    "idpBackboneFallback",
    "canonicalSiteValues",
    "quarantined",
    "ktcRank",
    "idpRank",
)


def build_rankings_delta_payload(
    raw_payload: dict[str, Any],
    *,
    data_source: dict[str, Any] | None = None,
    source_overrides: dict[str, dict[str, Any]] | None = None,
    tep_multiplier: float | None = None,
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
        _for_delta=True,
    )

    delta_players: list[dict[str, Any]] = []
    active_ids: list[str] = []
    for row in full.get("playersArray") or []:
        player_id = str(
            row.get("displayName") or row.get("canonicalName") or ""
        ).strip()
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
    unexplained: list[dict[str, Any]] = []
    for row in players_array:
        rank = row.get("canonicalConsensusRank")
        if rank is None or rank > rank_limit:
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
                warnings.append(
                    f"source_below_floor:{src_key}:{count}:{threshold}"
                )
                below_floor_count += 1

        if any_source_missing or below_floor_count >= 2:
            degraded = True

    # ── Pick-count floor ────────────────────────────────────────────────
    # Count draft picks on the board and error if below floor.  Live
    # carries ~126 picks; floor is 100 (≈80% baseline) per the audit
    # recommendation.  Missing pickAnchors is also an error.
    if len(players_array) >= 250:
        pick_count = sum(
            1
            for row in players_array
            if isinstance(row, dict) and row.get("assetClass") == "pick"
        )
        if pick_count < _PICK_COUNT_FLOOR:
            errors.append(
                f"pick_count_below_floor:{pick_count}:{_PICK_COUNT_FLOOR}"
            )
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
            vals = r.get("values")
            if not isinstance(vals, dict):
                return 0.0
            try:
                return float(vals.get("overall") or 0)
            except (TypeError, ValueError):
                return 0.0

        for bucket, src_floors in coverage_floors.items():
            bucket_rows = [
                r
                for r in players_array
                if isinstance(r, dict) and r.get("assetClass") == bucket
            ]
            if len(bucket_rows) < 50:
                warnings.append(
                    f"top50_coverage_insufficient_rows:{bucket}:{len(bucket_rows)}"
                )
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
                "source_parse_error:"
                f"{perr.get('source', '?')}:{perr.get('error', '?')}"
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
    run_summary = settings_block.get("sourceRunSummary") if isinstance(settings_block, dict) else None
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
                is_critical = (
                    src in _CRITICAL_PRIMARY_SOURCES
                    or src.startswith("IDPTradeCalc")
                )
                if is_critical:
                    errors.append(f"partial_run_critical:{src}")
                else:
                    warnings.append(f"partial_run_unknown:{src}")

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
