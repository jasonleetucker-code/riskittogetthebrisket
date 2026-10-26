"""Fast, synthetic checks for ``scripts/measure_trade_analyze_multi.py`` (Lane E
local latency / memory measurement of the N-team engine).

Everything here runs on ``multi_team_support``'s LABELLED synthetic league or on
hand-built result dicts: no archive, no TestClient, no network.  The script's
real-board and route runs are exercised by running the script itself.
"""

from __future__ import annotations

import importlib.util
import json
import random
import socket
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "measure_trade_analyze_multi", REPO / "scripts" / "measure_trade_analyze_multi.py"
)
m = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["measure_trade_analyze_multi"] = m
_spec.loader.exec_module(m)


# ── Statistics ─────────────────────────────────────────────────────────────


def test_percentiles_interpolate_and_empty_is_missing_never_zero():
    assert m.percentile([], 50) is None
    assert m.percentile([7.0], 95) == 7.0
    assert m.percentile([1, 2, 3, 4], 50) == 2.5
    assert m.percentile([0, 10], 95) == pytest.approx(9.5)
    empty = m.summarize([])
    assert empty["n"] == 0 and empty["p50"] is None and empty["p95"] is None
    got = m.summarize([10, 20, 30, 40, 50])
    assert (got["n"], got["p50"], got["max"]) == (5, 30.0, 50.0)
    with pytest.raises(ValueError):
        m.percentile([1], 101)


@pytest.mark.parametrize(
    ("caps", "total", "expected"),
    [
        ({1: 85, 3: 62}, 128, {1: 66, 3: 62}),
        ({1: 10, 2: 10, 3: 10}, 12, {1: 4, 2: 4, 3: 4}),
        ({1: 3, 2: 50}, 20, {1: 3, 2: 17}),
        ({1: 2, 2: 2}, 128, {1: 2, 2: 2}),
        ({1: 0, 2: 5}, 4, {1: 0, 2: 4}),
    ],
)
def test_water_fill_spreads_evenly_within_caps(caps, total, expected):
    assert m.water_fill(caps, total) == expected


# ── Local-only guards ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://chaseupside.com",
        "https://www.chaseupside.com/api/trade/analyze-multi",
        "https://api.chaseupside.com",
        "http://203.0.113.9:8000",
        "http://example.com",
        "ftp://127.0.0.1",
        "http://",
    ],
)
def test_production_and_non_loopback_targets_are_refused(url):
    with pytest.raises(m.TargetRefused):
        m.assert_local_target(url)


@pytest.mark.parametrize(
    "url",
    ["http://testserver", "http://127.0.0.1:8000", "http://localhost:3000", "http://[::1]:8000"],
)
def test_loopback_and_testclient_targets_are_accepted(url):
    assert m.assert_local_target(url).startswith("http://")


def test_the_deploy_host_secret_is_refused_by_name(monkeypatch):
    monkeypatch.setenv("DEPLOY_HOST", "box.internal.example")
    with pytest.raises(m.TargetRefused, match="production host"):
        m.assert_local_target("http://box.internal.example")


def test_main_refuses_a_production_base_url_before_doing_any_work(capsys):
    assert m.main(["--base-url", "https://chaseupside.com", "--synthetic"]) == m.EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().err


def test_main_rejects_bad_sample_counts(capsys):
    assert m.main(["--synthetic", "--cold-samples", "0"]) == m.EXIT_REFUSED
    assert m.main(["--synthetic", "--memory-limit-mb", "100", "--baseline-rss-mb", "200"]) == (
        m.EXIT_REFUSED
    )


