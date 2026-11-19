"""The V1 trade-route readiness wait is bounded, measures warm-up and fails loudly (STAB-10).

``scripts/v1_heavy_route_readiness.py`` probes the War Room's two heavy
requests (the FULL ``/api/data`` contract, a Team Context analyze) until both
answer warm.  Driven here with a fake client and a fake clock: no network.
"""

from __future__ import annotations

import io
import re
import sys
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import v1_heavy_route_readiness as ready  # noqa: E402

WORKFLOW = ROOT / ".github" / "workflows" / "v1-authenticated-verification.yml"
STEP_NAME = "Wait for warm trade routes (bounded, authenticated)"
#: Headroom the step keeps beyond the readiness wait's own worst case
#: (interpreter start, the report write, runner step overhead).
STEP_MARGIN_SECONDS = 60


def _contract() -> dict:
    teams = [
        {"roster_id": rid, "ownerId": f"o{rid}", "playerIds": [str(100 + rid)]} for rid in (1, 2, 3)
    ]
    id_to_player = {str(100 + rid): f"Player {rid}" for rid in (1, 2, 3)}
    rows = [{"displayName": f"Player {rid}", "rankDerivedValue": 5000 - rid} for rid in (1, 2, 3)]
    return {"sleeper": {"teams": teams, "idToPlayer": id_to_player}, "playersArray": rows}


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeClient:
    """Each attempt costs the scripted (data, analyze) seconds on the clock."""

    def __init__(self, clock: FakeClock, script: list[tuple[float, float, int]]) -> None:
        self.clock = clock
        self.script = list(script)
        self.calls: list[tuple[str, dict | None]] = []
        self._current: tuple[float, float, int] | None = None

    def request(self, path: str, body: dict | None = None):
        self.calls.append((path, body))
        if body is None:
            self._current = self.script.pop(0) if self.script else self._current
            data_s, _, status = self._current
            self.clock.now += data_s
            return (200, _contract()) if status == 200 else (status, None)
        _, analyze_s, _ = self._current
        self.clock.now += analyze_s
        return 200, {"analysisTiming": {"totalMs": analyze_s * 1000}}


def _wait(script, **kw):
    clock = FakeClock()
    client = FakeClient(clock, script)
    report = ready.wait_until_ready(
        client,
        "dynasty_main",
        budget_seconds=kw.get("budget", 240),
        ready_seconds=kw.get("ready_s", 30),
        interval_seconds=15,
        clock=clock,
        sleep=clock.sleep,
    )
    return report, client


def test_probes_the_war_rooms_own_heavy_requests():
    report, client = _wait([(2, 3, 200)])
    assert report["ready"] and len(report["attempts"]) == 1
    (data_path, _), (analyze_path, body) = client.calls
    assert data_path == "/api/data?leagueKey=dynasty_main", "the FULL contract, not view=app"
    assert analyze_path == "/api/trade/analyze"
    assert body["useTeamContext"] is True
    assert report["attempts"][0]["analyzeServerMs"] == 3000.0
    assert ready.annotations(report) == [
        "trade routes ready after 5.0s (1 probe(s); first probe: /api/data 2.0s (HTTP 200), "
        "analyze 3.0s (HTTP 200))"
    ]


def test_a_cold_start_is_waited_out_and_reported_as_a_warning():
    report, _ = _wait([(70, 50, 200), (40, 5, 200), (3, 4, 200)])
    assert report["ready"]
    assert len(report["attempts"]) == 3
    assert report["warmupSeconds"] == 70 + 50 + 15 + 40 + 5 + 15 + 3 + 4
    lines = ready.annotations(report)
    assert any(
        line.startswith("::warning title=Cold trade routes after restart::") for line in lines
    )
    assert "first probe: /api/data 70.0s" in lines[-1]


def test_not_ready_within_the_budget_is_an_error_and_bounded():
    report, client = _wait([(60, 60, 200)] * 50, budget=240)
    assert not report["ready"] and report["warmupSeconds"] is None
    # Each probe costs 120 s + 15 s sleep: the loop stops once the budget is spent.
    assert len(report["attempts"]) == 2
    (line,) = ready.annotations(report)
    assert line.startswith("::error title=Trade routes not ready::")


def test_a_failing_contract_is_not_ready_and_never_reaches_analyze():
    report, client = _wait([(1, 0, 503)] * 50, budget=60)
    assert not report["ready"]
    assert all(a["result"] == "data_not_ok" for a in report["attempts"])
    assert all(path.startswith("/api/data") for path, _ in client.calls)


def test_one_slow_leg_is_not_ready():
    report, _ = _wait([(2, 31, 200), (2, 3, 200)])
    assert report["ready"] and len(report["attempts"]) == 2


def test_cli_refuses_an_unreadable_cookie(tmp_path):
    assert (
        ready.main(["--origin", "https://x.invalid", "--cookie-file", str(tmp_path / "nope")]) == 1
    )


