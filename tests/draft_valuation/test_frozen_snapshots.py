"""Batch B (start) — frozen 2026 rookie inputs + completed-class spine curves."""

from __future__ import annotations

import json
import shutil
from decimal import Decimal

import pytest

from src.draft.rookie_auction.curve import compute_curve
from src.draft.rookie_auction.snapshots import (
    CONFIG_DIR,
    SnapshotIntegrityError,
    SpineUnavailableError,
    available_completed_classes,
    canonical_checksum,
    load_completed_class_curve,
    load_frozen_rookie_inputs,
    select_spine_years,
    spine_curves_for,
)
from tests.draft_valuation import _workbook as wb

# Pinned: a frozen snapshot that changes — even with a recomputed checksum —
# must fail here.  Changing these is an owner decision, not a refresh.
PINNED_CHECKSUMS = {
    "frozen_inputs/2026_spreadsheet_baseline.json": "a062fdca8390846ea99a00879b5fa7362c3922a4aa24401d204c3b05433f281b",
    "historical_curves/2024.json": "524a53df99b5afe0e403d4a31e13a10a9b59a81a8b226a2a063ebd659ee79bb3",
    "historical_curves/2025.json": "84c44c923725811409a8b661d9001d9e3864b4636c7b6fc64f2487cbc7428e0b",
    "historical_curves/2026.json": "a1e15dd79c33fcff80079cbcf37b63911fec5b1fb923f83a829922b7a8d61cf3",
}


@pytest.mark.parametrize("rel,checksum", sorted(PINNED_CHECKSUMS.items()))
def test_tracked_snapshots_are_pinned(rel, checksum):
    payload = json.loads((CONFIG_DIR / rel).read_text(encoding="utf-8"))
    assert payload["checksum"]["value"] == checksum
    assert canonical_checksum(payload) == checksum


def test_frozen_baseline_is_column_b_with_provenance():
    frozen = load_frozen_rookie_inputs()
    want = [Decimal(str(v)) for v in wb.inputs()["rookieValues"]["values"]]
    assert list(frozen.values) == want
    assert sum(frozen.values) == Decimal("180036.5")
    assert frozen.is_pre_draft_observation is False
    assert frozen.kind == "owner_approved_provisional_rookie_value_baseline"
    assert frozen.provenance["sourceWorkbookSha256"] == wb.SOURCE_SHA256
    assert frozen.provenance["range"] == "B2:B73"
    assert frozen.picks[0] == "1.01" and frozen.picks[-1] == "6.12"


def test_frozen_baseline_is_not_the_historical_2026_curve():
    frozen = load_frozen_rookie_inputs()
    curve_2026 = load_completed_class_curve(2026)
    assert frozen.values != curve_2026.dollars
    assert sum(curve_2026.dollars) == 1200 and sum(frozen.values) != 1200


@pytest.mark.parametrize("year,col", [(2024, "G"), (2025, "F"), (2026, "H")])
def test_historical_curves_are_the_workbook_columns(year, col):
    curve = load_completed_class_curve(year)
    assert list(curve.dollars) == [Decimal(str(r[col])) for r in wb.rows()]
    assert curve.kind == "spreadsheet_sourced_historical_curve"
    assert curve.provenance["range"] == f"{col}2:{col}73"
    raw = json.loads((CONFIG_DIR / "historical_curves" / f"{year}.json").read_text("utf-8"))
    # Unknown provenance stays unknown, with a reason — never invented.
    for field in ("inputs", "spineYears", "formulaVersion", "draftCompletion"):
        assert raw[field] is None and raw[f"{field}UnavailableReason"]


def test_spine_for_2027_is_2024_2025_2026():
    assert available_completed_classes() == (2024, 2025, 2026)
    assert select_spine_years(2027) == (2024, 2025, 2026)
    assert select_spine_years(2028, [2024, 2025, 2026, 2027]) == (2025, 2026, 2027)
    with pytest.raises(SpineUnavailableError):
        select_spine_years(2026)  # only 2024 and 2025 precede it
    with pytest.raises(SpineUnavailableError):
        select_spine_years(2027, [2025, 2026])


def test_curve_from_frozen_inputs_reproduces_the_workbook_exactly():
    frozen = load_frozen_rookie_inputs()
    years, curves = spine_curves_for(2027)
    assert years == (2024, 2025, 2026)
    result = compute_curve(frozen.values, curves)
    assert list(result.dollars) == [Decimal(str(r["L"])) for r in wb.rows()]
    assert result.total_dollars == Decimal(1200)


# --- tamper refusal -----------------------------------------------------------------


@pytest.fixture()
def config_copy(tmp_path):
    dst = tmp_path / "draft_valuation"
    shutil.copytree(CONFIG_DIR, dst)
    return dst


def _edit(path, mutate):
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_loader_refuses_an_edited_rookie_value(config_copy):
    path = config_copy / "frozen_inputs" / "2026_spreadsheet_baseline.json"
    _edit(path, lambda p: p["values"][0].__setitem__("value", "7581"))
    with pytest.raises(SnapshotIntegrityError, match="checksum"):
        load_frozen_rookie_inputs(config_dir=config_copy)


def test_loader_refuses_an_edited_curve(config_copy):
    path = config_copy / "historical_curves" / "2025.json"
    _edit(path, lambda p: p["dollars"][3].__setitem__("dollars", "78"))
    with pytest.raises(SnapshotIntegrityError, match="checksum"):
        load_completed_class_curve(2025, config_dir=config_copy)


def test_recomputed_checksum_still_refuses_a_broken_curve(config_copy):
    path = config_copy / "historical_curves" / "2025.json"

    def mutate(p):
        p["dollars"][3]["dollars"] = "78"  # pool no longer sums to $1200
        p["checksum"]["value"] = canonical_checksum(p)

    _edit(path, mutate)
    with pytest.raises(SnapshotIntegrityError, match="sum"):
        load_completed_class_curve(2025, config_dir=config_copy)


def test_relabelling_as_a_pre_draft_observation_is_refused(config_copy):
    path = config_copy / "frozen_inputs" / "2026_spreadsheet_baseline.json"

    def mutate(p):
        p["isPreDraftObservation"] = True
        p["checksum"]["value"] = canonical_checksum(p)

    _edit(path, mutate)
    with pytest.raises(SnapshotIntegrityError, match="pre-draft"):
        load_frozen_rookie_inputs(config_dir=config_copy)


def test_missing_snapshot_is_an_error_not_a_substitute(config_copy):
    (config_copy / "historical_curves" / "2024.json").unlink()
    with pytest.raises(SpineUnavailableError):
        spine_curves_for(2027, config_dir=config_copy)
    with pytest.raises(FileNotFoundError):
        load_completed_class_curve(2024, config_dir=config_copy)


def test_reordered_picks_are_refused(config_copy):
    path = config_copy / "frozen_inputs" / "2026_spreadsheet_baseline.json"

    def mutate(p):
        p["values"][0], p["values"][1] = p["values"][1], p["values"][0]
        p["checksum"]["value"] = canonical_checksum(p)

    _edit(path, mutate)
    with pytest.raises(SnapshotIntegrityError, match="order"):
        load_frozen_rookie_inputs(config_dir=config_copy)
