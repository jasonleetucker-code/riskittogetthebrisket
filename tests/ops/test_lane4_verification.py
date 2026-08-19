"""The verifier's own semantics.

A verification script is only worth what its vocabulary is worth. These pin
the three distinctions the package exists to preserve, because each of them
is a way a run could quietly read as green when it proved nothing:

* a 401 is INSUFFICIENT EVIDENCE, not a pass and not a failure;
* a missing input is BLOCKED, not a pass;
* an input that exists but does not contain the case under test is
  INAPPLICABLE, not a pass.

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
        report.add(verify.Check("Y", "V1-58", "t", verify.BLOCKED, ""))
        assert report.exit_code() == 0

    def test_the_three_non_proving_statuses_are_counted_apart_from_passes(self):
        report = _report()
        for status in (verify.INAPPLICABLE, verify.BLOCKED, verify.UNVERIFIABLE):
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
        assert report.checks[0].status == verify.INAPPLICABLE

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
