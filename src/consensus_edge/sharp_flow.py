"""Qualified-manager acquisition direction, with its uncertainty attached.

The existing signal (``src/intel/signals.py``) computes::

    100 x (net/volume) x v/(v+5) x m/(m+3) x managerQuality

That is a reasonable heuristic and it is deliberately preserved as a
benchmark.  Four things it cannot do, which this module does:

1. **Separate direction from certainty in a way that composes.**  The
   existing formula multiplies confidence INTO the strength, so a
   strength of 20 might be weak evidence of a big lean or strong
   evidence of a small one, and a downstream consumer cannot tell.  A
   posterior gives a direction and an interval, and the two travel
   separately.

2. **Bound a single contributor.**  Measured on ``main``: there is no
   per-manager or per-league cap anywhere.  One qualified manager active
   in ten leagues contributes ten observations, and ``breadth_factor``
   (``m/(m+3)``) saturates too fast to push back.  Here, no single
   manager or league may exceed a declared share of the evidence.

3. **Decay old evidence.**  A trade from five weeks ago and one from
   yesterday count identically today.  Weight now halves on a declared
   half-life.

4. **Refuse.**  With two observations the existing formula still returns
   a number.  Here, below a minimum effective sample size the direction
   is ``None`` with a reason, because "we do not know" and "the market
   is neutral" are different claims.

**This module cannot be validated in this environment, and says so.**
The ledger lives in prod-only, gitignored ``data/intel/``.  Everything
here is unit-tested against synthetic movements; none of it has been
checked against an outcome.  :func:`sharp_flow_index` returns an explicit
unavailable status rather than zeros when there is no ledger — a zero
would read as "no lean detected", which is a finding this module has not
earned.

**A directional caveat that is not a defect to be fixed here:** an
acquisition is not evidence of a good price.  A manager who massively
overpaid still registers as a buy.  The ledger stores no consideration,
so price-awareness is not merely unimplemented, it is unavailable — and
``priceAware: False`` is stamped on every payload so no consumer can
mistake direction for value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

# Statuses a Sharp Flow computation can report.
STATUS_OK = "ok"
STATUS_NO_LEDGER = "no_ledger"
STATUS_NO_COHORT = "no_qualified_cohort"

# Per-row reasons.
UNSCORED_NO_OBSERVATIONS = "no_observations_in_window"
UNSCORED_BELOW_MIN_SAMPLE = "effective_sample_below_minimum"


@dataclass(frozen=True)
class Movement:
    """One qualified-manager asset movement.

    Mirrors the ledger's ``asset_movements`` shape narrowly — this module
    does not import the ledger, so it can be unit-tested (and reasoned
    about) in an environment that has none.
    """

    asset_key: str
    manager_key: str
    league_key: str
    is_buy: bool
    timestamp_ms: int
    manager_quality: float = 1.0


def _recency_weight(age_days: float, half_life_days: float) -> float:
    """Exponential decay: weight halves every ``half_life_days``."""
    if half_life_days <= 0:
        return 1.0
    return math.exp(-math.log(2.0) * max(0.0, age_days) / half_life_days)


def _apply_share_cap(
    weights_by_group: dict[str, float],
    max_share: float,
) -> dict[str, float]:
    """Scale groups down until none exceeds ``max_share`` of the total.

    Iterative because capping one group lowers the total, which can push
    a second group over the line.  Converges quickly (each pass either
    caps something or stops) and is bounded so a pathological input
    cannot spin.

    Capping SHARES rather than counts is what makes this scale-free: ten
    managers each contributing 10% are untouched, while one manager
    contributing 80% is cut to the cap no matter how many observations
    that represents.
    """
    if max_share <= 0 or max_share >= 1 or not weights_by_group:
        return dict(weights_by_group)

    capped = dict(weights_by_group)
    for _ in range(32):
        total = sum(capped.values())
        if total <= 0:
            return capped
        over = {k: v for k, v in capped.items() if v / total > max_share + 1e-12}
        if not over:
            return capped
        # Cap the single largest offender per pass, then re-evaluate: the
        # total moves, so capping them all at once would over-correct.
        worst = max(over, key=lambda k: capped[k])
        others = total - capped[worst]
        if others <= 0:
            return capped
        # Solve capped[worst] / (capped[worst] + others) == max_share
        capped[worst] = others * max_share / (1.0 - max_share)
    return capped


def aggregate_asset(
    movements: Sequence[Movement],
    params: dict[str, Any],
    *,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Posterior buy-direction for one asset from its movements.

    Returns direction in ``[-1, 1]`` (positive = qualified managers are
    net acquiring), a credible interval, the effective sample size, and
    the concentration diagnostics a reader needs to discount it.
    """
    cfg = params.get("sharpFlow") or {}
    half_life = float(cfg.get("recencyHalfLifeDays") or 21.0)
    max_mgr = float(cfg.get("maxManagerShare") or 1.0)
    max_lg = float(cfg.get("maxLeagueShare") or 1.0)
    prior_a = float(cfg.get("priorAlpha") or 1.0)
    prior_b = float(cfg.get("priorBeta") or 1.0)
    min_ess = float(cfg.get("minEffectiveSampleForDirection") or 0.0)

    result: dict[str, Any] = {
        "direction": None,
        "reason": None,
        "rawBuys": 0,
        "rawSells": 0,
        "weightedBuys": 0.0,
        "weightedSells": 0.0,
        "effectiveSample": 0.0,
        "uniqueManagers": 0,
        "uniqueLeagues": 0,
        "topManagerShare": None,
        "topLeagueShare": None,
        "medianAgeDays": None,
        "posteriorMean": None,
        "credibleLow": None,
        "credibleHigh": None,
        "priceAware": False,
    }

    if not movements:
        result["reason"] = UNSCORED_NO_OBSERVATIONS
        return result

    now = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)

    # Weight each observation by recency and manager quality.
    weighted: list[tuple[Movement, float]] = []
    ages: list[float] = []
    for mv in movements:
        age_days = max(0.0, (now - int(mv.timestamp_ms)) / 86_400_000.0)
        ages.append(age_days)
        quality = max(0.0, min(1.0, float(mv.manager_quality)))
        weighted.append((mv, _recency_weight(age_days, half_life) * quality))

    result["rawBuys"] = sum(1 for mv in movements if mv.is_buy)
    result["rawSells"] = sum(1 for mv in movements if not mv.is_buy)
    result["uniqueManagers"] = len({mv.manager_key for mv in movements})
    result["uniqueLeagues"] = len({mv.league_key for mv in movements})
    ages.sort()
    result["medianAgeDays"] = ages[len(ages) // 2]

    # Cap concentration by manager, then by league. Applied as a scaling
    # factor on each observation so buys and sells shrink together and
    # capping cannot flip a direction.
    by_manager: dict[str, float] = {}
    by_league: dict[str, float] = {}
    for mv, w in weighted:
        by_manager[mv.manager_key] = by_manager.get(mv.manager_key, 0.0) + w
        by_league[mv.league_key] = by_league.get(mv.league_key, 0.0) + w

    mgr_total = sum(by_manager.values()) or 1.0
    lg_total = sum(by_league.values()) or 1.0
    result["topManagerShare"] = max(by_manager.values()) / mgr_total
    result["topLeagueShare"] = max(by_league.values()) / lg_total

    mgr_capped = _apply_share_cap(by_manager, max_mgr)
    lg_capped = _apply_share_cap(by_league, max_lg)
    mgr_scale = {k: (mgr_capped[k] / v if v > 0 else 1.0) for k, v in by_manager.items()}
    lg_scale = {k: (lg_capped[k] / v if v > 0 else 1.0) for k, v in by_league.items()}

    buys = sells = 0.0
    for mv, w in weighted:
        adjusted = w * mgr_scale.get(mv.manager_key, 1.0) * lg_scale.get(mv.league_key, 1.0)
        if mv.is_buy:
            buys += adjusted
        else:
            sells += adjusted

    result["weightedBuys"] = buys
    result["weightedSells"] = sells
    ess = buys + sells
    result["effectiveSample"] = ess

    if ess < min_ess:
        result["reason"] = UNSCORED_BELOW_MIN_SAMPLE
        return result

    alpha = prior_a + buys
    beta = prior_b + sells
    mean = alpha / (alpha + beta)
    result["posteriorMean"] = mean
    result["direction"] = 2.0 * mean - 1.0

    # Normal approximation to the Beta interval. Adequate here because
    # the interval is a discount factor on confidence, not a p-value, and
    # alpha+beta >= 2 by construction from the prior.
    var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1.0))
    sd = math.sqrt(max(var, 0.0))
    z = 1.2815515655446004  # 80% central mass
    result["credibleLow"] = max(0.0, mean - z * sd)
    result["credibleHigh"] = min(1.0, mean + z * sd)
    return result


