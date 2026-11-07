"""CW-40 Batch T2 -- findings still OPEN / PARTIAL / awaiting an owner decision on ``main`` (2026-11-07).

Each OPEN item has a CHARACTERIZATION test (passes today; pins what the code does now so a change is
noticed) and, where the intended behaviour is already settled, a ``strict=True`` xfail that states it
and flips the day the defect is repaired.  Items whose intended behaviour needs a product choice get
the characterization only; the exact question is in ``CW40_P1_BATCH_t2.md``.

* W12-F005  signal-alert cooldown / prior-signal are keyed on the rule TAG (OPEN; repair belongs to
            ``src/api/signal_alerts.py``, which PR #2105 is editing);
* W20-F010  ``/api/gameplan`` rollups: market / consensus / leagueAdjusted publish a measured 0.0
            (PARTIAL: pickValue is now an explicit unavailable state; repair belongs to
            ``src/api/gameplan.py``, which PR #2109 is editing);
* W20-F003  Terminal ``totalValue`` is a raw player sum that excludes picks (owner decision);
* W20-F004  the server half of the PortfolioSummary total/legend mismatch (JS half:
            ``frontend/__tests__/components/audit-cw40-batch-t2-portfolio.test.jsx``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# W12-F005
# ---------------------------------------------------------------------------


@pytest.fixture()
def kv_path(tmp_path):
    from src.api import user_kv

    user_kv._SETUP_DONE.clear()
    yield tmp_path / "user_kv.sqlite"
    user_kv._SETUP_DONE.clear()


def _sig(name, tag, signal, sid):
    return {
        "name": name,
        "pos": "QB",
        "signal": signal,
        "reason": f"{signal} reason",
        "tag": tag,
        "signalKey": f"{name}::{tag}",
        "aliasSignalKey": f"sid:{sid}::{tag}",
        "sleeperId": sid,
        "dismissed": False,
    }


def _flip(kv_path):
    """A player's signal flips BUY -> SELL with a different firing rule, zero seconds apart."""
    from src.api import signal_alerts

    first = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "uptrend_controlled", "BUY", "4017")], path=kv_path
    )
    second = signal_alerts.detect_signal_transitions(
        "alice", [_sig("Josh Allen", "sustained_downtrend", "SELL", "4017")], path=kv_path
    )
    return first, second


def test_w12_f005_characterization_a_flip_with_a_new_tag_fires_twice_with_no_prior(kv_path):
    """CURRENT behaviour: state rows are keyed ``sid:<id>::<tag>``, so the second rule is a brand
    new row (no ``notifiedAt``, no prior signal) and the 12-hour cooldown never engages."""
    first, second = _flip(kv_path)
    assert len(first) == 1 and first[0]["signal"] == "BUY"
    assert len(second) == 1 and second[0]["signal"] == "SELL"
    assert second[0]["priorSignal"] is None  # the digest renders this as "-- -> SELL"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W12-F005 open: a flip is presented as a brand-new signal; priorSignal should be the "
    "player's previous alerted signal (BUY), not None",
)
def test_w12_f005_a_flip_reports_the_players_previous_signal(kv_path):
    _first, second = _flip(kv_path)
    assert second and second[0]["priorSignal"] == "BUY"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W12-F005 open: the 12h cooldown is keyed on the rule tag, so it never engages when the "
    "reason changes (the case it exists for); key it on the player",
)
def test_w12_f005_cooldown_engages_when_the_same_player_flips_rule_immediately(kv_path):
    _first, second = _flip(kv_path)
    assert second == []


# ---------------------------------------------------------------------------
# W20-F010
# ---------------------------------------------------------------------------


def _pool():
    from src.ros.lineup import RosterPlayer

    return [
        RosterPlayer(player_id="qb1", canonical_name="qb1", position="QB", ros_value=50.0),
        RosterPlayer(player_id="rb1", canonical_name="rb1", position="RB", ros_value=40.0),
        RosterPlayer(player_id="wr1", canonical_name="wr1", position="WR", ros_value=30.0),
    ]


