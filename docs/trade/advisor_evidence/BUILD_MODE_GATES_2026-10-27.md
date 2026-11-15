# Trade Advisor + multi-team: build-mode gate status (2026-10-27)

- **Mode:** BUILD_ONLY_MAX_THROUGHPUT (owner, 2026-10-27). Build, test and open a draft PR
  only. Nothing here is merged, deployed or enabled. No flag default and no committed launch
  input changed.
- **Base:** `origin/main` `a53680edc7`.
- **Supersedes nothing.** This is an evidence addendum to
  [`../TRADE_ADVISOR_MULTITEAM_REPORT.md`](../TRADE_ADVISOR_MULTITEAM_REPORT.md) (2026-10-20). That
  report described four open PRs. All four (#1882, #1883, #1861, #1866) and the Lane E defect
  fixes (#1937) are now on `main`.
- **Locked methodology, untouched:** `fairness_bands_v2`, package model `geom_q078_v1`
  (q = 0.78), the one verdict owner `trade_decision.decide()`, the near-tie rule, and roster-neutral
  value kept separate from team utility.
- **Agent-OS-Receipt:** `cb64f74cf4d2763aa16d55ba0d6350f585a2a42f`

## 1. Public Advisor engineering prerequisites (D1)

| Gate item | State on `main` before this PR | This PR |
|---|---|---|
| Request validation (strict schema, body cap, content type, ledger order §2.3) | done (#1861, #1937 echo anchor) | unchanged |
| Player / pick ownership validation (409 `asset_not_owned`, stale rosters fail closed) | done (ledger) | unchanged; covered again by the D2 matrix |
| Admission bound + concurrency limit (`maxConcurrent` 2, retryable 503 `busy`) | done (`src/api/compute_admission.py`); sizes PENDING OWNER CONFIRMATION | unchanged |
| Caller deadline, server side (5 s, 503 `timeout`) | done | unchanged |
| **Caller deadline, client side (E4-2)** | **missing**: an unanswered request left the page "Analyzing…" forever | **added**: `CLIENT_DEADLINE_MS` (analyze 15 s, lists 10 s). These are declared priors, longer than the server bound plus floor plus a 2 s margin (pinned by a Python parity test). The timeout maps to the existing retryable `timeout` banner with the server's fixed copy. A caller's own abort still throws `AbortError`. The transient 502/504 retry shares the one deadline |
| Error handling (fixed copy, never a server string, never a 500) | done | unchanged |
| Privacy boundary: recursive value-free scan of every public route from every perspective | done (`tests/api/test_public_advisor_privacy_multi.py`) | unchanged |
| Public / private route separation (team-context entry points unreachable from public) | done (same file, `test_m1_*`) | unchanged |
| 2- / 3- / 4-team consistency (one market-fairness calculation) | done (#1889 audit, parity suites) | the D2 matrix adds named 2/3/4-team rows |
| Accessibility, keyboard, mobile | done for desktop-1366 and mobile-chromium (#1866 rounds 2–4) | not re-run. WebKit 390/430 are still not runnable locally |
| **Response-floor calibration** | measured 2026-10-20 on the engine only (200 ms); `responseFloorMs` = `null` | **re-measured on current `main`, engine AND end-to-end route** (§2). The config stays `null`, because this is an owner launch input |
| **Source permission (OD-3)** | validator done (R2-10); no record exists | **checklist + unanswered template added** (§3). No approval was written or inferred |

## 2. Worst-case p99 latency (local only, never production)

**Method.** `scripts/measure_trade_analyze_multi.py` ran on the archived board
`dynasty_export_20261025_120337.zip` (real `dynasty_main` rosters, 12 teams) at
`a53680edc7`. The machine was Windows 11, Python 3.12.10, with one process and the in-process
transport only. Every non-loopback connect was refused.

- **Worst case** is the spec §6.3 (P1) shape: `maxLegs` = 128 (103 at N = 2, the most two
  rosters hold), every team sending and receiving, every asset priced.
- **Cold** means the ledger snapshot memo and the before-roster cache were cleared before
  every sample.
- **New this PR: `--public-route`.** It drives `POST /api/public/league/trade-advisor/analyze`
  end to end through the in-process TestClient. The flag is ON and the launch gate is opened
  **in that process only**; committed config is untouched.
- **No floor is applied** (it is unset), so the raw latency the floor must cover is what gets
  measured.
- Both limiters are reset outside the timed window.
- **Raw outputs are not committed.** The measurement JSON from these runs was not added to the
  repository, so the tables below cannot be reproduced byte for byte from this PR. Re-run the
  script with `--output <file>` on the same archived board to regenerate them; expect machine and
  contention variance.

### Engine (`analyze_trade_n`, `market_fairness` mode)

Run settings: `--skip-route`, 30 cold and 30 warm samples. A frontend `npm ci` and vitest ran
concurrently for part of this run, so it reads high, not low.

| N | shape | legs | cold p50 / p95 ms | warm p50 / p95 ms |
|---|---|---|---|---|
| 2 | worst | 103 | 50.5 / 66.2 | 29.7 / 55.5 |
| 3 | worst | 128 | 65.2 / 91.2 | 68.2 / 105.9 |
| 4 | worst | 128 | 74.8 / 114.3 | 60.7 / 90.0 |

- **Worst-case cold p99 over N = 2–4: 134.7 ms.** The script's 50 ms-step candidate is **150 ms**.
- **Sample-size caveat:** with 30 samples per cell, a "p99" is effectively the **maximum** of
  the run, not a stable 99th percentile. Treat 134.7 ms as a worst observed value. The public-route
  numbers below (150–200 samples per cell) are the better-founded tail estimate.
- Structural budgets S1–S6 pass: one snapshot, at most one posture read, one scarcity read,
  `market_fairness` skips capacity / utility, and no comparables at N ≥ 3.

### Public route, end to end (new)

Run 2 was uncontended, with 200 cold and 200 warm samples. Run 1 used 150 + 150 and overlapped
a pytest run for about 1 min.

| N | shape | legs | run 2 cold p50 / p95 / p99 / max ms | run 1 cold p99 / max ms |
|---|---|---|---|---|
| 2 | representative | 5 | 39.7 / 65.6 / 127.3 / 151.0 | 120.2 / 155.4 |
| 3 | representative | 7 | 53.7 / 94.2 / 166.0 / 231.6 | 196.2 / 225.1 |
| 4 | representative | 10 | 70.4 / 114.4 / 172.7 / 212.9 | 203.3 / 208.4 |
| 2 | worst | 103 | 52.6 / 80.9 / 172.5 / 193.6 | 252.6 / 372.2 |
| 3 | worst | 128 | 69.5 / 123.3 / 178.0 / 235.5 | 184.8 / 201.8 |
| 4 | worst | 128 | 82.8 / 140.9 / **215.6** / 234.1 | 192.1 / 277.6 |

- **Process warm-up** (the first request after import) was 100–115 ms. That is the E4-1 case,
  paid once per process.
- **Worst-case cold p99 (uncontended): 215.6 ms (N = 4).** The 50 ms-step candidate is
  **250 ms**. No sample in run 2 exceeded 250 ms.
- **Under contention it rises.** Run 1 (N = 2) reached a p99 of 252.6 ms and a max of 372 ms,
  in line with E-4's in-process-scrape contention finding (p99 470–623 ms).

### Recommendation for the owner's `responseFloorMs` decision

This is an engineering recommendation only. The value stays `null`.

**`250`.** The floor is timed from after the launch gate, so it covers the route's limiter,
body read, schema, ledger, admission, single-flight, the reducer, value-free assertions and
response building. The engine-only number (150) does not.

- **Why it differs from 2026-10-20:** that report recommended 200 from an engine-only p99
  of 155.9 ms.
- **Alternative per-team-count table:** `{"2": 200, "3": 200, "4": 250}` (uncontended p99
  172.5 / 178.0 / 215.6).
- **Re-measure on the production box before launch.** A slower CPU, or a scrape running in
  the same process, raises every number here.

## 3. OD-3 source-permission checklist (owner-reserved; not an approval)

The launch gate needs `config/trade/public_advisor.json::approvedSourcePermissionRecord` to name a
JSON record under `docs/owner/`. `src/trade/public_advisor_permission.py` validates that record
in full:

- exact `recordType` / `schemaVersion` / `scope`;
- a named approver;
- `approvedAt <= today <= reviewBy`;
- every voting source approved;
- no denials and no `unknown`.

**No such record exists.** None was written.

`python scripts/advisor_permission_checklist.py` prints the live list. `--template` prints an
**unanswered** form: no approver, no dates, every provider `"unknown"`. The validator refuses
that form as it stands (pinned by test), so committing it unchanged cannot open the gate.

Current registry: 27 voting sources across 15 providers. A provider entry approves all of its
sources. Without a provider entry, **every** one of its source entries is needed. A denial at
either level refuses.

| # | provider | voting sources |
|---|---|---|
| 1 | `draftSharks` | `draftSharks`, `draftSharksIdp` |
| 2 | `dynastyDaddy` | `dynastyDaddySf` |
| 3 | `dynastyLeagueFootball` | `dlfIdp`, `dlfRookieIdp`, `dlfRookieSf`, `dlfSf`, `dlfValuesSfTep` |
| 4 | `dynastyNerds` | `dynastyNerdsSfTep` |
| 5 | `fantasyCalc` | `fantasyCalc` |
| 6 | `fantasyNavigator` | `fantasyNavigatorSf` |
| 7 | `fantasyPros` | `fantasyProsFitzmaurice`, `fantasyProsIdp`, `fantasyProsSf` |
| 8 | `flockFantasy` | `flockFantasySf`, `flockFantasySfRookies` |
| 9 | `idpTradeCalculator` | `idpTradeCalc` |
| 10 | `keepTradeCut` | `ktcCrowdSfTep`, `ktcTradesSfTep` |
| 11 | `otcFantasyFootball` | `otcffbSf` |
| 12 | `playForKeeps` | `pfkDynasty` |
| 13 | `signalsFantasy` | `signalsIdpDb`, `signalsIdpDl`, `signalsIdpLb`, `signalsSf` |
| 14 | `theIdpShow` | `idpShowCombined` |
| 15 | `yahoo` | `yahooBoone` |

What the owner must also supply:

- **`approvedBy`** — who approved.
- **`approvedAt` / `reviewBy`** — dates. `reviewBy` is the owner's own staleness choice.
- **The config pointer** — set `approvedSourcePermissionRecord` to the file's repository path.

Parity forbids a public-only source subset (2026-10-20 report, OD-3a–d), so each provider's
answer is "approve" or "do not launch".

**The checklist moves with the registry.** A source added to the board later makes an existing
record uncovered by construction, so the checklist must be regenerated whenever the voting set
changes.

## 4. Private multi-team correctness (D2)

`tests/trade/test_multi_team_decision_matrix.py` holds 59 tests. Each row is checked against an
independent oracle built from `fairness_bands.package_utilities` / `classify_packages`, never
from the engine's own numbers.

| Row | Scenario | Result |
|---|---|---|
| M01 | even 1-for-1 | FAIR, gap 0, NO_TOO_CLOSE, all modes |
| M02 | lopsided 1-for-1 | ±4,000, lopsided, NO / YES |
| M03 | raw-even 2-for-1 | +660 to the stud receiver (U = 4000 + 0.78 · 3000 = 6340 vs 7000), 9.43% → NOT_FAIR; raw value conserved |
| M04 | 3-team cycle of 2027 1sts | FAIR for all, NO_TOO_CLOSE |
| M05 | two same-label 2027 1sts to one team | two assets, 7,200 raw, never collapsed |
| M06 | 4-team cycle | per-team gaps {+4000, −1000, +1000, −4000}; Kleene NOT_FAIR; no trade-level gap / VA / utility |
| M07 | over the cap | forced drop reported; fairness and Asset-only unchanged |
| M08 | unpriced asset | UNABLE / NOT_ENOUGH_EVIDENCE, value `null`, never 0 |
| M09 | superflex lineup settings | canonical fairness and Asset-only unchanged |
| M10 | same facts, −3 ppg lens, by team goal | WIN_NOW → NO, REBUILD (LONG_TERM) → YES; fairness identical |
| M11 | Team Context on / off | fairness identical in all three modes, every row |
| M12 | +4,000 value against −3 ppg | value and utility are separate reasons; balanced → NO; Asset-only → YES |
| M13 | verdict vs fairness | FAIR never YES; UNABLE → NOT_ENOUGH_EVIDENCE; NOT_FAIR never "too close" |

**No new defect was found.** The two open strict xfails in `test_multi_team_properties.py` are
still owner decisions, and this PR does not fix them:

- **`LANE-E-DEFECT-I18-PICKINV`** — what `pick_ownership_unknown` means for a team that
  *receives* a ledger-verified pick.
  - *Option A:* in the N-team path the ledger's per-asset verdict supersedes the per-team
    inventory gate. Both teams are then judged, as I18 requires.
  - *Option B:* keep the gate. I18 is then amended for this case.
  - The gate is shared with the legacy 2-team routes, so the change is not mechanical.
- **`LANE-E-DEFECT-I9-TIEBREAK`** — the cut ladder breaks equal costs by display name. The file
  is `src/draft/displacement.py`; the related `roster_capacity.py` is owned this sprint by
  worker B.

## 5. Explanation UX (D3)

The War Room already explains each team in plain words:

- its decision and its market fairness, as two labelled answers;
- "Why" (one sentence per `decide()` reason);
- "What is missing";
- gives and receives, with each asset's own server value and destination;
- the Raw / Value Adjustment / Adjusted package table;
- the gap, against the larger package after the depth discount, with its percentage;
- roster fit and forced cuts, lineup impact, and team direction.

No component was added. A new vitest pins that every number is traceable on screen, for each
team of the 4-team fixture:

1. Asset values sum to raw.
2. Raw plus VA equals adjusted.
3. Adjusted receives minus adjusted sends equals the gap.
4. The gap divided by the larger package utility equals the percentage.

## Launch gates still open

1. **OD-3** source-permission record — owner.
2. **`responseFloorMs`** — owner input; the recommendation is above.
3. **Admission sizes** (`maxConcurrent` 2 / 5 s; private 2 / 30 s) — owner confirmation.
4. **OD-8 limiter priors** and the F-1 / slow-refinement residual acceptance — owner.
5. **WebKit mobile-390/430 E2E** — not runnable locally.
6. **Production network checks** (bind, firewall, `/docs`) — D-net / ops.
7. **Launch approval** (gate 11) — owner; the flag stays OFF.
