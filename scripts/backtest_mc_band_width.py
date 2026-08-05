#!/usr/bin/env python3
"""How far does the board actually move? — evidence for open decision #4.

THE QUESTION
============
``src/trade/monte_carlo.py`` draws each asset's value from a band and
reports the fraction of draws where side A wins.  On the live path that
band is a flat **±15%** on every asset: ``valueBand`` is stamped on 0 of
~1093 rows, so ``MonteCarloButton.jsx`` synthesizes one.

``docs/open-modeling-decisions.md`` decision #4 recorded the width as an
open question rather than picking a number, because the only quantity
available was ``marketDispersionCV`` — how much the sources disagree on
one day — which is 4.8x narrower than the flat band at the median and
0.4x at the maximum.  Source disagreement is a **lower bound** on value
uncertainty: it measures how much the boards differ today, not how wrong
they might all be together.

This measures something strictly better: **how much our own board
actually moves**.  If the board reprices a player by 30% over a week,
a ±15% band was too narrow for that player whatever the sources agreed
on at the time.

WHY NOT JUST WIRE THE PHASE-4 INTERVAL
======================================
``src/canonical/confidence_intervals.py`` looks like the answer and is
not.  Two of its three branches return hardcoded flat bands — one of them
the identical ±15%, justified by an unsourced docstring claim — and the
module explicitly disclaims being predictive: "not a predictive
confidence interval… a transparency metric, not a probability of realized
outcome."  Stamping it would flip ``bandSources`` to
``stamped_value_band`` on most rows while changing nothing that is
actually known.

METHOD
======
For each disjoint (origin, horizon) window over the reconstructable
panel: rebuild the real contract at both dates via
``panel.panel_day`` + ``build_api_data_contract``, take
``rankDerivedValue`` per player, and record ``(v_h - v_o) / v_o``.
Report the empirical p10/p90 half-width of that distribution against
0.15, and the coverage the flat band would have achieved.

Folds are the same disjoint windows ``src/consensus_edge/backtest.py``
uses, so results are independent observations rather than an overlapping
smear.

WHAT THIS CANNOT TELL YOU — read before quoting it
==================================================
Four limits, emitted as JSON fields rather than prose so they travel
with the numbers:

* ``modelIsCurrent`` — the replay runs TODAY's Hill curves over past
  inputs, so measured movement is input-driven only.  Real board movement
  also came from constant promotions, so this **understates** true
  movement — and the direction of that bias is easy to get backwards.
  Understated movement makes the band look MORE excessive than it is: a
  "±15% is too wide" verdict is therefore an **upper bound on the
  excess**, not a conservative one.  A "too narrow" verdict would be the
  emphatic one, because true movement is larger still.
* ``panelHeterogeneity`` — ``CSVs/site_raw`` held 9 sources on
  2026-04-16 and 24 from 2026-06-01.  Source count drives both band width
  and movement, so per-fold figures are reported and the early era is
  visible rather than blended away.
* ``offseasonOnly`` — the whole reconstructable window is the offseason.
  April-August volatility is not September volatility.
* ``measuresSelfConsistency`` — this is how much OUR board moves, not how
  wrong it is.  It cannot capture common-mode error, so decision #4's
  "too narrow, and for the right reason" argument survives it.

And the simulator has **no horizon at all**, so this yields a family of
numbers (h7/h14/h30), not a single answer.  Choosing among them is still
a judgement — but one anchored to measured quantities instead of to
nothing.

Exit codes: 0 verdict produced, 1 no usable folds, 2 refusing to measure
(shallow clone, panel too short).  A missing corpus is 2, never 0 — "no
data" must not read as "passed".
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.consensus_edge import backtest as bt  # noqa: E402
from src.consensus_edge import panel  # noqa: E402

OUT_DIR = REPO / "docs" / "measurements"

EXIT_OK, EXIT_NO_FOLDS, EXIT_REFUSED = 0, 1, 2

# The constant under examination: MonteCarloButton.jsx synthesizes
# p10 = v*0.85 / p90 = v*1.15 for every asset.
FLAT_BAND = 0.15

# Below this a fold's quantiles are noise, not a distribution.  Same
# floor the consensus-edge backtest uses.
MIN_PAIRS_PER_FOLD = bt.MIN_PAIRS_PER_FOLD


def _log(msg: str) -> None:
    print(f"[mc-band] {msg}", file=sys.stderr)


def _board_values(when: date) -> dict[str, float]:
    """``rankDerivedValue`` per player as of ``when``."""
    with panel.panel_day(when) as day:
        contract = build_api_data_contract(day.payload, csv_root=day.csv_root)
    out: dict[str, float] = {}
    for row in contract.get("playersArray") or []:
        name = row.get("displayName") or row.get("name")
        raw = row.get("rankDerivedValue")
        if name and isinstance(raw, (int, float)) and raw > 0:
            out[f"{name}::{row.get('assetClass') or ''}"] = float(raw)
    return out


def _halfwidth(returns: list[float]) -> dict[str, float]:
    """Empirical p10/p90 half-width, and what ±15% would have covered."""
    ordered = sorted(returns)
    n = len(ordered)

    def q(p: float) -> float:
        return ordered[min(n - 1, max(0, int(round(p * (n - 1)))))]

    p10, p90 = q(0.10), q(0.90)
    covered = sum(1 for r in ordered if abs(r) <= FLAT_BAND) / n
    return {
        "n": n,
        "p10": round(p10, 5),
        "p50": round(q(0.50), 5),
        "p90": round(p90, 5),
        # Half the p10..p90 span — directly comparable to FLAT_BAND.
        "impliedHalfWidth": round((p90 - p10) / 2.0, 5),
        "medianAbsReturn": round(statistics.median(abs(r) for r in ordered), 5),
        "flatBandCoverage": round(covered, 4),
    }


def run(horizon_days: int, *, limit_folds: int | None = None) -> dict[str, Any]:
    try:
        available = panel.available_dates()
    except Exception as exc:  # noqa: BLE001 — refusing is the point
        raise SystemExit(f"panel unavailable: {exc}")

    windows = bt.folds(available, horizon_days)
    if limit_folds:
        windows = windows[:limit_folds]
    _log(f"h{horizon_days}: {len(available)} panel days -> {len(windows)} disjoint folds")

    cache: dict[date, dict[str, float]] = {}

    def values(d: date) -> dict[str, float]:
        if d not in cache:
            cache[d] = _board_values(d)
        return cache[d]

    per_fold: list[dict[str, Any]] = []
    pooled: list[float] = []
    attrition = {"noOrigin": 0, "noHorizon": 0}

    for w in windows:
        try:
            origin, horizon = values(w.origin), values(w.horizon)
        except Exception as exc:  # noqa: BLE001 — one bad day must not kill the run
            _log(f"  fold {w.origin}->{w.horizon} skipped: {exc}")
            continue
        rets: list[float] = []
        for key, v0 in origin.items():
            v1 = horizon.get(key)
            if v1 is None:
                attrition["noHorizon"] += 1
                continue
            rets.append((v1 - v0) / v0)
        attrition["noOrigin"] += len(set(horizon) - set(origin))
        if len(rets) < MIN_PAIRS_PER_FOLD:
            _log(f"  fold {w.origin}->{w.horizon}: only {len(rets)} pairs, dropped")
            continue
        stats = _halfwidth(rets)
        stats.update({"origin": w.origin.isoformat(), "horizon": w.horizon.isoformat()})
        per_fold.append(stats)
        pooled.extend(rets)
        _log(
            f"  {w.origin} -> {w.horizon}: n={stats['n']} "
            f"halfWidth={stats['impliedHalfWidth']:.4f} "
            f"coverage={stats['flatBandCoverage']:.3f}"
        )

    result: dict[str, Any] = {
        "measurement": "monte-carlo-band-width",
        "question": (
            "The simulator draws every asset from a flat +-15% band. How far does the "
            "board actually move over the same kind of interval?"
        ),
        "flatBandUnderTest": FLAT_BAND,
        "horizonDays": horizon_days,
        "panelDays": len(available),
        "panelStart": available[0].isoformat() if available else None,
        "panelEnd": available[-1].isoformat() if available else None,
        "foldsAttempted": len(windows),
        "foldsUsable": len(per_fold),
        "byFold": per_fold,
        "attrition": attrition,
        "caveats": {
            "modelIsCurrent": (
                "The replay runs TODAY's Hill curves over past inputs, so measured "
                "movement is input-driven only; real board movement also came from "
                "constant promotions. This UNDERSTATES true movement, and the direction "
                "of that bias is easy to invert: understated movement makes the flat "
                "band look MORE excessive than it is, so a 'too wide' verdict is an "
                "UPPER BOUND on the excess, not a conservative floor. A 'too narrow' "
                "verdict would be the emphatic one."
            ),
            "panelHeterogeneity": (
                "CSVs/site_raw held 9 sources on 2026-04-16 and 24 from 2026-06-01. "
                "Source count drives both band width and movement; read byFold, not "
                "just the pooled figure."
            ),
            "offseasonOnly": (
                "The whole reconstructable window is the offseason. April-August "
                "volatility is not September volatility."
            ),
            "measuresSelfConsistency": (
                "This is how much OUR board moves, not how wrong it is. It cannot "
                "capture common-mode error, so decision #4's 'too narrow, and for the "
                "right reason' argument survives this measurement intact."
            ),
            "simulatorHasNoHorizon": (
                "monte_carlo.py's band is horizonless, so this yields a family of "
                "numbers (h7/h14/h30) rather than one. Choosing among them remains a "
                "judgement — an anchored one."
            ),
        },
    }

    if not per_fold:
        result["verdict"] = f"No usable folds at h{horizon_days}: refusing to report a band width."
        return result

    result["pooled"] = _halfwidth(pooled)
    hw = result["pooled"]["impliedHalfWidth"]
    cov = result["pooled"]["flatBandCoverage"]
    ratio = FLAT_BAND / hw if hw else float("inf")
    result["verdict"] = (
        f"Over {len(per_fold)} disjoint {horizon_days}-day folds "
        f"({result['pooled']['n']} player-pairs), the board's own p10-p90 half-width is "
        f"{hw:.4f} ({hw * 100:.2f}%), against the simulator's flat {FLAT_BAND:.0%}. The "
        f"flat band is {ratio:.2f}x that, and covers {cov:.1%} of observed moves. "
        "Read the caveats before quoting: the replay understates movement (so this "
        "ratio is an UPPER bound on the excess), this is offseason data, and the "
        "per-fold spread in byFold is wide."
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--horizon", type=int, default=7)
    ap.add_argument("--max-folds", type=int, default=None, help="cap folds (dev only)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    try:
        panel._assert_deep()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        _log(f"refusing to measure: {exc}")
        _log("run `git fetch --unshallow` — a shallow clone covers only the days it has")
        return EXIT_REFUSED

    result = run(args.horizon, limit_folds=args.max_folds)

    out = args.out or (OUT_DIR / f"mc-band-width-{date.today().isoformat()}-h{args.horizon}.json")
    if result["foldsUsable"]:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        _log(f"wrote {out.relative_to(REPO)}")
    else:
        _log("no usable folds — refusing to write a measurement")

    print(result["verdict"])
    return EXIT_OK if result["foldsUsable"] else EXIT_NO_FOLDS


if __name__ == "__main__":
    raise SystemExit(main())
