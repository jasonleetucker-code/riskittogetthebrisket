# Signals Fantasy — data integration and product-capability record (2026-09-30)

**Owner direction:** #1555, extended 2026-09-30. Signals is a comprehensive integration
workstream whose intended destination is an **active, validated Calculator source**
(activation stage 5 where justified). That supersedes the earlier optional/benchmark-only
destination. The earlier record's access, validation, privacy and lineage requirements are
kept. Map: `docs/valuation/VALUATION_ADVANCEMENT_MAP_2026-09-30.md`.

## 1. Current status

| Question | Answer |
|---|---|
| Activation stage | **1 — discovered and characterized from public pages.** No real observation ingested. |
| Affects canonical values now? | **No.** No Signals data exists in any build. |
| Exact remaining gate | Signals' **prior written consent** for automated access/extraction (Terms §"Prohibited", effective 2026-08-31). Also needed: the owner's active subscription (not confirmed) and an owner-controlled session path. |
| Owner subscription | intended, **not confirmed** — no plan purchased, no trial started |
| KTC permission applies? | **No.** It does not transfer. |

**Evidence standard.** Everything in §3–§5 comes from the public pages listed in §2,
fetched once each on 2026-09-30 through a summarizing fetch tool. That means paraphrase,
not verbatim capture. "Claimed" means the page says it. "Observed" means the public page
itself displayed the data. Nothing behind authentication was accessed.

## 2. Access and rights boundary

- **Terms (effective 2026-08-31):**
  - Automated tools that "access or extract data" require prior written consent.
  - Reverse engineering and commercial exploitation are prohibited.
  - Account credentials may not be shared.
  - AI-generated output may not be commercially redistributed without consent.
  - API and data export are not addressed.
- **robots.txt** allows everything except `/admin-control`. **robots.txt does not grant
  consent.** The Terms govern.
- **Security page:** passwordless email one-time codes; short-lived sessions via AWS
  Cognito; connected platforms read-only (except paid ESPN auto-lineups).
- **Blocked operations** — each needs written consent, however little it collects:
  - any scheduled or scripted fetch of public boards;
  - authenticated automated collection of paid datasets;
  - scripted CSV export;
  - storage of Signals data beyond personal use;
  - any derived value published outside the owner's private Calculator.
- **Permitted now:**
  - manual reading of public pages for research;
  - adapter and contract design;
  - **labelled synthetic** fixtures;
  - the draft permission request (§7).
- Also permitted, **pending confirmation of personal-use scope**: importing a CSV the
  owner exports manually from his own account for private use. It is disabled until the
  owner confirms and the §7 request answers whether storing it in Calculator is personal
  use.
- **Secrets:** never in chat, issues, fixtures, logs or screenshots. If authorized, use an
  owner-controlled login flow with local ignored storage or an approved secret manager.
  401/403 stops collection without retry loops. Expiry means refusing, not re-logging
  repeatedly.

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
| Offense dynasty board — public | `/rankings/dynasty` | public | positional rank + tier (S+…C); **no values**; stamped "Published …" and "Market data through …" | weekly rebuild (board page) vs daily engine (methodology) — **unresolved** | permission-blocked (automation); benchmark-only candidate as **ordering**, never cross-position prices |
| Offense dynasty values — league-adjusted | in-app | paid account | value scale; SF/TEP/custom scoring/roster/depth adjusted | "daily" (trade page, formats page) | permission-blocked |
| IDP dynasty board — public | `/rankings/idp-dynasty` | public | true positions CB/S/DT/DE/LB; "MKT" positional label (meaning unconfirmed) | weekly (board) / "in progress" (methodology) | permission-blocked |
| IDP dynasty values — league-adjusted | in-app | paid (Fanatic) | value scale | unclear | permission-blocked |
| Redraft / ROS / weekly projections (+IDP stat lines) | in-app; `/methodology/redraft` | paid | full stat lines scored per league | daily in season | permission-blocked; **external-projection baseline only**, never fundamentals |
| Devy + IDP prospect boards, grades, confidence, projected draft capital | `/rankings`, `/formats/devy` | boards public (not yet read); grades paid | grade + confidence | weekly | permission-blocked; contextual-only (vendor grades are model outputs, not scouting facts) |
| Rookie / future picks | in-app | paid | same value scale; priced as the 3rd-best class prospect, adjusted | daily (claimed) | permission-blocked |
| Player cards (fields, history, movement) | in-app | paid | undocumented publicly | — | not exposed publicly; permission-blocked |
| General vs league-adjusted boards; personal overrides; CSV import/export of custom rankings | `/features/rankings` | paid | CSV (fields undocumented) | — | owner-manual export = pending personal-use confirmation; **user edits are never independent evidence** |
| Trade calculator (itemization, package multipliers, consolidation, both-team lineup impact, league trade history, GO/NO-GO) | `/features/trade-calculator` | free basic, paid depth | — | daily models (claimed) | permission-blocked; product-capability reference (§5) |
| League / roster diagnostics (archetypes, strengths, age curves, draft capital, playoff odds, portfolio) | `/features/league-analyzer` | paid | — | — | permission-blocked; capability reference |
| Draft tools (mocks, live assistant, Chrome overlay) | `/features/draft-assistant` | paid | — | — | out of scope for data; capability reference |
| Waiver report (FAAB ranges), start/sit, lineup optimizer | `/features/waiver-report`, `/features/start-sit` | free (1 league) / paid | — | weekly | permission-blocked; capability reference |
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

## 4. Source contract (implemented only after consent; designed now)

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

## 7. Permission request — DRAFT, not sent (owner decision to send)

> Subject: Written consent request — automated access for a private dynasty analysis tool
>
> I subscribe (or will subscribe) to Signals and run a private, single-user dynasty
> analysis tool. Your Terms require prior written consent for automated access. I am asking
> for consent covering:
> 1. **Datasets:** dynasty and IDP dynasty boards (public and my league-adjusted values),
>    rookie/future pick values, prospect boards, and redraft/ROS projections for my own
>    leagues.
> 2. **Method:** authenticated, read-only automation from my own account, or a supported
>    export/API if you offer one. No credential sharing; no access to other users' data.
> 3. **Frequency:** at most once per publication (daily or weekly as you publish), with
>    conservative rate limits.
> 4. **Retention:** historical snapshots kept privately to measure changes over time.
> 5. **Derived values:** your values used as one input among many in my private valuation
>    model, and as a displayed "second opinion" visible only to me.
> 6. **Display:** no public display, redistribution or commercial use without separate
>    agreement.
> 7. **Clarification:** which datasets rebuild weekly vs daily, and whether an owner-exported
>    CSV imported into a personal tool is within personal use.

The owner must send it himself. No commercial terms are accepted on his behalf.
