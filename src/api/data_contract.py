from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any

from src.data_models.contracts import utc_now_iso

OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS = {
    "Bobby Brown",
    "Cameron Young",
    "Dwight Bentley",
    "Josh Johnson",
}


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
_RANKABLE_POSITIONS = _OFFENSE_POSITIONS | _IDP_POSITIONS
_OFFENSE_SIGNAL_KEYS = {
    "ktc",
}
_IDP_SIGNAL_KEYS = {
    "idpTradeCalc",
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
#   "name_collision_cross_universe" — same normalized name in offense + IDP
#   "position_source_contradiction" — position family disagrees with source evidence
#   "near_name_value_mismatch"     — same last name, wildly different values
#   "unsupported_position"         — position not in _SUPPORTED_BOARD_POSITIONS
#   "no_valid_source_values"       — no source values > 0 but has derived value
#   "orphan_csv_graft"             — value came from CSV enrichment for wrong entity
_QUARANTINE_FLAGS = {
    "name_collision_cross_universe",
    "position_source_contradiction",
    "near_name_value_mismatch",
    "unsupported_position",
    "no_valid_source_values",
    "orphan_csv_graft",
}

# CSV export paths for source enrichment (relative to repo root)
_SOURCE_CSV_PATHS = {
    "ktc": "exports/latest/site_raw/ktc.csv",
    "idpTradeCalc": "exports/latest/site_raw/idpTradeCalc.csv",
}


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
) -> list[str]:
    """Return a list of machine-readable anomaly flag strings for a player.

    Each flag signals a data-quality issue that a UI or audit script can
    surface.  An empty list means no anomalies detected.
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

    # 6. Suspicious disagreement between sources (> 150 ordinal ranks apart)
    rank_values = list(source_ranks.values())
    if len(rank_values) >= 2:
        spread = max(rank_values) - min(rank_values)
        if spread > _SUSPICIOUS_DISAGREEMENT_THRESHOLD:
            flags.append("suspicious_disagreement")

    # 7. Missing-source distortion — only 1 source present for a player that
    #    could reasonably appear in 2+ sources.  Currently only flags if the
    #    player has a single source but the OTHER source has a non-null value
    #    in canonicalSites (suggesting the source should have ranked them).
    off_site_vals = [canonical_sites.get(k) for k in _OFFENSE_SIGNAL_KEYS]
    idp_site_vals = [canonical_sites.get(k) for k in _IDP_SIGNAL_KEYS]
    has_off_val = any(v is not None and v > 0 for v in off_site_vals)
    has_idp_val = any(v is not None and v > 0 for v in idp_site_vals)
    if len(source_ranks) == 1 and has_off_val and has_idp_val:
        flags.append("missing_source_distortion")

    # 8. Impossible value state — has a rank but rankDerivedValue <= 0
    if source_ranks and (rank_derived_value is None or rank_derived_value <= 0):
        flags.append("impossible_value")

    return flags


def _compute_market_gap(
    source_ranks: dict[str, int],
) -> tuple[str, float | None]:
    """Determine which source ranks a player higher and by how much.

    Returns (direction, magnitude) where direction is one of:
      "ktc_higher", "idptc_higher", "none"
    and magnitude is the absolute ordinal rank difference (None if < 2 sources).
    """
    ktc_rank = source_ranks.get("ktc")
    idp_rank = source_ranks.get("idpTradeCalc")
    if ktc_rank is not None and idp_rank is not None:
        diff = idp_rank - ktc_rank  # positive means KTC ranks higher (lower number)
        if diff > 0:
            return "ktc_higher", float(abs(diff))
        elif diff < 0:
            return "idptc_higher", float(abs(diff))
        return "none", 0.0
    return "none", None


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
      1. Cross-universe name collision (same normalized name in offense + IDP)
      2. Position-source contradiction (offense player with only IDP evidence)
      3. Near-name value mismatch (same last name, different universes, wild value gap)
      4. Unsupported position on the public board
      5. No valid source values despite having a derived value
      6. Identity confidence scoring

    Returns a validation summary dict for payload-level reporting.
    """
    # ── Build indexes for collision detection ──
    norm_name_to_rows: dict[str, list[int]] = {}
    last_name_to_rows: dict[str, list[int]] = {}

    for idx, row in enumerate(players_array):
        name = row.get("canonicalName") or row.get("displayName") or ""
        norm = _normalize_for_collision(name)
        if norm:
            norm_name_to_rows.setdefault(norm, []).append(idx)
        last = _extract_last_name(name)
        if last and len(last) > 2:  # skip very short surnames
            last_name_to_rows.setdefault(last, []).append(idx)

    quarantine_count = 0
    collision_pairs: list[dict[str, Any]] = []
    near_name_pairs: list[dict[str, Any]] = []

    # ── Check 1: Cross-universe name collisions ──
    for norm, indices in norm_name_to_rows.items():
        if len(indices) < 2:
            continue
        asset_classes = {players_array[i].get("assetClass") for i in indices}
        # Flag if the same normalized name appears in both offense and IDP
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

        # Offense position but only IDP values (and not an allowed exception)
        name = row.get("canonicalName") or ""
        if pos in _OFFENSE_POSITIONS and has_idp_val and not has_off_val:
            if name not in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS:
                flags = row.get("anomalyFlags") or []
                if "position_source_contradiction" not in flags:
                    flags.append("position_source_contradiction")
                    row["anomalyFlags"] = flags

        # IDP position but only offense values
        if pos in _IDP_POSITIONS and has_off_val and not has_idp_val:
            if name not in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS:
                flags = row.get("anomalyFlags") or []
                if "position_source_contradiction" not in flags:
                    flags.append("position_source_contradiction")
                    row["anomalyFlags"] = flags

    # ── Check 3: Near-name value mismatch across universes ──
    for last, indices in last_name_to_rows.items():
        if len(indices) < 2:
            continue
        # Only check pairs that span offense + IDP
        off_indices = [i for i in indices if players_array[i].get("assetClass") == "offense"]
        idp_indices = [i for i in indices if players_array[i].get("assetClass") == "idp"]
        if not off_indices or not idp_indices:
            continue

        for oi in off_indices:
            for ii in idp_indices:
                off_row = players_array[oi]
                idp_row = players_array[ii]
                off_val = off_row.get("rankDerivedValue") or 0
                idp_val = idp_row.get("rankDerivedValue") or 0
                if off_val <= 0 or idp_val <= 0:
                    continue
                ratio = max(off_val, idp_val) / max(min(off_val, idp_val), 1)
                if ratio > _NEAR_NAME_VALUE_RATIO_THRESHOLD:
                    near_name_pairs.append({
                        "lastName": last,
                        "offenseName": off_row.get("canonicalName"),
                        "idpName": idp_row.get("canonicalName"),
                        "offenseValue": off_val,
                        "idpValue": idp_val,
                        "ratio": round(ratio, 1),
                    })
                    # Flag the lower-valued row as suspicious
                    suspect_idx = oi if off_val < idp_val else ii
                    suspect = players_array[suspect_idx]
                    flags = suspect.get("anomalyFlags") or []
                    if "near_name_value_mismatch" not in flags:
                        flags.append("near_name_value_mismatch")
                        suspect["anomalyFlags"] = flags

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
        "nearNameMismatches": near_name_pairs,
        "crossUniverseCollisionCount": len(collision_pairs),
        "nearNameMismatchCount": len(near_name_pairs),
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
    "hasSourceDisagreement",
    "blendedSourceRank",
    "sourceRankSpread",
    "marketGapDirection",
    "marketGapMagnitude",
    "identityConfidence",
    "identityMethod",
    "quarantined",
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
    """Strip generational suffixes (Jr, Sr, II-VI) for resilient matching."""
    n = name.strip()
    for sfx in (" Jr.", " Jr", " Sr.", " Sr", " II", " III", " IV", " V", " VI"):
        if n.endswith(sfx):
            n = n[: -len(sfx)].strip()
    return n


