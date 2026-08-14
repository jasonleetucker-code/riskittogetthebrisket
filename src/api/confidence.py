"""Canonical confidence — the one owner of "how good is the evidence here".

WHAT THIS REPLACES, AND WHY IT COULD NOT BE PATCHED
───────────────────────────────────────────────────
Confidence was decided by ``max(percentile) − min(percentile)`` across a
row's contributing sources, bucketed against two cutoffs, behind an
``n >= 2`` count gate.

A range has a structural pathology: removing an observation can only
preserve or narrow it. Under "narrower ⇒ more confident", **deleting
evidence promotes confidence**. PR #833 recorded the failed repair —
re-basing the same statistic onto independent evidence moved 60 rows the
WRONG way (A.J. Brown medium → high) because collapsing his FantasyPros
family removed one endpoint of the range. The input population was not
the defect. The statistic was.

It was also one axis wearing two hats — a count and a dispersion — and
nothing at all asked whether the evidence was independent, current,
applicable to this board's format, or anywhere near complete. So a large
source count silently compensated for every one of those.

THE REPLACEMENT
───────────────
Five axes, each a statement about the EVIDENCE rather than about the
number, combined by BOTTLENECK — the overall level is the weakest axis.
Nothing averages, so a strong axis cannot buy a weak one, which is the
owner ruling ("a huge source count must not compensate for poor
freshness / applicability / independent-family coverage / severe
disagreement") expressed as arithmetic rather than as a weighting.

    independence   how many B10 correlation-group heads voted
    coverage       how many of the ELIGIBLE families actually did
    freshness      how many of those are inside their staleness budget
    applicability  how many reached the row without approximation, and
                   on this board's TE-premium basis
    agreement      how many price within a material relative gap of the
                   published value

EVERY AXIS IS COMPUTED OVER FAMILY HEADS
────────────────────────────────────────
The unit of evidence is the B10 correlation group, never the source key.
A second observation from an already-represented family is not an input
to anything, so adding or removing one is an exact identity across all
five axes — invariants 1 and 2 discharged structurally rather than by
calibration. ``assess_confidence`` REFUSES a duplicate family rather
than averaging or ignoring it, because both of those are ways for a
duplicate to matter after all.

WHY REMOVING REAL EVIDENCE CANNOT PAY
─────────────────────────────────────
``coverage``'s denominator is what COULD have been observed, not what
was. A family that stops covering a row stays eligible, so its silence
is registered as missing evidence permanently. That is MISSING IS NEVER
ZERO applied to confidence: an absent eligible source is explicit
missingness, not a neutral non-event.

Confidence can still rise when the evidence that went away was STALE or
INAPPLICABLE — the ruling permits exactly that — and in those cases the
reason is in ``reasons``, which is the condition the ruling attaches.

AGREEMENT IS MEASURED IN VALUE SPACE, NOT RANK SPACE
────────────────────────────────────────────────────
A family agrees when its ``valueContribution`` is within a material
relative gap of the published value, using the same symmetric mean
normalisation ``_compute_market_gap`` uses. Value is the right currency
for the same reason it was right there: it is what the blend itself
compares sources in — post-ladder, common-scaled 1-9999, and after
ADR-015's ``convert_te_value``. Percentile space measures pool depth as
much as opinion, and it is where the old statistic's depth pathology
came from (median trimmed spread 0.068 in the top 100 against 0.30 at
ranks 201-400, so a flat cutoff either saturates the deep board or never
fires at the top).

Checked for the opposite bias before adopting: the within-tolerance
share FALLS with depth on the live board (median 1.000 in the top 100,
0.917 at 101-200, 0.750 at 201-800), so it does not become mechanically
easier where the Hill curve flattens.

CONFIDENCE IS NOT VALUE
───────────────────────
Nothing here returns, adjusts or reads back a price. The assessment
carries levels, shares and counts only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "AXES",
    "CONFIDENCE_LEVELS",
    "ConfidenceAssessment",
    "FamilyEvidence",
    "assess_confidence",
    "assess_pick_confidence",
    "gate_parameter",
    "gate_parameters",
]

#: Ordered weakest → strongest. The published ``confidenceBucket`` values.
CONFIDENCE_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high")

#: The axes, in reporting order.
AXES: tuple[str, ...] = (
    "independence",
    "coverage",
    "freshness",
    "applicability",
    "agreement",
)

_LEVEL_INDEX = {name: i for i, name in enumerate(CONFIDENCE_LEVELS)}

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "confidence" / "gate_v1.json"


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def gate_parameters() -> dict[str, dict[str, Any]]:
    """The full parameter entries, including unit and derivation."""
    raw = _document().get("parameters")
    if not isinstance(raw, dict):
        raise ValueError(f"{_CONFIG_PATH} has no 'parameters' object")
    return {str(k): dict(v) for k, v in raw.items() if isinstance(v, dict)}


def gate_parameter(name: str) -> float:
    """One gate parameter by name.

    Raises on an unknown name rather than substituting a default — the
    same rule ``src.api.thresholds.threshold`` follows, for the same
    reason: a silent default gates a decision surface on a number nobody
    chose.
    """
    entries = gate_parameters()
    if name not in entries:
        raise KeyError(f"no confidence gate parameter named {name!r} in {_CONFIG_PATH}")
    return entries[name]["value"]


@dataclass(frozen=True)
class FamilyEvidence:
    """One independent evidence family's contribution to one row.

    Exactly one of these per B10 correlation group. The caller has
    already collapsed families (``collapse_to_independent_families``);
    this type is the boundary at which that is assumed and checked.

    ``fresh`` is tri-state on purpose: ``None`` means the source's age
    could not be observed, which is not the same statement as "current"
    and must never count as one.
    """

    family: str
    source_key: str
    value_contribution: float | None
    fresh: bool | None
    #: False when the observation had to be lifted onto this board's
    #: TE-premium basis by ADR-015's measured conversion curve.
    format_native: bool = True
    #: False when the rank reached this row through an APPROXIMATING
    #: translation — a rookie-ladder lift or a backbone fallback — rather
    #: than the source's own placement.
    directly_observed: bool = True


@dataclass(frozen=True)
class ConfidenceAssessment:
    overall: str
    label: str
    axes: dict[str, str]
    reasons: list[str]
    metrics: dict[str, Any]


def _share_level(share: float | None) -> str:
    """The declared sufficiency ladder, applied to every share axis.

    ``None`` — the share could not be computed — is LOW, never HIGH: an
    unmeasurable axis is not a satisfied one.
    """
    if share is None:
        return "low"
    if share >= gate_parameter("EVIDENCE_SHARE_HIGH"):
        return "high"
    if share >= gate_parameter("EVIDENCE_SHARE_MEDIUM"):
        return "medium"
    return "low"


def _weaken(level: str) -> str:
    """One level down, floored at ``low``.

    Used for the TE-basis penalty, which is a KNOWN correction rather
    than missing evidence: it costs a level, not the axis.
    """
    return CONFIDENCE_LEVELS[max(1, _LEVEL_INDEX[level] - 1)]


def _relative_gap(a: float, b: float) -> float | None:
    """``|a − b|`` over their mean — the board's declared gap convention.

    Identical normalisation to ``_compute_market_gap``, so
    ``AGREEMENT_VALUE_RATIO`` means the same size of disagreement as the
    market-gap thresholds it was set from.
    """
    scale = (a + b) / 2.0
    if scale <= 0:
        return None
    return abs(a - b) / scale


def assess_confidence(
    evidence: Sequence[FamilyEvidence] | Iterable[FamilyEvidence],
    *,
    eligible_families: Iterable[str],
    consensus_value: float | None,
) -> ConfidenceAssessment:
    """Grade the evidence behind one canonical value.

    :param evidence: one entry per INDEPENDENT family head. A repeated
        family raises — see the module docstring.
    :param eligible_families: every family that COULD have covered this
        row (registry scope × non-empty pool). The coverage denominator,
        and the reason removing evidence cannot promote a row.
    :param consensus_value: the published ``rankDerivedValue``. ``None``
        means there is nothing to agree with, which is not agreement.
    """
    heads = list(evidence)
    seen: set[str] = set()
    for item in heads:
        if item.family in seen:
            raise ValueError(
                f"duplicate evidence family {item.family!r} "
                f"(source {item.source_key!r}): confidence consumes B10 family HEADS, "
                "so collapse the family before calling this"
            )
        seen.add(item.family)

    eligible = {str(f) for f in eligible_families}
    n = len(heads)

    metrics: dict[str, Any] = {
        "independentFamilies": n,
        "eligibleFamilies": len(eligible) or None,
        "coveredFamilies": len(seen & eligible) if eligible else None,
        "coverageShare": None,
        "freshFamilies": 0,
        "freshnessShare": None,
        "unknownFreshnessFamilies": 0,
        "directlyObservedFamilies": 0,
        "formatNativeFamilies": 0,
        "applicabilityShare": None,
        "formatNativeShare": None,
        "comparableFamilies": 0,
        "agreeingFamilies": 0,
        "agreementShare": None,
    }

    if n == 0:
        return ConfidenceAssessment(
            overall="none",
            label="None — no evidence",
            axes={axis: "none" for axis in AXES},
            reasons=["No evidence family covers this asset"],
            metrics=metrics,
        )

    reasons: list[str] = []

    # ── independence ──
    high_n = gate_parameter("INDEPENDENCE_HIGH_FAMILIES")
    medium_n = gate_parameter("INDEPENDENCE_MEDIUM_FAMILIES")
    if n >= high_n:
        independence = "high"
    elif n >= medium_n:
        independence = "medium"
    else:
        independence = "low"
    reasons.append(
        f"{n} independent evidence famil{'y' if n == 1 else 'ies'}"
        + ("" if n >= medium_n else " — too few to corroborate")
    )

    # ── coverage ──
    #
    # The denominator is what could have spoken. A family that stopped
    # covering this row is missing evidence for as long as it stays
    # eligible, which is what stops "delete the awkward source" from
    # reading as "the panel now agrees".
    if eligible:
        covered = len(seen & eligible)
        metrics["coverageShare"] = round(covered / len(eligible), 4)
        coverage = _share_level(metrics["coverageShare"])
        if covered < len(eligible):
            reasons.append(f"Covers {covered} of {len(eligible)} eligible evidence families")
    else:
        coverage = "low"
        reasons.append("No eligible evidence families declared for this asset")

    # ── freshness ──
    fresh = sum(1 for e in heads if e.fresh is True)
    unknown = sum(1 for e in heads if e.fresh is None)
    metrics["freshFamilies"] = fresh
    metrics["unknownFreshnessFamilies"] = unknown
    metrics["freshnessShare"] = round(fresh / n, 4)
    freshness = _share_level(metrics["freshnessShare"])
    stale = n - fresh - unknown
    if stale:
        reasons.append(
            f"{stale} of {n} contributing families "
            f"{'is' if stale == 1 else 'are'} past their staleness budget"
        )
    if unknown:
        reasons.append(
            f"{unknown} of {n} contributing families "
            f"{'has' if unknown == 1 else 'have'} unknown freshness"
        )
    if not stale and not unknown:
        reasons.append("All contributing evidence is current")

    # ── applicability ──
    #
    # Two distinct weaknesses, deliberately priced differently:
    #
    #   * an APPROXIMATING translation (rookie ladder, backbone
    #     fallback) is a guess at where the source would have placed the
    #     player — full-strength penalty;
    #   * a BASIS conversion onto this board's TE++ anchor is ADR-015's
    #     measured KTC uplift applied to a real observation — a known
    #     correction, so it costs one level rather than the axis. Not
    #     free either: the curve runs 1.209 at the top of the board to
    #     2.05 down it, so where the player sits changes the number
    #     materially.
    direct = sum(1 for e in heads if e.directly_observed)
    native = sum(1 for e in heads if e.format_native)
    metrics["directlyObservedFamilies"] = direct
    metrics["formatNativeFamilies"] = native
    metrics["applicabilityShare"] = round(direct / n, 4)
    metrics["formatNativeShare"] = round(native / n, 4)
    applicability = _share_level(metrics["applicabilityShare"])
    if direct < n:
        reasons.append(
            f"{n - direct} of {n} famil{'y' if n - direct == 1 else 'ies'} reached this "
            "asset through an approximating translation"
        )
    if metrics["formatNativeShare"] < gate_parameter("EVIDENCE_SHARE_MEDIUM"):
        applicability = _weaken(applicability)
        reasons.append(f"{n - native} of {n} families needed a TE-premium basis conversion")

    # ── agreement ──
    tolerance = gate_parameter("AGREEMENT_VALUE_RATIO")
    if consensus_value is None or float(consensus_value) <= 0:
        agreement = "low"
        reasons.append("No published value to compare the evidence against")
    else:
        center = float(consensus_value)
        comparable = 0
        agreeing = 0
        for e in heads:
            if e.value_contribution is None:
                continue
            gap = _relative_gap(float(e.value_contribution), center)
            if gap is None:
                continue
            comparable += 1
            if gap <= tolerance:
                agreeing += 1
        metrics["comparableFamilies"] = comparable
        metrics["agreeingFamilies"] = agreeing
        # Denominator is every head, not just the comparable ones: a
        # family we cannot compare has not agreed with anything.
        metrics["agreementShare"] = round(agreeing / n, 4)
        agreement = _share_level(metrics["agreementShare"])
        pct = int(round(tolerance * 100))
        if agreeing == n:
            reasons.append(f"All {n} families price within {pct}% of the published value")
        else:
            reasons.append(f"{agreeing} of {n} families price within {pct}% of the published value")

    axes = {
        "independence": independence,
        "coverage": coverage,
        "freshness": freshness,
        "applicability": applicability,
        "agreement": agreement,
    }
    overall = min((axes[a] for a in AXES), key=lambda level: _LEVEL_INDEX[level])
    # Name the BINDING axis — the thing a reader can act on. When every
    # axis sits at the same level there is nothing being held back by
    # anything, and listing all five would read like five complaints.
    binding = [a for a in AXES if axes[a] == overall]
    label = (
        f"{overall.capitalize()} — every axis {overall}"
        if len(binding) == len(AXES)
        else f"{overall.capitalize()} — limited by {', '.join(binding)}"
    )
    return ConfidenceAssessment(
        overall=overall,
        label=label,
        axes=axes,
        reasons=reasons,
        metrics=metrics,
    )


def assess_pick_confidence(
    site_values: dict[str, Any],
    *,
    is_slot_specific: bool,
) -> tuple[str, str]:
    """Pick confidence, with one vote per provider family.

    Picks keep their own coefficient-of-variation statistic — rank
    spread on picks is dominated by the flat-value regions in R3-R6 and
    misleads a player-centric gate — but they must not keep raw-source
    independence assumptions. The value list this reads names both
    ``dlfSf`` and ``dlfIdp``, which are one declared family; two members
    were being counted as two corroborating opinions.

    Measured before changing it: **0 of 144 live pick rows** carry two
    members of one family, so this closes the hole rather than moving a
    number. It is here, and pinned, so it cannot open again quietly.
    """
    # Imported lazily: ``data_contract`` imports this module, so a
    # top-level import would be circular.
    from src.api.data_contract import (
        _compute_pick_confidence,
        _source_precedence,
        correlation_group_for,
    )

    by_family: dict[str, list[str]] = {}
    for key, raw in site_values.items():
        if not isinstance(raw, (int, float)) or float(raw) <= 0:
            continue
        by_family.setdefault(correlation_group_for(str(key)), []).append(str(key))

    superseded = {
        member
        for members in by_family.values()
        if len(members) > 1
        for member in members
        if member != min(members, key=_source_precedence)
    }
    if superseded:
        site_values = {k: v for k, v in site_values.items() if k not in superseded}
    return _compute_pick_confidence(site_values, is_slot_specific=is_slot_specific)
