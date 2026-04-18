"""Value-Over-Replacement engine for the IDP calibration lab.

Rescores a *single* season player universe under two different
league scoring systems so the downstream math can compare apples to
apples. Enforces that the player universe (the set of player_ids) is
identical across both leagues — this is the core invariant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .scoring import score_line
from .stats_adapter import PlayerSeason


@dataclass
class ScoredPlayer:
    player_id: str
    name: str
    position: str
    games: int
    points_test: float
    points_mine: float


def build_universe(
    players: Iterable[PlayerSeason],
    *,
    min_games: int = 0,
) -> list[PlayerSeason]:
    """Filter the raw season list into the calibration universe.

    Default (``min_games=0``) keeps every valid DL/LB/DB with a
    non-empty stat line. ``min_games`` is the advanced filter exposed
    in the UI. Top-N per position cannot be applied here because we
    don't yet know each player's fantasy points — that selection is
    done in :func:`trim_to_top_n_per_position` after scoring.
    """
    valid: list[PlayerSeason] = []
    for p in players:
        if p.position not in {"DL", "LB", "DB"}:
            continue
        if not p.stats:
            continue
        if min_games and p.games < int(min_games):
            continue
        valid.append(p)
    return valid


def trim_to_top_n_per_position(
    scored: list["ScoredPlayer"], top_n: int | None
) -> list["ScoredPlayer"]:
    """Keep only the top ``top_n`` scored players per position.

    Selection criterion is ``max(points_test, points_mine)`` so a
    player who scores high in either league survives the cut — this
    preserves the apples-to-apples rescoring invariant (both leagues
    see the same surviving universe).

    Returns the input unchanged when ``top_n`` is falsy.
    """
    if not top_n or top_n <= 0:
        return list(scored)
    by_pos: dict[str, list[ScoredPlayer]] = {"DL": [], "LB": [], "DB": []}
    for s in scored:
        if s.position in by_pos:
            by_pos[s.position].append(s)
    keep_ids: set[str] = set()
    for cohort in by_pos.values():
        cohort.sort(
            key=lambda x: max(x.points_test, x.points_mine),
            reverse=True,
        )
        for s in cohort[: int(top_n)]:
            keep_ids.add(s.player_id)
    return [s for s in scored if s.player_id in keep_ids]


def score_universe(
    universe: list[PlayerSeason],
    test_weights: dict[str, float],
    my_weights: dict[str, float],
) -> list[ScoredPlayer]:
    """Rescore the same universe under both scoring systems."""
    out: list[ScoredPlayer] = []
    for p in universe:
        pts_test = score_line(p.stats, test_weights)
        pts_mine = score_line(p.stats, my_weights)
        out.append(
            ScoredPlayer(
                player_id=p.player_id,
                name=p.name,
                position=p.position,
                games=p.games,
                points_test=pts_test,
                points_mine=pts_mine,
            )
        )
    return out


@dataclass
class VorRow:
    player_id: str
    name: str
    position: str
    games: int
    points_test: float
    points_mine: float
    vor_test: float
    vor_mine: float
    rank_test: int  # 1-indexed within position
    rank_mine: int


def compute_vor(
    scored: list[ScoredPlayer],
    replacement_test: dict[str, float],
    replacement_mine: dict[str, float],
) -> list[VorRow]:
    """Compute VOR under both scoring systems and assign position ranks.

    Each player is ranked twice — once by their points under the test
    league scoring and once by their points under the my-league
    scoring — because a player's rank inside the DL cohort may differ
    between the two systems (that delta is the whole point of the
    calibration).
    """
    by_pos: dict[str, list[ScoredPlayer]] = {"DL": [], "LB": [], "DB": []}
    for s in scored:
        if s.position in by_pos:
            by_pos[s.position].append(s)

    rank_test: dict[str, int] = {}
    rank_mine: dict[str, int] = {}
    for pos, cohort in by_pos.items():
        for i, p in enumerate(sorted(cohort, key=lambda x: x.points_test, reverse=True), 1):
            rank_test[f"{pos}:{p.player_id}"] = i
        for i, p in enumerate(sorted(cohort, key=lambda x: x.points_mine, reverse=True), 1):
            rank_mine[f"{pos}:{p.player_id}"] = i

    rows: list[VorRow] = []
    for s in scored:
        repl_t = float(replacement_test.get(s.position, 0.0))
        repl_m = float(replacement_mine.get(s.position, 0.0))
        rows.append(
            VorRow(
                player_id=s.player_id,
                name=s.name,
                position=s.position,
                games=s.games,
                points_test=round(s.points_test, 3),
                points_mine=round(s.points_mine, 3),
                vor_test=round(s.points_test - repl_t, 3),
                vor_mine=round(s.points_mine - repl_m, 3),
                rank_test=rank_test.get(f"{s.position}:{s.player_id}", 9999),
                rank_mine=rank_mine.get(f"{s.position}:{s.player_id}", 9999),
            )
        )
    return rows


def vor_rows_to_dict(rows: list[VorRow]) -> list[dict[str, Any]]:
    return [
        {
            "player_id": r.player_id,
            "name": r.name,
            "position": r.position,
            "games": r.games,
            "points_test": r.points_test,
            "points_mine": r.points_mine,
            "vor_test": r.vor_test,
            "vor_mine": r.vor_mine,
            "rank_test": r.rank_test,
            "rank_mine": r.rank_mine,
        }
        for r in rows
    ]
