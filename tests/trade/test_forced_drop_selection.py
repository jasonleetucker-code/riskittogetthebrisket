"""Forced-drop fix (flag ``forced_drop_cheapest_legal``) — the rule, adversarially.

Owner decision 2026-10-20 §2.  The incumbent selected the forced cut by
Effective Cut Cost (0 for every sub-waiver player, so ties fell to NAME order)
and charged it at full ``base x scarcity``.  Under the flag the cut is the
cheapest LINEUP-LEGAL set by that same charge, a just-acquired release is
removed from the package instead of charged its raw value, unpriced drops are
charged at the documented ``assumedWaiver`` ceiling (never excluded), and the
charge is marginal to the trade.  Record: ``docs/trade/FORCED_DROP_FIX_2026-10-20.md``.

Synthetic leagues throughout (``tests/trade/forced_drop_reference.py`` plus
small random rosters for the brute-force properties); nothing reads the live
board.
"""

from __future__ import annotations

import copy
import dataclasses
import itertools
import random

import pytest

from src.api import feature_flags, terminal, trade_simulator
from src.draft import displacement as DP
from src.draft.context import build_roster_context
from src.league_intel.replacement import ScarcityComponents
from src.trade import forced_drop_selection as fds
from src.trade import analyze_trade as AT
from src.trade import roster_capacity as RC
from src.trade import trade_decision as TD
from src.trade.analyze_trade import analyze_trade
from src.valuation_math.package_model import adjusted_pair_totals
from tests.trade import forced_drop_reference as R

ENV = "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL"


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv(ENV, "1")
    feature_flags.reload()
    assert fds.enabled()
    yield
    monkeypatch.delenv(ENV, raising=False)
    feature_flags.reload()


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    feature_flags.reload()
    assert not fds.enabled()
    yield
    feature_flags.reload()


def _ctx(settings=None, **kw):
    c = R.contract(**kw)
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    return c, us, RC.build_capacity_context(c, None, us, roster_settings=settings or R.SETTINGS)


def _names(cap):
    return sorted(d.name for d in cap.forced_drops)


# ── The flag is a real switch, default OFF ─────────────────────────────


def test_flag_is_registered_off_and_live():
    assert feature_flags._DEFAULTS["forced_drop_cheapest_legal"] is False
    assert feature_flags.gate_status("forced_drop_cheapest_legal") == feature_flags.LIVE


def test_flag_off_keeps_the_alphabetical_incumbent(flag_off):
    """Pins the defect the flag exists to fix, so the comparison stays honest."""
    _c, _us, ctx = _ctx()
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                    outgoing_players=["WR Two"])  # fmt: skip
    assert _names(cap) == ["DB Archer"]  # 1,100 — first by name, not by value
    assert "forcedDropCharge" not in cap.to_dict()


# ── 1. No alphabetical selection among sub-waiver players ──────────────


def test_ties_on_ecc_are_broken_by_cost_not_name(flag_on):
    _c, _us, ctx = _ctx()
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                    outgoing_players=["WR Two"])  # fmt: skip
    # Every candidate here has ECC 0; the cheapest is WR Zed (300), last by name.
    assert _names(cap) == ["WR Zed"]
    assert cap.forced_drops[0].effective_cut_cost == 0.0
    assert cap.forced_drop_release_cost == 300.0
    d = cap.to_dict()
    assert d["forcedDropCharge"] == 300.0
    assert d["forcedDropSelection"]["rule"] == fds.RULE_ID
    assert d["rungOrderWasTied"] is False


def test_multiple_drops_climb_the_ladder_cheapest_first(flag_on):
    _c, _us, ctx = _ctx()
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=["Filler RB", "Filler WR", "Filler LB"], outgoing_players=[]
    )
    assert [d.name for d in cap.forced_drops] == ["WR Zed", "RB Young", "QB Zulu"]
    assert [d.rung for d in cap.forced_drops] == [1, 2, 3]
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 1050.0 and basis["state"] == "exact"


# ── 2. Lineup legality is the canonical solver's ───────────────────────


def test_a_cheaper_player_the_lineup_needs_is_never_cut(flag_on):
    """Remove every spare DB but one: the two DB starters + DB Archer (1,100)
    — all three are then required (2 DB slots + nobody else can play DB is
    false: only 2 DB slots) — so make DB Archer the cheapest by far and the
    sole DB depth while a DB starter leaves in the trade."""
    c, us, ctx = _ctx()
    # Trade away a DB starter: DB Archer (1,100) becomes a required starter.
    cap = RC.assess_roster_capacity(
        ctx,
        incoming_players=["Star WR", "Filler RB", "Filler WR"],
        outgoing_players=["DB One"],
    )
    assert "DB Archer" not in _names(cap)
    # And the selection still equals the brute-force legal minimum.
    bf = _Brute(ctx, cap, ["Star WR", "Filler RB", "Filler WR"], ["DB One"])
    assert cap.forced_drop_release_cost == pytest.approx(min(bf.own(S) for S in bf.legal))


# ── 3. Unpriced players: never silently zero ───────────────────────────


def _all_unpriced_bench_contract():
    """Starters priced; every bench player unpriced (on the board, no value)."""
    c = R.contract()
    priced_starters = {
        "QB Alpha", "QB Bravo", "RB Starter One", "RB Starter Two", "WR One", "WR Two",
        "WR Three", "TE One", "DL One", "DL Two", "LB One", "LB Two", "DB One", "DB Two",
    }  # fmt: skip
    for row in c["playersArray"]:
        if row.get("displayName") in {n for n, _v, _p in R.US} - priced_starters:
            row.pop("rankDerivedValue", None)
            row.pop("values", None)
    return c


def test_an_all_unpriced_bench_is_charged_at_assumed_waiver_never_zero(flag_on):
    c = _all_unpriced_bench_contract()
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Their QB"], outgoing_players=[])
    (drop,) = cap.forced_drops
    assert drop.value is None and drop.value_basis == "assumedWaiver"
    assert drop.release_cost == drop.waiver_value * drop.scarcity_multiplier > 0
    # The cheapest assumed ceiling on the board is TE's (1,400) — chosen by
    # cost.  The identity miss ("Ghost Guy", no position) falls back to the
    # cheapest positional ceiling too, and ties with TE Backup; the tie breaks
    # on player id, never on value or on a guess.
    assert drop.release_cost == 1400.0
    assert drop.name == "Ghost Guy" and drop.position == ""
    cost, basis = RC.forced_drop_cost(cap)
    # Charged, counted, and the SAME number the War Room reads.
    assert cost == 1400.0
    assert basis["assumedWaiverDrops"] == 1
    assert "unpriced_forced_drops_excluded" not in basis.get("lowerBoundReasons", [])
    assert cap.to_dict()["forcedDropCharge"] == 1400.0
    assert cap.unpriced_forced_drops == 1


def test_an_unpriced_player_is_cut_only_when_no_priced_option_is_cheaper(flag_on):
    _c, _us, ctx = _ctx()
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=["Filler RB", "Filler WR", "Filler LB"], outgoing_players=[]
    )
    assert all(d.value is not None for d in cap.forced_drops)  # DL Adams / Ghost kept


def test_incumbent_finder_rule_excluded_unpriced_as_zero(flag_off):
    """The inconsistency the flag removes, pinned on the incumbent."""
    c = _all_unpriced_bench_contract()
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Their QB"], outgoing_players=[])
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 0.0 and "unpriced_forced_drops_excluded" in basis["lowerBoundReasons"]
    assert cap.forced_drop_release_cost > 0  # ...while the War Room charged it


