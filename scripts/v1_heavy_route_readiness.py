#!/usr/bin/env python3
"""Bounded wait until the War Room's heavy authenticated routes answer warm (STAB-10).

Runs on the GitHub Actions RUNNER inside
``.github/workflows/v1-authenticated-verification.yml``, holding the guest-pass
session cookie that workflow mints.  Stdlib only (it reuses the trade builder
and HTTP client of ``scripts/smoke_trade_analysis.py``).

Why it exists.  The workflow's public warm check (``/api/health`` fast with no
scrape running) was satisfied in V1 run 44331428925, and the desktop War Room
spec still timed out at 125 s -- 6.2 min after a backend restart -- while the
same spec passed on mobile 9 min later in 41 s.  Over the 11 V1 runs of
2026-11-16..18 the desktop War Room spec, which runs 6-10 min after the
restart, took 13.8-125.3 s (median 53 s); the mobile run of the same spec,
11-18 min after, took 17.6-41.1 s (median 23 s).  The heavy requests that spec
makes -- the FULL ``/api/data`` contract and a Team Context
``POST /api/trade/analyze`` -- are cold after a restart, and nothing measured
that before a spec with 120 s waits ran into it.

What it does.  Repeats ONE probe of exactly those two requests (the same 2-team
trade the trade smoke builds, with Team Context ON, sending ``X-Chase-Smoke:
1`` so no decision receipt is written) until both answer HTTP 200 within
``--ready-seconds`` on the same attempt, or ``--budget-seconds`` runs out.  It
reports how long warm-up took and every attempt's latencies plus the analyze
route's own server wall time (``analysisTiming.totalMs``; never a cookie,
player or manager name), so the cold cost is measured instead of hidden.

Exit codes: 0 ready (a slow FIRST probe is still reported, as a ::warning);
2 not ready within the budget (::error -- the workflow's verdict step fails the
job on it; the suites still run so their evidence exists); 1 usage.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_trade_analysis as smoke  # noqa: E402

EXIT_READY = 0
EXIT_USAGE = 1
EXIT_NOT_READY = 2


def _server_ms(body: Any) -> float | None:
    """The analyze route's own server wall time (``analysisTiming.totalMs``).
    A guest session is served the total only -- per-stage times could reveal
    whether a shared cache was warm -- so the total is all this reads."""
    timing = body.get("analysisTiming") if isinstance(body, dict) else None
    total = timing.get("totalMs") if isinstance(timing, dict) else None
    return round(float(total), 1) if smoke._is_num(total) else None  # noqa: SLF001


def probe(
    client: smoke.Client, league: str, clock: Callable[[], float] = time.monotonic
) -> dict[str, Any]:
    """One attempt: the full contract, then a Team Context analyze."""
    attempt: dict[str, Any] = {}
    t0 = clock()
    status, contract = client.request(f"/api/data?leagueKey={league}")
    attempt["dataSeconds"] = round(clock() - t0, 1)
    attempt["dataStatus"] = status
    if status != 200 or not isinstance(contract, dict):
        attempt["result"] = "data_not_ok"
        return attempt
    try:
        built = smoke.build_trades(contract, league)
    except smoke.BuildError as exc:
        attempt["result"] = f"cannot_build_trade:{exc}"
        return attempt
    body = dict(built["two"], useTeamContext=True)
    t1 = clock()
    status, answer = client.request("/api/trade/analyze", body)
    attempt["analyzeSeconds"] = round(clock() - t1, 1)
    attempt["analyzeStatus"] = status
    attempt["analyzeServerMs"] = _server_ms(answer)
    attempt["result"] = "answered" if status == 200 else "analyze_not_ok"
    return attempt


def wait_until_ready(
    client: smoke.Client,
    league: str,
    *,
    budget_seconds: float,
    ready_seconds: float,
    interval_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    start = clock()
    attempts: list[dict[str, Any]] = []
    while True:
        attempt = probe(client, league, clock)
        attempts.append(attempt)
        ready = (
            attempt.get("result") == "answered"
            and attempt["dataSeconds"] <= ready_seconds
            and attempt["analyzeSeconds"] <= ready_seconds
        )
        elapsed = clock() - start
        if ready or elapsed >= budget_seconds:
            return {
                "ready": ready,
                "warmupSeconds": round(elapsed, 1) if ready else None,
                "elapsedSeconds": round(elapsed, 1),
                "budgetSeconds": budget_seconds,
                "readySeconds": ready_seconds,
                "attempts": attempts,
            }
        sleep(min(interval_seconds, max(0.0, budget_seconds - elapsed)))


def annotations(report: dict[str, Any]) -> list[str]:
    first = report["attempts"][0] if report["attempts"] else {}
    first_txt = (
        f"first probe: /api/data {first.get('dataSeconds')}s (HTTP {first.get('dataStatus')}), "
        f"analyze {first.get('analyzeSeconds', 'n/a')}s (HTTP {first.get('analyzeStatus', 'n/a')})"
    )
    if not report["ready"]:
        return [
            "::error title=Trade routes not ready::the full /api/data contract and a Team Context "
            f"analyze did not both answer within {report['readySeconds']:g}s inside the "
            f"{report['budgetSeconds']:g}s budget ({len(report['attempts'])} probe(s); {first_txt}). "
            "Production's trade path stayed cold or failing; the suites still run for evidence."
        ]
    lines = [
        f"trade routes ready after {report['warmupSeconds']}s "
        f"({len(report['attempts'])} probe(s); {first_txt})"
    ]
    if len(report["attempts"]) > 1:
        lines.append(
            "::warning title=Cold trade routes after restart::"
            f"the War Room's heavy requests took {report['warmupSeconds']}s to answer warm "
            f"({first_txt}); a user arriving first would have waited that long."
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--origin", required=True)
    p.add_argument("--cookie-file", required=True)
    p.add_argument("--league", default="dynasty_main")
    p.add_argument("--budget-seconds", type=float, default=300.0)
    p.add_argument("--ready-seconds", type=float, default=30.0)
    p.add_argument("--interval-seconds", type=float, default=15.0)
    p.add_argument("--request-timeout", type=float, default=150.0)
    p.add_argument("--out", help="also write the JSON report here")
    args = p.parse_args(argv)
    try:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    except OSError:
        print("::error::session cookie file is unreadable", file=sys.stderr)
        return EXIT_USAGE
    if not cookie or args.budget_seconds <= 0 or args.ready_seconds <= 0:
        print("::error::empty cookie or non-positive bound", file=sys.stderr)
        return EXIT_USAGE

    client = smoke.Client(
        args.origin, cookie, args.request_timeout, lambda m: print(m, file=sys.stderr)
    )
    report = wait_until_ready(
        client,
        args.league,
        budget_seconds=args.budget_seconds,
        ready_seconds=args.ready_seconds,
        interval_seconds=args.interval_seconds,
    )
    report["league"] = args.league
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    for line in annotations(report):
        print(line)
    return EXIT_READY if report["ready"] else EXIT_NOT_READY


if __name__ == "__main__":
    raise SystemExit(main())
