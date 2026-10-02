"""Sparse-evidence estimator: the eleven-state matrix (Batch 3 Unit E, owner directive).

Each state is constructed through the REAL ``_compute_unified_rankings`` (other
registry sources switched off with the documented ``source_overrides`` path, so
the row's evidence is exactly what the state says), built with the flag OFF (the
incumbent) and ON (candidate C), and asserted against the treatment its
semantics require:

* is the row in the estimator's scope (does it carry a ``sparseEvidence`` block);
* is a censored bound produced, binding or not, and why / why not;
* the ``evidenceState`` named in the block (the CERTAINTY half) and its causes;
* the confidence verdict, which only ``src/api/confidence.py`` decides;
* the central value, which the certainty half never moves.

The last test proves the states do not collapse to one treatment -- the
incumbent's defect (states 1-9 all become 0.30 x observation).

State 3 needs a filter stub: neither the incumbent Hampel filter nor the joint
filter can leave one family where two were present (a majority survives, and no
family has more than two members for one row), which is asserted below rather
than assumed. The stub models a VALID outlier removal of sources that listed
the player, the same seam the G1 trap uses.

Preregistration and verdict (unchanged by this file):
``docs/valuation/evidence/sparse-evidence-2026-10-01/``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.api import data_contract as dc
from src.api import sparse_evidence as se
from src.api import value_replay as vr
from tests.api.test_sparse_evidence_estimator import _index, _row, _Weighting

THREE = ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc")


def _only(*keys: str) -> dict[str, dict[str, Any]]:
    """Switch every other registered source off (the documented override path)."""
    return {s["key"]: {"include": False} for s in dc._RANKING_SOURCES if s["key"] not in keys}


def _listing_index(rows: list[dict[str, Any]], active: tuple[str, ...]) -> dict[str, Any]:
    return _index(
        *[(k, [r["canonicalName"] for r in rows if k in r["canonicalSiteValues"]]) for k in active]
    )


def _build(
    rows: list[dict[str, Any]],
    active: tuple[str, ...],
    *,
    on: bool,
    weighting: dict[str, _Weighting] | None = None,
    csv_index: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    weighting = weighting if weighting is not None else {k: _Weighting(k) for k in active}
    index = csv_index if csv_index is not None else _listing_index(rows, active)
    with vr._flag("sparse_evidence_estimator", on):
        dc._compute_unified_rankings(
            rows,
            {},
            csv_index=index,
            source_overrides=_only(*active),
            source_weighting=weighting,
        )
    return {f"{r['canonicalName']}|{r['position']}": r for r in rows}


def _anchor(*keys: str) -> dict[str, Any]:
    """Pins every value-direct site maximum at 9999: contributions = raw numbers."""
    return _row("Anchor QB", "QB", **{k: 9999 for k in keys})


def _floor(cutoff: int, *keys: str, name: str = "Floor WR") -> dict[str, Any]:
    """The deepest WR each board published: its WR cutoff."""
    return _row(name, "WR", **{k: cutoff for k in keys})


# ── the eleven states ───────────────────────────────────────────────


def _s1_sole() -> dict[str, Any]:
    active = ("ktcCrowdSfTep",)

    def rows():
        return [_anchor(*active), _row("Target WR", "WR", ktcCrowdSfTep=5000)]

    return {"rows": rows, "active": active}


def _s2_absent_from_deeper_boards() -> dict[str, Any]:
    def rows():
        return [_anchor(*THREE), _floor(2000, *THREE), _row("Target WR", "WR", ktcCrowdSfTep=5000)]

    return {"rows": rows, "active": THREE}


_S3_ACTIVE = ("ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc", "dynastyDaddySf")


def _s3_rows() -> list[dict[str, Any]]:
    return [
        _anchor(*_S3_ACTIVE),
        _floor(2000, *_S3_ACTIVE),
        _row(
            "Target WR",
            "WR",
            ktcCrowdSfTep=5000,
            ktcTradesSfTep=1000,
            idpTradeCalc=1100,
            dynastyDaddySf=1200,
        ),
    ]


def _outlier_stub(pairs, **_kw):
    """A valid outlier removal that leaves ktcCrowd alone on the target row."""
    pairs = list(pairs)
    if any(k == "ktcCrowdSfTep" and abs(v - 5000) < 1 for k, v in pairs):
        return [(k, v) for k, v in pairs if k == "ktcCrowdSfTep"], [
            k for k, _ in pairs if k != "ktcCrowdSfTep"
        ]
    return pairs, []


def _s3_outlier_removed() -> dict[str, Any]:
    return {"rows": _s3_rows, "active": _S3_ACTIVE, "patch_filter": _outlier_stub}


def _s4_stale() -> dict[str, Any]:
    s = _s2_absent_from_deeper_boards()
    s["weighting"] = {
        "ktcCrowdSfTep": _Weighting("ktcCrowdSfTep"),
        "ktcTradesSfTep": _Weighting("ktcTradesSfTep", freshness=0.5, state="STALE"),
        "idpTradeCalc": _Weighting("idpTradeCalc", freshness=0.4, state="STALE"),
    }
    return s


def _s5_unhealthy() -> dict[str, Any]:
    s = _s2_absent_from_deeper_boards()
    s["weighting"] = {
        "ktcCrowdSfTep": _Weighting("ktcCrowdSfTep"),
        "ktcTradesSfTep": _Weighting("ktcTradesSfTep", health="FAILED"),
        "idpTradeCalc": _Weighting("idpTradeCalc", health="DEGRADED"),
    }
    return s


def _s6_no_position_coverage() -> dict[str, Any]:
    def rows():
        # Neither absent board ranked a single TE: no cutoff exists for TE.
        return [_anchor(*THREE), _floor(2000, *THREE), _row("Target TE", "TE", ktcCrowdSfTep=5000)]

    return {"rows": rows, "active": THREE, "target": "Target TE|TE"}


def _s7_identity_unresolved() -> dict[str, Any]:
    def rows():
        # The name is on the board twice; an absence cannot be pinned on either.
        return [
            _anchor(*THREE),
            _floor(2000, *THREE),
            _row("Target WR", "WR", ktcCrowdSfTep=5000),
            _row("Target WR", "LB", idpTradeCalc=1500),
        ]

    return {"rows": rows, "active": THREE}


def _s8_beyond_shallower_boards() -> dict[str, Any]:
    def rows():
        # The absent boards stop at 6000 for WRs: a 5000 WR sits beyond them.
        return [_anchor(*THREE), _floor(6000, *THREE), _row("Target WR", "WR", ktcCrowdSfTep=5000)]

    return {"rows": rows, "active": THREE}


_S9_ACTIVE = ("ktcCrowdSfTep", "fantasyNavigatorSf")


def _s9_same_family() -> dict[str, Any]:
    def rows():
        return [
            _anchor(*_S9_ACTIVE),
            _row("Target WR", "WR", ktcCrowdSfTep=5000, fantasyNavigatorSf=4800),
        ]

    return {"rows": rows, "active": _S9_ACTIVE, "value_based": ("fantasyNavigatorSf",)}


def _s10_independent() -> dict[str, Any]:
    def rows():
        return [
            _anchor(*THREE),
            _floor(2000, *THREE),
            _row("Target WR", "WR", ktcCrowdSfTep=5000, ktcTradesSfTep=4000),
        ]

    return {"rows": rows, "active": THREE}


def _s11_no_evidence() -> dict[str, Any]:
    def rows():
        return [_anchor(*THREE), _floor(2000, *THREE), _row("Target WR", "WR")]

    return {"rows": rows, "active": THREE}


STATES = {
    1: _s1_sole,
    2: _s2_absent_from_deeper_boards,
    3: _s3_outlier_removed,
    4: _s4_stale,
    5: _s5_unhealthy,
    6: _s6_no_position_coverage,
    7: _s7_identity_unresolved,
    8: _s8_beyond_shallower_boards,
    9: _s9_same_family,
    10: _s10_independent,
    11: _s11_no_evidence,
}


def _target(spec: dict[str, Any], *, on: bool, monkeypatch) -> dict[str, Any]:
    with monkeypatch.context() as m:
        if spec.get("patch_filter"):
            m.setattr(dc, "_hampel_filter_per_player", spec["patch_filter"])
        extra = set(spec.get("value_based") or ()) | (
            {"dynastyDaddySf"} if "dynastyDaddySf" in spec["active"] else set()
        )
        if extra:
            m.setattr(dc, "_VALUE_BASED_SOURCES", frozenset(dc._VALUE_BASED_SOURCES | extra))
        got = _build(spec["rows"](), spec["active"], on=on, weighting=spec.get("weighting"))
    return got[spec.get("target", "Target WR|WR")]


def treatment(state: int, monkeypatch) -> dict[str, Any]:
    spec = STATES[state]()
    off = _target(spec, on=False, monkeypatch=monkeypatch)
    on = _target(spec, on=True, monkeypatch=monkeypatch)
    block = on.get("sparseEvidence")
    return {
        "off": off,
        "on": on,
        "block": block,
        "inScope": block is not None,
        "evidenceState": (block or {}).get("evidenceState"),
        "binding": [c["family"] for c in (block or {}).get("censoredFamiliesUsed", [])],
        "nonbinding": [c["family"] for c in (block or {}).get("nonBindingFamilies", [])],
        "refused": (block or {}).get("refusedFamilies", {}),
        "valueOff": off.get("rankDerivedValue"),
        "valueOn": on.get("rankDerivedValue"),
        "confidence": on.get("confidenceBucket"),
    }


# ── per-state assertions ────────────────────────────────────────────


def test_state_1_exactly_one_family_and_nothing_else_could_list_it(monkeypatch):
    t = treatment(1, monkeypatch)
    assert t["inScope"] and t["evidenceState"] == se.EV_SOLE
    assert t["block"]["evidenceCauses"] == [se.EV_SOLE]
    assert t["block"]["eligibleAbsentFamilyCount"] == 0
    assert t["binding"] == [] and t["nonbinding"] == [] and t["refused"] == {}
    assert t["block"]["state"] == se.STATE_UNCORROBORATED
    # Central value: the observation, never 30% of it.  Certainty: LOW.
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_2_healthy_deeper_boards_that_omit_the_player_bound_it(monkeypatch):
    t = treatment(2, monkeypatch)
    assert t["evidenceState"] == se.EV_CENSORED
    assert sorted(t["binding"]) == ["idpTradeCalc", "ktcTrades"]
    # Each absent family AT its own published WR cutoff (2000): n=3 blend of
    # [5000, 2000, 2000] = (mean 3000 + median 2000) / 2.  Not rank 301, not 0.
    assert (t["valueOff"], t["valueOn"]) == (1500, 2500)
    assert t["block"]["identifiedSet"]["lower"] is None
    assert t["confidence"] == "low"


def test_state_3_sources_removed_as_outliers_listed_the_player_so_they_never_censor(
    monkeypatch,
):
    t = treatment(3, monkeypatch)
    assert t["evidenceState"] == se.EV_OUTLIER_REMOVED
    assert t["block"]["listedNotVotingFamilies"] == {
        "dynastyDaddySf": se.LISTED_OUTLIER,
        "idpTradeCalc": se.LISTED_OUTLIER,
        "ktcTrades": se.LISTED_OUTLIER,
    }
    # A listing is not an absence: no bound, no refusal -- they are not absent.
    assert t["binding"] == [] and t["nonbinding"] == [] and t["refused"] == {}
    assert t["block"]["eligibleAbsentFamilyCount"] == 0
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_3_is_unreachable_through_the_real_filters():
    """The real filters keep a majority: the same row never becomes one family."""
    for joint in (False, True):
        with vr._flag("joint_outlier_sparse_challenger", joint):
            with pytest.MonkeyPatch.context() as m:
                m.setattr(
                    dc,
                    "_VALUE_BASED_SOURCES",
                    frozenset(dc._VALUE_BASED_SOURCES | {"dynastyDaddySf"}),
                )
                got = _build(_s3_rows(), _S3_ACTIVE, on=True)
        row = got["Target WR|WR"]
        assert "sparseEvidence" not in row, joint
        assert row["independentSourceCount"] >= 2, joint


def test_a_listing_switched_off_by_an_override_is_filtered_not_absent():
    """A source the user switched off LISTED the player: never a censor."""
    rows = [
        _anchor(*THREE),
        _floor(2000, *THREE),
        _row("Target WR", "WR", ktcCrowdSfTep=5000, ktcTradesSfTep=4000),
    ]
    active = ("ktcCrowdSfTep", "idpTradeCalc")
    block = _build(rows, active, on=True, csv_index=_listing_index(rows, THREE))["Target WR|WR"][
        "sparseEvidence"
    ]
    assert block["evidenceState"] == se.EV_LISTED_FILTERED
    assert block["listedNotVotingFamilies"] == {"ktcTrades": se.LISTED_INACTIVE}
    assert "ktcTrades" not in block["refusedFamilies"]
    assert [c["family"] for c in block["censoredFamiliesUsed"]] == ["idpTradeCalc"]


def test_a_value_from_a_board_that_cannot_rank_the_position_is_a_shared_name():
    """An offense board's value beside a DB of the same name is not a listing."""
    active = ("idpTradeCalc", "ktcCrowdSfTep")
    rows = [
        _anchor(*active),
        _row("Floor DB", "DB", idpTradeCalc=800),
        _row("Target DB", "DB", idpTradeCalc=1200, ktcCrowdSfTep=900),
    ]
    block = _build(rows, active, on=True)["Target DB|DB"]["sparseEvidence"]
    assert block["ineligibleSourceListings"] == ["ktcCrowdSfTep"]
    assert block["listedNotVotingFamilies"] == {}
    assert block["evidenceState"] == se.EV_SOLE


