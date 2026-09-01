"""Best Available IDPs — a two-source waiver decision lens.

Answers one narrow question for the Waivers page: among IDP players NOT
rostered by any team in the selected league, who ranks highest on an
equal-weight combination of exactly two named sources — **IDP Trade
Calculator** (``idpTradeCalc``) and **The IDP Show** (``idpShowCombined``)?

This is a PRESENTATION/DECISION LENS, not a canonical valuation concept.
It never reads or writes ``rankDerivedValue``, ``canonicalConsensusRank``,
``sourceCount``, or any other ranking source. It reuses the canonical
identity (one contract row per real player), canonical position
normalization (``DL``/``LB``/``DB`` families, already collapsed upstream),
and the canonical rostered-player set (``src.trade.waiver.rostered_name_set``)
rather than inventing any of the three.

Methodology
-----------
Each source's raw signal is converted to a DENSE rank within its own
IDP-only population (rostered AND unrostered players both counted — the
percentile question is "how good is this player per this source", which is
independent of availability):

* ``idpTradeCalc`` is value-based (``canonicalSiteValues.idpTradeCalc``,
  0-9999 scale, also covers offense/picks) — sorted descending by value.
* ``idpShowCombined`` is rank-based (``sourceOriginalRanks.idpShowCombined``)
  but that raw ordinal spans the vendor's COMBINED offense+IDP chart, not
  an IDP-only ordinal — sorted ascending by that raw rank to produce a
  clean 1..N IDP-only rank.

Each dense rank converts to a 0-100 score via a small formula LOCAL to this
module rather than ``src.canonical.player_valuation.rank_to_percentile`` —
that function is tuned for the whole multi-source board blend (fixed
``reference_n=500``, tail-clamp policy around rank 904) and its own
docstring says callers should almost never override ``reference_n``.
Coupling a narrow two-source waiver lens to those constants would import
board-blend behavior that has nothing to do with this question.

Tiering never fills a missing source with zero, an average, or a guess:

* Tier A — both sources cover the player: ``combined = mean(score_a, score_b)``.
* Tier B — exactly one source covers the player: ``combined = that score``.
* Neither source covers the player: not a candidate at all.

Selection is TIER-FIRST, then score, so a strong single-source outlier can
never displace a genuine two-source consensus player — the owner's explicit
requirement that "if at least 20 legitimately available players have both
sources, the Top 20 should consist entirely of two-source players."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.trade.waiver import _normalize_name, rostered_name_set

_IDP_POSITIONS = frozenset({"DL", "LB", "DB"})

_IDPTC_KEY = "idpTradeCalc"
_IDPSHOW_KEY = "idpShowCombined"


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _population_score(rank: int, population_size: int) -> float:
    """Dense rank -> 0-100, higher is better. Rank 1 -> 100.0."""
    if population_size <= 1:
        return 100.0
    return round(100.0 * (population_size - rank) / (population_size - 1), 2)


@dataclass
class _SourceReading:
    row_index: int
    raw: float


@dataclass
class IdpCandidate:
    name: str
    team: str | None
    position: str
    tier: str  # "A" | "B"
    combined_score: float
    sources_used: int
    idptc_rank: int | None
    idptc_raw_value: float | None
    idptc_score: float | None
    idpshow_rank: int | None
    idpshow_raw_rank: float | None
    idpshow_score: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "team": self.team,
            "position": self.position,
            "tier": self.tier,
            "combinedScore": self.combined_score,
            "sourcesUsed": self.sources_used,
            "idpTradeCalc": {
                "rank": self.idptc_rank,
                "rawValue": self.idptc_raw_value,
                "score": self.idptc_score,
            },
            "idpShowCombined": {
                "rank": self.idpshow_rank,
                "rawRank": self.idpshow_raw_rank,
                "score": self.idpshow_score,
            },
        }

    def _sort_key(self) -> tuple[int, float, float, float, str]:
        worst_source_score = (
            min(self.idptc_score, self.idpshow_score)
            if self.tier == "A" and self.idptc_score is not None and self.idpshow_score is not None
            else self.combined_score
        )
        idptc_tiebreak = self.idptc_score if self.idptc_score is not None else -1.0
        return (
            0 if self.tier == "A" else 1,
            -self.combined_score,
            -worst_source_score,
            -idptc_tiebreak,
            self.name.lower(),
        )


def best_available_idp(
    contract: dict[str, Any],
    sleeper_teams: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Rank available IDP free agents by IDPTradeCalc + The IDP Show, 50/50.

    Returns the FULL sorted candidate list (never pre-sliced to 20) so
    callers can safely re-filter by position and THEN slice — each
    candidate's score is computed against its source's whole IDP
    population, independent of any later position filter.
    """
    arr = contract.get("playersArray") if isinstance(contract, dict) else None
    if not isinstance(arr, list):
        arr = []

    ownership_resolved = isinstance(sleeper_teams, list) and len(sleeper_teams) > 0
    if not ownership_resolved:
        return {
            "ownershipResolved": False,
            "candidates": [],
            "availableCount": 0,
            "sources": {
                _IDPTC_KEY: {"populationSize": 0},
                _IDPSHOW_KEY: {"populationSize": 0},
            },
            "degraded": {
                "ownershipUnresolved": True,
                "missingSources": [],
            },
        }

    rostered = rostered_name_set(sleeper_teams)

    # Collect the full IDP-only population per source (rostered AND
    # unrostered rows both counted) so percentile position reflects "how
    # good is this player per this source", independent of availability.
    idptc_readings: list[_SourceReading] = []
    idpshow_readings: list[_SourceReading] = []

    for idx, row in enumerate(arr):
        if not isinstance(row, dict):
            continue
        if row.get("assetClass") == "pick":
            continue
        pos = str(row.get("position") or "").strip().upper()
        if pos not in _IDP_POSITIONS:
            continue

        site_values = row.get("canonicalSiteValues")
        if isinstance(site_values, dict):
            raw_value = _coerce_float(site_values.get(_IDPTC_KEY))
            if raw_value is not None:
                idptc_readings.append(_SourceReading(row_index=idx, raw=raw_value))

        orig_ranks = row.get("sourceOriginalRanks")
        if isinstance(orig_ranks, dict):
            raw_rank = _coerce_float(orig_ranks.get(_IDPSHOW_KEY))
            if raw_rank is not None:
                idpshow_readings.append(_SourceReading(row_index=idx, raw=raw_rank))

    idptc_population = len(idptc_readings)
    idpshow_population = len(idpshow_readings)

    # Dense rank: idpTradeCalc descending by value, idpShowCombined
    # ascending by its raw (combined-board) rank.
    idptc_score_by_row: dict[int, tuple[int, float, float]] = {}
    for dense_rank, reading in enumerate(sorted(idptc_readings, key=lambda r: -r.raw), start=1):
        score = _population_score(dense_rank, idptc_population)
        idptc_score_by_row[reading.row_index] = (dense_rank, reading.raw, score)

    idpshow_score_by_row: dict[int, tuple[int, float, float]] = {}
    for dense_rank, reading in enumerate(sorted(idpshow_readings, key=lambda r: r.raw), start=1):
        score = _population_score(dense_rank, idpshow_population)
        idpshow_score_by_row[reading.row_index] = (dense_rank, reading.raw, score)

    candidates: list[IdpCandidate] = []
    for idx, row in enumerate(arr):
        if not isinstance(row, dict):
            continue
        idptc_entry = idptc_score_by_row.get(idx)
        idpshow_entry = idpshow_score_by_row.get(idx)
        if idptc_entry is None and idpshow_entry is None:
            continue

        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if not name:
            continue
        if _normalize_name(name) in rostered:
            continue

        pos = str(row.get("position") or "").strip().upper()
        team = row.get("team")

        idptc_rank = idptc_raw = idptc_score = None
        if idptc_entry is not None:
            idptc_rank, idptc_raw, idptc_score = idptc_entry

        idpshow_rank = idpshow_raw = idpshow_score = None
        if idpshow_entry is not None:
            idpshow_rank, idpshow_raw, idpshow_score = idpshow_entry

        sources_used = int(idptc_entry is not None) + int(idpshow_entry is not None)
        if sources_used == 2:
            tier = "A"
            combined = round((idptc_score + idpshow_score) / 2.0, 1)
        else:
            tier = "B"
            combined = round(idptc_score if idptc_score is not None else idpshow_score, 1)

        candidates.append(
            IdpCandidate(
                name=name,
                team=str(team) if team else None,
                position=pos,
                tier=tier,
                combined_score=combined,
                sources_used=sources_used,
                idptc_rank=idptc_rank,
                idptc_raw_value=idptc_raw,
                idptc_score=idptc_score,
                idpshow_rank=idpshow_rank,
                idpshow_raw_rank=idpshow_raw,
                idpshow_score=idpshow_score,
            )
        )

    candidates.sort(key=lambda c: c._sort_key())

    missing_sources = []
    if idptc_population == 0:
        missing_sources.append(_IDPTC_KEY)
    if idpshow_population == 0:
        missing_sources.append(_IDPSHOW_KEY)

    return {
        "ownershipResolved": True,
        "candidates": [c.to_dict() for c in candidates],
        "availableCount": len(candidates),
        "sources": {
            _IDPTC_KEY: {"populationSize": idptc_population},
            _IDPSHOW_KEY: {"populationSize": idpshow_population},
        },
        "degraded": {
            "ownershipUnresolved": False,
            "missingSources": missing_sources,
        },
    }
