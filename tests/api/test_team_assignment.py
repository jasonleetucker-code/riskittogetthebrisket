"""Tests for ``src/api/team_assignment.py`` — the NFL Team Affinity model.

Covers config load/merge, favorite resolution (direct + alias +
missing, mechanism unchanged from the old points-based model), the
canonical-value formula (base value passthrough, the ONE starting-QB
2.0x multiplier and its "unknown never becomes starter" fallback),
affinity-share aggregation, the FIXED favorite + up to 4
coverage-maximizing team selection (``_assign_coverage_maximizing_teams``
-- natural top-4 per manager, then a single deterministic cross-manager
repair pass for any of the 32 real NFL teams nobody covers), and the
missing-is-never-zero / Meaningful-Core-reuse invariants the owner
mandate is built on.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.api import team_assignment
from src.public_league.identity import Manager, ManagerRegistry, TeamAlias
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.roster_intel.core import build_meaningful_core
from src.ros.lineup import RosterPlayer


# ── Helpers ────────────────────────────────────────────────────────

_DEFAULT_SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"]


def _season(rosters, *, slots=None):
    return SeasonSnapshot(
        season="2026",
        league_id="L1",
        league={"settings": {}, "roster_positions": list(slots or _DEFAULT_SLOTS)},
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


def _snapshot(rosters, nfl_players, managers, *, slots=None):
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[_season(rosters, slots=slots)],
        managers=managers,
        nfl_players=nfl_players,
    )


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


def _nfl_player(team, position, *, depth=1, years_exp=2, name=None):
    """Synthesize a Sleeper-shaped player record for the QB-starter signal."""
    return {
        "team": team,
        "position": position,
        "depth_chart_order": depth,
        "years_exp": years_exp,
        "full_name": name or f"{position}-{team}-{depth}",
    }


def _row(canonical_name, position, team, value, *, player_id=None, asset_class="offense"):
    return {
        "canonicalName": canonical_name,
        "displayName": canonical_name,
        "position": position,
        "team": team,
        "rankDerivedValue": value,
        "playerId": player_id,
        "assetClass": asset_class,
    }


def _contract(rows, teams, *, slots=None):
    """``teams`` is ``{ownerId: [canonicalName, ...]}``.  ``playerIds`` is
    derived from each row's ``playerId`` (or omitted when None, mirroring
    a name the Sleeper roster carries with no resolvable id)."""
    positions = {r["canonicalName"]: r["position"] for r in rows}
    by_name = {r["canonicalName"]: r for r in rows}
    team_dicts = []
    for owner_id, names in teams.items():
        team_dicts.append(
            {
                "ownerId": owner_id,
                "name": f"team-{owner_id}",
                "players": list(names),
                "playerIds": [by_name.get(n, {}).get("playerId") for n in names],
            }
        )
    return {
        "meta": {"leagueKey": "dynasty_main"},
        "playersArray": rows,
        "sleeper": {
            "teams": team_dicts,
            "rosterPositions": list(slots or _DEFAULT_SLOTS),
            "positions": positions,
            "fantasyPositions": {},
        },
    }


def _config_path(tmp_path: Path, body: dict) -> Path:
    p = tmp_path / "team_assignment.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _stub_config(monkeypatch, tmp_path: Path, *, qb_multiplier=2.0):
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
            "weights": {"nflStartingQbMultiplier": qb_multiplier},
            "limits": {},
        },
    )
    monkeypatch.setattr(team_assignment, "_CONFIG_PATH", cfg_path)


# ── Config loader ─────────────────────────────────────────────────


def test_load_config_uses_defaults_when_file_missing(tmp_path: Path):
    cfg = team_assignment.load_config(tmp_path / "missing.json")
    assert cfg["weights"]["nflStartingQbMultiplier"] == 2.0
    assert cfg["limits"] == {}
    assert cfg["favorites"] == {}
    assert "thresholds" not in cfg


def test_load_config_falls_back_on_malformed_json(tmp_path: Path):
    p = tmp_path / "team_assignment.json"
    p.write_text("not-json", encoding="utf-8")
    cfg = team_assignment.load_config(p)
    assert cfg["weights"]["nflStartingQbMultiplier"] == 2.0


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


def test_no_dead_weight_or_threshold_knobs_remain():
    """The old per-position point weights AND the percentage threshold
    are retired entirely -- one weight (the QB multiplier), zero
    thresholds.  The non-favorite team count is a hardcoded constant,
    not a config knob at all."""
    assert set(team_assignment._DEFAULT_CONFIG["weights"]) == {"nflStartingQbMultiplier"}
    assert "thresholds" not in team_assignment._DEFAULT_CONFIG
    assert team_assignment._NON_FAVORITE_TEAMS_PER_OWNER == 4


def test_shipped_config_declares_exactly_the_live_knobs():
    shipped = json.loads(team_assignment._CONFIG_PATH.read_text(encoding="utf-8"))
    weights = {k for k in shipped["weights"] if k != "_doc"}
    assert weights == set(team_assignment._DEFAULT_CONFIG["weights"])
    assert "thresholds" not in shipped


def test_load_config_merges_partial_user_config_over_defaults(tmp_path: Path):
    p = _config_path(tmp_path, {"weights": {"nflStartingQbMultiplier": 3.0}})
    cfg = team_assignment.load_config(p)
    assert cfg["weights"]["nflStartingQbMultiplier"] == 3.0
    assert "thresholds" not in cfg


# ── Favorite resolution (unchanged mechanism, test 19) ────────────


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


def test_build_section_alias_resolves_jasonleetucker(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "JasonLeeTucker")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": []}]
    snap = _snapshot(rosters, {}, mgrs)
    section = team_assignment.build_section(snap, None)
    a = section["assignments"][0]
    assert a["favoriteKey"] == "jason"
    assert a["nflTeams"][0]["abbr"] == "MIN"


# ── Owner worked example: the canonical formula, exactly ──────────


def test_owner_worked_example_dart_nabers_18000(monkeypatch, tmp_path: Path):
    """Jackson Dart (5,000, NFL starting QB) x2 + Malik Nabers (8,000)
    = 18,000 MIN affinity -- the owner's own worked example, verbatim."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["Jackson Dart", "Malik Nabers"]}]
    nfl = {"sqb": _nfl_player("MIN", "QB", depth=1)}
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "WR", "BN"])
    rows = [
        _row("Jackson Dart", "QB", "MIN", 5000, player_id="sqb"),
        _row("Malik Nabers", "WR", "MIN", 8000, player_id="wr1"),
    ]
    contract = _contract(rows, {"oA": ["Jackson Dart", "Malik Nabers"]}, slots=["QB", "WR", "BN"])
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    assert a["totalWeightedCoreValue"] == 18000.0
    min_team = next(t for t in a["nflTeams"] if t["abbr"] == "MIN")
    assert min_team["affinityScore"] == 18000.0
    dart = next(c for c in min_team["contributors"] if c["canonicalName"] == "Jackson Dart")
    assert dart["canonicalValue"] == 5000.0
    assert dart["multiplier"] == 2.0
    assert dart["multiplierReason"] == "nfl_starting_qb"
    assert dart["weightedValue"] == 10000.0
    nabers = next(c for c in min_team["contributors"] if c["canonicalName"] == "Malik Nabers")
    assert nabers["multiplier"] == 1.0
    assert nabers["weightedValue"] == 8000.0


