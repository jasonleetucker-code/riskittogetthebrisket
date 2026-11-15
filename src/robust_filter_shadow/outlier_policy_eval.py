"""Records and evaluation for ``outlier-corroborated-v1`` (2026-10-19).

``docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md`` fixes
every definition here; if this module and that document disagree, the document wins
and this module is the defect.

Three builds of one archived board, all in the directive's restored state (DLF IDP
vote hold OFF): the incumbent filter, the policy, and ``idp-hampel-n3-v1``. This
module only reads what those builds stamped and applies the registered metrics.
Nothing here changes a vote, a weight or a value. Missing is never zero: a unit with
no target is counted as not evaluable, never imputed.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from src.api import data_contract as dc
from src.api import outlier_policy as op
from src.robust_filter_shadow.outcomes import block_bootstrap, parse_time, target_day
from src.robust_filter_shadow.record import precap_weight

SCHEMA = "outlier-policy-replay/v1"
POLICY_FLAG = "outlier_disagreement_policy"
N3_FLAG = "idp_hampel_n3_challenger"
SEED = 2033
PRIMARY_H = 7
SECONDARY_H = (3, 14, 21)
BLOCK_DAYS = 7
RESAMPLES = 4000
NONINFERIORITY = 0.005
STABILITY_LIMIT = 1.10
MIN_UNITS = 300
MIN_DAYS = 10
MIN_BLOCKS = 4
MATERIAL = 0.10
OTHER_FILTER_CHALLENGERS = (
    "joint_outlier_sparse_challenger",
    "joint_sparse_limited_evidence",
    "rank_space_hampel_challenger",
    "rank_space_hampel_per_vote_challenger",
)
METHODS = ("incumbent", "policy", "n3", "none")


def _pins(overrides: Iterable[tuple[str, bool]]) -> list[tuple[str, bool]]:
    base = {
        "dlf_offense_only_vote": False,
        "source_freshness_weighting": True,
        "source_family_cap": True,
        "idp_deep_tail_native_challenger": False,
        POLICY_FLAG: False,
        N3_FLAG: False,
        **{f: False for f in OTHER_FILTER_CHALLENGERS},
    }
    base.update(dict(overrides))
    return sorted(base.items())


#: The three builds per board (PREREGISTRATION §2-§3).
BUILDS: dict[str, list[tuple[str, bool]]] = {
    "incumbent": _pins([]),
    "policy": _pins([(POLICY_FLAG, True)]),
    "n3": _pins([(N3_FLAG, True)]),
}


def family_of(source: str) -> str:
    return dc.correlation_group_for(source)


# ── record extraction ───────────────────────────────────────────────────


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def _row_votes(row: Mapping[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    votes: dict[str, float] = {}
    weights: dict[str, float] = {}
    for s, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, Mapping) or m.get("excludedReason"):
            continue
        v = _num(m.get("valueContribution"))
        if v is None or v <= 0:
            continue
        votes[str(s)] = v
        weights[str(s)] = round(precap_weight(m), 6)
    return votes, weights


def extract_record(builds: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The compact per-board record: incumbent votes once, every variant's outcome."""
    rows: dict[str, dict[str, Any]] = {}
    variants: dict[str, dict[str, list]] = {}
    mismatch: list[str] = []
    base_votes: dict[str, dict[str, float]] = {}
    for name, contract in builds.items():
        out: dict[str, list] = {}
        for row in contract.get("playersArray") or []:
            if not isinstance(row, Mapping) or not row.get("displayName"):
                continue
            key = str(row["displayName"])
            votes, weights = _row_votes(row)
            if name == "incumbent":
                rows[key] = {
                    "ac": row.get("assetClass"),
                    "pos": row.get("position"),
                    "votes": votes,
                    "w": weights,
                    "blend": _num(row.get("_blendedValueUncapped")),
                }
                base_votes[key] = votes
            elif base_votes.get(key) != votes and row.get("assetClass") != "pick":
                mismatch.append(f"{name}:{key}")
            out[key] = [
                _num(row.get("rankDerivedValue")),
                row.get("canonicalConsensusRank"),
                sorted(row.get("droppedSources") or []),
                row.get("confidenceBucket"),
            ]
        variants[name] = out
    policy = builds.get("policy") or {}
    reasons = {
        str(r["displayName"]): dict(r["outlierPolicyReasons"])
        for r in policy.get("playersArray") or []
        if isinstance(r, Mapping) and r.get("outlierPolicyReasons")
    }
    return {
        "rows": rows,
        "variants": variants,
        "policyReasons": reasons,
        "policyStamp": policy.get("outlierPolicy"),
        "checks": {"votesIdentical": not mismatch, "voteMismatches": mismatch[:50]},
    }


