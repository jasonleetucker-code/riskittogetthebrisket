"""W18-F001 RED — cross-league ranking reuse must be a FACT, not a label.

``leagues_share_scoring()`` is the single canonical owner of "may these two
leagues share scoring-dependent rankings?". Its entire body is

    return cfg_a.scoring_profile == cfg_b.scoring_profile

— equality of a hand-typed string in ``config/leagues/registry.json``.
Both live leagues carry ``superflex_tep15_ppr1`` while the host says their
scoring differs on 35 of 48 shared keys, so ``/api/data?leagueKey=
dynasty_new`` serves dynasty_main's board verbatim.

There is a second fail-open path in the same finding: ``server.py`` gates on
``if loaded_profile and loaded_profile != league_cfg.scoring_profile``, so a
contract carrying NO profile is treated as compatible with everything.

Intended architecture (owner-approved), which these tests encode:

* ``scoringProfile`` stays what its many consumers already rely on — a
  human/config/model label (bdvm, gameplan bundle cache keys, …). It is
  NOT repurposed.
* a separate FACTUAL fingerprint over valuation-affecting scoring rules
  answers compatibility.
* ``leagues_share_scoring`` remains the one owner of the question and
  consumes the fingerprint.
* unverifiable identity FAILS CLOSED.

These tests are written against that intent and fail today because the
capability does not exist. They deliberately do not assert *how* the
fingerprint is computed beyond the properties a compatibility identity must
have — a test that recomputed the hash the same way the code does would
prove nothing.

WHAT BELONGS IN THE FINGERPRINT, decided before coding it: the league's
scoring settings and nothing else. Not league name, season, roster size,
team count, draft config or any other metadata — those do not change what a
player is worth. Hashing a whole league object would make two identically
scored leagues incompatible for irrelevant reasons, which is the same class
of error as the label, inverted.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.api import league_registry as lr


def _cfg(key: str, profile: str, league_id: str):
    return lr.LeagueConfig(
        key=key,
        display_name=key,
        sleeper_league_id=league_id,
        scoring_profile=profile,
        roster_settings={},
        idp_enabled=False,
    )


#: Two genuinely different valuation-affecting cards. The differences are
#: the real ones the host reports between the two live leagues.
SCORING_A = {"rec": 1.0, "pass_td": 4.0, "pass_yd": 0.04, "pass_int": -1.0}
SCORING_B = {"rec": 0.08, "pass_td": 6.0, "pass_yd": 1 / 30, "pass_int": -4.0}


#: Module attributes this fixture swaps out.  Restored wholesale in
#: ``tearDown`` rather than per-``_install``: ``_install`` is called more
#: than once in a single test, and a cleanup that re-reads the "original"
#: at teardown time restores the PREVIOUS STUB instead of the real
#: function — leaking a patched ``get_league_by_key`` into every later
#: test in the process.  (That is not hypothetical: it is what this
#: fixture did when first written, and it broke four unrelated suites
#: that read the real registry.)
_PATCHED = ("get_league_by_key", "scoring_fingerprint_for_league")


class _RegistryFixture(unittest.TestCase):
    """Patch the registry + a scoring source; never touch the network."""

    def setUp(self):
        self._originals = {name: getattr(lr, name) for name in _PATCHED if hasattr(lr, name)}

    def tearDown(self):
        for name, original in self._originals.items():
            setattr(lr, name, original)

    def _install(self, configs: dict, scoring: dict):
        lr.get_league_by_key = lambda k: configs.get(str(k or "").lower())
        # The fingerprint source is patched by league_id so the test never
        # depends on which transport the repair chooses.
        if "scoring_fingerprint_for_league" in self._originals:
            lr.scoring_fingerprint_for_league = lambda cfg: scoring.get(
                getattr(cfg, "sleeper_league_id", None)
            )


class TestCompatibilityIsFactualNotLabelBased(_RegistryFixture):
    def test_A_same_label_different_scoring_must_not_share(self):
        """The live defect. Identical label, materially different cards."""
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        cfgs = {
            "a": _cfg("a", "superflex_tep15_ppr1", "111"),
            "b": _cfg("b", "superflex_tep15_ppr1", "222"),
        }
        self._install(
            cfgs,
            {"111": scoring_fingerprint(SCORING_A), "222": scoring_fingerprint(SCORING_B)},
        )
        self.assertFalse(
            lr.leagues_share_scoring("a", "b"),
            "two leagues with different scoring shared rankings because their "
            "hand-typed profile labels matched",
        )

    def test_B_different_label_identical_scoring_may_share(self):
        """The inverse, so we do not swap a label bug for a naming convention.

        If the product ever needs to refuse sharing despite identical
        scoring, that is a SEPARATE constraint and must be expressed
        somewhere other than the scoring-compatibility answer.
        """
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        cfgs = {
            "a": _cfg("a", "some_label", "111"),
            "b": _cfg("b", "a_totally_different_label", "222"),
        }
        fp = scoring_fingerprint(SCORING_A)
        self._install(cfgs, {"111": fp, "222": fp})
        self.assertTrue(
            lr.leagues_share_scoring("a", "b"),
            "identical scoring was refused because the config labels differ — "
            "compatibility is still label-dependent",
        )

    def test_C_unverifiable_identity_fails_closed(self):
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        cfgs = {"a": _cfg("a", "p", "111"), "b": _cfg("b", "p", "222")}
        fp = scoring_fingerprint(SCORING_A)
        for label, table in (
            ("both unknown", {}),
            ("requested unknown", {"111": fp}),
            ("loaded unknown", {"222": fp}),
        ):
            with self.subTest(label):
                self._install(cfgs, table)
                self.assertFalse(
                    lr.leagues_share_scoring("a", "b"),
                    f"{label}: unproven scoring compatibility permitted ranking reuse",
                )

    def test_C2_unknown_keys_still_fail_closed(self):
        """Pre-existing behaviour that must survive the repair."""
        self._install({}, {})
        self.assertFalse(lr.leagues_share_scoring("nope", "also_nope"))
        self.assertFalse(lr.leagues_share_scoring(None, None))


class TestTheServerGateDoesNotFailOpen(unittest.TestCase):
    """The second half of W18-F001, per the finding.

    ``server.py`` rejects only when the loaded profile is TRUTHY and
    unequal, so a contract with no profile is treated as compatible with
    every league. Asserted as a semantic property of the source rather
    than by string-matching one expression, because the repair may
    legitimately restructure the condition.
    """

    def test_missing_loaded_identity_is_not_treated_as_compatible(self):
        import re
        from pathlib import Path

        src = (Path(__file__).resolve().parents[2] / "server.py").read_text(encoding="utf-8")
        # The fail-open shape: gate the incompatibility check on the loaded
        # identity being present at all.
        offenders = re.findall(r"if\s+loaded_profile\s+and\s+loaded_profile\s*!=", src)
        self.assertEqual(
            offenders,
            [],
            "server.py still short-circuits the compatibility check when the "
            "loaded contract carries no scoring identity, so an unidentified "
            "contract is served for any league",
        )


class TestASnapshotProvesWhenItWasTaken(unittest.TestCase):
    """W18-F001, owner review gap 1 — staleness is not proof.

    ``refresh_scoring_snapshot`` deliberately leaves the previous snapshot
    in place when a refresh fails, and that is right: a transient Sleeper
    blip should not destroy stored evidence. But a snapshot proves *"this
    league had these rules when the fetch last succeeded"*, NOT *"this
    league still has these rules"*. If scoring changes and every later
    refresh fails, an indefinitely stale card would keep authorizing
    cross-league ranking reuse — the exact fail-open W18-F001 exists to
    close, arrived at through time instead of through a label.

    The budget is DERIVED, not invented. ``scheduled-refresh.yml`` runs
    ``42 */2 * * *`` and the warm pass writes this snapshot on that
    cadence; ``server.py`` calls a contract stale at
    ``SCRAPE_INTERVAL_HOURS * 3`` (= 6 h) and
    ``data_contract._SOURCE_MAX_AGE_HOURS`` gives every scrape-cadence
    source a 6-hour budget. Same artifact class, same number, two
    independent precedents.

    Three states, matching ``_build_source_timestamps``'s existing
    vocabulary: fresh / stale / missing.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("LEAGUE_SCORING_SNAPSHOT_DIR")
        os.environ["LEAGUE_SCORING_SNAPSHOT_DIR"] = self.tmp
        lr._scoring_fp_cache.clear()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(lr._scoring_fp_cache.clear)
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._prev is None:
            os.environ.pop("LEAGUE_SCORING_SNAPSHOT_DIR", None)
        else:
            os.environ["LEAGUE_SCORING_SNAPSHOT_DIR"] = self._prev

    @staticmethod
    def _write(league_id: str, scoring: dict, age_hours: float):
        """A snapshot of a given AGE, recording the current season — the
        shape ``refresh_scoring_snapshot`` actually writes
        (``season=info.season``).  Recording it here is what keeps these
        tests measuring age; a card with no season is its own case, and
        the tests for that are below."""
        from src.bdvm.actuals import nfl_projection_season

        path = lr.write_scoring_snapshot(league_id, scoring, season=str(nfl_projection_season()))
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["fetchedAt"] = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
        path.write_text(json.dumps(raw), encoding="utf-8")
        lr._scoring_fp_cache.clear()
        return path

    def test_a_fresh_snapshot_proves_identity(self):
        self._write("111", SCORING_A, age_hours=1.0)
        cfg = _cfg("a", "p", "111")
        self.assertTrue(lr.scoring_fingerprint_for_league(cfg))
        self.assertEqual(lr.scoring_evidence_state(cfg), "fresh")

    def test_a_stale_snapshot_does_not_prove_identity(self):
        """The defect: an old card must stop authorizing reuse."""
        self._write("111", SCORING_A, age_hours=48.0)
        cfg = _cfg("a", "p", "111")
        self.assertEqual(lr.scoring_evidence_state(cfg), "stale")
        self.assertIsNone(
            lr.scoring_fingerprint_for_league(cfg),
            "a 48-hour-old scoring card was still accepted as proof that this "
            "league's scoring matches another league's today",
        )

    def test_stale_evidence_is_retained_not_destroyed(self):
        """Failing closed is not the same as deleting what we know.

        The card must still be readable for diagnostics; only its
        authority to prove CURRENT compatibility expires.
        """
        self._write("111", SCORING_A, age_hours=48.0)
        cfg = _cfg("a", "p", "111")
        self.assertEqual(lr.scoring_settings_for_league(cfg), SCORING_A)

    def test_missing_and_stale_are_distinguishable(self):
        fresh = _cfg("a", "p", "111")
        stale = _cfg("b", "p", "222")
        absent = _cfg("c", "p", "333")
        self._write("111", SCORING_A, age_hours=1.0)
        self._write("222", SCORING_A, age_hours=48.0)
        self.assertEqual(
            [lr.scoring_evidence_state(c) for c in (fresh, stale, absent)],
            ["fresh", "stale", "missing"],
        )

    def test_the_budget_matches_the_repo_convention(self):
        """Pinned so the number cannot drift away from what derived it."""
        from src.api import data_contract as dc

        import server

        self.assertEqual(lr.SCORING_SNAPSHOT_MAX_AGE_HOURS, server.SCRAPE_INTERVAL_HOURS * 3)
        self.assertEqual(
            lr.SCORING_SNAPSHOT_MAX_AGE_HOURS,
            dc._SOURCE_MAX_AGE_HOURS["ktc"],
        )

    def test_a_snapshot_from_another_season_never_proves_identity(self):
        """A second, independent boundary: scoring is a per-season fact.

        Even inside the freshness window, a card stamped with a different
        season is evidence about a different season's rules.
        """
        self._write_with_season("111", SCORING_A, season="1999")
        cfg = _cfg("a", "p", "111")
        self.assertEqual(lr.scoring_evidence_state(cfg), "stale")
        self.assertIsNone(lr.scoring_fingerprint_for_league(cfg))

    @staticmethod
    def _write_with_season(league_id: str, scoring: dict, season):
        """A snapshot of the given season, dated NOW — so age can never be
        what any of the season tests below is measuring."""
        path = lr.write_scoring_snapshot(league_id, scoring)
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["fetchedAt"] = datetime.now(timezone.utc).isoformat()
        if season is None:
            raw.pop("season", None)
        else:
            raw["season"] = season
        path.write_text(json.dumps(raw), encoding="utf-8")
        lr._scoring_fp_cache.clear()
        return path

    # ── Season verification must fail closed (owner re-review) ──────
    #
    # ``if season:`` skipped the check entirely for an unrecorded season,
    # and ``except Exception: pass`` swallowed a resolver failure — both
    # landing on FRESH.  Neither is demonstrably current, and the state
    # they belong in already exists: the card is present and readable but
    # cannot be shown to describe this season, which is exactly what the
    # ``fetched_at is None`` branch three lines up already calls STALE.
    # No fourth state.

    def test_a_snapshot_with_no_recorded_season_is_not_fresh(self):
        self._write_with_season("111", SCORING_A, season=None)
        cfg = _cfg("a", "p", "111")
        self.assertEqual(
            lr.scoring_evidence_state(cfg),
            "stale",
            "a card whose season was never recorded was treated as proven-current",
        )
        self.assertIsNone(lr.scoring_fingerprint_for_league(cfg))

    def test_a_blank_recorded_season_is_not_fresh(self):
        for blank in ("", "   "):
            with self.subTest(repr(blank)):
                self._write_with_season("111", SCORING_A, season=blank)
                cfg = _cfg("a", "p", "111")
                self.assertEqual(lr.scoring_evidence_state(cfg), "stale")
                self.assertIsNone(lr.scoring_fingerprint_for_league(cfg))

    def test_a_failing_season_resolver_is_not_fresh(self):
        """An unavailable answer is not a passing answer."""
        import src.bdvm.actuals as actuals

        self._write_with_season("111", SCORING_A, season="2026")
        cfg = _cfg("a", "p", "111")
        original = actuals.nfl_projection_season

        def _boom(*_a, **_kw):
            raise RuntimeError("season resolver unavailable")

        actuals.nfl_projection_season = _boom
        self.addCleanup(setattr, actuals, "nfl_projection_season", original)
        lr._scoring_fp_cache.clear()
        self.assertEqual(
            lr.scoring_evidence_state(cfg),
            "stale",
            "a swallowed season-resolver failure still authorized compatibility",
        )
        self.assertIsNone(lr.scoring_fingerprint_for_league(cfg))

    def test_a_matching_season_is_still_fresh(self):
        """Non-vacuity: the strictness must not refuse a real current card."""
        from src.bdvm.actuals import nfl_projection_season

        self._write_with_season("111", SCORING_A, season=str(nfl_projection_season()))
        cfg = _cfg("a", "p", "111")
        self.assertEqual(lr.scoring_evidence_state(cfg), "fresh")
        self.assertTrue(lr.scoring_fingerprint_for_league(cfg))

    def test_the_real_snapshot_writer_records_a_season(self):
        """The repair is only safe if the writer actually supplies one.

        Without this, ``refresh_scoring_snapshot`` could silently start
        producing permanently-stale cards and every cross-league request
        would fail closed forever.
        """
        import inspect

        src = inspect.getsource(lr.refresh_scoring_snapshot)
        self.assertIn("season=info.season", src.replace(" ", "").replace("\n", ""))


