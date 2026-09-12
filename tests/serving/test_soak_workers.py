"""Worker terminal evidence must fail closed without retaining raw stderr.

These controls exercise receipt/cleanup and bounded worker admission/follow-up
seams. They do not launch the serving app, external providers or an experiment.
"""

import ast
import copy
import io
import json
import queue
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import soak_prepared_serving as soak


ATTEMPT = "a" * 32
GENERATION = "b" * 64
PRIVATE = "synthetic-private-player-path-cookie-and-exception-text"


def receipt(*, kind="unchanged", outcome="success", **changes):
    result = {
        "schemaVersion": 1,
        "attemptId": ATTEMPT,
        "workerKind": kind,
        "sequence": 7,
        "outcome": outcome,
        "stage": "complete" if outcome == "success" else "league_publish",
        "exceptionClass": None if outcome == "success" else "OSError",
        "errno": None if outcome == "success" else 13,
        "winerror": None if outcome == "success" else 5,
        "canonicalAccepted": kind in {"changed", "unchanged"},
        "acceptedPhysicalGeneration": GENERATION if kind in {"changed", "unchanged"} else None,
        "leagueOutcome": "not_started" if kind == "hold" else outcome,
    }
    result.update(changes)
    return result


def wire(record):
    return (soak.WORKER_RECEIPT_PREFIX + json.dumps(record) + "\n").encode()


def args_for(tmp_path):
    return SimpleNamespace(root=tmp_path / "store", budget_bytes=1024, port=12345)


class CompletedChild:
    def __init__(self, stderr=b"", exit_code=0):
        self.stderr = io.BytesIO(stderr)
        self.returncode = exit_code
        self.waits = []

    def wait(self, timeout=None):
        self.waits.append(timeout)
        return self.returncode

    def poll(self):
        return self.returncode


@pytest.fixture
def capture(tmp_path):
    captures = []

    def create(stderr=b"", *, code=0, kind="unchanged", sequence=7, attempt_id=ATTEMPT):
        child = CompletedChild(stderr, code)
        args = args_for(tmp_path / str(len(captures)))
        args.root.parent.mkdir()
        child._soak_receipt = soak.WorkerReceiptCapture(child, args, kind, sequence, attempt_id)
        captures.append(child._soak_receipt)
        return child

    yield create
    for item in captures:
        item.thread.join(timeout=2)
        assert not item.thread.is_alive()


@pytest.mark.parametrize("kind", ["changed", "unchanged", "league", "hold"])
@pytest.mark.parametrize("outcome", ["success", "failed"])
def test_terminal_receipt_preserves_distinct_canonical_and_league_outcomes(kind, outcome):
    record = receipt(kind=kind, outcome=outcome)
    assert soak.validate_worker_receipt(record, attempt_id=ATTEMPT, kind=kind, sequence=7) == record
    assert record["canonicalAccepted"] == (kind in {"changed", "unchanged"})
    if outcome == "failed" and record["canonicalAccepted"]:
        assert (
            record["leagueOutcome"] == "failed"
        )  # Canonical acceptance does not mean job success.


@pytest.mark.parametrize(
    "field,value",
    [
        ("schemaVersion", True),
        ("schemaVersion", 2),
        ("attemptId", "c" * 32),
        ("workerKind", "changed"),
        ("sequence", True),
        ("sequence", 8),
        ("outcome", "unknown"),
        ("stage", PRIVATE),
        ("canonicalAccepted", 1),
        ("acceptedPhysicalGeneration", PRIVATE),
        ("acceptedPhysicalGeneration", None),
        ("leagueOutcome", "unknown"),
        ("errno", True),
        ("errno", 2**32),
        ("winerror", -(2**31) - 1),
        ("winerror", "5"),
    ],
)
def test_mismatched_invalid_terminal_fields_are_rejected(field, value):
    record = receipt(**{field: value})
    with pytest.raises(ValueError):
        soak.validate_worker_receipt(record, attempt_id=ATTEMPT, kind="unchanged", sequence=7)


