# V1-52 — L2 production verification recipe (#996 → #1009)

Companion to `docs/power/V1_52_CANONICAL_POWER_ENGINE.md`. That document
records the engine's design and the retirement decision; this one is the
concrete, executable checklist for whoever merges `#996` then `#1009` onto
`main` and needs to prove the merged tree behaves correctly against a real
production league, not a synthetic fixture.

**Do not rebase or push to `#996` or `#1009`.** Both are frozen for
Integration. This document was produced by inspecting their current diffs
and the live repository state — no code on either branch was touched.

Every command below assumes `$BASE_URL` is the real deployed origin (e.g.
`https://<prod-host>`) and is meant to run **after** both PRs are merged.

## 0. Main-divergence check — do this first

`main` contains PR #992 (`a7ccdec3f`, "V1-97 / C3-REPLAY-01"), which is not
an ancestor of either `#996` or `#1009`'s branch — a genuine divergence to
integrate, not a fast-forward.

**#1009's own PR body overstates this conflict** — it names four files
(`_build_overview`, `_build_activity_section`, `build_section_payload`,
`overview.py::_current_power_leader`) as needing manual resolution. An
actual 3-way merge simulation shows this is not accurate:

```bash
git fetch origin claude/v1-52-retire-overview-power-leader claude/v1-52-retire-legacy-power-engine main
git merge-tree --write-tree --name-only origin/main origin/claude/v1-52-retire-overview-power-leader   # #996 onto main
git merge-tree --write-tree --name-only origin/main origin/claude/v1-52-retire-legacy-power-engine       # #1009 onto main (superset check)
```

Expect: **exactly one** file printed with `CONFLICT (content)` —
`docs/WORK_CLAIMS.md`, where both #992 and the #996/#1009 chain append a
new row to the same claims table at the same insertion point. Resolution:
**keep both rows** — they are independent, non-overlapping log entries,
accept-both.

`src/public_league/public_contract.py`, `docs/audits/formula-registry.json`,
and `tests/public_league/test_public_contract.py` are also touched by both
sides but **merge with zero conflict markers** — #992 only touches
`_build_activity_section`'s type annotation and `build_section_payload`'s
docstring/signature, on line ranges disjoint from what #996/#1009 touch in
the same file. `overview.py` is untouched by #992 at all.
`frontend/app/league/LeagueClient.jsx`, `tabs.js`, `useSettings.js`,
`settings/page.jsx`, `public-league-data.js` have zero commits on `main`
since the branch point — no conflict risk.

**If a real merge later shows a conflict outside `docs/WORK_CLAIMS.md`**,
that is a regression relative to this recipe, not something to resolve by
assumption — investigate fresh.

## 1. Both canonical lenses

Route: `GET /api/public/league/{section}` (`server.py`), param `lens: str`.

```bash
curl -s "$BASE_URL/api/public/league/rosPower" | python3 -m json.tool > /tmp/fwd.json
curl -s "$BASE_URL/api/public/league/rosPower?lens=forward_looking" | python3 -m json.tool > /tmp/fwd2.json
diff /tmp/fwd.json /tmp/fwd2.json   # expect no diff except the top-level "lens" echoing explicitly

curl -s "$BASE_URL/api/public/league/rosPower?lens=results_only" | python3 -m json.tool > /tmp/results.json

# Invalid lens must 400, not silently fall back
curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/api/public/league/rosPower?lens=bogus"
# expect: 400, body has {"error": "Unknown power lens: 'bogus'", "availableLenses": [...]}
```

```bash
python3 -c "
import json
fwd = json.load(open('/tmp/fwd.json'))['data']
res = json.load(open('/tmp/results.json'))['data']
assert fwd['lens'] == 'forward_looking'
assert res['lens'] == 'results_only'
assert res['rosTeamStrengthAvailable'] is False, 'results-only must never consult team strength'
fwd_order = [r['ownerId'] for r in fwd['currentRanking']]
res_order = [r['ownerId'] for r in res['currentRanking']]
print('same order:', fwd_order == res_order)
print('effectiveWeights fwd:', fwd['effectiveWeights'])
print('effectiveWeights res:', res['effectiveWeights'])
assert fwd['trend'] == res['trend'], 'trend is always results-only by construction, must not vary by requested lens'
"
```

