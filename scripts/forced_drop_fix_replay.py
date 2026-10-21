#!/usr/bin/env python3
"""Forced-drop fix — real-roster replay, flag OFF vs ON.  EVIDENCE ONLY.

Owner decision 2026-10-20 §2 (``docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md``).
The candidate is ``src/trade/forced_drop_selection.py`` behind flag
``forced_drop_cheapest_legal`` (default OFF).  This script measures, on the
board archive pinned by ``--archive`` (default: the research board
``low_value_asset_forced_drop_diagnostic.ARCHIVE_DEFAULT`` — NOT the newest
archive, so a re-measurement on a later tree compares like with like) and the
``dynasty_main`` rosters it carries, what turning the flag ON would change.  The
fairness-band version in force is read from the band owner
(``src/valuation_math/fairness_bands.receipt()``) and stamped in the evidence.  The flag is toggled IN-PROCESS only
(env var + ``feature_flags.reload()``, always restored); nothing is written but
the evidence JSON.

Sections:

1. **War Room filler-flip design** — the research diagnostic's 45-trade design
   (``scripts/low_value_asset_forced_drop_diagnostic.py``, same archive, seed and
   sampling loop): reproduce 133 / 85 / 43 / 5 with the flag OFF, the shadow
   variants V1-V4 plus V5 (the implemented rule, recomputed in-script) and V6
   (charge surplus over replacement), and the MEASURED flag-ON outcome through
   the production path.
2. **Analyze verdicts** — for every step of (1) with Team Context ON: the
   ``/api/trade/analyze`` headline and the private 5-level category
   (``team_verdicts.team_category``, formerly ``trade_decision.
   public_category_from_decision`` — same table, moved by the N-team advisor
   work) flag OFF vs ON.
3. **Census** — every ``dynasty_main`` team x a seeded set of real 1-for-2,
   2-for-1 and 1-for-3 trades from its rivals' rosters: ``/api/trade/simulate``
   rosterCapacity (drop set, charge), analyze headline and public category,
   OFF vs ON.
4. **Trade Finder** — Team Context ON with each team's capacity context:
   top-K overlap and forced-drop factor changes, OFF vs ON.
5. **Perfect Draft** — ``/api/draft/roster-context`` payload per team, OFF vs ON
   (must be identical).
6. **Illustrations** — trades whose verdict changes, with NFL player names only.

Both selection MODES of the flag are measured through production
(``forced_drop_selection.SELECTION_MODE``, toggled in-process and restored):
``package_consistent`` (V5) and ``roster_rational`` (V5-R, the default since
the owner's 2026-10-21 decision).  Every flag-ON section sets its mode
explicitly, so the constant changes only ``defaultSelectionMode``.  Each flag-ON section reports V5 under its historical
keys and V5-R under a ``rosterRational`` sibling, plus the "currency anomaly"
census in both directions: forward (an acquired piece released while a cheaper
existing player that could legally have been released instead is kept) and
reverse (an existing player released while a cheaper acquired piece that could
legally have been released instead is kept).  V5-R is 0 in both by construction
(its cut set minimises ``sum c``).  Locally scarcity is inert (1.0), so a
package credit never exceeds ``c`` and V5's reverse count is 0 here too; the box
replay with real scarcity must report both directions.

Output: ``docs/trade/evidence/forced_drop_fix_2026-10-20/replay.json`` —
aggregates and NFL player names only (no league / user / roster / team ids, no
team or manager names; checked with ``assert_aggregate_only``).

``--box`` — the READ-ONLY production-box mode (prepared, owner-run only; record
``docs/trade/FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md``).  Same pattern as
``package_model_phase3_research.py --box``: the audit-hook guard
(``research_readonly_guard.py``) is installed BEFORE any application import, so
the process cannot write outside its private scratch directory, open a network
connection, start a subprocess or open SQLite read-write; resource caps (nice,
address space, CPU, wall clock) are applied; the board is PINNED (archive sha256,
CSV-tree sha256, code SHA, built-board sha256 — a mismatch stops the run before
anything is measured); the report goes to STDOUT only and is refused unless it is
aggregate-only (``forced_drop_box_support.assert_box_output_safe``, which also
rejects any replayed league's ids, team and owner names).  Beyond the local
replay it measures real scarcity (the observed multiplier spread, no longer
inert), Component B / posture where the box has them (a second, B-voting
verdict census beside the A-driven stand-in), and reports the forward AND
reverse currency anomalies.  ``--box-selftest`` runs the guard's refusals only
(no application import) and exits.  Exit codes: 0 ok, 2 pin mismatch, 3 guard
refusal, 4 output refused, 5 resource cap.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import functools
import hashlib
import importlib.util
import io
import itertools
import json
import os
import random
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BOX = "--box" in sys.argv
REPO = Path(
    (os.environ.get("RISKIT_APP_DIR") if BOX else None) or Path(__file__).resolve().parents[1]
).resolve()
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/trade/evidence/forced_drop_fix_2026-10-20/replay.json"

# ── --box: the read-only guard goes in BEFORE any application import ────────
# numpy (third party, no application code) is imported first because CPython's
# ctypes import performs a dlopen the guard refuses; no bytecode is written.
GUARD = None
if BOX:
    sys.dont_write_bytecode = True
    try:
        import numpy  # noqa: F401
    except ImportError:  # pragma: no cover
        pass
    _gspec = importlib.util.spec_from_file_location(
        "research_readonly_guard", SCRIPT_DIR / "research_readonly_guard.py"
    )
    GUARD = importlib.util.module_from_spec(_gspec)
    sys.modules["research_readonly_guard"] = GUARD
    _gspec.loader.exec_module(GUARD)
    GUARD.install()
    if "--box-selftest" in sys.argv:
        # The guard's refusals, exercised in THIS process exactly as installed
        # for a real run, with no application code imported.  Prints JSON.
        def _attempt(fn):
            try:
                fn()
                return "allowed"
            except PermissionError:
                return "refused"
            except OSError as exc:  # allowed by the guard, failed for another reason
                return f"allowed:{type(exc).__name__}"

        def _write_outside():
            with open(os.path.join(os.path.dirname(GUARD._STATE["scratch"]), ".fdr_selftest"), "w"):
                pass

        def _write_scratch():
            with open(os.path.join(GUARD._STATE["scratch"], "ok.txt"), "w") as fh:
                fh.write("x")

        def _connect():
            import socket

            socket.create_connection(("127.0.0.1", 9), timeout=1)

        def _subprocess():
            import subprocess

            subprocess.run(["true"], check=False)

        def _sqlite_rw():
            import sqlite3

            sqlite3.connect(os.path.join(GUARD._STATE["scratch"], "x.db")).close()

        def _mkdir_outside():
            os.mkdir(os.path.join(os.path.dirname(GUARD._STATE["scratch"]), ".fdr_selftest_dir"))

        report = {
            "guardInstalled": GUARD.installed(),
            "writeOutsideScratch": _attempt(_write_outside),
            "writeInsideScratch": _attempt(_write_scratch),
            "mkdirOutsideScratch": _attempt(_mkdir_outside),
            "networkConnect": _attempt(_connect),
            "subprocess": _attempt(_subprocess),
            "sqliteReadWrite": _attempt(_sqlite_rw),
            "refusedEvents": sorted({d["event"] for d in GUARD.denied()}),
        }
        print(json.dumps(report))
        sys.exit(0)

sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


D = _load("low_value_asset_forced_drop_diagnostic")
S = D.S
SUP = _load("forced_drop_box_support")


def _code_sha() -> str:
    """The commit of the code under test.  ``--box`` reads ``.git`` files (the
    guard forbids starting ``git``); the local run asks git."""
    return S.P2._deployed_sha(REPO) if BOX else S.P1._git_sha()


from src.api import feature_flags  # noqa: E402
from src.trade import analyze_service as AS  # noqa: E402
from src.trade import analyze_trade as AT  # noqa: E402
from src.trade import roster_capacity as RC  # noqa: E402
from src.trade import trade_decision as TD  # noqa: E402
from src.trade import forced_drop_selection as FDS  # noqa: E402
from src.trade import team_verdicts as TV  # noqa: E402
from src.valuation_math import package_model as pm  # noqa: E402
from src.valuation_math import fairness_bands as FB  # noqa: E402

LEAGUE = D.LEAGUE
ENV = "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL"


# ── the board pin ─────────────────────────────────────────────────────────

#: What ``build_api_data_contract(csv_root=...)`` reads from a repository tree
#: besides the archive: the source CSVs, the per-source fetch stamps and the
#: coverage-floor configs.  The archive alone does NOT pin the board — the
#: 2-hourly source refreshes on ``main`` move these paths.
CSV_TREE_PATHS = ("CSVs", "data/scrape_state", "config/weights")


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _tree_content_sha256(root: Path) -> str:
    """sha256 over (relative path, bytes) of every file under ``CSV_TREE_PATHS``."""
    h = hashlib.sha256()
    for top in CSV_TREE_PATHS:
        base = root / top
        if not base.exists():
            continue
        for p in sorted(x for x in base.rglob("*") if x.is_file()):
            h.update(p.relative_to(root).as_posix().encode() + b"\0")
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


@contextlib.contextmanager
def csv_tree(rev: str | None):
    """Yield ``(csv_root, provenance)``.  ``rev`` None = the working tree
    (``csv_root`` None, the contract build's own default); otherwise
    ``CSV_TREE_PATHS`` at that git revision, materialised into a temporary
    directory that is deleted on exit."""
    if rev is None:
        yield None, {"source": "working tree", "contentSha256": _tree_content_sha256(REPO)}
        return
    full = _git("rev-parse", "--verify", f"{rev}^{{commit}}")
    tar = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", full, *CSV_TREE_PATHS],
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="fdr-csv-tree-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            tf.extractall(tmp, filter="data")
        root = Path(tmp)
        yield (
            root,
            {
                "source": "git revision",
                "revisionSha": full,
                "revisionCommittedAt": _git("log", "-1", "--format=%cI", full),
                "contentSha256": _tree_content_sha256(root),
            },
        )


def build_context_pinned(raw: dict, csv_root: Path | None) -> dict:
    """``S.build_context`` with the contract built against ``csv_root``
    (``build_context`` imports ``build_api_data_contract`` inside the call, so
    the module attribute is bound for the build and restored after)."""
    if csv_root is None:
        return S.build_context(raw)
    from src.api import data_contract as dc  # noqa: PLC0415

    original = dc.build_api_data_contract
    dc.build_api_data_contract = functools.partial(original, csv_root=csv_root)
    try:
        return S.build_context(raw)
    finally:
        dc.build_api_data_contract = original


def built_board_sha256(rows: dict) -> str:
    """Hash of the built board (name -> canonical value)."""
    blob = json.dumps(sorted((n, r["value"]) for n, r in rows.items()), separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


@contextlib.contextmanager
def flag(on: bool):
    prev = os.environ.get(ENV)
    os.environ[ENV] = "1" if on else "0"
    feature_flags.reload()
    try:
        assert FDS.enabled() is on
        yield
    finally:
        if prev is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = prev
        feature_flags.reload()


@contextlib.contextmanager
def mode(m: str):
    prev = FDS.SELECTION_MODE
    FDS.SELECTION_MODE = m
    try:
        yield
    finally:
        FDS.SELECTION_MODE = prev


#: suffix of the per-step keys -> selection mode ("" keeps the V5 key names).
MODES = {"": FDS.MODE_PACKAGE_CONSISTENT, "R": FDS.MODE_ROSTER_RATIONAL}


def _sgn(x):
    return (x > 0) - (x < 0)


def _r(x, n=0):
    return None if x is None else (round(x, n) if n else round(x))


def sim(ctx, me, pin, pout, tc, *, analysis=True):
    return AS.simulate_for_team(
        ctx["contract"],
        league_key=LEAGUE,
        roster_settings=ctx["roster_settings"],
        resolved_team=me,
        players_in=pin,
        players_out=pout,
        team_context=tc,
        for_analysis=analysis,
    )


#: LABELLED local stand-in.  Locally the roster-utility lens (Component B) has
#: no projection snapshot, so every packet stops at the evidence gate
#: (``roster_unknown: projection_basis_no_projection_snapshot``) and the
#: headline is NOT_ENOUGH_EVIDENCE whatever the forced drop is.  The replay
#: therefore also decides each trade with the utility block in the state the
#: decision owner itself treats as NOT APPLICABLE (``no_remaining_fantasy_weeks``,
#: ``trade_decision._ROSTER_NOT_APPLICABLE`` — the off-season shape), so the
#: production ``decide()`` runs on Component A + feasibility + posture.  On the
#: box Component B also votes; this measures the A-driven headline only.
B_NOT_APPLICABLE = {"available": False, "unavailableReason": "no_remaining_fantasy_weeks"}


def packet_of(ctx, s, *, b_stand_in: bool = True):
    s2 = copy.deepcopy(s)
    if b_stand_in:
        s2["rosterUtility"] = dict(B_NOT_APPLICABLE)
    return AS.analyze_for_team(s2, contract=ctx["contract"], counterfactuals=False)


def verdict(packet, s) -> dict:
    """The served decision (headline, public category, the evidence gaps that
    gated it) plus Component A computed from the same lenses — published even
    when the evidence gate withholds the headline."""
    dec = packet.get("decision") or {}
    a = comp_a(s, True) or {}
    return {
        "headline": dec.get("headline"),
        "category": TV.team_category(dec),
        "missingEvidence": sorted(m.get("code") for m in dec.get("missingEvidence") or []),
        "netGap": a.get("netGap"),
        "charge": a.get("forcedReleaseCost") or 0,
        "aDirection": a.get("direction"),
        "aMagnitude": a.get("magnitude"),
        # The fairness-band base (larger package utility), so a charge
        # difference can be read as a share of what classifies the trade.
        "base": a.get("largerPackageUtility"),
    }


def comp_a(s, tc):
    market = AT._market_lens(s)
    if not market.available:
        return None
    feas = (
        AT._feasibility_lens(s)
        if tc
        else AT._excluded_by_mode("feasibility", AT.LINEAGE_ROSTER_RULES)
    )
    return TD._objective_value(market, feas)


def ordinal(a):
    if a is None:
        return None
    return _sgn(a["netGap"]) * D.LEVEL_RANK[a["band"]["level"]]


def drops_of(s):
    rc = s.get("rosterCapacity") or {}
    return [
        (
            d.get("name"),
            d.get("position"),
            d.get("value"),
            d.get("releaseCost"),
            d.get("acquiredInTrade"),
        )
        for d in rc.get("forcedDrops") or []
    ]


def _fmt_drop(d) -> str:
    name, pos, value, release, acquired = d
    v = "unpriced" if value is None else f"{value:.0f}"
    return (
        f"{name} ({pos or '?'}, {v}{', just acquired' if acquired else ''}; charged {release:.0f})"
    )


def _match_pool(pool, drops) -> list[int] | None:
    """Pool indices of the served drops (by name and acquired flag)."""
    taken: list[int] = []
    for name, _pos, _v, _rel, acquired in drops:
        hit = next(
            (
                i
                for i, p in enumerate(pool)
                if i not in taken and p["name"] == name and bool(p["acquired"]) == bool(acquired)
            ),
            None,
        )
        if hit is None:
            return None
        taken.append(hit)
    return taken


def currency_anomaly(pool, legal, drops) -> dict | None:
    """``None`` when nothing is released.  Otherwise both directions of the
    "currency anomaly" (``c = base x scarcity``), each by a single lineup-legal
    swap:

    * **forward** (``anomaly``): an acquired cut ``a`` and a KEPT existing
      player ``e`` with ``c(e) < c(a)`` such that releasing ``e`` instead of
      ``a`` is legal — the roster keeps a less valuable player and lets a more
      valuable incoming one go.  ``None`` when no acquired piece is released.
    * **reverse** (``reverse``): an existing cut ``e`` and a KEPT acquired
      piece ``a`` with ``c(a) < c(e)`` such that releasing ``a`` instead of
      ``e`` is legal — a dearer existing player released while a cheaper
      incoming one is kept.  Possible under V5 when a piece's package credit
      exceeds its ``c`` (scarcity < 1 shrinks ``c`` but not the credit).
      ``None`` when no existing player is released or no acquired one kept.

    V5-R's cut set is the minimum-``sum c`` legal set, so a single legal swap
    can never lower ``sum c``: both counts are 0 for it BY CONSTRUCTION."""
    if not drops:
        return None
    idx = _match_pool(pool, drops)
    if idx is None:
        return {"anomaly": None, "reverse": None, "reason": "drops_not_matched"}
    S = set(idx)
    out: dict = {"anomaly": None, "reverse": None}
    acq_cut = [i for i in idx if pool[i]["acquired"]]
    if acq_cut:
        out["anomaly"] = False
        for a in sorted(acq_cut, key=lambda i: -pool[i]["release"]):
            for e in sorted(range(len(pool)), key=lambda i: pool[i]["release"]):
                if e in S or pool[e]["acquired"] or pool[e]["release"] >= pool[a]["release"]:
                    continue
                if legal.ok(frozenset((S - {a}) | {e})):
                    out.update(
                        anomaly=True,
                        released=f"{pool[a]['name']} ({pool[a]['pos']}, {pool[a]['release']:.0f})",
                        kept=f"{pool[e]['name']} ({pool[e]['pos']}, {pool[e]['release']:.0f})",
                    )
                    break
            if out["anomaly"]:
                break
    ex_cut = [i for i in idx if not pool[i]["acquired"]]
    acq_kept = [i for i in range(len(pool)) if pool[i]["acquired"] and i not in S]
    if ex_cut and acq_kept:
        out["reverse"] = False
        for e in sorted(ex_cut, key=lambda i: -pool[i]["release"]):
            for a in sorted(acq_kept, key=lambda i: pool[i]["release"]):
                if pool[a]["release"] >= pool[e]["release"]:
                    continue
                if legal.ok(frozenset((S - {e}) | {a})):
                    out.update(
                        reverse=True,
                        reverseReleased=(
                            f"{pool[e]['name']} ({pool[e]['pos']}, {pool[e]['release']:.0f})"
                        ),
                        reverseKept=(
                            f"{pool[a]['name']} ({pool[a]['pos']}, {pool[a]['release']:.0f}, "
                            "just acquired)"
                        ),
                    )
                    break
            if out["reverse"]:
                break
    return out


def _anomaly_summary(rows: list[dict]) -> dict:
    fwd = [r for r in rows if r.get("anomaly") is not None]
    rev = [r for r in rows if r.get("reverse") is not None]
    hits = [r for r in fwd if r["anomaly"]]
    rhits = [r for r in rev if r["reverse"]]
    return {
        "selectionsReleasingAnAcquiredPiece": len(fwd),
        "currencyAnomalies": len(hits),
        "selectionsReleasingExistingWhileKeepingAnAcquiredPiece": len(rev),
        "reverseCurrencyAnomalies": len(rhits),
        "unmatched": sum(1 for r in rows if r.get("reason") == "drops_not_matched"),
        "examples": [{"released": h["released"], "kept": h["kept"]} for h in hits[:6]],
        "reverseExamples": [
            {"released": h["reverseReleased"], "kept": h["reverseKept"]} for h in rhits[:6]
        ],
    }


# ── V5 vs V5-R regret, ties (2026-10-21 review follow-up) ───────────────────
#
# Both directions of what the mode choice costs, on the SAME post-trade pool:
# asset value forgone (sum of c of the released set; V5-R minimises it, so V5
# minus V5-R is >= 0) and the evaluator charge (V5 minimises it, so V5-R minus
# V5 is >= 0).  A negative value in either is a defect, so it is counted
# rather than averaged away.  V5-R's zero currency anomalies are true by
# construction and prove nothing; these are the informative V5-R measures.

FAVOURABLE = ("FAVORABLE", "STRONGLY_FAVORABLE")


def _sum_c(pool, drops) -> float | None:
    idx = _match_pool(pool, drops)
    return None if idx is None else float(sum(pool[i]["release"] for i in idx))


def _incoming_above_own_c(pool, drops) -> int:
    """Released just-acquired pieces whose charge exceeds their own ``c``
    (sequential-removal attribution or a clamp at ``sum c``)."""
    idx = _match_pool(pool, drops)
    if idx is None:
        return 0
    return sum(
        1
        for i, d in zip(idx, drops)
        if d[4] and d[3] is not None and d[3] > pool[i]["release"] + 0.5
    )


def _tie_of(s) -> dict | None:
    rc = s.get("rosterCapacity") or {}
    return (rc.get("forcedDropSelection") or {}).get("tieBreak")


def regret_row(pool, drops_v5, drops_r, charge_v5, charge_r, base, tie_r) -> dict:
    return {
        "sumC": (_sum_c(pool, drops_v5), _sum_c(pool, drops_r)),
        "charge": (float(charge_v5 or 0), float(charge_r or 0)),
        "base": base,
        "aboveOwnC": (_incoming_above_own_c(pool, drops_v5), _incoming_above_own_c(pool, drops_r)),
        "tie": tie_r,
    }


def _dist(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "median": None, "p90": None, "max": None}
    s = sorted(xs)
    return {
        "n": len(s),
        "median": _r(statistics.median(s), 1),
        "p90": _r(s[min(len(s) - 1, int(0.9 * len(s)))], 1),
        "max": _r(s[-1], 1),
    }


def _regret_summary(rows: list[dict]) -> dict:
    asset = [r["sumC"][0] - r["sumC"][1] for r in rows if None not in r["sumC"]]
    charge = [r["charge"][1] - r["charge"][0] for r in rows]
    share = [
        100.0 * (r["charge"][1] - r["charge"][0]) / r["base"]
        for r in rows
        if r["base"] and abs(r["charge"][1] - r["charge"][0]) > 0.5
    ]
    ties = [r["tie"] for r in rows if r["tie"]]
    return {
        "selectionsCompared": len(rows),
        "assetValueRegretV5MinusV5R": {
            **_dist([x for x in asset if x > 0.5]),
            "unmatched": sum(1 for r in rows if None in r["sumC"]),
            "negativeDefect": sum(1 for x in asset if x < -0.5),
        },
        "chargeRegretV5RMinusV5": {
            **_dist([x for x in charge if x > 0.5]),
            "negativeDefect": sum(1 for x in charge if x < -0.5),
        },
        "chargeRegretPctOfBandBase": _dist(share),
        "incomingChargedAboveOwnC": {
            "V5": sum(r["aboveOwnC"][0] for r in rows),
            "V5-R": sum(r["aboveOwnC"][1] for r in rows),
        },
        "tieCensusV5R": {
            "tieBreakApplied": len(ties),
            "resolvedBy": dict(Counter(t.get("resolvedBy") for t in ties)),
            "chargeSpread": _dist([t["chargeSpread"] for t in ties if t.get("chargeSpread")]),
        },
    }


def unpriced_roster_census(ctx) -> dict:
    """Rostered players the board does not price, by position: the
    dead-roster-spot vs real-asset question behind the evidence-gate lifts
    (an unpriced cut is charged the position's waiver ceiling)."""
    cap = int(ctx["roster_settings"].get("rosterSize") or 0)
    by_pos = Counter()
    rostered = teams_with = at_cap_with = 0
    for me in ctx["teams"]:
        cc = RC.build_capacity_context(
            ctx["contract"], LEAGUE, me, roster_settings=ctx["roster_settings"]
        )
        rostered += len(cc.roster_player_names)
        unpriced = [a for a in cc.assets_by_key.values() if a.board_value is None]
        for a in unpriced:
            by_pos[a.position or "unknown"] += 1
        if unpriced:
            teams_with += 1
            at_cap_with += len(me.get("players") or []) >= cap > 0
    return {
        "rosteredPlayers": rostered,
        "unpricedRostered": sum(by_pos.values()),
        "unpricedByPosition": dict(by_pos.most_common()),
        "teamsWithUnpriced": teams_with,
        "teamsAtCapWithUnpriced": at_cap_with,
    }


# ── 1 + 2. the War Room filler-flip design ──────────────────────────────────


def war_room(ctx, max_opps: int, seed: int) -> dict:
    t0 = time.time()
    with flag(False):
        diag = D.run_diagnostic(ctx, max_opps, seed)
    results = diag["results"]
    # Shadow-variant band base.  The diagnostic stores the larger ADJUSTED side
    # (``step["larger"]``), the fairness_bands_v1 base.  The production decision
    # (``trade_decision._objective_value``) classifies against the band owner's
    # basis — since fairness_bands_v2 the larger PACKAGE UTILITY of the same
    # (full) package — so the shadows are re-based onto what production reads,
    # taken from the same flag-OFF asset-only objective, never recomputed here.
    # Under v1 the two bases coincide and nothing changes.
    rebased = 0
    for rec in results:
        s = rec["s"]
        fill_names = [r["name"] for r in s["fill"]]
        for st in rec["steps"]:
            if st.get("larger") is None:
                continue
            pin = [s["y"]["name"]] + fill_names[: st["k"]]
            with flag(False):
                a = comp_a(sim(ctx, s["me"], pin, [s["x"]["name"]], False), False)
            st["largerAdjustedSide"] = st["larger"]
            st["larger"] = a["largerPackageUtility"]
            rebased += st["larger"] != st["largerAdjustedSide"]
    variants = {v: D.classify_flips(results, v) for v in D.VARIANTS}

    # V5 / V6 shadow costs, then the MEASURED flag-ON path.
    gap_cache: dict = {}
    for si, rec in enumerate(results):
        s = rec["s"]
        fill_names = [r["name"] for r in s["fill"]]
        pout = [s["x"]["name"]]

        def gap_with(fset, _s=s, _si=si, _pout=pout, _fill=fill_names):
            key = (_si, frozenset(fset))
            if key not in gap_cache:
                pin = [_s["y"]["name"]] + [n for n in _fill if n in fset]
                with flag(False):
                    a = comp_a(sim(ctx, _s["me"], pin, _pout, False), False)
                gap_cache[key] = (a["vaAdjustedGap"], a["largerAdjustedSide"]) if a else None
            return gap_cache[key]

        for st in rec["steps"]:
            k = st["k"]
            pin = [s["y"]["name"]] + fill_names[:k]
            if k > 0 and st["d"] > 0 and st.get("pool") is not None:
                pool, legal, d = st["pool"], st["legal"], st["d"]
                acq = [i for i, p in enumerate(pool) if p["acquired"] and p["name"] in fill_names]
                existing = {i for i, p in enumerate(pool) if not p["acquired"]}
                best = None
                for j in range(0, min(d, len(acq)) + 1):
                    for J in itertools.combinations(acq, j):
                        if not legal.ok(frozenset(J)):
                            continue
                        rest = D.greedy(pool, D._Fixed(legal, J), d - j,
                                        key=lambda i: (pool[i]["release"], str(pool[i]["asset"].player_id)),
                                        allowed=existing)  # fmt: skip
                        if len(rest) < d - j:
                            continue
                        kept = [n for n in fill_names[:k] if n not in {pool[i]["name"] for i in J}]
                        g = gap_with(kept)
                        if g is None:
                            continue
                        charge = st["gap"] - g[0] + sum(pool[i]["release"] for i in rest)
                        if best is None or charge < best:
                            best = charge
                st["charges"]["V5_implementedRule"] = best
                # V5-R shadow: cheapest legal set by ``c`` over the WHOLE pool
                # (existing and incoming alike); acquired fillers in it are then
                # netted out of the package, existing cuts charged ``c``.
                vr = D.greedy(pool, legal, d,
                              key=lambda i: (pool[i]["release"], str(pool[i]["asset"].player_id)))  # fmt: skip
                vr_charge = None
                if len(vr) == d and all(
                    not pool[i]["acquired"] or pool[i]["name"] in fill_names for i in vr
                ):
                    gone = {pool[i]["name"] for i in vr if pool[i]["acquired"]}
                    g = gap_with([n for n in fill_names[:k] if n not in gone])
                    if g is not None:
                        vr_charge = (
                            st["gap"]
                            - g[0]
                            + sum(pool[i]["release"] for i in vr if not pool[i]["acquired"])
                        )
                st["charges"]["V5R_rosterRational"] = vr_charge
                v6 = D.greedy(pool, legal, d, key=lambda i: (pool[i]["ecc"], pool[i]["release"],
                                                             str(pool[i]["asset"].player_id)))  # fmt: skip
                st["charges"]["V6_surplusCharge"] = sum(pool[i]["ecc"] for i in v6)
            # Measured: production path with the flag ON (Team Context ON),
            # once per selection mode.
            for sfx, md in MODES.items():
                with flag(True), mode(md):
                    son = sim(ctx, s["me"], pin, pout, True)
                    a_on = comp_a(son, True)
                    st[f"tcOrdOn{sfx}"] = ordinal(a_on)
                    st[f"chargeOn{sfx}"] = (a_on or {}).get("forcedReleaseCost") or 0
                    st[f"dropsOn{sfx}"] = drops_of(son)
                    st[f"verdictOn{sfx}"] = verdict(packet_of(ctx, son), son)
                    st[f"tieOn{sfx}"] = _tie_of(son)
                if st.get("pool") is not None and st["d"] > 0:
                    st[f"anomaly{sfx}"] = currency_anomaly(
                        st["pool"], st["legal"], st[f"dropsOn{sfx}"]
                    )
            with flag(False):
                soff = sim(ctx, s["me"], pin, pout, True)
                st["dropsOff"] = drops_of(soff)
                st["verdictOff"] = verdict(packet_of(ctx, soff), soff)

    def classify_on(results, sfx=""):
        out = Counter()
        over_sig = 0
        ratios = []
        for rec in results:
            s0 = rec["steps"][0]
            for st in rec["steps"][1:]:
                if st["aoOrd"] is None or s0["aoOrd"] is None or st[f"tcOrdOn{sfx}"] is None:
                    continue
                credit = st["gap"] - s0["gap"]
                if credit > 0:
                    ratios.append(st[f"chargeOn{sfx}"] / credit)
                    over_sig += st[f"chargeOn{sfx}"] > credit
                if _sgn(st["aoOrd"]) == _sgn(s0["aoOrd"]):
                    continue
                out["flips"] += 1
                vo, base = st[f"tcOrdOn{sfx}"], s0[f"tcOrdOn{sfx}"]
                if _sgn(vo) == _sgn(base):
                    out["neutralised"] += 1
                elif _sgn(vo) < _sgn(base):
                    out["overCorrected"] += 1
                else:
                    out["surviving_underCorrected"] += 1
        return {
            **{k: out.get(k, 0) for k in ("flips", "neutralised", "overCorrected", "surviving_underCorrected")},
            "notEvaluable": 0,
            "stepsWhereChargeExceedsFillerCredit": over_sig,
            "chargeOverCreditMedian": _r(statistics.median(ratios), 3) if ratios else None,
        }  # fmt: skip

    for v in ("V5_implementedRule", "V5R_rosterRational", "V6_surplusCharge"):
        variants[v] = D.classify_flips(results, v)
    variants["FLAG_ON_measured"] = classify_on(results)
    variants["FLAG_ON_measured_rosterRational"] = classify_on(results, "R")
    for v, note in (
        ("V5_implementedRule", "0 by construction: releasing the fillers themselves is a legal "
         "option charged exactly their package credit, and V5 minimises the charge — not "
         "evidence that V5 beats V1"),
        ("FLAG_ON_measured", "0 by construction (see V5_implementedRule)"),
        ("V5R_rosterRational", "not guaranteed: V5-R selects by c, not by the charge"),
        ("FLAG_ON_measured_rosterRational", "not guaranteed (see V5R_rosterRational)"),
    ):  # fmt: skip
        variants[v]["stepsWhereChargeExceedsFillerCreditNote"] = note

    def verdicts(sfx: str) -> dict:
        head = Counter()
        cat = Counter()
        cat_trans = Counter()
        gap_trans = Counter()
        unpriced_off = unpriced_on = 0
        drop_changed = 0
        steps = 0
        for rec in results:
            for st in rec["steps"]:
                steps += 1
                off, on = st["verdictOff"], st[f"verdictOn{sfx}"]
                head[(off["headline"] == on["headline"])] += 1
                cat[(off["category"] == on["category"])] += 1
                if off["category"] != on["category"]:
                    cat_trans[f"{off['category']} -> {on['category']}"] += 1
                drop_changed += sorted(map(str, st["dropsOff"])) != sorted(
                    map(str, st[f"dropsOn{sfx}"])
                )
                if off["missingEvidence"] != on["missingEvidence"]:
                    gap_trans[
                        f"{','.join(off['missingEvidence']) or '-'} -> "
                        f"{','.join(on['missingEvidence']) or '-'}"
                    ] += 1
                unpriced_off += any(d[2] is None for d in st["dropsOff"])
                unpriced_on += any(d[2] is None for d in st[f"dropsOn{sfx}"])
        return {
            "stepsCompared": steps,
            "headlineChanged": head[False],
            "publicCategoryChanged": cat[False],
            "publicCategoryTransitions": dict(cat_trans.most_common()),
            "evidenceGapTransitions": dict(gap_trans.most_common()),
            "stepsWithAnUnpricedForcedDrop": {"off": unpriced_off, "on": unpriced_on},
            "forcedDropSetChanged": drop_changed,
            "currencyAnomaly": _anomaly_summary(
                [
                    st[f"anomaly{sfx}"]
                    for rec in results
                    for st in rec["steps"]
                    if st.get(f"anomaly{sfx}") is not None
                ]
            ),
        }

    v5_vs_r = Counter()
    for rec in results:
        for st in rec["steps"]:
            v5_vs_r["steps"] += 1
            v5_vs_r["dropSetDiffers"] += sorted(map(str, st["dropsOn"])) != sorted(
                map(str, st["dropsOnR"])
            )
            v5_vs_r["v5rChargeHigher"] += st["chargeOnR"] > st["chargeOn"] + 0.5
            v5_vs_r["v5rChargeLower"] += st["chargeOnR"] < st["chargeOn"] - 0.5
            v5_vs_r["categoryDiffers"] += (
                st["verdictOn"]["category"] != st["verdictOnR"]["category"]
            )
    regret_rows = [
        regret_row(
            st["pool"],
            st["dropsOn"],
            st["dropsOnR"],
            st["chargeOn"],
            st["chargeOnR"],
            st["verdictOnR"].get("base"),
            st.get("tieOnR"),
        )
        for rec in results
        for st in rec["steps"]
        if st.get("pool") is not None and st["d"] > 0 and (st["dropsOn"] or st["dropsOnR"])
    ]
    rm, rt = diag["repro"]
    prod = variants["PROD"]
    return {
        "design": "identical to the research diagnostic (archive, seed SEED+2, 5 opponents per "
        "roster at the 58 cap; X 2,500-6,500 out, Y at 86-97% of X in, then 1-3 expendable fillers)",
        "reproduction": {
            "samples": len(results),
            "sweetenedSteps": sum(len(r["steps"]) - 1 for r in results),
            "flips_neutralised_overCorrected_surviving": [
                prod["flips"],
                prod["neutralised"],
                prod["overCorrected"],
                prod["surviving_underCorrected"],
            ],
            "matches_133_85_43_5": (
                prod["flips"],
                prod["neutralised"],
                prod["overCorrected"],
                prod["surviving_underCorrected"],
            )
            == (133, 85, 43, 5),
            "productionCutSetReconstructed": f"{rm}/{rt}",
        },  # fmt: skip
        "shadowBandBase": {
            "base": "largerPackageUtility (the production decision's band base, read from the "
            "flag-OFF asset-only objective; classified by fairness_bands.classify)",
            "bandVersion": FB.receipt()["version"],
            "stepsWhereBaseDiffersFromLargerAdjustedSide": rebased,
        },
        "variants": variants,
        "analyzeVerdicts": verdicts(""),
        "analyzeVerdictsRosterRational": verdicts("R"),
        "v5VsRosterRational": dict(v5_vs_r),
        "v5VsRosterRationalRegret": _regret_summary(regret_rows),
        "results": results,
        "elapsedSec": round(time.time() - t0, 1),
    }


# ── 3. census ─────────────────────────────────────────────────────────────


class _CensusTally:
    """Flag OFF vs one flag-ON mode, over the census trades."""

    def __init__(self):
        self.out = Counter()
        self.trans = Counter()
        self.cap_changes = Counter()
        self.charge_delta: list[float] = []
        self.delta_kind = Counter()
        self.gap_trans = Counter()
        self.up_examples: list[dict] = []
        self.examples: list[dict] = []
        self.anomalies: list[dict] = []

    def add(self, shape, pin, pout, ok, soff, voff, son, von, anomaly):
        out = self.out
        out["trades"] += 1
        out[f"trades:{shape}"] += 1
        rc_off, rc_on = soff.get("rosterCapacity") or {}, son.get("rosterCapacity") or {}
        if rc_off.get("requiresDrops"):
            out["requireDrops"] += 1
        d_off, d_on = drops_of(soff), drops_of(son)
        if sorted(map(str, d_off)) != sorted(map(str, d_on)):
            out["dropSetChanged"] += 1
        if (voff["charge"] or 0) != (von["charge"] or 0):
            out["chargeChanged"] += 1
            delta = (von["charge"] or 0) - (voff["charge"] or 0)
            self.charge_delta.append(delta)
            over_b = (rc_off.get("overLimitBefore") or 0) > 0
            self.delta_kind[
                f"{'overLimitBefore' if over_b else 'atOrUnderCap'}:{'up' if delta > 0 else 'down'}"
            ] += 1
            if delta > 0 and len(self.up_examples) < 4:
                self.up_examples.append(self._example(shape, pin, pout, ok, voff, von, d_off, d_on,
                                                      rc_off.get("overLimitBefore")))  # fmt: skip
        if voff["missingEvidence"] != von["missingEvidence"]:
            self.gap_trans[
                f"{','.join(voff['missingEvidence']) or '-'} -> "
                f"{','.join(von['missingEvidence']) or '-'}"
            ] += 1
        if voff["headline"] != von["headline"]:
            out["headlineChanged"] += 1
        if voff["category"] != von["category"]:
            out["publicCategoryChanged"] += 1
            self.trans[f"{voff['category']} -> {von['category']}"] += 1
            if len(self.examples) < 12:
                self.examples.append(self._example(shape, pin, pout, ok, voff, von, d_off, d_on))
        for k in ("forcedDropReleaseCost", "unpricedForcedDrops", "overLimitAfter"):
            if rc_off.get(k) != rc_on.get(k):
                self.cap_changes[k] += 1
        if anomaly is not None:
            self.anomalies.append(anomaly)
        # Review F2 / F4 receipts (counted only when they occur, so a run where
        # neither binds publishes exactly the keys it always did).
        sel_on = rc_on.get("forcedDropSelection") or {}
        if sel_on.get("packageCreditClamp"):
            out["packageCreditClampApplied"] += 1
        if sel_on.get("searchBoundExceeded"):
            out["searchBoundExceeded"] += 1

    @staticmethod
    def _example(shape, pin, pout, ok, voff, von, d_off, d_on, over_before=None):
        ex = {
            "shape": shape,
            "send": [f"{n} ({ok(n)['pos']}, {ok(n)['value']:.0f})" for n in pout],
            "receive": [f"{n} ({ok(n)['pos']}, {ok(n)['value']:.0f})" for n in pin],
            "off": {**voff, "cuts": [_fmt_drop(d) for d in d_off]},
            "on": {**von, "cuts": [_fmt_drop(d) for d in d_on]},
        }
        if over_before is not None:
            ex = {
                "shape": shape,
                "overLimitBefore": over_before,
                **{k: v for k, v in ex.items() if k != "shape"},
            }
        return ex

    def summary(self) -> dict:
        cd = self.charge_delta
        return {
            "counts": dict(self.out),
            "rosterCapacityFieldChanges": dict(self.cap_changes),
            "publicCategoryTransitions": dict(self.trans.most_common()),
            "evidenceGapTransitions": dict(self.gap_trans.most_common()),
            "chargeDeltaByKind": dict(self.delta_kind),
            "chargeIncreaseExamples": self.up_examples,
            "chargeDelta": {
                "n": len(cd),
                "median": _r(statistics.median(cd)) if cd else None,
                "min": _r(min(cd)) if cd else None,
                "max": _r(max(cd)) if cd else None,
            },
            "currencyAnomaly": _anomaly_summary(self.anomalies),
            "examples": self.examples,
        }


def _census_trades(ctx, per_shape: int, seed: int):
    """The census' seeded trades, one ``(team_index, team, shape, pin, pout, ok)``
    per sampled trade.  Flag-independent (the RNG is consumed only here), shared
    by the census and the box-only Component B census so both measure the SAME
    trades."""
    rng = random.Random(seed)
    rows, teams = ctx["rows"], ctx["teams"]

    def ok(n):
        r = rows.get(n)
        return r if r and not r["quarantined"] and r["cls"] != "pick" else None

    shapes = {"1-for-2": (1, 2), "2-for-1": (2, 1), "1-for-3": (1, 3)}
    for ti, me in enumerate(teams):
        mine = [r for r in (ok(n) for n in me["players"]) if r]
        mine_hi = [r for r in mine if 1500 <= r["value"] <= 7000]
        mine_lo = sorted(mine, key=lambda r: r["value"])[:12]
        opps = [o for oi, o in enumerate(teams) if oi != ti]
        for shape, (n_out, n_in) in shapes.items():
            for _ in range(per_shape):
                opp = rng.choice(opps)
                theirs = [r for r in (ok(n) for n in opp["players"]) if r]
                if not mine_hi or len(theirs) < 4:
                    continue
                x = rng.choice(mine_hi)
                main = [r for r in theirs if 0.8 * x["value"] <= r["value"] <= 1.05 * x["value"]]
                if not main:
                    continue
                y = rng.choice(main)
                low = sorted((r for r in theirs if r is not y), key=lambda r: r["value"])[:10]
                pin = [y["name"]] + [r["name"] for r in rng.sample(low, min(len(low), n_in - 1))]
                pout = [x["name"]] + [
                    r["name"] for r in rng.sample([r for r in mine_lo if r is not x], n_out - 1)
                ]
                yield ti, me, shape, pin, pout, ok


def census(ctx, per_shape: int, seed: int) -> dict:
    teams = ctx["teams"]
    cap = int(ctx["roster_settings"].get("rosterSize") or 0)
    tallies = {sfx: _CensusTally() for sfx in MODES}
    v5_vs_r = Counter()
    regret_rows: list[dict] = []
    at_cap = sum(1 for me in teams if len(me.get("players") or []) >= cap)
    ccs: dict[int, object] = {}
    for ti, me, shape, pin, pout, ok in _census_trades(ctx, per_shape, seed):
        with flag(False):
            soff = sim(ctx, me, pin, pout, True)
            voff = verdict(packet_of(ctx, soff), soff)
        charges = {}
        drops = {}
        cats = {}
        ties = {}
        bases = {}
        pool = None
        for sfx, md in MODES.items():
            with flag(True), mode(md):
                son = sim(ctx, me, pin, pout, True)
                von = verdict(packet_of(ctx, son), son)
            anomaly = None
            d_on = drops_of(son)
            if d_on:
                if ti not in ccs:
                    ccs[ti] = RC.build_capacity_context(
                        ctx["contract"], LEAGUE, me, roster_settings=ctx["roster_settings"]
                    )
                cc = ccs[ti]
                pool = D.post_trade_pool(cc, pin, pout)
                anomaly = currency_anomaly(pool, D.Legality(pool, cc), d_on)
            tallies[sfx].add(shape, pin, pout, ok, soff, voff, son, von, anomaly)
            charges[sfx], drops[sfx], cats[sfx] = von["charge"] or 0, d_on, von["category"]
            ties[sfx], bases[sfx] = _tie_of(son), von.get("base")
        if pool is not None:
            regret_rows.append(
                regret_row(
                    pool, drops[""], drops["R"], charges[""], charges["R"], bases["R"], ties["R"]
                )  # fmt: skip
            )
        v5_vs_r["trades"] += 1
        v5_vs_r["dropSetDiffers"] += sorted(map(str, drops[""])) != sorted(map(str, drops["R"]))
        v5_vs_r["v5rChargeHigher"] += charges["R"] > charges[""] + 0.5
        v5_vs_r["v5rChargeLower"] += charges["R"] < charges[""] - 0.5
        v5_vs_r["categoryDiffers"] += cats[""] != cats["R"]
    v5 = tallies[""].summary()
    return {
        "design": f"every dynasty_main team x {per_shape} seeded trades per shape (1-for-2, "
        "2-for-1, 1-for-3) against random rivals: the main incoming piece at 80-105% of a "
        "1,500-7,000 outgoing player, extra pieces from the rival's 10 cheapest players (and "
        "for 2-for-1 the sender's own 12 cheapest); Team Context ON",
        "teamsAtCap": at_cap,
        **v5,
        "rosterRational": tallies["R"].summary(),
        "v5VsRosterRational": dict(v5_vs_r),
        "v5VsRosterRationalRegret": _regret_summary(regret_rows),
    }


# ── 4. Trade Finder ───────────────────────────────────────────────────────


def finder_overlap(ctx, top_k: int) -> dict:
    from src.trade import finder  # noqa: PLC0415

    contract, teams = ctx["contract"], ctx["teams"]
    players = contract["players"]
    names = [t["name"] for t in teams]
    per = []
    per_r = []
    t0 = time.time()
    for me in teams:
        cc = RC.build_capacity_context(contract, LEAGUE, me, roster_settings=ctx["roster_settings"])
        res = {}
        for on in (False, True, "R"):
            with (
                flag(bool(on)),
                mode(FDS.MODE_ROSTER_RATIONAL if on == "R" else FDS.MODE_PACKAGE_CONSISTENT),
            ):
                payload = finder.find_trades(
                    players,
                    me["name"],
                    [n for n in names if n != me["name"]],
                    teams,
                    contract=contract,
                    capacity_context=cc,
                    use_team_context=True,
                    max_results=top_k,
                )
            res[on] = [
                (
                    " + ".join(sorted(a["name"] for a in t["give"]))
                    + " -> "
                    + " + ".join(sorted(a["name"] for a in t["receive"])),
                    (t.get("rankingFactors") or {}).get("forcedDropCost"),
                )
                for t in payload.get("trades") or []
            ]
        off_keys = [k for k, _ in res[False]]
        on_keys = [k for k, _ in res[True]]
        r_keys = [k for k, _ in res["R"]]
        per_r.append({
            "overlap": len(set(off_keys) & set(r_keys)),
            "returnedOff": len(off_keys),
            "returnedOn": len(r_keys),
            "sameOrder": off_keys == r_keys,
            "chargedOn": sum(1 for _k, f in res["R"] if f),
            "overlapWithV5": len(set(on_keys) & set(r_keys)),
            "sameOrderAsV5": on_keys == r_keys,
        })  # fmt: skip
        per.append({
            "atCap": len(me.get("players") or []) >= int(ctx["roster_settings"].get("rosterSize") or 0),
            "returnedOff": len(off_keys),
            "returnedOn": len(on_keys),
            "overlap": len(set(off_keys) & set(on_keys)),
            "sameOrder": off_keys == on_keys,
            "factorChanged": sum(1 for (k, f) in res[True] if k in dict(res[False]) and dict(res[False])[k] != f),
            "chargedOff": sum(1 for _k, f in res[False] if f),
            "chargedOn": sum(1 for _k, f in res[True] if f),
        })  # fmt: skip
    return {
        "design": f"find_trades per dynasty_main team vs every rival, Team Context ON, the team's "
        f"own capacity context, max_results={top_k} (the forced-drop re-rank path)",
        "teams": len(per),
        "meanOverlapAtK": _r(statistics.mean(p["overlap"] / max(1, p["returnedOff"]) for p in per), 3),
        "teamsIdenticalTopK": sum(1 for p in per if p["sameOrder"]),
        "teamsSameSetDifferentOrder": sum(1 for p in per if not p["sameOrder"] and p["overlap"] == p["returnedOff"] == p["returnedOn"]),
        "totalTradesChargedOff": sum(p["chargedOff"] for p in per),
        "totalTradesChargedOn": sum(p["chargedOn"] for p in per),
        "totalFactorChanges": sum(p["factorChanged"] for p in per),
        "perTeam": [{k: v for k, v in p.items()} for p in per],
        "rosterRational": {
            "meanOverlapAtK": _r(statistics.mean(p["overlap"] / max(1, p["returnedOff"]) for p in per_r), 3),
            "teamsIdenticalTopK": sum(1 for p in per_r if p["sameOrder"]),
            "totalTradesChargedOn": sum(p["chargedOn"] for p in per_r),
            "meanOverlapWithV5AtK": _r(statistics.mean(p["overlapWithV5"] / max(1, p["returnedOn"]) for p in per_r), 3),
            "teamsIdenticalToV5": sum(1 for p in per_r if p["sameOrderAsV5"]),
            "perTeam": per_r,
        },
        "elapsedSec": round(time.time() - t0, 1),
    }  # fmt: skip


# ── 5. Perfect Draft ──────────────────────────────────────────────────────


def perfect_draft(ctx) -> dict:
    from src.draft.context import build_roster_context  # noqa: PLC0415

    contract, teams = ctx["contract"], ctx["teams"]
    same = compared = 0
    errors = Counter()
    for t in teams:
        digests = {}
        raised = False
        for on in (False, True):
            with flag(on):
                try:
                    payload = build_roster_context(contract, LEAGUE, owner_id=t.get("ownerId"))
                except Exception as exc:  # noqa: BLE001
                    payload = {"error": type(exc).__name__}
                    errors[f"{type(exc).__name__}:{'on' if on else 'off'}"] += 1
                    raised = True
            digests[on] = hashlib.sha256(
                json.dumps(payload, sort_keys=True, default=str).encode()
            ).hexdigest()
        if raised:
            continue  # an error in both modes is not a comparison
        compared += 1
        same += digests[False] == digests[True]
    return {
        "surface": "src.draft.context.build_roster_context (/api/draft/roster-context)",
        "teams": len(teams),
        "comparedOffVsOn": compared,
        "identicalOffVsOn": same,
        "errorsByMode": dict(errors),
        "note": "teams whose roster context raises (in both modes) are excluded from the "
        "comparison rather than counted identical",
    }


# ── 6. illustrations ──────────────────────────────────────────────────────


def illustrations(results, limit: int = 8) -> list[dict]:
    out = []
    seen = set()
    for rec in results:
        s = rec["s"]
        for st in rec["steps"][1:]:
            if st["verdictOff"]["category"] == st["verdictOn"]["category"]:
                continue
            key = (s["x"]["name"], s["y"]["name"], st["k"])
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "send": f"{s['x']['name']} ({s['x']['pos']}, {s['x']['value']:.0f})",
                "receive": [f"{s['y']['name']} ({s['y']['pos']}, {s['y']['value']:.0f})"]
                + [f"{f['name']} ({f['pos']}, {f['value']:.0f})" for f in s["fill"][: st["k"]]],
                "off": {**st["verdictOff"], "cuts": [_fmt_drop(d) for d in st["dropsOff"]]},
                "on": {**st["verdictOn"], "cuts": [_fmt_drop(d) for d in st["dropsOn"]]},
            })  # fmt: skip
            break
        if len(out) >= limit:
            break
    return out


