"""Disagreement-preserving outlier policy (``outlier-corroborated-v1``; DEFAULT OFF).

Owner directive 2026-10-19 ("Universal source voting and freshness", §6): a
source must not be removed merely because it ranks a player much higher or lower
than the others -- "three sites around 5,000 and Draft Sharks at 3,000 does not
make Draft Sharks wrong" -- while corrupted, misidentified or improperly
normalized observations must still be caught.

The incumbent per-player Hampel filter (``data_contract._hampel_filter_per_player``)
cannot make that distinction. Its scale estimate is the median absolute deviation
of the row's votes, and on most rows several votes are near-identical by
construction (value-direct sources share one market; the IDP rank boards are
translated onto one backbone, so DLF IDP and FantasyPros IDP land on the IDP
Trade Calculator's exact value whenever they agree on the ordinal). The MAD then
collapses and the threshold degenerates to the fixed 1,000-point floor, so the
rule becomes "drop any vote more than 1,000 Hill points from the median" -- a
band that is ~12% of value at the top of the board and meaningless in the tail.
A fourth IDP voter is what switches it on (``_HAMPEL_MIN_N = 4``).

This module is the challenger, preregistered in
``docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md``
before it was run. It removes an observation only on EVIDENCE OF DATA ERROR:

1. **Per row: a gross, uncorroborated error.** Every vote is placed on one
   opinion coordinate, the rank its value implies on the row's own scope master
   curve, smoothed at the top: ``u = ln(RANK_OFFSET + N · p)`` with
   ``p = hill_inverse(value)`` and ``N = 500`` (the board's percentile reference).
   A factor-k disagreement in rank is the same distance at every depth below the
   top ``RANK_OFFSET`` ranks. A vote is rejected only when ALL hold:

   * the leave-family-out reference exists: at least ``MIN_OTHER_FAMILIES`` OTHER
     provider families voted (each family contributes the median of its
     members, so one provider's two boards are one voice);
   * it is GROSS: more than ``GROSS_RANK_FACTOR`` (4x) from the reference in
     ``u`` AND more than ``VALUE_FLOOR`` (the incumbent's 1,000 points) from the
     reference in value;
   * it is UNCORROBORATED: no other family sits within ``CORROBORATION_FACTOR``
     (2x) of it. Two independent providers sharing an outlying view is
     disagreement, never an error;
   * it is not the DOMINANT evidence: its family-capped weight is below half of
     the row's (a fresh observation is not removed by a stale cluster).

2. **Per board: a scale screen.** A whole board placed on the wrong scale is a
   normalization failure, not an opinion about players. For each
   ``(source, asset class)`` with at least ``BOARD_MIN_ROWS`` assessable rows,
   the median signed and the median absolute ``u`` deviation from the
   leave-family-out reference are measured; a board whose typical row sits more
   than ``BOARD_SHIFT_FACTOR`` (1.5x) away in one direction, or more than
   ``BOARD_SPREAD_FACTOR`` (2x) away in either, is flagged and its votes on that
   asset class are excluded (reason ``board_scale_mismatch``).

Guards shared by both: picks are never assessed (the incumbent's posture);
nothing is removed when fewer than two observations, or (on a multi-family row)
fewer than two families, would survive; a vote with
no finite coordinate is never assessed and never dropped (missing is never
zero). Results depend on the multiset of observations, never their order.

Pure functions; no I/O, no flag reads. ``data_contract`` calls :func:`assess_row`
in place of the incumbent filter and :func:`board_screen` once per build, only
when ``outlier_disagreement_policy`` is on.
"""

from __future__ import annotations

import copy
import math
import statistics
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

POLICY_VERSION = "outlier-corroborated-v1"

#: Rank smoothing at the top of the board: ranks below this compress, so "rank 1
#: vs rank 6" is not scored as a six-fold disagreement.
RANK_OFFSET = 10.0
#: Percentile reference of the board (``player_valuation.PERCENTILE_REFERENCE_N``).
REFERENCE_N = 500.0
#: A vote further than this factor (in smoothed implied rank) from the other
#: families' reference is GROSS.
GROSS_RANK_FACTOR = 4.0
#: Another family within this factor of a vote corroborates it.
CORROBORATION_FACTOR = 2.0
#: Value-space floor: a gross vote must also sit this far from the reference
#: value (the incumbent's ``_HAMPEL_MIN_THRESHOLD``; see ``data_contract``).
VALUE_FLOOR = 1000.0
#: Families other than the vote's needed to form a reference.
MIN_OTHER_FAMILIES = 2
#: A vote holding at least this share of the row's capped weight is never dropped.
DOMINANT_SHARE = 0.5
#: Board screen: rows a (source, asset class) needs before it can be screened.
BOARD_MIN_ROWS = 20
#: Board screen: median signed deviation beyond ln(1.5) flags a shifted board.
BOARD_SHIFT_FACTOR = 1.5
#: Board screen: median absolute deviation beyond ln(2) flags a scrambled board.
BOARD_SPREAD_FACTOR = 2.0