def test_canonical_value_player_contributes_actual_value(monkeypatch, tmp_path: Path):
    """Test 2: a non-QB core member contributes exactly his canonical
    value, no multiplier."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["Some WR"]}]
    rows = [_row("Some WR", "WR", "KC", 4321, player_id="w1")]
    contract = _contract(rows, {"oA": ["Some WR"]}, slots=["WR", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["WR", "BN"])
    section = team_assignment.build_section(snap, contract)
    kc = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "KC")
    assert kc["affinityScore"] == 4321.0
    assert kc["contributors"][0]["canonicalValue"] == 4321.0
    assert kc["contributors"][0]["multiplier"] == 1.0


def test_nfl_starting_qb_receives_exactly_2x(monkeypatch, tmp_path: Path):
    """Test 3."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["QB One"]}]
    nfl = {"sid": _nfl_player("KC", "QB", depth=1)}
    rows = [_row("QB One", "QB", "KC", 3000, player_id="sid")]
    contract = _contract(rows, {"oA": ["QB One"]}, slots=["QB", "BN"])
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "BN"])
    section = team_assignment.build_section(snap, contract)
    kc = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "KC")
    c = kc["contributors"][0]
    assert c["multiplier"] == 2.0
    assert c["multiplierReason"] == "nfl_starting_qb"
    assert c["weightedValue"] == 6000.0


