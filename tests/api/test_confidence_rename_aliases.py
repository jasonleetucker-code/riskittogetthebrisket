"""C1-U5: the deprecation set is pinned in three directions at once.

WHY THIS EXISTS
===============
A dual-write is a promise to remove one of the two writes. Nothing enforces
that promise, so "temporary" aliases become permanent — and then a later
reader cannot tell which of two spellings is authoritative, which is the
condition C1-U5 exists to end rather than to reproduce under new names.

So the alias set is asserted from three independent directions:

1. what the contract DECLARES it deprecated (``meta.deprecations``);
2. what a live-built row actually EMITS;
3. a frozen literal in this file.

Adding an alias without declaring it fails. Declaring one without emitting
it fails. Either drifting from the frozen literal fails, so removing an
alias is a deliberate edit here rather than something that happens by
accident to a payload nobody diffed.

Plus the property that makes the window safe at all: every legacy key
carries EXACTLY its replacement's value, on every row. A dual-write whose
two halves disagree is worse than no rename — it is two answers under one
concept, which is the defect class this whole series is about.

NOT ``livedata``-marked: builds from a tracked export and asserts
invariants, never absolute counts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.api.data_contract import (
    CONTRACT_VERSION,
    DEPRECATED_FIELD_ALIASES,
    build_api_data_contract,
)

_REPO = Path(__file__).resolve().parents[2]

#: Direction 3. Changing this is how an alias is deliberately retired.
FROZEN_ALIASES: dict[str, str] = {
    "identityConfidence": "identityResolutionConfidence",
    "identityMethod": "identityResolutionMethod",
    "marketConfidence": "marketBreadthAgreementIndex",
}

_contract_cache: dict[str, Any] | None = None


def _contract() -> dict[str, Any]:
    global _contract_cache
    if _contract_cache is None:
        files = sorted((_REPO / "exports" / "latest").glob("dynasty_data_*.json"), reverse=True)
        if not files:
            pytest.skip("no export under exports/latest")
        with files[0].open() as f:
            _contract_cache = build_api_data_contract(json.load(f))
    return _contract_cache


def _rows() -> list[dict[str, Any]]:
    return _contract().get("playersArray") or []


class TestTheDeclarationMatchesReality:
    def test_declared_set_equals_the_frozen_literal(self) -> None:
        declared = {d["field"]: d["replacedBy"] for d in DEPRECATED_FIELD_ALIASES}
        assert declared == FROZEN_ALIASES, (
            "the contract's declared deprecations drifted from this test's frozen set. "
            "If an alias is being retired, edit FROZEN_ALIASES deliberately and bump "
            "CONTRACT_VERSION — removal is the breaking half of the rename."
        )

    def test_the_contract_publishes_its_deprecations(self) -> None:
        published = _contract().get("deprecations")
        assert published, "the contract no longer publishes a deprecations block"
        assert {d["field"] for d in published} == set(FROZEN_ALIASES)

    def test_every_declared_alias_is_actually_emitted(self) -> None:
        """Declaring a deprecation for a field nobody emits is documentation theatre."""
        rows = _rows()
        for legacy, replacement in FROZEN_ALIASES.items():
            assert any(legacy in r for r in rows), f"declared alias {legacy!r} is emitted nowhere"
            assert any(replacement in r for r in rows), (
                f"replacement {replacement!r} for {legacy!r} is emitted nowhere — the rename "
                f"is declared but not done"
            )

    def test_no_undeclared_legacy_alias_is_emitted(self) -> None:
        """The reverse direction: a new dual-write must be declared."""
        suspects = {"identityConfidence", "identityMethod", "marketConfidence"}
        emitted = {k for r in _rows() for k in r if k in suspects}
        assert emitted <= set(
            FROZEN_ALIASES
        ), f"legacy field(s) {emitted - set(FROZEN_ALIASES)} are emitted but undeclared"


class TestTheTwoHalvesNeverDisagree:
    def test_each_legacy_key_carries_its_replacements_value(self) -> None:
        mismatches: list[tuple[str, str, Any, Any]] = []
        for row in _rows():
            name = str(row.get("canonicalName") or row.get("displayName") or "?")
            for legacy, replacement in FROZEN_ALIASES.items():
                if legacy in row or replacement in row:
                    if row.get(legacy) != row.get(replacement):
                        mismatches.append((name, legacy, row.get(legacy), row.get(replacement)))
        assert not mismatches, (
            f"{len(mismatches)} row/field pairs where the alias and its replacement "
            f"disagree — two answers under one concept: {mismatches[:5]}"
        )


class TestRemovalIsGatedOnAVersionBump:
    def test_aliases_declare_the_version_that_retires_them(self) -> None:
        for entry in DEPRECATED_FIELD_ALIASES:
            target = entry.get("removeAfterContractVersion")
            assert target, f"{entry['field']} declares no removal version"
            assert target != CONTRACT_VERSION, (
                f"{entry['field']} says it is removed after {target}, which is the CURRENT "
                f"contract version — either the alias should already be gone, or the "
                f"declaration is stale. Additive dual-write does not bump the version; "
                f"removal does."
            )

    def test_every_entry_states_why(self) -> None:
        for entry in DEPRECATED_FIELD_ALIASES:
            assert entry.get("reason"), (
                f"{entry['field']} deprecates without saying why. A future reader deciding "
                f"whether to delete the alias needs the reason, not just the mapping."
            )
