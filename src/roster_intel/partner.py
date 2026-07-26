"""Trade partner fit + acceptance model (WS-J).

Produces, per opposing roster: ``tradePartnerFitScore``,
``tradeAcceptanceEstimate``, ``partnerNeedAlignment``,
``partnerWindowAlignment``, and the first-class ``acceptanceConfidence``.

Pure computation: no I/O, no clock, no globals.

──────────────────────────────────────────────────────────────────────
READ THIS BEFORE TRUSTING ``tradeAcceptanceEstimate``
──────────────────────────────────────────────────────────────────────
**We never observe a rejection.** The league snapshot ingests only
``status == "complete"`` transactions, and an offer a manager declined
in the Sleeper UI leaves no record anywhere. So the dataset contains
the numerator of an acceptance rate (accepted trades) and never the
denominator (offers made).

An acceptance *rate* is therefore **statistically unidentifiable from
this data**, and no amount of modelling fixes that. What this module
emits is not a calibrated accept/reject probability. It is:

    "how plausible is it that an offer of this SHAPE gets engaged
     with, given fairness, roster fit, and window fit"

That is a **plausibility score wearing probability units**, and every
consumer must treat it as such. The field is deliberately named
``tradeAcceptanceEstimate`` — *estimate* — and ships beside
``acceptanceConfidence`` which, under current data, never exceeds
:data:`MAX_CONFIDENCE_WITHOUT_DECISION_DATA`.

**Never render this as "manager X will accept".** See
:func:`describe_limitations` for the machine-readable version of this
paragraph, which is a required deliverable and is asserted by tests.

──────────────────────────────────────────────────────────────────────
Model hierarchy (most-shrunk first)
──────────────────────────────────────────────────────────────────────
Terms accumulate in **log-odds**, each contributing a bounded delta.
Bounded-delta accumulation *is* the shrinkage mechanism: a term cannot
dominate simply by being confident about a large number, and the
ordering below is enforced by the size of the caps, not by convention.

    general plausibility prior      base rate, an ASSUMPTION (§1)
  + market fairness                 ±MAX_FAIRNESS_LOGIT   (strongest)
  + roster fit                      ±MAX_NEED_LOGIT
  + competitive-window fit          ±MAX_WINDOW_LOGIT
  + league-history adjustment       ±MAX_HISTORY_LOGIT    (shrunk hard)
  + manager-specific adjustment     ±MAX_MANAGER_LOGIT    (GATED, §2)

§1 The prior is not measured. With 12 managers and no rejection data
   there is nothing to measure it against, so it is a documented
   assumption (:data:`BASE_ACCEPTANCE_PRIOR`) rather than a fitted
   value, and it is stated as such in the explanation payload.

§2 The manager term is gated by :func:`manager_evidence`, which
   requires **decision** data — accepts *and* rejects. The public
   snapshot supplies only accepts, so the gate does not clear today
   and the term contributes exactly zero. That is the expected
   outcome, not a shortfall: with ~12 managers and single-digit
   trades each, a manager effect estimated from acceptances alone
   would be indistinguishable from noise. The gate is a real branch
   with a real threshold, not a comment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "BASE_ACCEPTANCE_PRIOR",
    "MANAGER_EVIDENCE_MIN_DECISIONS",
    "MANAGER_EVIDENCE_MIN_Z",
    "MAX_CONFIDENCE_WITHOUT_DECISION_DATA",
    "PARTNER_MODEL_VERSION",
    "STRUCTURAL_COVERAGE_FLOOR",
    "AcceptanceEvidence",
    "ManagerEvidence",
    "PartnerAssessment",
    "PartnerInputs",
    "RosterSignal",
    "TradeShape",
    "assess_partner",
    "assess_partners",
    "describe_limitations",
    "manager_evidence",
]

PARTNER_MODEL_VERSION = "wsj.partner.2026-07-27.v1"


# ── Tunables, all named and justified ────────────────────────────────

BASE_ACCEPTANCE_PRIOR = 0.18
"""Prior probability a well-formed, roughly-fair offer gets engaged with.

