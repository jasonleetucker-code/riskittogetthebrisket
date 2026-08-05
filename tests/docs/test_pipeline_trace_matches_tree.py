"""The pipeline trace doc must describe the tree it claims to trace.

WHY THIS EXISTS
===============
``docs/architecture/live-value-pipeline-trace.md`` opens with "This is a
reference for what actually runs in production" and closes the loop with
"when this doc drifts from the code, trust the code". That instruction
is not a defence — it tells a reader what to do *after* they have
already been misled, and nothing measured the gap. Measured on
2026-08-05, the gap was:

* **Phase 4c documented as a live stage.** With line numbers, stamped
  field names, and a regression test. ``_apply_idp_calibration_post_pass``
  is not in the tree; neither is ``config/idp_calibration.json``,
  ``src/idp_calibration/`` nor ``tests/idp_calibration/``. The most
  convincing possible account of a thing that is not there.
* **The auto-commit path ADR-008 deleted, advertised as live.** The doc
  said the weekly workflow "rewrites the constants in
  player_valuation.py, and rebaselines the KTC reconciliation test
  pins". ``auto_refit_hill_curves.py`` says the opposite in its own
  docstring: it produces a challenger and stops; a human promotes. A
  reader trusting the doc would conclude the promotion gate they were
  about to bypass did not exist.
* **A source table that did not match the registry.** 16 sources listed
  against 21 registered: three invented (``ktc``, ``footballGuysSf``,
  ``footballGuysIdp``), eight omitted **including the anchor
  ``ktcSfTep``**, and ``idpTradeCalc`` given weight 2.0 when every
  registry weight is 1.0 by policy.
* Refit cadence given as monthly; the cron is weekly (``17 6 * * 2``).
* The flat ``value *= 1.15`` TE boost, replaced by the measured basis
  conversion in ADR-015 on 2026-07-27.

WHAT THIS ASSERTS
=================
Two mechanical properties, both derived rather than transcribed:

1. the source table's key set equals ``_RANKING_SOURCES``;
2. every repo-looking path the file cites exists on disk.

Neither would have needed a human to notice. Both would have caught
every item above except the cadence and the TE constant, which are
content rather than structure — so the doc now also carries the date it
was verified and the name of this file, which is the part a reader can
act on.

This does not attempt to verify prose. A doc test that tried would be
unmaintainable; one that checks the two things a machine CAN check
turns silent rot into a build failure.

NOT ``livedata``-marked: reads the source tree, must block.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.api.data_contract import get_ranking_source_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "architecture" / "live-value-pipeline-trace.md"

# A backticked token that looks like a repo path: has a directory
# separator or a known source extension, and no shell/glob syntax.
_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|json|yml|yaml|jsx|js))`")

# Paths the doc names *because they are gone* — the corrective sentences
# would otherwise trip the guard they are part of.
_DELIBERATELY_ABSENT = frozenset(
    {
        "config/idp_calibration.json",
        "src/idp_calibration/",
        "tests/idp_calibration/",
        "src/canonical/transform.py",
        "src/canonical/pipeline.py",
        # Retired with the offline canonical-build path in PR #173,
        # named by the doc precisely to say it is retired.
        "scripts/canonical_build.py",
    }
)


def _doc_source_keys() -> set[str]:
    rows = re.findall(r"^\| `([A-Za-z0-9_]+)` \| overall", DOC.read_text(encoding="utf-8"), re.M)
    return set(rows)


class TestTheDocExists(unittest.TestCase):
    def test_the_file_is_there(self) -> None:
        """Non-vacuity: every assertion below reads this file, and a
        rename would make them all pass against nothing."""
        self.assertTrue(DOC.is_file(), f"{DOC} is missing — update this test with it")


class TestSourceTableMatchesRegistry(unittest.TestCase):
    def test_the_registry_is_non_empty(self) -> None:
        self.assertGreater(len(get_ranking_source_registry()), 15)

    def test_the_doc_table_was_parsed(self) -> None:
        """Guards the regex, not the doc. If the table's markdown shape
        changes, the comparison below silently compares two empty sets
        and passes — which is exactly the failure mode this module is
        about."""
        self.assertGreater(
            len(_doc_source_keys()),
            15,
            msg=(
                "parsed fewer than 16 source rows out of the doc. Either the table "
                "shrank or its markdown shape changed and this test stopped reading "
                "it — fix the regex rather than the expectation."
            ),
        )

    def test_no_phantom_or_missing_sources(self) -> None:
        registry = {s["key"] for s in get_ranking_source_registry()}
        documented = _doc_source_keys()
        phantom = sorted(documented - registry)
        missing = sorted(registry - documented)
        self.assertEqual(
            {"phantom": phantom, "missing": missing},
            {"phantom": [], "missing": []},
            msg=(
                "the pipeline trace's source table has drifted from _RANKING_SOURCES. "
                f"It invents {phantom or 'nothing'} and omits {missing or 'nothing'}. "
                "This table was 16 rows against a registry of 21 before 2026-08-05, "
                "with the anchor ktcSfTep among the omissions — regenerate it from "
                "the registry rather than hand-patching."
            ),
        )

    def test_documented_weights_match_the_registry(self) -> None:
        registry = {s["key"]: float(s.get("weight") or 1.0) for s in get_ranking_source_registry()}
        wrong: list[str] = []
        for line in DOC.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\| `([A-Za-z0-9_]+)` \| overall[^|]*\| ([0-9.*]+) \|", line)
            if not m:
                continue
            key, shown = m.group(1), m.group(2).replace("*", "")
            if key in registry and abs(float(shown) - registry[key]) > 1e-9:
                wrong.append(f"{key}: doc says {shown}, registry says {registry[key]}")
        self.assertEqual(
            wrong,
            [],
            msg=(
                "documented blend weights disagree with the registry: "
                + "; ".join(wrong)
                + ". The doc claimed idpTradeCalc was weighted 2.0 while every "
                "registry weight is 1.0 by policy."
            ),
        )


class TestEveryCitedPathExists(unittest.TestCase):
    def test_no_dead_path_references(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        dead: list[str] = []
        for raw in sorted(set(_PATH_RE.findall(text))):
            if raw in _DELIBERATELY_ABSENT:
                continue
            if "/" not in raw:
                continue  # a bare filename is prose, not a path claim
            if not (REPO_ROOT / raw).exists():
                dead.append(raw)
        self.assertEqual(
            dead,
            [],
            msg=(
                "the pipeline trace cites paths that do not exist: "
                + ", ".join(dead)
                + ". Before 2026-08-05 it cited tests/idp_calibration/... twice as a "
                "regression test 'pinning this pipeline' for a stage that had been "
                "removed. If a path is named because it is GONE, add it to "
                "_DELIBERATELY_ABSENT with a sentence saying so."
            ),
        )

    def test_the_absent_list_is_actually_absent(self) -> None:
        """Keeps the allowlist honest: if one of these comes back, the
        doc's 'this does not exist' sentences become wrong and must be
        revisited rather than left standing."""
        resurrected = [p for p in sorted(_DELIBERATELY_ABSENT) if (REPO_ROOT / p).exists()]
        self.assertEqual(
            resurrected,
            [],
            msg=(
                f"{resurrected} exist again, so the doc's claims that they were "
                "removed are now false. Update the doc, then this list."
            ),
        )


class TestTheRetiredStageStaysRetired(unittest.TestCase):
    """The single most misleading claim, pinned directly."""

    def test_the_idp_calibration_post_pass_is_not_in_the_tree(self) -> None:
        hits = [
            str(p.relative_to(REPO_ROOT))
            for p in (REPO_ROOT / "src").rglob("*.py")
            if "_apply_idp_calibration_post_pass" in p.read_text(encoding="utf-8", errors="ignore")
        ]
        self.assertEqual(
            hits,
            [],
            msg=(
                f"_apply_idp_calibration_post_pass is back, in {hits}. The pipeline "
                "trace and CLAUDE.md both describe it as removed — if it is being "
                "reintroduced, those say the opposite and must be rewritten."
            ),
        )

    def test_the_doc_does_not_describe_it_as_live(self) -> None:
        text = DOC.read_text(encoding="utf-8")
        self.assertIn("### Phase 4c — IDP calibration (REMOVED)", text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
