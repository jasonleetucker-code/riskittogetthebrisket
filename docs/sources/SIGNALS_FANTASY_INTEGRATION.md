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
| **Activation stage** | **Offense: stage 5, ACTIVE (`signalsSf`, owner addendum 2026-10-03, §9). IDP: collected and displayed, HELD from voting (§9.2).** The public boards stay at stage 3 (non-voting second opinion, §8). |
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
Dynasty Daddy do (its own native-value ORDER becomes a rank; rank → percentile
→ Hill). Value-direct was declined on measurement: Signals values run ~1.0×
market at the top but 1.4–3.1× deeper, a much flatter curve, so the
value-direct path would be new methodology.

**State after the independent review of #1627: OFFENSE ACTIVE, IDP HELD.**
The IDP boards are collected, stored and displayed, but cast no vote (§9.2).

### 9.1 What votes, and what never does

| Dataset | Registry key(s) | Vote | Notes |
|---|---|---|---|
| Offense native values (`PlayerValueSnapshot.signalsDynastyValue`, daily) | `signalsSf` | **yes** — value-ordered rank, OFFENSE Hill | Dynasty · **Superflex** · **not TE-premium** |
| IDP native values (`listIdpDynastyValuesBySeason`, sk `<season>#dynasty`) | `signalsIdpDl`, `signalsIdpLb`, `signalsIdpDb` (one board per family, scope `position_idp`) | **HELD** (`data_contract.PRIVATE_SOURCE_VOTE_HOLDS`) | ranked WITHIN family only; raw CB/S/DT/DE/LB kept as provenance; DL/LB/DB via `name_clean.normalize_position`, checked against Signals' own `family` |
| Public positional boards | `signalsDynasty`, `signalsIdpDynasty` | **never** | positional ordinal only (§8) |
| Exact-league values | — | not collected | computed client-side by Signals' app over a FantasyCalc fetch; not a server observation, not reimplemented |
| Snapshot KTC / redraft fields | — | never selected | KTC is its own source; redraft is the seasonal lane |

**Selection hierarchy, one observation per player** (`signals.build_board_rows`):
native value → VALUE (rank DERIVED from the value order, competition ranks);
no value but an authenticated rank on the board's own basis → RANK fallback;
otherwise MISSING. Neither payload publishes such a rank today, so the fallback
is implemented and pinned by synthetic tests but inert. Positional ranks are
retained as provenance and never become an overall order. Dataset-internal
homonyms (6 IDP rows) and rows keyed by a vendor slug instead of a Sleeper id
(2 IDP draft-prospect rows) are withheld, never guessed.

**Offense format, established by measurement (2026-10-03)** on the
authenticated board: Superflex (elite and mid-tier QBs price as superflex
assets, not at 1QB levels), and not TE-premium (TEs price below the WRs
FantasyCalc prices equally, and the stored value has no TEP control). So `is_tep_premium=False`, and the board's
measured base → TE++ conversion (ADR-015) applies **exactly once** (pinned).
The stored value carries no league adjustment, so nothing is double-applied.

### 9.2 IDP — why each family is separate, and why it is held

**Signals' IDP value is not a cross-family price** (independent review B1,
2026-10-03). `value` is a strictly monotone function of a per-family
`data.composite` (Spearman 1.000). Each family is normalised on its own scale:
the tops are within 4% of each other, and the curves are near-identical at #12
and #24. That makes the value inconsistent with Signals' own `projectedFp`
across families, and its top-100 is about half DBs (15–24 for IDPTC / DLF /
IDP Show).

The first design ordered it across families and crosswalked that order
through the shared-market ladder. That manufactured the shared DL/LB/DB rank
the addendum forbids. Measured, it drove an elite edge rusher 5,236 → 3,403
and pushed five DLs out of the top 200. That design is gone: the collector now
ranks each family **within itself only** and writes one board per family.

**The only existing route for a within-family rank is the positional IDP path**
(`SOURCE_SCOPE_POSITION_IDP` + `IdpBackbone.ladder_for`), which had never been
exercised. It works mechanically and is now pinned:
- a within-family rank lands exactly on that family's backbone ladder;
- a family #1 never inherits the IDP #1 price;
- with no family ladder, the vote is WITHHELD (Lane 8 rule), never passed
  through.

But it lands the rank in **IDP-local coordinates**, priced by the IDP master,
while every other IDP voter is priced in the **shared market**. Measured on the
production board with the hold lifted:
- an LB the backbone ranks IDP #4 contributed 9,484, against 5,238–5,668 from
  the other sources on the same row;
