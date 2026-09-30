"""A budget correction credited while nothing binding may happen (paused, or
9 PM-8 AM ET) takes effect at the next active moment — ahead of any close due
at that same instant — and replays identically."""

from __future__ import annotations

from src.auction import engine
from tests.auction.helpers import et
from tests.auction.test_independent_recovery_audit import _capped_state, _comm


def test_quiet_hours_credit_reresolves_at_8am_not_overnight():
    s, a1 = _capped_state()
    night = et(2026, 10, 5, 22, 0)
    s, _, _ = _comm(s, "adjust_budget", night, seat="S2", amount=100, reason="fix")
    assert s["auctions"][a1]["leader"] == "S1"
    assert engine.next_due_time(s) == et(2026, 10, 6, 8, 0)
    # The first thing that happens next morning (here: an unrelated no-op
    # advance at 08:05) settles the deferred re-resolution AT 08:00.
    s, _, events = engine.apply_command(
        s, {"kind": "advance", "actor": {"role": "system"}}, et(2026, 10, 6, 8, 5)
    )
    assert (s["auctions"][a1]["leader"], s["auctions"][a1]["price"]) == ("S2", 21)
    assert not s.get("deferred_reresolve")
    assert [e for e in events if e["type"] == "price"]


def test_resume_inside_quiet_hours_waits_for_8am():
    s, a1 = _capped_state()
    s, _, _ = _comm(s, "pause", et(2026, 10, 5, 12, 30), reason="hold")
    s, _, _ = _comm(s, "adjust_budget", et(2026, 10, 5, 12, 31), seat="S2", amount=100, reason="x")
    s, _, _ = _comm(s, "resume", et(2026, 10, 5, 22, 0))
    assert s["auctions"][a1]["leader"] == "S1"
    assert engine.next_due_time(s) == et(2026, 10, 6, 8, 0)
