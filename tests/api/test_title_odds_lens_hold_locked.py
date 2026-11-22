"""The trade title-odds lens is LOCKED OFF (owner directive 2026-11-21).

OWNER DIRECTIVE 2026-11-21 (intake DYN10, top-10 item #4; authorization: the
2026-11-21 section of ``docs/EXECUTION_PLAN.md``): anything that changes a
recommendation, verdict or served value ships behind a default-OFF flag, and
turning ANY flag ON is owner-reserved.  ``trade_title_odds_lens`` adds this
season's playoff / championship odds deltas to Analyze Trade
(``src/trade/title_odds_lens.py``).  It never votes, but it is a new served
block, so it is held OFF until the owner turns it on.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["trade_title_odds_lens"]`` is not ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_TRADE_TITLE_ODDS_LENS`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF;
* with default flags the lens module reports itself enabled.

CHANGING THIS FILE TO LET THE FLAG TURN ON *IS* THE OWNER'S ACTIVATION
DECISION, NOT A TEST FIX.
"""

from __future__ import annotations

from pathlib import Path

from scripts import verify_owner_held_flags as checker
from src.api import feature_flags
from src.trade import title_odds_lens
from tests.api import hold_lock_scan as scan

_FLAG = "trade_title_odds_lens"
_ENV = "RISKIT_FEATURE_TRADE_TITLE_ODDS_LENS"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The trade title-odds lens is LOCKED OFF by the owner (directive 2026-11-21, DYN10 #4: "
    "turning any flag ON is owner-reserved). Turning it on IS the owner's activation "
    "decision, not a test fix."
)


def test_registry_default_keeps_the_lens_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION
    assert title_odds_lens.FLAG == _FLAG
    assert feature_flags.gate_status(_FLAG) == feature_flags.LIVE


def test_the_registry_comment_names_the_decision():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # DYN10 #4 (owner directive 2026-11-21") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "2026-11-21" in prose
    assert "owner-reserved" in prose and "byte-identical" in prose


def test_default_flags_leave_the_lens_disabled(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()
    try:
        assert title_odds_lens.enabled() is False, _ACTIVATION
    finally:
        feature_flags.reload()


def test_no_tracked_surface_activates_the_lens():
    for form in (f"{_ENV}=1", f"export {_ENV}=true", f'Environment="{_ENV}=yes"'):
        assert scan.forbidden_assignments(form, _ENV, scan.TRUTHY, _FLAG), form
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_deploy_check_requires_the_flag_off():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-11-21" in decision and "DYN10" in decision, _ACTIVATION
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
    verify = (_REPO / "deploy/verify-deploy.sh").read_text(encoding="utf-8")
    assert "scripts/verify_owner_held_flags.py" in verify
    gate = verify[verify.index("scripts/verify_owner_held_flags.py") :]
    assert "exit 1" in gate[: gate.index("fi")], "the check must FAIL the deploy, not warn"