@pytest.mark.parametrize("mutation", ["missing", "extra", "not_mapping"])
def test_schema_does_not_accept_unknown_fields_or_raw_exception_material(mutation):
    record = receipt()
    if mutation == "missing":
        record.pop("stage")
    elif mutation == "extra":
        record["traceback"] = PRIVATE
    else:
        record = [record]
    with pytest.raises(ValueError, match="worker_receipt_schema"):
        soak.validate_worker_receipt(record, attempt_id=ATTEMPT, kind="unchanged", sequence=7)


@pytest.mark.parametrize(
    "changes",
    [
        {"stage": "canonical_publish"},
        {"exceptionClass": "OSError"},
        {"canonicalAccepted": False, "acceptedPhysicalGeneration": None},
        {"leagueOutcome": "failed"},
    ],
)
def test_success_requires_complete_canonical_and_league_work(changes):
    with pytest.raises(ValueError, match="worker_receipt_outcome"):
        soak.validate_worker_receipt(
            receipt(**changes), attempt_id=ATTEMPT, kind="unchanged", sequence=7
        )


@pytest.mark.parametrize("exception", [None, "", PRIVATE + ": file not found", "错误", "X" * 81])
def test_failed_receipt_cannot_include_exception_messages(exception):
    with pytest.raises(ValueError, match="worker_receipt_exception"):
        soak.validate_worker_receipt(
            receipt(outcome="failed", exceptionClass=exception),
            attempt_id=ATTEMPT,
            kind="unchanged",
            sequence=7,
        )


@pytest.mark.parametrize(
    "payload,problem",
    [
        (b"", "worker_receipt_missing"),
        (PRIVATE.encode() + b"\n", "worker_receipt_missing"),
        (wire(receipt(attemptId="c" * 32)), "worker_receipt_invalid"),
        (wire(receipt()) + wire(receipt()), "worker_receipt_invalid"),
        ((soak.WORKER_RECEIPT_PREFIX + "{" + PRIVATE + "}\n").encode(), "worker_receipt_invalid"),
        ((soak.WORKER_RECEIPT_PREFIX + "x" * 8192 + "\n").encode(), "worker_receipt_invalid"),
        (wire(receipt(traceback=PRIVATE)), "worker_receipt_invalid"),
    ],
)
def test_capture_rejects_missing_mismatched_duplicate_oversized_or_raw_protocol(
    capture, payload, problem
):
    child = capture(payload)
    errors, events = [], []
    result = soak.finish_worker(child, errors=errors, events=events)
    assert result["receiptError"] == problem and result["receipt"] is None
    assert errors == [problem] and events == [{"kind": "worker_outcome", **result}]
    serialized = child._soak_receipt.sink.path.read_text()
    assert PRIVATE not in serialized and "traceback" not in serialized
    assert len(serialized.encode()) <= soak.WORKER_RECEIPT_LIMIT
    assert child.stderr.closed


def test_raw_multichunk_line_cannot_smuggle_a_receipt_prefix(capture):
    raw = b"x" * (soak.WORKER_RECEIPT_LIMIT + 1)
    child = capture(raw + wire(receipt()))
    result = soak.finish_worker(child)
    assert result["receiptError"] == "worker_receipt_missing"
    assert result["stderrBytesObserved"] == len(raw + wire(receipt()))


def test_stderr_close_failure_after_valid_eof_cannot_accept_success(tmp_path, monkeypatch):
    payload = PRIVATE.encode() + b"\n" + wire(receipt())
    uncaught = []
    monkeypatch.setattr(threading, "excepthook", lambda args: uncaught.append(type(args.exc_value)))

    class CloseFailure(io.BytesIO):
        def close(self):
            if not self.closed:
                super().close()
                raise OSError(PRIVATE)

    child = CompletedChild()
    child.stderr = CloseFailure(payload)
    child._soak_receipt = soak.WorkerReceiptCapture(
        child, args_for(tmp_path), "unchanged", 7, ATTEMPT
    )
    errors = []
    result = soak.finish_worker(child, errors=errors)
    assert not uncaught and not child._soak_receipt.thread.is_alive()
    assert result["exitCode"] == 0  # Process success cannot hide channel-finalization failure.
    assert result["receiptError"] == "worker_receipt_invalid" and result["receipt"] is None
    assert errors == ["worker_receipt_invalid"]
    assert result["stderrBytesObserved"] == result["stderrBytesDiscarded"] == len(payload)
    assert result["validReceiptFramingBytes"] == 0
    saved = json.loads(child._soak_receipt.sink.path.read_text())
    assert saved == result and PRIVATE not in json.dumps(saved)


