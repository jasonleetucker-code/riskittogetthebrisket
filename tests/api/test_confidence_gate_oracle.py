"""Independent oracle for the confidence gate (QA directive 2026-11-06, CW-49).

The reference below is written from the SPECIFICATION only -- CLAUDE.md
"Confidence -- one owner, five axes, a bottleneck (B11)" (incl. "Losing evidence
never raises confidence") and the parameters in ``config/confidence/gate_v1.json``
-- and never calls the function under test to produce an expectation.  The
parameter numbers are re-declared here by value; the config-pin test catches a
silent edit to the config instead of absorbing it.

Oracle source per expectation:
  * ``_oracle`` -- spec text (axes, bottleneck, seating of withheld families).
  * known answers -- hand arithmetic in comments.
  * properties -- spec sentences "deleting evidence cannot promote", "losing a
    source never RAISES confidence", "a duplicate family raises".
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from src.api import confidence as conf
from src.api.confidence import FamilyEvidence, assess_confidence, assess_pick_confidence

LEVELS = ["none", "low", "medium", "high"]
AXES = ["independence", "coverage", "freshness", "applicability", "agreement"]

# Spec parameters (gate_v1.json), re-declared by value.
HIGH_N, MEDIUM_N = 5, 3
SHARE_HIGH, SHARE_MEDIUM = 0.75, 0.5
TOL = 0.15

_IDX = LEVELS.index


def test_config_pins_the_oracle_parameters() -> None:
    cfg = json.loads(
        (Path(__file__).resolve().parents[2] / "config/confidence/gate_v1.json").read_text()
    )["parameters"]
    got = {k: v["value"] for k, v in cfg.items()}
    assert got == {
        "INDEPENDENCE_HIGH_FAMILIES": HIGH_N,
        "INDEPENDENCE_MEDIUM_FAMILIES": MEDIUM_N,
        "EVIDENCE_SHARE_HIGH": SHARE_HIGH,
        "EVIDENCE_SHARE_MEDIUM": SHARE_MEDIUM,
        "AGREEMENT_VALUE_RATIO": TOL,
    }


def fam(name, value=100.0, fresh=True, native=True, direct=True) -> FamilyEvidence:
    return FamilyEvidence(
        family=name,
        source_key=f"src_{name}",
        value_contribution=value,
        fresh=fresh,
        format_native=native,
        directly_observed=direct,
    )


def lost(name) -> FamilyEvidence:
    return fam(name, value=None, fresh=None)


def _share(k: int, m: int) -> str:
    # spec: an axis is HIGH when >= 3/4 of the relevant evidence satisfies it,
    # MEDIUM when >= 1/2, otherwise LOW.  Integer cross-multiplication keeps
    # float rounding out of the oracle.
    if 4 * k >= 3 * m:
        return "high"
    if 2 * k >= m:
        return "medium"
    return "low"


def _agrees(contribution, center) -> bool:
    # spec: within 15% relative, symmetric mean normalisation |a-b| / mean(a,b).
    if contribution is None:
        return False
    a, b = float(contribution), float(center)
    mean = (a + b) / 2
    return mean > 0 and abs(a - b) / mean <= TOL


def _oracle(heads, eligible, consensus, withheld=()):
    n, w = len(heads), len(withheld)
    if n == 0:
        return "none", {a: "none" for a in AXES}
    panel = n + w  # lost families take a seat in every SHARE axis denominator
    axes = {}
    axes["independence"] = "high" if n >= HIGH_N else "medium" if n >= MEDIUM_N else "low"
    elig = set(eligible)
    covered = len({h.family for h in heads} & elig)
    axes["coverage"] = _share(covered, len(elig)) if elig else "low"
    axes["freshness"] = _share(sum(h.fresh is True for h in heads), panel)
    app = _share(sum(h.directly_observed for h in heads), panel)
    # Module-documented TE-basis rule: a majority of basis conversions costs one level.
    if 2 * sum(h.format_native for h in heads) < panel:
        app = LEVELS[max(1, _IDX(app) - 1)]
    axes["applicability"] = app
    if consensus is None or consensus <= 0:
        axes["agreement"] = "low"
    else:
        axes["agreement"] = _share(
            sum(_agrees(h.value_contribution, consensus) for h in heads), panel
        )
    return min(axes.values(), key=_IDX), axes


def _prod(heads, eligible, consensus, withheld=()):
    r = assess_confidence(
        heads, eligible_families=eligible, consensus_value=consensus, withheld=withheld
    )
    return r.overall, r.axes


# ───────────────────────── seeded differential sweep ─────────────────────────

FAMILIES = [f"f{i}" for i in range(12)]


def _panel(rng: random.Random):
    eligible = rng.sample(FAMILIES, rng.randint(1, 12))
    pool = list(set(eligible) | set(rng.sample(FAMILIES, 2)))
    rng.shuffle(pool)
    k = rng.randint(0, min(8, len(pool)))
    voting, rest = pool[:k], pool[k:]
    consensus = rng.choice([None, 0.0, 5000.0, 5000.0, 5000.0])
    heads = []
    for name in voting:
        v = rng.choice([None, 5000.0 * rng.uniform(0.7, 1.3), 5000.0 * rng.uniform(0.95, 1.05)])
        heads.append(
            fam(
                name,
                value=v,
                fresh=rng.choice([True, True, False, None]),
                native=rng.random() > 0.2,
                direct=rng.random() > 0.2,
            )
        )
    withheld = [lost(x) for x in rest[: rng.randint(0, 3)]]
    return heads, eligible, consensus, withheld


def test_production_matches_spec_oracle_on_seeded_sweep() -> None:
    rng = random.Random(20261106)
    for i in range(600):
        heads, eligible, consensus, withheld = _panel(rng)
        assert _prod(heads, eligible, consensus, withheld) == _oracle(
            heads, eligible, consensus, withheld
        ), f"case {i}: {heads} {eligible} {consensus} {withheld}"


# ───────────────────────── hand-computed known answers ─────────────────────────


def test_exactly_five_families_all_good_is_high() -> None:
    # 5 >= HIGH_N -> independence high; coverage 5/5=1.0; fresh 5/5; direct 5/5;
    # agreement 5/5 (identical values, gap 0) -> every axis high -> high.
    heads = [fam(f"f{i}") for i in range(5)]
    assert _prod(heads, [f"f{i}" for i in range(5)], 100.0)[0] == "high"


def test_four_families_cap_at_medium() -> None:
    # n=4: 3 <= 4 < 5 -> independence medium; all share axes 4/4 high -> medium.
    heads = [fam(f"f{i}") for i in range(4)]
    assert _prod(heads, [f"f{i}" for i in range(4)], 100.0)[0] == "medium"


def test_two_families_cannot_exceed_low() -> None:
    # n=2 < 3 -> independence low, regardless of perfect agreement -> low.
    heads = [fam("a"), fam("b")]
    assert _prod(heads, ["a", "b"], 100.0)[0] == "low"


def test_coverage_boundary_75_vs_74_percent() -> None:
    names = [f"f{i}" for i in range(5)]
    # 5 voting of 6 eligible = 0.8333 >= 0.75 -> high.
    assert _prod([fam(x) for x in names], names + ["x"], 100.0)[1]["coverage"] == "high"
    # 6 of 8 = 0.75 exactly -> high (>=).
    six = [f"f{i}" for i in range(6)]
    assert _prod([fam(x) for x in six], six + ["x", "y"], 100.0)[1]["coverage"] == "high"
    # 5 of 7 = 0.714 < 0.75 -> medium (>= 0.5).
    assert _prod([fam(x) for x in names], names + ["x", "y"], 100.0)[1]["coverage"] == "medium"
    # 74 of 100 vs 75 of 100.
    big = [f"g{i}" for i in range(100)]
    assert _prod([fam(x) for x in big[:74]], big, 100.0)[1]["coverage"] == "medium"
    assert _prod([fam(x) for x in big[:75]], big, 100.0)[1]["coverage"] == "high"


def test_agreement_exactly_at_fifteen_percent_counts() -> None:
    # consensus 43, contribution 37: |43-37| / ((43+37)/2) = 6/40 = 0.15 -> agrees (<=).
    heads = [fam(f"f{i}", value=37.0) for i in range(5)]
    assert _prod(heads, [h.family for h in heads], 43.0)[1]["agreement"] == "high"
    # contribution 36: 7/39.5 = 0.1772 > 0.15 -> disagrees -> 0/5 -> low.
    heads = [fam(f"f{i}", value=36.0) for i in range(5)]
    assert _prod(heads, [h.family for h in heads], 43.0)[1]["agreement"] == "low"


def test_one_stale_family_pulls_freshness_below_threshold() -> None:
    names = [f"f{i}" for i in range(5)]
    # 4 fresh of 5 = 0.8 -> high.
    four = [fam(x, fresh=(x != "f0")) for x in names]
    assert _prod(four, names, 100.0)[1]["freshness"] == "high"
    # 2 fresh of 3 = 0.667 -> medium.
    three = [fam("a"), fam("b"), fam("c", fresh=False)]
    assert _prod(three, list("abc"), 100.0)[1]["freshness"] == "medium"
    # unknown freshness (None) is never fresh: 2 fresh + 1 unknown of 3 -> medium.
    unk = [fam("a"), fam("b"), fam("c", fresh=None)]
    assert _prod(unk, list("abc"), 100.0)[1]["freshness"] == "medium"


def test_duplicate_family_raises() -> None:
    with pytest.raises(ValueError):
        assess_confidence([fam("a"), fam("a")], eligible_families=["a"], consensus_value=100.0)
    # a family with a voting member cannot also be withheld
    with pytest.raises(ValueError):
        assess_confidence(
            [fam("a")], eligible_families=["a"], consensus_value=100.0, withheld=[lost("a")]
        )


def test_withheld_families_are_seated_in_share_denominators_only() -> None:
    names = [f"f{i}" for i in range(5)]
    heads = [fam(x) for x in names]
    elig = names + ["w"]
    base = _prod(heads, elig, 100.0)
    # 5 voting + 1 withheld: panel 6 -> shares 5/6 = 0.833 high; independence
    # stays 5 (a withheld family is not a head); coverage 5/6 unchanged -> high.
    assert base[0] == "high"
    assert _prod(heads, elig, 100.0, [lost("w")]) == base
    # 5 voting + 2 withheld: panel 7 -> 5/7 = 0.714 -> medium on the three share
    # axes; independence/coverage (5 heads, 5/7 of 7 eligible = 0.714 -> medium).
    r = _prod(heads, elig + ["w2"], 100.0, [lost("w"), lost("w2")])
    assert r[0] == "medium"
    assert r[1]["freshness"] == r[1]["applicability"] == r[1]["agreement"] == "medium"
    assert r[1]["independence"] == "high"


def test_no_evidence_and_no_consensus() -> None:
    assert _prod([], ["a"], 100.0)[0] == "none"
    # a missing published value is not agreement
    heads = [fam(f"f{i}") for i in range(5)]
    assert _prod(heads, [h.family for h in heads], None)[1]["agreement"] == "low"


# ───────────────────────── properties ─────────────────────────


def test_losing_a_family_to_withheld_never_raises_anything() -> None:
    # The CW-47 class: evidence that stops voting but was observed must not promote.
    rng = random.Random(47)
    checked = 0
    for _ in range(500):
        heads, eligible, consensus, withheld = _panel(rng)
        if len(heads) < 2:
            continue
        victim = rng.choice(heads)
        rest = [h for h in heads if h is not victim]
        before = _prod(heads, eligible, consensus, withheld)
        after = _prod(rest, eligible, consensus, withheld + [lost(victim.family)])
        checked += 1
        assert _IDX(after[0]) <= _IDX(before[0]), (heads, victim)
        for a in AXES:
            assert _IDX(after[1][a]) <= _IDX(before[1][a]), (a, heads, victim)
    assert checked > 100


def test_deleting_a_family_never_raises_count_axes_or_when_it_was_good() -> None:
    rng = random.Random(7)
    for _ in range(500):
        heads, eligible, consensus, withheld = _panel(rng)
        if len(heads) < 2:
            continue
        victim = rng.choice(heads)
        rest = [h for h in heads if h is not victim]
        before = _prod(heads, eligible, consensus, withheld)
        after = _prod(rest, eligible, consensus, withheld)
        for a in ("independence", "coverage"):
            assert _IDX(after[1][a]) <= _IDX(before[1][a])
        good = (
            victim.fresh is True
            and victim.directly_observed
            and victim.format_native
            and _agrees(victim.value_contribution, consensus or 0)
        )
        if good:
            assert _IDX(after[0]) <= _IDX(before[0])


def test_extra_seated_family_never_raises_any_share_axis() -> None:
    rng = random.Random(11)
    for _ in range(300):
        heads, eligible, consensus, withheld = _panel(rng)
        if not heads:
            continue
        before = _prod(heads, eligible, consensus, withheld)
        after = _prod(heads, eligible, consensus, withheld + [lost("zz_extra")])
        for a in AXES:
            assert _IDX(after[1][a]) <= _IDX(before[1][a])


def test_panel_order_does_not_matter() -> None:
    rng = random.Random(3)
    for _ in range(200):
        heads, eligible, consensus, withheld = _panel(rng)
        a = _prod(heads, eligible, consensus, withheld)
        shuffled = heads[:]
        rng.shuffle(shuffled)
        w2 = withheld[:]
        rng.shuffle(w2)
        assert _prod(shuffled, eligible, consensus, w2) == a


# ───────────────────────── picks ─────────────────────────


def test_pick_single_provider_is_low() -> None:
    # KTC Crowd + KTC Trades are two families of ONE provider (spec): agreement
    # between them corroborates nothing, whatever the values.
    for slot in (False, True):
        bucket, label = assess_pick_confidence(
            {"ktcCrowdSfTep": 1000, "ktcTradesSfTep": 1000}, is_slot_specific=slot
        )
        assert (bucket, label) == ("low", "Low — single pick provider")


def test_pick_two_providers_agreeing_is_high_and_no_values_is_none() -> None:
    # KTC (1.0) + IDPTC (1.0) = 2.0 >= 1.5; cv = 0 <= 0.15 -> high.
    vals = {"ktcCrowdSfTep": 1000, "idpTradeCalc": 1000}
    assert assess_pick_confidence(vals, is_slot_specific=False)[0] == "high"
    # slot-specific KTC counts 0.5: 0.5 + 1.0 = 1.5 -> still high.
    assert assess_pick_confidence(vals, is_slot_specific=True)[0] == "high"
    assert assess_pick_confidence({}, is_slot_specific=False)[0] == "none"


def test_pick_unknown_provider_fails_closed(monkeypatch) -> None:
    real = conf._pick_provider
    monkeypatch.setattr(conf, "_pick_provider", lambda k: None if k == "idpTradeCalc" else real(k))
    bucket, label = assess_pick_confidence(
        {"ktcCrowdSfTep": 1000, "idpTradeCalc": 1000}, is_slot_specific=False
    )
    assert (bucket, label) == ("low", "Low — pick provider identity unknown")


def test_pick_withholding_never_raises() -> None:
    rng = random.Random(5)
    keys = ["ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc", "dlfSf", "dynastyNerdsSfTep"]
    for _ in range(300):
        vals = {k: rng.choice([800, 1000, 1000, 1500]) for k in rng.sample(keys, rng.randint(1, 5))}
        slot = rng.random() > 0.5
        base = assess_pick_confidence(vals, is_slot_specific=slot)[0]
        wh = rng.sample(sorted(vals), rng.randint(0, len(vals)))
        got = assess_pick_confidence(vals, is_slot_specific=slot, withheld_sources=wh)[0]
        assert _IDX(got) <= _IDX(base)
