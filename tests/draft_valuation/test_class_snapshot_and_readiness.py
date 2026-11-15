"""Batch B — rookie-class snapshot contract and the report-only readiness detector."""

from __future__ import annotations

import ast
import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from src.draft.rookie_auction import readiness as readiness_mod
from src.draft.rookie_auction.class_snapshot import (
    MODE_ACTUAL,
    MODE_FROZEN_FALLBACK,
    STATUS_COMPLETE,
    STATUS_NOT_READY,
    build_class_candidate,
    class_identity,
    frozen_fallback_snapshot,
)
from src.draft.rookie_auction.league_scope import LeagueNotConfiguredError
from src.draft.rookie_auction.readiness import PROMOTION_ENABLED, evaluate_class_readiness
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    load_frozen_rookie_inputs,
    select_spine_years,
)
from tests.draft_valuation import _workbook as wb


def _row(pid, value, *, years_exp=0, pos="WR", asset="offense", name=None, **extra):
    row = {
        "playerId": pid,
        "canonicalName": name or f"Player {pid}",
        "position": pos,
        "assetClass": asset,
        "yearsExp": years_exp,
        "rankDerivedValue": value,
    }
    row.update(extra)
    return row


def _contract(rows):
    return {"playersArray": rows}


def _class_rows(n, *, start=9000, years_exp=0, idp_every=0):
    rows = []
    for i in range(n):
        pos, asset = ("LB", "idp") if idp_every and i % idp_every == 0 else ("WR", "offense")
        rows.append(_row(f"p{i:03d}", start - 37 * i, years_exp=years_exp, pos=pos, asset=asset))
    return rows


# --- class identity ---------------------------------------------------------------


def test_class_identity_rules():
    assert class_identity({"eligibleDraftYear": 2027, "yearsExp": 3}, observed_nfl_season=2026) == (
        2027,
        "explicit",
    )
    assert class_identity({"yearsExp": 0}, observed_nfl_season=2026) == (2026, "sleeper_years_exp")
    assert class_identity({"yearsExp": 1}, observed_nfl_season=2027) == (2026, "sleeper_years_exp")
    assert class_identity({"yearsExp": 0}, observed_nfl_season=None)[0] is None
    assert class_identity({}, observed_nfl_season=2026)[0] is None
    assert class_identity({"yearsExp": True}, observed_nfl_season=2026)[0] is None


def test_october_2026_rookies_are_the_2026_class_not_2027():
    """The ``rookie`` flag in October names the class already drafted (audit D5)."""
    rows = [{**r, "rookie": True} for r in _class_rows(80, years_exp=0)]
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_NOT_READY
    assert snap.entries == ()
    assert snap.exclusions == {"other_class": 80}
    assert "insufficient_eligible:0/72" in snap.missing_reasons
    with pytest.raises(ValueError, match="never priced"):
        snap.curve_values()


# --- actual-mode candidate --------------------------------------------------------


def test_complete_class_is_sorted_desc_with_stable_tiebreak():
    rows = _class_rows(75, years_exp=0)
    rows[10]["rankDerivedValue"] = rows[11]["rankDerivedValue"]  # a value tie
    rows.reverse()  # input order must not matter
    rows.append(_row("pk", 9999, asset="pick"))
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2027,
        as_of="2027-04-30T00:00:00+00:00",
    )
    assert snap.status == STATUS_COMPLETE and snap.mode == MODE_ACTUAL
    assert len(snap.entries) == 72 and [e.rank for e in snap.entries] == list(range(1, 73))
    vals = snap.curve_values()
    assert all(vals[i] >= vals[i + 1] for i in range(71))
    tied = [e.canonical_player_id for e in snap.entries if e.value == Decimal(9000 - 37 * 11)]
    assert tied == ["p010", "p011"]
    assert snap.exclusions == {"pick_asset": 1}
    assert snap.provenance["eligibleRowsBeforeCut"] == 75


def test_snapshot_hash_is_deterministic_and_content_sensitive():
    kwargs = dict(target_draft_year=2027, league_key="dynasty_main", observed_nfl_season=2027)
    a = build_class_candidate(_contract(_class_rows(72)), **kwargs)
    b = build_class_candidate(_contract(list(reversed(_class_rows(72)))), **kwargs)
    assert a.snapshot_sha256 == b.snapshot_sha256
    rows = _class_rows(72)
    rows[5]["rankDerivedValue"] += 1
    assert build_class_candidate(_contract(rows), **kwargs).snapshot_sha256 != a.snapshot_sha256
    json.dumps(a.to_dict())


def test_duplicate_identity_is_refused_not_chosen():
    rows = _class_rows(80)
    rows.append(_row("p003", 1, name="Same id twice"))
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2026,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_NOT_READY
    assert "duplicate_identity:p003" in snap.missing_reasons
    assert "p003" not in {e.canonical_player_id for e in snap.entries}


def test_same_name_different_ids_are_two_players():
    rows = _class_rows(72)
    rows[0]["canonicalName"] = rows[1]["canonicalName"] = "Mike Williams"
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2026,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_COMPLETE
    assert sum(1 for e in snap.entries if e.name == "Mike Williams") == 2


def test_dynasty_main_includes_idp_rookies():
    rows = _class_rows(90, idp_every=5)
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2026,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_COMPLETE and snap.idp_eligible is True
    assert any(e.asset_class == "idp" for e in snap.entries)
    assert len(snap.entries) == 72


