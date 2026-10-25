"""Measure what the TC-C fairness-band change does on real data (read-only).

Owner decision 3 (2026-10-18) replaced the market lens's absolute 256 / 769
band (and the suggestions badge / equalizer's) with the ONE fairness-band owner
(``src/valuation_math/fairness_bands.py``: relative to the larger ADJUSTED side,
absolute minimum 250, PROVISIONAL).  That changes which trades Best Offers and
the package builder accept (``analyze_trade.equity_verdict``) and the
suggestions' badges and ranking.  This script measures it instead of assuming
"no test broke" is evidence.

Method (nothing is written anywhere but ``--out``):

* rebuild the canonical board from a committed export (``exports/latest``);
* use that export's own ``sleeper.teams`` (dynasty_main's 12 rosters);
* run each surface twice -- NEW bands (the owner as committed) and OLD bands
  (``fairness_bands.classify`` monkeypatched to the retired absolute rule:
  fair < 256, slight < 769, otherwise unfair -> even / lean / stretch);
* additionally record, inside the NEW run, every candidate the engines judged
  under BOTH rules, so flips are counted per candidate, not inferred.

Asset-only mode (``use_team_context=False``) is used for Best Offers and the
package builder: the band only enters through ``equity_verdict``, which Team
Context does not change, and Asset-only needs no gameplan bundle.

Usage::

    python scripts/measure_fairness_band_change.py \
        --export exports/latest/dynasty_data_2026-10-17.json \
        --out docs/trade/tc-c-fairness-band-impact/results.json

``--compare v1-v2`` (fairness_bands_v2, owner decisions 2026-10-20) measures
the denominator change instead: OLD = v1's base, the larger ADJUSTED side
(:func:`v1_basis` swaps ``fairness_bands.larger_package_utility``, which every
consumer reads its base through); NEW = the committed owner (larger PACKAGE
UTILITY).  Same cut points, same floor, same gap.  Inputs are pinned to a git
revision (``--pin-rev``) so the run is reproducible after the board moves::

    python scripts/measure_fairness_band_change.py --compare v1-v2 \
        --pin-rev 1511ca1d08 --export exports/latest/dynasty_data_2026-10-20.json \
        --out docs/trade/fairness-bands-v2-impact/results.json

It reports (a) the real own-league trades (per-team results), (b) a synthetic
grid (1-for-1, deep packages, picks R4-R6, IDP), (c) each live consumer -- the
private Asset-Only verdict, the /trade meter (through the JS library itself,
``scripts/measure_fairness_band_meter.mjs``), Best Offers, the Package Builder
and the suggestions badge -- and (d) League Hub trade-history grades that
disagree with v2 ``fair`` (OD-F6 input; the history grade is not changed).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.data_contract import build_api_data_contract  # noqa: E402
from src.trade import analyze_trade as at  # noqa: E402
from src.trade import best_offers as bo  # noqa: E402
from src.trade import package_builder as pb  # noqa: E402
from src.trade import suggestions as sg  # noqa: E402
from src.valuation_math import fairness_bands as fb  # noqa: E402
from src.valuation_math import package_model  # noqa: E402
from src.valuation_math.package_model import adjusted_pair_totals  # noqa: E402

IDP = {"DL", "LB", "DB", "DE", "DT", "CB", "S", "EDGE", "IDP"}
#: The committed (v2) denominator, held before any context swaps it.
REAL_LARGER_PACKAGE_UTILITY = fb.larger_package_utility
#: "Small package" for this report: the larger adjusted side is under 3,000
#: canonical points (roughly one mid-tier starter).  A reporting cut only.
SMALL_PACKAGE = 3000


def _old_classify(gap: float, larger_side: float) -> dict[str, Any]:
    a = abs(float(gap))
    level = "fair" if a < 256 else "slight" if a < 769 else "unfair"
    return {"level": level, "label": fb.LABELS[level], "absoluteGap": a, "relativePct": None}


@contextlib.contextmanager
def old_bands():
    real = fb.classify
    fb.classify = _old_classify
    try:
        yield
    finally:
        fb.classify = real


#: What the OLD side of a comparison runs under.  ``--compare tcc`` (the
#: default, the original TC-C measurement): the retired absolute band and Best
#: Offers' band-win-only rule.  ``--compare v1-v2``: fairness_bands_v1's
#: denominator (:func:`v1_basis`) with everything else as committed.  Bound in
#: :func:`main`.
OLD: dict[str, Any] = {}


@contextlib.contextmanager
def old_rules():
    """The retired rules as a whole: the absolute band AND Best Offers' old
    qualification, which had no meaningful-gain path (a band win only).  The
    NEW Best Offers rule is ``best_offers_qualification`` (owner decision
    2026-10-18, Option B)."""
    real_q = bo.best_offers_qualification
    bo.best_offers_qualification = lambda eq: real_q(eq) if eq["win"] else None
    try:
        with old_bands():
            yield
    finally:
        bo.best_offers_qualification = real_q


def _asset_tags(assets: list[Any]) -> set[str]:
    tags = set()
    for a in assets:
        pos = str(getattr(a, "position", "") or "").upper()
        if getattr(a, "is_pick", False) or pos == "PICK":
            tags.add("pick")
        elif pos in IDP:
            tags.add("idp")
        else:
            tags.add("offense")
    return tags


def _character(give_vals: list[float], recv_vals: list[float], tags: set[str]) -> dict[str, Any]:
    g_adj, r_adj, _, _ = adjusted_pair_totals(give_vals, recv_vals)
    larger = max(g_adj, r_adj)
    larger_u = REAL_LARGER_PACKAGE_UTILITY(give_vals, recv_vals)
    gap = r_adj - g_adj
    return {
        # unequal piece counts: one side consolidates
        "consolidation": len(give_vals) != len(recv_vals),
        "larger": round(larger),
        "gap": round(gap),
        "relativePct": round(abs(gap) / larger * 100, 2) if larger > 0 else None,
        "relativePctUtility": round(abs(gap) / larger_u * 100, 2) if larger_u > 0 else None,
        "small": larger < SMALL_PACKAGE,
        "idp": "idp" in tags,
        "pick": "pick" in tags,
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out = {"count": len(rows)}
    for k in ("small", "idp", "pick", "consolidation"):
        out[k] = sum(1 for r in rows if r[k])
    rel = sorted(r["relativePct"] for r in rows if r["relativePct"] is not None)
    if rel:
        out["relativePctMedian"] = rel[len(rel) // 2]
        out["relativePctRange"] = [rel[0], rel[-1]]
    gaps = sorted(abs(r["gap"]) for r in rows)
    if gaps:
        out["absGapRange"] = [gaps[0], gaps[-1]]
    return out


class _Recorder:
    """Wrap an engine's ``equity_verdict`` to judge each candidate under both
    rules while the engine runs under the NEW rule."""

    def __init__(self, module: Any, accept: str):
        self.module = module
        self.accept = accept  # "win" (best offers) or "not_opposes" (package builder)
        self.seen: dict[tuple, dict[str, Any]] = {}

    def _ok(self, v: dict[str, Any]) -> bool:
        return bool(v["win"]) if self.accept == "win" else v["direction"] != "opposes"

    def __enter__(self):
        real = at.equity_verdict
        rec = self
        # Both engines call finder.plausibility_check(give, receive) right
        # before equity_verdict on the same pair: stash the assets so each
        # judged candidate can be characterised (IDP / picks), not just valued.
        from src.trade import finder as _finder

        real_plaus = _finder.plausibility_check
        last: dict[str, Any] = {}

        def plaus(give, receive, *a, **kw):
            last["give"], last["receive"] = list(give), list(receive)
            return real_plaus(give, receive, *a, **kw)

        _finder.plausibility_check = plaus
        self._finder, self._real_plaus = _finder, real_plaus

        def wrapped(sending, receiving):
            new = real(sending, receiving)
            with OLD["bands"]():
                old = real(sending, receiving)
            key = (tuple(sorted(sending)), tuple(sorted(receiving)))
            if key not in rec.seen:
                assets = [*last.get("give", []), *last.get("receive", [])]
                # Best Offers' NEW rule is its own qualification (owner
                # decision 2026-10-18, Option B: band win OR a positive gain >=
                # absoluteMinimum); the OLD rule is the retired band's win.
                new_ok = (
                    bo.best_offers_qualification(new) is not None
                    if rec.accept == "win"
                    else rec._ok(new)
                )
                rec.seen[key] = {
                    "new": new_ok,
                    "old": rec._ok(old),
                    "meaningfulGainOnly": rec.accept == "win" and new_ok and not new["win"],
                    "sending": list(sending),
                    "receiving": list(receiving),
                    "tags": _asset_tags(assets),
                }
            return new

        self.module.equity_verdict = wrapped
        self._real = real
        return self

    def __exit__(self, *exc):
        self.module.equity_verdict = self._real
        self._finder.plausibility_check = self._real_plaus


class _Qualified:
    """Capture the QUALIFIED candidates of one engine run with their pre-rerank
    ranking score.  Both engines call ``best_offers._factors`` exactly once per
    candidate that passed every hard rule (canonical rule + external
    qualification), right after ``finder.plausibility_check`` on the same pair,
    so wrapping the two identifies each qualified candidate and its assets."""

    def __init__(self, owner_of: dict[str, str]):
        self.owner_of = owner_of
        self.rows: dict[tuple, dict[str, Any]] = {}

    def __enter__(self):
        from src.trade import finder as _finder

        self._finder = _finder
        self._plaus, self._factors = _finder.plausibility_check, bo._factors
        last: dict[str, Any] = {}
        me = self

        def plaus(give, receive, *a, **kw):
            last["give"], last["receive"] = list(give), list(receive)
            return me._plaus(give, receive, *a, **kw)

        def factors(give, receive, equity, verdict, prior, *a, **kw):
            out = me._factors(give, receive, equity, verdict, prior, *a, **kw)
            key = (
                tuple(sorted(str(x.asset_id or x.name) for x in give)),
                tuple(sorted(str(x.asset_id or x.name) for x in receive)),
            )
            opp = sorted({me.owner_of.get(x.name, "?") for x in receive})
            me.rows[key] = {
                "group": ",".join(opp),
                "score": bo._score(out, prior["weights"], {}),
                "give": [x.name for x in give],
                "receive": [x.name for x in receive],
                "character": _character(
                    [float(x.model_value) for x in give],
                    [float(x.model_value) for x in receive],
                    _asset_tags([*give, *receive]),
                ),
                "magnitude": equity.get("magnitude"),
            }
            return out

        _finder.plausibility_check = plaus
        bo._factors = factors
        return self

    def __exit__(self, *exc):
        self._finder.plausibility_check = self._plaus
        bo._factors = self._factors


def _compare_qualified(
    new: dict[tuple, dict], old: dict[tuple, dict], examples: int = 12
) -> dict[str, Any]:
    """Qualification (kept / dropped / added) SEPARATELY from ranking (order
    changes among candidates qualified under both)."""
    kept = new.keys() & old.keys()
    dropped = old.keys() - new.keys()
    added = new.keys() - old.keys()
    groups: dict[tuple, list[tuple]] = {}
    for k in kept:
        groups.setdefault((new[k]["me"], new[k]["group"]), []).append(k)
    moved_groups = moved_cands = 0
    for g, keys in groups.items():
        order_new = sorted(keys, key=lambda k: (-new[k]["score"], k))
        order_old = sorted(keys, key=lambda k: (-old[k]["score"], k))
        if order_new != order_old:
            moved_groups += 1
            moved_cands += sum(1 for a, b in zip(order_new, order_old) if a != b)
    top_changed = 0
    for g in {(new[k]["me"], new[k]["group"]) for k in new} | {
        (old[k]["me"], old[k]["group"]) for k in old
    }:
        bn = max(
            (k for k in new if (new[k]["me"], new[k]["group"]) == g),
            key=lambda k: (new[k]["score"], k),
            default=None,
        )
        bo_ = max(
            (k for k in old if (old[k]["me"], old[k]["group"]) == g),
            key=lambda k: (old[k]["score"], k),
            default=None,
        )
        if bn != bo_:
            top_changed += 1

    def ex(keys, src):
        rows = [
            src[k] for k in sorted(keys, key=lambda k: (-abs(src[k]["character"]["gap"]), repr(k)))
        ]
        return [
            {
                "me": r["me"],
                "opponent": r["group"],
                "give": r["give"],
                "receive": r["receive"],
                **{
                    k: r["character"][k]
                    for k in (
                        "gap",
                        "larger",
                        "relativePct",
                        "small",
                        "idp",
                        "pick",
                        "consolidation",
                    )
                },
            }
            for r in rows[:examples]
        ]

    return {
        "qualification": {
            "qualifiedOld": len(old),
            "qualifiedNew": len(new),
            "kept": len(kept),
            "dropped": _summarize([old[k]["character"] for k in dropped]),
            "added": _summarize([new[k]["character"] for k in added]),
            "droppedExamples": ex(dropped, old),
            "addedExamples": ex(added, new),
        },
        "ranking": {
            "groupsWithBothQualified": len(groups),
            "groupsWhoseOrderChanged": moved_groups,
            "positionsChanged": moved_cands,
            "groupsWhoseTopCandidateChanged": top_changed,
        },
    }


def _owner_map(teams) -> dict[str, str]:
    return {p: t["name"] for t in teams for p in t.get("players") or []}


def measure_qualification(players, teams, contract) -> dict[str, Any]:
    """Best Offers (one card per opponent) and the package builder ("sell a
    player" for each team's top three), qualification vs ranking."""
    owner_of = _owner_map(teams)
    board = {
        n: v
        for n, v in (
            (r.get("displayName") or r.get("canonicalName"), r.get("rankDerivedValue"))
            for r in contract.get("playersArray") or []
        )
        if n and isinstance(v, (int, float))
    }
    out = {}
    for name in ("bestOffers", "packageBuilder"):
        modes = {}
        for mode in ("new", "old"):
            rows: dict[tuple, dict] = {}
            ctx = OLD["rules"]() if mode == "old" else contextlib.nullcontext()
            with ctx:
                for team in teams:
                    me = team["name"]
                    calls = []
                    if name == "bestOffers":
                        calls.append(
                            lambda me=me: bo.build_best_offers(
                                players, me, teams, contract=contract, use_team_context=False
                            )
                        )
                    else:
                        mine = sorted(
                            (p for p in team.get("players") or [] if p in board),
                            key=lambda p: -board[p],
                        )[:3]
                        for o in mine:
                            calls.append(
                                lambda me=me, o=o: pb.build_packages(
                                    players,
                                    me,
                                    teams,
                                    contract=contract,
                                    outgoing=[o],
                                    use_team_context=False,
                                    per_opponent=True,
                                    limit=12,
                                )
                            )
                    for call in calls:
                        with _Qualified(owner_of) as q:
                            call()
                        for k, r in q.rows.items():
                            rows[(me, *k)] = {**r, "me": me}
            modes[mode] = rows
        out[name] = _compare_qualified(modes["new"], modes["old"])
    return out


def _offer_key(offer: dict[str, Any] | None) -> tuple | None:
    if not isinstance(offer, dict):
        return None
    names = lambda xs: tuple(sorted(str(x.get("name") or x.get("assetId") or x) for x in xs or []))  # noqa: E731
    return (names(offer.get("send")), names(offer.get("receive")))


def measure_best_offers(players, teams, contract) -> dict[str, Any]:
    finals: dict[str, dict] = {"new": {}, "old": {}}
    flips_gained, flips_lost = [], []
    cand = Counter()
    for team in teams:
        me = team["name"]
        with _Recorder(bo, "win") as rec:
            res = bo.build_best_offers(
                players, me, teams, contract=contract, use_team_context=False
            )
        for card in res["opponents"]:
            finals["new"][(me, card["team"])] = _offer_key(card.get("offer"))
        for v in rec.seen.values():
            cand["judged"] += 1
            if v.get("meaningfulGainOnly"):
                cand["qualifiedByMeaningfulGainOnly"] += 1
            if v["new"] and v["old"]:
                cand["winBoth"] += 1
            elif v["new"]:
                cand["winNewOnly"] += 1
            elif v["old"]:
                cand["winOldOnly"] += 1
        for v in rec.seen.values():
            if v["new"] != v["old"]:
                row = _character(v["sending"], v["receiving"], v["tags"])
                (flips_gained if v["new"] else flips_lost).append(row)
        with OLD["rules"]():
            res_old = bo.build_best_offers(
                players, me, teams, contract=contract, use_team_context=False
            )
        for card in res_old["opponents"]:
            finals["old"][(me, card["team"])] = _offer_key(card.get("offer"))
    pairs = set(finals["new"]) | set(finals["old"])
    tally = Counter()
    changed_examples = []
    for p in sorted(pairs):
        n, o = finals["new"].get(p), finals["old"].get(p)
        if n is None and o is None:
            tally["noOfferBoth"] += 1
        elif n == o:
            tally["sameOffer"] += 1
        elif o is None:
            tally["offerAdded"] += 1
            changed_examples.append({"pair": p, "old": None, "new": n})
        elif n is None:
            tally["offerDropped"] += 1
            changed_examples.append({"pair": p, "old": o, "new": None})
        else:
            tally["offerChanged"] += 1
            changed_examples.append({"pair": p, "old": o, "new": n})
    return {
        "cards": dict(tally),
        "cardPairs": len(pairs),
        "candidateCanonicalWin": dict(cand),
        "candidatesNowWinning": _summarize(flips_gained),
        "candidatesNoLongerWinning": _summarize(flips_lost),
        "changedCards": [
            {"me": p["pair"][0], "opponent": p["pair"][1], "old": p["old"], "new": p["new"]}
            for p in changed_examples
        ],
    }


def measure_package_builder(players, teams, contract) -> dict[str, Any]:
    """ "Sell a player": each team's three most valuable rostered players."""
    board = {
        n: v
        for n, v in (
            (r.get("displayName") or r.get("canonicalName"), r.get("rankDerivedValue"))
            for r in contract.get("playersArray") or []
        )
        if n and isinstance(v, (int, float))
    }
    flips_gained, flips_lost = [], []
    cand = Counter()
    finals = Counter()
    for team in teams:
        mine = sorted(
            (p for p in team.get("players") or [] if p in board), key=lambda p: -board[p]
        )[:3]
        for outgoing in mine:
            kwargs = dict(
                contract=contract,
                outgoing=[outgoing],
                use_team_context=False,
                per_opponent=True,
                limit=12,
            )
            with _Recorder(pb, "not_opposes") as rec:
                new = pb.build_packages(players, team["name"], teams, **kwargs)
            with OLD["bands"]():
                old = pb.build_packages(players, team["name"], teams, **kwargs)
            for v in rec.seen.values():
                cand["judged"] += 1
                if v["new"] != v["old"]:
                    row = _character(v["sending"], v["receiving"], v["tags"])
                    (flips_gained if v["new"] else flips_lost).append(row)
            nk = {_offer_key(p) for p in new.get("packages") or []}
            ok = {_offer_key(p) for p in old.get("packages") or []}
            finals["kept"] += len(nk & ok)
            finals["added"] += len(nk - ok)
            finals["dropped"] += len(ok - nk)
    return {
        "requests": sum(min(3, len(t.get("players") or [])) for t in teams),
        "packages": dict(finals),
        "candidateAccepted": dict(cand),
        "candidatesNowAccepted": _summarize(flips_gained),
        "candidatesNoLongerAccepted": _summarize(flips_lost),
    }


def measure_suggestions(teams, contract) -> dict[str, Any]:
    full = sg.build_asset_pool_from_contract(contract, ktc_top_n=0)
    pool = sg._apply_board_top_n_filter(list(full), sg.BOARD_TOP_N_FILTER)
    needs = sg.starter_needs_for_league("dynasty_main")
    by_key = {p.name: p for p in full}

    def run(team):
        others = [
            {"team_name": t["name"], "players": t.get("players") or []}
            for t in teams
            if t is not team
        ]
        res = sg.generate_suggestions_from_pool(
            roster_names=list(team.get("players") or []),
            pool=pool,
            league_rosters=others,
            starter_needs=needs,
            roster_pool=full,
            team_count=len(teams),
        )
        out = []
        for typ, items in res.items():
            if not isinstance(items, list):
                continue
            for rank, s in enumerate(items):
                if not isinstance(s, dict) or "give" not in s:
                    continue
                give = tuple(sorted(x.get("name") for x in s["give"]))
                recv = tuple(sorted(x.get("name") for x in s["receive"]))
                out.append(
                    {
                        "type": typ,
                        "key": (typ, give, recv),
                        "rank": rank,
                        "fairness": s.get("fairness"),
                        "give": give,
                        "recv": recv,
                    }
                )
        return out

    labels = Counter()
    kept = added = dropped = rank_moved = 0
    relabel_rows, drop_rows, add_rows = [], [], []
    drop_ex, add_ex = [], []
    for team in teams:
        new = {x["key"]: x for x in run(team)}
        with OLD["bands"]():
            old = {x["key"]: x for x in run(team)}
        for k in new.keys() & old.keys():
            kept += 1
            if new[k]["rank"] != old[k]["rank"]:
                rank_moved += 1
            if new[k]["fairness"] != old[k]["fairness"]:
                labels[f"{old[k]['fairness']}->{new[k]['fairness']}"] += 1
                relabel_rows.append(_sugg_character(new[k], by_key))
        for k in sorted(new.keys() - old.keys(), key=repr):
            added += 1
            add_rows.append(_sugg_character(new[k], by_key))
            add_ex.append(
                {
                    "team": team["name"],
                    "type": new[k]["type"],
                    "give": new[k]["give"],
                    "receive": new[k]["recv"],
                    "fairness": new[k]["fairness"],
                    **add_rows[-1],
                }
            )
        for k in sorted(old.keys() - new.keys(), key=repr):
            dropped += 1
            drop_rows.append(_sugg_character(old[k], by_key))
            drop_ex.append(
                {
                    "team": team["name"],
                    "type": old[k]["type"],
                    "give": old[k]["give"],
                    "receive": old[k]["recv"],
                    "fairness": old[k]["fairness"],
                    **drop_rows[-1],
                }
            )
    return {
        "kept": kept,
        "added": added,
        "dropped": dropped,
        "keptWithRankChange": rank_moved,
        "relabels": dict(labels),
        "relabelled": _summarize(relabel_rows),
        "addedCharacter": _summarize(add_rows),
        "droppedCharacter": _summarize(drop_rows),
        "droppedExamples": drop_ex,
        "addedExamples": add_ex,
    }


def _sugg_character(s: dict[str, Any], by_key: dict[str, Any]) -> dict[str, Any]:
    give = [by_key[n] for n in s["give"] if n in by_key]
    recv = [by_key[n] for n in s["recv"] if n in by_key]
    tags = _asset_tags(give + recv)
    return _character([p.display_value for p in give], [p.display_value for p in recv], tags)


def main_tcc(args: argparse.Namespace) -> int:
    OLD.update(bands=old_bands, rules=old_rules)
    raw = json.loads((REPO / args.export).read_text(encoding="utf-8"))
    contract = build_api_data_contract(raw)
    players = contract["players"]
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if len(teams) != 12:
        print(f"expected dynasty_main's 12 rosters, got {len(teams)}", file=sys.stderr)
        return 1
    result = {
        "export": args.export,
        "boardGeneratedAt": (contract.get("meta") or {}).get("generatedAt"),
        "sleeperLeagueId": (contract.get("sleeper") or {}).get("leagueId"),
        "teams": len(teams),
        "newBands": fb.receipt(),
        "oldBands": {"rule": "absolute: even < 256, lean < 769, stretch >= 769"},
        "smallPackageDefinition": f"larger adjusted side < {SMALL_PACKAGE}",
        # Hard-rule (canonical win / not-opposes) flips per judged candidate.
        "bestOffersCanonicalRule": measure_best_offers(players, teams, contract),
        "packageBuilderCanonicalRule": measure_package_builder(players, teams, contract),
        # Qualification vs ranking, owner request 2026-10-18.
        **{
            f"{k}Qualification": v
            for k, v in measure_qualification(players, teams, contract).items()
        },
        "suggestions": measure_suggestions(teams, contract),
    }
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=list) + "\n", encoding="utf-8")
    print(f"written {out}")
    return 0


