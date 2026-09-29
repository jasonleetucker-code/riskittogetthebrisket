#!/usr/bin/env python3
"""Replay the unified Manager of the Year against a persisted public snapshot.

Read-only.  Loads a public-league snapshot (``data/public_league/snapshot.json``
by default), runs the FROZEN v1 methodology
(``src/public_league/manager_of_the_year.py``) for every season that has
begun, and prints, per season:

* every manager: legacy composite + rank vs unified A/T/W/D/P, contributions,
  score, rank, status and coverage;
* winner changes with the component reasons;
* sensitivity: weights (+/-0.05 per component), KAPPA (0.25 / 0.5 / 1.0),
  leave-one-season-out draft expectation, and imputing the unobservable W
  charge weeks;
* anti-gaming diagnostics on real data (activity volume vs score, draft
  position vs D, component correlations).

Nothing here changes a parameter: sensitivity runs are counterfactual
re-scorings of the same frozen raw measurements.  Methodology record:
``docs/awards/MANAGER_OF_THE_YEAR_METHODOLOGY.md``.

    python scripts/replay_manager_of_the_year.py \
        [--snapshot PATH] [--nfl-players PATH] [--json OUT]
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.public_league import awards, metrics, snapshot_store  # noqa: E402
from src.public_league import manager_of_the_year as moty  # noqa: E402

COMPONENTS = ("A", "T", "W", "D", "P")


# ── small statistics ──────────────────────────────────────────────────────
def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3:
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def kendall_tau(order_a: list[str], order_b: list[str]) -> float | None:
    pos = {o: i for i, o in enumerate(order_b)}
    common = [o for o in order_a if o in pos]
    n = len(common)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            if pos[common[i]] < pos[common[j]]:
                conc += 1
            else:
                disc += 1
    return (conc - disc) / (n * (n - 1) / 2)


# ── re-scoring helpers (counterfactual views of the same raw measurements) ─
def rescore(
    evaluation: dict[str, Any],
    *,
    weights: dict[str, float] | None = None,
    kappa: float | None = None,
    raw_override: dict[str, dict[str, float]] | None = None,
) -> list[tuple[str, float]]:
    """Order of managers under altered weights / KAPPA / raw nets."""
    weights = weights or moty.WEIGHTS
    sigma = evaluation["parameters"]["sigmaWeek"]
    weeks = evaluation["weeksInWindow"]
    final = evaluation["status"] == moty.FINAL
    out = []
    for r in evaluation["rows"]:
        if r.get("score") is None:
            continue
        comp = r["components"]
        vals = {}
        for k in COMPONENTS:
            s = comp[k]["score"]
            if k in ("T", "W", "D") and (kappa is not None or raw_override):
                key = "netSurplusVsExpectation" if k == "D" else "netSurplus"
                net = (raw_override or {}).get(r["ownerId"], {}).get(k, comp[k]["raw"][key])
                if k == "T":
                    net += 0.0  # draftPickExpectationNet is already inside netSurplus
                use_k = kappa if kappa is not None else moty.KAPPA
                s = 50.0 + 50.0 * math.tanh((net / weeks) / (use_k * sigma))
            vals[k] = s
        if final:
            total = sum(weights[k] * vals[k] for k in COMPONENTS)
        else:
            nonp = sum(weights[k] for k in ("A", "T", "W", "D"))
            total = sum(weights[k] * vals[k] for k in ("A", "T", "W", "D")) / nonp
        out.append((r["ownerId"], total))
    out.sort(key=lambda t: -t[1])
    return out


def perturbed_weights(k: str, delta: float) -> dict[str, float] | None:
    w = dict(moty.WEIGHTS)
    if w[k] + delta <= 0:
        return None
    others = [c for c in COMPONENTS if c != k]
    total_other = sum(w[c] for c in others)
    w[k] += delta
    for c in others:
        w[c] -= delta * (w[c] / total_other)
    return w


@contextmanager
def annual_table(table: tuple[float, ...]):
    saved = moty.ANNUAL_BAND_EXPECTATION
    moty.ANNUAL_BAND_EXPECTATION = table
    try:
        yield
    finally:
        moty.ANNUAL_BAND_EXPECTATION = saved


def _pav(vals: list[float], wts: list[float]) -> list[float]:
    blocks: list[list[float]] = []
    for v, w in zip(vals, wts):
        blocks.append([v, w, 1])
        while len(blocks) > 1 and blocks[-2][0] < blocks[-1][0]:
            v2, w2, n2 = blocks.pop()
            v1, w1, n1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, n1 + n2])
    out: list[float] = []
    for v, _w, n in blocks:
        out += [v] * int(n)
    return out


def calibrate_annual(snapshot, seasons, levels_by_season) -> tuple[float, ...]:
    """Recompute the annual table from ``seasons`` only (the frozen recipe)."""
    acc: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for season in seasons:
        facts = moty._season_facts(season)
        u = moty._Surplus(snapshot, facts, levels_by_season[season.season])
        sels, _diag, _meta = moty._window_selections(snapshot, season)
        for s in sels:
            if s.kind != "annual":
                continue
            for wk in facts.weeks:
                v = u(s.pid, wk)
                if v is None:
                    continue
                acc[s.band][0] += v
                acc[s.band][1] += 1
    bands = sorted(acc)
    if not bands:
        return ()
    raw = [acc[b][0] / acc[b][1] for b in bands]
    return tuple(round(x, 3) for x in _pav(raw, [acc[b][1] for b in bands]))


# ── the replay ────────────────────────────────────────────────────────────
def replay(snapshot) -> dict[str, Any]:
    out: dict[str, Any] = {"seasons": []}
    levels_by_season = {}
    begun = [s for s in snapshot.seasons if awards._has_begun(s)]
    for season in begun:
        _rows, _excl, levels = awards._vorp_board_with_levels(
            snapshot, season, regular_season_only=True
        )
        levels_by_season[season.season] = levels
    for season in begun:
        levels = levels_by_season[season.season]
        evaluation = moty.build_season(snapshot, season, levels)
        trader_rows, _best = awards._trader_of_the_year_scores(snapshot, season)
        waiver_rows = awards._waiver_king_scores(snapshot, season)
        legacy = awards._manager_of_the_year_scores(snapshot, season, trader_rows, waiver_rows)
        legacy_rank = {r["ownerId"]: i + 1 for i, r in enumerate(legacy)}
        legacy_score = {r["ownerId"]: r["compositeScore"] for r in legacy}
        standings = {r["ownerId"]: r for r in metrics.season_standings(season, snapshot.managers)}

        order = [r["ownerId"] for r in evaluation["rows"] if r.get("score") is not None]
        sens: dict[str, Any] = {"weights": [], "kappa": [], "draftLoso": None, "waiverImpute": None}
        base_winner = order[0] if order else None
        for k in COMPONENTS:
            if k == "P" and evaluation["status"] != moty.FINAL:
                continue
            for delta in (-0.05, 0.05):
                w = perturbed_weights(k, delta)
                if w is None:
                    continue
                alt = rescore(evaluation, weights=w)
                sens["weights"].append(
                    {
                        "component": k,
                        "delta": delta,
                        "winner": alt[0][0] if alt else None,
                        "winnerChanged": bool(alt) and alt[0][0] != base_winner,
                        "kendallTau": kendall_tau(order, [o for o, _ in alt]),
                    }
                )
        for kappa in (0.25, 1.0):
            alt = rescore(evaluation, kappa=kappa)
            sens["kappa"].append(
                {
                    "kappa": kappa,
                    "winner": alt[0][0] if alt else None,
                    "winnerChanged": bool(alt) and alt[0][0] != base_winner,
                    "kendallTau": kendall_tau(order, [o for o, _ in alt]),
                }
            )
        # Leave-one-season-out annual draft expectation (completed seasons).
        others = [s for s in begun if s.is_complete and s.season != season.season]
        if others:
            table = calibrate_annual(snapshot, others, levels_by_season)
            if table:
                with annual_table(table):
                    loso = moty.build_season(snapshot, season, levels)
                alt_order = [r["ownerId"] for r in loso["rows"] if r.get("score") is not None]
                sens["draftLoso"] = {
                    "table": table,
                    "calibratedOn": [s.season for s in others],
                    "winner": alt_order[0] if alt_order else None,
                    "winnerChanged": bool(alt_order) and alt_order[0] != base_winner,
                    "kendallTau": kendall_tau(order, alt_order),
                }
        # Impute the unobservable W charge weeks at the season's mean observed
        # per-week W charge (an upper-bound-style stress on the known bias).
        led = moty.management_ledger(snapshot, season, levels)
        charge_sum = 0.0
        for _rid, ch in led["tally"].items():
            charge_sum += ch["W"].charge
        facts = led["facts"]
        u = moty._Surplus(snapshot, facts, levels)
        base0, _basis = moty._window_baseline(snapshot, season)
        ledger_events = [e for e in led.get("events", [])]
        ledger = moty._Ledger(ledger_events)
        drafted: dict[int, set[str]] = defaultdict(set)
        for s in moty._window_selections(snapshot, season)[0]:
            drafted[s.rid].add(s.pid)
        observed_weeks = 0
        for wk in facts.weeks:
            baseline = ledger.baseline_at(base0, wk)
            for rid, held in facts.holdings.get(wk, {}).items():
                world = baseline.get(rid, set()) | drafted.get(rid, set())
                for pid in world - held:
                    if ledger.exit_channel(rid, pid, wk) == "W" and u(pid, wk) is not None:
                        observed_weeks += 1
        mean_charge = charge_sum / observed_weeks if observed_weeks else 0.0
        override = {}
        for rid, ch in led["tally"].items():
            oid = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not oid:
                continue
            w = ch["W"]
            override[oid] = {"W": w.net - mean_charge * w.unknown_charge_weeks}
        alt = rescore(evaluation, raw_override=override)
        sens["waiverImpute"] = {
            "meanObservedChargePerWeek": mean_charge,
            "winner": alt[0][0] if alt else None,
            "winnerChanged": bool(alt) and alt[0][0] != base_winner,
            "kendallTau": kendall_tau(order, [o for o, _ in alt]),
        }

        # Proposed repair OD-MOTY-7 (NOT the frozen v1 method): trades that
        # moved a FUTURE pick have no measurable future-value side while the
        # FV-channel is incomplete, so drop them from T's production channel
        # too (their players' weeks become unexplained -> excluded, never 0).
        stripped = copy.deepcopy(season)
        removed = 0
        for wk, txs in list(stripped.transactions_by_week.items()):
            keep = []
            for tx in txs or []:
                if str(tx.get("type")).lower() == "trade" and any(
                    str(pk.get("season")) != str(season.season)
                    for pk in tx.get("draft_picks") or []
                ):
                    removed += 1
                    continue
                keep.append(tx)
            stripped.transactions_by_week[wk] = keep
        repaired = moty.build_season(snapshot, stripped, levels)
        rep_order = [r["ownerId"] for r in repaired["rows"] if r.get("score") is not None]
        sens["excludeFuturePickTrades"] = {
            "tradesExcluded": removed,
            "winner": rep_order[0] if rep_order else None,
            "winnerChanged": bool(rep_order) and rep_order[0] != base_winner,
            "kendallTau": kendall_tau(order, rep_order),
            "T": {r["ownerId"]: r["components"]["T"]["score"] for r in repaired["rows"]},
            "score": {r["ownerId"]: r.get("score") for r in repaired["rows"]},
        }

        # OD-MOTY-3 diagnostic: share of T/W credit earned in weeks the player
        # was in the counted (starting) lineup vs depth weeks.
        counted = depth = 0.0
        for wk in facts.weeks:
            baseline = ledger.baseline_at(base0, wk)
            starters_by_rid = {}
            for e in season.matchups_by_week.get(wk) or []:
                rid_e = metrics.roster_id_of(e)
                if rid_e is not None:
                    starters_by_rid[rid_e] = {str(x) for x in e.get("starters") or []}
            for rid, held in facts.holdings.get(wk, {}).items():
                world = baseline.get(rid, set()) | drafted.get(rid, set())
                for pid in held - world:
                    if ledger.acquisition_channel(rid, pid, wk) not in ("T", "W"):
                        continue
                    val = u(pid, wk)
                    if not val:
                        continue
                    if pid in starters_by_rid.get(rid, set()):
                        counted += val
                    else:
                        depth += val
        sens["creditCountedShare"] = counted / (counted + depth) if counted + depth else None

        # Anti-gaming diagnostics.
        scored = [r for r in evaluation["rows"] if r.get("score") is not None]
        diag = {}
        if len(scored) >= 3:
            trades = [r["components"]["T"]["raw"]["trades"] for r in scored]
            waiver_moves = defaultdict(int)
            for ev in led.get("events", []):
                if ev.channel == "W":
                    for rid in {*ev.adds.values(), *ev.drops.values()}:
                        waiver_moves[rid] += 1
            moves = [waiver_moves.get(r["rosterId"], 0) for r in scored]
            sel_band = defaultdict(list)
            for s in led["selections"]:
                sel_band[s["rosterId"]].append(s["band"])
            mean_band = [
                (sum(sel_band[r["rosterId"]]) / len(sel_band[r["rosterId"]]))
                if sel_band.get(r["rosterId"])
                else None
                for r in scored
            ]
            with_band = [(b, r) for b, r in zip(mean_band, scored) if b is not None]
            diag = {
                "spearman_trades_vs_T": spearman(
                    trades, [r["components"]["T"]["score"] for r in scored]
                ),
                "spearman_waiverMoves_vs_W": spearman(
                    moves, [r["components"]["W"]["score"] for r in scored]
                ),
                "spearman_meanDraftBand_vs_D": spearman(
                    [b for b, _ in with_band], [r["components"]["D"]["score"] for _, r in with_band]
                ),
                "spearman_A_vs_management": spearman(
                    [r["components"]["A"]["score"] for r in scored],
                    [r["management"] for r in scored],
                ),
                "spearman_unified_vs_legacy": spearman(
                    [r["score"] for r in scored],
                    [legacy_score.get(r["ownerId"], 0.0) for r in scored],
                ),
                "nonPlayoffInTop3": [
                    r["displayName"]
                    for r in scored[:3]
                    if r["components"]["P"].get("madePlayoffs") is False
                ],
            }

        rows = []
        for r in evaluation["rows"]:
            st = standings.get(r["ownerId"], {})
            rows.append(
                {
                    "ownerId": r["ownerId"],
                    "displayName": r["displayName"],
                    "record": f"{st.get('wins', '?')}-{st.get('losses', '?')}",
                    "legacyScore": legacy_score.get(r["ownerId"]),
                    "legacyRank": legacy_rank.get(r["ownerId"]),
                    "rank": r.get("rank"),
                    "tied": bool(r.get("tied")),
                    "score": r.get("score"),
                    "earnedOf90": r.get("earnedOf90"),
                    "components": {k: r["components"][k]["score"] for k in COMPONENTS},
                    "contributions": r.get("contributions"),
                    "raw": {
                        "T_net": r["components"]["T"]["raw"]["netSurplus"],
                        "T_trades": r["components"]["T"]["raw"]["trades"],
                        "W_net": r["components"]["W"]["raw"]["netSurplus"],
                        "W_faabSpentPct": r["components"]["W"]["raw"]["faabSpentPct"],
                        "D_net": r["components"]["D"]["raw"]["netSurplusVsExpectation"],
                        "D_selections": r["components"]["D"]["raw"]["selections"],
                        "unobservedWeeks": sum(
                            r["components"][k]["raw"]["unobservedWeeks"] for k in ("T", "W", "D")
                        ),
                    },
                    "explanation": r.get("explanation"),
                }
            )
        legacy_winner = legacy[0]["ownerId"] if legacy else None
        out["seasons"].append(
            {
                "season": season.season,
                "status": evaluation["status"],
                "official": evaluation["official"],
                "asOfWeek": evaluation["asOfWeek"],
                "coverage": evaluation["coverage"],
                "parameters": evaluation["parameters"],
                "legacyWinner": legacy_winner,
                "unifiedWinner": base_winner,
                "winnerChanged": base_winner != legacy_winner,
                "rows": rows,
                "sensitivity": sens,
                "antiGaming": diag,
            }
        )
    return out


def _fmt(x, d=1):
    return "—" if x is None else f"{x:.{d}f}"


def print_report(result: dict[str, Any], names: dict[str, str]) -> None:
    for s in result["seasons"]:
        cov = s["coverage"]
        print(
            f"\n## {s['season']} — {s['status']} (as of week {s['asOfWeek']}), coverage {cov['status']}"
        )
        print(f"reasons: {', '.join(cov['reasons'])}")
        print(
            f"sigma_week {_fmt(s['parameters']['sigmaWeek'], 2)} · trades {cov['counts'].get('trades')} "
            f"· waiver/FA {cov['counts'].get('waiverMoves')} · trade FV {cov['tradeFutureValue']}"
        )
        print(
            "| # | manager | rec | legacy (rank) | A | T | W | D | P | contrib A/T/W/D/P | score | T net | W net | D net | unobs |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for r in s["rows"]:
            c = r["components"]
            con = r["contributions"] or {}
            contrib = "/".join(
                _fmt(con.get(k)) if con.get(k) is not None else "pend" for k in COMPONENTS
            )
            rank = "—" if r["rank"] is None else (f"T{r['rank']}" if r["tied"] else str(r["rank"]))
            print(
                f"| {rank} | {r['displayName']} | {r['record']} | {_fmt(r['legacyScore'], 3)} ({r['legacyRank']}) "
                f"| {_fmt(c['A'])} | {_fmt(c['T'])} | {_fmt(c['W'])} | {_fmt(c['D'])} | {_fmt(c['P'])} "
                f"| {contrib} | {_fmt(r['score'], 2)} | {_fmt(r['raw']['T_net'])} | {_fmt(r['raw']['W_net'])} "
                f"| {_fmt(r['raw']['D_net'])} | {r['raw']['unobservedWeeks']} |"
            )
        lw, uw = (
            names.get(s["legacyWinner"], s["legacyWinner"]),
            names.get(s["unifiedWinner"], s["unifiedWinner"]),
        )
        print(f"legacy winner: {lw} · unified winner: {uw} · changed: {s['winnerChanged']}")
        sens = s["sensitivity"]
        flips = [x for x in sens["weights"] if x["winnerChanged"]]
        taus = [x["kendallTau"] for x in sens["weights"] if x["kendallTau"] is not None]
        flip_text = ", ".join(
            "{}{:+.2f}->{}".format(x["component"], x["delta"], names.get(x["winner"], x["winner"]))
            for x in flips
        )
        print(
            f"weights ±0.05: {len(flips)}/{len(sens['weights'])} change the winner "
            f"({flip_text or 'none'}); min Kendall tau {_fmt(min(taus) if taus else None, 2)}"
        )
        for x in sens["kappa"]:
            print(
                f"KAPPA {x['kappa']}: winner {names.get(x['winner'], x['winner'])} "
                f"(changed {x['winnerChanged']}), tau {_fmt(x['kendallTau'], 2)}"
            )
        if sens["draftLoso"]:
            x = sens["draftLoso"]
            print(
                f"draft LOSO (table from {x['calibratedOn']}): winner {names.get(x['winner'], x['winner'])} "
                f"(changed {x['winnerChanged']}), tau {_fmt(x['kendallTau'], 2)}"
            )
        x = sens["waiverImpute"]
        print(
            f"W unobserved weeks imputed at {_fmt(x['meanObservedChargePerWeek'], 2)}/wk: winner "
            f"{names.get(x['winner'], x['winner'])} (changed {x['winnerChanged']}), tau {_fmt(x['kendallTau'], 2)}"
        )
        x = sens["excludeFuturePickTrades"]
        print(
            f"proposed repair OD-MOTY-7 (exclude {x['tradesExcluded']} future-pick trades from T): winner "
            f"{names.get(x['winner'], x['winner'])} (changed {x['winnerChanged']}), tau {_fmt(x['kendallTau'], 2)}; "
            "T: " + ", ".join(f"{names.get(o, o)} {_fmt(v)}" for o, v in x["T"].items())
        )
        print(
            f"T/W credit earned in counted-lineup weeks: {_fmt((sens['creditCountedShare'] or 0) * 100)}%"
        )
        print(
            f"anti-gaming: {json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in s['antiGaming'].items()})}"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--snapshot", default=str(REPO / "data/public_league/snapshot.json"))
    ap.add_argument("--nfl-players", default=str(REPO / "data/public_league/nfl_players.json"))
    ap.add_argument("--json", help="also write the full result to this path")
    args = ap.parse_args(argv)
    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        print(f"snapshot not found: {snap_path}", file=sys.stderr)
        return 2
    snapshot = snapshot_store.snapshot_from_dict(json.loads(snap_path.read_text(encoding="utf-8")))
    nfl = Path(args.nfl_players)
    if nfl.exists():
        snapshot.nfl_players = json.loads(nfl.read_text(encoding="utf-8"))
    result = replay(snapshot)
    names = {oid: metrics.display_name_for(snapshot, oid) for oid in snapshot.managers.by_owner_id}
    print(f"# Unified Manager of the Year replay — {moty.METHOD_VERSION}")
    print(f"snapshot generated {snapshot.generated_at}")
    print_report(result, names)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
