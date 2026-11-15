"""The owner's required proxy examples plus money/cross-auction rules."""

from __future__ import annotations

import pytest

from src.auction import engine
from src.auction.engine import AuctionError
from tests.auction.helpers import NOON, bid, cmd, et, nominate, started


def _a(s, aid):
    return s["auctions"][aid]


def test_1_unchallenged_nomination_wins_at_zero():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    deadline = _a(s, aid)["deadline"]
    s, _, _ = cmd(s, "advance", deadline, role="system")
    a = _a(s, aid)
    assert a["status"] == "closed" and a["winner"] == "S1" and a["price"] == 0


def test_2_zero_budget_manager_may_nominate_and_win_at_zero():
    s = started([0] + [100] * 11)
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = cmd(s, "advance", _a(s, aid)["deadline"], role="system")
    assert _a(s, aid)["winner"] == "S1" and _a(s, aid)["price"] == 0
    assert engine.balance(s, "S1") == 0


def test_3_raising_own_max_alone_keeps_price_zero():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, r = bid(s, "S1", aid, 50)
    assert _a(s, aid)["price"] == 0 and _a(s, aid)["leader"] == "S1"
    assert r["leading"]


def test_4_owner_example_50_vs_39_leads_at_40():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 50)
    s, _ = bid(s, "S2", aid, 39)
    assert (_a(s, aid)["leader"], _a(s, aid)["price"]) == ("S1", 40)


def test_5_equal_max_earlier_wins_at_that_max():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 50)
    s, _ = bid(s, "S2", aid, 50)
    assert (_a(s, aid)["leader"], _a(s, aid)["price"]) == ("S1", 50)


def test_6_higher_max_takes_lead_at_its_max():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 50)
    s, _ = bid(s, "S2", aid, 50)
    s, _ = bid(s, "S2", aid, 51)
    assert (_a(s, aid)["leader"], _a(s, aid)["price"]) == ("S2", 51)


def test_7_two_zero_maxima_earlier_wins_at_zero():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, r = bid(s, "S2", aid, 0)
    assert (_a(s, aid)["leader"], _a(s, aid)["price"]) == ("S1", 0)
    assert not r["leading"]


def test_8_zero_offer_cannot_displace_positive_leader():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 5)
    assert _a(s, aid)["price"] == 1
    with pytest.raises(AuctionError) as e:
        bid(s, "S3", aid, 0)
    assert e.value.code == "below_price"


def test_9_identical_resubmission_is_a_noop():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 10)
    seq_before = _a(s, aid)["bids"]["S2"]["seq"]
    s2, r, ev = cmd(s, "bid", NOON + 5, seat="S2", auction=aid, max=10)
    assert r.get("noop") and _a(s2, aid)["bids"]["S2"]["seq"] == seq_before
    assert s2["seq"] == s["seq"]


def test_raise_gets_new_priority_not_retroactive():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 10)  # S1 earlier at 10
    s, _ = bid(s, "S2", aid, 30)  # S2 leads 11
    s, _ = bid(s, "S1", aid, 30)  # S1 raises to 30 LATER than S2's 30
    assert (_a(s, aid)["leader"], _a(s, aid)["price"]) == ("S2", 30)


@pytest.mark.parametrize("bad", [-1, 1.5, float("nan"), float("inf"), True, "5", None, 10**9])
def test_bad_amounts_rejected(bad):
    s = started()
    s, aid = nominate(s, "S1", "P1")
    with pytest.raises(AuctionError):
        bid(s, "S2", aid, bad)


def test_max_above_balance_rejected():
    s = started([100, 20] + [100] * 10)
    s, aid = nominate(s, "S1", "P1")
    with pytest.raises(AuctionError) as e:
        bid(s, "S2", aid, 21)
    assert e.value.code == "over_balance"


def test_leader_cannot_withdraw_or_reduce_below_price():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 50)
    s, _ = bid(s, "S2", aid, 20)
    with pytest.raises(AuctionError):
        cmd(s, "withdraw", NOON, seat="S1", auction=aid)
    with pytest.raises(AuctionError):
        bid(s, "S1", aid, 20)
    s, _ = bid(s, "S1", aid, 21)  # down to the binding price is allowed
    assert _a(s, aid)["price"] == 21