def test_isolation_env_forces_temp_stores_over_anything_the_operator_exported(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("RISKIT_TRADE_DECISION_LOG_DIR", "/real/decision/store")
    monkeypatch.setenv("UPTIME_CHECK_ENABLED", "1")
    env = m.isolation_env(tmp_path)
    assert env["RISKIT_TRADE_DECISION_LOG_DIR"].startswith(str(tmp_path))
    assert env["UPTIME_CHECK_ENABLED"] == "0" and env["SCRAPE_SCHEDULER_ENABLED"] == "0"
    assert env["SLEEPER_LEAGUE_ID"] is None
    for key in m._ENV_TEMP_DIRS:
        assert env[key].startswith(str(tmp_path))


def test_network_guard_blocks_remote_connects_and_lookups_then_restores():
    original = socket.socket.connect
    original_lookup = socket.getaddrinfo
    with m.network_guard():
        with pytest.raises(OSError, match="network blocked"):
            socket.create_connection(("203.0.113.10", 9), timeout=0.05)
        with pytest.raises(OSError, match="network blocked"):
            socket.getaddrinfo("chaseupside.com", 443)
        assert socket.getaddrinfo("127.0.0.1", 80)  # loopback stays reachable
    assert socket.socket.connect is original
    assert socket.getaddrinfo is original_lookup


# ── Cell measurement is surface-agnostic ───────────────────────────────────


def _scenario(name="s", shape="representative", teams=(1, 2), legs=(("p:1", 1, 2),)):
    return m.Scenario(name, shape, len(teams), tuple(teams), tuple(legs))


def test_measure_cell_counts_samples_preps_cold_only_and_reports_memory():
    calls = {"cold": 0, "total": 0, "prep": 0}
    state = {"cold": False}

    def prep():
        calls["prep"] += 1
        state["cold"] = True

    def run(scn, keep_info):
        calls["total"] += 1
        cold, state["cold"] = state["cold"], False
        calls["cold"] += cold
        ballast = [0] * 50_000  # something for tracemalloc to see
        return m.Sample(
            total_ms=10.0 if cold else 2.0,
            parts={"analyze": 1.0},
            stages={"decision": 0.5},
            info={"len": len(ballast)} if keep_info else {},
        )

    scenarios = [_scenario("a"), _scenario("b")]
    cell = m.measure_cell(
        run, scenarios, cold_samples=3, warm_samples=4, memory_samples=2, prep=prep
    )
    assert cell["cold"]["totalMs"]["n"] == 3 and cell["cold"]["totalMs"]["p50"] == 10.0
    assert cell["warm"]["totalMs"]["n"] == 4 and cell["warm"]["totalMs"]["p50"] == 2.0
    assert cell["cold"]["partsP50Ms"] == {"analyze": 1.0}
    assert cell["warm"]["stagesP50Ms"] == {"decision": 0.5}
    assert calls["prep"] == 3 + 2  # cold timing samples + cold memory samples
    assert cell["memory"]["cold"]["n"] == 2 and cell["memory"]["cold"]["max"] > 0.3
    assert cell["scenarios"] == ["a", "b"]


def test_measure_cell_with_no_memory_samples_reports_missing_not_zero():
    cell = m.measure_cell(
        lambda scn, keep: m.Sample(total_ms=1.0),
        [_scenario()],
        cold_samples=1,
        warm_samples=1,
        memory_samples=0,
        prep=lambda: None,
    )
    assert cell["memory"]["cold"] == {"n": 0, "p50": None, "max": None}


def test_stage_categories_sum_the_per_team_stages():
    stages = [("resolve", 1.0), ("team:3:simulation", 5.0), ("team:4:simulation", 7.0)]
    stages += [("team:3:decision", 2.0), ("receipt", 0.5)]
    assert m.stage_categories(stages) == {
        "resolve": 1.0,
        "simulation": 12.0,
        "decision": 2.0,
        "receipt": 0.5,
    }


# ── Budgets ────────────────────────────────────────────────────────────────

LIMITS = {
    "privateDeadlineMs": 30000.0,
    "publicDeadlineMs": 5000.0,
    "privateMaxConcurrent": 2,
    "publicMaxConcurrent": 2,
    "admissionStatus": "PENDING_OWNER_CONFIRMATION",
    "responseFloorMs": None,
    "memoryAllowanceMb": 722.0,
    "memorySource": "test",
}


def _cell(surface, mode, n, shape, *, cold=100.0, warm=80.0, peak=5.0, requests=None, outcome=None):
    def totals(v):
        return {"totalMs": {"n": 5, "p50": v, "p95": v, "p99": v, "max": v}}

    base = {"snapshot_builds": 1, "posture_bundle_reads": 1, "scarcity_reads": 1}
    if mode == "market_fairness":
        base = {"snapshot_builds": 1}
    reqs = requests or {
        "cold": dict(base),
        "warm": {k: v for k, v in base.items() if k != "snapshot_builds"},
        "warmRepeat": {k: v for k, v in base.items() if k != "snapshot_builds"},
    }
    return {
        "surface": surface,
        "mode": mode,
        "teams": n,
        "shape": shape,
        "cold": totals(cold),
        "warm": totals(warm),
        "memory": {"cold": {"max": peak}, "warm": {"max": peak}},
        "structural": {
            "requests": reqs,
            "outcome": outcome
            or {
                "teamsAnalysed": n,
                "notComputedComparables": n if n >= 3 and mode != "market_fairness" else 0,
            },
        },
    }


def _results(**over):
    cells = [
        _cell("engine", "team_context", 3, "worst_case"),
        _cell("engine", "asset_only", 4, "worst_case"),
        _cell("engine", "market_fairness", 4, "worst_case", cold=150.0),
        _cell("route", "team_context", 4, "worst_case", cold=2000.0),
    ]
    out = {
        "engine": [c for c in cells if c["surface"] == "engine"],
        "route": [c for c in cells if c["surface"] == "route"],
    }
    out.update(over)
    return out


def _by_id(budgets):
    return {b["id"]: b for b in budgets}


def test_a_healthy_run_has_no_breach_and_names_what_it_did_not_exercise():
    got = _by_id(m.evaluate_budgets(_results(), LIMITS))
    assert [b["id"] for b in got.values() if b["status"] == "breach"] == []
    assert got["S1_one_snapshot_per_request"]["status"] == "pass"
    assert got["S4_market_fairness_skips_capacity_roster_utility"]["status"] == "pass"
    assert got["S5_comparables_not_computed_at_n_ge_3"]["status"] == "pass"
    # No utility call was counted, so the reuse budget is "not exercised",
    # never a silent pass.
    assert got["S6_before_roster_cache_reused_per_team"]["status"] == "not_exercised"
    # No response floor is set: nothing to breach, but the candidate is named.
    floor = got["L3_public_response_floor_covers_worst_case_cold_p99"]
    assert floor["status"] == "not_set" and floor["candidateFloorMs"] == 150
    assert got["M1_peak_alloc_times_concurrency_within_memory_allowance"]["observed"] == 10.0


def test_unmeasured_surfaces_are_not_measured_never_passed_or_breached():
    got = _by_id(m.evaluate_budgets({"engine": [], "route": []}, LIMITS))
    assert {b["status"] for b in got.values()} <= {"not_measured", "not_exercised", "not_set"}
    assert got["M1_peak_alloc_times_concurrency_within_memory_allowance"]["status"] == (
        "not_measured"
    )


@pytest.mark.parametrize(
    ("limits", "breached"),
    [
        ({"publicDeadlineMs": 100.0}, "L2_market_fairness_cold_p95_vs_public_caller_deadline"),
        ({"privateDeadlineMs": 1500.0}, "L1_private_route_cold_p95_vs_caller_deadline"),
        ({"responseFloorMs": 100}, "L3_public_response_floor_covers_worst_case_cold_p99"),
        ({"memoryAllowanceMb": 9.0}, "M1_peak_alloc_times_concurrency_within_memory_allowance"),
    ],
)
def test_numeric_budgets_breach_when_the_observation_exceeds_the_limit(limits, breached):
    got = _by_id(m.evaluate_budgets(_results(), {**LIMITS, **limits}))
    assert got[breached]["status"] == "breach"


def test_structural_budgets_breach_on_the_counted_violation():
    bad_snapshot = _cell(
        "route",
        "team_context",
        2,
        "representative",
        requests={"cold": {"snapshot_builds": 2, "posture_bundle_reads": 1, "scarcity_reads": 1}},
    )
    got = _by_id(m.evaluate_budgets(_results(route=[bad_snapshot]), LIMITS))
    assert got["S1_one_snapshot_per_request"]["status"] == "breach"

    two_bundles = _cell(
        "engine",
        "asset_only",
        3,
        "representative",
        requests={"cold": {"snapshot_builds": 1, "posture_bundle_reads": 2, "scarcity_reads": 1}},
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[two_bundles]), LIMITS))
    assert got["S2_one_posture_bundle_per_request"]["status"] == "breach"

    built_outside = _cell(
        "engine",
        "asset_only",
        3,
        "representative",
        requests={
            "cold": {
                "snapshot_builds": 1,
                "posture_bundle_reads": 1,
                "posture_build_if_missing_true": 1,
                "scarcity_reads": 1,
            }
        },
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[built_outside]), LIMITS))
    assert got["S2_one_posture_bundle_per_request"]["status"] == "breach"

    two_reads = _cell(
        "engine",
        "team_context",
        3,
        "representative",
        requests={"cold": {"snapshot_builds": 1, "scarcity_reads": 2}},
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[two_reads]), LIMITS))
    assert got["S3_one_scarcity_read_per_request"]["status"] == "breach"


