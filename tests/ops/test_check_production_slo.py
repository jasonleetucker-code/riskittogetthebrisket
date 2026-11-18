"""Rules of ``scripts/check_production_slo.py`` (audit remediation 2026-11-18).

Synthetic delayed deploy -> alert; synthetic stale board -> alert; healthy ->
no alert; anything unmeasurable -> UNKNOWN, never healthy.  No network, no git
history: every rule is a pure function over a ``Snapshot``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_production_slo", _REPO / "scripts/check_production_slo.py"
)
slo = importlib.util.module_from_spec(_spec)
sys.modules["check_production_slo"] = slo
_spec.loader.exec_module(slo)

CFG = json.loads((_REPO / "config/ops/production_slo.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def run(conclusion: str, hours_ago: float) -> dict:
    return {"conclusion": conclusion, "updated_at": ago(hours_ago).isoformat()}


def healthy_slo(**over) -> dict:
    base = {
        "state": "measured",
        "top200StaleShare": 0.0,
        "pricedWithheldShare": 0.0,
        "boardAgeHours": 4.0,
        "privateSourcesProvisioned": 1,
        "privateSourcesStale": 0,
        "privateSourcesUnknown": 0,
    }
    base.update(over)
    return base


def snap(**kw) -> slo.Snapshot:
    defaults = dict(
        now=NOW,
        undeployed_relevant=[],
        deploy_runs=[run("success", 1)],
        refresh_runs=[run("success", 3)],
        freshness_slo=healthy_slo(),
    )
    defaults.update(kw)
    return slo.Snapshot(**defaults)


def by_rule(results):
    return {r.rule: r for r in results}


def test_healthy_snapshot_raises_nothing():
    results = slo.evaluate(snap(), CFG)
    assert [r.status for r in results] == [slo.OK] * len(results)
    assert slo.exit_code(results) == 0


# -- code freshness -------------------------------------------------------------
def test_delayed_deploy_breaches_and_names_value_and_threshold():
    limit = CFG["codeFreshness"]["deployLagMaxHours"]
    r = slo.rule_deploy_lag(snap(undeployed_relevant=[ago(limit + 3), ago(1)]), CFG)
    assert r.status == slo.BREACH and r.category == slo.CODE
    assert r.measured == pytest.approx(limit + 3) and r.threshold == limit
    assert "2 deploy-relevant" in r.detail


def test_recent_undeployed_commit_is_within_budget():
    limit = CFG["codeFreshness"]["deployLagMaxHours"]
    assert slo.rule_deploy_lag(snap(undeployed_relevant=[ago(limit - 1)]), CFG).status == slo.OK


def test_unknown_deployed_sha_is_unknown_not_ok():
    r = slo.rule_deploy_lag(snap(undeployed_relevant=None), CFG)
    assert r.status == slo.UNKNOWN and r.measured is None


def test_repeated_failures_with_a_long_gap_breach():
    c = CFG["codeFreshness"]["deployFailures"]
    gap = c["maxHoursSinceSuccessWithUndeployed"] + 5
    runs = [run("success", gap)] + [
        run("failure", gap - 1 - i) for i in range(c["maxConsecutiveFailures"])
    ]
    r = slo.rule_deploy_failures(snap(undeployed_relevant=[ago(2)], deploy_runs=runs), CFG)
    assert r.status == slo.BREACH
    assert r.measured["consecutiveFailures"] == c["maxConsecutiveFailures"]


def test_failures_that_recovered_quickly_are_normal_operation():
    c = CFG["codeFreshness"]["deployFailures"]
    runs = [run("failure", 3 + i) for i in range(c["maxConsecutiveFailures"] + 2)] + [
        run("success", 1)
    ]
    # The latest run succeeded: zero consecutive failures, short gap.
    r = slo.rule_deploy_failures(snap(undeployed_relevant=[ago(2)], deploy_runs=runs), CFG)
    assert r.status == slo.OK


def test_a_failure_streak_with_a_recent_success_does_not_breach():
    c = CFG["codeFreshness"]["deployFailures"]
    runs = [run("success", 2)] + [
        run("failure", 1.5 - 0.1 * i) for i in range(c["maxConsecutiveFailures"])
    ]
    assert (
        slo.rule_deploy_failures(snap(undeployed_relevant=[ago(1)], deploy_runs=runs), CFG).status
        == slo.OK
    )


def test_failures_with_nothing_waiting_do_not_alert():
    runs = [run("failure", 40 - i) for i in range(6)]
    assert (
        slo.rule_deploy_failures(snap(undeployed_relevant=[], deploy_runs=runs), CFG).status
        == slo.OK
    )


def test_no_success_in_window_with_failures_breaches():
    c = CFG["codeFreshness"]["deployFailures"]
    runs = [run("failure", 30 - i) for i in range(c["maxConsecutiveFailures"])]
    r = slo.rule_deploy_failures(snap(undeployed_relevant=[ago(20)], deploy_runs=runs), CFG)
    assert r.status == slo.BREACH and r.measured["hoursSinceSuccess"] is None


def test_cancelled_and_in_progress_runs_are_ignored():
    runs = [
        run("success", 30),
        {"conclusion": "cancelled", "updated_at": ago(5).isoformat()},
        {"conclusion": None, "status": "in_progress", "updated_at": ago(1).isoformat()},
    ]
    last, failures = slo.last_success_and_failures(runs, NOW)
    assert last == ago(30) and failures == 0


def test_missing_run_history_is_unknown():
    assert (
        slo.rule_deploy_failures(snap(deploy_runs=None, undeployed_relevant=[ago(1)]), CFG).status
        == slo.UNKNOWN
    )
    assert slo.rule_refresh(snap(refresh_runs=None), CFG).status == slo.UNKNOWN
    assert slo.rule_refresh(snap(refresh_runs=[run("failure", 1)]), CFG).status == slo.UNKNOWN


# -- pipeline -------------------------------------------------------------------
def test_stalled_refresh_breaches():
    limit = CFG["refreshPipeline"]["maxHoursSinceSuccess"]
    r = slo.rule_refresh(snap(refresh_runs=[run("success", limit + 6), run("failure", 2)]), CFG)
    assert r.status == slo.BREACH and r.category == slo.PIPELINE and r.threshold == limit


def test_normal_refresh_gap_is_ok():
    assert slo.rule_refresh(snap(refresh_runs=[run("success", 11.6)]), CFG).status == slo.OK


# -- data freshness (kept separate from code freshness) ---------------------------
def test_stale_board_breaches_each_data_rule_by_name():
    stale = healthy_slo(
        top200StaleShare=0.95, pricedWithheldShare=0.9, boardAgeHours=40.0, privateSourcesStale=1
    )
    results = by_rule(slo.evaluate(snap(freshness_slo=stale), CFG))
    for rule in (
        "data_freshness.top200_stale_share",
        "data_freshness.priced_withheld_share",
        "data_freshness.board_age_hours",
        "data_freshness.private_sources",
    ):
        assert results[rule].status == slo.BREACH, rule
        assert results[rule].category == slo.DATA
    assert results["code_freshness.deploy_lag"].status == slo.OK  # code OK, data not: separate
    assert slo.exit_code(list(results.values())) == 1


def test_share_exactly_at_threshold_is_ok():
    limit = CFG["dataFreshness"]["maxTop200StaleShare"]
    assert (
        slo.rule_top200_stale(snap(freshness_slo=healthy_slo(top200StaleShare=limit)), CFG).status
        == slo.OK
    )


def test_missing_freshness_block_is_unknown_never_healthy():
    results = by_rule(slo.evaluate(snap(freshness_slo=None), CFG))
    for rule in (
        "data_freshness.top200_stale_share",
        "data_freshness.priced_withheld_share",
        "data_freshness.board_age_hours",
        "data_freshness.private_sources",
    ):
        assert results[rule].status == slo.UNKNOWN, rule
    assert slo.exit_code(list(results.values())) == 3
    assert slo.exit_code(list(results.values()), unknown_ok=True) == 0


def test_null_measurement_is_unknown_not_zero():
    r = slo.rule_top200_stale(
        snap(freshness_slo=healthy_slo(top200StaleShare=None, state="unknown")), CFG
    )
    assert r.status == slo.UNKNOWN and r.measured is None


def test_unreachable_status_is_unknown():
    s = snap(freshness_slo=None, status_reachable=False)
    assert all(r.status == slo.UNKNOWN for r in slo.evaluate(s, CFG) if r.category == slo.DATA)


def test_unmeasurable_private_sources_are_unknown():
    r = slo.rule_private_sources(snap(freshness_slo=healthy_slo(privateSourcesUnknown=2)), CFG)
    assert r.status == slo.UNKNOWN


def test_breach_outranks_unknown_in_exit_code():
    results = [slo.Result("a", slo.CODE, slo.BREACH), slo.Result("b", slo.DATA, slo.UNKNOWN)]
    assert slo.exit_code(results) == 1


def test_report_names_every_breach_with_value_and_threshold_and_no_secrets(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_SECRETTOKENVALUE")
    results = slo.evaluate(
        snap(undeployed_relevant=[ago(30)], freshness_slo=healthy_slo(top200StaleShare=0.95)), CFG
    )
    text = slo.render(results, NOW)
    assert "BREACHED: code_freshness.deploy_lag, data_freshness.top200_stale_share" in text
    assert "measured=30.0 threshold=12.0" in text and "measured=0.95 threshold=0.1" in text
    assert "ghs_SECRETTOKENVALUE" not in text


# -- deploy path classification ---------------------------------------------------
@pytest.fixture(scope="module")
def ignore():
    return slo.load_paths_ignore(_REPO / CFG["deployPathsIgnoreFile"])


@pytest.mark.parametrize(
    "files,relevant",
    [
        (["data/scrape_state/ktc_last_success"], False),
        (["exports/latest/dynasty_data_2026-11-18.json"], False),
        (["docs/ops/NOTE.md", "tests/api/test_x.py"], False),
        (["README.md"], False),
        (["src/api/data_contract.py"], True),
        (["data/x.json", "server.py"], True),
        (["docs/sources/SIGNALS_FANTASY_INTEGRATION.md"], True),  # read at runtime: deploys
        (["docs/new_subtree/x.md"], True),  # fail-safe: unlisted docs deploy
        (["frontend/app/page.jsx"], True),
        ([], True),  # unknown file list fails toward alert
    ],
)
def test_commit_relevance_follows_deploy_workflow_paths_ignore(ignore, files, relevant):
    assert slo.commit_is_deploy_relevant(files, ignore) is relevant


def test_glob_semantics_match_github_actions():
    assert slo.glob_to_regex("*.md").match("README.md")
    assert not slo.glob_to_regex("*.md").match("docs/a.md")  # `*` stays in a segment
    assert slo.glob_to_regex("data/**").match("data/a/b/c.json")
    assert not slo.glob_to_regex("data/**").match("database/x")


# -- git integration (real repo, tiny history) -------------------------------------
def test_undeployed_relevant_times_against_a_real_repo(tmp_path, monkeypatch, ignore):
    def git(*a):
        env = {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@e",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@e",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        }
        return subprocess.run(
            ["git", *a], cwd=tmp_path, check=True, capture_output=True, text=True, env=env
        ).stdout

    git("init", "-q", "-b", "main")
    (tmp_path / "a.txt").write_text("1")
    git("add", "."), git("commit", "-qm", "base")
    deployed = git("rev-parse", "HEAD").strip()
    (tmp_path / "data").mkdir()
    (tmp_path / "data/x.json").write_text("{}")
    git("add", "."), git("commit", "-qm", "data only")
    (tmp_path / "src.py").write_text("x")
    git("add", "."), git("commit", "-qm", "code")
    monkeypatch.setattr(slo, "REPO_ROOT", tmp_path)
    times = slo.undeployed_relevant_times(deployed, "main", ignore)
    assert len(times) == 1  # the data-only commit starts no deploy; the code commit does
    assert slo.undeployed_relevant_times(git("rev-parse", "HEAD").strip(), "main", ignore) == []
    with pytest.raises(subprocess.CalledProcessError):  # unknown SHA is an error, never "no lag"
        slo.undeployed_relevant_times("0" * 40, "main", ignore)


def test_backtest_replay_fires_on_a_synthetic_outage(monkeypatch, tmp_path, ignore):
    """The replay uses the same rules: a deploy that never lands for a day alerts."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    t0 = now - timedelta(days=2)
    deploys = [
        {
            "conclusion": "success",
            "updated_at": t0.isoformat(),
            "head_sha": "a" * 40,
            "created_at": t0.isoformat(),
        }
    ]
    deploys += [
        {
            "conclusion": "failure",
            "updated_at": (t0 + timedelta(hours=14 + i)).isoformat(),
            "head_sha": "b" * 40,
            "created_at": (t0 + timedelta(hours=14 + i)).isoformat(),
        }
        for i in range(4)
    ]
    refreshes = [
        {
            "conclusion": "success",
            "updated_at": (now - timedelta(hours=h)).isoformat(),
            "created_at": (now - timedelta(hours=h)).isoformat(),
        }
        for h in range(1, 60, 6)
    ]
    monkeypatch.setattr(
        slo,
        "fetch_runs",
        lambda repo, wf, since, token, per_page=100: deploys
        if wf == CFG["deployWorkflow"]
        else refreshes,
    )
    monkeypatch.setattr(
        slo,
        "git_commits_not_in",
        lambda sha, ref: [("c" * 40, t0 + timedelta(hours=1), ["server.py"])],
    )
    summary = slo.backtest(CFG, 1, "main", None, warmup_days=3)
    assert summary["code_freshness.deploy_lag"]["alertHours"] > 0
    assert summary["pipeline.refresh"]["alertHours"] == 0


# -- workflow wiring ----------------------------------------------------------------
def test_workflow_runs_the_script_with_minimal_permissions_and_no_comment_per_run():
    import yaml

    text = (_REPO / ".github/workflows/health-check.yml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    assert doc["permissions"] == {"contents": "read", "actions": "read"}
    job = doc["jobs"]["slo"]
    assert set(job["permissions"]) <= {"contents", "actions", "issues"}
    assert "scripts/check_production_slo.py" in text
    sync = next(s for s in job["steps"] if "tracking issue" in s.get("name", ""))
    body = sync["run"]
    # Comment only when the breached set CHANGES; the body is refreshed in place.
    assert '"$OLD_SIG" != "$SIG"' in body and "gh api --method PATCH" in body
    assert body.count("gh issue comment") == 1
    # No threshold literals in the workflow: they live in the config file.
    assert "maxHours" not in text
    # A green run closes the tracker; an unmeasurable run does not.
    assert 'if [[ "${RC}" == "0" ]]' in body and "gh issue close" in body
