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
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.model_registry import learning_adapters as la
from src.model_registry import producer_receipts as pr
from src.model_registry import receipt_store as rs
from src.model_registry.learning_receipt import KIND_EVALUATION, KIND_OBSERVATION, ReceiptError
from src.model_registry.training_run import artifact_rel_path, pins_hash, summarize_run

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "hill_learning_receipts.py"
DEPLOY = REPO / "deploy" / "deploy.sh"
REGISTRY_DIR = REPO / "config" / "model_registry"
T_READ = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)  # a fixed deploy read time
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
        # an unchanged disposition is not re-observed (3), and v3's pruned-run summary,
        # already stored, is not re-described (2); everything else is a duplicate
        assert second["dispositionsObserved"] == 0
        assert second["summariesSkippedRunDescribed"] == 1
        assert second["duplicates"] == second["receipts"] == first["written"] - 3 - 2
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
        assert (code, second["written"], second["dispositionsObserved"]) == (0, 0, 0)
        assert second["duplicates"] == second["receipts"]
        assert second["contentConflicts"] == []

    def test_no_receipt_uses_revision_and_builds_are_deterministic(self, registry_dir):
        """``revision`` is a correction's identity in the AL-0 contract; none is used."""
        receipts, refused, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        assert refused == []
        assert all(r.revision is None for r in receipts)
        again, _, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        assert [(r.receipt_id, r.content_hash()) for r in receipts] == [
            (r.receipt_id, r.content_hash()) for r in again
        ]

    def test_a_disposition_change_adds_one_timed_observation_and_moves_nothing_else(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        store = tmp_path / "receipts.sqlite"
        _run(registry_dir, store, capsys=capsys)
        before = {r["receiptId"]: r for r in _stored(store)}
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        reg["versions"][1]["status"] = "rejected"
        reg["versions"][1]["notes"] = ["rejected: superseded"]
        path.write_text(json.dumps(reg), encoding="utf-8")
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == 0
        assert out["contentConflicts"] == []
        assert out["written"] == 1  # one disposition observation; MODEL/CHALLENGER unchanged
        # minus three dispositions (two unchanged, one now new) and the stored summary run
        assert out["duplicates"] == len(before) - 3 - 2
        new = [r for r in _stored(store) if r["receiptId"] not in before]
        assert len(new) == 1
        obs = new[0]
        assert obs["kind"] == "OBSERVATION" and obs["nativeId"].startswith("v2:disposition@")
        assert obs["body"]["state"]["status"] == "rejected"
        prior = before[obs["body"]["previousObservation"]["receiptId"]]
        assert prior["body"]["state"]["status"] == "challenger"
        # the order of states is explicit: each carries its own observed-at cutoff
        assert obs["cutoff"] > prior["cutoff"]
        assert obs["body"]["transitionAt"]["state"] == "unobserved"
        assert prior["cutoff"] in obs["body"]["transitionAt"]["reason"]

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


def _adjudications(receipts) -> dict:
    return {r.body["evaluatedAt"]: r for r in receipts if r.producer == pr.HILL_AUTOPILOT_PRODUCER}


def _registry_obs(receipts, observes: str) -> list:
    return [
        r
        for r in receipts
        if r.kind == KIND_OBSERVATION
        and r.producer == la.HILL_REGISTRY_PRODUCER
        and r.body["observes"] == observes
    ]


class TestUnobserved:
    def _by(self, registry_dir):
        receipts, refused, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        assert refused == []
        return receipts

    def test_a_pre_gate_line_publishes_outcome_and_validation_unobserved(self, registry_dir):
        legacy = _adjudications(self._by(registry_dir))["2026-09-14T23:36:55+00:00"].body
        assert legacy["outcome"]["state"] == "unobserved"
        assert legacy["independentValidation"]["state"] == "unobserved"
        assert legacy["triggerSha"]["state"] == "unobserved"
        assert legacy["promotionApplied"]["state"] == "unobserved"

    def test_a_blocked_adjudication_is_recorded_as_data(self, registry_dir):
        blocked = _adjudications(self._by(registry_dir))["2026-10-02T09:00:00+00:00"]
        assert blocked.body["outcome"] == "AUTO_PROMOTION_BLOCKED"
        assert blocked.body["reason"] == "no_independent_validation_target"
        assert (
            blocked.body["independentValidation"] == ADJUDICATION_BLOCKED["independentValidation"]
        )
        assert blocked.body["promotes"] is False and blocked.body["isPromotionRecord"] is False
        assert blocked.cutoff.isoformat() == "2026-10-02T09:00:00+00:00"
        assert blocked.model_version_id == la.hill_version_id_for_registry(2)
        assert "lineCanonicalJsonSha256" in blocked.body["sourceRecord"]

    def test_a_winner_with_unrecorded_fitted_at_is_not_offered_as_an_input(self, registry_dir):
        legacy = _adjudications(self._by(registry_dir))["2026-09-14T23:36:55+00:00"]
        # winner v3 is a composite with fittedAt 'unknown'
        assert legacy.slots["winner"].to_dict()["state"] == "unobserved"
        assert legacy.slots["champion"].to_dict()["fidelity"] == "exact"

    def test_lifecycle_stamps_are_their_own_instants_and_null_is_no_event(self, registry_dir):
        events = {
            (r.body["version"], r.body["event"]): r
            for r in _registry_obs(self._by(registry_dir), pr.HILL_LIFECYCLE_OBSERVES)
        }
        assert set(events) == {(1, "promotedAt"), (1, "appliedAt")}
        promoted = events[(1, "promotedAt")]
        assert promoted.cutoff.isoformat() == "2026-07-29T00:00:00+00:00"
        assert promoted.slots["event"].known_at == promoted.cutoff
        # v2: promotedAt null, appliedAt absent -> no event at all, never a guessed instant

    def test_an_absent_disposition_key_is_unobserved_never_empty(self, registry_dir):
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        del reg["versions"][1]["notes"]
        path.write_text(json.dumps(reg), encoding="utf-8")
        states = {
            r.body["version"]: r.body["state"]
            for r in _registry_obs(self._by(registry_dir), pr.HILL_DISPOSITION_OBSERVES)
        }
        assert states[2]["status"] == "challenger"
        assert states[2]["notes"]["state"] == "unobserved"
        assert states[1]["notes"] == []  # present and empty is the registry's own statement

    def test_an_unparseable_lifecycle_stamp_is_refused_not_guessed(self, registry_dir):
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        reg["versions"][0]["retiredAt"] = "2026-08-01"  # a date is not a proven instant
        path.write_text(json.dumps(reg), encoding="utf-8")
        _, refused, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        assert [i["item"] for i in refused] == ["registry v1"]

    def test_a_pruned_artifact_falls_back_to_the_summary_never_a_guess(self, registry_dir):
        receipts = self._by(registry_dir)
        runs = [r for r in receipts if r.kind == "MODEL" and r.producer == la.HILL_PRODUCER]
        assert sorted(r.body["recordForm"] for r in runs) == ["full", "summary"]
        summary_features = next(
            r for r in receipts if r.kind == "FEATURES" and r.body["inputCount"] is None
        )
        assert summary_features.slots["inputs"].to_dict()["state"] == "unobserved"

    def test_a_run_stored_in_full_is_not_redescribed_by_its_summary(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        store = tmp_path / "receipts.sqlite"
        _run(registry_dir, store, capsys=capsys)
        for art in (registry_dir / "training_runs").glob("*.json"):
            art.unlink()  # pruned after 30 days
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == 0, out
        assert out["contentConflicts"] == [] and out["written"] == 0
        assert out["summariesSkippedRunDescribed"] == 2  # v2's run and v3's pruned run

    def test_a_run_stored_as_a_summary_is_not_redescribed_in_full(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        """The mirror: summary first (artifact not yet readable), full later."""
        store = tmp_path / "receipts.sqlite"
        arts = list((registry_dir / "training_runs").glob("*.json"))
        hidden = {a: a.read_bytes() for a in arts}
        for a in arts:
            a.unlink()
        code, first = _run(registry_dir, store, capsys=capsys)
        assert code == 0, first
        for a, data in hidden.items():
            a.write_bytes(data)  # the full artifact becomes readable
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == 0, out
        assert out["contentConflicts"] == [] and out["written"] == 0
        assert out["fullSkippedStoredAsSummary"] == 1  # v2's run
        forms = {
            r["nativeId"]: r["body"]["recordForm"]
            for r in _stored(store, "MODEL")
            if r["producer"] == la.HILL_PRODUCER
        }
        assert set(forms.values()) == {"summary"}

    def test_an_edited_full_artifact_still_surfaces_as_a_conflict(
        self, registry_dir, tmp_path, enabled, capsys
    ):
        """The skip is form-to-form only: full-vs-full divergence is never hidden."""
        store = tmp_path / "receipts.sqlite"
        _run(registry_dir, store, capsys=capsys)
        art = next((registry_dir / "training_runs").glob("*.json"))
        record = json.loads(art.read_text(encoding="utf-8"))
        record["inputsCommit"] = "f" * 40  # an unhashed label: the pins still verify
        art.write_text(json.dumps(record), encoding="utf-8")
        code, out = _run(registry_dir, store, capsys=capsys)
        assert code == cli.EXIT_PARTIAL
        assert out["contentConflicts"]


# ── M1: no later fact is claimed at fittedAt ─────────────────────────────────


LATER_FACT_KEYS = {
    "status",
    "notes",
    "promotedAt",
    "appliedAt",
    "retiredAt",
    "championVersionAtRead",
}


class TestNoLookAhead:
    def _fit_time(self, registry_dir):
        receipts, refused, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        assert refused == []
        return {
            (r.kind, r.native_id): r
            for r in receipts
            if r.producer == la.HILL_REGISTRY_PRODUCER and r.kind in ("MODEL", "CHALLENGER")
        }

    def test_fit_anchored_bodies_carry_no_later_fact(self, registry_dir):
        for r in self._fit_time(registry_dir).values():
            assert not LATER_FACT_KEYS & set(r.body), (r.kind, r.native_id)
            assert r.body["scope"] == la.FIT_TIME_ONLY_NOTE

    def test_the_committed_registry_too(self):
        receipts, _, _ = cli.build_receipts(REGISTRY_DIR, observed_at=T_READ)
        for r in receipts:
            if r.producer == la.HILL_REGISTRY_PRODUCER and r.kind in ("MODEL", "CHALLENGER"):
                assert not LATER_FACT_KEYS & set(r.body), (r.kind, r.native_id)

    def test_a_disposition_flip_leaves_fit_anchored_receipts_byte_identical(self, registry_dir):
        before = {k: r.content_hash() for k, r in self._fit_time(registry_dir).items()}
        path = registry_dir / cli.REGISTRY_FILE
        reg = json.loads(path.read_text(encoding="utf-8"))
        reg["versions"][1]["status"] = "rejected"
        reg["versions"][1]["notes"] = ["rejected: superseded"]
        reg["championVersion"] = 1
        reg["versions"][0]["retiredAt"] = "2026-10-01T00:00:00+00:00"
        path.write_text(json.dumps(reg), encoding="utf-8")
        after = {k: r.content_hash() for k, r in self._fit_time(registry_dir).items()}
        assert after == before

    def test_disposition_is_stamped_at_the_read_time_never_at_fitted_at(self, registry_dir):
        receipts, _, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        for r in _registry_obs(receipts, pr.HILL_DISPOSITION_OBSERVES):
            assert r.cutoff == T_READ
            assert r.slots["registryEntry"].known_at == T_READ
            assert r.body["transitionAt"]["state"] == "unobserved"
            assert r.body["previousObservation"] is None  # empty store: no lower bound

    def test_an_unchanged_disposition_is_not_reobserved(self, registry_dir):
        receipts, _, _ = cli.build_receipts(registry_dir, observed_at=T_READ)
        stored = {
            "trainingRuns": {},
            "dispositions": {
                r.body["version"]: {
                    "state": r.body["state"],
                    "receiptId": r.receipt_id,
                    "observedAt": r.body["observedAt"],
                }
                for r in _registry_obs(receipts, pr.HILL_DISPOSITION_OBSERVES)
            },
        }
        later = T_READ + timedelta(hours=2)
        again, _, stats = cli.build_receipts(registry_dir, observed_at=later, stored=stored)
        assert stats["dispositionsObserved"] == 0
        assert not _registry_obs(again, pr.HILL_DISPOSITION_OBSERVES)

    def test_a_disposition_older_than_the_stored_one_is_refused(self, registry_dir):
        version = json.loads((registry_dir / cli.REGISTRY_FILE).read_text(encoding="utf-8"))[
            "versions"
        ][1]
        previous = {
            "state": {"status": "rejected", "notes": []},
            "receiptId": "rcpt:observation:x",
            "observedAt": T_READ.isoformat(),
        }
        with pytest.raises(ReceiptError, match="cannot follow"):
            pr.hill_disposition_receipt(
                version, observed_at=T_READ - timedelta(hours=1), previous=previous
            )


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

    def test_rollback_is_disarmed_once_the_target_is_recorded(self):
        """L2: nothing after ``record_success_state`` may trip the auto-rollback trap."""
        main = self.TEXT[self.TEXT.index("\nmain() {") :]
        success = main.index("\n  record_success_state\n")
        disarm = main.index("\n  trap - ERR\n")
        assert success < disarm < main.index("\n  archive_ros_forecasts\n")
        assert disarm < main.index("\n  record_hill_learning_receipts\n")
        # disarmed only there: the trap is still armed for every step before it
        assert main.count("trap - ERR") == 1
        assert "trap 'on_error $LINENO' ERR" in self.TEXT[: self.TEXT.index("\nmain() {")]

    def test_the_deploy_user_assumption_is_checked(self):
        """L3: deploy.sh has no run-as-app-user convention; the mismatch is warned."""
        fn = _function(self.TEXT, "record_hill_learning_receipts")
        assert '"${me}" != "${APP_USER}"' in fn
        assert "stat -c %U" in fn and "DEPLOY_USER == APP_USER" in self.TEXT

    def _harness(self, tmp_path, *, exit_code=0, script=True, venv=True, app_user=None):
        """Execute the real function under ``set -Eeuo pipefail`` with an armed ERR trap."""
        app = tmp_path / "app"
        (app / "scripts").mkdir(parents=True)
        if script:
            (app / "scripts" / "hill_learning_receipts.py").write_text("", encoding="utf-8")
        venv_dir = tmp_path / "venv"
        if venv:
            (venv_dir / "bin").mkdir(parents=True)
            stub = venv_dir / "bin" / "python"
            stub.write_text(
                f'#!/usr/bin/env bash\necho "enabled=$RISKIT_RECEIPTS_ENABLED"\nexit {exit_code}\n',
                encoding="utf-8",
                newline="\n",
            )
            stub.chmod(0o755)
        fn = _function(self.TEXT, "record_hill_learning_receipts")
        harness = (
            "set -Eeuo pipefail\n"
            "trap 'echo TRAPPED; exit 99' ERR\n"
            'APP_USER="${APP_USER:-$(id -un)}"\n'
            'log() { echo "LOG $*"; }\nwarn() { echo "WARN $*"; }\n'
            f"{fn}\n"
            "record_hill_learning_receipts\n"
            "echo REACHED_END\n"
        )
        path = tmp_path / "harness.sh"
        path.write_text(harness, encoding="utf-8", newline="\n")
        env = {
            "APP_DIR": app.as_posix(),
            "VENV_DIR": venv_dir.as_posix(),
            "PATH": os.environ.get("PATH", ""),
        }
        if app_user is not None:
            env["APP_USER"] = app_user
        proc = subprocess.run(
            ["bash", path.as_posix()], capture_output=True, text=True, env=env, timeout=60
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "REACHED_END" in proc.stdout and "TRAPPED" not in proc.stdout
        return proc.stdout

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
    @pytest.mark.parametrize("exit_code", [0, 1, 2, 124])
    def test_a_failing_or_timed_out_run_never_fails_the_deploy(self, tmp_path, exit_code):
        out = self._harness(tmp_path, exit_code=exit_code)
        assert "enabled=1" in out
        assert ("WARN [hill-receipts] WARNING" in out) == (exit_code != 0)

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
    @pytest.mark.parametrize(
        "script, venv, said",
        [(False, True, "script not present"), (True, False, "virtualenv missing")],
    )
    def test_the_skip_paths_skip_quietly(self, tmp_path, script, venv, said):
        out = self._harness(tmp_path, script=script, venv=venv)
        assert f"LOG [hill-receipts] {said}; skipping" in out
        assert "enabled=" not in out and "WARN" not in out

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
    def test_a_deploy_user_other_than_app_user_is_warned_not_fatal(self, tmp_path):
        out = self._harness(tmp_path, app_user="someone-else")
        assert "is not APP_USER 'someone-else'" in out
        assert "enabled=1" in out
