"""Records and evaluation for the two IDP evidence challengers (2026-10-18).

* ``idp-hampel-n3-v1`` (flag ``idp_hampel_n3_challenger``) --
  ``docs/valuation/evidence/idp-outlier-n3-2026-10-18/PREREGISTRATION.md``.
* ``idp-deep-tail-native-v1`` (flag ``idp_deep_tail_native_challenger``) --
  ``docs/valuation/evidence/idp-deep-tail-native-2026-10-18/PREREGISTRATION.md``.

Both preregistrations are frozen. This module only reads what four builds of one
archived board stamped (incumbent; the n = 3 challenger; the incumbent with the DLF
IDP vote hold off, read for DLF's own vote; the deep-tail challenger) and applies
the registered metrics. Nothing here changes a vote, a weight or a value. Missing is
never zero: a row or vote with no target is counted as not evaluable, never imputed.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from src.api import data_contract as dc
from src.canonical import deep_tail_native as dtn
from src.robust_filter_shadow.outcomes import block_bootstrap, parse_time, target_day
from src.robust_filter_shadow.record import voting_observations

N3_FLAG = "idp_hampel_n3_challenger"
N3_VERSION = "idp-hampel-n3-v1"
N3_SEED = 2029
DTN_FLAG = "idp_deep_tail_native_challenger"
DTN_SEED = 2031
DLF_HOLD_FLAG = "dlf_offense_only_vote"
OTHER_FILTER_CHALLENGERS = (
    "joint_outlier_sparse_challenger",
    "joint_sparse_limited_evidence",
    "rank_space_hampel_challenger",
    "rank_space_hampel_per_vote_challenger",
)
PRIMARY_H = 7
SECONDARY_H = (3, 14, 21)
BLOCK_DAYS = 7
RANKISH = frozenset({"canonicalConsensusRank", "canonicalPercentile", "canonicalTierId"})
FAMILIES = ("DL", "LB", "DB")
DLF_BOARDS = ("dlfIdp", "dlfRookieIdp")
IDPTC = "idpTradeCalc"


def _pins(overrides: Iterable[tuple[str, bool]]) -> list[tuple[str, bool]]:
    base = {
        DLF_HOLD_FLAG: True,
        "source_freshness_weighting": True,
        "source_family_cap": True,
        N3_FLAG: False,
        DTN_FLAG: False,
        **{f: False for f in OTHER_FILTER_CHALLENGERS},
    }
    base.update(dict(overrides))
    return sorted(base.items())


#: The four builds per board.  1 and 3 are shared by both experiments.
BUILDS: dict[str, list[tuple[str, bool]]] = {
    "incumbent": _pins([]),
    "n3": _pins([(N3_FLAG, True)]),
    "holdOff": _pins([(DLF_HOLD_FLAG, False)]),
    "deepTail": _pins([(DTN_FLAG, True)]),
}


# ── per-board extraction ────────────────────────────────────────────────


def _rows(contract: Mapping[str, Any]) -> dict[str, dict]:
    return {
        str(r.get("displayName")): r
        for r in contract.get("playersArray") or []
        if isinstance(r, dict) and r.get("displayName")
    }


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(float(x)) else None


def _strip(row: Mapping[str, Any]) -> str:
    return json.dumps(
        {k: v for k, v in row.items() if k not in RANKISH}, sort_keys=True, default=str
    )


def _is_tether_pick(*rows: Mapping[str, Any] | None) -> bool:
    for row in rows:
        if not row or row.get("assetClass") != "pick":
            continue
        prov = row.get("pickValueProvenance") or {}
        if isinstance(prov, Mapping) and prov.get("basis") == "rookie_pool_tether":
            return True
        if row.get("pickRookieAnchor") is not None:
            return True
    return False


def scope_guard(
    inc: Mapping[str, Any],
    ch: Mapping[str, Any],
    is_target: Callable[[Mapping[str, Any], Mapping[str, Any]], bool],
) -> dict[str, Any]:
    """Rows outside the challenger's scope must match the incumbent.

    Board-wide ordinals (rank / percentile / tier) are excluded from the
    comparison; the two documented post-blend couplings (current-year slot picks
    tethered to the merged rookie pool; the two-way player boost) are counted, not
    hidden. Anything else is a violation.
    """
    a, b = _rows(inc), _rows(ch)
    out: dict[str, Any] = {
        "rowsCompared": 0,
        "identical": 0,
        "ordinalOnly": 0,
        "rankCapCoupling": 0,
        "tetherPick": 0,
        "twoWay": 0,
        "violations": [],
    }
    for name, row in a.items():
        other = b.get(name)
        if other is None:
            out["violations"].append({"row": name, "why": "missing_in_challenger"})
            continue
        if is_target(row, other):
            continue
        out["rowsCompared"] += 1
        if json.dumps(row, sort_keys=True, default=str) == json.dumps(
            other, sort_keys=True, default=str
        ):
            out["identical"] += 1
        elif _strip(row) == _strip(other):
            out["ordinalOnly"] += 1
        elif row.get("droppedSources") != other.get("droppedSources") or (
            row.get("sourceRankMeta") != other.get("sourceRankMeta")
            and row.get("assetClass") != "pick"
        ):
            out["violations"].append({"row": name, "why": "votes_or_drops_differ"})
        elif row.get("rankDerivedValue") == other.get("rankDerivedValue") and row.get(
            "values"
        ) == other.get("values"):
            # Same votes, drops and value; only fields derived from the row's
            # board RANK moved (crossing the published-rank cap, idpRank,
            # blendedSourceRank).  A board-wide ordinal coupling.
            out["rankCapCoupling"] += 1
        elif _is_tether_pick(row, other):
            out["tetherPick"] += 1
        elif name in dc._TWO_WAY_PLAYERS:
            out["twoWay"] += 1
        else:
            fields = sorted(
                k for k in set(row) | set(other) if k not in RANKISH and row.get(k) != other.get(k)
            )
            out["violations"].append({"row": name, "why": "value_differs", "fields": fields})
    for name in b:
        if name not in a:
            out["violations"].append({"row": name, "why": "extra_in_challenger"})
    out["violationCount"] = len(out["violations"])
    out["violations"] = out["violations"][:50]
    return out


def _row_core(row: Mapping[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"v": None}
    return {
        "v": _num(row.get("rankDerivedValue")),
        "rank": row.get("canonicalConsensusRank"),
        "drop": sorted(row.get("droppedSources") or []),
        "conf": row.get("confidenceBucket"),
        "n": len(voting_observations(row)),
    }


def n3_record(inc: dict, n3: dict, hold_off: dict) -> dict[str, Any]:
    """The ``idp-hampel-n3-v1`` per-board record."""
    a, b, c = _rows(inc), _rows(n3), _rows(hold_off)
    rows: dict[str, Any] = {}
    for name, row in a.items():
        if row.get("assetClass") != "idp":
            continue
        dlf: dict[str, Any] = {}
        meta3 = (c.get(name) or {}).get("sourceRankMeta") or {}
        for key in DLF_BOARDS:
            m = meta3.get(key)
            if isinstance(m, Mapping) and (_num(m.get("valueContribution")) or 0) > 0:
                dlf[key] = {
                    "v": _num(m.get("valueContribution")),
                    "rawRank": m.get("rawRank"),
                    "excluded": m.get("excludedReason"),
                }
        rows[name] = {
            "pos": row.get("position"),
            "rookie": bool(row.get("rookie")),
            "votes": voting_observations(row),
            "inc": _row_core(row),
            "ch": _row_core(b.get(name)),
            "holdOff": {**_row_core(c.get(name)), "votes": voting_observations(c.get(name) or {})},
            "dlf": dlf,
        }

    def target(row: Mapping[str, Any], _other: Mapping[str, Any]) -> bool:
        return row.get("assetClass") == "idp" and len(voting_observations(row)) == 3

    # Hold-off board census (needed only for the PASS board-impact validation).
    hold_rows = [r for r in c.values() if r.get("assetClass") == "idp"]
    return {
        "rows": rows,
        "guard": scope_guard(inc, n3, target),
        "holdOffOtherRows": {
            name: _row_core(r)
            for name, r in c.items()
            if r.get("assetClass") != "idp"
            and _row_core(a.get(name)).get("v") != _num(r.get("rankDerivedValue"))
        },
        "holdOffIdpRows": len(hold_rows),
    }


def deep_tail_record(inc: dict, deep: dict, hold_off: dict, ladder_points: list) -> dict[str, Any]:
    """The ``idp-deep-tail-native-v1`` per-board record."""
    a, d, c = _rows(inc), _rows(deep), _rows(hold_off)
    rows: dict[str, Any] = {}
    for name, row in a.items():
        if row.get("assetClass") != "idp":
            continue
        other = d.get(name) or {}
        ma, md = row.get("sourceRankMeta") or {}, other.get("sourceRankMeta") or {}
        votes: dict[str, Any] = {}
        for key, m in ma.items():
            if not isinstance(m, Mapping):
                continue
            mo = md.get(key) or {}
            votes[key] = {
                "r": _num(m.get("effectiveRank")),
                "pool": m.get("rankCoordinatePool"),
                "path": m.get("valueContributionPath"),
                "v": _num(m.get("valueContribution")),
                "vch": _num(mo.get("valueContribution")),
                "ex": m.get("excludedReason"),
                "exch": mo.get("excludedReason"),
                "w": _num(m.get("preFamilyWeight", m.get("appliedWeight"))),
                "wch": _num(mo.get("preFamilyWeight", mo.get("appliedWeight"))),
                "dtn": mo.get("deepTailNative"),
            }
        meta3 = (c.get(name) or {}).get("sourceRankMeta") or {}
        dlf_rank = (meta3.get("dlfIdp") or {}).get("rawRank")
        rows[name] = {
            "pos": row.get("position"),
            "rookie": bool(row.get("rookie")),
            "inc": {
                **_row_core(row),
                "eff": row.get("effectiveSourceCount"),
                "ind": row.get("independentSourceCount"),
            },
            "ch": {
                **_row_core(other),
                "eff": other.get("effectiveSourceCount"),
                "ind": other.get("independentSourceCount"),
            },
            "votes": votes,
            "dlfRank": dlf_rank,
        }

    def target(row: Mapping[str, Any], other: Mapping[str, Any]) -> bool:
        return row.get("assetClass") == "idp"

    all_rows = {
        name: [
            _num(r.get("rankDerivedValue")),
            _num((d.get(name) or {}).get("rankDerivedValue")),
            r.get("canonicalConsensusRank"),
            (d.get(name) or {}).get("canonicalConsensusRank"),
            r.get("assetClass"),
        ]
        for name, r in a.items()
    }
    return {
        "rows": rows,
        "allRows": all_rows,
        "ladderPoints": [[round(float(r), 4), round(float(v), 4)] for r, v in ladder_points],
        "guard": scope_guard(inc, deep, target),
    }


# ── evaluation helpers ──────────────────────────────────────────────────


def board_day(rec: Mapping[str, Any]) -> date | None:
    at = parse_time((rec.get("board") or {}).get("scrapeTimestamp"))
    return at.date() if at else None


def daily(records: Sequence[Mapping[str, Any]]) -> dict[date, Mapping[str, Any]]:
    """The last record of each UTC day (the inherited origin/target thinning)."""
    out: dict[date, Mapping[str, Any]] = {}
    for rec in sorted(
        records, key=lambda r: parse_time((r.get("board") or {}).get("scrapeTimestamp"))
    ):
        day = board_day(rec)
        if day is not None:
            out[day] = rec
    return out


def _ci(units: list, stat: Callable[[Sequence], float | None], seed: int) -> dict[str, Any]:
    key = getattr(stat, "mean_key", None)
    if key is not None:
        res = _mean_block_bootstrap(units, key, seed)
    else:
        res = block_bootstrap(units, stat, block_of=lambda u: u["block"], seed=seed)
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in res.items()}


def _mean_block_bootstrap(units: Sequence[Mapping[str, Any]], key: str, seed: int) -> dict:
    """``outcomes.block_bootstrap`` for a plain mean, from per-block sums.

    The same blocks, the same ``random.Random(seed)`` draw sequence and the same
    percentile rule, so the interval is the inherited one; summing per block
    first only avoids re-walking every unit 4,000 times.
    """
    import random  # noqa: PLC0415

    from src.robust_filter_shadow.outcomes import BOOTSTRAP_RESAMPLES, _percentile  # noqa: PLC0415

    sums: dict[int, float] = defaultdict(float)
    counts: dict[int, int] = defaultdict(int)
    for u in units:
        v = u.get(key)
        if v is None:
            continue
        sums[u["block"]] += v
        counts[u["block"]] += 1
    blocks = sorted({u["block"] for u in units})
    total = sum(counts.values())
    point = (sum(sums.values()) / total) if total else None
    if point is None or not blocks:
        return {"point": point, "lo": None, "hi": None, "blocks": len(blocks), "used": 0}
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        s = n = 0.0
        for _b in blocks:
            b = rng.choice(blocks)
            s += sums.get(b, 0.0)
            n += counts.get(b, 0)
        if n:
            draws.append(s / n)
    draws.sort()
    return {
        "point": point,
        "lo": _percentile(draws, 0.025) if draws else None,
        "hi": _percentile(draws, 0.975) if draws else None,
        "blocks": len(blocks),
        "used": len(draws),
    }


def _mean_key(key: str) -> Callable[[Sequence[Mapping[str, Any]]], float | None]:
    def stat(units: Sequence[Mapping[str, Any]]) -> float | None:
        vals = [u[key] for u in units if u.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    stat.mean_key = key  # type: ignore[attr-defined]
    return stat


def _dlf_target(rec_row: Mapping[str, Any] | None) -> float | None:
    dlf = (rec_row or {}).get("dlf") or {}
    for key in DLF_BOARDS:  # dlfIdp first; dlfRookieIdp only when it alone lists him
        v = (dlf.get(key) or {}).get("v")
        if v and v > 0:
            return float(v)
    return None


# ── idp-hampel-n3-v1 evaluation (PREREGISTRATION §3-§5) ─────────────────


def n3_units(
    days: Mapping[date, Mapping[str, Any]],
    horizon: int,
    *,
    persistence: bool = False,
    row_filter: Callable[[str, Mapping[str, Any]], bool] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """One unit per evaluable disputed (row, origin) at ``horizon``."""
    ordered = sorted(days)
    first = ordered[0] if ordered else None
    units: list[dict] = []
    census = Counter()
    for origin in ordered:
        tday = origin if persistence else target_day(origin, horizon, ordered)
        if tday is None:
            census["noTargetBoard"] += 1
            continue
        o_rows = days[origin]["n3"]["rows"]
        t_rows = days[tday]["n3"]["rows"]
        for name, row in o_rows.items():
            vi, vc = row["inc"]["v"], row["ch"]["v"]
            if vi is None or vc is None or vi == vc:
                continue
            census["disputed"] += 1
            if row_filter and not row_filter(name, row):
                census["filteredOut"] += 1
                continue
            t1 = _dlf_target(t_rows.get(name))
            if t1 is None:
                census["notEvaluable"] += 1
                continue
            census["evaluable"] += 1
            dropped = sorted(set(row["ch"]["drop"]) - set(row["inc"]["drop"]))
            units.append(
                {
                    "day": origin.isoformat(),
                    "block": (origin - first).days // BLOCK_DAYS,
                    "row": name,
                    "pos": row.get("pos"),
                    "rookie": row.get("rookie"),
                    "dropped": dropped,
                    "vInc": vi,
                    "vCh": vc,
                    "t1": t1,
                    "d": abs(math.log(vc) - math.log(t1)) - abs(math.log(vi) - math.log(t1)),
                }
            )
    return units, dict(census)


def n3_horizon(days, horizon, seed=N3_SEED, **kw) -> dict[str, Any]:
    units, census = n3_units(days, horizon, **kw)
    ci = _ci(units, _mean_key("d"), seed)
    return {
        "horizon": horizon,
        "P1": ci,
        "n": len(units),
        "originDays": len({u["day"] for u in units}),
        "blocks": len({u["block"] for u in units}),
        "census": census,
    }


def n3_verdict(primary: Mapping[str, Any], secondary: Sequence[Mapping[str, Any]]) -> dict:
    p = primary["P1"]
    sample_ok = primary["n"] >= 30 and primary["originDays"] >= 10 and primary["blocks"] >= 4
    if not sample_ok:
        verdict = "INSUFFICIENT"
    elif (
        p["hi"] is not None
        and p["hi"] < 0
        and sum(1 for s in secondary if s["P1"]["point"] is not None and s["P1"]["point"] < 0) >= 2
    ):
        verdict = "PROMOTION-ELIGIBLE"
    elif p["lo"] is not None and p["lo"] > 0:
        verdict = "NOT BETTER"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "verdict": verdict,
        "minimumSample": {
            "evaluable": [primary["n"], 30],
            "originDays": [primary["originDays"], 10],
            "blocks": [primary["blocks"], 4],
            "met": sample_ok,
        },
        "secondaryNegative": sum(
            1 for s in secondary if s["P1"]["point"] is not None and s["P1"]["point"] < 0
        ),
    }


# ── idp-deep-tail-native-v1 evaluation (PREREGISTRATION §3-§5) ──────────


def ladder_without(points: Sequence[Sequence[float]], own_rank: float | None) -> dtn.NativeLadder:
    """The origin ladder with one player's own point removed (leave-player-out)."""
    if own_rank is None:
        return dtn.build_native_ladder((r, v) for r, v in points)
    return dtn.build_native_ladder((r, v) for r, v in points if r != own_rank)


