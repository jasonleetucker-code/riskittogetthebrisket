"""AL-P5: DECISION receipts for served Best Offers runs.

Producer: ``src/trade/best_offers.py::record_run`` (the run log, written at serve
time). Adapter: ``producer_receipts.best_offers_decision_receipts``. Recorder:
``scripts/trade_decision_receipts.py``, run by ``deploy/deploy.sh``.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.model_registry import learning_receipt as lr
from src.model_registry import producer_receipts as pr
from src.model_registry import receipt_store as rs
from src.model_registry.learning_receipt import KIND_DECISION, ReceiptError
from src.trade import best_offers as bo

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "trade_decision_receipts.py"
DEPLOY = REPO / "deploy" / "deploy.sh"


def _load_script():
    spec = importlib.util.spec_from_file_location("trade_decision_receipts_cli", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cli = _load_script()


def _payload():
    return {
        "myTeam": "Us",
        "rankingMethod": {
            "id": "best_offers_prior_v3",
            "status": "PRIOR_UNVALIDATED",
            "weights": {"mutualBalance": 0.4, "lineupImpact": 0.3},
            "configPath": "config/trade/best_offers_prior.json",
        },
        "teamContext": {"applied": True},
        "opponents": [
            {
                "team": "Them",
                "status": "qualified",
                "offer": {
                    "send": [{"name": "Our WR", "assetId": "player:1"}],
                    "receive": [{"name": "Their RB", "assetId": "player:2"}],
                    "score": 0.6,
                    "rankingFactors": {"mutualBalance": 0.5},
                    "external": {"calculator": "ktc"},
                },
            },
            {"team": "Other", "status": "no_result", "noResultReason": "no_canonical_win"},
            {"team": "Third", "status": "no_result", "noResultReason": "no_canonical_win"},
        ],
    }


@pytest.fixture(autouse=True)
def _isolated_decision_log(tmp_path, monkeypatch):
    """The recorder also reads the /api/trade/analyze decision log (TC-C). Its
    default comes from RISKIT_TRADE_DECISION_LOG_DIR, which conftest points at
    one shared directory that other tests in the same run write to -- so these
    Best Offers counts must not see it."""
    monkeypatch.setenv("RISKIT_TRADE_DECISION_LOG_DIR", str(tmp_path / "decisions"))


@pytest.fixture
def run_log(tmp_path):
    """A real run log, written by the producer's own recorder."""
    log_dir = tmp_path / "runs"
    run_id = bo.record_run(
        _payload(), league_key="main", board_stamp="2026-10-15T10:00:00+00:00", log_dir=log_dir
    )
    assert run_id
    return log_dir, run_id


def _lines(log_dir):
    return list(bo.iter_run_log_lines(log_dir))


def test_the_run_log_is_a_registered_artifact_store_written_by_best_offers():
    assert pr.BEST_OFFERS_STORE in lr.NATIVE_STORES
    assert pr.BEST_OFFERS_STORE in lr.ARTIFACT_STORES
    assert lr.ARTIFACT_STORE_WRITERS[pr.BEST_OFFERS_STORE] == {pr.BEST_OFFERS_PRODUCER}


def test_one_decision_receipt_points_into_the_run_line_and_copies_no_offer(run_log):
    log_dir, run_id = run_log
    ((file_name, line),) = _lines(log_dir)
    (receipt,) = pr.best_offers_decision_receipts(line, file_name=file_name)
    d = receipt.to_dict()
    assert d["kind"] == KIND_DECISION
    assert d["producer"] == "best_offers"
    assert d["nativeId"] == run_id
    assert lr.parse_instant(d["cutoff"], what="c") == lr.parse_instant(line["recordedAt"], what="r")
    ref = d["slots"]["decisionSet"]
    assert ref["store"] == "best_offers_run_log"
    assert ref["key"] == f"{file_name}#{run_id}"
    assert ref["role"] == "artifact" and ref["producedFor"] == run_id
    # the board is named only by a stamp, never guessed into a reference
    assert d["slots"]["board"]["state"] == "unobserved"
    body = d["body"]
    assert (body["opponents"], body["qualified"]) == (3, 1)
    assert body["noResultReasons"] == {"no_canonical_win": 2}
    assert body["promotes"] is False and body["action"] == "recommend_only"
    assert body["nonAction"]["state"] == "not_applicable"
    text = json.dumps(d)
    for leaked in ("Our WR", "Their RB", "player:1", "player:2", '"Us"'):
        assert leaked not in text
    assert d["modelVersionId"].startswith("mv:best_offers_prior:best_offers_prior_v3-w")


