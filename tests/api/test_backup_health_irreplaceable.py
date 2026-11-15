"""``backup_health`` surfaces the restore proof and irreplaceable-store coverage (MD-103).

Two blind spots, both closed here without touching the box:

* the post-deploy restore proof's result lived only in a CI log, so
  ``/api/health`` could say a backup EXISTED while saying nothing about whether
  it RESTORES.  The proof now leaves a small result file the app can read, and a
  proof that never ran (or whose result is unreadable) is ``unknown`` -- never
  healthy;
* the temporal ledger, analyst ledger and the other irreplaceable stores are
  OPTIONAL in the writer, so a missing or failed copy was a log line and an exit
  code 3 that the unit maps to success.  An existing store absent from the
  newest generation is now ``missing`` (loud); one that does not exist on the
  host is ``absent_by_design`` (not a failure).
"""

from __future__ import annotations

import gzip
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api import backup_health as bh
from src.api import ops_alerts

_REPO = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc).timestamp()
HOUR = 3600.0


def _stamp(hours_ago: float) -> str:
    return datetime.fromtimestamp(NOW - hours_ago * HOUR, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _write_proof(data_dir: Path, state: str, completed_ago: float | None = 2.0, **extra) -> None:
    doc = {
        "schema": 1,
        "state": state,
        "startedAt": _stamp((completed_ago or 0) + 0.2),
        "completedAt": None if completed_ago is None else _stamp(completed_ago),
        "exitCode": 0,
        "runBackup": True,
        "provenArtifacts": 12,
        "failures": 0,
        "optionalWarnings": 0,
        "generationDate": "2026-11-09",
    }
    doc.update(extra)
    target = data_dir / bh.RESTORE_PROOF_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(doc), encoding="utf-8")


def _proof(data_dir: Path) -> dict:
    return bh.restore_proof_health(data_dir=str(data_dir), now_epoch=NOW)


# -- restore proof ----------------------------------------------------------------
def test_a_proof_that_never_ran_is_unknown_never_healthy(tmp_path):
    out = _proof(tmp_path / "data")
    assert (out["result"], out["reason"]) == ("unknown", "no_result_recorded")
    assert out["completedAt"] is None and out["ageHours"] is None


def test_a_result_that_does_not_parse_is_unknown(tmp_path):
    target = tmp_path / "data" / bh.RESTORE_PROOF_RELATIVE
    target.parent.mkdir(parents=True)
    for junk in (
        "{not json",
        "[]",
        json.dumps({"schema": 2, "state": "proven"}),
        json.dumps({"schema": 1, "state": "great"}),
    ):
        target.write_text(junk, encoding="utf-8")
        out = _proof(tmp_path / "data")
        assert (out["result"], out["reason"]) == ("unknown", "result_unreadable"), junk


def test_a_proven_result_reports_state_timestamp_and_age(tmp_path):
    _write_proof(tmp_path, "proven", completed_ago=3.0)
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("proven", "all_artifacts_verified")
    assert out["completedAt"] == _stamp(3.0)
    assert out["ageHours"] == 3.0
    assert out["provenArtifacts"] == 12 and out["generationDate"] == "2026-11-09"


def test_a_proof_with_optional_warnings_says_so(tmp_path):
    _write_proof(tmp_path, "proven_with_warnings", optionalWarnings=2)
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("proven_with_warnings", "optional_store_warnings")


def test_a_proven_result_older_than_the_threshold_is_stale_not_healthy(tmp_path):
    _write_proof(tmp_path, "proven", completed_ago=bh.RESTORE_PROOF_STALE_AFTER_HOURS + 0.5)
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("stale", "older_than_threshold")


def test_a_failed_proof_stays_failed_however_old(tmp_path):
    _write_proof(tmp_path, "failed", completed_ago=900.0, exitCode=2, failures=3)
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("failed", "artifact_failed")
    assert out["failures"] == 3 and out["exitCode"] == 2


def test_a_proof_that_could_not_run_is_not_a_pass(tmp_path):
    _write_proof(tmp_path, "could_not_run", exitCode=1)
    assert _proof(tmp_path)["result"] == "could_not_run"


def test_a_run_in_flight_is_running_and_a_dead_one_is_interrupted(tmp_path):
    _write_proof(tmp_path, "running", completed_ago=None, completedAt=None)
    assert _proof(tmp_path)["result"] == "running"
    # started 5 h ago and never finished: it does NOT read as the previous run's pass
    doc_path = tmp_path / bh.RESTORE_PROOF_RELATIVE
    doc = json.loads(doc_path.read_text(encoding="utf-8"))
    doc["startedAt"] = _stamp(5.0)
    doc_path.write_text(json.dumps(doc), encoding="utf-8")
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("interrupted", "run_never_finished")


