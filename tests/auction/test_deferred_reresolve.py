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


def test_max_history_compression_is_lossless_for_tie_priority():
    """priority_at over the compressed history equals priority_at over the
    full raw history, at every level, including after further raw appends."""
    import random

    rng = random.Random(20260929)
    for _ in range(400):
        raw = [[rng.randint(0, 60), i] for i in range(rng.randint(1, 140))]
        comp = engine._compress_hist(raw)
        extra = [[rng.randint(0, 60), 1000 + i] for i in range(rng.randint(0, 5))]
        for levels in range(0, 62):
            full = engine.priority_at({"max": raw[-1][0], "seq": raw[-1][1], "hist": raw}, levels)
            got = engine.priority_at({"max": raw[-1][0], "seq": raw[-1][1], "hist": comp}, levels)
            assert got == full
            raw2, comp2 = raw + extra, comp + extra
            last = raw2[-1]
            assert engine.priority_at(
                {"max": last[0], "seq": last[1], "hist": comp2}, levels
            ) == engine.priority_at({"max": last[0], "seq": last[1], "hist": raw2}, levels)


def test_command_log_time_never_runs_backwards(tmp_path):
    """A request whose clock was read before it waited for the write lock is
    applied at the moment the room already reached, never earlier."""
    from tests.auction.test_independent_recovery_audit import NOON, M, _mkroom, _new_store

    st, _ = _new_store(tmp_path)
    room = _mkroom(st)
    a = M(st, room, "S1", "nominate", NOON + 100, player="P1")["result"]["auction"]
    M(st, room, "S2", "bid", NOON + 50, auction=a, max=5)  # overtaken request
    with st.read() as conn:
        times = [
            r[0]
            for r in conn.execute(
                "SELECT room_now FROM commands WHERE room_id=? ORDER BY revision", (room,)
            )
        ]
    assert times == sorted(times) and times[-1] == times[-2]
