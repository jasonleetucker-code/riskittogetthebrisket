"""Chronological point-in-time backtest over settled contests (DFS-MOD-09 / 10 / 11).

For each settled contest, OLDEST LOCK FIRST:

1. **Freeze** at T = lock.  Every input comes from ``pit.as_of(T, pre_lock)``
   and its digest is taken BEFORE the result record is opened — the code path
   cannot read truth while forecasting.
2. **Forecast** ownership three ways (structural prior, field-implied
   challenger, source ensemble) and read each projection source as held at T.
3. **Replay the decision** (optional, costly): candidates → simulation →
   selection, and the same-size projected-points baseline, via the SAME
   ``pipeline`` / ``portfolio_opt`` code the live endpoints use.
4. **Reveal and score**: ownership + projection forecasts vs realized; the naive
   duplication model vs observed copies; replayed portfolios get their
   COUNTERFACTUAL realized payout — each lineup's realized points ranked against
   the contest's real full-field score distribution with exact ties.  A lineup
   holding a player the results do not score is ``unscorable`` (never 0 points).
5. **Aggregate** with sample sizes and store evaluations for champion/challenger
   (``pit.promote``) — nothing is promoted here.

A replayed decision is labelled ``backtest``: made after the fact, it is
historical evidence, never forward evidence.
"""

from __future__ import annotations

import math
from typing import Any

from src.dfs import field, metrics, ownership, pit, store
from src.dfs.contests import Contest, contest_from_dict, tied_payout
from src.dfs.imports import SlateAthlete
from src.dfs.rules import get_ruleset


def realized_lineup_points(
    lineup: list[str], realized: dict[str, dict[str, Any]], ruleset: Any
) -> float | None:
    """Sum of realized points (slot multipliers applied); None if any player is unscored."""
    total = 0.0
    for slot, pid in zip(ruleset.slots, lineup):
        pts = (realized.get(pid) or {}).get("points")
        if pts is None:
            return None
        total += pts * ruleset.points_multiplier(slot.name)
    return total


def realized_payouts(
    contest: Contest, points_counts: list[tuple[float, int]], our_scores: list[float | None]
) -> list[dict[str, Any]]:
    """What each hypothetical entry WOULD have won in the real field (our entries joined in)."""
    field_counts = {float(p): int(c) for p, c in points_counts}
    ours = [s for s in our_scores if s is not None]
    out = []
    for s in our_scores:
        if s is None:
            out.append({"state": "unscorable"})
            continue
        above = sum(c for p, c in field_counts.items() if p > s) + sum(1 for o in ours if o > s)
        tied = field_counts.get(s, 0) + sum(1 for o in ours if o == s)
        pay = tied_payout(contest.ladder, above + 1, tied, contest.tie_rule)
        out.append(
            {
                "state": pay["state"],
                "rank": above + 1,
                "tiedWith": tied - 1,
                "payoutCents": pay.get("eachCents"),
            }
        )
    return out