REASON_GROSS = "gross_uncorroborated_error"
REASON_BOARD = "board_scale_mismatch"
KEPT_DOMINANT = "dominant_evidence_kept"
KEPT_SURVIVORS = "kept_to_preserve_two_survivors"

GROSS_DISTANCE = math.log(GROSS_RANK_FACTOR)
CORROBORATION_DISTANCE = math.log(CORROBORATION_FACTOR)
BOARD_SHIFT_DISTANCE = math.log(BOARD_SHIFT_FACTOR)
BOARD_SPREAD_DISTANCE = math.log(BOARD_SPREAD_FACTOR)


def constants() -> dict[str, Any]:
    """Every constant, for pins and stamps."""
    return {
        "version": POLICY_VERSION,
        "rankOffset": RANK_OFFSET,
        "referenceN": REFERENCE_N,
        "grossRankFactor": GROSS_RANK_FACTOR,
        "corroborationFactor": CORROBORATION_FACTOR,
        "valueFloor": VALUE_FLOOR,
        "minOtherFamilies": MIN_OTHER_FAMILIES,
        "dominantShare": DOMINANT_SHARE,
        "boardMinRows": BOARD_MIN_ROWS,
        "boardShiftFactor": BOARD_SHIFT_FACTOR,
        "boardSpreadFactor": BOARD_SPREAD_FACTOR,
    }


def hill_inverse(value: float, c: float, s: float) -> float:
    """Percentile coordinate of a Hill value (``V = 9999 / (1 + (p/c)^s)``).

    The exact inverse of ``player_valuation.percentile_to_value``; the same
    function as ``data_contract._hill_inverse`` (kept here so this module has no
    import-time dependency on the pipeline). A value at or above the ceiling is
    ``p = 0``; a non-positive value has no coordinate (``inf``).
    """
    if value >= 9999.0:
        return 0.0
    if value <= 0.0:
        return math.inf
    return c * (9999.0 / value - 1.0) ** (1.0 / s)


