"""Lane E: the N-team invariants I1-I20 (spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.10) as seeded properties and
adversarial ledgers.  TEST-ONLY: no production code, flag, config or
methodology is touched (``geom_q078_v1`` q = 0.78 and ``fairness_bands_v2`` are
read through their owners, never re-stated as constants).

Invariant -> where it is already pinned -> what this module adds
-----------------------------------------------------------------

``TAM`` = ``tests/trade/test_analyze_multi_team.py``, ``TTL`` =
``tests/trade/test_trade_ledger.py``, ``TTV`` =
``tests/trade/test_team_verdicts.py``, ``ROUTE`` =
``tests/api/test_trade_analyze_multi_route.py``, ``XSURF`` =
``tests/api/test_trade_analyze_multi_cross_surface.py``.

* I1 team order -- TAM ``test_i1_i2_i3_order_and_determinism_exhaustive_on_four_teams``
  (ONE fixed synthetic ledger), TAM ``test_property_sweep_on_the_real_board`` and
  ``test_real_board_four_team_exhaustive_team_order`` (real archive; skip
  without one), ROUTE ``test_route_is_team_order_and_asset_order_independent``.
  ADDED: every team permutation (exhaustive, N <= 4) over the seeded generator,
  in all three modes, in every board scenario (unverifiable / unpriced /
  quarantined / over-cap included); ``teams`` given as list / tuple / set.
* I2 leg order -- same owners as I1.  ADDED: a fresh leg shuffle per team
  permutation; legs spelled as dicts / ``assetId`` dicts / tuples / lists /
  ``Leg`` objects; the canonical key (single-flight identity) is
  permutation-invariant and injective over the corpus; re-validating a
  validated ledger is a fixed point.
* I3 determinism -- same owners as I1.  ADDED: repeat runs; results do not
  depend on what the snapshot evaluated BEFORE (forward / backward / after a
  poison run / on a rebuilt snapshot); the contract and the rosters are never
  written.
* I4 2-team equivalence with ``/api/trade/analyze`` -- ROUTE
  ``test_i4_two_team_engine_equals_the_existing_analyze_route`` and XSURF
  ``test_route_equals_engine_byte_for_byte_at_two_three_and_four_teams``.
  Route-level and complete; NOT duplicated here.
* I5 perspective reversal at N = 2 -- TAM real-board sweep only (skips without
  an archive).  ADDED: synthetic N = 2 sweep, all modes (gap, display side,
  base, relative %, level).
* I6 conservation / fail-closed -- TAM ``test_conservation_violation_is_raised_never_published``,
  ROUTE ``test_invariant_violation_fails_closed_with_500``.  ADDED:
  reconciliation of every generated ledger in every mode, and the SIMULATED
  post-trade roster (``delta`` / ``after``) equals the ledger's net flow for
  every team (value and per-position head counts), with the pre-trade roster
  the snapshot's whatever ledger it is in.
* I7 no phantom / duplicate assets -- TAM ``_assert_ledger_reconciles`` in the
  real-board sweeps, TTL ledger case ``duplicate_transfer``.  ADDED: generator,
  named duplicate-leg abuses, alias spellings that must never smuggle a copy
  past the duplicate check, a league team the ledger does not list is never
  analysed or touched.
* I8 verified owner not overridable -- TTL
  ``test_verified_owner_cannot_be_overridden_by_request_fields`` + ledger
  cases.  ADDED: seeded owner reassignment (409 when current, unverifiable
  when stale / unknown, the actual owner never echoed) WITH ownership claims
  riding on the leg; claims never change a valid ledger on any board.
* I9 renaming -- TAM ``test_i9_renaming_teams_and_labels_changes_no_verdict``
  (one ledger, player labels).  ADDED: generator; pick labels renamed;
  names swapped, named like another asset's id / a pick row, shared team
  names, shuffled pick labels; players sharing a display name.  DEFECTS FOUND:
  ``LANE-E-DEFECT-I9-PICKLABEL``, ``LANE-E-DEFECT-I9-DUPNAME`` (strict xfails
  at the end of the module).
* I10 locality -- TAM ``test_i10_locality_a_leg_between_other_teams_leaves_a_team_unchanged``
  (one ledger).  ADDED: seeded extra legs between other participants, and
  between NEW teams (N grows; the only difference allowed is the SD-12
  ``comparables`` stamp at N >= 3 in the private modes).
* I11 public = reduction of private -- ``tests/trade/test_public_advisor_parity.py``,
  ``tests/api/test_public_trade_advisor_privacy.py`` and TAM
  ``test_fairness_is_gross_and_identical_in_every_mode``.  ADDED (engine half
  only): per-team fairness identical across the three modes on every
  generated ledger, invariant to roster capacity, and invariant to every Team
  Context input (four postures, none, five roster-lens outcomes) while the
  private decisions DO move.
* I12 Python/JS parity -- ``tests/trade/test_multi_team_parity_fixture.py`` +
  ``frontend/__tests__/multi-team-package-parity.test.js``.  NOT duplicated.
* I13 one value per asset -- TAM
  ``test_unknown_slot_future_pick_has_one_generic_value_and_is_not_a_gap``,
  ``test_two_way_player_carries_one_value_in_every_view`` and the real sweep.
  ADDED: one value per asset across ALL generated ledgers, N and modes, equal
  to the board; current-year exact-slot picks, unknown-slot future picks and
  picks held by someone other than their origin (value follows the origin);
  an unpriced pick row (R14d) is ``value: None`` + UNABLE, never 0;
  quarantined / stale picks withheld on both sides.  DEFECT FOUND:
  ``LANE-E-DEFECT-I13-PICKSTATE``.
* I14 directional correctness -- TAM ``test_i14_one_to_many_directional_numbers``
  and ``test_multi_team_parity_fixture::test_i14_numbers_match_the_spec``.
  ADDED: the spec's literal numbers re-derived from the owners, §1's
  one-sided example, and a generalized ORACLE: every evaluable team's gap,
  display side, base, relative % and level equal the owners' math over the
  board values of its own (G_i, R_i).
* I15 raw conservation -- TAM ``test_i15_one_for_one_cycle_gaps_sum_to_zero`` (one
  cycle).  ADDED: seeded 1-for-1 cycles (sum of gaps = 0 exactly) and
  sum_i(raw_recv - raw_send) = 0 over every generated ledger; the summary
  carries RAW conserved quantities only.
* I16 forced drops -- TAM ``test_i16_forced_drops_come_from_the_post_trade_roster_and_are_not_legs``
  (one ledger).  ADDED: seeded over-cap ledgers, and capacity never moves
  fairness.
* I17 ownership gate -- TAM ``test_i17_stale_rosters_make_every_team_unable``,
  ``test_i17_multi_holder_player_touches_only_its_teams``,
  ``test_unknown_pick_ownership_is_unverifiable_not_guessed``.  ADDED: every
  unverifiable class over the generator, every mode, with an available
  posture AND a roster lens, plus a control group (the same ledger on the
  clean board reaches YES), so the ownership gate - not a missing input - is
  what keeps YES away.
* I18 N = 2 symmetry of states -- TAM real-board sweep only.  ADDED: synthetic
  sweep over every scenario and mode.  DEFECT FOUND: ``LANE-E-DEFECT-I18-PICKINV``.
* I19 band floor -- TAM ``test_i19_small_private_gift_is_fair_by_the_band_floor``
  (one value, 200).  ADDED: seeded gift values both sides of the floor, and
  gifts from several teams to one (N = 3 and 4), per-team.
* I20 category/fairness C1-C3 -- TAM ``_consistency`` in the real-board
  sweeps, TTV ``test_category_table`` / ``test_exhaustive_category_mapping``.
  ADDED: over the generator in every mode (C2 is gate-aware: the execution
  gate counts as a gate, per §2.8 "no gate fired"), and over NEAR-EVEN package
  cycles that reach all four band levels so FAIR / ``NO_TOO_CLOSE`` are
  checked hundreds of times rather than a handful.
* §2.3 validation order -- TTL ``test_ledger_case`` (one case per reason).
  ADDED: seeded adversarial ledgers carrying SEVERAL violations at once,
  judged by an independent oracle written from the §2.3 table (first failing
  check decides; stable reason; echoed ids sorted, safe-shaped, capped), a
  named matrix of structural abuses (duplicate legs, idle teams, one-sided
  gifts, non-int endpoints, check precedence).  DEFECT FOUND:
  ``LANE-E-DEFECT-ECHO-NEWLINE``.
* §2.9 summary -- TTV ``test_summary_is_ordered_by_roster_id_and_carries_no_trade_level_verdict``.
  ADDED: key whitelist, per-team projection and ``lines`` text over every
  generated ledger and mode.

Board: the LABELLED synthetic 4-team league of ``multi_team_support`` plus,
per team, one LABELLED current-year (2026) round-1 pick with a known slot
(the rookie-draft clock is pinned to 2026 so it resolves the exact slot);
the 2027 picks keep an unknown slot (generic grade).  Eleven board scenarios
(clean, off-board, quarantined, stale value, multi-holder, unknown pick
inventory, unpriced pick, stale / unknown rosters, over-cap, traded picks).
``team_context`` runs with a LABELLED roster lens (``_labelled_roster_utility``,
a pure function of the team's own legs) because the synthetic league has no
projections and every decision would otherwise be ``roster_unknown``.  No live
board value or count is asserted (CI two-lane rule); flags are never touched
(``analyze_trade_n`` is not flag-gated).

Defects are kept as ``xfail(strict=True)`` tests whose reason starts with
``LANE-E-DEFECT-<id>`` and whose docstring is the minimal repro; fixing the
defect makes the strict xfail fail, which is the cue to delete the marker.
"""

from __future__ import annotations

import collections
import copy
import hashlib
import itertools
import json
import random
import re
from dataclasses import replace
from functools import lru_cache
from typing import Any

import pytest

from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from src.valuation_math import fairness_bands, package_model
from tests.trade import multi_team_support as mts

KEY = mts.SYNTH_KEY
POLICY = tl.LedgerPolicy()
CURRENT_YEAR = 2026
#: LABELLED synthetic current-year slot values ("2026 Pick 1.0s").
CURRENT_SLOT_VALUES = {slot: 5000.0 - 100.0 * slot for slot in range(1, 5)}
SCENARIOS = (
    "clean",
    "off_board",
    "quarantined",
    "stale_value",
    "multi_holder",
    "pick_unknown",
    "pick_unpriced",
    "stale_rosters",
    "unknown_rosters",
    "over_cap",
    "traded_picks",  # appended last, so every earlier scenario keeps its seeded stream
)
NOT_CURRENT = ("stale_rosters", "unknown_rosters")
OVER_CAP_SETTINGS = {**mts.SYNTH_SETTINGS, "rosterSize": 5}
ASSET_GATES = {"asset_not_evaluable", "ownership_unverifiable", "evaluation_unavailable"}


def _labelled_roster_utility(
    context, capacity, *, incoming_players=(), outgoing_players=(), **_unused
) -> dict[str, Any]:
    """A LABELLED synthetic best-ball utility (Team Context's roster lens).

    The real one needs league-scored projections the synthetic league does not
    have, so without a stand-in every ``team_context`` decision is
    ``NOT_ENOUGH_EVIDENCE`` / ``roster_unknown`` and the properties that talk
    about YES / NO (I17 "never YES", I20 C1 / C3) would pass VACUOUSLY in that
    mode.  This is a pure function of the team's OWN incoming / outgoing player
    names (net board value plus a hash jitter, so the lens sometimes disagrees
    with the market lens), hence local (I10) and deterministic (I3).  Invented
    for tests; never a measured value."""
    values = _synthetic_values()
    ins, outs = sorted(incoming_players), sorted(outgoing_players)
    net = sum(values.get(n, 0.0) for n in ins) - sum(values.get(n, 0.0) for n in outs)
    digest = hashlib.sha256(("|".join(ins) + "#" + "|".join(outs)).encode()).digest()[0]
    ppg = max(-4.0, min(4.0, net / 1500.0)) + (digest / 255.0 - 0.5)
    return {
        "available": True,
        "unit": "LABELLED synthetic best-ball points per week",
        "impact": {"ppg": ppg, "standardError": 0.2},
        "coverage": {"state": "full", "tradedUnprojectedPlayerIds": []},
        "players": [],
        "depth": {"meanLossDeltaPpg": None},
        "cleanup": {"state": "none", "forcedDropIds": [], "candidatesTied": False},
    }


@lru_cache(maxsize=1)
def _synthetic_values() -> dict[str, float]:
    return {
        r["displayName"]: float(r["rankDerivedValue"])
        for r in _league("clean")["playersArray"]
        if r.get("playerId") and r.get("rankDerivedValue")
    }


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    """Pin the process-global reads that could otherwise decide a comparison:
    league scarcity (R1-2, ``multi_team_support``), the rookie-draft clock (so
    the LABELLED 2026 slot picks are current-year) and the roster lens (a
    LABELLED utility, so ``team_context`` reaches YES / NO / NO_TOO_CLOSE)."""
    from src.api import data_contract
    from src.trade import roster_capacity

    monkeypatch.setattr(data_contract, "current_rookie_draft_year", lambda today=None: 2026)
    monkeypatch.setattr(roster_capacity, "evaluate_final_roster_utility", _labelled_roster_utility)
    return mts.pin_league_scarcity(monkeypatch)


# ══ Board scenarios ════════════════════════════════════════════════════════


def _slot(rid: int) -> int:
    return 5 - rid