**An assumption, not a measurement.** No rejection data exists to fit
it against (see module docstring). 0.18 is deliberately pessimistic:
in a 12-team league most offers go nowhere, and a prior that is too
high manufactures false optimism in every downstream ranking. Moving
this constant moves every estimate, which is why it is named, single,
and surfaced in the explanation rather than buried in an expression.
"""

MAX_FAIRNESS_LOGIT = 1.40
"""Market fairness gets the largest budget — it is the only term backed
by a real, per-trade measurement (both sides' market values)."""

MAX_NEED_LOGIT = 0.90
MAX_WINDOW_LOGIT = 0.60
MAX_HISTORY_LOGIT = 0.35
"""League history is shrunk hard: it measures trade ACTIVITY (does this
manager trade at all), which is a propensity proxy and emphatically not
an acceptance rate."""

MAX_MANAGER_LOGIT = 0.50
"""Budget the manager term *would* get if its evidence gate cleared.
Today it never does, so this constant is latent."""

MANAGER_EVIDENCE_MIN_DECISIONS = 30
"""Minimum observed accept/reject DECISIONS for one manager before a
manager-specific term is admissible.

Rationale, not vibes: for a binary outcome the standard error of an
estimated rate is ``sqrt(p(1-p)/n)``. At n=30 and p≈0.2 that is ≈0.073
— i.e. ±7 percentage points, which is the coarsest resolution at which
a manager-specific claim is worth making at all. Below it the estimate
is dominated by sampling noise. At the league's actual volume
(single-digit trades per manager) the SE is ≈±0.2, wider than the
entire effect being claimed.
"""

MANAGER_EVIDENCE_MIN_Z = 2.0
"""Even with enough decisions, the manager's rate must sit at least
this many standard errors from the league mean. Volume alone does not
license a manager term — a manager who behaves exactly like the league
should contribute exactly zero, not a confidently-estimated zero-ish
number."""

MAX_CONFIDENCE_WITHOUT_DECISION_DATA = 0.45
"""Ceiling on ``acceptanceConfidence`` while no rejection data exists.

Confidence tracks EVIDENCE, not the size of the estimate. Without
decision data the model can be internally consistent but cannot be
*calibrated*, so it is capped below the midpoint no matter how clean
the fairness and fit signals look.
"""

STRUCTURAL_COVERAGE_FLOOR = 0.55
"""Confidence multiplier when NONE of the structural terms could be
measured, rising to 1.0 when all three could.

Without this, a partner assessed blind — no roster engine output, so
need and window both silently default to neutral — would carry exactly
the same confidence as one assessed with full roster context, purely
because both landed in the same evidence tier. That is wrong: a
defaulted term is an abstention, not a measurement, and abstentions
must cost confidence or the score launders ignorance into certainty.

The floor is not zero because a measured fairness edge on its own is
still real evidence about the offer; it is just thinner evidence.
"""

_TINY = 1e-9


class AcceptanceEvidence(str, Enum):
    """How well-supported an acceptance estimate is. Weakest first.

    Mirrors the naming and semantics of
    ``league_intel.adjustment.EvidenceTier`` on purpose so the two
    compose later; not imported, because that module lives on another
    workstream's branch and this one must stay dependency-free.
    """

    ABSENT = "absent"
    """No admissible signal. The estimate is the bare prior."""

    SHAPE_ONLY = "shapeOnly"
    """Fairness and/or roster-fit measured from the offer itself. Real
    evidence about the TRADE; none about the MANAGER."""

    HISTORY_INFORMED = "historyInformed"
    """Shape evidence plus league trade-activity context."""

    DECISION_CALIBRATED = "decisionCalibrated"
    """Estimate validated against observed accept/reject decisions.
    **Unreachable** until a source of declined offers exists."""


_EVIDENCE_CONFIDENCE: Mapping[AcceptanceEvidence, float] = {
    AcceptanceEvidence.ABSENT: 0.05,
    AcceptanceEvidence.SHAPE_ONLY: 0.30,
    AcceptanceEvidence.HISTORY_INFORMED: 0.40,
    AcceptanceEvidence.DECISION_CALIBRATED: 0.85,
}


# ── Consumed contracts ───────────────────────────────────────────────
# The roster engine (claude/ws-j-roster-intel) owns production of
# RosterSignal. This module declares the shape it consumes and degrades
# cleanly when it is absent, so the two workstreams can land in either
# order.


@dataclass(frozen=True)
class RosterSignal:
    """What the roster engine tells us about one roster.

    ``surplus`` / ``deficit`` map position → magnitude in whatever
    positive-is-more units the engine emits; only their RELATIVE sizes
    are used here, so the engine's scale is not baked in.

    ``contend_probability`` ∈ [0,1] is the engine's competitive-window
    read: 1.0 = firmly contending, 0.0 = firmly rebuilding.
    """

    owner_id: str
    surplus: Mapping[str, float] = field(default_factory=dict)
    deficit: Mapping[str, float] = field(default_factory=dict)
    contend_probability: float | None = None

    @property
    def has_window(self) -> bool:
        return self.contend_probability is not None


@dataclass(frozen=True)
class TradeShape:
    """The offer being assessed, from OUR side.

    ``send_positions`` / ``receive_positions`` are position → count.
    ``market_value_sent`` / ``market_value_received`` are on ONE market
    scale — the caller is responsible for not mixing KTC and IDPTC
    (audit F-1). ``markets_mixed`` records that the caller could not
    guarantee it; a mixed shape suppresses the fairness term rather
    than trusting an addition with no defined meaning.
    """

    send_positions: Mapping[str, float] = field(default_factory=dict)
    receive_positions: Mapping[str, float] = field(default_factory=dict)
    market_value_sent: float | None = None
    market_value_received: float | None = None
    markets_mixed: bool = False

    @property
    def has_market_values(self) -> bool:
        return (
            not self.markets_mixed
            and self.market_value_sent is not None
            and self.market_value_received is not None
            and self.market_value_sent > 0
            and self.market_value_received > 0
        )


@dataclass(frozen=True)
class ManagerEvidence:
    """Whether a manager-specific term is admissible, and why not."""

    owner_id: str
    admissible: bool
    reason: str
    decisions_observed: int = 0
    accepts_observed: int = 0
    rejects_observed: int = 0
    z_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "admissible": self.admissible,
            "reason": self.reason,
            "decisionsObserved": self.decisions_observed,
            "acceptsObserved": self.accepts_observed,
            "rejectsObserved": self.rejects_observed,
            "zScore": self.z_score,
        }


