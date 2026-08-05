""""Scrape ran" and "scrape published" are different facts.

R13 / W23-F002 / W23-F003 / W23-F001 / W23-F006.

* The partial-scrape guard blocked on ``site_count < total_sites / 2``.
  ``sites`` carries two entries on the live snapshot, so the predicate
  was ``site_count < 1.0`` — it fired only on TOTAL loss.  Losing one of
  the two anchor markets (KTC: the TE++ basis anchor and a pick market;
  IDPTradeCalc: the IDP backbone) promoted silently.
* On the blocked branch the run was recorded with
  ``_mark_scrape_success``: same event name, same ``last_success_at``,
  same ``outcome: "success"`` in ``scrape_history``, ``scrape_count``
  incremented, ``error`` cleared.  ``_scrape_success_rate_24h()``
  returned rate 1.0 through the one outcome the guard exists to prevent.
* ``_check_scrape_rate`` read ``scrape_success_rate_24h`` from a payload
  that never carried it, and the payload that DOES carry it holds a
  dict, which ``float()`` rejected.  Both routes to the alert were
  closed; the only shape that alerted was one no caller produced.
* ``data_age`` was measured from ``loadedAt`` — when this process read
  the file.  Measured live: uptime_seconds 7401 == data_age_seconds
  7401, while the snapshot's own ``sourceRunSummary.finishedAt`` made
  the real age 14,117 s.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import server as srv
from src.api.ops_alerts import _check_scrape_rate


@pytest.fixture(autouse=True)
def _clean_scrape_state():
    history = list(srv.scrape_history)
    status = dict(srv.scrape_status)
    metrics = dict(srv._metrics)
    source = dict(srv.latest_data_source)
    srv.scrape_history.clear()
    yield
    srv.scrape_history.clear()
    srv.scrape_history.extend(history)
    srv.scrape_status.clear()
    srv.scrape_status.update(status)
    srv._metrics.clear()
    srv._metrics.update(metrics)
    srv.latest_data_source.clear()
    srv.latest_data_source.update(source)


# ── The guard's denominator ──────────────────────────────────────────


def _sites(*pairs):
    return {"sites": [{"key": k, "playerCount": n} for k, n in pairs]}


def test_one_dead_anchor_market_blocks_promotion():
    """The live shape: two sites, one produced nothing."""
    reason = srv._partial_scrape_block_reason(_sites(("ktc", 0), ("idpTradeCalc", 900)))
    assert reason is not None
    assert "ktc" in reason


def test_a_healthy_run_promotes():
    assert srv._partial_scrape_block_reason(_sites(("ktc", 500), ("idpTradeCalc", 900))) is None


def test_total_loss_still_blocks():
    assert srv._partial_scrape_block_reason(_sites(("ktc", 0), ("idpTradeCalc", 0))) is not None


def test_ratio_rule_survives_for_larger_site_sets():
    reason = srv._partial_scrape_block_reason(
        _sites(("a", 10), ("b", 10), ("c", 10), ("d", 0), ("e", 0), ("f", 0))
    )
    assert reason is not None


def test_no_sites_block_is_not_invented():
    """An empty/absent sites list is unknown, not a failure — the caller
    has nothing to judge."""
    assert srv._partial_scrape_block_reason({"sites": []}) is None
    assert srv._partial_scrape_block_reason({}) is None
    assert srv._partial_scrape_block_reason(None) is None


# ── What a blocked run records ───────────────────────────────────────


def test_blocked_run_is_not_recorded_as_a_success():
    srv.scrape_status["last_success_at"] = None
    srv._mark_scrape_blocked(12.0, 800, 1, 2, "ktc returned zero rows")

    assert srv.scrape_status["last_success_at"] is None
    assert srv.scrape_status["current_step"] == "blocked"
    assert srv.scrape_status["error"]
    assert "blocked" in srv.scrape_status["error"]
    assert srv.scrape_history[-1]["outcome"] == "blocked"
    # The run DID happen, so last_scrape moves.
    assert srv.scrape_status["last_scrape"]


def test_blocked_run_does_not_count_toward_the_success_rate():
    srv._mark_scrape_blocked(1.0, 0, 0, 2, "ktc returned zero rows")
    rate = srv._scrape_success_rate_24h()
    assert rate["total"] == 1
    assert rate["success"] == 0
    assert rate["blocked"] == 1
    assert rate["rate"] == 0.0


def test_blocked_run_has_its_own_metrics_counter():
    before = dict(srv._metrics)
    srv._mark_scrape_blocked(1.0, 0, 0, 2, "reason")
    assert srv._metrics["scrape_blocked"] == before.get("scrape_blocked", 0) + 1
    assert srv._metrics["scrape_total"] == before.get("scrape_total", 0) + 1
    # A block is not an exception.
    assert srv._metrics.get("scrape_failures", 0) == before.get("scrape_failures", 0)


# ── The alert that could never fire ──────────────────────────────────


def _rate_dict(success: int, total: int) -> dict:
    return {
        "total": total,
        "success": success,
        "failure": total - success,
        "blocked": 0,
        "rate": round(success / total, 2) if total else None,
    }


def test_scrape_rate_alert_fires_on_the_production_dict_shape():
    alert = _check_scrape_rate({"scrape_success_rate_24h": _rate_dict(1, 10)})
    assert alert is not None
    assert alert.category == "scrape_failure"
    assert alert.severity == "critical"


def test_scrape_rate_alert_still_accepts_a_bare_float():
    assert _check_scrape_rate({"scrape_success_rate_24h": 0.1}) is not None


def test_scrape_rate_alert_is_quiet_on_a_healthy_rate_and_on_no_runs():
    assert _check_scrape_rate({"scrape_success_rate_24h": _rate_dict(9, 10)}) is None
    assert _check_scrape_rate({"scrape_success_rate_24h": _rate_dict(0, 0)}) is None
    assert _check_scrape_rate({}) is None


def test_scrape_rate_alert_needs_a_sample_before_it_shouts():
    """One failed run out of one is 0% and says nothing; freshness owns
    the 'nothing is running' case."""
    assert _check_scrape_rate({"scrape_success_rate_24h": _rate_dict(0, 1)}) is None


def test_the_sweep_hands_the_checker_a_payload_that_carries_the_rate():
    """The check read a key `_scrape_status_payload()` cannot contain."""
    import ast
    import inspect

    src = inspect.getsource(srv.run_signal_alerts)
    tree = ast.parse(src.strip())
    merged = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Dict)
        and any(
            isinstance(k, ast.Constant) and k.value == "scrape_success_rate_24h"
            for k in node.keys
            if k is not None
        )
    ]
    assert merged, "the ops sweep must merge the 24h rate into status_payload"


# ── Data age is the age of the DATA ──────────────────────────────────


def _payload(finished_at: str | None = None, scrape_ts: str | None = None) -> dict:
    payload: dict = {}
    if finished_at:
        payload["settings"] = {"sourceRunSummary": {"finishedAt": finished_at}}
    if scrape_ts:
        payload["scrapeTimestamp"] = scrape_ts
    return payload


def test_data_age_measures_from_the_scrape_not_the_load():
    finished = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
    srv._set_latest_data_source("disk_cache", "x", payload=_payload(finished_at=finished))
    age, basis = srv._data_age()
    assert basis == "scrape_finished"
    assert 5.9 * 3600 < age < 6.1 * 3600
    # ...and it does NOT restart from zero just because we loaded it now.
    assert srv.latest_data_source["loadedAt"] != srv.latest_data_source["producedAt"]


def test_data_age_falls_back_to_the_naive_scrape_timestamp():
    stamp = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(tzinfo=None).isoformat()
    srv._set_latest_data_source("disk_cache", "x", payload=_payload(scrape_ts=stamp))
    age, basis = srv._data_age()
    assert basis == "scrape_timestamp"
    assert 2.9 * 3600 < age < 3.1 * 3600


def test_data_age_names_the_fallback_instead_of_pretending():
    """A payload with no production stamp still yields an age — but the
    basis says it is the load time, so nobody reads it as scrape age."""
    srv._set_latest_data_source("disk_cache", "x", payload={})
    age, basis = srv._data_age()
    assert basis == "file_loaded"
    assert age is not None and age < 5


def test_health_and_metrics_stamp_the_basis():
    import inspect

    for fn in (srv.get_health, srv.get_metrics):
        assert "data_age_basis" in inspect.getsource(fn)
