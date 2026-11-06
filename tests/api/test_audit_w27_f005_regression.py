"""Master-site-audit W27-F005 regression (CW-40 P1 re-adjudication, 2026-11-06) -- PARTIAL.

August claim: ``marketGapDirection`` was computed in RANK space (mean retail rank vs mean
consensus rank) where the TE-basis conversion cannot act, so 33 of 33 edge-eligible TEs
were SELL and none BUY.

Closed (pinned by ``tests/api/test_audit_w12_f002_regression.py`` for the stamper, and
here on a real board): the direction is OUR ``rankDerivedValue`` vs KTC Market in VALUE
space; the retired rank-space ``marketGapMagnitude`` is stamped ``None`` on every row.

Still open: on the pinned tracked board the residual skew is real.  Among rows the board
labels (top-250, ``marketGapValueRatio >= 0.05``): TE 22 retail_premium / 1 consensus_premium
(96% SELL).  The audit's 33/0 became 22/1, not a balanced split.  The strict xfail pins
the target shape (TE is not >90% SELL when the other offensive positions are mixed); it
flips if a repair (or an archive-independent change) moves it.  Whether the residual is a
TE basis defect in our value or an artifact of KTC TE++ pricing is a methodology question
(owner-gated), not a routine fix.
"""

from __future__ import annotations

import collections
import json
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20261106_194518.zip"
_MIN_RATIO = 0.05  # frontend/lib/thresholds.js::MARKET_GAP_MIN_VALUE_RATIO
_cache: dict = {}


def _rows() -> list[dict]:
    if "rows" not in _cache:
        if not ARCHIVE.is_file():
            pytest.skip("pinned archive bundle absent")
        from src.api.data_contract import build_api_data_contract

        with zipfile.ZipFile(ARCHIVE) as zf:
            name = next(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            raw = json.loads(zf.read(name))
        _cache["rows"] = build_api_data_contract(raw)["playersArray"]
    return _cache["rows"]


def _labelled_by_position() -> dict[str, collections.Counter]:
    out: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in _rows():
        rank = r.get("canonicalConsensusRank")
        ratio = r.get("marketGapValueRatio")
        if rank is None or rank > 250 or r.get("quarantined") or ratio is None:
            continue
        if ratio < _MIN_RATIO:
            continue
        direction = r.get("marketGapDirection")
        if direction in ("retail_premium", "consensus_premium"):
            out[r["position"]][direction] += 1
    return out


def test_rank_space_gap_is_retired_on_every_row():
    rows = _rows()
    assert all(r.get("marketGapMagnitude") is None for r in rows)
    with_ratio = [r for r in rows if r.get("marketGapValueRatio") is not None]
    assert with_ratio
    for r in with_ratio:
        assert r.get("marketGapDirection") in ("retail_premium", "consensus_premium", "none")


def test_the_august_all_te_sell_shape_is_gone_but_the_skew_is_real():
    counts = _labelled_by_position()
    te = counts["TE"]
    # Not the audit's 33/0 any more: at least one TE is labelled the other way.
    assert te["consensus_premium"] >= 1
    # ...but the skew is still heavy: documents the residual (see strict xfail below).
    assert te["retail_premium"] > te["consensus_premium"]


@pytest.mark.xfail(
    strict=True,
    reason="W27-F005 PARTIAL: TEs are still ~96% SELL among labelled top-250 rows",
)
def test_te_labels_are_not_one_sided():
    te = _labelled_by_position()["TE"]
    total = sum(te.values())
    assert total >= 10
    assert te["retail_premium"] / total <= 0.90
