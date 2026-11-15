"""Candidate F — the coverage-aligned within-family crosswalk (owner directive
2026-10-19, SIGNALS_IDP_VOTING; ``src/bridges/family_crosswalk.py``).

Mathematics only, on SYNTHETIC values (no Signals data, no live board, no
network).  Pins the preregistered structural properties:

* permutation identity with no ties, tie averaging otherwise;
* monotone in the source's order;
* injection invariance (a source-only row changes no matched vote);
* no vote outside the matched coordinates' range;
* no bridge-priced matched player withheld; rookies and unmatched rows
  withheld with a reason (never zero);
* shuffle determinism;
* no fabricated cross-family order (the crosswalk sees one family at a time);
* fail closed with several bridges (plus the validator alert) and when the
  level source is withheld;
* fractional ranks never routed through ``translate_position_rank``;
* ONE pricing helper — shadow and vote — including the deep-tail band;
* the bridge's name key is the key σ's ties are broken on.

Property tests use a seeded ``random.Random`` (no hypothesis dependency).
"""

from __future__ import annotations

import ast
import inspect
import random
from dataclasses import dataclass, field
from typing import Any

import pytest

from src.api import data_contract as dc
from src.bridges import family_crosswalk as fx
from src.bridges.ladder import BridgeLadder, bridge_order_name_key, build_bridge_ladder

SEEDS = range(200)


def _obs(key, value, coord, *, name=None, rookie=False):
    return fx.FamilyObservation(
        key=key,
        order_value=float(value),
        name_key=name if name is not None else f"p{key:04d}",
        reference_coordinate=coord,
        rookie=rookie,
    )


def _random_family(rng: random.Random, *, ties: bool, n: int | None = None):
    n = n or rng.randint(1, 60)
    coords = sorted(rng.sample(range(1, 900), n))
    values = (
        [float(rng.randint(1, 8)) for _ in range(n)] if ties else rng.sample(range(1, 100000), n)
    )
    return [_obs(i, values[i], coords[i]) for i in range(n)]


# ── structural properties ───────────────────────────────────────────────


@pytest.mark.parametrize("seed", SEEDS)
def test_no_ties_votes_are_a_permutation_of_the_matched_coordinates(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=False)
    votes = fx.coverage_aligned_votes(obs)
    got = sorted(v.rank for v in votes.values())
    want = sorted(float(o.reference_coordinate) for o in obs)
    assert got == want
    assert all(v.tie_size == 1 and v.withheld_reason is None for v in votes.values())


@pytest.mark.parametrize("seed", SEEDS)
def test_tie_groups_vote_the_mean_of_their_slots(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=True)
    votes = fx.coverage_aligned_votes(obs)
    coords = sorted(o.reference_coordinate for o in obs)
    by_value: dict[float, list] = {}
    for o in obs:
        by_value.setdefault(o.order_value, []).append(o)
    start = 0
    for value in sorted(by_value, reverse=True):
        group = by_value[value]
        mean = sum(coords[start : start + len(group)]) / len(group)
        for o in group:
            assert votes[o.key].rank == pytest.approx(mean)
            assert votes[o.key].matched_rank == start + 1
            assert votes[o.key].tie_size == len(group)
        start += len(group)
    # The mean of the votes is the mean of the slots (ties redistribute only).
    assert sum(v.rank for v in votes.values()) == pytest.approx(sum(coords))


@pytest.mark.parametrize("seed", SEEDS)
def test_votes_are_monotone_in_the_source_order(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=bool(seed % 2))
    votes = fx.coverage_aligned_votes(obs)
    ordered = sorted(obs, key=lambda o: -o.order_value)
    for better, worse in zip(ordered, ordered[1:]):
        # A better (or equal) source order never votes a deeper rank.
        assert votes[better.key].rank <= votes[worse.key].rank + 1e-9


@pytest.mark.parametrize("seed", SEEDS)
def test_injection_invariance_source_only_rows_change_no_matched_vote(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=bool(seed % 2))
    base = fx.coverage_aligned_votes(obs)
    extra = [_obs(10_000 + j, rng.uniform(0, 200_000), None) for j in range(rng.randint(1, 25))]
    injected = fx.coverage_aligned_votes([*obs, *extra])
    for o in obs:
        assert injected[o.key] == base[o.key]
    for o in extra:
        assert injected[o.key].rank is None
        assert injected[o.key].withheld_reason == fx.WITHHELD_UNMATCHED


