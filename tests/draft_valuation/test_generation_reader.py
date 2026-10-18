"""THE draft-capital generation reader (Batch F, ``generation.py``).

Pins: the reader serves the canonical class curve through the published
resolver; the receipt is read from the SERVED record (never from what the
request computed); the rookie ladder is the canonical curve at the formula's
own size and refuses anything else (missing, never a stretched or flat-spine
curve, never $0); and the health rows the operator alert reads.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.draft.rookie_auction import generation as gen
from src.draft.rookie_auction.curve import FORMULA_VERSION
from src.draft.rookie_auction.published import REPO_STORE
from src.draft.rookie_auction.snapshots import SnapshotIntegrityError, load_frozen_rookie_inputs
from tests.draft_valuation import _workbook as wb
from tests.draft_valuation.test_whole_dollars import EXPECTED_WHOLE

LEAGUE = "dynasty_main"


@pytest.fixture()
def stores(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(REPO_STORE / LEAGUE / "2027", repo / LEAGUE / "2027")
    box = tmp_path / "box"
    return {"store_dirs": [repo, box], "write_dir": box}


def _seed_checksum() -> str:
    import json

    (path,) = sorted((REPO_STORE / LEAGUE / "2027").glob("*.json"))
    return json.loads(path.read_text(encoding="utf-8"))["checksum"]["value"]


def test_reader_serves_the_canonical_curve_identical_to_the_2027_seed(stores):
    g = gen.read_class_generation(LEAGUE, 2027, persist=False, **stores)
    assert g.allocation_state == "current"
    assert list(g.final_whole_dollars) == EXPECTED_WHOLE
    # Identical content: the seed record keeps serving, nothing new is written.
    assert g.allocation.record_checksum == _seed_checksum()
    assert not any((stores["write_dir"]).rglob("*.json"))


def test_receipt_fields_come_from_the_served_record(stores):
    g = gen.read_class_generation(LEAGUE, 2027, persist=False, **stores)
    r = g.receipt()
    assert tuple(r) == gen.RECEIPT_FIELDS
    assert r == {
        "generationHash": _seed_checksum(),
        "curveVersion": FORMULA_VERSION,
        "targetDraftYear": 2027,
        "actualInputClassYear": 2026,
        "spineYears": [2024, 2025, 2026],
        "inputMode": "frozen_fallback",
        "allocationState": "current",
    }


def test_failed_refresh_receipt_describes_the_last_known_good_record(stores):
    def broken(_key, _year):
        raise SnapshotIntegrityError("frozen baseline edited")

    g = gen.read_class_generation(LEAGUE, 2027, persist=False, inputs_fn=broken, **stores)
    assert g.allocation_state == "last_known_good"
    assert "frozen baseline edited" in g.allocation.failed_refresh["reason"]
    r = g.receipt()
    assert r["allocationState"] == "last_known_good"
    assert r["generationHash"] == _seed_checksum()
    assert r["spineYears"] == [2024, 2025, 2026]
    assert list(g.final_whole_dollars) == EXPECTED_WHOLE


def test_no_record_and_no_curve_is_unavailable_with_an_empty_receipt(tmp_path):
    g = gen.read_class_generation(
        LEAGUE, 2026, persist=False, store_dirs=[tmp_path / "none"], write_dir=tmp_path / "w"
    )
    assert g.allocation_state == "unavailable" and g.final_whole_dollars is None
    assert "class_curve_unavailable:SpineUnavailableError" in g.allocation.failed_refresh["reason"]
    r = g.receipt()
    assert r["generationHash"] is None and r["curveVersion"] is None
    assert r["targetDraftYear"] == 2026 and r["allocationState"] == "unavailable"


def test_unconfigured_league_is_unavailable_never_adapted():
    g = gen.read_class_generation("dynasty_new", 2028, persist=False)
    assert g.allocation_state == "unavailable"
    assert g.allocation.unavailable_reason == "league_not_configured:dynasty_new"
    assert g.receipt()["generationHash"] is None


def test_promoted_record_receipt_is_actual_for_its_own_class():
    promoted = SimpleNamespace(
        receipt={
            "formulaVersion": FORMULA_VERSION,
            "provenance": {
                "source": gen.PROMOTED_CLASS_SNAPSHOT_SOURCE,
                "spineYears": [2025, 2026, 2027],
            },
        },
        record_checksum="ab" * 32,
        allocation_state="current",
    )
    r = gen.generation_receipt(promoted, 2028)
    assert r["inputMode"] == "actual"
    assert r["actualInputClassYear"] == 2028
    assert r["spineYears"] == [2025, 2026, 2027]


# --- the rookie ladder ------------------------------------------------------------------


def test_ladder_over_the_frozen_inputs_equals_the_workbook_reference_curve():
    """Independent evidence: the workbook's own cached L (column D/L)."""
    values = list(load_frozen_rookie_inputs().values)
    ladder = gen.rookie_ladder(values, league_key=LEAGUE, draft_year=2027, input_source="frozen")
    assert ladder.state == gen.LADDER_COMPUTED and ladder.reason is None
    sheet_l = [float(v) for v in wb.by_row("L").values()]
    assert list(ladder.dollars) == sheet_l
    assert sum(ladder.dollars) == 1200
    assert ladder.receipt["spineYears"] == [2024, 2025, 2026]
    assert ladder.receipt["curveVersion"] == FORMULA_VERSION


@pytest.mark.parametrize(
    "values, reason",
    [
        ([Decimal(100 - i) for i in range(71)], "inputs_incomplete:need_72_rookies_have_71"),
        ([Decimal(100 - i) for i in range(73)], "inputs_incomplete:need_72_rookies_have_73"),
        ([Decimal(100 - i) for i in range(71)] + [Decimal(0)], "curve_unavailable:CurveInputError"),
    ],
)
def test_ladder_refuses_what_the_formula_does_not_define(values, reason):
    ladder = gen.rookie_ladder(values, league_key=LEAGUE, draft_year=2027, input_source="t")
    assert ladder.dollars is None and ladder.state == gen.LADDER_REFUSED
    assert ladder.reason.startswith(reason)


def test_ladder_refuses_an_unconfigured_league_and_a_class_without_a_spine():
    values = [Decimal(1000 - i) for i in range(72)]
    other = gen.rookie_ladder(values, league_key="dynasty_new", draft_year=2027, input_source="t")
    assert other.dollars is None and other.reason == "league_not_configured:dynasty_new"
    early = gen.rookie_ladder(values, league_key=LEAGUE, draft_year=2026, input_source="t")
    assert early.dollars is None and early.reason.startswith("curve_unavailable:SpineUnavailable")


# --- health rows (operator alerts) ---------------------------------------------------------


def test_health_rows_flag_only_degraded_classes(monkeypatch):
    healthy = gen.generation_health(LEAGUE, [2027], persist=False)
    assert healthy[0]["allocationState"] == "current" and healthy[0]["degraded"] is False

    def broken(_key, _year):
        raise SnapshotIntegrityError("frozen baseline edited")

    monkeypatch.setattr(gen, "class_curve_inputs", broken)
    lkg = gen.generation_health(LEAGUE, [2027], persist=False)
    assert lkg[0]["allocationState"] == "last_known_good" and lkg[0]["degraded"] is True
    assert "frozen baseline edited" in lkg[0]["reason"]

    assert gen.generation_health("dynasty_new", [2028], persist=False)[0]["degraded"] is False
