"""AL-1a: prospective learning receipts for the shadow and evaluation producers.

``src/model_registry/producer_receipts.py`` plus the hooks in
``scripts/sparse_evidence_shadow.py``, ``scripts/joint_filter_shadow.py`` and
``scripts/source_quality_eval.py``. Pinned here, per producer:

* receipts are emitted with the right kinds and refs into the producer's OWN
  store (``producedFor`` = that run's native id), copying no observation;
* the point-in-time guard passes, and a board that cannot be proven known at the
  cutoff is ``Unobserved`` rather than offered as an input;
* a receipt failure is isolated: the producer's exit code and outputs are
  unchanged;
* the producer's outputs are byte-identical with and without receipts;
* re-runs are idempotent (stored duplicates, never a second receipt or a
  conflict) — including the re-run whose recorder returns a freshly stamped copy;
* end to end, one producer run's receipts form a resolvable chain.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.model_registry import learning_receipt as lr
from src.model_registry import producer_receipts as pr
from src.model_registry import receipt_store as rs
from src.model_registry.evaluation_receipt import (
    VERDICT_CHAMPION_RETAINED,
    VERDICT_INSUFFICIENT,
)
from src.model_registry.feature_dictionary import load_dictionary

REPO = Path(__file__).resolve().parents[2]
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"al1a_{name}", REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sha_tree(base: Path) -> dict[str, str]:
    return {
        p.relative_to(base).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(base.rglob("*"))
        if p.is_file()
    }


@pytest.fixture(scope="module")
def dictionary():
    return load_dictionary()


def _kinds(receipts) -> list[str]:
    return sorted(r.kind for r in receipts)


def _keys(obj, out: set[str]) -> set[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, out)
    return out


def _all_refs(receipt) -> list[lr.StoreRef]:
    return [*receipt.refs, *(s for s in receipt.slots.values() if isinstance(s, lr.StoreRef))]


# ── synthetic producer records ──────────────────────────────────────────────


def _sparse_contracts():
    inc = {
        "playersArray": [
            {
                "displayName": "Solo Player",
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": 300,
                "canonicalConsensusRank": 410,
                "singleSourceValuePenaltyApplied": True,
            },
            {"displayName": "Many Sources", "position": "RB", "rankDerivedValue": 5000},
        ]
    }
    ch = {
        "playersArray": [
            {
                "displayName": "Solo Player",
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": 900,
                "canonicalConsensusRank": 300,
                "sparseEvidence": {
                    "evidenceState": "absent_from_deeper_boards",
                    "state": "censor_bounded",
                    "observedFamily": "dlf",
                    "observationCount": 1,
                    "observedValue": 1000,
                    "centralEstimate": 900,
                    "sensitivityInterval": {"low": 700, "high": 1000, "label": "uncalibrated"},
                },
            },
            {"displayName": "Many Sources", "position": "RB", "rankDerivedValue": 5000},
        ]
    }
    return inc, ch


def _sparse_record(*, recorded_at: datetime, scrape: str | None = "2026-10-01T06:00:00Z"):
    from src.api import sparse_evidence_shadow as shadow

    inc, ch = _sparse_contracts()
    rows, counts = shadow.shadow_rows(inc, ch)
    return shadow.assemble_record(
        board={
            "source": "exports/latest/dynasty_data_2026-10-01.json",
            "payloadSha256": "a" * 64,
            "scrapeTimestamp": scrape,
            "boardHashIncumbent": "b" * 64,
            "boardHashChallenger": "c" * 64,
            "rows": 2,
            "payloadAgeHours": 2.0,
            "staleBudgetHours": 6,
        },
        pins={
            "codeRevision": "0123456789abcdef0123456789abcdef01234567",
            "workingTreeDirty": False,
            "inputsSha256": "d" * 64,
            "flagsAtRecord": {"sparse_evidence_estimator": False, "x": True},
            "estimator": "sparse-censor-v1",
            "singleSourceRetention": 0.3,
        },
        rows=rows,
        counts=counts,
        recorded_at=recorded_at.isoformat(),
    )


def _meta(value: float, weight: float = 1.0, **extra) -> dict:
    return {"valueContribution": value, "appliedWeight": weight, **extra}


def _row(name, metas, *, dropped=(), reasons=None, value=5000, rank=1, cls="offense"):
    row = {
        "displayName": name,
        "assetClass": cls,
        "position": "WR",
        "sourceRankMeta": metas,
        "droppedSources": list(dropped),
        "rankDerivedValue": value,
        "canonicalConsensusRank": rank,
    }
    if reasons:
        row["jointFilterReasons"] = reasons
    return row


FIVE = {
    "dlfSf": 5000,
    "fantasyProsSf": 5100,
    "fantasyCalc": 4900,
    "dynastyDaddySf": 5050,
    "ktcCrowdSfTep": 9000,
}


def _robust_contracts(shift: int = 0):
    metas = {s: _meta(v + shift) for s, v in FIVE.items()}
    inc = {
        "playersArray": [
            _row("Alpha", metas, dropped=["ktcCrowdSfTep"], value=5000, rank=1),
            _row("Charlie", metas, value=3000, rank=3),
        ]
    }
    ch = {
        "playersArray": [
            _row(
                "Alpha",
                metas,
                dropped=["fantasyCalc"],
                reasons={"fantasyCalc": "outlier", "ktcCrowdSfTep": "dominant_evidence_kept"},
                value=5600,
                rank=1,
            ),
            _row("Charlie", metas, value=3000, rank=3),
        ]
    }
    return inc, ch


def _robust_pins() -> dict:
    return {
        "codeRevision": "fedcba9876543210fedcba9876543210fedcba98",
        "workingTreeDirty": False,
        "pipelineFingerprint": "e" * 64,
        "flagsAtRecord": {"joint_outlier_sparse_challenger": False},
        "variants": {
            "incumbent": {"joint_outlier_sparse_challenger": False},
            "challenger": {"joint_outlier_sparse_challenger": True},
        },
        "hampel": {"k": 3.0, "minN": 4, "minThreshold": 150.0},
        "familyCap": 1.0,
        "csvTreeSha256": "1" * 64,
        "stateTreeSha256": "2" * 64,
        "inputs": "live tree",
    }


def _robust_record(*, recorded_at: datetime, scrape: str = "2026-10-01T06:00:00Z"):
    from src.robust_filter_shadow import record as R

    inc, ch = _robust_contracts()
    rec = R.assemble_record(
        mode=R.MODE_LIVE,
        board={
            "source": "exports/latest/dynasty_data_2026-10-01.json",
            "payloadSha256": "f" * 64,
            "scrapeTimestamp": scrape,
            "completeness": "complete",
            "votingSources": sorted(FIVE),
            "votingFamilies": ["dlf"],
            "boardHashIncumbent": "3" * 64,
            "boardHashChallenger": "4" * 64,
        },
        pins=_robust_pins(),
        comparison=R.shadow_record(inc, ch),
        recorded_at=recorded_at.isoformat(),
    )
    rec["panel"] = "panels/ffffffffffffffff_0123456789abcdef.json.gz"
    return rec


# ── 1. sparse-evidence shadow: kinds, refs, point in time ───────────────────


class TestSparseReceipts:
    def test_kinds_and_refs(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        receipts = pr.sparse_evidence_receipts(
            rec, ledger_name="ledger-2026-10.jsonl", dictionary=dictionary
        )
        assert _kinds(receipts) == sorted(
            ["MODEL", "MODEL", "CHALLENGER", "OBSERVATION", "FEATURES", "PREDICTION", "PREDICTION"]
        )
        by_kind = {}
        for r in receipts:
            by_kind.setdefault(r.kind, []).append(r)
        for p in by_kind["PREDICTION"]:
            ref = p.slots["predictionSet"]
            assert ref.store == "sparse_evidence_shadow_ledger"
            assert ref.role == lr.ROLE_ARTIFACT and ref.produced_for == p.native_id
            side = p.body["side"]
            assert ref.key == f"ledger-2026-10.jsonl#{rec['key']}/{side}"
            assert lr.is_own_artifact(p, ref)
            assert p.prediction_id == lr.prediction_id(pr.SPARSE_PRODUCER, p.native_id)
            assert p.cutoff == T0 and p.body["outcomeSettled"] is False
        obs = by_kind["OBSERVATION"][0]
        board = obs.slots["board"]
        assert board.store == "repo_file" and board.role == lr.ROLE_INPUT
        assert board.key.endswith("@sha256:" + "a" * 64)
        assert board.known_at == datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)
        inc_m, ch_m = pr.sparse_model_ids(rec)
        assert {m.model_version_id for m in by_kind["MODEL"]} == {inc_m, ch_m}
        assert by_kind["CHALLENGER"][0].body["championModelVersionId"] == inc_m
        for r in receipts:
            if r.kind in ("MODEL", "CHALLENGER"):
                assert r.body["promotes"] is False

    def test_no_observation_is_copied(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        receipts = pr.sparse_evidence_receipts(rec, ledger_name="l.jsonl", dictionary=dictionary)
        text = json.dumps([r.to_dict() for r in receipts])
        assert "Solo Player" not in text and "Many Sources" not in text
        assert "rows" not in _keys([r.to_dict() for r in receipts], set())

    def test_a_board_scraped_after_the_run_is_unobserved_not_an_input(self, dictionary):
        rec = _sparse_record(recorded_at=T0, scrape="2026-10-01T09:00:00Z")
        obs = next(
            r
            for r in pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)
            if r.kind == "OBSERVATION"
        )
        assert isinstance(obs.slots["board"], lr.Unobserved)
        assert "after the run's recordedAt" in obs.slots["board"].reason

    def test_a_board_without_a_scrape_time_is_unobserved(self, dictionary):
        rec = _sparse_record(recorded_at=T0, scrape=None)
        obs = next(
            r
            for r in pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)
            if r.kind == "OBSERVATION"
        )
        assert isinstance(obs.slots["board"], lr.Unobserved)

    def test_property_point_in_time_never_violated(self, dictionary):
        rng = random.Random(1597)
        for _ in range(150):
            recorded = T0 + timedelta(seconds=rng.randrange(-3 * 86400, 3 * 86400))
            scraped = T0 + timedelta(seconds=rng.randrange(-3 * 86400, 3 * 86400))
            rec = _sparse_record(recorded_at=recorded, scrape=scraped.isoformat())
            receipts = pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)
            for r in receipts:
                lr.validate_receipt(r)
                for ref in _all_refs(r):
                    if ref.role == lr.ROLE_INPUT:
                        assert ref.known_at <= r.cutoff
            board = next(r for r in receipts if r.kind == "OBSERVATION").slots["board"]
            assert isinstance(board, lr.StoreRef) == (scraped <= recorded)

    def test_a_record_without_a_code_revision_is_refused(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        rec["pins"]["codeRevision"] = None
        with pytest.raises(lr.ReceiptError):
            pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)

    def test_an_unknown_tree_state_is_named_never_assumed_clean(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        rec["pins"]["workingTreeDirty"] = None
        inc, ch = pr.sparse_model_ids(rec)
        assert "-treeunknown-" in inc and "-treeunknown-" in ch


# ── 2. robust-filter shadow: kinds, refs, evaluation ────────────────────────


class TestRobustReceipts:
    def test_kinds_and_refs(self, dictionary):
        rec = _robust_record(recorded_at=T0)
        receipts = pr.robust_filter_receipts(rec, ledger_name="ledger.jsonl", dictionary=dictionary)
        assert _kinds(receipts) == sorted(
            ["MODEL", "MODEL", "CHALLENGER", "OBSERVATION", "FEATURES", "PREDICTION", "PREDICTION"]
        )
        obs = next(r for r in receipts if r.kind == "OBSERVATION")
        assert obs.slots["sourceCsvTree"].store == "repo_file"
        assert obs.slots["datasetStateTree"].store == "dataset_state"
        assert obs.slots["datasetStateTree"].known_at == T0
        feats = next(r for r in receipts if r.kind == "FEATURES")
        panel = feats.slots["observationPanel"]
        assert panel.store == "robust_filter_shadow_ledger" and panel.key == rec["panel"]
        for p in (r for r in receipts if r.kind == "PREDICTION"):
            ref = p.slots["predictionSet"]
            assert ref.store == "robust_filter_shadow_ledger" and lr.is_own_artifact(p, ref)
            assert ref.key == f"ledger.jsonl#{rec['key']}/{p.body['side']}"
        challenger = next(r for r in receipts if r.body.get("side") == "challenger")
        assert challenger.body["safeguardsFired"]["counts"]["dominant_evidence_kept"] == 1

    def test_a_missing_tree_is_unobserved(self, dictionary):
        rec = _robust_record(recorded_at=T0)
        rec["pins"]["stateTreeSha256"] = None
        obs = next(
            r
            for r in pr.robust_filter_receipts(rec, ledger_name="l", dictionary=dictionary)
            if r.kind == "OBSERVATION"
        )
        assert isinstance(obs.slots["datasetStateTree"], lr.Unobserved)

    @staticmethod
    def _evaluation(verdict, *, k=40, x=35, lo=-0.05, hi=-0.01):
        side = {"n": k, "meanLeadShare": {"point": 0.1, "lo95": 0.0, "hi95": 0.2, "blocks": 5}}
        sides = {
            "K": side,
            "X": {**side, "n": x},
            "R": {"n": 0, "meanLeadShare": {"point": None}},
        }
        summary = {
            "sides": sides,
            "delta": {
                "point": (lo + hi) / 2,
                "lo95": lo,
                "hi95": hi,
                "blocks": 5,
                "resamplesUsed": 4000,
            },
        }
        return {
            "schema": "joint-filter-shadow/v1/evaluation",
            "mode": "live_shadow",
            "preregistration": pr.ROBUST_PREREGISTRATION,
            "computedAt": "2026-10-09T00:00:00Z",
            "codeRevisions": ["fedcba"],
            "primary": {
                "boards": 12,
                "originDays": 11,
                "span": ["2026-09-28", "2026-10-09"],
                "horizons": {"7": summary, "3": summary},
                "decision": {
                    "verdict": verdict,
                    "reasons": ["x"],
                    "minimumSample": {"met": True},
                    "accumulation": None,
                },
            },
        }

    def test_a_settled_evaluation_maps_the_producer_verdict_with_sample_sizes(self, dictionary):
        records = [_robust_record(recorded_at=T0 + timedelta(hours=h)) for h in (0, 5)]
        records[1]["key"] = "k2"
        r = pr.robust_evaluation_receipt(
            self._evaluation("NOT_BETTER"),
            records,
            evaluation_name="evaluation_live_shadow.json",
            evaluator_revision="abc123",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        )
        lr.validate_receipt(r)
        assert r.kind == "EVALUATION" and r.cutoff == T0 + timedelta(hours=5)
        body = r.body
        assert body["verdict"] == VERDICT_CHAMPION_RETAINED and body["promotes"] is False
        assert body["overallResult"]["n"] == 75
        assert body["overallResult"]["metrics"]["deltaLeadShare"]["interval"] == [-0.05, -0.01]
        agreed = [c for c in body["cohorts"] if c["cohort"]["side"] == "R_agreed"]
        assert agreed and all(c["status"] == "insufficient_sample" for c in agreed)
        assert all(c["metrics"] == {} for c in agreed)
        assert body["extra"]["producerVerdict"] == "NOT_BETTER"

    def test_an_insufficient_producer_verdict_is_insufficient_sample(self, dictionary):
        r = pr.robust_evaluation_receipt(
            self._evaluation("INSUFFICIENT", k=3, x=0),
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        )
        assert r.body["verdict"] == VERDICT_INSUFFICIENT

    def test_no_decision_is_insufficient_never_a_zero_score(self, dictionary):
        ev = self._evaluation("INCONCLUSIVE")
        ev["primary"] = {"boards": 1, "originDays": 0, "horizons": {}, "decision": None}
        r = pr.robust_evaluation_receipt(
            ev,
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        )
        assert r.body["verdict"] == VERDICT_INSUFFICIENT
        assert r.body["overallResult"]["n"] is None and r.body["overallResult"]["nReason"]

    def test_an_unmapped_verdict_is_refused(self, dictionary):
        with pytest.raises(lr.ReceiptError, match="unmapped"):
            pr.robust_evaluation_receipt(
                self._evaluation("PROMOTE_NOW"),
                [_robust_record(recorded_at=T0)],
                evaluation_name="e.json",
                evaluator_revision="abc",
                evaluator_tree_dirty=False,
                dictionary=dictionary,
            )

    def test_the_evaluation_identity_ignores_the_wall_clock(self, dictionary):
        records = [_robust_record(recorded_at=T0)]
        a = self._evaluation("INCONCLUSIVE")
        b = {**a, "computedAt": "2027-01-01T00:00:00Z"}
        ra, rb = (
            pr.robust_evaluation_receipt(
                e,
                records,
                evaluation_name="e.json",
                evaluator_revision="r",
                evaluator_tree_dirty=False,
                dictionary=dictionary,
            )
            for e in (a, b)
        )
        assert ra.receipt_id == rb.receipt_id and ra.content_hash() == rb.content_hash()


def test_writers_are_pinned_to_the_producer_constants():
    assert lr.ARTIFACT_STORE_WRITERS[pr.ROBUST_STORE] == {pr.ROBUST_PRODUCER}
    assert lr.ARTIFACT_STORE_WRITERS[pr.SPARSE_STORE] == {pr.SPARSE_PRODUCER}
    assert {pr.ROBUST_STORE, pr.SPARSE_STORE} <= lr.ARTIFACT_STORES


def test_no_receipt_carries_a_canonical_or_contract_field(dictionary):
    from src.league_intel.overlay import CANONICAL_VALUE_FIELDS

    forbidden = {*CANONICAL_VALUE_FIELDS, "canonicalConsensusRank", "confidenceBucket"}
    receipts = [
        *pr.sparse_evidence_receipts(
            _sparse_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
        ),
        *pr.robust_filter_receipts(
            _robust_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
        ),
    ]
    keys = _keys([r.to_dict() for r in receipts], set())
    assert not keys & forbidden


# ── failure isolation (library level) ────────────────────────────────────────


class TestEmitSafely:
    def test_a_refused_store_path_is_logged_and_swallowed(self, dictionary):
        target = REPO / "config" / "al1a_must_not_exist.sqlite"
        logs: list[str] = []
        out = pr.emit_safely(
            lambda: pr.sparse_evidence_receipts(
                _sparse_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
            ),
            label="t",
            path=target,
            log=logs.append,
        )
        assert out["ok"] is False and "StorePathError" in out["error"]
        assert not target.exists()
        assert any("NOT written" in m for m in logs)

    def test_an_adapter_failure_is_swallowed(self, tmp_path):
        def boom():
            raise RuntimeError("adapter exploded")

        out = pr.emit_safely(boom, label="t", path=tmp_path / "r.sqlite", log=lambda _m: None)
        assert out["ok"] is False and out["error"] == "RuntimeError: adapter exploded"
        assert out["receiptFailures"] == 1
        assert out["cause"] == "the receipts could not be built or stored"
        assert not (tmp_path / "r.sqlite").exists()

    def test_an_unwritable_store_is_a_named_warning(
        self, tmp_path, monkeypatch, caplog, dictionary
    ):
        """L5: a permissions failure is never silent -- WARNING level, cause named,
        and a failure counter on the result."""

        def denied(*_a, **_k):
            raise PermissionError(13, "Permission denied", str(tmp_path / "r.sqlite"))

        monkeypatch.setattr(rs, "append_receipts", denied)
        logs: list[str] = []
        with caplog.at_level("WARNING", logger=pr.__name__):
            out = pr.emit_safely(
                lambda: pr.sparse_evidence_receipts(
                    _sparse_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
                ),
                label="t",
                path=tmp_path / "r.sqlite",
                log=logs.append,
            )
        assert out["ok"] is False and out["receiptFailures"] == 1
        assert out["cause"] == "the receipt store is unwritable or unreachable"
        assert any(
            r.levelname == "WARNING" and "unwritable" in r.getMessage() for r in caplog.records
        )
        assert any(m.startswith("WARNING:") and "receipt_failures=1" in m for m in logs)

    def test_a_database_failure_is_swallowed(self, tmp_path, monkeypatch, dictionary):
        def locked(*_a, **_k):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(rs, "append_receipts", locked)
        out = pr.emit_safely(
            lambda: pr.robust_filter_receipts(
                _robust_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
            ),
            label="t",
            path=tmp_path / "r.sqlite",
            log=lambda _m: None,
        )
        assert out["ok"] is False and "locked" in out["error"]


# ── producer 1 wiring: the sparse-evidence CLI ───────────────────────────────


class _Clock:
    def __init__(self, at: datetime):
        self.at = at

    def install(self, monkeypatch, module):
        clock = self

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return clock.at if tz is None else clock.at.astimezone(tz)

        monkeypatch.setattr(module, "datetime", FrozenDatetime)


@pytest.fixture()
def sparse_cli(tmp_path, monkeypatch):
    from src.api import sparse_evidence_shadow as shadow
    from src.api import value_replay as vr

    cli = _load_script("sparse_evidence_shadow")
    monkeypatch.setattr(shadow, "build_pair", lambda raw: _sparse_contracts())
    monkeypatch.setattr(
        vr,
        "pins",
        lambda path, root=None: {
            "codeRevision": "0123456789abcdef0123456789abcdef01234567",
            "workingTreeDirty": False,
            "singleSourceRetention": 0.3,
            "sourceCsvs": {"a.csv": "1"},
        },
    )
    clock = _Clock(T0)
    clock.install(monkeypatch, shadow)
    # The CLI computes the payload's age from its own wall clock; freeze it too, or
    # two runs a few seconds apart can differ in ``payloadAgeHours`` (a producer
    # property unrelated to receipts).
    clock.install(monkeypatch, cli)
    payload = tmp_path / "payload" / "dynasty_data_2026-10-01.json"
    payload.parent.mkdir()
    payload.write_text(
        json.dumps({"scrapeTimestamp": "2026-10-01T06:00:00Z", "players": {}}), encoding="utf-8"
    )

    def run(ledger: Path, store: Path | None, *extra: str) -> int:
        argv = ["record", "--payload", str(payload), "--dir", str(ledger), "--allow-stale"]
        argv += ["--learning-store", str(store)] if store else []
        return cli.main([*argv, *extra])

    return run, clock, cli


class TestSparseWiring:
    def test_emits_receipts_and_reruns_are_idempotent(self, sparse_cli, tmp_path):
        run, clock, _cli = sparse_cli
        store = tmp_path / "learning" / "receipts.sqlite"
        assert run(tmp_path / "ledger", store) == 0
        stored = list(rs.iter_receipts(store))
        assert sorted(s["kind"] for s in stored) == sorted(
            ["MODEL", "MODEL", "CHALLENGER", "OBSERVATION", "FEATURES", "PREDICTION", "PREDICTION"]
        )
        # A later re-run on the same board: the recorder returns a FRESHLY stamped
        # copy; receipts are built from the stored line, so nothing new is written.
        clock.at = T0 + timedelta(hours=3)
        out = rs.append_receipts(  # direct: what the hook does, observed
            pr.sparse_evidence_receipts(
                next(iter(_stored_lines(tmp_path / "ledger"))),
                ledger_name="ledger-2026-10.jsonl",
                dictionary=load_dictionary(),
            ),
            path=store,
        )
        assert out["written"] == 0 and out["contentConflicts"] == [] and out["duplicates"] == 7
        assert run(tmp_path / "ledger", store) == 0
        assert len(list(rs.iter_receipts(store))) == 7
        assert {s["receiptId"] for s in rs.iter_receipts(store)} == {s["receiptId"] for s in stored}

    def test_ledger_bytes_are_identical_with_and_without_receipts(self, sparse_cli, tmp_path):
        run, _clock, _cli = sparse_cli
        assert run(tmp_path / "with", tmp_path / "s" / "r.sqlite") == 0
        assert run(tmp_path / "without", None, "--no-learning-receipts") == 0
        assert _sha_tree(tmp_path / "with") == _sha_tree(tmp_path / "without")

    def test_a_store_failure_never_changes_the_exit_code_or_the_ledger(self, sparse_cli, tmp_path):
        run, _clock, _cli = sparse_cli
        bad = REPO / "config" / "al1a_must_not_exist.sqlite"
        assert run(tmp_path / "bad", bad) == 0
        assert not bad.exists()
        assert run(tmp_path / "good", None, "--no-learning-receipts") == 0
        assert _sha_tree(tmp_path / "bad") == _sha_tree(tmp_path / "good")

    def test_an_adapter_failure_never_changes_the_exit_code(
        self, sparse_cli, tmp_path, monkeypatch
    ):
        run, _clock, _cli = sparse_cli

        def boom(*_a, **_k):
            raise RuntimeError("adapter exploded")

        monkeypatch.setattr(pr, "sparse_evidence_receipts", boom)
        assert run(tmp_path / "ledger", tmp_path / "s" / "r.sqlite") == 0
        assert list((tmp_path / "ledger").glob("ledger-*.jsonl"))


def _stored_lines(base: Path):
    from src.api import sparse_evidence_shadow as shadow

    return list(shadow.iter_all_records(base))


# ── producer 2 wiring: the joint-filter CLI (record + evaluate) ──────────────


@pytest.fixture()
def robust_cli(tmp_path, monkeypatch):
    from src.robust_filter_shadow import record as R

    jfs = _load_script("joint_filter_shadow")
    root = tmp_path / "box"
    (root / "exports" / "latest").mkdir(parents=True)
    state = {"at": T0, "shift": 0}

    def write_payload(day: int):
        path = root / "exports" / "latest" / "dynasty_data_2026-10-01.json"
        scrape = (T0 + timedelta(days=day) - timedelta(hours=2)).isoformat()
        path.write_text(json.dumps({"scrapeTimestamp": scrape, "day": day}), encoding="utf-8")
        state["shift"] = day * 10

    monkeypatch.setattr(jfs, "REPO_ROOT", root)
    monkeypatch.setattr(jfs, "_base_pins", _robust_pins)
    monkeypatch.setattr(jfs, "_board_hash", lambda c: hashlib.sha256(b"x").hexdigest())
    monkeypatch.setattr(jfs, "_now", lambda: state["at"].isoformat().replace("+00:00", "Z"))
    monkeypatch.setattr(jfs, "_git", lambda *a, **k: "evaluatorrev\n")
    monkeypatch.setattr(jfs, "_evaluator_identity", lambda: ("evaluatorrev", False, None))
    monkeypatch.setattr(
        R, "build_pair", lambda raw, csv_root=None: _robust_contracts(state["shift"])
    )
    monkeypatch.setattr(R, "tree_sha256", lambda *a, **k: "9" * 64)

    def run(ledger: Path, store: Path | None, *argv: str) -> int:
        top = ["--dir", str(ledger)]
        top += ["--learning-store", str(store)] if store else ["--no-learning-receipts"]
        return jfs.main([*top, *argv])

    run.jfs = jfs  # the patched module, for tests that drive it below the CLI
    return run, state, write_payload


class TestRobustWiring:
    def test_record_and_evaluate_emit_receipts_idempotently(self, robust_cli, tmp_path):
        run, state, write_payload = robust_cli
        store = tmp_path / "learning" / "receipts.sqlite"
        ledger = tmp_path / "ledger"
        for day in range(3):
            write_payload(day)
            state["at"] = T0 + timedelta(days=day)
            assert run(ledger, store, "record") == 0
        assert run(ledger, store, "evaluate", "--mode", "live_shadow") == 0
        stored = list(rs.iter_receipts(store))
        kinds = sorted(s["kind"] for s in stored)
        assert kinds.count("PREDICTION") == 6 and kinds.count("OBSERVATION") == 3
        assert kinds.count("EVALUATION") == 1
        ev = next(s for s in stored if s["kind"] == "EVALUATION")
        # Three boards cannot meet the preregistered minimum: the producer says
        # INSUFFICIENT and the receipt says insufficient_sample, never a score.
        assert ev["body"]["verdict"] == VERDICT_INSUFFICIENT
        assert ev["cutoff"] == (T0 + timedelta(days=2)).isoformat()
        n_before = len(stored)
        # re-record the newest board (later clock) and re-evaluate: duplicates only
        state["at"] = T0 + timedelta(days=2, hours=4)
        assert run(ledger, store, "record") == 0
        assert run(ledger, store, "evaluate", "--mode", "live_shadow") == 0
        assert len(list(rs.iter_receipts(store))) == n_before

    def test_ledger_and_panels_are_byte_identical_with_and_without_receipts(
        self, robust_cli, tmp_path
    ):
        run, state, write_payload = robust_cli
        write_payload(0)
        assert run(tmp_path / "with", tmp_path / "s" / "r.sqlite", "record", "--then-evaluate") == 0
        assert run(tmp_path / "without", None, "record", "--then-evaluate") == 0
        assert _sha_tree(tmp_path / "with") == _sha_tree(tmp_path / "without")

    def test_a_store_failure_never_changes_the_exit_code(self, robust_cli, tmp_path):
        run, _state, write_payload = robust_cli
        write_payload(0)
        bad = REPO / "config" / "al1a_must_not_exist.sqlite"
        assert run(tmp_path / "bad", bad, "record", "--then-evaluate") == 0
        assert not bad.exists()
        assert run(tmp_path / "good", None, "record", "--then-evaluate") == 0
        assert _sha_tree(tmp_path / "bad") == _sha_tree(tmp_path / "good")


# ── producer 3 wiring: the source-quality evaluator hook ─────────────────────


def test_source_quality_hook_emits_the_al0_adapter_receipts_and_isolates_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(pr.RECEIPTS_ENABLED_ENV, "1")
    sq = REPO / "docs" / "valuation" / "evidence" / "source-quality-2026-10-01"
    results = json.loads((sq / "results_2026-09-30.json").read_text(encoding="utf-8"))
    lines = [
        json.loads(x) for x in (sq / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cli = _load_script("source_quality_eval")
    before = _sha_tree(sq)
    store = tmp_path / "learning" / "r.sqlite"

    class Args:
        no_learning_receipts = False
        learning_store = store

    cli.emit_learning_receipts(
        Args, results, lines, sq / "evaluations.jsonl", sq / "results_2026-09-30.json"
    )
    stored = list(rs.iter_receipts(store))
    assert sorted({s["kind"] for s in stored}) == ["CHALLENGER", "EVALUATION", "MODEL"]
    assert sum(1 for s in stored if s["kind"] == "EVALUATION") == len(lines)
    assert _sha_tree(sq) == before
    Args.learning_store = REPO / "config" / "al1a_must_not_exist.sqlite"
    cli.emit_learning_receipts(  # must not raise
        Args, results, lines, sq / "evaluations.jsonl", sq / "results_2026-09-30.json"
    )
    assert not Args.learning_store.exists()


# ── end to end: one producer run's receipts form a resolvable chain ──────────


def test_end_to_end_chain_for_one_sparse_run(sparse_cli, tmp_path):
    run, _clock, _cli = sparse_cli
    store = tmp_path / "learning" / "receipts.sqlite"
    ledger = tmp_path / "ledger"
    assert run(ledger, store) == 0
    stored = {s["receiptId"]: s for s in rs.iter_receipts(store)}
    predictions = [s for s in stored.values() if s["kind"] == "PREDICTION"]
    assert {p["body"]["side"] for p in predictions} == {"incumbent", "challenger"}
    line = _stored_lines(ledger)[0]
    for p in predictions:
        body = p["body"]
        for link in ("observationReceiptId", "featuresReceiptId", "challengerReceiptId"):
            assert body[link] in stored, link
        model = stored[body["modelReceiptId"]]
        assert model["kind"] == "MODEL" and model["modelVersionId"] == p["modelVersionId"]
        # the prediction points INTO the producer's own ledger line, by key
        ref = p["slots"]["predictionSet"]
        file_name, _, rest = ref["key"].partition("#")
        key, _, side = rest.partition("/")
        assert (ledger / file_name).is_file() and key == line["key"] and side == body["side"]
        assert ref["producedFor"] == p["nativeId"] == f"{key}|{side}"
        assert ref["knownAt"] == line["recordedAt"] == p["cutoff"]
    challenger = stored[predictions[0]["body"]["challengerReceiptId"]]
    sides = {p["body"]["side"]: p["modelVersionId"] for p in predictions}
    assert challenger["body"]["championModelVersionId"] == sides["incumbent"]
    assert challenger["body"]["challengerModelVersionId"] == sides["challenger"]
    obs = stored[predictions[0]["body"]["observationReceiptId"]]
    assert obs["slots"]["board"]["key"].endswith("@sha256:" + line["board"]["payloadSha256"])
    feats = stored[predictions[0]["body"]["featuresReceiptId"]]
    from src.model_registry.feature_dictionary import validate_manifest

    assert feats["body"]["featureManifestHash"] == validate_manifest(
        load_dictionary(), consumer=pr.SPARSE_FAMILY, features=pr.SPARSE_FEATURES
    )
    # no receipt is a promotion, and nothing claims an outcome yet
    assert all(
        s["kind"] not in ("PROMOTION_RECORD", "OUTCOME", "EVALUATION") for s in stored.values()
    )


# ── review fixes (#1612): replay, unknown blocks, tree pins, evaluator identity ──


def test_the_live_mode_constant_is_the_producers():
    from src.robust_filter_shadow import record as R

    assert pr.ROBUST_LIVE_MODE == R.MODE_LIVE


class TestReplayIsNeverProspective:
    """M1: a hindsight replay never yields a prospective EVALUATION (or any receipt)."""

    def test_a_replay_evaluation_is_refused(self, dictionary):
        ev = TestRobustReceipts._evaluation("NOT_BETTER")
        ev["mode"] = "historical_replay"
        records = [_robust_record(recorded_at=T0)]
        records[0]["mode"] = "historical_replay"
        with pytest.raises(lr.ReceiptError, match="retrospective"):
            pr.robust_evaluation_receipt(
                ev,
                records,
                evaluation_name="e.json",
                evaluator_revision="r",
                evaluator_tree_dirty=False,
                dictionary=dictionary,
            )

    def test_a_live_evaluation_over_a_replayed_line_is_refused(self, dictionary):
        records = [_robust_record(recorded_at=T0)]
        records[0]["mode"] = "historical_replay"
        with pytest.raises(lr.ReceiptError, match="historical_replay"):
            pr.robust_evaluation_receipt(
                TestRobustReceipts._evaluation("NOT_BETTER"),
                records,
                evaluation_name="e.json",
                evaluator_revision="r",
                evaluator_tree_dirty=False,
                dictionary=dictionary,
            )

    def test_a_replayed_ledger_line_yields_no_receipts(self, dictionary):
        rec = _robust_record(recorded_at=T0)
        rec["mode"] = "historical_replay"
        with pytest.raises(lr.ReceiptError, match="hindsight"):
            pr.robust_filter_receipts(rec, ledger_name="l", dictionary=dictionary)

    def test_the_cli_replay_evaluation_writes_no_receipt(self, robust_cli, tmp_path):
        from src.robust_filter_shadow import record as R

        run, state, write_payload = robust_cli
        jfs = run.jfs
        ledger = tmp_path / "ledger"
        store = tmp_path / "learning" / "receipts.sqlite"
        for day in range(3):
            write_payload(day)
            state["at"] = T0 + timedelta(days=day)
            payload = jfs.REPO_ROOT / "exports" / "latest" / "dynasty_data_2026-10-01.json"
            raw = json.loads(payload.read_text(encoding="utf-8"))
            board = {
                "archive": f"replay-{day}",
                "payloadSha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
                "scrapeTimestamp": raw["scrapeTimestamp"],
                "completeness": "complete",
            }
            assert jfs.record_board(
                raw,
                mode=R.MODE_REPLAY,
                board=board,
                pins={**_robust_pins(), "inputs": "archived"},
                base=ledger,
                csv_root=None,
            )
        # ``evaluate`` defaults to historical_replay: the evaluation is written,
        # and no receipt of any kind reaches the store.
        assert run(ledger, store, "evaluate") == 0
        assert (ledger / "evaluation_historical_replay.json").is_file()
        assert not store.exists() or list(rs.iter_receipts(store)) == []


class TestUnknownIsNotZero:
    """L1: a missing block is unobserved, never ``{}`` / ``[]`` / 0."""

    def test_missing_sparse_blocks_are_unobserved(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        del rec["counts"], rec["evidenceStates"]
        predictions = [
            p
            for p in pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)
            if p.kind == "PREDICTION"
        ]
        assert len(predictions) == 2
        for p in predictions:
            assert p.body["producerCounts"]["state"] == "unobserved"
            assert p.body["evidenceStates"]["state"] == "unobserved"
            assert "never zero" in p.body["producerCounts"]["reason"]

    def test_a_present_empty_block_keeps_its_counter_semantics(self, dictionary):
        rec = _sparse_record(recorded_at=T0)
        rec["counts"] = {}
        p = next(
            r
            for r in pr.sparse_evidence_receipts(rec, ledger_name="l", dictionary=dictionary)
            if r.kind == "PREDICTION"
        )
        assert p.body["producerCounts"] == {"counts": {}, "semantics": pr.COUNTS_SEMANTICS}

    def test_missing_robust_blocks_are_unobserved(self, dictionary):
        rec = _robust_record(recorded_at=T0)
        del rec["counts"], rec["safeguardsFired"], rec["topChurn"]
        del rec["board"]["votingFamilies"]
        receipts = pr.robust_filter_receipts(rec, ledger_name="l", dictionary=dictionary)
        obs = next(r for r in receipts if r.kind == "OBSERVATION")
        assert obs.body["votingFamilies"]["state"] == "unobserved"
        challenger = next(r for r in receipts if r.body.get("side") == "challenger")
        for field in ("producerCounts", "safeguardsFired", "topChurnVsIncumbent"):
            assert challenger.body[field]["state"] == "unobserved", field

    def test_missing_model_pins_are_unobserved(self, dictionary):
        rec = _robust_record(recorded_at=T0)
        del rec["pins"]["hampel"], rec["pins"]["variants"]
        models = [
            r
            for r in pr.robust_filter_receipts(rec, ledger_name="l", dictionary=dictionary)
            if r.kind == "MODEL"
        ]
        assert len(models) == 2
        assert all(m.body["hampel"]["state"] == "unobserved" for m in models)
        assert all(m.body["variantFlags"]["state"] == "unobserved" for m in models)


def test_the_input_tree_pins_are_nearest_prior_not_exact(dictionary):
    """L2: the trees are hashed before the build re-reads them; the receipt says so."""
    obs = next(
        r
        for r in pr.robust_filter_receipts(
            _robust_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
        )
        if r.kind == "OBSERVATION"
    )
    for slot in ("sourceCsvTree", "datasetStateTree"):
        ref = obs.slots[slot]
        assert ref.fidelity == "nearest-prior", slot
        assert "not excluded" in ref.basis


class TestEvaluatorIdentity:
    """L3: a dirty evaluator tree is keyed, never a conflict; no orphan model ids."""

    @staticmethod
    def _receipt(dictionary, **kw):
        return pr.robust_evaluation_receipt(
            TestRobustReceipts._evaluation("NOT_BETTER"),
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            dictionary=dictionary,
            **kw,
        )

    def test_a_dirty_tree_is_keyed_by_its_digest(self, dictionary):
        clean = self._receipt(dictionary, evaluator_tree_dirty=False)
        a = self._receipt(dictionary, evaluator_tree_dirty=True, evaluator_tree_digest="1" * 64)
        a2 = self._receipt(dictionary, evaluator_tree_dirty=True, evaluator_tree_digest="1" * 64)
        b = self._receipt(dictionary, evaluator_tree_dirty=True, evaluator_tree_digest="2" * 64)
        assert len({clean.receipt_id, a.receipt_id, b.receipt_id}) == 3
        assert a.receipt_id == a2.receipt_id and a.content_hash() == a2.content_hash()
        assert "-dirty-" in a.native_id and "-dirty-" not in clean.native_id
        assert a.body["extra"]["evaluatorTreeDirty"] is True
        assert clean.body["extra"]["evaluatorTreeDirty"] is False

    def test_an_unknown_tree_state_is_refused(self, dictionary):
        with pytest.raises(lr.ReceiptError, match="cannot be assumed clean"):
            self._receipt(dictionary, evaluator_tree_dirty=None)
        with pytest.raises(lr.ReceiptError, match="digest"):
            self._receipt(dictionary, evaluator_tree_dirty=True)

    def test_every_real_model_id_has_a_model_receipt_and_mixed_ids_are_unobserved(self, dictionary):
        a = _robust_record(recorded_at=T0)
        b = _robust_record(recorded_at=T0 + timedelta(hours=1))
        b["pins"]["codeRevision"] = "0" * 40
        b["key"] = "k-other"
        receipts = pr.robust_evaluation_receipts(
            TestRobustReceipts._evaluation("NOT_BETTER"),
            [a, b],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        )
        ev = receipts[-1]
        assert ev.kind == "EVALUATION"
        modelled = {r.model_version_id for r in receipts if r.kind == "MODEL"}
        named = {mv for pair in ev.body["extra"]["modelVersionsEvaluated"] for mv in pair}
        assert named == modelled and len(named) == 4
        mixed = ev.body["extra"]["mixedModelVersionIds"]
        assert mixed["modelReceipt"]["state"] == "unobserved"
        assert ev.model_version_id == mixed["challengerModelVersionId"]
        assert ev.model_version_id not in modelled

    def test_a_single_model_evaluation_names_only_receipted_ids(self, dictionary):
        receipts = pr.robust_evaluation_receipts(
            TestRobustReceipts._evaluation("NOT_BETTER"),
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        )
        ev = receipts[-1]
        modelled = {r.model_version_id for r in receipts if r.kind == "MODEL"}
        assert ev.model_version_id in modelled
        assert ev.body["championModelVersionId"] in modelled
        assert "mixedModelVersionIds" not in ev.body["extra"]

    def test_the_cli_keys_a_dirty_tree(self, monkeypatch):
        jfs = _load_script("joint_filter_shadow")
        answers = {
            ("rev-parse", "HEAD"): "abc\n",
            ("status",): " M src/x.py\0?? src/new file.py\0",
            ("diff",): b"diff --git a/src/x.py b/src/x.py\n",
        }

        def fake_git(*args, binary=False):
            return answers[args[:2]] if args[:2] in answers else answers[args[:1]]

        monkeypatch.setattr(jfs, "_git", fake_git)
        revision, dirty, digest = jfs._evaluator_identity()
        assert (revision, dirty) == ("abc", True) and len(digest) == 64
        assert jfs._evaluator_identity() == (revision, dirty, digest)
        answers[("status",)] = ""
        assert jfs._evaluator_identity() == ("abc", False, None)


def test_source_quality_receipts_are_off_unless_explicitly_enabled(tmp_path, monkeypatch):
    """L4: fail closed -- no receipt unless RISKIT_RECEIPTS_ENABLED=1."""
    sq = REPO / "docs" / "valuation" / "evidence" / "source-quality-2026-10-01"
    results = json.loads((sq / "results_2026-09-30.json").read_text(encoding="utf-8"))
    lines = [
        json.loads(x) for x in (sq / "evaluations.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    cli = _load_script("source_quality_eval")
    store = tmp_path / "learning" / "r.sqlite"

    class Args:
        no_learning_receipts = False
        learning_store = store

    for value in (None, "0", "true", "yes"):
        if value is None:
            monkeypatch.delenv(pr.RECEIPTS_ENABLED_ENV, raising=False)
        else:
            monkeypatch.setenv(pr.RECEIPTS_ENABLED_ENV, value)
        cli.emit_learning_receipts(
            Args, results, lines, sq / "evaluations.jsonl", sq / "results_2026-09-30.json"
        )
        assert not store.exists(), value


# ── re-review fixes (#1612) ──────────────────────────────────────────────────


def test_the_sparse_inputs_pin_is_nearest_prior_not_exact(dictionary):
    """The inputs are hashed AFTER the builds read them; the receipt says so."""
    obs = next(
        r
        for r in pr.sparse_evidence_receipts(
            _sparse_record(recorded_at=T0), ledger_name="l", dictionary=dictionary
        )
        if r.kind == "OBSERVATION"
    )
    ref = obs.slots["inputs"]
    assert ref.fidelity == "nearest-prior"
    assert "hashed after the builds read their inputs" in ref.basis
    assert "invisible" in ref.basis


class TestSparsePayloadHashIsWhatWasRead:
    """The sparse ledger's payloadSha256 hashes the bytes the builds parsed."""

    @staticmethod
    def _payload(tmp_path):
        path = tmp_path / "exports" / "latest" / "dynasty_data_2026-10-01.json"
        path.parent.mkdir(parents=True)
        path.write_text(
            json.dumps({"scrapeTimestamp": "2026-10-01T06:00:00Z", "players": {}}),
            encoding="utf-8",
        )
        return path

    def test_hashing_the_read_bytes_leaves_the_ledger_byte_identical(self, sparse_cli, tmp_path):
        from src.api import sparse_evidence_shadow as shadow

        path = self._payload(tmp_path)
        raw = json.loads(path.read_bytes())
        # the previous behaviour: a second read of the file after the builds
        assert shadow.record_board(raw, path, base=tmp_path / "old", source="s")
        # the fixed behaviour: the exact bytes the payload was parsed from
        assert shadow.record_board(
            raw, path, base=tmp_path / "new", source="s", payload_bytes=path.read_bytes()
        )
        assert _sha_tree(tmp_path / "old") == _sha_tree(tmp_path / "new")

    def test_the_hash_names_the_bytes_read_even_if_the_file_moved_on(self, sparse_cli, tmp_path):
        from src.api import sparse_evidence_shadow as shadow

        path = self._payload(tmp_path)
        read = path.read_bytes()
        raw = json.loads(read)
        path.write_text(json.dumps({"scrapeTimestamp": "2026-10-02T06:00:00Z"}), encoding="utf-8")
        record, _written = shadow.record_board(
            raw, path, base=tmp_path / "l", source="s", payload_bytes=read
        )
        assert record["board"]["payloadSha256"] == hashlib.sha256(read).hexdigest()

    def test_newest_live_payload_hands_back_the_bytes_it_parsed(self, tmp_path):
        from src.api import sparse_evidence_shadow as shadow

        path = self._payload(tmp_path)
        found = shadow.newest_live_payload(tmp_path, with_bytes=True)
        assert found[0] == path and found[3] == path.read_bytes()
        assert json.loads(found[3]) == found[1]
        assert len(shadow.newest_live_payload(tmp_path)) == 3  # default shape unchanged


