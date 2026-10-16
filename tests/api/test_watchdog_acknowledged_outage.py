"""Acknowledged fetch outages in the staleness watchdog (#1726, 2026-10-16).

The scheduled refresh had been red on every run since 2026-10-10 because
``idpShowCombined``'s FETCH (a prod timer behind a hand-minted cookie) went
silent on 2026-10-07 — while the board already withheld the source from every
vote (its vendor content has not changed since 2026-08-19, so the freshness
weighting quarantines it).  A source that cannot move a value made the whole
data job permanently red, so a real failure would have been invisible.

``acknowledgedFetchOutages`` downgrades exactly such a source to DEGRADED —
loud, non-fatal — and nothing else.  These tests pin every branch:

* acknowledged fetch outage + board withholds it  -> DEGRADED, exit 0
* acknowledged, but the source STILL VOTES         -> FAIL (named refusal)
* fetch failure with no acknowledgement            -> FAIL, even when the
  board already withholds it: a fetch failure is never relabelled as a vendor
  publication gap by inference
* expired / over-long / malformed acknowledgement  -> FAIL
* unbuildable board (no vote census)               -> FAIL
* healthy                                          -> pass
* vendor-frozen content with a FRESH fetch stamp   -> pass, untouched: content
  staleness is the freshness weighting's job, not this fetch watchdog's
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import watchdog_freshness as wf

_REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)

ACK = {
    "issue": "#1726",
    "reason": "test",
    "acknowledgedAt": "2026-10-16T00:00:00Z",
    "expiresAt": "2026-10-23T00:00:00Z",
}
WITHHELD = {"role": "model_input", "votingRows": 0, "excludedRows": 655}
VOTING = {"role": "model_input", "votingRows": 384, "excludedRows": 0}

STALE_ROW = ("idpShowCombined", 205.0, 24.0, "2026-10-07T20:32:14+00:00")


def _split(ack=ACK, census=WITHHELD, *, key="idpShowCombined", now=NOW):
    acks = {} if ack is None else {key: ack}
    vote_census = None if census is None else {"idpShowCombined": census}
    return wf.split_acknowledged_outages([STALE_ROW], acks, vote_census, now)


# ── pure decision core ─────────────────────────────────────────────────────


def test_acknowledged_outage_withheld_from_voting_is_degraded():
    hard, degraded, refusals = _split()
    assert hard == []
    assert refusals == {}
    assert [d[0] for d in degraded] == ["idpShowCombined"]
    line = wf.degraded_line(degraded[0])
    assert line.startswith("degraded: idpShowCombined")
    assert "#1726" in line and "2026-10-23" in line and "FETCH outage" in line


def test_acknowledged_outage_that_still_votes_fails():
    hard, degraded, refusals = _split(census=VOTING)
    assert [h[0] for h in hard] == ["idpShowCombined"]
    assert degraded == []
    assert refusals == {"idpShowCombined": "stale_source_still_votes_on_384_rows"}


def test_unacknowledged_fetch_failure_fails_even_when_withheld():
    """No inference from 'the board withholds it' to 'it is fine'."""
    hard, degraded, refusals = _split(ack=None, census=WITHHELD)
    assert [h[0] for h in hard] == ["idpShowCombined"]
    assert degraded == [] and refusals == {}


def test_acknowledgement_never_covers_a_vendor_family_prefix():
    hard, degraded, _ = _split(key="idpShow")
    assert [h[0] for h in hard] == ["idpShowCombined"]
    assert degraded == []


@pytest.mark.parametrize(
    ("ack", "reason"),
    [
        ({**ACK, "expiresAt": "2026-10-16T11:59:59Z"}, "acknowledgement_expired"),
        ({**ACK, "acknowledgedAt": "2026-10-17T00:00:00Z"}, "acknowledgement_not_yet_active"),
        (
            {**ACK, "acknowledgedAt": "2026-10-01T00:00:00Z", "expiresAt": "2026-10-20T00:00:00Z"},
            "acknowledgement_span_exceeds_14d",
        ),
        ({**ACK, "issue": ""}, "acknowledgement_missing_issue"),
        ({**ACK, "expiresAt": "2026-10-23T00:00:00"}, "acknowledgement_missing_or_unzoned_dates"),
        ({**ACK, "expiresAt": "next week"}, "acknowledgement_missing_or_unzoned_dates"),
        ("yes", "acknowledgement_malformed"),
    ],
)
def test_invalid_acknowledgement_fails_with_named_reason(ack, reason):
    hard, degraded, refusals = _split(ack=ack)
    assert [h[0] for h in hard] == ["idpShowCombined"]
    assert degraded == []
    assert refusals == {"idpShowCombined": reason}


@pytest.mark.parametrize(
    ("census_map", "reason"),
    [
        (None, "board_vote_census_unavailable"),
        ({}, "source_not_in_board_vote_census"),
        ({"idpShowCombined": {"role": "benchmark"}}, "source_not_in_board_vote_census"),
        (
            {"idpShowCombined": {"role": "model_input", "votingRows": None, "excludedRows": 3}},
            "board_vote_census_has_no_row_counts",
        ),
        (
            {"idpShowCombined": {"role": "model_input", "votingRows": False, "excludedRows": 3}},
            "board_vote_census_has_no_row_counts",
        ),
        (
            {"idpShowCombined": {"role": "model_input", "votingRows": 0, "excludedRows": 0}},
            "source_absent_from_board_not_withheld",
        ),
    ],
)
def test_missing_or_ambiguous_vote_evidence_fails_closed(census_map, reason):
    hard, degraded, refusals = wf.split_acknowledged_outages(
        [STALE_ROW], {"idpShowCombined": ACK}, census_map, NOW
    )
    assert [h[0] for h in hard] == ["idpShowCombined"]
    assert degraded == []
    assert refusals == {"idpShowCombined": reason}


def test_loader_reads_only_the_named_block(tmp_path):
    cfg = tmp_path / "s.json"
    cfg.write_text(json.dumps({"acknowledgedFetchOutages": {"_c": "x", "a": ACK}}))
    assert wf.load_acknowledged_fetch_outages(cfg) == {"a": ACK}
    assert wf.load_acknowledged_fetch_outages(tmp_path / "missing.json") == {}
    (tmp_path / "bad.json").write_text("{not json")
    assert wf.load_acknowledged_fetch_outages(tmp_path / "bad.json") == {}


def test_shipped_acknowledgements_are_well_formed_and_bounded():
    """Every shipped entry is a dated, issue-tracked, <=14-day promise.

    Deliberately NOT asserted: that it is unexpired.  Expiry turning the job
    red again is the mechanism working.
    """
    acks = wf.load_acknowledged_fetch_outages()
    for key, entry in acks.items():
        at = wf._parse_utc(entry.get("acknowledgedAt"))
        refusal = wf.acknowledgement_refusal(entry, at) if at else "unparseable"
        assert refusal is None, f"{key}: {refusal}"
        from src.api.data_contract import _SOURCE_CSV_PATHS

        assert key in _SOURCE_CSV_PATHS, f"{key} is not a registered source key"


# ── main(): exit codes end to end (IO seams patched) ───────────────────────


def _patch_main(monkeypatch, freshness, acks, census):
    monkeypatch.setattr(wf, "_read_freshness", lambda: dict(freshness))
    monkeypatch.setattr(wf, "unmeasurable_sources", lambda: [])
    monkeypatch.setattr(wf, "unprovisioned_private_sources", lambda: [])
    monkeypatch.setattr(wf, "split_seasonally_inactive", lambda f, t: (f, {}, {}))
    monkeypatch.setattr(wf, "load_thresholds", lambda: {"idpShow": 24.0, "fantasyCalc": 24.0})
    monkeypatch.setattr(wf, "load_soft_sources", lambda: {"idpShow"})
    monkeypatch.setattr(wf, "load_soft_escalation_hours", lambda: 72.0)
    monkeypatch.setattr(wf, "load_acknowledged_fetch_outages", lambda: dict(acks))
    calls = []

    def _census():
        calls.append(1)
        return census

    monkeypatch.setattr(wf, "board_vote_census", _census)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return calls


def _now_ack():
    now = datetime.now(tz=timezone.utc).replace(microsecond=0)
    return {
        "issue": "#1726",
        "acknowledgedAt": (now - timedelta(hours=1)).isoformat(),
        "expiresAt": (now + timedelta(days=7)).isoformat(),
    }


STALE_IDPSHOW = {"idpShowCombined": {"ageHours": 205.0, "lastFetched": "2026-10-07T20:32:14"}}
FRESH_FC = {"fantasyCalc": {"ageHours": 1.0, "lastFetched": "now"}}


def test_main_degraded_withheld_outage_exits_zero_and_says_so(monkeypatch, capsys):
    _patch_main(
        monkeypatch,
        {**STALE_IDPSHOW, **FRESH_FC},
        {"idpShowCombined": _now_ack()},
        {"idpShowCombined": WITHHELD},
    )
    assert wf.main() == 0
    out = capsys.readouterr().out
    assert "::warning title=DEGRADED (acknowledged fetch outage): idpShowCombined" in out
    assert "\ndegraded: idpShowCombined" in out
    ok = [ln for ln in out.splitlines() if ln.startswith("ok:")]
    assert ok and "1 DEGRADED" in ok[0] and "idpShowCombined" in ok[0]


def test_main_acknowledged_but_voting_exits_one(monkeypatch, capsys):
    _patch_main(
        monkeypatch,
        {**STALE_IDPSHOW, **FRESH_FC},
        {"idpShowCombined": _now_ack()},
        {"idpShowCombined": {**WITHHELD, "votingRows": 636}},
    )
    assert wf.main() == 1
    out = capsys.readouterr().out
    assert "stale_source_still_votes_on_636_rows" in out
    assert "degraded:" not in out


def test_main_unacknowledged_fetch_failure_exits_one(monkeypatch, capsys):
    calls = _patch_main(
        monkeypatch,
        {**STALE_IDPSHOW, **FRESH_FC},
        {},
        {"idpShowCombined": WITHHELD},
    )
    assert wf.main() == 1
    assert calls == [], "no acknowledgement applies, so no board is built"
    assert "Stale: idpShowCombined" in capsys.readouterr().out


def test_main_degraded_does_not_mask_another_stale_voting_source(monkeypatch, capsys):
    _patch_main(
        monkeypatch,
        {**STALE_IDPSHOW, "fantasyCalc": {"ageHours": 72.0, "lastFetched": "x"}},
        {"idpShowCombined": _now_ack()},
        {"idpShowCombined": WITHHELD, "fantasyCalc": VOTING},
    )
    assert wf.main() == 1
    out = capsys.readouterr().out
    assert "degraded: idpShowCombined" in out  # still named for the issue text
    fail = [ln for ln in out.splitlines() if ln.startswith("fail:")]
    assert fail and "Stale: fantasyCalc" in fail[0] and "1 degraded" in fail[0]


def test_main_healthy_exits_zero_without_building_a_board(monkeypatch, capsys):
    calls = _patch_main(
        monkeypatch,
        {"idpShowCombined": {"ageHours": 1.0, "lastFetched": "now"}, **FRESH_FC},
        {"idpShowCombined": _now_ack()},
        None,
    )
    assert wf.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "degraded:" not in out and "DEGRADED" not in out


def test_vendor_frozen_content_with_fresh_fetch_is_not_this_watchdogs_failure(monkeypatch, capsys):
    """Fresh fetch stamp + quarantined content: passes, unacknowledged.

    Content staleness is decided by the freshness weighting (which withholds
    the votes) and reported by check_source_health / the alert engine.  The
    fetch watchdog neither fails it nor needs an acknowledgement for it.
    """
    _patch_main(
        monkeypatch,
        {"idpShowCombined": {"ageHours": 1.5, "lastFetched": "now"}, **FRESH_FC},
        {},
        {"idpShowCombined": WITHHELD},
    )
    assert wf.main() == 0
    assert "ok: 2 sources fresh" in capsys.readouterr().out


# ── workflow wiring ────────────────────────────────────────────────────────


def _step(name: str) -> str:
    text = (_REPO_ROOT / ".github/workflows/scheduled-refresh.yml").read_text(encoding="utf-8")
    start = text.index(f"- name: {name}")
    nxt = text.find("\n      - name: ", start + 1)
    return text[start : nxt if nxt != -1 else len(text)]


def test_failure_issue_names_degraded_sources():
    alert = _step("Alert on workflow failure")
    assert "grep -E '^degraded:'" in alert
    assert "${DEGRADED_SUMMARY}" in alert


def test_green_run_does_not_close_tracking_issue_while_degraded():
    close = _step("Close the tracking issue on a green run")
    guard = close.index("grep -qE '^degraded:'")
    assert guard < close.index("gh issue close"), "the degraded guard must run before closing"