# ── the M1 emulator ─────────────────────────────────────────────────────


def blend(votes: Mapping[str, float], weights: Mapping[str, float]) -> float | None:
    """Family cap (base 1.0) then the pipeline's weighted count-aware blend."""
    if not votes:
        return None
    capped, _f = dc.cap_family_weights({k: float(weights.get(k, 1.0)) for k in votes})
    keys = sorted(votes)
    w = [capped[k] for k in keys]
    if sum(w) <= 0:
        return None
    centre, _mad = dc.weighted_count_aware_mean_median_blend([votes[k] for k in keys], w)
    return centre if centre and centre > 0 else None


def decide(
    method: str,
    votes: Mapping[str, float],
    weights: Mapping[str, float],
    asset_class: str,
    board_excluded: Sequence[str] = (),
) -> set[str]:
    """The dropped set each method returns on one row's votes."""
    pairs = sorted(votes.items())
    if asset_class == "pick" or method == "none":
        return set()
    if method in ("incumbent", "n3"):
        min_n = 3 if (method == "n3" and asset_class == "idp") else dc._HAMPEL_MIN_N
        if len(pairs) < min_n:
            return set()
        return set(dc._hampel_filter_per_player(pairs, min_n=min_n)[1])
    if method == "policy":
        if len(pairs) < 1 + op.MIN_OTHER_FAMILIES:
            return set()
        capped, _f = dc.cap_family_weights({k: float(weights.get(k, 1.0)) for k in votes})
        verdict = op.assess_row(
            pairs,
            curve=op.scope_curve(asset_class),
            family_of=family_of,
            weights=capped,
            board_excluded=board_excluded,
        )
        return set(verdict.dropped)
    raise ValueError(method)


def screen_for(
    rows: Mapping[str, Mapping[str, Any]], drop_family: str | None = None
) -> dict[str, list[str]]:
    """The policy's board screen on a record's rows, optionally without one family."""
    board = []
    for row in rows.values():
        if row.get("ac") == "pick":
            continue
        votes = {
            k: v
            for k, v in row["votes"].items()
            if drop_family is None or family_of(k) != drop_family
        }
        board.append(op.BoardRow(str(row.get("ac")), op.scope_curve(row.get("ac")), votes))
    return op.board_screen(board, family_of)["flagged"]


# ── daily thinning ──────────────────────────────────────────────────────


def daily(records: Sequence[Mapping[str, Any]]) -> dict[date, Mapping[str, Any]]:
    """The last complete record of each UTC day (``origins``)."""
    out: dict[date, tuple] = {}
    for rec in records:
        at = parse_time((rec.get("board") or {}).get("scrapeTimestamp"))
        if at is None:
            continue
        cur = out.get(at.date())
        if cur is None or at > cur[0]:
            out[at.date()] = (at, rec)
    return {d: v[1] for d, v in sorted(out.items())}


def _family_target(row: Mapping[str, Any] | None, fam: str) -> float | None:
    if not row:
        return None
    logs = [math.log(v) for k, v in row["votes"].items() if family_of(k) == fam and v > 0]
    return statistics.median(logs) if logs else None


# ── M1 ──────────────────────────────────────────────────────────────────


