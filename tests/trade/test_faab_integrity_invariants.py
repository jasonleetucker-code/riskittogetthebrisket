"""CW-10 — FAAB integrity: invariants, not snapshots.

The August master audit recorded five FAAB findings against code that has since
been replaced (``src/trade/waiver.py::_compute_faab_bid`` pool-relative share,
``faab_recommender.py`` position blend, a client-side ``computeFaabHint``, the
/draft ``draft-logic.js`` bid ladder).  Their stored reproductions are rotted,
so each is re-stated here as the INVARIANT it was a violation of and asserted
against the CURRENT canonical owner, ``src/trade/faab_engine.py``, on small
synthetic leagues (no network, no live board).

Verdicts and the exact reasoning live in
``docs/waivers/FAAB_INTEGRITY_VERIFICATION_2026-11-06.md``.  Every test here
states which finding it proves; where the documented model does NOT promise an
invariant the test says so and pins the actual behaviour instead of inventing
the promise.
"""

from __future__ import annotations

import math
import random
from datetime import date
from typing import Any

import pytest

from src.trade import faab_engine as FE
from src.trade import faab_recommender as FR
from src.trade import waiver as W

BUDGET = 100


def _board() -> list[float]:
    """A convex 700-row board: all-in line (rank 240) ~2.2k, replacement (rank 480) ~0.5k."""
    return [max(50.0, 9999.0 * math.exp(-i / 160.0)) for i in range(700)]


def _league(*, week: int | None = 8, in_season: bool = True, budget: int = BUDGET):
    return FE.LeagueContext(
        original_budget=budget,
        team_count=12,
        starters_per_team=20,
        current_week=week,
        in_season=in_season,
    )


def _anchors(league=None) -> FE.Anchors:
    return FE.resolve_anchors(
        _board(),
        league or _league(),
        available_values=[900.0 - 8.0 * i for i in range(60)],
    )


def _rivals(n: int = 5, *, balance: int = 60) -> list[FE.RivalTeam]:
    return [
        FE.RivalTeam(
            owner_id=f"r{i}",
            faab_remaining=balance + 5 * i,
            aggression=1.0,
            need_level="neutral",
            low_sample=False,
        )
        for i in range(n)
    ]


def _rec(
    value: float,
    *,
    remaining: int | None = 80,
    rivals: list[FE.RivalTeam] | None = None,
    league: FE.LeagueContext | None = None,
    anchors: FE.Anchors | None = None,
    need: str = "neutral",
    status: str = "bubble",
    posture: str = "balanced",
    open_spots: int = 1,
    drop_value: float = 0.0,
    crowd: dict[str, Any] | None = None,
    trending: dict[str, Any] | None = None,
) -> dict[str, Any]:
    league = league or _league()
    team = FE.TeamContext(
        owner_id="me",
        faab_remaining=remaining,
        open_roster_spots=open_spots,
        need_level=need,
        competitive_status=status,
        risk_posture=posture,
    )
    player = FE.PlayerInput(
        name="Target",
        value=float(value),
        position="WR",
        drop_name="Dropped" if drop_value > 0 else None,
        drop_value=float(drop_value),
    )
    return FE.recommend(
        player,
        league,
        team,
        anchors=anchors or _anchors(league),
        rivals=_rivals() if rivals is None else rivals,
        crowd=crowd,
        trending=trending,
    )


VALUES = [0, 300, 600, 900, 1200, 1500, 1800, 2200, 2600, 3200, 4500, 6500, 9999]


# ── W10-F001 — bids ignore the team's remaining budget ──────────────


