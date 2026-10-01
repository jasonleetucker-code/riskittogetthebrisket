"""The Hill manifest reads source dependence from the ONE lineage owner.

Before this, ``training_manifest._MEASURED_DEPENDENCES`` kept a private copy of
three residual correlations. When #1599 re-measured OTC (positive dependence on
base KTC, Dynasty Daddy and Yahoo/Boone), the copy still said OTC depended only on
FantasyCalc -- not a trainer -- so production ``independentCriterion`` counted OTC
as independent evidence. One concept, one owner: the manifest now derives every
holdout's relationship with every training family from
``config/sources/source_lineage.json`` (validated by
``src.sources.source_census.validate_lineage``).

Pinned here:

* derivation from the owner (no private literal; the categories follow the file);
* fail closed: invalid / unreadable lineage, no reconciled pair, a null category,
  an unregistered holdout, or an absence-of-evidence pair about a sibling key are
  all UNKNOWN -- never independent;
* OTC is no longer counted independent, and SUSPECTED counts (D2 §5);
* PROVEN ancestry across families excludes the board from the split;
* with no independent holdout, ``independentCriterion`` is ``None`` with the
  reason ``no_independent_holdout`` -- and no Autopilot gate reads it;
* a recorded relation is never outvoted by a pair (#1601 review);
* ``manifestHash`` covers the DERIVED holdout labels, not the lineage file's
  bytes: a label change stales challengers, an unrelated lineage edit does not.

No network. Assertions on the live lineage file are about the categories it
records, never about RMSE levels.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.model_registry import holdout
from src.model_registry import training_manifest as tm
from src.model_registry.training_manifest import (
    LINEAGE_INDEPENDENT,
    LINEAGE_MEASURED,
    LINEAGE_PROVEN,
    LINEAGE_SUSPECTED,
    LINEAGE_UNKNOWN,
    LineageView,
    build_manifest,
    default_manifest,
    load_lineage_view,
)
from src.sources import source_census as sc

REPO = Path(__file__).resolve().parents[2]
OFFENSE_TRAINER_FAMILIES = {
    "ktcCrowd",
    "dynastyDaddySf",
    "dynastyNerdsSfTep",
    "yahooBoone",
    "fantasyPros",
    "draftSharks",
}


def _view(*pairs: dict, relations: dict | None = None, sha: str = "x" * 64) -> LineageView:
    return LineageView("synthetic", sha, True, (), tuple(pairs), dict(relations or {}))


def _pair(pid: str, sources: list[str], category: str | None, **extra) -> dict:
    return {"id": pid, "sources": sources, "category": category, "relations": [], **extra}


def _holdout(m, key: str):
    (b,) = [b for b in m.boards if b.scope == "OFFENSE" and b.source_key == key]
    return b


def _otc_fully_independent_view(**kw) -> LineageView:
    trainers = ["ktc", "dynastyDaddySf", "dynastyNerdsSfTep", "yahooBoone"]
    trainers += ["fantasyProsFitzmaurice", "draftSharks"]
    return _view(
        *(_pair(f"p-{t}", ["otcffbSf", t], LINEAGE_INDEPENDENT) for t in trainers),
        **kw,
    )


# ── derivation from the owner ───────────────────────────────────────────────


class TestDerivedFromTheLineageOwner:
    def test_no_private_dependence_literal_remains(self):
        """No module-level name binds a dependence table, and no MeasuredDependence
        type exists to build one from (AST, so prose mentioning the history passes)."""
        import ast

        for rel in ("src/model_registry/training_manifest.py", "src/model_registry/holdout.py"):
            tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
            bound = set()
            for node in tree.body:
                targets = getattr(node, "targets", None) or [getattr(node, "target", None)]
                bound |= {t.id for t in targets if isinstance(t, ast.Name)}
                if isinstance(node, ast.ClassDef):
                    bound.add(node.name)
                if isinstance(node, ast.ImportFrom):
                    bound |= {a.asname or a.name for a in node.names}
            assert not {n for n in bound if "MEASURED_DEPENDENCES" in n}, rel
            assert "MeasuredDependence" not in bound, rel

    def test_the_live_lineage_file_is_valid_and_is_what_the_manifest_read(self):
        view = load_lineage_view()
        assert view.valid, view.errors
        assert sc.validate_lineage(sc.load_lineage()) == []
        assert default_manifest().lineage.to_dict() == view.to_dict()

    def test_every_offense_holdout_carries_one_entry_per_training_family(self):
        m = default_manifest()
        assert m.training_families("OFFENSE") == OFFENSE_TRAINER_FAMILIES
        for b in m.holdouts("OFFENSE"):
            assert {d.trainer_family for d in b.lineage_dependence} == OFFENSE_TRAINER_FAMILIES

    def test_categories_follow_the_file_not_a_literal(self):
        """Change only the lineage, and the manifest's answer changes with it."""
        dependent = build_manifest(
            lineage=_view(_pair("p", ["otcffbSf", "draftSharks"], LINEAGE_MEASURED))
        )
        independent = build_manifest(lineage=_otc_fully_independent_view())
        d_entry = {d.trainer_family: d for d in _holdout(dependent, "otcffbSf").lineage_dependence}
        assert d_entry["draftSharks"].category == LINEAGE_MEASURED
        assert d_entry["draftSharks"].pairs == ("p",)
        assert _holdout(independent, "otcffbSf").lineage_independent is True

    def test_live_otc_entries_match_the_owner_pair_reconciliation(self):
        """Each OTC entry is the category of the owner's reconciled pair for it."""
        pairs = {p["id"]: p for p in sc.load_lineage()["pairReconciliation"]}
        for d in _holdout(default_manifest(), "otcffbSf").lineage_dependence:
            assert d.pairs, d
            assert {pairs[p]["category"] for p in d.pairs} == {d.category}

    def test_current_measurements_come_from_the_cited_relations(self):
        (ktc,) = [
            d
            for d in _holdout(default_manifest(), "otcffbSf").lineage_dependence
            if d.trainer_family == "ktcCrowd"
        ]
        rel = {r["id"]: r for r in sc.load_lineage()["relations"]}["otc-ktc-dependence"]
        assert (
            ktc.current_measurements["otc-ktc-dependence"]["values"]
            == (sc.current_measurement(rel)["values"])
        )

    def test_a_multi_source_pair_speaks_only_for_the_sources_its_relations_join(self):
        """``pair-signals-market-families`` lists FantasyCalc beside KTC Crowd but is a
        statement about Signals; it must not decide FantasyCalc vs KTC."""
        fc = {
            d.trainer_family: d
            for d in _holdout(default_manifest(), "fantasyCalc").lineage_dependence
        }
        assert "pair-signals-market-families" not in fc["ktcCrowd"].pairs
        assert fc["ktcCrowd"].reason == "no_reconciled_pair"


