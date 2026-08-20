"""The one function that decides a BUY/SELL/HOLD-class verdict (C6-SIG-01).

See ``src.signals`` for the package-level design rationale. This module
is deliberately small: precedence, axis-bottleneck confidence, and the
magnitude ladder. Evidence EXTRACTION (turning a raw upstream payload
into a :class:`SignalFamilyEvidence`) lives in ``src.signals.families``,
kept separate so this module never has to know the shape of BDVM's or
Sharp's output.

VOCABULARY IS REUSED, NOT REINVENTED
──────────────────────────────────────
``src.analyst.stance`` already IS the owner-approved canonical vocabulary
(§4.16 of ``docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md``,
including the structural "STASH cannot merge into conviction BUY"
guarantee this reconciler's own precedence chain depends on). This
module imports :class:`~src.analyst.stance.Stance` and
:class:`~src.analyst.stance.Direction` rather than declaring a second,
parallel enum for the same nine categories -- exactly the duplication
ONE CONCEPT, ONE CANONICAL OWNER forbids, and the trap
``src/analyst/__init__.py``'s own docstring names by example (a module
that claims a vocabulary and drifts from it is worse than one that
never claimed it).

``Verdict`` therefore has ELEVEN reachable values: the nine
:class:`Stance` members, plus two states that are not analyst stances at
all -- ``CONFLICTED`` and ``WITHHELD`` describe whether a stance could be
formed, not what it says, so they stay outside the ``Stance`` enum on
purpose. ``Stance.NO_SIGNAL`` is NOT reused for the zero-evidence case:
its own docstring means "we looked and there is no call here", a
confident negative, whereas "no eligible family had ANY opinion" is
closer to the true-absence case that docstring explicitly distinguishes
itself from -- so that case is a third non-``Stance`` value,
``INSUFFICIENT_EVIDENCE``. ``Stance.CONDITIONAL_BUY``/``CONDITIONAL_SELL``
are reserved but unreachable in v1: they need roster/price context that
belongs to the Trade Intelligence lane, not this reconciler.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Union

from src.analyst.stance import Direction, Stance

__all__ = [
    "KNOWN_FAMILIES",
    "ConfidenceLevel",
    "Direction",
    "ReconciledVerdict",
    "SignalFamilyEvidence",
    "Stance",
    "Verdict",
    "gate_parameter",
    "gate_parameters",
    "reconcile_row",
]

#: Every family this reconciler's precedence/confidence logic knows about,
#: including the reserved slot that never fires in v1. Used as the
#: ``eligibleFamilies``/coverage denominator so coverage is honestly
#: capped below 1.0 until Consensus Edge is genuinely wired -- see
#: ``config/signals/reconciler_v1.json``'s ``EVIDENCE_SHARE_HIGH`` entry.
KNOWN_FAMILIES: tuple[str, ...] = (
    "board_consensus_gap",
    "bdvm_fundamental",
    "sharp_transaction",
    "consensus_edge_composite",
)

ConfidenceLevel = Literal["none", "low", "medium", "high"]

#: Reconciler-only meta-states -- see the module docstring for why these
#: three are not ``Stance`` members.
_MetaVerdict = Literal["CONFLICTED", "WITHHELD", "INSUFFICIENT_EVIDENCE"]
Verdict = Union[Stance, _MetaVerdict]

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "signals" / "reconciler_v1.json"


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def gate_parameters() -> dict[str, dict[str, Any]]:
    """The full parameter entries, including unit and derivation."""
    raw = _document().get("parameters")
    if not isinstance(raw, dict):
        raise ValueError(f"{_CONFIG_PATH} has no 'parameters' object")
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def gate_parameter(name: str) -> Any:
    """One gate parameter's value by name.

    Raises on an unknown name rather than substituting a default --
    the same rule ``src.api.confidence.gate_parameter`` follows, for
    the same reason: a silent default gates a verdict on a number
    nobody chose.
    """
    entries = gate_parameters()
    if name not in entries:
        raise KeyError(f"no signal reconciler parameter named {name!r} in {_CONFIG_PATH}")
    return entries[name]["value"]


@dataclass(frozen=True)
class SignalFamilyEvidence:
    """One independent evidence family's contribution to one asset's verdict.

    Deliberately NOT ``src.api.confidence.FamilyEvidence`` and does not
    import it -- see the "ONE CONCEPT, ONE CANONICAL OWNER" note in
    ``src.signals.__init__``. Shaped the same way on purpose: this is a
    second, sibling application of the same family-head discipline, not
    a fork of a different one.

    ``magnitude`` is normalized to 0..1 per family by the extractors in
    ``src.signals.families`` -- see ``config/signals/reconciler_v1.json``
    for how each family's raw units map onto this shared scale.

    ``fresh`` is tri-state on purpose: ``None`` means this family's age
    could not be observed, which is not the same statement as "current"
    and must never count as one (mirrors ``FamilyEvidence.fresh`` in
    ``src.api.confidence``).
    """

    family: str
    direction: Direction
    magnitude: float
    family_confidence: Literal["high", "medium", "low", "insufficient"]
    fresh: bool | None
    provenance: dict[str, Any]


@dataclass(frozen=True)
class ReconciledVerdict:
    verdict: Verdict
    reason: str
    confidenceBucket: ConfidenceLevel
    confidenceAxes: dict[str, str]
    families: list[dict[str, Any]]
    eligibleFamilies: list[str]
    sharedAnchors: list[str]
    provenance: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _share_level(share: float | None) -> str:
    """The declared sufficiency ladder (reused verbatim from
    ``src.api.confidence._share_level``'s thresholds -- see
    ``EVIDENCE_SHARE_HIGH``/``EVIDENCE_SHARE_MEDIUM`` in
    ``config/signals/reconciler_v1.json``), applied to a share axis.

    ``None`` -- the share could not be computed -- is LOW, never HIGH.
    """
    if share is None:
        return "low"
    if share >= gate_parameter("EVIDENCE_SHARE_HIGH"):
        return "high"
    if share >= gate_parameter("EVIDENCE_SHARE_MEDIUM"):
        return "medium"
    return "low"


def _independence_level(fired_count: int) -> str:
    if fired_count >= gate_parameter("INDEPENDENCE_HIGH_FAMILIES"):
        return "high"
    if fired_count >= gate_parameter("INDEPENDENCE_MEDIUM_FAMILIES"):
        return "medium"
    return "low"


_LEVEL_INDEX = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _bottleneck(*levels: str) -> str:
    return min(levels, key=lambda lvl: _LEVEL_INDEX.get(lvl, 0))


def reconcile_row(
    *,
    contract_row: dict[str, Any] | None = None,
    families: list[SignalFamilyEvidence] | None = None,
    quarantined: bool = False,
) -> ReconciledVerdict:
    """Decide ONE verdict from independently-declared evidence families.

    Pure: reads its arguments, returns a value. Never mutates
    ``contract_row``, never touches a league, never triggers an action
    -- recommendations and execution stay separate per CLAUDE.md §3.6.

    :param contract_row: the canonical ``/api/data`` row, used only to
        read ``confidenceBasis`` for the quarantine check when
        ``quarantined`` is not passed explicitly by the caller.
    :param families: the evidence already extracted by
        ``src.signals.families`` for this asset -- at most one entry
        per family name (a duplicate family name raises, mirroring
        ``src.api.confidence.assess_confidence``'s family-head rule).
    :param quarantined: pass explicitly to skip reading ``contract_row``.
        Precedence: an explicitly quarantined row is always WITHHELD,
        whatever its evidence says -- matching
        ``src.consensus_edge.score.classify``'s own first-check
        precedence, so when Consensus Edge is wired as a live family its
        own WITHHELD verdict becomes an ADDITIONAL trigger of this same
        branch rather than a new code path.
    """
    families = list(families or [])
    seen_families = set()
    for ev in families:
        if ev.family in seen_families:
            raise ValueError(
                f"duplicate evidence family {ev.family!r} passed to reconcile_row -- "
                "the caller must collapse to one entry per family before calling"
            )
        seen_families.add(ev.family)

    is_quarantined = quarantined
    if not is_quarantined and contract_row is not None:
        is_quarantined = contract_row.get("confidenceBasis") == "quarantine_degraded"

    eligible = list(KNOWN_FAMILIES)

    if is_quarantined:
        return ReconciledVerdict(
            verdict="WITHHELD",  # meta-state, not a Stance — see module docstring
            reason="Row is quarantined for identity/data-quality reasons; no verdict is published.",
            confidenceBucket="none",
            confidenceAxes={axis: "none" for axis in ("independence", "coverage", "freshness", "agreement")},
            families=[],
            eligibleFamilies=eligible,
            sharedAnchors=[],
            provenance={"precedence": "quarantine_withheld"},
        )

    if not families:
        return ReconciledVerdict(
            verdict="INSUFFICIENT_EVIDENCE",  # meta-state, not Stance.NO_SIGNAL — see module docstring
            reason="No eligible evidence family had an opinion on this asset.",
            confidenceBucket="none",
            confidenceAxes={axis: "none" for axis in ("independence", "coverage", "freshness", "agreement")},
            families=[],
            eligibleFamilies=eligible,
            sharedAnchors=[],
            provenance={"precedence": "no_evidence"},
        )

    floor = gate_parameter("MATERIAL_MAGNITUDE_FLOOR")
    material = [ev for ev in families if ev.magnitude >= floor]
    buy_material = [ev for ev in material if ev.direction == Direction.BUY_SIDE]
    sell_material = [ev for ev in material if ev.direction == Direction.SELL_SIDE]

    shared_anchors = sorted(
        {
            anchor
            for ev in families
            for anchor in (ev.provenance.get("sharedAnchors") or [])
        }
    )

    if buy_material and sell_material:
        # CONFLICTED — a deliberate extension beyond the owner's 9-value
        # vocabulary. The alternative is silently averaging opposed
        # evidence into a false HOLD, which src.consensus_edge.score's
        # own docstring names as the top-line anti-pattern this
        # reconciler exists to avoid. Flagged in
        # docs/lane4/C6_SIG_01_RECONCILER.md for explicit owner sign-off
        # rather than picked silently.
        axes = {
            "independence": _independence_level(len(families)),
            "coverage": _share_level(len(families) / len(eligible)),
            "freshness": _share_level(
                sum(1 for e in families if e.fresh is True) / len(families)
            ),
            "agreement": "low",  # by definition — the evidence disagrees
        }
        return ReconciledVerdict(
            verdict="CONFLICTED",  # meta-state, not a Stance — see module docstring
            reason=(
                f"{len(buy_material)} famil{'y' if len(buy_material) == 1 else 'ies'} "
                f"lean BUY, {len(sell_material)} lean SELL, both above the material "
                "magnitude floor — not averaged into a false HOLD."
            ),
            confidenceBucket=_bottleneck(*axes.values()),
            confidenceAxes=axes,
            families=[asdict(ev) for ev in families],
            eligibleFamilies=eligible,
            sharedAnchors=shared_anchors,
            provenance={"precedence": "conflicted", "buyFamilies": [e.family for e in buy_material], "sellFamilies": [e.family for e in sell_material]},
        )

    majority = buy_material or sell_material
    if not majority:
        # Every family fired below the material-magnitude floor — real
        # evidence exists but none of it clears the noise band.
        axes = {
            "independence": _independence_level(len(families)),
            "coverage": _share_level(len(families) / len(eligible)),
            "freshness": _share_level(
                sum(1 for e in families if e.fresh is True) / len(families)
            ),
            "agreement": _share_level(1.0),
        }
        return ReconciledVerdict(
            verdict=Stance.HOLD,
            reason="Evidence present but below the material-magnitude floor on every family.",
            confidenceBucket=_bottleneck(*axes.values()),
            confidenceAxes=axes,
            families=[asdict(ev) for ev in families],
            eligibleFamilies=eligible,
            sharedAnchors=shared_anchors,
            provenance={"precedence": "sub_material"},
        )

    direction: Direction = majority[0].direction
    agreeing = sum(1 for e in families if e.direction == direction)
    axes = {
        "independence": _independence_level(len(majority)),
        "coverage": _share_level(len(families) / len(eligible)),
        "freshness": _share_level(
            sum(1 for e in majority if e.fresh is True) / len(majority)
        ),
        "agreement": _share_level(agreeing / len(families)),
    }
    confidence = _bottleneck(*axes.values())
    composite_magnitude = sum(e.magnitude for e in majority) / len(majority)
    is_buy = direction == Direction.BUY_SIDE

    if composite_magnitude >= gate_parameter("STRONG_MAGNITUDE_THRESHOLD") and confidence in (
        "medium",
        "high",
    ):
        verdict: Verdict = Stance.STRONG_BUY if is_buy else Stance.STRONG_SELL
    else:
        verdict = Stance.BUY if is_buy else Stance.SELL

    if is_buy and _LEVEL_INDEX[confidence] <= _LEVEL_INDEX[gate_parameter("STASH_CONFIDENCE_CEILING")]:
        # STASH rule (owner spec 2026-08-13): genuine but thin/undiversified
        # BUY-leaning evidence must not publish as a confident acquisition
        # target — src.analyst.stance's own structural guarantee ("STASH
        # cannot merge into conviction BUY"), applied here rather than
        # re-invented.
        verdict = Stance.STASH

    reason = (
        f"{len(majority)} of {len(families)} families lean {direction.value.upper()}, "
        f"composite magnitude {composite_magnitude:.2f}, confidence {confidence}."
    )

    return ReconciledVerdict(
        verdict=verdict,
        reason=reason,
        confidenceBucket=confidence,
        confidenceAxes=axes,
        families=[asdict(ev) for ev in families],
        eligibleFamilies=eligible,
        sharedAnchors=shared_anchors,
        provenance={
            "precedence": "magnitude_ladder",
            "compositeMagnitude": round(composite_magnitude, 4),
            "majorityDirection": direction.value,
        },
    )
