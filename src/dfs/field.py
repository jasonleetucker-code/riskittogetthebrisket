"""Field model: plausible OPPONENT lineups, and how well the field fits its targets (DFS-MOD-05).

Not "run our optimizer many times" — opponents are not optimizing our
projections.  The baseline generator is auditable and every assumption is a
named, versioned parameter:

1. **Ownership-weighted sequential sampling.**  Slots are filled in the rule
   set's order; each pick is drawn in proportion to a per-player weight among
   the players who are eligible, unused (identity-aware: never a captain and
   his own flex row), and whose salary still leaves the remaining slots
   fillable at their cheapest.  The finished lineup must pass the INDEPENDENT
   validator (``optimizer.validate_lineup``) and use at least
   ``min_salary_share`` of the cap (fields rarely leave much salary unspent).
2. **Stacking tendency.**  After each pick, players the correlation model says
   move WITH that pick get their weight multiplied by
   ``1 + stack_strength × rho`` (only positive rho) — the field's habit of
   stacking, expressed through the same correlation priors the simulator uses.
3. **Raking to target ownership.**  Salary and legality constraints distort
   naive sampling, so weights are re-scaled ``w *= (target / realized)^eta``
   over a few rounds; the remaining gap is REPORTED (``fieldFit``), not hidden.

The field is represented by a weighted SAMPLE of at most ``MAX_FIELD_SAMPLE``
lineups; a contest of any size is simulated by weighting it.  Seeded and
bounded; numpy/Python only, never the MILP (ADR-DFS-012).
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Any

from src.dfs import correlation
from src.dfs.optimizer import validate_lineup
from src.dfs.rules import RuleSet

MODEL_ID = "field.sequential_raked"
MODEL_VERSION = "1.0.0"
MAX_FIELD_SAMPLE = 20_000
DEFAULT_PARAMS = {
    "min_salary_share": 0.97,  # prior: GPP fields rarely leave >3% of the cap unused
    "stack_strength": 1.5,  # prior: how strongly picks pull their positively correlated partners
    "rake_rounds": 4,
    "rake_eta": 0.8,
    "max_attempts_per_lineup": 60,
}


@dataclass
class FieldResult:
    lineups: list[tuple[str, ...]]  # slot-ordered player IDs
    params: dict[str, Any]
    fit: dict[str, Any]
    rejected_attempts: int
    exhausted: int


def _identity(a: Any) -> str:
    return getattr(a, "identity", a.player_id)


def generate(
    athletes: list[Any],
    ruleset: RuleSet,
    ownership: dict[str, float],
    *,
    sport: str,
    size: int,
    seed: int,
    params: dict[str, Any] | None = None,
) -> FieldResult:
    """``size`` legal field lineups whose player frequencies are raked toward ``ownership`` (%).

    Players without an ownership target are not drafted: a field model cannot
    invent interest in a player it has no forecast for (reported in ``fit``).
    """
    if not 1 <= size <= MAX_FIELD_SAMPLE:
        raise ValueError(f"field sample size must be 1..{MAX_FIELD_SAMPLE}")
    p = {**DEFAULT_PARAMS, **(params or {})}
    pool = [
        a for a in athletes if ownership.get(a.player_id) is not None and ownership[a.player_id] > 0
    ]
    by_id = {a.player_id: a for a in pool}
    target = {a.player_id: ownership[a.player_id] / 100.0 for a in pool}
    corr = correlation.pairs(pool, sport)["pairs"]
    partners: dict[str, list[tuple[str, float]]] = {}
    for (x, y), rho in corr.items():
        if rho > 0:
            partners.setdefault(x, []).append((y, rho))
            partners.setdefault(y, []).append((x, rho))
    by_ident: dict[str, list[str]] = {}
    for a in pool:
        by_ident.setdefault(_identity(a), []).append(a.player_id)
    eligible = [[a.player_id for a in pool if ruleset.eligible(a, s)] for s in ruleset.slots]
    min_salary = [min((by_id[pid].salary for pid in e), default=None) for e in eligible]
    cap = ruleset.salary_cap
    floor = p["min_salary_share"] * cap
    weights = dict(target)
    rnd = random.Random(seed)
    lineups: list[tuple[str, ...]] = []
    rejected = exhausted = 0
    rounds = max(1, int(p["rake_rounds"]))
    for r in range(rounds):
        lineups, rejected, exhausted = [], 0, 0
        for _ in range(size):
            lu = None
            for _attempt in range(int(p["max_attempts_per_lineup"])):
                lu = _one(
                    rnd,
                    ruleset,
                    eligible,
                    min_salary,
                    by_id,
                    weights,
                    partners,
                    by_ident,
                    cap,
                    p["stack_strength"],
                )
                if lu is None:
                    rejected += 1
                    continue
                if sum(by_id[x].salary for x in lu) < floor or validate_lineup(
                    list(zip([s.name for s in ruleset.slots], lu)), ruleset, by_id
                ):
                    rejected += 1
                    lu = None
                    continue
                break
            if lu is None:
                exhausted += 1
            else:
                lineups.append(lu)
        if r == rounds - 1 or not lineups:
            break
        freq = Counter(x for lu in lineups for x in lu)
        for pid, t in target.items():
            realized = freq.get(pid, 0) / len(lineups)
            ratio = t / max(realized, 0.5 / len(lineups))
            weights[pid] = weights[pid] * ratio ** p["rake_eta"]
    return FieldResult(
        lineups, p, fit_metrics(lineups, by_id, ownership, ruleset), rejected, exhausted
    )


def _one(
    rnd, ruleset, eligible, min_salary, by_id, weights, partners, by_ident, cap, stack_strength
):
    # Fill slots in a RANDOM order per lineup.  A fixed order (QB..DST) spends the
    # budget on early slots and leaves the last slot only its cheapest player —
    # measured: the $1,000 DST was drafted 97.5% of the time against a 3.3% target,
    # and raking could not fix it (weights are moot when one player is affordable).
    n = len(ruleset.slots)
    order = list(range(n))
    rnd.shuffle(order)
    chosen: list[str | None] = [None] * n
    used_idents: set[str] = set()
    boost: dict[str, float] = {}
    spent = 0
    for step, i in enumerate(order):
        rest_min = sum(min_salary[j] or 0 for j in order[step + 1 :])
        cands, ws = [], []
        for pid in eligible[i]:
            a = by_id[pid]
            if _identity(a) in used_idents or spent + a.salary + rest_min > cap:
                continue
            w = weights.get(pid, 0.0) * boost.get(pid, 1.0)
            if w > 0:
                cands.append(pid)
                ws.append(w)
        if not cands:
            return None
        pick = rnd.choices(cands, weights=ws, k=1)[0]
        chosen[i] = pick
        used_idents.add(_identity(by_id[pick]))
        spent += by_id[pick].salary
        # Correlation pairs are keyed by athlete IDENTITY; boost every row of each partner.
        for other_ident, rho in partners.get(_identity(by_id[pick]), []):
            for opid in by_ident.get(other_ident, []):
                boost[opid] = boost.get(opid, 1.0) * (1.0 + stack_strength * rho)
    return tuple(chosen)


def fit_metrics(
    lineups: list[tuple[str, ...]],
    by_id: dict[str, Any],
    ownership: dict[str, float],
    ruleset: RuleSet,
) -> dict[str, Any]:
    """How the generated field compares with its targets and with itself."""
    from src.dfs import metrics

    n = len(lineups)
    if not n:
        return {"lineups": 0}
    freq = Counter(x for lu in lineups for x in lu)
    realized = {pid: 100.0 * c / n for pid, c in freq.items()}
    target = {pid: v for pid, v in ownership.items() if pid in by_id}
    gap = metrics.point_forecast([(realized.get(pid, 0.0), t) for pid, t in target.items()])
    salaries = sorted(sum(by_id[x].salary for x in lu) for lu in lineups)
    q = lambda f: salaries[min(n - 1, int(f * n))]  # noqa: E731
    shapes = Counter(
        "-".join(str(c) for c in sorted(Counter(by_id[x].team for x in lu).values(), reverse=True))
        for lu in lineups
    )
    dups = Counter(frozenset(lu) for lu in lineups)
    return {
        "lineups": n,
        # Realized field frequency vs target ownership (points of %): how far raking got.
        "ownershipGap": gap,
        "salaryUsed": {"p10": q(0.1), "p50": q(0.5), "p90": q(0.9), "cap": ruleset.salary_cap},
        "stackShapes": [{"shape": s, "share": round(c / n, 4)} for s, c in shapes.most_common(8)],
        "distinctLineups": len(dups),
        "sampleDuplicateShare": round(sum(c for c in dups.values() if c > 1) / n, 4),
    }


def implied_ownership(
    athletes: list[Any],
    ruleset: RuleSet,
    *,
    sport: str,
    weights: dict[str, float],
    size: int = 4000,
    seed: int = 0,
    params: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Ownership read off a generated field: FEASIBLE by construction (challenger, DFS-MOD-02).

    The structural baseline spreads each slot's 100% without regard to the
    salary cap, so its targets can be unreachable together (measured on the NFL
    fixture: an irreducible ~5.4-point MAE gap no raking closes, while a feasible
    target rakes to ~0.4).  Sampling legal lineups from the same weights and
    reading off frequencies respects the cap.  Whether it predicts REAL
    ownership better is an open question for settled results, not this module.
    """
    res = generate(
        athletes,
        ruleset,
        weights,
        sport=sport,
        size=size,
        seed=seed,
        params={"rake_rounds": 1, **(params or {})},
    )
    freq = Counter(x for lu in res.lineups for x in lu)
    n = max(len(res.lineups), 1)
    return {
        a.player_id: round(100.0 * freq.get(a.player_id, 0) / n, 4)
        for a in athletes
        if a.player_id in weights
    }
