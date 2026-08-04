from src.sharp.consensus import aggregate_person_consensus


def movement(asset, manager, person, action, league):
    return {
        "canonicalAssetId": asset,
        "managerKey": manager,
        "canonicalManagerKey": person,
        "action": action,
        "leagueKey": league,
    }


def test_one_person_with_many_leagues_casts_one_vote():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "add", "l2"),
        movement("p1", "sleeper:1", "person:a", "add", "l3"),
        movement("p1", "sleeper:2", "person:b", "drop", "l4"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 1.0})["p1"]
    assert result["personBuys"] == 1
    assert result["personSells"] == 1
    assert result["personVotes"] == 2
    assert result["personNet"] == 0


def test_multiple_accounts_for_one_person_do_not_multiply_consensus():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "ffpc:1", "person:a", "add", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 0.9, "ffpc:1": 0.8})["p1"]
    assert result["personVotes"] == 1
    assert result["personBuys"] == 1


def test_opposite_portfolio_moves_are_mixed_not_two_votes():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:1", "person:a", "drop", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0})["p1"]
    assert result["personVotes"] == 0
    assert result["mixedPersonSignals"] == 1


def test_shared_network_receives_diminishing_independence_weight():
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:2", "person:b", "add", "l2"),
        movement("p1", "sleeper:3", "person:c", "add", "l3"),
    ]
    result = aggregate_person_consensus(
        rows,
        {"sleeper:1": 1.0, "sleeper:2": 1.0, "sleeper:3": 1.0},
        {"sleeper:1": "Network A", "sleeper:2": "Network A", "sleeper:3": "Independent"},
    )["p1"]
    assert result["personVotes"] == 3
    assert result["weightedPersonVolume"] < 3.0
    assert result["networkCount"] == 2
