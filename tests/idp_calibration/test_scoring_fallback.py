"""Under Option 1 (always use the user's input league's scoring
and lineup for every target year) every historical year "borrows"
from the current input league. These tests pin that behaviour and
the warning strings users see.
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
    """Return a chain fetcher that resolves exactly the given seasons.

    The first element of the returned list is the newest season —
    which is the ``walk[0]`` the engine now uses as the scoring
    source for every target year.
    """

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


def test_current_input_league_rules_applied_to_all_years(monkeypatch):
    """Both leagues resolve 2024+2025. The engine should still use
    the 2025 (walk[0]) rules for 2022, 2023, and 2024 — Option 1."""
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
    # Every resolved year should stamp its rules_source_season as 2025.
    for year in ("2022", "2023", "2024", "2025"):
        assert per_season[year]["resolved"] is True
        assert per_season[year]["test_rules_source_season"] == 2025
        assert per_season[year]["my_rules_source_season"] == 2025
    # 2025 matches the input league's season so it's NOT flagged as
    # borrowed. Historical years ARE flagged.
    assert per_season["2025"]["test_rules_borrowed"] is False
    assert per_season["2025"]["my_rules_borrowed"] is False
    assert per_season["2024"]["test_rules_borrowed"] is True
    assert per_season["2022"]["test_rules_borrowed"] is True
    # Warning messaging reflects Option 1's "rescored under today's
    # rules" phrasing, not the old "league did not exist" phrasing.
    assert any(
        "today's rules" in w and "2022" in w for w in art["warnings"]
    )


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
    # 2022 + 2023 resolve — the input league IS the 2023 league, so
    # historical 2022 uses 2023 rules (same input league).
    assert art["per_season"]["2022"]["resolved"] is True
    assert art["per_season"]["2023"]["resolved"] is True
    # 2024 + 2025 must stay unresolved — not forward-borrowed.
    assert art["per_season"]["2024"]["resolved"] is False
    assert art["per_season"]["2025"]["resolved"] is False
    reason_2025 = art["per_season"]["2025"]["reason"]
    assert "stale" in reason_2025.lower() or "forward-borrow" in reason_2025.lower()
    assert any("2025" in w and "stale" in w.lower() for w in art["warnings"])


def test_one_chain_short_other_chain_full(monkeypatch):
    """My league input is 2025; test league input is also 2025.
    Under Option 1 both leagues' rules come from their own walk[0]
    = 2025 regardless of which historical years the chains reach."""
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
    # Test side: rules always from 2025 (walk[0]).
    for year in ("2022", "2023", "2024", "2025"):
        assert art["per_season"][year]["test_rules_source_season"] == 2025
    # 2025 not borrowed (matches source); earlier years are borrowed.
    assert art["per_season"]["2022"]["test_rules_borrowed"] is True
    assert art["per_season"]["2025"]["test_rules_borrowed"] is False
    # My side: same story — 2025 native, earlier years borrowed.
    assert art["per_season"]["2022"]["my_rules_source_season"] == 2025
    assert art["per_season"]["2022"]["my_rules_borrowed"] is True
    assert art["per_season"]["2025"]["my_rules_borrowed"] is False


def test_standard_league_with_no_idp_in_historical_year_still_works(monkeypatch):
    """Repro for the real-world bug: the 2025 "Standard" league
    snapshot has no IDP scoring, but the 2026 input does. Under
    Option 1 the 2026 rules are applied to every historical year so
    the user never sees "No IDP stats scored" on a league that in
    fact has IDP today."""
    newest_league_with_idp = {
        "league_id": "current",
        "season": 2026,
        "previous_league_id": "prev",
        "scoring_settings": {"idp_tkl_solo": 1.0, "idp_sack": 4.0},
        "roster_positions": ["QB", "RB", "WR", "DL", "LB", "DB", "BN"],
        "total_rosters": 12,
    }
    historical_league_no_idp = {
        "league_id": "prev",
        "season": 2025,
        "previous_league_id": "",
        "scoring_settings": {"pass_yd": 0.04},  # NO IDP keys
        "roster_positions": ["QB", "RB", "WR", "TE", "K", "BN"],
        "total_rosters": 12,
    }
    monkeypatch.setattr(
        season_chain,
        "fetch_league_chain",
        lambda *a, **kw: [newest_league_with_idp, historical_league_no_idp],
    )
    settings = engine.AnalysisSettings(seasons=[2025])
    art = engine.run_analysis(
        "A", "B", settings, stats_adapter_factory=lambda s: _StubAdapter()
    )
    # 2025 resolves and is scored under the 2026 input league's rules.
    assert art["per_season"]["2025"]["resolved"] is True
    # Test/My scoring summary surfaces active IDP stats (proves the
    # 2026 rules were the ones parsed, not the 2025 "no IDP" rules).
    assert art["per_season"]["2025"]["test_scoring"]["active_idp_stats"]
    assert art["per_season"]["2025"]["my_scoring"]["active_idp_stats"]
    assert art["per_season"]["2025"]["test_rules_source_season"] == 2026
    assert art["per_season"]["2025"]["test_rules_borrowed"] is True
