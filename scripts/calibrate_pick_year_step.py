#!/usr/bin/env python3
"""C1-U6 champion/challenger calibration for the future-pick year step.

THE QUESTION (declared target per MATH_MODEL_CALIBRATION_POLICY §9):
what multiplier family best describes how the dynasty market steps a
generic pick-tier value DOWN one further year of distance, so the
pipeline's synthesized far-future year (today: 2029, cloned from 2028)
carries a derivation anchored in measured market behavior instead of the
retired hand-authored 0.53.

EVIDENCE — pure vendor observations only:
``site_raw/ktcSfTep.csv`` + ``site_raw/idpTradeCalc.csv`` inside every
archived export bundle (``exports/archive/dynasty_export_*.zip``, one
per date, 2026-07-14 onward).  These are the exact numbers the contract
blend votes with.  Deliberately NOT the raw payload's per-player ``ktc``
key (the scraper's own model composite — contaminated by its internal
tier model and its clamped [0.60,0.95] discount recalibration) and NOT
the temporal ledger's ``source_value`` lane for the same reason (the
backfill ingested the payload, so its pick-tier ``ktc`` rows inherit the
composite; its ``ktcSfTep``/``idpTradeCalc`` rows exist only from live
recording, which starts 2026-08-16).  This is a one-time offline
calibration read of the retained raw-evidence archive, not a production
consumer of history.

WHAT EACH RATIO IS: a same-day, same-provider, cross-sectional
observation ``value(year+2 tiers) / value(year+1 tiers)`` per
(tier, round) cell, rounds 1-4 (no vendor publishes future rounds 5-6).
Both legs of every ratio are observed simultaneously by one provider —
there is NO temporal leakage by construction; nothing about a later
date informs an earlier ratio.

FAMILIES COMPARED:
  incumbent        2029 = clone(2028) x 0.53   (offsetDiscounts["3"])
  config_step      x (0.53/0.66) = 0.803       (incremental config curve)
  pooled_step      x pooled median ratio       (1 parameter, measured)
  per_round_step   x round-median ratio        (4 parameters, measured)
  per_cell_step    x (tier x round) cell ratio (12 parameters, measured)

EVALUATION (leakage-free splits):
  provider holdout — fit each measured family on ONE provider's cells,
      score it predicting the OTHER provider's observed 2028 tier values
      from that provider's own 2027 values (median/mean absolute
      percentage error per cell-date).
  time holdout — fit on the first half of archive dates, score on the
      second half (KTC only; IDPTC's pick board is frozen across the
      window — one independent observation, 34 copies, and it is
      counted as such).

THE EXTRAPOLATION ASSUMPTION, NAMED: every family is fitted on the
1-out -> 2-out step (the furthest pair any vendor publishes) and applied
to the 2-out -> 3-out step.  No market evidence for the latter exists
anywhere in scope, so whichever family wins remains classification
PRIOR (measured-anchored), never MEASURED/VALIDATED.  The evaluation
answers only "which family describes the observable step best" — the
honest limit of today's evidence.

Output: JSON parameter block (for config/weights/pick_year_discount.json
``derivedYearModel``) + the scored comparison table.  Results are pinned
in docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md; re-run after material
archive growth.

Exit codes: 0 = scored and emitted; 2 = insufficient evidence (never 0).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
ARCHIVE = _REPO / "exports" / "archive"
TIER_RE = re.compile(r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(?:st|nd|rd|th)$", re.I)
PROVIDERS = ("ktcSfTep", "idpTradeCalc")
TIERS = ("Early", "Mid", "Late")
ROUNDS = (1, 2, 3, 4)


def load_archive() -> dict[str, dict[str, dict[tuple[int, str, int], float]]]:
    """date -> provider -> (year, tier, round) -> vendor value."""
    out: dict[str, dict[str, dict[tuple[int, str, int], float]]] = defaultdict(
        lambda: defaultdict(dict)
    )
    seen: set[str] = set()
    for zp in sorted(ARCHIVE.glob("dynasty_export_*.zip")):
        m = re.search(r"(\d{8})_", zp.name)
        if not m or m.group(1) in seen:
            continue
        date = m.group(1)
        try:
            z = zipfile.ZipFile(zp)
            names = set(z.namelist())
        except Exception:
            continue
        got = False
        for prov in PROVIDERS:
            member = f"site_raw/{prov}.csv"
            if member not in names:
                continue
            try:
                rows = list(
                    csv.DictReader(io.StringIO(z.read(member).decode("utf-8", errors="replace")))
                )
            except Exception:
                continue
            for row in rows:
                tm = TIER_RE.match((row.get("name") or "").strip())
                if not tm:
                    continue
                try:
                    val = float(row.get("value") or 0)
                except ValueError:
                    continue
                if val <= 0:
                    continue
                out[date][prov][(int(tm.group(1)), tm.group(2).capitalize(), int(tm.group(3)))] = (
                    val
                )
                got = True
        if got:
            seen.add(date)
    return out


def year_pair(per_date, dates, providers):
    """[(date, provider, tier, round, v_1out, v_2out)] for the two
    furthest published years on each date (self-rolling: derived from
    the data, never a literal)."""
    obs = []
    for date in dates:
        for prov in providers:
            vals = per_date[date].get(prov) or {}
            years = sorted({y for (y, t, r) in vals})
            if len(years) < 3:
                continue
            y1, y2 = years[-2], years[-1]  # 1-out and 2-out classes
            for tier in TIERS:
                for rnd in ROUNDS:
                    a, b = vals.get((y1, tier, rnd)), vals.get((y2, tier, rnd))
                    if a and b:
                        obs.append((date, prov, tier, rnd, a, b))
    return obs


def fit_cells(obs):
    """Per-(tier, round) median ratio, plus round and pooled medians."""
    cells = defaultdict(list)
    for _d, _p, tier, rnd, a, b in obs:
        cells[(tier, rnd)].append(b / a)
    cell_med = {k: statistics.median(v) for k, v in cells.items()}
    round_med = {}
    for rnd in ROUNDS:
        pool = [r for (t, rr), v in cells.items() if rr == rnd for r in v]
        if pool:
            round_med[rnd] = statistics.median(pool)
    pooled = statistics.median([r for v in cells.values() for r in v]) if cells else None
    return cell_med, round_med, pooled


def score(obs, predict):
    """Median/mean absolute percentage error of predict(tier, round, v_1out)
    against the observed 2-out value."""
    errs = []
    for _d, _p, tier, rnd, a, b in obs:
        pred = predict(tier, rnd, a)
        if pred is None:
            continue
        errs.append(abs(pred - b) / b)
    if not errs:
        return None
    return {
        "n": len(errs),
        "mape_median": round(statistics.median(errs) * 100, 2),
        "mape_mean": round(statistics.mean(errs) * 100, 2),
        "max_ape": round(max(errs) * 100, 2),
    }


def family_predictors(cell_med, round_med, pooled):
    return {
        "incumbent_0.53": lambda t, r, a: a * 0.53,
        "config_step_0.803": lambda t, r, a: a * (0.53 / 0.66),
        "pooled_step": (lambda t, r, a: a * pooled) if pooled else None,
        "per_round_step": lambda t, r, a: (a * round_med[r]) if r in round_med else None,
        "per_cell_step": lambda t, r, a: (a * cell_med[(t, r)]) if (t, r) in cell_med else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-out", help="write the winning parameter block here")
    args = ap.parse_args()

    per_date = load_archive()
    dates = sorted(per_date)
    if len(dates) < 8:
        print(f"INSUFFICIENT EVIDENCE: only {len(dates)} archive dates with vendor pick tiers")
        return 2
    print(f"archive dates with vendor pick tiers: {len(dates)} ({dates[0]}..{dates[-1]})")

    results: dict[str, dict[str, dict]] = defaultdict(dict)

    # ── Provider holdout ────────────────────────────────────────────
    for fit_prov, eval_prov in ((PROVIDERS[0], PROVIDERS[1]), (PROVIDERS[1], PROVIDERS[0])):
        fit_obs = year_pair(per_date, dates, [fit_prov])
        eval_obs = year_pair(per_date, dates, [eval_prov])
        cell_med, round_med, pooled = fit_cells(fit_obs)
        for name, pred in family_predictors(cell_med, round_med, pooled).items():
            if pred is None:
                continue
            results[name][f"fit={fit_prov}->eval={eval_prov}"] = score(eval_obs, pred)

    # ── Time holdout (KTC only — IDPTC frozen in the window) ────────
    half = len(dates) // 2
    fit_obs = year_pair(per_date, dates[:half], ["ktcSfTep"])
    eval_obs = year_pair(per_date, dates[half:], ["ktcSfTep"])
    cell_med, round_med, pooled = fit_cells(fit_obs)
    for name, pred in family_predictors(cell_med, round_med, pooled).items():
        if pred is None:
            continue
        results[name]["time_split_ktc"] = score(eval_obs, pred)

    print("\n=== challenger scores (absolute percentage error vs observed 2-out values) ===")
    for name, splits in results.items():
        print(f"\n{name}")
        for split, sc in splits.items():
            print(f"  {split}: {sc}")

    # ── Final parameters: fit on ALL evidence, cross-provider ───────
    all_obs = year_pair(per_date, dates, list(PROVIDERS))
    cell_med, round_med, pooled = fit_cells(all_obs)

    # Per-provider cell medians, for the cross-provider disagreement band.
    per_prov_cells = {}
    for prov in PROVIDERS:
        c, _, _ = fit_cells(year_pair(per_date, dates, [prov]))
        per_prov_cells[prov] = c
    disagreement = {}
    for key in cell_med:
        a = per_prov_cells[PROVIDERS[0]].get(key)
        b = per_prov_cells[PROVIDERS[1]].get(key)
        if a and b:
            disagreement[f"{key[0].lower()}.{key[1]}"] = round(abs(a - b) / ((a + b) / 2), 4)

    block = {
        "family": "measured_vendor_year_step_v1",
        "classification": "PRIOR",
        "classificationNote": (
            "measured-anchored: each cell is the median same-day cross-sectional "
            "1-out->2-out ratio over both vendor families and every archive date; "
            "applying it to the 2-out->3-out step is an extrapolation no market "
            "evidence can test today, so the family stays PRIOR, never VALIDATED"
        ),
        "stepByTierRound": {
            f"{t.lower()}.{r}": round(v, 4) for (t, r), v in sorted(cell_med.items())
        },
        "stepByRound": {str(r): round(v, 4) for r, v in sorted(round_med.items())},
        "stepFallback": round(pooled, 4),
        "crossProviderDisagreement": disagreement,
        "evidence": {
            "windowDates": [dates[0], dates[-1]],
            "dateCount": len(dates),
            "providers": list(PROVIDERS),
            "cellObservations": len(all_obs),
            "note": (
                "idpTradeCalc's pick board is frozen across the window — "
                "treated as ONE independent observation, not 34"
            ),
        },
        "record": "docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md",
    }
    print("\n=== derivedYearModel parameter block ===")
    print(json.dumps(block, indent=2))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(block, indent=2) + "\n")
        print(f"\nwritten: {args.json_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
