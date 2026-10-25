"""Tests for ESPN depth chart + usage cross-check gate."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from src.api import feature_flags
from src.nfl_data import depth_charts as dc
from src.utils import circuit_breaker


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _sample_depth_payload():
    return {
        "team": {"abbreviation": "BUF"},
        "athletes": [
            {
                "position": {"abbreviation": "QB"},
                "items": [
                    {"athlete": {"id": "3918298", "displayName": "Josh Allen"}},
                    {"athlete": {"id": "5555", "displayName": "Mitch Trubisky"}},
                ],
            },
            {
                "position": {"abbreviation": "RB"},
                "items": [
                    {"athlete": {"id": "4017", "displayName": "James Cook"}},
                    {"athlete": {"id": "7777", "displayName": "Ty Johnson"}},
                    {"athlete": {"id": "9999", "displayName": "Backup"}},
                ],
            },
        ],
    }


def test_flag_off_returns_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_DEPTH_CHART_VALIDATION", "0")
    feature_flags.reload()

    def opener(req, timeout=None):
        return io.BytesIO(b"{}")

    out = dc.fetch_team_depth_chart("2", _url_opener=opener, cache_dir=tmp_path)
    assert out == []


def test_parse_depth_payload_shapes(monkeypatch, tmp_path):
    monkeypatch.setenv("RISKIT_FEATURE_DEPTH_CHART_VALIDATION", "1")
    feature_flags.reload()

    def opener(req, timeout=None):
        return io.BytesIO(json.dumps(_sample_depth_payload()).encode("utf-8"))

    out = dc.fetch_team_depth_chart("2", _url_opener=opener, cache_dir=tmp_path)
    # 2 QBs + 3 RBs = 5 entries
    assert len(out) == 5
    qb1 = [e for e in out if e.position == "QB" and e.slot == 1][0]
    assert qb1.full_name == "Josh Allen"
    assert qb1.team_abbrev == "BUF"


def test_detect_slot_changes_promotion():
    prior = [
        dc.DepthChartEntry("BUF", "RB", 1, "A", "Starter A"),
        dc.DepthChartEntry("BUF", "RB", 2, "B", "Backup B"),
    ]
    current = [
        dc.DepthChartEntry("BUF", "RB", 1, "B", "Backup B"),
        dc.DepthChartEntry("BUF", "RB", 2, "A", "Starter A"),
    ]
    changes = dc.detect_slot_changes(prior, current)
    # Two entries changed: A demoted, B promoted.
    by_id = {c["espnAthleteId"]: c for c in changes}
    assert by_id["A"]["direction"] == "demoted"
    assert by_id["B"]["direction"] == "promoted"


def test_detect_slot_changes_debut():
    prior = []
    current = [dc.DepthChartEntry("BUF", "WR", 1, "N", "New")]
    changes = dc.detect_slot_changes(prior, current)
    assert changes[0]["direction"] == "debut"


def test_detect_slot_changes_no_change_emits_nothing():
    e = dc.DepthChartEntry("BUF", "QB", 1, "A", "A")
    changes = dc.detect_slot_changes([e], [e])
    assert changes == []


def test_usage_confirms_promotion_with_snap_delta():
    change = {"direction": "promoted", "espnAthleteId": "A", "fullName": "A"}
    # +8pp snap delta — confirms promotion.
    assert dc.usage_confirms_slot_change(change, 0.08) is True


def test_usage_rejects_promotion_with_snap_drop():
    """Direction mismatch — promoted player with declining snaps
    is not confirmed (could be a stat-sheet artifact)."""
    change = {"direction": "promoted"}
    assert dc.usage_confirms_slot_change(change, -0.08) is False


def test_usage_rejects_small_delta():
    """<5pp change is noise."""
    change = {"direction": "promoted"}
    assert dc.usage_confirms_slot_change(change, 0.02) is False


def test_usage_confirms_demotion_with_snap_drop():
    change = {"direction": "demoted"}
    assert dc.usage_confirms_slot_change(change, -0.10) is True


def test_debut_is_not_a_confirmed_signal():
    """A debut slot isn't a 'change' in the promoted/demoted sense —
    return False so we don't fire extra alerts on rookie debuts."""
    change = {"direction": "debut"}
    assert dc.usage_confirms_slot_change(change, 0.10) is False


def test_nfl_team_ids_covers_32_teams():
    assert len(dc.NFL_TEAM_IDS) == 32


