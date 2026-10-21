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
from dataclasses import dataclass, field, replace
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


# ═══════════════════════════════════════════════════════════════════════════
# outlier-integrity-v2, Layer C: legitimate disagreement (DEFAULT OFF)
# ═══════════════════════════════════════════════════════════════════════════
#
# Preregistered in ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §3.3
# (commit ``3c69945723``) before it was implemented; design in
# ``docs/sources/OUTLIER_INTEGRITY_V2_ARCHITECTURE.md`` §6. V1 above
# (``assess_row`` / ``board_screen``) is untouched and stays selectable for
# replay; the incumbent Hampel filter in ``data_contract`` is untouched too.
#
# Layer C runs AFTER Layers A (identity) and B (source integrity) have removed
# every observation with a non-statistical defect, so what reaches it is an
# opinion. It asks one narrow question: is this vote so far from EVERY other
# provider -- while two independent providers agree with each other -- that it
# cannot be an opinion anyone shares, and has the source never said it before?
# Everything else votes at its established weight.
#
# What it deliberately does NOT have, because each is the measured root cause
# of the incumbent's legitimate-vote losses: no MAD, no scale estimated from
# the row it judges, no 1,000-point floor. Numerical similarity never merges
# providers (only declared lineage does, and only to REFUSE a pair as a
# reference), so identical synthetic values from several rank boards cannot
# narrow anything -- there is no band to narrow.
#
# Remove vote ``o`` only if ALL hold (simultaneous, pairwise, order-free):
#
# 1. the row has >= ``C_MIN_PROVIDERS`` providers
#    (``source_census.provider_of``: DLF's boards are one provider, KTC Crowd
#    and KTC Trades are one provider);
# 2. a corroborated reference: two votes of two DIFFERENT providers, neither
#    ``o``'s, within ``ln 2`` of each other, that are not a translated vote and
#    its own declared translation backbone;
# 3. ``o``'s nearest distance to any vote of another provider exceeds
#    ``tau_C`` (never below ``ln 4``);
# 4. ``o`` is not persistence-confirmed (>= 2 consecutive accepted
#    observations of this source for this player within ``tau_c`` of ``u_o``);
# 5. ``o``'s FAMILY holds less than half of the row's family-capped weight;
# 6. at least 2 providers survive (otherwise nothing is dropped on the row).
#
# Kept votes whose nearest other provider is further than ``ln 2`` are stamped
# ``kept_dissent``: information, never an exclusion and never "invalid".

LAYER_C_VERSION = "oiv2-layer-c-v1"
#: Guard 1: providers a row needs before any vote can be judged.
C_MIN_PROVIDERS = 3
#: Guard 2 (and the ``kept_dissent`` stamp): two providers within this
#: distance corroborate each other.
C_CORROBORATION_DISTANCE = math.log(2.0)
#: Guard 3 hard floor: ``tau_C`` is never below ``ln 4`` (preregistration §3.5).
C_TAU_FLOOR = math.log(4.0)
#: Guard 3 provisional value until the Stage 2 freeze: the LARGEST registered
#: grid point ({ln 4, ln 5, ln 6}) -- the fewest drops.
C_TAU_PROVISIONAL = math.log(6.0)
#: Guard 4: accepted prior observations that confirm a contrarian view.
C_PERSISTENCE_MIN = 2
#: Guard 5: a family holding at least this share of the capped weight is kept.
C_DOMINANT_SHARE = 0.5
#: Guard 6: providers that must survive the row's drops.
C_MIN_SURVIVING_PROVIDERS = 2

REASON_TAIL = "extreme_uncorroborated_tail"
KEPT_DISSENT = "kept_dissent"
#: Why a guard-3 candidate was kept (recorded beside ``kept_dissent``).
C_KEPT_NO_REFERENCE = "no_corroborated_reference"
C_KEPT_PERSISTENT = "persistence_confirmed"
C_KEPT_DOMINANT = "dominant_family"
C_KEPT_SURVIVORS = "kept_to_preserve_two_providers"
C_KEPT_FEW_PROVIDERS = "fewer_than_three_providers"


