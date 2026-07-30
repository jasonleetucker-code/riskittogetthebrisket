"""Tripwire on the eight percentile-form master Hill constants.

2026-07-30, audit debt D16.

WHY THIS IS NEEDED WHEN THE MODEL REGISTRY ALREADY EXISTS
=========================================================
The registry governs how a challenger BECOMES a champion: fit → score
against held-out boards → record → a human runs
``scripts/model_registry.py promote`` + ``apply``.  That machinery is
sound and ADR-008 (``docs/roster-trade-intelligence/DECISIONS.md``) is
why it exists.

What it does not do is tell anyone what ELSE has to move when the
constants change.  ``apply`` rewrites
``src/canonical/player_valuation.py`` and stops.  Deliberately — the
whole point of ADR-008 is that the refit path must not rewrite its own
guards.  But the consequence is that every downstream expectation goes
stale silently, and one of them did:

``tests/canonical/test_ktc_reconciliation.py`` — the only test that
pinned what these constants produce — had **all 10 of its cases failing
on `main`** as of 2026-07-30.  Its pins were baselined 2026-04-20;
``HILL_PERCENTILE_C/S`` were promoted since.  Nobody saw it because
``tests/conftest.py`` auto-marks that module ``livedata``, so CI runs it
``continue-on-error``.

So the guard existed, was failing, and was invisible.  That is ADR-008's
third failure mode ("the guard is not even run") returning by a different
route: the old refit made the guard unfalsifiable by rewriting it, and
removing that rewrite left it merely unmaintained.

WHY A SEPARATE MODULE RATHER THAN FIXING THAT ONE
=================================================
Two constraints, both already pinned by
``tests/model_registry/test_refit_path_characterisation.py``:

* ``test_ktc_reconciliation.py`` must STAY ``livedata``-marked
  (``TestTheLivedataMarkingIsPreserved``).  Un-marking it re-introduces
  the PR-stalling failures the marking was added to prevent — a KTC
  row-count dip once blocked every open PR.
* It must keep both of its assertions
  (``test_the_guard_still_has_real_assertions_to_make``).

Both are right.  A test that reads ``CSVs/site_raw/ktc.csv`` cannot be a
blocking gate, so drift in these constants was always going to be
invisible in the hard tier without a check that reads no live data at
all.  This is that check: deterministic, hard-gating, and it names the
other places to update when it fires.

Same shape as ``test_rank_form_constants_tripwire.py`` — deliberately a
dumb equality assertion.  Every other test imports these symbolically
(right, so a legitimate promotion does not break them) and that is
exactly why none of them notices a change.
"""

from __future__ import annotations

from src.canonical.player_valuation import (
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    HILL_ROOKIE_PERCENTILE_C,
    HILL_ROOKIE_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
    percentile_to_value,
)

# Promoted values as of 2026-07-30.  These are the LIVE board's step-3
# curve constants — the single most load-bearing numbers in the repo.
_PINNED = {
    "HILL_GLOBAL_PERCENTILE_C": 0.1120,
    "HILL_GLOBAL_PERCENTILE_S": 0.725,
    "HILL_PERCENTILE_C": 0.1100,
    "HILL_PERCENTILE_S": 1.110,
    "IDP_HILL_PERCENTILE_C": 0.0830,
    "IDP_HILL_PERCENTILE_S": 1.110,
    "HILL_ROOKIE_PERCENTILE_C": 0.1530,
    "HILL_ROOKIE_PERCENTILE_S": 0.885,
}

# What the OFFENSE master produces at key ranks, at the live reference N.
# Pinned separately from the constants because this is the number users
# actually see, and because it catches a change to the FORMULA or to
# ``_PERCENTILE_REFERENCE_N`` that leaves the constants untouched.
_PINNED_OFFENSE_VALUES = {
    1: 9999,
    5: 9481,
    12: 8561,
    24: 7242,
    50: 5314,
    100: 3419,
    150: 2481,
    200: 1931,
    300: 1322,
    400: 996,
}

_GUIDANCE = """
The percentile-form master Hill constants changed.

If this is a PROMOTION (scripts/model_registry.py promote + apply), it is
expected — and there are FOUR follow-ups, which is the whole reason this
tripwire exists.  ``apply`` does none of them, by design: ADR-008
prohibits the refit path from rewriting its own guards.

  1. Update _PINNED and _PINNED_OFFENSE_VALUES in this file.

  2. Re-baseline PINNED_DELTAS in
     tests/canonical/test_ktc_reconciliation.py.  Both columns move: the
     exact ``ours`` value AND the pct-diff band centre.  That file is
     livedata-marked so it will NOT fail your PR — it will just go
     quietly stale, which is precisely what happened between 2026-04-20
     and 2026-07-30 (all 10 cases red on main, unnoticed).

  3. Re-run the rank-form drift check.  A promotion reshapes the board's
     rank->value relation, so the reconstruction curves go stale too:
         python scripts/check_rank_form_drift.py --verbose
     Measured precedent: the 2026-07-29 pre-promotion board refit to
     68.8/0.929, the post-promotion board to 65.2/0.905.  If it reports
     drift, follow its output (and remember the frontend mirror in
     frontend/lib/value-history.js).

  4. Record the promotion in config/model_registry/ if the registry CLI
     did not already.

If this is NOT a promotion: revert it.  These constants determine every
displayed value on the board, and nothing should be hand-editing them —
the refit driver cannot write files (pinned by
tests/model_registry/test_refit_path_characterisation.py).
"""


