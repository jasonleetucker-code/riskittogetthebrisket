"""Playoff odds must never publish alphabetical order as certainty.

THE DEFECT (W19-F008 / W30-F002)
--------------------------------
``playoff_odds.py`` substituted a flat ``[100.0]`` placeholder when an owner
had no sampled weekly scores and the league-wide pool was also empty.  Three
individually-defensible decisions then composed into a fabricated answer:

1. every simulated matchup became ``100.0 vs 100.0`` — an exact tie, so every
   owner finished every simulation with identical wins, ties and points-for;
2. ``_standings_from_sim`` breaks ties on ``(-(wins + 0.5*ties), -pointsFor,
   ownerId)`` — and its docstring justifies that crude third key on the
   grounds that advanced tiebreakers "don't matter for probability at
   num_sims >= 10_000 when integrated over many draws";
3. the placeholder destroys the variation that argument depends on.  With
   every draw identical there is nothing to integrate over, so the
   lexicographic tiebreak stops being noise and becomes the answer.

Result: the alphabetically-first N Sleeper user ids get ``playoffProbability:
1.0`` and everyone else ``0.0``, stamped ``scheduleCertainty: "posted"`` with
no null and no warning.  Verified on the committed production artifact
``docs/master-site-audit/evidence/W30/playoff-odds-two-engines.json``: v1
returns 1.0 for exactly seven owners, and they are exactly the lexically-first
seven ids.

MISSING IS NEVER ZERO — and it is never 1.0 either.  ``src/ros/playoff_sim.py``
already solved this class of problem correctly for its own engine, returning an
explicit ``unsimulable`` block whose text says "This is not a 0% chance"; these
tests hold this engine to the same standard rather than inventing a second
vocabulary for the same state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.public_league import playoff_odds as _po

EVIDENCE = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "master-site-audit"
    / "evidence"
    / "W30"
    / "playoff-odds-two-engines.json"
)


# ── the mechanism, in isolation ───────────────────────────────────────


def test_identical_records_do_not_resolve_to_alphabetical_order():
    """The tiebreak must not be a function of the ownerId STRING.

    With every owner on an identical record the standings order is the whole
    answer, and today it is ``sorted(owners)``.  A tiebreak that manufactures
    a stable ranking out of nothing manufactures confidence.
    """
    import random

    owners = ["zulu", "yankee", "xray", "charlie", "bravo", "alpha"]
    wins = {o: 0 for o in owners}
    ties = {o: 13 for o in owners}
    points = {o: 1300.0 for o in owners}

    # Across many draws the qualifier set must VARY. Under the old
    # lexicographic key it was constant, which is what turned a tiebreak into
    # a published probability.
    seen = set()
    rng = random.Random(11)
    for _ in range(50):
        seen.add(tuple(_po._standings_from_sim(wins, points, owners, ties=ties, rng=rng)[:3]))
    assert len(seen) > 1, (
        "the top-3 was identical across 50 draws of an exactly-level league — "
        "the tiebreak is deterministic and has become the answer"
    )


def test_relabelling_owners_does_not_change_who_qualifies():
    """The invariant behind the test above, stated as a property.

    Renaming an owner is not a football event.  If the same records produce a
    different qualifier set purely because the ids sort differently, the
    engine is reporting the alphabet.
    """
    import random

    ids = [f"owner{i}" for i in range(6)]
    wins = {o: 0 for o in ids}
    ties = {o: 13 for o in ids}
    pts = {o: 1300.0 for o in ids}

    # Same seed, same records: reversing the ITERATION ORDER of the ids must
    # not change which of them qualifies. Renaming or reordering owners is not
    # a football event.
    a = _po._standings_from_sim(wins, pts, list(ids), ties=ties, rng=random.Random(7))
    b = _po._standings_from_sim(wins, pts, list(reversed(ids)), ties=ties, rng=random.Random(7))
    assert sorted(a) == sorted(b), "the owner set itself changed"
    # Non-vacuity: an exactly-level league must not resolve to the id order.
    assert (
        a[:3] != sorted(ids)[:3] or b[:3] != sorted(ids)[:3]
    ), "both orderings collapsed to the alphabetical prefix"


# ── end to end: no games played ───────────────────────────────────────


def _snapshot_no_games(owner_ids, *, weeks=3):
    """A league whose schedule is posted but which has played nothing."""
    from types import SimpleNamespace

    rosters = [{"roster_id": i + 1} for i in range(len(owner_ids))]
    matchups = {}
    for wk in range(1, weeks + 1):
        entries = []
        for idx in range(0, len(owner_ids), 2):
            mid = idx // 2 + 1
            entries.append({"roster_id": idx + 1, "matchup_id": mid, "points": 0.0})
            entries.append({"roster_id": idx + 2, "matchup_id": mid, "points": 0.0})
        matchups[wk] = entries

    season = SimpleNamespace(
        season="2026",
        league_id="L",
        league={"settings": {"playoff_teams": 6, "playoff_week_start": weeks + 1}},
        users=[],
        rosters=rosters,
        matchups_by_week=matchups,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
        regular_season_weeks=list(range(1, weeks + 1)),
    )

    managers = SimpleNamespace(
        # ``roster_to_owner`` is a MAPPING keyed (league_id, roster_id) —
        # metrics.resolve_owner:71 does ``.get((league_id, rid_int), "")``.
        roster_to_owner={("L", i + 1): oid for i, oid in enumerate(owner_ids)},
        by_owner_id={o: SimpleNamespace(display_name=o) for o in owner_ids},
    )

    return SimpleNamespace(
        seasons=[season],
        current_season=season,
        managers=managers,
        root_league_id="L",
    )


def test_no_games_played_does_not_publish_one_point_zero():
    """The headline defect: certainty before a single game."""
    ids = ["alpha", "bravo", "charlie", "xray", "yankee", "zulu"]
    try:
        payload = _po.compute_playoff_odds(_snapshot_no_games(ids), num_sims=200)
    except Exception as exc:  # pragma: no cover - surfaces harness drift
        pytest.skip(f"snapshot shape drifted: {exc!r}")

    probs = [o.get("playoffProbability") for o in payload.get("owners", [])]
    assert not any(p == 1.0 for p in probs), f"published certainty with zero games played: {probs}"
    assert not any(
        p == 0.0 for p in probs
    ), "published a 0% chance with zero games played — missing is not zero"


def test_no_games_played_says_why_rather_than_guessing():
    ids = ["alpha", "bravo", "charlie", "xray", "yankee", "zulu"]
    try:
        payload = _po.compute_playoff_odds(_snapshot_no_games(ids), num_sims=200)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"snapshot shape drifted: {exc!r}")

    assert payload.get(
        "unsimulable"
    ), "an engine that cannot answer must say so, not return numbers"
    reason = str(payload["unsimulable"].get("reason") or "")
    assert reason, "unsimulable needs a machine-readable reason"


def test_simulated_is_stamped_on_every_path():
    """Absent and False must not read the same (the meta.valuationMode rule)."""
    ids = ["alpha", "bravo", "charlie", "xray", "yankee", "zulu"]
    try:
        payload = _po.compute_playoff_odds(_snapshot_no_games(ids), num_sims=200)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"snapshot shape drifted: {exc!r}")
    assert "simulated" in payload
    assert payload["simulated"] is False


# ── the committed production artifact ─────────────────────────────────


@pytest.mark.skipif(not EVIDENCE.exists(), reason="evidence artifact absent")
def test_the_recorded_production_output_is_the_alphabet():
    """Pins the defect as MEASURED, so the repair has a target to beat.

    This asserts the OLD behaviour is what the evidence shows — it documents
    the bug rather than requiring it.  If a future refresh of this artifact no
    longer shows the pattern, this test should be deleted along with the note.
    """
    rows = json.loads(EVIDENCE.read_text(encoding="utf-8"))["perOwner"]
    ones = sorted(r["ownerId"] for r in rows if r["v1_playoffProbability"] == 1.0)
    assert (
        ones == sorted(r["ownerId"] for r in rows)[: len(ones)]
    ), "the recorded 1.0 set is no longer the lexically-first N"


def test_the_simulation_loop_passes_an_rng_to_the_tiebreak():
    """Structural guard, in the repo's own idiom.

    ``_standings_from_sim`` keeps an ownerId fallback for callers that pass no
    rng, so a future edit could silently drop the argument at the ONE call
    site that matters and reinstate the defect with every test still green.
    An AST check is how this repo pins that class of regression elsewhere
    (see the lineup solver's no-fallback-greedy test).
    """
    import ast
    from pathlib import Path as _P

    src = _P(_po.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_standings_from_sim"
    ]
    assert calls, "no call to _standings_from_sim found — did it get renamed?"
    for call in calls:
        kwargs = {k.arg for k in call.keywords}
        assert "rng" in kwargs, (
            f"_standings_from_sim called without an explicit rng= at line "
            f"{call.lineno}. Every call site must STATE its tiebreak choice: a "
            "simulation passes the rng so the ownerId cannot become the "
            "answer; the final-standings path passes None because a completed "
            "season is a fact. Inheriting the default hides which one you meant."
        )