# ── fail closed ─────────────────────────────────────────────────────────────


class TestUnknownLineageFailsClosed:
    def _all_unknown(self, m, reason: str) -> None:
        for b in m.holdouts("OFFENSE"):
            assert b.lineage_independent is False
            assert {d.category for d in b.lineage_dependence} == {LINEAGE_UNKNOWN}
            assert {d.reason for d in b.lineage_dependence} == {reason}

    def test_missing_lineage_file(self, tmp_path):
        view = load_lineage_view(tmp_path / "absent.json")
        assert not view.valid and view.sha256 is None
        m = build_manifest(lineage=view)
        assert m.lineage.valid is False
        self._all_unknown(m, "lineage_invalid")

    def test_unparsable_lineage_file(self, tmp_path):
        p = tmp_path / "lineage.json"
        p.write_text("{not json", encoding="utf-8")
        self._all_unknown(build_manifest(lineage=load_lineage_view(p)), "lineage_invalid")

    def test_structurally_invalid_lineage_file(self, tmp_path):
        """A file the owner's validator rejects vouches for nothing -- even if it
        claims every OTC pair is independent."""
        data = sc.load_lineage()
        data["categories"] = {}  # validate_lineage: categories must be exactly the four
        p = tmp_path / "lineage.json"
        import json

        p.write_text(json.dumps(data), encoding="utf-8")
        view = load_lineage_view(p)
        assert not view.valid and view.errors
        self._all_unknown(build_manifest(lineage=view), "lineage_invalid")

    def test_no_reconciled_pair_is_unknown(self):
        m = build_manifest(lineage=_view())
        self._all_unknown(m, "no_reconciled_pair")

    def test_null_category_is_unknown_with_its_reason(self):
        view = _view(_pair("p", ["otcffbSf", "draftSharks"], None, unknownReason="pending"))
        (d,) = [
            d
            for d in _holdout(build_manifest(lineage=view), "otcffbSf").lineage_dependence
            if d.trainer_family == "draftSharks"
        ]
        assert d.category == LINEAGE_UNKNOWN and d.reason == "null_category:pending"

    def test_independence_about_a_sibling_is_not_independence_about_the_trainer(self):
        """``ktcCrowdSfTep`` is a ktcCrowd sibling; the OFFENSE trainer is ``ktc``."""
        view = _view(_pair("p", ["otcffbSf", "ktcCrowdSfTep"], LINEAGE_INDEPENDENT))
        (d,) = [
            d
            for d in _holdout(build_manifest(lineage=view), "otcffbSf").lineage_dependence
            if d.trainer_family == "ktcCrowd"
        ]
        assert d.category == LINEAGE_UNKNOWN

    def test_dependence_on_a_sibling_does_count(self):
        view = _view(_pair("p", ["otcffbSf", "ktcCrowdSfTep"], LINEAGE_MEASURED))
        (d,) = [
            d
            for d in _holdout(build_manifest(lineage=view), "otcffbSf").lineage_dependence
            if d.trainer_family == "ktcCrowd"
        ]
        assert d.category == LINEAGE_MEASURED

    def test_most_dependent_pair_wins_and_unknown_beats_absence_of_evidence(self):
        view = _view(
            _pair("a", ["otcffbSf", "ktc"], LINEAGE_INDEPENDENT),
            _pair("b", ["otcffbSf", "ktcSfTep"], None, unknownReason="u"),
        )
        (d,) = [
            d
            for d in _holdout(build_manifest(lineage=view), "otcffbSf").lineage_dependence
            if d.trainer_family == "ktcCrowd"
        ]
        assert d.category == LINEAGE_UNKNOWN and d.pairs == ("b",)

    def test_an_unregistered_holdout_path_is_unknown(self):
        tags = tm.holdout_lineage(
            None,
            {"draftSharks": {"draftSharks"}},
            lineage=_otc_fully_independent_view(),
            family_of=lambda k: k,
        )
        assert [(d.category, d.reason) for d in tags] == [(LINEAGE_UNKNOWN, "holdout_unregistered")]


