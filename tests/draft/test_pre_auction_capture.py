"""Pre-auction snapshot automation: gate, idempotency, refusal after start.

No network: Sleeper drafts, league resolution and the board build are fakes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from scripts.capture_pre_auction_snapshot import (
    EXIT_NO_BOARD,
    EXIT_OK,
    EXIT_SKIPPED,
    EXIT_TRANSIENT,
    run,
)
from src.draft import pre_auction_capture as pac

NOW = datetime(2027, 6, 1, 12, 0, tzinfo=timezone.utc)


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _draft(status="pre_draft", start=None, season="2027", did="d1"):
    return {
        "draft_id": did,
        "season": season,
        "status": status,
        "type": "auction",
        "start_time": start,
    }


def _resolve(*_a):
    return "dynasty_main", "LID", 2027


def _build_ok(_key):
    return {
        "capturedAt": "x",
        "boardHash": "h",
        "rookies": [1],
        "rosterContexts": {},
        "provenance": {"boardProducedAt": (NOW - timedelta(hours=1)).isoformat()},
    }, 0


def _call(tmp_path, drafts, build=_build_ok, now=NOW, kind="ok"):
    return run(
        out_dir=tmp_path,
        now=now,
        resolve=_resolve,
        fetch_drafts=lambda _lid: (kind, drafts),
        build=build,
    )


def test_inside_window_records_pre_with_receipt(tmp_path):
    start = _ms(NOW + timedelta(days=3))
    assert _call(tmp_path, [_draft(start=start)]) == EXIT_OK
    data = json.loads((tmp_path / "2027-pre.json").read_text(encoding="utf-8"))
    assert data["captureReceipt"]["kind"] == "pre"
    assert data["captureReceipt"]["scheduledStart"].startswith("2027-06-04")
    assert data["boardHash"] == "h"


def test_first_valid_wins_never_overwrites(tmp_path):
    start = _ms(NOW + timedelta(days=3))
    assert _call(tmp_path, [_draft(start=start)]) == EXIT_OK
    first = (tmp_path / "2027-pre.json").read_text(encoding="utf-8")

    def boom(_k):
        raise AssertionError("must not rebuild once held")

    assert (
        _call(tmp_path, [_draft(start=start)], build=boom, now=NOW + timedelta(days=1)) == EXIT_OK
    )
    assert (tmp_path / "2027-pre.json").read_text(encoding="utf-8") == first


def test_started_draft_refuses_and_writes_nothing(tmp_path):
    for status in ("drafting", "complete"):
        assert _call(tmp_path, [_draft(status=status)]) == EXIT_SKIPPED
    # start_time already passed while Sleeper still says pre_draft
    assert _call(tmp_path, [_draft(start=_ms(NOW - timedelta(hours=1)))]) == EXIT_SKIPPED
    assert list(tmp_path.iterdir()) == []


def test_before_window_and_unscheduled_write_one_early_copy_per_week(tmp_path):
    far = _ms(NOW + timedelta(days=60))
    assert _call(tmp_path, [_draft(start=far)]) == EXIT_OK
    assert _call(tmp_path, [], now=NOW + timedelta(days=1)) == EXIT_OK  # same ISO week
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["2027-early-2027W22.json"]
    assert not (tmp_path / "2027-pre.json").exists()


def test_other_season_drafts_are_ignored(tmp_path):
    assert _call(tmp_path, [_draft(status="complete", season="2026")]) == EXIT_OK
    assert (tmp_path / "2027-early-2027W22.json").exists()


def test_unreadable_drafts_are_transient_not_not_started(tmp_path):
    assert _call(tmp_path, None, kind="error") == EXIT_TRANSIENT
    assert list(tmp_path.iterdir()) == []


def test_build_skip_writes_nothing(tmp_path):
    start = _ms(NOW + timedelta(days=1))
    assert _call(tmp_path, [_draft(start=start)], build=lambda _k: (None, 2)) == EXIT_NO_BOARD
    assert list(tmp_path.iterdir()) == []


def test_write_once_is_no_replace(tmp_path):
    p = tmp_path / "x.json"
    assert pac.write_once(p, {"a": 1}) is True
    assert pac.write_once(p, {"a": 2}) is False
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_margin_crossed_during_build_writes_nothing(tmp_path):
    start = _ms(NOW + timedelta(minutes=20))
    ticks = iter([NOW, NOW + timedelta(minutes=10)])
    code = run(
        out_dir=tmp_path,
        clock=lambda: next(ticks),
        resolve=_resolve,
        fetch_drafts=lambda _l: ("ok", [_draft(start=start)]),
        build=_build_ok,
    )
    assert code == EXIT_SKIPPED
    assert list(tmp_path.iterdir()) == []


def _stale_build(age):
    def build(_k):
        payload, code = _build_ok(_k)
        payload["provenance"] = {"boardProducedAt": age}
        return payload, code

    return build


def test_stale_or_unknown_age_board_writes_nothing_and_retries(tmp_path):
    start = _ms(NOW + timedelta(days=1))
    for age in ((NOW - timedelta(hours=7)).isoformat(), None, "garbage"):
        assert _call(tmp_path, [_draft(start=start)], build=_stale_build(age)) == EXIT_NO_BOARD
        assert list(tmp_path.iterdir()) == []
    # early path too
    assert _call(tmp_path, [_draft()], build=_stale_build(None)) == EXIT_NO_BOARD
    assert list(tmp_path.iterdir()) == []
