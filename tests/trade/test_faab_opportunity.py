"""Tests for ``src/trade/faab_opportunity.py`` — the Live Waiver Opportunity layer.

Full design record: ``docs/faab-live-opportunity-model.md``.  These pin
the directive's guardrails (Part XIII) that are this module's
responsibility specifically — the engine-level guardrails (season
option value, market model, etc.) stay in ``test_faab_engine.py`` and
``test_faab_recommend_endpoint.py``.
"""

from __future__ import annotations

from unittest import mock

from src.bdvm.events import PlayerEvent
from src.trade import faab_opportunity as fo


def _snapshot(*, trend=None, games=4, rank=None):
    depth = {"rank": rank} if rank is not None else None
    snaps = {"trend": trend, "games": games} if trend is not None else None
    rec = {}
    if snaps is not None:
        rec["snaps"] = snaps
    if depth is not None:
        rec["depth"] = depth
    return {
        "sleeperIndex": {"sid1": "gsis1"},
        "players": {"gsis1": rec},
    }


class TestNoEvidenceDegradesToDynastyValue:
    def test_no_playerctx_no_events_returns_dynasty_value_unchanged(self):
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=None),
            mock.patch("src.bdvm.events.load_events_file", return_value=[]),
        ):
            result = fo.opportunity_value(2500.0, sleeper_id="sid1", player_name="Nobody Here")
        assert result["value"] == 2500.0
        assert result["hasEvidence"] is False
        assert result["shortTermSurplus"] == 0.0

    def test_missing_sleeper_id_is_missing_not_zero(self):
        # No sleeper_id at all -> playerctx lookup structurally cannot
        # run; this must read the same as "no evidence found", not
        # raise or silently invent a role signal.
        with mock.patch("src.bdvm.events.load_events_file", return_value=[]):
            result = fo.opportunity_value(1800.0, sleeper_id=None, player_name="Foo Bar")
        assert result["value"] == 1800.0
        assert result["hasEvidence"] is False


class TestRoleEvidenceRaisesValue:
    def test_strong_role_evidence_raises_value_above_dynasty_value(self):
        snap = _snapshot(trend=15.0, games=4, rank=1)
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=snap),
            mock.patch("src.bdvm.events.load_events_file", return_value=[]),
        ):
            result = fo.opportunity_value(2000.0, sleeper_id="sid1", player_name="Role Guy")
        assert result["value"] > 2000.0
        assert result["hasEvidence"] is True

    def test_role_evidence_never_pushes_value_below_dynasty_value(self):
        # A negative snap trend still only SUBTRACTS from a bounded
        # surplus that is clamped at 0 before being added — the layer
        # names a reason to price ABOVE the slow board, never below a
        # value the canonical pipeline already stands behind.
        snap = _snapshot(trend=-15.0, games=4, rank=4)
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=snap),
            mock.patch("src.bdvm.events.load_events_file", return_value=[]),
        ):
            result = fo.opportunity_value(2000.0, sleeper_id="sid1", player_name="Fading Guy")
        assert result["value"] == 2000.0


class TestRetentionBounds:
    def test_retention_defaults_flat_and_bounded(self):
        for v in (0.0, 500.0, 5000.0, 9999.0):
            r = fo.retention(v)
            assert 0.0 <= r <= 1.0
        # Documented provisional default: flat 1.0 until calibrated.
        assert fo.retention(2500.0) == 1.0


class TestNoDiscontinuity:
    """Directive Part XIII #3: canonical dynasty value changing slightly
    cannot create an absurd discontinuity in the opportunity value."""

    def test_small_dynasty_value_change_produces_small_opportunity_value_change(self):
        snap = _snapshot(trend=10.0, games=4, rank=2)
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=snap),
            mock.patch("src.bdvm.events.load_events_file", return_value=[]),
        ):
            low = fo.opportunity_value(1999.0, sleeper_id="sid1", player_name="Edge Case")
            high = fo.opportunity_value(2001.0, sleeper_id="sid1", player_name="Edge Case")
        # short_term_surplus is bounded independently of dynasty_value
        # (it never reads it), so the two results differ by exactly the
        # 2-point dynasty_value gap, not by anything the role evidence
        # contributes.
        assert abs((high["value"] - low["value"]) - 2.0) < 1e-6