def test_backup_qb_does_not_receive_2x(monkeypatch, tmp_path: Path):
    """Test 4."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["QB Two"]}]
    nfl = {"bid": _nfl_player("KC", "QB", depth=2)}
    rows = [_row("QB Two", "QB", "KC", 500, player_id="bid")]
    contract = _contract(rows, {"oA": ["QB Two"]}, slots=["QB", "BN"])
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "BN"])
    section = team_assignment.build_section(snap, contract)
    kc = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "KC")
    c = kc["contributors"][0]
    assert c["multiplier"] == 1.0
    assert c["multiplierReason"] == "qb_not_starting"
    assert c["weightedValue"] == 500.0


def test_unknown_qb_starter_state_does_not_receive_2x(monkeypatch, tmp_path: Path):
    """Test 5: no Sleeper player directory at all -- unknown never
    becomes starter."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["QB Three"]}]
    rows = [_row("QB Three", "QB", "KC", 500, player_id="uid")]
    contract = _contract(rows, {"oA": ["QB Three"]}, slots=["QB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["QB", "BN"])  # empty nfl_players
    section = team_assignment.build_section(snap, contract)
    assert section["qbSignalAvailable"] is False
    assert team_assignment.DEGRADED_NO_QB_SIGNAL in section["degradedReasons"]
    kc = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "KC")
    c = kc["contributors"][0]
    assert c["multiplier"] == 1.0
    assert c["multiplierReason"] == "starter_status_unknown"


def test_unresolvable_sleeper_id_also_falls_back_to_unknown(monkeypatch, tmp_path: Path):
    """A canonical name with no matched Sleeper id (playerId=None on the
    board row) cannot be looked up in the NFL depth chart at all."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["QB Four"]}]
    nfl = {"someone_else": _nfl_player("KC", "QB", depth=1)}
    rows = [_row("QB Four", "QB", "KC", 500, player_id=None)]
    contract = _contract(rows, {"oA": ["QB Four"]}, slots=["QB", "BN"])
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "BN"])
    section = team_assignment.build_section(snap, contract)
    kc = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "KC")
    c = kc["contributors"][0]
    assert c["multiplier"] == 1.0
    assert c["multiplierReason"] == "starter_status_unknown"
    assert c["sleeperPlayerId"] is None


# ── Aggregation / qualification ────────────────────────────────────


def test_two_teammates_aggregate_correctly(monkeypatch, tmp_path: Path):
    """Test 6: QB = 5,000 x2 + WR = 8,000 -> team score = 18,000
    (same shape as the owner example, phrased as its own test)."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["Q", "W"]}]
    nfl = {"q": _nfl_player("SEA", "QB", depth=1)}
    rows = [
        _row("Q", "QB", "SEA", 5000, player_id="q"),
        _row("W", "WR", "SEA", 8000, player_id="w"),
    ]
    contract = _contract(rows, {"oA": ["Q", "W"]}, slots=["QB", "WR", "BN"])
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "WR", "BN"])
    section = team_assignment.build_section(snap, contract)
    sea = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "SEA")
    assert sea["affinityScore"] == 18000.0


