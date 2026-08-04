"""Tests for ``src/api/team_assignment.py``.

Covers favorite resolution (direct + alias + missing), per-tier
scoring rules (T1 QB anchor, T2 skill, T4 rookie, T5 IDP), the
assignment threshold, the max-3 cap, the favorite-always-wins
invariant, and the config fallback when the JSON file is
malformed.

The per-player point totals below are the single-count ones.  There
is no T3: an "elite production" tier fired on the same
``depth_chart_order == 1`` condition as T1/T2 and paid a second time
for it (math audit 2026-08-04, H5b), so a primary QB scored 13 and a
primary skill player 8 against a config that reads 10 and 5.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


from src.api import team_assignment
from src.public_league.identity import Manager, ManagerRegistry, TeamAlias
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── Helpers ────────────────────────────────────────────────────────


def _season(rosters, *, idp=False):
    """Minimal SeasonSnapshot.  ``rosters`` is a list of dicts as
    Sleeper returns them.  ``idp`` controls roster_positions to
    flip the IDP gate on/off."""
    league_settings: dict = {
        "roster_positions": (
            ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"]
            + (["DL", "LB", "DB"] if idp else [])
        ),
    }
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league={"settings": {}, "roster_positions": league_settings["roster_positions"]},
        users=[],
        rosters=rosters,
        matchups_by_week={},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _snapshot(rosters, nfl_players, managers, *, idp=False):
    snap = PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[_season(rosters, idp=idp)],
        managers=managers,
        nfl_players=nfl_players,
    )
    return snap


def _manager(owner_id, display_name, team_name=""):
    return Manager(
        owner_id=owner_id,
        display_name=display_name,
        current_team_name=team_name or display_name,
        current_roster_id=1,
        current_league_id="L1",
        aliases=[
            TeamAlias(
                season="2026",
                league_id="L1",
                team_name=team_name or display_name,
                display_name=display_name,
            ),
        ],
    )


def _player(team, position, *, depth=1, years_exp=2, draft_round=None, name=None):
    """Synthesize a Sleeper-shaped player record."""
    rec = {
        "team": team,
        "position": position,
        "depth_chart_order": depth,
        "years_exp": years_exp,
        "full_name": name or f"{position}-{team}-{depth}",
    }
    if draft_round is not None:
        rec["draft_round"] = draft_round
    return rec


def _config_path(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "team_assignment.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


# ── Config loader ─────────────────────────────────────────────────


def test_load_config_uses_defaults_when_file_missing(tmp_path: Path):
    cfg = team_assignment.load_config(tmp_path / "missing.json")
    assert cfg["weights"]["qbAnchor"] == 10
    assert cfg["thresholds"]["assignmentMinPoints"] == 15
    assert cfg["limits"]["maxTeamsPerOwner"] == 3
    assert cfg["favorites"] == {}


def test_load_config_falls_back_on_malformed_json(tmp_path: Path):
    p = tmp_path / "team_assignment.json"
    p.write_text("not-json", encoding="utf-8")
    cfg = team_assignment.load_config(p)
    # Same defaults as the missing-file path.
    assert cfg["weights"]["qbAnchor"] == 10


def test_load_config_strips_doc_keys(tmp_path: Path):
    p = _config_path(
        tmp_path,
        {
            "_doc": "outer doc",
            "favorites": {
                "_doc": "inner doc",
                "joel": {"abbr": "KC", "display": "Kansas City Chiefs"},
            },
        },
    )
    cfg = team_assignment.load_config(p)
    assert "_doc" not in cfg
    assert "_doc" not in cfg["favorites"]
    assert cfg["favorites"]["joel"]["abbr"] == "KC"


def test_every_declared_weight_is_actually_read(tmp_path: Path):
    """A declared-but-unread knob is a lie in the config file.

    Static check over the module source: the default ``weights`` block
    and the ``weights[...]`` reads in ``_score_player`` must be the same
    set.  ``idpElite`` was declared and never read; the two
    ``eliteProduction*`` weights were read by a tier that
    double-counted.  Either direction of drift is a defect, so this
    fails on both.
    """
    src = Path(team_assignment.__file__).read_text(encoding="utf-8")
    read = set(re.findall(r'weights\["([A-Za-z0-9]+)"\]', src))
    declared = set(team_assignment._DEFAULT_CONFIG["weights"])
    assert declared == read


def test_shipped_config_declares_exactly_the_live_knobs():
    """The on-disk config must not re-introduce dead keys.

    ``_merge_config_with_defaults`` unions the user file over the
    defaults, so a stale key in the JSON survives into the payload's
    ``config`` block and reads as a live setting.
    """
    shipped = json.loads(team_assignment._CONFIG_PATH.read_text(encoding="utf-8"))
    weights = {k for k in shipped["weights"] if k != "_doc"}
    thresholds = {k for k in shipped["thresholds"] if k != "_doc"}
    assert weights == set(team_assignment._DEFAULT_CONFIG["weights"])
    assert thresholds == set(team_assignment._DEFAULT_CONFIG["thresholds"])


def test_load_config_merges_partial_user_config_over_defaults(tmp_path: Path):
    p = _config_path(
        tmp_path,
        {
            "weights": {"qbAnchor": 999},  # override one knob; rest stays default
        },
    )
    cfg = team_assignment.load_config(p)
    assert cfg["weights"]["qbAnchor"] == 999
    # Sibling weights still defaulted.
    assert cfg["weights"]["skillStarter"] == 5
    # Unrelated keys still defaulted.
    assert cfg["thresholds"]["assignmentMinPoints"] == 15


# ── Favorite resolution ───────────────────────────────────────────


def test_resolve_favorite_key_direct_match():
    favs = {"jason": {"abbr": "MIN"}, "ed": {"abbr": "DAL"}}
    aliases = {}
    assert team_assignment._resolve_favorite_key("Jason", favs, aliases) == "jason"
    assert team_assignment._resolve_favorite_key("ED", favs, aliases) == "ed"


def test_resolve_favorite_key_via_alias():
    favs = {"jason": {"abbr": "MIN"}, "michaela": {"abbr": "MIA"}}
    aliases = {"jasonleetucker": "jason", "makayla": "michaela"}
    assert team_assignment._resolve_favorite_key("JasonLeeTucker", favs, aliases) == "jason"
    assert team_assignment._resolve_favorite_key("MaKayla", favs, aliases) == "michaela"


def test_resolve_favorite_key_missing_falls_to_none():
    favs = {"jason": {"abbr": "MIN"}}
    aliases = {}
    assert team_assignment._resolve_favorite_key("Nobody", favs, aliases) is None
    assert team_assignment._resolve_favorite_key("", favs, aliases) is None
    assert team_assignment._resolve_favorite_key(None, favs, aliases) is None


# ── Per-player scoring ────────────────────────────────────────────


def _config():
    return team_assignment._merge_config_with_defaults({})


def test_score_qb_anchor():
    qb = _player("KC", "QB", depth=1, years_exp=5)
    pts, contribs = team_assignment._score_player(
        qb,
        config=_config(),
        league_idp_enabled=False,
    )
    # T1 only — being primary at QB is ONE signal, paid once.
    assert pts == 10
    reasons = {c["reason"] for c in contribs}
    assert "QB anchor" in reasons


def test_score_qb_backup_no_anchor():
    qb = _player("KC", "QB", depth=2, years_exp=5)
    pts, _ = team_assignment._score_player(
        qb,
        config=_config(),
        league_idp_enabled=False,
    )
    # No T1 (depth != 1).  No rookie / IDP / skill rules apply.  → 0.
    assert pts == 0


def test_score_skill_starter_is_paid_once():
    """The config's ``skillStarter`` is 5, so a starter scores 5.

    Regression guard for the double-count: the retired elite-production
    tier added another 3 on the same ``depth_order == 1`` test, so this
    player used to be worth 8 — a number that appeared nowhere in the
    config and made the weights unreadable.
    """
    rb = _player("BUF", "RB", depth=1, years_exp=3)
    pts, contribs = team_assignment._score_player(
        rb,
        config=_config(),
        league_idp_enabled=False,
    )
    assert pts == 5
    reasons = {c["reason"] for c in contribs}
    assert any("starter" in r for r in reasons)
    # Exactly one rule fired, so exactly one contributor row.
    assert len(contribs) == 1


def test_score_skill_committee():
    rb = _player("BUF", "RB", depth=2, years_exp=3)
    pts, _ = team_assignment._score_player(
        rb,
        config=_config(),
        league_idp_enabled=False,
    )
    # T2 committee (2).  → 2.
    assert pts == 2


def test_score_skill_bench_zero():
    rb = _player("BUF", "RB", depth=4, years_exp=3)
    pts, _ = team_assignment._score_player(
        rb,
        config=_config(),
        league_idp_enabled=False,
    )
    assert pts == 0


def test_score_rookie_round_one():
    rookie = _player("CHI", "WR", depth=1, years_exp=0, draft_round=1)
    pts, contribs = team_assignment._score_player(
        rookie,
        config=_config(),
        league_idp_enabled=False,
    )
    # T2 starter (5) + T4 round 1 (4) = 9.  Rookie capital is a
    # genuinely independent signal, so it still layers on top.
    assert pts == 9
    assert any("1st-round rookie" in c["reason"] for c in contribs)


def test_score_rookie_round_two():
    rookie = _player("CHI", "WR", depth=2, years_exp=0, draft_round=2)
    pts, contribs = team_assignment._score_player(
        rookie,
        config=_config(),
        league_idp_enabled=False,
    )
    # T2 committee (2) + T4 round 2 (2) = 4.
    assert pts == 4
    assert any("2nd-round rookie" in c["reason"] for c in contribs)


def test_score_idp_starter_only_when_league_idp_enabled():
    lb = _player("DAL", "LB", depth=1, years_exp=3)
    # IDP off -> no points at all.
    off_pts, _ = team_assignment._score_player(
        lb,
        config=_config(),
        league_idp_enabled=False,
    )
    assert off_pts == 0
    # IDP on -> T5 starter (2).
    on_pts, _ = team_assignment._score_player(
        lb,
        config=_config(),
        league_idp_enabled=True,
    )
    assert on_pts == 2


def test_score_player_with_no_position_returns_zero():
    odd = {"team": "KC", "position": ""}
    pts, contribs = team_assignment._score_player(
        odd,
        config=_config(),
        league_idp_enabled=False,
    )
    assert pts == 0
    assert contribs == []


# ── End-to-end build_section ──────────────────────────────────────


def _stub_config(monkeypatch, tmp_path: Path):
    """Patch the module's _CONFIG_PATH to a tmp file so each test
    runs against an isolated config without leaking real favorites."""
    cfg_path = _config_path(
        tmp_path,
        {
            "favorites": {
                "jason": {"abbr": "MIN", "display": "Minnesota Vikings"},
                "brent": {"abbr": "BUF", "display": "Buffalo Bills"},
            },
            "displayNameAliases": {
                "jasonleetucker": "jason",
            },
            "thresholds": {"assignmentMinPoints": 10},
            "limits": {"maxTeamsPerOwner": 3},
        },
    )
    monkeypatch.setattr(team_assignment, "_CONFIG_PATH", cfg_path)


def test_build_section_assigns_favorite_with_zero_roster_score(monkeypatch, tmp_path: Path):
    """Favorite is included even when the manager has no roster
    contribution to that team."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings Fan")})
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": ["p1"]},
    ]
    nfl = {
        # Jason's only player is on KC, NOT MIN.
        "p1": _player("KC", "QB", depth=1, years_exp=5),
    }
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    assignments = section["assignments"]
    assert len(assignments) == 1
    a = assignments[0]
    assert a["favoriteKey"] == "jason"
    # First entry MUST be the favorite (Vikings) with score 0.
    assert a["nflTeams"][0]["abbr"] == "MIN"
    assert a["nflTeams"][0]["isFavorite"] is True
    assert a["nflTeams"][0]["score"] == 0