@pytest.mark.parametrize(
    "counter",
    [
        "capacity_builds",
        "final_roster_simulations",
        "roster_utility_calls",
        "utility_evaluations",
        "before_roster_computed",
        "decision_receipts",
    ],
)
def test_market_fairness_that_does_capacity_roster_or_utility_work_breaches(counter):
    leaky = _cell(
        "engine",
        "market_fairness",
        3,
        "worst_case",
        requests={"cold": {"snapshot_builds": 1}, "warm": {counter: 1}, "warmRepeat": {}},
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[leaky]), LIMITS))
    assert got["S4_market_fairness_skips_capacity_roster_utility"]["status"] == "breach"


def test_comparables_computed_at_three_teams_breaches_and_a_missed_stamp_does_too():
    looked_up = _cell(
        "engine",
        "team_context",
        3,
        "worst_case",
        requests={"cold": {"snapshot_builds": 1, "comparables_lookups": 3}},
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[looked_up]), LIMITS))
    assert got["S5_comparables_not_computed_at_n_ge_3"]["status"] == "breach"

    unstamped = _cell(
        "engine",
        "asset_only",
        4,
        "worst_case",
        outcome={"teamsAnalysed": 4, "notComputedComparables": 2},
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[unstamped]), LIMITS))
    assert got["S5_comparables_not_computed_at_n_ge_3"]["status"] == "breach"


