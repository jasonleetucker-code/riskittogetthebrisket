from __future__ import annotations

import math
import re
from typing import Any

from src.utils import normalize_player_name, normalize_position_family

COMPOSITE_SCALE = 9999
DEFAULT_ALPHA = 1.678

TRADE_PACKAGE_BASE_DEPTH_PENALTY = 0.02
TRADE_PACKAGE_MAX_DEPTH_PENALTY = 0.14
TRADE_PACKAGE_MAX_BESTBALL_RELIEF = 0.024
TRADE_PACKAGE_MAX_STUD_PREMIUM = 0.055
TRADE_PACKAGE_MIN_MULT = 0.88
TRADE_PACKAGE_MAX_MULT = 1.08

IDP_POSITIONS = {"DL", "LB", "DB"}
PICK_NUMERIC_RE = re.compile(r"^(20\d{2})\s+(?:pick\s+)?([1-6])\.(0?[1-9]|1[0-2])$", re.IGNORECASE)
PICK_TIERED_RE = re.compile(r"^(20\d{2})\s+(early|mid|late)\s+([1-6])(st|nd|rd|th)$", re.IGNORECASE)
PICK_GENERIC_RE = re.compile(r"\b(20\d{2})\s+(pick|round)\b", re.IGNORECASE)


def _safe_float(value: Any) -> float | None:
    try:
        n = float(value)
    except Exception:
        return None
    if not math.isfinite(n):
        return None
    return n


def _safe_int(value: Any) -> int | None:
    n = _safe_float(value)
    if n is None:
        return None
    return int(round(n))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _round(value: float, digits: int = 2) -> float:
    return round(float(value), digits)


def _normalize_basis(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode == "raw":
        return "raw"
    if mode == "scoring":
        return "scoring"
    if mode == "scarcity":
        return "scarcity"
    if mode in {"bestball", "best_ball", "best-ball"}:
        return "bestBall"
    if mode == "adjusted":
        return "full"
    return "full"


def _normalize_pos(value: Any) -> str:
    p = normalize_position_family(str(value or "").strip().upper())
    if p in {"DE", "DT", "EDGE", "NT"}:
        return "DL"
    if p in {"CB", "S", "FS", "SS"}:
        return "DB"
    if p in {"OLB", "ILB"}:
        return "LB"
    return p


def _strip_parenthetical_suffix(label: str) -> str:
    out = str(label or "").strip()
    while True:
        trimmed = re.sub(r"\s*\([^)]*\)\s*$", "", out).strip()
        if trimmed == out:
            return trimmed
        out = trimmed


def _is_pick_label(label: str) -> bool:
    token = str(label or "").strip()
    if not token:
        return False
    if PICK_TIERED_RE.search(token):
        return True
    if PICK_NUMERIC_RE.search(token):
        return True
    if PICK_GENERIC_RE.search(token):
        return True
    return False


def _canonicalize_pick_label(label: str) -> str | None:
    token = str(label or "").strip()
    if not token:
        return None
    tiered = PICK_TIERED_RE.match(token)
    if tiered:
        year, tier, rnd, suffix = tiered.groups()
        return f"{year} {tier.title()} {rnd}{suffix.lower()}"
    numeric = PICK_NUMERIC_RE.match(token)
    if numeric:
        year, rnd, pick = numeric.groups()
        return f"{year} Pick {int(rnd)}.{int(pick):02d}"
    return None


def _candidate_labels(label: str) -> list[str]:
    base = str(label or "").strip()
    if not base:
        return []
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str | None) -> None:
        token = str(value or "").strip()
        if not token:
            return
        key = token.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(token)

    stripped = _strip_parenthetical_suffix(base)
    add(base)
    add(stripped)
    add(_canonicalize_pick_label(base))
    add(_canonicalize_pick_label(stripped))
    return candidates