def _settled_contests(owner: str, items: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Resolve {resultId, contestId?} items, sorted by slate lock (chronological)."""
    rows = []
    for it in items:
        res = store.get_result(owner, it["resultId"])
        if res is None:
            continue
        snap = store.get_snapshot(owner, res["snapshotId"])
        if snap is None:
            continue
        if pit.get_slate(owner, snap["id"]) is None:
            pit.capture_snapshot(owner, snap)
        slate = pit.get_slate(owner, snap["id"])
        cref = it.get("contestId") or (res.get("contestRef") or {}).get("contestId")
        crec = store.get_contest(owner, cref) if cref else None
        rows.append(
            {
                "resultId": it["resultId"],
                "snapshot": snap,
                "slate": slate,
                "contest": contest_from_dict(crec["contest"]) if crec else None,
            }
        )
    return sorted(rows, key=lambda r: (r["slate"]["lockAt"] or "9999", r["resultId"]))


def run(
    owner: str,
    items: list[dict[str, str]],
    *,
    replay_portfolio: bool = False,
    entries: int = 3,
    sims: int = 400,
    field_sample: int = 800,
    seed: int = 1,
    allow_priors: bool = False,
    record: bool = True,
) -> dict[str, Any]:
    from src.dfs import portfolio_opt
    from src.dfs.optimizer import Constraints

    per_contest = []
    agg: dict[str, list[tuple[float, float]]] = {}
    realized_profit: dict[str, list[float]] = {
        "optimizer": [],
        "baseline": [],
        "optimizerMinusBaseline": [],
    }
    predicted_vs_realized: list[tuple[float, float]] = []
    skipped = []
    for c in _settled_contests(owner, items):
        snap, slate = c["snapshot"], c["slate"]
        if slate["lockAt"] is None:
            skipped.append({"resultId": c["resultId"], "reason": "lock_unknown"})
            continue
        rs = get_ruleset(snap["ruleset"].split("@", 1)[0])
        t = slate["lockAt"]
        # ── 1-2. freeze + forecast (no result record opened yet) ─────────────
        view = pit.as_of(owner, snap["id"], t)
        digest_before = view["digest"]
        fc = ownership.forecast(owner, snap, rs, t)
        athletes = [SlateAthlete(**a) for a in snap["body"]["athletes"]]
        struct = ownership.structural_baseline(
            [
                ownership._P(
                    a.player_id,
                    a.positions,
                    a.eligible_slots,
                    a.salary,
                    ownership._latest_projection(view, a.player_id),
                )
                for a in athletes
            ],
            rs,
        )
        weights = {k: v for k, v in struct.items() if v}
        implied = (
            field.implied_ownership(
                athletes, rs, sport=rs.sport, weights=weights, size=1500, seed=seed
            )
            if weights
            else {}
        )
        forecasts = {
            "ownership.structural@prior": {k: v for k, v in struct.items() if v is not None},
            "ownership.field_implied": implied,
            "ownership.ensemble": {
                k: r["ownership"] for k, r in fc["players"].items() if r["ownership"] is not None
            },
        }
        proj_sources: dict[str, dict[str, float]] = {}
        for pid, kinds in view["players"].items():
            for src, v in (kinds.get("projection") or {}).items():
                proj_sources.setdefault(src, {})[pid] = float(v["value"])
        replay = None
        if replay_portfolio and c["contest"] is not None:
            try:
                replay = portfolio_opt.build_portfolio(
                    owner,
                    snap,
                    rs,
                    c["contest"],
                    t,
                    base=Constraints(),
                    entries=entries,
                    sims=sims,
                    field_sample=field_sample,
                    seed=seed,
                    allow_priors=allow_priors,
                )
            except (ValueError, pit.PitError) as exc:
                replay = {"error": getattr(exc, "code", "error"), "message": str(exc)}
        if pit.as_of(owner, snap["id"], t)["digest"] != digest_before:
            raise RuntimeError(
                "pre-lock inputs changed during the replay"
            )  # never silently continue
        # ── 4. reveal ────────────────────────────────────────────────────────
        res = store.get_result(owner, c["resultId"])
        realized = res["realized"]
        actual_own = {
            p: r["ownership"] for p, r in realized.items() if r.get("ownership") is not None
        }
        actual_pts = {p: r["points"] for p, r in realized.items() if r.get("points") is not None}
        row: dict[str, Any] = {
            "resultId": c["resultId"],
            "lockAt": t,
            "sport": slate["sport"],
            "platform": slate["platform"],
            "inputsDigest": digest_before,
            "scores": {},
        }
        for name, f in forecasts.items():
            card = metrics.ownership_scorecard(f, actual_own)
            row["scores"][name] = card
            if card:
                agg.setdefault(name, []).extend(
                    (f[k], actual_own[k]) for k in f.keys() & actual_own.keys()
                )
        for src, f in proj_sources.items():
            pairs = [(f[k], actual_pts[k]) for k in f.keys() & actual_pts.keys()]
            row["scores"][f"projection:{src}"] = metrics.point_forecast(pairs)
            agg.setdefault(f"projection:{src}", []).extend(pairs)
        if replay and "result" in replay and c["contest"] is not None:
            chosen = [r["lineup"] for r in replay["result"]["perLineup"]]
            fee = c["contest"].entry_fee_cents
            opt_scores = [realized_lineup_points(lu, realized, rs) for lu in chosen]
            opt_pay = realized_payouts(c["contest"], res["pointsCounts"], opt_scores)
            predicted = replay["result"]["portfolio"]["expectedPayoutCents"]
            row["replay"] = {
                "decisionId": replay["decisionId"],
                "realized": opt_pay,
                "predictedPortfolioPayoutCents": predicted,
            }
            base_lus = replay.get("baselineLineups") or []
            base_pay = realized_payouts(
                c["contest"],
                res["pointsCounts"],
                [realized_lineup_points(lu, realized, rs) for lu in base_lus],
            )
            row["replay"]["baselineRealized"] = base_pay
            opt_ok = all(p["state"] == "exact" for p in opt_pay)
            base_ok = bool(base_pay) and all(p["state"] == "exact" for p in base_pay)
            if opt_ok:
                won = sum(p["payoutCents"] for p in opt_pay)
                realized_profit["optimizer"].append(won - fee * len(chosen))
                predicted_vs_realized.append((predicted, float(won)))
                row["replay"]["realizedProfitCents"] = won - fee * len(chosen)
            if base_ok:
                base_won = sum(p["payoutCents"] for p in base_pay) - fee * len(base_lus)
                realized_profit["baseline"].append(base_won)
                if opt_ok:  # paired on the same contest
                    realized_profit["optimizerMinusBaseline"].append(
                        row["replay"]["realizedProfitCents"] - base_won
                    )
        per_contest.append(row)
    summary = {name: metrics.point_forecast(pairs) for name, pairs in agg.items()}
    roi = {k: _mean_ci(v) for k, v in realized_profit.items() if v}
    out = {
        "contests": len(per_contest),
        "skipped": skipped,
        "perContest": per_contest,
        "summary": summary,
        "realizedProfitCents": roi,
        "contestModelCalibration": metrics.point_forecast(predicted_vs_realized),
        "note": "Historical replay (made after the fact): historical evidence, never forward evidence. "
        "Sample sizes are shown; a handful of contests supports no promotion.",
    }
    if record and per_contest:
        window = {"windowStart": per_contest[0]["lockAt"], "windowEnd": per_contest[-1]["lockAt"]}
        for name, card in summary.items():
            if card:
                pit.record_evaluation(
                    owner, "backtest", name, window, card["n"], card, {"contests": len(per_contest)}
                )
    return out


def _mean_ci(xs: list[float]) -> dict[str, Any]:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else None
    return {
        "n": n,
        "meanCents": round(m, 2),
        "ci95Cents": None
        if sd is None
        else (round(m - 1.96 * sd / math.sqrt(n), 2), round(m + 1.96 * sd / math.sqrt(n), 2)),
    }
