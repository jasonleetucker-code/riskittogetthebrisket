"""Best-ball roster simulation and trade deltas (LI-8).

What this adds, and what it deliberately does not
─────────────────────────────────────────────────
``src/trade/monte_carlo.py`` already answers *"which side of this trade
got more value"* by sampling consensus bands — and says plainly in its
own disclaimer that this is not a real-world win probability.
``src/ros/playoff_sim.py`` already answers *"what are this team's
playoff odds"* from a league snapshot.

Neither answers the question a manager actually asks about a trade:
**"how does this change my team's weekly scoring distribution?"**  That
is the quantity playoff odds are computed FROM, so it is the right
primitive to expose — and it needs no league schedule, standings or
snapshot, which keeps it testable and cheap.

Nothing here reimplements a simulator.  The per-player weekly draw
model is imported from ``playoff_sim`` and the lineup solve from
``src.ros.lineup``, so a change to either propagates here.

Best ball rewards the deep bench
────────────────────────────────
The slot goes to whoever spiked, so a roster's *tail* carries real
value — which is why this takes the FULL roster rather than a starters
+ truncated-bench view.

Measured on the 12 real rosters (400 sim weeks, seed 7): simulating off
``startingLineup + benchDepth`` (29 of 44-58 players) understates the
weekly mean by **+1.1 to +9.4 points**, and the size of the loss varies
about 8x by team — deep rosters lose most, which is exactly backwards
from what you want a depth metric to do.

**Stated honestly, because the flattering reading is available and
wrong:** at today's roster construction that distortion does NOT
reorder anybody.  All 12 teams hold the same rank under both inputs.
The earlier figure recorded here (+5.8 to +34.2) was measured before
the per-player seeding fix below and was inflated by that bug; it is
retracted.  So the case for the full roster is that a truncated roster
is simply the wrong input to a format that pays for the tail, and the
error is team-dependent rather than a constant offset that cancels —
not that it currently changes any answer this league would read.

Confidence and the no-op rule
─────────────────────────────
Every result carries ``confidence`` and the assumptions that produced
it.  A delta computed from a roster the model cannot price is reported
as ``None`` with a reason, never as 0.0 — "no change" and "cannot say"
are different answers and collapsing them is how a UI ends up asserting
a trade is neutral when it simply has no data.

The draw model's known limit, and who is fixing it
──────────────────────────────────────────────────
Per-player weeks default to ``Gaussian(rosValue / 2.7, cv-by-position)``,
inherited from ``playoff_sim``.  Real weekly scores are right-skewed
and zero-inflated (injuries, benchings, game script), which a Gaussian
understates in both tails.  Best ball rewards the UPPER tail
specifically, so this most likely **understates** the value of
high-variance depth — the exact thing the format pays for.

Two separable problems live in that sentence, and only one is mine:

* the ``/2.7`` divisor and the CV table are **uncalibrated magic
  constants**.  ``claude/league-intel-sim`` fixes this properly, in
  ``src/league_intel/sim_calibration.py``, by deriving both from real
  stat lines scored through the exact scorer under this league's own
  settings.  That branch owns the schema; ``points_model`` here is the
  seam that consumes it, matching its
  ``draw(ros_value, position, rng)`` signature so its calibrated model
  drops in as a parameter with no edit to this file.  **Do not add a
  second calibration here.**
* the Gaussian *shape* is still an approximation even once calibrated.
  Fixing that needs per-player weekly histories, not a different closed
  form, and is unclaimed.

Every result stamps which model produced it in ``assumptions`` rather
than leaving it to the reader to know.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel import sim_calibration as _sim_calibration

__all__ = [
    "SIM_MODEL_VERSION",
    "DEFAULT_SIM_WEEKS",
    "RosterDistribution",
    "TradeDelta",
    "simulate_roster",
    "simulate_trade_delta",
]

SIM_MODEL_VERSION = "li.sim.2026-07-26.v1"

DEFAULT_SIM_WEEKS = 500
"""Simulated weeks per roster.  500 keeps the mean's standard error
well under a point at observed weekly sd (~25), which is finer than
the effects being measured."""

_MIN_PRICED_PLAYERS = 5
"""Below this the roster cannot be meaningfully simulated and the
result is reported as unavailable rather than as a number."""


@dataclass(frozen=True)
class RosterDistribution:
    """A roster's simulated weekly best-ball scoring distribution."""

    mean: float | None
    sd: float | None
    p10: float | None
    p90: float | None
    weeks: int
    priced_players: int
    total_players: int
    unavailable_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.mean is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mean": self.mean,
            "sd": self.sd,
            "p10": self.p10,
            "p90": self.p90,
            "weeks": self.weeks,
            "pricedPlayers": self.priced_players,
            "totalPlayers": self.total_players,
            "isAvailable": self.is_available,
            "unavailableReason": self.unavailable_reason,
        }


