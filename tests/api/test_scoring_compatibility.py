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

import unittest

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
