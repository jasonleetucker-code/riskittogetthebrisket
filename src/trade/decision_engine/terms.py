"""Term classification: each term in its OWN units, never a probability.

* **A** (market asset, lineage ``rank_derived_value``): the adjusted package
  gap READ from the analyze packet (raw + the active package model's VA), net
  of the marginal forced-release charge from
  ``roster_capacity.forced_drop_cost``, classified by the ONE fairness-band
  owner (``src.valuation_math.fairness_bands``).
* **C** (best-ball lineup delta, lineage ``bestball_lineup_delta``): a
  magnitude band ``max(materialityPpg, zPrior * predictive_sd)`` (just
  ``materialityPpg`` while ``predictive_basis`` is ``unavailable``) and a
  separate precision gate ``mc_standard_error <= band * precisionGateFraction``.
  The band never shrinks with Monte-Carlo draws, so more draws can tighten
  precision but can never turn a below-band delta into a distinguishable one.
* **D1** / **D2** (title / multi-season outcome layers): classified when
  available, but they vote only when their family is promoted.

Only ``available`` votes.  ``partial`` / ``stale`` / ``unavailable`` are
report-only and contribute nothing -- never 0.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, Mapping

from src.trade.decision_engine.contracts import (
    EVIDENCE_STATES,
    TERM_LINEAGE_MEMBER,
    TermResult,
)
from src.valuation_math import fairness_bands, package_model

A_UNIT = "canonical value points (adjusted package, net of added forced releases)"
C_UNIT = "expected best-ball lineup points per week"


def get(m: Mapping[str, Any] | None, camel: str, snake: str | None = None) -> Any:
    """Read a camelCase key, falling back to its snake_case spelling."""
    if not isinstance(m, Mapping):
        return None
    if camel in m:
        return m[camel]
    return m.get(snake) if snake else None


def num(x: Any) -> float | None:
    """A finite real number, or ``None`` -- never a coerced 0."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def _state(m: Mapping[str, Any] | None) -> tuple[str, str | None]:
    if not isinstance(m, Mapping) or not m:
        return "unavailable", "layer_missing"
    s = m.get("state")
    if s not in EVIDENCE_STATES:
        return "unavailable", "state_undeclared"
    return s, m.get("reason")


def _silent(term: str, state: str, reason: str | None, unit: str) -> TermResult:
    return TermResult(
        term=term,  # type: ignore[arg-type]
        lineage_member=TERM_LINEAGE_MEMBER[term],
        state=state,
        direction=None,
        magnitude_class=None,
        value=None,
        unit=unit,
        band=None,
        mc_standard_error=None,
        predictive_sd=None,
        predictive_basis="not_applicable" if term == "A" else "unavailable",
        precision_ok=None,
        counted_as_vote=False,
        reason=reason or state,
    )


# ── A ──────────────────────────────────────────────────────────────────────


def a_band_threshold(larger_side: float) -> float:
    """The absolute gap at which a package pairing leaves the fair band."""
    return max(fairness_bands.ABSOLUTE_MINIMUM, fairness_bands.SLIGHT_PCT / 100.0 * larger_side)


def _classify_gap(
    net: float, larger: float, params: Mapping[str, Any]
) -> tuple[str, str | None, dict]:
    band = fairness_bands.classify(net, larger)
    magnitude = params["terms"]["A"]["levelToMagnitude"][band["level"]]
    if magnitude is None:
        return "neutral", None, band
    return ("favours" if net > 0 else "opposes"), magnitude, band


def forced_release_charge(asset: Mapping[str, Any]) -> tuple[float | None, str]:
    """``(charge, basis_state)`` from ``roster_capacity.forced_drop_cost``.

    ``none`` -> no charge (the trade adds no release); ``exact`` /
    ``lower_bound`` -> the published marginal cost; anything else (missing,
    ``unknown``) -> ``None``, which keeps A from voting.
    """
    basis = get(asset, "forcedDropCostBasis", "forced_drop_cost_basis")
    state = basis.get("state") if isinstance(basis, Mapping) else None
    if state == "none":
        return 0.0, "none"
    cost = num(get(asset, "forcedDropCost", "forced_drop_cost"))
    if state in ("exact", "lower_bound") and cost is not None and cost >= 0:
        return cost, state
    return None, state if isinstance(state, str) else "missing"


