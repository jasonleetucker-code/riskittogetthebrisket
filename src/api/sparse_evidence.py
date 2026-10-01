"""Sparse-evidence estimator (Batch 3 Unit E, DISABLED by default).

Replaces the single-source haircut (``data_contract._SINGLE_SOURCE_VALUE_
RETENTION = 0.30``) when ``sparse_evidence_estimator`` is on. The haircut mixes
two questions: where a thinly covered player's value is (the central estimate)
and how sure we are (uncertainty). Uncertainty has one owner,
``src/api/confidence.py``, and a one-family row cannot exceed LOW there. This
module answers only the central question.

Preregistration (method, gates, decision rule):
``docs/valuation/evidence/sparse-evidence-2026-10-01/PREREGISTRATION.md``.

Method (candidate C):

* A row resting on one provider family keeps that family's observation ``x`` as
  central evidence. It is never multiplied by a constant.
* A family that did NOT list the player can still say something: if its board is
  healthy and covers the player's position, the player sits beyond its published
  depth, so its value under that family is at most the family's cutoff ``U``.
  That bound is used only when every condition in :func:`source_status` and
  :func:`family_bounds` holds. Unknown coverage, a failed or stale fetch, an
  inapplicable source, an unranked position or doubtful identity never produce a
  bound. Absences are counted per FAMILY (list depth and eligibility are shared
  within a family), and a family bound is the loosest member bound.
* A bound below ``x`` binds. The estimate is the pipeline's own blend over ``x``
  and the binding bounds, each placed AT its cutoff -- the most generous place
  the evidence allows. The blend is monotone in its values, so this is the upper
  end of the identified set, not an invented last-place rank and not a shrink
  toward zero. The lower end is not identified and is published as such.

Central value and certainty are separate (owner directive, 2026-10-01).
``state`` says what happened to the VALUE (bounded / bound non-binding / no
witness). ``evidenceState`` (:func:`classify`) says WHY the row rests on one
family and how much its absences can say -- the CERTAINTY half. It never moves
the central value; confidence is still decided only by ``src/api/confidence.py``.
The state matrix and its treatments are pinned by
``tests/api/test_sparse_evidence_state_matrix.py``.

The module is pure: the pipeline hands it the facts it already computed
(source pool contributions, dataset state, presence) and the blend function.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

ESTIMATOR_VERSION = "sparse-censor-v1"

STATE_CENSOR_BOUNDED = "censor_bounded"
STATE_CENSOR_NONBINDING = "censor_nonbinding"
STATE_UNCORROBORATED = "uncorroborated"

# Source-level refusal reasons.
REFUSE_INACTIVE = "source_inactive"
REFUSE_NOT_DYNASTY = "game_type_not_verified_dynasty"
REFUSE_UNMEASURED = "dataset_state_unmeasured"
REFUSE_UNHEALTHY = "health_not_healthy"
REFUSE_COVERAGE = "coverage_unknown_or_partial"
REFUSE_STALE = "board_not_on_schedule"
# Row-level refusal reasons.
REFUSE_SCOPE = "position_out_of_scope"
REFUSE_ROOKIE_ONLY = "rookie_only_board"
REFUSE_EXCLUDES_ROOKIES = "board_excludes_rookies"
REFUSE_POSITION_UNRANKED = "position_unranked_by_source"
REFUSE_NAME_PUBLISHED = "name_published_but_not_attached"
REFUSE_IDENTITY = "row_identity_unproven"
REFUSE_NAME_INDEX = "source_name_index_unavailable"

# -- Evidence states: the CERTAINTY half (never moves the central value) --
#
# Out of the estimator's scope (no block is ever stamped on these rows):
EV_NO_EVIDENCE = "no_usable_evidence"  # nothing priced it: unpriced, never 0
EV_INDEPENDENT = "independent_families"  # >= 2 present families: not sparse
# In scope (one present family), in precedence order:
EV_OUTLIER_REMOVED = "one_family_after_outlier_removal"  # others LISTED it, then filtered
EV_LISTED_FILTERED = "one_family_after_listing_filtered"  # others LISTED it, did not vote
EV_CENSORED = "absent_from_deeper_boards"  # a healthy board reaching below x omits it
EV_BEYOND_SHALLOW = "beyond_shallower_boards"  # healthy boards omit it, cutoffs above x
EV_SAME_FAMILY = "one_family_multiple_members"  # n observations, one opinion
EV_IDENTITY = "absent_families_identity_unresolved"
EV_STALE = "absent_families_stale"
EV_UNHEALTHY = "absent_families_unhealthy"
EV_UNVERIFIED = "absent_families_unverified"
EV_NO_COVERAGE = "absent_families_do_not_cover_position"
EV_MIXED = "absent_families_uninformative_mixed"
EV_SOLE = "sole_eligible_family"  # no other active family could have listed it

#: Every refusal reason, grouped by what it says about the absence. None of
#: these is evidence about the player; the grouping only names WHY not.
REFUSAL_CATEGORY: dict[str, str] = {
    REFUSE_STALE: EV_STALE,
    REFUSE_UNHEALTHY: EV_UNHEALTHY,
    REFUSE_COVERAGE: EV_UNHEALTHY,
    REFUSE_UNMEASURED: EV_UNVERIFIED,
    REFUSE_NOT_DYNASTY: EV_UNVERIFIED,
    REFUSE_INACTIVE: EV_UNVERIFIED,
    REFUSE_POSITION_UNRANKED: EV_NO_COVERAGE,
    REFUSE_ROOKIE_ONLY: EV_NO_COVERAGE,
    REFUSE_EXCLUDES_ROOKIES: EV_NO_COVERAGE,
    REFUSE_SCOPE: EV_NO_COVERAGE,
    REFUSE_IDENTITY: EV_IDENTITY,
    REFUSE_NAME_PUBLISHED: EV_IDENTITY,
    REFUSE_NAME_INDEX: EV_IDENTITY,
}

# Why a family that LISTED the player did not vote.  A listing is never an
# absence, so none of these can produce a censored bound.
LISTED_OUTLIER = "outlier_removed"
LISTED_FRESHNESS = "freshness_excluded"
LISTED_INACTIVE = "source_inactive"  # switched off by a source override
LISTED_NOT_VOTING = "listed_not_voting"

IN_SCOPE_STATES: tuple[str, ...] = (
    EV_OUTLIER_REMOVED,
    EV_LISTED_FILTERED,
    EV_CENSORED,
    EV_BEYOND_SHALLOW,
    EV_SAME_FAMILY,
    EV_IDENTITY,
    EV_STALE,
    EV_UNHEALTHY,
    EV_UNVERIFIED,
    EV_NO_COVERAGE,
    EV_MIXED,
    EV_SOLE,
)

#: The freshness band a board must be in to bound anything (the existing top
#: band of ``config/sources/freshness_v1.json`` -- not a new threshold).
ON_SCHEDULE = "ON_SCHEDULE"
HEALTHY = "HEALTHY"
DYNASTY = "DYNASTY"


@dataclass(frozen=True)
class SourceStatus:
    """Whether a source's board is healthy enough to bound an absent player."""

    ok: bool
    reason: str | None
    weight: float


