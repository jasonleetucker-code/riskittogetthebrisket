"""Sparse-evidence estimator (Batch 3 Unit E, flag ``sparse_evidence_estimator``).

Pure-logic tests over synthetic rows through the REAL ``_compute_unified_rankings``
plus the pure module, then whole-board invariants on the newest complete
archived scrape (no live board, no network). Preregistration:
``docs/valuation/evidence/sparse-evidence-2026-10-01/PREREGISTRATION.md``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.api import sparse_evidence as se
from src.api import value_replay as vr
from src.sources.freshness import STYLE_SNAPSHOT
from tests.archive_fixtures import newest_complete_raw_payload

# ── synthetic fixtures ───────────────────────────────────────────────


def _row(name: str, position: str, *, rookie: bool = False, **sites: Any) -> dict[str, Any]:
    asset_class = "idp" if position in ("DL", "LB", "DB") else "offense"
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "assetClass": asset_class,
        "canonicalSiteValues": dict(sites),
        "values": {"overall": 0, "rawComposite": None, "finalAdjusted": None, "displayValue": None},
        "sourceCount": 0,
        "sourcePresence": {},
        "rookie": rookie,
    }


class _Sub:
    def __init__(self, freshness: float, state: str) -> None:
        self.freshness = freshness
        self.state = state
        self.style = STYLE_SNAPSHOT


class _Weighting:
    """Minimal stand-in for ``src.sources.freshness.SourceWeighting``."""

    def __init__(
        self,
        key: str,
        *,
        freshness: float = 1.0,
        state: str = "ON_SCHEDULE",
        health: str = "HEALTHY",
        coverage: float | None = 1.0,
        measured: bool = True,
    ) -> None:
        self.source_key = key
        self.measured = measured
        self.health_state = health
        self.health_factor = {"HEALTHY": 1.0, "DEGRADED": 0.5, "FAILED": 0.0}[health]
        self.coverage = coverage
        self.coverage_factor = 1.0 if coverage is None else min(1.0, coverage / 0.8)
        self._sub = _Sub(freshness, state)

    def subset_for(self, is_pick: bool) -> _Sub:
        return self._sub

    def factor_for_row(self, **_kw: Any) -> tuple[float, float]:
        return self._sub.freshness, 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"sourceKey": self.source_key, "measured": self.measured}


def _index(*names_by_source: tuple[str, list[str]]) -> dict[str, dict[str, Any]]:
    """A CSV name index shaped like ``_enrich_from_source_csvs``'s."""
    out: dict[str, dict[str, Any]] = {}
    for key, names in names_by_source:
        out[key] = {f"{dc._canonical_match_key(n)}::*": {"displayName": n} for n in names}
    return out


def _board() -> list[dict[str, Any]]:
    # Anchor pins every value-direct site maximum at 9999, so each
    # contribution below is exactly its raw number.
    return [
        _row("Anchor QB", "QB", ktcCrowdSfTep=9999, ktcTradesSfTep=9999, idpTradeCalc=9999),
        # The deepest WR the two absent families published: their WR cutoff.
        _row("Floor WR", "WR", ktcCrowdSfTep=2000, ktcTradesSfTep=2000, idpTradeCalc=2000),
        _row("Solo WR", "WR", ktcCrowdSfTep=5000),
    ]


_LISTED = [
    ("ktcCrowdSfTep", ["Anchor QB", "Floor WR", "Solo WR"]),
    ("ktcTradesSfTep", ["Anchor QB", "Floor WR"]),
    ("idpTradeCalc", ["Anchor QB", "Floor WR"]),
]