def layer_c_constants(tau_c_big: float) -> dict[str, Any]:
    """Every Layer C constant, for pins and stamps."""
    return {
        "version": LAYER_C_VERSION,
        "rankOffset": RANK_OFFSET,
        "referenceN": REFERENCE_N,
        "minProviders": C_MIN_PROVIDERS,
        "corroborationDistance": round(C_CORROBORATION_DISTANCE, 6),
        "tauC": round(effective_tau_c_big(tau_c_big), 6),
        "tauCFloor": round(C_TAU_FLOOR, 6),
        "persistenceMin": C_PERSISTENCE_MIN,
        "dominantShare": C_DOMINANT_SHARE,
        "minSurvivingProviders": C_MIN_SURVIVING_PROVIDERS,
    }


def effective_tau_c_big(tau_c_big: float | None) -> float:
    """``tau_C`` as Layer C applies it: never below the ``ln 4`` floor; a
    missing or non-finite value is the provisional ``ln 6`` (fewest drops)."""
    if tau_c_big is None or not math.isfinite(float(tau_c_big)):
        return C_TAU_PROVISIONAL
    return max(C_TAU_FLOOR, float(tau_c_big))


@dataclass(frozen=True)
class LayerCVerdict:
    """Layer C's decision on one row.

    ``kept`` / ``dropped``: source keys in input order. ``reasons``: the drop
    reason per dropped key (``extreme_uncorroborated_tail``). ``dissent``:
    ``kept_dissent`` per kept vote further than ``ln 2`` from every other
    provider, with ``kept_because`` naming the guard that kept a guard-3
    candidate. ``details``: the measurements behind each verdict.
    """

    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    reasons: dict[str, str] = field(default_factory=dict)
    dissent: dict[str, str] = field(default_factory=dict)
    kept_because: dict[str, str] = field(default_factory=dict)
    details: dict[str, dict[str, Any]] = field(default_factory=dict)


def _family_shares(
    keys: Sequence[str],
    weights: Mapping[str, float] | None,
    family_of: Callable[[str], str],
) -> dict[str, float]:
    """``{family: share of the row's (already family-capped) weight}``; equal
    weights when none are given."""
    w = {k: max(0.0, float((weights or {}).get(k, 1.0))) for k in keys}
    total = sum(w.values())
    out: dict[str, float] = defaultdict(float)
    if total <= 0.0:
        return dict(out)
    for k, x in w.items():
        out[family_of(k)] += x / total
    return dict(out)