# ── 4. Incoming pieces and package consistency ─────────────────────────


def _pkg(c, pin, pout, picks_out=()):
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    sim = trade_simulator.simulate_trade(
        copy.deepcopy(c), resolved_team=us, players_in=list(pin), players_out=list(pout),
        picks_out=list(picks_out), roster_settings=R.SETTINGS, league_key=None,
    )  # fmt: skip
    return sim


def _objective(sim):
    """War Room Component A (``trade_decision._objective_value``) over the
    production lenses — what the decision subtracts.  (The whole packet stops at
    the evidence gate here: no roster-utility projection in a synthetic league.)
    """
    return TD._objective_value(AT._market_lens(sim), AT._feasibility_lens(sim))


def test_the_packet_carries_the_owner_charge(flag_on):
    sim = _pkg(R.contract(), ["Star WR", "Filler RB", "Filler WR"], ["WR Two"])
    packet = analyze_trade({**copy.deepcopy(sim), "teamContext": {"applied": True}})
    feas = packet["lenses"]["feasibility"]["detail"]
    assert feas["forcedDropCharge"] == sim["rosterCapacity"]["forcedDropCharge"] == 574.0
    # The UI can tell a package credit from a player's worth (review fix E).
    a = _objective(sim)
    assert a["forcedReleaseChargeBasis"] == "mixed"
    assert a["forcedReleaseChargeState"] == "exact"
    assert feas["forcedDropSelection"]["packageApplied"] is True
    assert [d["chargeBasis"] for d in feas["forcedDrops"]] == [
        fds.CHARGE_PACKAGE,
        fds.CHARGE_RELEASE,
    ]


def test_without_a_package_an_incoming_filler_is_a_candidate_at_raw_cost(flag_on):
    c, _us, ctx = _ctx(extra_us=(("WR Extra", 500.0, "WR"),))
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=["Filler RB", "Filler WR", "Filler LB"], outgoing_players=[]
    )
    filler = [d for d in cap.forced_drops if d.acquired_in_trade]
    assert [d.name for d in filler] == ["Filler RB"]
    assert filler[0].charge_basis == fds.CHARGE_NO_PACKAGE
    assert filler[0].release_cost == 450.0


def test_a_released_acquired_piece_is_removed_from_the_package_not_charged(flag_on):
    """1-for-3: the third piece's package credit is below every rostered cut,
    so the receiver releases the piece it just acquired — and that costs it
    exactly the credit the package gave it, never its raw value as well."""
    c = R.contract()
    sim = _pkg(c, ["Star WR", "Filler RB", "Filler WR"], ["WR Two"])
    rc = sim["rosterCapacity"]
    acquired = [d for d in rc["forcedDrops"] if d["acquiredInTrade"]]
    assert [d["name"] for d in acquired] == ["Filler RB"]
    assert acquired[0]["chargeBasis"] == fds.CHARGE_PACKAGE
    full = adjusted_pair_totals([5500.0], [6800.0, 650.0, 450.0])
    without = adjusted_pair_totals([5500.0], [6800.0, 650.0])
    credit = (full[1] - full[0]) - (without[1] - without[0])
    assert acquired[0]["releaseCost"] == round(credit, 1) < 450.0
    assert rc["forcedDropSelection"]["packageApplied"] is True

    # No double counting: the War Room's net equals the gap of the package
    # WITHOUT the released piece minus the existing-roster releases only.
    a = _objective(sim)
    existing = sum(d["releaseCost"] for d in rc["forcedDrops"] if not d["acquiredInTrade"])
    assert a["netGap"] == round((without[1] - without[0]) - existing)
    assert a["forcedReleaseCost"] == round(rc["forcedDropCharge"])


def test_unpriced_incoming_is_never_the_free_first_cut(flag_on):
    """Review fix D.  The market lens never credited "Unpriced DB" (unpricedIn),
    so releasing him forgoes no package credit — but he is NOT free: he is
    costed and charged at the ``assumedWaiver`` ceiling like any unpriced
    player (DB waiver 1,600 here), so the priced WR Zed (300) is the cut."""
    c = R.contract()
    sim = _pkg(c, ["Star WR", "Unpriced DB"], ["WR Three"])
    (drop,) = sim["rosterCapacity"]["forcedDrops"]
    assert drop["name"] == "WR Zed" and drop["releaseCost"] == 300.0
    assert sim["rosterCapacity"]["forcedDropChargeBasis"]["state"] == "exact"


def _asset(pid, value, pos="WR"):
    return DP.RosterAsset(player_id=pid, name=pid, position=pos, board_value=value)


@pytest.mark.parametrize("mode", [fds.MODE_PACKAGE_CONSISTENT, fds.MODE_ROSTER_RATIONAL])
def test_unpriced_incoming_released_is_charged_assumed_waiver_and_counted(flag_on, mode):
    """When the uncredited incoming piece IS the cheapest legal cut, it is
    charged its own ``c`` at the waiver ceiling (``release_value_uncredited``),
    counted in ``assumedWaiverDrops`` and the basis is ``assumed`` (an upper
    bound), never ``exact`` and never 0."""
    existing = [_asset("e1", 2000.0), _asset("e2", 2500.0)]
    incoming = [_asset("star", 3000.0), _asset("ghost", None, "WR")]
    package = fds.PackageSides(sending=(3000.0,), receiving=(("star", 3000.0), ("ghost", None)))
    sel = fds.select_forced_drops(
        existing, incoming, ["star", "ghost"], drops_needed=1, starter_slots=[],
        waiver_values={"WR": 900.0}, scarcity=None, slot_eligibility=None,
        package=package, mode=mode,
    )  # fmt: skip
    (drop,) = sel.drops
    assert drop.asset.player_id == "ghost" and drop.acquired
    assert drop.charge_basis == fds.CHARGE_UNCREDITED
    assert drop.charge == 900.0 and drop.value_basis == "assumedWaiver"
    cap = RC.RosterCapacity(
        roster_limit=3, taxi_size=0, size_before=3, size_after=4, incoming=2, outgoing=1,
        open_spots_before=0, open_spots_after=0, over_limit_before=0, over_limit_after=1,
        certainty="exact", over_limit_after_min=1, over_limit_after_max=1,
        forced_drops=[RC.ForcedDrop(
            player_id="ghost", name="ghost", position="WR", value=None,
            effective_cut_cost=0.0, release_cost=drop.charge, waiver_value=900.0,
            scarcity_multiplier=1.0, value_basis="assumedWaiver", rung=1,
            acquired_in_trade=True, charge_basis=drop.charge_basis,
        )],
        selection_rule=fds.rule_id(mode),
    )  # fmt: skip
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 900.0
    assert basis["assumedWaiverDrops"] == 1
    assert basis["state"] == "assumed" and basis["bound"] == "upper"


def test_assumed_state_reaches_the_war_room_and_the_finder_alike(flag_on):
    """An all-unpriced bench: the cut is an ``assumedWaiver`` player, so the
    capacity basis (what the Finder publishes) and the War Room objective both
    say ``assumed``."""
    c = _all_unpriced_bench_contract()
    sim = _pkg(c, ["Their QB"], [])
    rc = sim["rosterCapacity"]
    assert rc["forcedDropChargeBasis"]["state"] == "assumed"
    a = _objective(sim)
    assert a["forcedReleaseChargeState"] == "assumed"
    assert a["forcedReleaseChargeBasis"] == "release_value"


