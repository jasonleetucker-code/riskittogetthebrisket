"""Tests for the normalization validator."""

from __future__ import annotations

import logging

from src.canonical import normalization_validator as nv


def test_valid_contract_reports_healthy():
    contract = {
        "playersArray": [
            {
                "displayName": "Josh Allen",
                "canonicalName": "Josh Allen",
                "position": "QB",
                "assetClass": "offense",
            },
            {
                "displayName": "2027 Mid 4th",
                "canonicalName": "2027 Mid 4th",
                "position": "PICK",
                "assetClass": "pick",
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is True
    assert result["playersArray"]["total"] == 2


def test_detects_display_canonical_drift(caplog):
    contract = {
        "playersArray": [
            {
                "displayName": "Joshua Allen",
                "canonicalName": "Josh Allen",
                "position": "QB",
                "assetClass": "offense",
            },
        ],
    }
    with caplog.at_level(logging.WARNING):
        result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["playerNameDrift"] == 1
    # Structured log line emitted.
    assert any("normalization_mismatch=player_name_drift" in rec.message for rec in caplog.records)


def test_detects_malformed_pick_name():
    contract = {
        "playersArray": [
            {
                "displayName": "not a real pick",
                "canonicalName": "not a real pick",
                "position": "PICK",
                "assetClass": "pick",
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["pickNameMalformed"] == 1


def test_detects_asset_class_mismatch():
    contract = {
        "playersArray": [
            {
                "displayName": "Josh Allen",
                "canonicalName": "Josh Allen",
                "position": "QB",
                "assetClass": "idp",  # wrong — QB is offense
            },
        ],
    }
    result = nv.validate_contract(contract)
    assert result["healthy"] is False
    assert result["playersArray"]["assetClassMismatch"] == 1


def test_detects_duplicate_keys():
    contract = {
        "playersArray": [
            {"displayName": "Josh Allen", "position": "QB", "assetClass": "offense"},
            {"displayName": "Josh Allen", "position": "QB", "assetClass": "offense"},
        ],
    }
    result = nv.validate_contract(contract)
    assert result["playersArray"]["dupKeys"] == 1


def test_sample_cap_limits_output_size():
    contract = {
        "playersArray": [
            {
                "displayName": f"Bad {i}",
                "canonicalName": f"Real {i}",
                "position": "QB",
                "assetClass": "offense",
            }
            for i in range(50)
        ],
    }
    result = nv.validate_contract(contract)
    assert len(result["playersArray"]["samples"]) <= 20


def test_valid_pick_patterns_accepted():
    names = [
        "2027 Mid 4th",
        "2026 Early 1st",
        "2027 Late 6th",
        "2026 Pick 1.01",
        "2027 Pick 2.12",
        "2026 1st Round",
        "2027 4th Round",
    ]
    for name in names:
        assert nv.is_valid_pick_name(name), name


def test_invalid_pick_patterns_rejected():
    for name in ["", "2027 4th", "Josh Allen", "just garbage", "2027"]:
        assert not nv.is_valid_pick_name(name), name


def test_empty_contract_is_healthy():
    assert nv.validate_contract({})["healthy"] is True
    assert nv.validate_contract(None)["healthy"] is True


def test_malformed_rows_dont_crash():
    contract = {"playersArray": [None, "garbage", 42, {}]}
    result = nv.validate_contract(contract)
    # Counter doesn't advance for non-dict rows.
    assert result["playersArray"]["total"] == 1  # only {} counts


def test_legacy_dict_shape_validated():
    contract = {
        "players": {
            "Josh Allen": {"_canonicalName": "Joshua Allen"},  # drift
        },
    }
    result = nv.validate_contract(contract)
    assert result["playersDict"]["playerNameDrift"] == 1


# ── AUDIT F-27 ──────────────────────────────────────────────────────────────
# A health check that is always red is not a health check.
#
# `normalizationHealth.healthy` was **false in production** from the day C1-U6
# shipped until 2026-08-18, because this validator carried its own pick-name
# grammar and that grammar predated the GENERIC grade. Measured on the live
# board: `pickNameMalformed = 18` — 2027/2028/2029 x rounds 1-6, every one a
# deliberate canonical row — while `playerNameDrift`, `assetClassMismatch` and
# `dupKeys` were all 0. Nothing was wrong with the board.
#
# These tests pin the two halves of the repair: the canonical shapes come from
# the pick-identity owner (so they cannot drift out of sync again), and the
# legacy display shape is still accepted (so the repair did not quietly
# tighten the check while claiming to widen it).


class TestPickNameGrammarDelegatesToTheIdentityOwner:
    """C1-ID-02: pick identity has ONE owner. This module is a consumer."""

    def test_generic_grade_rows_are_valid(self) -> None:
        """The exact 18 rows that were false-flagged in production."""
        from src.canonical.normalization_validator import is_valid_pick_name

        for year in (2027, 2028, 2029):
            for rnd in range(1, 7):
                name = f"{year} Round {rnd}"
                assert is_valid_pick_name(name), (
                    f"{name!r} is the C1-U6 GENERIC grade — a canonical row this "
                    "board publishes. Flagging it makes normalizationHealth "
                    "permanently false on a correct board (F-27)."
                )

    def test_tier_and_slot_grades_are_still_valid(self) -> None:
        from src.canonical.normalization_validator import is_valid_pick_name

        assert is_valid_pick_name("2027 Early 1st")
        assert is_valid_pick_name("2026 Mid 4th")
        assert is_valid_pick_name("2026 Pick 1.01")

    def test_legacy_display_shape_is_still_accepted(self) -> None:
        """The owner does not MINT this shape, so delegating outright would
        newly flag any surviving legacy row. Widening a health check is a
        repair; silently tightening one is a regression in a repair's clothes.
        """
        from src.canonical.normalization_validator import is_valid_pick_name

        assert is_valid_pick_name("2026 1st Round")

    def test_genuine_nonsense_is_still_rejected(self) -> None:
        """The repair must not have turned the check off."""
        from src.canonical.normalization_validator import is_valid_pick_name

        for bad in ("2027 Round 7", "2027 Round 0", "Ja'Marr Chase", "", "   ", "Round 1"):
            assert not is_valid_pick_name(bad), f"{bad!r} should not validate as a pick name"

    def test_canonical_shapes_are_not_restated_locally(self) -> None:
        """Structural: the accepted canonical grammar must come from the owner.

        A future edit that re-adds a local tier/slot/generic regex would pass
        every behavioural test above while restoring the duplicate ownership
        that caused F-27 in the first place.
        """
        from pathlib import Path

        src = Path("src/canonical/normalization_validator.py").read_text(encoding="utf-8")
        assert "picks.parse_board_pick_name" in src, (
            "the canonical pick-name grammar must be resolved through "
            "src.identity.picks, not restated here (C1-ID-02)"
        )
        for restated in ("Early|Mid|Late", r"Pick\s+[1-6]", r"Round\s+([1-6])"):
            assert restated not in src, (
                f"{restated!r} looks like a locally restated canonical pick "
                "grammar — that duplicate ownership is exactly what F-27 was"
            )
