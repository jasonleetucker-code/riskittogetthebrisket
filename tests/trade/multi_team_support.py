"""Shared builders for the N-team engine tests (spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md``).

* :func:`synthetic_league` — a LABELLED synthetic 4-team league whose board
  values reproduce the spec's worked examples (I14);
* :func:`real_board` — the newest COMPLETE archived scrape built into a real
  contract (``tests/archive_fixtures``), with its rosters stamped ``live`` at a
  pinned clock so ownership is provable; SKIPS when no archive exists;
* :func:`random_ledger` — a seeded generator of valid routed ledgers over a
  snapshot (players and owned picks, 2..4 teams, every team participating);
* :func:`reverse_replays` — real recorded own-league trades
  (``data/sleeper_last_good.json``) replayed in REVERSE on the archived board:
  each side sends back what it got, which is exactly what it holds today when
  nothing moved since.  Real structures, real assets, current ownership.
"""

from __future__ import annotations

import copy
import json
import random
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.trade import trade_ledger as tl

REPO = Path(__file__).resolve().parents[2]
PINNED_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
SYNTH_KEY = "synth"

SYNTH_SETTINGS = {
    "teamCount": 4,
    "rosterSize": 8,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 2, "FLEX": 1},
}

#: LABELLED synthetic board: (sleeperId, name, position, value) per team.
SYNTH_ROSTERS: dict[int, list[tuple[str, str, str, float | None]]] = {
    1: [
        ("101", "A Six", "WR", 6000.0),
        ("102", "A Three", "RB", 3000.0),
        ("103", "A Qb", "QB", 4000.0),
        ("104", "A Depth", "WR", 300.0),
        ("105", "A Unpriced", "RB", None),
    ],
    2: [
        ("201", "B Seven", "WR", 7000.0),
        ("202", "B Two", "RB", 2000.0),
        ("203", "B Qb", "QB", 5000.0),
        ("204", "B Depth", "TE", 200.0),
    ],
    3: [
        ("301", "C TwoFive", "WR", 2500.0),
        ("302", "C Four", "RB", 4000.0),
        ("303", "C Qb", "QB", 3500.0),
        ("304", "C Depth", "WR", 150.0),
        ("305", "C Dl", "DL", 1800.0),
    ],
    4: [
        ("401", "D Eight", "WR", 8000.0),
        ("402", "D One", "RB", 1000.0),
        ("403", "D Qb", "QB", 2500.0),
        ("404", "D Lb", "LB", 1200.0),
    ],
}
#: Pick rows the synthetic board prices (generic grade, one per future round).
SYNTH_PICK_ROWS = {"2027 Round 1": 3600.0, "2027 Round 2": 1400.0}


def _row(pid: str, name: str, pos: str, value: float | None) -> dict[str, Any]:
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "assetClass": "idp" if pos in ("DL", "LB", "DB") else "offense",
        "position": pos,
        "pos": pos,
        "team": "FA",
        "rankDerivedValue": value,
        "values": {"full": value} if value else {},
    }


def synthetic_league(
    *, roster_source: str = "live", fetched_at: datetime | None = None
) -> dict[str, Any]:
    """A fresh copy of the LABELLED synthetic 4-team league contract."""
    rows = [_row(*p) for team in SYNTH_ROSTERS.values() for p in team]
    rows.append(_row("999", "Free Agent", "WR", 900.0))
    for name, value in SYNTH_PICK_ROWS.items():
        rows.append(
            {
                "displayName": name,
                "canonicalName": name,
                "assetClass": "pick",
                "pos": "PICK",
                "rankDerivedValue": value,
                "values": {"full": value},
            }
        )
    teams = []
    for rid, roster in SYNTH_ROSTERS.items():
        details = []
        for rnd in (1, 2):
            aid = f"pick:{SYNTH_KEY}:2027:r{rnd}:o{rid}"
            details.append(
                {
                    "season": 2027,
                    "round": rnd,
                    "fromRosterId": rid,
                    "ownerRosterId": rid,
                    "slot": None,
                    "label": f"2027 Round {rnd}",
                    "assetId": aid,
                }
            )
        teams.append(
            {
                "name": f"Team {'ABCD'[rid - 1]}",
                "roster_id": rid,
                "ownerId": f"owner{rid}",
                "players": [n for _p, n, _pos, _v in roster],
                "playerIds": [p for p, _n, _pos, _v in roster],
                "picks": [d["label"] for d in details],
                "pickDetails": details,
                "pickOwnershipState": "observed",
                "pickOwnershipReason": None,
            }
        )
    when = fetched_at or PINNED_NOW
    return {
        "generatedAt": "2026-10-20T11:00:00+00:00",
        "meta": {"leagueKey": SYNTH_KEY},
        "playersArray": rows,
        "sleeper": {
            "teams": teams,
            "idToPlayer": {"999": "Free Agent"},
            "rosterSource": roster_source,
            "rosterFetchedAt": when.isoformat(),
        },
    }


