#!/usr/bin/env python3
"""Historical trade grade vs the fairness-band owner -- READ-ONLY measurement (OD-F6 input).

The public ``/league`` timeline and the private ``/trades`` history grade every trade
side with ``src.public_league.trade_grading`` ("Fair trade" below a fixed share of the
larger EFFECTIVE side, no absolute minimum).  The advisor, the War Room market band, the
meter, Best Offers and the suggestions badge classify with the ONE band owner,
``src.valuation_math.fairness_bands`` (``fairness_bands_v2``: relative to the larger
PACKAGE UTILITY, with a 250-point floor).  Owner decision OD-F6 (align or relabel the
history grade) is open.  This script measures how far the two disagree on the SAME
trades, with the history grade CALLED (``trade_grading.grade_trade_sides``) and the band
CALLED (``fairness_bands.classify_packages`` / ``larger_package_utility`` /
``relative_pct``).  No grading code, band, flag, or threshold is changed here, and no band
number appears in this file: every cut point, floor and fair-level rule is read from the
two owners.

Population (be exact about it):

* ``own_league_trades_current_board`` -- the real own-league trades in the tracked
  ``data/sleeper_last_good.json`` (``rosterData.trades``: the rolling trade window of the
  one configured league), each asset priced at ONE pinned CURRENT canonical board built
  from ``--archive`` (+ ``--csv-rev``).  That is the basis of the history ``Current
  grade``; it is NOT the at-the-time grade the public timeline shows (the temporal ledger
  is box-local and not in the repository).  Both classifiers see identical inputs, so the
  comparison of the RULES is apples-to-apples; the distribution of what the public
  timeline displays is not reproduced.  It is also the rolling window, not necessarily
  every trade in the league's history.  An unpriced / ambiguous asset makes the whole
  trade NOT GRADABLE (counted, excluded; never priced as 0).
* ``synthetic_balanced`` (``--synthetic N``) -- deterministic, labelled illustrative
  trades drawn from the same board's values to cover small packages and every gap size.
  Not the league's trades.

Output is aggregate-only (counts, shares, fixed vocabulary, provenance pins): no league /
user / roster / transaction id, no team or manager name, no asset label.  Run::

    nice -n 10 python scripts/history_grade_vs_fairness_bands.py \\
        --archive exports/archive/dynasty_export_20261021_080314.zip \\
        --csv-rev 7dd8cb048 --trades-rev 7dd8cb048 --synthetic 1500 \\
        --out docs/trade/history-vs-public-fairness-alignment/results.json
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import importlib.util
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.public_league import trade_grading as tg  # noqa: E402
from src.valuation_math import fairness_bands as fb  # noqa: E402
from src.valuation_math import package_model as pm  # noqa: E402

SCHEMA = "history_grade_vs_fairness_bands.v1"
DEFAULT_TRADES = "data/sleeper_last_good.json"
SEED = 20261021
#: Reporting cuts for |gap|, in multiples of the band owner's absolute minimum.  Not band
#: thresholds -- a ruler for "how big is the gap" that moves with the owner's floor.
GAP_BIN_MULTIPLES = (1, 2, 5, 10)

# ── history grade, as the module defines it (read, never re-stated) ────────


def history_cut_points() -> list[float]:
    """The history grade's tier cut points, read from the module constants."""
    return [
        float(tg._GRADE_PCT_FAIR),
        float(tg._GRADE_PCT_SLIGHT),
        float(tg._GRADE_PCT_GOOD),
        float(tg._GRADE_PCT_CLEAR),
        float(tg._GRADE_PCT_ROBBERY),
    ]


def history_tier(pct: float) -> int:
    """0 = inside the history 'Fair trade' tier; higher = larger margin tier."""
    return bisect.bisect_right(history_cut_points(), pct)


