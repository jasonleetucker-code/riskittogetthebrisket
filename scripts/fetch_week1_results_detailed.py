"""Fetch week 1 rosters with player names from Sleeper league.

Usage:
    python scripts/fetch_week1_results_detailed.py --league-id <league_id>
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def _http_get_json(url: str) -> Any:
    """Fetch a URL and parse JSON."""
    try:
        headers = {"User-Agent": "brisket/1.0"}
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print(f"Error fetching {url}: {e}", file=sys.stderr)
        return None


def fetch_league_data_detailed(league_id: str) -> None:
    """Fetch and display week 1 rosters with player names."""
    base_url = "https://api.sleeper.app/v1"

    # Fetch NFL players to build name map
    print("Fetching player data...", file=sys.stderr)
    players_url = f"{base_url}/players/nfl"
    all_players = _http_get_json(players_url)
    if not all_players:
        print("Warning: Could not fetch player names, using IDs instead", file=sys.stderr)
        all_players = {}

    player_name_map = {}
    if isinstance(all_players, dict):
        for player_id, player_data in all_players.items():
            if isinstance(player_data, dict):
                first = player_data.get("first_name", "")
                last = player_data.get("last_name", "")
                if first and last:
                    player_name_map[player_id] = f"{first} {last}"
                elif player_data.get("full_name"):
                    player_name_map[player_id] = player_data["full_name"]

    # Fetch league
    league_url = f"{base_url}/league/{league_id}"
    league = _http_get_json(league_url)
    if not league:
        print(f"Failed to fetch league {league_id}")
        return

    print(f"\n{'='*80}")
    print(f"LEAGUE: {league.get('name', 'Unknown')} | Season: {league.get('season')}")
    print(f"{'='*80}\n")

    # Fetch users
    users_url = f"{base_url}/league/{league_id}/users"
    users = _http_get_json(users_url)
    if not users:
        print("Failed to fetch users")
        return

    user_map = {u["user_id"]: u["display_name"] for u in users}

    # Fetch rosters
    rosters_url = f"{base_url}/league/{league_id}/rosters"
    rosters = _http_get_json(rosters_url)
    if not rosters:
        print("Failed to fetch rosters")
        return

    roster_map = {r["roster_id"]: r for r in rosters}

    # Fetch matchups for week 1
    matchups_url = f"{base_url}/league/{league_id}/matchups/1"
    matchups = _http_get_json(matchups_url)
    if not matchups:
        print("Failed to fetch week 1 matchups")
        return

    # Group matchups by matchup_id
    matchup_groups = {}
    for m in matchups:
        mid = m.get("matchup_id")
        if mid not in matchup_groups:
            matchup_groups[mid] = []
        matchup_groups[mid].append(m)

    # Create matchup scores map
    matchup_scores = {}
    for m in matchups:
        rid = m.get("roster_id")
        score = m.get("points", 0) or 0
        matchup_scores[rid] = score

    # Display each matchup with player details
    for mid in sorted(matchup_groups.keys()):
        sides = matchup_groups[mid]
        if len(sides) < 2:
            continue

        side_a = sides[0]
        side_b = sides[1]

        roster_a = roster_map.get(side_a["roster_id"], {})
        roster_b = roster_map.get(side_b["roster_id"], {})

        manager_a = user_map.get(roster_a.get("owner_id"), "Unknown")
        manager_b = user_map.get(roster_b.get("owner_id"), "Unknown")

        score_a = matchup_scores.get(side_a["roster_id"], 0)
        score_b = matchup_scores.get(side_b["roster_id"], 0)

        print(f"MATCHUP {mid}: {manager_a} ({score_a:.1f}) vs {manager_b} ({score_b:.1f})")
        print("-" * 80)

        # Display rosters
        players_a = roster_a.get("players", [])
        players_b = roster_b.get("players", [])

        print(f"\n{manager_a} Roster:")
        for pid in sorted(players_a, key=lambda x: player_name_map.get(x, x)):
            name = player_name_map.get(pid, f"ID:{pid}")
            print(f"  • {name}")

        print(f"\n{manager_b} Roster:")
        for pid in sorted(players_b, key=lambda x: player_name_map.get(x, x)):
            name = player_name_map.get(pid, f"ID:{pid}")
            print(f"  • {name}")

        print(f"\n{'='*80}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league-id",
        required=True,
        help="Sleeper league ID",
    )
    args = parser.parse_args()

    fetch_league_data_detailed(args.league_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
