"""Structural + behavioural pins for the Signals IDP family rollback (PR-RB)
and the Signals health / native-probe workflow (PR-H / PR-P).

V1-49's guards (tests/deploy/test_v1_49_workflow_wiring.py), applied to the
new production writer: one fixed script, hard-coded keys, a closed family
choice, inputs reaching the shell only through env, rollback always OFF,
and post-verification on the SERVED board.
"""

from __future__ import annotations

import sys
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

# runs the production rollback shell with python3 on PATH; Windows has no python3 shim.
# Never skipped on Linux/CI.
_LINUX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Linux-only: runs the production rollback shell with python3 on PATH",
)


REPO = Path(__file__).resolve().parents[2]
ROLLBACK_WF = REPO / ".github" / "workflows" / "signals-idp-family-rollback.yml"
ROLLBACK_SH = REPO / "deploy" / "diagnostics" / "signals_idp_family_rollback.sh"
PROBE_WF = REPO / ".github" / "workflows" / "signals-health-probe.yml"

FAMILY_TABLE = {
    "dl": ("RISKIT_FEATURE_SIGNALS_IDP_DL_VOTE", "signals_idp_dl_vote", "signalsIdpDl"),
    "lb": ("RISKIT_FEATURE_SIGNALS_IDP_LB_VOTE", "signals_idp_lb_vote", "signalsIdpLb"),
    "db": ("RISKIT_FEATURE_SIGNALS_IDP_DB_VOTE", "signals_idp_db_vote", "signalsIdpDb"),
    "all-idp": (
        "RISKIT_FEATURE_SIGNALS_IDP_SHARED_MARKET",
        "signals_idp_shared_market",
        "signalsIdpDl signalsIdpLb signalsIdpDb",
    ),
    "all-signals": (
        "RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE",
        "signals_active_source",
        "signalsSf signalsIdpDl signalsIdpLb signalsIdpDb",
    ),
}
BASH = shutil.which("bash")


def _wf(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _inputs(doc: dict) -> dict:
    return doc.get("on", doc.get(True))["workflow_dispatch"]["inputs"]


# ── rollback workflow ────────────────────────────────────────────────────


def test_rollback_workflow_shape():
    doc = _wf(ROLLBACK_WF)
    assert doc["concurrency"] == {"group": "production-deploy", "cancel-in-progress": False}
    (job,) = doc["jobs"].values()
    assert job["environment"] == "production"
    inputs = _inputs(doc)
    assert set(inputs) == {"action", "family", "confirm", "expected_sha", "rollback_id", "reason"}
    assert set(inputs["action"]["options"]) == {"rollback", "restore"}
    assert set(inputs["family"]["options"]) == set(FAMILY_TABLE)
    assert not any("RISKIT_FEATURE" in str(spec) for spec in inputs.values())


def test_inputs_reach_the_shell_only_through_env():
    text = ROLLBACK_WF.read_text(encoding="utf-8")
    run_blocks = [
        step.get("run", "") for job in _wf(ROLLBACK_WF)["jobs"].values() for step in job["steps"]
    ]
    for block in run_blocks:
        assert "inputs.reason" not in block and "inputs.family" not in block
        assert "inputs.expected_sha" not in block and "inputs.rollback_id" not in block
    assert 'REASON=$(printf %q "$REASON_IN")' in text


def test_every_ssh_call_pipes_the_one_fixed_script():
    text = ROLLBACK_WF.read_text(encoding="utf-8")
    pipes = re.findall(r"< deploy/diagnostics/(\S+\.sh)", text)
    assert pipes and set(pipes) == {"signals_idp_family_rollback.sh"}
    keys = set(re.findall(r"([A-Z_][A-Z0-9_]*)=(?:rollback |restore |\$\(printf %q)", text))
    assert keys <= {
        "ACTION",
        "FAMILY",
        "APP_DIR",
        "PYTHON_BIN",
        "EXPECTED_SHA",
        "ROLLBACK_ID",
        "REASON",
    }


def test_the_script_only_ever_writes_off_and_restores_captured_state():
    text = ROLLBACK_SH.read_text(encoding="utf-8")
    assert re.findall(r'--value "([^"]*)"', text) == ["0"]
    assert text.count('prod_env_flag_ops.py" set') == 1
    assert text.count('prod_env_flag_ops.py" restore') == 1


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
def test_the_script_parses():
    subprocess.run([BASH, "-n", str(ROLLBACK_SH)], check=True)


def _source(snippet: str, **env) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", f'set -Eeuo pipefail; source "{ROLLBACK_SH}"; {snippet}'],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
    )


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
@pytest.mark.parametrize("family", sorted(FAMILY_TABLE))
def test_the_hard_coded_table(family):
    cp = _source(
        'resolve_family; printf "%s|%s|%s" "$FLAG_KEY" "$FLAG_GATE_NAME" "$SOURCE_KEYS"',
        FAMILY=family,
    )
    assert cp.returncode == 0, cp.stderr
    assert tuple(cp.stdout.split("|")) == FAMILY_TABLE[family]


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
@pytest.mark.parametrize("family", ["", "DL", "dl;rm", "../x", "offense"])
def test_an_unknown_family_is_refused(family):
    cp = _source("resolve_family", FAMILY=family)
    assert cp.returncode == 1 and "REFUSED" in cp.stderr