def hybrid_grade(pct: float, is_winner: bool, owner_fair: bool) -> dict[str, str]:
    """The history grade with ONLY its fair/not-fair decision taken from the band owner.

    Owner ``fair`` -> the history 'Fair trade' grade; owner not-fair but history-fair ->
    the history's lowest not-fair tier; everything above the fair boundary is the history
    grade unchanged.  This is the smallest relabelling that makes the word 'fair' mean the
    same thing (option B/C of the alignment doc); it invents no new cut point.
    """
    if owner_fair:
        return tg.grade_from_pct(0.0, is_winner)
    return tg.grade_from_pct(max(pct, history_cut_points()[0]), is_winner)


# ── gradability ────────────────────────────────────────────────────────────


def is_priced(value: Any) -> bool:
    """A usable asset value is a finite, strictly positive number.  Anything else is
    MISSING (never zero): the history grade would silently drop it from the side."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def gate_trade(sides: list[dict[str, Any]]) -> str | None:
    """Reason a trade is not gradable, else None."""
    if not isinstance(sides, list) or len(sides) < 2:
        return "fewer_than_two_sides"
    for side in sides:
        if not isinstance(side, dict):
            return "malformed_side"
        for key in ("got", "gave"):
            vals = side.get(key)
            if not isinstance(vals, list):
                return "malformed_side"
            if any(not is_priced(v) for v in vals):
                return "unpriced_asset"
    return None


# ── per-side evaluation ────────────────────────────────────────────────────


def side_record(got: list[float], gave: list[float]) -> dict[str, Any]:
    """One side, both classifiers.  ``got`` / ``gave`` are fully priced."""
    (hist,) = tg.grade_trade_sides([(got, gave)])
    # Same quantity every private surface classifies: recvAdjusted - sendAdjusted.
    send_total, recv_total, _, _ = pm.adjusted_pair_totals(gave, got)
    gap = recv_total - send_total
    band = fb.classify_packages(gap, gave, got)
    base_u = fb.larger_package_utility(gave, got)
    rel_v2 = fb.relative_pct(gap, base_u)  # unrounded; None for an empty pairing

    signed_pct = float(hist["pctGap"])
    pct = abs(signed_pct)
    # The history grade's denominator: the larger EFFECTIVE side (linear + the VA on the
    # side that earned it), floored at one point.  Re-derived from the grade's own output.
    va = float(hist["vaNet"])
    scale = max(
        float(hist["gotValue"]) + max(0.0, va), float(hist["gaveValue"]) + max(0.0, -va), 1.0
    )
    fair_cut = history_cut_points()[0]
    hist_fair = pct < fair_cut
    owner_fair = fb.counts_as_fair_trade(band["level"])
    floor = fb.ABSOLUTE_MINIMUM

    # Attribution ladder: history -> (1) owner's relative cut -> (2) + owner's floor ->
    # (3) owner's classification (adds the package-utility denominator).  Steps 1-2 are
    # arithmetic on the owner's constants for the history denominator; step 3 is the owner.
    step_cut = pct < fb.SLIGHT_PCT
    step_floor = step_cut or abs(gap) < floor
    v2_cut_only = rel_v2 is None or rel_v2 < fb.SLIGHT_PCT

    is_winner = signed_pct > 0
    hybrid = hybrid_grade(pct, is_winner, owner_fair)
    return {
        "gap": gap,
        "absGap": abs(gap),
        "pctSigned": signed_pct,
        "pct": pct,
        "histScale": scale,
        "packageUtility": base_u,
        "relV2": rel_v2,
        "histLabel": hist["grade"]["label"],
        "histTier": history_tier(pct),
        "rebasedTier": history_tier(pct if rel_v2 is None else rel_v2),
        "histFair": hist_fair,
        "ownerLevel": band["level"],
        "ownerFair": owner_fair,
        "stepCutFair": step_cut,
        "stepFloorFair": step_floor,
        "floorOnlyFair": owner_fair and not v2_cut_only,
        "hybridLabel": hybrid["label"],
        "gapAgrees": abs(gap - float(hist["netAdjusted"])) < 1e-6,
        "histWin": signed_pct >= fair_cut,
        "histLoss": signed_pct <= -fair_cut,
        "ownerWin": (not owner_fair) and gap > 0,
        "ownerLoss": (not owner_fair) and gap < 0,
        "nGot": len(got),
        "nGave": len(gave),
    }


# ── aggregation ────────────────────────────────────────────────────────────


def _share(n: int, d: int) -> float | None:
    return None if d == 0 else round(n / d, 4)


def _quantiles(xs: list[float]) -> dict[str, float] | None:
    if not xs:
        return None
    s = sorted(xs)

    def q(p: float) -> float:
        return round(s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))], 4)

    return {"p10": q(0.10), "median": q(0.50), "p90": q(0.90)}


def tally(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Side-level agreement counts for one group of side records."""
    n = len(recs)
    out: dict[str, Any] = {"sides": n}
    if n == 0:
        return out
    hf = sum(r["histFair"] for r in recs)
    of = sum(r["ownerFair"] for r in recs)
    stricter = sum(r["histFair"] and not r["ownerFair"] for r in recs)
    looser = sum((not r["histFair"]) and r["ownerFair"] for r in recs)
    changed = [r for r in recs if r["hybridLabel"] != r["histLabel"]]
    out.update(
        {
            "historyFair": hf,
            "ownerFair": of,
            "fairClassificationDiffers": stricter + looser,
            "shareFairClassificationDiffers": _share(stricter + looser, n),
            "historyFairOwnerNotFair": stricter,
            "historyNotFairOwnerFair": looser,
            "gradeBucketChangesIfOnlyFairIsOwners": len(changed),
            "shareGradeBucketChanges": _share(len(changed), n),
            "gradeBucketChangeDirection": {
                "fairToNotFair": sum(r["histFair"] and not r["ownerFair"] for r in changed),
                "notFairToFair": sum((not r["histFair"]) and r["ownerFair"] for r in changed),
            },
        }
    )
    return out


