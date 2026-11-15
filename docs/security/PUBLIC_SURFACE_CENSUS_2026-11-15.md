# Public surface census: Sleeper owner ids, performance, rate limits (2026-11-15)

Evidence for owner decision brief 11 (`docs/owner/DECISION_BRIEFS_2026-11-08.md` §11) and the backend payload work under
MD-114 (owner directive 2026-11-08 Priorities 17, 18 and Part 9F). **Nothing here changes what any public route exposes.**
The exposure model is owner-reserved. Two backend changes ship with this PR; both are described in §5 and neither adds,
removes or renames a field.

Method: one read-only GET per route from `https://chaseupside.com` on 2026-11-15 between 14:30 and 14:45 UTC, no load,
spaced 2-4 s apart; payloads counted with `scripts/public_surface_census.py` (committed, reproducible); consumers found by
reading (never editing) `frontend/` and `src/`. Sleeper's own API was not called. Statements about what Sleeper's API
returns for a user id are inferred from its documented endpoints and are marked as such.

## 1. What the owner has to decide

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | Pseudonymize Sleeper owner ids on public routes (§4) | **Yes, B1**: replace every Sleeper owner id with a stable per-league pseudonym; leave display names and team names | The id is the one field that resolves to a Sleeper account outside this league (§3). The page needs it only as an opaque join key. |
| D2 | Avatars | Decide separately; default **keep** for now | The 32-hex hash is a public CDN key to the manager's picture. It identifies nothing that the display name next to it does not, but it is a second stable handle. |
| D3 | Display names (33 distinct values, 4,401 occurrences) | **Keep** unless the owner wants managers anonymous to non-members | They are the product (every table is "who"). Pseudonymizing ids alone does not anonymize the league. |
| D4 | `/api/draft-capital` stays public | **Yes** | Its only identifying payload is 24 `ownerId` strings (12 distinct) that no frontend reader uses, plus team names. D1 covers it. |
| D5 | Rate limiting (§6) | Operator adds an nginx microcache and a heavy-route `limit_req` in dry-run first | The existing app limiter is cost-blind. |
| D6 | Keep the two code changes in this PR (§5) | **Yes**, either can be reverted alone | One removes an anonymous cache-bust; one removes a duplicate computation. |

## 2. Census

### 2.1 `/api/public/league` (full contract, 2,497,911 bytes raw, 246,184 gzip)

Counted on the response fetched 14:30:17 UTC. "Distinct" means distinct values.

| Field (leaf name) | Occurrences | Kind | Frontend source files that read it (non-test) | Classification |
|---|---:|---|---|---|
| `ownerId` | 7,477 | Sleeper user id | 35 under `app/league`, `components/league`, `app/sitemap.js` (223 references) | **Join key.** React keys (26), Map lookups (12), equality (15), URL builders (8). Shown raw in one place: `app/league/franchise/[owner]/page.jsx:161` ("Owner ID"). |
| `ownerIds[]` | 897 | Sleeper user id | 6 | Join key (rivalry pair). Shown raw in `app/league/sections/archives.jsx:149`. |
| `originalOwnerId` | 727 | Sleeper user id | 1 (`pick-chips.jsx:24`, a key fallback behind `originRosterId`) | Join key, effectively unused. |
| `winnerOwnerId` | 614 | Sleeper user id | 3 (`sections/weekly.jsx`, matchup page, its OG image) | Join key (compared to `home.ownerId`). |
| `fromOwnerId`, `toOwnerId` | 294 each | Sleeper user id | 1 each (`player/[playerId]/page.jsx:354`) | Join key (link to franchise page). |
| `homeOwnerId`, `awayOwnerId` | 215 each | Sleeper user id | 1 each (`sections/archives.jsx:207`) | Display of the raw id in a table. |
| `teamKey` | 32 | Sleeper user id | 2 (`ScheduleImpact`, `ScheduleMultiverse` row keys) | Join key. |
| `sideAOwnerId`, `sideBOwnerId` | 20 each | Sleeper user id | 0 | **Unused** by the frontend. |
| `biggestMarginWinnerOwnerId` | 5 | Sleeper user id | 0 | **Unused** by the frontend. |
| `featuredRivalryPair[]` | 2 | Sleeper user id | 0 | **Unused** by the frontend. |
| dict keys: `detail.{id}` 16, `pickOwnership.{id}` 12 | 28 | Sleeper user id as a key | franchise detail map read by id | Join key. |
| `transactionId` | 2,173 (1,723 distinct) | Sleeper transaction id | 4 (React keys, trade-history grade lookup) | Join key. Not a user id; with the league id already stripped it does not resolve to a league. Keep. |
| `displayName` | 4,401 (33 distinct) | name | 37 (131 references, `nameFor`) | **Needed for display.** |
| `displayNames[]`, `originDisplayName`, `winnerDisplayName` | 326 / 433 / 45 | name | 1 / 1 / 0 | Display (`winnerDisplayName` unused). |
| `teamName`, `currentTeamName` | 4,208 / 75 | name | 26 / 7 | **Needed for display.** |
| `avatar` | 100 (18 distinct) | 32-hex Sleeper CDN hash | 2 (`avatarUrlFor` builds `https://sleepercdn.com/avatars/thumbs/<hash>`) | Display (an image). |

