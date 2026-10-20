"""Outlier-integrity-v2 R constraints: every legitimate vote the incumbent wrongly
removes when DLF IDP / D4 vote must be kept by V2.

Directive 2026-10-20 §5 ("regression tests for every previously identified
legitimate vote incorrectly rejected") and §6; preregistration §11 criterion 2.
Deviation T1 (``docs/sources/outlier_integrity_v2/DEVIATIONS.md``): run before
the Stage 2 freeze, so every assertion here holds at EVERY registered ``tau_C``
grid point (ln 4, ln 5, ln 6) -- no Stage 2 choice can be steered by them.

Fixtures are the FROZEN pre-filter vote panels of the pinned inputs
(``tests/fixtures/oiv2/panels_pin*.json``, written by
``scripts/oiv2_regression_boards.py`` from board B / B' of pin2015 and pin0527;
payload sha256 checked against ``R_REGRESSION_PIN.json``). They were extracted,
not tuned: no value in them was chosen.

Two components are measured, and kept apart:

* **Layer C on the frozen panel** (always runs): the real
  ``outlier_policy.assess_row_layer_c`` with the real provider owner, the real
  family cap and NO lineage and NO persistence -- the strictest reading
  (lineage and persistence can only keep more votes). The same panel through the
  real incumbent reproduces the documented drop, which proves the fixture.
* **The full pipeline on the pinned boards** (``OIV2_R_DIR`` set): the committed
  ``r_<pin>.json`` produced by ``scripts/oiv2_regression_boards.py`` -- boards C,
  C′, C″ built end to end with V2 on, NO-HISTORY, provisional thresholds.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api import outlier_policy as op

REPO = Path(__file__).resolve().parents[2]
FIX = REPO / "tests" / "fixtures" / "oiv2"
DOCS = REPO / "docs" / "sources" / "outlier_integrity_v2"
REGRESSION_SET = json.loads((DOCS / "manifests" / "REGRESSION_SET.json").read_text("utf-8"))
R_PIN = json.loads((DOCS / "manifests" / "R_REGRESSION_PIN.json").read_text("utf-8"))
D4_SET = json.loads((DOCS / "r_constraints" / "D4_REGRESSION_SET.json").read_text("utf-8"))
PINS = ("pin2015", "pin0527")
PANELS = {p: json.loads((FIX / f"panels_{p}.json").read_text("utf-8")) for p in PINS}
THEO = json.loads((FIX / "panel_theo_johnson_pr1817_lane.json").read_text("utf-8"))
TAU_GRID = (math.log(4.0), math.log(5.0), math.log(6.0))
IDP_PAIRS = [(p["row"], p["source"]) for p in REGRESSION_SET["idpRestore"]["pin2015"]["pairs"]]
FOCUS = ("Trevin Wallace", "Myles Garrett", "Aidan Hutchinson")


def _layer_c(panel: dict, tau: float) -> op.LayerCVerdict:
    votes = panel["votes"]
    families = panel["families"]
    capped, _f = dc.cap_family_weights(dict(panel["preCapWeights"]))
    return op.assess_row_layer_c(
        sorted(votes.items()),
        curve=op.scope_curve(panel["assetClass"]),
        provider_of=dc._integrity_provider_of,
        family_of=lambda k: families.get(k) or dc.correlation_group_for(k) or k,
        weights=capped,
        linked=None,
        persistence_confirmed=None,
        tau_c_big=tau,
    )


def _incumbent_dropped(panel: dict) -> list[str]:
    _kept, dropped = dc._hampel_filter_per_player(sorted(panel["votes"].items()))
    return dropped


# ── fixture integrity ──────────────────────────────────────────────────


def test_regression_set_is_the_frozen_31_votes_on_30_rows():
    assert len(IDP_PAIRS) == 31
    assert len({r for r, _s in IDP_PAIRS}) == 30
    assert REGRESSION_SET["idpRestore"]["pairSetIdenticalAcrossPins"] is True
    from collections import Counter

    assert Counter(s for _r, s in IDP_PAIRS) == {
        "draftSharksIdp": 18,
        "fantasyProsIdp": 10,
        "idpTradeCalc": 3,
    }


@pytest.mark.parametrize("pin", PINS)
def test_panels_come_from_the_pinned_payloads(pin):
    expected = {
        "pin2015": next(p["payloadSha256"] for p in R_PIN["pins"] if p["pin"] == "pin2015"),
        "pin0527": "b639608f",
    }[pin]
    assert PANELS[pin]["payloadSha256"].startswith(expected)


@pytest.mark.parametrize("pin", PINS)
@pytest.mark.parametrize("row,source", IDP_PAIRS)
def test_panel_carries_the_registered_vote_and_the_incumbent_reproduces_the_drop(pin, row, source):
    """Fixture proof: the frozen panel holds the very vote the regression set
    names (same value) and the real incumbent removes it on that panel."""
    panel = PANELS[pin]["B"][row]
    registered = next(
        p
        for p in REGRESSION_SET["idpRestore"][pin]["pairs"]
        if p["row"] == row and p["source"] == source
    )
    assert panel["votes"][source] == pytest.approx(registered["valueContribution"], abs=1.0)
    assert source in _incumbent_dropped(panel)
    assert source in panel["droppedSources"]


# ── the 31 votes: Layer C keeps every one, at every tau_C ───────────────


@pytest.mark.parametrize("tau", TAU_GRID, ids=["ln4", "ln5", "ln6"])
@pytest.mark.parametrize("pin", PINS)
@pytest.mark.parametrize("row,source", IDP_PAIRS)
def test_layer_c_keeps_each_wrongly_removed_idp_vote(pin, row, source, tau):
    verdict = _layer_c(PANELS[pin]["B"][row], tau)
    assert source in verdict.kept
    assert source not in verdict.dropped


@pytest.mark.parametrize("pin", PINS)
def test_layer_c_drops_nothing_on_any_of_the_30_rows_at_the_floor(pin):
    """At the strictest registered point (tau_C = ln 4) Layer C removes no vote
    at all on the 30 rows -- including DLF's own (directive §6: DLF is not
    wrongly classified as an outlier either)."""
    dropped = {
        row: _layer_c(PANELS[pin]["B"][row], TAU_GRID[0]).dropped
        for row in {r for r, _ in IDP_PAIRS}
    }
    assert {r: d for r, d in dropped.items() if d} == {}


# ── focus rows: Trevin Wallace, Myles Garrett, Aidan Hutchinson ────────


@pytest.mark.parametrize("pin", PINS)
@pytest.mark.parametrize("row", FOCUS)
def test_focus_row_draft_sharks_vote_is_kept_and_the_reason_is_named(pin, row):
    """Directive §6: the incumbent removed Draft Sharks on each of these rows
    after DLF's vote collapsed the MAD band; V2 keeps it because it lies within
    tau_C of another provider (opinion, stamped kept_dissent when > ln 2)."""
    panel = PANELS[pin]["B"][row]
    assert "draftSharksIdp" in _incumbent_dropped(panel)
    for tau in TAU_GRID:
        v = _layer_c(panel, tau)
        assert "draftSharksIdp" in v.kept
        nearest = v.details["draftSharksIdp"]["nearestOtherProvider"]
        assert nearest <= op.effective_tau_c_big(tau)


# ── D4 (DLF Values offense) ─────────────────────────────────────────────


def test_d4_set_was_computed_by_the_registered_rule():
    assert D4_SET["rule"] == REGRESSION_SET["d4"]["definition"]
    assert len(D4_SET["pairs"]) >= 1
    assert all(p["source"] != "dlfValuesSfTep" for p in D4_SET["pairs"])


@pytest.mark.parametrize("tau", TAU_GRID, ids=["ln4", "ln5", "ln6"])
@pytest.mark.parametrize(
    "pin,row,source",
    [("pin2015", p["row"], p["source"]) for p in D4_SET["pairs"]]
    + [("pin0527", p["row"], p["source"]) for p in D4_SET["pin0527"]],
)
def test_layer_c_keeps_each_d4_wrongly_removed_offense_vote(pin, row, source, tau):
    panel = PANELS[pin]["B'"][row]
    assert source in _incumbent_dropped(panel)
    assert source in _layer_c(panel, tau).kept


@pytest.mark.parametrize("tau", TAU_GRID, ids=["ln4", "ln5", "ln6"])
def test_theo_johnson_draft_sharks_vote_is_kept_with_d4_on(tau):
    """The owner-named D4 case (addendum 2026-10-20): Draft Sharks 3182 removed
    by the incumbent once DLF Values votes (2184 -> 2023). Frozen panel from the
    PR #1817 lane's dump; the incumbent reproduces the drop, Layer C keeps it."""
    panel = THEO["B'"]["Theo Johnson"]
    assert panel["votes"]["draftSharks"] == 3182.0
    assert "draftSharks" in _incumbent_dropped(panel)
    v = _layer_c(panel, tau)
    assert "draftSharks" in v.kept and v.dropped == ()


