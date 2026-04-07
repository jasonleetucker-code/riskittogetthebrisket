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
    "Elijah Mitchell",
    "Josh Johnson",
}


CONTRACT_VERSION = "2026-03-10.v2"

# ── KTC-only rankings: single source of truth ─────────────────────────────────
# rank_to_value() is imported from src.canonical.player_valuation — that module
# is the ONE authoritative formula implementation.
#
# KTC_RANK_LIMIT is the hard player cap.  It must match both JS frontends:
#   • frontend/lib/dynasty-data.js           → KTC_RANK_LIMIT = 500
#   • Static/js/runtime/10-rankings-and-picks.js → KTC_LIMIT = 500
#
# _compute_ktc_rankings() stamps ktcRank + rankDerivedValue onto every
# playersArray entry (and the legacy players dict) so both frontends can
# consume pre-computed values and only fall back to client-side computation
# when these fields are absent (e.g. stale offline data without this field).
# ─────────────────────────────────────────────────────────────────────────────
KTC_RANK_LIMIT: int = 500
_KICKER_POSITIONS = {"K", "PK"}
_OFFENSE_POSITIONS = {"QB", "RB", "WR", "TE"}
_IDP_POSITIONS = {"DL", "LB", "DB"}
_OFFENSE_SIGNAL_KEYS = {
    "ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "draftSharks",
    "yahoo", "dynastyNerds", "dlfSf", "dlfRsf", "flock",
}
_IDP_SIGNAL_KEYS = {
    "pffIdp", "fantasyProsIdp", "draftSharksIdp", "dlfIdp", "dlfRidp",
    "idpTradeCalc", "adamIdp",
}


def _compute_ktc_rankings(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
) -> None:
    """Stamp ktcRank, rankDerivedValue, and canonicalConsensusRank onto each eligible entry.

    Eligibility (matches both JS frontends exactly):
      • position must be non-empty, not "?", not "PICK", not a kicker
      • canonicalSiteValues.ktc must be a finite positive number

    Ranks are integers 1..KTC_RANK_LIMIT (top 500 by KTC value descending).
    rank_to_value() is the authoritative formula — no duplication here.
    canonicalConsensusRank is the backend-authoritative rank that frontends
    should use directly instead of recomputing their own sort order.

    Also mirrors values into the legacy players dict for the Static runtime.
    """
    from src.canonical.player_valuation import rank_to_value  # noqa: PLC0415

    eligible: list[tuple[float, dict[str, Any]]] = []
    for row in players_array:
        pos = str(row.get("position") or "").strip().upper()
        if not pos or pos in {"?", "PICK"} or pos in _KICKER_POSITIONS:
            continue
        ktc_raw = (row.get("canonicalSiteValues") or {}).get("ktc")
        ktc_val = _safe_num(ktc_raw)
        if ktc_val is None or ktc_val <= 0:
            continue
        eligible.append((ktc_val, row))

    eligible.sort(key=lambda t: -t[0])

    for i, (_, row) in enumerate(eligible[:KTC_RANK_LIMIT]):
        rank = i + 1
        derived = int(rank_to_value(rank))
        row["ktcRank"] = rank
        row["rankDerivedValue"] = derived
        # Backend-authoritative consensus rank — frontends use this directly
        # instead of recomputing their own sort order.
        row["canonicalConsensusRank"] = rank
        # Mirror into legacy players dict so Static runtime reads consistent values.
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["ktcRank"] = rank
                pdata["rankDerivedValue"] = derived
                pdata["_canonicalConsensusRank"] = rank


IDP_RANK_LIMIT: int = 300


