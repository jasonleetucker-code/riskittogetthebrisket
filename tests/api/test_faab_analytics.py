"""Tests for ``src/api/faab_analytics.py`` — league FAAB summarizer.

The summarizer walks every season's completed waiver / free-agent
transactions, pulls the winning bid amount, and produces a
JSON-serializable block consumed by:

  1. /api/public/league/faabAnalytics  (waivers page UI)
  2. src.trade.faab_recommender         (per-pair recommender — B6)
"""

from __future__ import annotations

from src.api import faab_analytics
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot


def _snap(seasons: list[SeasonSnapshot], nfl_players: dict | None = None) -> PublicLeagueSnapshot:
    """Build a minimal PublicLeagueSnapshot fixture."""
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2026-04-30T00:00:00Z",
        seasons=seasons,
        nfl_players=nfl_players or {},
    )


def _season(
    season: str = "2026",
    *,
    league_id: str = "L1",
    txs_by_week: dict[int, list[dict]] | None = None,
    settings: dict | None = None,
    rosters: list[dict] | None = None,
) -> SeasonSnapshot:
    """SeasonSnapshot with the minimal fields the summarizer reads."""
    league = {
        "name": f"League {season}",
        "settings": settings if settings is not None else {"waiver_budget": 100},
        "season": season,
    }
    return SeasonSnapshot(
        season=season,
        league_id=league_id,
        league=league,
        users=[],
        rosters=rosters or [],
        matchups_by_week={},
        transactions_by_week=txs_by_week or {},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )


def _waiver_tx(
    *,
    bid: int = 0,
    adds: dict[str, int] | None = None,
    drops: dict[str, int] | None = None,
    roster_id: int = 1,
    type_: str = "waiver",
    status: str = "complete",
    created: int = 1700000000,
) -> dict:
    return {
        "type": type_,
        "status": status,
        "settings": {"waiver_bid": bid},
        "adds": adds or {},
        "drops": drops or {},
        "roster_ids": [roster_id],
        "created": created,
        "status_updated": created,
    }


# ── Basic shape ────────────────────────────────────────────────


def test_empty_snapshot_returns_zero_shape():
    snap = _snap([])
    out = faab_analytics.summarize_league_faab(snap)
    assert out["leagueAvgWinningBid"] == 0.0
    assert out["leagueMedianWinningBid"] == 0.0
    assert out["totalBidsAnalyzed"] == 0
    assert out["positionBids"] == {}
    assert "tier1" in out["tierBids"]
    assert out["teamAggression"] == {}
    assert out["recentWins"] == []
    assert out["playerHistory"] == {}


def test_falls_back_to_default_budget_when_unset():
    snap = _snap([_season(settings={})])
    out = faab_analytics.summarize_league_faab(snap)
    assert out["leagueBudget"] == 100


def test_uses_league_settings_waiver_budget():
    snap = _snap([_season(settings={"waiver_budget": 200})])
    out = faab_analytics.summarize_league_faab(snap)
    assert out["leagueBudget"] == 200


# ── Bid aggregation ────────────────────────────────────────────


def test_avg_and_median_are_computed_correctly():
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [
                        _waiver_tx(bid=10, adds={"P1": 1}),
                        _waiver_tx(bid=20, adds={"P2": 1}),
                        _waiver_tx(bid=30, adds={"P3": 1}),
                    ],
                }
            ),
        ]
    )
    out = faab_analytics.summarize_league_faab(snap)
    assert out["totalBidsAnalyzed"] == 3
    assert out["leagueAvgWinningBid"] == 20.0
    assert out["leagueMedianWinningBid"] == 20.0


def test_zero_bid_free_agents_excluded_from_avg():
    """Zero-bid FA pickups don't pull the average down — they
    represent free pickups, not bids the league competed on."""
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [
                        _waiver_tx(bid=20, adds={"P1": 1}),
                        _waiver_tx(bid=0, adds={"P2": 1}, type_="free_agent"),
                        _waiver_tx(bid=0, adds={"P3": 1}, type_="free_agent"),
                    ],
                }
            ),
        ]
    )
    out = faab_analytics.summarize_league_faab(snap)
    assert out["totalBidsAnalyzed"] == 1
    assert out["leagueAvgWinningBid"] == 20.0


