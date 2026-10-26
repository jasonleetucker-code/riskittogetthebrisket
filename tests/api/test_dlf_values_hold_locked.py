"""DLF Values offense voting (D4) is LOCKED OFF (owner decision 2026-10-20).

OWNER DECISION 2026-10-20 ~10:20 UTC, "Hold D4 for V2"
(``docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md``, addendum;
intake ``docs/OWNER_REQUESTED_TODO.md``): turning on DLF Values offense voting
(``dlf_values_rank_hill_vote``) makes the INCUMBENT outlier filter newly drop
other sources' valid votes on 12-13 offense rows (6 Draft Sharks, plus IDP
Trade Calculator, Yahoo/Boone, KTC Crowd, FantasyPros; Theo Johnson -7.4%) --
the same mechanism class the owner rejected for DLF IDP.  PR #1817 therefore
ships the D2/D3 withdrawal, D5 and the two-way fix now, with D4 default OFF
until outlier-integrity-v2 passes and the owner explicitly approves.  The D4
implementation stays intact, so flipping the default is the only activation
step.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["dlf_values_rank_hill_vote"]`` is not
  ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF;
* with default flags, a real board build lets DLF Values vote -- including
  when a user's source override asks for it with a positive weight.

CHANGING THIS FILE TO LET DLF VALUES VOTE *IS* THE OWNER'S D4 ACTIVATION
DECISION, NOT A TEST FIX.  Do it only in a reviewed PR that carries the
owner's explicit approval, after outlier-integrity-v2 has passed every
mandatory gate (``docs/EXECUTION_PLAN.md`` §0).

``tests/api/test_source_independence_closeout.py`` keeps pinning D4 itself
(flag forced ON in-process) -- evidence tooling, not activation.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import src.api.data_contract as dc
from scripts import verify_owner_held_flags as checker
from src.api import feature_flags
from tests.api import hold_lock_scan as scan
from tests.archive_fixtures import newest_complete_raw_payload

_FLAG = "dlf_values_rank_hill_vote"
_ENV = "RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE"
_KEY = "dlfValuesSfTep"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "DLF Values offense voting (D4) is LOCKED OFF by the owner (decision "
    "2026-10-20, 'Hold D4 for V2'; docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md). "
    "Changing this IS the owner's D4 activation decision, not a test fix: it "
    "requires the owner's explicit approval after outlier-integrity-v2 passes "
    "every mandatory gate."
)


# ── default configuration ─────────────────────────────────────────────────


def test_registry_default_keeps_dlf_values_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION


def test_the_hold_names_the_owner_decision_and_keeps_the_implementation():
    hold = dc.POLICY_SOURCE_VOTE_HOLDS[_KEY]
    assert hold["flag"] == _FLAG and hold["holdWhileFlag"] == "off"
    assert "2026-10-20" in hold["decision"] and "outlier-integrity-v2" in hold["decision"]
    assert "explicit owner approval" in hold["decision"], _ACTIVATION
    # The implementation is intact: still a registered, offense-only, rank-
    # signal DLF member, so the default flip is the only activation step.
    src = next(s for s in dc._RANKING_SOURCES if s["key"] == _KEY)
    assert src["correlation_group"] == "dlf" and src["is_rank_signal"] is True
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # DLF VALUES RANK -> HILL VOTE") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD pending outlier-integrity-v2 + explicit owner approval" in prose
    assert "2026-10-20" in prose


def test_default_flags_hold_dlf_values(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()
    try:
        assert feature_flags.is_enabled(_FLAG) is False, _ACTIVATION
        assert _KEY in dc._policy_source_vote_holds(), _ACTIVATION
    finally:
        feature_flags.reload()


# ── tracked surfaces ──────────────────────────────────────────────────────


def _truthy_assignments(text: str) -> list[str]:
    return scan.forbidden_assignments(text, _ENV, scan.TRUTHY, _FLAG)


def test_the_scan_recognises_every_activation_form():
    forms = [
        f"{_ENV}=1",
        f"export {_ENV}=true",
        f"Environment={_ENV}=on",
        f'Environment="{_ENV}=yes"',
        f"  {_ENV}: '1'",
        f'{{"{_ENV}": 1}}',
        f'os.environ["{_ENV}"] = "1"',
        f"({_ENV}=1 python server.py)",
        f"out=`{_ENV}=1 uvicorn server:app`",
        "F=DLF_VALUES_RANK_HILL_VOTE; export RISKIT_FEATURE_${F}=1",
        f'env[f"RISKIT_FEATURE_{{\'{_FLAG}\'.upper()}}"] = "1"',
    ]
    for form in forms:
        assert _truthy_assignments(form), form
    for prose in (
        f"# activate: {_ENV}=1 + restart",
        f"activation would be ({_ENV}=1 + restart)",
        f"set ``{_ENV}=1``",
        f"{_ENV}=0",
        f"({_ENV}=0 python server.py)",
    ):
        assert not _truthy_assignments(prose), prose


def test_no_tracked_surface_activates_dlf_values():
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


# ── deploy-time effective-flag check ──────────────────────────────────────


def test_the_deploy_check_requires_the_flag_off_and_runs_in_verify_deploy():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-10-20" in decision, _ACTIVATION
    # The checker and the registry must agree, or a deploy would fail (or
    # pass) against the repository's own intent.
    for flag, (want, _d, _c) in checker.OWNER_HELD_FLAGS.items():
        assert feature_flags._DEFAULTS[flag] is want, flag
    verify = (_REPO / "deploy/verify-deploy.sh").read_text(encoding="utf-8")
    assert "scripts/verify_owner_held_flags.py" in verify
    gate = verify[verify.index("scripts/verify_owner_held_flags.py") :]
    assert "exit 1" in gate[: gate.index("fi")], "the check must FAIL the deploy, not warn"


# ── a real board, default flags ───────────────────────────────────────────


@pytest.fixture(scope="module")
def boards():
    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")
    mp = pytest.MonkeyPatch()
    try:
        mp.delenv(_ENV, raising=False)
        feature_flags.reload()
        default = dc.build_api_data_contract(copy.deepcopy(raw))
        # A browser source override cannot lift an owner-policy hold.
        override = {_KEY: {"include": True, "weight": 3.0}}
        overridden = dc.build_api_data_contract(copy.deepcopy(raw), source_overrides=override)
    finally:
        mp.undo()
        feature_flags.reload()
    return {"default": default, "override": overridden}


@pytest.mark.parametrize("which", ["default", "override"])
def test_dlf_values_casts_no_vote(boards, which):
    contract = boards[which]
    observed = False
    for row in contract["playersArray"]:
        if not isinstance(row, dict):
            continue
        name = row.get("displayName")
        if (row.get("canonicalSiteValues") or {}).get(_KEY):
            observed = True
        for field in ("sourceRankMeta", "sourceRanks", "effectiveSourceRanks"):
            assert _KEY not in (row.get(field) or {}), f"{which}: {name} {field}. {_ACTIVATION}"
        assert _KEY not in (row.get("freshnessExcludedSources") or []), (which, name)
    assert observed, "archive carries no DLF Values observation; the lock would be vacuous"
    stamp = (contract.get("privateSourceAvailability") or {})[_KEY]
    assert stamp["holdKind"] == dc.VOTE_HOLD_KIND_OWNER_POLICY and stamp["votes"] is False
    assert contract["sourceVotingEligibility"][_KEY]["status"] == "policy_held", _ACTIVATION
