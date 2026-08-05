#!/bin/bash
# usage: w01_flagprobe.sh <port> <outdir>
PORT=$1; OUT=$2; mkdir -p "$OUT"
C=/tmp/audit-cookies-w01.txt
ROUTES=(
 "/api/data?view=app"
 "/api/data?view=full"
 "/api/rankings/sources"
 "/api/terminal"
 "/api/draft-capital"
 "/api/movers"
 "/api/news"
 "/api/leagues"
 "/api/valuation/league-adjusted"
 "/api/gameplan"
 "/api/ros/player-values"
 "/api/ros/team-strength"
 "/api/consensus-edge/top"
 "/api/consensus-edge/health"
 "/api/bdvm/values"
 "/api/bdvm/roster"
 "/api/data/rank-history"
 "/api/scaffold/status"
 "/api/scaffold/report"
 "/api/playerctx/player?name=Ja%27Marr%20Chase"
 "/api/public/league/metrics"
 "/api/league-comparison"
 "/api/sharp/market"
 "/api/sharp/roster-percentage"
 "/api/status"
)
for r in "${ROUTES[@]}"; do
  name=$(echo "$r" | sed 's|[/?=&%]|_|g')
  code=$(curl -s -m 120 -b $C -o "$OUT/$name.body" -w "%{http_code}" "http://127.0.0.1:$PORT$r")
  echo "$code $(wc -c < "$OUT/$name.body") $r" >> "$OUT/_index.txt"
done