def test_a_label_the_package_does_not_name_falls_back_with_a_note(flag_on):
    _c, _us, ctx = _ctx()
    package = fds.PackageSides(sending=(5500.0,), receiving=((None, 3000.0),))
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=["Star WR", "Filler RB"], outgoing_players=["WR Two"], package=package
    )
    assert cap.package_applied is False
    assert any("does not name every incoming player" in n for n in cap.notes)


# ── 5. League rules carried over unchanged ─────────────────────────────


def test_already_over_limit_roster_pays_only_what_the_trade_adds(flag_on):
    c, _us, ctx = _ctx(extra_us=(("WR Extra", 500.0, "WR"),))
    # No trade at all: the roster's own overage is not a trade cost.
    cap0 = RC.assess_roster_capacity(ctx)
    assert cap0.over_limit_before == 1
    assert RC.forced_drop_cost(cap0) == (0.0, RC.forced_drop_cost(cap0)[1])
    assert RC.forced_drop_cost(cap0)[1]["state"] == "none"
    # A 1-for-2 adds exactly one release: the second-cheapest (RB Young 350),
    # because WR Zed (300) was owed anyway.
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                    outgoing_players=["WR Two"])  # fmt: skip
    assert cap.pre_trade_cleanup_cost == 300.0
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 350.0 and basis["state"] == "exact"
    assert cap.to_dict()["forcedDropMarginal"] == 350.0
    assert "marginalClamp" not in basis


def test_relief_of_an_over_limit_roster_is_published_signed_never_credited(flag_on):
    """Review fix C.  One over the cap, sends two and receives one: the trade
    SPARES the roster the cut it owed (WR Zed, 300).  The charge stays clamped
    at 0 (``conservative_clamp``); the signed marginal is published."""
    _c, _us, ctx = _ctx(extra_us=(("WR Extra", 500.0, "WR"),))
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR"],
                                    outgoing_players=["WR Two", "WR Three"])  # fmt: skip
    assert cap.over_limit_before == 1 and cap.over_limit_after == 0
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 0.0 and basis["state"] == "none"
    assert basis["signedMarginal"] == -300.0
    assert basis["marginalClamp"] == "conservative_clamp"
    d = cap.to_dict()
    assert d["forcedDropCharge"] == 0.0 and d["forcedDropMarginal"] == -300.0
    # Two over, sends two, receives one: still one owed, but the cheaper one.
    _c, _us, ctx2 = _ctx(extra_us=(("WR Extra", 500.0, "WR"), ("WR Extra Two", 520.0, "WR")))
    cap2 = RC.assess_roster_capacity(ctx2, incoming_players=["Star WR"],
                                     outgoing_players=["WR Two", "WR Three"])  # fmt: skip
    assert cap2.over_limit_before == 2 and cap2.over_limit_after == 1
    cost2, basis2 = RC.forced_drop_cost(cap2)
    assert cost2 == 0.0 and basis2["marginalClamp"] == "conservative_clamp"
    assert basis2["signedMarginal"] == -350.0  # 300 owed after vs 300 + 350 before


# ── Re-review: incomplete / undeterminable cleanups are never exact ─────


def _over_limit_caps():
    """``(adds, spared)``: one-over roster + a 1-for-2 that ADDS a release
    (marginal 350, exact), and a two-over roster + a 2-for-1 whose netted
    marginal is <= 0 while drops are still required."""
    _c, _us, ctx = _ctx(extra_us=(("WR Extra", 500.0, "WR"),))
    adds = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                     outgoing_players=["WR Two"])  # fmt: skip
    _c, _us, ctx2 = _ctx(extra_us=(("WR Extra", 500.0, "WR"), ("WR Extra Two", 520.0, "WR")))
    spared = RC.assess_roster_capacity(ctx2, incoming_players=["Star WR"],
                                       outgoing_players=["WR Two", "WR Three"])  # fmt: skip
    assert RC.forced_drop_marginal(adds) == 350.0
    assert RC.forced_drop_marginal(spared) == -350.0
    assert spared.requires_drops is True
    return adds, spared


@pytest.mark.parametrize("field", ["ladder_exhausted", "pre_trade_cleanup_exhausted"])
def test_an_exhausted_cleanup_publishes_no_signed_marginal(flag_on, field):
    """Finding 1a: a cleanup that stops short of legal size is not an exact
    signed marginal — on either side of the difference."""
    for cap in _over_limit_caps():
        ex = dataclasses.replace(cap, **{field: True})
        assert RC.forced_drop_marginal(ex) is None
        assert ex.to_dict()["forcedDropMarginal"] is None
        _cost, basis = RC.forced_drop_cost(ex)
        assert "signedMarginal" not in basis and "marginalClamp" not in basis


def test_an_exhausted_ladder_never_reads_as_an_exact_zero(flag_on):
    """Finding 1b: the netted marginal is <= 0 but the post-trade cleanup ran
    out of legal releases — a lower bound, never ``state: none``."""
    _adds, spared = _over_limit_caps()
    assert RC.forced_drop_cost(spared)[1]["state"] == "none"
    cost, basis = RC.forced_drop_cost(dataclasses.replace(spared, ladder_exhausted=True))
    assert cost == 0.0
    assert basis["state"] == "lower_bound" and basis["bound"] == "lower"
    assert "cut_ladder_exhausted" in basis["lowerBoundReasons"]


def test_an_exhausted_pre_trade_cleanup_is_an_upper_bound(flag_on):
    """Finding 1c: the netted pre-trade cost understates what the roster owed,
    so the marginal is an UPPER bound, named ``pre_trade_cleanup_exhausted``."""
    adds, spared = _over_limit_caps()
    for cap, expected in ((adds, 350.0), (spared, 0.0)):
        cost, basis = RC.forced_drop_cost(
            dataclasses.replace(cap, pre_trade_cleanup_exhausted=True)
        )
        assert cost == expected
        assert basis["state"] == "assumed" and basis["bound"] == "upper"
        assert basis["upperBoundReasons"] == ["pre_trade_cleanup_exhausted"]
        assert basis["preTradeCleanupExhausted"] is True
    # Combined with a lower-bound reason: mixed.
    cost, basis = RC.forced_drop_cost(
        dataclasses.replace(adds, pre_trade_cleanup_exhausted=True, ladder_exhausted=True)
    )
    assert basis["state"] == "mixed_bound" and basis["bound"] == "mixed"
    assert basis["lowerBoundReasons"] == ["cut_ladder_exhausted"]
    assert basis["upperBoundReasons"] == ["pre_trade_cleanup_exhausted"]


