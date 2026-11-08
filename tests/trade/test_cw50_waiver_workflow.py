"""CW-50 — waiver recommendation workflow, verified against intended behaviour.

Owner directive 2026-11-07 (sitewide feature verification): *"A waiver
recommendation must respect the actual eligible players, available FAAB,
roster capacity, dynasty protection rules, and NO TRANSACTION alternative."*

Every expectation below is written by hand from a tiny league built in the
test — no production function is called to produce an expected value.  The
canonical owners exercised:

* ``src/trade/waiver.py::find_waiver_targets`` — the ONE add pool
  (``/api/waiver/suggestions``, ``/api/waiver/perfect``, ``/api/waiver/advisor``
  and ``/api/waiver/streaming`` all read it);
* ``src/trade/perfect_waivers.py::build_perfect_waivers`` — the joint plan.

Record: ``docs/engineering/CW50_WAIVER_WORKFLOW_VERIFICATION_2026-11-07.md``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.trade import waiver as w
from src.trade.perfect_waivers import build_perfect_waivers

# ── fixtures ─────────────────────────────────────────────────────────

# An offense-only Superflex lineup: no DL / LB / DB / IDP_FLEX slot at all.
OFFENSE_ONLY = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "SFLEX": 1}
# The same lineup plus one dedicated slot per defensive family.
WITH_IDP = {**OFFENSE_ONLY, "DL": 1, "LB": 1, "DB": 1}


def _p(name: str, pos: str, value: float | None, *, sources: int = 3, **extra: Any) -> dict:
    return {
        "playerId": f"id-{name.lower().replace(' ', '-')}",
        "displayName": name,
        "canonicalName": name,
        "position": pos,
        "rankDerivedValue": value,
        "sourceCount": sources,
        "rookie": False,
        **extra,
    }


def _wire() -> list[dict]:
    """Four free agents: three defenders and one receiver."""
    return [
        _p("Free Lb", "LB", 3000),
        _p("Free De", "DE", 2900),
        _p("Free Cb", "CB", 2800),
        _p("Free Wr", "WR", 1800),
    ]


def _contract(*players: dict, roster_positions: list[str] | None = None) -> dict:
    sleeper: dict[str, Any] = {"teams": []}
    if roster_positions is not None:
        sleeper["rosterPositions"] = roster_positions
    return {"playersArray": list(players), "sleeper": sleeper}


def _offered(result: dict) -> set[str]:
    return {c["name"] for items in result["by_position"].values() for c in items}


@pytest.fixture(autouse=True)
def _rookie_window_open(monkeypatch):
    # The rookie gate keys off the calendar; nothing here is a rookie, but pin
    # it so the census never depends on the month the suite runs in.
    monkeypatch.setattr(w, "_rookies_eligible_today", lambda: True)


# ── 1. eligible players: a position the league cannot start is not a claim ──


class TestTheAddPoolOnlyOffersPositionsTheLeagueStarts:
    """A defender is not a waiver pickup in a league with no defensive slot.

    The /waivers page already gates IDP rows on the league's ``idpEnabled``
    (``frontend/lib/waiver-logic.js::buildCandidatePool``); the backend add
    pool that Perfect Waivers, the Waiver Advisor and the suggestions list
    read did not, so an offense-only league was offered linebackers.
    """

    def test_offense_only_league_is_not_offered_defenders(self):
        out = w.find_waiver_targets(_contract(*_wire()), [], starters=OFFENSE_ONLY)
        assert _offered(out) == {"Free Wr"}
        assert out["positionEligibility"]["state"] == "league_slots"
        assert out["positionEligibility"]["excluded"] == 3

    def test_idp_league_is_offered_every_family(self):
        out = w.find_waiver_targets(_contract(*_wire()), [], starters=WITH_IDP)
        assert _offered(out) == {"Free Lb", "Free De", "Free Cb", "Free Wr"}
        assert out["positionEligibility"]["excluded"] == 0

    def test_an_idp_flex_alone_makes_every_defender_startable(self):
        starters = {**OFFENSE_ONLY, "IDP_FLEX": 1}
        out = w.find_waiver_targets(_contract(*_wire()), [], starters=starters)
        assert _offered(out) == {"Free Lb", "Free De", "Free Cb", "Free Wr"}

    def test_a_tight_end_with_no_te_slot_still_fills_the_flex(self):
        starters = {"QB": 1, "RB": 1, "WR": 1, "FLEX": 1}
        contract = _contract(_p("Free Te", "TE", 2000), _p("Free Lb", "LB", 3000))
        out = w.find_waiver_targets(contract, [], starters=starters)
        assert _offered(out) == {"Free Te"}

    def test_the_live_lineup_outranks_the_registry(self):
        """Truth ladder (``lineup.resolve_starter_slots``): live host first."""
        contract = _contract(*_wire(), roster_positions=["QB", "RB", "WR", "SUPER_FLEX", "BN"])
        out = w.find_waiver_targets(contract, [], starters=WITH_IDP)
        assert _offered(out) == {"Free Wr"}
        assert out["positionEligibility"]["slotSource"] == "sleeper_roster_positions"

    def test_an_unknown_lineup_is_unverified_not_offense_only(self):
        """No slots resolved: nothing is excluded for position, and it says so."""
        out = w.find_waiver_targets(_contract(*_wire()), [], starters=None)
        assert _offered(out) == {"Free Lb", "Free De", "Free Cb", "Free Wr"}
        assert out["positionEligibility"]["state"] == "unverified"

    def test_the_shared_census_counts_the_not_started_reason(self):
        census = w.waiver_pool_exclusion_census(
            _wire(), starter_slots=["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"]
        )
        assert census == {"position_not_started": 3}

    def test_rostered_and_own_players_are_never_offered(self):
        contract = _contract(*_wire())
        teams = [
            {"ownerId": "me", "players": ["Free Wr"]},
            {"ownerId": "them", "players": ["Free Lb"]},
        ]
        out = w.find_waiver_targets(contract, teams, starters=WITH_IDP)
        assert _offered(out) == {"Free De", "Free Cb"}


# ── 2. available FAAB: no bid above the balance; unknown is labelled ──────


def _league_teams(my_balance: Any) -> list[dict]:
    me: dict[str, Any] = {"ownerId": "me", "name": "Mine", "players": ["Bench Qb"]}
    if my_balance is not ...:
        me["faabRemaining"] = my_balance
    return [
        me,
        {"ownerId": "r1", "name": "R1", "players": ["Their Qb"], "faabRemaining": 90},
        {"ownerId": "r2", "name": "R2", "players": [], "faabRemaining": 70},
    ]


def _bid_contract() -> dict:
    board = [_p(f"Filler {i}", "WR", 9000 - 30 * i) for i in range(200)]
    return _contract(
        _p("Elite Wr", "WR", 9500),
        _p("Bench Qb", "QB", 4000),
        _p("Their Qb", "QB", 7000),
        *board,
    )


def _bids(out: dict) -> list[int]:
    vals: list[int] = []
    for items in out["by_position"].values():
        for c in items:
            for k in ("aggressive", "reasonable", "lowball"):
                if c["bid"] and c["bid"][k] is not None:
                    vals.append(int(c["bid"][k]))
    return vals


class TestEveryBidRespectsTheBalanceAndSaysWhereItCameFrom:
    """One published balance state: ``faabBudget`` (#2138's field; #2136's
    ``faabBalance`` was folded into it on reconciliation, never shipped beside it)."""

    def test_known_roster_balance_caps_every_bid_and_is_stamped(self):
        out = w.find_waiver_targets(
            _bid_contract(), _league_teams(7), team_owner_id="me", starters=OFFENSE_ONLY
        )
        assert max(_bids(out)) <= 7
        assert out["faabBudget"] == {
            "state": "known",
            "balance": 7,
            "originalBudget": 100,
            "bidsWithheld": False,
            "reason": None,
            "source": "roster",
            "requestedBalance": None,
            "observedBalance": 7,
        }

    def test_a_stale_requested_balance_never_lifts_the_cap_above_the_observed_one(self):
        """Client sent $50 (its baked contract); the live roster says $10."""
        out = w.find_waiver_targets(
            _bid_contract(),
            _league_teams(10),
            team_owner_id="me",
            starters=OFFENSE_ONLY,
            user_faab_remaining=50,
        )
        assert max(_bids(out)) <= 10
        budget = out["faabBudget"]
        assert budget["balance"] == 10
        assert budget["source"] == "roster"
        assert budget["requestedBalance"] == 50
        assert budget["observedBalance"] == 10

    def test_a_lower_requested_balance_still_caps_below_the_roster(self):
        """The other direction: the request is the lower observation, so it binds."""
        out = w.find_waiver_targets(
            _bid_contract(),
            _league_teams(60),
            team_owner_id="me",
            starters=OFFENSE_ONLY,
            user_faab_remaining=4,
        )
        assert max(_bids(out)) <= 4
        assert out["faabBudget"]["balance"] == 4
        assert out["faabBudget"]["source"] == "request"

    def test_unknown_balance_is_labelled_unknown_never_presented_as_known(self):
        out = w.find_waiver_targets(
            _bid_contract(), _league_teams(...), team_owner_id="me", starters=OFFENSE_ONLY
        )
        budget = out["faabBudget"]
        assert budget["state"] == "unknown"
        assert budget["balance"] is None
        assert budget["source"] is None
        assert budget["observedBalance"] is None

    def test_known_zero_stays_zero(self):
        out = w.find_waiver_targets(
            _bid_contract(), _league_teams(0), team_owner_id="me", starters=OFFENSE_ONLY
        )
        assert max(_bids(out)) == 0
        assert out["faabBudget"]["state"] == "known"
        assert out["faabBudget"]["balance"] == 0

    def test_an_overspent_roster_is_a_known_zero_with_the_raw_figure_beside_it(self):
        out = w.find_waiver_targets(
            _bid_contract(), _league_teams(-5), team_owner_id="me", starters=OFFENSE_ONLY
        )
        assert max(_bids(out)) == 0
        budget = out["faabBudget"]
        assert budget["state"] == "known"
        assert budget["balance"] == 0
        assert budget["observedBalance"] == -5


# ── 3–5. Perfect Waivers: capacity, protection, NO TRANSACTION, balance ──


def _pw_row(pid: str, name: str, pos: str, value: float | None) -> dict:
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": "XX",
        "rankDerivedValue": value,
        "sourceCount": 3,
        "assetClass": "offense",
    }


def _pw_contract(*, faab: Any = 50, wire_value: float = 2600) -> dict:
    return {
        "meta": {"leagueKey": "pw"},
        "playersArray": [
            _pw_row("qb1", "Star Qb", "QB", 8000),
            _pw_row("te1", "Weak Te", "TE", 900),
            _pw_row("wr1", "Deep Wr", "WR", 400),
            _pw_row("fa1", "Free Te", "TE", wire_value),
        ],
        "sleeper": {
            "rosterPositions": ["QB", "TE", "BN", "BN"],
            "teams": [
                {
                    "ownerId": "me",
                    "name": "Mine",
                    "roster_id": 1,
                    "players": ["Star Qb", "Weak Te", "Deep Wr"],
                    "playerIds": [],
                    "faabRemaining": faab,
                },
            ],
        },
    }


def _pw_targets(contract: dict, bid: int) -> dict:
    return {
        "bidMethodology": "market_aware",
        "by_position": {
            "TE": [
                {
                    "name": "Free Te",
                    "position": "TE",
                    "bid": {"aggressive": bid, "reasonable": bid, "lowball": bid},
                }
            ]
        },
    }


def _pw(contract: dict, *, bid: int = 0, roster_size: int = 3, constraints: Any = None) -> dict:
    return build_perfect_waivers(
        contract,
        league_key="pw",
        owner_id="me",
        waiver_targets=_pw_targets(contract, bid),
        constraints=constraints,
        roster_settings={"rosterSize": roster_size},
    )


class TestPerfectWaiversAgainstTheOwnersExample:
    def test_full_roster_claim_names_the_release_it_forces(self):
        # 3-man cap, 3 rostered: adding Free Te (2600) must displace someone.
        # The only legal release is Deep Wr or Weak Te (Star Qb fills QB);
        # the plan must name one, never an open spot.
        out = _pw(_pw_contract())
        (move,) = out["plan"]["moves"]
        assert move["add"]["name"] == "Free Te"
        assert move["release"]["kind"] == "drop"
        assert move["release"]["name"] in {"Deep Wr", "Weak Te"}
        assert move["release"]["value"] in {400, 900}

    def test_protected_player_is_never_the_release(self):
        from src.trade.constraints import resolve_constraints

        contract = _pw_contract()
        cons = resolve_constraints(contract=contract, persistent={"untouchables": ["Deep Wr"]})
        out = _pw(contract, constraints=cons)
        released = {m["release"].get("name") for m in out["plan"]["moves"]}
        assert "Deep Wr" not in released

    def test_no_transaction_wins_when_nothing_is_material(self):
        """A wire player worth no more than the cheapest release: stand pat."""
        out = _pw(_pw_contract(wire_value=410))
        assert out["plan"]["moves"] == []
        assert out["plan"]["addCount"] == 0
        assert out["plan"]["netValueGain"] == 0

    def test_an_overspent_balance_is_known_and_spends_nothing(self):
        """Sleeper can report a negative balance; that is a KNOWN $0, not unknown."""
        out = _pw(_pw_contract(faab=-5), bid=3)
        assert out["budget"]["state"] == "known"
        assert out["budget"]["balance"] == 0
        assert out["plan"]["totalRecommendedBid"] == 0
