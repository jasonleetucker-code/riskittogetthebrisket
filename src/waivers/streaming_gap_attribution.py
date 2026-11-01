"""IDP streaming GAP ATTRIBUTION -- research / diagnostic only.

Why does the dynasty-safe weekly optimizer (baseline 7 of the IDP streaming
backtest, ``streaming_backtest.DynastySafeOptimizerPolicy``) gain about +0.4
lineup points per decision week over holding, when the league's heaviest
defender streamer ("manager B") gained about +19.9 (2026)?

This module answers that by COUNTERFACTUAL ABLATION: it re-runs baseline 7
with exactly ONE constraint relaxed at a time (plus one all-relaxed run), on
the same frozen season data, and reports each run's gain over the same hold
reference.  It also profiles manager B's actual moves against the optimizer's
inputs at the same decision instant (was the player he added in the pool, was
he projected, was the player he released droppable under the rule?).

Every number here is a DIAGNOSTIC.  Nothing in this module is a
recommendation, nothing live imports it, and no default behaviour changes:

* relaxations that use information unavailable at the decision cutoff
  (realized points of week ``w``) are labelled ``hindsight=True`` and bound how
  much of the gap a perfect forecast could explain -- they are never a policy;
* relaxations that release a defender whose dynasty value is unknown treat
  that release as free ONLY to measure the constraint's cost; the shipped rule
  (unknown value is never droppable, missing is never zero) is unchanged;
* relaxing dynasty protection is what an owner-chosen dynasty-loss budget
  above 0 would allow; the default budget stays 0 (owner decision 7,
  2026-11-01).

One-at-a-time ablations do not add up: the constraints interact, and the
report states the interaction residual instead of forcing a sum.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.waivers.streaming_backtest import (
    EVIDENCE_DIR,
    MIN_WEEKS_MANAGER,
    RESEARCH_DIR,
    REPO,
    STREAMING_TX_TYPES,
    DecisionContext,
    DiskCache,
    DynastySafeOptimizerPolicy,
    RosterChange,
    SeasonData,
    Swap,
    WeekResult,
    _deltas,
    _dyn_flow,
    _idp_set,
    _rounded,
    _season_weeks,
    available_pool,
    classify_roster_changes,
    decision_weeks,
    ledger_dynasty_lookup,
    load_season,
    metric_rolling,
    pair_plan,
    privacy_violations,
    simulate_actual,
    simulate_hold,
    simulate_policy,
    streaming_activity,
    summarize_deltas,
)

__all__ = [
    "ABLATIONS",
    "Ablation",
    "AblatedOptimizerPolicy",
    "actual_move_profile",
    "run_gap_attribution",
]


@dataclass(frozen=True)
class Ablation:
    """One counterfactual: which constraint of baseline 7 is relaxed."""

    key: str
    factor: str
    description: str
    masked: bool = True
    max_swaps: int = 3
    release_above_line: bool = False
    release_unpriced: bool = False
    release_unprojected: bool = False
    open_spots: int = 0
    horizon: int = 1
    materiality: float = 1.0
    projection: str = "provider"  # provider | rolling | oracle
    hindsight: bool = False
    #: Search bound for the relaxed runs.  ``None`` = the solver default
    #: (the base cell, so it reproduces the 2026-10-29 numbers exactly).  A
    #: decision that hits it is counted ``bounded`` -- applied, never "optimal".
    work_limit: int | None = 100_000


#: The decomposition, in report order.  ``base`` reproduces baseline 7 masked
#: S = 3 exactly (the 2026-10-29 primary cell).
ABLATIONS: tuple[Ablation, ...] = (
    Ablation(
        "base",
        "reference",
        "baseline 7 as preregistered: masked pool, S = 3, budget 0",
        work_limit=None,
    ),
    Ablation(
        "conservative",
        "conservative scenario",
        "stricter than baseline 7: one swap a week and a 3-point materiality bar",
        max_swaps=1,
        materiality=3.0,
    ),
    Ablation(
        "pool_unmasked",
        "pool eligibility / waiver availability / FAAB",
        "unmasked pool: players another team claimed in week w are offered "
        "(would need winning claims; FAAB cost unknown, never $0)",
        masked=False,
    ),
    Ablation(
        "dynasty_protection_off",
        "dynasty protection",
        "a priced defender above his group's replacement line is releasable at no "
        "charge (what a dynasty-loss budget > 0 buys)",
        release_above_line=True,
    ),
    Ablation(
        "unpriced_releasable",
        "unpriced players",
        "a defender with NO known dynasty value is releasable (diagnostic only: "
        "the shipped rule never releases an unpriced player)",
        release_unpriced=True,
    ),
    Ablation(
        "injury_replacement",
        "injuries / inactive",
        "a rostered defender with no week-w projection, or a projection <= 0 "
        "(out / inactive at the cutoff), is releasable",
        release_unprojected=True,
    ),
    Ablation(
        "roster_capacity_plus5",
        "roster capacity",
        "up to 5 defender adds per week need no release (manager B carried ~5 "
        "more defenders than hold in 2026)",
        open_spots=5,
    ),
    Ablation("swaps_S6", "search limits (swap cap)", "up to 6 swaps per week", max_swaps=6),
    Ablation(
        "materiality_0",
        "bench / replacement threshold",
        "a move is recommended for any positive projected gain (materiality 0 "
        "instead of 1.0 point)",
        materiality=0.0,
    ),
    Ablation(
        "horizon_3wk",
        "single- vs multi-week horizon",
        "plans on weeks w..w+2 projections, equal weights",
        horizon=3,
    ),
    Ablation(
        "projection_rolling",
        "predicted production (point-in-time alternative)",
        "replace the provider projection with the player's recent realized "
        "average (weeks < w only)",
        projection="rolling",
    ),
    Ablation(
        "projection_oracle",
        "predicted production (HINDSIGHT bound)",
        "replace the projection with the week-w REALIZED points -- uses "
        "information unavailable at the cutoff; an upper bound, never a policy",
        projection="oracle",
        hindsight=True,
    ),
    Ablation(
        "all_point_in_time",
        "all point-in-time relaxations together",
        "unmasked + protection off + unpriced + injury + capacity +5 + S = 6 + "
        "materiality 0 (provider projection)",
        masked=False,
        max_swaps=6,
        release_above_line=True,
        release_unpriced=True,
        release_unprojected=True,
        open_spots=5,
        materiality=0.0,
    ),
    Ablation(
        "all_plus_oracle",
        "all relaxations + HINDSIGHT projection",
        "all_point_in_time with week-w realized points as the projection",
        masked=False,
        max_swaps=6,
        release_above_line=True,
        release_unpriced=True,
        release_unprojected=True,
        open_spots=5,
        materiality=0.0,
        projection="oracle",
        hindsight=True,
    ),
)


@dataclass
class AblatedOptimizerPolicy(DynastySafeOptimizerPolicy):
    """Baseline 7 with ONE (or several, for the combined runs) constraint
    relaxed.  ``data`` is held by the policy, not the context, and is read
    only for the multi-week horizon and the labelled HINDSIGHT projection --
    the :class:`DecisionContext` leakage boundary itself is untouched."""

    name: str = "7_ablation"
    ablation: Ablation = field(default_factory=lambda: ABLATIONS[0])
    data: SeasonData | None = None

    def __post_init__(self) -> None:
        self.materiality = self.ablation.materiality
        self.name = f"7_ablation:{self.ablation.key}"

    def _points(self, pid: str, ctx: DecisionContext) -> tuple[float | None, ...]:
        mode = self.ablation.projection
        if mode == "rolling":
            return (metric_rolling(pid, ctx),)
        if mode == "oracle":
            if self.data is None:
                return (None,)
            return (self.data.realized(ctx.week, pid),)
        out: list[float | None] = [ctx.projection.get(pid)]
        if self.ablation.horizon > 1 and self.data is not None:
            for w in range(ctx.week + 1, ctx.week + self.ablation.horizon):
                proj = self.data.projections.get(w, {}).get(pid)
                out.append(proj.points if proj is not None else None)
        return tuple(out)

    def build_input(self, ctx: DecisionContext) -> Any:
        from src.waivers.streaming_solver import StreamPlayer

        base = super().build_input(ctx)
        ab = self.ablation
        cost = {
            p.player_id: p.dynasty_value for p in base.roster if p.player_id in base.droppable_ids
        }
        droppable = set(base.droppable_ids)
        for pid in sorted(ctx.idp_roster):
            if pid in droppable:
                continue
            val = ctx.dynasty_value.get(pid)
            proj = ctx.projection.get(pid)
            if ab.release_above_line and val is not None:
                droppable.add(pid)
                cost[pid] = 0.0
            elif ab.release_unpriced and val is None:
                droppable.add(pid)
                cost[pid] = None
            elif ab.release_unprojected and (proj is None or proj <= 0.0):
                droppable.add(pid)
                cost[pid] = 0.0
        if ab.release_above_line:
            for pid in list(cost):
                cost[pid] = 0.0

        def player(pid: str, *, dyn: float | None) -> Any:
            return StreamPlayer(
                player_id=pid,
                name=pid,
                position=ctx.positions.get(pid, ""),
                weekly_points=self._points(pid, ctx),
                dynasty_value=dyn,
                fantasy_positions=tuple(ctx.eligibility.get(pid, ())),
                bid=0,
            )

        roster = tuple(player(p, dyn=cost.get(p)) for p in sorted(ctx.idp_roster))
        free_agents = tuple(
            fa
            for fa in (player(p, dyn=None) for p in sorted(ctx.pool))
            if any(v is not None for v in fa.weekly_points)
        )
        return dataclasses.replace(
            base,
            roster=roster,
            free_agents=free_agents,
            droppable_ids=frozenset(droppable),
            open_spots=int(ab.open_spots),
            week_weights=tuple(1.0 for _ in range(len(self._points("", ctx)))),
            materiality=float(ab.materiality),
            work_limit=ab.work_limit,
        )

    def decide(self, ctx: DecisionContext) -> list[Swap]:
        import time

        from src.waivers.streaming_solver import solve_streaming

        inp = self.build_input(ctx)
        self.stats["decisions"] += 1
        if not inp.droppable_ids and inp.open_spots <= 0:
            self.stats["noDroppable"] += 1
            return []
        t0 = time.perf_counter()
        res = solve_streaming(inp, alternatives=0, unbudgeted=False)
        self.stats["solverSeconds"] += time.perf_counter() - t0
        self.stats[res.status] = self.stats.get(res.status, 0) + 1
        if not res.recommend_move or res.best is None:
            return []
        swaps = pair_plan(res.best.adds, res.best.drops, ctx.positions)
        paired = {s.add_id for s in swaps}
        swaps += [Swap("", a, 0.0) for a in sorted(res.best.adds) if a not in paired]
        self.stats["moves"] += len(swaps)
        return swaps


# ── Manager B's actual moves, profiled against the optimizer's inputs ──


def actual_move_profile(
    data: SeasonData,
    rid: int,
    changes: Sequence[RosterChange],
    *,
    dynasty_lookup: Callable[[str, datetime], float | None] | None,
) -> dict[str, Any]:
    """For each in-season streaming add / release of one team: what the
    optimizer would have known about that player at the same cutoff.

    Point-in-time inputs only (the pool, the week-w projection, the value
    known before the cutoff); the realized columns are OUTCOMES, reported for
    scoring, never used to decide anything."""
    idp = data.idp_ids()
    adds: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []
    actual = {r.week: r for r in simulate_actual(data, rid)}
    for w in decision_weeks(data):
        prev = _idp_set(data, data.rosters[w - 1].get(rid, frozenset()))
        masked = available_pool(data, rid, w, prev, masked=True)
        unmasked = available_pool(data, rid, w, prev, masked=False)
        proj = data.projections.get(w, {})
        cutoff = data.cutoffs[w]

        def val(pid: str) -> float | None:
            return dynasty_lookup(pid, cutoff) if dynasty_lookup is not None else None

        line: dict[str, float] = {}
        # Rule 7's replacement line: best known value among PROJECTED players
        # of the masked pool (the base cell's pool).
        for pid in masked:
            if pid in proj:
                v = val(pid)
                g = data.players[pid].group or ""
                if v is not None and v > line.get(g, float("-inf")):
                    line[g] = v
        for ch in changes:
            if ch.roster_id != rid or ch.week != w or ch.player_id not in idp:
                continue
            if ch.kind not in STREAMING_TX_TYPES:
                continue
            pid = ch.player_id
            g = data.players[pid].group or ""
            p = proj.get(pid)
            v = val(pid)
            row = {
                "week": w,
                "group": g,
                "projected": p is not None,
                "projectionPositive": bool(p is not None and p.points > 0),
                "valued": v is not None,
                "playedWeek": pid in data.played.get(w, frozenset()),
                "realizedWeek": data.realized(w, pid),
            }
            if ch.direction == "add":
                row.update(
                    inMaskedPool=pid in masked,
                    inUnmaskedPool=pid in unmasked,
                    waiverBid=ch.waiver_bid,
                    madeLineup=pid in actual[w].starters if w in actual else None,
                )
                adds.append(row)
            else:
                row.update(
                    droppableUnderRule7=bool(v is not None and g in line and v <= line[g]),
                    aboveLine=bool(v is not None and g in line and v > line[g]),
                )
                drops.append(row)

    def share(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
        n = len(rows)
        k = sum(1 for r in rows if r.get(key))
        return {"count": k, "of": n, "share": (k / n) if n else None}

    return {
        "adds": {
            "n": len(adds),
            **{
                k: share(adds, k)
                for k in ("inMaskedPool", "inUnmaskedPool", "projected", "valued", "madeLineup")
            },
            "inMaskedPoolAndProjected": share(
                [dict(r, _ok=r["inMaskedPool"] and r["projected"]) for r in adds], "_ok"
            ),
            "paidClaims": sum(1 for r in adds if (r.get("waiverBid") or 0) > 0),
            # A free-agent add (or a claim with no recorded bid) has no bid: unknown,
            # never counted as a $0 claim.
            "zeroBidClaims": sum(1 for r in adds if r.get("waiverBid") == 0),
            "bidUnknown": sum(1 for r in adds if r.get("waiverBid") is None),
        },
        "drops": {
            "n": len(drops),
            **{
                k: share(drops, k)
                for k in ("valued", "droppableUnderRule7", "aboveLine", "projected", "playedWeek")
            },
            "unpriced": share([dict(r, _u=not r["valued"]) for r in drops], "_u"),
            "notProjectedOrNonPositive": share(
                [dict(r, _i=not r["projectionPositive"]) for r in drops], "_i"
            ),
            "realizedWeekMean": statistics.fmean(r["realizedWeek"] for r in drops)
            if drops
            else None,
        },
        "addsRealizedWeekMean": statistics.fmean(r["realizedWeek"] for r in adds) if adds else None,
    }


# ── Runner ─────────────────────────────────────────────────────────────


def _heaviest_streamer(data: SeasonData) -> tuple[int, int, float]:
    rids = sorted(data.rosters[min(data.weeks)])
    counts = {rid: streaming_activity(data, rid)["idpAdds"] for rid in rids}
    top = max(counts.values())
    leaders = [rid for rid, c in counts.items() if c == top]
    if len(leaders) != 1:
        raise RuntimeError("heaviest-streamer rule is ambiguous (tie); pass --manager")
    return leaders[0], top, statistics.fmean(counts.values())


def run_gap_attribution(
    *,
    season: int = 2026,
    weeks: Sequence[int] = (1, 2, 3, 4, 5, 6, 7),
    registry_league_key: str = "dynasty_main",
    ledger_path: Path | None = None,
    league_scope: bool = True,
    only: Sequence[str] | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the ablations on ONE frozen season.  Returns ``(evidence, private)``."""
    from src.public_league import sleeper_client

    registry = json.loads(
        (REPO / "config" / "leagues" / "registry.json").read_text(encoding="utf-8")
    )
    start_id = next(
        str(lg["sleeperLeagueId"])
        for lg in registry["leagues"]
        if lg.get("key") == registry_league_key
    )
    cache = DiskCache(RESEARCH_DIR / "raw")
    chain = cache.get("chain", lambda: sleeper_client.walk_league_chain(start_id))
    dump = cache.get("players_nfl", sleeper_client.fetch_nfl_players)
    league = next(lg for lg in chain if int(lg["season"]) == season)
    available = _season_weeks(league)
    use_weeks = [w for w in weeks if w in available]
    data, priv = load_season(league, use_weeks, cache=cache, players_dump=dump)
    dyn_lookup = ledger_dynasty_lookup(ledger_path, lane="source_value", source_key="idpTradeCalc")
    dyn_source = "source_value:idpTradeCalc (vendor value, NOT canonical)"
    changes = classify_roster_changes(data)
    mgr_rid, mgr_adds, league_mean_adds = _heaviest_streamer(data)
    rids = sorted(data.rosters[min(data.weeks)])
    teams = rids if league_scope else [mgr_rid]
    holds = {rid: simulate_hold(data, rid, changes) for rid in teams}
    actuals = {rid: simulate_actual(data, rid) for rid in teams}
    actual_delta = {rid: _deltas(actuals[rid], holds[rid]) for rid in teams}

    evidence: dict[str, Any] = {
        "schema": "idp_streaming_gap_attribution_v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "season": season,
        "scoredWeeks": list(data.weeks),
        "decisionWeeks": decision_weeks(data),
        "managerRule": "heaviest_idp_streamer (most complete waiver / free-agent defender adds)",
        "managerBIdpAdds": mgr_adds,
        "leagueMeanIdpAdds": league_mean_adds,
        "dynastyValueSource": dyn_source,
        "projectionSource": data.projection_source,
        "projectionPointInTimeVerified": False,
        "scope": "league" if league_scope else "managerB",
        "actualMinusHold": {
            "managerB": summarize_deltas(actual_delta[mgr_rid], minimum=MIN_WEEKS_MANAGER),
        },
        "ablations": {},
        "actualMoveProfile": {
            "managerB": actual_move_profile(data, mgr_rid, changes, dynasty_lookup=dyn_lookup),
        },
        "note": (
            "Diagnostics only. One-at-a-time ablations relax ONE constraint of "
            "baseline 7; they do not add up. hindsight=True rows use week-w "
            "realized points and bound, never recommend."
        ),
    }
    if league_scope:
        evidence["actualMinusHold"]["league"] = summarize_deltas(
            [v for rid in teams for v in actual_delta[rid]],
            minimum=6,
            clusters=[actual_delta[rid] for rid in teams],
        )
    for ab in ABLATIONS:
        if only and ab.key not in only:
            continue
        stats: dict[str, float] = {}
        per_team: dict[int, list[WeekResult]] = {}
        for rid in teams:
            policy = AblatedOptimizerPolicy(ablation=ab, data=data)
            per_team[rid] = simulate_policy(
                data,
                rid,
                rids.index(rid),
                policy,
                changes,
                max_swaps=ab.max_swaps,
                masked=ab.masked,
                dynasty_lookup=dyn_lookup,
                dynasty_value_source=dyn_source,
                open_spots=ab.open_spots,
            )
            for k, v in policy.stats.items():
                stats[k] = stats.get(k, 0) + v
        deltas = {rid: _deltas(per_team[rid], holds[rid]) for rid in teams}
        mgr_res = per_team[mgr_rid]
        cell: dict[str, Any] = {
            "factor": ab.factor,
            "description": ab.description,
            "hindsight": ab.hindsight,
            "config": {
                k: v
                for k, v in dataclasses.asdict(ab).items()
                if k not in ("key", "factor", "description")
            },
            "managerB": summarize_deltas(deltas[mgr_rid], minimum=MIN_WEEKS_MANAGER),
            "managerBAdds": sum(len(r.adds) for r in mgr_res),
            "managerBPureAdds": sum(max(0, len(r.adds) - len(r.drops)) for r in mgr_res),
            "managerBMeanDefenders": statistics.fmean(len(r.idp_set) for r in mgr_res),
            "managerBContestedAdds": any(r.faab is None for r in mgr_res),
            "managerBActualMinusAblation": summarize_deltas(
                [a - b for a, b in zip(actual_delta[mgr_rid], deltas[mgr_rid])],
                minimum=MIN_WEEKS_MANAGER,
            ),
            "managerBDynastyValueFlow": _dyn_flow(mgr_res, data, dyn_lookup),
            "solverStats": {
                k: (round(v, 1) if k == "solverSeconds" else v) for k, v in sorted(stats.items())
            },
        }
        if league_scope:
            cell["league"] = summarize_deltas(
                [v for rid in teams for v in deltas[rid]],
                minimum=6,
                clusters=[deltas[rid] for rid in teams],
            )
            cell["leagueAddsPerTeamWeek"] = sum(
                len(r.adds) for rid in teams for r in per_team[rid]
            ) / sum(len(per_team[rid]) for rid in teams)
        evidence["ablations"][ab.key] = cell
        if log:
            log(
                f"{ab.key}: managerB {cell['managerB']['mean']:+.2f}/wk "
                f"({cell['managerBAdds']} adds; {stats.get('solverSeconds', 0):.0f}s)"
            )
    # Same input, same candidate universe (masked pool, S = 3), other models:
    # the preregistered simple rules.  The no-move baseline IS the hold
    # reference (delta 0 by definition).
    evidence["models"] = {"1_no_move_hold": {"managerB": {"mean": 0.0, "note": "reference"}}}
    if not only or "models" in only:
        from src.waivers.streaming_backtest import RULE_POLICIES  # noqa: PLC0415

        for name, factory in RULE_POLICIES:
            if name.startswith("7_"):
                continue  # baseline 7 is the ``base`` ablation
            per = {}
            for rid in teams:
                per[rid] = simulate_policy(
                    data,
                    rid,
                    rids.index(rid),
                    factory(),
                    changes,
                    max_swaps=3,
                    masked=True,
                    dynasty_lookup=dyn_lookup if name.startswith("6_") else None,
                    dynasty_value_source=dyn_source,
                )
            d = {rid: _deltas(per[rid], holds[rid]) for rid in teams}
            cell = {
                "managerB": summarize_deltas(d[mgr_rid], minimum=MIN_WEEKS_MANAGER),
                "managerBAdds": sum(len(r.adds) for r in per[mgr_rid]),
            }
            if league_scope:
                cell["league"] = summarize_deltas(
                    [v for rid in teams for v in d[rid]],
                    minimum=6,
                    clusters=[d[rid] for rid in teams],
                )
            evidence["models"][name] = cell
            if log:
                log(f"model {name}: managerB {cell['managerB']['mean']:+.2f}/wk")
    gap = evidence["actualMinusHold"]["managerB"]["mean"]
    base = evidence["ablations"].get("base", {}).get("managerB", {}).get("mean")
    if gap is not None and base is not None:
        rows = []
        for key, cell in evidence["ablations"].items():
            m = cell["managerB"]["mean"]
            if key == "base" or m is None:
                continue
            rows.append(
                {
                    "ablation": key,
                    "hindsight": cell["hindsight"],
                    "gainOverBase": m - base,
                    "shareOfGapClosed": (m - base) / (gap - base) if gap != base else None,
                }
            )
        evidence["decomposition"] = {
            "gap": gap - base,
            "actualMinusHoldMean": gap,
            "baseMinusHoldMean": base,
            "rows": rows,
        }
    private = {"managerRosterId": mgr_rid, "sensitive": priv["sensitiveStrings"]}
    return evidence, private


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="IDP streaming gap attribution (diagnostic)")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--weeks", default="1,2,3,4,5,6,7", help="frozen scored weeks")
    parser.add_argument("--ledger", type=Path, default=RESEARCH_DIR / "temporal_ledger.sqlite")
    parser.add_argument("--manager-only", action="store_true", help="skip the league cells")
    parser.add_argument("--only", default="", help="comma-separated ablation keys")
    parser.add_argument(
        "--evidence-out", type=Path, default=EVIDENCE_DIR / "gap_attribution_2026-11-01.json"
    )
    args = parser.parse_args(argv)
    evidence, private = run_gap_attribution(
        season=args.season,
        weeks=tuple(int(w) for w in args.weeks.split(",")),
        ledger_path=args.ledger if args.ledger.exists() else None,
        league_scope=not args.manager_only,
        only=[k for k in args.only.split(",") if k] or None,
        log=lambda m: print(m, flush=True),
    )
    blob = json.dumps(_rounded(evidence), indent=1, sort_keys=True, default=str)
    leaks = privacy_violations(blob, private["sensitive"])
    if leaks:
        raise RuntimeError(f"privacy guard: {len(leaks)} identifying string(s) in evidence")
    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_out.write_text(blob + "\n", encoding="utf-8")
    print(f"evidence -> {args.evidence_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
