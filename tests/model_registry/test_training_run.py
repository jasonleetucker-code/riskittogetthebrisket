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
import os
import subprocess
import sys
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
                for i, v in enumerate(_board_values(60, 9999.0 + bump, 0.95)):
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

    def test_checkout_line_endings_are_not_evidence(self, tmp_path, run_a):
        """A Windows checkout (core.autocrlf) holds CRLF where git and CI hold LF.

        Measured on the first LOCAL demo: the worktree run and its own git replay
        disagreed because the snapshot and every dataset-state JSON were CRLF on
        disk. The pin is of content, not of a checkout policy."""
        crlf = _build_root(tmp_path / "crlf")
        for path in [crlf / SNAPSHOT_REL, *(crlf / "CSVs/site_raw").glob("*.csv")]:
            path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        assert _run(crlf).challenger_hash == run_a.challenger_hash

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
        as_of = datetime.fromisoformat(first["dataAsOf"].replace("Z", "+00:00"))
        assert as_of == datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)

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

    def test_a_challenger_fitted_under_other_code_or_manifest_is_excluded_not_fatal(self, run_a):
        """A forward-persisted winner fitted before a fit-code or manifest change
        cannot be verified by today's code; it is excluded (stale) so the
        scheduled refit stays live instead of failing verify every run."""
        from src.model_registry.training_run import (
            REASON_STALE_CODE_OR_MANIFEST,
            tournament_exclusion_reason,
        )

        base = dict(model_id="m", params=run_a.params, fitted_at="x", producer="p")
        v = ModelVersion(version=7, training_run=run_a.record, **base)
        code, manifest = run_a.record["codeHash"], run_a.record["manifestHash"]
        assert tournament_exclusion_reason(v, current_identity=(code, manifest)) != (
            REASON_STALE_CODE_OR_MANIFEST
        )
        assert (
            tournament_exclusion_reason(v, current_identity=("other-code", manifest))
            == REASON_STALE_CODE_OR_MANIFEST
        )
        assert (
            tournament_exclusion_reason(v, current_identity=(code, "other-manifest"))
            == REASON_STALE_CODE_OR_MANIFEST
        )

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

    def test_the_raw_refit_records_its_training_run(self, run_a, tmp_path):
        """The registry carries the compact summary; the full record is a committed
        artifact that round-trips exactly (review finding 7)."""
        from scripts.auto_refit_hill_curves import challenger_version
        from src.model_registry.training_run import (
            artifact_rel_path,
            load_training_run,
            summarize_run,
        )

        v = challenger_version(
            version=9, run=run_a, holdout=None, producer="test", registry_dir=tmp_path
        )
        assert v.status == "challenger"
        rel = artifact_rel_path(run_a.challenger_hash)
        assert v.training_run == summarize_run(run_a.record, artifact=rel)
        assert (tmp_path / rel).is_file()
        assert load_training_run(v.training_run, registry_dir=tmp_path) == run_a.record
        assert v.params == run_a.params
        assert v.training_inputs  # the legacy fingerprint view is still populated

    def test_a_composite_carries_its_source_pins_but_its_own_model_hash(self, run_a):
        """Review finding 5: the composite's non-OFFENSE params are the incumbent's,
        so inheriting the raw winner's modelHash/challengerHash was a false claim."""
        from scripts.model_registry import derived_training_run
        from src.model_registry.training_run import model_hash

        src = ModelVersion(
            model_id="m",
            version=5,
            params=run_a.params,
            fitted_at="x",
            producer="p",
            training_run=run_a.record,
        )
        composite = {**run_a.params, "IDP_HILL_PERCENTILE_C": 0.123}
        derived = derived_training_run(src, composite)
        assert derived["composedFrom"] == 5
        assert derived["pinsHash"] == run_a.record["pinsHash"]
        assert derived["sourceChallengerHash"] == run_a.challenger_hash
        assert derived["sourceModelHash"] == run_a.record["modelHash"]
        assert derived["modelHash"] == model_hash(composite) != run_a.record["modelHash"]
        assert derived["challengerHash"] != run_a.challenger_hash


# ── PR #1588 independent-review fixes ────────────────────────────────────────


