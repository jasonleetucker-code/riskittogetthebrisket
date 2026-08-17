"""Governance counts that are stated in more than one place must agree.

WHY THIS EXISTS
===============
``scripts/check_planning_integrity.py`` already guards the counts it was
taught about — the manifest row total, the RET-row total, the
source-family total, and that every manifest row maps to exactly one
execution unit.  Three *other* declared counts had no guard at all, and
all three were measurably wrong on 2026-08-17:

1. ``docs/C_SERIES_EXECUTION_MAP.md`` §12 opened "Every one of the **153**
   rows appears exactly once" and its per-unit ``n`` column summed to 153,
   against a manifest of 163.  It dropped ``C7-BEST-TRADE`` (no numeric
   suffix), ``C8-A11Y-01`` and ``C9-V3-01`` (digits in the middle segment)
   and ``X-01``…``X-07`` (two segments) — the identical ad-hoc-regex
   defect the map's own ``check_execution_map`` docstring documents,
   reproduced one section away from the fix.  The rows it dropped are
   precisely the out-of-scope dispositions a later session would
   otherwise "rediscover" as unexplored ideas.

   The §20 appendix *is* checked row-by-row by the integrity script, so
   the two tables in one file disagreed while CI stayed green.

2. ``docs/C_SERIES_SCOPE_MANIFEST.md`` §5 declared **5** explicitly
   superseded owner rules; ``docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`` §6
   declared **3** and enumerated three.  Neither included the
   meaningful-roster-core supersession (#839 replacing the fixed
   ``QB3/RB3/WR5/TE3/DL5/LB5/DB5`` caps), which is the one a C2
   implementer most needs to find.  A superseded rule that is not counted
   is a rule a future session will re-implement.

WHAT THIS GUARDS
================
Not the numbers themselves — they will change as scope changes, and that
is fine.  It guards the property that made all three wrong at once: a
count restated in a second place with nothing recomputing it.  Each
assertion below derives the number from the rows, never from prose.

``parse_manifest`` from the integrity script is reused deliberately: it
is the single owner of "what is a manifest row", and defect (1) above is
what happens when a second parser answers that question.

NOT ``livedata``-marked: reads Markdown, must block.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
MANIFEST = DOCS / "C_SERIES_SCOPE_MANIFEST.md"
EXEC_MAP = DOCS / "C_SERIES_EXECUTION_MAP.md"
TRACE = DOCS / "C_SERIES_ZERO_LOSS_TRACEABILITY.md"


def _integrity_module():
    """Load the integrity script as a module — it owns ``parse_manifest``."""
    spec = importlib.util.spec_from_file_location(
        "check_planning_integrity", REPO / "scripts" / "check_planning_integrity.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest_row_count() -> int:
    """Measured, never declared. OD-* rows are owner decisions, not manifest rows."""
    rows = _integrity_module().parse_manifest(MANIFEST.read_text(encoding="utf-8"))
    return len([r for r in rows if not r["id"].startswith("OD-")])


def _section(text: str, start: str, end: str = "\n---") -> str:
    assert start in text, f"section {start!r} is gone — update this test with the rename"
    body = text.split(start, 1)[1]
    return body.split(end, 1)[0]


class TestExecutionMapSummaryTable:
    """§12's per-unit summary must reconcile with the manifest it summarises."""

    def test_per_unit_counts_sum_to_the_measured_row_count(self, manifest_row_count: int) -> None:
        section = _section(EXEC_MAP.read_text(encoding="utf-8"), "# 12. Complete manifest-row")
        # Rows shaped ``| unit | rows | n |`` — take the trailing integer column.
        counts = [
            int(m.group(1))
            for m in re.finditer(r"^\|[^|]+\|[^|]+\|\s*(\d+)\s*\|\s*$", section, re.M)
        ]
        assert counts, "§12 has no per-unit count column any more"
        total = sum(counts)
        assert total == manifest_row_count, (
            f"§12's per-unit counts sum to {total}; the manifest measures "
            f"{manifest_row_count} rows. One of them dropped a row class — the last "
            f"time this happened it was ids without a numeric suffix, ids with digits "
            f"in the middle segment, and the seven two-segment X-* dispositions."
        )

    def test_declared_total_matches_the_measured_row_count(self, manifest_row_count: int) -> None:
        """The opening claim and the table's own total row, specifically.

        Deliberately NOT "every number in the section": §12 legitimately quotes the
        superseded 153 while explaining the correction, and a test that forbids naming a
        corrected number forbids explaining the correction.
        """
        section = _section(EXEC_MAP.read_text(encoding="utf-8"), "# 12. Complete manifest-row")

        opening = re.search(r"Every one of the \*\*(\d+)\*\* rows", section)
        assert opening, "§12 no longer opens by declaring how many rows it maps"
        assert int(opening.group(1)) == manifest_row_count, (
            f"§12 opens by declaring {opening.group(1)} rows; "
            f"the manifest measures {manifest_row_count}"
        )

        total_row = re.search(r"\|\s*\|\s*\*\*total\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|", section)
        assert total_row, "§12's table no longer carries a **total** row"
        assert int(total_row.group(1)) == manifest_row_count, (
            f"§12's table totals {total_row.group(1)}; "
            f"the manifest measures {manifest_row_count} rows"
        )