@pytest.mark.parametrize("seed", SEEDS)
def test_no_vote_outside_the_matched_range_and_no_matched_player_withheld(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=bool(seed % 2))
    votes = fx.coverage_aligned_votes(obs)
    lo = min(o.reference_coordinate for o in obs)
    hi = max(o.reference_coordinate for o in obs)
    for o in obs:
        assert votes[o.key].withheld_reason is None
        assert lo <= votes[o.key].rank <= hi


@pytest.mark.parametrize("seed", range(50))
def test_shuffle_determinism(seed):
    rng = random.Random(seed)
    obs = _random_family(rng, ties=True)
    want = fx.coverage_aligned_votes(obs)
    for _ in range(5):
        shuffled = list(obs)
        rng.shuffle(shuffled)
        assert fx.coverage_aligned_votes(shuffled) == want


def test_rookies_are_withheld_by_basis_and_free_their_slot():
    obs = [_obs(0, 9, 10), _obs(1, 8, 20, rookie=True), _obs(2, 7, 30)]
    votes = fx.coverage_aligned_votes(obs)
    assert votes[1] == fx.CrosswalkVote(rank=None, withheld_reason=fx.WITHHELD_ROOKIE)
    # The rookie is not in M, so the remaining matched players are aligned to
    # their OWN coordinates (permutation over the non-rookie matched set).
    assert (votes[0].rank, votes[2].rank) == (10.0, 30.0)
    assert fx.WITHHELD_ROOKIE in fx.WITHHELD_BY_TRANSLATION


def test_a_disagreeing_order_permutes_the_coordinates_it_never_invents_one():
    obs = [_obs(0, 1, 10), _obs(1, 2, 25), _obs(2, 3, 40)]  # source reverses the bridge
    votes = fx.coverage_aligned_votes(obs)
    assert [votes[k].rank for k in (2, 1, 0)] == [10.0, 25.0, 40.0]


def test_missing_is_never_zero():
    votes = fx.coverage_aligned_votes([_obs(0, 5, None), _obs(1, 4, None, rookie=True)])
    assert all(v.rank is None and v.withheld_reason for v in votes.values())
    assert fx.coverage_aligned_votes([]) == {}


def test_the_bridge_name_key_is_the_ladders_own_tiebreak():
    assert bridge_order_name_key("Abc Def") == "abc def"
    assert bridge_order_name_key(None) == ""
    src = inspect.getsource(build_bridge_ladder.__globals__["_family_pass"])
    assert "bridge_order_name_key(t[1])" in src


# ── the bridge's family positions (same pass as the ladder) ─────────────


@dataclass
class _Cap:
    combined_depth: int


@dataclass
class _Desc:
    bridge_key: str
    keys: tuple[str, ...]
    idp_keys: tuple[str, ...] = ()


@dataclass
class _Assess:
    descriptor: Any
    capability: Any
    usable: bool = True


def _rows(n_off=30, n_idp=30, picks=5):
    rows: list[dict] = []
    v = 9999.0
    for i in range(max(n_off, n_idp, picks)):
        if i < n_off:
            rows.append(
                {"displayName": f"Off {i:03d}", "position": "WR", "canonicalSiteValues": {"b": v}}
            )
            v -= 7
        if i < picks:
            rows.append(
                {
                    "displayName": f"2026 Pick 1.{i + 1:02d}",
                    "position": "PICK",
                    "canonicalSiteValues": {"b": v},
                }
            )
            v -= 7
        if i < n_idp:
            rows.append(
                {
                    "displayName": f"Idp {i:03d}",
                    "position": ("DL", "LB", "DB")[i % 3],
                    "canonicalSiteValues": {"b": v},
                }
            )
            v -= 7
    return rows  # fmt: skip


def _ladder(rows, contributors=1):
    assessments = [
        _Assess(_Desc(f"bridge{j}", ("b",), ("b",)), _Cap(len(rows))) for j in range(contributors)
    ]
    return build_bridge_ladder(
        assessments,
        rows,
        offense_positions=frozenset({"WR", "PICK"}),
        idp_positions=frozenset({"DL", "LB", "DB"}),
        limit=None,
    )