def _version(n, record, *, status="challenger", fitted_at="2026-09-30T12:00:00+00:00", params=None):
    return ModelVersion(
        model_id="hill_scope_masters",
        version=n,
        params=dict(params or {}),
        fitted_at=fitted_at,
        producer="p",
        status=status,
        training_run=record,
    )


class TestManifestIsLazy:
    """Finding 1: ``data_contract`` imports ``src.model_registry`` outside any try
    on every ``/api/data`` build; building the manifest at import meant one future
    registry edit that made ``build_manifest`` raise would crash every build."""

    def test_importing_the_package_with_a_raising_manifest_does_not_raise(self):
        code = "\n".join(
            [
                "import src.model_registry.training_manifest as tm",
                "def boom(*a, **k):",
                "    raise tm.ManifestError('a registry edit broke the manifest')",
                "tm.build_manifest = boom",
                "tm.default_manifest = boom",
                "import src.model_registry as pkg",
                "from src.model_registry import ModelRegistry, RegistryError",
                "import src.model_registry.holdout as ho",
                "try:",
                "    ho.OFFENSE_HOLDOUT_SOURCES",
                "except tm.ManifestError:",
                "    print('LAZY-OK')",
                "else:",
                "    print('NOT-LAZY')",
            ]
        )
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=REPO,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONUTF8": "1"},
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip().splitlines()[-1] == "LAZY-OK"

    def test_the_tables_still_resolve_by_name(self):
        from src.model_registry import holdout

        m = default_manifest()
        assert holdout.OFFENSE_HOLDOUT_SOURCES == m.csv_table("OFFENSE", "holdout")
        assert holdout.offense_training_sources() == m.csv_table("OFFENSE", "train")
        with pytest.raises(AttributeError):
            holdout.NOT_A_TABLE  # noqa: B018


class TestEvidenceDedup:
    """Finding 2: ``challengerHash`` includes the cutoff and cutoff-relative ages,
    so dedup on it never fired and identical-data refits counted as independent."""

    def test_identical_inputs_at_different_cutoffs_are_one_observation(self, tree, run_a):
        from scripts.hill_autopilot import tournament_versions

        later = _run(tree, cutoff=CUTOFF + timedelta(hours=6))
        assert later.challenger_hash != run_a.challenger_hash  # identity differs
        assert later.record["evidenceHash"] == run_a.record["evidenceHash"]  # evidence does not
        eligible, excluded = tournament_versions(
            [_version(2, run_a.record), _version(3, later.record)]
        )
        assert [v.version for v in eligible] == [2]
        assert excluded == {3: "duplicate_of_v2"}

    def test_a_holdout_file_change_is_not_new_training_evidence(self, tmp_path, run_a):
        root = _build_root(tmp_path / "holdout-moved")
        otc = root / default_manifest().board("OFFENSE", "OTCFFB").paths[0]
        otc.write_text(otc.read_text(encoding="utf-8").replace("9999.0", "9000.0"), "utf-8")
        again = _run(root)
        assert again.record["pinsHash"] != run_a.record["pinsHash"]
        assert again.record["evidenceHash"] == run_a.record["evidenceHash"]

    def test_changed_trainer_content_is_new_evidence(self, tmp_path, run_a):
        from scripts.hill_autopilot import tournament_versions

        moved = _run(_build_root(tmp_path / "trainer-moved", bump=500.0))
        assert moved.record["evidenceHash"] != run_a.record["evidenceHash"]
        eligible, _ = tournament_versions([_version(2, run_a.record), _version(3, moved.record)])
        assert [v.version for v in eligible] == [2, 3]

    def test_evidence_hash_is_recomputable_from_the_record(self, run_a):
        from src.model_registry.training_run import run_evidence_hash

        stripped = {k: v for k, v in run_a.record.items() if k != "evidenceHash"}
        assert run_evidence_hash(stripped) == run_a.record["evidenceHash"]


