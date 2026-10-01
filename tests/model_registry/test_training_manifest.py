"""The Hill training manifest: one canonical source/trainer list, derived from source authority.

Batch 3 Unit D (owner Section D, 2026-10-01). Before this unit the Hill trainer
set lived in two hand-maintained dictionaries (``fit_hill_curve_percentile.
OFFENSE_SOURCES`` and ``holdout.OFFENSE_TRAINING_SOURCES``, H8), the OFFENSE
trainer read KTC's base board with 36 pick rows inside its top 400 (E3), and
Fantasy Navigator — a KTC-derived board in the ``ktcCrowd`` family — was an
OFFENSE holdout while KTC trained (H5).

These tests pin the repaired substrate:

* item 1 — trainers, holdouts and the fit all read ONE manifest, whose paths,
  signal types and families come from the live registry
  (``data_contract._SOURCE_CSV_PATHS`` / ``_RANKING_SOURCES`` /
  ``correlation_group_for``), and a trainer list that diverges from it fails;
* item 3 — rank-only evidence (and the synthetic rank encodings in
  ``canonicalSiteValues``) can never teach value spacing;
* item 4 — a holdout may not share a provider family (confirmed common
  ancestry) with a trainer; MEASURED dependence is a different, reported tag;
* item 5 — every training population is players-only.

No network. Real-CSV assertions are properties over whatever the committed CSVs
contain, never counts.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import fit_hill_curve_percentile as fitter
from src.api import data_contract as dc
from src.identity.picks import is_pick_name
from src.model_registry import holdout
from src.model_registry.holdout import HoldoutError, evaluate_offense_master

REPO = Path(__file__).resolve().parents[2]


def _csv_path(source_key: str) -> str:
    cfg = dc._SOURCE_CSV_PATHS[source_key]
    return cfg if isinstance(cfg, str) else cfg["path"]


def _players_only_expected(path: Path, column: str) -> list[float]:
    """Independent re-statement of the population rule: positive, non-pick, descending."""
    out: list[float] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row.get("name") or row.get("Name") or row.get("Player") or ""
            pos = str(row.get("position") or row.get("pos") or "").strip().upper()
            if is_pick_name(name) or pos == "PICK":
                continue
            try:
                v = float(row.get(column) or 0)
            except ValueError:
                continue
            if v > 0:
                out.append(v)
    return sorted(out, reverse=True)


# ── item 5 / E3: the OFFENSE (and every) training population is players-only ──


class TestPlayersOnlyPopulation:
    @pytest.mark.parametrize(
        "scope_table", ["OFFENSE_SOURCES", "GLOBAL_SOURCES", "IDP_CSV_SOURCES"]
    )
    def test_fitter_loads_players_only_for_every_trainer(self, scope_table):
        """E3: ``_load_values`` kept every positive row, so KTC base trained with picks."""
        for label, (rel, col) in getattr(fitter, scope_table).items():
            path = REPO / rel
            if not path.exists():
                continue
            assert fitter._load_values(path, col) == _players_only_expected(
                path, col
            ), f"{scope_table}[{label}] trains on rows that are not players"

    def test_ktc_base_top_400_has_no_pick_rows(self):
        """The specific E3 regression: picks inside KTC's top 400 fit window."""
        manifest_mod = pytest.importorskip("src.model_registry.training_manifest")
        bv = manifest_mod.load_board_values(REPO / _csv_path("ktc"), "value")
        assert not any(is_pick_name(n) for n in bv.names[: manifest_mod.FIT_TOP_N])
        raw_picks = sum(
            1
            for r in csv.DictReader((REPO / _csv_path("ktc")).open(newline="", encoding="utf-8"))
            if is_pick_name(r.get("name") or "")
        )
        assert bv.picks_dropped == raw_picks

    def test_a_pick_row_never_reaches_a_fit_or_a_holdout(self, tmp_path):
        board = tmp_path / "board.csv"
        with board.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["name", "value", "position"])
            w.writeheader()
            w.writerow({"name": "Josh Allen", "value": 9999, "position": "QB"})
            w.writerow({"name": "2027 Early 1st", "value": 7000, "position": "PICK"})
            w.writerow({"name": "2026 Pick 1.01", "value": 6900, "position": ""})
            w.writerow({"name": "Some Player", "value": 5000, "position": "WR"})
        assert fitter._load_values(board, "value") == [9999.0, 5000.0]
        assert holdout._load_values(board, "value") == [9999.0, 5000.0]

    def test_every_manifest_board_declares_players_only(self):
        manifest_mod = pytest.importorskip("src.model_registry.training_manifest")
        m = manifest_mod.default_manifest()
        assert m.boards
        assert {b.population for b in m.boards} == {manifest_mod.POPULATION_PLAYERS_ONLY}


# ── item 1: one manifest, derived from source authority ──────────────────────


