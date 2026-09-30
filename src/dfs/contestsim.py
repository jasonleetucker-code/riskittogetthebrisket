"""Contest Monte Carlo: what a set of our lineups might WIN in one exact contest (DFS-MOD-07).

Each simulation draws every player's score JOINTLY (``distributions.sample`` —
Gaussian copula over the correlation priors), scores the field sample and our
lineups on the SAME draw, ranks our lineups among the field (binary search in
each simulation's sorted field scores, scaled from the sample of M lineups to
the real field of N), and pays them from the exact ladder:

* copies of our own lineup are drawn per simulation from the duplication model
  (Poisson with the expected-copies rate), and we split the tied places with
  them — exact split-position averaging over the prize-by-rank table;
* our other entries occupy places too, so a PORTFOLIO is ranked jointly;
* a contest whose tie rule is unknown is simulated under the split rule and the
  result says ``assumedTieRule`` — a forecast may assume, settlement may not.

Outputs per lineup and for the portfolio: expected payout and profit, ROI,
P(cash), P(top 1%), P(win), payout quantiles, P(loss) — each with its Monte Carlo
standard error.  Ticket / non-cash prizes are excluded from cash EV and counted
separately.  This is a MODEL OUTPUT under stated assumptions, never evidence of
profitability.  Bounded, seeded, vectorized numpy; never the MILP (ADR-DFS-012).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from src.dfs.contests import Contest, prize_at
from src.dfs.distributions import PlayerDistribution, sample
from src.dfs.rules import RuleSet

MODEL_ID = "contest.montecarlo"
MODEL_VERSION = "1.0.0"
MAX_SIMS = 5_000
MAX_CELLS = 20_000_000  # sims × field sample, the dominant memory term


@dataclass
class SimSetup:
    ruleset: RuleSet
    contest: Contest
    field_size: int
    dists: list[PlayerDistribution]
    corr: dict[tuple[str, str], float]
    field_lineups: list[tuple[str, ...]]
    sims: int
    seed: int


def prize_table(contest: Contest, field_size: int) -> tuple[Any, int]:
    """Cash cents at ranks 1..N (index 0 = rank 1) and the count of non-cash places."""
    import numpy as np

    prizes = np.array([prize_at(contest.ladder, r) for r in range(1, field_size + 1)], dtype=float)
    noncash = sum(
        min(b.max_rank, field_size) - b.min_rank + 1
        for b in contest.ladder
        if b.kind != "cash" and b.min_rank <= field_size
    )
    return prizes, noncash


class ContestSim:
    def __init__(self, setup: SimSetup):
        import numpy as np

        if not 1 <= setup.sims <= MAX_SIMS:
            raise ValueError(f"simulations must be 1..{MAX_SIMS}")
        if setup.sims * max(len(setup.field_lineups), 1) > MAX_CELLS:
            raise ValueError("simulations × field sample exceeds the memory budget")
        if not setup.field_lineups:
            raise ValueError("the field sample is empty")
        self.s = setup
        self.col = {d.player_id: j for j, d in enumerate(setup.dists)}
        drawn = sample(setup.dists, setup.corr, setup.sims, setup.seed)
        self.points = drawn["points"]  # sims × players
        self.correlation_repaired = drawn["correlationRepaired"]
        self.uncalibrated = drawn["uncalibratedPlayers"]
        self.mult = np.array(
            [setup.ruleset.points_multiplier(sl.name) for sl in setup.ruleset.slots]
        )
        field = self.score(setup.field_lineups)  # M × sims
        self.field_sorted = np.sort(field, axis=0)  # per simulation, ascending
        self.prizes, self.noncash_places = prize_table(setup.contest, setup.field_size)
        self.cum = np.concatenate([[0.0], np.cumsum(self.prizes)])
        self.rng = np.random.default_rng(setup.seed + 1)

    def score(self, lineups: list[tuple[str, ...]]) -> Any:
        """Lineups × sims fantasy points (slot multipliers applied once, at the slot)."""
        import numpy as np

        missing = sorted({p for lu in lineups for p in lu if p not in self.col})
        if missing:
            raise KeyError(f"no outcome distribution for {len(missing)} player(s): {missing[:5]}")
        idx = np.array([[self.col[p] for p in lu] for lu in lineups])  # L × slots
        # points[:, idx] is sims × L × slots; weight each slot, sum, return L × sims.
        return (self.points[:, idx] * self.mult[None, None, :]).sum(axis=2).T

    def payouts(self, lineups: list[tuple[str, ...]], expected_copies: list[float]) -> Any:
        """Lineups × sims cash payout (cents), ranking our entries JOINTLY with the field."""
        import numpy as np

        ours = self.score(lineups)  # L × S
        n_ours = len(lineups)
        m = self.field_sorted.shape[0]
        others = self.s.field_size - n_ours
        scale = others / m
        out = np.zeros_like(ours)
        for s in range(ours.shape[1]):
            col = self.field_sorted[:, s]
            right = np.searchsorted(col, ours[:, s], side="right")
            left = np.searchsorted(col, ours[:, s], side="left")
            above_field = (m - right) * scale
            for i in range(n_ours):
                above_ours = float(np.sum(ours[:, s] > ours[i, s]))
                # Outcomes are continuous, so an EQUAL field score is an identical lineup.
                # If the field sample holds copies of ours, they ARE the copies (scaled);
                # otherwise draw copies from the duplication model — never both.
                equal = int(right[i] - left[i])
                if equal:
                    copies = int(round(equal * scale))
                else:
                    copies = self.rng.poisson(expected_copies[i]) if expected_copies[i] > 0 else 0
                first = int(math.floor(above_field[i] + above_ours)) + 1
                last = min(first + copies, self.s.field_size)
                first = min(first, self.s.field_size)
                out[i, s] = (self.cum[last] - self.cum[first - 1]) / (last - first + 1)
        return out


def summarize(
    payouts: Any, fee_cents: int, field_size: int, ranks_top1: Any = None
) -> dict[str, Any]:
    """Distribution summary of a payout vector (one entry or a whole portfolio), with MC errors."""
    import numpy as np

    p = np.asarray(payouts, dtype=float)
    n = p.size
    ev = float(p.mean())
    se = float(p.std(ddof=1) / math.sqrt(n)) if n > 1 else None

    def prob(mask):
        x = float(np.mean(mask))
        return {"p": round(x, 5), "se": round(math.sqrt(x * (1 - x) / n), 5)}

    return {
        "sims": n,
        "expectedPayoutCents": round(ev, 2),
        "expectedPayoutSe": None if se is None else round(se, 2),
        "expectedProfitCents": round(ev - fee_cents, 2),
        "roi": round((ev - fee_cents) / fee_cents, 4) if fee_cents else None,
        "pCash": prob(p > 0),
        "pProfit": prob(p > fee_cents),
        "payoutQuantilesCents": {q: round(float(np.quantile(p, q)), 2) for q in (0.5, 0.9, 0.99)},
        **({"pTop1Pct": prob(ranks_top1)} if ranks_top1 is not None else {}),
    }


def simulate(
    setup: SimSetup, lineups: list[tuple[str, ...]], expected_copies: list[float]
) -> dict[str, Any]:
    """Per-lineup and portfolio outcomes for ``lineups`` entered together in the contest."""
    import numpy as np

    sim = ContestSim(setup)
    pay = sim.payouts(lineups, expected_copies)  # L × S
    fee = setup.contest.entry_fee_cents
    top_prize = sim.prizes[0]
    one_pct = max(1, int(setup.field_size * 0.01))
    top1_threshold = sim.prizes[one_pct - 1] if one_pct <= len(sim.prizes) else 0.0
    per = []
    for i, lu in enumerate(lineups):
        row = pay[i]
        per.append(
            {
                "lineup": list(lu),
                "expectedCopies": round(expected_copies[i], 4),
                **summarize(row, fee, setup.field_size),
                "pWin": round(float(np.mean(row >= top_prize)) if top_prize > 0 else 0.0, 5),
                "pTop1PctPayout": round(
                    float(np.mean(row >= top1_threshold)) if top1_threshold > 0 else 0.0, 5
                ),
            }
        )
    total = pay.sum(axis=0)
    portfolio = summarize(total, fee * len(lineups), setup.field_size)
    assumptions = []
    if setup.contest.tie_rule != "split_positions":
        assumptions.append("assumedTieRule: split_positions (the contest's tie rule is not known)")
    if sim.uncalibrated:
        assumptions.append(f"{sim.uncalibrated} player(s) use uncalibrated spread priors")
    if sim.noncash_places:
        assumptions.append(f"{sim.noncash_places} non-cash place(s) excluded from cash EV")
    return {
        "model": f"{MODEL_ID}@{MODEL_VERSION}",
        "sims": setup.sims,
        "seed": setup.seed,
        "fieldSize": setup.field_size,
        "fieldSample": len(setup.field_lineups),
        "correlationRepaired": sim.correlation_repaired,
        "perLineup": per,
        "portfolio": portfolio,
        "assumptions": assumptions,
        "note": "Model output under stated assumptions — not evidence of profitability.",
    }
