import json
from pathlib import Path

from src.platforms.assets import AssetResolver
from src.platforms.ffpc.parser import FFPCParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_public_league_home_expands_and_deduplicates_team_side_trade_rows():
    players = json.loads((FIXTURES / "players.json").read_text(encoding="utf-8"))
    parser = FFPCParser(AssetResolver.from_sleeper_directory(players))
    result = parser.parse(
        (FIXTURES / "league_home_public.html").read_text(encoding="utf-8"),
        source_url="https://myffpc.com/LeagueHome.aspx?ltuid=PUBLIC",
        source_league_id="PUBLIC",
        season="2026",
        format_type="dynasty",
        fetched_ms=1_800_000_000_000,
    )

    trades = [row for row in result.batch.transactions if row.transaction_type == "trade"]
    free_agents = [row for row in result.batch.transactions if row.transaction_type == "free_agent"]
    assert len(trades) == 1
    assert len(free_agents) == 1

    trade_movements = [
        row for row in result.batch.movements if row.transaction_key == trades[0].transaction_key
    ]
    assert len(trade_movements) == 6
    assert {row.manager_key for row in trade_movements} == {
        "ffpc:league:PUBLIC:team:1",
        "ffpc:league:PUBLIC:team:2",
    }
    assert {row.canonical_asset_id for row in trade_movements} == {
        "4046",
        "7564",
        "pick:2027:2",
    }
    assert {row.action for row in trade_movements} == {"add", "drop"}

    drop = next(
        row
        for row in result.batch.movements
        if row.transaction_key == free_agents[0].transaction_key
    )
    assert drop.canonical_asset_id == "10001"
    assert drop.action == "drop"

    # Division label rows are not managers or teams.
    assert len(result.batch.manager_seasons) == 2
    assert all(row.team_count == 2 for row in result.batch.manager_seasons)