def test_a_stamp_in_the_future_is_a_wrong_clock_not_a_fresh_proof(tmp_path):
    _write_proof(tmp_path, "proven", completed_ago=-72.0)
    out = _proof(tmp_path)
    assert (out["result"], out["reason"]) == ("unverifiable", "result_clock_skew")
    assert out["ageHours"] is None


def test_a_proven_result_with_no_usable_timestamp_is_not_a_result(tmp_path):
    _write_proof(tmp_path, "proven", completed_ago=1.0, completedAt="yesterday")
    assert _proof(tmp_path)["result"] == "unknown"


# -- irreplaceable stores -------------------------------------------------------
def _make_generation(
    root: Path,
    *,
    artifacts: tuple[str, ...] = (),
    manifest: str | None = None,
    date: str = "2026-11-09",
) -> Path:
    gen = root / "daily" / date
    (gen / "sqlite").mkdir(parents=True)
    for rel in ("sqlite/user_kv.sqlite.gz", *artifacts):
        target = gen / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(gzip.compress(b"x"))
    if manifest is not None:
        (gen / "optional_stores.tsv").write_text(manifest, encoding="utf-8")
    os.utime(gen, (NOW - HOUR, NOW - HOUR))
    return gen


def _make_sources(data: Path, *names: str) -> None:
    """Create the SOURCE of each named store, so the host really has it."""
    by_name = {row[0]: row for row in bh.IRREPLACEABLE_STORES}
    for name in names:
        _, kind, source, *_ = by_name[name]
        path = data.joinpath(*source.split("/"))
        if kind == "dir":
            path.mkdir(parents=True, exist_ok=True)
            (path / "x.json").write_text("{}", encoding="utf-8")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"sqlite")


def _all_artifacts(skip: tuple[str, ...] = ()) -> tuple[str, ...]:
    out = []
    for name, _k, _s, _w, artifacts, _m in bh.IRREPLACEABLE_STORES:
        if name not in skip:
            out.append(artifacts[0])
    return tuple(out)


def _coverage(tmp_path: Path) -> dict:
    out = bh.state_backup_health(
        root=str(tmp_path / "state"),
        fallback_root=str(tmp_path / "state_fb"),
        data_dir=str(tmp_path / "data"),
        now_epoch=NOW,
    )
    return out["irreplaceableLedgers"]


def _status(ledgers: dict) -> dict[str, str]:
    return {r["name"]: r["status"] for r in ledgers["stores"]}


def test_the_exact_list_names_temporal_analyst_receipts_game_day_and_forecast():
    names = {row[0] for row in bh.IRREPLACEABLE_STORES}
    assert {
        "temporal_ledger",
        "analyst_ledger",
        "learning_receipts",
        "game_day",
        "forecast_archive",
        "pick_forecast_snapshots",
        "intel_ledger",
    } <= names
    assert len(names) == len(bh.IRREPLACEABLE_STORES)


def test_every_listed_store_is_one_the_writer_actually_backs_up():
    """Lockstep with ``riskit-state-backup.sh``: each source path and each
    artifact name must be what the writer produces, or the list drifts silently."""
    script = (_REPO / "deploy" / "backup" / "riskit-state-backup.sh").read_text(encoding="utf-8")
    for name, kind, source, writer, artifacts, manifest_name in bh.IRREPLACEABLE_STORES:
        call = (
            "backup_dir"
            if kind == "dir"
            else ("backup_file" if source.endswith(".jsonl") else "backup_sqlite")
        )
        pattern = re.compile(
            rf'^(optional )?{call}\s+"\$\{{DATA_DIR\}}/{re.escape(source)}"', re.MULTILINE
        )
        match = pattern.search(script)
        assert match, f"{name}: the writer has no `{call} ${{DATA_DIR}}/{source}`"
        assert (match.group(1) is not None) == (writer == "optional"), f"{name}: writer class"
        # The artifact the writer names it (its optional-store manifest name too).
        artifact = artifacts[0]
        output_name = Path(artifact).name.removesuffix(".gz").removesuffix(".tar")
        assert output_name == manifest_name.removesuffix(".tar") or artifact.startswith(
            "dirs/"
        ), name
        if artifact.startswith("dirs/"):
            assert Path(artifact).name == f"{manifest_name}.tar.gz", name


