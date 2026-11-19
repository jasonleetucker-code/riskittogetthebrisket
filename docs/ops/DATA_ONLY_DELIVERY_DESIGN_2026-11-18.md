# Data-only delivery: decoupling data from the full code gate (design, shadow mode)

Audit-remediation Task 3, owner directive 2026-11-18. Status: **SHADOW MODE ONLY. Activation: BLOCKED — OWNER DECISION.**

This document records the problem, the evidence, a design, and the shadow instrumentation that this change adds. The
shadow observes every Deploy Production run and records what a data-only path *would* have done. It deploys, gates and
blocks nothing. Any path that ships a delta without the full L3 code gate changes a binding Agent OS rule
(`docs/AGENT_OPERATING_SYSTEM.md` §3: L3 "remains fully unconditional") and needs a separate owner decision (§9).

What this change adds:

| file | role |
|---|---|
| `scripts/classify_deploy_delta.py` | the DATA_ONLY / CODE rule (stdlib, git only, fail closed) |
| `scripts/data_delivery_gate.py` | the data gate set: the minimum checks a data-only delivery needs |
| `scripts/data_delivery_shadow.py` | shadow bookkeeping: resolve target/base (read-only REST), compare, aggregate, backtest |
| `.github/workflows/data-delivery-shadow.yml` | `workflow_run` observer of Deploy Production; never deploys |
| `tests/deploy/test_classify_deploy_delta.py`, `tests/deploy/test_data_delivery_shadow.py` | the rule, the fail-closed branches, the gate runner, the comparison, and the workflow's inability to act |

Not changed: `.github/workflows/deploy.yml`, `deploy/deploy.sh`, `scheduled-refresh.yml`, any server code, any box state.

## 1. Problem

Every Deploy Production run pays for the full code gate, whatever changed. Most runs ship data the scheduled refresh
committed (`scheduled-refresh.yml` dispatches `deploy.yml` after every `automated data refresh` or `freshness stamps`
commit), and those runs fail far more often than code pushes, because the hard gate still contains tests whose result
depends on the refreshed data. Each run costs about two runner-hours and restarts the backend, and every restart runs a
Chromium startup scrape (`conditional_startup_scrape` is OFF).

## 2. Evidence

**Coordinator measurement (verified 2026-11-18, last 100 Deploy Production runs):** 38 failed; data-triggered runs
failed 36 of 58 (62%) against 2 of 30 (7%) for code pushes; about 115 runner-minutes per run (8 shards), median wall
about 29 minutes; the backend restarts about 5 times a day from deploys.

**This change's own measurements (2026-11-18, read-only):**

- One successful run, 44289141366: pre-deploy jobs took 124 runner-minutes (8 shards 116.2, validate 6.6, the rest
  1.6) and 35 minutes from creation to the deploy job. Inside the validate job the data-relevant steps took: runtime
  import 3 s, contract FULL lane 2 s, live-data tests (advisory) 90 s.
- The data gate set on this tree, locally: `runtime_import` 1.8 s, `contract_full_lane` 1.5 s, `source_health` 1.9 s
  (advisory, open conditions), `tracked_data_privacy` 278 s (it reads every tracked file under the data roots).
- Live read-only resolve of dispatch run 44234235112: target `71cc45b7` (from its resolve-job log, `default`), base
  `e16f7bb0` (run 44193193657). Classified **CODE**: 98 data paths and 3 `config/model_registry/` paths.

