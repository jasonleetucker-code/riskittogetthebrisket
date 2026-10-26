#!/usr/bin/env python3
"""LI-5 replacement consolidation (design phase P3) — pinned offline replay.  EVIDENCE ONLY.

Design ``docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md`` §8
item 9 and §9; owner decisions 2026-10-21, LVA Package 3 (D1-D8).  Flag
``replacement_level_li5_consolidation`` (default OFF, owner-held).  The flag is
toggled IN-PROCESS only (env var + ``feature_flags.reload()``, always restored);
nothing is written but the evidence JSON.

Two modes:

``--mode identity``
    Digests of every served output the P3 row wires, built with ONLY APIs that
    exist on the pre-wiring commit, so the SAME script runs on ``origin/main``
    and on the branch: Perfect Draft roster context and droppability for every
    team, and the roster-capacity block + forced-drop charge for a seeded set of
    real trades per team, under ``forced_drop_cheapest_legal`` OFF and ON.  Equal
    digests on both trees, with the LI-5 flag OFF, are the real-board flag-OFF
    byte-identity proof.

``--mode replay`` (branch only)
    The stepwise table, flag OFF vs ON, per position: legacy anchor (capacity
    and Perfect Draft populations) -> add-pool eligibility -> health -> banding,
    plus the banded-only and lens-B (no health) shadows; the anchor-setter audit;
    population sizes and ladder length; the consumer effects (Perfect Draft
    waiver values / ladder / cut ladder / positive-surplus rookies,
    droppability ladder, capacity forced drops and charges under both
    forced-drop states); latency; and the board-value check (the flag moves no
    ``rankDerivedValue``).

The input tree is PINNED: the board archive (``--archive``, sha256 stamped) and
the ``CSVs`` / ``data/scrape_state`` / ``config/weights`` tree the contract
build reads, materialised from ``--csv-rev`` (the ``csv_tree`` helper of
``scripts/forced_drop_fix_replay.py``, lifted here because that script imports
the Unix-only ``resource`` module at import time).  Positional scarcity is held
inert (the box-only real scarcity is #1890's box replay's job), and every
socket connect is refused, so the run is offline by construction.

Output is aggregate-only plus NFL player names: teams appear as ``team01`` ..
``teamNN`` (sorted by an internal handle that is never written), never by
league / roster / owner id or team / manager name.

Usage::

    python scripts/li5_replacement_replay.py --mode identity --out <file>
    python scripts/li5_replacement_replay.py --mode replay \\
        --out docs/valuation/evidence/li5_p3_replay_2026-10-25/replay.json
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import random
import socket
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

ARCHIVE_DEFAULT = "exports/archive/dynasty_export_20261025_120337.zip"
CSV_REV_DEFAULT = "503f08581"
LEAGUE = "dynasty_main"
SEED = 20261025
LI5_ENV = "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION"
FDS_ENV = "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL"
CSV_TREE_PATHS = ("CSVs", "data/scrape_state", "config/weights")


# ── offline guard ──────────────────────────────────────────────────────────


def _refuse_network() -> None:
    def _refused(self, *a, **k):  # noqa: ANN001
        raise PermissionError("li5_replacement_replay is offline: socket connect refused")

    socket.socket.connect = _refused  # type: ignore[method-assign]
    socket.socket.connect_ex = _refused  # type: ignore[method-assign]


# ── the input pin (lifted from scripts/forced_drop_fix_replay.py) ─────────


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _tree_content_sha256(root: Path) -> str:
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
def csv_tree(rev: str):
    full = _git("rev-parse", "--verify", f"{rev}^{{commit}}")
    tar = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", full, *CSV_TREE_PATHS],
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="li5-csv-tree-") as tmp:
        with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
            tf.extractall(tmp, filter="data")
        root = Path(tmp)
        yield root, {"revisionSha": full, "contentSha256": _tree_content_sha256(root)}


def load_archive(rel: str) -> tuple[str, str, dict]:
    path = REPO / rel
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    with zipfile.ZipFile(path) as zf:
        member = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        return member, sha, json.loads(zf.read(member))


def build_contract(raw: dict, csv_root: Path) -> dict:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    return build_api_data_contract(raw, csv_root=csv_root)


def board_sha256(contract: dict) -> str:
    rows = sorted(
        (str(r.get("displayName")), r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
        for r in contract.get("playersArray") or []
    )
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


# ── flags and the scarcity hold ────────────────────────────────────────────


@contextlib.contextmanager
def env(name: str, value: str):
    from src.api import feature_flags  # noqa: PLC0415

    prev = os.environ.get(name)
    os.environ[name] = value
    feature_flags.reload()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prev
        feature_flags.reload()


@contextlib.contextmanager
def scarcity_inert():
    """Hold the scarcity reading inert (1.0) for the Perfect Draft context, as
    capacity is given ``scarcity_reading`` explicitly: locally the gameplan
    bundle would be the only network-capable read, and scarcity is #1890's
    box-replay question, not this one."""
    from src.draft import context as dctx  # noqa: PLC0415

    saved = dctx._league_scarcity
    dctx._league_scarcity = lambda league_key, contract: (None, "replay: scarcity held inert")
    try:
        yield
    finally:
        dctx._league_scarcity = saved


_INERT = (None, "replay: scarcity held inert")


def _digest(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def teams_of(contract: dict) -> list[tuple[str, dict]]:
    teams = [t for t in contract["sleeper"]["teams"] if t.get("ownerId")]
    teams.sort(key=lambda t: str(t.get("ownerId")))
    return [(f"team{i + 1:02d}", t) for i, t in enumerate(teams)]


def sample_trades(contract: dict) -> list[tuple[str, int, int, list[str], list[str]]]:
    """Seeded real trades per team: (shape, team index, rival index, in, out)."""
    from src.draft.context import index_contract_rows  # noqa: PLC0415

    _by_id, by_name = index_contract_rows(contract)

    def priced(names):
        out = []
        for n in names:
            row = by_name.get(str(n).strip().lower())
            v = (row or {}).get("rankDerivedValue")
            if isinstance(v, (int, float)) and v > 0:
                out.append((float(v), str(n)))
        return sorted(out)

    teams = teams_of(contract)
    rng = random.Random(SEED)
    trades = []
    for i, (_label, team) in enumerate(teams):
        j = (i + 1 + rng.randrange(len(teams) - 1)) % len(teams)
        mine = priced(team.get("players") or [])
        theirs = priced(teams[j][1].get("players") or [])
        if len(mine) < 4 or len(theirs) < 4:
            continue
        lo_t, mid_t = theirs[: len(theirs) // 3], theirs[len(theirs) // 3 :]
        lo_m, mid_m = mine[: len(mine) // 3], mine[len(mine) // 3 :]
        trades.append(
            ("2for1", i, j, [n for _v, n in rng.sample(mid_t, 2)], [rng.choice(mid_m)[1]])
        )
        trades.append(
            ("1for2", i, j, [rng.choice(mid_t)[1]], [n for _v, n in rng.sample(mid_m, 2)])
        )
        trades.append(("0for2", i, j, [n for _v, n in rng.sample(lo_t, 2)], []))
        trades.append(("3for1", i, j, [n for _v, n in rng.sample(lo_t, 3)], [rng.choice(lo_m)[1]]))
    return trades


def capacity_answers(contract: dict, trades) -> dict[str, dict]:
    from src.trade import roster_capacity as RC  # noqa: PLC0415

    teams = teams_of(contract)
    ctxs = {
        i: RC.build_capacity_context(contract, LEAGUE, t, scarcity_reading=_INERT)
        for i, (_l, t) in enumerate(teams)
    }
    out: dict[str, dict] = {}
    for shape, i, _j, pin, pout in trades:
        cap = RC.assess_roster_capacity(ctxs[i], incoming_players=pin, outgoing_players=pout)
        cost, basis = RC.forced_drop_cost(cap)
        out[f"{teams[i][0]}/{shape}"] = {
            "capacity": cap.to_dict(),
            "forcedDropCost": cost,
            "forcedDropCostBasis": basis,
            "_waiver": dict(ctxs[i].waiver_values),
        }
    return out


def consumer_outputs(contract: dict, trades) -> dict[str, Any]:
    """Every wired consumer's served output, flag state as set by the caller."""
    from src.draft.context import build_roster_context  # noqa: PLC0415
    from src.roster_intel.droppability import team_droppability  # noqa: PLC0415

    out: dict[str, Any] = {"draft": {}, "droppability": {}, "capacity": {}}
    with scarcity_inert():
        for label, team in teams_of(contract):
            out["draft"][label] = build_roster_context(contract, LEAGUE, owner_id=team["ownerId"])
            out["droppability"][label] = team_droppability(contract, owner_id=team["ownerId"])
    for state in ("0", "1"):
        with env(FDS_ENV, state):
            out["capacity"][f"fds{state}"] = capacity_answers(contract, trades)
    return out


