"""Production verification output is PUBLIC — only an allowlisted summary may reach it.

This repository is public, so every line ``v1-authenticated-verification.yml``
logs and every file it uploads is readable by anyone.  Before this guard the
API suite printed its full report (``print(json.dumps(report))``) and the
Lane 4 remote run was ``tee``'d into the log and the artifact, carrying, among
other things: a Sleeper ``ownerId`` and two player names in V27-3's request
``payload``; raw 500-character response-body excerpts; Sharp asset ids with
their manager-quality values (C1-C3 ``offenders``); and the private FAAB
recommendation (C9 ``standard`` / ``conservative`` / ``aggressive`` / ``max`` /
``clearing``).

Pinned here, against HOSTILE production responses fed through each producer's
real CLI entry point:

* stdout and the uploaded file carry the public schema of
  ``scripts/public_verification_report.py`` and nothing else — no ``detail``,
  only allowlisted evidence keys, each of its declared kind;
* no planted private token survives (cookie, owner id, player / team names,
  asset ids, bid amounts, response bodies, exception text);
* the gate stays meaningful: every check's id and status are published and the
  exit code is unchanged;
* the workflow uploads only allowlisted artifacts, tees nothing it uploads, and
  invokes both producers in their public mode.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import sys
from pathlib import Path

import pytest

import scripts.public_verification_report as pvr
import scripts.verify_v1_authenticated as auth

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"

_SPEC = importlib.util.spec_from_file_location(
    "verify_lane4_production_public", REPO_ROOT / "scripts" / "verify_lane4_production.py"
)
lane4 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = lane4
_SPEC.loader.exec_module(lane4)

_TOP_KEYS = {
    "schema",
    "sanitized",
    "producer",
    "generatedAt",
    "origin",
    "league",
    "counts",
    "exitCode",
    "checks",
    "withheld",
}
_CHECK_KEYS = {"id", "row", "title", "status", "denominator", "evidence", "evidenceWithheld"}


def _assert_public_schema(report: dict, allow: dict, extra_top: set[str] = frozenset()) -> None:
    assert set(report) == _TOP_KEYS | set(extra_top), set(report) ^ (_TOP_KEYS | set(extra_top))
    assert report["schema"] == pvr.SCHEMA and report["sanitized"] is True
    assert report["checks"], "a public report with no checks proves nothing"
    for c in report["checks"]:
        assert set(c) <= _CHECK_KEYS, f"{c['id']}: unexpected keys {set(c) - _CHECK_KEYS}"
        assert "detail" not in c
        assert c["status"] in pvr.STATUS_VOCABULARY, c
        if c["id"].endswith(":crash"):
            permitted = {"errorType"}
        else:
            permitted = set(allow.get(c["id"], {}))
        assert set(c["evidence"]) <= permitted, f"{c['id']}: {set(c['evidence']) - permitted}"
        for key, value in c["evidence"].items():
            _assert_kind(value, f"{c['id']}.{key}")


def _assert_kind(value, where: str) -> None:
    """Every published leaf is a bool, a finite number, null or a short code."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", k), where
            _assert_kind(v, where)
    elif isinstance(value, list):
        for v in value:
            _assert_kind(v, where)
    elif isinstance(value, str):
        assert re.fullmatch(r"[A-Za-z0-9_.:,+\-]{1,140}", value), f"{where}: {value!r}"
    else:
        assert value is None or isinstance(value, (bool, int, float)), where
        if isinstance(value, float):
            assert math.isfinite(value), where


def _assert_no_leak(blob: str, tokens: list[str]) -> None:
    leaked = [t for t in tokens if t in blob]
    assert leaked == [], f"private tokens reached public output: {leaked}"


# ── the sanitizer itself ───────────────────────────────────────────────


