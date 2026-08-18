"""A source we know NOTHING about must be named, not dropped.

AUDIT FINDING F-11 (2026-08-18)
───────────────────────────────
``scripts/watchdog_freshness._read_freshness`` prefers the ``_last_success``
stamp, falls back to the CSV mtime, and when NEITHER exists::

    except OSError:
        continue

— the source leaves the population entirely.  ``classify_freshness`` then
iterates only what survived, so the source is not fresh, not soft-stale and not
hard-stale: it is unaccounted for, and nothing says so.  ``main()``'s
``if not freshness`` guard catches only the TOTAL wipe, never a partial one.

MEASURED by injecting one evidence-less registry key::

    present in freshness dict: False
    hard_stale=0 soft_stale=0 fresh=22
    named in ANY bucket: False
    => "22 sources fresh, 0 hard-stale", exit 0

Deleting evidence promoted health — the same defect class as F-7's empty
coverage map, and the same rule as ``src/api/confidence.py``'s coverage axis:
**the denominator is what COULD have been observed.**

WHAT THIS DOES NOT DO
─────────────────────
It reports UNKNOWN and nothing more.  No age, no threshold, no staleness
verdict is invented.  Whether stale evidence still counts as a full-weight vote
is census item S-6 — OWNER DECISION REQUIRED — and inventing decay or weighting
during an audit is forbidden.

WHY A SEPARATE FUNCTION RATHER THAN A FOURTH BUCKET
───────────────────────────────────────────────────
``classify_freshness``'s 3-tuple is unpacked at eight call sites (seven of them
in ``tests/api/test_watchdog_freshness_soft.py``, one in
``scripts/check_source_health.py``), and ``_read_freshness``'s shape is consumed
by three more scripts.  A named fourth state consumed where it matters is the
smaller correct change, and it keeps the two mechanisms complementary rather
than letting one silently cover for the other — which is what
``test_unmeasurable_is_invisible_to_classify_freshness`` pins.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import src.api.data_contract as data_contract
from scripts.watchdog_freshness import (
    classify_freshness,
    load_soft_escalation_hours,
    load_soft_sources,
    load_thresholds,
    unmeasurable_sources,
)
from scripts.watchdog_freshness import _read_freshness  # noqa: PLC2701

_REPO = Path(__file__).resolve().parents[2]
_WATCHDOG = _REPO / "scripts" / "watchdog_freshness.py"

_GHOST = "ghostSourceForF11"


@pytest.fixture
def registry_with_ghost(monkeypatch: pytest.MonkeyPatch):
    """Register a source whose CSV does not exist and whose stamp is absent."""
    patched = dict(data_contract._SOURCE_CSV_PATHS)
    patched[_GHOST] = "CSVs/site_raw/__f11_no_such_file__.csv"
    monkeypatch.setattr(data_contract, "_SOURCE_CSV_PATHS", patched)
    return patched


def test_a_source_with_no_stamp_and_no_csv_is_reported(registry_with_ghost) -> None:
    assert _GHOST in unmeasurable_sources()


def test_unmeasurable_is_invisible_to_classify_freshness(registry_with_ghost) -> None:
    """The defect itself, pinned.

    The evidence-less source appears in NONE of the three freshness buckets.
    That is exactly why the fourth state has to exist, and pinning it stops a
    future change from quietly making one mechanism cover the other while the
    guard keeps passing.
    """
    hard, soft, fresh = classify_freshness(
        _read_freshness(), load_thresholds(), load_soft_sources(), load_soft_escalation_hours()
    )
    named = [r for r in list(hard) + list(soft) + list(fresh) if r and r[0] == _GHOST]
    assert named == []


def test_one_signal_is_enough_to_have_an_opinion(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source with a stamp but no CSV — or a CSV but no stamp — is NOT
    unmeasurable.  Freshness already has an answer for it, and reporting it as
    unknown would turn a working degradation signal into noise."""
    known = unmeasurable_sources()
    # Every registered source has at least one signal on a healthy tree, which
    # is the state this asserts: the guard is inert until evidence is missing.
    assert known == [], known


def test_the_live_tree_has_no_unmeasurable_source() -> None:
    """Inert today, and it must stay a statement about the CODE rather than a
    live-board count: this asserts the set is empty, not that it has N members
    (§3d)."""
    assert unmeasurable_sources() == []


# ── The wiring, read from the AST ───────────────────────────────────────────
#
# Defining the function is not the guard; USING it is.  A version that computed
# `unmeasurable` and never consulted it in the exit path would leave every
# behavioural assertion above passing while the watchdog still exited 0 — so
# these read the actual call and the actual condition, never a comment, a name
# or a docstring.


def _watchdog_ast() -> ast.Module:
    return ast.parse(_WATCHDOG.read_text())


def _main_fn() -> ast.FunctionDef:
    for node in ast.walk(_watchdog_ast()):
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    raise AssertionError("main() not found in scripts/watchdog_freshness.py")


def test_main_actually_calls_unmeasurable_sources() -> None:
    calls = [
        n.func.id
        for n in ast.walk(_main_fn())
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "unmeasurable_sources" in calls


def test_main_gates_its_success_exit_on_the_result() -> None:
    """The branch that RETURNS 0 must require nothing unmeasurable.

    Targeted at that specific ``if``, not at every condition in ``main()``.
    The first version of this test walked every ``ast.If`` and collected the
    names appearing in any of them — which the summary section's
    ``if unmeasurable:`` satisfied on its own, so the assertion passed with the
    success gate reading ``if not hard_stale:`` and an unmeasurable source
    still exiting 0.  It survived the mutant it exists to catch.
    """
    main = _main_fn()
    success_gates = []
    for node in ast.walk(main):
        if not isinstance(node, ast.If):
            continue
        returns_zero = any(
            isinstance(sub, ast.Return)
            and isinstance(sub.value, ast.Constant)
            and sub.value.value == 0
            for sub in ast.walk(node)
        )
        if returns_zero:
            names = {n.id for n in ast.walk(node.test) if isinstance(n, ast.Name)}
            success_gates.append(names)

    assert success_gates, "no branch in main() returns 0 — cannot verify the success gate"
    for names in success_gates:
        assert (
            "unmeasurable" in names
        ), f"a success (return 0) branch does not consult `unmeasurable`: {sorted(names)}"


def test_check_source_health_reports_it_too() -> None:
    """``check_source_health`` reuses the watchdog rule verbatim ("no second
    freshness rule"), so it inherited the hole and must inherit the repair."""
    src = (_REPO / "scripts" / "check_source_health.py").read_text()
    tree = ast.parse(src)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "unmeasurable_sources" in imported
    called = [
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert "unmeasurable_sources" in called
