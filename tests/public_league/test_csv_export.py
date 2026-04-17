"""Tests for the public-league CSV exporters."""
from __future__ import annotations

import csv
import io
import unittest

from src.public_league import build_public_contract, csv_export

from tests.public_league.fixtures import build_test_snapshot


class CsvExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = build_test_snapshot()
        cls.contract = build_public_contract(cls.snapshot)
        cls.sections = cls.contract["sections"]

    def _parse(self, csv_text: str) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(csv_text)))

    def test_history_export_has_rows(self) -> None:
        name, text = csv_export.export_history(self.sections["history"])
        self.assertTrue(name.endswith(".csv"))
        rows = self._parse(text)
        self.assertGreater(len(rows), 0)
        self.assertIn("ownerId", rows[0])
        self.assertIn("teamName", rows[0])
        self.assertIn("finalPlace", rows[0])

    def test_hall_of_fame_export(self) -> None:
        name, text = csv_export.export_hall_of_fame(self.sections["history"])
        rows = self._parse(text)
        self.assertTrue(rows)
        # owner-B wins in the fixture with 2 championships.
        champs = [r for r in rows if r["ownerId"] == "owner-B"]
        self.assertTrue(champs)
        self.assertEqual(int(champs[0]["championships"]), 2)

    def test_rivalries_export(self) -> None:
        name, text = csv_export.export_rivalries(self.sections["rivalries"])
        rows = self._parse(text)
        self.assertTrue(rows)
        self.assertIn("rivalryIndex", rows[0])
        self.assertIn("ownerIdA", rows[0])
        self.assertIn("ownerIdB", rows[0])

    def test_awards_export_includes_descriptions(self) -> None:
        name, text = csv_export.export_awards(self.sections["awards"])
        rows = self._parse(text)
        self.assertTrue(rows)
        keys = {r["key"] for r in rows}
        for required in ("champion", "runner_up", "top_seed"):
            self.assertIn(required, keys)

    def test_records_export_has_categories(self) -> None:
        name, text = csv_export.export_records(self.sections["records"])
        rows = self._parse(text)
        cats = {r["category"] for r in rows}
        self.assertIn("highest_single_week", cats)
        self.assertIn("biggest_margin", cats)

    def test_franchise_export_index(self) -> None:
        name, text = csv_export.export_franchise(self.sections["franchise"])
        rows = self._parse(text)
        self.assertTrue(rows)
        self.assertIn("ownerId", rows[0])

    def test_franchise_export_owner_scoped(self) -> None:
        name, text = csv_export.export_franchise(
            self.sections["franchise"], owner_id="owner-B",
        )
        self.assertIn("owner-B", name)
        rows = self._parse(text)
        self.assertTrue(rows)
        self.assertTrue(all(r["ownerId"] == "owner-B" for r in rows))

    def test_activity_export(self) -> None:
        name, text = csv_export.export_activity(self.sections["activity"])
        rows = self._parse(text)
        # Fixture has 2 trades × 2 sides = 4 rows.
        self.assertEqual(len(rows), 4)
        self.assertIn("receivedAssets", rows[0])

    def test_draft_export(self) -> None:
        name, text = csv_export.export_draft(self.sections["draft"])
        rows = self._parse(text)
        self.assertTrue(rows)
        self.assertTrue(any(r["playerName"] == "Rudy Rook" for r in rows))

    def test_weekly_export(self) -> None:
        name, text = csv_export.export_weekly(self.sections["weekly"])
        rows = self._parse(text)
        self.assertTrue(rows)
        for row in rows:
            self.assertIn("margin", row)

    def test_superlatives_export(self) -> None:
        name, text = csv_export.export_superlatives(self.sections["superlatives"])
        rows = self._parse(text)
        self.assertTrue(rows)
        superlatives = {r["superlative"] for r in rows}
        self.assertIn("mostQbHeavy", superlatives)

    def test_archives_export_trades(self) -> None:
        name, text = csv_export.export_archives(self.sections["archives"], kind="trades")
        rows = self._parse(text)
        self.assertEqual(len(rows), 2)  # fixture has 2 trades

    def test_archives_export_default_kind(self) -> None:
        # With no kind argument falls back to trades.
        name, text = csv_export.export_archives(self.sections["archives"])
        self.assertIn("archives-trades", name)

    def test_overview_export(self) -> None:
        name, text = csv_export.export_overview(self.sections["overview"])
        rows = self._parse(text)
        fields = {r["field"] for r in rows}
        self.assertIn("managers", fields)
        self.assertIn("totalTrades", fields)

    def test_export_section_router(self) -> None:
        name, text = csv_export.export_section("history", self.sections["history"])
        self.assertTrue(text)
        with self.assertRaises(KeyError):
            csv_export.export_section("does-not-exist", {})

    def test_cells_escape_commas_and_quotes(self) -> None:
        # Ensure the CSV module properly quotes cells with commas/quotes.
        rows = [{"team": 'Bea, "the Beast"', "wins": 11}]
        text = csv_export._write_csv(rows, ["team", "wins"])
        parsed = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(parsed[0]["team"], 'Bea, "the Beast"')
        self.assertEqual(parsed[0]["wins"], "11")


try:
    from fastapi.testclient import TestClient
    _HAVE_TC = True
except Exception:  # noqa: BLE001
    _HAVE_TC = False


@unittest.skipUnless(_HAVE_TC, "fastapi TestClient not installed")
class CsvRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import os
        from tests.public_league.fixtures import install_stubs, build_stub_client

        install_stubs(build_stub_client())
        os.environ["SLEEPER_LEAGUE_ID"] = "L2025"
        from server import app, _public_league_cache
        _public_league_cache.clear()
        _public_league_cache.update({
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
        })
        cls.client = TestClient(app)

    def test_csv_route_serves_text_csv(self) -> None:
        r = self.client.get("/api/public/league/history.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/csv", r.headers["content-type"])
        self.assertIn("attachment", r.headers.get("content-disposition", ""))
        self.assertIn("history-standings.csv", r.headers.get("content-disposition", ""))
        self.assertTrue(r.text.splitlines()[0].startswith("season,"))

    def test_csv_route_supports_franchise_owner(self) -> None:
        r = self.client.get("/api/public/league/franchise.csv?owner=owner-B")
        self.assertEqual(r.status_code, 200)
        self.assertIn("owner-B", r.headers["content-disposition"])

    def test_csv_route_supports_archives_kind(self) -> None:
        r = self.client.get("/api/public/league/archives.csv?kind=waivers")
        self.assertEqual(r.status_code, 200)
        self.assertIn("archives-waivers.csv", r.headers["content-disposition"])

    def test_csv_route_hall_of_fame_alias(self) -> None:
        r = self.client.get("/api/public/league/hall_of_fame.csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("hall-of-fame.csv", r.headers["content-disposition"])

    def test_csv_route_unknown_section_404(self) -> None:
        r = self.client.get("/api/public/league/nope.csv")
        self.assertEqual(r.status_code, 404)

    def test_csv_payload_never_leaks_private_fields(self) -> None:
        for section in ["history", "rivalries", "awards", "records", "activity", "draft", "weekly", "superlatives"]:
            r = self.client.get(f"/api/public/league/{section}.csv")
            self.assertEqual(r.status_code, 200)
            blob = r.text.lower()
            for banned in ("ourvalue", "edgesignals", "edgescore", "siteweights", "tradefinder"):
                self.assertNotIn(banned, blob, msg=f"{section}.csv leaked {banned}")


if __name__ == "__main__":
    unittest.main()
