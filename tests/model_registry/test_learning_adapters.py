"""AL-0 producer adapters: A6 (round-trip real committed evidence; producers
byte-identical) and A10 (reproducible from pinned inputs).

Every evidence file read here is COMMITTED: the Hill registry
(``config/model_registry/hill_scope_masters.json``), the Hill trainer-repair
replay demonstration, and the #1589 source-quality archive + results.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from src.model_registry import learning_adapters as la
from src.model_registry import receipt_store as rs
from src.model_registry.evaluation_receipt import VERDICT_INSUFFICIENT
from src.model_registry.feature_dictionary import load_dictionary
from src.model_registry.learning_receipt import ReceiptError

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "config" / "model_registry" / "hill_scope_masters.json"
HILL_DEMO = (
    REPO / "docs" / "valuation" / "evidence" / "hill-trainer-repair-2026-10-01" / "demo.json"
)
SQ_DIR = REPO / "docs" / "valuation" / "evidence" / "source-quality-2026-10-01"
SQ_ARCHIVE = SQ_DIR / "evaluations.jsonl"
SQ_RESULTS = SQ_DIR / "results_2026-09-30.json"
SQ_ARCHIVE_KEY = SQ_ARCHIVE.relative_to(REPO).as_posix()
SQ_RESULTS_KEY = SQ_RESULTS.relative_to(REPO).as_posix()
EVIDENCE = (REGISTRY, HILL_DEMO, SQ_ARCHIVE, SQ_RESULTS)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dictionary():
    return load_dictionary()


def _all_receipts(dictionary):
    reg = _load(REGISTRY)
    out = []
    for v in reg["versions"]:
        out += la.hill_receipts_from_registry_version(v, champion_version=reg["championVersion"])
    demo = _load(HILL_DEMO)
    out += la.hill_receipts_from_training_run(
        demo["1_twoReplaysOfOnePinSet"]["a"], dictionary=dictionary
    )
    out += la.hill_receipts_from_training_run(demo["3_pointInTime"]["a"], dictionary=dictionary)
    results = _load(SQ_RESULTS)
    for line in SQ_ARCHIVE.read_text(encoding="utf-8").splitlines():
        out += la.source_quality_receipts(
            json.loads(line),
            archive_key=SQ_ARCHIVE_KEY,
            dictionary=dictionary,
            results=results,
            results_key=SQ_RESULTS_KEY,
        )
    return out


# ── A6: real committed evidence round-trips; producers untouched ────────────


class TestRoundTrip:
    def test_every_committed_record_becomes_a_receipt_and_the_files_are_untouched(
        self, dictionary, tmp_path
    ):
        before = {p: _sha(p) for p in EVIDENCE}
        receipts = _all_receipts(dictionary)
        out = rs.append_receipts(receipts, path=tmp_path / "r.sqlite")
        assert out["rejected"] == [] and out["contentConflicts"] == []
        assert out["written"] == len({r.receipt_id for r in receipts})
        assert {p: _sha(p) for p in EVIDENCE} == before
        stored = list(rs.iter_receipts(tmp_path / "r.sqlite"))
        assert {s["receiptId"]: s for s in stored} == {r.receipt_id: r.to_dict() for r in receipts}

    def test_artifact_store_writers_are_the_adapters_producers(self):
        from src.model_registry.learning_receipt import ARTIFACT_STORE_WRITERS as W

        assert W["model_registry"] == {la.HILL_REGISTRY_PRODUCER}
        assert W["hill_training_run"] == {la.HILL_PRODUCER}
        assert W["source_quality_evaluations"] == {la.SQ_PRODUCER}
        assert W["source_quality_results"] == {la.SQ_PRODUCER}

    def test_every_post_cutoff_artifact_is_the_receipts_own_output(self, dictionary):
        """Round-2 finding 5 on real evidence: the source-quality evaluation's
        archive/results refs post-date its window cutoff and are exempt only
        because they name that evaluation run."""
        from src.model_registry.learning_receipt import ROLE_ARTIFACT, is_own_artifact

        late = 0
        for r in _all_receipts(dictionary):
            refs = [*r.refs, *(s for s in r.slots.values() if hasattr(s, "role"))]
            for ref in refs:
                if (
                    ref.role == ROLE_ARTIFACT
                    and r.cutoff is not None
                    and ref.known_at is not None
                    and ref.known_at > r.cutoff
                ):
                    late += 1
                    assert is_own_artifact(r, ref), (r.kind, ref.store, ref.key)
        assert late > 0, "expected the source-quality evaluations to cite post-cutoff output"

    def test_every_artifact_ref_is_own_or_comparable_with_a_cutoff(self, dictionary):
        """Round-3 finding D3 on real evidence: an artifact that is not the
        receipt's own output carries a knownAt AND sits on a receipt with a cutoff
        it does not exceed. No artifact is exempt by its role label alone."""
        from src.model_registry.learning_receipt import ROLE_ARTIFACT, is_own_artifact

        foreign = 0
        for r in _all_receipts(dictionary):
            for ref in [*r.refs, *(s for s in r.slots.values() if hasattr(s, "role"))]:
                if ref.role != ROLE_ARTIFACT or is_own_artifact(r, ref):
                    continue
                foreign += 1
                assert r.cutoff is not None and ref.known_at is not None, (r.kind, ref.key)
                assert ref.known_at <= r.cutoff, (r.kind, ref.key)
        assert foreign > 0, "the source-quality MODEL/CHALLENGER cite the run's archive"

    def test_the_preregistration_is_unobserved_not_an_unprovable_artifact(self, dictionary):
        """The producer pins the preregistration sha + commit but not its commit
        time, so it cannot be an artifact; the pin travels in extra, verbatim."""
        from src.model_registry.learning_receipt import Unobserved

        results = _load(SQ_RESULTS)
        line = json.loads(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines()[0])
        receipts = la.source_quality_receipts(
            line,
            archive_key=SQ_ARCHIVE_KEY,
            dictionary=dictionary,
            results=results,
            results_key=SQ_RESULTS_KEY,
        )
        model, challenger, evaluation = receipts
        assert isinstance(evaluation.slots["preregistration"], Unobserved)
        assert not any(ref.store == "preregistration" for ref in evaluation.refs)
        pin = evaluation.body["extra"]["preregistrationPin"]
        assert pin["sha256"] == line["preregistrationSha256"]
        assert pin["commit"] == results["pins"]["preregistration"]["commit"]
        evaluated_at = la.parse_instant(line["evaluatedAt"], what="evaluatedAt")
        assert model.cutoff == evaluated_at and challenger.cutoff == evaluated_at

    def test_a_registry_version_with_unrecorded_fitted_at_still_builds(self):
        """fittedAt 'unknown' (an Autopilot composite): every ref is the
        receipt's own registry output, so nothing needs an instant it lacks."""
        reg = _load(REGISTRY)
        version = dict(reg["versions"][0], fittedAt="unknown")
        receipts = la.hill_receipts_from_registry_version(
            version, champion_version=reg["championVersion"]
        )
        assert receipts
        for r in receipts:
            for ref in [*r.refs, *(s for s in r.slots.values() if hasattr(s, "role"))]:
                assert ref.known_at is None and ref.produced_for == r.native_id

    def test_the_training_run_artifact_claims_no_write_time_it_does_not_have(self, dictionary):
        """Minor finding: trainingCutoff bounds the run's INPUTS, not when the
        record was written, and the record carries no write time."""
        demo = _load(HILL_DEMO)
        record = demo["1_twoReplaysOfOnePinSet"]["a"]
        model = la.hill_receipts_from_training_run(record, dictionary=dictionary)[0]
        run_ref = model.slots["trainingRun"]
        assert run_ref.known_at is None and run_ref.fidelity == "unavailable"
        assert run_ref.produced_for == model.native_id == record["challengerHash"]
        assert "recordedAt" not in record

    def test_adapters_never_mutate_their_input(self, dictionary):
        reg = _load(REGISTRY)
        snap = copy.deepcopy(reg)
        for v in reg["versions"]:
            la.hill_receipts_from_registry_version(v, champion_version=reg["championVersion"])
        assert reg == snap
        line = json.loads(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines()[0])
        results = _load(SQ_RESULTS)
        line0, results0 = copy.deepcopy(line), copy.deepcopy(results)
        la.source_quality_receipts(
            line,
            archive_key=SQ_ARCHIVE_KEY,
            dictionary=dictionary,
            results=results,
            results_key=SQ_RESULTS_KEY,
        )
        assert line == line0 and results == results0

    def test_every_hill_registry_version_has_one_evaluation(self, dictionary):
        reg = _load(REGISTRY)
        evals = [
            r
            for r in _all_receipts(dictionary)
            if r.kind == "EVALUATION" and r.model_family == la.HILL_FAMILY
        ]
        assert len(evals) == len(reg["versions"])
        champion = [e for e in evals if e.body["role"] == "champion"]
        assert len(champion) == 1
        assert champion[0].model_version_id == la.hill_version_id_for_registry(
            reg["championVersion"]
        )
        assert {e.body["verdict"] for e in evals} <= {"inconclusive", VERDICT_INSUFFICIENT}

    def test_source_quality_verdicts_match_the_producer_dispositions(self, dictionary):
        results = _load(SQ_RESULTS)
        sq = [
            r
            for r in _all_receipts(dictionary)
            if r.kind == "EVALUATION" and r.model_family == la.SQ_FAMILY
        ]
        assert len(sq) == len(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines())
        for r in sq:
            disp = r.body["extra"]["producerDisposition"]
            assert r.body["verdict"] == la.SQ_DISPOSITION_TO_VERDICT[disp]
            cand = r.native_id.rsplit("|", 1)[1]
            assert r.body["overallResult"]["n"] == results["gates"][cand]["strata"]["ALL"]["cells"]

    def test_the_real_empty_stratum_is_insufficient_sample_not_zero(self, dictionary):
        sq = [
            r
            for r in _all_receipts(dictionary)
            if r.kind == "EVALUATION" and r.model_family == la.SQ_FAMILY
        ]
        for r in sq:
            in_season = [c for c in r.body["cohorts"] if c["cohort"] == {"stratum": "inSeason"}]
            assert in_season and in_season[0]["status"] == VERDICT_INSUFFICIENT
            assert in_season[0]["n"] == 0 and in_season[0]["metrics"] == {}

    def test_a_results_file_from_another_run_is_refused(self, dictionary):
        line = json.loads(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines()[0])
        results = _load(SQ_RESULTS)
        results["pins"] = {**results["pins"], "panelDigest": "0" * 64}
        with pytest.raises(ReceiptError, match="does not belong"):
            la.source_quality_receipts(
                line, archive_key=SQ_ARCHIVE_KEY, dictionary=dictionary, results=results
            )

    def test_an_unmapped_disposition_is_refused(self, dictionary):
        line = json.loads(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines()[0])
        line["disposition"] = "PROMOTE_NOW"
        with pytest.raises(ReceiptError, match="unmapped"):
            la.source_quality_receipts(line, archive_key=SQ_ARCHIVE_KEY, dictionary=dictionary)

    def test_archive_line_alone_keeps_n_unknown_with_a_reason(self, dictionary):
        line = json.loads(SQ_ARCHIVE.read_text(encoding="utf-8").splitlines()[0])
        ev = la.source_quality_receipts(line, archive_key=SQ_ARCHIVE_KEY, dictionary=dictionary)[-1]
        assert ev.body["overallResult"]["n"] is None and ev.body["overallResult"]["nReason"]

    def test_a_summary_without_scrape_time_offers_no_unprovable_input(self, dictionary):
        demo = _load(HILL_DEMO)["1_twoReplaysOfOnePinSet"]["a"]
        summary = {
            **demo,
            "snapshot": {k: demo["snapshot"][k] for k in ("resolved", "path", "sha256")},
        }
        _, features = la.hill_receipts_from_training_run(summary, dictionary=dictionary)
        assert features.slots["boardSnapshot"].to_dict()["state"] == "unobserved"


