"""In-room auction-dollar trades (milestone C)."""

from __future__ import annotations

import pytest

from src.auction import engine
from src.auction.engine import AuctionError
from tests.auction.helpers import NOON, et, nominate, started


def _do(s, kind, seat, now=NOON, **kw):
    return engine.apply_command(
        s, {"kind": kind, "actor": {"role": "manager", "seat": seat}, **kw}, now
    )


def _commish(s, kind, now=NOON, **kw):
    return engine.apply_command(s, {"kind": kind, "actor": {"role": "commissioner"}, **kw}, now)


def _offer(s, frm, to, now=NOON, **kw):
    s, r, _ = _do(s, "offer_trade", frm, now=now, to=to, **kw)
    return s, r["trade"]


def test_dollar_transfer_settles_atomically():
    s = started()
    s, t = _offer(s, "S1", "S2", give_dollars=10)
    s, r, ev = _do(s, "respond_trade", "S2", trade=t, version=1, accept=True)
    assert r["status"] == "completed"
    assert engine.balance(s, "S1") == 90 and engine.balance(s, "S2") == 110
    assert engine.total_opening_pool(s) == 1200  # no money created
    assert sum(engine.balance(s, x["id"]) for x in s["seats"]) == 1200
    assert any(e["type"] == "trade_completed" and e["vis"] == "public" for e in ev)


def test_money_reserved_by_a_lead_cannot_be_sent():
    s = started([50] + [100] * 11)
    s, aid = nominate(s, "S3", "P1")
    s, _, _ = _do(s, "bid", "S1", auction=aid, max=50)
    s, _, _ = _do(s, "bid", "S2", auction=aid, max=44)  # S1 leads at $45
    s, t = _offer(s, "S1", "S4", give_dollars=10)  # offers do not reserve money...
    with pytest.raises(AuctionError) as e:
        _do(s, "respond_trade", "S4", trade=t, version=1, accept=True)  # ...settlement re-checks
    assert e.value.code == "trade_unaffordable"
    s, t2 = _offer(s, "S1", "S4", give_dollars=5)
    s, r, _ = _do(s, "respond_trade", "S4", trade=t2, version=1, accept=True)
    assert r["status"] == "completed" and engine.spendable(s, "S1") == 0


def test_terms_version_expiry_and_roles():
    s = started()
    s, t = _offer(s, "S1", "S2", give_dollars=3, expires_hours=1)
    with pytest.raises(AuctionError) as e:
        _do(s, "respond_trade", "S2", trade=t, version=2, accept=True)
    assert e.value.code == "trade_changed"
    with pytest.raises(AuctionError) as e:
        _do(s, "respond_trade", "S3", trade=t, version=1, accept=True)
    assert e.value.status == 403
    with pytest.raises(AuctionError) as e:
        _do(s, "respond_trade", "S2", now=NOON + 3601, trade=t, version=1, accept=True)
    assert e.value.code == "trade_closed"
    s, t2 = _offer(s, "S1", "S2", give_dollars=3)
    s, _, _ = _do(s, "cancel_trade", "S1", trade=t2)
    with pytest.raises(AuctionError):
        _do(s, "respond_trade", "S2", trade=t2, version=1, accept=True)


def test_no_acceptance_during_the_nightly_pause_but_declining_is_fine():
    s = started()
    s, t = _offer(s, "S1", "S2", give_dollars=3)
    night = et(2026, 10, 5, 22)
    with pytest.raises(AuctionError) as e:
        _do(s, "respond_trade", "S2", now=night, trade=t, version=1, accept=True)
    assert e.value.code == "quiet_hours"
    s, r, _ = _do(s, "respond_trade", "S2", now=night, trade=t, version=1, accept=False)
    assert r["status"] == "declined"


def test_external_assets_need_commissioner_verification():
    s = started()
    s, t = _offer(s, "S1", "S2", get_dollars=20, external_note="my 2028 2nd-round pick on Sleeper")
    s, r, _ = _do(s, "respond_trade", "S2", trade=t, version=1, accept=True)
    assert r["status"] == "awaiting_verification"
    assert engine.balance(s, "S1") == 100  # nothing moved yet
    with pytest.raises(AuctionError) as e:
        _commish(s, "verify_trade", trade=t, approve=True, reason="")
    assert e.value.code == "reason_required"
    s, r, _ = _commish(
        s, "verify_trade", trade=t, approve=True, reason="Sleeper trade 123 confirmed"
    )
    assert r["status"] == "completed" and engine.balance(s, "S1") == 120
    with pytest.raises(AuctionError) as e:  # managers cannot verify
        _do(s, "verify_trade", "S1", trade=t, approve=True, reason="x")
    assert e.value.status == 403


def test_won_players_move_with_the_dollars():
    s = started()
    s, aid = nominate(s, "S1", "P1")
    s, _, _ = engine.apply_command(
        s, {"kind": "advance", "actor": {"role": "system"}}, s["auctions"][aid]["deadline"]
    )
    t_now = s["auctions"][aid]["closed_at"]
    s, t = _offer(s, "S1", "S2", now=t_now, give_lots=[aid], get_dollars=7)
    s, r, _ = _do(s, "respond_trade", "S2", now=t_now, trade=t, version=1, accept=True)
    a = s["auctions"][aid]
    assert a["winner"] == "S1" and engine.lot_owner(a) == "S2"  # history kept, ownership moved
    assert engine.balance(s, "S1") == 107
    with pytest.raises(AuctionError):  # S1 no longer owns it
        _offer(s, "S1", "S3", now=t_now, give_lots=[aid])


def test_money_received_reactivates_a_capped_proxy():
    s = started([30] + [100] * 11)
    s, a1 = nominate(s, "S2", "P1")
    s, a2 = nominate(s, "S3", "P2")
    s, _, _ = _do(s, "bid", "S1", auction=a1, max=25)
    s, _, _ = _do(s, "bid", "S4", auction=a1, max=20)  # S1 leads a1 @21 → $9 left
    s, _, _ = _do(s, "bid", "S1", auction=a2, max=30)
    s, _, _ = _do(s, "bid", "S5", auction=a2, max=15)  # S5 leads a2 @10 (S1 capped)
    s, t = _offer(s, "S6", "S1", give_dollars=20)
    s, _, _ = _do(s, "respond_trade", "S1", trade=t, version=1, accept=True)
    assert (s["auctions"][a2]["leader"], s["auctions"][a2]["price"]) == ("S1", 16)
    assert engine.committed(s, "S1") <= engine.balance(s, "S1")


def test_trades_are_private_until_completed():
    s = started()
    s, t = _offer(s, "S1", "S2", give_dollars=4)
    pub = engine.public_view(s, NOON)
    assert pub["completed_trades"] == []
    assert engine.seat_private_view(s, "S3", NOON)["trades"] == []
    assert engine.seat_private_view(s, "S2", NOON)["trades"][0]["id"] == t
