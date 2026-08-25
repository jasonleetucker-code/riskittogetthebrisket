"""The V1-27 §10 instrument's own tests.

A checklist nobody tested is a script someone else runs once, against
production, on faith. Three things are proven here and the second is the
one that matters:

1. every check **can PASS** on a clean payload, with a non-zero
   denominator so the fixture actually exercises it;
2. every check **can FAIL** on a payload that violates the property it
   claims to police — a check that cannot be made to fail proves nothing
   about the payloads it passes;
3. every check reports **UNMEASURABLE, never PASS**, on absent input.

Plus the two traps ``check_05`` exists to close, each pinned by a
regression test of its own, because both were real:

* the **name-vs-id join** that made the 2026-08-18 hand-run report 0
  hits and nearly read as a failing property (§10a);
* the **vocabulary mismatch** (raw ``DE``/``DT`` vs lineup ``DL``) that
  inflated the hybrid count from 3 to 16 on the 2026-08-24 board when
  this module was first run.

No network. Every test drives the check layer directly from fixtures;
the transport layer is never imported.
"""

from __future__ import annotations

import copy
from typing import Any

from scripts.verify_lineup_production import (
    CHECKS,
    PASS,
    UNAUTOMATABLE,
    FAIL,
    UNMEASURABLE,
    LineupBundle,
    check_01_stamp_available_and_sourced,
    check_03_simulate_starter_neutral,
    check_03a_sleeper_reachable_still_available,
    check_05_hybrid_started_off_primary,
    check_06_no_player_started_twice,
    run_checks,
)

# ---------------------------------------------------------------------------
# A minimal payload that satisfies every check.
# ---------------------------------------------------------------------------


def _clean_contract() -> dict[str, Any]:
    """Two teams, four slots each, one genuine DL/LB hybrid started at LB."""

    def team(name: str, owner: str, players: list[str], assignments: list[tuple[int, str, str]]):
        return {
            "ownerId": owner,
            "name": name,
            "players": players,
            "optimalLineup": {
                "available": True,
                "slotSource": "sleeper_roster_positions",
                "slots": [s for _i, s, _p in assignments],
                "assignments": [
                    {"slotIndex": i, "slot": s, "player": p} for i, s, p in assignments
                ],
                "starters": sorted(p for _i, _s, p in assignments),
                "bench": [],
                "unpriced": [],
                "unfilledSlots": [],
            },
        }

    return {
        "sleeper": {
            "rosterPositions": ["QB", "RB", "DL", "LB"],
            "scoringSettings": {"rec": 1.0},
            "teams": [
                team(
                    "Alpha",
                    "o1",
                    ["Amy QB", "Ben RB", "Cal DL", "Hyb Player"],
                    [
                        (0, "QB", "Amy QB"),
                        (1, "RB", "Ben RB"),
                        (2, "DL", "Cal DL"),
                        (3, "LB", "Hyb Player"),
                    ],
                ),
                team(
                    "Bravo",
                    "o2",
                    ["Dee QB", "Eli RB", "Fay DL", "Gus LB"],
                    [
                        (0, "QB", "Dee QB"),
                        (1, "RB", "Eli RB"),
                        (2, "DL", "Fay DL"),
                        (3, "LB", "Gus LB"),
                    ],
                ),
            ],
            # Name-keyed, exactly as production publishes them.
            "positions": {
                "Amy QB": "QB",
                "Ben RB": "RB",
                "Cal DL": "DE",
                "Hyb Player": "DL",
                "Dee QB": "QB",
                "Eli RB": "RB",
                "Fay DL": "DT",
                "Gus LB": "LB",
            },
            "fantasyPositions": {
                "Amy QB": ["QB"],
                "Ben RB": ["RB"],
                "Cal DL": ["DL"],
                # The hybrid: eligible at both, primary DL, started at LB.
                "Hyb Player": ["DL", "LB"],
                "Dee QB": ["QB"],
                "Eli RB": ["RB"],
                # THE DISCRIMINATING ROW. A DT eligible at DL *and* LB,
                # started at DL — i.e. at his own primary once ``DT`` is
                # normalized to ``DL``. Multi-eligible, so the
                # ``len(eligible_set) > 1`` gate does NOT excuse him: only
                # the vocabulary normalization keeps him off the hybrid
                # list. Without it, ``"DT" != "DL"`` and he is falsely
                # counted. ``Cal DL`` cannot make that point — he is
                # single-eligible and the gate drops him either way, which
                # is what made this pin vacuous when it was first written.
                "Fay DL": ["DL", "LB"],
                "Gus LB": ["LB"],
            },
        }
    }


