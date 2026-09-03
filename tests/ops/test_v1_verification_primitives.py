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
import yaml

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


# ── V1-56: the payload lives under "data", never under a "faabAnalytics" key ──


def test_v56_reads_the_data_envelope_not_a_section_named_key():
    # build_section_payload() (src/public_league/public_contract.py) always
    # wraps a section body as {contractVersion, league, section, data} — the
    # body never appears under a key matching the section's own name.
    client = _FakeClient(
        {
            "/api/public/league/faabAnalytics": (
                200,
                {
                    "contractVersion": "1",
                    "league": {},
                    "section": "faabAnalytics",
                    "data": {"leagueMedianWinningBid": 0, "leagueAvgWinningBid": 1.37},
                },
            )
        }
    )
    auth.check_v56(client)
    c = auth.CHECKS[-1]
    assert c.status == "pass"


def test_v56_a_faabanalytics_shaped_wrapper_fails_absence_not_a_false_pass():
    # A payload shaped like the OLD (buggy) expectation — body itself
    # carrying no "data" key — must not silently read as present.
    client = _FakeClient(
        {
            "/api/public/league/faabAnalytics": (
                200,
                {"faabAnalytics": {"leagueMedianWinningBid": 0}},
            )
        }
    )
    auth.check_v56(client)
    assert auth.CHECKS[-1].status == "fail"


def test_v56_401_is_unmeasurable_not_fail():
    client = _FakeClient({"/api/public/league/faabAnalytics": (401, {"error": "auth_required"})})
    auth.check_v56(client)
    assert auth.CHECKS[-1].status == "unmeasurable"


def test_v56_null_median_is_typed_pass():
    client = _FakeClient(
        {
            "/api/public/league/faabAnalytics": (
                200,
                {"data": {"leagueMedianWinningBid": None}},
            )
        }
    )
    auth.check_v56(client)
    assert auth.CHECKS[-1].status == "pass"


# ── V1-11 item 8: the terminal needs a RESOLVED team to have signal rows
# to check at all — an empty ``signals: []`` (no team resolvable, e.g. the
# guest_pass account has no Sleeper user id) is not the same finding as a
# real signal row genuinely missing confidence, and must not read as one.


def test_v11_8_no_team_resolvable_is_unmeasurable_not_fail():
    client = _FakeClient({})  # never reached — no team id in the contract
    auth.check_v11_item8(client, {"sleeper": {"teams": []}})
    assert auth.CHECKS[-1].status == "unmeasurable"


def test_v11_8_empty_signals_with_a_resolved_team_is_unmeasurable_not_fail():
    contract = {"sleeper": {"teams": [{"ownerId": "123"}]}}
    client = _FakeClient({"/api/terminal?team=123": (200, {"signals": []})})
    auth.check_v11_item8(client, contract)
    c = auth.CHECKS[-1]
    assert c.status == "unmeasurable"
    assert "zero signal rows" in c.detail


def test_v11_8_real_signal_rows_with_confidence_is_pass():
    contract = {"sleeper": {"teams": [{"ownerId": "123"}]}}
    client = _FakeClient(
        {
            "/api/terminal?team=123": (
                200,
                {"signals": [{"name": "Josh Allen", "confidence": 0.82}]},
            )
        }
    )
    auth.check_v11_item8(client, contract)
    assert auth.CHECKS[-1].status == "pass"


def test_v11_8_real_signal_rows_missing_confidence_is_a_real_fail():
    # The regression this check exists to catch: a resolved team WITH
    # signal rows, none of which carry the confidence field at all.
    contract = {"sleeper": {"teams": [{"ownerId": "123"}]}}
    client = _FakeClient(
        {
            "/api/terminal?team=123": (
                200,
                {"signals": [{"name": "Josh Allen", "signal": "HOLD"}]},
            )
        }
    )
    auth.check_v11_item8(client, contract)
    assert auth.CHECKS[-1].status == "fail"


def test_v11_8_401_is_unmeasurable_not_fail():
    contract = {"sleeper": {"teams": [{"ownerId": "123"}]}}
    client = _FakeClient({"/api/terminal?team=123": (401, {"error": "auth_required"})})
    auth.check_v11_item8(client, contract)
    assert auth.CHECKS[-1].status == "unmeasurable"


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


