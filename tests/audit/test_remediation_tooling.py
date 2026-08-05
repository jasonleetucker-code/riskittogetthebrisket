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
        """A gate that fires on nothing real would pass silently forever.

        Both sites named here are findings still recorded OPEN.  A third
        one lived here — ``waiver.py``'s ``top_value_in_pool or 0``, the
        latent half of W-2 — and #707 deleted it along with the rest of
        the pool-relative bid.  It was removed from this test rather
        than kept passing against something that no longer exists,
        which is the same rule the baseline's stale-entry check
        enforces.
        """
        accepted = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
        # N-2: a team missing from the sim is coerced to 0% and told to sell.
        self.assertTrue(
            any("trade_deadline.py" in k and "playoffOdds" in k for k in accepted),
            "the coercion gate no longer sees the N-2 site",
        )
        # U-1: an unresolvable asset is priced at zero, then graded publicly.
        self.assertTrue(
            any("activity.py" in k and "valuation(asset)" in k for k in accepted),
            "the coercion gate no longer sees the U-1 site",
        )

    def test_baseline_is_internally_consistent(self) -> None:
        """The recorded count must match the recorded entries.

        There was an absolute ceiling here (618).  It was wrong: main
        moves independently of any branch — #707 and #709 landed while
        batch C0 was open and brought their own pre-existing coercions —
        so a fixed number rots into a failure nobody caused.  The
        anti-growth property lives in the gate, which fails on new
        violations in the files a change actually touches, and in
        review, where a wholesale baseline regeneration is a visible
        diff.  Duplicating it weakly here only produced false failures.
        """
        doc = json.loads(BASELINE.read_text(encoding="utf-8"))
        self.assertEqual(doc["count"], len(doc["violations"]))
        self.assertGreater(len(doc["violations"]), 0)

    def test_baseline_has_no_entries_for_files_that_no_longer_exist(self) -> None:
        """A allowance pointing at a deleted file can never be checked."""
        doc = json.loads(BASELINE.read_text(encoding="utf-8"))
        missing = sorted(
            {
                k.split("::", 1)[0]
                for k in doc["violations"]
                if not (REPO_ROOT / k.split("::", 1)[0]).exists()
            }
        )
        self.assertEqual(missing, [], f"baseline references files that do not exist: {missing}")


class TestGoldenBoardInputIsFrozen(unittest.TestCase):
    """The board capture's input must be immutable, not merely named.

    It originally defaulted to ``exports/latest/dynasty_data_2026-08-04.json``
    and called that pinned.  The filename carries only the DATE and
    ``scheduled-refresh.yml`` runs every two hours, so same-day
    refreshes overwrite it: that file was rewritten six times in two
    days, and rebasing batch C0 onto main moved the capture's input
    from the 18:20 scrape to the 20:14 one without a word.

    A harness whose input can change underneath it reports data churn
    as code change — the exact confusion it exists to remove.
    """

    def test_default_input_is_the_committed_fixture(self) -> None:
        import scripts.golden_board as gb

        self.assertEqual(gb.DEFAULT_INPUT.name, "input_export.json.gz")
        self.assertTrue(gb.DEFAULT_INPUT.exists())
        # Under tests/fixtures, not under exports/ where the refresh writes.
        self.assertIn("fixtures", gb.DEFAULT_INPUT.parts)

    def test_baseline_records_BOTH_inputs_it_was_built_from(self) -> None:
        """The contract has two inputs on disk, and both move.

        The export was frozen first and the capture called itself
        pinned, which was worse than not claiming it: the build also
        reads the per-source boards from ``CSVs/site_raw/``, tracked
        files the 2-hourly refresh rewrites (nine times in one day).
        A rebase onto a main that had not touched ``data_contract.py``
        at all produced a diff of 290 moved values, 266 ranks and 664
        tier flips — pure CSV churn, reported as though the code did it.
        """
        baseline = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(len(baseline.get("inputSha256") or ""), 64)
        self.assertEqual(len(baseline.get("sourceCsvSha256") or ""), 64)
        self.assertGreater(baseline.get("sourceCsvCount") or 0, 0)

    def test_baseline_matches_the_current_tree_state(self) -> None:
        """The committed baseline must be a capture of THIS tree.

        Both inputs are checked. The export is frozen so it can only
        drift by an edit; the source CSVs drift on their own every two
        hours, which is what makes this the assertion that will fail
        most often — and that failure is the point. It means "re-capture
        before you diff", not "something is broken".
        """
        import scripts.golden_board as gb

        csv_digest, csv_count = gb._source_csv_digest()  # noqa: SLF001
        _, digest = gb._read_export(gb.DEFAULT_INPUT)  # noqa: SLF001
        baseline = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            baseline["inputSha256"],
            digest,
            "the committed baseline was built from a different export than the "
            "committed fixture — re-run scripts/golden_board.py",
        )
        self.assertEqual(
            baseline["sourceCsvSha256"],
            csv_digest,
            "CSVs/site_raw has changed since the baseline was captured (the "
            "2-hourly refresh rewrites it) — re-run scripts/golden_board.py so "
            "the next batch diffs against this tree, not a past one",
        )
        self.assertEqual(baseline["sourceCsvCount"], csv_count)


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

    def test_faab_bid_no_longer_depends_on_who_else_is_available(self) -> None:
        """W-2 / C07: CLOSED by #707 — this test is the reversal, recorded.

        It was written to assert the defect: the same player drew $11 on
        a rich wire and $28 on a picked-over one, a 2.5x swing driven
        only by who else happened to be available, so a thin wire said
        *spend* where it should say *save*.

        #707 landed on main while batch C0 was open, replacing the
        pool-relative `0.05 + 0.25 * (value / best on the wire)` with an
        engine whose ceiling is pinned to league-format anchors.  The
        assertion is inverted rather than deleted so a future reader can
        see that the reversal was deliberate and what evidence carried
        it — the finding is closed, not forgotten.

        `top_value_in_pool` is still accepted by the shim and ignored,
        which is what makes the two bids equal.
        """
        rich = self.rows["faab_bid/v=2000,pool=9000,budget=100"]["aggressive"]
        thin = self.rows["faab_bid/v=2000,pool=2200,budget=100"]["aggressive"]
        self.assertEqual(
            rich,
            thin,
            "the same player must draw the same bid regardless of the rest of the wire",
        )

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