# ── --compare v1-v2 (fairness_bands_v2, owner decisions 2026-10-20) ─────────

LEVEL_ORDER = {lvl: i for i, lvl in enumerate(fb.LEVELS)}
_FROM = re.compile(r"\s*\(from [^)]*\)\s*$", re.I)
_PICK = re.compile(r"^\d{4}\s")
_LATE_PICK = re.compile(
    r"(Round [456]$|Pick [456]\.\d\d$|Early [456]th$|Mid [456]th$|Late [456]th$)"
)


@contextlib.contextmanager
def v1_basis():
    """fairness_bands_v1's denominator: the larger ADJUSTED side.  Same owner,
    same cut points, same floor, same gap -- only the base differs.  Every
    consumer reads its base through ``fairness_bands.larger_package_utility``
    (or ``classify_packages``, which calls it), so swapping that one function
    re-runs every surface under v1."""

    def v1(side_a, side_b, *, model_id=None):
        a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(
            list(side_a), list(side_b), model_id=model_id
        )
        return fb.fairness_base([a_adj, b_adj])

    fb.larger_package_utility = v1
    try:
        yield
    finally:
        fb.larger_package_utility = REAL_LARGER_PACKAGE_UTILITY


def _git(rev: str, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def _pinned_json(rev: str | None, path: str) -> tuple[Any, dict[str, str]]:
    if rev:
        blob = _git(rev, "rev-parse", f"{rev}:{path}").decode().strip()
        data = json.loads(_git(rev, "show", f"{rev}:{path}"))
        return data, {"path": path, "rev": rev, "blob": blob}
    raw = (REPO / path).read_bytes()
    blob = (
        subprocess.run(
            ["git", "hash-object", "--stdin"], input=raw, capture_output=True, check=True, cwd=REPO
        )
        .stdout.decode()
        .strip()
    )
    return json.loads(raw), {"path": path, "rev": None, "blob": blob}


def _transition(old: str, new: str) -> str:
    return f"{old}->{new}"


def _stricter(old: str, new: str) -> bool:
    return LEVEL_ORDER[new] > LEVEL_ORDER[old]


def _asset_only_headline(gave: list[float], got: list[float]) -> str:
    """The private Asset-Only YES / NO for one team's packages, through the
    real ``analyze_trade`` -> ``trade_decision.decide`` path."""
    sim = {
        "receiving": [
            {"name": f"in{i}", "value": v, "confidenceBucket": "high"} for i, v in enumerate(got)
        ],
        "sending": [
            {"name": f"out{i}", "value": v, "confidenceBucket": "high"} for i, v in enumerate(gave)
        ],
        "teamContext": {"applied": False},
    }
    return at.analyze_trade(sim, counterfactuals=False)["decision"]["headline"]


def _judge(gave: list[float], got: list[float]) -> dict[str, Any]:
    """One team's packages under v1 and v2: band (equity_verdict) and the
    Asset-Only headline."""
    new = at.equity_verdict(gave, got)
    h_new = _asset_only_headline(gave, got)
    with v1_basis():
        old = at.equity_verdict(gave, got)
        h_old = _asset_only_headline(gave, got)
    return {
        "gap": new["vaAdjustedGap"],
        "v1Base": round(max(old["sendingAdjusted"], old["receivingAdjusted"]), 1),
        "v2Base": round(new["largerPackageUtility"], 1),
        "v1Level": old["band"]["level"],
        "v2Level": new["band"]["level"],
        "v1RelPct": old["band"]["relativePct"],
        "v2RelPct": new["band"]["relativePct"],
        "v1Headline": h_old,
        "v2Headline": h_new,
    }


def _tally(judged: list[dict[str, Any]]) -> dict[str, Any]:
    bands = Counter()
    heads = Counter()
    stricter = looser = 0
    for j in judged:
        if j["v1Level"] != j["v2Level"]:
            bands[_transition(j["v1Level"], j["v2Level"])] += 1
            if _stricter(j["v1Level"], j["v2Level"]):
                stricter += 1
            else:
                looser += 1
        if j["v1Headline"] != j["v2Headline"]:
            heads[_transition(j["v1Headline"], j["v2Headline"])] += 1
    return {
        "judged": len(judged),
        "bandChanged": sum(bands.values()),
        "bandStricter": stricter,
        "bandLooser": looser,
        "bandTransitions": dict(sorted(bands.items())),
        "fairToNotFair": sum(v for k, v in bands.items() if k.startswith("fair->")),
        "notFairToFair": sum(v for k, v in bands.items() if k.endswith("->fair")),
        "assetOnlyHeadlineChanged": sum(heads.values()),
        "assetOnlyHeadlineTransitions": dict(sorted(heads.items())),
    }


def _board(contract: dict[str, Any]):
    from src.api.pick_value_resolution import pick_rows_by_name, resolve_pick_label_value
    from src.utils.name_clean import normalize_player_name

    rows = contract["playersArray"]
    cdy = int(contract.get("currentDraftYear"))
    picks_by_name = pick_rows_by_name(contract)
    players: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("assetClass") in ("offense", "idp"):
            players[normalize_player_name(r.get("displayName") or "")].append(r)

    def val(r):
        v = r.get("rankDerivedValue")
        return (
            float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None
        )

    def price(label: str):
        name = _FROM.sub("", str(label)).strip()
        if _PICK.match(name):
            pv = resolve_pick_label_value(name, rows_by_name=picks_by_name, current_draft_year=cdy)
            if pv is None or pv.value is None:
                return None, "pick"
            return float(pv.value), "pick"
        cands = players.get(normalize_player_name(name)) or []
        if len(cands) != 1:
            return None, "player"
        return val(cands[0]), cands[0]["assetClass"]

    by_class: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        v = val(r)
        if v:
            by_class[r.get("assetClass")].append((str(r.get("displayName")), v))
    return price, by_class


def measure_real_trades(contract, trades) -> dict[str, Any]:
    """(a) every fully priced own-league trade, per team, plus (d) the League
    Hub trade-history grade beside the v1 / v2 band on the same quantity."""
    from src.public_league.trade_grading import HISTORY_EVEN_LABEL, grade_trade_sides

    price, _ = _board(contract)
    census = Counter()
    judged_all: list[dict[str, Any]] = []
    by_cat: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trade_fair = Counter()
    history = Counter()
    examples = []
    for t in trades:
        teams, classes, unpriced = [], set(), False
        for s in t["sides"]:
            gave, got = [], []
            for lab in s.get("gave") or []:
                v, cls = price(lab)
                classes.add(cls)
                unpriced |= v is None
                gave.append(v)
            for lab in s.get("got") or []:
                v, cls = price(lab)
                classes.add(cls)
                unpriced |= v is None
                got.append(v)
            teams.append({"team": s.get("team"), "gave": gave, "got": got})
        if unpriced:
            census["excludedUnpriced"] += 1  # never priced as 0
            continue
        census["graded"] += 1
        n = len(teams)
        cats = ["all", "multi_team" if n > 2 else "two_team"]
        if n == 2 and len(teams[0]["gave"]) == 1 and len(teams[0]["got"]) == 1:
            cats.append("1_for_1")
        if max(max(len(x["gave"]), len(x["got"])) for x in teams) >= 4:
            cats.append("deep_4plus_pieces")
        if "pick" in classes:
            cats.append("includes_pick")
        if "idp" in classes:
            cats.append("includes_idp")
        grades = grade_trade_sides([(x["got"], x["gave"]) for x in teams])
        per = []
        for x, g in zip(teams, grades):
            j = _judge(x["gave"], x["got"])
            j["team"] = x["team"]
            j["shape"] = f"{len(x['gave'])}>{len(x['got'])}"
            j["historyFair"] = g["grade"]["label"] == HISTORY_EVEN_LABEL
            per.append(j)
            judged_all.append(j)
            for c in cats:
                by_cat[c].append(j)
            history[
                f"v1:{'agree' if j['historyFair'] == (j['v1Level'] == 'fair') else 'disagree'}"
            ] += 1
            history[
                f"v2:{'agree' if j['historyFair'] == (j['v2Level'] == 'fair') else 'disagree'}"
            ] += 1
            if j["historyFair"] != (j["v2Level"] == "fair"):
                history[
                    "v2:"
                    + ("historyFair_v2NotFair" if j["historyFair"] else "historyNotFair_v2Fair")
                ] += 1
            if j["v1Level"] != j["v2Level"]:
                examples.append(
                    {
                        "date": datetime.fromtimestamp(t["timestamp"] / 1000, timezone.utc)
                        .date()
                        .isoformat(),
                        "team": x["team"],
                        "shape": j["shape"],
                        "gap": j["gap"],
                        "v1Base": j["v1Base"],
                        "v2Base": j["v2Base"],
                        "v1": f"{j['v1Level']} ({j['v1RelPct']}%)",
                        "v2": f"{j['v2Level']} ({j['v2RelPct']}%)",
                        "assetOnly": f"{j['v1Headline']} -> {j['v2Headline']}",
                        "cats": cats,
                    }
                )
        trade_fair["v1AllTeamsFair"] += all(p["v1Level"] == "fair" for p in per)
        trade_fair["v2AllTeamsFair"] += all(p["v2Level"] == "fair" for p in per)
    return {
        "census": dict(census),
        "teamResults": len(judged_all),
        "summary": _tally(judged_all),
        "byCategory": {c: _tally(js) for c, js in sorted(by_cat.items())},
        "tradeLevelFair": dict(trade_fair),
        "historyGradeVsBand": dict(sorted(history.items())),
        "examples": sorted(examples, key=lambda e: (e["date"], e["team"])),
    }


def _synthetic_pairs(by_class, seed: int = 20261020) -> dict[str, list[tuple[list, list]]]:
    """(b) the synthetic grid.  SYNTHETIC, labelled as such."""
    rng = random.Random(seed)
    q = package_model.PACKAGE_MODELS[package_model.GEOM_Q078_V1]["q"]
    grid: dict[str, list[tuple[list, list]]] = defaultdict(list)
    # 1-for-1: must be byte-identical (pinned by test; measured here too).
    levels = (300, 800, 1389, 2000, 2778, 4000, 7143, 9999)
    for big in levels:
        for pct in (0, 1, 2, 3, 3.5, 5, 8, 9, 12, 18, 25, 40):
            grid["one_for_one"].append(([big], [round(big * (1 - pct / 100), 2)]))
    # Deep packages: a stud vs k equal pieces with a fixed utility shortfall,
    # in both directions.
    for stud in (3000.0, 6000.0, 9000.0):
        for k in (2, 3, 4, 6, 8, 12):
            w = sum(q**i for i in range(k))
            for short in (0.0, 0.02, 0.03, 0.05, 0.08, 0.12, 0.18):
                for sign in (1, -1):
                    pile = [round(stud * (1 - sign * short) / w, 2)] * k
                    grid["deep_stud_vs_pile"].append(([stud], pile))

    def draw(pool, n):
        return [v for _, v in rng.sample(pool, n)]

    def near(pool, n_give, n_get, tries=60):
        give = draw(pool, n_give)
        ug = package_model.geom_utility(give, q)
        best = None
        for _ in range(tries):
            got = draw(pool, n_get)
            d = abs(package_model.geom_utility(got, q) - ug) / max(ug, 1)
            if best is None or d < best[0]:
                best = (d, got)
        return give, best[1]

    offense = by_class.get("offense") or []
    idp = by_class.get("idp") or []
    picks = by_class.get("pick") or []
    late_picks = [(n, v) for n, v in picks if _LATE_PICK.search(n)]
    shapes = ((1, 2), (2, 2), (2, 3), (1, 3), (1, 4), (2, 5), (1, 6), (3, 8))
    for name, pool in (("offense", offense), ("idp", idp), ("mixed", offense + idp + picks)):
        if len(pool) < 20:
            continue
        for g, r in shapes:
            for _ in range(60):
                grid[f"board_{name}"].append(near(pool, g, r))
    if len(late_picks) >= 8:
        for g, r in ((1, 1), (1, 2), (2, 2), (2, 3), (1, 3)):
            for _ in range(60):
                grid["picks_r4_r6"].append(near(late_picks, g, r))
    return grid


def measure_synthetic(by_class) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grid = _synthetic_pairs(by_class)
    out, pairs = {}, []
    for name, items in grid.items():
        judged = []
        ex = []
        for give, got in items:
            j = _judge(give, got)
            judged.append(j)
            pairs.append({"set": name, "gave": give, "got": got, "v2Level": j["v2Level"]})
            if j["v1Level"] != j["v2Level"] and len(ex) < 6:
                ex.append(
                    {
                        "gave": [round(v) for v in give],
                        "got": [round(v) for v in got],
                        "gap": j["gap"],
                        "v1": f"{j['v1Level']} ({j['v1RelPct']}%)",
                        "v2": f"{j['v2Level']} ({j['v2RelPct']}%)",
                        "assetOnly": f"{j['v1Headline']} -> {j['v2Headline']}",
                    }
                )
        out[name] = {**_tally(judged), "examples": ex}
    return out, pairs


def measure_meter(pairs: list[dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    """The /trade meter, through the JS library itself (node).  Side A = the
    team's gives, side B = its receipts, exactly as /trade lays a 2-team trade
    out; v1 = classifyGap on the larger ADJUSTED side, v2 = on
    sideTotalsFairnessBase.  Also checks the JS v2 band equals Python's."""
    harness = REPO / "scripts" / "measure_fairness_band_meter.mjs"
    inputs = out_dir / "meter_inputs.json"
    result = out_dir / "meter_results.json"
    inputs.write_text(json.dumps(pairs) + "\n", encoding="utf-8")
    try:
        subprocess.run(
            ["node", "--no-warnings", str(harness), str(inputs), str(result)],
            cwd=REPO,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return {"state": "not_run", "reason": repr(exc)}
    rows = json.loads(result.read_text(encoding="utf-8"))
    inputs.unlink()
    result.unlink()
    by_set: dict[str, Counter] = defaultdict(Counter)
    mismatch = []
    for p, r in zip(pairs, rows):
        c = by_set[p["set"]]
        c["judged"] += 1
        if r["v1"] != r["v2"]:
            c[_transition(r["v1"], r["v2"])] += 1
            c["changed"] += 1
        if r["v2"] != p["v2Level"]:
            mismatch.append({"set": p["set"], "js": r["v2"], "python": p["v2Level"]})
    return {
        "state": "ran",
        "bySet": {k: dict(sorted(v.items())) for k, v in sorted(by_set.items())},
        "pythonParityMismatches": len(mismatch),
        "pythonParityExamples": mismatch[:5],
    }


def main_v1_v2(args: argparse.Namespace) -> int:
    OLD.update(bands=v1_basis, rules=v1_basis)
    raw, export_pin = _pinned_json(args.pin_rev, args.export)
    trades_doc, trades_pin = _pinned_json(args.pin_rev, "data/sleeper_last_good.json")
    trades = trades_doc["rosterData"]["trades"]
    contract = build_api_data_contract(raw)
    players = contract["players"]
    teams = (contract.get("sleeper") or {}).get("teams") or []
    _, by_class = _board(contract)
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)

    real = measure_real_trades(contract, trades)
    synthetic, pairs = measure_synthetic(by_class)
    # Real two-team trades also go through the meter (the first team's view;
    # a 2-team gap and base are the same from either side).
    real_pairs = []
    price, _ = _board(contract)
    for t in trades:
        if len(t["sides"]) != 2:
            continue
        s = t["sides"][0]
        gave = [price(lab)[0] for lab in s.get("gave") or []]
        got = [price(lab)[0] for lab in s.get("got") or []]
        if any(v is None for v in gave + got):
            continue
        j = _judge(gave, got)
        real_pairs.append(
            {"set": "real_two_team", "gave": gave, "got": got, "v2Level": j["v2Level"]}
        )
    meter = measure_meter(real_pairs + pairs, out.parent)

    consumers: dict[str, Any] = {
        "state": "skipped",
        "reason": "export carries no 12-team sleeper block",
    }
    if len(teams) == 12:
        consumers = {
            "bestOffersCanonicalRule": measure_best_offers(players, teams, contract),
            "packageBuilderCanonicalRule": measure_package_builder(players, teams, contract),
            **{
                f"{k}Qualification": v
                for k, v in measure_qualification(players, teams, contract).items()
            },
            "suggestions": measure_suggestions(teams, contract),
        }
    result = {
        "compare": "fairness_bands_v1 (larger ADJUSTED side) vs fairness_bands_v2 (larger PACKAGE UTILITY)",
        "inputs": {"export": export_pin, "trades": trades_pin},
        "boardGeneratedAt": (contract.get("meta") or {}).get("generatedAt"),
        "packageModel": package_model.receipt(),
        "newBands": fb.receipt(),
        "oldBands": {
            "version": "fairness_bands_v1",
            "basis": "adjusted_package_totals",
            "note": "same cut points, floor and gap; base = max(sendAdjusted, recvAdjusted)",
        },
        "realTrades": real,
        "synthetic": synthetic,
        "meter": meter,
        "consumers": consumers,
    }
    out.write_text(json.dumps(result, indent=1, default=list) + "\n", encoding="utf-8")
    print(f"written {out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--compare", choices=("tcc", "v1-v2"), default="tcc")
    ap.add_argument("--export", default="exports/latest/dynasty_data_2026-10-17.json")
    ap.add_argument(
        "--pin-rev", default=None, help="read --export and the trade ledger from this git revision"
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    if args.compare == "v1-v2":
        return main_v1_v2(args)
    return main_tcc(args)


if __name__ == "__main__":
    raise SystemExit(main())
