"""Trade Desk owner (Part 12) — statuses are user-entered; roster check is evidence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.trade import trade_desk as desk

TEAMS = ["Us", "Them", "Other"]
T0 = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)


def _body(**over):
    body = {
        "leagueKey": "main",
        "myTeam": "Us",
        "opponent": "Them",
        "send": [{"name": "Our WR", "assetId": "player:1", "position": "WR"}],
        "receive": [{"name": "Their RB"}, {"name": "2027 Round 1", "isPick": True}],
        "source": "best_offers",
        "sourceRunId": "abcdef0123456789abcd",
    }
    body.update(over)
    return body


def test_a_new_item_is_a_user_marked_candidate_with_its_provenance():
    item = desk.new_item(_body(), team_names=TEAMS, now=T0)
    assert item["status"] == "candidate"
    assert item["statusHistory"] == [{"status": "candidate", "at": T0.isoformat(), "setBy": "user"}]
    assert item["source"] == "best_offers" and item["sourceRunId"] == "abcdef0123456789abcd"
    assert item["send"] == [
        {"name": "Our WR", "isPick": False, "assetId": "player:1", "position": "WR"}
    ]
    assert item["receive"][1] == {"name": "2027 Round 1", "isPick": True}
    assert len(item["id"]) == 16


@pytest.mark.parametrize(
    ("over", "code"),
    [
        ({"myTeam": "Nobody"}, "unknown_team"),
        ({"opponent": "Us"}, "invalid_body"),
        ({"send": []}, "invalid_body"),
        ({"receive": [{"name": ""}]}, "invalid_body"),
        (
            {"send": [{"name": f"p{i}"} for i in range(desk.MAX_ASSETS_PER_SIDE + 1)]},
            "invalid_body",
        ),
        ({"source": "autosend"}, "invalid_body"),
        ({"status": "sent_by_app"}, "invalid_status"),
        ({"sourceRunId": "not hex!"}, "invalid_body"),
        ({"note": "x" * (desk.MAX_NOTE_LEN + 1)}, "invalid_body"),
        ({"send": [{"name": "A", "assetId": "bad id with spaces"}]}, "invalid_body"),
    ],
)
def test_invalid_creates_are_refused(over, code):
    with pytest.raises(desk.DeskError) as e:
        desk.new_item(_body(**over), team_names=TEAMS, now=T0)
    assert e.value.code == code


def test_the_same_package_is_a_duplicate_whatever_the_asset_order():
    a = desk.new_item(_body(), team_names=TEAMS, now=T0)
    entry = desk.add_item(None, a)
    reordered = _body(receive=list(reversed(_body()["receive"])))
    b = desk.new_item(reordered, team_names=TEAMS, now=T1)
    with pytest.raises(desk.DeskError) as e:
        desk.add_item(entry, b)
    assert e.value.code == "duplicate" and e.value.detail == {"id": a["id"]}


def test_the_desk_is_bounded():
    entry = None
    for i in range(desk.MAX_ITEMS):
        entry = desk.add_item(
            entry, desk.new_item(_body(send=[{"name": f"p{i}"}]), team_names=TEAMS, now=T0)
        )
    with pytest.raises(desk.DeskError) as e:
        desk.add_item(entry, desk.new_item(_body(), team_names=TEAMS, now=T0))
    assert e.value.code == "desk_full"


def test_status_changes_append_user_history_and_notes_do_not():
    item = desk.new_item(_body(), team_names=TEAMS, now=T0)
    entry = desk.add_item(None, item)
    entry = desk.update_item(entry, item["id"], {"status": "manually_sent"}, now=T1)
    entry = desk.update_item(entry, item["id"], {"note": "  pinged them  "}, now=T1)
    (got,) = entry["items"]
    assert got["status"] == "manually_sent"
    assert [h["status"] for h in got["statusHistory"]] == ["candidate", "manually_sent"]
    assert {h["setBy"] for h in got["statusHistory"]} == {"user"}
    assert got["note"] == "pinged them"
    # Re-marking the same status is not a new event.
    entry = desk.update_item(entry, item["id"], {"status": "manually_sent"}, now=T1)
    assert len(entry["items"][0]["statusHistory"]) == 2


def test_update_and_remove_need_a_real_id():
    item = desk.new_item(_body(), team_names=TEAMS, now=T0)
    entry = desk.add_item(None, item)
    for bad in ("0" * 16, "../etc", ""):
        with pytest.raises(desk.DeskError) as e:
            desk.update_item(entry, bad, {"status": "saved"})
        assert e.value.code == "not_found"
    with pytest.raises(desk.DeskError):
        desk.update_item(entry, item["id"], {})
    assert desk.remove_item(entry, item["id"]) is None  # empty desk stores nothing


def _teams(us, them):
    return {"Us": {"name": "Us", "players": us}, "Them": {"name": "Them", "players": them}}


def test_roster_check_is_evidence_and_never_rewrites_status():
    item = desk.new_item(_body(), team_names=TEAMS, now=T0)
    ok = desk.roster_check(item, _teams(["Our WR"], ["Their RB"]))
    assert ok == {"state": "current", "noLongerInPlace": [], "picksNotChecked": 1}
    moved = desk.roster_check(item, _teams(["Our WR"], ["Someone Else"]))
    assert moved["state"] == "changed" and moved["noLongerInPlace"] == ["Their RB"]
    assert desk.roster_check(item, None)["state"] == "unknown"
    assert desk.roster_check(item, {"Us": {"players": []}})["state"] == "unknown"
    payload = desk.payload("main", desk.add_item(None, item), teams_by_name=_teams([], []))
    assert payload["items"][0]["status"] == "candidate"
    assert payload["items"][0]["rosterCheck"]["state"] == "changed"
    assert payload["action"] == "recommend_only"
    assert [s["value"] for s in payload["statuses"]] == list(desk.STATUSES)


def test_unknown_request_fields_are_named():
    assert desk.unknown_keys({"leagueKey": "m", "send": [], "execute": True}, create=True) == [
        "execute"
    ]
    assert desk.unknown_keys({"leagueKey": "m", "myTeam": "Us"}, create=False) == ["myTeam"]