@pytest.mark.parametrize(
    "outcome,code,problem",
    [
        ("success", 0, None),
        ("failed", 1, None),
        ("failed", 0, "worker_receipt_exit_mismatch"),
        ("success", 1, "worker_receipt_exit_mismatch"),
    ],
)
def test_process_exit_and_terminal_outcome_must_agree(capture, outcome, code, problem):
    child = capture(PRIVATE.encode() + b"\n" + wire(receipt(outcome=outcome)), code=code)
    result = soak.finish_worker(child)
    assert result["receiptError"] == problem
    assert result["receipt"] == (receipt(outcome=outcome) if problem is None else None)
    assert PRIVATE not in child._soak_receipt.sink.path.read_text()
    assert result["lifecycleSeconds"] >= 0
    assert result["lifecycleScope"] == "post_spawn_capture_to_parent_finalize"


def test_capture_finalization_is_idempotent_and_writes_only_one_record(capture):
    child = capture(wire(receipt()))
    first = soak.finish_worker(child)
    assert child._soak_receipt.finish() is first
    assert child._soak_receipt.sink.count == 1 and len(child.waits) == 1
    assert len(child._soak_receipt.sink.path.read_text().splitlines()) == 1


@pytest.mark.parametrize("kind", ["changed", "unchanged", "league"])
def test_only_explicit_hold_termination_can_omit_receipt(capture, kind):
    child = capture(kind=kind, code=-1)
    with pytest.raises(ValueError, match="only the queued-request hold fault"):
        soak.finish_worker(child, intentional_termination=True)
    assert child.waits == []
    assert soak.finish_worker(child)["receiptError"] == "worker_receipt_missing"


def test_hold_exemption_is_explicit_and_does_not_hide_bad_receipts(capture):
    child = capture(kind="hold", code=-1)
    result = soak.finish_worker(child, intentional_termination=True)
    assert result["receiptError"] is None and result["receipt"] is None
    assert result["intentionalTermination"]
    ordinary = capture(kind="hold", code=-1)
    assert soak.finish_worker(ordinary)["receiptError"] == "worker_receipt_missing"
    malformed = capture(wire(receipt(kind="hold", traceback=PRIVATE)), kind="hold", code=-1)
    assert (
        soak.finish_worker(malformed, intentional_termination=True)["receiptError"]
        == "worker_receipt_invalid"
    )


def test_sink_preserves_preexisting_path_and_caps_records_at_1024(tmp_path):
    path = tmp_path / "evidence.jsonl"
    path.write_bytes(b"preserve-existing-evidence")
    with pytest.raises(FileExistsError):
        soak.WorkerEvidenceSink(path)
    assert path.read_bytes() == b"preserve-existing-evidence"
    sink = soak.WorkerEvidenceSink(tmp_path / "fresh.jsonl")
    for _ in range(1024):
        sink.append(b"{}\n")
    before = sink.path.read_bytes()
    with pytest.raises(ValueError, match="count_limit"):
        sink.append(b"should-not-appear\n")
    assert sink.count == 1024 and sink.path.read_bytes() == before


def test_sink_write_error_latches_and_capture_marks_evidence_failure(capture, monkeypatch):
    child = capture(wire(receipt()))
    sink = child._soak_receipt.sink
    original = Path.open

    def fail_write(path, mode="r", *args, **kwargs):
        if path == sink.path and mode == "ab":
            raise OSError(PRIVATE)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_write)
    errors = []
    result = soak.finish_worker(child, errors=errors)
    assert sink.failed and sink.count == 0
    assert result["receiptError"] == "worker_evidence_write_failed"
    assert errors == ["worker_evidence_write_failed"] and PRIVATE not in json.dumps(result)
    with pytest.raises(ValueError, match="count_limit"):
        sink.append(b"{}\n")


