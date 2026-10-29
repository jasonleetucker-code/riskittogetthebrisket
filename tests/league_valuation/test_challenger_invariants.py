"""Structural invariants of the league fair value challenger (spec tests a-h, j).

Each property is asserted on the MATH, not by grepping for a constant: the
uniform-shift test is the structural replacement for "no literal 0.5 exists".
"""

from __future__ import annotations

import copy
import json
import math
import random
from collections import Counter

import pytest

from src.canonical.player_valuation import DISPLAY_SCALE_MAX, DISPLAY_SCALE_MIN
from src.league_intel.overlay import CANONICAL_VALUE_FIELDS
from src.league_valuation.challenger import (
    ChallengerInvariantError,
    compute_fair_values,
    interpolate,
    quantile_match,
)
from src.league_valuation.evidence import utility_evidence_from_bdvm
from tests.league_valuation._builders import (
    IDP,
    NOW,
    PARAMS,
    aligned_payload,
    bdvm_entry,
    board,
    params_with,
    payload,
    pins,
    row,
    run,
    shuffled_payload,
)

ALL_K_ONE = params_with(
    kMax__value=1.0, quality__byProjectionFamilies={"0": 0.0, "1": 1.0, "2": 1.0, "3": 1.0}
)


def _available(fb):
    return {k: v for k, v in fb.values.items() if v.state == "available"}


# (a) identical utility and market orders -> fair == market for every row
def test_identical_orders_are_an_exact_no_op():
    rows = board()
    fb = run(rows, aligned_payload(rows))
    avail = _available(fb)
    assert len(avail) == len(rows)
    for v in fb.values.values():
        assert v.fair_value == v.market_value
        assert v.fair_value_exact == float(v.market_value)
    for scope in ("OFFENSE", "IDP"):
        assert fb.diagnostics["scopes"][scope]["moved"] == 0
        assert fb.diagnostics["scopes"][scope]["logDrift"]["sum"] == 0.0


def test_identical_orders_with_k_one_are_still_an_exact_no_op():
    rows = board()
    fb = run(rows, aligned_payload(rows), params=ALL_K_ONE)
    assert all(v.fair_value == v.market_value for v in fb.values.values())


# (b) uniform utility shift -> zero movement (structural replacement of any grep)
@pytest.mark.parametrize("shift", [-500.0, -3.5, 0.0, 7.25, 10_000.0])
def test_uniform_utility_shift_moves_nothing(shift):
    rows = board()
    base = run(rows, shuffled_payload(rows))
    shifted_payload = shuffled_payload(rows)
    for e in shifted_payload["players"]:
        e["fundamental"]["balanced"] += shift
        e["raw"]["vorg"] += shift
    shifted = run(rows, shifted_payload)
    for key, v in base.values.items():
        assert shifted.values[key].fair_value == v.fair_value
        assert shifted.values[key].fair_value_exact == v.fair_value_exact


def test_uniform_positive_rescaling_of_utility_moves_nothing():
    rows = board()
    base = run(rows, shuffled_payload(rows))
    scaled = shuffled_payload(rows)
    for e in scaled["players"]:
        e["fundamental"]["balanced"] *= 3.0
        e["raw"]["vorg"] *= 3.0
    out = run(rows, scaled)
    assert {k: v.fair_value for k, v in out.values.items()} == {
        k: v.fair_value for k, v in base.values.items()
    }


# (c) k = 1 everywhere preserves the population log-value multiset exactly
def test_k_one_preserves_population_log_value_multiset():
    rows = board()
    fb = run(rows, shuffled_payload(rows), params=ALL_K_ONE)
    offense = [v for v in fb.values.values() if v.scope == "OFFENSE" and v.state == "available"]
    assert offense and all(v.k == 1.0 for v in offense)
    assert Counter(v.market_value for v in offense) == Counter(v.fair_value for v in offense)
    assert Counter(math.log(v.market_value) for v in offense) == Counter(
        math.log(v.fair_value_exact) for v in offense
    )
    assert sum(1 for v in offense if v.moved) > 0


