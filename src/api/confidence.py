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
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

__all__ = [
    "AXES",
    "CONFIDENCE_BASES",
    "CONFIDENCE_LEVELS",
    "ConfidenceAssessment",
    "FamilyEvidence",
    "assess_confidence",
    "assess_pick_confidence",
    "degrade_for_quarantine",
    "pick_evidence",
    "gate_parameter",
    "gate_parameters",
    "unassessed_defaults",
]

#: Ordered weakest → strongest. The published ``confidenceBucket`` values.
#:
#: **Exactly four, deliberately.** The overall level is the WEAKEST axis, so
#: widening this tuple changes what the bottleneck ``min()`` means for every
#: axis at once. C1-U5 adds a second, ORTHOGONAL field (``confidenceBasis``,
#: below) rather than a fifth level, because the thing that was missing was
#: never a degree of confidence — it was *which owner decided it, from what
#: class of evidence*.
CONFIDENCE_LEVELS: tuple[str, ...] = ("none", "low", "medium", "high")

#: What produced a row's ``confidenceBucket``. Closed set, always published.
#:
#: ``confidenceBucket`` answers "how good is the evidence"; ``confidenceBasis``
#: answers "what kind of evidence, decided by whom". Before C1-U5 the bucket
#: ``"none"`` was published for four incompatible states at once — measured on
#: the 2026-08-17 board: 24 priced-but-never-assessed rookie-anchored picks and
#: 261 genuinely unpriced rows, sharing one word with no field separating them.
#: A consumer could not tell "we looked and found nothing" from "we never
#: looked", which is MISSING-IS-NEVER-ZERO applied to the evidence label
#: instead of the value.
#:
#: The pairing makes the bad state UNREPRESENTABLE: a row with a finite
#: positive value and no basis now fails the contract validator, so a future
#: pass that prices a row without saying why cannot ship quietly the way
#: ``_anchor_current_year_picks_to_rookies`` did.
CONFIDENCE_BASES: tuple[str, ...] = (
    "evidence_gate",  # the five-axis bottleneck ran
    "pick_dispersion",  # the pick coefficient-of-variation rule ran
    "derived_round_step",  # value derived from the same year's nearest priced round
    # AUDIT F-30: value derived from the nearest PUBLISHED year via the
    # measured vendor year-step.  The far-future injector always stamped
    # this provenance class; before F-30 the row it stamped it on could
    # arrive unpriced, so no confidence basis was ever written and this
    # entry was not needed.  Completing the value made the basis reachable.
    "derived_year_step",  # value derived from the nearest published year
    "derived_rookie_tether",  # value inherited from the rookie at this slot
    "derived_tier_values",  # value derived from tier values (generic grade)
    "derived_two_way_boost",  # value derived from alt-position market evidence
    "unpriced",  # no canonical value exists for this row
    "no_evidence",  # a value exists, but zero families voted
    "quarantine_degraded",  # degraded after the fact by a data-quality flag
)

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
    withheld: Sequence[FamilyEvidence] | Iterable[FamilyEvidence] = (),
) -> ConfidenceAssessment:
    """Grade the evidence behind one canonical value.

    :param evidence: one entry per INDEPENDENT family head. A repeated
        family raises — see the module docstring.
    :param eligible_families: every family that COULD have covered this
        row (registry scope × non-empty pool). The coverage denominator,
        and the reason removing evidence cannot promote a row.
    :param consensus_value: the published ``rankDerivedValue``. ``None``
        means there is nothing to agree with, which is not agreement.
    :param withheld: one entry per family that OBSERVED this row but whose
        vote did not reach the published value, and that has no voting
        member. Owner directive 2026-10-07 (IDP Trade Calculator's
        quarantine cutoff): losing a source must never RAISE confidence.
        **Lost evidence occupies a seat on the panel and earns nothing**:
        each such family is in the denominator of every SHARE axis
        (freshness, applicability, TE-basis, agreement) and in no
        numerator. It is NOT a head: independence and coverage count
        voting families only. Compared with the same family voting, every
        axis can therefore only hold or fall — a voting head could earn a
        numerator, a lost one cannot. Without this, dropping a stale,
        disagreeing family shrank the freshness and agreement denominators
        and promoted the row — the #833 pathology entering through the
        quarantine door. The caller decides membership (see
        ``data_contract._withheld_family_evidence_for_row``); only the
        ``family`` and ``source_key`` of these entries are read.
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
    lost = list(withheld)
    lost_seen: set[str] = set()
    for item in lost:
        if item.family in seen or item.family in lost_seen:
            raise ValueError(
                f"withheld family {item.family!r} (source {item.source_key!r}) is "
                "already represented: a family with a voting member is not withheld, "
                "and a withheld family is ONE piece of lost evidence"
            )
        lost_seen.add(item.family)

    eligible = {str(f) for f in eligible_families}
    n = len(heads)
    w = len(lost)
    # Every SHARE axis is measured over the panel that should have spoken on
    # this row: the voting heads plus the lost families, which earn nothing.
    panel = n + w

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
        "withheldFamilies": w,
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
    metrics["freshnessShare"] = round(fresh / panel, 4)
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
    if w:
        reasons.append(
            f"{w} observed famil{'y' if w == 1 else 'ies'} did not reach the value "
            f"(withheld or rejected) and count against every share axis: "
            f"{', '.join(sorted(lost_seen))}"
        )
    if not stale and not unknown and not w:
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
    metrics["applicabilityShare"] = round(direct / panel, 4)
    metrics["formatNativeShare"] = round(native / panel, 4)
    applicability = _share_level(metrics["applicabilityShare"])
    if direct < n:
        reasons.append(
            f"{n - direct} of {n} famil{'y' if n - direct == 1 else 'ies'} reached this "
            "asset through an approximating translation"
        )
    if metrics["formatNativeShare"] < gate_parameter("EVIDENCE_SHARE_MEDIUM"):
        applicability = _weaken(applicability)
        if n - native:
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
        # family we cannot compare has not agreed with anything.  A lost
        # family did not price the published value, so it is in the
        # denominator too.
        metrics["agreementShare"] = round(agreeing / panel, 4)
        agreement = _share_level(metrics["agreementShare"])
        pct = int(round(tolerance * 100))
        if agreeing == panel:
            reasons.append(f"All {n} families price within {pct}% of the published value")
        else:
            reasons.append(
                f"{agreeing} of {panel} families price within {pct}% of the published value"
            )

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


#: The pick markets the coefficient-of-variation rule reads, in this order.
#:
#: The two KTC model inputs (owner directive 2026-09-23): Crowd and Trades
#: are separate B10 families — but ONE provider (``keepTradeCut``, same
#: per-player payload, one fetch; ``config/sources/source_lineage.json``
#: relation ``ktc-crowd-trades-same-payload``).  KTC Market
#: (``ktcCrowdTradesSfTep``, Crowd+Trades) is the benchmark and is derived
#: from these two, so it is deliberately ABSENT: it can never count here.
_PICK_CONFIDENCE_SOURCES: tuple[str, ...] = (
    "ktcCrowdSfTep",
    "ktcTradesSfTep",
    "idpTradeCalc",
    "dlfSf",
    "dynastyNerdsSfTep",
    "dlfIdp",
    "fantasyProsIdp",
)

#: KTC slot values on slot-specific picks are SYNTHESIZED by the scraper's
#: ``_estimate_slot_from_tier`` from KTC's 14 tier rows — partial
#: information, so they count 0.5 rather than 1.0.
_PICK_SLOT_SYNTH_SOURCES: frozenset[str] = frozenset({"ktcCrowdSfTep", "ktcTradesSfTep"})

#: ``pickEvidence.state`` vocabulary (closed).
PICK_EVIDENCE_MULTI_PROVIDER = "multi_provider"
PICK_EVIDENCE_SINGLE_PROVIDER = "single_provider"
PICK_EVIDENCE_NO_PROVIDER = "no_provider"
#: A voting source's provider is not recorded (lineage gap, or the lineage
#: registry could not be read): independence cannot be proven.
PICK_EVIDENCE_PROVIDER_UNKNOWN = "provider_unknown"

#: ``pickEvidence.valueBasis``: what actually produced the pick's VALUE.  The
#: market providers are reported either way; a tethered pick's value comes
#: from the rookie at its slot, not from those providers.
PICK_VALUE_BASIS_MARKET = "market_blend"
PICK_VALUE_BASIS_TETHER = "rookie_pool_tether"


def _pick_provider(key: str) -> str | None:
    """The PROVIDER behind a pick source — the unit of pick independence.

    Read from the lineage registry's one owner.  ``None`` when the registry
    does not name the key or cannot be read — and that FAILS CLOSED in every
    caller: an unknown provider cannot be counted as independent (falling
    back to the source key would turn KTC Crowd + KTC Trades back into two
    providers the moment the registry was unreadable).
    """
    from src.sources.source_census import provider_of  # noqa: PLC0415

    return provider_of(key)


def _collapse_pick_families(site_values: dict[str, Any]) -> dict[str, Any]:
    """One value per B10 family (``dlfSf`` / ``dlfIdp`` are one family)."""
    # Imported lazily: ``data_contract`` imports this module, so a
    # top-level import would be circular. These two are SOURCE-REGISTRY
    # concerns and legitimately live there; the pick RULE itself does not.
    from src.api.data_contract import _source_precedence, correlation_group_for

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
    return site_values


def assess_pick_confidence(
    site_values: dict[str, Any],
    *,
    is_slot_specific: bool,
    withheld_sources: Iterable[str] = (),
) -> tuple[str, str]:
    """Pick confidence, with one vote per independent PROVIDER.

    Picks keep their own coefficient-of-variation statistic — rank
    spread on picks is dominated by the flat-value regions in R3-R6 and
    misleads a player-centric gate — but they must not keep raw-source
    independence assumptions:

    * two members of one B10 family (``dlfSf`` / ``dlfIdp``) cast one vote
      (B11; measured 0 of 144 live rows carrying both, pinned anyway);
    * two FAMILIES of one PROVIDER are not two markets (owner directive
      2026-10-07).  KTC Crowd and KTC Trades are separate families with
      their own value votes — the blend is untouched — but they are two
      value modes of one KTC payload, so a pick priced by them alone rests
      on ONE provider and cannot corroborate itself into ``high``.  Measured
      on the 2026-10-07 board: the 12 vendor-priced 2029 tier rows read
      ``high — picks agree within 15%`` on KTC alone;
    * a source whose vote was WITHHELD on this row (``withheld_sources`` —
      the row's ``freshnessExcludedSources``: freshness quarantine or a
      FAILED source) is not evidence behind the published value, and losing
      it can never RAISE confidence: the verdict is the weaker of the
      voting panel's and the full observed panel's.  The second term is
      exactly the pre-quarantine reading of the same values, so this is
      monotone by construction (IDP Trade Calculator's 2026-10 cutoff).
    """
    collapsed = _collapse_pick_families(site_values)
    withheld = {str(k) for k in withheld_sources}
    observed = _pick_confidence_from_values(collapsed, is_slot_specific=is_slot_specific)
    if not withheld & set(collapsed):
        return observed
    voting = _pick_confidence_from_values(
        {k: v for k, v in collapsed.items() if k not in withheld},
        is_slot_specific=is_slot_specific,
    )
    if _LEVEL_INDEX[voting[0]] <= _LEVEL_INDEX[observed[0]]:
        return voting
    return observed


def pick_evidence(
    site_values: dict[str, Any],
    *,
    withheld_sources: Iterable[str] = (),
    value_basis: str = PICK_VALUE_BASIS_MARKET,
) -> dict[str, Any]:
    """Which independent PROVIDERS stand behind a pick's market confidence.

    A diagnostic, published per pick row as ``pickEvidence`` — never a
    value input.  Read over the same sources the pick rule reads (so KTC
    Market can never appear) and grouped by PROVIDER, so KTC Crowd + KTC
    Trades report as one provider however many families they are:

    * ``votingProviders`` — providers with at least one voting value;
    * ``withheldProviders`` — providers that observed the row but whose
      every value was withheld (freshness quarantine / FAILED source);
    * ``state`` — ``multi_provider`` / ``single_provider`` /
      ``no_provider``, over VOTING providers;
    * ``reducedCoverage`` — true when any provider was withheld: the value
      rests on less market evidence than the row was observed with;
    * ``unknownProviderSources`` — sources whose provider is not recorded;
      any VOTING one makes the state ``provider_unknown`` (fail closed);
    * ``valueBasis`` — ``market_blend``, or ``rookie_pool_tether`` for a
      current-year slot pick whose value is the rookie at its slot.
    """
    withheld = {str(k) for k in withheld_sources}
    voting: dict[str, list[str]] = {}
    lost: dict[str, list[str]] = {}
    unknown: list[str] = []
    unknown_voting = False
    for key in _PICK_CONFIDENCE_SOURCES:
        raw = site_values.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or float(raw) <= 0:
            continue
        provider = _pick_provider(key)
        if provider is None:
            unknown.append(key)
            unknown_voting = unknown_voting or key not in withheld
            continue
        bucket = lost if key in withheld else voting
        bucket.setdefault(provider, []).append(key)
    withheld_providers = sorted(p for p in lost if p not in voting)
    n = len(voting)
    state = (
        PICK_EVIDENCE_PROVIDER_UNKNOWN
        if unknown_voting
        else PICK_EVIDENCE_MULTI_PROVIDER
        if n >= 2
        else PICK_EVIDENCE_SINGLE_PROVIDER
        if n == 1
        else PICK_EVIDENCE_NO_PROVIDER
    )
    return {
        "state": state,
        "valueBasis": value_basis,
        "votingProviders": sorted(voting),
        "votingSources": sorted(k for keys in voting.values() for k in keys),
        "withheldProviders": withheld_providers,
        "withheldSources": sorted(k for p in withheld_providers for k in lost[p]),
        "unknownProviderSources": sorted(unknown),
        "reducedCoverage": bool(withheld_providers),
    }


def _pick_confidence_from_values(
    canonical_sites: dict[str, Any],
    is_slot_specific: bool,
) -> tuple[str, str]:
    """The pick coefficient-of-variation rule.

    Moved here by C1-U5 from ``src/api/data_contract.py`` (one concept, one
    owner).  Picks keep their own dispersion statistic rather than the
    five-axis gate because rank spread on picks is dominated by the
    flat-value regions in R3-R6 and misleads a player-centric bucketing.

    Rules:
      * Independence is counted per PROVIDER (owner directive 2026-10-07):
        each provider contributes the LARGEST weight among its values — a
        real tier row 1.0, a KTC slot value synthesized from tier rows on a
        slot-specific pick 0.5 — never one weight per value.  Before, KTC
        Crowd + KTC Trades counted 1.0 + 1.0 as two corroborating markets.
      * A source whose provider is not recorded (or an unreadable lineage
        registry) fails closed: ``low — pick provider identity unknown``.
      * One provider is a single-provider pick: ``low``, whatever its own
        values' spread (Crowd vs Trades agreeing is one vendor agreeing
        with itself).
      * cv = stdev(raw values) / mean over every contributing value
        (unchanged arithmetic; a provider's two modes disagreeing still
        widens it).
      * high   — effective count >= 1.5 AND cv <= 0.15
        medium — effective count >= 1.0 AND cv <= 0.30
        low    — otherwise
    """
    raw_values: list[tuple[str, float]] = []
    for key in _PICK_CONFIDENCE_SOURCES:
        v = canonical_sites.get(key)
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            raw_values.append((key, f))

    if not raw_values:
        return "none", "None — no pick source values"

    provider_weight: dict[str, float] = {}
    for key, _v in raw_values:
        weight = 0.5 if (key in _PICK_SLOT_SYNTH_SOURCES and is_slot_specific) else 1.0
        provider = _pick_provider(key)
        if provider is None:
            # Fail closed: independence that cannot be proven is not
            # credited (an unreadable lineage registry must not turn KTC
            # Crowd + KTC Trades back into two corroborating markets).
            return "low", "Low — pick provider identity unknown"
        provider_weight[provider] = max(provider_weight.get(provider, 0.0), weight)
    effective_count = sum(provider_weight.values())

    if len(provider_weight) == 1 and len(raw_values) > 1:
        # Several values, one provider: no independent agreement signal.
        return "low", "Low — single pick provider"

    values = [v for _k, v in raw_values]
    mean = sum(values) / len(values)
    if mean <= 0 or len(values) < 2:
        cv = None
    else:
        var = sum((v - mean) ** 2 for v in values) / len(values)
        cv = math.sqrt(var) / mean

    if cv is None:
        # Single-source pick — no agreement signal at all.
        if effective_count >= 1.0:
            return "low", "Low — single pick source"
        return "low", "Low — limited pick sources"

    if effective_count >= 1.5 and cv <= 0.15:
        return "high", "High — picks agree within 15%"
    if effective_count >= 1.0 and cv <= 0.30:
        return "medium", "Medium — moderate pick source disagreement"
    return "low", "Low — divergent pick sources"


def unassessed_defaults(*, priced: bool) -> tuple[str, str, str]:
    """The (bucket, label, basis) a row starts with before anything assesses it.

    Returns ``basis="unpriced"`` for a row with no canonical value, and
    ``basis="no_evidence"`` for one that HAS a value but that no assessment
    pass reached. Before C1-U5 both were the string ``"none"`` with the
    label ``"None — unranked"``, and the second case was silently wrong:
    the row was not unranked *and therefore* unconfident, it had simply
    never been looked at.

    Callers that price a row outside the assessment passes must stamp a
    real basis instead of leaving this default — the contract validator
    rejects a priced row whose basis is still ``no_evidence``.
    """
    if priced:
        return "none", "None — priced but not assessed", "no_evidence"
    return "none", "None — unpriced", "unpriced"


def degrade_for_quarantine(current: str) -> tuple[str, str, str]:
    """Degrade a bucket after a data-quality flag, without inventing a level.

    Quarantine weakens confidence; it never strengthens it. A row already
    at ``none`` stays there rather than being promoted to ``low`` by the
    act of being quarantined.
    """
    if current not in CONFIDENCE_LEVELS:
        current = "none"
    if _LEVEL_INDEX[current] <= _LEVEL_INDEX["low"]:
        return (
            current,
            "None — quarantined due to identity/data-quality flags"
            if current == "none"
            else "Low — quarantined due to identity/data-quality flags",
            "quarantine_degraded",
        )
    return "low", "Low — quarantined due to identity/data-quality flags", "quarantine_degraded"