#: Leave-player-out ladders, keyed by (board payload sha256, the player's own
#: IDP Trade Calculator rank); a pure function of the record, so caching it
#: changes no result.
_LADDER_CACHE: dict[tuple[Any, float | None], dtn.NativeLadder] = {}


def repriceable(vote: Mapping[str, Any], source: str) -> bool:
    """§1 rules 2-4 for a vote, from build-1 stamps (rule 5 is the ladder's)."""
    r = vote.get("r")
    return (
        source != IDPTC
        and source not in dc._VALUE_BASED_SOURCES
        and vote.get("path") == "rank_hill"
        and vote.get("pool") == "shared_market"
        and r is not None
        and dtn.in_deep_band(r)
    )


def _idptc_vote(row: Mapping[str, Any] | None) -> tuple[float | None, float | None]:
    v = ((row or {}).get("votes") or {}).get(IDPTC) or {}
    if v.get("path") != "value_direct":
        return None, None
    return v.get("r"), v.get("v")


def c1_units(
    days: Mapping[date, Mapping[str, Any]],
    horizon: int,
    *,
    persistence: bool = False,
    in_sample: bool = False,
    out_of_sample_player: bool = False,
    row_filter: Callable[[str, Mapping[str, Any]], bool] | None = None,
    source_filter: str | None = None,
    band: tuple[float, float] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    ordered = sorted(days)
    first = ordered[0] if ordered else None
    units: list[dict] = []
    census = Counter()
    for origin in ordered:
        tday = origin if persistence else target_day(origin, horizon, ordered)
        if tday is None:
            census["noTargetBoard"] += 1
            continue
        orec, trec = days[origin]["deepTail"], days[tday]["deepTail"]
        points = orec["ladderPoints"]
        full = dtn.build_native_ladder((r, v) for r, v in points)
        for name, row in orec["rows"].items():
            if row_filter and not row_filter(name, row):
                continue
            own_r, _own_v = _idptc_vote(row)
            if out_of_sample_player and own_r is not None:
                continue
            if in_sample:
                ladder = full
            else:
                ck = ((orec.get("board") or {}).get("payloadSha256"), own_r)
                ladder = _LADDER_CACHE.get(ck)
                if ladder is None:
                    ladder = _LADDER_CACHE[ck] = ladder_without(points, own_r)
            for source, vote in row["votes"].items():
                if vote.get("ex") or not repriceable(vote, source):
                    continue
                if source_filter and source != source_filter:
                    continue
                r = vote["r"]
                if band and not (band[0] < r <= band[1]):
                    continue
                p_ch = dtn.native_price(ladder, r)
                if p_ch is None or not vote.get("v"):
                    census["notCoveredByLadder"] += 1
                    continue
                census["votes"] += 1
                _tr, t = _idptc_vote(trec["rows"].get(name))
                if not t:
                    census["notEvaluable"] += 1
                    continue
                census["evaluable"] += 1
                p_inc = float(vote["v"])
                units.append(
                    {
                        "day": origin.isoformat(),
                        "block": (origin - first).days // BLOCK_DAYS,
                        "row": name,
                        "pos": row.get("pos"),
                        "source": source,
                        "r": r,
                        "pInc": p_inc,
                        "pCh": p_ch,
                        "t": t,
                        "d": abs(math.log(p_ch / t)) - abs(math.log(p_inc / t)),
                        "biasInc": math.log(p_inc / t),
                        "biasCh": math.log(p_ch / t),
                    }
                )
    return units, dict(census)


def c1_horizon(days, horizon, seed=DTN_SEED, **kw) -> dict[str, Any]:
    units, census = c1_units(days, horizon, **kw)
    out = {
        "horizon": horizon,
        "C1": _ci(units, _mean_key("d"), seed),
        "n": len(units),
        "originDays": len({u["day"] for u in units}),
        "blocks": len({u["block"] for u in units}),
        "census": census,
        "medianBiasInc": _r(statistics.median([u["biasInc"] for u in units])) if units else None,
        "medianBiasCh": _r(statistics.median([u["biasCh"] for u in units])) if units else None,
    }
    return out


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def _spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def ranks(vals: Sequence[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def r1_units(
    days: Mapping[date, Mapping[str, Any]],
    horizon: int,
    *,
    row_filter: Callable[[str, Mapping[str, Any]], bool] | None = None,
    disputed_only: bool = False,
) -> list[dict]:
    ordered = sorted(days)
    first = ordered[0] if ordered else None
    units = []
    for origin in ordered:
        tday = target_day(origin, horizon, ordered)
        if tday is None:
            continue
        orows = days[origin]["deepTail"]["rows"]
        trows = days[tday]["deepTail"]["rows"]
        vi, vc, dr = [], [], []
        for name, row in orows.items():
            if row_filter and not row_filter(name, row):
                continue
            a, b = row["inc"]["v"], row["ch"]["v"]
            if not a or not b or a <= 0 or b <= 0:
                continue
            if disputed_only and a == b:
                continue
            rank = (trows.get(name) or {}).get("dlfRank")
            if not isinstance(rank, (int, float)):
                continue
            vi.append(a)
            vc.append(b)
            dr.append(-float(rank))
        if len(dr) < 3:
            continue
        ri, rc = _spearman(vi, dr), _spearman(vc, dr)
        if ri is None or rc is None:
            continue
        units.append(
            {
                "day": origin.isoformat(),
                "block": (origin - first).days // BLOCK_DAYS,
                "rows": len(dr),
                "rhoInc": ri,
                "rhoCh": rc,
                "d": rc - ri,
            }
        )
    return units


def h1_units(
    days: Mapping[date, Mapping[str, Any]],
    *,
    row_filter: Callable[[str, Mapping[str, Any]], bool] | None = None,
) -> list[dict]:
    ordered = sorted(days)
    first = ordered[0] if ordered else None
    units = []
    for d0, d1 in zip(ordered, ordered[1:]):
        r0, r1 = days[d0]["deepTail"]["rows"], days[d1]["deepTail"]["rows"]
        mi, mc = [], []
        for name, row in r0.items():
            other = r1.get(name)
            if not other or (row_filter and not row_filter(name, row)):
                continue
            a0, c0, a1, c1 = row["inc"]["v"], row["ch"]["v"], other["inc"]["v"], other["ch"]["v"]
            if not all(x and x > 0 for x in (a0, c0, a1, c1)):
                continue
            mi.append(abs(math.log(a1 / a0)))
            mc.append(abs(math.log(c1 / c0)))
        if not mi:
            continue
        units.append(
            {
                "day": d1.isoformat(),
                "block": (d1 - first).days // BLOCK_DAYS,
                "inc": sum(mi) / len(mi),
                "ch": sum(mc) / len(mc),
                "rows": len(mi),
            }
        )
    return units


def h1_ratio(units: Sequence[Mapping[str, Any]]) -> float | None:
    inc = [u["inc"] for u in units]
    ch = [u["ch"] for u in units]
    if not inc or sum(inc) <= 0:
        return None
    return (sum(ch) / len(ch)) / (sum(inc) / len(inc))


#: config/model_registry/hill_autopilot_policy.json -> boardImpact (read at run time).
def board_rails(all_rows: Mapping[str, Sequence[Any]], limits: Mapping[str, Any]) -> dict:
    priced_inc = {n for n, r in all_rows.items() if r[0] and r[0] > 0}
    unpriced = sum(1 for n in priced_inc if not (all_rows[n][1] and all_rows[n][1] > 0))
    moves = sorted(
        abs(r[1] / r[0] - 1.0) for n, r in all_rows.items() if r[0] and r[1] and r[0] > 0
    )
    shifts = sorted(
        abs(int(r[3]) - int(r[2]))
        for r in all_rows.values()
        if isinstance(r[2], int) and isinstance(r[3], int)
    )

    def top(idx: int, n: int) -> set[str]:
        ranked = [(r[idx], name) for name, r in all_rows.items() if isinstance(r[idx], int)]
        return {name for _rk, name in sorted(ranked)[:n]}

    def q(vals: list, p: float) -> float:
        if not vals:
            return 0.0
        return vals[min(len(vals) - 1, int(round(p * (len(vals) - 1))))]

    m = {
        "unpricedFraction": unpriced / len(priced_inc) if priced_inc else 0.0,
        "medianAbsPctValueChange": q(moves, 0.5),
        "p90AbsPctValueChange": q(moves, 0.9),
        "maxAbsPctValueChange": moves[-1] if moves else 0.0,
        "top25Overlap": len(top(2, 25) & top(3, 25)),
        "top100Overlap": len(top(2, 100) & top(3, 100)),
        "medianAbsRankShift": q(shifts, 0.5),
        "p90AbsRankShift": q(shifts, 0.9),
    }
    ok = (
        m["unpricedFraction"] <= limits["maxUnpricedFraction"]
        and m["medianAbsPctValueChange"] <= limits["maxMedianAbsPctValueChange"]
        and m["p90AbsPctValueChange"] <= limits["maxP90AbsPctValueChange"]
        and m["maxAbsPctValueChange"] <= limits["maxSingleAbsPctValueChange"]
        and m["top25Overlap"] >= limits["minTop25Overlap"]
        and m["top100Overlap"] >= limits["minTop100Overlap"]
        and m["medianAbsRankShift"] <= limits["maxMedianAbsRankShift"]
        and m["p90AbsRankShift"] <= limits["maxP90AbsRankShift"]
    )
    return {"metrics": {k: _r(v, 5) for k, v in m.items()}, "pass": ok}


def group_by(units: Iterable[Mapping[str, Any]], key: str) -> dict[Any, list]:
    out: dict[Any, list] = defaultdict(list)
    for u in units:
        out[u.get(key)].append(u)
    return out