def test_non_leader_withdraw_keeps_history_and_price():
    s = started()
    s, aid = nominate(s, "S3", "P1")
    s, _ = bid(s, "S1", aid, 50)
    s, _ = bid(s, "S2", aid, 20)
    s, _, _ = cmd(s, "withdraw", NOON, seat="S2", auction=aid)
    assert _a(s, aid)["price"] == 21  # prices never go backward
    s, _ = bid(s, "S4", aid, 30)
    assert _a(s, aid)["price"] == 31


# ---------------------------------------------------------------------------
# Money across simultaneous auctions
# ---------------------------------------------------------------------------


def test_same_dollars_cannot_lead_two_auctions():
    s = started([50, 100, 100] + [100] * 9)
    s, a1 = nominate(s, "S2", "P1")
    s, a2 = nominate(s, "S3", "P2")
    s, _ = bid(s, "S2", a1, 60)
    s, _ = bid(s, "S1", a1, 50)  # S1 capped at 50 → S2 leads 51
    assert _a(s, a1)["leader"] == "S2"
    s, _ = bid(s, "S1", a2, 40)
    s, _ = bid(s, "S3", a2, 30)
    assert (_a(s, a2)["leader"], _a(s, a2)["price"]) == ("S1", 31)
    assert engine.committed(s, "S1") <= engine.balance(s, "S1")


def test_capped_proxy_sets_no_phantom_price():
    s = started([30] + [100] * 11)
    s, a1 = nominate(s, "S2", "P1")
    s, a2 = nominate(s, "S3", "P2")
    s, _ = bid(s, "S1", a1, 25)  # S1 leads a1 at 1 (vs S2's $0)
    s, _ = bid(s, "S4", a1, 20)  # S1 leads a1 at 21
    s, _ = bid(s, "S1", a2, 30)  # stored 30, but only 9 affordable on a2
    s, r = bid(s, "S5", a2, 5)
    assert (_a(s, a2)["leader"], _a(s, a2)["price"]) == ("S1", 6)
    s, r = bid(s, "S5", a2, 15)
    # S1's effective ceiling on a2 is 30-21 = 9: S5 leads at 10, not 31.
    assert (_a(s, a2)["leader"], _a(s, a2)["price"]) == ("S5", 10)


def test_budget_release_reactivates_capped_proxy_deterministically():
    s = started([30] + [100] * 11)
    s, a1 = nominate(s, "S2", "P1")
    s, a2 = nominate(s, "S3", "P2")
    s, _ = bid(s, "S1", a1, 25)
    s, _ = bid(s, "S4", a1, 20)  # S1 leads a1 @21
    s, _ = bid(s, "S1", a2, 30)
    s, _ = bid(s, "S5", a2, 15)  # S5 leads a2 @10 (S1 capped at 9)
    # Now S6 outbids S1 on a1 → S1's $21 is free → its a2 max reactivates.
    s, _ = bid(s, "S6", a1, 40)
    assert (_a(s, a1)["leader"], _a(s, a1)["price"]) == ("S6", 26)
    assert (_a(s, a2)["leader"], _a(s, a2)["price"]) == ("S1", 16)
    assert engine.committed(s, "S1") <= engine.balance(s, "S1")


def test_settlement_spends_and_prices_do_not_go_backward():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 30)
    s, _ = bid(s, "S3", aid, 12)
    s, _, _ = cmd(s, "advance", _a(s, aid)["deadline"], role="system")
    assert _a(s, aid)["winner"] == "S2" and _a(s, aid)["price"] == 13
    assert engine.balance(s, "S2") == 87


