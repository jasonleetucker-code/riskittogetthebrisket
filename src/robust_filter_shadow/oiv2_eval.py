"""Outlier-integrity-v2 replay evaluation (prereg §6.1, §8, §10, §11).

Reads the per-board records written by ``scripts/oiv2_replay.py run`` and applies
the registered metrics. Where a V1 definition is reused (M1, M3, M4, value
changes, movers) the V1 evaluator (``outlier_policy_eval``) is called on an
adapted record: ``incumbent`` = board A, ``policy`` = V2 (board D), so every
statistic is computed by the same code V1 was judged by. Nothing here changes a
vote or a value; missing is never zero (a row or target that is absent is not
evaluable, never imputed).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from src.robust_filter_shadow import outlier_policy_eval as E
from src.robust_filter_shadow.outcomes import target_day

ROOKIE_SOURCES = ("dlfRookieSf", "flockFantasySfRookies", "dlfRookieIdp")
H2_BOARDS = (
    "dynasty_export_20261007_092552.zip",
    "dynasty_export_20261008_141213.zip",
    "dynasty_export_20261016_134010.zip",
)
H3_BOARDS = (
    "dynasty_export_20260803_235610.zip",
    "dynasty_export_20261008_141213.zip",
    "dynasty_export_20261016_134010.zip",
)
H4_BOARDS = ("dynasty_export_20260803_235610.zip", "dynasty_export_20260806_150742.zip")
H3_ROW = "Justin Jefferson"
FOCUS = (
    "Trevin Wallace",
    "Myles Garrett",
    "Aidan Hutchinson",
    "CJ Allen",
    "T.J. Watt",
    "Josiah Trotter",
    "Will Anderson",
    "Danielle Hunter",
    "Jared Verse",
    "Theo Johnson",
    "Travis Hunter",
)
#: An exclusion whose record shows a deterministic contradiction (prereg §10:
#: A1/A2/A3, B0, B1 or B2 proof). Everything else counts as a false exclusion
#: until the independent reviewer confirms it from the archive.
DETERMINISTIC_PREFIXES = (
    "identity_contradicted:sleeper_id",
    "identity_contradicted:vendor_id",
    "identity_contradicted:join_inconsistent",
    "identity_contradicted:position_group",
    "format_",
    "normalization_untranslated",
    "normalization_dependency_unavailable",
    "provenance_",
    "feed_",
)


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and math.isfinite(float(x)) else None


def inc_panel(row: Mapping[str, Any]) -> dict[str, float]:
    return {
        k: v[0]
        for k, v in (row.get("obs") or {}).items()
        if v[0] is not None and v[0] > 0 and v[2] in ("voting", "filter_dropped")
    }


def inc_weights(row: Mapping[str, Any]) -> dict[str, float]:
    return {k: v[1] for k, v in (row.get("obs") or {}).items()}


def v2_panel(row: Mapping[str, Any]) -> dict[str, float]:
    return inc_panel(row)


def _nonvoting(entry: Mapping[str, Any]) -> dict[str, str]:
    if "obs" in entry:
        return {k: v[2] for k, v in entry["obs"].items() if v[2] != "voting"}
    return dict(entry.get("nv") or {})


def adapt(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The V1 evaluator's record shape: incumbent votes once, every variant's
    ``[value, rank, dropped-relative-to-the-incumbent-panel, confidence]``."""
    inc_rows = rec["builds"]["inc"]["rows"]
    rows: dict[str, Any] = {}
    for name, r in inc_rows.items():
        rows[name] = {
            "ac": r.get("ac"),
            "pos": r.get("pos"),
            "votes": inc_panel(r),
            "w": inc_weights(r),
        }
    variants: dict[str, dict[str, list]] = {}
    for cfg, b in rec["builds"].items():
        out = {}
        for name, e in b["rows"].items():
            panel = rows.get(name, {}).get("votes", {})
            nv = _nonvoting(e)
            dropped = sorted(k for k in panel if k in nv)
            out[name] = [_num(e.get("v")), e.get("rk"), dropped, e.get("cf")]
        variants["policy" if cfg == "v2" else ("incumbent" if cfg == "inc" else cfg)] = out
    return {"board": rec["board"], "rows": rows, "variants": variants, "_rec": rec}


# ── M1 (S10) ────────────────────────────────────────────────────────────


