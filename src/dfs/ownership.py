"""Projected ownership: a structural baseline, a source ensemble, overrides — all as-of T.

DFS-MOD-02.  Three explicit components, each separately evaluable:

1. **Structural baseline** (``ownership.structural``) — needs no third-party
   data, so there is always something to compare a source against.  Every
   roster slot's 100% is spread across the players eligible for it in
   proportion to ``exp(bv·z(points per $1K) + bp·z(projection))``; a player's
   ownership is the sum over slots, capped at 100% (excess redistributed), so
   the slate total is exactly 100% × roster size.  ``bv``/``bp`` start as
   declared, UNCALIBRATED priors; ``fit_structural`` refits them
   chronologically from settled results.  Unprojected players are
   ``not_modelled`` — never 0%.
2. **Source ensemble** (``ownership.ensemble``) — the latest value of each
   source held at T (``pit.as_of``), weighted by inverse historical MAE only
   once a source has ``MIN_EVAL_PLAYERS`` scored players; otherwise equal
   weights, stated.  Sources older than ``STALE_HOURS`` at T are flagged, not
   silently used as current.
3. **Owner overrides** — replace the value for that player, labelled.

Every player row names its method, so a forecast built from a mix of sources
and the baseline can be scored piece by piece.  Leakage guard: inputs come only
from ``pit.as_of`` (published AND recorded by T, and before lock).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.dfs import metrics, pit
from src.dfs.rules import RuleSet

STRUCTURAL_ID = "ownership.structural"
ENSEMBLE_ID = "ownership.ensemble"
STRUCTURAL_PRIOR = {"bv": 1.0, "bp": 1.0}
MIN_EVAL_PLAYERS = 60  # per source, before its historical error is allowed to weight it
STALE_HOURS = 24.0
PROMOTION_CRITERIA = {
    "minSamples": 150,
    "metric": "mae",
    "lowerIsBetter": True,
    "mustBeatBaselineBy": 0.25,
}


@dataclass
class _P:
    player_id: str
    positions: list[str]
    eligible_slots: list[str]
    salary: int
    projection: float | None


def _z(xs: list[float]) -> list[float]:
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))
    return [0.0 if sd == 0 else (x - m) / sd for x in xs]


def structural_baseline(
    players: list[Any], ruleset: RuleSet, params: dict[str, float] | None = None
) -> dict[str, float | None]:
    """player_id → projected ownership percent (None = not modelled: no projection)."""
    p = {**STRUCTURAL_PRIOR, **(params or {})}
    modelled = [a for a in players if a.projection is not None and a.salary]
    out: dict[str, float | None] = {a.player_id: None for a in players}
    if not modelled:
        return out
    value = [a.projection / (a.salary / 1000) for a in modelled]
    zv, zp = _z(value), _z([a.projection for a in modelled])
    weight = [math.exp(p["bv"] * v + p["bp"] * q) for v, q in zip(zv, zp)]
    # Per-slot shares: each slot's 100% lives on the players eligible for IT.
    shares: list[dict[int, float]] = []
    for slot in ruleset.slots:
        idx = [i for i, a in enumerate(modelled) if ruleset.eligible(a, slot)]
        total = sum(weight[i] for i in idx)
        shares.append({i: weight[i] / total for i in idx} if total > 0 else {})
    # Cap at one appearance per lineup.  A capped player's surplus in a slot goes
    # only to uncapped players eligible for THAT slot, so every slot still sums to
    # 100% and a position's total stays exact (one QB slot => QBs total 100%).
    # (Redistributing pro rata over everyone leaked a WR's surplus into QBs: 116%.)
    capped: set[int] = set()
    for _ in range(50):
        totals = [0.0] * len(modelled)
        for sh in shares:
            for i, v in sh.items():
                totals[i] += v
        over = [i for i, t in enumerate(totals) if t > 1.0 + 1e-12]
        if not over:
            break
        for i in over:
            capped.add(i)
            keep = 1.0 / totals[i]
            for sh in shares:
                if i not in sh:
                    continue
                freed = sh[i] * (1.0 - keep)
                sh[i] *= keep
                others = [j for j in sh if j not in capped]
                base = sum(weight[j] for j in others)
                for j in others:
                    sh[j] += freed * weight[j] / base
    own = [0.0] * len(modelled)
    for sh in shares:
        for i, v in sh.items():
            own[i] += v
    for a, o in zip(modelled, own):
        out[a.player_id] = round(100.0 * o, 4)
    return out


def _hours(a: str, b: str) -> float:
    return (datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds() / 3600


def source_weights(owner: str, sources: list[str]) -> dict[str, dict[str, Any]]:
    """Inverse-MAE weights from stored ownership evaluations; equal when evidence is thin."""
    evals = pit.list_evaluations(owner, "ownership")
    stats: dict[str, dict[str, float]] = {}
    for e in evals:
        mae = (e["metrics"] or {}).get("mae")
        if e["subject"] in sources and mae is not None and e["n"]:
            s = stats.setdefault(e["subject"], {"n": 0, "err": 0.0})
            s["n"] += e["n"]
            s["err"] += mae * e["n"]
    enough = {k: v for k, v in stats.items() if v["n"] >= MIN_EVAL_PLAYERS}
    if len(enough) == len(sources) and sources:
        inv = {k: 1.0 / max(v["err"] / v["n"], 1e-6) for k, v in enough.items()}
        total = sum(inv.values())
        return {
            k: {"weight": inv[k] / total, "basis": "inverse_mae", "n": int(enough[k]["n"])}
            for k in sources
        }
    return {
        k: {
            "weight": 1.0 / len(sources),
            "basis": "equal_insufficient_evidence",
            "n": int(stats.get(k, {}).get("n", 0)),
        }
        for k in sources
    }


def forecast(
    owner: str,
    snapshot: dict[str, Any],
    ruleset: RuleSet,
    at: str | datetime,
    *,
    overrides: dict[str, float] | None = None,
    structural_params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Ownership forecast for one slate as of ``at`` (must be before lock)."""
    view = pit.as_of(owner, snapshot["id"], at)
    held = view["players"]
    players = [
        _P(
            a["player_id"],
            a.get("positions") or [],
            a.get("eligible_slots") or [],
            int(a.get("salary") or 0),
            _latest_projection(view, a["player_id"]),
        )
        for a in snapshot["body"]["athletes"]
    ]
    base = structural_baseline(players, ruleset, structural_params)
    sources = sorted({s for p in held.values() for s in (p.get("ownership") or {})})
    weights = source_weights(owner, sources) if sources else {}
    rows = {}
    stale_sources: set[str] = set()
    for p in players:
        got = (held.get(p.player_id) or {}).get("ownership") or {}
        vals = {}
        for s, v in got.items():
            if _hours(view["asOf"], v["observedAt"]) > STALE_HOURS:
                stale_sources.add(s)
                continue
            vals[s] = float(v["value"])
        if overrides and p.player_id in overrides:
            rows[p.player_id] = {
                "ownership": float(overrides[p.player_id]),
                "method": "owner_override",
            }
        elif vals:
            w = {s: weights[s]["weight"] for s in vals}
            tot = sum(w.values())
            rows[p.player_id] = {
                "ownership": round(sum(vals[s] * w[s] for s in vals) / tot, 4),
                "method": "ensemble" if len(vals) > 1 else f"source:{next(iter(vals))}",
                "sources": sorted(vals),
            }
        elif base[p.player_id] is not None:
            rows[p.player_id] = {"ownership": base[p.player_id], "method": "structural_baseline"}
        else:
            rows[p.player_id] = {"ownership": None, "method": "not_modelled"}
    known = [r["ownership"] for r in rows.values() if r["ownership"] is not None]
    return {
        "snapshotId": snapshot["id"],
        "asOf": view["asOf"],
        "inputsDigest": view["digest"],
        "models": {
            STRUCTURAL_ID: {
                "params": {**STRUCTURAL_PRIOR, **(structural_params or {})},
                "calibrated": bool(structural_params),
            },
            ENSEMBLE_ID: {"weights": weights},
        },
        "staleSources": sorted(stale_sources),
        "players": rows,
        "totalPercent": round(sum(known), 2),
        "expectedTotalPercent": 100.0 * len(ruleset.slots),
        "notModelled": sum(1 for r in rows.values() if r["ownership"] is None),
    }


