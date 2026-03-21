from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _to_num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except Exception:
        return None
    if not math.isfinite(number):
        return None
    return number


def _to_int(value: Any, default: int = 0) -> int:
    number = _to_num(value)
    if number is None:
        return int(default)
    return int(round(number))


def _safe_ratio(numer: int, denom: int) -> float:
    if denom <= 0:
        return 0.0
    return float(numer) / float(denom)


IDP_SITE_KEYS = {"idpTradeCalc", "pffIdp", "fantasyProsIdp", "dlfIdp", "dlfRidp"}
OFFENSE_SITE_KEYS = {
    "ktc",
    "fantasyCalc",
    "dynastyDaddy",
    "fantasyPros",
    "draftSharks",
    "yahoo",
    "dynastyNerds",
    "dlfSf",
    "dlfRsf",
}
SITE_METADATA_AGGREGATE_ALIASES = {
    "DLF": {"dlfSf", "dlfRsf", "dlfIdp", "dlfRidp"},
}


def _row_impact_score(row: dict[str, Any]) -> int:
    values = row.get("values")
    if not isinstance(values, dict):
        return 0
    for key in ("overall", "finalAdjusted", "bestBallAdjusted", "rawComposite"):
        val = _to_num(values.get(key))
        if val is not None and val > 0:
            return int(round(val))
    return 0


def _args_from_cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate /api/data contract against latest payload.")
    parser.add_argument("--repo", default=".", help="Repository root (default: current directory)")
    parser.add_argument(
        "--strict-semantic",
        action="store_true",
        help="Fail when semantic integrity checks report degraded/critical status.",
    )
    return parser.parse_args()


def _load_latest_payload(repo_root: Path) -> tuple[dict, Path]:
    candidates: list[Path] = []
    for folder in (repo_root / "data", repo_root):
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.glob("dynasty_data_*.json")))
    if not candidates:
        raise FileNotFoundError("No dynasty_data_YYYY-MM-DD.json files found in repo/data or repo root.")
    latest = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    with latest.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload, latest


