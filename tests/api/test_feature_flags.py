"""Tests for the feature-flag registry.

These pin the two core guarantees:

1. Every flag has an explicit default.  Unknown flag reads raise.
2. Env-var override works, and reload() picks up mid-run changes.
"""

from __future__ import annotations

import pytest

from src.api import feature_flags


@pytest.fixture(autouse=True)
def _reset_cache():
    feature_flags.reload()
    yield
    feature_flags.reload()


def test_every_flag_defaults_off_except_safe_additive():
    """Safety guarantee: every default-ON flag has been explicitly
    vetted as safe in production.  Adding a flag to this allowlist
    requires matching rationale in _DEFAULTS (see src/api/feature_flags.py).

    When flipping a flag default ON in _DEFAULTS, ADD IT HERE so
    the test continues to pin the intent.
    """
    flags = feature_flags.snapshot()
    # The vetted-safe-ON set — each one has explanatory comments in
    # _DEFAULTS explaining why it's safe + how to flip it off via
    # RISKIT_FEATURE_<NAME>=0 if needed.
    safe_on = {
        "unified_id_mapper",  # no behavior change, read API only
        "nfl_data_ingest",  # guarded import; empty [] if missing
        "realized_points_api",  # endpoint-only, inert until called
        "value_confidence_intervals",  # additive valueBand field
        "positional_tiers",  # additive tierId field
        "usage_signals",  # freshness + starter-guarded
        "espn_injury_feed",  # circuit-breaker protected
        "depth_chart_validation",  # circuit-breaker protected
        "monte_carlo_trade",  # new endpoint, old unchanged
        # BDVM.  ON since 2026-07-28, and ADDITIVE in the strict sense
        # this set requires: it computes a SECOND value concept beside
        # the market board and never writes rankDerivedValue or touches
        # any existing route.  Turning it on cannot move a number that
        # was already on screen.
        #
        # What it adds: the /bdvm page, /api/bdvm/{values,roster,trades},
        # a "Fund gap" column on /rankings, and a leg on the daily
        # signal sweep.  Each degrades to nothing rather than to
        # something wrong — the column gates on status == "ok" so it
        # self-suppresses without a snapshot, and the alert leg seeds a
        # silent baseline per (user, league) so flag-on day cannot
        # flood.  Rollback: RISKIT_FEATURE_BDVM_ENGINE=0 + restart.
        "bdvm_engine",
        # Perfect Draft.  ON at introduction, and additive in the strict
        # sense this set requires: the engine writes no value, mutates no
        # contract, and adds only one new route plus one new panel on
        # /draft.  Turning it on cannot move a number that was already on
        # screen — the panel silently vanishes on any non-ok response, so
        # a box that cannot serve it renders the board exactly as before.
        #
        # Note what the flag does NOT gate: the removal of the fixed-slot
        # model from frontend/lib/draft-logic.js.  That was an
        # unconditional correction to a wrong assumption (this league caps
        # nobody's rookie count) and it DOES move MaxBid numbers — see
        # ADR-009 in docs/roster-trade-intelligence/DECISIONS.md.  It is
        # not flag-controlled because a flag would preserve a known-wrong
        # model as a live code path.
        # Rollback: RISKIT_FEATURE_PERFECT_DRAFT=0 + restart.
        "perfect_draft",
        # Consensus Edge.  ON since 2026-08-04, and ADDITIVE in this
        # set's strict sense — verified rather than argued:
        #
        #   * the flag gates exactly ONE thing, the
        #     ``/api/consensus-edge/*`` router mounted in server.py.
        #     Nothing else in the codebase reads it.
        #   * it never writes ``rankDerivedValue`` — the package
        #     contains no assignment to it at all.
        #   * it reads ``latest_contract_data`` and never mutates it.
        #   * unlike bdvm_engine it adds NO leg to the daily signal
        #     sweep and NO column to /rankings.  Its frontend surface is
        #     the /consensus-edge page, its own bridge routes, its own
        #     hook and lib, plus one nav entry.
        #
        # So turning it on cannot move a number that was already on
        # screen; it adds a page and some endpoints.
        #
        # Held OFF earlier the same day while the composite rested on
        # one measured component and two declared priors.  What changed
        # is evidence, not patience: Opportunity was backtested and
        # returned a null so its weight is zero (ADR-013), and the
        # artifact users actually read — a list of twenty names — was
        # scored for the first time.  The top-20 buy list returns a
        # median +3.59% cohort-excess over 7 non-overlapping folds
        # (+1.51% over 15 at a 7-day horizon), beating a random-20 draw
        # from the same priced universe in 6 of 7 and 11 of 15;
        # ``Strong Buy`` returns +8.83% at 6 of 6 folds.
        #
        # What is still NOT claimed rides on every payload rather than
        # on this comment: ``experimental: true``, an entirely offseason
        # panel, market movement rather than fantasy points, and a sell
        # side with NO measured edge (0 of 7 folds), which
        # ``sellSideValidation`` states and the sells view renders.
        # Rollback: RISKIT_FEATURE_CONSENSUS_EDGE=0 + restart.
        "consensus_edge",
    }
    # Flags that default ON and KNOWINGLY change output.  Deliberately a
    # separate set from ``safe_on``: every member of that one is there
    # because it is additive, inert, or otherwise cannot move a number,
    # and quietly admitting a value-moving flag would erode the only
    # thing the set's name promises.  Entry here requires a MEASURED
    # blast radius recorded at the point of change, not an argument that
    # the change is probably fine.
    value_moving_on = {
        # Collaborative audit finding F.  Replaces the flat 1.15 TE
        # alignment multiplier with KTC's measured base → TE++ curve.
        # Blast radius measured against the 2026-07-27 live board (810
        # rows): all 80 TEs move up, +1.08% (Bowers, against the 9999
        # ceiling) to +30.17% (Ruckert, deep), median +14.27%.  The only
        # non-TE values that move are 48 PICK rows, via the documented
        # current-year pick tethering inheriting rookie-TE values —
        # e.g. 2026 Pick 1.07 +3.91% matches Kenyon Sadiq exactly.  No
        # QB/RB/WR/IDP value changes.  Rank displacement median 7, p90
        # 22.  Rollback: RISKIT_FEATURE_TE_BASIS_CONVERSION=0.
        "te_basis_conversion",
        # IDP positional scoring fit.  Blast radius RE-measured against
        # the 2026-07-28 live board (1,094 rows) on the complete scoring
        # card:
        #
        #   398 IDP rows move — DL n=145 at +4.21%, DB n=139 at -0.29%,
        #   LB n=114 at -3.92%.  ZERO non-IDP values change (696 rows):
        #   the multiplier is keyed on the DL/LB/DB family and nothing
        #   else resolves to one.
        #
        # Mean-normalised, so it re-allocates between IDP positions and
        # cannot inflate IDP as a class.  Applies to the OPT-IN
        # league-adjusted lens only, never the default market board.
        # Rollback: RISKIT_FEATURE_IDP_SCORING_FIT=0.
        #
        # CORRECTION.  The figures first recorded here (DB +3.66% / DL
        # +0.01% / LB -3.67%) were measured on a PARTIALLY corrected
        # scoring card and had DB and DL the wrong way round.
        # ``idp_pass_def`` (a CB stat) had been aliased and was scoring;
        # ``idp_qb_hit`` (an EDGE stat, 6,545 points across 2025) had
        # not, and was scoring zero.  Fixing one and not the other lifts
        # DB against DL by precisely what DL was owed — the
        # partial-correction bias described in UNIMPLEMENTED_BACKLOG.md
        # §14, which a purely RELATIVE measurement like this one is
        # maximally exposed to.  No code changed: the multipliers are
        # computed at runtime, so the engine produced the corrected
        # numbers as soon as the alias map was completed.  What was
        # wrong was the recorded rationale, including the one used to
        # justify turning this flag on.
        "idp_scoring_fit",
        # Reception-distance banding — the largest scoring divergence on
        # this card, and one the market structurally cannot see: the
        # per-catch spread is 8x while every ranking source prices a
        # flat rate.
        #
        # Blast radius measured over 199 receivers with 20+ catches
        # (2025).  Quote the TILT, never the 8x:
        #
        #   median 1.000  p10 0.942  p90 1.042  min 0.765  max 1.098
        #   0 of 199 at the clamp; dispersion drift 0.0226 (bound 0.12)
        #
        # Coherent at the extremes — checkdown backs and short-area
        # tight ends down (Jerome Ford 0.765), deep threats up (Alec
        # Pierce 1.098) — and the band shape is year-over-year stable
        # (r=0.72-0.77), so it is a player trait rather than noise.
        #
        # Mean-normalised, so it re-allocates between receivers and
        # cannot inflate the receiving corps as a class.  The shared
        # LEVEL (0.9543) is deliberately held OUT: it depends on the
        # baseline league being what the market prices, an assumption
        # that swings the level 2x and flips its sign across plausible
        # rates.  Opt-in league-adjusted lens only.
        # Rollback: RISKIT_FEATURE_RECEPTION_SCORING_FIT=0.
        "reception_scoring_fit",
    }
    off_only = {
        "dynamic_source_weights",  # held OFF until backtest data exists
    }
    assert not (safe_on & value_moving_on), "a flag cannot be both no-change and value-moving"
    for name, value in flags.items():
        if name in safe_on or name in value_moving_on:
            continue
        if name in off_only:
            assert value is False, f"flag {name!r} expected OFF but is ON"
            continue
        assert value is False, (
            f"flag {name!r} defaults ON but hasn't been vetted as "
            f"regression-safe.  Either add it to ``safe_on`` (additive / "
            f"inert / cannot move a number) or to ``value_moving_on`` "
            f"(with a MEASURED blast radius), with matching rationale in "
            f"_DEFAULTS — or flip the default to False."
        )


