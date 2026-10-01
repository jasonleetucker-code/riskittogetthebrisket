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
| **Activation stage** | Advancing under Batch 2 Unit A (§8). Stage 1 (discovered) was reached on 2026-09-30; stages 2–3 for the public boards are recorded in §8 with their evidence. Stages 4–5 (shadow, then active canonical participation) require comparable native dynasty values, which the public boards do not publish. |
| **Affects canonical values?** | **No.** Public positional ranks are not eligible to vote, and nothing Signals-derived enters `_RANKING_SOURCES`. |
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
| Offense dynasty board — public | `/rankings/dynasty` | public | positional rank + tier (S+…C); **no values**; stamped "Published …" and "Market data through …" | weekly rebuild (board page) vs daily engine (methodology) — **unresolved** | permission-blocked (automation); benchmark-only candidate as **ordering**, never cross-position prices |
| Offense dynasty values — league-adjusted | in-app | paid account | value scale; SF/TEP/custom scoring/roster/depth adjusted | "daily" (trade page, formats page) | access-dependent (owner session; permission resolved 2026-10-01) |
| IDP dynasty board — public | `/rankings/idp-dynasty` | public | true positions CB/S/DT/DE/LB; "MKT" positional label (meaning unconfirmed) | weekly (board) / "in progress" (methodology) | permission-blocked |
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