# ── identity mode ──────────────────────────────────────────────────────────


def identity(contract: dict) -> dict:
    trades = sample_trades(contract)
    outs = consumer_outputs(contract, trades)
    digests: dict[str, str] = {}
    for section in ("draft", "droppability"):
        for label, payload in outs[section].items():
            digests[f"{section}/{label}"] = _digest(payload)
    for state, answers in outs["capacity"].items():
        for key, ans in answers.items():
            ans = {k: v for k, v in ans.items() if k != "_waiver"}
            digests[f"capacity/{state}/{key}"] = _digest(ans)
    return {
        "trades": len(trades),
        "teams": len(teams_of(contract)),
        "digests": digests,
        "combinedSha256": _digest(digests),
    }


# ── replay mode ────────────────────────────────────────────────────────────


def _levels(rows) -> dict[str, float]:
    from src.draft.displacement import _board_position  # noqa: PLC0415
    from src.league_intel.replacement import waiver_levels  # noqa: PLC0415

    lv = waiver_levels(rows, value_key="rankDerivedValue", position_of=_board_position)
    return {p: round(x.value, 1) for p, x in sorted(lv.items())}


def _best(rows) -> dict[str, float]:
    from src.draft.displacement import _board_position  # noqa: PLC0415

    out: dict[str, float] = {}
    for r in rows:
        p, v = _board_position(r), float(r["rankDerivedValue"])
        if v > out.get(p, 0.0):
            out[p] = v
    return {p: round(v, 1) for p, v in sorted(out.items())}


