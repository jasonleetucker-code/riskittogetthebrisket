"""V1-52: the legacy power engine must never come back.

``src/public_league/power.py`` (the pre-V1-52 v1 engine, superseded by
``src/ros/power_v2.py``) and its renderer are DELETED, not deprecated —
see ``docs/power/V1_52_CANONICAL_POWER_ENGINE.md`` "Step 5, corrected".
This is a structural reachability guard, same idiom as
``test_h_schedule_module_has_no_remote_downloader``: it asserts the file
is gone AND that the aggregate contract's eager section registry has no
path back to it, so a future change that quietly reintroduces either one
goes RED here rather than silently shipping a second power engine.

Mutation-proved (see the PR description) by temporarily restoring a stub
``power.py`` and re-registering it in ``_SECTION_BUILDERS``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.public_league import public_contract

_REPO_ROOT = Path(__file__).resolve().parents[2]


class LegacyPowerEngineRetiredTests(unittest.TestCase):
    def test_the_legacy_module_file_does_not_exist(self) -> None:
        legacy_path = _REPO_ROOT / "src" / "public_league" / "power.py"
        self.assertFalse(
            legacy_path.exists(),
            "src/public_league/power.py must stay deleted -- V1-52 retired it "
            "as the second power engine; do not restore it, even as a shim.",
        )

    def test_the_legacy_test_module_does_not_exist(self) -> None:
        legacy_test_path = _REPO_ROOT / "tests" / "public_league" / "test_power.py"
        self.assertFalse(
            legacy_test_path.exists(),
            "tests/public_league/test_power.py tested the retired engine; "
            "its return would mean the engine came back too.",
        )

    def test_no_power_key_in_the_eager_section_registry(self) -> None:
        self.assertNotIn(
            "power",
            public_contract._SECTION_BUILDERS,
            "'power' must not reappear in _SECTION_BUILDERS -- that key "
            "belongs to the retired v1 engine. The canonical engine is "
            "addressed at 'rosPower' in _LAZY_SECTION_BUILDERS.",
        )

    def test_rosPower_is_still_the_lazy_canonical_section(self) -> None:
        """The guard above is meaningless if it silently degenerated into
        checking that NOTHING renders power rankings."""
        self.assertIn("rosPower", public_contract._LAZY_SECTION_BUILDERS)

    def test_public_section_keys_excludes_power(self) -> None:
        self.assertNotIn("power", public_contract.PUBLIC_SECTION_KEYS)