def _league(scenario: str) -> dict[str, Any]:
    """The synthetic league (+ current-year slot picks) under one scenario."""
    if scenario == "stale_rosters":
        c = mts.synthetic_league(roster_source="last_good")
    else:
        c = mts.synthetic_league()
    if scenario == "unknown_rosters":
        del c["sleeper"]["rosterSource"]
    for team in c["sleeper"]["teams"]:
        rid = team["roster_id"]
        detail = {
            "season": CURRENT_YEAR,
            "round": 1,
            "fromRosterId": rid,
            "ownerRosterId": rid,
            "slot": _slot(rid),
            "label": f"{CURRENT_YEAR} Pick 1.{_slot(rid):02d}",
            "assetId": f"pick:{KEY}:{CURRENT_YEAR}:r1:o{rid}",
        }
        team["pickDetails"].append(detail)
        team["picks"].append(detail["label"])
    for slot, value in CURRENT_SLOT_VALUES.items():
        name = f"{CURRENT_YEAR} Pick 1.{slot:02d}"
        c["playersArray"].append(
            {
                "displayName": name,
                "canonicalName": name,
                "assetClass": "pick",
                "pos": "PICK",
                "rankDerivedValue": value,
                "values": {"full": value},
            }
        )
    teams = c["sleeper"]["teams"]
    rows = {r.get("playerId"): r for r in c["playersArray"] if r.get("playerId")}
    if scenario == "off_board":
        teams[0]["playerIds"].append("106")  # rostered, no board row
        teams[0]["players"].append("A Ghost")
    elif scenario == "quarantined":
        rows["202"]["quarantined"] = True
        rows["202"]["anomalyFlags"] = ["no_valid_source_values"]
    elif scenario == "stale_value":
        rows["302"]["confidenceAxes"] = {"freshness": "low"}
    elif scenario == "multi_holder":
        teams[1]["playerIds"].append("101")  # 101 on teams 1 and 2
        teams[3]["playerIds"].append("302")  # 302 on teams 3 and 4
    elif scenario == "pick_unknown":
        teams[2].update(
            pickDetails=None,
            picks=None,
            pickOwnershipState="unavailable",
            pickOwnershipReason="traded_picks_fetch_failed",
        )
    elif scenario == "pick_unpriced":
        for r in c["playersArray"]:
            if r.get("canonicalName") == "2027 Round 2":
                r["rankDerivedValue"] = None
                r["values"] = {}
                r["pickValueProvenance"] = {"state": "unavailable", "reason": "LABELLED_test"}
    elif scenario == "traded_picks":
        # Picks held by someone other than their origin: value follows the
        # ORIGIN's slot / the round, never the holder; ownership follows the
        # holder's inventory (team 2 and 3 no longer list what they traded).
        for src, season, rnd, dst in ((2, 2027, 1, 1), (3, CURRENT_YEAR, 1, 1), (4, 2027, 2, 2)):
            giver, taker = teams[src - 1], teams[dst - 1]
            moved = next(
                d for d in giver["pickDetails"] if d["season"] == season and d["round"] == rnd
            )
            giver["pickDetails"].remove(moved)
            giver["picks"] = [d["label"] for d in giver["pickDetails"]]
            moved["ownerRosterId"] = dst
            taker["pickDetails"].append(moved)
            taker["picks"] = [d["label"] for d in taker["pickDetails"]]
    return c


def _snapshot(contract: dict[str, Any], scenario: str) -> tl.TradeSnapshot:
    settings = OVER_CAP_SETTINGS if scenario == "over_cap" else mts.SYNTH_SETTINGS
    return tl.build_trade_snapshot(
        contract, league_key=KEY, roster_settings=settings, now=mts.PINNED_NOW
    )


@lru_cache(maxsize=None)
def _board(scenario: str) -> tuple[dict[str, Any], tl.TradeSnapshot]:
    c = _league(scenario)
    return c, _snapshot(c, scenario)


def _pick_parts(aid: str) -> tuple[int, int, int]:
    m = re.fullmatch(rf"pick:{KEY}:(\d{{4}}):r(\d):o(\d+)", aid)
    assert m, aid
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def board_value(contract: dict[str, Any], aid: str) -> float | None:
    """The asset's value read straight off the LABELLED board (the oracle;
    never the engine's own resolution).  ``None`` = unpriced / off board."""
    rows = contract["playersArray"]
    if aid.startswith("p:"):
        row = next((r for r in rows if r.get("playerId") == aid[2:]), None)
        v = row.get("rankDerivedValue") if row else None
    else:
        season, rnd, origin = _pick_parts(aid)
        name = (
            f"{season} Pick {rnd}.{_slot(origin):02d}"
            if season == CURRENT_YEAR
            else f"{season} Round {rnd}"
        )
        row = next((r for r in rows if r.get("canonicalName") == name), None)
        v = row.get("rankDerivedValue") if row else None
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


# ══ Generators ═════════════════════════════════════════════════════════════


def _pool(snap: tl.TradeSnapshot, rid: int) -> list[str]:
    """Every asset team ``rid`` lists — multi-holder players and
    unknown-ownership picks INCLUDED (unlike ``mts.team_assets``)."""
    team = snap.teams_by_roster_id[rid]
    out = [f"p:{p}" for p in team.get("playerIds") or []]
    details = team.get("pickDetails")
    if details:
        out += [str(d["assetId"]) for d in details]
    else:  # unpublished inventory: the team's own default picks
        out += [f"pick:{KEY}:2027:r{r}:o{rid}" for r in (1, 2)]
    return sorted(set(out))


def gen_ledger(
    snap: tl.TradeSnapshot,
    rng: random.Random,
    *,
    n_teams: int | None = None,
    max_per_team: int = 3,
    gifts: bool = True,
) -> tuple[list[int], list[dict[str, Any]]]:
    """A VALID routed ledger over 2..4 teams: players and picks (current-year
    slots, unknown-slot futures), one-sided gifts and receive-only teams
    allowed (``any_leg``), every listed team touched by a leg."""
    rids = sorted(snap.teams_by_roster_id)
    n = n_teams or rng.randint(2, len(rids))
    teams = sorted(rng.sample(rids, n))
    while True:
        senders = teams if not gifts or rng.random() < 0.6 else rng.sample(teams, rng.randint(1, n))
        used: set[str] = set()
        legs: list[dict[str, Any]] = []
        for rid in senders:
            pool = [a for a in _pool(snap, rid) if a not in used]
            for aid in rng.sample(pool, rng.randint(1, min(max_per_team, len(pool)))):
                used.add(aid)
                legs.append(
                    {"id": aid, "from": rid, "to": rng.choice([t for t in teams if t != rid])}
                )
        if {x["from"] for x in legs} | {x["to"] for x in legs} == set(teams):
            return teams, legs


def _validate(snap, teams, legs, policy=POLICY) -> tl.ValidatedLedger:
    return tl.validate_ledger(snap, teams=teams, legs=legs, policy=policy)


def _available_posture(contract, league_key, team, *, build_if_missing):
    """A LABELLED available posture block (the shape ``posture_block_for``
    publishes), so a team_context NO/YES is never decided by a missing one."""
    return {
        "available": True,
        "label": "HOLD",
        "probabilities": {"PUSH": 0.3, "HOLD": 0.4, "RETOOL": 0.2, "REBUILD": 0.1},
        "confidence": "LOW",
        "paramsVersion": "posture_v1_prior",
        "notes": ["LABELLED synthetic posture (Lane E)"],
        "bundleFreshness": None,
    }


def _run(snap, ledger, mode: str) -> dict[str, Any]:
    kw = {"posture_resolver": _available_posture} if mode == "team_context" else {}
    return svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False, **kw)


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _strip(team: dict[str, Any]) -> dict[str, Any]:
    t = copy.deepcopy(team)
    t.get("analysis", {}).pop("decisionRunId", None)
    return t


def _cases(seed: int, per_scenario: int, *, n_teams: int | None = None):
    """``(scenario, contract, snap, teams, legs)`` — deterministic."""
    rng = random.Random(seed)
    for scenario in SCENARIOS:
        contract, snap = _board(scenario)
        for _ in range(per_scenario):
            teams, legs = gen_ledger(snap, rng, n_teams=n_teams)
            yield scenario, contract, snap, teams, legs


# ══ The per-team oracle ════════════════════════════════════════════════════


def _expected_unverifiable(scenario: str, snap, legs) -> set[str]:
    if scenario in NOT_CURRENT:
        return {x["id"] for x in legs}
    out = set()
    for x in legs:
        aid = x["id"]
        if aid.startswith("p:"):
            if len(snap.player_owners.get(aid[2:]) or ()) >= 2:
                out.add(aid)
        elif scenario == "pick_unknown" and _pick_parts(aid)[2] == 3:
            out.add(aid)
    return out


def _expected_gate(scenario, contract, snap, rid, legs, unverifiable) -> str | None:
    """The fairness ``reasonCode`` the §2.8 gate order must produce for team
    ``rid``, from the board alone; ``None`` = the team is evaluable."""
    mine = [x["id"] for x in legs if rid in (x["from"], x["to"])]
    rows = {r.get("playerId"): r for r in contract["playersArray"] if r.get("playerId")}
    if any(board_value(contract, a) is None for a in mine):
        return "asset_not_evaluable"
    inventory_unknown = scenario == "pick_unknown" and rid == 3
    if any(a in unverifiable for a in mine) or (
        inventory_unknown and any(not a.startswith("p:") for a in mine)
    ):
        return "ownership_unverifiable"
    for a in mine:
        row = rows.get(a[2:]) if a.startswith("p:") else None
        if row and (
            row.get("quarantined") is True
            or (row.get("confidenceAxes") or {}).get("freshness") == "low"
        ):
            return "evaluation_unavailable"
    return None


def _owner_math(contract, rid, legs) -> dict[str, Any]:
    """Team ``rid``'s gap / display side / base / band computed with the
    package-model and fairness-band OWNERS over the board values of its own
    gives and receives (spec §1)."""
    gives = [board_value(contract, x["id"]) for x in legs if x["from"] == rid]
    recv = [board_value(contract, x["id"]) for x in legs if x["to"] == rid]
    send_adj, recv_adj, _sva, _rva = package_model.adjusted_pair_totals(gives, recv)
    gap = recv_adj - send_adj
    base = fairness_bands.larger_package_utility(gives, recv)
    band = fairness_bands.classify(gap, base)
    return {
        "gives": gives,
        "receives": recv,
        "gap": gap,
        "larger": max(send_adj, recv_adj),
        "base": base,
        "band": band,
        "fair": fairness_bands.counts_as_fair_trade(band["level"]),
    }


def _check_team(scenario, contract, snap, out, rid, legs, mode, unverifiable) -> None:
    team = out["teams"][rid]
    d = team["analysis"]["decision"]
    f = team["fairness"]
    gate = _expected_gate(scenario, contract, snap, rid, legs, unverifiable)
    ctx = (scenario, mode, rid, legs)
    # Missing is never zero: a withheld number is None, a published one > 0.
    for row in (*team["gives"], *team["receives"]):
        if row["valueState"] == "priced":
            assert isinstance(row["value"], (int, float)) and row["value"] > 0, ctx
        else:
            assert row["value"] is None, ctx
    # I17: the ownership evidence names exactly this team's unverifiable legs.
    mine = sorted(
        a for a in unverifiable if a in {x["id"] for x in legs if rid in (x["from"], x["to"])}
    )
    assert team["unverifiableAssetIds"] == mine, ctx
    if mine:
        assert team["simulation"]["ownershipEvidence"]["unverifiableAssetIds"] == mine, ctx
        assert d["headline"] != "YES", ctx
        assert f["state"] == "UNABLE", ctx
        assert f["reasonCode"] in ("asset_not_evaluable", "ownership_unverifiable"), ctx
        codes = [g["code"] for g in d.get("missingEvidence") or []]
        assert "ownership_unverifiable" in codes or d["deciding"] == "executionGate", ctx
    else:
        assert "ownershipEvidence" not in team["simulation"], ctx
    if gate is not None:
        assert (f["state"], f["reasonCode"]) == ("UNABLE", gate), ctx
        assert f["gap"] is None, ctx
    else:
        # I14 generalized: the engine's numbers are the owners' math.
        m = _owner_math(contract, rid, legs)
        assert f["state"] == ("FAIR" if m["fair"] else "NOT_FAIR"), ctx
        assert f["gap"] == m["gap"], ctx
        assert f["largerAdjustedSide"] == m["larger"], ctx
        assert f["largerPackageUtility"] == m["base"], ctx
        assert f["level"] == m["band"]["level"], ctx
        assert f["relativePct"] == m["band"]["relativePct"], ctx
        assert f["bands"] == fairness_bands.receipt()["version"], ctx
        if not m["gives"] or not m["receives"]:  # §1 empty-side rule: ±raw sum
            assert f["gap"] == sum(m["receives"]) - sum(m["gives"]), ctx
    # I20 / §2.8 C1-C3.
    if team["category"] == "STRONGLY_FAVORABLE":  # C1
        assert f["state"] == "NOT_FAIR", ctx
    if f["state"] == "UNABLE":  # C3
        assert d["headline"] == "NOT_ENOUGH_EVIDENCE" or (
            d["headline"] == "NO" and d["deciding"] == "executionGate"
        ), ctx
    gated = bool(d.get("missingEvidence")) or d.get("deciding") in ("executionGate", "evidenceGate")
    if mode != "team_context" and not gated:  # C2
        assert (d["headline"] == "NO_TOO_CLOSE") == (f["state"] == "FAIR"), ctx
    # Recommendation != execution.
    assert d["recommendationOnly"] is True and d["executes"] is False, ctx


def _reconciles(out, ledger) -> None:
    """I6 / I7: every leg once in its sender's gives and once in its
    receiver's receives; nothing else, in the rows or the simulation."""
    legs = {leg.asset_id: leg for leg in ledger.legs}
    seen = set()
    # A league team the ledger does not list is not analysed at all.
    assert list(out["teams"]) == sorted(ledger.teams)
    assert out["summary"]["teamCount"] == len(ledger.teams)
    assert out["summary"]["legCount"] == len(ledger.legs)
    for rid, team in out["teams"].items():
        gives = [g["assetId"] for g in team["gives"]]
        recv = [r["assetId"] for r in team["receives"]]
        assert len(gives) == len(set(gives)) and len(recv) == len(set(recv))
        assert set(gives) == {a for a, leg in legs.items() if leg.from_roster_id == rid}
        assert set(recv) == {a for a, leg in legs.items() if leg.to_roster_id == rid}
        for g in team["gives"]:
            assert g["toRosterId"] == legs[g["assetId"]].to_roster_id
        for r in team["receives"]:
            assert r["fromRosterId"] == legs[r["assetId"]].from_roster_id
        seen |= set(gives) | set(recv)
        for side in ("sending", "receiving"):
            for asset in team["simulation"].get(side) or []:
                aid = asset.get("assetId") or (
                    f"p:{asset['playerId']}" if asset.get("playerId") else None
                )
                if aid is not None:
                    assert aid in legs, f"phantom asset {aid}"
    assert seen == set(legs)
    cons = out["summary"]["conservation"]
    assert cons["assetsSent"] == cons["assetsReceived"] == len(legs)
    assert cons["balanced"] is True
    assert [p["rosterId"] for p in out["summary"]["perTeam"]] == sorted(out["teams"])


