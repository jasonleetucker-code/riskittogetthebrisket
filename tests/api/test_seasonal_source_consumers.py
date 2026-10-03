"""Consumers of the declared seasonal window (owner decision 2026-10-03).

* the freshness watchdog — a re-verified seasonally inactive source is
  reported, not failed, so ``scheduled-refresh.yml`` goes green; one whose
  re-verification lapsed is classified exactly as before;
* the alert engine — the same rule, so the site does not page on it;
* the canonical pipeline — an inactive source has ZERO current voting
  authority: absent from every row's vote, never a zero value, and a row it
  alone covered is unpriced rather than priced at 0.

Synthetic boards and temporary state directories only — nothing here reads
the live board.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import scripts.watchdog_freshness as wd
import src.api.data_contract as dc
from src.api import source_health_alerts as sha
from src.sources import seasonal_policy as sp

KEY = "flockFantasySfRookies"


def _record_inactive(state_dir: Path, at: datetime) -> None:
    policy = sp.load_policies()[KEY]
    verdict = sp.classify_empty_response(
        policy, {"format": "PROSPECTS_SF", "year": 2026, "data": []}, at
    )
    sp.record_inactive_observation(state_dir, policy, verdict, at)


# ── Freshness watchdog ─────────────────────────────────────────────────
def _freshness(age_flock: float) -> dict[str, dict]:
    return {
        KEY: {"lastFetched": "2026-09-30T00:00:00+00:00", "ageHours": age_flock},
        "fantasyCalc": {"lastFetched": "2026-10-02T10:00:00+00:00", "ageHours": 2.0},
    }


class TestWatchdog:
    def test_reverified_inactive_source_is_not_stale(self, tmp_path):
        now = datetime(2026, 10, 3, 0, tzinfo=timezone.utc)
        _record_inactive(tmp_path, datetime(2026, 10, 2, 22, tzinfo=timezone.utc))
        thresholds = {"flockFantasy": 24, "fantasyCalc": 24}
        remaining, verified, lapsed = wd.split_seasonally_inactive(
            _freshness(72.0), thresholds, state_dir=tmp_path, now=now
        )
        assert set(verified) == {KEY} and lapsed == {}
        hard, soft, fresh = wd.classify_freshness(remaining, thresholds, set())
        assert hard == [] and soft == []
        assert [f[0] for f in fresh] == ["fantasyCalc"]

    def test_lapsed_reverification_still_hard_fails(self, tmp_path):
        """A fetcher that stopped answering is not excused by the window."""
        _record_inactive(tmp_path, datetime(2026, 10, 2, tzinfo=timezone.utc))
        now = datetime(2026, 10, 4, tzinfo=timezone.utc)
        thresholds = {"flockFantasy": 24}
        remaining, verified, lapsed = wd.split_seasonally_inactive(
            _freshness(96.0), thresholds, state_dir=tmp_path, now=now
        )
        assert verified == {} and set(lapsed) == {KEY}
        hard, _soft, _fresh = wd.classify_freshness(remaining, thresholds, set())
        assert [h[0] for h in hard] == [KEY]

    def test_no_state_is_the_old_behaviour(self, tmp_path):
        thresholds = {"flockFantasy": 24}
        remaining, verified, _lapsed = wd.split_seasonally_inactive(
            _freshness(72.0), thresholds, state_dir=tmp_path
        )
        assert verified == {} and KEY in remaining

    def test_main_exits_green_for_a_reverified_inactive_source(self, tmp_path, monkeypatch, capsys):
        state_dir = tmp_path / "data" / "scrape_state"
        state_dir.mkdir(parents=True)
        _record_inactive(state_dir, datetime.now(timezone.utc))
        monkeypatch.setattr(wd, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(wd, "_read_freshness", lambda: _freshness(72.0))
        monkeypatch.setattr(wd, "unmeasurable_sources", lambda: [])
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(tmp_path / "summary.md"))
        assert wd.main() == 0
        out = capsys.readouterr().out
        assert "1 seasonally inactive" in out
        assert "Seasonally inactive" in (tmp_path / "summary.md").read_text(encoding="utf-8")

    def test_main_still_fails_when_inactivity_was_never_recorded(
        self, tmp_path, monkeypatch, capsys
    ):
        (tmp_path / "data" / "scrape_state").mkdir(parents=True)
        monkeypatch.setattr(wd, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(wd, "_read_freshness", lambda: _freshness(72.0))
        monkeypatch.setattr(wd, "unmeasurable_sources", lambda: [])
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        assert wd.main() == 1


# ── Alert engine ───────────────────────────────────────────────────────
def test_alert_engine_skips_only_named_inactive_sources():
    now = time.time()
    health = {"sources": {KEY: {"lastFetched": "2026-09-30T00:00:00+00:00"}}}
    stale = sha.detect_stale_sources(health, thresholds={"flockFantasy": 24}, now_epoch=now)
    assert [a.source for a in stale] == [KEY]
    muted = sha.detect_stale_sources(
        health, thresholds={"flockFantasy": 24}, now_epoch=now, seasonally_inactive={KEY}
    )
    assert muted == []


# ── Canonical pipeline: zero current voting authority ─────────────────
def _row(name: str, pos: str, **sites) -> dict:
    return {
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "assetClass": "offense",
        "values": {"overall": 0, "rawComposite": 0, "finalAdjusted": 0, "displayValue": None},
        "canonicalSiteValues": dict(sites),
        "sourceCount": len(sites),
        "rookie": KEY in sites,
    }


def _board(inactive: set[str]) -> dict[str, dict]:
    rows = [
        _row("Vet A", "QB", ktcCrowdSfTep=9999, flockFantasySf=9999),
        _row("Vet B", "WR", ktcCrowdSfTep=8000, flockFantasySf=9998),
        _row("Rook A", "WR", ktcCrowdSfTep=6000, flockFantasySfRookies=9999),
        _row("Rook B", "RB", ktcCrowdSfTep=5500, flockFantasySfRookies=9998),
        _row("Rook C", "TE", ktcCrowdSfTep=5000, flockFantasySfRookies=9997),
        _row("Rook Only", "TE", flockFantasySfRookies=9996),
    ]
    dc._compute_unified_rankings(rows, {}, seasonally_inactive_sources=inactive)
    return {r["canonicalName"]: r for r in rows}


class TestZeroVotingAuthority:
    def test_active_source_votes(self):
        board = _board(set())
        assert KEY in board["Rook A"]["sourceRankMeta"]
        assert board["Rook Only"]["rankDerivedValue"]

    def test_inactive_source_votes_nowhere(self):
        board = _board({KEY})
        for row in board.values():
            assert KEY not in (row.get("sourceRankMeta") or {})
            assert KEY not in (row.get("sourceRanks") or {})
            assert KEY not in (row.get("freshnessExcludedSources") or [])

    def test_row_only_it_covered_is_unpriced_not_zero(self):
        row = _board({KEY})["Rook Only"]
        assert row.get("rankDerivedValue") is None
        assert row.get("canonicalConsensusRank") is None

    def test_other_sources_rows_are_untouched(self):
        on, off = _board(set()), _board({KEY})
        for name in ("Vet A", "Vet B"):
            assert on[name]["rankDerivedValue"] == off[name]["rankDerivedValue"]

    def test_contract_reader_feeds_the_pipeline(self, tmp_path, monkeypatch):
        """``build_api_data_contract``'s resolver reads the owner, as of the
        board time, from the build's own state directory."""
        state_dir = tmp_path / "data" / "scrape_state"
        state_dir.mkdir(parents=True)
        _record_inactive(state_dir, datetime(2026, 10, 2, tzinfo=timezone.utc))
        got = dc._seasonally_inactive_sources(
            datetime(2026, 10, 3, tzinfo=timezone.utc), csv_root=tmp_path
        )
        assert set(got) == {KEY}
        assert (
            dc._seasonally_inactive_sources(
                datetime(2026, 9, 1, tzinfo=timezone.utc), csv_root=tmp_path
            )
            == {}
        )


