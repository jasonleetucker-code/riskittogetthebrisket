"""D-2: a backend boot scrapes at once unless its fresh, healthy board is still in-interval.

``docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md`` §6.1 D-2.  Every restart used
to launch a scrape (Chromium included) 3 s after boot whatever the age of the
board it had just primed, and reset the scheduled loop to ``boot + interval``.
``server._startup_scrape_plan`` now lets a boot skip that scrape ONLY when the
primed board is healthy and younger than one ``SCRAPE_INTERVAL_HOURS``, and
then schedules the first scrape at ``produced + interval`` -- when an
uninterrupted process would have scraped anyway.

What these tests pin:

* the plan never skips a stale, unknown-age, future-dated, unhealthy or absent
  board, nor with the flag off -- the "never skip a scrape when the on-disk
  contract is stale" requirement, stated as a sweep;
* a skipped boot's first scheduled scrape lands at ``produced + interval``,
  so the maximum served-board age is unchanged;
* ``schedule_loop`` honours the first delay once, never waits LONGER than an
  interval, and returns to the interval afterwards;
* the real ``server.lifespan`` wires the plan: with the flag at its DEFAULT
  (OFF) every boot scrapes exactly as before; with it ON a stale or unhealthy
  board still gets its startup scrape, a fresh healthy one does not, and both
  start the schedule.

The flag ``conditional_startup_scrape`` defaults OFF (today's behaviour): the
change is not a pure no-risk improvement -- a deploy that ships scraper code no
longer exercises it at once, and it changes the per-restart memory profile the
owner-reserved MemoryHigh canary measures -- so activation is a separate,
explicit decision.
"""

from __future__ import annotations

import asyncio
import types

import pytest

import server
from src.api import feature_flags

INTERVAL_H = server.SCRAPE_INTERVAL_HOURS
INTERVAL_S = INTERVAL_H * 3600.0


def _plan(age, *, has_contract=True, contract_ok=True, enabled=True):
    return server._startup_scrape_plan(
        age, has_contract=has_contract, contract_ok=contract_ok, enabled=enabled
    )


# ── the decision ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("age", "kwargs", "reason"),
    [
        (0.5, {"enabled": False}, "flag_off"),
        (0.5, {"has_contract": False}, "no_primed_contract"),
        (0.5, {"contract_ok": False}, "contract_unhealthy"),
        (None, {}, "board_age_unknown"),
        (-0.01, {}, "board_due"),
        (INTERVAL_H, {}, "board_due"),
        (INTERVAL_H * 3 + 0.1, {}, "board_due"),  # /api/health data_stale
        (500.0, {}, "board_due"),
    ],
)
def test_every_boot_that_is_not_provably_in_interval_scrapes_at_once(age, kwargs, reason):
    plan = _plan(age, **kwargs)
    assert plan["run_now"] is True
    assert plan["reason"] == reason
    # ...and the schedule keeps its old shape: one interval after boot.
    assert plan["first_delay_seconds"] == INTERVAL_S


def test_a_fresh_healthy_board_skips_and_scrapes_when_it_comes_due():
    plan = _plan(0.5)
    assert plan["run_now"] is False
    assert plan["reason"] == "board_within_interval"
    assert plan["first_delay_seconds"] == pytest.approx(INTERVAL_S - 0.5 * 3600)


@pytest.mark.parametrize("age", [i / 20 for i in range(0, 20 * int(INTERVAL_H * 4) + 1)])
def test_skipping_never_extends_the_age_of_the_served_board(age):
    plan = _plan(age)
    if plan["run_now"]:
        return
    # Only in-interval boards are skipped -- a fortiori never a stale one.
    assert 0 <= age < INTERVAL_H < INTERVAL_H * 3
    # The next scrape is due exactly when an uninterrupted process's would be.
    assert age + plan["first_delay_seconds"] / 3600 == pytest.approx(INTERVAL_H)


