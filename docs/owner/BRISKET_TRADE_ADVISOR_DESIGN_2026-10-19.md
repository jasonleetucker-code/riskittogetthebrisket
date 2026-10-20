# Brisket Trade Advisor — architecture audit and implementation design (2026-10-19)

**Status:** authoritative design record for PR #1861 and the follow-on advisor
units. **Product authority:** none of its own — the owner directive is
[`BRISKET_TRADE_ADVISOR_2026-10-19.md`](BRISKET_TRADE_ADVISOR_2026-10-19.md) and
current implementation authority is `docs/EXECUTION_PLAN.md`. OD-1..OD-8 below
are OPEN owner decisions, not decided scope.

> **SUPERSEDED IN PART — FAIRNESS-ONLY, MULTI-TEAM (2026-10-20).** The owner
> directive `docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md` and its
> same-day FAIRNESS-ONLY AMENDMENT replace the public recommendation product
> described below. The binding interface is
> [`docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`](../trade/NTEAM_TRADE_ENGINE_SPEC.md)
> §4 / §6.3. Read **Part 0** first; where Part II disagrees with Part 0, Part 0
> wins. Part I (the audit) stays as the historical record it is.

**How to cite this document.** Part I (the audit) uses sections **§A1–§A9**.
Part II (the design) uses **§0–§14**, then *Open questions / risks* (OD-1..OD-8)
and *Challenge disposition*. A bare `§N` means Part II.

**Redactions made when committing (2026-10-20).** Sandbox filesystem paths were
removed; specific canonical board values for named assets were replaced with
`<value>` placeholders (the direction of each measured change is kept); manager
first names in example payloads were replaced with placeholders. Nothing else
was changed apart from the audit section labels (§1–§9 → §A1–§A9) and one
corrected file pointer (marked inline).

---

# Part 0 — Current state: the public advisor is FAIRNESS-ONLY and multi-team (2026-10-20)

This part records what #1861 (Lane C of the multi-team directive) now
implements. It supersedes Part II wherever they disagree.

**What the public advisor answers.** One neutral question — *is this trade
fair?* — for 2-, 3- and 4-team trades:

| scope | results | labels |
|---|---|---|
| per participating team | `FAIR` / `NOT_FAIR` / `UNABLE_TO_DETERMINE` | `FAIR FOR THIS TEAM` / `NOT FAIR FOR THIS TEAM` / `UNABLE TO DETERMINE` (SD-14) |
| overall | `FAIR` only when every team is FAIR; any NOT_FAIR → NOT FAIR; else any UNABLE → UNABLE (Kleene AND, spec §2.9) | `FAIR TRADE` / `NOT FAIR` / `UNABLE TO DETERMINE` |

It never says accept / decline / approve / deny, and never publishes a value,
gap, band level, percentage, the private 5-level category, the YES/NO headline
or any Team Context inference. Every team's result ships in ONE response; the
perspective only selects the default view (privacy M6).

**How it is computed — no business logic in the public layer.**

1. Snapshot + ledger: `src/trade/trade_ledger.py` (`snapshot_for`,
   `validate_ledger` under the public policy `send_and_receive`). The same
   snapshot memo serves the private `/api/trade/analyze-multi` route.
2. Engine: `analyze_service.analyze_trade_n(mode="market_fairness",
   counterfactuals=False)` — Team Context off, no posture, no roster capacity,
   nothing written (no decision receipt, no progress, no caches).
3. Per-team fairness: `team_verdicts.team_fairness` — the asset evidence gates
   (`trade_decision.asset_evidence_gaps`), then the band `fairness_bands_v1`
   classified for that team's OWN adjusted package totals under the active
   `geom_q078_v1` model. FAIR iff the band is `fair` (SD-1 / OD-F1 default).
4. Reduction: `public_advisor.reduce_fairness` sees only, per team,
   `(rosterId, state, reasonCode, unavailable ids)`, the engine's overall state
   (cross-checked) and the canonical legs.
5. Enforcement: Pydantic outbound models (`extra="forbid"`, Literal enums, no
   float type) + `public_contract.assert_public_payload_safe` +
   `public_advisor.assert_advisor_payload_value_free` (int-key allowlist, no
   floats, advisor key blocklist, fixed copy only) on every body.

**What changed from Part II.**

| Part II item | now |
|---|---|
| §2.9 B1 `multi_side.py` (a JS transcription, built-but-off) | **Dropped** (SD-10). Multi-team is the shared Python N-team engine. |
| §2.10 B2 adapter (`_engine_analyze`, `_engine_resolve`, `_player_row_for`, `validate_trade`, private `roster_freshness`) | **Deleted.** Ledger + engine owners above; the ONE roster-freshness reader is `src/api/roster_freshness.py`. |
| §3 category mapping in the PUBLIC path | **Removed from the public path.** The 5-level category is private only (`team_verdicts.team_category`); the PUBLIC section of `trade_decision.py` (public categories, ACCEPT/DECLINE copy, net-band mapping, public reason codes) is deleted. |
| §4 contract (category / recommendation / headline; `value_desc` / `value_asc` / `alpha`; `multiTeam`; `multi_team_unsupported`, `roster_limit`) | **Replaced** by spec §4: `overall` + `teams[]` + `trade[]`, `fairnessVersion`, `snapshotChanged`; one asset order `position_alpha` (side → position → label → id; picks by season / round / origin) — never value-ordered (privacy M2, SD-8); `multiTeam`, the value sorts and both retired reasons are gone. |
| §0 "Players are value-sorted on the server" | **Superseded** (privacy M2). |
| §2.11 response floor on success only | The floor applies in `finally` to every analyze outcome after the limiter charge (200 / 400 / 409 / 413 / 415 / 429 / 503); the limiter is charged before the body is read; a per-`teamCount` floor table is accepted. |
| §2.11 launch gate = floor only | Launch gate (spec §6.3): flag + measured `responseFloorMs` + `approvedFairnessVersion` equal to the band receipt and not PROVISIONAL + `approvedSourcePermissionRecord` naming an existing file + geom package model. Every route answers 503 `advisor_unavailable` / `not_ready` until all hold. |
| GET caching `public, max-age=60` | Every response `no-store` (spec §4). |
| Errors | Ledger reason codes and fixed copy (spec §4.4 / §4.5); `unknown_team` in a trade body is now `team_not_in_league`; the 409 never names the actual owner. |

**Owner decisions.**

- **OD-1 — RESOLVED (2026-10-20): YES**, genuine multi-team evaluation, now
  fairness-only for the public product. Implemented for 2-4 teams; the public
  ceiling is `limits.maxTeams` (config), capped at the league's team count.
- **OD-F1..OD-F6 (fairness threshold) — OPEN, BLOCKING LAUNCH.** The band is
  used unchanged (`fairness_bands_v1`, PROVISIONAL); the launch gate refuses
  until the owner approves a non-provisional version.
- **OD-3 (source permission) — OPEN, BLOCKING LAUNCH**, recorded through
  `approvedSourcePermissionRecord`.
- **OD-4 (posture exposure) — MOOT for the public path**: posture is not an
  input of the public answer (Team Context off; pinned by an invariance test).
- **OD-8** — extend to the public `send_and_receive` rule (a "many to one"
  shape where a team only receives is refused publicly — an availability
  difference excluded from parity, not a different conclusion).
- The response floor is still unmeasured (`responseFloorMs: null`); measure it
  locally from the `market_fairness` worst-case p99, never against production.

**Rollback.** `RISKIT_FEATURE_BRISKET_TRADE_ADVISOR=0` (the default) + restart
disables only the public tool; the private calculator, the private multi-team
route and valuation are untouched.

---

# Part I — Architecture audit (Deliverable 1, final revision)

**Checkout audited:** `main` at `9668165298` (detached, clean, read-only worktree).

**Directive:** read in full (committed verbatim as `docs/owner/BRISKET_TRADE_ADVISOR_2026-10-19.md`).

**How claims are labelled:**
- **[verified]**: I re-read the file:line in the checkout during this revision.
- **(audit)**: taken from the original eight audit reports.
- **(critique)**: taken from the three adversarial reviews (parity, privacy, completeness), with the file:line they cite. The critiques' measurements were run on the 2026-10-19 archive board. I did not re-run them.
- **[inferred]**: my own reasoning, not executed.

---

## A1. Where the private trade calculator runs: split between browser and server

`/trade` shows **two separate verdicts**, and they are computed in different places.

| Piece | Runs | Owner (file:line) |
|---|---|---|
| Canonical per-asset value `rankDerivedValue` | server | `src/api/data_contract.py::_compute_unified_rankings` |
| Row materialisation `values.full = Math.round(rankDerivedValue…)` | browser | `frontend/lib/dynasty-data.js:1179` (audit) |
| Owned-pick label → board row for the meter | browser | `trade-logic.js::resolvePickRow` 1453-1495, with an "assume Mid" fallback at 1195-1205 (audit; critique measured that it disagrees with the server for all 18 overlay-grammar labels) |
| Package Value Adjustment (VA): 2 sides and N sides | browser | `trade-logic.js` 654-671, 735-759, 887-897 |
| **"Immediate result" meter** | browser | `fairness-bands.js:20-25`, `trade-logic.js:2021-2024`, `TradeMeter.jsx` |
| 3+-team routing, net flows, imbalance | **browser only** | `trade-logic.js` 1898-1962, 1985-2009, 2077-2091 |
| **"Final decision" War Room**, 2 teams only | server, session required | `server.py:17819` → `_build_trade_simulation` 17558 [verified] → `simulate_trade` → `analyze_trade` 907 [verified] → `trade_decision.decide` |
| War Room readiness | browser | analyses only when **both** sides are non-empty: `ready` at `TradeWarRoom.jsx:663-667` [verified] |
| Owned-pick ownership check | server only | `trade_simulator._classify_owned_picks` 111-225 |

**Route orchestration** [verified]. `_build_trade_simulation` (`server.py:17558-17752`) does all of this inline:
- auth (401 at 17571-17573);
- body parsing;
- league resolution;
- a cross-league overlay splice (17605-17646);
- `_valuation_scoped_contract` (17650-17652);
- `resolve_team` (17663-17677);
- `team_context_requested` (17686-17688);
- `_picks_with_ids` (17694-17716);
- `simulate_trade`, with posture `build_if_missing=for_analysis and use_team_context` (17718-17743);
- the `teamContext` stamp (17744-17748);
- `nflExposure` (17752-17757).

The analyze route then:
- re-reads the body for `teamGoal`;
- reads **the global** `latest_contract_data` again for `provenance` (17867-17880). That is a second read, not the captured contract;
- writes `record_decision` (17883-17890).

## A2. Valuation services

**Players.**
- The value is `rankDerivedValue`, served from `latest_contract_data`. A publish swaps whole object references (`server.py:3077-3090`). `latest_data_etag` is assigned after the contract.
- The server reads a row's value as `int(_row_value(row))` (`trade_simulator.py:319`). `_row_value` tries `rankDerivedValue`, then `values.full`, then a Hill-from-rank fallback (`terminal.py:141-168`).
- `terminal._players_array` returns shallow copies (`{**r, "_sleeperId": sid}`) for rows it enriches (`terminal.py:213` [verified]). Object identity therefore does not survive indexing. The critique measured 958 of 1,130 rows copied.

**Picks. Two label grammars reach one resolver** [verified]:
- **Baked** (scraper, `latest_contract_data`): `format_pick_label_baked` gives `"2028 Mid 1st"` for future classes. It uses `legacy_slot_tier_label`, whose own docstring calls the "Mid" "the legacy DISPLAY fabrication… the canonical answer for an unknown slot is `market_resolution`'s `unknown_slot` basis" (`src/identity/picks.py:751-780`).
- **Overlay**: `format_pick_label_overlay` gives `"2028 1st"` (`picks.py:783-790`). The overlay always stamps `"slot": None` (`src/api/sleeper_overlay.py:420-430`).
- `trade_simulator._resolve_asset` treats a parsed tier as **proven** and looks up that tier row before `market_resolution` (`trade_simulator.py:264-285` [verified]).
- **Consequence:** one owned 2028 1st prices at `<value A>` from the baked label and a higher `<value B>` from the overlay label. "2027 1st" (overlay) resolves to **None**, because "2027 Round 1" is not a board row and the ladder never calls `resolve_pick_value` (critique table).
- Inside one simulation, the before-roster picks come from baked labels (`trade_simulator.py:557-566` [verified]) while the traded legs come from the browser's label. Before/after and equity can therefore price the same 1st differently.
- The canonical single resolver is `resolve_pick_value(contract, ref, *, rows_by_name=None)` (`pick_value_resolution.py:119-124` [verified]). For the current year, a generic grade gets the centre-slot convention (166-172).