def test_capture_wait_timeout_does_not_manufacture_a_final_record(capture, monkeypatch):
    child = capture(wire(receipt()))
    child._soak_receipt.thread.join(timeout=2)
    original_wait = child.wait

    def timeout(timeout=None):
        raise subprocess.TimeoutExpired("fixture-only", timeout)

    monkeypatch.setattr(child, "wait", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        soak.finish_worker(child, timeout=0.001)
    assert child._soak_receipt.final is None and child._soak_receipt.sink.count == 0
    monkeypatch.setattr(child, "wait", original_wait)
    assert soak.finish_worker(child)["receiptError"] is None


@pytest.mark.parametrize("stage,timeout", [("ledger", False), ("capture", False), ("ledger", True)])
def test_launch_setup_failure_reaps_child_and_closes_stderr(tmp_path, monkeypatch, stage, timeout):
    calls = []
    error = RuntimeError(PRIVATE)
    child = SimpleNamespace(pid=123, stderr=io.BytesIO(), returncode=None)
    child.poll = lambda: child.returncode
    child.terminate = lambda: calls.append("terminate")
    child.kill = lambda: calls.append("kill")

    def wait(timeout=None):
        calls.append("wait")
        if len([c for c in calls if c == "wait"]) == 1 and timeout_case:
            raise subprocess.TimeoutExpired("fixture", timeout)
        child.returncode = -1
        return -1

    timeout_case = timeout
    child.wait = wait
    args = args_for(tmp_path)
    if stage == "ledger":
        args.child_ledger = SimpleNamespace(observe_pid=lambda pid: (_ for _ in ()).throw(error))
    else:
        monkeypatch.setattr(
            soak, "WorkerReceiptCapture", lambda *a, **k: (_ for _ in ()).throw(error)
        )
    monkeypatch.setattr(soak.subprocess, "Popen", lambda *a, **k: child)
    with pytest.raises(RuntimeError) as raised:
        soak.launch(args, "unchanged", 7)
    assert raised.value is error and child.stderr.closed and child.returncode is not None
    assert calls == (["terminate", "wait", "kill", "wait"] if timeout else ["terminate", "wait"])


def test_launch_refuses_preexisting_evidence_before_spawning(tmp_path, monkeypatch):
    args = args_for(tmp_path)
    evidence = args.root.with_name(args.root.name + ".workers.jsonl")
    evidence.write_text("preserve")

    def never_spawn(*args, **kwargs):
        pytest.fail("preexisting evidence must fail before Popen")

    monkeypatch.setattr(soak.subprocess, "Popen", never_spawn)
    with pytest.raises(FileExistsError):
        soak.launch(args, "unchanged", 7)
    assert evidence.read_text() == "preserve"


@pytest.mark.parametrize("kind", ["changed", "league"])
@pytest.mark.parametrize("evidence", ["failed", "missing", "corrupt", "busy_without_canonical"])
def test_completed_failed_worker_still_fails_real_supervisor_branch(capture, kind, evidence):
    # Execute the driver's actual bounded completed-child branch, without its
    # app setup or producers, to catch a receipt-only success replacing the
    # independent nonzero-exit gate.
    tree = ast.parse(Path(soak.__file__).read_text())
    name = "league_child" if kind == "league" else "child"
    expected_test = f"{name} is not None and {name}.poll() is not None"
    branch = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and ast.unparse(node.test) == expected_test
    )
    payload = wire(receipt(kind=kind, outcome="failed"))
    code = 1
    if evidence != "failed":
        code = 0
        payload = b"" if evidence == "missing" else wire(receipt(kind=kind, extra=PRIVATE))
        if evidence == "busy_without_canonical":
            payload = wire(
                receipt(
                    kind=kind,
                    leagueOutcome="busy",
                    canonicalAccepted=False,
                    acceptedPhysicalGeneration=None,
                )
            )
    child = capture(payload, code=code, kind=kind)
    events, errors = [], []
    namespace = {
        name: child,
        "finish_worker": soak.finish_worker,
        "events": events,
        "errors": errors,
        "sequence": 7,
        "cycle_worker_failed": False,
        "pending_followup": None,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[copy.deepcopy(branch)], type_ignores=[])),
            "<supervisor-branch>",
            "exec",
        ),
        namespace,
    )
    expected = (
        ("league_worker_exit_1" if kind == "league" else "worker_exit_1")
        if code
        else ("worker_receipt_missing" if evidence == "missing" else "worker_receipt_invalid")
    )
    assert errors == [expected]
    assert namespace[name] is None
    assert namespace["cycle_worker_failed"] is True
    assert namespace["pending_followup"] is None
    if code:
        assert events[0]["receiptError"] is None and events[0]["receipt"]["outcome"] == "failed"
    else:
        assert events[0]["receiptError"] == expected and events[0]["receipt"] is None
    samples = [
        {
            "seconds": second,
            "rssBytes": 100,
            "descriptorCount": 1,
            "processCount": 1,
            "diskBytes": 1,
        }
        for second in range(20)
    ]
    report = soak.summarize(
        samples,
        {"baseline": [1], "refresh": [1]},
        10,
        errors,
        events,
        100,
        children={"remainingCount": 0, "unknownCount": 0},
    )
    assert not report["checks"]["noIncorrectResponsesOrUnexpectedFailures"]
    assert not report["passed"]