def test_different_weights_are_a_different_model_version(run_log):
    log_dir, _ = run_log
    ((file_name, line),) = _lines(log_dir)
    (a,) = pr.best_offers_decision_receipts(line, file_name=file_name)
    changed = json.loads(json.dumps(line))
    changed["rankingMethod"]["weights"]["lineupImpact"] = 0.31
    (b,) = pr.best_offers_decision_receipts(changed, file_name=file_name)
    assert a.model_version_id != b.model_version_id


@pytest.mark.parametrize(
    "mutate",
    [
        lambda line: line.pop("runId"),
        lambda line: line.pop("recordedAt"),
        lambda line: line.__setitem__("recordedAt", "2026-10-15"),  # no time component
        lambda line: line.pop("rankingMethod"),
        lambda line: line["rankingMethod"].pop("weights"),
        lambda line: line.__setitem__("opponents", None),
        lambda line: line.pop("leagueKey"),
    ],
)
def test_a_malformed_line_is_refused_never_given_a_placeholder(run_log, mutate):
    log_dir, _ = run_log
    ((file_name, line),) = _lines(log_dir)
    bad = json.loads(json.dumps(line))
    mutate(bad)
    with pytest.raises((ReceiptError, ValueError)):
        pr.best_offers_decision_receipts(bad, file_name=file_name)


def test_the_recorder_is_idempotent_and_writes_only_when_enabled(
    run_log, tmp_path, monkeypatch, capsys
):
    log_dir, _ = run_log
    store = tmp_path / "receipts.sqlite"
    monkeypatch.delenv(pr.RECEIPTS_ENABLED_ENV, raising=False)
    assert cli.main(["--log-dir", str(log_dir), "--store", str(store)]) == cli.EXIT_OK
    assert not store.exists()
    assert json.loads(capsys.readouterr().out)["written"] is None

    monkeypatch.setenv(pr.RECEIPTS_ENABLED_ENV, "1")
    assert cli.main(["--log-dir", str(log_dir), "--store", str(store)]) == cli.EXIT_OK
    first = json.loads(capsys.readouterr().out)
    assert (first["written"], first["duplicates"]) == (1, 0)
    assert cli.main(["--log-dir", str(log_dir), "--store", str(store)]) == cli.EXIT_OK
    again = json.loads(capsys.readouterr().out)
    assert (again["written"], again["duplicates"]) == (0, 1)
    assert [r["kind"] for r in rs.iter_receipts(store)] == [KIND_DECISION]


def test_a_corrupt_line_is_counted_as_refused_and_the_rest_still_recorded(
    run_log, tmp_path, monkeypatch, capsys
):
    log_dir, _ = run_log
    (log_file,) = log_dir.glob("runs-*.jsonl")
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    store = tmp_path / "receipts.sqlite"
    monkeypatch.setenv(pr.RECEIPTS_ENABLED_ENV, "1")
    # A permanently invalid line is reported, but cannot fail every future deploy.
    assert cli.main(["--log-dir", str(log_dir), "--store", str(store)]) == cli.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["written"] == 1 and out["refusedCount"] == 1


def test_an_unterminated_final_line_is_an_append_in_progress_not_a_refusal(run_log):
    log_dir, run_id = run_log
    (log_file,) = log_dir.glob("runs-*.jsonl")
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write('{"runId": "half')  # no newline: still being written
    lines = _lines(log_dir)
    assert [line["runId"] for _, line in lines] == [run_id]


def test_no_run_log_yet_is_an_empty_run_not_an_error(tmp_path, capsys):
    assert cli.main(["--log-dir", str(tmp_path / "absent"), "--dry-run"]) == cli.EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["runLogPresent"] is False and out["receipts"] == 0


def _function(text: str, name: str) -> str:
    start = text.index(f"\n{name}() {{")
    end = text.index("\n}\n", start)
    return text[start : end + 3]


def test_deploy_records_them_after_success_bounded_and_non_fatal():
    text = DEPLOY.read_text(encoding="utf-8")
    main = text[text.index("\nmain() {") :]
    assert main.index("\n  trap - ERR\n") < main.index("\n  record_trade_decision_receipts\n")
    fn = _function(text, "record_trade_decision_receipts")
    assert "scripts/trade_decision_receipts.py" in fn
    assert 'if output="$(RISKIT_RECEIPTS_ENABLED=1 timeout 300 ' in fn
    assert fn.rstrip().endswith("return 0\n}")


def test_the_serving_path_does_not_emit_receipts():
    """AL-P5 acceptance: producer outputs byte-identical — no receipt code on the route."""
    import inspect

    import server

    src = inspect.getsource(server.post_trade_best_offers)
    assert "receipt" not in src.lower()