Totals: 10,840 textual occurrences of the 16 distinct owner ids (12 current, 4 former members): **10,812 as exact string
values and 28 as object keys, 0 embedded in longer strings.** That last number is what makes a closed-set exact
substitution complete for this payload (§4). The brief's 7,390 `ownerId` figure (Top 20 audit) has grown to 7,477 as the
season advanced. `rosterId` (5,350) is a 1-12 slot number inside the league and is not counted as identifying.

### 2.2 Other public routes (same ids, same 12 managers)

| Route | `ownerId` | other id fields | `displayName` | `teamName` / `currentTeamName` | `avatar` |
|---|---:|---|---:|---|---:|
| `playoffOdds` | 24 | | 54 | 30 / 12 | 41 |
| `rosPlayoffOdds` | 24 | | 54 | 30 / 12 | 41 |
| `rosChampionship` | 24 | | 54 | 30 / 12 | 41 |
| `conduct` | 24 | | 54 | 42 / 12 | 41 |
| `rosPower` | 588 | `priorOwnerId` 24, `franchiseBaselineOwnerId` 12, `previousOfficialOwnerId` 12, key `seriesByOwner.{id}` 12 | 498 | 66 / 12 | 41 |
| `/api/draft-capital` | 24 (`teamTotals[]` 12, `allYearsTeamTotals[]` 12) | | | `currentOwner` 216, `originalOwner` 216 (team names) | |
| `matchups`, `metrics` | 0 | | 0 | 0 | 0 |

`rosTeamStrength`, `rosTradeDeadline`, `faabAnalytics` and `teamAssignment` answered 401 anonymously and were not counted.
The CSV routes (`/api/public/league/{section}.csv`) are built from the same projected payload
(`src/public_league/csv_export.py` writes `ownerId` and `displayName` columns), so they carry the same ids.

### 2.3 Draft capital consumers

`teamTotals[].ownerId` and `allYearsTeamTotals[].ownerId` have **no frontend reader**. The Wave A join documented in
CLAUDE.md uses `rosterId` (`frontend/lib/pick-stack.js:176`), and `app/league/sections/draft-capital.jsx` reads neither
field. The `ownerId` references in `app/draft/page.jsx` and `app/trade/page.jsx` are Sleeper draft-feed and private
`sleeperTeams` ids, not this payload. Backend: `draft_capital_fallback.py:336` and `draft_capital_years.py:297` stamp it.

### 2.4 Cross-surface joins that a pseudonym must not break

These read a private-surface owner id and join or link it to the public payload:

1. `frontend/app/league/activity/ActivityClient.jsx:126`: `userState.selectedTeam.ownerId` (private user state) compared
   with the public payload's `ownerId` to build "my team" filtering.
2. `frontend/components/PlayerPopup.jsx:994` and `frontend/components/TeamPhasePanel.jsx:166`: link
   `/league/franchise/<ownerId>` using an id from the private contract.
3. Public URLs that embed the id: `/league/franchise/<ownerId>`, `/league/rivalry/<idA>-vs-<idB>` (or `:`), the sitemap
   (`app/sitemap.js:118,127`), the franchise OpenGraph image, and `GET /api/public/league/franchise?owner=<id>`.
   Shared links and bookmarks in the wild use raw ids.

## 3. Why the id matters (inference, not tested)