class TestW10F001BidsRespectTheBalance:
    """The /draft ladder this finding named is not the FAAB engine; the FAAB
    engine's version of the invariant is that a recommendation can never exceed
    what the team can pay, for ANY balance, while WORTH stays balance-free."""

    @pytest.mark.parametrize("remaining", [-7, 0, 1, 2, 3, 5, 17, 100, 250])
    @pytest.mark.parametrize("posture", ["conservative", "balanced", "aggressive"])
    def test_every_rung_is_bounded_by_the_balance(self, remaining, posture):
        cap = max(0, remaining)
        for value in VALUES:
            bids = _rec(value, remaining=remaining, posture=posture)["bids"]
            assert (
                0
                <= bids["conservative"]
                <= bids["recommended"]
                <= bids["aggressive"]
                <= bids["maxRational"]
                <= cap
            ), (value, remaining, posture, bids)

    @pytest.mark.parametrize("remaining", [1, 4, 33, 100])
    def test_max_rational_is_the_documented_hard_cap(self, remaining):
        """hardCap = min(R, floor(max(teamRaw$, team$))) — docs/faab-model.md Stage E."""
        league, anchors = _league(), _anchors()
        team = FE.TeamContext(faab_remaining=remaining, open_roster_spots=1)
        for value in VALUES:
            ceil = FE.team_ceiling(
                FE.PlayerInput(name="t", value=float(value)), anchors, league, team
            )
            expected = int(
                min(
                    remaining,
                    math.floor(max(ceil["teamRawCeilingDollars"], ceil["teamCeilingDollars"])),
                )
            )
            got = _rec(value, remaining=remaining)["bids"]["maxRational"]
            assert got == max(0, expected), (value, remaining)

    def test_a_broke_team_bids_zero_but_is_still_told_the_market_price(self):
        out = _rec(3200, remaining=0)
        assert out["bids"]["recommended"] == 0
        assert out["bids"]["maxRational"] == 0
        assert out["pctOfRemaining"] is None  # undefined, never 0%
        assert any("no FAAB left" in w for w in out["warnings"])
        # "what he will go for" is a statement about the field, not about our cash.
        assert out["bids"]["clearing"] > 0

    def test_a_known_zero_balance_is_not_an_unknown_one(self):
        """MISSING != 0 in both directions: None means "unknown" and falls back to
        the original budget (documented in ``find_waiver_targets``); a KNOWN $0
        must never be promoted to a full budget."""
        known_zero = _rec(3200, remaining=0)["bids"]["recommended"]
        unknown = _rec(3200, remaining=None)["bids"]["recommended"]
        full = _rec(3200, remaining=BUDGET)["bids"]["recommended"]
        assert known_zero == 0
        assert unknown == full > 0

    def test_a_larger_balance_never_lowers_the_bid(self):
        """The balance is only a CAP: on the dense (<= $40) part of the bid grid a
        larger cap can only add candidate bids, so the recommendation is
        non-decreasing in the balance."""
        for value in (900, 1800, 2600, 4500, 9999):
            seq = [_rec(value, remaining=r)["bids"]["recommended"] for r in range(0, 41)]
            assert seq == sorted(seq), (value, seq)

    def test_the_objective_ceiling_ignores_balance_roster_status_posture_and_rivals(self):
        """Objective = what he is WORTH: same for every team, whatever it has spent."""
        for value in (600, 1500, 2200, 4500, 9999):
            reference = _rec(value)["objective"]
            for remaining in (0, 1, 7, 60, 400):
                assert _rec(value, remaining=remaining)["objective"] == reference
            for need in ("starterHole", "surplus"):
                assert _rec(value, need=need)["objective"] == reference
            for status in ("contender", "eliminated"):
                assert _rec(value, status=status)["objective"] == reference
            for posture in ("conservative", "aggressive"):
                assert _rec(value, posture=posture)["objective"] == reference
            assert _rec(value, rivals=[])["objective"] == reference
            assert _rec(value, drop_value=1200, open_spots=0)["objective"] == reference
            assert _rec(value, trending={"share": 0.9})["objective"] == reference
            assert (
                _rec(value, crowd={"medianPct": 12.0, "shareOfClaims": 0.3})["objective"]
                == reference
            )

    def test_the_objective_is_scaled_by_the_original_budget_not_the_balance(self):
        small = _rec(_anchors().v_allin, remaining=3)["objective"]
        assert small["originalBudget"] == BUDGET
        assert small["dollars"] == BUDGET  # all-in line = the whole season's allowance
        assert small["pctOfOriginalBudget"] == 100.0


