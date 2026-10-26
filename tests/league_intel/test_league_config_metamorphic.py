"""Issue #1842 checkboxes 3-4: metamorphic league-config propagation tests.

Offline and deterministic.  Every fixture is synthetic (a temp registry, a temp
scoring-snapshot directory, in-memory contracts) except where a test says it
reads a committed artifact.  Nothing here touches the network, ``data/`` or a
running server.

The tests are RELATIONS, not golden values: change one input of the league
configuration and check that exactly the outputs that should move do move, and
the rest do not.  The matrix they accompany is
``docs/audits/LEAGUE_CONFIG_PROPAGATION_MATRIX_2026-10-26.md``.

    scoring controls rankings; the league key controls context

Sections
--------
A. scoring-key change moves scoring-dependent outputs, never ownership/context
B. slot change (SFLEX / TE / IDP) moves lineup-dependent outputs
C. same ``scoringProfile`` label, different cards: never share
D. multi-league isolation
E. a stale or missing card fails closed
F. genuine defects: still-open ones pinned ``xfail(strict=True)`` with their exact
   repro; repaired ones stand as ordinary regression tests

A section-F test that starts passing fails the suite (strict): remove its
marker in the same change that repairs the defect.  Nothing here changes a
served value, flag or methodology.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.api import league_registry as lr
from src.league_comparison.sleeper_scoring import scoring_fingerprint

ROOT = Path(__file__).resolve().parents[2]

#: One hand-typed label shared by two leagues that do NOT score alike -- the
#: exact shape of W18-F001 (both live leagues carry ``superflex_tep15_ppr1``).
LABEL = "superflex_tep15_ppr1"

#: Synthetic cards modelled on the live ``dynasty_main`` card (no TE premium,
#: length-banded receptions).  ``CARD_FULL_PPR`` is the other league's shape.
CARD_MAIN = {
    "pass_yd": 0.04,
    "pass_td": 6.0,
    "pass_int": -4.0,
    "pass_cmp": 0.37,
    "pass_inc": -0.67,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 0.1,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "bonus_rec_te": 0.0,
    "bonus_fd_te": 1.0,
    "bonus_fd_wr": 1.0,
    "bonus_fd_rb": 1.0,
    "idp_tkl_solo": 1.33,
    "idp_sack": 2.92,
    "fgm_yds": 0.07,
    "xpm": 2.31,
}
CARD_FULL_PPR = {
    **{k: v for k, v in CARD_MAIN.items() if k not in ("pass_cmp", "pass_inc", "bonus_fd_te")},
    "rec": 1.0,
    "pass_td": 4.0,
    "pass_int": -1.0,
    "bonus_rec_te": 0.5,
}

MAIN_STARTERS = {
    "QB": 1,
    "RB": 2,
    "WR": 3,
    "TE": 2,
    "FLEX": 2,
    "SFLEX": 1,
    "K": 1,
    "DL": 3,
    "LB": 3,
    "DB": 3,
}


# ── fixtures ────────────────────────────────────────────────────────────────


def _registry(*, default: str = "alpha", alpha_active: bool = True) -> dict:
    return {
        "defaultLeagueKey": default,
        "leagues": [
            {
                "key": "alpha",
                "displayName": "Alpha",
                "sleeperLeagueId": "L-ALPHA",
                "scoringProfile": LABEL,
                "idpEnabled": True,
                "bestBall": True,
                "active": alpha_active,
                "aliases": ["a", "primary"],
                "rosterSettings": {
                    "teamCount": 12,
                    "rosterSize": 58,
                    "taxiSize": 0,
                    "starters": dict(MAIN_STARTERS),
                },
            },
            {
                "key": "beta",
                "displayName": "Beta",
                "sleeperLeagueId": "L-BETA",
                "scoringProfile": LABEL,
                "idpEnabled": False,
                "bestBall": False,
                "active": True,
                "rosterSettings": {
                    "teamCount": 10,
                    "rosterSize": 27,
                    "taxiSize": 3,
                    "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "SFLEX": 1},
                },
            },
            {
                "key": "retired",
                "displayName": "Retired",
                "sleeperLeagueId": "L-RET",
                "scoringProfile": LABEL,
                "active": False,
                "rosterSettings": {},
            },
        ],
    }


class World:
    """A temp registry plus a temp scoring-snapshot directory."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.registry_path = tmp_path / "registry.json"
        self.cards_dir = tmp_path / "cards"

    def write_registry(self, payload: dict) -> None:
        self.registry_path.write_text(json.dumps(payload), encoding="utf-8")
        lr.reload_registry()
        lr._scoring_fp_cache.clear()

    def write_card(
        self,
        league_id: str,
        card: dict | None,
        *,
        age_hours: float = 0.5,
        season: str | None = "current",
        fetched_at: bool = True,
    ) -> Path:
        """A scoring snapshot of a given age, written the way the warm pass does.

        Written directly rather than through ``write_scoring_snapshot`` so the
        retention store is not touched.
        """
        from src.bdvm.actuals import nfl_projection_season

        self.cards_dir.mkdir(parents=True, exist_ok=True)
        payload: dict = {"sleeperLeagueId": league_id, "scoringSettings": card}
        if fetched_at:
            when = datetime.now(timezone.utc) - timedelta(hours=age_hours)
            payload["fetchedAt"] = when.isoformat()
        if season == "current":
            payload["season"] = str(nfl_projection_season())
        elif season is not None:
            payload["season"] = season
        path = lr.scoring_snapshot_path(league_id)
        path.write_text(json.dumps(payload), encoding="utf-8")
        lr._scoring_fp_cache.clear()
        return path

    def cfg(self, key: str):
        found = lr.get_league_by_key(key)
        assert found is not None, key
        return found


