"""Trade Finder replay under alternative package models (Phase 2 research).

RESEARCH ONLY, in-process isolation: each candidate is installed by replacing
``src.valuation_math.package_model._geom_pair`` inside THIS process only — the
one function every active-model Value Adjustment call reaches (finder scoring,
discovery ``equity_verdict``, suggestions, angle, Best Offers, Package Builder).
Production files, config and the live server are untouched; the incumbent run
uses the real, unpatched dispatch and the patch is always restored.

Replayed surfaces, each for every team against every other team, on ONE board:

* ``package_scan`` — the /arbitrage "Package Scan" request (Trade Finder,
  ``equalCountOnly`` + discovery top250 / both / most_impactful);
* ``finder_all_shapes`` — the same finder with unequal shapes allowed (1-for-2,
  2-for-3, ... — where a package model matters most);
* ``best_offers`` — one best offer per opponent;
* ``star_builder`` — Package Builder asked to acquire each opponent's single best
  player (the "superstar for a pile" request).

Golden Upgrades is 1-for-1 only; every candidate except KTC adds no adjustment to
a 1-for-1, so it is not replayed (stated, not skipped silently).

Team context is OFF (``use_team_context=False``) so forced-drop / posture effects,
which need box-local roster capacity, cannot be confused with model effects.
Candidate ENUMERATION is model-independent; ``packageEnumeration`` is checked to be
identical across models so any difference is a SCORING difference.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from src.valuation_math import package_model as pm
from src.valuation_math.ktc_va_core import js_round

DEFAULT_MODELS = ["GEOM_78", "EFD_78", "HYBRID_50", "FGEOM_70_20", "BLEND_G50_K50", "KTC"]


@contextmanager
def installed(gap: Callable | None):
    """Install a signed-gap model behind the active dispatch, in-process only."""
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "replay assumes the geometric incumbent"
    original = pm._geom_pair
    if gap is not None:

        def _alt(t1, t2, q, _gap=gap):
            d = _gap(list(t1), list(t2)) - (sum(t1) - sum(t2))
            v = js_round(abs(d))
            return (0, 0, False) if v <= 0 else (v, 1 if d > 0 else 2, True)

        pm._geom_pair = _alt
    try:
        yield
    finally:
        pm._geom_pair = original


def _key(trade: dict[str, Any]) -> str:
    give = sorted(a.get("name") or a.get("displayName") or "?" for a in trade.get("give") or [])
    recv = sorted(a.get("name") or a.get("displayName") or "?" for a in trade.get("receive") or [])
    return " + ".join(give) + "  ->  " + " + ".join(recv)


def _vals(side) -> list[float]:
    out = []
    for a in side or []:
        v = a.get("modelValue", a.get("value"))
        if isinstance(v, (int, float)) and v > 0:
            out.append(float(v))
    return out


def classify(trade: dict[str, Any], gap: Callable, level: Callable) -> dict[str, Any]:
    """Preregistered defensibility tags (PREREGISTRATION.md §4) on canonical values."""
    give, recv = _vals(trade.get("give")), _vals(trade.get("receive"))
    if not give or not recv:
        return {"priced": False}
    best_give, best_recv = max(give), max(recv)
    # The side giving the trade's single best asset:
    if best_give >= best_recv:
        star, pile = give, recv
    else:
        star, pile = recv, give
    s = max(star)
    lvl = level(gap, recv, give)  # from the user's side: receive vs give
    star_for_pile = len(pile) >= 3 and all(v < 0.5 * s for v in pile) and lvl in ("fair", "slight")

    # Sensible depth: a side receives >= 2 pieces each >= 40% of the best it gives,
    # with raw >= 1.15x what it gives.
    def sensible(rcv, gv):
        return len(rcv) >= 2 and all(v >= 0.4 * max(gv) for v in rcv) and sum(rcv) >= 1.15 * sum(gv)

    return {
        "priced": True,
        "shape": f"{len(give)}v{len(recv)}",
        "level": lvl,
        "starForPile": star_for_pile,
        "sensibleDepth": sensible(recv, give) or sensible(give, recv),
        "multiPiece3plus": max(len(give), len(recv)) >= 3,
        "elite": s >= 7000,
        "idp": any(
            (a.get("position") or "")
            in ("DL", "LB", "DB", "DE", "DT", "CB", "S", "EDGE", "ILB", "OLB")
            for a in (trade.get("give") or []) + (trade.get("receive") or [])
        ),  # fmt: skip
    }


def _geom_exact_gap(q: float = 0.78) -> Callable:
    def u(vals):
        d = sorted((float(v) for v in vals if v and v > 0), reverse=True)
        return sum(v * q**i for i, v in enumerate(d))

    return lambda a, b: u(a) - u(b)


def run(*, board_raw_path: Path, models: dict[str, dict], model_ids: list[str] | None = None,
        level: Callable | None = None) -> dict[str, Any]:  # fmt: skip
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.trade import best_offers as bo  # noqa: PLC0415
    from src.trade import discovery as disc  # noqa: PLC0415
    from src.trade import finder  # noqa: PLC0415
    from src.trade import package_builder as pb  # noqa: PLC0415

    raw = json.loads((Path(board_raw_path) if Path(board_raw_path).is_absolute() else
                      Path(__file__).resolve().parents[1] / board_raw_path).read_text())  # fmt: skip
    contract = build_api_data_contract(raw)
    teams = contract["sleeper"]["teams"]
    names = [t["name"] for t in teams]
    players = contract["players"]
    default = disc.DiscoveryFilters(quality="top250", scope="both", sort="most_impactful")
    model_ids = model_ids or DEFAULT_MODELS
    # Each opponent's single best player (by canonical value) — the star request.
    star_of = {}
    for t in teams:
        best = None
        for nm in t.get("players") or []:
            v = (players.get(nm) or {}).get("rankDerivedValue") or (players.get(nm) or {}).get(
                "_finalAdjusted"
            )
            if isinstance(v, (int, float)) and (best is None or v > best[1]):
                best = (nm, v)
        star_of[t["name"]] = best[0] if best else None

    def opps(me, equal):
        o = [n for n in names if n != me]
        return o + ([{"__arbitrageControl": {"equalCountOnly": True}}] if equal else [])

    surfaces = {
        "package_scan": lambda me: finder.find_trades(players, me, opps(me, True), teams, contract=contract,
                                                      use_team_context=False, discovery=default),
        "finder_all_shapes": lambda me: finder.find_trades(players, me, opps(me, False), teams, contract=contract,
                                                           use_team_context=False, discovery=default),
        "best_offers": lambda me: bo.build_best_offers(players, me, teams, contract=contract,
                                                       use_team_context=False, discovery=default),
        "star_builder": lambda me: {
            opp: pb.build_packages(players, me, teams, contract=contract, target=star_of[opp], opponent=opp,
                                   use_team_context=False, limit=5)
            for opp in names if opp != me and star_of.get(opp)
        },
    }  # fmt: skip

    def norm(t):
        return {"give": t.get("give") or t.get("send") or [], "receive": t.get("receive") or []}

    def trades_of(surface, payload):
        if surface in ("package_scan", "finder_all_shapes"):
            return [norm(t) for t in payload.get("trades") or []]
        if surface == "best_offers":
            return [norm(o["offer"]) for o in payload.get("opponents") or [] if o.get("offer")]
        return [norm(p) for res in payload.values() for p in res.get("packages") or []]

    # Gaps that themselves route through the active dispatch (the blends call the
    # geometric dispatch) would recurse once installed, so the replay uses the
    # closed-form geometric utility for them.  Exact up to integer rounding.
    geom_exact = _geom_exact_gap()
    safe = dict(models)
    safe["GEOM_78"] = {"gap": geom_exact}
    for mid in model_ids:
        if mid.startswith("BLEND_G"):
            w = int(mid.split("_")[1][1:]) / 100.0
            ktc = models["KTC"]["gap"]
            safe[mid] = {
                "gap": (lambda a, b, w=w, ktc=ktc: w * geom_exact(a, b) + (1 - w) * ktc(a, b))
            }

    results: dict[str, Any] = {}
    timings = {}
    for mid in model_ids:
        gap = None if mid == "GEOM_78" else safe[mid]["gap"]
        t0 = time.time()
        with installed(gap):
            per_surface = {}
            for sname, fn in surfaces.items():
                per_team = {}
                for me in names:
                    payload = fn(me)
                    tr = trades_of(sname, payload)
                    meta = (
                        (payload.get("metadata") or {})
                        if sname in ("package_scan", "finder_all_shapes")
                        else {}
                    )
                    per_team[me] = {
                        "keys": [_key(x) for x in tr],
                        "trades": [{"key": _key(x), "give": [(a.get("name"), a.get("modelValue", a.get("value")))
                                                             for a in x.get("give") or []],
                                    "receive": [(a.get("name"), a.get("modelValue", a.get("value")))
                                                for a in x.get("receive") or []],
                                    "tags": classify(x, safe[mid]["gap"], level)}
                                   for x in tr],
                        "enumeration": meta.get("packageEnumeration"),
                        "evaluated": meta.get("totalCandidatesEvaluated"),
                        "qualified": meta.get("totalQualified"),
                    }  # fmt: skip
                per_surface[sname] = per_team
        timings[mid] = round(time.time() - t0, 1)
        results[mid] = per_surface
    return {"surfaces": list(surfaces), "teams": names, "models": model_ids, "timingsSec": timings,
            "starTargets": star_of, "raw": results}  # fmt: skip


def _raw_gain(t: dict[str, Any]) -> float:
    """User-side canonical raw gain (receive minus give), the finder's own board edge."""
    return sum(v for _, v in t["receive"] if v) - sum(v for _, v in t["give"] if v)