def test_build_section_includes_roster_based_when_above_threshold(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2", "p3"]},
    ]
    nfl = {
        "p1": _player("BUF", "QB", depth=1, years_exp=5),  # +10
        "p2": _player("BUF", "RB", depth=1, years_exp=3),  # +5
        "p3": _player("BUF", "WR", depth=2, years_exp=3),  # +2
    }
    # Total Bills score: 17.  Threshold is 10.  Should appear.
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    teams = section["assignments"][0]["nflTeams"]
    abbrs = [t["abbr"] for t in teams]
    assert "MIN" in abbrs  # favorite
    assert "BUF" in abbrs  # roster-based qualifier
    bills = next(t for t in teams if t["abbr"] == "BUF")
    assert bills["isFavorite"] is False
    assert bills["score"] == 17


def test_build_section_filters_below_threshold(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": ["p1"]},
    ]
    nfl = {
        # 1 RB committee on BUF = 2 points.  Below threshold of 10.
        "p1": _player("BUF", "RB", depth=2, years_exp=3),
    }
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    teams = section["assignments"][0]["nflTeams"]
    abbrs = [t["abbr"] for t in teams]
    # Only Vikings (favorite); BUF below threshold.
    assert abbrs == ["MIN"]


def test_build_section_caps_at_max_teams(monkeypatch, tmp_path: Path):
    """Even when 5 NFL teams qualify, return only the cap (default 3).
    Favorite always counts toward the cap."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": [f"p{i}" for i in range(1, 11)]},
    ]
    # Stock five different NFL teams with +10 each (QB anchor).
    nfl = {
        "p1": _player("BUF", "QB", depth=1, years_exp=5),
        "p2": _player("KC", "QB", depth=1, years_exp=5),
        "p3": _player("DET", "QB", depth=1, years_exp=5),
        "p4": _player("PHI", "QB", depth=1, years_exp=5),
        "p5": _player("BAL", "QB", depth=1, years_exp=5),
        # Ensure tiebreaker is alphabetical when scores are equal.
        "p6": _player("BUF", "RB", depth=1, years_exp=5),  # bumps BUF to 15
        "p7": _player("BUF", "WR", depth=1, years_exp=5),  # bumps BUF to 20
        "p8": _player("KC", "RB", depth=1, years_exp=5),  # bumps KC to 15
        "p9": _player("DET", "RB", depth=1, years_exp=5),  # bumps DET to 15
        "p10": _player("PHI", "RB", depth=1, years_exp=5),  # bumps PHI to 15
    }
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    teams = section["assignments"][0]["nflTeams"]
    abbrs = [t["abbr"] for t in teams]
    # Cap of 3: Vikings (favorite) + top 2 by score.  BUF has 20
    # which beats KC/DET/PHI's 15.  Tiebreak among the 15-scorers
    # is alphabetical.
    assert len(abbrs) == 3
    assert abbrs[0] == "MIN"  # favorite always first
    assert abbrs[1] == "BUF"  # 29 pts
    # 2nd place is one of KC/DET/PHI (all 15); alphabetical → DET.
    assert abbrs[2] == "DET"


def test_build_section_alias_resolves_jasonleetucker(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "JasonLeeTucker")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": []}]
    snap = _snapshot(rosters, {}, mgrs)
    section = team_assignment.build_section(snap)
    a = section["assignments"][0]
    assert a["favoriteKey"] == "jason"
    assert a["nflTeams"][0]["abbr"] == "MIN"


def test_build_section_no_current_season_returns_empty():
    snap = PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[],
    )
    section = team_assignment.build_section(snap)
    assert section["assignments"] == []
    assert section["currentSeason"] is None


def test_build_section_emits_contributors_breakdown(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2"]}]
    nfl = {
        "p1": _player("BUF", "QB", depth=1, years_exp=5, name="Josh Allen"),
        "p2": _player("BUF", "WR", depth=1, years_exp=3, name="Stefon Diggs"),
    }
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    bills = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "BUF")
    contribs = bills["contributors"]
    # Expect one contributor row per scoring rule that fired — here one
    # each (QB anchor, WR starter), not two apiece.
    assert len(contribs) == 2
    # Every contributor has player + points + reason.
    for c in contribs:
        assert "player" in c and "points" in c and "reason" in c
    # Allen contributes 10, Diggs 5 → Bills total 15.
    assert bills["score"] == 15
    # The breakdown must add up to the score the UI renders.
    assert sum(c["points"] for c in contribs) == bills["score"]


def test_build_section_idp_off_excludes_idp_starter_points(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1"]}]
    nfl = {"p1": _player("DAL", "LB", depth=1, years_exp=3)}
    snap = _snapshot(rosters, nfl, mgrs, idp=False)
    section = team_assignment.build_section(snap)
    teams = section["assignments"][0]["nflTeams"]
    abbrs = [t["abbr"] for t in teams]
    # IDP off: LB is worth zero points → DAL not above threshold.
    assert abbrs == ["MIN"]


def test_build_section_idp_on_includes_idp_starter_when_above_threshold(
    monkeypatch, tmp_path: Path
):
    """With IDP enabled, a couple of starting LBs on the same NFL
    team should accumulate enough points to clear the threshold."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason", "Vikings")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": [f"p{i}" for i in range(1, 6)]}]
    # 5 starting LBs on DAL = 10 points (5 × 2).  Threshold is 10.
    nfl = {f"p{i}": _player("DAL", "LB", depth=1, years_exp=3) for i in range(1, 6)}
    snap = _snapshot(rosters, nfl, mgrs, idp=True)
    section = team_assignment.build_section(snap)
    teams = section["assignments"][0]["nflTeams"]
    abbrs = [t["abbr"] for t in teams]
    assert "DAL" in abbrs


