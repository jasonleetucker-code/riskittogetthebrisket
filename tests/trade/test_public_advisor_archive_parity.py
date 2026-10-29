"""Brisket Trade Advisor ⇄ private engine parity on a REAL archived board.

Same claim as ``test_public_advisor_parity.py`` (spec I11), on the newest
complete archived scrape: real rosters, IDP families, owned picks with
canonical asset ids, and 2-, 3- and 4-team trades built from them.  For every
trade and every participating team:

* the public per-team result == ``analyze_trade_n``'s ``fairness.state`` in
  ``team_context`` mode (posture seam fixed) AND in ``asset_only`` mode;
* the public overall == the private ``summary.fairnessOverall``.

The archive predates the scraper's roster-source stamp, so the contract is
stamped live here (otherwise every team is correctly UNABLE, SD-7).
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.trade import analyze_service, public_advisor, trade_ledger
from tests.api import trade_advisor_support as S

_PUBLIC = {"FAIR": "FAIR", "NOT_FAIR": "NOT_FAIR", "UNABLE": "UNABLE_TO_DETERMINE"}
LEAGUE = "dynasty_main"


@pytest.fixture(scope="module")
def archive():
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    contract = build_api_data_contract(copy.deepcopy(payload))
    contract.setdefault("meta", {})["leagueKey"] = LEAGUE
    contract["sleeper"]["rosterSource"] = "live"
    contract["sleeper"]["rosterFetchedAt"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    reg = json.loads((S.REPO / "config" / "leagues" / "registry.json").read_text(encoding="utf-8"))
    entry = next(lg for lg in reg["leagues"] if lg["key"] == LEAGUE)
    settings = entry.get("rosterSettings") or {}
    trade_ledger.clear_snapshot_memo()
    snap = trade_ledger.snapshot_for(contract, league_key=LEAGUE, roster_settings=settings)
    return contract, snap


def _real_trades(contract):
    teams = [t for t in contract["sleeper"]["teams"] if t.get("playerIds")]
    teams.sort(key=lambda t: int(t["roster_id"]))
    rows = {str(r.get("playerId")): r for r in contract["playersArray"] if r.get("playerId")}

    def pick_player(team, positions, rank=0):
        cands = [
            rows[p]
            for p in team["playerIds"]
            if p in rows
            and rows[p].get("position") in positions
            and (rows[p].get("rankDerivedValue") or 0) > 0
        ]
        cands.sort(key=lambda r: (-(r.get("rankDerivedValue") or 0), str(r.get("playerId"))))
        return f"p:{cands[rank]['playerId']}" if len(cands) > rank else None

    def pick(team):
        return next((d["assetId"] for d in team.get("pickDetails") or [] if d.get("assetId")), None)

    off = ("QB", "RB", "WR", "TE")
    a, b, c, d = (teams[i] for i in range(4))
    ra, rb, rc, rd = (int(t["roster_id"]) for t in (a, b, c, d))
    out = []
    out.append(
        (
            "2: offense swap",
            (ra, rb),
            [(pick_player(a, off), ra, rb), (pick_player(b, off), rb, ra)],
        )
    )
    for fam in ("DL", "LB", "DB"):
        out.append(
            (
                f"2: IDP {fam}",
                (ra, rb),
                [(pick_player(a, (fam,)), ra, rb), (pick_player(b, (fam,)), rb, ra)],
            )
        )
    out.append(
        (
            "2: pick for player",
            (ra, rb),
            [(pick(a), ra, rb), (pick_player(b, off, 3), rb, ra)],
        )
    )
    out.append(
        (
            "3: circular offense",
            (ra, rb, rc),
            [
                (pick_player(a, off, 2), ra, rb),
                (pick_player(b, off, 2), rb, rc),
                (pick_player(c, off, 2), rc, ra),
            ],
        )
    )
    out.append(
        (
            "3: players and picks, one-to-many",
            (ra, rb, rc),
            [
                (pick_player(a, off, 1), ra, rb),
                (pick_player(a, ("LB",), 1), ra, rc),
                (pick(b), rb, ra),
                (pick_player(c, off, 4), rc, ra),
            ],
        )
    )
    out.append(
        (
            "4: circular mixed",
            (ra, rb, rc, rd),
            [
                (pick_player(a, off, 5), ra, rb),
                (pick_player(b, ("DL",), 0), rb, rc),
                (pick(c), rc, rd),
                (pick_player(d, off, 5), rd, ra),
            ],
        )
    )
    return [(n, t, legs) for n, t, legs in out if all(leg[0] for leg in legs)]


def test_archive_public_fairness_equals_the_private_engine(archive, monkeypatch):
    from src.api import trade_simulator

    contract, snap = archive
    monkeypatch.setattr(
        trade_simulator,
        "league_posture_bundle",
        lambda *_a, **_k: ({}, {}, {"available": False, "unavailableReason": "test"}),
    )
    policy = public_advisor.public_policy(max_teams=4, max_legs=128)
    trades = _real_trades(contract)
    assert {len(t) for _n, t, _l in trades} == {2, 3, 4}
    results = set()
    for name, teams, legs in trades:
        ledger = public_advisor.validate(
            snap, perspective=teams[0], teams=list(teams), legs=legs, policy=policy
        )
        public = public_advisor.evaluate(snap, ledger)
        for mode in ("team_context", "asset_only"):
            private = analyze_service.analyze_trade_n(
                snap, ledger, mode=mode, counterfactuals=False
            )
            for row in public.teams:
                state = private["teams"][row.roster_id]["fairness"]["state"]
                assert row.result == _PUBLIC[state], (name, mode, row.roster_id)
            overall = private["summary"]["fairnessOverall"]["state"]
            assert public.overall.result == _PUBLIC[overall], (name, mode)
        results |= {t.result for t in public.teams}
    # A real board decides real trades: not everything is UNABLE.
    assert results & {"FAIR", "NOT_FAIR"}, results
