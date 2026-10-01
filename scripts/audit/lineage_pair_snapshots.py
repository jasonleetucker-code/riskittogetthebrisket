#!/usr/bin/env python3
"""Multi-snapshot named-pair dependence (Batch 3 G/D2 follow-up) — measurement only.

The 2026-10-01 integrity sweep (``scripts/audit/lineage_integrity_sweep.py``)
measured pairwise dependence on ONE captured state: each source's latest CSV.
A single-day statistic cannot decide whether a board is an ancestry-safe Hill
holdout, so this re-runs the sweep's own instrument — the LEAVE-PAIR-OUT
residual correlation of percentile ranks against a consensus that excludes both
members (``leave_pair_out_residuals``) — at many point-in-time snapshots and
reports the per-snapshot DISTRIBUTION.

One method owner: board parsing, identity, universes, percentiles, the
leave-pair-out residual and git access are imported from the sweep, never
re-implemented.  What this file adds:

* **snapshots** — for every snapshot instant ``T`` each board is the last
  committed version of its CSV at or before ``T`` (``git log`` of
  ``CSVs/site_raw``), so nothing later than ``T`` is ever read;
* **consensus variants** — ``lpo`` is the sweep's rule (the voting pool minus
  the two members).  ``lfo`` additionally drops every pool source in either
  member's B10 correlation group or from either member's provider (lineage
  owner), so a member's own siblings cannot sit in the consensus it is judged
  against (the defect the 2026-10-01 sweep found in the old +0.891 instrument,
  run in the other direction);
* **value-space dependence** — the D2 metric compares SPACING, not order, so the
  same leave-pair-out construction is run on ``ln(value / board max)`` over
  boards that publish native values.  Two statistics, named apart:
  ``valueResidualRaw`` (includes any shared curve SHAPE — two boards steeper
  than the consensus correlate here with no shared opinion) and
  ``valueResidualDetrended`` (each residual minus a cubic in the consensus,
  i.e. player-specific value agreement beyond curve shape);
* **partial correlation** for an indirect path (e.g. OTC -> FantasyCalc ->
  Dynasty Daddy): the pair's residual correlation with the intermediary's
  residual partialled out, all three excluded from the consensus.

Two instrument properties, both pinned by ``tests/sources/test_lineage_pair_snapshots.py``:

* **depth artifact** — the sweep's per-board percentiles put a 370-row and a
  460-row board on different scales, so two boards of similar depth share a
  residual whatever their opinions.  The ``cp`` variants re-rank every board
  inside ONE common population (members plus every consensus board covering
  >= 60% of the members' shared players), which removes it; ``cpx`` also drops
  TE rows, whose value basis differs across boards (KTC TE++ vs base);
* **leave-pair-out baseline** — two residuals against one consensus share that
  consensus's error, a positive floor of roughly 1 / (k + 1) for k equally
  noisy consensus boards (~+0.08 at k = 12).  Read small positives against it.

Correlation is dependence, never ancestry.  Evidence only: nothing here changes
a vote, weight, family or Hill constant.  No network.

Usage::

    python scripts/audit/lineage_pair_snapshots.py \\
        --out docs/sources/integrity/OTC_PAIR_SNAPSHOTS_2026-10-01.json

Exit codes: 0 written; 2 input missing.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_sweep():
    name = "lineage_integrity_sweep"
    if name in sys.modules:
        return sys.modules[name]
    path = Path(__file__).resolve().parent / "lineage_integrity_sweep.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


sweep = _load_sweep()

LINEAGE_PATH = REPO_ROOT / "config" / "sources" / "source_lineage.json"

#: The pairs this follow-up was asked to measure: OTC against every OFFENSE Hill
#: trainer (``training_manifest._DEFAULT_SPECS``), the historical KTC TE++
#: capture, and FantasyCalc (its recorded dependence, and the intermediary of
#: the indirect OTC -> FantasyCalc -> Dynasty Daddy path).
SUBJECT = "otcffbSf"
COMPARATORS: tuple[str, ...] = (
    "ktc",
    "ktcSfTep",
    "dynastyDaddySf",
    "dynastyNerdsSfTep",
    "yahooBoone",
    "fantasyProsFitzmaurice",
    "draftSharks",
    "fantasyCalc",
    "ktcCrowdSfTep",
    "ktcTradesSfTep",
)
#: Instrument controls: pairs with a recorded 2026-10-01 sweep verdict, measured
#: by the same code in the same run so the variants can be read against known
#: answers (DLF vs KTC recorded independent -0.447; FantasyCalc vs Dynasty Daddy
#: +0.635; Fitzmaurice vs Dynasty Nerds +0.643; PFK vs KTC +0.687 vs Crowd).
CONTROL_PAIRS: tuple[tuple[str, str], ...] = (
    ("dlfSf", "ktc"),
    ("fantasyCalc", "dynastyDaddySf"),
    ("fantasyProsFitzmaurice", "dynastyNerdsSfTep"),
    ("pfkDynasty", "ktc"),
)
#: (a, b, intermediary) indirect paths checked by partial correlation.
INDIRECT_PATHS: tuple[tuple[str, str, str], ...] = (("otcffbSf", "dynastyDaddySf", "fantasyCalc"),)

#: Non-voting keys that are not in the contract registry but are measured here.
#: ``ktc`` / ``ktcSfTep`` are the historical KTC Crowd captures (lineage relation
#: ktc-historical-calibration-states), so they sit in the ``ktcCrowd`` group.
EXTRA_GROUPS = {"ktc": "ktcCrowd", "ktcSfTep": "ktcCrowd"}
#: Before 2026-09-09 the live KTC Crowd voter has no CSV; its committed carrier is
#: ``ktcSfTep`` (D2 precondition P1: 22/22 overlap dates, 100% of players within
#: 0.5).  Used ONLY to fill the consensus pool, never as a measured member.
POOL_CARRIERS = {"ktcCrowdSfTep": "ktcSfTep"}

MIN_VALUE_OTHERS = 3
#: A consensus board joins the common population when it covers this share of
#: the members' shared players (shallower boards would shrink it too far).
MIN_COMMON_COVER = 0.6
VARIANTS = ("lpo", "lfo", "cp_lpo", "cp_lfo", "cpx_lpo", "cpx_lfo")
#: Positions dropped by the ``cpx`` variants.  TE value bases differ across
#: boards (KTC TE++, Dynasty Nerds TEP, OTC / base KTC non-TEP), so a TE row
#: carries a residual shared by every pair of same-basis boards regardless of
#: opinion; dropping TEs makes the measurement basis-neutral.
TE_EXCLUDED_POSITIONS = frozenset({"TE"})


# ── statistics ─────────────────────────────────────────────────────────


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    return sweep._pearson(xs, ys)


def partial_correlation(rxy: float, rxz: float, ryz: float) -> float | None:
    """r(x, y | z).  ``None`` when z explains x or y completely."""
    den = math.sqrt(max(0.0, (1.0 - rxz * rxz) * (1.0 - ryz * ryz)))
    return (rxy - rxz * ryz) / den if den > 1e-12 else None


def cubic_detrend(resid: Sequence[float], x: Sequence[float]) -> list[float]:
    """``resid`` minus its least-squares cubic in ``x`` (removes curve SHAPE)."""
    import numpy as np

    xa, ya = np.asarray(x, dtype=float), np.asarray(resid, dtype=float)
    if len(xa) < 8 or float(np.ptp(xa)) == 0.0:
        return list(ya - ya.mean())
    coef = np.polyfit(xa, ya, 3)
    return list(ya - np.polyval(coef, xa))


def log_values(board: Any, idents: Iterable[str]) -> dict[str, float]:
    """``{identity: ln(value / board max)}`` over positive native values."""
    vals = {
        i: board.entries[i]["value"]
        for i in idents
        if i in board.entries
        and board.entries[i]["value"] is not None
        and board.entries[i]["value"] > 0
    }
    if len(vals) < sweep.MIN_PAIR_OVERLAP:
        return {}
    top = max(vals.values())
    return {i: math.log(v / top) for i, v in vals.items()}


def residual_vectors(
    signal: Mapping[str, Mapping[str, float]],
    members: Sequence[str],
    others: Sequence[str],
    min_others: int,
) -> tuple[list[list[float]], list[float]]:
    """Per-member residual vectors over names every member carries and at least
    ``min_others`` consensus sources observe.  Returns (residuals, consensus)."""
    pools = [signal.get(m) or {} for m in members]
    common = set(pools[0])
    for p in pools[1:]:
        common &= set(p)
    res: list[list[float]] = [[] for _ in members]
    cons: list[float] = []
    for name in sorted(common):
        obs = [signal[k][name] for k in others if k in signal and name in signal[k]]
        if len(obs) < min_others:
            continue
        c = statistics.fmean(obs)
        cons.append(c)
        for j, p in enumerate(pools):
            res[j].append(p[name] - c)
    return res, cons


def pair_value_dependence(
    logv: Mapping[str, Mapping[str, float]], a: str, b: str, others: Sequence[str]
) -> dict[str, Any]:
    (ra, rb), cons = residual_vectors(logv, [a, b], others, MIN_VALUE_OTHERS)
    if len(ra) < sweep.MIN_PAIR_OVERLAP:
        return {"valueResidualRaw": None, "valueResidualDetrended": None, "nValue": len(ra)}
    raw = pearson(ra, rb)
    det = pearson(cubic_detrend(ra, cons), cubic_detrend(rb, cons))
    return {
        "valueResidualRaw": None if raw is None else round(raw, 4),
        "valueResidualDetrended": None if det is None else round(det, 4),
        "nValue": len(ra),
    }


def summarize(xs: Sequence[float | None]) -> dict[str, Any]:
    vals = [x for x in xs if x is not None]
    if not vals:
        return {"nSnapshots": 0, "median": None, "min": None, "max": None}
    return {
        "nSnapshots": len(vals),
        "median": round(statistics.median(vals), 4),
        "min": round(min(vals), 4),
        "max": round(max(vals), 4),
        "positiveShare": round(sum(1 for v in vals if v > 0) / len(vals), 3),
    }


# ── snapshot loading ───────────────────────────────────────────────────


class History:
    """git history of one CSV, newest-last; boards parsed lazily and cached."""

    def __init__(self, key: str, path: Path) -> None:
        self.key, self.path = key, path
        self.versions = list(reversed(sweep.git_versions(path)))
        self._cache: dict[str, Any] = {}

    def at(self, when: datetime) -> tuple[str, datetime, Any] | None:
        chosen = None
        for sha, at in self.versions:
            if at <= when:
                chosen = (sha, at)
            else:
                break
        if chosen is None:
            return None
        sha, at = chosen
        if sha not in self._cache:
            self._cache[sha] = sweep.board_at(self.key, self.path, sha)
        return sha, at, self._cache[sha]


def groups_and_providers(
    registry_groups: Mapping[str, str], lineage: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    groups = {k: g for k, g in registry_groups.items() if g}
    groups.update(EXTRA_GROUPS)
    providers = {k: str(s.get("provider")) for k, s in (lineage.get("sources") or {}).items()}
    return groups, providers


def lfo_others(
    pool: Sequence[str],
    members: Sequence[str],
    groups: Mapping[str, str],
    providers: Mapping[str, str],
) -> list[str]:
    """Pool minus the members, their B10 correlation groups and their providers."""
    gs = {groups[m] for m in members if groups.get(m)}
    ps = {providers[m] for m in members if providers.get(m)}
    return [
        k
        for k in pool
        if k not in members
        and not (groups.get(k) and groups[k] in gs)
        and not (providers.get(k) and providers[k] in ps)
    ]


def common_population(
    orders: Mapping[str, Mapping[str, float]],
    members: Sequence[str],
    others: Sequence[str],
    min_cover: float = MIN_COMMON_COVER,
) -> tuple[list[str], list[str]]:
    """(consensus boards, shared population) for the common-population rule.

    Consensus boards are those covering at least ``min_cover`` of the
    members' shared players; the population is the players EVERY member and
    every such board ranks.  Re-ranking each board inside one identical
    population removes the depth artifact of per-board percentiles: a
    370-row board and a 460-row board otherwise sit on different percentile
    scales, which is a residual shared by every pair of deep (or shallow)
    boards whatever their opinions."""
    base: set[str] = set(orders.get(members[0]) or {})
    for m in members[1:]:
        base &= set(orders.get(m) or {})
    if not base:
        return [], []
    incl = [
        k for k in others if k in orders and len(base & set(orders[k])) >= min_cover * len(base)
    ]
    pop = set(base)
    for k in incl:
        pop &= set(orders[k])
    return incl, sorted(pop)


def restrict(
    orders: Mapping[str, Mapping[str, float]],
    values: Mapping[str, Mapping[str, float]],
    keys: Sequence[str],
    pop: Sequence[str],
) -> tuple[dict[str, dict[str, float]], dict[str, dict[str, float]]]:
    """Percentiles and ln(value / max) of ``keys`` re-computed inside ``pop``."""
    pct: dict[str, dict[str, float]] = {}
    logv: dict[str, dict[str, float]] = {}
    for k in keys:
        pct[k] = sweep.to_percentiles({n: orders[k][n] for n in pop})
        vals = {n: values[k][n] for n in pop if n in (values.get(k) or {})}
        if pop and len(vals) == len(pop):
            top = max(vals.values())
            logv[k] = {n: math.log(v / top) for n, v in vals.items()}
    return pct, logv


def _rank_and_value(
    pct: Mapping[str, Mapping[str, float]],
    logv: Mapping[str, Mapping[str, float]],
    a: str,
    b: str,
    others: Sequence[str],
    min_others: int,
) -> dict[str, Any]:
    res, n = sweep.leave_pair_out_residuals(pct, a, b, others, min_others)
    return {
        "rankResidual": None if res is None else round(res, 4),
        "nRank": n,
        **pair_value_dependence(logv, a, b, [k for k in others if k in logv]),
        "consensusSources": len([k for k in others if k in pct]),
    }


def _partial_block(
    signal: Mapping[str, Mapping[str, float]],
    a: str,
    b: str,
    z: str,
    others: Sequence[str],
    min_o: int,
) -> dict[str, Any] | None:
    if not all(k in signal for k in (a, b, z)):
        return None
    (ra, rb, rz), _ = residual_vectors(signal, [a, b, z], others, min_o)
    if len(ra) < sweep.MIN_PAIR_OVERLAP:
        return {"n": len(ra)}
    rab, raz, rbz = pearson(ra, rb), pearson(ra, rz), pearson(rb, rz)
    part = None if rab is None or raz is None or rbz is None else partial_correlation(rab, raz, rbz)
    return {
        "n": len(ra),
        "rAB": None if rab is None else round(rab, 4),
        "rAZ": None if raz is None else round(raz, 4),
        "rBZ": None if rbz is None else round(rbz, 4),
        "partialAB_given_Z": None if part is None else round(part, 4),
    }


def _empty_cp(incl: Sequence[str], pop: Sequence[str]) -> dict[str, Any]:
    return {
        "rankResidual": None,
        "nRank": len(pop),
        "valueResidualRaw": None,
        "valueResidualDetrended": None,
        "nValue": 0,
        "consensusSources": len(incl),
        "population": len(pop),
    }


def measure_snapshot(
    boards: Mapping[str, Any],
    pool: Sequence[str],
    pairs: Sequence[tuple[str, str]],
    indirect: Sequence[tuple[str, str, str]],
    groups: Mapping[str, str],
    providers: Mapping[str, str],
    universe: Mapping[str, str],
    positions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Every pair under every variant at one snapshot.

    ``lpo`` / ``lfo`` are the sweep's per-board percentiles (``lfo`` drops
    the members' families and providers from the consensus); ``cp_*`` re-rank
    inside one common population; ``cpx_*`` do the same with TE rows removed.
    ``positions`` maps identity -> position letters for the TE filter."""
    positions = positions or {}
    pct: dict[str, dict[str, float]] = {}
    logv: dict[str, dict[str, float]] = {}
    orders: dict[str, dict[str, float]] = {}
    values: dict[str, dict[str, float]] = {}
    for key, board in boards.items():
        idents = [
            i
            for i, e in board.entries.items()
            if universe.get(i) == "offense" and not sweep.is_pick_name(e["raw"])
        ]
        if len(idents) >= sweep.MIN_PAIR_OVERLAP:
            orders[key] = sweep.ordering(board, idents)
            pct[key] = sweep.to_percentiles(orders[key])
            values[key] = {
                i: board.entries[i]["value"]
                for i in idents
                if board.entries[i]["value"] is not None and board.entries[i]["value"] > 0
            }
            lv = log_values(board, idents)
            if lv:
                logv[key] = lv
    out_pairs: list[dict[str, Any]] = []
    for a, b in pairs:
        if a not in pct or b not in pct:
            continue
        row: dict[str, Any] = {"a": a, "b": b}
        for variant, others in (
            ("lpo", [k for k in pool if k not in (a, b)]),
            ("lfo", lfo_others(pool, (a, b), groups, providers)),
        ):
            row[variant] = _rank_and_value(pct, logv, a, b, others, sweep.MIN_CONSENSUS_OTHERS)
            incl, pop = common_population(orders, (a, b), others)
            for prefix, members in (
                ("cp", pop),
                ("cpx", [n for n in pop if positions.get(n, "") not in TE_EXCLUDED_POSITIONS]),
            ):
                if (
                    len(incl) >= sweep.MIN_CONSENSUS_OTHERS
                    and len(members) >= sweep.MIN_PAIR_OVERLAP
                ):
                    cpct, clogv = restrict(orders, values, [a, b, *incl], members)
                    row[f"{prefix}_{variant}"] = {
                        **_rank_and_value(cpct, clogv, a, b, incl, len(incl)),
                        "population": len(members),
                    }
                else:
                    row[f"{prefix}_{variant}"] = _empty_cp(incl, members)
        out_pairs.append(row)
    out_indirect: list[dict[str, Any]] = []
    for a, b, z in indirect:
        if not all(k in pct for k in (a, b, z)):
            continue
        others = [k for k in pool if k not in (a, b, z)]
        entry: dict[str, Any] = {"a": a, "b": b, "via": z}
        entry["rank"] = _partial_block(pct, a, b, z, others, sweep.MIN_CONSENSUS_OTHERS)
        entry["value"] = _partial_block(logv, a, b, z, others, MIN_VALUE_OTHERS)
        incl, pop = common_population(orders, (a, b, z), others)
        nte = [n for n in pop if positions.get(n, "") not in TE_EXCLUDED_POSITIONS]
        if len(incl) >= sweep.MIN_CONSENSUS_OTHERS and len(nte) >= sweep.MIN_PAIR_OVERLAP:
            cpct, clogv = restrict(orders, values, [a, b, z, *incl], nte)
            entry["cpx_rank"] = _partial_block(cpct, a, b, z, incl, len(incl))
            entry["cpx_value"] = _partial_block(clogv, a, b, z, incl, MIN_VALUE_OTHERS)
        out_indirect.append(entry)
    return {"pairs": out_pairs, "indirect": out_indirect}