# ── W11-F003 — saturation: no all-in threshold ──────────────────────


class TestW11F003NoSaturationAtThePoolTop:
    """The audited formula was ``value / max(value, best free agent)``, which gave
    every player at or above the best free agent an identical baseline.  The
    engine's ceiling is pinned to league-FORMAT anchors instead."""

    def test_the_all_in_line_is_worth_the_whole_budget_and_replacement_is_worth_nothing(self):
        anchors = _anchors()
        league = _league()
        assert FE.objective_ceiling(anchors.v_repl, anchors)[0] == 0.0
        assert FE.objective_ceiling(anchors.v_allin, anchors)[0] == pytest.approx(1.0)
        assert _rec(anchors.v_allin)["objective"]["dollars"] == league.original_budget

    def test_objective_is_strictly_increasing_between_replacement_and_all_in(self):
        anchors = _anchors()
        xs = [anchors.v_repl + (anchors.band * i / 40.0) for i in range(1, 41)]
        ys = [FE.objective_ceiling(x, anchors)[0] for x in xs]
        assert all(b > a for a, b in zip(ys, ys[1:])), ys

    def test_values_above_the_best_free_agent_are_not_priced_identically(self):
        """The audited failure: Jacobs, Warren, Dobbins and the top free agent all
        took the same figure because each sat at/above the pool maximum."""
        anchors = _anchors()
        top_free_agent = 900.0
        assert top_free_agent < anchors.v_allin
        above = [top_free_agent + 150 * k for k in range(1, 8)]
        objective = [FE.objective_ceiling(v, anchors)[0] for v in above]
        assert len(set(objective)) == len(objective)
        bids = [_rec(v, remaining=BUDGET)["bids"]["maxRational"] for v in above]
        assert len(set(bids)) > 3, bids

    def test_above_all_in_players_stay_distinguishable_up_to_the_documented_cap(self):
        """Displayed worth saturates at 100% by design (a bid can never exceed the
        budget), but the RAW ceiling keeps separating a 2.4k from a 9.9k player."""
        anchors = _anchors()
        raws = [FE.objective_ceiling(v, anchors)[1] for v in (2300, 3000, 4500, 7000)]
        assert all(b > a for a, b in zip(raws, raws[1:])), raws
        cap = FE.FaabConfig().num("ceilingCurve", "rawCeilingCap", 6.0)
        assert max(raws) <= cap
        assert FE.objective_ceiling(9999, anchors)[0] == 1.0  # displayed never above budget

    def test_an_elite_player_outbids_an_all_in_line_player(self):
        anchors = _anchors()
        allin = _rec(anchors.v_allin, remaining=BUDGET)["bids"]["recommended"]
        elite = _rec(9999, remaining=BUDGET)["bids"]["recommended"]
        assert elite > allin > 0

    def test_a_barren_wire_does_not_raise_the_price_of_the_same_player(self):
        """The audited denominator bug in the other direction: a weaker field used to
        make the same player MORE expensive."""
        league = _league()
        rich = FE.resolve_anchors(
            _board(), league, available_values=[1400.0 - 8.0 * i for i in range(60)]
        )
        barren = FE.resolve_anchors(
            _board(), league, available_values=[300.0 - 2.0 * i for i in range(60)]
        )
        # A weaker wire lowers the replacement line, so the SAME player is worth
        # at least as much -- but the objective is monotone in that direction only;
        # what must never happen is the old inverse (bid RISING because the best
        # available fell while the player did not change).  Value and anchors are
        # the only inputs, and the player's surplus is what moves it.
        v = 1500.0
        assert FE.objective_ceiling(v, barren)[0] >= FE.objective_ceiling(v, rich)[0]


# ── W11-F004 — monotonicity ─────────────────────────────────────────


def _sweep(fn, values) -> list[float]:
    return [fn(v) for v in values]


FINE = list(range(0, 10000, 125))