def test_family_position_is_the_row_holding_that_family_slot():
    rows = _rows()
    ladder = _ladder(rows)
    assert ladder.family_positions_defined
    for family in ("DL", "LB", "DB"):
        members = [r for r in rows if r["position"] == family]
        slots = [ladder.family_position(r) for r in members]
        assert [s[1] for s in slots] == list(range(len(members)))
        assert {s[0] for s in slots} == {family}
        # c(p) = the family ladder's entry at p's slot = p's combined rank.
        combined = sorted(
            (r for r in rows),
            key=lambda r: (-r["canonicalSiteValues"]["b"], r["displayName"].lower()),
        )
        for r, (_f, slot) in zip(members, slots):
            assert ladder.family_ladder(family)[slot] == combined.index(r) + 1
    assert ladder.family_position({"displayName": "stranger"}) is None
    # Bridge-side diagnostics, never on the published dict.
    assert "familySlots" not in ladder.to_dict() and "family_slots" not in ladder.to_dict()


def test_pick_rows_above_each_family_slot_are_counted():
    rows = _rows()
    ladder = _ladder(rows)
    for family, above in ladder.family_pick_rows_above.items():
        assert list(above) == sorted(above)
        assert above[-1] == 5  # every pick sits above the deepest IDP here


def test_several_bridges_leave_family_positions_undefined():
    rows = _rows()
    ladder = _ladder(rows, contributors=2)
    assert len(ladder.contributors) == 2
    assert not ladder.family_positions_defined
    assert ladder.family_position(rows[2]) is None
    assert ladder.family_slots == {}


# ── data_contract seams ─────────────────────────────────────────────────


def _eligible(rows, family):
    return [
        (float(1000 - i), idx, "position_idp", r["displayName"].lower())
        for i, (idx, r) in enumerate((j, r) for j, r in enumerate(rows) if r["position"] == family)
    ]


def test_multi_bridge_fails_closed_with_a_named_reason_and_an_alert():
    rows = _rows()
    ladder = _ladder(rows, contributors=2)
    votes = dc._coverage_aligned_family_votes(
        _eligible(rows, "LB"),
        rows,
        position_group="LB",
        bridge_ladder=ladder,
        reference_withheld=False,
    )
    assert votes and {v.withheld_reason for v in votes.values()} == {fx.WITHHELD_MULTI_BRIDGE}
    summary = dc._family_crosswalk_summary(ladder, level_source=None, reference_withheld=False)
    assert summary["failClosed"] == fx.WITHHELD_MULTI_BRIDGE
    report = dc.validate_api_data_contract(
        {"crossPositionBridges": {"signalsIdpCrosswalk": summary}}
    )
    assert f"signals_idp_crosswalk_fail_closed:{fx.WITHHELD_MULTI_BRIDGE}" in report["warnings"]


def test_reference_withheld_fails_closed():
    rows = _rows()
    ladder = _ladder(rows)
    votes = dc._coverage_aligned_family_votes(
        _eligible(rows, "DB"),
        rows,
        position_group="DB",
        bridge_ladder=ladder,
        reference_withheld=True,
    )
    assert {v.withheld_reason for v in votes.values()} == {fx.WITHHELD_REFERENCE}


@dataclass
class _Sub:
    freshness: float


@dataclass
class _SW:
    measured: bool
    health_factor: float
    coverage_factor: float
    subsets: dict = field(default_factory=dict)

    def subset_for(self, is_pick):
        return self.subsets.get("players")


def test_the_reference_is_withheld_only_when_its_idp_weight_is_zero_and_applied():
    rows = _rows()
    ladder = _ladder(rows)
    assess = [_Assess(_Desc("bridge0", ("b",), ("b",)), _Cap(len(rows)))]
    zero = {"b": _SW(True, 1.0, 1.0, {"players": _Sub(0.0)})}
    live = {"b": _SW(True, 1.0, 1.0, {"players": _Sub(0.4)})}
    assert dc._family_reference_withheld(ladder, assess, zero, freshness_applied=True)
    assert not dc._family_reference_withheld(ladder, assess, live, freshness_applied=True)
    assert not dc._family_reference_withheld(ladder, assess, zero, freshness_applied=False)
    assert not dc._family_reference_withheld(ladder, assess, {}, freshness_applied=True)
    assert dc._family_level_source(ladder, assess) == "b"


