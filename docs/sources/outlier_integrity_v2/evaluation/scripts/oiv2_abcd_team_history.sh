#!/bin/bash
# Independent evidence for the V2 Layer A team_only_mismatch holds: the
# board's own Sleeper team map (data/player_map/team_map_last_good.json) as
# committed in git history, for every player V2 holds on the pins.
# usage: oiv2_abcd_team_history.sh [REPO]   (read-only; git objects only)
set -euo pipefail
cd "${1:-.}"
for c in $(git log --format=%h --since=2026-07-28 --until=2026-10-20 -- data/player_map/team_map_last_good.json | awk 'NR%25==1'); do
  printf '%s %s ' "$c" "$(git log -1 --format=%cs "$c")"
  git show "$c:data/player_map/team_map_last_good.json" | python3 -c '
import json, sys
P = json.load(sys.stdin)["players"]
names = ["Marvin Harrison", "Kaytron Allen", "Joe Milton", "Jarquez Hunter", "Jerome Ford"]
print(" ".join(f"{n.split()[-1]}={(P.get(n) or {}).get(chr(116)+chr(101)+chr(97)+chr(109))}" for n in names))'
done