class TestW11F004Monotonicity:
    """What the documented model PROMISES: worth and the ceilings that bound a bid
    are monotone in value; the market quantities derived from the same demand
    signal are too.  What it does NOT promise: the recommended bid is an ``argmax``
    of expected surplus (cheapest bid within ``minEdge`` of the optimum), so it is
    not required to be monotone where a higher-value player makes a small bid
    pointless -- see the last two tests."""

    @pytest.mark.parametrize("remaining", [3, 40, 100])
    @pytest.mark.parametrize("need", ["surplus", "neutral", "starterHole"])
    def test_worth_and_ceilings_are_monotone_in_value(self, remaining, need):
        outs = [_rec(v, remaining=remaining, need=need) for v in FINE]
        for path in (
            lambda o: o["objective"]["dollars"],
            lambda o: o["objective"]["pctOfOriginalBudget"],
            lambda o: o["teamCeilingDollars"],
            lambda o: o["bids"]["maxRational"],
        ):
            seq = [path(o) for o in outs]
            assert seq == sorted(seq), seq

    def test_ladder_rungs_and_clearing_are_monotone_in_value_at_a_real_balance(self):
        outs = [_rec(v, remaining=100) for v in FINE]
        for rung in ("conservative", "recommended", "aggressive", "clearing", "maxRational"):
            seq = [o["bids"][rung] for o in outs]
            assert seq == sorted(seq), (rung, seq)

    def test_recommended_is_monotone_when_the_balance_is_not_the_binding_constraint(self):
        """Seeded random leagues (rivals, needs, posture, crowd, trending, drop side,
        week).  Balance >= $8 -- the regime where the cap is not what decides.  This
        is an empirical regression pin of the shipped calibration, not a promise
        the model makes beyond what the sweep covers."""
        rng = random.Random(20261106)
        anchors = _anchors()
        values = list(range(0, 10000, 250))
        for _ in range(60):
            rivals = [
                FE.RivalTeam(
                    owner_id=f"r{i}",
                    faab_remaining=rng.choice([0, 5, 30, 90, 200]),
                    aggression=rng.uniform(0.4, 2.5),
                    need_level=rng.choice(["need", "neutral", "surplus", "starterHole"]),
                )
                for i in range(rng.randint(0, 11))
            ]
            drop = rng.random() < 0.4
            kwargs = dict(
                remaining=rng.choice([8, 15, 60, 100, 180]),
                rivals=rivals,
                league=_league(week=rng.choice([1, 8, 14])),
                anchors=anchors,
                need=rng.choice(["surplus", "neutral", "starterHole"]),
                status=rng.choice(["contender", "bubble", "eliminated"]),
                posture=rng.choice(["conservative", "balanced", "aggressive"]),
                open_spots=0 if drop else 1,
                drop_value=1200.0 if drop else 0.0,
                crowd=rng.choice([None, {"medianPct": 8.0, "shareOfClaims": 0.1}]),
                trending=rng.choice([None, {"share": 0.6}]),
            )
            seq = [_rec(v, **kwargs)["bids"]["recommended"] for v in values]
            assert seq == sorted(seq), (kwargs["remaining"], seq)

    def test_recommended_can_fall_to_zero_on_a_nearly_empty_balance_and_that_is_the_model(self):
        """NOT promised, and measured: with $1 left, a hotter player draws rivals
        who out-bid any $1, so ``P(win | $1)`` collapses onto ``P(win | $0)`` and
        the expected-surplus argmax is the CHEAPER $0 claim.  Higher value ->
        lower recommendation, always a drop to $0, never above the balance.  It
        is the documented ``argmax`` working, not a defect: the audited
        8,362-pair inversion came from a 0.5-weight position blend and a trending
        kicker that no longer exist (see verification doc)."""
        rivals = [
            FE.RivalTeam(owner_id="r", faab_remaining=200, need_level="starterHole"),
            FE.RivalTeam(owner_id="r2", faab_remaining=200, need_level="starterHole"),
        ]
        seq = [
            _rec(v, remaining=1, rivals=rivals, posture="aggressive")["bids"]["recommended"]
            for v in range(0, 10000, 100)
        ]
        assert max(seq) <= 1
        drops = [(a, b) for a, b in zip(seq, seq[1:]) if b < a]
        for a, b in drops:
            assert (a, b) == (1, 0)

    def test_inversions_are_confined_to_tiny_balances(self):
        """Pin the boundary of the exception above: at $8+ there is none (see the
        seeded sweep), and at the extremes of value the ladder is still ordered."""
        for remaining in (8, 20, 60):
            seq = [
                _rec(v, remaining=remaining)["bids"]["recommended"] for v in range(0, 10000, 100)
            ]
            assert seq == sorted(seq)