def rank_coordinate(value: Any, curve: tuple[float, float]) -> float | None:
    """``u = ln(RANK_OFFSET + N · p)`` for a vote, or ``None`` when it has none."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        return None
    p = hill_inverse(v, float(curve[0]), float(curve[1]))
    if not math.isfinite(p):
        return None
    return math.log(RANK_OFFSET + REFERENCE_N * p)


@dataclass(frozen=True)
class Reference:
    """The leave-family-out reference for one vote."""

    coordinate: float
    value: float
    families: int
    nearest_family_distance: float


def _median(xs: Sequence[float]) -> float:
    """The ordinary median (equal to ``statistics.median``; faster on short lists)."""
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return s[m] if n % 2 else (s[m - 1] + s[m]) / 2.0


def family_medians(
    coords: Mapping[str, float],
    values: Mapping[str, float],
    family_of: Callable[[str], str],
) -> dict[str, tuple[float, float]]:
    """``{family: (median coordinate, median value)}`` over the votes in ``coords``."""
    by_u: dict[str, list[float]] = defaultdict(list)
    by_v: dict[str, list[float]] = defaultdict(list)
    for key, u in coords.items():
        fam = family_of(key)
        by_u[fam].append(u)
        by_v[fam].append(values[key])
    return {fam: (_median(us), _median(by_v[fam])) for fam, us in by_u.items()}


def leave_family_out(
    key: str,
    coords: Mapping[str, float],
    values: Mapping[str, float],
    family_of: Callable[[str], str],
    *,
    families: Mapping[str, tuple[float, float]] | None = None,
) -> Reference | None:
    """Equal-family median of the OTHER families' votes, or ``None`` below the minimum.

    Each other family contributes the median of its members' coordinates (and
    values); the reference is the median of those family medians. Unweighted on
    purpose: the reference asks where the other providers place the player, not
    how much authority they carry. ``families`` (from :func:`family_medians` over
    the same ``coords``) saves recomputing them per vote.
    """
    fams = families if families is not None else family_medians(coords, values, family_of)
    own = family_of(key)
    others = [uv for fam, uv in fams.items() if fam != own]
    if len(others) < MIN_OTHER_FAMILIES:
        return None
    u_k = coords[key]
    return Reference(
        coordinate=_median([u for u, _v in others]),
        value=_median([v for _u, v in others]),
        families=len(others),
        nearest_family_distance=min(abs(u_k - u) for u, _v in others),
    )


@dataclass(frozen=True)
class RowVerdict:
    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)
    details: dict[str, dict[str, float]] = field(default_factory=dict)


def assess_row(
    pairs: Sequence[tuple[str, float]],
    *,
    curve: tuple[float, float],
    family_of: Callable[[str], str],
    weights: Mapping[str, float] | None = None,
    board_excluded: Iterable[str] = (),
) -> RowVerdict:
    """The policy's keep / drop decision for one non-pick row.

    ``pairs`` are the row's voting ``(source, board-scale value)`` observations;
    ``weights`` their family-capped effective weights (absent → equal);
    ``board_excluded`` the sources :func:`board_screen` flagged for this row's
    asset class. Returns kept / dropped keys in input order, a reason per dropped
    key (and per candidate a guard kept), and the per-vote measurements behind
    each gross verdict.
    """
    keys = [k for k, _v in pairs]
    values = {k: float(v) for k, v in pairs}
    coords: dict[str, float] = {}
    for k, v in pairs:
        u = rank_coordinate(v, curve)
        if u is not None:
            coords[k] = u
    excluded = {k for k in board_excluded if k in values}
    # A board the screen flagged is invalid data: it is not a reference for
    # anyone else on the row either.
    ref_coords = {k: u for k, u in coords.items() if k not in excluded}
    reasons: dict[str, str] = {}
    details: dict[str, dict[str, float]] = {}
    gross: set[str] = set()
    w = {k: max(0.0, float((weights or {}).get(k, 1.0))) for k in keys}
    total_w = sum(w.values())
    fams = family_medians(ref_coords, values, family_of)
    for k in keys:
        if k in excluded or k not in coords:
            continue
        ref = leave_family_out(k, ref_coords, values, family_of, families=fams)
        if ref is None:
            continue
        dist = coords[k] - ref.coordinate
        details[k] = {
            "distance": round(dist, 4),
            "referenceValue": round(ref.value, 1),
            "nearestFamily": round(ref.nearest_family_distance, 4),
            "otherFamilies": float(ref.families),
        }
        if (
            abs(dist) > GROSS_DISTANCE
            and abs(values[k] - ref.value) > VALUE_FLOOR
            and ref.nearest_family_distance > CORROBORATION_DISTANCE
        ):
            if total_w > 0 and w[k] / total_w >= DOMINANT_SHARE:
                reasons[k] = KEPT_DOMINANT
                continue
            gross.add(k)
    drop = excluded | gross
    families_present = {family_of(k) for k in keys}
    families_left = {family_of(k) for k in keys if k not in drop}
    if len(keys) - len(drop) < 2 or (len(families_present) >= 2 and len(families_left) < 2):
        for k in sorted(drop):
            reasons[k] = KEPT_SURVIVORS
        return RowVerdict(kept=tuple(keys), dropped=(), reasons=reasons, details=details)
    for k in drop:
        reasons[k] = REASON_BOARD if k in excluded else REASON_GROSS
    return RowVerdict(
        kept=tuple(k for k in keys if k not in drop),
        dropped=tuple(k for k in keys if k in drop),
        reasons=reasons,
        details=details,
    )


@dataclass(frozen=True)
class BoardRow:
    """One non-pick row's votes, as :func:`board_screen` reads them."""

    asset_class: str
    curve: tuple[float, float]
    votes: Mapping[str, float]


