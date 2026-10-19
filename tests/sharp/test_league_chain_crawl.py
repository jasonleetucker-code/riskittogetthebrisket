"""The budgeted league-chain (maturity) pass, G6.  Every Sleeper call is faked;
synthetic league ids only.  Pins: OFF at budget 0, the ONE walker / ONE store /
capture owner, completed hops answered from the store at zero calls, the 429
and consecutive-failure stops, the non-dynasty predecessor recorded so the
maturity it ends is EXACT, and the CLI pass wiring."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

from src.intel import ledger
from src.intel import league_filter as lf
from src.sharp import league_chain_crawl as lcc
from src.sharp import league_format_capture as lfc

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def db(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    path = tmp_path / "intel" / ledger.LEDGER_FILENAME
    conn = ledger.connect(path)
    for i, lid in enumerate(("SYN-T26", "SYN-U26")):
        conn.execute(
            "INSERT INTO asset_movements (movement_id, tx_id, league_id, tx_type, asset_id, "
            "asset_type, action, user_id, ts, ingested_ms) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"m{i}", f"t{i}", lid, "trade", "p1", "player", "add", "u1", 1, 1),
        )
    conn.commit()
    conn.close()
    yield path
    ledger.reset_setup_cache()


def lg(lid, season, prev, *, type_=2, status="complete"):
    return {
        "league_id": lid,
        "season": str(season),
        "status": status,
        "previous_league_id": prev,
        "settings": {"type": type_, "best_ball": 0},
    }


LEAGUES = {
    "SYN-T26": lg("SYN-T26", 2026, "SYN-T25", status="in_season"),
    "SYN-T25": lg("SYN-T25", 2025, "SYN-T24"),
    "SYN-T24": lg("SYN-T24", 2024, "SYN-T23"),
    "SYN-T23": lg("SYN-T23", 2023, "0"),
    "SYN-U26": lg("SYN-U26", 2026, "SYN-U25", status="in_season"),
    "SYN-U25": lg("SYN-U25", 2025, "SYN-U24", type_=0),  # redraft predecessor
}


class Fake:
    def __init__(self, leagues=None, rate_limit_on=None, error_on=()):
        self.leagues = dict(leagues or LEAGUES)
        self.rate_limit_on = rate_limit_on
        self.error_on = set(error_on)
        self.calls: list[str] = []

    def __call__(self, url):
        lid = url.rsplit("/", 1)[-1]
        self.calls.append(lid)
        if lid == self.rate_limit_on:
            raise lfc.RateLimited(url)
        if lid in self.error_on:
            return lfc.FETCH_ERROR
        return self.leagues.get(lid)


def _chain(db):
    conn = ledger.connect(db)
    try:
        return ledger.load_league_chain(conn)
    finally:
        conn.close()


def test_off_by_default(db):
    assert lcc.DEFAULT_BUDGET == 0
    fake = Fake()
    res = lcc.crawl_league_chains(http_get=fake, ledger_path=db)
    assert res.stopped_reason == "chain_budget_zero" and fake.calls == []


def test_walks_trade_bearing_leagues_and_resolves_maturity(db):
    fake = Fake()
    res = lcc.crawl_league_chains(budget=50, http_get=fake, ledger_path=db, sleep_s=0)
    assert res.targets == 2 and res.chains_walked == 2
    chain = _chain(db)
    t = lf.resolve_league_maturity("SYN-T26", chain)
    assert (t.completed_seasons, t.state, t.cohort) == (3, lf.MATURITY_EXACT, lf.COHORT_A)
    # The redraft predecessor was recorded, so the walk ending there is EXACT.
    assert "SYN-U25" in chain
    u = lf.resolve_league_maturity("SYN-U26", chain)
    assert (u.completed_seasons, u.state, u.stop_reason) == (
        0,
        lf.MATURITY_EXACT,
        lf.STOP_NON_DYNASTY,
    )
    assert res.hops_fetched == 6 and res.calls_used == 6
    assert "SYN" not in repr(res.to_dict())


def test_completed_hops_cost_zero_calls_on_the_next_run(db):
    lcc.crawl_league_chains(budget=50, http_get=Fake(), ledger_path=db, sleep_s=0)
    # Both are now exact -> nothing is due; force one back in to prove the
    # frozen-hop shortcut: only the in-progress season is re-fetched.
    fake = Fake()
    res = lcc.crawl_league_chains(
        league_ids=[], budget=50, http_get=fake, ledger_path=db, sleep_s=0
    )
    assert res.targets == 0 and fake.calls == []
    conn = ledger.connect(db)
    conn.execute("DELETE FROM league_season_chain WHERE league_id = 'SYN-T24'")
    conn.commit()
    conn.close()
    fake = Fake()
    res = lcc.crawl_league_chains(budget=50, http_get=fake, ledger_path=db, sleep_s=0)
    assert fake.calls == ["SYN-T26", "SYN-T24"]  # T25 (complete) from the store
    assert res.hops_from_store >= 1


def test_budget_is_never_exceeded(db):
    fake = Fake()
    res = lcc.crawl_league_chains(budget=2, http_get=fake, ledger_path=db, sleep_s=0)
    assert res.calls_used == 2 and len(fake.calls) == 2
    assert res.stopped_reason == "budget_exhausted" and res.leagues_pending == 1


def test_rate_limit_stops_the_pass(db):
    fake = Fake(rate_limit_on="SYN-T25")
    res = lcc.crawl_league_chains(budget=50, http_get=fake, ledger_path=db, sleep_s=0)
    assert res.stopped_reason == "rate_limited"
    assert "SYN-U26" not in fake.calls  # the next chain never started


def test_consecutive_failures_stop_the_pass(db, monkeypatch):
    monkeypatch.setattr(lcc, "MAX_CONSECUTIVE_FAILURES", 2)
    fake = Fake(error_on={"SYN-T26", "SYN-U26"})
    res = lcc.crawl_league_chains(budget=50, http_get=fake, ledger_path=db, sleep_s=0)
    assert res.stopped_reason == "consecutive_fetch_failures"


def test_a_payload_naming_another_league_proves_nothing(db):
    leagues = dict(LEAGUES)
    leagues["SYN-T26"] = lg("SYN-OTHER", 2026, "0")
    res = lcc.crawl_league_chains(
        league_ids=["SYN-T26"], budget=10, http_get=Fake(leagues), ledger_path=db, sleep_s=0
    )
    assert "SYN-OTHER" not in _chain(db) and res.hops_fetched == 0


def test_uses_the_one_walker_and_the_one_store():
    src = (REPO / "src/sharp/league_chain_crawl.py").read_text(encoding="utf-8")
    assert "iter_league_chain" in src and "record_league_chain_hop" in src
    tree = ast.parse(src)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.While)]
    assert not loops, "the chain pass must not hand-roll a previous_league_id loop"
    assert "INSERT" not in src.upper().replace("INSERT INTO LEAGUE_SEASON_CHAIN", "")


def _load_cli():
    spec = importlib.util.spec_from_file_location(
        "crawl_sharp_transactions", REPO / "scripts/crawl_sharp_transactions.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_pass_is_skipped_at_zero_and_after_a_429():
    cli = _load_cli()
    calls = []

    def spy(**kw):
        calls.append(kw)
        return lcc.ChainCrawlResult()

    assert cli._crawl_league_chains(budget=0, crawl=spy)["skipped"] == "chain_budget_zero"
    out = cli._crawl_league_chains(budget=5, stopped_reasons=("rate_limited",), crawl=spy)
    assert out["skipped"] == "earlier_pass_rate_limited" and calls == []
    cli._crawl_league_chains(budget=5, stopped_reasons=(None, None), crawl=spy)
    assert calls == [{"league_ids": None, "budget": 5}]