def test_percentile_constants_are_unchanged():
    actual = {
        "HILL_GLOBAL_PERCENTILE_C": HILL_GLOBAL_PERCENTILE_C,
        "HILL_GLOBAL_PERCENTILE_S": HILL_GLOBAL_PERCENTILE_S,
        "HILL_PERCENTILE_C": HILL_PERCENTILE_C,
        "HILL_PERCENTILE_S": HILL_PERCENTILE_S,
        "IDP_HILL_PERCENTILE_C": IDP_HILL_PERCENTILE_C,
        "IDP_HILL_PERCENTILE_S": IDP_HILL_PERCENTILE_S,
        "HILL_ROOKIE_PERCENTILE_C": HILL_ROOKIE_PERCENTILE_C,
        "HILL_ROOKIE_PERCENTILE_S": HILL_ROOKIE_PERCENTILE_S,
    }
    drifted = {k: (v, actual[k]) for k, v in _PINNED.items() if actual[k] != v}
    assert not drifted, f"{_GUIDANCE}\nChanged (pinned -> actual): " + ", ".join(
        f"{k}: {was} -> {now}" for k, (was, now) in sorted(drifted.items())
    )


def test_the_offense_curve_still_produces_the_pinned_values():
    """Catches a formula or reference-N change the constants would miss."""
    from src.api.data_contract import _PERCENTILE_REFERENCE_N

    denom = max(1, _PERCENTILE_REFERENCE_N - 1)
    drifted = []
    for rank, expected in _PINNED_OFFENSE_VALUES.items():
        actual = int(percentile_to_value((rank - 1) / denom))
        if actual != expected:
            drifted.append(f"rank {rank}: {expected} -> {actual}")
    assert not drifted, f"{_GUIDANCE}\nChanged: " + ", ".join(drifted)


def test_the_committed_source_matches_the_imported_values():
    """The registry reads these constants by REGEX out of the source file
    (``hill_masters.read_committed_constants``), and ``apply`` writes them
    the same way.  If the regex and the Python parser ever disagree — a
    duplicated assignment, a value written as ``1.11e0``, a constant moved
    behind a conditional — the registry would report and promote numbers
    the engine does not use.  Nothing else checks that they agree.
    """
    from src.model_registry.hill_masters import read_committed_constants

    committed = read_committed_constants()
    for name, pinned in _PINNED.items():
        assert name in committed, f"{name} is no longer regex-readable by the registry"
        assert committed[name] == pinned, (
            f"registry reads {name}={committed[name]} but the module imports {pinned} — "
            "the regex in hill_masters.py and the Python value have diverged"
        )


def test_the_livedata_guard_is_pinned_to_the_same_numbers():
    """The link that was missing, made mechanical.

    ``test_ktc_reconciliation.py``'s ``PINNED_DELTAS`` holds the same
    curve values this file pins.  Because that module is
    ``livedata``-marked it cannot block a PR, so its staleness has to be
    detectable from the hard tier — otherwise the next promotion repeats
    2026-04-20 → 07-30 exactly.

    Parses rather than imports: importing the module would execute its
    module-level KTC CSV load, coupling this hard gate to a live file.
    """
    import re
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[2] / "tests" / "canonical" / "test_ktc_reconciliation.py"
    )
    text = path.read_text(encoding="utf-8")
    # Anchor on the ASSIGNMENT, not the first mention of the name: that
    # file's docstring and comments talk about ``PINNED_DELTAS`` several
    # times before defining it, and a naive ``split`` lands in prose and
    # silently parses nothing.
    match = re.search(
        r"^PINNED_DELTAS[^=]*=\s*\[(?P<body>.*?)^\]",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match, f"could not locate the PINNED_DELTAS assignment in {path.name}"
    pinned_there = {
        int(rank): int(ours)
        for rank, ours in re.findall(r"\(\s*(\d+)\s*,\s*(\d+)\s*,", match.group("body"))
    }
    assert pinned_there, f"could not parse PINNED_DELTAS out of {path.name}"

    stale = {
        rank: (pinned_there[rank], expected)
        for rank, expected in _PINNED_OFFENSE_VALUES.items()
        if rank in pinned_there and pinned_there[rank] != expected
    }
    assert not stale, (
        "test_ktc_reconciliation.py::PINNED_DELTAS is stale — it is "
        "livedata-marked so it will not fail your PR on its own. Re-baseline "
        "it (see step 2 of the guidance in this module). Stale ranks "
        "(theirs -> should be): "
        + ", ".join(f"{r}: {t} -> {e}" for r, (t, e) in sorted(stale.items()))
    )