@pytest.fixture
def world(tmp_path, monkeypatch):
    w = World(tmp_path)
    with monkeypatch.context() as m:
        m.setenv("LEAGUE_REGISTRY_PATH", str(w.registry_path))
        m.setenv("LEAGUE_SCORING_SNAPSHOT_DIR", str(w.cards_dir))
        w.write_registry(_registry())
        yield w
    lr.reload_registry()
    lr._scoring_fp_cache.clear()


def _request(query: str = "", headers: list | None = None):
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/x",
            "query_string": query.encode(),
            "headers": headers or [],
        }
    )


def _contract(league_key: str, card: dict | None, **sleeper) -> dict:
    block: dict = {"teams": [], **sleeper}
    if card is not None:
        block["scoringSettings"] = dict(card)
    return {"meta": {"leagueKey": league_key}, "playersArray": [], "sleeper": block}


# ── A. scoring-key change: scoring outputs move, ownership/context does not ─


def test_a_scoring_key_change_moves_points_by_exactly_the_rate_delta():
    from src.league_intel.scorer import score_stat_line

    line = {"rec": 5, "rec_yd": 50, "rec_td": 1, "pass_att": 40}
    moved = {**CARD_MAIN, "rec": CARD_MAIN["rec"] + 0.9}
    base = score_stat_line(line, CARD_MAIN).total_points
    after = score_stat_line(line, moved).total_points
    assert after - base == pytest.approx(5 * 0.9)
    # a key the line does not carry cannot move it
    untouched = score_stat_line(line, {**CARD_MAIN, "idp_sack": 9.0}).total_points
    assert untouched == pytest.approx(base)
    # zero-vs-absent is no change at all
    assert score_stat_line(line, {**CARD_MAIN, "bonus_rec_te": 0.0}).total_points == pytest.approx(
        base
    )


def test_a_scoring_key_change_moves_the_identity_and_the_bdvm_config_but_not_its_slots():
    from src.bdvm import league_config

    positions = ["QB", "RB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"] + ["BN"] * 5
    settings = {"num_teams": 12, "taxi_slots": 0}
    a = league_config.from_contract(
        _contract("alpha", CARD_MAIN, rosterPositions=positions, leagueSettings=settings),
        league_key="alpha",
    )
    moved = {**CARD_MAIN, "rec": 1.0}
    b = league_config.from_contract(
        _contract("alpha", moved, rosterPositions=positions, leagueSettings=settings),
        league_key="alpha",
    )
    assert scoring_fingerprint(CARD_MAIN) != scoring_fingerprint(moved)
    assert a.scoring_settings != b.scoring_settings
    assert a.config_hash != b.config_hash
    # ownership/context facts do not move with a rate
    assert (a.starters, a.flex, a.teams, a.roster_size) == (
        b.starters,
        b.flex,
        b.teams,
        b.roster_size,
    )


def test_a_scoring_key_change_flips_the_cross_league_gate_but_not_league_resolution(world):
    """The same edit to beta's card changes WHAT may be shared (gate) and
    leaves WHO owns what (resolution, pick ownership) alone."""
    import server
    from src.trade.roster_capacity import league_roster_limit, league_taxi_size

    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_MAIN)
    loaded = _contract("alpha", CARD_MAIN)
    beta = world.cfg("beta")

    assert server._scoring_identity_error(loaded, beta) is None  # identical cards: shareable
    resolved_before = server._resolve_league_for_request(_request("leagueKey=beta"))
    cap_before = (league_roster_limit("beta"), league_taxi_size("beta"))

    world.write_card("L-BETA", {**CARD_MAIN, "rec": 1.0})  # ONE rate differs
    err = server._scoring_identity_error(loaded, beta)
    assert err is not None and err.status_code == 503
    resolved_after = server._resolve_league_for_request(_request("leagueKey=beta"))
    cap_after = (league_roster_limit("beta"), league_taxi_size("beta"))

    assert resolved_before.key == resolved_after.key == "beta"
    assert resolved_before.sleeper_league_id == resolved_after.sleeper_league_id == "L-BETA"
    assert cap_before == cap_after == (27, 3)  # context facts did not move with a rate


