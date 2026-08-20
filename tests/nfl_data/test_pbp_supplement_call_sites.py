"""#802 — every production caller must actually join the supplement.

The defect this closes was the ORIGINAL defect one level up.
``reception_depth`` had emitted Sleeper's six band keys by name since
2026-07-27 and ``scoring_coverage`` still called them impossible to know,
because nothing joined it. Adding a ``pbp_for_season`` parameter and
threading it through three functions repeats exactly that shape if the
call sites never pass one.

So this is a STATIC test over the AST, not a behavioural one: a
behavioural test can be satisfied by the test supplying its own resolver,
which is what every test in ``test_pbp_supplement_consumers.py`` does.
Only reading the call sites answers the question actually being asked.

A new call site is not automatically wrong — but it has to be declared
here with a reason, so "we forgot" and "we decided not to" stop looking
the same. That is the same posture
``tests/lineup/test_single_owner.py`` takes toward a second lineup fill.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: Functions that take a play-by-play resolver, and the keyword each one
#: names it. A call to any of these without its keyword scores the ten
#: play-by-play rules at nothing.
SUPPLEMENT_AWARE: dict[str, str] = {
    "compute_player_season_scores": "pbp_for_season",
    "realized_ppg_history": "pbp_for_season",
    "build_baseline_records": "pbp_for_season",
    "fetch_and_build_baseline": "pbp_for_season",
    "weekly_points_from_rows": "pbp_stats",
}

#: Call sites that deliberately do NOT join, with the reason. Anything
#: else must pass the keyword.
DECLARED_EXEMPT: dict[str, str] = {
    "scripts/measure_saf_defect.py": (
        "it measures the SAME call shape against two trees — this one and a "
        "worktree at origin/main, which has no supplement to pass. Joining it "
        "here would make the two arms incomparable and turn a before/after "
        "into a before/after-plus-a-new-feature"
    ),
}

#: Files that are the definitions themselves, or test/fixture code.
_SKIP_DIRS = ("tests/", "docs/", ".venv/", "node_modules/")


def _production_files() -> list[Path]:
    out: list[Path] = []
    for base in ("src", "scripts"):
        out.extend((REPO / base).rglob("*.py"))
    out.append(REPO / "server.py")
    return [p for p in out if p.exists()]


def _call_sites() -> list[tuple[str, int, str, bool]]:
    """``(relpath, lineno, func_name, passes_keyword)`` for every call."""
    found: list[tuple[str, int, str, bool]] = []
    for path in _production_files():
        rel = path.relative_to(REPO).as_posix()
        if any(rel.startswith(d) for d in _SKIP_DIRS):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):  # pragma: no cover - unreadable file
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name not in SUPPLEMENT_AWARE:
                continue
            keyword = SUPPLEMENT_AWARE[name]
            passes = any(kw.arg == keyword for kw in node.keywords) or any(
                kw.arg is None
                for kw in node.keywords  # **kwargs passthrough
            )
            found.append((rel, node.lineno, name, passes))
    return found


def test_the_scan_actually_finds_call_sites():
    """A guard that finds nothing passes vacuously. This is the one that
    fails if the AST walk stops matching."""
    sites = _call_sites()
    assert len(sites) >= 6, sites
    assert {name for _f, _l, name, _p in sites} >= {
        "compute_player_season_scores",
        "weekly_points_from_rows",
    }


@pytest.mark.parametrize("site", _call_sites(), ids=lambda s: f"{s[0]}:{s[1]}:{s[2]}")
def test_every_production_call_site_joins_the_play_by_play_supplement(site):
    rel, lineno, name, passes = site
    if rel in DECLARED_EXEMPT:
        pytest.skip(f"declared exempt: {DECLARED_EXEMPT[rel]}")
    assert passes, (
        f"{rel}:{lineno} calls {name}() without "
        f"{SUPPLEMENT_AWARE[name]!r}, so the six reception bands, the three "
        f"player special-teams rules and pass_int_td all score zero there. "
        f"Pass a resolver (src.nfl_data.pbp_weekly.SeasonPbpIndex().for_season), "
        f"or add this file to DECLARED_EXEMPT with the reason."
    )


def test_no_exemption_is_stale():
    """An exemption for a file with no call site asserts nothing.

    Left in place it reads as a reviewed decision about live code, and
    the next person to add a call there inherits a silent pass. Same
    posture as ``check_decision_coercions.py``, which fails on stale
    allowances rather than only on new debt.
    """
    called = {rel for rel, _lineno, _name, _passes in _call_sites()}
    stale = sorted(set(DECLARED_EXEMPT) - called)
    assert not stale, (
        f"DECLARED_EXEMPT names {stale}, which no longer call a "
        f"supplement-aware function — drop the entries"
    )
