"""Backend half of the strict canonical name-key parity test (debt item D1).

There is exactly ONE cross-language normalizer pair in this repo:

* ``src/utils/name_clean.py::normalize_player_name`` — the strict
  canonical join key (family 1 in that module's key registry).  Keys
  every cross-source join in the contract pipeline, the identity
  matcher, and BDVM (injected as ``name_normalizer``).
* ``frontend/lib/player-name-match.js::normalizePlayerNameKey`` — the
  documented JS mirror.  Keys the news-by-player index, the news
  filters, and the BDVM "Fund gap" column join on ``/rankings`` and
  ``/draft`` (``frontend/lib/bdvm.js``), all of which look up rows a
  backend keyed with the Python function.

That join is load-bearing and nothing checked the two agreed until this
file and its frontend twin.  The failure mode is silent: a drifted key
does not error, it just returns no news / no gap column for the
affected players.

This is not hypothetical.  ``frontend/lib/dynasty-data.js`` carried a
THIRD implementation, also documented as a mirror of the Python
function, which had silently drifted — it was missing the apostrophe
rule, so ``"Ja'Marr Chase"`` produced ``"ja marr chase"`` where the
backend produces ``"jamarr chase"``.  It went unnoticed because it had
no production callers and its own tests happened to use no apostrophe
names.  It was deleted on 2026-07-29 and this test exists so the
surviving pair cannot drift the same way.

BOTH halves assert against ONE fixture,
``tests/fixtures/name_key_cases.json``.  Neither may hardcode an
expectation of its own: if the implementations ever disagree, exactly
one of the two suites goes red against a shared, human-reviewable
statement of what the key means.

Frontend twin: ``frontend/__tests__/name-key-parity.test.js``.

WHAT IS DELIBERATELY NOT PINNED HERE
    ``resolve_canonical_name`` / ``CANONICAL_NAME_ALIASES``.  The alias
    table is intentionally NOT mirrored in JS (see the header of
    ``player-name-match.js``): news player mentions are tagged
    server-side from the live contract's display names, so both sides
    of every lookup already share one vocabulary and a second copy of
    the table would only add a source of truth that drifts.

    The COMPACT key family (``compact_name_key`` here vs
    ``waiver-logic.js::normalizeNameCompact``).  Those two look
    identical and are not — ``str.isalnum()`` is Unicode-aware and
    keeps ``é``, the JS ``[^a-z0-9]`` strip drops it.  They join
    different populations and are never compared, so they are
    documented as independent rather than forced into parity; making
    them equal would change the roster_intel join and the KTC crowd
    FAAB map for every accented name.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.utils.name_clean import normalize_player_name

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "name_key_cases.json"
JS_MIRROR_PATH = REPO_ROOT / "frontend" / "lib" / "player-name-match.js"


def load_cases() -> list[dict[str, str]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise AssertionError(f"{FIXTURE_PATH} has no cases")
    return cases


class TestNameKeyParityBackend(unittest.TestCase):
    def test_fixture_is_present_and_non_trivial(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 25, "corpus is too small to catch drift")
        # The apostrophe rule is the one that actually drifted; a corpus
        # without it would have passed against the broken dynasty-data.js
        # implementation, which is exactly how that drift survived.
        self.assertTrue(
            any("'" in c["input"] or "’" in c["input"] for c in cases),
            "corpus must include apostrophe cases",
        )
        self.assertTrue(
            any(any(ord(ch) > 127 for ch in c["input"]) for c in cases),
            "corpus must include diacritic cases",
        )
        self.assertTrue(
            any(c["input"].rstrip(".").endswith(("Jr", "III", "II", "IV")) for c in cases),
            "corpus must include generational-suffix cases",
        )

    def test_python_matches_the_shared_fixture(self):
        failures = []
        for case in load_cases():
            got = normalize_player_name(case["input"])
            if got != case["expected"]:
                failures.append(f"  {case['input']!r}: expected {case['expected']!r}, got {got!r}")
        if failures:
            self.fail(
                "normalize_player_name diverged from "
                "tests/fixtures/name_key_cases.json:\n" + "\n".join(failures)
            )

    def test_js_mirror_still_exists(self):
        """A deleted / renamed JS mirror must fail here, not silently
        skip.  The frontend half of this pair runs under vitest, which
        pytest does not invoke, so this is the backend's only signal
        that the counterpart is still there."""
        self.assertTrue(JS_MIRROR_PATH.exists(), f"missing JS mirror: {JS_MIRROR_PATH}")
        text = JS_MIRROR_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "export function normalizePlayerNameKey",
            text,
            "player-name-match.js no longer exports normalizePlayerNameKey — the "
            "cross-language pair named in src/utils/name_clean's key registry is gone",
        )


if __name__ == "__main__":
    unittest.main()