def test_no_waiver_table_makes_an_unpriced_release_undeterminable_not_free(flag_on):
    """Finding 3: with no waiver-level values ``displacement._waiver_value_for``
    gives an unpriced player base 0.  Under the flag that charge is refused
    (``None`` + reason), never 0.  The flag-OFF path is untouched (the
    pre-existing behaviour is a named follow-up in the record)."""
    c = _all_unpriced_bench_contract()
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = dataclasses.replace(
        RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS), waiver_values={}
    )
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Their QB"], outgoing_players=[])
    (drop,) = cap.forced_drops
    assert drop.value_basis == "assumedWaiver" and drop.release_cost == 0.0
    cost, basis = RC.forced_drop_cost(cap)
    assert cost is None
    assert basis["state"] == "unknown" and basis["reason"] == "waiver_values_unavailable"
    d = cap.to_dict()
    assert d["forcedDropCharge"] is None and d["forcedDropMarginal"] is None
    # A pre-trade cleanup resting on such a release is undeterminable too.
    pre_only = dataclasses.replace(
        cap,
        forced_drops=[dataclasses.replace(drop, value_basis="board")],
        over_limit_before=1,
        pre_trade_cleanup_cost=0.0,
        pre_trade_cleanup_drops=(("x", "assumedWaiver"),),
    )
    assert RC.forced_drop_cost(pre_only)[0] is None
    assert RC.forced_drop_marginal(pre_only) is None
    # With a waiver table, the same roster is charged (never 0).
    priced_ctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    cap2 = RC.assess_roster_capacity(priced_ctx, incoming_players=["Their QB"])
    assert RC.forced_drop_cost(cap2)[0] == 1400.0


def test_no_waiver_table_flag_off_is_unchanged(flag_off):
    c = _all_unpriced_bench_contract()
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = dataclasses.replace(
        RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS), waiver_values={}
    )
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Their QB"], outgoing_players=[])
    assert cap.selection_rule is None and cap.waiver_values_available is True
    assert "forcedDropCharge" not in cap.to_dict()


def test_relief_is_unpublished_with_the_flag_off(flag_off):
    _c, _us, ctx = _ctx(extra_us=(("WR Extra", 500.0, "WR"),))
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR"],
                                    outgoing_players=["WR Two", "WR Three"])  # fmt: skip
    assert "forcedDropMarginal" not in cap.to_dict()


def test_unknown_cap_is_unknown_not_free(flag_on):
    _c, _us, ctx = _ctx(settings={k: v for k, v in R.SETTINGS.items() if k != "rosterSize"})
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"])
    d = cap.to_dict()
    assert d["rosterLimit"] is None and d["forcedDropCharge"] is None
    assert d["forcedDropChargeBasis"]["state"] == "unknown"


def test_taxi_unknown_bracket_charges_only_guaranteed_drops(flag_on):
    _c, _us, ctx = _ctx(settings={**R.SETTINGS, "taxiSize": 2})
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=["Filler RB", "Filler WR", "Filler LB"], outgoing_players=[]
    )
    assert cap.certainty == "partial"
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == 300.0  # the one guaranteed release, the cheapest
    assert "taxi_occupancy_unknown_guaranteed_drops_only" in basis["lowerBoundReasons"]
    cap2 = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                     outgoing_players=["WR Two"])  # fmt: skip
    assert cap2.requires_drops is None
    assert RC.forced_drop_cost(cap2)[0] is None


def test_outgoing_player_not_on_roster_frees_no_spot(flag_on):
    _c, _us, ctx = _ctx()
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler WR"],
                                    outgoing_players=["Their QB"])  # fmt: skip
    assert cap.outgoing_not_on_roster == 1
    assert cap.over_limit_after == 2 and len(cap.forced_drops) == 2


def test_picks_occupy_no_spot(flag_on):
    c = R.contract()
    sim = _pkg(c, ["Filler RB", "Filler LB"], [], picks_out=[R.PICK[0]])
    rc = sim["rosterCapacity"]
    assert rc["sizeAfter"] == rc["sizeBefore"] + 2 and rc["overLimitAfter"] == 2


def test_scarcity_multiplier_enters_selection_and_charge(flag_on):
    """WR Zed (300, WR x1.15 = 345) vs RB Young (350, RB x0.85 = 297.5):
    with scarcity the RB is the cheaper RELEASE and is the one cut."""
    _c, _us, ctx = _ctx()
    sc = {
        "WR": ScarcityComponents("WR", None, None, 1.0, None, None, None),
        "RB": ScarcityComponents("RB", None, None, 0.0, None, None, None),
    }
    ctx = RC.CapacityContext(**{**ctx.__dict__, "scarcity": sc})
    cap = RC.assess_roster_capacity(ctx, incoming_players=["Star WR", "Filler RB"],
                                    outgoing_players=["WR Two"])  # fmt: skip
    (drop,) = cap.forced_drops
    assert drop.name == "RB Young" and drop.scarcity_multiplier == pytest.approx(0.85)
    assert drop.release_cost == pytest.approx(350.0 * 0.85)


# ── 6. Determinism: names and order decide nothing ─────────────────────


def _renamed_contract(mapping):
    c = R.contract()
    for row in c["playersArray"]:
        if row.get("displayName") in mapping:
            new = mapping[row["displayName"]]
            row["displayName"] = row["canonicalName"] = row["legacyRef"] = new
    for t in c["sleeper"]["teams"]:
        t["players"] = [mapping.get(n, n) for n in t["players"]]
    return c


def test_renaming_and_reordering_players_changes_nothing(flag_on):
    base_c = R.contract()
    us = terminal.resolve_team(base_c, owner_id="o1", name=None)
    ctx = RC.build_capacity_context(base_c, None, us, roster_settings=R.SETTINGS)
    pin, pout = ["Filler RB", "Filler WR", "Filler LB"], []
    base = RC.assess_roster_capacity(ctx, incoming_players=pin, outgoing_players=pout)

    # Reverse every name's sort order (ids unchanged).
    mapping = {n: f"Z{999 - i:03d} {n}" for i, (n, _v, _p) in enumerate(R.US)}
    c2 = _renamed_contract(mapping)
    rng = random.Random(7)
    us2 = terminal.resolve_team(c2, owner_id="o1", name=None)
    us2 = {**us2, "players": list(us2["players"])}
    order = list(range(len(us2["players"])))
    rng.shuffle(order)
    us2["players"] = [us2["players"][i] for i in order]
    us2["playerIds"] = [us2["playerIds"][i] for i in order]
    ctx2 = RC.build_capacity_context(c2, None, us2, roster_settings=R.SETTINGS)
    other = RC.assess_roster_capacity(ctx2, incoming_players=pin, outgoing_players=pout)
    assert sorted(d.player_id for d in base.forced_drops) == sorted(
        d.player_id for d in other.forced_drops
    )
    assert base.forced_drop_release_cost == other.forced_drop_release_cost


# ── 7. Properties against brute force (small random rosters) ───────────

_POS = ("QB", "RB", "WR", "TE")
_SMALL = {
    "teamCount": 2,
    "rosterSize": 9,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 2, "FLEX": 1},
}
_WIDE_POS = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")
#: SUPER_FLEX and IDP slots; 11-man roster, 4-piece trades, so up to d = 4.
_WIDE = {
    "teamCount": 2,
    "rosterSize": 11,
    "taxiSize": 0,
    "starters": {
        "QB": 1, "RB": 1, "WR": 1, "TE": 1, "SUPER_FLEX": 1,
        "DL": 1, "LB": 1, "DB": 1, "IDP_FLEX": 1,
    },
}  # fmt: skip
MODES = (fds.MODE_PACKAGE_CONSISTENT, fds.MODE_ROSTER_RATIONAL)