# ── 7. --box only: real scarcity, Component B, posture ────────────────────

#: Config files whose bytes the verdict depends on; hashed into the report.
BOX_CONFIGS = (
    "config/trade/package_model.json",
    "config/trade/fairness_bands.json",
    "config/trade/analyze_trade.json",
    "config/trade/decision_engine_v1.json",
    "config/trade/team_impact.json",
)
#: Keys carrying per-trade or per-team detail (player names, rosters): dropped
#: from the box report, which keeps counts and statistics only.
BOX_STRIP_KEYS = frozenset(
    {"examples", "reverseExamples", "chargeIncreaseExamples", "perTeam", "illustrations", "results"}
)


def _strip(obj):
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in BOX_STRIP_KEYS}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def scarcity_observed(ctx) -> dict:
    """The scarcity multipliers this host actually resolves (``displacement.
    scarcity_multiplier``, 0.85 - 1.15) per position: the local replay's are all
    1.0 (inert), so this is the receipt that the box run is NOT."""
    me = ctx["teams"][0]
    cc = RC.build_capacity_context(
        ctx["contract"], LEAGUE, me, roster_settings=ctx["roster_settings"]
    )
    mults = {
        pos: round(float(D.DP.scarcity_multiplier(comp)), 4)
        for pos, comp in sorted((cc.scarcity or {}).items())
    }
    vals = list(mults.values())
    return {
        "positions": len(mults),
        "multiplierByPosition": mults,
        "min": min(vals) if vals else None,
        "max": max(vals) if vals else None,
        "inert": (not vals) or all(v == 1.0 for v in vals),
        "waiverValuesPositions": len(cc.waiver_values or {}),
    }