def test_a_complete_generation_is_covered(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, *(row[0] for row in bh.IRREPLACEABLE_STORES))
    _make_generation(tmp_path / "state", artifacts=_all_artifacts())
    ledgers = _coverage(tmp_path)
    assert ledgers["coverage"] == "covered"
    assert ledgers["uncoveredCount"] == 0
    assert set(_status(ledgers).values()) == {"covered"}


def test_a_missing_irreplaceable_ledger_is_reported_loudly(tmp_path):
    """The source exists on the host and the newest generation has no copy and the
    writer recorded nothing (an older writer predating the store): ``missing``."""
    data = tmp_path / "data"
    _make_sources(data, "temporal_ledger", "analyst_ledger", "learning_receipts")
    _make_generation(tmp_path / "state", artifacts=_all_artifacts(skip=("temporal_ledger",)))
    ledgers = _coverage(tmp_path)
    status = _status(ledgers)
    assert status["temporal_ledger"] == "missing"
    assert status["analyst_ledger"] == "covered"
    assert status["learning_receipts"] == "covered"
    assert ledgers["coverage"] == "uncovered"
    assert ledgers["uncoveredCount"] == 1


def test_a_missing_core_store_is_loud_too(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "learning_receipts")
    _make_generation(tmp_path / "state", artifacts=_all_artifacts(skip=("learning_receipts",)))
    ledgers = _coverage(tmp_path)
    assert _status(ledgers)["learning_receipts"] == "missing"
    assert ledgers["coverage"] == "uncovered"


@pytest.mark.parametrize("recorded", ["failed", "skipped_low_space", "skipped_space_unmeasurable"])
def test_a_store_the_writer_recorded_as_shed_is_named_with_its_reason(tmp_path, recorded):
    data = tmp_path / "data"
    _make_sources(data, "temporal_ledger")
    _make_generation(
        tmp_path / "state",
        artifacts=_all_artifacts(skip=("temporal_ledger",)),
        manifest=f"temporal_ledger.sqlite\t{recorded}\tdetail\n",
    )
    ledgers = _coverage(tmp_path)
    assert _status(ledgers)["temporal_ledger"] == recorded
    assert ledgers["coverage"] == "uncovered"


def test_a_store_that_does_not_exist_on_the_host_is_absent_by_design_not_a_failure(tmp_path):
    """A host that never started the analyst ledger or the forecast archive must
    not fail the backup: no source, no artifact, nothing recorded."""
    data = tmp_path / "data"
    data.mkdir()
    _make_sources(data, "game_day")
    _make_generation(tmp_path / "state", artifacts=("dirs/game_day.tar.gz",))
    ledgers = _coverage(tmp_path)
    status = _status(ledgers)
    assert status["game_day"] == "covered"
    assert status["analyst_ledger"] == "absent_by_design"
    assert status["forecast_archive"] == "absent_by_design"
    assert ledgers["coverage"] == "covered"
    assert ledgers["uncoveredCount"] == 0


def test_the_proofs_own_requested_skips_read_partial_not_uncovered(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "temporal_ledger", "intel_ledger")
    _make_generation(
        tmp_path / "state",
        manifest=(
            "temporal_ledger.sqlite\tskipped_requested\tBACKUP_SKIP_OPTIONAL\n"
            "intel_ledger.sqlite3\tskipped_requested\tBACKUP_SKIP_OPTIONAL\n"
        ),
    )
    ledgers = _coverage(tmp_path)
    assert ledgers["coverage"] == "partial"
    assert ledgers["uncoveredCount"] == 0 and ledgers["partialCount"] == 2


def test_an_intel_ledger_held_only_as_a_raw_tarball_is_partial(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "intel_ledger")
    _make_generation(
        tmp_path / "state",
        artifacts=("dirs/intel.tar.gz",),
        manifest="intel_ledger.sqlite3\tfailed\tPRAGMA integrity_check failed on the copy\n",
    )
    status = _status(_coverage(tmp_path))
    assert status["intel_ledger"] == "archive_only"


def test_a_source_this_process_cannot_stat_is_unverifiable_not_absent(tmp_path, monkeypatch):
    data = tmp_path / "data"
    _make_sources(data, "analyst_ledger")
    _make_generation(tmp_path / "state")
    real = bh._stat
    blocked = os.path.normpath(str(data / "analyst_ledger.sqlite"))

    def fake(path):
        if os.path.normpath(path) == blocked:
            raise PermissionError(13, "Permission denied", path)
        return real(path)

    monkeypatch.setattr(bh, "_stat", fake)
    ledgers = _coverage(tmp_path)
    assert _status(ledgers)["analyst_ledger"] == "unverifiable"
    assert ledgers["coverage"] != "covered"


