"""Pinned, reproducible, point-in-time Hill training runs (owner Section D items 2 and 6).

Before this unit a refit pinned only the board snapshot (H9): no code identity,
no dataset-state, freshness, health, coverage, family or population record, no
training cutoff, and nothing that could prove two refits on the same evidence
produce the same challenger. These tests build a small synthetic input tree for
every file the manifest reads, so they are fast and independent of which
sources answered the last scrape.
"""

from __future__ import annotations

import csv
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.model_registry.training_manifest import default_manifest
from src.model_registry.training_run import (
    REQUIRED_PIN_FIELDS,
    SUBSTRATE_VERSION,
    TrainingRunError,
    commit_at_or_before,
    execute,
    is_tournament_eligible,
    materialize_inputs,
)
from src.model_registry.versioning import ModelRegistry, ModelVersion

REPO = Path(__file__).resolve().parents[2]
CUTOFF = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
SNAPSHOT_REL = "exports/latest/dynasty_data_2026-09-30.json"


def _board_values(n: int, top: float, decay: float) -> list[float]:
    return [round(top * (decay**i), 3) for i in range(n)]


def _build_root(
    root: Path, *, scrape_ts: str = "2026-09-30T10:00:00+00:00", bump: float = 0.0
) -> Path:
    manifest = default_manifest()
    written: set[str] = set()
    for b in manifest.boards:
        for rel in b.paths:
            if rel in written:
                continue
            written.add(rel)
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            col = b.value_column or "value"
            with path.open("w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=["name", col])
                w.writeheader()
                for i, v in enumerate(_board_values(120, 9999.0 + bump, 0.97)):
                    w.writerow({"name": f"{Path(rel).stem} Player {i}", col: v})
                # A pick row inside the window: must never train.
                w.writerow({"name": "2027 Early 1st", col: 5000})
    players = {}
    positions = {}
    for i in range(60):
        name = f"Defender {i}"
        players[name] = {"idpTradeCalc": 6000 * (0.95**i)}
        positions[name] = "LB"
    for i in range(30):
        name = f"Rookie {i}"
        players[name] = {
            "_isRookie": True,
            "_canonicalSiteValues": {"ktc": 7000 * (0.93**i), "idpTradeCalc": 6800 * (0.93**i)},
        }
    snap = root / SNAPSHOT_REL
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(
        json.dumps(
            {"scrapeTimestamp": scrape_ts, "players": players, "sleeper": {"positions": positions}}
        ),
        encoding="utf-8",
    )
    return root


def _run(root: Path, **kw):
    kw.setdefault("cutoff", CUTOFF)
    kw.setdefault("code_sha", "testsha")
    kw.setdefault("inputs_origin", "test-tree")
    return execute(root=root, snapshot=root / SNAPSHOT_REL, **kw)


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    return _build_root(tmp_path_factory.mktemp("hill-pins"))


@pytest.fixture(scope="module")
def run_a(tree):
    return _run(tree)


class TestReproducibility:
    def test_two_runs_on_identical_pins_produce_the_same_challenger(self, tree, run_a):
        run_b = _run(tree)
        assert run_b.params == run_a.params
        assert run_b.challenger_hash == run_a.challenger_hash
        assert run_b.record["pinsHash"] == run_a.record["pinsHash"]

    def test_a_copy_of_the_inputs_elsewhere_reproduces_the_hash(self, tmp_path, run_a):
        """Content-addressed: the root's location is not evidence."""
        other = _build_root(tmp_path / "elsewhere")
        assert _run(other).challenger_hash == run_a.challenger_hash

    def test_changed_evidence_changes_the_challenger(self, tmp_path, run_a):
        moved = _build_root(tmp_path / "moved", bump=500.0)
        assert _run(moved).challenger_hash != run_a.challenger_hash

    def test_wall_clock_and_code_sha_label_are_not_evidence(self, tree, run_a):
        again = _run(tree, code_sha="another-label")
        assert again.challenger_hash == run_a.challenger_hash
        assert again.record["codeSha"] == "another-label"


class TestPins:
    def test_every_required_pin_is_recorded(self, run_a):
        missing = [k for k in REQUIRED_PIN_FIELDS if k not in run_a.record]
        assert not missing, missing
        assert run_a.record["substrateVersion"] == SUBSTRATE_VERSION
        assert run_a.record["trainingCutoff"] == CUTOFF.isoformat()

    def test_each_input_carries_hash_family_population_and_state(self, run_a):
        inputs = run_a.record["inputs"]
        assert inputs
        for rel, pin in inputs.items():
            assert len(pin["sha256"]) == 64, rel
            for key in (
                "family",
                "population",
                "liveRole",
                "picksDropped",
                "rowsRead",
                "datasetState",
            ):
                assert key in pin, (rel, key)
            assert pin["population"] == "players_only"

    def test_pick_rows_are_counted_as_dropped(self, run_a):
        ktc = run_a.record["inputs"]["CSVs/site_raw/ktc.csv"]
        assert ktc["picksDropped"] == 1

    def test_scopes_pin_trainers_holdouts_and_their_families(self, run_a):
        off = run_a.record["scopes"]["OFFENSE"]
        assert off["trainers"] and off["holdouts"]
        assert not set(off["trainingFamilies"]) & set(off["holdoutFamilies"])
        assert "FantasyNavigator" in off["excluded"]

    def test_snapshot_is_pinned_by_bytes_and_scrape_time(self, run_a):
        snap = run_a.record["snapshot"]
        assert snap["path"] == SNAPSHOT_REL
        assert len(snap["sha256"]) == 64
        assert snap["scrapeTimestamp"] == "2026-09-30T10:00:00+00:00"

    def test_model_hash_covers_the_emitted_params(self, run_a):
        assert run_a.record["modelHash"] and run_a.record["challengerHash"] == run_a.challenger_hash
        assert set(run_a.params) == {
            "HILL_GLOBAL_PERCENTILE_C",
            "HILL_GLOBAL_PERCENTILE_S",
            "HILL_PERCENTILE_C",
            "HILL_PERCENTILE_S",
            "IDP_HILL_PERCENTILE_C",
            "IDP_HILL_PERCENTILE_S",
            "HILL_ROOKIE_PERCENTILE_C",
            "HILL_ROOKIE_PERCENTILE_S",
        }


class TestPointInTime:
    def test_a_snapshot_scraped_after_the_cutoff_is_refused(self, tmp_path):
        late = _build_root(tmp_path / "late", scrape_ts="2026-09-30T13:00:00+00:00")
        with pytest.raises(TrainingRunError, match="after the training cutoff"):
            _run(late)

    def test_dataset_state_that_changed_after_the_cutoff_is_refused(self, tmp_path):
        root = _build_root(tmp_path / "state")
        state = {
            "schemaVersion": 1,
            "sourceKey": "dynastyDaddySf",
            "health": {"state": "HEALTHY", "errors": [], "warnings": [], "since": None},
            "upstream": {"publishedAt": None, "version": None},
            "subsets": {
                "players": {
                    "lastAnyMeaningfulChangeAt": "2026-09-30T15:00:00Z",
                    "lastBroadDatasetChangeAt": "2026-09-30T15:00:00Z",
                    "rowCount": 120,
                    "rowCountHistory": [120],
                    "changeHistory": [],
                    "fingerprint": "x",
                }
            },
        }
        p = root / "data/scrape_state/dynastyDaddySf_dataset.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(TrainingRunError, match="after the training cutoff"):
            _run(root)

    def test_freshness_is_assessed_at_the_cutoff_not_now(self, tmp_path):
        root = _build_root(tmp_path / "fresh")
        state = {
            "schemaVersion": 1,
            "sourceKey": "dynastyDaddySf",
            "health": {"state": "HEALTHY", "errors": [], "warnings": [], "since": None},
            "upstream": {"publishedAt": None, "version": None},
            "subsets": {
                "players": {
                    "lastAnyMeaningfulChangeAt": "2026-09-29T12:00:00Z",
                    "lastBroadDatasetChangeAt": "2026-09-29T12:00:00Z",
                    "rowCount": 120,
                    "rowCountHistory": [120, 120, 120],
                    "changeHistory": [],
                    "fingerprint": "x",
                }
            },
        }
        p = root / "data/scrape_state/dynastyDaddySf_dataset.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state), encoding="utf-8")
        first = _run(root).record["inputs"]["CSVs/site_raw/dynastyDaddySf.csv"]["datasetState"]
        later_cutoff = _run(root, cutoff=CUTOFF + timedelta(days=30))
        later = later_cutoff.record["inputs"]["CSVs/site_raw/dynastyDaddySf.csv"]["datasetState"]
        assert first["ageHours"] == pytest.approx(24.0, abs=0.01)
        assert later["ageHours"] > first["ageHours"]
        assert first["dataAsOf"] == "2026-09-29T12:00:00+00:00"

    def test_commit_resolution_never_passes_the_cutoff(self):
        head_time = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "HEAD"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        if not head_time:
            pytest.skip("no git history")
        cutoff = datetime.fromisoformat(head_time) - timedelta(days=2)
        sha, when = commit_at_or_before(cutoff, repo=REPO)
        assert when <= cutoff

    def test_materialized_inputs_are_the_commit_bytes(self, tmp_path):
        rel = "src/model_registry/__init__.py"
        materialize_inputs("HEAD", tmp_path, paths=[rel], repo=REPO)
        expected = subprocess.run(
            ["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True
        ).stdout
        assert (tmp_path / rel).read_bytes() == expected


class TestRegistryAndAutopilot:
    def test_a_version_round_trips_its_training_run(self, run_a, tmp_path):
        reg = ModelRegistry("hill_test")
        v = ModelVersion(
            model_id="hill_test",
            version=1,
            params=run_a.params,
            fitted_at="2026-09-30T12:00:00+00:00",
            producer="test",
            training_run=run_a.record,
        )
        reg.add(v)
        reg.save(tmp_path)
        loaded = ModelRegistry.load("hill_test", tmp_path).get(1)
        assert loaded.training_run == run_a.record
        assert loaded.to_dict()["trainingRun"]["challengerHash"] == run_a.challenger_hash

    def test_only_reproducible_current_substrate_challengers_enter_the_tournament(self, run_a):
        base = dict(model_id="m", params=run_a.params, fitted_at="x", producer="p")
        legacy = ModelVersion(version=1, **base)
        current = ModelVersion(version=2, training_run=run_a.record, **base)
        unrepro = ModelVersion(
            version=3, training_run={**run_a.record, "reproducible": False}, **base
        )
        old = ModelVersion(version=4, training_run={**run_a.record, "substrateVersion": 1}, **base)
        assert is_tournament_eligible(current)
        assert not is_tournament_eligible(legacy)
        assert not is_tournament_eligible(unrepro)
        assert not is_tournament_eligible(old)

    def test_autopilot_tournament_skips_legacy_and_duplicate_challengers(self, run_a):
        """A refit on identical pins is the same challenger, not new evidence for the
        parameter-stability gate; a challenger with no pins cannot be reproduced."""
        from scripts.hill_autopilot import tournament_versions

        base = dict(model_id="hill_scope_masters", params=run_a.params, producer="p")
        versions = [
            ModelVersion(version=1, fitted_at="2026-09-01T00:00:00+00:00", **base),
            ModelVersion(
                version=2, fitted_at="2026-09-02T00:00:00+00:00", training_run=run_a.record, **base
            ),
            ModelVersion(
                version=3, fitted_at="2026-09-03T00:00:00+00:00", training_run=run_a.record, **base
            ),
        ]
        eligible, excluded = tournament_versions(versions)
        assert [v.version for v in eligible] == [2]
        assert excluded == {1: "legacy_substrate", 3: "duplicate_of_v2"}

    def test_the_raw_refit_records_its_training_run(self, run_a):
        from scripts.auto_refit_hill_curves import challenger_version

        v = challenger_version(version=9, run=run_a, holdout=None, producer="test")
        assert v.status == "challenger"
        assert v.training_run == run_a.record
        assert v.params == run_a.params
        assert v.training_inputs  # the legacy fingerprint view is still populated

    def test_a_composite_inherits_its_source_training_run(self, run_a):
        from scripts.model_registry import derived_training_run

        src = ModelVersion(
            model_id="m",
            version=5,
            params=run_a.params,
            fitted_at="x",
            producer="p",
            training_run=run_a.record,
        )
        derived = derived_training_run(src)
        assert derived["challengerHash"] == run_a.challenger_hash
        assert derived["composedFrom"] == 5