# ── OTC, SUSPECTED, PROVEN ──────────────────────────────────────────────────


class TestOtcIsNoLongerIndependent:
    def test_otc_is_dependent_on_three_trainer_families(self):
        otc = _holdout(default_manifest(), "otcffbSf")
        assert otc.role == "holdout"  # retained and reported, not dropped
        assert otc.lineage_independent is False
        cats = {d.trainer_family: d.category for d in otc.lineage_dependence}
        assert {f for f, c in cats.items() if c == LINEAGE_MEASURED} >= {
            "ktcCrowd",
            "dynastyDaddySf",
            "yahooBoone",
        }

    def test_suspected_dependence_counts_against_independence(self):
        """D2 preregistration §5: a SUSPECTED relation disqualifies a target."""
        view = _otc_fully_independent_view()
        view = _view(
            *[p for p in view.pairs if p["sources"][1] != "draftSharks"],
            _pair("s", ["otcffbSf", "draftSharks"], LINEAGE_SUSPECTED),
        )
        otc = _holdout(build_manifest(lineage=view), "otcffbSf")
        assert otc.role == "holdout"
        assert otc.lineage_independent is False
        assert otc.dependent_families == ("draftSharks",)

    def test_no_offense_holdout_is_independent_today(self):
        assert [
            b.label for b in default_manifest().holdouts("OFFENSE") if b.lineage_independent
        ] == []

    def test_proven_ancestry_across_families_excludes_from_the_split(self):
        view = _view(
            *_otc_fully_independent_view().pairs,
            _pair("pr", ["otcffbSf", "dynastyDaddySf"], LINEAGE_PROVEN),
        )
        otc = _holdout(build_manifest(lineage=view), "otcffbSf")
        assert otc.role == "excluded"
        assert otc.exclusion_reason == "confirmed_common_ancestry:lineage:pr"