def assess_row_layer_c(
    pairs: Sequence[tuple[str, float]],
    *,
    curve: tuple[float, float],
    provider_of: Callable[[str], str],
    family_of: Callable[[str], str],
    weights: Mapping[str, float] | None = None,
    linked: Callable[[str, str], bool] | None = None,
    persistence_confirmed: Callable[[str, float], bool] | None = None,
    tau_c_big: float | None = None,
    weights_fn: Callable[[], Mapping[str, float]] | None = None,
) -> LayerCVerdict:
    """Layer C's keep / drop decision for one non-pick row.

    ``pairs``: the row's voting ``(source, board-scale value)`` observations
    AFTER Layers A and B. ``weights``: their family-capped effective weights
    (absent -> equal). ``linked(a, b)``: True when ``a`` and ``b`` are a
    translated vote and its own declared translation backbone (declared
    lineage only; never numerical similarity). ``persistence_confirmed(k, u)``:
    True when source ``k``'s own accepted history confirms coordinate ``u``
    (absent -> never confirmed: the cold-start rule). ``tau_c_big``: guard 3's
    threshold (clamped at ``ln 4``).

    ``weights_fn`` (used only when ``weights`` is ``None``) supplies the same
    weights lazily: guard 4 is the only reader, so a row where no vote reaches
    it never computes them (V2.1 R13 performance; identical decisions).

    Pure: no I/O, no flag reads; the decision depends on the multiset of
    observations, never their order.
    """
    tau = effective_tau_c_big(tau_c_big)
    keys = [k for k, _v in pairs]
    coords: dict[str, float] = {}
    for k, v in pairs:
        u = rank_coordinate(v, curve)
        if u is not None:
            coords[k] = u
    prov = {k: provider_of(k) for k in keys}
    providers_present = set(prov.values())
    is_linked = linked or (lambda _a, _b: False)
    confirmed = persistence_confirmed or (lambda _k, _u: False)
    _shares: list[dict[str, float]] = []

    def _share_of(family: str) -> float:
        if not _shares:
            w = weights if weights is not None or weights_fn is None else weights_fn()
            _shares.append(_family_shares(keys, w, family_of))
        return _shares[0].get(family, 0.0)

    dissent: dict[str, str] = {}
    kept_because: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    candidates: set[str] = set()
    ordered = sorted(coords)
    ordered_coords = [(k, prov[k], coords[k]) for k in ordered]
    # The nearest OTHER-provider vote of each vote, read off the votes sorted
    # by coordinate: it is the first other-provider vote on the left or on the
    # right (subtraction is monotone), so this is the same minimum as the scan
    # over every pair, in O(k log k) (V2.1 R13 performance).
    by_u = sorted(ordered_coords, key=lambda t: t[2])
    at = {t[0]: i for i, t in enumerate(by_u)}

    def _nearest(o: str, u_o: float, p_o: str) -> float | None:
        best: float | None = None
        i = at[o]
        for step in (-1, 1):
            j = i + step
            while 0 <= j < len(by_u):
                if by_u[j][1] != p_o:
                    d = abs(u_o - by_u[j][2])
                    if best is None or d < best:
                        best = d
                    break
                j += step
        return best

    for o in ordered:
        u_o = coords[o]
        p_o = prov[o]
        nearest = _nearest(o, u_o, p_o)
        if nearest is None:
            continue
        info: dict[str, Any] = {"nearestOtherProvider": round(nearest, 4)}
        details[o] = info
        if nearest > C_CORROBORATION_DISTANCE:
            dissent[o] = KEPT_DISSENT
        if nearest <= tau:
            continue
        others = [k for k, p_k, _u in ordered_coords if p_k != p_o]
        # Guard 3 met: the vote is further than tau_C from every other
        # provider. Every other guard must hold before it can be removed.
        info["tauC"] = round(tau, 4)
        if len(providers_present) < C_MIN_PROVIDERS:
            kept_because[o] = C_KEPT_FEW_PROVIDERS
            continue
        reference: tuple[str, str] | None = None
        for i, a in enumerate(others):
            for b in others[i + 1 :]:
                if prov[a] == prov[b]:
                    continue
                if abs(coords[a] - coords[b]) > C_CORROBORATION_DISTANCE:
                    continue
                if is_linked(a, b) or is_linked(b, a):
                    continue
                reference = (a, b)
                break
            if reference is not None:
                break
        if reference is None:
            kept_because[o] = C_KEPT_NO_REFERENCE
            continue
        info["reference"] = list(reference)
        if confirmed(o, u_o):
            kept_because[o] = C_KEPT_PERSISTENT
            continue
        share = _share_of(family_of(o))
        info["familyShare"] = round(share, 4)
        if share >= C_DOMINANT_SHARE:
            kept_because[o] = C_KEPT_DOMINANT
            continue
        candidates.add(o)

    surviving = {prov[k] for k in keys if k not in candidates}
    if candidates and len(surviving) < C_MIN_SURVIVING_PROVIDERS:
        for o in candidates:
            kept_because[o] = C_KEPT_SURVIVORS
        candidates = set()
    for o in candidates:
        dissent.pop(o, None)
    return LayerCVerdict(
        kept=tuple(k for k in keys if k not in candidates),
        dropped=tuple(k for k in keys if k in candidates),
        reasons={k: REASON_TAIL for k in sorted(candidates)},
        dissent=dict(sorted(dissent.items())),
        kept_because=dict(sorted(kept_because.items())),
        details=dict(sorted(details.items())),
    )


@dataclass(frozen=True)
class LayerCContext:
    """Everything Layer C needs about ONE row, built once and handed to every
    call site (the per-row filter slot, the B11 lost-evidence replay, the
    two-way alt-family center) so the three can never disagree.

    ``weights_for(keys)`` returns the family-capped weights of a panel (the
    caller's own ``cap_family_weights`` over its own per-source weights).
    """

    curve: tuple[float, float]
    provider_of: Callable[[str], str]
    family_of: Callable[[str], str]
    linked: Callable[[str, str], bool] | None = None
    persistence_confirmed: Callable[[str, float], bool] | None = None
    tau_c_big: float | None = None
    weights_for: Callable[[Sequence[str]], Mapping[str, float]] | None = None

    def assess(
        self,
        pairs: Sequence[tuple[str, float]],
        weights: Mapping[str, float] | None = None,
    ) -> LayerCVerdict:
        weights_fn = None
        if weights is None and self.weights_for is not None:
            weights_for = self.weights_for
            weights_fn = lambda: weights_for([k for k, _v in pairs])  # noqa: E731
        return assess_row_layer_c(
            pairs,
            curve=self.curve,
            provider_of=self.provider_of,
            family_of=self.family_of,
            weights=weights,
            linked=self.linked,
            persistence_confirmed=self.persistence_confirmed,
            tau_c_big=self.tau_c_big,
            weights_fn=weights_fn,
        )

    def replay(self) -> Callable[[Sequence[tuple[str, float]]], list[str]]:
        """Layer C as a replay over an observed panel (voting + withheld), for
        ``data_contract._lost_evidence_seats``: which observations it rejects."""

        def _replay(observed: Sequence[tuple[str, float]]) -> list[str]:
            return list(self.assess(list(observed)).dropped)

        return _replay


