"""Tests for the reception-depth value tilt.

The single most important thing these pin is the MAGNITUDE, because the
headline number for this feature is misleading by an order of magnitude
if quoted alone. The per-catch spread really is 8x (0.25 to 2.00) and
``docs/ORCHESTRATION.md`` calls it "the largest unexploited edge
identified to date" — but receptions are only 17-33% of a player's
points, so the composed VALUE tilt lands near ±8%.

``test_composition_shrinks_the_per_catch_ratio_toward_one`` exists so
that anyone who later "simplifies" the composition away — applying the
per-catch ratio directly to player value — fails loudly instead of
shipping a 2x repricing.

The other load-bearing test is the dispersion-stability guard, shown
firing. It is the same standard :mod:`src.league_intel.scoring_fit`
applies, and it is what distinguishes this measurement (flat across
depth, kept) from the IDP per-player one (fans out, refused).
"""

from __future__ import annotations

import pytest

from src.league_intel.reception_fit import (
    MAX_TILT,
    MIN_RECEPTIONS,
    measure_reception_depth_fit,
    reception_scoring_keys,
)

# The real cards, reduced to the keys that matter here.
_MINE = {
    "rec": 0.08,
    "rec_0_4": 0.17,
    "rec_5_9": 0.42,
    "rec_10_19": 0.67,
    "rec_20_29": 0.92,
    "rec_30_39": 1.17,
    "rec_40p": 1.92,
}
_BASE = {"rec": 0.75}


def _payload(players: dict) -> dict:
    return {"season": 2025, "players": players}


def _player(name: str, bands: dict) -> dict:
    return {"name": name, "bands": bands, "receptions": sum(bands.values())}


def _uniform(n_players: int, bands: dict, share: float, prefix: str = "p"):
    """``n_players`` identical receivers — an exact, noise-free cohort."""
    players = {f"{prefix}{i:03d}": _player(f"{prefix}{i}", dict(bands)) for i in range(n_players)}
    shares = {f"{prefix}{i:03d}": share for i in range(n_players)}
    return players, shares


# ── Magnitude: the thing most likely to be misquoted ─────────────────


def test_composition_shrinks_the_per_catch_ratio_toward_one():
    """A deep threat's catches are worth ~2.4x here, but if only a fifth
    of his points come from receptions his VALUE moves ~28%, not 140%.

    Applying the per-catch ratio straight to player value is the error
    this test exists to prevent.
    """
    bands = {"rec_40p": 30, "rec_30_39": 10}  # all long
    # Share deliberately below the level at which MAX_TILT would bind,
    # so this test measures the COMPOSITION and not the clamp — the
    # clamp has its own test and a fixture that hit both would not
    # distinguish them.
    share = 0.15
    players, shares = _uniform(20, bands, share=share)
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert m.measured and m.trusted

    gid = "p000"
    per_catch = m.per_catch_ratios[gid]
    multiplier = m.multipliers[gid]
    assert per_catch > 2.0, "fixture is not actually a deep-threat shape"
    assert multiplier < 1.0 + MAX_TILT, "fixture hit the clamp; it is testing the wrong thing"
    # Exactly where the composition puts it, and far below the per-catch
    # ratio it came from.
    assert multiplier == pytest.approx(1.0 + share * (per_catch - 1.0))
    # The claim stated as a shrinkage: the value moves by the SHARE of
    # the per-catch move, so a 142% per-catch premium becomes a 21%
    # value premium. Asserting the deviations rather than the raw
    # numbers is what makes this about composition.
    assert (multiplier - 1.0) == pytest.approx(share * (per_catch - 1.0))
    assert (multiplier - 1.0) < 0.25 * (per_catch - 1.0)


def test_a_zero_reception_share_is_a_no_op_however_extreme_the_shape():
    """A player who scores nothing from catches cannot be repriced by a
    reception rule, no matter how lopsided his band shape is."""
    players, shares = _uniform(20, {"rec_40p": 40}, share=0.0)
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert m.multipliers["p000"] == pytest.approx(1.0)


def test_the_direction_matches_the_band_the_catches_fall_in():
    short, short_shares = _uniform(15, {"rec_0_4": 40}, share=0.30, prefix="s")
    deep, deep_shares = _uniform(15, {"rec_40p": 40}, share=0.30, prefix="d")
    players = {**short, **deep}
    shares = {**short_shares, **deep_shares}
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert m.multipliers["s000"] < 1.0 < m.multipliers["d000"]


# ── Guards ───────────────────────────────────────────────────────────


