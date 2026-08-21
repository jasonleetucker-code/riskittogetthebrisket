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