def _enrich_from_source_csvs(players_array: list[dict[str, Any]]) -> None:
    """Fill missing canonicalSiteValues from source CSV exports.

    When the scraper's dashboard payload is missing values for a source
    (e.g. KTC scrape failed but the CSV persists from a prior run), load
    the CSV and inject values into canonicalSiteValues so the ranking
    function can use them.
    """
    import csv
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]

    for source_key, csv_rel in _SOURCE_CSV_PATHS.items():
        csv_path = repo / csv_rel
        if not csv_path.exists():
            continue

        # Load CSV — always load and enrich missing values.
        # The per-row check below skips players that already have values,
        # so loading the CSV is safe even when most players are populated.
        csv_lookup: dict[str, int] = {}
        try:
            with csv_path.open("r", encoding="utf-8-sig") as f:
                for csvrow in csv.DictReader(f):
                    name = str(csvrow.get("name", "")).strip()
                    val = csvrow.get("value", "")
                    if not name or not val:
                        continue
                    try:
                        csv_lookup[_strip_name_suffix(name).lower()] = int(float(val))
                    except (ValueError, TypeError):
                        continue
        except Exception:
            continue

        if not csv_lookup:
            continue

        # Enrich missing values
        for row in players_array:
            csv_vals = row.get("canonicalSiteValues")
            if not isinstance(csv_vals, dict):
                continue
            existing = _safe_num(csv_vals.get(source_key))
            if existing is not None and existing > 0:
                continue
            canon_name = _strip_name_suffix(
                str(row.get("canonicalName") or row.get("displayName") or "")
            ).lower()
            csv_val = csv_lookup.get(canon_name)
            if csv_val is not None and csv_val > 0:
                csv_vals[source_key] = csv_val


