"""V1-95 / ``C9-AWARD-01`` — awards may not exist before games are played.

THE DEFECT, reproduced before it was repaired.

``_season_canonical_awards`` gated on ``if not standings: return []``.
``standings`` is built from the season's ROSTERS, so it is non-empty as soon
as a league exists — which is not the same statement as "games have been
played".  Sleeper flips dynasty leagues to ``in_season`` in the offseason,
months before NFL Week 1, so a league with twelve 0-0-0 rosters and no
matchups at all produced a full award board.

Measured on the fixture below (rosters present, zero games anywhere):

    champion                emitted
    regular_season_crown    record "0-0"
    points_king             pointsFor 0.0
    manager_of_the_year     compositeScore 0.3, finishRank 1
    + 1 finalists race

matching audit W19-F004 on the live payload: *"Points King: Jason, 0.0 PF",
"Regular-Season Crown: Jason, 0-0", "League MVP: Justin Jefferson, 0.0
VORP"*.  The live board showed eight; this fixture is smaller and shows four,
so the COUNT is fixture-dependent and the CLASS is what these tests pin.

THE REPAIR REUSES THE RULE THAT ALREADY EXISTED.  ``build_section`` already
knew what "has actually begun" means — ``_has_begun`` / ``_has_played_games``
— and already used it to pick the FEATURED season, which is why last
season's board correctly stayed featured all offseason.  It was a closure, so
it governed only the highlight and not generation.  It is module-level now
and one rule decides both.  **No second season-start rule was invented.**

``hasPlayerScoring`` is deliberately untouched: player-level scoring is a
NARROWER signal than "has begun" (a week can be scored at team level before
every ``players_points`` map lands), so it stays a diagnostic and decides
nothing.
"""

from __future__ import annotations

import copy

import pytest

from src.public_league import awards
from tests.public_league.fixtures import build_test_snapshot


def _zero_settings(roster: dict) -> dict:
    roster = copy.deepcopy(roster)
    settings = dict(roster.get("settings") or {})
    settings.update(
        wins=0,
        losses=0,
        ties=0,
        fpts=0,
        fpts_decimal=0,
        fpts_against=0,
        fpts_against_decimal=0,
        rank=0,
    )
    roster["settings"] = settings
    return roster


@pytest.fixture
def snapshot_with_unplayed_season():
    """A snapshot whose newest season exists but has played nothing.

    The league_id is deliberately KEPT so the manager registry still resolves
    owners — a season whose owners cannot be resolved produces empty standings
    and would short-circuit the very code path under test, passing for the
    wrong reason.
    """
    snapshot = build_test_snapshot()
    unplayed = copy.deepcopy(snapshot.seasons[0])
    unplayed.season = "2026"
    unplayed.league = dict(unplayed.league)
    unplayed.league["status"] = "in_season"  # is_complete derives from this
    unplayed.league["season"] = "2026"
    unplayed.matchups_by_week = {}
    unplayed.rosters = [_zero_settings(r) for r in unplayed.rosters]
    snapshot.seasons.insert(0, unplayed)
    return snapshot


def _row(section: dict, season: str) -> dict:
    return next(r for r in section["bySeason"] if r["season"] == season)


# ── 1. zero games → zero manufactured awards ──────────────────────────


def test_a_season_with_zero_games_manufactures_no_awards(snapshot_with_unplayed_season):
    section = awards.build_section(snapshot_with_unplayed_season)
    row = _row(section, "2026")

    assert row["awards"] == [], (
        f"awards manufactured from a season with no games: "
        f"{[a.get('key') for a in row['awards']]}"
    )
    assert row["finalists"] == {}


def test_the_named_defect_awards_are_specifically_gone(snapshot_with_unplayed_season):
    """Non-vacuity, aimed at the audit's own examples.

    Guards against a repair that empties the board for some unrelated reason:
    these three keys are the ones W19-F004 named, and the fixture provably
    produces them without the gate.
    """
    section = awards.build_section(snapshot_with_unplayed_season)
    keys = {a.get("key") for a in _row(section, "2026")["awards"]}
    assert not keys & {"regular_season_crown", "points_king", "manager_of_the_year", "champion"}


# ── 5. explicit refusal, not an ambiguous empty success ───────────────


def test_no_games_is_an_explicit_refusal_not_an_empty_success(snapshot_with_unplayed_season):
    """ "Nothing has been played" and "the computation found nothing" are
    different statements and must not render identically."""
    section = awards.build_section(snapshot_with_unplayed_season)
    row = _row(section, "2026")

    assert "awardsUnavailable" in row, "an empty award list with no reason is the ambiguous state"
    assert row["awardsUnavailable"]["reason"] == awards.AWARDS_UNAVAILABLE_NO_GAMES
    assert row["awardsUnavailable"]["detail"]


# ── 6. hasPlayerScoring survives as a diagnostic ──────────────────────


