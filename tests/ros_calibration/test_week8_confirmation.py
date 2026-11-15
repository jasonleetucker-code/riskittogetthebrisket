"""Tests for frozen week-8 calibration confirmation; no network or live value changes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import ros_scale_calibration_study as base
from scripts import ros_scale_week8_confirmation as confirm

# Week 8 2026 opened Thursday 2026-10-29 20:15 ET.
_KICKOFF = datetime(2026, 10, 30, 0, 15, tzinfo=timezone.utc)
_SCHED = {8: SimpleNamespace(first_kickoff_utc=_KICKOFF)}
_FROZEN_REL = "docs/league-intelligence/evidence/ros_scale_calibration/fits_week8_frozen.json"


def _fake_git(blob: str, committed: str):
    def git(*args: str) -> str:
        if args[0] == "rev-parse":
            assert args[1] == f"{confirm.PINNED_FREEZE_COMMIT}:{_FROZEN_REL}"
            return blob
        return committed

    return git


def test_freeze_before_kickoff_is_proven():
    receipt = confirm.verify_freeze(
        _KICKOFF, git=_fake_git(confirm.PINNED_FROZEN_BLOB, "2026-10-28T11:34:27-04:00")
    )
    assert receipt["commit"] == confirm.PINNED_FREEZE_COMMIT
    assert receipt["committedAt"] == "2026-10-28T11:34:27-04:00"


def test_freeze_after_kickoff_refuses():
    with pytest.raises(base.v1.StudyRefusal, match="at or after first kickoff"):
        confirm.verify_freeze(
            _KICKOFF, git=_fake_git(confirm.PINNED_FROZEN_BLOB, "2026-10-29T20:15:00-04:00")
        )


def test_freeze_commit_with_other_blob_refuses():
    with pytest.raises(base.v1.StudyRefusal, match="not the pinned"):
        confirm.verify_freeze(_KICKOFF, git=_fake_git("0" * 40, "2026-10-28T11:34:27-04:00"))


def test_unavailable_freeze_commit_refuses():
    def git(*_args: str) -> str:
        raise OSError("git missing")

    with pytest.raises(base.v1.StudyRefusal, match="unavailable"):
        confirm.verify_freeze(_KICKOFF, git=git)


def _resign_payload(tmp_path: Path, payload: dict) -> tuple[Path, str]:
    """Re-sign a synthetic artifact to test the semantic guard past checksum checks."""
    p = tmp_path / "fits.json"
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    p.write_bytes(raw)
    return p, confirm.git_blob_sha(raw)


def test_frozen_models_are_pinned_and_losslessly_serialized():
    models, receipt = confirm.load_frozen_models()
    assert set(models) == set(base.EVAL_MODELS)
    assert receipt["gitBlobSha1"] == confirm.PINNED_FROZEN_BLOB
    assert len(receipt["fileSha256"]) == 64
    assert models["F"].fits == {}
    assert models["CR"].fits["QB"].source == "CR:QB"


def test_crlf_checkout_still_matches_the_git_blob_pin(tmp_path):
    lf = confirm.FROZEN_PATH.read_bytes().replace(b"\r\n", b"\n")
    crlf = tmp_path / "fits_crlf.json"
    crlf.write_bytes(lf.replace(b"\n", b"\r\n"))
    _models, receipt = confirm.load_frozen_models(crlf)
    assert receipt["gitBlobSha1"] == confirm.PINNED_FROZEN_BLOB


def test_mutated_frozen_file_refuses_even_if_it_is_valid_json(tmp_path):
    raw = json.loads(confirm.FROZEN_PATH.read_text(encoding="utf-8"))
    raw["models"]["C0"]["fits"]["*"]["b"] += 0.001
    path, _ = _resign_payload(tmp_path, raw)
    with pytest.raises(base.v1.StudyRefusal, match="Git blob changed"):
        confirm.load_frozen_models(path)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(confirmWeek=9),
        lambda p: p.update(fitWeeks=[1, 2, 3, 4, 5, 6, 7, 8]),
        lambda p: p.update(promotes=True),
        lambda p: p["models"]["CR"]["fits"]["QB"].update(n=0),
        lambda p: p["models"]["CR"]["fits"]["QB"].update(a="NaN"),
        lambda p: p["models"].pop("CG"),
    ],
)
def test_semantically_invalid_frozen_artifact_is_rejected(tmp_path, change):
    raw = json.loads(confirm.FROZEN_PATH.read_text(encoding="utf-8"))
    change(raw)
    path, sha = _resign_payload(tmp_path, raw)
    with pytest.raises(base.v1.StudyRefusal):
        confirm.load_frozen_models(path, expected_blob=sha)


def test_incomplete_week_refuses_before_reading_matchups(monkeypatch):
    class FakeStudy:
        def is_final(self, _week):
            return False

        def week(self, _week):
            pytest.fail("week must not be loaded before final")

    monkeypatch.setattr(confirm.study_mod, "Study", lambda offline=False: FakeStudy())
    with pytest.raises(base.v1.StudyRefusal, match="not final"):
        confirm.run_confirmation()


def test_replay_uses_frozen_fits_and_never_refits(monkeypatch):
    fake = SimpleNamespace(
        is_final=lambda _week: True,
        week=lambda _week: SimpleNamespace(
            snapshot=confirm.REPO / "data" / "ros_calibration" / "week8_snapshot.json",
            rows=[
                SimpleNamespace(points=12.0, host_points=12.0),
                SimpleNamespace(points=3.0, host_points=None),
            ],
        ),
        sched=_SCHED,
        fingerprint="test-card",
        f=SimpleNamespace(network_calls=0),
    )
    observed = {}

    monkeypatch.setattr(confirm.study_mod, "Study", lambda offline=False: fake)
    monkeypatch.setattr(confirm, "verify_freeze", lambda kickoff: {"firstKickoffUtc": str(kickoff)})
    monkeypatch.setattr(
        confirm.study_mod, "fit_all", lambda *_a, **_kw: pytest.fail("must not refit")
    )

    def fake_evaluate(_study, week, models):
        observed["week"] = week
        observed["models"] = models
        return {"records": [{"week": week}], "teams": {}}

    monkeypatch.setattr(confirm.study_mod, "evaluate_week", fake_evaluate)
    monkeypatch.setattr(
        confirm.study_mod,
        "accuracy_block",
        lambda _records, _models: {
            "nScoredByEveryModel": 1,
            "byModel": {"C0": {"mae": 1.0}},
        },
    )
    monkeypatch.setattr(confirm.study_mod, "concordance_block", lambda _evals, _models: {})
    monkeypatch.setattr(confirm.study_mod, "team_block", lambda _evals, _models: {})
    monkeypatch.setattr(
        confirm.study_mod,
        "write_json",
        lambda path, data: observed.update({"writtenTo": path, "payload": data}),
    )
    monkeypatch.setattr(confirm.study_mod.v1, "sha256_file", lambda _p: "snapshot-hash")
    monkeypatch.setattr(confirm.study_mod.v1, "code_identity", lambda: "code-receipt")

    out = confirm.run_confirmation(offline=True)
    assert observed["week"] == 8
    assert observed["writtenTo"] == confirm.OUTPUT_PATH
    assert observed["models"]["CR"].fits["QB"].source == "CR:QB"
    assert out["promotes"] is False
    assert out["retrainedOnConfirmationWeek"] is False
    assert out["gates"]["status"] == "NOT_RERUN"
    assert out["hostPointsReconciled"]["match"] == 1
    assert out["hostPointsReconciled"]["scoredWithoutHostPoints"] == 1
    assert out["frozenFits"]["freeze"]["firstKickoffUtc"] == str(_KICKOFF)


def test_unproven_freeze_refuses_before_loading_the_week(monkeypatch):
    fake = SimpleNamespace(
        is_final=lambda _week: True,
        sched=_SCHED,
        week=lambda _week: pytest.fail("week must not load without a proven freeze"),
    )
    monkeypatch.setattr(confirm.study_mod, "Study", lambda offline=False: fake)
    monkeypatch.setattr(
        confirm,
        "verify_freeze",
        lambda _kickoff: confirm._refuse("frozen fits committed after first kickoff"),
    )
    with pytest.raises(base.v1.StudyRefusal, match="after first kickoff"):
        confirm.run_confirmation()


def test_scoring_mismatch_refuses_before_producing_evidence(monkeypatch):
    fake = SimpleNamespace(
        is_final=lambda _week: True,
        week=lambda _week: SimpleNamespace(rows=[SimpleNamespace(points=2.0, host_points=4.0)]),
        sched=_SCHED,
    )
    monkeypatch.setattr(confirm.study_mod, "Study", lambda offline=False: fake)
    monkeypatch.setattr(confirm, "verify_freeze", lambda _kickoff: {})
    monkeypatch.setattr(
        confirm.study_mod, "write_json", lambda *_args: pytest.fail("must not write")
    )
    with pytest.raises(base.v1.StudyRefusal, match="does not reconcile"):
        confirm.run_confirmation()
