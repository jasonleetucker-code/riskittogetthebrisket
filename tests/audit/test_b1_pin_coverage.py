"""The B1 pin set must cover every input the fit actually trains on.

`docs/master-site-audit/evidence/W30/b1_denominator_measure.py` exists so
a challenger-vs-champion comparison can be attributed to model code
rather than to data movement. That guarantee is only as good as its
coverage, and the first version of the script did not have it: it kept a
hand-written parallel list naming 3 of the 6 `OFFENSE_SOURCES`, omitted
the DraftSharks SF/IDP pair that GLOBAL concatenates, and never
identified the board snapshot at all — even though the snapshot supplies
both the position filter and the per-player IDPTradeCalc values behind
the entire IDP scope, and is selected by **mtime**.

These tests fail if a new training source, or a new snapshot dependency,
enters the fit without entering the pin set.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/master-site-audit/evidence/W30/b1_denominator_measure.py"
FITTER = ROOT / "scripts/fit_hill_curve_percentile.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    return module


@pytest.fixture(scope="module")
def evidence():
    return _load(EVIDENCE, "b1_evidence_under_test")


@pytest.fixture(scope="module")
def fitter():
    return _load(FITTER, "b1_fitter_under_test")


class TestFitSourceCoverage:
    def test_every_declared_source_is_pinned(self, evidence, fitter):
        """No source dict entry may sit outside the pin set."""
        pinned = set(evidence.fit_source_files(fitter))
        declared = {
            rel
            for table in (
                fitter.OFFENSE_SOURCES,
                fitter.GLOBAL_SOURCES,
                fitter.IDP_CSV_SOURCES,
            )
            for rel, _col in table.values()
        }
        missing = sorted(declared - pinned)
        assert not missing, f"training sources absent from the B1 pin set: {missing}"

    def test_the_draftsharks_combined_pair_is_pinned(self, evidence, fitter):
        """GLOBAL's combined pool is built in code, not declared in a dict.

        `_load_draftsharks_combined_values` concatenates the SF and IDP
        CSVs, so neither appears in `GLOBAL_SOURCES` and a dict-only
        sweep misses them. That is exactly how draftSharksSf.csv — the
        largest single fit input at ~164 KB — went unpinned.
        """
        pinned = set(evidence.fit_source_files(fitter))
        for rel in ("CSVs/site_raw/draftSharksSf.csv", "CSVs/site_raw/draftSharksIdp.csv"):
            assert rel in pinned, f"{rel} feeds DraftSharks-Combined but is not pinned"

    def test_every_pinned_source_actually_exists(self, evidence, fitter):
        """A pin naming a file that is not there is not a pin."""
        for rel in evidence.fit_source_files(fitter):
            assert (ROOT / rel).is_file(), f"pinned fit source missing from the tree: {rel}"

    def test_the_pin_set_is_derived_not_hardcoded(self):
        """Guard the mechanism, not just today's list.

        A future edit that reintroduces a literal tuple would pass the
        coverage tests above on the day it is written and rot silently
        afterwards, which is the failure this whole file exists for.
        """
        src = EVIDENCE.read_text()
        assert "fitter.OFFENSE_SOURCES" in src
        assert "fitter.GLOBAL_SOURCES" in src
        assert "fitter.IDP_CSV_SOURCES" in src
        assert "FIT_SOURCE_FILES = (" not in src, "the parallel hardcoded list is back"


class TestSnapshotIsPinned:
    def test_the_snapshot_is_resolved_and_hashed(self, evidence, fitter):
        snap = evidence.pin_snapshot(fitter)
        if not snap.get("resolved"):
            pytest.skip(f"no board snapshot available here: {snap.get('reason')}")
        assert snap["path"], "the snapshot must be identified by path"
        assert len(snap["sha256"]) == 64, "the snapshot must be hashed, not just named"
        assert snap["bytes"] > 0
        assert "origin" in snap, "data/ vs exports/latest/ must be recorded"
        assert snap["pinEnvVar"] == fitter.SNAPSHOT_ENV_VAR

    def test_the_fitter_exposes_a_forcing_override(self, fitter, tmp_path, monkeypatch):
        """A refit must be forceable onto an exact snapshot.

        Without this the fit picks by mtime, so a challenger can silently
        train on different data than the champion it is compared with.
        """
        forced = tmp_path / "dynasty_data_9999-01-01.json"
        forced.write_text("{}")
        monkeypatch.setenv(fitter.SNAPSHOT_ENV_VAR, str(forced))
        assert fitter._latest_snapshot() == forced

    def test_a_bad_pin_is_fatal_not_a_silent_fallback(self, fitter, tmp_path, monkeypatch):
        """Falling back would train on data the operator did not name."""
        monkeypatch.setenv(fitter.SNAPSHOT_ENV_VAR, str(tmp_path / "does-not-exist.json"))
        with pytest.raises(SystemExit):
            fitter._latest_snapshot()

    def test_unset_override_keeps_the_default_search(self, fitter, monkeypatch):
        """The pin is additive; default behavior is unchanged."""
        monkeypatch.delenv(fitter.SNAPSHOT_ENV_VAR, raising=False)
        found = fitter._latest_snapshot()
        if found is not None:
            assert found.name.startswith("dynasty_data_")


class TestFitTopNParity:
    def test_canonical_constant_matches_the_fitter_literals(self, evidence):
        """The measurement must not carry its own copy of 400."""
        parity = evidence.fit_top_n_parity()
        assert parity["fitterTruncationLiterals"], "expected truncation literals in the fitter"
        assert parity["inParity"], (
            f"FIT_TOP_N={parity['canonicalFitTopN']} but the fitter truncates at "
            f"{parity['fitterTruncationLiterals']} — the holdout would score a curve "
            "trained on a different pool than it believes"
        )

    def test_the_measurement_imports_the_constant(self):
        src = EVIDENCE.read_text()
        assert "from src.model_registry.holdout import FIT_TOP_N" in src
        assert "fit_top_n = 400" not in src, "the measurement hardcodes 400 again"


class TestHoldoutIntegrity:
    def test_holdout_is_derived_from_the_registry(self, evidence):
        from src.model_registry.holdout import OFFENSE_HOLDOUT_SOURCES

        declared = {rel for rel, _col in OFFENSE_HOLDOUT_SOURCES.values()}
        assert set(evidence.holdout_source_files()) == declared

    def test_no_source_sits_on_both_sides(self, evidence, fitter):
        """A contaminated holdout scores a curve against its own training data."""
        overlap = sorted(
            set(evidence.fit_source_files(fitter)) & set(evidence.holdout_source_files())
        )
        assert not overlap, f"holdout contaminated by training sources: {overlap}"