class TestSanitizerKinds:
    def test_wrong_kind_is_dropped_never_coerced(self):
        out = pvr.public_check(
            "X1",
            "V1-1",
            "a title",
            "pass",
            {"n": "12", "b": 1, "f": float("nan"), "ok": True, "missing": None, "e": "Has Caps"},
            {
                "n": pvr.COUNT,
                "b": pvr.BOOL,
                "f": pvr.NUMBER,
                "ok": pvr.BOOL,
                "missing": pvr.COUNT,
                "e": pvr.ENUM,
            },
        )
        # MISSING IS NEVER ZERO: an explicit null is published as null.
        assert out["evidence"] == {"ok": True, "missing": None}
        assert out["evidenceWithheld"] == 4

    def test_bool_is_not_a_count_and_negative_is_not_a_count(self):
        out = pvr.public_check(
            "X1", "-", "t", "pass", {"a": True, "b": -1}, {"a": pvr.COUNT, "b": pvr.COUNT}
        )
        assert out["evidence"] == {} and out["evidenceWithheld"] == 2

    def test_unlisted_key_and_detail_are_never_published(self):
        out = pvr.public_check("X1", "-", "t", "fail", {"payload": {"team": "1"}}, {})
        assert out["evidence"] == {} and out["evidenceWithheld"] == 1
        assert "detail" not in out

    def test_maps_must_stay_inside_their_fixed_key_set(self):
        kind = pvr.count_map(("a", "b"))
        assert pvr.clean_value(kind, {"a": 1, "b": 2}) == {"a": 1, "b": 2}
        out = pvr.public_check(
            "X1", "-", "t", "pass", {"m": {"a": 1, "Player Name": 2}}, {"m": kind}
        )
        assert out["evidence"] == {}
        out = pvr.public_check("X1", "-", "t", "pass", {"m": {"a": {"nested": 1}}}, {"m": kind})
        assert out["evidence"] == {}

    def test_secret_and_session_header_are_dropped_even_when_the_kind_matches(self):
        secret = "lowercasecookie_abcdef"
        out = pvr.public_check(
            "X1",
            "-",
            "jason_session=abc in a title",
            "pass",
            {"r": secret, "s": "fine_code"},
            {"r": pvr.REASON, "s": pvr.REASON},
            secrets=(secret,),
        )
        assert out["evidence"] == {"s": "fine_code"}
        assert "title" not in out

    def test_unknown_status_and_ids_are_marked_not_echoed(self):
        out = pvr.public_check("Bad Id With Spaces", "x y", "t", "Player Name", {}, {})
        assert out["id"] == "invalid_id" and out["status"] == "invalid_status"
        assert out["row"] is None

    def test_report_rejects_hostile_origin_and_league(self):
        rep = pvr.public_report(
            producer="p",
            generated_at="2026-10-08T00:00:00Z",
            origin="https://x.test/?session=abc",
            league="1234567890 raw sleeper id",
            checks=[],
            exit_code=3,
        )
        assert rep["origin"] is None and rep["league"] is None


# ── verify_v1_authenticated.py, end to end through main() ──────────────

_V1_COOKIE = "V1COOKIE_9f8e7d6c5b4a3210"
_OWNER_ID = "998877665544332211"
_V1_TOKENS = [
    _V1_COOKIE,
    _OWNER_ID,
    "Secret Bench Guy",
    "Hostile Q. Player",
    "SECRET_BODY_TOKEN",
    "PRIVATE_DETAIL",
    "SECRET_EXC_TEXT",
    "123.456",
    "/home/dynasty/secret",
]


def _v1_contract() -> dict:
    rows = [
        {
            "displayName": f"Hostile Q. Player {i}",
            "rankDerivedValue": 4000 + i,
            "assetClass": "offense",
            "canonicalConsensusRank": i + 1,
            **({"confidenceBasis": "families"} if i % 2 else {}),
        }
        for i in range(6)
    ]
    teams = [
        {"ownerId": _OWNER_ID, "optimalLineup": {"bench": ["Secret Bench Guy A"]}},
        {"ownerId": "112233445566778899", "optimalLineup": {"bench": ["Secret Bench Guy B"]}},
    ]
    return {
        "playersArray": rows,
        "sleeper": {"teams": teams},
        "privateSourceAvailability": {
            "signalsSf": {"state": "present", "votes": True, "path": "/home/dynasty/secret"}
        },
    }


