"""Adapters from the EXISTING canonical owners into a room's frozen inputs.

Nothing here computes a value, a budget or a player identity.  It reads:

* seats — the contract's league-scoped ``sleeper.teams`` (Sleeper
  ``ownerId`` = user_id, ``roster_id``), joined to
* budgets — ``/api/draft-capital``'s raw ``teamTotals[].auctionDollars``
  (NOT effective auction power, NOT player value, NOT waiver FAAB).  That
  payload names teams only, as ``team_name || display_name``, which is the
  contract's ``sleeperTeamName``; the join is exact, and any seat it cannot
  place is reported ``missing`` — never guessed, never defaulted to $100.
* rookie pool — ``src/draft/rookie_pool.select_rookie_rows`` over the live
  contract (canonical Sleeper ``playerId``).

The room SNAPSHOTS these at creation with provenance; later refreshes never
touch a room.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from src.draft.rookie_pool import select_rookie_rows


def league_seats(contract: Mapping[str, Any] | None) -> list[dict]:
    teams = ((contract or {}).get("sleeper") or {}).get("teams") or []
    seats = []
    for t in teams:
        if not isinstance(t, Mapping):
            continue
        seats.append(
            {
                "name": str(t.get("name") or t.get("sleeperTeamName") or "Team"),
                "team": str(t.get("sleeperTeamName") or t.get("name") or ""),
                "sleeper_user_id": str(t.get("ownerId")) if t.get("ownerId") else None,
                "roster_id": t.get("roster_id"),
            }
        )
    seats.sort(key=lambda s: (s["roster_id"] is None, s["roster_id"] or 0))
    return seats


def join_budgets(
    seats: list[dict], draft_capital: Mapping[str, Any] | None
) -> tuple[list[dict], dict]:
    """Attach raw auction dollars.  Returns (seats, provenance)."""
    totals = (draft_capital or {}).get("teamTotals") or []
    by_team: dict[str, int] = {}
    dupes: set[str] = set()
    for row in totals:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("team") or "").strip().lower()
        dollars = row.get("auctionDollars")
        if not key or isinstance(dollars, bool) or not isinstance(dollars, (int, float)):
            continue
        if key in by_team:
            dupes.add(key)
        by_team[key] = int(round(float(dollars)))
    out = []
    unmatched = []
    for s in seats:
        key = (s.get("team") or "").strip().lower()
        amount = by_team.get(key) if key not in dupes else None
        if amount is None:
            unmatched.append(s.get("team") or s.get("name"))
        out.append(
            {
                **s,
                "opening_budget": amount,
                "budget_source": "draft_capital" if amount is not None else "missing",
            }
        )
    matched_keys = {(s.get("team") or "").strip().lower() for s in seats}
    provenance = {
        "source": "/api/draft-capital teamTotals[].auctionDollars (raw dollars)",
        "season": (draft_capital or {}).get("season"),
        "totalBudget": (draft_capital or {}).get("totalBudget"),
        "numTeams": (draft_capital or {}).get("numTeams"),
        "sourceKind": (draft_capital or {}).get("source") or "workbook",
        "sum": sum(v for v in by_team.values()),
        "unmatchedSeats": unmatched,
        "unmatchedBudgetRows": sorted(k for k in by_team if k not in matched_keys),
        "duplicateTeamNames": sorted(dupes),
    }
    return out, provenance


def rookie_pool_from_contract(contract: Mapping[str, Any] | None, *, top_n: int = 120) -> dict:
    rows = select_rookie_rows(contract, top_n=top_n)
    players = {}
    for r in rows:
        pid = str(r.get("playerId"))
        players[pid] = {
            "name": str(r.get("canonicalName") or r.get("displayName")),
            "pos": str(r.get("position") or r.get("pos") or ""),
            "team": str(r.get("team") or r.get("nflTeam") or ""),
            "value": float(r.get("rankDerivedValue") or 0) or None,
        }
    digest = hashlib.sha256(json.dumps(sorted(players), sort_keys=True).encode()).hexdigest()[:12]
    draft_year = None
    meta = (contract or {}).get("meta") or {}
    for key in ("currentRookieDraftYear", "rookieDraftYear"):
        if meta.get(key):
            draft_year = meta.get(key)
    return {
        "version": f"contract-rookies-{digest}",
        "label": (
            "PRIOR-CLASS FIXTURE: the current board's rookie rows (the 2026 NFL class). "
            "This is NOT the official 2027 rookie class, which does not exist in the data yet."
        ),
        "is_official_class": False,
        "source_draft_year": draft_year,
        "players": players,
    }


def synthetic_pool(n: int = 96) -> dict:
    positions = ["QB", "RB", "WR", "TE", "WR", "RB", "LB", "DL", "DB", "WR", "RB", "TE"]
    players = {}
    for i in range(1, n + 1):
        players[f"syn{i:03d}"] = {
            "name": f"Synthetic Rookie {i:02d}",
            "pos": positions[i % len(positions)],
            "team": "",
            "value": round(9000 * (0.965**i), 1),
        }
    return {
        "version": f"synthetic-{n}-v1",
        "label": "SYNTHETIC FIXTURE: invented players for rehearsal only",
        "is_official_class": False,
        "players": players,
    }
