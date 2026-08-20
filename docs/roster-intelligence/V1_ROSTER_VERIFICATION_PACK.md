# Roster Intelligence — V1 verification pack

Executable checklist for V1-27…V1-33, in the format
`docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10 established.

**Artifacts**

| what | where |
|---|---|
| the checks (pure) + the probe (HTTP) | `scripts/verify_roster_intelligence.py` |
| proof the checks work | `tests/roster_intel/test_verification_pack.py` (63 tests) |
| V1-35 model-half separation | `tests/roster_intel/test_metric_separation.py` (10 tests) |
| the metric census | `docs/roster-intelligence/V1_35_METRIC_SEPARATION_AUDIT.md` |
| the ledger | `docs/roster-intelligence/V1_ROSTER_EVIDENCE_MATRIX.md` |

---

## 1. The rule this pack is built around

> A verification that cannot distinguish "measured and found none" from
> "matched nothing" is not a verification.
> — `docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10a

That §10a was written after a checklist nearly passed vacuously: a join
by Sleeper id returned 0 hits, because `optimalLineup.assignments`
carries a *name* and not an id, and **0-of-0 violations reads exactly
like 0-of-240**.

So every check here publishes its own **denominator**, and the rule is
enforced by the *harness*, not by each check's author:
`finalize()` rewrites any `PASS` whose denominator is 0 into
`UNMEASURABLE`. A check author cannot forget to apply it, and
`test_harness_downgrades_a_vacuous_pass` pins it.

A `FAIL` with a zero denominator is deliberately left alone — that is a
contradiction the check is asserting, and rewriting it would hide a
defect in the check.

### Exit codes

| code | meaning |
|---|---|
| **0** | every check was MEASURED and PASSED |
| **1** | a check measured a violation |
| **2** | one or more checks could not be measured |

`2` is never collapsed into `0` ("no data" must not read as "passed" —
the convention `scripts/backtest_perfect_draft.py:51` sets) and never
into `1` ("we looked and it is broken" and "we could not look" call for
different actions: a defect versus a missing credential, an undeployed
endpoint, or a league with no contract).

### Evidence levels

Spelled `EVIDENCE-L1`…`EVIDENCE-L4` throughout, because
`docs/VERSION_1_COMPLETION_CONTRACT.md` uses `L1`…`L6` for **lanes** and
`L1`…`L4` for **levels** in the same table, and that ambiguity should
not reach machine-readable output.

Each check declares the level it can **reach**; the harness caps it at
what the run's **source** can support. A check whose ceiling is
EVIDENCE-L3 reports EVIDENCE-L2 when the run read a locally rebuilt
contract. Evidence is only as strong as its source.

---

## 2. Running it

### Post-deploy (EVIDENCE-L3 / L4) — for the integration lane

```bash
export ROSTER_VERIFY_COOKIE='session=…'      # /api/roster/intelligence is
                                             # behind server.py::_private_api_gate
python scripts/verify_roster_intelligence.py \
    --base-url "$PROD_PUBLIC_URL" \
    --expect-sha "$DEPLOYED_SHA" \
    --json-out data/ops/roster-intelligence-verification.json
```

`--base-url` is **required and has no default**: an unset origin is an
outage to surface, not a value to guess
(`.github/workflows/prod-e2e-smoke.yml:40`). With no `--league-key` it
runs every **active** league in the registry.

A 401/403 is **terminal, not retried** — the service is up and correctly
refusing an anonymous caller, and retrying it is guaranteed to fail
identically. `verify-sharp-production.yml` spent 40 minutes per run
learning that.

### Offline (EVIDENCE-L1 / L2) — runs in CI already

```bash
python -m pytest tests/roster_intel/test_verification_pack.py \
                 tests/roster_intel/test_metric_separation.py -q
```

Both files are pure-logic and stay in the **hard gate**
(`-m "not livedata"`); neither is in `_LIVEDATA_MODULES` and neither
touches the network —
`tests/infra/test_unit_suite_does_not_probe_production.py` forbids it,
which is why the pack is built as `fetch → payload → pure check`.

---

## 3. Results

Measured 2026-08-19 at `fd70515`, offline, against the newest COMPLETE
archived scrape (`dynasty_export_20260818_230211.zip`) rebuilt through
`build_api_data_contract` → `build_league_roster_intelligence`.

`newest_complete_raw_payload()` refuses a source-degraded bundle, so this
is a real board or nothing.

