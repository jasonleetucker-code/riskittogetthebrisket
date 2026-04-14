"""End-to-end safety rails for draft pick handling.

Draft picks travel the same authoritative pipeline as players:
scraper payload → ``build_api_data_contract`` → ``_compute_unified_rankings``
→ ``playersArray``.  The backend already stamps
``canonicalConsensusRank``, ``rankDerivedValue``, ``sourceRanks``,
``confidenceBucket``, and the full trust/audit block on every pick,
and the frontend now renders them on the rankings board and trade
calculator alongside players.

These tests guard the pick-specific invariants that must never
regress:

1. Picks survive the full contract build (assetClass=="pick", pos=="PICK")
2. Pick canonical ids do not collide with any player canonical name
3. Picks carry a unified rank + value + source ranks
4. Picks do not break ``assert_ranking_coherence`` (no duplicate
   ranks, monotonic value decrease, tier alignment)
5. Every top-400 1-src pick has an allowlist reason (or matches the
   structural exemption — expected_sources == matched_sources)
6. Picks from the live ``idpTradeCalc.csv`` do not silently disappear
   from the API output
7. Representative picks (2026 1.01, 1.06, 1.12, 2.06, 2027 Mid 1st)
   are present with positive values

Run with:  python3 -m pytest tests/api/test_picks_end_to_end.py -v
"""
from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    SINGLE_SOURCE_ALLOWLIST,
    _is_pick_name,
    assert_no_unexplained_single_source,
    assert_ranking_coherence,
    build_api_data_contract,
)


_REPO = Path(__file__).resolve().parents[2]


def _load_contract() -> dict[str, Any] | None:
    """Build a contract from the latest scraper export, or return None."""
    data_dir = _REPO / "exports" / "latest"
    json_files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


def _pick_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r
        for r in contract.get("playersArray", [])
        if r.get("assetClass") == "pick"
    ]


def _player_rows(contract: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        r
        for r in contract.get("playersArray", [])
        if r.get("assetClass") != "pick"
    ]


class TestPicksPresentInContract(unittest.TestCase):
    """Picks must survive the full contract build."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_picks_present_in_players_array(self) -> None:
        picks = _pick_rows(self.contract)
        # The scraper payload currently carries ~120 distinct pick
        # canonical names (slot-specific 2026 Pick 1.01..6.12 +
        # generic 2027/2028 Early/Mid/Late × 1st..4th).  Require at
        # least 60 as a sanity floor — enough that a regression where
        # picks are dropped entirely (or scoped-out of the board) would
        # trip the test but shallow data drift does not.
        self.assertGreaterEqual(
            len(picks),
            60,
            f"Too few picks in playersArray: {len(picks)}",
        )

    def test_every_pick_is_PICK_position(self) -> None:
        picks = _pick_rows(self.contract)
        bad = [p for p in picks if p.get("position") != "PICK"]
        self.assertEqual(
            bad,
            [],
            "Pick rows with wrong position: "
            f"{[(p['canonicalName'], p.get('position')) for p in bad[:5]]}",
        )

    def test_every_pick_has_rank_and_value(self) -> None:
        picks = _pick_rows(self.contract)
        missing = [
            p["canonicalName"]
            for p in picks
            if not p.get("canonicalConsensusRank")
            or not p.get("rankDerivedValue")
            or p.get("rankDerivedValue") <= 0
        ]
        self.assertEqual(
            missing, [], f"Picks missing rank/value: {missing[:10]}"
        )

    def test_every_pick_has_source_ranks(self) -> None:
        picks = _pick_rows(self.contract)
        empty = [
            p["canonicalName"]
            for p in picks
            if not (p.get("sourceRanks") or {})
        ]
        self.assertEqual(
            empty, [], f"Picks with no sourceRanks: {empty[:10]}"
        )


class TestPickCanonicalIdentity(unittest.TestCase):
    """Pick canonical ids must not collide with player names."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_pick_names_match_pick_detector(self) -> None:
        picks = _pick_rows(self.contract)
        bad = [
            p["canonicalName"]
            for p in picks
            if not _is_pick_name(p["canonicalName"] or "")
        ]
        self.assertEqual(
            bad,
            [],
            f"assetClass=='pick' rows whose name fails _is_pick_name: {bad[:5]}",
        )

    def test_pick_names_unique_against_players(self) -> None:
        picks = _pick_rows(self.contract)
        players = _player_rows(self.contract)
        pick_names = {p["canonicalName"] for p in picks}
        player_names = {p["canonicalName"] for p in players}
        collisions = pick_names & player_names
        self.assertEqual(
            collisions,
            set(),
            f"Pick canonical names collide with player names: "
            f"{sorted(collisions)[:5]}",
        )

    def test_no_player_name_accidentally_flagged_as_pick(self) -> None:
        players = _player_rows(self.contract)
        flagged = [
            p["canonicalName"]
            for p in players
            if _is_pick_name(p.get("canonicalName") or "")
        ]
        self.assertEqual(
            flagged,
            [],
            f"Player rows whose name matches pick pattern: {flagged[:5]}",
        )