def test_workflow_runs_it_and_the_verdict_step_fails_on_it():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["v1-authenticated"]["steps"]
    names = [s.get("name") for s in steps]
    step = steps[names.index("Wait for warm trade routes (bounded, authenticated)")]
    assert step["id"] == "heavy_ready"
    assert "continue-on-error" not in step
    assert "python3 scripts/v1_heavy_route_readiness.py" in step["run"]
    assert 'echo "heavy_ready_exit=$rc" >> "$GITHUB_OUTPUT"' in step["run"]
    assert step["timeout-minutes"] <= 8
    # After login and the public warm wait, before every suite.
    assert names.index("Log in through the real auth path") < names.index(step["name"])
    assert names.index("Wait for a warm backend (bounded, public endpoints)") < names.index(
        step["name"]
    )
    for suite in (
        "API verification suite",
        "Browser verification suite (prod-auth Playwright specs)",
    ):
        assert names.index(step["name"]) < names.index(suite)
    verdict = steps[names.index("Fail the job on API/lane4/browser verdicts")]
    assert verdict["env"]["HEAVY_READY_EXIT"] == "${{ steps.heavy_ready.outputs.heavy_ready_exit }}"
    assert "title=Trade routes not ready" in verdict["run"]


# ── the step cap holds the wait's worst case ─────────────────────────


def _step() -> dict:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["v1-authenticated"]["steps"]
    return next(s for s in steps if s.get("name") == STEP_NAME)


def _step_args(step: dict) -> list[str]:
    """The bounds the workflow actually passes the script."""
    args: list[str] = []
    for flag in ("--budget-seconds", "--ready-seconds", "--interval-seconds", "--request-timeout"):
        match = re.search(rf"{flag} (\S+)", step["run"])
        assert match, f"the step must pass {flag} explicitly"
        args += [flag, match.group(1)]
    return args


class _Response:
    status = 200

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _adversarial_run(monkeypatch, tmp_path, args: list[str]) -> float:
    """Run ``main`` against the slowest server the step can meet, on a fake
    clock, through the REAL HTTP client (only ``urlopen`` and ``sleep`` are
    faked); return the simulated wall seconds.

    Until the budget is spent every request is refused at once (HTTP 503), so
    the loop keeps probing and its last probe STARTS at the very end of the
    budget.  From then on the contract answers 200 only after the full
    request timeout and every analyze attempt times out -- the longest a
    probe can run."""
    clock = FakeClock()
    budget = float(args[args.index("--budget-seconds") + 1])

    def urlopen(req, timeout):
        if clock.now < budget:
            raise urllib.error.HTTPError(req.full_url, 503, "busy", {}, io.BytesIO(b"{}"))
        clock.now += timeout
        if "/api/data" in req.full_url:
            return _Response(b"{}")
        raise TimeoutError("timed out")

    monkeypatch.setattr(ready.smoke.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ready.smoke.time, "sleep", clock.sleep)
    monkeypatch.setattr(ready.smoke, "build_trades", lambda contract, league: {"two": {}})
    real_wait = ready.wait_until_ready
    monkeypatch.setattr(
        ready,
        "wait_until_ready",
        lambda client, league, **kw: real_wait(
            client, league, clock=clock, sleep=clock.sleep, **kw
        ),
    )
    cookie = tmp_path / "cookie"
    cookie.write_text("c", encoding="utf-8")
    code = ready.main(["--origin", "https://x.invalid", "--cookie-file", str(cookie), *args])
    assert code == ready.EXIT_NOT_READY
    return clock.now


def test_the_worst_case_wait_fits_inside_the_step_cap(monkeypatch, tmp_path):
    # A step killed by its own timeout-minutes skips every later suite and
    # loses their evidence; the wait must end on its own, with margin.
    step = _step()
    elapsed = _adversarial_run(monkeypatch, tmp_path, _step_args(step))
    cap = step["timeout-minutes"] * 60
    assert (
        elapsed + STEP_MARGIN_SECONDS <= cap
    ), f"worst case {elapsed:g}s + {STEP_MARGIN_SECONDS}s margin exceeds the {cap}s step cap"


def test_the_worst_case_formula_is_exact_and_fits_the_cap(monkeypatch, tmp_path):
    step = _step()
    args = _step_args(step)
    bounds = dict(zip(args[::2], (float(v) for v in args[1::2])))
    formula = ready.worst_case_seconds(bounds["--budget-seconds"], bounds["--request-timeout"])
    assert _adversarial_run(monkeypatch, tmp_path, args) == formula
    assert formula + STEP_MARGIN_SECONDS <= step["timeout-minutes"] * 60
    # A request slower than the ready bound must still be MEASURED, not cut off.
    assert bounds["--request-timeout"] > bounds["--ready-seconds"]


@pytest.mark.parametrize("attempts", [None, 1, 2])
def test_a_requests_worst_case_matches_the_real_client(monkeypatch, attempts):
    clock = FakeClock()
    calls: list[float] = []

    def urlopen(req, timeout):
        calls.append(timeout)
        clock.now += timeout
        raise TimeoutError("timed out")

    monkeypatch.setattr(ready.smoke.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(ready.smoke.time, "sleep", clock.sleep)
    extra = {} if attempts is None else {"attempts": attempts}
    client = ready.smoke.Client("https://x.invalid", "c", 50.0, lambda _m: None, **extra)
    assert client.request("/api/data") == (None, None)
    # The trade smoke keeps its one retry; the readiness probe passes 1.
    expected = 2 if attempts is None else attempts
    assert len(calls) == expected
    assert clock.now == ready.request_worst_case_seconds(50.0, expected)
