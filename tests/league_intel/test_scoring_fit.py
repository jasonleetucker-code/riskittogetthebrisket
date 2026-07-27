"""Tests for the IDP positional scoring-fit measurement (Tier 2).

The measurement exists because this league's rate card inverts the
market's on IDP — it pays coverage and disruption (``idp_pass_def``
2.52x, ``idp_tkl_loss`` 2.06x) and discounts finishing plays
(``idp_sack`` 0.64x) — while every ranking source prices IDP on a
generic card.

**The tests that matter most are the ones that pin what this module
REFUSES to do.** The same data supports a per-player multiplier
arithmetically, and it would be noise: measured p90/p10 among rosterable
IDPs is only ~1.07-1.12 and it grows monotonically with pool depth,
which is the signature of small samples rather than of a real
player-selection edge. So:

* :func:`test_depth_drift_rejects_a_cohort_that_is_only_sampling_noise`
  builds a cohort whose ratio genuinely moves with depth and asserts the
  multiplier is forced to 1.0. Per ORCHESTRATION.md 6.15, a guard that
  cannot fire is not a guard — this one is shown firing.
* :func:`test_a_stable_cohort_is_trusted` is its control. Without it the
  rejection test would pass against a module that rejects everything.

Fixtures are synthetic and hermetic. Nothing here touches Sleeper or
nflverse.
"""

from __future__ import annotations

import pytest

from src.league_intel.adjustment import EvidenceTier, scoring_fit_axis
from src.league_intel.scoring_fit import (
    MAX_DEPTH_DRIFT,
    MIN_COHORT_SIZE,
    measure_positional_scoring_fit,
)

# Two rate cards that differ ONLY on the two keys below, so every ratio
# in these tests is traceable to a deliberate choice rather than to an
# accident of a large settings dict.
_MINE = {"idp_tkl_solo": 1.0, "idp_sack": 2.0}
_BASE = {"idp_tkl_solo": 1.0, "idp_sack": 4.0}


def _week(pid: str, pos: str, week: int, *, solo: float, sacks: float) -> dict:
    return {
        "player_id": pid,
        "player_name": pid,
        "position": pos,
        "season": 2025,
        "week": week,
        "def_tackles_solo": solo,
        "def_tackles_with_assist": 0,
        "def_tackle_assists": 0,
        "def_sacks": sacks,
    }


def _cohort(pos: str, n: int, *, solo: float, sacks: float, weeks: int = 17) -> list[dict]:
    """``n`` players at ``pos``, each with an identical weekly line.

    Identical lines mean the cohort's ratio is exact rather than noisy,
    so a test that asserts a specific multiplier is asserting the
    arithmetic and not a sampling outcome.
    """
    rows: list[dict] = []
    for i in range(n):
        for w in range(1, weeks + 1):
            rows.append(_week(f"{pos}-{i:03d}", pos, w, solo=solo, sacks=sacks))
    return rows


def test_a_stable_cohort_is_trusted():
    """The control for the rejection test below.

    Every DL has the same stat line, so the ratio is identical at every
    pool depth and drift is exactly 0.
    """
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    assert m.measured, m.reason
    dl = m.positions["DL"]
    assert dl.trusted, dl.reason
    assert dl.depth_drift == pytest.approx(0.0, abs=1e-9)


def test_the_tilt_points_the_way_the_rate_cards_do():
    """DL earns sacks, which this card halves; LB earns tackles, which
    it leaves alone. So DL must come out BELOW LB.

    Asserting the direction rather than a magnitude: the magnitude is a
    property of the fixture, the direction is a property of the model.
    """
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    assert m.multiplier_for("DL") < m.multiplier_for("LB")


def test_multipliers_are_mean_normalised_so_idp_is_not_inflated():
    """Only the tilt BETWEEN positions carries information; the shared
    level is an artifact of how generously each commissioner numbered
    their sheet. The measurement must re-allocate, never inflate."""
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    trusted = [f.multiplier for f in m.positions.values() if f.trusted]
    assert trusted
    assert sum(trusted) / len(trusted) == pytest.approx(1.0, abs=1e-9)


def test_depth_drift_rejects_a_cohort_that_is_only_sampling_noise():
    """THE GUARD, shown firing.

    The top 24 LBs are pure tacklers (ratio 1.0 — no sacks, and the
    cards agree on tackles). Everyone below them is a pure sack
    specialist (ratio 0.5). So the cohort's median ratio is 1.0 at
    depth 24 and collapses toward 0.5 as the pool deepens — exactly the
    depth-dependence that says 'this number is measuring sample
    composition, not scoring'.

    A position like that must be refused, not averaged.
    """
    rows = (
        _cohort("LB", 24, solo=10, sacks=0)  # high scorers, ratio 1.0
        + _cohort("LB", 96, solo=0, sacks=2)  # low scorers, ratio 0.5
        + _cohort("DL", 40, solo=3, sacks=1)  # a stable cohort alongside
    )
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    lb = m.positions["LB"]
    assert lb.depth_drift > MAX_DEPTH_DRIFT, (
        f"fixture did not actually drift (drift={lb.depth_drift}); the guard "
        "would pass vacuously"
    )
    assert not lb.trusted
    assert lb.multiplier == 1.0
    assert "sampling artifact" in lb.reason
    # And the untrusted position must not contaminate the normalisation
    # of the one that IS trustworthy.
    assert m.positions["DL"].trusted


