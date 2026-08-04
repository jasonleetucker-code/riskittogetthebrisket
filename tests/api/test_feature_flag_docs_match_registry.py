"""Documentation about flag defaults must match ``_DEFAULTS``.

WHY THIS EXISTS
===============
Three places asserted "every feature flag defaults OFF" and that
"nothing in production changes until a flag flips":

* ``docs/ARCHITECTURE.md``
* ``README.md``
* ``src/api/feature_flags.py``'s own module docstring — the file the
  other two point at

**8 of the 15 flags in ``_DEFAULTS`` default ON**, including
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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