def _bundle_value_for_basis(bundle: dict[str, Any], basis: str) -> tuple[int | None, str]:
    raw = _safe_int(bundle.get("rawValue"))
    scoring = _safe_int(bundle.get("scoringAdjustedValue")) or raw
    scarcity = _safe_int(bundle.get("scarcityAdjustedValue")) or scoring
    best_ball = _safe_int(bundle.get("bestBallAdjustedValue")) or scarcity
    full = _safe_int(bundle.get("fullValue"))
    guardrails = bundle.get("guardrails") if isinstance(bundle.get("guardrails"), dict) else {}
    quarantined = bool(guardrails.get("quarantined"))

    if basis == "raw":
        return raw, "rawValue"
    if basis == "scoring":
        return scoring, "scoringAdjustedValue"
    if basis == "scarcity":
        return scarcity, "scarcityAdjustedValue"
    if basis == "bestBall":
        return best_ball, "bestBallAdjustedValue"
    if quarantined:
        return None, "fullValue_quarantined"
    return (full or best_ball or scarcity or scoring or raw), (
        "fullValue" if full is not None else "fullValue_derived_fallback"
    )


def _best_ball_lift_from_bundle(bundle: dict[str, Any]) -> float:
    layers = bundle.get("layers") if isinstance(bundle.get("layers"), dict) else {}
    best_ball_layer = layers.get("bestBall") if isinstance(layers.get("bestBall"), dict) else {}
    pct = _safe_float(best_ball_layer.get("deltaPctFromScarcity"))
    if pct is not None:
        return _clamp(pct, -0.18, 0.18)

    best_ball = _safe_float(bundle.get("bestBallAdjustedValue"))
    scarcity = _safe_float(bundle.get("scarcityAdjustedValue"))
    if best_ball is not None and scarcity is not None and scarcity > 0:
        return _clamp((best_ball / scarcity) - 1.0, -0.18, 0.18)
    return 0.0


def _resolve_confidence(entry: dict[str, Any]) -> float:
    candidates = (
        entry.get("confidence"),
        entry.get("marketReliabilityScore"),
        (entry.get("marketReliability") or {}).get("score")
        if isinstance(entry.get("marketReliability"), dict)
        else None,
        entry.get("marketConfidence"),
    )
    for raw in candidates:
        n = _safe_float(raw)
        if n is not None:
            return _clamp(n, 0.20, 0.95)
    return 0.55


def _resolve_best_ball_lift(entry: dict[str, Any]) -> float:
    candidates = (
        entry.get("bestBallLift"),
        entry.get("best_ball_lift"),
        entry.get("bestBallDelta"),
        entry.get("_bestBallDelta"),
    )
    for raw in candidates:
        n = _safe_float(raw)
        if n is not None:
            return _clamp(n, -0.18, 0.18)
    best_ball = _safe_float(entry.get("bestBallAdjustedValue"))
    scarcity = _safe_float(entry.get("scarcityAdjustedValue"))
    if best_ball is not None and scarcity is not None and scarcity > 0:
        return _clamp((best_ball / scarcity) - 1.0, -0.18, 0.18)
    return 0.0


def _normalize_entry(raw_entry: dict[str, Any]) -> dict[str, Any] | None:
    value = _safe_float(
        raw_entry.get("value")
        if raw_entry.get("value") is not None
        else raw_entry.get("metaValue")
    )
    if value is None or value <= 0:
        return None
    value = _clamp(value, 1, COMPOSITE_SCALE)

    is_pick = bool(raw_entry.get("isPick")) or str(raw_entry.get("assetClass") or "").lower() == "pick"
    pos = _normalize_pos(raw_entry.get("pos") or raw_entry.get("position"))
    if is_pick:
        pos = "PICK"
    is_idp = bool(raw_entry.get("isIdp")) or (not is_pick and pos in IDP_POSITIONS)
    is_rookie = bool(raw_entry.get("isRookie"))

    asset_class = str(raw_entry.get("assetClass") or "").strip().lower()
    if not asset_class:
        asset_class = "pick" if is_pick else ("idp" if is_idp else "offense")

    return {
        "name": str(raw_entry.get("name") or raw_entry.get("label") or "").strip(),
        "value": float(value),
        "pos": pos,
        "isPick": is_pick,
        "isIdp": is_idp,
        "isRookie": is_rookie,
        "assetClass": asset_class,
        "confidence": _resolve_confidence(raw_entry),
        "bestBallLift": _resolve_best_ball_lift(raw_entry),
        "resolution": str(raw_entry.get("resolution") or ""),
    }