def test_affinity_share_denominator_is_total_weighted_core_value(monkeypatch, tmp_path: Path):
    """Test 7: two NFL teams, verify shares sum against the TOTAL. Both
    show -- there are only two real candidate teams, well under the
    4-team cap, so no selection logic excludes either."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A", "B"]}]
    rows = [
        _row("A", "RB", "SEA", 9000, player_id="a"),
        _row("B", "RB", "KC", 1000, player_id="b"),
    ]
    contract = _contract(rows, {"oA": ["A", "B"]}, slots=["RB", "RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    assert a["totalWeightedCoreValue"] == 10000.0
    sea = next(t for t in a["nflTeams"] if t["abbr"] == "SEA")
    assert sea["affinityShare"] == 0.9
    abbrs = {t["abbr"] for t in a["nflTeams"]}
    assert abbrs == {"SEA", "KC"}


def test_non_favorite_teams_always_shown_regardless_of_lopsided_share(monkeypatch, tmp_path: Path):
    """No percentage threshold exists any more -- a team that would
    have failed the old 10% cutoff (900/10000 = 9%) is still shown,
    because selection is now purely about the 4-team cap, never a
    share minimum."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A", "B"]}]
    rows = [
        _row("A", "RB", "SEA", 9100, player_id="a"),
        _row("B", "RB", "KC", 900, player_id="b"),
    ]
    contract = _contract(rows, {"oA": ["A", "B"]}, slots=["RB", "RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    abbrs = {t["abbr"] for t in section["assignments"][0]["nflTeams"]}
    assert abbrs == {"SEA", "KC"}


def test_favorite_remains_assigned_with_zero_affinity(monkeypatch, tmp_path: Path):
    """Test 10: favorite has zero roster contribution, still shown."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A"]}]
    rows = [_row("A", "RB", "KC", 9999, player_id="a")]
    contract = _contract(rows, {"oA": ["A"]}, slots=["RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    assert a["nflTeams"][0]["abbr"] == "MIN"
    assert a["nflTeams"][0]["isFavorite"] is True
    assert a["nflTeams"][0]["affinityScore"] == 0.0
    assert a["nflTeams"][0]["qualifiesByRoster"] is False
    assert a["nflTeams"][0]["assignmentReason"] == "favorite"


def test_natural_top4_selected_with_deterministic_sort_no_repair_needed(
    monkeypatch, tmp_path: Path
):
    """Favorite + up to 4 non-favorites, sorted by (affinityScore desc,
    abbr asc).  Exactly 4 real non-favorite candidates exist here, so
    they all fit the cap with no coverage-repair swap needed."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    names = [f"P{i}" for i in range(5)]
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": names}]
    rows = [
        _row("P0", "RB", "BUF", 5000, player_id="p0"),
        _row("P1", "RB", "KC", 1000, player_id="p1"),
        _row("P2", "RB", "DET", 1000, player_id="p2"),
        _row("P3", "RB", "PHI", 1000, player_id="p3"),
        _row("P4", "RB", "MIN", 100, player_id="p4"),  # favorite, tiny
    ]
    contract = _contract(rows, {"oA": names}, slots=["RB", "RB", "RB", "RB", "RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "RB", "RB", "RB", "RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    abbrs = [t["abbr"] for t in section["assignments"][0]["nflTeams"]]
    assert len(abbrs) == 5
    assert abbrs[0] == "MIN"  # favorite always first
    assert abbrs[1] == "BUF"  # clearly highest score
    # KC, DET, PHI tied at the same score -- alphabetical order
    assert abbrs[2:5] == ["DET", "KC", "PHI"]
    reasons = {t["abbr"]: t["assignmentReason"] for t in section["assignments"][0]["nflTeams"]}
    assert reasons["MIN"] == "favorite"
    assert all(reasons[a] == "top_affinity" for a in ("BUF", "KC", "DET", "PHI"))


def test_fifth_candidate_naturally_excluded_not_silently_dropped(monkeypatch, tmp_path: Path):
    """A manager with 5 real non-favorite candidate teams keeps only
    the top 4 by score; the 5th (weakest) is excluded from this
    single-manager league by construction -- with no other manager to
    keep it covered, repair cannot safely place it either, so it is
    reported in unresolvedCoverageGaps rather than silently vanishing."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    names = [f"P{i}" for i in range(5)]
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": names}]
    rows = [
        _row("P0", "RB", "BUF", 5000, player_id="p0"),
        _row("P1", "RB", "KC", 4000, player_id="p1"),
        _row("P2", "RB", "DET", 3000, player_id="p2"),
        _row("P3", "RB", "PHI", 2000, player_id="p3"),
        _row("P4", "RB", "SEA", 1000, player_id="p4"),
    ]
    contract = _contract(rows, {"oA": names}, slots=["RB", "RB", "RB", "RB", "RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "RB", "RB", "RB", "RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    abbrs = {t["abbr"] for t in section["assignments"][0]["nflTeams"]}
    assert abbrs == {"BUF", "KC", "DET", "PHI"}
    assert "SEA" not in abbrs
    assert "SEA" in section["unresolvedCoverageGaps"]


def test_missing_canonical_value_is_not_converted_to_zero(monkeypatch, tmp_path: Path):
    """Test 13: an unpriced rostered player is excluded from the core
    (never seated at 0) and reported via unpricedCount."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["Priced", "Unpriced"]}]
    rows = [
        _row("Priced", "RB", "KC", 4000, player_id="p"),
        # "Unpriced" has no matching playersArray row at all -> no value.
    ]
    contract = _contract(rows, {"oA": ["Priced", "Unpriced"]}, slots=["RB", "RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    assert a["unpricedCount"] == 1
    assert a["totalWeightedCoreValue"] == 4000.0
    kc = next(t for t in a["nflTeams"] if t["abbr"] == "KC")
    assert len(kc["contributors"]) == 1


def test_meaningful_core_unavailable_for_one_team_is_not_a_confident_empty_answer(
    monkeypatch, tmp_path: Path
):
    """Test 14 (per-team narrower case): contract is usable league-wide,
    but THIS manager's roster has no matching pool -- must say so, not
    render a silent empty roster-based result indistinguishable from
    'scored, nothing qualified'."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(
        by_owner_id={
            "oA": _manager("oA", "nofavorite-a"),
            "oB": _manager("oB", "nofavorite-b"),
        }
    )
    rosters = [
        {"roster_id": 1, "owner_id": "oA", "players": ["A"]},
        {"roster_id": 2, "owner_id": "oB", "players": ["B"]},
    ]
    rows = [_row("A", "RB", "KC", 4000, player_id="a")]
    # Contract only carries oA's team -- oB is absent from sleeper.teams.
    contract = _contract(rows, {"oA": ["A"]}, slots=["RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    assert section["rosterScoringAvailable"] is True  # league-wide is fine
    by_owner = {a["ownerId"]: a for a in section["assignments"]}
    assert by_owner["oA"]["rosterScored"] is True
    assert by_owner["oB"]["rosterScored"] is False
    assert (
        by_owner["oB"]["rosterUnavailableReason"] == team_assignment.ROSTER_REASON_NOT_IN_CONTRACT
    )
    assert by_owner["oB"]["totalWeightedCoreValue"] is None


def test_favorite_survives_degraded_roster_intelligence(monkeypatch, tmp_path: Path):
    """Test 15: no canonical contract at all -- favorite still shown,
    with a truthful degraded reason, not a confident empty roster."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A"]}]
    snap = _snapshot(rosters, {}, mgrs)
    section = team_assignment.build_section(snap, None)
    assert section["available"] is True
    assert section["rosterScoringAvailable"] is False
    assert team_assignment.DEGRADED_NO_CONTRACT in section["degradedReasons"]
    a = section["assignments"][0]
    assert a["rosterScored"] is False
    assert a["nflTeams"][0]["abbr"] == "MIN"
    assert a["nflTeams"][0]["isFavorite"] is True


def test_idp_players_use_canonical_value_with_no_penalty(monkeypatch, tmp_path: Path):
    """Test 16: an LB counts its full canonical value like any other
    position -- no arbitrary IDP discount, no special-case gate."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["LB One"]}]
    rows = [_row("LB One", "LB", "DAL", 2500, player_id="lb1", asset_class="idp")]
    contract = _contract(rows, {"oA": ["LB One"]}, slots=["LB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["LB", "BN"])
    section = team_assignment.build_section(snap, contract)
    dal = next(t for t in section["assignments"][0]["nflTeams"] if t["abbr"] == "DAL")
    c = dal["contributors"][0]
    assert c["canonicalValue"] == 2500.0
    assert c["weightedValue"] == 2500.0
    assert c["multiplier"] == 1.0
    assert c["multiplierReason"] == "not_qb"


def test_deep_non_core_roster_players_contribute_nothing(monkeypatch, tmp_path: Path):
    """Test 17: a roster with far more players than starter + reserve
    demand -- the excess never enters the core, and their value never
    reaches the total."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    # 1 RB slot + 1 BN (no reserve demand configured beyond the core's
    # own multiplier ceiling) -- five RBs on the roster, only a few can
    # ever be seated.
    names = [f"RB{i}" for i in range(6)]
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": names}]
    rows = [_row(n, "RB", "KC", 1000 * (i + 1), player_id=n.lower()) for i, n in enumerate(names)]
    contract = _contract(rows, {"oA": names}, slots=["RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    core = build_meaningful_core(
        [
            RosterPlayer(player_id=n, canonical_name=n, position="RB", ros_value=1000.0 * (i + 1))
            for i, n in enumerate(names)
        ],
        ["RB", "BN"],
    )
    seated = len(core.members)
    assert seated < len(names)
    kc = next(t for t in a["nflTeams"] if t["abbr"] == "KC")
    assert len(kc["contributors"]) == seated


def test_flex_players_are_not_selected_a_second_time(monkeypatch, tmp_path: Path):
    """Test 18: the total weighted core value must equal exactly the
    sum over the Meaningful Core's own members -- never double-counting
    a FLEX-assigned player against both his native slot and FLEX."""
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "nofavorite")})
    names = ["RB1", "RB2", "RB3", "WR1"]
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": names}]
    rows = [
        _row("RB1", "RB", "KC", 5000, player_id="rb1"),
        _row("RB2", "RB", "KC", 4000, player_id="rb2"),
        _row("RB3", "RB", "KC", 3000, player_id="rb3"),  # eligible for FLEX
        _row("WR1", "WR", "KC", 100, player_id="wr1"),
    ]
    slots = ["RB", "RB", "FLEX", "BN"]
    contract = _contract(rows, {"oA": names}, slots=slots)
    snap = _snapshot(rosters, {}, mgrs, slots=slots)
    section = team_assignment.build_section(snap, contract)
    a = section["assignments"][0]
    # 5000 + 4000 + 3000 = 12000 seated as starters (RB3 fills FLEX);
    # WR1 (100) is the sole reserve candidate depending on demand -- in
    # any case no player's value can appear twice.
    kc = next(t for t in a["nflTeams"] if t["abbr"] == "KC")
    names_seen = [c["canonicalName"] for c in kc["contributors"]]
    assert len(names_seen) == len(set(names_seen))


# ── Coverage-maximizing selection (cross-manager) ──────────────────
#
# Direct, pure-function tests of ``_assign_coverage_maximizing_teams``
# -- no snapshot/contract fixtures needed.  ``ALL_TEAMS`` below is a
# small closed universe (never the real 32) so gap/uncoverable-team
# behavior is exercisable without constructing every real NFL team.


_ALL_TEAMS = frozenset({"BUF", "KC", "DET", "PHI", "SEA", "CLE", "MIA", "DAL"})


def _assign(owner_ids, scores, holds_qb=None, favorites=None, all_teams=None, **kwargs):
    return team_assignment._assign_coverage_maximizing_teams(
        owner_ids,
        scores,
        holds_qb or {oid: {} for oid in owner_ids},
        favorites or {oid: None for oid in owner_ids},
        all_teams=all_teams if all_teams is not None else _ALL_TEAMS,
        **kwargs,
    )


def test_natural_top4_when_league_already_covers_everything():
    """Two managers whose natural top-4s collectively already cover
    every team with any leaguewide affinity -- no repair fires."""
    owner_ids = ["m1", "m2"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000},
        "m2": {"SEA": 5000, "CLE": 4000, "MIA": 3000, "DAL": 2000},
    }
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    assert {c["abbr"] for c in non_fav["m1"]} == {"BUF", "KC", "DET", "PHI"}
    assert {c["abbr"] for c in non_fav["m2"]} == {"SEA", "CLE", "MIA", "DAL"}
    assert all(c["reason"] == "top_affinity" for c in non_fav["m1"] + non_fav["m2"])
    assert uncoverable == []
    assert unresolved == []


