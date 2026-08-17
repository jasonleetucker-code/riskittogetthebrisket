"""The deploy's own verdict must be about the DEPLOY.

Audit 2026-08-17, batch A.  Three defects in `.github/workflows/deploy.yml`
made the deploy's verdict untrustworthy in both directions, and all three
are cheap to reintroduce, so they are pinned here.

**1. A source-health condition reported as a failed deploy.**
``/api/health`` returns **503** whenever ``is_ok`` is false — and ``is_ok``
requires ``not data_stale`` and ``contractHealth.ok``, so a box that is
merely MID-SCRAPE answers 503 while being perfectly alive.  The readiness
loop broke only on ``200`` and the probe then demanded ``200``, so the
step failed the deploy over source health.  Measured on run 32062696830
(2026-08-17): the remote deploy script had already SUCCEEDED at 20:10:45,
the startup scrape ran 20:10:21→20:14:02, the smoke test ran
20:10:45→20:13:26 entirely inside it, and the job went red.  25 of 27
checks had passed.  That is the CI-lane inversion
``docs/ops/STABILIZATION_2026-08-16.md`` §3d exists to prevent,
reproduced on the deploy side.

**2. Two consecutive steps held opposite policies on one signal.**
``Validate live data contract`` accepts ``degraded`` deliberately
(``if status not in ("ok", "degraded")``), while the smoke step one
position earlier failed on the 503 that *means* degraded — and being
earlier, it won, and the adjudicating step never ran (it reported
``skipped``).

**3. An unset ``PROD_PUBLIC_URL`` silently skipped BOTH verification
steps and the job still reported green** — a gate whose input is missing
reading exactly like a gate that passed, which is the same failure class
as the contract gate that silently skipped for months.

These are assertions about the workflow's *text* because that is where
the policy lives; there is no runtime to interrogate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / ".github" / "workflows" / "deploy.yml"
RELEASE_CANDIDATE = REPO / ".github" / "workflows" / "release-candidate.yml"
PR_VALIDATION = REPO / ".github" / "workflows" / "pr-validation.yml"
SERVER = REPO / "server.py"


@pytest.fixture(scope="module")
def deploy_text() -> str:
    return DEPLOY.read_text(encoding="utf-8")


class TestHealthProbeToleratesDegraded:
    def test_the_server_really_does_answer_503_when_degraded(self):
        """The premise.  If this ever stops being true the tolerance
        below is unnecessary — and this test says so rather than leaving
        a mysterious allowance behind."""
        src = SERVER.read_text(encoding="utf-8")
        assert "status_code=200 if is_ok else 503" in src, (
            "/api/health no longer returns 503 when degraded — re-examine whether the "
            "deploy probe still needs to tolerate it"
        )

    def test_the_readiness_loop_accepts_503(self, deploy_text: str):
        loop = deploy_text.split("Waiting for ${URL}/api/health", 1)
        assert len(loop) == 2, "the /api/health readiness loop is gone"
        window = loop[1][:1200]
        assert '"${_hc}" == "503"' in window, (
            "the readiness loop must accept 503 (degraded) as an ANSWER, or it cannot "
            "distinguish 'still booting' from 'booted and degraded' and will burn its "
            "whole budget on a mid-scrape box"
        )

    def test_the_health_probe_tolerates_200_or_503(self, deploy_text: str):
        assert 'check_endpoint "/api/health" "200|503"' in deploy_text, (
            "the /api/health probe must accept 200 OR 503; a 503 is a source-health "
            "statement adjudicated by the live-contract step, not a deploy failure"
        )

    def test_the_probe_helper_still_anchors_its_match(self, deploy_text: str):
        """The tolerance is a REGEX now, so it must stay anchored —
        otherwise `2000` or `1503` would pass."""
        assert "=~ ^(${expect_code})$" in deploy_text, (
            "check_endpoint's match must stay anchored; an unanchored regex would "
            "accept any code containing the expected one"
        )

    def test_the_auth_gate_probe_is_untouched(self, deploy_text: str):
        """The single most valuable probe in the file: an unauthenticated
        /api/data MUST be 401.  Widening it would expose private data."""
        assert 'check_endpoint "/api/data" 401' in deploy_text
        assert 'check_endpoint "/api/data" "200|401"' not in deploy_text

    def test_the_two_steps_no_longer_disagree(self, deploy_text: str):
        """The live-contract step tolerates `degraded`; the smoke step
        must not contradict it."""
        assert 'status not in ("ok", "degraded")' in deploy_text, (
            "the live-contract adjudicator changed shape — re-check that the smoke "
            "step's tolerance still matches it"
        )


class TestExhaustionIsLoud:
    """A wait loop that gives up silently turns a real condition into an
    unexplained failure 30 lines later."""

    @pytest.mark.parametrize(
        "marker",
        ["title=Health never answered", "title=Public-league snapshot never warmed"],
    )
    def test_loop_exhaustion_emits_a_warning(self, deploy_text: str, marker: str):
        assert marker in deploy_text, f"loop exhaustion must announce itself: {marker}"


class TestVerificationCannotSilentlySkip:
    def test_an_unset_public_url_fails_instead_of_skipping(self, deploy_text: str):
        assert "Assert post-deploy verification will actually run" in deploy_text, (
            "without this guard, an unset PROD_PUBLIC_URL skips BOTH post-deploy "
            "steps and the job reports green having verified nothing"
        )
        assert "title=PROD_PUBLIC_URL is not set" in deploy_text

    def test_the_guard_runs_before_the_deploy_script(self, deploy_text: str):
        """Fail before shipping, not after."""
        guard = deploy_text.index("Assert post-deploy verification will actually run")
        ship = deploy_text.index("- name: Run remote deploy script")
        assert guard < ship, "the guard must run BEFORE the remote deploy script"

    def test_both_verification_steps_are_still_gated_on_the_same_variable(self, deploy_text: str):
        """If they ever diverge, the guard above stops protecting one of
        them."""
        gated = deploy_text.count("if: ${{ vars.PROD_PUBLIC_URL != '' }}")
        assert gated == 2, (
            f"expected exactly 2 steps gated on PROD_PUBLIC_URL, found {gated} — "
            "the assert-guard covers that variable only"
        )


class TestReleaseCandidateReallyMatchesPrValidation:
    """`release-candidate.yml` exists to validate the tree that will
    actually merge, and its header claims it "runs the same gates
    `PR Validation` runs".  The audit measured that claim false by eight
    gates — so the HEAD-FREEZE tree was validated MORE WEAKLY than any
    ordinary PR, which is the exact defect `deploy.yml` records at its own
    head and had already fixed once.
    """

    @pytest.fixture(scope="class")
    def rc(self) -> str:
        return RELEASE_CANDIDATE.read_text(encoding="utf-8")

    @pytest.mark.parametrize(
        "gate,why",
        [
            ("python -m pip check", "a broken dependency graph"),
            ("scripts/check_env.py", "a missing runtime module"),
            ("py_compile", "a syntax error in server.py or the scraper"),
            ("import server", "an import-time failure in the app itself"),
            ("npm test", "every frontend unit test — ~1,390 assertions"),
            ("npm run check:bundles", "a blown bundle budget"),
            ("bash -n", "a broken deploy script"),
        ],
    )
    def test_the_candidate_runs_the_gate(self, rc: str, gate: str, why: str):
        assert gate in rc, (
            f"release-candidate.yml does not run `{gate}` — the merge candidate would "
            f"ship without anyone checking for {why}"
        )

    def test_it_sets_up_node_at_all(self, rc: str):
        assert (
            "actions/setup-node" in rc
        ), "no Node setup means the frontend gates above cannot run even if invoked"

    def test_node_major_matches_pr_validation(self, rc: str):
        pr = PR_VALIDATION.read_text(encoding="utf-8")

        def node_versions(text: str) -> set[str]:
            return set(re.findall(r'node-version:\s*"([^"]+)"', text))

        assert node_versions(rc) == node_versions(pr), (
            "release-candidate and pr-validation must agree on the Node version, or "
            "the candidate is validated on a runtime production never sees"
        )

    def test_the_blocking_hard_gate_is_still_there(self, rc: str):
        assert 'pytest tests/ -x -q --tb=short -m "not livedata"' in rc
