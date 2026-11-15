"""The pre-auction unit's exit-code semantics must match the script's.

A terminal skip (draft started) must be a systemd SUCCESS, or every daily run
after the draft starts fails, retries, and fires failed-unit alerts.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import capture_pre_auction_snapshot as cap

_UNIT = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "systemd"
    / "dynasty-pre-auction-snapshot.service.template"
)


def _directive(name: str) -> str:
    m = re.search(rf"^{name}=(.*)$", _UNIT.read_text(encoding="utf-8"), re.M)
    assert m, name
    return m.group(1).strip()


def test_success_exit_status_is_ok_plus_terminal_skip_only():
    codes = {int(c) for c in _directive("SuccessExitStatus").split()}
    assert codes == {cap.EXIT_OK, cap.EXIT_SKIPPED}


def test_retryable_codes_are_failures_distinct_from_terminal_skip():
    success = {int(c) for c in _directive("SuccessExitStatus").split()}
    retry = {cap.EXIT_ERROR, cap.EXIT_TRANSIENT, cap.EXIT_NO_BOARD}
    assert retry.isdisjoint(success)
    assert len({cap.EXIT_OK, cap.EXIT_SKIPPED, *retry}) == 5
    assert _directive("Restart") == "on-failure"


def test_template_comment_documents_the_same_codes():
    text = _UNIT.read_text(encoding="utf-8")
    assert "SuccessExitStatus=0 5" in text
    assert "5 terminal skip" in text
