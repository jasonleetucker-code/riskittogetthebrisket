"""The 2026-08-05 audit's findings must stay machine-checked.

WHY THIS EXISTS
===============
Five findings from the unfalsifiable-number audit could not go into
``scripts/audit_status.py``: that table is a status overlay on a
**frozen** registry, keyed by position (``C01…C43``), with no seam for a
finding the frozen artifact does not contain. Left as prose in a
markdown file they were the least durable thing the audit produced — a
list nobody re-probes is exactly what
``docs/audits/remediation-protocol.md`` warns about ("a finding list
maintained by memory would have had someone re-fixing W-2 in batch C9").

So they now have a registry, a generated status file and a probe, reusing
``audit_status``'s ``_probe`` rather than forking it.

WHAT THIS GUARDS
================
The two ways a tripwire quietly stops being one:

1. **A signature that is not present.** An OPEN finding whose signature
   cannot be found is not being tracked — the probe records "absent",
   the checker compares absent-to-absent, and it reports no drift
   forever. This is not hypothetical: **U02 shipped with exactly that
   defect during authoring** (its signature was written from memory as
   ``row_index.get(str(name).strip().lower())`` when the source says
   ``row = row_index.get(key)``), and ``unfalsifiable_status.py`` happily
   reported "no drift" on all six. Only checking presence caught it.
2. **A drifted registry.** Status is generated; if the generated file and
   the registry disagree about membership, the check is running against
   a stale set.

Mirrors ``test_remediation_tooling.py``'s posture, including shelling out
to the script so CI runs the real thing rather than a reimplementation.

NOT ``livedata``-marked: reads the source tree, must block.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY = REPO_ROOT / "docs" / "audits" / "unfalsifiable-number-audit-2026-08-05.registry.json"
STATUS = REPO_ROOT / "docs" / "audits" / "unfalsifiable-number-audit-2026-08-05.status.json"
SCRIPT = REPO_ROOT / "scripts" / "unfalsifiable_status.py"
DOC = REPO_ROOT / "docs" / "audits" / "unfalsifiable-number-audit-2026-08-05.md"


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


class TestTheArtifactsExist(unittest.TestCase):
    """Non-vacuity: every assertion below reads these paths."""

    def test_all_four_are_present(self) -> None:
        for p in (REGISTRY, STATUS, SCRIPT, DOC):
            self.assertTrue(p.is_file(), f"{p.relative_to(REPO_ROOT)} is missing")

    def test_the_registry_has_findings(self) -> None:
        self.assertGreaterEqual(len(_registry().get("findings") or []), 5)


class TestEveryOpenFindingIsActuallyTracked(unittest.TestCase):
    def test_open_findings_have_a_locatable_signature(self) -> None:
        """The one that caught a real defect in this very registry.

        An OPEN finding whose signature is absent is untracked: the
        probe records absent, the checker sees absent, and it reports no
        drift forever. U02 was written with a from-memory signature that
        did not match the source and the tooling reported clean.
        """
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from audit_status import _probe  # noqa: PLC0415

        unlocatable: list[str] = []
        for f in _registry()["findings"]:
            if f.get("status") != "open" or not f.get("signature"):
                continue
            result = _probe(f.get("path"), f["signature"])["result"]
            if result != "signature_present":
                unlocatable.append(f"{f['id']} ({f['path']}): {result}")
        self.assertEqual(
            unlocatable,
            [],
            msg=(
                "these findings are recorded OPEN but their defect signature cannot be "
                "found: " + "; ".join(unlocatable) + ". A signature that does not match "
                "the source tracks nothing — the checker compares absent to absent and "
                "reports no drift. Re-anchor it on text that is actually there, and "
                "confirm it VANISHES when the defect is fixed."
            ),
        )

    def test_every_finding_carries_its_evidence(self) -> None:
        """A finding with no measurement is a claim, not a finding."""
        thin: list[str] = []
        for f in _registry()["findings"]:
            for field in ("measured", "verifiedBy", "userSurface", "consequence"):
                if not str(f.get(field) or "").strip():
                    thin.append(f"{f['id']}.{field}")
        self.assertEqual(thin, [], msg=f"missing evidence fields: {thin}")

    def test_ids_are_unique(self) -> None:
        ids = [f["id"] for f in _registry()["findings"]]
        self.assertEqual(sorted(ids), sorted(set(ids)))


class TestTheGeneratedStatusMatchesTheRegistry(unittest.TestCase):
    def test_membership_agrees(self) -> None:
        reg = {f["id"] for f in _registry()["findings"]}
        st = {f["id"] for f in json.loads(STATUS.read_text(encoding="utf-8"))["findings"]}
        self.assertEqual(
            reg,
            st,
            msg=(
                "the generated status file and the registry disagree about which "
                "findings exist — run `python3 scripts/unfalsifiable_status.py --rebuild`. "
                "Status is GENERATED; the registry is the authority."
            ),
        )

    def test_the_status_file_says_it_is_generated(self) -> None:
        """So nobody edits it by hand and has it silently overwritten."""
        self.assertIn("GENERATED", json.loads(STATUS.read_text(encoding="utf-8"))["note"])


class TestTheCheckerRuns(unittest.TestCase):
    def test_the_script_reports_no_drift(self) -> None:
        """Shell out, so CI exercises the real entry point."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=(
                "scripts/unfalsifiable_status.py reports drift:\n"
                f"{proc.stdout}\n{proc.stderr}\n"
                "A recorded status and the tree disagree. Either a defect was fixed "
                "(mark it closed with the measured effect) or a signature moved "
                "(re-anchor it by content)."
            ),
        )


class TestItDidNotDisturbTheOtherAudit(unittest.TestCase):
    """This audit deliberately does not touch the fix-plan session's
    tooling. Proof, not assertion."""

    def test_the_08_04_checker_still_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "audit_status.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, msg=f"{proc.stdout}\n{proc.stderr}")

    def test_the_probe_is_imported_not_forked(self) -> None:
        """One definition of 'is the signature still there'. If the name
        is ever changed in audit_status.py this fails loudly, which is
        the correct outcome — a silent fork is what this avoids."""
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("from audit_status import _probe", src)
        self.assertNotIn("def _probe", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