@dataclass(frozen=True)
class PartnerInputs:
    """Everything needed to assess one opposing roster."""

    owner_id: str
    display_name: str = ""
    our_roster: RosterSignal | None = None
    their_roster: RosterSignal | None = None
    shape: TradeShape | None = None
    #: Completed trades involving this manager (activity, NOT acceptance).
    trades_completed: int = 0
    #: League-wide mean completed trades per manager, for shrinkage.
    league_mean_trades: float | None = None
    #: Completed trades between US and this manager specifically.
    pair_trades_completed: int = 0
    #: ``faab_analytics.teamAggression`` entry, if available. Used only
    #: as a weak engagement proxy — a manager who never spends FAAB is
    #: plausibly less transaction-active. Never as an acceptance rate.
    team_aggression: Mapping[str, Any] | None = None
    #: Observed accept/reject decisions. Populated only if a source of
    #: DECLINED offers ever exists; the public snapshot has none.
    decisions_accepted: int | None = None
    decisions_rejected: int | None = None


@dataclass(frozen=True)
class PartnerAssessment:
    """Per-partner output. All scores in [0,1] unless noted."""

    owner_id: str
    display_name: str
    trade_partner_fit_score: float  # 0..100, the RANKING quantity
    trade_acceptance_estimate: float
    partner_need_alignment: float
    partner_window_alignment: float
    acceptance_confidence: float
    evidence: AcceptanceEvidence
    manager_evidence: ManagerEvidence
    contributions: Mapping[str, float] = field(default_factory=dict)
    notes: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ownerId": self.owner_id,
            "displayName": self.display_name,
            "tradePartnerFitScore": round(self.trade_partner_fit_score, 2),
            "tradeAcceptanceEstimate": round(self.trade_acceptance_estimate, 4),
            "partnerNeedAlignment": round(self.partner_need_alignment, 4),
            "partnerWindowAlignment": round(self.partner_window_alignment, 4),
            "acceptanceConfidence": round(self.acceptance_confidence, 4),
            "evidence": self.evidence.value,
            "managerEvidence": self.manager_evidence.to_dict(),
            "contributions": {k: round(v, 4) for k, v in sorted(self.contributions.items())},
            "notes": list(self.notes),
            "modelVersion": PARTNER_MODEL_VERSION,
        }


