from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "crawl_sharp_activity.py"
SPEC = importlib.util.spec_from_file_location("crawl_sharp_activity", SCRIPT)
assert SPEC and SPEC.loader
activity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity)


def test_qualified_sleeper_ids_excludes_other_platforms_and_unqualified(monkeypatch):
    records = [SimpleNamespace(user_id="sleeper:one"), SimpleNamespace(user_id="ffpc:two")]
    scores = [
        SimpleNamespace(user_id="sleeper:one", evaluable=True, qualified=True),
        SimpleNamespace(user_id="sleeper:no", evaluable=True, qualified=False),
        SimpleNamespace(user_id="ffpc:two", evaluable=True, qualified=True),
    ]
    monkeypatch.setattr(
        activity.platform_records, "build_manager_records", lambda: (records, {"a": 1})
    )
    monkeypatch.setattr(activity.sharp_score, "score_managers", lambda _records: scores)
    monkeypatch.setattr(activity.sharp_score, "methodology_version", lambda: "sharp-v2")

    manager_ids, summary = activity.qualified_sleeper_ids()

    assert manager_ids == ["one"]
    assert summary == {
        "methodologyVersion": "sharp-v2",
        "managerRecords": 2,
        "evidenceManagers": 1,
        "evaluableManagers": 3,
        "qualifiedManagers": 2,
        "qualifiedSleeperManagers": 1,
    }


def test_no_qualified_manager_is_a_clean_cohort_building_result(monkeypatch):
    monkeypatch.setattr(
        activity, "qualified_sleeper_ids", lambda: ([], {"qualifiedSleeperManagers": 0})
    )
    monkeypatch.setattr(
        activity.platform_ledger,
        "platform_coverage",
        lambda: {"sleeper": {"transactions": 0, "movements": 0}},
    )
    called = False

    def fail_refresh(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("refresh must not run without qualified managers")

    monkeypatch.setattr(activity.intel_service, "refresh_intel", fail_refresh)

    result = activity.run_activity_crawl()

    assert result["status"] == "cohort_building"
    assert result["selectedManagers"] == 0
    assert result["coverageAfter"]["movements"] == 0
    assert called is False


def test_activity_crawl_uses_only_bounded_qualified_manager_pool(monkeypatch):
    monkeypatch.setattr(
        activity,
        "qualified_sleeper_ids",
        lambda: (["3", "1", "2"], {"qualifiedSleeperManagers": 3}),
    )
    coverage = iter(
        [
            {"sleeper": {"transactions": 0, "movements": 0}},
            {"sleeper": {"transactions": 4, "movements": 8}},
        ]
    )
    monkeypatch.setattr(activity.platform_ledger, "platform_coverage", lambda: next(coverage))
    captured = {}

    def refresh_intel(**kwargs):
        captured.update(kwargs)
        return {"callsUsed": 19, "newEventCount": 8}

    monkeypatch.setattr(activity.intel_service, "refresh_intel", refresh_intel)

    result = activity.run_activity_crawl(
        budget=123,
        max_managers=2,
        sleep_seconds=0.0,
        league_key="sharp-test",
    )

    assert captured == {
        "member_ids": ["3", "1"],
        "league_key": "sharp-test",
        "budget": 123,
        "sleep_s": 0.0,
    }
    assert result["status"] == "success"
    assert result["selectedManagers"] == 2
    assert result["coverageAfter"] == {"transactions": 4, "movements": 8}


def test_systemd_wiring_installs_daily_activity_collector():
    repo = SCRIPT.parents[1]
    service = (repo / "deploy/systemd/dynasty-sharp-activity.service.template").read_text()
    timer = (repo / "deploy/systemd/dynasty-sharp-activity.timer.template").read_text()
    bootstrap = (repo / "deploy/bootstrap-sharp-records.sh").read_text()

    assert "scripts/crawl_sharp_activity.py" in service
    assert "OnCalendar=*-*-* 06:30:00 UTC" in timer
    assert 'enable --now "${activity_timer}"' in bootstrap
    assert 'run_oneshot "${activity_service}"' in bootstrap