def test_no_observed_generation_is_unverifiable_not_covered(tmp_path):
    out = bh.state_backup_health(
        root=str(tmp_path / "state"),
        fallback_root=str(tmp_path / "state_fb"),
        data_dir=str(tmp_path / "data"),
        now_epoch=NOW,
    )
    ledgers = out["irreplaceableLedgers"]
    assert ledgers["coverage"] == "unverifiable"
    assert ledgers["reason"] == "no_generation_observed"
    assert ledgers["stores"] is None and ledgers["uncoveredCount"] is None


# -- the public block ---------------------------------------------------------------
def _walk_strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield str(key)
            yield from _walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_strings(value)
    elif isinstance(node, str):
        yield node


def test_the_public_payload_carries_the_aggregate_but_no_store_name_or_path(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "temporal_ledger", "learning_receipts")
    _make_generation(tmp_path / "state", artifacts=_all_artifacts(skip=("temporal_ledger",)))
    _write_proof(data, "proven")
    public = bh.build_backup_health(
        state_root=str(tmp_path / "state"),
        state_fallback_root=str(tmp_path / "state_fb"),
        legacy_dirs=(),
        data_dir=str(data),
        now_epoch=NOW,
    )
    assert public["schemaVersion"] == "backup-health.v4"
    ledgers = public["stateBackup"]["irreplaceableLedgers"]
    assert ledgers["coverage"] == "uncovered" and ledgers["uncoveredCount"] == 1
    assert public["restoreProof"] == {
        "result": "proven",
        "reason": "all_artifacts_verified",
        "completedAt": _stamp(2.0),
        "ageHours": 2.0,
    }
    text = json.dumps(public)
    for private in (
        "temporal_ledger",
        "learning_receipts",
        "analyst_ledger",
        str(tmp_path),
        "backup_restore_proof",
        "diagnostics",
        "sqlite",
    ):
        assert private not in text, private
    for value in _walk_strings(public):
        assert "/" not in value and "\\" not in value, value


def test_a_probe_failure_in_the_proof_reads_unknown_in_the_public_block(tmp_path, monkeypatch):
    def boom(**_kw):
        raise RuntimeError("exploded")

    monkeypatch.setattr(bh, "restore_proof_health", boom)
    public = bh.build_backup_health(
        state_root=str(tmp_path / "s"),
        state_fallback_root=str(tmp_path / "s2"),
        legacy_dirs=(),
        data_dir=str(tmp_path / "data"),
        now_epoch=NOW,
    )
    assert (public["restoreProof"]["result"], public["restoreProof"]["reason"]) == (
        "unknown",
        "probe_error",
    )


# -- the operator alert --------------------------------------------------------------
def _detail(tmp_path: Path) -> dict:
    return bh.build_backup_health_detail(
        state_root=str(tmp_path / "state"),
        state_fallback_root=str(tmp_path / "state_fb"),
        legacy_dirs=(),
        data_dir=str(tmp_path / "data"),
        now_epoch=NOW,
    )


def test_alert_rows_name_the_uncovered_store_and_the_failed_proof(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "temporal_ledger")
    _make_generation(tmp_path / "state", artifacts=_all_artifacts(skip=("temporal_ledger",)))
    _write_proof(data, "failed", exitCode=2, failures=2)
    block = bh.alert_rows(_detail(tmp_path))
    assert block["ledgersChecked"] and block["proofChecked"]
    kinds = {(r["kind"], r.get("store") or r.get("result")) for r in block["rows"]}
    assert kinds == {("ledger", "temporal_ledger"), ("restore_proof", "failed")}
    alerts = ops_alerts._check_backup_coverage(block)
    assert {a.category for a in alerts} == {"backup_ledger:temporal_ledger", "backup_restore_proof"}
    assert all("temporal_ledger" in a.title or "restore proof" in a.title.lower() for a in alerts)