class TestPicksDoNotBreakSafetyRails(unittest.TestCase):
    """Picks must coexist with the board-level assertions."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")

    def test_ranking_coherence_with_picks(self) -> None:
        # ``assert_ranking_coherence`` walks rows in the order supplied
        # and requires strictly increasing ranks, so the caller is
        # responsible for sorting by rank first.  Existing coherence
        # tests (tests/api/test_ranking_coherence.py) sort the same way.
        ranked = sorted(
            [
                r
                for r in self.contract["playersArray"]
                if r.get("canonicalConsensusRank")
            ],
            key=lambda r: int(r["canonicalConsensusRank"]),
        )
        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], "\n".join(errors[:5]))

    def test_no_unexplained_single_source_with_picks(self) -> None:
        # All 1-src picks in the top 400 must either be explicitly
        # allowlisted or structurally single-source (expected ==
        # matched).  The assertion function already handles both cases.
        unexplained = assert_no_unexplained_single_source(
            self.contract["playersArray"], rank_limit=400
        )
        self.assertEqual(
            unexplained,
            [],
            "Unexplained 1-src rows (including any picks): "
            f"{[u['canonicalName'] for u in unexplained[:5]]}",
        )


class TestIdpTradeCalcPicksSurviveEnrichment(unittest.TestCase):
    """Every pick in the IDPTC CSV must end up in the final contract."""

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")
        csv_path = _REPO / "exports" / "latest" / "site_raw" / "idpTradeCalc.csv"
        if not csv_path.exists():
            self.skipTest("No idpTradeCalc.csv snapshot")
        self.csv_picks: list[str] = []
        with csv_path.open("r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or row.get("Name") or "").strip()
                if name and _is_pick_name(name):
                    self.csv_picks.append(name)

    def test_idptc_picks_all_present_in_contract(self) -> None:
        if not self.csv_picks:
            self.skipTest("No picks in idpTradeCalc.csv")
        contract_pick_names = {
            p["canonicalName"] for p in _pick_rows(self.contract)
        }
        missing = [n for n in self.csv_picks if n not in contract_pick_names]
        self.assertEqual(
            missing,
            [],
            f"IDPTC picks missing from contract output: {missing[:10]}",
        )


class TestRepresentativePicks(unittest.TestCase):
    """Specific picks from the 7-point verification list must be findable."""

    TARGETS = [
        "2026 Pick 1.01",  # early-1st, slot-specific
        "2026 Pick 1.06",  # mid-1st, slot-specific
        "2026 Pick 1.12",  # late-1st, slot-specific
        "2026 Pick 2.06",  # mid-2nd, slot-specific
        "2027 Mid 1st",    # generic future 1st
    ]

    def setUp(self) -> None:
        self.contract = _load_contract()
        if self.contract is None:
            self.skipTest("No live scraper export available")
        self.by_name = {
            p["canonicalName"]: p for p in _pick_rows(self.contract)
        }

    def test_targets_have_rank_and_value(self) -> None:
        for name in self.TARGETS:
            with self.subTest(pick=name):
                row = self.by_name.get(name)
                self.assertIsNotNone(
                    row, f"{name} missing from pick contract output"
                )
                assert row is not None
                self.assertTrue(
                    row.get("canonicalConsensusRank"),
                    f"{name} has no canonicalConsensusRank",
                )
                self.assertGreater(
                    int(row.get("rankDerivedValue") or 0),
                    0,
                    f"{name} has non-positive rankDerivedValue",
                )
                self.assertEqual(row.get("assetClass"), "pick")
                self.assertEqual(row.get("position"), "PICK")
                # Every target must have at least one ranking source.
                self.assertTrue(
                    (row.get("sourceRanks") or {}),
                    f"{name} has no sourceRanks",
                )

    def test_early_first_outranks_late_first(self) -> None:
        early = self.by_name.get("2026 Pick 1.01")
        late = self.by_name.get("2026 Pick 1.12")
        if not early or not late:
            self.skipTest("Slot-specific 1st not in snapshot")
        self.assertLess(
            int(early["canonicalConsensusRank"]),
            int(late["canonicalConsensusRank"]),
            "Early 1st should outrank late 1st",
        )
        self.assertGreater(
            int(early["rankDerivedValue"]),
            int(late["rankDerivedValue"]),
            "Early 1st should have higher value than late 1st",
        )


if __name__ == "__main__":
    unittest.main()