# ══ Seeded property sweep: I6 I7 I13 I14 I15 I17 I20 + missing-never-zero ══


@pytest.mark.parametrize("mode", svc.MODES)
def test_seeded_sweep_every_scenario_against_the_oracle(mode):
    per = 5 if mode == "team_context" else 16
    values: dict[tuple[str, str], set[Any]] = {}
    reached: set[str] = set()
    for scenario, contract, snap, teams, legs in _cases(20261025 + len(mode), per):
        ledger = _validate(snap, teams, legs)
        unverifiable = _expected_unverifiable(scenario, snap, legs)
        assert set(ledger.unverifiable_asset_ids) == unverifiable, (scenario, legs)
        out = _run(snap, ledger, mode)
        _reconciles(out, ledger)
        for rid in ledger.teams:
            _check_team(scenario, contract, snap, out, rid, legs, mode, unverifiable)
            f = out["teams"][rid]["fairness"]
            reached.add(f["reasonCode"])
            reached.add(f"headline:{out['teams'][rid]['analysis']['decision']['headline']}")
            reached.add(f"category:{out['teams'][rid]['category']}")
            if not out["teams"][rid]["gives"] or not out["teams"][rid]["receives"]:
                reached.add("one_sided_team")
            reached.add(f"n{len(ledger.teams)}")
        # I15: Σ_i (raw_recv_i − raw_send_i) = 0 over assets priced in both views.
        priced: dict[str, list[float]] = {}
        net = 0.0
        for team in out["teams"].values():
            for row in (*team["gives"], *team["receives"]):
                if row["valueState"] == "priced":
                    priced.setdefault(row["assetId"], []).append(row["value"])
        for team in out["teams"].values():
            for side, sign in (("gives", -1), ("receives", 1)):
                for row in team[side]:
                    if len(priced.get(row["assetId"], [])) == 2:
                        net += sign * row["value"]
        assert net == 0, (scenario, legs)
        # I13: one value per asset across every ledger, equal to the board.
        for aid, vs in priced.items():
            values.setdefault((scenario, aid), set()).update(vs)
            assert set(vs) == {int(board_value(contract, aid))}, (scenario, aid, vs)
        # Fairness overall is the Kleene AND of the per-team states (§2.9).
        states = [out["teams"][r]["fairness"]["state"] for r in ledger.teams]
        expect = "NOT_FAIR" if "NOT_FAIR" in states else "UNABLE" if "UNABLE" in states else "FAIR"
        assert out["summary"]["fairnessOverall"]["state"] == expect
    assert all(len(vs) == 1 for vs in values.values())
    # The sweep really reached every branch it claims to cover.
    assert reached >= {
        "within_fairness_threshold",
        "outside_fairness_threshold",
        "asset_not_evaluable",
        "ownership_unverifiable",
        "evaluation_unavailable",
        "one_sided_team",
        "n2",
        "n3",
        "n4",
        # Not vacuous: C1 / C3 / I17 "never YES" are only meaningful when the
        # sweep also reaches YES and NO.  That holds in team_context only
        # because the roster lens is the LABELLED utility above.
        "headline:YES",
        "headline:NO",
        "headline:NOT_ENOUGH_EVIDENCE",
        "category:STRONGLY_FAVORABLE",
        "category:STRONGLY_UNFAVORABLE",
        "category:UNAVAILABLE",
    }, (mode, reached)
    # The sweep really reached both pick grades and every gate class.
    assert any(a.startswith(f"pick:{KEY}:{CURRENT_YEAR}") for _s, a in values)
    assert any(a.startswith(f"pick:{KEY}:2027") for _s, a in values)


def test_unpriced_pick_row_is_none_and_unable_never_zero():
    """I13 / R14d: a pick whose row is unpriced (provenance ``unavailable``)
    is ``value: None`` for sender and receiver and makes both UNABLE."""
    contract, snap = _board("pick_unpriced")
    legs = [
        {"id": f"pick:{KEY}:2027:r2:o1", "from": 1, "to": 2},
        {"id": "p:201", "from": 2, "to": 1},
    ]
    for mode in svc.MODES:
        out = _run(snap, _validate(snap, [1, 2], legs), mode)
        sent = out["teams"][1]["gives"][0]
        got = out["teams"][2]["receives"][0]
        assert (sent["value"], got["value"]) == (None, None)
        # Withheld in both views, never priced (the exact state name is
        # LANE-E-DEFECT-I13-PICKSTATE, pinned separately below).
        assert sent["valueState"] == got["valueState"] != "priced"
        for t in out["teams"].values():
            assert (t["fairness"]["state"], t["fairness"]["reasonCode"]) == (
                "UNABLE",
                "asset_not_evaluable",
            )
        # The unpriced pick is excluded from the raw totals, never counted as 0.
        assert out["summary"]["conservation"]["pricedRawSent"] == 7000


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-I13-PICKSTATE: a pick whose board row exists but is "
        "unpriced (provenance unavailable) reads valueState 'off_board' / gate "
        "off_board_assets; spec I13 (R14d) says it is UNPRICED"
    ),
)
def test_lane_e_defect_i13_unpriced_pick_row_reads_unpriced():
    """Minimal repro.  Synthetic league; the ``2027 Round 2`` board row is
    present with ``rankDerivedValue: None`` and ``pickValueProvenance:
    {"state": "unavailable"}``.  Team 1 sends ``pick:synth:2027:r2:o1`` to
    team 2 for ``p:201`` (7000).  Spec I13: "A pick whose provenance is
    ``unavailable`` is unpriced, giving UNABLE (R14d)."  Actual: UNABLE holds
    (``asset_not_evaluable``), but both rows read ``valueState: "off_board"``,
    the simulation lists the pick in ``unresolvedOut`` / ``unresolvedIn`` and
    the decision gap is ``off_board_assets`` — the asset IS on the board."""
    _contract, snap = _board("pick_unpriced")
    legs = [
        {"id": f"pick:{KEY}:2027:r2:o1", "from": 1, "to": 2},
        {"id": "p:201", "from": 2, "to": 1},
    ]
    out = _run(snap, _validate(snap, [1, 2], legs), "market_fairness")
    assert out["teams"][1]["gives"][0]["valueState"] == "unpriced"
    codes = [g["code"] for g in out["teams"][1]["analysis"]["decision"]["missingEvidence"]]
    assert "unpriced_assets" in codes


def test_current_year_slot_and_future_generic_picks_carry_one_value():
    """I13: the current-year pick resolves its EXACT slot row, the 2027 pick
    (slot unknown) its generic grade — one value per asset in every view."""
    contract, snap = _board("clean")
    legs = [
        {"id": f"pick:{KEY}:{CURRENT_YEAR}:r1:o1", "from": 1, "to": 2},
        {"id": f"pick:{KEY}:2027:r1:o2", "from": 2, "to": 3},
        {"id": "p:301", "from": 3, "to": 1},
    ]
    out = _run(snap, _validate(snap, [1, 2, 3], legs), "market_fairness")
    slot_pick = out["teams"][1]["gives"][0]
    assert slot_pick["value"] == CURRENT_SLOT_VALUES[_slot(1)]
    assert out["teams"][2]["receives"][0]["value"] == slot_pick["value"]
    future = out["teams"][2]["gives"][0]
    assert future["value"] == mts.SYNTH_PICK_ROWS["2027 Round 1"]
    assert out["teams"][3]["receives"][0]["value"] == future["value"]
    for t in out["teams"].values():
        assert t["fairness"]["state"] in ("FAIR", "NOT_FAIR")


# ══ I1 I2 I3: order and determinism over the generator ════════════════════


def test_i1_i2_i3_exhaustive_team_permutations_and_leg_shuffles():
    """Every ordering of the teams (exhaustive, N <= 4) and a fresh shuffle of
    the legs per ordering, in ALL THREE modes: the whole result is
    byte-identical to the first evaluation, and a repeat evaluation is too
    (only the per-request receipt id is excluded, ``_stable``)."""
    rng = random.Random(1)
    for scenario, _contract, snap, teams, legs in _cases(11, 2):
        for mode in svc.MODES:
            reference = _stable(_run(snap, _validate(snap, teams, legs), mode))
            assert _stable(_run(snap, _validate(snap, teams, legs), mode)) == reference  # I3
            for perm in itertools.permutations(teams):  # I1, exhaustive for N <= 4
                shuffled = legs[:]
                rng.shuffle(shuffled)  # I2
                out = _run(snap, _validate(snap, list(perm), shuffled), mode)
                assert _stable(out) == reference, (scenario, mode, perm)


# ══ I5 / I18: N = 2 perspective reversal and symmetry of states ═══════════


def _inventory_unknown_team_receives_a_pick(scenario, legs) -> bool:
    """The LANE-E-DEFECT-I18-PICKINV class (see the strict xfail below)."""
    return scenario == "pick_unknown" and any(
        x["to"] == 3 and not x["id"].startswith("p:") for x in legs
    )


@pytest.mark.parametrize("mode", svc.MODES)
def test_i5_i18_two_team_states_are_symmetric(mode):
    reached_unable = False
    for scenario, _contract, snap, teams, legs in _cases(18, 8, n_teams=2):
        if _inventory_unknown_team_receives_a_pick(scenario, legs):
            continue  # pinned separately: LANE-E-DEFECT-I18-PICKINV
        out = _run(snap, _validate(snap, teams, legs), mode)
        a, b = (out["teams"][r]["fairness"] for r in teams)
        ctx = (scenario, legs)
        assert a["state"] == b["state"], ctx  # I18, UNABLE included
        assert out["summary"]["fairnessOverall"]["state"] == a["state"], ctx
        if a["state"] == "UNABLE":
            reached_unable = True
            assert a["reasonCode"] == b["reasonCode"], ctx
        else:  # I5
            assert a["gap"] == -b["gap"], ctx
            assert a["largerAdjustedSide"] == b["largerAdjustedSide"], ctx
            assert a["largerPackageUtility"] == b["largerPackageUtility"], ctx
            assert (a["level"], a["relativePct"]) == (b["level"], b["relativePct"]), ctx
    assert reached_unable


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-I18-PICKINV: at N = 2 a team whose pick inventory is "
        "unpublished goes UNABLE (pick_ownership_unknown) on RECEIVING a "
        "verified pick while its counterparty is NOT_FAIR — I18 requires equal states"
    ),
)
@pytest.mark.parametrize("mode", svc.MODES)
def test_lane_e_defect_i18_pick_inventory_asymmetry(mode):
    """Minimal repro.  Synthetic league; team 3's ``/traded_picks`` failed
    (``pickDetails: null``, ``pickOwnershipState: "unavailable"``).  Team 1
    sends its OWN pick ``pick:synth:2027:r1:o1`` (published, owned by team 1
    -> the ledger marks it VERIFIED, ``unverifiable_asset_ids == ()``) to team
    3 for ``p:302`` (4000).  Spec I18 / §2.9: at N = 2 both teams' fairness
    states are always equal, UNABLE included.  Actual: team 1 NOT_FAIR
    (``outside_fairness_threshold``), team 3 UNABLE ``ownership_unverifiable``
    via the ``pick_ownership_unknown`` gate (headline NOT_ENOUGH_EVIDENCE)."""
    _contract, snap = _board("pick_unknown")
    legs = [
        {"id": f"pick:{KEY}:2027:r1:o1", "from": 1, "to": 3},
        {"id": "p:302", "from": 3, "to": 1},
    ]
    ledger = _validate(snap, [1, 3], legs)
    assert ledger.unverifiable_asset_ids == ()
    out = _run(snap, ledger, mode)
    assert out["teams"][1]["fairness"]["state"] == out["teams"][3]["fairness"]["state"]


# ══ I8: the verified owner cannot be overridden ═══════════════════════════


def test_i8_reassigned_origin_is_409_when_current_and_unverifiable_otherwise():
    rng = random.Random(8)
    checked = 0
    for scenario in ("clean", "stale_rosters", "unknown_rosters"):
        contract, snap = _board(scenario)
        for _ in range(25):
            teams, legs = gen_ledger(snap, rng, gifts=False)
            i = rng.randrange(len(legs))
            leg = legs[i]
            # A participating team that neither holds the asset nor receives it.
            others = [t for t in teams if t not in (leg["from"], leg["to"])]
            still_touched = any(
                leg["from"] in (x["from"], x["to"]) for j, x in enumerate(legs) if j != i
            )
            if not others or not still_touched:
                continue  # otherwise check 12 (idle_team) would decide first
            bad = [dict(x) for x in legs]
            bad[i]["from"] = rng.choice(others)
            # ...and the request insists, in every field it can think of, that
            # the new origin holds the asset: none of it is read (I8).
            bad[i].update(
                owner=bad[i]["from"],
                ownerRosterId=bad[i]["from"],
                holder=bad[i]["from"],
                verified=True,
                unverifiable=False,
            )
            if scenario == "clean":
                with pytest.raises(tl.LedgerError) as exc:
                    _validate(snap, teams, bad)
                err = exc.value
                assert (err.status, err.error, err.reason) == (
                    409,
                    "stale_assets",
                    "asset_not_owned",
                )
                assert err.asset_ids == (leg["id"],)
                assert err.roster_ids == ()  # the actual owner is never revealed
                assert "rosterIds" not in err.to_dict()
            else:
                ledger = _validate(snap, teams, bad)
                assert leg["id"] in ledger.unverifiable_asset_ids
                out = _run(snap, ledger, "market_fairness")
                for t in out["teams"].values():
                    assert t["fairness"]["state"] == "UNABLE"
            checked += 1
    assert checked >= 30


# ══ I9: renaming changes no verdict ═══════════════════════════════════════


def _renamed(contract: dict[str, Any]) -> dict[str, Any]:
    c = copy.deepcopy(contract)
    for t in c["sleeper"]["teams"]:
        t["name"] = f"Renamed FC {t['roster_id'] * 7}"
        t["players"] = [f"Renamed {pid}" for pid in t["playerIds"]]
        for d in t.get("pickDetails") or []:
            d["label"] = f"Renamed pick {d['assetId'][-8:]}"
        if t.get("pickDetails"):
            t["picks"] = [d["label"] for d in t["pickDetails"]]
    for r in c["playersArray"]:
        if r.get("playerId"):
            r["displayName"] = r["canonicalName"] = f"Renamed {r['playerId']}"
    return c


