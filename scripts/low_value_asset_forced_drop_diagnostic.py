#!/usr/bin/env python3
"""Low-value-asset research — forced-drop (Team Context) diagnostic.  RESEARCH ONLY.

Owner question (2026-10-20): "Is Team Context already charging too much for
forced drops?" — War Room / ``/api/trade/analyze`` with Team Context ON, under the
production package model ``geom_q078_v1``.

This re-runs the SAME War Room design as
``scripts/low_value_asset_shadow_replay.py::war_room`` (same board archive, same
seed, same sampling loop, same production calls) to reproduce its headline
(133 asset-only filler flips; 85 neutralised / 43 over-corrected / 5 surviving
with Team Context), then:

1. records every forced drop: value basis (``board`` / ``assumedWaiver``),
   position, scarcity multiplier, whether a cheaper post-trade roster piece —
   in particular a just-acquired filler — existed but was not the one cut, and
   whether a cheaper piece was lineup-protected;
2. attributes each production over-correction to the shadow counterfactual(s)
   that remove it;
3. evaluates shadow counterfactuals, recomputed INSIDE this script only:

   * ``V1_cheapestRelease`` — the cut set is the lineup-legal set with the
     smallest total release cost over the whole post-trade roster (incoming
     pieces included), instead of the production ECC order (which ties at 0 for
     every at-or-below-waiver player and so falls back to alphabetical order);
   * ``V2a_unpricedExcluded`` — production selection; an unpriced drop is not
     charged (the rule ``roster_capacity.forced_drop_cost`` already applies for
     the Trade Finder, and the rule the feasibility lens's own comment states);
   * ``V2b_unpricedBoardFloor`` — production selection; an unpriced drop is
     charged ``min(waiver, lowest priced board value at his position) x scarcity``
     — the board prices everyone it has trusted evidence for, so an unpriced
     player is not shown to be worth more than the position's priced floor;
   * ``V3a`` / ``V3b`` — V1 selection with the V2a / V2b unpriced cost;
   * ``V4_packageConsistent`` — V3b, except that cutting a just-acquired piece
     is charged what the package credited for it (the trade is re-scored
     without that piece) rather than its raw value x scarcity; the receiver
     picks the legal cut set that leaves it best off.

Band basis (added 2026-10-21, ``docs/valuation/LOW_VALUE_ASSET_V2_CORRECTION_2026-10-21.md``).
The committed evidence was produced when the fairness band divided by the larger
ADJUSTED side (fairness_bands_v1).  The band's base is read from the production
lens that took it from the fairness-band owner (``largerPackageUtility``) for the
production path AND every counterfactual, so they can never disagree again.
``--band-basis current`` (default) = the engine as it now is (fairness_bands_v2);
``--band-basis v1_legacy`` runs the engine inside ``legacy_v1_denominator()`` to
reproduce the committed numbers.  ``--archive`` / ``--csv-rev`` pin the board.

No production code, config, value or served path is changed; every production
function is only CALLED.  Output:
``docs/valuation/evidence/low_value_assets_2026-10-20/forced_drop_diagnostic.json``
— aggregates plus a few illustrative examples with NFL player names and values
only (checked with ``assert_aggregate_only``).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import itertools
import json
import random
import statistics
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/valuation/evidence/low_value_assets_2026-10-20/forced_drop_diagnostic.json"
ARCHIVE_DEFAULT = "exports/archive/dynasty_export_20261020_052241.zip"
ARCHIVE_SHA256 = "8e9b826a3a148bbb17636aec79b46eefe3e9138940976959c4342dc4774b198a"
sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("low_value_asset_shadow_replay")  # build_context / classify_assets / constants

from src.draft import displacement as DP  # noqa: E402
from src.trade import analyze_service as AS  # noqa: E402
from src.trade import analyze_trade as AT  # noqa: E402
from src.trade import roster_capacity as RC  # noqa: E402
from src.trade import trade_decision as TD  # noqa: E402
from src.valuation_math import fairness_bands  # noqa: E402
from src.valuation_math import package_model as pm  # noqa: E402

LEAGUE = S.LEAGUE
LEVEL_RANK = S.LEVEL_RANK
VARIANTS = (
    "PROD",
    "V1_cheapestRelease",
    "V2a_unpricedExcluded",
    "V2b_unpricedBoardFloor",
    "V3a_cheapest_unpricedExcluded",
    "V3b_cheapest_unpricedBoardFloor",
    "V4_packageConsistent",
)


def _sgn(x):
    return (x > 0) - (x < 0)


def _r(x, n=0):
    return None if x is None else round(x, n) if n else round(x)


def _ord(net: float, base: float) -> int:
    """Signed ordinal of ``net`` against the band base the production lens used (the
    owner's larger package utility; under ``legacy_v1_denominator`` the v1 base)."""
    band = fairness_bands.classify(net, base)
    return _sgn(net) * LEVEL_RANK[band["level"]]


def load_archive(rel: str) -> tuple[str, bytes, dict]:
    zpath = REPO / rel
    with zipfile.ZipFile(zpath) as zf:
        member = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        blob = zf.read(member)
    return member, blob, json.loads(blob)


# ── post-trade pool, costed exactly as roster_capacity / displacement do ──


def post_trade_pool(cc, incoming: list[str], outgoing: list[str]) -> list[dict]:
    """``assess_roster_capacity``'s surviving pool (same construction), each
    player costed by ``displacement.effective_cut_cost`` and tagged
    ``acquired`` when it arrives in the trade."""
    outgoing_keys = {RC._norm(n) for n in outgoing}
    raw: list[tuple[object, bool]] = []
    for name in cc.roster_player_names:
        key = RC._norm(name)
        if key in outgoing_keys:
            outgoing_keys.discard(key)
            continue
        a = cc.assets_by_key.get(key) or RC._resolve_incoming(name, cc.by_name)
        raw.append((a, False))
    for name in incoming:
        raw.append((RC._resolve_incoming(name, cc.by_name), True))
    pool = []
    for a, acq in raw:
        asset = DP.RosterAsset(
            player_id=str(a.player_id),
            name=str(a.name or a.player_id),
            position=str(a.position or ""),
            board_value=a.board_value if isinstance(a.board_value, (int, float)) else None,
            ros_value=DP.FEASIBILITY_OBJECTIVE,
            fantasy_positions=tuple(a.fantasy_positions or ()),
            injured=bool(a.injured),
        )
        ecc, base, basis, waiver, mult = DP.effective_cut_cost(asset, cc.waiver_values, cc.scarcity)
        pool.append({
            "asset": asset, "acquired": acq, "ecc": ecc, "base": base, "basis": basis,
            "waiver": waiver, "mult": mult, "release": base * mult,
            "pos": asset.position, "name": asset.name, "value": asset.board_value,
        })  # fmt: skip
    return pool


class Legality:
    """Lineup-legality oracle for one post-trade pool (the ladder's own rule:
    a removal is legal iff the surviving roster fills as many starting slots as
    the post-trade roster does)."""

    def __init__(self, pool, cc):
        self.pool = pool
        self.slots = [s for s in (cc.starter_slots or []) if s]
        self.elig = cc.slot_eligibility or None
        self.base = self._filled(range(len(pool))) if self.slots else 0
        self.cache: dict = {}

    def _filled(self, idx) -> int:
        return DP._filled_slot_count([self.pool[i]["asset"] for i in idx], self.slots, self.elig)

    def ok(self, removed: frozenset) -> bool:
        if not self.slots:
            return True
        if removed not in self.cache:
            keep = [i for i in range(len(self.pool)) if i not in removed]
            self.cache[removed] = self._filled(keep) >= self.base
        return self.cache[removed]


def greedy(pool, legal: Legality, d: int, key, allowed=None) -> list[int]:
    """Cheapest-first greedy with the lineup guard (exact on the cut matroid)."""
    order = sorted((i for i in range(len(pool)) if allowed is None or i in allowed), key=key)
    chosen: list[int] = []
    for i in order:
        if len(chosen) >= d:
            break
        if legal.ok(frozenset([*chosen, i])):
            chosen.append(i)
    return chosen


def cost_v2b(p, floor_by_pos: dict, floor_any: float) -> float:
    if p["basis"] != "assumedWaiver":
        return p["release"]
    fl = floor_by_pos.get(p["pos"], floor_any)
    return min(p["waiver"], fl) * p["mult"]


def cost_v2a(p) -> float:
    return 0.0 if p["basis"] == "assumedWaiver" else p["release"]


# ── the War Room replay ───────────────────────────────────────────────────


def sample_trades(ctx, max_opps: int, seed: int) -> list[dict]:
    """VERBATIM the sampling loop of ``low_value_asset_shadow_replay.war_room``
    (same RNG consumption), so the same 45 trades come out."""
    rng = random.Random(seed)
    rows, teams = ctx["rows"], ctx["teams"]
    cap = int(ctx["roster_settings"].get("rosterSize") or 0)

    def ok(n):
        r = rows.get(n)
        return r if r and not r["quarantined"] and r["cls"] != "pick" else None

    samples = []
    for ti, me in enumerate(teams):
        if len(me.get("players") or []) != cap:
            continue
        mine = [ok(n) for n in me["players"]]
        mine = [r for r in mine if r and r["cat"] == "starter" and 2500 <= r["value"] <= 6500]
        opps = [o for oi, o in enumerate(teams) if oi != ti]
        rng.shuffle(opps)
        for opp in opps[:max_opps]:
            theirs = [r for r in (ok(n) for n in opp["players"]) if r]
            fillers = [r for r in theirs if r["cat"] == "filler" and r["value"] >= 300]
            if not mine or len(fillers) < 3:
                continue
            x = rng.choice(mine)
            cand = [
                r
                for r in theirs
                if r["cat"] != "filler" and 0.86 * x["value"] <= r["value"] <= 0.97 * x["value"]
            ]
            if not cand:
                continue
            y = rng.choice(cand)
            fl = rng.sample(fillers, 3)
            samples.append({"ti": ti, "me": me, "x": x, "y": y, "fill": fl})
    return samples


def run_diagnostic(ctx, max_opps: int, seed: int) -> dict:
    contract, rs = ctx["contract"], ctx["roster_settings"]
    rows = ctx["rows"]
    # Position floor of the PRICED board (V2b): the lowest rankDerivedValue the
    # board assigns anyone at the position.
    floor_by_pos: dict[str, float] = {}
    for r in rows.values():
        if r["cls"] != "pick" and r["pos"]:
            floor_by_pos[r["pos"]] = min(floor_by_pos.get(r["pos"], 1e9), r["value"])
    floor_any = min(floor_by_pos.values())

    def sim(me, pin, pout, tc):
        return AS.simulate_for_team(contract, league_key=LEAGUE, roster_settings=rs,
                                    resolved_team=me, players_in=pin, players_out=pout,
                                    team_context=tc, for_analysis=True)  # fmt: skip

    def comp_a(s, tc):
        market = AT._market_lens(s)
        if not market.available:
            return None
        feas = (AT._feasibility_lens(s) if tc
                else AT._excluded_by_mode("feasibility", AT.LINEAGE_ROSTER_RULES))  # fmt: skip
        return TD._objective_value(market, feas)

    def ordinal(a):
        if a is None:
            return None
        return _sgn(a["netGap"]) * LEVEL_RANK[a["band"]["level"]]

    samples = sample_trades(ctx, max_opps, seed)
    cc_cache: dict = {}
    gap_cache: dict = {}
    results = []
    drop_rows: list[dict] = []
    cut_rows: list[dict] = []
    repro_match = repro_total = 0
    scarcity_state = None
    for si, s in enumerate(samples):
        me = s["me"]
        if s["ti"] not in cc_cache:
            cc_cache[s["ti"]] = RC.build_capacity_context(contract, LEAGUE, me, roster_settings=rs)
        cc = cc_cache[s["ti"]]
        scarcity_state = (
            "available"
            if cc.scarcity
            else "inert (multiplier 1.0): " + "; ".join(n for n in cc.notes if "scarcity" in n)
        )
        fill_names = [r["name"] for r in s["fill"]]
        pout = [s["x"]["name"]]

        def gap_with(fset, _s=s, _me=me, _pout=pout, _si=si):
            key = (_si, frozenset(fset))
            if key not in gap_cache:
                pin = [_s["y"]["name"]] + [n for n in fill_names if n in fset]
                a = comp_a(sim(_me, pin, _pout, False), False)
                gap_cache[key] = (a["vaAdjustedGap"], a["largerPackageUtility"]) if a else None
            return gap_cache[key]

        rec = {"s": s, "steps": []}
        for k in range(4):
            pin = [s["y"]["name"]] + fill_names[:k]
            sa, st = sim(me, pin, pout, False), sim(me, pin, pout, True)
            a_ao, a_tc = comp_a(sa, False), comp_a(st, True)
            gap_cache[(si, frozenset(fill_names[:k]))] = (
                (a_ao["vaAdjustedGap"], a_ao["largerPackageUtility"]) if a_ao else None
            )
            rc = st.get("rosterCapacity") or {}
            drops = rc.get("forcedDrops") or []
            step = {
                "k": k,
                "aoOrd": ordinal(a_ao),
                "tcOrd": ordinal(a_tc),
                "gap": a_ao["vaAdjustedGap"] if a_ao else None,
                "larger": a_ao["largerPackageUtility"] if a_ao else None,
                "prodCharged": (a_tc or {}).get("forcedReleaseCost"),
                "prodDrops": drops,
                "d": int(rc.get("overLimitAfter") or 0),
                "overBefore": rc.get("overLimitBefore"),
                "certainty": rc.get("certainty"),
            }
            if k > 0 and step["d"] > 0 and a_ao is not None:
                pool = post_trade_pool(cc, pin, pout)
                legal = Legality(pool, cc)
                d = step["d"]
                # (0) the production ladder order, reconstructed: ECC then name.
                prod_idx = greedy(
                    pool, legal, d, key=lambda i: (pool[i]["ecc"], pool[i]["name"].lower())
                )
                repro_total += 1
                repro_match += sorted(pool[i]["name"] for i in prod_idx) == sorted(
                    x.get("name") for x in drops
                )
                # V1 / V3: cheapest total release first.
                v1_idx = greedy(
                    pool, legal, d, key=lambda i: (pool[i]["release"], pool[i]["name"].lower())
                )
                v3a_idx = greedy(
                    pool, legal, d, key=lambda i: (cost_v2a(pool[i]), pool[i]["name"].lower())
                )
                v3b_idx = greedy(pool, legal, d,
                                 key=lambda i: (cost_v2b(pool[i], floor_by_pos, floor_any),
                                                pool[i]["name"].lower()))  # fmt: skip
                charges = {
                    "PROD_recomputed": sum(pool[i]["release"] for i in prod_idx),
                    "V1_cheapestRelease": sum(pool[i]["release"] for i in v1_idx),
                    "V2a_unpricedExcluded": sum(cost_v2a(pool[i]) for i in prod_idx),
                    "V2b_unpricedBoardFloor": sum(
                        cost_v2b(pool[i], floor_by_pos, floor_any) for i in prod_idx
                    ),  # fmt: skip
                    "V3a_cheapest_unpricedExcluded": sum(cost_v2a(pool[i]) for i in v3a_idx),
                    "V3b_cheapest_unpricedBoardFloor": sum(
                        cost_v2b(pool[i], floor_by_pos, floor_any) for i in v3b_idx
                    ),  # fmt: skip
                }
                # V4: cut J of the acquired fillers (trade re-scored without them),
                # the rest cheapest legal (V2b cost) from the existing roster.
                acq_fill = [
                    i for i, p in enumerate(pool) if p["acquired"] and p["name"] in fill_names
                ]
                existing = {i for i, p in enumerate(pool) if not p["acquired"]}
                best = None
                for j in range(0, min(d, len(acq_fill)) + 1):
                    for J in itertools.combinations(acq_fill, j):
                        if not legal.ok(frozenset(J)):
                            continue
                        rest = greedy(pool, _Fixed(legal, J), d - j,
                                      key=lambda i: (cost_v2b(pool[i], floor_by_pos, floor_any),
                                                     pool[i]["name"].lower()),
                                      allowed=existing)  # fmt: skip
                        if len(rest) < d - j:
                            continue
                        kept = [n for n in fill_names[:k] if n not in {pool[i]["name"] for i in J}]
                        g = gap_with(kept)
                        if g is None:
                            continue
                        rel = sum(cost_v2b(pool[i], floor_by_pos, floor_any) for i in rest)
                        net = g[0] - rel
                        if best is None or net > best[0]:
                            best = (net, list(J) + rest, step["gap"] - g[0] + rel)
                step["v4"] = best
                charges["V4_packageConsistent"] = best[2] if best else None
                step["charges"] = charges
                step["pool"] = pool
                step["idx"] = {"PROD": prod_idx, "V1": v1_idx, "V3a": v3a_idx, "V3b": v3b_idx,
                               "V4": best[1] if best else None}  # fmt: skip
                step["legal"] = legal
                # per forced drop record (production drops)
                max_charged = max((pool[i]["release"] for i in prod_idx), default=0.0)
                acq_costs = [pool[i]["release"] for i in acq_fill]
                for i in prod_idx:
                    p = pool[i]
                    cheaper_unc = [
                        q for q in range(len(pool))
                        if q not in prod_idx and pool[q]["release"] < p["release"]
                    ]  # fmt: skip
                    cheaper_acq = [q for q in cheaper_unc if pool[q]["acquired"]]
                    cheaper_legal = [
                        q for q in cheaper_unc if legal.ok(frozenset([*prod_idx, q]) - {i})
                    ]
                    drop_rows.append({
                        "basis": p["basis"], "pos": p["pos"] or "(none)", "mult": round(p["mult"], 4),
                        "release": p["release"], "value": p["value"], "acquired": p["acquired"],
                        "ecc": p["ecc"], "cheaperAcquiredUncut": bool(cheaper_acq),
                        "cheaperLegalSwapExists": bool(cheaper_legal),
                        "cheaperOnlyIllegal": bool(cheaper_unc) and not cheaper_legal,
                    })  # fmt: skip
                step["maxCharged"] = max_charged
                for vk in ("V1", "V3b"):
                    for i in step["idx"][vk]:
                        q = pool[i]
                        cut_rows.append({
                            "variant": vk, "basis": q["basis"], "value": q["value"],
                            "acquired": q["acquired"],
                            "atBoardFloor": q["value"] is not None
                            and q["value"] <= floor_by_pos.get(q["pos"], floor_any) + 1,
                        })  # fmt: skip
                step["acqCosts"] = acq_costs
            rec["steps"].append(step)
        results.append(rec)
    return {
        "results": results,
        "drops": drop_rows,
        "repro": (repro_match, repro_total),
        "floor": floor_by_pos,
        "scarcity": scarcity_state,
        "scarcityByPosition": _scarcity_table(next(iter(cc_cache.values())).scarcity)
        if cc_cache
        else {},
        "cuts": cut_rows,
        "waiver": dict(next(iter(cc_cache.values())).waiver_values) if cc_cache else {},
    }


def _scarcity_table(sc) -> dict:
    out = {}
    for pos, comp in sorted((sc or {}).items()):
        ws = getattr(comp, "waiver_scarcity", None)
        out[str(pos)] = {
            "waiverScarcity": None if ws is None else round(float(ws), 4),
            "multiplier": round(DP.scarcity_multiplier(comp), 4),
        }
    return out


def cut_summary(cuts) -> dict:
    out = {}
    for vk in sorted({c["variant"] for c in cuts}):
        rows = [c for c in cuts if c["variant"] == vk]
        vals = sorted(c["value"] for c in rows if c["value"] is not None)
        out[vk] = {
            "cuts": len(rows),
            "byBasis": dict(Counter(c["basis"] for c in rows)),
            "justAcquiredFillerCut": sum(c["acquired"] for c in rows),
            "pricedValueQuartiles": [_r(v) for v in statistics.quantiles(vals, n=4)]
            if len(vals) >= 4
            else None,
            "pricedValueMin": _r(vals[0]) if vals else None,
            "atPositionBoardFloor": sum(c["atBoardFloor"] for c in rows),
        }
    return out


class _Fixed:
    """A legality oracle with some members already removed."""

    def __init__(self, legal: Legality, fixed):
        self.legal, self.fixed = legal, frozenset(fixed)

    def ok(self, removed: frozenset) -> bool:
        return self.legal.ok(frozenset(removed) | self.fixed)


# ── aggregation ───────────────────────────────────────────────────────────


def variant_ord(step, variant: str):
    if step["k"] == 0 or step["d"] == 0:
        return step["tcOrd"]
    if variant == "PROD":
        return step["tcOrd"]
    ch = step["charges"].get(variant)
    if ch is None:
        return None
    # trade_decision._objective_value: charged only when > 0.
    net = step["gap"] - (ch if ch > 0 else 0.0)
    return _ord(net, step["larger"])


def variant_charge(step, variant: str):
    if step["d"] == 0:
        return 0.0
    if variant == "PROD":
        return float(step["prodCharged"] or 0)
    ch = step["charges"].get(variant)
    return None if ch is None else float(ch)


def classify_flips(results, variant: str) -> dict:
    out = Counter()
    over_sig = 0
    charge_vs_credit = []
    for rec in results:
        s0 = rec["steps"][0]
        for st in rec["steps"][1:]:
            if st["aoOrd"] is None or s0["aoOrd"] is None or st["tcOrd"] is None:
                continue
            credit = st["gap"] - s0["gap"]
            ch = variant_charge(st, variant)
            if ch is not None and credit > 0:
                charge_vs_credit.append(ch / credit)
                over_sig += ch > credit
            if _sgn(st["aoOrd"]) == _sgn(s0["aoOrd"]):
                continue
            out["flips"] += 1
            vo = variant_ord(st, variant)
            base = variant_ord(s0, variant)
            if vo is None:
                out["notEvaluable"] += 1
            elif _sgn(vo) == _sgn(base):
                out["neutralised"] += 1
            elif _sgn(vo) < _sgn(base):
                out["overCorrected"] += 1
            else:
                out["surviving_underCorrected"] += 1
    return {
        **{k: out.get(k, 0) for k in ("flips", "neutralised", "overCorrected",
                                      "surviving_underCorrected", "notEvaluable")},
        "stepsWhereChargeExceedsFillerCredit": over_sig,
        "chargeOverCreditMedian": _r(statistics.median(charge_vs_credit), 3) if charge_vs_credit else None,
    }  # fmt: skip


def attribute(results) -> dict:
    """Which shadow fix removes each production over-correction, plus
    non-exclusive descriptive flags."""
    attr = Counter()
    flags = Counter()
    n = 0
    for rec in results:
        s0 = rec["steps"][0]
        for st in rec["steps"][1:]:
            if st["aoOrd"] is None or s0["aoOrd"] is None or st["tcOrd"] is None:
                continue
            if _sgn(st["aoOrd"]) == _sgn(s0["aoOrd"]) or _sgn(st["tcOrd"]) >= _sgn(s0["tcOrd"]):
                continue
            n += 1

            def fixed(v, _st=st, _s0=s0):
                o = variant_ord(_st, v)
                return o is not None and _sgn(o) >= _sgn(variant_ord(_s0, v))

            f1 = fixed("V1_cheapestRelease")
            f2a, f2b = fixed("V2a_unpricedExcluded"), fixed("V2b_unpricedBoardFloor")
            f3a, f3b = (
                fixed("V3a_cheapest_unpricedExcluded"),
                fixed("V3b_cheapest_unpricedBoardFloor"),
            )
            f4 = fixed("V4_packageConsistent")
            if f1 and (f2a or f2b):
                attr["either_selection_or_unpricedCost_fix_alone"] += 1
            elif f1:
                attr["selection_only (cheapest cut, V1)"] += 1
            elif f2b:
                attr["unpricedCost_only (V2b board floor; V2a too)"] += 1
            elif f2a:
                attr["unpricedCost_only_if_excluded (V2a)"] += 1
            elif f3b:
                attr["needs_both (V3b)"] += 1
            elif f3a:
                attr["needs_both_with_unpriced_excluded (V3a)"] += 1
            elif f4:
                attr["needs_packageConsistent_accounting (V4: raw x scarcity vs VA credit)"] += 1
            else:
                attr["not_removed_by_any_variant"] += 1
            pool, idx = st["pool"], st["idx"]["PROD"]
            dp = [pool[i] for i in idx]
            flags["unpricedDropCharged (assumedWaiver)"] += any(
                p["basis"] == "assumedWaiver" for p in dp
            )
            flags["cheaperAcquiredFillerExistedButNotCut"] += any(
                c < st["maxCharged"] for c in st["acqCosts"]
            )
            flags["acquiredFillerWasCut"] += any(p["acquired"] for p in dp)
            flags["scarcityMultiplierAbove1"] += any(p["mult"] > 1.0 + 1e-9 for p in dp)
            flags["multipleDrops (k>=2)"] += len(dp) >= 2
            flags["chargeExceedsSumOfIncomingFillerRawValues"] += st["prodCharged"] > sum(
                pool[i]["value"] or 0 for i in range(len(pool)) if pool[i]["acquired"]
                and pool[i]["name"] in {f["name"] for f in rec["s"]["fill"]}
            )  # fmt: skip
            # lineup-legality protection: a cheaper candidate that may not be cut
            cheaper_blocked = any(
                pool[q]["release"] < st["maxCharged"]
                and q not in idx
                and not st["legal"].ok(frozenset([q]))
                for q in range(len(pool))
            )
            flags["cheaperCandidateLineupProtected"] += cheaper_blocked
    return {
        "overCorrections": n,
        "byFirstSufficientFix": dict(attr),
        "descriptiveFlags": dict(flags),
    }


def drop_summary(drops) -> dict:
    by_basis = Counter(d["basis"] for d in drops)
    rel = {b: [d["release"] for d in drops if d["basis"] == b] for b in by_basis}
    pos_basis = Counter(f"{d['pos']}:{d['basis']}" for d in drops)
    mults = Counter(d["mult"] for d in drops)
    return {
        "forcedDrops": len(drops),
        "byBasis": dict(by_basis),
        "releaseCostMedianByBasis": {b: _r(statistics.median(v)) for b, v in rel.items() if v},
        "releaseCostRangeByBasis": {b: [_r(min(v)), _r(max(v))] for b, v in rel.items() if v},
        "byPositionAndBasis": dict(sorted(pos_basis.items())),
        "scarcityMultipliersUsed": {str(k): v for k, v in sorted(mults.items())},
        "eccZero": sum(1 for d in drops if d["ecc"] == 0),
        "justAcquiredFillerCut": sum(1 for d in drops if d["acquired"]),
        "cheaperJustAcquiredPieceExistedButWasNotCut": sum(
            1 for d in drops if d["cheaperAcquiredUncut"]
        ),
        "cheaperLegalSwapExists": sum(1 for d in drops if d["cheaperLegalSwapExists"]),
        "cheaperCandidatesAllLineupProtected": sum(1 for d in drops if d["cheaperOnlyIllegal"]),
    }


def examples(results, limit: int = 6) -> list[dict]:
    out = []
    picked = 0
    for rec in results:
        s0 = rec["steps"][0]
        if not any(
            st["d"] and _sgn(st["aoOrd"] or 0) != _sgn(s0["aoOrd"] or 0)
            and _sgn(st["tcOrd"] or 0) < _sgn(s0["tcOrd"] or 0)
            for st in rec["steps"][1:]
        ):  # fmt: skip
            continue
        s = rec["s"]
        steps = []
        for st in rec["steps"][1:]:
            if not st["d"]:
                continue
            pool = st["pool"]

            def names(key, _st=st, _pool=pool):
                idx = _st["idx"].get(key) or []
                return [
                    f"{_pool[i]['name']} ({_pool[i]['pos'] or '?'}, "
                    + ("unpriced" if _pool[i]["value"] is None else f"{_pool[i]['value']:.0f}")
                    + (", just acquired" if _pool[i]["acquired"] else "")
                    + f"; release {_pool[i]['release']:.0f})"
                    for i in idx
                ]

            steps.append({
                "fillersReceived": st["k"],
                "fillerVaCredit": st["gap"] - s0["gap"],
                "ordinal_assetOnly": st["aoOrd"],
                "prodCuts": names("PROD"),
                "prodCharged": st["prodCharged"],
                "ordinal_prod": st["tcOrd"],
                "v1Cuts": names("V1"),
                "chargeByVariant": {v: _r(c) for v, c in st["charges"].items()},
                "ordinalByVariant": {v: variant_ord(st, v) for v in VARIANTS},
            })  # fmt: skip
        out.append({
            "send": f"{s['x']['name']} ({s['x']['pos']}, {s['x']['value']:.0f})",
            "receive": f"{s['y']['name']} ({s['y']['pos']}, {s['y']['value']:.0f})",
            "fillers": [f"{f['name']} ({f['pos']}, {f['value']:.0f})" for f in s["fill"]],
            "ordinal_k0": s0["aoOrd"],
            "steps": steps,
        })  # fmt: skip
        picked += 1
        if picked >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--archive", default=ARCHIVE_DEFAULT)
    ap.add_argument("--war-room-opps", type=int, default=5)
    ap.add_argument(
        "--band-basis",
        choices=("current", "v1_legacy"),
        default="current",
        help="current = the engine as it now is (default); v1_legacy = reproduce the recorded "
        "(larger ADJUSTED side) evidence",
    )
    ap.add_argument(
        "--csv-rev",
        default=None,
        help="git revision whose " + ", ".join(S.RPB.CSV_TREE_PATHS) + " the contract build "
        "reads (default: the working tree); with --archive this pins the whole board",
    )
    args = ap.parse_args()
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "the incumbent must be the active model"
    with contextlib.ExitStack() as stack:
        csv_root, csv_provenance = stack.enter_context(S.RPB.csv_tree(args.csv_rev))
        stack.enter_context(S.RPB.pinned_contract_builds(csv_root))
        if args.band_basis == "v1_legacy":
            stack.enter_context(S.P1.legacy_v1_denominator())
        return _run(args, csv_provenance)


def _run(args, csv_provenance: dict) -> int:
    t0 = time.time()
    member, blob, raw = load_archive(args.archive)
    sha = hashlib.sha256(blob).hexdigest()
    ctx = S.build_context(raw)
    S.classify_assets(ctx)
    board_sha = S.RPB.built_board_sha256(ctx["rows"])
    diag = run_diagnostic(ctx, args.war_room_opps, S.SEED + 2)
    results = diag["results"]
    variants = {v: classify_flips(results, v) for v in VARIANTS}
    prod = variants["PROD"]
    rm, rt = diag["repro"]
    result = {
        "purpose": "RESEARCH ONLY, EXPLORATORY.  Owner question: is Team Context already charging "
        "too much for forced drops (War Room, /api/trade/analyze, Team Context ON, production "
        "geom_q078_v1)?  Shadow counterfactuals are recomputed inside the script; no production "
        "code, config, value or served path changed.",
        "generatedBy": "scripts/low_value_asset_forced_drop_diagnostic.py",
        "activeModelAtRun": pm.active_model_id(),
        "board": {
            "archive": args.archive,
            "member": member,
            "sha256": sha,
            "matchesShadowReplayBoard": sha == ARCHIVE_SHA256,
            "builtBoardSha256": board_sha,
            "csvTree": {"paths": list(S.RPB.CSV_TREE_PATHS), **csv_provenance},
        },  # fmt: skip
        "codeSha": S.P1._git_sha(),
        "bandBasis": {
            "basis": args.band_basis,
            "receiptOfOwnerInForce": fairness_bands.receipt(),
            "base": "the band base the production lens used (largerPackageUtility) for PROD and "
            "every variant; under v1_legacy the engine ran inside legacy_v1_denominator() "
            "(the larger ADJUSTED side)",
        },
        "design": "identical to shadow_replay.json S5d_warRoomTeamContext (same archive, seed "
        "SEED+2, sampling loop verbatim, 5 opponents per roster); every dynasty_main roster at "
        "the 58 cap sends a genuine starter X (2,500-6,500) for Y at 86-97% of X, then receives "
        "1-3 of the opponent's expendable fillers",
        "reproduction": {
            "samples": len(results),
            "sweetenedSteps": sum(len(r["steps"]) - 1 for r in results),
            "fillerFlipsAssetOnly": prod["flips"],
            "neutralised": prod["neutralised"],
            "overCorrected": prod["overCorrected"],
            "surviving": prod["surviving_underCorrected"],
            "matchesShadowReplay_133_85_43_5": (
                prod["flips"],
                prod["neutralised"],
                prod["overCorrected"],
                prod["surviving_underCorrected"],
            )
            == (133, 85, 43, 5),
            "productionCutSetReconstructedExactly": f"{rm}/{rt} steps with drops",
        },  # fmt: skip
        "inputs": {
            "waiverValueByPosition": {k: _r(v) for k, v in sorted(diag["waiver"].items())},
            "pricedBoardFloorByPosition": {k: _r(v) for k, v in sorted(diag["floor"].items())},
            "scarcityMultiplier": diag["scarcity"],
            "scarcityByPosition": diag["scarcityByPosition"],
        },
        "forcedDrops_production": drop_summary(diag["drops"]),
        "cutsChosenByCheapestVariants": cut_summary(diag["cuts"]),
        "overCorrectionAttribution": attribute(results),
        "counterfactuals": variants,
        "variantDefinitions": {
            "PROD": "production: trade_decision._objective_value charges "
            "rosterCapacity.forcedDropReleaseCost = sum over the ladder's drops of base x scarcity",
            "V1_cheapestRelease": "cut set = lineup-legal set of minimum total release cost over the "
            "whole post-trade roster (incoming pieces included); costs unchanged",
            "V2a_unpricedExcluded": "production cut set; an unpriced (assumedWaiver) drop charges 0 "
            "(the roster_capacity.forced_drop_cost rule used by the Trade Finder)",
            "V2b_unpricedBoardFloor": "production cut set; an unpriced drop charges min(waiver, "
            "lowest priced board value at his position) x scarcity",
            "V3a_cheapest_unpricedExcluded": "V1 selection with V2a costs",
            "V3b_cheapest_unpricedBoardFloor": "V1 selection with V2b costs",
            "V4_packageConsistent": "receiver chooses the legal cut set maximising its net: cutting "
            "a just-acquired filler removes it from the package (trade re-scored by the production "
            "market lens without it) instead of charging raw value x scarcity; other cuts as V3b",
        },
        "examples": examples(results),
        "localLimit": "Component B (roster-utility / lineup lens) needs the box-local projection "
        "snapshot and is NOT_ENOUGH_EVIDENCE locally; only Component A (VA gap minus forced "
        "release) is measured.  Fairness bands use the base the production lens took from the "
        "fairness-band owner for every variant (v1_legacy: the larger adjusted side).",
        "elapsedSec": round(time.time() - t0, 1),
    }
    assert pm.active_model_id() == pm.GEOM_Q078_V1
    S.P2.assert_aggregate_only({k: v for k, v in result.items() if k not in ("board", "codeSha")})
    S.P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "reproduction": result["reproduction"],
                      "counterfactuals": variants}, indent=1))  # fmt: skip
    return 0


if __name__ == "__main__":
    sys.exit(main())