def test_k_one_with_utility_ties_preserves_the_log_sum():
    market = [9000, 7000, 5000, 3000, 1000]
    utility = [(1.0, 0.0), (1.0, 0.0), (0.5, 0.0), (0.5, 0.0), (0.1, 0.0)]
    matched, ranks = quantile_match(market, utility)
    assert ranks == [1.5, 1.5, 3.5, 3.5, 5.0]
    assert matched[0] == matched[1] == pytest.approx(math.sqrt(9000 * 7000))
    assert math.fsum(math.log(m) for m in matched) == pytest.approx(
        math.fsum(math.log(v) for v in market), abs=1e-12
    )


def test_uniform_k_preserves_the_population_log_sum():
    rows = board()
    fb = run(
        rows,
        shuffled_payload(rows),
        params=params_with(quality__byProjectionFamilies={"0": 0.0, "1": 0.6, "2": 0.6, "3": 0.6}),
    )
    assert abs(fb.diagnostics["scopes"]["OFFENSE"]["logDrift"]["sum"]) < 1e-9


# (d) fair always between v_i and m_i, inside [1, 9999] -- adversarial property test
@pytest.mark.parametrize("seed", range(40))
def test_fair_is_bounded_between_own_and_matched_and_inside_scale(seed):
    rng = random.Random(seed)
    n = rng.randint(2, 60)
    rows = [
        row(
            str(9000 + i),
            rng.choice(("QB", "RB", "WR", "TE")),
            rng.choice([1, 2, 9998, 9999, rng.randint(1, 9999)]),
            i + 1,
        )
        for i in range(n)
    ]
    entries = []
    for r in rows:
        dv = rng.choice([0.0, 0.0, rng.uniform(0, 1e6), 1e-300, 1e300])
        vorg = rng.choice([-1e9, -1.0, 0.0, 1.0, rng.uniform(-50, 50)])
        srcs = ["a", "b", "c", "d", "e"][: rng.randint(1, 5)]
        entries.append(bdvm_entry(r["playerId"], r["position"], dv, vorg, sources=srcs))
    params = params_with(kMax__value=rng.choice([0.0, 0.25, 0.5, 0.99, 1.0]))
    fb = run(rows, payload(entries), params=params)
    for v in fb.values.values():
        if v.state != "available":
            continue
        lo = min(v.market_value, v.matched_value_exact)
        hi = max(v.market_value, v.matched_value_exact)
        assert lo - 1e-9 <= v.fair_value_exact <= hi + 1e-9
        assert lo <= v.fair_value <= hi
        assert DISPLAY_SCALE_MIN <= v.fair_value <= DISPLAY_SCALE_MAX


def test_interpolation_is_exact_at_endpoints():
    assert interpolate(4000.0, 6000.0, 0.0) == 4000.0
    assert interpolate(4000.0, 6000.0, 1.0) == 6000.0
    assert interpolate(4000.0, 4000.0, 0.37) == 4000.0
    mid = interpolate(4000.0, 9000.0, 0.5)
    assert mid == pytest.approx(6000.0)  # geometric mean


# (e) stale or missing evidence -> fair == market exactly
@pytest.mark.parametrize(
    "mutate,reason",
    [
        (
            lambda p: p["meta"]["projectionSnapshot"].update(asOf="2026-09-01T00:00:00+00:00"),
            "evidence_stale",
        ),
        (
            lambda p: p["meta"]["projectionSnapshot"].update(asOf=None, asOfUnknown=True),
            "evidence_unavailable",
        ),
        (lambda p: p.update(status="no_projection_snapshot"), "no_utility_evidence"),
        (lambda p: p.update(players=[]), "no_utility_evidence"),
    ],
)
def test_stale_or_missing_evidence_returns_market_exactly(mutate, reason):
    rows = board()
    pl = shuffled_payload(rows)
    mutate(pl)
    fb = run(rows, pl)
    for v in fb.values.values():
        assert v.state == "excluded"
        assert v.fair_value == v.market_value
        assert v.excluded_reason == reason
        assert v.k == 0.0