def _semantic_integrity_report(contract_payload: dict[str, Any]) -> dict[str, Any]:
    rows_raw = contract_payload.get("playersArray")
    rows = rows_raw if isinstance(rows_raw, list) else []
    sites_raw = contract_payload.get("sites")
    sites = sites_raw if isinstance(sites_raw, list) else []
    players_map_raw = contract_payload.get("players")
    players_map = players_map_raw if isinstance(players_map_raw, dict) else {}

    total_rows = 0
    blank_position_count = 0
    blank_non_pick_position_count = 0
    source_count_without_positive_sites = 0
    single_source_count = 0
    low_confidence_count = 0
    low_confidence_actionable_count = 0
    low_confidence_non_actionable_count = 0
    positive_site_counts: dict[str, int] = {}
    blank_position_causes: dict[str, int] = {}
    source_mismatch_causes: dict[str, int] = {}
    low_confidence_by_asset_class: dict[str, int] = {}
    low_confidence_by_source_count: dict[str, int] = {}
    blank_position_samples: list[dict[str, Any]] = []
    source_mismatch_samples: list[dict[str, Any]] = []
    low_confidence_actionable_samples: list[dict[str, Any]] = []
    low_confidence_non_actionable_samples: list[dict[str, Any]] = []

    fallback_counts = {
        "scoring": 0,
        "scarcity": 0,
    }
    layer_source_breakdown: dict[str, dict[str, int]] = {
        "scoring": {},
        "scarcity": {},
    }

    for row in rows:
        if not isinstance(row, dict):
            continue
        total_rows += 1

        position = str(row.get("position") or "").strip().upper()
        asset_class = str(row.get("assetClass") or "").strip().lower()
        if not position:
            blank_position_count += 1
            if asset_class != "pick":
                blank_non_pick_position_count += 1

        source_count = max(0, _to_int(row.get("sourceCount"), default=0))
        if source_count == 1:
            single_source_count += 1

        row_name = str(
            row.get("canonicalName")
            or row.get("displayName")
            or row.get("legacyRef")
            or ""
        ).strip()
        player_payload = players_map.get(row_name) if isinstance(players_map.get(row_name), dict) else {}
        fallback_value = bool(player_payload.get("_fallbackValue"))
        fallback_reason = str(player_payload.get("_fallbackReason") or "").strip()

        canonical_site_values = row.get("canonicalSiteValues")
        positive_sites_for_row = 0
        has_idp_signal = False
        has_offense_signal = False
        if isinstance(canonical_site_values, dict):
            for key, value in canonical_site_values.items():
                val_num = _to_num(value)
                if val_num is None or val_num <= 0:
                    continue
                positive_sites_for_row += 1
                key_s = str(key)
                positive_site_counts[key_s] = int(positive_site_counts.get(key_s, 0)) + 1
                if key_s in IDP_SITE_KEYS:
                    has_idp_signal = True
                if key_s in OFFENSE_SITE_KEYS:
                    has_offense_signal = True

        row_impact = _row_impact_score(row)

        if source_count > 0 and positive_sites_for_row == 0:
            source_count_without_positive_sites += 1
            if fallback_value:
                mismatch_cause = "fallback_value_with_no_positive_canonical_sites"
            elif source_count == 1:
                mismatch_cause = "single_source_without_positive_canonical_sites"
            else:
                mismatch_cause = "multi_source_without_positive_canonical_sites"
            source_mismatch_causes[mismatch_cause] = int(source_mismatch_causes.get(mismatch_cause, 0)) + 1
            source_mismatch_samples.append(
                {
                    "name": row_name,
                    "assetClass": asset_class,
                    "position": position or None,
                    "sourceCount": source_count,
                    "fallbackValue": fallback_value,
                    "fallbackReason": fallback_reason or None,
                    "impactScore": row_impact,
                    "cause": mismatch_cause,
                }
            )

        if not position and asset_class != "pick":
            if has_idp_signal and not has_offense_signal:
                blank_cause = "idp_signal_missing_position"
            elif has_offense_signal and not has_idp_signal:
                blank_cause = "offense_signal_missing_position"
            elif has_idp_signal and has_offense_signal:
                blank_cause = "mixed_signal_missing_position"
            else:
                blank_cause = "no_market_signal_missing_position"
            blank_position_causes[blank_cause] = int(blank_position_causes.get(blank_cause, 0)) + 1
            blank_position_samples.append(
                {
                    "name": row_name,
                    "assetClass": asset_class,
                    "sourceCount": source_count,
                    "fallbackValue": fallback_value,
                    "fallbackReason": fallback_reason or None,
                    "hasIdpSignal": bool(has_idp_signal),
                    "hasOffenseSignal": bool(has_offense_signal),
                    "impactScore": row_impact,
                    "cause": blank_cause,
                }
            )

        value_bundle = row.get("valueBundle")
        if not isinstance(value_bundle, dict):
            continue
        confidence = _to_num(value_bundle.get("confidence"))
        if confidence is not None and confidence < 0.50:
            low_confidence_count += 1
            low_confidence_by_asset_class[asset_class] = int(
                low_confidence_by_asset_class.get(asset_class, 0)
            ) + 1
            source_count_key = str(source_count)
            low_confidence_by_source_count[source_count_key] = int(
                low_confidence_by_source_count.get(source_count_key, 0)
            ) + 1
            guardrails = row.get("valueGuardrails")
            guardrails = guardrails if isinstance(guardrails, dict) else {}
            quarantined = bool(guardrails.get("quarantined"))
            confidence_sample = {
                "name": row_name,
                "assetClass": asset_class,
                "position": position or None,
                "sourceCount": source_count,
                "confidence": round(float(confidence), 4),
                "quarantined": quarantined,
                "fallbackValue": fallback_value,
                "impactScore": row_impact,
            }
            if asset_class != "pick" and not quarantined:
                low_confidence_actionable_count += 1
                low_confidence_actionable_samples.append(confidence_sample)
            else:
                low_confidence_non_actionable_count += 1
                low_confidence_non_actionable_samples.append(confidence_sample)

        layers = value_bundle.get("layers")
        if not isinstance(layers, dict):
            continue
        for layer_key in ("scoring", "scarcity"):
            layer = layers.get(layer_key)
            if not isinstance(layer, dict):
                continue
            source = str(layer.get("source") or "").strip()
            if source:
                source_map = layer_source_breakdown[layer_key]
                source_map[source] = int(source_map.get(source, 0)) + 1
            if source.startswith("fallback_") or source.endswith("_fallback"):
                fallback_counts[layer_key] += 1

    site_metadata_anomalies: list[dict[str, Any]] = []
    for site in sites:
        if not isinstance(site, dict):
            continue
        key = str(site.get("key") or "").strip()
        if not key:
            continue
        player_count = max(0, _to_int(site.get("playerCount"), default=0))
        positive_count = int(positive_site_counts.get(key, 0))
        if key in SITE_METADATA_AGGREGATE_ALIASES:
            positive_count = 0
            for alias in SITE_METADATA_AGGREGATE_ALIASES[key]:
                positive_count += int(positive_site_counts.get(alias, 0))
        if player_count > 0 and positive_count == 0:
            site_metadata_anomalies.append(
                {
                    "site": key,
                    "sitePlayerCount": player_count,
                    "positiveCanonicalSiteValueRows": positive_count,
                }
            )

    blank_non_pick_ratio = _safe_ratio(blank_non_pick_position_count, total_rows)
    source_mismatch_ratio = _safe_ratio(source_count_without_positive_sites, total_rows)
    scoring_fallback_ratio = _safe_ratio(fallback_counts["scoring"], total_rows)
    scarcity_fallback_ratio = _safe_ratio(fallback_counts["scarcity"], total_rows)
    low_confidence_ratio = _safe_ratio(low_confidence_count, total_rows)
    low_confidence_actionable_ratio = _safe_ratio(low_confidence_actionable_count, total_rows)
    single_source_ratio = _safe_ratio(single_source_count, total_rows)

    blank_position_samples = sorted(
        blank_position_samples,
        key=lambda row: (-int(row.get("impactScore", 0) or 0), str(row.get("name") or "")),
    )
    source_mismatch_samples = sorted(
        source_mismatch_samples,
        key=lambda row: (-int(row.get("impactScore", 0) or 0), str(row.get("name") or "")),
    )
    low_confidence_actionable_samples = sorted(
        low_confidence_actionable_samples,
        key=lambda row: (-int(row.get("impactScore", 0) or 0), str(row.get("name") or "")),
    )
    low_confidence_non_actionable_samples = sorted(
        low_confidence_non_actionable_samples,
        key=lambda row: (-int(row.get("impactScore", 0) or 0), str(row.get("name") or "")),
    )

    warnings: list[str] = []
    if blank_non_pick_position_count > 0:
        warnings.append(
            "blank positions detected "
            f"(non-pick={blank_non_pick_position_count}, totalBlank={blank_position_count})."
        )
    if source_count_without_positive_sites > 0:
        warnings.append(
            "source-count mismatch detected "
            f"({source_count_without_positive_sites} rows have sourceCount > 0 with no positive canonical site values)."
        )
    if scoring_fallback_ratio >= 0.50:
        warnings.append(
            "scoring layer fallback rate is high "
            f"({fallback_counts['scoring']}/{total_rows}, {scoring_fallback_ratio:.1%})."
        )
    if scarcity_fallback_ratio >= 0.50:
        warnings.append(
            "scarcity layer fallback rate is high "
            f"({fallback_counts['scarcity']}/{total_rows}, {scarcity_fallback_ratio:.1%})."
        )
    if low_confidence_actionable_ratio >= 0.30:
        warnings.append(
            "actionable low-confidence asset ratio is high "
            f"({low_confidence_actionable_count}/{total_rows}, {low_confidence_actionable_ratio:.1%})."
        )
    if single_source_ratio >= 0.25:
        warnings.append(
            "single-source asset ratio is high "
            f"({single_source_count}/{total_rows}, {single_source_ratio:.1%})."
        )
    if site_metadata_anomalies:
        preview = ", ".join(row["site"] for row in site_metadata_anomalies[:8])
        warnings.append(
            "site metadata anomalies detected (site playerCount > 0 but no positive canonical values): "
            f"{preview}"
        )

    critical_reasons: list[str] = []
    if blank_non_pick_ratio >= 0.15:
        critical_reasons.append(f"blank_non_pick_ratio={blank_non_pick_ratio:.1%}")
    if source_mismatch_ratio >= 0.10:
        critical_reasons.append(f"source_mismatch_ratio={source_mismatch_ratio:.1%}")
    if scoring_fallback_ratio >= 0.95:
        critical_reasons.append(f"scoring_fallback_ratio={scoring_fallback_ratio:.1%}")
    if scarcity_fallback_ratio >= 0.95:
        critical_reasons.append(f"scarcity_fallback_ratio={scarcity_fallback_ratio:.1%}")
    if low_confidence_actionable_ratio >= 0.45:
        critical_reasons.append(
            f"low_confidence_actionable_ratio={low_confidence_actionable_ratio:.1%}"
        )

    if critical_reasons:
        status = "critical"
    elif warnings:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "status": status,
        "warnings": warnings,
        "criticalReasons": critical_reasons,
        "metrics": {
            "totalRows": total_rows,
            "blankPositionCount": blank_position_count,
            "blankNonPickPositionCount": blank_non_pick_position_count,
            "sourceCountWithoutPositiveCanonicalSites": source_count_without_positive_sites,
            "singleSourceCount": single_source_count,
            "lowConfidenceCount": low_confidence_count,
            "lowConfidenceActionableCount": low_confidence_actionable_count,
            "lowConfidenceNonActionableCount": low_confidence_non_actionable_count,
            "blankNonPickPositionRatio": round(blank_non_pick_ratio, 6),
            "sourceMismatchRatio": round(source_mismatch_ratio, 6),
            "scoringFallbackRatio": round(scoring_fallback_ratio, 6),
            "scarcityFallbackRatio": round(scarcity_fallback_ratio, 6),
            "singleSourceRatio": round(single_source_ratio, 6),
            "lowConfidenceRatio": round(low_confidence_ratio, 6),
            "lowConfidenceActionableRatio": round(low_confidence_actionable_ratio, 6),
        },
        "layerFallbackCounts": fallback_counts,
        "layerSourceBreakdown": layer_source_breakdown,
        "rootCauses": {
            "blankNonPickPosition": {
                "counts": dict(
                    sorted(blank_position_causes.items(), key=lambda kv: (-int(kv[1]), kv[0]))
                ),
                "topSamples": blank_position_samples[:40],
            },
            "sourceCountWithoutPositiveCanonicalSites": {
                "counts": dict(
                    sorted(source_mismatch_causes.items(), key=lambda kv: (-int(kv[1]), kv[0]))
                ),
                "topSamples": source_mismatch_samples[:40],
            },
            "lowConfidence": {
                "countsByAssetClass": dict(
                    sorted(low_confidence_by_asset_class.items(), key=lambda kv: (-int(kv[1]), kv[0]))
                ),
                "countsBySourceCount": dict(
                    sorted(
                        low_confidence_by_source_count.items(),
                        key=lambda kv: (int(kv[0]), kv[0]) if str(kv[0]).isdigit() else (9999, kv[0]),
                    )
                ),
                "actionableCount": int(low_confidence_actionable_count),
                "nonActionableCount": int(low_confidence_non_actionable_count),
                "topActionableSamples": low_confidence_actionable_samples[:40],
                "topNonActionableSamples": low_confidence_non_actionable_samples[:20],
            },
        },
        "siteMetadataAnomalies": site_metadata_anomalies[:30],
    }


