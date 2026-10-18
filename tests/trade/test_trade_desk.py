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


def test_a_renamed_team_is_still_found_by_its_owner_id():
    item = desk.new_item(_body(), team_names=TEAMS, owner_ids={"Us": "1", "Them": "2"}, now=T0)
    assert (item["myOwnerId"], item["opponentOwnerId"]) == ("1", "2")
    renamed = {
        "Us": {"name": "Us", "ownerId": "1", "players": ["Our WR"]},
        "Them Renamed": {"name": "Them Renamed", "ownerId": "2", "players": ["Their RB"]},
    }
    assert desk.roster_check(item, renamed)["state"] == "current"


def test_a_name_now_held_by_another_owner_is_never_matched():
    item = desk.new_item(_body(), team_names=TEAMS, owner_ids={"Us": "1", "Them": "2"}, now=T0)
    swapped = {
        "Us": {"name": "Us", "ownerId": "1", "players": ["Our WR"]},
        "Them": {"name": "Them", "ownerId": "9", "players": ["Their RB"]},
    }
    assert desk.roster_check(item, swapped) == {"state": "unknown", "reason": "team_not_in_league"}


def test_the_duplicate_check_survives_a_rename():
    a = desk.new_item(_body(), team_names=TEAMS, owner_ids={"Us": "1", "Them": "2"}, now=T0)
    entry = desk.add_item(None, a)
    b = desk.new_item(
        _body(opponent="Other"), team_names=TEAMS, owner_ids={"Us": "1", "Other": "2"}, now=T1
    )
    with pytest.raises(desk.DeskError) as e:
        desk.add_item(entry, b)
    assert e.value.code == "duplicate"


# ── TC-B2 / TCM-G18: the War Room decision a calculator save carries ──────

_RUN = "0123456789abcdef0123"
_LINE = {
    "runId": _RUN,
    "recordedAt": "2026-10-18T12:00:00+00:00",
    "leagueKey": "main",
    "team": "Us",
    "headline": "YES",
    "confidenceLevel": "MEDIUM",
    "strategy": {"used": "BALANCED", "source": "posture"},
    "teamContext": True,
    "decisionVersion": "trade_decision_v2",
    "receipt": {"packageModel": {"id": "geom_q078_v1"}},
}


def _calc(**over):
    return _body(**{"source": "calculator", "sourceRunId": None, "decisionRunId": _RUN, **over})


def test_a_calculator_save_carries_the_logged_decision_never_a_client_verdict():
    seen = []

    def lookup(run_id):
        seen.append(run_id)
        return _LINE

    item = desk.new_item(
        _calc(), team_names=TEAMS, now=T0, league_key="main", decision_lookup=lookup
    )
    assert seen == [_RUN]
    assert item["decision"] == {
        "runId": _RUN,
        "recordedAt": "2026-10-18T12:00:00+00:00",
        "headline": "YES",
        # The words come from the decision owner, not the request.
        "headlineText": "YES — MAKE THE TRADE",
        "confidenceLevel": "MEDIUM",
        "strategy": "BALANCED",
        "teamContext": True,
        "decisionVersion": "trade_decision_v2",
        "packageModel": "geom_q078_v1",
    }
    assert "decisionUnavailable" not in item
    # A snapshot is evidence: the status is still the user's.
    assert item["status"] == "candidate"


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        (None, "decision_run_not_found"),
        ({**_LINE, "leagueKey": "other"}, "decision_run_other_league"),
        ({**_LINE, "team": "Them"}, "decision_run_other_team"),
        ({**_LINE, "headline": "MAYBE"}, "decision_run_unreadable"),
    ],
)
def test_an_unverifiable_decision_is_not_attached_and_the_package_still_saves(line, reason):
    item = desk.new_item(
        _calc(), team_names=TEAMS, league_key="main", decision_lookup=lambda _r: line
    )
    assert "decision" not in item
    assert item["decisionUnavailable"] == reason
    assert item["send"] and item["receive"]


def test_a_decision_run_is_refused_outside_calculator_saves_or_malformed():
    with pytest.raises(desk.DeskError) as e:
        desk.new_item(_body(decisionRunId=_RUN), team_names=TEAMS)
    assert e.value.code == "invalid_body"
    with pytest.raises(desk.DeskError):
        desk.new_item(_calc(decisionRunId="not hex!"), team_names=TEAMS)
    assert desk.unknown_keys(_calc(), create=True) == []


def test_find_decision_run_reads_the_server_log(tmp_path):
    from src.trade import trade_decision_log as log

    run = log.record_decision(
        {"decision": {"headline": "NO", "version": "v"}, "version": "p"},
        league_key="main",
        team="Us",
        log_dir=tmp_path,
    )
    assert run
    found = log.find_decision_run(run, log_dir=tmp_path)
    assert found["runId"] == run and found["headline"] == "NO"
    assert log.find_decision_run("ffffffffffffffffffff", log_dir=tmp_path) is None
    assert log.find_decision_run("", log_dir=tmp_path) is None
    assert log.find_decision_run(run, log_dir=tmp_path / "missing") is None
    # A torn line is skipped, never fatal.
    (tmp_path / "runs-2099-01.jsonl").write_text('{"runId": "' + run + '"\n')
    assert log.find_decision_run(run, log_dir=tmp_path)["runId"] == run
