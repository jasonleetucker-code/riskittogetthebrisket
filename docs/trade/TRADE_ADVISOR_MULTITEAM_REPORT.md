# Brisket Trade Advisor + multi-team trades: implementation report (directive §17 A–I)

- **Date:** 2026-10-20.
- **Authority:** owner directive 2026-10-20, *Complete Brisket Trade Advisor and implement full
  multi-team trade support*, recorded verbatim at
  [`docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md`](../owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md),
  including its superseding **fairness-only amendment** for the public product. CLAUDE.md
  invariants apply.
- **Engineering contract:** [`docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`](NTEAM_TRADE_ENGINE_SPEC.md).
- **What this document is:** an evidence report. It authorizes nothing. Nothing described here
  is merged, deployed or enabled. Both new flags (`trade_multi_team_analysis` and
  `brisket_trade_advisor`) are `False` in the registry, and the public launch gate is closed in
  the committed config.
- **Agent-OS-Receipt:** `cdca1dca8385f70c0989302dece8d1bd4ce4843c`

---

## I. Launch recommendation (exactly one)

> **BLOCKED — SPECIFIC UNRESOLVED ISSUE**
>
> **The public launch gate cannot open.** Two owner-reserved inputs it requires do not exist:
>
> 1. **No approved fairness threshold version.** `fairness_bands_v1` is `PROVISIONAL`. The
>    threshold research (below) finds it unsuitable as the fixed public FAIR / NOT FAIR
>    threshold in its current form (OD-F1–F6).
> 2. **No source-permission record** for public derived use of the voting sources (OD-3a–d).
>    Directive §9 says: do not launch until OD-3 is resolved.
>
> **Separately, the engineering gates still fail,** so the stack is not yet ready for the
> owner's approval review:
>
> - **CI:** all four PRs are red or unmergeable (section H).
> - **Accessibility (gate 8):** the public focus loss after edit / remove / reset is fixed on
>   #1866 (Lane D round 2, below); mobile-390/430 (WebKit) are still not run locally.
> - **Abuse controls (gate 7):** there is no admission or concurrency bound on either analyze
>   route.
> - **Engine snapshot consistency:** the scarcity bundle is read once per team instead of once
>   per request.

Why not the other two options:

- **Not READY FOR PUBLIC LAUNCH APPROVAL.** Launch gates 6, 7, 8, 9 and 10 are not met
  (section *Launch gate checklist*).
- **Not IMPLEMENTED — VERIFICATION REMAINING.** Several items need *code* changes, not just
  verification: the focus fix, the per-request scarcity read, the decision-path coercion, the
  E2E skip ceiling, the existing `trade-tcd2` spec regression, the admission bound and the
  service-worker cache prefix. The threshold and source-permission questions need the owner, not
  more testing.

What *is* demonstrated:

- Genuine 2-, 3- and 4-team evaluation on both surfaces. 3- and 4-team trades are never answered
  "unsupported".
- Byte-level parity between the engine, the private route and the existing 2-team route.
- The public result is an exact value-free reduction of the private fairness.
- Real-browser desktop and mobile flows on both surfaces.

---

## A. Current-state reconciliation: built, reused, new

Read-only reconciliation was done first, against `origin/main` `1511ca1d08` (the scratch
reconciliations `engine_state.md` / `ui_state.md` are summarised here).

**Starting point:**

- **#1853** (B0 shared-engine repairs) was already merged via release train 15 (#1876,
  `fd798c3ec0`). It stays authoritative.
- **#1861** (public backend) and **#1866** (League Hub frontend) were open. #1866 was 167
  commits behind `main`.

**What already existed:**

- **The Python stack was already per-team.** `simulate_trade` → `analyze_trade` →
  `trade_decision.decide` take one team's sending / receiving lists and never read a
  counterparty.
- **The active package model generalizes exactly.** Under `geom_q078_v1`,
  `adjusted_pair_totals(G_i, R_i)` gives `recv_adj − send_adj = U(R_i) − U(G_i)`.
- **Defect found:** the browser's 3+-team meter priced each side against the *union* of every
  other side. That could contradict the server.

| Area | Reused (unchanged owner) | Built new | Deleted / superseded |
|---|---|---|---|
| Valuation | `rankDerivedValue` (one value per asset), identity-first pick resolution (`src/identity/picks.py`, `src/api/pick_value_resolution.py`) | none | none |
| Package VA | `package_model.adjusted_pair_totals` / `geom_q078_v1`, q = 0.78; LP_150 untouched | none | none |
| Fairness | `fairness_bands.classify` + `fairness_bands_v1` (unchanged, still PROVISIONAL) | `team_verdicts.team_fairness` (reads the band the equity lens already produced; never recomputes) | #1861's own fairness / `multi_side.py` plan (SD-10) |
| Per-team decision | `analyze_service.simulate_for_team` / `analyze_for_team`, `trade_decision.decide` | `trade_decision.asset_evidence_gaps` split, plus a new `ownership_unverifiable` gate (only the ledger can fire it) | `trade_decision` PUBLIC section (Lane C) |
| Ownership / freshness | `src/api/roster_freshness.py` (single owner) | `src/trade/trade_ledger.py`: one snapshot per request, canonical asset ids, ordered validation with stable reason codes | #1861's private `roster_freshness` copy and `validate_trade` |
| N-team composition | none | `analyze_service.analyze_trade_n` (modes `team_context` / `asset_only` / `market_fairness`), `POST /api/trade/analyze-multi`, `config/trade/multi_team.json` | none |
| Private UI | War Room detail sections (exported and reused) | `MultiTeamWarRoom`, `lib/trade-multi-team.js`, `lib/trade-team-binding.js`, `packageAdjustedPairTotals` | `computeMultiSideAdjustments` (union-collapse defect) |
| Public backend | B0-h client identity, limiter, body cap, `assert_public_payload_safe` | the reducer in `src/trade/public_advisor.py`, `assert_advisor_payload_value_free`, launch gate, response floor in `finally`, perspective-free single-flight | value sorts, `multi_team_unsupported`, the `roster_limit` public reason |
| Public frontend | ds Tabs / Select, League Hub shell, bundle-privacy script | 2/3/4-team builder, destination select, team-by-team review, overall + per-team results, perspective switch with no new request | value sort, accept / decline wording |

