#!/usr/bin/env python3
"""Corridor dependency pass — candidate families under controlled failures.

Evaluates every candidate corridor methodology against a battery of injected
production-path failures plus a healthy control, and reports the metrics the
pass requires: trigger rate, false-intervention rate, detection rate,
direction, magnitude, source coverage, top-third impact, dependence lineage,
confidence sensitivity, missing-evidence behaviour and stability.

Run with ``--measure``. Add ``--tail903`` to repeat the whole battery with
the B4-selected tail policy enabled experimentally (the coupling test).
Nothing here changes production; ``TAIL_SATURATION_RANK`` is restored on
exit.

Why offline evaluation is exact here
------------------------------------

``canonicalConsensusRank`` is stamped at ``data_contract.py:~8506`` and
``_apply_market_corridor_clamp`` runs at ``:8562`` — after it. The corridor
therefore rewrites ``rankDerivedValue`` only and never reorders the board.
So a candidate is a pure function of ``(value, anchor, contributions,
confidenceBucket)`` over the pre-corridor rows, and evaluating candidates
against a perturbed copy of those rows reproduces exactly what the
production stage would do. One board build per tail setting, not one per
(candidate x scenario).

That ordering is also a finding in its own right: a clamped row keeps the
rank its UNCLAMPED value earned, so its published value and published rank
come from different stages.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent
PCT = 0.90


def _pctile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = int(round((len(sorted_vals) - 1) * max(0.0, min(1.0, p))))
    return float(sorted_vals[idx])


# ── the row view every candidate sees ────────────────────────────────


class Row:
    """Everything a corridor candidate is allowed to look at."""

    __slots__ = ("name", "value", "anchor", "anchor_src", "contribs", "bucket", "rank", "broken")

    def __init__(self, name, value, anchor, anchor_src, contribs, bucket, rank):
        self.name = name
        self.value = value
        self.anchor = anchor
        self.anchor_src = anchor_src
        self.contribs = contribs  # {source_key: contribution}
        self.bucket = bucket
        self.rank = rank
        self.broken = False

    def copy(self):
        r = Row(
            self.name,
            self.value,
            self.anchor,
            self.anchor_src,
            dict(self.contribs),
            self.bucket,
            self.rank,
        )
        r.broken = self.broken
        return r


def load_rows(tail_rank=None) -> list[Row]:
    """Pre-corridor IDP-side rows from a real pipeline build."""
    from src.api.data_contract import build_api_data_contract, _market_anchor_for_row
    from src.canonical import tail_policy

    board = sorted((ROOT / "exports/latest").glob("dynasty_data_*.json"), reverse=True)[0]
    raw = json.loads(board.read_bytes())
    prev = tail_policy.TAIL_SATURATION_RANK
    tail_policy.TAIL_SATURATION_RANK = tail_rank
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            contract = build_api_data_contract(raw, suppress_market_corridor_clamp=True)
    finally:
        tail_policy.TAIL_SATURATION_RANK = prev

    out = []
    for r in contract.get("playersArray") or []:
        if not r.get("canonicalConsensusRank"):
            continue
        if str(r.get("assetClass") or "") == "offense":
            continue
        anchor, src = _market_anchor_for_row(r)
        try:
            v = float(r.get("rankDerivedValue") or 0.0)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        contribs = {}
        for k, m in (r.get("sourceRankMeta") or {}).items():
            if isinstance(m, dict):
                try:
                    c = float(m.get("valueContribution") or 0.0)
                except (TypeError, ValueError):
                    c = 0.0
                if c > 0:
                    contribs[k] = c
        out.append(
            Row(
                str(r.get("displayName")),
                v,
                anchor,
                src,
                contribs,
                str(r.get("confidenceBucket") or "low"),
                int(r["canonicalConsensusRank"]),
            )
        )
    return out


# ── candidate families ───────────────────────────────────────────────
#
# Each returns {name: ("clamp", new_value) | ("flag", None) | None}.
# "flag" is a DEGRADED/ABSTAIN outcome: detected, deliberately not coerced.


def _self_derived_bands(rows, anchor_of):
    by_bucket: dict[str, list[float]] = {}
    allv: list[float] = []
    for r in rows:
        a = anchor_of(r)
        if not a:
            continue
        d = abs(r.value - a) / a
        by_bucket.setdefault(r.bucket, []).append(d)
        allv.append(d)
    overall = _pctile(sorted(allv), PCT)
    return {
        b: (_pctile(sorted(v), PCT) if len(v) >= 30 else overall) for b, v in by_bucket.items()
    }, overall


def _clamp_to(r, a, band):
    if a is None or a <= 0:
        return None
    if abs(r.value - a) / a <= band:
        return None
    return ("clamp", a * (1.0 + band) if r.value > a else a * (1.0 - band))


def cand_current(rows):
    anchor_of = lambda r: r.anchor  # noqa: E731
    bands, overall = _self_derived_bands(rows, anchor_of)
    return {r.name: _clamp_to(r, r.anchor, bands.get(r.bucket, overall)) for r in rows}


def _loo_anchor(r):
    """Median of the row's contributions EXCLUDING the anchor source."""
    others = [v for k, v in r.contribs.items() if k != r.anchor_src]
    if not others:
        return None
    others.sort()
    n = len(others)
    return others[n // 2] if n % 2 else (others[n // 2 - 1] + others[n // 2]) / 2.0


def cand_loo_anchor(rows):
    bands, overall = _self_derived_bands(rows, _loo_anchor)
    out = {}
    for r in rows:
        a = _loo_anchor(r)
        out[r.name] = _clamp_to(r, a, bands.get(r.bucket, overall)) if a else None
    return out


def cand_multi_anchor(rows):
    """Median of >=3 non-anchor contributions; ABSTAIN below that."""

    def anchor(r):
        others = sorted(v for k, v in r.contribs.items() if k != r.anchor_src)
        if len(others) < 3:
            return None
        n = len(others)
        return others[n // 2] if n % 2 else (others[n // 2 - 1] + others[n // 2]) / 2.0

    bands, overall = _self_derived_bands(rows, anchor)
    out = {}
    for r in rows:
        a = anchor(r)
        if a is None:
            out[r.name] = ("flag", None)  # too thin to judge — abstain, do not coerce
        else:
            out[r.name] = _clamp_to(r, a, bands.get(r.bucket, overall))
    return out


#: Band measured once on a reference board and then held fixed, so it
#: cannot re-derive itself from the board it is policing.
HISTORICAL_BAND: float | None = None


def cand_historical_band(rows):
    band = HISTORICAL_BAND
    if band is None:
        return {r.name: None for r in rows}
    return {r.name: _clamp_to(r, r.anchor, band) for r in rows}


def cand_hull_invariant(rows):
    """Anomaly-only: the blend must lie inside its own inputs' hull.

    A weighted blend of source contributions cannot fall outside
    ``[min, max]`` of those contributions. Ordinary disagreement — however
    violent — can never trigger this; only a pipeline, routing or
    calibration fault can. So it separates "the market disagrees" from
    "the pipeline is broken", which is the distinction the corridor's
    stated purpose needs and its current form cannot make.
    """
    out = {}
    for r in rows:
        if len(r.contribs) < 2:
            out[r.name] = None
            continue
        lo, hi = min(r.contribs.values()), max(r.contribs.values())
        tol = 0.02
        if r.value > hi * (1 + tol):
            out[r.name] = ("clamp", hi)
        elif r.value < lo * (1 - tol):
            out[r.name] = ("clamp", lo)
        else:
            out[r.name] = None
    return out


def cand_hull_abstain(rows):
    """Same detector, DEGRADED instead of coercion."""
    return {n: (("flag", None) if d else None) for n, d in cand_hull_invariant(rows).items()}


def cand_changepoint(rows):
    """Board-level invariant: has the drift distribution SHIFTED?

    Not a per-row clamp. Fires one board-level alarm when this board's
    median drift departs from the reference by more than a factor, which
    is the thing a self-derived percentile structurally cannot see.
    """
    if HISTORICAL_BAND is None:
        return {r.name: None for r in rows}
    drifts = sorted(abs(r.value - r.anchor) / r.anchor for r in rows if r.anchor)
    med = drifts[len(drifts) // 2] if drifts else 0.0
    ref = HISTORICAL_BAND * 0.35  # reference median, derived with the band
    shifted = ref > 0 and (med / ref > 1.5 or med / ref < 0.667)
    return {r.name: (("flag", None) if shifted else None) for r in rows}


def cand_none(rows):
    return {r.name: None for r in rows}


def cand_external_anchor(rows):
    """Family 4 — genuinely independent external/reference anchor.

    **NOT CONSTRUCTIBLE on this tree, and that is the finding.** An
    independent anchor must come from a source that does not vote in the
    blend it constrains. Exactly one loaded source does not vote —
    ``ktc`` — and it is offense-only, while the corridor clamps IDP rows
    only. Every source covering IDP on the live board (idpTradeCalc,
    idpShow, draftSharksIdp, dlfIdp, fantasyProsIdp, dlfRookieIdp) votes.

    Implemented as a no-op that is reported rather than omitted, because
    "we did not evaluate it" and "it cannot exist without a new data
    source" are different statements and only the second is true.
    """
    return {r.name: None for r in rows}


CANDIDATES = {
    "1_current": cand_current,
    "2_loo_anchor": cand_loo_anchor,
    "3_multi_anchor": cand_multi_anchor,
    "4_external_anchor_NOT_CONSTRUCTIBLE": cand_external_anchor,
    "5_historical_band": cand_historical_band,
    "6_changepoint": cand_changepoint,
    "7_hull_anomaly_only": cand_hull_invariant,
    "8_hull_abstain": cand_hull_abstain,
    "9_none": cand_none,
}


# ── scenarios ────────────────────────────────────────────────────────


def sc_healthy(rows, rng):
    return [r.copy() for r in rows]


def _jitter_sources(rows, rng, sd):
    """Perturb CONTRIBUTIONS and carry the blend with them.

    Load-bearing, and the first draft got it wrong. Perturbing ``value``
    alone moves the blend independently of its own inputs, which violates
    the hull invariant BY CONSTRUCTION — so it scores the hull candidate as
    firing on "normal disagreement" when what it actually detected was the
    scenario spoofing a pipeline fault. Real disagreement moves the
    sources, and the blend follows them and stays inside their range.
    """
    out = []
    for r in rows:
        c = r.copy()
        fs = []
        for k in list(c.contribs):
            f = max(0.05, 1.0 + rng.gauss(0, sd))
            c.contribs[k] *= f
            fs.append(f)
        if c.anchor and c.anchor_src in c.contribs:
            c.anchor = c.contribs[c.anchor_src]
        c.value = max(1.0, c.value * (sum(fs) / len(fs) if fs else 1.0))
        out.append(c)
    return out


def sc_normal_disagreement(rows, rng):
    return _jitter_sources(rows, rng, 0.08)


def _break_rows(rows, rng, frac, mult, which):
    out = [r.copy() for r in rows]
    idxs = rng.sample(range(len(out)), max(1, int(frac * len(out))))
    for i in idxs:
        c = out[i]
        c.broken = True
        if which == "value":
            c.value *= mult
        elif which == "anchor":
            if c.anchor:
                c.anchor *= mult
                if c.anchor_src in c.contribs:
                    c.contribs[c.anchor_src] *= mult
        elif which == "one_source":
            ks = [k for k in c.contribs if k != c.anchor_src]
            if ks:
                c.contribs[rng.choice(ks)] *= mult
                c.value *= 1.0 + (mult - 1.0) / max(1, len(c.contribs))
        elif which == "correlated":
            ks = [k for k in c.contribs if k != c.anchor_src][:3]
            for k in ks:
                c.contribs[k] *= mult
            if ks:
                c.value *= 1.0 + (mult - 1.0) * len(ks) / max(1, len(c.contribs))
    return out


def sc_one_source_anomaly(rows, rng):
    return _break_rows(rows, rng, 0.05, 5.0, "one_source")


def sc_anchor_anomaly(rows, rng):
    return _break_rows(rows, rng, 0.05, 5.0, "anchor")


def sc_correlated_anomaly(rows, rng):
    return _break_rows(rows, rng, 0.05, 3.0, "correlated")


def sc_whole_board_drift(rows, rng):
    out = [r.copy() for r in rows]
    for c in out:
        c.value *= 1.5
        c.broken = True
    return out


def sc_routing_failure(rows, rng):
    """Wrong-curve routing: a slice is priced on a different master.

    Reproduced as the measured GLOBAL-vs-IDP ratio at equal rank rather
    than an invented multiplier — the W02-F001 failure mode, which the
    corridor is downstream of.
    """
    out = [r.copy() for r in rows]
    idxs = rng.sample(range(len(out)), int(0.25 * len(out)))
    for i in idxs:
        out[i].value *= 0.48
        out[i].broken = True
    return out


SCENARIOS = {
    "healthy_control": sc_healthy,
    "normal_disagreement": sc_normal_disagreement,
    "one_source_anomaly": sc_one_source_anomaly,
    "anchor_source_anomaly": sc_anchor_anomaly,
    "correlated_multi_source": sc_correlated_anomaly,
    "whole_board_scale_drift": sc_whole_board_drift,
    "coordinate_routing_failure": sc_routing_failure,
}


# ── evaluation ───────────────────────────────────────────────────────


def evaluate(cand_fn, rows):
    dec = cand_fn(rows)
    by = {r.name: r for r in rows}
    fired = [n for n, d in dec.items() if d]
    clamps = [n for n, d in dec.items() if d and d[0] == "clamp"]
    flags = [n for n, d in dec.items() if d and d[0] == "flag"]
    broken = {r.name for r in rows if r.broken}
    caught = len([n for n in fired if n in broken])
    healthy_fired = len([n for n in fired if n not in broken])
    n_healthy = len(rows) - len(broken)

    ups = downs = 0
    mags = []
    for n in clamps:
        r, (_k, nv) = by[n], dec[n]
        if nv > r.value:
            ups += 1
        else:
            downs += 1
        mags.append(abs(nv - r.value) / r.value)
    mags.sort()

    third = sorted(r.rank for r in rows)
    cutoff = third[len(third) // 3] if third else 0
    top_third = len([n for n in fired if by[n].rank <= cutoff])
    lineage = len([n for n in fired if by[n].anchor_src in by[n].contribs])
    no_anchor = len([r for r in rows if not r.anchor])
    no_anchor_fired = len([n for n in fired if not by[n].anchor])

    bucket_fired: dict[str, int] = {}
    for n in fired:
        bucket_fired[by[n].bucket] = bucket_fired.get(by[n].bucket, 0) + 1
    cov = sorted(len(by[n].contribs) for n in fired)

    return {
        "rows": len(rows),
        "fired": len(fired),
        "clamped": len(clamps),
        "flagged": len(flags),
        "triggerRatePct": round(100.0 * len(fired) / len(rows), 2) if rows else 0.0,
        "brokenRows": len(broken),
        "detectionPct": round(100.0 * caught / len(broken), 2) if broken else None,
        "falseInterventionPct": round(100.0 * healthy_fired / n_healthy, 2) if n_healthy else None,
        "directionUp": ups,
        "directionDown": downs,
        "medianMagnitudePct": round(100.0 * mags[len(mags) // 2], 2) if mags else None,
        "maxMagnitudePct": round(100.0 * mags[-1], 2) if mags else None,
        "medianSourceCoverageOnFired": cov[len(cov) // 2] if cov else None,
        "topThirdFired": top_third,
        "firedWhoseAnchorAlsoVotes": lineage,
        "rowsWithNoAnchor": no_anchor,
        "firedWithNoAnchor": no_anchor_fired,
        "firedByBucket": bucket_fired,
    }


def stability(cand_fn, rows, rng, trials=5):
    """Jaccard of the fired set across small, COHERENT board perturbations.

    Perturbs sources and lets the blend follow, for the same reason
    ``_jitter_sources`` does: jittering the blend alone would spoof a
    pipeline fault and score an invariant-based candidate as unstable when
    it was correctly detecting the spoof.

    Two empty sets are perfectly stable, not undefined — a candidate that
    fires on nothing before and nothing after has agreed with itself.
    """
    base = {n for n, d in cand_fn(rows).items() if d}
    js = []
    for _ in range(trials):
        f = {n for n, d in cand_fn(_jitter_sources(rows, rng, 0.02)).items() if d}
        u = base | f
        js.append(len(base & f) / len(u) if u else 1.0)
    return round(sum(js) / len(js), 4)


def measure(tail903: bool) -> dict:
    global HISTORICAL_BAND
    tail = 903 if tail903 else None
    label = "TAIL_SATURATION_RANK=903 (B4 coupling)" if tail903 else "production tail (None)"
    print("\n" + "#" * 74)
    print(f"#  {label}")
    print("#" * 74)

    rows = load_rows(tail)
    print(f"\neligible pre-corridor IDP-side rows: {len(rows)}")

    # The historical/reference band is measured ONCE on the healthy board
    # and then frozen. That is the whole point of candidate 5: it must not
    # be recomputed from the board it is policing.
    healthy_drifts = sorted(abs(r.value - r.anchor) / r.anchor for r in rows if r.anchor)
    HISTORICAL_BAND = _pctile(healthy_drifts, PCT)
    print(f"reference band frozen from this healthy board: {HISTORICAL_BAND:.4f}")

    results: dict = {
        "tail": tail,
        "eligibleRows": len(rows),
        "referenceBand": round(HISTORICAL_BAND, 4),
    }
    for sname, sfn in SCENARIOS.items():
        rng = random.Random(20260811)
        pert = sfn(rows, rng)
        print(f"\n=== scenario: {sname}  (broken rows: {sum(1 for r in pert if r.broken)}) ===")
        print(
            f"  {'candidate':<22}{'fire%':>7}{'detect%':>9}{'falseInt%':>11}"
            f"{'up/down':>10}{'medMag%':>9}{'top3rd':>8}{'lineage':>9}"
        )
        results.setdefault("scenarios", {})[sname] = {}
        for cname, cfn in CANDIDATES.items():
            m = evaluate(cfn, pert)
            results["scenarios"][sname][cname] = m
            det = m["detectionPct"] if m["detectionPct"] is not None else -1.0
            fi = m["falseInterventionPct"] if m["falseInterventionPct"] is not None else -1.0
            updown = f"{m['directionUp']}/{m['directionDown']}"
            print(
                f"  {cname:<22}{m['triggerRatePct']:>7.1f}{det:>9.1f}{fi:>11.1f}"
                f"{updown:>10}{(m['medianMagnitudePct'] or 0):>9.1f}"
                f"{m['topThirdFired']:>8}{m['firedWhoseAnchorAlsoVotes']:>9}"
            )

    print("\n=== stability (Jaccard of fired set under +/-2% board noise, 5 trials) ===")
    rng = random.Random(7)
    results["stability"] = {}
    for cname, cfn in CANDIDATES.items():
        s = stability(cfn, rows, rng)
        results["stability"][cname] = s
        print(f"  {cname:<22}{s:>8.4f}")
    return results


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure", action="store_true")
    ap.add_argument("--tail903", action="store_true", help="also run the B4 coupling battery")
    args = ap.parse_args()
    if not args.measure:
        ap.error("pass --measure")
    payload = {"production": measure(False)}
    if args.tail903:
        payload["tail903"] = measure(True)
    (OUT / "cd_corridor_candidates.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / 'cd_corridor_candidates.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
