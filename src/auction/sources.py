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


def budget_league_mismatch(
    seat_league_key: str | None, draft_capital: Mapping[str, Any] | None
) -> str | None:
    """Why these budgets may not be joined to seats of ``seat_league_key``.

    ``None`` when the draft-capital payload is stamped for the SAME league as
    the seats.  Otherwise a machine-readable reason: the dollars are another
    league's (``budget_league_mismatch``) or the payload does not say whose
    they are (``budget_league_unstated``).  LI1842-DEFECT-13: the seats come
    from the loaded contract and the budgets from a separately resolved
    league, so the two could silently be different leagues.  An unknown seat
    league is not asserted here (generic seats carry none).
    """
    if not seat_league_key:
        return None
    budget_key = (draft_capital or {}).get("leagueKey")
    if not budget_key:
        return "budget_league_unstated"
    if str(budget_key) != str(seat_league_key):
        return "budget_league_mismatch"
    return None


def join_budgets(
    seats: list[dict],
    draft_capital: Mapping[str, Any] | None,
    *,
    seat_league_key: str | None = None,
) -> tuple[list[dict], dict]:
    """Attach raw auction dollars.  Returns (seats, provenance).

    Provenance names the league the DOLLARS belong to (``leagueKey``, the
    draft-capital payload's own stamp) and, when known, the league the SEATS
    belong to (``seatLeagueKey``), so a room's receipt shows whether the two
    agree (``leagueMismatch``).  The caller refuses a mismatch; this function
    only reports.
    """
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
        # Whose dollars these are: the payload's own league stamp, never
        # inferred.  ``None`` = the payload did not say.
        "leagueKey": (draft_capital or {}).get("leagueKey"),
        "seatLeagueKey": seat_league_key,
        "leagueMismatch": budget_league_mismatch(seat_league_key, draft_capital),
        "season": (draft_capital or {}).get("season"),
        "totalBudget": (draft_capital or {}).get("totalBudget"),
        "numTeams": (draft_capital or {}).get("numTeams"),
        "sourceKind": (draft_capital or {}).get("source") or "workbook",
        "sum": sum(v for v in by_team.values()),
        "unmatchedSeats": unmatched,
        "unmatchedBudgetRows": sorted(k for k in by_team if k not in matched_keys),
        "duplicateTeamNames": sorted(dupes),
        # The payload's own statement about its budgets.  When it is
        # ``unavailable`` every ``auctionDollars`` is null, so every seat above
        # is ``missing`` — never an opening budget of $0.
        "teamTotalsState": (draft_capital or {}).get("teamTotalsState"),
        "teamTotalsReason": (draft_capital or {}).get("teamTotalsReason"),
        # Which dollars generation the budgets came from (Batch F receipt:
        # generationHash, curveVersion, targetDraftYear, spineYears,
        # inputMode, allocationState …), snapshotted with the room.  ``None``
        # when the payload carried none (a board that predates the receipt).
        "draftValuationGeneration": (draft_capital or {}).get("draftValuationGeneration"),
        # Set only when the board was a stale-while-revalidate answer.
        "staleWhileRevalidate": (draft_capital or {}).get("staleWhileRevalidate"),
    }
    return out, provenance


def advice_board_values(
    contract: Mapping[str, Any] | None, state: Mapping[str, Any]
) -> tuple[dict[str, float], str | None]:
    """Current canonical values for a room's frozen pool, or why none.

    Withheld (``{}``, ``board_is_for_another_league``) when the room's seats
    are a league's and the loaded board DECLARES a different league: neither
    that board's rosters nor its values are this room's to mix in (LATENT-06,
    LI1842-DEFECT-13).  The same declared-league rule the roster context
    uses; an unstamped board is the server's own league.
    """
    meta = (contract or {}).get("meta") or {}
    room_league = state.get("league_key")
    if room_league and meta.get("leagueKey") and str(meta["leagueKey"]) != str(room_league):
        return {}, "board_is_for_another_league"
    wanted = set((state.get("pool") or {}).get("players") or {})
    values: dict[str, float] = {}
    for row in (contract or {}).get("playersArray") or []:
        pid = str(row.get("playerId") or "")
        if pid in wanted:
            v = row.get("rankDerivedValue")
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                values[pid] = float(v)
    return values, None


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