def classify_asset(asset: Mapping[str, Any], params: Mapping[str, Any]) -> tuple[TermResult, dict]:
    state, reason = _state(asset)
    detail: dict[str, Any] = {"gateCodes": list(get(asset, "gateCodes", "gate_codes") or [])}
    if state != "available":
        return _silent("A", state, reason, A_UNIT), detail
    gates = detail["gateCodes"]
    if gates:
        gstate = "stale" if set(gates) == {"stale_values"} else "partial"
        return _silent("A", gstate, "gated:" + ",".join(map(str, gates)), A_UNIT), detail
    gap = num(get(asset, "vaGap", "va_gap"))
    send_adj = num(get(asset, "sendAdjusted", "send_adjusted"))
    recv_adj = num(get(asset, "recvAdjusted", "recv_adjusted"))
    if gap is None or send_adj is None or recv_adj is None:
        return _silent("A", "unavailable", "asset_totals_missing", A_UNIT), detail
    charge, charge_state = forced_release_charge(asset)
    detail["forcedReleaseCharge"] = charge
    detail["forcedReleaseBasis"] = charge_state
    if charge is None:
        return _silent("A", "partial", f"forced_drop_cost_{charge_state}", A_UNIT), detail
    larger = max(send_adj, recv_adj)
    net = gap - charge
    direction, magnitude, band = _classify_gap(net, larger, params)
    detail.update({"fairness": band, "vaGap": gap, "largerAdjustedSide": larger})
    return (
        TermResult(
            term="A",
            lineage_member=TERM_LINEAGE_MEMBER["A"],
            state="available",
            direction=direction,  # type: ignore[arg-type]
            magnitude_class=magnitude,  # type: ignore[arg-type]
            value=round(net, 1),
            unit=A_UNIT,
            band=round(a_band_threshold(larger), 1),
            mc_standard_error=None,
            predictive_sd=None,
            predictive_basis="not_applicable",
            precision_ok=None,
            counted_as_vote=True,
            reason=None,
        ),
        detail,
    )


def a_term_from_values(
    send_values: list[float],
    recv_values: list[float],
    charge: float,
    params: Mapping[str, Any],
    *,
    model_id: str | None = None,
) -> TermResult:
    """A for a HYPOTHETICAL package (the what-would-change price grid): the
    package model re-runs from scratch, never a raw value subtracted from an
    adjusted gap."""
    send_adj, recv_adj, _, _ = package_model.adjusted_pair_totals(
        send_values, recv_values, model_id=model_id
    )
    larger = max(send_adj, recv_adj)
    net = recv_adj - send_adj - charge
    direction, magnitude, _ = _classify_gap(net, larger, params)
    return TermResult(
        term="A",
        lineage_member=TERM_LINEAGE_MEMBER["A"],
        state="available",
        direction=direction,  # type: ignore[arg-type]
        magnitude_class=magnitude,  # type: ignore[arg-type]
        value=round(net, 1),
        unit=A_UNIT,
        band=round(a_band_threshold(larger), 1),
        mc_standard_error=None,
        predictive_sd=None,
        predictive_basis="not_applicable",
        precision_ok=None,
        counted_as_vote=True,
        reason=None,
    )


# ── C ──────────────────────────────────────────────────────────────────────


def c_band(params: Mapping[str, Any], predictive_sd: float | None, basis: str) -> float:
    c = params["terms"]["C"]
    band = float(c["materialityPpg"])
    if basis != "unavailable" and predictive_sd is not None and predictive_sd > 0:
        band = max(band, float(c["zPrior"]) * predictive_sd)
    return band


def classify_lineup(lineup: Mapping[str, Any], params: Mapping[str, Any]) -> TermResult:
    state, reason = _state(lineup)
    if state == "available" and get(lineup, "coverage") == "partial":
        state, reason = "partial", "partial_projection_coverage"
    if state != "available":
        return _silent("C", state, reason, C_UNIT)
    delta = num(get(lineup, "deltaPpg", "delta_ppg"))
    if delta is None:
        # "available" without a number is a malformed layer, not a zero.
        return _silent("C", "unavailable", "delta_missing", C_UNIT)
    se = num(get(lineup, "mcStandardError", "mc_standard_error"))
    psd = num(get(lineup, "predictiveSd", "predictive_sd"))
    basis = get(lineup, "predictiveBasis", "predictive_basis")
    basis = basis if isinstance(basis, str) else "unavailable"
    c = params["terms"]["C"]
    band = c_band(params, psd, basis)
    precision_ok = None if se is None else se <= band * float(c["precisionGateFraction"])
    if precision_ok is not True:
        direction, magnitude = "neutral", None
        why = "imprecise" if precision_ok is False else "precision_unknown"
    elif abs(delta) < band:
        direction, magnitude, why = "neutral", None, "within_band"
    else:
        direction = "favours" if delta > 0 else "opposes"
        magnitude = "large" if abs(delta) >= float(c["largeMultiple"]) * band else "modest"
        why = None
    return TermResult(
        term="C",
        lineage_member=TERM_LINEAGE_MEMBER["C"],
        state="available",
        direction=direction,  # type: ignore[arg-type]
        magnitude_class=magnitude,  # type: ignore[arg-type]
        value=round(delta, 3),
        unit=C_UNIT,
        band=round(band, 3),
        mc_standard_error=se,
        predictive_sd=psd,
        predictive_basis=basis,
        precision_ok=precision_ok,
        counted_as_vote=True,
        reason=why,
    )


