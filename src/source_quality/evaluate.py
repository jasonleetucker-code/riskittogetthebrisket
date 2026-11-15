"""Walk-forward challenger evaluation, preregistered gates, whole-board impact.

Two evaluation spaces, labelled everywhere they appear:

* **harness space (primary, preregistered)** -- for each test origin T and each
  held-out family G, a board blended from the OTHER families' as-published
  observations at T (weighted mean of ``-log(rank)``) is scored against G's own
  published board at T+h.  The target never contains a family that is in the
  predictor, so a family cannot be rewarded for predicting itself.  Weights for
  a test origin are learned only from origins whose whole target window closed
  before the fold began (purged walk-forward); the learner receives a matrix cut
  at that date, so a later observation cannot reach it.
* **pipeline space (impact, not a score)** -- the latest archived payload rebuilt
  through TODAY's canonical pipeline via the existing source-override path,
  once per candidate.  This is a counterfactual on one day's inputs, labelled as
  such; it measures what a candidate would change, never how good it is.

The comparison quantity is agreement with independent future evidence.  It is
never called accuracy, and KTC agreement is never a target.
"""

from __future__ import annotations

import hashlib
import subprocess
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from src.source_quality import SCHEMA
from src.source_quality import challengers as ch
from src.source_quality import metrics as mt
from src.source_quality import panel as pn
from src.source_quality.bootstrap import block_ids, bootstrap
from src.sources.ktc_market import KTC_MARKET_KEY

KTC_FAMILIES = frozenset({"ktcCrowd", "ktcTrades"})
KTC_KEYS = frozenset(
    {
        "ktc",
        "ktcSfTep",
        "ktcCrowdSfTep",
        "ktcTradesSfTep",
        KTC_MARKET_KEY,
        "fantasyNavigatorSf",
    }
)


@dataclass(frozen=True)
class Plan:
    """Everything the preregistration freezes."""

    primary_horizon: int = 21
    fold_start: date = date(2026, 6, 1)
    fold_days: int = 14
    min_test_blocks: int = 6
    stratum_min_cells: int = 200
    stratum_min_blocks: int = 4
    c2_min_blocks: int = 6
    c2_min_cells: int = 200
    c2_min_families_per_universe: int = 4
    sparse_max_families: int = 3
    in_season_start: date = date(2026, 9, 10)  # 2026 NFL regular-season kickoff
    metrics: mt.Config = field(default_factory=mt.Config)


CANDIDATES = ("C1_conservative_reliability", "C2_asset_class_reliability", "C3_lead_lag_authority")


# ── helpers ──────────────────────────────────────────────────────────────