def _b_row(s, packet) -> dict:
    dec = packet.get("decision") or {}
    ru = s.get("rosterUtility") or {}
    return {
        "headline": dec.get("headline"),
        "category": TV.team_category(dec),
        "gaps": sorted(m.get("code") for m in dec.get("missingEvidence") or []),
        "bAvailable": bool(ru.get("available")),
        "bReason": None if ru.get("available") else ru.get("unavailableReason"),
        # Component B's own number: the best-ball lineup impact in points per
        # game of the FINAL legal roster (after the forced cuts).
        "ppg": (ru.get("impact") or {}).get("ppg") if ru.get("available") else None,
        "drops": sorted(map(str, drops_of(s))),
        "strategySource": (dec.get("strategy") or {}).get("source"),
        "postureAvailable": bool((s.get("competitivePosture") or {}).get("available")),
    }


def component_b_census(ctx, per_shape: int, seed: int) -> dict:
    """The census trades decided with the box's REAL roster-utility lens
    (Component B) and posture — no not-applicable stand-in — flag OFF vs each
    flag-ON mode.  Where Component B is unavailable on a trade the row says why
    (``bReason``); that is a finding, not an error."""
    t0 = time.time()
    keys = ("off", *MODES)
    n = Counter()
    state = {k: Counter() for k in keys}
    posture = {k: Counter() for k in keys}
    strategy = {k: Counter() for k in keys}
    headline = {k: Counter() for k in keys}
    changed = {sfx: Counter() for sfx in MODES}
    trans = {sfx: Counter() for sfx in MODES}
    gaps = {sfx: Counter() for sfx in MODES}
    # Interplay (review 2026-10-21): the cut is chosen by dynasty value
    # (Component A) and then scored by lineup utility (Component B).
    inter = {sfx: Counter() for sfx in MODES}
    ppg_delta = {sfx: [] for sfx in MODES}
    for _ti, me, _shape, pin, pout, _ok in _census_trades(ctx, per_shape, seed):
        rows = {}
        a_only = {}
        with flag(False):
            so = sim(ctx, me, pin, pout, True)
            rows["off"] = _b_row(so, packet_of(ctx, so, b_stand_in=False))
        for sfx, md in MODES.items():
            with flag(True), mode(md):
                sn = sim(ctx, me, pin, pout, True)
                rows[sfx] = _b_row(sn, packet_of(ctx, sn, b_stand_in=False))
                a_only[sfx] = TV.team_category((packet_of(ctx, sn).get("decision") or {}))
        for sfx in MODES:
            off, on = rows["off"], rows[sfx]
            if a_only[sfx] in FAVOURABLE:
                inter[sfx]["favourableWithAOnly"] += 1
                if on["bAvailable"]:
                    inter[sfx]["favourableWithAOnlyAndBAvailable"] += 1
                    if on["category"] not in FAVOURABLE:
                        inter[sfx]["favourableLostWhenBVotes"] += 1
            if off["drops"] != on["drops"] and off["bAvailable"] and on["bAvailable"]:
                inter[sfx]["cutChangedWithBAvailable"] += 1
                if off["ppg"] is not None and on["ppg"] is not None:
                    delta = on["ppg"] - off["ppg"]
                    ppg_delta[sfx].append(delta)
                    inter[sfx][
                        "onCutLowersLineupPpg"
                        if delta < -0.05
                        else "onCutRaisesLineupPpg"
                        if delta > 0.05
                        else "lineupPpgUnchanged"
                    ] += 1
        n["trades"] += 1
        for k in keys:
            r = rows[k]
            state[k]["B available" if r["bAvailable"] else f"B unavailable: {r['bReason']}"] += 1
            posture[k]["posture available" if r["postureAvailable"] else "posture unavailable"] += 1
            strategy[k][str(r["strategySource"])] += 1
            headline[k][str(r["headline"])] += 1
        for sfx in MODES:
            off, on = rows["off"], rows[sfx]
            if off["category"] != on["category"]:
                changed[sfx]["categoryChanged"] += 1
                trans[sfx][f"{off['category']} -> {on['category']}"] += 1
            if off["headline"] != on["headline"]:
                changed[sfx]["headlineChanged"] += 1
            if off["gaps"] != on["gaps"]:
                gaps[sfx][f"{','.join(off['gaps']) or '-'} -> {','.join(on['gaps']) or '-'}"] += 1
    names = {"": "V5", "R": "V5-R"}
    return {
        "design": "the census' seeded trades (same sampler), decided with the box's own "
        "roster-utility lens (Component B) and posture instead of the not-applicable stand-in",
        "trades": n["trades"],
        "componentBState": {k: dict(v) for k, v in state.items()},
        "postureState": {k: dict(v) for k, v in posture.items()},
        "strategySource": {k: dict(v) for k, v in strategy.items()},
        "headlineDistribution": {k: dict(v) for k, v in headline.items()},
        "vsOff": {
            names[sfx]: {
                **dict(changed[sfx]),
                "categoryTransitions": dict(trans[sfx].most_common()),
                "evidenceGapTransitions": dict(gaps[sfx].most_common()),
            }
            for sfx in MODES
        },
        "interplay": {
            names[sfx]: {
                **dict(inter[sfx]),
                "lineupPpgDeltaOnMinusOff": {
                    "lower": _dist([-x for x in ppg_delta[sfx] if x < -0.05]),
                    "higher": _dist([x for x in ppg_delta[sfx] if x > 0.05]),
                },
            }
            for sfx in MODES
        },
        "elapsedSec": round(time.time() - t0, 1),
    }


