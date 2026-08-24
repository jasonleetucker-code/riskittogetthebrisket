"""The retention health surface.

The failure this whole tranche is built against is a recorder that ships,
stops, and stays quiet.  A health check that reports ``ok`` for a dead
stream reproduces it exactly, so these tests are mostly about the states
that must NOT be ``ok``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.retention import evidence_store, health, league_events


@pytest.fixture
def data_dir(tmp_path):
    evidence_store._reset_setup_cache_for_tests()
    league_events._reset_setup_cache_for_tests()
    d = tmp_path / "data"
    d.mkdir()
    yield d
    evidence_store._reset_setup_cache_for_tests()
    league_events._reset_setup_cache_for_tests()


def _by_id(report):
    return {s["id"]: s for s in report["streams"]}


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_every_manifest_row_is_probed(data_dir):
    report = health.retention_health(data_dir=data_dir)
    assert sorted(_by_id(report)) == [f"C1-RET-0{n}" for n in range(1, 9)]


def test_an_empty_host_reports_missing_not_ok(data_dir):
    report = health.retention_health(data_dir=data_dir)
    assert report["allOk"] is False
    assert report["counts"][health.STATE_MISSING] == 8
    assert all(s["state"] == health.STATE_MISSING for s in report["streams"])


def test_a_store_that_exists_but_is_empty_is_unknown_not_ok(data_dir):
    """MISSING IS NEVER ZERO: an empty store is the absence of evidence,
    never evidence of absence."""
    db = data_dir / "retention" / "evidence.sqlite"
    evidence_store.connect(db).close()

    streams = _by_id(health.retention_health(data_dir=data_dir))
    assert streams["C1-RET-04"]["state"] == health.STATE_UNKNOWN
    assert streams["C1-RET-05"]["state"] == health.STATE_UNKNOWN


def test_a_fresh_observation_is_ok(data_dir):
    db = data_dir / "retention" / "evidence.sqlite"
    evidence_store.observe_scoring_card("111", {"rec": 1.0}, observed_at=_iso(1), path=db)

    assert (
        _by_id(health.retention_health(data_dir=data_dir))["C1-RET-04"]["state"] == health.STATE_OK
    )


def test_a_recorder_that_stopped_reports_stale(data_dir):
    """A store with content whose newest observation is past budget.
    This is the B-1 pattern — the mechanism shipped and then stopped."""
    db = data_dir / "retention" / "evidence.sqlite"
    evidence_store.observe_scoring_card("111", {"rec": 1.0}, observed_at=_iso(500), path=db)

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-04"]
    assert stream["state"] == health.STATE_STALE
    assert stream["ageHours"] > stream["budgetHours"]


def test_the_private_ledger_is_labelled_private(data_dir):
    streams = _by_id(health.retention_health(data_dir=data_dir))
    assert streams["C1-RET-06"]["privacyClass"] == "private"
    # Everything else defaults to internal — the label is a deliberate
    # per-stream statement, not a blanket one.
    assert streams["C1-RET-04"]["privacyClass"] == "internal"


def test_all_ok_requires_every_stream(data_dir):
    """An aggregate that averaged would let healthy streams hide dead
    ones — the exact failure the module exists for."""
    db = data_dir / "retention" / "evidence.sqlite"
    evidence_store.observe_scoring_card("111", {"rec": 1.0}, observed_at=_iso(1), path=db)

    report = health.retention_health(data_dir=data_dir)
    assert report["counts"][health.STATE_OK] >= 1
    assert report["allOk"] is False


def test_crowd_faab_accumulator_is_probed(data_dir):
    faab = data_dir / "faab"
    faab.mkdir()
    (faab / "crowd_history_dynasty_main.json").write_text(
        json.dumps({"updatedAt": _iso(1), "rows": [{"id": "1"}, {"id": "2"}]}),
        encoding="utf-8",
    )
    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-01"]
    assert stream["state"] == health.STATE_OK
    assert stream["rows"] == 2


def test_an_unreadable_accumulator_is_unknown_not_missing(data_dir):
    """'I could not tell' and 'it was never written' have different
    fixes."""
    faab = data_dir / "faab"
    faab.mkdir()
    (faab / "crowd_history_dynasty_main.json").write_text("{not json", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-01"]
    assert stream["state"] == health.STATE_UNKNOWN


def test_playerctx_snapshots_are_probed(data_dir):
    """A genuinely fresh dated snapshot must probe as healthy.

    Use the test clock instead of a calendar fixture: a fixed filename
    eventually ages past C1-RET-08's 14-day freshness budget and turns
    this positive-path test into a deterministic deploy blocker.
    """
    hist = data_dir / "playerctx" / "history"
    hist.mkdir(parents=True)
    today = datetime.now(timezone.utc).date().isoformat()
    (hist / f"playerctx_{today}.json").write_text("{}", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-08"]
    assert stream["state"] == health.STATE_OK
    assert stream["snapshots"] == 1


def test_identity_reports_are_probed(data_dir):
    ident = data_dir / "identity"
    ident.mkdir()
    (ident / "identity_resolution_2026-04-20.json").write_text("{}", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-07"]
    assert stream["newest"] == "identity_resolution_2026-04-20.json"
    assert stream["stampSource"] == "filename"


def test_a_dated_filename_beats_mtime(data_dir):
    """Measured on the live checkout: mtime put the newest identity
    report at 4 days old, its filename at 116 — the real halt.  A deploy,
    restore or container rebuild rewrites mtime, so trusting it turns a
    four-month gap into "fresh"."""
    ident = data_dir / "identity"
    ident.mkdir()
    old = ident / "identity_report_20260420T194828Z.json"
    old.write_text("{}", encoding="utf-8")  # mtime = now

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-07"]
    assert stream["state"] == health.STATE_STALE
    assert stream["ageHours"] > 2000, "must reflect the filename date, not the fresh mtime"


def test_an_undated_artifact_falls_back_to_mtime_and_says_so(data_dir):
    ident = data_dir / "identity"
    ident.mkdir()
    (ident / "identity_report_latest.json").write_text("{}", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-07"]
    assert stream["stampSource"] == "mtime"
    assert stream["state"] == health.STATE_OK


def test_newest_is_chosen_by_stamp_not_by_write_order(data_dir):
    ident = data_dir / "identity"
    ident.mkdir()
    # Written newest-first on disk; the OLDER name must not win.
    (ident / "identity_report_20260420T000000Z.json").write_text("{}", encoding="utf-8")
    (ident / "identity_report_20260814T000000Z.json").write_text("{}", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-07"]
    assert stream["newest"] == "identity_report_20260814T000000Z.json"


def test_a_probe_failure_does_not_blind_the_other_streams(data_dir, monkeypatch):
    def boom(_root):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(
        health, "_PROBES", (("C1-RET-04", boom), ("C1-RET-01", health._probe_crowd_faab))
    )
    report = health.retention_health(data_dir=data_dir)

    assert len(report["streams"]) == 2
    assert report["streams"][0]["state"] == health.STATE_UNKNOWN
    assert report["streams"][1]["id"] == "C1-RET-01"


def test_a_crashed_probe_keeps_its_stream_id(data_dir, monkeypatch):
    """A crash must degrade the stream, never erase it from the report.

    The id came from the probe's function NAME, so a crashed probe
    reported ``_probe_scoring_cards`` — and ``--require C1-RET-04`` then
    failed with "unknown stream id" (exit 1, the check could not run)
    instead of exit 2 (this stream is unhealthy).  A crash silently
    downgraded itself out of the required set.
    """

    def boom(_root):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(health, "_PROBES", (("C1-RET-04", boom),))
    report = health.retention_health(data_dir=data_dir)

    assert report["streams"][0]["id"] == "C1-RET-04"
    assert report["streams"][0]["state"] == health.STATE_UNKNOWN


def test_the_declared_stream_ids_match_what_is_probed(data_dir):
    """STREAM_IDS is what --require validates against, so it must not
    drift from the probes."""
    report = health.retention_health(data_dir=data_dir)

    assert list(health.STREAM_IDS) == [s["id"] for s in report["streams"]]


def test_report_is_json_serialisable(data_dir):
    """The CLI's --json mode and any CI consumer depend on it."""
    json.dumps(health.retention_health(data_dir=data_dir))