def sha256_file(path: Path) -> str:
    """Content hash that is stable across checkouts: CRLF is normalized to LF, so
    a Windows ``core.autocrlf`` working copy hashes like the committed blob."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def git_head(root: Path) -> str | None:
    out = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return out.stdout.strip() if out.returncode == 0 else None


def panel_digest(panel: pn.ObservationPanel) -> str:
    h = hashlib.sha256()
    for k in sorted(panel.versions):
        for v in panel.versions[k]:
            h.update(f"{k}|{v.known_at.isoformat()}|{v.content_hash}\n".encode())
    return h.hexdigest()


def slice_matrix(m: pn.Matrix, last: int) -> pn.Matrix:
    """The matrix as it stood at the end of date index ``last`` (inclusive)."""
    return pn.Matrix(
        assets=m.assets,
        universe=m.universe,
        dates=m.dates[: last + 1],
        obs={k: v[:, : last + 1] for k, v in m.obs.items()},
        age_days={k: v[: last + 1] for k, v in m.age_days.items()},
        rookie=m.rookie[:, : last + 1],
        identity=m.identity,
        specs=m.specs,
    )


def lineage_partners(lineage: Mapping[str, Any], keys: Sequence[str]) -> set[str]:
    """Every source sharing a recorded relation (proven/measured/suspected) with ``keys``."""
    out: set[str] = set()
    ks = set(keys)
    for rel in lineage.get("relations") or []:
        members = set(rel.get("sources") or [])
        if members & ks:
            out |= members - ks
    return out


def ktc_lineage_families(m: pn.Matrix, lineage: Mapping[str, Any]) -> frozenset[str]:
    partners = lineage_partners(lineage, sorted(KTC_KEYS)) | KTC_KEYS
    fams = {m.specs[k].family for k in partners if k in m.specs}
    return frozenset(fams | KTC_FAMILIES)


# ── learning (strictly from a sliced matrix) ─────────────────────────────


def _evidence_blocks(
    origins: np.ndarray, counts: np.ndarray, dates: Sequence[date], block_days: int
) -> int:
    used = [dates[j] for j, n in zip(origins, counts) if n > 0]
    return int(len(np.unique(block_ids(used, block_days)))) if used else 0


def learn_reliability(
    m: pn.Matrix,
    X: Mapping[str, np.ndarray],
    cfg: mt.Config,
    horizon: int,
    universes: Sequence[str],
) -> dict[str, ch.Quality]:
    per_fam: dict[str, list[tuple[float | None, float | None, int]]] = defaultdict(list)
    for u in universes:
        stats, origins = mt.future_agreement_stats(m, X, u, horizon, cfg)
        for f, st in stats.items():
            keep = st[:, 1] > 0
            if not keep.any():
                continue
            est = bootstrap(
                st[keep],
                lambda s: (-s[0] / s[1]) if s[1] > 0 else None,
                block_ids([m.dates[j] for j in origins[keep]], cfg.block_days),
                n_boot=cfg.n_boot,
                seed=cfg.seed,
            )
            per_fam[f].append((est.point, est.se, est.n_blocks))
    return {f: ch.pooled(v) for f, v in per_fam.items()}


def learn_lead(
    m: pn.Matrix,
    X: Mapping[str, np.ndarray],
    cfg: mt.Config,
    horizon: int,
    universes: Sequence[str],
) -> dict[str, ch.Quality]:
    per_fam: dict[str, list[tuple[float | None, float | None, int]]] = defaultdict(list)
    for u in universes:
        umask = m.universe == u
        for f in mt.families_in(X, umask):
            res = mt.lead_lag(m, X, f, u, horizon, cfg)
            if res.get("status") != "ok":
                continue
            b = res["betaGap"]
            per_fam[f].append((b["point"], b["se"], b["blocks"]))
    return {f: ch.pooled(v) for f, v in per_fam.items()}


def candidate_weights(
    name: str, m: pn.Matrix, X: Mapping[str, np.ndarray], plan: Plan, c2_enabled: bool
) -> tuple[dict[str, float], dict[str, dict[str, float]] | None, dict]:
    """Family weights (and per-universe weights for C2) learned from ``m`` only."""
    cfg, h = plan.metrics, plan.primary_horizon
    if name == "C1_conservative_reliability":
        w, diag = ch.shrunk_weights(learn_reliability(m, X, cfg, h, (pn.OFFENSE, pn.IDP)))
        return w, None, diag
    if name == "C3_lead_lag_authority":
        w, diag = ch.shrunk_weights(learn_lead(m, X, cfg, h, (pn.OFFENSE, pn.IDP)))
        return w, None, diag
    if name == "C2_asset_class_reliability":
        if not c2_enabled:
            return {}, None, {"reason": "not run: data-volume gate"}
        per_u: dict[str, dict[str, float]] = {}
        diags = {}
        for u in (pn.OFFENSE, pn.IDP):
            w, d = ch.shrunk_weights(learn_reliability(m, X, cfg, h, (u,)))
            per_u[u] = w
            diags[u] = d
        pooled_w, pd = ch.shrunk_weights(learn_reliability(m, X, cfg, h, (pn.OFFENSE, pn.IDP)))
        diags["pooled"] = pd
        return pooled_w, per_u, diags
    raise KeyError(name)


def c2_data_volume(m: pn.Matrix, X: Mapping[str, np.ndarray], plan: Plan) -> dict:
    """Data-volume gate for the asset-class-aware challenger (counts only, no scores)."""
    cfg, h = plan.metrics, plan.primary_horizon
    out: dict[str, Any] = {"universes": {}}
    ok = True
    for u in (pn.OFFENSE, pn.IDP):
        umask = m.universe == u
        fams = mt.families_in(X, umask)
        qualifying = []
        for f in fams:
            tgt, cnt = mt.consensus(X, [g for g in fams if g != f])
            tgt = np.where(cnt >= cfg.min_consensus_families, mt.shifted(tgt, h), np.nan)
            cell = np.isfinite(np.where(umask[:, None], X[f], np.nan)) & np.isfinite(tgt)
            cell &= mt.fresh_dates(m, f)[None, :]
            per_date = cell.sum(axis=0)
            origins = np.arange(len(m.dates))
            blocks = _evidence_blocks(origins, per_date, m.dates, cfg.block_days)
            if int(per_date.sum()) >= plan.c2_min_cells and blocks >= plan.c2_min_blocks:
                qualifying.append(f)
        out["universes"][u] = {"families": fams, "qualifying": qualifying}
        ok &= len(qualifying) >= plan.c2_min_families_per_universe
    out["run"] = bool(ok)
    return out


# ── harness-space walk-forward ───────────────────────────────────────────

#: Strata the broad-improvement requirement names (plus picks, gated separately).
REQUIRED_STRATA = frozenset({pn.OFFENSE, pn.IDP, "elite", "sparse"})
STRATA = ("ALL", pn.OFFENSE, pn.IDP, "elite", "core", "depth", "sparse", "rookie", "inSeason")


def _blend(
    X: Mapping[str, np.ndarray], fams: Sequence[str], w: Mapping[str, float]
) -> tuple[np.ndarray, np.ndarray]:
    num = None
    den = None
    cnt = None
    for f in fams:
        arr = X[f]
        ok = np.isfinite(arr)
        wf = float(w.get(f, 1.0))
        a = np.where(ok, arr * wf, 0.0)
        d = ok * wf
        num = a if num is None else num + a
        den = d if den is None else den + d
        cnt = ok.astype(int) if cnt is None else cnt + ok
    with np.errstate(invalid="ignore", divide="ignore"):
        return num / np.where(den > 0, den, np.nan), cnt


def _bands(
    score: np.ndarray, valid: np.ndarray, universe: str
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Elite/core/depth masks from the champion board's own rank at each date."""
    elite_n, core_n = mt.UNIVERSE_BANDS[universe]
    rank = np.full(score.shape, np.nan)
    for j in range(score.shape[1]):
        v = valid[:, j]
        if not v.any():
            continue
        order = np.argsort(-score[v, j], kind="stable")
        r = np.empty(order.size)
        r[order] = np.arange(1, order.size + 1)
        rank[np.where(v)[0], j] = r
    return rank <= elite_n, (rank > elite_n) & (rank <= core_n), rank > core_n


