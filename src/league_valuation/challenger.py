"""Brisket League Fair Value -- challenger ``league_fair_value_v1_shadow``.

A separately named, league-scoped SHADOW artifact. It shrinks the canonical
market value toward the league-utility ORDER, on the canonical 1-9999 scale, and
it is never written to a canonical field, never served, and never routed through
``server._valuation_scoped_contract`` or ``src/league_intel/{overlay,adjustment,
publish}.py``. Nothing in production imports this package (pinned by an
import-graph test).

The math, per scope population (OFFENSE QB/RB/WR/TE; IDP DL/LB/DB)::

    eligible  = structural eligibility (population.py) AND available evidence
    u_i       = (balanced DV, signed points over replacement)  -- BDVM's own output
    rank      = utility rank inside the population, midranks for ties
    m_i       = the canonical value occupying that rank among the SAME
                population's canonical values; a tie block takes the log-mean of
                the value block it spans
    k_i       = kMax * q_i            (PRIOR; q from utility evidence only)
    fair_i    = exp((1 - k_i) ln v_i + k_i ln m_i)

Properties that hold BY CONSTRUCTION (each pinned by a test, not by a grep):

* identical utility and market orders give ``m_i == v_i`` and so ``fair == v``
  exactly -- the structural no-op. A uniform shift of every utility number is an
  order-preserving change and moves nothing;
* ``fair_i`` lies between two observed in-population canonical values, so it
  sits inside ``[DISPLAY_SCALE_MIN, DISPLAY_SCALE_MAX]`` and never touches the
  Hill asymptote. The ±25% factor clamp of the withdrawn lens is unused;
* with ``k == 1`` for every row the population's multiset of log-values is
  preserved exactly (a permutation), so no centring constant exists. With
  row-varying ``k`` the drift is REPORTED (log and value space), never claimed
  to be zero;
* only the DISAGREEMENT between the league-utility order and the market order
  moves a row. Superflex and TE premium already priced into the market order
  cannot be re-added.

The IDP per-player component is admitted only when the IDP disagreement passes
``scoring_fit``'s depth fan-out stability test (reused read-only); otherwise
``k = 0`` for the whole IDP scope.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from src.canonical.player_valuation import DISPLAY_SCALE_MAX, DISPLAY_SCALE_MIN
from src.league_valuation.contracts import (
    FAIR_VALUE_STATE_AVAILABLE,
    FAIR_VALUE_STATE_EXCLUDED,
    MODEL_VERSION,
    SCOPES,
    TE_BASIS_LABEL,
    LeagueFairValue,
    UtilityEvidence,
)
from src.league_valuation.evidence import evidence_asset_key
from src.league_valuation.population import (
    eligible_rows,
    market_value_of,
    row_key,
    scope_of_row,
)
from src.utils.name_clean import normalize_position_family

#: Pins every board must carry. ``leagueKey`` is REQUIRED and never defaulted:
#: no code here resolves a league implicitly (``dynasty_new`` is never selected
#: by omission).
REQUIRED_PIN_KEYS: tuple[str, ...] = (
    "leagueKey",
    "scoringFingerprint",
    "formatFingerprint",
    "contractScrapeTimestamp",
    "contractVersion",
    "bdvmModelVersion",
    "bdvmParamSetId",
    "bdvmSnapshotAsOf",
    "challengerVersion",
    "challengerParamSetId",
)


#: Why the board carries no challenger rank or tier. The one ranker
#: (``data_contract.compact_ranks_and_tiers``) sorts on the canonical value
#: field, and a shadow challenger may never write that field -- not even on a
#: local copy (``tests/api/test_canonical_ownership_protections.py``). A second
#: ranker is equally forbidden. Ranks wait for an owner-approved serving seam.
RANKS_UNAVAILABLE_REASON = (
    "no_challenger_ranker: the one ranker sorts on the canonical value field, which a "
    "shadow challenger may not write; no second ranker exists"
)


class PinError(ValueError):
    """A board whose provenance cannot be stated (fail closed)."""


class ChallengerInvariantError(RuntimeError):
    """A structural invariant failed. Never clamped into a plausible number."""


@dataclass(frozen=True)
class FairValueBoard:
    values: dict[str, LeagueFairValue]
    diagnostics: Mapping[str, Any]
    pins: Mapping[str, str]
    model_version: str = MODEL_VERSION
    param_set_id: str = ""
    lineage_ids: tuple[str, ...] = ("league_fair_value",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelVersion": self.model_version,
            "paramSetId": self.param_set_id,
            "pins": dict(sorted(self.pins.items())),
            "lineageIds": list(self.lineage_ids),
            "shadowOnly": True,
            "values": {k: v.to_dict() for k, v in sorted(self.values.items())},
            "diagnostics": self.diagnostics,
        }


# ── pins ─────────────────────────────────────────────────────────────────────


def validate_pins(pins: Mapping[str, Any], params: Mapping[str, Any]) -> dict[str, str]:
    missing = [k for k in REQUIRED_PIN_KEYS if not str(pins.get(k) or "").strip()]
    if missing:
        raise PinError(f"board pins must be stated explicitly; missing {missing}")
    out = {k: str(v) for k, v in pins.items()}
    if out["challengerParamSetId"] != str(params.get("paramSetId")):
        raise PinError(
            "challengerParamSetId pin does not match the parameter set in use "
            f"({out['challengerParamSetId']!r} vs {params.get('paramSetId')!r})"
        )
    if out["challengerVersion"] != MODEL_VERSION:
        raise PinError(f"challengerVersion pin must be {MODEL_VERSION!r}")
    return out


def build_board_pins(
    contract: Mapping[str, Any],
    bdvm_payload: Mapping[str, Any],
    *,
    league_key: str,
    format_fingerprint: str | None,
    params: Mapping[str, Any],
) -> dict[str, str]:
    """Pins for one board, every one read from the artifact it describes.

    ``league_key`` is keyword-only and REQUIRED; it must agree with the
    contract's and the BDVM payload's own ``leagueKey``. The scoring fingerprint
    is recomputed from the contract's own ``sleeper.scoringSettings`` (factual
    identity, W18-F001) and must agree with ``meta.scoringFingerprint`` when that
    stamp exists; an unverifiable card fails closed. ``format_fingerprint`` is the
    caller's ``tmf1:`` identity (``src.trade.market_trade_format``); it is not
    derived here.
    """
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    key = str(league_key or "").strip()
    if not key:
        raise PinError("league_key is required; no league is resolved implicitly")
    meta = contract.get("meta") if isinstance(contract.get("meta"), Mapping) else {}
    bdvm_meta = bdvm_payload.get("meta") if isinstance(bdvm_payload.get("meta"), Mapping) else {}
    for label, stated in (
        ("contract", meta.get("leagueKey")),
        ("bdvm", bdvm_meta.get("leagueKey")),
    ):
        if str(stated or "") != key:
            raise PinError(f"{label} leagueKey {stated!r} does not match requested {key!r}")
    sleeper = contract.get("sleeper") if isinstance(contract.get("sleeper"), Mapping) else {}
    fingerprint = scoring_fingerprint(sleeper.get("scoringSettings"))
    if fingerprint is None:
        raise PinError("scoring identity unverifiable: the contract carries no usable card")
    stamped = meta.get("scoringFingerprint")
    if stamped and stamped != fingerprint:
        raise PinError(f"contract scoringFingerprint {stamped!r} disagrees with its card")
    fmt = str(format_fingerprint or "").strip()
    if not fmt.startswith("tmf1:"):
        raise PinError("formatFingerprint must be a tmf1 identity; unknown format fails closed")
    snap = bdvm_meta.get("projectionSnapshot")
    snap = snap if isinstance(snap, Mapping) else {}
    return validate_pins(
        {
            "leagueKey": key,
            "scoringFingerprint": fingerprint,
            "formatFingerprint": fmt,
            "contractScrapeTimestamp": str(
                contract.get("scrapeTimestamp") or contract.get("generatedAt") or ""
            ),
            "contractVersion": str(contract.get("contractVersion") or ""),
            "bdvmModelVersion": str(bdvm_meta.get("modelVersion") or ""),
            "bdvmParamSetId": str(bdvm_meta.get("paramSetId") or ""),
            "bdvmSnapshotAsOf": str(snap.get("asOf") or ""),
            "challengerVersion": MODEL_VERSION,
            "challengerParamSetId": str(params.get("paramSetId") or ""),
        },
        params,
    )


# ── core math ────────────────────────────────────────────────────────────────


def _log_mean(values: Sequence[float]) -> float:
    return math.exp(statistics.fmean(math.log(v) for v in values))


def quantile_match(
    market: Sequence[float], utility: Sequence[tuple[float, ...]]
) -> tuple[list[float], list[float]]:
    """``(matched values m_i, utility midranks)`` for one population.

    Rank 1 is the highest utility. ``m_i`` is the canonical value at the same
    position in the population's own descending value list; a utility tie block
    spanning positions ``[a, b)`` gives each member the log-mean of those
    values. Sorting is stable over input order, so the result is deterministic.
    """
    n = len(market)
    if n != len(utility):
        raise ValueError("market and utility must be the same length")
    sorted_values = sorted((float(v) for v in market), reverse=True)
    order = sorted(range(n), key=lambda i: utility[i], reverse=True)
    matched = [0.0] * n
    ranks = [0.0] * n
    pos = 0
    while pos < n:
        end = pos + 1
        while end < n and utility[order[end]] == utility[order[pos]]:
            end += 1
        block = sorted_values[pos:end]
        m = block[0] if len(block) == 1 else _log_mean(block)
        midrank = (pos + 1 + end) / 2.0
        for j in range(pos, end):
            matched[order[j]] = m
            ranks[order[j]] = midrank
        pos = end
    return matched, ranks


def interpolate(v: float, m: float, k: float) -> float:
    """``exp((1-k) ln v + k ln m)``; exact at the endpoints and at ``m == v``."""
    if k <= 0.0 or m == v:
        return float(v)
    if k >= 1.0:
        return float(m)
    return math.exp((1.0 - k) * math.log(v) + k * math.log(m))


def _bounded_int(fair: float, v: int, m: float) -> int:
    """Nearest integer to ``fair`` that stays inside ``[min(v, m), max(v, m)]``.

    ``v`` is an integer endpoint, so the interval always contains one."""
    lo, hi = min(float(v), m), max(float(v), m)
    out = int(round(fair))
    if out > hi:
        out = math.floor(hi)
    if out < lo:
        out = math.ceil(lo)
    return out


def _quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Linear-interpolated quantile of an ascending sequence."""
    if not sorted_xs:
        raise ValueError("empty")
    if len(sorted_xs) == 1:
        return float(sorted_xs[0])
    h = (len(sorted_xs) - 1) * q
    lo = math.floor(h)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return float(sorted_xs[lo] + (h - lo) * (sorted_xs[hi] - sorted_xs[lo]))