def synthetic_snapshot(contract: dict[str, Any] | None = None, **kw: Any) -> tl.TradeSnapshot:
    return tl.build_trade_snapshot(
        contract if contract is not None else synthetic_league(**kw),
        league_key=SYNTH_KEY,
        roster_settings=SYNTH_SETTINGS,
        now=PINNED_NOW,
    )


# ── Real archived board ────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _real_contract() -> tuple[dict[str, Any] | None, str | None]:
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, label = newest_complete_raw_payload()
    if raw is None:
        return None, None
    contract = build_api_data_contract(raw)
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if len(teams) < 4:
        return None, label
    contract["sleeper"]["rosterSource"] = "live"
    contract["sleeper"]["rosterFetchedAt"] = (PINNED_NOW - timedelta(hours=1)).isoformat()
    contract.setdefault("meta", {})["leagueKey"] = "dynasty_main"
    return contract, label


def real_board() -> tuple[dict[str, Any], tl.TradeSnapshot, str]:
    """``(contract, snapshot, archive_label)``; skips when unavailable.  The
    contract is a private deep copy per call."""
    import pytest

    contract, label = _real_contract()
    if contract is None:
        pytest.skip("no complete archived scrape with >= 4 rosters available")
    contract = copy.deepcopy(contract)
    snap = tl.build_trade_snapshot(
        contract,
        league_key="dynasty_main",
        roster_settings=_dynasty_main_settings(),
        now=PINNED_NOW,
    )
    return contract, snap, str(label)