def test_the_flag_is_registered_live_and_off_by_default():
    assert feature_flags._DEFAULTS["conditional_startup_scrape"] is False
    assert feature_flags._GATE_STATUS["conditional_startup_scrape"] == feature_flags.LIVE


# ── the schedule ────────────────────────────────────────────────────────────


def _drive_schedule(monkeypatch, first_delay, rounds=2):
    sleeps: list[float] = []
    scrapes: list[int] = []

    class _Stop(Exception):
        pass

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    async def fake_scheduled_scrape():
        scrapes.append(1)
        if len(scrapes) >= rounds:
            raise _Stop

    monkeypatch.setattr(server.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(server, "scheduled_scrape", fake_scheduled_scrape)
    with pytest.raises(_Stop):
        asyncio.run(server.schedule_loop(first_delay))
    return sleeps


def test_schedule_loop_defaults_to_the_interval(monkeypatch):
    assert _drive_schedule(monkeypatch, None) == [INTERVAL_S, INTERVAL_S]


def test_schedule_loop_honours_a_shorter_first_delay_once(monkeypatch):
    assert _drive_schedule(monkeypatch, 1800.0) == [1800.0, INTERVAL_S]


@pytest.mark.parametrize(("given", "used"), [(-5.0, 0.0), (INTERVAL_S * 10, INTERVAL_S)])
def test_schedule_loop_clamps_the_first_delay_inside_one_interval(monkeypatch, given, used):
    assert _drive_schedule(monkeypatch, given, rounds=1) == [used]


# ── the lifespan wiring ─────────────────────────────────────────────────────


@pytest.fixture
def flag(monkeypatch):
    """Set ``conditional_startup_scrape`` through its env override (or clear it)."""

    def _set(value):
        if value is None:
            monkeypatch.delenv("RISKIT_FEATURE_CONDITIONAL_STARTUP_SCRAPE", raising=False)
        else:
            monkeypatch.setenv("RISKIT_FEATURE_CONDITIONAL_STARTUP_SCRAPE", value)
        feature_flags.reload()

    yield _set
    monkeypatch.delenv("RISKIT_FEATURE_CONDITIONAL_STARTUP_SCRAPE", raising=False)
    feature_flags.reload()


def _run_lifespan(monkeypatch, tmp_path, *, board_age, contract_ok=True):
    """Enter the REAL ``server.lifespan`` with its heavy collaborators stubbed."""
    from src.api import session_store, startup_validation
    from src.auction import runtime as auction_runtime

    scrapes: list[str] = []
    loop_args: list[float | None] = []
    events: list[tuple[str, dict]] = []

    async def fake_run_scraper(trigger="manual"):
        scrapes.append(trigger)

    async def fake_schedule_loop(first_delay_seconds=None):
        loop_args.append(first_delay_seconds)
        await asyncio.Event().wait()

    async def idle():
        await asyncio.Event().wait()

    def fake_prime(data, **_kw):
        server.latest_contract_data = {"playersArray": []} if data else None
        server.contract_health = {"ok": contract_ok}

    real_sleep = asyncio.sleep

    async def fast_sleep(seconds):  # initial_scrape's 3 s boot delay
        await real_sleep(0)

    fast_asyncio = types.SimpleNamespace(**{**vars(asyncio), "sleep": fast_sleep})

    monkeypatch.setattr(server, "asyncio", fast_asyncio)
    monkeypatch.setattr(server, "SCRAPE_SCHEDULER_ENABLED", True)
    monkeypatch.setattr(server, "latest_data", None)
    monkeypatch.setattr(server, "latest_contract_data", None)
    monkeypatch.setattr(server, "contract_health", dict(server.contract_health))
    monkeypatch.setattr(server, "load_from_disk", lambda: {"players": {"a": {}}})
    monkeypatch.setattr(server, "_seed_ingestion_verdict_from_startup_payload", lambda d: None)
    monkeypatch.setattr(server, "_prime_latest_payload", fake_prime)
    monkeypatch.setattr(server, "_recover_startup_contract_from_checkout", lambda d: d)
    monkeypatch.setattr(server, "_board_age_hours", lambda: board_age)
    monkeypatch.setattr(server, "_screenshot_import_startup_check", lambda: None)
    monkeypatch.setattr(server, "_warmup_public_snapshot", lambda: None)
    monkeypatch.setattr(server, "run_scraper", fake_run_scraper)
    monkeypatch.setattr(server, "schedule_loop", fake_schedule_loop)
    monkeypatch.setattr(server, "uptime_watchdog_loop", idle)
    monkeypatch.setattr(
        server, "_record_scrape_event", lambda event, **kw: events.append((event, kw))
    )
    monkeypatch.setattr(startup_validation, "run_all", lambda: [])
    monkeypatch.setattr(startup_validation, "summary", lambda checks: {"total": 0})
    monkeypatch.setattr(session_store, "hydrate", lambda **kw: {})
    monkeypatch.setattr(auction_runtime, "start", lambda: None)
    history = tmp_path / "source_value_history.jsonl"
    history.write_text("{}\n", encoding="utf-8")  # non-empty: no startup backfill
    monkeypatch.setattr(server._source_history, "HISTORY_PATH", history)

    async def body():
        async with server.lifespan(server.app):
            for _ in range(20):
                await real_sleep(0)

    asyncio.run(body())
    plan_events = [kw for event, kw in events if event == "startup_scrape_plan"]
    return scrapes, loop_args, plan_events


def test_lifespan_default_keeps_todays_boot_scrape_even_for_a_fresh_board(
    monkeypatch, tmp_path, flag
):
    flag(None)  # the registry default
    scrapes, loop_args, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=0.5)
    assert scrapes == ["startup"]
    assert loop_args == [None]  # schedule_loop() exactly as before
    assert plan_events == []  # and no new telemetry