def charge_shift(results) -> dict:
    """War Room steps: the flag-ON minus flag-OFF forced-release charge, over the
    steps whose charge changed, per mode (median and direction counts)."""
    out = {}
    for sfx, name in (("", "V5"), ("R", "V5-R")):
        deltas = []
        steps = 0
        for rec in results:
            for st in rec["steps"]:
                steps += 1
                off, on = st["verdictOff"]["charge"] or 0, st[f"verdictOn{sfx}"]["charge"] or 0
                if off != on:
                    deltas.append(on - off)
        out[name] = {
            "steps": steps,
            "chargeChanged": len(deltas),
            "medianDelta": _r(statistics.median(deltas)) if deltas else None,
            "down": sum(1 for d in deltas if d < 0),
            "up": sum(1 for d in deltas if d > 0),
        }
    return out


@contextlib.contextmanager
def _single_source_unpriced(ctx):
    """STRESS: every single-source player is treated as unpriced (board value
    None, so a cut of him is charged at the position's waiver ceiling).  This is
    the 'are the cheap single-source tail values real?' question: the local
    replay's favourable verdicts rest on 226 - 440 single-source values.  In-process
    monkeypatch of the capacity owner's asset builders, always restored."""
    import dataclasses  # noqa: PLC0415

    ss = set()
    for r in ctx["contract"].get("playersArray") or []:
        if str(r.get("assetClass")).lower() != "pick" and r.get("sourceCount") == 1:
            for key in (r.get("displayName"), r.get("canonicalName"), r.get("playerId")):
                if key:
                    ss.add(RC._norm(key))
    ss.discard("")
    build_orig, resolve_orig = RC.build_roster_assets, RC._resolve_incoming

    def hit(a):
        return RC._norm(a.name) in ss or RC._norm(a.player_id) in ss

    def build(team, by_name, by_id, _o=build_orig):
        assets, unmatched = _o(team, by_name, by_id)
        return [
            dataclasses.replace(a, board_value=None) if hit(a) else a for a in assets
        ], unmatched

    def resolve(name, by_name, _o=resolve_orig):
        a = _o(name, by_name)
        return dataclasses.replace(a, board_value=None) if hit(a) else a

    RC.build_roster_assets, RC._resolve_incoming = build, resolve
    try:
        yield len(ss)
    finally:
        RC.build_roster_assets, RC._resolve_incoming = build_orig, resolve_orig