def _random_league(seed):
    rng = random.Random(seed)
    rows, us, them = [], [], []
    for i in range(9):
        pos = _POS[i % 4] if i < 6 else rng.choice(_POS)
        v = None if rng.random() < 0.15 else float(rng.choice(range(100, 4000, 50)))
        rows.append(R._row(f"U{i}", v, pos))
        us.append(f"U{i}")
    for i in range(4):
        pos = rng.choice(_POS)
        v = None if rng.random() < 0.15 else float(rng.choice(range(100, 4000, 50)))
        rows.append(R._row(f"T{i}", v, pos))
        them.append(f"T{i}")
    for p in _POS:
        rows.append(R._row(f"FA {p}", float(rng.choice(range(300, 1500, 50))), p))
    teams = [
        {"ownerId": "o1", "name": "Us", "players": us, "playerIds": [R._pid(n) for n in us]},
        {"ownerId": "o2", "name": "Them", "players": them, "playerIds": [R._pid(n) for n in them]},
    ]
    c = {"playersArray": rows, "sleeper": {"teams": teams}}
    k = rng.randint(1, 3)
    pin = rng.sample(them, k)
    pout = rng.sample(us, rng.randint(0, 1))
    return c, teams[0], pin, pout


def _random_wide_league(seed):
    """SUPER_FLEX + IDP slots, 11-man roster, a 1-4 piece incoming side."""
    rng = random.Random(10_000 + seed)
    rows, us, them = [], [], []
    for i in range(11):
        pos = _WIDE_POS[i] if i < len(_WIDE_POS) else rng.choice(_WIDE_POS)
        v = None if rng.random() < 0.15 else float(rng.choice(range(100, 4000, 50)))
        rows.append(R._row(f"U{i}", v, pos))
        us.append(f"U{i}")
    for i in range(5):
        pos = rng.choice(_WIDE_POS)
        v = None if rng.random() < 0.15 else float(rng.choice(range(100, 4000, 50)))
        rows.append(R._row(f"T{i}", v, pos))
        them.append(f"T{i}")
    for p in _WIDE_POS:
        rows.append(R._row(f"FA {p}", float(rng.choice(range(300, 1500, 50))), p))
    teams = [
        {"ownerId": "o1", "name": "Us", "players": us, "playerIds": [R._pid(n) for n in us]},
        {"ownerId": "o2", "name": "Them", "players": them, "playerIds": [R._pid(n) for n in them]},
    ]
    c = {"playersArray": rows, "sleeper": {"teams": teams}}
    pin = rng.sample(them, rng.randint(1, 4))
    pout = rng.sample(us, rng.randint(0, 1))
    return c, teams[0], pin, pout


def _scarce(ctx, seed, positions):
    """Real (non-inert) scarcity: a multiplier in 0.85-1.15 per position."""
    rng = random.Random(77 + seed)
    sc = {p: ScarcityComponents(p, None, None, rng.random(), None, None, None) for p in positions}
    ctx = RC.CapacityContext(**{**ctx.__dict__, "scarcity": sc})
    mults = {p: DP.scarcity_multiplier(v) for p, v in sc.items()}
    assert all(0.85 <= m <= 1.15 for m in mults.values())
    return ctx


def _league(kind, seed):
    if kind == "wide_scarce":
        c, us, pin, pout = _random_wide_league(seed)
        ctx = RC.build_capacity_context(c, None, us, roster_settings=_WIDE)
        return c, ctx, pin, pout, _scarce(ctx, seed, _WIDE_POS)
    c, us, pin, pout = _random_league(seed)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=_SMALL)
    return c, ctx, pin, pout, (_scarce(ctx, seed, _POS) if kind == "scarce" else ctx)


def _post_pool(ctx, pin, pout):
    existing = []
    pending = {RC._norm(n) for n in pout}
    for n in ctx.roster_player_names:
        if RC._norm(n) in pending:
            pending.discard(RC._norm(n))
            continue
        existing.append(ctx.assets_by_key.get(RC._norm(n)) or RC._resolve_incoming(n, ctx.by_name))
    incoming = [RC._resolve_incoming(n, ctx.by_name) for n in pin]
    return existing, incoming


def _filled(ctx, assets):
    return DP._filled_slot_count(
        [
            DP.RosterAsset(**{**a.__dict__, "player_id": f"{i}", "ros_value": 0.0})
            for i, a in enumerate(assets)
        ],
        list(ctx.starter_slots),
        ctx.slot_eligibility,
    )


class _Brute:
    """Every lineup-legal cut set of the required size, costed both ways."""

    def __init__(self, ctx, cap, pin, pout, package=None):
        self.existing, self.incoming = _post_pool(ctx, pin, pout)
        self.pool = [*self.existing, *self.incoming]
        self.n_e = len(self.existing)
        self.c = [fds.release_charge(a, ctx.waiver_values, ctx.scarcity)[0] for a in self.pool]
        self.labels = [RC._norm(n) for n in pin]
        self.package = package
        base = _filled(ctx, self.pool)
        d = cap.over_limit_after_max
        self.legal = [
            S
            for S in itertools.combinations(range(len(self.pool)), d)
            if _filled(ctx, [a for i, a in enumerate(self.pool) if i not in S]) >= base
        ]
        # k-th incoming with a label <-> k-th package entry with that label.
        self.uncredited = set()
        if package is not None:
            entries: dict[str, list[bool]] = {}
            for k, v in package.receiving:
                if k is not None:
                    entries.setdefault(k, []).append(v is not None)
            seen: dict[str, int] = {}
            for j, lab in enumerate(self.labels):
                flags = entries.get(lab, [])
                if seen.get(lab, 0) < len(flags) and not flags[seen.get(lab, 0)]:
                    self.uncredited.add(self.n_e + j)
                seen[lab] = seen.get(lab, 0) + 1

    def own(self, S) -> float:
        return sum(self.c[i] for i in S)

    def charge(self, S) -> float:
        """Rule 2: existing at ``c``; acquired at the package credit forgone
        (+ its own ``c`` when the package never credited it)."""
        if self.package is None:
            return self.own(S)
        cost = 0.0
        removed: dict[str, int] = {}
        for i in S:
            if i < self.n_e or i in self.uncredited:
                cost += self.c[i]
            if i >= self.n_e:
                lab = self.labels[i - self.n_e]
                removed[lab] = removed.get(lab, 0) + 1
        if removed:
            cost += self.package.gap() - self.package.gap(removed)
        return cost

    def selected(self, cap) -> tuple[int, ...]:
        """The pool indices of the capacity owner's drops (names are unique)."""
        names = [a.name for a in self.pool]
        taken: list[int] = []
        for d in cap.forced_drops:
            i = next(j for j, n in enumerate(names) if n == d.name and j not in taken)
            taken.append(i)
        return tuple(sorted(taken))


def _package_for(c, pin, pout):
    vals = {r["displayName"]: r.get("rankDerivedValue") for r in c["playersArray"]}
    return fds.PackageSides(
        sending=tuple(vals[n] for n in pout if vals.get(n)),
        receiving=tuple((RC._norm(n), vals.get(n)) for n in pin),
    )


def _assess(ctx, pin, pout, package, mode, monkeypatch):
    monkeypatch.setattr(fds, "SELECTION_MODE", mode)
    return RC.assess_roster_capacity(
        ctx, incoming_players=pin, outgoing_players=pout, package=package
    )


_KINDS = (
    [("plain", s) for s in range(40)]
    + [("scarce", s) for s in range(30)]
    + [("wide_scarce", s) for s in range(30)]
)


