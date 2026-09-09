"""Advisory KTC reconciliation for the currently canonical OFFENSE Hill.

This file intentionally contains no champion-specific pins.  Literal pins
made every valid Hill promotion create manual maintenance debt.  The hard
gate now lives in test_hill_percentile_constants_tripwire.py and proves that
runtime constants exactly equal the model-registry champion.  These livedata
checks only ask whether the canonical curve remains sane relative to KTC.
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import _PERCENTILE_REFERENCE_N  # noqa: E402
from src.canonical.player_valuation import (  # noqa: E402
    percentile_to_value,
    rank_to_percentile,
)

KTC_CSV = REPO / "CSVs" / "site_raw" / "ktc.csv"
_PICK_PATTERN = re.compile(r"^\d{4}\s+(Early|Mid|Late)\s+\d", re.IGNORECASE)


def _load_ktc_players_sorted() -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    with KTC_CSV.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            raw = (row.get("value") or "").strip()
            if not name or not raw or _PICK_PATTERN.match(name):
                continue
            try:
                value = int(raw)
            except ValueError:
                continue
            rows.append((name, value))
    rows.sort(key=lambda x: -x[1])
    return rows


def _ours(rank: int) -> int:
    return int(
        percentile_to_value(
            rank_to_percentile(rank, reference_n=_PERCENTILE_REFERENCE_N)
        )
    )


@pytest.fixture(scope="module")
def ktc_players() -> list[tuple[str, int]]:
    if not KTC_CSV.exists():
        pytest.skip(f"KTC fixture missing at {KTC_CSV}")
    rows = _load_ktc_players_sorted()
    if len(rows) < 400:
        pytest.skip(f"KTC fixture too small ({len(rows)} players, need >= 400)")
    return rows


def test_rank_one_remains_near_the_market_anchor(ktc_players):
    _, ktc = ktc_players[0]
    assert abs(_ours(1) - ktc) <= 100


@pytest.mark.parametrize("rank", [25, 50, 100, 150, 200, 300, 400])
def test_canonical_curve_does_not_separate_catastrophically_from_ktc(ktc_players, rank):
    _, ktc = ktc_players[rank - 1]
    ours = _ours(rank)
    pct = abs(ours - ktc) / max(1, ktc)
    assert pct <= 0.60, (
        f"canonical Hill diverges >60% from KTC at rank {rank}: "
        f"ours={ours} ktc={ktc}"
    )


def test_canonical_curve_is_strictly_nonincreasing_at_key_ranks():
    ranks = [1, 5, 12, 25, 50, 100, 150, 200, 300, 400]
    vals = [_ours(r) for r in ranks]
    assert all(a >= b for a, b in zip(vals, vals[1:], strict=False))