def single_source_stress_census(ctx, per_shape: int, seed: int) -> dict:
    """The census trades, base vs the single-source stress: how many verdicts end
    FAVORABLE and how many category changes survive when the cheap single-source
    tail is not trusted.  A-driven stand-in packets (comparable to the local
    replay's stress figures)."""
    t0 = time.time()
    keys = ("off", *MODES)
    cats = {sc: {k: Counter() for k in keys} for sc in ("base", "stress")}
    changed = {sc: {sfx: Counter() for sfx in MODES} for sc in ("base", "stress")}
    n = 0
    for _ti, me, _shape, pin, pout, _ok in _census_trades(ctx, per_shape, seed):
        n += 1
        for sc in ("base", "stress"):
            cm = _single_source_unpriced(ctx) if sc == "stress" else contextlib.nullcontext()
            with cm:
                rows = {}
                with flag(False):
                    so = sim(ctx, me, pin, pout, True)
                    rows["off"] = verdict(packet_of(ctx, so), so)
                for sfx, md in MODES.items():
                    with flag(True), mode(md):
                        sn = sim(ctx, me, pin, pout, True)
                        rows[sfx] = verdict(packet_of(ctx, sn), sn)
            for k in keys:
                cats[sc][k][rows[k]["category"]] += 1
            for sfx in MODES:
                if rows["off"]["category"] != rows[sfx]["category"]:
                    changed[sc][sfx]["categoryChanged"] += 1
    names = {"": "V5", "R": "V5-R"}
    with _single_source_unpriced(ctx) as n_single:
        pass
    return {
        "design": "the census' seeded trades under the base board and under the stress "
        "(every single-source player unpriced -> charged at the waiver ceiling)",
        "trades": n,
        "singleSourcePlayersOnBoard": n_single,
        "categoryDistribution": {
            sc: {("OFF" if k == "off" else names[k]): dict(c) for k, c in per.items()}
            for sc, per in cats.items()
        },
        "categoryChangesVsOff": {
            sc: {names[sfx]: dict(c) for sfx, c in per.items()} for sc, per in changed.items()
        },
        "elapsedSec": round(time.time() - t0, 1),
    }


