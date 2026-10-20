"""The DLF IDP vote hold is LOCKED ON (owner decision 2026-10-20, Option 3).

OWNER DECISION 2026-10-20 (``docs/owner/OUTLIER_FILTER_V2_OPTION3_2026-10-20.md``,
intake ``docs/OWNER_REQUESTED_TODO.md`` O3-1..O3-10): DLF IDP and DLF Rookie
IDP do NOT vote.  The incumbent outlier filter's 34-54% moves on a DLF IDP
restore (Trevin Wallace and others, every one caused by the filter newly
discarding a valid Draft Sharks / FantasyPros / IDP Trade Calculator vote)
are NOT accepted, and the #1847 replacement candidate, which failed three of
its six mandatory adversarial tests, is NOT activated.  The hold
``dlf_offense_only_vote`` stays ON until a PREREGISTERED outlier-filter
Version 2 passes every mandatory gate, and then lifts only with the owner's
explicit approval.  The owner's words: "Make sure rebases, merges,
deployments, and default configuration cannot accidentally enable it."

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["dlf_offense_only_vote"]`` is not ``True``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE`` to a false-y value (literal,
  subshell, backtick or indirect ``RISKIT_FEATURE_${...}`` forms --
  ``tests/api/hold_lock_scan.py``);
* a DLF IDP-scoped source exists that the hold does not name;
* with default flags, a real board build lets any DLF IDP source vote --
  including when a user's source override (``POST /api/rankings/overrides``
  -> ``source_overrides``) asks for it with a positive weight.

The production box's untracked ``.env`` is covered at deploy time:
``deploy/verify-deploy.sh`` runs ``scripts/verify_owner_held_flags.py``
against the live process and fails the deploy (auto-rollback) when the hold
is not effectively ON.

CHANGING THIS FILE TO LET DLF IDP VOTE *IS* THE OWNER'S DLF IDP ACTIVATION
DECISION, NOT A TEST FIX.  Do it only in a reviewed PR that carries the
owner's explicit approval, after outlier-filter Version 2 has passed every
mandatory gate (``docs/EXECUTION_PLAN.md`` §0, 2026-10-20 entry).

Board assertions are all-of / none-of over the newest complete archived
scrape, never a count, so an archive or CSV refresh cannot flip them.
``tests/api/test_dlf_offense_only_vote.py`` keeps pinning the restore path
itself (flag forced OFF in-process) -- that is evidence tooling, not
activation; nothing here forbids measuring the restore.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

import src.api.data_contract as dc
from src.api import feature_flags
from tests.api import hold_lock_scan as scan
from tests.archive_fixtures import newest_complete_raw_payload

_FLAG = "dlf_offense_only_vote"
_ENV = "RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE"
_KNOWN_DLF_IDP = frozenset({"dlfIdp", "dlfRookieIdp"})
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "DLF IDP voting is LOCKED OFF by the owner (Option 3, 2026-10-20; "
    "docs/owner/OUTLIER_FILTER_V2_OPTION3_2026-10-20.md). Changing this IS the "
    "owner's DLF IDP activation decision, not a test fix: it requires the "
    "owner's explicit approval after a preregistered outlier-filter Version 2 "
    "passes every mandatory gate."
)


def _dlf_idp_keys() -> frozenset[str]:
    """Every registered DLF-family source that votes on an IDP scope."""
    out = set()
    for src in dc._RANKING_SOURCES:
        key = str(src.get("key") or "")
        if dc.correlation_group_for(key) != "dlf":
            continue
        scopes = [str(src.get("scope") or "")] + [str(s) for s in src.get("extra_scopes") or []]
        if any("idp" in s for s in scopes) or src.get("position_group") in {"DL", "LB", "DB"}:
            out.add(key)
    return frozenset(out)


# ── default configuration ─────────────────────────────────────────────────


def test_registry_default_keeps_the_hold_on():
    assert feature_flags._DEFAULTS[_FLAG] is True, _ACTIVATION


def test_the_hold_is_labelled_temporary_and_names_the_owner_decision():
    hold = dc.POLICY_SOURCE_VOTE_HOLDS["dlfIdp"]
    assert "2026-10-20" in hold["decision"] and "Option 3" in hold["decision"], _ACTIVATION
    assert "temporary" in hold["decision"] and "explicit owner approval" in hold["decision"]
    src = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = src[: src.index(f'    "{_FLAG}": True,')]
    block = block[block.rindex("    # DLF IDP HOLD") :]
    assert "TEMPORARY" in block and "Option 3" in block and "2026-10-20" in block, (
        "the dlf_offense_only_vote registry comment must label the hold TEMPORARY "
        "and cite the owner's Option 3 decision of 2026-10-20"
    )


def test_every_dlf_idp_source_is_under_the_hold():
    keys = _dlf_idp_keys()
    assert _KNOWN_DLF_IDP <= keys, f"DLF IDP sources moved or were renamed: {sorted(keys)}"
    for key in keys:
        hold = dc.POLICY_SOURCE_VOTE_HOLDS.get(key)
        assert hold is not None and hold["flag"] == _FLAG, f"{key}: {_ACTIVATION}"
        assert "holdWhileFlag" not in hold, f"{key}: the hold's own flag names the hold"


def test_default_flags_hold_every_dlf_idp_source(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()
    try:
        assert feature_flags.is_enabled(_FLAG) is True, _ACTIVATION
        assert _dlf_idp_keys() <= set(dc._policy_source_vote_holds()), _ACTIVATION
    finally:
        feature_flags.reload()


# ── deploy / workflow / config / env surfaces ─────────────────────────────
#
# The scanner is shared with the DLF Values lock (``hold_lock_scan``): every
# tracked file under deploy/, .github/, config/, scripts/, src/, frontend/,
# server.py and env / systemd unit files anywhere.  The production box's
# UNTRACKED ``.env`` is covered from the other end by
# ``scripts/verify_owner_held_flags.py``, which deploy/verify-deploy.sh runs
# against the live process (tests/scripts/test_verify_owner_held_flags.py).


def _falsey_assignments(text: str) -> list[str]:
    """Lines that ASSIGN the env var a false-y value.  Prose that tells an
    operator how a lift WOULD be done -- a comment line, ``(VAR=0 + restart``,
    ````VAR=0```` -- is documentation, not configuration."""
    return scan.forbidden_assignments(text, _ENV, scan.FALSEY, _FLAG)


def test_the_scan_recognises_every_assignment_form():
    """The scanner is only a guard if it fires.  Each form below lifts the
    hold in its own config language; each must be caught."""
    forms = [
        f"{_ENV}=0",
        f"export {_ENV}=false",
        f"Environment={_ENV}=off",
        f'Environment="{_ENV}=no"',
        f"  {_ENV}: '0'",
        f'  - {_ENV}="0"',
        f'{{"{_ENV}": "false"}}',
        f'{{"{_ENV}": 0}}',
        f'os.environ["{_ENV}"] = "0"',
        f'monkeypatch.setenv("{_ENV}", "0")',
        # subshell / command substitution / backtick forms
        f"({_ENV}=0 python server.py)",
        f"out=$({_ENV}=0 python -m scripts.x)",
        f"out=`{_ENV}=off uvicorn server:app`",
        f"env {_ENV}=0 ./deploy/deploy.sh",
        # indirect names, in a file that names the flag
        'FLAG=DLF_OFFENSE_ONLY_VOTE\nexport "RISKIT_FEATURE_${FLAG}=0"',
        "N=DLF_OFFENSE_ONLY_VOTE; RISKIT_FEATURE_$N=false ./run.sh",
        f'os.environ[f"RISKIT_FEATURE_{{\'{_FLAG}\'.upper()}}"] = "0"',
    ]
    for form in forms:
        assert _falsey_assignments(form), form
    for prose in (
        f"# Rollback: {_ENV}=0 + restart",
        f"lift the hold ({_ENV}=0 + restart, or flip the default)",
        f"set ``{_ENV}=1``",
        f"see ``{_ENV}=0``",
        f"{_ENV}=1",
        f"({_ENV}=1 python server.py)",
        # an indirect name in a file that never names this flag is not attributable
        'export "RISKIT_FEATURE_${OTHER}=0"',
        '"rollback": f"RISKIT_FEATURE_{name.upper()}=0 + restart"',
    ):
        assert not _falsey_assignments(prose), prose


def test_no_tracked_deploy_config_or_env_surface_lifts_the_hold():
    offenders = scan.surface_offenders(_ENV, scan.FALSEY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


def test_the_scan_reaches_src_server_and_frontend():
    rels = {str(p.relative_to(scan.REPO)) for p in scan.tracked_surface_files()}
    assert "src/api/feature_flags.py" in rels
    assert "deploy/verify-deploy.sh" in rels
    assert not any(r.startswith(("tests/", "docs/")) for r in rels)
    if (scan.REPO / "server.py").is_file():
        assert "server.py" in rels


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
        # A user source override asking for DLF IDP at a raised weight (the
        # ``POST /api/rankings/overrides`` path threads exactly this).  The
        # owner-policy hold is applied AFTER the override gate, so it must
        # not be liftable from a browser.
        override = {k: {"include": True, "weight": 3.0} for k in _dlf_idp_keys()}
        overridden = dc.build_api_data_contract(copy.deepcopy(raw), source_overrides=override)
    finally:
        mp.undo()
        feature_flags.reload()
    return {"default": default, "override": overridden}


@pytest.mark.parametrize("which", ["default", "override"])
def test_no_dlf_idp_source_casts_any_vote(boards, which):
    contract = boards[which]
    held = _dlf_idp_keys()
    observed = False
    for row in contract["playersArray"]:
        if not isinstance(row, dict):
            continue
        name = row.get("displayName")
        if any((row.get("canonicalSiteValues") or {}).get(k) for k in held):
            observed = True
        for field in ("sourceRankMeta", "sourceRanks", "effectiveSourceRanks"):
            leaked = set(row.get(field) or {}) & held
            assert not leaked, f"{which}: {name} {field} carries {leaked}. {_ACTIVATION}"
        withheld = set(row.get("freshnessExcludedSources") or []) & held
        assert not withheld, f"{which}: {name} seats {withheld} as withheld evidence"
    assert observed, "archive carries no DLF IDP observation; the lock would be vacuous"


@pytest.mark.parametrize("which", ["default", "override"])
def test_the_board_stamps_the_hold(boards, which):
    contract = boards[which]
    stamp = contract.get("privateSourceAvailability") or {}
    eligibility = contract.get("sourceVotingEligibility") or {}
    weighting = ((contract.get("sourceWeighting") or {}).get("sources")) or {}
    for key in _dlf_idp_keys():
        assert stamp[key]["holdKind"] == dc.VOTE_HOLD_KIND_OWNER_POLICY, (which, key)
        assert stamp[key]["votes"] is False, f"{which}: {key}. {_ACTIVATION}"
        assert eligibility[key]["status"] == "policy_held", (which, key, eligibility[key])
        assert not (weighting.get(key) or {}).get("votingRows"), (which, key)
