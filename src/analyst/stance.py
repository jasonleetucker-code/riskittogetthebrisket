"""Analyst stance taxonomy — the one vocabulary for what a take SAYS.

Owner spec: ``docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`` §4.16,
tracked as **T-NEW-10** (`OWNER_REQUESTED_TODO_SPEC_INDEX.md`), status
*REQUIRED METHODOLOGY REFINEMENT*.  This module is that spec made executable;
it invents no category and no weight.

Two vocabularies, deliberately kept apart
─────────────────────────────────────────
``SourceLabel``  what the SOURCE said, in its own words —
                 ``BUY / SELL / HOLD / FADE / BREAKOUT / SLEEPER / STASH /
                 INSUFFICIENT_SIGNAL``.  Retained verbatim so a take can
                 always be shown as the analyst meant it.
``Stance``       the canonical category the platform reasons in — the nine
                 in §4.16.

Both travel together.  Collapsing the source label into the canonical stance
would lose the distinction the owner spent a paragraph protecting: *"SLEEPER
is an undervalued player with a meaningful upside/start case, not merely any
deep bench name."*

THE RULE THIS MODULE EXISTS TO ENFORCE
──────────────────────────────────────
    "STASH must not create false consensus with true conviction BUY calls."

That is enforced STRUCTURALLY rather than by convention.  ``tally`` counts by
:class:`ConvictionClass` and there is no code path that returns a single
"number of buys": speculative interest and conviction are different
quantities, and a caller has to ask for the one it means.  A future Consensus
Edge integration therefore cannot accidentally sum them, because the shape it
receives will not let it.

Nothing here scores, ranks, or weights a take.  Deciding how much a stance
moves a recommendation is evidence-gated and belongs to whatever engine
consumes this — the same posture ``faab_comparability`` takes with its
similarity tiers.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class Stance(str, Enum):
    """The canonical stance categories of owner spec §4.16, in order from
    most bullish to most bearish, with the two non-directional states last.

    ``str`` mixin so a stance serialises as its own name with no adapter —
    a payload field and an enum member are the same token.
    """

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    CONDITIONAL_BUY = "CONDITIONAL_BUY"
    #: STASH / SPECULATIVE BUY.  Interest without conviction.
    STASH = "STASH"
    HOLD = "HOLD"
    CONDITIONAL_SELL = "CONDITIONAL_SELL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"
    #: An answer, not an absence.  "We looked and there is no call here" is
    #: a different statement from "nobody has covered this player", and the
    #: claim schema keeps them apart.
    NO_SIGNAL = "NO_SIGNAL"


class SourceLabel(str, Enum):
    """Subtype labels for analyst extraction (§4.16), preserved as spoken."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    FADE = "FADE"
    BREAKOUT = "BREAKOUT"
    SLEEPER = "SLEEPER"
    STASH = "STASH"
    INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"


class ConvictionClass(str, Enum):
    """How much weight a stance is *entitled* to carry.

    The class — not the stance — is what aggregation groups by, because the
    thing that must never merge is conviction with speculation.
    """

    CONVICTION = "conviction"
    #: Real, but contingent on a stated trigger ("buy only if cheap").
    CONDITIONAL = "conditional"
    #: STASH.  Interest, explicitly not conviction.
    SPECULATIVE = "speculative"
    NEUTRAL = "neutral"
    #: NO_SIGNAL — carries no directional information at all.
    NONE = "none"


class Direction(str, Enum):
    BUY_SIDE = "buy"
    SELL_SIDE = "sell"
    NEITHER = "neither"


#: Stance → (conviction class, direction).  Declared as data so the two
#: properties below cannot drift apart, and so a reader can audit the whole
#: taxonomy in one place.
_STANCE_PROPERTIES: Mapping[Stance, tuple[ConvictionClass, Direction]] = {
    Stance.STRONG_BUY: (ConvictionClass.CONVICTION, Direction.BUY_SIDE),
    Stance.BUY: (ConvictionClass.CONVICTION, Direction.BUY_SIDE),
    Stance.CONDITIONAL_BUY: (ConvictionClass.CONDITIONAL, Direction.BUY_SIDE),
    Stance.STASH: (ConvictionClass.SPECULATIVE, Direction.BUY_SIDE),
    Stance.HOLD: (ConvictionClass.NEUTRAL, Direction.NEITHER),
    Stance.CONDITIONAL_SELL: (ConvictionClass.CONDITIONAL, Direction.SELL_SIDE),
    Stance.SELL: (ConvictionClass.CONVICTION, Direction.SELL_SIDE),
    Stance.STRONG_SELL: (ConvictionClass.CONVICTION, Direction.SELL_SIDE),
    Stance.NO_SIGNAL: (ConvictionClass.NONE, Direction.NEITHER),
}