def _verdict(team: dict[str, Any]) -> dict[str, Any]:
    return {
        "category": team["category"],
        "headline": team["analysis"]["decision"]["headline"],
        "fairness": team["fairness"],
        "unverifiable": team["unverifiableAssetIds"],
        "gives": [
            (g["assetId"], g["value"], g["valueState"], g["toRosterId"]) for g in team["gives"]
        ],
        "receives": [
            (r["assetId"], r["value"], r["valueState"], r["fromRosterId"]) for r in team["receives"]
        ],
    }


def test_i9_renaming_teams_players_and_pick_labels_changes_no_verdict():
    for scenario, contract, snap, teams, legs in _cases(9, 2):
        renamed = _renamed(contract)
        snap2 = _snapshot(renamed, scenario)
        for mode in ("market_fairness", "asset_only"):
            a = _run(snap, _validate(snap, teams, legs), mode)
            b = _run(snap2, _validate(snap2, teams, legs), mode)
            for rid in teams:
                assert _verdict(a["teams"][rid]) == _verdict(b["teams"][rid]), (scenario, mode)
            assert a["summary"]["fairnessOverall"] == b["summary"]["fairnessOverall"]


# ══ I10: locality ═════════════════════════════════════════════════════════


def test_i10_extra_leg_between_other_participants_leaves_a_team_unchanged():
    rng = random.Random(10)
    checked = 0
    for scenario, _contract, snap, teams, legs in _cases(100, 3):
        if len(teams) < 3:
            continue
        i = rng.choice(teams)
        j, k = rng.sample([t for t in teams if t != i], 2)
        free = [a for a in _pool(snap, j) if a not in {x["id"] for x in legs}]
        if not free:
            continue
        more = [*legs, {"id": rng.choice(free), "from": j, "to": k}]
        for mode in svc.MODES:
            a = _run(snap, _validate(snap, teams, legs), mode)
            b = _run(snap, _validate(snap, teams, more), mode)
            assert _canon(_strip(a["teams"][i])) == _canon(_strip(b["teams"][i])), (scenario, mode)
        checked += 1
    assert checked >= 10


def test_i10_new_teams_trading_among_themselves_leave_the_others_unchanged():
    """N grows 2 -> 4 by adding two teams that trade only with each other.
    Market fairness: byte-identical.  Private modes: identical apart from
    the SD-12 ``comparables`` stamp that every team carries at N >= 3."""
    rng = random.Random(1010)
    for scenario in SCENARIOS:
        _contract, snap = _board(scenario)
        for _ in range(2):
            teams, legs = gen_ledger(snap, rng, n_teams=2)
            j, k = [t for t in sorted(snap.teams_by_roster_id) if t not in teams]
            taken = {x["id"] for x in legs}
            a_j = rng.choice([a for a in _pool(snap, j) if a not in taken])
            a_k = rng.choice([a for a in _pool(snap, k) if a not in taken | {a_j}])
            extra = [{"id": a_j, "from": j, "to": k}, {"id": a_k, "from": k, "to": j}]
            for mode in svc.MODES:
                a = _run(snap, _validate(snap, teams, legs), mode)
                b = _run(snap, _validate(snap, [*teams, j, k], [*legs, *extra]), mode)
                for rid in teams:
                    x, y = _strip(a["teams"][rid]), _strip(b["teams"][rid])
                    if mode != "market_fairness":
                        assert y.pop("comparables") == {"state": "not_computed_multi_team"}
                        assert "comparables" not in x
                    assert _canon(x) == _canon(y), (scenario, mode, rid)


# ══ I11 (engine half): fairness is one market quantity ════════════════════


def test_i11_fairness_is_identical_in_every_mode_and_ignores_capacity():
    """Per-team fairness reads the gross market band: identical in the three
    modes and unchanged by the roster cap (§2.8, §10 OD-R)."""
    contract, snap = _board("clean")
    capped = _snapshot(contract, "over_cap")
    rng = random.Random(1111)
    for _ in range(12):
        teams, legs = gen_ledger(snap, rng)
        seen = set()
        for s in (snap, capped):
            ledger = _validate(s, teams, legs)
            for mode in svc.MODES:
                out = _run(s, ledger, mode)
                seen.add(
                    _canon(
                        (
                            {r: out["teams"][r]["fairness"] for r in ledger.teams},
                            out["summary"]["fairnessOverall"],
                            out["summary"]["conservation"],
                        )
                    )
                )
        assert len(seen) == 1, legs


# ══ I14: the worked numbers, re-derived from the owners ═══════════════════


def test_i14_spec_numbers_follow_from_the_owners():
    """Spec I14 / §2.6, computed with ``package_model`` + ``fairness_bands``
    (independent of the engine; the engine half is ``test_i14_one_to_many_directional_numbers``)."""
    teams = {"A": ([6000, 3000], [7000, 2500]), "B": ([7000], [6000]), "C": ([2500], [3000])}
    got = {}
    for name, (g, r) in teams.items():
        send_adj, recv_adj, _s, _r = package_model.adjusted_pair_totals(g, r)
        base = fairness_bands.larger_package_utility(g, r)
        band = fairness_bands.classify(recv_adj - send_adj, base)
        got[name] = (
            recv_adj - send_adj,
            max(send_adj, recv_adj),
            pytest.approx(base),
            band["relativePct"],
            band["level"],
        )
    assert got == {
        "A": (610, 9610, 8950, 6.82, "slight"),
        "B": (-1000, 7000, 7000, 14.29, "unfair"),
        "C": (500, 3000, 3000, 16.67, "unfair"),
    }
    # Raw conservation holds; the adjusted gaps do not sum to zero (R14a).
    assert sum(sum(r) - sum(g) for g, r in teams.values()) == 0
    assert sum(v[0] for v in got.values()) == 110


def test_one_sided_team_gap_is_the_raw_sum_not_the_utility_difference():
    """§1 empty-side rule: G = [6000, 3000], R = [] -> gap = −9000 (raw),
    while U_R − U_G = −(6000 + 0.78 x 3000); the receiver reads +9000."""
    contract, snap = _board("clean")
    legs = [{"id": "p:101", "from": 1, "to": 2}, {"id": "p:102", "from": 1, "to": 2}]
    out = _run(snap, _validate(snap, [1, 2], legs), "market_fairness")
    giver, taker = out["teams"][1]["fairness"], out["teams"][2]["fairness"]
    u = package_model.geom_utility([6000, 3000])
    assert (giver["gap"], taker["gap"]) == (-9000, 9000)
    assert giver["gap"] != -u
    assert giver["largerPackageUtility"] == taker["largerPackageUtility"] == u
    assert giver["state"] == taker["state"] == "NOT_FAIR"


# ══ I15: 1-for-1 cycles ════════════════════════════════════════════════════


def test_i15_one_for_one_cycles_sum_gaps_to_exactly_zero():
    contract, snap = _board("clean")
    rng = random.Random(15)
    for _ in range(30):
        n = rng.randint(2, 4)
        teams = rng.sample(sorted(snap.teams_by_roster_id), n)
        while True:  # a derangement: everyone sends one, receives one
            dest = teams[:]
            rng.shuffle(dest)
            if all(a != b for a, b in zip(teams, dest)):
                break
        legs = []
        for frm, to in zip(teams, dest):
            pool = [a for a in _pool(snap, frm) if board_value(contract, a) is not None]
            legs.append({"id": rng.choice(pool), "from": frm, "to": to})
        out = _run(snap, _validate(snap, teams, legs), "market_fairness")
        gaps = [t["fairness"]["gap"] for t in out["teams"].values()]
        assert all(isinstance(g, (int, float)) for g in gaps), legs
        assert sum(gaps) == 0, legs
        cons = out["summary"]["conservation"]
        assert (
            cons["pricedRawSent"]
            == cons["pricedRawReceived"]
            == sum(int(board_value(contract, x["id"])) for x in legs)
        )


# ══ I16: forced drops ══════════════════════════════════════════════════════


def test_i16_forced_drops_over_the_generator():
    contract, snap = _board("over_cap")
    rng = random.Random(16)
    forced = 0
    for _ in range(25):
        teams, legs = gen_ledger(snap, rng, max_per_team=3)
        ledger = _validate(snap, teams, legs)
        leg_ids = {leg.asset_id for leg in ledger.legs}
        out = _run(snap, ledger, "asset_only")
        _reconciles(out, ledger)
        for rid, team in out["teams"].items():
            cap = team["simulation"]["rosterCapacity"]
            drops = {str(d["playerId"]) for d in cap.get("forcedDrops") or []}
            forced += len(drops)
            gives = {g["assetId"][2:] for g in team["gives"] if g["kind"] == "player"}
            gets = {r["assetId"][2:] for r in team["receives"] if r["kind"] == "player"}
            post = (set(snap.teams_by_roster_id[rid]["playerIds"]) - gives) | gets
            assert drops <= post, (rid, legs)  # chosen from post_i
            assert not drops & gives, (rid, legs)  # disjoint from G_i
            listed = {x["assetId"] for x in (*team["gives"], *team["receives"])}
            assert not {f"p:{d}" for d in drops} & (listed - {f"p:{g}" for g in gets})
            assert listed <= leg_ids  # never a leg, never in gives/receives
            if cap.get("overLimitAfter"):
                assert len(drops) == cap["overLimitAfter"] or cap.get("forcedDropsAreUpperBound")
        assert out["summary"]["conservation"]["assetsSent"] == len(legs)
    assert forced > 0  # the sweep really exercised the forced-drop path


# ══ I17 in team_context with an available posture ═════════════════════════


def test_i17_unverifiable_assets_never_yield_yes_even_with_a_posture():
    """I17, with a control group: the SAME ledger on the clean board (ownership
    provable) reaches YES for some team, so the ownership gate - not a missing
    posture or roster lens - is what withheld it on the unverifiable boards."""
    rng = random.Random(17)
    _clean_contract, clean = _board("clean")
    prevented_yes = 0
    for scenario in ("multi_holder", "pick_unknown", "stale_rosters", "unknown_rosters"):
        _contract, snap = _board(scenario)
        hits = 0
        for _ in range(12):
            teams, legs = gen_ledger(snap, rng)
            ledger = _validate(snap, teams, legs)
            try:
                twin = _run(clean, _validate(clean, teams, legs), "team_context")["teams"]
            except tl.LedgerError:  # e.g. a multi-holder leg the clean board refuses
                twin = {}
            for mode in svc.MODES:
                out = _run(snap, ledger, mode)
                for rid, team in out["teams"].items():
                    if not team["unverifiableAssetIds"]:
                        continue
                    hits += 1
                    d = team["analysis"]["decision"]
                    assert d["headline"] == "NOT_ENOUGH_EVIDENCE" or (
                        d["headline"] == "NO" and d["deciding"] == "executionGate"
                    ), (scenario, mode)
                    assert team["fairness"]["state"] == "UNABLE"
                    assert team["category"] not in ("FAVORABLE", "STRONGLY_FAVORABLE")
                    if mode == "team_context" and rid in twin:
                        control = twin[rid]["analysis"]["decision"]["headline"]
                        prevented_yes += control == "YES"
        assert hits, scenario
    assert prevented_yes > 0  # the control group reached YES: the gate is what held it back


# ══ I19: the band floor ═══════════════════════════════════════════════════


def test_i19_gift_values_either_side_of_the_absolute_floor():
    rng = random.Random(19)
    floor = fairness_bands.receipt()["absoluteMinimum"]
    values = [rng.randint(1, int(floor) - 1) for _ in range(10)]
    values += [int(floor), *(rng.randint(int(floor), 9999) for _ in range(10))]
    for v in values:
        c = _league("clean")
        for r in c["playersArray"]:
            if r.get("playerId") == "204":
                r["rankDerivedValue"] = float(v)
                r["values"] = {"full": float(v)}
        snap = _snapshot(c, "clean")
        out = _run(
            snap, _validate(snap, [1, 2], [{"id": "p:204", "from": 2, "to": 1}]), "asset_only"
        )
        states = {t["fairness"]["state"] for t in out["teams"].values()}
        assert states == ({"FAIR"} if v < floor else {"NOT_FAIR"}), v
        assert {t["fairness"]["gap"] for t in out["teams"].values()} == {v, -v}


# ══ §2.3 adversarial ledgers against an independent oracle ═══════════════

_ECHO = re.compile(r"^[A-Za-z0-9:_-]{1,64}$")
JUNK_IDS = (
    "p:777",
    "p:12-3",
    "A Six",
    "<script>",
    "pick:other:2027:r1:o1",
    f"pick:{KEY}:2027:r3:o1",
    f"pick:{KEY}:2027:r1:o9",
    "",
)


