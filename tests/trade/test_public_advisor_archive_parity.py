"""Brisket Trade Advisor ⇄ private engine parity on a REAL board (group A).

Same comparison as ``test_public_advisor_parity.py``, on the newest complete
archived scrape: IDP families (DL / LB / DB), owned picks in the baked label
grammar with canonical asset ids, a top offensive swap.  The private side is
the exact composition ``/api/trade/analyze`` runs (Team Context on, posture
built if missing, names + ``pickAssetIds``); the posture seam is fixed so both
paths read identical inputs.
"""

from __future__ import annotations

import copy

import pytest

from src.trade import public_advisor
from src.trade import trade_decision as td
from tests.api import trade_advisor_support as S

COMPARED = ("headline", "leaning", "deciding", "components", "confidence", "primaryReason")


@pytest.fixture(scope="module")
def archive_contract():
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    contract = build_api_data_contract(copy.deepcopy(payload))
    contract.setdefault("meta", {})["leagueKey"] = "dynasty_main"
    return contract


def _archive_trades(contract):
    """A handful of real 2-team shapes: top offense swap, IDP per family,
    owned picks both ways."""
    teams = [t for t in contract["sleeper"]["teams"] if t.get("playerIds")]
    a, b = teams[0], teams[1]
    rows = {str(r.get("playerId")): r for r in contract["playersArray"] if r.get("playerId")}

    def best(team, pred):
        cands = [
            rows[p]
            for p in team["playerIds"]
            if p in rows and pred(rows[p]) and (rows[p].get("rankDerivedValue") or 0) > 0
        ]
        cands.sort(key=lambda r: -(r.get("rankDerivedValue") or 0))
        return f"p:{cands[0]['playerId']}" if cands else None

    ra, rb = a["roster_id"], b["roster_id"]
    out = []
    off = lambda r: r.get("position") in ("QB", "RB", "WR", "TE")  # noqa: E731
    for fam in ("DL", "LB", "DB"):
        pa, pb = (
            best(a, lambda r, f=fam: r.get("position") == f),
            best(b, lambda r, f=fam: r.get("position") == f),
        )
        if pa and pb:
            out.append((f"IDP {fam}", ra, rb, [(pa, ra, rb), (pb, rb, ra)]))
    oa, ob = best(a, off), best(b, off)
    out.append(("offense", ra, rb, [(oa, ra, rb), (ob, rb, ra)]))
    pick_a = next((d["assetId"] for d in a.get("pickDetails") or [] if d.get("assetId")), None)
    if pick_a:
        out.append(("pick for player", ra, rb, [(pick_a, ra, rb), (ob, rb, ra)]))
    return out


def test_archive_board_parity(archive_contract, monkeypatch):
    import json
    from types import SimpleNamespace

    from src.api import trade_simulator
    from src.trade.analyze_trade import analyze_trade

    monkeypatch.setattr(
        trade_simulator,
        "competitive_posture_for",
        lambda contract, league_key, team, *, build_if_missing: dict(S.POSTURE),
    )
    # The suite runs with no registry (conftest); read the committed league
    # config directly so both paths get the real roster settings.
    reg = json.loads((S.REPO / "config" / "leagues" / "registry.json").read_text())
    entry = next(lg for lg in reg["leagues"] if lg["key"] == "dynasty_main")
    cfg = SimpleNamespace(roster_settings=entry.get("rosterSettings") or {})
    snap = public_advisor.build_snapshot(
        archive_contract, league_key="dynasty_main", roster_settings=cfg.roster_settings
    )
    teams = {t["roster_id"]: t for t in archive_contract["sleeper"]["teams"]}
    rows = {
        str(r.get("playerId")): r for r in archive_contract["playersArray"] if r.get("playerId")
    }
    details = {d["assetId"]: d for t in teams.values() for d in (t.get("pickDetails") or [])}
    checked = 0
    for name, ra, rb, legs in _archive_trades(archive_contract):
        for perspective in (ra, rb):
            trade = public_advisor.validate_trade(
                snap, perspective=perspective, teams=[ra, rb], legs=legs
            )
            result, internals = public_advisor._evaluate_trade_internal(snap, trade)
            if "analysis" not in internals:
                assert result.category == "UNAVAILABLE"
                continue
            # The private route's exact composition.
            body = {
                "playersIn": [],
                "playersOut": [],
                "picksIn": [],
                "picksOut": [],
                "idsIn": [],
                "idsOut": [],
            }
            for aid, _f, to in legs:
                inc = to == perspective
                if aid.startswith("p:"):
                    body["playersIn" if inc else "playersOut"].append(rows[aid[2:]]["displayName"])
                else:
                    body["picksIn" if inc else "picksOut"].append(details[aid]["label"])
                    body["idsIn" if inc else "idsOut"].append(aid)
            team = teams[perspective]
            sim = trade_simulator.simulate_trade(
                archive_contract,
                resolved_team=team,
                players_in=body["playersIn"],
                players_out=body["playersOut"],
                picks_in=body["picksIn"],
                picks_out=body["picksOut"],
                pick_asset_ids_in=body["idsIn"],
                pick_asset_ids_out=body["idsOut"],
                roster_settings=dict(cfg.roster_settings or {}),
                league_key="dynasty_main",
                include_roster_utility=True,
                competitive_posture=trade_simulator.competitive_posture_for(
                    archive_contract, "dynasty_main", team, build_if_missing=True
                ),
            )
            sim["teamContext"] = {"applied": True, "mode": "team"}
            private = analyze_trade(sim, comparables={"state": "unavailable"})["decision"]
            public = internals["analysis"]["decision"]
            for key in COMPARED:
                assert public[key] == private[key], (name, perspective, key)
            assert result.category == td.public_category_from_decision(private)
            checked += 1
    assert checked >= 4
