"""Fetch week 1 rosters and scores from Sleeper league.

Usage:
    python scripts/fetch_week1_results.py --league-id <league_id>
    python scripts/fetch_week1_results.py --league-id 1312006700437352448
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


def fetch_league_data(league_id: str) -> None:
    """Fetch and display week 1 rosters and scores."""
    base_url = "https://api.sleeper.app/v1"

    # Fetch users and league info
    league_url = f"{base_url}/league/{league_id}"
    league = _http_get_json(league_url)
    if not league:
        print(f"Failed to fetch league {league_id}")
        return

    print(f"\n=== League: {league.get('name', 'Unknown')} ===")
    print(f"Season: {league.get('season')}")
    print(f"Settings: {league.get('settings')}")

    # Fetch users
    users_url = f"{base_url}/league/{league_id}/users"
    users = _http_get_json(users_url)
    if not users:
        print("Failed to fetch users")
        return

    user_map = {u["user_id"]: u["display_name"] for u in users}
    print(f"\nManagers ({len(users)}):")
    for u in users:
        print(f"  {u['display_name']} (id: {u['user_id']})")

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

    print(f"\n=== Week 1 Matchups ===\n")

    # Group matchups by matchup_id
    matchup_groups = {}
    for m in matchups:
        mid = m.get("matchup_id")
        if mid not in matchup_groups:
            matchup_groups[mid] = []
        matchup_groups[mid].append(m)

    # Display each matchup
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

        score_a = side_a.get("points", 0) or 0
        score_b = side_b.get("points", 0) or 0

        print(f"Matchup {mid}:")
        print(f"  {manager_a}: {score_a} points")
        print(f"    Roster: {roster_a.get('players', [])[:5]}..." if roster_a.get('players') else "    Roster: (no data)")
        print(f"  {manager_b}: {score_b} points")
        print(f"    Roster: {roster_b.get('players', [])[:5]}..." if roster_b.get('players') else "    Roster: (no data)")
        print()

    # Also display team-by-team breakdown with player details
    print("\n=== Team Rosters (Week 1) ===\n")

    for roster in rosters:
        owner_id = roster.get("owner_id")
        manager_name = user_map.get(owner_id, "Unknown")
        players = roster.get("players", [])

        print(f"{manager_name}:")
        print(f"  Players: {players}")

        # Find their score in matchups
        matchup = next((m for m in matchups if m.get("roster_id") == roster["roster_id"]), None)
        if matchup:
            score = matchup.get("points", 0) or 0
            print(f"  Week 1 Score: {score}")
        print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league-id",
        required=True,
        help="Sleeper league ID",
    )
    args = parser.parse_args()

    fetch_league_data(args.league_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
