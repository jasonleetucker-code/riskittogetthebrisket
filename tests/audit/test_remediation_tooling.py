"""Pin the remediation pass's own measurement tooling.

WHY THIS EXISTS
---------------
The 2026-08-04 audit's Part B makes every value-affecting change
measured rather than asserted, and the remediation batches gate on
three tools: the golden board capture, the decision-surface capture,
and the finding-status registry.

A measurement harness that silently stops measuring is worse than no
harness, because the batches keep reporting "no unexpected movement"
and mean nothing by it.  Finding Q-1 is precisely this failure in its
test-suite form — 33 core-blend tests exempted from the blocking gate
by a filename rule, reporting green while unable to fail.

So the tools that verify the pass are themselves verified.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STATUS = REPO_ROOT / "docs" / "audits" / "decision-intelligence-audit-2026-08-04.status.json"
BASELINE = REPO_ROOT / "config" / "coercion_baseline.json"


class TestFindingStatusRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = json.loads(STATUS.read_text(encoding="utf-8"))
        self.findings = self.doc["findings"]

    def test_covers_every_critical_in_the_registry(self) -> None:
        """43 Criticals in the audit, 43 tracked — no silent drops."""
        self.assertEqual(len(self.findings), 43)
        self.assertEqual(self.doc["total"], 43)

    def test_every_finding_carries_a_verdict_and_its_reasoning(self) -> None:
        for f in self.findings:
            with self.subTest(finding=f["id"]):
                self.assertIn(f["status"], {"open", "closed", "deferred", "needs_review"})
                # A status without stated reasoning is the unfalsifiable
                # claim this registry exists to prevent.
                self.assertTrue(
                    (f.get("verifiedBy") or "").strip(),
                    f"{f['id']} has a status but records no reasoning for it",
                )

    def test_closed_findings_name_why_they_are_closed(self) -> None:
        closed = [f for f in self.findings if f["status"] == "closed"]
        # Six were closed by work that landed after the audit was written
        # (#715 and the draft-capital table removal), not by this pass.
        self.assertGreaterEqual(len(closed), 6)
        for f in closed:
            with self.subTest(finding=f["id"]):
                self.assertGreater(len(f["verifiedBy"]), 40)

    def test_open_findings_have_a_locatable_defect_signature(self) -> None:
        """An open finding the probe cannot find is a rotted record."""
        for f in self.findings:
            if f["status"] != "open" or not f.get("signature"):
                continue
            with self.subTest(finding=f["id"]):
                self.assertEqual(
                    f["probe"]["result"],
                    "signature_present",
                    f"{f['id']} ({f['auditId']}) is recorded open but its signature "
                    f"is no longer in {f.get('path')} — re-verify and update the "
                    f"curated table in scripts/audit_status.py",
                )

    def test_drift_check_passes(self) -> None:
        proc = subprocess.run(
            [sys.executable, "scripts/audit_status.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


class TestCoercionGate(unittest.TestCase):
    def test_baseline_matches_the_tree(self) -> None:
        """No new coercions, and no allowance for a defect already fixed."""
        proc = subprocess.run(
            [sys.executable, "scripts/check_decision_coercions.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_gate_actually_detects_the_audits_own_sites(self) -> None:
        """A gate that fires on nothing real would pass silently forever."""
        accepted = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
        # N-2: a team missing from the sim is coerced to 0% and told to sell.
        self.assertTrue(
            any("trade_deadline.py" in k and "playoffOdds" in k for k in accepted),
            "the coercion gate no longer sees the N-2 site",
        )
        # W-2 latent: an unknown pool ceiling defaults to zero.
        self.assertTrue(
            any("waiver.py" in k and "top_value_in_pool" in k for k in accepted),
            "the coercion gate no longer sees the W-2 site",
        )

    def test_baseline_shrinks_only(self) -> None:
        """The baseline is debt to burn down, not a place to add to.

        Recorded as a hard ceiling so a future batch cannot quietly
        widen the allowance to make a build pass — the failure mode the
        script's own docstring warns about.
        """
        doc = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertLessEqual(
            len(doc["violations"]),
            618,
            "the coercion baseline grew; a decision path may not fabricate a number",
        )
        self.assertEqual(doc["count"], len(doc["violations"]))


class TestSurfaceHarness(unittest.TestCase):
    """The surface capture must keep exposing the defects it was built for.

    These assert the CURRENT, defective behaviour on purpose.  Each one
    names the batch that will invert it, so the failure reads as "the
    fix landed, update this test" rather than as a mystery regression —
    trap 3 in the remediation brief: reversals must be recorded in
    place, not deleted silently.
    """

    @classmethod
    def setUpClass(cls) -> None:
        path = REPO_ROOT / "tests" / "fixtures" / "golden" / "surfaces.json"
        cls.rows = json.loads(path.read_text(encoding="utf-8"))["rows"]

    def test_captures_all_four_surfaces(self) -> None:
        prefixes = {k.split("/", 1)[0] for k in self.rows}
        self.assertEqual(prefixes, {"ros_direction", "faab_bid", "news_polarity", "trade_verdict"})

    def test_exposes_the_ros_dead_band(self) -> None:
        """R-2 / C36: 0.40 playoff odds falls through to the catch-all.

        Inverted by batch C10. When it fails, the ladder is exhaustive.
        """
        seller = self.rows["ros_direction/p=0.35,c=0.00,age=0"]["label"]
        dead = self.rows["ros_direction/p=0.40,c=0.00,age=0"]["label"]
        buyer = self.rows["ros_direction/p=0.45,c=0.00,age=0"]["label"]
        self.assertEqual(seller, "Selective Seller")
        self.assertEqual(dead, "Hold / Evaluate")
        self.assertEqual(buyer, "Selective Buyer")

    def test_exposes_a_dead_team_and_a_certain_team_getting_identical_advice(self) -> None:
        """R-2: at championship odds 0.02, 0% and 100% playoff odds agree.

        The audit reported "a team at 100% playoff odds gets the same
        advice as one at 0%".  Enumerating the grid locates exactly
        where that holds and shows the shape of it: the responsive bands
        are ISLANDS (0.20-0.35 sells, 0.45-0.55 buys) surrounded by
        catch-all, so the ladder is non-monotonic in the input it exists
        to read — the strongest team in the league and a mathematically
        eliminated one land on the same verb.

        Inverted by batch C10; the release gate then requires the label
        to be monotonic in playoff odds with no cell reaching a
        catch-all.
        """
        at = lambda p: self.rows[f"ros_direction/p={p},c=0.02,age=0"]["label"]  # noqa: E731
        self.assertEqual(at("0.00"), "Hold / Evaluate")
        self.assertEqual(at("1.00"), "Hold / Evaluate")
        # Non-monotonic: it responds in the middle and gives up at both ends.
        self.assertEqual(at("0.25"), "Selective Seller")
        self.assertEqual(at("0.50"), "Selective Buyer")
        self.assertEqual(at("0.40"), "Hold / Evaluate")

        catch_all = [
            p for p in (f"{i * 0.05:.2f}" for i in range(21)) if at(p) == "Hold / Evaluate"
        ]
        # Over half the grid reaches a label that means "no advice".
        self.assertGreater(len(catch_all), 10)

    def test_exposes_the_faab_wire_dependence(self) -> None:
        """W-2 / C07: the same player's bid swings on who ELSE is available.

        Inverted by batch C9, which anchors the bid to replacement level.
        """
        rich = self.rows["faab_bid/v=2000,pool=9000,budget=100"]["aggressive"]
        thin = self.rows["faab_bid/v=2000,pool=2200,budget=100"]["aggressive"]
        self.assertLess(rich, thin, "a thin wire should mean save, not spend")
        # Top of pool is a constant share of budget by construction.
        self.assertEqual(self.rows["faab_bid/v=9000,pool=9000,budget=100"]["label"], "30%")

    def test_exposes_released_scored_as_positive(self) -> None:
        """E-2 / C40: a player being cut is scored as good news.

        Inverted by batch C11.
        """
        for headline in (
            "news_polarity/Star RB released by the Panthers",
            "news_polarity/Veteran WR waived after failed physical",
        ):
            with self.subTest(headline=headline):
                self.assertEqual(self.rows[headline]["impact"], "positive")

    def test_exposes_scale_dependent_fairness(self) -> None:
        """T-2 / C05: identical lopsidedness, opposite verdict.

        Both trades are 64% apart. Inverted by batch C5, after which the
        two verdicts must match — that is the release gate's own case.
        """
        small = self.rows["trade_verdict/A=500,B=180"]
        large = self.rows["trade_verdict/A=9000,B=3240"]
        self.assertEqual(small["gapPercent"], large["gapPercent"])
        self.assertEqual(small["meterLabel"], "FAIR")
        self.assertEqual(large["meterLabel"], "LOPSIDED")

    def test_exposes_the_lenient_small_trade(self) -> None:
        """T-2: an 81%-lopsided bench trade reads FAIR."""
        row = self.rows["trade_verdict/A=420,B=80"]
        self.assertEqual(row["gapPercent"], 81)
        self.assertEqual(row["meterLabel"], "FAIR")


if __name__ == "__main__":
    unittest.main()
