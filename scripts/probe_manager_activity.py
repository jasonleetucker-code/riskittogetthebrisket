#!/usr/bin/env python3
"""READ-ONLY live probe of Manager Intelligence activity (Batches B1 + B2 + B3).

Runs ``build_manager_activity`` against REAL Sleeper for one username and
prints a short summary: counts, coverage, and the first trades /
acquisitions / feed events.  Not a test and never run in CI — the
deterministic, fixture-based tests are ``tests/intel/test_manager_activity.py``.
The workstream requires one such probe per batch, recorded in the PR.

It only issues GETs against Sleeper's public API.  Values are priced from the
newest local contract export when one is present (``--contract``); otherwise
every value is ``None`` (labelled ``board_unavailable``), which is the
honest answer without a board.

    python scripts/probe_manager_activity.py jnesselhauf --window 90d
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.intel import manager_activity  # noqa: E402


def _load_contract(path: str | None) -> dict | None:
    """A contract JSON (``playersArray``) as-is, or a raw scraper export
    (``exports/latest/dynasty_data_*.json``) built through the ONE live
    pipeline, ``data_contract.build_api_data_contract``."""
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"contract unreadable ({exc}); values will be None", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("playersArray"):
        return data
    if data.get("players"):
        from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

        return build_api_data_contract(data)
    return None


def _asset(a: dict) -> str:
    name = a.get("name") or a.get("label") or a.get("playerId")
    value = a.get("value")
    return f"{name} ({value if value is not None else '—'}{'' if value is not None else ': ' + str(a.get('valueReason'))})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("username")
    parser.add_argument("--window", default="30d", choices=sorted(manager_activity.WINDOWS))
    parser.add_argument("--season", default=None)
    parser.add_argument("--league", default=None)
    parser.add_argument(
        "--contract",
        default=None,
        help="contract JSON (playersArray) or a raw export to build one from",
    )
    parser.add_argument("--json", action="store_true", help="dump the whole payload")
    args = parser.parse_args()

    out = manager_activity.build_manager_activity(
        args.username,
        contract=_load_contract(args.contract),
        window=args.window,
        season=args.season,
        league_id=args.league,
    )
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0
    print(
        f"status={out.get('status')} season={out.get('season')} window={out.get('windowApplied')}"
    )
    if out.get("status") not in ("ok", "partial"):
        return 1
    m = out["manager"]
    cov = out["coverage"]
    print(f"manager={m['username']} ({m['displayName']}) userId={m['userId']}")
    print(
        f"leagues={len(cov['leagues'])} legs={cov['legsRequested']} calls={cov['callsSpent']}/"
        f"{cov['callBudget']} budgetExhausted={cov['budgetExhausted']} truncated={cov['truncated']}"
    )
    print(f"excluded={cov['excluded']}")
    for c in cov["leagues"]:
        if c.get("rosterHeld") is False:
            continue
        print(
            f"  {c['name']!s:40.40} tx={c['transactions']:<12} drafts={c['drafts']:<12} "
            f"weeks ok/failed={c['weeksFetched']}/{c['weeksFailed']}"
        )
    print(
        f"trades={len(out['trades'])} acquisitions={len(out['acquisitions'])} "
        f"feed={len(out['feed'])} model={out['packageModel']['id']}"
    )
    for t in out["trades"][:3]:
        print(
            f"\nTRADE {t['id']} {t['leagueName']} {t['season']} wk{t['week']} at={t['occurredAt']}"
        )
        print(f"  attribution={t['attribution']}")
        for s in t["sides"]:
            gets = [_asset(a) for a in (*s["playersIn"], *s["picksIn"])]
            faab = f" +${s['faabIn']} FAAB" if s.get("faabIn") is not None else ""
            tag = " (manager)" if s["isManager"] else ""
            print(f"  {s['displayName']}{tag} gets: {', '.join(gets) or '—'}{faab}")
            print(f"    in={s['incomingValue']} out={s['outgoingValue']}")
        pc = t["packageComparison"]
        print(f"  package={pc.get('manager') if pc.get('available') else pc}")
        print(f"  atTime={t['atTime']['manager']}  aging={t['aging']['manager']}")
    for a in out["acquisitions"][:3]:
        print(
            f"\nACQ {a['method']} {_asset(a['player'])} {a['leagueName']} at={a['occurredAt']} "
            f"faab={a['faabBid']} draft={a['draft']} still={a['stillRostered']} "
            f"slot={a['currentSlot']} later={a['subsequent']['state']} "
            f"gaveUp={[_asset(g) for g in a['gaveUp']]}"
        )
    for f in out["feed"][:5]:
        print(
            f"FEED {f['id']} {f['kind']} {f['leagueName']} +{[_asset(x) for x in f['added']]} "
            f"-{[_asset(x) for x in f['dropped']]} faab={f['faabBid']} attr={f['attribution']['basis']}"
        )
    a = out["analytics"]
    print(
        f"\nanalytics: byMethod={a['byMethod']} byPosition={a['byPosition']} "
        f"addsVsDrops={a['addsVsDrops']} repeat={len(a['repeatTargets'])} "
        f"rookies={a['rookies']['count']} idp={a['idp']['count']}"
    )
    _print_draft_capital(out.get("draftCapital") or {})
    _print_tendencies(out.get("tendencies") or {})
    return 0


def _print_draft_capital(dc: dict) -> None:
    """Batch B3: picks held per league, pick movement."""
    if not dc.get("available"):
        print(f"\ndraftCapital: unavailable ({dc.get('reason')})")
        return
    print(f"\ndraftCapital totals={dc.get('totals')}")
    for e in dc.get("leagues") or []:
        years = e.get("draftYears") or {}
        print(
            f"  {e.get('name')!s:40.40} ownership={e.get('pickOwnershipState')}"
            f"/{e.get('pickOwnershipReason')} coverage={e.get('coverage')} "
            f"held={years.get('heldSeasons')} retired={years.get('retiredSeasons')} draftComplete={years.get('draftCompleteSeasons')} "
            f"evidence={years.get('evidence')} rounds={e.get('rounds')}({e.get('roundsSource')})"
        )
        if e.get("picks") is None:
            continue
        print(
            f"    counts={e['counts']} pricedValue={e['pricedValue']} "
            f"priced/unpriced={e['pricedPickCount']}/{e['unpricedPickCount']} "
            f"unpricedReasons={e['unpricedReasons']}"
        )
        for p in e["picks"]:
            origin = "own" if p["own"] else f"from {p.get('originOwnerName')}"
            print(f"    HELD {_asset(p)} [{origin}] basis={p.get('valueBasis')}")
        for p in e["ownPicksTradedAway"]:
            print(f"    AWAY {p['label']} -> {p.get('currentOwnerName')}")
    mv = dc.get("movements") or {}
    print(f"  movements acquired={mv.get('acquired')} sent={mv.get('sent')}")
    for r in (mv.get("rows") or [])[:6]:
        print(
            f"    {r['direction']:8} {_asset(r['pick'])} {r['leagueName']} at={r['occurredAt']} "
            f"with={r['counterparty'].get('displayName')} stillHeld={r['stillHeld']}"
            f"{'' if r['stillHeldReason'] is None else ' (' + r['stillHeldReason'] + ')'}"
        )


def _print_tendencies(t: dict) -> None:
    if not t:
        return

    def _n(block: dict) -> str:
        return f"n={block['n']}{'' if block['sufficientSample'] else ' INSUFFICIENT'}"

    print(
        f"\ntendencies window={t['window']} trades={t['tradeCount']} "
        f"excludedUncertain={t['excludedUncertain']} minSample={t['minSample']} ({t['minSampleBasis']})"
    )
    print(f"  pickPlayer {_n(t['pickPlayer'])} {t['pickPlayer']['counts']}")
    print(f"  pieces {_n(t['pieces'])} {t['pieces']['counts']} shapes={t['pieces']['shapes']}")
    for name in ("positions", "ages"):
        block = t[name]
        rows = " ".join(
            f"{r['key']}:+{r['acquired']['count']}/-{r['sent']['count']}" for r in block["rows"]
        )
        print(f"  {name} {_n(block)} {rows}")


if __name__ == "__main__":
    raise SystemExit(main())
