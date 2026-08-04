"""Insider Trading lead scoring — which league-mate to approach, and why.

The product question: *"I want to move Player X. Who in my league is the
best person to call?"*  And its mirror: *"I want Player X. Who has him,
and what do they want?"*

──────────────────────────────────────────────────────────────────────
Why this COMPOSES ``roster_intel.partner`` instead of extending it
──────────────────────────────────────────────────────────────────────
``partner.assess_partner`` already models the hard half — positional
need, competitive-window alignment, market fairness, activity — as a
bounded log-odds accumulation with calibrated confidence.  Reimplementing
any of that here would be exactly the competing-implementation problem
this codebase keeps paying for, so it is reused wholesale.

What is NOT done is adding a "demonstrated interest" term *inside* that
module, and the reason is worth stating because it looks like the
obvious move:

1. **Different questions.**  ``partner.py`` scores a trade SHAPE —
   "would an offer of this construction get engaged with".  A lead score
   answers a MANAGER question — "is this the right person to call about
   this specific player".  Revealed preference for one player is
   evidence for the second and mostly noise for the first.

2. **Blast radius.**  Five other surfaces consume ``assess_partner``
   (gameplan, trade suggestions, angle, the roster engine, the terminal).
   Injecting a new term into its logit budget would move every one of
   their numbers, which is far beyond what a new page should do.

3. **It is pinned as a closed set.**  ``contributions`` is asserted by
   exact set equality, and a separate test independently reimplements
   the assembly arithmetic over the ``MAX_*_LOGIT`` constants.  Those
   tests exist precisely to stop a term being bolted on casually.

So partner fit enters here as ONE bounded input among several, and the
lead score is its own transparent, separately-explained number.

──────────────────────────────────────────────────────────────────────
Epistemic inheritance
──────────────────────────────────────────────────────────────────────
``partner.py`` is emphatic that its acceptance figure is a plausibility
score wearing probability units, because a rejection is never observed.
That limitation is INHERITED, not escaped: a lead score is a ranking of
who to talk to first, never a prediction that anyone will say yes.  It
is deliberately reported on an unbounded-looking 0-100 display scale
with its components exposed, and never as a probability.

Demonstrated interest is the one genuinely NEW evidence type, and unlike
acceptance it IS observable: a manager who traded FOR this player in
another league revealed a preference, in public, with real assets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

from src.roster_intel import partner as partner_model

# ── weights ──────────────────────────────────────────────────────────
#
# Additive on a 0-1 scale, then displayed x100.  Deliberately NOT log
# odds: this is a ranking, not a probability, and borrowing the odds
# machinery would imply a calibration that does not exist.

W_DEMONSTRATED_INTEREST = 0.34
W_PARTNER_FIT = 0.26
W_POSITIONAL_NEED = 0.18
W_VALUE_MATCH = 0.12
W_ACTIVITY = 0.10

# Contradictory behaviour is SUBTRACTED rather than folded into the
# interest term, so "they bought him twice and sold him once" stays
# legible instead of collapsing to a single net number.
MAX_CONTRADICTION_PENALTY = 0.20
# Thin evidence is discounted, never hidden.
MAX_LOW_SAMPLE_PENALTY = 0.12

# Recency: an acquisition 3 days ago is stronger evidence of current
# appetite than one 300 days ago.  Half-life rather than a cliff, so a
# lead does not blink out overnight.
INTEREST_HALF_LIFE_DAYS = 45.0

DAY_MS = 24 * 3600 * 1000


@dataclass
class InterestObservation:
    """One manager's observed behaviour toward ONE asset, elsewhere."""

    user_id: str
    asset_id: str
    buys: int = 0
    sells: int = 0
    unique_leagues: int = 0
    last_ts: int | None = None

    @property
    def volume(self) -> int:
        return self.buys + self.sells


@dataclass
class Lead:
    owner_id: str
    display_name: str = ""
    score: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)
    interest: InterestObservation | None = None
    partner_fit: float | None = None
    partner_confidence: float | None = None
    owns_asset: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "displayName": self.display_name or None,
            "leadScore": round(self.score, 1),
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "reasons": self.reasons,
            "cautions": self.cautions,
            "ownsAsset": self.owns_asset,
            "partnerFitScore": self.partner_fit,
            "partnerConfidence": self.partner_confidence,
            "interest": (
                {
                    "buys": self.interest.buys,
                    "sells": self.interest.sells,
                    "uniqueLeagues": self.interest.unique_leagues,
                    "lastTs": self.interest.last_ts,
                }
                if self.interest
                else None
            ),
        }


def _recency_weight(last_ts: int | None, now_ms: int) -> float:
    """1.0 for something that just happened, decaying by half-life."""
    if not last_ts:
        return 0.0
    age_days = max(0.0, (now_ms - int(last_ts)) / DAY_MS)
    return 0.5 ** (age_days / INTEREST_HALF_LIFE_DAYS)


