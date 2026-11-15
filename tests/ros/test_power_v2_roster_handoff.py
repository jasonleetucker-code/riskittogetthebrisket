"""CQ-09 -- Power Rankings follow the ROSTER through a mid-season hand-off.

Production, dynasty_main 2026: roster 11 passed from Joel (jstuedle) to John
(jnesselhauf) effective week 6 (``config/leagues/roster_ownership_changes.json``,
owned by ``src/public_league/ownership.py``).  ``power_v2`` read the weekly
scores through the per-week owner (``ownership.owner_at``), so weeks 1-5 went
to Joel -- a retired manager who is never ranked -- and the roster's CURRENT
franchise was scored on nothing: ``gamesUsed 0``, all-play / recent / PPG all
null, ranked 11th where a full recompute put it about 10th.  Luck and the
playoff odds (#1822, ``luck._season_weekly_scores(by_franchise=True)``)
already credited the roster with its games.

Two halves are pinned here, on a four-team fixture where roster 4 passes from
``joel`` to ``john`` at week 4:

* **attribution** -- the current franchise is scored on every game the roster
  played, and its row is identical to the row the same roster earns with no
  hand-off at all (an attribution fix, never a formula change);
* **movement baseline** -- the week N-1 publication is keyed to the manager
  who held the roster THEN, so the franchise's previous official rank is
  looked up under that manager, and the row names whose rank it is
  (``previousOfficialOwnerId``) rather than presenting it as John's own.
  Without a recorded hand-off nothing is inferred: a different owner on the
  same roster is still "no previous rank".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import league_registry
from src.public_league import ownership
from src.public_league.identity import Manager, ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot
from src.ros import power_snapshots, power_v2, team_strength
from tests.ros.test_power_v2 import _make_season

LEAGUE = "L2026"
LEAGUE_KEY = "testleague"
JOEL = "joel"
JOHN = "john"
ROSTER = 4
EFFECTIVE_WEEK = 4

# Roster 4 is the strongest team every week, so a correct attribution ranks
# the franchise first; the bug left it with no results at all.
_POINTS = {1: 120.0, 2: 100.0, 3: 90.0, ROSTER: 130.0}
_PAIRS = {
    1: [(1, 2), (3, ROSTER)],
    2: [(1, 3), (2, ROSTER)],
    3: [(1, ROSTER), (2, 3)],
    4: [(1, 2), (3, ROSTER)],
}


def _matchups(last_scored_leg: int) -> dict[int, list[dict]]:
    """Weeks through ``last_scored_leg`` are final; later weeks carry the
    ``0.0`` placeholders Sleeper publishes for an unplayed week."""
    out: dict[int, list[dict]] = {}
    for wk, pairs in _PAIRS.items():
        rows = []
        for mid, (a, b) in enumerate(pairs, start=1):
            for rid in (a, b):
                pts = _POINTS[rid] + wk if wk <= last_scored_leg else 0.0
                rows.append({"roster_id": rid, "matchup_id": mid, "points": pts})
        out[wk] = rows
    return out


def _snapshot(last_scored_leg: int) -> PublicLeagueSnapshot:
    rosters = [
        {"roster_id": 1, "owner_id": "o1"},
        {"roster_id": 2, "owner_id": "o2"},
        {"roster_id": 3, "owner_id": "o3"},
        {"roster_id": ROSTER, "owner_id": JOHN},
    ]
    registry = ManagerRegistry()
    for r in rosters:
        oid = r["owner_id"]
        registry.by_owner_id[oid] = Manager(owner_id=oid, display_name=oid)
        registry.roster_to_owner[(LEAGUE, r["roster_id"])] = oid
    # The outgoing owner keeps an identity for his own weeks and is retired
    # from current directories -- exactly what
    # ``identity.register_handed_off_owners`` gives Joel in production.
    registry.by_owner_id[JOEL] = Manager(owner_id=JOEL, display_name=JOEL, is_retired=True)
    season = _make_season(
        "2026", LEAGUE, rosters, _matchups(last_scored_leg), last_scored_leg=last_scored_leg
    )
    return PublicLeagueSnapshot(
        root_league_id=LEAGUE,
        generated_at="2026-10-19T00:00:00Z",
        seasons=[season],
        managers=registry,
    )


_HANDOFF = {
    (LEAGUE, ROSTER): (
        {
            "leagueId": LEAGUE,
            "rosterId": ROSTER,
            "season": "2026",
            "effectiveWeek": EFFECTIVE_WEEK,
            "fromOwnerId": JOEL,
            "fromUsername": JOEL,
            "toOwnerId": JOHN,
            "toUsername": JOHN,
        },
    )
}


@pytest.fixture
def handoff(monkeypatch):
    monkeypatch.setattr(ownership, "_changes", lambda: _HANDOFF)


@pytest.fixture
def no_handoff(monkeypatch):
    monkeypatch.setattr(ownership, "_changes", lambda: {})


@pytest.fixture
def canonical_env(tmp_path, monkeypatch):
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    monkeypatch.setattr(team_strength, "load_or_compute_team_strength", lambda *a, **k: [])
    monkeypatch.setattr(league_registry, "league_key_for_sleeper_id", lambda _id: LEAGUE_KEY)
    return tmp_path


def _rows(section: dict) -> dict[str, dict]:
    return {r["ownerId"]: r for r in section["currentRanking"]}


# ── attribution ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("last_scored_leg", [EFFECTIVE_WEEK - 1, EFFECTIVE_WEEK])
@pytest.mark.parametrize("lens", [power_v2.LENS_RESULTS_ONLY, power_v2.LENS_CANONICAL])
def test_the_current_franchise_is_scored_on_every_game_the_roster_played(
    handoff, canonical_env, lens, last_scored_leg
):
    """Scored through week 3 is production's shape (hand-off effective the
    week after the last scored one: John had ``gamesUsed 0``); through week 4
    the hand-off week itself is scored and the split left John one game."""
    section = power_v2.build_section(_snapshot(last_scored_leg), lens=lens)
    rows = _rows(section)

    assert JOEL not in rows
    john = rows[JOHN]
    assert john["gamesUsed"] == last_scored_leg
    assert john["recentGamesUsed"] == last_scored_leg
    expected_ppg = sum(_POINTS[ROSTER] + wk for wk in range(1, last_scored_leg + 1))
    assert john["components"]["pointsPerGame"] == pytest.approx(expected_ppg / last_scored_leg)
    assert john["components"]["all_play"] == pytest.approx(1.0)
    # The roster won every game it played; the matchup record is the
    # franchise's, not "0-0".
    assert john["recordSource"] == "matchups"
    assert john["record"] == f"{last_scored_leg}-0"
    assert john["rank"] == 1
    # Every franchise rests on the same number of games: no divergence.
    assert {r["gamesUsed"] for r in rows.values()} == {last_scored_leg}
    assert section["blend"]["scoredGames"] == last_scored_leg


@pytest.mark.parametrize("lens", [power_v2.LENS_RESULTS_ONLY, power_v2.LENS_CANONICAL])
def test_a_recorded_handoff_does_not_change_any_teams_power(canonical_env, monkeypatch, lens):
    """Attribution, not formula: the table with the hand-off recorded is the
    table the same rosters earn when John held roster 4 all season."""
    _drop = ("previousOfficialOwnerId", "franchiseBaselineOwnerId")

    def _table() -> dict[str, dict]:
        rows = _rows(power_v2.build_section(_snapshot(EFFECTIVE_WEEK), lens=lens))
        return {o: {k: v for k, v in r.items() if k not in _drop} for o, r in rows.items()}

    monkeypatch.setattr(ownership, "_changes", lambda: {})
    without = _table()
    monkeypatch.setattr(ownership, "_changes", lambda: _HANDOFF)
    with_handoff = _table()
    assert with_handoff == without


# ── movement baseline ────────────────────────────────────────────────────


def _publish_baseline(root: Path, week: int, ranks: dict[str, int]) -> None:
    """A frozen week-N-1 publication, keyed the way production keyed it."""
    path = root / "power_snapshots" / LEAGUE_KEY / "2026" / f"week_{week:02d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "leagueKey": LEAGUE_KEY,
                "season": "2026",
                "week": week,
                "preseason": week == 0,
                "methodologyVersion": power_v2.METHODOLOGY_VERSION,
                "ranking": [
                    {"ownerId": oid, "rank": rank, "powerScore": 100.0 - 10 * rank}
                    for oid, rank in ranks.items()
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize("last_scored_leg", [EFFECTIVE_WEEK - 1, EFFECTIVE_WEEK])
def test_movement_compares_the_franchise_with_its_own_previous_rank(
    handoff, canonical_env, last_scored_leg
):
    baseline_week = last_scored_leg - 1
    # Before the hand-off week, so the publication carries Joel's ownerId.
    assert baseline_week < EFFECTIVE_WEEK
    _publish_baseline(canonical_env, baseline_week, {"o1": 1, "o2": 2, JOEL: 3, "o3": 4})

    section = power_v2.build_section(_snapshot(last_scored_leg), lens=power_v2.LENS_CANONICAL)
    assert section["movementBaseline"]["status"] == "compared"
    rows = _rows(section)

    john = rows[JOHN]
    assert john["rank"] == 1
    assert john["previousOfficialRank"] == 3
    assert john["weekRankDelta"] == 2
    assert john["previousOfficialPowerScore"] == 70.0
    # Honest label: the baseline rank was earned under the previous manager.
    assert john["previousOfficialOwnerId"] == JOEL
    assert john["franchiseBaselineOwnerId"] == JOEL

    o1 = rows["o1"]
    assert o1["previousOfficialRank"] == 1
    assert o1["previousOfficialOwnerId"] == "o1"


def test_without_a_recorded_handoff_a_new_owner_has_no_previous_rank(no_handoff, canonical_env):
    """No evidence, no continuation: the baseline row belongs to someone
    else and nothing says the roster changed hands."""
    _publish_baseline(canonical_env, EFFECTIVE_WEEK - 1, {"o1": 1, "o2": 2, JOEL: 3, "o3": 4})

    rows = _rows(power_v2.build_section(_snapshot(EFFECTIVE_WEEK), lens=power_v2.LENS_CANONICAL))
    john = rows[JOHN]
    assert john["previousOfficialRank"] is None
    assert john["weekRankDelta"] is None
    assert john["previousOfficialOwnerId"] is None


def test_the_published_week_freezes_the_franchise_movement_and_its_baseline_owner(
    handoff, canonical_env
):
    """The publisher recomputes movement from the live section; it must reach
    the same franchise baseline and record whose rank it was."""
    _publish_baseline(canonical_env, EFFECTIVE_WEEK - 1, {"o1": 1, "o2": 2, JOEL: 3, "o3": 4})
    snapshot = _snapshot(EFFECTIVE_WEEK)
    section = power_v2.build_section(snapshot, lens=power_v2.LENS_CANONICAL)

    path, created = power_snapshots.record_snapshot(
        league_key=LEAGUE_KEY,
        section=section,
        scoring_fingerprint="fp",
        finalized_at="2026-10-20T00:00:00+00:00",
        expected_owner_ids={"o1", "o2", "o3", JOHN},
    )
    assert created
    published = {r["ownerId"]: r for r in json.loads(path.read_text(encoding="utf-8"))["ranking"]}
    assert published[JOHN]["priorRank"] == 3
    assert published[JOHN]["rankDelta"] == 2
    assert published[JOHN]["priorOwnerId"] == JOEL
    assert published["o1"]["priorOwnerId"] == "o1"

    # A restatement over the frozen pair reaches the same franchise baseline,
    # so it neither refuses nor rewrites the published arrow.
    _path, restated = power_snapshots.restate_movement(
        league_key=LEAGUE_KEY, season="2026", week=EFFECTIVE_WEEK, reason="test"
    )
    assert restated is False