def _compute_idp_rankings(
    players_array: list[dict[str, Any]],
    players_by_name: dict[str, Any],
    offense_ranked_count: int,
) -> None:
    """Stamp idpRank, rankDerivedValue, and canonicalConsensusRank onto IDP players.

    IDP players have pffIdp / idpTradeCalc / fantasyProsIdp / dlfIdp / dlfRidp
    values but no KTC value, so _compute_ktc_rankings skips them entirely.
    This function ranks IDP players by the mean of their available IDP source
    values (descending), assigns idpRank 1..IDP_RANK_LIMIT, and sets
    canonicalConsensusRank = offense_ranked_count + idpRank so they sort after
    offense in a unified board but still have proper ranks.
    """
    from src.canonical.player_valuation import rank_to_value  # noqa: PLC0415

    eligible: list[tuple[float, dict[str, Any]]] = []
    for row in players_array:
        pos = str(row.get("position") or "").strip().upper()
        if pos not in _IDP_POSITIONS:
            continue
        # Already ranked by KTC? Skip (shouldn't happen, but guard)
        if row.get("ktcRank") is not None:
            continue

        csv = row.get("canonicalSiteValues") or {}
        idp_vals = [
            v for k in _IDP_SIGNAL_KEYS
            if (v := _safe_num(csv.get(k))) is not None and v > 0
        ]
        if not idp_vals:
            continue
        composite = sum(idp_vals) / len(idp_vals)
        eligible.append((composite, row))

    eligible.sort(key=lambda t: -t[0])

    for i, (_, row) in enumerate(eligible[:IDP_RANK_LIMIT]):
        idp_rank = i + 1
        global_rank = offense_ranked_count + idp_rank
        derived = int(rank_to_value(idp_rank))
        row["idpRank"] = idp_rank
        row["rankDerivedValue"] = derived
        row["canonicalConsensusRank"] = global_rank
        legacy_ref = row.get("legacyRef")
        if legacy_ref and legacy_ref in players_by_name:
            pdata = players_by_name[legacy_ref]
            if isinstance(pdata, dict):
                pdata["idpRank"] = idp_rank
                pdata["rankDerivedValue"] = derived
                pdata["_canonicalConsensusRank"] = global_rank


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
    "rookie",
    "values",
    "canonicalSiteValues",
    "sourceCount",
}

# Fields that are useful for deeper diagnostics/explanations but are not required
# for initial first-paint startup rendering in the Static runtime.
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
            out[key] = _to_int_or_none(explicit.get(key))
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
    scoring = _to_int_or_none(p_data.get("_scoringAdjusted", p_data.get("_leagueAdjusted")))
    scarcity = _to_int_or_none(p_data.get("_scarcityAdjusted"))
    final = _to_int_or_none(
        p_data.get("_finalAdjusted", p_data.get("_leagueAdjusted", p_data.get("_composite")))
    )
    if final is None:
        final = raw
    overall = final
    display = _to_int_or_none(p_data.get("_canonicalDisplayValue"))
    return {
        "overall": overall,
        "rawComposite": raw,
        "scoringAdjusted": scoring,
        "scarcityAdjusted": scarcity,
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
        "rookie": bool(p_data.get("_formatFitRookie", False)),
        "assetClass": "pick" if is_pick else ("idp" if pos in {"DL", "LB", "DB"} else "offense"),
        "values": values,
        "canonicalSiteValues": canonical_sites,
        "sourceCount": source_count,
        "sourcePresence": {k: (v is not None and v > 0) for k, v in canonical_sites.items()},
        "marketConfidence": _safe_num(p_data.get("_marketConfidence")),
        "marketDispersionCV": _safe_num(p_data.get("_marketDispersionCV")),
        "legacyRef": canonical_name,
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

    # Compute KTC-only integer ranks and rank-derived values.
    # This is the single source of truth for ktcRank / rankDerivedValue.
    # Both JS frontends prefer these fields over client-side computation.
    _compute_ktc_rankings(players_array, players_by_name)

    # Compute IDP rankings using IDP source values (pffIdp, idpTradeCalc, etc.)
    # Global rank offsets from the offense count so unified board sorts correctly.
    offense_ranked = sum(1 for r in players_array if r.get("ktcRank") is not None)
    _compute_idp_rankings(players_array, players_by_name, offense_ranked)

    data_source = data_source or {}
    contract_payload: dict[str, Any] = {
        **base,
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": utc_now_iso(),
        "playersArray": players_array,
        "playerCount": len(players_array),
        "valueAuthority": _build_value_authority_summary(players_array),
        "dataSource": {
            "type": str(data_source.get("type") or ""),
            "path": str(data_source.get("path") or ""),
            "loadedAt": str(data_source.get("loadedAt") or ""),
        },
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

    Preference order: calibrated_value > scarcity_adjusted_value > blended_value.
    This ensures shadow comparisons use the same value a consumer would see.
    """
    for key in ("calibrated_value", "scarcity_adjusted_value", "blended_value"):
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
                    or legacy_data.get("_leagueAdjusted")
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
            or pdata.get("_leagueAdjusted")
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

    Keeps the same top-level contract shape expected by the live Static app,
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
            for k in ("overall", "rawComposite", "scoringAdjusted", "scarcityAdjusted", "finalAdjusted"):
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