# ── the gate with no independent holdout ────────────────────────────────────


class TestNoIndependentHoldout:
    def test_independent_criterion_is_none_with_a_named_reason(self):
        result = holdout.evaluate_offense_master(0.11, 1.11)
        blob = result.to_dict()
        assert result.independent_boards == ()
        assert blob["independentBoards"] == []
        assert blob["independentCriterion"] is None
        assert blob["independentCriterionReason"] == "no_independent_holdout"
        assert blob["independentCriterionGates"] is False
        assert "OTCFFB" in blob["measuredDependence"]
        # The ordinary criterion is still computed over all three boards.
        assert set(result.per_source) == {"FantasyCalc", "OTCFFB", "PFKDynasty"}
        assert blob["criterion"] > 0

    def test_an_independent_board_would_report_a_number(self, monkeypatch):
        monkeypatch.setattr(holdout, "default_lineage_view", _otc_fully_independent_view)
        result = holdout.evaluate_offense_master(0.11, 1.11)
        assert result.independent_boards == ("OTCFFB",)
        assert result.independent_criterion == pytest.approx(result.per_source["OTCFFB"])
        assert result.to_dict()["independentCriterionReason"] is None

    def test_a_result_without_lineage_is_never_independent(self):
        r = holdout.HoldoutResult(
            criterion=1.0,
            per_source={"A": 1.0},
            per_source_rows={"A": 300},
            skipped={},
            params={"c": 0.1, "s": 1.0},
            holdout_labels=("A",),
            training_labels=("B",),
        )
        assert r.independent_criterion is None
        assert r.independent_criterion_reason == "no_independent_holdout"

    def test_no_autopilot_gate_reads_independence(self):
        """``independentCriterion`` is reporting-only: auto-promotion is decided on
        ``criterion`` / ``per_source`` alone, so it neither stops nor loosens here."""
        from src.model_registry import autopilot

        params = set(inspect.signature(autopilot.decide).parameters)
        assert not {p for p in params if "independ" in p.lower()}
        src = inspect.getsource(autopilot)
        assert "independent_criterion" not in src and "independentCriterion" not in src

    def test_autopilot_plan_reports_the_reason(self):
        """The run log names ``no_independent_holdout`` instead of omitting it."""
        text = (REPO / "scripts/hill_autopilot.py").read_text(encoding="utf-8")
        assert '"holdoutIndependence"' in text
        assert "independent_criterion_reason" in text
        assert '"gatesPromotion": False' in text


# ── recorded relations are never outvoted by a pair ────────────────────────


def _live_lineage_data() -> dict:
    import json

    return json.loads((REPO / tm.LINEAGE_REL).read_text(encoding="utf-8"))


def _unvalidated_view(data: dict) -> LineageView:
    """A view of ``data`` marked valid WITHOUT running the validator, so the
    manifest's own defence is tested independently of the owner's."""
    return LineageView(
        "synthetic",
        "x" * 64,
        True,
        (),
        tuple(data["pairReconciliation"]),
        {r["id"]: r for r in data["relations"]},
    )


