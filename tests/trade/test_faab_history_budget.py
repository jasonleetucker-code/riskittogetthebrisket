"""An unknown FAAB budget is not $100.

Audit 2026-08-17, batch D.  ``fetch_bid_history`` carried

    budget = int(settings.get("waiver_budget") or 0) or 100

which is verbatim the example this repository's own coercion gate names
in its docstring ("An unknown FAAB budget becomes ``or 100``") — and it
was still live on the path that builds the market priors.

Why it is not a rounding-level problem: ``budget`` is the DENOMINATOR of
every ``bidPct`` row, and ``src/trade/faab_history.py``'s own header
records that this league ran **$1,000 in 2024 and $200** in another
season.  Fabricating 100 therefore does not produce a slightly-wrong
percentage; it produces one wrong by up to 10x, in exactly the
distribution ``summarize_bid_history`` turns into the priors the
recommender bids against.

Two distinct unknowns were both answered with 100:

* the key is ABSENT — the budget is unknown;
* the budget is genuinely ``0`` — a league with no FAAB at all, where
  "percentage of budget" is not a defined quantity.

Neither is 100.  Both mean the season cannot contribute a percentage, so
it is skipped with a logged reason instead of contributing fabricated
ones.
"""

from __future__ import annotations

import pytest

from src.trade import faab_history


def _league(budget, season="2025", previous=None):
    settings = {"num_teams": 12}
    if budget is not None:
        settings["waiver_budget"] = budget
    return {
        "settings": settings,
        "season": season,
        "previous_league_id": previous,
    }


def _install(monkeypatch, leagues, transactions=None, rosters=None):
    """Route ``_get`` at the module's own seam, so the real walk, the
    real filters and the real bidPct arithmetic all execute."""

    def fake_get(url: str):
        if "/transactions/" in url:
            week = int(url.rsplit("/", 1)[-1])
            return (transactions or {}).get(week, [])
        if url.endswith("/rosters"):
            return rosters or []
        league_id = url.rsplit("/", 1)[-1]
        return leagues.get(league_id)

    monkeypatch.setattr(faab_history, "_get", fake_get)


def _add(bid, player="4034", week=1):
    return {
        "type": "waiver",
        "status": "complete",
        "settings": {"waiver_bid": bid},
        "adds": {player: 1},
        "roster_ids": [1],
        "status_updated": 1_700_000_000,
    }


class TestUnknownBudgetIsNotFabricated:
    def test_absent_budget_skips_the_season_rather_than_inventing_100(self, monkeypatch):
        _install(
            monkeypatch,
            {"L1": _league(None)},
            transactions={1: [_add(20)]},
        )
        out = faab_history.fetch_bid_history("L1")
        assert out["seasons"] == [], (
            "a season with an unknown budget must contribute nothing — it used to "
            "contribute bids priced against a fabricated $100 budget"
        )
        assert out["totalAdds"] == 0

    def test_zero_budget_is_not_a_100_dollar_league(self, monkeypatch):
        """A league with no FAAB is a real state, and it is not 'unknown'
        and not 100 — a percentage of a zero budget is undefined."""
        _install(
            monkeypatch,
            {"L1": _league(0)},
            transactions={1: [_add(0)]},
        )
        out = faab_history.fetch_bid_history("L1")
        assert out["seasons"] == []

    def test_a_real_budget_still_produces_percentages_against_itself(self, monkeypatch):
        _install(
            monkeypatch,
            {"L1": _league(1000)},
            transactions={1: [_add(200)]},
        )
        out = faab_history.fetch_bid_history("L1")
        assert len(out["seasons"]) == 1
        season = out["seasons"][0]
        assert season["budget"] == 1000
        assert season["adds"][0]["bid"] == 200
        # 200 of 1000 is 20%.  Under the retired coercion an unknown
        # budget would have made the identical bid read as 200%.
        assert season["adds"][0]["bidPct"] == pytest.approx(20.0)

    def test_a_budgetless_season_does_not_end_the_walk_early(self, monkeypatch):
        """The chain must keep walking to previous seasons — skipping a
        season is not the same as truncating the history."""
        _install(
            monkeypatch,
            {
                "L1": _league(None, season="2025", previous="L0"),
                "L0": _league(200, season="2024"),
            },
            transactions={1: [_add(50)]},
        )
        out = faab_history.fetch_bid_history("L1")
        seasons = [s["season"] for s in out["seasons"]]
        assert seasons == ["2024"], (
            "the unknown-budget season must be skipped while the walk continues to "
            "the seasons that CAN be priced"
        )
        assert out["seasons"][0]["adds"][0]["bidPct"] == pytest.approx(25.0)

    def test_a_non_numeric_budget_is_unknown_not_a_crash(self, monkeypatch):
        _install(
            monkeypatch,
            {"L1": _league("lots")},
            transactions={1: [_add(20)]},
        )
        out = faab_history.fetch_bid_history("L1")
        assert out["seasons"] == []


def test_the_retired_coercion_is_not_present_as_CODE():
    """Structural: the exact expression the coercion gate's docstring
    names must not come back as executable code.

    Comments are stripped first, deliberately — the repair's own comment
    quotes the retired expression to explain what was wrong, and a naive
    substring scan flagged that explanation as the defect.  A guard that
    forbids describing a bug is a guard that deletes its own rationale.
    """
    import inspect

    code = "\n".join(
        line.split("#", 1)[0]
        for line in inspect.getsource(faab_history.fetch_bid_history).splitlines()
    )
    assert (
        'int(settings.get("waiver_budget") or 0) or 100' not in code
    ), "the fabricated-$100 budget coercion is back in fetch_bid_history"
    assert "or 100" not in code, (
        "some `or 100` fallback has reappeared on the budget path — an unknown "
        "denominator must abstain, not default"
    )
