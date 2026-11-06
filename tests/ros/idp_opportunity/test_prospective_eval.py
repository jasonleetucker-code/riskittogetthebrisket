"""Prospective evaluation runner: refusal gate, PROV selection, exclusion counting, metric
parity with the retrospective metric owner, decisions, determinism.  Synthetic; no network."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.ros import sleeper_weekly_projections as swp
from src.ros.idp_opportunity.evaluate import Prediction, bootstrap_delta_mae, metrics
from src.ros.idp_opportunity.prospective import fit_frozen, predict_week
from src.ros.idp_opportunity.prospective_eval import (
    ALL_MODELS,
    GitFacts,
    ProvSelection,
    evaluate_week,
    holm_adjust,
    select_prov,
    verify_gate,
)
from tests.ros.idp_opportunity._fixtures import CARD_SETTINGS, card, season

WEEK = 6
KICK_AAA = datetime(2026, 11, 5, 1, 15, tzinfo=timezone.utc)
KICK_BBB = KICK_AAA + timedelta(days=3)
FP_BLOB = "f" * 40
RECEIPT = {
    "week": WEEK,
    "refit": False,
    "frozenParams": {"blob": FP_BLOB},
    "code": {
        "src/ros/idp_opportunity/prospective.py": "p" * 40,
        "src/ros/idp_opportunity/model.py": "m" * 40,
        "scripts/idp_opportunity_prospective.py": "s" * 40,
    },
}
FROZEN_BASE = {
    "card": {"fingerprint": "sf1:test"},
    "lineupDemand": {
        "topN": {"DL": 2, "LB": 1, "DB": 2},
        "slots": ["QB", "DL", "DL", "LB", "DB", "DB"],
    },
}


def _facts(**kw) -> GitFacts:
    base = dict(
        receipt_commit_iso=(KICK_AAA - timedelta(days=2)).isoformat(),
        receipt_clean=True,
        frozen_blob_now=FP_BLOB,
        code_blobs_now=dict(RECEIPT["code"]),
    )
    base.update(kw)
    return GitFacts(**base)


def _gate(**kw):
    args = dict(
        week=WEEK,
        receipt=RECEIPT,
        frozen=FROZEN_BASE,
        card_fingerprint="sf1:test",
        first_kickoff=KICK_AAA,
        week_final=True,
        finality_reason=None,
        git=_facts(),
    )
    args.update(kw)
    return verify_gate(**args)


# ── gate ─────────────────────────────────────────────────────────────────────


def test_gate_passes_a_clean_week():
    g = _gate()
    assert g.ok and not g.refusals and not g.deviations


def test_gate_refuses_no_receipt():
    g = _gate(receipt=None, git=_facts(receipt_clean=False, receipt_commit_iso=None))
    assert not g.ok and "no_receipt" in g.refusals


def test_gate_refuses_uncommitted_receipt():
    g = _gate(git=_facts(receipt_clean=False))
    assert "receipt_not_committed" in g.refusals


@pytest.mark.parametrize("delta", [timedelta(0), timedelta(seconds=1), timedelta(days=1)])
def test_gate_refuses_receipt_not_strictly_before_kickoff(delta):
    g = _gate(git=_facts(receipt_commit_iso=(KICK_AAA + delta).isoformat()))
    assert "receipt_commit_not_before_first_kickoff" in g.refusals


def test_gate_refuses_a_week_that_is_not_final():
    g = _gate(week_final=False, finality_reason="host_week_not_final")
    assert not g.ok and any(r.startswith("week_not_final") for r in g.refusals)


def test_gate_refuses_wrong_week_refit_or_card():
    assert "receipt_week_mismatch" in _gate(receipt={**RECEIPT, "week": 7}).refusals
    assert "receipt_refit_not_false" in _gate(receipt={**RECEIPT, "refit": True}).refusals
    assert "scoring_card_differs_from_frozen_card" in _gate(card_fingerprint="sf1:other").refusals
    assert "scoring_card_differs_from_frozen_card" in _gate(card_fingerprint=None).refusals


def test_blob_mismatch_refuses_unless_allowed_then_is_labelled():
    drift = _facts(frozen_blob_now="0" * 40)
    g = _gate(git=drift)
    assert not g.ok and "deviation_without_allow_deviation" in g.refusals
    g2 = _gate(git=drift, allow_deviation=True)
    assert g2.ok and "frozen_params_blob_differs_from_receipt" in g2.deviations
    blobs = dict(RECEIPT["code"]) | {"src/ros/idp_opportunity/model.py": "9" * 40}
    g3 = _gate(git=_facts(code_blobs_now=blobs), allow_deviation=True)
    assert g3.ok and any("model.py" in d for d in g3.deviations)


def test_deviation_flag_never_waives_receipt_timing_or_finality():
    late = _facts(receipt_commit_iso=(KICK_AAA + timedelta(hours=1)).isoformat())
    assert not _gate(git=late, allow_deviation=True).ok
    assert not _gate(week_final=False, allow_deviation=True).ok
    assert not _gate(receipt=None, allow_deviation=True).ok


def test_receipted_script_blob_mismatch_refuses_unless_allowed():
    blobs = dict(RECEIPT["code"]) | {"scripts/idp_opportunity_prospective.py": "n" * 40}
    g = _gate(git=_facts(code_blobs_now=blobs))
    assert not g.ok
    assert "deviation_without_allow_deviation" in g.refusals
    assert any("scripts/idp_opportunity_prospective.py" in d for d in g.deviations)
    g2 = _gate(git=_facts(code_blobs_now=blobs), allow_deviation=True)
    assert g2.ok and g2.deviations


def test_retrospective_waives_only_receipt_timing():
    g = _gate(
        receipt=None, git=_facts(receipt_clean=False, receipt_commit_iso=None), retrospective=True
    )
    assert g.ok
    assert not _gate(
        receipt=None,
        git=_facts(receipt_clean=False, receipt_commit_iso=None),
        retrospective=True,
        week_final=False,
    ).ok


# ── PROV champion ────────────────────────────────────────────────────────────

COMPANY = str((swp._census_entry().get("modelAncestry") or {}).get("model") or "")


def _row(pid, team, game, tkl, *, updated=None):
    row = {
        "player_id": pid,
        "season": "2026",
        "week": WEEK,
        "season_type": "regular",
        "stats": {"idp_tkl_solo": float(tkl)},
        "game_id": game,
        "company": COMPANY,
        "team": team,
        "opponent": "BBB" if team == "AAA" else "AAA",
        "player": {"position": "LB", "fantasy_positions": ["LB"]},
    }
    if updated is not None:
        row["updated_at"] = int(updated.timestamp() * 1000)
    return row


def _iso(dt):
    return dt.isoformat()


KICK = {"AAA": KICK_AAA, "BBB": KICK_BBB}


def _prov(captures):
    return select_prov(
        captures, season=2026, week=WEEK, kickoff_by_team=KICK, card_settings=CARD_SETTINGS
    )


def test_prov_uses_each_players_own_kickoff_and_the_latest_capture_before_it():
    early = KICK_AAA - timedelta(days=1)
    mid = KICK_AAA + timedelta(hours=5)  # after AAA kicks off, before BBB
    c1 = (_iso(early), [_row("1", "AAA", "g", 2), _row("5", "BBB", "h", 2)])
    c2 = (_iso(mid), [_row("1", "AAA", "g", 9), _row("5", "BBB", "h", 7)])
    sel = _prov([c1, c2])
    # AAA's player: c2 is post-kickoff -> c1 (2 tackles); BBB's player: c2 is pre-kickoff
    assert sel.points["1"] == pytest.approx(2 * CARD_SETTINGS["idp_tkl_solo"])
    assert sel.points["5"] == pytest.approx(7 * CARD_SETTINGS["idp_tkl_solo"])
    assert sel.post_kickoff_ignored == 1


def test_prov_capture_at_exactly_kickoff_is_not_pre_kickoff():
    at = (_iso(KICK_AAA), [_row("1", "AAA", "g", 4)])
    sel = _prov([at])
    assert "1" not in sel.points and "1" in sel.no_pre_kickoff


def test_prov_unknown_kickoff_and_missing_rows_are_distinct_never_zero():
    c = (_iso(KICK_AAA - timedelta(days=1)), [_row("1", "AAA", "g", 3), _row("3", "ZZZ", "z", 3)])
    sel = _prov([c])
    assert set(sel.points) == {"1"}
    assert sel.unknown_kickoff == {"3"}
    assert sel.seen == {"1", "3"}
    assert "9" not in sel.seen


# ── the weekly evaluation ────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def world():
    data = season(6)
    fp, diag = fit_frozen(data, card(), [2, 3, 4])
    frozen = {**FROZEN_BASE, "fit": diag}
    preds = predict_week(data, card(), fp, WEEK)
    early = KICK_AAA - timedelta(days=1)
    caps = [
        (
            _iso(early),
            [
                _row("1", "AAA", "g", 5),
                _row("2", "AAA", "g", 3),
                _row("3", "AAA", "g", 4),
                _row("5", "BBB", "h", 6),
                _row("6", "BBB", "h", 2),
                _row("7", "BBB", "h", 4),
            ],
        ),
        # player 4 only appears AFTER his kickoff: excluded, counted, never 0
        (_iso(KICK_AAA + timedelta(hours=1)), [_row("4", "AAA", "g", 5)]),
    ]
    return data, fp, frozen, preds, _prov(caps)


def _run(world, **kw):
    data, _, frozen, preds, prov = world
    args = dict(
        data=data,
        card=card(),
        frozen=frozen,
        week=WEEK,
        prediction_rows=preds,
        prov=prov,
        resamples=200,
    )
    args.update(kw)
    return evaluate_week(**args)


def test_population_and_exclusions_are_counted_and_listed(world):
    out = _run(world)
    assert out["population"]["players"] == 9
    assert out["population"]["byFamily"] == {"DL": 3, "LB": 2, "DB": 4}
    prov_excl = out["exclusions"]["PROV"]
    assert prov_excl["no_pre_kickoff_capture"] == ["4"]
    assert prov_excl["no_provider_row"] == ["8", "9"]
    assert out["coverage"]["PROV"] == {"rows": 6, "excluded": 3}
    assert out["coverage"]["S0"]["excluded"] == 0
    assert out["population"]["subgroupUnknownExcludedFromSubgroups"] == 1  # player 8
    by = {r["pid"]: r for r in out["rows"]}
    assert by["4"]["PROV"] is None and by["8"]["PROV"] is None  # never scored 0


def test_actuals_are_the_canonical_scorer_over_the_week_stat_line(world):
    from src.league_intel.scorer import score_stat_line

    data = world[0]
    out = _run(world)
    for r in out["rows"]:
        assert r["actual"] == pytest.approx(
            score_stat_line(data.stats[WEEK][r["pid"]], CARD_SETTINGS).total_points, abs=1e-5
        )


def test_point_error_metrics_have_parity_with_the_retrospective_owner(world):
    out = _run(world)
    for model in ("S0", "SNAP", "HYB"):
        for fam in ("DL", "LB", "DB"):
            rows = [
                Prediction(
                    2026,
                    WEEK,
                    r["pid"],
                    r["family"],
                    r["subgroup"],
                    None,
                    model,
                    model,
                    r[model],
                    r["actual"],
                    None,
                    None,
                    (),
                )  # fmt: skip
                for r in out["rows"]
                if r["family"] == fam and r[model] is not None
            ]
            got = out["pointError"]["byModelFamily"][fam][model]
            want = metrics(rows, FROZEN_BASE["lineupDemand"]["topN"][fam])
            assert got["n"] == want["n"]
            assert got["mae"] == pytest.approx(want["mae"], abs=1e-5)
            assert got["bias"] == pytest.approx(want["bias"], abs=1e-5)
            assert got["rmse"] == pytest.approx(want["rmse"], abs=1e-5)
    # a paired bootstrap cell is the owner's, byte for byte
    cell = out["pointError"]["primary"]["SNAP_vs_S0"]["DB"]
    a = [
        Prediction(2026, WEEK, r["pid"], "DB", "x", None, "m", "m", r["SNAP"], r["actual"], None, None, ())
        for r in out["rows"]
        if r["family"] == "DB"
    ]  # fmt: skip
    b = [
        Prediction(2026, WEEK, r["pid"], "DB", "x", None, "m", "m", r["S0"], r["actual"], None, None, ())
        for r in out["rows"]
        if r["family"] == "DB"
    ]  # fmt: skip
    want = bootstrap_delta_mae(a, b, resamples=200)
    assert cell["deltaMae"] == pytest.approx(want["deltaMae"], abs=1e-5)
    assert cell["ci95.0"] == [round(x, 6) for x in want["ci95.0"]]


def test_family_of_primary_endpoints_is_27_and_paired_on_covered_rows(world):
    out = _run(world)
    pe = out["pointError"]
    assert pe["holmFamilySize"] == 27
    assert len([k for k in pe["primary"] if k.endswith("_vs_PROV")]) == 5
    assert len([k for k in pe["primary"] if k.endswith("_vs_S0")]) == 4
    # vs PROV only the 6 PROV-covered rows are paired
    paired = sum(c.get("nRows", 0) for c in pe["primary"]["S0_vs_PROV"].values())
    assert paired == 6
    for fam_cells in pe["primary"].values():
        for cell in fam_cells.values():
            assert cell["holmAdjustedP"] is None or 0 <= cell["holmAdjustedP"] <= 1


def test_prov_has_no_interval_and_challengers_use_frozen_quantiles(world):
    out = _run(world)
    for fam in ("DL", "LB", "DB"):
        assert out["pointError"]["byModelFamily"][fam]["PROV"].get("coverageN", 0) == 0


def test_decisions_are_a_separate_section_and_top_n_uses_paired_rows(world):
    out = _run(world)
    assert "pointError" in out and "decisions" in out
    cell = out["decisions"]["topN"]["S0_vs_PROV"]["LB"]
    assert cell["topN"] == 1 and cell["pairedRows"] == 2
    assert cell["deltaHit"] == pytest.approx(cell["hitModel"] - cell["hitReference"])
    assert out["decisions"]["rosterLineup"]["state"] == "not_computed"
    assert out["decisions"]["streaming"]["state"] == "not_computed"


def test_roster_lineup_and_streaming_with_point_in_time_inputs(world):
    inputs = {
        "source": "synthetic",
        "teams": {
            "t1": {
                "roster": ["1", "2", "3", "4", "5", "6", "7"],
                "pool": ["8", "9"],
                "droppable": ["4", "6", "7"],
            },
            "t2": {"roster": ["1", "2", "3"], "pool": ["9"], "droppable": ["3"]},
        },
    }
    out = _run(world, decision_inputs=inputs)
    rl = out["decisions"]["rosterLineup"]
    assert rl["rosterWeeks"] == 2 and rl["slots"] == ["DL", "DL", "LB", "DB", "DB"]
    for m in ALL_MODELS:
        cell = rl["models"][m]
        assert cell["meanRegretVsCeiling"] >= -1e-9  # never beats the realized ceiling
    # PROV did not project players 4, 7?(7 yes) -> unprojected counted, not zero
    assert rl["unprojectedRosteredDefenders"]["PROV"] >= 1
    st = out["decisions"]["streaming"]
    assert st["teamWeeks"] == 2 and st["pooledOverFamilies"] is True
    assert set(st["paired"]) == {
        f"{m}_vs_{r}"
        for r in ("PROV", "S0")
        for m in (
            ("S0", "SNAP", "OPP", "ROLE", "HYB") if r == "PROV" else ("SNAP", "OPP", "ROLE", "HYB")
        )
    }
    for m in ALL_MODELS:
        assert st["models"][m]["meanOpportunityCost"] >= -1e-9  # the oracle is the ceiling


def test_evaluation_is_deterministic(world):
    a = json.dumps(_run(world), sort_keys=True)
    b = json.dumps(_run(world), sort_keys=True)
    assert a == b


def test_outcome_week_never_enters_the_in_package_predictions(world):
    # predictions are an INPUT made from weeks < W: poisoning week-W outcomes changes
    # actuals but not a single projection
    data, fp, frozen, preds, prov = world
    again = predict_week(data, card(), fp, WEEK)
    assert again == preds


def test_empty_prov_means_every_row_excluded_not_zero(world):
    empty = ProvSelection({}, frozenset(), frozenset(), frozenset(), 0, 0, 0, 0)
    out = _run(world, prov=empty)
    assert out["coverage"]["PROV"] == {"rows": 0, "excluded": 9}
    assert out["pointError"]["byModelFamily"]["DL"]["PROV"] == {"n": 0}


def test_holm_adjust():
    adj = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03, "d": None})
    assert adj["a"] == pytest.approx(0.03)
    assert adj["c"] == pytest.approx(0.06)
    assert adj["b"] == pytest.approx(0.06)  # monotone
    assert adj["d"] is None