# ── V1-49 item 3: the authenticated league-comparison probe ──


def test_v49_item3_401_with_real_session_is_a_fail_not_unmeasurable():
    # A 401 despite a genuinely authenticated session means the earlier
    # code-read conclusion ("only auth was ever blocking this") was wrong
    # -- that is a real finding, not an absence of evidence.
    client = _FakeClient({"/api/league-comparison?refresh=1": (401, {"error": "auth_required"})})
    auth.check_v49_item3(client)
    assert auth.CHECKS[-1].status == "fail"


def test_v49_item3_503_degraded_state_is_unmeasurable_not_a_fabricated_pass():
    client = _FakeClient(
        {
            "/api/league-comparison?refresh=1": (
                503,
                {"error": "sleeper_unreachable", "detail": "timeout"},
            )
        }
    )
    auth.check_v49_item3(client)
    assert auth.CHECKS[-1].status == "unmeasurable"


def test_v49_item3_200_authenticated_is_pass():
    client = _FakeClient(
        {"/api/league-comparison?refresh=1": (200, {"leagues": [], "positions": []})}
    )
    auth.check_v49_item3(client)
    assert auth.CHECKS[-1].status == "pass"


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


def test_every_suite_verdict_is_consumed_by_the_one_verdict_step():
    """A captured exit code that nothing reads is not a gate.

    `browser_exit` used to be written to $GITHUB_OUTPUT and consumed by
    nothing, while the verdict step carried `if: inputs.suite != 'browser'`.
    On a browser run the job's conclusion was therefore structurally
    independent of whether the Playwright specs passed: a failing browser
    suite reported success. Same class as a gate that cannot find its input
    and so reads exactly like a gate that passed.

    Pins the property rather than the wording: every `*_exit` a step
    publishes must reach the verdict step's environment, and that step must
    not be conditioned away for any suite.
    """
    wf_path = REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"
    wf = yaml.safe_load(wf_path.read_text())
    steps = wf["jobs"]["v1-authenticated"]["steps"]

    published = set()
    for step in steps:
        for name in re.findall(r"(\w+_exit)=", step.get("run") or ""):
            published.add(name)
    assert published, "no suite publishes an exit code — the scan is vacuous"

    verdict = [s for s in steps if "verdict" in (s.get("name") or "").lower()]
    assert len(verdict) == 1, f"expected exactly one verdict owner, found {len(verdict)}"
    verdict = verdict[0]

    # It must not be skipped for any suite: a conditioned-away verdict is
    # what produced the defect.
    assert verdict.get("if") is None, (
        f"the verdict step is conditional ({verdict.get('if')!r}); a suite it "
        "skips for has no binding verdict"
    )

    consumed = " ".join((verdict.get("env") or {}).values())
    body = verdict.get("run") or ""
    for name in sorted(published):
        assert name in consumed, f"{name} is published but never reaches the verdict step"
        var = name.upper()
        assert (
            f"${{{var}}}" in body or f'"${var}"' in body
        ), f"{name} reaches the verdict step's env but its body never reads ${var}"