# ── D1 / D2 ────────────────────────────────────────────────────────────────


def _outcome_term(term: str, delta: float, band: float, unit: str) -> TermResult:
    if abs(delta) < band:
        direction, magnitude = "neutral", None
    else:
        direction, magnitude = ("favours" if delta > 0 else "opposes"), "modest"
    return TermResult(
        term=term,  # type: ignore[arg-type]
        lineage_member=TERM_LINEAGE_MEMBER[term],
        state="available",
        direction=direction,  # type: ignore[arg-type]
        magnitude_class=magnitude,  # type: ignore[arg-type]
        value=round(delta, 4),
        unit=unit,
        band=band,
        mc_standard_error=None,
        predictive_sd=None,
        predictive_basis="unavailable",
        precision_ok=None,
        counted_as_vote=False,
        reason="not_promoted",
    )


def classify_title(title: Mapping[str, Any], params: Mapping[str, Any]) -> TermResult:
    cfg = params["terms"]["D1"]
    state, reason = _state(title)
    if state != "available":
        return _silent("D1", state, reason, cfg["unit"])
    delta = num(get(title, "delta"))
    if delta is None:
        return _silent("D1", "unavailable", "delta_missing", cfg["unit"])
    return _outcome_term("D1", delta, float(cfg["materialityDelta"]), cfg["unit"])


def _by_season(h: Any) -> dict[int, float | None]:
    rows = get(h, "bySeason", "by_season") or ()
    out: dict[int, float | None] = {}
    for row in rows:
        if isinstance(row, Mapping):
            season, ppg = row.get("season"), num(row.get("expectedPpg", row.get("expected_ppg")))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            season, ppg = row[0], num(row[1])
        else:
            continue
        if isinstance(season, int):
            out[season] = ppg
    return out


def classify_horizon(horizon: Mapping[str, Any], params: Mapping[str, Any]) -> TermResult:
    cfg = params["terms"]["D2"]
    state, reason = _state(horizon)
    if state != "available":
        return _silent("D2", state, reason, cfg["unit"])
    delta = num(get(horizon, "deltaPpg", "delta_ppg"))
    if delta is None:
        before = _by_season(get(horizon, "before"))
        after = _by_season(get(horizon, "after"))
        seasons = sorted(set(before) & set(after))
        diffs = [
            after[s] - before[s] for s in seasons if before[s] is not None and after[s] is not None
        ]  # type: ignore[operator]
        if not seasons or len(diffs) != len(seasons):
            return _silent("D2", "partial", "horizon_seasons_incomplete", cfg["unit"])
        delta = sum(diffs) / len(diffs)
    return _outcome_term("D2", delta, float(cfg["materialityPpg"]), cfg["unit"])


# ── P selection: the ONE league_scored_projection vote ────────────────────


def select_p_term(
    c: TermResult,
    d1: TermResult,
    d2: TermResult,
    *,
    promoted_families: frozenset[str],
    params: Mapping[str, Any],
) -> tuple[TermResult, TermResult, TermResult, str | None]:
    """Mark at most one of C / D1 / D2 as the voting P term.

    D1 / D2 replace C only when their lineage member is in
    ``promoted_families`` AND their state is available.  Returns the three
    terms with ``counted_as_vote`` set, plus the chosen term name (``None``
    when nothing in the group can vote).
    """
    terms = {"C": c, "D1": d1, "D2": d2}
    chosen: str | None = None
    for name in params["pTermPrecedence"]:
        t = terms[name]
        if t.state != "available":
            continue
        if name != "C" and t.lineage_member not in promoted_families:
            continue
        chosen = name
        break
    out = {}
    for name, t in terms.items():
        if name == chosen:
            out[name] = replace(t, counted_as_vote=True, reason=t.reason if name == "C" else None)
        elif t.state != "available":
            out[name] = replace(t, counted_as_vote=False)
        elif name != "C" and t.lineage_member not in promoted_families:
            out[name] = replace(t, counted_as_vote=False, reason="not_promoted")
        else:
            out[name] = replace(t, counted_as_vote=False, reason=f"replaced_by_{chosen}")
    return out["C"], out["D1"], out["D2"], chosen