def box_main(args) -> int:
    """The read-only production-box replay (prepared; owner-run only)."""
    t0 = time.time()
    problems = SUP.validate_box_args(args)
    if problems:
        print(json.dumps({"refused": "arguments", "problems": problems}), file=sys.stderr)
        return SUP.EXIT_PIN_MISMATCH
    caps = SUP.apply_resource_caps(
        max_mem_gib=args.max_mem_gib,
        max_cpu_seconds=args.max_cpu_seconds,
        wall_seconds=args.wall_seconds,
    )
    csv_root = Path(args.csv_root)
    expected = {
        "archiveSha256": args.archive_sha256,
        "csvTreeSha256": args.csv_tree_sha256,
        "codeSha": args.expect_code_sha,
        "builtBoardSha256": args.expect_board_sha256,
        "archiveMemberSha256": args.expect_member_sha256,
    }
    observed = {
        "archiveSha256": SUP.sha256_file(REPO / args.archive),
        "csvTreeSha256": SUP.tree_content_sha256(csv_root, CSV_TREE_PATHS),
        "codeSha": _code_sha(),
    }
    pre = ("archiveSha256", "csvTreeSha256", "codeSha")
    bad = SUP.pin_mismatches(observed, {k: v for k, v in expected.items() if k in pre})
    if bad:
        print(json.dumps({"refused": "pin_mismatch", "pins": bad, "observed": observed}),
              file=sys.stderr)  # fmt: skip
        return SUP.EXIT_PIN_MISMATCH
    member, blob, raw = D.load_archive(args.archive)
    observed["archiveMemberSha256"] = hashlib.sha256(blob).hexdigest()
    ctx = build_context_pinned(raw, csv_root)
    S.classify_assets(ctx)
    observed["builtBoardSha256"] = built_board_sha256(ctx["rows"])
    bad = SUP.pin_mismatches(observed, expected)
    if bad:
        print(json.dumps({"refused": "pin_mismatch", "pins": bad, "observed": observed}),
              file=sys.stderr)  # fmt: skip
        return SUP.EXIT_PIN_MISMATCH

    wr = war_room(ctx, args.war_room_opps, S.SEED + 2)
    cen = census(ctx, args.census_per_shape, S.SEED + 7)
    fin = None if args.skip_finder else finder_overlap(ctx, args.finder_top_k)
    pd = perfect_draft(ctx)
    scar = scarcity_observed(ctx)
    comp_b = component_b_census(ctx, args.census_per_shape, S.SEED + 7)
    stress = single_source_stress_census(ctx, args.census_per_shape, S.SEED + 7)
    shift = charge_shift(wr["results"])
    unpriced = unpriced_roster_census(ctx)
    denied = GUARD.denied() if GUARD else []
    net = [d for d in denied if d["event"].startswith("socket.")]
    fatal = [d for d in denied if not d["event"].startswith("socket.")]
    result = {
        "purpose": "EVIDENCE ONLY.  Forced-drop fix (flag forced_drop_cheapest_legal, default "
        "OFF), flag OFF vs ON on the PRODUCTION BOX: read-only, pinned board, aggregates only.",
        "generatedBy": "scripts/forced_drop_fix_replay.py --box",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "activeModelAtRun": pm.active_model_id(),
        "rule": FDS.RULE_ID,
        "ruleRosterRational": FDS.RULE_ID_ROSTER_RATIONAL,
        "defaultSelectionMode": FDS.SELECTION_MODE,
        "provenance": {
            "deployedCodeSha": observed["codeSha"],
            "expectedCodeSha": args.expect_code_sha,
            "archive": args.archive,
            "archiveSha256": observed["archiveSha256"],
            "expectedArchiveSha256": args.archive_sha256,
            "archiveMemberSha256": observed["archiveMemberSha256"],
            "expectedArchiveMemberSha256": args.expect_member_sha256 or "NOT_PROVIDED",
            "csvRev": args.csv_rev,
            "csvTreeSha256": observed["csvTreeSha256"],
            "expectedCsvTreeSha256": args.csv_tree_sha256,
            "builtBoardSha256": observed["builtBoardSha256"],
            "expectedBoardSha256": args.expect_board_sha256 or "NOT_PROVIDED",
            "pricedAssets": len(ctx["rows"]),
            "pinsMatch": True,
            "configSha256": SUP.config_hashes(REPO, BOX_CONFIGS),
        },
        "fairnessBands": FB.receipt(),
        "packageModel": pm.receipt(),
        "resourceCaps": caps,
        "scarcityObserved": scar,
        "warRoom": _strip(wr),
        "census": _strip(cen),
        "finder": None if fin is None else _strip(fin),
        "perfectDraft": pd,
        "componentBCensus": comp_b,
        "singleSourceStress": stress,
        "warRoomChargeShift": shift,
        "unpricedRosterCensus": unpriced,
        "readOnlyGuard": {
            "installed": bool(GUARD and GUARD.installed()),
            "refusedWriteOrProcessAttempts": len(fatal),
            "refusedWriteOrProcessEvents": sorted({d["event"] for d in fatal}),
            "refusedNetworkAttempts": len(net),
            "refusedNetworkCallers": sorted({d["caller"] for d in net}),
        },
        "peakRssMb": SUP.peak_rss_mb(),
        "elapsedSec": round(time.time() - t0, 1),
    }
    result["currencyAnomalyDirections"] = {
        "warRoomV5": wr["analyzeVerdicts"].get("currencyAnomaly"),
        "warRoomV5R": wr["analyzeVerdictsRosterRational"].get("currencyAnomaly"),
        "censusV5": cen.get("currencyAnomaly"),
        "censusV5R": (cen.get("rosterRational") or {}).get("currencyAnomaly"),
    }
    result["currencyAnomalyDirections"] = _strip(result["currencyAnomalyDirections"])
    try:
        SUP.assert_box_output_safe(result, forbidden=SUP.forbidden_tokens(ctx["contract"]))
        S.P2.assert_aggregate_only({k: v for k, v in result.items() if k not in ("provenance",)})
    except ValueError as exc:  # OutputRefused is a ValueError
        print(json.dumps({"refused": "output_not_aggregate_only", "detail": str(exc)}),
              file=sys.stderr)  # fmt: skip
        return SUP.EXIT_OUTPUT_REFUSED
    sys.stdout.write(SUP.dumps_aggregate(result))
    return SUP.EXIT_GUARD_REFUSED if fatal else SUP.EXIT_OK


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--archive", default=D.ARCHIVE_DEFAULT)
    ap.add_argument("--war-room-opps", type=int, default=5)
    ap.add_argument("--census-per-shape", type=int, default=8)
    ap.add_argument("--finder-top-k", type=int, default=20)
    ap.add_argument("--skip-finder", action="store_true")
    ap.add_argument(
        "--csv-rev",
        default=None,
        help="git revision whose " + ", ".join(CSV_TREE_PATHS) + " the contract build reads "
        "(default: the working tree); with --archive this pins the whole board",
    )
    box = ap.add_argument_group("--box (read-only production-box mode; owner-run only)")
    box.add_argument("--box", action="store_true", help="read-only run; report to stdout")
    box.add_argument("--box-selftest", action="store_true", help="guard refusals only, then exit")
    box.add_argument(
        "--csv-root", help="ABSOLUTE path of the pre-materialised CSV tree at --csv-rev"
    )
    box.add_argument("--archive-sha256", help="expected sha256 of the --archive zip")
    box.add_argument("--csv-tree-sha256", help="expected contentSha256 of the --csv-root tree")
    box.add_argument("--expect-code-sha", help="expected deployed code commit (40 hex)")
    box.add_argument("--expect-board-sha256", help="expected built-board sha256 (optional pin)")
    box.add_argument(
        "--expect-member-sha256",
        help="expected sha256 of the archive's JSON member (optional pin; the committed "
        "replay.json records it as board.sha256)",
    )
    box.add_argument("--max-mem-gib", type=float, default=4.0)
    box.add_argument("--max-cpu-seconds", type=int, default=5400)
    box.add_argument("--wall-seconds", type=int, default=7200)
    args = ap.parse_args()
    if args.box:
        # --out is rejected in box mode (validate_box_args); the default is
        # not a user choice, so an explicit one is detected from argv.
        args.out = args.out if "--out" in sys.argv else None
        try:
            return box_main(args)
        except MemoryError:
            print(json.dumps({"refused": "resource_cap", "cap": "memory"}), file=sys.stderr)
            return SUP.EXIT_RESOURCE_CAP
        except TimeoutError as exc:
            print(json.dumps({"refused": "resource_cap", "detail": str(exc)}), file=sys.stderr)
            return SUP.EXIT_RESOURCE_CAP
        except PermissionError as exc:
            print(json.dumps({"refused": "guard", "detail": str(exc)[:200]}), file=sys.stderr)
            return SUP.EXIT_GUARD_REFUSED
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    t0 = time.time()
    member, blob, raw = D.load_archive(args.archive)
    sha = hashlib.sha256(blob).hexdigest()
    with csv_tree(args.csv_rev) as (csv_root, csv_provenance):
        ctx = build_context_pinned(raw, csv_root)
    S.classify_assets(ctx)

    wr = war_room(ctx, args.war_room_opps, S.SEED + 2)
    cen = census(ctx, args.census_per_shape, S.SEED + 7)
    fin = None if args.skip_finder else finder_overlap(ctx, args.finder_top_k)
    pd = perfect_draft(ctx)
    ill = illustrations(wr["results"])
    wr.pop("results")
    result = {
        "purpose": "EVIDENCE ONLY.  Forced-drop fix (flag forced_drop_cheapest_legal, default "
        "OFF): flag OFF vs ON on real dynasty_main rosters.  The flag is toggled in-process "
        "and always restored; nothing served changes.",
        "generatedBy": "scripts/forced_drop_fix_replay.py",
        "activeModelAtRun": pm.active_model_id(),
        "rule": FDS.RULE_ID,
        "ruleRosterRational": FDS.RULE_ID_ROSTER_RATIONAL,
        "defaultSelectionMode": FDS.SELECTION_MODE,
        "board": {
            "archive": args.archive,
            "member": member,
            "sha256": sha,
            "pricedAssets": len(ctx["rows"]),
            "builtBoardSha256": built_board_sha256(ctx["rows"]),
            "csvTree": {"paths": list(CSV_TREE_PATHS), **csv_provenance},
            "pinNote": "the board is a function of the archive AND the CSV tree (source CSVs, "
            "scrape-state stamps, config/weights) the contract build reads; builtBoardSha256 "
            "hashes the resulting name -> canonical value map",
        },
        "fairnessBands": FB.receipt(),
        "codeSha": _code_sha(),
        "warRoom": wr,
        "census": cen,
        "finder": fin,
        "perfectDraft": pd,
        "illustrations": ill,
        "unpricedRosterCensus": unpriced_roster_census(ctx),
        "localLimits": [
            "Component B (roster utility / lineup lens) needs the box-local projection snapshot "
            "and abstains locally; only Component A (VA gap net of the forced-release charge) "
            "and the decision built on it are measured.",
            "Positional scarcity resolves inert locally (multiplier 1.0); on the box it can "
            "scale every release charge by 0.85-1.15.",
        ],
        "elapsedSec": round(time.time() - t0, 1),
    }
    S.P2.assert_aggregate_only({k: v for k, v in result.items() if k not in ("board", "codeSha")})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "reproduction": wr["reproduction"],
                      "flagOn": wr["variants"]["FLAG_ON_measured"],
                      "flagOnR": wr["variants"]["FLAG_ON_measured_rosterRational"],
                      "verdicts": wr["analyzeVerdicts"],
                      "verdictsR": wr["analyzeVerdictsRosterRational"],
                      "v5VsR": wr["v5VsRosterRational"], "census": cen["counts"],
                      "censusR": cen["rosterRational"]["counts"],
                      "censusV5VsR": cen["v5VsRosterRational"],
                      "warRoomRegret": wr["v5VsRosterRationalRegret"],
                      "censusRegret": cen["v5VsRosterRationalRegret"],
                      "finder": None if fin is None else {k: fin[k] for k in fin if k != "perTeam"},
                      "perfectDraft": pd}, indent=1, default=str))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
