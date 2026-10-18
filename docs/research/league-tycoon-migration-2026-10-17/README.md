# League Tycoon migration: research and engineering blueprint

**Status:** RESEARCH ONLY. Nothing here authorizes implementation. `docs/EXECUTION_PLAN.md` is the only
authorization record, and no migration, provider adapter or contract model is authorized today. The
owner-intake pointer is `docs/OWNER_REQUESTED_TODO.md` → "Added 2026-10-17 — League Tycoon migration research".

**Date:** 2026-10-17. Repo base `ae489e18` (`main`). **Scope:** this Calculator repository only. The Market
Edge Lab repository is out of scope and was not touched.

**Owner authorization on record (2026-10-17):**

- The league owner has authorized **read-only** collection of **their own** League Tycoon league's data,
  including data that needs the owner's signed-in session.
- The authorization does not cover other leagues, other users' accounts, platform administration, or any
  write to League Tycoon.
- The owner restated it during this session: "I have permission to scrape my own league."
- See §1.5 for how this interacts with League Tycoon's own Terms of Use. That was the single largest risk in
  this document, and it is now **resolved by League Tycoon's written permission** (next bullet).
- **League Tycoon's written permission (2026-10-17).** support@leaguetycoon.com, signed "George", replied to the
  owner's "League Scrape Inquiry" (addressed to the owner, 9:11 AM; shared as a screenshot of the owner's mail
  client): *"Yeah that is totally
  fine, you can scrape our site sir whatever you need to get all of the same information that you were able to
  get from Sleeper's API."*
  - **Retention.** The owner keeps the original email, with full headers, outside the repo. That copy is the
    durable evidence.

**What this research could and could not do:**

| Done | Not done (and why) |
|---|---|
| Read all 51 public pages in leaguetycoon.com's sitemap, including the Terms, contract rules and the league-import docs | No signed-in observation of League Tycoon. Sign-in is Google/Apple only, and this research never asks for or handles the owner's credentials. |
| Inspected the public app shell at `app.leaguetycoon.com` | Did not decompile or reverse-engineer the app bundle. The Terms prohibit it, and it isn't needed to plan. |
| Verified candidate id `1416568994525167616` against Sleeper's public API | Could not verify that id against League Tycoon (no session). |
| Full read-only audit of every Sleeper dependency in this repo (four parallel audits, file:line evidence) | No code, config, production or Sleeper behaviour was changed. |

Companion files in this directory:

- [`SLEEPER_DEPENDENCY_INVENTORY.md`](SLEEPER_DEPENDENCY_INVENTORY.md): every Sleeper endpoint, every
  consumer feature, every Sleeper-keyed store, and the hidden-coupling catalog (Phase 2).
- [`PARITY_MATRIX.md`](PARITY_MATRIX.md): Sleeper field → League Tycoon counterpart → availability → consumers
  (Deliverable 2), plus the feature impact report (Deliverable 6).
- [`OWNER_EVIDENCE_CAPTURE.md`](OWNER_EVIDENCE_CAPTURE.md): the exact, minimal steps the owner performs to
  unblock verified data access (Deliverable 4 detail, Phase 6 procedure).

Evidence labels follow the brief:

- **VERIFIED**: observed and tested here.
- **DOCUMENTED**: stated by League Tycoon's own published pages.
- **INFERRED**: strongly suggested, not tested.
- **UNKNOWN**: insufficient evidence.
- **UNAVAILABLE**: investigated, not offered.

---

## Deliverable 1: Executive assessment

**Can we realistically replace Sleeper with authorized League Tycoon data for this league?**

**Yes, for the league-scoped half of what Sleeper gives us, conditionally.** Three conditions, in order of
severity:

1. **Access is unproven, and the platform forbids automation.**
   - League Tycoon publishes **no API, developer program, export, CSV or webhook** (UNAVAILABLE under every
     public source examined).
   - Its Terms of Use (last updated 2026-05-14, §4) prohibit
     *"bots, scripts, scrapers, automated agents, or any other automated means to access, interact with, or
     extract data from the Service"*, and prohibit reverse engineering.
   - Enforcement is at League Tycoon's sole discretion. The remedy includes termination with forfeiture of
     *"league standings, draft picks, contracts"* (§3/§4).
   - The owner's permission covers the league's data. It cannot waive the platform's terms on the owner's
     own account.
   - **UPDATE 2026-10-17: League Tycoon support granted written permission** to scrape for "all of the same
     information that you were able to get from Sleeper's API". Method B is now sanctioned rather than
     risk-accepted. See §1.5 for the scope boundary (contract/cap data is not Sleeper data).