def source_status(
    src_def: Mapping[str, Any] | None,
    weighting: Any,
    *,
    base_weight: float,
    freshness_applied: bool,
) -> SourceStatus:
    """Source-level witness conditions (preregistration W1, W5, W6).

    ``weighting`` is the source's ``src.sources.freshness.SourceWeighting`` (or
    ``None``). Fails closed: anything unmeasured or unknown refuses.
    """
    if not src_def:
        return SourceStatus(False, REFUSE_INACTIVE, 0.0)
    if str(src_def.get("game_type") or "") != DYNASTY:
        return SourceStatus(False, REFUSE_NOT_DYNASTY, 0.0)
    if weighting is None or not getattr(weighting, "measured", False):
        return SourceStatus(False, REFUSE_UNMEASURED, 0.0)
    if getattr(weighting, "health_state", None) != HEALTHY:
        return SourceStatus(False, REFUSE_UNHEALTHY, 0.0)
    if getattr(weighting, "coverage", None) is None or weighting.coverage_factor < 1.0:
        return SourceStatus(False, REFUSE_COVERAGE, 0.0)
    sub = weighting.subset_for(False)
    if sub is None or getattr(sub, "state", None) != ON_SCHEDULE:
        return SourceStatus(False, REFUSE_STALE, 0.0)
    dyn = float(sub.freshness) * float(weighting.health_factor) * float(weighting.coverage_factor)
    weight = base_weight * dyn if freshness_applied else base_weight
    return SourceStatus(True, None, max(0.0, weight))


@dataclass(frozen=True)
class FamilyBound:
    family: str
    bound: float
    weight: float
    witnesses: tuple[str, ...]