def test_per_player_stale_proxy_and_missing_strategy_return_market():
    rows = [
        row("1", "QB", 9000, 1),
        row("2", "QB", 8000, 2),
        row("3", "QB", 7000, 3),
        row("4", "QB", 6000, 4),
        row("5", "QB", 5000, 5),
    ]
    entries = [
        bdvm_entry("1", "QB", 1.0, -1.0),
        bdvm_entry("2", "QB", 900.0, 9.0, sources=["clay"], stale=["clay"]),
        bdvm_entry("3", "QB", 950.0, 9.5, sources=["reconstructed_baseline"], proxy=True),
        bdvm_entry("4", "QB", None, 9.9, strategies={"win_now": 1.0}),
        bdvm_entry("5", "QB", 999.0, 10.0),
    ]
    fb = run(rows, payload(entries))
    assert fb.values["player:2"].excluded_reason == "evidence_stale"
    assert fb.values["player:3"].excluded_reason == "evidence_partial"
    assert fb.values["player:4"].excluded_reason == "evidence_unavailable"
    assert fb.values["player:4"].reason == "strategy_missing:balanced"
    for key in ("player:2", "player:3", "player:4"):
        assert fb.values[key].fair_value == fb.values[key].market_value
    # The two available rows swap places in utility and move toward each other.
    assert fb.values["player:1"].fair_value < 9000
    assert fb.values["player:5"].fair_value > 5000


# (f) haircut, override, off-cap and blend-integrity rows excluded and unchanged
def test_structurally_excluded_rows_are_unchanged_and_named():
    path = "tests/fixtures/league_valuation/"
    rows = json.load(open(path + "synthetic_board.json", encoding="utf-8"))["playersArray"]
    pl = json.load(open(path + "bdvm_payload.json", encoding="utf-8"))
    fb = run(rows, pl)
    expected = {
        "player:7002": "quarantined",
        "player:7003": "single_source_haircut",
        "player:7004": "two_way_player",
        "player:7005": "blend_integrity_violation",
        "player:7006": "off_cap_value_only",
        "player:7001": "unsupported_position",
        "mpick:2027:r1:tearly": "pick",
        "player:7007": "evidence_unavailable",
        "player:7012": "no_market_value",
    }
    for key, reason in expected.items():
        v = fb.values[key]
        assert v.excluded_reason == reason, key
        assert v.fair_value == v.market_value
    assert fb.values["player:7007"].reason == "bdvm_unpriced:no_projection"
    # Excluded rows (each with very high utility) do not enter any population:
    # removing them changes no in-population fair value.
    kept = [r for r in rows if r.get("playerId") not in {"7002", "7003", "7004", "7005", "7006"}]
    again = run(kept, pl)
    for key, v in _available(fb).items():
        assert again.values[key].fair_value == v.fair_value


def test_te_rows_stay_in_and_carry_the_tepp_basis_label():
    rows = board()
    fb = run(rows, shuffled_payload(rows))
    tes = [v for v in fb.values.values() if v.position == "TE"]
    assert tes and all(v.state == "available" for v in tes)
    assert all("te_basis_tepp" in v.labels for v in tes)
    assert not any("te_basis_tepp" in v.labels for v in fb.values.values() if v.position != "TE")


# (g) IDP and OFFENSE never mix populations
def test_scopes_never_mix():
    rows = board()
    fb = run(rows, shuffled_payload(rows), params=ALL_K_ONE)
    for scope in ("OFFENSE", "IDP"):
        members = [v for v in fb.values.values() if v.scope == scope and v.state == "available"]
        market = sorted(v.market_value for v in members)
        matched = sorted(round(v.matched_value_exact, 6) for v in members)
        assert matched == sorted(round(float(m), 6) for m in market)


def test_scope_mismatched_evidence_is_refused():
    rows = [row("1", "WR", 9000, 1), row("2", "WR", 5000, 2)]
    entries = [bdvm_entry("1", "LB", 1.0, 1.0), bdvm_entry("2", "WR", 2.0, 2.0)]
    fb = run(rows, payload(entries))
    assert fb.values["player:1"].excluded_reason == "scope_mismatch"
    assert fb.values["player:2"].fair_value == 5000  # a population of one cannot move


def test_idp_fanout_gate_forces_k_zero_when_unstable():
    rows = board()
    fb = run(rows, shuffled_payload(rows))
    idp = [v for v in fb.values.values() if v.scope == "IDP" and v.state == "available"]
    assert idp and all(v.k == 0.0 and v.fair_value == v.market_value for v in idp)
    assert fb.diagnostics["scopes"]["IDP"]["idpFanOut"]["stable"] is False
    assert all("idp_fanout_unstable" in v.reason for v in idp)