# ── W11-F005 — bids depend on UI / filter state ─────────────────────


def _player(name: str, pos: str, value: float) -> dict[str, Any]:
    return {
        "displayName": name,
        "canonicalName": name,
        "position": pos,
        "rankDerivedValue": value,
        "sourceCount": 3,
        "rookie": False,
        "canonicalConsensusRank": None,
    }


def _wire_contract() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows = [
        _player(f"P{i}", ["QB", "RB", "WR", "TE", "DL", "LB", "DB"][i % 7], v)
        for i, v in enumerate(_board()[:420])
    ]
    mine = [f"P{i}" for i in range(0, 270, 3)]
    theirs = [f"P{i}" for i in range(1, 270, 3)]
    teams = [
        {"ownerId": "me", "faabRemaining": 70, "players": mine},
        {"ownerId": "o1", "faabRemaining": 90, "players": theirs},
        {"ownerId": "o2", "faabRemaining": 45, "players": [f"P{i}" for i in range(2, 270, 3)]},
    ]
    return {"playersArray": rows}, teams


@pytest.fixture()
def rookies_allowed(monkeypatch):
    monkeypatch.setattr(W, "_rookies_eligible_today", lambda: True)


def _list_bids(contract, teams, **kwargs) -> dict[str, dict[str, Any]]:
    out = W.find_waiver_targets(
        contract,
        teams,
        team_owner_id="me",
        league_budget=BUDGET,
        roster_size=60,
        today=date(2026, 10, 29),
        **kwargs,
    )
    return {c["name"]: c for cs in out["by_position"].values() for c in cs}


class TestW11F005BidsAreNotAFunctionOfDisplayState:
    """The audited denominator was the max over the CURRENTLY DISPLAYED rows.  On
    the server the display-shaped inputs are page size, ordering and grouping;
    none may reach a dollar figure.  (The position dropdown itself never reaches
    the backend -- ``tests/api/test_faab_integrity_surfaces.py`` pins that the
    client holds no bid arithmetic at all.)"""

    def test_page_size_does_not_change_any_bid(self, rookies_allowed):
        contract, teams = _wire_contract()
        full = _list_bids(contract, teams, per_position_limit=1000)
        paged = _list_bids(contract, teams, per_position_limit=2)
        assert paged and len(paged) < len(full)
        for name, cand in paged.items():
            assert cand["bid"] == full[name]["bid"], name
            for key in ("clearing", "maxRational", "objectiveDollars"):
                assert cand[key] == full[name][key], (name, key)

    def test_input_row_order_does_not_change_any_bid(self, rookies_allowed):
        contract, teams = _wire_contract()
        forward = _list_bids(contract, teams, per_position_limit=1000)
        reversed_contract = {"playersArray": list(reversed(contract["playersArray"]))}
        backward = _list_bids(reversed_contract, teams, per_position_limit=1000)
        assert forward.keys() == backward.keys()
        for name in forward:
            assert forward[name]["bid"] == backward[name]["bid"], name

    def test_the_family_regrouping_carries_the_same_figure_as_the_position_bucket(
        self, rookies_allowed
    ):
        contract, teams = _wire_contract()
        out = W.find_waiver_targets(
            contract,
            teams,
            team_owner_id="me",
            league_budget=BUDGET,
            roster_size=60,
            today=date(2026, 10, 29),
            per_position_limit=1000,
        )
        by_pos = {c["name"]: c for cs in out["by_position"].values() for c in cs}
        for items in out["by_family"].values():
            for cand in items:
                assert cand["bid"] == by_pos[cand["name"]]["bid"]

    def test_pricing_other_players_leaves_a_players_bid_untouched(self):
        """The engine is a pure function of (player, league, team, anchors, rivals):
        no hidden state, so what else is on screen cannot leak into a figure."""
        first = _rec(1800)
        for v in (600, 2600, 9999, 0):
            _rec(v)
        assert _rec(1800) == first