def _v1_request(self, path, *, method="GET", body=None):
    if path == "/api/auth/status":
        return 200, {
            "authenticated": True,
            "authMethod": "guest_pass",
            "username": _V1_COOKIE,
            "isAdmin": False,
            "features": {"consensusEdge": {"available": True}},
        }
    if path.startswith("/api/data"):
        return 200, _v1_contract()
    if path == "/api/sharp/roster-percentage":
        return 500, "Traceback (most recent call last): SECRET_BODY_TOKEN"
    if path == "/api/public/league/faabAnalytics":
        return 200, {"data": {"leagueMedianWinningBid": 7.77}}
    if path == "/api/consensus-edge/players":
        return 200, {}
    if path.startswith("/api/league-comparison"):
        return 503, {"error": "sleeper_unreachable", "detail": "PRIVATE_DETAIL"}
    if path.startswith("/api/terminal"):
        raise ValueError("boom SECRET_EXC_TEXT " + _OWNER_ID)
    if path == "/api/trade/simulate":
        return 200, {
            "teamImpact": {"starterDelta": 123.456},
            "finalRosterSimulation": {"available": True, "rows": ["Secret Bench Guy A"]},
        }
    raise AssertionError(f"unexpected path {path}")


def _run_v1(tmp_path, monkeypatch, capsys) -> tuple[int, str, dict]:
    auth.CHECKS.clear()
    cookie_file = tmp_path / "cookie"
    cookie_file.write_text(_V1_COOKIE, encoding="utf-8")
    report_file = tmp_path / "v1-auth-report.json"
    monkeypatch.setattr(auth.Client, "request", _v1_request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "verify_v1_authenticated.py",
            "--origin",
            "https://chaseupside.com",
            "--league",
            "dynasty_main",
            "--cookie-file",
            str(cookie_file),
            "--report",
            str(report_file),
            "--expected-duration-seconds",
            "7200",
            "--observed-expires-epoch",
            str(__import__("time").time() + 7200),
            "--free-agent-out",
            str(tmp_path / "free_agent.txt"),
        ],
    )
    try:
        code = auth.main()
    finally:
        checks = list(auth.CHECKS)
        auth.CHECKS.clear()
    out = capsys.readouterr().out
    file_text = report_file.read_text(encoding="utf-8")
    # Non-vacuity: the producer really saw the private data it must withhold.
    private = json.dumps([c.__dict__ for c in checks], default=str)
    assert _OWNER_ID in private and "Secret Bench Guy" in private
    return code, out, json.loads(file_text) | {"_raw": file_text}


class TestV1PublicOutput:
    def test_stdout_and_artifact_carry_no_private_token(self, tmp_path, monkeypatch, capsys):
        code, out, report = _run_v1(tmp_path, monkeypatch, capsys)
        _assert_no_leak(out, _V1_TOKENS)
        _assert_no_leak(report.pop("_raw"), _V1_TOKENS)

    def test_artifact_matches_the_public_schema(self, tmp_path, monkeypatch, capsys):
        code, _, report = _run_v1(tmp_path, monkeypatch, capsys)
        report.pop("_raw")
        _assert_public_schema(report, auth.PUBLIC_EVIDENCE)

    def test_the_gate_stays_visible(self, tmp_path, monkeypatch, capsys):
        code, out, report = _run_v1(tmp_path, monkeypatch, capsys)
        assert report["exitCode"] == code == 1  # the V11-8 crash is an error
        by_id = {c["id"]: c for c in report["checks"]}
        assert by_id["V61A"]["status"] == "fail"
        assert by_id["V49-3"]["status"] == "unmeasurable"
        assert by_id["V11-8:crash"]["status"] == "error"
        assert by_id["V11-8:crash"]["evidence"] == {"errorType": "ValueError"}
        assert by_id["V27-3"]["evidence"] == {"starterDeltaNeutral": False}
        assert by_id["AUTH0"]["evidence"]["authMethod"] == "guest_pass"
        for c in report["checks"]:
            assert c["id"] in out and c["status"] in out


# ── verify_lane4_production.py --mode remote --public-report ───────────

_L4_COOKIE_VALUE = "lane4cookie_xyz987654abc"
_L4_TOKENS = [
    _L4_COOKIE_VALUE,
    "SECRET_ASSET_ID_1",
    "0.987654",
    "SECRET_LEAGUE",
    "SECRET_FACTOR",
    "31.4159",
    "27.1828",
    "41.4142",
    "99.0001",
    "12.3456",
    "SECRET_TS",
    "SECRET_ROUTE",
    "SECRET_500_BODY",
    "Hostile Player",
]


