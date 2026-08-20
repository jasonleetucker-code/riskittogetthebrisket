"""What a cross-position bridge declares, and what is measured about it.

The distinction in this module is the whole point of it.

**Declared** facts are registry content: which keys carry the offense half,
which carry the IDP half, which provider family they belong to, whether the
vendor publishes a cardinal scale or only an order, and what evidence (if
any) shows the two halves are comparable.

**Measured** facts are computed from the board that actually arrived:
does this family's value column carry positive values in BOTH pools, and
where does its IDP ladder start.  Nothing here trusts a declaration for a
question the data can answer.

Why that split is load-bearing
──────────────────────────────

The pipeline currently selects its cross-position backbone with a registry
flag, ``is_backbone``, and ``tests/consensus_edge/test_fair_value.py::
TestTheGuardIsACapabilityNotAFlag`` already demonstrates what that costs:
setting ``is_backbone=True`` on ``draftSharksIdp`` satisfies the guard while
leaving the board exactly as broken, because that key carries **zero**
positive offense values — its offense half lives under the separate
``draftSharks`` key.  Promoting it yields the identity ladder ``[1, 2, 3, …]``,
which *is* the fallback the guard exists to prevent.

Two consequences shape this module:

1. **A bridge is a FAMILY, not a key.**  Draft Sharks is a genuine
   cross-position source — its offense and IDP boards come from one
   league-scored pass and share one ``3D Value +`` scale (measured: offense
   converts projection surplus at 0.09610, IDP at 0.09586, a ratio of 0.998,
   with the spread *within* each pool larger than the difference *between*
   them).  It is invisible to a single-key rule purely because the vendor's
   two halves are registered under two keys.
2. **Ladder depth is not a capability test.**  ``dlfIdp`` (163 entries) and
   ``idpShow`` (247) both clear any depth comparison while producing identity
   ladders.  The property that separates a real ladder from the identity is
   that it **does not start at 1** — a real combined pool has offense assets
   ahead of the best defender.  On the live board ``idpTradeCalc`` starts at
   34.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.bridges import states as bridge_states

__all__ = [
    "BRIDGE_KINDS",
    "CARDINAL",
    "ORDINAL",
    "BridgeAssessment",
    "BridgeCapability",
    "BridgeDescriptor",
    "measure_capability",
]


#: The vendor publishes numbers whose RATIOS mean something across positions
#: ("this defender is worth 53% of the best quarterback").  A cardinal bridge
#: can seed a value mapping.
CARDINAL = "CARDINAL"
#: The vendor publishes an ORDER spanning both pools but no comparable
#: magnitudes.  An ordinal bridge can seed a ladder and nothing more.
ORDINAL = "ORDINAL"

BRIDGE_KINDS: frozenset[str] = frozenset({CARDINAL, ORDINAL})

#: A ladder starting at 1 is the identity, i.e. "the best defender is the best
#: asset" — which is the claim the whole crosswalk exists to prevent a
#: specialist source from making.
_IDENTITY_LADDER_START = 1


class BridgeDescriptorError(ValueError):
    """A descriptor was declared that cannot be true."""


@dataclass(frozen=True)
class BridgeDescriptor:
    """The DECLARED half.  Registry content; decides nothing on its own."""

    bridge_key: str
    display_name: str
    #: Provider family.  Two bridges sharing a family are ONE opinion.
    family: str
    kind: str
    #: Registry keys carrying this vendor's offense half.
    offense_keys: tuple[str, ...]
    #: Registry keys carrying this vendor's IDP half.
    idp_keys: tuple[str, ...]
    #: Has the offense/IDP same-basis question been settled?  Fails closed.
    comparability: str = bridge_states.PENDING
    #: Human-readable proof (or the named blockers when PENDING).  Required
    #: for QUALIFIED — a qualification with no stated evidence is a label.
    comparability_evidence: str = ""
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in BRIDGE_KINDS:
            raise BridgeDescriptorError(
                f"{self.bridge_key}: unknown bridge kind {self.kind!r}; "
                f"expected one of {sorted(BRIDGE_KINDS)}"
            )
        if self.comparability not in bridge_states.COMPARABILITY_STATUSES:
            raise BridgeDescriptorError(
                f"{self.bridge_key}: unknown comparability {self.comparability!r}; "
                f"expected one of {sorted(bridge_states.COMPARABILITY_STATUSES)}"
            )
        if not self.offense_keys or not self.idp_keys:
            raise BridgeDescriptorError(
                f"{self.bridge_key}: a bridge must declare BOTH an offense half and "
                "an IDP half. A source covering one pool cannot connect two."
            )
        if self.comparability == bridge_states.QUALIFIED and not self.comparability_evidence:
            raise BridgeDescriptorError(
                f"{self.bridge_key}: QUALIFIED requires comparability_evidence. "
                "An unevidenced qualification is exactly the label this module refuses."
            )
        if not self.family:
            raise BridgeDescriptorError(f"{self.bridge_key}: a bridge must declare a family")

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self.offense_keys) + tuple(self.idp_keys)


@dataclass(frozen=True)
class BridgeCapability:
    """The MEASURED half.  Computed from the board that actually arrived."""

    offense_values: int
    idp_values: int
    #: Combined-pool rank of this bridge's best IDP.  ``None`` when the
    #: combined pool could not be formed at all.
    ladder_start: int | None
    ladder_depth: int
    combined_depth: int

    @property
    def spans_both_pools(self) -> bool:
        return self.offense_values > 0 and self.idp_values > 0

    @property
    def is_identity_ladder(self) -> bool:
        """Does this 'ladder' just say the best defender is the best asset?"""
        return self.ladder_start is not None and self.ladder_start <= _IDENTITY_LADDER_START

    @property
    def capable(self) -> bool:
        """Can this bridge seed a real cross-position translation?

        Measured, never declared.  Both halves must carry values, and the
        resulting ladder must not be the identity.
        """
        return self.spans_both_pools and self.ladder_depth > 0 and not self.is_identity_ladder

    def to_dict(self) -> dict[str, Any]:
        return {
            "offenseValues": self.offense_values,
            "idpValues": self.idp_values,
            "ladderStart": self.ladder_start,
            "ladderDepth": self.ladder_depth,
            "combinedDepth": self.combined_depth,
            "spansBothPools": self.spans_both_pools,
            "isIdentityLadder": self.is_identity_ladder,
            "capable": self.capable,
        }


@dataclass(frozen=True)
class BridgeAssessment:
    """A descriptor plus what the board says about it, plus the verdict."""

    descriptor: BridgeDescriptor
    capability: BridgeCapability
    state: str
    reason: str = ""

    @property
    def usable(self) -> bool:
        return self.state in bridge_states.USABLE_BRIDGE_STATES

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "bridgeKey": self.descriptor.bridge_key,
            "displayName": self.descriptor.display_name,
            "family": self.descriptor.family,
            "kind": self.descriptor.kind,
            "offenseKeys": list(self.descriptor.offense_keys),
            "idpKeys": list(self.descriptor.idp_keys),
            "comparability": self.descriptor.comparability,
            "state": self.state,
            "usable": self.usable,
            "capability": self.capability.to_dict(),
        }
        if self.descriptor.comparability_evidence:
            out["comparabilityEvidence"] = self.descriptor.comparability_evidence
        if self.reason:
            out["reason"] = self.reason
        return out


def measure_capability(
    descriptor: BridgeDescriptor,
    rows: Iterable[Mapping[str, Any]],
    *,
    offense_positions: Sequence[str] | frozenset[str],
    idp_positions: Sequence[str] | frozenset[str],
    value_field: str = "canonicalSiteValues",
    position_field: str = "position",
) -> BridgeCapability:
    """Build this bridge's combined pool and report what it can actually do.

    The pool is formed over the union of the family's declared keys, which is
    what lets a two-key vendor (offense under one key, IDP under another)
    produce a real ladder.  A row contributes its value from the FIRST
    declared key that carries a positive one, so the two halves stay one
    scale rather than being averaged into a third.

    Ordering matches ``idp_backbone.build_backbone_from_rows`` — descending
    value, ties broken by lowercased name — so a capable bridge measured here
    and a ladder built there agree about where the IDP entries sit.
    """
    offense_set = {str(p).upper() for p in offense_positions}
    idp_set = {str(p).upper() for p in idp_positions}
    keys = descriptor.keys

    combined: list[tuple[float, str, bool]] = []
    offense_values = 0
    idp_values = 0

    for row in rows or []:
        values = row.get(value_field)
        if not isinstance(values, Mapping):
            continue
        val: float | None = None
        for key in keys:
            raw = values.get(key)
            if isinstance(raw, (int, float)) and float(raw) > 0.0:
                val = float(raw)
                break
        if val is None:
            continue
        pos = str(row.get(position_field) or "").upper()
        is_idp = pos in idp_set
        is_offense = pos in offense_set
        if not is_idp and not is_offense:
            continue
        if is_idp:
            idp_values += 1
        else:
            offense_values += 1
        combined.append((val, str(row.get("displayName") or ""), is_idp))

    combined.sort(key=lambda t: (-t[0], t[1].lower()))
    ladder = [rank for rank, (_v, _n, is_idp) in enumerate(combined, start=1) if is_idp]

    return BridgeCapability(
        offense_values=offense_values,
        idp_values=idp_values,
        ladder_start=(ladder[0] if ladder else None),
        ladder_depth=len(ladder),
        combined_depth=len(combined),
    )
