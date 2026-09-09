"""Assert the LIVE server is serving a fully-enriched board.

The silent failure this closes: the committed export is intrinsically
a 3-source artifact; the full ~11-source board only exists after the
running process re-primes and ``_enrich_from_source_csvs`` grafts the
per-source CSVs on.  If a deploy doesn't actually re-prime (or a
source silently drops), the server keeps serving a degraded 3-source
board and *every* health/smoke check still passes — ``/api/health``
is 200, ``player_count`` is normal, ``sites``/``source_health`` only
ever list the 3 legacy sources so they look unchanged.  That is
exactly how OTCFFB (+ ~8 others) stayed off the live board for days
with no alarm.

This fetches ``/api/status``'s ``served_source_coverage`` — the real
per-source player counts of the board being served right now — and
runs it through the SAME fresh-but-absent decision core the CI
contract-coverage watchdog uses (``evaluate_coverage_map``).  A
registered source that is fresh + non-empty in the checkout but
missing from the served board fails this check.

Used at two layers so a degraded board cannot persist silently:
  * ``deploy/verify-deploy.sh`` — on-box, right after the service
    restart; a failure makes the deploy fail and trips the existing
    auto-rollback, so a deploy literally cannot "succeed" while
    serving a degraded board.
  * ``.github/workflows/health-check.yml`` — every 6h against the
    public URL, catching drift that happens outside a deploy.

Usage:
    python scripts/verify_live_source_coverage.py <base_url>
    # or: DEPLOY_VERIFY_BASE_URL=http://127.0.0.1:8000 python ...

Exit codes:
  0 — every fresh registered source is present in the served board
  1 — a fresh source is absent (degraded board), or /api/status was
      unreachable / unparseable after retries
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.watchdog_contract_coverage import evaluate_coverage_map  # noqa: E402
from scripts.watchdog_freshness import _read_freshness  # noqa: E402
from src.api.source_health_alerts import load_thresholds  # noqa: E402

_ATTEMPTS = 6
_SLEEP_SECONDS = 5
_TIMEOUT_SECONDS = 20

# A backend restart deliberately launches the startup scrape three seconds
# after the cached board is primed. The served board can therefore be
# temporarily behind the fresh checkout CSVs while that scrape is still
# rebuilding the canonical contract. A one-shot coverage check turned that
# recovery window into a deploy failure and triggered rollback while the
# process was still recovering. Retry ONLY while the server reports an
# active, non-stalled scrape. Idle/stalled degradation still fails
# immediately. 61 x 5s = at most five minutes of bounded recovery time.
_COVERAGE_WAIT_ATTEMPTS = 61
_COVERAGE_WAIT_SLEEP_SECONDS = 5


def _fetch_status(base_url: str) -> dict | None:
    """GET ``<base>/api/status`` with retries (tolerates the brief
    window after a service restart before priming completes)."""
    url = base_url.rstrip("/") + "/api/status"
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "verify-live-source-coverage"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                reason = f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001
            reason = repr(exc)
        if attempt < _ATTEMPTS:
            print(
                f"attempt {attempt}/{_ATTEMPTS}: {url} not ready "
                f"({reason}); retrying in {_SLEEP_SECONDS}s"
            )
            time.sleep(_SLEEP_SECONDS)
    print(
        f"::error title=Live status unreachable::{url} did not return a "
        f"parseable 200 after {_ATTEMPTS} attempts."
    )
    return None


def _coverage_result(status: dict):
    """Evaluate one /api/status payload against checkout freshness truth.

    Returns (violations, ok, skipped). violations=None means the server
    has not published a served_source_coverage map yet.
    """
    cov = status.get("served_source_coverage")
    if not isinstance(cov, dict) or not cov:
        return None, [], []

    cov_int = {str(k): int(v) for k, v in cov.items()}
    freshness = _read_freshness()
    thresholds = load_thresholds()
    return evaluate_coverage_map(cov_int, freshness, thresholds)


def _recovering_scrape(status: dict) -> bool:
    """True only for an active scrape that still has a chance to republish."""
    return bool(status.get("running")) and not bool(
        status.get("stalled") or status.get("hung")
    )


def _print_coverage_failure(violations) -> None:
    if violations is None:
        print(
            "::error title=Degraded board::/api/status reported no "
            "served_source_coverage — the live board is not enriched "
            "(serving the bare legacy export, not the full registered-source "
            "blend)."
        )
        return

    for key, count in violations:
        print(
            f"::error title=Source absent from LIVE board: {key}::"
            f"{key} is fresh in the checkout but only {count} player(s) "
            f"carry it in the SERVED board (/api/status "
            f"served_source_coverage). The live process is serving a "
            f"degraded board."
        )


def main() -> int:
    base_url = (
        sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DEPLOY_VERIFY_BASE_URL", "")
    ).strip()
    if not base_url:
        print(
            "::error title=No base URL::Pass the server base URL as "
            "argv[1] or set DEPLOY_VERIFY_BASE_URL."
        )
        return 1

    last_status: dict = {}
    last_violations = None
    for coverage_attempt in range(1, _COVERAGE_WAIT_ATTEMPTS + 1):
        status = _fetch_status(base_url)
        if status is None:
            return 1
        last_status = status

        violations, ok, skipped = _coverage_result(status)
        last_violations = violations
        if violations == []:
            print(
                f"ok: live board carries {len(ok)} registered source(s); "
                f"0 fresh-but-absent ({len(skipped)} skipped: stale/empty)"
            )
            return 0

        if not _recovering_scrape(status):
            break

        if coverage_attempt < _COVERAGE_WAIT_ATTEMPTS:
            missing_label = (
                "coverage map not published yet"
                if violations is None
                else f"{len(violations)} fresh source(s) not yet republished"
            )
            print(
                f"recovery {coverage_attempt}/{_COVERAGE_WAIT_ATTEMPTS}: "
                f"{missing_label}; startup/scheduled scrape is still active "
                f"(step={status.get('current_step')!r}, "
                f"source={status.get('current_source')!r}). "
                f"Waiting {_COVERAGE_WAIT_SLEEP_SECONDS}s before re-check."
            )
            time.sleep(_COVERAGE_WAIT_SLEEP_SECONDS)

    _print_coverage_failure(last_violations)
    if last_violations is None:
        print(
            "\nfail: served board never published source coverage after the "
            "bounded recovery window."
        )
    else:
        print(
            f"\nfail: {len(last_violations)} fresh source(s) missing from the "
            f"LIVE board: {', '.join(k for k, _ in last_violations)}"
        )
    if _recovering_scrape(last_status):
        print(
            "The scrape remained active for the entire bounded recovery "
            "window; refusing to call this deployment healthy."
        )
    else:
        print(
            "The board is degraded while no recoverable scrape is active; "
            "failing immediately instead of hiding a persistent source loss."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
