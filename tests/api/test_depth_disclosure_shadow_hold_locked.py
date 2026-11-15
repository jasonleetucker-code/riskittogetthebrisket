"""The depth-note shadow counters are LOCKED OFF (owner decision 2026-10-21).

OWNER DECISION 2026-10-21, LVA Package 4 (``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md``):
"APPROVED FOR SHADOW MEASUREMENT ONLY ... Authorize implementation of the
hidden shadow counters behind a default-OFF flag".  Implementing and merging
them dormant is authorized; starting the production shadow window is not --
the owner separates developing code from activating production behaviour.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["low_value_depth_disclosure_shadow"]`` is
  not ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF.

CHANGING THIS FILE TO LET THE COUNTERS RUN *IS* THE OWNER'S SHADOW-WINDOW
DECISION (design gate G3), NOT A TEST FIX.
"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_owner_held_flags as checker
from src.api import feature_flags
from tests.api import hold_lock_scan as scan

_FLAG = "low_value_depth_disclosure_shadow"
_ENV = "RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE_SHADOW"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The depth-note shadow counters are LOCKED OFF by the owner (decision 2026-10-21, "
    "LVA Package 4). Turning them on IS the owner's shadow-window decision, not a test fix."
)


def test_registry_default_keeps_the_counters_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION


def test_the_registry_comment_names_the_decision():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # Low-value depth disclosure SHADOW COUNTERS") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "2026-10-21" in prose and "Package 4" in prose


def test_no_tracked_surface_activates_the_counters():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-10-21" in decision and "Package 4" in decision
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
