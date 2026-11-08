"""The scoring-parity taxonomy: classifier branches and the pinned evidence.

Record: ``docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md``.  The
classifier is exercised on hand-built exceptions (one per class); the committed
evidence files are checked for internal consistency and for the one property the
owner's release decision rests on: both trees were measured on IDENTICAL inputs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.idp_accuracy.scoring_parity_taxonomy import CLASSES, classify_exception

EVID = Path(__file__).resolve().parents[2] / "docs/valuation/idp_accuracy/evidence"
MAIN = json.loads((EVID / "scoring_parity_taxonomy_main.json").read_text(encoding="utf-8"))
PR = json.loads((EVID / "scoring_parity_taxonomy_pr1938.json").read_text(encoding="utf-8"))


def _exc(category="stat_source_disagreement", group="LB", dk=None, attribution=None, diff=1.0):
    return {
        "category": category,
        "group": group,
        "awarded": 10.0,
        "diff": diff,
        "keysDifferHostVsNflverse": dk or {},
        "attribution": attribution or [],
    }


@pytest.mark.parametrize(
    "exc,supplement,listing,want",
    [
        (_exc("identity_join_miss"), None, None, "incorrect_player_identity"),
        (_exc("identity_name_collision_dropped"), None, None, "incorrect_player_identity"),
        (_exc("stat_source_gap_week_missing"), None, None, "unavailable_evidence"),
        (_exc(diff=0.015), None, None, "rounding"),
        (_exc(diff=0.5), None, None, "unexplained"),
        # FB (Sleeper) vs RB (nflverse): a position-scoped rate paid under the provider's listing
        (_exc(group="FB", dk={"bonus_fd_rb": [0.0, 1.0]}), None, "RB", "incorrect_position_classification"),
        # a DL/LB listing split does NOT matter: every IDP rate on this card is position-agnostic
        (_exc(group="DL", dk={"idp_hit": [6.36, 4.24]}), None, "LB", "source_data_disagreement"),
        # the nflverse path has no scorer for the key at all
        (_exc(dk={"fum_rec": [1.0, 0.0]}), None, None, "missing_stat_category"),
        (
            _exc(group="WR", dk={"idp_tkl_solo": [1.33, 0.0]}, attribution=["IDPA-DEFECT-01"]),
            None, None, "implementation_error",
        ),
        (
            _exc(group="WR", dk={"idp_tkl_ast": [0.8, 0.0]}, attribution=["IDPA-DEFECT-01"]),
            None, None, "irreconcilable_provider_semantics",
        ),
        (
            _exc(group="K", dk={"fgmiss_40_49": [-2.45, 0.0]}, attribution=["IDPA-DEFECT-02"]),
            None, None, "missing_stat_category",
        ),
        (
            _exc(group="DB", dk={"idp_def_td": [6.36, 0.0]}, attribution=["IDPA-DEFECT-03"]),
            None, None, "missing_stat_category",
        ),
        (
            _exc(dk={"idp_tkl_solo": [1.33, 2.66]}), {"st_tkl_solo": 1}, None,
            "implementation_error",
        ),
        (
            _exc(dk={"idp_tkl_ast": [0.8, 1.6]}), {"st_tkl_solo": 1}, None,
            "irreconcilable_provider_semantics",
        ),
        (_exc(dk={"idp_tkl_ast": [0.8, 1.6]}), None, None, "source_data_disagreement"),
        (_exc(dk={"idp_pd": [5.3, 0.0]}), {"st_tkl_solo": 1}, None, "source_data_disagreement"),
    ],
)  # fmt: skip
def test_classifier_branch(exc, supplement, listing, want):
    cls, sub, detail = classify_exception(exc, supplement, listing)
    assert cls == want and cls in CLASSES and sub and detail


def test_classifier_is_deterministic_and_pure():
    exc = _exc(dk={"idp_tkl_solo": [1.33, 2.66]})
    before = json.dumps(exc, sort_keys=True)
    a = classify_exception(exc, {"st_tkl_solo": 1}, None)
    b = classify_exception(exc, {"st_tkl_solo": 1}, None)
    assert a == b and json.dumps(exc, sort_keys=True) == before


@pytest.mark.parametrize("ev", [MAIN, PR], ids=["main", "pr1938"])
def test_evidence_is_internally_consistent(ev):
    census = ev["nflverseCensus"]
    mismatches = sum(
        census.get(k, 0)
        for k in (
            "scorer_defect",
            "stat_source_disagreement",
            "identity_name_collision_dropped",
            "identity_join_miss",
            "stat_source_gap_week_missing",
            "unexplained",
        )
    )
    t = ev["taxonomy"]
    assert t["totalMismatchingPlayerWeeks"] == len(ev["mismatches"]) == mismatches
    assert sum(b["playerWeeks"] for b in t["byClass"].values()) == mismatches
    for side in ("IDP", "OFFENSE"):
        assert sum(b["playerWeeks"] for b in t["bySide"][side].values()) <= mismatches
    assert sum(sum(b["playerWeeks"] for b in t["bySide"][s].values()) for s in t["bySide"]) == (
        mismatches
    )
    assert {m["class"] for m in ev["mismatches"]} <= set(CLASSES)
    assert ev["scoringFingerprint"] == "sf1:9e51824690d091f9"
    # the host-native scorer reconciles on every scored player-week (the oracle for the rest)
    assert ev["sample"]["hostWithinTol"] == ev["sample"]["hostScored"]


def test_both_trees_were_measured_on_identical_inputs():
    keys = (
        "nflverseRowsFileSha256",
        "nflverseRowsCanonicalSha256",
        "nflverseRowCount",
        "pbpArtifactSha256",
    )
    assert {k: MAIN["inputs"][k] for k in keys} == {k: PR["inputs"][k] for k in keys}
    m, p = MAIN["inputs"]["sleeperResponses"], PR["inputs"]["sleeperResponses"]
    assert m.keys() == p.keys()
    assert {u: v["sha256"] for u, v in m.items()} == {u: v["sha256"] for u, v in p.items()}
    assert MAIN["sourceTree"]["realizedPointsSha256"] != PR["sourceTree"]["realizedPointsSha256"]


def test_pinned_headline_numbers():
    """The figures the doc and the #1938 release brief quote."""
    assert MAIN["nflverseCensus"]["match"] == 2834 and PR["nflverseCensus"]["match"] == 2978
    assert MAIN["sample"]["nflverseJoinedAndScored"] == 3095
    assert PR["sample"]["nflverseJoinedAndScored"] == 3095
    mc, pc = MAIN["taxonomy"]["byClass"], PR["taxonomy"]["byClass"]
    assert mc["implementation_error"]["playerWeeks"] == 137
    assert pc["implementation_error"]["playerWeeks"] == 0
    # what #1938 does not touch is byte-identical between the two trees
    for c in (
        "incorrect_player_identity",
        "incorrect_position_classification",
        "source_data_disagreement",
    ):
        assert mc[c] == pc[c]