# ── 2026-10-25 repair: the live endpoint and its formation shape ─────────────
#
# ``dynasty-depth-charts-refresh`` logged ``0/32 OK`` on every run in its
# retained journal: the singular ``/depthchart`` path answers 200 with ``{}``.
# The fixture is a trimmed real ``/depthcharts`` response (BUF, 2026-10-25;
# ids, names and position abbreviations only).

_FIXTURE = Path(__file__).parent / "fixtures" / "espn_depthcharts_buf_2026-10-25.json"


@pytest.fixture
def _flag_on(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_DEPTH_CHART_VALIDATION", "1")
    feature_flags.reload()
    circuit_breaker.reset_all_for_tests()
    yield
    circuit_breaker.reset_all_for_tests()


def _opener_for(payload, calls=None):
    def opener(req, timeout=None):
        if calls is not None:
            calls.append(req.full_url)
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


def _fixture_payload():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_endpoint_is_the_plural_depthcharts_path(_flag_on, tmp_path):
    calls: list[str] = []
    dc.fetch_team_depth_chart(
        "2", _url_opener=_opener_for(_fixture_payload(), calls), cache_dir=tmp_path
    )
    assert calls == [
        "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/2/depthcharts"
    ]


def test_real_formation_payload_parses(_flag_on, tmp_path):
    out = dc.fetch_team_depth_chart(
        "2", _url_opener=_opener_for(_fixture_payload()), cache_dir=tmp_path
    )
    assert out, "the live shape must yield entries"
    assert {e.team_abbrev for e in out} == {"BUF"}
    by = {(e.position, e.slot): e.full_name for e in out if e.position != "WR"}
    assert by[("QB", 1)] == "Josh Allen"
    assert by[("QB", 2)] == "Kyle Allen"
    assert by[("RB", 1)] == "James Cook III"
    assert by[("PK", 1)] == "Tyler Bass"
    # wr1 / wr2 / wr3 are three receiver slots, each with its own starter.
    wr_starters = {e.full_name for e in out if e.position == "WR" and e.slot == 1}
    assert wr_starters == {"DJ Moore", "Khalil Shakir", "Keon Coleman"}
    # Secondary special-teams duties are not depth at a position.
    assert not {"PR", "KR", "H", "LS"} & {e.position for e in out}
    # One entry per (position, athlete).
    keys = [(e.position, e.espn_athlete_id) for e in out]
    assert len(keys) == len(set(keys))


def test_athlete_listed_twice_at_one_position_keeps_best_slot():
    def grp(*ids):
        return {
            "position": {"abbreviation": "CB"},
            "athletes": [{"id": i, "displayName": i} for i in ids],
        }

    payload = {
        "team": {"abbreviation": "BUF"},
        "status": "success",
        "depthchart": [
            {"name": "Base 4-3 D", "positions": {"lcb": grp("1", "2")}},
            {"name": "Nickel", "positions": {"rcb": grp("2")}},
        ],
    }
    out = dc._parse_depth_payload(payload)
    assert sorted((e.espn_athlete_id, e.slot) for e in out) == [("1", 1), ("2", 1)]


@pytest.mark.parametrize(
    "payload",
    [
        {},  # what the retired singular endpoint returns for every team
        {"status": "error", "depthchart": []},
        {"status": "success", "depthchart": []},
    ],
)
def test_an_empty_answer_is_a_failure_and_is_never_cached(_flag_on, tmp_path, payload):
    out = dc.fetch_team_depth_chart("2", _url_opener=_opener_for(payload), cache_dir=tmp_path)
    assert out == []
    # Not cached: the next call asks ESPN again and gets the real chart.
    calls: list[str] = []
    out = dc.fetch_team_depth_chart(
        "2", _url_opener=_opener_for(_fixture_payload(), calls), cache_dir=tmp_path
    )
    assert calls and out


def test_a_non_success_status_is_not_parsed_even_with_rows(_flag_on, tmp_path):
    payload = _fixture_payload()
    payload["status"] = "error"
    out = dc.fetch_team_depth_chart("2", _url_opener=_opener_for(payload), cache_dir=tmp_path)
    assert out == []


def test_refresh_keeps_last_good_chart_for_a_team_that_failed():
    from scripts import refresh_depth_charts as rdc

    prior = [
        dc.DepthChartEntry("BUF", "QB", 1, "A", "A"),
        dc.DepthChartEntry("MIA", "QB", 1, "M", "M"),
    ]
    current = [dc.DepthChartEntry("BUF", "QB", 1, "B", "B")]
    # BUF is fresh (its prior rows are not carried); MIA failed this run and
    # keeps its last good rows rather than vanishing from the next diff's base.
    assert rdc._snapshot_to_keep(prior, current) == [current[0], prior[1]]