def _weights(**overrides: _Weighting) -> dict[str, _Weighting]:
    base = {k: _Weighting(k) for k in ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc")}
    base.update(overrides)
    return base


def _run(rows, *, weighting=None, csv_index=None, on=True):
    with vr._flag("sparse_evidence_estimator", on):
        dc._compute_unified_rankings(
            rows,
            {},
            csv_index=csv_index if csv_index is not None else _index(*_LISTED),
            source_weighting=weighting if weighting is not None else _weights(),
        )
    return {r["canonicalName"]: r for r in rows}


# ── the flag ─────────────────────────────────────────────────────────


def test_flag_is_registered_default_off_and_live():
    assert feature_flags.is_enabled("sparse_evidence_estimator") is False
    assert feature_flags.gate_status("sparse_evidence_estimator") == feature_flags.LIVE


def test_off_is_the_incumbent_haircut_and_never_calls_the_estimator(monkeypatch):
    def _refuse(*_a, **_k):
        raise AssertionError("estimator called with the flag off")

    monkeypatch.setattr(dc, "_apply_sparse_evidence_estimator", _refuse)
    got = _run(_board(), on=False)
    assert got["Solo WR"]["rankDerivedValue"] == 1500  # 5000 x 0.30
    assert got["Solo WR"]["singleSourceValuePenaltyApplied"] is True
    assert not any("sparseEvidence" in r for r in got.values())


# ── the method through the real pipeline ─────────────────────────────


def test_healthy_absent_families_bound_the_value_at_their_cutoff():
    got = _run(_board())
    solo = got["Solo WR"]
    block = solo["sparseEvidence"]
    # Two absent families (ktcTrades, idpTradeCalc), each with a WR cutoff of
    # 2000 < 5000: both bind.  The pipeline's n=3 blend of [5000, 2000, 2000]
    # at equal weight = (mean 3000 + median 2000) / 2 = 2500.
    assert block["state"] == se.STATE_CENSOR_BOUNDED
    assert solo["rankDerivedValue"] == 2500
    assert block["centralEstimate"] == 2500
    assert block["observedValue"] == 5000
    assert sorted(c["family"] for c in block["censoredFamiliesUsed"]) == [
        "idpTradeCalc",
        "ktcTrades",
    ]
    assert block["sensitivityInterval"] == {
        "low": 2500,
        "high": 5000,
        "label": "sensitivity_uncalibrated",
        "note": block["sensitivityInterval"]["note"],
    }
    assert block["identifiedSet"]["lower"] is None
    assert block["independentFamilyCount"] == 1
    assert not solo.get("singleSourceValuePenaltyApplied")
    assert solo["_blendedValueUncapped"] == 2500
    # Rows with two or more present families are untouched.
    assert got["Floor WR"]["rankDerivedValue"] == 2000
    assert "sparseEvidence" not in got["Floor WR"]


def test_confidence_comes_from_the_owner_and_is_copied_not_decided():
    got = _run(_board())
    solo = got["Solo WR"]
    conf = solo["sparseEvidence"]["confidence"]
    assert conf["owner"] == "src/api/confidence.py"
    assert conf["bucket"] == solo["confidenceBucket"]
    assert conf["label"] == solo["confidenceLabel"]
    # One family cannot exceed LOW under the owner's gate.
    assert solo["confidenceBucket"] in ("low", "none")


def test_the_4600_to_1380_trap_through_the_real_pipeline(monkeypatch):
    """Three weak observations (3000/3100/3200 at weight 0.03) and one fresh 4600.

    A naive weighted filter drops the three weak ones; the incumbent then hands
    the fresh 4600 to the 0.30 rule: 1380. The estimator keeps the fresh
    observation as central evidence: the three dropped ones LISTED the player,
    so they are not absences and bound nothing.
    """
    monkeypatch.setattr(
        dc, "_VALUE_BASED_SOURCES", frozenset(dc._VALUE_BASED_SOURCES | {"dynastyDaddySf"})
    )

    def naive_weighted_filter(pairs, **_kw):
        pairs = list(pairs)
        if any(k == "ktcCrowdSfTep" and abs(v - 4600) < 1 for k, v in pairs):
            return [(k, v) for k, v in pairs if k == "ktcCrowdSfTep"], [
                k for k, _ in pairs if k != "ktcCrowdSfTep"
            ]
        return pairs, []

    monkeypatch.setattr(dc, "_hampel_filter_per_player", naive_weighted_filter)

    def board():
        return [
            _row(
                "Anchor QB",
                "QB",
                ktcCrowdSfTep=9999,
                ktcTradesSfTep=9999,
                idpTradeCalc=9999,
                dynastyDaddySf=9999,
            ),
            _row(
                "Trap WR",
                "WR",
                ktcCrowdSfTep=4600,
                ktcTradesSfTep=3000,
                idpTradeCalc=3100,
                dynastyDaddySf=3200,
            ),
        ]

    weak = {
        k: _Weighting(k, freshness=0.03, state="SEVERELY_STALE")
        for k in ("ktcTradesSfTep", "idpTradeCalc", "dynastyDaddySf")
    }
    weighting = {"ktcCrowdSfTep": _Weighting("ktcCrowdSfTep"), **weak}
    names = ["Anchor QB", "Trap WR"]
    index = _index(*[(k, names) for k in weighting])

    off = _run(board(), weighting=weighting, csv_index=index, on=False)
    assert off["Trap WR"]["droppedSources"] == ["ktcTradesSfTep", "idpTradeCalc", "dynastyDaddySf"]
    assert off["Trap WR"]["rankDerivedValue"] == 1380  # the failure, reproduced

    on = _run(board(), weighting=weighting, csv_index=index, on=True)
    assert on["Trap WR"]["rankDerivedValue"] == 4600
    assert on["Trap WR"]["sparseEvidence"]["censoredFamiliesUsed"] == []


# ── censor semantics: what may NEVER become negative evidence ───────


@pytest.mark.parametrize(
    "bad, reason",
    [
        (_Weighting("ktcTradesSfTep", coverage=None), se.REFUSE_COVERAGE),
        (_Weighting("ktcTradesSfTep", coverage=0.5), se.REFUSE_COVERAGE),
        (_Weighting("ktcTradesSfTep", health="FAILED"), se.REFUSE_UNHEALTHY),
        (_Weighting("ktcTradesSfTep", health="DEGRADED"), se.REFUSE_UNHEALTHY),
        (_Weighting("ktcTradesSfTep", freshness=0.5, state="STALE"), se.REFUSE_STALE),
        (_Weighting("ktcTradesSfTep", measured=False), se.REFUSE_UNMEASURED),
    ],
)
def test_unhealthy_unknown_or_stale_boards_produce_no_bound(bad, reason):
    got = _run(_board(), weighting=_weights(ktcTradesSfTep=bad))
    block = got["Solo WR"]["sparseEvidence"]
    assert block["refusedFamilies"]["ktcTrades"] == reason
    assert [c["family"] for c in block["censoredFamiliesUsed"]] == ["idpTradeCalc"]
    # n=2 weighted mean of [5000, 2000] = 3500: one bound, never two.
    assert got["Solo WR"]["rankDerivedValue"] == 3500


def test_missing_dataset_state_produces_no_bound_at_all():
    got = _run(_board(), weighting={"ktcCrowdSfTep": _Weighting("ktcCrowdSfTep")})
    block = got["Solo WR"]["sparseEvidence"]
    assert block["state"] == se.STATE_UNCORROBORATED
    assert got["Solo WR"]["rankDerivedValue"] == 5000


def test_a_name_the_source_published_but_did_not_attach_is_not_an_absence():
    index = _index(
        ("ktcCrowdSfTep", ["Anchor QB", "Floor WR", "Solo WR"]),
        ("ktcTradesSfTep", ["Anchor QB", "Floor WR", "Solo WR"]),
        ("idpTradeCalc", ["Anchor QB", "Floor WR"]),
    )
    got = _run(_board(), csv_index=index)
    block = got["Solo WR"]["sparseEvidence"]
    assert block["refusedFamilies"]["ktcTrades"] == se.REFUSE_NAME_PUBLISHED


def test_no_name_index_means_identity_is_unprovable():
    got = _run(_board(), csv_index={"ktcCrowdSfTep": {"solo wr::*": {}}})
    block = got["Solo WR"]["sparseEvidence"]
    assert block["refusedFamilies"]["ktcTrades"] == se.REFUSE_NAME_INDEX
    assert block["refusedFamilies"]["idpTradeCalc"] == se.REFUSE_NAME_INDEX
    assert got["Solo WR"]["rankDerivedValue"] == 5000


def test_quarantined_or_duplicate_identity_produces_no_bound():
    rows = _board()
    rows[2]["anomalyFlags"] = ["duplicate_canonical_identity"]
    block = _run(rows)["Solo WR"]["sparseEvidence"]
    assert set(block["refusedFamilies"].values()) == {se.REFUSE_IDENTITY}

    # Two board rows share the name: an absence cannot be pinned on either.
    rows = _board() + [_row("Solo WR", "LB", idpTradeCalc=1500)]
    _run(rows)
    solo = next(r for r in rows if r["position"] == "WR" and r["canonicalName"] == "Solo WR")
    assert set(solo["sparseEvidence"]["refusedFamilies"].values()) == {se.REFUSE_IDENTITY}
    assert solo["rankDerivedValue"] == 5000


def test_an_inapplicable_source_is_neither_a_bound_nor_a_refusal():
    weighting = _weights(dlfIdp=_Weighting("dlfIdp"))
    block = _run(_board(), weighting=weighting)["Solo WR"]["sparseEvidence"]
    # dlfIdp ranks IDP only; it could never have listed a WR.  (Its family's
    # offense board dlfSf has no dataset state here, so it is refused as
    # unmeasured -- never bounded.)
    assert "dlf" not in [c["family"] for c in block["censoredFamiliesUsed"]]
    assert block["refusedFamilies"].get("dlf") in (None, se.REFUSE_UNMEASURED)


def test_a_position_the_source_never_ranked_is_not_negative_evidence():
    rows = [
        _row("Anchor QB", "QB", ktcCrowdSfTep=9999, ktcTradesSfTep=9999, idpTradeCalc=9999),
        _row("Solo TE", "TE", ktcCrowdSfTep=5000),
    ]
    index = _index(
        ("ktcCrowdSfTep", ["Anchor QB", "Solo TE"]),
        ("ktcTradesSfTep", ["Anchor QB"]),
        ("idpTradeCalc", ["Anchor QB"]),
    )
    block = _run(rows, csv_index=index)["Solo TE"]["sparseEvidence"]
    assert block["refusedFamilies"]["ktcTrades"] == se.REFUSE_POSITION_UNRANKED
    assert block["refusedFamilies"]["idpTradeCalc"] == se.REFUSE_POSITION_UNRANKED
    assert block["state"] == se.STATE_UNCORROBORATED


# ── pure module: family counting, no invented last place ────────────


def _src(key: str, **kw: Any) -> dict[str, Any]:
    return {"key": key, "scope": "overall_offense", "game_type": "DYNASTY", **kw}


def _bounds(sources, listed=frozenset(), mins=None, status=None, rookie=False):
    family_of = {"a1": "A", "a2": "A", "b": "B", "c": "C", "rk": "R"}
    mins = mins or {("a1", "WR"): 1000.0, ("a2", "WR"): 1500.0, ("b", "WR"): 800.0}
    status = status or {s["key"]: se.SourceStatus(True, None, 1.0) for s in sources}
    return se.family_bounds(
        position="WR",
        is_rookie=rookie,
        listed_families=set(listed),
        sources=sources,
        family_of=family_of,
        status=status,
        min_contribution=mins,
        name_check=lambda _k: None,
        scope_eligible=dc._scope_eligible,
        identity_ok=True,
        family_cap=lambda w: dc.cap_family_weights(w)[0],
    )


def test_absences_count_once_per_family_at_the_loosest_member_bound():
    bounds, _ = _bounds([_src("a1"), _src("a2"), _src("b")])
    assert set(bounds) == {"A", "B"}
    assert bounds["A"].bound == 1500.0  # the loosest witness, never the tightest
    assert bounds["A"].witnesses == ("a1", "a2")


def test_a_family_bound_carries_one_provider_authority():
    # Real registry keys: Fantasy Navigator sits in the KTC Crowd family, so
    # two absent members are ONE censored family at the family cap (1.0, not 2.0).
    srcs = [_src("ktcCrowdSfTep"), _src("fantasyNavigatorSf")]
    bounds, _ = se.family_bounds(
        position="WR",
        is_rookie=False,
        listed_families=set(),
        sources=srcs,
        family_of={k["key"]: dc.correlation_group_for(k["key"]) for k in srcs},
        status={k["key"]: se.SourceStatus(True, None, 1.0) for k in srcs},
        min_contribution={("ktcCrowdSfTep", "WR"): 900.0, ("fantasyNavigatorSf", "WR"): 1100.0},
        name_check=lambda _k: None,
        scope_eligible=dc._scope_eligible,
        identity_ok=True,
        family_cap=lambda w: dc.cap_family_weights(w)[0],
    )
    assert set(bounds) == {"ktcCrowd"}
    assert bounds["ktcCrowd"].bound == 1100.0
    assert bounds["ktcCrowd"].weight == pytest.approx(1.0)


def test_a_listed_family_is_never_censored():
    bounds, refused = _bounds([_src("a1"), _src("a2"), _src("b")], listed={"A"})
    assert set(bounds) == {"B"}
    assert "A" not in refused


def test_rookie_only_and_rookie_excluding_boards():
    srcs = [_src("rk", needs_rookie_translation=True), _src("b", excludes_rookies=True)]
    mins = {("rk", "WR"): 700.0, ("b", "WR"): 800.0}
    bounds, refused = _bounds(srcs, mins=mins, rookie=False)
    assert refused["R"] == se.REFUSE_ROOKIE_ONLY and set(bounds) == {"B"}
    bounds, refused = _bounds(srcs, mins=mins, rookie=True)
    assert refused["B"] == se.REFUSE_EXCLUDES_ROOKIES and set(bounds) == {"R"}


def test_unverified_game_type_produces_no_bound():
    status = se.source_status(
        {"key": "x", "game_type": "UNKNOWN"},
        _Weighting("x"),
        base_weight=1.0,
        freshness_applied=True,
    )
    assert not status.ok and status.reason == se.REFUSE_NOT_DYNASTY


def test_no_invented_last_place_and_no_shrink_toward_zero():
    blend = dc.weighted_count_aware_mean_median_blend
    hi = se.FamilyBound("H", 3000.0, 1.0, ("h",))
    lo = se.FamilyBound("L", 900.0, 1.0, ("l",))
    # A non-binding cutoff says nothing: the observation stands.
    est = se.estimate(1000.0, 1.0, {"H": hi}, blend)
    assert est.central == 1000.0 and est.state == se.STATE_CENSOR_NONBINDING
    assert est.nonbinding == [hi] and est.binding == []
    # A binding cutoff enters AT the cutoff -- never below it, never at zero.
    est = se.estimate(1000.0, 1.0, {"H": hi, "L": lo}, blend)
    assert est.state == se.STATE_CENSOR_BOUNDED
    assert 900.0 <= est.central <= 1000.0
    assert est.central == pytest.approx(950.0)  # n=2 mean of [1000, 900]
    # No witnesses at all: the observation stands, uncorroborated.
    est = se.estimate(1000.0, 1.0, {}, blend)
    assert est.central == 1000.0 and est.state == se.STATE_UNCORROBORATED


def test_the_estimate_is_monotone_in_the_observation():
    blend = dc.weighted_count_aware_mean_median_blend
    bounds = {f: se.FamilyBound(f, b, 1.0, (f,)) for f, b in [("A", 800.0), ("B", 1200.0)]}
    centrals = [se.estimate(x, 1.0, bounds, blend).central for x in range(500, 3000, 50)]
    assert centrals == sorted(centrals)


# ── whole board (newest complete archived scrape) ───────────────────


@pytest.fixture(scope="module")
def boards():
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    raw = json.loads(json.dumps(payload))
    off = vr.build(raw)
    with vr._flag("sparse_evidence_estimator", True):
        on = vr.build(raw)
    return off, on


def _by(contract):
    return {r["displayName"]: r for r in contract["playersArray"] if r.get("displayName")}


def test_board_only_former_haircut_rows_change(boards):
    off, on = boards
    a, b = _by(off), _by(on)
    haircut = {n for n, r in a.items() if r.get("singleSourceValuePenaltyApplied")}
    assert haircut, "archive should exercise the single-family path"
    for name, row in a.items():
        if name in haircut:
            continue
        if row.get("assetClass") == "pick":
            # A pick may move only through the rookie-pool tether (an H rookie
            # is in the pool it inherits from) -- preregistration G4.
            if row.get("rankDerivedValue") != (b.get(name) or {}).get("rankDerivedValue"):
                prov = (b.get(name) or {}).get("pickValueProvenance") or {}
                assert prov.get("class") == "rookie_pool_tether", name
            continue
        assert row.get("rankDerivedValue") == (b.get(name) or {}).get("rankDerivedValue"), name
    assert {n for n, r in b.items() if r.get("sparseEvidence")} == haircut


def test_board_estimates_stay_inside_their_inputs(boards):
    _off, on = boards
    for row in on["playersArray"]:
        block = row.get("sparseEvidence")
        if not block:
            assert not row.get("singleSourceValuePenaltyApplied")
            continue
        inputs = [block["observedValue"]] + [c["bound"] for c in block["censoredFamiliesUsed"]]
        assert min(inputs) - 1 <= block["centralEstimate"] <= block["observedValue"]
        if row.get("rankDerivedValue") is not None:
            assert row["rankDerivedValue"] == max(dc._CANONICAL_VALUE_MIN, block["centralEstimate"])
        assert block["confidence"]["bucket"] == row.get("confidenceBucket")
    assert not any(r.get("blendIntegrityViolation") for r in on["playersArray"])