# ── Tier bucketing ─────────────────────────────────────────────


def test_tier_bucketing_by_pct_of_budget():
    """20+% → tier1, 10-20% → tier2, 3-10% → tier3, ≤3% → tier4."""
    snap = _snap(
        [
            _season(
                settings={"waiver_budget": 100},
                txs_by_week={
                    1: [
                        _waiver_tx(bid=25, adds={"P1": 1}),  # tier1
                        _waiver_tx(bid=15, adds={"P2": 1}),  # tier2
                        _waiver_tx(bid=5, adds={"P3": 1}),  # tier3
                        _waiver_tx(bid=2, adds={"P4": 1}),  # tier4
                    ],
                },
            ),
        ]
    )
    out = faab_analytics.summarize_league_faab(snap)
    assert out["tierBids"]["tier1"]["count"] == 1
    assert out["tierBids"]["tier2"]["count"] == 1
    assert out["tierBids"]["tier3"]["count"] == 1
    assert out["tierBids"]["tier4"]["count"] == 1


# ── Position attribution ───────────────────────────────────────


def test_position_bids_resolve_via_nfl_players():
    nfl = {
        "WR1": {"position": "WR", "full_name": "WR Guy"},
        "RB1": {"position": "RB", "full_name": "RB Guy"},
    }
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [
                        _waiver_tx(bid=15, adds={"WR1": 1}),
                        _waiver_tx(bid=8, adds={"RB1": 1}),
                    ],
                }
            )
        ],
        nfl_players=nfl,
    )
    out = faab_analytics.summarize_league_faab(snap)
    assert "WR" in out["positionBids"]
    assert "RB" in out["positionBids"]
    assert out["positionBids"]["WR"]["avg"] == 15.0
    assert out["positionBids"]["RB"]["avg"] == 8.0


def test_multi_add_split_is_aggregated_at_full_precision():
    """A $10 bid across three adds is $3.33 a head, not $3.

    Each split used to be ``int(round(per_player_bid))`` BEFORE being
    stored, so the three shares of a $10 bid added back up to $9 — a
    10% understatement of what the league actually paid at that
    position, feeding straight into the recommender's per-position
    calibration blend.
    """
    nfl = {
        "WR1": {"position": "WR"},
        "WR2": {"position": "WR"},
        "WR3": {"position": "WR"},
    }
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [_waiver_tx(bid=10, adds={"WR1": 1, "WR2": 1, "WR3": 1})],
                }
            )
        ],
        nfl_players=nfl,
    )
    out = faab_analytics.summarize_league_faab(snap)
    wr = out["positionBids"]["WR"]
    assert wr["count"] == 3
    # 10 / 3 = 3.3333… → 3.33 after the display round.
    assert wr["avg"] == 3.33
    # min/max are whole dollars for display, rounded not truncated.
    assert wr["min"] == 3
    assert wr["max"] == 3


def test_two_way_split_of_an_odd_bid_keeps_the_half():
    """$25 across two adds is $12.50 each — the display average must
    be 12.5, not the 12 that two rounded-down halves produced."""
    nfl = {"RB1": {"position": "RB"}, "RB2": {"position": "RB"}}
    snap = _snap(
        [_season(txs_by_week={1: [_waiver_tx(bid=25, adds={"RB1": 1, "RB2": 1})]})],
        nfl_players=nfl,
    )
    out = faab_analytics.summarize_league_faab(snap)
    assert out["positionBids"]["RB"]["avg"] == 12.5


