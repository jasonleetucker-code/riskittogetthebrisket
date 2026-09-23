"""Freshness × health × coverage in the canonical blend — end to end.

Two value-direct voters (KTC Crowd and KTC Trades, separate families) make
the arithmetic exact: a row they both price blends to their WEIGHTED mean,
so a stale source's loss of influence is measurable to the point.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.sources import freshness as fr

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
CFG = fr.load_config()


def _state(days_ago: float) -> dict:
    """A SNAPSHOT-style source whose last broad change was ``days_ago``."""
    events = [
        {
            "at": (NOW - timedelta(days=days_ago + k * 0.25)).isoformat(),
            "broad": True,
            "rowsChanged": 90,
            "rowsTotal": 100,
        }
        for k in range(6, 0, -1)
    ]
    at = (NOW - timedelta(days=days_ago)).isoformat()
    return {
        "subsets": {
            "players": {
                "changeHistory": events,
                "lastAnyMeaningfulChangeAt": at,
                "lastBroadDatasetChangeAt": at,
                "rowCount": 100,
                "rowCountHistory": [100],
            }
        },
        "health": {"state": "HEALTHY", "errors": []},
        "upstream": {},
    }


def _weighting(crowd_days: float, trades_days: float) -> dict:
    return {
        "ktcCrowdSfTep": fr.assess_source("ktcCrowdSfTep", _state(crowd_days), as_of=NOW, cfg=CFG),
        "ktcTradesSfTep": fr.assess_source(
            "ktcTradesSfTep", _state(trades_days), as_of=NOW, cfg=CFG
        ),
    }


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
    }


def _board(weighting: dict | None) -> dict[str, dict]:
    rows = [
        # Pins each source's site max at 9999 so value-direct = raw.
        _row("Anchor", "QB", ktcCrowdSfTep=9999, ktcTradesSfTep=9999),
        _row("Target", "WR", ktcCrowdSfTep=6000, ktcTradesSfTep=3000),
        _row("CrowdOnly", "RB", ktcCrowdSfTep=5000),
    ]
    dc._compute_unified_rankings(rows, {}, source_weighting=weighting)
    return {r["displayName"]: r for r in rows}


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.delenv("RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING", raising=False)
    feature_flags.reload()
    yield
    feature_flags.reload()


class TestInfluence:
    def test_fresh_sources_keep_full_influence(self):
        target = _board(_weighting(0.1, 0.1))["Target"]
        assert target["rankDerivedValue"] == 4500  # plain mean of 6000 / 3000
        assert target["sourceWeightState"] == dc.SOURCE_WEIGHT_NORMAL
        assert target["retainedAuthority"] == 1.0

    def test_stale_source_loses_influence_exactly_by_its_factor(self):
        # KTC Trades 24 h old against its 12 h rhythm → r = 2 → 0.7071.
        target = _board(_weighting(0.1, 1.0))["Target"]
        w = fr.freshness_from_ratio(2.0)
        expected = (6000 + 3000 * w) / (1 + w)
        assert target["rankDerivedValue"] == pytest.approx(expected, abs=1.0)
        meta = target["sourceRankMeta"]["ktcTradesSfTep"]
        assert meta["freshness"] == pytest.approx(w, abs=1e-4)
        assert meta["appliedWeight"] == pytest.approx(w, abs=1e-4)

    def test_influence_recovers_after_a_genuine_update(self):
        stale = _board(_weighting(0.1, 1.0))["Target"]["rankDerivedValue"]
        recovered = _board(_weighting(0.1, 0.1))["Target"]["rankDerivedValue"]
        assert stale > recovered == 4500

    def test_quarantined_source_drops_out_without_becoming_zero(self):
        # 30 days against a 12 h rhythm → far past quarantine.
        board = _board(_weighting(0.1, 30.0))
        target = board["Target"]
        assert target["rankDerivedValue"] > 0
        assert target["freshnessExcludedSources"] == ["ktcTradesSfTep"]
        assert target["sourceRankMeta"]["ktcTradesSfTep"]["contributedToBlend"] is False
        # A zero vote would have dragged the mean toward 0; exclusion does not,
        # and the stale observation still counts as present evidence for the
        # single-source haircut (no cliff at the quarantine line).
        assert target["rankDerivedValue"] == 6000
        assert target["sourceWeightState"] == dc.SOURCE_WEIGHT_SEVERELY_DEGRADED
        assert target["retainedAuthority"] == pytest.approx(0.5)

    def test_no_cliff_at_the_quarantine_line(self):
        """Owner requirement: smooth, no cliffs.  Just above the quarantine
        threshold the stale vote carries ~2% weight; just below it the vote
        is dropped.  The value must barely move — in particular the drop must
        not flip the row into the 30% single-source haircut."""
        # E = 12 h for KTC Trades; C4 crosses 0.02 at r ≈ 7.52 (≈ 90.2 h).
        above = _board(_weighting(0.1, 89.0 / 24))["Target"]
        below = _board(_weighting(0.1, 92.0 / 24))["Target"]
        assert above["freshnessExcludedSources"] == []
        assert below["freshnessExcludedSources"] == ["ktcTradesSfTep"]
        assert abs(above["rankDerivedValue"] - below["rankDerivedValue"]) <= 70
        assert not below.get("singleSourceValuePenaltyApplied")

    def test_missing_observation_is_not_zero(self):
        crowd_only = _board(_weighting(0.1, 0.1))["CrowdOnly"]
        assert crowd_only["rankDerivedValue"] > 0
        assert "ktcTradesSfTep" not in (crowd_only.get("sourceRanks") or {})

    def test_board_summary_names_every_source_and_its_weight(self):
        _board(_weighting(0.1, 1.0))
        summary = dc._LAST_SOURCE_WEIGHTING_SUMMARY
        assert summary["applied"] is True
        trades = summary["sources"]["ktcTradesSfTep"]
        assert trades["role"] == "model_input"
        assert trades["subsets"]["players"]["freshness"] == pytest.approx(0.7071, abs=1e-3)
        assert summary["sources"]["ktcCrowdTradesSfTep"]["role"] == "benchmark"

    def test_deterministic(self):
        a = _board(_weighting(0.1, 1.0))["Target"]["rankDerivedValue"]
        b = _board(_weighting(0.1, 1.0))["Target"]["rankDerivedValue"]
        assert a == b


class TestRollback:
    def test_flag_off_applies_base_weights_but_keeps_diagnostics(self, monkeypatch):
        monkeypatch.setenv("RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING", "0")
        feature_flags.reload()
        target = _board(_weighting(0.1, 1.0))["Target"]
        assert target["rankDerivedValue"] == 4500
        assert target["sourceRankMeta"]["ktcTradesSfTep"]["freshness"] == pytest.approx(
            0.7071, abs=1e-3
        )
        assert dc._LAST_SOURCE_WEIGHTING_SUMMARY["applied"] is False

    def test_no_weighting_means_base_weights(self):
        assert _board(None)["Target"]["rankDerivedValue"] == 4500


class TestAsOfIsTheBoardsOwnTime:
    def test_payload_without_a_scrape_timestamp_gets_no_weighting(self):
        assert dc._payload_as_of({}) is None
        assert dc._load_source_weighting(None) == {}

    def test_scrape_timestamp_is_the_clock(self):
        as_of = dc._payload_as_of({"scrapeTimestamp": "2026-09-23T18:41:31.473075+00:00"})
        assert as_of == datetime(2026, 9, 23, 18, 41, 31, 473075, tzinfo=timezone.utc)

    def test_a_historical_tree_never_reads_todays_state(self, tmp_path):
        assert dc._load_source_weighting(NOW, csv_root=tmp_path) == {}


class TestConfidenceReadsContentFreshness:
    """The B11 freshness axis: fetched-on-time is not fresh evidence when the
    content itself has aged past ``freshForConfidence`` of its authority."""

    def _evidence(self, freshness: float | None, *, applies: bool) -> bool | None:
        meta = {"valueContribution": 5000, "method": "value_direct"}
        if freshness is not None:
            meta["freshness"] = freshness
        (ev,) = dc._family_evidence_for_row(
            row={"position": "WR"},
            effective_source_ranks={"ktcCrowdSfTep": 10},
            effective_source_meta={"ktcCrowdSfTep": meta},
            src_by_key={},
            family_by_key={"ktcCrowdSfTep": "ktcCrowd"},
            fresh_by_source={"ktcCrowdSfTep": True},
            content_freshness_applies=applies,
        )
        return ev.fresh

    def test_stale_content_is_not_fresh_evidence(self):
        assert self._evidence(CFG.fresh_for_confidence - 0.01, applies=True) is False

    def test_mildly_overdue_content_is_still_fresh_evidence(self):
        assert self._evidence(CFG.fresh_for_confidence + 0.01, applies=True) is True

    def test_unreduced_content_keeps_the_fetch_answer(self):
        assert self._evidence(None, applies=True) is True

    def test_rollback_restores_the_fetch_only_answer(self):
        assert self._evidence(0.05, applies=False) is True