def test_a_the_ownership_fold_takes_no_scoring_input():
    """Structural half of the relation: there is no parameter a rate could ride in on."""
    import inspect

    from src.identity import picks

    params = set(inspect.signature(picks.build_pick_ownership).parameters)
    assert not {p for p in params if "scor" in p or "card" in p or "profile" in p}
    traded = [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 5}]
    owned = picks.build_pick_ownership(
        "alpha", [1, 2, 3, 4, 5, 6], traded, seasons=[2027], rounds=2
    )
    moved = [p for p in owned if p.identity.origin_roster_id == 2 and p.identity.round_num == 1]
    assert [p.state.owner_roster_id for p in moved] == [5]  # traded away: STATE, same identity


def test_a_faab_target_format_follows_the_card_never_the_label(world):
    from src.trade.faab_comparability import TargetFormat

    results = {}
    for name, card in (("none", CARD_MAIN), ("tep", {**CARD_MAIN, "bonus_rec_te": 0.5})):
        world.write_card("L-BETA", card)
        results[name] = TargetFormat.from_league_config(world.cfg("beta")).tep
    # the label (``..._tep15_...``) is identical in both runs
    assert world.cfg("beta").scoring_profile == LABEL
    assert results == {"none": False, "tep": True}


# ── B. slot change: lineup-dependent outputs move ────────────────────────────


def _player(pid: str, pos: str, value: float):
    from src.ros.lineup import RosterPlayer

    return RosterPlayer(player_id=pid, canonical_name=pid, position=pos, ros_value=value)


POOL = [
    _player("qb1", "QB", 90),
    _player("qb2", "QB", 80),
    _player("rb1", "RB", 60),
    _player("rb2", "RB", 50),
    _player("wr1", "WR", 55),
    _player("wr2", "WR", 45),
    _player("te1", "TE", 40),
    _player("te2", "TE", 35),
    _player("dl1", "DL", 30),
    _player("dl2", "DL", 25),
    _player("lb1", "LB", 28),
]
BASE_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE"]


def _solve(slots: list[str]):
    from src.ros.lineup import assign_lineup

    return assign_lineup(POOL, slots)


def test_b_adding_a_superflex_slot_starts_the_second_qb_and_changes_nothing_else():
    base = _solve(BASE_SLOTS)
    sflex = _solve([*BASE_SLOTS, "SUPER_FLEX"])
    assert sflex.starter_ids - base.starter_ids == {"qb2"}
    assert base.starter_ids <= sflex.starter_ids
    assert sflex.score - base.score == pytest.approx(80)


def test_b_sflex_spelling_is_the_same_slot():
    assert (
        _solve([*BASE_SLOTS, "SFLEX"]).starter_ids
        == _solve([*BASE_SLOTS, "SUPER_FLEX"]).starter_ids
    )


def test_b_a_second_te_slot_starts_the_second_te():
    base = _solve(BASE_SLOTS)
    two_te = _solve([*BASE_SLOTS, "TE"])
    assert two_te.starter_ids - base.starter_ids == {"te2"}
    assert two_te.score - base.score == pytest.approx(35)


def test_b_idp_slots_start_defenders_only_when_the_league_has_them():
    offense_only = _solve(BASE_SLOTS)
    idp = _solve([*BASE_SLOTS, "DL", "DL", "LB"])
    assert {"dl1", "dl2", "lb1"} <= idp.starter_ids
    assert not ({"dl1", "dl2", "lb1"} & offense_only.starter_ids)
    # a rostered defender in an offense-only league is bench, not unpriced
    assert "dl1" in offense_only.bench_ids(POOL)
    assert idp.unfilled_slots == []


def test_b_an_unfillable_slot_is_reported_not_zero_filled():
    out = _solve([*BASE_SLOTS, "DB"])  # nobody on this roster is a DB
    assert out.unfilled_slots == ["DB"]
    assert out.score == pytest.approx(_solve(BASE_SLOTS).score)


def test_b_bdvm_slots_follow_the_live_slot_list_and_idp_flag():
    from src.bdvm import league_config

    settings = {"num_teams": 12}
    positions = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DL", "LB"] + ["BN"] * 4

    def build(slots, **kw):
        return league_config.from_contract(
            _contract("alpha", CARD_MAIN, rosterPositions=slots, leagueSettings=settings),
            league_key="alpha",
            **kw,
        )

    base = build(positions)
    assert base.starters["TE"] == 1 and "SUPER_FLEX" not in base.flex
    with_sflex = build([*positions, "SUPER_FLEX"])
    assert with_sflex.flex["SUPER_FLEX"][0] == 1
    two_te = build([*positions, "TE"])
    assert two_te.starters["TE"] == 2
    # slot edits change the hash; the scoring card did not move
    assert len({base.config_hash, with_sflex.config_hash, two_te.config_hash}) == 3
    assert base.scoring_settings == with_sflex.scoring_settings == two_te.scoring_settings
    # a non-IDP league never keeps defenders in its lineup model
    assert build(positions, idp_enabled=False).starters.get("DL") is None
    assert base.starters["DL"] == 1


