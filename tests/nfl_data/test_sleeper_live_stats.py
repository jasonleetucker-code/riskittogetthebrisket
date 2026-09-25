"""Sleeper weekly stat lines for Game Day.  Offline: fixtures + injected fetchers."""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.league_comparison import sleeper_stats
from src.nfl_data import sleeper_live_stats as sls

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "game_day"
    / "sleeper"
    / "real_2026w3_thu_sleeper_stats.json"
)
OBSERVED = datetime(2026, 9, 25, 0, 58, 24, tzinfo=timezone.utc)
URL = "https://api.sleeper.app/v1/stats/nfl/regular/2026/3"


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _parse(payload, **kw) -> sls.LiveStatsSnapshot:
    return sls.parse_week_stats(payload, season=2026, week=3, observed_at=OBSERVED, **kw)


# ── Parsing the real capture ─────────────────────────────────────────


def test_real_capture_players_and_team_entries_are_separated():
    snap = _parse(_payload())
    assert snap.ok
    assert snap.payload_shape == sls.SHAPE_PLAYER_MAP
    assert snap.row_count == 9
    assert snap.skipped_rows == 0
    assert set(snap.lines) == {"6804", "8154", "7553", "13545", "6788", "10934", "12586"}
    assert set(snap.team_lines) == {"GB", "TEAM_GB"}
    assert all(line.is_team_entry for line in snap.team_lines.values())
    assert not any(line.is_team_entry for line in snap.lines.values())


def test_real_capture_keeps_sleeper_stat_keys_verbatim_across_positions():
    snap = _parse(_payload())
    qb = snap.line("6804")
    assert qb.stats["pass_yd"] > 0 and "pass_att" in qb.stats
    kicker = snap.line("13545")
    assert {"xpm", "xpa"} <= set(kicker.stats)
    idp = snap.line("6788")
    assert {"idp_int", "idp_tkl_solo", "idp_pass_def"} <= set(idp.stats)
    # No translation into nflverse vocabulary happens here.
    assert not any(k.startswith("def_") or k == "passing_yards" for k in qb.stats)
    assert all(isinstance(v, float) for v in qb.stats.values())


def test_v1_shape_carries_no_provider_timestamp_game_or_team():
    snap = _parse(_payload())
    for line in snap.lines.values():
        assert line.updated_at is None
        assert line.game_id is None
        assert line.team is None


def test_missing_player_is_none_not_zero_and_listed_player_without_production_is_kept():
    snap = _parse(_payload())
    assert snap.line("99999999") is None
    listed = snap.line("12586")
    assert listed is not None
    assert listed.stats == {"gms_active": 1.0}


# ── Row-list shape + malformed rows ──────────────────────────────────


def test_row_list_shape_reads_updated_at_game_and_team():
    payload = [
        {
            "player_id": "6804",
            "stats": {"pass_yd": 120.0, "pass_td": 1},
            "updated_at": 1790297412362,
            "game_id": "202610312",
            "team": "gb",
        }
    ]
    snap = _parse(payload)
    line = snap.line("6804")
    assert snap.payload_shape == sls.SHAPE_ROW_LIST
    assert line.game_id == "202610312"
    assert line.team == "GB"
    assert line.updated_at == datetime.fromtimestamp(1790297412.362, tz=timezone.utc)
    assert line.stats == {"pass_yd": 120.0, "pass_td": 1.0}


def test_malformed_rows_are_skipped_and_counted():
    payload = {
        "6804": {"pass_yd": 10, "note": "text", "flag": True, "nested": {"a": 1}},
        "1": "not-an-object",
        "2": None,
        "": {"rec": 1},
    }
    snap = _parse(payload)
    assert snap.row_count == 4
    assert snap.skipped_rows == 3
    assert snap.skipped_values == 3
    assert snap.line("6804").stats == {"pass_yd": 10.0}


def test_malformed_list_rows_are_skipped():
    snap = _parse([{"player_id": "1", "stats": {"rec": 2}}, "junk", {"stats": {"rec": 1}}, 7])
    assert set(snap.lines) == {"1"}
    assert snap.skipped_rows == 3


@pytest.mark.parametrize(
    ("payload", "shape", "error"),
    [
        (None, sls.SHAPE_MISSING, "missing_payload"),
        ("nope", sls.SHAPE_UNRECOGNIZED, "unrecognized_payload_shape"),
    ],
)
def test_unusable_payloads_carry_named_errors(payload, shape, error):
    snap = _parse(payload)
    assert snap.payload_shape == shape
    assert snap.error == error
    assert snap.lines == {}


# ── Fetch (through the one HTTP owner) ───────────────────────────────


