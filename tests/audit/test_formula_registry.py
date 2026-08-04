"""The formula registry must stay true, and duplicates must stay visible.

``docs/audits/formula-registry.json`` records, per numerical CONCEPT, which
implementation is authoritative and which others exist.  Its value is not the
document — it is that a new duplicate implementation of an already-owned
concept shows up as a diff against this file instead of as a bug report
months later.

These tests check the things that can be checked mechanically: the file
parses, every canonical path it names still exists, and the invariants it
claims are actually enforced somewhere.  They deliberately do NOT check that
the prose is accurate — nothing can.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY = _REPO_ROOT / "docs" / "audits" / "formula-registry.json"

_VALID_RISK = {"critical", "high", "medium", "low"}
_VALID_STATUS = {"verified", "corrected", "open-decision", "documented-divergence"}


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(_REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def concepts(registry) -> list[dict]:
    return registry["concepts"]


class TestRegistryShape:
    def test_parses_and_is_non_trivial(self, concepts):
        assert len(concepts) >= 15

    def test_ids_are_unique(self, concepts):
        ids = [c["id"] for c in concepts]
        assert len(ids) == len(set(ids))

    def test_required_fields_present_and_valid(self, concepts):
        for c in concepts:
            for field in ("id", "concept", "canonical", "units", "consumers", "duplicates", "risk", "status"):
                assert field in c, f"{c.get('id')} missing {field}"
            assert c["risk"] in _VALID_RISK, f"{c['id']} has risk={c['risk']}"
            assert c["status"] in _VALID_STATUS, f"{c['id']} has status={c['status']}"

    def test_every_duplicate_states_a_disposition(self, concepts):
        """A duplicate with no disposition is an unanswered question, which is
        the state this registry exists to eliminate."""
        for c in concepts:
            for dup in c["duplicates"]:
                assert dup.get("impl"), f"{c['id']} has a duplicate with no impl"
                assert dup.get("disposition"), f"{c['id']} duplicate {dup['impl']} has no disposition"


class TestNamedFilesExist:
    """Every file the registry points at must still be there.  A rename that
    silently orphans a registry entry is how these documents rot."""

    # ``json`` and ``jsx`` must precede ``js`` in the alternation, or the
    # regex truncates ``foo.json`` to ``foo.js`` and reports a phantom
    # missing file.
    _PATH_RE = re.compile(r"[A-Za-z0-9_./-]+\.(?:json|jsx|js|py)")

    @classmethod
    def _paths(cls, text: str) -> list[str]:
        """Repo-relative paths named in a registry field.

        ``Dynasty Scraper.py`` contains a space, so it is lifted out before
        the token scan rather than being shredded into ``Scraper.py``.
        """
        found: list[str] = []
        rest = text
        if "Dynasty Scraper.py" in rest:
            found.append("Dynasty Scraper.py")
            rest = rest.replace("Dynasty Scraper.py", " ")
        found.extend(cls._PATH_RE.findall(rest))
        return found

    def test_canonical_paths_resolve(self, concepts):
        missing: list[str] = []
        for c in concepts:
            for path in self._paths(c["canonical"]):
                if not (_REPO_ROOT / path).exists():
                    missing.append(f"{c['id']}: {path}")
        assert not missing, f"registry names files that do not exist: {missing}"

    def test_consumer_and_duplicate_paths_resolve(self, concepts):
        missing: list[str] = []
        for c in concepts:
            blobs = list(c["consumers"]) + [d["impl"] for d in c["duplicates"]]
            for blob in blobs:
                for path in self._paths(blob):
                    if not (_REPO_ROOT / path).exists():
                        missing.append(f"{c['id']}: {path}")
        assert not missing, f"registry names files that do not exist: {missing}"


class TestClaimedInvariantsAreEnforced:
    """Spot-check that the registry's load-bearing claims are backed by code,
    not just by prose."""

    def test_value_bundle_scale_contract_is_enforced(self):
        from src.api.data_contract import _player_value_bundle

        bundle = _player_value_bundle({"_composite": 8100, "_finalAdjusted": 8200})
        assert bundle["overall"] is None
        assert bundle["finalAdjusted"] is None
        assert bundle["displayValue"] is None
        assert bundle["rawComposite"] == 8100

    def test_te_conversion_double_count_guard_is_structural(self):
        from src.league_intel.te_premium import convert_te_value

        # from == to must be a no-op, so a second call cannot compound.
        assert convert_te_value(5000.0, from_basis="tepp", to_basis="tepp") == 5000.0

    def test_te_lift_cannot_collapse_distinct_votes(self):
        from src.api.data_contract import _te_lift_under_ceiling

        # The three real uncapped Bowers votes measured on the live CSVs.
        out = [_te_lift_under_ceiling(v) for v in (10975.0, 10130.8, 10057.8)]
        assert len(set(out)) == 3

    def test_nested_windows_are_not_summed_into_the_board_ranking(self):
        """C2's invariant.  ``trend_score`` may still exist for wire
        compatibility, but nothing may RANK by it."""
        service = (_REPO_ROOT / "src" / "intel" / "service.py").read_text(encoding="utf-8")
        for line in service.splitlines():
            if ".sort(" in line or "sorted(" in line:
                assert "trendScore" not in line, f"board still ranks on trendScore: {line.strip()}"
