"""Load the golden ``Draft Data`` workbook fixture (Batch A evidence)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "draft_valuation"
FIXTURE = FIXTURE_DIR / "workbook_2026_10_17.json"
INPUTS = FIXTURE_DIR / "workbook_2026_10_17_inputs.json"
SOURCE_SHA256 = "50d130e5a34d0bb4c2b7ae02cf8dc2bc5a03081263e17a869ba8f8c2eb1dce88"


@lru_cache(maxsize=1)
def fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def inputs() -> dict:
    return json.loads(INPUTS.read_text(encoding="utf-8"))


def cells(sheet: str = "Draft Data") -> dict:
    return fixture()["cells"][sheet]


def rows() -> list[dict]:
    return fixture()["curve"]["rows"]


def by_row(col: str) -> dict[int, object]:
    return {r["row"]: r[col] for r in rows()}


def sig10(x) -> float:
    """Round to the 10 significant digits a Google Sheets export caches."""
    return float(f"{float(x):.10g}")
