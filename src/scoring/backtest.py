from __future__ import annotations

import math
from typing import Dict, Iterable, List

from .types import BacktestRow


def _pearson(xs: List[float], ys: List[float]) -> float:
    if len(xs) < 3 or len(xs) != len(ys):
        return 0.0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = 0.0
    dx = 0.0
    dy = 0.0
    for x, y in zip(xs, ys):
        vx = x - mx
        vy = y - my
        num += vx * vy
        dx += vx * vx
        dy += vy * vy
    if dx <= 1e-12 or dy <= 1e-12:
        return 0.0
    return num / math.sqrt(dx * dy)


def run_scoring_backtest(player_fits: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    rows: List[BacktestRow] = []
    for _, fit in (player_fits or {}).items():
        try:
            baseline = float(fit.get("ppgTest", 0.0) or 0.0)
            custom = float(fit.get("ppgCustom", 0.0) or 0.0)
            ratio = float(fit.get("fitFinal", 1.0) or 1.0)
            mult = float(fit.get("productionMultiplier", 1.0) or 1.0)
            conf = float(fit.get("confidence", 0.0) or 0.0)
            pos = str(fit.get("bucket", "") or "")
            name = str(fit.get("name", fit.get("playerName", "")) or "")
            rows.append(
                BacktestRow(
                    player_name=name,
                    position_bucket=pos,
                    baseline_ppg=baseline,
                    league_ppg=custom,
                    ratio=ratio,
                    multiplier=mult,
                    confidence=conf,
                    delta_points=custom - baseline,
                )
            )
        except Exception:
            continue

    all_rows = [r.to_dict() for r in rows]
    ratios = [r.ratio for r in rows]
    deltas = [r.delta_points for r in rows]
    confs = [r.confidence for r in rows]
    abs_deltas = [abs(x) for x in deltas]
    report: Dict[str, object] = {
        "sampleSize": len(rows),
        "overall": {
            "corr_ratio_vs_delta_points": round(_pearson(ratios, deltas), 6),
            "corr_confidence_vs_abs_delta": round(
                _pearson(confs, abs_deltas),
                6,
            ),
            "avg_ratio": round(sum(ratios) / len(ratios), 6) if ratios else 1.0,
            "avg_confidence": round(sum(confs) / len(confs), 6) if confs else 0.0,
            "avg_abs_delta_points": round(sum(abs_deltas) / len(abs_deltas), 6) if abs_deltas else 0.0,
        },
        "byPosition": {},
        "byConfidenceBucket": {},
        "topGainers": sorted(all_rows, key=lambda r: -float(r.get("delta_points", 0.0)))[:12],
        "topLosers": sorted(all_rows, key=lambda r: float(r.get("delta_points", 0.0)))[:12],
    }

    buckets = sorted(set(r.position_bucket for r in rows if r.position_bucket))
    for b in buckets:
        bucket_rows = [r for r in rows if r.position_bucket == b]
        br = [x.ratio for x in bucket_rows]
        bd = [x.delta_points for x in bucket_rows]
        if not bucket_rows:
            continue
        report["byPosition"][b] = {
            "n": len(bucket_rows),
            "avg_ratio": round(sum(br) / len(br), 6),
            "avg_delta_points": round(sum(bd) / len(bd), 6),
            "corr_ratio_vs_delta_points": round(_pearson(br, bd), 6),
        }
    conf_buckets = {
        "low": [r for r in rows if r.confidence < 0.40],
        "medium": [r for r in rows if 0.40 <= r.confidence < 0.70],
        "high": [r for r in rows if r.confidence >= 0.70],
    }
    for label, bucket_rows in conf_buckets.items():
        if not bucket_rows:
            continue
        br = [x.ratio for x in bucket_rows]
        bd = [x.delta_points for x in bucket_rows]
        report["byConfidenceBucket"][label] = {
            "n": len(bucket_rows),
            "avg_ratio": round(sum(br) / len(br), 6),
            "avg_abs_delta_points": round(sum(abs(x) for x in bd) / len(bd), 6),
            "corr_ratio_vs_delta_points": round(_pearson(br, bd), 6),
        }
    return report
