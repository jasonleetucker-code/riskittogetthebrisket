"""Pin the canonical engine's single-curve invariant.

The canonical 6-step Hill-curve pipeline (``src/canonical/player_valuation.py``)
produces display-scaled values in a single pass.  The legacy
``calibration.py`` remap (percentile power curve + per-universe scales)
is explicitly skipped for canonical output — see the
``if not use_canonical_engine:`` gate in
``scripts/canonical_build.py``.

These tests pin that invariant from two directions:

  1. **Emit side** — ``valuation_result_to_asset_dicts`` writes
     ``blended_value == calibrated_value == display_value`` for every
     canonical asset.  The three field names are retained for
     downstream consumers that still read legacy keys, but they
     reference the same Hill-curve value.

  2. **Consume side** — ``calibrate_canonical_values`` raises
     ``RuntimeError`` if called on a canonical-tagged asset, defending
     against accidental double-calibration if the engine-flag gate is
     ever bypassed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.calibration import calibrate_canonical_values
from src.canonical.player_valuation import (
    PlayerInput,
    run_valuation,
    valuation_result_to_asset_dicts,
)


def _make_canonical_assets(n: int = 20) -> list[dict]:
    """Run the full canonical pipeline on a small synthetic roster."""
    players = [
        PlayerInput(
            player_id=f"p{i:02d}",
            display_name=f"Player {i:02d}",
            source_ranks=[float(i), float(i), float(i + 1)],
        )
        for i in range(1, n + 1)
    ]
    result = run_valuation(players)
    return valuation_result_to_asset_dicts(result, universe="offense_vet")


class TestSingleCurveInvariant:
    """Pin: canonical emit writes blended == calibrated == display."""

    def test_three_value_fields_are_equal(self):
        assets = _make_canonical_assets()
        assert assets, "pipeline produced no assets"
        for asset in assets:
            blended = asset["blended_value"]
            calibrated = asset["calibrated_value"]
            display = asset["display_value"]
            assert blended == calibrated == display, (
                f"canonical asset {asset['display_name']!r} "
                f"has diverging value fields: "
                f"blended={blended}, calibrated={calibrated}, display={display}. "
                f"The canonical engine is supposed to emit a single "
                f"Hill-curve value across all three fields."
            )

    def test_every_canonical_asset_carries_pipeline_tag(self):
        assets = _make_canonical_assets()
        for asset in assets:
            assert asset.get("_pick_calibration_source") == "canonical_pipeline", (
                f"asset {asset['display_name']!r} missing canonical pipeline tag; "
                f"the defensive guard in calibrate_canonical_values relies on "
                f"this marker to detect canonical output."
            )


class TestCalibrationRejectsCanonical:
    """Pin: calibrate_canonical_values refuses already-canonical assets."""

    def test_raises_on_canonical_tagged_asset(self):
        assets = _make_canonical_assets(n=5)
        with pytest.raises(RuntimeError, match="canonical Hill-curve pipeline"):
            calibrate_canonical_values(assets)

    def test_raises_error_names_offending_asset(self):
        assets = _make_canonical_assets(n=3)
        with pytest.raises(RuntimeError) as exc_info:
            calibrate_canonical_values(assets)
        # Error message should reference the canonical pipeline and hint
        # at the gate the caller should respect.
        msg = str(exc_info.value)
        assert "canonical" in msg.lower()
        assert "use_canonical_engine" in msg

    def test_raises_even_when_only_one_asset_is_canonical(self):
        # Mixed input: most legacy, one canonical-tagged.  The guard must
        # still fire — it's a defensive tripwire, not a majority vote.
        legacy_assets = [
            {
                "display_name": "Legacy Player",
                "universe": "offense_vet",
                "blended_value": 5000,
            },
        ]
        canonical_assets = _make_canonical_assets(n=1)
        with pytest.raises(RuntimeError, match="canonical Hill-curve pipeline"):
            calibrate_canonical_values(legacy_assets + canonical_assets)

    def test_still_works_on_pure_legacy_assets(self):
        # Sanity: non-canonical assets still calibrate normally.
        legacy_assets = [
            {
                "display_name": f"Legacy Player {i}",
                "universe": "offense_vet",
                "blended_value": 9000 - i * 100,
                "metadata": {"position": "WR"},
            }
            for i in range(10)
        ]
        result = calibrate_canonical_values(legacy_assets)
        assert len(result) == 10
        for asset in result:
            assert "calibrated_value" in asset