The records committed with the spec are:

- the directive, verbatim;
- an `OWNER_REQUESTED_TODO` intake entry;
- an `EXECUTION_PLAN` §0 authorization (implementation and validation, **not activation**);
- `WORK_CLAIMS` rows for lanes A–E.

## B. Shared multi-team engine: architecture, routing semantics, simultaneous evaluation

The full contract is in [`NTEAM_TRADE_ENGINE_SPEC.md`](NTEAM_TRADE_ENGINE_SPEC.md): §2 covers the
ledger and §3 the engine. §12 and §13 hold the implementation notes from Lanes A and B. The
engine is PR #1882.

### Request ledger

- A request is a set of directed legs `{assetId, from, to}`.
- **Assets** are canonical: `p:<sleeperId>` for players, `pick:<leagueKey>:<season>:r<N>:o<rid>`
  for picks.
- **Ordering:** teams are sorted by rosterId and legs by asset id. Request order therefore cannot
  change a result. This is checked over all 24 orderings of a real 4-team trade.

### Validation

`trade_ledger.validate_ledger` checks the ledger in a fixed order and returns stable codes:

- `too_few_teams` / `duplicate_team` / `too_many_teams`
- `team_not_in_league`
- `unknown_asset`
- `duplicate_asset`
- `invalid_destination` / `destination_is_origin`
- `idle_team`
- `asset_not_owned` (409, never naming the real holder)

### Ownership

- **Who holds an asset** is read from the snapshot only: `sleeper.teams[].playerIds` and
  `pickDetails[].assetId`. No request field can override it.
- **Stale or unknown rosters, a player on two rosters, or a pick with unknown ownership** make
  the asset `ownership_unverifiable`. That gives UNABLE / NOT_ENOUGH_EVIDENCE. Ownership is
  never guessed (SD-7).

### Simultaneous evaluation

- **Per team:** each team *i* is simulated once from the one snapshot, with `G_i` = every leg it
  sends and `R_i` = every leg routed to it.
- **No chains:** an asset cannot move twice, so chains are impossible.
- **Locality holds:** a team's result never depends on legs that don't touch it. This was tested
  by adding a disjoint exchange at N = 5.

**VA is applied once per team, over its full package. The trade is never split into 2-team
pieces.** Real board, S06:

| Team | Engine gap (full package) | Sum of pairwise sub-trade gaps |
|---|---:|---:|
| Jason | −5,762 | −6,415 |
| Collin | +335 | +460 |
| Roy | +5,427 | +5,955 |

### Conservation vs utility

- **Raw routed value is conserved** (`summary.conservation.balanced`).
- **Per-team adjusted gaps and roster utility need not sum to zero.** For example, S04 sums to
  +108 and S05 to +245.

### Per-team outputs

- **Decision:** one authoritative `decide()` result per team (YES / NO / NO_TOO_CLOSE /
  NOT_ENOUGH_EVIDENCE).
- **Category:** the 5-level private category plus unavailable.
- **Market fairness:** FAIR / NOT_FAIR / UNABLE.
- **Overall fairness:** a three-valued (Kleene) AND. Any NOT_FAIR → NOT FAIR; otherwise any
  UNABLE → UNABLE; otherwise FAIR.
- **All-team summary:** a projection of the per-team decisions, never a second verdict.

### Guards

- The N-team route refuses unless the package model is `geom_q078_v1` with a readable config.
- A result that does not reconcile with the ledger raises and is never published.
- `market_fairness` mode writes nothing.

## C. Private calculator: 2/3/4-team analysis with team numbers and final recommendations (PR #1883)

### Flag

With `trade_multi_team_analysis` ON, `/trade` sends 3- and 4-team trades to
`/api/trade/analyze-multi`. With the flag OFF, the page is exactly as today. The 2-team path is
unchanged and still uses `/api/trade/analyze`.

### Building a trade

- Each side card is bound to a league team, either by explicit choice or by ownership of every
  asset on it. Display names never decide the binding.
- Destinations are set per asset.
- The client refuses before sending, and names each problem: an unbound side, the same team on
  two sides, a generic market pick, a player with no id, a copied asset, a missing destination,
  an unheld asset, an idle side, or an empty trade.

### War Room

`MultiTeamWarRoom` shows:

- **An every-team summary:** decision, market fairness, "all teams fair?" and raw conservation.
- **One perspective tab per team,** all from a single response.
- **Per team:**
  - decision and category, labelled separately from market fairness (spec C4);
  - sends and receives, with destinations and server values;
  - raw / VA / adjusted totals;
  - roster fit and forced drops;
  - lineup impact, team direction, confidence and missing evidence.

### Behaviour

- **Edits:** an edit hides the old answer and re-asks.
- **Stale responses:** a response is shown only when it matches the exact ledger that was sent.
- **Preliminary meter:** the meter is labelled "Preliminary". Once the War Room answers, it shows
  the War Room's final words instead (SD-9).