# ── helpers ──────────────────────────────────────────────────────────
def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _logit(p: float) -> float:
    p = _clamp(p, _TINY, 1.0 - _TINY)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# ── term: market fairness ────────────────────────────────────────────
def _fairness_term(shape: TradeShape | None) -> tuple[float, str | None]:
    """Log-odds delta from how the offer prices out for THEM.

    Positive when the partner receives more market value than they send
    — an offer that favours them is more likely to be engaged with.
    Saturating so a wildly lopsided gift does not run away to certainty:
    a 100% overpay is implausible for reasons this model cannot see
    (collusion optics, roster space, the partner smelling a rat).
    """
    if shape is None:
        return 0.0, "no trade shape supplied — fairness term inert"
    if not shape.has_market_values:
        if shape.markets_mixed:
            return 0.0, (
                "package mixes offense and IDP markets; per audit F-1 there is no "
                "validated cross-market normalization, so the fairness term is "
                "suppressed rather than computed from an undefined sum"
            )
        return 0.0, "market values unavailable — fairness term inert"

    sent = float(shape.market_value_sent or 0.0)
    received = float(shape.market_value_received or 0.0)
    # From the PARTNER's perspective: they receive what we send.
    partner_gets = sent
    partner_gives = received
    denom = max(partner_gets + partner_gives, _TINY)
    # Normalised edge in [-1, 1]; +1 = they get everything for nothing.
    edge = (partner_gets - partner_gives) / denom
    return MAX_FAIRNESS_LOGIT * math.tanh(2.0 * edge), None


# ── term: roster need alignment ──────────────────────────────────────
def _need_alignment(
    ours: RosterSignal | None, theirs: RosterSignal | None, shape: TradeShape | None
) -> tuple[float, str | None]:
    """Fraction of what we send that lands on a position they lack.

    Complementarity, not charity: we only get credit where OUR surplus
    meets THEIR deficit. Returns a 0..1 alignment score.
    """
    if theirs is None:
        return 0.5, "roster engine output unavailable — need alignment defaults to neutral"
    if not theirs.deficit:
        return 0.5, "partner shows no positional deficit — need alignment neutral"

    sending = dict(shape.send_positions) if shape and shape.send_positions else {}
    if not sending and ours is not None and ours.surplus:
        # No concrete package: score the STANDING complementarity of the
        # two rosters instead, which is what a partner-ranking view wants
        # before any specific offer exists.
        sending = dict(ours.surplus)
    if not sending:
        return 0.5, "nothing to match against partner deficit — neutral"

    total = sum(max(0.0, v) for v in sending.values())
    if total <= 0:
        return 0.5, "no positive send-side weight — neutral"

    deficit_total = sum(max(0.0, v) for v in theirs.deficit.values()) or 1.0
    matched = 0.0
    for pos, weight in sending.items():
        w = max(0.0, float(weight))
        if w <= 0:
            continue
        need = max(0.0, float(theirs.deficit.get(pos, 0.0)))
        matched += w * (need / deficit_total)
    # matched/total is in [0,1] but concentrated low; rescale so a
    # perfectly-targeted package reads as ~1.0.
    raw = matched / total
    peak = max(max(0.0, float(v)) for v in theirs.deficit.values()) / deficit_total
    if peak <= 0:
        return 0.5, "partner deficit has no positive mass — neutral"
    return _clamp(raw / peak, 0.0, 1.0), None


# ── term: competitive-window alignment ───────────────────────────────
def _window_alignment(
    ours: RosterSignal | None, theirs: RosterSignal | None
) -> tuple[float, str | None]:
    """Do our windows point in useful opposite directions?

    A contender and a rebuilder are natural counterparties; two teams in
    the same phase compete for the same assets. 1.0 = maximally
    complementary, 0.0 = identical windows.
    """
    if theirs is None or not theirs.has_window:
        return 0.5, "partner window probability unavailable — window alignment neutral"
    if ours is None or not ours.has_window:
        return 0.5, "our window probability unavailable — window alignment neutral"
    gap = abs(float(ours.contend_probability or 0.0) - float(theirs.contend_probability or 0.0))
    return _clamp(gap, 0.0, 1.0), None


