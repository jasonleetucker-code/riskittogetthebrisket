"""Sharp discovery is not enough: production must also collect records.

The Sharp Tracker can show thousands of observable managers while remaining
empty when the season-records unit is missing, never receives its first run,
or repeatedly spends its budget on the same prefix of leagues.  These guards
pin the production path that turns discovery coverage into scoreable history.
"""

from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BOOTSTRAP = _REPO / "deploy" / "bootstrap-sharp-records.sh"
_TIMER = _REPO / "deploy" / "systemd" / "dynasty-sharp-records.timer.template"
_WORKFLOW = _REPO / ".github" / "workflows" / "sharp-records-bootstrap.yml"
_CRAWLER = _REPO / "scripts" / "crawl_sharp_records.py"


def test_bootstrap_installs_reloads_and_enables_both_sharp_timers() -> None:
    body = _BOOTSTRAP.read_text(encoding="utf-8")
    assert "dynasty-sharp-discovery.timer.template" in body
    assert "dynasty-sharp-records.timer.template" in body
    assert "daemon-reload" in body
    assert 'enable --now "${discovery_timer}"' in body
    assert 'enable --now "${records_timer}"' in body


def test_bootstrap_can_immediately_start_the_records_service() -> None:
    body = _BOOTSTRAP.read_text(encoding="utf-8")
    assert 'run_oneshot "${records_service}"' in body
    assert "SHARP_BOOTSTRAP_MAX_PASSES" in body
    assert "completedSeasonRows" in body


def test_records_timer_has_a_first_activation_safety_net() -> None:
    body = _TIMER.read_text(encoding="utf-8")
    assert "OnActiveSec=" in body
    assert "OnCalendar=" in body
    assert "Persistent=true" in body


def test_production_deploy_success_triggers_the_bootstrap_workflow() -> None:
    body = _WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" in body
    assert "Deploy Production" in body
    assert "workflow_run.conclusion == 'success'" in body
    assert "deploy/bootstrap-sharp-records.sh" in body


def test_default_records_crawl_uses_the_persistent_fair_queue() -> None:
    body = _CRAWLER.read_text(encoding="utf-8")
    assert "record_queue.prioritized_league_ids()" in body
    assert 'payload["queue"] = record_queue.queue_stats()' in body