def demonstrated_interest(
    obs: InterestObservation | None,
    now_ms: int,
    *,
    direction: str = "buy",
) -> tuple[float, list[str], list[str]]:
    """0-1 strength of revealed preference, plus reasons and cautions.

    ``direction="buy"`` scores "do they want this player" (for SELL
    mode).  ``direction="sell"`` scores "are they willing to move him"
    (for BUY mode).  The same observations answer both questions from
    opposite sides, which is why one function serves both modes.
    """
    if obs is None or obs.volume == 0:
        return 0.0, [], []

    wanted = obs.buys if direction == "buy" else obs.sells
    against = obs.sells if direction == "buy" else obs.buys
    if wanted <= 0:
        return 0.0, [], []

    # Saturating in count: the SECOND acquisition is the one that turns
    # a data point into a pattern; the fifth adds little.
    depth = wanted / (wanted + 1.5)
    # Breadth across independent leagues is worth more than repetition
    # inside one.
    breadth = min(1.0, obs.unique_leagues / 2.0) if obs.unique_leagues else 0.5
    recency = _recency_weight(obs.last_ts, now_ms)

    strength = depth * (0.55 + 0.25 * breadth + 0.20 * recency)

    verb = "acquired" if direction == "buy" else "moved"
    reasons = []
    if wanted == 1:
        reasons.append(f"{verb.capitalize()} this asset once in another league")
    else:
        reasons.append(f"{verb.capitalize()} this asset {wanted}x across other leagues")
    if obs.unique_leagues >= 2:
        reasons.append(f"Across {obs.unique_leagues} independent leagues")
    if recency >= 0.6:
        reasons.append("Recent — within the last few weeks")

    cautions = []
    if against > 0:
        cautions.append(
            f"Also {'sold' if direction == 'buy' else 'bought'} this asset "
            f"{against}x — mixed signal, not a clean read"
        )
    return min(1.0, strength), reasons, cautions


def _contradiction_penalty(obs: InterestObservation | None, direction: str) -> float:
    if obs is None or obs.volume == 0:
        return 0.0
    against = obs.sells if direction == "buy" else obs.buys
    wanted = obs.buys if direction == "buy" else obs.sells
    if against <= 0:
        return 0.0
    share = against / float(obs.volume)
    # A manager who both bought and sold him is genuinely ambiguous;
    # one who ONLY moved him against us is a negative lead.
    return MAX_CONTRADICTION_PENALTY * share * (1.0 if wanted else 1.0)


def _low_sample_penalty(obs: InterestObservation | None) -> float:
    """A single observation is a hint, not a pattern."""
    volume = obs.volume if obs else 0
    if volume >= 3:
        return 0.0
    if volume == 2:
        return MAX_LOW_SAMPLE_PENALTY * 0.4
    if volume == 1:
        return MAX_LOW_SAMPLE_PENALTY * 0.8
    return MAX_LOW_SAMPLE_PENALTY


def positional_need_fit(
    their_roster: partner_model.RosterSignal | None,
    position: str | None,
    *,
    direction: str = "buy",
) -> tuple[float, list[str]]:
    """Does this manager's roster shape want (or want to shed) the
    asset's position?

    Reuses the RosterSignal the roster engine already produces rather
    than recomputing need — only the relative magnitudes are read, so
    the engine's units are not baked in.
    """
    if their_roster is None or not position:
        return 0.0, []
    deficits = their_roster.deficit or {}
    surpluses = their_roster.surplus or {}
    pos = str(position).upper()

    if direction == "buy":
        magnitude = float(deficits.get(pos) or 0.0)
        pool = [float(v) for v in deficits.values() if v]
        label = "needs"
    else:
        magnitude = float(surpluses.get(pos) or 0.0)
        pool = [float(v) for v in surpluses.values() if v]
        label = "is deep at"

    if magnitude <= 0 or not pool:
        return 0.0, []
    # Normalise against their OWN largest gap so a roster with mild
    # needs everywhere does not read as desperate.
    strongest = max(pool)
    fit = magnitude / strongest if strongest > 0 else 0.0
    reasons = []
    if fit >= 0.75:
        reasons.append(
            f"{pos} is one of their biggest {'gaps' if direction == 'buy' else 'surpluses'}"
        )
    elif fit >= 0.4:
        reasons.append(f"Roster {label} {pos}")
    return max(0.0, min(1.0, fit)), reasons


def value_match(
    our_value: float | None,
    their_matchable: Sequence[float] | None,
    *,
    tolerance: float = 0.18,
) -> tuple[float, list[str]]:
    """Can they actually pay?  1.0 when they hold an asset within
    ``tolerance`` of the target's value."""
    if not our_value or our_value <= 0 or not their_matchable:
        return 0.0, []
    best = None
    for v in their_matchable:
        if not v or v <= 0:
            continue
        gap = abs(v - our_value) / our_value
        if best is None or gap < best:
            best = gap
    if best is None:
        return 0.0, []
    if best <= tolerance:
        return 1.0, ["Holds an asset in the same value range"]
    # Degrade smoothly out to 3x tolerance, then nothing.
    span = tolerance * 3.0
    if best >= span:
        return 0.0, []
    return max(0.0, 1.0 - (best - tolerance) / (span - tolerance)), []


