"""BDVM roster capital counts the picks the roster actually holds.

Audit finding W13-F002: ``analyze_rosters`` built ``assets`` exclusively
from ``roster["playerIds"]`` and consumed ``roster["picks"]`` with
``len()`` alone.  ``capitals``, ``nowFutureRatio`` and every asset the
double-positive scan could propose were therefore player-only — a
rebuilder holding 62 picks reported 59,693 of rebuilder capital against
114,477 with picks included (47.9% omitted), and 2 of 12 direction
labels flipped.  The /bdvm Rosters table rendered ``pickCount`` right
next to capitals computed as if those picks were worth zero.
"""

from __future__ import annotations

from src.bdvm.params import load_param_set
from src.bdvm.roster import analyze_rosters

STRATEGIES = ("contender", "balanced", "rebuilder")


def _player(pid: str, name: str, value: float, age: int = 25) -> dict:
    return {
        "playerId": pid,
        "name": name,
        "position": "WR",
        "group": "WR",
        "projection": {"fpg": 12.0},
        "raw": {"age": age},
        "tradeValue": {s: value for s in STRATEGIES},
        "market": {"marketValue": value, "tradeClearing": value},
    }


def _pick(name: str, ev: float) -> dict:
    return {
        "name": name,
        "assetClass": "pick",
        "distribution": {s: {"ev": ev} for s in STRATEGIES},
        "market": {"marketValue": ev, "tradeClearing": ev},
    }


def _payload() -> dict:
    return {
        "players": [_player("1", "Alpha", 4000.0), _player("2", "Beta", 3000.0)],
        "picks": [
            _pick("2026 Pick 1.06", 2500.0),
            _pick("2027 Mid 1st", 2000.0),
            # Priced by the board but not held by anyone below.
            _pick("2028 Mid 1st", 1500.0),
            # The board declines to price this one.
            {"name": "2026 Mid 6th", "assetClass": "pick", "distribution": None},
        ],
        "replacement": {"WR": {"replacementFpg": 8.0}},
    }


def _contract(picks: list) -> dict:
    return {
        "pickAliases": {"2026 Mid 1st": "2026 Pick 1.06"},
        "sleeper": {
            "teams": [
                {
                    "name": "Holder",
                    "ownerId": "o1",
                    "roster_id": 1,
                    "playerIds": ["1"],
                    "players": ["Alpha"],
                    "picks": picks,
                },
                {
                    "name": "Other",
                    "ownerId": "o2",
                    "roster_id": 2,
                    "playerIds": ["2"],
                    "players": ["Beta"],
                    "picks": [],
                },
            ]
        },
    }


def _analyze(picks: list) -> dict:
    out = analyze_rosters(_payload(), _contract(picks), load_param_set())
    return {r["name"]: r for r in out["rosters"]}


class TestPickCapital:
    def test_picks_are_counted_into_every_strategy_capital(self):
        r = _analyze(["2026 1st", "2027 1st"])["Holder"]
        # Alpha 4000 + 2026 slot 2500 + 2027 mid 2000.
        for strategy in STRATEGIES:
            assert r["capitals"][strategy] == 8500.0

    def test_pick_capital_is_reported_separately(self):
        r = _analyze(["2026 1st", "2027 1st"])["Holder"]
        assert r["pickCapital"]["balanced"] == 4500.0

    def test_a_roster_with_no_picks_is_unchanged(self):
        r = _analyze([])["Holder"]
        assert r["capitals"]["balanced"] == 4000.0
        assert r["pickCapital"]["balanced"] == 0.0

    def test_sleeper_pick_details_resolve_as_well_as_flat_labels(self):
        details = [
            {"season": "2026", "round": 1, "slot": None, "label": "2026 1st"},
            {"season": "2027", "round": 1, "slot": None, "label": "2027 1st"},
        ]
        assert _analyze(details)["Holder"]["capitals"]["balanced"] == 8500.0

    def test_the_sleeper_own_suffix_resolves(self):
        assert _analyze(["2027 1st (own)"])["Holder"]["pickCapital"]["balanced"] == 2000.0


class TestUnpricedStaysUnpriced:
    def test_an_unpriced_pick_is_reported_not_valued_at_zero(self):
        r = _analyze(["2026 6th", "2027 1st"])["Holder"]
        assert r["pickCountUnpriced"] == 1
        assert r["pickCountPriced"] == 1
        # And it did not enter the capital as a zero.
        assert r["pickCapital"]["balanced"] == 2000.0

    def test_a_pick_the_board_does_not_carry_is_unpriced(self):
        # 2029 has no board row at all.  Inventing a value here is the
        # failure this codebase already had with a flat
        # 7000/4000/2000/1200 table.
        r = _analyze(["2029 1st"])["Holder"]
        assert r["pickCountUnpriced"] == 1
        assert r["pickCapital"]["balanced"] == 0.0


class TestScopeDiscipline:
    def test_value_weighted_age_stays_player_only(self):
        # A pick has no age; weighting it in at zero would drag the mean
        # toward a number nothing measured.
        with_picks = _analyze(["2026 1st", "2027 1st"])["Holder"]
        without = _analyze([])["Holder"]
        assert with_picks["valueWeightedAge"] == without["valueWeightedAge"] == 25.0
        assert with_picks["valueWeightedAgeScope"] == "players"

    def test_starter_fpg_and_surplus_stay_player_only(self):
        with_picks = _analyze(["2026 1st", "2027 1st"])["Holder"]
        without = _analyze([])["Holder"]
        assert with_picks["starterFpg"] == without["starterFpg"]
        assert with_picks["positionalSurplus"] == without["positionalSurplus"]

    def test_picks_are_proposable_by_the_trade_scan(self):
        r = _analyze(["2026 1st", "2027 1st"])["Holder"]
        assert any(a.get("isPick") for a in r["assets"]), "no pick in the scan's asset list"