#: The class method as defined: a wrapped method (a replay call recorder)
#: makes ``LayerCMemo`` stand aside so the recorder sees every call.
_LAYER_C_ASSESS_ORIGINAL = LayerCContext.assess


class LayerCMemo:
    """V2.1 R13: Layer C's per-row decision memoized across builds.

    ``assess_row_layer_c`` is pure; through a ``LayerCContext`` it reads the
    ordered panel, the curve, ``tau_C``, each key's provider and family, and
    three lookups -- ``linked``, ``persistence_confirmed`` and the lazily
    computed family-capped weights.  The key holds the panel, the curve, the
    threshold and every key's provider and family; the lookups' answers are
    RECORDED on a miss and RE-ASKED on a hit.  A hit is therefore returned only
    when every input the original decision read is unchanged, so an identical
    rebuild (rankings overrides) re-decides nothing and any difference is a
    miss.  Bounded (cleared at ``max_entries``).  The verdict is shared, and
    every consumer only reads it.
    """

    def __init__(self, max_entries: int = 100_000) -> None:
        self.max_entries = max_entries
        self.entries: dict[tuple, tuple[LayerCVerdict, tuple]] = {}
        self.hits = 0
        self.misses = 0

    def assess(self, ctx: LayerCContext, pairs: Sequence[tuple[str, float]]) -> LayerCVerdict:
        if LayerCContext.assess is not _LAYER_C_ASSESS_ORIGINAL:
            return ctx.assess(pairs)
        keys = [k for k, _v in pairs]
        try:
            key = (
                tuple((str(k), float(v)) for k, v in pairs),
                tuple(ctx.curve),
                ctx.tau_c_big,
                tuple(ctx.provider_of(k) for k in keys),
                tuple(ctx.family_of(k) for k in keys),
                ctx.linked is None,
                ctx.persistence_confirmed is None,
                ctx.weights_for is None,
            )
            hit = self.entries.get(key)
        except (TypeError, ValueError):
            return ctx.assess(pairs)
        if hit is not None and all(self._answer(ctx, call) == ans for call, ans in hit[1]):
            self.hits += 1
            return hit[0]
        recorded: list[tuple[tuple, Any]] = []

        def _linked(a: str, b: str) -> bool:
            ans = ctx.linked(a, b)  # type: ignore[misc]
            recorded.append((("l", a, b), ans))
            return ans

        def _persist(k: str, u: float) -> bool:
            ans = ctx.persistence_confirmed(k, u)  # type: ignore[misc]
            recorded.append((("p", k, u), ans))
            return ans

        def _weights(ks: Sequence[str]) -> Mapping[str, float]:
            ans = dict(ctx.weights_for(ks))  # type: ignore[misc]
            recorded.append((("w", tuple(ks)), ans))
            return ans

        recording = replace(
            ctx,
            linked=_linked if ctx.linked is not None else None,
            persistence_confirmed=_persist if ctx.persistence_confirmed is not None else None,
            weights_for=_weights if ctx.weights_for is not None else None,
        )
        verdict = recording.assess(pairs)
        self.misses += 1
        if len(self.entries) >= self.max_entries:
            self.entries.clear()
        self.entries[key] = (verdict, tuple(recorded))
        return verdict

    @staticmethod
    def _answer(ctx: LayerCContext, call: tuple) -> Any:
        if call[0] == "l":
            return ctx.linked(call[1], call[2])  # type: ignore[misc]
        if call[0] == "p":
            return ctx.persistence_confirmed(call[1], call[2])  # type: ignore[misc]
        return dict(ctx.weights_for(list(call[1])))  # type: ignore[misc]
