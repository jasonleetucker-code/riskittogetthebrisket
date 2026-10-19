"""Trade War Room speed (owner directive 2026-10-19, part 4) — exactness pins.

Three changes made ``/api/trade/analyze`` faster without changing any number,
and each is pinned here against the computation it replaced:

* the single-starter-absence scenarios reuse ONE slot-eligibility derivation
  per roster (the seam ``_run`` already used) instead of re-deriving it in each
  of ~250 solves;
* the lineup solver's canonical-labelling pass reads the precomputed
  eligibility it was handed (``tests/lineup`` pins the solver itself);
* the BEFORE roster's simulation is reused across trades for the same team —
  content-addressed, so a hit is the identical computation.

Plus: cache-key isolation (scope and every input), mutation safety, single
flight under concurrency, a deterministic performance guard (counts, never
wall-clock), and cross-process determinism of the affected-player rows.
"""

from __future__ import annotations

import dataclasses
import json
import os
import random
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src.league_intel.sim_calibration import PointsModel
from src.roster_intel import best_ball_utility as bbu
from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility

REPO = Path(__file__).resolve().parents[2]
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "DL", "LB", "DB", "IDP_FLEX"]
WEEKS = [7, 8, 9, 10, 11]
DRAWS = 120


@pytest.fixture(autouse=True)
def _fresh_cache():
    bbu.clear_before_side_cache()
    yield
    bbu.clear_before_side_cache()


def _roster(seed: int, n: int = 22, prefix: str = "p") -> list[UtilityPlayer]:
    rng = random.Random(seed)
    positions = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]
    out = []
    for i in range(n):
        pos = positions[i % len(positions)]
        fantasy = ()
        if pos == "DL" and rng.random() < 0.4:
            fantasy = ("DL", "LB")  # hybrid: legal at LB too
        ppg = None if rng.random() < 0.08 else round(rng.uniform(0.0, 22.0), 2)
        availability = None
        if rng.random() < 0.5:
            availability = {
                w: ("unavailable" if rng.random() < 0.15 else "available") for w in WEEKS
            }
        out.append(
            UtilityPlayer(
                player_id=f"{prefix}{i:02d}",
                name=f"{prefix.upper()} {i}",
                position=pos,
                ppg=ppg,
                fantasy_positions=fantasy,
                availability=availability,
            )
        )
    return out


def _trade(before, rng):
    out = rng.sample([p.player_id for p in before], 2)
    incoming = [
        UtilityPlayer("in1", "In One", "WR", 15.5),
        UtilityPlayer("in2", "In Two", "LB", 9.25, ("LB",)),
    ]
    after = [p for p in before if p.player_id not in out] + incoming
    roles = {pid: "outgoing" for pid in out}
    roles.update({"in1": "incoming", "in2": "incoming"})
    return after, roles


def _evaluate(before, after, roles, *, scope=None, weeks=WEEKS, slot_eligibility=None, **kw):
    return evaluate_trade_utility(
        before=before,
        after=after,
        slots=SLOTS,
        roles=roles,
        draws=DRAWS,
        weeks=weeks,
        slot_eligibility=slot_eligibility,
        cache_scope=scope,
        **kw,
    )


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True)


# ── exactness ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("seed", [1, 2, 3, 4])
@pytest.mark.parametrize("weeks", [WEEKS, None])
def test_reused_before_side_is_byte_identical_to_a_fresh_computation(seed, weeks):
    before = _roster(seed)
    after, roles = _trade(before, random.Random(seed))
    fresh = _evaluate(before, after, roles, weeks=weeks)
    first = _evaluate(before, after, roles, scope=("L", "o1"), weeks=weeks)  # miss
    second = _evaluate(before, after, roles, scope=("L", "o1"), weeks=weeks)  # hit
    assert _canon(first) == _canon(fresh)
    assert _canon(second) == _canon(fresh)


