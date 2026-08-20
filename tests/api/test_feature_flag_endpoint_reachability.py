"""A flag's documented ROUTE must be the one its gate actually reaches.

Audit **F-26**: a comment in ``_DEFAULTS`` named ``/api/gameplan`` as the
endpoint ``reception_scoring_fit`` gates. Measured, that was wrong — the
gate reaches only ``/api/valuation/league-adjusted``. The repair (naming
the right endpoint) is correct and already shipped. What was missing is
a test that could have caught the ORIGINAL defect, and Integration
proved by mutation that none of the existing guards do:

* ``tests/api/test_feature_flag_docs_match_registry.py`` /
  ``tests/league_intel/test_flag_docs_match_reality.py`` compare a
  docstring's ON/OFF claim against ``_DEFAULTS`` — never a route name.
* ``tests/api/test_feature_flag_reachability.py`` measures whether a
  flag's gate is reachable from ``server.py`` AT ALL (LIVE / UNREACHABLE
  / SCRIPT_ONLY / NO_GATE) — module-level, not route-specific. A flag
  correctly measured LIVE tells you nothing about which of the app's
  ~100 routes it actually affects.
* A route-existence check (``scripts/verify_lane4_production.py``'s
  ``_registered_routes_static``) would also pass vacuously here:
  ``/api/gameplan`` IS a registered route. The defect was reachability
  FROM THIS FLAG, not existence of the named route anywhere in the app.

This file closes that gap using ``src.api.flag_reachability``, which
resolves flag -> gate call site -> enclosing function -> every function
that calls it, transitively -> any route handler reached along the way.
"""

from __future__ import annotations

from pathlib import Path

from src.api import flag_reachability as fr

REPO_ROOT = Path(__file__).resolve().parents[2]
FEATURE_FLAGS_PATH = REPO_ROOT / "src" / "api" / "feature_flags.py"

#: Flags whose ``_DEFAULTS`` comment makes a bold-marked ``/api/...``
#: claim today. Reused across the positive and mutation tests below so
#: there is exactly one place naming "the relevant flag".
_DOCUMENTED_FLAG = "reception_scoring_fit"
_DOCUMENTED_ROUTE = "/api/valuation/league-adjusted"
_F26_WRONG_ROUTE = "/api/gameplan"


def test_the_documented_endpoint_is_actually_reachable():
    """The positive case: today's comment names a route the gate reaches.

    This is the assertion the original F-26 defect would have failed:
    with the comment naming ``/api/gameplan``, the documented set would
    not be a subset of what the gate structurally reaches, because
    ``/api/gameplan``'s handler (``get_gameplan``) never calls the
    reception-fit resolver at all.
    """
    documented = fr.documented_endpoints(_DOCUMENTED_FLAG)
    assert documented, (
        f"{_DOCUMENTED_FLAG}'s _DEFAULTS comment makes no bold-marked /api/... "
        "claim -- update _DOCUMENTED_FLAG or the comment"
    )
    reachable = fr.reachable_routes_for_flag(_DOCUMENTED_FLAG)
    assert reachable, (
        f"no route is structurally reachable from is_enabled({_DOCUMENTED_FLAG!r}) at all "
        "-- the BFS or the gate scan is broken, not just this flag"
    )
    assert documented.issubset(reachable), (
        f"{_DOCUMENTED_FLAG} documents {sorted(documented)} but the gate only "
        f"structurally reaches {sorted(reachable)}"
    )
    assert _DOCUMENTED_ROUTE in reachable


def test_the_f26_wrong_route_is_not_reachable_from_this_flag():
    """Negative control.

    Proves the guard can actually say NO: if ``reachable_routes_for_flag``
    returned "every route in the app" regardless of the flag, this would
    fail. It doesn't -- ``/api/gameplan``'s handler (``get_gameplan``)
    never touches ``_resolve_reception_fit`` or anything that calls it.
    """
    reachable = fr.reachable_routes_for_flag(_DOCUMENTED_FLAG)
    assert _F26_WRONG_ROUTE not in reachable


def test_reintroducing_the_exact_f26_defect_fails_the_guard():
    """Mutation proof, against the REAL file's actual current text.

    Takes ``src/api/feature_flags.py`` as it exists on disk right now,
    performs the exact edit F-26 reverted (rename the bold-marked
    endpoint claim from ``/api/valuation/league-adjusted`` back to
    ``/api/gameplan``), and re-runs the same extraction against the
    mutated text. The claim must fail the reachability check -- if it
    doesn't, this guard is exactly as vacuous as the ones Integration
    already refuted.
    """
    real_source = FEATURE_FLAGS_PATH.read_text(encoding="utf-8")
    marker = f"**`{_DOCUMENTED_ROUTE}`**"
    assert marker in real_source, (
        "the bold-marked claim this test mutates is no longer present verbatim "
        "in feature_flags.py -- the comment changed shape, update this test"
    )

    mutated_source = real_source.replace(marker, f"**`{_F26_WRONG_ROUTE}`**", 1)
    assert mutated_source != real_source

    documented_after_mutation = fr.documented_endpoints(
        _DOCUMENTED_FLAG, feature_flags_source=mutated_source
    )
    assert documented_after_mutation == {_F26_WRONG_ROUTE}, (
        "the mutation did not change what documented_endpoints() extracts -- "
        f"got {documented_after_mutation}, extraction logic drifted from the marker"
    )

    reachable = fr.reachable_routes_for_flag(_DOCUMENTED_FLAG)  # unaffected by the text mutation
    assert not documented_after_mutation.issubset(reachable), (
        "REGRESSION: reintroducing the exact F-26 defect (claiming "
        f"{_F26_WRONG_ROUTE!r} for {_DOCUMENTED_FLAG!r}) did not fail this guard"
    )


def test_documented_endpoints_prefers_the_bold_marked_claim_over_history():
    """Non-vacuity for the extraction itself.

    The real comment legitimately mentions BOTH endpoints in prose --
    ``/api/gameplan`` as "this line used to name", ``/api/valuation/
    league-adjusted`` as the bold-marked current answer. A naive
    "every /api/... token in the block" extraction would make the
    positive test above fail permanently (the retired route is always
    mentioned), which would make a real operator either delete the
    historical note or ignore a red test. Bold-marking is what lets the
    comment keep its own history AND stay machine-checkable.
    """
    real_source = FEATURE_FLAGS_PATH.read_text(encoding="utf-8")
    assert _F26_WRONG_ROUTE in real_source  # the historical mention is still there
    documented = fr.documented_endpoints(_DOCUMENTED_FLAG, feature_flags_source=real_source)
    assert documented == {_DOCUMENTED_ROUTE}
    assert _F26_WRONG_ROUTE not in documented


def test_reachable_routes_sees_the_run_in_threadpool_indirection():
    """Non-vacuity for the caller graph's over-approximation.

    ``server.py``'s route handler reaches the module-level assembler via
    ``await run_in_threadpool(_gameplan.get_league_adjusted_values, ...)``
    -- the target is a plain argument, never itself a ``Call.func``. A
    caller graph built only from direct call sites would miss this hop
    entirely and report zero reachable routes for a flag that
    demonstrably affects a real endpoint.
    """
    reachable = fr.reachable_routes_for_flag(_DOCUMENTED_FLAG)
    assert reachable, (
        "reachable_routes_for_flag found nothing -- the run_in_threadpool "
        "indirection is invisible again, the exact false negative this guards"
    )