**Source weighting, freshness, family cap, IDP and TE basis** live entirely inside `_compute_unified_rankings`. The advisor inherits them by reading the contract.

**Package VA.**
- Python reads `config/trade/package_model.json` (`geom_q078_v1`). On an unreadable or unknown config it **falls back to KTC**: `DEFAULT_ACTIVE = KTC_2026_04` (`package_model.py:66-80` [verified]). The docstring rationale ("never silently promote a challenger") dates from when KTC was the incumbent.
- JavaScript hard-codes geom (`trade-logic.js:628`).
- Floating point (critique):
  - `0.78**i` differs between V8 and CPython from i = 4 onward.
  - CPython 3.12's `sum()` is compensated; JavaScript uses a plain `reduce`.
  - Rounded VA still agreed 200,000 of 200,000 times.

**Fairness bands.** `fairness_bands_v1`, PROVISIONAL. Python owns it, and the JavaScript copy is pinned to it.

**Team Context reads inputs from outside the contract** (critique, `trade_simulator.py:404-440`; `roster_capacity.py:1012-1027`):
- the posture bundle (a cold build is possible);
- league-scored projections;
- the availability context;
- Monte-Carlo roster utility (`trade_simulator.py:839-866`).

## A3. Trade evaluation methods

**Two sides (server).**
- `equity_verdict` (`analyze_trade.py:160-192`) is the Python twin of the meter's band.
- `decide`:
  - runs the execution gate, then the evidence gates (12 codes, `trade_decision.py:269-395`, critique);
  - computes component A with `_objective_value` [verified 406-442]. It returns `direction` (favors/opposes/neutral), `magnitude` (modest/large) and `band`, all computed on `net = vaAdjustedGap − forcedReleaseCost`;
  - computes component B, the roster lens;
  - applies `_rule`, then `_confidence`.
- `leaning` is computed before the gates and is always returned.
- On every path past the gates, `decide` **always** runs `_what_would_change` (`trade_decision.py:1384` [verified]). That is a linear search `for v in range(_FLIP_STEP, _FLIP_MAX+1, _FLIP_STEP)` that breaks at the first flip (774-798 [verified]). Its run time therefore encodes the size of the gap. Measured locally (critique): 0.05 ms to 29 ms.
- Its prose embeds numbers: "an asset worth about {v:,}".

**N sides (browser only).**
- `computeMultiSideAdjustments` (735-759) is a "structural extension … NOT a separately fit formula" (727-728).
- `computeSideFlows` (1898-1962) silently routes a bad destination to the next side.
- The 3+-team meter shows Even / Getting value / Losing value per side, plus an overall worst-net band (`TradeMeter.jsx:208-226`).
- No Python version exists.

## A4. Verdict band sets

| Set | Owner | Live use |
|---|---|---|
| `fairness_bands_v1` fair/slight/unfair/lopsided (absolute floor 250; 3.5 / 9 / 18%) | `fairness_bands.py` + JSON; JS mirror | meter, market lens, component A |
| legacy magnitude even/lean/stretch | `fairness_bands.legacy_magnitude` | `leaning` "strong" |
| `_objective_value.magnitude` modest/large (large ⟺ unfair/lopsided) | `trade_decision.py:426-430` [verified] | component A |
| Decision headline YES/NO/NO_TOO_CLOSE/NOT_ENOUGH_EVIDENCE | `trade_decision.HEADLINE_TEXT` 54-59 | War Room |
| Graded leaning MAKE…PASS | `trade_decision.leaning` 103-149 | War Room |
| Confidence axes (weakest axis wins) | `_confidence` 633-716 | War Room |
| 3+-team per-side tag | `TradeMeter.jsx:208-226` | `/trade` |
| Trade-history letter grades | `src/public_league/trade_grading.py:61-89` (audit) | public history |
| Generation gates (769, −175, 350, 250) | suggestions / finder / best_offers (audit) | not verdicts; must not be mapped |

D8 forbids reopening the fairness classifications or the YES/NO engine (`docs/EXECUTION_PLAN.md:87-88`, audit).

## A5. League Hub routing

**Entry points.**
- **No "GO TO LEAGUE HUB" control exists.** The signed-out landing button reads "League" (`frontend/app/page.jsx:103-117`). Signed-in visitors get `TerminalLayout` at `/` and never see that button (critique, `page.jsx:18-20, 173`).
- Navigation "League → Hub" is at `nav-model.js:264-270, 422-426`.
- **Eight** bare `/league` back-links exist, not six (critique F4). Two of them are error-state "← Back to league" links.

**Tab model** (`frontend/app/league/tabs.js`):
- `SUB_TABS` 18-48;
- `DEFAULT_TAB = "overview"` 51;
- aliases 62-66;
- `leagueTabHref` 73-91;
- unknown tab falls back through `sectionForTab` (131-135).

**URL parameters owned by sections** [verified]:
- `owner` is shared by the franchise **and** draft tabs;
- `week` belongs to weekly;
- the draft-capital year param belongs to draft capital (`LeagueClient.jsx:163-168`).

All section selectors route through `setActiveTab(tab, {param})`.

**`LeagueClient.jsx` behaviour:**
- Tab switches use `router.replace` (206, 223-226), so Back and Forward never move between tabs.
- A missing `tab` in the URL is ignored (196-200). This is inferred from the code.
- Three hard early returns blank the whole hub (358-372).
- Sections other than Overview are `next/dynamic` with `ssr:false`.
- OverviewSection is "deliberately NOT split — it is DEFAULT_TAB, so splitting it would trade a bundle win for a loading flash on the landing view" (`LeagueClient.jsx:74-76` [verified]).

**Public access and budget.**
- Public by prefix: `PUBLIC_PREFIXES = ["/league"]` (audit).
- Budget: `/league/page` is 50 KB, explicitly tightened so that a static section import trips CI (`frontend/scripts/check-bundle-sizes.mjs:118-128` [verified]). The last measurement was 45.1 KB (audit).
- The budget script gates **page** chunks only, not lazy chunks [verified].

**Existing public trade tooling and projections.**
- The public hub **already has** a pick-dollar "Trade Simulator" on Draft Capital (`sections/_trade-simulator.jsx`, mounted at `sections/draft-capital.jsx:50, 381` [verified]). It is a pick-dollar sum.
- Draft Capital **already publishes** projected slots publicly: `"slotStatus": "projected"` (`server.py:13183-13188` [verified]; `SLOT_PROJECTED` at `src/api/draft_capital_classes.py:133` [verified]).
- The rookie-order owner is `src/public_league/draft_order.py`, and draft-capital ordering is in `src/api/draft_capital_order.py` (both exist [verified]).

## A6. Roster and pick data

| Producer | Freshness | Read by |
|---|---|---|
| Baked `sleeper.teams` in `latest_contract_data` | about 2 h. On a Sleeper outage it is restored from the last-good snapshot. The scraper knows `_cache_age_h` and does not stamp success, but **nothing in the contract** says the data was restored (`Dynasty Scraper.py:1624-1640` [verified]) | `/api/trade/simulate`, `/analyze`, `/finder` (dynasty_main) |
| Live overlay | 15 min | the private `/api/data` splice; Pick Projector |
| Public snapshot | 300 s SWR | `/api/public/league/*` |
| `/api/draft-capital` workbook | own fetch | public Draft Capital, including projected slots |

**What the baked block contains:**
- 12 teams, each with `name`, `ownerId`, `roster_id`, `playerIds` (complete), `players` (names; roster 6 has 57 names for 58 IDs, and the missing one is Alim McNeill, critique), `pickDetails` (baked grammar, `slot` null today), `pickOwnershipState` and `sleeperTeamName`.
- Raw defensive tokens for rostered players: DT 21, CB 20, DE 16, **S 0**. The rest are family-level.