Sleeper's documented public API resolves a user id to the account (`/v1/user/<id>`: username, display name, avatar) and
to every league that account plays in (`/v1/user/<id>/leagues/nfl/<season>`). If that holds, publishing the owner id
undoes two decisions the code already made: the league id is stripped from every public payload
(`RAW_SLEEPER_ID_FIELDS`), yet it is recoverable from any listed manager's league list; and the username, which no
payload carries, becomes recoverable. The display names and team names add little on top, because they are what Sleeper
shows to anyone who has the league. This is the argument for D1. It is an inference from documented endpoints; no call
was made.

## 4. Pseudonymization design (B1), for owner approval

**Replaces:** every Sleeper user id served on a public route: all field names in §2.1/§2.2, the 28 dict keys, the `?owner=`
query, `/player/{id}` and `/matchup/...` payload ids, the CSV id columns, and `/api/draft-capital`'s `ownerId`. It does not
touch display names, team names, avatars (D2/D3), roster ids, or transaction ids, and it does not touch private routes.

**The pseudonym.** `m_` + the first 13 characters of lowercase base32 of `HMAC-SHA256(key, leagueKey + "|" + ownerId)`.
Stable across seasons and restarts, different per league, not derivable from the Sleeper id without the key. Characters
are `[a-z2-7_]`, so it contains neither `-vs-` nor `:` (the rivalry slug separators) and needs no URL escaping. `key` is a
server secret (`PUBLIC_OWNER_PSEUDONYM_KEY`, same handling as the session secret). The 16 ids are asserted collision-free
when the table is built; a collision or a missing key fails closed (503), never falls back to the raw id.

**Where it lives.** One place: `public_contract.public_payload`, already the single serving projection for every public
route (it already drops `RAW_SLEEPER_ID_FIELDS`). It gains a closed-set substitution over the registry's manager ids
(`snapshot.managers.by_owner_id`): replace any string value or dict key that equals a known id. §2.1 shows value-plus-key
equality is exhaustive on the live payload (10,812 + 28 = 10,840, 0 substrings), so no field-name list is needed and a
new field cannot leak. `assert_public_payload_safe` gains the same check as a raising blocklist for the known ids, so a
payload that skips the projection fails closed, as the league ids do today.

**Joins keep working.** The frontend treats the id as an opaque string everywhere: no `Number()` or `parseInt` on an
owner id, no digit-only route validation (checked in `app/league`, `app/api/public`, `lib`, `middleware.js`). Map keys,
React keys, equality and `encodeURIComponent` all work unchanged on `m_...`. Inbound, the backend accepts either form for
`?owner=` and path ids and resolves both to the same manager (raw ids resolved only through the closed manager set, never
echoed). The response always speaks pseudonyms.

**What frontend must change (handoff text only; no frontend file is edited in this PR).**
1. Private-to-public joins (§2.4 items 1 and 2) need the pseudonym for the signed-in user's own team. Recommended: the
   private contract stamps `publicOwnerKey` on each `sleeper.teams[]` row and on `selectedTeam`, computed by the same
   function server-side, so no client ever computes it. The three call sites then read `publicOwnerKey`.
2. Stop displaying raw ids: `franchise/[owner]/page.jsx:161`, `sections/archives.jsx:149` and `:207`, and the
   `nameFor`/`DivisionOddsTable` fallbacks that print the id when a name is missing. Show the display name or the
   team name; the fallback should be "Unknown manager".
3. Old links: `/league/franchise/<rawId>` and `/league/rivalry/<rawA>-vs-<rawB>` should 308 to the pseudonym form. The
   server component can ask the backend to resolve (an operator-only internal call, not a public endpoint), because a
   public raw-to-pseudonym endpoint would be a membership oracle. Sitemap and OG images then emit pseudonyms.
4. Frontend tests: 76 test files mention `ownerId`. They use fixture strings and stay valid because the id is opaque.

**Migration.**
- Phase 0 (this PR): nothing changes.
- Phase 1: backend ships the substitution behind flag `public_owner_pseudonyms` (default OFF), the `publicOwnerKey`
  stamp on private contracts, and dual-form inbound resolution. Frontend ships items 1-3 and is verified against both
  forms.
- Phase 2: owner approves D1; set `RISKIT_FEATURE_PUBLIC_OWNER_PSEUDONYMS=1` and restart (flag reads are cached per
  process). The public memos are keyed by snapshot and must be cleared by the restart; `Cache-Control: public,
  max-age=60, stale-while-revalidate=300` bounds browser and CDN staleness at about 6 minutes, so raw ids age out of
  caches by then.
