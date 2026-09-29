"""scripts/auction_backup_verify.py — back up, restore, verify."""

from __future__ import annotations

import json

from scripts import auction_backup_verify as abv
from src.auction.store import open_store
from tests.auction.helpers import NOON, make_room


def _store_with_room(tmp_path):
    st = open_store(tmp_path / "live" / "auction" / "auction.sqlite")
    with st.write() as conn:
        conn.execute(
            "INSERT INTO users (id, handle, display_name, created_at) VALUES (1,'o','O',0)"
        )
    s = make_room(preset="fast")
    st.create_room(s, created_by=1, now_real=NOON)
    st.execute(
        s["room_id"],
        {"kind": "start", "actor": {"role": "commissioner"}},
        user_id=None,
        now_real=NOON,
    )
    st.execute(
        s["room_id"],
        {"kind": "nominate", "actor": {"role": "manager", "seat": "S1"}, "player": "P1"},
        user_id=None,
        now_real=NOON,
    )
    return st, s["room_id"]


def test_verified_backup_is_kept_and_recorded(tmp_path):
    st, room = _store_with_room(tmp_path)
    dest = tmp_path / "copies"
    assert abv.run(st.path, dest, keep=3) == 0
    assert len(list(dest.glob("auction-*.sqlite.gz"))) == 1
    with st.read() as conn:
        rec = conn.execute("SELECT value FROM meta WHERE key='last_verified_backup'").fetchone()
    assert rec and "1 room(s) restored and verified" in rec["value"]


def test_tampered_state_fails_verification(tmp_path):
    st, room = _store_with_room(tmp_path)
    with st.write() as conn:
        state = json.loads(
            conn.execute("SELECT state_json FROM rooms WHERE id=?", (room,)).fetchone()[0]
        )
        state["seats"][0]["opening_budget"] = 999  # no command did this
        conn.execute("UPDATE rooms SET state_json=? WHERE id=?", (json.dumps(state), room))
    dest = tmp_path / "copies"
    assert abv.run(st.path, dest, keep=3) == 1
    assert list(dest.glob("*.FAILED")) and not list(dest.glob("*.gz"))


def test_missing_store_is_a_failure_not_a_pass(tmp_path):
    assert abv.run(tmp_path / "nope" / "auction.sqlite", tmp_path / "copies", keep=3) == 2
