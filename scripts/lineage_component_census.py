#!/usr/bin/env python3
"""Manager-lineage component census for the Chase Upside Trade Market holdout
decision (owner decision Package 5A, 2026-10-21).  RESEARCH ONLY.

The owner has NOT chosen a reserve policy.  Their stated intent for Q2 was to
hold out ENTIRE LEAGUES with chronological separation; a permanent 20%
manager-lineage reserve and its five-way split are NOT approved.  This script
measures the evidence the owner asked for before choosing:

* the real sizes of manager-lineage components among completed trades (their
  distribution, concentration -- top-k shares, HHI, Gini -- and coverage);
* what candidate allocation policies would look like on that population --
  whole-league holdout with a chronological split (the owner's intent), a
  lineage-component reserve at a few sizes, a hybrid, and a chronological-only
  reference -- with their leakage, size and concentration.

What it never does:

* it never draws, persists or exposes THE reserve.  The policy simulations use
  throwaway seeds and a different hash input (``census-sim|seed|unit``) from the
  reserve's ``sha256(component || 0x1f || committed salt)``, so no result here
  says anything about which components the committed salt would lock;
* it writes nothing, opens every store ``mode=ro`` and prints aggregates only:
  no league, lineage, user, manager, transaction or asset id ever leaves the
  process (``assert_aggregate_only``);
* it changes no value, vote, weight, flag or served payload.

Components.  A trade belongs to its league (season-league).  Three nested
definitions, so the effect of each kind of link is visible:

* ``L`` lineage: season-leagues joined along ``previous_league_id``;
* ``P`` participants: ``L`` plus a link through every manager who was a side
  of a trade in the population (the plan's manager-lineage component);
* ``M`` memberships: ``P`` plus a link through every member of a population
  league (a manager can carry knowledge into a league without trading there).

A trade with no league id is its own unlinkable singleton (and its leakage is
unmeasurable, not zero).  Manager links exist only where the host record names
the managers -- the Sleeper-observed lane via the Sharp intel ledger; KTC
database rows name a league but no manager.

Run on the production host with ``--box`` (owner-authorized, separately; see
``docs/market_trades/LINEAGE_COMPONENT_CENSUS_2026-10-21.md``): the read-only
audit hook (``research_readonly_guard.py``) is installed BEFORE any application
import.  Locally: ``--ledger PATH --intel PATH`` against copies, or
``--synthetic OVERLAP`` for a labelled synthetic rehearsal.
Exit codes: 0 ok, 2 an input store is absent, 3 the guard refused a write /
process start.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(os.environ.get("RISKIT_APP_DIR") or Path(__file__).resolve().parents[1]).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent

# numpy is third-party (no application code) and is imported before the guard
# because CPython's ctypes import performs a dlopen the guard refuses.
sys.dont_write_bytecode = True
import numpy as np  # noqa: E402

if "--box" in sys.argv:
    _gspec = importlib.util.spec_from_file_location(
        "research_readonly_guard", SCRIPT_DIR / "research_readonly_guard.py"
    )
    GUARD = importlib.util.module_from_spec(_gspec)
    sys.modules["research_readonly_guard"] = GUARD
    _gspec.loader.exec_module(GUARD)
    GUARD.install()
else:
    GUARD = None

sys.path.insert(0, str(REPO))

CENSUS_VERSION = "ctm-lineage-component-census-v1"
SIM_PREFIX = "census-sim"
DEFINITIONS = ("L", "P", "M")
DEFAULT_FRACTIONS = (0.10, 0.20, 0.30)
DEFAULT_WINDOWS = (28, 56)
DEFAULT_PURGE_DAYS = 7
DEFAULT_GIANT_SHARE = 0.05
DEFAULT_REPLICATES = 100
TOP_K = (1, 5, 10, 20, 50)
SIZE_BUCKETS = ((1, 1), (2, 4), (5, 9), (10, 49), (50, 249), (250, 999), (1000, None))

LANE_SLEEPER = "sleeper_observed"
LANE_KTC = "ktc_database"
LANE_BOTH = "sleeper_and_ktc"
LANE_OTHER = "other"
_SLEEPER_FAMILIES = ("sleeper_sharp_discovery", "own_league_sleeper")
_KTC_FAMILY = "ktc_trade_database"
_UNPROVEN_DEDUPE = ("POSSIBLE_OVERLAP", "UNRESOLVED")
_NO_PREDECESSOR = ("", "0", "None")

# ── data model ──────────────────────────────────────────────────────────────


@dataclass
class Trade:
    lane: str
    league: str | None
    day: date | None
    participants: tuple[str, ...] = ()
    fit: bool = False


@dataclass
class Dataset:
    trades: list[Trade]
    predecessor: dict[str, str] = field(default_factory=dict)
    members: dict[str, set[str]] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)


def trade_lane(families: Iterable[str]) -> str:
    fams = set(families or ())
    sleeper = bool(fams & set(_SLEEPER_FAMILIES))
    ktc = _KTC_FAMILY in fams
    if sleeper and ktc:
        return LANE_BOTH
    if sleeper:
        return LANE_SLEEPER
    if ktc:
        return LANE_KTC
    return LANE_OTHER


def _parse_day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


# ── union-find ──────────────────────────────────────────────────────────────


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        parent = self.parent
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            self.parent[rb] = ra


def _lineage_roots(ds: Dataset, leagues: Iterable[str]) -> dict[str, str]:
    """League -> lineage root, walking ``previous_league_id`` (loop-safe)."""
    uf = _UnionFind()
    for lg in leagues:
        seen: set[str] = set()
        cur = lg
        uf.find("L:" + cur)
        while cur in ds.predecessor and cur not in seen:
            seen.add(cur)
            prev = ds.predecessor[cur]
            uf.union("L:" + cur, "L:" + prev)
            cur = prev
    return {lg: uf.find("L:" + lg) for lg in leagues}


def component_labels(ds: Dataset, idx: Sequence[int], definition: str) -> np.ndarray:
    """Per-trade component label (dense ints, in ``idx`` order)."""
    if definition not in DEFINITIONS:
        raise ValueError(f"unknown component definition {definition!r}")
    trades = [ds.trades[i] for i in idx]
    leagues = sorted({t.league for t in trades if t.league})
    lineage = _lineage_roots(ds, leagues)
    uf = _UnionFind()
    for lg in leagues:
        uf.union("L:" + lg, lineage[lg])
    if definition in ("P", "M"):
        for t in trades:
            if t.league:
                for u in t.participants:
                    uf.union("L:" + t.league, "U:" + u)
    if definition == "M":
        for lg in leagues:
            for u in ds.members.get(lg, ()):
                uf.union("L:" + lg, "U:" + u)
    raw = [uf.find("L:" + t.league) if t.league else f"T:{k}" for k, t in enumerate(trades)]
    _, labels = np.unique(np.asarray(raw, dtype=object).astype(str), return_inverse=True)
    return labels.astype(np.int64)


# ── concentration ───────────────────────────────────────────────────────────


def _r(x: float) -> float:
    return round(float(x), 4)


def _gini(counts: np.ndarray) -> float:
    if counts.size == 0 or counts.sum() == 0:
        return 0.0
    c = np.sort(counts.astype(float))
    n = c.size
    return float((2.0 * np.sum(np.arange(1, n + 1) * c) / (n * c.sum())) - (n + 1) / n)


def concentration(labels: np.ndarray) -> dict[str, Any]:
    """Size distribution and concentration of trades over components."""
    counts = np.bincount(labels) if labels.size else np.zeros(0, dtype=np.int64)
    counts = counts[counts > 0]
    total = int(counts.sum())
    if total == 0:
        return {"components": 0, "trades": 0}
    desc = np.sort(counts)[::-1]
    shares = desc / total
    hhi = float(np.sum(shares**2))
    hist: dict[str, int] = {}
    for lo, hi in SIZE_BUCKETS:
        mask = (counts >= lo) & ((counts <= hi) if hi is not None else True)
        key = f"{lo}" if hi == lo else (f"{lo}+" if hi is None else f"{lo}-{hi}")
        hist[key] = int(np.sum(mask))
    return {
        "components": int(counts.size),
        "trades": total,
        "tradesPerComponent": {
            "mean": _r(counts.mean()),
            "p50": _r(np.percentile(counts, 50)),
            "p90": _r(np.percentile(counts, 90)),
            "p99": _r(np.percentile(counts, 99)),
            "max": int(desc[0]),
        },
        "componentsBySize": hist,
        "topKTradeShare": {str(k): _r(shares[:k].sum()) for k in TOP_K},
        "hhi": _r(hhi),
        "effectiveComponents": _r(1.0 / hhi),
        "gini": _r(_gini(counts)),
        "singletonComponents": int(np.sum(counts == 1)),
    }


def largest_component_profile(ds: Dataset, idx: Sequence[int], labels: np.ndarray) -> dict:
    """How much of the population the single largest component holds."""
    if labels.size == 0:
        return {}
    big = int(np.argmax(np.bincount(labels)))
    members = [ds.trades[idx[k]] for k in np.flatnonzero(labels == big)]
    leagues = {t.league for t in members if t.league}
    all_leagues = {ds.trades[i].league for i in idx if ds.trades[i].league}
    mgrs = {u for t in members for u in t.participants}
    all_mgrs = {u for i in idx for u in ds.trades[i].participants}
    return {
        "tradeShare": _r(len(members) / len(idx)),
        "leagueShare": _r(len(leagues) / max(1, len(all_leagues))),
        "participantManagerShare": _r(len(mgrs) / max(1, len(all_mgrs))),
        "lineages": len(set(_lineage_roots(ds, leagues).values())),
    }


def coverage(ds: Dataset, idx: Sequence[int]) -> dict[str, Any]:
    trades = [ds.trades[i] for i in idx]
    days = sorted(t.day for t in trades if t.day)
    leagues = {t.league for t in trades if t.league}
    by_month: dict[str, int] = {}
    for d in days:
        by_month[d.strftime("%Y-%m")] = by_month.get(d.strftime("%Y-%m"), 0) + 1
    by_lane: dict[str, int] = {}
    for t in trades:
        by_lane[t.lane] = by_lane.get(t.lane, 0) + 1
    with_mgr = sum(1 for t in trades if t.participants)
    return {
        "trades": len(trades),
        "byLane": dict(sorted(by_lane.items())),
        "leagues": len(leagues),
        "lineages": len(set(_lineage_roots(ds, leagues).values())),
        "leaguesWithMembership": sum(1 for lg in leagues if ds.members.get(lg)),
        "tradesWithoutLeague": sum(1 for t in trades if not t.league),
        "tradesWithParticipants": with_mgr,
        "participantCoverage": _r(with_mgr / max(1, len(trades))),
        "participantManagers": len({u for t in trades for u in t.participants}),
        "dateRange": [days[0].isoformat(), days[-1].isoformat()] if days else None,
        "tradesWithoutDate": len(trades) - len(days),
        "byMonth": dict(sorted(by_month.items())),
    }


# ── allocation policies (simulated; never the committed reserve) ────────────


def _unit_uniform(unit: str, seed: int) -> float:
    h = hashlib.sha256(f"{SIM_PREFIX}|{seed}|{unit}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2.0**64


def _csr(lists: Sequence[Sequence[int]]) -> tuple[np.ndarray, np.ndarray]:
    lens = np.fromiter((len(x) for x in lists), dtype=np.int64, count=len(lists))
    ptr = np.zeros(len(lists) + 1, dtype=np.int64)
    np.cumsum(lens, out=ptr[1:])
    flat = np.fromiter((v for x in lists for v in x), dtype=np.int64, count=int(ptr[-1]))
    return ptr, flat


def _leak_through(ptr: np.ndarray, flat: np.ndarray, n_keys: int, train: np.ndarray) -> np.ndarray:
    """Per row: does any of its keys (managers / members) also sit on a
    TRAINING row?  Rows with no keys never leak (and are counted apart)."""
    if n_keys == 0 or flat.size == 0:
        return np.zeros(len(ptr) - 1, dtype=bool)
    in_train = np.zeros(n_keys, dtype=bool)
    in_train[flat[np.repeat(train, np.diff(ptr))]] = True
    cums = np.concatenate([[0], np.cumsum(in_train[flat].astype(np.int64))])
    return (cums[ptr[1:]] - cums[ptr[:-1]]) > 0


@dataclass
class _Frame:
    """Population arrays shared by every policy and replicate."""

    n: int
    day: np.ndarray  # ordinal, -1 unknown
    lineage: np.ndarray
    comp_p: np.ndarray
    has_league: np.ndarray
    has_mgr: np.ndarray
    mgr_ptr: np.ndarray
    mgr_flat: np.ndarray
    n_mgr: int
    mem_ptr: np.ndarray
    mem_flat: np.ndarray
    n_mem: int
    has_mem: np.ndarray
    lineage_names: list[str]
    comp_names: list[str]


def _frame(ds: Dataset, idx: Sequence[int]) -> _Frame:
    trades = [ds.trades[i] for i in idx]
    lin = component_labels(ds, idx, "L")
    cp = component_labels(ds, idx, "P")
    mgr_ids: dict[str, int] = {}
    mgr_lists = [[mgr_ids.setdefault(u, len(mgr_ids)) for u in t.participants] for t in trades]
    mem_ids: dict[str, int] = {}
    mem_lists = [
        [mem_ids.setdefault(u, len(mem_ids)) for u in sorted(ds.members.get(t.league or "", ()))]
        for t in trades
    ]
    mptr, mflat = _csr(mgr_lists)
    eptr, eflat = _csr(mem_lists)
    return _Frame(
        n=len(trades),
        day=np.array([t.day.toordinal() if t.day else -1 for t in trades], dtype=np.int64),
        lineage=lin,
        comp_p=cp,
        has_league=np.array([bool(t.league) for t in trades]),
        has_mgr=np.array([bool(t.participants) for t in trades]),
        mgr_ptr=mptr,
        mgr_flat=mflat,
        n_mgr=len(mgr_ids),
        mem_ptr=eptr,
        mem_flat=eflat,
        n_mem=len(mem_ids),
        has_mem=np.array([bool(x) for x in mem_lists]),
        # opaque labels only feed the throwaway hash; never emitted
        lineage_names=[f"lin{k}" for k in range(int(lin.max()) + 1 if lin.size else 0)],
        comp_names=[f"cmp{k}" for k in range(int(cp.max()) + 1 if cp.size else 0)],
    )


def _held_units(names: Sequence[str], fraction: float, seed: int) -> np.ndarray:
    return np.array([_unit_uniform(u, seed) < fraction for u in names], dtype=bool)


def _evaluate(fr: _Frame, train: np.ndarray, ev: np.ndarray) -> dict[str, float]:
    """Leakage, size and concentration of one (train, eval) split."""
    n_eval = int(ev.sum())
    out: dict[str, float] = {
        "train": float(train.sum()),
        "eval": float(n_eval),
        "unused": float(fr.n - train.sum() - n_eval),
    }
    if n_eval == 0:
        return out
    mgr_leak = _leak_through(fr.mgr_ptr, fr.mgr_flat, fr.n_mgr, train)
    mem_leak = _leak_through(fr.mem_ptr, fr.mem_flat, fr.n_mem, train)
    lin_train = np.zeros(int(fr.lineage.max()) + 1, dtype=bool)
    lin_train[fr.lineage[train & fr.has_league]] = True
    lin_leak = lin_train[fr.lineage] & fr.has_league
    cp_train = np.zeros(int(fr.comp_p.max()) + 1, dtype=bool)
    cp_train[fr.comp_p[train & fr.has_league]] = True
    cp_leak = cp_train[fr.comp_p] & fr.has_league
    ev_obs = ev & fr.has_mgr
    ev_mem = ev & fr.has_mem
    shares = np.bincount(fr.comp_p[ev]) / n_eval
    hhi = float(np.sum(shares**2))
    out.update(
        {
            "evalShare": float(n_eval / fr.n),
            "evalDatedBeforeTrainEnd": _before_train_end(fr, train, ev) / n_eval,
            "evalComponentsP": float(np.count_nonzero(shares)),
            "evalEffectiveComponentsP": 1.0 / hhi,
            "evalLargestComponentShare": float(shares.max()),
            "evalLineages": float(np.unique(fr.lineage[ev & fr.has_league]).size),
            "lineageLeak": float((lin_leak & ev).sum() / n_eval),
            "componentLeakP": float((cp_leak & ev).sum() / n_eval),
            "participantLeak": float((mgr_leak & ev_obs).sum() / max(1, ev_obs.sum())),
            "participantUnobserved": float((ev & ~fr.has_mgr).sum() / n_eval),
            "membershipLeak": float((mem_leak & ev_mem).sum() / max(1, ev_mem.sum())),
            "leakageUnmeasurable": float((ev & ~fr.has_league).sum() / n_eval),
        }
    )
    return out


def _before_train_end(fr: _Frame, train: np.ndarray, ev: np.ndarray) -> float:
    """Eval trades dated on or before the newest training trade (temporal
    overlap -- what a chronological split removes)."""
    tr_days = fr.day[train & (fr.day >= 0)]
    if tr_days.size == 0:
        return 0.0
    return float((ev & (fr.day >= 0) & (fr.day <= tr_days.max())).sum())


def _summ(rows: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    keys = sorted({k for r in rows for k in r})
    out: dict[str, Any] = {}
    for k in keys:
        vals = np.array([r[k] for r in rows if k in r], dtype=float)
        if vals.size == 0:
            continue
        if np.allclose(vals, vals[0]):
            out[k] = _r(vals[0])
        else:
            out[k] = {
                "mean": _r(vals.mean()),
                "p5": _r(np.percentile(vals, 5)),
                "p95": _r(np.percentile(vals, 95)),
            }
    return out


def _windows(fr: _Frame, window_days: int, purge_days: int) -> tuple[np.ndarray, np.ndarray]:
    known = fr.day >= 0
    if not known.any():
        return np.zeros(fr.n, bool), np.zeros(fr.n, bool)
    end = int(fr.day[known].max())
    ev_win = known & (fr.day > end - window_days)
    tr_win = known & (fr.day <= end - window_days - purge_days)
    return tr_win, ev_win


def simulate_policies(
    ds: Dataset,
    idx: Sequence[int],
    *,
    fractions: Sequence[float] = DEFAULT_FRACTIONS,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    purge_days: int = DEFAULT_PURGE_DAYS,
    giant_share: float = DEFAULT_GIANT_SHARE,
    replicates: int = DEFAULT_REPLICATES,
) -> dict[str, Any]:
    """Every candidate policy, over ``replicates`` throwaway seeds."""
    fr = _frame(ds, idx)
    if fr.n == 0:
        return {}
    largest = int(np.argmax(np.bincount(fr.comp_p)))
    comp_share = np.bincount(fr.comp_p) / fr.n
    giant = comp_share > giant_share
    # Hybrid unit: a non-giant P-component is held whole; inside a giant
    # component the unit falls back to the lineage (league holdout).
    hyb_names = sorted(
        {f"g{fr.lineage[k]}" if giant[fr.comp_p[k]] else f"c{fr.comp_p[k]}" for k in range(fr.n)}
    )
    hyb_pos = {u: j for j, u in enumerate(hyb_names)}
    hyb_unit = np.array(
        [
            hyb_pos[f"g{fr.lineage[k]}" if giant[fr.comp_p[k]] else f"c{fr.comp_p[k]}"]
            for k in range(fr.n)
        ],
        dtype=np.int64,
    )
    out: dict[str, Any] = {
        "giantComponentRule": f"P-component holding more than {giant_share:.0%} of trades",
        "giantComponents": int(giant.sum()),
        "giantTradeShare": _r(comp_share[giant].sum()),
    }
    for w in windows:
        tr_win, ev_win = _windows(fr, w, purge_days)
        out[f"chronologicalOnly_{w}d"] = _summ([_evaluate(fr, tr_win, ev_win)])
    for f in fractions:
        tag = f"{int(round(f * 100))}pct"
        rows_comp: list[dict[str, float]] = []
        rows_lc: dict[int, list[dict[str, float]]] = {w: [] for w in windows}
        rows_cc: dict[int, list[dict[str, float]]] = {w: [] for w in windows}
        rows_hy: dict[int, list[dict[str, float]]] = {w: [] for w in windows}
        largest_in = 0
        for rep in range(replicates):
            held_lin = _held_units(fr.lineage_names, f, rep)[fr.lineage] & fr.has_league
            held_cmp = _held_units(fr.comp_names, f, rep)[fr.comp_p]
            held_hyb = _held_units(hyb_names, f, rep)[hyb_unit]
            largest_in += int(_unit_uniform(fr.comp_names[largest], rep) < f)
            rows_comp.append(_evaluate(fr, ~held_cmp, held_cmp))
            for w in windows:
                tr_win, ev_win = _windows(fr, w, purge_days)
                rows_lc[w].append(_evaluate(fr, tr_win & ~held_lin, ev_win & held_lin))
                rows_cc[w].append(_evaluate(fr, tr_win & ~held_cmp, ev_win & held_cmp))
                rows_hy[w].append(_evaluate(fr, tr_win & ~held_hyb, ev_win & held_hyb))
        out[f"componentReserve_{tag}"] = {
            **_summ(rows_comp),
            "largestComponentHeldRate": _r(largest_in / replicates),
        }
        for w in windows:
            out[f"wholeLeagueChronological_{tag}_{w}d"] = _summ(rows_lc[w])
            out[f"componentChronological_{tag}_{w}d"] = _summ(rows_cc[w])
            out[f"hybrid_{tag}_{w}d"] = _summ(rows_hy[w])
    return out


# ── the census ──────────────────────────────────────────────────────────────


def populations(ds: Dataset) -> dict[str, list[int]]:
    fit = [i for i, t in enumerate(ds.trades) if t.fit]
    return {
        "all": list(range(len(ds.trades))),
        "fitEligible": fit,
        "fitEligibleSleeperObserved": [
            i for i in fit if ds.trades[i].lane in (LANE_SLEEPER, LANE_BOTH)
        ],
    }


def census(
    ds: Dataset,
    *,
    replicates: int = DEFAULT_REPLICATES,
    fractions: Sequence[float] = DEFAULT_FRACTIONS,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    purge_days: int = DEFAULT_PURGE_DAYS,
    giant_share: float = DEFAULT_GIANT_SHARE,
    policy_populations: Sequence[str] = ("fitEligible", "fitEligibleSleeperObserved"),
) -> dict[str, Any]:
    pops = populations(ds)
    result: dict[str, Any] = {"populations": {}}
    for name, idx in pops.items():
        block: dict[str, Any] = {"coverage": coverage(ds, idx), "components": {}}
        for d in DEFINITIONS:
            labels = component_labels(ds, idx, d)
            block["components"][d] = {
                **concentration(labels),
                "largest": largest_component_profile(ds, idx, labels),
            }
        if name in policy_populations and idx:
            block["policies"] = simulate_policies(
                ds,
                idx,
                fractions=fractions,
                windows=windows,
                purge_days=purge_days,
                giant_share=giant_share,
                replicates=replicates,
            )
        result["populations"][name] = block
    result["settings"] = {
        "replicates": replicates,
        "fractions": list(fractions),
        "evalWindowsDays": list(windows),
        "purgeDays": purge_days,
        "giantShare": giant_share,
        "simulationHash": f"sha256('{SIM_PREFIX}|<seed>|<opaque unit>'), seeds 0..{replicates - 1}",
        "dateBasis": "trade date (occurredDate); the protocol's availability filter is collectedAt",
    }
    return result


# ── inputs ──────────────────────────────────────────────────────────────────


def dataset_from_stores(ledger: sqlite3.Connection, intel: sqlite3.Connection | None) -> Dataset:
    """Build the in-memory dataset from the underlying-trade ledger and the
    Sharp intel ledger (both ``mode=ro``).  Raw ids stay in this process."""
    from src.trade import market_trade_eval as ev  # noqa: PLC0415

    trades: list[Trade] = []
    keys: list[tuple[str, str] | None] = []
    audit = {"rows": 0, "excludedUnprovenDedupe": 0, "fitEligible": 0}
    for (record_json,) in ledger.execute(
        "SELECT record_json FROM underlying_trades ORDER BY underlying_trade_id"
    ):
        g = json.loads(record_json)
        audit["rows"] += 1
        if g.get("dedupeState") in _UNPROVEN_DEDUPE:
            audit["excludedUnprovenDedupe"] += 1
            continue
        fit = ev.fit_suitability(g, ev.classify_topology(g))["fit"] != ev.FIT_UNSUITABLE
        audit["fitEligible"] += int(fit)
        league = str(g.get("hostLeagueId") or "").strip() or None
        host = str(g.get("host") or "")
        tx = str(g.get("hostTxId") or "").strip()
        trades.append(
            Trade(
                lane=trade_lane(g.get("sourceFamilies") or ()),
                # a league id is only linkable within one host's id space
                league=f"{host}:{league}" if league else None,
                day=_parse_day(g.get("occurredDate")),
                fit=fit,
            )
        )
        keys.append((league, tx) if host == "sleeper" and league and tx else None)
    predecessor: dict[str, str] = {}
    members: dict[str, set[str]] = {}
    intel_audit: dict[str, Any] = {"available": intel is not None}
    if intel is not None:
        wanted = {k for k in keys if k}
        parts: dict[tuple[str, str], set[str]] = {}
        for lg, tx, uid in intel.execute(
            "SELECT league_id, tx_id, user_id FROM asset_movements WHERE tx_type = 'trade'"
        ):
            key = (str(lg), str(tx))
            if key in wanted and uid:
                parts.setdefault(key, set()).add(str(uid))
        for k, t in zip(keys, trades):
            if k and k in parts:
                t.participants = tuple(sorted(parts[k]))
        for lg, prev in intel.execute("SELECT league_id, previous_league_id FROM leagues"):
            p = str(prev or "").strip()
            if p not in _NO_PREDECESSOR:
                predecessor[f"sleeper:{lg}"] = f"sleeper:{p}"
        pop_leagues = {t.league for t in trades if t.league}
        for lg, uid in intel.execute("SELECT league_id, user_id FROM league_memberships"):
            key = f"sleeper:{lg}"
            if key in pop_leagues and uid:
                members.setdefault(key, set()).add(str(uid))
        intel_audit.update(
            {
                "sleeperTradesJoinable": len(wanted),
                "sleeperTradesWithParticipants": sum(1 for k in wanted if k in parts),
                "predecessorLinks": len(predecessor),
                "populationLeaguesWithMembership": len(members),
            }
        )
    return Dataset(
        trades=trades,
        predecessor=predecessor,
        members=members,
        inputs={"ledger": audit, "intel": intel_audit},
    )


def dataset_synthetic(overlap: float, seed: int = 0, n_leagues: int = 160) -> Dataset:
    """A labelled SYNTHETIC rehearsal from the power-study world generator."""
    from src.trade import market_trade_sim as sim  # noqa: PLC0415

    cfg = sim.SimConfig(seed=seed, n_leagues=n_leagues, manager_multi_league_prob=overlap)
    world = sim.generate_world(cfg)
    lg, ts = world.leagues, world.trades
    start = date(2026, 1, 1)
    trades = [
        Trade(
            lane=LANE_SLEEPER,
            league=f"syn:{int(ts.league[k])}",
            day=start + timedelta(days=int(ts.date[k])),
            participants=(f"m{int(ts.mgr_a[k])}", f"m{int(ts.mgr_b[k])}"),
            fit=True,
        )
        for k in range(len(ts.league))
    ]
    members = {f"syn:{i}": {f"m{m}" for m in seats} for i, seats in enumerate(lg.seats)}
    return Dataset(
        trades=trades,
        members=members,
        inputs={"synthetic": {"perSeatOverlap": overlap, "seed": seed, "leagues": n_leagues}},
    )


# ── output safety ───────────────────────────────────────────────────────────

_ID_LIKE = re.compile(r"\d{9,}|mk:|utrade:|sleeper:|syn:|U:|L:|T:\d")


def assert_aggregate_only(result: Mapping[str, Any]) -> None:
    """Refuse output that carries anything shaped like an identifier."""
    text = json.dumps(result, default=str)
    hit = _ID_LIKE.search(text)
    if hit:
        raise ValueError(f"refusing to publish: identifier-like text at offset {hit.start()}")


def _open_ro(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.synthetic is not None:
        ds = dataset_synthetic(args.synthetic, seed=args.seed)
        label = "SYNTHETIC rehearsal (power-study generator) -- not evidence about real leagues"
    else:
        if args.ledger:
            ledger_path = Path(args.ledger)
        else:
            from src.trade import market_trade_report as report  # noqa: PLC0415

            ledger_path = report.ledger_file_path()
        intel_path = Path(args.intel or REPO / "data" / "intel" / "ledger.sqlite3")
        ledger = _open_ro(ledger_path)
        if ledger is None:
            return {"available": False, "reason": "no_market_trade_ledger_on_this_host"}, 2
        intel = _open_ro(intel_path)
        try:
            built = ledger.execute("SELECT value FROM meta WHERE key = 'builtAt'").fetchone()
            ds = dataset_from_stores(ledger, intel)
        finally:
            ledger.close()
            if intel is not None:
                intel.close()
        ds.inputs["ledgerBuiltAt"] = json.loads(built[0]) if built else None
        label = "production stores (read-only)" if args.box else "local store copies"
    result = {
        "purpose": (
            "RESEARCH ONLY (owner Package 5A, 2026-10-21): manager-lineage component census. "
            "No reserve is drawn, persisted or exposed; nothing is activated."
        ),
        "version": CENSUS_VERSION,
        "dataLabel": label,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": ds.inputs,
        **census(ds, replicates=args.replicates),
    }
    code = 0
    if GUARD is not None:
        denied = GUARD.denied()
        net = [d for d in denied if d["event"].startswith("socket.")]
        fatal = [d for d in denied if not d["event"].startswith("socket.")]
        result["readOnlyGuard"] = {
            "installed": bool(GUARD.installed()),
            "refusedWriteOrProcessAttempts": len(fatal),
            "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
            "refusedNetworkAttempts": len(net),
        }
        code = 3 if fatal else 0
    assert_aggregate_only(result)
    return result, code


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--box", action="store_true", help="read-only production-store run")
    src.add_argument("--ledger", help="local copy of underlying_trades.sqlite")
    src.add_argument("--synthetic", type=float, metavar="OVERLAP", help="per-seat overlap")
    ap.add_argument("--intel", help="local copy of the intel ledger.sqlite3 (with --ledger)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    args = ap.parse_args(argv)
    result, code = run(args)
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
