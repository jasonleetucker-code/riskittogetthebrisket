"""Combine several bridges into ONE shared-market ladder.

A ladder's i-th entry is the combined offense+IDP rank at which the (i+1)-th
best IDP sits.  It is what lifts a specialist source's within-IDP ordinal into
combined-market space, and until this module there was exactly one of them,
seeded from exactly one source.

Two problems have to be solved to combine several.

**Coverage.** Bridges see different numbers of assets.  "18th of 523" and
"34th of 911" are not the same claim, and averaging the raw integers would let
a shallow board pull every IDP toward the top of the market purely by covering
less of it.  So each bridge's ladder is rescaled onto the deepest usable
bridge's pool before anything is combined.

That choice has a property worth stating, because it is what makes this unit
safe to land: **with one usable bridge the scale factor is exactly 1, so the
combined ladder is the incumbent ladder, integer for integer.**  The healthy
board cannot move because a second bridge was made *possible*; it moves only
when a second bridge is actually usable.

**Combination.** Once rescaled, the per-knot values are combined with
``weighted_count_aware_mean_median_blend`` — the count-aware mean-median the
pipeline already uses to fold several cross-market sources into one anchor.
This is deliberate reuse, not a new rule: that function's own comment records
why it was chosen over a bare mean, using a three-bridge example (a FootballGuys
combined rank of 304 against IDPTC's 43 and Draft Sharks' 89, where the bare
mean pulled the anchor ~15% below reality).  Inventing a bridge-weighting rule
here would be a second methodology for a question that already has an owner.

Monotonicity is enforced afterwards: a deeper IDP may never receive a shallower
combined rank than the one above it, whatever the blend returns.

**Per-family ladders** (2026-10-04, the Signals IDP crosswalk).  The same pass
also publishes, for each IDP family (DL / LB / DB), the combined offense+IDP
rank at which that family's (i+1)-th player sits.  A source that ranks only
WITHIN a family (Signals: "LB3") is translated by asking where the third LB
sits on this shared market — never by ordering one family against another,
which such a source does not claim to know.  Same ordering, same rescale, same
blend and the same monotonicity rule as the overall ladder: one owner, one
coordinate system, sliced by family.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.bridges.descriptor import BridgeAssessment

__all__ = ["BridgeLadder", "build_bridge_ladder"]


@dataclass(frozen=True)
class BridgeLadder:
    """The combined ladder, plus what it was built from."""

    ladder: tuple[int, ...]
    #: Bridge keys that contributed, in registry order.
    contributors: tuple[str, ...]
    #: Pool size every contributor was rescaled onto.
    reference_depth: int
    #: Per contributor: its own ladder depth and combined-pool depth.
    per_bridge: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Per IDP family: the combined rank of that family's (i+1)-th player.
    #: Same coordinate system as ``ladder``; a family no bridge prices is
    #: absent (never an empty tuple standing in for "rank 1").
    position_ladders: dict[str, tuple[int, ...]] = field(default_factory=dict)

    def family_ladder(self, family: str) -> tuple[int, ...]:
        """The shared-market ladder for one IDP family, or ``()`` if none."""
        return self.position_ladders.get(str(family or "").upper(), ())

    @property
    def available(self) -> bool:
        """Is there a usable translation at all?

        An empty ladder is not a degenerate ladder — it means no bridge could
        be qualified, and the caller must refuse to translate rather than fall
        back to an untranslated rank.
        """
        return bool(self.ladder)

    def to_dict(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "contributors": list(self.contributors),
            "referenceDepth": self.reference_depth,
            "depth": len(self.ladder),
            "startsAt": self.ladder[0] if self.ladder else None,
            "perBridge": {k: dict(v) for k, v in self.per_bridge.items()},
            "familyDepths": {k: len(v) for k, v in sorted(self.position_ladders.items())},
        }


def _ladder_for(
    assessment: BridgeAssessment,
    rows: Sequence[Mapping[str, Any]],
    *,
    offense_positions: frozenset[str],
    idp_positions: frozenset[str],
) -> list[int]:
    """This bridge's own ladder, over its own combined pool."""
    return _ladders_for(
        assessment, rows, offense_positions=offense_positions, idp_positions=idp_positions
    )[0]