def family_bounds(
    *,
    position: str,
    is_rookie: bool,
    listed_families: set[str],
    sources: Iterable[Mapping[str, Any]],
    family_of: Mapping[str, str],
    status: Mapping[str, SourceStatus],
    min_contribution: Mapping[tuple[str, str], float],
    name_check: Callable[[str], str | None],
    scope_eligible: Callable[[str, str, str | None], bool],
    identity_ok: bool,
    family_cap: Callable[[Mapping[str, float]], Mapping[str, float]],
) -> tuple[dict[str, FamilyBound], dict[str, str]]:
    """Censored upper bounds, one per absent family (preregistration W2-W8).

    Returns ``(bounds, refused)``: ``refused`` names every absent eligible
    family that produced no bound, with the first member's reason (families
    whose every member is out of scope are not listed -- they could never have
    covered the row).
    """
    per_family: dict[str, list[tuple[str, float, float]]] = {}
    refused: dict[str, str] = {}
    for src in sources:
        key = str(src.get("key") or "")
        family = family_of.get(key, key)
        if family in listed_families:
            continue
        scopes = [src.get("scope")] + list(src.get("extra_scopes") or [])
        if not any(scope_eligible(position, str(s), src.get("position_group")) for s in scopes):
            continue
        reason: str | None = None
        st = status.get(key)
        if not identity_ok:
            reason = REFUSE_IDENTITY
        elif src.get("needs_rookie_translation") and not is_rookie:
            reason = REFUSE_ROOKIE_ONLY
        elif src.get("excludes_rookies") and is_rookie:
            reason = REFUSE_EXCLUDES_ROOKIES
        elif st is None or not st.ok:
            reason = st.reason if st is not None else REFUSE_UNMEASURED
        elif (key, position) not in min_contribution:
            reason = REFUSE_POSITION_UNRANKED
        else:
            reason = name_check(key)
        if reason is not None:
            refused.setdefault(family, reason)
            continue
        per_family.setdefault(family, []).append(
            (key, float(min_contribution[(key, position)]), st.weight)
        )
    bounds: dict[str, FamilyBound] = {}
    for family, members in per_family.items():
        refused.pop(family, None)
        capped = family_cap({k: w for k, _u, w in members})
        bounds[family] = FamilyBound(
            family=family,
            # The loosest member bound: the family can only be said to sit
            # below the cutoff every witness agrees on.
            bound=max(u for _k, u, _w in members),
            weight=sum(capped.values()),
            witnesses=tuple(sorted(k for k, _u, _w in members)),
        )
    return bounds, refused


@dataclass
class Estimate:
    central: float
    observed: float
    state: str
    reason: str
    binding: list[FamilyBound] = field(default_factory=list)
    nonbinding: list[FamilyBound] = field(default_factory=list)


def estimate(
    observed: float,
    observed_weight: float,
    bounds: Mapping[str, FamilyBound],
    blend: Callable[[list[float], list[float]], tuple[float, Any]],
) -> Estimate:
    """Central estimate from one observed family and its censored bounds.

    Binding bounds (``bound < observed``) enter the pipeline's blend AT their
    bound -- the largest value consistent with the censoring. Non-binding
    bounds say nothing about the row and are dropped, never treated as an
    observation. With no binding bound the observation stands.
    """
    ordered = sorted(bounds.values(), key=lambda b: (b.bound, b.family))
    binding = [b for b in ordered if b.bound < observed and b.weight > 0.0]
    nonbinding = [b for b in ordered if b not in binding]
    if not binding:
        state = STATE_CENSOR_NONBINDING if bounds else STATE_UNCORROBORATED
        reason = (
            "every censored family's cutoff sits above the observation"
            if bounds
            else "no healthy eligible absent family can bound this row"
        )
        return Estimate(observed, observed, state, reason, [], nonbinding)
    values = [observed] + [b.bound for b in binding]
    weights = [max(observed_weight, 0.0)] + [b.weight for b in binding]
    if sum(weights) <= 0.0:
        weights = [1.0] * len(values)
    central, _ = blend(values, weights)
    # The blend cannot leave its inputs' hull; clamp float slack only.
    central = min(max(central, min(values)), observed)
    return Estimate(
        central,
        observed,
        STATE_CENSOR_BOUNDED,
        f"{len(binding)} absent famil{'y' if len(binding) == 1 else 'ies'} bound the value "
        "below the observation; each placed at its published cutoff",
        binding,
        nonbinding,
    )


@dataclass(frozen=True)
class Evidence:
    """The certainty classification of one row (see :func:`classify`)."""

    state: str
    causes: tuple[str, ...]
    listed_not_voting: dict[str, str]
    refusal_categories: dict[str, str]
    eligible_absent_families: int