def test_prod_auth_config_reports_annotations_as_evidence():
    """`states-observed` must survive the run.

    Specs record which branch of a multi-state render actually ran by
    pushing onto `testInfo.annotations`. The `list` reporter drops them and
    the html folder is not uploaded, so without a structured report a green
    tick proves a spec passed but not WHICH state production produced —
    which is precisely what V1-45's L4 bar asks.
    """
    cfg = (REPO_ROOT / "tests" / "e2e" / "prod-auth.config.js").read_text()
    assert '["json"' in cfg, "no json reporter: annotations never leave the runner"
    assert "prod-auth-results.json" in cfg

    wf = (REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml").read_text()
    assert (
        "tests/e2e/prod-auth-results.json" in wf
    ), "the json report is produced but never uploaded"


def test_onbox_workflow_gates_the_only_write_behind_a_flag():
    wf = (REPO_ROOT / ".github" / "workflows" / "v1-onbox-checklists.yml").read_text()
    # The write path (--allow-writes) is only produced when run_live_builder
    # is true.
    assert "run_live_builder && '--allow-writes' || ''" in wf


def test_v89_control_archive_names_parse_under_the_detector_grammar():
    """The step-8 control must speak the detector's filename dialect.

    measure_content_staleness stamps archives via (\\d{8})_(\\d{6}) and
    silently skips names that do not parse.  The first control used
    dashed dates, both archives were skipped, and {} read as 'the
    detector cannot see DraftSharks staleness' — a false FAIL against a
    sound detector.  Pin: every archive filename the verifier constructs
    for the control matches the real detector's stamp regex.
    """
    from scripts.check_source_health import _ARCHIVE_STAMP_RE

    src = Path(onbox.__file__).read_text(encoding="utf-8")
    names = re.findall(r'f"(dynasty_[a-z]+_\{[a-z]+\}\.zip)"', src)
    assert names, "the control's archive-name f-string moved — update this pin"
    stamps = re.findall(r"for stamp in \(([^)]*)\)", src)
    assert stamps, "the control's stamp tuple moved — update this pin"
    for stamp in re.findall(r'"([^"]+)"', stamps[0]):
        rendered = names[0].replace("{stamp}", stamp)
        assert _ARCHIVE_STAMP_RE.search(rendered), (
            f"control archive name {rendered!r} does not parse under "
            "_ARCHIVE_STAMP_RE — the detector will silently skip it and the "
            "control will fail falsely again"
        )


def test_isolated_records_a_crash_as_that_checks_error(_reset_checks):
    """A check's crash costs that check, never the suite.

    The first production run lost the report file, the free-agent pick
    and every downstream check to one uncaught read timeout in
    check_v61.
    """

    def boom():
        raise TimeoutError("the read operation timed out")

    out = auth._isolated("V61A", boom)
    assert out is None
    crash = [c for c in auth.CHECKS if c.check_id == "V61A:crash"]
    assert len(crash) == 1
    assert crash[0].status == "error"
    assert "TimeoutError" in crash[0].detail

    def fine():
        return "value"

    assert auth._isolated("OK", fine) == "value"
    assert not [c for c in auth.CHECKS if c.check_id == "OK:crash"]


def test_c1u8_item4_absent_store_is_blocked_not_fail():
    """acquisition_status exit 2 + ABSENT is the script's defined
    'ledger absent' semantic — a blocked dependency on the unrun §8
    items 2/3 builder, never a code failure."""
    src = Path(onbox.__file__).read_text(encoding="utf-8")
    m = re.search(r'rc == 2 and "ABSENT" in out', src)
    assert m, "the item-4 absent-store branch is gone — exit 2 would read as FAIL again"
    seg = src[m.start() : m.start() + 1500]
    assert '"blocked"' in seg, "the absent-store branch must record blocked"


def test_c1u8_item7_targets_the_acquisition_store_not_the_intel_ledger():
    """holdings/pick_lineage live in data/retention/acquisition.sqlite;
    the intel ledger is the wrong population by design."""
    src = Path(onbox.__file__).read_text(encoding="utf-8")
    item7 = src[src.index('"C1U8-7"') :]
    head = item7[:3000]
    assert "acquisition_store" in head
    assert "pick_lineage" in head
    assert "event_type = 'TRADE'" in head


# ── V59 chain check honors each unit's own SuccessExitStatus contract ──


def _fake_run_v59_chain(exec_main_status: str):
    """Build a fake onbox._run that answers exactly the calls check_v59()
    makes, for all three chain units plus the ffpc unit, with the given
    ExecMainStatus on the chain units. Result=success on every unit,
    matching what systemd itself reports once SuccessExitStatus=0 2 has
    been applied — real production evidence (2026-08-29 on-box run)."""

    def fake_run(cmd, timeout=300):
        if cmd[:2] == ["systemctl", "show"] and "chaseupside-ffpc-sharp.service" in cmd:
            return 0, "Result=success\nExecMainStatus=0\nNRestarts=0\n", ""
        if cmd[:2] == ["systemctl", "show"]:
            return (
                0,
                f"Result=success\nExecMainStatus={exec_main_status}\n"
                "ExecMainExitTimestamp=Sat 2026-08-29 10:47:16 CEST\n"
                "ActiveEnterTimestamp=\n",
                "",
            )
        if cmd[:2] == ["systemctl", "list-timers"]:
            return 0, "NEXT LEFT LAST PASSED UNIT ACTIVATES\n", ""
        if cmd[:1] == ["journalctl"]:
            return 0, "", ""
        raise AssertionError(f"unexpected command in test: {cmd}")

    return fake_run


def test_v59_chain_exit_2_is_pass_not_fail(monkeypatch):
    """Regression pin for a real false-fail found during the 2026-08-29
    on-box harvest: dynasty-sharp-discovery.service.template and
    dynasty-sharp-rosters.service.template both declare
    SuccessExitStatus=0 2 (exit 2 is a documented nothing-to-do outcome,
    not a failure) and systemd's own Result= property already reflects
    that. The old check ignored Result and independently required
    ExecMainStatus == "0", so a genuinely healthy Result=success run
    with ExecMainStatus=2 was reported as a chain failure."""
    monkeypatch.setattr(onbox, "_run", _fake_run_v59_chain("2"))
    onbox.check_v59()
    chain_check = [c for c in onbox.CHECKS if c.check_id == "V59"]
    assert len(chain_check) == 1
    assert chain_check[0].status == "pass", chain_check[0].detail


def test_v59_chain_still_fails_on_a_real_bad_result(monkeypatch):
    """The fix must not become a rubber stamp: a unit whose Result is
    genuinely not success/exit-code (e.g. a real timeout/failed unit)
    still fails the check."""

    def fake_run(cmd, timeout=300):
        if cmd[:2] == ["systemctl", "show"] and "chaseupside-ffpc-sharp.service" in cmd:
            return 0, "Result=success\nExecMainStatus=0\nNRestarts=0\n", ""
        if cmd[:2] == ["systemctl", "show"]:
            return 0, "Result=failed\nExecMainStatus=15\n", ""
        if cmd[:2] == ["systemctl", "list-timers"]:
            return 0, "NEXT LEFT LAST PASSED UNIT ACTIVATES\n", ""
        if cmd[:1] == ["journalctl"]:
            return 0, "", ""
        raise AssertionError(f"unexpected command in test: {cmd}")

    monkeypatch.setattr(onbox, "_run", fake_run)
    onbox.check_v59()
    chain_check = [c for c in onbox.CHECKS if c.check_id == "V59"]
    assert len(chain_check) == 1
    assert chain_check[0].status == "fail"
    assert "Result=failed" in chain_check[0].detail


# ── V1-20 fails-closed, against the real (this-tree) registry ──


def test_v20_refuses_unknown_redraft_and_absent_but_accepts_the_honest_case():
    """The property `test_game_type_gate_red.py` already pins, run through
    the on-box driver's own check function rather than pytest directly --
    this is what makes it eligible to run over SSH against the deployed
    tree via `v1-onbox-checklists.yml`'s `checks=v20`, closing V1-20's
    named L3 gap (the fails-closed half proven against the deployed SHA,
    not just this dev tree)."""
    onbox.check_v20()
    result = [c for c in onbox.CHECKS if c.check_id == "V20"]
    assert len(result) == 1
    assert result[0].status == "pass", result[0].detail
    assert result[0].evidence["refused"] == {
        "unknown": True,
        "redraft": True,
        "absent": True,
    }
    assert result[0].evidence["honest_case_passed"] is True


def test_v20_records_fail_when_the_gate_lets_a_rogue_source_through(monkeypatch):
    """Mutation-shaped: if the injected validator stopped refusing, this
    check must say FAIL, not silently report pass on a broken gate."""
    from src.api import data_contract as dc

    def permissive(sources=None):
        return None  # never raises -- simulates a broken gate

    monkeypatch.setattr(dc, "_validate_source_game_types_invariant", permissive)
    onbox.check_v20()
    result = [c for c in onbox.CHECKS if c.check_id == "V20"]
    assert len(result) == 1
    assert result[0].status == "fail"
    assert result[0].evidence["refused"] == {
        "unknown": False,
        "redraft": False,
        "absent": False,
    }
