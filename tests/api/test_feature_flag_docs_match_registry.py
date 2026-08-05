"""Documentation about flag defaults must match ``_DEFAULTS``.

WHY THIS EXISTS
===============
Three places asserted "every feature flag defaults OFF" and that
"nothing in production changes until a flag flips":

* ``docs/ARCHITECTURE.md``
* ``README.md``
* ``src/api/feature_flags.py``'s own module docstring — the file the
  other two point at

**8 of the 16 flags in ``_DEFAULTS`` default ON**, including
``te_basis_conversion``, which reprices every tight end on the live
board, and ``bdvm_engine``, which powers a whole page. A reader
trusting any of those three sentences would have concluded that a live
repricing path was dormant.

That is class 8 of this audit — documentation that misleads the next
reader — and it is the shape with the highest multiplier, because the
next reader makes decisions on it.

WHAT THIS GUARDS, AND WHY IT IS PHRASED THIS WAY
================================================
A test that pinned the exact count (``assert on_count == 8``) would go
red every time someone legitimately adds a flag, and the cheapest way
to make it green again is to bump the number — which teaches people to
re-baseline the guard instead of reading it. That is the
green-by-construction habit ADR-008
(``docs/roster-trade-intelligence/DECISIONS.md``) exists to stop.

So this asserts the *claim*, not the count: **while any flag defaults
ON, no doc may state that flags default OFF.** Adding a flag never
breaks it. Reintroducing the false sentence does. And if the project
ever genuinely moves every flag to OFF, the assertion inverts cleanly
because it reads the registry rather than a hardcoded number.

...AND THAT WAS NOT ENOUGH, AS THIS MODULE'S OWN AUTHOR PROVED
==============================================================
Guarding the claim while ignoring the numbers left the numbers
unguarded, and the very commit that introduced this file replaced a
wrong sentence with a differently-wrong one. All three docs said
**"7 of the 15"**; this docstring said **"8 of the 15"**. The truth on
2026-08-05 is **8 of 16** — every one of them omitted ``perfect_draft``,
a flag that had been LIVE and default-ON for days and that CLAUDE.md
documents at length.

That is this audit's own defect class landing on the audit: a survey
taken once, transcribed into prose, and never compared to the registry
again. The lesson is not "pin the count" — the reasoning above still
holds, and a bare ``== 8`` would still teach re-baselining. It is that
a number written in prose needs the same adversary as a number written
in code.

So the counts and the flag NAMES are now parsed out of the prose and
compared against ``_DEFAULTS`` directly. Adding a flag *does* break
this — correctly, because the sentences enumerate flags by name and
become false the moment one is added. The failure message says exactly
which name and which number, so the fix is mechanical rather than a
re-baseline.

NOT ``livedata``-marked: pure logic over the source tree, must block.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.api.feature_flags import _DEFAULTS

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files that make claims about flag defaults.
_DOCS = (
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "src" / "api" / "feature_flags.py",
)

# Sentences asserting a blanket OFF default. Each is matched against
# text with our own corrective sentences stripped first — otherwise the
# correction ("they do NOT all default OFF") would trip the guard it is
# part of.
_BLANKET_OFF_CLAIMS = (
    re.compile(r"flags?\s+default\s+to\s+\*{0,2}OFF", re.IGNORECASE),
    re.compile(r"\(default\s+OFF\)", re.IGNORECASE),
    re.compile(r"nothing\s+in\s+production\s+changes\s+until\s+a\s+flag\s+flips", re.IGNORECASE),
)

# Lines that are explicitly CORRECTING the claim, not making it.
_NEGATED = re.compile(r"\b(do NOT|does not|never|used to|no longer|false|was not true)\b", re.I)


def _claim_lines(path: Path) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if _NEGATED.search(line):
            continue
        for pattern in _BLANKET_OFF_CLAIMS:
            if pattern.search(line):
                out.append((i, line.strip()))
                break
    return out


class TestFlagDocsMatchRegistry(unittest.TestCase):
    def test_the_registry_still_has_flags_defaulting_on(self) -> None:
        """Non-vacuity guard.

        Every assertion below is conditional on at least one flag
        defaulting ON. If that ever stops being true, the blanket-OFF
        sentences become CORRECT and this module must be revisited
        rather than left asserting a stale prohibition.
        """
        on = sorted(name for name, default in _DEFAULTS.items() if default is True)
        self.assertTrue(
            on,
            msg=(
                "no flag defaults ON any more — the docs this module forbids would now "
                "be accurate. Revisit the prohibition instead of deleting the tests."
            ),
        )

    def test_no_doc_claims_flags_default_off(self) -> None:
        on = sorted(name for name, default in _DEFAULTS.items() if default is True)
        offenders: list[str] = []
        for path in _DOCS:
            if not path.is_file():
                continue
            for line_no, text in _claim_lines(path):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no}: {text}")

        self.assertEqual(
            offenders,
            [],
            msg=(
                "documentation claims feature flags default OFF, but "
                f"{len(on)} of {len(_DEFAULTS)} default ON: {', '.join(on)}.\n"
                "Offending lines:\n  " + "\n  ".join(offenders) + "\n"
                "A reader trusting this concludes a live path is dormant — "
                "te_basis_conversion reprices every TE on the board."
            ),
        )


class TestDocumentedCountsMatchTheRegistry(unittest.TestCase):
    """The half the original module left unguarded.

    Every doc below states an ``N of M`` and then enumerates the ON
    flags by name.  Both halves are checked against ``_DEFAULTS``.
    """

    # "8 of the 16", "8 of 16 entries", "7 of the 15 in `_DEFAULTS`", ...
    _COUNT_RE = re.compile(r"\b(\d+)\s+of\s+(?:the\s+)?(\d+)\b")
    _ON = frozenset(name for name, default in _DEFAULTS.items() if default is True)

    def _claim_files(self) -> list[Path]:
        return [p for p in _DOCS if p.is_file()]

    def test_there_is_something_to_check(self) -> None:
        """Non-vacuity. If the prose stops stating a count, every
        assertion below passes over an empty list — which is exactly how
        the count went unchecked in the first place."""
        found = [p for p in self._claim_files() if self._COUNT_RE.search(p.read_text("utf-8"))]
        self.assertEqual(
            len(found),
            len(self._claim_files()),
            msg=(
                "a doc stopped stating an 'N of M' flag count: "
                f"{sorted(str(p.name) for p in set(self._claim_files()) - set(found))}. "
                "Either restore the sentence or drop the file from _DOCS — silently "
                "checking nothing is the failure mode this class exists to prevent."
            ),
        )

    def test_every_stated_count_is_correct(self) -> None:
        want = (len(self._ON), len(_DEFAULTS))
        wrong: list[str] = []
        for path in self._claim_files():
            for line_no, line in enumerate(path.read_text("utf-8").splitlines(), start=1):
                for m in self._COUNT_RE.finditer(line):
                    got = (int(m.group(1)), int(m.group(2)))
                    # Only judge pairs that are plausibly about flags —
                    # a doc may legitimately say "2 of 3" about
                    # something else on another line.
                    if got[1] not in (len(_DEFAULTS), len(_DEFAULTS) - 1, len(_DEFAULTS) + 1):
                        continue
                    if got != want:
                        rel = path.relative_to(REPO_ROOT)
                        wrong.append(f"{rel}:{line_no}: says {got[0]} of {got[1]}")
        self.assertEqual(
            wrong,
            [],
            msg=(
                f"documented flag counts disagree with _DEFAULTS ({want[0]} of {want[1]}): "
                + "; ".join(wrong)
                + ".\nThis is not a re-baseline prompt — check WHICH flag moved before "
                "editing the number. The commit that added this module said '7 of the 15' "
                "in three files and '8 of the 15' in a fourth, when the answer was 8 of 16; "
                "every one of them had missed perfect_draft."
            ),
        )

    def test_every_enumerated_flag_name_is_actually_on(self) -> None:
        """A correct count with the wrong names is still wrong."""
        bad: list[str] = []
        for path in self._claim_files():
            text = path.read_text("utf-8")
            for name in re.findall(r"[`]{1,2}([a-z][a-z0-9_]{3,})[`]{1,2}", text):
                if name in _DEFAULTS and _DEFAULTS[name] is not True and name in self._ON:
                    bad.append(f"{path.name}: {name}")
        self.assertEqual(bad, [], msg=f"docs name flags as ON that default OFF: {bad}")

    def test_no_on_flag_is_omitted_from_the_enumerations(self) -> None:
        """The exact miss that happened: ``perfect_draft`` was ON, LIVE,
        documented in CLAUDE.md, and absent from every enumeration."""
        missing: list[str] = []
        for path in self._claim_files():
            text = path.read_text("utf-8")
            if not self._COUNT_RE.search(text):
                continue
            for name in sorted(self._ON):
                if f"`{name}`" not in text and f"``{name}``" not in text:
                    missing.append(f"{path.relative_to(REPO_ROOT)}: {name}")
        self.assertEqual(
            missing,
            [],
            msg=(
                "a flag that defaults ON is missing from a doc's enumeration: "
                + "; ".join(missing)
                + ". The count and the list have to move together."
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