class TestEvaluationExtraIsNeverDefaulted:
    def test_no_decision_reads_unobserved_not_empty(self, dictionary):
        ev = TestRobustReceipts._evaluation("INCONCLUSIVE")
        ev["primary"] = {"horizons": {}, "decision": None}
        del ev["codeRevisions"]
        extra = pr.robust_evaluation_receipt(
            ev,
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        ).body["extra"]
        for field in (
            "reasons",
            "minimumSample",
            "accumulation",
            "boards",
            "originDays",
            "span",
            "recordCodeRevisions",
        ):
            assert extra[field]["state"] == "unobserved", field

    def test_present_fields_are_carried_verbatim(self, dictionary):
        extra = pr.robust_evaluation_receipt(
            TestRobustReceipts._evaluation("NOT_BETTER"),
            [_robust_record(recorded_at=T0)],
            evaluation_name="e.json",
            evaluator_revision="abc",
            evaluator_tree_dirty=False,
            dictionary=dictionary,
        ).body["extra"]
        assert extra["reasons"] == ["x"] and extra["minimumSample"] == {"met": True}
        assert extra["accumulation"] is None  # the producer's own explicit None
        assert extra["boards"] == 12 and extra["recordCodeRevisions"] == ["fedcba"]


def test_a_missing_voting_source_list_is_unobserved(dictionary):
    rec = _robust_record(recorded_at=T0)
    del rec["board"]["votingSources"]
    obs = next(
        r
        for r in pr.robust_filter_receipts(rec, ledger_name="l", dictionary=dictionary)
        if r.kind == "OBSERVATION"
    )
    assert obs.body["votingSourceCount"]["state"] == "unobserved"


def test_flags_token_separates_missing_from_empty_without_moving_present_ids():
    assert pr._flags_token(None) == "fmissing"
    assert pr._flags_token("garbage") == "fmissing"
    assert pr._flags_token({}) == "fnone"
    flags = {"joint_outlier_sparse_challenger": False}
    assert pr._flags_token(flags) == "f" + pr._sha(flags)[:8]
