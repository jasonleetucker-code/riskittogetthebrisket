"""The rookie-class tether guard is LOCKED OFF until the owner decides.

``pick_class_tether_guard`` (2026-11-21) stops a current-year slot pick from
inheriting the value of a rookie from a DIFFERENT draft class (in season,
"2027 Pick 1.01" tethered to a 2026 rookie).  It moves canonical pick values
(measured in ``docs/picks/PICK_CLASS_GUARD_EVIDENCE_2026-11-21.md``), so its
activation is reserved for the owner, and no owner decision has authorized it.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["pick_class_tether_guard"]`` is not
  ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF.

CHANGING THIS FILE TO LET THE FLAG TURN ON *IS* THE OWNER'S ACTIVATION
DECISION, NOT A TEST FIX.
"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_owner_held_flags as checker
from src.api import data_contract, feature_flags
from tests.api import hold_lock_scan as scan

_FLAG = "pick_class_tether_guard"
_ENV = "RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The rookie-class tether guard is LOCKED OFF: it moves canonical pick values and "
    "its activation is reserved for the owner. Turning it on IS the owner's activation "
    "decision, not a test fix."
)


def test_registry_default_keeps_the_guard_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION
    assert data_contract.PICK_CLASS_TETHER_GUARD_FLAG == _FLAG


def test_the_registry_comment_names_the_hold():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # Rookie-class guard on the current-year pick tether") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "OWNER-RESERVED" in prose
    assert "PICK_CLASS_GUARD_EVIDENCE_2026-11-21" in prose


def test_no_tracked_surface_activates_the_guard():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "owner-reserved" in decision
    assert "PICK_CLASS_GUARD_EVIDENCE_2026-11-21" in decision
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
