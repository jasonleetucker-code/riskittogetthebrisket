"""Power Rankings must rank THIS season's league, all of it, or refuse.

**The defect (owner report + live reproduction, 2026-09-23).** The share
card showed 10 of 12 teams — Brent, Joey, MaKayla, Ed, Ty, Kich, Collin,
Jason, Eric, Roy — labelled "2026 · Preseason · Current" in Week 3, with NEW
on every row and effective weights of 42/30/14/14. Rebuilding the snapshot
from live Sleeper data and blanking the 2026 rosters (what a failed
``/rosters`` GET produces, since ``sleeper_client`` answers every failure
with ``[]``) reproduced that card exactly. Three compounding engine faults:

1. ``build_section``'s per-season loop ``continue``s on a season with no
   resolvable scores BEFORE resetting its accumulators, so the "current"
   state silently stayed **2025's complete season** (13 games: hence
   ``recent`` distinctness 1 − 4/13 and the 42/30/14/14 split).
2. ``asOfWeek`` became 0 — "Preseason" — so ``movement_against_previous``
   returned ``None`` for every row: all NEW, though Weeks 0, 1 and 2 were
   published and intact.
3. Owner enumeration fell back to team-strength/history filtered by a
   registry built from the same missing rosters, so the two owners who
   joined in 2026 vanished with only a log warning.

Fault 1 is also reachable with a perfectly healthy snapshot: while Week 1
is in progress, live points make ``_is_preseason`` False but no week is
final yet.

Everything here is a synthetic league shaped like the real one: ten
owners who played 2025, two who joined for 2026.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.ros import power_snapshots, power_v2

_VETS = [f"vet-{i:02d}" for i in range(1, 11)]
_NEW = ["new-blaine", "new-jstuedle"]
_OWNERS_2026 = [*_VETS, *_NEW]

#: 2025: every veteran plays 13 weeks; vet-01 is best, vet-10 worst. If any
#: of this reaches a 2026 answer it is unmissable: 2025 points are in the
#: thousands, 2026 points in the low hundreds.
_SCORES_2025 = {wk: {rid: 2000.0 - 100.0 * rid for rid in range(1, 11)} for wk in range(1, 14)}


def _week_2026(wk: int, overrides: dict[int, float] | None = None) -> dict[int, float]:
    """2026 points: the ORDER FLIPS vs 2025 (roster 12 best, roster 1 worst)."""
    out = {rid: 100.0 + 10.0 * rid + wk for rid in range(1, 13)}
    out.update(overrides or {})
    return out


def _rows(scores: dict[int, float]) -> list[dict]:
    return [
        {"roster_id": rid, "matchup_id": (rid + 1) // 2, "points": pts}
        for rid, pts in sorted(scores.items())
    ]


def _season(
    year: str,
    owners: list[str],
    weekly: dict[int, dict[int, float]],
    *,
    last_scored_leg: int | None,
    complete: bool = False,
    wins: dict[int, int] | None = None,
) -> SeasonSnapshot:
    league_id = f"L{year}"
    rosters = []
    for rid, oid in enumerate(owners, start=1):
        w = (wins or {}).get(rid, 0)
        games = last_scored_leg or 0
        rosters.append(
            {
                "roster_id": rid,
                "owner_id": oid,
                "settings": {"wins": w, "losses": max(0, games - w), "ties": 0},
            }
        )
    settings: dict = {"playoff_week_start": 15}
    if last_scored_leg is not None:
        settings["last_scored_leg"] = last_scored_leg
    league = {
        "league_id": league_id,
        "season": year,
        "status": "complete" if complete else "in_season",
        "total_rosters": len(rosters),
        "settings": settings,
    }
    return SeasonSnapshot(
        season=year,
        league_id=league_id,
        league=league,
        users=[{"user_id": oid, "display_name": oid} for oid in owners],
        rosters=rosters,
        matchups_by_week={wk: _rows(s) for wk, s in weekly.items()},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot(current: SeasonSnapshot) -> PublicLeagueSnapshot:
    prior = _season("2025", _VETS, _SCORES_2025, last_scored_leg=17, complete=True)
    seasons = [current, prior]
    snap = PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-09-23T00:00:00Z",
        seasons=seasons,
    )
    snap.managers = build_manager_registry(
        [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
    )
    return snap


def _healthy_2026(**kwargs) -> SeasonSnapshot:
    weekly = kwargs.pop("weekly", {1: _week_2026(1), 2: _week_2026(2)})
    return _season("2026", _OWNERS_2026, weekly, last_scored_leg=2, **kwargs)


#: ROS strength, higher = stronger. Deliberately NOT the results order, so a
#: test can tell which input drove a rank.
_ROS = {oid: float(i) for i, oid in enumerate(reversed(_OWNERS_2026), start=1)}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    """No network, no real data dir, a resolvable league key."""
    rows = [{"ownerId": oid, "teamRosStrength": v} for oid, v in _ROS.items()]
    monkeypatch.setattr(power_v2, "_load_team_strength_rows", lambda *a, **k: list(rows))
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    import src.api.league_registry as league_registry

    monkeypatch.setattr(league_registry, "league_key_for_sleeper_id", lambda _id: "testleague")
    yield tmp_path


def _by_owner(section: dict) -> dict[str, dict]:
    return {r["ownerId"]: r for r in section["currentRanking"]}


# ── Completeness: all twelve, exactly the current league ───────────────


class TestTheCanonicalRankingIsTheWholeCurrentLeague:
    def test_every_current_owner_is_ranked_and_no_one_else(self):
        section = power_v2.build_section(_snapshot(_healthy_2026()))
        ranked = {r["ownerId"] for r in section["currentRanking"] if r["rank"] is not None}
        assert ranked == set(_OWNERS_2026)
        assert len(section["currentRanking"]) == 12
        assert section["expectedTeamCount"] == 12
        assert section["rankingComplete"] is True
        assert section["unownedRosters"] == 0

    def test_owners_new_this_season_carry_only_this_seasons_numbers(self):
        section = power_v2.build_section(_snapshot(_healthy_2026()))
        rows = _by_owner(section)
        for oid, rid in (("new-blaine", 11), ("new-jstuedle", 12)):
            row = rows[oid]
            assert row["gamesUsed"] == 2
            expected_ppg = ((100.0 + 10.0 * rid + 1) + (100.0 + 10.0 * rid + 2)) / 2
            assert row["components"]["pointsPerGame"] == pytest.approx(expected_ppg)

    def test_asof_is_the_last_final_week_of_this_season(self):
        section = power_v2.build_section(_snapshot(_healthy_2026()))
        assert section["asOfSeason"] == "2026"
        assert section["asOfWeek"] == 2
        assert section["countedWeeks"] == [1, 2]


# ── The reproduced defect: a half-fetched current season ───────────────


class TestAHalfFetchedCurrentSeasonIsRefusedNotRanked:
    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(lambda s: setattr(s, "rosters", []), id="rosters-fetch-failed"),
            pytest.param(lambda s: setattr(s, "rosters", s.rosters[:10]), id="rosters-short"),
        ],
    )
    def test_membership_failure_is_an_explicit_refusal(self, mutate):
        current = _healthy_2026()
        mutate(current)
        section = power_v2.build_section(_snapshot(current))
        assert section["currentRanking"] == []
        assert section["unrankable"]["reason"] == "current_league_membership_incomplete"
        assert section["rankingComplete"] is False
        # Never 0: 0 claims "preseason" and turns every movement into NEW.
        assert section["asOfWeek"] is None

    def test_the_exact_production_shape_never_yields_ten_prior_season_rows(self):
        """Pre-fix this returned the ten veterans ranked on 2025 results."""
        current = _healthy_2026()
        current.rosters = []
        section = power_v2.build_section(_snapshot(current))
        assert len(section["currentRanking"]) != 10
        assert section["blend"]["scoredGames"] != 13

    def test_a_registry_missing_this_seasons_roster_map_is_refused(self):
        snap = _snapshot(_healthy_2026())
        for key in [k for k in snap.managers.roster_to_owner if k[0] == "L2026"]:
            del snap.managers.roster_to_owner[key]
        section = power_v2.build_section(snap)
        assert section["unrankable"]["reason"] == "current_league_membership_incomplete"

    def test_host_scored_weeks_with_no_matchups_is_refused(self):
        current = _healthy_2026(weekly={})
        section = power_v2.build_section(_snapshot(current))
        assert section["unrankable"]["reason"] == "current_season_scores_unresolvable"
        assert section["currentRanking"] == []

    def test_the_results_only_lens_is_held_to_the_same_membership(self):
        current = _healthy_2026()
        current.rosters = []
        section = power_v2.build_section(_snapshot(current), lens=power_v2.LENS_RESULTS_ONLY)
        assert section["currentRanking"] == []


# ── Week 1 in progress: the healthy-snapshot route to the same leak ────


class TestNoPriorSeasonResultsBeforeTheFirstFinalWeek:
    def _week1_live(self) -> PublicLeagueSnapshot:
        live = _week_2026(1, overrides={rid: 0.0 for rid in range(1, 7)})
        current = _season("2026", _OWNERS_2026, {1: live}, last_scored_leg=0)
        return _snapshot(current)

    def test_no_result_component_is_measured(self):
        section = power_v2.build_section(self._week1_live())
        assert section["preseason"] is False  # live points on the board
        assert section["blend"]["scoredGames"] == 0
        assert set(section["effectiveWeights"]) == {"team_ros_strength"}
        for row in section["currentRanking"]:
            comps = row["components"]
            for key in ("all_play", "recent", "wl_record", "pointsPerGame", "recentAvg"):
                assert comps[key] is None, (row["ownerId"], key, comps[key])

    def test_all_twelve_are_still_ranked_on_ros_strength(self):
        section = power_v2.build_section(self._week1_live())
        assert section["rankingComplete"] is True
        order = [r["ownerId"] for r in section["currentRanking"]]
        assert order == sorted(_OWNERS_2026, key=lambda o: -_ROS[o])


# ── Zero is an observation inside a final week ─────────────────────────


def test_a_zero_point_roster_week_counts_as_a_game():
    weekly = {1: _week_2026(1), 2: _week_2026(2, overrides={5: 0.0})}
    section = power_v2.build_section(_snapshot(_healthy_2026(weekly=weekly)))
    rows = _by_owner(section)
    assert {r["gamesUsed"] for r in rows.values()} == {2}
    assert section["blend"]["scoredGamesDiverged"] is False
    assert rows["vet-05"]["components"]["pointsPerGame"] == pytest.approx((100.0 + 50.0 + 1) / 2)
    assert rows["vet-05"]["components"]["recentAvg"] == pytest.approx((100.0 + 50.0 + 1) / 2)


# ── Direction and range of every weighted component ────────────────────


class TestComponentDirectionAndRange:
    def test_every_weighted_component_is_a_unit_interval_score(self):
        section = power_v2.build_section(_snapshot(_healthy_2026()))
        for row in section["currentRanking"]:
            for key in section["effectiveWeights"]:
                value = row["components"][key]
                assert value is None or 0.0 <= value <= 1.0, (row["ownerId"], key, value)

    def test_more_points_never_lowers_results_or_power(self):
        base = power_v2.build_section(_snapshot(_healthy_2026()))
        boosted_weekly = {1: _week_2026(1), 2: _week_2026(2, overrides={1: 900.0})}
        boosted = power_v2.build_section(_snapshot(_healthy_2026(weekly=boosted_weekly)))
        before, after = _by_owner(base)["vet-01"], _by_owner(boosted)["vet-01"]
        assert after["components"]["all_play"] > before["components"]["all_play"]
        assert after["components"]["ppg"] > before["components"]["ppg"]
        assert after["powerScore"] > before["powerScore"]
        assert after["rank"] < before["rank"]

    def test_stronger_ros_is_a_higher_percentile_not_a_lower_rank_number(self):
        pct = power_v2._load_team_strength_percentiles()
        strongest = max(_ROS, key=_ROS.get)
        weakest = min(_ROS, key=_ROS.get)
        assert pct[strongest] > pct[weakest]
        assert 0.0 <= pct[weakest] < pct[strongest] <= 1.0

    def test_a_missing_ros_strength_is_unknown_not_the_bottom(self, monkeypatch):
        rows = [
            {"ownerId": oid, "teamRosStrength": (None if oid == "vet-03" else v)}
            for oid, v in _ROS.items()
        ]
        monkeypatch.setattr(power_v2, "_load_team_strength_rows", lambda *a, **k: list(rows))
        section = power_v2.build_section(_snapshot(_healthy_2026()))
        row = _by_owner(section)["vet-03"]
        assert row["components"]["team_ros_strength"] is None
        assert row["rank"] is not None  # still ranked on what IS measured
        assert any("vet-03" in m for m in section["missingInputs"])


# ── Movement: exactly week N-1's frozen publication ────────────────────


def _publish(week: int, ranks: dict[str, int], *, methodology: str) -> Path:
    ranking = [
        {"ownerId": oid, "displayName": oid, "rank": rank, "powerScore": 100.0 - rank}
        for oid, rank in ranks.items()
    ]
    path, created = power_snapshots.record_snapshot(
        league_key="testleague",
        section={
            "asOfSeason": "2026",
            "asOfWeek": week,
            "methodologyVersion": methodology,
            "currentRanking": ranking,
        },
        scoring_fingerprint="fp",
    )
    assert created
    return path


class TestMovementAgainstThePreviousOfficialPublication:
    def _live(self) -> dict:
        return power_v2.build_section(_snapshot(_healthy_2026()))

    def _live_ranks(self) -> dict[str, int]:
        return {r["ownerId"]: r["rank"] for r in self._live()["currentRanking"]}

    def test_up_down_and_unchanged_are_signed_correctly(self):
        live = self._live_ranks()
        order = sorted(live, key=live.get)
        up, down, same = order[2], order[4], order[0]  # live ranks 3, 5, 1
        prior = dict(live)
        prior[up], prior[down] = 5, 3
        _publish(1, prior, methodology=power_v2.METHODOLOGY_VERSION)
        rows = _by_owner(self._live())
        assert rows[up]["weekRankDelta"] == 2  # previous 5 -> current 3 = up 2
        assert rows[down]["weekRankDelta"] == -2  # previous 3 -> current 5 = down 2
        assert rows[same]["weekRankDelta"] == 0
        assert rows[same]["previousOfficialRank"] == 1

    def test_an_owner_absent_from_the_previous_publication_is_new(self):
        live = self._live_ranks()
        prior = {oid: r for oid, r in live.items() if oid != "new-blaine"}
        _publish(1, prior, methodology=power_v2.METHODOLOGY_VERSION)
        section = self._live()
        rows = _by_owner(section)
        assert rows["new-blaine"]["previousOfficialRank"] is None
        assert section["movementBaseline"]["status"] == "compared"

    def test_the_baseline_is_week_n_minus_1_never_the_latest_publication(self):
        live = self._live_ranks()
        _publish(1, live, methodology=power_v2.METHODOLOGY_VERSION)
        # Week 2 is also already published (e.g. under the old formula) with a
        # DIFFERENT order; the live Week 2 table must still move against Week 1.
        _publish(2, {oid: 13 - r for oid, r in live.items()}, methodology="old")
        section = self._live()
        assert section["movementBaseline"]["week"] == 1
        assert {r["weekRankDelta"] for r in section["currentRanking"]} == {0}

    def test_no_prior_publication_is_named_not_guessed(self):
        section = self._live()
        assert section["movementBaseline"] == {"status": "no_prior_publication", "week": 1}
        assert all(r["previousOfficialRank"] is None for r in section["currentRanking"])

    def test_the_live_calculation_never_writes_a_publication(self, _isolated):
        before = sorted(p.name for p in _isolated.rglob("*"))
        self._live()
        self._live()
        assert sorted(p.name for p in _isolated.rglob("*")) == before

    def test_a_methodology_change_leaves_history_frozen_and_named(self):
        live = self._live_ranks()
        week1 = _publish(1, live, methodology="canonical-power-2026.09-v1")
        frozen = week1.read_bytes()
        section = self._live()
        assert week1.read_bytes() == frozen
        baseline = section["movementBaseline"]
        assert baseline["methodologyVersion"] == "canonical-power-2026.09-v1"
        assert baseline["sameMethodology"] is False
        assert section["methodologyVersion"] == power_v2.METHODOLOGY_VERSION
        # Movement is still measured, not reset to NEW by the version change.
        assert all(r["previousOfficialRank"] is not None for r in section["currentRanking"])
        # And the history entry names its version.
        assert section["officialHistory"][0]["methodologyVersion"] == "canonical-power-2026.09-v1"
        assert json.loads(frozen)["week"] == 1