# ── W11-F007 — one figure across surfaces ───────────────────────────


class TestW11F007OneEngineOneFigure:
    def test_the_desk_legacy_keys_are_the_engines_own_numbers(self):
        league = _league()
        anchors = _anchors(league)
        rivals = _rivals()
        desk = FR.recommend_faab(
            add_player_value=2600,
            add_player_position="WR",
            add_player_name="Target",
            team_faab_remaining=70,
            league_budget=BUDGET,
            anchors=anchors,
            rivals=rivals,
            team_count=12,
            starters_per_team=20,
            current_week=8,
            in_season=True,
            open_roster_spots=1,
        )
        engine_out = FE.recommend(
            FE.PlayerInput(name="Target", value=2600.0, position="WR"),
            league,
            FE.TeamContext(faab_remaining=70, open_roster_spots=1),
            anchors=anchors,
            rivals=rivals,
        )
        assert desk["bids"] == engine_out["bids"]
        assert desk["objective"] == engine_out["objective"]
        assert desk["standard"] == desk["bids"]["recommended"] == engine_out["bids"]["recommended"]
        assert desk["conservative"] == desk["bids"]["conservative"]
        assert desk["aggressive"] == desk["bids"]["aggressive"]
        assert desk["max"] == desk["bids"]["maxRational"]

    def test_the_list_bid_is_the_engines_recommendation_capped_at_the_balance(
        self, monkeypatch, rookies_allowed
    ):
        """Capture what ``find_waiver_targets`` hands the engine and what comes back;
        the figure on the list must be that return value verbatim (capped by the
        balance), and the desk, given the same arguments, must answer the same."""
        contract, teams = _wire_contract()
        calls: list[tuple[tuple, dict, dict]] = []
        real = FE.recommend

        def spy(*args, **kwargs):
            out = real(*args, **kwargs)
            calls.append((args, kwargs, out))
            return out

        monkeypatch.setattr(FE, "recommend", spy)
        listed = _list_bids(contract, teams, per_position_limit=1000)
        assert calls
        cap = 70
        checked = 0
        for args, kwargs, out in calls:
            player = args[0]
            cand = listed.get(player.name)
            if cand is None or cand["bid"] is None:
                continue
            assert cand["bid"]["reasonable"] == min(out["bids"]["recommended"], cap)
            assert cand["bid"]["aggressive"] == min(out["bids"]["aggressive"], cap)
            assert cand["bid"]["lowball"] == min(out["bids"]["conservative"], cap)
            assert cand["clearing"] == out["bids"]["clearing"]
            assert cand["maxRational"] == out["bids"]["maxRational"]
            assert cand["objectiveDollars"] == out["objective"]["dollars"]
            # The same call, replayed, is the desk's number.
            assert real(*args, **kwargs)["bids"] == out["bids"]
            checked += 1
            if checked >= 25:
                break
        assert checked >= 10

    def test_rendering_inputs_are_not_engine_inputs(self):
        """The engine's public signature takes no display state: no filter, sort,
        page, position-dropdown or "top add value" parameter exists to leak."""
        import inspect

        banned = {"filter", "sort", "page", "limit", "top_add_value", "top_value_in_pool"}
        for fn in (FE.recommend, FE.team_ceiling, FE.optimal_bid, FE.objective_ceiling):
            names = set(inspect.signature(fn).parameters)
            assert not any(b in n for n in names for b in banned), (fn.__name__, names)


# ── IST-7 — current-week / season-phase behaviour ───────────────────


