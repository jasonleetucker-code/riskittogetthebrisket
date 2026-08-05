"""``--record-snapshot`` must work from a cold shell, because nothing else can.

The pre-draft board and every team's roster context stop being recoverable the
moment the first rookie pick lands, and no code recovers an observation nobody
made — so this capture is the one step in the whole backtest chain whose window
closes permanently.  It is also the only one that unblocks fitting
``PRICE_DISPERSION_PRIOR``.

It did not work.  ``record_snapshot`` reads ``server.latest_contract_data``,
which is populated inside the FastAPI *lifespan* (``load_from_disk`` then
``_prime_latest_payload``).  Importing the module does not run lifespan, so from
a plain ``python scripts/backtest_perfect_draft.py --record-snapshot`` the
global was always ``None`` and the script exited 2 — "start the server or run a
scrape first" — on a machine whose disk cache was sitting right there.

What is pinned:

* the hydration fallback runs, and a snapshot lands, when the global is unset
  but the on-disk cache has a contract;
* it is a FALLBACK — an already-primed process is not re-primed, so a live
  server's in-memory generation is never swapped underneath it;
* a genuinely empty disk still exits 2, never 0.  "No data" must not read as
  "captured", which is the same reason the corpus check exits 2 rather than 0.
"""

from __future__ import annotations

import sys
import types

import pytest

from scripts.backtest_perfect_draft import EXIT_OK, EXIT_SKIPPED, record_snapshot

_CONTRACT = {"meta": {"leagueKey": "dynasty_main"}}


def _fake_server(*, primed, on_disk):
    """A stand-in for the real ``server`` module.

    Deliberately not the real one: importing it pulls the whole app in, and the
    behaviour under test is entirely about which of two globals is populated
    and when.
    """
    mod = types.ModuleType("server")
    mod.latest_contract_data = _CONTRACT if primed else None
    mod.DRAFT_TOTAL_BUDGET = 1200
    mod._KTC_TOTAL_PICKS = 72
    mod.prime_calls = []

    def load_from_disk():
        return dict(on_disk) if on_disk else None

    def _prime_latest_payload(data, *, is_fresh_scrape=False):
        mod.prime_calls.append(data)
        mod.latest_contract_data = data

    def _our_rookie_pool(_n):
        return [{"name": "Jeremiyah Love", "pos": "RB", "value": 7798.0}]

    def _rookie_dollars_from_values(values, _budget):
        return [135 for _ in values]

    mod.load_from_disk = load_from_disk
    mod._prime_latest_payload = _prime_latest_payload
    mod._our_rookie_pool = _our_rookie_pool
    mod._rookie_dollars_from_values = _rookie_dollars_from_values
    return mod


@pytest.fixture
def fake_context(monkeypatch):
    """Stub ``src.draft.context`` so the test isolates the hydration path."""
    ctx = types.ModuleType("src.draft.context")
    ctx.CONTEXT_VERSION = "test.v1"
    ctx.list_draft_teams = lambda _c: [{"name": "Alpha"}]
    ctx.build_roster_context = lambda _c, _k, team_name=None: {
        "team": {"name": team_name},
        "openRosterSpots": 5,
    }
    monkeypatch.setitem(sys.modules, "src.draft.context", ctx)
    return ctx


def test_a_cold_process_hydrates_from_disk_and_captures(tmp_path, monkeypatch, fake_context):
    """The regression: unset global + populated disk must still capture."""
    server = _fake_server(primed=False, on_disk=_CONTRACT)
    monkeypatch.setitem(sys.modules, "server", server)

    assert record_snapshot(tmp_path, None) == EXIT_OK

    written = list(tmp_path.glob("*-pre.json"))
    assert len(written) == 1, "the capture is the whole point; it must land on disk"
    assert server.prime_calls == [_CONTRACT], "hydration should run exactly once"


def test_an_already_primed_process_is_not_re_primed(tmp_path, monkeypatch, fake_context):
    """It is a fallback, not an unconditional reload.

    Re-priming a live server would swap its in-memory generation for whatever
    happens to be on disk — a different contract from the one whose board is
    being captured.
    """
    server = _fake_server(primed=True, on_disk={"meta": {"leagueKey": "stale_from_disk"}})
    monkeypatch.setitem(sys.modules, "server", server)

    assert record_snapshot(tmp_path, None) == EXIT_OK
    assert server.prime_calls == [], "a primed process must not be re-primed"
    assert server.latest_contract_data is _CONTRACT


def test_an_empty_disk_still_skips_rather_than_claiming_success(
    tmp_path, monkeypatch, fake_context
):
    """Exit 2, not 0 — "nothing to capture" must not read as "captured"."""
    server = _fake_server(primed=False, on_disk=None)
    monkeypatch.setitem(sys.modules, "server", server)

    assert record_snapshot(tmp_path, None) == EXIT_SKIPPED
    assert list(tmp_path.glob("*-pre.json")) == []
