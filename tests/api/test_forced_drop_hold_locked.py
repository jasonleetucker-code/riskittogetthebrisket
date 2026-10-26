"""The forced-drop correctness fix is LOCKED OFF (owner decision 2026-10-21).

OWNER DECISION 2026-10-21, LVA Package 1 (``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md``):
"Keep ``forced_drop_cheapest_legal`` OFF ... I am NOT authorizing activation."
``docs/EXECUTION_PLAN.md`` (P1) records that ``scripts/verify_owner_held_flags.py``
keeps holding it OFF; until this lock that check did not list the flag.  The fix
(#1890, #1912) is merged dormant; turning it on is the owner's separate decision
after the box replay.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["forced_drop_cheapest_legal"]`` is not
  ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL`` to a true-y value
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
from src.api import feature_flags
from src.trade import forced_drop_selection
from tests.api import hold_lock_scan as scan

_FLAG = "forced_drop_cheapest_legal"
_ENV = "RISKIT_FEATURE_FORCED_DROP_CHEAPEST_LEGAL"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The forced-drop correctness fix is LOCKED OFF by the owner (decision 2026-10-21, "
    "LVA Package 1). Turning it on IS the owner's activation decision, not a test fix."
)


def test_registry_default_keeps_the_fix_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION
    assert forced_drop_selection.FLAG == _FLAG


def test_the_registry_comment_names_the_decision():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # Owner decision 2026-10-20 §2 (forced-drop") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "2026-10-21" in prose and "Package 1" in prose


def test_no_tracked_surface_activates_the_fix():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-10-21" in decision and "Package 1" in decision
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