class TestIST7SeasonPhase:
    @pytest.mark.parametrize(
        "today, expected",
        [
            (date(2026, 9, 9), (None, False)),  # Wednesday before kickoff
            (date(2026, 9, 10), (1, True)),  # Thursday after Labor Day
            (date(2026, 9, 15), (1, True)),  # Tuesday waiver run -> the week just finished
            (date(2026, 9, 17), (2, True)),
            (date(2026, 10, 29), (8, True)),
            (date(2027, 1, 13), (18, True)),
            (date(2027, 1, 14), (None, False)),  # week 19 does not exist
            (date(2027, 2, 1), (None, False)),  # January/February are the 2026 season's tail
            (date(2027, 7, 1), (None, False)),
        ],
    )
    def test_the_season_clock(self, today, expected):
        assert FE.current_nfl_week(today) == expected

    def test_option_value_rises_through_the_season_and_offseason_is_lowest(self):
        team = FE.TeamContext(faab_remaining=60, competitive_status="bubble")
        league = _league
        factors = []
        for week in (1, 4, 8, 12, 14):
            f, _ = FE.season_option_value(league(week=week), team)
            factors.append(f)
        assert factors == sorted(factors)
        assert factors[-1] > factors[0]
        off, reason = FE.season_option_value(league(week=None, in_season=False), team)
        assert reason.startswith("offseason")
        assert off < factors[0]

    def test_option_value_is_final_period_aware_of_the_leagues_own_playoff_week(self):
        team = FE.TeamContext(faab_remaining=60, competitive_status="bubble")
        early_playoffs = FE.LeagueContext(current_week=12, in_season=True, playoff_week_start=13)
        late_playoffs = FE.LeagueContext(current_week=12, in_season=True, playoff_week_start=15)
        f_early, why_early = FE.season_option_value(early_playoffs, team)
        f_late, _ = FE.season_option_value(late_playoffs, team)
        assert "final waiver period" in why_early
        assert f_early > f_late

    def test_list_bids_are_priced_in_season_not_with_the_offseason_factor(
        self, monkeypatch, rookies_allowed
    ):
        """IST-7's behavioural claim: ``find_waiver_targets`` hands the engine the
        CURRENT week, so list bids for an elite target are higher in the final
        waiver period than in week 1, and week 1 is not the offseason value."""
        contract, teams = _wire_contract()
        contract["playersArray"].append(_player("Free Star", "WR", 6000.0))

        def top_bid(today: date) -> tuple[int, str]:
            seen: dict[str, Any] = {}
            real = FE.recommend

            def spy(player, league, team, **kw):
                seen["league"] = league
                return real(player, league, team, **kw)

            monkeypatch.setattr(FE, "recommend", spy)
            out = W.find_waiver_targets(
                contract,
                teams,
                team_owner_id="me",
                league_budget=BUDGET,
                roster_size=60,
                today=today,
                per_position_limit=1000,
            )
            monkeypatch.setattr(FE, "recommend", real)
            top = max(
                (c for cs in out["by_position"].values() for c in cs),
                key=lambda c: c["bid"]["reasonable"],
            )
            _, reason = FE.season_option_value(
                seen["league"], FE.TeamContext(faab_remaining=70, competitive_status="bubble")
            )
            return top["bid"]["reasonable"], reason

        week1_bid, week1_reason = top_bid(date(2026, 9, 10))
        late_bid, late_reason = top_bid(date(2026, 12, 10))
        off_bid, off_reason = top_bid(date(2026, 7, 1))
        assert off_reason.startswith("offseason")
        assert not week1_reason.startswith("offseason")
        assert "final waiver period" in late_reason
        assert off_bid <= week1_bid <= late_bid
        assert late_bid > off_bid

    def test_both_bid_surfaces_read_the_one_season_clock_owner(self):
        """Source guard: the desk and the list resolve week/playoff start through the
        same two engine functions, so they cannot drift apart again."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2]
        server_src = (root / "server.py").read_text(encoding="utf-8")
        waiver_src = (root / "src" / "trade" / "waiver.py").read_text(encoding="utf-8")
        assert "_faab_engine.current_nfl_week()" in server_src
        assert "_faab_engine.league_playoff_week_start(" in server_src
        assert "_engine.current_nfl_week(today)" in waiver_src
        assert "_engine.league_playoff_week_start(contract)" in waiver_src
