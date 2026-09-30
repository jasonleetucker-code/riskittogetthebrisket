"""Settlement: exact winnings from the full field, honest about ties, tickets and unknowns."""

from __future__ import annotations

from src.dfs.contests import Contest, PayoutBand, contest_from_dict
from src.dfs.settlement import settle


def _contest(tie_rule="split_positions", ladder=None, **kw):
    return Contest(
        name="Test GPP",
        platform="draftkings",
        sport="nfl",
        format="classic",
        entry_fee_cents=500,
        tie_rule=tie_rule,
        ladder=ladder or [PayoutBand(1, 1, 100_000), PayoutBand(2, 2, 10_000)],
        **kw,
    )


def _me(pts, rank=None, eid="E1"):
    return {"entryId": eid, "entryName": "me", "points": pts, "platformRank": rank}


def test_outright_win_is_exact_with_net_and_roi():
    s = settle(_contest(), [(150.0, 1), (120.0, 1), (90.0, 3)], [_me(150.0, 1), _me(90.0, 3, "E2")])
    assert s["state"] == "complete" and s["fieldSize"] == 5
    assert [r["payout"]["eachCents"] for r in s["rows"]] == [100_000, 0]
    assert s["feesCents"] == 1000 and s["netCents"] == 99_000 and s["roi"] == 99.0
    assert [r["rankCheck"] for r in s["rows"]] == ["agrees", "agrees"]


def test_tie_across_paid_places_splits_to_550():
    s = settle(_contest(), [(150.0, 2), (90.0, 3)], [_me(150.0, 1)])
    row = s["rows"][0]
    assert row["rank"] == 1 and row["tiedWith"] == 1
    assert row["payout"]["eachCents"] == 55_000  # ($1,000 + $100) / 2


def test_unknown_tie_rule_in_the_money_blocks_the_net_but_not_an_unpaid_tie():
    s = settle(_contest(tie_rule="unknown"), [(150.0, 2), (90.0, 3)], [_me(150.0)])
    assert s["rows"][0]["payout"]["state"] == "unavailable"
    assert s["state"] == "partial" and s["netCents"] is None and s["roi"] is None
    # Tied entirely outside the paid places: $0 whatever the rule.
    s = settle(_contest(tie_rule="unknown"), [(150.0, 1), (120.0, 1), (90.0, 3)], [_me(90.0)])
    assert s["rows"][0]["payout"] == {"state": "exact", "eachCents": 0, "exact": "0"}
    assert s["state"] == "complete" and s["netCents"] == -500


def test_ticket_prizes_are_not_counted_as_cash():
    c = _contest(
        ladder=[PayoutBand(1, 1, 0, kind="ticket", value_cents=None), PayoutBand(2, 2, 10_000)]
    )
    s = settle(c, [(150.0, 1), (120.0, 1)], [_me(150.0)])
    assert s["rows"][0]["payout"]["state"] == "noncash" and s["netCents"] is None


def test_unreadable_field_scores_make_ranks_unknowable():
    s = settle(_contest(), [(150.0, 1)], [_me(150.0)], unscored_entries=2)
    assert s["state"] == "unavailable"


def test_rank_and_field_size_disagreements_are_reported():
    s = settle(_contest(current_entries=10), [(150.0, 1), (120.0, 1)], [_me(120.0, 5)])
    assert s["rows"][0]["rankCheck"] == "disagrees" and s["rankDisagreements"] == 1
    assert s["fieldSizeCheck"] == "disagrees" and s["declaredFieldSize"] == 10


def test_no_owner_entries_is_its_own_state():
    assert settle(_contest(), [(150.0, 1)], [])["state"] == "no_owner_entries"


def test_contest_round_trips_through_its_stored_form():
    c = _contest(current_entries=10)
    assert contest_from_dict(c.to_dict()) == c