def test_fetch_uses_the_shared_owner_url_and_never_caches():
    seen = []

    def fetcher(url):
        seen.append(url)
        return _payload()

    first = sls.fetch_live_week_stats(2026, 3, fetcher=fetcher, now=lambda: OBSERVED)
    second = sls.fetch_live_week_stats(2026, 3, fetcher=fetcher, now=lambda: OBSERVED)
    assert seen == [URL, URL]
    assert sleeper_stats.week_stats_url(2026, 3) == URL
    assert first.ok and second.ok
    assert first.source_url == URL
    assert first.observed_at == OBSERVED
    assert first.http_status is None  # injected fetcher: status not observed, not assumed 200
    assert len(first.lines) == 7


def test_fetch_http_error_is_a_degraded_snapshot():
    def fetcher(url):
        raise urllib.error.HTTPError(url, 500, "boom", {}, None)

    snap = sls.fetch_live_week_stats(2026, 3, fetcher=fetcher, now=lambda: OBSERVED)
    assert snap.http_status == 500
    assert snap.error == "http_error:500"
    assert snap.payload_shape == sls.SHAPE_MISSING
    assert snap.lines == {}


def test_fetch_network_error_never_raises():
    def fetcher(url):
        raise TimeoutError("slow")

    snap = sls.fetch_live_week_stats(2026, 3, fetcher=fetcher, now=lambda: OBSERVED)
    assert snap.error == "fetch_failed:TimeoutError"
    assert snap.http_status is None


def test_default_path_passes_a_bounded_timeout(monkeypatch):
    seen = {}

    class _Resp:
        status = 200

        def read(self):
            return b'{"6804": {"pass_yd": 5}}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        seen["timeout"] = timeout
        seen["url"] = req.full_url
        return _Resp()

    monkeypatch.setattr(sleeper_stats.urllib.request, "urlopen", fake_urlopen)
    snap = sls.fetch_live_week_stats(2026, 3, now=lambda: OBSERVED)
    assert seen == {"timeout": sls.LIVE_TIMEOUT_SEC, "url": URL}
    assert snap.http_status == 200
    assert snap.line("6804").stats == {"pass_yd": 5.0}


# ── Stat corrections ─────────────────────────────────────────────────


def _line(pid, game_id=None, **stats):
    return sls.StatLine(
        player_id=pid, stats={k: float(v) for k, v in stats.items()}, game_id=game_id
    )


def test_change_after_final_is_a_correction_with_key_level_diff():
    prev = {"1": _line("1", "G1", rec=5, rec_yd=60)}
    cur = {"1": _line("1", "G1", rec=5, rec_yd=62, rec_td=1)}
    report = sls.detect_stat_corrections(prev, cur, {"G1"})
    assert report.unattributable == ()
    (corr,) = report.corrections
    assert corr.kind == sls.CORRECTION_CHANGED
    assert corr.game_id == "G1"
    assert corr.changes == {"rec_yd": (60.0, 62.0), "rec_td": (None, 1.0)}


def test_change_in_a_live_game_is_not_a_correction():
    prev = {"1": _line("1", "G2", rec=1)}
    cur = {"1": _line("1", "G2", rec=2)}
    report = sls.detect_stat_corrections(prev, cur, {"G1"})
    assert report.corrections == () and report.unattributable == ()


def test_unchanged_final_line_reports_nothing():
    prev = {"1": _line("1", "G1", rec=3)}
    assert sls.detect_stat_corrections(prev, dict(prev), {"G1"}).corrections == ()


def test_vanished_player_is_reported_not_zeroed():
    prev = {"1": _line("1", "G1", rec=3)}
    report = sls.detect_stat_corrections(prev, {}, {"G1"})
    (corr,) = report.corrections
    assert corr.kind == sls.CORRECTION_MISSING_IN_CURRENT
    assert corr.changes == {"rec": (3.0, None)}


def test_player_first_seen_after_final():
    cur = {"1": _line("1", "G1", idp_tkl_solo=1)}
    (corr,) = sls.detect_stat_corrections({}, cur, {"G1"}).corrections
    assert corr.kind == sls.CORRECTION_FIRST_SEEN_AFTER_FINAL


def test_v1_lines_need_a_player_game_map_else_unattributable():
    prev = _parse({"6804": {"pass_yd": 100}, "13545": {"xpm": 1}})
    cur = _parse({"6804": {"pass_yd": 104}, "13545": {"xpm": 1}})

    unmapped = sls.detect_stat_corrections(prev, cur, {"202610312"})
    assert unmapped.corrections == ()
    assert unmapped.unattributable == ("6804",)

    mapped = sls.detect_stat_corrections(
        prev, cur, {"202610312"}, player_game_ids={"6804": "202610312"}
    )
    assert mapped.unattributable == ()
    (corr,) = mapped.corrections
    assert corr.player_id == "6804"
    assert corr.changes == {"pass_yd": (100.0, 104.0)}


# ── The historical path still behaves after the fetch refactor ───────


def test_cached_historical_fetch_still_treats_404_as_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("src.nfl_data.cache._default_cache_dir", lambda: tmp_path / "c")

    def fetcher(url):
        raise urllib.error.HTTPError(url, 404, "nf", {}, None)

    assert sleeper_stats._fetch_week_stats(2026, 3, fetcher=fetcher) is None
