#!/bin/bash
BASE=http://127.0.0.1:3000
COOKIE="jason_session=537a2ce4e91741db9d1d8172ea5d95a4"
PAGES=(
 / /login /rankings /rankings/qb /trending /idptc-rookies /players/compare /bdvm
 /news /trade /angle /arbitrage /trades /rosters /waivers /draft /phases
 /edge /consensus-edge /market/sharp-tracker /market/sharp-roster-percentage
 /league /league/activity /league/insider-trading /league-comparison
 /settings /more /tools/source-health /tools/ros-data-health /tools/trade-coverage /admin
 /finder /design /intel /draft-capital
 /league/franchise/1 /league/player/4046 /league/rivalry/a-vs-b /league/week/2025/1
 /league/weekly/2025/1/1 /league/articles/2025/1 /league/articles/2025/1/1/recap
 /robots.txt /sitemap.xml /manifest.webmanifest /nonexistent-xyz
)
printf "%-46s %-24s %-24s\n" PAGE ANON AUTH
for p in "${PAGES[@]}"; do
  a=$(curl -s -m 25 -o /dev/null -w "%{http_code}|%{redirect_url}" "$BASE$p")
  b=$(curl -s -m 25 -o /dev/null -w "%{http_code}|%{redirect_url}" -H "Cookie: $COOKIE" "$BASE$p")
  printf "%-46s %-24s %-24s\n" "$p" "${a:0:23}" "${b:0:23}"
done