@pytest.mark.parametrize("league", ["dynasty_new", "", None, "anything_else"])
def test_unconfigured_league_fails_closed(league):
    """Owner scope 2026-10-18: dynasty_main only — other leagues are refused, not adapted."""
    snap = build_class_candidate(
        _contract(_class_rows(80)),
        target_draft_year=2026,
        league_key=league,
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_NOT_READY and snap.entries == ()
    assert snap.missing_reasons == (f"league_not_configured:{league}",)
    with pytest.raises(LeagueNotConfiguredError):
        frozen_fallback_snapshot(2027, league_key=league)
    with pytest.raises(LeagueNotConfiguredError):
        select_spine_years(2027, league_key=league)
    report = evaluate_class_readiness(snap, league_key=league)
    assert report.state == "LEAGUE_NOT_CONFIGURED" and report.promotion_authorized is False


@pytest.mark.parametrize("bad", [None, 0, -5, float("nan"), float("inf"), "100", True])
def test_missing_values_are_excluded_never_zero_priced(bad):
    rows = _class_rows(72)
    rows[7]["rankDerivedValue"] = bad
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2026,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_NOT_READY
    assert snap.exclusions == {"no_positive_value": 1}
    assert all(e.value > 0 for e in snap.entries)


def test_prospect_without_sleeper_id_needs_explicit_class():
    rows = _class_rows(71)
    rows.append(_row(None, 50, name="College Prospect"))  # yearsExp only: unprovable
    rows.append(_row(None, 40, name="Listed Prospect", eligibleDraftYear=2026))
    snap = build_class_candidate(
        _contract(rows),
        target_draft_year=2026,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    assert snap.status == STATUS_COMPLETE
    prospect = [e for e in snap.entries if e.name == "Listed Prospect"][0]
    assert (
        prospect.rosterable_on_sleeper is False
        and prospect.canonical_player_id == "name:listed prospect"
    )
    assert snap.exclusions == {"class_unprovable:no_identity": 1}


# --- frozen fallback template -----------------------------------------------------


def test_frozen_fallback_is_a_pricing_template_in_original_order():
    snap = frozen_fallback_snapshot(2027, league_key="dynasty_main")
    frozen = load_frozen_rookie_inputs()
    assert snap.mode == MODE_FROZEN_FALLBACK and snap.status == STATUS_COMPLETE
    assert snap.actual_input_class_year == 2026 and snap.target_draft_year == 2027
    assert snap.as_of == "2026-10-17"
    assert snap.curve_values() == frozen.values  # unsorted golden order kept
    assert all(e.canonical_player_id is None and e.name is None for e in snap.entries)
    assert snap.entries[0].pick == "1.01" and snap.provenance["isPreDraftObservation"] is False


# --- readiness (report-only) ------------------------------------------------------


def test_readiness_today_is_fallback_verified_with_exact_fallback_curve():
    candidate = build_class_candidate(
        _contract(_class_rows(80, years_exp=0)),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    report = evaluate_class_readiness(candidate, league_key="dynasty_main")
    d = report.to_dict()
    assert d["state"] == "FALLBACK_VERIFIED"
    assert d["promotionAuthorized"] is False and d["switchPolicy"] == "owner_approval_required"
    assert d["spineYears"] == [2024, 2025, 2026]
    units = d["fallbackCurveReceipt"]["finalUnits"]
    assert [u / 2 for u in units] == [float(r["L"]) for r in wb.rows()]


def test_complete_candidate_reaches_ready_but_never_promotable():
    candidate = build_class_candidate(
        _contract(_class_rows(72, years_exp=0)),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2027,
    )
    report = evaluate_class_readiness(candidate, league_key="dynasty_main")
    outcomes = {g.name: g.outcome for g in report.gates}
    assert report.state == "CANDIDATE_READY"
    assert report.promotion_authorized is False
    assert outcomes["formula_exact_budget"] == "PASS"
    for name, _ in readiness_mod.POLICY_GATES:
        assert outcomes[name] == "NOT_EVALUATED"
    assert sum(report.candidate_curve_receipt["finalUnits"]) == 2400


def test_incomplete_candidate():
    candidate = build_class_candidate(
        _contract(_class_rows(40, years_exp=0)),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2027,
    )
    assert (
        evaluate_class_readiness(candidate, league_key="dynasty_main").state
        == "CANDIDATE_INCOMPLETE"
    )


def test_corrupted_fallback_is_an_error_state(tmp_path):
    cfg = tmp_path / "draft_valuation"
    shutil.copytree(CONFIG_DIR, cfg)
    p = cfg / "frozen_inputs" / "2026_spreadsheet_baseline.json"
    payload = json.loads(p.read_text("utf-8"))
    payload["values"][0]["value"] = "1"
    p.write_text(json.dumps(payload), "utf-8")
    candidate = build_class_candidate(
        _contract([]),
        target_draft_year=2027,
        league_key="dynasty_main",
        observed_nfl_season=2026,
    )
    report = evaluate_class_readiness(candidate, league_key="dynasty_main", config_dir=cfg)
    assert report.state == "ERROR_FALLBACK_INVALID"


def test_readiness_is_inert():
    assert PROMOTION_ENABLED is False
    src = Path(readiness_mod.__file__).read_text("utf-8")
    tree = ast.parse(src)
    names = {
        n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    } - {"promotion_authorized"}  # a read-only property that always answers False
    assert not any("promot" in n or "activate" in n or "switch" in n for n in names)
    for forbidden in ("open(", "write_text", "os.replace", "requests", "urllib"):
        assert forbidden not in src