def snapshot_instants(start: datetime, end: datetime, step_days: int) -> list[datetime]:
    out, t = [], start
    while t <= end:
        out.append(t)
        t += timedelta(days=step_days)
    if out and out[-1] != end:
        out.append(end)
    return out


def aggregate(snapshots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_pair: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for snap in snapshots:
        for row in snap["pairs"]:
            by_pair.setdefault((row["a"], row["b"]), []).append(
                {**row, "versions": snap["versions"]}
            )
    out = []
    for (a, b), rows in by_pair.items():
        entry: dict[str, Any] = {"a": a, "b": b}
        distinct = {(r["versions"].get(a), r["versions"].get(b)) for r in rows}
        entry["distinctVersionPairs"] = len(distinct)
        entry["distinctVersions"] = {
            a: len({r["versions"].get(a) for r in rows}),
            b: len({r["versions"].get(b) for r in rows}),
        }
        entry["control"] = (a, b) in CONTROL_PAIRS
        for variant in VARIANTS:
            vs = [r[variant] for r in rows]
            entry[variant] = {
                "rankResidual": summarize([v["rankResidual"] for v in vs]),
                "valueResidualRaw": summarize([v["valueResidualRaw"] for v in vs]),
                "valueResidualDetrended": summarize([v["valueResidualDetrended"] for v in vs]),
                "nRankMedian": int(statistics.median([v["nRank"] for v in vs])),
                "nValueMedian": int(statistics.median([v["nValue"] for v in vs])),
            }
        out.append(entry)
    return out


def run(start: datetime, end: datetime, step_days: int, pool: Sequence[str]) -> dict[str, Any]:
    from src.api import data_contract as dc

    sweep._registry()
    lineage = json.loads(LINEAGE_PATH.read_text(encoding="utf-8"))
    groups, providers = groups_and_providers(
        {s["key"]: s.get("correlation_group") for s in dc._RANKING_SOURCES}, lineage
    )
    keys = sorted(
        set(pool)
        | {SUBJECT, *COMPARATORS}
        | {k for pair in CONTROL_PAIRS for k in pair}
        | set(POOL_CARRIERS.values())
    )
    hist = {k: History(k, sweep.csv_path(k)) for k in keys}
    current = {k: b for k in keys if (b := sweep.load_board(k, sweep.csv_path(k))) is not None}
    pairs = [(SUBJECT, c) for c in COMPARATORS] + list(CONTROL_PAIRS)
    positions = sweep._position_map()
    snaps = []
    for t in snapshot_instants(start, end, step_days):
        boards: dict[str, Any] = {}
        versions: dict[str, str] = {}
        ages: dict[str, float] = {}
        for k in keys:
            got = hist[k].at(t)
            if got is None:
                continue
            sha, at, board = got
            boards[k], versions[k] = board, sha
            ages[k] = round((t - at).total_seconds() / 86400.0, 1)
        substituted = {}
        for live, carrier in POOL_CARRIERS.items():
            if live not in boards and carrier in boards:
                boards[live] = boards[carrier]
                versions[live] = f"{carrier}@{versions[carrier]}"
                substituted[live] = carrier
        if SUBJECT not in boards:
            continue
        # Universe from boards at T, backed by today's boards for identities no
        # board at T places (positions do not change with time for these rows).
        universe = sweep.build_universe_index({**current, **boards})
        snap_pool = [k for k in pool if k in boards]
        # A carrier fills the consensus pool only; it is never a measured member.
        snap_pairs = [(a, b) for a, b in pairs if a not in substituted and b not in substituted]
        result = measure_snapshot(
            boards, snap_pool, snap_pairs, INDIRECT_PATHS, groups, providers, universe, positions
        )
        snaps.append(
            {
                "at": t.isoformat(),
                "pool": snap_pool,
                "poolCarrierSubstitution": substituted,
                "versions": versions,
                "ageDays": ages,
                **result,
            }
        )
    return {
        "schema": "lineage-pair-snapshots/v1",
        "subject": SUBJECT,
        "method": {
            "rankResidual": "leave-pair-out residual correlation of percentile ranks "
            "(scripts/audit/lineage_integrity_sweep.py::leave_pair_out_residuals), offense "
            f"universe, picks excluded, >= {sweep.MIN_CONSENSUS_OTHERS} consensus observations "
            f"per player, >= {sweep.MIN_PAIR_OVERLAP} players",
            "valueResidualRaw": "same construction on ln(value / board max) over boards "
            "publishing positive native values; includes shared curve shape",
            "valueResidualDetrended": "valueResidualRaw after removing each residual's "
            "least-squares cubic in the consensus ln-value (curve shape removed)",
            "lpo": "consensus = voting pool minus both members (the sweep's rule)",
            "lfo": "consensus additionally excludes every pool source in either member's "
            "B10 correlation group or from either member's provider",
            "partial": "r(A,B | Z) on residuals against a consensus excluding A, B and Z",
            "cp": "common population: every member and every consensus board covering "
            f">= {MIN_COMMON_COVER:.0%} of the members' shared players re-ranked inside the "
            "players they ALL rank (removes the per-board-percentile depth artifact)",
            "cpx": "cp with TE rows removed (value bases differ: KTC TE++ vs base boards)",
            "baseline": "leave-pair-out residuals share the consensus error: expect about "
            "+1/(k+1) for k equally noisy consensus boards even with no dependence",
            "snapshots": f"every {step_days} days {start.date()}..{end.date()} at 23:59:59Z; "
            "each board = last committed CSV version at or before the instant",
        },
        "codeSha": sweep._git("rev-parse", "HEAD").strip(),
        "groups": {k: groups.get(k) for k in keys},
        "providers": {k: providers.get(k) for k in keys},
        "summary": aggregate(snaps),
        "indirectSummary": _indirect_summary(snaps),
        "snapshots": snaps,
    }


def _indirect_summary(snaps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for s in snaps:
        for e in s["indirect"]:
            by.setdefault((e["a"], e["b"], e["via"]), []).append(e)
    out = []
    for (a, b, z), rows in by.items():
        entry: dict[str, Any] = {"a": a, "b": b, "via": z}
        for label in ("rank", "value", "cpx_rank", "cpx_value"):
            vs = [r[label] for r in rows if isinstance(r.get(label), Mapping) and "rAB" in r[label]]
            entry[label] = {
                "rAB": summarize([v["rAB"] for v in vs]),
                "rAZ": summarize([v["rAZ"] for v in vs]),
                "rBZ": summarize([v["rBZ"] for v in vs]),
                "partialAB_given_Z": summarize([v["partialAB_given_Z"] for v in vs]),
                "nMedian": int(statistics.median([v["n"] for v in vs])) if vs else 0,
            }
        out.append(entry)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--start", default="2026-05-16")
    parser.add_argument("--end", default="2026-10-01")
    parser.add_argument("--step-days", type=int, default=7)
    args = parser.parse_args(argv)
    if not sweep.CSV_DIR.is_dir():
        print(f"[pair-snapshots] missing {sweep.CSV_DIR}", file=sys.stderr)
        return 2
    voting, _ = sweep._registry()

    def _instant(day: str) -> datetime:
        return datetime.fromisoformat(day).replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

    result = run(_instant(args.start), _instant(args.end), args.step_days, voting)
    text = json.dumps(result, indent=1, default=str) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"[pair-snapshots] wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