class TestFullTrainingRunRecord:
    """A full ``TrainingRun.record`` from the real producer (on its synthetic test tree)."""

    @pytest.fixture(scope="class")
    def uncommitted_run(self, tmp_path_factory):
        """One real ``execute`` (~30 s) shared by the class: a worktree run with no commit."""
        spec = importlib.util.spec_from_file_location(
            "al0_training_run_fixture", REPO / "tests" / "model_registry" / "test_training_run.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._run(mod._build_root(tmp_path_factory.mktemp("al0-hill")))

    @pytest.fixture(scope="class")
    def run(self, uncommitted_run):
        """The same record as a replay stamps it: ``inputsCommit`` names the commit the
        inputs were materialized at. It is a provenance label outside ``pinsHash``
        (``training_run._UNHASHED_FIELDS``), so the record still verifies."""
        record = {**copy.deepcopy(uncommitted_run.record), "inputsCommit": "0" * 40}
        return type(uncommitted_run)(params=dict(uncommitted_run.params), record=record)

    def test_full_record_round_trips_and_is_byte_identical_afterwards(self, run, dictionary):
        before = json.dumps(run.record, sort_keys=True)
        model, features = la.hill_receipts_from_training_run(run.record, dictionary=dictionary)
        assert json.dumps(run.record, sort_keys=True) == before
        assert model.body["recordForm"] == "full"
        assert model.body["challengerHash"] == run.challenger_hash
        offered = [features.slots["inputs"], *features.refs]
        assert all(r.known_at <= features.cutoff for r in offered)
        assert len(offered) == features.body["inputCount"]

    def test_inputs_with_no_provable_instant_are_not_offered(self, uncommitted_run, dictionary):
        """No commit and no measured data clock: the instant cannot be proven, so the
        input is listed as not offered rather than stamped with a guessed time."""
        _, features = la.hill_receipts_from_training_run(
            uncommitted_run.record, dictionary=dictionary
        )
        assert features.slots["inputs"].to_dict()["state"] == "unobserved"
        assert tuple(features.refs) == ()
        present = [
            r for r, p in uncommitted_run.record["inputs"].items() if p.get("sha256") != "missing"
        ]
        assert sorted(features.body["inputsNotOffered"]) == sorted(uncommitted_run.record["inputs"])
        assert present

    def test_an_edited_record_is_refused(self, run, dictionary):
        bad = copy.deepcopy(run.record)
        bad["config"]["fitTopN"] = 1
        with pytest.raises(ReceiptError, match="pinsHash"):
            la.hill_receipts_from_training_run(bad, dictionary=dictionary)


# ── A10: reproducible from pinned inputs ────────────────────────────────────


class TestReproducible:
    def test_two_derivations_are_byte_identical(self, dictionary):
        a = [r.to_dict() for r in _all_receipts(dictionary)]
        b = [r.to_dict() for r in _all_receipts(dictionary)]
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

    def test_two_replays_of_one_hill_pin_set_give_one_receipt(self, dictionary):
        demo = _load(HILL_DEMO)["1_twoReplaysOfOnePinSet"]
        ra = la.hill_receipts_from_training_run(demo["a"], dictionary=dictionary)
        rb = la.hill_receipts_from_training_run(demo["b"], dictionary=dictionary)
        assert [r.content_hash() for r in ra] == [r.content_hash() for r in rb]

    def test_reingest_is_a_pure_noop(self, dictionary, tmp_path):
        path = tmp_path / "r.sqlite"
        rs.append_receipts(_all_receipts(dictionary), path=path)
        again = rs.append_receipts(_all_receipts(dictionary), path=path)
        assert again["written"] == 0 and again["contentConflicts"] == [] and again["rejected"] == []