def test_coverage_gap_resolved_by_clear_best_fit_swap():
    """CLE is uncovered.  m1 is the only manager with CLE affinity;
    m1's weakest natural team (PHI) is also naturally held by m2, so
    donating it is safe -- m1 gains CLE via coverage_repair, m2 keeps
    PHI untouched."""
    owner_ids = ["m1", "m2"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 500},
        "m2": {"SEA": 5000, "MIA": 4000, "DAL": 3000, "PHI": 2000},
    }
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    m1_abbrs = {c["abbr"] for c in non_fav["m1"]}
    assert "CLE" in m1_abbrs
    assert "PHI" not in m1_abbrs
    cle_entry = next(c for c in non_fav["m1"] if c["abbr"] == "CLE")
    assert cle_entry["reason"] == "coverage_repair"
    assert {c["abbr"] for c in non_fav["m2"]} == {"SEA", "MIA", "DAL", "PHI"}
    assert uncoverable == []
    assert unresolved == []


def test_gap_falls_to_second_best_fit_when_best_fit_cannot_afford_swap():
    """m1 has the highest CLE score, but ALL FOUR of m1's natural
    teams (BUF/KC/DET/PHI) are solely covered by m1 -- nobody else's
    natural list touches any of them, so no safe donation exists on
    m1.  Repair falls through to m2 (lower CLE score, but m2's
    weakest natural team NE is also a third manager m3's sole
    candidate, so it is safe to donate)."""
    owner_ids = ["m1", "m2", "m3"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 900},
        "m2": {"SEA": 5000, "MIA": 4000, "DAL": 3000, "NE": 2500, "CLE": 100},
        "m3": {"NE": 1000},
    }
    all_teams = _ALL_TEAMS | {"NE"}
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores, all_teams=all_teams)
    # m1's slots are untouched -- no safe donor was found on m1.
    assert {c["abbr"] for c in non_fav["m1"]} == {"BUF", "KC", "DET", "PHI"}
    m2_abbrs = {c["abbr"] for c in non_fav["m2"]}
    assert "CLE" in m2_abbrs
    assert "NE" not in m2_abbrs
    cle_entry = next(c for c in non_fav["m2"] if c["abbr"] == "CLE")
    assert cle_entry["reason"] == "coverage_repair"
    assert {c["abbr"] for c in non_fav["m3"]} == {"NE"}
    assert uncoverable == []
    assert unresolved == []


