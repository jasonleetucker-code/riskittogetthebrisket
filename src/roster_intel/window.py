"""Competitive window as a probability distribution, not a label.

Five states — ``championship_contender``, ``playoff_contender``,
``retool``, ``productive_struggle``, ``rebuild`` — reported as
probabilities that are mutually exclusive and sum to 1.  A binary
contender/rebuilder flag throws away the thing managers actually
disagree about: a 55/45 split between retool and rebuild is a real
strategic fork, and a label picks a side without saying it was close.

Ordering (recorded because a consumer asked)
────────────────────────────────────────────
The five sit on a contend↔rebuild axis, but that axis conflates two
different quantities: CURRENT COMPETITIVENESS (championship / playoff
contender) and DIRECTIONAL INTENT (retool / rebuild).
``productive_struggle`` mixes both.  The ends are solidly ordered; the
weak link is **retool vs productive_struggle**, which are different
strategies at similar competitiveness rather than adjacent points on
one scale.  ``STATE_ORDER`` encodes the axis for consumers that need
one, and ``ORDERING_CAVEAT`` states where it is soft, so a visual form
that assumes a strict order can be chosen deliberately rather than by
accident.

How the probabilities are produced
──────────────────────────────────
Two measured axes, then a softmax over each state's affinity:

* ``competitiveness`` — where this roster's championship odds sit
  relative to the league.  Sourced from ``src/ros/playoff_sim.py`` when
  the caller supplies its output; falls back to lineup-score rank when
  it does not, with the source stamped either way.
* ``trajectory`` — value-weighted age of the players who actually ENTER
  the optimal lineup, against the league's own distribution.  Weighted
  and lineup-restricted on purpose: the age of a bench dart throw tells
  you nothing about a window, and an unweighted mean lets six rookies
  hide one 33-year-old anchor.

Softmax rather than hand-cut thresholds because thresholds produce
exactly the artifact this project has been burned by — a team one point
either side of a cut flips category while its neighbour does not move
at all.  Temperature controls decisiveness and is explicit.

Pure computation: no I/O, no network, no clock.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.roster_intel.marginal import solve_summary
from src.ros.lineup import RosterPlayer, is_priced

__all__ = [
    "COMPETITIVE_STATES",
    "ORDERING_CAVEAT",
    "STATE_ORDER",
    "CompetitiveWindow",
    "WindowInputs",
    "compute_window",
    "league_competitiveness",
    "trajectory_score",
]

COMPETITIVE_STATES = (
    "championship_contender",
    "playoff_contender",
    "retool",
    "productive_struggle",
    "rebuild",
)

# Contend → rebuild. See the module docstring: solid at the ends, soft
# in the middle pair.
STATE_ORDER = COMPETITIVE_STATES

ORDERING_CAVEAT = (
    "States are ordered contend->rebuild, but the axis conflates current "
    "competitiveness with directional intent. 'retool' vs "
    "'productive_struggle' are different strategies at similar "
    "competitiveness, not adjacent competitiveness levels; treat that "
    "pair's ordering as soft. A diverging visual should place its centre "
    "BETWEEN them, and that centre is a boundary rather than a state."
)

# Each state's ideal position in (competitiveness, trajectory) space,
# both on 0-1. Trajectory: 1.0 = young/ascending, 0.0 = old/descending.
_STATE_ANCHORS: dict[str, tuple[float, float]] = {
    "championship_contender": (0.95, 0.45),
    "playoff_contender": (0.70, 0.50),
    "retool": (0.45, 0.70),
    "productive_struggle": (0.25, 0.80),
    "rebuild": (0.05, 0.60),
}

# Competitiveness matters more than trajectory for placing a roster: a
# strong team is contending whatever its age curve, while a weak team's
# age tells you which KIND of weak it is.
_COMPETITIVENESS_WEIGHT = 2.0
_TRAJECTORY_WEIGHT = 1.0

DEFAULT_TEMPERATURE = 0.18

# Ages bounding the trajectory scale. Outside these the score clamps;
# they are fantasy-relevant career bounds, not biology.
_AGE_YOUNG = 22.0
_AGE_OLD = 32.0


@dataclass(frozen=True)
class WindowInputs:
    """The measured axes, exposed so a caller can audit the placement."""

    competitiveness: float
    trajectory: float
    competitiveness_source: str
    trajectory_sample: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "competitiveness": round(self.competitiveness, 4),
            "trajectory": round(self.trajectory, 4),
            "competitivenessSource": self.competitiveness_source,
            "trajectorySample": self.trajectory_sample,
        }


def _round_preserving_sum(probs: Mapping[str, float], places: int = 4) -> dict[str, float]:
    """Round to ``places`` while keeping the sum at exactly 1.

    Naive per-key rounding drifts: five values rounded to 4dp summed to
    1.0001 in the serialized payload, so a consumer reading the JSON saw
    a distribution that did not sum to 1 even though the underlying one
    did.  The invariant has to survive serialization, because the
    payload is what consumers actually read.

    Largest-remainder method: floor everything at the target precision,
    then hand the leftover quanta to the keys with the biggest discarded
    remainder.  Deterministic — ties break on key name.
    """
    if not probs:
        return {}
    scale = 10**places
    scaled = {k: v * scale for k, v in probs.items()}
    floored = {k: math.floor(v) for k, v in scaled.items()}
    remainder = int(round(scale - sum(floored.values())))
    if remainder > 0:
        order = sorted(probs, key=lambda k: (-(scaled[k] - floored[k]), k))
        for k in order[:remainder]:
            floored[k] += 1
    return {k: floored[k] / scale for k in probs}


@dataclass(frozen=True)
class CompetitiveWindow:
    """Five mutually exclusive probabilities summing to 1."""

    probabilities: dict[str, float]
    inputs: WindowInputs
    most_likely: str
    # True when a caller pinned the state by hand.
    overridden: bool = False
    override_reason: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def confidence(self) -> float:
        """Probability mass on the most likely state.  Near 0.2 means
        the five are indistinguishable and the label means nothing."""
        return self.probabilities.get(self.most_likely, 0.0)

    def to_dict(self) -> dict[str, Any]:
        # ``affinities`` is the honest name.  These are softmaxed
        # NEGATIVE SQUARED DISTANCES to five hand-placed anchors in
        # (competitiveness x trajectory), normalised so they sum to 1.
        #
        # Summing to 1 does not make a distribution a probability.  No
        # anchor position, no axis weight and no temperature here was
        # fitted to an observed outcome, and nothing scores these against
        # what teams actually did — so "70% rebuild" would be a claim the
        # model cannot support.  ``probabilities`` is retained as a
        # deprecated alias for one release; new consumers read
        # ``affinities`` (audit finding H).
        rounded = _round_preserving_sum(self.probabilities)
        return {
            "affinities": rounded,
            "probabilities": rounded,  # deprecated alias
            "mostLikely": self.most_likely,
            "confidence": round(self.confidence, 4),
            "overridden": self.overridden,
            "overrideReason": self.override_reason,
            "inputs": self.inputs.to_dict(),
            "stateOrder": list(STATE_ORDER),
            "orderingCaveat": ORDERING_CAVEAT,
            "notes": list(self.notes),
        }


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def league_competitiveness(
    owner_id: str,
    *,
    playoff_odds: Sequence[Mapping[str, Any]] | None = None,
    lineup_scores: Mapping[str, float] | None = None,
) -> tuple[float, str]:
    """Where this roster sits competitively, on 0-1.

    Prefers championship odds from ``src/ros/playoff_sim.py`` — that
    simulator already models schedule, variance and the bracket, and
    building a second one here would be a parallel path (the repo's
    one-live-path rule).  Falls back to lineup-score percentile, which
    is a structural proxy and is stamped as such.

    Returns ``(score, source)``.
    """
    if playoff_odds:
        rows = [r for r in playoff_odds if r.get("ownerId")]
        champ = {str(r["ownerId"]): float(r.get("championshipOdds") or 0.0) for r in rows}
        if champ and any(v > 0 for v in champ.values()):
            mine = champ.get(str(owner_id))
            if mine is not None:
                # Percentile against the league, so the scale is
                # league-relative rather than absolute-odds-relative
                # (in a 12-team league even the best team's title odds
                # are small in absolute terms).
                below = sum(1 for v in champ.values() if v < mine)
                ties = sum(1 for v in champ.values() if v == mine)
                pct = (below + 0.5 * ties) / len(champ)
                return _clamp01(pct), "championshipOdds"

    if lineup_scores:
        mine = lineup_scores.get(str(owner_id))
        if mine is not None and len(lineup_scores) > 1:
            below = sum(1 for v in lineup_scores.values() if v < mine)
            ties = sum(1 for v in lineup_scores.values() if v == mine)
            pct = (below + 0.5 * ties) / len(lineup_scores)
            return _clamp01(pct), "lineupScoreRank"

    return 0.5, "unavailable"


def trajectory_score(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[float, int]:
    """Value-weighted age of LINEUP ENTRANTS, mapped to 0-1.

    1.0 = young/ascending, 0.0 = old/descending.

    Restricted to lineup entrants and weighted by value because those
    are the two ways an age number lies: a bench dart throw's age says
    nothing about the window, and an unweighted mean lets six rookies
    hide one 33-year-old anchor.

    Returns ``(score, sample_size)``.  Sample 0 ⇒ 0.5 (neutral), which
    is the honest answer when no ages were supplied.
    """
    meta = player_meta or {}
    entered = solve_summary(list(pool), list(slots)).assigned_ids
    weighted_sum = 0.0
    weight = 0.0
    n = 0
    for p in pool:
        if p.player_id not in entered:
            continue
        age = (meta.get(p.player_id) or {}).get("age")
        if age is None:
            continue
        if not is_priced(p):
            continue  # UNKNOWN carries no weight; it is not weight zero
        w = max(0.0, p.ros_value)
        if w <= 0:
            continue
        weighted_sum += float(age) * w
        weight += w
        n += 1
    if weight <= 0 or n == 0:
        return 0.5, 0
    mean_age = weighted_sum / weight
    # Older -> lower score.
    raw = (_AGE_OLD - mean_age) / (_AGE_OLD - _AGE_YOUNG)
    return _clamp01(raw), n


def _softmax_affinities(
    competitiveness: float,
    trajectory: float,
    temperature: float,
) -> dict[str, float]:
    """Distance-to-anchor softmax over the five states."""
    scores: dict[str, float] = {}
    for state, (c_anchor, t_anchor) in _STATE_ANCHORS.items():
        d2 = (
            _COMPETITIVENESS_WEIGHT * (competitiveness - c_anchor) ** 2
            + _TRAJECTORY_WEIGHT * (trajectory - t_anchor) ** 2
        )
        scores[state] = -d2
    temp = max(1e-6, temperature)
    mx = max(scores.values())
    exps = {k: math.exp((v - mx) / temp) for k, v in scores.items()}
    total = sum(exps.values())
    if total <= 0:  # pragma: no cover - unreachable while exps are positive
        return {k: 1.0 / len(exps) for k in exps}
    return {k: v / total for k, v in exps.items()}


def compute_window(
    owner_id: str,
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    *,
    playoff_odds: Sequence[Mapping[str, Any]] | None = None,
    lineup_scores: Mapping[str, float] | None = None,
    player_meta: Mapping[str, Mapping[str, Any]] | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    override_state: str | None = None,
    override_reason: str | None = None,
) -> CompetitiveWindow:
    """Probabilistic competitive window for one roster.

    ``override_state`` is the manual hook.  It pins the distribution to
    that state rather than nudging it: a manager who says "I am
    rebuilding" is stating intent the model cannot observe, and
    blending it with a model guess would produce a number that is
    neither their intent nor the model's read.  The override is stamped
    so a consumer can always tell it apart from a measurement.
    """
    notes: list[str] = []

    if override_state is not None:
        if override_state not in COMPETITIVE_STATES:
            raise ValueError(
                f"unknown competitive state {override_state!r}; "
                f"expected one of {COMPETITIVE_STATES}"
            )
        probs = {s: 0.0 for s in COMPETITIVE_STATES}
        probs[override_state] = 1.0
        comp, comp_src = league_competitiveness(
            owner_id, playoff_odds=playoff_odds, lineup_scores=lineup_scores
        )
        traj, sample = trajectory_score(pool, slots, player_meta)
        return CompetitiveWindow(
            probabilities=probs,
            inputs=WindowInputs(comp, traj, comp_src, sample),
            most_likely=override_state,
            overridden=True,
            override_reason=override_reason,
            notes=("manual override; model inputs retained for audit",),
        )

    comp, comp_src = league_competitiveness(
        owner_id, playoff_odds=playoff_odds, lineup_scores=lineup_scores
    )
    if comp_src == "unavailable":
        notes.append("no competitiveness source supplied; defaulted to league median")
    elif comp_src == "lineupScoreRank":
        notes.append(
            "competitiveness from lineup-score rank (structural proxy); "
            "supply playoff_sim output for simulated odds"
        )

    traj, sample = trajectory_score(pool, slots, player_meta)
    if sample == 0:
        notes.append("no ages supplied for lineup entrants; trajectory neutral")

    probs = _softmax_affinities(comp, traj, temperature)
    most_likely = max(probs, key=lambda k: probs[k])
    if probs[most_likely] < 0.30:
        notes.append(
            "no state clears 30%; this roster sits between windows and the "
            "single label should not be presented alone"
        )

    return CompetitiveWindow(
        probabilities=probs,
        inputs=WindowInputs(comp, traj, comp_src, sample),
        most_likely=most_likely,
        notes=tuple(notes),
    )
