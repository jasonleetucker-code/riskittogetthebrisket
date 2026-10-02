"""AL-1a step 4: Hill refit / challenger learning receipts (``scripts/hill_learning_receipts.py``).

The refit commits evidence under ``config/model_registry/``; the box's deploy
reads it into ``data/learning/receipts.sqlite``. Pinned here:

* idempotency -- a re-run over the same artifacts stores only duplicates, and a
  changed registry entry is a new receipt, never a conflict;
* missing stays missing -- absent fields are ``unobserved`` with a reason;
* no prospective label on a retrospective verdict -- no Hill holdout EVALUATION;
* fail closed -- a missing / corrupt registry or run log writes nothing (exit 2);
  an edited training-run artifact is refused, never laundered;
* the deploy wiring -- post-deploy, enabled, bounded, non-fatal;
* nothing promotes and nothing under ``config/`` changes.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from src.model_registry import learning_adapters as la
from src.model_registry import producer_receipts as pr
from src.model_registry import receipt_store as rs
from src.model_registry.learning_receipt import KIND_EVALUATION, KIND_OBSERVATION
from src.model_registry.training_run import artifact_rel_path, pins_hash, summarize_run

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hill_learning_receipts.py"
DEPLOY = REPO / "deploy" / "deploy.sh"
REGISTRY_DIR = REPO / "config" / "model_registry"
DEMO = REPO / "docs" / "valuation" / "evidence" / "hill-trainer-repair-2026-10-01" / "demo.json"


def _load_script():
    spec = importlib.util.spec_from_file_location("hill_learning_receipts_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load_script()


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv(pr.RECEIPTS_ENABLED_ENV, "1")


def _full_record(summary: dict) -> dict:
    """A full run record (``inputs`` present) whose pins hash to its own ``pinsHash``."""
    record = copy.deepcopy(summary)
    record["inputs"] = {
        "CSVs/site_raw/ktc.csv": {
            "sha256": "ab" * 32,
            "datasetState": {
                "measured": True,
                # at the cutoff: the latest instant a point-in-time input may carry
                "lastAnyMeaningfulChangeAt": summary["trainingCutoff"],
            },
        }
    }
    record["pinsHash"] = pins_hash(record)
    return record


ADJUDICATION_BLOCKED = {
    "schemaVersion": 1,
    "evaluatedAt": "2026-10-02T09:00:00+00:00",
    "triggerSha": "f" * 40,
    "championVersion": 1,
    "winnerVersion": 2,
    "ready": False,
    "outcome": "AUTO_PROMOTION_BLOCKED",
    "reason": "no_independent_validation_target",
    "gates": {"winner": True, "per_source": True},
    "independentValidation": {
        "challengerVersion": 2,
        "registrySize": 0,
        "eligibleTargets": [],
        "passed": False,
        "assessments": [],
        "gatesPromotion": True,
        "reason": "no_independent_validation_target",
        "error": None,
    },
    "safePromotionScope": ["OFFENSE"],
    "requiredImprovement": 60.0,
    "currentImprovement": 600.0,
}

#: A pre-gate-7 line: no ``outcome``, no ``independentValidation``.
ADJUDICATION_LEGACY = {
    "schemaVersion": 1,
    "evaluatedAt": "2026-09-14T23:36:55+00:00",
    "championVersion": 1,
    "winnerVersion": 3,
    "ready": True,
    "reason": "all automatic-promotion evidence gates cleared",
    "gates": {"winner": True},
}


@pytest.fixture
def registry_dir(tmp_path) -> Path:
    """A small committed-shaped registry: a champion, a raw challenger with a full
    artifact on disk, a rejected composite whose artifact was pruned, a run log."""
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    raw = _full_record(demo["1_twoReplaysOfOnePinSet"]["a"])
    pruned = demo["3_pointInTime"]["a"]
    d = tmp_path / "model_registry"
    (d / "training_runs").mkdir(parents=True)
    rel = artifact_rel_path(raw["challengerHash"])
    (d / rel).write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    holdout = {
        "criterion": 600.0,
        "criterionName": "mean_per_source_rmse",
        "perSource": {"FantasyCalc": 600.0},
        "perSourceRows": {"FantasyCalc": 397},
        "holdoutSources": ["FantasyCalc"],
        "skipped": {},
    }
    registry = {
        "modelId": "hill_scope_masters",
        "schemaVersion": 1,
        "championVersion": 1,
        "versions": [
            {
                "version": 1,
                "status": "champion",
                "fittedAt": "2026-07-28T09:08:00+00:00",
                "producer": "scripts/fit_hill_curve_percentile.py @ 3df9cc4",
                "trainingInputs": {"KTC": "sha256:c208f1c542e97e74"},
                "holdout": holdout,
                "notes": [],
                "promotedAt": "2026-07-29T00:00:00+00:00",
                "appliedAt": "2026-07-29T00:05:00+00:00",
                "retiredAt": None,
            },
            {
                "version": 2,
                "status": "challenger",
                "fittedAt": "2026-10-01T13:40:00+00:00",
                "producer": "scripts/fit_hill_curve_percentile.py @ abc1234",
                "trainingInputs": {"KTC": "sha256:c208f1c542e97e74"},
                "holdout": holdout,
                "notes": [],
                "promotedAt": None,
                "retiredAt": None,
                # no "appliedAt" key at all: unobserved, not null
                "trainingRun": summarize_run(raw, artifact=rel),
            },
            {
                "version": 3,
                "status": "rejected",
                "fittedAt": "unknown",
                "producer": "Hill Autopilot OFFENSE composite from raw v2",
                "trainingInputs": {},
                "holdout": holdout,
                "notes": [
                    "rejected: Hill Autopilot downstream board-impact gate blocked promotion"
                ],
                "promotedAt": None,
                "appliedAt": None,
                "retiredAt": None,
                "trainingRun": summarize_run(pruned, artifact="training_runs/pruned.json"),
            },
        ],
    }
    (d / cli.REGISTRY_FILE).write_text(json.dumps(registry, indent=2), encoding="utf-8")
    (d / cli.RUN_LOG_FILE).write_text(
        "\n".join(
            json.dumps(x, sort_keys=True) for x in (ADJUDICATION_LEGACY, ADJUDICATION_BLOCKED)
        )
        + "\n",
        encoding="utf-8",
    )
    return d


def _run(registry_dir: Path, store: Path, *extra: str, capsys=None) -> tuple[int, dict | None]:
    code = cli.main(["--registry-dir", str(registry_dir), "--store", str(store), *extra])
    if capsys is None:
        return code, None
    out = capsys.readouterr().out.strip()
    return code, (json.loads(out.splitlines()[-1]) if out else None)


def _stored(store: Path, kind: str | None = None) -> list[dict]:
    return list(rs.iter_receipts(store, kind=kind))


def _tree_digest(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ── idempotency ──────────────────────────────────────────────────────────────


class TestIdempotent:
    def test_a_rerun_over_the_same_artifacts_stores_only_duplicates(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        store = tmp_path / "receipts.sqlite"
        code, first = _run(registry_dir, store, capsys=capsys)
        assert code == 0, first
        assert first["written"] > 0 and first["duplicates"] == 0
        code, second = _run(registry_dir, store, capsys=capsys)
        assert code == 0
        assert second["written"] == 0
        assert second["duplicates"] == first["written"]
        assert second["contentConflicts"] == [] and second["rejected"] == []
        assert len(_stored(store)) == first["written"]

    def test_the_committed_registry_reruns_as_duplicates(self, tmp_path, enabled, capsys):
        """The real config/model_registry/: every entry and adjudication builds, and a
        second pass adds nothing."""
        store = tmp_path / "receipts.sqlite"
        code, first = _run(REGISTRY_DIR, store, capsys=capsys)
        assert code == 0, first["refused"]
        assert first["refused"] == [] and first["written"] == first["receipts"]
        code, second = _run(REGISTRY_DIR, store, capsys=capsys)
        assert (code, second["written"], second["duplicates"]) == (0, 0, first["written"])

    def test_identity_is_the_native_id_plus_a_content_revision(self, registry_dir):
        receipts, refused, _ = cli.build_receipts(registry_dir)
        assert refused == []
        assert all(r.revision and r.revision.startswith("sha256:") for r in receipts)
        again, _, _ = cli.build_receipts(registry_dir)
        assert [(r.receipt_id, r.content_hash()) for r in receipts] == [
            (r.receipt_id, r.content_hash()) for r in again
        ]

    def test_a_changed_entry_is_a_new_receipt_never_a_conflict(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        store = tmp_path / "receipts.sqlite"
        _run(registry_dir, store, capsys=capsys)
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        reg["versions"][1]["status"] = "rejected"
        reg["versions"][1]["notes"] = ["rejected: superseded"]
        path.write_text(json.dumps(reg), encoding="utf-8")
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == 0
        assert out["contentConflicts"] == []
        assert out["written"] == 2  # v2's MODEL and CHALLENGER, under a new revision
        v2_models = [
            r
            for r in _stored(store, "MODEL")
            if r["producer"] == la.HILL_REGISTRY_PRODUCER and r["nativeId"] == "v2"
        ]
        assert sorted(m["body"]["status"] for m in v2_models) == ["challenger", "rejected"]

    def test_a_shared_training_run_yields_one_receipt(self, registry_dir):
        """Two raw refits on unchanged data share one run: one receipt, not a batch conflict."""
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        twin = copy.deepcopy(reg["versions"][1])
        twin["version"] = 4
        reg["versions"].append(twin)
        path.write_text(json.dumps(reg), encoding="utf-8")
        receipts, refused, _ = cli.build_receipts(registry_dir)
        assert refused == []
        ids = [r.receipt_id for r in receipts]
        assert len(ids) == len(set(ids))


# ── missing stays missing ────────────────────────────────────────────────────


class TestUnobserved:
    def _by(self, registry_dir):
        receipts, refused, _ = cli.build_receipts(registry_dir)
        assert refused == []
        return receipts

    def test_a_pre_gate_line_publishes_outcome_and_validation_unobserved(self, registry_dir):
        obs = {
            r.body["evaluatedAt"]: r for r in self._by(registry_dir) if r.kind == KIND_OBSERVATION
        }
        legacy = obs["2026-09-14T23:36:55+00:00"].body
        assert legacy["outcome"]["state"] == "unobserved"
        assert legacy["independentValidation"]["state"] == "unobserved"
        assert legacy["triggerSha"]["state"] == "unobserved"
        assert legacy["promotionApplied"]["state"] == "unobserved"

    def test_a_blocked_adjudication_is_recorded_as_data(self, registry_dir):
        blocked = next(
            r
            for r in self._by(registry_dir)
            if r.kind == KIND_OBSERVATION and r.body["evaluatedAt"].startswith("2026-10-02")
        )
        assert blocked.body["outcome"] == "AUTO_PROMOTION_BLOCKED"
        assert blocked.body["reason"] == "no_independent_validation_target"
        assert (
            blocked.body["independentValidation"] == ADJUDICATION_BLOCKED["independentValidation"]
        )
        assert blocked.body["promotes"] is False and blocked.body["isPromotionRecord"] is False
        assert blocked.producer == pr.HILL_AUTOPILOT_PRODUCER
        assert blocked.cutoff.isoformat() == "2026-10-02T09:00:00+00:00"
        assert blocked.model_version_id == la.hill_version_id_for_registry(2)

    def test_a_winner_with_unrecorded_fitted_at_is_not_offered_as_an_input(self, registry_dir):
        legacy = next(
            r
            for r in self._by(registry_dir)
            if r.kind == KIND_OBSERVATION and r.body["evaluatedAt"].startswith("2026-09-14")
        )
        # winner v3 is a composite with fittedAt 'unknown'
        assert legacy.slots["winner"].to_dict()["state"] == "unobserved"
        assert legacy.slots["champion"].to_dict()["fidelity"] == "exact"

    def test_absent_registry_fields_are_unobserved_but_explicit_null_is_carried(self, registry_dir):
        models = {
            r.native_id: r
            for r in self._by(registry_dir)
            if r.kind == "MODEL" and r.producer == la.HILL_REGISTRY_PRODUCER
        }
        assert models["v1"].body["promotedAt"] == "2026-07-29T00:00:00+00:00"
        assert models["v2"].body["promotedAt"] is None  # the registry's own null
        assert models["v2"].body["appliedAt"]["state"] == "unobserved"  # key absent

    def test_a_pruned_artifact_falls_back_to_the_summary_never_a_guess(self, registry_dir):
        runs = [
            r
            for r in self._by(registry_dir)
            if r.kind == "MODEL" and r.producer == la.HILL_PRODUCER
        ]
        forms = sorted(r.body["recordForm"] for r in runs)
        assert forms == ["full", "summary"]
        summary_features = next(
            r
            for r in self._by(registry_dir)
            if r.kind == "FEATURES" and r.body["inputCount"] is None
        )
        assert summary_features.slots["inputs"].to_dict()["state"] == "unobserved"


# ── no prospective label on a retrospective verdict ──────────────────────────


class TestRetrospectiveIsNotProspective:
    def test_no_hill_evaluation_receipt_is_emitted(self, registry_dir):
        receipts, _, stats = cli.build_receipts(registry_dir)
        assert KIND_EVALUATION not in {r.kind for r in receipts}
        assert stats["evaluationsWithheld"] == 3
        assert "retrospective" in stats["evaluationsWithheldReason"]

    def test_none_for_the_committed_registry_either(self):
        receipts, refused, stats = cli.build_receipts(REGISTRY_DIR)
        assert refused == []
        assert KIND_EVALUATION not in {r.kind for r in receipts}
        assert stats["evaluationsWithheld"] == stats["registryVersions"]

    def test_the_al0_adapter_still_builds_its_evaluation_by_default(self, registry_dir):
        """The withholding is AL-1a's decision at the box, not a change to AL-0."""
        reg = json.loads((registry_dir / cli.REGISTRY_FILE).read_text(encoding="utf-8"))
        kinds = [
            r.kind
            for r in la.hill_receipts_from_registry_version(reg["versions"][0], champion_version=1)
        ]
        assert kinds[-1] == KIND_EVALUATION

    def test_no_receipt_claims_a_target_event_or_a_prediction(self, registry_dir):
        receipts, _, _ = cli.build_receipts(registry_dir)
        assert all(r.target_event_at is None and r.prediction_id is None for r in receipts)

    def test_nothing_promotes(self, registry_dir):
        receipts, _, _ = cli.build_receipts(registry_dir)
        assert {r.kind for r in receipts} <= {"MODEL", "CHALLENGER", "FEATURES", "OBSERVATION"}
        for r in receipts:
            if r.kind != "FEATURES":
                assert r.body["promotes"] is False


