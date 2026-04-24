"""Tests for the dynamic weights fitter + approval gate."""
from __future__ import annotations

import json

from src.backtesting import dynamic_weights as dw
from src.backtesting.correlation import SourceAccuracy


def _acc(source, rho, n=100):
    return SourceAccuracy(source=source, n_players=n, spearman_rho=rho, top_50_hit_rate=0.5)


def test_raw_weights_sum_to_one():
    accs = [_acc("A", 0.7), _acc("B", 0.6), _acc("C", 0.4)]
    w = dw.raw_weights_from_accuracy(accs)
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_raw_weights_higher_rho_gets_more():
    accs = [_acc("A", 0.8), _acc("B", 0.3)]
    w = dw.raw_weights_from_accuracy(accs)
    assert w["A"] > w["B"]


def test_raw_weights_filters_low_n_sources():
    accs = [_acc("A", 0.8, n=100), _acc("B", 0.9, n=10)]
    w = dw.raw_weights_from_accuracy(accs)
    assert "A" in w
    assert "B" not in w


def test_smooth_weights_converges_toward_new():
    """Repeated smoothing with the same new weights converges to them."""
    prior = {"A": 0.6, "B": 0.4}
    new = {"A": 0.2, "B": 0.8}
    cur = prior
    for _ in range(30):
        cur = dw.smooth_weights_ewma(cur, new, alpha=0.25)
    assert abs(cur["A"] - new["A"]) < 0.01
    assert abs(cur["B"] - new["B"]) < 0.01


def test_smooth_weights_handles_new_source():
    prior = {"A": 1.0}
    new = {"A": 0.5, "B": 0.5}
    out = dw.smooth_weights_ewma(prior, new)
    assert abs(sum(out.values()) - 1.0) < 1e-6
    assert "B" in out


def test_propose_weights_no_change_when_no_eligible_sources():
    prior = {"A": 0.5, "B": 0.5}
    accs = [_acc("A", 0.7, n=5), _acc("B", 0.6, n=5)]  # both below min_n
    out = dw.propose_weights(accs, prior)
    assert out.status == "no_change"
    assert out.weights == prior


def test_propose_weights_approved_when_drift_small():
    prior = {"A": 0.5, "B": 0.5}
    # New weights close to 0.5 each → small drift.
    accs = [_acc("A", 0.5), _acc("B", 0.48)]
    out = dw.propose_weights(accs, prior, alpha=0.1)
    assert out.status == "approved"


def test_propose_weights_pending_when_drift_large():
    """Massive rho gap → new weights deviate from prior → gate fires."""
    prior = {"A": 0.5, "B": 0.5}
    accs = [_acc("A", 0.95), _acc("B", -0.5)]
    out = dw.propose_weights(accs, prior, alpha=1.0, tolerance_pct=0.10)
    assert out.status == "pending_approval"
    assert out.max_drift_pct > 0.10


def test_save_and_load_weights_round_trip(tmp_path):
    path = tmp_path / "dyn.json"
    dw.save_weights({"A": 0.6, "B": 0.4}, path=path, meta={"refit_at": "2026-04-24"})
    got = dw.load_prior_weights(path)
    assert got == {"A": 0.6, "B": 0.4}


def test_load_missing_returns_empty(tmp_path):
    assert dw.load_prior_weights(tmp_path / "absent.json") == {}


def test_load_malformed_returns_empty(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid", encoding="utf-8")
    assert dw.load_prior_weights(p) == {}


def test_save_file_structure(tmp_path):
    path = tmp_path / "dyn.json"
    dw.save_weights({"A": 0.6}, path=path, meta={"hash": "abc123"})
    body = json.loads(path.read_text(encoding="utf-8"))
    assert "weights" in body
    assert "meta" in body
    assert body["meta"]["hash"] == "abc123"
