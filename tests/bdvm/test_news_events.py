"""News → structured-events ingestion.

The safety properties that must hold, in order:
1. Auto events ALWAYS land in the speculation lane (confidence < 0.5)
   — effective_impact suppresses every non-sigma channel, so a
   headline can widen uncertainty but can never move a mean, shift
   hazard, or dock games.
2. Closed ontology: unmatched headlines map to nothing; ambiguous
   player mentions map to nothing.
3. Merge is dedup-by-eventId with existing-wins (a human may have
   raised an event's confidence — re-ingest must not undo that), and
   pruning touches ONLY news:* events.
4. The events-file fingerprint participates in the values cache key —
   writing the file invalidates cached boards.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.bdvm import news_events as ne
from src.bdvm.events import PlayerEvent, effective_impact

_norm = lambda s: s.lower()  # noqa: E731


def _item(headline, *, item_id="prov-abc123", players=None, ts="2026-07-28T12:00:00Z", body=""):
    return {
        "id": item_id,
        "ts": ts,
        "headline": headline,
        "body": body,
        "players": players
        if players is not None
        else [{"name": "Elite Backer", "impact": "negative", "ambiguous": False}],
    }


class TestClassification(unittest.TestCase):
    def test_keyword_rules_map_conservatively(self):
        cases = {
            "Star LB tears ACL in practice": "SURGERY",
            "RB suspended six games": "SUSPENSION",
            "WR activated from IR": "ACTIVATED_RETURN",
            "QB suffers hamstring injury": "INJURY",
            "TE questionable for opener": "PRACTICE_LIMITATION",
            "CB named starter for week 1": "DEPTH_CHART_PROMOTION",
            "Veteran benched after rough outing": "DEPTH_CHART_DEMOTION",
            "Team trades edge rusher to rival": "TRADE",
            "Safety released after camp": "RELEASE",
            "Star agrees to contract extension": "CONTRACT_EXTENSION",
            "Club places franchise tag on DT": "FRANCHISE_TAG",
            "FA linebacker signs two-year deal": "SIGNING",
        }
        for headline, expected in cases.items():
            self.assertEqual(ne.classify_news_item(_item(headline)), expected, headline)

    def test_unmatched_headline_maps_to_nothing(self):
        self.assertIsNone(ne.classify_news_item(_item("Player has great practice, looks fast")))

    def test_order_prefers_specific_over_general(self):
        # "season-ending injury" must be SURGERY-tier, not generic INJURY
        self.assertEqual(
            ne.classify_news_item(_item("Season-ending injury for star WR")), "SURGERY"
        )


class TestMapping(unittest.TestCase):
    def test_auto_events_are_speculation_sigma_only(self):
        events = ne.map_news_items_to_events(
            [_item("RB suspended six games")], name_normalizer=_norm
        )
        self.assertEqual(len(events), 1)
        e = events[0]
        self.assertLess(e["confidence"], 0.5)
        # Prove the §7 machinery treats it as sigma-only: build the real
        # PlayerEvent and check the effective impact channels.
        pe = PlayerEvent(
            event_id=e["eventId"],
            player_key=e["playerKey"],
            event_type=e["eventType"],
            effective_date=e["effectiveDate"],
            confidence=e["confidence"],
            source_reliability=e["sourceReliability"],
        )
        impact = effective_impact(pe, as_of=e["effectiveDate"])
        non_sigma = {k: v for k, v in impact.items() if k != "sigma_mult"}
        self.assertEqual(non_sigma, {})

    def test_ambiguous_mentions_skipped(self):
        events = ne.map_news_items_to_events(
            [
                _item(
                    "WR suffers hamstring injury",
                    players=[{"name": "Smith", "ambiguous": True}],
                )
            ],
            name_normalizer=_norm,
        )
        self.assertEqual(events, [])

    def test_event_id_is_stable_per_item_and_player(self):
        events = ne.map_news_items_to_events(
            [_item("QB suffers hamstring injury", item_id="espn-deadbeef")],
            name_normalizer=_norm,
        )
        self.assertEqual(events[0]["eventId"], "news:espn-deadbeef:elite backer")


class TestMerge(unittest.TestCase):
    def _event(self, event_id, date="2026-07-28", **kw):
        return {
            "eventId": event_id,
            "playerKey": "elite backer",
            "eventType": "INJURY",
            "effectiveDate": date,
            "confidence": kw.get("confidence", 0.45),
        }

    def test_existing_wins_on_collision_and_human_events_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            human = self._event("manual-1", date="2025-01-01", confidence=0.9)
            edited = self._event("news:x:elite backer", confidence=0.9)  # human-raised
            (base / "2026.json").write_text(json.dumps({"events": [human, edited]}))
            summary = ne.merge_events_file(
                [self._event("news:x:elite backer"), self._event("news:y:elite backer")],
                season=2026,
                base_dir=base,
                now=datetime(2026, 7, 28, tzinfo=timezone.utc),
            )
            self.assertTrue(summary["ok"])
            self.assertEqual(summary["added"], 1)  # only news:y is new
            stored = json.loads((base / "2026.json").read_text())["events"]
            by_id = {e["eventId"]: e for e in stored}
            # collision kept the HUMAN-EDITED confidence
            self.assertEqual(by_id["news:x:elite backer"]["confidence"], 0.9)
            # ancient HUMAN event survives pruning (only news:* prune)
            self.assertIn("manual-1", by_id)

    def test_stale_auto_events_pruned(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            old_auto = self._event("news:old:someone", date="2026-01-01")
            (base / "2026.json").write_text(json.dumps({"events": [old_auto]}))
            summary = ne.merge_events_file(
                [],
                season=2026,
                base_dir=base,
                now=datetime(2026, 7, 28, tzinfo=timezone.utc),
            )
            self.assertEqual(summary["pruned"], 1)
            stored = json.loads((base / "2026.json").read_text())["events"]
            self.assertEqual(stored, [])

    def test_no_change_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            summary = ne.merge_events_file([], season=2026, base_dir=base)
            self.assertTrue(summary.get("unchanged"))
            self.assertFalse((base / "2026.json").exists())

    def test_corrupt_file_refuses_rather_than_discarding(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / "2026.json").write_text("{not json")
            summary = ne.merge_events_file([self._event("news:x:a")], season=2026, base_dir=base)
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["reason"], "events_file_unreadable")
            self.assertEqual((base / "2026.json").read_text(), "{not json")


class TestCacheFingerprint(unittest.TestCase):
    def test_events_file_write_invalidates_values_cache(self):
        from src.api import bdvm_api
        from src.bdvm import events as events_mod

        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            with (
                mock.patch.object(events_mod, "EVENTS_DIR", base),
                mock.patch.object(bdvm_api, "latest_snapshot_path", return_value=None),
                mock.patch.object(bdvm_api, "_actuals_for", return_value=(None, {})),
                mock.patch.object(
                    bdvm_api,
                    "run_valuation",
                    side_effect=lambda _c, **kw: {"status": "ok", "meta": {}},
                ) as rv,
            ):
                contract = {"generatedAt": "x", "currentDraftYear": 2026}
                bdvm_api.get_bdvm_values(contract, "dynasty_main")
                bdvm_api.get_bdvm_values(contract, "dynasty_main")
                self.assertEqual(rv.call_count, 1)  # cached
                (base / "2026.json").write_text('{"events": []}')
                bdvm_api.get_bdvm_values(contract, "dynasty_main")
                self.assertEqual(rv.call_count, 2)  # fingerprint change → recompute


if __name__ == "__main__":
    unittest.main()
