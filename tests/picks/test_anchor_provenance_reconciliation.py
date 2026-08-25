"""F-22 / V1-85 — pickAnchors provenance describes the anchors the export EMITS.

``SitePickMap``'s own contract is that a key absent from ``values`` is
absent from ``provenance`` too.  The scraper's export broke exactly that
invariant at the payload level: ``pick_anchors = rebuilt_pick_anchors``
replaces the stage-1 vendor anchor maps with the model's rebuilt board,
while ``pick_anchors_provenance`` sailed on describing the stage-1
builds.  Measured on the live 2026-08-25 payload:

    pickAnchors            → ktc: 84, idpTradeCalc: 84   (no ktcSfTep)
    pickAnchorsProvenance  → ktc: 180, ktcSfTep: 180, idpTradeCalc: 180

Two surfaces describing the same anchors differently — the audit's F-22,
reclassified P2 (reporting; the served values were never implicated,
because the contract reads the vendor CSVs independently).

``reconcile_emitted_anchor_provenance`` is the repair's owner half; the
scraper wiring is pinned structurally below (this file cannot run a full
scrape, and a wiring assertion that cannot observe its subject would
read exactly like one that passed — the F-8/F-23 lesson).
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.picks.site_pick_map import (
    MODEL_INJECTED_PROVENANCE,
    VENDOR_ROW_PROVENANCE,
    reconcile_emitted_anchor_provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER = REPO_ROOT / "Dynasty Scraper.py"


def _live_shaped_fixture():
    """The measured live inconsistency, in miniature.

    Stage-1 provenance covers two sites and a superset of keys; the
    emitted model board carries one site, a subset of its keys, plus one
    model-injected composite the stage-1 build never saw.
    """
    emitted = {
        "ktc": {
            "2026 1.01": 6726,
            "2026 Early 1st": 5605,
            "2027 Mid 4th": 310,  # model-injected composite
        },
        "idpTradeCalc": {"2026 1.01": 8013},
    }
    stage1 = {
        "ktc": {
            "2026 1.01": "derived_slot_from_tier",
            "2026 Early 1st": "published_tier",
            "2026 Late 3rd": "published_tier",  # not emitted
        },
        # A whole site the emitted map does not carry — the live payload's
        # ktcSfTep exactly.
        "ktcSfTep": {"2026 Early 1st": "published_tier"},
    }
    injected = {("ktc", "2027 Mid 4th")}
    return emitted, stage1, injected


class TestReconciledProvenanceDescribesTheEmittedMap:
    def test_stage1_provenance_violates_the_invariant_the_reconciler_restores(self):
        """The defect, stated as the invariant it breaks.

        Pass the stage-1 provenance through unreconciled — the pre-fix
        export behaviour — and it names a site and keys the emitted map
        does not contain.  Reconciled, site and key sets match exactly.
        """
        emitted, stage1, injected = _live_shaped_fixture()

        def violations(prov):
            out = []
            for site, site_prov in prov.items():
                if site not in emitted:
                    out.append(f"site:{site}")
                    continue
                for key in site_prov:
                    if key not in emitted[site]:
                        out.append(f"{site}:{key}")
            for site, site_map in emitted.items():
                for key in site_map:
                    if key not in (prov.get(site) or {}):
                        out.append(f"missing:{site}:{key}")
            return out

        # Pre-fix behaviour: provenance for anchors that are not there.
        assert violations(stage1), "fixture must reproduce the live inconsistency"

        reconciled = reconcile_emitted_anchor_provenance(emitted, stage1, injected)
        assert violations(reconciled) == []
        assert set(reconciled) == set(emitted)
        for site in emitted:
            assert set(reconciled[site]) == set(emitted[site])

    def test_a_dropped_site_is_dropped_not_carried(self):
        emitted, stage1, injected = _live_shaped_fixture()
        reconciled = reconcile_emitted_anchor_provenance(emitted, stage1, injected)
        assert "ktcSfTep" not in reconciled

    def test_stage1_evidence_class_is_carried_for_vendor_values(self):
        emitted, stage1, injected = _live_shaped_fixture()
        reconciled = reconcile_emitted_anchor_provenance(emitted, stage1, injected)
        assert reconciled["ktc"]["2026 1.01"] == "derived_slot_from_tier"
        assert reconciled["ktc"]["2026 Early 1st"] == "published_tier"

    def test_model_injection_is_named_not_dressed_as_a_vendor(self):
        emitted, stage1, injected = _live_shaped_fixture()
        reconciled = reconcile_emitted_anchor_provenance(emitted, stage1, injected)
        assert reconciled["ktc"]["2027 Mid 4th"] == MODEL_INJECTED_PROVENANCE

    def test_unrecorded_vendor_value_gets_the_honest_fallback_class(self):
        emitted, stage1, injected = _live_shaped_fixture()
        # idpTradeCalc has no stage-1 provenance in the fixture at all.
        reconciled = reconcile_emitted_anchor_provenance(emitted, stage1, injected)
        assert reconciled["idpTradeCalc"]["2026 1.01"] == VENDOR_ROW_PROVENANCE

    def test_non_mapping_site_values_are_skipped_not_crashed(self):
        reconciled = reconcile_emitted_anchor_provenance(
            {"ktc": {"a": 1}, "broken": None}, {}, None
        )
        assert set(reconciled) == {"ktc"}


class TestScraperWiring:
    """Structural pin: the export path actually reconciles.

    The scraper cannot be executed here, so the wiring is asserted over
    its AST — the same posture as ``test_finder_va_is_not_bypassable``.
    """

    def _tree(self):
        return ast.parse(SCRAPER.read_text(encoding="utf-8"))

    def test_provenance_is_reassigned_from_the_owner_reconciler(self):
        found = False
        for node in ast.walk(self._tree()):
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "pick_anchors_provenance" not in targets:
                continue
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "reconcile_emitted_anchor_provenance"
            ):
                found = True
        assert found, (
            "the scraper must reassign pick_anchors_provenance from "
            "reconcile_emitted_anchor_provenance after replacing pick_anchors "
            "with the rebuilt model board — otherwise the export stamps "
            "provenance for anchors it does not emit (F-22 / V1-85)"
        )

    def test_model_injected_keys_are_recorded_at_the_injection_branch(self):
        src = SCRAPER.read_text(encoding="utf-8")
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "_model_injected_pick_keys"
            ):
                found = True
        assert found, (
            "the e['ktc'] = v model-injection branch must record its "
            "(site, key) so provenance can name it MODEL_INJECTED_PROVENANCE"
        )