class TestTheStampMustAgreeWithTheCard(unittest.TestCase):
    """W18-F001, owner review gap 3 — a stamp is a cache, not an oracle.

    ``meta.scoringFingerprint`` was justified precisely because the
    contract can prove its identity from the scoring card it carries. A
    stamp that contradicts that card is a stale, corrupted or hand-edited
    claim and must not authorize anything.
    """

    @staticmethod
    def _contract(stamp, card):
        out = {"meta": {"leagueKey": "loaded"}, "sleeper": {}}
        if stamp is not None:
            out["meta"]["scoringFingerprint"] = stamp
        if card is not None:
            out["sleeper"]["scoringSettings"] = card
        return out

    def test_an_internally_inconsistent_contract_proves_nothing(self):
        import server
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        fp_a = scoring_fingerprint(SCORING_A)
        contract = self._contract(stamp=fp_a, card=SCORING_B)
        self.assertIsNone(
            server._contract_scoring_fingerprint(contract),
            "a contract whose stamp says A while its own scoring card says B "
            "was still allowed to prove it was A",
        )

    def test_an_agreeing_stamp_is_accepted(self):
        import server
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        fp_a = scoring_fingerprint(SCORING_A)
        self.assertEqual(
            server._contract_scoring_fingerprint(self._contract(fp_a, SCORING_A)),
            fp_a,
        )

    def test_a_card_with_no_stamp_is_accepted(self):
        """The migration path: pre-stamp contracts identify from the card."""
        import server
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        self.assertEqual(
            server._contract_scoring_fingerprint(self._contract(None, SCORING_A)),
            scoring_fingerprint(SCORING_A),
        )

    def test_a_stamp_with_no_card_proves_nothing(self):
        """Decided explicitly, not left to fallback order.

        The documented migration policy makes the CARD the thing that
        keeps existing contracts working — the live board carries 141
        scoring keys and identifies immediately. A stamp alone cannot be
        checked against anything, and unverifiable fails closed.
        """
        import server
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        self.assertIsNone(
            server._contract_scoring_fingerprint(
                self._contract(scoring_fingerprint(SCORING_A), None)
            )
        )

    def test_a_stamp_from_another_fingerprint_version_fails_closed(self):
        import server
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        real = scoring_fingerprint(SCORING_A)
        foreign = "sf0:" + real.split(":", 1)[1]
        self.assertIsNone(
            server._contract_scoring_fingerprint(self._contract(foreign, SCORING_A)),
            "a stamp produced under different normalization rules was compared "
            "as though it were the current version",
        )