@dataclass
class TradeDelta:
    """Change in a roster's weekly distribution from a trade.

    ``mean_delta`` is the headline: expected weekly points gained or
    lost.  ``sd_delta`` matters independently — in best ball a trade
    that raises the ceiling while lowering the floor is a real
    strategic choice, not noise, and collapsing both into one number
    hides it.
    """

    before: RosterDistribution
    after: RosterDistribution
    mean_delta: float | None
    sd_delta: float | None
    confidence: float = 0.0
    model_version: str = SIM_MODEL_VERSION
    assumptions: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None

    @property
    def is_available(self) -> bool:
        return self.mean_delta is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "meanDelta": self.mean_delta,
            "sdDelta": self.sd_delta,
            "confidence": self.confidence,
            "modelVersion": self.model_version,
            "isAvailable": self.is_available,
            "unavailableReason": self.unavailable_reason,
            "assumptions": list(self.assumptions),
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


class _LegacyPointsModel:
    """The pre-calibration rosValue->points model, behind the same
    interface ``sim_calibration.PointsModel`` exposes.

    This exists so the draw model is a SEAM rather than a hardcoded
    formula: a calibrated ``PointsModel`` drops in as the ``points_model``
    parameter with no edit to this module.

    It no longer restates the arithmetic. It used to hardcode the ``2.7``
    divisor and import the per-position CV table from
    ``ros/playoff_sim``, which itself held a byte-identical copy of
    ``sim_calibration.FALLBACK_CV_BY_POSITION`` — three copies of three
    numbers, and two implementations of one Gaussian draw. It now
    delegates to a ``PointsModel`` built from the owner's own fallback
    constants, which is an exact behavioural identity (pinned by
    ``tests/league_intel/test_points_model_single_owner.py``).

    What it keeps is its own ``source`` stamp. Parity of NUMBERS is not
    parity of PROVENANCE: a run on this path must still report
    ``legacy-constants`` rather than borrow the owner's
    ``fallback-constants`` label, so ``pointsModelSource`` cannot claim a
    provenance the run did not have.
    """

    source = "legacy-constants"

    def __init__(self) -> None:
        # The owner's documented fallback — NOT a calibrated artifact.
        # ``PointsModel()`` with no arguments is exactly the constants
        # this class used to inline.
        self._model = _sim_calibration.PointsModel()

    def draw(self, ros_value: float, position: str, rng: Any) -> float:
        return self._model.draw(ros_value, position, rng)


_LEGACY_POINTS_MODEL = _LegacyPointsModel()


def _draw_week(
    players: Sequence[Mapping[str, Any]],
    week: int,
    seed: int,
    points_model: Any = None,
):
    """One week of per-player draws, as optimizer-ready rows.

    Reuses ``playoff_sim``'s draw model rather than restating it, so
    the two simulators cannot drift apart.

    **Each player is drawn from its OWN RNG**, seeded by
    ``(seed, week, player_id)``, rather than from one shared stream.
    That matters for trade deltas: a shared stream advances once per
    player, so removing a player from the roster shifts every
    subsequent draw and desynchronises the before/after comparison.
    Measured, that phantom effect reported +2.55 weekly points for
    DROPPING a player — impossible in best ball, where removing an
    option is weakly negative.  Per-player seeding makes a player's
    weekly score independent of roster composition and ordering, so
    the paired comparison is real.
    """
    from src.ros.lineup import RosterPlayer  # noqa: PLC0415

    model = points_model or _LEGACY_POINTS_MODEL
    drawn: list[RosterPlayer] = []
    for p in players:
        ros = float(p.get("rosValue") or 0.0)
        if ros <= 0:
            continue
        pos = str(p.get("position") or "").upper()
        pid = str(p.get("playerId") or p.get("canonicalName") or "")
        rng = random.Random(f"{seed}|{week}|{pid}")
        drawn.append(
            RosterPlayer(
                player_id=pid,
                canonical_name=str(p.get("canonicalName") or ""),
                position=pos,
                ros_value=model.draw(ros, pos, rng),
                fantasy_positions=tuple(
                    str(fp).upper() for fp in (p.get("fantasyPositions") or ())
                ),
            )
        )
    return drawn