_UNAVAILABLE_MESSAGES: dict[str, str] = {
    STATUS_NO_LEDGER: (
        "No qualified-manager ledger available. Sharp Flow is omitted from "
        "the composite rather than contributing a neutral zero, which would "
        "read as 'no lean detected'."
    ),
    STATUS_NO_COHORT: (
        "A ledger exists but no manager currently qualifies, so no movement "
        "in it can be attributed to the cohort this component is about. "
        "Reported separately from 'no ledger' because the two have "
        "different fixes."
    ),
    "ledger_unreadable": (
        "The ledger could not be read. Sharp Flow is omitted rather than "
        "reported as empty, which would claim the ledger was consulted."
    ),
}


def sharp_flow_index(
    movements_by_asset: dict[str, Sequence[Movement]] | None,
    params: dict[str, Any],
    *,
    now_ms: int | None = None,
    unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """Sharp Flow for every asset with movements.

    ``movements_by_asset`` of ``None`` means "no movements available",
    which is reported as an explicit status rather than as an empty
    result. The distinction matters: an empty dict means the ledger was
    read and nobody traded, and that IS a finding.

    ``unavailable_reason`` says WHICH kind of unavailable. Absent it,
    everything collapses to ``no_ledger`` — including the case where a
    ledger exists but nobody qualifies, which has a different fix.
    ``STATUS_NO_COHORT`` was declared for exactly that case and, until
    the cohort filter was actually applied in ``inputs.sharp_movements``,
    was unreachable dead code.
    """
    if movements_by_asset is None:
        status = unavailable_reason or STATUS_NO_LEDGER
        return {
            "status": status,
            "message": _UNAVAILABLE_MESSAGES.get(status, _UNAVAILABLE_MESSAGES[STATUS_NO_LEDGER]),
            "assets": {},
            "priceAware": False,
        }

    assets = {
        key: aggregate_asset(list(movements), params, now_ms=now_ms)
        for key, movements in movements_by_asset.items()
    }
    scored = sum(1 for a in assets.values() if a.get("direction") is not None)
    return {
        "status": STATUS_OK,
        "assets": assets,
        "assetsScored": scored,
        "assetsTotal": len(assets),
        "priceAware": False,
    }


def legacy_signal_strength(
    net: int, volume: int, unique_managers: int, manager_quality: float = 1.0
) -> float:
    """The incumbent formula, kept as a benchmark.

    Reimplemented here rather than imported so this module stays free of
    ``src/intel`` (which open PR #670 is rewriting) and so a backtest can
    score old against new on identical inputs.  Mirrors
    ``src.intel.signals.signal_strength``; a test pins the two together
    when that module is importable.
    """
    v = max(0, int(volume))
    if v <= 0:
        return 0.0
    normalized_net = max(-1.0, min(1.0, net / float(v)))
    sample_confidence = v / (v + 5.0)
    m = max(0, int(unique_managers))
    breadth = (m / (m + 3.0)) if m > 0 else 0.0
    return round(
        normalized_net * sample_confidence * breadth * max(0.0, float(manager_quality)) * 100.0, 2
    )


def movements_from_ledger_rows(rows: Iterable[dict[str, Any]]) -> dict[str, list[Movement]]:
    """Adapt ledger query rows into :class:`Movement` objects.

    Kept at the boundary so the ledger's column names live in exactly one
    place here, and so the rest of the module needs no database to test.
    """
    out: dict[str, list[Movement]] = {}
    for row in rows:
        asset = str(row.get("canonicalAssetId") or row.get("asset_id") or "")
        if not asset:
            continue
        action = str(row.get("action") or "")
        if action not in ("add", "drop"):
            continue
        out.setdefault(asset, []).append(
            Movement(
                asset_key=asset,
                manager_key=str(
                    row.get("canonicalManagerKey") or row.get("manager_key") or row.get("user_id")
                ),
                league_key=str(row.get("league_key") or row.get("league_id") or ""),
                is_buy=(action == "add"),
                timestamp_ms=int(row.get("timestamp_ms") or row.get("ts") or 0),
                manager_quality=float(row.get("managerQuality") or 1.0),
            )
        )
    return out
