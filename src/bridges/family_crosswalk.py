"""Coverage-aligned within-family crosswalk (Candidate F).

A source that ranks players only WITHIN an IDP family (Signals: "LB3") has
no opinion about where its LB3 sits against DL, DB, offense or picks.  The
bridge owner (:mod:`src.bridges.ladder`) answers that question: each family
slot of the bridge ladder holds the combined offense+IDP rank of one board
row.  This module turns a within-family ORDER into votes in those
shared-market coordinates.

Candidate A (the October 2026 shadow method) mapped the source's k-th player
onto the bridge's k-th family slot.  Where the two boards cover different
players that shifts every vote below the first coverage difference (the
"coverage displacement" defect: a source-only row consumes a slot a
bridge-priced player then cannot reach).  Candidate F aligns coverage first:

* ``M`` — the players BOTH boards price (source order σ ∩ bridge slots c);
* ``L`` — the ascending list of those players' bridge coordinates c(q);
* a tie group of size t starting at matched competition rank k votes the
  mean of ``L[k-1 .. k+t-2]``.

Stated plainly, so nobody reads more into the number than it holds:

* With no ties the votes are a PERMUTATION of the matched players' bridge
  coordinates: the source contributes its within-family ORDER only.
* The cross-family LEVEL and the within-family SPACING are the bridge's
  (``levelSource``).  The vote is never a cross-family price the source
  asserted.
* Source-only rows (no bridge coordinate) are WITHHELD — never interpolated,
  never extrapolated, never zero.
* No parameter is learned.

Pure functions only: no flags, no I/O, no board.  The caller
(``data_contract._compute_unified_rankings``) decides when F runs and owns
pricing (one helper prices a rank, shadow or vote).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Iterable

__all__ = [
    "CANDIDATE_A",
    "CANDIDATE_F",
    "CONTRIBUTES_WITHIN_FAMILY_ORDER",
    "CrosswalkVote",
    "FamilyObservation",
    "WITHHELD_BY_TRANSLATION",
    "WITHHELD_FAMILY_MISMATCH",
    "WITHHELD_MULTI_BRIDGE",
    "WITHHELD_NO_FAMILY_LADDER",
    "WITHHELD_NOT_WITHIN_FAMILY_RANK",
    "WITHHELD_REFERENCE",
    "WITHHELD_ROOKIE",
    "WITHHELD_SID_CONTRADICTION",
    "WITHHELD_UNMATCHED",
    "coverage_aligned_votes",
]

#: Candidate identifiers published on every shadow / vote stamp.
CANDIDATE_A = "signals-idp-A-family-ladder-v1"
CANDIDATE_F = "signals-idp-F-coverage-aligned-v1"

#: What a Candidate F vote carries from the source (nonnegotiable: a borrowed
#: level is never presented as the source's own cross-family price).
CONTRIBUTES_WITHIN_FAMILY_ORDER = "within_family_order"

# Withheld reasons — every withheld observation names one; none is a zero.
WITHHELD_UNMATCHED = "unmatched_in_reference"
WITHHELD_MULTI_BRIDGE = "family_positions_undefined_multi_bridge"
WITHHELD_REFERENCE = "reference_withheld"
WITHHELD_SID_CONTRADICTION = "sleeper_id_contradiction"
WITHHELD_NOT_WITHIN_FAMILY_RANK = "not_a_within_family_rank"
WITHHELD_FAMILY_MISMATCH = "family_mismatch"
WITHHELD_ROOKIE = "rookie_unobservable_by_basis"
WITHHELD_NO_FAMILY_LADDER = "no_family_ladder"

#: Reasons that mean OUR translation declined an observation the source made
#: (as opposed to the source not covering the row).  The confidence gate must
#: not score such a row as one the source family failed to cover.
WITHHELD_BY_TRANSLATION: frozenset[str] = frozenset(
    {
        WITHHELD_UNMATCHED,
        WITHHELD_MULTI_BRIDGE,
        WITHHELD_REFERENCE,
        WITHHELD_ROOKIE,
        WITHHELD_NO_FAMILY_LADDER,
    }
)


@dataclass(frozen=True)
class FamilyObservation:
    """One row the within-family source priced.

    ``order_value`` — the source's ordering value (higher is better; equal
    values are a tie).  ``name_key`` — the bridge's tie-break key
    (:func:`src.bridges.ladder.bridge_order_name_key`), so σ and c(p) break
    ties identically.  ``reference_coordinate`` — c(p), the row's combined
    rank in the bridge's family ladder, or ``None`` when the bridge does not
    price it.
    """

    key: Hashable
    order_value: float
    name_key: str
    reference_coordinate: int | None
    rookie: bool = False


@dataclass(frozen=True)
class CrosswalkVote:
    """The crosswalk's answer for one observation.

    Exactly one of ``rank`` / ``withheld_reason`` is set.  ``rank`` is a
    shared-market coordinate and may be FRACTIONAL (a tie group's mean); it
    must be priced as-is, never rounded through a rank translator.
    """

    rank: float | None
    withheld_reason: str | None
    matched_rank: int | None = None
    tie_size: int = 0


def coverage_aligned_votes(
    observations: Iterable[FamilyObservation],
    *,
    withhold_rookies: bool = True,
) -> dict[Hashable, CrosswalkVote]:
    """Candidate F votes for one family.  Deterministic in its input SET.

    Order of ``observations`` never matters: matched rows are sorted by
    (−order_value, name_key, c) and tie groups are defined by equal
    ``order_value`` alone, so a shuffle of the input yields identical votes.
    """
    obs = list(observations)
    out: dict[Hashable, CrosswalkVote] = {}
    matched: list[FamilyObservation] = []
    for o in obs:
        if withhold_rookies and o.rookie:
            out[o.key] = CrosswalkVote(rank=None, withheld_reason=WITHHELD_ROOKIE)
        elif o.reference_coordinate is None:
            out[o.key] = CrosswalkVote(rank=None, withheld_reason=WITHHELD_UNMATCHED)
        else:
            matched.append(o)
    matched.sort(key=lambda o: (-float(o.order_value), o.name_key, int(o.reference_coordinate)))
    coordinates = sorted(int(o.reference_coordinate) for o in matched)
    i = 0
    n = len(matched)
    while i < n:
        j = i + 1
        while j < n and float(matched[j].order_value) == float(matched[i].order_value):
            j += 1
        tie = j - i
        rank = sum(coordinates[i:j]) / tie
        for o in matched[i:j]:
            out[o.key] = CrosswalkVote(
                rank=float(rank), withheld_reason=None, matched_rank=i + 1, tie_size=tie
            )
        i = j
    return out