Checklist:
- [ ] `data.lens` differs between the two responses.
- [ ] `data.rosTeamStrengthAvailable` is always `False` for results-only.
- [ ] `data.effectiveWeights` never contains `team_ros_strength`/
      `schedule_adjusted` for results-only.
- [ ] `currentRanking` ordering generally differs between lenses (unless the
      board happens to tie).
- [ ] `data.trend` is byte-identical between the two lens responses.
- [ ] On the live UI (`ros-power.jsx`'s lens toggle above the ranking
      table): clicking it re-sorts the table and changes the weights panel
      without a full reload; a second click within 30 min does not re-fetch
      (module-level per-lens cache, `CACHE_TTL_MS = 30 * 60 * 1000` —
      confirm via the Network tab).

## 2. 12 real owners — full census, not a subset

`_enumerate_owner_ids` (`src/ros/power_v2.py`) unions three sources through
the registry's non-retired filter: the live team-strength snapshot, current
Sleeper season rosters, and historical `career_state` participants — so a
brand-new owner with zero history still appears via the roster source.

```bash
curl -s "$BASE_URL/api/public/league/rosPower" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
names = [r.get('displayName') or r.get('ownerId') for r in d['currentRanking']]
print('owner count:', len(names))
print(sorted(names))
"
```

Checklist:
- [ ] Count matches the league's actual current roster count — check
      against Sleeper's own roster listing or the site's `/league`
      standings tab, not a hardcoded expectation (a real league's owner
      count changes year to year).
- [ ] Every `displayName` is a real name/handle, never a bare numeric
      Sleeper id.
- [ ] A manager who joined this season with no prior-season history still
      appears, with `record` reflecting only current-season games (can be
      `"0-0"` pre-week-1) and a real `powerScore` (not `null`) as long as at
      least one component survives.
- [ ] No **retired** owner appears (they're excluded from
      `ordered_managers()` by default per C9-HIST-01) — confirm a former
      owner shows on historical/archive pages but not here.
- [ ] Reference point from this repo's own last dual-engine capture
      (`docs/master-site-audit/evidence/W30/power-two-engines.json`, dated
      2026-08-17): this league's real owners are **Brent, Joey, Kich, Ty,
      Ed, MaKayla, Collin, Roy, Eric, Jason, Blaine, jstuedle** — confirm
      all still appear (or the roster has genuinely changed since).

## 3. Rank agreement/disagreement — sanity-check against something independent

**(a) Against the archived last-known dual-engine capture**
(`docs/master-site-audit/evidence/W30/power-two-engines.json`):

```bash
git show origin/main:docs/master-site-audit/evidence/W30/power-two-engines.json
```

That file has the last recorded output of both the legacy `power.py` (10
owners) and `power_v2` forward-looking (12 owners), `overlap: 10`,
`meanAbsRankShift: 2.8`, `maxAbsRankShift: 7`. Pull a fresh forward-looking
response post-merge and compare against that snapshot:

```bash
curl -s "$BASE_URL/api/public/league/rosPower" | python3 -c "
import json, sys
new = {r['displayName']: r['rank'] for r in json.load(sys.stdin)['data']['currentRanking']}
old = {'Brent':1,'Joey':2,'Jason':3,'Collin':4,'Eric':5,'MaKayla':6,'Ty':7,'Kich':8,'Ed':9,'Roy':10,'Blaine':11,'jstuedle':12}
common = set(new) & set(old)
shifts = {k: abs(new[k]-old[k]) for k in common}
print('common owners:', len(common), '/ 12')
print('mean shift vs archived v2 capture:', sum(shifts.values())/len(shifts))
print('max shift:', max(shifts.values()))
print(shifts)
"
```

Expect a **small** shift (single-digit, natural week-over-week movement of
the SAME engine) — not the ~2.8 mean / 7 max seen between the OLD v1 and
NEW v2 engines in that file (that magnitude reflected two genuinely
different methodologies, now moot since v1 is deleted).

**(b) Against actual win-loss standings** (methodology sanity, not
exact-match — `power_v2` blends ROS strength/PPG/luck-regression on top of
W/L, it is not expected to equal standings order):

```bash
curl -s "$BASE_URL/api/public/league/rosPower" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']['currentRanking']
for r in d:
    print(f\"{r['rank']:>2}  {r['displayName']:<12} score={r['powerScore']}  record={r['record']}\")
"
```