def test_state_4_stale_absent_boards_are_not_evidence(monkeypatch):
    t = treatment(4, monkeypatch)
    assert t["evidenceState"] == se.EV_STALE
    assert t["refused"] == {"idpTradeCalc": se.REFUSE_STALE, "ktcTrades": se.REFUSE_STALE}
    assert t["binding"] == [] and t["nonbinding"] == []
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_5_unhealthy_absent_boards_are_not_evidence(monkeypatch):
    t = treatment(5, monkeypatch)
    assert t["evidenceState"] == se.EV_UNHEALTHY
    assert t["refused"] == {"idpTradeCalc": se.REFUSE_UNHEALTHY, "ktcTrades": se.REFUSE_UNHEALTHY}
    assert t["binding"] == [] and t["nonbinding"] == []
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_6_boards_that_do_not_cover_the_position_are_not_evidence(monkeypatch):
    t = treatment(6, monkeypatch)
    assert t["evidenceState"] == se.EV_NO_COVERAGE
    assert t["refused"] == {
        "idpTradeCalc": se.REFUSE_POSITION_UNRANKED,
        "ktcTrades": se.REFUSE_POSITION_UNRANKED,
    }
    assert t["binding"] == [] and t["nonbinding"] == []
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_7_unresolved_identity_is_not_evidence(monkeypatch):
    t = treatment(7, monkeypatch)
    assert t["evidenceState"] == se.EV_IDENTITY
    assert set(t["refused"].values()) == {se.REFUSE_IDENTITY}
    assert t["binding"] == [] and t["nonbinding"] == []
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_7_a_published_but_unattached_name_is_identity_not_absence():
    rows = [_anchor(*THREE), _floor(2000, *THREE), _row("Target WR", "WR", ktcCrowdSfTep=5000)]
    index = _index(
        ("ktcCrowdSfTep", ["Anchor QB", "Floor WR", "Target WR"]),
        ("ktcTradesSfTep", ["Anchor QB", "Floor WR", "Target WR"]),
        ("idpTradeCalc", ["Anchor QB", "Floor WR", "Target WR"]),
    )
    block = _build(rows, THREE, on=True, csv_index=index)["Target WR|WR"]["sparseEvidence"]
    assert block["evidenceState"] == se.EV_IDENTITY
    assert set(block["refusedFamilies"].values()) == {se.REFUSE_NAME_PUBLISHED}