- 76 of 406 Signals IDP votes were outlier-dropped;
- the surviving votes widened the outlier window enough to re-admit other
  sources' outliers (+867 and +875 on two top-50 LBs).

Making the boards vote needs a coordinate decision. For example, the family
ladder could be composed with the shared-market IDP ladder and routed to the
GLOBAL curve. That is methodology, so the IDP half is **HELD**:
- collected and displayed ("collected, NOT voting" in the Rankings column);
- no vote;
- not an expected source;
- no confidence family;
- the contract stamps `privateSourceAvailability[*].heldFromVote`.

Lifting the hold is a reviewed change to `PRIVATE_SOURCE_VOTE_HOLDS`.

### 9.3 Lineage and family

Signals' web app bundle (read-only, 2026-10-03) falls back to FantasyCalc's
value for its offense dynasty baseline (`dynastyValueMap ?? dynastyValue ??
fcValue`) and computes league-exact values over a FantasyCalc fetch. The stored
value's own ancestry is not vendor-stated, so the relation is **suspected**
(`signals-fantasycalc-app-composition`).

- **Offense:** no independence bonus (owner direction). `signalsSf` sits in the
  `fantasyCalc` B10 group: FantasyCalc + Signals share one provider's
  authority per row (`cap_family_weights`) and count as ONE family to the
  confidence gate.
- **IDP (when it votes):** the IDP boards share that group, but FantasyCalc
  publishes no IDP, so on IDP rows Signals would be its own family. That is
  defensible because its IDP value is model-derived from per-snap features
  (projected points, prior-season points, pressure and playmaking per snap)
  with no market input. Recorded in `source_lineage.json`. Not a Hill
  trainer or holdout (`NOT_HILL_BOARDS`). The shared `fantasyCalc` label on
  the IDP boards is **deliberate**: family leave-one-out
  (`expand_correlation_groups(["fantasyCalc"])`) drops them together with
  FantasyCalc, which is the conservative direction, and the two never meet
  on a row today. If FantasyCalc ever registers an IDP key, revisit the
  group before it ships.
