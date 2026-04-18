from __future__ import annotations

from src.idp_calibration.season_chain import DEFAULT_SEASONS, resolve_seasons


def _fake_chain_builder(seasons):
    def _builder(league_id, max_hops):
        out = []
        for i, s in enumerate(seasons):
            out.append(
                {
                    "league_id": f"{league_id}_{s}",
                    "season": s,
                    "name": f"{league_id} {s}",
                    "previous_league_id": f"{league_id}_{s - 1}" if i < len(seasons) - 1 else "",
                }
            )
        return out

    return _builder


def test_resolves_all_default_seasons():
    chain = resolve_seasons(
        "L1",
        chain_fetcher=_fake_chain_builder([2025, 2024, 2023, 2022]),
    )
    assert chain.input_league_id == "L1"
    for season in DEFAULT_SEASONS:
        res = chain.seasons[season]
        assert res.resolved
        assert res.league_id == f"L1_{season}"
    assert chain.warnings == []


def test_flags_missing_season_without_substitution():
    # 2022 not present in chain.
    chain = resolve_seasons(
        "L2",
        chain_fetcher=_fake_chain_builder([2025, 2024, 2023]),
    )
    assert chain.seasons[2022].resolved is False
    assert chain.seasons[2023].resolved is True
    # Ensure 2022 was never silently mapped to 2023.
    assert chain.seasons[2022].league_id is None
    assert any("2022" in w for w in chain.warnings)


def test_empty_league_id_returns_warning():
    chain = resolve_seasons("", chain_fetcher=_fake_chain_builder([]))
    assert chain.warnings
    for season in DEFAULT_SEASONS:
        assert chain.seasons[season].resolved is False