@pytest.mark.parametrize("code", [0, 1])
def test_real_short_subprocess_drains_noise_and_one_terminal_receipt(tmp_path, code):
    record = receipt(outcome="success" if code == 0 else "failed")
    body = PRIVATE + "\n" + wire(record).decode()
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys;sys.stderr.write(sys.argv[1]);sys.exit(int(sys.argv[2]))",
            body,
            str(code),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        child._soak_receipt = soak.WorkerReceiptCapture(
            child, args_for(tmp_path), "unchanged", 7, ATTEMPT
        )
        result = soak.finish_worker(child, timeout=5)
        assert result["receiptError"] is None and result["receipt"] == record
        assert PRIVATE not in child._soak_receipt.sink.path.read_text()
        assert child.stderr.closed and not child._soak_receipt.thread.is_alive()
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)


def test_stderr_drain_timeout_is_final_failure_even_if_pipe_later_closes(tmp_path):
    released = threading.Event()

    class DelayedStderr:
        closed = False

        def readline(self, limit):
            released.wait(timeout=3)
            return b""

        def close(self):
            self.closed = True

    child = CompletedChild()
    child.stderr = DelayedStderr()
    child._soak_receipt = soak.WorkerReceiptCapture(
        child, args_for(tmp_path), "unchanged", 7, ATTEMPT
    )
    try:
        errors = []
        result = soak.finish_worker(child, timeout=0.001, errors=errors)
        assert result["receiptError"] == "worker_receipt_drain_timeout"
        assert result["receipt"] is None and errors == ["worker_receipt_drain_timeout"]
    finally:
        released.set()
        child._soak_receipt.thread.join(timeout=2)
    assert child.stderr.closed and not child._soak_receipt.thread.is_alive()
    assert soak.finish_worker(child) is result


@pytest.mark.parametrize("failed", [False, True])
def test_worker_wrapper_emits_only_final_schema_and_safe_failure_details(
    monkeypatch, capsys, failed
):
    def work(args, record):
        record.update(
            canonicalAccepted=True,
            acceptedPhysicalGeneration=GENERATION,
            stage="league_publish",
            leagueOutcome="running" if failed else "success",
        )
        if failed:
            error = OSError(13, PRIVATE)
            error.winerror = 5
            raise error

    monkeypatch.setattr(soak, "_worker", work)
    args = SimpleNamespace(worker="unchanged", sequence=7, attempt_id=ATTEMPT)
    if failed:
        with pytest.raises(SystemExit) as raised:
            soak.worker(args)
        assert raised.value.code == 1
    else:
        assert soak.worker(args) is None
    output = capsys.readouterr()
    assert not output.out and PRIVATE not in output.err and "Traceback" not in output.err
    assert len(output.err.splitlines()) == 1 and output.err.startswith(soak.WORKER_RECEIPT_PREFIX)
    result = json.loads(output.err[len(soak.WORKER_RECEIPT_PREFIX) :])
    assert (
        soak.validate_worker_receipt(result, attempt_id=ATTEMPT, kind="unchanged", sequence=7)
        == result
    )
    assert result["canonicalAccepted"] and result["acceptedPhysicalGeneration"] == GENERATION
    assert result["leagueOutcome"] == ("failed" if failed else "success")
    assert result["exceptionClass"] == ("PermissionError" if failed else None)
    assert result["stage"] == ("league_publish" if failed else "complete")


