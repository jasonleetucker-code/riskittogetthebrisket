from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Iterable, Optional, Tuple

from .feature_engineering import RECEPTION_DEPENDENCY_TAG, infer_scoring_tags


#: Label for "not enough observed features to classify".  Same label the
#: function already returned for an unsupported bucket; ``summarize_archetype_priors``
#: already buckets it as ``unknown`` and no scoring adjustment is derived from it.
UNKNOWN_ARCHETYPE: Tuple[str, str] = ("unknown", "unknown")


def _observed(features: Dict[str, float], key: str) -> Optional[float]:
    """The feature's value, or ``None`` when it is absent / None / non-numeric /
    non-finite.  MISSING IS NEVER ZERO: an observed ``0.0`` is returned as 0.0,
    an unobserved feature is never coerced to it."""
    v = features.get(key)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def infer_archetype(bucket: str, features: Dict[str, float]) -> Tuple[str, str]:
    """Hand-cut archetype classifier (cut-points unchanged, AMATH-S38).

    A branch whose deciding feature is unobserved returns
    ``UNKNOWN_ARCHETYPE`` instead of the default label a read of 0.0 implies.
    Branches are evaluated in order; a feature is only required when the
    earlier, already-observed features did not decide the answer.
    """
    p = str(bucket or "").upper()
    f = features or {}

    def two_way(key, cut, hi, lo):
        v = _observed(f, key)
        if v is None:
            return UNKNOWN_ARCHETYPE
        return hi if v >= cut else lo

    if p == "QB":
        return two_way(
            "qb_rush_contribution", 0.22, ("dual_threat_qb", "mobile"), ("pocket_qb", "passing")
        )
    if p == "RB":
        # Shares the ``reception_sensitive`` cut rather than carrying a
        # second, looser 0.18 of its own — the two read the same
        # feature, and a back who is a ``receiving_rb`` here but not
        # reception-sensitive there is an incoherent pair of labels.
        rec = _observed(f, "reception_dependency")
        if rec is None:
            return UNKNOWN_ARCHETYPE
        if rec >= RECEPTION_DEPENDENCY_TAG:
            return "receiving_rb", "receiving"
        return two_way(
            "goal_line_proxy", 0.45, ("goal_line_rb", "power"), ("early_down_rb", "balanced")
        )
    if p == "WR":
        return two_way(
            "field_stretcher_proxy",
            13.5,
            ("field_stretcher_wr", "downfield"),
            ("possession_wr", "volume"),
        )
    if p == "TE":
        return two_way("red_zone_proxy", 0.45, ("td_te", "red_zone"), ("volume_te", "chain_mover"))
    if p == "DL":
        return two_way("splash_dependency", 1.2, ("sack_dl", "splash"), ("tackle_dl", "tackle"))
    if p == "LB":
        return two_way("tackle_dependency", 6.5, ("tackle_lb", "tackle"), ("splash_lb", "splash"))
    if p == "DB":
        return two_way(
            "splash_dependency", 0.85, ("ballhawk_db", "splash"), ("tackle_db", "tackle")
        )
    return UNKNOWN_ARCHETYPE


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
