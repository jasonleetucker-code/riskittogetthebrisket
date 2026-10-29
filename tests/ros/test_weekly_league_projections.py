"""League-scored weekly projections — the one owner (IDP streaming W1).

No network: every source fetch is injected, the schedule is passed in, and
the scoring card is the committed dynasty_main snapshot.  Fixtures are trimmed
real-shaped rows with fictitious names / ids
(``tests/fixtures/weekly_projections/``).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.league_intel.scorer import score_stat_line
from src.ros import weekly_league_projections as wlp
from src.ros.fptrack_weekly_projections import FPTrackFetchResult
from src.ros.sleeper_weekly_projections import FetchResult

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "weekly_projections"
CARD = json.loads(
    (REPO / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json").read_text(
        encoding="utf-8"
    )
)["scoring_settings"]
OBSERVED = "2026-10-29T09:05:00+00:00"
NOW = datetime(2026, 10, 29, 9, 10, tzinfo=timezone.utc)


def _sleeper_rows() -> list[dict]:
    return json.loads((FIX / "sleeper_week8_sample.json").read_text(encoding="utf-8"))


def _fptrack_payload() -> dict:
    return json.loads((FIX / "fptrack_week8_sample.json").read_text(encoding="utf-8"))


def _schedule(week_teams=(("GB", "CAR"), ("BAL", "BUF"), ("NYJ", "LV"), ("CIN", "TEN"))):
    """nflverse-shaped rows: HOU / NO play week 7 only -> on bye in week 8."""
    rows = [
        {"season": 2026, "week": 8, "game_type": "REG", "home_team": h, "away_team": a}
        for h, a in week_teams
    ]
    rows.append(
        {"season": 2026, "week": 7, "game_type": "REG", "home_team": "HOU", "away_team": "NO"}
    )
    return rows


def _fetch(sleeper=None, fptrack=None):
    sleeper = _sleeper_rows() if sleeper is None else sleeper
    fptrack = _fptrack_payload() if fptrack is None else fptrack
    calls = []

    def fetch(key, season, week):
        calls.append((key, season, week))
        if key == wlp.SLEEPER_SOURCE:
            if sleeper == "down":
                return FetchResult("fetch_failed", season, week, "u", None, reason="boom")
            return FetchResult("ok", season, week, "u", OBSERVED, rows=tuple(sleeper))
        if fptrack == "off":
            return FPTrackFetchResult("feature_disabled", season, week, "u", None, reason="off")
        return FPTrackFetchResult("ok", season, week, "u", OBSERVED, payload=fptrack)

    fetch.calls = calls
    return fetch


def _load(**kw):
    kw.setdefault("fetch", _fetch())
    kw.setdefault("scoring_settings", CARD)
    kw.setdefault("schedule_rows", _schedule())
    kw.setdefault("now", NOW)
    kw.setdefault("use_cache", False)
    return wlp.load_weekly_projections("dynasty_main", 2026, 8, **kw)


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    # FPTrack identity resolves against a directory built from the fixture's
    # own Sleeper rows, never a developer's cached dump.
    from src.identity import directory_cache

    monkeypatch.setattr(directory_cache, "get_default_sleeper_index", lambda *a, **k: None)
    # The fixture carries 3 IDP rows, not the 25-row production floor.
    from src.ros import fptrack_weekly_projections as fpt

    monkeypatch.setattr(fpt, "ZERO_PLACEHOLDER_MIN_ROWS", 3)
    wlp.clear_caches()
    yield
    wlp.clear_caches()


def test_projected_points_are_the_exact_league_score():
    s = _load()
    p = s.get("90001")
    assert p.state == wlp.STATE_PROJECTED and p.position == "LB"
    stats = {
        k: float(v) for k, v in _sleeper_rows()[0]["stats"].items() if isinstance(v, (int, float))
    }
    assert p.weekly_points == pytest.approx(score_stat_line(stats, CARD).total_points)
    assert p.combine_method == wlp.COMBINE_PASSTHROUGH
    assert [c.source_key for c in p.sources] == [wlp.SLEEPER_SOURCE]
    assert p.sources[0].family == "rotowire" and p.sources[0].provider_model == "rotowire"
    assert p.family_count == 1 and p.disagreement_spread is None


def test_fptrack_never_votes_beside_rotowire():
    """Alpha is projected by both; FPTrack declares rotowire ancestry."""
    p = _load().get("90001")
    assert p.excluded_sources == (wlp.FPTRACK_SOURCE,)
    assert len(p.sources) == 1


def test_fptrack_fills_a_player_rotowire_did_not_project():
    """Golf has a Sleeper placeholder only; FPTrack (resolved by exact name +
    team) prices him as a single-family passthrough."""
    p = _load().get("90007")
    assert p.state == wlp.STATE_PROJECTED
    assert [c.source_key for c in p.sources] == [wlp.FPTRACK_SOURCE]
    assert p.combine_method == wlp.COMBINE_PASSTHROUGH
    # tacklesForLoss is a zero placeholder in the fixture -> UNCOVERED, never 0.
    assert "idp_tkl_loss" in p.coverage.uncovered_keys
    assert "idp_tkl_loss" not in p.coverage.covered_keys


def test_without_fptrack_a_placeholder_is_unprojected_not_zero():
    p = _load(fetch=_fetch(fptrack="off")).get("90007")
    assert p.state == wlp.STATE_UNPROJECTED
    assert p.weekly_points is None
    assert p.reason == "provider_published_no_projection"


def test_bye_is_zero_only_when_the_schedule_proves_it():
    s = _load()
    p = s.get("90006")
    assert (p.state, p.weekly_points, p.reason) == (wlp.STATE_BYE, 0.0, "bye")
    assert s.schedule_state == "ok" and "HOU" in s.bye_teams


def test_unknown_schedule_never_produces_a_bye():
    s = _load(schedule_rows=[])
    p = s.get("90006")
    assert s.schedule_state == "unavailable"
    assert p.state == wlp.STATE_UNPROJECTED and p.weekly_points is None
    assert "schedule_unavailable" in p.reason


def test_injured_out_only_for_the_stated_current_week():
    rows = _sleeper_rows()
    rows[7]["team"] = "CAR"  # off the bye team so the injury branch is reached
    rows[7]["player"]["team"] = "CAR"
    s = _load(fetch=_fetch(sleeper=rows), current_week=8)
    p = s.get("90008")
    assert (p.state, p.weekly_points, p.reason) == (
        wlp.STATE_INJURED_OUT,
        0.0,
        "host_injury_status:Out",
    )
    # A future week (or an unstated current week) never inherits today's tag.
    p2 = _load(fetch=_fetch(sleeper=rows), current_week=None).get("90008")
    assert p2.state == wlp.STATE_UNPROJECTED and p2.weekly_points is None


def test_no_nfl_team_is_unprojected():
    p = _load().get("90009")
    assert (p.state, p.weekly_points, p.reason) == (
        wlp.STATE_UNPROJECTED,
        None,
        "no_nfl_team_on_file",
    )


def test_all_sources_down_is_unprojected_with_reasons():
    s = _load(fetch=_fetch(sleeper="down", fptrack="off"))
    assert all(st.state == "unavailable" for st in s.source_states)
    # Sleeper is down, so its universe is empty: no player is invented.
    assert s.players == {}


def test_unpublished_week_reads_week_not_published():
    from src.ros.sleeper_weekly_projections import row_refusal_reason

    rows = [r for r in _sleeper_rows() if row_refusal_reason(r, season=2026, week=8)]
    empty = dict(_fptrack_payload(), players=[])
    s = _load(fetch=_fetch(sleeper=rows, fptrack=empty))
    reasons = {p.reason for p in s.players.values() if p.state == wlp.STATE_UNPROJECTED}
    assert any(r.startswith("week_not_published") for r in reasons)


def test_coverage_names_uncovered_league_keys():
    p = _load().get("90001")
    cov = p.coverage
    assert set(cov.covered_keys) <= set(cov.league_paid_keys)
    assert set(cov.uncovered_keys) <= set(cov.league_paid_keys)
    assert not set(cov.covered_keys) & set(cov.uncovered_keys)
    # dynasty_main pays blocked kicks; nobody projects them for an LB.
    assert "idp_blk_kick" in cov.uncovered_keys
    assert 0.0 < cov.coverage_share < 1.0


def test_positions_filter():
    s = _load(positions=("LB",))
    assert {p.position for p in s.players.values()} == {"LB"}


def test_two_independent_families_use_the_ensemble(monkeypatch):
    """With the ancestry overlap removed, two families -> equal_family_mean."""
    monkeypatch.setattr(wlp.census, "ancestry_overlaps", lambda keys: [])
    p = _load().get("90001")
    assert p.combine_method == wlp.COMBINE_ENSEMBLE and p.family_count == 2
    pts = [c.weekly_points + c.imputed_points for c in p.sources]
    assert p.weekly_points == pytest.approx(sum(pts) / 2)
    assert p.disagreement_spread == pytest.approx(max(pts) - min(pts))


def test_cache_is_keyed_by_fingerprint_not_label():
    fetch = _fetch()
    a = _load(fetch=fetch, use_cache=True)
    b = _load(fetch=fetch, use_cache=True)
    assert a is b and a.cache_key
    other = dict(CARD, idp_tkl_solo=2.0)
    c = _load(fetch=fetch, scoring_settings=other, use_cache=True)
    assert c is not a and c.cache_key != a.cache_key
    assert c.scoring_fingerprint != a.scoring_fingerprint


def test_cache_key_changes_when_a_source_refetches():
    a = _load(use_cache=True)
    later = _fetch()

    def refetched(key, season, week):
        r = later(key, season, week)
        if key == wlp.SLEEPER_SOURCE:
            return FetchResult("ok", season, week, "u", "2026-10-29T12:00:00+00:00", rows=r.rows)
        return r

    b = _load(fetch=refetched, use_cache=True)
    assert b.cache_key != a.cache_key


def test_missing_scoring_card_refuses(monkeypatch):
    s = wlp.load_weekly_projections(
        "no_such_league", 2026, 8, fetch=_fetch(), schedule_rows=_schedule(), now=NOW
    )
    assert s.refusal and s.refusal.startswith("unknown_league") and s.players == {}


def test_to_dict_is_camel_case_and_json_safe():
    d = _load().to_dict()
    json.dumps(d)
    p = d["players"]["90001"]
    for key in ("playerId", "weeklyPoints", "combineMethod", "coverage", "sources"):
        assert key in p
    assert set(p["coverage"]) == {"leaguePaidKeys", "coveredKeys", "uncoveredKeys", "coverageShare"}
    assert set(p["sources"][0]) >= {
        "sourceKey",
        "family",
        "providerModel",
        "fetchedAt",
        "updatedAt",
        "weeklyPoints",
    }


def test_default_fetch_respects_the_ttl(monkeypatch):
    calls = []

    def fake(key, season, week):
        calls.append(key)
        return FetchResult("ok", season, week, "u", OBSERVED, rows=tuple(_sleeper_rows()))

    monkeypatch.setattr(wlp, "_default_fetch", fake)
    t0 = NOW.timestamp()
    wlp._cached_fetch(wlp.SLEEPER_SOURCE, 2026, 8, t0)
    wlp._cached_fetch(wlp.SLEEPER_SOURCE, 2026, 8, t0 + 60)
    assert calls == [wlp.SLEEPER_SOURCE]
    wlp._cached_fetch(wlp.SLEEPER_SOURCE, 2026, 8, t0 + wlp.FETCH_TTL_SECONDS + 1)
    assert calls == [wlp.SLEEPER_SOURCE, wlp.SLEEPER_SOURCE]


def test_seasonal_lane_never_touches_dynasty_value():
    src = (REPO / "src" / "ros" / "weekly_league_projections.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "rankDerivedValue =" not in code and '["rankDerivedValue"]' not in code
