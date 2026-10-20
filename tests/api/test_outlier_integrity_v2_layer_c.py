"""Outlier integrity v2, Layer C (legitimate disagreement) and its wiring.

Preregistration: ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §3.3
(rule), §3.4 (Layer D: the confidence owner is unchanged), §9 (correctness
properties), architecture §9 (transparency). Synthetic rows only (Stage 1):
no R_REGRESSION_PIN, V_HELDOUT or I_INDEPENDENT board is read here.

Every test that names a §9 property says which one.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import random
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.api import source_integrity as si
from tests.api.test_source_integrity import (
    ALL_ON,
    META,
    _build,
    _csvs,
    _rows,
)

REPO = Path(__file__).resolve().parents[2]
OFF = op.scope_curve("offense")
IDP = op.scope_curve("idp")


def value_at_rank(rank: float, curve=OFF) -> float:
    """The Hill value whose Layer C coordinate is ``ln(10 + rank)``."""
    c, s = curve
    p = rank / op.REFERENCE_N
    return 9999.0 / (1.0 + (p / c) ** s)


def providers(mapping):
    return lambda k: mapping.get(k, k)


def assess(votes, *, prov=None, fam=None, curve=OFF, **kw):
    pairs = [(k, value_at_rank(r, curve)) for k, r in votes]
    return op.assess_row_layer_c(
        pairs,
        curve=curve,
        provider_of=providers(prov or {}),
        family_of=providers(fam or prov or {}),
        **kw,
    )


# ── the rule ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("curve", [OFF, IDP], ids=["offense", "idp"])
def test_owner_example_keeps_draft_sharks(curve):
    """§9 property 1: IDPTC 5,000 / FantasyPros 5,100 / DLF 5,000 / Draft
    Sharks 3,000 -- every observation valid, so Draft Sharks keeps its vote."""
    pairs = [("idpTradeCalc", 5000.0), ("fantasyProsIdp", 5100.0), ("dlfIdp", 5000.0)]
    pairs.append(("draftSharksIdp", 3000.0))
    v = op.assess_row_layer_c(pairs, curve=curve, provider_of=str, family_of=str)
    assert v.dropped == ()
    assert set(v.kept) == {k for k, _ in pairs}


@pytest.mark.parametrize("curve", [OFF, IDP], ids=["offense", "idp"])
@pytest.mark.parametrize("n_agree", [2, 3])
def test_agreeing_providers_plus_one_dissent_is_kept_inside_tau(curve, n_agree):
    """§9 property 1: two / three agree, one dissents by 4x in implied rank
    (far beyond the incumbent's MAD band, inside tau_C): kept, stamped
    ``kept_dissent``."""
    votes = [(f"a{i}", 40 + i) for i in range(n_agree)] + [("dissent", 170)]
    v = assess(votes, curve=curve)
    assert v.dropped == ()
    assert v.dissent == {"dissent": op.KEPT_DISSENT}


@pytest.mark.parametrize("curve", [OFF, IDP], ids=["offense", "idp"])
def test_gross_uncorroborated_cold_start_tail_is_removed(curve):
    """A x20-style tail (rank 40 -> 900) with a corroborated reference, no
    history, not dominant: removed as ``extreme_uncorroborated_tail``."""
    v = assess([("a", 40), ("b", 42), ("c", 45), ("bad", 900)], curve=curve)
    assert v.dropped == ("bad",)
    assert v.reasons == {"bad": op.REASON_TAIL}
    assert "bad" not in v.dissent
    assert v.details["bad"]["reference"]


def test_four_materially_different_opinions_are_all_kept():
    """§9 property 2: no two other providers within ln 2 of each other means
    no corroborated reference -- nothing is dropped however far apart."""
    v = assess([("a", 10), ("b", 60), ("c", 400), ("d", 3000)])
    assert v.dropped == ()
    assert set(v.kept_because.values()) <= {op.C_KEPT_NO_REFERENCE}


@pytest.mark.parametrize("n", [1, 2])
def test_one_or_two_providers_abstain(n):
    """§9 property 3: below three providers Layer C cannot drop anything."""
    votes = [("a", 40), ("b", 4000)][:n]
    assert assess(votes).dropped == ()
    # Two sources of ONE provider plus a far vote are still two providers.
    v = assess(
        [("ktcCrowd", 40), ("ktcTrades", 41), ("far", 4000)],
        prov={"ktcCrowd": "ktc", "ktcTrades": "ktc"},
    )
    assert v.dropped == ()
    assert v.kept_because.get("far") in (op.C_KEPT_FEW_PROVIDERS, op.C_KEPT_NO_REFERENCE)


def test_tau_c_is_never_below_ln4_and_defaults_to_ln6():
    assert op.effective_tau_c_big(None) == pytest.approx(math.log(6))
    assert op.effective_tau_c_big(math.log(2)) == pytest.approx(math.log(4))
    assert op.effective_tau_c_big(math.log(5)) == pytest.approx(math.log(5))
    # A vote 5x away (in 10+rank) is a drop at ln 4, kept at the provisional ln 6.
    votes = [("a", 50), ("b", 52), ("bad", 5 * 60 - 10 + 5)]
    assert assess(votes, tau_c_big=math.log(4)).dropped == ("bad",)
    assert assess(votes).dropped == ()


def test_identical_synthetic_values_from_different_rank_boards_narrow_nothing():
    """§9 property 4 (+ INJ-DUP): several rank boards landing on the same
    translated value add no band -- the kept set of every other vote can only
    grow, and numerical similarity never merges providers."""
    base = [("a", 40), ("b", 120), ("c", 400)]
    v0 = assess(base)
    for n_dup in (1, 2, 4):
        dups = [(f"dup{i}", 40) for i in range(n_dup)]
        v = assess(base + dups)
        assert set(v0.kept) <= set(v.kept)
        # Each duplicate is still its own provider (no merge by similarity).
        assert {f"dup{i}" for i in range(n_dup)} <= set(v.kept)


def test_translated_vote_and_its_backbone_are_not_a_corroborated_reference():
    """§3.3 guard 2: FantasyPros IDP translated onto IDPTC's ladder and IDPTC
    itself agreeing is one lineage, not two independent providers."""
    votes = [("idpTradeCalc", 40), ("fantasyProsIdp", 40), ("draftSharksIdp", 900)]

    def linked(a, b):
        return a == "fantasyProsIdp" and b == "idpTradeCalc"

    assert assess(votes, curve=IDP, linked=linked).dropped == ()
    assert assess(votes, curve=IDP).dropped == ("draftSharksIdp",)
    # Two translated votes of DIFFERENT providers are independent ordinals.
    votes2 = [("fantasyProsIdp", 40), ("dlfIdp", 41), ("draftSharksIdp", 900)]
    assert assess(votes2, curve=IDP, linked=linked).dropped == ("draftSharksIdp",)


def test_persistence_confirmed_contrarian_is_kept():
    """§9 property 7 / guard 4: a source that has said this before (two
    accepted observations within tau_c) is a view, not a tail."""
    votes = [("a", 40), ("b", 42), ("contrarian", 900)]
    v = assess(votes, persistence_confirmed=lambda k, _u: k == "contrarian")
    assert v.dropped == ()
    assert v.kept_because == {"contrarian": op.C_KEPT_PERSISTENT}
    assert v.dissent == {"contrarian": op.KEPT_DISSENT}


def test_dominant_family_is_kept():
    """Guard 5: a family holding half the capped weight is never removed."""
    votes = [("a", 40), ("b", 42), ("heavy", 900)]
    v = assess(votes, weights={"a": 0.5, "b": 0.5, "heavy": 1.0})
    assert v.dropped == ()
    assert v.kept_because == {"heavy": op.C_KEPT_DOMINANT}


def test_two_providers_always_survive():
    """Guard 6: whatever is dropped, two providers remain on the row."""
    rng = random.Random(20261020)
    for _ in range(400):
        n = rng.randint(3, 7)
        votes = [(f"s{i}", rng.choice([5, 40, 41, 300, 900, 4000])) for i in range(n)]
        v = assess(votes)
        assert len({k for k in v.kept}) >= 2


def test_an_invalid_source_agreeing_with_another_is_the_named_residual():
    """§9 property 6: two sources wrong in the SAME way corroborate each other;
    Layer C cannot tell that from shared opinion. Documented miss: only an A or
    B signature catches it (asserted, never faked)."""
    v = assess([("good1", 40), ("good2", 42), ("bad1", 900), ("bad2", 905)])
    assert v.dropped == ()


def test_family_caps_are_consumed_not_changed():
    """§9 property 11: Layer C reads the caller's family-capped weights; the
    cap owner's output for the same surviving set is unchanged."""
    w = {"dlfSf": 1.0, "dlfRookieSf": 1.0, "ktcCrowdSfTep": 1.0}
    before = dc.cap_family_weights(dict(w), base=w)
    assess([("dlfSf", 40), ("dlfRookieSf", 41), ("ktcCrowdSfTep", 42)], weights=before[0])
    assert dc.cap_family_weights(dict(w), base=w) == before


def test_order_independence_over_every_permutation():
    """§9 property 12: permuting the vote order never changes a decision."""
    votes = [("a", 40), ("b", 42), ("c", 300), ("bad", 900), ("e", 45)]
    ref = assess(votes)
    for perm in itertools.permutations(votes):
        v = assess(list(perm))
        assert set(v.dropped) == set(ref.dropped)
        assert v.dissent == ref.dissent
        assert v.kept_because == ref.kept_because


def test_monotonicity_adding_a_vote_never_turns_a_retain_into_a_drop():
    """§9 property 14 (restated): in a row that already meets guards 1, 2 and
    5 for a vote, adding ANY vote never turns that vote's retain into a drop."""
    rng = random.Random(2033)
    ranks = [3, 20, 40, 42, 45, 80, 150, 300, 600, 900, 2000, 5000]
    checked = 0
    for _ in range(3000):
        n = rng.randint(3, 6)
        votes = [(f"s{i}", rng.choice(ranks)) for i in range(n)]
        before = assess(votes)
        new = ("new", rng.choice(ranks))
        after = assess(votes + [new])
        for o in before.kept:
            if o not in before.details:
                continue
            # Guards 1, 2 and 5 held for o (otherwise the property is not
            # claimed: adding a vote can newly satisfy one of them).
            if before.kept_because.get(o) in (
                op.C_KEPT_FEW_PROVIDERS,
                op.C_KEPT_NO_REFERENCE,
                op.C_KEPT_DOMINANT,
            ):
                continue
            checked += 1
            assert o in after.kept, (votes, new, o)
    assert checked > 1000


def test_missing_coordinate_is_never_assessed_or_dropped():
    """§9 property 15: a non-positive vote has no coordinate; it is never a 0."""
    pairs = [("a", 5000.0), ("b", 5050.0), ("c", 4900.0), ("zero", 0.0), ("neg", -3.0)]
    v = op.assess_row_layer_c(pairs, curve=OFF, provider_of=str, family_of=str)
    assert v.dropped == ()
    assert "zero" not in v.details and "neg" not in v.details


def test_v1_is_untouched_and_still_selectable():
    """V1 (``outlier-corroborated-v1``) keeps its constants and verdicts."""
    assert op.POLICY_VERSION == "outlier-corroborated-v1"
    assert op.constants()["grossRankFactor"] == 4.0
    v = op.assess_row(
        [("a", 5000.0), ("b", 5100.0), ("c", 5000.0), ("d", 3000.0)],
        curve=OFF,
        family_of=str,
    )
    assert v.dropped == ()


# ── history: persistence (guard 4) and C11 acceptance ──────────────────


def test_persistence_uses_the_last_two_accepted_observations():
    th = si.IntegrityThresholds()
    h = si.IntegrityHistory(boards=3, observations={"src|player:1": (3.0, 5.0, 5.1)})
    assert si.persistence_confirmed(h, th, "src", "player:1", 5.05)
    assert not si.persistence_confirmed(h, th, "src", "player:1", 3.0)
    assert not si.persistence_confirmed(None, th, "src", "player:1", 5.0)
    assert not si.persistence_confirmed(h, th, "src", None, 5.0)
    one = si.IntegrityHistory(boards=1, observations={"src|player:1": (5.0,)})
    assert not si.persistence_confirmed(one, th, "src", "player:1", 5.0)


def test_a_layer_c_drop_is_still_an_accepted_observation():
    """DEVIATIONS C11: the history lane accumulates a contrarian's view even on
    boards where Layer C set it aside, so persistence can confirm it."""
    rec = {
        "asOf": "2026-08-20T00:00:00+00:00",
        "hashes": {"s": "h1"},
        "observations": {
            "s|player:1": {"u": 6.5, "status": si.STATUS_REJECTED_TAIL, "team": None},
            "s|player:2": {"u": 4.0, "status": si.STATUS_HELD, "team": None},
        },
    }
    h = si.advance(None, rec)
    assert h.observations["s|player:1"] == (6.5,)
    assert "s|player:2" not in h.observations


# ── pipeline wiring (synthetic payload through build_api_data_contract) ──


def _far_fantasycalc_csvs():
    """fantasyCalc moves one top-10 player to the bottom of its own board."""
    csvs = _csvs(META)
    lines = csvs["fantasyCalc.csv"].splitlines()
    head, body = lines[0], lines[1:]
    body = [ln for ln in body if not ln.startswith("Off Vet 005,")] + ["Off Vet 005,1,999"]
    csvs["fantasyCalc.csv"] = "\n".join([head] + body) + "\n"
    return csvs


@pytest.fixture(scope="module")
def far_on():
    return _build(ALL_ON, csvs=_far_fantasycalc_csvs())


def test_pipeline_layer_c_drop_is_stamped_as_a_rule_never_as_corruption(far_on):
    """§9 property 17: the dropped vote carries exactly one primary reason in
    the "rejected by a justified integrity rule" category, never identity /
    format / normalization / broken feed; the incumbent's ``hampelDropped`` /
    ``droppedSources`` shape is kept so every existing consumer still reads it."""
    row = _rows(far_on)["Off Vet 005"]
    meta = row["sourceRankMeta"]["fantasyCalc"]
    assert meta["integrity"]["status"] == si.STATUS_REJECTED_TAIL
    assert meta["integrity"]["primaryReason"] == si.REASON_TAIL
    assert meta["integrity"]["category"] == si.CATEGORY_RULE
    assert meta["hampelDropped"] is True
    assert "fantasyCalc" in row["droppedSources"]
    assert row["outlierIntegrityReasons"]["fantasyCalc"] == si.REASON_TAIL
    lc = far_on["sourceIntegrity"]["layerC"]
    assert lc["bySource"]["fantasyCalc"]["dropped"] >= 1
    assert lc["constants"]["tauC"] == pytest.approx(math.log(6), abs=1e-6)


def test_pipeline_never_maps_a_vote_that_passed_a_and_b_to_an_invalid_category(far_on):
    """§9 property 17, over every observation of the board."""
    invalid = {
        si.CATEGORY_IDENTITY,
        si.CATEGORY_FORMAT,
        si.CATEGORY_NORMALIZATION,
        si.CATEGORY_BROKEN_FEED,
    }
    seen = 0
    for row in far_on["playersArray"]:
        for meta in (row.get("sourceRankMeta") or {}).values():
            integ = meta.get("integrity") or {}
            if integ.get("status") in (si.STATUS_VOTING, si.STATUS_REJECTED_TAIL):
                seen += 1
                assert integ.get("category") not in invalid
                assert si.reason_category(integ.get("primaryReason")) == integ.get("category")
            if integ.get("primaryReason") == si.REASON_KEPT_DISSENT:
                assert integ["status"] == si.STATUS_VOTING
                assert integ["category"] == si.CATEGORY_DISSENT
                assert meta.get("contributedToBlend") is not False
                assert not meta.get("hampelDropped")
    assert seen > 100


def test_pipeline_voting_categories_census(far_on):
    """Directive §10: per-source category counts read from the stamps plus the
    source-level state from ``sourceVotingEligibility``."""
    census = far_on["sourceIntegrity"]["votingCategories"]
    assert census["categories"][0] == si.CATEGORY_VOTING
    fc = census["sources"]["fantasyCalc"]
    assert fc["rows"].get(si.CATEGORY_RULE, 0) >= 1
    assert fc["rows"].get(si.CATEGORY_VOTING, 0) > 50
    assert fc["sourceStatus"] == "voting"
    total = sum(census["totals"].values())
    obs = 0
    for r in far_on["playersArray"]:
        meta = r.get("sourceRankMeta") or {}
        obs += len(meta)
        obs += sum(
            1
            for k, v in (r.get("sourceIntegrity") or {}).items()
            if k not in meta and isinstance(v, dict) and v.get("status")
        )
    assert total == obs


def test_census_counts_pre_ranking_refusals_from_the_row_block():
    """A Layer A refusal never reaches ``sourceRankMeta``; the census still
    reports it, in the identity category."""
    rows = [
        {
            "sourceRankMeta": {"a": {"integrity": {"status": "voting", "primaryReason": "voting"}}},
            "sourceIntegrity": {
                "b": si.integrity_stamp(
                    si.STATUS_REFUSED, ["identity_contradicted:position_group"]
                ),
                "a": {"identity": {"verdict": "VERIFIED"}},
            },
        }
    ]
    census = si.voting_category_census(rows, {"c": {"status": "policy_held", "reason": "x"}})
    assert census["sources"]["b"]["rows"] == {si.CATEGORY_IDENTITY: 1}
    assert census["sources"]["a"]["rows"] == {si.CATEGORY_VOTING: 1}
    assert census["sources"]["c"]["sourceCategory"] == si.CATEGORY_HELD
    assert census["sources"]["c"]["rows"] == {}


def test_pipeline_v2_never_asks_the_incumbent_statistic(monkeypatch):
    """One dispatcher: with V2 on, no row, replay or alt panel reaches the
    incumbent ``_hampel_filter_per_player``; with it off the incumbent owns
    the build."""
    calls = {"incumbent": 0}
    real_hampel = dc._hampel_filter_per_player

    def counting_hampel(*a, **k):
        calls["incumbent"] += 1
        return real_hampel(*a, **k)

    monkeypatch.setattr(dc, "_hampel_filter_per_player", counting_hampel)
    _build(ALL_ON, csvs=_far_fantasycalc_csvs())
    assert calls["incumbent"] == 0
    _build((), csvs=_far_fantasycalc_csvs())
    assert calls["incumbent"] > 0


def test_lost_evidence_seats_are_exact_under_the_layer_c_replay():
    """§3.4: the B11 seats ask Layer C of the observed panel (voting +
    withheld) -- the same context, so voting and confidence seats agree.

    * a withheld source Layer C would have KEPT is a lost voting head (seated);
    * a withheld source Layer C itself rejects on the observed panel was never
      evidence, so it is not a new loss (not seated).
    """
    ctx = op.LayerCContext(curve=OFF, provider_of=str, family_of=str)
    voting = [("a", value_at_rank(40)), ("b", value_at_rank(42)), ("c", value_at_rank(45))]
    kept_withheld = [("w", value_at_rank(60))]
    tail_withheld = [("t", value_at_rank(2000))]
    seats = dc._lost_evidence_seats(
        voting_pairs=voting,
        withheld_pairs=kept_withheld + tail_withheld,
        dropped_now=[],
        outlier_test_applies=True,
        replay=ctx.replay(),
    )
    assert seats == ["w"]


def test_pipeline_two_way_alt_center_routes_through_layer_c(monkeypatch):
    """#1817's ``_two_way_alt_center`` is the second call site of the filter:
    with V2 on it receives the Layer C dispatcher, with V2 off none."""
    seen = []
    real = dc._two_way_alt_center

    def spy(votes, **kw):
        seen.append(kw.get("outlier_filter"))
        return real(votes, **kw)

    monkeypatch.setattr(dc, "_two_way_alt_center", spy)

    def add_hunter(payload):
        payload["players"]["Travis Hunter"] = {
            "position": "WR",
            "team": "JAX",
            "age": 23,
            "_sleeperId": "4999",
            "_yearsExp": 1,
            "_canonicalSiteValues": {"idpTradeCalc": 6000, "ktcCrowdSfTep": 6000},
            "idpTradeCalc": 6000,
            "ktcCrowdSfTep": 6000,
        }

    _build(ALL_ON, mutate=add_hunter)
    on_filters = list(seen)
    seen.clear()
    _build((), mutate=add_hunter)
    assert on_filters, "Travis Hunter's alt-family center was never asked"
    assert all(f is not None for f in on_filters)
    assert seen and all(f is None for f in seen)
    # The filter itself: a gross cold-start tail on an alt panel is removed.
    votes = [
        ("idpTradeCalc", value_at_rank(40, IDP), 1.0),
        ("draftSharksIdp", value_at_rank(42, IDP), 1.0),
        ("fantasyProsIdp", value_at_rank(44, IDP), 1.0),
        ("idpShow", value_at_rank(900, IDP), 1.0),
    ]
    center, surviving, dropped = real(
        votes,
        hierarchical=True,
        anchor_keys={"idpTradeCalc"},
        family_cap=True,
        base_weights={k: 1.0 for k, _v, _w in votes},
        outlier_filter=lambda v: list(
            op.LayerCContext(curve=IDP, provider_of=str, family_of=str)
            .assess([(k, x) for k, x, _w in v])
            .dropped
        ),
    )
    assert dropped == ["idpShow"] and "idpShow" not in surviving and center


# ── Layer D: the confidence owner is unchanged ──────────────────────────


def test_layer_d_confidence_owner_and_gate_are_byte_identical_to_main():
    """§3.4: ``src/api/confidence.py`` and ``config/confidence/gate_v1.json``
    are not changed by V2 (no second confidence engine). Pinned against the
    files' git blobs at the merge base with ``main``."""
    import subprocess

    for path in ("src/api/confidence.py", "config/confidence/gate_v1.json"):
        base = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            cwd=REPO,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if not base:
            pytest.skip("no origin/main in this checkout")
        blob_main = subprocess.run(
            ["git", "rev-parse", f"{base}:{path}"], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        blob_here = subprocess.run(
            ["git", "hash-object", path], cwd=REPO, capture_output=True, text=True
        ).stdout.strip()
        assert blob_main == blob_here, path


def test_layer_d_dropped_family_stays_eligible_coverage_can_only_fall(far_on):
    """§3.4: a Layer C drop behaves like today's filter drop -- the family is
    not voting evidence on the row, its confidence cannot rise, and the row's
    confidence is decided by the unchanged gate (``confidenceAxes`` present)."""
    row = _rows(far_on)["Off Vet 005"]
    clean = _rows(_build(ALL_ON))["Off Vet 005"]
    assert row.get("confidenceBucket") in ("high", "medium", "low")
    order = {"low": 0, "medium": 1, "high": 2}
    assert order[row["confidenceBucket"]] <= order[clean["confidenceBucket"]]
    assert "fantasyCalc" not in (row.get("effectiveSourceRanks") or {}) or row["sourceRankMeta"][
        "fantasyCalc"
    ].get("hampelDropped")


# ── transparency: frontend label map parity ─────────────────────────────


def test_frontend_integrity_labels_cover_every_category_and_never_call_dissent_invalid():
    """Directive §10: the one frontend label map (source-voting-status.js)
    labels every category the backend can emit, and the dissent label never
    reads as an error."""
    js = (REPO / "frontend" / "lib" / "source-voting-status.js").read_text()
    for cat in (
        si.CATEGORY_VOTING,
        si.CATEGORY_DISSENT,
        si.CATEGORY_IDENTITY,
        si.CATEGORY_FORMAT,
        si.CATEGORY_NORMALIZATION,
        si.CATEGORY_STALE,
        si.CATEGORY_BROKEN_FEED,
        si.CATEGORY_MISSING,
        si.CATEGORY_HELD,
        si.CATEGORY_RULE,
    ):
        assert f"{cat}:" in js, cat
    for code in si.REASON_CATEGORY:
        assert f'"{code}"' in js or f"{code}:" in js, code
    start = js.index("valid_but_disagreeing:")
    label = js[start : js.index("\n", start)].lower()
    for bad in ("invalid", "corrupt", "error", "rejected", "not voting"):
        assert bad not in label


def test_v2_stamp_digest_is_reproducible(far_on):
    """§9 property 13 on the Layer C stamps specifically."""
    again = _build(ALL_ON, csvs=_far_fantasycalc_csvs())

    def digest(c):
        rows = [
            (r["displayName"], r.get("outlierIntegrityReasons"), r.get("droppedSources"))
            for r in c["playersArray"]
        ]
        return hashlib.sha256(
            json.dumps([rows, c["sourceIntegrity"]["layerC"]], sort_keys=True).encode()
        ).hexdigest()

    assert digest(far_on) == digest(again)