**The private engine keys identity by display name:**
- `terminal._build_row_index` (263-269).
- `simulate_trade` builds the before-roster from `team["players"]` (`trade_simulator.py:521` [verified]).
- `roster_capacity` counts names (critique, `roster_capacity.py:468`).
- Byron Murphy CB (ID 5864) has **no** board row. Sent by name, the War Room prices him as the DL 11668 row (that row's `<value>`).

## A7. Auth, rate limits, caching, logging

**Auth.**
- One gate, `_private_api_gate` (`server.py:4286-4337`). Every path under `/api/public/league/` is public by prefix.
- Dot-segment bypasses were probed and return 404 (critique).

**Client IP** [verified, `server.py:4394-4421`]:
- `X-Real-IP` is trusted from **any** peer.
- The fallback is the last `X-Forwarded-For` entry, then `request.client.host`.
- The backend binds `0.0.0.0` (`server.py:113`).
- `next start -p 3000` binds every interface (critique).
- No firewall rules exist in `deploy/` (critique).

**Keyed limiter** [verified, `src/api/rate_limit.py:150-200`]:
- A single shared `_keyed_buckets` store capped at `_MAX_TRACKED_KEYS = 5000`. On overflow the oldest 10% are evicted.
- Also used by screenshot OCR and Manager Intelligence (critique).
- Test seam: `_keyed_now`.

**Bodies and errors.**
- Request size is checked from the declared Content-Length only (`server.py:4163-4183`). nginx allows 25 MB.
- Starlette's `request.body()` buffers the whole body (critique).
- No `RequestValidationError` override exists, so typed path or query parameters produce FastAPI's default 422 body (critique).
- The global error handler logs the full traceback (`src/api/error_responses.py:122-145`, critique).
- `deploy/deploy.sh:968` prints 120 journal lines when a restart fails. That output lands in public GitHub Actions logs (critique).

**Caching.**
- Public league routes: `public, max-age=60, stale-while-revalidate=300`.
- nginx caches only `/_next/static`. No CORS middleware.
- The service worker caches public-league GETs in `PUBLIC_LEAGUE_CACHE` and skips POSTs.
- Pre-existing: it also stores private GET responses at rest (`sw.js:157, 176-183`; `NEVER_CACHE` omits `/api/terminal`, `/api/bdvm/*`, `/api/ros/*`) (critique).

## A8. Defects and divergences that affect the advisor

1. **Owned picks have two values inside the server engine**, depending on label grammar (§A2), plus a third value in the browser meter ("assume Mid"). "2027 1st" is None on the server.
   - [inferred] The War Room is non-deterministic today: it depends on whether the browser received the overlay block or the baked one.
2. **Name-keyed player identity.** Affects the leg resolution, the before-roster (from `players`, not `playerIds`) and capacity counts.
3. **52 of 696 rostered players are unpriced**, including all kickers (audit).
4. **No server-side N-team engine.**
5. **`/trade` enforces no ownership, allows unlimited copies, and allows up to 5 sides.** `SHARE_MAX_LINES_PER_SIDE = 32` is "untrusted URL INPUT only … not calculator quantity caps (owner decision 2026-10-03)" (`frontend/lib/trade-share.js:60-71` [verified]).
6. **The public blocklist matches whole key names only** (`public_contract.py:421-441`). It lacks `value`, `gap`, `band`, `confidence`, `decision`, `whatWouldChange` and similar keys (critique).
7. **The boundary and permission records conflict with the directive:**
   - `docs/MASTER_PRODUCT_PLAN.md:602`;
   - Signals "authenticated Calculator displays" only (`docs/sources/SIGNALS_FANTASY_INTEGRATION.md:33-35`);
   - decision 10 / D10: "no fabricated 3+-team YES/NO" (`docs/EXECUTION_PLAN.md:80`; `docs/trade/TRADE_CALCULATOR_COMPLETION_WORKSTREAM.md:609-614`).
8. **Inputs the private meter honours and the War Room ignores:**
   - per-line `customValue`;
   - user `siteWeights`, which re-weight through `/api/rankings/overrides`;
   - the TE slider (critique, audit).
9. **Python silently falls back to the KTC package model** on a bad config (§A2).
10. **The counterfactual search is a timing side channel**, and its prose embeds numbers (§A3).

## A9. Reuse and how the public interface reaches the engine

**Reuse:**
- `simulate_trade`, `analyze_trade` and `decide`, through one extracted service (B0-c);
- `package_model`, `fairness_bands` and `resolve_pick_value`;
- `parse_league_pick_id`, `league_pick_owner_index`, `lookup_league_pick_owner`, `market_resolution`, `round_suffix` and `slot_tier`;
- `normalize_position`;
- `_public_league_key_error` and `_public_unavailable_body`;
- the rate-limit refill arithmetic;
- the `configure_host` router pattern;
- the explicit-allowlist precedent;
- the ds primitives;
- the existing ARIA combobox pattern (`frontend/app/trade/trade-sections.jsx:750-765` [verified]).

**How the public interface reaches the engine:**
1. The public browser sends only league, team and asset identifiers.
2. The server captures **one** `latest_contract_data` object and validates ownership against it.
3. It calls **the same service function** the War Room route calls.
4. It returns an outbound-model-validated enum and fixed text.

No value, rank, gap, band, counterfactual or confidence leaves the server.

---


# Part II — Implementation design (final)

## 0. Decisions this design makes

| Topic | Decision | Why |
|---|---|---|
| Private reference | **The War Room** ("Final decision", Team Context on) is the private reference for 2 teams, not the meter. For 3–4 teams the only private evaluation is the 3+-team meter. | They already differ on release cost and overrides (§A8). One reference must be named. |
| 2-team evaluation | A new shared service `src/trade/analyze_service.py`, called by `/api/trade/analyze`, `/api/trade/simulate` and the advisor. Team Context on, no comparables, no decision log, `counterfactuals=False`. | One owner of "how a 2-team trade becomes an analysis", so route changes propagate automatically. Counterfactuals are computed after the headline, leaning and confidence (`trade_decision.py:1355-1384`), so skipping them cannot change a category. |
| Engine repairs | Fix the shared owners, not just the public path:<br>• pick pricing by identity through `resolve_pick_value` (B0-a);<br>• player identity by Sleeper ID, roster built from `playerIds` (B0-b);<br>• `/trade` reads a server-stamped pick row (B0-g/F0). | "Repair the owner; a page-local workaround becomes a second owner" (CLAUDE.md). It also makes the War Room deterministic. |
| 3–4-team evaluation | `src/valuation_math/multi_side.py` (a Python twin pinned to JS by a fixture that CI regenerates) is **built but switched off**: `multiTeamRecommendations: false` returns UNAVAILABLE `multi_team_unsupported`. Turning it on needs:<br>• OD-1 (decision 10 superseded for this surface);<br>• OD-5 (twin accepted);<br>• the end-to-end parity fixture against the real meter (T-A4) green. | Decision 10 and D10 are still recorded. The directive's own "return an unavailable result" clause (:667) and "do not improvise methodology" make OFF the safe default. |
| Category mapping | Lives in `trade_decision.py`. Uses no new thresholds. "Strong" = the value band is unfair or lopsided in the matching direction, at every N (§3). | One module emits recommendations, and "strong" means the same thing across team counts. |
| Snapshot | One captured `latest_contract_data` per request. Team Context inputs are read live at evaluation time. **No caching of analyze results.** | Coherent contract, fresh Team Context, no cross-user timing channel. |
| Identity | `p:<sleeperId>`, `pick:<leagueKey>:<season>:r<N>:o<rid>`, `rosterId` | Already public and carry no values. |
| Ordering | Players are value-sorted on the server. **Picks always sit in their own segment, ordered by (season, round, origin label), never by value.** `value_asc` is the exact reverse of the priced part of `value_desc`. | Prevents cross-team landmarks and tie leaks. Criterion D says "**Players** can be sorted by internal value". |
| Abuse controls | A dedicated limiter instance with:<br>• per-key and neighbourhood buckets;<br>• a global ceiling;<br>• a streamed 16 KiB body cap;<br>• a constant response floor;<br>• proxy headers trusted only from trusted peers. | Closes the timing, eviction and forgery channels. |
| Payload bound | At most 4 teams, at most 128 legs in total. Declared as a **new payload-safety bound**, not an existing rule and not a per-team quantity cap. | `SHARE_MAX_LINES_PER_SIDE` is explicitly not a quantity cap (`trade-share.js:60-71`). Ownership already bounds what a team can send. |
| Hub | New tab `trade-advisor` = `DEFAULT_TAB`. Its team step is in the page chunk and server-rendered. Overview becomes a lazy section. | Keeps the no-loading-flash rationale (`LeagueClient.jsx:74-76`) for the new landing. |

---

## 1. Units, owners and order of work

| Unit | Owner | Depends on | Changes a live private result? |
|---|---|---|---|
| R0 records and claims | either | — | no |
| B0-a pick pricing by identity / single resolver | backend | — | **yes**: War Room owned-2027 picks (None → value); baked-label owned 2028+ picks (`<value A>` → `<value B>`) |
| B0-b player identity by ID; roster from `playerIds` | backend | — | **yes**: name-collision and name-missing rosters |
| B0-c `analyze_service` extraction | backend | B0-a, B0-b | no (pinned) |
| B0-d decision helpers: `counterfactuals` kwarg, public mapping, evidence helpers | backend | — | no |
| B0-e package-model `config_state` + left-fold/iterative-power hardening in both languages | backend + JS | — | ULP only (rounded VA unchanged; fixture regenerated) |
| B0-f roster freshness evidence | backend | — | no |
| B0-g canonical `boardRowName` stamp on every `pickDetails` entry | backend | B0-a | no (additive field) |
| B0-h client-IP hardening + `KeyedLimiter` instances | backend | — | no in production (nginx peer is loopback) |
| F0 `/trade` follow-through: War Room sends player IDs; `resolvePickRow` reads `boardRowName`; "assume Mid" deleted | frontend | B0-b, B0-g | **yes**: `/trade` meter owned 2028+ picks `<value A>` → `<value B>` |
| B1 `multi_side.py` + CI-regenerated parity fixture | backend + JS script | B0-e | no |
| B2 `src/trade/public_advisor.py` | backend | B0-a…d, B0-f | — |
| B3 `src/api/public_trade_advisor_api.py`, flag, config | backend | B2, B0-h | — |
| F1 hub routing | frontend | §4 contract | hub-wide (named) |
| F2 advisor UI | frontend | §4 + fixtures | — |
| T tests and E2E; S security pass; P performance; D deploy and verify; Deliverable 10 report | both | all | — |

**Coordination.**
- §4 is the frozen contract. The backend commits `frontend/__tests__/fixtures/trade-advisor/*.json`: success and error examples per endpoint, including the `rosters.state: "stale"` variant. Backend tests assert real responses against those exact key sets. Frontend tests and route mocks consume them.
- F0 touches `trade-logic.js` and `trade-war-room.js`. Before starting it, check `docs/WORK_CLAIMS.md` and live PRs for the trade-calculator rework (CLAUDE.md names `app/trade/page.jsx` and `lib/trade-assets.js` as held by it). If those files are claimed, F0 waits, and so does the multi-team switch. The 2-team advisor does not depend on F0.

---

## 2. Backend

### 2.1 B0-a: owned picks priced by identity through one resolver (`src/api/trade_simulator.py`)

1. **Replace the pick branch of `_resolve_asset`** (264-285) with one canonical path:
   - `parse_pick_label`;
   - then `resolve_pick_value(contract, parsed.market_ref, rows_by_name=…)`;
   - if no value, `market_resolution(year, round, slot, current_rookie_draft_year()).ref`, then `resolve_pick_value`;
   - take the row via `row_index[res.basis_row_name.lower()]`.

   The critique measured this over all 282 board, overlay and baked labels: the same row in 276 cases, with the 6 differences exactly the "2027 1st…6th" defect. So it is behaviour-preserving except for the fix, and it retires the simulator's private ladder.

2. **Identity first.** Add `_resolve_owned_pick(asset_id, *, contract, rows_by_name, row_index)`:
   - `parse_league_pick_id`;
   - the slot from that contract's `pickDetails[assetId].slot`;
   - `market_resolution(year, round, slot, current_rookie_draft_year())`;
   - `resolve_pick_value`.

   `simulate_trade` uses it whenever a leg or roster pick carries a proven `assetId`:
   - traded legs after `_attach_ids` (~600);
   - roster entries from `_roster_pick_entries` (557-566).

   Labels are then a fallback for picks with no ID, so the War Room no longer depends on which block the browser had.

3. **Public wrappers**, so the adapter calls no private functions:
   - `asset_row_index(contract)`;
   - `pick_rows_by_name(contract)` (made public in `pick_value_resolution`);
   - `resolve_trade_asset(label, *, asset_id=None, player_id=None, contract, row_index, pick_rows_by_name)`;
   - `row_name(row)`;
   - `row_player_id(row)`: `str(row.get("playerId") or row.get("_sleeperId") or "")`.

4. **Before merge:**
   - Confirm the production defect: one authenticated `/api/trade/analyze` sending an owned 2027 pick should return `missingEvidence[0].code == "off_board_assets"`.
   - Run `scripts/board_diff.py --expect-no-value-change`. Board values are untouched.
   - Record a before/after census on the trade surfaces: every `pickDetails` label in both grammars, old row vs new row.

### 2.2 B0-b: player identity by Sleeper ID (`simulate_trade`)

- **New optional parallel arrays** `player_ids_in` / `player_ids_out`, mirroring `pick_asset_ids_*`.
  - An entry with an ID resolves through `rows_by_player_id` (built from the **same** `_players_array` list as `row_index`).
  - No row for the ID means unresolved. It is never sent to the name index.
  - Entries without an ID keep today's name lookup.
- **Before-roster** is built from `team["playerIds"]` when present, joined to rows by ID. A player with no row is listed as unpriced and still occupies a roster spot (same rule as roster capacity). It falls back to `team["players"]` only when `playerIds` is absent.
- [inferred, verify before coding] `simulate_trade` hands its roster list to `roster_capacity`. Change only the list `simulate_trade` builds, not `roster_capacity`'s counting rule. Pin that finder, suggestions and angle outputs are unchanged on the archive board.
- **Effect:**
  - Byron Murphy CB (no row) → unresolved → `off_board_assets` on both surfaces once F0 sends IDs.
  - Roster 6 counts 58 spots.
  - Pinned by `tests/api/test_trade_simulator_player_ids.py`.

### 2.3 B0-c: one 2-team analysis owner (`src/trade/analyze_service.py`)

```python
def simulate_for_team(contract, *, league_key: str, roster_settings: Mapping, resolved_team: Mapping,
                      players_in, players_out, player_ids_in, player_ids_out,
                      picks_in, picks_out, pick_ids_in, pick_ids_out,
                      team_context: bool, for_analysis: bool,
                      posture_resolver: Callable[..., Mapping | None]) -> dict
def analyze_for_team(simulation: dict, *, contract, team_goal=None, comparables=None,
                     counterfactuals: bool = True) -> dict
```

**What the service owns** (moved out of `server.py:17650-17748`):
- the valuation-scope step, through a pure `src/trade/valuation_scope.py::scoped_contract(contract, requested_mode)`. `server._valuation_scoped_contract` delegates to it, so `tests/api/test_canonical_value_invariance.py` still pins one seam;
- the `simulate_trade` call;
- the posture resolution rule `build_if_missing = for_analysis and team_context`;
- the `teamContext` stamp;
- the `analyze_trade` call, with `provenance` read from **the passed contract**. This removes the second global read at 17875.

**What the route keeps:** auth, body parsing, league resolution and the overlay splice, `resolve_team`, `nflExposure`, comparables and `record_decision`.

**Pinning:** an AST test in the style of `tests/trade/test_finder_va_is_not_bypassable.py` asserts:
- `/api/trade/analyze`, `/api/trade/simulate` and `public_advisor` call the service;
- no other module calls `simulate_trade` and `analyze_trade` together.

### 2.4 B0-d: decision-owner helpers (`src/trade/trade_decision.py`, `analyze_trade.py`)

- `decide(..., counterfactuals: bool = True)` and `analyze_trade(..., counterfactuals: bool = True)`. When False, `whatWouldChange = []`. This is a performance win and closes the timing channel.
- **Public mapping**, owned here:

  ```python
  PUBLIC_CATEGORIES = ("STRONGLY_FAVORABLE","FAVORABLE","APPROXIMATELY_EVEN",
                       "UNFAVORABLE","STRONGLY_UNFAVORABLE","UNAVAILABLE")
  PUBLIC_CATEGORY_TEXT: Mapping[str, Mapping[str, str]]   # recommendation/headline/message, §3
  PUBLIC_REASON_TEXT: Mapping[str, str]                   # §3
  def asset_is_priced(asset) -> bool
  def asset_evidence_codes(asset) -> tuple[str, ...]
  def public_category_from_decision(decision) -> str
  def public_category_from_net_band(band, net) -> str
  def public_reason_code(decision) -> str | None          # unknown future codes -> None (fail closed)
  ```

- Refactor `_evidence_gaps`' quarantined and stale lists, and `_market_lens._priced`, to use these helpers. Behaviour is pinned by the existing `tests/trade/test_trade_decision*.py`.

### 2.5 B0-e: package-model safety and float determinism

**`package_model.config_state() -> Literal["ok","unreadable","unknown_active"]`** reports what `_config()` actually saw.
- The advisor returns UNAVAILABLE (generic copy) unless the state is `"ok"` **and** the active model is `geom_q078_v1`, i.e. equal to JavaScript's `ACTIVE_PACKAGE_MODEL_ID`.
- An error is logged.
- The War Room's KTC fallback is left alone. Changing it is a decision-engine behaviour change; it is a named DEFERRED follow-up.

**Hardening in both owners:**
- `geom_utility` (`package_model.py:120`) and `trade-logic.js:646` both compute weights iteratively (`w *= q`) and sum with an explicit left fold. No `sum()`, no `**`, no `Math.pow`.
- Regenerate `tests/fixtures/package_model_parity_cases.json`.
- The rounded VA must be unchanged on the existing fixtures plus 200,000 random pairs (the critique's harness).

### 2.6 B0-f: roster freshness evidence

The advisor must say how fresh its rosters are.

1. **Preferred, no scraper change:** read the Sleeper source's existing last-success stamp, the one the watchdog reads (`scripts/watchdog_freshness`; the scraper "does NOT stamp success" on a restore, `Dynasty Scraper.py:1629-1631`). [inferred: verify which `data/scrape_state/` file carries it.]
2. **If that stamp cannot be tied to the contract**, add to the scraper's restore branch:
   - `sleeper.rosterSource = "last_good"`;
   - `sleeper.rosterSnapshotAgeHours = _cache_age_h` (otherwise `"live"`).

   `Dynasty Scraper.py` is high risk: L2 runs both suites.

Rule: `rosters.state = "current"` when live and ≤ 6 h (`SCORING_SNAPSHOT_MAX_AGE_HOURS`, the existing scrape-cadence rule); `"stale"` otherwise; `"unknown"` when unprovable. Only the date is exposed.

### 2.7 B0-g: canonical pick row on every `pickDetails` entry

Add `pick_value_resolution.stamp_owned_pick_rows(sleeper_block, rows_by_name, current_draft_year)`.
- It adds `boardRowName` (the `basis_row_name` from the B0-a identity path) to every `pickDetails` entry.
- It is called where the baked contract is built (`data_contract`) and where the overlay block is merged into `/api/data` (`server.py:4795-4874`).
- `boardRowName` names a board row; it carries no number.

### 2.8 B0-h: client identity and limiter isolation

**`_client_ip_from_request`:**
- Trust `X-Real-IP` / last-XFF only when `request.client.host` is loopback or listed in `RATE_LIMIT_TRUSTED_PROXIES`.
- Parse with `ipaddress`. On failure use the TCP peer, never raw header text.
- Map IPv4-mapped IPv6 to IPv4.
- Tests that set `X-Real-IP` through TestClient (peer `"testclient"`) set the environment variable. Audit them with a grep before merge.

**`rate_limit.KeyedLimiter(name, max_keys)`:**
- Each instance has its own store and lock, and uses the same `_refilled` arithmetic.
- `ceiling=True` buckets are never evicted.
- The advisor uses its own instance, so screenshot-OCR and Manager-Intelligence buckets are untouched.
- `reset_for_tests()` resets all instances.

**Ops (unit D, separate PR, verified on the box):**
- bind uvicorn to `127.0.0.1` through an env default;
- `next start -H 127.0.0.1`;
- confirm `:8000` / `:3000` / `/openapi.json` are not reachable from the internet.

### 2.9 B1: `src/valuation_math/multi_side.py` (built, switched off)

> **DROPPED (Part 0, SD-10).**

```python
@dataclass(frozen=True)
class SideFlow: given: float; received: float; net: float; adjustment: float
def multi_side_adjustments(sides, *, model_id=None) -> list[int]
def side_flows(sides, destinations, *, model_id=None) -> list[SideFlow]
def net_summary(flows) -> dict          # nets, largerSide, worst, overall band
def side_band(flows, index) -> dict     # fairness_bands.classify(flows[i].net, largerSide)
```

**Semantics** are a line-for-line transcription of `trade-logic.js:248-252, 735-759, 1898-1962, 2077-2091`, using the B0-e folds.
- **Deliberate difference:** a missing, out-of-range or self destination raises `ValueError`, where the JavaScript silently re-routes.
- **Order:** teams are evaluated in the **request's** order, and legs in request order within each origin. Accumulation order affects only ULPs. Documented.

**Parity:**
- `frontend/scripts/generate-multi-side-parity-cases.mjs` runs **in CI** inside the Python test job, through Node. `tests/valuation_math/test_multi_side_parity.py` compares Python with the fresh JavaScript output, so no committed expectation can be hand-edited. A JavaScript change without the matching Python change fails CI in the same PR.
- A committed snapshot remains for review diffs.
- Comparison is per field: exact `==` on adjustments and levels, `float.hex` equality on flows. **Not** `json.dumps`, because integral floats print differently in the two languages (critique F5).
- The N = 2 reduction against `vaAdjustedGap` uses a tolerance of 1e-6, matching `trade-package-equity-parity.test.js:67`.
- Single-owner fingerprint guard in `tests/valuation_math/test_single_owner.py`.
- Update the "3+-team" `intentionalDifferences` entry.

### 2.10 B2: `src/trade/public_advisor.py`

> **SUPERSEDED by Part 0 — the adapter below was deleted; the module is now the fairness reduction.**

Pure; imports no FastAPI.

```python
ADVISOR_VERSION = "brisket_trade_advisor_v1"
SORTS = ("value_desc", "value_asc", "alpha")
OFFENSE = {"QB","RB","WR","TE","K"}; DEFENSE = {"DL","LB","DB"}

@dataclass(frozen=True)
class AdvisorSnapshot:
    contract; league_key; generation; teams_by_rid; row_index; pick_rows
    rows_by_player_id      # from the SAME _players_array list as row_index
    player_owners          # from teams[].playerIds only
    pick_owner_index; roster_settings
    rosters_state; rosters_as_of   # B0-f

@dataclass(frozen=True)
class PublicAsset: id; kind; label; side; position; nfl_team; season; round; origin_roster_id; projection; evaluable

@dataclass(frozen=True)
class AdvisorResult:            # the ONLY type the router can serialize
    category: str; reason_code: str | None; unavailable_asset_ids: tuple[str, ...]; legs: tuple[TradeLeg, ...]

def build_snapshot(contract, *, league_key, roster_settings, freshness) -> AdvisorSnapshot
def list_teams(snap) -> list[PublicTeam]
def list_team_assets(snap, roster_id, *, sort, projections=None) -> tuple[list[PublicAsset], str]
def validate_trade(snap, *, perspective, teams, legs) -> ValidatedTrade
def evaluate_trade(snap, trade, *, posture_resolver, multi_team_enabled=False) -> AdvisorResult
def _evaluate_trade_internal(...) -> tuple[AdvisorResult, Mapping]   # tests only; internals never leave
```

**Identity translation:**
- **Player `p:<id>`:**
  - `row = rows_by_player_id.get(id)`.
  - No row: UNAVAILABLE `asset_not_evaluable` with that ID.
  - Row found: pass `player_ids_* = [id]` and `players_* = [row_name(row)]` to the service, so it resolves by ID (B0-b).
- **Pick `pick:…`:**
  - `parse_league_pick_id`; its league key must equal the snapshot's.
  - Pass the asset ID (identity pricing, B0-a) and, as the label, the snapshot's own `pickDetails[assetId].label`.

**Validation order** (raises `AdvisorError`):
1. perspective ∈ teams;
2. teams distinct;
3. teams known;
4. IDs parse;
5. no duplicate IDs;
6. `from`, `to` ∈ teams and `to ≠ from`;
7. total legs ≤ 128;
8. **N = 2: each team sends at least 1 asset** (mirrors War Room `ready`, `TradeWarRoom.jsx:663-667`). **N ≥ 3: every team sends or receives** (`idle_team`). Both are recorded as new validity rules in R0;
9. ownership against the snapshot. Players: `player_owners[id] == (from,)`. Picks: `lookup_league_pick_owner` must give owned by `from`. A mismatch is 409 `stale_assets`. Unknown or conflicting ownership continues to evaluation and comes back UNAVAILABLE `ownership_unverifiable`. That is a deliberate stricter divergence from the War Room, named in T.

**2-team evaluation:**
1. Run `analyze_service.simulate_for_team(..., team_context=True, for_analysis=True)`.
2. Run `analyze_for_team(..., counterfactuals=False)`.
3. Map with `public_category_from_decision`.

**3–4-team evaluation:**
- If `multi_team_enabled` is False: UNAVAILABLE `multi_team_unsupported`.
- Otherwise, per team:
  1. call the service with `team_context=False`;
  2. if any team gets `NOT_ENOUGH_EVIDENCE`: UNAVAILABLE;
  3. take leg values from the origin team's `sending`;
  4. run `multi_side.side_flows`, then `side_band`, then `public_category_from_net_band`.

**Package-model guard:** if `config_state() != "ok"`: UNAVAILABLE, generic.

**Asset lists:**
- **Players:** iterate `playerIds`.
  - Label: the row name, else `idToPlayer[id]`, else `"Player <id>"`.
  - Position: `normalize_position`.
  - Value via `resolve_trade_asset(player_id=…)`.
- **Picks:** from `pickDetails`, labelled per §5. When `pickOwnershipState == "unavailable"`: no picks, state `"unavailable"`.
- **`evaluable`** = the asset has a canonical priced row: not off-board, not unpriced, not ambiguous. It does **not** fold in quarantine or staleness. This reduces per-asset model-state exposure. Quarantined or stale assets surface only as a generic UNAVAILABLE at analyze time.
- **Sort:**
  - `value_desc`: priced players by (−value, casefold label, id), then unpriced players by (label, id), then the pick segment.
  - `value_asc`: the exact reverse of the priced-player segment, tie-breaks included, then unpriced players, then picks.
  - `alpha`: all assets by (label, id).
- **Filtering** by group or position is client-side over the returned order.

### 2.11 B3: `src/api/public_trade_advisor_api.py`

**Wiring.** `configure_host`; included beside the articles router. Paths are multi-segment under `/api/public/league/trade-advisor/`. Path and query parameters are declared as `str` and validated in the handler, so FastAPI's 422 can never fire.

**Every handler:**
1. Flag check.
2. `_public_league_key_error`.
3. Capture `contract = host.latest_contract_data` **once**. If `meta.leagueKey` is not the public league: 503 `not_ready`. No overlay splice.
4. Snapshot memo keyed by `(id(contract), generation)`, LRU size 2. It depends on the contract only.

**Analyze, in order:**
1. Exact `Content-Type: application/json`, else 415.
2. Stream the body with `request.stream()`, aborting at 16,385 bytes → 413.
3. `AdvisorAnalyzeRequest.model_validate_json(raw)` (`extra="forbid"`, `strict=True`). This avoids `json.loads` recursion. Failure → 400.
4. **Charge the limiter** (§7) before any evaluation.
5. Evaluate in a threadpool. The posture resolver is `competitive_posture_for(..., build_if_missing=True)`, the same rule as the War Room.
6. **Response floor:** `await asyncio.sleep(max(0, floor − elapsed))`.
7. Serialise through outbound Pydantic models (§4.5), then `assert_public_payload_safe` as a third line.

**Exceptions:** every handler has a `try/except Exception`. Log `type(exc).__name__`, the request ID and `traceback.format_tb()` frames only, never the message and never simulation or decision objects. Return 503 with fixed text.

**Config `config/trade/public_advisor.json`:**

```json
{"version":"public_advisor_v1","multiTeamRecommendations":false,"pickProjectionLabels":false,
 "limits":{"maxTeams":4,"maxLegs":128,"maxBodyBytes":16384},
 "responseFloorMs":null,
 "rateLimits":{"perKeyBurst":{"capacity":40,"windowSeconds":600},
               "perKeyDaily":{"capacity":400,"windowSeconds":86400},
               "neighbourhoodBurst":{"capacity":200,"windowSeconds":600},
               "globalCeiling":{"capacity":3000,"windowSeconds":3600}}}
```

- `responseFloorMs` is set from P's measured p95 Team Context analyze (§11) before launch. Launch is blocked while it is null.
- All numbers are declared priors.

**Flag:** `brisket_trade_advisor`, default True, LIVE, `safe_on`. Rollback: `RISKIT_FEATURE_BRISKET_TRADE_ADVISOR=0` plus a restart.

---

## 3. Category mapping (exact; no new thresholds)

> **PRIVATE ONLY since the fairness-only amendment (Part 0); the public path no longer uses it.**

**Two teams** (`public_category_from_decision`); `A = decision.components.objectiveValue`:

| Condition | Category |
|---|---|
| headline `NOT_ENOUGH_EVIDENCE` | UNAVAILABLE |
| `YES` ∧ `A.direction=="favors"` ∧ `A.magnitude=="large"` ∧ `leaning=="MAKE"` | STRONGLY_FAVORABLE |
| `YES` otherwise | FAVORABLE |
| `NO_TOO_CLOSE` | APPROXIMATELY_EVEN |
| `NO` ∧ `A.direction=="opposes"` ∧ `A.magnitude=="large"` ∧ `leaning=="PASS"` | STRONGLY_UNFAVORABLE |
| `NO` otherwise | UNFAVORABLE |
| `NO` with `deciding=="executionGate"` | UNFAVORABLE with reason `roster_limit`, using its own copy |

**Why this rule:**
- "Strong" = the value band is unfair or lopsided (`_objective_value`, `trade_decision.py:426-430`), measured on the War Room's own quantity (the adjusted gap net of release cost), **and** the engine's headline and graded leaning agree.
- That is the same strong cut used for 3–4 teams (band unfair/lopsided), so "strong" means the same thing at every N.
- In Asset-Only mode it is equivalent to the earlier rule.
- In Team mode it cannot be satisfied by a large roster effect sitting on a slight value edge.

**Three or four teams** (only when enabled):
- fair → APPROXIMATELY_EVEN;
- slight → FAVORABLE / UNFAVORABLE by the sign of net;
- unfair or lopsided → STRONGLY_* by sign.

The help text states:
- the 2-team result accounts for the team's roster, strategy and forced cuts;
- the 3–4-team result is value-only;
- the private reference is the War Room for 2 teams and the meter for 3+.

**Copy** (`PUBLIC_CATEGORY_TEXT`):

| Category (reason) | recommendation | headline | message |
|---|---|---|---|
| STRONGLY_FAVORABLE | ACCEPT | ACCEPT — STRONG TRADE FOR YOUR TEAM | Our analysis strongly favors your side of this trade. |
| FAVORABLE | ACCEPT | ACCEPT — GOOD TRADE FOR YOUR TEAM | Our analysis indicates this trade benefits your team. |
| APPROXIMATELY_EVEN | FAIR | FAIR TRADE — YOUR DECISION | Our analysis considers this a relatively balanced exchange. |
| UNFAVORABLE | DECLINE | DECLINE — NOT RECOMMENDED | Our analysis indicates this trade does not favor your team. |
| UNFAVORABLE (`roster_limit`) | DECLINE | DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE | Your team couldn't complete this trade under the roster limit. |
| STRONGLY_UNFAVORABLE | DECLINE | DECLINE — STRONGLY NOT RECOMMENDED | Our analysis strongly favors the assets your team would give up. |
| UNAVAILABLE | NONE | NO RECOMMENDATION | This trade can't be evaluated reliably right now. |

**Reason codes.** Only these are exposed. Everything else is `null` with the generic UNAVAILABLE copy, and any unknown future code fails closed.

| Engine source | `reasonCode` | Text |
|---|---|---|
| `off_board_assets`, `unpriced_assets`, `no_priced_assets`, adapter no-row | `asset_not_evaluable` (+ IDs) | One or more assets in this trade can't be evaluated right now. |
| `unheld_assets`, `pick_ownership_unknown`, adapter conflicting claims | `ownership_unverifiable` | We couldn't confirm who owns every asset in this trade. |
| config switch | `multi_team_unsupported` | Recommendations for trades with more than two teams aren't available yet. |
| execution gate | `roster_limit` | (copy above) |
| `quarantined_values`, `stale_values`, `posture_unknown`, `roster_unknown`, `unprojected_players`, `roster_limit_unknown`, `forced_drop_unpriced`, package-model guard, unknown codes | `null` | — |

The collapse in the last row hides which teams are classified as rebuilders and which players lack projections. A residual leak remains (see OD-4).

**Stated limitation:** the bands are PROVISIONAL priors and D8 forbids retuning them. When the larger package is below about 2,778, the slight band is unreachable, so small trades read EVEN or STRONG.

---

## 4. Public API contract (frozen)

> **SUPERSEDED by `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` §4 (Part 0).**

**Common to every endpoint:**
- Optional `leagueKey` query parameter (string, validated by the existing helper).
- JSON responses only. No `Server-Timing`, no debug fields.
- Correlation headers stay.
- **All error responses carry `Cache-Control: no-store`, on GET as well as POST.**

### 4.1 `GET /api/public/league/trade-advisor/teams`

200; `public, max-age=60, stale-while-revalidate=300`.

```json
{"leagueKey":"dynasty_main","generation":"3f9a0c1e5b7d2a46",
 "limits":{"minTeams":2,"maxTeams":4,"maxLegs":128},
 "multiTeam":"unavailable",
 "rosters":{"state":"current","asOf":"2026-10-19"},
 "teams":[{"rosterId":4,"displayName":"<manager display name>","teamName":"…"}]}
```

- `rosters.state` ∈ `current | stale | unknown`.
- `asOf` is an ISO date, or null.

### 4.2 `GET /api/public/league/trade-advisor/teams/{rosterId}/assets?sort=value_desc`

- `sort` ∈ SORTS. There are no group or position parameters.
- 200 with the public cache headers.

```json
{"leagueKey":"dynasty_main","generation":"…","rosterId":4,"sort":"value_desc",
 "pickOwnership":"observed","rosters":{"state":"current","asOf":"2026-10-19"},
 "assets":[
  {"id":"p:4984","kind":"player","label":"Josh Allen","side":"offense","position":"QB","nflTeam":"BUF","evaluable":true},
  {"id":"pick:dynasty_main:2027:r1:o7","kind":"pick","label":"2027 1st — Originally <team name>","side":"pick",
   "season":2027,"round":1,"originRosterId":7,"projection":null,"evaluable":true}]}
```

- Player keys and pick keys are exactly the ones shown.
- When `pickOwnership == "unavailable"`, no picks are listed.

### 4.3 `POST /api/public/league/trade-advisor/analyze`

**Request:** at most 16,384 bytes. Same JSON schema as before, except:
- `assets.maxItems = 128`;
- `from` / `to` integers 1–99.

**Response:** 200; `no-store`.

```json
{"status":"success","leagueKey":"dynasty_main","generation":"…","perspectiveRosterId":4,"teamCount":2,
 "category":"FAVORABLE","recommendation":"ACCEPT","headline":"…","message":"…",
 "reasonCode":null,"reasonText":null,"unavailableAssetIds":[],
 "trade":[{"id":"p:4984","from":4,"to":7},{"id":"p:6797","from":7,"to":4}]}
```

`trade` echoes the validated legs in request order.

### 4.4 Errors

Body: `{"error", "message", …extras}`.

| HTTP | `error` | reasons | extras |
|---|---|---|---|
| 400 | `invalid_request` | `invalid_json`, `schema`, `unsupported_sort`, `invalid_roster_id` | `field` (a location path only) |
| 400 | `invalid_trade` | `perspective_not_in_trade`, `duplicate_team`, `unknown_team`, `idle_team`, `one_sided_trade`, `unknown_asset`, `duplicate_asset`, `invalid_origin`, `invalid_destination`, `destination_is_origin`, `too_many_assets` | `assetIds` or `rosterIds` |
| 400 / 404 | `unknown_league` / `inactive_league` / `league_not_public` | — | `leagueKey` |
| 404 | `unknown_team` | — | — |
| 409 | `stale_assets` | `asset_not_owned` | `assetIds` |
| 413 | `payload_too_large` | — | `maxBytes` |
| 415 | `unsupported_media_type` | — | — |
| 429 | `rate_limited` | — | `retryAfterSeconds` + `Retry-After` |
| 503 | `advisor_unavailable` | `disabled`, `not_ready`, `upstream_unavailable` | — |

### 4.5 Outbound models

Every body above has a Pydantic model with:
- `extra="forbid"`;
- `Literal[...]` enums;
- `StrictInt` on exactly these integer keys:
  - `rosterId`, `perspectiveRosterId`, `teamCount`;
  - `season`, `round`, `originRosterId`;
  - `from`, `to`;
  - `minTeams`, `maxTeams`, `maxLegs`;
  - `maxBytes`, `retryAfterSeconds`;
- **no float type anywhere**.

The router cannot send anything except a validated model.

---

## 5. Identifiers and pick labels

**Label format:**
- `f"{season} {round_suffix(round)} — " + ("Own" if fromRosterId == ownerRosterId else f"Originally {team name}")`.
- If OD-2 is approved: `f" — Projected {slot_tier(slot).capitalize()}"`. The projected slot comes from **the draft-order owner already public through Draft Capital**: `src/public_league/draft_order.py` via `draft_capital_order` / `slotStatus: "projected"`. Not the Pick Projector.

The label never affects evaluation. Value is canonical through identity (B0-a).

## 6. Snapshot coherence and freshness

- Every handler captures the contract once. `generation = sha256("brisket-advisor-v1|" + generatedAt)[:16]`.
- Team Context inputs (posture, projections, availability) are read live at analyze time and **never cached across requests**.
- 409 `stale_assets`: the UI refetches with `cache:"reload"`.
- A changed generation in the analyze response triggers a background list refresh.
- **Stale rosters:** when `rosters.state != "current"`, a persistent info Banner reads: "Rosters as of {date}. Recent trades or roster moves may not appear yet."

## 7. Abuse controls

- **Global:** the existing per-IP public bucket (60/min, 1000/h) still applies.
- **Advisor `KeyedLimiter`** (own store, max 20,000 keys), charged before evaluation:
  - per key (IPv4, or IPv6 `/64`): burst 40/600 s, daily 400/day;
  - neighbourhood (IPv4 `/24`, IPv6 `/48`): 200/600 s;
  - global ceiling: 3,000/h, never evicted.
- These are declared priors. The aim is that a draft party on one network does not hit the per-key burst in normal use. A shared IP sitting behind the neighbourhood bucket is the accepted trade-off.
- **Response floor** on analyze (§2.11).
- **Observability only:** a per-key counter of degenerate structures (perspective sends nothing; a third team routes only to a non-perspective team). It is logged, not blocking.
- Production Next bridges for the advisor return 404 when `NODE_ENV === "production"`. nginx sends `/api/` to the backend anyway.

---

## 8. Frontend

### 8.1 Routing (F1)

**`tabs.js`:**
- `TRADE_ADVISOR_TAB = "trade-advisor"` goes first, and `DEFAULT_TAB = TRADE_ADVISOR_TAB`.
- Alias `advisor`.
- `overview` label "Home" → "Overview" (key unchanged).
- `ADVISOR_PARAMS = ["team","step"]`. `leagueTabHref` drops them when the target is not the advisor. Other tabs' parameters behave as today, which keeps `draft-capital-years.test.js` semantics.
- An unknown `?tab=` now falls back to the advisor. Update the pinned tests.

**`LeagueClient.jsx`:**
- The advisor's **team step shell** (`trade-advisor-shell.jsx`, budget ≤ 4 KB) is statically imported. The builder and picker are lazy.
- **OverviewSection becomes `dynamic(…, {ssr:false})`** like the other sections. This removes it from the page chunk and keeps the "no loading flash on the default tab" rationale for the new default.
- URL sync: track the previous `urlTab` in a ref. Any change, including to null, sets `activeTab = valid ? urlTab : DEFAULT_TAB`.
- User tab clicks use `router.push`. Canonicalisation and section-internal selectors (`owner`, `week`, year) keep `router.replace`, so there is no new history entry per selector change.
- On the advisor: `PageHeader` eyebrow = league name, `title = "Brisket Trade Advisor"`, plus the subtitle.
- Overview fetch failures become in-panel states instead of blanking the hub.

**`page.jsx` (league):**
- On the advisor tab, server-fetch `/api/public/league/trade-advisor/teams` (public, value-free) and pass `teams` + `rosters` as props, so the first paint shows the real team picker.
- `generateMetadata` gets an advisor branch.

**`app/page.jsx`:**
- Button text "Go to League Hub"; updated caption and comment.
- **Signed-in visitors** reach the advisor through nav "League → Hub". Criterion A is literally met for signed-out visitors, and the final report says so.

**Other routing changes:**
- **Eight** back-links are retargeted to `/league?tab=overview` (default, pending OD-6).
- `nav-model.js`: hint and keywords.
- `sitemap.js`.
- No change to `public-routes.js` or `middleware.js`.

### 8.2 Components (`frontend/app/league/sections/`)

| File | Role |
|---|---|
| `trade-advisor-shell.jsx` | static. The PSI island root (`psi-editorial`, `--surface-1`); team-count control (desktop: top); "Which team are you evaluating for?" Combobox; field hint. Restores session state in `useEffect` after mount, never during render, so there is no hydration mismatch. |
| `trade-advisor.jsx` (lazy) | reducer orchestration, builder, summary, result |
| `_advisor-team-panel.jsx` | ds `Panel` per team. Selected rows with Remove (`aria-label`); for N ≥ 3, a "Send to" `Select` |
| `_advisor-asset-picker.jsx` | search; `SegmentedControl` All / Offense / Defense / Picks; position `Select` from the positions present ("DL (DT/DE)", "DB (CB/S)"); sort `Select`; options rendered as `<ul role="listbox">` **without** `aria-posinset` / `aria-setsize`; per-list loading skeleton, error with Retry, and two distinct empty states: "No assets match this filter." vs "Pick ownership for this team can't be confirmed right now, so picks aren't listed." |
| `_advisor-asset-sheet.jsx` | Drawer (bottom) below 768 px, Modal at 768 px and above; lazy |
| `_advisor-summary.jsx` | 2 teams: You send / You receive. 3+: a DataTable of text columns |
| `_advisor-result.jsx` | heading "Trade analysis" (focus target); server text rendered verbatim; semantic rule and icon; one polite live region; buttons **Edit trade**, **New trade** (keeps teams), **Start over** (clears teams), and **Try again** on UNAVAILABLE (resubmits the same trade) |
| `trade-advisor.module.css` | tokens and the 480/768/1024/1320 breakpoints only; 44 px targets |
| `lib/trade-advisor.js` | pure reducer and selectors; `toAnalyzeRequest`. No values. |
| `lib/trade-advisor-client.js` | fetch helpers; `credentials:"omit"`; analyze `no-store`; latest request wins; one retry on 502/504 |
| `components/ds/Combobox.jsx` | new ds primitive modelled on the existing ARIA pattern at `trade-sections.jsx:750-765` (role, `aria-activedescendant`, keys). `/trade` is not migrated (Lane 6 follow-up). Added to the `/design` gallery and `frontend/__tests__/components/ds/psi-gallery.test.jsx`. |
| Dev bridges | three routes under `frontend/app/api/public/league/trade-advisor/…`; return 404 in production |

### 8.3 State machine

**State:** `{phase, teamCount, slots, legs, result, error, staleIds}`.

**Actions:**
- `SET_SLOT(i, rid)`: **teams already in another slot are disabled in the picker** ("in trade"), and the reducer rejects them defensively. There is no swap.
- `SET_TEAM_COUNT(n)`:
  - legs from dropped teams are removed;
  - legs to dropped teams get `to = null`;
  - **when n becomes 2, every surviving leg is retargeted to the other slot automatically**;
  - an info Banner lists removed legs.
- `ADD_ASSET` is refused for duplicates.
- Any edit in `result` returns to `build` and clears the result.

**Client validation:**
- choose your team / choose a partner / choose Team C;
- **each team must send at least one asset** (2 teams);
- every team must send or receive (3+);
- choose where X goes.

**Persistence:** `sessionStorage["brisketAdvisor:v1"]` holds teams, legs (IDs and labels) and the last result enum and text keyed by `(generation, trade hash)`. Wrapped in try/catch.

**URL:**
- `?team=` is set with `replace`. **The URL wins:** if it differs from the stored slot 0, start fresh with the URL team.
- On analyze success, `push` `?step=result`. Back returns to `build` with the legs intact. Forward re-shows the result only if the cached `(generation, hash)` matches; otherwise it shows build.

**Refresh:** lists are refetched on `visibilitychange` when more than 5 minutes old, on 409, and on a generation change.

**Errors:** 409 Banner plus moved-leg flags; 429 `FailureState` with countdown; 503 / offline Retry; `disabled` → a Panel with a link to Overview.

### 8.4 Mobile flow

The directive's mobile order:
1. Select your team.
2. Select trade partner. The "Teams involved: 2 ▾" control sits in this step's header, default 2. This reconciles Phase 4 "at the top" (desktop) with the mobile flow at directive :890.
3. Build: You send / You receive.
4. Review.
5. Analyze.
6. Recommendation.

No horizontal overflow at 390 px.

### 8.5 Bundle plan

- `/league/page` stays ≤ 50 KB. It gains the shell (≤ 4 KB) and loses OverviewSection.
- `frontend/scripts/check-public-bundle-privacy.mjs`:
  - locates the advisor chunks through the build's loadable manifest;
  - fails above a declared advisor-chunk budget (measured + 15%);
  - greps them for **data-path markers**: `/api/data`, `/api/dynasty-data`, `/api/trade/`, `useDynastyData`, `credentials:"include"`. Formula names are not used as markers, because shared chunks already carry them through AppShell.
- Import ds parts by file path, not through the barrel.

### 8.6 Data the frontend never holds

No values, ranks, `data-*` value attributes or numeric position attributes. Only IDs, labels, positions, booleans and enums.

---

## 9. Records (R0)

**Owner intake and authorisation:**
- The directive saved verbatim at `docs/owner/BRISKET_TRADE_ADVISOR_2026-10-19.md` *(pointer corrected on commit; the draft named a `…_DIRECTIVE_…` filename)*, registered in `docs/PLANNING_DOCUMENT_STATUS.md` §3.
- `docs/OWNER_REQUESTED_TODO.md` entry, with rows for OD-1…OD-8.
- `docs/EXECUTION_PLAN.md` §0 authorisation, including what it does not authorise: multi-team recommendations, projected labels, retuning the bands.

**Boundary records:**
- `MASTER_PRODUCT_PLAN.md` 43/46/452/602 (371 only if OD-2).
- `OWNER_PRODUCT_BACKLOG_SPEC.md` 38/217/373/382/392-400.
- `CLAUDE.md`: boundary paragraph; a new section "Brisket Trade Advisor — public restricted interface"; correct the stale statements found by the audits.
- `C_SERIES_EXECUTION_MAP.md` 545-547.

**The boundary exception must name, explicitly:**
- inferred strategy direction (OD-4);
- per-team player ordering;
- `evaluable`;
- the new validity rules (`one_sided_trade`, `idle_team`);
- the 128-leg payload bound.

**Scope manifest and coupled records:**
- `C_SERIES_SCOPE_MANIFEST.md` row `C9-ADVISOR-01` (deps `C3-VA-01, C7-DESK-01, C1-ID-01, C1-ID-02, F-PRIV-01`).
- Row count 164 → 165; §5 tally.
- `C_SERIES_EXECUTION_MAP.md` unit `C9-U8`.
- `docs/completion/families/family_C.json`, then `python scripts/completion_ledger.py`.
- `C_SERIES_ZERO_LOSS_TRACEABILITY.md` §6.

**Registers, inventories and ledgers:**
- `OWNER_DECISION_REGISTER.md` rows.
- `OWNER_FEATURE_INVENTORY.md`.
- `PACKAGE_MODEL_CONSUMER_INVENTORY.md` (`public_advisor`, `multi_side`, `analyze_service`).
- `CANONICAL_VALUE_CONSUMER_AUDIT.md:60`.
- `WORK_CLAIMS.md` (backend, frontend, F0, records; `Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c`).
- `docs/ui/UI_PARALLEL_LEDGER.md` (advisor route, ds Combobox, measured chunk sizes).

**Code-adjacent counts and inventories:**
- Feature-flag counts: `feature_flags.py`, `README.md:20`, `docs/ARCHITECTURE.md:29`. Recount at implementation.
- Route and privacy inventories: `test_private_auth.py`, `test_cache_control_privacy.py` (`SCANNED_SOURCES`), `test_public_league_no_raw_ids.py`, `test_health_operation_id.py`, `critical-smoke.spec.js`.

## 10. Engineering-reliability applicability check

Against `docs/engineering/ENGINEERING_RELIABILITY_PRIORITIES_2026-09-06.md`:

| Mechanism | Disposition |
|---|---|
| Typed API contracts | **APPLY_NOW**: inbound and outbound Pydantic models plus shared JSON fixtures |
| Property / adversarial contract tests | **APPLY_NOW**: perspective reversal, the category invariant table, the sentinel and no-float tests |
| Cross-language parity | **APPLY_NOW**: CI-regenerated multi-side fixture; pick-row cross-language test |
| Architecture / import boundaries | **APPLY_NOW**: the AST service-delegation guard; the frontend import-graph isolation test |
| Observability / SLOs | **APPLY_NOW** (light): latency measurement, UNAVAILABLE-rate census, degenerate-structure counter |
| Source replay | ALREADY_COVERED: no new external input |
| Persistence / migrations | NOT_RELEVANT: no writes |
| Supply chain | NOT_RELEVANT: no new dependencies |
| Mutation testing of the mapping | DEFERRED_BY_AUTHORITY |

## 11. Tests, mapped to the owner's groups A–F

### A — Parity

**A1. `tests/trade/test_public_advisor_parity.py`**
- Builds the contract from `newest_complete_raw_payload()`.
- Monkeypatches the posture and utility seams once, so both paths see the same inputs.
- For each case it calls:
  - the private `/api/trade/analyze` with a session, sending names **and** `playerIdsIn/Out` + `pickAssetIds` (post-F0 shape), with Team Context on and off;
  - `public_advisor._evaluate_trade_internal`.
- Asserts equal `headline`, `leaning`, `deciding`, `components.objectiveValue` and `confidence.axes`, and the category mapping.
- Cases (directive items 1–15):
  - **shapes:** 1-for-1, premium-for-several, many-for-many;
  - **positions:** offense only, IDP only **per family (DL / LB / DB)**, mixed;
  - **players and picks:** players↔picks, mixed packages, VA > 0;
  - **unpriced and ownership:** unpriced kicker; owned 2027 pick; owned 2028 pick;
  - **identity and rosters:** a **synthetic name-collision fixture** (both paths now UNAVAILABLE); a **roster-6-style ID-not-in-names** case;
  - **projected labels:** run with `pickProjectionLabels` on in test config. The category must not change;
  - **comparables:** with vs without comparables (the private side) gives the same category.

**A2. `tests/api/test_trade_simulator_pick_identity.py`** (B0-a)
- For every `pickDetails` label in **both grammars** on the archive board: the identity path gives the same row regardless of label.
- "2027 1st" → "2027 Pick 1.06".
- The label-only path matches the old row for all non-defect labels (the 276/282 census).
- `board_diff --expect-no-value-change`.

**A3. `tests/identity/test_pick_row_cross_language.py` + `frontend/__tests__/pick-row-parity.test.js`**
- For every `pickDetails` entry, the JavaScript `resolvePickRow` row name equals Python's `boardRowName`.

**A4. End-to-end 3+-team meter parity** (gates the multi-team switch)
- Node materialises rows with `buildRows` from the archive contract.
- It resolves owned picks through `boardRowName`, then runs `computeSideFlows`, `multiTeamNetSummary` and `meterVerdict` per side.
- Python asserts that `public_category_from_net_band` agrees in sign and level for every perspective.
- Cases: 3-team and 4-team cycles, nonreciprocal routing, unequal counts, mixed players and picks.

**A5. Twin parity** per §2.9, with the corrected assertions.

**A6. Rounding seam**
- Component A's band equals `equity_verdict`'s band when no release cost is charged.
- A contract-level test that `rankDerivedValue` is integral on every row, which is what keeps the `int()` / banker's-rounding seams inert.

**A7. Package model** on `config_state != ok` → UNAVAILABLE.

**Parity tests pin the default board** (no `customValue`, no `siteWeights`, no TE slider). This is documented.

### B — Consistency

`tests/trade/test_public_category_mapping.py`:
- An exhaustive table over (headline × leaning × A.direction × A.magnitude × deciding).
- **Invariants:**
  - STRONGLY_FAVORABLE only with YES and a large favouring band;
  - never favourable with NO;
  - NOT_ENOUGH_EVIDENCE always → UNAVAILABLE;
  - **never STRONGLY_FAVORABLE when `equity_verdict`'s band is unfair or lopsided against the perspective**.
- **Perspective reversal:**
  - Asset-Only, 1,000 synthetic trades: mirrored;
  - Team mode: each perspective equals the private result for that perspective;
  - N-side: agrees with the JavaScript tag.
- **Source scans:**
  - category text exists only in `trade_decision.py`;
  - the frontend renders it verbatim;
  - `reasonText ∈ PUBLIC_REASON_TEXT.values()`;
  - no engine `text` field is forwarded;
  - unknown gap codes → null.

### C — Ownership

`tests/api/test_public_trade_advisor_validation.py`:
- 409 for a player or pick not held by the origin team.
- Every `invalid_trade` reason, including `one_sided_trade`.
- Swap the contract S1 → S2: 409, then the list moves.
- Unknown pick inventory → UNAVAILABLE `ownership_unverifiable`.
- A contract swap during evaluation still uses the captured object.
- A cached list (max-age 60) against a swapped contract → 409 recovery.
- The roster-6 ID-not-in-names player is listed and tradeable.

### D — Privacy and security

`tests/api/test_public_trade_advisor_privacy.py`:
- Every body passes its outbound model with exact key sets, on all paths: 400/404/409/413/415/429/503 and the forced exception.
- Sentinel `rankDerivedValue` 987654 / 876543 never appears in any body or header.
- No floats. Integer keys only from the §4.5 list.
- An environment-secret sentinel and an exception-message sentinel are absent from responses **and from the logged record** (`caplog`: type and frames only).
- Headers: no `Server-Timing`; analyze and **all** errors `no-store`.
- A streamed chunked body over the cap → 413.
- Deeply nested JSON → 400.
- Non-integer `rosterId` path → 400 in our body shape (never 422).
- Limiter:
  - per-key, neighbourhood and global ceiling 429 via the `_keyed_now` seam;
  - advisor keys cannot evict another `KeyedLimiter`'s buckets;
  - a spoofed `X-Real-IP` from an untrusted peer is ignored.
- The response floor holds: elapsed ≥ floor for fast cases (monkeypatched clock).
- `whatWouldChange` is not computed on the public path (a spy).
- Private routes return 401 anonymously.

Frontend:
- **Import-graph isolation** (`route-import-graph.mjs`).
- A source scan for value field names.
- The **manifest-located chunk grep**.
- `productionBrowserSourceMaps` is off.
- The picker has no `aria-posinset`, no `<ol>` and no `data-*` value attributes.

### E — Frontend

**Reducer tests:**
- every action;
- 3→2 retargeting;
- disabled-team rejection;
- one-sided validation;
- URL `team` vs sessionStorage precedence.

**Component tests:**
- selection, search, filters, server sort order rendered unchanged;
- a non-allowlisted numeric field never reaches the DOM;
- empty-filter vs unavailable-ownership copy;
- per-list loading and error;
- all categories, including the `roster_limit` copy;
- Try again on UNAVAILABLE;
- the stale-roster Banner;
- Back from result → build;
- 409 / 429 / 503;
- focus and the single announcement.

**E2E `league-trade-advisor.spec.js`** (desktop-1366 and mobile-chromium; anonymous; service workers blocked; fixtures mocked):
- h1 is "Brisket Trade Advisor";
- the 2-team flow and the 3-team builder showing UNAVAILABLE;
- one case per category;
- 409 / 429;
- Back across tabs and Back from a result;
- `?tab=awards` still works;
- the landing button opens the advisor;
- no requests to `/api/data` or `/api/trade/`;
- 390 px with no horizontal scroll;
- axe scans.

Plus one unmocked smoke test against the E2E stack.

### F — Regression

Update:
- `league-tab-sections.test.js` (79-90);
- `draft-capital-legacy-redirect.test.js`, `draft-capital-years.test.js`;
- `public-league.spec.js`, `public-league-visual.spec.js:75`;
- `prod-auth/w1-12-public-pregame.spec.js:105`, `prod-auth/v1-123-public-league-matrix.spec.js:28-42, 90-93`;
- `a11y-axe.spec.js`;
- `tests/e2e/route-useful-state.test.mjs`, `helpers/journey.js`, `measure-route-baselines.mjs`;
- naming-canon;
- `sitemap.js`.

Also:
- F0: update the `/trade` meter tests for owned 2028+ picks (`<value A>` → `<value B>`) and the War Room request shape.
- Run `bash scripts/tiered_validate.sh l1`, then the full `pr-validation` (`server.py` and `Dynasty Scraper.py` are high risk, so both suites run).
- Write zero new coercions, and do not touch `config/coercion_baseline.json`.

## 12. Performance (P)

**Backend:** `scripts/measure_trade_advisor.py`, 50 runs each, p50 and p95, for:
- list assets (12 teams × 3 sorts);
- 2-team Team Context analyze with warm and cold posture;
- Asset-Only analyze;
- the 4-team internal path;
- the route through TestClient.

Its output sets `responseFloorMs`.

**Posture warm:** add the posture bundle to the post-publish warm pass, so anonymous traffic rarely triggers a cold build. [inferred: locate the existing post-scrape warm hook.]

**UNAVAILABLE census:** the rate of UNAVAILABLE over a sample of realistic trades per team, in Team mode.

**Frontend:**
- `measure-mobile-usability.mjs` and `measure-route-baselines.mjs` for `/league` LCP/CLS before and after;
- `measure-trade-interaction.mjs`, adapted, for list render and filter on an 80-asset roster on throttled CPU.

There is **no analyze-result cache.**

## 13. Security checklist (S)

1. New paths are public only by prefix. No change to `_PUBLIC_API_EXACT`. Private routes stay 401.
2. Outbound models; exact key sets; sentinels.
3. No floats, bands, confidence, counterfactuals or decision objects. `AdvisorResult` holds public fields only.
4. Headers: errors `no-store`; GETs identical for every caller.
5. Errors carry no exception text, no input values and no `errorType`. Logs contain type and frames only.
6. Streamed body cap, 415, strict inbound schema, `str` path and query parameters, 4 teams, 128 legs.
7. Trusted-proxy IP parsing; isolated limiter; neighbourhood and global ceilings. **Ops:** bind both services to loopback and verify that `:8000`, `:3000` and `/openapi.json` are unreachable.
8. No `record_decision`, comparables, disk writes or result memo.
9. No overlay splice; public league only.
10. RSC payload carries only teams, rosters freshness and overview data.
11. No value `data-*`, no posinset.
12. Storage: IDs, labels, result enum and text only. Analyze is a POST and never cached by the service worker.
13. Bundle: manifest-located grep, source maps off, import-graph isolation.
14. No debug routes. Production bridges return 404.
15. Pre-existing exposures to report, not change:
    - `/api/draft-capital` dollars;
    - `/api/rankings/sources` weights;
    - `/api/status` source health;
    - `/api/public/league/metrics` count;
    - the public bridge echoing `err.message`;
    - **the service worker storing private GET responses at rest** (`sw.js:157`);
    - deploy logs printing backend journals into public Actions logs.
16. Leakage baseline: the repo is public (`SECURITY.md:56-66`). The final report states that the controls protect the served product, not against reconstruction from git.

## 14. Deploy, verification and Deliverable 10 (D)

**Sequence:** R0 → B0 PRs (each with board_diff and trade-surface before/after evidence) → B-advisor + F1/F2 integration PR (L2) → L3 `release-candidate.yml` HEAD FREEZE → merge → `deploy.yml` → production verification.

**Production verification** (UI contract completion bar, `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md:157-158, 336-339`):
- anonymous desktop and mobile screenshots of `/league` (advisor landing), the picker and each result type;
- a production analyze returning only the enum shape;
- `curl` headers;
- private routes 401;
- the B0-a production check (an owned 2027 pick in the War Room now decides);
- the measured advisor chunk size and LCP;
- UNAVAILABLE census.

Report MERGED / DEPLOYED / VERIFIED separately.

**Deliverable 10:** a final report with commit SHAs, PR links, measured numbers, limitations (signed-in landing path; DT/DE/CB/S filters; multi-team off; projected labels off; the residual leakage of OD-4), rollback steps, and the completion result contract with `UNRESOLVED`.

---

## OPEN QUESTIONS / RISKS

### Owner decisions

**OD-1 — 3–4-team recommendations.** *RESOLVED 2026-10-20: YES (fairness-only publicly) — see Part 0.*
- Decision 10 / D10 (`EXECUTION_PLAN.md:80`) against the directive's "existing multi-team engine".
- **Default OFF** (`multi_team_unsupported`).
- Switching on also requires OD-5 and A4 green (A4 depends on F0).

**OD-2 — Projected Early/Mid/Late labels.**
- `/trade` has no projected-pick logic.
- Two producers exist: Draft Capital's public `slotStatus: "projected"` (draft-order owner) and the private Pick Projector.
- Recommended owner, if approved: the public draft-order path.
- **Default OFF.** Labels never change value.

**OD-3 — Source permission.**
- Signals' authorisation covers "authenticated Calculator displays". Public categories and player orderings carry its contribution, and with the rest of the board reproducible from git the advisor is effectively its public readout.
- Confirm, or decide otherwise. Excluding Signals would break parity.
- IDP Trade Calculator remains unrecorded.

**OD-4 — Posture exposure.**
- With Team Context required, the split between UNAVAILABLE and a decision, plus value-up/lineup-down probes, lets anyone infer each team's strategy class.
- Reason collapse narrows this but cannot remove it.
- Accept it as part of the boundary exception?

**OD-5 — One formula, two languages.**
- The pinned, CI-regenerated Python twin follows the existing VA and fairness-band two-language pattern.
- The alternative: Python owns N-side flows and `/trade`'s 3+-team meter consumes a server result, which would need the private route to accept `customValue` numbers.

**OD-6 — "League home" back-links.**
- `?tab=overview` (keep the old meaning; the default here) or the new default (advisor)?

**OD-7 — The existing public pick-dollar Trade Simulator** on Draft Capital.
- Keep, relabel ("Pick dollar totals") or retire? It can contradict the advisor one tab away.

**OD-8 — New validity rules and bounds.**
- `one_sided_trade`, `idle_team`, the 128-leg payload bound and the limiter priors are new declared rules. Confirm them.
- Also: picks ordered separately rather than value-interleaved.

### Risks

1. **B0-a, B0-b and F0 change live private results:**
   - War Room owned-2027 picks get a decision;
   - baked-label owned 2028+ picks and the `/trade` meter go `<value A>` → `<value B>`;
   - name-collision and name-missing rosters change.

   These are defect fixes toward the canonical owner (`picks.py:751-760`), but they are user-visible. Before/after evidence and an owner heads-up are required.
2. **F0 file contention** with the trade-calculator rework. The 2-team advisor does not wait for it; multi-team enablement does.
3. **Team Context UNAVAILABLE rate in season** may feel broken. Measure it (P).
4. **Method change between 2 and 3+ teams** (only relevant if OD-1 is enabled): the 2-team result includes release cost and roster context; 3+ is value-only.
5. **Roster freshness:** up to about 2 h, longer after an outage. It is now labelled, but the private UI's 15-minute overlay can still show newer moves.
6. **Inference:** per-team ordering plus categories still allow slow reconstruction. The rate limits are speed bumps (in-process, so correct only with a single worker; per-/64 keys can be multiplied).
7. **Unverified exposure:** whether `:8000` / `:3000` are reachable from the internet. If they are, IP-based limits can be bypassed today, independent of this feature.
8. **Timing floor:** the 0.05–29 ms spread was measured in a sandbox. The floor value depends on P.
9. **PROVISIONAL bands;** small trades jump from EVEN to STRONG; D8 forbids retuning.
10. **Hub-wide changes:**
    - `push` for tab clicks;
    - the Overview rename and lazy-load;
    - unknown-tab fallback;
    - back-link targets;
    - about 5 KB of budget headroom.
11. **Offensive team name** surfaced on the landing dropdown (already present on public franchise pages).
12. **DT/DE/CB/S filtering** cannot be met literally from the data (S = 0 tokens). Reported as a limitation.
13. **Merge conflicts** with `origin/integration/train-12-2026-10-19` and the idp-source-independence branch (§0, the intake ledger, `trade-logic.js`, `page.jsx`, flag counts). Rebase and recount.
14. **War Room KTC fallback** (`package_model.py:66-80`) is left unchanged on private surfaces: a DEFERRED follow-up.
15. **Not yet measured:**
    - cold-posture latency;
    - the advisor chunk size and landing LCP/CLS;
    - the production effect of B0-a/b;
    - whether posture caching is keyed to the contract generation.

---

## CHALLENGE DISPOSITION

### Parity critique

| # | Disposition | Reason / fold-in |
|---|---|---|
| F1 pick grammar / two values | **Accepted** | B0-a: identity-first pricing, with the label path replaced by `resolve_pick_value` (no extra rung). B0-g: `boardRowName` stamp. F0: `resolvePickRow` reads it and "Mid" is deleted. A2/A3 cross-grammar and cross-language tests. |
| F2 copied orchestration | **Accepted** | B0-c `analyze_service` used by both private routes and the advisor; valuation scope moved to pure `valuation_scope.py` with the server seam delegating; provenance taken from the passed contract; AST delegation guard. |
| F3 identity guard fails (shallow copies) | **Accepted** | Both indexes are built from the same list; identity is compared by `row_player_id`; superseded by ID-keyed resolution (B0-b). |
| F4 no end-to-end 3+ meter parity | **Accepted** | A4 Node `buildRows`-based fixture; it gates the multi-team switch. |
| F5 two assertions fail | **Accepted** | Per-field / `float.hex` comparison; 1e-6 tolerance for the N = 2 reduction. |
| F6 float divergence | **Accepted** | B0-e iterative weights plus left fold in both owners; fixture regenerated; request team order kept and the ULP-order effect documented. |
| F7 gift trades | **Accepted** | `one_sided_trade` rule at N = 2, mirroring `TradeWarRoom.jsx:663-667`; recorded as a new rule (OD-8). |
| F8 strong differs by N; War Room is the reference | **Accepted** | War Room named as the reference; "strong" now requires the large value band at every N; help text states release cost and Team Context apply to 2 teams only. |
| F9 rounding seams | **Accepted in part** | Added A6: band-equality test plus an integral-value contract test proving the seams inert. **Rejected** changing `_objective_value` / `int()` rounding now: behaviour-preserving only for integer inputs, which are all that exist, and D8 forbids reopening the decision engine (`docs/EXECUTION_PLAN.md:87-88`). |
| F10 KTC fallback | **Accepted in part** | The advisor fails closed via `config_state()`. The War Room fallback change is DEFERRED: it alters a private decision-engine behaviour outside the advisor's authority. Listed as Risk 14. |
| F11 stricter divergences / name-keyed roster | **Accepted** | B0-b roster from `playerIds`; deliberate divergences (conflicting claims, player ownership) named and tested (C, A1). |
| F12 /trade-only inputs | **Accepted** | Parity tests pin the default board; `customValue`, `siteWeights` and the TE slider documented. |

### Privacy critique

| # | Disposition | Reason / fold-in |
|---|---|---|
| 3.2 shared memo | **Accepted** | Dropped; no analyze-result caching anywhere. |
| 4.1 posture oracle / reason codes | **Accepted** | `team_context_unavailable` and `value_withheld` collapsed to generic; residual raised as OD-4. |
| 3.1 counterfactual timing | **Accepted** | `counterfactuals=False` (B0-d) plus a constant response floor set from measurement. |
| 2.1 pick landmarks | **Accepted** | Picks get their own segment, ordered by season, round and origin; owner nod in OD-8. |
| 2.2 ties | **Accepted** | `value_asc` is the exact reverse of the priced segment. |
| 2.3 posinset / `<ol>` | **Accepted** | `<ul>` listbox without posinset; component test. |
| 2.4 `evaluable` | **Accepted** | Narrowed to "has a canonical priced row" (no quarantine or stale); named in the boundary record. |
| 3.3 cold posture | **Accepted** | Posture added to the post-publish warm pass; floor covers the residual. |
| 3.4 GET errors cacheable | **Accepted** | All errors `no-store`. |
| 4.2 3–4-team value oracle | **Accepted** | Multi-team off by default; global ceiling and neighbourhood buckets; the per-team 32 replaced by a declared 128-leg bound; degenerate-structure counter. |
| 5.1 IP forgery | **Accepted** | B0-h trusted-proxy parsing; loopback binding as an ops unit with verification. |
| 5.2 shared, evictable store | **Accepted** | Separate `KeyedLimiter` instance; the ceiling is never evicted. |
| 5.3 `request.body()` | **Accepted** | Streamed cap. |
| 5.4 Next bridges | **Accepted** | 404 in production. |
| 6.1 blocklist misses vocabulary | **Accepted** | Outbound Pydantic models with no float types. |
| 6.2 decision on dataclass / numeric prose / unknown codes | **Accepted** | `AdvisorResult` holds public fields only, with `_evaluate_trade_internal` for tests; constant-copy tests; unknown codes → null. |
| 6.3 422 / RecursionError | **Accepted** | `str` parameters; `model_validate_json`. |
| 7 logs to public Actions | **Accepted** | Type and frames-only logging; deploy-log exposure reported. |
| 8.1 bundle grep target | **Accepted** | Manifest-located chunks; data-path markers. |
| 8.4 service worker private caching | **Accepted as report only** | Pre-existing and outside this feature's authority. Listed in §13 item 15; not changed in the advisor PR. |

### Completeness critique

| # | Disposition | Reason / fold-in |
|---|---|---|
| §0.1 multi-team default ON | **Accepted** | Default OFF; enablement gated on OD-1, OD-5 and A4. |
| §0.2 twin as second owner | **Accepted in part** | The twin is still specified because the repo's established model is a pinned per-language twin (CLAUDE.md "Owners" table lists separate Python and JS VA owners; the fairness-band JS mirror). But it is now CI-regenerated so drift cannot merge, switched off, and the single-owner alternative is put to the owner as OD-5. The literal objection is rejected in so far as precedent shows a pinned twin is not an "independent calculator". |
| §0.3 identity workaround | **Accepted** | B0-b fixes the shared owner; the advisor no longer diverges. |
| §0.4 pick parity with the meter | **Accepted** | B0-g + F0 + A3/A4. |
| §0.5 / F2 projected-slot inventory | **Accepted** | Audit corrected; OD-2 restated with the draft-order owner as recommended producer; A15 runs with labels on in tests. |
| §0.6 freshness / degraded | **Accepted** | B0-f evidence, `rosters` block in the API, stale Banner. |
| F1 existing public Trade Simulator | **Accepted** | Inventoried; OD-7. |
| F3 baked grammar | **Accepted** | As parity F1. |
| F4 eight back-links | **Accepted** | Corrected. |
| F5 owner/week params | **Accepted** | Only advisor-owned params are dropped; other tabs' parameter behaviour is unchanged. |
| F6 32 not a cap | **Accepted** | Removed; declared 128-leg payload bound (OD-8). |
| F7 KTC fallback | **Accepted in part** | As parity F10. |
| F8 Team Context outside generation | **Accepted** | No result caching; documented in §6. |
| F9 cold-solve cost lever | **Accepted** | Warm pass, limits, ceiling, floor. |
| F10 single worker | **Accepted** | Already Risk 6; no change needed. |
| F11 psi-gallery path | **Accepted** | Corrected. |
| F12 existing combobox | **Accepted** | ds Combobox modelled on `trade-sections.jsx:750-765`; migrating `/trade` is a Lane 6 follow-up, to avoid a `/trade` regression in this unit. |
| F13 missing regression specs | **Accepted** | Added to F; also `test_health_operation_id.py`. |
| Phase 2: signed-in landing | **Accepted** | Stated as a limitation of criterion A. |
| Phase 2: Back/Forward | **Accepted** | Push for tabs, replace for selectors, `?step=result` history entry, URL-over-storage precedence. |
| Phase 2: first-paint flash / hydration | **Accepted** | Static SSR team shell with server-fetched teams; Overview lazy; restore in `useEffect`. |
| Phase 2: back-link meaning | **Accepted** | OD-6. |
| Phase 3 disabled-vs-swap | **Accepted** | Disabled, no swap. |
| Phase 4: 3→2 retarget | **Accepted** | Automatic retarget. |
| Phase 4: new rules | **Accepted** | Recorded (OD-8). |
| Phase 4: mobile order | **Accepted** | Team count moved into Step 2 on mobile. |
| Phase 5: DT/DE/CB/S | **Accepted** | Reported as a limitation (Risk 12). |
| Phase 5: collision sort | **Accepted** | Resolved by ID-keyed resolution. |
| Phase 5: `evaluable` leak | **Accepted** | Narrowed. |
| Phase 5: filter execution | **Accepted** | Server sort, client filters; group and position removed from the API. |
| Phase 6 unavailable-ownership copy | **Accepted** | Distinct empty states. |
| Phase 8 strong semantics | **Accepted** | Large value band required at every N. |
| Phase 8 executionGate copy | **Accepted** | Dedicated `roster_limit` headline and message. |
| Phase 9 Retry / full reset | **Accepted** | Try again on UNAVAILABLE; Start over. |
| Phase 10 shared IPs | **Accepted** | Raised per-key burst plus a neighbourhood bucket; trade-off stated. |
| Phase 10 eviction | **Accepted** | Isolated limiter. |
| Phase 10 credential sentinel | **Accepted** | Added. |
| Phase 10 integer allowlist | **Accepted** | Complete list in §4.5. |
| Phase 12 UI contract not cited | **Accepted** | Cited; completion bar in §14. |
| Phase 13 periodic refresh | **Accepted** | Visibility-based refetch. |
| Phase 14 empty / loading / IDP per family | **Accepted** | Added. |
| Phase 16 frontend performance, lazy budget | **Accepted** | Harnesses named; advisor-chunk budget in the privacy/bundle script. |
| Phase 17 applicability check | **Accepted** | §10. |
| Phase 18 Deliverable 10 / deploy plan | **Accepted** | §14. |