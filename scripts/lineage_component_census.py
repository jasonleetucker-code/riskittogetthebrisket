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
  reserve's ``sha256(component || 0x1f || committed salt)``; the reserve config
  and its salt are never read;
* it writes nothing at the Python level (``--box`` installs the read-only audit
  hook first), opens every store ``mode=ro`` and prints aggregates only: no
  league, lineage, user, manager, transaction or asset id ever leaves the
  process (``assert_aggregate_only``);
* it changes no value, vote, weight, flag or served payload.

Components.  A trade belongs to its season-league.  Three nested definitions,
so the effect of each kind of link is visible:

* ``L`` lineage: season-leagues joined along the intel ledger's
  ``previous_league_id`` (and a record's ``leagueMaturity.lineageId`` when a
  maturity owner has stamped one);
* ``P`` participants: ``L`` plus a link through every manager observed on a
  side of ANY ledger trade (the plan's manager-lineage component);
* ``M`` memberships: ``P`` plus a link through every recorded member of any
  ledger league (a manager can carry knowledge into a league without trading).

Links come from every trade in the ledger (unproven dedupes included, though
they are never measured), not only the population being measured, so a component is the one a reserve built over all observed trades
would see.  UNKNOWN LINKAGE IS NOT "NO LINKAGE": a trade with no league is an
unlinkable singleton, a trade whose managers are not (fully) observed is
counted as such, and every leakage share says how many evaluation trades it
could not check.

Participants come from the Sharp intel ledger (``asset_movements.user_id``,
joined on the Sleeper transaction id, which is globally unique) -- the box's
market-trade ledger is built without a side-key secret, so its
``sideEvidence.managerKey`` is null.  ``--participants side_keys`` uses the
pseudonymous keys instead once they exist.

Run on the production host with ``--box`` (owner-authorized, separately; see
``docs/market_trades/LINEAGE_COMPONENT_CENSUS_2026-10-21.md``).  Locally:
``--ledger PATH --intel PATH`` against copies, or ``--synthetic OVERLAP`` for a
labelled synthetic rehearsal.  Exit codes: 0 ok, 2 an input store is absent,
3 the guard refused a write / process start, 64 bad invocation.
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

CENSUS_VERSION = "ctm-lineage-component-census-v2"
SIM_PREFIX = "census-sim"
DEFINITIONS = ("L", "P", "M")
DEFAULT_FRACTIONS = (0.10, 0.20, 0.30)
DEFAULT_WINDOWS = (28, 56)
DEFAULT_PURGE_DAYS = 7
DEFAULT_GIANT_SHARE = 0.05
DEFAULT_REPLICATES = 100
TOP_K = (1, 5, 10, 20, 50)
SIZE_BUCKETS = ((1, 1), (2, 4), (5, 9), (10, 49), (50, 249), (250, 999), (1000, None))
MIN_CELL = 5
SUPPRESSED = "<5"
POLICY_POPULATIONS = (
    "fitEligibleSleeperObserved",
    "estimatorEligible",
    "estimatorEligibleSleeperObserved",
)

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
    day: date | None  # the clock the chronological split uses
    participants: tuple[str, ...] = ()
    sides: int = 2
    fit: bool = False
    estimator: bool = False
    occurred: date | None = None
    collected: date | None = None
    lineage_id: str | None = None
    proven: bool = True  # False: an unproven dedupe -- links, never measured

    @property
    def observed(self) -> str:
        """``complete`` / ``partial`` / ``none`` participant observation."""
        if not self.participants:
            return "none"
        return "complete" if len(self.participants) >= max(2, self.sides) else "partial"


@dataclass
class Dataset:
    trades: list[Trade]
    predecessor: dict[str, str] = field(default_factory=dict)
    members: dict[str, set[str]] = field(default_factory=dict)
    known_leagues: set[str] | None = None  # leagues present in the intel table
    inputs: dict[str, Any] = field(default_factory=dict)
    labels: dict[str, np.ndarray] = field(default_factory=dict, repr=False)  # cache


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


def _link_lineage(uf: _UnionFind, ds: Dataset, leagues: Iterable[str]) -> None:
    """Join each league to its recorded predecessors (loop-safe walk)."""
    for lg in leagues:
        seen: set[str] = set()
        cur = lg
        uf.find("L:" + cur)
        while cur in ds.predecessor and cur not in seen:
            seen.add(cur)
            prev = ds.predecessor[cur]
            uf.union("L:" + cur, "L:" + prev)
            cur = prev


def _build_labels(ds: Dataset, definition: str) -> list[str]:
    """Raw component root for EVERY trade under ``definition``; links come
    from the whole ledger, never only the population being measured."""
    if definition not in DEFINITIONS:
        raise ValueError(f"unknown component definition {definition!r}")
    leagues = sorted({t.league for t in ds.trades if t.league})
    uf = _UnionFind()
    _link_lineage(uf, ds, leagues)
    for t in ds.trades:
        if t.league and t.lineage_id:
            uf.union("L:" + t.league, "N:" + t.lineage_id)
    if definition in ("P", "M"):
        for t in ds.trades:
            if t.league:
                for u in t.participants:
                    uf.union("L:" + t.league, "U:" + u)
    if definition == "M":
        for lg in leagues:
            for u in ds.members.get(lg, ()):
                uf.union("L:" + lg, "U:" + u)
    return [uf.find("L:" + t.league) if t.league else f"T:{k}" for k, t in enumerate(ds.trades)]


def _global_labels(ds: Dataset, definition: str) -> np.ndarray:
    """Labels over the whole dataset, cached on it (a dataset is built once
    and never mutated after its first census)."""
    if definition not in ds.labels:
        raw = np.asarray(_build_labels(ds, definition), dtype=object).astype(str)
        _, labels = np.unique(raw, return_inverse=True)
        ds.labels[definition] = labels.astype(np.int64)
    return ds.labels[definition]


def component_labels(ds: Dataset, idx: Sequence[int], definition: str) -> np.ndarray:
    """Per-trade component label (dense ints, in ``idx`` order)."""
    full = _global_labels(ds, definition)
    sub = full[np.asarray(idx, dtype=np.int64)] if len(idx) else np.zeros(0, np.int64)
    _, dense = np.unique(sub, return_inverse=True)
    return dense.astype(np.int64)


# ── concentration ───────────────────────────────────────────────────────────


def _r(x: float) -> float:
    return round(float(x), 4)


def _cell(n: int) -> int | str:
    return SUPPRESSED if 0 < n < MIN_CELL else n


def _gini(counts: np.ndarray) -> float:
    if counts.size == 0 or counts.sum() == 0:
        return 0.0
    c = np.sort(counts.astype(float))
    n = c.size
    return float((2.0 * np.sum(np.arange(1, n + 1) * c) / (n * c.sum())) - (n + 1) / n)


def concentration(labels: np.ndarray) -> dict[str, Any]:
    """Size distribution and concentration of trades over components.  The
    histogram counts COMPONENTS (structural units, not people), so it is not
    small-cell suppressed: "one component of 1000+ trades" is the finding."""
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
    lin = _global_labels(ds, "L")
    return {
        "tradeShare": _r(len(members) / len(idx)),
        "leagueShare": _r(len(leagues) / max(1, len(all_leagues))),
        "participantManagerShare": _r(len(mgrs) / max(1, len(all_mgrs))),
        "lineages": int(np.unique(lin[[idx[k] for k in np.flatnonzero(labels == big)]]).size),
    }


def linkage(ds: Dataset, idx: Sequence[int]) -> dict[str, Any]:
    """How much of the population the census can actually link."""
    trades = [ds.trades[i] for i in idx]
    n = max(1, len(trades))
    obs = {"complete": 0, "partial": 0, "none": 0}
    for t in trades:
        obs[t.observed] += 1
    leagues = {t.league for t in trades if t.league}
    known = ds.known_leagues
    with_pred = sum(1 for lg in leagues if lg in ds.predecessor)
    gaps = sum(
        1
        for lg in leagues
        if lg in ds.predecessor and known is not None and ds.predecessor[lg] not in known
    )
    return {
        "tradesWithoutLeague": sum(1 for t in trades if not t.league),
        "participantsComplete": obs["complete"],
        "participantsPartial": obs["partial"],
        "participantsUnobserved": obs["none"],
        "fullyLinkableShare": _r(
            sum(1 for t in trades if t.league and t.observed == "complete") / n
        ),
        "populationLeagues": len(leagues),
        "leaguesInIntelTable": (
            sum(1 for lg in leagues if lg in known) if known is not None else None
        ),
        "leaguesWithPredecessorLink": with_pred,
        "predecessorLinksLeavingTheTable": gaps if known is not None else None,
        "leaguesWithLineageStamp": len({t.league for t in trades if t.league and t.lineage_id}),
    }


def coverage(ds: Dataset, idx: Sequence[int]) -> dict[str, Any]:
    trades = [ds.trades[i] for i in idx]
    by_month: dict[str, int] = {}
    for t in trades:
        if t.day:
            k = t.day.strftime("%Y-%m")
            by_month[k] = by_month.get(k, 0) + 1
    by_lane: dict[str, int] = {}
    for t in trades:
        by_lane[t.lane] = by_lane.get(t.lane, 0) + 1

    def _range(days: list[date]) -> list[str] | None:
        return [min(days).isoformat(), max(days).isoformat()] if days else None

    occ = [t.occurred for t in trades if t.occurred]
    col = [t.collected for t in trades if t.collected]
    return {
        "trades": len(trades),
        "byLane": {k: _cell(v) for k, v in sorted(by_lane.items())},
        "leagues": len({t.league for t in trades if t.league}),
        "lineages": int(np.unique(_global_labels(ds, "L")[list(idx)]).size) if idx else 0,
        "participantManagers": len({u for t in trades for u in t.participants}),
        "occurredDateRange": _range(occ),
        "collectedDateRange": _range(col),
        "tradesWithoutOccurredDate": len(trades) - len(occ),
        "tradesWithoutCollectedDate": len(trades) - len(col),
        "splitClockByMonth": {k: _cell(v) for k, v in sorted(by_month.items())},
    }


# ── allocation policies (simulated; never the committed reserve) ────────────


def _unit_uniforms(n_units: int, prefix: str, seed: int) -> np.ndarray:
    """One throwaway uniform per opaque unit index for one replicate."""
    out = np.empty(n_units, dtype=float)
    for k in range(n_units):
        h = hashlib.sha256(f"{SIM_PREFIX}|{seed}|{prefix}{k}".encode()).digest()
        out[k] = int.from_bytes(h[:8], "big") / 2.0**64
    return out


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
    day: np.ndarray  # split-clock ordinal, -1 unknown
    lineage: np.ndarray
    comp_p: np.ndarray
    has_league: np.ndarray
    complete: np.ndarray
    has_mgr: np.ndarray
    mgr_ptr: np.ndarray
    mgr_flat: np.ndarray
    n_mgr: int
    know_ptr: np.ndarray
    know_flat: np.ndarray
    has_know: np.ndarray


def _frame(ds: Dataset, idx: Sequence[int]) -> _Frame:
    trades = [ds.trades[i] for i in idx]
    # One key space for participants and members, so a manager who TRADES in a
    # training league and is a MEMBER of an evaluation league is a leak.
    key_ids: dict[str, int] = {}
    mgr_lists = [[key_ids.setdefault(u, len(key_ids)) for u in t.participants] for t in trades]
    know_lists = [
        sorted(
            {key_ids.setdefault(u, len(key_ids)) for u in ds.members.get(t.league or "", ())}
            | set(m)
        )
        for t, m in zip(trades, mgr_lists)
    ]
    mptr, mflat = _csr(mgr_lists)
    kptr, kflat = _csr(know_lists)
    return _Frame(
        n=len(trades),
        day=np.array([t.day.toordinal() if t.day else -1 for t in trades], dtype=np.int64),
        lineage=component_labels(ds, idx, "L"),
        comp_p=component_labels(ds, idx, "P"),
        has_league=np.array([bool(t.league) for t in trades], dtype=bool),
        complete=np.array([t.observed == "complete" for t in trades], dtype=bool),
        has_mgr=np.array([bool(t.participants) for t in trades], dtype=bool),
        mgr_ptr=mptr,
        mgr_flat=mflat,
        n_mgr=len(key_ids),
        know_ptr=kptr,
        know_flat=kflat,
        has_know=np.array([bool(x) for x in know_lists], dtype=bool),
    )


def _evaluate(fr: _Frame, train: np.ndarray, ev: np.ndarray) -> dict[str, float]:
    """Leakage, size and concentration of one (train, eval) split.  Size keys
    are always present; the rest only when the evaluation set is non-empty."""
    n_eval = int(ev.sum())
    out: dict[str, float] = {
        "train": float(train.sum()),
        "eval": float(n_eval),
        "evalShare": float(n_eval / fr.n),
        "unused": float(fr.n - train.sum() - n_eval),
    }
    if n_eval == 0:
        return out
    mgr_leak = _leak_through(fr.mgr_ptr, fr.mgr_flat, fr.n_mgr, train)
    know_leak = _leak_through(fr.know_ptr, fr.know_flat, fr.n_mgr, train)
    lin_train = np.zeros(int(fr.lineage.max()) + 1, dtype=bool)
    lin_train[fr.lineage[train & fr.has_league]] = True
    cp_train = np.zeros(int(fr.comp_p.max()) + 1, dtype=bool)
    cp_train[fr.comp_p[train & fr.has_league]] = True
    ev_complete = ev & fr.complete
    ev_know = ev & fr.has_know
    shares = np.bincount(fr.comp_p[ev]) / n_eval
    hhi = float(np.sum(shares**2))
    tr_days = fr.day[train & (fr.day >= 0)]
    before = float((ev & (fr.day >= 0) & (fr.day <= tr_days.max())).sum()) if tr_days.size else 0.0
    out.update(
        {
            "evalDatedBeforeTrainEnd": before / n_eval,
            "evalComponentsP": float(np.count_nonzero(shares)),
            "evalEffectiveComponentsP": 1.0 / hhi,
            "evalLargestComponentShare": float(shares.max()),
            "evalLineages": float(np.unique(fr.lineage[ev & fr.has_league]).size),
            "lineageLeak": float((lin_train[fr.lineage] & fr.has_league & ev).sum() / n_eval),
            "componentLeakP": float((cp_train[fr.comp_p] & fr.has_league & ev).sum() / n_eval),
            # among evaluation trades whose every side is observed
            "participantLeak": float((mgr_leak & ev_complete).sum() / max(1, ev_complete.sum())),
            "participantLeakAnyObserved": float(
                (mgr_leak & ev & fr.has_mgr).sum() / max(1, (ev & fr.has_mgr).sum())
            ),
            "participantPartialShare": float((ev & fr.has_mgr & ~fr.complete).sum() / n_eval),
            "participantUnobservedShare": float((ev & ~fr.has_mgr).sum() / n_eval),
            # a participant OR member of the eval league also trades / sits in
            # a training league
            "membershipLeak": float((know_leak & ev_know).sum() / max(1, ev_know.sum())),
            "leakageUnmeasurableShare": float((ev & ~fr.has_league).sum() / n_eval),
        }
    )
    return out


def _summ(rows: Sequence[Mapping[str, float]]) -> dict[str, Any]:
    """Distribution over replicates.  Never collapsed to a scalar, and the
    number of replicates with a non-empty evaluation set is always stated:
    leak / concentration keys are conditional on it."""
    keys = sorted({k for r in rows for k in r})
    out: dict[str, Any] = {
        "replicates": len(rows),
        "replicatesWithEval": sum(1 for r in rows if r.get("eval", 0) > 0),
    }
    for k in keys:
        vals = np.array([r[k] for r in rows if k in r], dtype=float)
        if vals.size == 0:
            continue
        out[k] = {
            "mean": _r(vals.mean()),
            "p5": _r(np.percentile(vals, 5)),
            "p95": _r(np.percentile(vals, 95)),
            "min": _r(vals.min()),
            "max": _r(vals.max()),
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
    comp_counts = np.bincount(fr.comp_p)
    largest = int(np.argmax(comp_counts))
    giant = comp_counts / fr.n > giant_share
    # Hybrid unit: a non-giant P-component is held whole; inside a giant
    # component the unit falls back to the lineage (league holdout).  With one
    # all-covering giant the hybrid IS the whole-league holdout.
    hyb_keys = [
        ("g", int(fr.lineage[k])) if giant[fr.comp_p[k]] else ("c", int(fr.comp_p[k]))
        for k in range(fr.n)
    ]
    hyb_pos: dict[tuple[str, int], int] = {}
    hyb_unit = np.array([hyb_pos.setdefault(h, len(hyb_pos)) for h in hyb_keys], dtype=np.int64)
    n_lin, n_cmp, n_hyb = int(fr.lineage.max()) + 1, int(fr.comp_p.max()) + 1, len(hyb_pos)
    win = {w: _windows(fr, w, purge_days) for w in windows}
    out: dict[str, Any] = {
        "giantComponentRule": f"P-component holding more than {giant_share:.0%} of trades",
        "giantComponents": int(giant.sum()),
        "giantTradeShare": _r(comp_counts[giant].sum() / fr.n),
        "trainEvalPurgeNote": "unused = trades in neither set (held-out pre-window, purge gap, "
        "non-held in-window, unknown clock)",
    }
    for w in windows:
        tr_win, ev_win = win[w]
        out[f"chronologicalOnly_{w}d"] = _summ([_evaluate(fr, tr_win, ev_win)])
    rows: dict[str, list[dict[str, float]]] = {}
    largest_in = {f: 0 for f in fractions}
    for rep in range(replicates):
        u_lin = _unit_uniforms(n_lin, "lin", rep)
        u_cmp = _unit_uniforms(n_cmp, "cmp", rep)
        u_hyb = _unit_uniforms(n_hyb, "hyb", rep)
        for f in fractions:
            tag = f"{int(round(f * 100))}pct"
            held_lin = (u_lin < f)[fr.lineage] & fr.has_league
            held_cmp = (u_cmp < f)[fr.comp_p]
            held_hyb = (u_hyb < f)[hyb_unit]
            largest_in[f] += int(u_cmp[largest] < f)
            rows.setdefault(f"componentReserve_{tag}", []).append(
                _evaluate(fr, ~held_cmp, held_cmp)
            )
            for w in windows:
                tr_win, ev_win = win[w]
                for name, held in (
                    ("wholeLeagueChronological", held_lin),
                    ("componentChronological", held_cmp),
                    ("hybrid", held_hyb),
                ):
                    rows.setdefault(f"{name}_{tag}_{w}d", []).append(
                        _evaluate(fr, tr_win & ~held, ev_win & held)
                    )
    for key, rs in rows.items():
        out[key] = _summ(rs)
    for f in fractions:
        out[f"componentReserve_{int(round(f * 100))}pct"]["largestComponentHeldRate"] = _r(
            largest_in[f] / replicates
        )
    return out


# ── the census ──────────────────────────────────────────────────────────────


def populations(ds: Dataset) -> dict[str, list[int]]:
    sleeper = (LANE_SLEEPER, LANE_BOTH)
    fit = [i for i, t in enumerate(ds.trades) if t.fit and t.proven]
    est = [i for i, t in enumerate(ds.trades) if t.estimator and t.proven]
    return {
        "allProvenDedupe": [i for i, t in enumerate(ds.trades) if t.proven],
        "fitEligible": fit,
        "fitEligibleSleeperObserved": [i for i in fit if ds.trades[i].lane in sleeper],
        "estimatorEligible": est,
        "estimatorEligibleSleeperObserved": [i for i in est if ds.trades[i].lane in sleeper],
    }


def census(
    ds: Dataset,
    *,
    replicates: int = DEFAULT_REPLICATES,
    fractions: Sequence[float] = DEFAULT_FRACTIONS,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    purge_days: int = DEFAULT_PURGE_DAYS,
    giant_share: float = DEFAULT_GIANT_SHARE,
    policy_populations: Sequence[str] = POLICY_POPULATIONS,
) -> dict[str, Any]:
    pops = populations(ds)
    result: dict[str, Any] = {"populations": {}}
    for name, idx in pops.items():
        block: dict[str, Any] = {
            "coverage": coverage(ds, idx),
            "linkage": linkage(ds, idx),
            "components": {},
        }
        for d in DEFINITIONS:
            labels = component_labels(ds, idx, d)
            block["components"][d] = {
                **concentration(labels),
                "largest": largest_component_profile(ds, idx, labels),
            }
        # Concentration among trades the census can link completely, so an
        # unobserved trade is never read as an independent component.
        full = [i for i in idx if ds.trades[i].league and ds.trades[i].observed == "complete"]
        block["components"]["P_fullyObservedOnly"] = concentration(component_labels(ds, full, "P"))
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
        "smallCellRule": f"trade counts by lane / month in [1, {MIN_CELL}) print as {SUPPRESSED!r}",
    }
    return result


# ── inputs ──────────────────────────────────────────────────────────────────


def dataset_from_stores(
    ledger: sqlite3.Connection,
    intel: sqlite3.Connection | None,
    *,
    clock: str = "collected",
    participant_source: str = "intel",
) -> Dataset:
    """Build the in-memory dataset from the underlying-trade ledger and the
    Sharp intel ledger (both ``mode=ro``).  Raw ids stay in this process."""
    from src.trade import market_trade_eval as ev  # noqa: PLC0415

    trades: list[Trade] = []
    tx_keys: list[str | None] = []
    key_states: dict[str, int] = {}
    audit = {"rows": 0, "excludedUnprovenDedupe": 0}
    for (record_json,) in ledger.execute(
        "SELECT record_json FROM underlying_trades ORDER BY underlying_trade_id"
    ):
        g = json.loads(record_json)
        audit["rows"] += 1
        proven = g.get("dedupeState") not in _UNPROVEN_DEDUPE
        audit["excludedUnprovenDedupe"] += int(not proven)
        fit = ev.fit_suitability(g, ev.classify_topology(g))["fit"] != ev.FIT_UNSUITABLE
        est = not ev.estimator_evidence(g)["hardExclusions"]
        side_ev = g.get("sideEvidence") or {}
        state = str(side_ev.get("managerKeyState") or "absent")
        key_states[state] = key_states.get(state, 0) + 1
        keys: tuple[str, ...] = ()
        if participant_source == "side_keys":
            keys = tuple(
                sorted(
                    {
                        str(s["managerKey"])
                        for s in side_ev.get("sides") or []
                        if s.get("managerKey")
                    }
                )
            )
        league = str(g.get("hostLeagueId") or "").strip() or None
        host = str(g.get("host") or "").strip() or "unknown"
        occurred = _parse_day(g.get("occurredDate"))
        # The clock a fit on the group's SIDES uses -- the same order as the
        # estimator gate (``market_trade_eval.estimator_evidence``).
        collected = _parse_day(g.get("representativeCollectedAt") or g.get("collectedAt"))
        lm = g.get("leagueMaturity") or {}
        trades.append(
            Trade(
                lane=trade_lane(g.get("sourceFamilies") or ()),
                # a league id is only linkable within one host's id space
                league=f"{host}:{league}" if league else None,
                day=collected if clock == "collected" else occurred,
                participants=keys,
                sides=len([s for s in g.get("sides") or [] if s is not None]) or 2,
                fit=fit,
                estimator=est,
                occurred=occurred,
                collected=collected,
                lineage_id=lm.get("lineageId") if isinstance(lm.get("lineageId"), str) else None,
                proven=proven,
            )
        )
        tx = str(g.get("hostTxId") or "").strip()
        tx_keys.append(tx or None)
    audit["fitEligible"] = sum(1 for t in trades if t.fit and t.proven)
    audit["estimatorEligible"] = sum(1 for t in trades if t.estimator and t.proven)
    audit["managerKeyStates"] = dict(sorted(key_states.items()))
    predecessor: dict[str, str] = {}
    members: dict[str, set[str]] = {}
    known: set[str] | None = None
    intel_audit: dict[str, Any] = {"available": intel is not None}
    if intel is not None:
        wanted = {k for k in tx_keys if k}
        parts: dict[str, set[str]] = {}
        tx_league: dict[str, str] = {}
        for lg, tx, uid in intel.execute(
            "SELECT league_id, tx_id, user_id FROM asset_movements WHERE tx_type = 'trade'"
        ):
            tx = str(tx)
            if tx in wanted:
                tx_league.setdefault(tx, f"sleeper:{lg}")
                if uid:
                    parts.setdefault(tx, set()).add(str(uid))
        for k, t in zip(tx_keys, trades):
            if not k or k not in tx_league:
                continue
            # Sleeper transaction ids are globally unique, so the intel row
            # names the league even when the group's representative record
            # came from another feed.
            t.league = tx_league[k]
            if participant_source == "intel":
                t.participants = tuple(sorted(parts.get(k, ())))
        known = set()
        for lg, prev in intel.execute("SELECT league_id, previous_league_id FROM leagues"):
            known.add(f"sleeper:{lg}")
            p = str(prev or "").strip()
            if p not in _NO_PREDECESSOR:
                predecessor[f"sleeper:{lg}"] = f"sleeper:{p}"
        ledger_leagues = {t.league for t in trades if t.league}
        for lg, uid in intel.execute("SELECT league_id, user_id FROM league_memberships"):
            key = f"sleeper:{lg}"
            if key in ledger_leagues and uid:
                members.setdefault(key, set()).add(str(uid))
        intel_audit.update(
            {
                "tradesWithHostTxId": len(wanted),
                "tradesFoundInIntel": sum(1 for k in tx_keys if k and k in tx_league),
                "tradesWithParticipants": sum(1 for t in trades if t.participants),
                "ledgerLeaguesWithMembership": len(members),
            }
        )
    return Dataset(
        trades=trades,
        predecessor=predecessor,
        members=members,
        known_leagues=known,
        inputs={
            "ledger": audit,
            "intel": intel_audit,
            "clock": clock,
            "participantSource": participant_source,
        },
    )


def dataset_synthetic(overlap: float, seed: int = 0, n_leagues: int = 160) -> Dataset:
    """A labelled SYNTHETIC rehearsal from the power-study world generator."""
    from src.trade import market_trade_sim as sim  # noqa: PLC0415

    cfg = sim.SimConfig(seed=seed, n_leagues=n_leagues, manager_multi_league_prob=overlap)
    world = sim.generate_world(cfg)
    lg, ts = world.leagues, world.trades
    start = date(2026, 1, 1)
    trades = []
    for k in range(len(ts.league)):
        day = start + timedelta(days=int(ts.date[k]))
        trades.append(
            Trade(
                lane=LANE_SLEEPER,
                league=f"syn:{int(ts.league[k])}",
                day=day,
                participants=(f"m{int(ts.mgr_a[k])}", f"m{int(ts.mgr_b[k])}"),
                fit=True,
                estimator=True,
                occurred=day,
                collected=day,
            )
        )
    members = {f"syn:{i}": {f"m{m}" for m in seats} for i, seats in enumerate(lg.seats)}
    return Dataset(
        trades=trades,
        members=members,
        known_leagues=set(members),
        inputs={"synthetic": {"perSeatOverlap": overlap, "seed": seed, "leagues": n_leagues}},
    )


# ── output safety ───────────────────────────────────────────────────────────

# A 9+ digit run (Sleeper / KTC ids), or any ``word:`` key prefix this script
# builds internally (``sleeper:``, ``unknown:``, ``mk:``, ``utrade:``, ...).
_ID_LIKE = re.compile(r"\d{9,}|[A-Za-z]{2,}:[A-Za-z0-9]|\b[LUNT]:[A-Za-z0-9]")


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


def _guard_block() -> tuple[dict[str, Any], int]:
    denied = GUARD.denied()
    net = [d for d in denied if d["event"].startswith("socket.")]
    fatal = [d for d in denied if not d["event"].startswith("socket.")]
    block = {
        "installed": bool(GUARD.installed()),
        "refusedWriteOrProcessAttempts": len(fatal),
        "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
        "refusedNetworkAttempts": len(net),
    }
    return block, (3 if fatal else 0)


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.box and GUARD is None:
        return {"available": False, "reason": "box_mode_requires_the_read_only_guard"}, 64
    if args.synthetic is not None:
        ds = dataset_synthetic(args.synthetic, seed=args.seed, n_leagues=args.leagues)
        label = "SYNTHETIC rehearsal (power-study generator) -- not evidence about real leagues"
    else:
        try:
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
            if intel is None and args.box:
                ledger.close()
                return {"available": False, "reason": "no_intel_ledger_on_this_host"}, 2
            try:
                try:
                    built = ledger.execute(
                        "SELECT value FROM meta WHERE key = 'builtAt'"
                    ).fetchone()
                except sqlite3.DatabaseError:
                    built = None
                ds = dataset_from_stores(
                    ledger, intel, clock=args.clock, participant_source=args.participants
                )
            finally:
                ledger.close()
                if intel is not None:
                    intel.close()
        except PermissionError:
            # The guard refused something; report the event type only.
            res: dict[str, Any] = {"available": False, "reason": "read_only_guard_refused"}
            if GUARD is not None:
                res["readOnlyGuard"], _ = _guard_block()
            return res, 3
        try:
            ds.inputs["ledgerBuiltAt"] = json.loads(built[0]) if built else None
        except (TypeError, ValueError):
            ds.inputs["ledgerBuiltAt"] = None
        label = "production stores (read-only)" if args.box else "local store copies"
    result = {
        "purpose": (
            "RESEARCH ONLY (owner Package 5A, 2026-10-21). Manager-lineage component census; "
            "no reserve is drawn, persisted or exposed; nothing is activated."
        ),
        "version": CENSUS_VERSION,
        "dataLabel": label,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inputs": ds.inputs,
        **census(ds, replicates=args.replicates),
    }
    code = 0
    if GUARD is not None:
        result["readOnlyGuard"], code = _guard_block()
    assert_aggregate_only(result)
    return result, code


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], allow_abbrev=False)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--box", action="store_true", help="read-only production-store run")
    src.add_argument("--ledger", help="local copy of underlying_trades.sqlite")
    src.add_argument("--synthetic", type=float, metavar="OVERLAP", help="per-seat overlap")
    ap.add_argument("--intel", help="local copy of the intel ledger.sqlite3 (with --ledger)")
    ap.add_argument("--clock", choices=("collected", "occurred"), default="collected")
    ap.add_argument("--participants", choices=("intel", "side_keys"), default="intel")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--leagues", type=int, default=160, help="synthetic leagues (--synthetic)")
    ap.add_argument("--replicates", type=int, default=DEFAULT_REPLICATES)
    args = ap.parse_args(argv)
    result, code = run(args)
    print(json.dumps(result, indent=1, sort_keys=True, default=str))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
