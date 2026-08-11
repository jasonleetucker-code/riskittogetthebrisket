"""A scope must not ride another scope's validation into production.

The Hill model set is four curves — GLOBAL, OFFENSE, IDP, ROOKIE — stored
as eight constants and promoted as one unit. The held-out criterion scores
**one** of them: `VALIDATED_PARAMS` is literally
``("HILL_PERCENTILE_C", "HILL_PERCENTILE_S")``, and
`holdout.evaluate_offense_master` reads only offense boards.

So "the challenger beat the champion" has always meant "the OFFENSE curve
beat the OFFENSE curve", while the promotion moved all eight numbers. That
is not hypothetical: the v1 → v2 promotion moved GLOBAL from 0.113/0.87 to
0.112/0.725 — a 14% slope change — and IDP from 0.093/0.97 to 0.083/1.11,
with no out-of-sample evidence for either. The promotion note is accurate
about OFFENSE and silent about the other six constants.

This module makes the distinction structural. It does NOT invent evidence
for GLOBAL or IDP, and it does not weaken the existing margin gate. It
answers one question per scope — *did this challenger change you, and if
so what scored you?* — and refuses a promotion where the honest answer is
"nothing did".

Deliberately NOT collapsed into `promotion.decide_promotion`: that
function compares two criteria and is correct at what it does. Scope
eligibility is a different question asked of a different input (the
parameter sets), and fusing them would make a two-scalar comparison
secretly depend on eight floats.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from src.model_registry.versioning import RegistryError

#: Which constants belong to which scope. The single mapping; callers must
#: not re-derive it by string prefix, because ``HILL_PERCENTILE_C``
#: (OFFENSE) is a prefix of nothing and ``HILL_GLOBAL_PERCENTILE_C``
#: (GLOBAL) shares its stem — a prefix rule silently mis-assigns them.
SCOPE_CONSTANTS: dict[str, tuple[str, str]] = {
    "GLOBAL": ("HILL_GLOBAL_PERCENTILE_C", "HILL_GLOBAL_PERCENTILE_S"),
    "OFFENSE": ("HILL_PERCENTILE_C", "HILL_PERCENTILE_S"),
    "IDP": ("IDP_HILL_PERCENTILE_C", "IDP_HILL_PERCENTILE_S"),
    "ROOKIE": ("HILL_ROOKIE_PERCENTILE_C", "HILL_ROOKIE_PERCENTILE_S"),
}

#: Scopes the live pipeline actually routes to. ROOKIE is fit by the weekly
#: refit and consumed by nothing — ``data_contract._curve_for_source`` sends
#: rookie sources through OFFENSE/IDP after ladder translation. A scope that
#: cannot reach a served value does not need holdout evidence to move, and
#: pretending otherwise would block promotions for no protection.
ROUTED_SCOPES: frozenset[str] = frozenset({"GLOBAL", "OFFENSE", "IDP"})


class ScopeValidation:
    """The states a scope can be in for one champion→challenger pair.

    Strings rather than an enum so they survive JSON round-trips into the
    registry unchanged, and so a stored record stays readable without
    importing this module.
    """

    #: Scored against boards the fit never read. The only state that means
    #: "we measured whether this generalizes".
    VALIDATED_EXTERNAL_HOLDOUT = "VALIDATED_EXTERNAL_HOLDOUT"

    #: Resampling/LOSO evidence only. Says the fit is stable, NOT that it
    #: predicts anything unseen. Never upgrade this to the state above —
    #: that is evidence laundering (§43).
    VALIDATED_CROSS_VALIDATION_ONLY = "VALIDATED_CROSS_VALIDATION_ONLY"

    #: Changed, and nothing independent scored it.
    UNVALIDATED_NO_HOLDOUT = "UNVALIDATED_NO_HOLDOUT"

    #: Byte-identical to the champion. Needs no evidence, because it makes
    #: no claim — this is what keeps the gate from blocking an OFFENSE-only
    #: promotion.
    UNCHANGED_FROM_CHAMPION = "UNCHANGED_FROM_CHAMPION"

    #: Fit but not consumed by the serving pipeline.
    NOT_ROUTED = "NOT_ROUTED"

    #: Changed, unvalidated, and an owner explicitly accepted the risk with
    #: a recorded reason. Distinct from VALIDATED_* on purpose: it records
    #: a decision, never a measurement.
    OVERRIDDEN_BY_OWNER = "OVERRIDDEN_BY_OWNER"


def _changed(champion: Mapping[str, float], challenger: Mapping[str, float], scope: str) -> bool:
    for name in SCOPE_CONSTANTS[scope]:
        if name not in challenger:
            continue
        old = champion.get(name)
        if old is None:
            return True
        if float(old) != float(challenger[name]):
            return True
    return False


def classify_scopes(
    champion: Mapping[str, float],
    challenger: Mapping[str, float],
    *,
    validated_scopes: Iterable[str] = (),
    cross_validated_scopes: Iterable[str] = (),
    override_scopes: Iterable[str] = (),
) -> dict[str, str]:
    """Label every scope for one champion→challenger pair.

    ``validated_scopes`` is what an external holdout actually scored — today
    that is ``{"OFFENSE"}`` and nothing else, because no value-publishing
    GLOBAL or IDP board exists that the fit does not already train on.
    Passing a scope here is a claim about data, not a preference.
    """
    validated = set(validated_scopes)
    cross = set(cross_validated_scopes)
    overridden = set(override_scopes)

    out: dict[str, str] = {}
    for scope in SCOPE_CONSTANTS:
        if not _changed(champion, challenger, scope):
            # Checked FIRST, and deliberately: an unchanged scope makes no
            # claim, so its evidence state is irrelevant. Ordering this
            # after the routed check would label unchanged ROOKIE
            # NOT_ROUTED and lose the more useful fact.
            out[scope] = ScopeValidation.UNCHANGED_FROM_CHAMPION
        elif scope not in ROUTED_SCOPES:
            out[scope] = ScopeValidation.NOT_ROUTED
        elif scope in validated:
            out[scope] = ScopeValidation.VALIDATED_EXTERNAL_HOLDOUT
        elif scope in overridden:
            out[scope] = ScopeValidation.OVERRIDDEN_BY_OWNER
        elif scope in cross:
            out[scope] = ScopeValidation.VALIDATED_CROSS_VALIDATION_ONLY
        else:
            out[scope] = ScopeValidation.UNVALIDATED_NO_HOLDOUT
    return out


#: States that permit a CHANGED routed scope to be promoted.
#: ``VALIDATED_CROSS_VALIDATION_ONLY`` is absent on purpose: resampling
#: shows a fit is stable, not that it generalizes, and the whole point of
#: this module is that those are different claims.
_PROMOTABLE = frozenset(
    {
        ScopeValidation.UNCHANGED_FROM_CHAMPION,
        ScopeValidation.NOT_ROUTED,
        ScopeValidation.VALIDATED_EXTERNAL_HOLDOUT,
        ScopeValidation.OVERRIDDEN_BY_OWNER,
    }
)


def assert_promotable(
    champion: Mapping[str, float],
    challenger: Mapping[str, float],
    *,
    validated_scopes: Iterable[str] = (),
    cross_validated_scopes: Iterable[str] = (),
    override_scopes: Iterable[str] = (),
    override_reason: str = "",
) -> dict[str, str]:
    """Fail closed unless every changed routed scope has its own evidence.

    Returns the scope states when it passes, so the caller can record them
    alongside the promotion rather than recomputing and possibly
    disagreeing.

    An override is available because a permanently unpromotable model is
    its own failure mode — GLOBAL and IDP may never get an external holdout,
    and the owner must be able to accept that risk knowingly. It requires a
    non-empty reason for the same purpose `promote()` requires one: an
    exception with no stated reason is indistinguishable from an accident.
    """
    overridden = set(override_scopes)
    if overridden and not override_reason.strip():
        raise RegistryError(
            f"override_scopes {sorted(overridden)} requires a non-empty "
            "override_reason; an unrecorded exception is not an exception, "
            "it is a silently weakened gate"
        )

    states = classify_scopes(
        champion,
        challenger,
        validated_scopes=validated_scopes,
        cross_validated_scopes=cross_validated_scopes,
        override_scopes=overridden,
    )
    blocked = sorted(s for s, state in states.items() if state not in _PROMOTABLE)
    if blocked:
        detail = ", ".join(f"{s}={states[s]}" for s in blocked)
        raise RegistryError(
            f"cannot promote: changed scope(s) without their own evidence — {detail}. "
            "The held-out criterion scores OFFENSE only; a scope that moved must be "
            "scored, unchanged, unrouted, or explicitly overridden with a reason."
        )
    return states