- **Balancing suggestions:** off at N ≥ 3 (SD-13).

### Meter fix evidence

The before/after table for the 3+-team meter correctness fix is in
[`advisor_evidence/private_meter_before_after.txt`](advisor_evidence/private_meter_before_after.txt).
For example, in the spec I14 one-to-many case, team C went from a phantom −1,995 to the correct
+500.

### Screenshots

The private-surface screenshots are **not** copied into this public repository. They show the
private calculator's numeric output and a real team's competitive-posture classification, which
the §5 public/private boundary keeps private. They remain in the session scratchpad:

- `screens/private/` (8 files);
- `screens/e2e/*private*` (keyboard flows, 2/3/4 teams, desktop and mobile).

The private numeric results for the §17 G trades are reproduced in section G instead. Those
numbers derive only from the tracked archive board (`exports/archive/…`), with no box-local
source.

## D. Public Advisor flow, value-free (PRs #1861 + #1866)

The flow (League Hub, no login) is:

1. Choose your team.
2. Choose 2, 3 or 4 teams. The cap comes from the server's `limits.maxTeams`.
3. Choose the partner teams.
4. Add the real rostered players and owned picks. Lists are in identity order
   (`position_alpha`), never value order. Search and filters only remove rows.
5. Assign a destination to each asset.
6. Review team by team, with → / ← routing labels.
7. Analyze.
8. Read the overall result: **FAIR TRADE / NOT FAIR / UNABLE TO DETERMINE**.
9. Read the "Result for each team" list, with per-team labels such as "FAIR FOR THIS TEAM"
   (SD-14).
10. Switch perspective. This reads other rows of the same response and sends no request.
11. Edit, start a new trade, or start over.

For 3+ teams the copy states that "a trade with more than two teams is fair only when it is fair
for every team". There is no accept / decline / approve wording anywhere.

**Server contract.** The reducer sees only, per team: `(rosterId, state, reasonCode, own
unavailable asset ids)`, plus the overall state and the legs. Every body then passes, in order:

- strict Pydantic models (`extra=forbid`, `StrictInt`, no floats);
- `assert_public_payload_safe`;
- `assert_advisor_payload_value_free` (integer-key allowlist, a key blocklist, fixed copy only).

All responses are `no-store`.

Screenshots (value-free; real local stack; launch gate opened in-process only):

| | 2 teams | 3 teams | 4 teams |
|---|---|---|---|
| desktop review | [png](advisor_evidence/screens/public/desktop-1366-2team-1-review.png) | [png](advisor_evidence/screens/public/desktop-1366-3team-1-review.png) | [png](advisor_evidence/screens/public/desktop-1366-4team-1-review.png) |
| desktop result | [png](advisor_evidence/screens/public/desktop-1366-2team-2-result.png) | [png](advisor_evidence/screens/public/desktop-1366-3team-2-result.png) | [png](advisor_evidence/screens/public/desktop-1366-4team-2-result.png) |
| desktop perspective | [png](advisor_evidence/screens/public/desktop-1366-2team-3-perspective.png) | [png](advisor_evidence/screens/public/desktop-1366-3team-3-perspective.png) | [png](advisor_evidence/screens/public/desktop-1366-4team-3-perspective.png) |
| phone review | [png](advisor_evidence/screens/public/mobile-chromium-2team-1-review.png) | [png](advisor_evidence/screens/public/mobile-chromium-3team-1-review.png) | [png](advisor_evidence/screens/public/mobile-chromium-4team-1-review.png) |
| phone result | [png](advisor_evidence/screens/public/mobile-chromium-2team-2-result.png) | [png](advisor_evidence/screens/public/mobile-chromium-3team-2-result.png) | [png](advisor_evidence/screens/public/mobile-chromium-4team-2-result.png) |
| phone perspective | [png](advisor_evidence/screens/public/mobile-chromium-2team-3-perspective.png) | [png](advisor_evidence/screens/public/mobile-chromium-3team-3-perspective.png) | [png](advisor_evidence/screens/public/mobile-chromium-4team-3-perspective.png) |

Keyboard-only E2E captures (public):

- per-team result enums: `*-05-result.json`;
- error recovery: network failure, 500, recovered, asset-list error;
- a stale-roster run.

All are in [`advisor_evidence/screens/public-e2e/`](advisor_evidence/screens/public-e2e/).

Every live public run on the local board returned NOT_FAIR, or UNABLE under stale rosters. No
live FAIR verdict was observed in the browser. FAIR rendering is covered by Lane D's mocked
fixtures. Lane E-1 observed FAIR TRADE at the API level for S09, S22 and S23.

## E. Parity report

Full report: [`advisor_evidence/PARITY_REPORT.md`](advisor_evidence/PARITY_REPORT.md) (Lane E-1).
It was run on the real archived board (`dynasty_export_20261020_052241.zip`, real `dynasty_main`
rosters and owned picks).

- **Deterministic §11 matrix:** 26 structures and 11 refused-request cases. **2,082 / 2,082
  checks passed.**
- **Seeded random sweep:** 36 real-board ledgers. **892 / 892 checks passed.**
- **vitest UI parity:** 61 passed. A negative control (server totals +1) fails all 25 math
  cases.

What was proven, all exact:

- **Private route = engine:** byte-identical at N = 2, 3 and 4, in both private modes.
- **2-team path:** the generalized engine at N = 2 is byte-equal to the existing
  `/api/trade/analyze` route, driven with the War Room's request shape.
- **Public = private:** per-team result, reason code and overall equal the private fairness. The
  public body is byte-identical from every perspective.
