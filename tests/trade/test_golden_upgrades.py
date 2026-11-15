"""C7-GOLD-01 — Golden Upgrades (owner inventory row 2.5).

Adversarial: each of the six criteria has a case a convenient shortcut would
pass and the owner rule forbids — a cross-position "upgrade", a legacy KTC key
answering for KTC Market, a withheld provider, a sub-threshold inversion, a
protected player offered away.
"""

from __future__ import annotations

from pathlib import Path

from src.league_intel.cross_market import MARKET_IDPTC, MARKET_KTC
from src.trade import golden_upgrades as gu
from src.trade.constraints import resolve_constraints


def _league(mine, theirs, *, withheld=()):
    """rows: ``(name, pos, board, sites: dict, nfl_team)``."""
    players, rows = {}, []
    for name, pos, board, sites, team in (*mine, *theirs):
        players[name] = {
            "_canonicalSiteValues": dict(sites),
            "position": pos,
            "team": team,
            "_sites": 8,
        }
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "position": pos,
                "team": team,
                "rankDerivedValue": board,
                "canonicalSiteValues": dict(sites),
                "freshnessExcludedSources": [MARKET_IDPTC] if name in withheld else [],
                "assetClass": "player",
            }
        )
    teams = [
        {"name": "Us", "ownerId": "1", "players": [m[0] for m in mine]},
        {"name": "Them", "ownerId": "2", "players": [t[0] for t in theirs]},
    ]
    return players, teams, {"playersArray": rows}


def _run(mine, theirs, *, constraints=None, withheld=(), **kw):
    players, teams, contract = _league(mine, theirs, withheld=withheld)
    return gu.find_golden_upgrades(
        players, "Us", teams, contract=contract, constraints=constraints, **kw
    )


OWNED_LB = ("Our LB", "LB", 3000, {MARKET_IDPTC: 4000}, "CIN")
TARGET_LB = ("Their LB", "LB", 3600, {MARKET_IDPTC: 3500}, "BUF")


def test_a_same_position_inversion_is_a_golden_upgrade():
    out = _run([OWNED_LB], [TARGET_LB])
    assert out["action"] == "recommend_only"
    [u] = out["upgrades"]
    assert (u["owned"]["name"], u["target"]["name"], u["opponent"]) == (
        "Our LB",
        "Their LB",
        "Them",
    )
    assert u["market"] == "IDP Trade Calculator"
    assert u["boardGainPct"] == 20.0
    assert u["marketInversionPct"] == round(100 * 500 / 3500, 2)
    assert u["owned"]["marketValue"] == 4000 and u["target"]["marketValue"] == 3500


def test_a_different_position_is_never_an_upgrade():
    target = ("Their S", "DB", 3600, {MARKET_IDPTC: 3500}, "BUF")
    out = _run([OWNED_LB], [target])
    assert out["upgrades"] == []
    assert out["diagnostics"]["notSubstitutable"] == 1
    assert out["noResultReason"] == "no_same_position_target_board_prefers"


def test_the_board_must_prefer_the_target():
    target = ("Their LB", "LB", 2900, {MARKET_IDPTC: 3500}, "BUF")
    out = _run([OWNED_LB], [target])
    assert out["upgrades"] == [] and out["diagnostics"]["boardDoesNotPreferTarget"] == 1


def test_the_market_must_prefer_what_you_own():
    target = ("Their LB", "LB", 3600, {MARKET_IDPTC: 4200}, "BUF")
    out = _run([OWNED_LB], [target])
    assert out["upgrades"] == [] and out["diagnostics"]["marketDoesNotPreferOwned"] == 1


def test_a_legacy_ktc_key_never_answers_for_ktc_market():
    """The finder's pool falls back to historical KTC keys for offense; a
    Golden Upgrade's market criterion is native KTC Market only."""
    owned = ("Our WR", "WR", 3000, {"ktcSfTep": 4000}, "CIN")
    target = ("Their WR", "WR", 3600, {"ktcSfTep": 3500}, "BUF")
    out = _run([owned], [target])
    assert out["upgrades"] == []
    assert out["diagnostics"]["marketUnpriced"] == 1
    # "No price to judge" is not "no swap exists".
    assert out["noResultReason"] == "market_prices_unavailable"


def test_native_ktc_market_offense_upgrade_qualifies():
    owned = ("Our WR", "WR", 3000, {MARKET_KTC: 4000}, "CIN")
    target = ("Their WR", "WR", 3600, {MARKET_KTC: 3500}, "BUF")
    [u] = _run([owned], [target])["upgrades"]
    assert u["market"] == "KTC Market"


def test_a_withheld_provider_is_not_a_market_preference():
    out = _run([OWNED_LB], [TARGET_LB], withheld=("Their LB",))
    assert out["upgrades"] == [] and out["diagnostics"]["marketWithheld"] == 1
    assert out["noResultReason"] == "market_withheld"


