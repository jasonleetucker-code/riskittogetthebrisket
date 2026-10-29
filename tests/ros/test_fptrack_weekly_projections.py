"""FPTrack weekly projections — fixture replay (no network).

The fixture is a trimmed copy of the 2026-10-29 week-8 catalog with
fictitious names / ids (``tests/fixtures/weekly_projections/``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.identity.resolution import build_sleeper_index
from src.league_intel.scorer import score_stat_line
from src.ros import fptrack_weekly_projections as fpt
from src.ros import projection_source_census as census

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "weekly_projections" / "fptrack_week8_sample.json"
CARD = json.loads(
    (REPO / "config" / "league_intel" / "sleeper_league_snapshot_2026-07-26.json").read_text(
        encoding="utf-8"
    )
)["scoring_settings"]
OBSERVED = "2026-10-29T09:05:00+00:00"

DIRECTORY = {
    "90001": {"first_name": "Alpha", "last_name": "Linebacker", "position": "LB", "team": "CAR",
              "active": True},
    "90007": {"first_name": "Golf", "last_name": "Backer", "position": "LB", "team": "BUF",
              "active": True},
    "90005": {"first_name": "Echo", "last_name": "Receiver", "position": "WR", "team": "GB",
              "active": True},
}  # fmt: skip


def _payload() -> dict:
    return json.loads(FIX.read_text(encoding="utf-8"))


def _build(payload=None, directory=None, **kw):
    index = build_sleeper_index(DIRECTORY if directory is None else directory)
    return fpt.build_weekly_observations(
        _payload() if payload is None else payload,
        season=2026,
        week=8,
        observed_at=OBSERVED,
        scoring_settings=CARD,
        resolve_player=fpt.exact_identity_resolver(index),
        **kw,
    )


def test_census_entry_is_a_rotowire_constituent_and_flag_off():
    entry = census.get_source(fpt.CENSUS_SOURCE_KEY)
    assert entry["implementationStatus"] == "IMPLEMENTED_FLAG_OFF"
    assert entry["featureFlag"] == fpt.FEATURE_FLAG
    assert "rotowire" in entry["modelAncestry"]["constituentFamilies"]
    overlaps = census.ancestry_overlaps([fpt.CENSUS_SOURCE_KEY, "sleeperWeeklyProjections"])
    assert overlaps and "rotowire" in overlaps[0][2]


def test_maps_solo_and_assisted_tackles_and_rescores_exactly():
    mapped, _parsed = _build(zero_placeholder_min_rows=3)
    obs = mapped.batch.by_player_id()["90001"]
    raw = next(p for p in _payload()["players"] if p["fullName"] == "Alpha Linebacker")["stats"]
    assert obs.stat_line["idp_tkl_solo"] == raw["tackles"]
    assert obs.stat_line["idp_tkl_ast"] == raw["assists"]
    assert obs.stat_line["idp_tkl"] == pytest.approx(raw["tackles"] + raw["assists"])
    assert obs.league_scored_points == pytest.approx(
        score_stat_line(dict(obs.stat_line), CARD).total_points
    )
    assert obs.provider_updated_at is None  # epoch asOf is not a provider stamp


def test_all_zero_field_is_a_placeholder_never_a_zero():
    mapped, parsed = _build(zero_placeholder_min_rows=3)
    assert "tacklesForLoss" in parsed.placeholder_zero_fields["DEF"]
    obs = mapped.batch.by_player_id()["90001"]
    assert "idp_tkl_loss" not in obs.stat_line
    assert "idp_tkl_loss" in obs.uncovered_scoring_keys


def test_below_the_population_floor_a_zero_is_kept():
    mapped, parsed = _build(zero_placeholder_min_rows=100)
    assert parsed.placeholder_zero_fields == {}
    assert mapped.batch.by_player_id()["90001"].stat_line["idp_tkl_loss"] == 0.0


def test_null_fumble_recoveries_are_uncovered():
    mapped, _ = _build(zero_placeholder_min_rows=3)
    obs = mapped.batch.by_player_id()["90001"]
    assert "idp_fum_rec" not in obs.stat_line
    assert "idp_fum_rec" in obs.uncovered_scoring_keys


def test_unresolved_and_team_units_are_refused_never_guessed():
    mapped, _ = _build()
    assert mapped.batch.refused.get("team_unit") == 1
    assert mapped.batch.refused.get("unresolved_identity") == 1
    assert [r.name for r in mapped.unresolved_players] == ["Juliet Unknown"]


def test_team_must_corroborate_the_exact_name():
    directory = dict(DIRECTORY)
    directory["90001"] = dict(directory["90001"], team="DAL")
    mapped, _ = _build(directory=directory)
    assert "90001" not in mapped.batch.by_player_id()


def test_identity_collision_refuses_both_rows():
    payload = _payload()
    twin = json.loads(json.dumps(payload["players"][0]))
    twin["fptrackId"] = 99999
    payload["players"].append(twin)
    mapped, _ = _build(payload=payload)
    assert "90001" not in mapped.batch.by_player_id()


def test_unpublished_week_has_no_observations():
    payload = dict(_payload(), players=[])
    mapped, parsed = _build(payload=payload)
    assert parsed.rows == () and mapped.batch.observations == ()


def test_payload_week_must_match_the_request():
    payload = dict(_payload(), week=7)
    mapped, _ = _build(payload=payload)
    assert mapped.batch.observations == ()
    assert mapped.batch.refused.get("week_mismatch", 0) >= 3


def test_no_unmapped_numeric_fields_on_the_capture():
    mapped, _ = _build()
    assert dict(mapped.unmapped_provider_fields) == {}


def test_fetch_makes_no_call_while_the_flag_is_off(monkeypatch):
    from src.api import feature_flags

    monkeypatch.delenv("RISKIT_FEATURE_FPTRACK_WEEKLY_PROJECTIONS", raising=False)
    feature_flags.reload()

    def boom(url, timeout):  # pragma: no cover — must not be called
        raise AssertionError("network call with the flag off")

    r = fpt.fetch_weekly_projection_payload(2026, 8, http_get=boom)
    assert r.status == "feature_disabled" and r.payload is None


def test_fetch_parses_when_on(monkeypatch):
    from datetime import datetime, timezone

    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_FPTRACK_WEEKLY_PROJECTIONS", "1")
    feature_flags.reload()
    body = FIX.read_bytes()
    seen = []

    def get(url, timeout):
        seen.append(url)
        return body

    r = fpt.fetch_weekly_projection_payload(
        2026, 8, http_get=get, now=lambda: datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
    )
    bad = fpt.fetch_weekly_projection_payload(2026, 8, http_get=lambda u, t: b"[]")
    monkeypatch.delenv("RISKIT_FEATURE_FPTRACK_WEEKLY_PROJECTIONS")
    feature_flags.reload()
    assert r.ok and r.payload["week"] == 8 and "week=8" in seen[0]
    assert r.observed_at == "2026-10-29T09:00:00+00:00"
    assert bad.status == "bad_payload" and bad.payload is None