def test_has_player_scoring_is_still_published(snapshot_with_unplayed_season):
    """It survives on EVERY row, including the refused one.

    Note it is not asserted to be ``True`` for 2025: this fixture's matchups
    carry team ``points`` without ``players_points``, so 2025 is legitimately
    ``False`` while having played. That is exactly why this field could not
    have been the gate — it is a narrower signal than "has begun".
    """
    section = awards.build_section(snapshot_with_unplayed_season)
    for season in ("2026", "2025", "2024"):
        assert "hasPlayerScoring" in _row(section, season)
    assert _row(section, "2026")["hasPlayerScoring"] is False


# ── 2. the first real scored game unlocks awards ──────────────────────


def test_one_real_scored_game_lets_awards_appear(snapshot_with_unplayed_season):
    """The gate must OPEN, not merely stay shut.

    Without this a repair that suppressed awards unconditionally would pass
    every other test in this file.
    """
    snapshot = snapshot_with_unplayed_season
    unplayed = snapshot.seasons[0]
    assert awards.build_section(snapshot)["bySeason"][0]["awards"] == []

    played = copy.deepcopy(snapshot.seasons[1].matchups_by_week.get(1) or [])
    assert played, "fixture has no week-1 matchups to borrow"
    unplayed.matchups_by_week = {1: played}

    row = _row(awards.build_section(snapshot), "2026")
    assert row["awards"], "a season with a real scored game still produced no awards"
    assert "awardsUnavailable" not in row


# ── 3. completed historical seasons are untouched ─────────────────────


def test_completed_seasons_are_unchanged_by_the_gate():
    """Byte-level: the gate must not perturb a season that has played."""
    before = awards.build_section(build_test_snapshot())

    snapshot = build_test_snapshot()
    unplayed = copy.deepcopy(snapshot.seasons[0])
    unplayed.season = "2026"
    unplayed.league = dict(unplayed.league)
    unplayed.league["status"] = "in_season"
    unplayed.matchups_by_week = {}
    unplayed.rosters = [_zero_settings(r) for r in unplayed.rosters]
    snapshot.seasons.insert(0, unplayed)
    after = awards.build_section(snapshot)

    # Compared on the award KEYS and the finalists shape, not on whole dicts.
    # ``best_rebuild`` is decided by a compositeScore that TIES at 1.1 between
    # two owners in this fixture, and the winner moves when a season is
    # inserted ahead of it — a pre-existing incidental-ordering tiebreak of
    # the same family as the ROS standings defect, unrelated to this gate and
    # deliberately NOT repaired inside a V1-95-scoped unit. Asserting whole
    # dicts here would pin that instability into this test instead of
    # reporting it.
    for season in ("2025", "2024"):
        b, a = _row(before, season), _row(after, season)
        assert [x["key"] for x in a["awards"]] == [
            x["key"] for x in b["awards"]
        ], f"{season} award set moved"
        assert sorted(a["finalists"]) == sorted(b["finalists"]), f"{season} finalists moved"
        assert "awardsUnavailable" not in a
    assert _row(after, "2025")["awards"], "non-vacuity: 2025 must actually have awards"


# ── 4. the prior season stays featured through the offseason ──────────


def test_the_prior_season_stays_featured_until_the_new_one_begins(snapshot_with_unplayed_season):
    """Pre-existing behaviour this unit must PRESERVE, not just not break.

    ``_has_begun`` already governed featuring; hoisting it out of the closure
    must leave that answer identical.
    """
    section = awards.build_section(snapshot_with_unplayed_season)
    assert section["featuredSeason"] == "2025"
    assert section["currentSeason"] == "2025"
    assert section["upcomingSeason"] == "2026"
    assert section["awardRaces"] or section["awardRaces"] == []
    assert _row(section, "2025")["awards"], "last season's board went empty in the offseason"


def test_featuring_moves_once_the_new_season_plays(snapshot_with_unplayed_season):
    snapshot = snapshot_with_unplayed_season
    played = copy.deepcopy(snapshot.seasons[1].matchups_by_week.get(1) or [])
    snapshot.seasons[0].matchups_by_week = {1: played}
    section = awards.build_section(snapshot)
    assert section["featuredSeason"] == "2026"


# ── the rule has ONE owner ────────────────────────────────────────────


def test_there_is_only_one_season_start_rule():
    """Structural. The brief for this unit was explicit: reuse the existing
    evidence, do not invent a second season-start rule.

    ``_has_begun`` must be the only thing the generation gate consults, and
    it must be module-level (a closure cannot be shared, which is how the
    featuring rule and the generation rule diverged in the first place)."""
    import ast
    import inspect

    assert callable(awards._has_begun)
    assert callable(awards._has_played_games)

    tree = ast.parse(inspect.getsource(awards.build_section).lstrip())
    outer = tree.body[0]
    nested = [n.name for n in ast.walk(outer) if isinstance(n, ast.FunctionDef) and n is not outer]
    assert not nested, f"build_section re-nested a season-start closure: {nested}"