class TestRecordedRelationIsNeverOutvoted:
    def test_review_repro_pfk_stays_dependent_on_ktc(self):
        """#1601 review: replace ``pair-ktc-pfk`` with an INDEPENDENT
        (pfkDynasty, ktc) pair that cites nothing. ``pfk-ktc-dependence`` still
        records measured dependence, so PFK must not read independent of KTC."""
        data = _live_lineage_data()
        data["pairReconciliation"] = [
            p for p in data["pairReconciliation"] if p["id"] != "pair-ktc-pfk"
        ] + [_pair("pair-pfk-ktc-independent", ["pfkDynasty", "ktc"], LINEAGE_INDEPENDENT)]
        # The owner refuses the file ...
        assert any("pair-pfk-ktc-independent" in e for e in sc.validate_lineage(data))
        # ... and the manifest, handed it anyway, still takes the worse verdict.
        pfk = _holdout(build_manifest(lineage=_unvalidated_view(data)), "pfkDynasty")
        (ktc,) = [d for d in pfk.lineage_dependence if d.trainer_family == "ktcCrowd"]
        assert ktc.category == LINEAGE_MEASURED
        assert "pfk-ktc-dependence" in ktc.relations
        assert ktc.pairs == ()  # the INDEPENDENT pair lost
        assert ktc.reason == "relation_measured_dependence"
        assert pfk.lineage_independent is False

    def test_suspected_relation_beats_an_independent_pair(self):
        rel = {"id": "r", "classification": "suspected", "sources": ["otcffbSf", "draftSharks"]}
        view = _otc_fully_independent_view(relations={"r": rel})
        otc = _holdout(build_manifest(lineage=view), "otcffbSf")
        cats = {d.trainer_family: d for d in otc.lineage_dependence}
        assert cats["draftSharks"].category == LINEAGE_SUSPECTED
        assert cats["draftSharks"].relations == ("r",)
        assert otc.lineage_independent is False

    def test_proven_relation_beats_a_measured_pair_and_excludes(self):
        rel = {"id": "r", "classification": "proven", "sources": ["otcffbSf", "draftSharks"]}
        view = _view(
            *[p for p in _otc_fully_independent_view().pairs if p["sources"][1] != "draftSharks"],
            _pair("m", ["otcffbSf", "draftSharks"], LINEAGE_MEASURED),
            relations={"r": rel},
        )
        otc = _holdout(build_manifest(lineage=view), "otcffbSf")
        assert otc.role == "excluded"
        (ds,) = [d for d in otc.lineage_dependence if d.trainer_family == "draftSharks"]
        assert ds.category == LINEAGE_PROVEN and ds.relations == ("r",)

    def test_a_relation_with_no_reconciled_pair_is_not_unknown(self):
        rel = {"id": "r", "classification": "measured", "sources": ["otcffbSf", "draftSharks"]}
        otc = _holdout(build_manifest(lineage=_view(relations={"r": rel})), "otcffbSf")
        (ds,) = [d for d in otc.lineage_dependence if d.trainer_family == "draftSharks"]
        assert ds.category == LINEAGE_MEASURED

    def test_a_relation_not_naming_the_holdout_decides_nothing(self):
        rel = {"id": "r", "classification": "proven", "sources": ["fantasyCalc", "draftSharks"]}
        otc = _holdout(
            build_manifest(lineage=_otc_fully_independent_view(relations={"r": rel})), "otcffbSf"
        )
        assert otc.lineage_independent is True

    @staticmethod
    def _measured(residual: float) -> dict:
        return {
            "id": "r",
            "classification": "measured",
            "relation": "measured_dependence",
            "sources": ["otcffbSf", "draftSharks"],
            "asOf": "2026-10-01",
            "statistics": {
                "measurements": [
                    {
                        "asOf": "2026-10-01",
                        "status": "current",
                        "method": "m",
                        "values": {"residualR": residual},
                    }
                ]
            },
        }

    def test_a_measured_relation_with_no_positive_dependence_decides_nothing(self):
        """#1601 round 2: ``dlf-ktc-independence`` is classified measured but its
        latest residual is -0.447. D2 §5 counts a measured relation only "with a
        positive dependence in its latest recorded measurement" -- the SAME rule
        the owner's validator reads (``relation_dependence_category``)."""
        neg = self._measured(-0.447)
        assert sc.relation_dependence_category(neg) is None
        otc = _holdout(
            build_manifest(lineage=_otc_fully_independent_view(relations={"r": neg})), "otcffbSf"
        )
        assert otc.lineage_independent is True
        pos = self._measured(0.038)
        assert sc.relation_dependence_category(pos) == LINEAGE_MEASURED
        otc = _holdout(
            build_manifest(lineage=_otc_fully_independent_view(relations={"r": pos})), "otcffbSf"
        )
        (ds,) = [d for d in otc.lineage_dependence if d.trainer_family == "draftSharks"]
        assert ds.category == LINEAGE_MEASURED and ds.relations == ("r",)

    def test_live_labels_are_unchanged_by_the_relation_defence(self):
        """On the real registry every relation agrees with its pair, so the
        defence moves no category (the validator also refuses disagreement)."""
        pairs = {p["id"]: p for p in sc.load_lineage()["pairReconciliation"]}
        for b in default_manifest().holdouts("OFFENSE"):
            for d in b.lineage_dependence:
                if d.pairs:
                    assert {pairs[p]["category"] for p in d.pairs} == {d.category}, (b.label, d)


