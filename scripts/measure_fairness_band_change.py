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
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections import Counter
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
from src.valuation_math.package_model import adjusted_pair_totals  # noqa: E402

IDP = {"DL", "LB", "DB", "DE", "DT", "CB", "S", "EDGE", "IDP"}
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
    gap = r_adj - g_adj
    return {
        # unequal piece counts: one side consolidates
        "consolidation": len(give_vals) != len(recv_vals),
        "larger": round(larger),
        "gap": round(gap),
        "relativePct": round(abs(gap) / larger * 100, 2) if larger > 0 else None,
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
            with old_bands():
                old = real(sending, receiving)
            key = (tuple(sorted(sending)), tuple(sorted(receiving)))
            if key not in rec.seen:
                assets = [*last.get("give", []), *last.get("receive", [])]
                rec.seen[key] = {
                    "new": rec._ok(new),
                    "old": rec._ok(old),
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
        rows = sorted((src[k] for k in keys), key=lambda r: -abs(r["character"]["gap"]))
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
            ctx = old_bands() if mode == "old" else contextlib.nullcontext()
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
        with old_bands():
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
            with old_bands():
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
        with old_bands():
            old = {x["key"]: x for x in run(team)}
        for k in new.keys() & old.keys():
            kept += 1
            if new[k]["rank"] != old[k]["rank"]:
                rank_moved += 1
            if new[k]["fairness"] != old[k]["fairness"]:
                labels[f"{old[k]['fairness']}->{new[k]['fairness']}"] += 1
                relabel_rows.append(_sugg_character(new[k], by_key))
        for k in new.keys() - old.keys():
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
        for k in old.keys() - new.keys():
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--export", default="exports/latest/dynasty_data_2026-10-17.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
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


if __name__ == "__main__":
    raise SystemExit(main())