def test_votes_never_route_through_translate_position_rank():
    """Fractional tie means are priced as-is: no rounding translator on F's path."""
    for fn in (dc._coverage_aligned_family_votes, fx.coverage_aligned_votes, dc._price_rank_vote):
        assert "translate_position_rank" not in inspect.getsource(fn)


def test_fractional_ranks_price_between_their_neighbours():
    c, s = dc.curve_for_pool(dc.RANK_POOL_SHARED_MARKET)
    kw = dict(hill_c=c, hill_s=s, reference_n=500, deep_tail_ladder=None, row={"assetClass": "idp"})
    lo, _ = dc._price_rank_vote(40, rank_pool="shared_market", **kw)
    mid, _ = dc._price_rank_vote(40.5, rank_pool="shared_market", **kw)
    hi, _ = dc._price_rank_vote(41, rank_pool="shared_market", **kw)
    assert lo > mid > hi


def test_deep_tail_band_is_priced_by_the_same_helper():
    from src.canonical import deep_tail_native as dtn

    ladder = dtn.build_native_ladder([(r, 2000.0 - r) for r in range(400, 905, 5)])
    c, s = dc.curve_for_pool(dc.RANK_POOL_SHARED_MARKET)
    value, stamp = dc._price_rank_vote(
        700.0,
        hill_c=c,
        hill_s=s,
        reference_n=500,
        deep_tail_ladder=ladder,
        row={"assetClass": "idp"},
        rank_pool="shared_market",
    )
    assert stamp is not None and value == pytest.approx(stamp["nativeValue"])
    # Offense rows, other pools and in-curve ranks keep the Hill price.
    for row, pool, rank in (
        ({"assetClass": "offense"}, "shared_market", 700.0),
        ({"assetClass": "idp"}, "idp", 700.0),
        ({"assetClass": "idp"}, "shared_market", 120.0),
    ):
        assert (
            dc._price_rank_vote(
                rank,
                hill_c=c,
                hill_s=s,
                reference_n=500,
                deep_tail_ladder=ladder,
                row=row,
                rank_pool=pool,
            )[1]
            is None
        )


def test_one_pricing_helper_no_inline_shadow_copy():
    """``wouldContribute`` is written with a real number in exactly ONE place,
    the deferred loop that calls ``_price_rank_vote`` — never by an inline Hill
    copy inside Phase 1 (the copy that bypassed the deep-tail challenger)."""
    tree = ast.parse(inspect.getsource(dc._compute_unified_rankings))
    writes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.slice, ast.Constant)
                    and target.slice.value == "wouldContribute"
                ):
                    writes.append(node)
    assert len(writes) == 1
    # ...and that one write sits in the loop that calls the shared helper.
    enclosing = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.For) and any(w is writes[0] for w in ast.walk(n))
    ]
    assert enclosing and "_price_rank_vote(" in ast.unparse(enclosing[-1])
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_price_rank_vote"
    ]
    assert len(calls) == 2  # the vote path and the shadow pass — nothing else
    assert "percentile_to_value(_p" not in inspect.getsource(dc._compute_unified_rankings)


def test_no_fabricated_cross_family_order():
    """The crosswalk is computed per family board; nothing in it can compare
    a DL with an LB.  Each family's votes are drawn only from its own slots."""
    rows = _rows()
    ladder = _ladder(rows)
    for family in ("DL", "LB", "DB"):
        votes = dc._coverage_aligned_family_votes(
            _eligible(rows, family),
            rows,
            position_group=family,
            bridge_ladder=ladder,
            reference_withheld=False,
        )
        assert {v.rank for v in votes.values()} <= {float(c) for c in ladder.family_ladder(family)}


def test_bridge_ladder_dataclass_keeps_family_slots_off_equality_and_repr():
    a = BridgeLadder(
        ladder=(1,), contributors=("x",), reference_depth=1, family_slots={1: ("DL", 0)}
    )
    b = BridgeLadder(ladder=(1,), contributors=("x",), reference_depth=1)
    assert a == b and "family_slots" not in repr(a)