def test_b_the_slot_ladder_prefers_the_live_host_list_over_the_registry():
    from src.ros.lineup import resolve_starter_slots

    registry = {"starters": {"QB": 1, "RB": 2}}
    live = ["QB", "RB", "RB", "RB", "SUPER_FLEX", "BN"]
    slots, source = resolve_starter_slots(roster_positions=live, roster_settings=registry)
    assert source == "sleeper_roster_positions" and "SUPER_FLEX" in slots
    slots, source = resolve_starter_slots(roster_positions=[], roster_settings=registry)
    assert source == "registry_starters" and slots == ["QB", "RB", "RB"]
    assert resolve_starter_slots() == ([], None)  # refuse, never a default lineup


# ── C. same label, different cards: never share ───────────────────────────────


def test_c_same_label_different_cards_do_not_share(world):
    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_FULL_PPR)
    assert world.cfg("alpha").scoring_profile == world.cfg("beta").scoring_profile
    assert not lr.leagues_share_scoring("alpha", "beta")
    assert lr.scoring_fingerprint_for_league(world.cfg("alpha")) != (
        lr.scoring_fingerprint_for_league(world.cfg("beta"))
    )


def test_c_different_labels_identical_cards_may_share(world):
    payload = _registry()
    payload["leagues"][1]["scoringProfile"] = "some_other_label"
    world.write_registry(payload)
    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", dict(reversed(list(CARD_MAIN.items()))))  # key order is not identity
    assert world.cfg("alpha").scoring_profile != world.cfg("beta").scoring_profile
    assert lr.leagues_share_scoring("alpha", "beta")


def test_c_the_label_never_decides_the_gate_even_when_it_is_the_only_thing_that_matches(world):
    import server

    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_FULL_PPR)
    err = server._scoring_identity_error(_contract("alpha", CARD_MAIN), world.cfg("beta"))
    assert err is not None and err.status_code == 503
    body = json.loads(err.body)
    assert body["error"] == "data_not_ready"
    assert body["scoringFingerprint"] != body["loadedScoringFingerprint"]


def test_c_a_contract_whose_stamp_disagrees_with_its_own_card_proves_nothing(world):
    import server

    world.write_card("L-BETA", CARD_MAIN)
    contract = _contract("alpha", CARD_MAIN)
    contract["meta"]["scoringFingerprint"] = scoring_fingerprint(CARD_FULL_PPR)
    err = server._scoring_identity_error(contract, world.cfg("beta"))
    assert err is not None  # a stamp is a cache of the card; disagreement fails closed


def test_c_the_ensemble_cache_is_keyed_by_the_card_not_the_label():
    """``best_ball_utility`` shares an ensemble per (season, card fingerprint)."""
    import inspect

    from src.roster_intel import best_ball_utility

    src = inspect.getsource(best_ball_utility._ensemble_index)
    assert "scoring_fingerprint" in src and "scoring_profile" not in src
    assert scoring_fingerprint(CARD_MAIN) != scoring_fingerprint(CARD_FULL_PPR)


# ── D. multi-league isolation ─────────────────────────────────────────────────


def test_d_explicit_keys_beat_saved_state_and_aliases_resolve(world, monkeypatch):
    import server

    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "u"})
    monkeypatch.setattr(server._user_kv, "get_user_state", lambda u: {"activeLeagueKey": "beta"})
    assert server._resolve_league_for_request(_request()).key == "beta"  # saved state
    assert server._resolve_league_for_request(_request("leagueKey=alpha")).key == "alpha"
    assert server._resolve_league_for_request(_request("leagueKey=primary")).key == "alpha"
    body_pick = server._resolve_league_for_request(_request(), body={"leagueKey": "alpha"})
    assert body_pick.key == "alpha"


def test_d_unknown_and_inactive_keys_are_refused_never_substituted(world):
    import server

    for query, code in (
        ("leagueKey=ghost", "unknown_league"),
        ("leagueKey=retired", "inactive_league"),
    ):
        with pytest.raises(server.LeagueResolutionError) as excinfo:
            server._resolve_league_for_request(_request(query))
        assert (excinfo.value.status, excinfo.value.code) == (400, code)


def test_d_a_loaded_contract_for_another_league_is_never_served_as_this_one(world, monkeypatch):
    import server

    monkeypatch.setattr(server, "latest_contract_data", _contract("alpha", CARD_MAIN))
    with pytest.raises(server.LeagueResolutionError) as excinfo:
        server._resolve_league_for_request(_request("leagueKey=beta"), require_loaded_contract=True)
    assert (excinfo.value.status, excinfo.value.code) == (503, "data_not_ready")
    assert (
        server._resolve_league_for_request(
            _request("leagueKey=alpha"), require_loaded_contract=True
        ).key
        == "alpha"
    )


def test_d_pick_identity_and_ownership_are_league_scoped():
    from src.identity import picks

    alpha = picks.build_pick_ownership("alpha", [1, 2], [], seasons=[2027], rounds=1)
    beta = picks.build_pick_ownership("beta", [1, 2], [], seasons=[2027], rounds=1)
    alpha_ids = {p.identity.canonical_id for p in alpha}
    beta_ids = {p.identity.canonical_id for p in beta}
    assert alpha_ids and beta_ids and alpha_ids.isdisjoint(beta_ids)
    teams = [
        {"roster_id": 1, "pickDetails": [{"assetId": i} for i in sorted(alpha_ids)]},
        {"roster_id": 2, "pickDetails": []},
    ]
    for own in alpha_ids:
        assert picks.lookup_league_pick_owner(teams, own).state == picks.PICK_OWNER_OWNED
    for foreign in beta_ids:
        assert picks.lookup_league_pick_owner(teams, foreign).state == picks.PICK_OWNER_ABSENT