def m1_units(
    days: Mapping[date, Mapping[str, Any]],
    h: int,
    *,
    with_screen: bool = True,
    screens: dict | None = None,
) -> list[dict[str, Any]]:
    """Every (origin, row, held-out family) unit at horizon ``h`` with each method's loss."""
    units: list[dict[str, Any]] = []
    order = sorted(days)
    screens = screens if screens is not None else {}
    for d in order:
        rec = days[d]
        if h == 0:
            tgt = rec
        else:
            td = target_day(d, h, set(order))
            if td is None:
                continue
            tgt = days[td]
        rows = rec["rows"]
        trows = tgt["rows"]
        fams_on_board = sorted({family_of(k) for r in rows.values() for k in r["votes"]})
        for name, row in rows.items():
            ac = row.get("ac")
            if ac == "pick":
                continue
            fams = {family_of(k) for k in row["votes"]}
            for F in sorted(fams):
                if len(fams - {F}) < 3:
                    continue
                target = _family_target(trows.get(name), F)
                if target is None:
                    continue
                reduced = {k: v for k, v in row["votes"].items() if family_of(k) != F}
                w = {k: row["w"].get(k, 1.0) for k in reduced}
                skey = (id(rec), F)
                if with_screen and skey not in screens:
                    screens[skey] = screen_for(rows, F) if F in fams_on_board else {}
                excluded = (screens.get(skey) or {}).get(str(ac), []) if with_screen else []
                losses = {}
                dropped = {}
                for method in METHODS:
                    drop = decide(method, reduced, w, str(ac), excluded)
                    V = blend({k: v for k, v in reduced.items() if k not in drop}, w)
                    if V is None:
                        break
                    losses[method] = abs(math.log(V) - target)
                    dropped[method] = sorted(drop)
                else:
                    units.append(
                        {
                            "day": d.isoformat(),
                            "row": name,
                            "ac": ac,
                            "pos": row.get("pos"),
                            "family": F,
                            "loss": losses,
                            "dropped": dropped,
                        }
                    )
    return units


def _blocks(day_iso: str, first: date) -> int:
    return (date.fromisoformat(day_iso) - first).days // BLOCK_DAYS


def paired_stat(
    units: Sequence[Mapping[str, Any]],
    challenger: str,
    *,
    disputed_only: bool = True,
    seed: int = SEED,
) -> dict[str, Any]:
    """Mean of L_challenger − L_incumbent with a 7-day-block bootstrap interval."""
    sel = [
        u
        for u in units
        if not disputed_only or u["dropped"][challenger] != u["dropped"]["incumbent"]
    ]
    if not sel:
        return {"n": 0, "mean": None, "ci95": None, "days": 0, "blocks": 0}
    first = min(date.fromisoformat(u["day"]) for u in units)
    diffs = [(u["day"], u["loss"][challenger] - u["loss"]["incumbent"]) for u in sel]
    boot = block_bootstrap(
        diffs,
        lambda xs: statistics.fmean(x for _d, x in xs) if xs else None,
        block_of=lambda unit: _blocks(unit[0], first),
        resamples=RESAMPLES,
        seed=seed,
    )
    vals = [x for _d, x in diffs]
    return {
        "n": len(vals),
        "mean": round(boot["point"], 6),
        "ci95": [round(boot["lo"], 6), round(boot["hi"], 6)] if boot["lo"] is not None else None,
        "days": len({d for d, _x in diffs}),
        "blocks": boot["blocks"],
        "shareChallengerCloser": round(sum(1 for x in vals if x < 0) / len(vals), 4),
    }


# ── M3: what happened to the disputed observations ──────────────────────


def _lfo(votes: Mapping[str, float], exclude_family: str) -> float | None:
    by: dict[str, list[float]] = defaultdict(list)
    for k, v in votes.items():
        f = family_of(k)
        if f != exclude_family and v > 0:
            by[f].append(math.log(v))
    if len(by) < 2:
        return None
    return statistics.median(statistics.median(x) for x in by.values())