def _compute_unified_rankings(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Compute a single unified ranking across all sources and positions.

    Step 1: For each source, rank eligible players by that source's value
            descending to produce a source-specific ordinal rank.
    Step 2: Convert each source rank to a normalized 1-9999 value via
            rank_to_value() (Hill curve).
    Step 3: For players with multiple sources (future), average the
            normalized values.  Currently each player has exactly one source.
    Step 4: Sort all players by their normalized value descending and assign
            canonicalConsensusRank 1..N as the overall board position.

    Stamps onto each row:
      - sourceRanks: dict of {sourceKey: ordinalRank}
      - rankDerivedValue: the normalized 1-9999 value from rank_to_value()
      - canonicalConsensusRank: the unified overall rank (1 = best)
      - blendedSourceRank: mean of per-source ordinal ranks (float, 2dp)
      - sourceRankSpread: max - min source rank (None if < 2 sources)
      - isSingleSource: True when exactly one source contributed
      - hasSourceDisagreement: True when spread exceeds medium threshold
      - marketGapDirection: "ktc_higher" | "idptc_higher" | "none"
      - marketGapMagnitude: absolute ordinal rank difference (None if < 2)
      - confidenceBucket: "high" | "medium" | "low" | "none"
      - confidenceLabel: human-readable explanation of the bucket
      - anomalyFlags: list[str] of machine-readable anomaly identifiers
      - ktcRank / idpRank: preserved for backward compatibility
    """
    from src.canonical.player_valuation import rank_to_value  # noqa: PLC0415

    # ── Step 1: Per-source ordinal ranking ──
    source_configs = [
        ("ktc", lambda row: _safe_num((row.get("canonicalSiteValues") or {}).get("ktc"))),
        ("idpTradeCalc", lambda row: _safe_num((row.get("canonicalSiteValues") or {}).get("idpTradeCalc"))),
    ]

    # Track per-source rank for each row index
    row_source_ranks: dict[int, dict[str, int]] = {}

    for source_key, value_fn in source_configs:
        eligible: list[tuple[float, int]] = []  # (value, row_index)
        for idx, row in enumerate(players_array):
            pos = str(row.get("position") or "").strip().upper()
            if pos not in _RANKABLE_POSITIONS:
                continue
            val = value_fn(row)
            if val is None or val <= 0:
                continue
            eligible.append((val, idx))

        eligible.sort(key=lambda t: -t[0])
        for rank_idx, (_, row_idx) in enumerate(eligible):
            ordinal_rank = rank_idx + 1
            row_source_ranks.setdefault(row_idx, {})[source_key] = ordinal_rank

    # ── Step 2-3: Normalized value (Hill curve) and blend ──
    row_normalized: list[tuple[float, int]] = []  # (normalized_value, row_index)
    for row_idx, source_ranks in row_source_ranks.items():
        # Convert each source rank to normalized value, then average
        normalized_values = [rank_to_value(r) for r in source_ranks.values()]
        blended_value = sum(normalized_values) / len(normalized_values)
        row_normalized.append((blended_value, row_idx))

    # ── Step 4: Unified sort and overall rank assignment ──
    row_normalized.sort(key=lambda t: (-t[0], players_array[t[1]].get("canonicalName", "").lower()))

    for overall_idx, (norm_val, row_idx) in enumerate(row_normalized[:OVERALL_RANK_LIMIT]):
        row = players_array[row_idx]
        overall_rank = overall_idx + 1
        derived = int(norm_val)
        source_ranks = row_source_ranks.get(row_idx, {})
        rank_values = list(source_ranks.values())

        # ── Core ranking fields (existing) ──
        row["sourceRanks"] = source_ranks
        row["rankDerivedValue"] = derived
        row["canonicalConsensusRank"] = overall_rank
        row["sourceCount"] = len(source_ranks)

        # ── New trust/transparency fields ──
        # Blended source rank: mean of per-source ordinal ranks
        blended_source_rank = (
            sum(rank_values) / len(rank_values) if rank_values else None
        )
        row["blendedSourceRank"] = (
            round(blended_source_rank, 2) if blended_source_rank is not None else None
        )

        # Source rank spread: max - min across sources (None if < 2 sources)
        source_rank_spread: float | None = None
        if len(rank_values) >= 2:
            source_rank_spread = float(max(rank_values) - min(rank_values))
        row["sourceRankSpread"] = source_rank_spread

        # Single-source flag
        row["isSingleSource"] = len(source_ranks) == 1

        # Source disagreement flag (True when spread exceeds medium threshold)
        row["hasSourceDisagreement"] = (
            source_rank_spread is not None
            and source_rank_spread > _CONFIDENCE_SPREAD_MEDIUM
        )

        # Market gap: which source ranks the player higher
        gap_dir, gap_mag = _compute_market_gap(source_ranks)
        row["marketGapDirection"] = gap_dir
        row["marketGapMagnitude"] = gap_mag

        # Confidence bucket
        bucket, label = _compute_confidence_bucket(len(source_ranks), source_rank_spread)
        row["confidenceBucket"] = bucket
        row["confidenceLabel"] = label

        # Anomaly flags
        row["anomalyFlags"] = _compute_anomaly_flags(
            name=row.get("canonicalName") or row.get("displayName") or "",
            position=row.get("position"),
            asset_class=row.get("assetClass") or "",
            source_ranks=source_ranks,
            rank_derived_value=derived,
            canonical_sites=row.get("canonicalSiteValues") or {},
        )

        # Backward compatibility: set ktcRank / idpRank if applicable
        if "ktc" in source_ranks:
            row["ktcRank"] = source_ranks["ktc"]
        if "idpTradeCalc" in source_ranks:
            row["idpRank"] = source_ranks["idpTradeCalc"]

        # Mirror into legacy players dict
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["rankDerivedValue"] = derived
                pdata["_canonicalConsensusRank"] = overall_rank
                if "ktc" in source_ranks:
                    pdata["ktcRank"] = source_ranks["ktc"]
                if "idpTradeCalc" in source_ranks:
                    pdata["idpRank"] = source_ranks["idpTradeCalc"]


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
        "rookie": bool(p_data.get("_formatFitRookie", False)),
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
        "hasSourceDisagreement": False,
        "blendedSourceRank": None,
        "sourceRankSpread": None,
        "marketGapDirection": "none",
        "marketGapMagnitude": None,
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
    _enrich_from_source_csvs(players_array)

    # Compute unified rankings: all sources, all positions, one board.
    # This is the single source of truth for canonicalConsensusRank / rankDerivedValue.
    _compute_unified_rankings(players_array, players_by_name)

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
            "Unified dynasty + IDP rankings board. Each player is ranked "
            "within their source(s) by raw source value descending, then "
            "converted to a 1-9999 normalized value via a Hill-curve formula. "
            "Players with multiple sources have their normalized values "
            "averaged. All players are sorted by normalized value into one "
            "unified board capped at {limit} entries."
        ).format(limit=OVERALL_RANK_LIMIT),
        "sources": [
            {
                "key": "ktc",
                "name": "KeepTradeCut",
                "covers": "Offense (QB, RB, WR, TE) + draft picks",
            },
            {
                "key": "idpTradeCalc",
                "name": "IDP Trade Calculator",
                "covers": "IDP (DL, LB, DB)",
            },
        ],
        "formula": {
            "name": "Hill curve",
            "expression": "value = max(1, min(9999, round(1 + 9998 / (1 + ((rank-1)/45)^1.10))))",
            "midpoint": 45,
            "slope": 1.10,
            "scaleMin": 1,
            "scaleMax": 9999,
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
            "missing_source_distortion",
            "impossible_value",
            "name_collision_cross_universe",
            "position_source_contradiction",
            "near_name_value_mismatch",
            "unsupported_position",
            "no_valid_source_values",
            "orphan_csv_graft",
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
            if len(players_array) >= 250 and name in OFFENSE_TO_IDP_VALIDATION_EXCEPTIONS:
                continue
            errors.append(
                f"playersArray offense→IDP mismatch: {name or '<unknown>'} tagged {pos} "
                "with offensive-only source signal(s)"
            )

        if name:
            norm = re.sub(r"[^a-z0-9]+", "", str(name).lower())
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