def test_d_the_cross_league_sleeper_block_ignores_the_loaded_leagues_league_fields():
    """Invariance: nothing league-specific is inherited from the LOADED league."""
    from src.api import sleeper_overlay as so

    overlay = {"teams": [{"ownerId": "b1"}], "idToPlayer": {}}
    beta_cfg = {
        "scoringSettings": dict(CARD_FULL_PPR),
        "rosterPositions": ["QB", "RB", "BN"],
        "leagueSettings": {"num_teams": 10},
    }
    one = so.merge_cross_league_sleeper_block(
        loaded_sleeper={
            "scoringSettings": dict(CARD_MAIN),
            "rosterPositions": ["QB", "SUPER_FLEX", "TE", "TE", "BN"],
            "leagueSettings": {"num_teams": 12},
            "teams": [{"ownerId": "a1"}],
            "playerIds": ["x"],
        },
        overlay=overlay,
        requested_league_config=beta_cfg,
    )
    other = so.merge_cross_league_sleeper_block(
        loaded_sleeper={"scoringSettings": {"rec": 9.0}, "playerIds": ["x"]},
        overlay=overlay,
        requested_league_config=beta_cfg,
    )
    assert one == other
    block, ready = one
    assert ready is True
    assert block["scoringSettings"] == CARD_FULL_PPR and block["teams"] == [{"ownerId": "b1"}]
    # and with NO config for the requested league the fields are absent, not inherited
    block2, ready2 = so.merge_cross_league_sleeper_block(
        loaded_sleeper={"scoringSettings": dict(CARD_MAIN), "rosterPositions": ["QB"]},
        overlay=overlay,
        requested_league_config=None,
    )
    assert ready2 is False
    for field in so.LEAGUE_SPECIFIC_SLEEPER_FIELDS:
        assert field not in block2


def test_d_each_league_is_scored_under_its_own_card(world):
    from src.league_intel.scorer import score_stat_line

    line = {"rec": 4, "rec_yd": 40, "pass_td": 1}
    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_FULL_PPR)
    a = score_stat_line(line, lr.scoring_settings_for_league(world.cfg("alpha"))).total_points
    b = score_stat_line(line, lr.scoring_settings_for_league(world.cfg("beta"))).total_points
    assert a == pytest.approx(4 * 0.1 + 40 * 0.1 + 6)
    assert b == pytest.approx(4 * 1.0 + 40 * 0.1 + 4)


# ── E. a stale or missing card fails closed ──────────────────────────────────


@pytest.mark.parametrize(
    ("kwargs", "state"),
    [
        ({"age_hours": 0.5}, "fresh"),
        ({"age_hours": 5.9}, "fresh"),
        ({"age_hours": 6.5}, "stale"),
        ({"age_hours": 72.0}, "stale"),
        ({"age_hours": 0.5, "season": "1999"}, "stale"),
        ({"age_hours": 0.5, "season": None}, "stale"),
        ({"fetched_at": False}, "stale"),
    ],
)
def test_e_the_card_states(world, kwargs, state):
    world.write_card("L-BETA", CARD_MAIN, **kwargs)
    assert lr.scoring_evidence_state(world.cfg("beta")) == state
    proven = lr.scoring_fingerprint_for_league(world.cfg("beta"))
    assert (proven is not None) is (state == "fresh")


def test_e_missing_is_not_stale_and_not_fresh(world):
    assert lr.scoring_evidence_state(world.cfg("beta")) == "missing"
    assert lr.scoring_fingerprint_for_league(world.cfg("beta")) is None
    world.write_card("L-BETA", None)  # a card of null: nothing to fingerprint
    assert lr.scoring_evidence_state(world.cfg("beta")) == "missing"


@pytest.mark.parametrize("which", ["alpha", "beta"])
def test_e_either_side_unproven_means_no_sharing_even_with_identical_cards(world, which):
    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_MAIN)
    assert lr.leagues_share_scoring("alpha", "beta")
    world.write_card("L-ALPHA" if which == "alpha" else "L-BETA", CARD_MAIN, age_hours=48.0)
    assert not lr.leagues_share_scoring("alpha", "beta")


def test_e_stale_evidence_is_retained_but_loses_its_authority(world):
    world.write_card("L-BETA", CARD_FULL_PPR, age_hours=48.0)
    assert lr.scoring_settings_for_league(world.cfg("beta")) == CARD_FULL_PPR
    assert lr.scoring_fingerprint_for_league(world.cfg("beta")) is None