**Backtest** (`python scripts/data_delivery_shadow.py backtest --runs-json <200 runs> --rows`, runs created
2026-11-03..2026-11-18, cancelled runs excluded; a dispatch run's target is taken as its `head_sha`, true for the
scheduled refresh's dispatches, which pass no `deploy_ref`, and flagged on 44 rows):

| | runs | full gate passed | full gate failed |
|---|---|---|---|
| classified | 138 | 80 | 58 |
| push | 94 | 66 | 28 |
| workflow_dispatch | 44 | 14 | 30 |
| **DATA_ONLY (rules below)** | **23** | 14 | **9** |
| CODE | 115 | 66 | 49 |
| CODE only because of `config/model_registry/` | 34 | 8 | 26 |
| CODE only because of `config/model_registry/` and docs | 41 | 12 | 29 |

The 9 DATA_ONLY deltas that failed the full gate had code byte-identical to a commit that had just passed it. Their
failing steps: 7 × `Run unit tests (hard gate — pure logic)` (runs 41789907470, 42496066177, 42821399496,
43075102338, 43333485414, 43741547744, 43935057527) and 2 × `Install tesseract-ocr` on several shards (43038689727,
43059307840). None failed the contract FULL lane. The unit-test failures are the data-coupled tests that PR #2239
(hermetic hard gate) inventories and pins: the full gate refused data, not code. Across all "data-like" deltas (the 23
plus the 34), 35 of 57 failed (61%), the same rate the coordinator measured.

What the backtest says: under the strict rules about one deploy in six is DATA_ONLY. A champion-invariant rule for
`config/model_registry/hill_scope_masters.json` would make it about two in five. And a data-only path activated today
would have shipped about 35 deliveries the full gate refused. That is why activation waits for a hermetic hard gate and
for shadow evidence (§7).

**Finding: a stale comment in `deploy.yml`.** Lines 7-8 say "Skip deploy for data-only commits from scheduled-refresh.
Data flows to production via the server's own scrape loop, not via git deploy." Neither is what happens.
`scheduled-refresh.yml` dispatches `deploy.yml` explicitly after every data or stamp commit. Its pushes use
`GITHUB_TOKEN`, so they never start a push run. `paths-ignore` omits `CSVs/**` and `config/**`, so a box-side commit
that touches `CSVs/` does start one (`scripts/deploy_trigger_audit.py`). This change leaves the strict L3 file alone.
The proposed wording for that comment: "Data-only commits are delivered by scheduled-refresh.yml's explicit dispatch
(its GITHUB_TOKEN pushes start no push run); `data/**` and `exports/**` are ignored here only so a box timer's
stamp-only push does not deploy."

## 3. Design

A deploy target is **DATA_ONLY** when its code tree is byte-identical to the code tree of the last fully validated
deployed commit (the BASE). For such a delta, every check whose verdict is a function of the code alone has already
passed on exactly this code. Only checks a data change can move need to run again: the **data gate set** (§5). Any
other delta, and any doubt, is **CODE** and takes the full gate unchanged.

```
deploy target ──► classify(base, target) ──► CODE ──────► full L3 gate (unchanged)
                         │
                         └──► DATA_ONLY ──► data gate set ──► [activation only] data delivery + box-side verification
```

In shadow mode the right-hand branch only records what it would have done (§6).

## 4. The classifier's exact rules (`scripts/classify_deploy_delta.py`)

`DATA_ONLY` if and only if:

1. base and target are full 40-hex SHAs that resolve to commits in the repository;
2. the base is an ancestor of, or equal to, the target. A rollback or a diverged history is CODE (the same
   fast-forward property `deploy.yml`'s guard asserts);
3. the code-tree digest of the target equals that of the base. The digest is sha256 over `mode type object-id\tpath\0`
   of every tracked entry classified **code**, in path order. Identity is git's own, so a one-byte edit, a mode change,
   an added and a deleted file all change it. The per-path diff is computed from the same two `git ls-tree -r -z`
   listings and must agree with the digests; if it does not, the answer is CODE (`internal_inconsistency`).

A tracked entry is **data** only when all of these hold:

| condition | value |
|---|---|
| path prefix (case-sensitive) | `CSVs/`, `data/`, `exports/` |
| git mode | `100644` only (no symlink `120000`, executable `100755`, submodule `160000`) |
| basename not in | `.gitattributes`, `.gitmodules`, `__init__.py`, `conftest.py`, `sitecustomize.py`, `usercustomize.py` |
| suffix (lower-cased) not in | `.bash .bat .cfg .cjs .cmd .conf .css .dll .exe .htm .html .ini .ipynb .js .jsx .mjs .ps1 .pth .py .pyc .pyi .pyw .service .sh .so .socket .timer .toml .ts .tsx .whl .yaml .yml .zsh` |
| reviewed exception | `exports/latest/dynasty_data.js`: the raw scraper export as `window.DYNASTY_DATA = {...}`; nothing executes or serves it |
| path components | no empty, `.` or `..` component |

**Everything else is CODE**, including every path nobody has classified: `src/`, `server.py`, `Dynasty Scraper.py`,
`scripts/`, `frontend/` (lockfiles included), `tests/`, `deploy/`, `.github/`, `requirements*`, `package*.json`,
`pyproject.toml`, docs, root files and **all of `config/`**.

Why these choices:

- The three roots are the ones the scheduled refresh commits (`CSVs/ exports/ data/...`) and the box timers push
  (`data/scrape_state`, `data/playerctx`). `deploy/deploy.sh` already treats the same three as auto-managed. On
  2026-11-18 the 12,184 tracked entries under them are `.json .csv .jsonl .zip .xlsx .md`, extensionless stamps, one
  `.gitkeep` and the one reviewed `.js` export. None is executable or a symlink.
- `config/` stays CODE. Most of it is policy the code executes (weights, thresholds, flags, curves). The parts
  automation writes were reviewed and kept CODE anyway. `config/draft_valuation/*` stores change served draft dollars
  when a promotion lands, and they change rarely (no commit from 2026-10-26 to 2026-11-18), so being strict costs
  nothing.
  `config/model_registry/*` changes with every Hill evidence commit (50 of 50 since 2026-11-01), and each of those
  rewrites `hill_scope_masters.json`, whose champion the contract's provenance stamp checks against the live
  constants. A champion-invariant content rule would unlock about 34 of 138 backtest deltas; that rule is DEFERRED
  until the shadow's `codePathGroups` confirm the gain.
- Docs stay CODE. The box reads `docs/valuation/evidence/**`, `docs/measurements/**`, `docs/sources/**` and
  `docs/owner/*.json`. The prose subset is already owned by `deploy.yml`'s `paths-ignore`, and this classifier does not
  keep a second copy of that list.
- Tests stay CODE. A changed test changes what the full gate means.

**Fail closed:** an empty, malformed or unknown base or target, a non-ancestor base, an unreadable or empty tree, or
any exception gives CODE, with the reason in `reasons` and `errorDetail`. Every receipt carries the rules and their
sha256 (`rulesDigest`), so verdicts made under different rule sets are never pooled.

**Where the base comes from.** In shadow mode: the newest successful Deploy Production run created before the observed
run (runs are serialised by `production-deploy`, so once a run completes, every earlier run has finished). The commit
it deployed is read from its "Resolve Deploy Target" job log. A `push` run's `head_sha` is its target by construction.
A `workflow_dispatch` run whose log cannot be read has no known target, never a guessed `head_sha`. After activation,
the base must come from a box-side record that only full-gate deploys write (§8).

## 5. The data gate set and the coverage comparison

### 5.1 The gate set (`scripts/data_delivery_gate.py run`)

Each gate repeats a step the full pipeline already runs, with the same command and environment, against the deploy
target tree.

| gate | blocking | mirrors | what it judges |
|---|---|---|---|
| `runtime_import` | yes | validate: "Python runtime import gate" | `import server` with this data in place |
| `contract_full_lane` | yes | validate: "API data contract check (FULL lane — blocking)" | builds the canonical contract from `exports/latest` + `CSVs/site_raw` with this code: schema, rank invariants, the 1..9999 scale, blend-hull integrity, pick-completeness census, pick-count and IDP floors, source health |
| `tracked_data_privacy` | yes | the hard-gate tests whose subject is the tracked data (`tests/api/test_tracked_artifacts_privacy.py`, `tests/trade/test_market_trade_privacy.py`) | no per-manager intelligence in a published file; the trade-ledger store is never tracked |
| `source_health` | no (advisory, as on PRs) | `scripts/check_source_health.py` | contract source-health partition, fetch freshness, content staleness |
| `livedata_tests` | no (advisory, as in validate) | validate: "Run live-data tests (advisory — non-blocking)" | the `livedata`-marked tests |

`wouldShip` is true only when at least one blocking gate ran and every blocking gate passed. A timeout or a command
that cannot start counts as a failure.

### 5.2 What the full gate covers for a data change, and what the data path keeps

Class C (`scripts/check_release_candidate.py`): `data/`, `exports/`, `CSVs/` are build, test and contract inputs, and
"a commit that changes them changes what the test suite means". So the question for each full-gate check is whether
its verdict can depend on class-C inputs. If it cannot, it is a function of class-B content, which is byte-identical
to a commit that passed; running it again re-tests the runner, not the delta.

| full-gate check (`deploy.yml`) | reads data roots? | data path |
|---|---|---|
| resolve, checkout, tree-identity assertion | no | the shadow checks out the target by SHA; activation re-checks code-tree identity on the box |
| lock install, `pip check`, `check_env.py` | no (lockfiles are code) | same lock installed for the gates |
| `py_compile`, ruff format, ruff check | no (`pyproject.toml` excludes `data`, `exports`; the classifier makes any `.py`/`.ipynb` under a data root CODE) | not needed |
| runtime import gate | possibly (import-time reads) | **kept**: `runtime_import` |
| generated leagues contract | no (`config/leagues`, code) | not needed |
| live-data tests (advisory) | yes | **kept, advisory**: `livedata_tests` |
| contract FULL lane | yes, by design | **kept**: `contract_full_lane` |
| deploy artifacts exist, deploy script syntax | no | not needed |
| frontend `npm ci`, `npm test`, build, bundle budgets | no (no frontend build or test reads a data root; nginx serves no `exports/`) | not needed; a data delivery ships no frontend artifact |
| wheelhouse, release artifact | no | not needed; the box keeps its verified release |
| hard gate: tracked-data invariant tests | yes (their subject is the data) | **kept**: `tracked_data_privacy` |
| hard gate: tests that run code over refreshable data (`newest_complete_raw_payload()`, `exports/latest`, `CSVs/site_raw`, `data/scrape_state`, server `TestClient`s that load the latest export) | **yes** | **not kept: the one loss.** See below |
| hard-gate completeness proof | no | n/a |
| deploy job: box-side `verify-deploy.sh` (health, public URL, served-board coverage #451), post-deploy smoke, live health | yes | **kept unchanged** on any activated path (§8) |

**The lost coverage, and why it may not stay lost.** Some blocking hard-gate tests read refreshable class-C data. A
static census on 2026-11-18 finds 265 of 1,444 test files that name a data root or a data helper (102 use the
archive / `newest_complete_raw_payload` family, 103 name `CSVs`, 51 `exports/latest`, 44 `data/scrape_state`), plus
server `TestClient`s that load the latest export indirectly. A data change can flip these tests. That is exactly the
backtest's 7 unit-test refusals of byte-identical code.

The data gate set does not re-run them. Selected statically, they would be a third of the suite and still incomplete
(indirect reads). The design closes the gap from the other side: **the activation precondition is a hard gate that
reads no refreshable data root** (§7).

- PR #2239 starts this: a static guard against rolling-archive literals and missing-data skips, and pinned fixtures for
  the known offenders.
- Extend that guard to every data root and prove it with a dynamic census: an opt-in pytest plugin, using
  `sys.addaudithook` `open`/`os.listdir`/`os.scandir` events, that records each blocking test opening a path under
  `CSVs/`, `data/` or `exports/`. Its output must be empty, or every entry must be an immutable pinned fixture.

Once that holds, no blocking hard-gate verdict can be moved by a data change. The full gate's data-dependent safety
then sits where it already belongs: the contract FULL lane, the tracked-data privacy tests and the box-side
verification. All three are kept.

Two further observations, so the loss is not overstated:

- The full gate is not production's only data barrier. The box scrapes itself every 2 hours (`schedule_loop`) and at
  every boot, and those boards reach users through the box's own promotion guard and contract health. None of them
  passes through the hard gate. A refused data deploy does not keep that data out of production; it keeps out the CI
  scrape's copy.
- Time-dependent tests (a test that starts failing on a date) are not a data effect. Production already runs the code
  on that date. To keep that signal, and runner-image drift, the activation design bounds the age of the base's full
  validation (24 hours) and keeps a scheduled full-gate run (§8).

## 6. Shadow wiring (this change)

`.github/workflows/data-delivery-shadow.yml`, triggered by `workflow_run: [Deploy Production], types: [completed]`, or
a manual `workflow_dispatch` with a run id:

1. **Resolve** (`data_delivery_shadow.py resolve`, read-only REST, `actions: read`): the observed run, its jobs (the
   full verdict), its target, and the base.
2. **Classify** (`classify_deploy_delta.py`, the workflow commit's copy) → `classification.json`.
3. **DATA_ONLY only:** check out the target tree, install its locked dependencies, and run the data gate set →
   `gates.json`. This is the only `continue-on-error` step: a failing gate is a recorded "would refuse", not a broken
   shadow.
4. **Compare** (`data_delivery_shadow.py compare`) → `shadow.json` and a job-summary table.
5. **Upload** `data-delivery-shadow-<deploy run id>` (90-day retention).

Outcomes (one per observed run):

| outcome | meaning |
|---|---|
| `AGREE_SHIP` | DATA_ONLY; fast path would ship; full pre-deploy gates passed |
| `AGREE_REFUSE` | DATA_ONLY; both refuse |
| `UNSAFE_DISAGREEMENT` | DATA_ONLY; fast path would ship what the full gate refused. Every one is triaged |
| `CONSERVATIVE_DISAGREEMENT` | DATA_ONLY; fast path would refuse what the full gate passed |
| `NO_FULL_VERDICT` | the full run reached no gate verdict (e.g. only runner-preparation steps failed: `Install `, `Set up `, `Checkout`, ...; an unnamed failure counts as a gate failure) |
| `FAST_PATH_NOT_RUN` | DATA_ONLY, but the gate receipt is missing (a shadow defect) |
| `NOT_APPLICABLE` | CODE; the full path is the only path |

Recorded timing: full pre-deploy runner minutes and wall minutes, the gate seconds (blocking and total), and the shadow
job's wall clock (checkout, install and gates included).

Why a separate workflow and not a job in `deploy.yml`:

- `deploy.yml` is the strict L3 file.
- A workflow in the `production-deploy` group can evict a queued deploy
  (`tests/deploy/test_production_deploy_concurrency.py`); the shadow has its own per-run group.
- `workflow_run` sees human-started deploy runs only: GitHub creates no `workflow_run` run for a run started by
  `GITHUB_TOKEN`, which is how scheduled-refresh dispatches its data deploys. Those deploy runs dispatch the shadow
  themselves (`deploy.yml` job `dispatch-data-delivery-shadow`, STAB-10), so every deploy run is still observed.
- The agreement metric needs the full verdict, so the shadow runs after completion instead of polling a runner for an
  hour.

Tests pin what it cannot do: no `secrets.`, read-only permissions, no `environment`, no ssh/scp/curl/`gh`/push, no
production URL, no `production-deploy` group, no reference to it from `deploy.yml`, and the deploy run id reaches the
shell only as a validated numeric env var.

## 7. Shadow plan: when the evidence supports asking for activation

Collect the shadow artifacts and run:

```bash
gh run list --workflow data-delivery-shadow.yml --limit 200 --json databaseId
gh run download <id> ...            # per run, into one directory
python scripts/data_delivery_shadow.py aggregate --receipts <dir>
```

`aggregate` reports `activationEvidenceMet` only when all of these hold. Evidence never activates anything; the owner
decides.

1. **zero `UNSAFE_DISAGREEMENT`**, each historical one triaged and its cause fixed (expected today: the non-hermetic
   tests; PR #2239 removes the known ones);
2. **at least 30 compared DATA_ONLY deliveries** (`AGREE_*` or `*_DISAGREEMENT`);
3. **spanning at least 14 days**;
4. **zero `FAST_PATH_NOT_RUN`**;
5. **one rule set throughout** (a single `rulesDigest`).

Separate preconditions, not measured by the shadow: PR #2239 merged; the hermetic-input guard extended to every data
root, with an empty dynamic census (§5.2); every `CONSERVATIVE_DISAGREEMENT` explained.

Also reported: runner-minutes saved on agreed ships (full pre-deploy runner minutes minus the shadow job's wall; about
124 − 8 per delivery on the run measured in §2), and the code groups that kept deltas CODE, which is the input to the
deferred `config/model_registry` rule.

## 8. Activation design (owner-gated; NOT built)

Phase C1 (CI saving only, same restart):

- `deploy.yml` gains a `classify` job after `resolve`. It reads the base from a NEW box record,
  `.deploy-state/<app>.last_full_gate_deploy_commit`, written only by the full path. It requires that record to equal
  the running process's `/api/status` `build.commit` and to be at most 24 hours old. It classifies with
  `classify_deploy_delta.py`.
- DATA_ONLY, and the repository variable `DATA_DELIVERY_FAST_PATH` set to `on` → `data-gate` job → existing `deploy`
  job in data mode. CODE, the variable unset, or any classifier doubt → the full path, byte-for-byte as today.
- Data mode on the box: fetch the target and re-run the classifier there against the running commit (a second,
  independent identity check). Then `git checkout --force <target>`: only data paths change, because the code tree is
  identical. Skip the artifact and frontend staging (the verified release stays), restart, keep `verify-deploy.sh`,
  the post-deploy smoke and the live health check, and keep the temporal-ledger / source-history steps. Write
  `last_data_delivery_commit`. Never advance `last_full_gate_deploy_commit`. `last_successful_deploy_commit` keeps its
  current meaning (what the box runs) so the fast-forward guard still works.
- The smoke step's `build.commit == target` assertion becomes `build.commit == code base` plus a `dataCommit == target`
  check. A no-restart variant leaves `build.commit` at the base, which is correct for code (`src/api/build_identity.py`
  reads it once at import).
- It runs inside the same `production-deploy` group (it is a job of `deploy.yml`), so box state stays serialised.

Phase C2 (restart avoidance): separately owner-gated, and only after the measurement in §10.

**Rollback.**

- Kill switch: unset `DATA_DELIVERY_FAST_PATH`; the next deploy takes the full path. No code change is needed.
- Bad data: redeploy the previous commit with `allow_non_fast_forward`. A non-fast-forward is always CODE, so a
  rollback always takes the full gate.
- Bad classifier: unset the variable and revert the classifier. The full path does not depend on it.

## 9. The Agent OS amendment the owner would need to approve

Proposed text, to be inserted in `docs/AGENT_OPERATING_SYSTEM.md` §3 directly after the paragraph that begins
"**L3 — Production candidate validation. This remains strict and is NOT weakened by this policy.**":

> **Data-only delivery (owner decision YYYY-MM-DD; narrows L3 for one change class only).** A Deploy Production target
> whose code tree is byte-identical to the last commit that passed the full L3 gate and was deployed, as decided by
> `scripts/classify_deploy_delta.py` (every tracked path outside the reviewed data roots `CSVs/`, `data/`, `exports/`
> compared by git mode and object id; only regular, non-executable, non-code-suffix files under those roots are data;
> any unknown path, unresolvable base, non-fast-forward target or classifier error is CODE), may be delivered after the
> data gate set (`scripts/data_delivery_gate.py`: runtime import, contract FULL lane and tracked-data privacy blocking;
> source health and live-data tests advisory) instead of re-running the code gate. This holds only while all of the
> following are true: (1) the base's full gate ran within the previous 24 hours; (2) no blocking hard-gate test reads a
> data root, as enforced by the hermetic-input guard; (3) the box-side post-delivery verification (`deploy/verify-deploy.sh`,
> the post-deploy smoke and live health checks) runs unchanged; (4) the delivery records its own receipt and never
> advances the last-full-gate record; and (5) the repository variable `DATA_DELIVERY_FAST_PATH` is `on`. Every other
> change, and every delivery that fails any condition, takes the full L3 gate unchanged. This changes neither L2 nor
> the release-candidate gate, and removing the variable restores fully unconditional L3.

Until that text is approved and merged, L3 stays fully unconditional, and the shadow is the only consumer of this
design.

## 10. Restart avoidance (investigation only; no box change made)

What a deploy does today. `deploy/deploy.sh` checks out the target while the old process is still serving, then
`restart_service`. Every successful deploy restarts the backend, and every boot scrapes 3 s later with Chromium
(`conditional_startup_scrape` OFF). That is 6 to 8 startup scrapes a day
(`docs/ops/SCRAPE_CADENCE_MEASUREMENT_2026-11-09.md` §2).

Can the server load refreshed files without a restart?

| mechanism | exists? | effect |
|---|---|---|
| reload endpoint / file watch / SIGHUP | **no** | nothing re-primes the in-memory board from disk while running |
| `POST /api/scrape` (admin session) | yes | a full scrape, not a reload; it re-primes from the scrape's own output |
| in-process `schedule_loop` (every 2 h) | yes | re-primes after each box scrape; each restart resets it to boot + 2 h |
| `conditional_startup_scrape` (D-2) | yes, OFF (owner-reserved) | skips the boot scrape when the board is under 2 h old and healthy; cuts restart cost, not restarts |
| boot `load_from_disk()` | yes | **prefers the box's own runtime cache `data/dynasty_data_*.json` (gitignored) over the delivered `exports/latest`**; the delivered board is a fallback/recovery source only |
| per-request disk readers | yes | `_per_source_freshness` reads `data/scrape_state` stamps per request (30 s memo); source CSV parse caches are keyed by mtime (`_parse_source_csv_cached`), so a delivered CSV is used at the next contract build, including `POST /api/rankings/overrides` builds; `Draft Data.xlsx` is keyed by (path, mtime_ns, size) |

Findings:

1. **Part of what a data delivery is for needs no restart.** The source-freshness stamps (`data/scrape_state`), the
   reason `CLAUDE.md` gives for force-adding that directory, are read from disk per request. A file update shows within
   30 s.
2. **The served board does not change from a delivery alone.** The running process keeps its in-memory board. After a
   restart it loads the box's own runtime cache first. So a delivered `exports/latest` changes what users see only when
   that cache is missing, collapsed or degraded. The delivered source CSVs reach the board at the next contract build
   (the next box scrape or a restart).
3. **The box's own scrape rewrites the same roots** (`CSVs/site_raw`, `exports`, `data`) every 2 hours, and
   `deploy.sh`'s `checkout --force` overwrites the box's copies. Delivered data and box-scraped data race, and the
   winner depends on ordering. Before building a reload path, measure what a delivery provides that the box's own
   scrape does not: stamps for sources the box cannot scrape, CI-only outputs such as `data/ros`, the draft workbook.
   Much of a delivery's value may be the per-request-read stamps alone.
4. **No-restart delivery would need on the box:**
   - re-verification that the target's code tree equals the running code tree (the classifier, run on the box);
   - `git checkout --force <target>` (no rsync needed: only data paths differ);
   - a reload signal that runs `load_from_disk()` + `_prime_latest_payload()` + checkout recovery under the same lock
     the scrape uses. This would be a new loopback-only admin action, separately reviewed;
   - the data subset of `verify-deploy.sh`;
   - a `dataCommit` identity beside `build.commit`.
5. **Atomicity and rollback risks:**
   - a git checkout is not atomic across files, so per-request readers can see a mix mid-checkout. Today the same
     window exists between checkout and restart;
   - without an explicit re-prime, stamps and override builds would be new while the default board is old (mixed
     generations);
   - a box scrape running during the checkout writes the same files;
   - the append-only stores `deploy.sh` feeds (temporal ledger, source history) cannot be un-recorded by a data
     rollback, the same as today;
   - rollback to an older data commit is non-fast-forward, so it takes the full path by design.

Recommendation: do C1 (CI saving) first. Measure point 3. Treat C2 as its own owner-gated unit; turning
`conditional_startup_scrape` ON is the smaller, separately owner-reserved alternative for the restart cost.

## 11. Applicability check (engineering reliability priorities)

- `APPLY_NOW`: deterministic replay of real history (backtest); fail-closed classification with receipts and a rules
  digest; read-only least-privilege CI.
- `ALREADY_COVERED`: release-gate step classification (`config/ci/release_gate_classification.json`); the
  production-deploy concurrency invariant.
- `DEFERRED_BY_AUTHORITY`: the fast path itself, the box-side records, the reload mechanism, the champion-invariant
  `config/model_registry` rule, and the dynamic hermeticity census plugin (an activation prerequisite).