class TestCutoffRouting:
    """Finding 3: ``--cutoff`` without ``--replay-commit`` fitted HEAD's tree while
    recording an earlier cutoff with ``reproducible: true``."""

    def test_a_cutoff_before_head_is_replayed_from_git(self, monkeypatch):
        import scripts.auto_refit_hill_curves as ar

        calls: list[dict] = []
        monkeypatch.setattr(ar, "commit_time", lambda _ref: CUTOFF + timedelta(days=1))
        monkeypatch.setattr(ar, "replay", lambda **kw: calls.append(kw) or "REPLAYED")

        def _no_tree_fit(**_kw):
            raise AssertionError("HEAD's tree must not be fitted for an earlier cutoff")

        monkeypatch.setattr(ar, "execute", _no_tree_fit)
        assert ar.run_training(cutoff=CUTOFF) == "REPLAYED"
        assert calls == [{"cutoff": CUTOFF}]

    def test_a_cutoff_at_or_after_head_fits_the_clean_tree(self, monkeypatch):
        import scripts.auto_refit_hill_curves as ar
        import src.model_registry.hill_masters as hm

        head_time = CUTOFF - timedelta(hours=1)
        seen: dict = {}
        monkeypatch.setattr(ar, "commit_time", lambda _ref: head_time)
        monkeypatch.setattr(ar, "worktree_inputs_state", lambda **_k: ("abc", True, head_time))
        monkeypatch.setattr(hm, "_resolve_fit_snapshot", lambda _f: None)
        monkeypatch.setattr(hm, "_fitter_module", lambda: None)
        monkeypatch.setattr(ar, "replay", lambda **_k: pytest.fail("no replay expected"))
        monkeypatch.setattr(ar, "execute", lambda **kw: seen.update(kw) or "TREE")
        assert ar.run_training(cutoff=CUTOFF) == "TREE"
        assert seen["cutoff"] == CUTOFF and seen["reproducible"] is True

    def test_a_naive_cutoff_is_refused(self):
        import scripts.auto_refit_hill_curves as ar

        with pytest.raises(TrainingRunError, match="timezone-aware"):
            ar.run_training(cutoff=CUTOFF.replace(tzinfo=None))


