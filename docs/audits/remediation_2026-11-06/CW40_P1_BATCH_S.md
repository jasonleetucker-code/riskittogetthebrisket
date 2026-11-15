# CW-40 Batch S: adjudication of 12 security / auth / privacy / ops / test-integrity P1 findings

Adjudicated against `main` at `17d8bd7290` (2026-11-07), the same way `CW40_P0_ADJUDICATION.md`,
`CW40_P1_OPEN_ADJUDICATION.md` and `CW40_P1_UNADJUDICATED.md` did. The November recount labelled these
"repro_rotted" / "unsafe-to-rerun", so no evidence either way. Every check is offline and deterministic
(TestClient, stub providers, source-shape scans, `git ls-files`, workflow YAML). No network, no production, no live
board. **No code behavior changed in this PR**: the three W22 security findings were already repaired on `main`
(so no security fix was needed here); the open items get strict xfails and a smallest-repair note.

CW-07 is recorded MERGED in `build_inventory.py`. Verified rather than trusted: the redirect fix is `2b566a25bf`
(2026-08-05), the throttle `ff4986e413` (#1115, 2026-08-25), the trusted-proxy identity `dc3a41201c` (#1112) then
`src/api/client_ip.py` (B0-h, 2026-10-19). All three are live and pinned (below). CW-07's remaining scope
(draft-capital boundary) is outside this batch.

| id | verdict | evidence | test | repair | gate |
|---|---|---|---|---|---|
| W22-F001 | CLOSED_VERIFIED | `server.py:1003-1048` rejects `\`, control chars, scheme/netloc, `//`; used at `:18088` | `test_audit_cw40_batch_s_closed.py` (end-to-end login) + `test_next_path_sanitizer.py` | none | n/a |
| W22-F002 | CLOSED_VERIFIED | `server.py:4891-4902` -> `src/api/client_ip.py` (proxy headers only from trusted peer, last XFF) | closed.py (rotating XFF vs `/api/health`) + `test_client_ip_trust.py` | none | n/a |
| W22-F003 | CLOSED_VERIFIED | `rate_limit.py:342-476` `login_*`; wired `server.py:18066-18085`, checked before credential compare | closed.py (30 wrong passwords, spoofed headers -> 429 + `Retry-After`) + `test_login_throttle.py` | none | n/a |
| W09-F007 | REPAIRED | `frontend/app/api/trade/suggestions/route.js:9-27` never reads the cookie; finder/angle routes do | `audit-w09-f007-regression.test.js` (`it.fails`) | 2 lines (below) | routine |
| W21-F003 | REPAIRED | `server.py:19270`, `:19409` pass `resolved_team["name"]`; `terminal.py:1317-1320`; `news/service.py:233-245,424` | open.py (strict xfail) | pass `team_name=None` / filter on roster players | routine (see section) |
| W03-F010 | CLOSED_VERIFIED | `data_contract.py:7804-7885` read-only; snapshot + `write_snapshot` deleted | closed.py + `tests/history/test_temporal_red.py:93` | none | n/a |
| W24-F001 | OPEN | no union skip census, no executed/skip floor gate (`pr-validation.yml:339,359`); 443 sites now vs naive count | open.py (characterization + strict xfail) | union census script + floor gate | routine (CI) |
| W24-F002 | OPEN | `test_real_rosters.py:59,64,87`: `nfl_players_full.json` untracked; 22 skipped | open.py (strict xfail) | commit trimmed fixture / archive-derived dump | routine |
| W24-F004 | OPEN | `e2e.yml:387,409` sets `SKIP_VISUAL_REGRESSION=1`; both specs skip whole describe | open.py (strict xfail) | drop env, skip only `toHaveScreenshot` | routine (CI) |
| W25-F010 | PARTIAL | verdict verified; finder fix `a62af217` not an ancestor of audited `9c5d972f`; header cross-refs absent | open.py (chronology pass + header xfail) | add header pointers | routine (docs) |
| W26-F004 | CLOSED_VERIFIED | `bdvm_api.py:150-199` loads snapshot / `cache_only=True`, never fetches | `tests/bdvm/test_request_path_is_local.py`, `test_http_route_no_fetch.py` (35 pass) | none | n/a |
| W20-F006 | PARTIAL / REQUIRES_OWNER_DECISION | `scoreTeamTiers` gone; three classifiers remain reachable | open.py (characterization + strict xfail) | owner picks the canonical classifier | owner |

Tally: **5 CLOSED_VERIFIED** (W22-F001/2/3, W03-F010, W26-F004), **5 OPEN** (W09-F007, W21-F003, W24-F001,
W24-F002, W24-F004), **2 PARTIAL** (W25-F010, W20-F006). Tests: `tests/api/test_audit_cw40_batch_s_closed.py`
(11 pass), `tests/api/test_audit_cw40_batch_s_open.py` (6 pass + 6 strict xfail),
`frontend/__tests__/audit-w09-f007-regression.test.js` (3 pass + 1 `it.fails`).

## W22-F001 (open redirect via backslash) - CLOSED_VERIFIED

**Claim.** `/login?next=/\evil.com` passed every string guard and was returned verbatim.
**Live path.** `_sanitize_next_path` (`server.py:1003-1048`) refuses control characters and any backslash, then
parses with `urlsplit` and refuses any scheme/netloc or `//` prefix, re-emitting the parsed form. The login route
calls it at `:18088`; `frontend/lib/safe-next.js` mirrors it client side and re-checks the serialized output.
**Evidence.** Added end-to-end test posts `next` = `/\evil.com`, `/\\evil.com`, `/\tevil.com`, `//evil.com`,
`https://evil.com` to the real login route and asserts the returned `redirect` is `/`; a legitimate `/trade?x=1`
round-trips. Unit pins: `test_next_path_sanitizer.py`.

## W22-F002 (rate limiter keys on client X-Forwarded-For) - CLOSED_VERIFIED

**Live path.** `server.py:4891-4902` delegates to `src/api/client_ip.py`: `X-Real-IP` then the LAST XFF entry,
honoured only when the TCP peer is loopback or in `RATE_LIMIT_TRUSTED_PROXIES`, only if it parses as an IP;
otherwise the TCP peer. IPv6 buckets by /64 (`rate_limit.py::_site_bucket_key`). Backend binds loopback by default
(#2050).
**Evidence.** From an untrusted peer, 80 `/api/health` requests with rotating `X-Forwarded-For` hit the 60/min
limit (429). Unit pins: `test_client_ip_trust.py`.

## W22-F003 (login has no throttle) - CLOSED_VERIFIED

**Live path.** `rate_limit.py:342-476`: 5 free failures per 15 min window, then 1s doubling to a 60s cap, keyed by
IP and (IP, username), never username alone; `server.py:18066-18085` checks BEFORE comparing credentials and answers
429 `too_many_attempts` + `Retry-After`; success clears state.
**Evidence.** 30 wrong passwords with rotating spoofed headers trip a 429; the CORRECT password is then also 429
during backoff (check precedes comparison). Unit pins: `test_login_throttle.py` (clock-driven, isolation,
cool-off). Residual (not a defect of this finding): in-memory per process, so a multi-worker deploy multiplies the
free attempts; production runs one uvicorn process.

## W09-F007 (suggestions bridge drops the session cookie) - REPAIRED

**Live path.** `frontend/app/api/trade/suggestions/route.js:9-27` builds headers `{"Content-Type"}` only.
`finder`, `angle/find`, `angle/packages` read `request.headers.get("cookie")` and forward it. `/api/trade/suggestions`
is private, so in dev / the E2E stack (Next serves `/api/*`) the page's call is anonymous. Production unaffected
(nginx). `bridge-routes-forward-cookies.test.js` could not see it: it walks only `proxyGet/proxyPost` routes.
**Evidence.** `it.fails` in `audit-w09-f007-regression.test.js`; the three siblings are pinned passing.
**Smallest repair.** `const cookie = request.headers.get("cookie") || "";` and `Cookie: cookie` in the fetch
headers (2 lines). Routine. Adjacent observation, not adjudicated: `app/api/scrape/route.js` and `app/api/news/route.js`
are also raw-`fetch` bridges with no cookie read (`public/*` ones are public by design); worth a follow-up check
and a widened guard test.

**Repaired in this PR.** `suggestions/route.js` now reads the `cookie` header and forwards it, exactly as the
finder and angle bridges do (no new helper; they hand-roll the same two lines). The `it.fails` is now a plain `it`.
Adjudication of the two adjacent bridges: `/api/scrape` REQUIRES the session (backend `trigger_scrape` calls
`_require_admin_session`, W22-F007), so the same defect applied; `scrape/route.js` now forwards the cookie and the
guard test pins it. `/api/news` is deliberately public (`/api/news` is in the backend's public-path set: no
rosters, rankings or user state; the public `/league/player/<id>` page consumes it), so it is left unchanged.

## W21-F003 (terminal news filtered by fantasy team name) - REPAIRED

**Live path.** `server.py:19270-19275` (and `:19409-19414` for `/api/signals/reconciled`) pass the resolved FANTASY
team name; `terminal.py:1317-1320` forwards it as `team_names=[...]`; `news/service.py:233-245` intersects it with
`{p.name for p in item.players}` (NFL player names). A resolved team therefore drops every item.
**Evidence.** Stub provider with one item mentioning Josh Allen: `gather_news_items(..., "Jason")` returns `[]`
(strict xfail) while `gather_news_items(..., None)` returns the item (control passes).
**Smallest repair.** Stop passing the fantasy team name as `team_names` (pass `None`; the roster scoping the
feature wants is player-name based and already handled by `live_names`). Routine, but it changes what authenticated
terminal users see and re-activates news-driven signal rules, so land with a before/after on a pinned fixture
board; flip the xfail in the same PR.

**Repaired in this PR.** `gather_news_items` no longer forwards the fantasy team name as `team_names`; its third
argument is now informational only. A new `roster_player_names` kwarg (built by `terminal.roster_player_names`
from the resolved `sleeper.teams` entry's `players`) is what scopes news, so a roster player's item is kept and a
non-roster player's is dropped. Both server.py call sites pass it; no roster (or an empty one) keeps the unfiltered
path. The strict xfail is now a plain passing test, plus a roster-inclusion/exclusion regression test. No values or
ranks change.

## W03-F010 (overrides rewrites the shared rank snapshot) - CLOSED_VERIFIED

**Live path.** C1-U4 deleted `data/snapshots/ranks_last.json` and the `write_snapshot` parameter.
`_stamp_rank_changes` (`data_contract.py:7804-7885`) derives `rankChange` read-only from the temporal ledger's
previous board date; no build kind (override bodies included) writes a baseline.
**Evidence.** Added tests: signature has no `write_snapshot`; the function body contains no write primitive; a call
with an absent ledger returns `rankChange: None` (never 0) and creates no file; no executable reference to
`ranks_last.json` remains in `src/` or `server.py`. Existing: `tests/history/test_temporal_red.py:93`.

## W24-F001 (skip census undercounts) - OPEN

**Claim.** The audit's census greps only `pytest.skip(` and misses unittest-style skips.
**Live state.** The evidence file is a frozen audit artifact; the recommended repair never shipped: there is no
union census tool and `pr-validation.yml:339,359` runs pytest with no `--junitxml`/skip ceiling/executed floor.
Re-measured with the union pattern today: 443 skip sites in 197 files (naive pattern far lower), pinned as a
characterization. `test_livedata_policy.py` polices the livedata list, not skip counts.
**Evidence.** Strict xfail asserts a floor/skip-budget gate exists.
**Smallest repair.** A `scripts/` union census plus a skipped-count ceiling read from `--junitxml` in the hard gate.
Routine CI work; touching the workflow makes it L2/L3-sensitive, so land as its own PR.

## W24-F002 (real-roster variation guards never execute) - OPEN

**Live path.** `test_real_rosters.py:59` marks the module `livedata`; the fixture needs
`data/public_league/nfl_players_full.json` (`:64`, skip at `:87`), which is gitignored and absent in CI. Progress
since August: `data/sleeper_last_good.json` and `data/ros/aggregate/latest.json` are now tracked (pinned passing).
**Evidence.** `pytest tests/roster_intel/test_real_rosters.py -rs`: 22 skipped (this checkout). Strict xfail asserts
all three inputs are tracked.
**Smallest repair.** Commit a trimmed eligibility/age extract (the fixture needs only `fantasy_positions` and `age`
for rostered players) or build it from a tracked archive, then drop `livedata` from the pure-logic parts. Routine.

## W24-F004 (E2E visual skip swallows structural assertions) - OPEN

**Live path.** `e2e.yml:387` and `:409` set `SKIP_VISUAL_REGRESSION: "1"`; both specs start with
`test.describe(... test.skip(!!process.env.SKIP_VISUAL_REGRESSION ...))`, skipping every test including those the
workflow comment says "still run their structural assertions".
**Evidence.** Characterization (both specs skip the whole describe) passes; strict xfail asserts CI does not.
**Smallest repair.** Remove the env var from both steps (`--ignore-snapshots` already neutralizes pixel
comparisons) and gate only the `toHaveScreenshot` calls. Routine, but it adds E2E runtime and may surface latent
failures; dispatch the E2E workflow on the PR to measure first.

## W25-F010 (two prior audits reconciliation) - PARTIAL

**Verdict re-verified.** The 08-04 audit's finder claim was fixed by `a62af217` (2026-08-04 13:16), which is NOT an
ancestor of the audited `9c5d972f` (`git merge-base --is-ancestor` exit 1); IDP routing is pinned by
`tests/trade/test_finder_idp_routing.py`. The reconciliation (spine vs decision layer) stands.
**Not shipped.** The recommended header cross-references (object audited, SHA, pointer to the other audit) are
absent from both audit documents (strict xfail). Docs-only, routine.

## W26-F004 (bdvm roster spends 48 s on discarded downloads) - CLOSED_VERIFIED

**Live path.** The request path no longer fetches: `_context_for` loads a materialised snapshot
(`bdvm_api.py:150-180`), `_schedule_for` uses `cache_only=True` (`:182-195`), actuals likewise. `scripts/refresh_bdvm_inputs.py`
writes the snapshot off the request path. The 48 s cold download and the 60 s retry cannot occur per request.
**Evidence.** `tests/bdvm/test_request_path_is_local.py` and `test_http_route_no_fetch.py` (35 pass on this head;
network is patched to fail). Residual: with `snapshot is None` the context/schedule loads still run (now cheap
local reads, not downloads); skipping them would save milliseconds only.

## W20-F006 (four team-direction classifiers) - PARTIAL / REQUIRES_OWNER_DECISION

**Live state.** `scoreTeamTiers` (/rosters) is retired (W20-F007). Three remain reachable with different
vocabularies: `frontend/lib/team-phase.js::classifyPhase` (/phases, client 2x2 median split),
`src/roster_intel/window.py::competitive_posture` (PUSH/HOLD/RETOOL/REBUILD, the CLAUDE.md-documented owner) and
`src/ros/direction.py::classify_team` (public ROS buyer/seller; CLAUDE.md names it a separately named concept).
**Evidence.** Characterization (three owners) passes; strict xfail asserts one.
**Repair / gate.** Choosing the canonical classifier and the display vocabulary is owner methodology; the routine
step after the decision is to make `/phases` read `competitive_posture` (a frontend materializer, not a client
classifier). Not attempted here.