- Phase 3: after a quiet period, drop raw-id acceptance except through the redirect resolver.

**Rollback.** Unset the flag and restart: public routes serve raw ids again. Pseudonym links already shared keep working
because inbound resolution accepts both forms regardless of the flag. Rotating the key is a separate event that breaks
shared pseudonym links; support one previous key on input for a window if the owner ever rotates.

**Tests that must exist before enabling:** closed-set substitution equals the raw payload under inverse mapping; zero
raw ids remain in every route and CSV (a census run against the served bytes, using `scripts/public_surface_census.py`
and expecting 0); `?owner=` accepts both forms; franchise detail and rivalry slugs round-trip; private routes unchanged.

## 5. Performance

### 5.1 Measurements (production, `Accept-Encoding: gzip` for warm; first hit without)

Nothing measured here is a load test. "First hit" is the first request of this session; a data generation published at
14:31 UTC (`/api/health` `last_scrape`) landed between the first and third passes, and a pass-3 re-sample at about 14:39
showed the same cold costs again, so first-hit values are the cost paid by the first visitor after a publish or restart.
The network floor from this client is about 0.39 s (401 responses and the cheapest cached sections).

| Route | First hit s | Warm s (pass 1, pass 2) | Raw bytes | Gzip bytes |
|---|---:|---|---:|---:|
| `/api/public/league` | 5.16 | 1.38, 1.10 | 2,497,911 | 246,184 |
| `overview` | 0.63 | 0.39, 0.39 | 14,627 | 3,556 |
| `history` | 0.59 | 0.39, 0.51 | 23,235 | 3,499 |
| `rivalries` | 0.74 | 0.40, 0.69 | 78,573 | 7,931 |
| `awards` | 4.35 | 0.85, 0.65 | 189,287 | 21,583 |
| `records` | 4.99 | 0.59, 0.66 | 36,386 | 5,195 |
| `franchise` | 3.28 | 1.04, 1.03 | 111,701 | 11,352 |
| `activity` | 0.79 | 0.49, 0.62 | 207,158 | 17,351 |
| `draft` | 0.91 | 0.57, 0.90 | 216,896 | 17,961 |
| `weekly` | 1.74 | 0.48, 0.52 | 128,687 | 8,233 |
| `superlatives` | 0.68 | 0.56, 0.52 | 31,645 | 2,457 |
| `archives` | 2.47 | 0.97, 0.71 | 832,070 | 102,404 |
| `luck` | 0.89 | 0.60, 0.67 | 146,939 | 18,157 |
| `streaks` | 0.92 | 0.39, 0.40 | 30,361 | 3,453 |
| `matchupPreview` | 0.56 | 0.42, 0.59 | 18,330 | 3,217 |
| `weeklyRecap` | 0.98 | 0.60, 0.72 | 262,741 | 25,120 |
| `conduct` | 0.90 | 0.47, 0.44 | 43,411 | 10,834 |
| `playoffOdds` | **18.49** | 0.42, 0.48 | 10,930 | 2,400 |
| `rosPower` | 1.19 | 0.79, 0.71 | 281,069 | 22,749 |
| `rosPlayoffOdds` | **7.38** | 0.41, 0.42 | 17,819 | 3,748 |
| `rosChampionship` | 0.41 | 0.54, 0.41 | 9,674 | 2,221 |
| `/api/draft-capital` | 3.09 | 0.48, 0.44 | 146,680 | 8,945 |

Pass 3 (about 14:39, after the publish): `league` 0.98, `awards` 0.58, `records` 1.80, `franchise` 1.49, `playoffOdds`
**7.74**, `rosPlayoffOdds` 0.41, `draft-capital` **3.90**.

### 5.2 Where the cold time goes (from code)

- **`playoffOdds` (7-18 s) and `rosPlayoffOdds` (7 s).** `src/public_league/playoff_odds.py::build_section` reads the
  canonical forecast, `src/ros/playoff_sim.py::canonical_forecast`, which serves a file-backed payload only when
  `cached_forecast_matches_snapshot` holds and otherwise runs the 8,000-simulation Monte Carlo live (memoized in
  `_LIVE_MEMO`). After a publish the file cache no longer matches, so the first anonymous visitor pays the simulation.
  These sections are deliberately not in `_HEAVY_SECTION_KEYS` (a file-backed result keyed by snapshot alone would hide a
  newer ROS artifact; pinned by `tests/public_league/test_server_routes.py`).