def _oracle(scenario, contract, snap, teams, legs, policy):
    """§2.3 written out independently: ``("ok", unverifiable)`` or
    ``(status, error, reason, asset_ids, roster_ids)``."""
    cap = policy.max_legs

    def err(status, reason, aids=(), rids=()):
        error = "stale_assets" if status == 409 else "invalid_trade"
        echo = sorted({str(a) for a in aids if _ECHO.match(str(a))})[:cap]
        return (status, error, reason, tuple(echo), tuple(sorted(set(rids))[:cap]))

    league = {t["roster_id"] for t in contract["sleeper"]["teams"]}
    distinct = sorted(set(teams))
    if len(distinct) < policy.min_teams:
        return err(400, "too_few_teams", rids=distinct)
    dups = [t for t in distinct if teams.count(t) > 1]
    if dups:
        return err(400, "duplicate_team", rids=dups)
    if len(distinct) > min(policy.max_teams, len(league)):
        return err(400, "too_many_teams", rids=distinct)
    foreign = [t for t in distinct if t not in league]
    if foreign:
        return err(400, "team_not_in_league", rids=foreign)
    if not legs:
        return err(400, "empty_trade")
    if len(legs) > cap:
        return err(400, "too_many_assets")
    holders: dict[str, set[int]] = {}
    for t in contract["sleeper"]["teams"]:
        for pid in t["playerIds"]:
            holders.setdefault(str(pid), set()).add(t["roster_id"])
    known_players = set(holders) | set(contract["sleeper"]["idToPlayer"])

    def pick_state(aid):
        own = tl.lookup_league_pick_owner((), aid, index=snap.pick_owner_index)
        return own.state, own.owner_roster_id

    def known(aid):
        if aid.startswith("p:"):
            pid = aid[2:]
            return bool(pid) and pid.isalnum() and pid.isascii() and pid in known_players
        if not re.fullmatch(rf"pick:{KEY}:\d{{4}}:r\d+:o\d+", aid):
            return False
        return pick_state(aid)[0] != "absent"

    unknown = [x["id"] for x in legs if not known(x["id"])]
    if unknown:
        return err(400, "unknown_asset", aids=unknown)
    ids = [x["id"] for x in legs]
    dup_ids = [a for a in ids if ids.count(a) > 1]
    if dup_ids:
        return err(400, "duplicate_asset", aids=dup_ids)
    tset = set(distinct)
    bad = [x["id"] for x in legs if x["from"] not in tset]
    if bad:
        return err(400, "invalid_origin", aids=bad)
    bad = [x["id"] for x in legs if x["to"] not in tset]
    if bad:
        return err(400, "invalid_destination", aids=bad)
    bad = [x["id"] for x in legs if x["from"] == x["to"]]
    if bad:
        return err(400, "destination_is_origin", aids=bad)
    senders, receivers = {x["from"] for x in legs}, {x["to"] for x in legs}
    idle = [t for t in distinct if t not in senders | receivers]
    if idle:
        return err(400, "idle_team", rids=idle)
    if policy.participation == "send_and_receive":
        lop = [t for t in distinct if t not in senders or t not in receivers]
        if lop:
            return err(400, "one_sided_trade", rids=lop)
    if scenario in NOT_CURRENT:
        return ("ok", tuple(sorted(ids)))
    unverifiable, not_owned = [], []
    for x in legs:
        aid, frm = x["id"], x["from"]
        if aid.startswith("p:"):
            h = holders.get(aid[2:], set())
            if h == {frm}:
                continue
            if len(h) >= 2 and frm in h:
                unverifiable.append(aid)
            else:
                not_owned.append(aid)
        else:
            state, owner = pick_state(aid)
            if state == "unknown":
                unverifiable.append(aid)
            elif owner != frm:
                not_owned.append(aid)
    if not_owned:
        return err(409, "asset_not_owned", aids=not_owned)
    return ("ok", tuple(sorted(unverifiable)))


def _mutate(rng, snap, teams, legs, policy):
    """Apply 1..3 random §2.3 violations; returns ``(teams, legs, policy)``."""
    teams, legs = list(teams), [dict(x) for x in legs]
    league = sorted(snap.teams_by_roster_id)
    outside = [t for t in league if t not in teams]
    for _ in range(rng.randint(1, 3)):
        kind = rng.choice(
            [
                "too_few",
                "dup_team",
                "too_many",
                "foreign_team",
                "empty",
                "too_many_assets",
                "unknown_asset",
                "dup_asset",
                "bad_origin",
                "bad_dest",
                "self_dest",
                "idle",
                "one_sided",
                "not_owned",
                "free_agent",
            ]
        )
        if kind == "too_few":
            teams = teams[:1]
        elif kind == "dup_team":
            teams.append(rng.choice(teams))
        elif kind == "too_many":
            if rng.random() < 0.5:
                teams = [*league, 5]
            else:
                policy = replace(policy, max_teams=max(2, len(set(teams)) - 1))
        elif kind == "foreign_team":
            teams.append(rng.choice([9, 12, 0]))
        elif kind == "empty":
            legs = []
        elif kind == "too_many_assets" and len(legs) >= 2:
            policy = replace(policy, max_legs=len(legs) - 1)
        elif kind == "unknown_asset":
            legs.append(
                {"id": rng.choice(JUNK_IDS), "from": rng.choice(teams), "to": rng.choice(teams)}
            )
        elif kind == "dup_asset" and legs:
            copy_ = dict(rng.choice(legs))
            copy_["to"] = rng.choice(teams)
            legs.append(copy_)
        elif kind == "bad_origin" and outside:
            src = rng.choice(outside)
            legs.append({"id": rng.choice(_pool(snap, src)), "from": src, "to": rng.choice(teams)})
        elif kind == "bad_dest" and legs:
            rng.choice(legs)["to"] = rng.choice([*outside, 9])
        elif kind == "self_dest" and legs:
            leg = rng.choice(legs)
            leg["to"] = leg["from"]
        elif kind == "idle" and outside:
            teams.append(rng.choice(outside))
        elif kind == "one_sided":
            policy = replace(policy, participation="send_and_receive")
        elif kind == "not_owned" and legs and len(set(teams)) >= 2:
            leg = rng.choice(legs)
            leg["from"] = rng.choice([t for t in teams if t != leg["from"]] or teams)
        elif kind == "free_agent" and legs:
            legs.append({"id": "p:999", "from": rng.choice(teams), "to": rng.choice(teams)})
    return teams, legs, policy


def test_adversarial_ledgers_follow_the_spec_validation_order():
    rng = random.Random(23)
    reasons: set[str] = set()
    for scenario in ("clean", "multi_holder", "pick_unknown", "stale_rosters", "unknown_rosters"):
        contract, snap = _board(scenario)
        for _ in range(160):
            teams, legs = gen_ledger(snap, rng)
            teams, legs, policy = _mutate(rng, snap, teams, legs, POLICY)
            perm_teams = teams[:]
            rng.shuffle(perm_teams)
            perm_legs = legs[:]
            rng.shuffle(perm_legs)
            expect = _oracle(scenario, contract, snap, teams, legs, policy)
            for t, lg in ((teams, legs), (perm_teams, perm_legs)):  # order never decides
                ctx = (scenario, t, lg, policy)
                if expect[0] == "ok":
                    ledger = tl.validate_ledger(snap, teams=t, legs=lg, policy=policy)
                    assert ledger.unverifiable_asset_ids == expect[1], ctx
                    assert list(ledger.teams) == sorted(set(t)), ctx
                    assert [leg.asset_id for leg in ledger.legs] == sorted(x["id"] for x in lg)
                    reasons.add("ok")
                    continue
                with pytest.raises(tl.LedgerError) as exc:
                    tl.validate_ledger(snap, teams=t, legs=lg, policy=policy)
                e = exc.value
                assert (e.status, e.error, e.reason, e.asset_ids, e.roster_ids) == expect, ctx
                reasons.add(e.reason)
    # The fuzz reached every stable reason code of §2.3 (and valid ledgers).
    assert reasons >= {
        "ok",
        "too_few_teams",
        "duplicate_team",
        "too_many_teams",
        "team_not_in_league",
        "empty_trade",
        "too_many_assets",
        "unknown_asset",
        "duplicate_asset",
        "invalid_origin",
        "invalid_destination",
        "destination_is_origin",
        "idle_team",
        "one_sided_trade",
        "asset_not_owned",
    }, reasons


# ══════════════════════════════════════════════════════════════════════════
# Lane E, second pass: stratified generators, post-trade reconciliation,
# evaluation-order independence, label chaos, adversarial matrix
# ══════════════════════════════════════════════════════════════════════════


# ══ Near-even ledgers: the FAIR cut is actually reached (I20 / C2 have teeth) ═


def gen_near_even_ledger(
    contract: dict[str, Any],
    snap: tl.TradeSnapshot,
    rng: random.Random,
    tol: float,
    *,
    n_teams: int | None = None,
) -> tuple[list[int], list[dict[str, Any]]] | None:
    """A package CYCLE built to land near the FAIR cut: every team sends one
    package of 1-2 of its own priced assets whose board total is within ``tol``
    of a common target to the next team of a random cycle.  The uniform random
    generator almost never produces FAIR (~1 % of teams), which would leave
    C2 (``NO_TOO_CLOSE`` <=> FAIR) checked on a handful of cases; ``tol`` sweeps
    the sample from deep inside the fair band out to lopsided.  ``None`` when
    no package set fits (callers skip)."""
    rids = sorted(snap.teams_by_roster_id)
    n = n_teams or rng.randint(2, len(rids))
    teams = sorted(rng.sample(rids, n))
    pools = {r: [a for a in _pool(snap, r) if board_value(contract, a) is not None] for r in teams}
    packages = {
        r: [
            (combo, sum(board_value(contract, a) for a in combo))
            for size in (1, 2)
            for combo in itertools.combinations(pools[r], size)
        ]
        for r in teams
    }
    for _ in range(60):
        target = rng.choice(packages[rng.choice(teams)])[1]
        chosen: dict[int, tuple[str, ...]] = {}
        for r in teams:
            near = [combo for combo, total in packages[r] if abs(total - target) <= tol]
            if not near:
                break
            chosen[r] = rng.choice(near)
        else:
            while True:
                dest = teams[:]
                rng.shuffle(dest)
                if all(a != b for a, b in zip(teams, dest)):
                    break
            return teams, [
                {"id": aid, "from": frm, "to": to}
                for frm, to in zip(teams, dest)
                for aid in chosen[frm]
            ]
    return None


@pytest.mark.parametrize("mode", svc.MODES)
@pytest.mark.parametrize("scenario", ["clean", "over_cap", "traded_picks"])
def test_near_even_ledgers_reach_every_band_and_c1_c3_hold(scenario, mode):
    """I20 with the FAIR cut actually exercised: ``tol`` sweeps package cycles
    from inside the fair band out to lopsided; every team is checked against
    the owners' math (``_check_team``, which carries C1-C3) and the sample must
    contain all four band levels - and, outside team_context, both sides of
    C2 (``NO_TOO_CLOSE`` <=> FAIR) many times over."""
    contract, snap = _board(scenario)
    rng = random.Random(7000 + 13 * len(mode) + len(scenario))
    levels: collections.Counter = collections.Counter()
    c2_fair = c2_other = checked = 0
    for i in range(54):
        built = gen_near_even_ledger(contract, snap, rng, (40, 120, 260, 500, 900, 1700)[i % 6])
        if built is None:
            continue
        teams, legs = built
        ledger = _validate(snap, teams, legs)
        out = _run(snap, ledger, mode)
        _reconciles(out, ledger)
        checked += 1
        for rid in ledger.teams:
            _check_team(scenario, contract, snap, out, rid, legs, mode, set())
            team = out["teams"][rid]
            decision = team["analysis"]["decision"]
            levels[team["fairness"]["level"]] += 1
            if mode != "team_context" and not decision.get("missingEvidence"):  # C2
                if team["fairness"]["state"] == "FAIR":
                    c2_fair += 1
                    assert decision["headline"] == "NO_TOO_CLOSE", legs
                else:
                    c2_other += 1
                    assert decision["headline"] != "NO_TOO_CLOSE", legs
    assert checked >= 40
    assert set(levels) >= set(fairness_bands.LEVELS), levels
    if mode != "team_context":
        assert c2_fair >= 25 and c2_other >= 25, (c2_fair, c2_other)


# ══ I6: the simulated roster change IS the ledger's net flow ═══════════════

_BUCKETS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def _bucket(position: str) -> str:
    return position if position in _BUCKETS else "IDP"


def _expected_roster_delta(
    contract: dict[str, Any], rid: int, legs: list[dict[str, Any]]
) -> tuple[float, collections.Counter]:
    """What team ``rid``'s roster must change by, read off the LABELLED board
    and the ledger alone: net board value, and a head-count per position bucket.
    A player with a board row counts (even unpriced); a rostered player with no
    row and a pick with no price are counted nowhere (missing is not a zero-
    value asset)."""
    rows = {r["playerId"]: r for r in contract["playersArray"] if r.get("playerId")}
    total, counts = 0.0, collections.Counter()
    for x in legs:
        sign = (x["to"] == rid) - (x["from"] == rid)
        if not sign:
            continue
        aid, value = x["id"], board_value(contract, x["id"])
        if aid.startswith("p:"):
            row = rows.get(aid[2:])
            if row is None:
                continue
            counts[_bucket(row["position"])] += sign
        else:
            if value is None:
                continue
            counts["PICK"] += sign
        total += sign * (value or 0.0)
    return total, counts


@pytest.mark.parametrize("mode", svc.MODES)
def test_i6_simulated_roster_change_equals_the_ledgers_net_flow(mode):
    """I6 beyond ``gives`` / ``receives``: team i's simulated post-trade roster
    is ``pre_i - G_i + R_i`` (spec 2.4).  Value totals and per-position head
    counts must move by exactly the ledger's net flow in every scenario -
    forced drops, unverifiable ownership and withheld values included - and a
    team's PRE-trade roster must be the snapshot's whatever ledger it is in."""
    before_seen: dict[tuple[str, int], Any] = {}
    compared = 0
    for scenario, contract, snap, teams, legs in _cases(61, 8):
        out = _run(snap, _validate(snap, teams, legs), mode)
        for rid, team in out["teams"].items():
            sim = team["simulation"]
            total, counts = _expected_roster_delta(contract, rid, legs)
            ctx = (scenario, mode, rid, legs)
            assert sim["delta"]["totalValue"] == pytest.approx(total), ctx
            assert sim["after"]["totalValue"] - sim["before"]["totalValue"] == pytest.approx(
                total
            ), ctx
            for pos, cell in sim["delta"]["byPosition"].items():
                assert cell["count"] == counts.get(pos, 0), (pos, ctx)
            if scenario == "pick_unknown" and rid == 3:
                # The unpublished inventory is LABELLED unknown on the team's own
                # simulation; its 'before' can only show the picks the trade names.
                assert sim["pickOwnership"]["state"] == "unavailable", ctx
            else:
                assert sim["before"] == before_seen.setdefault((scenario, rid), sim["before"]), ctx
            compared += 1
    assert compared >= 150


# ══ I3 / purity: nothing an earlier evaluation did may show in a later one ═


def _stable(out: dict[str, Any]) -> str:
    """The whole result minus the per-request receipt id (I3 exclusions)."""
    return _canon(
        {
            "teams": {r: _strip(t) for r, t in out["teams"].items()},
            "summary": out["summary"],
            "ledger": out["ledger"],
            "mode": out["mode"],
        }
    )


