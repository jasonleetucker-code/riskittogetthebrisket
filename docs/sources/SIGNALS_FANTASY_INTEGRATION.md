# Signals Fantasy — data integration and product-capability record (2026-09-30, updated 2026-10-01)

**Owner direction:** #1555, extended 2026-09-30 ([extension record](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/1555#issuecomment-5920621510)). Signals is a comprehensive integration
workstream whose intended destination is an **active, validated Calculator source**
(activation stage 5 where justified). That supersedes the earlier optional/benchmark-only
destination. The earlier record's access, validation, privacy and lineage requirements are
kept. Map: `docs/valuation/VALUATION_ADVANCEMENT_MAP_2026-09-30.md`.

## 1. Current status

Four separate questions, answered separately:

| Question | Answer (2026-10-01) |
|---|---|
| **Permission** | **Resolved — owner-attested.** The owner stated on 2026-10-01: *"I have explicit permission to use signals how I see fit."* It is recorded as owner-attested authorization for the requested Calculator integration (#1555, 2026-10-01 comment). No permission document or provider correspondence is invented, and no independent legal verification is claimed. |
| **Technical access** | Public boards: accessible without login. Paid / native-value / league-adjusted / projection surfaces: need an **owner-controlled authenticated session**, which does not exist in this environment. That is an access dependency, not missing permission. No subscription is assumed, purchased or trialled. |
| **Data availability** | Public dynasty and IDP-dynasty boards publish **positional ordinal rank + tier** only, with no value scale and no cross-position order. Native values and projections exist only behind the account. |
| **Activation stage** | **Stage 5 — ACTIVE for offense and IDP (owner addendum 2026-10-03, §9).** The authenticated native values (`signalsSf`, `signalsIdp`) vote in the canonical board. The public boards stay at stage 3 (non-voting second opinion, §8). |
| **Affects canonical values?** | **Yes, since 2026-10-03**, through the authenticated native values only, as a value-ordered rank signal inside the FantasyCalc B10 family (§9). Public positional ranks still never vote. |
| **KTC permission applies?** | No. KTC authorization is separate. Signals now has its own owner-attested authorization. |

**Evidence standard.** Everything in §3–§5 comes from the public pages listed in §2,
fetched once each on 2026-09-30 through a summarizing fetch tool. That means paraphrase,
not verbatim capture. "Claimed" means the page says it. "Observed" means the public page
itself displayed the data. Nothing behind authentication was accessed.

## 2. Access and rights boundary

- **Authorization:** owner-attested on 2026-10-01 (§1). It supersedes the 2026-09-30
  posture, under which every automated operation was "blocked pending written consent".
  That posture is kept here as history, not as a live gate. The Terms (effective
  2026-08-31, paraphrased from a summarizing fetch) require prior written consent for
  automated access; the owner attests he holds the permission.
- **Authorized now:** read-only collection of the boards the available access reaches,
  normalization, private historical retention, analysis, and authenticated Calculator
  displays.
- **Privacy boundary, unchanged by permission:**
  - No raw paid data, league-private payloads, credentials or session material in this
    public repository, public CI artifacts, logs, shared caches or public `/league`
    endpoints.
  - Raw pages and releases live in a gitignored private store on the production box.
  - Fixtures are sanitized and labelled synthetic.
- **Operational limits:** bounded requests, conditional GET, backoff, honour 429, stop on
  401/403 or session expiry, no access-control bypass, no uncontrolled retries, no
  recurring manual CSV upload as the operating workflow.
- **Security page:** passwordless email one-time codes; short-lived sessions via AWS
  Cognito; connected platforms read-only (except paid ESPN auto-lineups).
- **Secrets:** never in chat, issues, fixtures, logs or screenshots. For paid surfaces:
  - an owner-controlled login flow, with local ignored storage or an approved secret
    manager;
  - expiry means stopping and reporting, not repeated re-login.
  - Implemented (2026-10-01): `docs/sources/SIGNALS_ACCOUNT_CONNECTION.md` (observed login
    mechanism, session store, renewal, failure classes, operations).

**Public pages fetched** (HTTP 200):
- `/`, `/robots.txt`, `/terms`, `/security`
- `/rankings`, `/rankings/dynasty`, `/rankings/idp-dynasty`, `/rankings/redraft`
- `/features/rankings`, `/features/trade-calculator`, `/features/league-analyzer`,
  `/features/waiver-report`, `/features/start-sit`, `/features/draft-assistant`
- `/formats/idp`, `/formats/dynasty`, `/formats/devy`
- `/methodology`, `/methodology/dynasty`, `/methodology/idp-dynasty`,
  `/methodology/redraft`

404: `/pricing` (plans sit at `/#plans`) and `/changelog`.

**Not yet read** (budget, not refusal): `/rankings/devy`, `/rankings/idp-redraft`,
`/rankings/idp-prospect`, `/methodology/devy`, `/methodology/idp-redraft`,
`/methodology/idp-prospect`, `/integrations`, `/guides`, `/features/ai-assistant`.

## 3. Dataset coverage manifest

The denominator is the discovery checklist in #1555 §F. It is complete over that checklist
and **not** a claim of complete coverage of the product, whose authenticated surfaces are
unseen.

| Dataset | Where (claimed) | Scope | Units / format | Cadence (claimed) | Disposition |
|---|---|---|---|---|---|
| Offense dynasty board — public | `/rankings/dynasty` | public | positional rank + tier (S+…C); **no values**; stamped "Published …" and "Market data through …" | weekly rebuild (board page) vs daily engine (methodology) — **unresolved** | **stage 2 collector + stage 3 rank-only second opinion implemented (Unit A, §8)**; non-voting, positional **ordering** only, never cross-position prices |
| Offense dynasty values — league-adjusted | in-app | paid account | value scale; SF/TEP/custom scoring/roster/depth adjusted | "daily" (trade page, formats page) | access-dependent (owner session; permission resolved 2026-10-01) |
| IDP dynasty board — public | `/rankings/idp-dynasty` | public | true positions CB/S/DT/DE/LB; "MKT" positional label (meaning unconfirmed) | weekly (board) / "in progress" (methodology) | **stage 2 collector + stage 3 rank-only second opinion implemented (Unit A, §8)**; "MKT" = Signals' stated market positional rank (from the badge title) |
| IDP dynasty values — league-adjusted | in-app | paid (Fanatic) | value scale | unclear | access-dependent (owner session; permission resolved 2026-10-01) |
| Redraft / ROS / weekly projections (+IDP stat lines) | in-app; `/methodology/redraft` | paid | full stat lines scored per league | daily in season | access-dependent (owner session; permission resolved 2026-10-01); **external-projection baseline only**, never fundamentals |
| Devy + IDP prospect boards, grades, confidence, projected draft capital | `/rankings`, `/formats/devy` | boards public (not yet read); grades paid | grade + confidence | weekly | access-dependent (owner session; permission resolved 2026-10-01); contextual-only (vendor grades are model outputs, not scouting facts) |
| Rookie / future picks | in-app | paid | same value scale; priced as the 3rd-best class prospect, adjusted | daily (claimed) | access-dependent (owner session; permission resolved 2026-10-01) |
| Player cards (fields, history, movement) | in-app | paid | undocumented publicly | — | not exposed publicly; access-dependent (owner session; permission resolved 2026-10-01) |
| General vs league-adjusted boards; personal overrides; CSV import/export of custom rankings | `/features/rankings` | paid | CSV (fields undocumented) | — | owner-manual export = pending personal-use confirmation; **user edits are never independent evidence** |
| Trade calculator (itemization, package multipliers, consolidation, both-team lineup impact, league trade history, GO/NO-GO) | `/features/trade-calculator` | free basic, paid depth | — | daily models (claimed) | access-dependent (owner session; permission resolved 2026-10-01); product-capability reference (§5) |
| League / roster diagnostics (archetypes, strengths, age curves, draft capital, playoff odds, portfolio) | `/features/league-analyzer` | paid | — | — | access-dependent (owner session; permission resolved 2026-10-01); capability reference |
| Draft tools (mocks, live assistant, Chrome overlay) | `/features/draft-assistant` | paid | — | — | out of scope for data; capability reference |
| Waiver report (FAAB ranges), start/sit, lineup optimizer | `/features/waiver-report`, `/features/start-sit` | free (1 league) / paid | — | weekly | access-dependent (owner session; permission resolved 2026-10-01); capability reference |
| Notifications | none described | — | — | — | not exposed |
| Public API | none described | — | — | — | not exposed |
| Methodology / source disclosures | `/methodology/*` | public | prose. Unnamed "community dynasty value markets", real startup ADP, trade-implied values from ~7,965 trades, licensed charted data. **KTC/FantasyCalc/Dynasty Daddy never named.** | methodology updated 2026-08-13/14 | ingested as documentation (this record) |
| Changelog / publication calendar | 404 | — | — | — | not exposed |

**Lineage warning.** Signals says it aggregates "community dynasty value markets" and
trade-implied values. Calculator already votes KTC Crowd/Trades, FantasyCalc and Dynasty
Daddy. Until ancestry is disclosed, any Signals value must be treated as **correlated with
those families**. It gets a family-cap review and no presumption of independence (lead
V2-4).

**Cadence conflict, unresolved.** Board pages say the dynasty and IDP boards "rebuild
weekly". Methodology, trade and formats pages say "daily". Per dataset, it is resolved by
observed publication stamps once collection is authorized, or by first-party clarification
(§7). The faster claim is not chosen by default.

## 4. Source contract (design; implementation in Unit A, §8)

- **Reuse:**
  - canonical registry `_RANKING_SOURCES` (`src/api/data_contract.py`);
  - identity (`src/identity/resolution.py`);
  - dataset state and freshness (`src/sources/dataset_state.py`, `freshness.py`);
  - archive (`src/source_archive/store.py`, which is DYNASTY-only);
  - history (`src/history/`).
- **No separate engine** and no disconnected scraper folder.
- **Variants kept distinct, one family:**
  - public positional rank/tier;
  - native general-market value;
  - league-adjusted value (private);
  - vendor projections;
  - prospect grades;
  - user overrides.
  
  Only comparable general-market dynasty values could ever vote. Redraft, devy, IDP
  variants and multiple screens are not extra votes. League-adjusted values are private to
  the user and league, excluded from raw CSVs, public APIs, logs, fixtures and shared caches,
  and never re-scored (no double scoring).
- **Persisted per observation:** provider/family, asset identity/type, raw rank/value/unit,
  model/horizon, league settings hash, defensive eligibility, as-of/fetch/change times,
  publication id, lineage, override flag, rights/visibility, coverage, parser/schema version.
  Missing fields stay null.
- **Operations:**
  - bounded, idempotent, conditional requests where supported;
  - low concurrency; backoff; honour 429;
  - stop on 401/403;
  - schema-drift quarantine;
  - atomic per-release publication;
  - last-good retention with truthful age;
  - partial coverage is never marked complete.
- **Game type:** every board must be verified DYNASTY per endpoint before it can reach the
  dynasty lane (`_validate_source_game_types_invariant`). Redraft/projection boards go only
  to the seasonal lane.

**Activation stages:**
1. Discovered and characterized.
2. Real authorized observations ingested, validated and replayable.
3. Visible second opinion with honest scope, coverage and freshness.
4. Shadow canonical participation with lineage caps and whole-board diffs.
5. Active for eligible assets and formats after the existing promotion gates.

Readiness at any stage is not promotion authority. Unique information must be measured
separately from its correlation with families already in the pool.

## 5. Product-capability adoption matrix

| Capability | Signals (claimed) | Calculator today | Decision |
|---|---|---|---|
| Value/rank tiers, scarcity cliffs | S+…C tiers | canonical tiers (`canonicalTierId`) | already present |
| Consistent values across surfaces | claimed | one canonical board; BDVM separate and now labelled | improve (value-type labels shipped in Lane 6) |
| Itemized trade explanation, both-team fit, forced drops | claimed | #792 Analyze + roster capacity owner + #843 | already present / improve via #792 |
| Roster windows / archetypes | 6 archetypes | #840 posture, #838 young core, #839 core | already present — no copied labels |
| Trade-partner discovery, completed-trade comparisons | league trade history | finder/angle; ledger CE-01 | improve later (V6) |
| Source disagreement, changes, alerts, confidence | limited | explain view, B11 confidence, signal alerts | improve: information-age display (next Lane 6 unit) |
| Personal overrides with reset + provenance | drag-drop tiers, CSV | source weight overrides through the canonical pipeline | already present (source-level); player pins = sequence later |
| Player profiles with uncertainty + attributed news | cards | Player File + news | already present |
| Draft prep / pick valuation | mocks, overlay | /draft, Perfect Draft, Auction Room | already present |
| Waiver FAAB ranges | yes | FAAB engine with crowd market | already present |
| Cross-league portfolio | yes | — | sequence later |
| Grounded natural-language explanations | AI verdicts | — | sequence later — must summarize canonical calculations only |
| Chrome draft overlay | yes | — | reject (out of scope) |
| Branded content studio | add-on | — | reject |

## 6. Failure and expiry behaviour (design)

- A session expiry or a 401/403 stops that collection and records `auth_expired`.
- Last-good data keeps its true age; no timestamp is refreshed from a cached copy.
- Schema drift is quarantined. Truncated pagination means the release is withheld.
- One board's failure never marks another board, or the whole run, successful.

## 7. Permission request — SUPERSEDED 2026-10-01 (historical, never sent)

Superseded by the owner's attestation of explicit permission (§1). It was never sent, and
no action on it remains. It is kept unedited below as the record of the 2026-09-30 posture.

> Subject: Written consent request — automated access for a private dynasty analysis tool
>
> I subscribe (or will subscribe) to Signals and run a private dynasty analysis site
> (login required; used by me and a small number of invited league members; not public, no
> advertising, no resale). Your Terms require prior written consent for automated access. I am
> asking for consent covering:
> 1. **Datasets:** dynasty and IDP dynasty boards (public and my league-adjusted values),
>    rookie/future pick values, prospect boards, and redraft/ROS projections for my own
>    leagues.
> 2. **Method:** authenticated, read-only automation from my own account, or a supported
>    export/API if you offer one. No credential sharing; no access to other users' data.
> 3. **Frequency:** at most once per publication (daily or weekly as you publish), with
>    conservative rate limits.
> 4. **Retention:** historical snapshots kept privately to measure changes over time.
> 5. **Derived values:** your values used as one input among many in the site's valuation
>    model, whose blended values are shown to its logged-in users, and optionally shown
>    directly as a labelled "second opinion" to those same logged-in users. Please say
>    which of these you permit.
> 6. **Display:** nothing public; no redistribution of your raw values or commercial use
>    without separate agreement.
> 7. **Clarification:** which datasets rebuild weekly vs daily, and whether an owner-exported
>    CSV imported into a personal tool is within personal use.

The owner must send it himself, after confirming the audience description in points 1 and
5 matches how the site is actually used. The intended stage-5 destination (an active source)
means blended values reach every logged-in user, not only the owner. No commercial terms
are accepted on his behalf.

> **Superseded in part (2026-10-03).** §1–§8 record the public-board stage
> and the pre-access posture. Where they say Signals does not vote or that
> native values are unreachable, §9 is the current state.

## 8. Collection and stage evidence (Unit A, 2026-10-01)

Scope of this section: the two **public** dynasty boards only, collected read-only under
the owner's attestation of 2026-10-01. No login, no paid surface, no bypass. The access
and rights record itself is §1/§2.

### 8.1 What was built

| Piece | Where |
|---|---|
| One owner: parser, store, collection, identity join, serving payload | `src/sources/signals.py` |
| Thin CLI fetcher (exit 0 ok / 1 failed or stopped / 2 quarantined) | `scripts/fetch_signals.py` |
| Box timer, every 6 h (`--min-interval-hours 5`) | `deploy/systemd/dynasty-signals-fetch.{service,timer}.template`, wired via `install_simple_timer` |
| Authenticated endpoint (no public allowlist entry) | `GET /api/second-opinion/signals` in `server.py` |
| Rank-only basis + per-asset state | `frontend/lib/second-opinions.js` (`POSITIONAL_RANK_ONLY`, `rankOnlyOpinionFor`) |
| Display under the Second Opinions table | `frontend/components/trade/SignalsRankOpinion.jsx` |
| Tests (labelled synthetic markup, no network) | `tests/sources/test_signals.py`, `frontend/__tests__/components/signals-rank-opinion.test.jsx` |

- **Storage:** `data/sources/signals/<board>/`, holding `raw/<sha256>.html.gz`,
  `releases/<contentSha>.json`, `quarantine/`, `latest.json`, `fetch_state.json` and
  `dataset_state.json`. `data/` is gitignored, and no workflow or push script force-adds
  `data/sources/`. Collection runs only on the box, never in GitHub Actions, whose output
  is public.
- **Freshness:** reuses `src/sources/dataset_state.observe`, so the three-clock model,
  health and row-collapse rules are the shared ones.
- **Release identity:** a normalized content hash over the rows plus the page's
  Published and market-through stamps. The Nuxt build id and `prerenderedAt` change on
  every site deploy without the rankings changing, so they are excluded.
- **Identity:** `CONTRACT_CSV_JOIN_V1`, using the contract's own key functions, made
  stricter. Each entry is keyed by Signals' TRUE position group, with no `name_star` or
  `single_group` fallback. Collisions and homonyms are quarantined with reasons and are
  never best-guessed.
- **Not touched:** `_RANKING_SOURCES`, the game-type gate, the blend, confidence and any
  canonical field. A test pins that no `signals*` key is registered.

### 8.2 Real capture (local run, 2026-10-01 ~09:03 UTC)

| | `/rankings/dynasty` | `/rankings/idp-dynasty` |
|---|---|---|
| Rows / sections | 800 — QB 200, RB 200, WR 200, TE 200 (matches each section's declared count) | 1,072 — CB 244, S 171, DT 235, DE 215, LB 207 (matches) |
| Tiers seen | S+ … B (9 bands) | S+ … F (12 bands) |
| Market badge present | 359 / 800 (441 null — no badge on the page) | 967 / 1,072 (105 null) |
| Published (page `<time>`) | 2026-10-01T01:31:48.554Z | 2026-10-01T01:31:48.554Z |
| Market data through | 2026-09-30 | 2026-09-30 |
| `prerenderedAt` (build stamp) | 2026-10-01T01:37:41.697Z | 2026-10-01T01:37:41.857Z |
| `Last-Modified` | Thu, 01 Oct 2026 01:38:26 GMT | same |
| Drift errors / warnings | 0 / 0 | 0 / 0 |
| Page cadence claim | "Rebuilt weekly after the market and model refreshes." | "Rebuilt weekly after the IDP and market refreshes." |

- **Conditional GET verified live.** A second run sent `If-None-Match` and
  `If-Modified-Since`, received 304 on both boards, and created no release. The
  information clock did not move.
- **Identity against the 2026-09-30 export board (1,131 rows):**
  - Resolved: 757 of 1,872 (offense 344, IDP 413).
  - Ambiguous: 6. These are real homonyms on the IDP board (Byron Murphy CB/DT,
    Byron Young DE/DT, Jordan Phillips DT×2).
  - Unresolved: 1,109. Of these, 1,105 are `no_board_row`, with median positional rank
    144 because Signals ranks deeper than our board; only 1 sits in a top-24 positional
    rank. The other 4 are `position_group_mismatch`, including Travis Hunter (CB vs our
    WR row) and Justin Jefferson LB, who was correctly not joined to the WR.
- **Privacy:** `git status --ignored` shows `data/sources/` as ignored, and no raw page,
  release or cookie is staged. The store is 1.9 MB.

### 8.3 Activation stage per dataset

| Dataset | Stage | Evidence |
|---|---|---|
| Offense dynasty board (public) | **2 — real authorized observations ingested, validated, replayable** | §8.2 capture; raw page + normalized release stored privately and replayable through the deterministic parser |
| IDP dynasty board (public) | **2** | same |
| Both, as a visible second opinion | **3 — implemented, not yet deployed/verified** | authenticated endpoint plus the /trade rank-only line ("positional rank only · not counted"), with explicit not-collected / not-ranked / out-of-scope states. Stage 3 becomes VERIFIED after merge, deploy, timer enable and an observed authenticated response on production |

### 8.4 Cadence evidence

One observation so far. Both boards carry the same Published stamp
(2026-10-01T01:31:48Z), and Last-Modified is about 6.5 minutes after it (the static
rebuild). The page text says the boards are "rebuilt weekly", while the methodology pages
claim daily models. That conflict stays **unresolved**: the 6-hourly conditional checks
will accumulate Published / Last-Modified / content-change history in each board's
`dataset_state.json`. The faster claim is still not assumed.

### 8.5 What remains for stage 4/5

- The public boards have **no native value scale** and no cross-position ordering. They
  are therefore **not eligible** for canonical participation. Converting positional
  ordinals into prices would invent methodology.
- Native or league-adjusted values exist only in paid, authenticated surfaces. Reaching
  them is an **access dependency**: it needs an owner-controlled session. Permission is
  not the blocker.
- Any future value participation still needs the lineage and family-cap review in §3.

### 8.6 Not done here

- Box backup of `data/sources/signals/` is not covered: it is not in
  `riskit-state-backup`.
- The `/rankings` page shows nothing yet; only /trade renders the line.
- `rankOnlyOpinionFor` does not distinguish identity-quarantined rows from unranked
  rows; both read "not ranked / unresolved". The server's `identity` block lists the
  reasons.

## 9. Active canonical source — authenticated native values (2026-10-03)

**Authority.** Owner addendum of 2026-10-03 ("Signals must become an active
offense + IDP source"), confirmed in chat. Voting path chosen by the owner the
same day: **value-ordered rank** — Signals votes exactly as FantasyCalc and
Dynasty Daddy do (its own cross-position native-value ORDER becomes a rank;
rank → percentile → Hill). Value-direct was declined on measurement: Signals
values run ~1.0× market at the top but 1.4–3.1× too high deeper (vs IDP Trade
Calculator for IDP, vs FantasyCalc for offense) — a much flatter curve, so the
value-direct path would be new methodology.

### 9.1 What votes, and what never does

| Dataset | Registry key | Vote | Notes |
|---|---|---|---|
| Offense native values (`PlayerValueSnapshot.signalsDynastyValue`, daily) | `signalsSf` | **yes** — value-ordered rank, OFFENSE Hill | Dynasty · **Superflex** · **not TE-premium** |
| IDP native values (`listIdpDynastyValuesBySeason`, sk `<season>#dynasty`) | `signalsIdp` | **yes** — value-ordered IDP rank through the shared-market IDP ladder | raw CB/S/DT/DE/LB kept as provenance; DL/LB/DB via `name_clean.normalize_position` |
| Public positional boards | `signalsDynasty`, `signalsIdpDynasty` | **never** | positional ordinal only (§8) |
| Exact-league values | — | not collected | computed client-side by Signals' app over a FantasyCalc fetch — not a server observation, not reimplemented |
| Snapshot KTC / redraft fields | — | never selected | KTC is its own source; redraft is the seasonal lane |

**Selection hierarchy, one observation per player** (`signals.build_board_rows`):
native value → VALUE (rank DERIVED from the value order, competition ranks);
no value but an authenticated CROSS-POSITION rank → RANK fallback; otherwise
MISSING. Neither payload publishes a cross-position rank today, so the
fallback is implemented and pinned by synthetic tests but structurally inert;
positional ranks are retained as provenance and never become an overall order.
Homonyms inside a dataset (6 IDP rows on 2026-10-03) and rows keyed by a vendor
slug instead of a Sleeper id (2 IDP draft-prospect rows) are withheld, never
guessed.

**Format, established by measurement (2026-10-03).** Superflex: Josh Allen
above Jaxon Smith-Njigba, and Caleb Williams / Lamar Jackson / Joe Burrow
priced as top-12 assets (a 1QB board puts those QBs near half of WR1). Not
TE-premium: the TE1 sits below WRs FantasyCalc prices equally, and no TEP
control exists on the stored value. So `is_tep_premium=False` and the board's
measured base → TE++ conversion (ADR-015) applies **exactly once** (pinned:
`tepBoostApplied`, `tepBasisFrom == "base"`, no native correction). Signals'
stored value carries no league adjustment, so none is double-applied.

### 9.2 Lineage and family

Signals' web app bundle (read-only, 2026-10-03) falls back to FantasyCalc's
value for its dynasty baseline (`dynastyValueMap ?? dynastyValue ?? fcValue`)
and computes league-exact values over a FantasyCalc fetch. The stored value's
own ancestry is not vendor-stated, so the relation is **suspected**
(`signals-fantasycalc-app-composition`, `config/sources/source_lineage.json`).
Owner direction: no independence bonus. Both Signals keys therefore carry
`correlation_group: "fantasyCalc"`: FantasyCalc + Signals share one provider's
authority per row through `cap_family_weights`, and count as ONE B10 family to
the confidence gate. Not a Hill trainer or holdout (`NOT_HILL_BOARDS`).

### 9.3 Data path, privacy, and CI vs box

* **Where production builds the served contract** (verified in `server.py`):
  in-process on the box, from the raw scrape payload plus every registered
  CSV, at startup and after each promoted scrape (`_prime_latest_payload` →
  `build_api_data_contract`). CI builds its own contract (refresh workflow,
  PR validation, the deploy FULL lane) from committed inputs only.
* **Collection** (box only): `scripts/fetch_signals_values.py` on the
  `dynasty-signals-values` timer (6-hourly at :17, `--min-interval-hours 5`)
  with the owner session at `/var/lib/signals-auth`. Measured run: 23 GraphQL
  requests (21 aliased offense batches of 25 + 2 IDP pages), hard cap 60.
  One renewal on 401/403 (and on AppSync's HTTP-200 `Unauthorized`), then a
  recorded `access_denied` stop; 429 honours Retry-After; schema drift, runaway
  pagination or a row collapse quarantines the release and keeps the last good
  board with its true age.
* **Private store** (gitignored, never force-added — pinned by a test):
  `data/sources/signals/values/` (raw, releases, latest, quarantine, fetch
  state, `collector_state.json`) and the board CSVs
  `data/sources/signals/board/signalsSf.csv` / `signalsIdp.csv` that the
  contract reads. Dataset state and success stamps go to the box's
  `data/scrape_state/` and are in `PROD_TIMER_OWNED_KEYS`, so the GitHub
  refresh never writes (or commits) a Signals state file.
* **Absent by design.** `data_contract.private_source_availability` decides,
  from files on the host: CSV present → votes; collector has run but CSV gone
  → `missing` → `source_missing` (a real failure, source-health lane);
  collector never ran (CI, local dev, a fresh box) → `not_provisioned` → no
  vote, expected on no row, a warning (`private_source_absent_by_design`) and
  never an error in either CI lane. The contract stamps
  `privateSourceAvailability`; a payload without the stamp fails closed. The
  freshness watchdog reports such a source as not provisioned instead of
  unmeasurable.
* **Stale never masquerades as current.** The vendor's own stamp is the
  freshness clock (`EXPLICIT_UPSTREAM_TIMESTAMP`; offense = the newest
  `updatedAt` of the run's publication date, IDP = `sourceUpdatedAt`), an
  auth failure moves no clock and refreshes no success stamp, a quarantine
  records DEGRADED health, and the offense collector keeps only the run's
  majority publication date — a player whose newest snapshot is older is
  excluded, not carried forward. Budgets: `_SOURCE_MAX_AGE_HOURS` 24 =
  `config/source_staleness.json` `signals` 24.
* **Who can see it.** Per-source numbers reach only authenticated endpoints
  (`/api/data`, `/api/rankings/overrides`); the public `/league` guard now
  refuses `sourceNativeValues`, `sourceOriginalRanks`, `signalsSf` and
  `signalsIdp`. CI never holds the data, so committed exports and archives
  cannot carry it. On the box, Signals values also reach the private `data/`
  histories (rank/source-value history, temporal ledger) and the operator's
  own state backup — never the repository.

### 9.4 Rankings source column

Two columns, **Signals** (offense) and **Signals IDP**, rendered by the
existing source-column contract: the cell shows the source's 1–9,999 Hill
contribution and effective board rank; its title, the mobile chip and the
expanded audit card add the native value, "value-ordered rank (derived)" (or
"published rank" for a RANK fallback), VALUE vs RANK fallback, the dataset,
the format ("Dynasty · Superflex · non-TEP (TE++ converted)" / "Dynasty · IDP")
and the content as-of + freshness state from `sourceWeighting`. Every number
is a backend stamp (`frontend/app/rankings/board-utils.js::sourceObservation`).

### 9.5 Whole-board impact (measured on the production box, 2026-10-03)

Branch code run read-only against the box's own inputs (raw payload
`dynasty_data_2026-10-03.json`, scrape 14:39 UTC; the box's CSVs and scrape
state), building the contract with and without the Signals store under
`/tmp`. Both builds validate `ok` with zero structural and zero source-health
errors.

| | Offense (`signalsSf`) | IDP (`signalsIdp`) |
|---|---|---|
| Collected | 509 valued (517 queried; 8 without a snapshot in window) | 1,064 board rows (1,072 published; 6 homonyms + 2 slug ids withheld) |
| Joined to board rows | 501 of 507 | 416 of 423 |
| Voted / Hampel-dropped | 480 / 21 | 388 / 28 |
| Rows whose value moved | 454 of 507 | 360 of 423 |
| Median / p90 abs change | 17 / 86 (0.79% / 4.74%) | 17 / 573 (1.02% / 213.8%) |
| Max abs change | 1,403 | 1,833 |
| Top-50 membership | unchanged | +1 / −1 |
| Top-200 membership | +1 / −1 | +6 / −6 |
| Confidence buckets changed | 9 (all `none` → `low`) | 26 (all `none` → `low`) |

* The IDP p90 is driven by deep, previously single-source rows: a second
  source lifts them out of the existing 30% single-source haircut, so a
  floor-region value roughly triples. That is the existing methodology
  responding to new evidence, not a Signals-specific rule.
* Largest moves where Signals disagrees with the consensus: an elite veteran
  edge rusher (5,236 → 3,403, rank 61 → 144), the two-way WR/CB (3,982 →
  3,274), and deep offense rows previously priced on one or two sources.
* Family cap: 362 offense rows carry both FantasyCalc and Signals votes;
  their combined authority never exceeds one provider's (max 1.0000, median
  family adjustment 0.5). 69 current-year pick rows move through the existing
  rookie tether.
* The top of each position barely moves (Josh Allen 9,972 → 9,972; Jaxon
  Smith-Njigba 9,623 → 9,623; Bijan Robinson and Brock Bowers unchanged, where
  Signals' vote was Hampel-dropped). Representative top / middle / deep rows
  per position and rookies are in the PR record.

### 9.6 Rollback

`RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE=0` + restart: both keys leave the active
source set exactly as a disabled source does (no vote, not expected), their
native values stay visible, and the contract stamps
`privateSourceAvailability[*].rolledBack`. Stopping the
`dynasty-signals-values` timer instead leaves the last board to age out
through freshness weighting.

### 9.7 Not done / unresolved

* No point-in-time Signals history exists yet, so FantasyCalc/Signals
  dependence is unmeasured (`pair-signals-market-families` stays UNKNOWN).
* The authenticated offense board is read for the players the raw payload
  carries (517 with Sleeper ids on 2026-10-03); a Signals-valued player the
  board cannot hold is not queried.
* The RANK fallback is inert until a dataset publishes a cross-position rank.
* Production verification (acceptance 17) happens after merge and deploy.