def _dynasty_main_settings() -> dict[str, Any]:
    reg = json.loads((REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    for league in reg.get("leagues") or []:
        if league.get("key") == "dynasty_main":
            return dict(league.get("rosterSettings") or {})
    return {}


# ── Generators ─────────────────────────────────────────────────────────────


def team_assets(snap: tl.TradeSnapshot, rid: int) -> list[str]:
    """Every asset id team ``rid`` holds in the snapshot (single-holder
    players and owned picks only, so a generated leg is always verifiable)."""
    team = snap.teams_by_roster_id[rid]
    out = []
    for pid in team.get("playerIds") or []:
        sid = str(pid)
        if snap.player_owners.get(sid) == (rid,):
            out.append(f"p:{sid}")
    for d in team.get("pickDetails") or []:
        aid = str(d.get("assetId") or "")
        if aid and tl.parse_asset_id(aid, league_key=snap.league_key):
            own = tl.lookup_league_pick_owner((), aid, index=snap.pick_owner_index)
            if own.state == "owned" and own.owner_roster_id == rid:
                out.append(aid)
    return sorted(set(out))


def random_ledger(
    snap: tl.TradeSnapshot,
    rng: random.Random,
    *,
    n_teams: int | None = None,
    max_per_team: int = 3,
    picks: bool = True,
    send_and_receive: bool = False,
) -> tuple[list[int], list[dict[str, Any]]]:
    """``(teams, legs)`` — a valid routed ledger: every team sends 1..k of its
    own assets, each to a random OTHER participant; with
    ``send_and_receive`` every team also receives at least one."""
    rids = sorted(snap.teams_by_roster_id)
    n = n_teams or rng.randint(2, min(4, len(rids)))
    teams = sorted(rng.sample(rids, n))
    while True:
        legs: list[dict[str, Any]] = []
        for rid in teams:
            pool = [a for a in team_assets(snap, rid) if picks or a.startswith("p:")]
            k = rng.randint(1, min(max_per_team, len(pool)))
            for aid in rng.sample(pool, k):
                to = rng.choice([t for t in teams if t != rid])
                legs.append({"id": aid, "from": rid, "to": to})
        receivers = {leg["to"] for leg in legs}
        if not send_and_receive or receivers == set(teams):
            return teams, legs


def reverse_replays(snap: tl.TradeSnapshot, *, sides: int | None = None) -> list[dict[str, Any]]:
    """Real own-league trades replayed in reverse on the archived board.

    Each recorded side ``got`` assets; on today's board that side still holds
    them when nothing moved since, so the reverse ledger (each side sends back
    what it got, to the side that gave it) is a REAL structure that validates
    against current ownership.  Trades whose assets moved on are dropped.
    """
    path = REPO / "data" / "sleeper_last_good.json"
    if not path.exists():
        return []
    trades = (json.loads(path.read_text(encoding="utf-8")).get("rosterData") or {}).get(
        "trades"
    ) or []
    name_to_ids: dict[str, set[str]] = {}
    for pid, name in snap.id_to_player.items():
        name_to_ids.setdefault(str(name).strip().lower(), set()).add(pid)
    out = []
    for trade in trades:
        tsides = trade.get("sides") or []
        if sides is not None and len(tsides) != sides:
            continue
        legs = []
        ok = True
        for side in tsides:
            rid = side.get("rosterId")
            if rid not in snap.teams_by_roster_id:
                ok = False
                break
            team = snap.teams_by_roster_id[rid]
            labels = {
                str(d.get("label")): str(d.get("assetId")) for d in team.get("pickDetails") or []
            }
            for got in side.get("got") or []:
                giver = next(
                    (s.get("rosterId") for s in tsides if got in (s.get("gave") or [])), None
                )
                if giver is None or giver == rid:
                    ok = False
                    break
                if got in labels:
                    aid = labels[got]
                else:
                    ids = [
                        i
                        for i in name_to_ids.get(str(got).strip().lower(), set())
                        if snap.player_owners.get(i) == (rid,)
                    ]
                    if len(ids) != 1:
                        ok = False
                        break
                    aid = f"p:{ids[0]}"
                legs.append({"id": aid, "from": rid, "to": giver})
            if not ok:
                break
        if not ok or not legs:
            continue
        teams = sorted({s["rosterId"] for s in tsides})
        try:
            tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
        except tl.LedgerError:
            continue
        out.append({"teams": teams, "legs": legs, "timestamp": trade.get("timestamp")})
    return out


def structure_replays(snap: tl.TradeSnapshot, *, sides: int) -> list[dict[str, Any]]:
    """Real recorded own-league trade STRUCTURES on today's rosters.

    Rosters move after a trade, so a recorded 3-team trade rarely validates
    as-is.  Each recorded leg (giver -> receiver, player or pick) is kept;
    the asset is the recorded one when the giver still holds it, else the
    giver's first not-yet-used asset of the same kind (deterministic).  The
    routing — who sends how many players and picks to whom — is the real one.
    """
    path = REPO / "data" / "sleeper_last_good.json"
    if not path.exists():
        return []
    trades = (json.loads(path.read_text(encoding="utf-8")).get("rosterData") or {}).get(
        "trades"
    ) or []
    name_to_ids: dict[str, set[str]] = {}
    for pid, name in snap.id_to_player.items():
        name_to_ids.setdefault(str(name).strip().lower(), set()).add(pid)
    out = []
    for trade in trades:
        tsides = trade.get("sides") or []
        if len(tsides) != sides:
            continue
        if any(s.get("rosterId") not in snap.teams_by_roster_id for s in tsides):
            continue
        used: set[str] = set()
        legs = []
        for side in tsides:
            giver = side["rosterId"]
            held = team_assets(snap, giver)
            for item in side.get("gave") or []:
                to = next((s["rosterId"] for s in tsides if item in (s.get("got") or [])), None)
                if to is None or to == giver:
                    continue
                labels = {
                    str(d.get("label")): str(d.get("assetId"))
                    for d in snap.teams_by_roster_id[giver].get("pickDetails") or []
                }
                kind = "pick" if item in labels or "(" in item or item[:4].isdigit() else "player"
                ids = [
                    f"p:{i}"
                    for i in name_to_ids.get(str(item).strip().lower(), set())
                    if snap.player_owners.get(i) == (giver,)
                ]
                aid = labels.get(item) if kind == "pick" else (ids[0] if len(ids) == 1 else None)
                if aid is None or aid in used or aid not in held:
                    aid = next(
                        (
                            a
                            for a in held
                            if a not in used and (a.startswith("p:") == (kind == "player"))
                        ),
                        None,
                    )
                if aid is None:
                    continue
                used.add(aid)
                legs.append({"id": aid, "from": giver, "to": to})
        teams = sorted({s["rosterId"] for s in tsides})
        try:
            tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
        except tl.LedgerError:
            continue
        out.append({"teams": teams, "legs": legs, "timestamp": trade.get("timestamp")})
    return out
