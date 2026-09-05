# W1-13 — public/private leakage audit, 2026-09-05

**Row:** `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` W1-13 — *"Public/private
leakage audit proves proprietary values, edges, targets, forecasts, or private
decision intelligence are not exposed publicly."*

**Method:** every check below was run **anonymously against production**
(`https://chaseupside.com`, no cookie, no session), plus a read of the gate's
own source. No fixtures.

**Verdict: no leakage. One real inconsistency found and repaired** — the
sitemap advertised a private route.

---

## 1. Public contract sections — 20 public, 4 private, no leaks

Every section key from `GET /api/public/league` fetched anonymously, and each
200 payload run through `public_contract.assert_public_payload_safe` (the
canonical field blocklist).

| result | count | sections |
|---|---|---|
| public, 200, blocklist **CLEAN** | 20 | overview, history, rivalries, awards, records, franchise, activity, draft, weekly, superlatives, archives, luck, streaks, **matchupPreview**, weeklyRecap, conduct, playoffOdds, rosPower, rosPlayoffOdds, rosChampionship |
| private, **401** to an anonymous caller | 4 | rosTeamStrength, rosTradeDeadline, faabAnalytics, teamAssignment |

`PRIVATE sections served 200 anonymously: NONE`.
`blocklist LEAKS on public sections: NONE`.

## 2. The semantic half — what a field-name denylist cannot catch

CLAUDE.md §5 is explicit that the boundary is **semantic, not a field-name
denylist**: a per-manager decomposition under a fresh key name would pass §1.
So the pregame and forecast surfaces were scanned again for **22 proprietary
markers** by substring on every key at every depth — `rankDerivedValue`,
`ourValue`, `canonicalConsensus`, `projectedPoints`, `projectedMean`,
`winMatchupPct`, `beatMedianPct`, `expectedLineup`, `recommendedBid`, `buyLow`,
`sellHigh`, `tradeTarget`, `weaknessScore`, `benchDepth`, `surplusValue`,
`consensusEdge`, `marketGap`, `arbitrage`, `maxBid`, `planMaxBid`,
`fundamentalValue`, `faabRecommend`.

| surface | bytes | markers |
|---|---|---|
| matchupPreview | 18,164 | **NONE** |
| weeklyRecap | 390,034 | **NONE** |
| playoffOdds | 9,471 | **NONE** |
| rosPower | 154,924 | **NONE** |
| rosPlayoffOdds | 8,198 | **NONE** |
| rosChampionship | 8,148 | **NONE** |
| overview | 15,109 | **NONE** |

The Week 1 pregame content is head-to-head record, recent form and factual
retrospect — exactly the public half of the split, and none of the private
half.

## 3. Private pages and APIs are closed

Anonymous, production:

| private page | result |
|---|---|
| `/matchup` (new), `/rosters`, `/waivers`, `/trade`, `/edge`, `/draft`, `/phases`, `/settings` | all land on **`/login`** |

| private API | result |
|---|---|
| `/api/matchup/intel` (new), `/api/roster/intelligence`, `/api/gameplan`, `/api/data`, `/api/terminal`, `/api/bdvm/values` | all **401 `auth_required`** |

**The API surface is default-deny, and that is the load-bearing fact.**
`server.py::_private_api_gate` 401s *every* `/api/*` path without a session
unless it is on an explicit allowlist (`_PUBLIC_API_EXACT`,
`_SELF_AUTHED_API_EXACT`, `_PUBLIC_API_PREFIXES`). So a new private endpoint is
closed **before it is deployed** rather than because someone remembered to
protect it — `/api/matchup/intel` already answered 401 on production while the
PR that adds it was still open. `/matchup` is closed by the mirror-image rule
in `public-routes.js`, which treats every path outside its allowlist as
private, so the new route needed no entry there either.

Both properties are structural, not observations, which is why they are worth
recording as the reason rather than the result.

## 4. The finding — the sitemap advertised a private route

`frontend/lib/public-routes.js` names its consumers in its own docstring and
says it exists *because those consumers used to disagree*:

> One predicate, three consumers: `middleware.js`, `AppShellWrapper.jsx`,
> `robots.js`. It lives here, pure and dependency-free, because those three
> used to disagree.

**`frontend/app/sitemap.js` is a fourth consumer that was never wired to it**,
and it had drifted the same way. Measured on production:

```
sitemap.xml            1,276 entries, including  /trades
public-routes.js       "/trades … this route is private"
GET /trades  (anon)    302 -> /login?next=%2Ftrades
robots.txt             Disallow: /   (allows only /$, /login, /league, /league/)
```

**Nothing leaked.** `robots.txt` disallows the path, and the page redirects an
anonymous visitor to `/login`, so no private data was ever served. But a
sitemap is a **positive assertion that a URL is worth indexing**, it is
submitted to search engines, and it contradicted `robots.txt` on the same host.
That is precisely the drift `public-routes.js` was written to end.

`/draft-capital`, the other non-`/league` entry, is correct: it is in
`PUBLIC_EXACT` as a legacy shim and production redirects it to
`/league?tab=draft-capital`.

### Repair

`sitemap.js` now **filters its static list through `isPublicPath`** — the same
predicate `robots.js` already imports. Filtering rather than deleting the
`/trades` line, because a hand-edited list drifts again the next time a route
changes sides; query-string entries are checked on their pathname.

Pinned by `frontend/__tests__/sitemap-public-only.test.js` (3 tests), which is
structural on purpose: the drift is a one-line addition to an array and is
invisible in review. **Mutation-proved** — replacing the filter with
`.filter(() => true)` turns 2 of the 3 red, and restoring it returns them to
green. The third test asserts the sitemap still carries `/`, `/league`,
`/draft-capital` and the `?tab=` entries, so a filter that emptied the sitemap
could not pass the first two vacuously.

## 5. Row status

**W1-13 → `VERIFIED`.** The row's acceptance is that an audit *proves* the
claim, and this is that audit, run against production with the evidence above:
20 public sections clean on both the field and the semantic check, 4 private
sections closed, 8 private pages and 6 private APIs closed, and the one
inconsistency found is repaired and test-pinned.

The repair itself is not yet deployed. That does not gate this row — the
sitemap entry was never a leak (robots disallowed it, the page redirected) and
the row asks for the audit, not for a fix to ship. It **is** noted here so the
next reader does not mistake "audited" for "the sitemap on production is
already filtered": production will still list `/trades` until the next deploy.
