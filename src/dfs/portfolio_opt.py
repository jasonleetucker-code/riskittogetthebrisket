"""Portfolio optimization against a contest's simulated payouts (DFS-MOD-08).

Selects a SET of entries, not a ranking of lineups:

1. **Candidates.**  The projected-points baseline builds (the existing MILP),
   plus "sample-optimal" lineups — the same MILP re-solved on joint outcome
   draws, which surfaces the upside lineups a mean projection never picks.  All
   solves go through the pinned solver thread (ADR-DFS-012), serially, bounded.
2. **Payout matrix.**  Every candidate is simulated against the SAME field and
   draws (``pipeline``), giving candidates × simulations payouts.
3. **Greedy selection** under a chosen objective family — ``ev`` (expected
   profit), ``log_growth`` (bankroll-aware; needs a stated bankroll), or
   ``mean_downside`` (EV minus λ × downside deviation) — honouring per-player
   exposure caps and the contest's entry ceiling.  No Kelly sizing: the model's
   EV is itself uncertain.
4. **Recommended entry count** stops adding entries once the lower 90% bound of
   the next entry's marginal expected profit reaches zero — conservative by
   design, and never above what the owner asked for or may enter.
5. **Final joint evaluation** of the chosen set (our entries ranked together),
   a PAIRED comparison with the projected-points portfolio (difference and its
   standard error, same draws), and a frozen ``pit`` decision with selected and
   rejected candidates, objective terms and the inputs digest.

The baseline comparison is WITHIN the model: it says the optimizer does what
the model rewards, not that the model is right.  Nothing here enters or
submits anything.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from src.dfs import contests, duplication, pipeline, pit
from src.dfs.imports import SlateAthlete
from src.dfs.optimizer import Constraints, optimize

OBJECTIVES = ("ev", "log_growth", "mean_downside")
MAX_CANDIDATES = 80
MAX_ENTRIES = 150
Z90 = 1.2816


def candidates(
    prep: pipeline.Prepared,
    sim: Any,
    base: Constraints,
    *,
    sample_optimal: int,
    baseline: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Distinct candidate lineups with their origin (``baseline`` | ``sample:<k>``)."""
    import numpy as np

    rs = prep.setup.ruleset
    pool = [prep.athletes[pid] for pid in prep.athletes]
    out: dict[frozenset[str], dict[str, Any]] = {}
    res = optimize(
        rs, pool, replace(base, lineups=max(1, baseline), min_unique=max(base.min_unique, 1))
    )
    for lu in res["lineups"]:
        ids = tuple(p["playerId"] for p in lu["players"])
        out.setdefault(
            frozenset(ids), {"lineup": ids, "origin": "baseline", "projection": lu["projection"]}
        )
    col = sim.col
    rng = np.random.default_rng(seed)
    for k in range(sample_optimal):
        # One joint draw of every player's score: the MILP's best lineup IF this happened.
        row = sim.points[rng.integers(0, sim.points.shape[0])]
        overrides = {pid: float(row[j]) for pid, j in col.items()}
        r = optimize(
            rs,
            pool,
            replace(
                base, lineups=1, projection_overrides={**base.projection_overrides, **overrides}
            ),
        )
        for lu in r["lineups"]:
            ids = tuple(p["playerId"] for p in lu["players"])
            out.setdefault(
                frozenset(ids), {"lineup": ids, "origin": f"sample:{k}", "projection": None}
            )
        if len(out) >= MAX_CANDIDATES:
            break
    return list(out.values())[:MAX_CANDIDATES]


def _objective(total: Any, fees: float, kind: str, bankroll: float | None, lam: float) -> float:
    import numpy as np

    if kind == "ev":
        return float(total.mean()) - fees
    if kind == "log_growth":
        wealth = (bankroll - fees + total) / bankroll
        return float(np.mean(np.log(np.maximum(wealth, 1e-9))))
    shortfall = np.minimum(total - fees, 0.0)
    return float(total.mean()) - fees - lam * float(np.sqrt(np.mean(shortfall**2)))


def select(
    pay: Any,
    lineups: list[tuple[str, ...]],
    *,
    fee: int,
    entries: int,
    objective: str,
    bankroll: int | None,
    lam: float,
    max_exposure: float | None,
) -> dict[str, Any]:
    """Greedy portfolio under the objective; returns chosen indices and the marginal trail."""
    import numpy as np

    if objective not in OBJECTIVES:
        raise ValueError(f"objective must be one of {OBJECTIVES}")
    if objective == "log_growth" and (not bankroll or bankroll <= fee * entries):
        raise ValueError("log_growth needs a bankroll larger than the total entry fees")
    chosen: list[int] = []
    total = np.zeros(pay.shape[1])
    counts: dict[str, int] = {}
    trail = []
    cap = None if max_exposure is None else max(1, math.floor(max_exposure * entries))
    for k in range(entries):
        best, best_val = None, None
        for c in range(len(lineups)):
            if c in chosen or (
                cap is not None and any(counts.get(p, 0) >= cap for p in lineups[c])
            ):
                continue
            val = _objective(total + pay[c], fee * (k + 1), objective, bankroll, lam)
            if best_val is None or val > best_val:
                best, best_val = c, val
        if best is None:
            break
        marginal = pay[best] - fee
        se = float(marginal.std(ddof=1) / math.sqrt(len(marginal)))
        trail.append(
            {
                "entry": k + 1,
                "candidate": best,
                "objective": round(best_val, 4),
                "marginalExpectedProfitCents": round(float(marginal.mean()), 2),
                "marginalLower90Cents": round(float(marginal.mean()) - Z90 * se, 2),
            }
        )
        chosen.append(best)
        total = total + pay[best]
        for p in lineups[best]:
            counts[p] = counts.get(p, 0) + 1
    recommended = next(
        (t["entry"] - 1 for t in trail if t["marginalLower90Cents"] <= 0), len(trail)
    )
    return {"chosen": chosen, "trail": trail, "recommendedEntries": recommended}