def test_before_roster_reuse_breaches_only_when_the_utility_actually_ran():
    ran = _cell(
        "engine",
        "team_context",
        3,
        "worst_case",
        requests={
            "cold": {"snapshot_builds": 1, "utility_evaluations": 3, "before_roster_computed": 3},
            "warm": {"utility_evaluations": 3, "before_roster_reused": 3},
            "warmRepeat": {"utility_evaluations": 3, "before_roster_computed": 3},
        },
    )
    got = _by_id(m.evaluate_budgets(_results(engine=[ran]), LIMITS))
    assert got["S6_before_roster_cache_reused_per_team"]["status"] == "breach"


# ── Scenarios and the end-to-end run on the synthetic league ───────────────


def test_worst_case_ledger_has_every_team_sending_and_receiving():
    from tests.trade import multi_team_support as mts

    snap = mts.synthetic_snapshot()
    view = m.clean_view(snap, set())
    for n in (2, 3, 4):
        teams, legs = m.worst_case_ledger(view, n, 128, random.Random(n))
        assert len(teams) == n
        assert {leg["from"] for leg in legs} == set(teams)
        assert {leg["to"] for leg in legs} == set(teams)
        assert all(leg["from"] != leg["to"] for leg in legs)
        assert len({leg["id"] for leg in legs}) == len(legs)


def test_clean_view_omits_excluded_assets_without_touching_the_snapshot():
    from tests.trade import multi_team_support as mts

    snap = mts.synthetic_snapshot()
    before = list(snap.teams_by_roster_id[1]["playerIds"])
    view = m.clean_view(snap, {"p:101"})
    assert "101" not in view.teams_by_roster_id[1]["playerIds"]
    assert snap.teams_by_roster_id[1]["playerIds"] == before


@pytest.fixture(scope="module")
def synthetic_report(tmp_path_factory):
    out = tmp_path_factory.mktemp("measure") / "report.json"
    # ``--roster-utility real`` keeps Team Context cheap here (no projection
    # basis on a synthetic league, so the Monte Carlo ends early); the labelled
    # Monte Carlo path is pinned separately below on a single ledger.
    code = m.main(
        [
            "--synthetic",
            "--quiet",
            "--roster-utility",
            "real",
            "--team-counts",
            "2,4",
            "--cold-samples",
            "1",
            "--warm-samples",
            "1",
            "--memory-samples",
            "0",
            "--ledgers",
            "1",
            "--output",
            str(out),
        ]
    )
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_synthetic_run_covers_every_mode_team_count_and_shape(synthetic_report):
    code, report = synthetic_report
    assert code == m.EXIT_OK and report["exitCode"] == 0 and report["breaches"] == []
    cells = report["results"]["engine"]
    assert len(cells) == 3 * 2 * 2  # modes x team counts x shapes
    assert {(c["mode"], c["teams"], c["shape"]) for c in cells} == {
        (mode, n, shape) for mode in m.MODES for n in (2, 4) for shape in m.SHAPES
    }
    assert report["results"]["route"] == []
    assert report["method"]["routeNote"]
    assert report["provenance"]["board"]["kind"] == "synthetic"
    for cell in cells:
        assert cell["cold"]["totalMs"]["n"] == 1 and cell["warm"]["totalMs"]["n"] == 1
        assert cell["allAssetsPriced"] is True
        # Memory was not sampled in this fast run: missing, never 0.
        assert cell["memory"]["cold"] == {"n": 0, "p50": None, "max": None}