def _status(enabled, absent, has_data=True):
    return json.dumps(
        {
            "has_data": has_data,
            "featureFlags": {"signals_idp_dl_vote": {"enabled": enabled, "gateStatus": "LIVE"}},
            "served_private_absent_by_design": absent,
        }
    )


@pytest.mark.skipif(BASH is None, reason="bash unavailable")
@pytest.mark.parametrize(
    "body, want, ok",
    [
        (_status(False, ["signalsIdpDl"]), "False", True),
        (_status(False, []), "False", False),  # flag off but still served
        (_status(True, ["signalsIdpDl"]), "False", False),  # flag still on
        (_status(False, ["signalsIdpDl"], has_data=False), "False", False),
        (_status(True, []), "True", True),
        ("not json", "False", False),
    ],
)
@_LINUX_ONLY
def test_served_state_verification(tmp_path, body, want, ok):
    status = tmp_path / "status.json"
    status.write_text(body, encoding="utf-8")
    py = shutil.which("python3") or "python3"
    cp = _source(
        f'resolve_family; PYTHON_BIN={py}; curl() {{ cat "{status}"; }}; '
        f"verify_served_state {want}",
        FAMILY="dl",
        VERIFY_MAX_ATTEMPTS="1",
    )
    assert (cp.returncode == 0) is ok, cp.stdout + cp.stderr


# ── health / native-probe workflow ───────────────────────────────────────


def test_probe_workflow_runs_deployed_scripts_from_main_only():
    doc = _wf(PROBE_WF)
    assert doc["concurrency"]["group"] == "signals-onbox-verification"
    bundle, onbox = doc["jobs"]["bundle"], doc["jobs"]["onbox"]
    # Tier 0 never touches production: no environment, no secret
    assert "environment" not in bundle
    assert "secrets." not in json.dumps(bundle)
    assert onbox["environment"] == "production"
    names = [s["name"] for s in onbox["steps"]]
    assert names.index("Refuse unless dispatched from main") < names.index(
        "Configure production SSH"
    )
    text = PROBE_WF.read_text(encoding="utf-8")
    # the deployed copy runs; no runner copy is uploaded to the host
    assert "$APP_DIR/scripts/verify_signals_health.py" in text
    assert "$APP_DIR/scripts/probe_signals_native.py" in text
    assert "cat >" not in text
    assert set(_inputs(doc)["mode"]["options"]) == {"health", "native-bundle", "native-probe"}
    assert _inputs(doc)["allow_league_footprint"]["default"] is False