def fit_structural(samples: list[dict[str, Any]], ruleset_of) -> dict[str, Any]:
    """Refit bv/bp by grid search on SETTLED slates (chronological training data only).

    ``samples``: [{"players": [_P-like], "ruleset": RuleSet key, "actual": {pid: pct}}].
    Returns the best params and their training MAE — training error, never
    evidence of improvement (that needs a later holdout through ``pit.promote``).
    """
    grid = [x / 4 for x in range(0, 13)]
    best = None
    for bv in grid:
        for bp in grid:
            errs = []
            for s in samples:
                pred = structural_baseline(
                    s["players"], ruleset_of(s["ruleset"]), {"bv": bv, "bp": bp}
                )
                errs += [
                    abs(pred[k] - v) for k, v in s["actual"].items() if pred.get(k) is not None
                ]
            if errs:
                mae = sum(errs) / len(errs)
                if best is None or mae < best[0]:
                    best = (mae, bv, bp, len(errs))
    if best is None:
        return {"params": None, "reason": "no scorable samples"}
    return {
        "params": {"bv": best[1], "bp": best[2]},
        "trainingMae": round(best[0], 4),
        "n": best[3],
        "note": "Training error only — improvement must be shown on a later holdout.",
    }


def score_forecast(fc: dict[str, Any], actual: dict[str, float]) -> dict[str, Any]:
    """Score the ensemble AND each component separately against realized ownership."""
    by_method: dict[str, dict[str, float]] = {}
    overall: dict[str, float] = {}
    for pid, r in fc["players"].items():
        if r["ownership"] is None:
            continue
        overall[pid] = r["ownership"]
        by_method.setdefault(r["method"].split(":")[0], {})[pid] = r["ownership"]
    return {
        "overall": metrics.ownership_scorecard(overall, actual),
        "byMethod": {m: metrics.ownership_scorecard(v, actual) for m, v in by_method.items()},
    }


