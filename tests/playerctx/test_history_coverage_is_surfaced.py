"""Retention coverage must reach a surface someone reads.

`store.history_coverage` was written to make a halted retention timer
visible "before a study needs the data rather than after it produces a
wrong answer" — and was then wired to nothing at all, while its sibling
`rank_history.coverage()` was surfaced on `/api/status` with a comment
making the identical argument.

That gap is why the 2026-08-05 deploy could install the producer, skip
the pusher, and leave the only symptom in a deploy log nobody re-reads.
A monitor that exists but is unreachable reads exactly like a working
one, which is the failure this repo keeps rediscovering.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SERVER = _REPO / "server.py"


def _server() -> str:
    return _SERVER.read_text(encoding="utf-8", errors="replace")


def test_the_status_payload_carries_retention_coverage():
    body = _server()
    assert '"playerctxHistoryCoverage": _playerctx_history_coverage_safe()' in body


def test_the_helper_exists_and_never_raises():
    """Same contract as `_rank_history_coverage_safe`: a diagnostic that
    can take down the endpoint it reports on is worse than none."""
    body = _server()
    assert "def _playerctx_history_coverage_safe()" in body
    block = body.split("def _playerctx_history_coverage_safe()", 1)[1].split("\ndef ", 1)[0]
    assert "except Exception" in block
    assert "return {}" in block


def test_the_helper_uses_a_repo_root_that_server_actually_defines():
    """The first draft passed `REPO_ROOT`, which `server.py` does not
    define — a NameError inside the try, swallowed by the same guard that
    makes the helper safe, so the field would have silently reported `{}`
    forever. A monitor that always says "nothing to see" is worse than no
    monitor, because it looks like a passing check.
    """
    body = _server()
    block = body.split("def _playerctx_pending_push(", 1)[1].split("\ndef ", 1)[0]
    names = set(re.findall(r"cwd=str\((\w+)\)", block))
    assert names, "the git probe must run in an explicit working directory"
    for name in names:
        assert re.search(rf"^{name} = ", body, re.M), f"{name} is not defined in server.py"


def test_pending_push_is_measured_not_assumed():
    """The producer and the pusher fail independently.

    `history_coverage` sees only the first: a stalled pusher leaves the
    local directory looking perfect while `main` gets nothing, which is
    the failure that actually happened. `data/` is gitignored repo-wide
    and retained snapshots reach the tree only via an explicit
    `git add -f`, so "on disk but untracked" is exactly "written but not
    pushed".
    """
    body = _server()
    assert "def _playerctx_pending_push(" in body
    block = body.split("def _playerctx_pending_push(", 1)[1].split("\ndef ", 1)[0]
    assert "ls-files" in block
    assert "pendingPush" in block
    # Absence of an answer must not be reported as zero pending.
    assert "return {}" in block


def test_the_probe_cannot_hang_the_status_endpoint():
    """`/api/status` is polled by the settings page and the tools pages.
    A subprocess without a timeout there is a way to wedge all of them."""
    body = _server()
    block = body.split("def _playerctx_pending_push(", 1)[1].split("\ndef ", 1)[0]
    assert "timeout=" in block