@pytest.mark.parametrize(
    "scenario", ["clean", "multi_holder", "over_cap", "quarantined", "traded_picks"]
)
def test_i3_results_do_not_depend_on_what_was_evaluated_before(scenario):
    """Evaluate the same ledgers forward, backward and after a deliberately
    different 'poison' run on ONE snapshot, then on a snapshot rebuilt from the
    same contract: byte-identical every time (no cache, memo or shared state may
    leak between requests), and the analysis never writes the board, a roster or
    the snapshot (it is a read of ONE captured contract)."""
    contract, snap = _board(scenario)
    frozen_contract = copy.deepcopy(contract)
    frozen_teams = copy.deepcopy(dict(snap.teams_by_roster_id))
    rng = random.Random(33 + len(scenario))
    ledgers = [_validate(snap, *gen_ledger(snap, rng)) for _ in range(6)]
    poison = _validate(snap, *gen_ledger(snap, random.Random(9), n_teams=4, max_per_team=3))
    rebuilt = _snapshot(copy.deepcopy(contract), scenario)
    for mode in svc.MODES:
        forward = [_stable(_run(snap, ledger, mode)) for ledger in ledgers]
        _run(snap, poison, mode)
        backward = [_stable(_run(snap, ledger, mode)) for ledger in reversed(ledgers)]
        assert forward == backward[::-1], (scenario, mode)
        again = [
            _stable(
                _run(rebuilt, tl.validate_ledger(rebuilt, **_replay(ledger), policy=POLICY), mode)
            )
            for ledger in ledgers
        ]
        assert forward == again, (scenario, mode)
    assert contract == frozen_contract
    assert dict(snap.teams_by_roster_id) == frozen_teams


def _replay(ledger: tl.ValidatedLedger) -> dict[str, Any]:
    """``validate_ledger`` keyword arguments that rebuild ``ledger``."""
    return {"teams": list(ledger.teams), "legs": [leg.to_dict() for leg in ledger.legs]}


# ══ I9, adversarial: swapped, odd and colliding labels ═════════════════════


def _label_chaos(
    contract: dict[str, Any],
    seed: int,
    *,
    relabel_picks: bool = True,
    duplicate_names: bool = True,
) -> dict[str, Any]:
    """Every rename a data feed could plausibly (or implausibly) produce:
    names swapped between players, a player named like ANOTHER asset's id, a
    player named like a pick row, two teams with one name and pick labels
    shuffled across rounds and shared by several picks - and, with
    ``duplicate_names``, several players sharing one display name (including a
    case / whitespace twin of someone else's name).  Identity is the rosterId /
    assetId, so no verdict may move."""
    rng = random.Random(seed)
    c = copy.deepcopy(contract)
    rows = {r["playerId"]: r for r in c["playersArray"] if r.get("playerId")}
    ids = sorted(rows)
    names = {pid: rows[pid]["displayName"] for pid in ids}
    new = dict(names)
    if duplicate_names:
        for _ in range(3):
            a, b = rng.sample(ids, 2)
            new[b] = new[a]
    for _ in range(2):
        a, b = rng.sample(ids, 2)
        new[a], new[b] = new[b], new[a]
    a, b, c3, d = rng.sample(ids, 4)
    new[a] = f"p:{b}"
    new[b] = "2027 Round 1"
    new[c3] = names[d].upper() + " " if duplicate_names else f"Twin of {names[d]}"
    for pid, name in new.items():
        rows[pid]["displayName"] = rows[pid]["canonicalName"] = name
    labels = [d_["label"] for t in c["sleeper"]["teams"] for d_ in t.get("pickDetails") or []]
    for t in c["sleeper"]["teams"]:
        t["name"] = rng.choice(["Team A", "Same Name"])
        t["players"] = [new.get(str(pid), nm) for pid, nm in zip(t["playerIds"], t["players"])]
        if relabel_picks and t.get("pickDetails"):
            for d_ in t["pickDetails"]:
                d_["label"] = rng.choice([*labels, "x", ""])
            t["picks"] = [d_["label"] for d_ in t["pickDetails"]]
    return c


def _capacity_view(team: dict[str, Any]) -> tuple[Any, ...]:
    cap = team["simulation"].get("rosterCapacity") or {}
    return (
        cap.get("sizeBefore"),
        cap.get("sizeAfter"),
        cap.get("overLimitAfter"),
        cap.get("outgoingNotOnRoster"),
        sorted(str(d.get("playerId")) for d in cap.get("forcedDrops") or []),
        cap.get("ladderExhausted"),
    )


def _needs_a_cut(team: dict[str, Any]) -> bool:
    cap = team["simulation"].get("rosterCapacity") or {}
    return cap.get("requiresDrops") is not False and bool(cap)


@pytest.mark.parametrize("mode", ["market_fairness", "asset_only"])
def test_i9_swapped_and_odd_unique_labels_change_no_verdict_or_forced_cut(mode):
    """(``team_context`` is excluded only because the LABELLED roster lens is,
    by construction, a function of player NAMES; the verdict machinery under
    test is identical in all three modes.)  Names stay UNIQUE here: collisions
    are the next test and a strict xfail."""
    compared = 0
    for k, (scenario, contract, snap, teams, legs) in enumerate(_cases(91, 4)):
        # ``pick_unpriced`` keeps its pick labels: relabelling there is the strict
        # xfail below (LANE-E-DEFECT-I9-PICKLABEL); every other rename still runs.
        chaos = _snapshot(
            _label_chaos(
                contract,
                1000 + k,
                relabel_picks=scenario != "pick_unpriced",
                duplicate_names=False,
            ),
            scenario,
        )
        ledger = _validate(snap, teams, legs)
        a = _run(snap, ledger, mode)
        b = _run(chaos, _validate(chaos, teams, legs), mode)
        for rid in ledger.teams:
            ctx = (scenario, mode, rid, legs)
            assert _verdict(a["teams"][rid]) == _verdict(b["teams"][rid]), ctx
            assert _capacity_view(a["teams"][rid]) == _capacity_view(b["teams"][rid]), ctx
            compared += 1
        assert a["summary"]["fairnessOverall"] == b["summary"]["fairnessOverall"]
        assert a["summary"]["conservation"] == b["summary"]["conservation"]
    assert compared >= 80


@pytest.mark.parametrize("mode", ["market_fairness", "asset_only"])
def test_i9_players_sharing_a_display_name_change_no_verdict_unless_a_cut_is_needed(mode):
    """Players who share a display name (and case / whitespace twins) must not
    move any verdict.  A team that must RELEASE someone is the one place the
    capacity owner still joins the roster to the board by NAME - that is the
    strict xfail ``LANE-E-DEFECT-I9-DUPNAME`` below, so a team the baseline says
    needs a cut is excluded from this comparison and pinned there instead."""
    compared = skipped = 0
    for k, (scenario, contract, snap, teams, legs) in enumerate(_cases(92, 5)):
        collided = _snapshot(
            _label_chaos(contract, 2000 + k, relabel_picks=False, duplicate_names=True), scenario
        )
        ledger = _validate(snap, teams, legs)
        a = _run(snap, ledger, mode)
        b = _run(collided, _validate(collided, teams, legs), mode)
        for rid in ledger.teams:
            if _needs_a_cut(a["teams"][rid]):
                skipped += 1
                continue
            ctx = (scenario, mode, rid, legs)
            assert _verdict(a["teams"][rid]) == _verdict(b["teams"][rid]), ctx
            compared += 1
    assert compared >= 90
    if mode == "asset_only":
        assert skipped > 0  # the sweep really did reach the cut path it is carving out


# ══ Traded picks: value follows the ORIGIN, ownership follows the HOLDER ═══


def test_traded_pick_value_follows_origin_and_ownership_follows_holder():
    _clean_contract, clean = _board("clean")
    _traded_contract, traded = _board("traded_picks")
    moved = f"pick:{KEY}:2027:r1:o2"  # team 2's pick, held by team 1 on this board
    # I13: the same pick id carries the same value whoever holds it.
    out_clean = _run(
        clean,
        _validate(
            clean, [2, 4], [{"id": moved, "from": 2, "to": 4}, {"id": "p:401", "from": 4, "to": 2}]
        ),
        "market_fairness",
    )
    out_traded = _run(
        traded,
        _validate(
            traded, [1, 4], [{"id": moved, "from": 1, "to": 4}, {"id": "p:401", "from": 4, "to": 1}]
        ),
        "market_fairness",
    )
    assert out_clean["teams"][2]["gives"][0]["value"] == out_traded["teams"][1]["gives"][0]["value"]
    assert out_clean["teams"][4]["receives"][0]["value"] == 3600
    # The ORIGIN no longer holds it: sending it is a 409 that never names the holder (I8).
    with pytest.raises(tl.LedgerError) as exc:
        _validate(
            traded, [2, 4], [{"id": moved, "from": 2, "to": 4}, {"id": "p:401", "from": 4, "to": 2}]
        )
    err = exc.value
    assert (err.status, err.reason, err.asset_ids, err.roster_ids) == (
        409,
        "asset_not_owned",
        (moved,),
        (),
    )
    # The simulated rosters follow the holder: team 1's pick count drops, team 2's does not.
    legs = [{"id": moved, "from": 1, "to": 3}, {"id": "p:301", "from": 3, "to": 1}]
    out = _run(traded, _validate(traded, [1, 3], legs), "asset_only")
    assert out["teams"][1]["simulation"]["delta"]["byPosition"]["PICK"]["count"] == -1
    assert out["teams"][3]["simulation"]["delta"]["byPosition"]["PICK"]["count"] == 1
    # Current-year slot value is the origin's slot (team 3's), held by team 1.
    slot_pick = f"pick:{KEY}:{CURRENT_YEAR}:r1:o3"
    legs = [{"id": slot_pick, "from": 1, "to": 3}, {"id": "p:301", "from": 3, "to": 1}]
    out = _run(traded, _validate(traded, [1, 3], legs), "market_fairness")
    assert out["teams"][1]["gives"][0]["value"] == CURRENT_SLOT_VALUES[_slot(3)]
    assert out["teams"][3]["receives"][0]["value"] == CURRENT_SLOT_VALUES[_slot(3)]


# ══ Named adversarial ledgers: the structural abuses, one by one ═══════════
#
# (board, teams, legs, policy overrides, expected).  ``expected`` is
# ``("ok", unverifiable_ids)`` or ``(status, reason, asset_ids, roster_ids)``.
# The fuzz above finds these by chance; these pin the exact answer.