def decomposition(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Which rule difference flips which sides (sequential attribution, fair <-> not fair)."""

    def step(a: str, b: str) -> dict[str, int]:
        return {
            "notFairToFair": sum((not r[a]) and r[b] for r in recs),
            "fairToNotFair": sum(r[a] and not r[b] for r in recs),
        }

    return {
        "1_relativeCutChange": step("histFair", "stepCutFair"),
        "2_absoluteFloorAdded": step("stepCutFair", "stepFloorFair"),
        "3_packageUtilityDenominator": step("stepFloorFair", "ownerFair"),
        "netHistoryToOwner": step("histFair", "ownerFair"),
    }


def tier_matrix(recs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Counts of history margin tier (rows) by owner level (columns).  No crosswalk is
    assumed between the two vocabularies -- the matrix is the evidence."""
    m: dict[str, Counter] = defaultdict(Counter)
    for r in recs:
        m[f"tier{r['histTier']}"][r["ownerLevel"]] += 1
    return {k: dict(v) for k, v in sorted(m.items())}


def winners_losers(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """The Winners & Losers W/L rule under each definition (per side, no team identity)."""

    def status(r: dict[str, Any], w: str, lo: str) -> str:
        return "win" if r[w] else "loss" if r[lo] else "none"

    trans: Counter = Counter()
    for r in recs:
        trans[f"{status(r, 'histWin', 'histLoss')}>{status(r, 'ownerWin', 'ownerLoss')}"] += 1
    return {
        "historyWins": sum(r["histWin"] for r in recs),
        "historyLosses": sum(r["histLoss"] for r in recs),
        "ownerWins": sum(r["ownerWin"] for r in recs),
        "ownerLosses": sum(r["ownerLoss"] for r in recs),
        "historyStatusToOwnerStatus": dict(sorted(trans.items())),
        "sidesWithChangedStatus": sum(
            status(r, "histWin", "histLoss") != status(r, "ownerWin", "ownerLoss") for r in recs
        ),
    }


def rebased_tiers(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """If the history margin were the owner's relative gap (larger package utility, no
    floor) with the history's own cut points: how many margin tiers would move?  (The
    denominator effect alone, on every tier -- the broadest relabelling.)"""
    n = len(recs)
    up = sum(r["rebasedTier"] > r["histTier"] for r in recs)
    down = sum(r["rebasedTier"] < r["histTier"] for r in recs)
    return {
        "sides": n,
        "tierMovesMoreSevere": up,
        "tierMovesLessSevere": down,
        "shareTierMoves": _share(up + down, n),
    }


def fair_boundary(recs: list[dict[str, Any]]) -> dict[str, Any]:
    """Is "fair" monotone in the history grade's own margin (|pct|)?  With the owner's
    floor and denominator it is not, by design; this puts a number on it."""
    fair = [r["pct"] for r in recs if r["ownerFair"]]
    unfair = [r["pct"] for r in recs if not r["ownerFair"]]
    top = max(fair) if fair else None
    return {
        "ownerFairMaxPct": None if top is None else round(top, 3),
        "ownerNotFairMinPct": round(min(unfair), 3) if unfair else None,
        "ownerNotFairSidesBelowOwnerFairMax": (0 if top is None else sum(p < top for p in unfair)),
        "ownerFairSidesAtOrAboveHistoryCut": sum(
            r["ownerFair"] and not r["histFair"] for r in recs
        ),
        "ownerNotFairSidesBelowHistoryCut": sum(
            (not r["ownerFair"]) and r["histFair"] for r in recs
        ),
    }


def gap_bin(abs_gap: float) -> str:
    """Where |gap| sits against the band owner's floor (a ruler, not a threshold)."""
    floor = fb.ABSOLUTE_MINIMUM
    lows = (0, *GAP_BIN_MULTIPLES)
    for lo, hi in zip(lows, lows[1:]):
        if abs_gap < hi * floor:
            return f"below_{hi}x_floor" if lo == 0 else f"{lo}x_to_{hi}x_floor"
    return f"{GAP_BIN_MULTIPLES[-1]}x_or_more_floor"


def shape_of(sides: list[dict[str, Any]]) -> str:
    if len(sides) > 2:
        return "multi_team"
    counts = sorted((len(sides[0]["got"]), len(sides[0]["gave"])))
    return {(1, 1): "1v1", (1, 2): "2v1", (2, 2): "2v2"}.get(tuple(counts), "larger_two_team")


def evaluate(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate report over PRICED trades (``{"sides": [{"got": [...], "gave": [...]}],
    "hasPick": bool}``).  Trades that fail :func:`gate_trade` are counted and excluded."""
    census: Counter = Counter()
    recs: list[dict[str, Any]] = []
    by_shape: dict[str, list] = defaultdict(list)
    by_pick: dict[str, list] = defaultdict(list)
    by_bin: dict[str, list] = defaultdict(list)
    trade_rows: list[dict[str, Any]] = []
    asym = 0
    for t in trades:
        census["trades"] += 1
        reason = gate_trade(t.get("sides"))
        if reason:
            census["notGradable"] += 1
            census[f"notGradable_{reason}"] += 1
            continue
        census["gradable"] += 1
        sides = t["sides"]
        srecs = [side_record(list(s["got"]), list(s["gave"])) for s in sides]
        shape = shape_of(sides)
        pick = "includes_pick" if t.get("hasPick") else "no_pick"
        if len(sides) == 2 and (
            srecs[0]["histFair"] != srecs[1]["histFair"]
            or srecs[0]["ownerLevel"] != srecs[1]["ownerLevel"]
        ):
            asym += 1
        for r in srecs:
            recs.append(r)
            by_shape[shape].append(r)
            by_pick[pick].append(r)
            by_bin[gap_bin(r["absGap"])].append(r)
        trade_rows.append(
            {
                "histFair": all(r["histFair"] for r in srecs),
                "ownerFair": all(r["ownerFair"] for r in srecs),
                "shape": shape,
                "hasPick": bool(t.get("hasPick")),
            }
        )
    nt = len(trade_rows)
    t_strict = sum(r["histFair"] and not r["ownerFair"] for r in trade_rows)
    t_loose = sum((not r["histFair"]) and r["ownerFair"] for r in trade_rows)
    below_floor = [r for r in recs if r["absGap"] < fb.ABSOLUTE_MINIMUM]
    ratios = [r["relV2"] / r["pct"] for r in recs if r["relV2"] is not None and r["pct"] > 0]
    return {
        "census": dict(census),
        "twoTeamAsymmetries": asym,
        "gapAgreementFailures": sum(not r["gapAgrees"] for r in recs),
        "sideLevel": {
            **tally(recs),
            "decomposition": decomposition(recs),
            "fairBoundary": fair_boundary(recs),
            "rebasedMarginTiers": rebased_tiers(recs),
            "historyTierByOwnerLevel": tier_matrix(recs),
            "ownerLevelCounts": dict(Counter(r["ownerLevel"] for r in recs)),
            "historyLabelCounts": dict(Counter(r["histLabel"] for r in recs)),
            "hybridLabelCounts": dict(Counter(r["hybridLabel"] for r in recs)),
            "winnersLosers": winners_losers(recs),
        },
        "tradeLevel": {
            "trades": nt,
            "historyFair": sum(r["histFair"] for r in trade_rows),
            "ownerFair": sum(r["ownerFair"] for r in trade_rows),
            "fairClassificationDiffers": t_strict + t_loose,
            "shareFairClassificationDiffers": _share(t_strict + t_loose, nt),
            "historyFairOwnerNotFair": t_strict,
            "historyNotFairOwnerFair": t_loose,
        },
        "byShape": {k: tally(v) for k, v in sorted(by_shape.items())},
        "byPicks": {k: tally(v) for k, v in sorted(by_pick.items())},
        "byAbsGap": {k: tally(v) for k, v in sorted(by_bin.items())},
        "absoluteFloor": {
            "sidesBelowFloor": len(below_floor),
            "shareBelowFloor": _share(len(below_floor), len(recs)),
            "belowFloorButHistoryNotFair": sum(not r["histFair"] for r in below_floor),
            "ownerFairOnlyBecauseOfFloor": sum(r["floorOnlyFair"] for r in recs),
            "ownerFairOnlyBecauseOfFloorShare": _share(
                sum(r["floorOnlyFair"] for r in recs), len(recs)
            ),
        },
        "ownerRelativePctOverHistoryPct": _quantiles(ratios),
        "packageUtilityOverHistoryScale": _quantiles(
            [r["packageUtility"] / r["histScale"] for r in recs if r["histScale"] > 0]
        ),
    }


# ── populations ────────────────────────────────────────────────────────────


def price_trades(
    raw_trades: Iterable[dict[str, Any]],
    price: Callable[[str], tuple[float | None, str | None]],
    asset_census: Counter | None = None,
) -> list[dict[str, Any]]:
    """Resolve each trade's asset labels through ``price`` (``label -> (value|None, class)``).
    Labels are read here and never copied into any result; ``asset_census`` (optional)
    receives asset COUNTS by outcome and class only."""
    out: list[dict[str, Any]] = []
    for t in raw_trades:
        sides_in = t.get("sides") if isinstance(t, dict) else None
        if not isinstance(sides_in, list):
            out.append({"sides": None})
            continue
        has_pick = False
        sides = []
        for s in sides_in:
            got, gave = [], []
            for key, dest in (("got", got), ("gave", gave)):
                for label in s.get(key) or []:
                    value, cls = price(str(label))
                    has_pick |= cls == "pick"
                    if asset_census is not None:
                        asset_census["assets"] += 1
                        if not is_priced(value):
                            asset_census["unpriced"] += 1
                            asset_census[f"unpriced_class_{cls or 'unknown'}"] += 1
                    dest.append(value)
            sides.append({"got": got, "gave": gave})
        out.append({"sides": sides, "hasPick": has_pick})
    return out


def synthetic_trades(pool: list[float], n: int, seed: int = SEED) -> list[dict[str, Any]]:
    """Deterministic, balanced-by-construction trades from board values.

    Shape drawn uniformly; the last received piece is the pool value that lands the
    relative package gap closest to a target drawn uniformly in [0, 0.20] of the larger
    adjusted side, so every band edge is exercised.  Illustrative: it is NOT the league's
    trades and says nothing about how often such trades occur."""
    rng = random.Random(seed)
    values = sorted({float(v) for v in pool if is_priced(v)}, reverse=True)
    if len(values) < 2:
        return []
    shapes = ((1, 1), (2, 1), (2, 2), (3, 2), (3, 3))
    out = []
    for _ in range(n):
        ng, nr = rng.choice(shapes)
        gave = [rng.choice(values) for _ in range(ng)]
        got = [rng.choice(values) for _ in range(nr - 1)]
        target = rng.uniform(0.0, 0.20)
        best, best_err = values[0], math.inf
        for cand in values:
            send_t, recv_t, _, _ = pm.adjusted_pair_totals(gave, got + [cand])
            larger = max(send_t, recv_t)
            err = abs(abs(recv_t - send_t) / larger - target) if larger > 0 else math.inf
            if err < best_err:
                best, best_err = cand, err
        got.append(best)
        out.append(
            {
                "sides": [{"got": got, "gave": gave}, {"got": list(gave), "gave": list(got)}],
                "hasPick": False,
            }
        )
    return out


# ── aggregate-only guard ───────────────────────────────────────────────────

_KEY_OK = re.compile(r"^[A-Za-z0-9 _.>+:<=/-]{1,80}$")
_PROVENANCE_VALUE_OK = re.compile(r"^[A-Za-z0-9_./:+-]{1,200}$")
#: Keys whose string values are provenance pins (paths, shas, timestamps), not data.
PROVENANCE_KEYS = frozenset(
    {
        "path",
        "rev",
        "blob",
        "revisionSha",
        "contentSha256",
        "revisionCommittedAt",
        "source",
        "archive",
        "archiveMember",
        "archiveMemberSha256",
        "builtBoardSha256",
        "id",
        "version",
        "status",
        "basis",
        "schema",
        "name",
        "model",
        "family",
        "activeModelId",
        "classification",
        "module",
        "postLaunchValidation",
    }
)


def _vocabulary() -> set[str]:
    words: set[str] = set(fb.LEVELS) | set(fb.LABELS.values()) | set(fb.FAIR_TRADE_LEVELS)
    for pct in (0.0, *history_cut_points(), 10_000.0):
        for winner in (True, False):
            words.add(tg.grade_from_pct(pct, winner)["label"])
    return words


def assert_aggregate_only(obj: Any, extra_vocab: Iterable[str] = (), path: str = "$") -> None:
    """Refuse any output that could carry an identity: dict keys must be short fixed
    tokens; a string VALUE is allowed only as a provenance pin under a known key or as a
    word of the fixed vocabulary (band levels / labels, history grade labels, the
    script's own fixed notes)."""
    vocab = _vocabulary() | set(extra_vocab)

    def walk(node: Any, p: str, key: str | None) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if not isinstance(k, str) or not _KEY_OK.match(k):
                    raise ValueError(f"non-token key at {p}")
                walk(v, f"{p}.{k}", k)
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{p}[{i}]", key)
        elif isinstance(node, str):
            if node in vocab:
                return
            if key in PROVENANCE_KEYS and _PROVENANCE_VALUE_OK.match(node):
                return
            raise ValueError(f"free-text string at {p}")
        elif node is None or isinstance(node, (bool, int, float)):
            return
        else:
            raise ValueError(f"unsupported value at {p}")

    walk(obj, path, None)


# ── inputs / provenance ────────────────────────────────────────────────────


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], check=True, capture_output=True).stdout


def _load_module(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def read_trades(rev: str | None, path: str = DEFAULT_TRADES) -> tuple[list[dict], dict[str, Any]]:
    """The tracked own-league trade list, optionally pinned to a git revision."""
    if rev:
        raw = _git("show", f"{rev}:{path}")
        blob = _git("rev-parse", f"{rev}:{path}").decode().strip()
    else:
        raw = (REPO / path).read_bytes()
        blob = hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()  # noqa: S324 (git blob id)
    doc = json.loads(raw)
    trades = (doc.get("rosterData") or {}).get("trades") or []
    return trades, {"path": path, "rev": rev or "working_tree", "blob": blob}


def build_board_price(
    archive: str, csv_rev: str | None
) -> tuple[Callable[[str], tuple[float | None, str | None]], list[float], dict[str, Any]]:
    """Pinned current board -> ``price(label)``, the pool of board values, provenance."""
    rpb = _load_module("research_pinned_board")
    mfb = _load_module("measure_fairness_band_change")
    from src.api import data_contract as dc  # noqa: PLC0415

    zpath, member, blob, raw = rpb.load_archive(archive)
    with rpb.csv_tree(csv_rev) as (csv_root, csv_prov):
        with rpb.pinned_contract_builds(csv_root):
            contract = dc.build_api_data_contract(raw)
    price, by_class = mfb._board(contract)
    pool = [v for vals in by_class.values() for _, v in vals]
    rows = sorted(
        (str(r.get("displayName")), r.get("rankDerivedValue"))
        for r in contract["playersArray"]
        if is_priced(r.get("rankDerivedValue"))
    )
    prov = {
        "archive": zpath.name,
        "archiveMember": member,
        "archiveMemberSha256": hashlib.sha256(blob).hexdigest(),
        "csvTree": {
            **{k: v for k, v in csv_prov.items() if k != "source"},
            "source": "git_revision" if csv_rev else "working_tree",
        },
        "builtBoardSha256": hashlib.sha256(
            json.dumps(rows, separators=(",", ":")).encode()
        ).hexdigest(),
    }
    return price, pool, prov


# ── main ───────────────────────────────────────────────────────────────────

NOTES = {
    "valueBasis": (
        "Both classifiers read identical CURRENT-board values; the at-the-time grade shown on "
        "the public timeline is not reproduced (temporal ledger is box-local)."
    ),
    "population": (
        "Rolling-window own-league trades from the tracked trade file, not necessarily the "
        "whole league history."
    ),
    "synthetic": "Illustrative balanced-by-construction trades; not the league's trades.",
    "denominator": (
        "History grade divides by the larger effective (adjusted) side; the band owner divides "
        "by the larger package utility."
    ),
}


def build_report(populations: dict[str, dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    report = {
        "schema": SCHEMA,
        "readOnly": True,
        "meta": meta,
        "notes": NOTES,
        "populations": populations,
    }
    assert_aggregate_only(report, extra_vocab=NOTES.values())
    return report


def common_meta() -> dict[str, Any]:
    return {
        "historyGrade": {
            "module": "src/public_league/trade_grading.py",
            "cutPoints": history_cut_points(),
        },
        "bandOwner": fb.receipt(),
        "packageModel": {
            k: v
            for k, v in pm.receipt().items()
            if k in ("id", "family", "version", "classification")
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--archive", required=True, help="dynasty_export_*.zip that pins the board")
    ap.add_argument("--csv-rev", default=None, help="git rev for the CSV/config tree of the build")
    ap.add_argument("--trades-rev", default=None, help="git rev for data/sleeper_last_good.json")
    ap.add_argument("--synthetic", type=int, default=0, help="also run N synthetic trades")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    price, pool, board_prov = build_board_price(args.archive, args.csv_rev)
    asset_census: Counter = Counter()
    raw_trades, trades_pin = read_trades(args.trades_rev)
    populations: dict[str, dict[str, Any]] = {
        "own_league_trades_current_board": {
            "description": NOTES["population"],
            "valueBasis": NOTES["valueBasis"],
            "inputs": {"trades": trades_pin, "board": board_prov},
            "assetCensus": None,
            **evaluate(price_trades(raw_trades, price, asset_census)),
        }
    }
    populations["own_league_trades_current_board"]["assetCensus"] = dict(asset_census)
    if args.synthetic > 0:
        populations["synthetic_balanced"] = {
            "description": NOTES["synthetic"],
            "inputs": {"seed": SEED, "count": args.synthetic},
            **evaluate(synthetic_trades(sorted(pool, reverse=True)[:450], args.synthetic)),
        }
    report = build_report(populations, common_meta())
    text = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if args.out:
        out = REPO / args.out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"written {out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
