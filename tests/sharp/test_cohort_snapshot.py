"""The cohort snapshot must detect the thing it exists to detect.

`sharp-v2.1` shipped with the claim that renormalizing the score leaves
ORDER and cohort membership unchanged, asserted on synthetic records but
never measured against a live population — the dev ledger yields zero
members.  `scripts/sharp_cohort_snapshot.py` is how that debt gets paid
on the box that has the data, so its comparison logic needs to be
trustworthy before anyone runs it there and believes the answer.

The failure mode to guard is a comparison that returns "unchanged" too
easily: it would launder a real cohort shift into a clean bill of health.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "sharp_cohort_snapshot.py"


def _load():
    spec = importlib.util.spec_from_file_location("sharp_cohort_snapshot", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sharp_cohort_snapshot"] = mod
    spec.loader.exec_module(mod)
    return mod


def _snap(ranking, cohort, scores=None):
    return {
        "methodologyVersion": "sharp-v2",
        "population": {
            "records": len(ranking),
            "evaluable": len(ranking),
            "qualified": len(cohort),
            "cohortMembers": len(cohort),
        },
        "ranking": list(ranking),
        "cohort": sorted(cohort),
        "scores": scores or {u: {"score": 100.0 - i} for i, u in enumerate(ranking)},
    }


def test_identical_snapshots_compare_clean():
    mod = _load()
    snap = _snap(["a", "b", "c"], ["a", "b"])
    code, lines = mod.compare(snap, snap)
    assert code == 0
    assert any("order unchanged" in ln for ln in lines)


def test_a_reordering_is_caught():
    mod = _load()
    before = _snap(["a", "b", "c"], ["a", "b"])
    after = _snap(["b", "a", "c"], ["a", "b"])
    code, lines = mod.compare(before, after)
    assert code == 1
    assert any("ORDER CHANGED" in ln for ln in lines)


def test_membership_change_is_caught():
    mod = _load()
    before = _snap(["a", "b", "c"], ["a", "b"])
    after = _snap(["a", "b", "c"], ["a", "c"])
    code, lines = mod.compare(before, after)
    assert code == 1
    assert any("+ c" in ln for ln in lines)
    assert any("- b" in ln for ln in lines)


def test_a_grown_population_is_not_reported_as_a_reorder():
    """New managers appearing must not read as the order moving.

    Comparing the raw ranking lists would flag every population change as
    a reorder, and a check that cries wolf on normal growth is one whose
    real alarm gets ignored.
    """
    mod = _load()
    before = _snap(["a", "b"], ["a"])
    after = _snap(["a", "z", "b"], ["a"])
    code, lines = mod.compare(before, after)
    assert code == 0, [ln for ln in lines if "ORDER" in ln]
    assert any("order unchanged across 2 shared managers" in ln for ln in lines)


def test_uniform_scaling_shows_a_zero_spread():
    """The v2.1 safety argument in one number.

    If every score scales by the same factor the ordering cannot move, so
    a spread at zero is the signature of the argument holding — and a
    wide spread is the signature of it failing, which is what a live run
    is meant to distinguish.
    """
    mod = _load()
    users = ["a", "b", "c"]
    before = _snap(users, ["a"], {u: {"score": s} for u, s in zip(users, [78.0, 60.0, 39.0])})
    after = _snap(
        users,
        ["a"],
        {u: {"score": s * 100 / 78} for u, s in zip(users, [78.0, 60.0, 39.0])},
    )
    code, lines = mod.compare(before, after)
    assert code == 0
    spread_line = next(ln for ln in lines if "spread" in ln and "ratio" in ln)
    assert "spread 0.0000" in spread_line


def _with_weights(users, weights_by_user):
    snap = _snap(users, [users[0]])
    for u in users:
        snap["scores"][u]["weightsApplied"] = weights_by_user[u]
    return snap


_UNIFORM = {"performance": 0.4615, "multiLeagueConsistency": 0.2821, "longevity": 0.1538}


def test_a_uniform_absent_set_proves_the_ordering_claim():
    """One distinct weightsApplied map across the population is the whole
    sharp-v2.1 safety argument: same factor for everyone, so the order —
    and therefore the percentile-selected cohort — cannot have moved."""
    mod = _load()
    users = ["a", "b", "c"]
    snap = _with_weights(users, {u: dict(_UNIFORM) for u in users})
    code, lines = mod.verify_invariant(snap)
    assert code == 0
    assert any("INVARIANT HOLDS" in ln for ln in lines)


def test_a_split_absent_set_fails_loudly():
    """If managers do NOT share one absent set, renormalization scaled
    them by different factors and could have reordered them — which is
    exactly the case the shipped claim assumed away."""
    mod = _load()
    users = ["a", "b", "c"]
    other = {"performance": 0.36, "rosterQuality": 0.22, "multiLeagueConsistency": 0.22}
    snap = _with_weights(users, {"a": dict(_UNIFORM), "b": dict(_UNIFORM), "c": other})
    code, lines = mod.verify_invariant(snap)
    assert code == 1
    assert any("INVARIANT VIOLATED" in ln for ln in lines)
    assert any("distinct weightsApplied maps" in ln and ": 2" in ln for ln in lines)


def test_an_unstamped_manager_is_not_silently_counted_as_agreeing():
    """A missing stamp means the renormalization is unauditable for that
    manager. Treating "no stamp" as "same as everyone else" would let the
    check pass by ignoring the rows it cannot see."""
    mod = _load()
    users = ["a", "b"]
    snap = _with_weights(users, {u: dict(_UNIFORM) for u in users})
    snap["scores"]["b"]["weightsApplied"] = None
    code, lines = mod.verify_invariant(snap)
    assert code == 1
    assert any("no weightsApplied stamp" in ln for ln in lines)


def test_float_noise_does_not_split_an_otherwise_uniform_set():
    """weightsApplied is rounded to 6dp at the source; comparing raw
    floats would report a spurious violation from representation noise
    rather than a real difference in the absent set."""
    mod = _load()
    users = ["a", "b"]
    jittered = {k: v + 1e-12 for k, v in _UNIFORM.items()}
    snap = _with_weights(users, {"a": dict(_UNIFORM), "b": jittered})
    code, _ = mod.verify_invariant(snap)
    assert code == 0


def test_the_no_data_path_is_not_success():
    """`main()` must exit 2, never 0, on an empty population.

    "no data" reading as "verified unchanged" is exactly how an unpaid
    measurement debt gets marked paid — the same reason
    `scripts/backtest_perfect_draft.py` exits 2.
    """
    body = _SCRIPT.read_text(encoding="utf-8")
    assert "return 2" in body
    assert 'evaluable"] == 0' in body