@pytest.mark.parametrize("allow_busy", [False, True])
def test_league_worker_only_optional_outer_contention_is_busy(tmp_path, allow_busy):
    from src.serving.artifacts import ArtifactStore, PublishLockTimeout, _publish_lock
    from src.serving.producer_status import pending_league_refresh, request_league_refresh

    store = ArtifactStore(tmp_path)
    pending = request_league_refresh(store, "test")
    record = receipt()
    with _publish_lock(tmp_path / "league-producer.lock", 0):
        if allow_busy:
            assert soak.league_worker(store, record, lease_wait_seconds=0, allow_busy=True) is False
            assert record["leagueOutcome"] == "busy"
        else:
            with pytest.raises(PublishLockTimeout):
                soak.league_worker(store, record, lease_wait_seconds=0)
    assert pending_league_refresh(store)["requestId"] == pending["requestId"]
    assert record["canonicalAccepted"] is True
    assert record["acceptedPhysicalGeneration"] == GENERATION
    assert record["stage"] == "league_admission"


@pytest.mark.parametrize("stage", ["claim", "board_read", "prepare", "publish"])
@pytest.mark.parametrize("error_type", ["timeout", "unknown"])
def test_optional_league_worker_never_relabels_admitted_failure(
    monkeypatch, tmp_path, stage, error_type
):
    from src.serving import artifacts, league_views, producer_status, serialization

    observed = []
    error = (
        artifacts.PublishLockTimeout(PRIVATE) if error_type == "timeout" else ValueError(PRIVATE)
    )

    @contextmanager
    def lease(path, timeout):
        observed.append("admitted")
        try:
            yield
        finally:
            observed.append("released")

    def step(name, value=None):
        observed.append(name)
        if name == stage:
            raise error
        return value

    board = SimpleNamespace(contract={"meta": {"leagueKey": "fixture", "scoringProfile": "same"}})
    store = SimpleNamespace(root=tmp_path, read_current=lambda *a: step("board_read", board))
    monkeypatch.setattr(artifacts, "_publish_lock", lease)
    monkeypatch.setattr(producer_status, "claim_league_refresh", lambda store: step("claim"))
    monkeypatch.setattr(serialization, "load_generation", lambda artifact: artifact)
    monkeypatch.setattr(league_views, "prepare_league_views", lambda *a: step("prepare", object()))
    monkeypatch.setattr(league_views, "publish_league_views", lambda *a, **k: step("publish"))
    record = receipt()
    with pytest.raises(type(error)) as raised:
        soak.league_worker(store, record, lease_wait_seconds=0, allow_busy=True)
    assert raised.value is error
    assert observed[-1] == "released" and observed.count("admitted") == 1
    assert record["stage"] == "league_" + stage
    assert record["leagueOutcome"] != "busy"
    assert record["canonicalAccepted"] and record["acceptedPhysicalGeneration"] == GENERATION


@pytest.mark.parametrize("queue_fails", [False, True])
def test_source_busy_followup_queues_after_acceptance_and_queue_errors_remain_errors(
    monkeypatch, tmp_path, queue_fails
):
    from src.serving import producer_status

    artifact = SimpleNamespace(manifest={}, files={}, generation_id=GENERATION)
    store = SimpleNamespace(
        root=tmp_path, read_current=lambda *a: artifact, publish=lambda *a, **k: artifact
    )
    monkeypatch.setattr(soak, "store_for", lambda *a: store)
    monkeypatch.setattr(producer_status, "claim_source_refresh", lambda store: None)
    queued = []

    def busy(store, record, **options):
        assert options == {"lease_wait_seconds": 0, "allow_busy": True}
        assert record["canonicalAccepted"] and record["acceptedPhysicalGeneration"] == GENERATION
        record["leagueOutcome"] = "busy"
        return False

    def queue(store, trigger):
        queued.append(trigger)
        if queue_fails:
            raise OSError(PRIVATE)

    monkeypatch.setattr(soak, "league_worker", busy)
    monkeypatch.setattr(producer_status, "request_league_refresh", queue)
    record = receipt(canonicalAccepted=False, acceptedPhysicalGeneration=None)
    options = SimpleNamespace(root=tmp_path, budget_bytes=1024, worker="unchanged", sequence=7)
    if queue_fails:
        with pytest.raises(OSError):
            soak._worker(options, record)
    else:
        soak._worker(options, record)
    assert queued == ["soak_followup"]
    assert record["stage"] == "league_deferred_queue"
    assert record["canonicalAccepted"] and record["acceptedPhysicalGeneration"] == GENERATION