| # | check | result | level | denominator | evidence |
|---|---|---|---|---|---|
| 01 | every active configured league answers | **PASS** | EVIDENCE-L2 | 1 | one league rebuilt offline; see §4 for the second |
| 02 | weakness thresholds scale with `teamCount` | **PASS** | EVIDENCE-L1 | **216 rungs** | every `thresholdRank == rung × 12` |
| 03 | flex slots come from actual league configuration | **PASS** | EVIDENCE-L2 | **36 flex slots** | `slotSource = sleeper_roster_positions`; 12 teams × (FLEX×2 + SUPER_FLEX×1), each seated or reported unfilled |
| 04 | every player appears at most once per core | **PASS** | EVIDENCE-L2 | **374 members** | no duplicate `playerId` in any core |
| 05 | starters removed before the reserve solve | **PASS** | EVIDENCE-L2 | **240 starters** | starter ∩ reserve = ∅ (240 = 12 × 20, the same figure C2-U1 §10a reports) |
| 06 | core size respects starters + reserve demand | **PASS** | EVIDENCE-L2 | **12 teams** | `|core| ≤ slots + demand.total`, and `ceil(1.5·s) − s` re-derived per dedicated position |
| 07 | unpriced players reported, not coerced | **PASS** | EVIDENCE-L2 | **660 rostered** | `core.unpricedIds == strength.unpricedIds`; no zero-valued member hidden behind an empty list |
| 08 | unpriced excluded from every value aggregate | **PASS** | EVIDENCE-L2 | **83 unpriced** | `unpricedIds ∩ members = ∅` — 83 of 660 (12.6%) exercised the rule |
| 09 | Team Strength groups re-sum to total | **PASS** | EVIDENCE-L2 | **12 teams** | group sum and starter+reserve both equal `total` within rounding tolerance |
| 10 | weakness credits no player to two rungs | **PASS** | EVIDENCE-L2 | **215 rung credits** | no `playerId` fills two rungs on one team |
| 11 | Young Core uses core-only value, discloses PRIOR | **PASS** | EVIDENCE-L2 | **12 portfolios** | `coverage.totalPlayers == |core|`, `coverage.totalValue == strength.total`, `youngCoreIndexStatus == "PRIOR"` |
| 12 | teamAssignment degrades honestly | **UNMEASURABLE** | — | 0 | needs the deployed public-league section — see §4 |
| 13 | endpoint latency within budget | **UNMEASURABLE** | — | 0 | nothing was fetched over HTTP — see §4 |

Offline exit code: **2**. Correct, and the point: eleven checks passed
and two could not be measured, so the run does not report success.

**Denominators matter more than the verdicts.** Every figure above is
non-zero and independently plausible: 240 starters is 12 teams × 20 live
slots; 83 unpriced is 12.6% of 660 rostered, the same figure
`src/api/roster_intelligence.py`'s module docstring records. Had the
join silently failed, these would read 0 and the harness would have
downgraded every PASS.

---

## 4. Outstanding — for the integration lane

| # | item | why it is not closed here | what closes it |
|---|---|---|---|
| 01 | `dynasty_new` (10-team, no IDP) | it has no local contract; it is served by the Sleeper-derived fallback | run §2 against the deploy with no `--league-key` |
| 12 | degraded `/league?tab=teamAssignment` | needs a deployed public-league section | §2; the three states are already pinned Python-side by `tests/api/test_team_assignment_availability.py` |
| 13 | latency | needs a timed HTTP request | §2; budget cited from `docs/GLOBAL_PERFORMANCE_STANDARD.md` (p95 ≤ 2 s, warm target 1 s). One sample per endpoint — a smoke measurement, reported as such, **not** a p95 |

### Two gaps worth naming rather than working around

**No API surface publishes the deployed commit.** EVIDENCE-L3 is defined
as "the named checklist executed against the **deployed SHA**", and
neither `/api/status` nor `/api/health` carries one. `--expect-sha` is
therefore recorded as *operator-asserted* provenance, and the artifact
stamps `shaPublishedByApi: null` so the two can never be confused. Take
the SHA from the deploy run, not from the response.

**`team-assignment.jsx` has no frontend test.** Its degraded contract is
pinned on the Python side only. The EVIDENCE-L4 half of check 12 would be
a component test in the shape of
`frontend/__tests__/components/activity-news-unavailable.test.jsx`
(`role="alert"` for hard-unavailable, `role="status"` for a partial
note). That is Claude 6's lane and is **not** written here.

---

## 5. Why the checks are trusted

63 tests in `tests/roster_intel/test_verification_pack.py`, in three
groups:

1. **every check passes a clean payload** — and with a non-zero
   denominator, so the fixture actually exercises it;
2. **every check fails when its property is violated** — ten mutations,
   one per check, each confirmed to turn its check red. A check that
   cannot be made to fail proves nothing about the payloads it passes;
3. **every check reports `UNMEASURABLE` on absent input** — the
   non-vacuity requirement, discharged by assertion rather than by
   reading the code.

Plus the harness rules (vacuous-pass downgrade, level capping, exit-code
precedence) and an EVIDENCE-L2 pass of checks 2–11 over the real
rebuilt board.

### Transport, exercised end-to-end

The check layer is proven by the suite above; the *transport* layer is
not reachable from pytest, so it was exercised by hand against a canned
local backend serving the suite's own fixtures. Measured 2026-08-19:

| scenario | expected | measured |
|---|---|---|
| healthy backend | exit **0**, 13/13 PASS, levels capped at the source | exit 0, 13 passed / 0 failed / 0 unmeasurable; check 02 reported EVIDENCE-L1 (its ceiling) while 12–13 reported EVIDENCE-L3 |
| `--base-url` omitted | exit **2** | exit 2, `::error title=No base URL` |
| connection refused | exit **2** | exit 2, every check UNMEASURABLE with the URLError named |
| backend returns 401 | exit **2**, **terminal not retried** | exit 2 in **0 s** — three retries × 4 s per endpoint would have taken ≈24 s+. The reason names both remedies and notes that a 401 on a route that should be *public* is itself the finding |

The last row is the one worth keeping: `verify-sharp-production.yml`
spent 40 minutes per run, on every push to main, retrying a 401 that was
never going to change.

**Measured mutation specificity, reported rather than engineered away.**
Six of the ten mutations turn exactly one check red. Four also trip
check 11, and one also trips check 04 — and in every case the collateral
is a *genuine* second violation: check 11's property is that the age
portfolio's population **is** the core, so any mutation changing the core
member count really does violate it, and making a starter also a reserve
really is a duplicate. The test therefore asserts "the intended check is
among the red ones" with a bounded allowance, not "exactly one is red".
Claiming the stricter property would mean weakening a check to buy a
tidier table.
