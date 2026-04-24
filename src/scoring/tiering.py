"""Cohen's-d positional tiering.

Walks a list of players sorted by descending value and starts a
new tier whenever Cohen's d between (current tier) and (next
player) exceeds a per-position threshold.

Cohen's d
---------
    d = (mean_A − mean_B) / pooled_sd

For our purposes:
  * mean_A = mean value of the current tier-so-far
  * mean_B = value of the candidate next player
  * pooled_sd = stdev of values remaining in the position pool
                (NOT stdev of the current tier — which tends to
                zero and makes every player a new tier)

Thresholds are per-position and live in
``config/tiers/thresholds.json`` (see ``scripts/fit_tier_thresholds.py``
for the grid-search fitter).  Sensible priors baked in here:

    QB:  d ≈ 0.35 (4–6 tiers for ~30 players)
    RB:  d ≈ 0.22 (8–12 tiers for ~60 players)
    WR:  d ≈ 0.22 (8–12 tiers for ~80 players)
    TE:  d ≈ 0.35 (4–6 tiers for ~30 players)

Drift detection
---------------
``detect_threshold_drift(old_tiers, new_tiers)`` returns True when
re-running the fitter produces tier counts that differ from the
stored config by >15% (cumulative across positions).  Used by the
monthly refit cron to decide whether to open a PR rather than
silently updating prod.

Pure-Python.  No numpy.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Sensible priors — overridden by config/tiers/thresholds.json if
# present.  Keys are position strings (uppercase).
_DEFAULT_THRESHOLDS: dict[str, float] = {
    "QB": 0.35,
    "RB": 0.22,
    "WR": 0.22,
    "TE": 0.35,
    # IDP defaults — coarser because IDP value scale is noisier.
    "DL": 0.30,
    "LB": 0.30,
    "DB": 0.30,
    # Picks — keep flat (one tier per round) via a high threshold.
    "PICK": 2.0,
}


@dataclass(frozen=True)
class TierEntry:
    tier_id: int
    player_name: str
    value: float
    position: str


def _safe_stdev(values: Iterable[float]) -> float:
    """Population standard deviation, returns 0 when n<2 to avoid
    divide-by-zero in the cold-start path."""
    vs = [float(v) for v in values if isinstance(v, (int, float))]
    if len(vs) < 2:
        return 0.0
    mean = sum(vs) / len(vs)
    sq = sum((v - mean) ** 2 for v in vs) / len(vs)
    return math.sqrt(sq)


def _cohens_d(tier_mean: float, candidate: float, pooled_sd: float) -> float:
    if pooled_sd <= 0:
        return 0.0
    return abs(tier_mean - candidate) / pooled_sd


def load_thresholds(path: Path | None = None) -> dict[str, float]:
    """Return the effective per-position thresholds.  Reads
    ``config/tiers/thresholds.json`` when present, else returns
    the module defaults."""
    default = dict(_DEFAULT_THRESHOLDS)
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "tiers" / "thresholds.json"
    if not path.exists():
        return default
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default
    if not isinstance(raw, dict):
        return default
    # Accept {"QB": 0.3, ...} or {"thresholds": {"QB": 0.3, ...}}
    core = raw.get("thresholds") if "thresholds" in raw else raw
    if not isinstance(core, dict):
        return default
    for k, v in core.items():
        try:
            default[str(k).upper()] = float(v)
        except (TypeError, ValueError):
            continue
    return default


def detect_tiers(
    rows: list[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
) -> list[TierEntry]:
    """Walk players sorted by descending value, emitting tier IDs.

    Input rows must carry ``name``, ``pos`` (or ``position``), and
    a numeric value (``rankDerivedValue`` preferred, then
    ``values.full``, then ``value``).

    Returns a list of TierEntry in the input's position order —
    but tiers are computed per-position, starting at tier 1 for
    the best player at each position.

    Thresholds default to the module priors when not supplied.
    """
    thresholds = thresholds or load_thresholds()

    # Group by position, preserving a value sort.
    by_pos: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        if not isinstance(r, dict):
            continue
        pos = str(r.get("pos") or r.get("position") or "").upper()
        if not pos:
            continue
        by_pos.setdefault(pos, []).append(r)

    result_map: dict[id, TierEntry] = {}
    for pos, group in by_pos.items():
        group_sorted = sorted(
            group,
            key=lambda r: -_value_of(r),
            reverse=False,  # sort ascending by -value ⇒ descending value
        )
        thresh = thresholds.get(pos, 0.25)
        pool_sd = _safe_stdev(_value_of(r) for r in group_sorted)
        if pool_sd <= 0:
            # Everyone in one tier.
            for r in group_sorted:
                result_map[id(r)] = TierEntry(
                    tier_id=1, player_name=str(r.get("name") or ""),
                    value=_value_of(r), position=pos,
                )
            continue

        tier_id = 1
        tier_values: list[float] = []
        for r in group_sorted:
            val = _value_of(r)
            if not tier_values:
                tier_values.append(val)
            else:
                tier_mean = sum(tier_values) / len(tier_values)
                d = _cohens_d(tier_mean, val, pool_sd)
                if d > thresh:
                    tier_id += 1
                    tier_values = [val]
                else:
                    tier_values.append(val)
            result_map[id(r)] = TierEntry(
                tier_id=tier_id,
                player_name=str(r.get("name") or ""),
                value=val, position=pos,
            )

    # Return in input order.
    return [result_map[id(r)] for r in rows if isinstance(r, dict) and id(r) in result_map]


def stamp_tiers_on_players(
    rows: list[dict[str, Any]],
    *,
    thresholds: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Stamp ``tierId`` onto a COPY of each row (non-destructive).

    Safe to call from the contract builder when the
    ``positional_tiers`` feature flag is on — the stamp is additive.
    """
    tiers = detect_tiers(rows, thresholds=thresholds)
    by_id = {id(rows[i]): tiers[i].tier_id for i in range(len(tiers))}
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            out.append(r)
            continue
        new_r = dict(r)
        if id(r) in by_id:
            new_r["tierId"] = by_id[id(r)]
        out.append(new_r)
    return out