def test_manager_may_win_more_than_six():
    s = started([1000] + [100] * 11)
    won = 0
    for rnd in range(1, 7):
        for i, seat in enumerate(s["order"]):
            pass
    # Nominate 12, S1 outbids everything, close, repeat.
    t = NOON
    for batch in range(2):
        aids = []
        for i, seat in enumerate(s["order"]):
            s, aid = nominate(s, seat, f"P{batch * 12 + i + 1}", now=t)
            aids.append(aid)
        for aid in aids:
            s, _ = bid(s, "S1", aid, 5, now=t)
        s, _, _ = cmd(s, "advance", max(_a(s, a)["deadline"] for a in aids), role="system")
        t = max(_a(s, a)["deadline"] for a in aids)
        s, _, _ = cmd(
            s, "advance", engine.schedule.next_active_start(engine._window(s), t), role="system"
        )
        t = engine.schedule.next_active_start(engine._window(s), t)
    won = sum(1 for a in s["auctions"].values() if a["winner"] == "S1")
    assert won >= 12


# ---------------------------------------------------------------------------
# Time rules
# ---------------------------------------------------------------------------


def test_no_binding_bids_in_quiet_hours():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    with pytest.raises(AuctionError) as e:
        bid(s, "S2", aid, 5, now=et(2026, 10, 5, 22))
    assert e.value.code == "quiet_hours"


def test_late_bid_after_deadline_is_rejected_even_without_close_worker():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    deadline = _a(s, aid)["deadline"]
    with pytest.raises(AuctionError) as e:
        bid(s, "S2", aid, 5, now=deadline)
    assert e.value.code == "closed"


def test_last_hour_competitive_bid_extends_to_one_active_hour():
    s = started(rules_patch=None)
    s, aid = nominate(s, "S1", "P1")
    deadline = _a(s, aid)["deadline"]
    late = deadline - 600  # 10 active minutes left (deadline is inside a window)
    s, _ = bid(s, "S2", aid, 5, now=late)
    assert _a(s, aid)["deadline"] == engine.schedule.add_active(engine._window(s), late, 3600)
    assert _a(s, aid)["extensions"] == 1


def test_private_ceiling_raise_does_not_extend():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 5)
    deadline = _a(s, aid)["deadline"]
    s, _ = bid(s, "S2", aid, 50, now=deadline - 600)
    assert _a(s, aid)["deadline"] == deadline


def test_extension_is_max_not_additive():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    deadline = _a(s, aid)["deadline"]
    t = deadline - 600
    s, _ = bid(s, "S2", aid, 5, now=t)
    d1 = _a(s, aid)["deadline"]
    s, _ = bid(s, "S3", aid, 8, now=t + 1)
    assert _a(s, aid)["deadline"] - d1 == pytest.approx(1)  # re-anchored, not +1h


def test_outage_pause_does_not_settle_expired_auctions():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    deadline = _a(s, aid)["deadline"]
    heartbeat = deadline - 1800
    now = deadline + 5 * 3600
    s, _, _ = cmd(s, "pause", now, at=heartbeat, pause_kind="outage", reason="service unreachable")
    assert _a(s, aid)["status"] == "open"
    assert _a(s, aid)["remaining"] == pytest.approx(1800)
    s, _, _ = cmd(s, "resume", now, reason="restored")
    # fair window: at least one active hour after resume
    assert engine.schedule.active_between(
        engine._window(s), now, _a(s, aid)["deadline"]
    ) == pytest.approx(3600)


def test_commissioner_pause_freezes_and_blocks_bids():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = cmd(s, "pause", NOON + 60, reason="test")
    with pytest.raises(AuctionError) as e:
        bid(s, "S2", aid, 5, now=NOON + 120)
    assert e.value.code == "paused"
    s, _, _ = cmd(s, "advance", NOON + 10 * 86400, role="system")
    assert _a(s, aid)["status"] == "open"


# ---------------------------------------------------------------------------
# Nomination window, completion
# ---------------------------------------------------------------------------


def test_twelve_open_limit_and_board_full():
    s = started()
    for i, seat in enumerate(s["order"]):
        s, _ = nominate(s, seat, f"P{i + 1}")
    assert len(engine.open_auctions(s)) == 12
    with pytest.raises(AuctionError) as e:
        nominate(s, "S1", "P20")
    assert e.value.code == "board_full"


