"""V1-52 / #1020 — power_v2's PPG accumulator must not carry a prior
season's scoring into the current season's number.

``career_state`` in ``build_section`` (src/ros/power_v2.py) is accumulated
across EVERY season in the snapshot with no per-season reset, and its
``points``/``games`` fed ``ppg`` (and ``wins``/``losses`` fed
``wl_record``) directly — a CAREER average presented as the current
season's number.  ``recentAvg`` and ``all_play`` were already correctly
season-scoped, which is what proves the bug was in the accumulator, not
in the season concept generally.

This file builds a genuine two-season fixture — extreme, unmissable
season-1 scoring and known season-2 scoring with an explicit expected
season-2-only PPG — and proves the fix in the only way that discriminates:
if season 1's scoring alone determines who ranks first, the accumulator is
still contaminated; if season 2's scoring alone determines it, it isn't.

Uses ``tests.ros.test_power_v2._make_snapshot``'s pattern for
``roster_to_owner`` wiring (LOAD-BEARING — see that file's own comment:
without it every owner scores an identical neutral default and the
fixture measures nothing).  Verified directly against ``main`` before
writing this file, not assumed from an old note: current ``main``
already populates it correctly.
"""

from __future__ import annotations

import pytest

from src.public_league.identity import Manager, ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.ros import power_v2


def _matchup_week(scores: dict[int, float]) -> list[dict]:
    """``{roster_id: points}`` for one week -> matchup rows, paired 1v2."""
    rids = sorted(scores)
    return [{"roster_id": rid, "matchup_id": 1, "points": scores[rid]} for rid in rids]


def _season(
    year: str,
    league_id: str,
    rosters: list[dict],
    weekly_scores: dict[int, dict[int, float]],
    *,
    is_complete: bool,
) -> SeasonSnapshot:
    league = {
        "league_id": league_id,
        "season": year,
        "season_type": "regular",
        "settings": {"playoff_week_start": 15},
        "total_rosters": len(rosters),
    }
    if is_complete:
        league["status"] = "complete"
    return SeasonSnapshot(
        season=year,
        league_id=league_id,
        league=league,
        users=[],
        rosters=rosters,
        matchups_by_week={wk: _matchup_week(s) for wk, s in weekly_scores.items()},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


#: alpha = roster 1, bravo = roster 2 in both seasons (dynasty owners
#: persist across a league_id change year to year, which real Sleeper
#: history does — a different league_id per season is deliberate here,
#: not an oversight).
_ROSTERS = [{"roster_id": 1, "owner_id": "alpha"}, {"roster_id": 2, "owner_id": "bravo"}]

#: Season 2025 (complete): alpha blows bravo out every week, 500 vs 50 —
#: chosen so any leakage into season 2026's numbers is unmissable, not
#: a rounding-sized discrepancy.
_SEASON_2025_SCORES = {1: {1: 500.0, 2: 50.0}, 2: {1: 500.0, 2: 50.0}, 3: {1: 500.0, 2: 50.0}}

#: Season 2026 (in-progress, NOT complete): the roles flip. alpha's
#: known PPG is exactly 10.0; bravo's is exactly 200.0.
_SEASON_2026_SCORES = {1: {1: 8.0, 2: 190.0}, 2: {1: 10.0, 2: 200.0}, 3: {1: 12.0, 2: 210.0}}
_ALPHA_2026_PPG = 10.0
_BRAVO_2026_PPG = 200.0


def _registry_with(rosters: list[dict], *league_ids: str) -> ManagerRegistry:
    registry = ManagerRegistry()
    for r in rosters:
        oid = str(r["owner_id"])
        registry.by_owner_id.setdefault(oid, Manager(owner_id=oid, display_name=oid))
        for league_id in league_ids:
            registry.roster_to_owner[(league_id, int(r["roster_id"]))] = oid
    return registry


def _two_season_snapshot() -> PublicLeagueSnapshot:
    season_2025 = _season("2025", "L2025", _ROSTERS, _SEASON_2025_SCORES, is_complete=True)
    season_2026 = _season("2026", "L2026", _ROSTERS, _SEASON_2026_SCORES, is_complete=False)
    registry = _registry_with(_ROSTERS, "L2025", "L2026")
    # current_season is seasons[0] (PublicLeagueSnapshot's own contract,
    # NOT chronological) — 2026 must be first for _is_preseason to see
    # the right "current" season. build_section re-sorts seasons_sorted
    # chronologically itself for the accumulation walk, so this ordering
    # only affects current_season/_is_preseason, not the accumulator.
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-21T00:00:00Z",
        seasons=[season_2026, season_2025],
        managers=registry,
    )