def test_e_the_gate_503s_on_stale_or_missing_snapshots_but_never_on_the_loaded_league(world):
    import server

    loaded = _contract("alpha", CARD_MAIN)
    beta = world.cfg("beta")
    for age in (None, 48.0):  # missing, then stale
        if age is not None:
            world.write_card("L-BETA", CARD_MAIN, age_hours=age)
        err = server._scoring_identity_error(loaded, beta)
        assert err is not None and err.status_code == 503
        assert json.loads(err.body)["scoringFingerprint"] is None
    # the loaded league's own requests never reach the comparison
    assert server._scoring_identity_error(loaded, world.cfg("alpha")) is None
    # an unidentified contract (no card) proves nothing about anyone else
    world.write_card("L-BETA", CARD_MAIN)
    assert server._scoring_identity_error(_contract("alpha", None), beta) is not None


def test_e_faab_target_tep_is_unknown_when_the_card_is_not_fresh(world):
    from src.trade.faab_comparability import TargetFormat

    world.write_card("L-BETA", {**CARD_MAIN, "bonus_rec_te": 0.5}, age_hours=48.0)
    assert TargetFormat.from_league_config(world.cfg("beta")).tep is None  # UNKNOWN, not False
    world.write_card("L-BETA", {**CARD_MAIN, "bonus_rec_te": 0.5}, age_hours=0.5)
    assert TargetFormat.from_league_config(world.cfg("beta")).tep is True


def test_e_bdvm_refuses_a_missing_card_instead_of_scoring_at_zero():
    from src.bdvm import league_config

    contract = _contract(
        "alpha", None, rosterPositions=["QB", "RB", "BN"], leagueSettings={"num_teams": 12}
    )
    with pytest.raises(league_config.LeagueConfigError):
        league_config.from_contract(contract, league_key="alpha")


def test_e_a_zero_filled_card_is_not_an_identity():
    assert scoring_fingerprint({}) is None
    assert scoring_fingerprint(None) is None


# ── F. genuine defects (open: xfail strict; repaired: regression tests) ───────
#
# Each reason starts with its id so a grep for ``LI1842-DEFECT-`` is the defect
# register.  The prose, repro and severity live in the matrix document.


# LI1842-DEFECT-01 -- REPAIRED: POST /api/intel/leads is a 503 data_not_ready for a league the loaded contract was not built for, and the context helper abstains.
def test_f01_intel_leads_do_not_borrow_another_leagues_rosters_or_values(world, monkeypatch):
    import server
    from src.intel import lead_service

    captured: dict = {}
    monkeypatch.setattr(lead_service, "build_leads", lambda **kw: captured.update(kw) or {})
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {
            "meta": {"leagueKey": "alpha"},
            "sleeper": {"teams": [{"ownerId": "ALPHA_OWNER", "playerIds": ["4046"]}]},
            "playersArray": [{"playerId": "4046", "position": "QB", "rankDerivedValue": 9000}],
        },
    )
    server._build_intel_leads(world.cfg("beta"), "4046", "buy")
    assert captured["league_key"] == "beta"
    assert captured["owner_of_asset"] is None  # league A's owner leaked in
    assert captured["target_value"] is None  # league A's board value leaked in


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-02: a manual tep_multiplier in the POST /api/rankings/overrides body still "
        "changes rankDerivedValue (110 rows on the 2026-10-25 board) although the client comment "
        "and CLAUDE.md describe the user's manual override as withdrawn; only source weights are "
        "(normalize_source_overrides)."
    ),
)
def test_f02_a_manual_tep_multiplier_cannot_move_the_canonical_board():
    from src.api import data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")

    def values(tep):
        out = data_contract.build_rankings_delta_payload(
            raw, source_overrides={}, tep_multiplier=tep
        )
        return {r["id"]: r.get("rankDerivedValue") for r in out["rankingsDelta"]["players"]}

    baseline = values(None)
    assert len(baseline) > 500  # a real board, not an empty delta
    assert values(1.45) == baseline


# LI1842-DEFECT-03 -- REPAIRED: GET /api/movers follows the board's _scoring_identity_error gate.
def test_f03_movers_follow_the_same_scoring_gate_as_the_board(world, monkeypatch, tmp_path):
    import server
    from src.api import rank_history

    world.write_card("L-ALPHA", CARD_MAIN)
    world.write_card("L-BETA", CARD_FULL_PPR)
    history = tmp_path / "rank_history.jsonl"
    today = datetime.now(timezone.utc).date()
    rows = [
        {"date": (today - timedelta(days=2)).isoformat(), "ranks": {"Riser::offense": 80}},
        {"date": today.isoformat(), "ranks": {"Riser::offense": 30}},
    ]
    history.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(rank_history, "HISTORY_PATH", history)
    monkeypatch.setattr(server, "latest_contract_data", _contract("alpha", CARD_MAIN))

    gate = server._scoring_identity_error(server.latest_contract_data, world.cfg("beta"))
    assert gate is not None  # the board itself is refused for beta ...
    response = asyncio.run(server.get_movers(_request("leagueKey=beta&window=2&threshold=15")))
    served_risers = response.status_code == 200 and bool(json.loads(response.body).get("risers"))
    assert not served_risers  # ... so its movers must not be served either


