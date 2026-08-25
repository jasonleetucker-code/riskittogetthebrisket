"""Pin the ``--offline`` mode of ``scripts/verify_roster_intelligence.py``.

``V1_ROSTER_VERIFICATION_PACK.md`` §3's real-board results table ("216
rungs", "215 rung credits", ...) was produced by hand against
``newest_complete_raw_payload()``, and the doc's own documented offline
reproduction command — ``pytest tests/roster_intel/test_verification_pack.py``
— only drives the checks from a synthetic fixture, so it proves the
checks are LIVE, never that they hold on a real board. ``--offline``
closes that gap: a committed, re-runnable command that rebuilds a real
contract from the newest COMPLETE archive and reports EVIDENCE-L2, the
same evidence class the hand-run produced.

Marked ``livedata`` — like ``test_real_rosters.py`` — because it reads a
real archived scrape and is excluded from the blocking hard gate
(``-m "not livedata"``); the check LOGIC itself stays pinned by the
synthetic-fixture suite in ``test_verification_pack.py``, which does run
in the hard gate.
"""

from __future__ import annotations

import pytest

from scripts.verify_roster_intelligence import (
    L1,
    L2,
    PASS,
    UNMEASURABLE,
    build_bundle_offline,
    run_checks,
)
from tests.archive_fixtures import newest_complete_raw_payload

pytestmark = pytest.mark.livedata


def _skip_if_no_archive():
    raw, _ = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available in this environment")


def test_offline_bundle_rebuilds_a_real_board_not_a_synthetic_one():
    _skip_if_no_archive()
    bundle, source = build_bundle_offline("dynasty_main", {"teamCount": 12, "known": True})
    assert source is not None
    assert bundle.intelligence is not None
    assert len(bundle.teams) > 0
    # A synthetic pack fixture in test_verification_pack.py has exactly
    # 12 teams and a handful of members; a real board has hundreds.
    total_members = sum(len((t.get("core") or {}).get("members") or []) for t in bundle.teams)
    assert total_members > 100, "this looks like a synthetic fixture, not a real board"


def test_offline_run_measures_v1_31_and_v1_32_at_evidence_l2():
    _skip_if_no_archive()
    bundle, _ = build_bundle_offline("dynasty_main", {"teamCount": 12, "known": True})
    results = {r.id: r for r in run_checks([bundle], source_level=L2)}

    strength = results["09/dynasty_main"]
    assert strength.result == PASS
    assert strength.level == L2
    assert strength.denominator == 12, "one row per team — Team Strength re-sum (V1-31)"

    weakness_scaling = results["02/dynasty_main"]
    assert weakness_scaling.result == PASS
    # This check's own ceiling is EVIDENCE-L1 (a config-scaling fact) —
    # it does not rise to L2 merely because the run's SOURCE did.
    assert weakness_scaling.level == L1
    assert weakness_scaling.denominator > 0, "must examine real rungs, not 0-of-0"

    weakness_credit = results["10/dynasty_main"]
    assert weakness_credit.result == PASS
    assert weakness_credit.level == L2
    assert weakness_credit.denominator > 0, "must examine real rung credits, not 0-of-0"


def test_offline_run_never_fabricates_team_assignment():
    """check 12 needs the deployed public-league section this archive does
    not carry — it must report UNMEASURABLE, never a fabricated PASS."""
    _skip_if_no_archive()
    bundle, _ = build_bundle_offline("dynasty_main", {"teamCount": 12, "known": True})
    results = {r.id: r for r in run_checks([bundle], source_level=L2)}
    assert results["12/dynasty_main"].result == UNMEASURABLE


def test_offline_run_never_fabricates_endpoint_latency():
    """check 13 polices HTTP round-trip latency against a p95 budget. The
    offline path never makes an HTTP request, so ``bundle.latency_ms``
    must stay empty and this must report UNMEASURABLE — not a fabricated
    PASS built from local contract-rebuild CPU time, which is a
    different quantity than the one this check claims to measure."""
    _skip_if_no_archive()
    bundle, _ = build_bundle_offline("dynasty_main", {"teamCount": 12, "known": True})
    assert bundle.latency_ms == {}, "offline mode must not time local work as endpoint latency"
    results = {r.id: r for r in run_checks([bundle], source_level=L2)}
    assert results["13/dynasty_main"].result == UNMEASURABLE


def test_offline_run_touches_no_network():
    """The offline path must not import the HTTP fetch layer's transport
    call. ``build_bundle_offline`` reaches archive fixtures + the
    contract builder only — never ``fetch_json``."""
    import inspect

    import scripts.verify_roster_intelligence as mod

    src = inspect.getsource(mod.build_bundle_offline)
    assert "fetch_json" not in src
    assert "urllib" not in src
