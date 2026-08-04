from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "crawl_sharp_activity.py"
SPEC = importlib.util.spec_from_file_location("crawl_sharp_activity", SCRIPT)
assert SPEC and SPEC.loader
activity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(activity)


def test_qualified_sleeper_ids_selects_from_the_shared_cohort(monkeypatch):
    """The activity crawl selects from the ONE cohort, not its own copy.

    It used to re-derive the pool here — ``build_manager_records`` then
    ``score_managers`` then filter on ``qualified`` — which meant a
    change to qualification moved the Sharp boards while the crawl that
    feeds them kept selecting the old set. The selection now comes from
    ``src/sharp/cohort.py``, so this test patches that seam and asserts
    only what the function still does itself: keep the Sleeper accounts.
    """
    members = [
        SimpleNamespace(manager_key="sleeper:one"),
        SimpleNamespace(manager_key="ffpc:two"),
    ]
    captured = {}

    def fake_cohort_members(**kwargs):
        captured.update(kwargs)
        return members, {"evidenceManagers": 1}

    monkeypatch.setattr(activity.sharp_cohort, "cohort_members", fake_cohort_members)
    monkeypatch.setattr(activity.sharp_score, "methodology_version", lambda: "sharp-v2")

    manager_ids, summary = activity.qualified_sleeper_ids()

    assert manager_ids == ["one"]
    # Curated and provisional members are FFPC-only; this pass crawls Sleeper.
    assert captured == {"qualification": "automated"}
    assert summary == {
        "methodologyVersion": "sharp-v2",
        "evidenceManagers": 1,
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