def _row(rankings: list[dict], owner_id: str) -> dict:
    return next(r for r in rankings if r["ownerId"] == owner_id)


#: A separate, purpose-built fixture for the streak test. alpha/bravo's
#: main fixture above does NOT discriminate streak contamination: each
#: owner's season-2026 outcomes are already uniform (all-L for alpha,
#: all-W for bravo) AND season-2025's uniform outcome is the OPPOSITE
#: sign, so `_streak_score_from_outcomes`'s trailing-run search
#: naturally stops at the season boundary either way — the bug is real
#: but that fixture can't see it. Here "charlie" loses every game of
#: BOTH seasons (same sign on both sides of the boundary), so a
#: career-contaminated trailing run keeps counting straight through the
#: season boundary while the season-2-only run correctly stops at
#: season 2's own first game.
_STREAK_ROSTERS = [{"roster_id": 1, "owner_id": "charlie"}, {"roster_id": 2, "owner_id": "dave"}]
_STREAK_SEASON_2025_SCORES = {1: {1: 10.0, 2: 90.0}, 2: {1: 10.0, 2: 90.0}, 3: {1: 10.0, 2: 90.0}}
_STREAK_SEASON_2026_SCORES = {1: {1: 10.0, 2: 90.0}, 2: {1: 10.0, 2: 90.0}, 3: {1: 10.0, 2: 90.0}}


def _streak_snapshot() -> PublicLeagueSnapshot:
    season_2025 = _season(
        "2025", "L2025", _STREAK_ROSTERS, _STREAK_SEASON_2025_SCORES, is_complete=True
    )
    season_2026 = _season(
        "2026", "L2026", _STREAK_ROSTERS, _STREAK_SEASON_2026_SCORES, is_complete=False
    )
    registry = _registry_with(_STREAK_ROSTERS, "L2025", "L2026")
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-21T00:00:00Z",
        seasons=[season_2026, season_2025],
        managers=registry,
    )


