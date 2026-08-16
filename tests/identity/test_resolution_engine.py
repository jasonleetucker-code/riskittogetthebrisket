"""C1-ID-01: the canonical resolution engine — policies, ambiguity, provenance.

Fixture: ``tests/fixtures/identity_directory_subset.json`` — a curated
subset of the REAL Sleeper directory (captured 2026-08-16) containing
every homonym family and defect-class player from the two measured
corpora:

* the matcher-disagreement RED corpus (10 live-board rows where the
  scraper's ladder and ``unified_mapper`` answered differently), and
* the W06-F006 false-merge corpus (11 pairs the mapper's raw fuzzy rung
  merged wrongly).

Whit Weeks, Jamarion Miller and Rod Moore are deliberately ABSENT from
the fixture, exactly as they were absent from the live directory — that
absence is what exposed the legacy ladder's unguarded initial+last rung
(it handed each of them a sibling or homonym instead of refusing).
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.identity import resolution as R

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "identity_directory_subset.json"


def _directory() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["players"]


class _Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = _directory()
        cls.index = R.build_sleeper_index(cls.directory)


class TestScraperAttachV1Fidelity(_Base):
    """The V1 policy must reproduce the legacy ladder — hazards included.
    It exists so the production dual-read can prove zero divergence; a
    'fixed' V1 would poison that proof."""

    def test_exact_clean_name_hit(self):
        got = R.resolve_scraper_attach_v1(self.index, "Patrick Mahomes", preferred_pos="QB")
        self.assertTrue(got.resolved)
        self.assertEqual(got.method, "exact_clean")

    def test_homonym_argmax_guesses_rather_than_refusing(self):
        # Two rostered IDP Byron Youngs (LAR LB 10917, PHI DL 10925).
        # The legacy ladder ALWAYS picks one — that is its documented
        # hazard, preserved verbatim in V1 and recorded via tie/candidate
        # provenance so the dual-read artifact can show the exposure.
        got = R.resolve_scraper_attach_v1(self.index, "Byron Young", preferred_pos="DL")
        self.assertTrue(got.resolved)
        self.assertEqual(got.candidates_considered, 2)
        self.assertEqual(set(got.candidate_ids), {"10917", "10925"})

    def test_unguarded_initial_last_rung_false_merges_absent_players(self):
        # THE measured live hazard: "Whit Weeks" is not in the directory;
        # the (initial, last) rung hands back his brother West Weeks.
        got = R.resolve_scraper_attach_v1(self.index, "Whit Weeks")
        self.assertTrue(got.resolved)
        self.assertEqual(got.sleeper_id, "13785")  # West Weeks — the wrong human
        self.assertEqual(got.method, "initial_last")

    def test_pick_names_are_refused(self):
        got = R.resolve_scraper_attach_v1(self.index, "2026 Pick 1.04")
        self.assertFalse(got.resolved)
        self.assertEqual(got.reason, R.REASON_PICK_NAME)

    def test_empty_input(self):
        got = R.resolve_scraper_attach_v1(self.index, "")
        self.assertFalse(got.resolved)
        self.assertEqual(got.reason, R.REASON_EMPTY_INPUT)


class TestCanonicalV2KillsTheMeasuredDefects(_Base):
    """CANONICAL_V2 is the destination semantics: every assertion here is
    grounded in a measured defect, not a hypothetical."""

    # ── the sibling / absent-player false-merge class ──

    def test_absent_player_is_unresolved_not_a_sibling(self):
        for ghost in ("Whit Weeks", "Jamarion Miller", "Rod Moore"):
            got = R.resolve_canonical_v2(self.index, name=ghost)
            self.assertFalse(got.resolved, f"{ghost} must not resolve to a sibling/homonym")
            self.assertEqual(got.reason, R.REASON_NO_CANDIDATE)

    # ── the W06-F006 fuzzy false-merge class ──

    def test_f006_pairs_never_resolve_to_the_wrong_player(self):
        pairs = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "docs/master-site-audit/evidence/W06/fuzzy-false-merges.json"
            ).read_text()
        )
        from src.identity.name_primitives import clean_name

        for src_name, wrong_name, pos, _score, _method in pairs:
            wrong_ids = {c.sleeper_id for c in self.index.by_clean.get(clean_name(wrong_name), [])}
            got = R.resolve_canonical_v2(self.index, name=src_name, position=pos or None)
            if got.resolved:
                self.assertNotIn(
                    got.sleeper_id,
                    wrong_ids,
                    f"V2 reproduced the W06-F006 false merge {src_name!r} -> {wrong_name!r}",
                )

    # ── the retired-homonym class (mapper's first-in-directory rung) ──

    def test_frank_gore_resolves_to_the_rostered_son_not_the_retired_father(self):
        got = R.resolve_canonical_v2(self.index, name="Frank Gore", position="RB")
        self.assertTrue(got.resolved)
        self.assertEqual(got.sleeper_id, "11573")  # BUF — rostered
        self.assertIn("teamed", got.method)

    def test_kyle_williams_resolves_to_the_rostered_wr(self):
        got = R.resolve_canonical_v2(self.index, name="Kyle Williams", position="WR")
        self.assertTrue(got.resolved)
        self.assertEqual(got.sleeper_id, "12547")

    # ── genuine ambiguity is an explicit state ──

    def test_two_rostered_homonyms_are_ambiguous_not_a_guess(self):
        got = R.resolve_canonical_v2(self.index, name="Byron Young", position="DL")
        self.assertFalse(got.resolved)
        self.assertEqual(got.reason, R.REASON_AMBIGUOUS)
        self.assertEqual(set(got.candidate_ids), {"10917", "10925"})

    # ── drift tolerance: position narrowing is GROUP-level ──

    def test_idp_family_drift_does_not_exclude_candidates(self):
        # Byron Young is DL on the board and LB in Sleeper for the very
        # player the board serves.  A family-exact filter would silently
        # drop one candidate and turn a real ambiguity into a false
        # certainty; the group filter keeps both.
        got = R.resolve_canonical_v2(self.index, name="Byron Young", position="LB")
        self.assertEqual(set(got.candidate_ids), {"10917", "10925"})

    # ── id rungs ──

    def test_sleeper_id_rung(self):
        got = R.resolve_canonical_v2(self.index, sleeper_id="11573")
        self.assertTrue(got.resolved)
        self.assertEqual(got.method, "sleeper_id")
        self.assertEqual(got.confidence, 1.00)

    def test_gsis_and_espn_rungs(self):
        entry = self.directory["11573"]
        if entry.get("gsis_id"):
            got = R.resolve_canonical_v2(self.index, gsis_id=entry["gsis_id"])
            self.assertEqual(got.sleeper_id, "11573")
        if entry.get("espn_id"):
            got = R.resolve_canonical_v2(self.index, espn_id=str(entry["espn_id"]))
            self.assertEqual(got.sleeper_id, "11573")

    # ── guarded initial-expansion ──

    def test_initial_expansion_still_works_when_guarded(self):
        got = R.resolve_canonical_v2(self.index, name="J. Smith-Njigba", position="WR")
        self.assertTrue(got.resolved)
        self.assertEqual(got.display_name, "Jaxon Smith-Njigba")
        self.assertIn("initial_last_guarded", got.method)

    # ── confidence discipline ──

    def test_fuzzy_confidence_never_reaches_an_exact_rung(self):
        # W06-F006 required repair: "never report a fuzzy match above 0.90".
        got = R.resolve_canonical_v2(self.index, name="Marvin Harrison Jr", position="WR")
        self.assertTrue(got.resolved)
        if got.method.startswith(("fuzzy_guarded", "initial_last_guarded")):
            self.assertLessEqual(got.confidence, 0.89)

    def test_pick_names_are_refused(self):
        got = R.resolve_canonical_v2(self.index, name="2027 Mid 1st")
        self.assertFalse(got.resolved)
        self.assertEqual(got.reason, R.REASON_PICK_NAME)


class TestDeterminism(_Base):
    """Same directory content, different insertion order → same V2 answer.
    The legacy ladders inherit dict order; the canonical semantics must
    not."""

    def test_v2_stable_under_directory_reordering(self):
        reversed_dir = dict(reversed(list(self.directory.items())))
        idx_rev = R.build_sleeper_index(reversed_dir)
        for name, pos in (
            ("Frank Gore", "RB"),
            ("Byron Young", "DL"),
            ("Whit Weeks", None),
            ("Patrick Mahomes", "QB"),
            ("Kyle Williams", "WR"),
        ):
            a = R.resolve_canonical_v2(self.index, name=name, position=pos)
            b = R.resolve_canonical_v2(idx_rev, name=name, position=pos)
            self.assertEqual(
                (a.status, a.sleeper_id, a.reason, a.candidate_ids),
                (b.status, b.sleeper_id, b.reason, b.candidate_ids),
                f"V2 answer for {name!r} depends on directory insertion order",
            )


class TestContractCsvJoinTranscription(unittest.TestCase):
    """The CSV-join policy must be the inline cascade, exactly."""

    def setUp(self):
        self.per_source = {
            "patrick mahomes::OFFENSE": {"value": 9000},
            "quay walker::IDP": {"value": 800},
            "mystery man::*": {"value": 5},
        }
        self.sid_index = {"4046": {"value": 9000, "sleeperId": "4046"}}
        self.row_groups = {
            "patrick mahomes": {"OFFENSE"},
            "quay walker": {"IDP"},
            "lone star": {"IDP"},
        }
        from src.utils.name_clean import canonical_position_group, resolve_canonical_name

        self.kwargs = dict(
            per_source=self.per_source,
            sid_index=self.sid_index,
            row_groups_by_key=self.row_groups,
            canonical_match_key=lambda n: resolve_canonical_name(n),
            position_group=canonical_position_group,
        )

    def test_sleeper_id_wins_first(self):
        d = R.match_row_to_source_entry(
            row_player_id="4046", row_name="Patrick Mahomes", row_position="QB", **self.kwargs
        )
        self.assertEqual(d.via, "sleeper_id")
        self.assertEqual(d.entry_key, "sid::4046")

    def test_name_group_join(self):
        d = R.match_row_to_source_entry(
            row_player_id=None, row_name="Quay Walker", row_position="LB", **self.kwargs
        )
        self.assertEqual((d.via, d.entry_key), ("name_group", "quay walker::IDP"))

    def test_star_fallback(self):
        d = R.match_row_to_source_entry(
            row_player_id=None, row_name="Mystery Man", row_position=None, **self.kwargs
        )
        self.assertEqual((d.via, d.entry_key), ("name_star", "mystery man::*"))

    def test_single_group_fallback(self):
        per_source = {"lone star::IDP": {"value": 3}}
        kwargs = {**self.kwargs, "per_source": per_source, "sid_index": {}}
        d = R.match_row_to_source_entry(
            row_player_id=None, row_name="Lone Star", row_position=None, **kwargs
        )
        self.assertEqual((d.via, d.entry_key), ("single_group", "lone star::IDP"))

    def test_miss_is_none_not_a_guess(self):
        d = R.match_row_to_source_entry(
            row_player_id=None, row_name="Nobody Atall", row_position="QB", **self.kwargs
        )
        self.assertEqual((d.via, d.entry_key), ("none", None))


class TestDualReadTally(unittest.TestCase):
    def test_id_comparison_arithmetic(self):
        t = R.DualReadTally("site_x", example_cap=2)
        t.record(input_name="A", legacy_id="1", v1_id="1")
        t.record(input_name="B", legacy_id="1", v1_id="2")
        t.record(input_name="C", legacy_id=None, v1_id=None)
        d = t.to_dict()
        self.assertEqual((d["calls"], d["v1Agree"], d["v1Diverge"]), (3, 2, 1))
        self.assertEqual(d["v1Examples"][0]["name"], "B")

    def test_v2_would_change_is_tracked_separately(self):
        t = R.DualReadTally("site_x")
        v2 = R.Resolution(
            status=R.UNRESOLVED, policy=R.CANONICAL_V2, method="m", reason="ambiguous"
        )
        t.record(input_name="A", legacy_id="1", v1_id="1", v2=v2)
        d = t.to_dict()
        self.assertEqual((d["v1Diverge"], d["v2WouldChange"]), (0, 1))
        self.assertEqual(d["v2Examples"][0]["v2Reason"], "ambiguous")

    def test_key_comparison(self):
        t = R.DualReadTally("join_site")
        t.record_keys(input_name="A", source="ktc", legacy_key="k::1", engine_key="k::1")
        t.record_keys(input_name="B", source="ktc", legacy_key="k::1", engine_key=None)
        d = t.to_dict()
        self.assertEqual((d["v1Agree"], d["v1Diverge"]), (1, 1))

    def test_example_cap_bounds_the_artifact(self):
        t = R.DualReadTally("site_x", example_cap=3)
        for i in range(10):
            t.record(input_name=f"P{i}", legacy_id="1", v1_id="2")
        self.assertEqual(len(t.to_dict()["v1Examples"]), 3)
        self.assertEqual(t.to_dict()["v1Diverge"], 10)


class TestFlags(unittest.TestCase):
    def test_cutover_defaults_off(self):
        self.assertFalse(R.cutover_active(env={}))
        self.assertTrue(R.cutover_active(env={"RISKIT_IDENTITY_CUTOVER": "1"}))

    def test_dual_read_defaults_on_with_kill_switch(self):
        self.assertTrue(R.dual_read_enabled(env={}))
        self.assertFalse(R.dual_read_enabled(env={"RISKIT_IDENTITY_DUAL_READ": "0"}))


if __name__ == "__main__":
    unittest.main()
