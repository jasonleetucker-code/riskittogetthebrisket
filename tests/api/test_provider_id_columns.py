"""W06-F009 — provider-ID columns must be found whatever they are spelled.

The loader picked the Sleeper-id column out of a CSV by testing the header
against a hand-maintained tuple of literal spellings:

    _SLEEPER_ID_ALIASES = ("sleeper_id", "sleeperId", "sleeper_player_id")

``dynastyNerdsSfTep.csv`` ships ``SleeperId`` — a spelling nobody added —
so all 294 of its rows carried no ID and the source joined by name only.
The defect is not that one spelling was missing. It is that an
enumerated-literal list silently fails closed: a source can start
publishing ID-grade identity and the pipeline keeps ignoring it with no
warning, no metric, and no failing test.

Measured before the repair (``b5_id_join_probe``): the ID join would have
recovered **0 rows** on the 2026-08-12 board, because the name cascade
already resolved 293 of 294 and the two agreed on all 290 overlaps with
**zero contradictions**. So this repair buys resilience, not match rate —
ID-grade identity survives the vendor/Sleeper name drift that breaks a
name join ("Kenneth Gainwell" vs "Kenny Gainwell"), and nothing on the
current board moves. That is the desired shape: an identity repair whose
immediate blast radius is zero is one that cannot have introduced a
false positive.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.api import data_contract as dc

REPO = Path(__file__).resolve().parents[2]


class TestTheColumnIsFoundWhateverItIsCalled(unittest.TestCase):
    def test_common_spellings_all_resolve(self):
        for spelling in (
            "sleeper_id",
            "sleeperId",
            "SleeperId",
            "SLEEPER_ID",
            "Sleeper Id",
            "sleeper-id",
            "sleeper_player_id",
            "SleeperPlayerId",
        ):
            got = dc._pick_provider_id({spelling: "1234"}, dc._SLEEPER_ID_TOKENS)
            self.assertEqual(got, "1234", f"{spelling!r} was not recognised")

    def test_unrelated_columns_are_not_swept_in(self):
        """The failure mode in the other direction.

        A normalizing matcher that is too loose starts claiming columns
        that merely mention the word — which would attach a wrong ID and
        produce a confident wrong match, the outcome this phase ranks as
        worse than a miss.
        """
        for spelling in (
            "sleeper_id_source",
            "old_sleeper_id",
            "sleeper_team_id",
            "sleeper",
            "id",
            "espn_id",
            "gsis_id",
        ):
            got = dc._pick_provider_id({spelling: "1234"}, dc._SLEEPER_ID_TOKENS)
            self.assertEqual(got, "", f"{spelling!r} was wrongly treated as a Sleeper id")

    def test_blank_and_missing_are_not_values(self):
        self.assertEqual(dc._pick_provider_id({"SleeperId": ""}, dc._SLEEPER_ID_TOKENS), "")
        self.assertEqual(dc._pick_provider_id({"SleeperId": None}, dc._SLEEPER_ID_TOKENS), "")
        self.assertEqual(dc._pick_provider_id({}, dc._SLEEPER_ID_TOKENS), "")

    def test_an_explicit_spelling_still_wins_over_a_normalized_one(self):
        """Determinism when a CSV carries two spellings at once."""
        row = {"sleeper_id": "111", "SleeperId": "222"}
        self.assertEqual(dc._pick_provider_id(row, dc._SLEEPER_ID_TOKENS), "111")


class TestTheLiveSourcesAreCovered(unittest.TestCase):
    """The regression that would have caught W06-F009 when it appeared.

    Reads the real CSV headers rather than a fixture: the defect was a
    mismatch between what vendors publish and what the loader enumerates,
    and only the real headers can express that.
    """

    def _headers(self):
        out = {}
        for key, spec in dc._SOURCE_CSV_PATHS.items():
            rel = spec if isinstance(spec, str) else spec.get("path")
            p = REPO / str(rel)
            if not p.is_file():
                continue
            hdr = next(csv.reader(p.open(encoding="utf-8-sig")), [])
            out[key] = hdr
        return out

    def test_every_published_sleeper_id_column_is_visible(self):
        missed = []
        for key, hdr in self._headers().items():
            for col in hdr:
                norm = dc._normalize_header_token(col)
                looks_like_sleeper_id = norm in dc._SLEEPER_ID_TOKENS
                mentions = "sleeper" in col.lower() and "id" in col.lower()
                if mentions and not looks_like_sleeper_id:
                    # Not automatically a defect — could be a genuinely
                    # different field — but it must be a deliberate call,
                    # so surface it rather than let it pass silently.
                    missed.append((key, col))
        self.assertEqual(
            missed,
            [],
            "a source publishes a sleeper-id-shaped column the loader does not "
            f"recognise: {missed}. Add the normalized token to _SLEEPER_ID_TOKENS "
            "or record why it is a different field.",
        )

    def test_dynasty_nerds_is_the_source_this_finding_was_about(self):
        hdr = self._headers().get("dynastyNerdsSfTep")
        if hdr is None:
            self.skipTest("dynastyNerdsSfTep CSV not present")
        self.assertIn("SleeperId", hdr)
        self.assertEqual(dc._pick_provider_id({"SleeperId": "4034"}, dc._SLEEPER_ID_TOKENS), "4034")


if __name__ == "__main__":
    unittest.main()
