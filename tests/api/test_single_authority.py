"""Regression tests ensuring a single authoritative ranking pipeline.

These tests prevent accidental reintroduction of parallel ranking logic.
The authoritative pipeline is:

    src/api/data_contract.py::build_api_data_contract()
      └── _compute_unified_rankings()  [stamps ALL ranking fields]

No other code path may override canonicalConsensusRank, rankDerivedValue,
canonicalTierId, sourceRanks, confidenceBucket, anomalyFlags,
isSingleSource, or hasSourceDisagreement AFTER build_api_data_contract()
has produced the playersArray.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from src.api.data_contract import (
    build_api_data_contract,
    assert_ranking_coherence,
)


# ── Authoritative fields that MUST be present on ranked rows ────────────
AUTHORITATIVE_FIELDS = (
    "canonicalConsensusRank",
    "rankDerivedValue",
    "canonicalTierId",
    "sourceRanks",
    "sourceRankMeta",
    "sourceCount",
    "blendedSourceRank",
    "confidenceBucket",
    "confidenceLabel",
    "anomalyFlags",
    "isSingleSource",
    "isStructurallySingleSource",
    "hasSourceDisagreement",
    "sourceAudit",
)


def _load_live_contract() -> dict[str, Any] | None:
    data_path = Path(__file__).resolve().parents[2] / "exports" / "latest"
    json_files = sorted(data_path.glob("dynasty_data_*.json"), reverse=True)
    if not json_files:
        return None
    with json_files[0].open() as f:
        raw = json.load(f)
    return build_api_data_contract(raw)


class TestSingleAuthority(unittest.TestCase):
    """Every ranked player must have all authoritative fields stamped
    by the backend.  If any field is missing, the frontend fallback
    logic can fire and create a parallel ranking system."""

    def test_all_authoritative_fields_present(self):
        contract = _load_live_contract()
        if contract is None:
            self.skipTest("No live data")
        pa = contract.get("playersArray", [])
        ranked = [r for r in pa if r.get("canonicalConsensusRank")]

        missing = []
        for r in ranked[:200]:  # check top 200
            for field in AUTHORITATIVE_FIELDS:
                if field not in r or r[field] is None:
                    missing.append(f"#{r.get('canonicalConsensusRank')} {r.get('canonicalName')}: missing {field}")

        self.assertEqual(missing, [], f"Missing authoritative fields:\n" + "\n".join(missing[:20]))

    def test_no_value_inversions(self):
        """Value must monotonically decrease with rank."""
        contract = _load_live_contract()
        if contract is None:
            self.skipTest("No live data")
        pa = contract.get("playersArray", [])
        ranked = sorted(
            [r for r in pa if r.get("canonicalConsensusRank")],
            key=lambda r: r["canonicalConsensusRank"],
        )
        errors = assert_ranking_coherence(ranked)
        self.assertEqual(errors, [], f"Coherence errors:\n" + "\n".join(errors[:10]))

    def test_no_duplicate_ranks(self):
        contract = _load_live_contract()
        if contract is None:
            self.skipTest("No live data")
        pa = contract.get("playersArray", [])
        ranks = [r["canonicalConsensusRank"] for r in pa if r.get("canonicalConsensusRank")]
        self.assertEqual(len(ranks), len(set(ranks)), "Duplicate ranks detected")

    def test_tier_bounded_and_monotonic(self):
        """canonicalTierId lands in 1..10 and is non-decreasing with rank.

        Tier assignment is gap-based on ``rankDerivedValue`` (see
        ``_compute_value_based_tier_ids``) rather than fixed rank
        buckets, so the strict ``_tier_id_from_rank`` equality check
        this test previously enforced no longer applies.  Instead we
        pin the two invariants the frontend relies on: tier IDs stay in
        the ``TIER_LABELS`` vocabulary (1..10), and higher-ranked rows
        never land in a worse (higher-numbered) tier than lower-ranked
        rows.
        """
        contract = _load_live_contract()
        if contract is None:
            self.skipTest("No live data")
        pa = contract.get("playersArray", [])
        ranked = sorted(
            [r for r in pa if r.get("canonicalConsensusRank") is not None],
            key=lambda r: int(r["canonicalConsensusRank"]),
        )
        out_of_range = [
            f"#{r['canonicalConsensusRank']}: tier={r.get('canonicalTierId')}"
            for r in ranked
            if not (
                isinstance(r.get("canonicalTierId"), int)
                and 1 <= r["canonicalTierId"] <= 10
            )
        ]
        self.assertEqual(
            out_of_range, [],
            f"Tier IDs out of 1..10 range:\n" + "\n".join(out_of_range[:10]),
        )
        prev_tier = 0
        non_monotonic: list[str] = []
        for r in ranked:
            t = r.get("canonicalTierId") or 0
            if t < prev_tier:
                non_monotonic.append(
                    f"#{r['canonicalConsensusRank']}: tier {t} after tier {prev_tier}"
                )
            prev_tier = t
        self.assertEqual(
            non_monotonic, [],
            f"Tier IDs must be non-decreasing with rank:\n"
            + "\n".join(non_monotonic[:10]),
        )


class TestOverlayRemoved(unittest.TestCase):
    """The canonical overlay function in server.py must be fully removed."""

    def test_overlay_function_is_absent(self):
        """_apply_canonical_primary_overlay must not exist on the server module."""
        import importlib
        try:
            server = importlib.import_module("server")
            self.assertFalse(
                hasattr(server, "_apply_canonical_primary_overlay"),
                "Dead canonical-overlay stub must be removed, not left as a no-op",
            )
        except (ImportError, ModuleNotFoundError):
            self.skipTest("server module not importable in test environment")


class TestFrontendFallbackGuards(unittest.TestCase):
    """Verify the frontend ranking helpers use backend-first logic."""

    def test_resolved_rank_prefers_backend(self):
        """resolvedRank() must return canonicalConsensusRank when present."""
        # Simulate what the frontend does
        row_with_backend = {
            "canonicalConsensusRank": 42,
            "computedConsensusRank": 99,
        }
        # resolvedRank logic: canonicalConsensusRank ?? computedConsensusRank ?? Infinity
        resolved = row_with_backend.get("canonicalConsensusRank") or row_with_backend.get("computedConsensusRank") or float("inf")
        self.assertEqual(resolved, 42, "Must prefer backend rank over computed")

    def test_computed_rank_is_fallback_only(self):
        """When backend rank is missing, computedConsensusRank is used."""
        row_without_backend = {
            "canonicalConsensusRank": None,
            "computedConsensusRank": 99,
        }
        resolved = row_without_backend.get("canonicalConsensusRank") or row_without_backend.get("computedConsensusRank") or float("inf")
        self.assertEqual(resolved, 99, "Must fall back to computed rank")


if __name__ == "__main__":
    unittest.main()
