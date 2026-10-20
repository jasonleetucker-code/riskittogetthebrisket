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
    _assert_is_legal_minimum(ctx, cap, ["Star WR", "Filler RB", "Filler WR"], ["DB One"])


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


def test_unpriced_incoming_released_forgoes_no_credit(flag_on):
    c = R.contract()
    sim = _pkg(c, ["Star WR", "Unpriced DB"], ["WR Three"])
    (drop,) = sim["rosterCapacity"]["forcedDrops"]
    assert drop["name"] == "Unpriced DB" and drop["acquiredInTrade"] is True
    # The market lens never credited him (unpricedIn), so releasing him costs
    # the package nothing; his value stays UNKNOWN (value None), not zero.
    assert drop["value"] is None and drop["releaseCost"] == 0.0
    assert sim["rosterCapacity"]["unpricedForcedDrops"] == 1


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


def _assert_is_legal_minimum(ctx, cap, pin, pout, package=None):
    """The charged cleanup equals the brute-force minimum over EVERY
    lineup-legal cut set of the required size."""
    existing, incoming = _post_pool(ctx, pin, pout)
    pool = [*existing, *incoming]
    base = _filled(ctx, pool)
    d = cap.over_limit_after_max
    labels = [RC._norm(n) for n in pin]
    best = None
    for S in itertools.combinations(range(len(pool)), d):
        rest = [a for i, a in enumerate(pool) if i not in S]
        if _filled(ctx, rest) < base:
            continue
        cost = 0.0
        acq = [i - len(existing) for i in S if i >= len(existing)]
        for i in S:
            if i < len(existing) or package is None:
                cost += fds.release_charge(pool[i], ctx.waiver_values, ctx.scarcity)[0]
        if package is not None and acq:
            removed: dict[str, int] = {}
            for j in acq:
                removed[labels[j]] = removed.get(labels[j], 0) + 1
            cost += package.gap() - package.gap(removed)
        best = cost if best is None else min(best, cost)
    assert best is not None
    assert cap.forced_drop_release_cost == pytest.approx(best)
    return best


@pytest.mark.parametrize("seed", range(40))
def test_charge_is_the_brute_force_legal_minimum_without_package(flag_on, seed):
    c, us, pin, pout = _random_league(seed)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=_SMALL)
    cap = RC.assess_roster_capacity(ctx, incoming_players=pin, outgoing_players=pout)
    if not cap.over_limit_after:
        pytest.skip("trade fits")
    if cap.ladder_exhausted:
        pytest.skip("no legal cleanup")
    _assert_is_legal_minimum(ctx, cap, pin, pout)


def _package_for(c, pin, pout):
    vals = {r["displayName"]: r.get("rankDerivedValue") for r in c["playersArray"]}
    return fds.PackageSides(
        sending=tuple(vals[n] for n in pout if vals.get(n)),
        receiving=tuple((RC._norm(n), vals.get(n)) for n in pin),
    )


@pytest.mark.parametrize("seed", range(40))
def test_charge_is_the_brute_force_legal_minimum_with_package(flag_on, seed):
    c, us, pin, pout = _random_league(seed)
    ctx = RC.build_capacity_context(c, None, us, roster_settings=_SMALL)
    package = _package_for(c, pin, pout)
    cap = RC.assess_roster_capacity(
        ctx, incoming_players=pin, outgoing_players=pout, package=package
    )
    if not cap.over_limit_after or cap.ladder_exhausted:
        pytest.skip("trade fits or no legal cleanup")
    _assert_is_legal_minimum(ctx, cap, pin, pout, package=package)
    # Package consistency: the charge never exceeds what releasing the
    # cheapest-credited legal subset of the incoming pieces would cost, so a
    # just-acquired piece is never both credited and charged.
    for d in cap.forced_drops:
        if d.acquired_in_trade:
            assert d.charge_basis == fds.CHARGE_PACKAGE


@pytest.mark.parametrize("seed", range(40))
def test_adding_an_incoming_piece_never_lowers_the_receivers_net(flag_on, seed):
    """Monotonicity of the package-consistent net: receiving one more player
    can always be undone by releasing him, so it never makes the trade worse
    (geometric package model; roster fills every slot without him)."""
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
    for extra in [n for n in c["sleeper"]["teams"][1]["players"] if n not in pin]:
        before, after = net(pin), net([*pin, extra])
        if before is None or after is None:
            continue
        assert after >= before - 1e-6


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