- **`/api/draft-capital` (3-4 s).** A 300 s result cache keyed by league; a miss runs the workbook build, up to six
  blocking Sleeper calls and the dollar generation in the threadpool. A new contract generation or the TTL makes the next
  visitor pay it.
- **`awards`, `archives` (2.5-4.3 s).** Memoized per snapshot and board generation in `_heavy_section_cache`; a new
  generation makes the first visitor pay (stale-while-revalidate masks it for later ones within the staleness bound).
- **`records`, `franchise`, `weekly` (1.7-5 s first, 0.5-1.5 s warm).** Not memoized: every request calls
  `build_section_payload`. Only `awards`, `archives`, `overview` and `activity` are served from a memo.
- **Duplicated work found.** `franchise` recomputed the entire awards section and the rivalries section on every request
  (`franchise.build_section` falls back to `awards.build_section(snapshot)` when called with the snapshot alone), and
  each franchise page view issues that request twice (the page and its OpenGraph image). The full-contract path already
  avoids this by passing the awards it built.
- **Wire size.** The full contract is 2.5 MB raw; browsers receive 246 KB gzip. Clients that send no `Accept-Encoding`
  (curl by default) get all 2.5 MB.

### 5.3 What ships (backend-only, byte-identical)

1. **`franchise` reuses the memoized awards body** (`server.py::_exact_memoized_awards_body`, new optional
   `awards_section` argument on `build_section_payload`). Only an exact-key hit (same snapshot `generated_at`, same board
   etag) is used, never a stale entry; any miss falls back to the standalone build. `franchise` reads only
   `bySeason`/`seasonStatus`/`season`/`awards[].ownerId|key|label` of that section, none of which `public_payload`
   projects away.
   **Byte identity proof** (`tests/public_league/test_franchise_awards_reuse.py`): `json.dumps` of the franchise payload
   built fresh equals that built from the projected awards body (key order included); the route returns equal bytes with
   a warm awards memo and with none; the awards builder is called 0 times on a memo hit and once on a miss; a stale-key
   entry is rejected; the shared awards body is not mutated; other sections ignore the argument. Expected effect: the
   awards recompute leaves every franchise request. I did not measure the production effect (the change is not deployed).
2. **An anonymous `?refresh=` on `/api/draft-capital` is ignored** (same posture as `_authorized_force_refresh` on the
   public-league routes: ignored, not refused). Before, any non-empty value, `?refresh=0` included, skipped the 300 s
   cache and ran the full build inside a single-flight lock, so any caller could keep the worker busy with serialized 3-4 s
   builds, 60 per minute under the existing limiter. Found by reading `get_draft_capital`; I did not call it on
   production. No frontend or script uses it (the Next bridge does not forward `refresh`; searched `frontend/`,
   `scripts/`, `.github/`). Authenticated callers keep the forced rebuild. Pinned by
   `tests/api/test_draft_capital_anonymous_refresh.py` (anonymous `1`/`0`/`true`/`x` return the same bytes as the plain
   cached request and call the builder 0 times; an authenticated `1` still rebuilds). This one is a request-behavior
   change on a public route, not strictly a pure memo; D6 asks the owner to confirm it.

### 5.4 Opportunities not taken (need an owner or operator decision)

- **Memoize the remaining snapshot-pure sections** (`records`, `weekly`, `history`, `rivalries`, `superlatives`,
  `streaks`, `luck`, `draft`) by adding them to the heavy memo. Not done: the transitive import closure of each builder is
  237 modules and includes clock and file reads (e.g. `time.time` in `metrics`, `datetime.now` in `snapshot`), so "pure
  function of the snapshot key" is unproven, and a memo keyed on an incomplete input is a correctness bug. It needs a
  purity audit per builder plus a byte-identity test per section. Warm saving is about 0.2-0.6 s each.
- **Warm the cold paths after a publish.** `playoffOdds`/`rosPlayoffOdds` and `/api/draft-capital` could be warmed in
  the existing post-refresh hook (`_warm_overlays_in_background`) so no visitor pays 4-18 s. Needs the owner's view on
  background CPU after each ~2 hourly publish.
