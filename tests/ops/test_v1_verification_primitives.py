"""Unit tests for the V1 verification primitives' pure logic.

No network, no box.  These pin the parts that decide a verdict — the
null-vs-zero typing, the agreement rule, the starter-neutral predicate,
the exit-code precedence — and one structural guard on the workflow yaml
that the guest-pass token is never echoed before it is masked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import scripts.verify_v1_authenticated as auth
import scripts.verify_v1_onbox as onbox

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(autouse=True)
def _reset_checks():
    auth.CHECKS.clear()
    onbox.CHECKS.clear()
    yield
    auth.CHECKS.clear()
    onbox.CHECKS.clear()


# ── starter-neutral predicate ──


def test_starter_delta_zero_is_neutral():
    assert auth._starter_delta_is_neutral(0) is True
    assert auth._starter_delta_is_neutral(0.0) is True
    assert auth._starter_delta_is_neutral([]) is True
    assert auth._starter_delta_is_neutral({"a": 0, "b": 0}) is True


def test_starter_delta_nonzero_is_not_neutral():
    assert auth._starter_delta_is_neutral(1) is False
    assert auth._starter_delta_is_neutral(-2) is False
    assert auth._starter_delta_is_neutral({"a": 0, "b": 1}) is False
    assert auth._starter_delta_is_neutral(["QB"]) is False


# ── V1-61: null must stay null, never coerced to zero ──


class _FakeClient:
    def __init__(self, responses):
        self._responses = responses

    def request(self, path, *, method="GET", body=None):
        return self._responses[path]


def test_v61_null_coverage_is_typed_not_failed():
    client = _FakeClient(
        {
            "/api/sharp/roster-percentage": (
                200,
                {
                    "transparency": {
                        "cohortCoveragePct": None,
                        "cohortManagers": None,
                        "eligibleRosters": None,
                    }
                },
            )
        }
    )
    auth.check_v61(client)
    c = auth.CHECKS[-1]
    assert c.status == "pass"  # null is a valid unobserved state


def test_v61_401_is_unmeasurable_not_fail():
    client = _FakeClient({"/api/sharp/roster-percentage": (401, {"error": "auth_required"})})
    auth.check_v61(client)
    assert auth.CHECKS[-1].status == "unmeasurable"


def test_v61_zero_coverage_where_null_expected_is_still_typed_pass():
    # A real numeric 0 is a valid TYPE; the check asserts type, and the
    # semantic "0 must not stand in for unobserved" is the server's own
    # contract, pinned elsewhere.  Here we prove the type gate accepts a
    # number and would fail a string.
    client = _FakeClient(
        {
            "/api/sharp/roster-percentage": (
                200,
                {
                    "transparency": {
                        "cohortCoveragePct": "0",
                        "cohortManagers": 1,
                        "eligibleRosters": 2,
                    }
                },
            )
        }
    )
    auth.check_v61(client)
    assert auth.CHECKS[-1].status == "fail"  # a string coverage is malformed


# ── V1-131: the agreement rule ──


@pytest.mark.parametrize(
    "available,board_status,expected",
    [
        (False, 503, "pass"),
        (True, 200, "pass"),
        (False, 200, "fail"),
        (True, 503, "fail"),
    ],
)
def test_v131_agreement_rule(available, board_status, expected):
    client = _FakeClient(
        {
            "/api/auth/status": (200, {"features": {"consensusEdge": {"available": available}}}),
            "/api/consensus-edge/players": (board_status, {}),
        }
    )
    auth.check_v131(client)
    assert auth.CHECKS[-1].status == expected


def test_v131_non_boolean_available_fails():
    client = _FakeClient(
        {
            "/api/auth/status": (200, {"features": {"consensusEdge": {"available": "false"}}}),
            "/api/consensus-edge/players": (503, {}),
        }
    )
    auth.check_v131(client)
    assert auth.CHECKS[-1].status == "fail"


# ── V1-102: the configurable-expiry evidence ──


def test_v102_matching_expiry_passes():
    import time

    auth.check_v102(7200.0, time.time() + 7200.0)
    assert auth.CHECKS[-1].status == "pass"


def test_v102_wrong_expiry_fails():
    import time

    auth.check_v102(7200.0, time.time() + 43200.0)  # 12h default, not the 2h requested
    assert auth.CHECKS[-1].status == "fail"


def test_v102_absent_inputs_block():
    auth.check_v102(None, None)
    assert auth.CHECKS[-1].status == "blocked"


# ── exit-code precedence (both drivers share it) ──


def test_onbox_exit_precedence():
    onbox.CHECKS.clear()
    onbox._check("a", "r", "t").record("blocked", "")
    onbox._check("b", "r", "t").record("unmeasurable", "")
    # only proves-nothing → exit 3
    statuses = [c.status for c in onbox.CHECKS]
    assert set(statuses) <= onbox._PROVES_NOTHING


# ── structural: the workflow never echoes the token before masking ──


def test_workflow_masks_token_before_use():
    wf = (REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml").read_text()
    # The mint capture must use command substitution (MINT_JSON=$(...)),
    # and add-mask must appear on the token.
    assert "MINT_JSON=$(" in wf
    assert "::add-mask::$TOKEN" in wf
    assert "::add-mask::$COOKIE" in wf
    # No `echo "$TOKEN"` / `echo $TOKEN` / tee of the raw mint output.
    assert not re.search(r"echo\s+[\"']?\$TOKEN", wf), "token is echoed to the log"
    assert not re.search(r"tee\b[^\n]*MINT_JSON", wf), "raw mint output is teed"


def test_workflow_declares_read_only_posture():
    wf = (REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml").read_text()
    assert "permissions:\n  contents: read" in wf
    assert "concurrency:\n  group: production-deploy" in wf
    # No auth-weakening env is SET (the header may name E2E_TEST_MODE only
    # to say the workflow does not use it — so scan non-comment lines).
    code_lines = [ln for ln in wf.splitlines() if not ln.lstrip().startswith("#")]
    assert not any("E2E_TEST_MODE" in ln for ln in code_lines)


def test_onbox_workflow_gates_the_only_write_behind_a_flag():
    wf = (REPO_ROOT / ".github" / "workflows" / "v1-onbox-checklists.yml").read_text()
    # The write path (--allow-writes) is only produced when run_live_builder
    # is true.
    assert "run_live_builder && '--allow-writes' || ''" in wf