def _ranked(rows, pos):
    from src.draft.displacement import _board_position  # noqa: PLC0415

    return sorted(
        (r for r in rows if _board_position(r) == pos),
        key=lambda r: -float(r["rankDerivedValue"]),
    )


def stepwise(contract: dict, inputs) -> dict:
    from src.draft import displacement as D  # noqa: PLC0415
    from src.draft import waiver_population as WP  # noqa: PLC0415
    from src.draft.context import league_rostered_keys  # noqa: PLC0415
    from src.draft.rookie_pool import auction_rookie_keys  # noqa: PLC0415
    from src.trade.waiver import (  # noqa: PLC0415
        MIN_WAIVER_VALUE,
        waiver_candidate_exclusion,
        waiver_positions,
    )

    rostered = league_rostered_keys(contract)
    auction = auction_rookie_keys(contract)
    pops = {
        "capacity": WP.consumer_population(contract, rostered, (), inputs=inputs),
        "perfectDraft": WP.consumer_population(contract, rostered, auction, inputs=inputs),
    }
    positions = sorted({D._board_position(r) for p in pops.values() for r in p.base_rows} - {""})
    table = []
    for consumer, pop in pops.items():
        legacy = D.waiver_values_by_position(
            contract, rostered, () if consumer == "capacity" else auction
        )
        banded_base = _levels(pop.base_rows)
        add_best, add_banded = _best(pop.add_pool_rows), _levels(pop.add_pool_rows)
        served = _levels(pop.rows)
        health_best = _best(pop.rows) if pop.health.get("state") == WP.HEALTH_APPLIED else None
        for pos in positions:
            table.append(
                {
                    "consumer": consumer,
                    "position": pos,
                    "A0_legacyBestUnrostered": legacy.get(pos),
                    "addPoolBest": add_best.get(pos),
                    "healthBest": None if health_best is None else health_best.get(pos),
                    "servedLi5": served.get(pos),
                    "bandedOnlyNoAddPool": banded_base.get(pos),
                    "lensB_dynastyShadow_addPoolBanded": add_banded.get(pos),
                    "delta_served_minus_A0": (
                        None
                        if served.get(pos) is None or legacy.get(pos) is None
                        else round(served[pos] - legacy[pos], 1)
                    ),
                    "eligibleFreeAgents": sum(1 for r in pop.rows if D._board_position(r) == pos),
                    "baseFreeAgents": sum(1 for r in pop.base_rows if D._board_position(r) == pos),
                }
            )

    # Sensitivity: exclude ``uncertain`` too (D5) — only meaningful when health ran.
    cap = pops["capacity"]
    uncertain_sensitivity: Any = f"not measured: health {cap.health.get('state')}"
    if cap.health.get("state") == WP.HEALTH_APPLIED:
        kept = [
            r
            for r in cap.rows
            if cap.health_by_id.get(str(r.get("playerId") or ""), ("",))[0] != "uncertain"
        ]
        uncertain_sensitivity = _levels(kept)

    # Anchor-setter audit (design §9 item 2, review caveat 4).
    pos_set = waiver_positions(include_kicker_def=True)

    def describe(row):
        pid = str(row.get("playerId") or "")
        keys = {
            str(row.get(f) or "").strip().lower()
            for f in ("playerId", "legacyRef", "canonicalName", "displayName")
        } - {""}
        return {
            "name": row.get("displayName"),
            "value": row.get("rankDerivedValue"),
            "rookie": bool(row.get("rookie")),
            "sourceCount": row.get("sourceCount"),
            "addPoolExclusion": waiver_candidate_exclusion(
                dict(row),
                positions=pos_set,
                min_value=MIN_WAIVER_VALUE,
                rookies_eligible=inputs.rookies_eligible,
            ),
            "availability": cap.health_by_id.get(pid),
            "inAuctionRookieKeys": bool(keys & {k.lower() for k in auction}),
        }

    setters = {}
    for pos in positions:
        base = _ranked(cap.base_rows, pos)
        setters[pos] = {
            "legacySetter": describe(base[0]) if base else None,
            "bandedMembers": [describe(r) for r in _ranked(cap.rows, pos)[:3]],
        }

    sizes = {
        consumer: {
            "base": len(pop.base_rows),
            "addPool": len(pop.add_pool_rows),
            "served": len(pop.rows),
            "excludedByReason": dict(sorted(pop.excluded_by_reason.items())),
            "health": dict(pop.health),
            "lens": pop.served_lens,
        }
        for consumer, pop in pops.items()
    }
    legacy_ladder = D.free_agent_ladder(contract, rostered, auction, limit=90)
    li5_ladder = D.free_agent_ladder(
        contract, rostered, auction, limit=90, population=pops["perfectDraft"]
    )
    ladder = {
        "legacyLength": len(legacy_ladder),
        "li5Length": len(li5_ladder),
        "legacyTop5": [round(v, 1) for v in legacy_ladder[:5]],
        "li5Top5": [round(v, 1) for v in li5_ladder[:5]],
        "legacyTail": round(legacy_ladder[-1], 1) if legacy_ladder else None,
        "li5Tail": round(li5_ladder[-1], 1) if li5_ladder else None,
    }
    return {
        "table": table,
        "uncertainExcludedSensitivity": uncertain_sensitivity,
        "anchorSetters": setters,
        "populationSizes": sizes,
        "perfectDraftLadder": ladder,
    }


