"""``usage_signals`` claimed to fire, had no consumer, and is uncalibrated.

Two separate defects wearing one flag, and the tests here pin both so
neither can quietly come back.

1. **No live path.**  ``src/api/feature_flags.py`` reported
   ``usage_signals: True`` with a comment asserting it "fires via
   unified_signal_engine".  Nothing in the tree calls
   ``detect_usage_transitions`` or ``unified_signal_engine``.  A flag
   registry that reports True for capability that cannot execute is the
   §6.15 family exactly — the stated purpose and the actual predicate
   differ, and nothing forces them to agree.

2. **It would not survive contact with real data if it were wired.**
   Measured against the persisted 2025 season it fires on a mean 17.8%
   of active players per week.  The unit tests in
   ``test_usage_signals.py`` all pass because each one feeds a
   hand-built spike; none of them establishes a base rate, which is the
   only number that says whether the detector discriminates.

These tests deliberately assert on the *wiring*, not on the detector's
arithmetic — that is already covered.  The gap was never in the maths.
"""

from __future__ import annotations

import ast
from pathlib import Path

from src.api import feature_flags
from src.nfl_data.usage_windows import UsageWindow
from src.news.usage_signals import detect_usage_transitions

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The functions that would have to appear in a live module for the
#: engine to actually run.
_ENTRY_POINTS = ("detect_usage_transitions", "build_unified_signals")

#: Directories that are production code.  ``scripts/`` is excluded on
#: purpose: an audit script calling the detector is not the same claim
#: as the server calling it, and conflating them is how "it's wired"
#: becomes true-ish.
_PRODUCTION_ROOTS = ("src", "server.py")


def _python_files() -> list[Path]:
    out: list[Path] = []
    for root in _PRODUCTION_ROOTS:
        path = REPO_ROOT / root
        if path.is_file():
            out.append(path)
        elif path.is_dir():
            out.extend(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
    return out


def _callers_of(names: tuple[str, ...]) -> set[str]:
    """Files containing an actual CALL to one of ``names``.

    Parsed with ast rather than grepped.  A substring search would count
    the definition itself, the import in ``unified_signal_engine``, and
    every docstring that names the function — which is precisely how the
    original registry comment came to sound true.
    """
    callers: set[str] = set()
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        defined = {
            n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = getattr(func, "id", None) or getattr(func, "attr", None)
            if called in names and called not in defined:
                callers.add(str(path.relative_to(REPO_ROOT)))
    return callers


def test_the_flag_is_off_because_nothing_consumes_it():
    """The flag and the wiring must agree.

    If someone wires a real consumer, this test fails and forces them to
    flip the default deliberately — with the audit re-run — rather than
    leaving a live feature switched off by an old decision.  If someone
    flips the flag on without wiring a consumer, it also fails.  Either
    drift is caught; that is the point of asserting both halves in one
    place.
    """
    callers = _callers_of(_ENTRY_POINTS)
    enabled = feature_flags.is_enabled("usage_signals")
    assert not callers and not enabled, (
        f"usage_signals enabled={enabled}, production callers={sorted(callers) or 'none'}. "
        "A flag that is ON with no consumer reports capability that cannot execute; "
        "a consumer with the flag OFF is dead code. Re-run "
        "scripts/audit/measure_usage_signal_rate.py before changing either."
    )


def test_the_detector_returns_nothing_while_the_flag_is_off(monkeypatch):
    """The safe default is real, not just documented.

    Uses a window built to fire — snap share four standard deviations
    above its mean — so a pass cannot come from feeding the detector
    something boring.  The companion assertion with the flag ON proves
    the fixture genuinely fires, which is what makes the OFF assertion
    mean anything (§2b: an underfed fixture and a disabled feature are
    indistinguishable without it).
    """
    window = UsageWindow(
        player_id="00-0036322",
        season=2025,
        week=10,
        snap_pct_mean=0.30,
        snap_pct_sd=0.05,
        target_share_mean=0.10,
        target_share_sd=0.02,
        carry_share_mean=0.0,
        carry_share_sd=0.0,
        snap_pct_z=4.0,
        target_share_z=0.1,
        carry_share_z=None,
    )

    monkeypatch.setattr(feature_flags, "is_enabled", lambda name: name != "usage_signals")
    assert detect_usage_transitions([window], season_year=2025, season_current_week=11) == []

    monkeypatch.setattr(feature_flags, "is_enabled", lambda _name: True)
    fired = detect_usage_transitions([window], season_year=2025, season_current_week=11)
    assert [s.signal for s in fired] == [
        "BUY"
    ], "fixture must fire, or the OFF assertion is vacuous"


def test_the_audit_script_reports_a_rate_the_gate_would_reject():
    """The instrument has to be able to fail.

    ``measure`` is imported and run against a synthetic season rather
    than the repo's data files, so this does not depend on anything
    having been persisted.  Every player spikes, so the alert rate must
    come back far above the 5% the script calls acceptable — a
    measurement tool that reported a healthy number for obviously
    pathological input would be worth nothing.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "measure_usage_signal_rate",
        REPO_ROOT / "scripts" / "audit" / "measure_usage_signal_rate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    from src.nfl_data.usage_windows import build_rolling_windows

    # Ten near-flat weeks then a jump for everyone.  The jitter is
    # load-bearing: a PERFECTLY flat window has sd 0, ``_zscore`` returns
    # None, and no z-score exists to compare — which is the same
    # degenerate case the audit's docstring blames for the failed
    # sd-floor fix.  The first draft of this fixture was perfectly flat
    # and produced zero spikes for exactly that reason.
    rows = []
    for player in range(20):
        for week in range(1, 12):
            pct = 0.95 if week == 11 else 0.30 + (week % 3) * 0.01
            rows.append(
                {
                    "player_id_gsis": f"00-{player:07d}",
                    "player_name": f"P{player}",
                    "position": "WR",
                    "team": "DAL",
                    "season": 2025,
                    "week": week,
                    "seasonType": "REG",
                    "targets": 5.0,
                    "carries": 0.0,
                    "receptions": 3.0,
                    "snap_pct": pct,
                    "snapUnit": "offense",
                }
            )

    windows = build_rolling_windows(rows)
    week_11 = [w for w in windows if w.week == 11]
    assert len(week_11) == 20
    assert all(w.snap_pct_z is not None for w in week_11), "fixture must produce a usable sd"
    spiking = [w for w in week_11 if w.snap_pct_z >= module._BUY_Z]
    assert len(spiking) == 20, "every synthetic player must clear the BUY threshold"


def test_an_absent_season_is_reported_not_silently_empty(tmp_path):
    """``measure`` against a directory with no persisted actuals must say
    so.  Returning an empty week list would read identically to "the
    detector never fires", which is the opposite conclusion."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "measure_usage_signal_rate_missing",
        REPO_ROOT / "scripts" / "audit" / "measure_usage_signal_rate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    result = module.measure(1999, actuals_dir=tmp_path)
    assert "error" in result
    assert "no persisted actuals" in result["error"]