_SR = {"participation": "send_and_receive"}
NAMED_LEDGERS: list[tuple[str, str, list[Any], list[tuple[Any, Any, Any]], dict, tuple]] = [
    (
        "exact_duplicate_leg",
        "clean",
        [1, 2],
        [("p:101", 1, 2), ("p:101", 1, 2), ("p:201", 2, 1)],
        {},
        (400, "duplicate_asset", ("p:101",), ()),
    ),
    (
        "one_asset_two_receivers",
        "clean",
        [1, 2, 3],
        [("p:101", 1, 2), ("p:101", 1, 3), ("p:201", 2, 1), ("p:301", 3, 1)],
        {},
        (400, "duplicate_asset", ("p:101",), ()),
    ),
    (
        "one_asset_two_senders",
        "clean",
        [1, 2],
        [("p:101", 1, 2), ("p:101", 2, 1)],
        {},
        (400, "duplicate_asset", ("p:101",), ()),
    ),
    (
        "duplicate_is_decided_before_ownership",
        "clean",
        [1, 2],
        [("p:201", 1, 2), ("p:201", 1, 2)],
        {},
        (400, "duplicate_asset", ("p:201",), ()),
    ),
    (
        "duplicate_pick_leg",
        "clean",
        [1, 2],
        [("pick:synth:2027:r1:o1", 1, 2), ("pick:synth:2027:r1:o1", 1, 2), ("p:201", 2, 1)],
        {},
        (400, "duplicate_asset", ("pick:synth:2027:r1:o1",), ()),
    ),
    (
        "listed_team_with_no_leg",
        "clean",
        [1, 2, 3, 4],
        [("p:101", 1, 2), ("p:201", 2, 1)],
        {},
        (400, "idle_team", (), (3, 4)),
    ),
    (
        "idle_is_decided_before_ownership",
        "clean",
        [1, 2, 3],
        [("p:201", 1, 2)],  # team 1 does not hold p:201, but team 3 is idle first
        {},
        (400, "idle_team", (), (3,)),
    ),
    (
        "unknown_is_decided_before_idle",
        "clean",
        [1, 2, 3],
        [("p:777", 1, 2)],
        {},
        (400, "unknown_asset", ("p:777",), ()),
    ),
    (
        "float_origin_is_not_an_int",
        "clean",
        [1, 2],
        [("p:101", 1.0, 2), ("p:201", 2, 1)],
        {},
        (400, "invalid_origin", ("p:101",), ()),
    ),
    (
        "string_destination_is_not_an_int",
        "clean",
        [1, 2],
        [("p:101", 1, "2"), ("p:201", 2, 1)],
        {},
        (400, "invalid_destination", ("p:101",), ()),
    ),
    (
        "bool_origin_is_not_an_int",
        "clean",
        [1, 2],
        [("p:101", True, 2), ("p:201", 2, 1)],
        {},
        (400, "invalid_origin", ("p:101",), ()),
    ),
    (
        "missing_origin",
        "clean",
        [1, 2],
        [("p:101", None, 2), ("p:201", 2, 1)],
        {},
        (400, "invalid_origin", ("p:101",), ()),
    ),
    (
        "too_many_assets_before_unknown",
        "clean",
        [1, 2],
        [("p:101", 1, 2), ("p:201", 2, 1), ("p:777", 1, 2)],
        {"max_legs": 2},
        (400, "too_many_assets", (), ()),
    ),
    (
        "send_and_receive_refuses_a_gift",
        "clean",
        [1, 2],
        [("p:101", 1, 2), ("p:102", 1, 2)],
        _SR,
        (400, "one_sided_trade", (), (1, 2)),
    ),
    (
        "send_and_receive_refuses_a_receive_only_third_team",
        "clean",
        [1, 2, 3],
        [("p:101", 1, 3), ("p:201", 2, 1), ("p:102", 1, 2)],
        _SR,
        (400, "one_sided_trade", (), (3,)),
    ),
    ("gift_between_two_any_leg", "clean", [1, 2], [("p:101", 1, 2)], {}, ("ok", ())),
    (
        "gift_to_two_teams_any_leg",
        "clean",
        [1, 2, 3],
        [("p:101", 1, 2), ("p:102", 1, 3)],
        {},
        ("ok", ()),
    ),
    (
        "receive_only_team_among_four_any_leg",
        "clean",
        [1, 2, 3, 4],
        [("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 4), ("p:102", 1, 4)],
        {},
        ("ok", ()),
    ),
    (
        "unknown_slot_pick_is_verified_when_the_inventory_is_published",
        "clean",
        [1, 4],
        [("pick:synth:2027:r1:o1", 1, 4), ("p:402", 4, 1)],
        {},
        ("ok", ()),
    ),
    (
        "unknown_inventory_pick_is_unverifiable",
        "pick_unknown",
        [1, 3],
        [("pick:synth:2027:r1:o3", 3, 1), ("p:101", 1, 3)],
        {},
        ("ok", ("pick:synth:2027:r1:o3",)),
    ),
    (
        "a_pick_nobody_claims_is_unknown",
        "clean",
        [1, 2],
        [("pick:synth:2027:r4:o1", 1, 2), ("p:201", 2, 1)],
        {},
        (400, "unknown_asset", ("pick:synth:2027:r4:o1",), ()),
    ),
]


@pytest.mark.parametrize("case", NAMED_LEDGERS, ids=[c[0] for c in NAMED_LEDGERS])
def test_named_adversarial_ledger(case):
    _name, scenario, teams, raw_legs, policy_kw, expect = case
    _contract, snap = _board(scenario)
    policy = replace(POLICY, **policy_kw)
    legs = [{"id": a, "from": f, "to": t} for a, f, t in raw_legs]
    # Order never decides: the verdict is identical for every ordering of the request.
    for perm_legs in (legs, legs[::-1]):
        for perm_teams in (teams, teams[::-1]):
            if expect[0] == "ok":
                ledger = tl.validate_ledger(snap, teams=perm_teams, legs=perm_legs, policy=policy)
                assert ledger.unverifiable_asset_ids == expect[1]
                continue
            with pytest.raises(tl.LedgerError) as exc:
                tl.validate_ledger(snap, teams=perm_teams, legs=perm_legs, policy=policy)
            e = exc.value
            assert (e.status, e.reason, e.asset_ids, e.roster_ids) == expect
            assert e.error == ("stale_assets" if e.status == 409 else "invalid_trade")


ECHO_NEWLINE_ALIAS = "p:101\n"
ALIASES = [
    "P:101",
    "p:101 ",
    " p:101",
    ECHO_NEWLINE_ALIAS,
    "p:+101",
    "p:\u0661\u0660\u0661",
    "p:101;",
    "p:0101",
    "p:1_01",
    "p:101\u200b",
    "p:",
    "pick:synth:2027:r1:o1 ",
    "PICK:synth:2027:r1:o1",
    "pick:synth:2027:r01:o1",
    "pick:synth:2027:r1:o01",
    "pick:SYNTH:2027:r1:o1",
    "pick:synth:2027:r1:o1:extra",
    "pick:other:2027:r1:o1",
    "2027 Round 1",
    "A Six",
    "",
    None,
    101,
    ["p:101"],
]


@pytest.mark.parametrize("alias", ALIASES, ids=[repr(a) for a in ALIASES])
def test_an_alias_of_a_real_asset_id_is_never_accepted(alias):
    """No spelling other than the canonical id identifies an asset, so an alias
    can neither smuggle a SECOND copy of an asset past the duplicate check nor
    be read as an owner's asset."""
    _contract, snap = _board("clean")
    for legs in (
        [{"id": alias, "from": 1, "to": 2}, {"id": "p:201", "from": 2, "to": 1}],
        # alongside the real asset: a duplicate-by-alias must NOT read as a duplicate
        [
            {"id": "p:101", "from": 1, "to": 2},
            {"id": alias, "from": 1, "to": 2},
            {"id": "p:201", "from": 2, "to": 1},
        ],
    ):
        with pytest.raises(tl.LedgerError) as exc:
            _validate(snap, [1, 2], legs)
        e = exc.value
        assert (e.status, e.error, e.reason) == (400, "invalid_trade", "unknown_asset")
        if alias != ECHO_NEWLINE_ALIAS:  # LANE-E-DEFECT-ECHO-NEWLINE, pinned below
            assert all(re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", a) for a in e.asset_ids)
        assert set(e.asset_ids) <= {str(alias)}  # only what the request supplied, never a real id


# ══ Representation independence, canonical key, re-validation ═════════════


def test_leg_team_representations_canonical_key_and_revalidation():
    """The same trade spelled any accepted way validates to the SAME ledger
    (dict / ``assetId`` dict / tuple / list / ``Leg`` legs; list / tuple / set
    teams), re-validating a validated ledger is a fixed point, and the
    canonical key (the single-flight / receipt identity, spec 2.11) is
    permutation-invariant yet distinguishes every different ledger."""
    rng = random.Random(21)
    keys: dict[str, tuple[Any, ...]] = {}
    for scenario in ("clean", "multi_holder", "stale_rosters", "pick_unknown", "traded_picks"):
        _contract, snap = _board(scenario)
        for _ in range(30):
            teams, legs = gen_ledger(snap, rng)
            ref = _validate(snap, teams, legs)
            shuffled = legs[:]
            rng.shuffle(shuffled)
            spellings = [
                [dict(x) for x in shuffled],
                [{"assetId": x["id"], "from": x["from"], "to": x["to"]} for x in shuffled],
                [(x["id"], x["from"], x["to"]) for x in shuffled],
                [[x["id"], x["from"], x["to"]] for x in shuffled],
                [tl.Leg(x["id"], x["from"], x["to"]) for x in shuffled],
            ]
            for spelled in spellings:
                for team_spelling in (list(reversed(teams)), tuple(teams), set(teams)):
                    got = tl.validate_ledger(snap, teams=team_spelling, legs=spelled, policy=POLICY)
                    assert got == ref
                    assert got.canonical_key() == ref.canonical_key()
            again = tl.validate_ledger(snap, teams=ref.teams, legs=ref.legs, policy=POLICY)
            assert again == ref and again.canonical_key() == ref.canonical_key()
            identity = (scenario, ref.teams, tuple(leg.to_dict().items() for leg in ref.legs))
            assert keys.setdefault(ref.canonical_key(), identity) == identity  # injective
    assert len(keys) >= 100


def test_i8_extra_request_fields_never_change_a_valid_ledger():
    """Ownership claims, verification flags and unverifiable overrides riding on
    a LEG are not read: the ledger, including its unverifiable set, is the same
    as without them - on every board, current or not (I8)."""
    rng = random.Random(81)
    for scenario in ("clean", "multi_holder", "stale_rosters", "unknown_rosters", "pick_unknown"):
        _contract, snap = _board(scenario)
        for _ in range(20):
            teams, legs = gen_ledger(snap, rng)
            claims = [
                {
                    **x,
                    "owner": x["from"],
                    "ownerRosterId": x["from"],
                    "currentOwner": x["from"],
                    "holder": x["from"],
                    "verified": True,
                    "unverifiable": False,
                    "unverifiableAssetIds": [],
                    "rostersState": "current",
                }
                for x in legs
            ]
            assert _validate(snap, teams, claims) == _validate(snap, teams, legs)


# ══ I11 (engine half): fairness ignores every Team Context input ═══════════


def _posture_resolver(label: str | None):
    def resolver(contract, league_key, team, *, build_if_missing):
        if label is None:
            return {"available": False, "unavailableReason": "LABELLED_test"}
        probabilities = {k: 0.1 for k in ("PUSH", "HOLD", "RETOOL", "REBUILD")}
        probabilities[label] = 0.7
        return {
            "available": True,
            "label": label,
            "probabilities": probabilities,
            "confidence": "LOW",
            "paramsVersion": "posture_v1_prior",
            "notes": ["LABELLED synthetic posture (Lane E)"],
            "bundleFreshness": None,
        }

    return resolver


def _constant_utility(ppg: float | None):
    def utility(context, capacity, **_unused):
        if ppg is None:
            return {"available": False, "unavailableReason": "LABELLED_test"}
        return {
            **_labelled_roster_utility(context, capacity),
            "impact": {"ppg": ppg, "standardError": 0.2},
        }

    return utility


def test_i11_fairness_is_invariant_to_posture_utility_and_capacity_inputs(monkeypatch):
    """Spec I11 / privacy M1, engine half: the market fairness a public
    product reduces to does not read posture, projections, roster capacity or
    forced drops.  Sweep every Team Context input - four postures, none, and
    five roster-lens outcomes - and per-team fairness, the overall state and
    the conservation block never move, while the private DECISIONS do (so the
    inputs are live, not ignored by a broken test)."""
    from src.trade import roster_capacity

    rng = random.Random(1112)
    postures = [_posture_resolver(x) for x in ("PUSH", "HOLD", "RETOOL", "REBUILD", None)]
    utilities = [_constant_utility(x) for x in (None, -3.0, 0.0, 3.0)] + [_labelled_roster_utility]
    decision_vectors: set[tuple[str, ...]] = set()
    for scenario in ("clean", "over_cap", "traded_picks"):
        _contract, snap = _board(scenario)
        for _ in range(4):
            ledger = _validate(snap, *gen_ledger(snap, rng))
            ref = svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
            want = _canon(
                (
                    {r: ref["teams"][r]["fairness"] for r in ledger.teams},
                    ref["summary"]["fairnessOverall"],
                    ref["summary"]["conservation"],
                )
            )
            for posture in postures:
                for utility in utilities:
                    monkeypatch.setattr(roster_capacity, "evaluate_final_roster_utility", utility)
                    out = svc.analyze_trade_n(
                        snap,
                        ledger,
                        mode="team_context",
                        counterfactuals=False,
                        posture_resolver=posture,
                    )
                    got = _canon(
                        (
                            {r: out["teams"][r]["fairness"] for r in ledger.teams},
                            out["summary"]["fairnessOverall"],
                            out["summary"]["conservation"],
                        )
                    )
                    assert got == want, (scenario, ledger.legs)
                    decision_vectors.add(
                        tuple(
                            out["teams"][r]["analysis"]["decision"]["headline"]
                            for r in ledger.teams
                        )
                    )
    assert len(decision_vectors) > 3  # the Team Context inputs really do move decisions


# ══ Summary: a projection, never a second verdict (spec 2.9, R14a) ═════════

_SUMMARY_KEYS = {
    "teamCount",
    "legCount",
    "perTeam",
    "lines",
    "fairnessOverall",
    "conservation",
    "nonConservedNote",
}
_NO_TRADE_LEVEL_VERDICT = (
    "overallRecommendation",
    "recommendation",
    "winner",
    "loser",
    "headline",
    "verdict",
    "category",
    "netGap",
    "totalGap",
    "gap",
)


def test_summary_is_a_projection_with_no_trade_level_verdict_or_adjusted_sum():
    from src.trade import team_verdicts

    checked = 0
    for scenario, _contract, snap, teams, legs in _cases(88, 4):
        ledger = _validate(snap, teams, legs)
        for mode in svc.MODES:
            out = _run(snap, ledger, mode)
            s = out["summary"]
            ctx = (scenario, mode, legs)
            assert set(s) == _SUMMARY_KEYS, ctx
            assert set(s["conservation"]) == {
                "assetsSent",
                "assetsReceived",
                "pricedRawSent",
                "pricedRawReceived",
                "balanced",
            }, ctx  # RAW conserved quantities only: no adjusted gap, VA or utility
            assert set(s["fairnessOverall"]) == {"state", "reasonCode"}, ctx
            assert not set(_NO_TRADE_LEVEL_VERDICT) & (set(out) | set(s)), ctx
            assert s["nonConservedNote"] == team_verdicts.NON_CONSERVED_NOTE, ctx
            assert [p["rosterId"] for p in s["perTeam"]] == list(ledger.teams), ctx
            for p, line in zip(s["perTeam"], s["lines"]):
                team = out["teams"][p["rosterId"]]
                assert set(p) == {"rosterId", "teamName", "headline", "category", "fairness"}, ctx
                assert p["headline"] == team["analysis"]["decision"]["headline"], ctx
                assert p["category"] == team["category"], ctx
                assert p["fairness"] == team["fairness"]["state"], ctx
                assert line == f"{p['teamName']}: {team['categoryText']}.", ctx
            checked += 1
    assert checked >= 120


# ══ I19 at N >= 3: the floor is a per-team property ═══════════════════════


def test_i19_gifts_from_several_teams_follow_the_floor_per_team():
    """Several teams gift small assets to one team (N = 3 and 4).  Each team's
    state is decided by the owners' math over ITS OWN legs, the receiver by the
    sum of what it was given, and below the 250-point floor everything is FAIR
    - private behaviour that the public product avoids with
    ``send_and_receive`` (which refuses these ledgers outright)."""
    rng = random.Random(1919)
    floor = fairness_bands.receipt()["absoluteMinimum"]
    saw_fair = saw_not_fair = False
    for _ in range(60):
        n = rng.randint(3, 4)
        givers = {1: "104", 3: "304", 4: "404"}
        gifts = dict(list(givers.items())[: n - 1])
        values = {
            pid: float(rng.choice([rng.randint(20, 120), rng.randint(120, 600)]))
            for pid in gifts.values()
        }
        contract = _league("clean")
        for r in contract["playersArray"]:
            if r.get("playerId") in values:
                r["rankDerivedValue"] = values[r["playerId"]]
                r["values"] = {"full": values[r["playerId"]]}
        snap = _snapshot(contract, "clean")
        teams = sorted([2, *gifts])
        legs = [{"id": f"p:{pid}", "from": rid, "to": 2} for rid, pid in gifts.items()]
        with pytest.raises(tl.LedgerError) as exc:
            _validate(snap, teams, legs, replace(POLICY, **_SR))
        assert exc.value.reason == "one_sided_trade"
        for mode in ("market_fairness", "asset_only"):
            out = _run(snap, _validate(snap, teams, legs), mode)
            for rid in teams:
                f = out["teams"][rid]["fairness"]
                m = _owner_math(contract, rid, legs)
                assert f["gap"] == m["gap"], (values, rid)
                expected = "FAIR" if abs(m["gap"]) < floor else "NOT_FAIR"
                assert f["state"] == expected, (values, rid, f)
                saw_fair |= expected == "FAIR"
                saw_not_fair |= expected == "NOT_FAIR"
    assert saw_fair and saw_not_fair


# ══ Named adversarial analyses: withheld values, gifts, nothing priced ═════


def _clean_with(mutate) -> tuple[dict[str, Any], tl.TradeSnapshot]:
    contract = _league("clean")
    mutate(contract)
    return contract, _snapshot(contract, "clean")


def _pick_row(contract: dict[str, Any], name: str) -> dict[str, Any]:
    return next(r for r in contract["playersArray"] if r.get("canonicalName") == name)


@pytest.mark.parametrize("flag", ["quarantined", "stale"])
@pytest.mark.parametrize("mode", svc.MODES)
def test_a_quarantined_or_stale_pick_is_withheld_on_both_sides(flag, mode):
    """The withholding applies to PICKS as it does to players: the pick row's
    value is ``None`` with the same state in the sender's and the receiver's
    view, both teams are UNABLE ``evaluation_unavailable``, and the withheld
    asset is excluded from the raw totals (never counted as zero)."""

    def mutate(contract):
        for name in ("2027 Round 1", "2026 Pick 1.03"):
            row = _pick_row(contract, name)
            if flag == "quarantined":
                row.update(quarantined=True, anomalyFlags=["no_valid_source_values"])
            else:
                row["confidenceAxes"] = {"freshness": "low"}

    _contract, snap = _clean_with(mutate)
    legs = [
        {"id": f"pick:{KEY}:2027:r1:o1", "from": 1, "to": 2},
        {"id": f"pick:{KEY}:{CURRENT_YEAR}:r1:o2", "from": 2, "to": 1},
        {"id": "p:301", "from": 3, "to": 1},
        {"id": "p:102", "from": 1, "to": 3},
    ]
    out = _run(snap, _validate(snap, [1, 2, 3], legs), mode)
    _reconciles(out, _validate(snap, [1, 2, 3], legs))
    for rid in (1, 2):
        team = out["teams"][rid]
        for row in (*team["gives"], *team["receives"]):
            if row["kind"] == "pick":
                assert (row["value"], row["valueState"]) == (None, flag), (rid, row)
            else:  # the players beside the withheld picks keep their own price
                assert row["valueState"] == "priced" and row["value"] > 0, (rid, row)
        assert team["fairness"]["state"] == "UNABLE"
        assert team["fairness"]["reasonCode"] == "evaluation_unavailable"
        codes = [g["code"] for g in team["analysis"]["decision"]["missingEvidence"]]
        assert f"{flag}_values" in codes
    # Team 3 only touches priced players (3000 for 2500): judged on its own legs (I10).
    assert out["teams"][3]["fairness"]["state"] in ("FAIR", "NOT_FAIR")
    assert out["summary"]["fairnessOverall"]["state"] in ("NOT_FAIR", "UNABLE")
    # Raw conservation counts only the assets priced in BOTH views: the two players.
    cons = out["summary"]["conservation"]
    assert cons["pricedRawSent"] == cons["pricedRawReceived"] == 2500 + 3000


@pytest.mark.parametrize("mode", svc.MODES)
def test_a_gift_of_an_unpriced_player_is_unable_never_a_free_gift(mode):
    """Team 1 'gifts' p:105 (on the roster, on the board, NO price).  MISSING
    IS NEVER ZERO: neither team is judged on a 0-value asset, the value is
    ``None`` in both views, and the raw totals do not pretend to know it."""
    _contract, snap = _board("clean")
    ledger = _validate(snap, [1, 2], [{"id": "p:105", "from": 1, "to": 2}])
    out = _run(snap, ledger, mode)
    for rid in (1, 2):
        team = out["teams"][rid]
        row = (team["gives"] or team["receives"])[0]
        assert (row["value"], row["valueState"]) == (None, "unpriced")
        assert (team["fairness"]["state"], team["fairness"]["reasonCode"]) == (
            "UNABLE",
            "asset_not_evaluable",
        )
        assert team["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
        assert team["category"] == "UNAVAILABLE"
    cons = out["summary"]["conservation"]
    assert (cons["pricedRawSent"], cons["pricedRawReceived"]) == (0, 0)
    assert cons["balanced"] is True  # one leg, counted once each way
    assert out["summary"]["fairnessOverall"] == {
        "state": "UNABLE",
        "reasonCode": "evidence_insufficient",
    }


@pytest.mark.parametrize("mode", svc.MODES)
def test_a_trade_with_nothing_priced_has_no_evaluable_team(mode):
    """An off-board ghost and an unpriced player, routed to two teams: no team
    has a single priced asset, so no team is evaluable and the market lens
    itself says so (``no_priced_assets``)."""
    _contract, snap = _board("off_board")
    legs = [{"id": "p:106", "from": 1, "to": 2}, {"id": "p:105", "from": 1, "to": 3}]
    out = _run(snap, _validate(snap, [1, 2, 3], legs), mode)
    for team in out["teams"].values():
        assert team["fairness"]["state"] == "UNABLE"
        assert team["fairness"]["reasonCode"] == "asset_not_evaluable"
        assert team["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
    codes = [g["code"] for g in out["teams"][1]["analysis"]["decision"]["missingEvidence"]]
    assert "no_priced_assets" in codes
    assert out["summary"]["conservation"]["pricedRawSent"] == 0


@pytest.mark.parametrize("mode", svc.MODES)
def test_a_team_the_ledger_does_not_list_is_never_analysed_or_touched(mode):
    """Two of the league's four teams trade; the other two are not in the
    result, the summary, or any asset set - and their rosters stay as they were."""
    _contract, snap = _board("clean")
    frozen = copy.deepcopy(snap.teams_by_roster_id[3]), copy.deepcopy(snap.teams_by_roster_id[4])
    legs = [{"id": "p:101", "from": 1, "to": 2}, {"id": "p:201", "from": 2, "to": 1}]
    ledger = _validate(snap, [1, 2], legs)
    out = _run(snap, ledger, mode)
    assert list(out["teams"]) == [1, 2]
    assert [p["rosterId"] for p in out["summary"]["perTeam"]] == [1, 2]
    blob = _canon(out)
    for other in (
        "p:301",
        "p:302",
        "p:401",
        "p:402",
        f"pick:{KEY}:2027:r1:o3",
        f"pick:{KEY}:2027:r1:o4",
        "Team C",
        "Team D",
        "owner3",
        "owner4",
    ):
        assert other not in blob, other
    assert (snap.teams_by_roster_id[3], snap.teams_by_roster_id[4]) == frozen


# ══ Defects found by this lane (strict xfails; fix -> remove the marker) ═══


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-ECHO-NEWLINE: trade_ledger._ECHO_RE ends in '$', which in "
        "Python also matches just BEFORE a trailing newline, so an unknown asset id "
        "'p:101\\n' is echoed back in LedgerError.asset_ids (spec 2.3: an echo "
        "carries only ids of the safe shape [A-Za-z0-9:_-]{1,64}); the public "
        "advisor's own _ECHO_RE has the same anchor"
    ),
)
def test_lane_e_defect_error_echo_rejects_a_trailing_newline():
    """Minimal repro.  Synthetic league.  Legs ``[("p:101\\n", 1, 2),
    ("p:201", 2, 1)]`` -> 400 ``unknown_asset`` (correct).  Expected
    ``asset_ids == ()`` - the id is not of the echo shape.  Actual
    ``('p:101\\n',)``: ``re.match(r"^[A-Za-z0-9:_-]{1,64}$", "p:101\\n")`` matches.
    Fix: ``\\Z`` (or ``re.fullmatch``) instead of ``$``."""
    _contract, snap = _board("clean")
    legs = [{"id": ECHO_NEWLINE_ALIAS, "from": 1, "to": 2}, {"id": "p:201", "from": 2, "to": 1}]
    with pytest.raises(tl.LedgerError) as exc:
        _validate(snap, [1, 2], legs)
    assert exc.value.reason == "unknown_asset"
    assert exc.value.asset_ids == ()
    assert "assetIds" not in exc.value.to_dict()


def _relabelled_pick(contract: dict[str, Any], asset_id: str, label: str) -> dict[str, Any]:
    c = copy.deepcopy(contract)
    for t in c["sleeper"]["teams"]:
        for d in t.get("pickDetails") or []:
            if d["assetId"] == asset_id:
                d["label"] = label
        if t.get("pickDetails"):
            t["picks"] = [d["label"] for d in t["pickDetails"]]
    return c


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-I9-PICKLABEL: when a pick's identity-resolved board row is "
        "unpriced, trade_simulator.resolve_pick_board_row falls back to its display "
        "LABEL; a label that names ANOTHER grade prices the pick at that grade's "
        "value (spec 2.5: labels are display only; I9 / I13 / R14d: an unpriced "
        "pick is UNABLE, never priced from a label)"
    ),
)
@pytest.mark.parametrize("mode", ["market_fairness", "asset_only"])
def test_lane_e_defect_i9_pick_label_prices_an_unpriced_pick(mode):
    """Minimal repro.  Synthetic league whose ``2027 Round 2`` board row is
    unpriced (``pickValueProvenance.state == "unavailable"``).  Team 3 sends
    ``p:305`` (1800) to team 4 for ``pick:synth:2027:r2:o4`` (a ROUND-2 pick).
    Baseline (label ``2027 Round 2``): both teams UNABLE
    ``asset_not_evaluable``, the pick ``off_board`` with ``value: None``.
    Only team 4's DISPLAY label for that pick is changed to ``2027 Round 1``:
    expected, no verdict moves (I9); actual, the pick is ``priced`` at 3600
    (the ROUND-1 grade), team 3 reads STRONGLY_FAVORABLE and team 4
    STRONGLY_UNFAVORABLE, both fairness NOT_FAIR."""
    contract, snap = _board("pick_unpriced")
    aid = f"pick:{KEY}:2027:r2:o4"
    legs = [{"id": "p:305", "from": 3, "to": 4}, {"id": aid, "from": 4, "to": 3}]
    base = _run(snap, _validate(snap, [3, 4], legs), mode)
    relabelled = _snapshot(_relabelled_pick(contract, aid, "2027 Round 1"), "pick_unpriced")
    other = _run(relabelled, _validate(relabelled, [3, 4], legs), mode)
    for rid in (3, 4):
        assert _verdict(base["teams"][rid]) == _verdict(other["teams"][rid])


def _with_duplicate_name(contract: dict[str, Any], renamed: str, like: str) -> dict[str, Any]:
    """The contract with player ``renamed`` given player ``like``'s display name."""
    c = copy.deepcopy(contract)
    rows = {r["playerId"]: r for r in c["playersArray"] if r.get("playerId")}
    rows[renamed]["displayName"] = rows[renamed]["canonicalName"] = rows[like]["displayName"]
    for t in c["sleeper"]["teams"]:
        t["players"] = [
            rows[str(pid)]["displayName"] if str(pid) in rows else nm
            for pid, nm in zip(t["playerIds"], t["players"])
        ]
    return c


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-I9-DUPNAME: roster_capacity builds the cut ladder from "
        "src/draft/context.py::build_roster_assets, which joins each roster entry "
        "to the board by NAME before id, so two players sharing a display name get "
        "one board row / player_id between them; the ladder keys on player_id, so "
        "the forced-cut set changes (or the ladder 'exhausts') with the names alone "
        "(spec I9 / 2.4: identity is the assetId; B0-b: names are the fallback only)"
    ),
)
@pytest.mark.parametrize(
    "renamed, like",
    [("104", "105"), ("104", "304")],
    ids=["two_players_on_one_roster", "same_name_as_another_teams_player"],
)
def test_lane_e_defect_i9_duplicate_display_names_change_the_forced_cut(renamed, like):
    """Minimal repro.  Synthetic league, roster limit 5 (``over_cap``); team 1
    holds exactly 5 (101-105).  Team 2 gifts ``p:201`` to team 1, so team 1 is
    at 6 of 5 and must release exactly one player.  Baseline: the forced cut is
    ``104`` ("A Depth"), the ladder is not exhausted.  Only the DISPLAY NAME of
    ``renamed`` is changed to ``like``'s.  Expected: the same forced cut.
    Actual: ``("104", "105")`` -> ``forcedDrops == []`` with ``ladderExhausted``
    ("cut ladder offers 0 release(s) but 1 are needed"), and in ``team_context``
    team 1 flips from YES / FAVORABLE to NO / UNFAVORABLE ``executionGate``
    ("roster can't fit this trade"); ``("104", "304")`` -> the cut becomes
    ``105`` (the entry takes team 3's player's row)."""
    contract, snap = _board("over_cap")
    renamed_snap = _snapshot(_with_duplicate_name(contract, renamed, like), "over_cap")
    legs = [{"id": "p:201", "from": 2, "to": 1}]
    a = _run(snap, _validate(snap, [1, 2], legs), "asset_only")
    b = _run(renamed_snap, _validate(renamed_snap, [1, 2], legs), "asset_only")
    assert _capacity_view(a["teams"][1]) == _capacity_view(b["teams"][1])


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LANE-E-DEFECT-I9-DUPNAME (verdict level): two of a team's own players sharing "
        "a display name turn a legal over-the-cap trade into 'roster can't fit' "
        "(NO / executionGate) in team_context - same root cause as above"
    ),
)
def test_lane_e_defect_i9_duplicate_display_names_flip_a_team_context_decision(monkeypatch):
    """Same repro as the capacity test, read at the decision.  The roster lens
    is pinned to a constant (+0.9 ppg) so it cannot depend on names.  Baseline
    team 1: YES / FAVORABLE (one cut, charged and fit).  After renaming player
    104 to player 105's display name: NO, deciding ``executionGate``,
    UNFAVORABLE - ``roster_limit`` - although nothing but a label changed."""
    from src.trade import roster_capacity

    monkeypatch.setattr(roster_capacity, "evaluate_final_roster_utility", _constant_utility(0.9))
    contract, snap = _board("over_cap")
    renamed = _snapshot(_with_duplicate_name(contract, "104", "105"), "over_cap")
    legs = [{"id": "p:201", "from": 2, "to": 1}]
    a = _run(snap, _validate(snap, [1, 2], legs), "team_context")
    b = _run(renamed, _validate(renamed, [1, 2], legs), "team_context")
    assert _verdict(a["teams"][1]) == _verdict(b["teams"][1])
