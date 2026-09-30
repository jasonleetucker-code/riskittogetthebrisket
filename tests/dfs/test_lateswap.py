"""Late swap: locked slots never move; only proven-open players come in; nothing is submitted."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

import pytest

from src.dfs.lateswap import export_late_swap, plan_late_swap, player_lock_state
from src.dfs.optimizer import Constraints, optimize, validate_lineup
from src.dfs.rules import get_ruleset
from tests.dfs.test_optimizer import _pool

pytest.importorskip("scipy")

DK = get_ruleset("draftkings.nfl.classic")
SLOTS = [s.name for s in DK.slots]
EARLY, LATE = "2026-10-04T17:00:00+00:00", "2026-10-04T20:25:00+00:00"
NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)  # early game started, late not


def _slate(seed):
    pool = _pool(seed)
    for a in pool:
        a.start_time_utc = EARLY if a.game == "AA@BB" else LATE
    return pool


def _entry(lineup, eid="E1", state="complete"):
    return {
        "entry_id": eid,
        "contest_id": "C1",
        "contest_name": "Test",
        "entry_fee_cents": 300,
        "lineup": lineup,
        "state": state,
        "problems": [],
    }


def _slot_brute(pool, pins, allowed):
    """Best legal total filling every slot, pins fixed IN their slots, others from ``allowed``.

    Slot-aware on purpose: a player pinned to FLEX leaves both RB slots to be
    filled, which a position-ordered enumeration cannot express.
    """
    by_id = {a.player_id: a for a in pool}
    c = Constraints(slot_pins=pins)
    best = None

    def rec(k, chosen):
        nonlocal best
        if k == len(SLOTS):
            if validate_lineup(list(zip(SLOTS, chosen)), DK, by_id, c):
                return
            tot = round(sum(by_id[p].projection for p in chosen), 2)
            best = tot if best is None or tot > best else best
            return
        if k in pins:
            rec(k + 1, chosen + [pins[k]])
            return
        for a in pool:
            if a.player_id in chosen or a.player_id in pins.values() or a.player_id not in allowed:
                continue
            if DK.eligible(a, DK.slots[k]):
                rec(k + 1, chosen + [a.player_id])

    rec(0, [])
    return best


def _worst_legal_lineup(pool):
    """A legal but deliberately poor lineup (negated projections), so swaps have room."""
    flipped = [type(a)(**{**a.__dict__, "projection": -(a.projection or 0)}) for a in pool]
    res = optimize(DK, flipped, Constraints())
    return [p["playerId"] for p in res["lineups"][0]["players"]]


def test_locked_slots_never_move_and_the_swap_is_the_exact_best():
    statuses = []
    for seed in (51, 52, 53, 59, 60):
        pool = _slate(seed)
        by_id = {a.player_id: a for a in pool}
        current = _worst_legal_lineup(pool)
        plan = plan_late_swap(DK, pool, [_entry(current)], NOW)
        p = plan["entries"][0]
        assert plan["submitted"] is False
        for i, pid in enumerate(current):
            if by_id[pid].game == "AA@BB":  # started
                assert p["finalLineup"][i] == pid, "a locked slot moved"
        for pid in set(p["finalLineup"]) - set(current):
            assert by_id[pid].game == "CC@DD", "a started player was swapped in"
        # Exact: slot-aware brute force honouring the same pins and open set.
        pins = {i: pid for i, pid in enumerate(current) if by_id[pid].game == "AA@BB"}
        best = _slot_brute(pool, pins, {a.player_id for a in pool if a.game == "CC@DD"})
        assert best is not None
        current_total = sum(by_id[x].projection for x in current)
        final_total = sum(by_id[x].projection for x in p["finalLineup"])
        # The final lineup scores the exact best; a tie keeps the current lineup.
        assert final_total == pytest.approx(best, abs=1e-6)
        if p["status"] == "swap_recommended":
            assert p["openSlotGain"] == pytest.approx(best - current_total, abs=1e-6)
            assert p["openSlotGain"] > 0 and p["changes"]
        else:
            assert p["status"] == "keep"
            assert p["finalLineup"] == current and p["changes"] == []
        statuses.append(p["status"])
    assert "swap_recommended" in statuses  # non-vacuity: a real swap was exercised


def test_unknown_start_time_is_treated_as_locked_and_never_swapped_in():
    pool = _slate(54)
    current = _worst_legal_lineup(pool)
    target = next(a for a in pool if a.player_id == current[1])
    target.start_time_utc = None
    assert player_lock_state(target, NOW) == "unknown"
    stranger = next(a for a in pool if a.player_id not in current and a.game == "CC@DD")
    stranger.start_time_utc = "2026-10-04T20:25:00"  # naive: cannot be compared, so unknown
    assert player_lock_state(stranger, NOW) == "unknown"
    stranger.projection = 999.0  # would be taken if it were (wrongly) considered open
    p = plan_late_swap(DK, pool, [_entry(current)], NOW)["entries"][0]
    assert p["finalLineup"][1] == target.player_id
    assert stranger.player_id not in p["finalLineup"]


def test_all_locked_and_unresolved_entries_are_left_alone():
    pool = _slate(55)
    current = _worst_legal_lineup(pool)
    late_clock = datetime(2026, 10, 4, 23, 0, tzinfo=timezone.utc)
    plan = plan_late_swap(
        DK, pool, [_entry(current), _entry([None] * 9, eid="E2", state="unresolved")], late_clock
    )
    a, b = plan["entries"]
    assert a["status"] == "all_locked" and a["finalLineup"] == current and a["changes"] == []
    assert b["status"] == "entry_unresolved"


def test_a_pinned_unprojected_player_makes_the_total_unknown_not_zero():
    pool = _slate(56)
    by_id = {a.player_id: a for a in pool}
    current = _worst_legal_lineup(pool)
    locked = next(pid for pid in current if by_id[pid].game == "AA@BB")
    by_id[locked].projection = None
    p = plan_late_swap(DK, pool, [_entry(current)], NOW)["entries"][0]
    assert locked in p["finalLineup"]
    # The lineup total is unknown, but the open-slot gain is still comparable.
    assert p["status"] == "swap_recommended" and p["openSlotGain"] > 0
    assert p["lineup"]["projection"] is None and p["lineup"]["projectionKnownPart"] > 0


def test_export_writes_final_lineups_and_skips_unplannable_entries():
    pool = _slate(57)
    current = _worst_legal_lineup(pool)
    entries = [_entry(current), _entry([None] * 9, eid="E2", state="unresolved")]
    plan = plan_late_swap(DK, pool, entries, NOW)
    text, report = export_late_swap(DK, plan, entries, pool)
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["Entry ID", "Contest Name", "Contest ID", "Entry Fee", *SLOTS]
    assert rows[1][0] == "E1" and rows[1][4:] == plan["entries"][0]["finalLineup"]
    assert rows[1][3] == "$3.00"
    assert report["written"] == ["E1"] and report["skipped"] == [
        {"entryId": "E2", "status": "entry_unresolved"}
    ]


def test_naive_clock_is_refused():
    with pytest.raises(ValueError):
        plan_late_swap(DK, _slate(58), [], datetime(2026, 10, 4, 18, 0))