def test_build_section_no_favorite_match_still_emits_roster_assignment(monkeypatch, tmp_path: Path):
    """Manager with no favorite configured still gets roster-based
    assignments above the threshold."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Stranger")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1", "p2"]}]
    nfl = {
        "p1": _player("KC", "QB", depth=1, years_exp=5),  # +10
        "p2": _player("KC", "RB", depth=1, years_exp=3),  # +5
    }
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    a = section["assignments"][0]
    assert a["favoriteKey"] is None
    teams = a["nflTeams"]
    assert len(teams) == 1  # No favorite, just the one roster qualifier.
    assert teams[0]["abbr"] == "KC"
    assert teams[0]["isFavorite"] is False


def test_build_section_orders_assignments_alphabetically_by_display_name(
    monkeypatch, tmp_path: Path
):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(
        by_owner_id={
            "oA": _manager("oA", "Zane"),
            "oB": _manager("oB", "Alex"),
            "oC": _manager("oC", "Brent"),
        }
    )
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": []},
        {"roster_id": 2, "owner_id": "oB", "players": []},
        {"roster_id": 3, "owner_id": "oC", "players": []},
    ]
    snap = _snapshot(rosters, {}, mgrs)
    section = team_assignment.build_section(snap)
    names = [a["displayName"] for a in section["assignments"]]
    assert names == ["Alex", "Brent", "Zane"]


# ── Integration with public_contract ──────────────────────────────


def test_section_registered_in_public_contract():
    from src.public_league.public_contract import (
        _SECTION_BUILDERS,
        PUBLIC_SECTION_KEYS,
    )

    assert "teamAssignment" in _SECTION_BUILDERS
    assert "teamAssignment" in PUBLIC_SECTION_KEYS


def test_section_payload_safe(monkeypatch, tmp_path: Path):
    """Section's output passes the public-payload safety check —
    no private field names leak."""
    from src.public_league.public_contract import assert_public_payload_safe

    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "Jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["p1"]}]
    nfl = {"p1": _player("KC", "QB", depth=1, years_exp=5)}
    snap = _snapshot(rosters, nfl, mgrs)
    section = team_assignment.build_section(snap)
    assert_public_payload_safe(section)
