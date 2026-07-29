"""Pin ``calibrate_canonical_values``' double-calibration tripwire.

``calibration.py`` is the LEGACY remap (percentile power curve +
per-universe scales).  It must refuse any asset already tagged
``_pick_calibration_source == "canonical_pipeline"``, because stacking
that remap on top of a Hill-curve value double-calibrates it.

SCOPE NOTE (2026-07-29).  This file previously also pinned the *emit*
side of that invariant — that ``valuation_result_to_asset_dicts`` wrote
``blended_value == calibrated_value == display_value`` and stamped the
canonical tag.  That emitter belonged to the retired offline
canonical-build engine, had no production caller, and was deleted from
``src/canonical/player_valuation.py``; its tests went with it.  The
consume-side guard below is unchanged and NOT weakened — it now builds
its canonical-tagged fixture directly, which is also a more honest
test: the guard's job is to reject the tag, whoever wrote it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.canonical.calibration import calibrate_canonical_values  # noqa: E402


def _make_canonical_assets(n: int = 20) -> list[dict]:
    """Assets carrying the canonical-pipeline tag the guard looks for."""
    return [
        {
            "asset_key": f"p{i:02d}",
            "display_name": f"Player {i:02d}",
            "universe": "offense_vet",
            "blended_value": 10000 - i * 100,
            "calibrated_value": 10000 - i * 100,
            "display_value": 10000 - i * 100,
            "metadata": {"position": "WR"},
            "_pick_calibration_source": "canonical_pipeline",
        }
        for i in range(1, n + 1)
    ]


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
        msg = str(exc_info.value)
        assert "canonical" in msg.lower()
        # Error message must cite the offending asset's display_name so
        # callers can investigate without grepping the logs.
        assert "Player 01" in msg or "Player 02" in msg or "Player 03" in msg

    def test_raises_even_when_only_one_asset_is_canonical(self):
        # Mixed input: most legacy, one canonical-tagged.  The guard
        # must still fire — it's a defensive tripwire, not a majority
        # vote.
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