class TestStreakAndLuckRegressionIsolation:
    """V1-52 follow-up (#1032's own residual comment): season_outcomes
    and expected_share_total fed streak/luck_regression from a career
    total the same way season_state's points/games fed ppg/wl_record
    before the original fix."""

    def test_streak_resets_at_the_season_boundary(self):
        """charlie loses every game of both seasons (uniform sign on
        both sides of the boundary). Season-2-only: 3 straight losses
        -> run=3 -> streak score = max(0.0, 0.5 - 3*0.10) = 0.2.
        Career-contaminated: 6 straight losses (the run keeps counting
        through the season boundary since season 2025 also ended in an
        unbroken loss streak) -> run=6 -> streak score floors at 0.0.
        """
        out = power_v2.build_section(_streak_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        charlie = _row(out["currentRanking"], "charlie")
        assert charlie["components"]["streak"] == pytest.approx(0.2), (
            "season-2-only losing streak is 3 games (score 0.2); a career-contaminated "
            "6-game streak would floor the score at 0.0"
        )

    def test_luck_regression_uses_season_2_only_expected_share(self):
        """alpha (from the main two-season fixture) went undefeated on
        all-play EXPECTATION in season 2025 (expectedShare 1.0 every
        week, blowing bravo out) and 0-for-3 on it in season 2026
        (expectedShare 0.0 every week, getting blown out). wins/games
        are already season-2-only (post the original V1-52 fix).

        Season-2-only expected_share_running = 0.0 (3 x 0.0) ->
        luck_delta = (0 - 0.0) / 3 = 0.0 -> luck_score = 0.5 (neutral,
        correct: alpha's season-2 results matched its season-2
        all-play expectation exactly).

        Career-contaminated expected_share_running = 3.0 (season
        2025's 3 x 1.0 leaking in) + 0.0 = 3.0 -> luck_delta =
        (0 - 3.0) / 3 = -1.0 -> luck_score clamps to 1.0 (maximally
        "unlucky", which is false: nothing about season 2025 has
        anything to do with alpha's season-2 luck).
        """
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        alpha = _row(out["currentRanking"], "alpha")
        assert alpha["components"]["luck_regression"] == pytest.approx(0.5), (
            "season-2-only luck score must be neutral (0.5); a career-contaminated "
            "expected-share total would clamp this to 1.0"
        )

    def test_both_lenses_agree_on_the_season_2_only_streak_and_luck(self):
        forward = power_v2.build_section(_streak_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
        results = power_v2.build_section(_streak_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        for out in (forward, results):
            charlie = _row(out["currentRanking"], "charlie")
            assert charlie["components"]["streak"] == pytest.approx(0.2)


class TestSeasonIsolation:
    """The core reproduction + fix proof."""

    def test_ppg_percentile_ranks_season_2_only_not_career(self):
        """The discriminating assertion. Correct (season-2-only): bravo
        (200 ppg) ranks ABOVE alpha (10 ppg) on the ppg component.
        Contaminated (career): alpha's career ppg (500*3+8+10+12)/6 = 255
        would rank ABOVE bravo's (50*3+190+200+210)/6 = 125 — a complete
        inversion driven entirely by a season that is not this one.
        """
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        alpha = _row(out["currentRanking"], "alpha")
        bravo = _row(out["currentRanking"], "bravo")
        assert bravo["components"]["ppg"] > alpha["components"]["ppg"], (
            "bravo's real season-2 PPG (200) is far above alpha's (10); "
            "the accumulator is still reading career totals if this fails"
        )
        assert bravo["rank"] < alpha["rank"], "bravo must rank ahead of alpha on season-2 form"

    def test_wl_record_is_season_2_only(self):
        """wl_record is NOT percentile-transformed — assert the raw
        value directly. Season 2026: alpha lost all 3, bravo won all 3.
        Career (contaminated): both would read 0.5 exactly (each won
        their own blowout season and lost the other) — a TIE that hides
        the real season-2 gap entirely."""
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        alpha = _row(out["currentRanking"], "alpha")
        bravo = _row(out["currentRanking"], "bravo")
        assert alpha["components"]["wl_record"] == 0.0
        assert bravo["components"]["wl_record"] == 1.0

    def test_both_lenses_agree_on_season_2_only_ppg(self):
        """Both lenses share one career_state/season_state build — the
        fix must not be lens-specific."""
        forward = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING)
        results = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        for out in (forward, results):
            alpha = _row(out["currentRanking"], "alpha")
            bravo = _row(out["currentRanking"], "bravo")
            assert bravo["components"]["ppg"] > alpha["components"]["ppg"]
            assert alpha["components"]["wl_record"] == 0.0
            assert bravo["components"]["wl_record"] == 1.0

    def test_recent_avg_is_exact_and_unaffected_by_the_fix(self):
        """recentAvg was ALREADY correctly season-scoped — regression
        check with real numbers, not just 'still passes'. 3 games played
        in season 2026, _RECENT_WINDOW is 3, so recentAvg == season PPG
        here exactly."""
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        alpha = _row(out["currentRanking"], "alpha")
        bravo = _row(out["currentRanking"], "bravo")
        assert bravo["components"]["recent"] > alpha["components"]["recent"]

    def test_all_play_is_unaffected_by_the_fix(self):
        """all_play was ALREADY correctly season-scoped (overwritten,
        not accumulated, every week). Season 2026's last week: bravo
        beat alpha, so bravo's all-play share is 1.0 and alpha's is 0.0."""
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        alpha = _row(out["currentRanking"], "alpha")
        bravo = _row(out["currentRanking"], "bravo")
        assert bravo["components"]["all_play"] == 1.0
        assert alpha["components"]["all_play"] == 0.0

    def test_trend_series_week_1_of_season_2_is_not_contaminated(self):
        """The task's own strongest edge case: week 1 of season 2026,
        BEFORE most of season 2026 has even happened, must still show
        only season-2026 points — not season-2025's totals plus one
        week. With the bug this is where the contamination is largest
        RELATIVE to the real signal (1 week of real data vs 3 weeks of
        career baggage)."""
        out = power_v2.build_section(_two_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        trend = out["trend"]
        weeks = trend["weeks"]
        week1_2026_idx = next(
            i for i, w in enumerate(weeks) if w["season"] == "2026" and w["week"] == 1
        )
        alpha_week1 = trend["seriesByOwner"]["alpha"][week1_2026_idx]
        bravo_week1 = trend["seriesByOwner"]["bravo"][week1_2026_idx]
        # Real ranks must already reflect week 1's own result (bravo 190
        # vs alpha 8), not 3 weeks of alpha's 500-point season carried
        # in from 2025.
        assert alpha_week1["rank"] is not None and bravo_week1["rank"] is not None
        assert bravo_week1["rank"] < alpha_week1["rank"]


class TestMidRejoinFallback:
    """The design correction this investigation found: career_state
    itself must NOT be reset, because _enumerate_owner_ids's historical
    fallback depends on its keys surviving past the season loop."""

    def test_a_historical_only_owner_still_appears_with_a_real_zero_ppg(self):
        """charlie played in 2025 only — absent from 2026's rosters
        entirely (the mid-rejoin / departed-then-returned shape
        _enumerate_owner_ids's docstring names). Must still appear
        (career_state.keys() fallback, untouched by this fix) with a
        REAL 0.0 ppg (season_state has nothing for him this season) —
        distinct from the unrankable/refusal None case."""
        rosters_2025 = _ROSTERS + [{"roster_id": 3, "owner_id": "charlie"}]
        scores_2025 = {wk: {**s, 3: 75.0} for wk, s in _SEASON_2025_SCORES.items()}
        season_2025 = _season("2025", "L2025", rosters_2025, scores_2025, is_complete=True)
        season_2026 = _season("2026", "L2026", _ROSTERS, _SEASON_2026_SCORES, is_complete=False)
        registry = _registry_with(rosters_2025, "L2025")
        registry.roster_to_owner.update(
            {
                (str_league, rid): oid
                for str_league, rid, oid in (("L2026", 1, "alpha"), ("L2026", 2, "bravo"))
            }
        )
        registry.by_owner_id.setdefault(
            "charlie", Manager(owner_id="charlie", display_name="charlie")
        )
        snapshot = PublicLeagueSnapshot(
            root_league_id="L2026",
            generated_at="2026-08-21T00:00:00Z",
            seasons=[season_2026, season_2025],
            managers=registry,
        )
        out = power_v2.build_section(snapshot, lens=power_v2.LENS_RESULTS_ONLY)
        owner_ids = {r["ownerId"] for r in out["currentRanking"]}
        assert "charlie" in owner_ids, "mid-rejoin/departed owner dropped from the table"
        charlie = _row(out["currentRanking"], "charlie")
        assert charlie["rank"] is not None, "a real zero must still be rankable, not refused"
        assert charlie["components"]["wl_record"] == 0.0


class TestUnrankableUnaffected:
    """The refusal path is orthogonal to season_state — confirm the fix
    did not touch it. Mirrors tests/ros/test_power_unrankable.py's own
    proven fixture shape (forward-looking + preseason is the reachable
    every-component-missing state) rather than inventing a new one."""

    def test_preseason_forward_looking_still_refuses_rather_than_zero(self):
        rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2)]
        season = _season("2026", "L2026", rosters, {}, is_complete=False)
        registry = _registry_with(rosters, "L2026")
        snapshot = PublicLeagueSnapshot(
            root_league_id="L2026",
            generated_at="2026-08-21T00:00:00Z",
            seasons=[season],
            managers=registry,
        )
        out = power_v2.build_section(snapshot, lens=power_v2.LENS_FORWARD_LOOKING)
        assert out["preseason"] is True
        assert out.get("unrankable"), "every component missing must refuse, not publish an order"
        for row in out["currentRanking"]:
            assert row["powerScore"] is None
            assert row["rank"] is None


#: V1-52 follow-up 2 — the PRODUCTION shape, which no fixture above has:
#: a scoreless CURRENT season sitting after prior scored seasons. Every
#: other two-season fixture in this file gives 2026 real scores, so the
#: retired ``season is seasons_sorted[-1]`` guard fired and the defect was
#: invisible. Here 2026 has no matchups at all — exactly what production
#: reports in preseason (``weeksPlayed 0``) — so ``seasons_sorted[-1]`` is
#: a season the accumulation loop ``continue``s straight past.
#:
#: 2025 runs FOUR weeks against ``_RECENT_WINDOW = 3`` deliberately: the
#: trailing window must drop week 1, so a buffer that never slid would
#: give alpha 265.0 rather than 20.0 and the test would catch that too.
_RECENT_ROSTERS = [{"roster_id": 1, "owner_id": "alpha"}, {"roster_id": 2, "owner_id": "bravo"}]
_RECENT_SEASON_2025_SCORES = {
    1: {1: 1000.0, 2: 0.0},
    2: {1: 10.0, 2: 100.0},
    3: {1: 20.0, 2: 200.0},
    4: {1: 30.0, 2: 300.0},
}
#: Trailing-3 means over weeks 2-4, week 1 having slid out of the window.
_ALPHA_RECENT = 20.0
_BRAVO_RECENT = 200.0


def _preseason_shape_snapshot() -> PublicLeagueSnapshot:
    """Prior scored season + scoreless current season."""
    season_2025 = _season(
        "2025", "L2025", _RECENT_ROSTERS, _RECENT_SEASON_2025_SCORES, is_complete=True
    )
    season_2026 = _season("2026", "L2026", _RECENT_ROSTERS, {}, is_complete=False)
    registry = _registry_with(_RECENT_ROSTERS, "L2025", "L2026")
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-21T00:00:00Z",
        seasons=[season_2026, season_2025],
        managers=registry,
    )