class TestOneManifest:
    def test_trainer_and_holdout_lists_are_the_manifest(self):
        from src.model_registry.training_manifest import default_manifest

        m = default_manifest()
        assert fitter.OFFENSE_SOURCES == m.csv_table("OFFENSE", "train")
        assert fitter.GLOBAL_SOURCES == m.csv_table("GLOBAL", "train")
        assert fitter.IDP_CSV_SOURCES == m.csv_table("IDP", "train")
        assert holdout.OFFENSE_TRAINING_SOURCES == m.csv_table("OFFENSE", "train")
        assert holdout.OFFENSE_HOLDOUT_SOURCES == m.csv_table("OFFENSE", "holdout")

    def test_paths_signals_and_families_come_from_the_registry(self):
        from src.model_registry.training_manifest import default_manifest

        for b in default_manifest().boards:
            for key, rel in zip(b.path_keys, b.paths):
                assert rel == _csv_path(key), f"{b.label}: path not derived from the registry"
            assert b.family == dc.correlation_group_for(b.source_key), b.label
            cfg = dc._SOURCE_CSV_PATHS[b.source_key]
            signal = "value" if isinstance(cfg, str) else str(cfg.get("signal") or "value")
            assert b.csv_signal == signal, b.label

    def test_every_registry_source_is_classified(self):
        """A new source cannot silently leave Hill behind (H8): it must be declared
        as a Hill board or explicitly listed as not one, with a reason."""
        from src.model_registry.training_manifest import unclassified_source_keys

        assert unclassified_source_keys() == set()

    def test_the_manifest_has_a_stable_content_hash(self):
        from src.model_registry.training_manifest import build_manifest, default_manifest

        assert default_manifest().manifest_hash() == build_manifest().manifest_hash()
        assert len(default_manifest().manifest_hash()) == 64

    def test_no_path_literal_remains_in_the_fitter_or_holdout(self):
        """The two hand-maintained dictionaries are gone, not mirrored."""
        for path in (
            REPO / "scripts/fit_hill_curve_percentile.py",
            REPO / "src/model_registry/holdout.py",
        ):
            text = path.read_text(encoding="utf-8")
            assert '"CSVs/site_raw/ktc.csv"' not in text, path
            assert '"CSVs/site_raw/fantasyCalc.csv"' not in text, path

    def test_ktc_market_is_never_trained_or_held_out(self):
        from src.model_registry.training_manifest import BoardSpec, build_manifest
        from src.sources.ktc_market import KTC_MARKET_KEY

        m = build_manifest(
            specs=(
                BoardSpec("KTCMarket", KTC_MARKET_KEY, "OFFENSE", "train", "value"),
                BoardSpec("DynastyDaddy", "dynastyDaddySf", "OFFENSE", "holdout", "value"),
            ),
            dependences=(),
        )
        (b,) = [b for b in m.boards if b.label == "KTCMarket"]
        assert b.role == "excluded" and "benchmark" in (b.exclusion_reason or "")
        assert all(KTC_MARKET_KEY != x.source_key for x in default_trainers_and_holdouts())


def default_trainers_and_holdouts():
    from src.model_registry.training_manifest import SCOPES, default_manifest

    m = default_manifest()
    return [b for s in SCOPES for b in (*m.trainers(s), *m.holdouts(s))]


# ── item 3: rank-only evidence never teaches spacing ─────────────────────────


class TestRankOnlyNeverTeachesSpacing:
    def test_every_trainer_and_holdout_is_native_value_evidence(self):
        from src.model_registry.training_manifest import SPACING_NATIVE_VALUE

        boards = default_trainers_and_holdouts()
        assert boards
        assert {b.spacing_evidence for b in boards} == {SPACING_NATIVE_VALUE}

    def test_a_rank_only_board_is_refused_as_a_trainer(self):
        from src.model_registry.training_manifest import BoardSpec, build_manifest

        m = build_manifest(
            specs=(BoardSpec("DLFRank", "dlfSf", "OFFENSE", "train", None),), dependences=()
        )
        (b,) = m.boards
        assert b.role == "excluded"
        assert b.spacing_evidence == "rank_only"
        assert m.trainers("OFFENSE") == ()

    def test_declaring_a_rank_column_as_a_value_column_is_an_error(self):
        from src.model_registry.training_manifest import BoardSpec, ManifestError, build_manifest

        with pytest.raises(ManifestError):
            build_manifest(
                specs=(BoardSpec("Boone", "yahooBoone", "OFFENSE", "train", "rank"),),
                dependences=(),
            )

    def test_snapshot_slices_of_rank_signal_sources_are_synthetic_and_refused(self):
        """``canonicalSiteValues`` carries a synthetic rank encoding for a rank-signal
        source; a rookie slice read from it would fit Hill to (const − rank)."""
        from src.model_registry.training_manifest import default_manifest

        m = default_manifest()
        rookie_trainers = {b.source_key for b in m.trainers("ROOKIE")}
        assert rookie_trainers
        for key in rookie_trainers:
            cfg = dc._SOURCE_CSV_PATHS[key]
            signal = "value" if isinstance(cfg, str) else str(cfg.get("signal") or "value")
            assert signal == "value", f"ROOKIE trains on {key}'s synthetic rank encoding"
        excluded = {b.source_key: b for b in m.excluded("ROOKIE")}
        for key in ("yahooBoone", "fantasyProsFitzmaurice"):
            assert key in excluded
            assert excluded[key].spacing_evidence == "synthetic_rank_encoding"

    def test_strict_policy_trains_only_on_value_signal_lineages(self):
        """The owner's strict reading of item 3 is one switch away, and tested."""
        from src.model_registry.training_manifest import TrainingPolicy, build_manifest

        m = build_manifest(policy=TrainingPolicy(allow_rank_voter_native_values=False))
        assert m.trainers("OFFENSE")
        for scope in ("OFFENSE", "GLOBAL", "IDP", "ROOKIE"):
            for b in m.trainers(scope):
                assert b.live_role in {"value_voter", "non_voting_calibration"}, (scope, b.label)