def test_theo_johnson_on_the_pins_is_documented_not_assumed():
    """On pin2015 the rule does not produce Theo Johnson (Draft Sharks votes
    3001 there and the incumbent keeps it); the registration's must-include is
    honoured through the PR #1817-lane panel above, and the D4 set file says so."""
    must = D4_SET["mustInclude"][0]
    assert must["row"] == "Theo Johnson" and must["source"] == "draftSharks"
    assert "NOT produced by the rule" in must["onPin2015"]


# ── full pipeline (pinned boards; OIV2_R_DIR) ───────────────────────────

R_DIR = os.environ.get("OIV2_R_DIR")


@pytest.mark.skipif(not R_DIR, reason="set OIV2_R_DIR to the r_<pin>.json directory")
@pytest.mark.parametrize("pin", PINS)
def test_full_pipeline_boards_keep_every_regression_vote(pin):
    r = json.loads((Path(R_DIR) / f"r_{pin}.json").read_text("utf-8"))
    idp = r["idpRestore"]
    assert idp["total"] == 31 and idp["droppedInB"] == 31
    assert idp["retainedInC"] == 31, [e for e in idp["pairs"] if not e["retainedC"]]
    assert idp["retainedInCpp"] == 31
    d4 = r["d4"]
    assert d4["retainedInCp"] == d4["count"] and d4["retainedInCpp"] == d4["count"]
    assert r["determinism"]["identical"] is True
    for row in FOCUS:
        f = r["focus"][row]
        assert f["C"]["votes"]["draftSharksIdp"][1] is None
        assert f["B"]["votes"]["draftSharksIdp"][1] == "filter_dropped"
        # Attribution: with nothing dropped on the row, C equals the no-filter board.
        assert f["C"]["value"] == f["Bnf"]["value"]
