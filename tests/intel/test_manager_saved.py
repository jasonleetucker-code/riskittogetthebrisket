"""Manager Intelligence Batch F — saved managers (``src/intel/manager_saved.py``).

Identity is the permanent Sleeper user id: a rename keeps the entry and shows
the new name; a username later taken by someone else never rewrites it.
"""

from __future__ import annotations

import pytest

from src.api import user_kv
from src.intel import manager_saved as ms
from src.public_league import sleeper_client as sc

KV = "owner"


def _user(uid: str, username: str, display: str | None = None) -> dict:
    return {"user_id": uid, "username": username, "display_name": display or username}


class Clock:
    def __init__(self, t: float = 1_700_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


@pytest.fixture(autouse=True)
def _fresh_memo():
    ms.reset_name_memo()
    yield
    ms.reset_name_memo()


@pytest.fixture
def kv(tmp_path):
    return tmp_path / "kv.sqlite"


def test_save_is_keyed_by_user_id_and_idempotent(kv):
    entry, created, entries = ms.save_manager(KV, _user("111", "alpha"), path=kv)
    assert created is True and entry["userId"] == "111" and entry["alerts"] is True
    assert entry["nameState"] == ms.NAME_CURRENT
    again, created2, entries2 = ms.save_manager(KV, _user("111", "alpha"), path=kv)
    assert created2 is False and len(entries2) == 1
    stored = user_kv.get_user_state(KV, path=kv)[ms.SAVED_FIELD]["managers"]
    assert [e["userId"] for e in stored] == ["111"]
    # nameState describes a response, never the stored entry.
    assert "nameState" not in stored[0]


def test_alerts_toggle_updates_in_place(kv):
    ms.save_manager(KV, _user("111", "alpha"), path=kv)
    entry, created, _ = ms.save_manager(KV, _user("111", "alpha"), alerts=False, path=kv)
    assert created is False and entry["alerts"] is False
    entry, _c, _e = ms.save_manager(KV, _user("111", "alpha"), path=kv)
    assert entry["alerts"] is False  # unspecified leaves it alone


def test_cap_refuses_the_fifty_first(kv):
    for i in range(ms.MAX_SAVED):
        ms.save_manager(KV, _user(str(1000 + i), f"m{i}"), path=kv)
    with pytest.raises(ms.SavedError) as err:
        ms.save_manager(KV, _user("9999", "late"), path=kv)
    assert err.value.code == "saved_limit_reached"
    # Re-saving an existing one at the cap is still allowed.
    _e, created, entries = ms.save_manager(KV, _user("1000", "m0"), path=kv)
    assert created is False and len(entries) == ms.MAX_SAVED


def test_remove_drops_entry_and_alert_state(kv):
    ms.save_manager(KV, _user("111", "alpha"), path=kv)
    ms.save_manager(KV, _user("222", "beta"), path=kv)
    user_kv.mutate_user_state(
        KV, lambda s: s.update({ms.ALERT_FIELD: {"111": {"seededAt": 1}}}), path=kv
    )
    removed, entries = ms.remove_manager(KV, "111", path=kv)
    assert removed is True and [e["userId"] for e in entries] == ["222"]
    assert "111" not in user_kv.get_user_state(KV, path=kv)[ms.ALERT_FIELD]
    removed2, _ = ms.remove_manager(KV, "111", path=kv)
    assert removed2 is False


def test_rename_keeps_the_entry_and_refreshes_the_name(kv):
    clock = Clock()
    ms.save_manager(KV, _user("111", "oldname", "Old Name"), path=kv, now=clock)
    calls = []

    def fetch(handle):
        calls.append(handle)
        return sc.FETCH_OK, _user("111", "newname", "New Name")

    out = ms.list_saved(KV, fetch_user=fetch, path=kv, now=clock)
    assert calls == ["111"]  # re-read by the id, never the stored username
    (m,) = out["managers"]
    assert m["userId"] == "111" and m["username"] == "newname"
    assert m["displayName"] == "New Name" and m["previousUsernames"] == ["oldname"]
    assert m["nameState"] == ms.NAME_CURRENT
    stored = user_kv.get_user_state(KV, path=kv)[ms.SAVED_FIELD]["managers"][0]
    assert stored["username"] == "newname" and stored["previousUsernames"] == ["oldname"]


def test_old_username_taken_by_someone_else_never_rewrites_the_entry(kv):
    ms.save_manager(KV, _user("111", "alpha"), path=kv)

    def fetch(handle):
        # Sleeper is asked by id; another user now owns "alpha", irrelevant.
        assert handle == "111"
        return sc.FETCH_OK, _user("111", "alpha_renamed")

    out = ms.list_saved(KV, fetch_user=fetch, path=kv)
    assert out["managers"][0]["userId"] == "111"
    assert out["managers"][0]["username"] == "alpha_renamed"


@pytest.mark.parametrize(
    ("kind", "user", "state"),
    [
        (sc.FETCH_RATE_LIMITED, None, ms.NAME_STORED),
        (sc.FETCH_ERROR, None, ms.NAME_STORED),
        (sc.FETCH_NOT_FOUND, None, ms.NAME_NOT_FOUND),
        (sc.FETCH_OK, {"user_id": "999", "username": "other"}, ms.NAME_ID_MISMATCH),
    ],
)
def test_failed_reread_serves_stored_name_and_says_so(kv, kind, user, state):
    ms.save_manager(KV, _user("111", "alpha", "Alpha"), path=kv)
    out = ms.list_saved(KV, fetch_user=lambda h: (kind, user), path=kv)
    (m,) = out["managers"]
    assert m["username"] == "alpha" and m["displayName"] == "Alpha"
    assert m["nameState"] == state


def test_name_reread_is_memoised(kv):
    clock = Clock()
    ms.save_manager(KV, _user("111", "alpha"), path=kv)
    calls = []

    def fetch(h):
        calls.append(h)
        return sc.FETCH_OK, _user("111", "alpha")

    ms.list_saved(KV, fetch_user=fetch, path=kv, now=clock)
    ms.list_saved(KV, fetch_user=fetch, path=kv, now=clock)
    assert calls == ["111"]
    clock.t += ms.NAME_TTL_SECONDS + 1
    ms.list_saved(KV, fetch_user=fetch, path=kv, now=clock)
    assert calls == ["111", "111"]


def test_empty_list_spends_no_calls(kv):
    out = ms.list_saved(KV, fetch_user=lambda h: pytest.fail("no call"), path=kv)
    assert out["managers"] == [] and out["count"] == 0 and out["limit"] == ms.MAX_SAVED


def test_invalid_user_object_is_refused(kv):
    with pytest.raises(ms.SavedError):
        ms.save_manager(KV, {"user_id": "abc"}, path=kv)