def build_portfolio(
    owner: str,
    snapshot: dict[str, Any],
    ruleset: Any,
    contest: contests.Contest,
    at: str,
    *,
    base: Constraints,
    entries: int,
    objective: str = "ev",
    bankroll: int | None = None,
    lam: float = 0.5,
    sims: int = 800,
    field_sample: int = 1500,
    seed: int = 1,
    allow_priors: bool = False,
    sample_optimal: int = 30,
    baseline: int = 20,
    spend_limit_cents: int | None = None,
) -> dict[str, Any]:
    import numpy as np

    if not 1 <= entries <= MAX_ENTRIES:
        raise ValueError(f"entries must be 1..{MAX_ENTRIES}")
    cap = contests.entry_upper_bound(contest, spend_limit_cents)
    if cap["upperBound"] is not None:
        entries = min(entries, cap["upperBound"])
    if entries < 1:
        raise pipeline.PipelineError(
            "NO_ENTRIES_ALLOWED", "The contest's entry ceiling allows no new entries.", cap
        )
    athletes = [SlateAthlete(**a) for a in snapshot["body"]["athletes"]]
    prep = pipeline.prepare(
        owner,
        snapshot,
        ruleset,
        contest,
        at,
        sims=sims,
        field_sample=field_sample,
        seed=seed,
        allow_priors=allow_priors,
        must_cover={a.player_id for a in athletes if a.projection is not None},
    )
    from src.dfs.contestsim import ContestSim, simulate

    sim = ContestSim(prep.setup)
    cands = candidates(prep, sim, base, sample_optimal=sample_optimal, baseline=baseline, seed=seed)
    lineups = [c["lineup"] for c in cands]
    rates = [
        (d.get("fitted", d.get("naive", 0.0)) if d["state"] == "estimated" else 0.0)
        for d in pipeline.expected_copies(prep, lineups)
    ]
    # Each candidate ALONE against the field (same draws) — the greedy's currency.
    pay = np.vstack([sim.payouts([lu], [r])[0] for lu, r in zip(lineups, rates)])
    fee = contest.entry_fee_cents
    sel = select(
        pay,
        lineups,
        fee=fee,
        entries=entries,
        objective=objective,
        bankroll=bankroll,
        lam=lam,
        max_exposure=base.max_exposure,
    )
    chosen = [lineups[i] for i in sel["chosen"]]
    final = simulate(prep.setup, chosen, [rates[i] for i in sel["chosen"]])
    # Paired comparison with the projected-points portfolio of the same size, same draws.
    base_idx = [i for i, c in enumerate(cands) if c["origin"] == "baseline"][: len(chosen)]
    comparison = None
    if base_idx:
        base_joint = ContestSim(prep.setup).payouts(
            [lineups[i] for i in base_idx], [rates[i] for i in base_idx]
        )
        ours_joint = ContestSim(prep.setup).payouts(chosen, [rates[i] for i in sel["chosen"]])
        diff = ours_joint.sum(axis=0) - base_joint.sum(axis=0)
        fee_diff = fee * (len(chosen) - len(base_idx))
        comparison = {
            "baselineEntries": len(base_idx),
            "profitDifferenceCents": round(float(diff.mean()) - fee_diff, 2),
            "profitDifferenceSe": round(float(diff.std(ddof=1) / math.sqrt(len(diff))), 2),
            "note": "Within-model comparison on identical draws: the optimizer pursues what the model rewards.",
        }
    rejected = [
        {
            "lineup": list(c["lineup"]),
            "origin": c["origin"],
            "expectedPayoutCents": round(float(pay[i].mean()), 2),
            "reason": "not selected by the greedy objective or blocked by an exposure cap",
        }
        for i, c in enumerate(cands)
        if i not in sel["chosen"]
    ]
    view = pit.as_of(owner, snapshot["id"], at)
    decision = pit.freeze_decision(
        owner,
        snapshot["id"],
        as_of_view=view,
        contest_ref=f"{contest.name}",
        models=[
            {"modelId": "contest.montecarlo", "version": "1.0.0"},
            {"modelId": "field.sequential_raked", "version": "1.0.0"},
            {
                "modelId": duplication.MODEL_ID if prep.dup_params else duplication.NAIVE_ID,
                "version": "1.0.0",
            },
        ],
        objective={"kind": objective, "bankrollCents": bankroll, "lambda": lam},
        constraints={
            "entries": entries,
            "maxExposure": base.max_exposure,
            "entryCeiling": cap["upperBound"],
        },
        selected=[
            {"lineup": list(lu), "origin": cands[i]["origin"]}
            for lu, i in zip(chosen, sel["chosen"])
        ],
        rejected=rejected,
        uncertainty={
            "sims": prep.setup.sims,
            "portfolioEvSe": final["portfolio"]["expectedPayoutSe"],
        },
    )
    return {
        "decisionId": decision["decisionId"],
        "timing": decision["timing"],
        "objective": objective,
        "entriesRequested": entries,
        "entryCeiling": cap,
        "candidates": len(cands),
        "selection": sel,
        "result": final,
        "vsProjectionBaseline": comparison,
        "note": "Decision support only: nothing is entered or submitted. Model output, not evidence of profit.",
    }
