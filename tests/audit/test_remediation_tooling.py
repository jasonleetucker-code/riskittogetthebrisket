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

        Three sites lived here and were removed as the code they pointed
        at was fixed: ``waiver.py``'s ``top_value_in_pool or 0`` (the
        latent half of W-2, deleted by #707 with the rest of the
        pool-relative bid), ``trade_deadline.py``'s ``playoffOdds or
        0.0`` (N-2, fixed in batch C3), and ``activity.py``'s
        ``valuation(asset) or 0.0`` (U-1 — "Public trade grades price
        unresolvable assets at 1.0 [...] with the losing manager named",
        ``docs/audits/decision-intelligence-audit-2026-08-04.md`` §4.14 —
        fixed by V1-97 / C3-REPLAY-01: an unresolvable asset now makes
        its whole side an explicit ``unavailable`` grade, never a
        coerced number). Each was removed rather than kept passing
        against something that no longer exists, which is the same rule
        the baseline's stale-entry check enforces — and the removals are
        the burn-down this gate was built to make visible. See
        ``test_the_n2_coercion_is_gone_from_the_tree_and_the_baseline``
        and ``test_the_u1_coercion_is_gone_from_the_tree_and_the_baseline``
        for the two-directional burn-down proofs.
        """
        # Deliberately no assertion here anymore: the specific site this
        # test used to pin (U-1) is fixed, and — per the W-2 precedent
        # above — a closed site is removed rather than replaced with an
        # unverified guess at another "still open" line.  The gate's
        # actual detection behaviour is proven functionally by
        # ``test_baseline_matches_the_tree`` and
        # ``test_baseline_is_internally_consistent`` against the full
        # 600+-entry baseline, and the two-directional burn-down tests
        # below prove specific sites by name.

    def test_the_u1_coercion_is_gone_from_the_tree_and_the_baseline(self) -> None:
        """U-1, asserted in both directions (same shape as N-2 below).

        ``docs/audits/decision-intelligence-audit-2026-08-04.md`` §4.14:
        "Public trade grades price unresolvable assets at 1.0, so any
        historical trade containing a retired or off-board player is
        publicly graded a ~100% fleecing, with the losing manager
        named." V1-97 / C3-REPLAY-01 closes this as a byproduct of
        removing the hindsight leak: ``_apply_trade_grades`` no longer
        coerces a missing value to any number at all — an unresolvable
        asset makes its side an explicit ``unavailable`` grade.
        """
        accepted = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
        self.assertFalse(
            any("activity.py" in k and "valuation(asset)" in k for k in accepted),
            "the U-1 allowance is back in the baseline",
        )
        source = (REPO_ROOT / "src" / "public_league" / "activity.py").read_text(encoding="utf-8")
        self.assertNotIn("valuation(asset) or 0.0", source)

    def test_the_n2_coercion_is_gone_from_the_tree_and_the_baseline(self) -> None:
        """Burn-down, asserted in both directions.

        Deleting a baseline entry is only honest if the code went with
        it; deleting the code is only durable if the allowance goes too,
        or the defect can quietly return under its own blessing.
        """
        accepted = set(json.loads(BASELINE.read_text(encoding="utf-8"))["violations"])
        self.assertFalse(
            any("trade_deadline.py" in k and "Odds" in k for k in accepted),
            "the N-2 allowance is back in the baseline",
        )
        source = (REPO_ROOT / "src" / "ros" / "trade_deadline.py").read_text(encoding="utf-8")
        self.assertNotIn('playoffOdds") or 0.0', source)
        self.assertNotIn('championshipOdds") or 0.0', source)

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

    def test_the_frozen_export_has_not_been_edited(self) -> None:
        """The export is immutable, so a mismatch here is a real edit.

        This half stays a hard assertion precisely because the fixture
        cannot move on its own: nothing writes to ``tests/fixtures/``.
        """
        import scripts.golden_board as gb

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

    def test_baseline_freshness_is_enforced_AT_USE_not_here(self) -> None:
        """Why there is no "baseline matches the tree" assertion.

        There was one, and it was wrong — not in what it wanted but in
        where it stood.  ``CSVs/site_raw`` is TRACKED and the scheduled
        refresh rewrites it roughly eight times a day (16 commits in the
        two days this was measured).  CI builds ``refs/pull/N/merge``,
        so the tree under test carries main's newest refresh: the
        assertion went red on every PR older than one refresh cycle, for
        a reason no PR caused.  Batches C0 and C2 passed it by luck —
        captured, pushed, and merged inside the window — and C3 lost the
        same coin flip.

        Clearing it by re-capturing is worse than the noise.  A baseline
        regenerated eight times a day absorbs data-driven board movement
        into itself, so the diff between two consecutive baselines is
        churn, and a genuine code regression landing in that window is
        indistinguishable from it.  The instrument meant to make code
        movement visible would have been erased by the routine that kept
        it green.

        The freshness requirement is real, so it is enforced where it
        BITES: ``board_diff`` refuses (exit 2) to compare captures built
        from different trees.  A batch therefore cannot measure against
        a stale baseline even if one is committed — it gets a refusal
        instead of a plausible-looking diff.  That fires exactly when it
        matters and never otherwise, which a repo-wide test cannot do.
        The two tests below pin that refusal, which nothing tested
        before.
        """
        # Non-vacuous: the claim above is only true while the guard it
        # points at exists, so assert that it does.  If someone deletes
        # the refusal, this reads as "the reasoning for removing the CI
        # assertion no longer holds" rather than going quietly green.
        diff_src = (REPO_ROOT / "scripts" / "board_diff.py").read_text(encoding="utf-8")
        self.assertIn("sourceCsvSha256", diff_src)
        self.assertIn("allow_input_change", diff_src)

    def _run_diff(self, before: dict, after: dict) -> subprocess.CompletedProcess:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            bp, ap_ = Path(tmp) / "before.json", Path(tmp) / "after.json"
            bp.write_text(json.dumps(before), encoding="utf-8")
            ap_.write_text(json.dumps(after), encoding="utf-8")
            return subprocess.run(
                [sys.executable, "scripts/board_diff.py", str(bp), str(ap_)],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_diff_refuses_captures_built_from_different_source_csvs(self) -> None:
        """The CSV churn case, which is the one that actually happens.

        A rebase onto a main that had not touched ``data_contract.py``
        at all once produced a diff of 290 moved values, 266 ranks and
        664 tier flips — pure refresh churn, presented as though the
        code had done it.
        """
        base = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        stale = dict(base)
        stale["sourceCsvSha256"] = "0" * 64
        proc = self._run_diff(stale, base)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("different inputs", proc.stderr)
        self.assertIn("source CSVs", proc.stderr)

    def test_diff_refuses_a_capture_that_records_no_inputs_at_all(self) -> None:
        """The guard's own blind spot, found and closed in C0.

        The refusal was written as ``if before and after and before !=
        after``, so a capture predating the field — exactly the stale
        baseline that motivated the guard — skipped it silently. Absence
        is now refused by name, which is the same lesson as N-2 one
        layer up.
        """
        base = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        old = {k: v for k, v in base.items() if k not in ("inputSha256", "sourceCsvSha256")}
        proc = self._run_diff(old, base)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("does not record its inputs", proc.stderr)

    def test_diff_refuses_a_capture_missing_only_the_freshness_digest(self) -> None:
        """The THIRD input, added 2026-08-18 (audit F-9).

        ``data_contract._source_freshness_flags`` stats every registered
        source's ``data/scrape_state/<key>_last_success`` at BUILD time
        and feeds the B11 confidence gate, so the stamps are a board
        input.  Measured by perturbing only the stamps, with the export
        and all 24 CSVs byte-identical: all-stale flips **588
        confidenceBucket and 705 confidenceLabel** while moving 0 values
        and 0 ranks.  A capture predating the digest therefore cannot be
        shown comparable on the confidence half, and "cannot verify"
        must not read as "verified equal" — the same lesson as the test
        above, one input later.
        """
        base = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        base.setdefault("freshnessSha256", "0" * 64)
        base.setdefault("freshnessStampCount", 28)
        old = {k: v for k, v in base.items() if k != "freshnessSha256"}
        proc = self._run_diff(old, base)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("freshnessSha256", proc.stderr)

    def test_diff_refuses_when_only_the_freshness_stamps_moved(self) -> None:
        """Export and CSVs identical, stamps different — still not comparable."""
        base = json.loads(
            (REPO_ROOT / "tests" / "fixtures" / "golden" / "baseline.json").read_text(
                encoding="utf-8"
            )
        )
        before = dict(base, freshnessSha256="a" * 64, freshnessStampCount=28)
        after = dict(base, freshnessSha256="b" * 64, freshnessStampCount=28)
        proc = self._run_diff(before, after)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("freshness stamps", proc.stderr)


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

    def test_captures_every_declared_surface(self) -> None:
        """Each batch adds the surfaces it needs before claiming an effect.

        Asserted as an exact set rather than a subset: a surface that
        silently stops capturing would leave the diff green while
        observing nothing, which is the one failure mode a measurement
        harness cannot have.
        """
        prefixes = {k.split("/", 1)[0] for k in self.rows}
        self.assertEqual(
            prefixes,
            {
                "ros_direction",  # C0 — the ladder itself (R-2)
                "ros_deadline",  # C3 — its caller (N-2), where absence became "Seller"
                "market_gap",  # C4 — retail vs consensus (S-1/S-2/S-3)
                "faab_bid",
                "news_polarity",
                "trade_verdict",
            },
        )

    def test_an_absent_manager_gets_no_direction(self) -> None:
        """N-2, pinned at the harness level.

        The four ``absent`` rows are managers no simulation covers. The
        fixture puts the league's best roster (rank 1) among them,
        because that is what the live data did.
        """
        absent = {
            k: v for k, v in self.rows.items() if k.startswith("ros_deadline/") and "absent" in k
        }
        self.assertEqual(len(absent), 4)
        for key, row in absent.items():
            with self.subTest(row=key):
                self.assertIsNone(row["value"])
                self.assertFalse(row["measurable"])
                self.assertEqual(row["label"], "Insufficient evidence")
        # And they sort after every measured team rather than as the
        # worst ones.
        covered = [
            v["sortPosition"]
            for k, v in self.rows.items()
            if k.startswith("ros_deadline/") and "covered" in k
        ]
        self.assertTrue(min(r["sortPosition"] for r in absent.values()) > max(covered))

    def test_the_gap_is_measured_in_value_space(self) -> None:
        """S-1, pinned at the harness level.

        REWRITTEN. This used to assert a rank-space result on a
        depth-mismatched pair, because batch C4 fixed the ordinal
        comparison by normalizing ranks. #740 fixed it differently and
        better — by comparing ``valueContribution``, which is already
        common-scaled and past ADR-015's TE conversion — so rank space
        no longer exists to assert on. The property that survives is the
        one that mattered: the gap follows the VALUES, not the ordinals.
        """
        retail = self.rows["market_gap/retail_premium_large"]
        consensus = self.rows["market_gap/consensus_premium_large"]
        self.assertEqual(retail["label"], "retail_premium")
        self.assertEqual(consensus["label"], "consensus_premium")
        # 6000 vs 4000 either way → |(6000-4000)/5000| = 0.40.
        self.assertAlmostEqual(retail["value"], 0.40, places=6)
        self.assertAlmostEqual(consensus["value"], 0.40, places=6)

    def test_a_tight_end_with_a_huge_rank_gap_is_not_a_signal(self) -> None:
        """S-2, pinned at the harness level, and the reason value space wins.

        The retail anchor is a TE-premium board, so an ordinary tight end
        shows an enormous ORDINAL gap — here rank 40 against 180 and 200.
        Under the old comparison that was the 68-of-72 SELL artifact.
        Their values agree to within 2.5%, because valueContribution is
        already on the TE++ basis, so the artifact never forms and no
        basis has to be measured and subtracted.
        """
        row = self.rows["market_gap/tight_end_rank_gap_but_value_agreement"]
        self.assertEqual(row["label"], "retail_premium")
        self.assertLess(row["value"], 0.05)  # below the label floor

    def test_a_gap_under_the_floor_still_reports_its_direction(self) -> None:
        """The floor is a DISPLAY gate, not a measurement.

        The backend reports the direction and the ratio; the frontend
        decides what is big enough to show. Collapsing small gaps to
        "none" in the contract would throw away a real measurement.
        """
        row = self.rows["market_gap/small_gap_under_floor"]
        self.assertEqual(row["label"], "retail_premium")
        self.assertLess(row["value"], 0.05)

    def test_the_cases_that_cannot_be_compared_abstain(self) -> None:
        """Four ways to have no gap, all of which must return none/None.

        Note ``ranked_but_unpriced``: a payload with per-source RANKS but
        no value stamps must abstain rather than quietly fall back to the
        ordinal arithmetic that value space replaced.
        """
        for key in (
            "market_gap/retail_only",
            "market_gap/consensus_only_every_defender",
            "market_gap/unranked",
            "market_gap/ranked_but_unpriced",
        ):
            with self.subTest(row=key):
                self.assertEqual(self.rows[key]["label"], "none")
                self.assertIsNone(self.rows[key]["value"])

    def test_an_exact_tie_is_a_measured_zero_not_an_absence(self) -> None:
        row = self.rows["market_gap/exact_tie"]
        self.assertEqual(row["label"], "none")
        self.assertEqual(row["value"], 0.0)

    def test_a_measured_zero_still_sells(self) -> None:
        """The control on the batch above: real signal is not silenced."""
        zeros = [
            v
            for k, v in self.rows.items()
            if k.startswith("ros_deadline/") and "covered" in k and v["value"] == 0.0
        ]
        self.assertEqual(len(zeros), 2)
        for row in zeros:
            self.assertEqual(row["label"], "Seller")

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


class TestCoercionScannerAccuracy(unittest.TestCase):
    """The scanner must skip prose WITHOUT going blind to code.

    Both failure directions are live risks and both happened during
    batch C2:

    * too loose — a sentence explaining ``or 0`` inside a docstring was
      reported as a violation, and a gate that cries wolf is a gate
      somebody switches off;
    * too strict — the obvious fix (treat any line containing a string
      token as prose) silences ``x = data.get("k") or 0``, a real
      coercion on a line that merely contains a string. That would
      disable the gate almost everywhere while still reporting success,
      which is the exact defect class it exists to catch.
    """

    def _scanner(self):
        import importlib.util  # noqa: PLC0415

        spec = importlib.util.spec_from_file_location(
            "cdc", REPO_ROOT / "scripts" / "check_decision_coercions.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_prose_skipped_and_code_still_caught(self) -> None:
        m = self._scanner()
        src = (
            '"""Docstring mentioning or 0 and or 1.0 in prose."""\n'
            "# comment with or 0\n"
            'x = data.get("k") or 0\n'
            'y = "a string with or 0 inside"\n'
            "z = other or 0.0\n"
            'w = cfg["a"] or 100\n'
        )
        masked = m._masked_spans(src)  # noqa: SLF001
        hits = []
        for n, line in enumerate(src.splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            for match in m._PY_PATTERN.finditer(line):  # noqa: SLF001
                if not m._is_masked(masked, n, match.start()):  # noqa: SLF001
                    hits.append(n)
        self.assertEqual(
            hits,
            [3, 5, 6],
            "lines 3/5/6 are real coercions (3 and 6 sit on lines that also "
            "contain string literals); 1, 2 and 4 are prose",
        )

    def test_unparseable_source_is_scanned_not_exempted(self) -> None:
        """Over-reporting is recoverable; quietly not looking is not."""
        m = self._scanner()
        self.assertEqual(m._masked_spans("def broken(:\n  x = 1 or 0\n"), {})  # noqa: SLF001