def walk_forward(
    m: pn.Matrix,
    X: Mapping[str, np.ndarray],
    plan: Plan,
    c2_enabled: bool,
    target_variants: Mapping[str, frozenset[str]],
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Per-date paired error sums, per candidate x target-variant x stratum."""
    cfg, h = plan.metrics, plan.primary_horizon
    D = len(m.dates)
    last_origin = D - 1 - h
    fold_starts = []
    d0 = m.dates.index(plan.fold_start) if plan.fold_start in m.dates else None
    if d0 is None:
        return {"status": "insufficient", "reason": "fold start outside panel"}
    j = d0
    while j <= last_origin:
        fold_starts.append(j)
        j += plan.fold_days
    # sums[candidate][variant][stratum] -> (D, 3) [sum err champion, sum err candidate, cells]
    sums: dict[str, dict[str, dict[str, np.ndarray]]] = {
        c: {v: {s: np.zeros((D, 3)) for s in STRATA} for v in target_variants} for c in CANDIDATES
    }
    fold_weights = []
    in_season = np.broadcast_to(
        np.array([d >= plan.in_season_start for d in m.dates])[None, :], (len(m.assets), D)
    )
    for fs in fold_starts:
        test = np.arange(fs, min(fs + plan.fold_days, last_origin + 1))
        cutoff = fs - 1 - h  # the last origin whose target window closes before the fold
        learn_last = fs - 1  # observations up to the day before the fold
        msl = slice_matrix(m, learn_last)
        Xsl = {f: a[:, : learn_last + 1] for f, a in X.items()}
        # origins after `cutoff` have targets past learn_last -> NaN in the slice
        del cutoff
        weights = {}
        for c in CANDIDATES:
            if progress:
                progress(f"fold {m.dates[fs]} learn {c}")
            weights[c] = candidate_weights(c, msl, Xsl, plan, c2_enabled)
        fold_weights.append(
            {
                "foldStart": m.dates[fs].isoformat(),
                "testOrigins": [m.dates[test[0]].isoformat(), m.dates[test[-1]].isoformat()],
                "learnedThrough": m.dates[learn_last].isoformat(),
                "weights": {
                    c: {k: round(v, 4) for k, v in w[0].items()} for c, w in weights.items()
                },
                "c2PerUniverse": (
                    {
                        u: {k: round(v, 4) for k, v in ww.items()}
                        for u, ww in weights["C2_asset_class_reliability"][1].items()
                    }
                    if weights["C2_asset_class_reliability"][1]
                    else None
                ),
            }
        )
        for u in (pn.OFFENSE, pn.IDP):
            umask = m.universe == u
            fams = mt.families_in(X, umask)
            Xu = {f: np.where(umask[:, None], X[f], np.nan) for f in fams}
            for G in fams:
                others = [f for f in fams if f != G]
                champ, cnt = _blend(Xu, others, {})
                valid = cnt >= cfg.min_consensus_families
                y = mt.shifted(Xu[G], h)
                e0 = np.abs(champ - y)
                elite, core, depth = _bands(champ, valid, u)
                masks = {
                    "ALL": np.ones_like(valid),
                    pn.OFFENSE: np.full(valid.shape, u == pn.OFFENSE),
                    pn.IDP: np.full(valid.shape, u == pn.IDP),
                    "elite": elite,
                    "core": core,
                    "depth": depth,
                    "sparse": cnt <= plan.sparse_max_families,
                    "rookie": m.rookie,
                    "inSeason": in_season,
                }
                for c in CANDIDATES:
                    wfam, per_u, _diag = weights[c]
                    if c == "C2_asset_class_reliability" and not c2_enabled:
                        continue
                    w = per_u[u] if per_u else wfam
                    cand, _ = _blend(Xu, others, w)
                    e1 = np.abs(cand - y)
                    ok = valid & np.isfinite(e0) & np.isfinite(e1)
                    for v, excluded in target_variants.items():
                        if G in excluded:
                            continue
                        for s, mask in masks.items():
                            mm = ok & mask
                            for jj in test:
                                col = mm[:, jj]
                                if not col.any():
                                    continue
                                sums[c][v][s][jj] += (
                                    e0[col, jj].sum(),
                                    e1[col, jj].sum(),
                                    col.sum(),
                                )
    return {
        "status": "ok",
        "folds": fold_weights,
        "sums": sums,
        "foldStarts": [m.dates[f] for f in fold_starts],
    }


def _delta_estimates(st: np.ndarray, dates: Sequence[date], cfg: mt.Config) -> dict:
    keep = st[:, 2] > 0
    if not keep.any():
        return {"status": "insufficient", "cells": 0, "blocks": 0}
    st = st[keep]
    blocks = block_ids([d for d, k in zip(dates, keep) if k], cfg.block_days)
    delta = bootstrap(
        st,
        lambda s: (s[0] - s[1]) / s[2] if s[2] > 0 else None,
        blocks,
        n_boot=cfg.n_boot,
        seed=cfg.seed,
    )
    base = bootstrap(
        st, lambda s: s[0] / s[2] if s[2] > 0 else None, blocks, n_boot=cfg.n_boot, seed=cfg.seed
    )
    return {
        "status": "ok",
        "cells": int(st[:, 2].sum()),
        "blocks": delta.n_blocks,
        "championMALE": base.as_dict(5),
        "deltaMALE": delta.as_dict(5),  # champion error - candidate error; > 0 = candidate better
    }


def gates(
    wf: dict,
    plan: Plan,
    dates: Sequence[date],
    c2_enabled: bool,
    picks_unchanged: Mapping[str, bool | None],
) -> dict:
    """``picks_unchanged[c]``: True / False / None (unknown, see
    :func:`picks_requirement`); anything but True leaves picks as missing evidence."""
    cfg = plan.metrics
    out = {}
    for c in CANDIDATES:
        if c == "C2_asset_class_reliability" and not c2_enabled:
            out[c] = {"disposition": "NOT_RUN", "reason": "asset-class data-volume gate not met"}
            continue
        res: dict[str, Any] = {"strata": {}, "variants": {}}
        for v, by_s in wf["sums"][c].items():
            res["variants"][v] = {s: _delta_estimates(st, dates, cfg) for s, st in by_s.items()}
        res["strata"] = res["variants"]["allTargets"]
        agg = res["strata"]["ALL"]
        missing: list[str] = []
        failed: list[str] = []
        # G5 sample adequacy
        if agg.get("status") != "ok" or agg["blocks"] < plan.min_test_blocks:
            missing.append(
                f"G5: {agg.get('blocks', 0)} out-of-sample date blocks < {plan.min_test_blocks} required"
            )
        else:
            d, base = agg["deltaMALE"], agg["championMALE"]
            # G1 aggregate: CI excludes 0 and the gain exceeds the baseline metric's own SE
            if d["ci90"][0] is None or base["se"] is None:
                missing.append("G1: bootstrap undefined")
            elif not (d["point"] > 0 and d["ci90"][0] > 0 and d["point"] >= base["se"]):
                failed.append(
                    f"G1: delta {d['point']} (90% CI {d['ci90']}) vs materiality {base['se']} (champion MALE SE)"
                )
        # G2 broad: no evaluable stratum materially harmed.  REQUIRED strata must
        # be evaluable; the others are judged when samples support them and
        # otherwise only reported.
        not_evaluable: list[str] = []
        for s in STRATA[1:]:
            e = res["strata"][s]
            if (
                e.get("status") != "ok"
                or e["cells"] < plan.stratum_min_cells
                or e["blocks"] < plan.stratum_min_blocks
            ):
                msg = f"G2[{s}]: not evaluable ({e.get('cells', 0)} cells, {e.get('blocks', 0)} blocks)"
                (missing if s in REQUIRED_STRATA else not_evaluable).append(msg)
                continue
            lo, se = e["deltaMALE"]["ci90"][0], e["championMALE"]["se"]
            if lo is None or se is None:
                missing.append(f"G2[{s}]: bootstrap undefined")
            elif lo < -se:
                failed.append(f"G2[{s}]: 90% CI lower bound {lo} < -{se} (material harm)")
        pick_ok = picks_unchanged.get(c)
        if pick_ok is None:
            missing.append(
                "G2[PICK]: pick markets are not evaluable and no market-priced pick row was matched on the latest board (unknown: fails closed)"
            )
        elif not pick_ok:
            missing.append(
                "G2[PICK]: pick markets are not evaluable and the candidate changes market-priced pick rows on the latest board"
            )
        # G3 KTC / lineage sensitivity
        for v in ("noKtcTargets", "noKtcLineageTargets"):
            e = res["variants"][v]["ALL"]
            if e.get("status") != "ok" or e["deltaMALE"]["ci90"][0] is None:
                missing.append(f"G3[{v}]: not evaluable")
            elif not e["deltaMALE"]["ci90"][0] > 0:
                failed.append(f"G3[{v}]: 90% CI lower bound {e['deltaMALE']['ci90'][0]} <= 0")
        if failed:
            disp = "DOES_NOT_MEET_PREREGISTERED_GATE"
        elif missing:
            disp = "INSUFFICIENT_EVIDENCE"
        else:
            disp = "MEETS_PREREGISTERED_GATE"
        res.update(
            {
                "disposition": disp,
                "failed": failed,
                "missingEvidence": missing,
                "notEvaluable": not_evaluable,
            }
        )
        out[c] = res
    return out


# ── pipeline-space impact (override path) ────────────────────────────────


def registry_families() -> dict[str, str]:
    from src.api import data_contract as dc

    return {
        str(s["key"]): dc.correlation_group_for(str(s["key"]))
        for s in dc._RANKING_SOURCES
        if s.get("key")
    }


def c2_per_source(
    per_u: Mapping[str, Mapping[str, float]], pooled: Mapping[str, float], census: Mapping[str, Any]
) -> dict[str, float]:
    """Single-universe source keys take their universe's family weight; a key
    covering both universes keeps the pooled family weight."""
    fam_of = registry_families()
    out: dict[str, float] = {}
    for e in census.get("sources") or []:
        key = e.get("key")
        if key not in fam_of:
            continue
        pop = e.get("population") or {}
        fam = fam_of[key]
        if pop.get("offense") and not pop.get("idp"):
            w = per_u.get(pn.OFFENSE, {}).get(fam)
        elif pop.get("idp") and not pop.get("offense"):
            w = per_u.get(pn.IDP, {}).get(fam)
        else:
            w = pooled.get(fam)
        if w is not None:
            out[key] = w
    return out


def _rank_bands(base: Mapping, other: Mapping) -> dict:
    b = {r["displayName"]: r for r in base.get("playersArray") or [] if r.get("displayName")}
    o = {r["displayName"]: r for r in other.get("playersArray") or [] if r.get("displayName")}
    bands = [(1, 50), (51, 100), (101, 200), (201, 400), (401, 10**9)]
    out = {}
    for lo, hi in bands:
        moves = []
        for n, r in b.items():
            r0 = r.get("canonicalConsensusRank")
            r1 = (o.get(n) or {}).get("canonicalConsensusRank")
            if isinstance(r0, int) and lo <= r0 <= hi and isinstance(r1, int):
                moves.append(abs(r1 - r0))
        label = f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"
        out[label] = {
            "rows": len(moves),
            "moved": sum(1 for x in moves if x),
            "meanAbsRankMove": round(float(np.mean(moves)), 3) if moves else None,
            "maxAbsRankMove": max(moves) if moves else None,
        }
    top = sorted(
        (r for r in b.values() if isinstance(r.get("canonicalConsensusRank"), int)),
        key=lambda r: r["canonicalConsensusRank"],
    )[:24]
    out["top24Changes"] = [
        {
            "asset": r["displayName"],
            "rankBefore": r["canonicalConsensusRank"],
            "rankAfter": (o.get(r["displayName"]) or {}).get("canonicalConsensusRank"),
        }
        for r in top
        if (o.get(r["displayName"]) or {}).get("canonicalConsensusRank")
        != r["canonicalConsensusRank"]
    ]
    return out


PICK_MARKET_CLASSES = frozenset(
    {"direct_market_blend", "derived_year_step", "derived_round_step", "derived_uniform_tier_ev"}
)


def _pick_class(row: Mapping) -> str | None:
    p = row.get("pickValueProvenance")
    return p.get("class") if isinstance(p, Mapping) else None


def _subset_changes(base: Mapping, other: Mapping, pred: Callable[[Mapping], bool]) -> dict:
    o = {r["displayName"]: r for r in other.get("playersArray") or [] if r.get("displayName")}
    deltas = []
    for r in base.get("playersArray") or []:
        if not r.get("displayName") or not pred(r):
            continue
        a, b = r.get("rankDerivedValue"), (o.get(r["displayName"]) or {}).get("rankDerivedValue")
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            deltas.append(b - a)
    nz = [abs(d) for d in deltas if d]
    return {
        "rows": len(deltas),
        "changed": len(nz),
        "maxAbs": max(nz) if nz else 0,
        "medianAbsChanged": float(np.median(nz)) if nz else 0,
    }


def picks_requirement(market_priced: Mapping[str, Any] | None) -> bool | None:
    """The G2 picks requirement from ``picksMarketPriced`` impact counts.

    ``True`` only when market-priced pick rows were actually matched AND none
    changed.  Zero matched rows is UNKNOWN (``None``) -- "no pick row moved"
    and "no pick row was compared" must not read the same -- and the gate
    treats it as missing evidence (fails closed).
    """
    if not market_priced or not market_priced.get("rows"):
        return None
    return market_priced.get("changed") == 0


def sparse_changes(
    base: Mapping, other: Mapping, max_families: int = Plan.sparse_max_families
) -> dict:
    """Changes on SPARSE non-pick rows: ``independentSourceCount <= max_families``.

    The threshold is the harness's preregistered sparse stratum
    (``Plan.sparse_max_families``: at most 3 independent families), applied to
    the board row's own independent-family count, so the impact report and the
    harness name the same population.  (The 2026-09-30 run's impact used <= 2;
    see its report's post-hoc notes.)  A row whose count is MISSING is UNKNOWN,
    never sparse: it is excluded and counted in ``unknownFamilyCount``.
    """

    def count(r: Mapping) -> int | None:
        n = r.get("independentSourceCount")
        return n if isinstance(n, int) and not isinstance(n, bool) else None

    unknown = sum(
        1
        for r in base.get("playersArray") or []
        if r.get("assetClass") != "pick" and r.get("displayName") and count(r) is None
    )
    out = _subset_changes(
        base,
        other,
        lambda r: r.get("assetClass") != "pick"
        and (count(r) is not None and count(r) <= max_families),
    )
    return {**out, "maxFamilies": max_families, "unknownFamilyCount": unknown}


def concentration(contract: Mapping) -> dict:
    """Per-family share of applied weight on the rows it voted on, and row HHI."""
    fam_of = registry_families()
    shares: dict[str, list[float]] = defaultdict(list)
    hhis = []
    for r in contract.get("playersArray") or []:
        meta = r.get("sourceRankMeta") or {}
        per_fam: dict[str, float] = defaultdict(float)
        for k, mm in meta.items():
            w = mm.get("appliedWeight")
            if mm.get("contributedToBlend") is False or not isinstance(w, (int, float)) or w <= 0:
                continue
            per_fam[fam_of.get(k, k)] += w
        tot = sum(per_fam.values())
        if tot <= 0:
            continue
        for f, w in per_fam.items():
            shares[f].append(w / tot)
        hhis.append(sum((w / tot) ** 2 for w in per_fam.values()))
    return {
        "meanShareByFamily": {f: round(float(np.mean(v)), 4) for f, v in sorted(shares.items())},
        "maxShareAnyRow": round(max((max(v) for v in shares.values()), default=0.0), 4),
        "meanRowHHI": round(float(np.mean(hhis)), 4) if hhis else None,
    }


def board_impact(
    raw_payload: Mapping[str, Any],
    candidates: Mapping[str, Mapping[str, float]],
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Rebuild the latest payload once per candidate through the override path."""
    from src.api import value_replay as vr

    champion = vr.build(raw_payload)
    fam_of = registry_families()
    equal = {k: 1.0 for k in fam_of}
    reproduces = vr.board_hash(vr.build(raw_payload, {"weights": equal})) == vr.board_hash(champion)
    voting_fams = sorted(
        {
            fam_of[k]
            for r in champion.get("playersArray") or []
            for k in (r.get("sourceRankMeta") or {})
            if k in fam_of
        }
    )
    members = defaultdict(list)
    for k, f in fam_of.items():
        members[f].append(k)

    def loo(base_overrides: Mapping[str, float] | None, base_board: Mapping) -> dict:
        out = {}
        for f in voting_fams:
            spec: dict[str, Any] = {"disable": sorted(members[f])}
            if base_overrides:
                spec["weights"] = {k: v for k, v in base_overrides.items() if k not in members[f]}
            other = vr.build(raw_payload, spec)
            d = vr.board_diff(base_board, other)
            out[f] = {
                "rowsChanged": d["rowsChanged"],
                "top200MembershipChanges": d["top200MembershipChanges"],
                "maxAbsByGroup": {g: s["maxAbs"] for g, s in d["byGroup"].items()},
            }
        return out

    if progress:
        progress("champion leave-family-out")
    result: dict[str, Any] = {
        "kind": "pipeline-space counterfactual on the latest archived inputs (today's pipeline code); impact, not a score",
        "equalWeightOverrideReproducesChampion": reproduces,
        "champion": {
            "concentration": concentration(champion),
            "leaveFamilyOut": loo(None, champion),
        },
        "candidates": {},
    }
    for name, overrides in candidates.items():
        if progress:
            progress(f"impact {name}")
        board = vr.build(raw_payload, {"weights": dict(overrides)})
        diff = vr.board_diff(champion, board, top=15)
        result["candidates"][name] = {
            "overrides": dict(sorted(overrides.items())),
            "boardDiff": diff,
            "rankBands": _rank_bands(champion, board),
            "picks": _subset_changes(champion, board, lambda r: r.get("assetClass") == "pick"),
            # Picks priced from the pick MARKETS (KTC + IDPTC) or derived from them;
            # tethered current-year slots follow the rookie pool (rookie stratum).
            "picksMarketPriced": _subset_changes(
                champion,
                board,
                lambda r: r.get("assetClass") == "pick" and _pick_class(r) in PICK_MARKET_CLASSES,
            ),
            "sparse": sparse_changes(champion, board),
            "rookies": _subset_changes(champion, board, lambda r: bool(r.get("rookie"))),
            "concentration": concentration(board),
            "leaveFamilyOut": loo(overrides, board),
            "weightsAtCap": sorted(
                k for k, v in overrides.items() if abs(abs(v - 1.0) - ch.CAP) < 1e-9
            ),
        }
    return result


# ── report ───────────────────────────────────────────────────────────────


def to_jsonable(x: Any) -> Any:
    if isinstance(x, dict):
        return {str(k): to_jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [to_jsonable(v) for v in x]
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    if isinstance(x, np.ndarray):
        return x.tolist()
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, frozenset):
        return sorted(x)
    return x


def archive_records(result: Mapping[str, Any]) -> list[dict]:
    """One compact, append-friendly line per candidate evaluation."""
    recs = []
    for c, g in (result.get("gates") or {}).items():
        agg = (g.get("strata") or {}).get("ALL") or {}
        recs.append(
            {
                "schema": SCHEMA,
                "evaluatedAt": result["generatedAt"],
                "codeRevision": result["pins"]["codeRevision"],
                "preregistrationSha256": result["pins"]["preregistration"]["sha256"],
                "panelDigest": result["pins"]["panelDigest"],
                "dataWindow": result["dataWindow"],
                "candidate": c,
                "horizonDays": result["plan"]["primary_horizon"],
                "finalWeights": (result.get("finalWeights") or {}).get(c),
                "disposition": g.get("disposition"),
                "deltaMALE": agg.get("deltaMALE"),
                "championMALE": agg.get("championMALE"),
                "failed": g.get("failed"),
                "missingEvidence": g.get("missingEvidence"),
                "status": "SHADOW",
            }
        )
    return recs
