"""Production baseline uses the existing ephemeral guest-auth owner."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/v1-authenticated-verification.yml"


def test_opt_in_baseline_does_not_change_legacy_suites():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "options: [api, browser, all, baseline]" in text
    assert text.count("inputs.suite != 'browser' && inputs.suite != 'baseline'") == 2
    assert "(inputs.suite != 'api' && inputs.suite != 'baseline')" in text
    assert "node-version: '20'" in text
    assert "--auth production-cookie --runs 5 --viewport both" in text
    assert "--routes /rankings,/trade" in text
    assert "PROD_SESSION_EXPIRES_EPOCH: ${{ steps.login.outputs.expires_epoch }}" in text
    assert '"$BASELINE_REQUESTED" = "true"' in text
    assert '"$BASELINE_EXIT" != "0"' in text


def test_revocation_and_report_privacy_preserved():
    text = WORKFLOW.read_text(encoding="utf-8")
    revoke = text.split("- name: Revoke the pass (always)", 1)[1].split("- name: Fail the job", 1)[
        0
    ]
    assert "always() && steps.mint.outputs.pass_id != ''" in revoke
    assert "guest_passes.revoke(pass_id)" in revoke
    assert "trap 'rm -f --" in revoke
    uploads = text.split("- name: Upload the reports", 1)[1]
    assert "production-route-baselines.json" in uploads
    assert "session_cookie" not in uploads
    assert "guest_pass_token" not in uploads
    assert "RUNNER_TEMP" not in uploads


def test_new_workflow_steps_are_blocking():
    data = json.loads((ROOT / "config/ci/release_gate_classification.json").read_text())

    def find(value, key):
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for item in value.values():
                result = find(item, key)
                if result is not None:
                    return result
        return None

    for step in ("Set up Node 20 for production baseline", "Collect authenticated route baseline"):
        key = "v1-authenticated-verification.yml::v1-authenticated::" + step
        assert find(data, key) == {"category": "blocking"}


def test_baseline_origin_guard_precedes_every_credential_action():
    text = WORKFLOW.read_text(encoding="utf-8")
    guard = text.index('"$PROD_PUBLIC_URL" != "https://chaseupside.com"')
    assert guard < text.index("- name: Configure production SSH")
    assert guard < text.index("- name: Mint an ephemeral verification guest pass")
    assert guard < text.index("- name: Log in through the real auth path")
    resolve = text.split("- name: Resolve production origin", 1)[1].split(
        "- name: Configure production SSH", 1
    )[0]
    assert "BASELINE_REQUESTED:" in resolve
    assert 'if [ "$BASELINE_REQUESTED" = "true" ]' in resolve
    assert resolve.index("baseline production origin is not approved") < resolve.index(
        'echo "ORIGIN='
    )


def test_actual_baseline_login_opener_refuses_redirects_and_untrusted_origin():
    import ast
    import textwrap
    import urllib.request

    import pytest

    text = WORKFLOW.read_text(encoding="utf-8")
    login = text.split("- name: Log in through the real auth path", 1)[1].split(
        "- name: API verification suite", 1
    )[0]
    code = textwrap.dedent(login.split("<<'PYEOF'\n", 1)[1].split("          PYEOF", 1)[0])
    tree = ast.parse(code)
    definitions = ast.Module(
        body=[node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))],
        type_ignores=[],
    )
    import urllib

    namespace = {"urllib": urllib}
    exec(compile(definitions, "workflow-login-definitions", "exec"), namespace)
    opener = namespace["login_opener"]
    with pytest.raises(ValueError, match="baseline_origin_refused"):
        opener("https://unrelated.invalid", True)
    assert opener("https://legacy.example", False) is urllib.request.urlopen
    bound = opener("https://chaseupside.com", True)
    handlers = bound.__self__.handlers
    redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
    assert len(redirects) == 1
    for status in (301, 302, 303, 307, 308):
        assert (
            redirects[0].redirect_request(None, None, status, "", {}, "https://unrelated.invalid")
            is None
        )
    assert code.index("open_login = login_opener") < code.index("token = open(")
    assert "with open_login(req, timeout=30)" in code
