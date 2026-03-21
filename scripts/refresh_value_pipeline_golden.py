from __future__ import annotations

import argparse
from copy import deepcopy
import datetime as dt
import json
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api.data_contract import build_api_data_contract


CASE_SPECS: list[dict[str, Any]] = [
    {
        "id": "elite_qb",
        "category": "elite QB",
        "player": "Josh Allen",
        "stability": "stable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "draftSharks", "yahoo", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
    },
    {
        "id": "elite_rb",
        "category": "elite RB",
        "player": "Bijan Robinson",
        "stability": "stable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "draftSharks", "yahoo", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
    },
    {
        "id": "elite_wr",
        "category": "elite WR",
        "player": "Ja'Marr Chase",
        "stability": "stable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "draftSharks", "yahoo", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
    },
    {
        "id": "elite_te",
        "category": "elite TE",
        "player": "Brock Bowers",
        "stability": "stable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "draftSharks", "yahoo", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
    },
    {
        "id": "elite_dl",
        "category": "elite DL",
        "player": "Will Anderson",
        "stability": "moderate",
        "requiredSites": ["idpTradeCalc", "pffIdp", "fantasyProsIdp", "dlfIdp"],
        "minSourceCount": 4,
    },
    {
        "id": "elite_lb",
        "category": "elite LB",
        "player": "Fred Warner",
        "stability": "moderate",
        "requiredSites": ["idpTradeCalc", "pffIdp", "fantasyProsIdp", "dlfIdp"],
        "minSourceCount": 4,
    },
    {
        "id": "elite_db",
        "category": "elite DB",
        "player": "Kyle Hamilton",
        "stability": "moderate",
        "requiredSites": ["idpTradeCalc", "pffIdp", "fantasyProsIdp", "dlfIdp"],
        "minSourceCount": 4,
    },
    {
        "id": "rookie_offense",
        "category": "rookie offensive player",
        "player": "Jeremiyah Love",
        "stability": "moderate",
        "requiredSites": ["ktc", "fantasyCalc", "draftSharks", "idpTradeCalc", "dlfRsf"],
        "minSourceCount": 8,
    },
    {
        "id": "rookie_idp",
        "category": "rookie IDP player",
        "player": "Arvell Reese",
        "stability": "unstable",
        "requiredSites": ["idpTradeCalc", "dlfRidp"],
        "minSourceCount": 2,
        "maxSourceCount": 2,
    },
    {
        "id": "aging_veteran",
        "category": "aging veteran",
        "player": "Aaron Rodgers",
        "stability": "moderate",
        "requiredSites": ["ktc", "fantasyCalc", "draftSharks", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
    },
    {
        "id": "injured_player",
        "category": "injured player",
        "player": "Jonathon Brooks",
        "stability": "unstable",
        "requiredSites": ["ktc", "fantasyCalc", "draftSharks", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
        # Current payload has no explicit injury status field; this proxy is the
        # available signal we can lock in for regression coverage.
        "injuryProxyField": "_formatFitLowSample",
    },
    {
        "id": "draft_pick",
        "category": "draft pick",
        "player": "2026 Pick 1.01",
        "stability": "stable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "yahoo", "idpTradeCalc"],
        "minSourceCount": 5,
        "maxSourceCount": 5,
    },
    {
        "id": "partial_source_coverage",
        "category": "player with partial source coverage",
        "player": "Brandon Aubrey",
        "stability": "unstable",
        "requiredSites": ["draftSharks"],
        "minSourceCount": 1,
        "maxSourceCount": 1,
    },
    {
        "id": "conflicting_source_coverage",
        "category": "player with conflicting source coverage",
        "player": "Spencer Rattler",
        "stability": "unstable",
        "requiredSites": ["ktc", "fantasyCalc", "dynastyDaddy", "fantasyPros", "yahoo", "dynastyNerds", "idpTradeCalc", "dlfSf"],
        "minSourceCount": 8,
        "conflictSpreadMin": 1000.0,
    },
]

NORM_TOLERANCE_BY_STABILITY = {
    "stable": 0.01,
    "moderate": 0.02,
    "unstable": 0.04,
}

VALUE_ABS_TOLERANCE_BY_STABILITY = {
    "stable": 35,
    "moderate": 70,
    "unstable": 140,
}

VALUE_PCT_TOLERANCE_BY_STABILITY = {
    "stable": 0.005,
    "moderate": 0.010,
    "unstable": 0.020,
}

Z_FLOOR = -2.0
Z_CEILING = 4.0


def _latest_payload_path(repo_root: Path) -> Path:
    candidates = sorted(repo_root.glob("data/dynasty_data_*.json"))
    if not candidates:
        raise FileNotFoundError("No data/dynasty_data_*.json files found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _to_num(v: Any) -> float | None:
    try:
        n = float(v)
    except Exception:
        return None
    if not (n == n):  # NaN guard
        return None
    return n


def _normalize_site_value(
    *,
    site_key: str,
    canonical_value: float,
    site_stats: dict[str, Any],
    max_values: dict[str, Any],
) -> float:
    stat = site_stats.get(site_key)
    if isinstance(stat, dict):
        mean = _to_num(stat.get("mean"))
        stdev = _to_num(stat.get("stdev"))
        if mean is not None and stdev is not None and stdev > 0:
            z = (float(canonical_value) - float(mean)) / float(stdev)
            return max(0.0, min(1.0, (z - Z_FLOOR) / (Z_CEILING - Z_FLOOR)))
    mx = _to_num(max_values.get(site_key))
    if mx is None or mx <= 0:
        mx = 9999.0
    return max(0.0, min(1.0, float(canonical_value) / float(mx)))


def _value_band(value: int, stability: str) -> tuple[int, int]:
    abs_tol = int(VALUE_ABS_TOLERANCE_BY_STABILITY.get(stability, 70))
    pct_tol = float(VALUE_PCT_TOLERANCE_BY_STABILITY.get(stability, 0.01))
    tol = max(abs_tol, int(round(float(value) * pct_tol)))
    lo = max(1, int(value) - tol)
    hi = min(9999, int(value) + tol)
    return lo, hi


def _subset_sleeper(raw_sleeper: dict[str, Any], selected_names: set[str], selected_ids: set[str]) -> dict[str, Any]:
    out = deepcopy(raw_sleeper or {})
    pos_map = raw_sleeper.get("positions")
    if isinstance(pos_map, dict):
        out["positions"] = {k: v for k, v in pos_map.items() if k in selected_names}
    player_ids = raw_sleeper.get("playerIds")
    if isinstance(player_ids, dict):
        out["playerIds"] = {k: v for k, v in player_ids.items() if k in selected_names}
        for v in out["playerIds"].values():
            if isinstance(v, (str, int)):
                selected_ids.add(str(v))
    id_to_player = raw_sleeper.get("idToPlayer")
    if isinstance(id_to_player, dict):
        out["idToPlayer"] = {k: v for k, v in id_to_player.items() if str(k) in selected_ids}
    return out


def _build_golden_input(raw_payload: dict[str, Any], selected_names: set[str]) -> dict[str, Any]:
    players = raw_payload.get("players")
    if not isinstance(players, dict):
        raise ValueError("raw payload missing players map")
    subset_players = {name: deepcopy(players[name]) for name in selected_names if name in players}

    selected_ids: set[str] = set()
    for pdata in subset_players.values():
        if isinstance(pdata, dict):
            sid = pdata.get("_sleeperId")
            if isinstance(sid, (str, int)) and str(sid).strip():
                selected_ids.add(str(sid))

    out: dict[str, Any] = {
        "version": raw_payload.get("version"),
        "date": raw_payload.get("date"),
        "scrapeTimestamp": raw_payload.get("scrapeTimestamp"),
        "settings": deepcopy(raw_payload.get("settings")),
        "sites": deepcopy(raw_payload.get("sites")),
        "maxValues": deepcopy(raw_payload.get("maxValues")),
        "siteStats": deepcopy(raw_payload.get("siteStats")),
        "pickAnchors": deepcopy(raw_payload.get("pickAnchors")),
        "pickAnchorsRaw": deepcopy(raw_payload.get("pickAnchorsRaw")),
        "rawMarketDiagnostics": deepcopy(raw_payload.get("rawMarketDiagnostics")),
        "coverageAudit": deepcopy(raw_payload.get("coverageAudit")),
        "empiricalLAM": deepcopy(raw_payload.get("empiricalLAM")),
        "players": subset_players,
    }

    raw_sleeper = raw_payload.get("sleeper")
    if isinstance(raw_sleeper, dict):
        out["sleeper"] = _subset_sleeper(raw_sleeper, selected_names, selected_ids)
    else:
        out["sleeper"] = {}
    return out


def _case_from_row(
    *,
    spec: dict[str, Any],
    row: dict[str, Any],
    raw_player: dict[str, Any],
    site_stats: dict[str, Any],
    max_values: dict[str, Any],
) -> dict[str, Any]:
    name = str(row.get("canonicalName") or spec["player"])
    stability = str(spec.get("stability") or "moderate")
    norm_tol = float(NORM_TOLERANCE_BY_STABILITY.get(stability, 0.02))
    bundle = row.get("valueBundle") or {}
    source_cov = bundle.get("sourceCoverage") or {}

    canonical_sites = row.get("canonicalSiteValues") or {}
    present_sites = [
        str(sk) for sk, sv in canonical_sites.items()
        if _to_num(sv) is not None and float(_to_num(sv)) > 0
    ]
    present_sites = sorted(present_sites)

    normalized_bands: dict[str, dict[str, float]] = {}
    for sk in present_sites:
        sv_num = _to_num(canonical_sites.get(sk))
        if sv_num is None or sv_num <= 0:
            continue
        norm = _normalize_site_value(
            site_key=sk,
            canonical_value=float(sv_num),
            site_stats=site_stats,
            max_values=max_values,
        )
        normalized_bands[sk] = {
            "min": round(max(0.0, norm - norm_tol), 4),
            "max": round(min(1.0, norm + norm_tol), 4),
            "expected": round(norm, 4),
        }

    full_val = int(bundle.get("fullValue") or 0)
    raw_val = int(bundle.get("rawValue") or 0)
    full_lo, full_hi = _value_band(full_val, stability)
    raw_lo, raw_hi = _value_band(raw_val, stability)

    vals = [
        float(_to_num(canonical_sites.get(sk)) or 0.0)
        for sk in present_sites
        if _to_num(canonical_sites.get(sk)) is not None and float(_to_num(canonical_sites.get(sk))) > 0
    ]
    spread = float(max(vals) / max(1.0, min(vals))) if vals else 1.0

    injury_proxy_field = spec.get("injuryProxyField")
    injury_proxy_expected = None
    if isinstance(injury_proxy_field, str) and injury_proxy_field:
        injury_proxy_expected = bool(raw_player.get(injury_proxy_field))

    expected = {
        "mergeIdentity": {
            "canonicalName": name,
            "position": row.get("position"),
            "playerId": row.get("playerId"),
            "assetClass": row.get("assetClass"),
        },
        "sourcePresence": {
            "requiredSites": list(spec.get("requiredSites") or []),
            "minSourceCount": int(spec.get("minSourceCount") or 0),
            "maxSourceCount": (
                int(spec["maxSourceCount"])
                if spec.get("maxSourceCount") is not None
                else None
            ),
            "presentSitesExpected": present_sites,
        },
        "normalizedValues": {
            "bands": normalized_bands,
            "tolerance": round(norm_tol, 4),
        },
        "finalAdjustedValueBand": {
            "min": int(full_lo),
            "max": int(full_hi),
            "expected": int(full_val),
        },
        "rawValueBand": {
            "min": int(raw_lo),
            "max": int(raw_hi),
            "expected": int(raw_val),
        },
        "coverageAndConfidence": {
            "sourceCoverageCount": int(source_cov.get("count") or 0),
            "confidence": float(bundle.get("confidence") or 0.0),
            "sourceSpread": round(spread, 4),
        },
        "rookieExpected": bool(row.get("rookie")),
    }
    if injury_proxy_field:
        expected["injuryProxy"] = {
            "field": injury_proxy_field,
            "expected": bool(injury_proxy_expected),
        }
    if spec.get("conflictSpreadMin") is not None:
        expected["sourceConflict"] = {
            "spreadMin": float(spec["conflictSpreadMin"]),
            "expectedSpread": round(spread, 4),
        }
    return {
        "id": spec["id"],
        "category": spec["category"],
        "canonicalName": name,
        "stability": stability,
        "expected": expected,
        "notes": spec.get("notes") or "",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh curated value pipeline golden regression fixtures.")
    parser.add_argument(
        "--source-payload",
        default="",
        help="Path to source dynasty_data_*.json payload. Defaults to latest in data/.",
    )
    parser.add_argument(
        "--golden-input-out",
        default="tests/fixtures/value_pipeline_golden_input.json",
        help="Output path for frozen curated input payload.",
    )
    parser.add_argument(
        "--golden-spec-out",
        default="tests/fixtures/value_pipeline_golden.json",
        help="Output path for golden expectation dataset.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    source_path = Path(args.source_payload).resolve() if args.source_payload else _latest_payload_path(repo_root)
    if not source_path.is_file():
        raise FileNotFoundError(f"Source payload not found: {source_path}")

    raw_payload = json.loads(source_path.read_text(encoding="utf-8"))
    selected_names = {str(c["player"]) for c in CASE_SPECS}
    for name in sorted(selected_names):
        if name not in (raw_payload.get("players") or {}):
            raise KeyError(f"Golden case player not found in payload: {name}")

    golden_input = _build_golden_input(raw_payload, selected_names)
    contract = build_api_data_contract(golden_input)
    by_name = {str(r.get("canonicalName")): r for r in contract.get("playersArray") or [] if isinstance(r, dict)}

    site_stats = golden_input.get("siteStats") if isinstance(golden_input.get("siteStats"), dict) else {}
    max_values = golden_input.get("maxValues") if isinstance(golden_input.get("maxValues"), dict) else {}
    raw_players = golden_input.get("players") if isinstance(golden_input.get("players"), dict) else {}

    cases_out: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        player_name = str(spec["player"])
        row = by_name.get(player_name)
        if not isinstance(row, dict):
            raise KeyError(f"Expected player missing from contract playersArray: {player_name}")
        raw_player = raw_players.get(player_name) if isinstance(raw_players.get(player_name), dict) else {}
        cases_out.append(
            _case_from_row(
                spec=spec,
                row=row,
                raw_player=raw_player,
                site_stats=site_stats,
                max_values=max_values,
            )
        )

    golden_input_out = (repo_root / args.golden_input_out).resolve()
    golden_input_out.parent.mkdir(parents=True, exist_ok=True)
    golden_input_out.write_text(json.dumps(golden_input, indent=2), encoding="utf-8")

    golden_spec = {
        "meta": {
            "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
            "sourcePayloadPath": str(source_path),
            "contractVersion": str(contract.get("contractVersion") or ""),
            "goldenInputPath": str(golden_input_out),
            "caseCount": len(cases_out),
            "refreshCommand": "python scripts/refresh_value_pipeline_golden.py --source-payload <path-to-approved-dynasty-data.json>",
            "latestLivePayloadGlob": "data/dynasty_data_*.json",
            "purpose": "Golden regression suite for source presence + normalization + final adjusted values + merge identity.",
        },
        "cases": cases_out,
    }

    golden_spec_out = (repo_root / args.golden_spec_out).resolve()
    golden_spec_out.parent.mkdir(parents=True, exist_ok=True)
    golden_spec_out.write_text(json.dumps(golden_spec, indent=2), encoding="utf-8")

    print(f"[golden] Source payload: {source_path}")
    print(f"[golden] Golden input written: {golden_input_out}")
    print(f"[golden] Golden spec written:  {golden_spec_out}")
    print(f"[golden] Cases: {len(cases_out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
