"""The composed Team Advisor plan is LOCKED OFF until the owner decides.

``team_advisor_plan`` (2026-11-21, DYN10 top-10 item #2) gates
``GET /api/team/plan``, which serves new recommendations composed from the
existing owners.  The 2026-11-21 authorization (``docs/EXECUTION_PLAN.md``)
reserves "turning any flag ON" for the owner, and no owner decision has
authorized it.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["team_advisor_plan"]`` is not ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets ``RISKIT_FEATURE_TEAM_ADVISOR_PLAN``
  to a true-y value (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the box's
  untracked ``.env``) stops requiring the flag OFF.

CHANGING THIS FILE TO LET THE FLAG TURN ON *IS* THE OWNER'S ACTIVATION
DECISION, NOT A TEST FIX.
"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_owner_held_flags as checker
from src.api import feature_flags, team_plan
from tests.api import hold_lock_scan as scan

_FLAG = "team_advisor_plan"
_ENV = "RISKIT_FEATURE_TEAM_ADVISOR_PLAN"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The composed Team Advisor plan is LOCKED OFF: it serves new recommendations and "
    "its activation is reserved for the owner. Turning it on IS the owner's activation "
    "decision, not a test fix."
)


def test_registry_default_keeps_the_plan_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION
    assert team_plan.FLAG == _FLAG
    assert feature_flags.gate_status(_FLAG) == feature_flags.LIVE


def test_the_registry_comment_names_the_hold():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # Composed Team Advisor plan") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "OWNER-RESERVED" in prose
    assert "test_team_plan_hold_locked" in prose


def test_no_tracked_surface_activates_the_plan():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "owner-reserved" in decision
    assert "2026-11-21" in decision
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