class TestSupersededRuleCensus:
    """The two records that count superseded owner rules must agree, and enumerate."""

    @staticmethod
    def _traceability_section() -> str:
        return _section(TRACE.read_text(encoding="utf-8"), "# 6. Superseded owner rules")

    def test_traceability_enumerates_as_many_rules_as_it_declares(self) -> None:
        section = self._traceability_section()
        declared = re.search(
            r"\*\*(One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|\d+)\*\*", section
        )
        assert declared, "§6 no longer declares how many superseded rules there are"
        words = {
            "one": 1,
            "two": 2,
            "three": 3,
            "four": 4,
            "five": 5,
            "six": 6,
            "seven": 7,
            "eight": 8,
            "nine": 9,
            "ten": 10,
        }
        raw = declared.group(1).lower()
        n_declared = words.get(raw, int(raw) if raw.isdigit() else -1)
        assert n_declared > 0, f"could not read the declared count from {declared.group(1)!r}"

        enumerated = len(re.findall(r"^\d+\.\s+\*\*", section, re.M))
        assert enumerated == n_declared, (
            f"§6 declares {n_declared} superseded rules but enumerates {enumerated}. "
            f"An uncounted supersession is a rule a future session re-implements."
        )

    def test_manifest_tally_agrees_with_the_traceability_enumeration(self) -> None:
        enumerated = len(re.findall(r"^\d+\.\s+\*\*", self._traceability_section(), re.M))
        tally = re.search(
            r"\|\s*Explicitly superseded owner rules\s*\|\s*(\d+)", MANIFEST.read_text("utf-8")
        )
        assert tally, "the manifest counts table no longer tallies superseded owner rules"
        assert int(tally.group(1)) == enumerated, (
            f"the manifest tallies {tally.group(1)} superseded owner rules; "
            f"the traceability record enumerates {enumerated}"
        )


class TestClosedUnitsAreNotDescribedAsUnauthorized:
    """A closed unit must not still be listed as 'not authorized'.

    ``docs/C_SERIES_EXECUTION_MAP.md`` §18 listed ``C1-U3`` under "Not
    authorized" for a day after C1-U3, C1-U4 and C1-U6 had all closed. Its
    bottom line stayed accidentally correct while its reasoning rotted,
    which is the failure this map's own standing rules exist to catch.
    """

    CLOSED_UNITS = ("C1-U1", "C1-U2", "C1-U3", "C1-U4", "C1-U6")

    #: The old §18 wrote the offending id as ``C1-U3 (`C1-ID-02`)`` — bare, with the
    #: backticks around the *manifest row* rather than the unit. Matching only
    #: ``` `C1-U3` ``` would have missed it, so match the id either way.
    @staticmethod
    def _mentions(unit: str, text: str) -> bool:
        return re.search(rf"`?{re.escape(unit)}`?\b", text) is not None

    def test_no_closed_unit_appears_in_the_not_authorized_boundary(self) -> None:
        section = _section(EXEC_MAP.read_text(encoding="utf-8"), "# 18. Authorization boundary")
        # The blocked list starts at the **bolded lead-in**, not at the first prose
        # mention — §18 legitimately narrates that it once listed a closed unit, and a
        # test that trips on the explanation cannot tell a defect from its own fix.
        marker = re.search(r"^\*\*[^*]*not authorized[^*]*\*\*", section, re.I | re.M)
        assert marker, "§18 no longer states what is NOT authorized — that list is the point"
        blocked = section[marker.start() :]

        # Check each blocked ITEM's subject, not the whole block. A closed unit may
        # legitimately appear in an item's explanatory clause — "`CANONICAL_V2`
        # activation — C1-U2 measured it and deliberately deferred it" names C1-U2 as
        # the unit that deferred the item, which is provenance, not a claim that C1-U2
        # is blocked. The subject is everything before the em-dash.
        offenders: list[str] = []
        for raw in re.split(r"[\n·]", blocked):
            subject = re.sub(r"^\s*[-*]\s*", "", raw).split("—", 1)[0]
            offenders += [
                u for u in self.CLOSED_UNITS if self._mentions(u, subject) and u not in offenders
            ]
        assert not offenders, (
            f"§18 lists closed unit(s) {offenders} as not authorized. They are CLOSED; "
            f"saying otherwise invites a session to redo finished work."
        )