class TestMissingColumnIsNotZero:
    """Finding 4: a renamed vendor column read as 0.0 on every row ("nonpositive"),
    the trainer was skipped, and the master still entered the tournament."""

    def test_the_loader_raises_on_an_absent_column(self, tmp_path):
        from src.model_registry.training_manifest import MissingColumnError, load_board_values

        path = tmp_path / "renamed.csv"
        path.write_text("name,value_v2\nA,10\nB,9\n", encoding="utf-8")
        with pytest.raises(MissingColumnError) as err:
            load_board_values(path, "value")
        assert err.value.column == "value"
        # A present column with an empty cell is still a row-level non-positive.
        path.write_text("name,value\nA,10\nB,\n", encoding="utf-8")
        assert load_board_values(path, "value").nonpositive_dropped == 1

    @pytest.fixture(scope="class")
    def renamed_run(self, tmp_path_factory):
        root = _build_root(tmp_path_factory.mktemp("renamed"))
        rel = default_manifest().board("OFFENSE", "DynastyDaddy").paths[0]
        path = root / rel
        path.write_text(
            path.read_text(encoding="utf-8").replace("name,value", "name,value_v2", 1), "utf-8"
        )
        return rel, _run(root)

    def test_a_skipped_declared_trainer_makes_the_scope_non_promotable(self, renamed_run):
        rel, run = renamed_run
        offense = run.record["scopes"]["OFFENSE"]
        assert offense["fitSkipped"] == {"DynastyDaddy": "missing_column:value"}
        assert offense["promotable"] is False
        assert offense["nonPromotableReasons"] == [
            "declared_trainer_skipped:DynastyDaddy:missing_column:value"
        ]
        pin = run.record["inputs"][rel]
        assert pin["missingColumn"] == "value"
        assert pin["rowsRead"] is None and pin["picksDropped"] is None

    def test_it_cannot_enter_the_tournament(self, renamed_run, run_a):
        from scripts.hill_autopilot import tournament_versions
        from src.model_registry.training_run import offense_promotable

        _rel, run = renamed_run
        assert offense_promotable(run.record)[0] is False
        assert offense_promotable(run_a.record) == (True, [])
        eligible, excluded = tournament_versions([_version(2, run.record)])
        assert eligible == []
        assert excluded[2].startswith("offense_not_promotable:declared_trainer_skipped:")

    def test_unrecorded_promotability_fails_closed(self, run_a):
        from src.model_registry.training_run import tournament_exclusion_reason

        record = {**run_a.record, "scopes": {}}
        assert tournament_exclusion_reason(_version(2, record)).startswith(
            "offense_not_promotable:promotability_unrecorded"
        )

    def test_a_holdout_with_an_absent_column_is_skipped_with_the_reason(self, tmp_path):
        from src.model_registry.holdout import evaluate_offense_master

        def _csv(name, col):
            lines = [f"name,{col}"] + [f"P{i},{9999 * 0.99**i:.2f}" for i in range(150)]
            (tmp_path / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

        _csv("good.csv", "value")
        _csv("renamed.csv", "value_v2")
        result = evaluate_offense_master(
            0.03,
            1.5,
            repo_root=tmp_path,
            holdout_sources={"Good": ("good.csv", "value"), "Renamed": ("renamed.csv", "value")},
            training_sources={"T": ("train.csv", "value")},
        )
        assert result.skipped == {"Renamed": "missing_column:value"}
        assert set(result.per_source) == {"Good"}


class TestCompositeVerification:
    """Finding 5: composites inherited the raw winner's hashes, ``verify`` compared
    only hashes, and a composite could compete in later tournaments."""

    def test_verify_compares_parameters_not_only_hashes(self, run_a):
        from src.model_registry.training_run import verify_against_replay

        assert verify_against_replay(run_a.params, run_a.record, run_a) == []
        tampered = {**run_a.params, "HILL_PERCENTILE_C": run_a.params["HILL_PERCENTILE_C"] + 0.01}
        problems = verify_against_replay(tampered, run_a.record, run_a)
        assert any("modelHash" in p for p in problems)
        assert any("params differ" in p and "HILL_PERCENTILE_C" in p for p in problems)

    def test_a_composite_verifies_its_source_and_its_offense_pair(self, run_a):
        from src.model_registry.training_run import compose_run_summary, verify_against_replay

        composite = {**run_a.params, "IDP_HILL_PERCENTILE_C": 0.123}
        summary = compose_run_summary(run_a.record, source_version=5, params=composite)
        assert verify_against_replay(composite, summary, run_a) == []
        moved = {**composite, "HILL_PERCENTILE_S": composite["HILL_PERCENTILE_S"] + 0.1}
        drifted = compose_run_summary(run_a.record, source_version=5, params=moved)
        problems = verify_against_replay(moved, drifted, run_a)
        assert problems and "HILL_PERCENTILE_S" in problems[-1]

    def test_a_composite_never_enters_the_tournament(self, run_a):
        from scripts.hill_autopilot import tournament_versions
        from src.model_registry.training_run import compose_run_summary

        summary = compose_run_summary(run_a.record, source_version=5, params=run_a.params)
        eligible, excluded = tournament_versions([_version(9, summary)])
        assert eligible == [] and excluded == {9: "composite_not_a_fit"}


class TestRunArtifacts:
    """Finding 7: ~15 KB per record x 12/day in one registry file. The registry
    keeps a compact summary; the full record is a committed, integrity-checked
    artifact with retention."""

    def test_round_trip_through_the_registry(self, run_a, tmp_path):
        from src.model_registry.training_run import (
            REQUIRED_PIN_FIELDS,
            load_training_run,
            write_run_artifact,
        )

        summary = write_run_artifact(run_a.record, registry_dir=tmp_path)
        reg = ModelRegistry("hill_scope_masters")
        reg.add(_version(1, summary, params=run_a.params))
        path = reg.save(tmp_path)
        loaded = ModelRegistry.load("hill_scope_masters", tmp_path).get(1)
        assert loaded.training_run == summary
        assert (
            "inputs"
            not in json.loads(path.read_text(encoding="utf-8"))["versions"][0]["trainingRun"]
        )
        assert len(json.dumps(summary)) < 4096
        full = load_training_run(loaded.training_run, registry_dir=tmp_path)
        assert full == run_a.record
        assert all(k in full for k in REQUIRED_PIN_FIELDS)
        # verify needs only the summary: the replay pins live there.
        for key in ("inputsCommit", "trainingCutoff", "pinsHash", "challengerHash", "modelHash"):
            assert key in summary
        assert summary["snapshot"]["path"] == SNAPSHOT_REL

    def test_a_tampered_artifact_is_refused(self, run_a, tmp_path):
        from src.model_registry.training_run import load_training_run, write_run_artifact

        summary = write_run_artifact(run_a.record, registry_dir=tmp_path)
        path = tmp_path / summary["artifact"]
        blob = json.loads(path.read_text(encoding="utf-8"))
        blob["config"]["fitTopN"] = 999
        path.write_text(json.dumps(blob), encoding="utf-8")
        with pytest.raises(TrainingRunError, match="pinsHash"):
            load_training_run(summary, registry_dir=tmp_path)

    def test_a_composite_loads_its_source_artifact(self, run_a, tmp_path):
        from src.model_registry.training_run import (
            compose_run_summary,
            load_training_run,
            write_run_artifact,
        )

        summary = write_run_artifact(run_a.record, registry_dir=tmp_path)
        composite = {**run_a.params, "IDP_HILL_PERCENTILE_C": 0.123}
        derived = compose_run_summary(summary, source_version=5, params=composite)
        full = load_training_run(derived, registry_dir=tmp_path)
        assert full["inputs"] == run_a.record["inputs"]
        assert full["composedFrom"] == 5 and full["modelHash"] == derived["modelHash"]

    def test_retention_keeps_what_can_still_matter(self, run_a, tmp_path):
        from src.model_registry.training_run import TRAINING_RUNS_DIRNAME, prune_training_runs

        runs = tmp_path / TRAINING_RUNS_DIRNAME
        runs.mkdir()
        for name in ("live", "old_rejected", "new_rejected", "orphan", "composite_src"):
            (runs / f"{name}.json").write_text("{}", encoding="utf-8")

        def ref(name):
            return {"artifact": f"{TRAINING_RUNS_DIRNAME}/{name}.json"}

        now = datetime(2026, 10, 1, tzinfo=timezone.utc)
        versions = [
            _version(1, ref("live"), fitted_at="2026-01-01T00:00:00+00:00"),
            _version(2, ref("old_rejected"), status="rejected", fitted_at="2026-08-01T00:00:00Z"),
            _version(3, ref("new_rejected"), status="rejected", fitted_at="2026-09-25T00:00:00Z"),
            _version(4, ref("composite_src"), status="rejected", fitted_at="2026-08-01T00:00:00Z"),
            _version(5, {**ref("composite_src"), "composedFrom": 4}, status="champion"),
            _version(6, None),
        ]
        removed = prune_training_runs(versions, registry_dir=tmp_path, now=now, max_age_days=30)
        assert removed == [
            f"{TRAINING_RUNS_DIRNAME}/old_rejected.json",
            f"{TRAINING_RUNS_DIRNAME}/orphan.json",
        ]
        assert sorted(p.stem for p in runs.glob("*.json")) == [
            "composite_src",
            "live",
            "new_rejected",
        ]


class TestReplayRefusals:
    def test_replay_refuses_a_commit_with_no_snapshot(self, monkeypatch, tmp_path):
        """Finding 9: no snapshot at the commit must not fall through to the
        operator's ``RISKIT_FIT_SNAPSHOT``."""
        import src.model_registry.training_run as tr

        decoy = _build_root(tmp_path / "decoy") / SNAPSHOT_REL
        monkeypatch.setenv("RISKIT_FIT_SNAPSHOT", str(decoy))
        monkeypatch.setattr(tr, "_snapshot_at", lambda _sha, repo=None: None)
        monkeypatch.setattr(
            tr, "execute", lambda **_k: pytest.fail("must refuse before fitting anything")
        )
        with pytest.raises(TrainingRunError, match="no board snapshot"):
            tr.replay(commit="HEAD")


class TestMissingInputPins:
    def test_a_missing_input_records_none_not_zero(self, tmp_path):
        """Finding 10: an input that was never read read no rows because it was
        never read — ``None``, not ``0``."""
        root = _build_root(tmp_path / "missing-holdout")
        rel = default_manifest().board("OFFENSE", "OTCFFB").paths[0]
        (root / rel).unlink()
        pin = _run(root).record["inputs"][rel]
        assert pin["sha256"] == "missing"
        assert pin["rowsRead"] is None
        assert pin["picksDropped"] is None
        assert pin["playerRows"] is None
