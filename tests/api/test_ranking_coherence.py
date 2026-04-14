"""Safety rail tests for ranking coherence.

These tests guarantee that rank, value, sort order, tiers, and rendered
rows come from one authoritative dataset without drift.

Hard safety rails:
1. Displayed value order and displayed rank order never diverge.
2. Duplicate ranks never appear for non-identical sort keys.
3. Tier/group boundaries match the final sorted rows.
4. Frontend helper logic cannot override authoritative ordering.
5. Backend stamps canonicalTierId on every ranked row.
"""
from __future__ import annotations

import unittest
from typing import Any

from src.api.data_contract import (
    _compute_unified_rankings,
    _tier_id_from_rank,
    assert_ranking_coherence,
)


def _row(
    name: str,
    position: str,
    *,
    ktc: int | None = None,
    idp: int | None = None,
    dlf: int | None = None,
) -> dict[str, Any]:
    sites: dict[str, int | None] = {
        "ktc": ktc,
        "idpTradeCalc": idp,
        "dlfIdp": dlf,
    }
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": "idp" if position in ("DL", "LB", "DB") else "offense",
        "canonicalSiteValues": sites,
        "values": {"overall": max(v or 0 for v in sites.values()), "rawComposite": None, "finalAdjusted": None, "displayValue": None},
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": False,
    }


class TestMonotonicOrdering(unittest.TestCase):
    """Proof of monotonic ordering: rank strictly increases, value
    monotonically decreases."""

    def test_simple_board_is_monotonic(self):
        rows = [
            _row("Player A", "QB", ktc=9000, idp=9000),
            _row("Player B", "RB", ktc=8000, idp=8000),
            _row("Player C", "WR", ktc=7000, idp=7000),
            _row("Player D", "LB", idp=6000, dlf=999400),
            _row("Player E", "TE", ktc=5000, idp=5000),
        ]
        _compute_unified_rankings(rows, {})
        ranked = [r for r in rows if r.get("canonicalConsensusRank")]
        ranked.sort(key=lambda r: r["canonicalConsensusRank"])

        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], f"Coherence errors: {errors}")

    def test_rank_value_never_diverge(self):
        """If rank A < rank B, then value A >= value B (no inversions)."""
        rows = [
            _row(f"P{i}", "QB", ktc=9999 - i * 100, idp=9999 - i * 100)
            for i in range(20)
        ]
        _compute_unified_rankings(rows, {})
        ranked = sorted(
            [r for r in rows if r.get("canonicalConsensusRank")],
            key=lambda r: r["canonicalConsensusRank"],
        )
        for i in range(len(ranked) - 1):
            a, b = ranked[i], ranked[i + 1]
            self.assertGreaterEqual(
                a["rankDerivedValue"],
                b["rankDerivedValue"],
                f"Value inversion at rank {a['canonicalConsensusRank']} vs {b['canonicalConsensusRank']}",
            )


class TestNoDuplicateRanks(unittest.TestCase):
    """Proof that duplicate ranks are impossible."""

    def test_no_duplicate_ranks(self):
        rows = [
            _row(f"P{i}", "QB", ktc=9999 - i * 50, idp=9999 - i * 50)
            for i in range(50)
        ]
        _compute_unified_rankings(rows, {})
        ranks = [r["canonicalConsensusRank"] for r in rows if r.get("canonicalConsensusRank")]
        self.assertEqual(len(ranks), len(set(ranks)), "Duplicate ranks detected")

    def test_tied_values_get_distinct_ranks(self):
        """Two players with identical source values get distinct ranks
        via the canonicalName tiebreaker."""
        rows = [
            _row("Alpha Player", "QB", ktc=5000, idp=5000),
            _row("Beta Player", "QB", ktc=5000, idp=5000),
        ]
        _compute_unified_rankings(rows, {})
        ranks = [r["canonicalConsensusRank"] for r in rows if r.get("canonicalConsensusRank")]
        self.assertEqual(sorted(ranks), [1, 2], "Tied values should produce ranks 1 and 2")

    def test_tie_policy_alphabetical(self):
        """Tie policy: identical values are broken alphabetically by
        canonicalName (case-insensitive). Lower alpha name gets better rank."""
        rows = [
            _row("Zeta Player", "QB", ktc=5000, idp=5000),
            _row("Alpha Player", "QB", ktc=5000, idp=5000),
        ]
        _compute_unified_rankings(rows, {})
        alpha = next(r for r in rows if r["canonicalName"] == "Alpha Player")
        zeta = next(r for r in rows if r["canonicalName"] == "Zeta Player")
        self.assertLess(
            alpha["canonicalConsensusRank"],
            zeta["canonicalConsensusRank"],
            "Alpha should rank higher than Zeta on identical values",
        )