def test_idp_fanout_gate_admits_a_depth_stable_disagreement():
    rows = []
    entries = []
    rank = 0
    for pos in IDP:
        for i in range(40):
            rank += 1
            pid = str(rank)
            value = round(9000 * (0.97**i))
            rows.append(row(pid, pos, value, rank, assetClass="idp"))
            # adjacent pairs swap in utility: the disagreement is the same at
            # every depth, so it does not fan out
            u = float(i ^ 1)
            entries.append(bdvm_entry(pid, pos, 1000.0 - u, -u))
    fb = run(rows, payload(entries))
    gate = fb.diagnostics["scopes"]["IDP"]["idpFanOut"]
    assert gate["stable"] is True, gate
    assert any(v.moved for v in fb.values.values() if v.scope == "IDP")


# (h) below-replacement is not tied with missing
def test_below_replacement_is_ranked_not_missing():
    rows = [row(str(i), "RB", 9000 - 1000 * i, i + 1) for i in range(5)]
    # Every DV truncated to 0 (BDVM's risk floor); signed vorg still orders them,
    # REVERSED against the market.
    entries = [bdvm_entry(str(i), "RB", 0.0, -1.0 * (5 - i)) for i in range(4)]
    fb = run(rows, payload(entries), params=ALL_K_ONE)
    assert fb.values["player:4"].excluded_reason == "no_utility_evidence"
    ranks = [fb.values[f"player:{i}"].utility_rank for i in range(4)]
    assert ranks == [4.0, 3.0, 2.0, 1.0]  # distinct: no zero-block tie
    assert [fb.values[f"player:{i}"].fair_value for i in range(4)] == [6000, 7000, 8000, 9000]


def test_market_confidence_never_amplifies_shrinkage():
    rows = board()
    base = run(rows, shuffled_payload(rows))
    degraded = copy.deepcopy(rows)
    for r in degraded:
        r["confidenceBucket"] = "low"
        r["confidenceLabel"] = "Low"
    out = run(degraded, shuffled_payload(rows))
    assert {k: (v.k, v.fair_value) for k, v in out.values.items()} == {
        k: (v.k, v.fair_value) for k, v in base.values.items()
    }


# (j) no canonical field is written; inputs untouched
def test_no_canonical_field_is_written_anywhere():
    rows = board()
    before = json.dumps(rows, sort_keys=True)
    fb = run(rows, shuffled_payload(rows))
    assert json.dumps(rows, sort_keys=True) == before  # caller rows untouched

    def _keys(node):
        if isinstance(node, dict):
            for k, v in node.items():
                yield k
                yield from _keys(v)
        elif isinstance(node, list):
            for v in node:
                yield from _keys(v)

    keys = set(_keys(fb.to_dict()))
    assert not (keys & set(CANONICAL_VALUE_FIELDS)), keys & set(CANONICAL_VALUE_FIELDS)
    assert "experimentalLeagueAdjustedValue" not in keys
    assert fb.to_dict()["shadowOnly"] is True


def test_no_challenger_ranks_are_produced():
    """The one ranker sorts on the canonical field, which a shadow challenger
    may not write; no second ranker exists, so ranks are stated unavailable."""
    rows = board()
    fb = run(rows, shuffled_payload(rows))
    assert fb.diagnostics["ranks"]["state"] == "unavailable"
    some = next(iter(fb.values.values())).to_dict()
    assert "fairRank" not in some and "fairTier" not in some


def test_deterministic_and_reproducible_from_inputs():
    rows = board()
    a = run(rows, shuffled_payload(rows)).to_dict()
    b = run(copy.deepcopy(rows), shuffled_payload(rows)).to_dict()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_invalid_k_max_fails_closed():
    rows = board()
    ev = utility_evidence_from_bdvm(shuffled_payload(rows), now=NOW, params=PARAMS)
    bad = params_with(kMax__value=1.5)
    with pytest.raises(ChallengerInvariantError):
        compute_fair_values(rows, ev, params=bad, pins=pins(bad))