def m1_units(days: Mapping[Any, Mapping[str, Any]], h: int) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    order = sorted(days)
    for d in order:
        rec = days[d]
        td = d if h == 0 else target_day(d, h, set(order))
        if td is None:
            continue
        tgt = days[td]
        v2rows = rec["_rec"]["builds"]["v2"]["rows"]
        for name, row in rec["rows"].items():
            ac = row.get("ac")
            if ac == "pick":
                continue
            fams = {E.family_of(k) for k in row["votes"]}
            v2 = v2rows.get(name)
            if v2 is None or "m1" not in v2:
                continue
            v2votes = v2_panel(v2)
            v2w = inc_weights(v2)
            for F in sorted(fams):
                if len(fams - {F}) < 3:
                    continue
                target = E._family_target(tgt["rows"].get(name), F)
                if target is None:
                    continue
                reduced = {k: v for k, v in row["votes"].items() if E.family_of(k) != F}
                w = {k: row["w"].get(k, 1.0) for k in reduced}
                losses, dropped = {}, {}
                ok = True
                for method in ("incumbent", "none"):
                    drop = E.decide(method, reduced, w, str(ac))
                    V = E.blend({k: v for k, v in reduced.items() if k not in drop}, w)
                    if V is None:
                        ok = False
                        break
                    losses[method] = abs(math.log(V) - target)
                    dropped[method] = sorted(drop)
                if not ok:
                    continue
                v2_red = {k: v for k, v in v2votes.items() if E.family_of(k) != F}
                c_drop = set(v2["m1"].get(F) or [])
                kept = {k: v for k, v in v2_red.items() if k not in c_drop}
                V = E.blend(kept, v2w)
                if V is None:
                    continue
                losses["v2"] = abs(math.log(V) - target)
                dropped["v2"] = sorted(k for k in reduced if k not in kept)
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


# ── census, H cases, false exclusions ───────────────────────────────────


def v2_exclusions(rec: Mapping[str, Any], cfg: str = "v2") -> Counter:
    c: Counter = Counter()
    for name, e in rec["builds"][cfg]["rows"].items():
        for k, st in _nonvoting(e).items():
            if st.startswith("integrity:") or st == "filter_dropped":
                c[f"{st}|{k}"] += 1
    return c


def exclusion_census(rec: Mapping[str, Any]) -> dict[str, Any]:
    out = {}
    for cfg, b in rec["builds"].items():
        by_state: Counter = Counter()
        by_source: Counter = Counter()
        for name, e in b["rows"].items():
            ac = (rec["builds"]["inc"]["rows"].get(name) or {}).get("ac")
            for k, st in _nonvoting(e).items():
                if st == "voting" or st.startswith("excluded:"):
                    continue
                by_state[st.split(":", 1)[0] if st == "filter_dropped" else st] += 1
                by_source[f"{ac}|{k}"] += 1
        out[cfg] = {
            "total": sum(by_state.values()),
            "byReason": dict(by_state.most_common()),
            "bySource": dict(by_source.most_common(25)),
        }
    return out


def voting_observations(rec: Mapping[str, Any], cfg: str = "v2") -> int:
    n = 0
    for e in rec["builds"][cfg]["rows"].values():
        for v in (e.get("obs") or {}).values():
            if v[0] is not None and v[0] > 0 and not v[2].startswith("excluded:"):
                n += 1
    return n


def false_exclusions(rec: Mapping[str, Any]) -> dict[str, Any]:
    """Prereg §10 clean-board false exclusions on the V2 primary build."""
    det, other = Counter(), Counter()
    for name, e in rec["builds"]["v2"]["rows"].items():
        if (rec["builds"]["inc"]["rows"].get(name) or {}).get("ac") == "pick":
            continue
        for k, st in _nonvoting(e).items():
            if not (st.startswith("integrity:") or st == "filter_dropped"):
                continue
            reason = st.split(":", 1)[1] if ":" in st else "layer_c_drop"
            if reason.startswith(DETERMINISTIC_PREFIXES):
                det[reason] += 1
            else:
                other[reason] += 1
    votes = voting_observations(rec)
    return {
        "votingObservations": votes,
        "deterministicPendingReview": dict(det),
        "nonDeterministic": dict(other),
        "rateUpperBound": round((sum(det.values()) + sum(other.values())) / votes, 6)
        if votes
        else None,
        "rateNonDeterministicOnly": round(sum(other.values()) / votes, 6) if votes else None,
    }


def board_level_findings(rec: Mapping[str, Any], cfg: str = "v2") -> list[dict]:
    integ = rec["builds"][cfg].get("sourceIntegrity") or {}
    out = []
    for f in integ.get("findings") or []:
        if f.get("hard"):
            out.append(
                {
                    "source": f.get("source"),
                    "reason": f.get("reason"),
                    "scope": f.get("scope"),
                    "evidence": f.get("evidence"),
                }
            )
    for s, blk in (integ.get("provenance") or {}).items():
        if blk.get("boardProof"):
            out.append({"source": s, "reason": "b2_board_proof", "groups": blk.get("provenGroups")})
    return out