def test_state_8_beyond_shallower_boards_is_consistent_absence_not_contradiction(monkeypatch):
    t = treatment(8, monkeypatch)
    assert t["evidenceState"] == se.EV_BEYOND_SHALLOW
    assert t["binding"] == [] and sorted(t["nonbinding"]) == ["idpTradeCalc", "ktcTrades"]
    assert t["block"]["state"] == se.STATE_CENSOR_NONBINDING
    # The boards stop above the player: their absence is what a 5000 WR implies.
    assert (t["valueOff"], t["valueOn"]) == (1500, 5000)
    assert t["confidence"] == "low"


def test_state_9_several_members_of_one_family_are_one_opinion(monkeypatch):
    t = treatment(9, monkeypatch)
    assert t["evidenceState"] == se.EV_SAME_FAMILY
    assert t["block"]["evidenceCauses"] == [se.EV_SAME_FAMILY, se.EV_SOLE]
    assert t["block"]["observationCount"] == 2
    assert t["block"]["independentFamilyCount"] == 1
    assert t["block"]["effectiveFamilyCount"] == pytest.approx(1.0)  # one provider's cap
    # The family's capped blend of 5000 / 4800, kept; the incumbent keeps 30%.
    assert (t["valueOff"], t["valueOn"]) == (1470, 4900)
    assert t["confidence"] == "low"