# ── fail closed on a crashing validator ────────────────────────────────────


class TestLineageViewNeverRaises:
    def test_validation_crash_fails_closed(self, monkeypatch):
        def boom(_data):
            raise KeyError("synthetic")

        monkeypatch.setattr(sc, "validate_lineage", boom)
        view = load_lineage_view()
        assert view.valid is False
        assert view.errors and view.errors[0].startswith("validation_crashed: KeyError")
        assert view.pairs == () and dict(view.relations) == {}
        m = build_manifest(lineage=view)
        for b in m.holdouts("OFFENSE"):
            assert {d.category for d in b.lineage_dependence} == {LINEAGE_UNKNOWN}
            assert b.lineage_independent is False

    def test_wrong_shaped_sections_never_raise(self, tmp_path, monkeypatch):
        import json

        p = tmp_path / "lineage.json"
        data = _live_lineage_data()
        data["pairReconciliation"] = 5
        p.write_text(json.dumps(data), encoding="utf-8")
        # The real validator (crash or error) ...
        assert load_lineage_view(p).valid is False
        # ... and a validator that wrongly passes it: the view still refuses.
        monkeypatch.setattr(sc, "validate_lineage", lambda _d: [])
        view = load_lineage_view(p)
        assert view.valid is False and view.pairs == ()


# ── trainer keys: one derivation ────────────────────────────────────────────


class TestTrainerKeysAgree:
    def test_holdout_path_keys_equal_manifest_trainer_keys(self):
        """``holdout.evaluate_offense_master`` keys trainers by file path;
        ``build_manifest`` by ``trainer_lineage_keys``. They must agree."""
        m = default_manifest()
        trainers = [b for s in tm.SCOPES for b in m.trainers(s) if b.paths]
        assert {b.label for b in m.trainers("OFFENSE")} <= {b.label for b in trainers}
        for b in trainers:
            from_paths = {tm.source_key_for_path(p) for p in b.paths}
            assert from_paths == set(tm.trainer_lineage_keys(b)), b.label


# ── hash coverage ───────────────────────────────────────────────────────────


def _edited_view(tmp_path, mutate) -> LineageView:
    import json

    data = _live_lineage_data()
    mutate(data)
    p = tmp_path / "lineage.json"
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    view = load_lineage_view(p)
    assert view.valid, view.errors
    return view


def _set_pair_category(pid: str, category: str):
    def mutate(data):
        (pair,) = [p for p in data["pairReconciliation"] if p["id"] == pid]
        pair["category"] = category
        pair.pop("measurement", None)

    return mutate


