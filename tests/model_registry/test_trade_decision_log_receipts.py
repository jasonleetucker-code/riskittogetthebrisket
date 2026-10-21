"""TC-C decision receipts through the AL-P5 path (no second receipt system).

Producer: ``src/trade/trade_decision_log.py::record_decision`` (the decision's
own run log, written at serve time by ``/api/trade/analyze``).  Adapter:
``producer_receipts.trade_decision_receipts``.  Recorder: the same
``scripts/trade_decision_receipts.py`` that records Best Offers runs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from src.model_registry import learning_receipt as lr
from src.model_registry import producer_receipts as pr
from src.model_registry.learning_receipt import KIND_DECISION, ReceiptError
from src.trade import trade_decision_log as tdl
from src.trade.analyze_trade import analyze_trade

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "trade_decision_receipts.py"


def _cli():
    spec = importlib.util.spec_from_file_location("trade_decision_receipts_cli_tcc", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _analysis():
    sim = {
        "team": {"name": "Our Team"},
        "receiving": [{"name": "Secret Receiver", "value": 6000, "confidenceBucket": "high"}],
        "sending": [{"name": "Secret Sender", "value": 5000, "confidenceBucket": "high"}],
        "teamContext": {"applied": False},
    }
    return analyze_trade(sim, provenance={"boardStamp": "2026-10-17T00:00:00+00:00"})


@pytest.fixture
def log(tmp_path):
    d = tmp_path / "decisions"
    run_id = tdl.record_decision(_analysis(), league_key="dynasty_main", team="Our Team", log_dir=d)
    assert run_id
    return d, run_id


def test_the_decision_log_is_a_registered_artifact_store_written_by_trade_decision():
    assert pr.TRADE_DECISION_STORE in lr.NATIVE_STORES
    assert pr.TRADE_DECISION_STORE in lr.ARTIFACT_STORES
    assert lr.ARTIFACT_STORE_WRITERS[pr.TRADE_DECISION_STORE] == {pr.TRADE_DECISION_PRODUCER}


def test_one_decision_receipt_points_into_the_line_and_copies_no_asset(log):
    d, run_id = log
    ((file_name, line),) = list(tdl.iter_decision_log_lines(d))
    (receipt,) = pr.trade_decision_receipts(line, file_name=file_name)
    out = receipt.to_dict()
    assert out["kind"] == KIND_DECISION and out["producer"] == "trade_decision"
    assert out["nativeId"] == run_id
    ref = out["slots"]["decisionSet"]
    assert ref["store"] == "trade_decision_log" and ref["key"] == f"{file_name}#{run_id}"
    assert out["slots"]["board"]["state"] == "unobserved"
    body = out["body"]
    assert body["headline"] == line["headline"] == "YES"
    assert body["action"] == "recommend_only" and body["promotes"] is False
    assert body["bands"] == "fairness_bands_v2"
    assert out["modelVersionId"].startswith("mv:trade_decision:trade_decision_v")
    text = json.dumps(out)
    for leaked in ("Secret Receiver", "Secret Sender"):
        assert leaked not in text
    # ...and the run line itself names no asset either.
    assert "Secret" not in json.dumps(line)


def test_a_line_without_its_receipt_is_refused(log):
    d, _ = log
    ((file_name, line),) = list(tdl.iter_decision_log_lines(d))
    bad = {k: v for k, v in line.items() if k != "receipt"}
    with pytest.raises(ReceiptError):
        pr.trade_decision_receipts(bad, file_name=file_name)


def test_the_recorder_script_reads_the_decision_log(log):
    d, _ = log
    receipts, refused, lines = _cli().build_decision_receipts(d)
    assert (len(receipts), refused, lines) == (1, [], 1)


def test_recording_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert (
        tdl.record_decision(_analysis(), league_key="k", team="t", log_dir=blocker / "sub") is None
    )