# ── fail closed ──────────────────────────────────────────────────────────────


class TestFailsClosed:
    def _assert_refused(self, registry_dir, tmp_path, capsys, match):
        store = tmp_path / "receipts.sqlite"
        code = cli.main(["--registry-dir", str(registry_dir), "--store", str(store)])
        err = capsys.readouterr().err
        assert code == cli.EXIT_REFUSED
        assert re.search(match, err), err
        assert "nothing written" in err
        assert not store.exists()

    def test_a_missing_registry_is_refused(self, registry_dir, tmp_path, enabled, capsys):
        (registry_dir / cli.REGISTRY_FILE).unlink()
        self._assert_refused(registry_dir, tmp_path, capsys, "registry is missing")

    def test_a_corrupt_registry_is_refused(self, registry_dir, tmp_path, enabled, capsys):
        (registry_dir / cli.REGISTRY_FILE).write_text('{"versions": [', encoding="utf-8")
        self._assert_refused(registry_dir, tmp_path, capsys, "registry is unreadable")

    @pytest.mark.parametrize(
        "mutate, match",
        [
            (lambda r: r.pop("championVersion"), "championVersion"),
            (lambda r: r["versions"].append(dict(r["versions"][0])), "appears twice"),
            (lambda r: r.__setitem__("versions", {"1": {}}), "versions"),
            (lambda r: r["versions"][0].pop("version"), "integer version"),
            (lambda r: r.__setitem__("championVersion", 99), "not a registry entry"),
        ],
    )
    def test_a_structurally_corrupt_registry_is_refused(
        self, registry_dir, tmp_path, enabled, capsys, mutate, match
    ):
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        mutate(reg)
        path.write_text(json.dumps(reg), encoding="utf-8")
        self._assert_refused(registry_dir, tmp_path, capsys, match)

    def test_a_corrupt_run_log_line_is_refused(self, registry_dir, tmp_path, enabled, capsys):
        with (registry_dir / cli.RUN_LOG_FILE).open("a", encoding="utf-8") as f:
            f.write('{"evaluatedAt": \n')
        self._assert_refused(registry_dir, tmp_path, capsys, "corrupt run-log line")

    def test_a_missing_run_log_is_refused(self, registry_dir, tmp_path, enabled, capsys):
        (registry_dir / cli.RUN_LOG_FILE).unlink()
        self._assert_refused(registry_dir, tmp_path, capsys, "run log is missing")

    def test_an_edited_artifact_is_refused_and_the_rest_still_recorded(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        art = next((registry_dir / "training_runs").glob("*.json"))
        record = json.loads(art.read_text(encoding="utf-8"))
        record["inputs"]["CSVs/site_raw/ktc.csv"]["sha256"] = "cd" * 32
        art.write_text(json.dumps(record), encoding="utf-8")
        code, out = _run(registry_dir, tmp_path / "receipts.sqlite", capsys=capsys)
        assert code == cli.EXIT_PARTIAL
        assert any("v2 trainingRun" in i["item"] for i in out["refused"])
        assert out["written"] > 0  # the registry entries and adjudications still landed

    def test_an_unreferenced_artifact_is_still_adapted(self, registry_dir):
        demo = json.loads(DEMO.read_text(encoding="utf-8"))
        extra = _full_record(demo["3_pointInTime"]["a"])
        path = registry_dir / artifact_rel_path(extra["challengerHash"])
        path.write_text(json.dumps(extra), encoding="utf-8")
        receipts, refused, stats = cli.build_receipts(registry_dir)
        assert refused == []
        assert stats["trainingRuns"] == 3
        assert extra["challengerHash"] in {r.native_id for r in receipts}


# ── gating, inputs untouched ─────────────────────────────────────────────────


class TestGateAndSideEffects:
    def test_without_the_enable_switch_nothing_is_written(
        self, registry_dir, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.delenv(pr.RECEIPTS_ENABLED_ENV, raising=False)
        store = tmp_path / "receipts.sqlite"
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == 0
        assert out["written"] is None and pr.RECEIPTS_ENABLED_ENV in out["notWrittenBecause"]
        assert not store.exists()

    def test_dry_run_writes_nothing_even_when_enabled(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        store = tmp_path / "receipts.sqlite"
        code, out = _run(registry_dir, store, "--dry-run", capsys=capsys)
        assert code == 0 and out["notWrittenBecause"] == "--dry-run"
        assert not store.exists()

    def test_the_committed_evidence_is_read_never_written(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        before = _tree_digest(registry_dir)
        _run(registry_dir, tmp_path / "receipts.sqlite", capsys=capsys)
        assert _tree_digest(registry_dir) == before

    def test_the_script_can_neither_promote_nor_override_a_scope(self):
        text = SCRIPT.read_text(encoding="utf-8")
        code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
        body = "\n".join(code_lines).split('"""', 2)[-1]  # skip the module docstring
        for forbidden in ("override-scope", "override_scope", "promotion", ".promote(", ".apply("):
            assert forbidden not in body, forbidden
        assert "model_registry.py" not in body


# ── deploy wiring ────────────────────────────────────────────────────────────


def _function(text: str, name: str) -> str:
    start = text.index(f"\n{name}() {{")
    end = text.index("\n}\n", start)
    return text[start : end + 3]


class TestDeployWiring:
    TEXT = DEPLOY.read_text(encoding="utf-8")

    def test_deploy_runs_it_after_the_deploy_is_recorded(self):
        main = self.TEXT[self.TEXT.index("\nmain() {") :]
        assert "record_hill_learning_receipts" in main
        assert main.index("record_success_state") < main.index("record_hill_learning_receipts")
        assert main.index("verify_deploy") < main.index("record_hill_learning_receipts")

    def test_the_box_run_is_enabled_bounded_and_non_fatal(self):
        fn = _function(self.TEXT, "record_hill_learning_receipts")
        assert "scripts/hill_learning_receipts.py" in fn
        assert "RISKIT_RECEIPTS_ENABLED=1" in fn
        assert "timeout 300" in fn
        assert re.search(r"if output=\"\$\(RISKIT_RECEIPTS_ENABLED=1 timeout 300 ", fn)
        assert 'warn "[hill-receipts] WARNING' in fn
        assert fn.rstrip().endswith("return 0\n}")
        assert "--override-scope" not in fn and "promote" not in fn

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
    @pytest.mark.parametrize("exit_code", [0, 1, 2])
    def test_a_failing_run_never_fails_the_deploy(self, tmp_path, exit_code):
        """Execute the real function with a stub interpreter under ``set -Eeuo pipefail``."""
        app = tmp_path / "app"
        (app / "scripts").mkdir(parents=True)
        (app / "scripts" / "hill_learning_receipts.py").write_text("", encoding="utf-8")
        venv = tmp_path / "venv"
        (venv / "bin").mkdir(parents=True)
        stub = venv / "bin" / "python"
        stub.write_text(
            f'#!/usr/bin/env bash\necho "enabled=$RISKIT_RECEIPTS_ENABLED"\nexit {exit_code}\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
        fn = _function(self.TEXT, "record_hill_learning_receipts")
        harness = (
            "set -Eeuo pipefail\n"
            "trap 'echo TRAPPED; exit 99' ERR\n"
            'log() { echo "LOG $*"; }\nwarn() { echo "WARN $*"; }\n'
            f"{fn}\n"
            "record_hill_learning_receipts\n"
            "echo REACHED_END\n"
        )
        script = tmp_path / "harness.sh"
        script.write_text(harness, encoding="utf-8", newline="\n")
        env = {
            "APP_DIR": app.as_posix(),
            "VENV_DIR": venv.as_posix(),
            "PATH": __import__("os").environ.get("PATH", ""),
        }
        proc = subprocess.run(
            ["bash", script.as_posix()], capture_output=True, text=True, env=env, timeout=60
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "REACHED_END" in proc.stdout and "TRAPPED" not in proc.stdout
        assert "enabled=1" in proc.stdout
        assert ("WARN [hill-receipts] WARNING" in proc.stdout) == (exit_code != 0)