def test_state_10_two_independent_families_are_not_sparse(monkeypatch):
    t = treatment(10, monkeypatch)
    assert not t["inScope"]
    assert t["valueOff"] == t["valueOn"] == 4500
    assert t["off"]["confidenceBucket"] == t["on"]["confidenceBucket"]
    assert not t["off"].get("singleSourceValuePenaltyApplied")


def test_state_11_zero_evidence_is_unpriced_never_zero(monkeypatch):
    t = treatment(11, monkeypatch)
    assert not t["inScope"]
    assert "rankDerivedValue" not in t["off"] and "rankDerivedValue" not in t["on"]
    assert t["confidence"] is None
    ev = se.classify(
        observed=0.0,
        present_families=0,
        observations=0,
        listed_not_voting={},
        est=None,
        refused={},
    )
    assert ev.state == se.EV_NO_EVIDENCE


# ── shallow vs deep censors ─────────────────────────────────────────


@pytest.mark.parametrize("cutoff", [7000, 6000, 5000, 4000, 3000, 2000, 1000])
def test_a_censor_is_only_as_strong_as_the_board_is_deep(cutoff):
    """One absent board at a time, at cutoff U, against an observation of 5000.

    A shallow board (U >= x) omitting the player says only "below U", which the
    observation already satisfies: non-binding, value unchanged.  A deeper board
    (U < x) contradicts the observation and enters AT its cutoff -- the most
    generous place the evidence allows -- so the estimate never falls below U.
    The difference is carried entirely by where the cutoff sits; no
    depth-dependent weight is invented.
    """
    active = ("ktcCrowdSfTep", "ktcTradesSfTep")
    rows = [
        _anchor(*active),
        _floor(cutoff, *active),
        _row("Target WR", "WR", ktcCrowdSfTep=5000),
    ]
    row = _build(rows, active, on=True)["Target WR|WR"]
    block = row["sparseEvidence"]
    if cutoff >= 5000:
        assert block["evidenceState"] == se.EV_BEYOND_SHALLOW
        assert row["rankDerivedValue"] == 5000
    else:
        assert block["evidenceState"] == se.EV_CENSORED
        # n=2 weighted mean of [5000, U] at equal weight.
        assert row["rankDerivedValue"] == (5000 + cutoff) // 2
        assert cutoff <= row["rankDerivedValue"] < 5000