@pytest.mark.parametrize("with_package", [False, True])
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("kind,seed", _KINDS)
def test_selection_and_charge_against_brute_force(flag_on, monkeypatch, kind, seed, mode,
                                                  with_package):  # fmt: skip
    """Exactness of both modes over every lineup-legal cut set, with inert and
    REAL scarcity (0.85-1.15, mixed incoming/existing candidates — review fix
    B) and in SUPER_FLEX + IDP leagues up to d = 4 (review fix F):

    * V5 (package_consistent): the charge is the minimum of rule 2 over every
      legal set;
    * V5-R (roster_rational): the cut SET has the minimum ``sum c`` over every
      legal set, and the charge is rule 2 applied to that set;
    * without a package both modes are the plain cheapest-``c`` cleanup.
    """
    c, _ctx0, pin, pout, ctx = _league(kind, seed)
    package = _package_for(c, pin, pout) if with_package else None
    cap = _assess(ctx, pin, pout, package, mode, monkeypatch)
    if not cap.over_limit_after or cap.ladder_exhausted:
        pytest.skip("trade fits or no legal cleanup")
    bf = _Brute(ctx, cap, pin, pout, package)
    assert bf.legal
    chosen = bf.selected(cap)
    assert chosen in bf.legal
    min_own = min(bf.own(S) for S in bf.legal)
    if package is None or mode == fds.MODE_ROSTER_RATIONAL:
        assert bf.own(chosen) == pytest.approx(min_own)
    if package is None:
        assert cap.forced_drop_release_cost == pytest.approx(min_own)
    elif mode == fds.MODE_PACKAGE_CONSISTENT:
        assert cap.forced_drop_release_cost == pytest.approx(min(bf.charge(S) for S in bf.legal))
    else:
        assert cap.forced_drop_release_cost == pytest.approx(bf.charge(chosen))
    if package is not None and cap.package_applied:
        for d in cap.forced_drops:
            if d.acquired_in_trade:
                assert d.charge_basis in (fds.CHARGE_PACKAGE, fds.CHARGE_UNCREDITED)
            else:
                assert d.charge_basis == fds.CHARGE_RELEASE
    # An uncredited (unpriced) incoming release is never charged 0.
    for d in cap.forced_drops:
        if d.charge_basis == fds.CHARGE_UNCREDITED:
            assert d.release_cost > 0


@pytest.mark.parametrize("kind,seed", _KINDS)
def test_v5_charge_never_exceeds_v5r_and_v5r_cut_is_never_dearer(flag_on, monkeypatch, kind,
                                                                 seed):  # fmt: skip
    """The trade-off the owner decides (record §3a), as an identity: V5
    minimises the CHARGE, so its charge <= V5-R's; V5-R minimises the cut's own
    value, so its ``sum c`` <= V5's."""
    c, _ctx0, pin, pout, ctx = _league(kind, seed)
    package = _package_for(c, pin, pout)
    v5 = _assess(ctx, pin, pout, package, fds.MODE_PACKAGE_CONSISTENT, monkeypatch)
    v5r = _assess(ctx, pin, pout, package, fds.MODE_ROSTER_RATIONAL, monkeypatch)
    if not v5.over_limit_after or v5.ladder_exhausted or v5r.ladder_exhausted:
        pytest.skip("trade fits or no legal cleanup")
    assert v5.forced_drop_release_cost <= v5r.forced_drop_release_cost + 1e-6
    bf = _Brute(ctx, v5, pin, pout, package)
    assert bf.own(bf.selected(v5r)) <= bf.own(bf.selected(v5)) + 1e-6
    assert v5.selection_rule == fds.RULE_ID
    assert v5r.selection_rule == fds.RULE_ID_ROSTER_RATIONAL


def test_v5_releases_a_dearer_incoming_piece_v5r_the_cheaper_roster_player():
    """The unit mismatch the review found, pinned: receive [5000, 1000, 1000]
    with an existing 700 the cheapest roster player.  V5 releases a 1,000
    incoming piece (its package credit under the geometric model is ~608 <
    700); V5-R releases the 700 existing player, charged 700."""
    existing = [_asset("e700", 700.0), _asset("e3000", 3000.0)]
    incoming = [_asset("a5000", 5000.0), _asset("b1000", 1000.0), _asset("c1000", 1000.0)]
    package = fds.PackageSides(
        sending=(6500.0,),
        receiving=(("a5000", 5000.0), ("b1000", 1000.0), ("c1000", 1000.0)),
    )
    kw = dict(drops_needed=1, starter_slots=[], waiver_values={"WR": 300.0}, scarcity=None,
              slot_eligibility=None, package=package)  # fmt: skip
    labels = ["a5000", "b1000", "c1000"]
    v5 = fds.select_forced_drops(existing, incoming, labels, mode=fds.MODE_PACKAGE_CONSISTENT, **kw)
    v5r = fds.select_forced_drops(existing, incoming, labels, mode=fds.MODE_ROSTER_RATIONAL, **kw)
    (d5,) = v5.drops
    assert d5.acquired and d5.asset.board_value == 1000.0
    assert d5.charge_basis == fds.CHARGE_PACKAGE
    credit = package.gap() - package.gap({d5.asset.player_id: 1})
    assert d5.charge == pytest.approx(credit) and credit < 700.0
    (dr,) = v5r.drops
    assert dr.asset.player_id == "e700" and dr.charge == 700.0
    assert dr.charge_basis == fds.CHARGE_RELEASE


def _taxi_unknown_case(seed, mode, monkeypatch):
    c, us, pin, pout = _random_wide_league(seed)
    ctx = RC.build_capacity_context(c, None, us, roster_settings={**_WIDE, "taxiSize": 2})
    package = _package_for(c, pin, pout)
    cap = _assess(ctx, pin, pout, package, mode, monkeypatch)
    return ctx, cap, pin, pout, package


@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("seed", range(120))
def test_taxi_unknown_lower_bound_is_the_cheapest_legal_cleanup_of_the_guaranteed_count(
    flag_on, monkeypatch, seed, mode
):  # fmt: skip
    """Review F3.  With taxi membership invisible the charge is a LOWER BOUND on
    the releases guaranteed under every assignment.  The cheapest ``k`` drops of
    the worst-case cleanup are a legal ``k``-set but not necessarily the
    cheapest one, so the bound is now RE-SELECTED at ``k``: it equals the
    brute-force minimum charge over every lineup-legal ``k``-set, and is never
    above the cheapest ``k`` of the worst-case drops (23 of 462 random cases
    were strictly below)."""
    ctx, cap, pin, pout, package = _taxi_unknown_case(seed, mode, monkeypatch)
    if cap.certainty != "partial" or cap.taxi_bound_cleanup is None or cap.ladder_exhausted:
        pytest.skip("no taxi bracket to bound")
    added = min(cap.over_limit_after_min, max(0, cap.size_after - cap.size_before))
    bf = _Brute(ctx, cap, pin, pout, package)
    base = _filled(ctx, bf.pool)
    legal_k = [
        S
        for S in itertools.combinations(range(len(bf.pool)), added)
        if _filled(ctx, [a for i, a in enumerate(bf.pool) if i not in S]) >= base
    ]
    cost, basis = RC.forced_drop_cost(cap)
    assert cost == pytest.approx(min(bf.charge(S) for S in legal_k), abs=0.06)
    old = sum(sorted(d.release_cost for d in cap.forced_drops)[:added])
    assert cost <= old + 1e-6
    assert basis["state"] in ("lower_bound", "mixed_bound")
    assert "taxi_occupancy_unknown_guaranteed_drops_only" in basis["lowerBoundReasons"]