#: Source label → canonical stance.  A DECLARED translation, not an
#: inference: each line is a decision about what that word means here.
#:
#: ``SLEEPER`` maps to ``BUY`` and NOT to ``STASH``, per §4.16 — a sleeper is
#: "an undervalued player with a meaningful upside/start case, not merely any
#: deep bench name".  The source label rides along so the two remain
#: distinguishable downstream; mapping it to STASH would silently demote a
#: real start-case call, and mapping STASH up to BUY is the exact false
#: consensus the spec forbids.
_LABEL_TO_STANCE: Mapping[SourceLabel, Stance] = {
    SourceLabel.BUY: Stance.BUY,
    SourceLabel.SELL: Stance.SELL,
    SourceLabel.HOLD: Stance.HOLD,
    # A fade is a bearish call on price//usage rather than a "sell your
    # shares" instruction, so it lands on the sell side without conviction
    # inflation.
    SourceLabel.FADE: Stance.CONDITIONAL_SELL,
    SourceLabel.BREAKOUT: Stance.BUY,
    SourceLabel.SLEEPER: Stance.BUY,
    SourceLabel.STASH: Stance.STASH,
    SourceLabel.INSUFFICIENT_SIGNAL: Stance.NO_SIGNAL,
}


def conviction_class(stance: Stance) -> ConvictionClass:
    return _STANCE_PROPERTIES[Stance(stance)][0]


def direction(stance: Stance) -> Direction:
    return _STANCE_PROPERTIES[Stance(stance)][1]


def is_speculative(stance: Stance) -> bool:
    """STASH and only STASH.  Named so callers express the intent rather
    than comparing against a literal."""
    return conviction_class(stance) is ConvictionClass.SPECULATIVE


def requires_condition(stance: Stance) -> bool:
    """Conditional stances are meaningless without their trigger.

    "Buy only if cheap" and "buy" are different claims, and the owner spec
    lists preserving that context as a requirement.  The claim schema refuses
    to build a conditional stance with no stated condition.
    """
    return conviction_class(stance) is ConvictionClass.CONDITIONAL


def stance_for_label(label: SourceLabel) -> Stance:
    """The declared canonical stance for a source's own word."""
    return _LABEL_TO_STANCE[SourceLabel(label)]


@dataclass(frozen=True)
class StanceTally:
    """Counts that CANNOT be added together by accident.

    There is deliberately no ``buys`` property.  A caller that wants "how
    many people are bullish" has to choose whether it means conviction,
    conviction-plus-conditional, or everything including speculation — and
    say so at the call site, where the choice is visible in review.
    """

    by_stance: Mapping[Stance, int]
    by_class: Mapping[ConvictionClass, int]

    def conviction(self, side: Direction) -> int:
        """Conviction-class votes on one side.  The number that may be
        called consensus."""
        return sum(
            n
            for stance, n in self.by_stance.items()
            if direction(stance) is side and conviction_class(stance) is ConvictionClass.CONVICTION
        )

    def speculative(self, side: Direction) -> int:
        """Speculative interest on one side — reported BESIDE conviction,
        never inside it."""
        return sum(
            n
            for stance, n in self.by_stance.items()
            if direction(stance) is side and conviction_class(stance) is ConvictionClass.SPECULATIVE
        )

    def conditional(self, side: Direction) -> int:
        return sum(
            n
            for stance, n in self.by_stance.items()
            if direction(stance) is side and conviction_class(stance) is ConvictionClass.CONDITIONAL
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "byStance": {s.value: n for s, n in sorted(self.by_stance.items())},
            "byClass": {c.value: n for c, n in sorted(self.by_class.items())},
            "convictionBuy": self.conviction(Direction.BUY_SIDE),
            "convictionSell": self.conviction(Direction.SELL_SIDE),
            "conditionalBuy": self.conditional(Direction.BUY_SIDE),
            "conditionalSell": self.conditional(Direction.SELL_SIDE),
            "speculativeBuy": self.speculative(Direction.BUY_SIDE),
        }


def tally(stances: Iterable[Stance]) -> StanceTally:
    """Count stances without ever merging conviction classes.

    Callers are expected to have deduplicated by thesis lineage FIRST — see
    ``src.analyst.claim.independent_claims``.  Counting is not the place to
    discover that the same analyst said the same thing four times.
    """
    by_stance: Counter[Stance] = Counter()
    for raw in stances:
        by_stance[Stance(raw)] += 1
    by_class: Counter[ConvictionClass] = Counter()
    for stance, n in by_stance.items():
        by_class[conviction_class(stance)] += n
    return StanceTally(by_stance=dict(by_stance), by_class=dict(by_class))