def idp_fanout_stability(
    entries: Sequence[tuple[str, float, float]], params: Mapping[str, Any]
) -> dict[str, Any]:
    """Depth fan-out test on the IDP utility-vs-market disagreement.

    ``entries`` are ``(position family, market value v, matched value m)``. For
    each IDP position, rows are ordered by market value and, at every pool depth
    in ``scoring_fit.DEPTH_PROBES`` the cohort reaches, the p90/p10 spread of the
    ratio ``m / v`` is measured. A per-player signal is flat across depth; a
    sampling artifact fans out as the pool deepens. The scope is stable only when
    EVERY IDP position has at least two usable probes, a cohort of at least
    ``MIN_COHORT_SIZE``, and a spread drift within ``MAX_DEPTH_DRIFT``.
    Insufficient evidence is unstable (fail closed).
    """
    from src.league_intel.scoring_fit import (  # noqa: PLC0415 - read-only reuse
        DEPTH_PROBES,
        MAX_DEPTH_DRIFT,
        MIN_COHORT_SIZE,
    )

    q_lo, q_hi = (float(x) for x in params["idpFanOut"]["spreadQuantiles"])
    by_pos: dict[str, list[tuple[float, float]]] = {}
    for family, v, m in entries:
        by_pos.setdefault(family, []).append((float(v), float(m)))
    positions: dict[str, Any] = {}
    stable = True
    reasons: list[str] = []
    for family in sorted(str(f) for f in params["scopes"]["IDP"]):
        cohort = sorted(by_pos.get(family, []), key=lambda t: -t[0])
        probes: dict[str, float] = {}
        for depth in DEPTH_PROBES:
            if depth > len(cohort):
                continue
            ratios = sorted(m / v for v, m in cohort[:depth])
            p_lo = _quantile(ratios, q_lo)
            probes[str(depth)] = _quantile(ratios, q_hi) / p_lo if p_lo > 0 else math.inf
        drift = (max(probes.values()) - min(probes.values())) if len(probes) >= 2 else None
        ok = (
            len(cohort) >= MIN_COHORT_SIZE
            and drift is not None
            and math.isfinite(drift)
            and drift <= MAX_DEPTH_DRIFT
        )
        if not ok:
            stable = False
            if len(cohort) < MIN_COHORT_SIZE or drift is None:
                reasons.append(f"{family}:insufficient_depth({len(cohort)})")
            else:
                reasons.append(f"{family}:fans_out({drift:.4f}>{MAX_DEPTH_DRIFT})")
        positions[family] = {
            "cohortSize": len(cohort),
            "spreadByDepth": {k: round(val, 6) for k, val in probes.items()},
            "drift": None if drift is None else round(drift, 6),
            "stable": ok,
        }
    return {
        "stable": stable,
        "test": "src.league_intel.scoring_fit depth fan-out (DEPTH_PROBES, MAX_DEPTH_DRIFT)",
        "positions": positions,
        "reason": None if stable else "; ".join(reasons),
    }