def board_screen(
    rows: Iterable[BoardRow],
    family_of: Callable[[str], str],
) -> dict[str, Any]:
    """Per ``(source, asset class)`` scale statistics and the flagged set.

    Returns ``{"flagged": {asset_class: [source, ...]}, "stats": {"source|class":
    {...}}}``. A board is screened only with at least ``BOARD_MIN_ROWS`` rows on
    which the vote has a coordinate and a leave-family-out reference.
    """
    devs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        values = {k: float(v) for k, v in row.votes.items()}
        coords = {}
        for k, v in values.items():
            u = rank_coordinate(v, row.curve)
            if u is not None:
                coords[k] = u
        fams = family_medians(coords, values, family_of)
        for k in coords:
            ref = leave_family_out(k, coords, values, family_of, families=fams)
            if ref is not None:
                devs[(k, row.asset_class)].append(coords[k] - ref.coordinate)
    flagged: dict[str, list[str]] = defaultdict(list)
    stats: dict[str, dict[str, Any]] = {}
    for (source, asset_class), ds in sorted(devs.items()):
        signed = statistics.median(ds)
        spread = statistics.median(abs(d) for d in ds)
        screened = len(ds) >= BOARD_MIN_ROWS
        flag = screened and (abs(signed) > BOARD_SHIFT_DISTANCE or spread > BOARD_SPREAD_DISTANCE)
        stats[f"{source}|{asset_class}"] = {
            "rows": len(ds),
            "medianSigned": round(signed, 4),
            "medianAbsolute": round(spread, 4),
            "screened": screened,
            "flagged": flag,
        }
        if flag:
            flagged[asset_class].append(source)
    return {"flagged": {k: sorted(v) for k, v in sorted(flagged.items())}, "stats": stats}


def scope_curve(asset_class: Any) -> tuple[float, float]:
    """The scope master a row's votes are placed on: IDP rows the IDP master,
    every other row the OFFENSE master (``rank-space-hampel-v1``'s selection)."""
    from src.canonical import player_valuation as pv  # noqa: PLC0415

    if asset_class == "idp":
        return (pv.IDP_HILL_PERCENTILE_C, pv.IDP_HILL_PERCENTILE_S)
    return (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S)


def replay_dropped(
    *,
    curve: tuple[float, float],
    family_of: Callable[[str], str],
    board_excluded: Iterable[str] = (),
) -> Callable[[Sequence[tuple[str, float]]], list[str]]:
    """The policy as an unweighted replay, for the lost-evidence seats
    (``data_contract._lost_evidence_seats``): which observations the policy
    rejects on a panel that includes withheld votes."""
    excluded = tuple(board_excluded)

    def _replay(observed: Sequence[tuple[str, float]]) -> list[str]:
        verdict = assess_row(
            list(observed), curve=curve, family_of=family_of, board_excluded=excluded
        )
        return list(verdict.dropped)

    return _replay


def stamped_votes(row: Mapping[str, Any]) -> dict[str, float]:
    """``{source: vote}`` for every observation that voted on a built row."""
    out: dict[str, float] = {}
    for source, meta in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(meta, Mapping) or meta.get("excludedReason"):
            continue
        value = meta.get("valueContribution")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            out[str(source)] = float(value)
    return out


def board_rows(players_array: Iterable[Mapping[str, Any]]) -> list[BoardRow]:
    """Every non-pick row of a ranked board as :class:`BoardRow`."""
    out = []
    for row in players_array:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        asset_class = str(row.get("assetClass") or "")
        out.append(BoardRow(asset_class, scope_curve(asset_class), stamped_votes(row)))
    return out


def rank_with_board_screen(
    rank_once: Callable[[Mapping[str, Sequence[str]]], Any],
    players_array: list[Any],
    players_by_name: dict[str, Any],
    *,
    family_of: Callable[[str], str],
) -> tuple[Any, dict[str, Any]]:
    """Run the ranking, screen the boards it priced, and re-run once if needed.

    ``rank_once(exclusions)`` ranks ``players_array`` / ``players_by_name`` in
    place with ``{asset_class: [source, ...]}`` excluded by the board screen.
    The votes are computed before any filter, so the first pass's votes ARE the
    second pass's: the screen is exact. A healthy board costs one deep copy of
    the two inputs; a flagged one restores them in place and ranks again.
    Returns ``(rank_once result, contract stamp)``.
    """
    snapshot = copy.deepcopy((players_array, players_by_name))
    result = rank_once({})
    screen = board_screen(board_rows(players_array), family_of)
    passes = 1
    if screen["flagged"]:
        array0, by_name0 = snapshot
        players_array[:] = array0
        players_by_name.clear()
        players_by_name.update(by_name0)
        result = rank_once(screen["flagged"])
        passes = 2
    return result, {
        "version": POLICY_VERSION,
        "constants": constants(),
        "boardScreen": screen,
        "rankingPasses": passes,
    }
