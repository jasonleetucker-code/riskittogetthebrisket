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


class TestTheDocumentItselfNamesRealRoutes:
    """The regression guard on the corrected procedures document.

    Every `/api/...` path the document names must be registered. This is what
    would have caught `POST /api/faab/recommend` before it shipped, and it is
    the reason a correction is worth more than a superseding document.
    """

    def test_every_api_path_in_the_procedures_doc_is_a_real_route(self):
        import re

        doc = REPO_ROOT / "docs" / "lane4" / "L2_L3_VERIFICATION_PROCEDURES.md"
        text = doc.read_text(encoding="utf-8")
        registered = {path for path, _method in verify._registered_routes_static()}
        # The corrections quote the retired names in order to say they are
        # wrong. Quoting a wrong name must stay legal, or the document cannot
        # record its own history -- so the whole retired prefix is exempt, and
        # naming it is the point rather than an oversight.
        retired_prefix = "/api/faab"
        named = {
            m.rstrip("/.,`*")
            for m in re.findall(r"/api/[a-zA-Z0-9/_{}-]+", text)
            if not m.startswith(retired_prefix)
        }
        assert named, "the guard must not pass by matching nothing"
        missing = sorted(n for n in named if n not in registered and not n.endswith("/*"))
        # `/api/sharp/` appears as a prefix in prose; allow bare prefixes that
        # are the parent of a real route.
        missing = [
            n for n in missing if not any(r.startswith(n.rstrip("/") + "/") for r in registered)
        ]
        assert missing == [], f"procedures doc names unregistered routes: {missing}"