def test_w20_f010_characterization_unfed_value_rollups_publish_a_measured_zero():
    """CURRENT: with no ``player_values`` the engine still emits ``market``/``consensus``/
    ``leagueAdjusted`` as 0.0 beside a positive pricedPlayers count (pickValue was repaired to an
    explicit ``unavailable`` state; these three were not)."""
    from src.roster_intel.engine import analyze_roster

    intel = analyze_roster("o1", _pool(), ["QB", "RB", "WR"])
    values = intel.values.to_dict()
    assert values["pricedPlayers"] == 3
    assert values["market"] == 0.0 and values["consensus"] == 0.0
    assert values["leagueAdjusted"] == 0.0
    assert values["pickValue"] is None and values["pickValueState"] == "unavailable"


def _analyze_roster_call_keywords() -> set[str]:
    tree = ast.parse((REPO / "src" / "api" / "gameplan.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "analyze_roster"
        ):
            return {k.arg for k in node.keywords if k.arg}
    raise AssertionError("analyze_roster call not found in gameplan.py")


def test_w20_f010_characterization_gameplan_does_not_feed_player_values():
    assert "player_values" not in _analyze_roster_call_keywords()


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="W20-F010 open: build_league_bundle must pass player_values (the site-value map it "
    "already builds) to analyze_roster, or the engine must publish market/consensus/"
    "leagueAdjusted as unavailable instead of 0.0",
)
def test_w20_f010_gameplan_feeds_the_value_rollups():
    assert "player_values" in _analyze_roster_call_keywords()


# ---------------------------------------------------------------------------
# W20-F003 / W20-F004 (server half)
# ---------------------------------------------------------------------------


def _contract_with_picks():
    rows = [
        {
            "displayName": name,
            "canonicalName": name,
            "assetClass": "offense",
            "position": pos,
            "pos": pos,
            "canonicalConsensusRank": rank,
            "rankDerivedValue": value,
            "values": {"full": value},
            "rookie": False,
            "age": 26,
        }
        for name, pos, rank, value in (("Alice", "QB", 1, 9000), ("Bob", "WR", 2, 7000))
    ]
    rows.append(
        {
            "displayName": "2026 Pick 1.01",
            "canonicalName": "2026 Pick 1.01",
            "assetClass": "pick",
            "position": "PICK",
            "pos": "PICK",
            "canonicalConsensusRank": None,
            "rankDerivedValue": 5000,
            "values": {"full": 5000},
        }
    )
    return {
        "date": "2026-11-07",
        "generatedAt": "2026-11-07T00:00:00+00:00",
        "contractVersion": "2026-03-10.v2",
        "playersArray": rows,
        "sleeper": {
            "teams": [
                {
                    "ownerId": "o1",
                    "name": "Alpha",
                    "roster_id": 1,
                    "players": ["Alice", "Bob"],
                    "picks": ["2026 1.01"],
                }
            ],
            "trades": [],
        },
    }


def test_w20_f003_f004_characterization_terminal_total_is_the_player_sum_and_excludes_picks(
    tmp_path, monkeypatch
):
    """CURRENT: ``teamAggregates.totalValue`` and ``portfolio.totalValue`` are the raw sum of the
    roster PLAYERS' ``rankDerivedValue`` -- a portfolio total (labelled "Team value" in the UI), not
    a lineup-weighted strength -- and exclude every pick the team holds.  Whether picks belong in
    this total is the owner decision recorded in ``CW40_P1_BATCH_t2.md`` (W20-F003 / W20-F004)."""
    from src.api import rank_history, terminal

    monkeypatch.setattr(rank_history, "HISTORY_PATH", tmp_path / "rank_history.jsonl")
    contract = _contract_with_picks()
    team = terminal.resolve_team(contract, owner_id="o1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)

    assert payload["teamAggregates"]["totalValue"] == 9000 + 7000
    portfolio = payload["portfolio"]
    assert portfolio["totalValue"] == 9000 + 7000
    assert portfolio["byPosition"]["PICK"]["count"] == 0
    assert portfolio["byPosition"]["PICK"]["value"] == 0


def test_w20_f003_the_ui_labels_the_raw_sum_as_team_value_not_strength():
    header = (REPO / "frontend/components/terminal/TeamCommandHeader.jsx").read_text(
        encoding="utf-8"
    )
    assert 'label="Team value"' in header
    assert "strength" not in header.lower().split("<section", 1)[1]