- **Share the rivalries section** between `franchise` and its standalone builder the same way as awards (smaller win).

## 6. Rate-limit proposal (operator; deploy and nginx not changed here)

**What exists.** `src/api/rate_limit.py`, applied in `server.py::_private_api_gate` to every public-allowlisted path
(including all `/api/public/league*` and `/api/draft-capital`): a per-client token bucket, **60 requests per minute and
1,000 per hour**, IPv6 keyed by `/64`, client identity taken from `X-Real-IP` set by nginx
(`deploy/nginx/chaseupside-proxy.conf:57`), bypass list `RATE_LIMIT_BYPASS_IPS` (empty by default), 429 with
`Retry-After`. nginx has no `limit_req` and no `proxy_cache` on `/api/`.

**Gaps.**
1. It is **cost-blind**. A 5 s cold rebuild and a 0.4 s cached read cost one token each, so 60 per minute on the
   expensive routes is far above what the worker can do.
2. The one amplifier found, anonymous `?refresh=`, is fixed in §5.3 but would have been the cheapest way to exhaust it.
3. **Verify, do not assume:** Next server-side renders (sitemap, OpenGraph images, franchise pages) call the backend from
   the Next process. If they arrive from `127.0.0.1` and `RATE_LIMIT_BYPASS_IPS` does not contain it, they share one
   60/min bucket. I could not read the box environment; the operator should check.

**Proposal.** In order of value:
1. **nginx microcache for anonymous public GETs.** The backend already sends `Cache-Control: public, max-age=60,
   stale-while-revalidate=300`. A `proxy_cache` zone with `proxy_cache_valid 200 30s`, `proxy_cache_lock on`,
   `proxy_cache_use_stale updating error timeout`, scoped to explicit `location` blocks for the public routes only (never
   `/api/*` generally), keyed on the full URI, and bypassed whenever a session cookie is present
   (`proxy_cache_bypass $cookie_<session>; proxy_no_cache $cookie_<session>`), turns N anonymous readers into one
   backend hit per 30 s per URL. Private routes must stay outside it.
2. **`limit_req` on the heavy routes**, started in dry-run:

   ```nginx
   # http {} context. Key on the IPv4 address or the IPv6 /64, matching the app limiter.
   map $remote_addr $rl_client {
       default                                      $remote_addr;
       "~^(?<net>[0-9a-f]{1,4}:[0-9a-f]{1,4}:[0-9a-f]{1,4}:[0-9a-f]{1,4}):"  $net;
   }
   limit_req_zone $rl_client zone=riskit_pub_heavy:10m rate=12r/m;

   # server {} context, one block per heavy route group (regex prefix, before `location /api/`):
   location ~ ^/api/(public/league(/(archives|awards|activity|draft|weeklyRecap|rosPower|playoffOdds|rosPlayoffOdds|luck|rivalries))?|draft-capital)$ {
       limit_req zone=riskit_pub_heavy burst=8 nodelay;
       limit_req_status 429;
       limit_req_dry_run on;          # log "dry run" decisions first (nginx 1.17.1+); remove after a week
       limit_req_log_level warn;
       # then the same proxy_pass / headers as `location /api/`
   }
   ```

   12 requests per minute with a burst of 8 allows one person to open several `/league` tabs (assumed, not measured: about one
   heavy request per tab) and blocks a loop. Numbers are a starting point for the operator to tune against the dry-run
   log; they are not measured against real traffic here.
3. **App level, cost-weighted tokens.** Charge heavy routes 5 tokens in the existing bucket, so the single owner of
   limiting stays `rate_limit.py` and heavy routes cannot burn 60 builds a minute. Needs a code change and owner sign-off
   on the weights; not made here.
4. Keep the existing `Retry-After` 429 body; the frontend already tolerates it.

## 7. Limits of this evidence

- One production sample per route for the cold figures, three for warm; the cold cause (publish vs restart) is inferred
  from `last_scrape`, not logged server-side.
- Census counts are for the 2026-11-15 payload; they move with the season.
- Consumer counts come from grep over `frontend/app`, `frontend/components`, `frontend/lib` (non-test); dynamic property
  access (`row[key]`) would not be found. Test files were counted separately, not classified.
- Nothing about Sleeper's API behavior was exercised; §3 is inference.
- The production effect of §5.3 is unmeasured until deploy.