def test_a_different_trade_reusing_the_before_side_matches_fresh():
    before = _roster(7)
    rng = random.Random(7)
    after_a, roles_a = _trade(before, rng)
    after_b, roles_b = _trade(before, rng)
    _evaluate(before, after_a, roles_a, scope=("L", "o1"))  # seeds the before side
    reused = _evaluate(before, after_b, roles_b, scope=("L", "o1"))
    assert bbu.before_side_stats["reused"] >= 1
    assert _canon(reused) == _canon(_evaluate(before, after_b, roles_b))


def test_cleanup_roster_and_custom_flex_rule_stay_exact():
    before = _roster(11)
    after, roles = _trade(before, random.Random(11))
    landed = after + [UtilityPlayer("in3", "In Three", "RB", 4.0)]
    rule = {"FLEX": ["RB", "WR"], "IDP_FLEX": ["LB", "DB"]}
    kw = {"after_before_cleanup": landed, "slot_eligibility": rule}
    fresh = _evaluate(before, after, {**roles, "in3": "forcedDrop"}, **kw)
    for _ in range(2):
        got = _evaluate(before, after, {**roles, "in3": "forcedDrop"}, scope=("L", "o1"), **kw)
        assert _canon(got) == _canon(fresh)


@pytest.mark.parametrize("seed", [21, 22, 23])
def test_absence_depth_with_one_eligibility_derivation_matches_per_solve(seed, monkeypatch):
    roster = _roster(seed, n=26)
    rule = {"FLEX": ["RB", "WR", "TE"]}
    shared = bbu._absence_depth(roster, SLOTS, rule, WEEKS)
    monkeypatch.setattr(bbu, "_roster_eligibility", lambda *a, **k: None)
    per_solve = bbu._absence_depth(roster, SLOTS, rule, WEEKS)
    assert shared == per_solve


def test_duplicate_ids_with_different_positions_fall_back_to_per_solve():
    a = UtilityPlayer("dup", "Dup", "RB", 10.0)
    b = UtilityPlayer("dup", "Dup", "WR", 12.0)
    assert bbu._roster_eligibility([a, b], SLOTS, None) is None


# ── isolation ────────────────────────────────────────────────────────────


def _count_computes(monkeypatch) -> list[int]:
    calls: list[int] = []
    real = bbu._compute_before_side

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(bbu, "_compute_before_side", counting)
    return calls


def test_two_leagues_or_two_teams_never_share_an_entry(monkeypatch):
    calls = _count_computes(monkeypatch)
    before = _roster(31)
    after, roles = _trade(before, random.Random(31))
    for scope in [("league_a", "o1"), ("league_b", "o1"), ("league_a", "o2")]:
        _evaluate(before, after, roles, scope=scope)
    assert len(calls) == 3  # identical rosters, three scopes: three computations
    _evaluate(before, after, roles, scope=("league_a", "o1"))
    assert len(calls) == 3  # same scope, same inputs: reused


def _first(r, **changes):
    return [dataclasses.replace(r[0], **changes), *r[1:]]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: _first(r, ppg=30.0),
        lambda r: _first(r, position="TE"),
        lambda r: _first(r, availability={w: "unavailable" for w in WEEKS}),
        lambda r: [*r, UtilityPlayer("extra", "Extra", "DB", 3.0)],
        lambda r: list(reversed(r)),  # order is an input (float summation order)
    ],
)
def test_any_before_roster_input_change_is_a_different_key(mutate, monkeypatch):
    calls = _count_computes(monkeypatch)
    before = _roster(41)
    after, roles = _trade(before, random.Random(41))
    _evaluate(before, after, roles, scope=("L", "o1"))
    changed = mutate(before)
    got = _evaluate(changed, after, roles, scope=("L", "o1"))
    assert len(calls) == 2
    assert _canon(got) == _canon(_evaluate(changed, after, roles))