def _clean_simulate() -> dict[str, Any]:
    return {"teamImpact": {"starterDelta": {"QB": 0, "RB": 0, "DL": 0, "LB": 0}}}


def _bundle(contract=None, simulate=None) -> LineupBundle:
    return LineupBundle(
        "dynasty_main",
        contract=_clean_contract() if contract is None else contract,
        simulate=_clean_simulate() if simulate is None else simulate,
    )


# ---------------------------------------------------------------------------
# 1. Every check passes a clean payload, non-vacuously.
# ---------------------------------------------------------------------------


def test_every_check_passes_a_clean_payload_with_a_real_denominator():
    results = run_checks(_bundle())
    assert len(results) == len(CHECKS)
    for r in results:
        assert r.result == PASS, f"{r.id} did not pass a clean payload: {r.reason}"
        assert r.denominator > 0, f"{r.id} passed having examined nothing"


# ---------------------------------------------------------------------------
# 2. Every check fails when its property is violated.
# ---------------------------------------------------------------------------


def test_01_fails_when_a_team_is_unavailable():
    c = _clean_contract()
    c["sleeper"]["teams"][0]["optimalLineup"]["available"] = False
    c["sleeper"]["teams"][0]["optimalLineup"]["reason"] = "solver_error"
    r = check_01_stamp_available_and_sourced(_bundle(contract=c))
    assert r.result == FAIL
    assert r.evidence["violationCount"] == 1


def test_01_fails_when_slot_source_is_a_default():
    """The whole point of the check: a lineup solved from declared
    defaults rather than the league's real Sleeper config."""
    c = _clean_contract()
    c["sleeper"]["teams"][1]["optimalLineup"]["slotSource"] = "registry_starters"
    r = check_01_stamp_available_and_sourced(_bundle(contract=c))
    assert r.result == FAIL
    assert any(v["kind"] == "wrong_slot_source" for v in r.evidence["violations"])


def test_03a_fails_on_the_serving_path_defect():
    """§7a: sleeper block healthy, lineups nonetheless unavailable."""
    c = _clean_contract()
    for t in c["sleeper"]["teams"]:
        t["optimalLineup"]["available"] = False
        t["optimalLineup"]["reason"] = "no_starter_slots"
    r = check_03a_sleeper_reachable_still_available(_bundle(contract=c))
    assert r.result == FAIL
    assert "§7a" in (r.reason or "")


def test_03_fails_when_a_starter_neutral_trade_moves_a_seat():
    r = check_03_simulate_starter_neutral(
        _bundle(simulate={"teamImpact": {"starterDelta": {"QB": 0, "RB": -1}}})
    )
    assert r.result == FAIL
    assert r.evidence["moved"] == {"RB": -1}


def test_05_fails_when_eligibility_is_published_but_unused():
    """Every player started at his own primary — eligibility inert."""
    c = _clean_contract()
    c["sleeper"]["teams"][0]["optimalLineup"]["assignments"][3] = {
        "slotIndex": 3,
        "slot": "DL",
        "player": "Hyb Player",
    }
    r = check_05_hybrid_started_off_primary(_bundle(contract=c))
    assert r.result == FAIL
    assert r.evidence["hybridCount"] == 0
    assert r.evidence["assignmentsJoined"] > 0, "must still publish a real join denominator"


def test_06_fails_when_one_player_holds_two_slots():
    c = _clean_contract()
    c["sleeper"]["teams"][0]["optimalLineup"]["assignments"][2] = {
        "slotIndex": 2,
        "slot": "DL",
        "player": "Hyb Player",
    }
    r = check_06_no_player_started_twice(_bundle(contract=c))
    assert r.result == FAIL
    assert r.evidence["violations"][0]["duplicates"] == {"Hyb Player": 2}