def main() -> int:
    args = _args_from_cli()
    repo_root = Path(args.repo).resolve()
    sys.path.insert(0, str(repo_root))

    from src.api.data_contract import (  # noqa: WPS433 - intentional runtime import from repo root
        CONTRACT_VERSION,
        build_api_data_contract,
        validate_api_data_contract,
    )

    payload, source_file = _load_latest_payload(repo_root)
    contract_payload = build_api_data_contract(
        payload,
        data_source={
            "type": "ci_file",
            "path": str(source_file),
            "loadedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    report = validate_api_data_contract(contract_payload)
    semantic_report = _semantic_integrity_report(contract_payload)

    validation_dir = repo_root / "data" / "validation"
    validation_dir.mkdir(parents=True, exist_ok=True)
    out_path = validation_dir / "api_contract_validation_latest.json"
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "contractVersion": CONTRACT_VERSION,
                "sourceFile": str(source_file),
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "report": report,
                "semanticReport": semantic_report,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"[contract] source={source_file}")
    print(
        f"[contract] ok={report.get('ok')} errors={report.get('errorCount')} "
        f"warnings={report.get('warningCount')} players={report.get('playerCount')}"
    )
    if report.get("warnings"):
        for msg in report["warnings"][:8]:
            print(f"[contract][warn] {msg}")
    print(
        f"[semantic] status={semantic_report.get('status')} warnings={len(semantic_report.get('warnings') or [])}"
    )
    metrics = semantic_report.get("metrics") or {}
    print(
        "[semantic] "
        f"blankNonPickPositions={metrics.get('blankNonPickPositionCount')} "
        f"sourceCountNoPositiveSites={metrics.get('sourceCountWithoutPositiveCanonicalSites')} "
        f"lowConfidenceActionable={metrics.get('lowConfidenceActionableCount')} "
        f"scoringFallbackRatio={metrics.get('scoringFallbackRatio')} "
        f"scarcityFallbackRatio={metrics.get('scarcityFallbackRatio')}"
    )
    root_causes = semantic_report.get("rootCauses") or {}
    blank_causes = (root_causes.get("blankNonPickPosition") or {}).get("counts") or {}
    mismatch_causes = (root_causes.get("sourceCountWithoutPositiveCanonicalSites") or {}).get("counts") or {}
    if blank_causes:
        top_blank = ", ".join(
            f"{k}={v}"
            for k, v in list(blank_causes.items())[:3]
        )
        print(f"[semantic] blankPositionCauses: {top_blank}")
    if mismatch_causes:
        top_mismatch = ", ".join(
            f"{k}={v}"
            for k, v in list(mismatch_causes.items())[:3]
        )
        print(f"[semantic] sourceMismatchCauses: {top_mismatch}")
    for msg in (semantic_report.get("warnings") or [])[:8]:
        print(f"[semantic][warn] {msg}")
    for reason in (semantic_report.get("criticalReasons") or [])[:4]:
        print(f"[semantic][critical] {reason}")

    if not report.get("ok"):
        for msg in report.get("errors", [])[:20]:
            print(f"[contract][error] {msg}")
        print(f"[contract] validation output: {out_path}")
        return 1

    if args.strict_semantic and semantic_report.get("status") != "healthy":
        print("[semantic] strict mode failed due to semantic integrity status")
        print(f"[contract] validation output: {out_path}")
        return 2

    print(f"[contract] validation output: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