class TestEventAxisPromotionAndAvailability:
    def test_confirmed_promotion_event_is_evidence(self):
        snap = _snapshot(trend=None, rank=None)
        promo = PlayerEvent(
            event_id="depthchart:2026-09-01:role guy:promoted",
            player_key="role guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-09-01",
            confidence=0.85,
            source_reliability=0.85,
        )
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=snap),
            mock.patch("src.bdvm.events.load_events_file", return_value=[promo]),
        ):
            result = fo.opportunity_value(
                2000.0, sleeper_id="sid1", player_name="Role Guy", today="2026-09-01"
            )
        assert result["hasEvidence"] is True
        assert result["value"] > 2000.0

    def test_starter_out_style_promotion_materially_increases_backup_opportunity(self):
        """Directive Part XIII #4: a depth-chart promotion event (the
        mechanism a starter's injury reaches a backup through, per
        docs/faab-live-opportunity-model.md — ESPN's own depth chart
        re-orders when a starter goes down) must materially move the
        backup's value, not just nudge it."""
        promo = PlayerEvent(
            event_id="depthchart:2026-09-01:backup guy:promoted",
            player_key="backup guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-09-01",
            confidence=0.85,
            source_reliability=0.85,
        )
        snap = _snapshot(trend=None, rank=1)
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=snap),
            mock.patch("src.bdvm.events.load_events_file", return_value=[promo]),
        ):
            result = fo.opportunity_value(
                1800.0, sleeper_id="sid1", player_name="Backup Guy", today="2026-09-01"
            )
        # A material move, not a rounding-error nudge.
        assert result["value"] - 1800.0 > 50.0

    def test_active_injury_damps_availability_and_reduces_surplus(self):
        promo = PlayerEvent(
            event_id="e1",
            player_key="hurt guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-08-30",
            confidence=0.85,
            source_reliability=0.85,
        )
        injury = PlayerEvent(
            event_id="e2",
            player_key="hurt guy",
            event_type="INJURY",
            effective_date="2026-08-31",
            confidence=0.9,
            source_reliability=0.9,
        )
        snap = _snapshot(trend=None, rank=1)
        with mock.patch("src.playerctx.service.load_playerctx", return_value=snap):
            with mock.patch("src.bdvm.events.load_events_file", return_value=[promo]):
                healthy = fo.opportunity_value(
                    1800.0, sleeper_id="sid1", player_name="Hurt Guy", today="2026-09-01"
                )
            with mock.patch("src.bdvm.events.load_events_file", return_value=[promo, injury]):
                injured = fo.opportunity_value(
                    1800.0, sleeper_id="sid1", player_name="Hurt Guy", today="2026-09-01"
                )
        assert injured["availability"] < 1.0
        assert injured["value"] < healthy["value"]


class TestStaleSpeculationCannotMoveTheMean:
    """Directive Part XIII #5: a stale/speculative (news-lane,
    confidence < 0.5) event cannot apply a role boost — enforced by
    ``src.bdvm.events.effective_impact``'s speculation gate, exercised
    here through this module's own entry point."""

    def test_speculative_news_event_contributes_no_mu_pct(self):
        speculative = PlayerEvent(
            event_id="news:item1:speculative guy",
            player_key="speculative guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-09-01",
            confidence=0.45,  # below the 0.5 speculation threshold
            source_reliability=0.6,
        )
        with (
            mock.patch("src.playerctx.service.load_playerctx", return_value=None),
            mock.patch("src.bdvm.events.load_events_file", return_value=[speculative]),
        ):
            result = fo.opportunity_value(
                2000.0, sleeper_id="sid1", player_name="Speculative Guy", today="2026-09-01"
            )
        # Speculative-confidence events widen sigma only (BDVM's own
        # rule) — mu_pct is suppressed entirely, so this must read as
        # NO evidence for the FAAB opportunity layer, not a small boost.
        assert result["hasEvidence"] is False
        assert result["value"] == 2000.0

    def test_stale_event_contributes_far_less_than_a_fresh_one(self):
        """~8 months against a 45-day half-life (2026-01-01 as-of
        2026-09-01) decays toward negligible but never hits exactly
        zero — ``2 ** (-days/half_life)`` is asymptotic, not a cutoff.
        The guarantee this pins is relative: a long-stale event must
        move the value far less than a fresh, otherwise-identical one,
        not that it is coerced to a fabricated exact zero."""
        fresh = PlayerEvent(
            event_id="e1",
            player_key="fresh guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-08-30",
            confidence=0.9,
            source_reliability=0.9,
        )
        stale = PlayerEvent(
            event_id="e2",
            player_key="stale guy",
            event_type="DEPTH_CHART_PROMOTION",
            effective_date="2026-01-01",
            confidence=0.9,
            source_reliability=0.9,
        )
        with mock.patch("src.playerctx.service.load_playerctx", return_value=None):
            with mock.patch("src.bdvm.events.load_events_file", return_value=[fresh]):
                fresh_result = fo.opportunity_value(
                    2000.0, sleeper_id="sid1", player_name="Fresh Guy", today="2026-09-01"
                )
            with mock.patch("src.bdvm.events.load_events_file", return_value=[stale]):
                stale_result = fo.opportunity_value(
                    2000.0, sleeper_id="sid1", player_name="Stale Guy", today="2026-09-01"
                )
        fresh_gain = fresh_result["value"] - 2000.0
        stale_gain = stale_result["value"] - 2000.0
        assert fresh_gain > 0.0
        assert stale_gain < fresh_gain * 0.1


class TestMarketHeatNeverEntersThisModule:
    """Worth and demand are different axes (directive Part VII) — this
    module must have no path that reads Sleeper trending at all."""

    def test_module_never_imports_sleeper_trending(self):
        import ast
        from pathlib import Path

        src = Path(fo.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
        assert not any("sleeper_trending" in n for n in names)