def test_a_healthy_pass_and_an_unjudgeable_pass_raise_nothing_but_differ_in_checked(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _write_proof(data, "proven")
    _make_generation(tmp_path / "state")
    healthy = bh.alert_rows(_detail(tmp_path))
    assert healthy["rows"] == [] and healthy["ledgersChecked"] and healthy["proofChecked"]

    nothing = bh.alert_rows(_detail(tmp_path / "elsewhere"))  # no generation, no proof
    assert nothing["rows"] == []
    assert not nothing["ledgersChecked"] and not nothing["proofChecked"]


def test_an_unjudgeable_pass_does_not_recover_a_firing_alert(tmp_path):
    """Losing sight of the state root (or the proof's result) is unknown, never
    'recovered' -- the recovery notice must wait for a pass that CAN judge."""
    state = {
        "backup_ledger:temporal_ledger": {
            "attemptedAt": 1,
            "deliveredAt": 1,
            "recoveryFired": False,
        },
        "backup_restore_proof": {"attemptedAt": 1, "deliveredAt": 1, "recoveryFired": False},
    }
    sent: list[tuple] = []

    def delivery(to, subject, body):
        sent.append((subject, body))
        return True

    kv = tmp_path / "kv.sqlite"
    ops_alerts._save_ops_state(state, set(state), path=kv)
    summary = ops_alerts.check_and_alert(
        backup_coverage={"rows": [], "ledgersChecked": False, "proofChecked": False},
        delivery=delivery,
        to_email="ops@example.test",
        kv_path=kv,
    )
    assert summary["recovered"] == 0 and not sent

    summary = ops_alerts.check_and_alert(
        backup_coverage={"rows": [], "ledgersChecked": True, "proofChecked": True},
        delivery=delivery,
        to_email="ops@example.test",
        kv_path=kv,
    )
    assert summary["recovered"] == 2 and sent


# -- a deleted ledger is not "absent by design" ------------------------------------
def _two_generations(tmp_path: Path, *, older_has: tuple[str, ...]) -> None:
    """Newest generation holds game_day only; an older one holds ``older_has``."""
    root = tmp_path / "state"
    _make_generation(root, artifacts=("dirs/game_day.tar.gz",), date="2026-11-09")
    _make_generation(root, artifacts=older_has, date="2026-11-08")


def test_a_store_that_never_existed_in_any_retained_generation_is_absent_by_design(tmp_path):
    data = tmp_path / "data"
    _make_sources(data, "game_day")
    _two_generations(tmp_path, older_has=("dirs/game_day.tar.gz",))
    ledgers = _coverage(tmp_path)
    assert _status(ledgers)["analyst_ledger"] == "absent_by_design"
    assert ledgers["coverage"] == "covered" and ledgers["uncoveredCount"] == 0


def test_a_store_deleted_after_it_was_backed_up_is_lost_after_backup_and_loud(tmp_path):
    """Source gone from the host, absent from the newest generation, but an OLDER
    retained generation holds it: the exact failure this report exists to catch."""
    data = tmp_path / "data"
    _make_sources(data, "game_day")
    _two_generations(
        tmp_path, older_has=("dirs/game_day.tar.gz", "sqlite/analyst_ledger.sqlite.gz")
    )
    ledgers = _coverage(tmp_path)
    assert _status(ledgers)["analyst_ledger"] == "lost_after_backup"
    assert ledgers["coverage"] == "uncovered" and ledgers["uncoveredCount"] == 1
    # ... and it alerts like `missing`, by name, for the operator only.
    detail = _detail(tmp_path)
    rows = bh.alert_rows(detail)["rows"]
    assert [(r["store"], r["status"]) for r in rows] == [("analyst_ledger", "lost_after_backup")]
    alerts = ops_alerts._check_backup_coverage(bh.alert_rows(detail))
    assert [a.category for a in alerts] == ["backup_ledger:analyst_ledger"]
    assert "analyst_ledger" not in json.dumps(
        bh.build_backup_health(
            state_root=str(tmp_path / "state"),
            state_fallback_root=str(tmp_path / "state_fb"),
            legacy_dirs=(),
            data_dir=str(data),
            now_epoch=NOW,
        )
    )


def test_unlistable_generations_make_an_absent_source_unverifiable_not_absent_by_design(
    tmp_path, monkeypatch
):
    data = tmp_path / "data"
    _make_sources(data, "game_day")
    _two_generations(tmp_path, older_has=("dirs/game_day.tar.gz",))
    daily = os.path.normpath(str(tmp_path / "state" / "daily"))
    real_listdir = bh._listdir
    calls = {"n": 0}

    def flaky(path):
        # The newest-generation probe lists daily/ first; every LATER listing of it
        # (the retained-generation scan) is refused, as for a closed directory.
        if os.path.normpath(path) == daily:
            calls["n"] += 1
            if calls["n"] > 1:
                raise PermissionError(13, "Permission denied", path)
        return real_listdir(path)

    monkeypatch.setattr(bh, "_listdir", flaky)
    ledgers = _coverage(tmp_path)
    status = _status(ledgers)
    assert status["analyst_ledger"] == "unverifiable"
    assert "absent_by_design" not in status.values()
    assert ledgers["coverage"] == "unverifiable"
