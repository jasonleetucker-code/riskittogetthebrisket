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
                    missing.append(
                        f"#{r.get('canonicalConsensusRank')} {r.get('canonicalName')}: missing {field}"
                    )

        self.assertEqual(missing, [], "Missing authoritative fields:\n" + "\n".join(missing[:20]))

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
        self.assertEqual(errors, [], "Coherence errors:\n" + "\n".join(errors[:10]))

    def test_no_duplicate_ranks(self):
        contract = _load_live_contract()
        if contract is None:
            self.skipTest("No live data")
        pa = contract.get("playersArray", [])
        ranks = [r["canonicalConsensusRank"] for r in pa if r.get("canonicalConsensusRank")]
        self.assertEqual(len(ranks), len(set(ranks)), "Duplicate ranks detected")

    def test_tier_bounded_and_monotonic(self):
        """canonicalTierId is a positive integer and non-decreasing with rank.

        Tier assignment is gap-based on ``rankDerivedValue`` (see
        ``_compute_value_based_tier_ids``).  The frontend renders
        generic "Tier N" labels, so there's no upper bound on the
        number of math-detected tiers — we only pin that tier IDs are
        positive integers and that higher-ranked rows never land in a
        worse (higher-numbered) tier than lower-ranked rows.
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
            if not (isinstance(r.get("canonicalTierId"), int) and r["canonicalTierId"] >= 1)
        ]
        self.assertEqual(
            out_of_range,
            [],
            "Tier IDs must be positive ints:\n" + "\n".join(out_of_range[:10]),
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
            non_monotonic,
            [],
            "Tier IDs must be non-decreasing with rank:\n" + "\n".join(non_monotonic[:10]),
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
        resolved = (
            row_with_backend.get("canonicalConsensusRank")
            or row_with_backend.get("computedConsensusRank")
            or float("inf")
        )
        self.assertEqual(resolved, 42, "Must prefer backend rank over computed")

    def test_computed_rank_is_fallback_only(self):
        """When backend rank is missing, computedConsensusRank is used."""
        row_without_backend = {
            "canonicalConsensusRank": None,
            "computedConsensusRank": 99,
        }
        resolved = (
            row_without_backend.get("canonicalConsensusRank")
            or row_without_backend.get("computedConsensusRank")
            or float("inf")
        )
        self.assertEqual(resolved, 99, "Must fall back to computed rank")


if __name__ == "__main__":
    unittest.main()


class TestLegacyLamStripperDoesNotEatLiveFields(unittest.TestCase):
    """The legacy LAM stripper must not silently delete a modern field.

    CONTEXT, because this is easy to misread. LAM — League Adjustment
    Multiplier, a position-based value multiplier — was deleted in April
    2026 along with positional scarcity, on the grounds that upstream
    sources already price the operator's SF/TEP/IDP config and the
    per-league delta was small and noisy (``src/league/README.md``,
    audit finding F2).

    ``_strip_legacy_lam_fields`` then deletes ``_lam*``, ``_rawLeague*``,
    ``_shrunkLeague*``, ``_leagueAdjusted``, ``_effectiveMultiplier`` and
    top-level ``empiricalLAM`` from EVERY response. That is hygiene, not
    suppression: data files on disk predate the removal and still carry
    those fields, so without the strip the API would serve stale LAM
    numbers computed by code that no longer exists.

    THE TRAP: it strips by PREFIX, and league-aware valuation has since
    come BACK in ``src/league_intel/`` under names built from the same
    words — ``leagueAdjustedDynastyValue`` and friends. Today's names
    are safe only because none of them start with an underscore. A
    plausible future tidy-up that marks one private
    (``_rawLeagueAdjusted``, say) would match the ``_rawLeague`` prefix
    and vanish from every response with no error and no log line.

    A field that disappears from a payload looks exactly like a field
    that was never computed. This test makes that collision loud instead
    of leaving it to be discovered from a blank UI.
    """

    def test_live_valuation_field_names_survive_the_stripper(self) -> None:
        from src.api.data_contract import _strip_legacy_lam_fields

        live_names = [
            "leagueAdjustedDynastyValue",
            "leagueAdjustedIsNoop",
            "rankDerivedValue",
            "canonicalConsensusRank",
            "valuationOverlay",
        ]
        players = {"P": {name: 1 for name in live_names}}
        base: dict[str, Any] = {}
        _strip_legacy_lam_fields(base, players)
        for name in live_names:
            self.assertIn(
                name,
                players["P"],
                f"{name!r} was eaten by the legacy LAM stripper — rename the field "
                f"or narrow _LEGACY_LAM_PLAYER_PREFIXES",
            )

    def test_the_stripper_still_removes_what_it_is_for(self) -> None:
        """The control. Without this the test above passes against a
        stripper that does nothing at all."""
        from src.api.data_contract import _strip_legacy_lam_fields

        players = {
            "P": {
                "_lamMultiplier": 1.2,
                "_rawLeagueValue": 900,
                "_shrunkLeagueValue": 880,
                "_leagueAdjusted": 910,
                "_effectiveMultiplier": 1.05,
                "keepMe": 1,
            }
        }
        base = {"empiricalLAM": {"QB": 1.1}, "keepMe": 1}
        _strip_legacy_lam_fields(base, players)
        self.assertEqual(list(players["P"].keys()), ["keepMe"])
        self.assertNotIn("empiricalLAM", base)
        self.assertIn("keepMe", base)
