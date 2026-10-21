# Brisket Trade Advisor — privacy and abuse verification (Lane E-2, read-only)

- **Date:** 2026-10-20.
- **Authority:** owner directive 2026-10-20 §9, plus its fairness-only amendment. CLAUDE.md invariants apply.
- **Target:** `claude/advisor-hub-frontend` @ `650bea61473f9f7905f7b73bcb186000912d3162` (#1866). It contains #1861 Lane C @ `82ca5fa984` and Lane A @ `44960d624c`.
- **Stack:** a locally booted copy in a throwaway sparse worktree, `/home/user/rit-tam-e2`. It has since been removed.
- **Changes:** none to any branch, PR, flag, config or record. Production was not touched.
- **Agent-OS-Receipt:** `cdca1dca8385f70c0989302dece8d1bd4ce4843c`

Each claim is tagged:
- **[measured]**: observed on the local stack;
- **[verified]**: read in code or config;
- **[inferred]**: reasoned from the first two;
- **[ops]**: can only be settled on the production box.

## 0. Harness

Everything ran locally. Nothing in this harness changes product code.

**Backend:** `scratchpad/tam/e2/run_backend.py` runs `server.py` from the throwaway worktree with these in-process settings:
- `RISKIT_FEATURE_BRISKET_TRADE_ADVISOR=1`.
- `_launch_gate_reason` patched to open. The committed gate correctly stays closed, because the floor, the fairness approval and the source-permission record are all null.
- `SCRAPE_SCHEDULER_ENABLED=0`.
- The loaded contract's `sleeper` block stamped `rosterSource=live` / `rosterFetchedAt=now`. The checked-out export carries no stamp, so without it every team answers UNABLE (`roster_freshness` → `unknown`).
- Optional in-process overrides: `responseFloorMs`, and limiter capacities raised to 10^9.

**Instances:**
- **:8200:** bound to 0.0.0.0 (sandbox only), default limits, no floor. Used for the limiter, client-IP, fuzz, auth and browser probes.
- **:8201:** loopback, limits lifted, no floor. Used for the reconstruction and timing baseline.
- **:8202:** loopback, limits lifted, floor `{"2":50,"3":65,"4":110}` ms. These floor numbers are illustrative local values, **not** a recommended production floor.

**Frontend:** `next start` from the same worktree on :3300, built with `npm run build:nocheck` at that head. `check:bundles` passed and the advisor bundle-privacy check passed.

**Proxy:** `scratchpad/tam/e2/proxy.js` on :3400 stands in for nginx. It routes `/api/` to the backend and everything else to Next. Like `chaseupside-proxy.conf`, it **replaces** `X-Real-IP` and **appends** to `X-Forwarded-For`.

**Board:** `exports/latest/dynasty_data_2026-10-20.json`, the dynasty_main rosters:
- 913 assets in total: 697 players and 216 picks;
- 858 assets are `evaluable`;
- ground truth for scoring the attacks is `rankDerivedValue` from authenticated `/api/data`. It was used only to score results, never by the attacker.

**Signals:** `signalsSf` is `not_provisioned` locally. The local board therefore carries no Signals vote, and the private-delta scenario in §3 is a stand-in [verified].

**Probe scripts:** `scratchpad/tam/e2/p1_collect.py` … `p12_timing.py`, plus `zz-e2-privacy.spec.js`. Raw outputs are `recon_*.json/log` and `timing_*.json`.

## 1. Directive §9 checklist

| §9 item | Result | Evidence |
|---|---|---|
| No raw values / proprietary scores in any response, from any perspective | **PASS** | 212 successful analyze bodies plus every error body, across 2/3/4-team trades, scanned by an independent scanner (not Lane C's own assert). 0 floats; every integer sits on an allowlisted key (`rosterId(s)`, `from`/`to`, `teamCount`, …); the key set holds no value-like key. 28 distinct strings were seen, all fixed copy. [measured, `p3_analyze.py`] |
| No leak from alternate perspectives | **PASS** | Perspective, reversed team order and shuffled asset order give byte-identical bodies apart from `perspectiveRosterId`: 0 failures in 212 pairs [measured]. All teams arrive in one response; switching perspective in the browser sends 0 extra requests [measured, browser]. |
| No hidden value arrays in serialized page data | **PASS** | `/league`, `/league?tab=trade-advisor`, `…&team=1`, `?tab=overview` and `/` scanned: HTML + `self.__next_f` flight data, plus the cached RSC payloads (`?_rsc=`, `team=9&step=result`). Hits for 30 value/model key patterns: 0. A player's own canonical value within 160 characters of their name: 0 occurrences. [measured, `p7_pagescan.py`] |
| No model numbers in bundled JS | **PASS for advisor code; PRE-EXISTING sitewide exception** | Advisor chunks (`9899.*`, `app/league/page-*`): no geom/fairness/source/value identifiers. Their only `0.78` hits are `fontSize:"0.78rem"`. No `.map` under `.next/static`, and `/_next/static/…js.map` returns 404 [measured]. **But** app-shell chunks `6023-*` and `7372-*` load on **every** page, `/login` and `/league` included. They contain the package model (`GEOM_Q078_V1`, `q:.78`, the geom utility), `rankDerivedValue` readers and the `RANKING_SOURCES` registry. The identical chunk hash ships in Lane A's build, so this comes from main [measured, `p8_bundles.py`]. The repo is public, so the marginal disclosure is nil. It still breaks the literal §9 wording, and it is not advisor-introduced. → follow-up F-3. |
| No sensitive browser storage | **PASS** | After a live 3-team flow: `localStorage` {}; IndexedDB none; no cookies. `sessionStorage['brisketAdvisor:v2']` holds the ledger (ids, labels, from/to) and the public result. Its numeric leaves are only `from`/`to`/`rosterId`/`slots`/`teamCount`/`perspectiveRosterId` [measured, `zz-e2-privacy.spec.js`]. |
| No cache holding sensitive personalized analysis | **PASS, with a LOW note** | Every advisor response is `Cache-Control: no-store` [measured]. The service worker skips POST, so analyze results are never stored. **However**, `sw.js` network-first stores the advisor **GET** lists (`/teams/{id}/assets`) in `chaseupside-v9-public-league` despite `no-store`. Three entries were found in CacheStorage. They are value-free identity lists, but they persist at rest across sessions and can be replayed offline. The advisor e2e spec runs with `serviceWorkers: "block"`, so this path is untested → F-2. |
| No private decision logs / writes from the public path | **PASS** | Covered by Lane C tests with writers patched to raise (re-run green, see §6). Nothing here contradicted them. |
| No debug fields | **PASS** | Outbound models use `extra="forbid"`. 30 malformed bodies and 5 content types give no extra keys. `extra_field` (`debug`) in a request → 400 `schema` [measured, `p5_fuzz.py`]. |
| No leaks via error messages | **PASS** | 30 bodies (invalid/empty/NaN JSON, 5,000-deep nesting, huge ints, unicode and script ids, foreign-league picks, 130 legs, not-owned, gift, self-destination …): every advisor error is fixed copy, `no-store`, and never 422/500 or a stack trace. Echoes are limited to request-supplied ids matching the inbound pattern; a 409 never names the real owner [measured]. One unmatched `/api/public/league/...` path returns FastAPI's default `{"detail":"Not Found"}`. That is not advisor copy and carries nothing. |
| No authenticated API access via public endpoints | **PASS** | Anonymous `/api/trade/analyze(-multi)`, `/simulate`, `/suggestions`, `/api/data`, `/api/dynasty-data`, `/api/gameplan`, `/api/rankings/overrides`, and a `/api/public/league/../../trade/…` traversal → all 401. A valid session cookie changes nothing in any advisor body; there is no `Set-Cookie`. `leagueKey=dynasty_new` while signed in → 404 `league_not_public`. A foreign-origin CORS preflight → 405 with no `Access-Control-*` headers [measured, `p9_auth.py`]. |
| Value-ordering exposure (C1) | **CLOSED** | `value_desc`, `value_asc` and `alpha` → 400 `unsupported_sort`. The served order equals a pure (side, position, label, id) sort for all 12 teams. Within a position, listed-before vs higher-value is 1,272 vs 1,295 pairs (τ = −0.009, i.e. no value signal) [measured, `p2_order.py`]. |
| Client-IP validation | **PASS (code); [ops] for the network** | Non-loopback peer (192.0.2.2) sending 45 distinct spoofed `X-Real-IP`: headers ignored, keyed on the peer, 429 at request 41. Loopback (nginx position): honoured. IPv6: 45 addresses in one /64 share one bucket (429 at 41). `::ffff:a.b.c.d` and `a.b.c.d` share a bucket. Garbage headers fall back to the peer [measured, `p10_limits.py`]. `server.py` still hardcodes `HOST = "0.0.0.0"` on this head [verified]. Direct `:8000` serves `/docs`, `/redoc` and `/openapi.json` (148 KB route schema) [measured] → D-net unit. |
| Rate limits / neighbourhood / global ceiling | **PASS as configured; DoS residual** | Per key 40/600 s → 429 at 41, `Retry-After: 15`. /24 and IPv6 /48: 429 at 201. /16 region daily: 429 at 2,000 (one token had been spent earlier from that /16). **Global ceiling:** 1,200 cheap `{}` posts from distinct /16s hit 429 at request 417, once cumulative hourly traffic reached about 3,000. A brand-new legitimate client then got 429. The flood took 4.7 s [measured]. |
| Request bounds / body caps | **PASS** | `Content-Length` > 16 KiB → 413. A chunked body with no length → 413 mid-stream. A raw-socket chunked 30 KB body → 413. Non-JSON content types → 415. `APPLICATION/JSON` is accepted (case-insensitive). Over 128 legs → 400 `too_many_assets`. Over 4 teams → 400 `schema` [measured]. |
| Response-timing protection | **PASS once a floor is set; the floor is not set** | §4. |
| Reconstruction through repeated requests | **Residual, quantified** | §3. |
| Source permission (OD-3 / OD-4) | **BLOCKING — no record exists** | §5. |

## 2. Findings ranked (new in this lane)

1. **F-1 MEDIUM, accepted-residual class: hidden per-asset data-quality state is recoverable cheaply.**
   - Quarantined or stale-source values make the engine gap `quarantined_values` / `stale_values`. Publicly that becomes `evaluation_unavailable` with **no asset ids**, and `evaluable` stays `true` (spec §4.2's accepted residual) [verified, `team_verdicts._GAP_REASON`].
   - Adaptive group testing over analyze recovers the **complete** hidden set: **19 of 642** evaluable rostered players in **180 queries**. That is 12 to find clean anchors plus binary splitting of whole-roster packages, against 630 for exhaustive 1-for-1. It agreed exactly with the exhaustive answer [measured, `p11_grouptest.py`].
   - 7 of the 19 are `quarantined: true` in `/api/data` [measured]. The other 12 are inferred to be `stale_values`, the only other gate that maps to `evaluation_unavailable` [inferred].
   - 180 queries fit inside one residential IP's daily budget (400). This is the cheapest confidential-classification channel left. It reveals model internals ("this value is distrusted"), not values.
   - Options:
     - (a) the owner explicitly accepts it as the spec §4.2 residual;
     - (b) fold quarantine/staleness into `evaluable`. That is honest UX, but discloses the same set for free;
     - there is no option that both keeps UNABLE honest and hides the set.
   - Owner decision.
2. **F-2 LOW:** the service worker stores advisor GET lists at rest despite `no-store` (§1). Fix: add `/api/public/league/trade-advisor/` to `NEVER_CACHE` in `frontend/public/sw.js` and bump `CACHE_VERSION`. Add an SW-allowed e2e assertion.
3. **F-3 LOW, pre-existing on main, not advisor:** app-shell chunks on every public page ship the package model constants and the source registry (§1). The repo is public, so this is a literal-§9 issue only. Owner call, or a bundle-split follow-up.
4. **F-4 LOW: global ceiling as a cheap DoS lever.**
   - Invalid `{}` bodies are charged (correct: charging comes before validation), so draining 3,000/h costs the attacker no server CPU and locks out every user.
   - Each /16 (IPv6 /32) region is capped at 2,000/day, so a sustained lockout needs about 36 regions a day [inferred]. That is cheap with a residential proxy pool.
   - This is a design tradeoff (the ceiling protects CPU), recorded in OD-8's limiter priors. Pair it with M10 alerting.
5. **F-5 LOW: two limiters with different 429 shapes.**
   - The generic public limiter in `_private_api_gate` (60/min and 1,000/h per **exact** IP) runs before the advisor limiter.
   - Its 429 copy ("Too many requests — slow down.") is not advisor fixed copy, and it is not floored. It carries no evaluation information.
   - On the GET lists it is the only meter, and keying on the exact IPv6 address means one /64 reads lists without limit. Measured: 120 GETs from 120 addresses in one /64 → all 200, at about 5 ms each.
   - The lists are value-free, so this is availability only.
6. **F-6 INFO:** response size differs by outcome (gzip on). An on-path TLS observer could guess FAIR or NOT FAIR for a user's own query. Negligible.

Re-verified and still holding: M1 (asset-only market fairness: Team Context does not reach the public path), M2 (no value order), M3 (coarse output only), M5 (send-and-receive rejects gifts), M6 (all teams in one response), M8 (charge before validation), M11 (no analyze caching), M12 (fixed vocabulary).

## 3. Reconstruction attacks (privacy.md §2.4) executed against the local stack

**Method.**
- `p4_recon.py` ports `recon/sim_rounds.py` onto the **real** `POST /analyze` over HTTP.
- 2-team trades only; real rostered assets only. Target x goes from A to B; B returns a ladder rung (1–2 assets).
- The attacker knows q, the band and the package code (all public in git) and bisects to the upper FAIR edge. Each round it solves jointly by weighted least squares with a prior. Three partner teams per target per round.
- A counted pre-screen (654 queries) first removes the 19 unprobeable assets from F-1.
- The client IP was rotated per request inside 100.64/10 and limits were lifted (:8201), so these are **query counts**, not wall-clock times. Wall-clock under the real limiter is computed below.

| Scenario (attacker prior) | Rounds | Cumulative queries | Prior → estimate RMSE | Median abs error | Median rel error | Pairwise order accuracy | Private-Δ correlation |
|---|---|---|---|---|---|---|---|
| ±5% drift (git board) | 1 | 6,939 | 137.6 → 106.0 | 57.5 | 3.16% → 2.41% | 0.972 | — |
| | 2 | 13,241 | → 84.1 | 49.2 | → 1.87% | 0.978 | — |
| | 3 | **19,714** | → **78.8** | **44.5** | → **1.82%** | 0.979 | — |
| exact git board + unknown private Δ (σ = 25) | 1 | 7,691 | 24.1 → 22.5 | 14.0 | 0.68% → 0.64% | 0.991 | 0.361 |
| | 2 | 14,805 | → 22.1 | 13.5 | → 0.62% | 0.991 | 0.400 |
| | 3 | **21,988** | → **21.8** | **13.6** | → **0.61%** | 0.992 | **0.432** |
| hidden quarantine/stale set (F-1) | — | **180** | 19 of 19 recovered exactly | | | | |

Assets in scope: 642 evaluable rostered players (623 after the screen removes the 19).

**Reading.**
- On the real board and the real engine, the attack recovers **roughly half** of what the stand-in simulation predicted:
  - the simulation reached 1.06% median error and Δ-correlation 0.74 at about 30–33k queries;
  - here, 1.82% and 0.43 at about 20–22k queries.
- The reason [inferred]: real rosters give fewer ladders that start inside the band, so there are 2,978 boundary equations from 19.7k queries.
- Precision still improves monotonically with queries. As privacy.md says, this is a bound on effort, not a proof of safety: a smarter attacker does better.

**Wall-clock under the committed limiter priors** [inferred from the measured counts]:

| Attacker resources | ±5% scenario (19.7k queries) | Quarantine set (180 queries) |
|---|---|---|
| One IPv4 (400/day) | ≈ 49 days | **< 1 day** (≈ 45 min at the 40/10 min burst) |
| One /24 (1,000/day) | ≈ 20 days | |
| One /16 (2,000/day) | ≈ 10 days | |
| ~10 regions | ≈ 1 day | |
| Unlimited address space | ≥ 6.6 h at the 3,000/h global ceiling, with every legitimate user locked out (F-4) | |

**Effect of the mitigations.**
- **M2** removes the free channel C1 (about 3.1k bits per generation): **verified closed**.
- **M5** removes the absolute-anchor probes: gift trades → 400 `one_sided_trade` [measured].
- **M6** makes perspective switching cost 0 extra bits [measured].
- **The limiter** turns the ±5% attack into a slow and loud campaign.
- **Noise:** none applied, and none should be (privacy.md §2.5).
- **Nothing** prevents F-1 at 180 queries, or the slow value refinement. Both need explicit owner acceptance.
- **Not exercisable locally:** cross-generation differencing (re-probing the same boundary after a board refresh to learn which way a value moved), because the local board never refreshes. The opaque `generation` and `snapshotChanged` tell an attacker when to re-probe [inferred].

## 4. Timing channel (C7) and the floor

`p12_timing.py`, sequential, roughly 550 requests per run. AUC: 0.5 = indistinguishable, 1.0 = perfectly separable.

| Comparison | No floor (:8201) | Floor 50/65/110 ms (:8202) |
|---|---|---|
| 2-team FAIR vs NOT FAIR | 0.486 | 0.498 |
| 2-team decided vs UNABLE | 0.443 | 0.460 |
| 2-team decided vs any 4xx (validation, 409) | **0.996** | **0.445** |
| p50, 2-team decided | 25 ms | 54 ms |
| p50, 3-team decided | 35 ms | 69 ms |
| p50, 4-team decided | 46 ms | 114 ms |
| p50, schema error | 2.7 ms | 113.7 ms (table maximum, by design) |

- **Without a floor:** the outcome (FAIR, NOT FAIR or UNABLE) is **not** visible in timing, because all three run the same market-fairness path. Only early exits separate, and their bodies already state them. So the leak today is small. The floor matters for defence in depth and for future code paths.
- **With a floor:** the early-exit separation collapses (0.996 → 0.445). It works in `finally` for 400, 409, 413, 415 and 429, as Lane C claims [measured].
- **Tail overshoot:** p99 reached 212–234 ms on some 2- and 4-team requests. Those overshoots are visible, but they track load and garbage collection, not outcome.
- **The production floor must come from a measurement on the box** of the worst-case market-fairness p99 under realistic load (directive §13). The local values above are illustrative only. `responseFloorMs` stays null, so the launch gate stays closed [verified].

## 5. Source-permission status per source (OD-3 / OD-4)

- **No record exists:**
  - `config/trade/public_advisor.json::approvedSourcePermissionRecord` is null;
  - the repo holds no "public derived use" permission record;
  - `C_SERIES_SCOPE_MANIFEST.md` `F-EXT-02` still says IDPTC has "no record of any kind", which is stale against the 2026-09-25 attestation [verified on this head].
- Every voting source reaches the public verdict through the one canonical blend. Excluding any of them would break public/private parity (directive §10). So each answer is either **confirm public derived use** or **do not launch**.

| Provider (registry keys on this head; 27 registered) | Role in the public verdict | Record | Status |
|---|---|---|---|
| Sleeper (rosters, picks, ownership) | asset universe and ownership only; no value | public `/league` already shows rosters; 09-25 attestation | **Permitted** (same use as the existing League Hub); non-commercial status is the owner's to confirm |
| Signals (`signalsSf` votes; `signalsIdpDl/Lb/Db` held by `PRIVATE_SOURCE_VOTE_HOLDS`) | one family-capped offense vote | scope recorded up to "authenticated Calculator displays" | **Unknown: OD-3a**. Owner's words ("how I see fit") suggest a cheap confirmation. Production-only, so it is the main marginal secret (§3 σ=25 stand-in: 0.43 correlation at 22k queries) |
| KeepTradeCut (`ktcCrowdSfTep`, `ktcTradesSfTep`; pick market; `ktcCrowdTradesSfTep` non-voting) | two votes plus one of two pick providers | ingestion-only wording | **Unknown: OD-3b** |
| IDP Trade Calculator (`idpTradeCalc`) | IDP anchor, second pick provider | conflicting (F-EXT-02 vs 09-25) | **Unknown: OD-3c**, plus record repair |
| DLF (`dlfSf`, `dlfRookieSf`, `dlfValuesSfTep`, `dlfIdp`, `dlfRookieIdp`), DraftSharks (`draftSharks`, `draftSharksIdp`), IDP Show (`idpShowCombined`), Flock (`flockFantasySf`, `flockFantasySfRookies`) | votes | 09-25 attestation (ingestion and project use) | **Unknown: OD-3d**. Raw boards are already committed to the public repo (pre-existing `F-EXT-03`) |
| FantasyCalc, Dynasty Nerds, OTC, Fantasy Navigator, PFK, Dynasty Daddy, FantasyPros (SF, IDP, Fitzmaurice), Yahoo/Boone | votes | 09-25 attestation | **Unknown: OD-3d** |
| OD-4 (posture / Team Context exposure) | — | — | **Moot for the public path.** Market-fairness mode reads no posture, projections, capacity or forced drops (Lane C invariance tests green, §6). A signed-in cookie changes no body [measured]. |

## 6. Corroborating runs

- **Lane C test suites re-run green on this head:** `pytest tests/api/test_public_trade_advisor_{privacy,validation,contract}.py tests/api/test_client_ip_trust.py tests/api/test_cache_control_privacy.py`: **166 passed**.
- **Build:** `npm run build:nocheck` OK. `check-bundle-sizes`: 17 of 17 under budget, `/league/page` 47.6 of 50 KB. `check-public-bundle-privacy`: PASS, lazy advisor 9.6 of 11 KB, team step 9.4 of 10 KB.

## 7. Ops items (repo cannot answer)

These remain as listed in privacy.md §3.2:
- `ss -ltnp` for :8000 and :3000;
- external reachability of :8000, :3000 and `/openapi.json`;
- firewall rules;
- rendered nginx equals the repo templates;
- no CDN in front;
- `RATE_LIMIT_TRUSTED_PROXIES` unset or loopback-only, and `RATE_LIMIT_BYPASS_IPS` (it also governs SSR's loopback reads through the generic limiter);
- IPv6 `$remote_addr`;
- the D-net loopback-bind unit;
- the on-box measurement of the production-only (Signals) delta;
- the production `responseFloorMs`.

## Completion result

- **STATUS:** DONE for this read-only verification unit. The launch-blocking owner decisions and ops items remain open.
- **ACCEPTANCE:** every §9 item was checked on a stack built from #1866's head with the flag on locally (§1). The privacy.md reconstruction attacks were executed over HTTP, with query counts, recovery and mitigation effect (§3–§4). Source status is given per source (§5).
- **EVIDENCE:** §0–§6. Scripts and raw outputs are in `scratchpad/tam/e2/`.
- **UNRESOLVED:**
  - OD-3a–d (no permission record);
  - owner acceptance of F-1 (180-query quarantine/stale recovery) and of slow value refinement (±5% → 1.8% median error at about 20k queries);
  - F-2 (service-worker caching of advisor GETs);
  - F-3 (pre-existing app-shell model constants);
  - F-4 / F-5 limiter tradeoffs (OD-8);
  - production floor not measured;
  - every §7 ops check;
  - cross-generation differencing not exercisable locally;
  - Signals delta measured only as a stand-in.
- **BLOCKERS:** owner decisions (OD-3, residual acceptance, OD-8) and production-box access.
- **NEXT_ACTION:**
  - Lane D: the F-2 `NEVER_CACHE` fix, plus an SW-allowed e2e assertion.
  - Coordination: put OD-3a–d plus the F-1 and reconstruction residuals to the owner in one message.
  - Ops: the §7 checks and an on-box floor measurement.