def test_donor_search_tries_next_weakest_before_giving_up_on_manager():
    """m1's single weakest team (PHI) is solely-covered (unsafe), but
    the second-weakest (DET) is safely covered elsewhere -- the search
    must not give up on m1 after the first unsafe candidate."""
    owner_ids = ["m1", "m2"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 900},
        "m2": {"SEA": 5000, "DET": 200},  # DET also held by m2 -> safe to donate
    }
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    m1_abbrs = {c["abbr"] for c in non_fav["m1"]}
    assert "CLE" in m1_abbrs
    assert "PHI" in m1_abbrs  # weakest kept -- it was unsafe to donate
    assert "DET" not in m1_abbrs  # second-weakest donated instead
    assert {c["abbr"] for c in non_fav["m2"]} == {"SEA", "DET"}
    # MIA/DAL have zero affinity anywhere in this fixture -- genuinely
    # uncoverable, not a failure of the repair logic under test here.
    assert set(uncoverable) == {"MIA", "DAL"}
    assert unresolved == []


def test_totally_uncoverable_team_reported_transparently():
    """DAL has zero affinity anywhere in the league -- reported in
    uncoverable_teams, never assigned to anyone."""
    owner_ids = ["m1"]
    scores = {"m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000}}
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    assert "DAL" in uncoverable
    assert all("DAL" != c["abbr"] for c in non_fav["m1"])
    assert "DAL" not in unresolved


def test_qb_holder_tiebreak_decides_between_equal_scored_managers():
    """m1 and m2 are tied exactly on CLE score; only m2 holds CLE's
    starting QB -- the tiebreak orders m2 ahead of m1 as CLE's repair
    candidate, so m2 is tried first and wins immediately."""
    owner_ids = ["m1", "m2"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 1000},
        "m2": {"SEA": 5000, "MIA": 4000, "DAL": 3000, "PHI": 2000, "CLE": 1000},
    }
    holds_qb = {
        "m1": {"CLE": False},
        "m2": {"CLE": True},
    }
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores, holds_qb)
    assert "CLE" not in {c["abbr"] for c in non_fav["m1"]}
    assert "CLE" in {c["abbr"] for c in non_fav["m2"]}