def _ladders_for(
    assessment: BridgeAssessment,
    rows: Sequence[Mapping[str, Any]],
    *,
    offense_positions: frozenset[str],
    idp_positions: frozenset[str],
) -> tuple[list[int], dict[str, list[int]]]:
    """This bridge's own ladder, over its own combined pool, plus its slices
    by IDP family (the combined rank of each family's i-th player).

    Ordering matches ``idp_backbone.build_backbone_from_rows`` exactly —
    descending value, ties broken by lowercased name — so a bridge measured as
    capable and a bridge used to translate agree about where its IDPs sit.
    """
    keys = assessment.descriptor.keys
    combined: list[tuple[float, str, str]] = []
    for row in rows:
        values = row.get("canonicalSiteValues")
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
        pos = str(row.get("position") or "").upper()
        is_idp = pos in idp_positions
        if not is_idp and pos not in offense_positions:
            continue
        combined.append((val, str(row.get("displayName") or ""), pos if is_idp else ""))

    combined.sort(key=lambda t: (-t[0], t[1].lower()))
    overall: list[int] = []
    families: dict[str, list[int]] = {}
    for rank, (_v, _n, family) in enumerate(combined, start=1):
        if family:
            overall.append(rank)
            families.setdefault(family, []).append(rank)
    return overall, families


def _rescale_and_blend(
    scaled_ladders: Sequence[Sequence[int]],
) -> list[int]:
    """Knot-wise count-aware blend of already-rescaled ladders, monotone."""
    from src.api.data_contract import (  # noqa: PLC0415  (circular at module scope)
        weighted_count_aware_mean_median_blend,
    )

    deepest = max((len(s) for s in scaled_ladders), default=0)
    combined: list[int] = []
    previous = 0
    for knot in range(deepest):
        values = [s[knot] for s in scaled_ladders if knot < len(s)]
        if not values:
            continue
        blended, _mad = weighted_count_aware_mean_median_blend(
            [float(v) for v in values], [1.0] * len(values)
        )
        rank = max(1, int(round(blended)))
        # A deeper IDP may never sit ahead of a shallower one.
        if rank <= previous:
            rank = previous + 1
        combined.append(rank)
        previous = rank
    return combined


def build_bridge_ladder(
    assessments: Iterable[BridgeAssessment],
    rows: Sequence[Mapping[str, Any]],
    *,
    offense_positions: frozenset[str],
    idp_positions: frozenset[str],
    limit: int | None = None,
) -> BridgeLadder:
    """One ladder from every usable bridge.  Empty when none is usable.

    ``limit`` caps how many usable bridges contribute, in registry order.
    ``limit=1`` reproduces the incumbent single-bridge ladder exactly, which is
    what the ``multi_bridge_ladder`` flag uses in its off position: the
    capability test still decides WHICH bridge, so the label is gone either
    way, but the published ladder does not move until the flag is flipped.
    """
    usable = [a for a in assessments if a.usable]
    if limit is not None:
        usable = usable[: max(0, limit)]
    if not usable:
        return BridgeLadder(ladder=(), contributors=(), reference_depth=0)

    built: list[tuple[str, list[int], int]] = []
    built_families: list[dict[str, list[int]]] = []
    for assessment in usable:
        own, families = _ladders_for(
            assessment,
            rows,
            offense_positions=offense_positions,
            idp_positions=idp_positions,
        )
        if not own:
            continue
        built.append((assessment.descriptor.bridge_key, own, assessment.capability.combined_depth))
        built_families.append(families)

    if not built:
        return BridgeLadder(ladder=(), contributors=(), reference_depth=0)

    reference_depth = max(depth for _k, _l, depth in built)

    # Rescale each contributor onto the reference pool.  With one contributor
    # the factor is exactly 1.0 and every entry is unchanged.
    scaled: list[list[int]] = []
    factors: list[float] = []
    per_bridge: dict[str, dict[str, int]] = {}
    for key, own, depth in built:
        factor = (reference_depth / depth) if depth > 0 else 1.0
        factors.append(factor)
        scaled.append([max(1, int(round(entry * factor))) for entry in own])
        per_bridge[key] = {"ladderDepth": len(own), "combinedDepth": depth}

    combined = _rescale_and_blend(scaled)

    # The same rescale and blend, sliced by family.  A family is published
    # only when at least one contributor prices it.
    position_ladders: dict[str, tuple[int, ...]] = {}
    family_names = sorted({f for fams in built_families for f in fams})
    for family in family_names:
        family_scaled = [
            [max(1, int(round(entry * factor))) for entry in fams[family]]
            for fams, factor in zip(built_families, factors)
            if fams.get(family)
        ]
        blended = _rescale_and_blend(family_scaled)
        if blended:
            position_ladders[family] = tuple(blended)

    return BridgeLadder(
        ladder=tuple(combined),
        contributors=tuple(k for k, _l, _d in built),
        reference_depth=reference_depth,
        per_bridge=per_bridge,
        position_ladders=position_ladders,
    )