def test_deeper_boards_bound_harder_and_monotonically():
    values = []
    for cutoff in (7000, 6000, 5000, 4000, 3000, 2000, 1000):
        active = ("ktcCrowdSfTep", "ktcTradesSfTep")
        rows = [
            _anchor(*active),
            _floor(cutoff, *active),
            _row("Target WR", "WR", ktcCrowdSfTep=5000),
        ]
        values.append(_build(rows, active, on=True)["Target WR|WR"]["rankDerivedValue"])
    assert values == sorted(values, reverse=True)
    assert min(values) > 0


# ── precedence and mixtures ─────────────────────────────────────────


def test_a_binding_censor_outranks_same_family_members_in_the_state():
    active = ("ktcCrowdSfTep", "fantasyNavigatorSf", "ktcTradesSfTep")
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            dc, "_VALUE_BASED_SOURCES", frozenset(dc._VALUE_BASED_SOURCES | {"fantasyNavigatorSf"})
        )
        rows = [
            _anchor(*active),
            _floor(2000, *active),
            _row("Target WR", "WR", ktcCrowdSfTep=5000, fantasyNavigatorSf=4800),
        ]
        block = _build(rows, active, on=True)["Target WR|WR"]["sparseEvidence"]
    assert block["evidenceState"] == se.EV_CENSORED
    assert block["evidenceCauses"] == [se.EV_CENSORED, se.EV_SAME_FAMILY]