def test_draws_seed_weeks_model_and_rule_are_part_of_the_key(monkeypatch):
    calls = _count_computes(monkeypatch)
    before = _roster(51)
    after, roles = _trade(before, random.Random(51))
    base = {"scope": ("L", "o1")}
    _evaluate(before, after, roles, **base)
    _evaluate(before, after, roles, seed=99, **base)
    _evaluate(before, after, roles, weeks=[7, 8], **base)
    _evaluate(before, after, roles, slot_eligibility={"FLEX": ["WR"]}, **base)
    _evaluate(before, after, roles, points_model=PointsModel(cv_by_position={"WR": 0.9}), **base)
    evaluate_trade_utility(
        before=before,
        after=after,
        slots=SLOTS,
        roles=roles,
        draws=DRAWS + 1,
        weeks=WEEKS,
        cache_scope=("L", "o1"),
    )
    assert len(calls) == 6


def test_callers_cannot_corrupt_the_reused_entry():
    before = _roster(61)
    after, roles = _trade(before, random.Random(61))
    first = _evaluate(before, after, roles, scope=("L", "o1"))
    pristine = _canon(first)
    first["lineupHoles"]["before"]["noEligiblePlayer"].append("JUNK")
    first["depth"]["before"]["meanLossPpg"] = -1
    first["before"]["unprojectedPlayerIds"].append("JUNK")
    again = _evaluate(before, after, roles, scope=("L", "o1"))
    assert _canon(again) == pristine


# ── concurrency + performance guard ──────────────────────────────────────


def test_concurrent_identical_before_sides_compute_once(monkeypatch):
    gate = threading.Event()
    calls: list[int] = []
    real = bbu._compute_before_side

    def slow(*a, **k):
        calls.append(1)
        gate.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(bbu, "_compute_before_side", slow)
    before = _roster(71)
    after, roles = _trade(before, random.Random(71))
    results: list[dict] = []

    def worker():
        results.append(_evaluate(before, after, roles, scope=("L", "o1")))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    while not calls:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)  # let the other two reach the in-flight build
    gate.set()
    for t in threads:
        t.join(10)
    assert len(calls) == 1
    assert len({_canon(r) for r in results}) == 1


def test_performance_guard_counts_rosters_simulated_and_eligibility_work(monkeypatch):
    """Deterministic: counts work, never time.  N trades for one team simulate
    the before roster once, and each absence-depth pass derives slot
    eligibility once per roster instead of once per solve."""
    runs: list[int] = []
    real_run = bbu._run
    monkeypatch.setattr(bbu, "_run", lambda *a, **k: runs.append(1) or real_run(*a, **k))
    predicate_calls = {"n": 0}
    import src.ros.lineup as lineup

    real_pred = lineup._player_eligible_for_slot

    def counting_pred(slot, player):
        predicate_calls["n"] += 1
        return real_pred(slot, player)

    monkeypatch.setattr(lineup, "_player_eligible_for_slot", counting_pred)
    before = _roster(81, n=30)
    rng = random.Random(81)
    for _ in range(4):
        after, roles = _trade(before, rng)
        _evaluate(before, after, roles, scope=("L", "o1"))
    assert len(runs) == 1 + 4  # before once, one after per trade
    assert bbu.before_side_stats["computed"] >= 1
    # Per evaluation, eligibility is derived O(roster x slots) a handful of
    # times (the run, the absence pass, the structural-holes solves), never
    # once per solve (~250 absence solves x roster x slots before this unit).
    per_eval_bound = 4 * 12 * len(before) * len(SLOTS)
    assert predicate_calls["n"] < 4 * per_eval_bound


# ── cross-process determinism ─────────────────────────────────────────────

_PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from src.roster_intel.best_ball_utility import UtilityPlayer, evaluate_trade_utility
slots = ["RB", "RB", "RB"]
# Trading away all three starters promotes three 0.0-point backs in EVERY
# draw: their lineup-entry shifts tie exactly (+100 pp each).
stars = [UtilityPlayer(f"s{i}", f"S{i}", "RB", 20.0) for i in range(3)]
backs = [UtilityPlayer(f"z{c}", f"Z{c}", "RB", 0.0) for c in "QWERTYUI"]
before = stars + backs
after = list(backs)
roles = {p.player_id: "outgoing" for p in stars}
r = evaluate_trade_utility(before=before, after=after, slots=slots, roles=roles, draws=32)
print(json.dumps([[p["playerId"], p["role"]] for p in r["players"]]))
"""


def test_affected_player_rows_do_not_depend_on_the_hash_seed():
    outs = []
    for seed in ("1", "2", "3"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        res = subprocess.run(
            [sys.executable, "-c", _PROBE, str(REPO)],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=True,
        )
        outs.append(res.stdout.strip())
    assert len(set(outs)) == 1, outs
    rows = json.loads(outs[0])
    promoted = [pid for pid, role in rows if role == "promoted"]
    assert len(promoted) == 3  # the tie this test exists for
    assert promoted == sorted(promoted)


def test_concurrent_cold_ensemble_reads_build_once(monkeypatch):
    from types import SimpleNamespace

    import src.ros.game_day_capture as gdc
    import src.ros.projection_ensemble as pe

    gate = threading.Event()
    builds: list[int] = []

    def build(*, season, scoring_settings):
        builds.append(season)
        gate.wait(5)
        return SimpleNamespace(
            ensemble=(), horizon="PRESEASON_FULL_SEASON", sources_loaded=(), sources_unavailable=()
        )

    monkeypatch.setattr(pe, "build_ros_full_season_ensemble", build)
    monkeypatch.setattr(gdc, "estimate_index_from_ensemble", lambda ens: {"x": 1.0})
    monkeypatch.setattr(bbu, "_ensemble_cache", {})
    card = {"rec": 1.0, "pass_td": 4.0}
    out: list = []
    threads = [
        threading.Thread(target=lambda: out.append(bbu._ensemble_index(2026, card)))
        for _ in range(3)
    ]
    for t in threads:
        t.start()
    while not builds:
        threading.Event().wait(0.01)
    threading.Event().wait(0.2)
    gate.set()
    for t in threads:
        t.join(10)
    assert builds == [2026]
    assert len(out) == 3 and all(o == out[0] for o in out)


def test_a_failed_ensemble_build_is_not_handed_to_concurrent_callers(monkeypatch):
    from types import SimpleNamespace

    import src.ros.game_day_capture as gdc
    import src.ros.projection_ensemble as pe

    gate = threading.Event()
    builds: list[int] = []

    def build(*, season, scoring_settings):
        builds.append(season)
        if len(builds) == 1:
            gate.wait(5)
            raise RuntimeError("snapshot unreadable")
        return SimpleNamespace(
            ensemble=(), horizon="PRESEASON_FULL_SEASON", sources_loaded=(), sources_unavailable=()
        )

    monkeypatch.setattr(pe, "build_ros_full_season_ensemble", build)
    monkeypatch.setattr(gdc, "estimate_index_from_ensemble", lambda ens: {"x": 1.0})
    monkeypatch.setattr(bbu, "_ensemble_cache", {})
    card = {"rec": 1.0, "pass_td": 4.0}
    out: dict = {}

    def lead():
        try:
            bbu._ensemble_index(2026, card)
        except RuntimeError:
            out["lead"] = "raised"

    t = threading.Thread(target=lead)
    t.start()
    while not builds:
        threading.Event().wait(0.01)
    f = threading.Thread(target=lambda: out.setdefault("follow", bbu._ensemble_index(2026, card)))
    f.start()
    threading.Event().wait(0.2)
    gate.set()
    t.join(10)
    f.join(10)
    assert out["lead"] == "raised"
    assert out["follow"][0] == {"x": 1.0}  # its own build succeeded
    assert builds == [2026, 2026]