class TestTierAlignment(unittest.TestCase):
    """Proof that tier headers align with the final sorted rows."""

    def test_tiers_non_decreasing(self):
        """Tier IDs must be non-decreasing when sorted by rank."""
        rows = [
            _row(f"P{i}", "QB", ktc=9999 - i * 80, idp=9999 - i * 80)
            for i in range(100)
        ]
        _compute_unified_rankings(rows, {})
        ranked = sorted(
            [r for r in rows if r.get("canonicalConsensusRank")],
            key=lambda r: r["canonicalConsensusRank"],
        )
        prev_tier = 0
        for r in ranked:
            tier = r.get("canonicalTierId")
            self.assertIsNotNone(tier, f"Row #{r['canonicalConsensusRank']} missing canonicalTierId")
            self.assertGreaterEqual(
                tier, prev_tier,
                f"Tier decreased at rank {r['canonicalConsensusRank']}: {tier} < {prev_tier}",
            )
            prev_tier = tier

    def test_backend_stamps_tier_on_every_ranked_row(self):
        """Every row with a canonicalConsensusRank must also have canonicalTierId."""
        rows = [
            _row("QB1", "QB", ktc=9000, idp=9000),
            _row("RB1", "RB", ktc=8000, idp=8000),
            _row("LB1", "LB", idp=7000, dlf=999300),
        ]
        _compute_unified_rankings(rows, {})
        for r in rows:
            if r.get("canonicalConsensusRank"):
                self.assertIsNotNone(
                    r.get("canonicalTierId"),
                    f"{r['canonicalName']} has rank but no canonicalTierId",
                )

    def test_tier_id_matches_rank_boundaries(self):
        """Verify _tier_id_from_rank matches the documented boundaries."""
        self.assertEqual(_tier_id_from_rank(1), 1)    # Elite
        self.assertEqual(_tier_id_from_rank(12), 1)   # Elite boundary
        self.assertEqual(_tier_id_from_rank(13), 2)   # Blue-Chip start
        self.assertEqual(_tier_id_from_rank(36), 2)   # Blue-Chip boundary
        self.assertEqual(_tier_id_from_rank(37), 3)   # Premium Starter start
        self.assertEqual(_tier_id_from_rank(72), 3)
        self.assertEqual(_tier_id_from_rank(73), 4)
        self.assertEqual(_tier_id_from_rank(120), 4)
        self.assertEqual(_tier_id_from_rank(121), 5)
        self.assertEqual(_tier_id_from_rank(200), 5)
        self.assertEqual(_tier_id_from_rank(201), 6)
        self.assertEqual(_tier_id_from_rank(800), 9)
        self.assertEqual(_tier_id_from_rank(801), 10)


class TestNoFrontendOverride(unittest.TestCase):
    """When backend stamps rank, value, and tier, the frontend must
    not override them.  We verify the backend fields are present and
    complete so the frontend's conditional override never fires."""

    def test_all_backend_fields_present(self):
        """Every ranked row has all authoritative fields stamped."""
        rows = [
            _row("QB1", "QB", ktc=9000, idp=9000),
            _row("RB1", "RB", ktc=7000),
            _row("LB1", "LB", idp=6000, dlf=999400),
        ]
        _compute_unified_rankings(rows, {})
        for r in rows:
            rank = r.get("canonicalConsensusRank")
            if rank is None:
                continue
            # These fields must be present so the frontend never
            # falls back to its own computation.
            self.assertIsNotNone(r.get("rankDerivedValue"), f"#{rank}: missing rankDerivedValue")
            self.assertGreater(r["rankDerivedValue"], 0, f"#{rank}: rankDerivedValue <= 0")
            self.assertIsNotNone(r.get("canonicalTierId"), f"#{rank}: missing canonicalTierId")
            self.assertIsNotNone(r.get("blendedSourceRank"), f"#{rank}: missing blendedSourceRank")
            self.assertIsNotNone(r.get("sourceRanks"), f"#{rank}: missing sourceRanks")


class TestCoherenceOnRealData(unittest.TestCase):
    """Integration test: build the full contract from live data and
    verify coherence end-to-end."""

    def test_live_data_coherence(self):
        """Build the contract from the latest dynasty_data JSON and
        verify the full board passes all coherence checks."""
        import json
        from pathlib import Path

        data_path = Path(__file__).resolve().parents[2] / "exports" / "latest"
        json_files = sorted(data_path.glob("dynasty_data_*.json"), reverse=True)
        if not json_files:
            self.skipTest("No dynasty_data JSON found in exports/latest/")
        with json_files[0].open() as f:
            raw = json.load(f)

        from src.api.data_contract import build_api_data_contract

        contract = build_api_data_contract(raw)
        pa = contract.get("playersArray", [])
        ranked = [r for r in pa if r.get("canonicalConsensusRank")]
        ranked.sort(key=lambda r: r["canonicalConsensusRank"])

        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], f"Coherence errors on live data:\n" + "\n".join(errors[:10]))


if __name__ == "__main__":
    unittest.main()