def _rung_names(payload: dict, k: int = 5) -> list[str]:
    return [r["name"] for r in payload["cutLadder"]["rungs"][:k]]


def _transition_label(before: Any, after: Any) -> str:
    return f"{before}->{after}"


def capacity_state_effects(off_answers: dict, on_answers: dict) -> dict:
    """One forced-drop state's capacity effects, LI-5 flag OFF vs ON.

    ``boundTransitions`` reads ``basis.bound`` only.  ``stateTransitions`` reads
    ``basis.state`` (``exact`` / ``lower_bound`` / ...), which is where a charge
    that LI-5 turns from a priced figure into a floor shows up while ``bound``
    stays ``None`` on both sides (LI-5 P3 review finding F-A: three charges moved
    ``exact`` -> ``lower_bound`` at 0.0 and ``boundTransitions`` was ``[]``).
    Both are counted over trades that require drops, and
    ``stateTransitionTrades`` names every changed trade so none is hidden inside
    an aggregate.
    """
    rows = []
    for key, a in off_answers.items():
        b = on_answers[key]
        da = sorted(d["name"] for d in a["capacity"]["forcedDrops"])
        db = sorted(d["name"] for d in b["capacity"]["forcedDrops"])
        rows.append(
            {
                "trade": key,
                "requiresDrops": a["capacity"]["requiresDrops"],
                "dropSetChanged": da != db,
                "chargeOff": a["forcedDropCost"],
                "chargeOn": b["forcedDropCost"],
                "basisOff": {k: a["forcedDropCostBasis"].get(k) for k in ("state", "bound")},
                "basisOn": {
                    k: b["forcedDropCostBasis"].get(k)
                    for k in ("state", "bound", "assumedWaiverBasis")
                },
            }
        )
    with_drops = [r for r in rows if r["requiresDrops"]]
    deltas = [
        r["chargeOn"] - r["chargeOff"]
        for r in with_drops
        if isinstance(r["chargeOn"], (int, float)) and isinstance(r["chargeOff"], (int, float))
    ]
    state_changed = [
        r for r in with_drops if r["basisOff"].get("state") != r["basisOn"].get("state")
    ]
    state_counts: dict[str, int] = {}
    for r in state_changed:
        label = _transition_label(r["basisOff"].get("state"), r["basisOn"].get("state"))
        state_counts[label] = state_counts.get(label, 0) + 1
    return {
        "trades": len(rows),
        "tradesRequiringDrops": len(with_drops),
        "dropSetChanged": sum(1 for r in with_drops if r["dropSetChanged"]),
        "chargeChanged": sum(1 for d in deltas if abs(d) > 1e-9),
        "chargeDeltaMean": round(statistics.fmean(deltas), 1) if deltas else None,
        "chargeDeltaMin": round(min(deltas), 1) if deltas else None,
        "chargeDeltaMax": round(max(deltas), 1) if deltas else None,
        "boundTransitions": sorted(
            {
                _transition_label(r["basisOff"].get("bound"), r["basisOn"].get("bound"))
                for r in with_drops
                if r["basisOff"].get("bound") != r["basisOn"].get("bound")
            }
        ),
        "stateTransitions": dict(sorted(state_counts.items())),
        "stateTransitionTrades": [
            {
                "trade": r["trade"],
                "state": _transition_label(r["basisOff"].get("state"), r["basisOn"].get("state")),
                "chargeOff": r["chargeOff"],
                "chargeOn": r["chargeOn"],
            }
            for r in state_changed
        ],
        "rows": rows,
    }