- [ ] Best-record team is generally near the top, worst near the bottom —
      not perfectly, but a 0-8 team at #1 or an 8-0 team at #10 is a red
      flag worth investigating (check `effectiveWeights` on that response
      first — a legitimately renormalized preseason state could explain it).
- [ ] `record` matches the site's actual standings page/tab exactly (a
      plain fact, not approximate).

## 4. Unrankable teams — real-world trigger conditions and correct shape

`unrankable` (`power_v2.py`) is non-null only when every weighted component
is dropped. Two structurally-reachable real conditions:

- **Preseason + forward-looking lens with no team-strength snapshot yet** —
  reason `"preseason_and_no_forward_looking_input"`.
- **The entire offseason, before the first season has any scored games at
  all** — reason `"no_scoring_component_available"`.

Hit this on a real league at any point before week 1's games have scored, if
the ROS scrape hasn't run yet:

```bash
curl -s "$BASE_URL/api/public/league/rosPower?lens=forward_looking" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
u = d.get('unrankable')
if u:
    print('reason:', u['reason'])
    assert u['reason'] in ('no_scoring_component_available', 'preseason_and_no_forward_looking_input')
    print('missingInputs:', u['missingInputs'])
    for row in d['currentRanking']:
        assert row['powerScore'] is None, f\"{row['ownerId']} has a fabricated score {row['powerScore']!r}\"
        assert row['rank'] is None, f\"{row['ownerId']} has a fabricated rank {row['rank']!r}\"
        assert row['record'] is not None, 'record is a FACT and must survive refusal'
        print(row['ownerId'], row['record'], row['components'].get('pointsPerGame'))
else:
    print('currently rankable -- re-run this check in true preseason to exercise the refusal path')
"
```

- [ ] `powerScore`/`rank` are JSON `null`, **never** `0` — `0.0` is a real,
      earnable score, indistinguishable from a legitimately terrible team.
- [ ] `reason` is one of the two real strings above, never a generic
      fallback.
- [ ] `record` and `components.pointsPerGame`/`components.recentAvg` are
      still populated on unrankable rows — facts survive the refusal; only
      the weighted score is withheld.
- [ ] On the live UI, the table shows a visible "we can't rank right now"
      state, not an empty table and not a silent fallback to alphabetical
      order.

## 5. Performance at production scale

All prior numbers are **synthetic** (a 12-owner/8-season fixture, 35.25ms
full build, explicitly flagged in `docs/WORK_CLAIMS.md` and
`docs/power/V1_52_CANONICAL_POWER_ENGINE.md` as "nothing here is
deployed... observed in production rather than assumed"). This closes that
gap.

```bash
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "rosPower fwd:  %{time_total}s (http %{http_code})\n" \
    "$BASE_URL/api/public/league/rosPower"
done
for i in 1 2 3 4 5; do
  curl -s -o /dev/null -w "rosPower res:  %{time_total}s (http %{http_code})\n" \
    "$BASE_URL/api/public/league/rosPower?lens=results_only"
done

# Aggregate /league landing-page contract -- includes the eager
# currentPowerLeader call inside _build_overview, now the ONLY power
# computation on this path since power.py is deleted.
for i in 1 2 3; do
  curl -s -o /dev/null -w "aggregate /league: %{time_total}s\n" "$BASE_URL/api/public/league"
done

curl -s -o /dev/null -w "TTFB /league?tab=power: %{time_starttransfer}s / total %{time_total}s\n" \
  "$BASE_URL/league?tab=power"
```

- [ ] Record the real season/week count for this league (`len(data.trend.weeks)`
      from the `rosPower` response) — this league is not "8 seasons," use
      whatever it actually is.
- [ ] Compare real `time_total` against the synthetic 35.25ms figure scaled
      by real season/week count — a 2-5x multiple is plausible; an
      order-of-magnitude blowup (>500ms) is a real regression.
- [ ] The **aggregate `/league` payload** should be faster post-merge than
      the pre-#996 baseline (one eager power computation deleted, not
      replaced) — if it's not faster, check `_build_overview` isn't
      accidentally calling `power_v2.build_section` twice.