2. **The league's format may not survive the move.** Nothing public confirms League Tycoon supports:
   - **IDP** (DL/LB/DB starters), or
   - **best ball**.

   `dynasty_main` ("Risk It To Get The Brisket") is **both**. It is 12 teams, best ball, 3 DL / 3 LB / 3 DB
   starters, 17 `idp_*` scoring keys of 148, 2 TE + SUPER_FLEX + K, and 58-man rosters (VERIFIED against
   Sleeper's public API today).
   - If League Tycoon cannot host IDP or best ball, the league itself changes format.
   - Then "parity" means modelling a **different** league correctly, not reproducing today's.
   - This is a 10-minute question to League Tycoon support and must be answered **before** anything else.
   - Its import preview also lists unmappable scoring and roster rules by name, which is a second free
     check.
3. **Sleeper stays in the system either way.**
   - About half of our Sleeper usage is **global**: the player directory, NFL state, weekly stats,
     projections, trending, Sharp cohort crawls of other leagues, and the username portfolio. None of that is
     league-hosted, and League Tycoon cannot replace it.
   - Sleeper also remains the **only** record of this league's pre-migration transactions and trades.
     League Tycoon's import rebuilds standings, matchups, lineups, brackets and the Hall of Fame. It does
     **not** list transactions or trade history among what it imports (DOCUMENTED by omission on
     `/features/league-import/` and `/learn/how-to-switch-from-sleeper/`).
   - The correct target is therefore **Sleeper for seasons ≤ the cutover season, League Tycoon after**. It is
     not "replace Sleeper".

**What League Tycoon adds** (DOCUMENTED):

- per-player salary and multi-year contracts;
- cap space, holdback, rollover and dead money (two-season lump-sum rule);
- extension, franchise-tag and rookie-option state;
- RFA tenders with right-to-match and compensation picks;
- auction and contract-bidding outcomes;
- cap-space trading;
- compensatory picks and a draft lottery.

These are high-value inputs **if** the league runs as *contract dynasty* (paid, $11.99 per team per season) and
**if** they can be collected. They are not available on a standard-dynasty League Tycoon league.

**Bottom line:**

- The engineering is tractable. The repo already has the seams we need:
  - one league registry;
  - a season-chain concept;
  - a `src/platforms/` adapter protocol;
  - single owners for identity, picks, lineup and history.
- The blockers are **not** engineering:
  - a platform-format answer (IDP / best ball);
  - ~~an access-posture decision~~ (resolved 2026-10-17: League Tycoon granted written permission);
  - one owner-run evidence capture.

  Until those land, no data-access claim in this document is better than DOCUMENTED, and **no integration
  should be called ready**.

---

## 1. Phase 1: League Tycoon as it exists today

### 1.1 Platform facts

| Fact | Evidence | Label |
|---|---|---|
| Operator: Figment Labs LLC; support@leaguetycoon.com; Discord community | `/terms/`, `/support/` | DOCUMENTED |
| Marketing site is Next.js. The app is a separate **Flutter web** build at `app.leaguetycoon.com` (also iOS `id1488816698`, Android `io.figmentlabs.leaguetycoon`) | App shell HTML: `flutter_bootstrap.js`, a Flutter-team comment, `<meta name="robots" content="noindex">` | VERIFIED (shell only) |
| Sign-in is **Google or Apple only**. There are no League Tycoon passwords | `/support/account-help/`; app shell carries `google-signin-client_id`, preconnects to `appleid.cdn-apple.com` | DOCUMENTED + VERIFIED |
| Backend is Google Firebase in some capacity | App shell `dns-prefetch` to `firebasestorage.googleapis.com` | VERIFIED that it's referenced; INFERRED that Firebase Auth/Firestore/Functions carry league data |
| Player/game data comes from a third-party sports data provider; in 2024 that was SportsDataIO | Terms §10 ("third-party sports data providers"); a 2024 urlscan of the old site loaded a `sportsdata.io` partner badge | DOCUMENTED (a provider exists) / INFERRED (it is SportsDataIO today) |
| Ships about twice a week (iOS 7.0.24 → 7.3.16 between May and Oct 2026, generic release notes) | App Store version history | VERIFIED. **Implication:** any unofficial interface will churn |
| Superflex supported | App Store description ("superflex formats") | DOCUMENTED |
| TE premium exists (at least as a format bonus) | Gambit format page; a 2021 App Store review says the developer added TE premium on request | DOCUMENTED (weak) |
| **IDP** | No mention on any of 51 site pages, the App Store listing, or the FantasyPros May 2026 platform review | UNKNOWN (absence of evidence) |
| **Best ball** | Same | UNKNOWN (absence of evidence) |
| Season ends at Week 17. Playoffs default Week 15, 6 teams (10+ team leagues). Trade deadline default Week 9 | `/rules/contract-league-rules/` | DOCUMENTED |
| Rookie draft formats: linear (default), snake, offline. **No rookie auction**. Contract leagues' *free-agent* draft can be live auction, slow auction or contract bidding | Same | DOCUMENTED. Our rookie auction (Perfect Draft, Rookie Auction Room) has no direct counterpart |
| Draft order: weighted lottery (default), inverse standings, max-points-for, manual | Same | DOCUMENTED. Our `draft_order.py` rule (reverse record, PF tiebreak) is config for `dynasty_main` only |
| Waivers: "default" mode plus FAAB-only mode. FAAB tiebreak: lower standings, then more cap. FA pickups get 1-year contracts at the bid | Same | DOCUMENTED |
| Taxi is replaced by a **practice squad** with per-player permanent eligibility (25% / 0% PS dead money) | Same | DOCUMENTED |
| IR has three modes (traditional, full-season, end-of-season) | Same | DOCUMENTED |

### 1.2 Answers to the ten Phase 1 questions

| # | Question | Answer | Label |
|---|---|---|---|
| 1 | Official API? | None published. No developer docs, partner program or public repo found (site, App Store, web search) | UNAVAILABLE (public) |
| 2 | Machine-readable web interface? | The Flutter app must fetch league data over the network, so *some* machine-readable channel exists. Which one (Firestore listen channel, Cloud Functions REST/JSON, gRPC-web, custom REST) is not knowable without a signed-in capture | INFERRED exists / UNKNOWN form |
| 3 | Requests made when opening a league | Requires the owner capture in `OWNER_EVIDENCE_CAPTURE.md` | UNKNOWN |
| 4 | Mobile app has data the web lacks? | League Tycoon says web and mobile are "same account, same data" with a "full web experience" | DOCUMENTED (parity claimed) |
| 5 | Can a member see every team's roster, transactions, picks, contracts? | Trade auctions are league-visible. Hall of Fame and standings are league-wide. Cap compliance is enforced on both sides of a trade, so other teams' cap is visible at least to the engine. Per-team roster and contract screens for *other* teams are implied but not confirmed | INFERRED |
| 6 | Commissioner-only data/operations? | Yes: comp-pick assignment, HoF editing, draft controls (pause/undo/nominate for a team), trade review/veto settings, rollover date, lottery ball edits | DOCUMENTED |
| 7 | Existing export/integration? | Import only (Sleeper, ESPN, CBS, MFL, Fantrax → League Tycoon). No outbound export of any kind | DOCUMENTED / UNAVAILABLE (export) |
| 8 | Sync without repeated manual interaction? | Possible only with a long-lived session (§4.2). If Firebase Auth is used, refresh tokens are long-lived and ID tokens last 1 h. That is how the app itself stays signed in | INFERRED |
| 9 | Authentication and session refresh | Google/Apple OAuth, then a League Tycoon session in the Flutter app. Token type, storage and refresh path are unobserved | INFERRED / UNKNOWN |
| 10 | Supported vs confirmed vs hypothetical | Supported: none for outbound data. Confirmed: none yet. Hypothetical: Methods B and C below | — |

### 1.3 Candidate league id `1416568994525167616`

- **Not a Sleeper league.** `GET https://api.sleeper.app/v1/league/1416568994525167616` returns `404` / `null`
  (VERIFIED 2026-10-17). Both registry leagues resolve normally: `dynasty_main` = "Risk It To Get The Brisket",
  2026, `in_season`; `dynasty_new` = "Blood, Sweat, and Beers", 2026, `in_season`.
- The id is in no file in this repo.
- Its 19-digit snowflake shape is consistent with a League Tycoon id, but that is **UNKNOWN** until the owner
  capture shows it in a League Tycoon URL or response.
- **Do not hard-code it anywhere until then.**

### 1.4 Ranked access methods

The brief's Methods A–D, scored 1 (worst) to 5 (best). Coverage and reliability are **INFERRED** for B–D, because
no method is verified yet.

| Rank | Method | Coverage | Reliability | Auth complexity | Maintenance | Refresh | Op. cost | Risk |
|---|---|---|---|---|---|---|---|---|
| **1 (if obtainable)** | **A. Sanctioned access**: written permission from League Tycoon, ideally a read token, export or partner feed | 5 | 5 | 3 | 5 | 4 | 5 | **None.** Removes the §1.5 risk |
| **2 (primary; sanctioned 2026-10-17)** | **B. Owner-session network capture**: an owner-run collector loads the app under the owner's own signed-in session and keeps the JSON the app already fetches, or replays those exact read requests at low rate | 4 | 3 | 2 | 2 (≈2 releases/week) | 3 | 4 | **Low** since League Tycoon's written permission (§1.5). Still human-paced and read-only |
| 3 | **C. Browser automation of the rendered UI** | 2 | 1 | 2 | 1 | 2 | 3 | Same Terms risk as B, worse data. Flutter web draws to a canvas, so there is no DOM table to read; only the semantics/accessibility tree, if enabled (INFERRED) |
| **4 (fallback)** | **D. Manual-assisted**: owner screenshots (reusing our shipped Screenshot Import / Tesseract OCR lane), owner-entered contract CSV, commissioner HoF | 3 | 4 | 5 | 4 | 1 | 2 (owner time) | **None** on Terms. Bounded by owner effort |

**Recommendation:**

1. **Ask first.** DONE 2026-10-17: League Tycoon support granted written permission (§1.5). Still open:
   - the IDP / best-ball question (OD-3);
   - whether an export or read endpoint exists, which would make Method A available;
   - confirmation that contract/cap pages are in scope.
2. **Primary:** Method **B**, scoped and paced as in §4. Permission is granted. If League Tycoon later offers a
   sanctioned feed, Method A replaces B.
3. **Fallback:** Method **D** for anything B cannot reach, and as the continuity plan if the account is ever
   challenged. Contract tables change mainly at a few calendar moments (rollover, drafts, trades), so manual
   capture is a credible floor for the contract domain.
4. **Rejected:** Method **C**. Flutter canvas rendering gives it the worst coverage-to-risk ratio.

### 1.5 The Terms-of-Use problem, stated once

The owner's authorization and League Tycoon's Terms are different instruments. The owner can authorize use of
the league's data. The Terms bind **the account holder**, and §4 prohibits automated access regardless of whose
data it is.

The consequence is borne by the same account that holds the league: possible termination, with no appeal or
restoration of standings, picks or contracts (§3–§4).

This blueprint therefore:

- never designs anything that writes, impersonates, or touches another account or league;
- keeps request volume at or below what a human browsing the app would generate (§4.4);
- keeps every League Tycoon fetch **behind a single kill switch**, so the integration can be stopped instantly;
- treats written permission from League Tycoon as the cheapest risk removal available. One email.

**Resolution (2026-10-17).** League Tycoon support replied in writing:

> "Yeah that is totally fine, you can scrape our site sir whatever you need to get all of the same information
> that you were able to get from Sleeper's API." (George, support@leaguetycoon.com)

What this changes, and the boundary we keep:

- **Sanctioned scope.** Everything with a Sleeper counterpart is now sanctioned to collect: the whole of
  `PARITY_MATRIX.md` §A1–§A5. Method B is the primary method, and option S3 (§4.2) is no longer excluded on
  Terms grounds.
- **Contract and cap data.** §A6 has no Sleeper counterpart. "Whatever you need" plausibly covers it, but the
  literal measure is Sleeper parity. Before Batch 6 collects contracts, send a one-line follow-up asking League
  Tycoon to confirm that contract/cap pages are included.
- **Unchanged.** The permission is to scrape *for this league's data*. The read-only, single-league, kill-switch
  and pacing rules in §4.4 stay: they are good citizenship and keep us clear of "unreasonable load" (§4).

---

## 2. Phase 2: the Sleeper dependency audit (summary)

Full inventory, with file:line evidence: [`SLEEPER_DEPENDENCY_INVENTORY.md`](SLEEPER_DEPENDENCY_INVENTORY.md).

| Dimension | Finding |
|---|---|
| Endpoints | **17** distinct Sleeper REST endpoints, all anonymous, no GraphQL. **10 are league-scoped** (`league`, `rosters`, `users`, `matchups/{w}`, `transactions/{w}`, `traded_picks`, `drafts`, `draft/{id}`, `draft/{id}/picks`, `winners/losers_bracket`). **7 are global** (`state/nfl`, `players/nfl`, `trending`, `stats`, undocumented `projections`, `user/{name}`, `user/{id}/leagues`). Only the 10 league-scoped endpoints are in migration scope |
| Client layers | Five: overlay `urllib`, `public_league/sleeper_client` pooled session, scraper `requests`, about 8 ad hoc `urllib` sites, and the trending/news adapters. **There is no single Sleeper client.** That is the first thing the provider seam must fix |
| Hubs | Three hubs feed nearly every consumer: **(A)** the contract `sleeper` block (scraper + per-request overlay splice), **(B)** `PublicLeagueSnapshot` (raw verbatim Sleeper payloads per season), **(C)** Sleeper-derived ledgers (retention, acquisition, FAAB history, own-league format captures, intel) |
| Scheduled load | About 20 jobs touch Sleeper: GH `scheduled-refresh` every 2 h, public warmup every 20 min, Game Day live **every minute**, live draft sync **every 2.5 s** while drafting, plus daily/4-hourly timers |
| Identity coupling | Sleeper **player id** is the canonical player key (contract `playerId`, `player:<sleeperId>` history, sharp, game day, headshots). Sleeper **owner_id** is the manager key. Sleeper **roster_id** is embedded in canonical league-pick ids `pick:<leagueKey>:<season>:r<N>:o<rid>`. Sleeper **matchup_id** is in public permalinks |
| Vocabulary coupling | Sleeper scoring keys are the canonical scoring language (`sf1` fingerprint, realized points, BDVM). Sleeper `roster_positions` slot names are the lineup owner's vocabulary. Sleeper transaction types, bracket shape, `fpts + fpts_decimal`, `league_average_match`, `best_ball` and season chaining via `previous_league_id` all leak into consumers |
| Name joins | Several engines join teams by **display name** (`owner_names.json` labels): finder/best-offers/golden-upgrades/package-builder `myTeam`, `/trade` and `/rosters` player membership, the default-league draft-capital workbook bridge |
| Registry | `config/leagues/registry.json` has **no `platform` field**. `sleeperLeagueId` is hard-wired, with the scraper and `data_contract` falling back to `SLEEPER_LEAGUE_ID` and a hard-coded default id |

---

## 3. Phases 3–4: data inventory and contract-dynasty data

Every element is in `PARITY_MATRIX.md` §A. Summary by category, with **League Tycoon concept** (does the product
have it?) separate from **machine access** (can we get it?). Machine access is **UNKNOWN for every row** until the
owner capture. Any row that says otherwise is wrong.

| Category | League Tycoon has the concept? | Notes that change our design |
|---|---|---|
| A. League configuration | DOCUMENTED (settings exist for every listed item except divisions, which are implied by "division winners get the highest seeds") | Scoring with "no League Tycoon equivalent" is reported by name at import, so the import preview is a free scoring-parity check. Week 17 season end, playoffs from week 15 by default |
| B. All rosters | DOCUMENTED (rosters, lineups, practice squad, IR) | Practice-squad eligibility is per player and permanent: a new state we don't model. IDP coverage UNKNOWN |
| C. Transactions and trades | DOCUMENTED (trades, trade auctions, FAAB, FA pickups, cap-space trades, comp picks) | **Pre-migration Sleeper transactions are not imported**, so Sleeper stays authoritative for them. Trade auctions add *public losing offers*, a new evidence class (league-internal market prices) |
| D. Picks and drafts | DOCUMENTED (rookie picks tradable 2 seasons ahead by default, lottery, comp picks, auction drafts with nominations and proxy bids) | League Tycoon's pick horizon (2) is shorter than ours (`OWNED_PICK_HORIZON_CLASSES = 4`). Comp picks are new pick *origins* that our `o<rid>` id cannot express |
| E. Matchups and scoring | DOCUMENTED (weekly matchups, lineups, stat lines, brackets incl. bankrupt bowl, all-play is ours) | All-play, luck, median-game and strength-of-schedule are **ours to compute** and remain so |
| F. IDP | **UNKNOWN** | Gating question (Deliverable 1, condition 2) |
| Contracts | DOCUMENTED in depth (salary per year, length 1–5, allocations, rookie scale, extensions stable/performance-based, tags, rookie options, RFA tenders, expiry) | Only on **contract dynasty** leagues. Salary escalation is locked at signing, so future salaries are knowable facts, not projections |
| Cap | DOCUMENTED (cap $250 default, holdback $50, rollover ≤ $25, dead money 100% current + 25%×years lump next season, PS 25%/0%, cap must be satisfied to trade/claim/set lineups) | Dead money never lasts beyond two seasons, so multi-year cap projection is exactly computable from contracts + cuts |
| Auctions | DOCUMENTED (live/slow/contract-bidding; nominations, proxy bids, anti-snipe) | Losing bids may or may not be visible. UNKNOWN |

---

## 4. Phases 5–6: identifying and accessing the owner's league

### 4.1 What the integration needs

| Need | Status |
|---|---|
| League Tycoon league id | Candidate `1416568994525167616`, UNKNOWN (§1.3) |
| Owner's team id / user id on League Tycoon | UNKNOWN; capture |
| Season identifier (League Tycoon "league year", rollover-based, default April 1) | DOCUMENTED concept; id format UNKNOWN |
| Signed-in session | Required (Google/Apple). The owner signs in themselves; we never see the Google/Apple password |
| Commissioner privileges | Not needed for read-only member views. Possibly useful for comp picks/HoF edits (DOCUMENTED as commissioner-only *operations*, which we must never call) |

### 4.2 Session design (only after the access posture is decided)

| Option | How | Verdict |
|---|---|---|
| **S1. Owner-machine collector** (recommended first) | Owner runs `scripts/league_tycoon/collect.py` (future) on their own computer. Playwright opens a **persistent profile** the owner signed into by hand. The script visits a fixed page list, keeps the app's own JSON responses, sanitizes, and uploads a signed bundle to our backend | Credentials and tokens never leave the owner's machine. Refresh is "whenever the owner's computer runs it" (a scheduled task). Lowest secret risk |
| S2. Server-side persistent profile | Same, on the VPS. The owner signs in once through a remote browser session | Google sign-in commonly blocks automated/headless browsers ("this browser may not be secure"). Fragile, and puts a live session on the server |
| S3. Server-side token refresh | If capture proves Firebase Auth, store **only** the refresh token as a deploy secret and mint 1-h ID tokens server-side | Most automatic, and the most sensitive (a long-lived secret on the server). Since the 2026-10-17 permission it is no longer excluded on Terms grounds. Choose S1 vs S3 on secret-handling grounds after the capture |

**Never:** collect or store Google/Apple passwords. Paste tokens, cookies or unredacted HARs into chat, issues,
commits or repo files. Reuse a session against any league but the authorized one.

### 4.3 Discovery procedure

See `OWNER_EVIDENCE_CAPTURE.md`. It covers the 18 screens from the brief (Phase 6), the redaction rules, and the
per-request record template:

- purpose
- sanitized path
- method
- params
- auth mechanism
- response fields
- pagination
- scoping
- refresh
- proof it is the authorized league

### 4.4 Rate and footprint policy (binding on any future collector)

- Read-only methods only. Any request that is not a read **aborts the run**.
- Paced at or below human browsing:
  - at most 1 request per 2 s;
  - a full sweep at most every 2 h, matching our existing scrape cadence;
  - in-game live polling **not** from League Tycoon (§5.4).
- One league id, allow-listed. Any response whose league id differs is discarded and alarms.
- Global kill switch `RISKIT_FEATURE_LEAGUE_TYCOON_COLLECT=0`. A `401`/`403`/`429` or an unexpected schema
  **stops the run, never retries in a loop**, and raises a source-health alert.

---

## 5. Phase 7: technical architecture (Deliverable 5)

### 5.1 Principles, taken from the repo's own invariants

1. **One concept, one owner.**
   - Extend `src/platforms/` (it already defines a `PlatformAdapter` protocol, `Normalized*` records and
     `scoped_key()` for Sharp ingestion) into the league-hosting seam.
   - Do not start a third adapter framework.
   - `src/platforms/sleeper.py` currently has no importers. It is the natural place for the Sleeper league
     adapter to land.
2. **Sleeper and League Tycoon are season segments of one league.**
   - `dynasty_main` stays `dynasty_main`.
   - Each season-league in its chain gets a `provider` and a provider league id.
   - Today's `previous_league_id` walk generalizes to a provider-aware chain. This is the same shape as the
     own-league format capture's `own_league_season_chain` table.
3. **Missing is never zero, unknown is never false.**
   - A League Tycoon field we could not observe is `null` + reason, never a default.
   - The pick-ownership `observed | unavailable` vocabulary (`src/identity/picks.py`) is the model for every
     new League Tycoon field.
4. **Contracts never touch `rankDerivedValue`.**
   - Salary and cap are a separately named, league-scoped lens. This follows "raw canonical value vs
     contextual adjustment" in CLAUDE.md.
   - The canonical board stays scoring-profile scoped.
5. **Recommendation ≠ execution.** The League Tycoon adapter is read-only by construction. It has no write
   method in its protocol.

### 5.2 Target shape

```text
                       ┌──────────────── config/leagues/registry.json ───────────────┐
                       │ key: dynasty_main                                            │
                       │ seasons: [{season: ≤2026, provider: sleeper,  id: 1312…},    │
                       │           {season: 2027+, provider: leaguetycoon, id: <LT>}] │
                       └──────────────────────────────┬──────────────────────────────┘
                                                      │ src/api/league_registry.py (single resolver)
            ┌─────────────────────────────────────────┴───────────────────────────────┐
  src/platforms/sleeper_league.py                                 src/platforms/leaguetycoon/
  (wraps the existing Sleeper reads:                              ├─ collect (owner-run, §4.2 S1)
   overlay, sleeper_client, scraper)                              ├─ raw evidence store (append-only)
            │                                                     └─ normalize → Normalized* records
            └──────────────────────┬──────────────────────────────────────────┘
                                   ▼
        src/platforms/league_model.py   ← NEW normalized league model (one owner)
        League, Season, Franchise, Manager, Roster(slot states), Transaction(legs),
        PickAsset, Draft, Matchup, Bracket, ScoringCard, RosterRules
        + ContractTerms, CapLedger (LT-only, nullable, never zero-filled)
                                   │
          ┌────────────────────────┼─────────────────────────────┐
          ▼                        ▼                             ▼
  Hub A projection         Hub B projection               Hub C ledgers
  contract `sleeper` block PublicLeagueSnapshot           retention / acquisition /
  (same field names first; (same per-season shape)        FAAB history / format captures
   neutral alias later)                                   (+ provider column)
          │                        │                             │
          └──────── existing consumers unchanged (lineup, trade, public league, …) ──┘
```

**Why project into the existing hubs instead of migrating 100+ consumers:**

- Hubs A and B are already the integration points.
- A League Tycoon season that projects to the same shapes inherits every consumer immediately.
- Consumers then move to the neutral model one owner at a time, behind tests.

**Risk:** the projection would carry Sleeper semantics into League Tycoon data, for example `fpts_decimal` or bracket
`p`. **Mitigation:** projection fields carry `provider` in `meta`, and every semantic mismatch in `PARITY_MATRIX.md`
§A is an explicit projection rule with a test, never an implicit default.

### 5.3 Identity

| Identity | Today | Plan | Evidence needed |
|---|---|---|---|
| Player | Sleeper id is canonical | League Tycoon id → canonical Sleeper id via crosswalk, owned by `src/identity/` | Capture League Tycoon player ids |
| Manager | Sleeper `owner_id` | Keep Sleeper `owner_id` as the canonical manager key (continuity of every public franchise permalink, rivalries, HoF and Manager Scout). Add `manager_crosswalk` (League Tycoon user/team id → canonical manager key), owner-confirmed | League Tycoon owner/team ids |
| Franchise slot (pick origin) | Sleeper `roster_id` in `pick:…:o<rid>` | League-scoped **franchise number** that keeps the Sleeper `roster_id` for continuing franchises, so every existing pick id stays valid. New franchises get the next unused number | League Tycoon team ids, and the import's franchise matching |
| Season-league | Sleeper league id per season | `(leagueKey, season) → (provider, providerLeagueId)` | — |
| Matchup | Sleeper `matchup_id` | Provider-scoped `matchup:<season>:<week>:<n>`. Existing Sleeper permalinks kept verbatim for ≤ cutover seasons | — |

**Player crosswalk detail:**

- If League Tycoon's player ids are SportsDataIO `PlayerID`s (INFERRED from the 2024 SportsDataIO badge), the
  crosswalk is direct. Sleeper's own `/players/nfl` carries `fantasy_data_id` = SportsDataIO PlayerID, and
  `src/platforms/assets.py:96-105` already reads it.
- Otherwise, fall back to the `CANONICAL_V2` rungs (gsis/espn when present, then guarded name+position+team+age)
  with an explicit `AMBIGUOUS`/`UNRESOLVED` review queue. Never best-fuzzy.
- Every **IDP** player must resolve or be listed. A defender that cannot be matched is a reported gap, never
  silently dropped.

**Mid-season manager changes:**

- League Tycoon commissioners can reassign a team to a new account.
- That maps onto the 2026-10-17 `config/leagues/roster_ownership_changes.json` owner (`src/public_league/ownership.py`).
- Reuse it. Do not invent a second hand-off mechanism.

### 5.4 Sync design

| Class | Data | Cadence (proposal) | Source |
|---|---|---|---|
| High | rosters, transactions, completed trades, cap ledger, contracts, auction outcomes | every 2 h (existing scrape cadence) + on-demand after a known event | League Tycoon (B or A) |
| Game day | lineups, matchup pairings | lineups once per kickoff window (they lock at kickoff); **live points computed locally** from the Sleeper/nflverse live stats we already poll × the league's own scoring card | League Tycoon (lineups) + existing live stats |
| Low | league settings, scoring card, roster rules, completed drafts, past seasons | daily, plus at rollover and draft completion | League Tycoon |
| Live draft | picks while a League Tycoon draft runs | **not** at today's 2.5 s Sleeper cadence. At most once per 30–60 s, owner-initiated, or manual entry (Rookie Auction Room already supports manual) | League Tycoon |

**Why game-day points are computed locally:**

- Game Day polls Sleeper every minute today. Doing that against League Tycoon would be the most detectable
  pattern in the whole design.
- Our scorer is already validated: the canonical lineup solver reproduces Sleeper's awarded best-ball lineups 10/10.
- So League Tycoon is asked only for *who started*, never *how many points*.
- League Tycoon's final weekly results are then reconciled the next day as a parity check.

There are no webhooks (none documented), so everything is polling with explicit backoff: stop on 401/403/429, never
hot-retry.

### 5.5 Storage

**Raw evidence**

- Append-only `data/leaguetycoon/raw/<season>/<capturedAt>/<endpointSlug>.json.gz`, plus a manifest with
  hashes.
- Gitignored, box-local, like `data/sources/signals/board/`.
- Never committed: payloads can carry other managers' ids.

**Normalized tables** (additive, in one SQLite store owned by the new module)

- `lt_seasons`
- `lt_franchises`
- `lt_manager_crosswalk`
- `lt_player_crosswalk`
- `lt_rosters` (slot state incl. practice squad / IR)
- `lt_transactions`
- `lt_transaction_legs`
- `lt_picks` (origin incl. `comp`, holder state)
- `lt_matchups`
- `lt_brackets`

**Contract tables** (only if R60 is authorized; see §7)

- `contract_terms(asset, franchise, signed_at, type, years, salary_by_season[], flags)`
- `cap_ledger(franchise, season, cap, used, dead_money, rollover_in, holdback, as_of)`
- `contract_events(kind: sign|extend|tag|option|tender|cut|trade|expire, …)`

Every row carries `observed_at`. Contract state is **point-in-time**, so "salary commitments before and after a trade"
is answered from rows at or before the trade timestamp. It is never reconstructed from today's contract.

**Existing ledgers** gain a `provider` column (retention `league_transactions`, acquisition events, own-league
captures) rather than a parallel store. **Sleeper history is never rewritten with League Tycoon ids.**

### 5.6 Failure handling and observability

- League Tycoon source health joins `scripts/check_source_health.py` as a **source-health** lane, never the
  structural lane. A League Tycoon outage must not red PRs.
- States:
  - `fresh`
  - `stale`
  - `missing`
  - `not_provisioned` (CI, dev boxes; same posture as the Signals private source)
  - `access_challenged` (401/403/429: stop and alert the owner)
- Schema drift: each normalizer validates the fields it reads and quarantines the capture on mismatch. No partial
  write. Reconciliation alerts are in `PARITY_MATRIX.md` §C.

---

## 6. Phase 9: feature impact (Deliverable 6, summary)

Full table: `PARITY_MATRIX.md` §B. Four classes:

| Class | Features |
|---|---|
| **Unchanged**: global Sleeper data, not league-hosted | rankings/values pipeline, player directory/identity, news, trending, Sharp market + roster %, curated sharps, DFS, weekly projections, the username portfolio (owner directive 2026-10-16) |
| **Works once Hubs A/B/C are fed**: no consumer change if the projection is faithful | trade calculator, suggestions/finder/angle/best-offers, terminal, rosters, BDVM roster, signal alerts, power rankings, playoff sim, gameplan/posture, public `/league` sections, Manager Scout, temporal history |
| **Needs semantic adaptation** | draft order (lottery/MPF on League Tycoon vs our reverse-record rule), rookie auction / Perfect Draft (League Tycoon rookie drafts are linear/snake), live draft sync (cadence), FAAB engine + bid history (FA contract cost, tiebreaks, cap gating), roster capacity (practice squad + IR states; finally *exact* taxi-equivalent membership), Game Day (median game, best ball, week 17 end), brackets (bankrupt bowl), pick horizon (2 vs 4 classes) and comp picks, scoring fingerprint (League Tycoon scoring vocabulary → our canonical keys), lineup slot vocabulary |
| **Loses its source / needs owner decision** | intel crawler "members' other leagues" (League Tycoon exposes no cross-league membership; members may still be on Sleeper), Sleeper avatars (League Tycoon logos via Firebase Storage URLs, UNKNOWN), `/league` permalinks for post-cutover seasons, `SLEEPER_LEAGUE_ID` fallbacks and the hard-coded default id |

**Username portfolio:**

- The owner reversed the earlier X-07 rejection on 2026-10-16 ("Manager Intelligence: Sleeper username lookup,
  dynasty portfolio…", Batch A in progress).
- That feature is **Sleeper-global** and unaffected.
- A League Tycoon equivalent is **not possible** from public evidence: League Tycoon has no username lookup and no
  public league data. Per the brief, any League Tycoon portfolio stays limited to the one authorized league.

**Trade valuation:**

- Contract terms are an **additional, separately named lens**. Examples: "cap-adjusted surplus", "affordability
  check: blocked, team B over cap by $X".
- They never alter `rankDerivedValue`, the VA, or `tradeImbalance`.
- Trade history keeps both at-the-time and current comparisons per `TRADE_HISTORY_AGING_SPEC.md`. Contract state
  at trade time comes from point-in-time rows, never today's contract.

---

## 7. Deliverable 7: contract-dynasty intelligence opportunities

**Separate from migration.** R60 ("salary-cap and contract-league extension") is **DEFER** in
`docs/research/calculator-reconciliation-2026-09-25/`. None of the below is authorized.

| # | Capability | Inputs (all DOCUMENTED concepts) | Why it's exact rather than modelled |
|---|---|---|---|
| 1 | Multi-year cap projection | salary_by_season (locked at signing), dead money rule, rollover ≤ cap, holdback | Escalation is locked at signing, and dead money ends after two seasons |
| 2 | Contract-aware trade evaluation | canonical value + contract years + salary | Separate lens beside raw + VA |
| 3 | Surplus value | value per $ vs the league's own contract market | League-internal price data from auctions |
| 4 | Expiration / tag / extension / option alerts | contract year, eligibility flags, windows | Windows are deterministic (rollover → first kickoff) |
| 5 | Free-agent planning | expiring contracts league-wide, cap space, tag price (avg top-N at position) | Tag price is a published formula |
| 6 | Cap-efficiency rankings | canonical value per cap $ per team | — |
| 7 | Rebuild recommendations | cap runway + posture (existing `competitive_posture`) | Reuses the posture owner |
| 8 | Trade affordability check | both teams' cap after the trade, incl. traded cap $ | League Tycoon itself blocks over-cap trades, so we can pre-flight them |
| 9 | Tag / extension decision support | performance-based extension formula (85% computed) vs tag price | Both formulas DOCUMENTED |
| 10 | League contract market intelligence | auction prices, contract-bidding length discounts, trade-auction offers | **New market class:** trade auctions publish competing offers league-wide. A real "market price" signal, subject to the signal-independence rules before it may touch any value |

---

## 8. Deliverable 8: risk and feasibility

| Risk | Severity | Mitigation / fallback |
|---|---|---|
| Terms of Use §4 (automation) → account termination, forfeiting the league | **Reduced → Low** (written permission 2026-10-17, §1.5) | Keep the original email. Confirm contract/cap scope before Batch 6. Human-paced, read-only, single-league, kill switch. Method D fallback remains |
| League Tycoon lacks IDP and/or best ball | **Critical** (format change) | Ask League Tycoon before import. Use the import preview's unmapped-rule list. If missing, the owner decides the league's future format, and we model *that* league, not today's |
| No machine access verified | High | Owner capture (`OWNER_EVIDENCE_CAPTURE.md`) is Batch 1. Nothing proceeds without it |
| Interface churn (≈2 releases/week, private interface) | High | Schema validation per field read, quarantine on drift, raw evidence retained for replay, parser tests on captured fixtures |
| Firestore-style streaming channel instead of REST | Medium | Capture-the-app's-responses (S1) works for either. Direct replay may not; then S1 stays the method |
| Session expiry / Google blocking automation | Medium | S1 owner-machine profile; `access_challenged` state; owner re-signs in |
| Pre-cutover transactions not imported by League Tycoon | Medium | Sleeper stays the record for ≤ cutover seasons, unchanged and still readable (Sleeper keeps league data public) |
| Identity drift (player, manager, franchise) | Medium | Crosswalk tables with review queues; owner confirmation of managers; import-day reconciliation (§10) |
| Contract data only exists on paid contract dynasty | Medium | Owner decision OD-2. On a standard dynasty League Tycoon league every contract feature is simply UNAVAILABLE |
| Rate limits unknown | Medium | §4.4 caps; stop on 429 |
| Historical point-in-time data (contracts at trade time) | Medium | Start capturing on day one. History before the first capture is UNKNOWN, never back-filled from current state |
| Operational cost | Low | $0 for standard. $11.99 × 12 teams = $143.88 per season for contract dynasty (paid by the league, not this repo). Our compute is negligible |
| Maintenance | Ongoing | Estimate a parser touch-up per League Tycoon UI release that changes a screen we read. Not quantifiable until Batch 1 shows the interface |

---

## 9. Deliverable 9: ranked implementation roadmap

Each batch is one coherent L2 integration PR (Agent OS §3). Effort is not estimated; there is no evidence to estimate
from until Batch 1 lands. **Batches 2+ require `docs/EXECUTION_PLAN.md` authorization.** Batch 6 additionally
requires R60 to be lifted.

### Batch 0: owner decisions (no code)

- **Objective:** answer the decisions in §11.
- **Done when:** each has a recorded answer in `docs/OWNER_REQUESTED_TODO.md`.

### Batch 1: access proof of concept and evidence catalog

| | |
|---|---|
| **Objective** | Verified access catalog, from one owner-run capture |
| **Access** | Owner signs in on their own machine and follows `OWNER_EVIDENCE_CAPTURE.md` |
| **Files** | `scripts/league_tycoon/sanitize_capture.py` (new, offline, stdlib-only redactor + field-shape extractor); `docs/research/league-tycoon-migration-2026-10-17/ACCESS_CATALOG.md` |
| **DB** | none |
| **Tests** | sanitizer unit tests (redacts Authorization/Cookie/`token`/`idToken`/`refreshToken`/emails; preserves shapes) |
| **Acceptance** | Every Phase 6 screen classified VERIFIED / UNAVAILABLE. League id proven. Player-id scheme identified (SportsDataIO or not, on ≥ 25 players incl. ≥ 5 IDP). No secret in any committed file (`run_secret_scanning`) |
| **Rollback** | Delete files |
| **Done** | The catalog replaces every INFERRED row in this document with a verdict |

### Batch 2: provider seam with no behaviour change

| | |
|---|---|
| **Objective** | Registry season segments + `provider`. Normalized league model in `src/platforms/`. The Sleeper league adapter routes the existing reads through one client |
| **Files** | `config/leagues/registry.json` (additive), `src/api/league_registry.py`, `src/platforms/{league_model,sleeper_league}.py`, the five Sleeper client sites |
| **Tests** | **Byte-identical** contract and public snapshot before/after on archive fixtures (`tests/archive_fixtures.py`, `scripts/board_diff.py --expect-no-value-change`) |
| **Risk** | Touches shared core, so it is high-risk under `ci_change_scope.py`. Full L2 |
| **Rollback** | Revert. No data migration |

### Batch 3: League Tycoon adapter, part 1

| | |
|---|---|
| **Scope** | config, franchises, managers, rosters |
| **Contents** | normalizer + crosswalks (player via `src/identity/`, manager owner-confirmed, franchise numbering) + review queue |
| **DB** | `lt_*` tables |
| **Tests** | Captured fixtures from Batch 1. IDP coverage = every rostered defender resolved or listed |
| **Acceptance** | `PARITY_MATRIX.md` §A rows A/B pass on the import-day comparison (§10) |

### Batch 4: picks, transactions, trades

- Covers comp picks as a new origin class, and the pick horizon difference.
- Ownership uses the `observed | unavailable` vocabulary.

### Batch 5: matchups, standings, brackets, scoring

- Covers the scoring-card mapping to canonical keys, `sf1` fingerprint compatibility, and local scoring
  recompute vs League Tycoon finals.

### Batch 6: contracts and cap

**Gated by R60.**

- **Contents:** storage + point-in-time reads + a display-only panel.
- **Excluded:** valuation changes.

### Batch 7: wire into Hubs A/B/C

- **Contents:** projection rules with tests, consumer conformance per `PARITY_MATRIX.md` §B, neutral display
  labels.
- **Gate:** a feature flag per league.

### Batch 8: history stitching and reconciliation

- Provider-aware chain walk.
- Public league seasons span providers.
- Parity tests and reconciliation alerts.

### Batch 9: scheduling, monitoring, resilience

- Timers, source-health lane, kill switch, `access_challenged` alerting, runbook.

### Batch 10: controlled cutover

**Requires explicit owner approval.**

- Flip `provider` for the cutover season of `dynasty_main` only.
- Sleeper code, data and tests are retained.
- **Rollback:** flip the segment back.

---

## 10. Phase 10: proving parity

### Import-day reconciliation (the strongest test available)

League Tycoon's import copies Sleeper's final state, so at import time **both platforms describe the same league**.
A one-shot diff between Sleeper's end-of-season data and League Tycoon's first capture is the parity proof for:

- teams and managers;
- every roster, incl. every IDP player;
- future pick ownership (origin and holder);
- scoring card;
- roster rules;
- past-season standings, matchups and brackets (from League Tycoon's rebuilt seasons).

Every diff must be explained: either a documented League Tycoon semantic difference, or a defect.

Remaining tests and when they can run:

| Test | Pre-migration (synthetic/captured) | Needs League Tycoon league | Needs live season |
|---|---|---|---|
| Team count, managers, rosters, ownership, IDP coverage | normalizer on Batch 1 fixtures | ✓ import-day diff | — |
| Picks (origin/holder, comp) | ✓ | ✓ | — |
| Draft history | ✓ (rebuilt seasons) | ✓ | rookie draft |
| Transactions, completed trades | parser only | ✓ | ✓ (first real trades) |
| Matchups, weekly scoring, standings | ✓ (rebuilt seasons vs Sleeper archive) | ✓ | ✓ (local recompute = League Tycoon final) |
| Contracts, years, dead money, cap totals, future obligations | arithmetic properties (dead money ≤ 2 seasons; Σ salaries + dead money = cap used) | ✓ contract league | ✓ (cuts, rollover) |

**Negative tests:**

- session expiry → `access_challenged`, no partial write;
- network failure;
- duplicate transactions (idempotent on provider tx id);
- missing IDP player → listed, never dropped;
- changed player id → crosswalk conflict surfaced;
- failed history import;
- league rollover (new season segment);
- contract expiry at rollover;
- cap adjustment;
- trade reversal / commissioner correction (a correction row, never an in-place edit);
- partial data → field-level `null` + reason;
- League Tycoon UI release → schema quarantine.

---

## 11. Owner decisions needed (Batch 0)

> **OWNER_PAUSED (owner directive 2026-10-18).** League Tycoon is shelved: this research and the Ideas backlog are
> retained, but no integration, contract-dynasty feature or platform migration is to be implemented, and OD-1, OD-2,
> OD-3, OD-5, OD-6, OD-7 and the signed-in evidence capture are **not to be requested** now. Sleeper remains the
> platform. Reopen only on a fresh explicit owner directive. OD-4 stays recorded as decided.
> Register: `docs/owner/OWNER_DECISION_REGISTER.md`.

| # | Decision | Recommendation |
|---|---|---|
| OD-1 | Which league moves, and from which season? (League Tycoon imports always target the next *fresh* season) | Confirm `dynasty_main`, 2027 season; `dynasty_new` stays on Sleeper unless stated |
| OD-2 | Standard dynasty (free) or contract dynasty (paid) on League Tycoon? | Owner's league decision. Contract features exist only on contract dynasty |
| OD-3 | Does League Tycoon support IDP (DL/LB/DB + the 17 IDP scoring keys), best ball, 2 TE + SUPER_FLEX + K, 58-man rosters, TE premium (`bonus_rec_te`)? | Ask League Tycoon support before importing |
| OD-4 | Access posture: request League Tycoon written permission (recommended) or proceed on owner-accepted risk? | **DECIDED 2026-10-17:** League Tycoon support granted written permission (§1.5). Follow-up still needed to confirm contract/cap pages before Batch 6 |
| OD-5 | Lift R60 (contract-league modelling) from DEFER? | Only after OD-2 = contract dynasty |
| OD-6 | Keep Sleeper as the record for ≤ cutover seasons? | Yes |
| OD-7 | Rookie auction → League Tycoon rookie draft format; draft-order rule (League Tycoon lottery/inverse/MPF vs our reverse-record + PF rule) | League decision; `draft_order_rules.json` records it |

---

## 12. Deliverable 10: next implementation prompt (do not execute until approved)

```text
Risk It To Get The Brisket — Calculator repo. Batch 1 of the League Tycoon migration
(docs/research/league-tycoon-migration-2026-10-17/README.md §9). Precondition: the owner has
recorded OD-1 and OD-4 in docs/OWNER_REQUESTED_TODO.md and docs/EXECUTION_PLAN.md authorizes
"League Tycoon Batch 1". If either is missing, stop and say so.

Goal: turn the owner's signed-in capture into a VERIFIED access catalog. Read-only. No production,
Sleeper, or League Tycoon writes. No credentials, cookies, tokens, or unredacted HARs in chat, commits,
issues or files — ever.

1. Read README.md, PARITY_MATRIX.md and OWNER_EVIDENCE_CAPTURE.md in that directory.
2. Write scripts/league_tycoon/sanitize_capture.py (stdlib only, offline): input = a HAR or a
   directory of saved JSON responses supplied locally by the owner; output = (a) a redacted copy with
   Authorization/Cookie/Set-Cookie headers, any key matching /token|secret|session|auth|password|email/i,
   and query-string credentials removed, and (b) a per-request record: method, sanitized path template
   (ids → {leagueId}/{teamId}/{playerId}), params, status, response field tree (types only, no values
   except whitelisted enums), pagination hints, timestamps fields. Refuse to run on input containing a
   league id other than the allow-listed one. Unit-test the redactor with synthetic inputs only.
3. Have the owner run it locally; receive ONLY the sanitized field-shape output.
4. Write ACCESS_CATALOG.md: for each Phase-6 screen, VERIFIED / UNAVAILABLE / UNKNOWN with the record.
   Prove the league id. Determine the player-id scheme on ≥25 players incl. ≥5 IDP by joining to
   Sleeper /players/nfl fantasy_data_id; report the match rate, never guess.
5. Update README.md/PARITY_MATRIX.md rows from INFERRED/UNKNOWN to their verified status.
6. Run L0/L1 (bash scripts/tiered_validate.sh l0 && l1), run secret scanning on the diff, open one PR.
End with the Agent OS completion result contract (STATUS, ACCEPTANCE, EVIDENCE, UNRESOLVED, BLOCKERS,
NEXT_ACTION).
```

---

## Sources

- League Tycoon public site (51 sitemap pages, fetched 2026-10-17), notably:
  - [Terms of Use](https://leaguetycoon.com/terms/)
  - [League import](https://leaguetycoon.com/features/league-import/)
  - [Contract league rules](https://leaguetycoon.com/rules/contract-league-rules/)
  - [Switch from Sleeper](https://leaguetycoon.com/learn/how-to-switch-from-sleeper/)
  - [Account help](https://leaguetycoon.com/support/account-help/)
  - [Pricing](https://leaguetycoon.com/pricing/)
- Public app shell `https://app.leaguetycoon.com/` (fetched 2026-10-17)
- [App Store listing](https://apps.apple.com/us/app/league-tycoon-fantasy-football/id1488816698)
- [FantasyPros League Tycoon platform breakdown (May 2026)](https://www.fantasypros.com/2026/05/league-tycoon-platform-breakdown-fantasy-football/)
- [urlscan.io scan of leaguetycoon.com (2024-01-07)](https://urlscan.io/result/4579c93c-a85d-4491-812c-572739e27eb9/)
- Sleeper public API, `GET /v1/league/{id}` for the candidate id and both registry leagues (2026-10-17)
- Repo audit evidence: `SLEEPER_DEPENDENCY_INVENTORY.md`