def _slate_size_bucket(games: int) -> str:
    return "1" if games <= 1 else "2-4" if games <= 4 else "5-9" if games <= 9 else "10+"


def evaluate_against_results(
    owner: str, snapshot: dict[str, Any], ruleset: RuleSet, realized: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Score every ownership forecast knowable AT LOCK against realized %Drafted.

    Components are scored separately (each source's own numbers, the ensemble,
    the structural baseline) and each is stored as a ``pit`` evaluation scoped by
    sport / platform / format / slate size — the data future ensemble weights
    and model promotion read.  No lock, no evaluation: an unprovable pre-lock
    forecast is not evidence.
    """
    if pit.get_slate(owner, snapshot["id"]) is None:
        pit.capture_snapshot(owner, snapshot)
    slate = pit.get_slate(owner, snapshot["id"])
    if slate["lockAt"] is None:
        return {
            "state": "unavailable",
            "reason": "Slate lock time unknown; no pre-lock forecast to score.",
        }
    actual = {
        pid: float(r["ownership"]) for pid, r in realized.items() if r.get("ownership") is not None
    }
    if not actual:
        return {"state": "unavailable", "reason": "No realized ownership in the results."}
    fc = forecast(owner, snapshot, ruleset, slate["lockAt"])
    view = pit.as_of(owner, snapshot["id"], slate["lockAt"])
    scope = {
        "sport": slate["sport"],
        "platform": slate["platform"],
        "format": slate["format"],
        "slateSize": _slate_size_bucket(len(slate["games"])),
    }
    refs = {"snapshotId": snapshot["id"], "asOf": fc["asOf"], "inputsDigest": fc["inputsDigest"]}
    stored = []
    per_source: dict[str, dict[str, float]] = {}
    for pid, kinds in view["players"].items():
        for src, v in (kinds.get("ownership") or {}).items():
            per_source.setdefault(src, {})[pid] = float(v["value"])
    for src, values in per_source.items():
        card = metrics.ownership_scorecard(values, actual)
        if card:
            stored.append(
                pit.record_evaluation(owner, "ownership", src, scope, card["n"], card, refs)
            )
    base = structural_baseline(
        [
            _P(
                a["player_id"],
                a.get("positions") or [],
                a.get("eligible_slots") or [],
                int(a.get("salary") or 0),
                _latest_projection(view, a["player_id"]),
            )
            for a in snapshot["body"]["athletes"]
        ],
        ruleset,
    )
    base_card = metrics.ownership_scorecard(
        {k: v for k, v in base.items() if v is not None}, actual
    )
    if base_card:
        stored.append(
            pit.record_evaluation(
                owner,
                "ownership",
                f"model:{STRUCTURAL_ID}@prior",
                scope,
                base_card["n"],
                base_card,
                refs,
            )
        )
    scored = score_forecast(fc, actual)
    if scored["overall"]:
        stored.append(
            pit.record_evaluation(
                owner,
                "ownership",
                f"model:{ENSEMBLE_ID}",
                scope,
                scored["overall"]["n"],
                scored["overall"],
                refs,
            )
        )
    return {
        "state": "evaluated",
        "scope": scope,
        "sources": {s: metrics.ownership_scorecard(v, actual) for s, v in per_source.items()},
        "structuralBaseline": base_card,
        "forecast": scored,
        "stored": len(stored),
        "refs": refs,
        # The as-of-lock forecast itself, for downstream evaluations (duplication).
        "forecastOwnership": {
            pid: r["ownership"] for pid, r in fc["players"].items() if r["ownership"] is not None
        },
        "note": "Scored as-of lock. One slate is one sample of players, not evidence that any method is better.",
    }


# The owner's own import is the projection the model uses; a pulled source never
# silently replaces it.  Other sources fill in only where the owner has nothing.
PROJECTION_PREFERENCE = ("owner_import", "platform_season_average")


def _latest_projection(view: dict[str, Any], pid: str) -> float | None:
    got = ((view["players"].get(pid) or {}).get("projection")) or {}
    for src in PROJECTION_PREFERENCE:
        if src in got:
            return float(got[src]["value"])
    latest = max(got.values(), key=lambda v: v["observedAt"], default=None)
    return None if latest is None else float(latest["value"])
