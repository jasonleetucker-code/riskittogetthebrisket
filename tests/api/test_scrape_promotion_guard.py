"""The partial-scrape guard, and what a refused scrape is recorded as.

Two audit findings meet here, and they compounded:

* **O-3** — the guard's denominator is ``result["sites"]``, populated
  from the legacy in-scraper SITES dict.  On live data that list has
  exactly TWO entries against a 21-source registry, so "fewer than half
  the sites" degenerates to "fewer than one of two": it blocked only on
  total loss.  Lose KTC and keep IDPTradeCalc and the board published
  without its own cross-market anchor.
* **O-2** — when the guard *did* fire it called ``_mark_scrape_success``,
  filing the refusal as a success.  So the 24h success rate read 100%
  while every scrape was being thrown away.

Together: the guard rarely fired, and when it did the metric that would
have shown it was inverted.
"""

from __future__ import annotations

import server


class TestMissingExpectedSites:
    """The payload declares its own anchors; the guard should read them."""

    def test_detects_a_missing_anchor(self) -> None:
        result = {
            "coverageAudit": {"expectedSites": {"offense": ["ktc"], "idp": ["idpTradeCalc"]}},
            "sites": [{"key": "idpTradeCalc", "playerCount": 900}],
            "siteStats": {"idpTradeCalc": {"count": 1054}},
        }
        assert server._missing_expected_sites(result) == ["ktc"]  # noqa: SLF001

    def test_the_exact_case_the_old_ratio_guard_let_through(self) -> None:
        """KTC dies, IDPTradeCalc survives: 1 of 2 sites, so 1 < 1 is False.

        The old guard published this board. It is missing the anchor
        every offense value is calibrated against.
        """
        result = {
            "coverageAudit": {"expectedSites": {"offense": ["ktc"], "idp": ["idpTradeCalc"]}},
            "sites": [
                {"key": "ktc", "playerCount": 0},
                {"key": "idpTradeCalc", "playerCount": 900},
            ],
        }
        site_count = len([s for s in result["sites"] if s.get("playerCount", 0) > 0])
        total_sites = len(result["sites"])
        # The ratio test alone does NOT block:
        assert not (total_sites > 0 and site_count < total_sites / 2)
        # The anchor check does:
        assert server._missing_expected_sites(result) == ["ktc"]  # noqa: SLF001

    def test_present_but_empty_counts_as_missing(self) -> None:
        """A source that returned zero players did not return."""
        result = {
            "coverageAudit": {"expectedSites": {"idp": ["idpTradeCalc"]}},
            "sites": [{"key": "idpTradeCalc", "playerCount": 0}],
            "siteStats": {"idpTradeCalc": {"count": 0}},
        }
        assert server._missing_expected_sites(result) == ["idpTradeCalc"]  # noqa: SLF001

    def test_all_anchors_present_is_clean(self) -> None:
        result = {
            "coverageAudit": {"expectedSites": {"offense": ["ktc"], "idp": ["idpTradeCalc"]}},
            "sites": [
                {"key": "ktc", "playerCount": 500},
                {"key": "idpTradeCalc", "playerCount": 900},
            ],
        }
        assert server._missing_expected_sites(result) == []  # noqa: SLF001

    def test_malformed_payload_does_not_break_the_scrape(self) -> None:
        """A diagnostic that crashes the scrape is worse than the defect.

        Note the fallback is "no anchors KNOWN missing", not "all
        present" — which is why the ratio test is kept alongside this
        rather than replaced by it.
        """
        for bad in (None, {}, {"coverageAudit": "nonsense"}, {"sites": "nope"}):
            assert server._missing_expected_sites(bad) == []  # noqa: SLF001

    def test_matches_the_real_payload_shape(self) -> None:
        """Guard against the fixture drifting from what the scraper emits."""
        import gzip  # noqa: PLC0415
        import json  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        fixture = (
            Path(__file__).resolve().parents[2]
            / "tests"
            / "fixtures"
            / "golden"
            / "input_export.json.gz"
        )
        payload = json.loads(gzip.decompress(fixture.read_bytes()))
        expected = (payload.get("coverageAudit") or {}).get("expectedSites") or {}
        assert expected, "the real payload must declare expectedSites for the guard to read"
        # A healthy real payload is missing nothing.
        assert server._missing_expected_sites(payload) == []  # noqa: SLF001


class TestBlockedScrapeIsNotASuccess:
    """O-2: a refused scrape must not advance the success record."""

    def _reset(self):
        server.scrape_status.clear()
        server.scrape_history.clear()

    def test_blocked_does_not_advance_last_success_at(self) -> None:
        self._reset()
        server.scrape_status["last_success_at"] = "2020-01-01T00:00:00+00:00"
        server._mark_scrape_blocked("test", 1.0, 100, 1, 2)  # noqa: SLF001
        assert (
            server.scrape_status["last_success_at"] == "2020-01-01T00:00:00+00:00"
        ), "a scrape whose output was refused must not look like a successful one"
        assert server.scrape_status["last_blocked_at"]
        assert server.scrape_status["current_step"] == "blocked"

    def test_blocked_counts_against_the_24h_success_rate(self) -> None:
        """This is the metric the O-1 alert reads.

        Under the old code the guard called _mark_scrape_success, so a
        run of blocked scrapes drove the rate toward 100%.
        """
        self._reset()
        for _ in range(3):
            server._mark_scrape_blocked("test", 1.0, 100, 1, 2)  # noqa: SLF001
        rate = server._scrape_success_rate_24h()  # noqa: SLF001
        assert rate["total"] == 3
        assert rate["success"] == 0
        assert rate["rate"] == 0.0

    def test_a_blocked_run_is_distinguishable_from_a_crash(self) -> None:
        """The scraper worked and the server is healthy — just nothing new."""
        self._reset()
        server._mark_scrape_blocked("test", 1.0, 100, 1, 2)  # noqa: SLF001
        assert server.scrape_status.get("error") is None
        assert server.scrape_history[-1]["outcome"] == "blocked"