- **What the cap does not cover (pre-existing design, stated here because
  this is the first family whose extra member is a different provider's
  composition).** The outlier filter and the count-aware blend rung count
  OBSERVATIONS, not families: Hampel runs before the family cap, so
  FantasyCalc + Signals act as two agreeing points when judging the other
  sources, and the n ≥ 5 trim rung can be reached with four families
  present. This is the same posture DLF and KTC Crowd + Navigator already
  have, and the owner directive of 2026-09-24 accepted it ("runs AFTER
  Hampel deliberately"). The cap bounds the family's WEIGHT in the blend;
  it does not make the filter family-aware.
- **Two-way players.** A private source that does not vote on a build
  (absent, held, in shadow, or rolled back) is also excluded from the
  two-way player alt-family value, so it cannot reach the board through that
  side door.

### 9.4 Data path, privacy, and CI vs box

- **Where production builds the served contract** (verified in `server.py`):
  in-process on the box, from the raw scrape payload plus every registered CSV,
  at startup and after each promoted scrape (`_prime_latest_payload` →
  `build_api_data_contract`). CI builds from committed inputs only.
- **Collection** (box only): `scripts/fetch_signals_values.py` on the
  `dynasty-signals-values` timer (6-hourly at :17, `--min-interval-hours 5`)
  with the owner session at `/var/lib/signals-auth`.
  - Measured run: 23 GraphQL requests, hard cap 60.
  - One renewal on 401/403 (and on AppSync's HTTP-200 `Unauthorized`), then a
    recorded `access_denied` stop.
  - 429 honours Retry-After.
  - Schema drift, a vendor family disagreeing with the raw position, runaway
    pagination, a board below its floor (`MIN_BOARD_ROWS`) or a row collapse
    quarantines the release and keeps the last good boards.
- **Private store** (gitignored, never force-added; pinned by a test):
  - `data/sources/signals/values/`: raw, releases, latest, quarantine, fetch
    state, `collector_state.json`;
  - the board CSVs `data/sources/signals/board/signalsSf.csv` and
    `signalsIdp{Dl,Lb,Db}.csv`.
  - Dataset state and success stamps go to the box's `data/scrape_state/`
    and are in `PROD_TIMER_OWNED_KEYS`, so the GitHub refresh never writes or
    commits them.
- **Absent by design.** `data_contract.private_source_availability` decides
  from files on the host. Provisioning evidence is the collector marker OR any
  `<key>_last_success` / `<key>_dataset.json` in the scrape state, so deleting
  the store on a box that collected surfaces `missing`.
  - CSV present → votes (unless held);
  - provisioned but CSV gone → `source_missing`;
  - never provisioned (CI, dev, a fresh box) → `not_provisioned`: no vote, not
    expected, a warning only, never an error in either CI lane.
  - A payload without the stamp fails closed.
- **Stale and auth-failed data.**
  - The vendor's own stamp is the freshness clock (`EXPLICIT_UPSTREAM_TIMESTAMP`).
  - A quarantine records DEGRADED health.
  - The offense collector keeps only the run's majority publication date.
  - An **auth stop** moves no clock and refreshes no success stamp. The last
    good board therefore keeps voting at a weight that decays with its true
    age through the freshness curve, until it falls below the quarantine floor
    and stops voting. That is the same posture every source has when its
    fetcher fails.
  - The board is labelled stale (`dataFreshness.sourceTimestamps`, the
    source-health alert and the freshness watchdog) once the success stamp is
    more than 24 h old (`_SOURCE_MAX_AGE_HOURS` 24 = `config/source_staleness.json`
    `signals` 24).
- **Who can see it.** Per-source numbers reach only authenticated endpoints
  (`/api/data`, `/api/rankings/overrides`). The public `/league` guard refuses
  `sourceNativeValues`, `sourceOriginalRanks` and every Signals key. CI never
  holds the data, so committed exports cannot carry it. On the box, Signals
  values also reach the private `data/` histories and the operator's own state
  backup, never the repository.

### 9.5 Rankings source column

**Signals** (offense) votes. **Signals DL / LB / DB** show the held IDP boards.
The cell title, the mobile chip and the expanded audit card carry:
- native value;
- "value-ordered rank (derived)" (per family for IDP), or "published rank" for
  a RANK fallback;
- VALUE vs RANK fallback;
- dataset and format;
- as-of and freshness state;
- for the IDP boards, "collected, NOT voting".

Every number is a backend stamp (`frontend/app/rankings/board-utils.js::sourceObservation`).

### 9.6 Whole-board impact (production box, 2026-10-03, re-measured after the rework)

Branch code run read-only against the box's own inputs (raw payload
`dynasty_data_2026-10-03.json`, scrape 19:00 UTC; the box's CSVs and scrape
state), with and without the Signals store under `/tmp`. Both builds validate
`ok` with 0 structural and 0 source-health errors.

| | Offense (`signalsSf`, active) | IDP (held) |
|---|---|---|
| Collected | 509 valued (516 queried) | DL 445 / LB 205 / DB 414 board rows |
| Joined to board rows | 502 / 507 | 416 / 423 |
| Voted / outlier-dropped | 482 / 20 | 0 / 0 |
| Rows whose value moved | 456 / 507 | **0** |
| Median / p90 abs change | 18 / 86 (0.76% / 4.93%) | 0 |
| Max abs change | 1,400 | 0 |
| Top-50 membership | +DeVonta Smith / −Christian McCaffrey | unchanged |
| Top-200 membership | +Colby Parkinson / −Ollie Gordon | unchanged |
| IDP top-50 / top-100 family share | — | unchanged: DB 6 / DL 19 / LB 25; DB 17 / DL 38 / LB 45 |
| Confidence buckets changed | 9 (`none` → `low`) | 0 |

**Review watch list:**

| Player | Before → after | Rank | Bucket |
|---|---|---|---|
| Myles Garrett (DL) | 5,237 → 5,237 | 61 → 61 | <1% |
| Travis Hunter (WR) | 3,997 → 3,997 | 107 → 106 | <1% |
| DJ Rogers (TE) | 674 → 2,074 | unranked → 313 | >15% (offense vote; the row leaves the single-source haircut) |

- **Family cap:** 363 offense rows carry both FantasyCalc and Signals votes;
  combined authority max 1.0000, median family adjustment 0.5.
- **Picks:** 57 current-year pick rows move through the existing rookie tether.

### 9.7 Rollback

- `RISKIT_FEATURE_SIGNALS_ACTIVE_SOURCE=0` + restart removes every Signals vote
  (stamped `rolledBack`).
- Stopping the `dynasty-signals-values` timer leaves the last boards to age
  out through freshness weighting.

### 9.8 Not done / unresolved

- **IDP is held** pending a coordinate decision for within-family ranks (§9.2).
- No point-in-time Signals history exists, so FantasyCalc / Signals dependence
  is unmeasured (`pair-signals-market-families` stays UNKNOWN).
- The offense board covers only the players the raw payload carries with
  Sleeper ids.
- The RANK fallback is inert.
- Production verification (acceptance 17) happens after merge and deploy.

## 10. Signals IDP — shared-market family crosswalk (PREREGISTERED 2026-10-04)

Written before any production measurement of the new route.  The candidates,
metrics and thresholds below are fixed; results are appended in §10.6 and
judged against them, never the other way round.

### 10.1 What Signals knows, and what it does not

Signals' IDP values are normalised WITHIN a family (DL, LB, DB each have their
own scale, §9.2).  Signals therefore says "this player is about LB3" and does
not say "LB3 > DB2".  The crosswalk uses Signals for the first statement only
and the existing shared market for the second: where the k-th player of a
family sits against every other IDP, offense and pick is the shared market's
question, answered by its existing owner.