# ── term: league history (activity, shrunk) ──────────────────────────
def _history_term(inp: PartnerInputs) -> tuple[float, str | None]:
    """Shrunk log-odds delta from observed trade ACTIVITY.

    This is not an acceptance rate and is never treated as one — it
    only says "this manager transacts more/less than the league".
    Shrinkage is an explicit James-Stein-flavoured pull toward the
    league mean with a small prior sample size, so a manager with two
    trades barely moves off the mean.
    """
    if inp.league_mean_trades is None:
        return 0.0, "no league trade baseline — history term inert"
    mean = max(0.0, float(inp.league_mean_trades))
    observed = max(0, int(inp.trades_completed))
    # Shrink toward the mean: with PRIOR_N pseudo-observations at the
    # league mean, a manager needs real volume to move.
    prior_n = 5.0
    shrunk = (observed + prior_n * mean) / (1.0 + prior_n)
    if mean <= 0:
        return 0.0, "league mean trade count is zero — history term inert"
    ratio = shrunk / mean
    # log ratio, saturating, scaled into the small history budget.
    delta = MAX_HISTORY_LOGIT * math.tanh(math.log(max(ratio, _TINY)))
    return delta, None


# ── the manager gate ─────────────────────────────────────────────────
def manager_evidence(inp: PartnerInputs) -> ManagerEvidence:
    """Is a manager-specific term admissible for this owner?

    **This is the gate.** Two conditions, both required:

    1. ``decisions_observed >= MANAGER_EVIDENCE_MIN_DECISIONS`` — where
       a *decision* is an offer this manager accepted **or rejected**.
       Completed trades alone are not decisions: they are the accepted
       arm only, with no denominator.
    2. ``|z| >= MANAGER_EVIDENCE_MIN_Z`` against the league mean, so
       volume alone cannot license a term for a manager who behaves
       exactly like everyone else.

    Under the current data the first condition is **structurally
    unsatisfiable**: the snapshot ingests only ``status == "complete"``
    transactions, and declined offers are not recorded anywhere. The
    gate therefore reports ``admissible=False`` with a reason naming
    the missing input, and the manager term contributes exactly zero.
    """
    accepted = inp.decisions_accepted
    rejected = inp.decisions_rejected

    if accepted is None or rejected is None:
        return ManagerEvidence(
            owner_id=inp.owner_id,
            admissible=False,
            reason=(
                "no decision data: the league snapshot records only completed "
                "trades, so rejections are unobserved and an acceptance rate is "
                "unidentifiable. Manager-specific term contributes zero."
            ),
            accepts_observed=int(inp.trades_completed),
        )

    decisions = int(accepted) + int(rejected)
    if decisions < MANAGER_EVIDENCE_MIN_DECISIONS:
        return ManagerEvidence(
            owner_id=inp.owner_id,
            admissible=False,
            reason=(
                f"only {decisions} observed decisions; "
                f"{MANAGER_EVIDENCE_MIN_DECISIONS} required before a "
                "manager-specific rate is distinguishable from sampling noise"
            ),
            decisions_observed=decisions,
            accepts_observed=int(accepted),
            rejects_observed=int(rejected),
        )

    rate = accepted / decisions
    baseline = BASE_ACCEPTANCE_PRIOR
    se = math.sqrt(max(baseline * (1.0 - baseline) / decisions, _TINY))
    z = (rate - baseline) / se
    if abs(z) < MANAGER_EVIDENCE_MIN_Z:
        return ManagerEvidence(
            owner_id=inp.owner_id,
            admissible=False,
            reason=(
                f"manager rate {rate:.2f} is {abs(z):.2f} SE from the league "
                f"baseline; {MANAGER_EVIDENCE_MIN_Z} required — behaves like "
                "the league, so no manager-specific term is warranted"
            ),
            decisions_observed=decisions,
            accepts_observed=int(accepted),
            rejects_observed=int(rejected),
            z_score=z,
        )

    return ManagerEvidence(
        owner_id=inp.owner_id,
        admissible=True,
        reason=(
            f"{decisions} decisions, rate {rate:.2f} at {abs(z):.2f} SE from "
            "baseline — manager-specific term admissible"
        ),
        decisions_observed=decisions,
        accepts_observed=int(accepted),
        rejects_observed=int(rejected),
        z_score=z,
    )


