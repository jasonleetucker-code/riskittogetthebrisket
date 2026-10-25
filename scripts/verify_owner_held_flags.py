"""Fail a deploy whose RUNNING process has an owner-held vote flag in the
wrong state.

The repository locks five owner-held flags by owner decision (three
source-vote flags, one shadow-measurement flag and one dormant
replacement-level flag):

* ``dlf_offense_only_vote`` must be effectively **ON** -- the DLF IDP / DLF
  Rookie IDP vote hold (owner Option 3, 2026-10-20;
  ``tests/api/test_dlf_idp_hold_locked.py``);
* ``dlf_values_rank_hill_vote`` must be effectively **OFF** -- DLF Values
  offense voting, held for outlier-integrity-v2 (owner decision 2026-10-20,
  "Hold D4 for V2"; ``tests/api/test_dlf_values_hold_locked.py``);
* ``source_freshness_schedule_v2`` must be effectively **OFF** -- the owner's
  universal freshness step schedule: implementation and percentages approved,
  activation held (owner decision 2026-10-20 on PR #1831, Option B;
  ``tests/api/test_freshness_v2_hold_locked.py``);
* ``low_value_depth_disclosure_shadow`` must be effectively **OFF** -- the
  low-value depth-note shadow counters: implementation authorized, the shadow
  window is the owner's separate decision (owner decision 2026-10-21, LVA
  Package 4; ``tests/api/test_depth_disclosure_shadow_hold_locked.py``);
* ``replacement_level_li5_consolidation`` must be effectively **OFF** -- the
  LI-5 replacement-level consolidation: implementation authorized behind a
  default-OFF flag, no served replacement-level change authorized (owner
  decision 2026-10-21, LVA Package 3;
  ``tests/api/test_li5_replacement_hold_locked.py``).

A flag ABSENT from the snapshot fails closed, exactly as for D4: this check
runs after the restart, against the process the deploy just started, and
that process's registry carries every flag listed here.

The repository tests lock the registry defaults and every TRACKED
deploy/config/env surface.  They cannot see the production box's untracked
``${APP_DIR}/.env`` (loaded by the systemd unit's ``EnvironmentFile=``), where
one ``RISKIT_FEATURE_...`` line would silently activate a held source.  This
check closes that gap from the other end: it reads the effective flag values
the LIVE process reports on ``/api/status`` (``featureFlags``, i.e.
``feature_flags.effective_flags()`` -- registry default plus the process's
env) and fails when either is wrong.

Fails CLOSED: a missing, malformed or incomplete ``featureFlags`` snapshot is
a failure, because "cannot tell" is not "held".

Called by ``deploy/verify-deploy.sh`` after the service restart.  A non-zero
exit fails verification, which trips ``deploy/deploy.sh``'s ERR trap and its
auto-rollback to the previous revision.  The rollback does NOT edit ``.env``:
an operator must remove the offending override before the next deploy.

Changing a required state here IS the owner's activation decision for that
source, not a deploy fix.

Usage:
    python scripts/verify_owner_held_flags.py <base_url>
    # or: DEPLOY_VERIFY_BASE_URL=http://127.0.0.1:8000 python ...

Exit codes:
  0 -- every owner-held flag is in its required effective state
  1 -- a flag is in the wrong state, or the snapshot is missing/unreadable
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

#: flag -> (required effective value, owner decision, what the wrong state means)
OWNER_HELD_FLAGS: dict[str, tuple[bool, str, str]] = {
    "dlf_offense_only_vote": (
        True,
        "owner decision 2026-10-20 (Option 3): DLF IDP voting is held until a "
        "preregistered outlier-filter Version 2 passes every mandatory gate and "
        "the owner explicitly approves",
        "DLF IDP / DLF Rookie IDP are VOTING in production",
    ),
    "dlf_values_rank_hill_vote": (
        False,
        "owner decision 2026-10-20 ('Hold D4 for V2'): DLF Values offense voting "
        "is held until outlier-integrity-v2 passes and the owner explicitly approves",
        "DLF Values is VOTING on offense rows in production",
    ),
    "source_freshness_schedule_v2": (
        False,
        "owner decision 2026-10-20 on PR #1831 (Option B): the universal freshness "
        "schedule is approved but its activation is held for the owner's explicit "
        "approval (outlier-integrity-v2 overlap)",
        "the universal freshness step schedule is REWEIGHTING source votes in production",
    ),
    "low_value_depth_disclosure_shadow": (
        False,
        "owner decision 2026-10-21, LVA Package 4 (V4, 'approved for shadow measurement "
        "only'): the hidden depth-note shadow counters are implemented dormant; starting "
        "the production shadow window is the owner's separate decision",
        "the depth-note shadow counters are RECORDING trade evaluations in production",
    ),
    "replacement_level_li5_consolidation": (
        False,
        "owner decision 2026-10-21, LVA Package 3 (D2: 'Implement behind a default-OFF "
        "flag. No served replacement-level ... changes are authorized'): the LI-5 waiver "
        "level is wired dormant; activation is the owner's separate decision (design P4/P5)",
        "the LI-5 banded waiver level is REPRICING roster-capacity, droppability and "
        "Perfect Draft cut costs in production",
    ),
}

_ATTEMPTS = 6
_SLEEP_SECONDS = 5
_TIMEOUT_SECONDS = 20


def _env_name(flag: str) -> str:
    return f"RISKIT_FEATURE_{flag.upper()}"


def _effective(entry: object) -> bool | None:
    """``{"enabled": bool, ...}`` (``effective_flags``) or a bare bool
    (``snapshot``).  Anything else is unreadable -> ``None``."""
    if isinstance(entry, bool):
        return entry
    if isinstance(entry, dict) and isinstance(entry.get("enabled"), bool):
        return entry["enabled"]
    return None


def evaluate(status: object) -> list[str]:
    """Violations for one ``/api/status`` payload; empty means every
    owner-held flag is in its required effective state."""
    if not isinstance(status, dict):
        return ["/api/status did not return a JSON object; cannot prove the owner holds"]
    flags = status.get("featureFlags")
    if not isinstance(flags, dict) or not flags:
        return [
            "/api/status carries no featureFlags snapshot; cannot prove the owner-held "
            "vote flags are in force (failing closed)"
        ]
    out = []
    for flag, (required, decision, consequence) in OWNER_HELD_FLAGS.items():
        actual = _effective(flags.get(flag))
        want = "ON" if required else "OFF"
        if actual is None:
            out.append(
                f"{flag}: missing or unreadable in the live featureFlags snapshot; it must "
                f"be effectively {want} ({decision}). Failing closed."
            )
        elif actual is not required:
            got = "ON" if actual else "OFF"
            out.append(
                f"{flag} is effectively {got} on the live process but must be {want}: "
                f"{consequence}. {decision}. Changing it IS the owner's activation "
                f"decision, not a deploy fix. Look for {_env_name(flag)} in the box's "
                f"${{APP_DIR}}/.env (systemd EnvironmentFile) or the service environment "
                f"and remove it."
            )
    return out


def _fetch_status(base_url: str) -> dict | None:
    url = base_url.rstrip("/") + "/api/status"
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "verify-owner-held-flags"})
            with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                reason = f"HTTP {resp.status}"
        except Exception as exc:  # noqa: BLE001
            reason = repr(exc)
        if attempt < _ATTEMPTS:
            print(f"attempt {attempt}/{_ATTEMPTS}: {url} not ready ({reason}); retrying")
            time.sleep(_SLEEP_SECONDS)
    return None


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base_url = (args[0] if args else os.environ.get("DEPLOY_VERIFY_BASE_URL", "")).strip()
    if not base_url:
        print("::error title=No base URL::Pass the server base URL or set DEPLOY_VERIFY_BASE_URL.")
        return 1
    status = _fetch_status(base_url)
    if status is None:
        print(
            "::error title=Owner-held flags unverifiable::/api/status was unreachable; "
            "cannot prove the owner-held vote flags are in force (failing closed)."
        )
        return 1
    violations = evaluate(status)
    for msg in violations:
        print(f"::error title=Owner-held vote flag in the wrong state::{msg}")
    if violations:
        return 1
    for flag, (required, _decision, _c) in OWNER_HELD_FLAGS.items():
        print(f"{flag}: effectively {'ON' if required else 'OFF'} (owner hold in force)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