# ---------------------------------------------------------------------------
# 3. Absent input is UNMEASURABLE, never PASS.
# ---------------------------------------------------------------------------


def test_every_check_is_unmeasurable_on_an_empty_payload():
    empty = LineupBundle("dynasty_main", contract={"sleeper": {}}, simulate=None)
    for check in CHECKS:
        r = check(empty)
        assert r.result == UNMEASURABLE, f"{r.id} returned {r.result} on an empty payload"
        assert r.reason, f"{r.id} gave no reason for being unmeasurable"


def test_03a_is_unmeasurable_when_sleeper_is_not_reachable():
    """The check is about the REACHABLE state. An unpopulated sleeper
    block cannot exercise it and must not report a verdict either way."""
    c = _clean_contract()
    c["sleeper"].pop("scoringSettings")
    r = check_03a_sleeper_reachable_still_available(_bundle(contract=c))
    assert r.result == UNMEASURABLE
    assert "REACHABLE" in (r.reason or "")


# ---------------------------------------------------------------------------
# The two traps, pinned as regressions.
# ---------------------------------------------------------------------------


def test_05_reports_unmeasurable_not_failure_when_the_join_matches_nothing():
    """THE 2026-08-18 NEAR-FALSE-PASS.

    Assignments keyed one way, eligibility keyed another: the join
    resolves 0 rows. That is a join failure and must read as one —
    reporting FAIL here would repeat the exact mistake §10a records.
    """
    c = _clean_contract()
    for t in c["sleeper"]["teams"]:
        for a in t["optimalLineup"]["assignments"]:
            a["player"] = f"sleeper-id-{a['player']}"  # ids, not names
    r = check_05_hybrid_started_off_primary(_bundle(contract=c))
    assert r.result == UNMEASURABLE, "a 0-row join must never be reported as a property verdict"
    assert r.evidence["assignmentsJoined"] == 0
    assert "JOIN FAILURE" in (r.reason or "")
    assert "no hybrids" in (r.reason or "")


def test_05_does_not_count_a_de_playing_dl_as_a_hybrid():
    """THE VOCABULARY TRAP, measured 2026-08-24: 3 real hybrids became
    16 because ``positions`` says ``DE``/``DT`` while the slot says ``DL``.

    ``Fay DL`` is the row that discriminates: a DT eligible at DL **and**
    LB, started at DL. He is multi-eligible, so the ``len(eligible_set)
    > 1`` gate does not drop him; only normalizing ``DT`` -> ``DL`` on
    the primary side keeps him off the list. Remove that normalization
    and this test goes red.

    ``Cal DL`` (a DE eligible only at DL) is kept as the ordinary case,
    but he proves nothing on his own — the eligibility gate excludes him
    whether or not the vocabulary is normalized.
    """
    r = check_05_hybrid_started_off_primary(_bundle())
    names = {h["player"] for h in r.evidence["hybridsStartedOffPrimary"]}
    assert "Cal DL" not in names, "a DE playing DL was counted as started off-primary"
    assert "Fay DL" not in names, "a DT playing DL was counted as started off-primary"
    assert names == {"Hyb Player"}, f"expected exactly the real hybrid, got {names}"


def test_unautomatable_items_are_declared_not_silently_dropped():
    """§10 has six items; this instrument automates four of them. The
    other two must stay visible, or a partial verification comes to read
    as a complete one."""
    declared = {item for item, _why in UNAUTOMATABLE}
    assert declared == {"02", "04"}
    for _item, why in UNAUTOMATABLE:
        assert len(why) > 40, "an unautomatable item needs a real reason, not a label"


def test_a_clean_run_is_deterministic():
    """Same payload twice, same verdicts — no ordering or set-iteration
    leakage into the result."""
    a = [(r.id, r.result, r.denominator) for r in run_checks(_bundle())]
    b = [
        (r.id, r.result, r.denominator)
        for r in run_checks(_bundle(contract=copy.deepcopy(_clean_contract())))
    ]
    assert a == b