def _compute_package_score(entries: list[dict[str, Any]], alpha: float, best_ball_mode: bool) -> dict[str, Any]:
    alpha = _clamp(alpha, 1.0, 3.0)
    normalized: list[dict[str, Any]] = []
    for raw in entries:
        entry = _normalize_entry(raw)
        if not entry:
            continue
        normalized.append(entry)
    normalized.sort(key=lambda e: e["value"], reverse=True)

    if not normalized:
        return {
            "weightedBase": 0.0,
            "linearTotal": 0.0,
            "weightedTotal": 0.0,
            "packageMultiplier": 1.0,
            "packageDeltaPct": 0.0,
            "assetCount": 0,
            "components": {},
            "entryEffects": [],
        }

    weighted_base = sum(math.pow(max(1.0, e["value"]), alpha) for e in normalized)
    linear_total = sum(max(1.0, e["value"]) for e in normalized)
    n = len(normalized)
    extras = max(0, n - 1)
    pick_count = sum(1 for e in normalized if e["isPick"] or e["assetClass"] == "pick")
    idp_count = sum(1 for e in normalized if e["isIdp"] or e["assetClass"] == "idp")
    rookie_count = sum(1 for e in normalized if e["isRookie"])
    top = normalized[0]
    second = normalized[1] if n > 1 else None
    top_share = _clamp(top["value"] / max(1.0, linear_total), 0.0, 1.0)
    tier_gap = _clamp(
        ((top["value"] - second["value"]) / max(1.0, top["value"])) if second else 1.0,
        0.0,
        1.0,
    )

    if top["assetClass"] == "idp":
        elite_pivot = 4300.0
        elite_range = 2400.0
    elif top["assetClass"] == "pick":
        elite_pivot = 5200.0
        elite_range = 2200.0
    elif top["pos"] == "QB":
        elite_pivot = 6800.0
        elite_range = 2600.0
    else:
        elite_pivot = 6200.0
        elite_range = 2600.0

    elite_norm = _clamp((top["value"] - elite_pivot) / max(1.0, elite_range), 0.0, 1.0)
    alpha_strength = _clamp((alpha - 1.0) / 0.85, 0.0, 1.35)

    pos_factor = 1.0
    if top["pos"] == "QB":
        pos_factor += 0.1
    elif top["pos"] == "TE":
        pos_factor += 0.03
    if top["assetClass"] == "idp":
        pos_factor *= 0.82
    if top["assetClass"] == "pick":
        pos_factor *= 0.78
    if top["isRookie"]:
        pos_factor *= 0.95

    stud_premium = TRADE_PACKAGE_MAX_STUD_PREMIUM * elite_norm * pos_factor * alpha_strength
    concentration = (
        1.0
        if n == 1
        else _clamp(0.4 + (0.45 * top_share) + (0.35 * tier_gap), 0.3, 1.0)
    )
    stud_premium *= concentration

    depth_rate = TRADE_PACKAGE_BASE_DEPTH_PENALTY
    if pick_count > 0:
        depth_rate += 0.003
    if idp_count == n:
        depth_rate -= 0.003
    depth_rate = _clamp(depth_rate, 0.012, 0.03)

    depth_penalty = min(TRADE_PACKAGE_MAX_DEPTH_PENALTY, extras * depth_rate)
    tier_relief = depth_penalty * _clamp((0.55 * tier_gap) + (0.35 * max(0.0, top_share - 0.5)), 0.0, 0.8)
    flat_penalty = (extras * 0.006 * _clamp(1.0 - tier_gap, 0.0, 1.0)) if extras > 0 else 0.0
    pick_penalty = ((pick_count - 1) * 0.0045) if pick_count > 1 else 0.0
    rookie_penalty = ((rookie_count - 1) * 0.0035) if rookie_count > 1 else 0.0
    idp_penalty = (extras * 0.002) if (idp_count > 1 and idp_count == n) else 0.0

    if normalized:
        avg_best_ball_lift = (
            sum(max(0.0, float(e["bestBallLift"])) * float(e["confidence"]) for e in normalized)
            / len(normalized)
        )
    else:
        avg_best_ball_lift = 0.0
    best_ball_depth_relief = (
        _clamp((extras * 0.004) + (avg_best_ball_lift * 0.35), 0.0, TRADE_PACKAGE_MAX_BESTBALL_RELIEF)
        if best_ball_mode and extras > 0
        else 0.0
    )

    raw_package_delta = (
        stud_premium
        - depth_penalty
        + tier_relief
        - flat_penalty
        - pick_penalty
        - rookie_penalty
        - idp_penalty
        + best_ball_depth_relief
    )
    bounded_package_delta = _clamp(
        raw_package_delta,
        TRADE_PACKAGE_MIN_MULT - 1.0,
        TRADE_PACKAGE_MAX_MULT - 1.0,
    )
    package_multiplier = _clamp(
        1.0 + bounded_package_delta,
        TRADE_PACKAGE_MIN_MULT,
        TRADE_PACKAGE_MAX_MULT,
    )
    weighted_total = weighted_base * package_multiplier
    penalty_pool = max(
        0.0,
        depth_penalty
        - tier_relief
        + flat_penalty
        + pick_penalty
        + rookie_penalty
        + idp_penalty
        - best_ball_depth_relief,
    )

    entry_effects: list[dict[str, Any]] = []
    for idx, entry in enumerate(normalized):
        power = math.pow(max(1.0, entry["value"]), alpha)
        share = power / max(1.0, weighted_base)
        stud_leverage = _clamp(0.85 if idx == 0 else (0.25 + (share * 0.55)), 0.05, 1.25)
        depth_exposure = _clamp((1.0 - share) * (1.0 if extras > 0 else 0.4), 0.0, 1.2)
        entry_delta = (stud_premium * stud_leverage) - (penalty_pool * depth_exposure)
        if best_ball_mode and extras > 0:
            entry_delta += best_ball_depth_relief + (0.45 * max(0.0, float(entry["bestBallLift"])))
        entry_delta = _clamp(entry_delta, -0.08, 0.08)
        entry_effects.append(
            {
                "name": entry["name"],
                "pos": entry["pos"],
                "assetClass": entry["assetClass"],
                "value": int(round(entry["value"])),
                "deltaPct": _round(entry_delta * 100.0, 2),
                "weightedImpact": _round(power * entry_delta, 2),
                "resolution": entry.get("resolution") or "",
            }
        )

    abs_delta_pct = abs((package_multiplier - 1.0) * 100.0)
    if abs_delta_pct >= 5.5:
        curve_profile = "steep"
    elif abs_delta_pct <= 1.2:
        curve_profile = "flat"
    else:
        curve_profile = "balanced"

    return {
        "weightedBase": float(weighted_base),
        "linearTotal": float(linear_total),
        "weightedTotal": float(weighted_total),
        "packageMultiplier": float(package_multiplier),
        "packageDeltaPct": float((package_multiplier - 1.0) * 100.0),
        "assetCount": int(n),
        "components": {
            "studPremium": float(stud_premium),
            "depthPenalty": float(depth_penalty),
            "tierGapRelief": float(tier_relief),
            "flatPackagePenalty": float(flat_penalty),
            "pickBundlePenalty": float(pick_penalty),
            "rookieBundlePenalty": float(rookie_penalty),
            "idpBundlePenalty": float(idp_penalty),
            "bestBallDepthRelief": float(best_ball_depth_relief),
            "rawPackageDelta": float(raw_package_delta),
            "boundedPackageDelta": float(bounded_package_delta),
            "curveProfile": curve_profile,
        },
        "entryEffects": entry_effects,
    }