class TestFingerprintStability(unittest.TestCase):
    """Properties a compatibility identity must have to be trustworthy.

    The existing ``_scoring_hash`` in sleeper_scoring.py is
    ``sha1(json.dumps(scoring, sort_keys=True, default=str))``. It gets key
    ordering right and everything else wrong for this purpose: ``1`` and
    ``1.0`` serialize differently, and a missing key differs from an
    explicit ``0.0`` even though Sleeper scores an absent rule as zero.
    Promoting it unchanged would manufacture false incompatibility.
    """

    def setUp(self):
        from src.league_comparison.sleeper_scoring import scoring_fingerprint

        self.fp = scoring_fingerprint

    def test_key_order_is_irrelevant(self):
        self.assertEqual(
            self.fp({"rec": 1.0, "pass_td": 4.0}),
            self.fp({"pass_td": 4.0, "rec": 1.0}),
        )

    def test_numeric_form_is_irrelevant(self):
        """1 vs 1.0 vs 1.00 are the same rule to Sleeper."""
        self.assertEqual(self.fp({"rec": 1}), self.fp({"rec": 1.0}))
        self.assertEqual(self.fp({"rec": 1.0}), self.fp({"rec": 1.00}))

    def test_absent_rule_equals_explicit_zero(self):
        """Sleeper scores an absent rule as zero, so they must agree."""
        self.assertEqual(
            self.fp({"rec": 1.0, "bonus_rec_te": 0.0}),
            self.fp({"rec": 1.0}),
        )

    def test_irrelevant_metadata_is_excluded(self):
        """Only valuation-affecting scoring belongs in the identity."""
        self.assertEqual(
            self.fp({"rec": 1.0}),
            self.fp({"rec": 1.0, "league_name": "whatever", "season": "2026"}),
        )

    def test_a_material_scoring_difference_changes_it(self):
        self.assertNotEqual(self.fp(SCORING_A), self.fp(SCORING_B))
        self.assertNotEqual(self.fp({"rec": 1.0}), self.fp({"rec": 0.5}))
        self.assertNotEqual(self.fp({"rec": 1.0}), self.fp({"rec": 1.0, "pass_td": 6.0}))

    def test_missing_input_is_not_a_fingerprint(self):
        """Missing is never zero — and never a hash of an empty dict."""
        self.assertIsNone(self.fp(None))

    def test_it_is_deterministic_across_calls(self):
        self.assertEqual(self.fp(SCORING_A), self.fp(dict(SCORING_A)))


if __name__ == "__main__":
    unittest.main()