def consumer_effects(contract: dict, off: dict, on: dict) -> dict:
    from src.draft.rookie_pool import select_rookie_rows  # noqa: PLC0415

    rookies = [
        (str(r.get("position") or "").strip().upper(), float(r["rankDerivedValue"]))
        for r in select_rookie_rows(contract)
        if isinstance(r.get("rankDerivedValue"), (int, float))
    ]

    def positive_surplus(waiver):
        out: dict[str, int] = {}
        for pos, v in rookies:
            if pos in waiver and v > waiver[pos]:
                out[pos] = out.get(pos, 0) + 1
        return dict(sorted(out.items()))

    draft = {}
    for label in off["draft"]:
        a, b = off["draft"][label], on["draft"][label]
        draft[label] = {
            "cutRungs": [a["counts"]["cutRungs"], b["counts"]["cutRungs"]],
            "assumedWaiverRungs": [
                a["counts"]["assumedWaiverRungs"],
                b["counts"]["assumedWaiverRungs"],
            ],
            "undroppable": [a["counts"]["undroppable"], b["counts"]["undroppable"]],
            "top5RungsChanged": _rung_names(a) != _rung_names(b),
            "rungMembershipChanged": {r["name"] for r in a["cutLadder"]["rungs"]}
            != {r["name"] for r in b["cutLadder"]["rungs"]},
        }
    any_label = next(iter(off["draft"]))
    pd_off, pd_on = off["draft"][any_label], on["draft"][any_label]
    drop = {}
    for label in off["droppability"]:
        a, b = off["droppability"][label], on["droppability"][label]
        drop[label] = {
            "rungMembershipChanged": {r["name"] for r in a["cutLadder"]["rungs"]}
            != {r["name"] for r in b["cutLadder"]["rungs"]},
            "undroppableOrderChanged": [u["name"] for u in a["cutLadder"]["undroppable"]]
            != [u["name"] for u in b["cutLadder"]["undroppable"]],
        }

    capacity = {
        state: capacity_state_effects(off["capacity"][state], on["capacity"][state])
        for state in ("fds0", "fds1")
    }

    scarcity = sorted(
        {
            r["scarcityMultiplier"]
            for out in (on["draft"], on["droppability"])
            for p in out.values()
            for r in p["cutLadder"]["rungs"]
        }
    )
    return {
        "perfectDraft": {
            "waiverValuesOff": pd_off["waiverValues"],
            "waiverValuesOn": pd_on["waiverValues"],
            "positiveSurplusRookiesOff": positive_surplus(pd_off["waiverValues"]),
            "positiveSurplusRookiesOn": positive_surplus(pd_on["waiverValues"]),
            "contextVersion": [pd_off["contextVersion"], pd_on["contextVersion"]],
            "perTeam": draft,
            "teamsWithTop5RungChange": sum(1 for d in draft.values() if d["top5RungsChanged"]),
            "teamsWithRungMembershipChange": sum(
                1 for d in draft.values() if d["rungMembershipChanged"]
            ),
        },
        "droppability": {
            "teamsWithRungMembershipChange": sum(
                1 for d in drop.values() if d["rungMembershipChanged"]
            ),
            "teamsWithUndroppableOrderChange": sum(
                1 for d in drop.values() if d["undroppableOrderChanged"]
            ),
        },
        "capacity": capacity,
        "scarcityMultipliersServedOn": scarcity,
    }