def fit_thresholds_grid_search(
    rows: list[dict[str, Any]],
    *,
    grids: dict[str, tuple[float, float, float]] | None = None,
    targets: dict[str, tuple[int, int]] | None = None,
) -> dict[str, float]:
    """Grid-search a per-position threshold that yields tier
    counts inside ``targets``.

    ``grids[pos] = (start, stop, step)``
    ``targets[pos] = (min_count, max_count)``

    Returns ``{pos: threshold}`` — best threshold per position, where
    "best" = smallest distance to the midpoint of the target range.

    Used offline by ``scripts/fit_tier_thresholds.py`` — not called
    from live request paths.
    """
    grids = grids or {
        "QB": (0.2, 0.6, 0.02),
        "RB": (0.1, 0.5, 0.02),
        "WR": (0.1, 0.5, 0.02),
        "TE": (0.2, 0.6, 0.02),
        "DL": (0.2, 0.6, 0.04),
        "LB": (0.2, 0.6, 0.04),
        "DB": (0.2, 0.6, 0.04),
    }
    targets = targets or {
        "QB": (4, 6),
        "RB": (8, 12),
        "WR": (8, 12),
        "TE": (4, 6),
        "DL": (4, 8),
        "LB": (4, 8),
        "DB": (4, 8),
    }

    best: dict[str, float] = {}
    for pos, (start, stop, step) in grids.items():
        target_lo, target_hi = targets.get(pos, (4, 10))
        midpoint = (target_lo + target_hi) / 2.0
        pos_rows = [r for r in rows if str(r.get("pos") or r.get("position") or "").upper() == pos]
        if len(pos_rows) < 3:
            continue
        best_t = start
        best_dist = float("inf")
        t = start
        while t <= stop + 1e-9:
            tiers = detect_tiers(pos_rows, thresholds={pos: t})
            count = max((te.tier_id for te in tiers), default=0)
            dist = abs(count - midpoint)
            if count < target_lo or count > target_hi:
                dist += 10  # penalize out-of-range
            if dist < best_dist:
                best_dist = dist
                best_t = t
            t += step
        best[pos] = round(best_t, 3)
    return best


def detect_threshold_drift(
    old_thresholds: dict[str, float],
    new_thresholds: dict[str, float],
    *,
    tolerance_pct: float = 0.15,
) -> dict[str, Any]:
    """Return {hasDrift, positions: {pos: pctChange}}.

    ``hasDrift`` is True when the max absolute pct change across
    positions exceeds ``tolerance_pct``.  Monthly refit cron uses
    this to decide between silent update vs. open-a-PR.
    """
    drifted = {}
    max_drift = 0.0
    for pos in set(list(old_thresholds.keys()) + list(new_thresholds.keys())):
        old = float(old_thresholds.get(pos, 0.0) or 0.0)
        new = float(new_thresholds.get(pos, 0.0) or 0.0)
        if old <= 0:
            drifted[pos] = None
            continue
        pct = (new - old) / old
        drifted[pos] = round(pct, 4)
        if abs(pct) > max_drift:
            max_drift = abs(pct)
    return {
        "hasDrift": max_drift > tolerance_pct,
        "maxDriftPct": round(max_drift, 4),
        "positions": drifted,
    }


def _value_of(row: dict[str, Any]) -> float:
    """Resolve a row's numeric value, preferring the canonical
    fields in order of authority."""
    v = row.get("rankDerivedValue")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    values = row.get("values") or {}
    if isinstance(values, dict):
        for key in ("full", "display", "displayValue"):
            if values.get(key) is not None:
                try:
                    return float(values[key])
                except (TypeError, ValueError):
                    pass
    v2 = row.get("value")
    if v2 is not None:
        try:
            return float(v2)
        except (TypeError, ValueError):
            pass
    return 0.0