# ── board ────────────────────────────────────────────────────────────────────


def _excluded(
    key: str,
    row: Mapping[str, Any],
    reason: str,
    *,
    detail: str | None,
    params: Mapping[str, Any],
    pins: Mapping[str, str],
) -> LeagueFairValue:
    mv = market_value_of(row)
    return LeagueFairValue(
        asset_key=key,
        player_id=str(row.get("playerId")) if row.get("playerId") else None,
        scope=scope_of_row(row),
        market_value=mv,
        fair_value=mv,
        matched_value=None,
        k=0.0,
        utility_rank=None,
        market_rank=_int_or_none(row.get("canonicalConsensusRank")),
        excluded_reason=reason,
        model_version=MODEL_VERSION,
        param_set_id=str(params["paramSetId"]),
        pins=pins,
        state=FAIR_VALUE_STATE_EXCLUDED,
        reason=detail or reason,
        fair_value_exact=None if mv is None else float(mv),
        position=normalize_position_family(str(row.get("position") or "")) or None,
        name=str(row.get("canonicalName") or row.get("displayName") or "") or None,
        labels=_labels(row),
    )


def _evidence_for(
    key: str, row: Mapping[str, Any], evidence: Mapping[str, UtilityEvidence]
) -> UtilityEvidence | None:
    """Evidence by the row's own key; a name-grade key only to NAME an absence.

    BDVM's ``unpriced`` entries carry no platform id, so a player BDVM declined
    to price is keyed by name. The name-grade fallback is accepted ONLY for
    non-available evidence: it turns ``no_utility_evidence`` into BDVM's own
    reason (e.g. ``no_projection``) and can never hand a row another player's
    utility.
    """
    ev = evidence.get(key)
    if ev is not None:
        return ev
    name = row.get("canonicalName") or row.get("displayName")
    fallback = evidence_asset_key(None, name, row.get("position")) if name else None
    alt = evidence.get(fallback) if fallback else None
    if alt is not None and alt.state != "available":
        return alt
    return None