def test_synthetic_run_pins_the_structural_budgets_on_the_real_engine(synthetic_report):
    _code, report = synthetic_report
    statuses = {b["id"]: b["status"] for b in report["budgets"]}
    for bid in (
        "S1_one_snapshot_per_request",
        "S2_one_posture_bundle_per_request",
        "S3_one_scarcity_read_per_request",
        "S4_market_fairness_skips_capacity_roster_utility",
        "S5_comparables_not_computed_at_n_ge_3",
    ):
        assert statuses[bid] == "pass", (bid, statuses[bid])
    # No projection basis here, so the utility never ran: named, not passed.
    assert statuses["S6_before_roster_cache_reused_per_team"] == "not_exercised"
    # The route was not measured, and the budgets say so.
    assert statuses["L1_private_route_cold_p95_vs_caller_deadline"] == "not_measured"
    # The stubs are named, so nobody mistakes them for production inputs.
    assert any("LABELLED" in s for s in report["method"]["stubs"])


def test_labelled_utility_runs_the_real_monte_carlo_and_reuses_the_before_roster():
    args = m.build_parser().parse_args(["--synthetic", "--roster-utility", "labelled"])
    patches = m.Patches()
    try:
        ctx = m.build_context(args)
        m.install_stubs(ctx, patches, roster_utility="labelled")
        plan, _screened = m.build_scenarios(ctx, seed=1, ledgers=1, team_counts=[2])
        run = m.make_engine_runner(ctx, "team_context")
        got = m.counted_pass(ctx, run, plan[("representative", 2)][0], m.Patches())
    finally:
        patches.undo()
    cold, repeat = got["requests"]["cold"], got["requests"]["warmRepeat"]
    assert cold["utility_evaluations"] == 2 and cold["before_roster_computed"] == 2
    assert repeat["before_roster_computed"] == 0 and repeat["before_roster_reused"] == 2
    assert got["outcome"]["rosterUtility"] == {"available": 2}


def test_the_report_states_what_spec_2_11_does_and_does_not_budget(synthetic_report):
    _code, report = synthetic_report
    assert any("no numeric latency or memory budget" in f for f in report["findings"])
    assert report["limits"]["admissionStatus"] == "PENDING_OWNER_CONFIRMATION"
    table = m.render_table(report)
    for mode in m.MODES:
        assert mode in table


def test_a_tight_deadline_turns_the_same_measurement_into_a_breach(synthetic_report):
    _code, report = synthetic_report
    budgets = m.evaluate_budgets(report["results"], {**report["limits"], "publicDeadlineMs": 1e-6})
    breached = [b["id"] for b in budgets if b["status"] == "breach"]
    assert any(b.startswith("L2_market_fairness") for b in breached)


# ── Exit codes ─────────────────────────────────────────────────────────────


def _canned(exit_code, breaches=()):
    return {"exitCode": exit_code, "breaches": list(breaches), "budgets": [], "results": {}}


def test_exit_code_follows_the_breach_list(monkeypatch, tmp_path, capsys):
    out = tmp_path / "r.json"
    monkeypatch.setattr(m, "run_measurement", lambda args, temp: _canned(1, ["L2_x"]))
    monkeypatch.setattr(m, "render_table", lambda report: "table")
    assert m.main(["--synthetic", "--quiet", "--output", str(out)]) == m.EXIT_BUDGET_BREACH
    assert json.loads(out.read_text(encoding="utf-8"))["breaches"] == ["L2_x"]
    monkeypatch.setattr(m, "run_measurement", lambda args, temp: _canned(0))
    assert m.main(["--synthetic", "--quiet", "--output", str(out)]) == m.EXIT_OK


def test_a_failed_measurement_is_exit_three_not_a_pass(monkeypatch, capsys):
    def boom(args, temp):
        raise m.MeasurementFailed("no board")

    monkeypatch.setattr(m, "run_measurement", boom)
    assert m.main(["--synthetic", "--quiet"]) == m.EXIT_MEASUREMENT_FAILED
    assert "no board" in capsys.readouterr().err
