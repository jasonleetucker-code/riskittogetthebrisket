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


def test_concentration_is_undefined_not_diversified_when_nothing_is_weighted():
    """``networkConcentration`` is a SHARE of weighted volume.

    With no weighted volume there is no share for any network to hold, so
    the ratio does not exist — and ``0.0`` is the one value that reads as
    its exact opposite, "no single network dominates". ``None`` is what
    ``roster_percentage`` publishes for ``cohortCoveragePct`` in the same
    situation, and this keeps the two consistent.
    """
    rows = [movement("p1", "sleeper:1", "person:a", "add", "l1")]
    # Quality 0 means the vote carries no weight, so the denominator is 0
    # while the movement itself is still a real, counted observation.
    result = aggregate_person_consensus(rows, {"sleeper:1": 0.0})["p1"]
    assert result["weightedPersonVolume"] == 0
    assert result["networkConcentration"] is None
    # The raw evidence is untouched — only the ratio is withheld.
    assert result["personBuys"] == 1


def test_concentration_is_reported_when_it_is_defined():
    """The withholding must be specific to the undefined case, or it would
    hide a real concentration finding."""
    rows = [
        movement("p1", "sleeper:1", "person:a", "add", "l1"),
        movement("p1", "sleeper:2", "person:b", "add", "l2"),
    ]
    result = aggregate_person_consensus(rows, {"sleeper:1": 1.0, "sleeper:2": 1.0})["p1"]
    assert result["weightedPersonVolume"] > 0
    assert isinstance(result["networkConcentration"], float)


def test_an_explicitly_zero_quality_manager_does_not_vote_at_full_weight():
    """A manager scored 0.0 is the LOWEST possible quality.

    ``float(person["quality"] or 1.0)`` promoted that to 1.0 — the highest —
    so a worthless vote carried full weight into both the consensus and the
    concentration cap. The default already happens upstream when a manager
    is absent from the quality map, so the second one could only ever
    overwrite a real measurement.
    """
    rows = [movement("p1", "sleeper:1", "person:a", "add", "l1")]
    zero = aggregate_person_consensus(rows, {"sleeper:1": 0.0})["p1"]
    full = aggregate_person_consensus(rows, {"sleeper:1": 1.0})["p1"]
    assert zero["weightedPersonVolume"] == 0
    assert full["weightedPersonVolume"] == 1.0
    # The vote is still COUNTED as evidence — only its weight is zero.
    assert zero["personBuys"] == full["personBuys"] == 1


def test_a_manager_absent_from_the_quality_map_still_defaults_to_full():
    """The upstream default is the intended one and must survive the fix."""
    rows = [movement("p1", "sleeper:9", "person:a", "add", "l1")]
    result = aggregate_person_consensus(rows, {})["p1"]
    assert result["weightedPersonVolume"] == 1.0