def _manager_term(ev: ManagerEvidence) -> float:
    """Log-odds delta from the manager term. Zero unless the gate cleared."""
    if not ev.admissible or ev.z_score is None:
        return 0.0
    # Bounded by the manager budget; tanh keeps an extreme z from
    # swamping the fairness signal.
    return MAX_MANAGER_LOGIT * math.tanh(ev.z_score / 4.0)


# ── assembly ─────────────────────────────────────────────────────────
def assess_partner(inp: PartnerInputs) -> PartnerAssessment:
    """Assess one opposing roster. Pure."""
    notes: list[str] = []

    fairness, fairness_note = _fairness_term(inp.shape)
    if fairness_note:
        notes.append(fairness_note)

    need, need_note = _need_alignment(inp.our_roster, inp.their_roster, inp.shape)
    if need_note:
        notes.append(need_note)

    window, window_note = _window_alignment(inp.our_roster, inp.their_roster)
    if window_note:
        notes.append(window_note)

    history, history_note = _history_term(inp)
    if history_note:
        notes.append(history_note)

    ev = manager_evidence(inp)
    manager = _manager_term(ev)
    if not ev.admissible:
        notes.append(f"manager term inert: {ev.reason}")

    # Alignment scores are 0..1 centred at 0.5; convert to a signed
    # contribution so a genuinely poor fit can push the estimate DOWN.
    need_logit = MAX_NEED_LOGIT * (2.0 * need - 1.0)
    window_logit = MAX_WINDOW_LOGIT * (2.0 * window - 1.0)

    total = _logit(BASE_ACCEPTANCE_PRIOR) + fairness + need_logit + window_logit + history + manager
    estimate = _sigmoid(total)

    # ── evidence tier + confidence ───────────────────────────────────
    # Tier keys on whether a term could be MEASURED, never on how large
    # its contribution turned out to be. A perfectly balanced offer
    # yields a fairness delta of exactly 0.0 and a league-average
    # manager yields a history delta of exactly 0.0 — both are real
    # measurements that happen to say "no adjustment", and treating
    # them as absent evidence would penalise the cleanest cases.
    # Each term returns a note iff it abstained.
    if ev.admissible:
        tier = AcceptanceEvidence.DECISION_CALIBRATED
    elif history_note is None:
        tier = AcceptanceEvidence.HISTORY_INFORMED
    elif fairness_note is None or need_note is None or window_note is None:
        tier = AcceptanceEvidence.SHAPE_ONLY
    else:
        tier = AcceptanceEvidence.ABSENT

    confidence = _EVIDENCE_CONFIDENCE[tier]

    # Structural coverage: how many of the three per-offer terms were
    # actually MEASURED rather than defaulted to neutral. Each term
    # returns a note iff it abstained, so this counts real signal.
    measured = sum(1 for note in (fairness_note, need_note, window_note) if note is None)
    coverage = measured / 3.0
    confidence *= STRUCTURAL_COVERAGE_FLOOR + (1.0 - STRUCTURAL_COVERAGE_FLOOR) * coverage
    if measured < 3:
        notes.append(
            f"structural coverage {measured}/3: confidence reduced because "
            "one or more of fairness, roster fit and window fit had to "
            "abstain rather than measure"
        )

    if tier is not AcceptanceEvidence.DECISION_CALIBRATED:
        bound = confidence > MAX_CONFIDENCE_WITHOUT_DECISION_DATA
        confidence = min(confidence, MAX_CONFIDENCE_WITHOUT_DECISION_DATA)
        notes.append(
            (
                "acceptanceConfidence capped at " f"{MAX_CONFIDENCE_WITHOUT_DECISION_DATA}: "
                if bound
                else f"acceptanceConfidence held under {MAX_CONFIDENCE_WITHOUT_DECISION_DATA}: "
            )
            + "no rejection data exists, so this estimate is a plausibility "
            "score in probability units, not a calibrated acceptance probability"
        )

    # ── the ranking quantity ─────────────────────────────────────────
    # Confidence is NOT decoration: it multiplies. A high-looking
    # estimate built on thin evidence must rank below a moderate
    # estimate built on real signal, which is exactly what shrinking
    # toward the prior by (1 - confidence) achieves.
    anchored = BASE_ACCEPTANCE_PRIOR + confidence * (estimate - BASE_ACCEPTANCE_PRIOR)
    structural = 0.5 * (need + window)
    fit_score = 100.0 * _clamp(0.65 * anchored + 0.35 * structural * confidence, 0.0, 1.0)

    return PartnerAssessment(
        owner_id=inp.owner_id,
        display_name=inp.display_name or inp.owner_id,
        trade_partner_fit_score=fit_score,
        trade_acceptance_estimate=estimate,
        partner_need_alignment=need,
        partner_window_alignment=window,
        acceptance_confidence=confidence,
        evidence=tier,
        manager_evidence=ev,
        contributions={
            "prior": _logit(BASE_ACCEPTANCE_PRIOR),
            "marketFairness": fairness,
            "rosterFit": need_logit,
            "windowFit": window_logit,
            "leagueHistory": history,
            "managerSpecific": manager,
        },
        notes=tuple(notes),
    )