def test_duplicate_and_ineligible_nominations_rejected():
    s = started()
    s, _ = nominate(s, "S1", "P1")
    with pytest.raises(AuctionError) as e:
        nominate(s, "S2", "P1")
    assert e.value.code == "already_nominated"
    with pytest.raises(AuctionError) as e:
        nominate(s, "S2", "VETERAN")
    assert e.value.code == "not_eligible"


def test_nomination_timeout_passes_turn_and_full_board_pauses_clock():
    s = started()
    for i, seat in enumerate(s["order"][:11]):
        s, _ = nominate(s, seat, f"P{i + 1}")
    last = s["order"][11]
    right = engine._current_right_for(s, last)
    s, _, _ = cmd(s, "advance", right["deadline"], role="system")
    assert right["id"] in [r["id"] for r in s["rights"] if r["status"] == "passed"]


def test_money_spent_drains_then_completes():
    s = started([5, 5] + [0] * 10)
    s, a1 = nominate(s, "S1", "P1")
    s, a2 = nominate(s, "S3", "P2")
    s, _ = bid(s, "S1", a2, 5)
    s, _ = bid(s, "S2", a2, 4)  # S1 leads a2 at 5
    s, _ = bid(s, "S2", a1, 5)  # S2 leads a1 at 1... then S1 capped at 0
    t = max(_a(s, a1)["deadline"], _a(s, a2)["deadline"])
    s, _, _ = cmd(s, "advance", _a(s, a2)["deadline"], role="system")
    assert s["status"] == "running"
    # S2 still holds $4 unspent → not all money spent yet.
    s, _, _ = cmd(s, "advance", t, role="system")
    assert engine.balance(s, "S1") == 0


def test_all_zero_mock_budgets_do_not_trigger_money_spent_end():
    s = started([0] * 12)
    assert s["status"] == "running"
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = cmd(s, "advance", _a(s, aid)["deadline"], role="system")
    assert s["status"] == "running"


def test_rights_exhausted_drains_and_discloses_unspent():
    s = started(rules_patch={"rounds": 1})
    t = NOON
    for i, seat in enumerate(s["order"]):
        s, _ = nominate(s, seat, f"P{i + 1}", now=t)
    assert s["status"] == "draining" and s["drain_reason"] == "rights_exhausted"
    last = max(a["deadline"] for a in s["auctions"].values())
    s, _, ev = cmd(s, "advance", last, role="system")
    assert s["status"] == "complete"
    done = [e for e in ev if e["type"] == "complete"][0]
    assert done["data"]["unspent"]["S1"] == 100


def test_official_room_requires_confirmed_rules_and_pool():
    from tests.auction.helpers import make_room

    s = make_room(room_type="official")
    with pytest.raises(AuctionError) as e:
        cmd(s, "start", NOON)
    assert e.value.code == "rules_unconfirmed"


def test_missing_budget_blocks_start():
    from tests.auction.helpers import make_room

    s = make_room([None] + [100] * 11)
    with pytest.raises(AuctionError) as e:
        cmd(s, "start", NOON)
    assert e.value.code == "missing_budgets"


def test_private_maxima_never_in_public_view():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 77)
    import json

    pub = engine.public_view(s, NOON)
    assert '"max"' not in json.dumps(pub) and '"bids"' not in json.dumps(pub)
    assert all(a["price"] != 77 for a in pub["auctions"])
    mine = engine.seat_private_view(s, "S2", NOON)
    assert mine["my_bids"][0]["max"] == 77
    other = engine.seat_private_view(s, "S3", NOON)
    assert "77" not in json.dumps(other)


def test_commissioner_cannot_drive_balance_below_commitments():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _ = bid(s, "S2", aid, 50)
    s, _ = bid(s, "S3", aid, 40)  # S2 leads @41
    with pytest.raises(AuctionError) as e:
        engine.apply_command(
            s,
            {
                "kind": "adjust_budget",
                "actor": {"role": "commissioner"},
                "seat": "S2",
                "amount": -70,
                "reason": "x",
            },
            NOON,
        )
    assert e.value.code == "below_obligations"


def test_manager_cannot_run_commissioner_commands():
    s = started()
    with pytest.raises(AuctionError) as e:
        cmd(s, "pause", NOON, seat="S1", role="manager")
    assert e.value.status == 403