def test_taxi_unknown_lower_bound_can_be_strictly_below_the_cheapest_k_of_the_worst_case(
    flag_on, monkeypatch
):  # fmt: skip
    """Pinned instance (review F3, the "9/364" class): the guaranteed count is 1
    of 3 possible releases.  The cheapest single drop of the 3-release cleanup is
    335, but a different legal single release costs 261."""
    ctx, cap, _pin, _pout, _pk = _taxi_unknown_case(40, fds.MODE_PACKAGE_CONSISTENT, monkeypatch)
    assert (cap.over_limit_after_min, cap.over_limit_after_max) == (1, 3)
    cost, _basis = RC.forced_drop_cost(cap)
    assert cost == 261.0
    assert min(d.release_cost for d in cap.forced_drops) == 335.0


def _seven_incoming(d):
    existing = [_asset(f"e{i}", 1500.0 + 400.0 * i) for i in range(6)]
    incoming = [_asset(f"in{i}", 700.0 + 350.0 * i) for i in range(7)]
    labels = [a.player_id for a in incoming]
    package = fds.PackageSides(
        sending=(6000.0,), receiving=tuple((a.player_id, a.board_value) for a in incoming)
    )
    kw = dict(drops_needed=d, starter_slots=[], waiver_values={"WR": 300.0}, scarcity=None,
              slot_eligibility=None, package=package)  # fmt: skip
    return existing, incoming, labels, kw


def test_search_bound_exceeded_is_explicit_and_uses_package_charging_review_f2():
    """Review F2.  Above 64 acquired subsets V5 used to drop the package step
    SILENTLY (raw charging, a different currency).  Now it says so
    (``searchBoundExceeded``) and uses the V5-R selection WITH package charging
    (exact, polynomial).  7 incoming, d = 4 -> 99 subsets > 64."""
    existing, incoming, labels, kw = _seven_incoming(4)
    v5 = fds.select_forced_drops(existing, incoming, labels, mode=fds.MODE_PACKAGE_CONSISTENT, **kw)
    v5r = fds.select_forced_drops(existing, incoming, labels, mode=fds.MODE_ROSTER_RATIONAL, **kw)
    assert v5.search_bound_exceeded is True and v5.search_bound == fds.MAX_PACKAGE_SUBSETS == 64
    assert v5r.search_bound_exceeded is False
    # The V5-R selection WITH package charging, not the raw-charge fallback.
    assert v5.package_applied is True and v5.mode == fds.MODE_ROSTER_RATIONAL
    assert [(d.asset.player_id, d.charge, d.charge_basis) for d in v5.drops] == [
        (d.asset.player_id, d.charge, d.charge_basis) for d in v5r.drops
    ]
    acquired = [d for d in v5.drops if d.acquired]
    assert acquired and all(d.charge_basis == fds.CHARGE_PACKAGE for d in acquired)
    assert not any(d.charge_basis == fds.CHARGE_NO_PACKAGE for d in v5.drops)
    assert any("search bound" in n for n in v5.notes)
    # The raw charge of the same cut set would be strictly higher (credit < c).
    raw = sum(fds.release_charge(d.asset, {"WR": 300.0}, None)[0] for d in v5.drops)
    assert v5.total < raw


def test_at_or_below_the_search_bound_nothing_changes():
    """63 subsets would be fine too; 6 incoming, d = 2 -> 22 subsets: the V5
    subset search runs, publishes ``searchBoundExceeded`` False, and keeps its
    own mode (no behaviour change at or below the bound)."""
    existing, incoming, labels, kw = _seven_incoming(2)
    incoming, labels = incoming[:6], labels[:6]
    kw["package"] = fds.PackageSides(
        sending=(6000.0,), receiving=tuple((a.player_id, a.board_value) for a in incoming)
    )
    v5 = fds.select_forced_drops(existing, incoming, labels, mode=fds.MODE_PACKAGE_CONSISTENT, **kw)
    assert v5.search_bound_exceeded is False and v5.mode == fds.MODE_PACKAGE_CONSISTENT
    assert not any("search bound" in n for n in v5.notes)
    # d = 4 with 6 incoming is 57 subsets: still within the bound.
    existing, incoming, labels, kw4 = _seven_incoming(4)
    incoming, labels = incoming[:6], labels[:6]
    kw4["package"] = kw["package"]
    v5_4 = fds.select_forced_drops(
        existing, incoming, labels, mode=fds.MODE_PACKAGE_CONSISTENT, **kw4
    )
    assert v5_4.search_bound_exceeded is False and v5_4.mode == fds.MODE_PACKAGE_CONSISTENT


def test_search_bound_is_published_in_the_capacity_block(flag_on):
    existing, incoming, labels, kw = _seven_incoming(4)
    rows = [
        R._row(a.player_id, a.board_value, "WR") for a in [*existing, *incoming]
    ]  # fmt: skip
    rows += [R._row("FA WR", 300.0, "WR")]
    us_names = [a.player_id for a in existing]
    them_names = [a.player_id for a in incoming]
    teams = [
        {"ownerId": "o1", "name": "Us", "players": us_names,
         "playerIds": [R._pid(n) for n in us_names]},
        {"ownerId": "o2", "name": "Them", "players": them_names,
         "playerIds": [R._pid(n) for n in them_names]},
    ]  # fmt: skip
    c = {"playersArray": rows, "sleeper": {"teams": teams}}
    settings = {"teamCount": 2, "rosterSize": 6, "taxiSize": 0, "starters": {"WR": 1}}
    ctx = RC.build_capacity_context(c, None, teams[0], roster_settings=settings)
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=them_names, outgoing_players=[], package=kw["package"]
    )
    out = cap.to_dict()["forcedDropSelection"]
    assert out["searchBound"] == 64 and out["searchBoundExceeded"] is True
    assert out["rule"] == fds.RULE_ID_ROSTER_RATIONAL and out["packageApplied"] is True
    assert cap.over_limit_after == 7


def test_unknown_selection_mode_is_refused():
    with pytest.raises(ValueError):
        fds.select_forced_drops(
            [_asset("e", 1.0)], (), (), drops_needed=1, starter_slots=[], waiver_values={},
            scarcity=None, slot_eligibility=None, mode="nope",
        )  # fmt: skip


def test_default_mode_is_package_consistent():
    assert fds.SELECTION_MODE == fds.MODE_PACKAGE_CONSISTENT
    assert fds.rule_id() == fds.RULE_ID