def test_mixed_refusals_are_named_mixed_and_every_category_is_kept():
    weighting = {
        "ktcCrowdSfTep": _Weighting("ktcCrowdSfTep"),
        "ktcTradesSfTep": _Weighting("ktcTradesSfTep", freshness=0.5, state="STALE"),
        "idpTradeCalc": _Weighting("idpTradeCalc", health="FAILED"),
    }
    rows = [_anchor(*THREE), _floor(2000, *THREE), _row("Target WR", "WR", ktcCrowdSfTep=5000)]
    block = _build(rows, THREE, on=True, weighting=weighting)["Target WR|WR"]["sparseEvidence"]
    assert block["evidenceState"] == se.EV_MIXED
    assert block["refusalCategories"] == {"idpTradeCalc": se.EV_UNHEALTHY, "ktcTrades": se.EV_STALE}


def test_the_certainty_half_never_moves_the_central_value():
    """Same observation, same binding evidence: the value is identical whatever
    the certainty state says about the OTHER absences."""
    est = se.estimate(
        5000.0,
        1.0,
        {"B": se.FamilyBound("B", 2000.0, 1.0, ("b",))},
        dc.weighted_count_aware_mean_median_blend,
    )
    a = se.stamp(
        est,
        observations=1,
        voting_families=1,
        effective_families=1.0,
        refused={},
        evidence=se.classify(
            observed=5000.0,
            present_families=1,
            observations=1,
            listed_not_voting={},
            est=est,
            refused={},
        ),
    )
    b = se.stamp(
        est,
        observations=1,
        voting_families=1,
        effective_families=1.0,
        refused={"S": se.REFUSE_STALE},
        evidence=se.classify(
            observed=5000.0,
            present_families=1,
            observations=1,
            listed_not_voting={"L": se.LISTED_OUTLIER},
            est=est,
            refused={"S": se.REFUSE_STALE},
        ),
    )
    assert a["evidenceState"] != b["evidenceState"]
    assert a["centralEstimate"] == b["centralEstimate"] == 3500


def test_flag_off_no_state_carries_a_block(monkeypatch):
    for state in STATES:
        off = _target(STATES[state](), on=False, monkeypatch=monkeypatch)
        assert "sparseEvidence" not in off, state


# ── the states do not collapse ──────────────────────────────────────


def _value_class(t: dict[str, Any]) -> str:
    if not t["inScope"]:
        return "unpriced" if t["valueOn"] is None else "untouched"
    observed = t["block"]["observedValue"]
    return "bounded_below_observation" if t["valueOn"] < observed else "observation_kept"


def test_the_eleven_states_do_not_collapse_to_one_treatment(monkeypatch):
    table = {s: treatment(s, monkeypatch) for s in STATES}
    states = {s: (t["evidenceState"] if t["inScope"] else None) for s, t in table.items()}
    states[10] = se.EV_INDEPENDENT
    states[11] = se.EV_NO_EVIDENCE
    # Every state is named distinctly.
    assert len(set(states.values())) == 11, states
    # ... and the value treatments differ where the evidence differs.
    classes = {s: _value_class(t) for s, t in table.items()}
    assert classes[2] == "bounded_below_observation"
    assert classes[10] == "untouched" and classes[11] == "unpriced"
    assert {classes[s] for s in (1, 3, 4, 5, 6, 7, 8, 9)} == {"observation_kept"}
    assert len(set(classes.values())) == 4
    # Censor bounds exist only where an absence is evidence.
    produced = {s for s, t in table.items() if t["binding"] or t["nonbinding"]}
    assert produced == {2, 8}
    # The incumbent collapses states 1-9 onto one rule: 30% of the observation.
    for s in range(1, 10):
        off = table[s]["off"]
        assert off.get("singleSourceValuePenaltyApplied") is True, s
    # Uncertainty stays with its owner: every sparse state is LOW, never higher.
    assert {table[s]["confidence"] for s in range(1, 10)} == {"low"}