def test_the_tilt_is_clamped(monkeypatch):
    """An upstream data fault must not be able to express itself as a
    3x repricing. The clamp is a backstop, not a shaper — on real 2025
    data exactly one of 200 receivers reaches it."""
    players, shares = _uniform(20, {"rec_40p": 40}, share=1.0)
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert m.multipliers["p000"] == pytest.approx(1.0 + MAX_TILT)


def test_players_below_the_reception_floor_are_excluded():
    """A handful of catches describes noise, not a shape."""
    thin = {"p000": _player("Thin", {"rec_40p": MIN_RECEPTIONS - 1})}
    m = measure_reception_depth_fit(_payload(thin), {"p000": 0.3}, _MINE, _BASE, season=2025)
    assert "p000" not in m.multipliers


def test_a_player_with_no_scored_season_is_skipped_not_guessed():
    """The per-catch ratio is knowable from the histogram alone, but its
    WEIGHT is not. Inventing a reception share would invent the entire
    magnitude of the adjustment."""
    players, shares = _uniform(20, {"rec_40p": 40}, share=0.3)
    shares.pop("p000")
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert "p000" not in m.multipliers
    assert m.multiplier_for("p000") == 1.0


def test_dispersion_drift_rejects_the_whole_measurement():
    """THE GUARD, shown firing.

    High-volume receivers are uniform (dispersion ~1.0); the low-volume
    tail is split between extremes, so dispersion widens sharply as the
    pool deepens. That pattern says the number is describing sample
    composition, and no individual multiplier from it is trustworthy —
    so the refusal is total rather than per player.
    """
    top, top_sh = _uniform(24, {"rec_10_19": 40}, share=0.30, prefix="t")
    lo_a, lo_a_sh = _uniform(60, {"rec_40p": 25}, share=0.60, prefix="a")
    lo_b, lo_b_sh = _uniform(60, {"rec_0_4": 25}, share=0.60, prefix="b")
    players = {**top, **lo_a, **lo_b}
    shares = {**top_sh, **lo_a_sh, **lo_b_sh}
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)

    assert m.measured
    assert m.dispersion_drift > 0.12, (
        f"fixture did not actually drift (drift={m.dispersion_drift}); "
        "the guard would pass vacuously"
    )
    assert not m.trusted
    assert "sample composition" in m.reason
    # Untrusted means EVERY lookup is inert, including the ones whose
    # own numbers looked fine.
    assert m.multiplier_for("t000") == 1.0
    assert m.multiplier_for("a000") == 1.0


def test_a_stable_measurement_is_trusted():
    """Control for the test above: without it, the rejection test would
    pass against a module that rejects everything."""
    players, shares = _uniform(80, {"rec_10_19": 30, "rec_40p": 10}, share=0.30)
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert m.trusted, m.reason


# ── Refusals ─────────────────────────────────────────────────────────


def test_missing_inputs_refuse_rather_than_crash():
    players, shares = _uniform(20, {"rec_10_19": 40}, share=0.3)
    for depth, sh, mine, base in (
        (None, shares, _MINE, _BASE),
        (_payload(players), shares, None, _BASE),
        (_payload(players), shares, _MINE, None),
    ):
        m = measure_reception_depth_fit(depth, sh, mine, base, season=2025)
        assert not m.measured
        assert m.reason
        assert m.multiplier_for("p000") == 1.0


def test_a_tiny_sample_is_not_a_measurement():
    players, shares = _uniform(5, {"rec_10_19": 40}, share=0.3)
    m = measure_reception_depth_fit(_payload(players), shares, _MINE, _BASE, season=2025)
    assert not m.trusted
    assert m.multiplier_for("p000") == 1.0


def test_reception_keys_cover_the_flat_and_banded_forms():
    """The share computation zeroes these to isolate the reception
    component. Missing ``rec`` would leave the flat portion in the
    remainder and understate every share."""
    keys = reception_scoring_keys()
    assert "rec" in keys
    assert "rec_0_4" in keys and "rec_40p" in keys


# ── The axis: wired, not staged ──────────────────────────────────────
#
# ORCHESTRATION.md 6.14/6.15: a module nothing imports cannot be caught
# by the guards written for it. The axis is constructed on every board
# and yields ABSENT when there is no measurement, so the flag-off path
# still exercises this code.


def test_a_measured_player_reaches_the_axis_with_its_evidence():
    from src.league_intel.adjustment import EvidenceTier, reception_fit_axis

    axis = reception_fit_axis("Alec Pierce", "WR", {"alec pierce": 1.048})
    assert axis.tier is EvidenceTier.SCORING_MEASURED
    assert axis.applied
    assert axis.factor == pytest.approx(1.048)
    # The rationale must state the composition, because "1.048x" alone
    # invites someone to think it came from the per-catch ratio.
    assert "per_catch_ratio" in axis.rationale