def compare(replay: dict[str, Any], base: str = "GEOM_78", top_k: int = 10) -> dict[str, Any]:
    """Appear / disappear / reorder / reclassify versus the incumbent, plus the
    preregistered defensibility counts — per model x surface."""
    out: dict[str, Any] = {}
    for mid in replay["models"]:
        out[mid] = {}
        for s in replay["surfaces"]:
            b_all, m_all = replay["raw"][base][s], replay["raw"][mid][s]
            appear = disappear = same = reordered = 0
            topk_overlap = []
            enum_identical = True
            counts = {"trades": 0, "starForPile": 0, "sensibleDepth": 0, "multiPiece3plus": 0, "elite": 0,
                      "idp": 0, "levels": {}}  # fmt: skip
            for team in replay["teams"]:
                bk, mk = b_all[team]["keys"], m_all[team]["keys"]
                bs, ms = set(bk), set(mk)
                appear += len(ms - bs)
                disappear += len(bs - ms)
                common = [k for k in mk if k in bs]
                same += len(common)
                reordered += sum(1 for k in common if bk.index(k) != mk.index(k))
                if bk or mk:
                    topk_overlap.append(
                        len(set(bk[:top_k]) & set(mk[:top_k]))
                        / max(1, min(top_k, max(len(bk), len(mk))))
                    )
                if b_all[team]["enumeration"] != m_all[team]["enumeration"]:
                    enum_identical = False
                for tr in m_all[team]["trades"]:
                    tg = tr["tags"]
                    if not tg.get("priced"):
                        continue
                    counts["trades"] += 1
                    for k in ("starForPile", "sensibleDepth", "multiPiece3plus", "elite", "idp"):
                        counts[k] += bool(tg.get(k))
                    counts["levels"][tg["level"]] = counts["levels"].get(tg["level"], 0) + 1
            # Preregistered C6 counts versus the incumbent's own list.
            lost_sensible = 0
            gain_app, gain_dis = [], []
            for team in replay["teams"]:
                b = {t["key"]: t for t in b_all[team]["trades"]}
                m = {t["key"]: t for t in m_all[team]["trades"]}
                lost_sensible += sum(
                    1 for k, t in b.items() if k not in m and t["tags"].get("sensibleDepth")
                )
                gain_app += [_raw_gain(m[k]) for k in m if k not in b]
                gain_dis += [_raw_gain(b[k]) for k in b if k not in m]
            out[mid][s] = {
                "lostSensibleDepthVsIncumbent": lost_sensible,
                "meanUserRawGainAppeared": round(sum(gain_app) / len(gain_app))
                if gain_app
                else None,
                "meanUserRawGainDisappeared": round(sum(gain_dis) / len(gain_dis))
                if gain_dis
                else None,
                "appear": appear,
                "disappear": disappear,
                "kept": same,
                "keptButReordered": reordered,
                "meanTop10Overlap": round(sum(topk_overlap) / len(topk_overlap), 3)
                if topk_overlap
                else None,
                "enumerationIdenticalToIncumbent": enum_identical,
                **counts,
            }
    return out


def examples(replay: dict[str, Any], base: str = "GEOM_78", per: int = 12) -> dict[str, Any]:
    """Concrete appeared / disappeared recommendations (with tags) per model x surface."""
    out: dict[str, Any] = {}
    for mid in replay["models"]:
        if mid == base:
            continue
        out[mid] = {}
        for s in replay["surfaces"]:
            appeared, disappeared = [], []
            for team in replay["teams"]:
                b = {t["key"]: t for t in replay["raw"][base][s][team]["trades"]}
                m = {t["key"]: t for t in replay["raw"][mid][s][team]["trades"]}
                appeared += [{"team": team, **m[k]} for k in m if k not in b]
                disappeared += [{"team": team, **b[k]} for k in b if k not in m]
            out[mid][s] = {"appeared": appeared[:per], "disappeared": disappeared[:per],
                           "appearedStarForPile": [x for x in appeared if x["tags"].get("starForPile")][:per]}  # fmt: skip
    return out