@pytest.mark.parametrize("seed", range(40))
def test_adding_an_incoming_piece_never_lowers_the_receivers_net(flag_on, seed):
    """Monotonicity of the package-consistent (V5) net: receiving one more
    player can always be undone by releasing him, so it never makes the trade
    worse (geometric package model; roster fills every slot without him)."""
    c, us, pin, pout = _random_league(seed)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=_SMALL)

    def net(players_in):
        package = _package_for(c, players_in, pout)
        cap = RC.assess_roster_capacity(
            ctx, incoming_players=players_in, outgoing_players=pout, package=package
        )
        if cap.ladder_exhausted:
            return None
        cost, _b = RC.forced_drop_cost(cap)
        return package.gap() - (cost or 0.0)

    existing, incoming = _post_pool(ctx, pin, pout)
    if _filled(ctx, [*existing, *incoming]) < len(ctx.starter_slots):
        # The property's precondition.  When the extra piece fills a slot the
        # roster could not, the lineup guard PROTECTS him (releasing him would
        # empty that slot again), so "release him" is not an available undo —
        # a documented limit of the guard, not of the charge.
        pytest.skip("roster cannot fill every slot without the extra piece")
    priced = {r["displayName"] for r in c["playersArray"] if r.get("rankDerivedValue")}
    # Precondition 2 (review fix D): the extra piece is CREDITED by the package.
    # An unpriced piece takes a spot with no package credit and its release is
    # charged at the ``assumedWaiver`` ceiling (never free — an identity miss is
    # not a free cut), so receiving him can lower the net by up to the cheapest
    # legal cut.  That is the intended price of not treating unknown as zero.
    for extra in [n for n in c["sleeper"]["teams"][1]["players"] if n not in pin]:
        if extra not in priced:
            continue
        before, after = net(pin), net([*pin, extra])
        if before is None or after is None:
            continue
        assert after >= before - 1e-6


def _net(existing, incoming, labels, package, mode, d):
    """``package gap - charge`` of the selected cleanup (the War Room net when
    the roster owed nothing before the trade)."""
    sel = fds.select_forced_drops(
        existing, incoming, labels, drops_needed=d, starter_slots=[],
        waiver_values={"WR": 300.0}, scarcity=None, slot_eligibility=None,
        package=package, mode=mode,
    )  # fmt: skip
    return package.gap() - sel.total, sel


def test_v5r_net_is_not_monotone_in_a_free_credited_extra_piece_v5_is():
    """Record §3 / §9 (review F1).  Net-monotonicity ("receiving one more
    CREDITED piece never lowers the receiver's net") holds for V5 ONLY.

    Minimal reproducer: a roster at the cap whose cheapest player is a bench
    900.  Trade 1 sends a 3,000 and receives a 3,000 (no release owed, net 0).
    Trade 2 is the same plus a free 1,000.  V5 may release the 1,000 it just
    received, charged the package credit it forgoes (780), so its net stays 0.
    V5-R selects by ``c`` across both pools, so it cuts the 900 bench player
    instead (900 > 780): net -120 — the free extra piece LOWERED the net.

    This is the known price of V5-R's roster-rational cut (it never prefers a
    cheaper-looking package credit to a cheaper real player), NOT a regression:
    if this test starts failing, V5-R's selection changed and the owner
    decision in record §3a must be re-read.  V5's net dominates V5-R's.
    """
    existing = [_asset("bench900", 900.0), _asset("star5000", 5000.0)]
    r3000 = _asset("r3000", 3000.0)
    free1000 = _asset("free1000", 1000.0)

    # Trade 1: 1-for-1, the roster stays at the cap, nothing is released.
    p1 = fds.PackageSides(sending=(3000.0,), receiving=(("r3000", 3000.0),))
    net_1 = p1.gap()
    assert net_1 == 0.0

    # Trade 2: the same plus a free credited 1,000 — one release is owed.
    p2 = fds.PackageSides(sending=(3000.0,), receiving=(("r3000", 3000.0), ("free1000", 1000.0)))
    labels = ["r3000", "free1000"]
    net_v5, sel_v5 = _net(existing, [r3000, free1000], labels, p2,
                          fds.MODE_PACKAGE_CONSISTENT, 1)  # fmt: skip
    net_v5r, sel_v5r = _net(existing, [r3000, free1000], labels, p2,
                            fds.MODE_ROSTER_RATIONAL, 1)  # fmt: skip

    (d5,) = sel_v5.drops
    assert d5.asset.player_id == "free1000" and d5.charge_basis == fds.CHARGE_PACKAGE
    assert net_v5 == pytest.approx(0.0, abs=1e-6)
    assert net_v5 >= net_1 - 1e-6  # V5: monotone

    (dr,) = sel_v5r.drops
    assert dr.asset.player_id == "bench900" and dr.charge == 900.0
    assert net_v5r == pytest.approx(-120.0, abs=1e-6)
    assert net_v5r < net_1 - 100.0  # V5-R: the free extra piece lowered the net
    assert net_v5 >= net_v5r  # V5 dominates V5-R on the same instance


# ── 8. One number across surfaces ──────────────────────────────────────


@pytest.mark.parametrize("trade", sorted(R.TRADES))
def test_war_room_and_finder_read_the_same_charge(flag_on, trade):
    c = R.contract()
    pin, pout, _kin, kout = R.TRADES[trade]
    sim = _pkg(c, pin, pout, picks_out=kout)
    rc = sim["rosterCapacity"]
    a = _objective(sim)
    charge = rc["forcedDropCharge"]
    assert (a.get("forcedReleaseCost") or 0) == round(charge or 0)
    # The Finder ranks on forced_drop_cost of the same capacity owner.
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    cap = RC.assess_roster_capacity(
        ctx,
        incoming_players=pin,
        outgoing_players=pout,
        package=trade_simulator._capacity_package(
            sim["receiving"], sim["sending"], sim["unresolvedIn"]
        ),
    )
    cost, _basis = RC.forced_drop_cost(cap)
    assert (cost if cost is None else round(cost, 1)) == charge


def test_finder_charges_through_the_flagged_owner(flag_on):
    from src.trade.finder import find_trades

    c = R.contract()
    us = terminal.resolve_team(c, owner_id="o1", name=None)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=R.SETTINGS)
    res = find_trades(
        players=R._finder_players(c),
        my_team="Us",
        opponent_teams=["Them"],
        sleeper_teams=c["sleeper"]["teams"],
        contract=c,
        capacity_context=ctx,
        use_team_context=True,
    )
    bases = [
        (t.get("rankingFactors") or {}).get("forcedDropCostBasis") or {} for t in res["trades"]
    ]
    stated = [b for b in bases if b.get("state")]
    assert stated and all(b.get("rule") == fds.RULE_ID for b in stated)


# ── 9. Perfect Draft is untouched ──────────────────────────────────────


def test_build_cut_ladder_default_order_is_unchanged_by_the_new_seams():
    assets = [
        DP.RosterAsset(player_id=f"p{i}", name=n, position="WR", board_value=v)
        for i, (n, v) in enumerate([("Zed", 100.0), ("Abe", 900.0), ("Mid", 500.0)])
    ]
    plain = DP.build_cut_ladder(assets, [], {"WR": 1000.0})
    seams = DP.build_cut_ladder(assets, [], {"WR": 1000.0}, order_key=None, candidate_ids=None)
    assert [r.name for r in plain.rungs] == [r.name for r in seams.rungs] == ["Abe", "Mid", "Zed"]
    keyed = DP.build_cut_ladder(assets, [], {"WR": 1000.0}, order_key=lambda a: a.board_value)
    assert [r.name for r in keyed.rungs] == ["Zed", "Mid", "Abe"]
    limited = DP.build_cut_ladder(assets, [], {"WR": 1000.0}, candidate_ids={"p2"})
    assert [r.name for r in limited.rungs] == ["Mid"]


def test_perfect_draft_roster_context_is_identical_flag_on(monkeypatch):
    c = R.contract()
    out = {}
    for on in ("0", "1"):
        monkeypatch.setenv(ENV, on)
        feature_flags.reload()
        out[on] = build_roster_context(c, None, owner_id="o1")
    monkeypatch.delenv(ENV, raising=False)
    feature_flags.reload()
    assert out["0"] == out["1"]