def _l4_http(faab_status: int):
    def fake(url, *, cookie, body=None, timeout=30.0):
        if url.endswith("/api/status"):
            return 200, {
                "contract": {"version": "2026-03-10.v2", "health": {"ok": True}},
                "data_runtime": {
                    "last_data_refresh_at": "2026-10-08T10:00:00+00:00",
                    "last_payload_loaded_at": "not a timestamp SECRET_TS",
                },
            }
        if "/api/sharp/market" in url:
            return 200, {
                "assets": [
                    {
                        "assetId": "SECRET_ASSET_ID_1",
                        "personConsensus": {
                            "personVotes": 0,
                            "personManagerQuality": 0.987654,
                            "weightedPersonVolume": 0,
                            "networkConcentration": 0.55,
                        },
                    }
                ]
            }
        if url.endswith("/api/waiver/faab-recommend"):
            if faab_status != 200:
                return faab_status, {"raw": "SECRET_500_BODY"}
            return 200, {
                "crowdMarket": {
                    "state": "fresh",
                    "refusalReason": _L4_COOKIE_VALUE,
                    "targetFormatUnknown": [],
                    "rowsTotal": 10,
                    "rowsUsed": 5,
                    "playerHasEvidence": True,
                    "pricesIdp": False,
                    "excludedCounts": {"SECRET_LEAGUE": 3},
                },
                "factors": [{"label": "Cross-league market", "detail": "SECRET_FACTOR"}],
                "standard": 31.4159,
                "conservative": 27.1828,
                "aggressive": 41.4142,
                "max": 99.0001,
                "contention": {"clearing": 12.3456},
            }
        raise AssertionError(url)

    return fake


def _routes_stub(report):
    c = report.add(lane4.Check("R0", "-", "every route this package names is registered"))
    c.status = lane4.PASS
    c.denominator = 5
    c.detail = "SECRET_ROUTE"
    c.evidence = {"routesDiscovered": 5, "missing": ["SECRET_ROUTE"]}


def _run_lane4(tmp_path, monkeypatch, capsys, faab_status=200):
    monkeypatch.setenv("RISKIT_SESSION_COOKIE", f"jason_session={_L4_COOKIE_VALUE}")
    monkeypatch.setattr(lane4, "_http", _l4_http(faab_status))
    monkeypatch.setattr(lane4, "check_required_routes_exist", _routes_stub)
    out_file = tmp_path / "lane4-remote.json"
    code = lane4.main(
        [
            "--mode",
            "remote",
            "--origin",
            "https://chaseupside.com",
            "--league",
            "dynasty_main",
            "--add-player",
            "Hostile Player",
            "--public-report",
            str(out_file),
        ]
    )
    captured = capsys.readouterr()
    text = out_file.read_text(encoding="utf-8")
    return code, captured.out + captured.err, text


class TestLane4PublicOutput:
    @pytest.mark.parametrize("faab_status", [200, 500])
    def test_public_mode_publishes_no_private_token(
        self, tmp_path, monkeypatch, capsys, faab_status
    ):
        code, logged, text = _run_lane4(tmp_path, monkeypatch, capsys, faab_status)
        _assert_no_leak(logged, _L4_TOKENS)
        _assert_no_leak(text, _L4_TOKENS)

    def test_public_report_matches_the_schema(self, tmp_path, monkeypatch, capsys):
        code, _, text = _run_lane4(tmp_path, monkeypatch, capsys)
        report = json.loads(text)
        _assert_public_schema(
            report, lane4.PUBLIC_EVIDENCE, {"mode", "deployed", "applicableChecks"}
        )
        assert set(report["deployed"]) <= set(lane4.PUBLIC_DEPLOYED)
        assert report["deployed"]["contractVersion"] == "2026-03-10.v2"
        assert "lastPayloadLoadedAt" not in report["deployed"]
        assert report["exitCode"] == code

    def test_the_gate_stays_visible(self, tmp_path, monkeypatch, capsys):
        code, logged, text = _run_lane4(tmp_path, monkeypatch, capsys)
        report = json.loads(text)
        by_id = {c["id"]: c for c in report["checks"]}
        # The zero-voter row published 0.987654 instead of null: a real FAIL,
        # and its count survives while the offending asset id does not.
        assert by_id["C1"]["status"] == "fail"
        assert by_id["C1"]["evidence"]["offenderCount"] == 1
        assert code == 2 and report["exitCode"] == 2
        assert by_id["C9"]["evidence"]["crowdFactorRows"] == 1
        for check_id in ("R0", "C1", "C2", "C3", "C8", "C9"):
            assert check_id in logged

    def test_without_public_mode_the_full_report_is_unchanged(self, tmp_path, monkeypatch, capsys):
        """Non-vacuity + no regression for the on-box/private use: the full
        report still carries what the public one withholds."""
        monkeypatch.setattr(lane4, "_http", _l4_http(200))
        monkeypatch.setattr(lane4, "check_required_routes_exist", _routes_stub)
        lane4.main(["--mode", "remote", "--origin", "https://chaseupside.com", "--add-player", "X"])
        full = capsys.readouterr().out
        assert "SECRET_ASSET_ID_1" in full and "31.4159" in full