def test_manager_with_fewer_than_four_real_candidates_not_padded():
    owner_ids = ["m1"]
    scores = {"m1": {"BUF": 5000, "KC": 4000}}
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    assert {c["abbr"] for c in non_fav["m1"]} == {"BUF", "KC"}
    assert len(non_fav["m1"]) == 2


def test_selection_deterministic_across_repeated_calls():
    owner_ids = ["m1", "m2", "m3"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 900},
        "m2": {"SEA": 5000, "MIA": 4000, "DAL": 3000},
        "m3": {"CLE": 100},
    }
    result_a = _assign(owner_ids, scores)
    result_b = _assign(owner_ids, scores)
    assert result_a == result_b


def test_zero_or_absent_score_never_assigned():
    """A team present in ``scores`` at 0 (defensive input -- callers
    are supposed to omit it) must never be treated as real affinity."""
    owner_ids = ["m1"]
    scores = {"m1": {"BUF": 5000, "CLE": 0}}
    non_fav, uncoverable, unresolved = _assign(owner_ids, scores)
    assert "CLE" not in {c["abbr"] for c in non_fav["m1"]}


def test_favorite_excluded_from_gap_and_natural_candidacy():
    """A team that is someone's favorite counts as covered and is
    never separately assigned as a repair -- it also never appears as
    a natural candidate for the manager whose favorite it is.  m2 has
    enough OTHER real candidates that its own marginal CLE affinity is
    naturally excluded from its top-4 anyway, isolating what this test
    actually checks: CLE never becomes a repair target for m2 because
    it is already covered by m1's favorite."""
    owner_ids = ["m1", "m2"]
    scores = {
        "m1": {"BUF": 5000, "KC": 4000, "DET": 3000, "PHI": 2000, "CLE": 9999},
        "m2": {"SEA": 5000, "MIA": 4000, "DAL": 3000, "NE": 2000, "CLE": 100},
    }
    favorites = {"m1": "CLE", "m2": None}
    all_teams = _ALL_TEAMS | {"NE"}
    non_fav, uncoverable, unresolved = _assign(
        owner_ids, scores, favorites=favorites, all_teams=all_teams
    )
    # CLE is m1's favorite, so it is excluded from m1's own natural
    # candidacy even though it scores highest of all -- favorites never
    # compete for a non-favorite slot.
    assert "CLE" not in {c["abbr"] for c in non_fav["m1"]}
    assert {c["abbr"] for c in non_fav["m1"]} == {"BUF", "KC", "DET", "PHI"}
    # CLE is covered (via m1's favorite) so it is not a gap for m2 either
    # -- m2's own top-4 naturally excludes its marginal CLE affinity.
    assert "CLE" not in {c["abbr"] for c in non_fav["m2"]}
    assert {c["abbr"] for c in non_fav["m2"]} == {"SEA", "MIA", "DAL", "NE"}
    assert uncoverable == []
    assert unresolved == []