# LI1842-DEFECT-04 -- REPAIRED: the scoring-fit / reception-fit memos are keyed on the cards' scoring fingerprints.
def test_f04_the_scoring_fit_memo_notices_a_changed_card(monkeypatch):
    from src.api import feature_flags, gameplan
    from src.league_comparison import service as lc_service
    from src.league_comparison import sleeper_scoring
    from src.league_intel import scoring_fit as li_scoring_fit
    from src.nfl_data import ingest

    cards = {"M": {"rec": 1.0, "pass_td": 4.0}, "B": {"rec": 0.5, "pass_td": 4.0}}
    monkeypatch.setattr(feature_flags, "is_enabled", lambda *_a, **_k: True)
    monkeypatch.setattr(
        lc_service, "_load_config", lambda: {"baseline_league": {"id": "B"}, "seasons": [2025]}
    )
    monkeypatch.setattr(lr, "get_sleeper_league_id", lambda key: "M")
    monkeypatch.setattr(
        sleeper_scoring,
        "fetch_league_scoring",
        lambda lid, **k: SimpleNamespace(scoring_settings=dict(cards[lid])),
    )
    monkeypatch.setattr(ingest, "fetch_weekly_defensive_stats", lambda *_a, **_k: [{}])
    monkeypatch.setattr(
        li_scoring_fit,
        "measure_positional_scoring_fit",
        lambda rows, mine, base, season=None: scoring_fingerprint(mine),
    )
    gameplan.invalidate_scoring_fit_cache()
    try:
        first = gameplan._resolve_scoring_fit("dynasty_main")
        cards["M"] = {"rec": 0.08, "pass_td": 6.0}  # the host edits the card
        second = gameplan._resolve_scoring_fit("dynasty_main")
    finally:
        gameplan.invalidate_scoring_fit_cache()
    assert first == scoring_fingerprint({"rec": 1.0, "pass_td": 4.0})
    assert second == scoring_fingerprint(cards["M"])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-05: consensus_edge.scoring_fit._scoring_cards reads the committed "
        "2026-07-26 dated snapshot (sf1:b7ad1575925091f6, 141 keys) via load_canonical_config and "
        "never compares it with the league's fresh evidence (live card is sf1:9e51824690d091f9). "
        "Flag consensus_edge is OFF today, so the reach is latent."
    ),
)
def test_f05_consensus_edge_fit_does_not_score_with_a_card_the_league_no_longer_has(
    world, monkeypatch
):
    from src.consensus_edge import scoring_fit
    from src.league_intel import config as li_config

    committed = dict(li_config.load_canonical_config().scoring_settings)
    live = {**committed, "rec": committed["rec"] + 0.02, "pass_cmp": 0.37}
    payload = _registry()
    payload["leagues"][0]["sleeperLeagueId"] = li_config.load_canonical_config().sleeper_league_id
    world.write_registry(payload)
    world.write_card(li_config.load_canonical_config().sleeper_league_id, live)

    mine, _baseline, _meta = scoring_fit._scoring_cards()
    # either the fit follows the fresh evidence, or it abstains; it may not use the old card
    assert mine is None or scoring_fingerprint(mine) == scoring_fingerprint(live)


# LI1842-DEFECT-06 -- REPAIRED: an unknown league key is refused (no rows; 400 unknown_league at the route), never the default league.
def test_f06_an_unknown_league_key_never_computes_another_leagues_team_strength(world, monkeypatch):
    from src.api import sleeper_overlay
    from src.ros import team_strength

    calls: list = []
    monkeypatch.setattr(team_strength, "load_ros_aggregate_players", lambda: {"x": {"a": 1}})
    monkeypatch.setattr(
        sleeper_overlay, "fetch_sleeper_overlay", lambda **kw: calls.append(kw) or {"teams": []}
    )
    assert team_strength.compute_team_strength_live("not_a_league") == []
    assert calls == []  # no Sleeper fetch for the default league on an unknown key's behalf


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-07: the trade-side roster cap (roster_capacity.league_roster_limit) reads "
        "only the registry rosterSize; the live sleeper.rosterPositions that the lineup ladder "
        "prefers is never consulted and a disagreement is not even noted. dynasty_new today: "
        "registry 27 vs live 24 slots."
    ),
)
def test_f07_roster_capacity_reports_a_disagreement_with_the_live_slot_list():
    from src.trade import roster_capacity as rc

    live_slots = [
        "QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "WRRB_FLEX", "SUPER_FLEX",
    ] + ["BN"] * 14  # fmt: skip
    contract = {
        "meta": {},
        "playersArray": [],
        "sleeper": {
            "rosterPositions": live_slots,
            "teams": [{"ownerId": "o", "name": "T", "players": []}],
        },
    }
    registry_settings = {
        "rosterSize": 27,
        "taxiSize": 3,
        "starters": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "WRRB_FLEX": 1, "SFLEX": 1},
    }
    team = {"name": "T", "ownerId": "o", "players": []}
    ctx = rc.build_capacity_context(
        contract, "beta", team, roster_settings=registry_settings, scarcity_reading=(None, None)
    )
    notes = " ".join(ctx.notes).lower()
    assert ctx.roster_limit == len(live_slots) or "disagree" in notes or "live" in notes


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-08: the client builds the rankings override POST body without a leagueKey "
        "(and the URL is only ?view=delta) while every other league-scoped fetch in "
        "dynasty-data.js carries it, so the server resolves the league from saved user state."
    ),
)
def test_f08_the_overrides_request_carries_the_pages_league_key():
    text = (ROOT / "frontend" / "lib" / "dynasty-data.js").read_text(encoding="utf-8")
    start = text.index("const body = { ...(siteOverrides")
    end = text.index("const base = await basePromise;", start)
    assert "leagueKey" in text[start:end]