def test_an_unmeasured_player_is_inert():
    from src.league_intel.adjustment import EvidenceTier, reception_fit_axis

    axis = reception_fit_axis("Nobody At All", "WR", {"alec pierce": 1.048})
    assert axis.tier is EvidenceTier.ABSENT
    assert axis.effective_factor == 1.0


def test_no_measurement_at_all_is_inert():
    """The flag-off path. `_resolve_reception_fit` returns None, and the
    axis is still constructed so the guards keep running against it."""
    from src.league_intel.adjustment import EvidenceTier, reception_fit_axis

    axis = reception_fit_axis("Alec Pierce", "WR", None)
    assert axis.tier is EvidenceTier.ABSENT
    assert axis.effective_factor == 1.0


def test_the_axis_joins_on_the_canonical_name_not_the_raw_string():
    """Contract rows and stat rows spell names differently — suffixes,
    apostrophes, accents. Joining on the raw string would silently drop
    exactly the players whose names are hardest to spell."""
    from src.league_intel.adjustment import reception_fit_axis
    from src.utils.name_clean import resolve_canonical_name

    key = resolve_canonical_name("Ja'Marr Chase")
    axis = reception_fit_axis("JaMarr Chase Jr.", "WR", {key: 0.93})
    assert axis.factor == pytest.approx(0.93)


def test_the_board_applies_the_per_player_tilt():
    """End to end through build_board_adjustments — the wiring, not just
    the axis function."""
    from src.league_intel.adjustment import build_board_adjustments

    rows = [
        {"displayName": "Deep Threat", "position": "WR", "rankDerivedValue": 5000},
        {"displayName": "Check Down", "position": "RB", "rankDerivedValue": 5000},
    ]
    board = build_board_adjustments(rows, reception_fit={"deep threat": 1.05, "check down": 0.90})
    by_name = {e.display_name: e for e in board.explanations}
    assert by_name["Deep Threat"].league_adjusted_value > 5000
    assert by_name["Check Down"].league_adjusted_value < 5000


def test_the_board_is_unchanged_without_a_measurement():
    """Flag-off must be arithmetically identical to the board before
    this feature existed."""
    from src.league_intel.adjustment import build_board_adjustments

    rows = [{"displayName": "Deep Threat", "position": "WR", "rankDerivedValue": 5000}]
    plain = build_board_adjustments(rows)
    with_none = build_board_adjustments(rows, reception_fit=None)
    assert (
        plain.explanations[0].league_adjusted_value
        == with_none.explanations[0].league_adjusted_value
    )
    assert with_none.explanations[0].league_adjusted_value == pytest.approx(5000)


def test_the_reception_flag_is_separate_from_the_idp_one(monkeypatch):
    """Sharing ``idp_scoring_fit`` would make its name a lie: an operator
    disabling the IDP feature would silently also disable every receiver
    adjustment.

    This used to assert both flags were ``False``, which passed for the
    wrong reason — they merely happened to share a default. When
    ``idp_scoring_fit`` was enabled on 2026-07-27 the test failed, having
    caught a deliberate change rather than a regression.

    Independence is the actual invariant, so that is what is asserted
    now: two distinct keys, and moving one must not move the other. The
    defaults are free to diverge, and today they do.
    """
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_IDP_SCORING_FIT", "1")
    monkeypatch.setenv("RISKIT_FEATURE_RECEPTION_SCORING_FIT", "0")
    feature_flags.reload()
    assert feature_flags.is_enabled("idp_scoring_fit") is True
    assert feature_flags.is_enabled("reception_scoring_fit") is False

    # And the other way round, so the test cannot pass by both being
    # wired to the same underlying switch in either direction.
    monkeypatch.setenv("RISKIT_FEATURE_IDP_SCORING_FIT", "0")
    monkeypatch.setenv("RISKIT_FEATURE_RECEPTION_SCORING_FIT", "1")
    feature_flags.reload()
    assert feature_flags.is_enabled("idp_scoring_fit") is False
    assert feature_flags.is_enabled("reception_scoring_fit") is True


def test_the_resolver_is_inert_while_the_reception_flag_is_off(monkeypatch):
    from src.api import feature_flags, gameplan

    monkeypatch.setenv("RISKIT_FEATURE_RECEPTION_SCORING_FIT", "0")
    feature_flags.reload()
    gameplan.invalidate_reception_fit_cache()
    called = []
    monkeypatch.setattr(
        "src.nfl_data.ingest.fetch_weekly_stats", lambda *a, **k: called.append(1) or []
    )
    try:
        assert gameplan._resolve_reception_fit("main") is None
        assert called == [], "flag off must not fetch stats"
    finally:
        feature_flags.reload()
        gameplan.invalidate_reception_fit_cache()