def test_an_inversion_below_the_declared_minimums_is_not_golden():
    target = ("Their LB", "LB", 3100, {MARKET_IDPTC: 3950}, "BUF")  # +3.3% board
    out = _run([OWNED_LB], [target])
    assert out["upgrades"] == [] and out["diagnostics"]["inversionTooSmall"] == 1
    assert out["noResultReason"] == "no_inversion_meets_the_thresholds"


def test_a_protected_owned_player_is_never_offered_but_a_protected_target_is_obtainable():
    c = resolve_constraints(persistent={"untouchables": ["Our LB"]})
    second = ("Our LB2", "LB", 3000, {MARKET_IDPTC: 4000}, "CIN")
    out = _run([OWNED_LB, second], [TARGET_LB], constraints=c)
    assert {u["owned"]["name"] for u in out["upgrades"]} == {"Our LB2"}
    # Protection is an outgoing rule: the same name as a TARGET is allowed.
    c2 = resolve_constraints(persistent={"untouchables": ["Their LB"]})
    assert _run([OWNED_LB], [TARGET_LB], constraints=c2)["upgrades"]


def test_everything_protected_is_an_explained_no_result():
    c = resolve_constraints(persistent={"nflTeams": ["CIN"]})
    # A non-CIN player proves the team rule reads the real team (not a
    # fail-closed unknown that would block everything for the wrong reason).
    other = ("Our DAL LB", "LB", 3000, {MARKET_IDPTC: 4000}, "DAL")
    assert _run([OWNED_LB, other], [TARGET_LB], constraints=c)["upgrades"]
    out = _run([OWNED_LB], [TARGET_LB], constraints=c)
    assert out["noResultReason"] == "all_outgoing_assets_constrained"
    assert out["noResultLabel"] == "No Golden Upgrade found under current constraints"


def test_lock_narrows_to_the_locked_player_and_bad_locks_are_explained():
    second = ("Our LB2", "LB", 3000, {MARKET_IDPTC: 4000}, "CIN")
    locked = _run(
        [OWNED_LB, second],
        [TARGET_LB],
        constraints=resolve_constraints(refinement={"lock": ["Our LB2"]}),
    )
    assert {u["owned"]["name"] for u in locked["upgrades"]} == {"Our LB2"}
    two = _run(
        [OWNED_LB, second],
        [TARGET_LB],
        constraints=resolve_constraints(refinement={"lock": ["Our LB", "Our LB2"]}),
    )
    assert two["noResultReason"] == "locked_players_exceed_package_size"
    # (With a second sendable player, so the roster is not fully blocked —
    # that more fundamental reason would be reported first, as Best Offers does.)
    conflict = _run(
        [OWNED_LB, second],
        [TARGET_LB],
        constraints=resolve_constraints(
            persistent={"untouchables": ["Our LB"]}, refinement={"lock": ["Our LB"]}
        ),
    )
    assert conflict["noResultReason"] == "lock_conflicts_with_protection"


def test_lineup_impact_is_reported_from_the_solver_seam():
    calls = []

    def lineup(us, them, give, recv):
        calls.append((us, them, tuple(give), tuple(recv)))
        return {"available": True, "ourDelta": 1.5, "theirDelta": -0.5}

    [u] = _run([OWNED_LB], [TARGET_LB], lineup_delta=lineup)["upgrades"]
    assert calls == [("1", "2", ("Our LB",), ("Their LB",))]
    assert u["lineupImpact"]["ourDelta"] == 1.5


def test_the_consumer_never_enumerates_packages_itself():
    src = Path(gu.__file__).read_text(encoding="utf-8")
    assert "combinations(" not in src and "itertools" not in src


def test_a_huge_inversion_is_flagged_and_ranked_below_a_clean_one():
    """Review S2: the live #1 was a 23% board gain against a 61% market
    inversion — two boards disagreeing about the players, not an upgrade."""
    huge = ("Huge LB", "LB", 3000, {MARKET_IDPTC: 5600}, "CIN")  # +61% market
    clean = ("Clean LB", "LB", 3000, {MARKET_IDPTC: 3900}, "CIN")
    targets = [
        ("Target A", "LB", 3700, {MARKET_IDPTC: 3450}, "BUF"),
    ]
    out = _run([huge, clean], targets)
    by_owned = {u["owned"]["name"]: u for u in out["upgrades"]}
    assert by_owned["Huge LB"]["exploitRisk"] is True
    assert by_owned["Clean LB"]["exploitRisk"] is False
    assert out["upgrades"][0]["owned"]["name"] == "Clean LB"


def test_golden_enumerates_single_swaps_only():
    out = _run([OWNED_LB, ("Our LB2", "LB", 2900, {MARKET_IDPTC: 3900}, "CIN")], [TARGET_LB])
    assert all(isinstance(u["owned"], dict) for u in out["upgrades"])
    assert out["diagnostics"]["pairs"] == 2  # two 1-for-1s; no 2-for-2 was built
