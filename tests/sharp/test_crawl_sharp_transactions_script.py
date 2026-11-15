"""``scripts/crawl_sharp_transactions.py``: the operator-facing summary.

Exit 2 is recorded as success by the systemd unit (``SuccessExitStatus=0 2``),
so it must not be the only thing that says why a pass ended.
"""

from __future__ import annotations

import importlib.util
import json
import logging
from pathlib import Path

import pytest

from src.sharp import transactions

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "crawl_sharp_transactions.py"


@pytest.fixture()
def script():
    spec = importlib.util.spec_from_file_location("crawl_sharp_transactions_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def run(script, monkeypatch, capsys):
    """Run ``main()`` with the crawl stubbed; returns (exit_code, payload, kwargs)."""

    def _run(result, argv):
        seen: dict = {}

        def fake_crawl(*, league_ids=None, **kwargs):
            seen["league_ids"] = league_ids
            seen.update(kwargs)
            return result

        monkeypatch.setattr(transactions, "crawl_transactions", fake_crawl)
        monkeypatch.setattr(transactions, "crawl_coverage", lambda **k: {"stub": True})
        monkeypatch.setattr(
            "sys.argv", ["crawl_sharp_transactions.py", "--format-budget", "0", *argv]
        )
        code = script.main()
        out = capsys.readouterr().out
        return code, json.loads(out), seen

    return _run


def test_a_breaker_stop_is_in_the_summary_and_the_log(run, caplog):
    result = transactions.SharpCrawlResult(
        leagues_considered=6092,
        leagues_fetched=0,
        leagues_pending=6092,
        stopped_reason=transactions.STOPPED_BREAKER_OPEN,
    )
    with caplog.at_level(logging.ERROR, logger="crawl_sharp_transactions"):
        code, payload, _ = run(result, [])
    assert code == 2, "exit-code semantics are unchanged (the unit reads 2 as success)"
    assert payload["stoppedReason"] == "sleeper_breaker_open"
    assert payload["leaguesFetched"] == 0
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("STOPPED EARLY" in m and "circuit breaker" in m for m in messages)


def test_a_budget_stop_does_not_claim_the_breaker(run, caplog):
    result = transactions.SharpCrawlResult(
        leagues_considered=10,
        leagues_fetched=4,
        leagues_pending=6,
        stopped_reason=transactions.STOPPED_BUDGET_EXHAUSTED,
    )
    with caplog.at_level(logging.ERROR, logger="crawl_sharp_transactions"):
        code, payload, _ = run(result, [])
    assert code == 2
    assert payload["stoppedReason"] == "budget_exhausted"
    assert not [r for r in caplog.records if "STOPPED EARLY" in r.getMessage()]


def test_the_default_pass_skips_known_gone_leagues(run):
    _, _, seen = run(transactions.SharpCrawlResult(), [])
    assert seen["skip_gone"] is True
    assert seen["league_ids"] is None


def test_naming_a_league_refetches_it_even_if_gone(run):
    _, _, seen = run(transactions.SharpCrawlResult(), ["--league", "123"])
    assert seen["league_ids"] == ["123"]
    assert seen["skip_gone"] is False