class TestRecentFormSurvivesAScorelessCurrentSeason:
    """``recent`` carries 0.12 of ``WEIGHTS`` — 21.8% of the results-only
    score, whose active weights sum to 0.55. Under the retired binding it
    was a constant 0.5 for every owner in every preseason, with a "0.0"
    recentAvg rendered as though it had been observed."""

    def test_the_fixture_really_is_the_preseason_shape(self):
        """Non-vacuity: if 2026 ever gains scores this fixture stops
        discriminating, exactly as the older ones already fail to."""
        snap = _preseason_shape_snapshot()
        newest = max(s.season for s in snap.seasons)
        assert newest == "2026"
        scoreless = next(s for s in snap.seasons if s.season == "2026")
        assert not scoreless.matchups_by_week, "2026 must be scoreless for this to test anything"

    def test_recent_avg_is_the_last_scored_seasons_trailing_window(self):
        out = power_v2.build_section(_preseason_shape_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        assert _row(rows, "alpha")["components"]["recentAvg"] == pytest.approx(_ALPHA_RECENT)
        assert _row(rows, "bravo")["components"]["recentAvg"] == pytest.approx(_BRAVO_RECENT)

    def test_recent_percentiles_are_measured_not_a_shared_default(self):
        out = power_v2.build_section(_preseason_shape_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        alpha = _row(rows, "alpha")["components"]["recent"]
        bravo = _row(rows, "bravo")["components"]["recent"]
        assert {alpha, bravo} != {0.5}, (
            "every owner sharing the 0.5 midpoint is the signature of an "
            "unmeasured component, not a real tie"
        )
        assert bravo > alpha

    def test_all_play_also_survives_the_scoreless_season(self):
        """``last_season_allplay_share`` resets alongside it, so the two
        cannot disagree about which season they describe.

        Non-vacuity (V1-52 residual): BOTH of this fixture's owners hold
        an ``allplay`` key, so the bravo>alpha comparison alone survived
        the retired ``.get(oid, 0.0)`` default untouched.  The
        absent-owner fixture is what actually exercises the default arm:
        carol has no key in the last scored season's share map, and
        unmeasured must surface as None -- never the 0.0 the default
        would coerce."""
        out = power_v2.build_section(_preseason_shape_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        shares = {r["ownerId"]: r["components"]["all_play"] for r in rows}
        assert shares["bravo"] > shares["alpha"]
        absent = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        carol = _row(absent["currentRanking"], "carol")["components"]
        assert carol["all_play"] is None, carol["all_play"]

    def test_recent_still_carries_its_declared_weight(self):
        """Guards the other direction: a fix that silently dropped the
        component would also stop it being a constant."""
        out = power_v2.build_section(_preseason_shape_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        assert out["effectiveWeights"].get("recent") == power_v2.WEIGHTS["recent"]


# ── Missing is never zero (owner invariant) ────────────────────────────
#
# The first repair in this file bound recent form to the last SCORED
# season. That fixed WHICH season it describes but left the unmeasured
# case coerced: ``recent = ... if rb else 0.0``, which every owner shared,
# so ``_percentile`` returned a confident 0.5 for all of them. Per the
# owner invariant, unmeasured must stay unmeasured -- never 0.0, never a
# bottom percentile, never a neutral 0.5 kept merely so a number exists.
#
# Two distinct cases, deliberately tested apart because they resolve
# through different mechanisms:
#   (a) NOBODY has recent form  -> the component is unmeasurable
#       league-wide and drops out of the weight budget entirely.
#   (b) ONE owner lacks it while others have it -> the component is
#       measurable, but THIS owner's value is unknown.


def _no_scored_weeks_snapshot() -> PublicLeagueSnapshot:
    """Case (a): a league whose every season is scoreless."""
    rosters = [{"roster_id": 1, "owner_id": "alpha"}, {"roster_id": 2, "owner_id": "bravo"}]
    season_2025 = _season("2025", "L2025", rosters, {}, is_complete=True)
    season_2026 = _season("2026", "L2026", rosters, {}, is_complete=False)
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-25T00:00:00Z",
        seasons=[season_2026, season_2025],
        managers=_registry_with(rosters, "L2025", "L2026"),
    )


#: Case (b): three owners, but ``carol`` sits out the last SCORED season
#: (2025). She played 2024, so a career-scoped or unreset accumulator
#: would hand her a stale 2024 recent average -- which is the other way
#: this can go wrong, and is why she has real 2024 scores rather than
#: none at all.
_ABSENT_ROSTERS_2024 = [
    {"roster_id": 1, "owner_id": "alpha"},
    {"roster_id": 2, "owner_id": "bravo"},
    {"roster_id": 3, "owner_id": "carol"},
]
_ABSENT_ROSTERS_2025 = [
    {"roster_id": 1, "owner_id": "alpha"},
    {"roster_id": 2, "owner_id": "bravo"},
]
_ABSENT_2024_SCORES = {
    1: {1: 100.0, 2: 110.0, 3: 900.0},
    2: {1: 100.0, 2: 110.0, 3: 900.0},
    3: {1: 100.0, 2: 110.0, 3: 900.0},
}
_ABSENT_2025_SCORES = {
    1: {1: 120.0, 2: 130.0},
    2: {1: 121.0, 2: 131.0},
    3: {1: 122.0, 2: 132.0},
}


def _owner_absent_from_last_scored_season_snapshot() -> PublicLeagueSnapshot:
    season_2024 = _season(
        "2024", "L2024", _ABSENT_ROSTERS_2024, _ABSENT_2024_SCORES, is_complete=True
    )
    season_2025 = _season(
        "2025", "L2025", _ABSENT_ROSTERS_2025, _ABSENT_2025_SCORES, is_complete=True
    )
    season_2026 = _season("2026", "L2026", _ABSENT_ROSTERS_2024, {}, is_complete=False)
    registry = ManagerRegistry()
    for r in _ABSENT_ROSTERS_2024:
        oid = str(r["owner_id"])
        registry.by_owner_id.setdefault(oid, Manager(owner_id=oid, display_name=oid))
        registry.roster_to_owner[("L2024", int(r["roster_id"]))] = oid
        registry.roster_to_owner[("L2026", int(r["roster_id"]))] = oid
    for r in _ABSENT_ROSTERS_2025:
        registry.roster_to_owner[("L2025", int(r["roster_id"]))] = str(r["owner_id"])
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-25T00:00:00Z",
        seasons=[season_2026, season_2025, season_2024],
        managers=registry,
    )


class TestUnmeasuredRecentFormStaysUnknown:
    """Owner invariant: missing/unknown != zero."""

    # ── (a) nothing measured anywhere ──────────────────────────────────

    def test_no_scored_weeks_drops_recent_from_the_weight_budget(self):
        out = power_v2.build_section(_no_scored_weeks_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        assert "recent" not in (out["effectiveWeights"] or {}), (
            "an input nothing can supply must renormalise away, not be "
            "scored at a stand-in value"
        )

    def test_no_scored_weeks_publishes_null_not_zero_or_neutral(self):
        out = power_v2.build_section(_no_scored_weeks_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        for row in out["currentRanking"]:
            c = row["components"]
            assert c["recent"] is None, c["recent"]
            assert c["recentAvg"] is None, c["recentAvg"]

    # ── (b) one owner absent from the last scored season ───────────────

    def test_the_absent_owner_really_is_absent_and_the_others_are_not(self):
        """Non-vacuity: if carol ever gained 2025 games, or the others
        lost theirs, everything below would pass for the wrong reason."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        rows = out["currentRanking"]
        assert {r["ownerId"] for r in rows} == {"alpha", "bravo", "carol"}
        assert _row(rows, "alpha")["components"]["recentAvg"] is not None
        assert _row(rows, "bravo")["components"]["recentAvg"] is not None

    def test_the_absent_owners_recent_is_null_not_zero_or_neutral(self):
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        carol = _row(out["currentRanking"], "carol")["components"]
        assert carol["recent"] is None, carol["recent"]
        assert carol["recentAvg"] is None, carol["recentAvg"]

    def test_the_absent_owner_does_not_inherit_a_stale_prior_season(self):
        """carol's 900.0-per-week 2024 must not resurface as 2025 form."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        assert _row(out["currentRanking"], "carol")["components"]["recentAvg"] != 900.0

    def test_the_absent_owner_is_scored_without_the_unknown_component(self):
        """Not deflated by a zero, and not credited with a midpoint --
        the weight is simply not applied to this row."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        rows = out["currentRanking"]
        carol = _row(rows, "carol")
        assert "recent" not in carol["weightsApplied"]
        assert carol["powerScore"] is not None
        # The component IS measurable league-wide, so it stays in the
        # section budget and the owners who have it keep their weight.
        assert "recent" in out["effectiveWeights"]
        assert "recent" in _row(rows, "alpha")["weightsApplied"]

    def test_a_null_component_never_reaches_the_weighted_sum(self):
        """Structural: every weight a row applies has a real value behind
        it, so no stand-in can be multiplied in."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        for row in out["currentRanking"]:
            for key in row["weightsApplied"]:
                assert row["components"].get(key) is not None, (row["ownerId"], key)


class TestUnmeasuredAllPlayStaysUnknown:
    """Owner invariant, all_play edition (V1-52 residual): the ``recent``
    repair above left its four-lines-later neighbour coerced --
    ``state["allplay"].get(oid, 0.0)``.  all_play is an expected share on
    [0, 1] consumed raw (never percentiled), so the 0.0 default did not
    even get recent's every-owner-ties-at-0.5 camouflage: it scored a
    missing owner as the league's WORST all-play performer, at weight
    0.08.  Same two cases as recent, resolved through the same two
    mechanisms."""

    # ── (a) nothing measured anywhere ──────────────────────────────────

    def test_no_scored_weeks_drops_all_play_from_the_weight_budget(self):
        out = power_v2.build_section(_no_scored_weeks_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        assert "all_play" not in (out["effectiveWeights"] or {}), (
            "an input nothing can supply must renormalise away, not be "
            "scored at a stand-in value"
        )
        assert "all_play" in out["missingInputs"]

    def test_no_scored_weeks_publishes_null_not_zero(self):
        out = power_v2.build_section(_no_scored_weeks_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        for row in out["currentRanking"]:
            assert row["components"]["all_play"] is None, row["components"]["all_play"]

    # ── (b) one owner absent from the last scored season ───────────────

    def test_the_absent_owners_all_play_is_null_not_zero(self):
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        rows = out["currentRanking"]
        carol = _row(rows, "carol")["components"]
        assert carol["all_play"] is None, carol["all_play"]
        # The measured owners keep real shares -- the null is carol's,
        # not a league-wide wipe.
        assert _row(rows, "alpha")["components"]["all_play"] is not None
        assert _row(rows, "bravo")["components"]["all_play"] is not None

    def test_the_absent_owner_does_not_inherit_a_stale_prior_season(self):
        """carol dominated 2024's all-play (900 vs 100/110 every week,
        expectedShare 1.0); none of that may resurface as 2025 form."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        assert _row(out["currentRanking"], "carol")["components"]["all_play"] != 1.0

    def test_the_absent_owner_is_scored_without_the_unknown_component(self):
        """Not deflated by a worst-in-league zero -- the weight is simply
        not applied to this row."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        rows = out["currentRanking"]
        carol = _row(rows, "carol")
        assert "all_play" not in carol["weightsApplied"]
        assert carol["powerScore"] is not None
        # The component IS measurable league-wide, so it stays in the
        # section budget and the owners who have it keep their weight.
        assert "all_play" in out["effectiveWeights"]
        assert "all_play" in _row(rows, "alpha")["weightsApplied"]

    def test_a_null_all_play_never_reaches_the_weighted_sum(self):
        """Mirror of recent's structural sweep, made discriminating for
        all_play: that sweep passed on the PRE-fix code because the
        coerced 0.0 is not None -- the weight WAS applied, to a stand-in.
        This version additionally pins that the absent owner applies no
        all_play weight at all, so there is no value, real or invented,
        for it to multiply."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY
        )
        for row in out["currentRanking"]:
            for key in row["weightsApplied"]:
                assert row["components"].get(key) is not None, (row["ownerId"], key)
        assert "all_play" not in _row(out["currentRanking"], "carol")["weightsApplied"]

    def test_the_refusal_path_serialises_the_unknown_share_as_null(self):
        """Forward-looking + preseason with no team-strength file is the
        every-component-dropped refusal state (the same reachable shape
        tests/ros/test_power_unrankable.py pins).  carol's unmeasured
        share must serialise as null there too: the pre-fix ``round()``
        call would TypeError on None, and a coerced 0.0 would publish a
        confident worst-in-league share inside the branch whose whole
        point is refusing to invent numbers."""
        out = power_v2.build_section(
            _owner_absent_from_last_scored_season_snapshot(), lens=power_v2.LENS_FORWARD_LOOKING
        )
        assert out.get("unrankable"), "fixture must land on the refusal path"
        rows = out["currentRanking"]
        assert _row(rows, "carol")["components"]["all_play"] is None
        assert _row(rows, "alpha")["components"]["all_play"] is not None


# ── All three season resets, pinned on one three-season fixture ────────
#
# This file's three repairs each reset a different accumulator at the top
# of every SCORED season:
#
#   1. season_state                          -> ppg, wl_record      (#1032)
#   2. season_outcomes, expected_share_total -> streak, luck_reg    (#1059)
#   3. last_season_recent,                   -> recent, all_play    (this
#      last_season_allplay_share                                     unit)
#
# The two-season fixtures above can only show that the LAST season wins.
# A third season is what proves the reset happens on EVERY scored season
# rather than once at the end -- an accumulator reset only on the final
# iteration would pass every earlier test in this file.
#
# 2024: dave is overwhelming. 2025: the roles invert completely. 2026 is
# scoreless. So every component must describe 2025, and any accumulator
# still carrying 2024 flips at least one of them the wrong way.
_THREE_ROSTERS = [{"roster_id": 1, "owner_id": "dave"}, {"roster_id": 2, "owner_id": "erin"}]
_THREE_2024 = {
    1: {1: 900.0, 2: 10.0},
    2: {1: 900.0, 2: 10.0},
    3: {1: 900.0, 2: 10.0},
}
_THREE_2025 = {
    1: {1: 20.0, 2: 200.0},
    2: {1: 20.0, 2: 200.0},
    3: {1: 20.0, 2: 200.0},
}


def _three_season_snapshot() -> PublicLeagueSnapshot:
    season_2024 = _season("2024", "L2024", _THREE_ROSTERS, _THREE_2024, is_complete=True)
    season_2025 = _season("2025", "L2025", _THREE_ROSTERS, _THREE_2025, is_complete=True)
    season_2026 = _season("2026", "L2026", _THREE_ROSTERS, {}, is_complete=False)
    return PublicLeagueSnapshot(
        root_league_id="L2026",
        generated_at="2026-08-25T00:00:00Z",
        seasons=[season_2026, season_2025, season_2024],
        managers=_registry_with(_THREE_ROSTERS, "L2024", "L2025", "L2026"),
    )


class TestEverySeasonResetHoldsAcrossThreeSeasons:
    def test_the_fixture_really_inverts_between_the_two_scored_seasons(self):
        """Non-vacuity: if 2024 and 2025 agreed, contamination would be
        undetectable and every assertion below would pass for free."""
        assert _THREE_2024[1][1] > _THREE_2024[1][2]
        assert _THREE_2025[1][1] < _THREE_2025[1][2]

    def test_reset_one_ppg_and_wl_record_describe_the_last_scored_season(self):
        out = power_v2.build_section(_three_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        dave, erin = _row(rows, "dave"), _row(rows, "erin")
        # 2025-only PPG is exactly 20.0 / 200.0; carrying 2024 would give
        # dave 613.33 and invert both of these.
        assert dave["components"]["pointsPerGame"] == pytest.approx(20.0)
        assert erin["components"]["pointsPerGame"] == pytest.approx(200.0)
        assert dave["components"]["wl_record"] == pytest.approx(0.0)
        assert erin["components"]["wl_record"] == pytest.approx(1.0)

    def test_reset_two_streak_and_luck_describe_the_last_scored_season(self):
        out = power_v2.build_section(_three_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        # dave lost all three 2025 games. A career-scoped run would start
        # from three 2024 WINS and the trailing streak would not be a
        # clean three-game losing run.
        assert _row(rows, "dave")["components"]["streak"] == pytest.approx(0.2)
        assert _row(rows, "erin")["components"]["streak"] == pytest.approx(0.8)
        # luck_regression is (wins - expected_share) / games, and both
        # halves must come from the same season for it to mean anything.
        assert _row(rows, "dave")["components"]["luck_regression"] == pytest.approx(0.5)
        assert _row(rows, "erin")["components"]["luck_regression"] == pytest.approx(0.5)

    def test_reset_three_recent_and_all_play_describe_the_last_scored_season(self):
        out = power_v2.build_section(_three_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        rows = out["currentRanking"]
        dave, erin = _row(rows, "dave"), _row(rows, "erin")
        # Trailing-3 over 2025 only. dave's 2024 average was 900.0.
        assert dave["components"]["recentAvg"] == pytest.approx(20.0)
        assert erin["components"]["recentAvg"] == pytest.approx(200.0)
        # all_play is the last scored week's expected share, and 2025's
        # last week has erin ahead.
        assert erin["components"]["all_play"] > dave["components"]["all_play"]

    def test_the_middle_season_is_not_the_one_being_described(self):
        """Guards the specific failure a third season exists to catch: an
        accumulator reset only on the final loop iteration would leave
        every component describing 2024+2025 combined rather than 2025."""
        out = power_v2.build_section(_three_season_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
        dave = _row(out["currentRanking"], "dave")["components"]
        combined_ppg = (900.0 * 3 + 20.0 * 3) / 6
        assert dave["pointsPerGame"] != pytest.approx(combined_ppg)
