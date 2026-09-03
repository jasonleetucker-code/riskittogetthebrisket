"""V1-125 composite zero-live-second-owner acceptance gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "v1_125_zero_second_owner.py"


def _gate_module():
    spec = importlib.util.spec_from_file_location("v1_125_zero_second_owner", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_v1_125_reconciliation_has_exact_v1_family_coverage():
    gate = _gate_module()
    code, messages = gate.evaluate(run_commands=False)
    assert code == gate.EXIT_OK, messages
    assert len(gate.FAMILIES) == 9


def test_v1_125_zero_live_second_owner_gate():
    gate = _gate_module()
    code, messages = gate.evaluate(run_commands=True)
    assert code == gate.EXIT_OK, "\n\n".join(messages)
    assert any(
        message == "MEASURED: 0 live second owners across 9 V1-applicable retirement families"
        for message in messages
    )
