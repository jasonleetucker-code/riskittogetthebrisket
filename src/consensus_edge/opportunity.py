"""Whether the value gap is likely to persist — on data that actually exists.

A mispricing is a claim that the market will move toward our number. That
claim is much weaker when the gap exists *because* our inputs are stale:
a player whose role collapsed last week is not underpriced, he is
correctly repriced and our board has not caught up. This is the check on
that.

**Rebuilt on playerctx**, after an audit established that the obvious
alternative is not usable. ``src/nfl_data/opportunity_stats.py`` looks
like the right source — red-zone and third-down work per player — but it
has zero callers, no persisted artifact, no timer, a fabricated
``position`` field (literally ``"WR/TE"`` for anyone targeted), and
double-counted third-down conversions. Wiring it would have produced a
component with no rows. ``usage_windows``, ``depth_charts`` and
``injury_feed`` are likewise unwired with flags off and no artifacts;
target share and route participation do not exist on disk anywhere in
this repo.

What *is* real is ``data/playerctx/snapshot.json``: refreshed weekly in
production by an unconditional systemd timer, keyed by GSIS id with a
``sleeperIndex``, carrying per-player snap share, a recent-vs-season snap
trend, and team depth rank. Those are genuine role signals.

**Direction, stated carefully.** Two axes here point in *opposite*
directions by design:

* **Snap trend is opportunity.** Rising snap share means the role is
  growing, which supports the gap persisting long enough to close.
* **Board momentum is RISK, and only risk.** A value already climbing
  means the market is closing the gap without us. That is a reason to
  discount a buy, never to add to one. The previous version scored
  rising board value POSITIVELY — plain momentum-chasing, worth up to
  20% of the composite pushed toward Buy purely because a price went up.
  Its own docstring said it did the opposite. Corrected here: the axis
  is clamped to ``<= 0`` so it can subtract and never add.

**Unevidenced axes contribute exactly nothing** and are named in
``absentAxes``, borrowing ``league_intel/adjustment.py``'s ABSENT tier so
a caller structurally cannot smuggle in an effect. Returning 0.0 would
read as "assessed and found neutral", which is a different claim.
"""

from __future__ import annotations

from typing import Any

# Evidence tiers, mirroring league_intel/adjustment.py.
TIER_ABSENT = "absent"
TIER_OBSERVED = "observed"

UNSCORED_NO_EVIDENCE = "no_opportunity_evidence_available"

# A snap-share swing of this many percentage points saturates the axis.
# Chosen as a plain, legible bound rather than a fitted one: nothing here
# has been validated against an outcome, so a tuned constant would imply
# precision this component has not earned.
_SNAP_TREND_SATURATION_PCT = 15.0

# Board-value move at which the risk axis saturates. 25% over the window
# is a large repricing; beyond it the discount stops growing.
_MOMENTUM_SATURATION = 0.25


def _axis(name: str, value: float | None, tier: str, detail: str | None = None) -> dict[str, Any]:
    return {"axis": name, "score": value, "tier": tier, "detail": detail}


def snap_trend_axis(context: dict[str, Any] | None) -> dict[str, Any]:
    """Is this player's role growing or shrinking?

    Reads ``snaps.trend`` from a playerctx record — ``recentPct`` minus
    ``seasonPct``, so positive means the last three games used him more
    than his season average. That is the one genuinely forward-looking
    role signal this repo has on disk.
    """
    snaps = (context or {}).get("snaps")
    if not isinstance(snaps, dict):
        return _axis("snapTrend", None, TIER_ABSENT, "no player-context snap record")

    trend = snaps.get("trend")
    if not isinstance(trend, (int, float)):
        return _axis("snapTrend", None, TIER_ABSENT, "snap record carries no trend")

    games = snaps.get("games")
    if isinstance(games, (int, float)) and games < 3:
        # recentPct is a last-three-games figure; under three games it is
        # the same number as the season average and the "trend" is an
        # artifact of the window, not a change in role.
        return _axis("snapTrend", None, TIER_ABSENT, "fewer than three games played")

    score = max(-1.0, min(1.0, float(trend) / _SNAP_TREND_SATURATION_PCT))
    return _axis(
        "snapTrend",
        score,
        TIER_OBSERVED,
        f"snap share {float(trend):+.1f} pts vs season average",
    )


def board_momentum_risk_axis(rank_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Discount a gap the market is already closing. Never a positive.

    Clamped to ``<= 0`` deliberately. A rising board value means the
    market is moving toward our number without us, so the remaining edge
    is smaller than the current gap suggests — a reason to temper a buy.
    Letting it go positive would make "the price went up" evidence that
    the price should go up, which is the momentum-chasing this package
    exists to avoid.

    Reads ``val`` — the field ``rank_history.load_history`` actually
    emits. The previous version read ``rankDerivedValue``, a key that
    producer never writes, so the axis returned ABSENT for every player
    in every environment including production. Its unit test built the
    fixture by hand in the wrong shape, so nothing caught it.
    """
    if not rank_history or len(rank_history) < 3:
        return _axis("boardMomentumRisk", None, TIER_ABSENT, "no rank history available")

    values = [
        float(point["val"])
        for point in rank_history
        if isinstance(point, dict) and isinstance(point.get("val"), (int, float))
    ]
    if len(values) < 3:
        return _axis("boardMomentumRisk", None, TIER_ABSENT, "rank history carries no values")

    first, last = values[0], values[-1]
    if first <= 0:
        return _axis("boardMomentumRisk", None, TIER_ABSENT, "non-positive baseline value")

    change = (last - first) / first
    if change <= 0:
        # A falling value is not evidence FOR buying — it is what created
        # the gap in the first place, and counting it again would double
        # count the mispricing signal.
        return _axis(
            "boardMomentumRisk",
            0.0,
            TIER_OBSERVED,
            f"board value moved {change:+.1%}; no gap-closing risk",
        )

    penalty = -min(1.0, change / _MOMENTUM_SATURATION)
    return _axis(
        "boardMomentumRisk",
        penalty,
        TIER_OBSERVED,
        f"board value already up {change:+.1%} over {len(values)} snapshots",
    )


def assess(
    *,
    rank_history: list[dict[str, Any]] | None = None,
    player_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Combine whatever opportunity evidence exists into one score.

    Returns ``score = None`` with a reason when nothing is evidenced —
    never 0.0, which would read as "assessed and found neutral".
    """
    axes = [
        snap_trend_axis(player_context),
        board_momentum_risk_axis(rank_history),
    ]

    observed = [a for a in axes if a["tier"] == TIER_OBSERVED and a["score"] is not None]
    absent = [a["axis"] for a in axes if a["tier"] == TIER_ABSENT]

    result: dict[str, Any] = {
        "score": None,
        "reason": None,
        "axes": axes,
        "absentAxes": absent,
        "observedAxes": [a["axis"] for a in observed],
    }
    if not observed:
        result["reason"] = UNSCORED_NO_EVIDENCE
        return result

    result["score"] = sum(float(a["score"]) for a in observed) / len(observed)
    return result
