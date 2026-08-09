from __future__ import annotations

from src.roster_intel.team_strength import TOP_N_LIMITS, build_team_strength, compare_team_strength


def _p(name: str, pos: str, value: int | None, rank: int = 999) -> dict:
    row = {
        "name": name,
        "basePos": pos,
        "pos": pos,
        "rank": rank,
        "assetClass": "player",
    }
    if value is not None:
        row["value"] = value
    return row


def test_exact_product_top_n_limits_are_canonical() -> None:
    assert TOP_N_LIMITS == {
        "QB": 3,
        "RB": 3,
        "WR": 5,
        "TE": 3,
        "DL": 5,
        "LB": 5,
        "DB": 5,
    }


def test_wr_six_does_not_add_immediate_top_five_strength() -> None:
    assets = [_p(f"WR{i}", "WR", 7000 - i * 500, i) for i in range(1, 7)]
    snap = build_team_strength(assets)

    assert [m["name"] for m in snap["positions"]["WR"]["core"]] == [
        "WR1",
        "WR2",
        "WR3",
        "WR4",
        "WR5",
    ]
    assert [m["name"] for m in snap["positions"]["WR"]["depth"]] == ["WR6"]


def test_trading_wr3_promotes_former_wr6_and_charges_only_real_top_five_delta() -> None:
    before = [_p(f"WR{i}", "WR", 7000 - i * 500, i) for i in range(1, 7)]
    after = [p for p in before if p["name"] != "WR3"]

    impact = compare_team_strength(before, after)
    wr = impact["delta"]["byPosition"]["WR"]

    # WR3 = 5500 leaves; WR6 = 4000 replaces him, so the real loss is 1500,
    # not the outgoing player's full 5500 dynasty value.
    assert wr["delta"] == -1500
    assert [p["name"] for p in wr["enteredCore"]] == ["WR6"]
    assert wr["enteredCore"][0]["movement"] == "promoted_from_depth"
    assert [p["name"] for p in wr["exitedCore"]] == ["WR3"]
    assert wr["exitedCore"][0]["movement"] == "sent_from_core"


def test_trading_wr6_changes_asset_portfolio_but_not_current_team_strength() -> None:
    before = [_p(f"WR{i}", "WR", 7000 - i * 500, i) for i in range(1, 7)]
    after = [p for p in before if p["name"] != "WR6"]

    impact = compare_team_strength(before, after)

    assert impact["delta"]["byPosition"]["WR"]["delta"] == 0
    assert impact["delta"]["totalValue"] == 0


def test_incoming_qb4_has_asset_value_but_zero_immediate_top_three_strength() -> None:
    before = [
        _p("QB1", "QB", 9000, 1),
        _p("QB2", "QB", 8000, 2),
        _p("QB3", "QB", 7000, 3),
    ]
    after = [*before, _p("QB4", "QB", 6000, 4)]

    impact = compare_team_strength(before, after)

    assert impact["delta"]["byPosition"]["QB"]["delta"] == 0
    assert impact["after"]["positions"]["QB"]["depth"][0]["name"] == "QB4"


def test_incoming_qb_enters_top_three_and_bumps_previous_qb3_to_depth() -> None:
    before = [
        _p("QB1", "QB", 9000, 1),
        _p("QB2", "QB", 8000, 2),
        _p("QB3", "QB", 7000, 3),
    ]
    after = [*before, _p("New QB", "QB", 8500, 2)]

    impact = compare_team_strength(before, after)
    qb = impact["delta"]["byPosition"]["QB"]

    assert qb["delta"] == 1500
    assert qb["enteredCore"][0]["name"] == "New QB"
    assert qb["enteredCore"][0]["movement"] == "received_into_core"
    assert qb["exitedCore"][0]["name"] == "QB3"
    assert qb["exitedCore"][0]["movement"] == "bumped_to_depth"


def test_picks_never_contribute_current_team_strength() -> None:
    assets = [
        _p("QB1", "QB", 9000, 1),
        {
            "name": "2029 1st",
            "basePos": "PICK",
            "pos": "PICK",
            "value": 6000,
            "assetClass": "pick",
        },
    ]

    snap = build_team_strength(assets)

    assert snap["totalValue"] == 9000


def test_idp_rooms_use_top_five_per_dl_lb_db() -> None:
    assets = []
    for pos in ("DL", "LB", "DB"):
        assets.extend(_p(f"{pos}{i}", pos, 6000 - i * 100, i) for i in range(1, 8))

    snap = build_team_strength(assets)

    for pos in ("DL", "LB", "DB"):
        assert snap["positions"][pos]["coreCount"] == 5
        assert snap["positions"][pos]["eligibleCount"] == 7
        assert len(snap["positions"][pos]["depth"]) == 2


def test_missing_value_is_reported_not_silently_zeroed() -> None:
    assets = [_p("Priced", "RB", 5000, 1), _p("Missing", "RB", None, 2)]

    snap = build_team_strength(assets)

    assert snap["totalValue"] == 5000
    assert snap["missingValueCount"] == 1
    assert snap["positions"]["RB"]["missingValueAssets"][0]["name"] == "Missing"
