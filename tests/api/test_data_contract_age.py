"""Pin that ``age`` flows from raw scraper output to the contract row.

Regression for the Age curves panel — the frontend overlay
(``frontend/components/graphs/AgeCurveOverlay.jsx``) filters out
rows where ``age`` is null/non-finite, so any future change that
strips this field will silently empty the curves.
"""
from __future__ import annotations

import unittest

from src.api.data_contract import build_api_data_contract


def _payload_with_ages():
    return {
        "players": {
            "Josh Allen": {
                "_composite": 8500,
                "_rawComposite": 8500,
                "_finalAdjusted": 8400,
                "_sites": 6,
                "position": "QB",
                "team": "BUF",
                "age": 30,
            },
            "Ja'Marr Chase": {
                "_composite": 9200,
                "_rawComposite": 9200,
                "_finalAdjusted": 9100,
                "_sites": 7,
                "position": "WR",
                "team": "CIN",
                "age": 26,
            },
            "Mystery Rookie": {
                "_composite": 5000,
                "_rawComposite": 5000,
                "_finalAdjusted": 5000,
                "_sites": 4,
                "position": "RB",
                "team": "FA",
                # No age — Sleeper hasn't ingested birth_date yet.
            },
        },
        "sites": [{"key": "ktcSfTep"}],
        "maxValues": {"ktcSfTep": 9999},
        "sleeper": {
            "positions": {
                "Josh Allen": "QB",
                "Ja'Marr Chase": "WR",
                "Mystery Rookie": "RB",
            }
        },
    }


class TestContractAgePreservation(unittest.TestCase):
    def test_age_stamped_on_player_rows(self):
        contract = build_api_data_contract(_payload_with_ages())
        rows = {r["canonicalName"]: r for r in contract.get("playersArray", [])}
        self.assertEqual(rows["Josh Allen"]["age"], 30)
        self.assertEqual(rows["Ja'Marr Chase"]["age"], 26)

    def test_age_null_when_source_missing(self):
        contract = build_api_data_contract(_payload_with_ages())
        rows = {r["canonicalName"]: r for r in contract.get("playersArray", [])}
        self.assertIsNone(rows["Mystery Rookie"]["age"])

    def test_age_raw_fallback_used_when_age_absent(self):
        payload = _payload_with_ages()
        payload["players"]["Josh Allen"].pop("age")
        payload["players"]["Josh Allen"]["age_raw"] = 30
        contract = build_api_data_contract(payload)
        rows = {r["canonicalName"]: r for r in contract.get("playersArray", [])}
        self.assertEqual(rows["Josh Allen"]["age"], 30)