def latency(contract: dict) -> dict:
    from src.draft import waiver_population as WP  # noqa: PLC0415
    from src.trade import roster_capacity as RC  # noqa: PLC0415

    team = teams_of(contract)[0][1]

    def measure(n, reset):
        xs = []
        for _ in range(n):
            if reset:
                WP.reset_cache()
            t0 = time.perf_counter()
            RC.build_capacity_context(contract, LEAGUE, team, scarcity_reading=_INERT)
            xs.append((time.perf_counter() - t0) * 1000)
        xs.sort()
        return {"p50ms": round(xs[len(xs) // 2], 2), "p95ms": round(xs[int(len(xs) * 0.95) - 1], 2)}

    with env(LI5_ENV, "0"):
        off = measure(40, False)
    with env(LI5_ENV, "1"):
        cold = measure(40, True)
        warm = measure(40, False)
    return {"buildCapacityContext": {"flagOff": off, "flagOnCold": cold, "flagOnCached": warm}}


def replay(raw: dict, csv_root: Path, as_of: date) -> dict:
    from src.draft import waiver_population as WP  # noqa: PLC0415

    with env(LI5_ENV, "0"):
        contract = build_contract(raw, csv_root)
        board_off = board_sha256(contract)
    with env(LI5_ENV, "1"):
        board_on = board_sha256(build_contract(raw, csv_root))
    trades = sample_trades(contract)
    WP.reset_cache()
    inputs = WP.resolve_request_inputs(contract, today=as_of)
    with env(LI5_ENV, "0"):
        off = consumer_outputs(contract, trades)
    with env(LI5_ENV, "1"):
        WP.reset_cache()
        on = consumer_outputs(contract, trades)
    return {
        "boardValueCheck": {
            "boardSha256FlagOff": board_off,
            "boardSha256FlagOn": board_on,
            "identical": board_off == board_on,
        },
        "requestInputs": {
            "asOf": as_of.isoformat(),
            "rookiesEligible": inputs.rookies_eligible,
            "availabilityContext": inputs.availability is not None,
            "availabilityReason": inputs.availability_reason,
            "currentWeek": getattr(inputs.availability, "current_week", None),
        },
        "stepwise": stepwise(contract, inputs),
        "consumerEffects": consumer_effects(contract, off, on),
        "latency": latency(contract),
        "trades": len(trades),
        "teams": len(teams_of(contract)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--mode", choices=("identity", "replay"), required=True)
    ap.add_argument("--archive", default=ARCHIVE_DEFAULT)
    ap.add_argument("--csv-rev", default=CSV_REV_DEFAULT)
    ap.add_argument("--as-of", default="2026-10-25")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    member, archive_sha, raw = load_archive(args.archive)
    with csv_tree(args.csv_rev) as (csv_root, csv_prov):
        _refuse_network()
        provenance = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "codeSha": _git("rev-parse", "HEAD"),
            "archive": args.archive,
            "archiveMember": member,
            "archiveSha256": archive_sha,
            "csvTree": csv_prov,
            "flag": "replacement_level_li5_consolidation",
            "scarcity": "held inert (1.0) — box-only question",
            "network": "every socket connect refused",
        }
        if args.mode == "identity":
            with env(LI5_ENV, "0"):
                contract = build_contract(raw, csv_root)
                body = {"boardSha256": board_sha256(contract), **identity(contract)}
        else:
            body = replay(raw, csv_root, date.fromisoformat(args.as_of))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"provenance": provenance, **body}, indent=1, default=str) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