def test_lifespan_still_scrapes_at_boot_when_the_board_is_due(monkeypatch, tmp_path, flag):
    flag("1")
    scrapes, loop_args, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=INTERVAL_H + 1)
    assert scrapes == ["startup"]
    assert loop_args == [INTERVAL_S]
    assert plan_events and plan_events[0]["run_now"] is True
    assert plan_events[0]["reason"] == "board_due"


def test_lifespan_still_scrapes_at_boot_when_the_board_is_stale(monkeypatch, tmp_path, flag):
    flag("1")
    scrapes, _, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=INTERVAL_H * 3 + 1)
    assert scrapes == ["startup"]
    assert plan_events[0]["reason"] == "board_due"


def test_lifespan_still_scrapes_at_boot_when_the_board_age_is_unknown(monkeypatch, tmp_path, flag):
    flag("1")
    scrapes, _, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=None)
    assert scrapes == ["startup"]
    assert plan_events[0]["reason"] == "board_age_unknown"


def test_lifespan_still_scrapes_at_boot_when_the_contract_is_unhealthy(monkeypatch, tmp_path, flag):
    flag("1")
    scrapes, _, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=0.2, contract_ok=False)
    assert scrapes == ["startup"]
    assert plan_events[0]["reason"] == "contract_unhealthy"


def test_lifespan_skips_the_startup_scrape_for_a_fresh_healthy_board(monkeypatch, tmp_path, flag):
    flag("1")
    scrapes, loop_args, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=0.5)
    assert scrapes == []
    assert loop_args == [pytest.approx(INTERVAL_S - 1800.0)]
    assert plan_events[0]["run_now"] is False
    assert plan_events[0]["reason"] == "board_within_interval"


def test_lifespan_rollback_value_restores_the_boot_scrape(monkeypatch, tmp_path, flag):
    flag("0")
    scrapes, loop_args, plan_events = _run_lifespan(monkeypatch, tmp_path, board_age=0.5)
    assert scrapes == ["startup"]
    assert loop_args == [None]
    assert plan_events == []