def test_coverage_summary_arithmetic_and_disjointness(monkeypatch, tmp_path: Path):
    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A"]}]
    rows = [_row("A", "RB", "KC", 4000, player_id="a")]
    contract = _contract(rows, {"oA": ["A"]}, slots=["RB", "BN"])
    snap = _snapshot(rosters, {}, mgrs, slots=["RB", "BN"])
    section = team_assignment.build_section(snap, contract)
    summary = section["coverageSummary"]
    assert (
        summary["coveredTeams"] + summary["uncoverableCount"] + summary["unresolvedGapCount"]
        == summary["totalNflTeams"]
    )
    assert not (set(section["uncoverableTeams"]) & set(section["unresolvedCoverageGaps"]))


# ── Structural / global availability ───────────────────────────────


def test_build_section_no_current_season_returns_empty():
    snap = PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=[],
    )
    section = team_assignment.build_section(snap, None)
    assert section["assignments"] == []
    assert section["currentSeason"] is None


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
    section = team_assignment.build_section(snap, None)
    names = [a["displayName"] for a in section["assignments"]]
    assert names == ["Alex", "Brent", "Zane"]


# ── Integration with public_contract ──────────────────────────────


def test_section_registered_in_public_contract():
    from src.public_league.public_contract import (
        _LAZY_SECTION_BUILDERS,
        PRIVATE_INTELLIGENCE_SECTIONS,
        PUBLIC_SECTION_KEYS,
    )

    assert "teamAssignment" in _LAZY_SECTION_BUILDERS
    assert "teamAssignment" in PUBLIC_SECTION_KEYS
    assert "teamAssignment" in PRIVATE_INTELLIGENCE_SECTIONS


def test_section_payload_safe(monkeypatch, tmp_path: Path):
    """No private field names leak, regardless of the section's auth
    gate (the safety assertion runs unconditionally)."""
    from src.public_league.public_contract import assert_public_payload_safe

    _stub_config(monkeypatch, tmp_path)
    mgrs = ManagerRegistry(by_owner_id={"oA": _manager("oA", "jason")})
    rosters = [{"roster_id": 1, "owner_id": "oA", "players": ["A"]}]
    nfl = {"a": _nfl_player("KC", "QB", depth=1)}
    rows = [_row("A", "QB", "KC", 5000, player_id="a")]
    contract = _contract(rows, {"oA": ["A"]}, slots=["QB", "BN"])
    snap = _snapshot(rosters, nfl, mgrs, slots=["QB", "BN"])
    section = team_assignment.build_section(snap, contract)
    assert_public_payload_safe(section)
