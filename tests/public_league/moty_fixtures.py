"""A tiny deterministic league builder for the unified Manager of the Year.

Every test states its league directly: a previous season's final rosters
(the window baseline), per-player weekly points, and the moves.  Week
holdings are DERIVED from those moves (host truth in real data is Sleeper's
per-week ``players`` list; here the builder plays the host), so a test can
never hand the engine an inconsistent roster.

All players are WR unless told otherwise, and tests pass the replacement
level explicitly (``levels={"WR": 10.0}``), so the surplus arithmetic is
readable: a WR scoring 25 in a week has surplus 15.
"""

from __future__ import annotations

from typing import Any, Callable

from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

LEVELS = {"WR": 10.0, "RB": 10.0}


def owner(rid: int) -> str:
    return f"o{rid}"


class League:
    """Build a two-league chain: ``P`` (previous, complete) -> ``C`` (current)."""

    def __init__(
        self,
        *,
        weeks: int = 4,
        teams: int = 4,
        base: dict[int, list[str]] | None = None,
        points: dict[str, float | Callable[[int], float]] | None = None,
        status: str = "complete",
        inaugural: bool = False,
        positions: dict[str, str] | None = None,
    ) -> None:
        self.weeks = weeks
        self.teams = teams
        self.base = (
            base
            if base is not None
            else {r: [f"r{r}p{i}" for i in range(3)] for r in range(1, teams + 1)}
        )
        self.points = points or {}
        self.status = status
        self.inaugural = inaugural
        self.positions = positions or {}
        self.txs: list[dict[str, Any]] = []
        self.team_points: dict[tuple[int, int], float | None] = {}
        self.missing_entries: set[tuple[int, int]] = set()
        self.bracket: list[dict[str, Any]] = []
        self.drafts: list[dict[str, Any]] = []
        self.draft_picks: dict[str, list[dict[str, Any]]] = {}
        self.pairings: dict[int, list[tuple[int, int]]] = {}
        self.waiver_budget = 100
        self._clock = 1_000

    # ── moves ────────────────────────────────────────────────────────────
    def _tx(self, kind: str, leg: int, adds=None, drops=None, **extra) -> dict[str, Any]:
        self._clock += 1
        rids = sorted({*(adds or {}).values(), *(drops or {}).values()})
        tx = {
            "transaction_id": f"tx{self._clock}",
            "type": kind,
            "status": "complete",
            "leg": leg,
            "created": self._clock,
            "roster_ids": rids,
            "adds": dict(adds) if adds else None,
            "drops": dict(drops) if drops else None,
            "draft_picks": extra.pop("draft_picks", []),
            "waiver_budget": extra.pop("waiver_budget", []),
            "settings": extra.pop("settings", None),
        }
        tx.update(extra)
        self.txs.append(tx)
        return tx

    def trade(self, leg: int, a: int, a_sends: list[str], b: int, b_sends: list[str], **extra):
        adds = {p: b for p in a_sends} | {p: a for p in b_sends}
        drops = {p: a for p in a_sends} | {p: b for p in b_sends}
        return self._tx("trade", leg, adds, drops, **extra)

    def waiver(self, leg: int, rid: int, add: str | None = None, drop: str | None = None, bid=None):
        return self._tx(
            "waiver",
            leg,
            {add: rid} if add else None,
            {drop: rid} if drop else None,
            settings={"waiver_bid": bid} if bid is not None else {"waiver_bid": 0},
        )

    def free_agent(self, leg: int, rid: int, add: str | None = None, drop: str | None = None):
        return self._tx(
            "free_agent", leg, {add: rid} if add else None, {drop: rid} if drop else None
        )

    def draft(self, picks: list[tuple[int, str, int]], *, kind: str = "linear", amounts=None):
        """``picks`` = [(roster_id, player_id, pick_no)], drafted before week 1."""
        did = f"d{len(self.drafts) + 1}"
        self.drafts.append(
            {
                "draft_id": did,
                "type": kind,
                "status": "complete",
                "start_time": 500 + len(self.drafts),
                "settings": {"teams": self.teams, "rounds": 3},
                "draft_order": {owner(r): r for r in range(1, self.teams + 1)},
            }
        )
        rows = []
        for i, (rid, pid, pick_no) in enumerate(picks):
            meta = {"amount": str(amounts[i])} if amounts else {}
            rows.append(
                {
                    "draft_id": did,
                    "roster_id": rid,
                    "player_id": pid,
                    "pick_no": pick_no,
                    "round": (pick_no - 1) // self.teams + 1,
                    "metadata": meta,
                }
            )
        self.draft_picks[did] = rows

    # ── derived state ────────────────────────────────────────────────────
    def pts(self, pid: str, week: int) -> float:
        val = self.points.get(pid, 0.0)
        return float(val(week)) if callable(val) else float(val)

    def holdings(self) -> dict[int, dict[int, list[str]]]:
        held = {r: list(ps) for r, ps in self.base.items()}
        for r in range(1, self.teams + 1):
            held.setdefault(r, [])
        drafted = {}
        for rows in self.draft_picks.values():
            for row in rows:
                drafted.setdefault(row["roster_id"], []).append(row["player_id"])
        for r, ps in drafted.items():
            held[r] = held[r] + [p for p in ps if p not in held[r]]
        out = {}
        txs = sorted(self.txs, key=lambda t: t["created"])
        for wk in range(1, self.weeks + 1):
            for tx in txs:
                if tx["leg"] != wk:
                    continue
                for pid, rid in (tx["drops"] or {}).items():
                    if pid in held[rid]:
                        held[rid].remove(pid)
                for pid, rid in (tx["adds"] or {}).items():
                    if pid not in held[rid]:
                        held[rid].append(pid)
            out[wk] = {r: list(ps) for r, ps in held.items()}
        return out

    def build(self) -> tuple[PublicLeagueSnapshot, SeasonSnapshot]:
        hold = self.holdings()
        matchups: dict[int, list[dict[str, Any]]] = {}
        for wk in range(1, self.weeks + 1):
            pairs = self.pairings.get(wk) or [(r, r + 1) for r in range(1, self.teams + 1, 2)]
            mid_of = {}
            for i, (a, b) in enumerate(pairs):
                mid_of[a] = mid_of[b] = i + 1
            entries = []
            for rid in range(1, self.teams + 1):
                if (wk, rid) in self.missing_entries:
                    continue
                players = hold[wk][rid]
                pp = {p: self.pts(p, wk) for p in players}
                total = self.team_points.get((wk, rid), sum(pp.values()) + 100 + 10 * rid)
                entries.append(
                    {
                        "roster_id": rid,
                        "matchup_id": mid_of.get(rid),
                        "points": total,
                        "players": players,
                        "players_points": pp,
                        "starters": players[:2],
                    }
                )
            matchups[wk] = entries
        playoff_start = self.weeks + 1
        users = [
            {
                "user_id": owner(r),
                "display_name": f"Manager {r}",
                "metadata": {"team_name": f"Team {r}"},
            }
            for r in range(1, self.teams + 1)
        ]
        prev_rosters = [
            {
                "roster_id": r,
                "owner_id": owner(r),
                "players": list(self.base.get(r, [])),
                "settings": {},
            }
            for r in range(1, self.teams + 1)
        ]
        cur_rosters = [
            {
                "roster_id": r,
                "owner_id": owner(r),
                "players": hold[self.weeks][r],
                "settings": {"wins": 1, "losses": 1},
            }
            for r in range(1, self.teams + 1)
        ]
        cur_league = {
            "league_id": "C",
            "season": "2025",
            "status": self.status,
            "previous_league_id": None if self.inaugural else "P",
            "total_rosters": self.teams,
            "settings": {
                "playoff_week_start": playoff_start,
                "last_scored_leg": self.weeks,
                "playoff_teams": 2,
                "waiver_budget": self.waiver_budget,
            },
        }
        prev_league = {
            "league_id": "P",
            "season": "2024",
            "status": "complete",
            "previous_league_id": None,
            "total_rosters": self.teams,
            "settings": {"playoff_week_start": 15, "last_scored_leg": 17},
        }
        tx_by_week: dict[int, list[dict[str, Any]]] = {}
        for tx in self.txs:
            tx_by_week.setdefault(tx["leg"], []).append(tx)
        current = SeasonSnapshot(
            season="2025",
            league_id="C",
            league=cur_league,
            users=users,
            rosters=cur_rosters,
            matchups_by_week=matchups,
            transactions_by_week=tx_by_week,
            drafts=self.drafts,
            draft_picks_by_draft=self.draft_picks,
            traded_picks=[],
            winners_bracket=self.bracket,
            losers_bracket=[],
        )
        previous = SeasonSnapshot(
            season="2024",
            league_id="P",
            league=prev_league,
            users=users,
            rosters=prev_rosters,
            matchups_by_week={},
            transactions_by_week={},
            drafts=[],
            draft_picks_by_draft={},
            traded_picks=[],
            winners_bracket=[],
            losers_bracket=[],
        )
        seasons = [current] if self.inaugural else [current, previous]
        snapshot = PublicLeagueSnapshot(root_league_id="C", generated_at="t", seasons=seasons)
        snapshot.managers = build_manager_registry(
            [{"league": s.league, "users": s.users, "rosters": s.rosters} for s in seasons]
        )
        every = {p for wk in hold.values() for ps in wk.values() for p in ps} | {
            p for ps in self.base.values() for p in ps
        }
        snapshot.nfl_players = {
            p: {"first_name": "P", "last_name": p, "position": self.positions.get(p, "WR")}
            for p in every
        }
        return snapshot, current
