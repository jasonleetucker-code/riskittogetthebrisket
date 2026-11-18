"""Rank-form drift: standing accepted drift is green, new/worse drift is red (T15).

``audit-rank-form-drift.yml`` failed every week since 2026-08-18 on a drift
that awaits an owner decision (issue #898).  A permanently red check is noise;
a blanket ``continue-on-error`` would be a silent pass.  The tripwire keeps it
meaningful: accepted state is recorded in config, anything worse still fails.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import rank_form_drift_tripwire as tw  # noqa: E402

ACCEPTED = json.loads(
    (ROOT / "config" / "ci" / "rank_form_drift_accepted.json").read_text(encoding="utf-8")
)


def _verdict(offense: float, idp: float, thr: float = 25.0) -> dict:
    scopes = {
        "offense": {"excessRmse": offense, "drifted": offense > thr},
        "idp": {"excessRmse": idp, "drifted": idp > thr},
    }
    return {"scopes": scopes, "drifted": [k for k, v in scopes.items() if v["drifted"]]}


def test_no_drift_is_ok():
    assert tw.classify(_verdict(5, 5), ACCEPTED)[0] == "ok"


def test_recorded_standing_drift_is_accepted():
    assert tw.classify(_verdict(96.5, 181.8), ACCEPTED)[0] == "accepted"


def test_improvement_is_still_accepted():
    assert tw.classify(_verdict(60, 100), ACCEPTED)[0] == "accepted"


def test_worse_drift_fails():
    state, reasons = tw.classify(_verdict(96.5 + 25.1, 181.8), ACCEPTED)
    assert state == "worse" and "offense" in reasons[0]


def test_new_drifted_scope_fails():
    accepted = dict(ACCEPTED, scopes={"offense": ACCEPTED["scopes"]["offense"]})
    state, reasons = tw.classify(_verdict(96.5, 40), accepted)
    assert state == "worse" and "NEW drifted scope" in reasons[0]


def test_cli_exit_codes_and_outputs(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    summary = tmp_path / "sum.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    good = tmp_path / "v.json"
    good.write_text(json.dumps(_verdict(96.5, 181.8)), encoding="utf-8")
    assert tw.main(["--verdict", str(good)]) == 0
    assert "state=accepted" in out.read_text(encoding="utf-8")
    assert "Pending owner decision" in summary.read_text(encoding="utf-8")
    assert "::warning" in capsys.readouterr().out
    bad = tmp_path / "w.json"
    bad.write_text(json.dumps(_verdict(300, 181.8)), encoding="utf-8")
    assert tw.main(["--verdict", str(bad)]) == 2
    assert tw.main(["--verdict", str(tmp_path / "missing.json")]) == 1


def test_accepted_record_names_owner_decision():
    for key in ("pendingOwnerDecision", "decisionReference", "recordedAt", "worseningMargin"):
        assert ACCEPTED.get(key), key


def test_workflow_gates_on_the_tripwire_state():
    wf = yaml.safe_load(
        (ROOT / ".github/workflows/audit-rank-form-drift.yml").read_text(encoding="utf-8")
    )
    steps = {s["name"]: s for s in wf["jobs"]["audit"]["steps"]}
    assert steps["Classify drift against the accepted baseline"]["id"] == "tripwire"
    assert "worse" in steps["Open or update an issue on drift"]["if"]
    fail = steps["Fail loudly on drift or error"]
    assert "continue-on-error" not in fail
    assert "'accepted'" in fail["if"] and "'ok'" in fail["if"]
    # An accepted standing drift must never close the tracker carrying the decision.
    assert "state == 'ok'" in steps["Close the tracking issue when the drift audit is green"]["if"]


def test_non_finite_excess_rmse_is_error_never_accepted():
    for bad in (float("nan"), float("inf"), float("-inf")):
        v = _verdict(96.5, 181.8)
        v["scopes"]["offense"]["excessRmse"] = bad
        state, reasons = tw.classify(v, ACCEPTED)
        assert state == "error", (bad, state)
        assert reasons and "not finite" in reasons[0]


def test_nan_in_json_verdict_exits_nonzero(tmp_path):
    v = tmp_path / "v.json"
    # json.dumps writes the non-standard token NaN, which json.loads accepts.
    v.write_text(json.dumps(_verdict(float("nan"), 181.8)), encoding="utf-8")
    acc = ROOT / "config" / "ci" / "rank_form_drift_accepted.json"
    assert tw.main(["--verdict", str(v), "--accepted", str(acc)]) == 1