# LI1842-DEFECT-09 -- REPAIRED: rosTeamStrength serves the persisted file only under the read path's freshness + evidence rule.
def test_f09_public_ros_team_strength_does_not_serve_an_expired_file_as_current(
    tmp_path, monkeypatch
):
    from src.ros import api as ros_api
    from src.ros import team_strength

    monkeypatch.setattr(team_strength, "ROS_DATA_DIR", tmp_path)
    target = tmp_path / "team_strength"
    target.mkdir()
    snapshot = target / "latest.json"
    snapshot.write_text(json.dumps([{"ownerId": "o1", "startingLineupScore": 0}]), encoding="utf-8")
    month_ago = time.time() - 30 * 86400
    os.utime(snapshot, (month_ago, month_ago))
    assert team_strength.persisted_fast_path_rows(None) is None  # the read path's own verdict
    section = ros_api.build_section(SimpleNamespace(root_league_id=""))
    assert not (section["source"] == "snapshot" and section["stale"] is False)


# LI1842-DEFECT-10 -- REPAIRED: an inactive defaultLeagueKey is not served implicitly.
def test_f10_an_inactive_default_league_is_not_served_implicitly(world):
    world.write_registry(_registry(default="alpha", alpha_active=False))
    assert lr.get_default_league().key == "beta"


# LI1842-DEFECT-11 -- REPAIRED: FLEX_SLOTS mirrors the owner's flex vocabulary (exact lockstep: tests/lineup/test_single_owner.py).
def test_f11_the_perfect_draft_flex_vocabulary_covers_every_canonical_flex_slot():
    from src.ros import lineup

    text = (ROOT / "frontend" / "lib" / "perfect-draft.js").read_text(encoding="utf-8")
    match = re.search(r"const FLEX_SLOTS = new Set\(\[(.*?)\]\)", text, re.S)
    assert match is not None
    js_slots = {s.strip().strip("\"'") for s in match.group(1).split(",") if s.strip()}
    assert set(lineup._FLEX_SLOT_ELIGIBILITY) <= js_slots


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-12: ros.trade_deadline._load_playoff_odds_map/_load_championship_map are "
        "hard-wired to sims/latest_*.json, so build_team_directions(league_key=<non-default>) "
        "classifies that league's teams from the DEFAULT league's simulations (the module "
        "comment names this as a known follow-on). Latent: the public section only serves the "
        "default league today."
    ),
)
def test_f12_trade_deadline_reads_the_requested_leagues_simulation(tmp_path, monkeypatch):
    from src.ros import trade_deadline

    sims = tmp_path / "sims"
    sims.mkdir()
    for name, payload in (
        ("latest_playoff.json", {"playoffOdds": [{"ownerId": "A", "playoffOdds": 0.95}]}),
        ("beta_playoff.json", {"playoffOdds": [{"ownerId": "A", "playoffOdds": 0.05}]}),
        ("latest_championship.json", {"championshipOdds": [{"ownerId": "A", "championshipOdds": 0.4}]}),
        ("beta_championship.json", {"championshipOdds": [{"ownerId": "A", "championshipOdds": 0.01}]}),
    ):  # fmt: skip
        (sims / name).write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(trade_deadline, "ROS_DATA_DIR", tmp_path)
    rows = trade_deadline.build_team_directions(
        league_key="beta", team_strength_map={"A": {"ownerId": "A", "rank": 1}}
    )
    assert rows and rows[0]["playoffOdds"] == pytest.approx(0.05)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LI1842-DEFECT-13: auction.sources.join_budgets joins seats to draft-capital teamTotals by "
        "team NAME and its provenance does not name the league the dollars came from, so a room "
        "created while the admin's saved league differs from the loaded contract's league cannot "
        "be detected from the room's own receipt (api.py takes seats from latest_contract_data and "
        "budgets from a separately-resolved league)."
    ),
)
def test_f13_auction_budget_provenance_names_the_league_of_its_dollars():
    from src.auction import sources

    seats = [{"name": "A", "team": "Alice", "sleeper_user_id": "u1", "roster_id": 1}]
    payload = {
        "leagueKey": "beta",
        "source": "sleeper_derived",
        "teamTotals": [{"team": "Alice", "auctionDollars": 250}],
    }
    _joined, provenance = sources.join_budgets(seats, payload)
    assert provenance.get("leagueKey") == "beta"