# ── item 4: holdout family leakage ───────────────────────────────────────────


class TestHoldoutFamilies:
    def test_fantasy_navigator_is_not_an_offense_holdout_while_ktc_trains(self):
        assert "FantasyNavigator" not in holdout.OFFENSE_HOLDOUT_SOURCES

    def test_fantasy_navigator_exclusion_names_the_shared_family(self):
        from src.model_registry.training_manifest import default_manifest

        m = default_manifest()
        (fn,) = [
            b for b in m.boards if b.source_key == "fantasyNavigatorSf" and b.scope == "OFFENSE"
        ]
        assert fn.role == "excluded"
        assert "confirmed_common_ancestry" in fn.exclusion_reason
        assert "ktcCrowd" in fn.exclusion_reason

    def test_no_scope_has_a_family_on_both_sides(self):
        from src.model_registry.training_manifest import SCOPES, default_manifest

        m = default_manifest()
        for scope in SCOPES:
            assert not (m.training_families(scope) & m.holdout_families(scope)), scope

    def test_the_rule_runs_in_both_directions(self):
        """A held-out family must not leak into training through a derivative either."""
        from src.model_registry.training_manifest import BoardSpec, build_manifest

        m = build_manifest(
            specs=(
                BoardSpec("FantasyNavigator", "fantasyNavigatorSf", "OFFENSE", "train", "value"),
                BoardSpec("KTCCrowd", "ktcCrowdSfTep", "OFFENSE", "holdout", "value"),
            ),
            dependences=(),
        )
        assert m.holdouts("OFFENSE") == ()

    def test_the_evaluator_refuses_a_family_shared_across_the_split(self):
        fn = ("CSVs/site_raw/fantasyNavigatorSf.csv", "value")
        with pytest.raises(HoldoutError, match="family"):
            evaluate_offense_master(0.11, 1.11, holdout_sources={"FN": fn})

    def test_measured_dependence_is_reported_not_confused_with_ancestry(self):
        from src.model_registry.training_manifest import default_manifest

        m = default_manifest()
        held = {b.source_key: b for b in m.holdouts("OFFENSE")}
        assert {"pfkDynasty", "fantasyCalc", "otcffbSf"} <= set(held)
        assert any(d.trainer_family == "ktcCrowd" for d in held["pfkDynasty"].measured_dependence)
        assert any(
            d.trainer_family == "dynastyDaddySf" for d in held["fantasyCalc"].measured_dependence
        )
        assert held["otcffbSf"].measured_dependence == ()

    def test_measured_dependence_exclusion_is_an_explicit_policy(self):
        from src.model_registry.training_manifest import (
            HoldoutPolicy,
            TrainingPolicy,
            build_manifest,
        )

        m = build_manifest(
            policy=TrainingPolicy(holdout=HoldoutPolicy(measured_dependence="exclude"))
        )
        held = {b.source_key for b in m.holdouts("OFFENSE")}
        assert "pfkDynasty" not in held and "fantasyCalc" not in held
        assert "otcffbSf" in held

    def test_holdout_result_publishes_independent_and_dependent_views(self):
        result = evaluate_offense_master(0.11, 1.11)
        blob = result.to_dict()
        assert "PFKDynasty" in blob["measuredDependence"]
        assert "OTCFFB" not in blob["measuredDependence"]
        assert blob["independentCriterion"] == pytest.approx(result.per_source["OTCFFB"], abs=1e-3)
        assert set(blob["holdoutFamilies"]) >= {"otcffbSf", "pfkDynasty", "fantasyCalc"}