def test_unknown_flag_read_raises():
    with pytest.raises(KeyError, match="unknown feature flag"):
        feature_flags.is_enabled("does_not_exist")


def test_env_override_truthy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    assert feature_flags.is_enabled("monte_carlo_trade") is True


def test_env_override_falsy(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_UNIFIED_ID_MAPPER", "0")
    feature_flags.reload()
    assert feature_flags.is_enabled("unified_id_mapper") is False


def test_env_override_accepts_common_strings(monkeypatch):
    for val in ("true", "TRUE", "yes", "YES", "on", "ON"):
        monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", val)
        feature_flags.reload()
        assert feature_flags.is_enabled("monte_carlo_trade") is True, val
    for val in ("false", "FALSE", "no", "NO", "off", "OFF"):
        monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", val)
        feature_flags.reload()
        assert feature_flags.is_enabled("monte_carlo_trade") is False, val


def test_garbage_env_falls_back_to_default(monkeypatch):
    """Invalid env value → falls back to the registered default.
    Uses dynamic_source_weights since it's the one flag still defaulting
    OFF in the 2026-04-25 activation."""
    monkeypatch.setenv("RISKIT_FEATURE_DYNAMIC_SOURCE_WEIGHTS", "maybe")
    feature_flags.reload()
    assert feature_flags.is_enabled("dynamic_source_weights") is False


def test_snapshot_covers_every_registered_flag():
    snap = feature_flags.snapshot()
    for name in feature_flags.registered_flags():
        assert name in snap


def test_cache_stable_within_a_read_cycle(monkeypatch):
    """Within one reload cycle the value is stable — setting env
    after first read doesn't flip the cached value."""
    feature_flags.reload()
    initial = feature_flags.is_enabled("monte_carlo_trade")
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    # No reload — cache still holds the initial False.
    assert feature_flags.is_enabled("monte_carlo_trade") == initial
    feature_flags.reload()
    assert feature_flags.is_enabled("monte_carlo_trade") is True