- **Python/JS:** the JS per-team package math equals the server's totals and band.
- **Invariances:**
  - team / asset reorder;
  - renaming teams;
  - no double transfer;
  - the owner cannot be overridden;
  - ledger reconciliation and conservation;
  - simultaneous updates and locality;
  - one value per asset, with missing → `null`, never 0;
  - every decision traces to its receipt;
  - a mid-session board change is detected;
  - stale rosters fail closed.

## F. Test evidence

| Kind | Result | Where |
|---|---|---|
| Engine regression (Lane A) | `tests/trade` + `tests/api` not-livedata: 9,634 passed. 3 failures were fixed; the affected files re-run: 152 passed | PR #1882 |
| Property / invariant (I1–I20) | synthetic and real boards; I14 worked example exact | PR #1882, `tests/trade/test_analyze_multi_team.py`, `tests/fixtures/multi_team/` |
| Python↔JS parity fixture | 8 multi-team cases, checked by both pytest and vitest | `tests/fixtures/multi_team_trade_parity_cases.json` |
| Cross-surface gap tests (E-1) | 7 new tests, plus the route tests: 26 passed | `tests/api/test_trade_analyze_multi_cross_surface.py` (#1882 @ `52b2aef95a`) — **one is flaky under xdist; see R1-2** |
| Private UI (Lane B) | vitest 4,662 / 4,662; Playwright desktop-1366 + mobile-chromium 8 / 8; axe clean | PR #1883 |
| Public backend (Lane C) | 4,998 passed (targeted); `tests/api` 5,148 passed (1 doc-count failure, fixed) | PR #1861 |
| Public frontend (Lane D) | vitest 4,800 / 4,800; Playwright 116 passed (repeat-each = 2, live 2/3/4-team flows, axe clean) | PR #1866 |
| Combined tree (integration review) | D + B + A + `main` 675ebc751f merge cleanly. Build OK; bundles OK (/trade 91.7 / 93 KB, /league 47.6 / 50 KB); public bundle privacy OK; vitest 4,834 / 4,834; pytest 311 passed | integration reviewer |
| Privacy / abuse (E-2) | §9 checklist passes for values, perspective, page data, storage, errors, auth isolation, client IP, limits and body caps. Gates failed: OD-3, F-1, F-2, floor unset | [`PRIVACY_ABUSE_VERIFICATION.md`](advisor_evidence/PRIVACY_ABUSE_VERIFICATION.md) |
| Performance (E-4) | floor recommendation 200 ms (measured); no OOM under a 2.56 GB cap; no admission bound | [`PERFORMANCE.md`](advisor_evidence/PERFORMANCE.md) |
| Accessibility / keyboard E2E (E-3) | public: 6 of 12 pass (error recovery and hydration); the 6 multi-step flows fail only on focus loss; axe clean at every step. Private: 8 / 8 by default; strict mode fails only on 2 pre-existing `/trade` items | specs on #1866 (`advisor-e2e-keyboard-a11y.spec.js`) and #1883 (`trade-multi-team-e2e-keyboard-a11y.spec.js`) |
| Fairness threshold research | read-only; the threshold is unsuitable as-is | [`FAIRNESS_THRESHOLD_RESEARCH.md`](advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md) |

What was not run:

- the mobile-390 and mobile-430 projects (WebKit is unavailable in this environment);
- Team Context verdicts with real projections (box-local only, so every team is
  NOT_ENOUGH_EVIDENCE locally);
- LCP / CLS for the advisor;
- production screenshots (the advisor is off in production).

## G. Example trades

Full private numeric tables and the exact value-free public bodies are in
[`advisor_evidence/EXAMPLE_TRADES_G.md`](advisor_evidence/EXAMPLE_TRADES_G.md). They cover sends,
receives, raw / VA / adjusted totals, gap, band, fairness, asset-only decision and Team Context
decision.

How to read the table:

- **Private** shows each team's market fairness and its asset-only decision. Team Context answers
  NOT_ENOUGH_EVIDENCE locally for every team (`roster_unknown`), because league-scored projection
  snapshots are box-local.
- **Public** shows the overall result. The per-team rows mirror the private fairness exactly, and
  the body is identical from every perspective.

| # | Shape | Private per team (fairness · asset-only decision) | Public overall |
|---|---|---|---|
| G1 | 2 teams, offense 1-for-1 | Jason NOT_FAIR · NO; Roy NOT_FAIR · YES | NOT FAIR |
| G2 | 3 teams, circular | Jason NOT_FAIR · NO; Collin NOT_FAIR (+253, 4.27%) · YES; Roy NOT_FAIR · YES | NOT FAIR |
| G3 | 4 teams, circular | Jason NOT_FAIR · NO; Ty NOT_FAIR · NO; Collin NOT_FAIR · YES; Roy NOT_FAIR · YES | NOT FAIR |
| G4 | IDP (DL/LB/DB for LB/DB) | 1 NOT_FAIR · NO; 4 NOT_FAIR · YES | NOT FAIR |
| G5 | Picks only, 3-team cycle of 2027 1sts | all three FAIR · NO_TOO_CLOSE | **FAIR TRADE** |
| G6 | Mixed players + pick, one team to two destinations | 1 FAIR · NO_TOO_CLOSE; 4 NOT_FAIR · NO; 7 NOT_FAIR · YES | NOT FAIR |
| G7 | Benefits more than one team (two YES) | 1 NOT_FAIR · NO; 4 NOT_FAIR · YES; 7 NOT_FAIR · YES | NOT FAIR |
| G8 | Clearly disadvantages one team (elite for depth) | 1 NOT_FAIR · NO; 7 NOT_FAIR · YES | NOT FAIR |
| G9 | Cannot be evaluated reliably (unpriced rostered player) | 1 NOT_FAIR · NO; 4 UNABLE · NOT_ENOUGH_EVIDENCE; 7 UNABLE · NOT_ENOUGH_EVIDENCE | NOT FAIR (Kleene AND: one proven NOT_FAIR team decides it; the unpriced asset is named in `unavailableAssetIds`) |
| G10 | Cannot be evaluated reliably (2028/2029 unknown-slot picks) | both UNABLE · NOT_ENOUGH_EVIDENCE (`quarantined_values`) | UNABLE TO DETERMINE |
| G11 | 4 teams, offense + IDP + picks | 1, 3, 7 UNABLE; 4 NOT_FAIR · YES | NOT FAIR |
| G12 | Exceeds roster limits (2-for-1 into a 58-man roster) | 1 NOT_FAIR · NO; 7 NOT_FAIR · YES, with 1 forced drop reported | NOT FAIR (roster limits never affect public fairness, SD-3) |
| G13 | Stale roster ownership (restored, 30 h old) | all UNABLE · NOT_ENOUGH_EVIDENCE (`ownership_unverifiable`) | UNABLE TO DETERMINE |

**Public FAIR TRADE is rare in practice.** It needs every team inside the PROVISIONAL band, and
that gets strictly harder as N grows (research §7c). Only near-equal cycles (G5, S22, S23)
reach it.

## H. Integration status

Status as of writing, from the GitHub REST API. `main` is at `675ebc751f`.

| PR | Lane | Branch | Base | Head | Mergeable | CI on head |
|---|---|---|---|---|---|---|
| [#1882](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1882) | A, engine (+ E-1 gap tests) | `claude/trade-nteam-engine` | `main` | `52b2aef95a` | **no (dirty)**: conflicts with `main` in README, `docs/ARCHITECTURE.md`, `OWNER_REQUESTED_TODO`, `WORK_CLAIMS`, `feature_flags.py` | only L0 Fast Checks ran (success). PR Validation and E2E have never run |
| [#1883](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1883) | B, private UI | `claude/trade-nteam-private` | `claude/trade-nteam-engine` | `ccab9bdef4` | yes (unstable) | **Validate PR: failure** (decision-coercion gate). **E2E Safety Net: failure** (4 failed, 70 skipped, 368 passed: the existing `trade-tcd2.spec.js` and the new 2-team keyboard spec, on both projects) |
| [#1861](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1861) | C, public backend | `claude/advisor-public-backend` | `main` (stacked on #1882) | `82ca5fa984` | **no (dirty)**: same conflict set | only L0 Fast Checks ran (success) |
| [#1866](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/1866) | D, public frontend (+ E-3 keyboard spec) | `claude/advisor-hub-frontend` | `main` (stacked on #1861) | `8064c4a6d8` (before this report's commit) | yes (unstable) | **E2E Safety Net: failure** (82 skips > 70 ceiling); Validate PR in progress |

- **Merged:** none of the four.
- **Deployed:** nothing.
- **Flags:** `brisket_trade_advisor` and `trade_multi_team_analysis` both default `False`. The
  launch-gate inputs in `config/trade/public_advisor.json` (`responseFloorMs`,
  `approvedFairnessVersion`, `approvedSourcePermissionRecord`) are all `null`.
- **Merge order:** #1882 → #1883, and #1882 → #1861 → #1866. Each PR must merge after the one it
  stacks on, or in the same release train.
- **Not in this campaign:** D-net (the loopback-bind change) has no PR yet.

**Rollback.** Set `RISKIT_FEATURE_BRISKET_TRADE_ADVISOR=0` and restart; flag reads are cached
per process.

- This gates only the public router. The shared engine, the private
  `/api/trade/analyze-multi` (its own flag) and core valuation do not depend on it.
- The private multi-team War Room rolls back independently with
  `RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS=0` + restart. `/trade` then shows the static 3+-team
  panel, and 2-team analysis is untouched.
- **R2-9 (fixed on #1866, Lane D round 2):** the League Hub offers the advisor only when the
  server's probe says `ready`; `disabled`, `unknown` (a closed launch gate's 503 `not_ready`, a
  backend outage) and a missing bootstrap all leave `/league` exactly as main. Caveat: the
  probe is a Next fetch cached for 60 s (`revalidate`), so a rollback can serve the advisor
  landing for up to that window plus one request after the restart.

## Fairness-threshold research conclusion

Full memo: [`advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md`](advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md).

The **owner** is right: `fairness_bands.classify`, called once per team on that team's full
package. That reduces exactly to today's 2-team band at N = 2, with no new formula.

The **threshold** is not suitable as the fixed public threshold in its current form:

1. **The 250-point floor decides 97.5% of priced assets** (everything below 7,143).
   - A 1-for-1 stays FAIR up to a 25% gap at 1,000 and a 50% gap at 500, but only 3.5% at 9,999.
   - Every IDP 1-for-1 is decided by the floor alone.
2. **The denominator re-adds the depth the package model discarded.** The gap is in
   package-utility units, but the denominator is the larger *adjusted* side. Tolerance therefore
   loosens by about ×1.36 at 4 pieces and ×2.73 at 12. A stud-for-12 trade 8% short in utility
   reads FAIR.
3. **It is officially `PROVISIONAL`.** It is a rescaled KTC-era prior, never fit against a target.
4. **It conflicts with the public history grade.** The League Hub's trade-history grade ("Fair
   trade" below 3.0%, no floor) disagrees on 12 of 153 real team results.

The engineering recommendation, which needs owner acceptance, is:

- **OD-F1** (a): FAIR = band `fair` only.
- **OD-F2** (b): utility denominator.
- **OD-F3:** keep 250 only as an explicitly approved PRIOR.
- **OD-F5** (a): publish as an owner-approved prior version, with OD-F4 validation after launch.
- **OD-F6:** align the history grade.

Nothing was changed. Any change moves the private Asset-Only YES / NO, the meter, balancers and
suggestions too, so it must be re-measured with `scripts/measure_fairness_band_change.py`.

## Owner decisions needed

**Blocking public launch:**

1. **OD-F1–OD-F6, fairness threshold:**
   - the FAIR level;
   - the denominator basis;
   - the 250 floor;
   - the validation target;
   - the published version and status;
   - reconciling the trade-history grade.

   Also: whether the amendment overrides #1861 design rule D8.
2. **OD-3a–d, source permission for a public derived verdict.** Covers Signals (3a), KTC (3b),
   IDP Trade Calculator (3c, whose F-EXT-02 record is stale) and every other voting source (3d).
   - Parity forbids a public-only source subset, so each answer is "confirm" or "do not launch".
   - The answer is recorded at `approvedSourcePermissionRecord`.
   - OD-4 no longer applies to the public path: it reads no team-context inputs, and a login
     changes nothing.
3. **Residual acceptance, or a redesign:**
   - **F-1:** the hidden quarantined / stale per-asset set is recoverable in about 180 queries by
     group testing. Folding it into `evaluable` would publish it for free.
   - **Slow refinement:** about 20k queries bring a git-board attacker from 3.16% to 1.82% median
     error, and recover a Signals-like delta only partly (correlation 0.43). Under the limits
     that is 10–49 days, or at least 6.6 h at the global ceiling with everyone else locked out.
4. **New limit sizes (gate 7):**
   - a public admission / concurrency bound (suggested: a semaphore with a small declared prior,
     a bounded wait, and a fixed-copy 503 held to the floor);
   - the matching private bound.
5. **Launch inputs:**
   - **`responseFloorMs`:** 200 ms measured (alternative table `{"2":150,"3":200,"4":200}`).
     Also accept that 200 ms is exceeded during in-process scrape contention (p99 470–623 ms).
   - **OD-8 limiter priors,** including the global-ceiling lockout tradeoff (F-4) and the
     public `send_and_receive` rule (SD-5).
6. **F1, pick evaluability (valuation / pick owner).** Every 2028 / 2029 league pick resolves to
   a generic row that is quarantined (`no_valid_source_values`, `derived_uniform_tier_ev`). Any
   trade containing one is unevaluable on every surface, including today's 2-team War Room.
   - This is a usefulness blocker, not a privacy or parity one.
   - E-4 separately found that 175 of the 858 assets listed as evaluable carry the quarantine or
     stale gate.
7. **Public launch itself (gate 11).**

**Confirmations requested, not blocking:**

- SD-3 (roster limits outside public fairness);
- SD-7 (stale rosters fail closed);
- SD-9 (meter fix before / after);
- SD-13 (no N ≥ 3 balancers);
- SD-14 (per-team copy);
- raising private `maxTeams` above 4;
- whether the name "Brisket Trade Advisor" stays under a fairness-only scope;
- F-3 (whether the main-branch app-shell chunk that ships q = 0.78 and the source list on every
  page must be split).

**Ops, on the production box:**

- check that :8000 / :3000 are not reachable from outside, the firewall, that there is no CDN,
  and the trusted-proxy settings;
- deploy D-net (`server.py` still binds `0.0.0.0` and serves `/docs` / `/openapi.json` on a
  direct :8000 hit);
- measure the production floor and the Signals delta on the box.

## Reviewer findings and resolutions

"Open" means routed to the named owner and not yet fixed on any branch. Nothing below is
resolved by this report.

### Spec review (30 items) — all resolved in the spec

The engine / methodology items R1–R16 and the privacy / contract P-items were all accepted. Each
disposition is recorded in [`NTEAM_TRADE_ENGINE_SPEC.md`](NTEAM_TRADE_ENGINE_SPEC.md) §11 and
implemented in Lanes A–D. Examples:

- ownership-unverifiable gate (I17);
- Kleene AND;
- gap = recv_adj − send_adj;
- one snapshot per request;
- `comparables_provider` injection;
- validation order;
- value-free assertion;
- floor applied in `finally`;
- the public path writes nothing;
- canonical ordering;
- no value sort.

### Independent review 1 — engine (#1882), not passed, fixable

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| R1-1 | MEDIUM | The league scarcity bundle (`gameplan.get_league_bundle`, through `roster_capacity` → `draft/context._league_scarcity`) is read once per **team**, not once per request. Its live fallback has a 120 s TTL, so teams in one request can see different scarcity availability. Observed: teams[2] and teams[3] got "scarcity unavailable" in the same request as teams[0] and teams[1]. This breaks §4's "one snapshot". | **Open → Lane A.** Resolve scarcity once per request, memoised like `_PostureMemo` or carried on the snapshot, and add a resolved-once test. |
| R1-2 | MEDIUM (CI) | The `test_route_equals_engine_byte_for_byte…[True]` gap test fails 4 of 4 runs under `-n 3` with the multi-team suites (passes alone). The diff is only the scarcity notes. It also depends on the network-capable live team-strength fallback inside the hard gate. | **Open → Lane A.** Fixing R1-1, then pinning the scarcity source in the fixture, closes it. |
| R1-L1 | LOW | `simulate_trade` now degrades any `team_impact` `ValueError` to `teamImpact` unavailable instead of a 500, on the existing routes too. | Recorded; deliberate (Lane A). |
| R1-L2 / E1-F2 | MEDIUM | A quarantined asset is published as `valueState: "priced"` with its number, next to a decision that refused it. The public `unavailableAssetIds` cannot name it. | **Open → Lane A** (row contract) and **Lane C** (public ids). Interacts with F-1 disclosure: an owner decision. |

### Independent review 2 — public side (#1866 @ 8064c4a6d8), not passed, not fixable without the owner

| ID | Finding | Resolution |
|---|---|---|
| R2-1 | No source-permission record (OD-3a–d) | **Owner** |
| R2-2 | Fairness threshold unapproved (OD-F1–F6) | **Owner.** The gate enforces it correctly |
| R2-3 | F-1 quarantine-set recovery (180 queries) | **Owner** acceptance or redesign |
| R2-4 | Slow value refinement through the binary oracle | **Owner** acceptance |
| R2-5 | No admission / concurrency bound or compute timeout (saturates at about 12–14 rps; `/api/health` 0.7–1.4 s at 32 concurrent) | **Open → Lane C**; limit size → **owner** |
| R2-6 | `responseFloorMs` unset (200 ms measured) | **Owner** launch input |
| R2-7 / E2-F2 | The service worker caches the advisor GET lists despite `no-store` (`sw.js` NEVER_CACHE lacks the prefix) | **Fixed on #1866 (Lane D round 2):** `/api/public/league/trade-advisor` in NEVER_CACHE, `CACHE_VERSION` v10; vitest runs the real `sw.js` and proves no `respondWith` / `caches.open` / `put` for the advisor GETs. No browser check with the service worker allowed (the advisor cannot be served in CI) |
| R2-8 / E2-F3 | App-shell chunks on every page ship q = 0.78, package-model code and the source list (pre-existing on `main`) | **Open**, follow-up, owner confirmation |
| R2-9 | The hub treats any probe state other than `disabled` as available. A backend error with the flag OFF, or the flag ON with the gate closed, makes the advisor the landing tab | **Fixed on #1866 (Lane D round 2):** `ready` only (hub state + metadata); vitest SSR + client cases for 503 `not_ready`, no answer and no bootstrap |
| R2-10 | `_source_permission_record_exists` accepts any existing repo file (e.g. README.md) | **Open → Lane C.** Validate the record's shape and coverage |
| R2-11 / E3 | Public keyboard focus falls to `<body>` after Edit trade, Remove, New trade and Start over (6 / 6 multi-step flows, desktop and mobile) | **Fixed on #1866 (Lane D round 2):** Edit / New trade → "Build your trade" heading, Start over → "Which team is yours?" heading, Remove → next asset's Remove, else previous, else that team's Add. Keyboard spec assertions are now hard and target-specific; 12 / 12 public keyboard tests pass locally (desktop-1366 + mobile-chromium) |
| R2-12 / E2-F5 | The site-wide public limiter keys on the exact IP (one IPv6 /64 reads the GET lists without limit), and its 429 copy differs from the advisor's | **Open → Lane C** |

### Independent review 3 — integration, not passed, fixable

| ID | Finding | Resolution |
|---|---|---|
| CI-1 | #1883 Validate PR fails `check_decision_coercions`. The new coercion is `trade-logic.js:892` (`Number(v) \|\| 0` in the 3+-side branch of `valueAdjustmentFromSideArrays`), plus one stale baseline entry | **Open → Lane B** |
| CI-2 | #1866 E2E fails the skip ceiling, 82 > 70: 12 skips from `league-trade-advisor.spec.js` live tests that skip whenever the advisor is off | **Fixed on #1866 (Lane D round 2):** the 6 serving-dependent tests (mocked flows included — the hub's server-side probe decides whether the advisor renders, and the launch gate cannot open in CI) register only under `E2E_ADVISOR_E2E=1`. CI registers 2 instead of 14 (−12 skips → 70, main's count); `E2E_MAX_SKIPPED` unchanged |
| CI-3 | #1882 and #1861 are dirty against `main` and have never run full CI | **Open → Lanes A, C.** Merge `main`; keep one consistent flag count across the stack |
| UX-1 | = R2-11 | Lane D |
| UX-2 | The floating feedback / camera button covers "Start over" in the 390 px public result | **Fixed on #1866 (Lane D round 2):** phone bottom reserve on the advisor root; the live spec hit-tests "Analyze trade" and "Start over" at the page end. Before: `button.screenshot-fab` covered Analyze on mobile-chromium (390 px); after: clear on 2/3/4 teams |
| UX-3 | `/trade` (pre-existing): focus lost after Remove; "Owned pick" badge contrast 4.48:1 | **Open**, pre-existing; recorded as annotations in the private keyboard spec |
| UX-4 | `trade-stack-withdrawn.test.js` was loosened from an exact key set to a `/stack/` blocklist at 3+ teams | **Open → Lane B.** Restore an explicit allowlist (CLAUDE.md treats that file as a methodology guard) |
| RECORDS-1 | The Lane B `WORK_CLAIMS` row names the wrong branch and omits files Lane B touched | **Open → coordinator** |

### Lane-reported findings not covered above

| ID | Finding | Resolution |
|---|---|---|
| E1-F1 | 2028 / 2029 generic pick rows are quarantined, so any such pick is unevaluable everywhere | **Owner** (valuation / pick owner) |
| E1-F3 | Private builder destinations are keyed by player display name (`tradeEntryKey`) | **Open → Lane B** (low) |
| E1-F5 | War Room package totals show 0 for an unpriced-only package, with no "incomplete" marker (verdict correct) | **Open → Lane B** (missing-is-never-zero display) |
| E2-F4 | Cheap invalid requests from many /16s drained the global ceiling in 4.7 s, after which a legitimate client got 429 | **Owner** (OD-8 limiter priors) |
| E2-bind | `server.py` binds `0.0.0.0`; `/docs` and `/openapi.json` are served on a direct :8000 hit | **Open → D-net** (separate PR) + ops |
| E4-1 | First request after boot takes 0.4–0.8 s, above the floor once per process start | **Open, optional → Lanes A / C** (warm evaluation) |
| E4-2 | No client timeout in `trade-advisor-client.js` | **Open, optional → Lane D** |
| LC-1 | `team_verdicts.team_category` maps a malformed decision (YES with `deciding = executionGate`) to FAVORABLE. `decide()` cannot produce that shape, and the old test was dropped | **Open → Lane A** to decide whether to restore it |
| H-1 (this report, from the #1883 CI log) | The existing `tests/e2e/specs/trade-tcd2.spec.js` expects the old 3-team copy "reliable YES / NO unavailable for 3 teams", but Lane B's sticky tray now reads "Preliminary · … · final result in the War Room". The new private 2-team keyboard test never reached `[data-war-room="ok"]` in CI (2 projects × 2 retries) | **Open → Lane B.** Update the existing spec to the new copy, and diagnose the 2-team War Room state in the CI stack |

## Launch gate checklist (directive §16)

| # | Gate | State |
|---|---|---|
| 1 | Backend + frontend integrated | **Partly.** The combined tree merges and builds cleanly. #1882 and #1861 are dirty against `main` |
| 2 | 2/3/4-team results work end to end | **Yes, locally.** Real stack, real browser, desktop and mobile |
| 3 | Private / public parity verified | **Yes** (2,082 + 892 checks) |
| 4 | Player and pick ownership validation | **Yes** (V05 / V09 409 everywhere; stale fails closed) |
| 5 | Privacy | **Partly.** Values, perspective, storage and errors pass. F-1, F-2 and F-3 are open |
| 6 | Source permission resolved | **No** (OD-3) |
| 7 | Performance and abuse controls | **No.** Floor measured but unset; no admission bound or timeout |
| 8 | Accessibility and mobile E2E | **Partly.** Public focus management fixed and passing on desktop-1366 + mobile-chromium (390 px); mobile-390/430 (WebKit) not runnable locally |
| 9 | Independent review complete | **Done, none passed** (3 reviews, findings above) |
| 10 | CI and deploy verification green | **No** (section H) |
| 11 | Owner approves launch | **Not requested.** Blocked by 6–10 |

## Evidence index (this repository)

- [`advisor_evidence/PARITY_REPORT.md`](advisor_evidence/PARITY_REPORT.md): Lane E-1 parity,
  invariance, matrix and findings F1–F5.
- [`advisor_evidence/EXAMPLE_TRADES_G.md`](advisor_evidence/EXAMPLE_TRADES_G.md): §17 G, 13
  trades, private numeric and public value-free.
- [`advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md`](advisor_evidence/FAIRNESS_THRESHOLD_RESEARCH.md):
  threshold research and OD-F1–F6.
- [`advisor_evidence/PRIVACY_ABUSE_VERIFICATION.md`](advisor_evidence/PRIVACY_ABUSE_VERIFICATION.md):
  Lane E-2 §9 checklist, reconstruction, timing and source permission.
- [`advisor_evidence/PERFORMANCE.md`](advisor_evidence/PERFORMANCE.md): Lane E-4 floor
  calibration, concurrency and memory.
- [`advisor_evidence/private_meter_before_after.txt`](advisor_evidence/private_meter_before_after.txt):
  SD-9 before / after (synthetic values).
- [`advisor_evidence/screens/public/`](advisor_evidence/screens/public/): 18 value-free
  screenshots.
- [`advisor_evidence/screens/public-e2e/`](advisor_evidence/screens/public-e2e/): keyboard-E2E
  captures, result enums, error recovery and stale rosters.

Paths written `<session-scratchpad>/…` inside the copied evidence refer to the session-local
harness and raw outputs. They were not committed: they include private response bodies, attack
harnesses and private screenshots. Every number in the copied evidence derives from tracked
repository data (`exports/archive/`, `exports/latest/`) or is labelled synthetic. Signals is
`not_provisioned` locally, so no box-local source contributes to any value.

## Completion result

- **STATUS:** PARTIAL. The report unit itself is done. The campaign it reports on is blocked.
- **ACCEPTANCE:**
  - §17 A–I covered, with links to the evidence;
  - the threshold conclusion;
  - owner decisions;
  - every reviewer finding with its resolution;
  - exactly one launch recommendation.
- **EVIDENCE:** the lane reports and reviews cited above, and live PR / CI states from the GitHub
  REST API at the time of writing.
- **UNRESOLVED:**
  - the owner decisions listed above;
  - the open engineering findings R1-1, R1-2, CI-1–3, R2-5, R2-7, R2-9–R2-12, UX-2, UX-4, H-1,
    E1-F3 and E1-F5;
  - Team Context verdicts with real projections (box only);
  - the mobile-390/430 projects;
  - production network checks;
  - no PR is merged, deployed or enabled.
- **NEXT_ACTION:**
  - Lanes A and C merge `main` and fix R1-1 / R1-2.
  - Lane B fixes CI-1 and H-1.
  - Lane D: CI-2, the focus management, R2-7, R2-9 and UX-2 are fixed (round 2); CI to confirm.
  - The owner rules on OD-F1–F6 and OD-3.
