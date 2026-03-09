from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Tuple

from .feature_engineering import infer_scoring_tags


def infer_archetype(bucket: str, features: Dict[str, float]) -> Tuple[str, str]:
    p = str(bucket or "").upper()
    f = features or {}
    if p == "QB":
        if f.get("qb_rush_contribution", 0.0) >= 0.22:
            return "dual_threat_qb", "mobile"
        return "pocket_qb", "passing"
    if p == "RB":
        if f.get("reception_dependency", 0.0) >= 0.18:
            return "receiving_rb", "receiving"
        if f.get("goal_line_proxy", 0.0) >= 0.45:
            return "goal_line_rb", "power"
        return "early_down_rb", "balanced"
    if p == "WR":
        if f.get("field_stretcher_proxy", 0.0) >= 13.5:
            return "field_stretcher_wr", "downfield"
        return "possession_wr", "volume"
    if p == "TE":
        if f.get("red_zone_proxy", 0.0) >= 0.45:
            return "td_te", "red_zone"
        return "volume_te", "chain_mover"
    if p == "DL":
        if f.get("splash_dependency", 0.0) >= 1.2:
            return "sack_dl", "splash"
        return "tackle_dl", "tackle"
    if p == "LB":
        if f.get("tackle_dependency", 0.0) >= 6.5:
            return "tackle_lb", "tackle"
        return "splash_lb", "splash"
    if p == "DB":
        if f.get("splash_dependency", 0.0) >= 0.85:
            return "ballhawk_db", "splash"
        return "tackle_db", "tackle"
    return "unknown", "unknown"


def summarize_archetype_priors(rows: Iterable[Dict[str, object]]) -> Dict[str, Dict[str, float]]:
    agg = defaultdict(lambda: {"count": 0, "fit_sum": 0.0, "conf_sum": 0.0})
    for row in rows or []:
        archetype = str(row.get("archetype") or "unknown")
        a = agg[archetype]
        a["count"] += 1
        a["fit_sum"] += float(row.get("raw_fit", 1.0) or 1.0)
        a["conf_sum"] += float(row.get("confidence", 0.4) or 0.4)
    out: Dict[str, Dict[str, float]] = {}
    for k, v in agg.items():
        n = max(1, int(v["count"]))
        out[k] = {
            "count": n,
            "fit_prior": round(float(v["fit_sum"]) / n, 6),
            "confidence_prior": round(float(v["conf_sum"]) / n, 6),
        }
    return out


def build_scoring_tags(bucket: str, features: Dict[str, float]) -> list[str]:
    return infer_scoring_tags(bucket, features)

