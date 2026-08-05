"""The coordination docs must not give opposite instructions.

WHY THIS EXISTS
===============
Two process documents described branching and merging, in the present
tense, and told an assistant to do opposite things:

* ``ASSISTANT_COORDINATION.md`` — "Merge one task at a time back to
  ``main``."
* ``docs/ORCHESTRATION.md`` §2, headed "REVISED — **effective now**" —
  "Old mode (per-task PR, merge-on-green, ~13 merges/day) is retired.
  **One branch per WORKSTREAM**, not per task. **PR only at integration
  checkpoints.**"

Neither linked to the other, and ``CLAUDE.md`` / ``AGENTS.md`` both point
at the first while the second called itself canonical
("Supersedes ad-hoc per-track instructions").

The second was **time-boxed to two named windows, ~2026-07-29 and
~2026-08-01**, and nothing renewed it. Measured on 2026-08-05, merge
commits per day on ``main``:

    2026-07-29   2
    2026-07-30  12
    2026-07-31   1
    2026-08-03   1
    2026-08-04  37    <- the mode it declared retired, at ~3x the rate

So the expired policy was the one that *sounded* current, and the live
practice was the one a reader would have concluded was superseded.

WHAT THIS GUARDS
================
Not the merge cadence — that is a human call and will change. It guards
the two properties that made the contradiction *invisible*:

1. each document points at the other, so a reader of either learns the
   other exists;
2. neither presents an expired policy as current.

Phrased so that changing the policy is easy and losing the cross-link is
hard, because the cross-link is what was actually missing.

NOT ``livedata``-marked: reads two files, must block.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COORD = REPO_ROOT / "ASSISTANT_COORDINATION.md"
ORCH = REPO_ROOT / "docs" / "ORCHESTRATION.md"

# The §2 heading. Its parenthetical is what tells a reader whether the
# policy below it is live.
_ORCH_S2 = re.compile(r"^##\s*2\.\s*Git & integration policy\s*\(([^)]*)\)", re.M)

# Wording that presents a policy as currently in force.
_PRESENT_TENSE = re.compile(r"effective now|in force now|current policy", re.I)


class TestBothDocsExist(unittest.TestCase):
    """Non-vacuity: every assertion below reads these two paths, and a
    rename would make them all pass over nothing."""

    def test_the_files_are_where_this_test_thinks(self) -> None:
        self.assertTrue(COORD.is_file(), f"{COORD} moved — update this test with it")
        self.assertTrue(ORCH.is_file(), f"{ORCH} moved — update this test with it")


class TestTheyPointAtEachOther(unittest.TestCase):
    """The missing cross-link is the actual defect. Two documents may
    disagree; two documents that disagree *and* do not know about each
    other cannot be reconciled by a reader."""

    def test_coordination_names_orchestration(self) -> None:
        self.assertIn(
            "docs/ORCHESTRATION.md",
            COORD.read_text(encoding="utf-8"),
            msg=(
                "ASSISTANT_COORDINATION.md no longer references docs/ORCHESTRATION.md. "
                "These two both describe branching and merging and once gave opposite "
                "instructions with no link between them — which is how the "
                "contradiction survived. Keep the pointer."
            ),
        )

    def test_orchestration_names_coordination(self) -> None:
        self.assertIn(
            "ASSISTANT_COORDINATION.md",
            ORCH.read_text(encoding="utf-8"),
            msg=(
                "docs/ORCHESTRATION.md no longer references ASSISTANT_COORDINATION.md. "
                "Its §2 policy expired 2026-08-01; without the pointer a reader takes "
                "the expired policy as current."
            ),
        )

    def test_coordination_declares_which_wins(self) -> None:
        """A cross-link alone is not enough — a reader landing on either
        file must learn which one to obey."""
        head = COORD.read_text(encoding="utf-8")[:1200].lower()
        self.assertIn(
            "authority",
            head,
            msg=(
                "ASSISTANT_COORDINATION.md no longer states that it is the authority "
                "for day-to-day branch and merge practice. Two documents that link to "
                "each other but neither of which claims precedence leaves the reader "
                "exactly where they started."
            ),
        )


class TestTheExpiredPolicyIsLabelledExpired(unittest.TestCase):
    def test_section_2_heading_does_not_claim_to_be_current(self) -> None:
        m = _ORCH_S2.search(ORCH.read_text(encoding="utf-8"))
        self.assertIsNotNone(
            m,
            msg=(
                "could not find the '## 2. Git & integration policy (…)' heading in "
                "docs/ORCHESTRATION.md. If the section was renamed, update this test "
                "rather than deleting it — the parenthetical is what tells a reader "
                "whether the policy is live."
            ),
        )
        note = (m.group(1) if m else "").lower()
        self.assertNotIn(
            "effective now",
            note,
            msg=(
                f"docs/ORCHESTRATION.md §2 is headed '({m.group(1) if m else ''})'. It was "
                "headed 'REVISED — effective now' while being time-boxed to two windows "
                "that had already passed, and it contradicted ASSISTANT_COORDINATION.md. "
                "If the policy is genuinely being revived, give it new dates and update "
                "ASSISTANT_COORDINATION.md in the same commit."
            ),
        )
        self.assertRegex(
            note,
            r"expired|historical|superseded",
            msg=(
                "docs/ORCHESTRATION.md §2's heading no longer marks the policy as "
                "expired/historical/superseded. Its integration windows were ~2026-07-29 "
                "and ~2026-08-01; if they have been renewed, say so with the new dates "
                "and reconcile ASSISTANT_COORDINATION.md in the same commit."
            ),
        )

    def test_the_expired_section_says_where_the_live_rule_is(self) -> None:
        text = ORCH.read_text(encoding="utf-8")
        start = text.find("## 2. Git & integration policy")
        section = text[start : text.find("## 2a.", start)] if start >= 0 else ""
        self.assertIn(
            "ASSISTANT_COORDINATION.md",
            section,
            msg=(
                "docs/ORCHESTRATION.md §2 is marked expired but does not name the "
                "document that replaced it. A reader who stops at the strikethrough "
                "has been told what NOT to do and not what to do."
            ),
        )

    def test_the_still_live_rules_are_not_swept_up_in_the_expiry(self) -> None:
        """The asymmetry matters. §2 rule 6 (safety / no cross-agent file
        edits without a registry entry), §2a's git mechanics and §3's
        custodians never expired, and marking the whole section dead
        would quietly discard them."""
        text = ORCH.read_text(encoding="utf-8")
        start = text.find("## 2. Git & integration policy")
        section = text[start : text.find("## 2a.", start)] if start >= 0 else ""
        self.assertRegex(
            section,
            r"(?i)still in force|never expires|not expired",
            msg=(
                "docs/ORCHESTRATION.md §2 no longer distinguishes the expired "
                "integration policy from the safety rules that outlived it. Rule 6 "
                "(no cross-agent file edits without a registry entry) is still live."
            ),
        )


class TestNoPresentTenseContradiction(unittest.TestCase):
    """The general form, so a NEW contradiction is caught rather than
    just the one that was fixed."""

    def test_orchestration_does_not_reassert_batching_as_current(self) -> None:
        text = ORCH.read_text(encoding="utf-8")
        offenders: list[str] = []
        for i, line in enumerate(text.splitlines(), start=1):
            if _PRESENT_TENSE.search(line) and re.search(
                r"integration checkpoint|one branch per workstream|batch", line, re.I
            ):
                offenders.append(f"docs/ORCHESTRATION.md:{i}: {line.strip()[:120]}")
        self.assertEqual(
            offenders,
            [],
            msg=(
                "docs/ORCHESTRATION.md asserts a batching/checkpoint merge policy as "
                "currently effective: " + "; ".join(offenders) + ". "
                "ASSISTANT_COORDINATION.md says 'merge one task at a time'. Change both "
                "or neither."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
