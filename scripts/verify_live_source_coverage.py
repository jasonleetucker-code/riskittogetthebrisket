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

    status = _fetch_status(base_url)
    if status is None:
        return 1

    cov = status.get("served_source_coverage")
    if not isinstance(cov, dict) or not cov:
        # Empty/absent == the served board carries no per-source
        # coverage == degraded (or a server too old to expose it,
        # which post-deploy is itself the regression).
        print(
            "::error title=Degraded board::/api/status reported no "
            "served_source_coverage — the live board is not enriched "
            "(serving the bare legacy export, not the ~11-source "
            "blend).  The process did not re-prime from the CSVs."
        )
        return 1

    cov_int = {str(k): int(v) for k, v in cov.items()}
    freshness = _read_freshness()
    thresholds = load_thresholds()
    violations, ok, skipped = evaluate_coverage_map(cov_int, freshness, thresholds)

    if not violations:
        print(
            f"ok: live board carries {len(ok)} registered source(s); "
            f"0 fresh-but-absent ({len(skipped)} skipped: stale/empty)"
        )
        return 0

    for key, c in violations:
        print(
            f"::error title=Source absent from LIVE board: {key}::"
            f"{key} is fresh in the checkout but only {c} player(s) "
            f"carry it in the SERVED board (/api/status "
            f"served_source_coverage).  The live process is serving a "
            f"degraded board — it did not re-prime / enrich.  A "
            f"`systemctl restart {os.environ.get('SERVICE_NAME', 'dynasty')}` "
            f"on the host forces a re-prime; investigate why the deploy "
            f"restart didn't take."
        )
    print(
        f"\nfail: {len(violations)} fresh source(s) missing from the "
        f"LIVE board: {', '.join(k for k, _ in violations)}"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
