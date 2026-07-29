"""Roster assembly — join names, values, and SLOT ELIGIBILITY.

Why this module exists
──────────────────────
ADR-007 recorded that Sleeper evaluates slot eligibility against
``fantasy_positions``, not ``position``.  A pass-rushing linebacker ships
as ``position="DL"`` with ``fantasy_positions=["DL","LB"]`` and is legal
in either slot.  LI-3 fixed that in ``src/ros/lineup.py`` and measured
the cost of getting it wrong: hybrid IDPs were locked out of half their
legal slots in production, and 6 of 12 teams had a materially wrong
starting lineup.

WS-J reintroduced the same defect from a different direction.  The ROS
aggregate (``data/ros/aggregate/latest.json``) carries
``canonicalName`` / ``position`` / ``rosValue`` and **no
fantasy_positions**.  Joining rosters to it alone therefore hands the
optimizer position-only rows, and the optimizer — correct as it is —
cannot slot a hybrid it was never told about.  The bug was not in the
code this time; it was in the data path feeding it.

So eligibility is a first-class input here, not an optional extra.
``build_roster_pool`` requires the NFL player map to enrich hybrids, and
``hybrid_coverage`` exists so a caller can PROVE the enrichment landed
rather than assume it.

Pure computation: callers supply the loaded maps; this module does no
I/O and no network, mirroring ``replacement.py``'s shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from src.utils.name_clean import compact_name_key

__all__ = [
    "HybridCoverage",
    "JoinReport",
    "build_nfl_position_index",
    "build_roster_pool",
    "build_value_index",
    "compact_name_key",
    "hybrid_coverage",
    "normalize_name",
]

# Positions that can legally appear in more than one slot family, i.e.
# the ones where losing fantasy_positions actually costs lineup points.
_MULTI_FAMILY = {
    "DL",
    "DE",
    "DT",
    "EDGE",
    "NT",
    "LB",
    "ILB",
    "OLB",
    "MLB",
    "DB",
    "CB",
    "S",
    "FS",
    "SS",
}


# Deprecated alias, kept because it is in ``__all__`` and imported by
# tests and callers.  The lowercase-alphanumeric key now has exactly
# one definition — ``src/utils/name_clean.compact_name_key``, family 2
# in that module's key registry — shared with
# ``src/adapters/ktc_crowd_faab``.
#
# It is NOT byte-equivalent to the frontend's
# ``waiver-logic.normalizeNameCompact`` (Python's ``str.isalnum()``
# keeps ``é``; the JS ``[^a-z0-9]`` strip drops it), and the previous
# docstring here claimed otherwise.  Nothing joins across that
# boundary, so the two stay independent — see the registry note.
#
# It is also NOT interchangeable with ``normalize_player_name``: this
# key keeps generational suffixes, so swapping it would change which
# roster rows collide.
normalize_name = compact_name_key


@dataclass(frozen=True)
class JoinReport:
    """What the join actually managed to resolve.

    Exists because a silent join loss is indistinguishable from a weak
    roster: both show up as fewer players and a lower lineup score.
    """

    rostered: int
    valued: int
    eligibility_enriched: int
    hybrids_found: int
    unmatched_names: tuple[str, ...] = ()

    @property
    def value_join_rate(self) -> float:
        return (self.valued / self.rostered) if self.rostered else 0.0

    @property
    def eligibility_join_rate(self) -> float:
        return (self.eligibility_enriched / self.rostered) if self.rostered else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rostered": self.rostered,
            "valued": self.valued,
            "eligibilityEnriched": self.eligibility_enriched,
            "hybridsFound": self.hybrids_found,
            "valueJoinRate": round(self.value_join_rate, 4),
            "eligibilityJoinRate": round(self.eligibility_join_rate, 4),
            "unmatchedNames": list(self.unmatched_names),
        }


def build_value_index(
    aggregate_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    """``normalized name -> ROS row``.

    The WS-E audit found duplicate rows in the aggregate (the same
    player under two spellings, ROS value split across both).  On a
    collision the HIGHER-valued row wins: the split is an artifact of
    the identity defect, and taking whichever row happens to be last
    would make the result depend on file ordering.
    """
    out: dict[str, Mapping[str, Any]] = {}
    for row in aggregate_rows:
        key = compact_name_key(row.get("canonicalName") or row.get("name"))
        if not key:
            continue
        prev = out.get(key)
        if prev is not None:
            try:
                if float(row.get("rosValue") or 0.0) <= float(prev.get("rosValue") or 0.0):
                    continue
            except (TypeError, ValueError):
                continue
        out[key] = row
    return out


def build_nfl_position_index(
    nfl_players: Mapping[str, Mapping[str, Any]],
) -> dict[str, tuple[str, tuple[str, ...]]]:
    """``normalized name -> (position, fantasy_positions)``.

    Keyed by name rather than Sleeper id because the ROS aggregate is
    name-keyed; the identity layer owns id-grade joins, and duplicating
    it here would be a second source of truth.
    """
    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    for entry in nfl_players.values():
        if not isinstance(entry, Mapping):
            continue
        name = entry.get("full_name") or (
            f"{entry.get('first_name') or ''} {entry.get('last_name') or ''}".strip()
        )
        key = compact_name_key(name)
        if not key:
            continue
        fpos = tuple(
            str(fp).strip().upper()
            for fp in (entry.get("fantasy_positions") or ())
            if str(fp or "").strip()
        )
        position = str(entry.get("position") or "").strip().upper()
        # Prefer the entry that actually carries eligibility data; the
        # dump contains retired/duplicate shells with none.
        prev = out.get(key)
        if prev is not None and not fpos and prev[1]:
            continue
        out[key] = (position, fpos)
    return out


def build_roster_pool(
    roster_names: Sequence[str],
    *,
    values: Mapping[str, Mapping[str, Any]],
    eligibility: Mapping[str, tuple[str, tuple[str, ...]]],
) -> tuple[list[dict[str, Any]], JoinReport]:
    """Assemble optimizer-ready rows for one roster.

    ``eligibility`` is REQUIRED, not optional.  Making it optional is
    exactly how the ADR-007 defect came back: a caller omits it, the
    rows still look valid, the optimizer still runs, and the only
    symptom is a quietly worse lineup for teams with hybrid IDPs.

    Returns the rows plus a :class:`JoinReport` so callers can assert
    the join landed instead of trusting it.
    """
    rows: list[dict[str, Any]] = []
    unmatched: list[str] = []
    enriched = 0
    hybrids = 0

    for name in roster_names:
        key = compact_name_key(name)
        val_row = values.get(key)
        if val_row is None:
            unmatched.append(str(name))
            continue

        elig = eligibility.get(key)
        # Position precedence: the NFL dump is the host's own view and
        # wins over the aggregate's, which is scraped from ranking
        # sites and disagrees on IDP labelling in particular.
        position = str(val_row.get("position") or "").strip().upper()
        fantasy_positions: tuple[str, ...] = ()
        if elig is not None:
            dump_pos, fpos = elig
            if dump_pos:
                position = dump_pos
            fantasy_positions = fpos
            if fpos:
                enriched += 1
                if len(fpos) > 1:
                    hybrids += 1

        rows.append(
            {
                "playerId": str(name),
                "canonicalName": str(name),
                "position": position,
                "rosValue": float(val_row.get("rosValue") or 0.0),
                "confidence": float(val_row.get("confidence") or 0.0),
                "fantasyPositions": fantasy_positions,
            }
        )

    return rows, JoinReport(
        rostered=len(roster_names),
        valued=len(rows),
        eligibility_enriched=enriched,
        hybrids_found=hybrids,
        unmatched_names=tuple(unmatched),
    )


@dataclass(frozen=True)
class HybridCoverage:
    """Proof that eligibility enrichment actually happened.

    ``multi_family_without_eligibility`` is the number that matters: a
    DL/LB/DB-family player carrying no ``fantasy_positions`` is one the
    optimizer may bench illegally.  Zero is the target; anything else is
    a known lower bound on IDP marginals and must be reported as such.
    """

    total: int
    multi_family: int
    multi_family_with_eligibility: int
    multi_family_without_eligibility: int
    true_hybrids: int

    @property
    def eligibility_complete(self) -> bool:
        return self.multi_family_without_eligibility == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "multiFamily": self.multi_family,
            "multiFamilyWithEligibility": self.multi_family_with_eligibility,
            "multiFamilyWithoutEligibility": self.multi_family_without_eligibility,
            "trueHybrids": self.true_hybrids,
            "eligibilityComplete": self.eligibility_complete,
        }


def hybrid_coverage(rows: Iterable[Mapping[str, Any]]) -> HybridCoverage:
    """Audit a built pool for missing slot eligibility."""
    total = mf = mf_with = hybrids = 0
    for r in rows:
        total += 1
        pos = str(r.get("position") or "").strip().upper()
        fpos = tuple(r.get("fantasyPositions") or ())
        if pos in _MULTI_FAMILY:
            mf += 1
            if fpos:
                mf_with += 1
        if len(fpos) > 1:
            hybrids += 1
    return HybridCoverage(
        total=total,
        multi_family=mf,
        multi_family_with_eligibility=mf_with,
        multi_family_without_eligibility=mf - mf_with,
        true_hybrids=hybrids,
    )
