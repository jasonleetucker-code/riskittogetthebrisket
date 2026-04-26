"""Dynasty Scraper Sleeper-side candidate scoring.

When the Sleeper /v1/players/nfl response contains multiple entries
that clean to the same name (e.g. two "Josh Allen" rows: an active
QB and a long-retired offensive guard), ``_candidate_score`` is the
tiebreaker that picks which Sleeper ID gets stamped onto the player
row. The Sleeper ID flows through the data contract to
``frontend/lib/player-images.js`` to build the headshot CDN URL —
so a wrong pick here ships the wrong avatar.

Sleeper's ``search_rank`` is "lower is better" (1 = most popular)
and uses ``9999999`` as a sentinel for irrelevant/inactive players.
A naive ``score += search_rank * 0.01`` formula treats the sentinel
as ~+100k points and lets the inactive homonym beat the active
star, which is exactly the bug this test guards against.

We mirror the scraper's scoring function rather than importing
``Dynasty Scraper.py`` directly (it has a top-level Playwright
import that isn't available in CI).
"""
from __future__ import annotations


def _pos_family(pos: str) -> str:
    up = str(pos or "").upper()
    if up in {"DE", "DT", "EDGE", "NT"}:
        return "DL"
    if up in {"CB", "S", "FS", "SS"}:
        return "DB"
    if up in {"OLB", "ILB"}:
        return "LB"
    return up


def _candidate_score(cand: dict, preferred_pos: str = "") -> float:
    score = 0.0
    if cand.get("active"):
        score += 10000.0
    if cand.get("team"):
        score += 500.0
    sr = cand.get("search_rank") or 0
    if 0 < sr < 9999999:
        score += max(0.0, 1000.0 - float(sr))
    score += cand.get("years_exp", 0) * 2.0
    if preferred_pos:
        if _pos_family(cand.get("pos")) == _pos_family(preferred_pos):
            score += 300.0
    return score


def _pick(candidates: list[dict], preferred_pos: str = "") -> dict:
    return max(candidates, key=lambda c: _candidate_score(c, preferred_pos))


JOSH_ALLEN_QB = {
    "id": "4984",
    "name": "Josh Allen",
    "pos": "QB",
    "active": 1,
    "team": "BUF",
    "search_rank": 1.0,
    "years_exp": 8,
}

JOSH_ALLEN_RETIRED_G = {
    "id": "2212",
    "name": "Josh Allen",
    "pos": "G",
    "active": 0,
    "team": "",
    "search_rank": 9999999.0,
    "years_exp": 8,
}


def test_active_qb_beats_inactive_homonym_without_position_hint():
    # Without a preferred_pos, the active QB with a team must still
    # win — the search_rank=9999999 sentinel on the inactive guard
    # must not flood the score.
    assert _pick([JOSH_ALLEN_QB, JOSH_ALLEN_RETIRED_G])["id"] == "4984"


def test_active_qb_beats_inactive_homonym_with_qb_hint():
    assert _pick([JOSH_ALLEN_QB, JOSH_ALLEN_RETIRED_G], preferred_pos="QB")["id"] == "4984"


def test_search_rank_sentinel_is_ignored():
    # Two otherwise-identical inactive candidates: the one with a
    # real (low) search_rank should win over the 9999999 sentinel.
    a = {"id": "A", "active": 0, "team": "", "search_rank": 50.0, "years_exp": 0, "pos": "WR"}
    b = {"id": "B", "active": 0, "team": "", "search_rank": 9999999.0, "years_exp": 0, "pos": "WR"}
    assert _pick([a, b])["id"] == "A"


def test_position_hint_breaks_ties_between_active_homonyms():
    # DJ Turner WR (CIN) vs DJ Turner II CB (ARI): both active,
    # both rostered. With a position hint we should land on the
    # right family.
    wr = {"id": "WR1", "active": 1, "team": "CIN", "search_rank": 250.0, "years_exp": 2, "pos": "WR"}
    cb = {"id": "CB1", "active": 1, "team": "ARI", "search_rank": 300.0, "years_exp": 2, "pos": "CB"}
    assert _pick([wr, cb], preferred_pos="WR")["id"] == "WR1"
    assert _pick([wr, cb], preferred_pos="CB")["id"] == "CB1"