# ── Contract coverage watchdog ─────────────────────────────────────────
def test_coverage_watchdog_does_not_flag_an_inactive_source_with_a_fresh_stamp(monkeypatch):
    """The transition day: the board empties hours after a successful fetch,
    so the stamp is still fresh while the source (correctly) votes nowhere."""
    import scripts.watchdog_contract_coverage as wcc

    monkeypatch.setattr(wcc, "_csv_nonempty", lambda key: key == KEY)
    freshness = {KEY: {"lastFetched": "2026-10-02T22:00:00+00:00", "ageHours": 2.0}}
    violations, _ok, _skipped = wcc.evaluate_coverage_map(
        {}, freshness, {"flockFantasy": 24}, seasonally_inactive=set()
    )
    assert [v[0] for v in violations] == [KEY]
    violations, _ok, skipped = wcc.evaluate_coverage_map(
        {}, freshness, {"flockFantasy": 24}, seasonally_inactive={KEY}
    )
    assert violations == [] and KEY in skipped


@pytest.mark.parametrize("key", [s["key"] for s in dc._RANKING_SOURCES if s["key"] != KEY])
def test_undeclared_sources_cannot_be_switched_off_by_state(tmp_path, key):
    state_dir = tmp_path / "data" / "scrape_state"
    state_dir.mkdir(parents=True)
    (state_dir / f"{key}_seasonal.json").write_text(
        '{"state":"seasonally_inactive","transitions":'
        '[{"state":"seasonally_inactive","at":"2026-10-01T00:00:00Z"}]}',
        encoding="utf-8",
    )
    assert (
        dc._seasonally_inactive_sources(datetime(2026, 10, 3, tzinfo=timezone.utc), tmp_path) == {}
    )
