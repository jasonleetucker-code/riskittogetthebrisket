"""The registry must not destroy the history it maintains.

B1.2. `load_or_seed_registry` wrapped `ModelRegistry.load()` in a bare
`except RegistryError` and answered by seeding a fresh v1 champion and
calling `save()`. `load()` raises that error for a missing file — the
intended trigger — but ALSO for any structural failure of a file that
exists. The two were indistinguishable, so a registry that merely failed
validation was replaced by a one-version seed, taking every recorded
promotion, rejection and rollback with it.

Not hypothetical. It fired during B1.2: an experimental guard that made
`load()` raise replaced the real three-version registry with a seeded
single-version one inside one test run, and the file had to be restored
from git.

This is the THIRD instance of ARCHITECTURE_HANDOFF invariant 6 — "tools
must not destroy the evidence they maintain" — after the two closure-
harness defects found in Phase A. That invariant's own note says to assume
a third exists.

These tests use a temporary registry directory. `config/model_registry/`
is production state and is asserted untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.model_registry.hill_masters import CONSTANT_NAMES
from src.model_registry.versioning import RegistryError

REPO = Path(__file__).resolve().parents[2]
PROD_REGISTRY = REPO / "config" / "model_registry" / "hill_scope_masters.json"


# ── the registry must not destroy the history it maintains ─────────


class TestAnUnreadableRegistryIsNotAnAbsentOne:
    """`load_or_seed_registry` used to overwrite production on any error.

    It wrapped `load()` in a bare `except RegistryError` and answered by
    seeding a fresh v1 champion and calling `save()`. `load()` raises that
    error for a missing file — the intended trigger — but ALSO for any
    structural failure of an existing one. So a registry that existed and
    merely failed validation was indistinguishable from no registry, and
    the single artifact recording every promotion and rollback decision was
    replaced by a one-version seed.

    Reproduced live during B1.2: a guard that made `load()` raise replaced
    the real three-version registry with a seeded single-version one inside
    one test run, and it had to be restored from git.

    Third instance of ARCHITECTURE_HANDOFF invariant 6 — tools must not
    destroy the evidence they maintain.
    """

    def test_a_corrupt_registry_raises_rather_than_reseeding(self, tmp_path, monkeypatch):
        import src.model_registry.hill_masters as hm

        path = tmp_path / "hill_scope_masters.json"
        # Valid JSON, invalid registry: two champions is a state `_validate`
        # refuses. Deliberately not malformed bytes — the dangerous case is
        # the one that parses.
        version = {
            "modelId": hm.MODEL_ID,
            "params": {n: 0.1 for n in CONSTANT_NAMES},
            "fittedAt": "2026-01-01T00:00:00Z",
            "producer": "test",
            "status": "champion",
        }
        path.write_text(
            json.dumps(
                {
                    "modelId": hm.MODEL_ID,
                    "schemaVersion": 1,
                    "championVersion": 1,
                    "versions": [dict(version, version=1), dict(version, version=2)],
                }
            )
        )
        before = path.read_text()

        with pytest.raises(RegistryError):
            hm.load_or_seed_registry(tmp_path)

        assert path.read_text() == before, (
            "an unreadable registry was overwritten instead of reported; the "
            "promotion history is the thing this file exists to preserve"
        )

    def test_a_genuinely_absent_registry_still_seeds(self, tmp_path):
        import src.model_registry.hill_masters as hm

        reg = hm.load_or_seed_registry(tmp_path)
        assert reg.has_champion
        assert (tmp_path / "hill_scope_masters.json").exists()

    def test_a_seeded_champion_records_that_its_apply_time_is_unknown(self, tmp_path):
        """Seeding records constants that ARE live, at an unrecoverable time.

        `None` would read as "never applied"; a fabricated timestamp would
        be worse. The sentinel says exactly what is known.
        """
        import src.model_registry.hill_masters as hm

        reg = hm.load_or_seed_registry(tmp_path)
        assert reg.champion.applied_at == "UNKNOWN_HISTORICAL_APPLY_TIME"


class TestProductionRegistryIsNotReseeded:
    """The registry must survive the test suite that exercises seeding.

    The invariant is "no test overwrote production with a fresh seed" — NOT
    "the registry has exactly N versions". An earlier version of this test
    asserted the literal list `[1, 2, 3]` and went red the moment the weekly
    refit recorded challenger v4 on `main` (`1430c3023`), which is the
    refit doing exactly what ADR-008 designed it to do. A guard that fails
    on legitimate activity trains people to ignore it, so it is written
    against the destruction signature instead.

    A destroyed registry has an unmistakable shape: exactly one version,
    champion v1, producer "seeded from committed constants". Anything with
    real history is not that, however many challengers have accumulated.
    """

    def test_the_registry_has_not_been_reset_to_a_seed(self):
        blob = json.loads(PROD_REGISTRY.read_text())
        versions = blob.get("versions") or []
        assert len(versions) > 1, (
            "the production registry has collapsed to a single version — this "
            "is the seed shape, which means something reseeded it"
        )
        producers = {(v.get("producer") or "") for v in versions}
        assert any("fit_hill_curve_percentile" in p for p in producers), (
            "no version was produced by a real fit; the registry looks seeded"
        )

    def test_it_still_names_a_champion_with_recorded_history(self):
        blob = json.loads(PROD_REGISTRY.read_text())
        champion = blob.get("championVersion")
        assert champion is not None
        by_version = {v["version"]: v for v in blob.get("versions") or []}
        assert champion in by_version
        assert by_version[champion]["status"] == "champion"
        # The promotion that made it champion must still be recorded — losing
        # that is the specific harm a reseed causes.
        assert by_version[champion].get("promotedAt")

    def test_the_historical_versions_survive(self):
        """v1-v3 are the pre-B1 record. Later versions may legitimately
        accumulate; these three disappearing would mean history was lost."""
        blob = json.loads(PROD_REGISTRY.read_text())
        present = {v["version"] for v in blob.get("versions") or []}
        assert {1, 2, 3} <= present, f"historical versions missing: {sorted({1, 2, 3} - present)}"
