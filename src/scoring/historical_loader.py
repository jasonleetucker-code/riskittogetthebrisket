from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, Tuple


def aggregate_weighted_season_profile(
    season_stats: Dict[int, Dict[str, float]],
    season_games: Dict[int, int],
    ordered_seasons: Iterable[int],
    season_weights: Iterable[float],
) -> Tuple[Dict[str, float], int, int]:
    weighted_stats = defaultdict(float)
    total_weight = 0.0
    total_games = 0
    recent_games = 0
    seasons = list(ordered_seasons or [])
    weights = list(season_weights or [])
    if len(weights) < len(seasons):
        weights.extend([0.0] * (len(seasons) - len(weights)))

    for idx, season in enumerate(seasons):
        games = int(season_games.get(season, 0) or 0)
        if games <= 0:
            continue
        w = float(weights[idx]) if idx < len(weights) else 0.0
        if w <= 0:
            continue
        stats = season_stats.get(season) or {}
        for k, v in stats.items():
            weighted_stats[str(k)] += float(v or 0.0) * w
        total_weight += w
        total_games += games
        if idx == 0:
            recent_games = games

    if total_weight <= 0:
        return {}, total_games, recent_games
    profile = {k: (v / total_weight) for k, v in weighted_stats.items()}
    return profile, total_games, recent_games

