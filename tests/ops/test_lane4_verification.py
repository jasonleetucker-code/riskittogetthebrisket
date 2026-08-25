"""The verifier's own semantics.

A verification script is only worth what its vocabulary is worth. These pin
the three distinctions the package exists to preserve, because each of them
is a way a run could quietly read as green when it proved nothing:

* a 401 is INSUFFICIENT EVIDENCE, not a pass and not a failure;
* a missing input is BLOCKED, not a pass;
* an input that exists but does not contain the case under test is
  UNMEASURABLE, not a pass.

The checks themselves are exercised against synthetic PAYLOADS, which is not
the same as fabricating production evidence: these are unit inputs to the
analyser, and every one of them lives here in the test file rather than in a
`data/` path any production run would read.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "verify_lane4_production", REPO_ROOT / "scripts" / "verify_lane4_production.py"
)
verify = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
# Registered BEFORE execution: ``@dataclass`` resolves annotations through
# ``sys.modules[cls.__module__]``, so a module loaded by path alone raises
# while processing its own dataclasses.
sys.modules[_SPEC.name] = verify
_SPEC.loader.exec_module(verify)


def _report():
    return verify.Report("onbox", "dynasty_main", None)


def _market(*people):
    return {"assets": [{"assetId": f"p{i}", "personConsensus": p} for i, p in enumerate(people)]}


def _person(**kw):
    base = {
        "personVotes": 1,
        "mixedPersonSignals": 0,
        "weightedPersonVolume": 1.0,
        "personManagerQuality": 0.9,
        "networkConcentration": 1.0,
    }
    base.update(kw)
    return base


# ── The vocabulary ─────────────────────────────────────────────────


class TestStatusVocabulary:
    def test_a_run_that_proves_nothing_does_not_exit_zero(self):
        """The single most important property.

        A run where every check was blocked or unauthenticated has measured
        nothing. Exiting 0 would make "we could not check" indistinguishable
        from "we checked and it was fine" — to a human reading a CI badge,
        and to any automation keying on the code.
        """
        report = _report()
        report.add(verify.Check("X", "V1-58", "t", verify.BLOCKED, ""))
        report.add(verify.Check("Y", "V1-59", "t", verify.UNVERIFIABLE, ""))
        assert report.exit_code() == 3

    def test_a_failure_outranks_everything_else(self):
        report = _report()
        report.add(verify.Check("X", "V1-63", "t", verify.PASS, ""))
        report.add(verify.Check("Y", "V1-129", "t", verify.FAIL, ""))
        report.add(verify.Check("Z", "V1-57", "t", verify.BLOCKED, ""))
        assert report.exit_code() == 2

    def test_an_error_outranks_a_failure(self):
        """An error means a check did not run. That is a different problem
        from a check that ran and disagreed, and it must not be reported as
        the latter."""
        report = _report()
        report.add(verify.Check("Y", "V1-129", "t", verify.FAIL, ""))
        report.add(verify.Check("Z", "V1-57", "t", verify.ERROR, ""))
        assert report.exit_code() == 1

    def test_green_needs_at_least_one_real_pass(self):
        report = _report()
        report.add(verify.Check("X", "V1-63", "t", verify.PASS, ""))
        assert report.exit_code() == 0

    def test_a_single_blocked_check_caps_the_run_at_incomplete(self):
        """Exit 0 is reserved for a COMPLETE run.

        A 401, an absent credential, an empty population, a missing scoring
        card or a missing ledger each leave a question unanswered, and an
        unanswered question is not a pass -- however many other checks passed
        alongside it.
        """
        report = _report()
        report.add(verify.Check("X", "V1-63", "t", verify.PASS, "", denominator=9))
        report.add(verify.Check("Y", "V1-58", "t", verify.BLOCKED, ""))
        assert report.exit_code() == 3

    @pytest.mark.parametrize("status", [verify.BLOCKED, verify.UNVERIFIABLE, verify.UNMEASURABLE])
    def test_every_non_proving_status_caps_the_run(self, status):
        report = _report()
        report.add(verify.Check("X", "V1-63", "t", verify.PASS, "", denominator=9))
        report.add(verify.Check("Y", "-", "t", status, ""))
        assert report.exit_code() == 3

    def test_the_three_non_proving_statuses_are_counted_apart_from_passes(self):
        report = _report()
        for status in (verify.UNMEASURABLE, verify.BLOCKED, verify.UNVERIFIABLE):
            report.add(verify.Check(status, "-", "t", status, ""))
        report.add(verify.Check("P", "-", "t", verify.PASS, ""))
        assert report.to_dict()["applicableChecks"] == 1


class TestUnauthenticatedIsItsOwnAnswer:
    def test_401_and_403_raise_the_dedicated_type(self, monkeypatch):
        """Never swallowed into a generic failure path.

        The measured history on this repo is 80/80 attempts returning 401
        across 79 runs — a definitive answer to "do we hold a credential?",
        which is not the question the check is asking.
        """
        import urllib.error

        def boom(*_args, **_kwargs):
            raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

        monkeypatch.setattr(verify.urllib.request, "urlopen", boom)
        with pytest.raises(verify.Unauthenticated):
            verify._http("https://example.invalid/api/sharp/market", cookie=None)

    def test_no_cookie_means_no_cookie_header(self, monkeypatch):
        """There is no fallback credential path, and this proves it
        structurally rather than by reading the source."""
        seen = {}

        class _Resp:
            status = 200

            def read(self):
                return b"{}"

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def capture(request, timeout=None):
            seen["headers"] = dict(request.headers)
            return _Resp()

        monkeypatch.setattr(verify.urllib.request, "urlopen", capture)
        verify._http("https://example.invalid/api/status", cookie=None)
        assert not any(k.lower() == "cookie" for k in seen["headers"])


# ── The #927 checks ────────────────────────────────────────────────


class TestZeroVoterQuality:
    def test_a_zero_voter_row_with_a_number_fails(self):
        report = _report()
        payload = _market(_person(personVotes=0, mixedPersonSignals=2, personManagerQuality=1.0))
        verify.check_zero_voter_quality(report, payload, "test")
        check = report.checks[0]
        assert check.status == verify.FAIL
        assert check.evidence["offenderCount"] == 1

    def test_a_zero_voter_row_with_null_passes(self):
        report = _report()
        payload = _market(_person(personVotes=0, mixedPersonSignals=2, personManagerQuality=None))
        verify.check_zero_voter_quality(report, payload, "test")
        assert report.checks[0].status == verify.PASS

    def test_a_board_with_no_zero_voter_row_is_inapplicable_not_pass(self):
        """ "We looked and the situation did not arise" is not "we looked and
        it was correct". Collapsing them is the defect class this package
        exists to catch."""
        report = _report()
        verify.check_zero_voter_quality(report, _market(_person()), "test")
        assert report.checks[0].status == verify.UNMEASURABLE

    def test_an_empty_board_is_blocked_not_pass(self):
        report = _report()
        verify.check_zero_voter_quality(report, {"assets": []}, "test")
        assert report.checks[0].status == verify.BLOCKED


class TestMeasuredZeroSurvives:
    def test_a_measured_zero_is_a_pass_not_a_missing_value(self):
        report = _report()
        payload = _market(_person(personVotes=2, personManagerQuality=0.0))
        verify.check_measured_zero_quality(report, payload, "test")
        check = report.checks[0]
        assert check.status == verify.PASS
        assert check.evidence["measuredZeroRows"] == 1

    def test_nulling_a_row_that_has_voters_fails(self):
        """The repair must not overshoot: UNKNOWN and WORST are different
        answers, and a row with voters has an answer."""
        report = _report()
        payload = _market(_person(personVotes=3, personManagerQuality=None))
        verify.check_measured_zero_quality(report, payload, "test")
        assert report.checks[0].status == verify.FAIL


class TestUndefinedConcentration:
    def test_zero_volume_with_a_number_fails(self):
        report = _report()
        payload = _market(_person(weightedPersonVolume=0.0, networkConcentration=0.0))
        verify.check_undefined_concentration(report, payload, "test")
        assert report.checks[0].status == verify.FAIL

    def test_zero_volume_with_null_passes(self):
        report = _report()
        payload = _market(_person(weightedPersonVolume=0.0, networkConcentration=None))
        verify.check_undefined_concentration(report, payload, "test")
        assert report.checks[0].status == verify.PASS


class TestCrowdRefusalReasons:
    def test_a_build_without_target_format_unknown_fails(self):
        """Pre-#927: an undescribable target and an absent feed report the
        same thing, so the reader is sent to the wrong place."""
        report = _report()
        verify.check_crowd_refusal_reasons(
            report, {"crowdMarket": {"state": "missing", "refusalReason": "no_crowd_ledger"}}, "t"
        )
        assert report.checks[0].status == verify.FAIL

    def test_an_undescribable_target_must_name_our_side(self):
        report = _report()
        verify.check_crowd_refusal_reasons(
            report,
            {
                "crowdMarket": {
                    "state": "missing",
                    "targetFormatUnknown": ["tep"],
                    "refusalReason": "no_crowd_ledger",
                }
            },
            "t",
        )
        assert report.checks[0].status == verify.FAIL

    def test_the_correct_refusal_passes(self):
        report = _report()
        verify.check_crowd_refusal_reasons(
            report,
            {
                "crowdMarket": {
                    "state": "missing",
                    "targetFormatUnknown": ["tep"],
                    "refusalReason": "target_format_unverifiable:tep",
                }
            },
            "t",
        )
        assert report.checks[0].status == verify.PASS

    def test_a_fresh_fully_described_market_passes(self):
        report = _report()
        verify.check_crowd_refusal_reasons(
            report,
            {"crowdMarket": {"state": "fresh", "targetFormatUnknown": [], "refusalReason": None}},
            "t",
        )
        assert report.checks[0].status == verify.PASS


class TestCrowdEffectOnTheBid:
    def test_a_refused_crowd_that_still_contributes_a_factor_fails(self):
        """A refusal that still moves the number is cosmetic."""
        report = _report()
        verify.check_faab_recommendation_effect(
            report,
            {
                "crowdMarket": {
                    "state": "missing",
                    "playerHasEvidence": False,
                    "refusalReason": "no_crowd_ledger",
                },
                "factors": [{"label": "Cross-league market", "contribution": "..."}],
            },
            "t",
        )
        assert report.checks[0].status == verify.FAIL

    def test_an_admitted_crowd_with_no_visible_factor_fails(self):
        report = _report()
        verify.check_faab_recommendation_effect(
            report,
            {
                "crowdMarket": {"state": "fresh", "playerHasEvidence": True},
                "factors": [{"label": "Expected competition"}],
            },
            "t",
        )
        assert report.checks[0].status == verify.FAIL

    def test_a_refused_crowd_with_no_factor_passes(self):
        report = _report()
        verify.check_faab_recommendation_effect(
            report,
            {
                "crowdMarket": {
                    "state": "stale",
                    "playerHasEvidence": False,
                    "refusalReason": "crowd_ledger_stale",
                },
                "factors": [{"label": "Expected competition"}],
                "standard": 12,
            },
            "t",
        )
        assert report.checks[0].status == verify.PASS


# ── Mutation proofs: the guards must be able to go red ─────────────
#
# A verification tool that has never been observed failing is an
# unfalsifiable claim of exactly the kind it exists to prevent. Each test
# below breaks one thing and asserts the verifier notices.


class TestItDetectsAWrongEndpoint:
    def test_a_route_that_does_not_exist_fails(self, monkeypatch):
        """The defect that motivated this package.

        `POST /api/faab/recommend` was named in the shipped procedures and is
        not a route — there is no `/api/faab/*` prefix at all.
        """
        monkeypatch.setattr(
            verify, "REQUIRED_ROUTES", (("/api/faab/recommend", "POST"),), raising=True
        )
        report = _report()
        verify.check_required_routes_exist(report)
        check = report.checks[0]
        assert check.status == verify.FAIL
        assert check.evidence["missing"] == ["POST /api/faab/recommend"]

    def test_the_real_route_passes(self, monkeypatch):
        """The converse, so the check cannot pass by matching nothing."""
        monkeypatch.setattr(
            verify, "REQUIRED_ROUTES", (("/api/waiver/faab-recommend", "POST"),), raising=True
        )
        report = _report()
        verify.check_required_routes_exist(report)
        check = report.checks[0]
        assert check.status == verify.PASS
        assert check.denominator == 1
        assert check.evidence["routesDiscovered"] > 50

    def test_the_shipped_routes_all_exist_right_now(self):
        """The live assertion, not a fixture: every route this package names
        is registered at HEAD. This is what fails if someone renames one."""
        report = _report()
        verify.check_required_routes_exist(report)
        assert report.checks[0].status == verify.PASS, report.checks[0].detail

    def test_the_wrong_method_is_also_caught(self, monkeypatch):
        """A route registered only for POST must not pass a GET step."""
        monkeypatch.setattr(
            verify, "REQUIRED_ROUTES", (("/api/waiver/faab-recommend", "GET"),), raising=True
        )
        report = _report()
        verify.check_required_routes_exist(report)
        assert report.checks[0].status == verify.FAIL


class TestItDetectsARenamedField:
    def test_a_missing_field_path_fails(self):
        report = _report()
        verify.check_required_fields_exist(report, {"crowd-market": {"state": "fresh"}})
        check = report.checks[0]
        assert check.status == verify.FAIL
        assert any("targetFormatUnknown" in m for m in check.evidence["missing"])

    def test_a_field_present_but_null_is_present(self):
        """Presence, not truthiness.

        `cohortCoveragePct: null` is the CORRECT unmeasured state, so a
        truthiness test here would report right behaviour as a missing field —
        inverting the very invariant the field exists to express.
        """
        present, value = verify._dotted(
            {"transparency": {"cohortCoveragePct": None}}, "transparency.cohortCoveragePct"
        )
        assert present is True and value is None

    def test_a_field_nested_under_the_wrong_parent_is_absent(self):
        """The exact defect found in the shipped doc: `cohortCoveragePct` was
        read from `cohort`, where it has never lived."""
        board = {"cohort": {"selectedManagers": 0}, "transparency": {"cohortCoveragePct": None}}
        assert verify._dotted(board, "cohort.cohortCoveragePct")[0] is False
        assert verify._dotted(board, "transparency.cohortCoveragePct")[0] is True

    def test_no_producer_available_is_blocked_not_pass(self):
        report = _report()
        verify.check_required_fields_exist(report, {})
        check = report.checks[0]
        assert check.status == verify.BLOCKED
        assert check.denominator == 0

    def test_the_shipped_field_paths_all_exist_right_now(self):
        """Live, against the real producers. Fails if a payload is reshaped."""
        from src.sharp import market as sharp_market
        from src.sharp import roster_percentage
        from src.trade.faab_history import CrowdMarket

        report = _report()
        verify.check_required_fields_exist(
            report,
            {
                "roster-percentage": roster_percentage.build_board(),
                "sharp-market": sharp_market.market_payload(window="30d", limit=1),
                "crowd-market": CrowdMarket().to_dict(),
            },
        )
        check = report.checks[0]
        assert check.status == verify.PASS, check.detail
        assert check.denominator == len(verify.REQUIRED_FIELDS)


class TestItCannotBeGreenWhileInspectingNothing:
    def test_a_pass_over_an_empty_population_is_downgraded(self):
        """The structural anti-vacuous-green guard.

        A check that iterates an empty list and finds no offenders looks
        exactly like one that examined a thousand rows and found none. The
        denominator is what tells them apart, and the downgrade happens in
        `Check.finalize` rather than at each call site so one forgotten guard
        cannot produce a false green.
        """
        check = verify.Check("X", "-", "t", verify.PASS, "all good", denominator=0)
        check.finalize()
        assert check.status == verify.UNMEASURABLE
        assert "proved nothing" in check.detail

    def test_a_pass_over_a_real_population_survives(self):
        check = verify.Check("X", "-", "t", verify.PASS, "all good", denominator=7)
        check.finalize()
        assert check.status == verify.PASS

    def test_a_denominator_of_none_is_exempt(self):
        """Structural checks — a route registration, a file's presence — have
        no population, and must not be downgraded for lacking one."""
        check = verify.Check("X", "-", "t", verify.PASS, "registered", denominator=None)
        check.finalize()
        assert check.status == verify.PASS

    def test_a_failure_is_never_downgraded(self):
        check = verify.Check("X", "-", "t", verify.FAIL, "broken", denominator=0)
        check.finalize()
        assert check.status == verify.FAIL

    def test_the_report_finalises_every_check(self):
        report = _report()
        report.add(verify.Check("A", "-", "t", verify.PASS, "", denominator=0))
        report.add(verify.Check("B", "-", "t", verify.PASS, "", denominator=3))
        report.finalize()
        assert [c.status for c in report.checks] == [verify.UNMEASURABLE, verify.PASS]
        # ...and with the only "pass" downgraded, a run of just A proves nothing.
        solo = _report()
        solo.add(verify.Check("A", "-", "t", verify.PASS, "", denominator=0))
        solo.finalize()
        assert solo.exit_code() == 3


class TestItDetectsAnEmptyPopulation:
    def test_an_empty_market_blocks_rather_than_passing(self):
        report = _report()
        verify.check_zero_voter_quality(report, {"assets": []}, "test")
        assert report.checks[0].status == verify.BLOCKED

    def test_rows_without_the_case_are_unmeasurable_and_carry_a_zero_denominator(self):
        report = _report()
        verify.check_zero_voter_quality(report, _market(_person()), "test")
        check = report.checks[0]
        assert check.status == verify.UNMEASURABLE
        assert check.evidence["rowsWithPersonConsensus"] == 1


class TestItDetectsStaleEvidence:
    @pytest.mark.parametrize("state", ["stale", "missing", "", "unknown"])
    def test_unproven_scoring_with_a_positive_tep_claim_fails(self, state):
        """Stale evidence that still yields a TEP answer is unproven scoring
        promoted to a positive claim."""
        from src.trade.faab_comparability import TargetFormat

        report = _report()
        ctx = {
            "evidenceState": state,
            "target": TargetFormat(teams=12, superflex=True, tep=True),
        }
        verify.check_unproven_scoring_fails_closed(report, ctx)
        assert report.checks[0].status == verify.FAIL

    def test_unproven_scoring_that_fails_closed_passes(self):
        from src.trade.faab_comparability import TargetFormat

        report = _report()
        ctx = {"evidenceState": "stale", "target": TargetFormat(teams=12, superflex=True, tep=None)}
        verify.check_unproven_scoring_fails_closed(report, ctx)
        check = report.checks[0]
        assert check.status == verify.PASS
        assert "tep" in check.evidence["unprovableTargetFields"]

    def test_fresh_evidence_makes_the_stale_branch_unmeasurable_not_passed(self):
        from src.trade.faab_comparability import TargetFormat

        report = _report()
        ctx = {
            "evidenceState": "fresh",
            "target": TargetFormat(teams=12, superflex=True, tep=False),
        }
        verify.check_unproven_scoring_fails_closed(report, ctx)
        assert report.checks[0].status == verify.UNMEASURABLE


class TestItDetectsTheTepRule:
    def test_the_deployed_rule_is_read_from_the_signature(self):
        """Signature-first, because a behaviour-only check passes on a
        label-rule build whenever the label happens to agree with the card."""
        assert verify._deployed_tep_rule() == "card"

    def test_a_card_with_no_te_edge_yields_a_false_tep(self):
        """The measured `dynasty_main` shape, asserted through the same owner
        the verifier uses rather than a reimplementation."""
        from src.league_intel.te_premium import measure_te_demand

        card = {"rec": 1.0, "bonus_rec_te": 0.0, "bonus_fd_te": 1.0, "bonus_fd_wr": 1.0}
        assert measure_te_demand(None, card).has_scoring_edge is False

    def test_a_card_with_a_te_edge_yields_a_true_tep(self):
        from src.league_intel.te_premium import measure_te_demand

        assert measure_te_demand(None, {"bonus_rec_te": 0.5}).has_scoring_edge is True


class TestItDetectsIdpRefusal:
    class _Market:
        def __init__(self, prices_idp, rows_used=40):
            self.prices_idp = prices_idp
            self.rows_used = rows_used

    def test_an_offense_only_population_refuses_idp_and_still_prices_offense(self):
        report = _report()
        verify.check_idp_population_refusal(report, self._Market(prices_idp=False))
        check = report.checks[0]
        assert check.status == verify.PASS
        assert check.evidence["idpPositionsRefused"] == ["DL", "LB", "DB"]
        assert check.evidence["offensePositionsAllowed"] == ["QB", "RB", "WR", "TE"]

    def test_a_population_containing_an_idp_league_is_unmeasurable_not_failed(self):
        """The gate reads what the retained rows contain, so it self-corrects
        the day an IDP league appears. That is a finding about the feed."""
        report = _report()
        verify.check_idp_population_refusal(report, self._Market(prices_idp=True))
        assert report.checks[0].status == verify.UNMEASURABLE

    def test_no_ledger_is_blocked_never_passed(self):
        report = _report()
        verify.check_idp_population_refusal(report, None)
        assert report.checks[0].status == verify.BLOCKED


#: A ``/api/...`` token followed by one of these is a FILE PATH, not a route
#: claim -- ``tests/api/test_x.py``, ``frontend/app/api/.../route.js``. A
#: procedures document legitimately cites the test file an operator should run,
#: and before this exclusion existed such a citation was read as a phantom
#: route and failed the guard below.
_SOURCE_FILE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".json")

#: The corrections quote the retired names in order to say they are wrong.
#: Quoting a wrong name must stay legal, or the document cannot record its own
#: history -- so the whole retired prefix is exempt, and naming it is the point
#: rather than an oversight.
_RETIRED_ROUTE_PREFIX = "/api/faab"


def _routes_named_in(text: str) -> set[str]:
    """Every ``/api/...`` token in ``text`` that is a route CLAIM.

    Pure over its input so the extraction rule can be exercised against
    synthetic strings. Asserting it against the real document instead would be
    vacuous: every route that appears there as a curl target also appears in
    prose, so a rule that dropped the curl form entirely would still leave the
    route in the set and the test would pass while the rule was broken. That
    is not hypothetical -- it is what a first cut of these tests did.

    The exclusion keys on the token's **suffix**, never on what PRECEDES it.
    ``/api/`` sits mid-token in both a curl target
    (``https://chaseupside.com/api/sharp/cohort``) and a file path
    (``tests/api/test_x.py``), so a "must be preceded by a delimiter" rule
    cannot tell a route from a path -- it just drops both.
    """
    import re

    named: set[str] = set()
    for match in re.finditer(r"/api/[a-zA-Z0-9/_{}-]+", text):
        token = match.group(0)
        if token.startswith(_RETIRED_ROUTE_PREFIX):
            continue
        # The character class excludes ``.``, so the match stops immediately
        # before any extension and the tail is inspectable here.
        if text[match.end() :].startswith(_SOURCE_FILE_SUFFIXES):
            continue
        named.add(token.rstrip("/.,`*"))
    return named


def _routes_named_by_the_procedures_doc() -> set[str]:
    doc = REPO_ROOT / "docs" / "lane4" / "L2_L3_VERIFICATION_PROCEDURES.md"
    return _routes_named_in(doc.read_text(encoding="utf-8"))


class TestTheDocumentItselfNamesRealRoutes:
    """The regression guard on the corrected procedures document.

    Every `/api/...` path the document names must be registered. This is what
    would have caught `POST /api/faab/recommend` before it shipped, and it is
    the reason a correction is worth more than a superseding document.
    """

    def test_every_api_path_in_the_procedures_doc_is_a_real_route(self):
        named = _routes_named_by_the_procedures_doc()
        registered = {path for path, _method in verify._registered_routes_static()}
        assert named, "the guard must not pass by matching nothing"
        missing = sorted(n for n in named if n not in registered and not n.endswith("/*"))
        # `/api/sharp/` appears as a prefix in prose; allow bare prefixes that
        # are the parent of a real route.
        missing = [
            n for n in missing if not any(r.startswith(n.rstrip("/") + "/") for r in registered)
        ]
        assert missing == [], f"procedures doc names unregistered routes: {missing}"


# ── Adversarial review findings, pinned ────────────────────────────


class TestFreshEvidenceIsNotTheSameAsAReadableCard:
    """C4 could report PASS having observed no card at all.

    `scoring_evidence_state` decides freshness from the snapshot's fetch
    timestamp and season — it never reads `scoringSettings` — so a snapshot
    written by a partial fetch is `fresh` while carrying no card. In that
    state `_tep_from_scoring` correctly returns `None` (fail-closed, so the
    product is fine), the served value then equalled the derived value
    trivially (both `None`), and the check reported **pass** with the detail
    "derived from the fresh card".

    That is a false green in the check whose whole job is to prove TEP is
    card-derived: Integration could have recorded the capability as observed
    without a card ever existing.
    """

    @staticmethod
    def _run(card, evidence="fresh"):
        import types
        from unittest import mock

        from src.api import league_registry

        report = _report()
        cfg = types.SimpleNamespace(
            key="dynasty_main", scoring_profile="superflex_tep15_ppr1", idp_enabled=True
        )
        with (
            mock.patch.object(league_registry, "get_league_by_key", return_value=cfg),
            mock.patch.object(league_registry, "scoring_evidence_state", return_value=evidence),
            mock.patch.object(league_registry, "scoring_settings_for_league", return_value=card),
            mock.patch.object(
                league_registry,
                "get_league_roster_settings",
                return_value={"teamCount": 12, "starters": {"QB": 1, "TE": 2, "SFLEX": 1}},
            ),
        ):
            verify.check_tep_is_card_derived(report, "dynasty_main")
        report.finalize()
        return report.checks[0]

    @pytest.mark.parametrize("card", [{}, None])
    def test_a_fresh_snapshot_with_no_card_is_blocked_not_passed(self, card):
        check = self._run(card)
        assert check.status == verify.BLOCKED
        assert check.evidence["cardPresent"] is False
        assert "no scoringSettings" in check.detail

    def test_a_fresh_snapshot_with_a_real_card_still_passes(self):
        """The converse, so the repair cannot pass by refusing everything."""
        check = self._run({"rec": 1.0, "bonus_rec_te": 0.0, "bonus_fd_te": 1.0, "bonus_fd_wr": 1.0})
        assert check.status == verify.PASS
        assert check.evidence["cardPresent"] is True
        assert check.evidence["servedTep"] is False

    def test_c6_already_handled_this_and_still_does(self):
        """C6 blocked on an absent card from the start. That asymmetry is why
        C4's omission reads as an oversight rather than a decision, and this
        keeps the two consistent."""
        report = _report()
        verify.check_dynasty_main_is_not_te_premium(report, {"card": None}, "dynasty_main")
        assert report.checks[0].status == verify.BLOCKED


class TestTheRequiredListsCannotBeSilentlyEmptied:
    """Emptying `REQUIRED_ROUTES` disarmed the route guard with **zero** test
    failures — the "a verifier test that itself matches nothing" case.

    At runtime `Check.finalize` downgrades the resulting zero-denominator pass
    to `unmeasurable`, so the verifier itself stays honest. What was missing is
    that **CI would not tell anyone the guard had been disarmed**: a refactor,
    a bad merge, or a well-meaning cleanup could empty the list and every test
    would stay green. `REQUIRED_FIELDS` was already covered by two tests; this
    closes the asymmetry.
    """

    def test_the_route_list_is_not_empty(self):
        assert verify.REQUIRED_ROUTES, "the route guard has been disarmed"

    def test_the_field_list_is_not_empty(self):
        assert verify.REQUIRED_FIELDS, "the field guard has been disarmed"

    @pytest.mark.parametrize(
        "route",
        [
            ("/api/waiver/faab-recommend", "POST"),
            ("/api/sharp/market", "GET"),
            ("/api/sharp/roster-percentage", "GET"),
            ("/api/sharp/cohort", "GET"),
            ("/api/status", "GET"),
        ],
    )
    def test_each_route_the_procedures_depend_on_is_still_guarded(self, route):
        """Named individually, so dropping ONE — which an empty-list check
        would not catch — fails here."""
        assert route in verify.REQUIRED_ROUTES

    @pytest.mark.parametrize(
        "field",
        [
            ("roster-percentage", "transparency.cohortCoveragePct"),
            ("crowd-market", "targetFormatUnknown"),
            ("crowd-market", "pricesIdp"),
            ("sharp-market", "coverage.platforms"),
        ],
    )
    def test_each_field_a_correction_depends_on_is_still_guarded(self, field):
        """These four are precisely the paths the six documented corrections
        turned on. If one stops being guarded, the correction it protects can
        silently rot back."""
        assert field in verify.REQUIRED_FIELDS

    def test_a_route_named_only_as_a_curl_target_is_still_scanned(self):
        """The exclusion must not be re-implemented as a LOOKBEHIND.

        In ``https://chaseupside.com/api/sharp/cohort`` the ``/api/`` is
        preceded by the ``m`` of ``.com``, exactly as it is preceded by the
        ``s`` of ``tests`` in a file path. Suppressing the file-path false
        positive by requiring a delimiter before the token therefore drops
        curl targets too -- and a procedures document whose whole purpose is
        recording curl commands would then be checked barely at all.

        Asserted on synthetic text rather than the real document ON PURPOSE:
        every route the doc curls is also named in prose, so a broken rule
        still leaves it in the set and a test over the real file passes while
        proving nothing.
        """
        only_curled = "curl -s 'https://chaseupside.com/api/sharp/cohort' -b \"$C\"\n"
        assert _routes_named_in(only_curled) == {"/api/sharp/cohort"}

    def test_a_route_named_only_inside_a_source_file_path_is_not_a_route(self):
        """The failure this exclusion was written for.

        ``tests/api/test_feature_flag_endpoint_reachability.py`` contains the
        substring ``/api/test_feature_flag_endpoint_reachability``. Citing that
        file -- which the procedures document does, because an operator needs
        to know which suite to run -- produced a phantom route and failed the
        guard.
        """
        cited = "python -m pytest tests/api/test_feature_flag_endpoint_reachability.py -q\n"
        assert _routes_named_in(cited) == set()
        # …and the real document, which now contains exactly that citation,
        # carries no phantom route either.
        phantoms = sorted(
            n for n in _routes_named_by_the_procedures_doc() if n.startswith("/api/test_")
        )
        assert phantoms == [], f"file paths are being read as routes: {phantoms}"

    def test_the_two_rules_do_not_cancel_each_other_out(self):
        """Non-vacuity for the pair.

        Both tests above assert on a SINGLE-token string, so a rule that
        returned the empty set for everything would pass the second and fail
        the first, and one that returned every token would do the reverse.
        This pins that one string containing both forms splits them.
        """
        mixed = (
            "run `pytest tests/api/test_x.py`, then "
            "curl 'https://chaseupside.com/api/sharp/market'\n"
        )
        assert _routes_named_in(mixed) == {"/api/sharp/market"}

# ── V1-65: the league-population census ────────────────────────────


def _intel_ledger(tmp_path, monkeypatch):
    """A tmp intel ledger, schema applied — the test_discovery pattern."""
    from src.intel import ledger, store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    path = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(path).close()
    return path


def _league_row(league_id, *, type_=2, best_ball=0, signal=True, sharp=True, age=2, omit_age=False):
    import json

    settings = {
        "type": type_,
        "bestBall": best_ball,
        "signalEligible": signal,
        "sharpEligible": sharp,
        "ageSeasons": age,
    }
    if omit_age:
        settings.pop("ageSeasons")
    return {
        "league_id": league_id,
        "season": "2026",
        "previous_league_id": "prev" if age >= 2 else "",
        "name": f"League {league_id}",
        "total_rosters": 12,
        "settings_json": json.dumps(settings),
    }


class TestLeaguePopulationCensus:
    """V1-65's L2 census: signal- vs sharp-admitted, with the difference
    explained rather than merely counted."""

    def test_a_populated_ledger_yields_the_census_and_the_reason_histogram(
        self, tmp_path, monkeypatch
    ):
        from src.intel import ledger

        path = _intel_ledger(tmp_path, monkeypatch)
        ledger.upsert_leagues(
            [
                # signal AND sharp: dynasty, 2 seasons.
                _league_row("DYN_OLD", type_=2, signal=True, sharp=True, age=2),
                # signal only: keeper (dynasty-adjacent, never sharp).
                _league_row("KEEP", type_=1, signal=True, sharp=False, age=2),
                # signal only: first-year dynasty.
                _league_row("DYN_NEW", type_=2, signal=True, sharp=False, age=1),
                # neither: best-ball and redraft.
                _league_row("BB", type_=2, best_ball=1, signal=False, sharp=False),
                _league_row("RED", type_=0, signal=False, sharp=False),
            ],
            path=path,
        )
        conn = ledger.connect(path)
        try:
            conn.execute(
                "INSERT INTO manager_seasons (league_id, season, user_id, is_complete, "
                "sharp_eligible) VALUES ('DYN_OLD', '2025', 'u1', 1, 1)"
            )
            conn.commit()
        finally:
            conn.close()

        report = _report()
        verify.check_league_population_difference(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.PASS, check.detail
        assert check.evidence["signalAdmitted"] == 3
        assert check.evidence["sharpAdmitted"] == 1
        assert check.evidence["sharpOnlyCount"] == 0
        assert check.evidence["signalOnlyCount"] == 2
        assert sorted(check.evidence["signalOnlySample"]) == ["DYN_NEW", "KEEP"]
        assert check.evidence["sharpExclusionReasons"] == {"keeper": 1, "too_new": 1}
        assert check.evidence["managerSeasonsSharpCompleteLeagues"] == 1
        assert check.denominator == 5

    def test_a_sharp_league_outside_the_signal_set_fails(self, tmp_path, monkeypatch):
        """Sharp is strictly narrower by definition; a member here means the
        two gates disagreed about the same stored evidence."""
        from src.intel import ledger

        path = _intel_ledger(tmp_path, monkeypatch)
        ledger.upsert_leagues(
            [_league_row("WEIRD", type_=2, signal=False, sharp=True, age=2)], path=path
        )
        report = _report()
        verify.check_league_population_difference(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.FAIL
        assert check.evidence["sharpOnlySample"] == ["WEIRD"]

    def test_an_unrecorded_age_is_not_reported_as_too_new(self, tmp_path, monkeypatch):
        """Missing is never a value: a league whose stored settings carry no
        ageSeasons must not read as a measured 'too new'."""
        from src.intel import ledger

        path = _intel_ledger(tmp_path, monkeypatch)
        ledger.upsert_leagues(
            [_league_row("NOAGE", type_=2, signal=True, sharp=False, age=1, omit_age=True)],
            path=path,
        )
        report = _report()
        verify.check_league_population_difference(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.PASS
        assert check.evidence["sharpExclusionReasons"] == {"age_unrecorded": 1}

    def test_an_empty_leagues_table_is_unmeasurable_never_pass(self, tmp_path, monkeypatch):
        path = _intel_ledger(tmp_path, monkeypatch)
        report = _report()
        verify.check_league_population_difference(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.UNMEASURABLE
        assert "carries no discovered leagues here" in check.detail
        assert check.evidence["ledgerPresent"] is True

    def test_an_absent_ledger_is_blocked_and_is_not_created(self, tmp_path):
        """Read-only: probing for the store must not mint one — an empty
        ledger this check created would be indistinguishable from a real
        empty crawl on the next run."""
        path = tmp_path / "absent" / "ledger.sqlite3"
        report = _report()
        verify.check_league_population_difference(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.BLOCKED
        assert check.evidence["ledgerPresent"] is False
        assert not path.exists()


# ── V1-58: the in-process cohort resolution ────────────────────────


class TestCohortPopulationOnbox:
    """On the box the cohort is resolvable in-process through the canonical
    owner — the same pattern run_onbox uses for the market and roster
    boards. Two honesty rules: a measured zero over present stores is a
    truthful pass-with-populated-false, and absent stores are blocked."""

    def test_an_absent_store_is_blocked_and_is_not_created(self, tmp_path):
        path = tmp_path / "absent" / "ledger.sqlite3"
        report = _report()
        verify.check_cohort_population_onbox(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.BLOCKED
        assert check.evidence["ledgerPresent"] is False
        assert not path.exists()

    def test_a_measured_zero_over_present_stores_is_a_truthful_pass(self, tmp_path, monkeypatch):
        """Zero members with the stores present is a REAL measured answer.

        Not converted to FAILED (an empty cohort is a finding about the
        deployed data, not about the check), not presented as populated,
        and not downgraded by the vacuous-pass guard — this check verifies
        measurability, so its denominator is deliberately None.
        """
        from src.sharp import cohort

        path = _intel_ledger(tmp_path, monkeypatch)
        monkeypatch.setattr(cohort, "load_ffpc_config", lambda path=None: {})
        # The curated-industry population reads a separate store that may or
        # may not exist in a dev checkout; pin it empty so this test measures
        # the automated path over the tmp ledger deterministically.
        monkeypatch.setattr(cohort, "curated_industry_members", lambda qualification: [])
        report = _report()
        verify.check_cohort_population_onbox(report, ledger_path=path)
        report.finalize()
        check = report.checks[0]
        assert check.status == verify.PASS, check.detail
        assert check.evidence["populated"] is False
        assert check.evidence["memberCount"] == 0
        assert "ZERO" in check.detail and "measured" in check.detail

    def test_a_populated_cohort_reports_the_qualification_and_platform_split(
        self, tmp_path, monkeypatch
    ):
        from src.sharp import cohort

        path = _intel_ledger(tmp_path, monkeypatch)
        members = [
            cohort.CohortMember("sleeper:u1", "sleeper", "automated_qualified", 0.9),
            cohort.CohortMember("ffpc:m1", "ffpc", "curated_high_stakes", 0.75),
        ]
        coverage = {
            "automatedQualifiedManagers": 1,
            "curatedManagers": 1,
            "provisionalManagers": 0,
            "evidenceManagers": 5,
            "methodologyVersion": "sharp-v2-test",
        }
        monkeypatch.setattr(cohort, "cohort_members", lambda **kw: (members, coverage))
        report = _report()
        verify.check_cohort_population_onbox(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.PASS
        assert check.evidence["populated"] is True
        assert check.evidence["memberCount"] == 2
        assert check.evidence["byQualificationMethod"] == {
            "automated_qualified": 1,
            "curated_high_stakes": 1,
        }
        assert check.evidence["byPlatform"] == {"sleeper": 1, "ffpc": 1}
        assert check.evidence["coverage"]["methodologyVersion"] == "sharp-v2-test"


class TestBlockedRowsModeSplit:
    """B58 stays blocked only where nothing measured it: REMOTE mode.

    On the box check_cohort_population_onbox resolves the cohort in-process,
    so recording the row as blocked there would deny a measurement the run
    just made. B59 stays blocked in both modes.
    """

    def test_remote_mode_records_both_rows_blocked(self):
        report = _report()
        verify.record_blocked_rows(report, None, mode="remote")
        assert [c.row for c in report.checks] == ["V1-58", "V1-59"]
        assert all(c.status == verify.BLOCKED for c in report.checks)

    def test_remote_mode_with_a_401_records_both_rows_unverifiable(self):
        report = _report()
        verify.record_blocked_rows(report, "401 from /api/sharp/cohort", mode="remote")
        assert [c.row for c in report.checks] == ["V1-58", "V1-59"]
        assert all(c.status == verify.UNVERIFIABLE for c in report.checks)

    def test_onbox_mode_keeps_only_b59(self):
        report = _report()
        verify.record_blocked_rows(report, None, mode="onbox")
        assert [c.row for c in report.checks] == ["V1-59"]
        assert report.checks[0].status == verify.BLOCKED

    def test_run_onbox_actually_registers_the_in_process_check(self):
        """Non-vacuity: the mode split is only honest if the on-box run
        REPLACES the blocked row with a measurement rather than dropping it."""
        import inspect

        source = inspect.getsource(verify.run_onbox)
        assert "check_cohort_population_onbox(report)" in source
        assert 'record_blocked_rows(report, None, mode="onbox")' in source


# ── V1-87: the rank-change flag's blast radius ─────────────────────


def _temporal_ledger(tmp_path):
    from src.history import store

    store._reset_setup_cache_for_tests()
    path = tmp_path / "temporal_ledger.sqlite"
    store.connect(path).close()
    return path


def _record_board(path, observed_date, ranks_by_player):
    """One canonical_board date: ``{player_suffix: rank}``."""
    from src.history import store

    result = store.write_observations(
        [
            {
                "asset_key": f"player:{suffix}",
                "asset_class": "offense",
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": observed_date,
                "rank": rank,
                "value": 1000.0 - rank,
                "origin": "test",
            }
            for suffix, rank in ranks_by_player.items()
        ],
        path=path,
    )
    assert not result["rejected"], result["rejected"]
    return result


class TestLedgerRankChangeFlag:
    """V1-87: the flag's ON/OFF blast radius, measured against a ledger with
    real canonical_board rows — and honestly unmeasurable without one, since
    with no ledger BOTH branches stamp None and the diff is vacuous."""

    def test_two_board_dates_yield_the_measured_blast_radius(self, tmp_path):
        path = _temporal_ledger(tmp_path)
        _record_board(path, "2026-08-01", {"1": 10, "2": 20, "3": 30})
        # player:4 is new on the second board: ranked, but no comparator,
        # so the ON branch stamps None for it — it must not count.
        _record_board(path, "2026-08-02", {"2": 15, "3": 35, "4": 40})
        report = _report()
        verify.check_ledger_rank_change_flag(report, ledger_path=path)
        report.finalize()
        check = report.checks[0]
        assert check.status == verify.PASS, check.detail
        assert check.evidence["canonicalBoardRows"] == 6
        assert check.evidence["canonicalBoardDates"] == 2
        assert check.evidence["newestBoardDate"] == "2026-08-02"
        assert check.evidence["comparatorDate"] == "2026-08-01"
        assert check.evidence["rankedRowsOnNewestBoard"] == 3
        assert check.evidence["nonNullRankChangeOn"] == 2
        assert check.evidence["nonNullRankChangeOff"] == 0
        assert check.evidence["offIsStructural"] is True
        assert check.evidence["delta"] == 2
        assert check.denominator == 3

    def test_a_single_board_date_is_unmeasurable_not_zero(self, tmp_path):
        """One date has no strictly-prior comparator. Reporting a blast
        radius of 0 there would present 'cannot measure' as 'measured
        nothing moved'."""
        path = _temporal_ledger(tmp_path)
        _record_board(path, "2026-08-01", {"1": 10, "2": 20})
        report = _report()
        verify.check_ledger_rank_change_flag(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.UNMEASURABLE
        assert "strictly-prior comparator" in check.detail
        assert check.evidence["canonicalBoardDates"] == 1

    def test_an_absent_ledger_is_unmeasurable_and_is_not_created(self, tmp_path):
        path = tmp_path / "absent" / "temporal_ledger.sqlite"
        report = _report()
        verify.check_ledger_rank_change_flag(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.UNMEASURABLE
        assert "environment artifact" in check.detail
        assert check.evidence["ledgerPresent"] is False
        assert not path.exists()

    def test_a_ledger_without_canonical_board_rows_is_unmeasurable(self, tmp_path):
        """Other lanes are not the served board; their presence must not
        make the flag's blast radius look measurable."""
        from src.history import store

        path = _temporal_ledger(tmp_path)
        result = store.write_observations(
            [
                {
                    "asset_key": "player:1",
                    "asset_class": "offense",
                    "lane": store.LANE_SOURCE,
                    "source_key": "ktcSfTep",
                    "observed_date": "2026-08-01",
                    "value": 5000.0,
                    "origin": "test",
                }
            ],
            path=path,
        )
        assert result["written"] == 1
        report = _report()
        verify.check_ledger_rank_change_flag(report, ledger_path=path)
        check = report.checks[0]
        assert check.status == verify.UNMEASURABLE
        assert check.evidence["canonicalBoardRows"] == 0
        assert check.evidence["laneRowCounts"].get(store.LANE_SOURCE) == 1
