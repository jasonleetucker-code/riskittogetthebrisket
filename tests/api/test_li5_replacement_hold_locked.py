"""The LI-5 replacement-level consolidation is LOCKED OFF (owner decision 2026-10-21).

OWNER DECISION 2026-10-21, LVA Package 3 (``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md``):
"Implement behind a default-OFF flag. No served replacement-level, IDP valuation,
voting or scarcity changes are authorized."  Wiring the consumers dormant (design
phase P3, ``docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md``) is
authorized; serving the new waiver level is not -- that is P4 (evidence and owner
approval) and P5 (activation).

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["replacement_level_li5_consolidation"]`` is
  not ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF.

CHANGING THIS FILE TO LET THE FLAG TURN ON *IS* THE OWNER'S ACTIVATION
DECISION (design P5), NOT A TEST FIX.
"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_owner_held_flags as checker
from src.api import feature_flags
from src.draft import waiver_population
from tests.api import hold_lock_scan as scan

_FLAG = "replacement_level_li5_consolidation"
_ENV = "RISKIT_FEATURE_REPLACEMENT_LEVEL_LI5_CONSOLIDATION"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The LI-5 replacement-level consolidation is LOCKED OFF by the owner (decision "
    "2026-10-21, LVA Package 3). Turning it on IS the owner's activation decision, "
    "not a test fix."
)


def test_registry_default_keeps_the_consolidation_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION
    assert waiver_population.FLAG == _FLAG


def test_the_registry_comment_names_the_decision():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # LI-5 replacement-level consolidation") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "2026-10-21" in prose and "Package 3" in prose


def test_no_tracked_surface_activates_the_consolidation():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-10-21" in decision and "Package 3" in decision
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