def followup_action(task, now, **changes):
    options = dict(
        companions_drained=True, cycle_failed=False, canonical_version="A", drain_ready=False
    )
    return task.action(now, **{**options, **changes})


def test_deferred_work_waits_for_companions_and_actual_adoption_not_marker_or_exit():
    task = soak.DeferredLeagueFollowup(0)
    assert followup_action(task, 1, companions_drained=False) == "wait"
    assert task.attempts == 0
    assert followup_action(task, 2) == "launch"
    task.worker_finished("A")
    assert followup_action(task, 3) == "wait"  # Same-pointer worker exit is not adoption.
    assert followup_action(task, 4, canonical_version="B") == "wait"  # No mid-run supersession.
    assert task.attempts == 1
    assert followup_action(task, 5, drain_ready=True) == "complete"


def test_deferred_second_attempt_requires_mid_run_new_pointer_and_is_bounded():
    task = soak.DeferredLeagueFollowup(0)
    assert followup_action(task, 1) == "launch"
    task.worker_finished("B")
    assert followup_action(task, 2, canonical_version="B") == "launch"
    task.worker_finished("C")
    assert followup_action(task, 3, canonical_version="C") == "wait"
    assert task.attempts == 2
    assert followup_action(task, 89.999, canonical_version="C") == "wait"
    assert followup_action(task, 90, canonical_version="C") == "failed"
    assert task.failure == "league_followup_deadline"


@pytest.mark.parametrize(
    "now,changes,failure",
    [
        (
            1,
            {"cycle_failed": True, "drain_ready": True},
            "league_followup_blocked_by_worker_failure",
        ),
        (90, {"drain_ready": True}, "league_followup_deadline"),
        (1, {"canonical_version": None}, "league_followup_missing_canonical"),
    ],
)
def test_deferred_failure_cannot_be_retried_or_hidden_by_ready(now, changes, failure):
    task = soak.DeferredLeagueFollowup(0)
    assert followup_action(task, 0) == "launch"
    task.worker_finished("B")
    assert followup_action(task, now, **changes) == "failed"
    assert task.attempts == 1 and task.failure == failure