def test_idp_positions_normalize_to_base_buckets():
    nfl = {
        "DT1": {"position": "DT"},
        "EDGE1": {"position": "EDGE"},
        "ILB1": {"position": "ILB"},
        "CB1": {"position": "CB"},
        "S1": {"position": "S"},
    }
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [
                        _waiver_tx(bid=5, adds={"DT1": 1}),
                        _waiver_tx(bid=4, adds={"EDGE1": 1}),
                        _waiver_tx(bid=3, adds={"ILB1": 1}),
                        _waiver_tx(bid=2, adds={"CB1": 1}),
                        _waiver_tx(bid=1, adds={"S1": 1}),
                    ],
                }
            )
        ],
        nfl_players=nfl,
    )
    out = faab_analytics.summarize_league_faab(snap)
    # DT, EDGE → DL.  ILB → LB.  CB, S → DB.
    assert out["positionBids"]["DL"]["count"] == 2
    assert out["positionBids"]["LB"]["count"] == 1
    assert out["positionBids"]["DB"]["count"] == 2


# ── Team aggression ────────────────────────────────────────────


def test_team_aggression_aggregates_per_owner():
    rosters = [
        {"roster_id": 1, "owner_id": "ownerA"},
        {"roster_id": 2, "owner_id": "ownerB"},
    ]
    snap = _snap(
        [
            _season(
                rosters=rosters,
                txs_by_week={
                    1: [
                        _waiver_tx(bid=20, adds={"P1": 1}, roster_id=1),
                        _waiver_tx(bid=10, adds={"P2": 1}, roster_id=1),
                        _waiver_tx(bid=5, adds={"P3": 1}, roster_id=2),
                        _waiver_tx(bid=0, adds={"P4": 1}, roster_id=2, type_="free_agent"),
                    ],
                },
            ),
        ]
    )
    out = faab_analytics.summarize_league_faab(snap)
    a = out["teamAggression"]["ownerA"]
    assert a["totalSpent"] == 30
    assert a["winningCount"] == 2
    assert a["maxBid"] == 20
    b = out["teamAggression"]["ownerB"]
    assert b["totalSpent"] == 5  # FA pickup doesn't count
    assert b["totalCount"] == 2  # but it counts towards activity
    assert b["winningCount"] == 1


# ── Player history ─────────────────────────────────────────────


def test_player_history_records_each_add():
    rosters = [{"roster_id": 1, "owner_id": "ownerA"}]
    snap = _snap(
        [
            _season(
                season="2025",
                rosters=rosters,
                txs_by_week={1: [_waiver_tx(bid=15, adds={"PX": 1})]},
            ),
            _season(
                season="2026",
                rosters=rosters,
                txs_by_week={1: [_waiver_tx(bid=22, adds={"PX": 1})]},
            ),
        ]
    )
    out = faab_analytics.summarize_league_faab(snap)
    history = out["playerHistory"]["PX"]
    assert len(history) == 2
    assert {h["bid"] for h in history} == {15, 22}
    assert {h["season"] for h in history} == {"2025", "2026"}


# ── Recent wins ────────────────────────────────────────────────


def test_recent_wins_skip_zero_bid_pickups():
    """Recent-wins timeline excludes free-agent pickups so the UI
    only surfaces actual bidding activity."""
    snap = _snap(
        [
            _season(
                txs_by_week={
                    1: [
                        _waiver_tx(bid=15, adds={"WR1": 1}, created=1000),
                        _waiver_tx(bid=0, adds={"P0": 1}, type_="free_agent", created=2000),
                        _waiver_tx(bid=10, adds={"WR2": 1}, created=3000),
                    ],
                }
            )
        ],
    )
    out = faab_analytics.summarize_league_faab(snap)
    bids = [w["bid"] for w in out["recentWins"]]
    assert 0 not in bids
    # Newest-first ordering by createdAt — the second tx (created=3000)
    # is bid=10, the first (created=1000) is bid=15.
    created_at = [w["createdAt"] for w in out["recentWins"]]
    assert sorted(created_at, reverse=True) == created_at


# ── Section registration ───────────────────────────────────────


def test_section_registered_in_public_contract():
    from src.public_league.public_contract import PUBLIC_SECTION_KEYS

    assert "faabAnalytics" in PUBLIC_SECTION_KEYS


def test_build_section_returns_summarize_output():
    snap = _snap([])
    via_section = faab_analytics.build_section(snap)
    via_summary = faab_analytics.summarize_league_faab(snap)
    assert via_section == via_summary