### 10.2 The coordinate system (no new scale)

The bridge owner (`src/bridges/ladder.py`) already builds the shared-market
ladder every other IDP voter is translated through (today exactly IDP Trade
Calculator, `multi_bridge_ladder` OFF).  It now also publishes, in the same
pass, a FAMILY slice: the combined offense+IDP+pick rank of each family's
i-th player.  Same ordering, same rescale and blend, same monotonicity.

Lineage, unchanged and already recorded in `config/sources/source_lineage.json`:
the shared market is positioned against IDPTC's offense half, which is a lagged
copy of KTC Crowd in some batches (`idptc-offense-ktc-value-identity`).  The
crosswalk inherits that dependence exactly as `dlfIdp` and `fantasyProsIdp`
already do; it adds none.

Reproducibility: a crosswalk result is a function of (code SHA, the board's raw
payload, the IDPTC CSV, the Signals release `contentSha256`, the league's
scoring card, identity owner version).  The on-box evaluation records all of
them.

### 10.3 Candidates (exactly two; declared before results)

| | Rule | Role |
|---|---|---|
| **A** | Signals family rank k → `family_ladder[k-1]` (shared-market combined rank of the k-th player of that family) → GLOBAL curve.  k past the ladder's depth is WITHHELD (no extrapolation).  Only value-ordered rows (a native value exists). | The candidate for promotion.  Implemented in the contract (shadow). |
| **B** | Signals family percentile `(k-1)/(N_signals-1)` → the same quantile of the family ladder (linear interpolation) → GLOBAL curve. | Diagnostic only: shows how much of any disagreement is Signals covering more or fewer players of a family than the market.  Not promotable in this round. |

The incumbent ("champion") is the board with no Signals IDP vote.

#### 10.3.1 Future candidates — declared, NOT run (amendment 2026-10-04)

**Prospective only.**  This amendment was merged before any production
evaluation result was inspected.  It changes nothing about Candidates A and B,
the §10.4 metrics or the §10.6 gate; those stay exactly as preregistered and
are what the first on-box run evaluates.  C, D and E are named now so that no
method can be chosen after the numbers are seen.  Each runs only in a FUTURE
round, once its entry condition holds, under its own preregistration.

| | Rule | Role | Entry condition |
|---|---|---|---|
| **C** | Monotone (isotonic) family map from Signals' within-family rank to the shared-market coordinate, fitted on players that carry independent shared-market evidence. | Promotable in a future round. | A **second, genuinely independent** shared-market reference must exist **for validation**: C is fitted against one reference and judged against another.  Fitting and judging against the same reference is circular.  Today the only bridge is IDP Trade Calculator (`multi_bridge_ladder` OFF), so C cannot run. |
| **D** | Completed-trade-informed family crosswalk. | Promotable in a future round. | **Absolute floor: at least 30 unique, deduplicated, format-comparable underlying IDP trades per position family** (DL, LB, DB separately), one per `underlyingTradeId`, dispositions `NATIVE_COMPARABLE` / `VALIDATED_TRANSFORMABLE` only (§10.7).  Thirty is a floor, NOT a finding of adequacy.  Every D report also states, per family: distinct-league count, effective sample size (Kish, with each league's trades weighted so one league cannot stand in for many), time span, format similarity to `dynasty_main`, and concentration (largest single-league and single-manager share).  Repeated trades from one league or one manager, and duplicated observations of one trade (a Sleeper trade seen twice, a KTC/Sleeper echo), may not be what satisfies the floor.  Fit and validation are time-split; a trade used to fit D never validates it. |
| **E** | BDVM structural position scarcity (DL / LB / DB). | **Diagnostic / structural reasonableness check only — never a promotable market-price candidate.** | None needed to report it.  BDVM may say whether a learned DL / LB / DB relationship is structurally plausible for this league's lineup and scoring.  It is fundamental value, not the market-value target, so it never prices a Signals vote and can never by itself pass or fail a candidate. |

### 10.4 Metrics, per family (DL, LB, DB) and combined

Rows collected, identity-matched, translated, withheld (by reason),
extrapolated (must be 0 for A); family-position mismatches — a Signals family entry joined to a row we hold at another position — are **hard-withheld**: counted, reported, and zero of them may vote (made explicit 2026-10-04, prospectively);
Hampel outlier drops among Signals votes; value movement median / p90 / max;
rank movement median; top-50 / top-100 / top-200 membership changes; DL/LB/DB
share of the IDP top-100 and of the overall top-200; confidence-bucket
changes; independent-family-count changes; the watch list (§10.5); completed-
trade fit (§10.7).

### 10.5 Watch list (interpretation only; never tuned on)

The #1627 cases (the LB the backbone ranks IDP #4 that the retired route
priced at 9,484; the two top-50 LBs re-admitted at +867 / +875), plus for each
family the Signals rank-1, rank-12 and rank-36 players (elite / mid / deep),
plus the five rows where Signals' family rank and the market's family rank
differ most.