class TestManifestHashCoversDerivedLabelsOnly:
    def test_manifest_records_the_normalized_lineage_sha(self):
        raw = (REPO / tm.LINEAGE_REL).read_bytes().replace(b"\r\n", b"\n")
        blob = default_manifest().to_dict()
        assert blob["lineage"]["sha256"] == hashlib.sha256(raw).hexdigest()
        assert blob["lineage"]["path"] == "config/sources/source_lineage.json"

    def test_the_lineage_file_identity_is_not_hashed(self):
        payload = default_manifest().hash_payload()
        assert "lineage" not in payload
        for b in payload["boards"]:
            for d in b["lineageDependence"]:
                assert set(d) == set(tm._HASHED_DEPENDENCE_FIELDS)

    def test_a_byte_only_lineage_change_keeps_the_hash(self, tmp_path):
        p = tmp_path / "lineage.json"
        p.write_bytes((REPO / tm.LINEAGE_REL).read_bytes() + b"\n")
        edited = load_lineage_view(p)
        assert edited.valid and edited.sha256 != load_lineage_view().sha256
        m = build_manifest(lineage=edited)
        assert m.to_dict()["lineage"]["sha256"] == edited.sha256  # still recorded
        assert m.manifest_hash() == default_manifest().manifest_hash()

    def test_an_unrelated_idp_pair_edit_keeps_the_offense_manifest_hash(self, tmp_path):
        edited = _edited_view(
            tmp_path,
            _set_pair_category("pair-idptradecalc-idpshow", "SUSPECTED_DEPENDENCE"),
        )
        assert edited.sha256 != load_lineage_view().sha256
        assert build_manifest(lineage=edited).manifest_hash() == (
            default_manifest().manifest_hash()
        )

    def test_an_edit_that_changes_an_offense_holdout_label_changes_the_hash(self, tmp_path):
        edited = _edited_view(
            tmp_path, _set_pair_category("pair-otc-draftsharks", "SUSPECTED_DEPENDENCE")
        )
        m = build_manifest(lineage=edited)
        (ds,) = [
            d
            for d in _holdout(m, "otcffbSf").lineage_dependence
            if d.trainer_family == "draftSharks"
        ]
        assert ds.category == LINEAGE_SUSPECTED
        assert m.manifest_hash() != default_manifest().manifest_hash()

    def test_line_endings_alone_do_not_change_the_sha(self, tmp_path):
        crlf = (REPO / tm.LINEAGE_REL).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        p = tmp_path / "lineage.json"
        p.write_bytes(crlf)
        assert load_lineage_view(p).sha256 == load_lineage_view().sha256

    def test_run_record_lineage_is_provenance_not_pins(self):
        from src.model_registry.training_run import pins_hash

        record = {"manifestHash": "m", "lineage": {"sha256": "a"}}
        assert pins_hash(record) == pins_hash({**record, "lineage": {"sha256": "b"}})
        assert pins_hash(record) != pins_hash({**record, "manifestHash": "n"})

    def test_a_challenger_fitted_under_another_label_set_is_stale(self, tmp_path):
        from src.model_registry.training_run import (
            REASON_STALE_CODE_OR_MANIFEST,
            SUBSTRATE_VERSION,
            code_identity,
            tournament_exclusion_reason,
        )

        edited = _edited_view(
            tmp_path, _set_pair_category("pair-otc-draftsharks", "SUSPECTED_DEPENDENCE")
        )
        old_hash = build_manifest(lineage=edited).manifest_hash()
        code_hash = str(code_identity()["codeHash"])
        version = SimpleNamespace(
            training_run={
                "substrateVersion": SUBSTRATE_VERSION,
                "reproducible": True,
                "challengerHash": "c" * 64,
                "codeHash": code_hash,
                "manifestHash": old_hash,
                "scopes": {"OFFENSE": {"promotable": True}},
            }
        )
        now = (code_hash, default_manifest().manifest_hash())
        assert tournament_exclusion_reason(version, current_identity=now) == (
            REASON_STALE_CODE_OR_MANIFEST
        )