def m3_outcomes(days: Mapping[date, Mapping[str, Any]], h: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    order = sorted(days)
    groups: dict[str, list[dict]] = {"K": [], "X": []}
    for d in order:
        td = target_day(d, h, set(order))
        if td is None:
            continue
        rec, tgt = days[d], days[td]
        inc, pol = rec["variants"]["incumbent"], rec["variants"]["policy"]
        for name, row in rec["rows"].items():
            if row.get("ac") == "pick" or name not in inc or name not in pol:
                continue
            di, dp = set(inc[name][2]), set(pol[name][2])
            for side, obs in (("K", di - dp), ("X", dp - di)):
                for s in obs:
                    v = row["votes"].get(s)
                    if not v:
                        continue
                    f = family_of(s)
                    x = math.log(v)
                    c0 = _lfo(row["votes"], f)
                    trow = tgt["rows"].get(name)
                    c1 = _lfo(trow["votes"], f) if trow else None
                    if c0 is None or c1 is None or abs(x - c0) < 0.01:
                        continue
                    m = max(-1.0, min(1.0, (c1 - c0) / (x - c0)))
                    xv = (trow or {}).get("votes", {}).get(s)
                    if xv:
                        r = max(-1.0, min(1.0, (math.log(xv) - x) / (c0 - x)))
                        cls = "LED" if m >= 0.5 else ("ABANDONED" if r >= 0.5 else "UNRESOLVED")
                    else:
                        r = None
                        cls = "LED" if m >= 0.5 else "DELISTED"
                    groups[side].append(
                        {"day": d.isoformat(), "row": name, "source": s, "m": m, "r": r, "cls": cls}
                    )
    for side, obs in groups.items():
        rs = [o["r"] for o in obs if o["r"] is not None]
        out[side] = {
            "n": len(obs),
            "meanLeadShare": round(statistics.fmean(o["m"] for o in obs), 4) if obs else None,
            "meanRetreatShare": round(statistics.fmean(rs), 4) if rs else None,
            "classes": dict(Counter(o["cls"] for o in obs)),
            "bySource": dict(Counter(o["source"] for o in obs).most_common()),
        }
    return out


# ── M4: stability ───────────────────────────────────────────────────────


def m4_stability(days: Mapping[date, Mapping[str, Any]], methods=("incumbent", "policy", "n3")):
    order = sorted(days)
    pairs = []
    for a, b in zip(order, order[1:]):
        ra, rb = days[a], days[b]
        pair = {"day": a.isoformat()}
        for m in methods:
            va, vb = ra["variants"][m], rb["variants"][m]
            sums: dict[str, list[float]] = {"all": [], "idp": [], "offense": []}
            for name, row in ra["rows"].items():
                ac = row.get("ac")
                if ac == "pick" or name not in vb:
                    continue
                x, y = (va.get(name) or [None])[0], vb[name][0]
                if not x or not y or x <= 0 or y <= 0:
                    continue
                dl = abs(math.log(y) - math.log(x))
                sums["all"].append(dl)
                if ac in ("idp", "offense"):
                    sums[str(ac)].append(dl)
            pair[m] = {k: (statistics.fmean(v) if v else None) for k, v in sums.items()}
        pairs.append(pair)
    out: dict[str, Any] = {"pairs": len(pairs)}
    first = order[0] if order else None
    for seg in ("all", "idp", "offense"):
        seg_out = {}
        for m in methods:
            vals = [p[m][seg] for p in pairs if p[m][seg] is not None]
            seg_out[m] = round(statistics.fmean(vals), 6) if vals else None
        if first is not None:
            by_block: dict[int, list[tuple[float, float]]] = defaultdict(list)
            for p in pairs:
                a_, b_ = p["incumbent"][seg], p["policy"][seg]
                if a_ is not None and b_ is not None:
                    by_block[_blocks(p["day"], first)].append((b_, a_))
            seg_out["ratioPolicyOverIncumbent"] = _ratio_ci(by_block)
        out[seg] = seg_out
    return out


def _ratio_ci(by_block: Mapping[int, list[tuple[float, float]]]) -> dict[str, Any]:
    keys = sorted(by_block)
    if not keys:
        return {"ratio": None, "ci95": None}

    def ratio(ks):
        num = sum(b for k in ks for b, _a in by_block[k])
        den = sum(a for k in ks for _b, a in by_block[k])
        return num / den if den else None

    rng = random.Random(SEED)
    draws = []
    for _ in range(RESAMPLES):
        r = ratio([rng.choice(keys) for _k in keys])
        if r is not None:
            draws.append(r)
    draws.sort()
    lo = draws[int(0.025 * (len(draws) - 1))] if draws else None
    hi = draws[int(0.975 * (len(draws) - 1))] if draws else None
    point = ratio(keys)
    return {
        "ratio": round(point, 6) if point else None,
        "ci95": [round(lo, 6), round(hi, 6)] if draws else None,
    }


# ── M5 / M6 ─────────────────────────────────────────────────────────────


def census(rec: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m, rows in rec["variants"].items():
        c = Counter()
        for name, v in rows.items():
            ac = (rec["rows"].get(name) or {}).get("ac")
            for s in v[2]:
                c[f"{ac}|{s}"] += 1
        out[m] = {"drops": sum(c.values()), "bySource": dict(c.most_common())}
    reasons = Counter(r for d in rec.get("policyReasons", {}).values() for r in d.values())
    out["policyReasons"] = dict(reasons)
    stamp = rec.get("policyStamp") or {}
    out["boardScreenFlagged"] = ((stamp.get("boardScreen") or {}).get("flagged")) or {}
    out["rankingPasses"] = stamp.get("rankingPasses")
    return out


def _q(vals: Sequence[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def value_changes(rec: Mapping[str, Any], a: str, b: str) -> dict[str, Any]:
    """|Δ| (relative) of variant ``b`` vs ``a`` per asset class."""
    va, vb = rec["variants"][a], rec["variants"][b]
    out: dict[str, Any] = {}
    seg: dict[str, list[float]] = defaultdict(list)
    for name, x in va.items():
        y = vb.get(name)
        if not y or not x[0] or not y[0]:
            continue
        ac = (rec["rows"].get(name) or {}).get("ac") or "pick"
        rel = abs(y[0] - x[0]) / x[0]
        seg[str(ac)].append(rel)
        seg["all"].append(rel)
    for k, vals in sorted(seg.items()):
        moved = [v for v in vals if v > 0]
        out[k] = {
            "rows": len(vals),
            "moved": len(moved),
            "medianMoved": round(statistics.median(moved), 4) if moved else 0.0,
            "p90": round(_q(vals, 0.90) or 0.0, 4),
            "p99": round(_q(vals, 0.99) or 0.0, 4),
            "max": round(max(vals), 4) if vals else 0.0,
        }
    return out


def movers(rec: Mapping[str, Any], a: str, b: str, threshold: float = 0.30) -> list[dict]:
    """Every row moving more than ``threshold`` between two variants, with its cause."""
    va, vb = rec["variants"][a], rec["variants"][b]
    out = []
    for name, x in va.items():
        y = vb.get(name)
        if not y or not x[0] or not y[0]:
            continue
        rel = (y[0] - x[0]) / x[0]
        if abs(rel) <= threshold:
            continue
        row = rec["rows"].get(name) or {}
        da, db = set(x[2]), set(y[2])
        out.append(
            {
                "row": name,
                "assetClass": row.get("ac"),
                "position": row.get("pos"),
                a: x[0],
                b: y[0],
                "relative": round(rel, 4),
                "votes": {k: int(v) for k, v in sorted(row.get("votes", {}).items())},
                f"droppedOnlyBy_{a}": sorted(da - db),
                f"droppedOnlyBy_{b}": sorted(db - da),
            }
        )
    out.sort(key=lambda m: -abs(m["relative"]))
    return out


# ── M7: adversarial suite ───────────────────────────────────────────────


def _reprice(v: float, curve: tuple[float, float], factor: float) -> float:
    c, s = curve
    p = op.hill_inverse(v, c, s) * factor
    return 9999.0 / (1.0 + (p / c) ** s)


def adversarial(rec: Mapping[str, Any], seed: int = SEED) -> dict[str, Any]:
    """Function-level corruption cases on the record's real rows (PREREGISTRATION §4 M7)."""
    rng = random.Random(seed)
    rows = {
        n: r
        for n, r in sorted(rec["rows"].items())
        if r.get("ac") != "pick" and len({family_of(k) for k in r["votes"]}) >= 3
    }
    clean_screen = screen_for(rec["rows"])
    rank_of = {n: (rec["variants"]["incumbent"].get(n) or [None, None])[1] for n in rows}

    def fam_count_band(r):
        n = len({family_of(k) for k in r["votes"]})
        return "3" if n == 3 else ("4-5" if n <= 5 else ">=6")

    def run(name, row, source, bad_value):
        ac = str(row["ac"])
        excl = clean_screen.get(ac, [])
        corrupted = dict(row["votes"])
        corrupted[source] = bad_value
        res = {}
        for method in METHODS:
            dc_clean = decide(method, row["votes"], row["w"], ac, excl)
            dc_bad = decide(method, corrupted, row["w"], ac, excl)
            v_clean = blend({k: v for k, v in row["votes"].items() if k not in dc_clean}, row["w"])
            v_bad = blend({k: v for k, v in corrupted.items() if k not in dc_bad}, row["w"])
            if not v_clean or not v_bad:
                return None
            harm = abs(math.log(v_bad) - math.log(v_clean))
            res[method] = {"caught": source in dc_bad, "harm": harm}
        return res

    cases: dict[str, list[dict]] = defaultdict(list)
    by_source_rows: dict[str, list[str]] = defaultdict(list)
    for n, r in rows.items():
        for s in r["votes"]:
            by_source_rows[s].append(n)
    for name, row in rows.items():
        sources = sorted(row["votes"])
        band = fam_count_band(row)
        for case, factor in (("AD1a", 5.0), ("AD1b", 0.2), ("AD1c", 20.0), ("AD1d", 0.05)):
            s = rng.choice(sources)
            bad = min(9999.0, max(1.0, row["votes"][s] * factor))
            res = run(name, row, s, bad)
            if res:
                cases[case].append({"row": name, "source": s, "band": band, **res})
        s = rng.choice(sources)
        rk = rank_of.get(name)
        pool = [
            o
            for o in by_source_rows[s]
            if o != name
            and rank_of.get(o) is not None
            and rk is not None
            and abs(rank_of[o] - rk) >= 100
        ]
        if pool:
            other = rng.choice(sorted(pool))
            res = run(name, row, s, rows[other]["votes"][s])
            if res:
                cases["AD2"].append({"row": name, "source": s, "band": band, "as": other, **res})
        if rk is not None and 150 <= rk <= 400:
            s = rng.choice(sources)
            res = run(name, row, s, 9000.0)
            if res:
                cases["AD4"].append({"row": name, "source": s, "band": band, **res})
    summary: dict[str, Any] = {}
    gate = {"AD1a": 0.90, "AD1b": 0.90, "AD1c": 0.95, "AD1d": 0.95, "AD2": 0.90, "AD4": 0.95}
    for case, items in sorted(cases.items()):
        material = [c for c in items if c["none"]["harm"] >= MATERIAL]
        entry: dict[str, Any] = {"cases": len(items), "material": len(material)}
        for method in ("incumbent", "n3", "policy"):

            def passed(c, m=method):
                return c[m]["caught"] or c[m]["harm"] < MATERIAL

            entry[method] = {
                "passRate": round(sum(passed(c) for c in material) / len(material), 4)
                if material
                else None,
                "byBand": {
                    b: round(
                        sum(passed(c) for c in material if c["band"] == b)
                        / max(1, sum(1 for c in material if c["band"] == b)),
                        4,
                    )
                    for b in ("3", "4-5", ">=6")
                    if any(c["band"] == b for c in material)
                },
                "caughtShareAll": round(sum(c[method]["caught"] for c in items) / len(items), 4)
                if items
                else None,
            }
        entry["gate"] = gate.get(case)
        entry["policyPasses"] = (
            entry["policy"]["passRate"] is not None and entry["policy"]["passRate"] >= gate[case]
        )
        summary[case] = entry
    # AD3: whole boards on the wrong scale.
    ad3 = []
    for source in ("dynastyNerdsSfTep", "flockFantasySf", "fantasyCalc", "fantasyProsIdp"):
        ac = "idp" if source == "fantasyProsIdp" else "offense"
        covered = [n for n, r in rec["rows"].items() if r.get("ac") == ac and source in r["votes"]]
        for kind in ("ranks_x2", "ranks_x5", "values_x0.01", "reversed"):
            mutated = {n: dict(r, votes=dict(r["votes"])) for n, r in rec["rows"].items()}
            if kind == "reversed":
                ordered = sorted(covered, key=lambda n: -rec["rows"][n]["votes"][source])
                vals = [rec["rows"][n]["votes"][source] for n in ordered]
                for n, v in zip(ordered, reversed(vals)):
                    mutated[n]["votes"][source] = v
            else:
                for n in covered:
                    v = rec["rows"][n]["votes"][source]
                    curve = op.scope_curve(ac)
                    if kind == "ranks_x2":
                        mutated[n]["votes"][source] = _reprice(v, curve, 2.0)
                    elif kind == "ranks_x5":
                        mutated[n]["votes"][source] = _reprice(v, curve, 5.0)
                    else:
                        mutated[n]["votes"][source] = max(1.0, v * 0.01)
            flagged = screen_for(mutated)
            ad3.append(
                {
                    "source": source,
                    "kind": kind,
                    "rows": len(covered),
                    "flagged": source in flagged.get(ac, []),
                    "flaggedAll": flagged,
                }
            )
    summary["AD3"] = {
        "boards": len(ad3),
        "flagged": sum(1 for a in ad3 if a["flagged"]),
        "policyPasses": all(a["flagged"] for a in ad3),
        "cases": ad3,
        "cleanBoardFlagged": clean_screen,
    }
    summary["gatePasses"] = all(v.get("policyPasses") for v in summary.values())
    return summary


# ── M2: G1 on published values (reported, not decisive) ─────────────────


def m2_g1(days: Mapping[date, Mapping[str, Any]], h: int, challenger: str = "policy") -> dict:
    """The joint framework's G1 on full-pipeline published values (PREREGISTRATION §4 M2).

    Rows whose ``rankDerivedValue`` differs between the challenger and incumbent
    builds; T = equal-family median on the target board over the families other
    than the disputed observations' (≥ 2). Biased toward the incumbent by
    construction when the challenger mostly rescues votes (stated in advance).
    """
    order = sorted(days)
    units = []
    for d in order:
        td = target_day(d, h, set(order))
        if td is None:
            continue
        rec, tgt = days[d], days[td]
        inc, ch = rec["variants"]["incumbent"], rec["variants"][challenger]
        for name, row in rec["rows"].items():
            if row.get("ac") == "pick" or name not in inc or name not in ch:
                continue
            vi, vc = inc[name][0], ch[name][0]
            if not vi or not vc or vi == vc:
                continue
            disputed = set(inc[name][2]) ^ set(ch[name][2])
            fams = {family_of(s) for s in disputed}
            trow = tgt["rows"].get(name)
            if not trow:
                continue
            by: dict[str, list[float]] = defaultdict(list)
            for k, v in trow["votes"].items():
                if family_of(k) not in fams and v > 0:
                    by[family_of(k)].append(math.log(v))
            if len(by) < 2:
                continue
            T = statistics.median(statistics.median(x) for x in by.values())
            units.append((d.isoformat(), abs(math.log(vc) - T) - abs(math.log(vi) - T)))
    if not units:
        return {"n": 0, "mean": None, "ci95": None}
    first = min(date.fromisoformat(u[0]) for u in units)
    boot = block_bootstrap(
        units,
        lambda xs: statistics.fmean(x for _d, x in xs) if xs else None,
        block_of=lambda unit: _blocks(unit[0], first),
        resamples=RESAMPLES,
        seed=SEED,
    )
    return {
        "n": len(units),
        "mean": round(boot["point"], 6),
        "ci95": [round(boot["lo"], 6), round(boot["hi"], 6)] if boot["lo"] is not None else None,
        "days": len({d for d, _x in units}),
        "blocks": boot["blocks"],
    }
