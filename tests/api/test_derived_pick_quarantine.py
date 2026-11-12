"""Derived and tethered pick values are judged by their basis, not by an empty
source map (2026-11-12, "2029 Mid 5th (received, quarantined)").

The defect.  ``_validate_and_quarantine_rows`` Check 5 flags any row with a
positive value and no positive ``canonicalSiteValues`` entry as
``no_valid_source_values``, a quarantine-level flag.  Every pick the C1-U6
completion pass prices by an APPROVED derivation (``derived_round_step``,
``derived_uniform_tier_ev``, ``derived_year_step``) or by the rookie tether
(``rookie_pool_tether``) has no per-source values of its own BY CONSTRUCTION:
its number is computed from named basis rows.  So Check 5 quarantined all of
them -- measured on the 2026-11-12 board: 35 of 138 pick rows, every 2028/2029
round-5/6 tier pick, every 2028/2029 generic "Round N" row, and 2027 slots
6.02-6.12 (6.01 escaped only because an unrelated rookie-board key sat in its
map).  The trade decision then withheld every trade touching one of them
(``quarantined_values``), contradicting TC-19 / TC-21 (every active pick
through 2029 has a usable canonical value; generic future picks use a
documented method with uncertainty) and the C1-U6 product contract §1.

The rule now.  A pick whose provenance names such a class is evidence-backed
exactly when every basis row resolves to ONE row that is itself
evidence-backed (recursively) and carries no quarantine-level flag.  A missing,
ambiguous, cyclic, valueless or quarantined basis keeps the quarantine.
Players, vendor-priced (``direct_market_blend``) picks and picks with no
provenance are judged exactly as before.  Uncertainty is not hidden: these rows
stay ``confidenceBucket: "low"`` with their PRIOR provenance, and the trade
decision reports them as low-confidence assets.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from src.api.data_contract import _QUARANTINE_FLAGS, _validate_and_quarantine_rows
from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from tests.archive_fixtures import newest_complete_contract
from tests.trade import multi_team_support as mts

DERIVED_CLASSES = (
    "rookie_pool_tether",
    "derived_year_step",
    "derived_round_step",
    "derived_uniform_tier_ev",
)


# ── Unit: the rule on hand-built rows ────────────────────────────────────


def _pick(name: str, value: float, *, sites=None, prov=None, flags=None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "canonicalName": name,
        "displayName": name,
        "position": "PICK",
        "assetClass": "pick",
        "rankDerivedValue": value,
        "canonicalSiteValues": sites if sites is not None else {"ktc": None, "idpTradeCalc": None},
        "anomalyFlags": list(flags or []),
        "confidenceBucket": "low",
    }
    if prov is not None:
        row["pickValueProvenance"] = prov
    return row


def _market_tier(name: str, value: float, **kw) -> dict[str, Any]:
    return _pick(
        name,
        value,
        sites={"ktc": value, "idpTradeCalc": value - 100},
        prov={"class": "direct_market_blend"},
        **kw,
    )


def _round_step(name: str, value: float, basis: str) -> dict[str, Any]:
    return _pick(
        name,
        value,
        prov={
            "class": "derived_round_step",
            "family": "canonical_rookie_ladder_round_step_v1",
            "classification": "PRIOR",
            "basis": basis,
            "factor": 0.929,
        },
    )


def _player(name: str, value: float, sites: dict, *, pos: str = "TE") -> dict[str, Any]:
    return {
        "canonicalName": name,
        "displayName": name,
        "position": pos,
        "assetClass": "player",
        "rankDerivedValue": value,
        "canonicalSiteValues": sites,
        "anomalyFlags": [],
        "confidenceBucket": "medium",
    }


def _run(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _validate_and_quarantine_rows(rows)
    return {r["canonicalName"]: r for r in rows}


def test_a_round_step_pick_on_a_source_backed_basis_is_not_quarantined():
    """The reported asset: 2029 Mid 5th = 2029 Mid 4th x 0.929."""
    out = _run(
        [_market_tier("2029 Mid 4th", 1583), _round_step("2029 Mid 5th", 1471, "2029 Mid 4th")]
    )
    assert out["2029 Mid 5th"]["quarantined"] is False
    assert "no_valid_source_values" not in out["2029 Mid 5th"]["anomalyFlags"]
    # The derivation's uncertainty is not hidden by the fix.
    assert out["2029 Mid 5th"]["confidenceBucket"] == "low"


def test_a_chained_derivation_is_judged_through_the_whole_chain():
    """2029 Mid 6th is derived from Mid 5th, itself derived from Mid 4th."""
    out = _run(
        [
            _market_tier("2029 Mid 4th", 1583),
            _round_step("2029 Mid 5th", 1471, "2029 Mid 4th"),
            _round_step("2029 Mid 6th", 1347, "2029 Mid 5th"),
        ]
    )
    assert out["2029 Mid 6th"]["quarantined"] is False


def test_a_generic_round_row_over_three_source_backed_tiers_is_not_quarantined():
    tiers = [
        _market_tier(f"2029 {t} 1st", v)
        for t, v in (("Early", 4489), ("Mid", 4155), ("Late", 3749))
    ]
    generic = _pick(
        "2029 Round 1",
        4131,
        prov={
            "class": "derived_uniform_tier_ev",
            "family": "uniform_tier_ev_v1",
            "classification": "PRIOR",
            "basis": ["2029 Early 1st", "2029 Mid 1st", "2029 Late 1st"],
        },
    )
    out = _run([*tiers, generic])
    assert out["2029 Round 1"]["quarantined"] is False


def test_a_tethered_slot_pick_follows_its_rookie():
    rookie = _player("Marlin Klein", 1780, {"ktc": 1700, "dlfRookieSf": 995000})
    slot = _pick(
        "2027 Pick 6.02", 1780, prov={"class": "rookie_pool_tether", "basis": "Marlin Klein"}
    )
    out = _run([rookie, slot])
    assert out["2027 Pick 6.02"]["quarantined"] is False


@pytest.mark.parametrize(
    "basis_flag",
    [
        "blend_integrity_violation",
        "duplicate_canonical_identity",
        "unsupported_position",
        "position_source_contradiction",
    ],
)
def test_a_quarantined_basis_keeps_the_derived_pick_quarantined(basis_flag):
    """A derived number inherits the trust of what it was computed from."""
    rows = [
        _market_tier("2029 Mid 4th", 1583, flags=[basis_flag]),
        _round_step("2029 Mid 5th", 1471, "2029 Mid 4th"),
        _round_step("2029 Mid 6th", 1347, "2029 Mid 5th"),
    ]
    out = _run(rows)
    assert out["2029 Mid 4th"]["quarantined"] is True
    for name in ("2029 Mid 5th", "2029 Mid 6th"):
        assert out[name]["quarantined"] is True, name
        assert "no_valid_source_values" in out[name]["anomalyFlags"], name


def test_a_basis_flagged_by_the_identity_pass_in_the_same_call_keeps_the_quarantine():
    """Ordering pin: the identity pass flags the basis inside this same
    validator call, before Check 5 reads it.  An offensive lineman is not a
    supported board position."""
    rookie = _player("Line Man", 1780, {"ktc": 1700}, pos="OL")
    slot = _pick("2027 Pick 6.02", 1780, prov={"class": "rookie_pool_tether", "basis": "Line Man"})
    rows = [rookie, slot]
    _validate_and_quarantine_rows(rows)
    assert "unsupported_position" in rows[0]["anomalyFlags"]
    assert rows[0]["quarantined"] is True
    assert rows[1]["quarantined"] is True


def test_a_tethered_pick_on_a_rookie_with_no_evidence_stays_quarantined():
    rookie = _player("Hollow Rookie", 900, {"ktc": None, "dlfRookieSf": 0})
    slot = _pick(
        "2027 Pick 6.09", 900, prov={"class": "rookie_pool_tether", "basis": "Hollow Rookie"}
    )
    rows = [rookie, slot]
    _validate_and_quarantine_rows(rows)
    assert rows[0]["quarantined"] is True
    assert rows[1]["quarantined"] is True


def test_a_basis_of_the_wrong_kind_is_not_the_basis():
    """A player row that happens to carry a pick's name cannot back a
    derivation, and a pick row cannot back the rookie tether."""
    impostor = _player("2029 Mid 4th", 1583, {"ktc": 1500})
    derived = _round_step("2029 Mid 5th", 1471, "2029 Mid 4th")
    pick_named_rookie = _market_tier("Marlin Klein", 1780)
    tethered = _pick(
        "2027 Pick 6.02", 1780, prov={"class": "rookie_pool_tether", "basis": "Marlin Klein"}
    )
    out = _run([impostor, derived, pick_named_rookie, tethered])
    assert out["2029 Mid 5th"]["quarantined"] is True
    assert out["2027 Pick 6.02"]["quarantined"] is True


def test_a_basis_with_no_evidence_keeps_the_chain_quarantined():
    """Mid 4th has a value but no source values at all: nothing downstream is
    evidence-backed."""
    hollow = _pick("2029 Mid 4th", 1583, prov={"class": "direct_market_blend"})
    out = _run([hollow, _round_step("2029 Mid 5th", 1471, "2029 Mid 4th")])
    assert out["2029 Mid 4th"]["quarantined"] is True
    assert out["2029 Mid 5th"]["quarantined"] is True


@pytest.mark.parametrize(
    "basis",
    [None, "", "2029 Nonexistent 4th", ["2029 Mid 4th", "2029 Nowhere 4th"], []],
)
def test_a_missing_or_unresolvable_basis_keeps_the_quarantine(basis):
    rows = [_market_tier("2029 Mid 4th", 1583), _round_step("2029 Mid 5th", 1471, "x")]
    rows[1]["pickValueProvenance"]["basis"] = basis
    out = _run(rows)
    assert out["2029 Mid 5th"]["quarantined"] is True


def test_an_ambiguous_basis_name_keeps_the_quarantine():
    """Two rows answer to the basis name: which one priced the pick is unknown."""
    rows = [
        _player("Marlin Klein", 1780, {"ktc": 1700}),
        _player("Marlin Klein", 300, {"idpTradeCalc": 300}, pos="LB"),
        _pick(
            "2027 Pick 6.02", 1780, prov={"class": "rookie_pool_tether", "basis": "Marlin Klein"}
        ),
    ]
    _validate_and_quarantine_rows(rows)
    assert rows[2]["quarantined"] is True


def test_a_basis_cycle_is_refused_not_looped():
    rows = [
        _round_step("2029 Mid 5th", 1471, "2029 Mid 6th"),
        _round_step("2029 Mid 6th", 1347, "2029 Mid 5th"),
    ]
    out = _run(rows)
    assert out["2029 Mid 5th"]["quarantined"] is True
    assert out["2029 Mid 6th"]["quarantined"] is True


def test_a_basis_without_a_positive_value_keeps_the_quarantine():
    rows = [
        _market_tier("2029 Mid 4th", 1583),
        _round_step("2029 Mid 5th", 1471, "2029 Mid 4th"),
    ]
    rows[0]["rankDerivedValue"] = None
    out = _run(rows)
    assert out["2029 Mid 5th"]["quarantined"] is True


def test_players_and_vendor_priced_picks_are_judged_exactly_as_before():
    """The basis rule reaches only the four derived/tether classes."""
    hollow_player = _player("Fringe Rookie", 412, {"ktc": None, "dlfRookieSf": 0})
    hollow_market_pick = _pick("2028 Mid 2nd", 3022, prov={"class": "direct_market_blend"})
    no_provenance_pick = _pick("2028 Mid 3rd", 2210)
    out = _run([hollow_player, hollow_market_pick, no_provenance_pick])
    for name in ("Fringe Rookie", "2028 Mid 2nd", "2028 Mid 3rd"):
        assert out[name]["quarantined"] is True, name
        assert "no_valid_source_values" in out[name]["anomalyFlags"], name


def test_a_small_positive_derived_value_is_a_value_not_a_zero():
    """Rounding boundary: a value of 1 is positive; 0 and None are not values
    and are never quarantined as 'derived' (Check 5 needs a positive value)."""
    rows = [
        _market_tier("2029 Late 4th", 2),
        _round_step("2029 Late 5th", 1, "2029 Late 4th"),
        _round_step("2029 Late 6th", 0, "2029 Late 5th"),
    ]
    out = _run(rows)
    assert out["2029 Late 5th"]["quarantined"] is False
    assert out["2029 Late 6th"]["quarantined"] is False
    assert "no_valid_source_values" not in out["2029 Late 6th"]["anomalyFlags"]


def test_check_five_is_recomputed_not_sticky():
    """The validator owns the flag: a stale flag from an earlier pass on a row
    that is now evidence-backed is dropped, and re-running is a fixed point."""
    rows = [_market_tier("2029 Mid 4th", 1583), _round_step("2029 Mid 5th", 1471, "2029 Mid 4th")]
    rows[1]["anomalyFlags"] = ["no_valid_source_values"]
    _validate_and_quarantine_rows(rows)
    first = copy.deepcopy(rows)
    _validate_and_quarantine_rows(rows)
    assert rows == first
    assert rows[1]["quarantined"] is False


# ── Real board: the whole pipeline (build_api_data_contract) ───────────────


def _board() -> dict[str, Any]:
    contract, _name = newest_complete_contract()
    if contract is None:
        pytest.skip("no complete archived scrape available")
    return contract


def _by_name(contract: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in contract["playersArray"]:
        out.setdefault(str(r.get("canonicalName") or ""), []).append(r)
    return out


def _basis_names(row: dict[str, Any]) -> list[str]:
    basis = (row.get("pickValueProvenance") or {}).get("basis")
    return [str(b) for b in (basis if isinstance(basis, list) else [basis]) if b]


def test_no_derived_pick_on_the_real_board_is_quarantined_while_its_basis_is_clean():
    """The census the incident needed: on the real board, a derived or
    tethered pick is quarantined only when some row in its basis chain is."""
    contract = _board()
    by_name = _by_name(contract)

    def chain_clean(name: str, seen: frozenset[str] = frozenset()) -> bool:
        rows = by_name.get(name) or []
        if len(rows) != 1 or name in seen:
            return False
        row = rows[0]
        if row.get("quarantined"):
            return False
        prov = row.get("pickValueProvenance") or {}
        if row.get("assetClass") == "pick" and prov.get("class") in DERIVED_CLASSES:
            return all(chain_clean(b, seen | {name}) for b in _basis_names(row))
        return True

    derived = [
        r
        for r in contract["playersArray"]
        if r.get("assetClass") == "pick"
        and (r.get("pickValueProvenance") or {}).get("class") in DERIVED_CLASSES
        and (r.get("rankDerivedValue") or 0) > 0
    ]
    assert derived, "the board carries derived/tethered picks"
    wrong = [
        r["canonicalName"]
        for r in derived
        if r.get("quarantined") and all(chain_clean(b) for b in _basis_names(r)) and _basis_names(r)
    ]
    assert wrong == [], f"derived picks quarantined on a clean basis: {wrong}"
    # Their uncertainty is still stamped: low confidence, a named derivation.
    for r in derived:
        if (r.get("pickValueProvenance") or {}).get("class") != "rookie_pool_tether":
            assert r.get("confidenceBucket") == "low", r["canonicalName"]


@pytest.mark.parametrize("year", [2028, 2029])
def test_the_reported_picks_are_priced_by_their_round_step_and_usable(year):
    """Hand oracle: value(R) = value(R-1) x roundStep(R), per tier, from the
    served config; and the rows are no longer quarantined."""
    from src.api.data_contract import _load_pick_year_discount

    contract = _board()
    by_name = {n: rs[0] for n, rs in _by_name(contract).items() if len(rs) == 1}
    if f"{year} Mid 5th" not in by_name:
        pytest.skip(f"the archived board does not carry {year} round 5")
    # The steps the build itself read (``derivedRoundModel.stepByRound``).
    steps = _load_pick_year_discount()["roundStepByRound"]
    for tier in ("Early", "Mid", "Late"):
        r4 = by_name[f"{year} {tier} 4th"]["rankDerivedValue"]
        r5 = by_name[f"{year} {tier} 5th"]
        r6 = by_name[f"{year} {tier} 6th"]
        assert abs(r5["rankDerivedValue"] - r4 * float(steps["5"])) <= 1.0, (tier, r4, r5)
        assert abs(r6["rankDerivedValue"] - r4 * float(steps["5"]) * float(steps["6"])) <= 1.5
        for row in (r5, r6):
            assert row["quarantined"] is False, row["canonicalName"]
            assert not set(row.get("anomalyFlags") or ()) & _QUARANTINE_FLAGS
            assert row["pickValueProvenance"]["class"] == "derived_round_step"
            assert row["pickValueProvenance"]["classification"] == "PRIOR"


def test_the_board_quarantines_no_player_differently():
    """Scope pin: every non-pick row with a positive value and no positive
    source value is still flagged (the rule was not widened to players)."""
    contract = _board()
    for r in contract["playersArray"]:
        if r.get("assetClass") == "pick":
            continue
        sites = r.get("canonicalSiteValues") or {}
        hollow = not any(
            isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
            for v in sites.values()
        )
        if hollow and (r.get("rankDerivedValue") or 0) > 0:
            assert "no_valid_source_values" in (r.get("anomalyFlags") or []), r["canonicalName"]
            assert r["quarantined"] is True, r["canonicalName"]


# ── Real board: the trade the report showed ────────────────────────────────


@pytest.fixture
def _pinned_scarcity(monkeypatch):
    return mts.pin_league_scarcity(monkeypatch)


def _no_posture(*_a, **_k):
    return None


def _analyze(snap, teams, legs, mode):
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
    kw = {"posture_resolver": _no_posture} if mode != "market_fairness" else {}
    return svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False, **kw)


def _future_pick(snap, rid: int, season: int, rnd: int) -> str | None:
    want = f":{season}:r{rnd}:"
    for aid in mts.team_assets(snap, rid):
        if aid.startswith("pick:") and want in aid:
            return aid
    return None


def _first_player(snap, contract, rid: int) -> str | None:
    rows = {str(r.get("playerId")): r for r in contract["playersArray"] if r.get("playerId")}
    best = None
    for aid in mts.team_assets(snap, rid):
        if not aid.startswith("p:"):
            continue
        r = rows.get(aid[2:]) or {}
        v = r.get("rankDerivedValue") or 0
        if v > 0 and not r.get("quarantined") and (best is None or v > best[0]):
            best = (v, aid)
    return best[1] if best else None


def _reported_shape(snap, contract):
    """Side B sends its own late-round future picks to Side A; Side A and
    Side C trade players around the circle (the reported three-team shape)."""
    rids = sorted(snap.teams_by_roster_id)
    for season in (2029, 2028):
        for b in rids:
            p5, p6 = _future_pick(snap, b, season, 5), _future_pick(snap, b, season, 6)
            if not (p5 and p6):
                continue
            others = [r for r in rids if r != b]
            a, c = others[0], others[1]
            pa, pc = _first_player(snap, contract, a), _first_player(snap, contract, c)
            if pa and pc:
                return season, (a, b, c), (p5, p6, pa, pc)
    pytest.skip("no team holds its own round-5 and round-6 future picks on the archived board")


@pytest.mark.parametrize("mode", svc.MODES)
def test_the_reported_three_team_trade_is_evaluable(mode, _pinned_scarcity):
    contract, snap, _label = mts.real_board()
    season, (a, b, c), (p5, p6, pa, pc) = _reported_shape(snap, contract)
    legs = [
        {"id": p5, "from": b, "to": a},
        {"id": p6, "from": b, "to": a},
        {"id": pa, "from": a, "to": c},
        {"id": pc, "from": c, "to": b},
    ]
    out = _analyze(snap, [a, b, c], legs, mode)
    for rid in (a, b, c):
        team = out["teams"][rid]
        codes = {g["code"] for g in team["analysis"]["decision"]["missingEvidence"]}
        assert "quarantined_values" not in codes, (rid, codes)
        for row in (*team["gives"], *team["receives"]):
            if row["kind"] == "pick":
                # Counted once, priced, never zero.
                assert row["valueState"] == "priced", (rid, row)
                assert row["value"] and row["value"] > 0, (rid, row)
    # The picks count exactly once: what B gives is what A receives.
    give_b = sorted(r["value"] for r in out["teams"][b]["gives"] if r["kind"] == "pick")
    recv_a = sorted(r["value"] for r in out["teams"][a]["receives"] if r["kind"] == "pick")
    assert give_b == recv_a and len(give_b) == 2
    # A and B now get an answer from the same gates C always did.
    for rid in (a, b):
        assert out["teams"][rid]["fairness"]["state"] in ("FAIR", "NOT_FAIR"), rid

    # The derivation's uncertainty is reported, not hidden: the evidence lens
    # names both picks as low-confidence, and where the decision grades asset
    # evidence (team_context has other open gaps under the stub posture) the
    # touching teams' axis is no longer HIGH.  C touches neither pick.
    def axes(rid):
        return (out["teams"][rid]["analysis"]["decision"].get("confidence") or {}).get("axes") or {}

    for rid in (a, b):
        analysis = out["teams"][rid]["analysis"]
        detail = analysis["lenses"]["evidence"]["detail"]
        low = {x["name"] for x in detail["lowConfidenceAssets"]}
        sim = out["teams"][rid]["simulation"]
        pick_names = {
            x.get("name")
            for x in [*(sim.get("sending") or []), *(sim.get("receiving") or [])]
            if x.get("assetClass") == "pick"
        }
        assert len(pick_names) == 2 and pick_names <= low, (rid, pick_names, low)
        if mode != "team_context":
            assert axes(rid)["assetEvidence"] == "MEDIUM", rid
    if mode != "team_context":
        assert axes(c)["assetEvidence"] == "HIGH"


@pytest.mark.parametrize("mode", svc.MODES)
def test_a_two_team_trade_with_the_reported_picks_is_evaluable(mode, _pinned_scarcity):
    contract, snap, _label = mts.real_board()
    season, (a, b, _c), (p5, p6, pa, _pc) = _reported_shape(snap, contract)
    legs = [
        {"id": p5, "from": b, "to": a},
        {"id": p6, "from": b, "to": a},
        {"id": pa, "from": a, "to": b},
    ]
    out = _analyze(snap, [a, b], legs, mode)
    for rid in (a, b):
        codes = {g["code"] for g in out["teams"][rid]["analysis"]["decision"]["missingEvidence"]}
        assert "quarantined_values" not in codes, (rid, codes)
        assert out["teams"][rid]["fairness"]["state"] in ("FAIR", "NOT_FAIR"), rid


def test_a_genuinely_quarantined_pick_is_still_withheld(_pinned_scarcity):
    """The safeguard stays: inject a real quarantine on the generic row the
    picks resolve to, and both touching teams are withheld again."""
    contract, snap, _label = mts.real_board()
    season, (a, b, c), (p5, p6, pa, pc) = _reported_shape(snap, contract)
    for row in contract["playersArray"]:
        if row.get("canonicalName") in (f"{season} Round 5", f"{season} Round 6"):
            row["quarantined"] = True
            row["anomalyFlags"] = ["blend_integrity_violation"]
    snap2 = tl.build_trade_snapshot(
        contract,
        league_key="dynasty_main",
        roster_settings=mts._dynasty_main_settings(),
        now=mts.PINNED_NOW,
    )
    legs = [
        {"id": p5, "from": b, "to": a},
        {"id": p6, "from": b, "to": a},
        {"id": pa, "from": a, "to": c},
        {"id": pc, "from": c, "to": b},
    ]
    out = _analyze(snap2, [a, b, c], legs, "asset_only")
    for rid in (a, b):
        codes = {g["code"] for g in out["teams"][rid]["analysis"]["decision"]["missingEvidence"]}
        assert "quarantined_values" in codes, rid
        assert out["teams"][rid]["fairness"]["state"] == "UNABLE", rid