# ── further watchdog bypasses found by adversarial review ────────────


def test_a_future_dated_stamp_does_not_grade_ok(data_dir):
    """A stamp ahead of this host's clock yields a NEGATIVE age, and a
    negative age satisfies any budget — so a stream stopped in March
    graded `ok` if one artifact was dated next year."""
    hist = data_dir / "playerctx" / "history"
    hist.mkdir(parents=True)
    (hist / "playerctx_2027-01-01.json").write_text("{}", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-08"]
    assert stream["state"] == health.STATE_UNKNOWN
    assert stream["ageHours"] < 0


def test_a_small_clock_skew_is_still_ok(data_dir):
    """Writer and prober clocks differ; a few minutes ahead is skew, not
    a corrupt date."""
    faab = data_dir / "faab"
    faab.mkdir()
    (faab / "crowd_history_dynasty_main.json").write_text(
        json.dumps({"updatedAt": _iso(-0.1), "rows": [{"id": "1"}]}), encoding="utf-8"
    )
    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-01"]

    assert stream["state"] == health.STATE_OK


def test_one_corrupt_accumulator_degrades_the_whole_stream(data_dir):
    """A corrupt file beside a healthy one is lost crowd evidence from a
    ~5-day rolling window that cannot be re-fetched.  Grading it `ok`
    because a sibling still parses is "some of it works" reasoning."""
    faab = data_dir / "faab"
    faab.mkdir()
    (faab / "crowd_history_dynasty_main.json").write_text(
        json.dumps({"updatedAt": _iso(1), "rows": [{"id": "1"}]}), encoding="utf-8"
    )
    (faab / "crowd_history_dynasty_new.json").write_text("{truncated", encoding="utf-8")

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-01"]
    assert stream["state"] == health.STATE_UNKNOWN
    # And the corruption is NAMED, not merely reflected in a state.
    assert "unreadable" in stream["detail"]
    assert stream["unreadable"] == ["crowd_history_dynasty_new.json"]


def test_an_undated_sibling_cannot_outrank_a_dated_artifact(data_dir):
    """The anti-mtime defence, defeated by its own fallback: a single
    undated file carries a fresh mtime and outranked every genuinely
    dated artifact, so a collector halted in April read as current."""
    ident = data_dir / "identity"
    ident.mkdir()
    (ident / "identity_report_20260420T194828Z.json").write_text("{}", encoding="utf-8")
    (ident / "identity_report_latest.json").write_text("{}", encoding="utf-8")  # fresh mtime

    stream = _by_id(health.retention_health(data_dir=data_dir))["C1-RET-07"]
    assert stream["stampSource"] == "filename"
    assert stream["state"] == health.STATE_STALE
    assert stream["ageHours"] > 2000