# ── the workflow publishes only allowlisted outputs ────────────────────

#: Every file the V1 workflow may upload.  security-acceptance.json is PR
#: #1724's int/bool-only summary (``build_security_summary``), pinned by its
#: own tests; listed so that PR lands without loosening this guard.
_ALLOWED_UPLOADS = {
    "production-route-baselines.json",
    "v1-auth-report.json",
    "lane4-remote.json",
    "security-acceptance.json",
    "tests/e2e/prod-auth-results.json",
}


def _upload_paths(workflow: str) -> list[str]:
    out: list[str] = []
    for block in re.split(r"\n\s*- name:", workflow):
        if "actions/upload-artifact" not in block:
            continue
        m = re.search(r"\n\s*path:\s*(\|?)\s*\n?(.*?)(\n\s*[a-z-]+:|\Z)", block, re.S)
        assert m, "an upload step with no parseable path"
        out += [
            ln.strip()
            for ln in m.group(2).splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    return out


def _run_code(workflow: str) -> str:
    """Workflow text minus comment lines (prose may name what code must not do)."""
    return "\n".join(ln for ln in workflow.splitlines() if not ln.lstrip().startswith("#"))


class TestWorkflowPublishesOnlyAllowlistedOutputs:
    wf = WORKFLOW.read_text(encoding="utf-8")

    def test_uploads_are_allowlisted(self):
        paths = _upload_paths(self.wf)
        assert paths, "parser found no upload paths"
        assert set(paths) <= _ALLOWED_UPLOADS, set(paths) - _ALLOWED_UPLOADS
        assert "lane4-remote.txt" not in paths

    def test_nothing_uploaded_is_teed_or_catted_into_the_log(self):
        code = _run_code(self.wf)
        teed = re.findall(r"\btee\s+(?:-a\s+)?(\S+)", code)
        # The browser suite's stdout is the sanitized reporter's own lines; the
        # file is not uploaded.
        assert set(teed) <= {"prod-auth-browser.txt"}, teed
        for name in _ALLOWED_UPLOADS | {"lane4-remote.txt"}:
            assert not re.search(rf"\bcat\b[^\n]*{re.escape(name)}", code), name

    def test_both_producers_run_in_public_mode(self):
        code = _run_code(self.wf)
        lane4_call = re.search(r"verify_lane4_production\.py(.*?)\|\|\s*rc=", code, re.S)
        assert lane4_call, "lane4 invocation not found"
        assert "--public-report lane4-remote.json" in lane4_call.group(1)
        assert "--out" not in lane4_call.group(1)
        v1_call = re.search(r"verify_v1_authenticated\.py \\\n(.*?)\|\|\s*rc=", code, re.S)
        assert v1_call and "--report v1-auth-report.json" in v1_call.group(1)

    def test_free_agent_name_is_not_logged(self):
        code = _run_code(self.wf)
        assert not re.search(r'echo[^\n]*\$\(cat "\$RUNNER_TEMP/free_agent\.txt"\)', code)

    def test_guard_catches_the_legacy_shape(self):
        """Non-vacuity: the pre-fix workflow fails these checks."""
        legacy = (
            '            "${ADD_PLAYER_ARGS[@]}" 2>&1 | tee lane4-remote.txt || rc=$?\n'
            "      - name: Upload the reports\n        uses: actions/upload-artifact@v7\n"
            "        with:\n          path: |\n            lane4-remote.txt\n"
            "          retention-days: 30\n"
        )
        assert set(_upload_paths(legacy)) - _ALLOWED_UPLOADS == {"lane4-remote.txt"}
        assert re.findall(r"\btee\s+(?:-a\s+)?(\S+)", legacy) == ["lane4-remote.txt"]
