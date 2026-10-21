"""The universal freshness schedule (v2) is LOCKED OFF (owner decision 2026-10-20).

OWNER DECISION 2026-10-20 on PR #1831, OPTION B
(``docs/owner/PR1831_OPTION_B_DECISION_2026-10-20.md``; intake
``docs/OWNER_REQUESTED_TODO.md``): merge the universal freshness schedule with
``source_freshness_schedule_v2`` OFF by default.  The implementation and the
freshness percentages (0-7 days 100%, 8-14 75%, 15-21 50%, 22-30 25%, >30 0%)
are APPROVED; activation is NOT.  Turned on, the schedule moved 918 values
(LaJohntay Wester +42.9%), and the INCUMBENT outlier filter can remove
legitimate source votes when the voting population changes -- the defect
outlier-integrity-v2 exists to fix.  The implementation stays intact, so
flipping the default is the only activation step.

This file is that lock.  It fails if:

* the registry default ``_DEFAULTS["source_freshness_schedule_v2"]`` is not
  ``False``;
* any tracked deploy / workflow / config / script / src / frontend /
  ``server.py`` / env / systemd surface sets
  ``RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2`` to a true-y value
  (``tests/api/hold_lock_scan.py``);
* the deploy-time check (``scripts/verify_owner_held_flags.py``, run by
  ``deploy/verify-deploy.sh`` against the live process, which covers the
  box's untracked ``.env``) stops requiring the flag OFF;
* with default flags, a real board build weights a vote with the step
  schedule, or differs in any way from the same build with the flag
  explicitly OFF.

CHANGING THIS FILE TO LET THE SCHEDULE WEIGHT VOTES *IS* THE OWNER'S
FRESHNESS ACTIVATION DECISION, NOT A TEST FIX.  Do it only in a reviewed PR
that carries the owner's explicit approval (``docs/EXECUTION_PLAN.md`` §0).

The schedule's own tests (``tests/sources/test_freshness_schedule_v2.py``,
``tests/api/test_universal_freshness_schedule.py``) keep pinning it with the
flag forced ON in-process -- evidence tooling, not activation.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

import src.api.data_contract as dc
from scripts import verify_owner_held_flags as checker
from src.api import feature_flags
from src.sources import freshness
from tests.api import hold_lock_scan as scan
from tests.archive_fixtures import newest_complete_raw_payload

_FLAG = "source_freshness_schedule_v2"
_ENV = "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2"
_REPO = Path(__file__).resolve().parents[2]

_ACTIVATION = (
    "The universal freshness schedule (v2) is LOCKED OFF by the owner (decision "
    "2026-10-20 on PR #1831, Option B; docs/owner/PR1831_OPTION_B_DECISION_2026-10-20.md). "
    "Changing this IS the owner's freshness activation decision, not a test fix: it "
    "requires the owner's explicit approval."
)


# ── default configuration ─────────────────────────────────────────────────


def test_registry_default_keeps_the_schedule_off():
    assert feature_flags._DEFAULTS[_FLAG] is False, _ACTIVATION


def test_the_registry_comment_names_the_decision():
    text = (_REPO / "src/api/feature_flags.py").read_text(encoding="utf-8")
    block = text[: text.index(f'    "{_FLAG}": False,')]
    block = block[block.rindex("    # The owner's universal freshness SCHEDULE") :]
    prose = " ".join(line.strip().lstrip("#").strip() for line in block.splitlines())
    assert "HELD, DEFAULT OFF" in prose and "Option B" in prose
    assert "2026-10-20" in prose and "outlier-integrity-v2" in prose
    assert "percentages are APPROVED" in prose


def test_default_flags_select_the_v1_rule(monkeypatch):
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()
    try:
        assert feature_flags.is_enabled(_FLAG) is False, _ACTIVATION
        assert freshness.active_schedule() == freshness.SCHEDULE_V1, _ACTIVATION
    finally:
        feature_flags.reload()


def test_the_approved_schedule_stays_intact():
    """Option B keeps the approved percentages; the lock is on activation only."""
    data = json.loads(freshness.SCHEDULE_CONFIG_PATH.read_text(encoding="utf-8"))
    assert [(s["maxDays"], s["freshness"]) for s in data["schedule"]] == [
        (7, 1.0),
        (14, 0.75),
        (21, 0.5),
        (30, 0.25),
    ]
    assert data["beyondMaxFreshness"] == 0.0
    sched = freshness.load_step_schedule()
    assert [sched.freshness_for_days(d) for d in (0, 7, 8, 14, 15, 21, 22, 30, 31)] == [
        1.0,
        1.0,
        0.75,
        0.75,
        0.5,
        0.5,
        0.25,
        0.25,
        0.0,
    ]


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
        "F=SOURCE_FRESHNESS_SCHEDULE_V2; export RISKIT_FEATURE_${F}=1",
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


def test_no_tracked_surface_activates_the_schedule():
    offenders = scan.surface_offenders(_ENV, scan.TRUTHY, _FLAG)
    assert not offenders, f"{_ACTIVATION} Offending surfaces: {offenders}"


# ── deploy-time effective-flag check ──────────────────────────────────────


def test_the_deploy_check_requires_the_flag_off_and_runs_in_verify_deploy():
    required, decision, _consequence = checker.OWNER_HELD_FLAGS[_FLAG]
    assert required is False and "2026-10-20" in decision and "#1831" in decision, _ACTIVATION
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
        dc._SOURCE_WEIGHTING_CACHE.clear()
        default = dc.build_api_data_contract(copy.deepcopy(raw))
        mp.setenv(_ENV, "0")
        feature_flags.reload()
        dc._SOURCE_WEIGHTING_CACHE.clear()
        explicit_off = dc.build_api_data_contract(copy.deepcopy(raw))
    finally:
        mp.undo()
        feature_flags.reload()
    return {"default": default, "off": explicit_off}


def _value_fingerprint(contract: dict) -> list[tuple]:
    out = []
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        meta = row.get("sourceRankMeta") or {}
        out.append(
            (
                row.get("displayName"),
                row.get("rankDerivedValue"),
                row.get("canonicalConsensusRank"),
                row.get("confidenceBucket"),
                tuple(sorted((k, (m or {}).get("appliedWeight")) for k, m in meta.items())),
            )
        )
    return out


def test_default_board_uses_the_v1_rule(boards):
    contract = boards["default"]
    sw = contract.get("sourceWeighting") or {}
    assert sw.get("curve") != "STEP_V2", _ACTIVATION
    for key, entry in (sw.get("sources") or {}).items():
        assert "freshnessSchedule" not in json.dumps(entry), (key, _ACTIVATION)
    status = contract.get("sourceVotingStatus") or {}
    # The voting status reports the rule actually in force (v1) ...
    assert status.get("freshnessSchedule") == freshness.SCHEDULE_V1, _ACTIVATION
    # ... and any v2 figure on it is the labelled, non-voting shadow.
    for entry in status.get("sources") or []:
        shadow = entry.get("shadowScheduleV2")
        if shadow is not None:
            assert shadow["votes"] is False, entry["key"]
    if "shadow" in status:
        assert status["shadow"]["votes"] is False


def test_default_board_is_the_explicit_flag_off_board(boards):
    assert _value_fingerprint(boards["default"]) == _value_fingerprint(boards["off"]), _ACTIVATION


def test_a_failing_shadow_is_stamped_and_moves_nothing(boards, monkeypatch):
    """The non-voting v2 shadow can never break or reprice a build."""
    raw, _name = newest_complete_raw_payload()
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()

    def _boom(*_a, **_k):
        raise RuntimeError("shadow unavailable")

    monkeypatch.setattr(dc, "_source_weighting_shadow_v2", _boom)
    try:
        contract = dc.build_api_data_contract(copy.deepcopy(raw))
    finally:
        feature_flags.reload()
    assert _value_fingerprint(contract) == _value_fingerprint(boards["default"])
    status = contract["sourceVotingStatus"]
    if (contract.get("sourceWeighting") or {}).get("measured"):
        assert status["shadow"]["available"] is False
        assert "shadow unavailable" in status["shadow"]["error"]
        assert all("shadowScheduleV2" not in e for e in status["sources"])