def test_an_untrusted_position_is_inert_through_the_axis():
    """The rejection has to survive the trip into the adjustment model,
    not just look right on the measurement object."""
    rows = _cohort("LB", 24, solo=10, sacks=0) + _cohort("LB", 96, solo=0, sacks=2)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    axis = scoring_fit_axis("LB", m)
    assert axis.tier is EvidenceTier.ABSENT
    assert axis.effective_factor == 1.0
    assert not axis.applied


def test_a_trusted_position_reaches_the_axis_with_its_evidence():
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    axis = scoring_fit_axis("DL", m)
    assert axis.tier is EvidenceTier.SCORING_MEASURED
    assert axis.applied
    assert axis.measured_value is not None
    assert "real player-seasons" in axis.rationale


def test_offensive_positions_are_never_tilted():
    """Offence is excluded on purpose. Its real divergence is
    reception-distance banding, which a position-level multiplier cannot
    express — applying one would paper over the actual edge with a
    number that does not represent it."""
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    for pos in ("WR", "RB", "QB", "TE"):
        assert m.multiplier_for(pos) == 1.0
        assert scoring_fit_axis(pos, m).tier is EvidenceTier.ABSENT


def test_unknown_and_empty_positions_are_inert():
    rows = _cohort("DL", 40, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    assert m.multiplier_for("") == 1.0
    assert m.multiplier_for("KICKER") == 1.0
    assert m.multiplier_for(None) == 1.0


def test_a_thin_cohort_is_dropped_rather_than_guessed():
    rows = _cohort("DL", MIN_COHORT_SIZE - 1, solo=3, sacks=1) + _cohort("LB", 40, solo=6, sacks=0)
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    assert "DL" not in m.positions
    assert m.multiplier_for("DL") == 1.0


def test_missing_scoring_settings_is_a_refusal_not_a_crash():
    rows = _cohort("DL", 40, solo=3, sacks=1)
    for mine, base in ((None, _BASE), (_MINE, None), ({}, {})):
        m = measure_positional_scoring_fit(rows, mine, base, season=2025)
        assert not m.measured
        assert m.reason
        assert m.multiplier_for("DL") == 1.0


def test_no_rows_is_a_refusal_not_a_crash():
    m = measure_positional_scoring_fit([], _MINE, _BASE, season=2025)
    assert not m.measured
    assert m.multiplier_for("DL") == 1.0


def test_a_null_measurement_yields_an_absent_axis():
    """The flag-off path. ``_resolve_scoring_fit`` returns None when the
    feature is disabled, and that must be inert rather than an error —
    the axis is still constructed on every board so the guards above
    keep running against it."""
    axis = scoring_fit_axis("DL", None)
    assert axis.tier is EvidenceTier.ABSENT
    assert axis.effective_factor == 1.0


def test_a_lone_trusted_position_expresses_no_tilt():
    """Surprising but correct, so it is pinned.

    With only one trusted cohort there is no *relative* tilt to express
    — the mean it is normalised against is itself — so the multiplier is
    exactly 1.0. That is the honest answer: 'DL scores 1.09x the
    baseline card' says nothing about DL versus LB if LB was refused.

    Someone reading a 1.0 here might reasonably think the measurement
    failed. It did not; it declined to invent a comparison.
    """
    rows = (
        _cohort("DL", 40, solo=3, sacks=1)
        # LB drifts and is refused, leaving DL alone.
        + _cohort("LB", 24, solo=10, sacks=0)
        + _cohort("LB", 96, solo=0, sacks=2)
    )
    m = measure_positional_scoring_fit(rows, _MINE, _BASE, season=2025)
    assert m.positions["DL"].trusted
    assert not m.positions["LB"].trusted
    assert m.multiplier_for("DL") == pytest.approx(1.0)
    # The raw ratio still carries the real measurement, so the evidence
    # is not lost — only the comparison is withheld.
    assert m.positions["DL"].raw_ratio != pytest.approx(1.0)


def test_the_resolver_is_inert_while_the_flag_is_off(monkeypatch):
    """Flag-off must produce None (an ABSENT axis), and must not pay the
    cost of the measurement — it scores ~19k player-weeks twice."""
    from src.api import feature_flags, gameplan

    monkeypatch.setenv("RISKIT_FEATURE_IDP_SCORING_FIT", "0")
    feature_flags.reload()
    gameplan.invalidate_scoring_fit_cache()

    called = []
    monkeypatch.setattr(
        "src.nfl_data.ingest.fetch_weekly_defensive_stats",
        lambda *a, **k: called.append(1) or [],
    )
    try:
        assert gameplan._resolve_scoring_fit("main") is None
        assert called == [], "flag off must not fetch stats"
    finally:
        feature_flags.reload()
        gameplan.invalidate_scoring_fit_cache()


def test_the_flag_defaults_off():
    """Unlike te_basis_conversion, which the operator directed on. This
    moves every IDP value on the board and nobody has asked for it."""
    from src.api import feature_flags

    feature_flags.reload()
    assert feature_flags.is_enabled("idp_scoring_fit") is False