def _labels(row: Mapping[str, Any]) -> tuple[str, ...]:
    family = normalize_position_family(str(row.get("position") or ""))
    return (TE_BASIS_LABEL,) if family == "TE" else ()


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _k_summary(ks: Sequence[float]) -> dict[str, Any]:
    if not ks:
        return {"n": 0}
    s = sorted(ks)
    return {
        "n": len(s),
        "min": s[0],
        "p50": _quantile(s, 0.5),
        "max": s[-1],
        "mean": statistics.fmean(s),
        "positive": sum(1 for k in s if k > 0),
    }


def compute_fair_values(
    rows: Sequence[Mapping[str, Any]],
    evidence: Mapping[str, UtilityEvidence],
    *,
    params: Mapping[str, Any],
    pins: Mapping[str, str],
) -> FairValueBoard:
    """The challenger board. Reads ``rows``; writes nothing to them.

    ``rows`` are canonical ``playersArray`` rows (read-only). ``evidence`` comes
    from :func:`src.league_valuation.evidence.utility_evidence_from_bdvm`.
    No rank or tier is produced: see :data:`RANKS_UNAVAILABLE_REASON`.
    """
    checked_pins = validate_pins(pins, params)
    k_max = float(params["kMax"]["value"])
    if not (0.0 <= k_max <= 1.0):
        raise ChallengerInvariantError(f"kMax must lie in [0, 1]: {k_max}")

    populations, structural = eligible_rows(rows)
    by_key: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if isinstance(row, Mapping):
            by_key.setdefault(row_key(row, index), row)

    values: dict[str, LeagueFairValue] = {}
    census: dict[str, int] = {}

    def _exclude(key: str, row: Mapping[str, Any], reason: str, detail: str | None = None) -> None:
        census[reason] = census.get(reason, 0) + 1
        values[key] = _excluded(key, row, reason, detail=detail, params=params, pins=checked_pins)

    for key, reason in structural.items():
        _exclude(key, by_key[key], reason)

    scope_diag: dict[str, Any] = {}
    for scope in SCOPES:
        members: list[tuple[str, Mapping[str, Any], UtilityEvidence]] = []
        for index_row in populations.get(scope, []):
            key = row_key(index_row, -1)  # population rows are always keyed
            ev = _evidence_for(key, index_row, evidence)
            if ev is None:
                _exclude(key, index_row, "no_utility_evidence")
                continue
            if ev.scope != scope:
                _exclude(key, index_row, "scope_mismatch", f"evidence scope {ev.scope}")
                continue
            if ev.state != "available":
                _exclude(key, index_row, f"evidence_{ev.state}", ev.reason)
                continue
            members.append((key, index_row, ev))

        market = [market_value_of(r) for _, r, _ in members]
        assert all(v is not None for v in market)
        mv = [int(v) for v in market if v is not None]
        utility = [ev.utility_key for _, _, ev in members]
        assert all(u is not None for u in utility)
        matched, midranks = quantile_match(mv, [u for u in utility if u is not None])

        gate: dict[str, Any] | None = None
        scope_k_forced: str | None = None
        if scope == "IDP":
            gate = idp_fanout_stability(
                [
                    (normalize_position_family(str(r.get("position") or "")), v, m)
                    for (_, r, _), v, m in zip(members, mv, matched)
                ],
                params,
            )
            if not gate["stable"]:
                scope_k_forced = f"k_zero:idp_fanout_unstable ({gate['reason']})"

        ks: list[float] = []
        log_shift: list[float] = []
        value_shift: list[float] = []
        out_of_range = 0
        for (key, row, ev), v, m, rank in zip(members, mv, matched, midranks):
            assert ev.quality is not None  # UtilityEvidence refuses available without it
            q = float(ev.quality)
            k = 0.0 if scope_k_forced else min(1.0, max(0.0, k_max * q))
            fair_exact = interpolate(float(v), m, k)
            fair_int = _bounded_int(fair_exact, v, m)
            lo, hi = min(float(v), m), max(float(v), m)
            if not (
                lo - 1e-9 <= fair_exact <= hi + 1e-9
                and lo <= fair_int <= hi
                and DISPLAY_SCALE_MIN <= fair_int <= DISPLAY_SCALE_MAX
            ):
                out_of_range += 1
            ks.append(k)
            log_shift.append(math.log(fair_exact) - math.log(v))
            value_shift.append(fair_exact - v)
            values[key] = LeagueFairValue(
                asset_key=key,
                player_id=ev.player_id,
                scope=scope,
                market_value=v,
                fair_value=fair_int,
                matched_value=int(round(m)),
                k=k,
                utility_rank=rank,
                market_rank=_int_or_none(row.get("canonicalConsensusRank")),
                excluded_reason=None,
                model_version=MODEL_VERSION,
                param_set_id=str(params["paramSetId"]),
                pins=checked_pins,
                state=FAIR_VALUE_STATE_AVAILABLE,
                reason=scope_k_forced,
                fair_value_exact=fair_exact,
                matched_value_exact=m,
                position=normalize_position_family(str(row.get("position") or "")) or None,
                name=str(row.get("canonicalName") or row.get("displayName") or "") or None,
                labels=_labels(row),
                lineage_ids=("league_fair_value",) + tuple(ev.lineage_ids),
            )
        if out_of_range:
            # Bounded by construction; a violation is a code fault, not a value.
            raise ChallengerInvariantError(
                f"{out_of_range} {scope} fair values left [min(v, m), max(v, m)] or the scale"
            )
        scope_diag[scope] = {
            "n": len(members),
            "kDistribution": _k_summary(ks),
            "kForced": scope_k_forced,
            "moved": sum(1 for x in value_shift if x != 0.0),
            "logDrift": {
                "sum": math.fsum(log_shift),
                "mean": statistics.fmean(log_shift) if log_shift else None,
                "maxAbs": max((abs(x) for x in log_shift), default=None),
            },
            "valueDrift": {
                "sum": math.fsum(value_shift),
                "mean": statistics.fmean(value_shift) if value_shift else None,
                "maxAbs": max((abs(x) for x in value_shift), default=None),
            },
            "outOfRangeCount": out_of_range,
            "idpFanOut": gate,
        }

    diagnostics = {
        "scopes": scope_diag,
        "exclusions": dict(sorted(census.items())),
        "ranks": {
            "state": "unavailable",
            "reason": RANKS_UNAVAILABLE_REASON,
        },
        "scale": {"min": DISPLAY_SCALE_MIN, "max": DISPLAY_SCALE_MAX},
        "kMax": k_max,
        "noCentringConstant": True,
    }
    return FairValueBoard(
        values=values,
        diagnostics=diagnostics,
        pins=checked_pins,
        param_set_id=str(params["paramSetId"]),
    )
