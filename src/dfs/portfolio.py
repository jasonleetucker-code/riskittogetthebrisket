"""Portfolio summary of a multi-lineup build — descriptive counts only.

What the built set actually contains: how many lineups lean on each team and
game, the shape of each lineup's biggest team stack, the salary spread and how
many distinct players are used.  Computed from the built lineups alone; it
estimates nothing (no ownership, duplication or payout model) and ranks nothing.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


def _stack_shape(players: list[dict[str, Any]]) -> str:
    """Team-count shape, largest first: "4-2-1-1-1" (each number = players from one team)."""
    counts = sorted(Counter(p["team"] for p in players).values(), reverse=True)
    return "-".join(str(c) for c in counts)


def summarize(lineups: list[dict[str, Any]]) -> dict[str, Any] | None:
    n = len(lineups)
    if n < 2:
        return None
    team_lineups: Counter[str] = Counter()
    game_lineups: Counter[str] = Counter()
    shapes: Counter[str] = Counter()
    players: set[str] = set()
    salaries = []
    unknown_game = 0
    for lu in lineups:
        ps = lu["players"]
        team_lineups.update({p["team"] for p in ps})
        games = {p.get("game") for p in ps}
        unknown_game += None in games
        game_lineups.update(g for g in games if g)
        shapes[_stack_shape(ps)] += 1
        players.update(p["playerId"] for p in ps)
        salaries.append(lu["salary"])

    def rows(counter: Counter[str]) -> list[dict[str, Any]]:
        return [
            {"key": k, "lineups": c, "share": round(c / n, 4)}
            for k, c in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    return {
        "lineups": n,
        "distinctPlayers": len(players),
        "teams": rows(team_lineups),
        "games": rows(game_lineups),
        # Lineups with a player whose game is unknown are counted, not guessed.
        "lineupsWithUnknownGame": unknown_game,
        "stackShapes": rows(shapes),
        "salary": {"min": min(salaries), "max": max(salaries)},
        "note": "Counts of what was built. Not an ownership, duplication or payout estimate.",
    }