def assess_partners(inputs: Iterable[PartnerInputs]) -> list[PartnerAssessment]:
    """Assess many partners, ranked by fit score descending.

    Ranking uses ``tradePartnerFitScore``, which already carries the
    confidence penalty — so a confidently-mediocre partner outranks a
    speculatively-attractive one, by construction.
    """
    out = [assess_partner(i) for i in inputs]
    out.sort(key=lambda a: (-a.trade_partner_fit_score, a.owner_id))
    return out


def describe_limitations() -> dict[str, Any]:
    """Machine-readable limitations of the acceptance model.

    Required deliverable of the WS-J directive, and asserted by tests so
    it cannot silently drift away from the model's real behaviour. Any
    surface that renders ``tradeAcceptanceEstimate`` should render this
    alongside it.
    """
    return {
        "modelVersion": PARTNER_MODEL_VERSION,
        "canSupport": [
            "Ranking opposing rosters by structural trade fit (positional "
            "complementarity and competitive-window opposition).",
            "Flagging offers that are implausible on market fairness grounds.",
            "Stating, with an auditable reason, why a manager-specific term " "was not applied.",
            "Relative comparison between partners assessed under identical " "assumptions.",
        ],
        "cannotSupport": [
            "Any claim that a specific manager will accept a specific trade.",
            "A calibrated acceptance PROBABILITY: rejections are never "
            "observed, so the rate is statistically unidentifiable.",
            "Manager-specific behavioural effects: the evidence gate requires "
            f"{MANAGER_EVIDENCE_MIN_DECISIONS} accept/reject decisions and the "
            "available data supplies zero rejections.",
            "Absolute probability calibration of any kind — only the ordering "
            "of partners is meaningful.",
            "Cross-market (offense+IDP) fairness, pending audit F-1's " "normalization work.",
        ],
        "keyAssumptions": {
            "baseAcceptancePrior": BASE_ACCEPTANCE_PRIOR,
            "baseAcceptancePriorIsMeasured": False,
            "baseAcceptancePriorNote": (
                "Assumed, not fitted. Nothing in the available data can "
                "estimate a base acceptance rate."
            ),
        },
        "confidenceCeiling": MAX_CONFIDENCE_WITHOUT_DECISION_DATA,
        "confidenceCeilingReason": (
            "No decision data exists, so the model can be internally "
            "consistent but not calibrated."
        ),
        "structuralCoverageFloor": STRUCTURAL_COVERAGE_FLOOR,
        "structuralCoverageNote": (
            "Confidence is additionally reduced when fairness, roster fit or "
            "window fit had to abstain instead of measure, so a partner "
            "assessed blind never scores as though it were assessed fully."
        ),
        "whatWouldUnlockMore": [
            "A record of DECLINED offers — the single highest-value missing "
            "input; it converts the estimate from plausibility to a "
            "calibratable rate.",
            "Cross-league decision data from src/intel/ if it ever captures "
            "offers rather than only completed trades.",
            "A validated offense/IDP market normalization (audit F-1), which "
            "would let mixed packages use the fairness term at all.",
        ],
    }