def simulate_roster(
    players: Iterable[Mapping[str, Any]],
    starter_slots: Sequence[str],
    *,
    weeks: int = DEFAULT_SIM_WEEKS,
    seed: int = 0,
    points_model: Any = None,
) -> RosterDistribution:
    """Simulate one roster's weekly best-ball scoring distribution.

    Pass the FULL roster — best ball pays for the tail.  Players with
    no ROS value are counted but cannot be drawn; when too few are
    priced the distribution is reported unavailable rather than
    fabricated from a handful.

    ``points_model`` is the rosValue->points seam: anything exposing
    ``draw(ros_value, position, rng)``, which is
    ``sim_calibration.PointsModel``'s signature.  ``None`` keeps the
    legacy constants, so this is a no-op until a calibrated model is
    passed in.
    """
    roster = list(players)
    priced = sum(1 for p in roster if float(p.get("rosValue") or 0.0) > 0)
    if priced < _MIN_PRICED_PLAYERS or not starter_slots:
        return RosterDistribution(
            mean=None,
            sd=None,
            p10=None,
            p90=None,
            weeks=0,
            priced_players=priced,
            total_players=len(roster),
            unavailable_reason=(
                f"only {priced} priced player(s) and {len(starter_slots)} slot(s); "
                "too little to simulate"
            ),
        )

    from src.ros.lineup import optimize_lineup  # noqa: PLC0415

    scores = [
        optimize_lineup(
            _draw_week(roster, week, seed, points_model), starter_slots=list(starter_slots)
        ).starting_lineup_score
        for week in range(weeks)
    ]
    ordered = sorted(scores)
    return RosterDistribution(
        mean=statistics.fmean(scores),
        sd=statistics.pstdev(scores),
        p10=ordered[int(0.10 * len(ordered))],
        p90=ordered[int(0.90 * len(ordered))],
        weeks=weeks,
        priced_players=priced,
        total_players=len(roster),
    )


def simulate_trade_delta(
    roster_before: Iterable[Mapping[str, Any]],
    roster_after: Iterable[Mapping[str, Any]],
    starter_slots: Sequence[str],
    *,
    weeks: int = DEFAULT_SIM_WEEKS,
    seed: int = 0,
    points_model: Any = None,
) -> TradeDelta:
    """How a roster change moves the weekly scoring distribution.

    Both sides are simulated with the SAME seed, so the difference is
    the roster change rather than sampling noise — the paired-sample
    trick, and without it a 500-week run would report several points of
    phantom delta.

    Returns an unavailable delta (``mean_delta is None``) when either
    roster cannot be simulated.  That is deliberately distinct from a
    delta of 0.0.
    """
    before = simulate_roster(
        roster_before, starter_slots, weeks=weeks, seed=seed, points_model=points_model
    )
    after = simulate_roster(
        roster_after, starter_slots, weeks=weeks, seed=seed, points_model=points_model
    )

    model_source = getattr(points_model or _LEGACY_POINTS_MODEL, "source", "unknown")
    assumptions = [
        f"weekly scores drawn from the '{model_source}' points model; a Gaussian "
        "approximation on rosValue, not a fitted per-player distribution",
        "lineup solved exactly per simulated week (src.ros.lineup)",
        "paired seeds: before/after share draws so the delta isolates the " "roster change",
    ]
    if not before.is_available or not after.is_available:
        blocked = before if not before.is_available else after
        return TradeDelta(
            before=before,
            after=after,
            mean_delta=None,
            sd_delta=None,
            confidence=0.0,
            assumptions=assumptions,
            unavailable_reason=blocked.unavailable_reason,
        )

    # Confidence reflects how much of the roster the model could price.
    coverage = min(
        before.priced_players / max(1, before.total_players),
        after.priced_players / max(1, after.total_players),
    )
    return TradeDelta(
        before=before,
        after=after,
        mean_delta=after.mean - before.mean,
        sd_delta=after.sd - before.sd,
        confidence=round(0.6 * coverage, 3),
        assumptions=assumptions,
    )
