"""Scoring/lineup fallback when a league didn't exist in the target year.

Regression test for the behaviour change that lets historical stats
still score against each league's most-recent rules when the league
chain doesn't reach that far back.
"""
from __future__ import annotations

from src.idp_calibration import engine, season_chain
from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason


class _StubAdapter(HistoricalStatsAdapter):
    name = "stub"

    def _fetch_impl(self, season: int):
        rows = []
        for i in range(30):
            rows.append(
                PlayerSeason(
                    player_id=f"p{season}_{i}",
                    name=f"P{i}",
                    position=["DL", "LB", "DB"][i % 3],
                    games=16,
                    stats={"idp_tkl_solo": 50 - i, "idp_sack": max(0, 6 - i / 5)},
                )
            )
        return rows


def _short_chain(seasons_present):
    """Return a chain fetcher that only resolves a subset of seasons."""

    def _builder(league_id, max_hops):
        return [
            {
                "league_id": f"{league_id}_{s}",
                "season": s,
                "previous_league_id": f"{league_id}_{s - 1}" if i < len(seasons_present) - 1 else "",
                "scoring_settings": {"idp_tkl_solo": 1.0, "idp_sack": 4.0},
                "roster_positions": ["QB", "RB", "WR", "DL", "LB", "LB", "DB", "BN"],
                "total_rosters": 12,
            }
            for i, s in enumerate(sorted(seasons_present, reverse=True))
        ]

    return _builder


def test_borrows_current_scoring_when_historical_league_missing(monkeypatch):
    """Both leagues only reach back to 2024. Settings request 2022-2025.
    The 2022/2023 payloads should still resolve using borrowed rules."""
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _short_chain([2024, 2025]),
    )
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    per_season = art["per_season"]
    # 2024 + 2025 resolve natively (no borrow).
    assert per_season["2024"]["resolved"] is True
    assert per_season["2024"]["test_rules_borrowed"] is False
    assert per_season["2024"]["my_rules_borrowed"] is False
    # 2022 + 2023 were outside the chain but we still computed VOR for
    # them using rules borrowed from the most recent resolved league.
    assert per_season["2022"]["resolved"] is True
    assert per_season["2022"]["test_rules_borrowed"] is True
    assert per_season["2022"]["my_rules_borrowed"] is True
    assert per_season["2022"]["test_rules_source_season"] == 2025
    # A user-facing warning is emitted per borrowed season per league.
    assert any("2022" in w and "borrowed" in w for w in art["warnings"])
    assert any("2023" in w and "borrowed" in w for w in art["warnings"])


def test_refuses_when_chain_is_completely_empty(monkeypatch):
    """If a chain returns nothing at all we can't borrow anything;
    that season's payload stays unresolved."""
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        lambda *a, **kw: [],
    )
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    for season_key in ("2022", "2023", "2024", "2025"):
        assert art["per_season"][season_key]["resolved"] is False


def test_refuses_forward_borrow_for_stale_league_id(monkeypatch):
    """Chain only reaches 2023, user asks for 2022-2025. The 2024 and
    2025 target seasons must NOT silently use 2023 rules — they stay
    unresolved with a "is the league ID stale?" warning so the
    misconfig is visible to the reviewer instead of producing wrong
    calibration output."""
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        _short_chain([2022, 2023]),
    )
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    # 2022 + 2023 resolve natively.
    assert art["per_season"]["2022"]["resolved"] is True
    assert art["per_season"]["2023"]["resolved"] is True
    # 2024 + 2025 must stay unresolved — not forward-borrowed.
    assert art["per_season"]["2024"]["resolved"] is False
    assert art["per_season"]["2025"]["resolved"] is False
    reason_2025 = art["per_season"]["2025"]["reason"]
    assert "stale" in reason_2025.lower() or "forward-borrow" in reason_2025.lower()
    # Warning must surface at the run-level too.
    assert any("2025" in w and "stale" in w.lower() for w in art["warnings"])


def test_one_chain_short_other_chain_full(monkeypatch):
    """My league reaches 2022-2025; test league only reaches 2024-2025.
    The 2022/2023 payloads borrow only on the test side."""
    chains = {
        "MINE": _short_chain([2022, 2023, 2024, 2025]),
        "TEST": _short_chain([2024, 2025]),
    }

    def _dispatch(league_id, max_hops):
        kind = "MINE" if league_id == "MINE" else "TEST"
        return chains[kind](league_id, max_hops)

    monkeypatch.setattr(season_chain, "fetch_league_chain", _dispatch)
    settings = engine.AnalysisSettings()
    art = engine.run_analysis(
        "TEST", "MINE", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    assert art["per_season"]["2022"]["test_rules_borrowed"] is True
    assert art["per_season"]["2022"]["my_rules_borrowed"] is False
    assert art["per_season"]["2025"]["test_rules_borrowed"] is False
    assert art["per_season"]["2025"]["my_rules_borrowed"] is False