def rookie_status(rec: Mapping[str, Any], cfg: str = "v2", key: str | None = None) -> dict:
    rows = (rec[key] if key else rec["builds"][cfg])["rows"]
    out = {}
    for s in ROOKIE_SOURCES:
        present = withheld = voting = 0
        reasons: Counter = Counter()
        for e in rows.values():
            st = ((e.get("obs") or {}).get(s) or [None, 0, None])[2]
            if st is None:
                continue
            present += 1
            reasons[st] += 1
            if st.startswith("integrity:normalization") or st.startswith("excluded:"):
                withheld += 1
            elif st in ("voting", "filter_dropped"):
                voting += 1
        out[s] = {
            "observations": present,
            "withheld": withheld,
            "stillVoting": voting,
            "reasons": dict(reasons),
        }
    return out


def untranslated_fires(rec: Mapping[str, Any], cfg: str = "v2") -> int:
    integ = rec["builds"][cfg].get("sourceIntegrity") or {}
    return int((integ.get("voteExclusions") or {}).get("normalization_untranslated", 0))


def h3_status(rec: Mapping[str, Any], cfg: str) -> dict[str, Any] | None:
    rows = rec["builds"][cfg]["rows"]
    e = rows.get(H3_ROW)
    if e is None:
        return None
    nv = _nonvoting(e)
    st = nv.get("idpTradeCalc", "voting")
    out = {"idpTradeCalcState": st, "value": e.get("v")}
    if "obs" in e:
        out["idpTradeCalcVote"] = (e["obs"].get("idpTradeCalc") or [None])[0]
    return out


def provenance_of(rec: Mapping[str, Any], cfg: str, source: str = "idpTradeCalc") -> Any:
    integ = rec["builds"][cfg].get("sourceIntegrity") or {}
    return (integ.get("provenance") or {}).get(source)


def movers_attributed(adapted: Mapping[str, Any], a: str, b: str, threshold: float = 0.10):
    """Every row moving ≥ threshold between two variants with the vote changes
    that explain it (prereg §10 M5/M6, criterion 9)."""
    rec = adapted["_rec"]
    out = []
    names = {"incumbent": "inc", "policy": "v2"}
    ba = rec["builds"][names.get(a, a)]["rows"]
    bb = rec["builds"][names.get(b, b)]["rows"]
    for name, x in ba.items():
        y = bb.get(name)
        vx, vy = _num(x.get("v")), _num((y or {}).get("v"))
        if not vx or not vy:
            continue
        rel = (vy - vx) / vx
        if abs(rel) < threshold:
            continue
        nx, ny = _nonvoting(x), _nonvoting(y)
        changed = {
            k: {"a": nx.get(k, "voting"), "b": ny.get(k, "voting")}
            for k in sorted(set(nx) | set(ny))
            if nx.get(k, "voting") != ny.get(k, "voting")
        }
        inc_row = rec["builds"]["inc"]["rows"].get(name) or {}
        out.append(
            {
                "row": name,
                "assetClass": inc_row.get("ac"),
                "position": inc_row.get("pos"),
                "a": vx,
                "b": vy,
                "relative": round(rel, 4),
                "voteStateChanges": changed,
                "attributed": bool(changed),
                "incumbentVotes": {k: int(v) for k, v in sorted(inc_panel(inc_row).items())},
            }
        )
    out.sort(key=lambda m: -abs(m["relative"]))
    return out


def focus_rows(rec: Mapping[str, Any], cfgs: Sequence[str]) -> dict[str, Any]:
    out = {}
    for name in FOCUS:
        inc = rec["builds"]["inc"]["rows"].get(name)
        if inc is None:
            continue
        entry = {"incumbentVotes": {k: v[0] for k, v in (inc.get("obs") or {}).items()}}
        for cfg in cfgs:
            e = rec["builds"][cfg]["rows"].get(name)
            if e is None:
                continue
            entry[cfg] = {"value": e.get("v"), "notVoting": _nonvoting(e), "dropped": e.get("dr")}
        out[name] = entry
    return out


def stability_ratio(days: Mapping[Any, Mapping[str, Any]]) -> dict[str, Any]:
    return E.m4_stability(days, methods=("incumbent", "policy", "v1"))


def median_q(vals: Sequence[float]) -> float | None:
    return statistics.median(vals) if vals else None


def by_category(counter: Mapping[str, int]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for k, v in counter.items():
        out[k.split("|", 1)[0]] += v
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
