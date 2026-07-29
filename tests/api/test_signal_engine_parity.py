"""Backend half of the Buy/Sell/Hold engine parity test (debt item D3).

There are TWO Buy/Sell/Hold rule engines in this repo and they are not
a primary/fallback pair, whatever the comment above
``_build_signal_context`` says:

* ``src/api/terminal.py::_evaluate_signal`` — what gets EMAILED.
  ``server.py`` feeds the terminal payload's ``signals`` block into
  ``src/api/signal_alerts.py::process_user_alerts``, whose
  ``ACTIONABLE_SIGNALS`` set is {RISK, SELL, BUY, MONITOR}.
* ``frontend/lib/signal-engine.js::evaluate`` — what the user SEES.
  ``BuySellHold.jsx`` and ``TopSignalsRail.jsx`` render the verdicts
  from ``evaluateRoster``; nothing in the UI reads the backend
  ``signal`` / ``reason`` / ``tag`` / ``fired`` fields (the server
  ``signals`` block is consumed only for ``injuryImpact``).

So a divergence is not cosmetic — it is "you were emailed a SELL that
the Signals panel does not show". Nothing checked that the two agreed
until this file and its frontend twin.

BOTH halves assert against ONE fixture,
``tests/fixtures/signal_parity_cases.json``. Neither may hardcode an
expectation of its own: if the engines ever disagree, exactly one of
the two suites goes red against a shared, human-authored statement of
what the rule table is supposed to mean.

Frontend twin: ``frontend/__tests__/signal-engine-parity.test.js``.

WHAT IS ASSERTED
    ``signal``, ``tag``, and the ORDERED list of firing rule tags — the
    machine-readable verdict, in priority order.

WHAT IS DELIBERATELY NOT ASSERTED, and why
    * ``reason`` prose. The two engines word four rules differently
      (e.g. Python "Alert-severity news alongside…" vs JS
      "Alert-severity injury or rumor alongside…") and round MAD
      differently (Python ``f"{mad:.1f}"`` is round-half-even, JS
      ``.toFixed(1)`` rounds half away from zero, so MAD 2.25 renders
      "2.2" vs "2.3"). Unifying user-visible copy that ships in both
      the UI and alert emails is a product decision, not a test fix.
    * The ``fired[]`` ENTRY SHAPE. Python entries are
      ``{priority, signal, tag, reason}``; JS entries are
      ``{id, signal, tag, reason}`` where ``id`` is a dotted rule name
      the backend has no concept of. Only the tag sequence is common
      vocabulary, so only the tag sequence is pinned.
    * The CONTEXT BUILDERS. ``_build_signal_context`` consumes a
      contract row; ``buildContext`` consumes a ``buildRows``-
      materialized row. They cannot share a row fixture, and they are
      known to disagree (``confidence`` vs ``marketConfidence``,
      ``"IDP"`` vs ``"LB"`` position vocabularies, history lookup by
      bare name vs ``"Name::assetClass"``). This file pins the RULE
      TABLE only; the builders are a separate, larger piece of work.

FIXTURE HYGIENE
    Keep the fixture free of type-punned values (a string
    ``confidence``, a list ``volatility``). JS wraps every ``test`` in
    try/catch and treats a throw as "did not fire"; Python has no such
    guard and raises. A fixture that exercises that difference would
    fail here as an error rather than as a parity report.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from src.api import terminal

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = REPO_ROOT / "tests" / "fixtures" / "signal_parity_cases.json"
TERMINAL_SRC = REPO_ROOT / "src" / "api" / "terminal.py"


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


FIXTURE = _load_fixture()


def _declared_rules_from_terminal_source() -> list[dict[str, Any]]:
    """Scrape (priority, signal, tag) out of ``_evaluate_signal``.

    Static, not introspective: the rules are inline ``add(...)`` calls
    inside the function, so there is no object to enumerate at runtime.
    This exists so that ADDING AN 11th RULE to one engine and not the
    other fails a test instead of silently drifting.
    """
    src = TERMINAL_SRC.read_text(encoding="utf-8")
    start = src.index("def _evaluate_signal(")
    end = src.index("\ndef ", start + 1)
    body = src[start:end]
    out: list[dict[str, Any]] = []
    for m in re.finditer(r'add\(\s*(\d+),\s*"([A-Z_]+)",\s*"([a-z0-9_]+)"', body):
        out.append({"priority": int(m.group(1)), "signal": m.group(2), "tag": m.group(3)})
    return out


class TestSignalParityFixtureIntegrity(unittest.TestCase):
    """The fixture has to be worth trusting before it can bind anything."""

    def test_fixture_exists_and_is_non_trivial(self) -> None:
        self.assertTrue(FIXTURE_PATH.is_file(), f"missing fixture {FIXTURE_PATH}")
        self.assertGreaterEqual(len(FIXTURE["cases"]), 40)
        self.assertEqual(len(FIXTURE["rules"]), 10)

    def test_case_ids_are_unique(self) -> None:
        ids = [c["id"] for c in FIXTURE["cases"]]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertFalse(dupes, f"duplicate case ids: {sorted(dupes)}")

    def test_priorities_are_distinct(self) -> None:
        """No two rules may share a priority.

        Both engines sort by priority alone with a stable sort, so ties
        resolve by declaration order — which is currently identical on
        both sides but is not enforced anywhere. Keeping priorities
        distinct means tie-break order can never become a source of
        divergence in the first place.
        """
        prios = [r["priority"] for r in FIXTURE["rules"]]
        self.assertEqual(len(prios), len(set(prios)), f"duplicate priorities: {prios}")

    def test_every_rule_is_exercised_as_a_winner_and_in_a_chain(self) -> None:
        winners = {c["expected"]["tag"] for c in FIXTURE["cases"]}
        in_chain = {t for c in FIXTURE["cases"] for t in c["expected"]["firedTags"]}
        for rule in FIXTURE["rules"]:
            tag = rule["tag"]
            self.assertIn(tag, winners, f"no case where {tag} owns the verdict")
            self.assertIn(tag, in_chain, f"no case where {tag} appears in fired[]")

    def test_there_is_a_case_where_nothing_fires(self) -> None:
        default = FIXTURE["defaultVerdict"]
        empties = [
            c
            for c in FIXTURE["cases"]
            if c["expected"]["firedTags"] == [] and c["expected"]["tag"] == default["tag"]
        ]
        self.assertGreaterEqual(len(empties), 1)

    def test_fired_tags_are_ordered_by_descending_priority(self) -> None:
        prio = {r["tag"]: r["priority"] for r in FIXTURE["rules"]}
        for c in FIXTURE["cases"]:
            tags = c["expected"]["firedTags"]
            got = [prio[t] for t in tags]
            self.assertEqual(
                got,
                sorted(got, reverse=True),
                f"{c['id']}: firedTags not in descending priority order",
            )
            if tags:
                self.assertEqual(
                    c["expected"]["tag"],
                    tags[0],
                    f"{c['id']}: winner is not the highest-priority firing rule",
                )


class TestSignalRuleTableMatchesFixture(unittest.TestCase):
    """The Python rule table must be exactly the table the fixture declares."""

    def test_backend_rules_match_fixture_declaration(self) -> None:
        declared = sorted(
            ((r["priority"], r["signal"], r["tag"]) for r in FIXTURE["rules"]),
            reverse=True,
        )
        actual = sorted(
            (
                (r["priority"], r["signal"], r["tag"])
                for r in _declared_rules_from_terminal_source()
            ),
            reverse=True,
        )
        self.assertEqual(
            actual,
            declared,
            "src/api/terminal.py::_evaluate_signal no longer matches the "
            "rule table in tests/fixtures/signal_parity_cases.json. If you "
            "added or changed a rule, mirror it in "
            "frontend/lib/signal-engine.js AND add fixture cases for it "
            "(threshold, either side of the threshold, and every input "
            "null) — otherwise the two engines are free to drift.",
        )


class TestSignalEngineParity(unittest.TestCase):
    """Every fixture case, through ``_evaluate_signal``."""

    def test_all_cases(self) -> None:
        for c in FIXTURE["cases"]:
            with self.subTest(case=c["id"]):
                verdict = terminal._evaluate_signal(dict(c["ctx"]))
                expected = c["expected"]
                self.assertEqual(
                    verdict["signal"],
                    expected["signal"],
                    f"{c['id']}: {c['why']}",
                )
                self.assertEqual(
                    verdict["tag"],
                    expected["tag"],
                    f"{c['id']}: {c['why']}",
                )
                self.assertEqual(
                    [f["tag"] for f in verdict["fired"]],
                    expected["firedTags"],
                    f"{c['id']}: {c['why']}",
                )

    def test_every_verdict_carries_a_non_empty_reason(self) -> None:
        """Prose is not compared across engines, but it must exist."""
        for c in FIXTURE["cases"]:
            with self.subTest(case=c["id"]):
                verdict = terminal._evaluate_signal(dict(c["ctx"]))
                self.assertTrue(str(verdict.get("reason") or "").strip())
                for entry in verdict["fired"]:
                    self.assertTrue(str(entry.get("reason") or "").strip())

    def test_null_trend30_is_not_read_as_flat(self) -> None:
        """Regression pin for the one real divergence this test found.

        ``sell.sustained_downtrend`` and ``strong.elite_stable`` both
        gate on trend30. The frontend used ``(c.trend30 ?? 0)``, which
        makes "no 30d coverage" satisfy both ``<= 0`` and ``>= 0`` — so
        a player with NO rank history came back SELL from one rule and
        STRONG_HOLD from the other, while this engine returned HOLD.
        Python's ``is not None`` reading is the correct one (absent is
        not flat, and SELL is an emailed signal), so the JS rules were
        changed to match rather than the reverse. Pinned on both sides
        so neither can drift back.
        """
        for case_id in ("r3_trend30_null_no_history", "r8_trend30_null_no_history"):
            case = next(c for c in FIXTURE["cases"] if c["id"] == case_id)
            self.assertIsNone(case["ctx"]["trend30"])
            self.assertEqual(case["expected"]["signal"], "HOLD")
            verdict = terminal._evaluate_signal(dict(case["ctx"]))
            self.assertEqual(verdict["signal"], "HOLD")
            self.assertEqual(verdict["fired"], [])


if __name__ == "__main__":
    unittest.main()