- [ ] `Cache-Control` header on `/api/public/league/rosPower` reads as
      expected (`curl -sI`).

## 6. No legacy power engine reachable — prove it on the running process

Repo-level (fast, but insufficient alone):
```bash
git show origin/main:src/public_league/power.py 2>&1   # expect: fatal: path does not exist
git show origin/main:frontend/app/league/sections/power.jsx 2>&1   # expect: fatal: path does not exist
```

On the live deployed process:
```bash
curl -s "$BASE_URL/api/public/league" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'power' not in d.get('sections', {}), 'legacy power section key still present'
print('OK: sections keys:', sorted(d.get('sections', {}).keys()))
"

curl -s -o /dev/null -w "%{http_code}\n" "$BASE_URL/api/public/league/power"
# expect: 404
```

Run the pinned, mutation-proven suites this repo ships for exactly this
purpose:
```bash
python -m pytest tests/public_league/test_legacy_power_engine_retired.py -v
cd frontend && npx vitest run __tests__/legacy-power-engine-retired.test.js
```

- [ ] Search the merged tree for any lingering reference:
      `git grep -n "public_league.power\b\|public_league import power" -- '*.py'`
      (excluding the test files that assert its absence) returns nothing.

## 7. No fabricated `weekRankDelta`

**(a) Landing-page power-leader card** — `overview.py::_current_power_leader`
reads `head.get("weekRankDelta")` with no default, and `power_v2` rows never
carry that key, so it is always `None`.

```bash
curl -s "$BASE_URL/api/public/league" | python3 -c "
import json, sys
d = json.load(sys.stdin)
leader = d.get('sections', {}).get('overview', {}).get('currentPowerLeader')
print(leader)
assert leader is None or leader.get('weekRankDelta') is None
"
```

- [ ] `null` at every point in the season, not just week 1 — this field has
      no data source at all post-retirement (`team_strength.py` only ever
      writes a current snapshot), so it should never regress into a `0`.

**(b) Power tab's per-row trend arrow** — `ros-power.jsx`'s `TrendCell`
renders `—` for `null` (< 2 trend points, or the compared week was
unrankable), `•` for a genuine `0` (rank unchanged), `▲`/`▼ N` otherwise.

```bash
curl -s "$BASE_URL/api/public/league/rosPower" | python3 -c "
import json, sys
d = json.load(sys.stdin)['data']
weeks = d['trend']['weeks']
print('total trend weeks:', len(weeks))
if weeks:
    print('week 1 owners:', [r['ownerId'] for r in weeks[0]['rankings']])
"
```

- [ ] The season's earliest tracked trend week: every owner's trend-delta
      cell renders `—`, never `▼0`/`▲0`/a bare `0`.
- [ ] A newly-joined owner's earliest appearance also renders `—`.
- [ ] A genuinely rank-unchanged owner renders `•`, not `▼0` — dash and dot
      must not collapse into the same rendering.

## 8. Playoff Odds presentation preserved

Ported verbatim from the deleted `power.jsx` into `ros-power.jsx`: same
`/api/public/league/playoffOdds` data source, same 30-minute cache TTL, same
`<PlayoffOddsChart>` render.

```bash
curl -s "$BASE_URL/api/public/league/playoffOdds" | python3 -m json.tool | head -30
```

- [ ] The Power tab renders a "Playoff odds" card below the power-score
      chart, subtitled "Monte Carlo over remaining regular-season weeks;
      samples each owner's score from their actual weekly history."
- [ ] Devtools Network: switching to the Power tab, away, then back within
      30 minutes fires exactly **one** `GET .../playoffOdds` request.
- [ ] Error state: blocking `/api/public/league/playoffOdds` in devtools
      shows the card with "Couldn't load playoff odds: <error>" rather than
      crashing the whole Power tab.
- [ ] The dormant `rosPlayoffOdds` (ROS-blended) section was **not**
      silently activated — `grep rosPlayoffOdds frontend/app/league/sections/ros-power.jsx`
      should return nothing; only `playoffOdds` is wired in.

## Handoff

If any checklist item fails, that is a causal gap worth reporting back to
the Season/Scoring lane — this document does not authorize new V1-52
implementation on its own. If everything passes, V1-52 can move to the next
verification level per `docs/VERSION_1_COMPLETION_CONTRACT.md`'s own
process.
