"""An interactive BDVM request may never start a remote nflverse ingest.

THE DEFECT, reproduced.

PR #938 repaired the E2E Safety Net and proved a hidden architecture defect
underneath it.  ``journey-trade.spec.js:96`` did not fail because the page was
slow — the page had already rendered a terminal error::

    Rankings unavailable — Failed to load dynasty data: 503
    reason: backend_idle_timeout   timeoutMs: 4000

The Next data bridge aborts when the backend streams no chunk for >4s.  At
failure time the request-serving Python process was doing BDVM/nflverse work
that began at the FIRST BDVM values request: ~112,450 weekly-stat rows and
~157,615 snap-count rows parsed, plus schedule downloads.

``run_in_threadpool`` is not the protection and never was.  Parsing ~270,000
CSV rows is CPU/GIL-heavy, so a worker thread in the same uvicorn process
starves ``/api/data``'s response streaming just as effectively as blocking the
event loop would.

The request path, as measured on ``main`` at 547e51bc6::

    get_bdvm_values                       src/api/bdvm_api.py:162
      ├─ _actuals_for   :120 → actuals.py:170  → ingest.fetch_weekly_stats
      ├─ _context_for   :63  → context.py:199  → ingest.fetch_id_map
      │                                        → ingest.fetch_weekly_stats  (6 seasons)
      │                                        → ingest.fetch_snap_counts   (6 seasons)
      └─ _schedule_for  :79  → schedule.py:46  → urllib.request.urlopen

Note ``_actuals_for`` is already gated on a projection snapshot existing, but
``_context_for`` and ``_schedule_for`` are not — they run on every values-cache
miss regardless.

THE RULE THIS FILE PINS.  The refresh process decides WHEN TO FETCH.  The
request process decides only WHETHER A MATERIALISED ARTIFACT EXISTS, and
reports its freshness truthfully.  An interactive request reads what is on
disk or degrades honestly; it never crawls.
"""

from __future__ import annotations

import unittest
import urllib.request
from typing import Any
from unittest import mock

from src.api import bdvm_api


def _contract() -> dict[str, Any]:
    """A contract complete enough for ``run_valuation`` to reach its own logic.

    ``rosterPositions`` / ``leagueSettings`` are required — without them
    ``league_config`` raises before the prerequisites are even reported, and
    the test would fail for a fixture reason rather than the defect.
    """
    return {
        "generatedAt": "2026-08-20T00:00:00Z",
        "currentDraftYear": 2026,
        "playersArray": [],
        "sleeper": {
            "scoringSettings": {"rec": 1.0, "pass_td": 4.0},
            "rosterPositions": ["QB", "WR", "WR", "LB", "BN", "BN"],
            "leagueSettings": {"num_teams": 12},
        },
    }


class _NetworkRecorder:
    """Records every remote-fetch attempt instead of performing one.

    Returning empty rather than raising is deliberate: the test then reports
    *which* owners were called, rather than dying on whichever happened to run
    first and hiding the rest.
    """

    def __init__(self) -> None:
        self.attempts: list[str] = []

    def ingest_fetch(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.attempts.append(f"ingest._try_fetch_with_fallback(label={kwargs.get('label')})")
        return []

    def urlopen(self, req: Any, *args: Any, **kwargs: Any):
        url = getattr(req, "full_url", None) or str(req)
        self.attempts.append(f"urllib.request.urlopen({url})")
        raise AssertionError("network disabled in this test")


class TestInteractiveBdvmRequestDoesNoRemoteIngest(unittest.TestCase):
    """TEST A — the cold interactive request must not fetch remotely."""

    def setUp(self) -> None:
        bdvm_api.reset_cache()
        self.addCleanup(bdvm_api.reset_cache)
        self.recorder = _NetworkRecorder()

    def _run_cold_request(self, tmp_cache_dir) -> dict[str, Any]:
        """Serve one BDVM request with a COLD cache and no network.

        Both remote owners are intercepted at the lowest level each one has:
        ``_try_fetch_with_fallback`` is the single choke point for everything
        under ``src.nfl_data.ingest``, and ``urllib.request.urlopen`` catches
        ``bdvm/schedule.py``, which bypasses that owner entirely.
        """
        from src.nfl_data import cache as nfl_cache
        from src.nfl_data import ingest

        with (
            mock.patch.object(
                ingest, "_try_fetch_with_fallback", side_effect=self.recorder.ingest_fetch
            ),
            mock.patch.object(urllib.request, "urlopen", side_effect=self.recorder.urlopen),
            # Cold: an empty cache directory, so nothing can be served locally.
            mock.patch.object(nfl_cache, "_default_cache_dir", return_value=tmp_cache_dir),
        ):
            return bdvm_api.get_bdvm_values(_contract(), "dynasty_main")

    def test_a_cold_request_attempts_no_remote_fetch(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            payload = self._run_cold_request(Path(tmp) / "cold_cache")

        self.assertEqual(
            self.recorder.attempts,
            [],
            "an interactive BDVM request started a remote nflverse fetch:\n  "
            + "\n  ".join(self.recorder.attempts),
        )
        # Non-vacuity: the request must still have produced a payload. A repair
        # that made this test pass by refusing to serve anything is not a repair.
        self.assertIsInstance(payload, dict)
        self.assertIn("status", payload)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