def classify(
    *,
    observed: float,
    present_families: int,
    observations: int,
    listed_not_voting: Mapping[str, str],
    est: Estimate | None,
    refused: Mapping[str, str],
) -> Evidence:
    """Name the row's evidence state -- the certainty half, kept off the value.

    ``observed`` is the one family's blend, ``present_families`` the pipeline's
    own count (voting + freshness-excluded families), ``observations`` the
    voting observations, ``listed_not_voting`` the families that LISTED the
    player but did not vote (``{family: LISTED_*}``), ``est`` the central
    estimate (its binding / non-binding bounds) and ``refused`` the absent
    eligible families that produced no bound (``{family: REFUSE_*}``).

    Precedence (the first that applies is ``state``; every one that applies is
    in ``causes``): a listing filtered away; a binding censor; a non-binding
    censor (the player sits beyond boards shallower than its observation);
    several observations of one family; the absences' refusal category (one
    category names it, several are ``EV_MIXED``); no other eligible family.
    """
    categories = {f: REFUSAL_CATEGORY.get(r, EV_MIXED) for f, r in refused.items()}
    binding = list(est.binding) if est is not None else []
    nonbinding = list(est.nonbinding) if est is not None else []
    eligible_absent = len(binding) + len(nonbinding) + len(refused)
    if observations <= 0 or observed <= 0:
        return Evidence(EV_NO_EVIDENCE, (EV_NO_EVIDENCE,), {}, categories, eligible_absent)
    if present_families >= 2:
        return Evidence(EV_INDEPENDENT, (EV_INDEPENDENT,), {}, categories, eligible_absent)
    causes: list[str] = []
    reasons = set(listed_not_voting.values())
    if LISTED_OUTLIER in reasons:
        causes.append(EV_OUTLIER_REMOVED)
    if reasons - {LISTED_OUTLIER}:
        causes.append(EV_LISTED_FILTERED)
    if binding:
        causes.append(EV_CENSORED)
    if nonbinding:
        causes.append(EV_BEYOND_SHALLOW)
    if observations >= 2:
        causes.append(EV_SAME_FAMILY)
    refusal_states = sorted(set(categories.values()))
    causes.extend(refusal_states)
    if not listed_not_voting and eligible_absent == 0:
        causes.append(EV_SOLE)
    primary = next((c for c in causes if c not in refusal_states and c != EV_SOLE), None)
    if primary is None and refusal_states:
        primary = refusal_states[0] if len(refusal_states) == 1 else EV_MIXED
    if primary is None:
        primary = EV_SOLE
    return Evidence(
        primary,
        tuple(causes),
        dict(sorted(listed_not_voting.items())),
        dict(sorted(categories.items())),
        eligible_absent,
    )


def stamp(
    est: Estimate,
    *,
    observations: int,
    voting_families: int,
    effective_families: float,
    refused: Mapping[str, str],
    evidence: Evidence | None = None,
    observed_family: str | None = None,
    ineligible_listings: Iterable[str] = (),
) -> dict[str, Any]:
    """The additive per-row ``sparseEvidence`` block."""
    certainty: dict[str, Any] = {}
    if evidence is not None:
        certainty = {
            # The CERTAINTY half: why one family, and what the absences can say.
            # Never an input to ``centralEstimate``.
            "evidenceState": evidence.state,
            "evidenceCauses": list(evidence.causes),
            "observedFamily": observed_family,
            "listedNotVotingFamilies": evidence.listed_not_voting,
            "refusalCategories": evidence.refusal_categories,
            "eligibleAbsentFamilyCount": evidence.eligible_absent_families,
            # Values under this name from boards that cannot rank the position:
            # a shared name, not a listing.  Reported, never a cause or a bound.
            "ineligibleSourceListings": sorted(ineligible_listings),
        }
    return {
        "estimator": ESTIMATOR_VERSION,
        "state": est.state,
        "reason": est.reason,
        **certainty,
        # Truncated exactly as ``rankDerivedValue`` is, so the two agree.
        "centralEstimate": int(est.central),
        "observedValue": int(round(est.observed)),
        "sensitivityInterval": {
            "low": int(est.central),
            "high": int(round(est.observed)),
            "label": "sensitivity_uncalibrated",
            "note": (
                "low = censor-bounded estimate, high = the uncorroborated observation; "
                "not a credible interval"
            ),
        },
        "identifiedSet": {
            "upper": int(est.central),
            "lower": None,
            "lowerReason": "values below an absent family's cutoff are unobserved",
        },
        "observationCount": observations,
        "independentFamilyCount": voting_families,
        "effectiveFamilyCount": round(effective_families, 4),
        "censoredFamiliesUsed": [
            {"family": b.family, "bound": int(round(b.bound)), "witnesses": list(b.witnesses)}
            for b in est.binding
        ],
        "boundsUsed": [round(b.bound, 2) for b in est.binding],
        "nonBindingFamilies": [
            {"family": b.family, "bound": int(round(b.bound))} for b in est.nonbinding
        ],
        "refusedFamilies": dict(sorted(refused.items())),
        # Filled from src/api/confidence.py's verdict once it is assessed.
        "confidence": None,
    }