def activity_fit(trades_completed: int, league_mean: float | None) -> tuple[float, list[str]]:
    """Do they trade at all?  A manager who never trades is a poor lead
    however well they fit — but volume is capped so churn cannot
    dominate."""
    if trades_completed <= 0:
        return 0.0, []
    mean = float(league_mean) if league_mean and league_mean > 0 else 3.0
    ratio = trades_completed / mean
    score = min(1.0, math.tanh(ratio))
    reasons = []
    if trades_completed >= max(3, int(mean * 1.5)):
        reasons.append(f"Active trader — {trades_completed} trades observed")
    return score, reasons


def score_lead(
    *,
    owner_id: str,
    display_name: str = "",
    interest: InterestObservation | None,
    partner: partner_model.PartnerAssessment | None,
    their_roster: partner_model.RosterSignal | None,
    position: str | None,
    target_value: float | None = None,
    their_matchable_values: Sequence[float] | None = None,
    trades_completed: int = 0,
    league_mean_trades: float | None = None,
    now_ms: int,
    direction: str = "buy",
    owns_asset: bool = False,
) -> Lead:
    """One league-mate's lead score for one asset.

    ``direction="buy"`` = "would they want this from me" (SELL mode).
    ``direction="sell"`` = "would they part with this" (BUY mode).
    """
    lead = Lead(owner_id=owner_id, display_name=display_name, owns_asset=owns_asset)
    lead.interest = interest

    interest_score, interest_reasons, interest_cautions = demonstrated_interest(
        interest, now_ms, direction=direction
    )
    need_score, need_reasons = positional_need_fit(their_roster, position, direction=direction)
    value_score, value_reasons = value_match(target_value, their_matchable_values)
    activity_score, activity_reasons = activity_fit(trades_completed, league_mean_trades)

    # partner fit arrives on a 0-100 display scale whose reachable
    # maximum is deliberately below 50 (see partner.py) — normalise
    # against that reachable range rather than the nominal 100, or the
    # term would silently contribute at most half its weight.
    fit_raw = getattr(partner, "trade_partner_fit_score", None) if partner else None
    reachable_max = getattr(partner_model, "FIT_SCORE_REACHABLE_MAX", 50.0) or 50.0
    fit_score = max(0.0, min(1.0, (fit_raw or 0.0) / reachable_max)) if fit_raw else 0.0

    total = (
        W_DEMONSTRATED_INTEREST * interest_score
        + W_PARTNER_FIT * fit_score
        + W_POSITIONAL_NEED * need_score
        + W_VALUE_MATCH * value_score
        + W_ACTIVITY * activity_score
    )
    contradiction = _contradiction_penalty(interest, direction)
    low_sample = _low_sample_penalty(interest)
    total = max(0.0, total - contradiction - low_sample)

    lead.score = round(total * 100.0, 1)
    lead.components = {
        "demonstratedInterest": W_DEMONSTRATED_INTEREST * interest_score,
        "partnerFit": W_PARTNER_FIT * fit_score,
        "positionalNeed": W_POSITIONAL_NEED * need_score,
        "valueMatch": W_VALUE_MATCH * value_score,
        "activity": W_ACTIVITY * activity_score,
        "contradictionPenalty": -contradiction,
        "lowSamplePenalty": -low_sample,
    }
    lead.reasons = [*interest_reasons, *need_reasons, *value_reasons, *activity_reasons]
    lead.cautions = list(interest_cautions)
    if low_sample >= MAX_LOW_SAMPLE_PENALTY * 0.8:
        lead.cautions.append("Thin evidence — one observation, or none")
    if partner is not None:
        lead.partner_fit = fit_raw
        lead.partner_confidence = getattr(partner, "acceptance_confidence", None)
    return lead


def rank_leads(leads: Sequence[Lead], limit: int | None = None) -> list[Lead]:
    ordered = sorted(
        leads,
        key=lambda x: (
            -x.score,
            -(x.interest.volume if x.interest else 0),
            x.owner_id,
        ),
    )
    return ordered[:limit] if limit else ordered


def describe_limitations() -> dict[str, Any]:
    """Machine-readable statement of what a lead score is NOT.

    Mirrors ``partner.describe_limitations``: a consumer that renders
    this as a probability of acceptance is misusing it, and the model
    says so in its own payload rather than only in a docstring.
    """
    return {
        "isNotAProbability": True,
        "statement": (
            "A lead score ranks who to approach first about a specific asset. "
            "It is not a prediction that anyone will accept: declined offers are "
            "never recorded by Sleeper, so no acceptance rate is identifiable from "
            "this data."
        ),
        "demonstratedInterestIsObservable": (
            "Unlike acceptance, revealed preference IS observable — a manager who "
            "traded for this asset elsewhere committed real assets in public."
        ),
        "coverageCaveat": (
            "Interest is counted only across the leagues this platform has crawled "
            "and within the retention window. Absence of observed interest is not "
            "evidence of disinterest."
        ),
    }
