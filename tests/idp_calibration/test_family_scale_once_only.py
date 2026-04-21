"""Pin: IDP ``family_scale`` is folded into ``rankDerivedValue`` exactly once.

Audit concern R-V6 (see audit dated 2026-04-20): a prior review pass
believed ``family_scale`` was dead code and was about to multiply it a
second time in ``_apply_idp_calibration_post_pass``, which would have
stacked (family × family) on top of each IDP value (≈1.58× at the
current 1.2571 scale).  The current code is correct — ``family_scale``
is pre-folded into the return of
``production.get_idp_bucket_multiplier`` at
``src/idp_calibration/production.py`` — and a load-bearing comment at
``src/api/data_contract.py:3186-3195`` defends against future cleanup
that would reintroduce the bug.

This test makes the invariant executable: with an explicit promoted
config (family_scale=1.1, DL bucket=0.5), the live pipeline must
produce ``rankDerivedValue ≈ rankDerivedValueUncalibrated × 0.5 × 1.3``
for DL rows — a single combined multiplication, NOT a double one.

If anyone re-introduces a second application of ``family_scale`` in
the post-pass, this test will fail loudly instead of silently shifting
the entire IDP board.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract
from src.idp_calibration import production


FAMILY_SCALE = 1.1  # within the [0.85, 1.15] production clamp
DL_BUCKET = 0.5


def _write_config(path: Path) -> None:
    """Write a minimal promoted config with family_scale + single DL bucket."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "active_mode": "blended",
                "family_scale": {
                    "intrinsic": FAMILY_SCALE,
                    "market": 1.0,
                    "final": FAMILY_SCALE,
                },
                "multipliers": {
                    # Single DL bucket spanning all ranks so every DL row
                    # gets the same predictable multiplier under test.
                    "DL": {
                        "position": "DL",
                        "buckets": [
                            {
                                "label": "1-500",
                                "intrinsic": DL_BUCKET,
                                "market": DL_BUCKET,
                                "final": DL_BUCKET,
                                "count": 500,
                            },
                        ],
                    },
                },
                "anchors": {},
            }
        )
    )


def _load_latest_raw() -> dict | None:
    data_dir = REPO / "exports" / "latest"
    files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    if not files:
        return None
    with files[0].open() as f:
        return json.load(f)


def test_family_scale_is_folded_exactly_once(tmp_path, monkeypatch):
    """Full live-pipeline exercise: under an active promoted config,
    ``rankDerivedValue`` for DL rows must equal
    ``uncalibrated × (bucket × family_scale)`` once — never twice.
    """
    raw = _load_latest_raw()
    if raw is None:
        pytest.skip("no latest snapshot for contract rebuild")

    cfg_path = tmp_path / "idp_calibration.json"
    _write_config(cfg_path)
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg_path
    )
    production.reset_cache()

    contract = build_api_data_contract(raw)
    dl_rows = [
        r
        for r in contract.get("playersArray") or []
        if r.get("canonicalConsensusRank")
        and str(r.get("position") or "").upper() == "DL"
    ]
    assert dl_rows, "expected DL rows in the live board"

    expected_combined = DL_BUCKET * FAMILY_SCALE  # 0.65
    checked = 0
    for row in dl_rows:
        uncal = row.get("rankDerivedValueUncalibrated")
        final_val = row.get("rankDerivedValue")
        bucket = row.get("idpCalibrationMultiplier")
        family = row.get("idpFamilyScale")
        if uncal is None or final_val is None:
            continue
        # Skip rows where the market-corridor clamp has pulled the
        # value away from the calibration-folded expectation.  The
        # invariant we're testing is that the CALIBRATION itself
        # folds exactly once — a subsequent clamp operating on the
        # calibrated value is a different transform and is tested
        # separately.
        if row.get("marketCorridorClamp"):
            continue
        # Stamped components match the config exactly.
        assert bucket is not None and abs(bucket - DL_BUCKET) < 1e-6, (
            f"{row.get('canonicalName')}: "
            f"idpCalibrationMultiplier={bucket} != {DL_BUCKET}"
        )
        assert family is not None and abs(family - FAMILY_SCALE) < 1e-6, (
            f"{row.get('canonicalName')}: "
            f"idpFamilyScale={family} != {FAMILY_SCALE}"
        )
        # Combined factor is applied exactly once, not twice.
        expected_once = int(round(float(uncal) * expected_combined))
        expected_twice = int(round(float(uncal) * expected_combined * FAMILY_SCALE))
        assert abs(int(final_val) - expected_once) <= 2, (
            f"{row.get('canonicalName')}: "
            f"rankDerivedValue={final_val}, "
            f"uncal={uncal}, expected_once={expected_once} "
            f"(combined={expected_combined:.4f}). "
            f"family_scale may have been double-applied — "
            f"double-apply expectation would yield ≈{expected_twice}."
        )
        # Defensive: the observed value must NOT match the
        # double-apply expectation.
        assert abs(int(final_val) - expected_twice) > 2, (
            f"{row.get('canonicalName')}: rankDerivedValue={final_val} "
            f"matches double-application of family_scale "
            f"(expected_twice={expected_twice}). family_scale is being "
            f"applied twice."
        )
        checked += 1

    assert checked >= 10, (
        f"expected to exercise many DL rows; checked only {checked}"
    )


def test_family_scale_zero_in_test_env(tmp_path, monkeypatch):
    """Sanity check: with an empty config, production returns identity
    multipliers and no IDP-calibration fields are stamped.  This pins
    the "neutral" branch that the live single-curve invariant test
    relies on.
    """
    cfg_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(
        production, "production_config_path", lambda base=None: cfg_path
    )
    production.reset_cache()

    raw = _load_latest_raw()
    if raw is None:
        pytest.skip("no latest snapshot for contract rebuild")
    contract = build_api_data_contract(raw)

    idp_rows = [
        r
        for r in contract.get("playersArray") or []
        if r.get("canonicalConsensusRank")
        and str(r.get("position") or "").upper() in ("DL", "LB", "DB")
    ]
    assert idp_rows

    offenders = [
        r.get("canonicalName")
        for r in idp_rows
        if r.get("idpCalibrationMultiplier") is not None
        or r.get("idpFamilyScale") is not None
    ]
    assert not offenders, (
        f"IDP calibration fields stamped despite neutral config: "
        f"{offenders[:5]}"
    )
