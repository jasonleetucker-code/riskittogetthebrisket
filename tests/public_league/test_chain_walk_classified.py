"""``walk_league_chain_status`` with an injected CLASSIFIED league fetcher
(Manager Intelligence Batch E's budgeted career walk), and the classified
winners-bracket read.  No network."""

from __future__ import annotations

from src.public_league import sleeper_client as sc


def _leagues() -> dict[str, dict]:
    return {
        "A": {"league_id": "A", "previous_league_id": "B", "settings": {"type": 2}},
        "B": {"league_id": "B", "previous_league_id": "C", "settings": {"type": 2}},
        "C": {"league_id": "C", "previous_league_id": "0", "settings": {"type": 2}},
    }


def _fetcher(fail: dict[str, str] | None = None):
    leagues = _leagues()
    calls: list[str] = []

    def fetch(lid: str):
        calls.append(lid)
        if fail and lid in fail:
            return fail[lid], None
        return (sc.FETCH_OK, leagues[lid]) if lid in leagues else (sc.FETCH_NOT_FOUND, None)

    return fetch, calls


def test_injected_fetch_walks_the_whole_chain():
    fetch, calls = _fetcher()
    chain, cov = sc.walk_league_chain_status("A", 10, fetch_league_fn=fetch)
    assert [lg["league_id"] for lg in chain] == ["A", "B", "C"]
    assert cov["state"] == sc.CHAIN_COMPLETE and calls == ["A", "B", "C"]


def test_injected_fetch_names_a_rate_limited_link():
    fetch, _ = _fetcher({"B": sc.FETCH_RATE_LIMITED})
    chain, cov = sc.walk_league_chain_status("A", 10, fetch_league_fn=fetch)
    assert len(chain) == 1
    assert cov == {
        "state": sc.CHAIN_UNVERIFIED,
        "reason": "predecessor_rate_limited",
        "seasonsWalked": 1,
        "cap": 10,
        "stoppedAtLeagueId": "B",
    }


def test_injected_fetch_names_budget_and_start_failures():
    fetch, _ = _fetcher({"B": "budget"})
    assert sc.walk_league_chain_status("A", 10, fetch_league_fn=fetch)[1]["reason"] == (
        "predecessor_budget_exhausted"
    )
    fetch, _ = _fetcher({"A": sc.FETCH_ERROR})
    assert sc.walk_league_chain_status("A", 10, fetch_league_fn=fetch)[1]["reason"] == (
        "start_fetch_failed"
    )


def test_default_path_is_unchanged(monkeypatch):
    leagues = _leagues()
    monkeypatch.setattr(sc, "fetch_league", lambda lid: leagues.get(lid))
    chain, cov = sc.walk_league_chain_status("A", 2)
    assert len(chain) == 2 and cov["state"] == sc.CHAIN_TRUNCATED
    monkeypatch.setattr(sc, "fetch_league", lambda lid: None if lid == "B" else leagues[lid])
    assert sc.walk_league_chain_status("A", 9)[1]["reason"] == "predecessor_fetch_failed"


def test_classified_winners_bracket_keeps_a_missing_body_unknown(monkeypatch):
    monkeypatch.setattr(sc, "request_json_classified", lambda url: (sc.FETCH_NOT_FOUND, None))
    assert sc.fetch_winners_bracket_classified("1") == (sc.FETCH_NOT_FOUND, None)
    monkeypatch.setattr(sc, "request_json_classified", lambda url: (sc.FETCH_OK, {"x": 1}))
    assert sc.fetch_winners_bracket_classified("1") == (sc.FETCH_ERROR, None)
    monkeypatch.setattr(sc, "request_json_classified", lambda url: (sc.FETCH_OK, [{"m": 1}]))
    assert sc.fetch_winners_bracket_classified("1") == (sc.FETCH_OK, [{"m": 1}])
