"""The realistic free-agent pool over a synthetic dynasty_main-shaped league."""

from __future__ import annotations

import pytest

from src.bestball.replacement import waiver_candidates
from tests.fixtures.bestball.synthetic_league import (
    AUCTION_ROOKIES,
    DYNASTY_MAIN_SLOTS,
    ROSTER_SIZE,
    TEAMS,
    build_league,
    ppg_lookup_for,
    rostered_ids,
)


@pytest.fixture(scope="module")
def league():
    return build_league()


def _pool(league, params, **kw):
    return waiver_candidates(
        league["contract"],
        kw.pop("rostered", rostered_ids(league)),
        season=2026,
        scoring_settings={"rec": 1.0},
        params=params,
        ppg_lookup=kw.pop("lookup", ppg_lookup_for(league["ppg"])),
        **kw,
    )


def test_league_is_dynasty_main_shaped(league):
    assert len(DYNASTY_MAIN_SLOTS) == 21
    teams = league["contract"]["sleeper"]["teams"]
    assert len(teams) == TEAMS == 12
    assert all(len(t["playerIds"]) == ROSTER_SIZE == 58 for t in teams)


def test_pool_excludes_every_rostered_player(league, params):
    pool = _pool(league, params)
    taken = set(rostered_ids(league))
    assert pool.state == "available"
    assert pool.candidates
    assert not {c.player_id for c in pool.candidates} & taken
    assert pool.basis["excluded"]["rostered"] == TEAMS * ROSTER_SIZE


def test_rostered_is_league_wide_even_when_the_caller_passes_nothing(league, params):
    # src.draft.context.league_rostered_keys reads every team from the contract.
    pool = _pool(league, params, rostered=())
    assert not {c.player_id for c in pool.candidates} & set(rostered_ids(league))


def test_pool_excludes_the_live_rookie_auction(league, params):
    pool = _pool(league, params)
    lots = {f"rookie{i + 1:02d}" for i in range(AUCTION_ROOKIES)}
    assert set(pool.excluded_auction_lot_ids) == lots
    ids = {c.player_id for c in pool.candidates} | set(pool.unpriced_ids)
    assert not ids & lots
    # They are strong on purpose: had they leaked they would top the pool.
    assert max(league["ppg"][r] for r in lots) > pool.candidates[0].ppg


def test_unprojected_free_agents_are_listed_unpriced_never_zero(league, params):
    pool = _pool(league, params)
    assert set(pool.unpriced_ids) == set(league["unprojected"])
    assert all(
        c.ppg is not None and c.player_id not in league["unprojected"] for c in pool.candidates
    )


def test_candidates_sorted_best_first_and_picks_never_offered(league, params):
    pool = _pool(league, params)
    ppgs = [c.ppg for c in pool.candidates]
    assert ppgs == sorted(ppgs, reverse=True)
    assert all(c.position != "PICK" for c in pool.candidates)
    assert pool.basis["excluded"]["picks"] == 1


def test_player_unavailable_every_remaining_week_is_excluded(league, params):
    weeks = [8, 9, 10]
    top = _pool(league, params).candidates[0].player_id
    pool = _pool(
        league,
        params,
        weeks=weeks,
        availability_by_id={top: {8: "unavailable", 9: "unavailable", 10: "unavailable"}},
    )
    assert top not in {c.player_id for c in pool.candidates}
    assert pool.basis["unavailableEveryWeekIds"] == [top]
    # Partly available: stays, carrying his weekly map for the solve.
    pool2 = _pool(
        league, params, weeks=weeks, availability_by_id={top: {8: "unavailable", 9: "available"}}
    )
    kept = next(c for c in pool2.candidates if c.player_id == top)
    assert kept.availability == {8: "unavailable", 9: "available"}


def test_caller_exclusions_apply(league, params):
    top = _pool(league, params).candidates[0].player_id
    pool = _pool(league, params, excluded_ids=[top])
    assert top not in {c.player_id for c in pool.candidates}


def test_pricing_unavailable_is_unknown_not_empty(league, params):
    def dead(ids, *, season, scoring_settings):
        return {}, {"state": "unavailable", "reason": "no_projection_snapshot"}

    pool = _pool(league, params, lookup=dead)
    assert pool.state == "unavailable"
    assert pool.reason == "pricing_unavailable:no_projection_snapshot"
    assert pool.candidates == ()
    assert pool.unpriced_ids  # every free agent, not silently dropped


def test_no_free_agent_projected_is_unknown(league, params):
    def nobody(ids, *, season, scoring_settings):
        return {}, {"state": "available"}

    pool = _pool(league, params, lookup=nobody)
    assert pool.state == "unavailable"
    assert pool.reason == "no_free_agent_projected"


def test_observed_empty_pool_is_available_with_reason(params):
    contract = {"playersArray": [], "sleeper": {"teams": []}}
    pool = waiver_candidates(contract, [], season=2026, scoring_settings={}, params=params)
    assert (pool.state, pool.reason, pool.candidates) == ("available", "no_free_agents", ())


def test_missing_players_array_is_unavailable(params):
    pool = waiver_candidates({}, [], season=2026, scoring_settings={}, params=params)
    assert (pool.state, pool.reason) == ("unavailable", "contract_players_missing")