def _build_row_indexes(contract_payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    exact: dict[str, dict[str, Any]] = {}
    normalized: dict[str, list[dict[str, Any]]] = {}

    def add_row(row: dict[str, Any]) -> None:
        if not isinstance(row, dict):
            return
        name = str(row.get("canonicalName") or row.get("displayName") or "").strip()
        if not name:
            return
        if name not in exact:
            exact[name] = row
        norm = normalize_player_name(name)
        if not norm:
            return
        bucket = normalized.setdefault(norm, [])
        bucket.append(row)

    players_array = contract_payload.get("playersArray")
    if isinstance(players_array, list):
        for row in players_array:
            add_row(row if isinstance(row, dict) else {})

    players_map = contract_payload.get("players")
    if isinstance(players_map, dict):
        for name, pdata in players_map.items():
            canonical = str(name or "").strip()
            if not canonical or canonical in exact:
                continue
            pdata_dict = pdata if isinstance(pdata, dict) else {}
            pseudo_row = {
                "canonicalName": canonical,
                "displayName": canonical,
                "position": pdata_dict.get("position"),
                "rookie": bool(pdata_dict.get("rookie") or pdata_dict.get("_isRookie")),
                "valueBundle": pdata_dict.get("valueBundle"),
            }
            add_row(pseudo_row)
    return exact, normalized


def _resolve_row(
    label: str,
    exact: dict[str, dict[str, Any]],
    normalized: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, str]:
    for candidate in _candidate_labels(label):
        row = exact.get(candidate)
        if row is not None:
            return row, "exact"
    for candidate in _candidate_labels(label):
        norm = normalize_player_name(candidate)
        if not norm:
            continue
        rows = normalized.get(norm) or []
        if len(rows) == 1:
            return rows[0], "normalized_unique"
        if len(rows) > 1:
            return None, "normalized_ambiguous"
    return None, "unresolved"


def _build_fallback_entry(item: dict[str, Any], label: str) -> dict[str, Any] | None:
    fallback_value = _safe_float(item.get("fallbackValue") if item.get("fallbackValue") is not None else item.get("value"))
    if fallback_value is None or fallback_value <= 0:
        return None
    is_pick = bool(item.get("isPick")) or _is_pick_label(label)
    pos = _normalize_pos(item.get("pos") or item.get("fallbackPos"))
    if is_pick:
        pos = "PICK"
    is_idp = bool(item.get("isIdp")) or (not is_pick and pos in IDP_POSITIONS)
    asset_class = str(item.get("assetClass") or "").strip().lower()
    if not asset_class:
        asset_class = "pick" if is_pick else ("idp" if is_idp else "offense")
    return {
        "name": label,
        "value": _clamp(fallback_value, 1, COMPOSITE_SCALE),
        "pos": pos,
        "isPick": is_pick,
        "isIdp": is_idp,
        "isRookie": bool(item.get("isRookie")),
        "assetClass": asset_class,
        "confidence": _resolve_confidence(item),
        "bestBallLift": _resolve_best_ball_lift(item),
    }


def score_trade_payload(
    *,
    contract_payload: dict[str, Any],
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    basis = _normalize_basis(request_payload.get("valueBasis"))
    alpha = _safe_float(request_payload.get("alpha"))
    alpha = _clamp(alpha if alpha is not None else DEFAULT_ALPHA, 1.0, 3.0)
    best_ball_mode = bool(request_payload.get("bestBallMode", True))

    exact, normalized = _build_row_indexes(contract_payload)
    sides_in = request_payload.get("sides") if isinstance(request_payload.get("sides"), dict) else {}
    sides_out: dict[str, Any] = {}
    summary = {
        "inputItems": 0,
        "backendResolved": 0,
        "fallbackUsed": 0,
        "quarantinedExcluded": 0,
        "unresolvedExcluded": 0,
    }

    for side in ("A", "B", "C"):
        raw_items = sides_in.get(side)
        items = raw_items if isinstance(raw_items, list) else []
        summary["inputItems"] += len(items)
        resolved_entries: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        side_counts = {
            "inputCount": len(items),
            "backendResolved": 0,
            "fallbackUsed": 0,
            "quarantinedExcluded": 0,
            "unresolvedExcluded": 0,
        }

        for raw_item in items:
            item = raw_item if isinstance(raw_item, dict) else {}
            label = str(item.get("label") or item.get("name") or "").strip()
            if not label:
                continue
            manual_override = bool(item.get("manualOverride"))

            if manual_override:
                fallback_entry = _build_fallback_entry(item, label)
                if fallback_entry:
                    fallback_entry["resolution"] = "fallback_manual_override"
                    resolved_entries.append(fallback_entry)
                    side_counts["fallbackUsed"] += 1
                    summary["fallbackUsed"] += 1
                else:
                    unresolved.append({"label": label, "reason": "manual_override_without_fallback_value"})
                    side_counts["unresolvedExcluded"] += 1
                    summary["unresolvedExcluded"] += 1
                continue

            row, resolution_method = _resolve_row(label, exact, normalized)
            if row is None:
                fallback_entry = _build_fallback_entry(item, label)
                if fallback_entry:
                    fallback_entry["resolution"] = f"fallback_{resolution_method}"
                    resolved_entries.append(fallback_entry)
                    side_counts["fallbackUsed"] += 1
                    summary["fallbackUsed"] += 1
                else:
                    unresolved.append({"label": label, "reason": f"unresolved_{resolution_method}"})
                    side_counts["unresolvedExcluded"] += 1
                    summary["unresolvedExcluded"] += 1
                continue

            bundle = row.get("valueBundle") if isinstance(row.get("valueBundle"), dict) else {}
            guardrails = bundle.get("guardrails") if isinstance(bundle.get("guardrails"), dict) else {}
            is_quarantined = bool(guardrails.get("quarantined"))
            pos = _normalize_pos(row.get("position"))
            canonical_name = str(row.get("canonicalName") or row.get("displayName") or label).strip() or label
            is_pick = pos == "PICK" or _is_pick_label(canonical_name)
            if is_pick:
                pos = "PICK"

            if is_quarantined and not is_pick:
                unresolved.append(
                    {
                        "label": label,
                        "canonicalName": canonical_name,
                        "reason": "quarantined_from_final_authority",
                        "quarantineReasons": list(guardrails.get("quarantineReasons") or []),
                    }
                )
                side_counts["quarantinedExcluded"] += 1
                summary["quarantinedExcluded"] += 1
                continue

            basis_value, value_source = _bundle_value_for_basis(bundle, basis)
            if basis_value is None or basis_value <= 0:
                fallback_entry = _build_fallback_entry(item, label)
                if fallback_entry:
                    fallback_entry["resolution"] = "fallback_missing_bundle_value"
                    resolved_entries.append(fallback_entry)
                    side_counts["fallbackUsed"] += 1
                    summary["fallbackUsed"] += 1
                else:
                    unresolved.append(
                        {
                            "label": label,
                            "canonicalName": canonical_name,
                            "reason": f"missing_basis_value_{basis}",
                        }
                    )
                    side_counts["unresolvedExcluded"] += 1
                    summary["unresolvedExcluded"] += 1
                continue

            is_idp = pos in IDP_POSITIONS
            asset_class = "pick" if is_pick else ("idp" if is_idp else "offense")
            confidence = _safe_float(bundle.get("confidence"))
            source_coverage = bundle.get("sourceCoverage") if isinstance(bundle.get("sourceCoverage"), dict) else {}
            if confidence is None:
                ratio = _safe_float(source_coverage.get("ratio"))
                confidence = _clamp(0.3 + (0.55 * ratio), 0.20, 0.95) if ratio is not None else 0.55

            resolved_entries.append(
                {
                    "name": canonical_name,
                    "value": int(_clamp(float(basis_value), 1, COMPOSITE_SCALE)),
                    "pos": pos,
                    "isPick": is_pick,
                    "isIdp": is_idp,
                    "isRookie": bool(row.get("rookie")),
                    "assetClass": asset_class,
                    "confidence": _clamp(float(confidence), 0.20, 0.95),
                    "bestBallLift": _best_ball_lift_from_bundle(bundle),
                    "resolution": f"backend_value_bundle:{resolution_method}",
                    "source": value_source,
                    "label": label,
                    "canonicalName": canonical_name,
                }
            )
            side_counts["backendResolved"] += 1
            summary["backendResolved"] += 1

        side_score = _compute_package_score(resolved_entries, alpha, best_ball_mode)
        sides_out[side] = {
            **side_score,
            "authority": "backend_trade_scoring_v1",
            "resolution": {
                **side_counts,
                "resolvedCount": len(resolved_entries),
                "unresolvedCount": len(unresolved),
            },
            "resolvedEntries": resolved_entries,
            "unresolvedEntries": unresolved,
        }

    return {
        "ok": True,
        "authority": "backend_trade_scoring_v1",
        "valueBasis": basis,
        "alpha": alpha,
        "bestBallMode": best_ball_mode,
        "sides": sides_out,
        "summary": summary,
    }
