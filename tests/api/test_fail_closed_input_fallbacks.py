"""Fail-closed fallbacks for the two board-input loaders (lane C2, 2026-10-16).

* ``_seasonally_inactive_sources`` — an unreadable / malformed seasonal policy
  used to log a warning and apply NO exclusions, so the graduated class's stale
  48-row ``flockFantasySfRookies`` board would vote again on nothing but a
  config typo.  It now falls back to the RECORDED seasonal states (the
  fetcher's own transition log, read as of the board's time), stamps
  ``sourceSeasonalState.policyError`` and the validator reports
  ``seasonal_policy_unreadable`` + ``degraded``.
* ``_load_source_weighting`` — a missing dataset-state directory silently gave
  every source full base authority.  The weighting is unchanged (``{}`` — the
  documented replay posture), but it is now logged loudly and stamped
  ``sourceWeighting.unavailableReason`` + ``degraded``.

Healthy paths stamp nothing new (byte-identical); proven on the real board by
``scripts/board_diff.py --expect-no-value-change`` in the lane report.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

import src.api.data_contract as dc
from src.sources import seasonal_policy as sp

KEY = "flockFantasySfRookies"
AS_OF = datetime(2026, 10, 3, tzinfo=timezone.utc)


def _state_dir(root: Path) -> Path:
    d = root / "data" / "scrape_state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _record_inactive(state_dir: Path, at: datetime) -> None:
    policy = sp.load_policies()[KEY]
    verdict = sp.classify_empty_response(
        policy, {"format": "PROSPECTS_SF", "year": 2026, "data": []}, at
    )
    sp.record_inactive_observation(state_dir, policy, verdict, at)


@pytest.fixture
def broken_policy(tmp_path, monkeypatch):
    """Point the policy owner at a malformed (or unreadable) declaration."""

    def _break(kind: str) -> None:
        cfg = tmp_path / "policy_cfg"
        cfg.mkdir(exist_ok=True)
        if kind == "malformed":
            path = cfg / "seasonal_policy_v1.json"
            path.write_text('{"sources": {"flockFantasySfRookies": ', encoding="utf-8")
        elif kind == "wrong_shape":
            path = cfg / "seasonal_policy_v1.json"
            path.write_text('{"sources": []}', encoding="utf-8")
        else:  # unreadable: a directory where the file should be
            path = cfg / "seasonal_policy_dir.json"
            path.mkdir(exist_ok=True)
        monkeypatch.setattr(sp, "CONFIG_PATH", path)

    return _break


# ── seasonal policy ───────────────────────────────────────────────────────


def test_healthy_policy_is_unchanged(tmp_path):
    _record_inactive(_state_dir(tmp_path), datetime(2026, 10, 2, tzinfo=timezone.utc))
    inactive, error = dc._seasonal_inactive_resolution(AS_OF, tmp_path)
    assert error is None
    assert set(inactive) == {KEY}
    assert "basis" not in inactive[KEY]


@pytest.mark.parametrize("kind", ["malformed", "wrong_shape", "unreadable"])
def test_unreadable_policy_fails_closed_to_the_recorded_state(tmp_path, broken_policy, kind):
    _record_inactive(_state_dir(tmp_path), datetime(2026, 10, 2, tzinfo=timezone.utc))
    broken_policy(kind)
    with pytest.raises(sp.SeasonalPolicyError):
        sp.load_policies()
    got = dc._seasonally_inactive_sources(AS_OF, tmp_path)
    assert set(got) == {KEY}, "a broken policy must not let the stale seasonal board vote"
    assert got[KEY]["basis"] == dc.SEASONAL_BASIS_RECORDED_STATE_POLICY_UNREADABLE
    assert got[KEY]["policyId"]
    _inactive, error = dc._seasonal_inactive_resolution(AS_OF, tmp_path)
    assert error


def test_fallback_still_reads_the_state_in_force_at_the_boards_time(tmp_path, broken_policy):
    _record_inactive(_state_dir(tmp_path), datetime(2026, 10, 2, tzinfo=timezone.utc))
    broken_policy("malformed")
    assert (
        dc._seasonally_inactive_sources(datetime(2026, 9, 1, tzinfo=timezone.utc), tmp_path) == {}
    )


def test_fallback_never_switches_off_an_undeclared_source(tmp_path, broken_policy):
    """A state file not written under a declaration (no ``policyId`` /
    ``sourceKey``) switches nothing off, broken policy or not."""
    state_dir = _state_dir(tmp_path)
    (state_dir / "fantasyCalc_seasonal.json").write_text(
        '{"state":"seasonally_inactive","transitions":'
        '[{"state":"seasonally_inactive","at":"2026-10-01T00:00:00Z"}]}',
        encoding="utf-8",
    )
    broken_policy("malformed")
    assert dc._seasonally_inactive_sources(AS_OF, tmp_path) == {}


def test_no_board_time_still_gets_no_exclusions(tmp_path, broken_policy):
    _record_inactive(_state_dir(tmp_path), datetime(2026, 10, 2, tzinfo=timezone.utc))
    broken_policy("malformed")
    assert dc._seasonal_inactive_resolution(None, tmp_path) == ({}, None)


# ── source weighting ──────────────────────────────────────────────────────


def test_missing_state_dir_is_loud_and_named(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger=dc.__name__):
        weighting, reason = dc._source_weighting_resolution(AS_OF, tmp_path)
    assert weighting == {}, "base weights — the documented replay posture, unchanged"
    assert reason == dc.SOURCE_WEIGHTING_UNAVAILABLE_STATE_DIR_MISSING
    assert any("source weighting UNAVAILABLE" in r.getMessage() for r in caplog.records)
    assert dc._load_source_weighting(AS_OF, tmp_path) == {}


def test_healthy_weighting_names_no_reason():
    weighting, reason = dc._source_weighting_resolution(AS_OF)
    assert reason is None and weighting
    assert dc._load_source_weighting(AS_OF) is weighting  # same memo entry


def test_no_board_time_is_not_reported_as_missing_state(tmp_path):
    assert dc._source_weighting_resolution(None, tmp_path) == ({}, None)


# ── contract + validator ──────────────────────────────────────────────────


def _raw(scrape_ts: str | None = "2026-10-03T00:00:00Z") -> dict:
    players = {}
    market = 9000
    for i in range(30):
        sites = {"idpTradeCalc": market, "ktcCrowdSfTep": market, "fantasyCalc": market}
        players[f"Vet {i:03d}"] = {
            "_canonicalSiteValues": dict(sites),
            "position": "WR",
            "age": 25,
            **sites,
        }
        market -= 50
    raw = {
        "version": "fallback-fixture",
        "date": "2026-10-03",
        "settings": {},
        "sites": {},
        "maxValues": {},
        "players": players,
    }
    if scrape_ts:
        raw["scrapeTimestamp"] = scrape_ts
    return raw


def test_contract_stamps_and_validator_degrades_on_both_fallbacks(tmp_path, broken_policy):
    # No data/scrape_state at all → weighting unavailable; and a broken policy.
    broken_policy("malformed")
    contract = dc.build_api_data_contract(_raw(), csv_root=tmp_path)
    assert contract["sourceWeighting"]["unavailableReason"] == "state_dir_missing"
    assert contract["sourceSeasonalState"]["policyError"]
    report = dc.validate_api_data_contract(contract)
    warnings = report.get("warnings") or []
    assert "source_weighting_unavailable:state_dir_missing" in warnings
    assert "seasonal_policy_unreadable" in warnings
    assert report.get("status") == "degraded"
    assert not report.get("structuralErrors")


def test_contract_with_a_broken_policy_keeps_the_seasonal_source_out(tmp_path, broken_policy):
    _record_inactive(_state_dir(tmp_path), datetime(2026, 10, 2, tzinfo=timezone.utc))
    broken_policy("malformed")
    contract = dc.build_api_data_contract(_raw(), csv_root=tmp_path)
    block = contract["sourceSeasonalState"]
    assert set(block["inactive"]) == {KEY}
    assert block["basis"] == dc.SEASONAL_BASIS_RECORDED_STATE_POLICY_UNREADABLE
    for row in contract["playersArray"]:
        assert KEY not in (row.get("sourceRankMeta") or {})


def test_healthy_inputs_stamp_nothing_new(tmp_path):
    _state_dir(tmp_path)
    contract = dc.build_api_data_contract(_raw(), csv_root=tmp_path)
    assert "unavailableReason" not in (contract.get("sourceWeighting") or {})
    assert "policyError" not in contract["sourceSeasonalState"]
    assert "basis" not in contract["sourceSeasonalState"]
    warnings = dc.validate_api_data_contract(contract).get("warnings") or []
    assert not any(
        w.startswith(("source_weighting_unavailable", "seasonal_policy_unreadable"))
        for w in warnings
    )