@pytest.mark.parametrize(
    "stuck",
    ["source", "league", "web", "close_runtime", "close_queue", "web_nonzero", "stream_close"],
)
def test_actual_main_finally_retains_failed_report_and_cleans_other_children(
    monkeypatch, tmp_path, stuck
):
    calls = []

    class Child:
        def __init__(self, name):
            self.name, self.returncode, self.killed = name, None, False

        def poll(self):
            return self.returncode

        def terminate(self):
            calls.append((self.name, "terminate"))

        def kill(self):
            calls.append((self.name, "kill"))
            self.killed = True
            self.returncode = -9

        def wait(self, timeout=None):
            calls.append((self.name, "wait"))
            if self.name == stuck and not self.killed:
                raise subprocess.TimeoutExpired("fixture", timeout)
            self.returncode = -9 if self.killed else 0
            return self.returncode

        def communicate(self, timeout=None):
            calls.append((self.name, "communicate"))
            self.wait(timeout)
            if self.name == "web" and stuck == "web_nonzero":
                self.returncode = 3
            return b"", b""

    source, league, web = (Child(name) for name in ("source", "league", "web"))

    def finish(child, **kwargs):
        calls.append((child.name, "finish"))
        child.wait(kwargs.get("timeout"))
        return {"receiptError": None, "exitCode": child.returncode}

    def close_diagnostics():
        calls.append(("diagnostics", "close"))
        raise RuntimeError(PRIVATE) if stuck == "close_runtime" else queue.Full()

    def close_stream():
        calls.append(("stream", "close"))
        if stuck == "stream_close":
            raise OSError(PRIVATE)

    monkeypatch.setattr(soak, "finish_worker", finish)
    tree = ast.parse(Path(soak.__file__).read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    guarded = next(
        node
        for node in main.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(item, ast.Assign) and ast.unparse(item.targets[0]) == "observation_seconds"
            for item in node.finalbody
        )
    )
    report_assignment = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "report"
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "summarize"
    )
    final_pass = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "report['passed']"
    )
    write_report = next(
        node
        for node in main.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "args.output.write_text"
    )
    errors, events = [], []
    options = SimpleNamespace(
        output=tmp_path / "failed-report.json",
        root=tmp_path,
        baseline_seconds=10,
        budget_bytes=2000,
        latency_policy=soak.LEGACY_LATENCY_POLICY,
        child_ledger=SimpleNamespace(remaining=lambda *a: {"remainingCount": 0, "unknownCount": 0}),
    )
    namespace = {
        **vars(soak),
        "started": 0,
        "samples": [
            {
                "seconds": second,
                "rssBytes": 100,
                "descriptorCount": 1,
                "processCount": 1,
                "diskBytes": 1,
            }
            for second in range(100)
        ],
        "stop": SimpleNamespace(set=lambda: calls.append(("reader", "stop"))),
        "reader": SimpleNamespace(
            join=lambda **k: calls.append(("reader", "join")), is_alive=lambda: False
        ),
        "request_stream": SimpleNamespace(close=close_stream),
        "diagnostic_output": SimpleNamespace(
            close=close_diagnostics,
            collection_report=lambda: {"complete": False, "dropped": 0},
        )
        if stuck.startswith("close_")
        else None,
        "exchange_clocks": lambda state: {"comparable": True},
        "child": source,
        "league_child": league,
        "web_child": web,
        "fault_thread": SimpleNamespace(
            join=lambda **k: calls.append(("fault", "join")), is_alive=lambda: False
        ),
        "state": SimpleNamespace(
            stop=lambda: calls.append(("state", "stop")) or True,
            control=lambda *a: calls.append(("state", "shutdown")),
        ),
        "errors": errors,
        "events": events,
        "args": options,
        "process": object(),
        "latencies": {"baseline": [1], "refresh": [1]},
        "baseline_process_count": 1,
        "quiet_bounds": (90, 99),
    }
    code = ast.Module(
        body=[
            ast.Try(body=[ast.Pass()], handlers=[], orelse=[], finalbody=guarded.finalbody),
            report_assignment,
            final_pass,
            write_report,
        ],
        type_ignores=[],
    )
    exec(compile(ast.fix_missing_locations(code), "<main-finally-report>", "exec"), namespace)
    report = json.loads(options.output.read_text())
    assert report["passed"] is False and errors
    assert report["checks"]["noIncorrectResponsesOrUnexpectedFailures"] is False
    if stuck in {"source", "league", "web"}:
        assert (stuck, "kill") in calls
    elif stuck.startswith("close_"):
        assert ("diagnostics", "close") in calls
    elif stuck == "web_nonzero":
        assert web.returncode == 3
    assert all(child.poll() is not None for child in (source, league, web))
    assert {
        ("reader", "join"),
        ("stream", "close"),
        ("fault", "join"),
        ("state", "stop"),
        ("state", "shutdown"),
    } <= set(calls)
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize(
    "case", ["valid", "noise", "invalid", "duplicate", "oversized", "truncated", "exit_mismatch"]
)
def test_stderr_discard_accounting_excludes_only_one_accepted_complete_receipt(capture, case):
    framing = wire(receipt())
    payload, code = framing, 0
    if case == "noise":
        payload = PRIVATE.encode() + b"\n" + framing
    elif case == "invalid":
        payload = (soak.WORKER_RECEIPT_PREFIX + "not-json\n").encode()
    elif case == "duplicate":
        payload += framing
    elif case == "oversized":
        payload = (soak.WORKER_RECEIPT_PREFIX + "x" * 8192 + "\n").encode()
    elif case == "truncated":
        payload = framing.rstrip(b"\n")
    elif case == "exit_mismatch":
        code = 1
    child = capture(payload, code=code)
    result = soak.finish_worker(child)
    retained = len(framing) if case in {"valid", "noise"} else 0
    assert result["stderrBytesObserved"] == len(payload)
    assert result["validReceiptFramingBytes"] == retained
    assert result["stderrBytesDiscarded"] == len(payload) - retained
    assert (
        result["stderrBytesObserved"]
        == result["validReceiptFramingBytes"] + result["stderrBytesDiscarded"]
    )
    assert (result["receiptError"] is None) is (retained > 0)
    assert PRIVATE not in json.dumps(result)
