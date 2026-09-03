#!/usr/bin/env python3
"""V1-125 — exact-head zero-live-second-owner composite gate.

This is an orchestration check, not a new ownership methodology.  Every family
below is already reconciled in ``docs/v1/V1_125_RETIREMENT_RECONCILIATION.md``
and delegates to that family's existing deterministic guard.  A missing guard,
an unresolved reconciliation classification, an unmeasured command, or a guard
failure is a failure; missing is never treated as zero.

Exit codes: 0 clean, 1 violation, 2 unmeasured.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RECONCILIATION = REPO / "docs" / "v1" / "V1_125_RETIREMENT_RECONCILIATION.md"
TAG = "[v1-125-zero-owner]"

EXIT_OK, EXIT_VIOLATION, EXIT_UNMEASURED = 0, 1, 2


@dataclass(frozen=True)
class Family:
    unit: str
    capability: str
    command: tuple[str, ...]


# These are the nine V1-applicable historical retirement declarations already
# reconciled on main. C6-U1 is intentionally absent: the completion contract
# classifies that signal-intelligence continuation as POST-V1.
FAMILIES: tuple[Family, ...] = (
    Family(
        "C1-U2",
        "player identity",
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/identity/test_dual_read_zero_divergence.py",
            "tests/identity/test_name_primitives_parity.py",
            "-q",
        ),
    ),
    Family(
        "C1-U3",
        "pick identity",
        (sys.executable, "-m", "pytest", "tests/identity/test_pick_identity_red.py", "-q"),
    ),
    Family(
        "C1-U4",
        "as-of/history ownership",
        (sys.executable, "-m", "pytest", "tests/history/", "-q"),
    ),
    Family(
        "C2-U1",
        "lineup ownership",
        (sys.executable, "-m", "pytest", "tests/lineup/test_single_owner.py", "-q"),
    ),
    Family(
        "C2-U2",
        "replacement ownership",
        (sys.executable, "scripts/replacement_census.py"),
    ),
    Family(
        "C2-U4",
        "Team Strength ownership",
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/roster_intel/test_strength_weakness_single_owner.py",
            "-q",
        ),
    ),
    Family(
        "C2-U5",
        "Team Weakness ownership",
        (
            sys.executable,
            "-m",
            "pytest",
            "tests/roster_intel/test_strength_weakness_single_owner.py",
            "-q",
        ),
    ),
    Family(
        "C3-U1",
        "package construction ownership",
        (sys.executable, "-m", "pytest", "tests/packages/test_construction.py", "-q"),
    ),
    Family(
        "C3-U2",
        "Value Adjustment ownership",
        (sys.executable, "-m", "pytest", "tests/valuation_math/test_single_owner.py", "-q"),
    ),
)

FORBIDDEN_CLASSIFICATIONS = {
    "LIVE_SECOND_OWNER_SETTLED_REPLACEMENT",
    "OWNER_DECISION_REQUIRED",
    "NEEDS_CURRENT_REACHABILITY_CHECK",
}
EXPECTED_CLASSIFICATION = "ALREADY_RETIRED_OR_INERT"


def _reconciliation_rows() -> dict[str, str]:
    if not RECONCILIATION.exists():
        raise FileNotFoundError(RECONCILIATION)
    text = RECONCILIATION.read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    for unit in (f.unit for f in FAMILIES):
        # Restrict to the markdown table row so explanatory prose cannot make a
        # missing classification look present.
        match = re.search(rf"^\| `?{re.escape(unit)}`?.*$", text, flags=re.MULTILINE)
        if match is None:
            continue
        row = match.group(0)
        classifications = re.findall(r"`([A-Z][A-Z_]+)`", row)
        rows[unit] = classifications[-1] if classifications else ""
    return rows


def evaluate(*, run_commands: bool = True) -> tuple[int, list[str]]:
    messages: list[str] = []
    try:
        rows = _reconciliation_rows()
    except (OSError, UnicodeError) as exc:
        return EXIT_UNMEASURED, [f"reconciliation unreadable: {exc}"]

    expected = {f.unit for f in FAMILIES}
    missing = sorted(expected - set(rows))
    if missing:
        return EXIT_UNMEASURED, [f"missing V1-applicable reconciliation rows: {missing}"]

    unresolved = {u: c for u, c in rows.items() if c in FORBIDDEN_CLASSIFICATIONS}
    malformed = {u: c for u, c in rows.items() if c != EXPECTED_CLASSIFICATION}
    if unresolved:
        return EXIT_VIOLATION, [f"unresolved ownership classification(s): {unresolved}"]
    if malformed:
        return EXIT_UNMEASURED, [f"unexpected/unmeasured classification(s): {malformed}"]

    # This exact exclusion is part of the frozen V1 boundary, not a convenience.
    text = RECONCILIATION.read_text(encoding="utf-8")
    if "C6-U1" not in text or "POST-V1" not in text:
        return EXIT_UNMEASURED, ["POST-V1 C6-U1 exclusion is not explicitly recorded"]

    if not run_commands:
        return EXIT_OK, [f"coverage: {len(FAMILIES)}/{len(FAMILIES)} V1-applicable families mapped"]

    failed: list[str] = []
    for family in FAMILIES:
        proc = subprocess.run(
            family.command,
            cwd=REPO,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stdout + "\n" + proc.stderr).strip()[-3000:]
            failed.append(f"{family.unit} {family.capability}: rc={proc.returncode}\n{tail}")
        else:
            messages.append(f"PASS {family.unit} — {family.capability}")

    if failed:
        return EXIT_VIOLATION, failed

    messages.append(
        f"MEASURED: 0 live second owners across {len(FAMILIES)} V1-applicable retirement families"
    )
    return EXIT_OK, messages


def main() -> int:
    code, messages = evaluate(run_commands=True)
    for message in messages:
        print(f"{TAG} {message}")
    if code == EXIT_OK:
        print(f"{TAG} clean")
    elif code == EXIT_UNMEASURED:
        print(f"{TAG} UNMEASURED — never coerced to pass")
    else:
        print(f"{TAG} VIOLATION")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