### 10.6 Promotion gate (fixed now)

Candidate A may be switched on (`signals_idp_shared_market`) only when ALL hold
on the production board:

1. No Signals-created cross-family order (structural; tested).
2. Every Signals IDP vote lands in `shared_market` coordinates (structural; tested).
3. The 9,484 case: the watch-list LB's Signals contribution lies within the
   range of the other sources on its row, widened by 15%.
4. Hampel drops among Signals IDP votes ≤ 5% (the retired route: 76/406 = 19%),
   with the outlier window unchanged (no threshold edits).
5. Family composition: each family's share of the overall top-200 moves by at
   most 3 percentage points.  (Amended 2026-10-04, before any result was
   run: the earlier "or explained by named rows" escape could not fail and
   is removed.)
6. Board movement: IDP value movement median ≤ 2%, p90 ≤ 8%; no offense
   PLAYER row changes value.  Current-year slot picks are tethered to the
   merged offense+IDP rookie pool (Phase 5.2b), so a Signals-covered IDP
   rookie can legitimately move a slot pick: that pick movement is allowed,
   reported separately (count, median, max), and never counted as a
   violation.  (Amended 2026-10-04, before any result was run — the
   earlier "no non-IDP row moves" was predictably violated by that known
   coupling.)
6b. Coverage bias: per family, the SIGNED median of
   (`wouldContribute` − row median of the other sources) / row median lies
   within ±5%.  Signals' family rank counts only rows Signals covers while
   the family ladder counts rows the bridge covers, so a coverage hole above
   rank k shifts every later Signals rank by one market position; an
   absolute-disagreement metric cannot see a consistent shift.  The count of
   bridge players Signals lacks (and vice versa) is reported per family.
   (Added 2026-10-04, before any result was run; from the IDP-math review.)
7. Independent fresh-context review approves the methodology and the numbers.
8. Tests cover missing ladder, bad identity, unsupported family, stale source.
9. Completed-trade evidence (§10.7) does not materially contradict A: the
   median absolute side gap of covered trades does not worsen by more than
   5% under A versus the champion.  The gap is the repo's canonical
   comparison quantity — raw + Value Adjustment (`_va_gap`), never a raw
   sum (amended 2026-10-04, before any result was run).  With fewer than 30 covered trades this
   criterion is recorded as INSUFFICIENT and does not block on its own; it is
   re-run as the ledger grows.

If any of 1–8 fails, the hold stays, the shadow keeps running, and the failed
criterion is recorded here.  A failed first challenger is evidence about A,
not about Signals IDP.

### 10.7 Completed-trade validation design

Source: the production `data/market_trades/underlying_trades.sqlite`
(`scripts/market_trade_ledger.py`), one row per `underlyingTradeId` (the
group owner already collapses a Sleeper trade seen twice and a KTC/Sleeper
echo of one event).  Admitted: dispositions `NATIVE_COMPARABLE` and
`VALIDATED_TRANSFORMABLE` only, verified dynasty, at least one DL/LB/DB player
on either side.  `BROAD_CONTEXT` trades are counted, not scored.  Score: for
each trade, the Value-Adjustment-inclusive gap (`suggestions._va_gap`, the
canonical comparison quantity) in canonical value, under the champion and
under A.  Candidate A fits no parameter, so no trade is used for fitting and
there is no train/test overlap.

### 10.8 Results

Appended from the on-box evaluation (`scripts/verify_signals_onbox.py`, workflow
`signals-onbox-verification.yml`).  ONLY the public projection is recorded
here — counts, distributions and per-criterion pass/fail.  The watch list,
largest disagreements and any per-player Signals number stay in the private
on-box report (`data/sources/signals/reports/`); this repository is public.
