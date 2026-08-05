# Test Gap Matrix

**Deliverable section 16 of the master site audit.** Sources: the W24 shard
(`docs/master-site-audit/evidence/registry/W24.jsonl`, 10 findings),
`docs/master-site-audit/evidence/test-results-summary.txt`, the W24 artifacts under
`docs/master-site-audit/evidence/W24/`, and the adversarial verdict
`docs/master-site-audit/evidence/verify/W24-F003.json`. Findings-file commit `fb4a15a0`;
measurements taken on the live checkout at `e96c06ef` and re-run for this document.

---

## 0. The suite is green, and the green is real

| Suite | Result | Duration |
|---|---|---|
| Python (`pytest tests/ -q`) | **6,278 passed, 40 skipped, 0 failed**, 496 subtests passed | 1,929.98 s (32 m 10 s), exit 0 |
| Frontend (`npm --prefix frontend test`) | **104 test files passed, 1,754 tests passed**, 0 failed | 32.38 s, exit 0 |

Re-run: `.venv/bin/python -m pytest tests/ -q --tb=short -rf` and
`npm --prefix frontend test`. Archived output:
`docs/master-site-audit/evidence/pytest-full.txt` (line 99),
`docs/master-site-audit/evidence/vitest.txt` (tail).

Two facts about that run worth stating up front, because they bound everything below:

- **Python version skew.** The archived run used `.venv/bin/python` 3.11.15. CI runs 3.12,
  and `pyproject`/`.python-version` pin 3.12. The green above is a 3.11 green.
- **One warning was emitted and is a real route-registration defect, not a test failure:**
  `UserWarning: Duplicate Operation ID get_health_api_health_get for function get_health`.

This document is about what the green **does not** prove. Section 8 is what it does.

---

## 1. Summary — the gap classes, ranked

| # | Gap class | Measured size | Finding | Status |
|---|---|---|---|---|
| 1 | Skip sites undercounted 6× in the audit's own census | 27 declared vs **166 actual**, 43 files | W24-F001 (P1) | Re-verified here |
| 2 | 22 tests written for a known live-only defect execute in **neither** CI tier | 22 tests, 0 executions | W24-F002 (P1) | Re-verified here |
| 3 | 13 E2E tests skipped in the only workflow that runs them, incl. the non-screenshot half | 13 tests | W24-F004 (P1) | Re-verified here |
| 4 | Pure-logic tests exempted from the blocking gate by a filename rule | 286 advisory; **40** probe-proven pure (33 wholly) | W24-F003 (**P1→P2, rescoped**) | Verifier-corrected |
| 5 | Sleeper league-context fetch: 0 tests exercise the live branch | 0 of 6,326 | W24-F005 (P2) | Re-verified here |
| 6 | Shipped `config/leagues/registry.json` never routed through an endpoint under test | `leagues_share_scoring` inverted vs prod | W24-F006 (P2) | Re-verified here |
| 7 | 104 Python + 39 frontend tests assert by grepping source text | 1.8% / 1.1% | W24-F010 (P3) | Re-verified here |
| 8 | A 722 KB "golden baseline" with zero automated consumers | 0 consumers | W24-F009 (P3) | Re-verified here |
| 9 | One genuinely vacuous self-comparison | 1 of 5,867 | W24-F008 (P3) | Re-verified here |
| — | `percentile_to_value` "has zero numeric pins" | **Claim does not hold** — a blocking-tier freeze guard pins 10 ranks | W24-F007 (P2) | **Corrected below (§6.1)** |

---

## 2. The skip census: 27 declared, 166 actual

`evidence/test-results-summary.txt:13` labels its 27-line list "the declared set". That list is
produced by a grep for `pytest.skip(` / `pytest.mark.skipif` against a suite that is
majority `unittest.TestCase`. The union pattern finds **166 skip sites across 43 files** —
139 of them `self.skipTest(...)` / `unittest.skipIf(...)`, invisible to the census grep.

| File | Skip sites | Visible to the census grep? |
|---|---|---|
| `tests/api/test_launch_readiness.py` | 26 | no |
| `tests/api/test_single_curve_live.py` | 17 | no |
| `tests/api/test_draft_capital.py` | 17 | no |
| `tests/api/test_source_monitoring.py` | 15 | no |
| `tests/api/test_picks_end_to_end.py` | 12 | no |
| — remaining 38 files | 79 | mixed |

Re-run: `.venv/bin/python - <<'PY'` … union regex
`pytest\.skip\(|self\.skipTest\(|pytest\.mark\.skipif|unittest\.skipIf|unittest\.skipUnless|skipIf\(`
over `tests/**/*.py` — full script in `docs/master-site-audit/evidence/W24/skip-census.txt`.
Result reproduced for this document: `TOTAL 166 files 43`.

**Why this matters mechanically:** a skipped test and a passing test are byte-identical in
`pytest -q` output, and no workflow asserts a minimum collected/passed count. The declared
figure is what a reader uses to size the risk (W24-F001).

`tests/api/test_draft_capital.py` is **not** `livedata`-marked, so its 17 skip sites sit in the
**blocking** tier: if `openpyxl` or `CSVs/Draft Data.xlsx` goes missing, the only check that a
Sleeper-traded pick moves auction dollars in the right direction becomes a pass-by-not-running
inside a green PR.

### 2.1 Which skips actually fire, and what each leaves untested

Running all 43 skip-declaring files in one pass: **807 passed, 35 skipped in 378.68 s**.

| Skips fired | Module | Reason | Invariant left untested in CI | CI disposition |
|---|---|---|---|---|
| 22 | `tests/roster_intel/test_real_rosters.py` | `nfl player dump not present in this checkout` | Every `/rosters` + terminal headline metric **varies across the 12 real teams** — positional coverage, fragility, clogger value, entry rate, lineup score, positional deficit, competitive-window probabilities | **Permanent.** Input is gitignored (`.gitignore:45`) and untracked; module is also `livedata`-marked → 0 executions in either tier |
| 10 | `tests/consensus_edge/test_panel.py` | `shallow clone: as-of reconstruction needs full history` | As-of board reconstruction | **Not a CI gap.** `pr-validation.yml:65` and `deploy.yml:43` both set `fetch-depth: 0`, so these run in CI. They skip only in shallow containers and `smoke-test.yml` |
| 3 | `tests/api/test_fantasypros_idp_integration.py` | `No live API fixture present` | FantasyPros IDP live-fixture path | **Permanent.** Gated on env `LIVE_API_FIXTURE`, set in no workflow |

Re-run (all 43 files): `.venv/bin/python -m pytest <43 files> -q -rs --tb=no`.
Re-run (livedata tier alone, reproduced for this document):
`.venv/bin/python -m pytest tests/ -q -rs --tb=no -m livedata` → **261 passed, 25 skipped,
6,040 deselected in 44.53 s** (22 `test_real_rosters` + 3 `fantasypros_idp_integration`).

### 2.2 The other 139 skip sites are latent, not active

`exports/latest/` (8 files) and `CSVs/site_raw/` (24 files) **are tracked in git**, so the
"No live data" / "CSV missing" / "KTC export not available" gates resolve *false* in a clean
checkout and the tests run. Deleting or renaming any of those tracked artifacts silently
converts hundreds of assertions into passes-by-not-running with no CI signal at all
(`evidence/W24/skip-census.txt`).

### 2.3 `test_real_rosters.py` — 22 tests, zero executions, both tiers

This is the sharpest single case (W24-F002). The module docstring records the exact defect it
exists to catch: *"`_positional_coverage` once returned exactly 100.00 for all 12 teams — a
constant masquerading as a score. Synthetic fixtures would not have caught that, because it only
collapsed on live data."*

| Tier | Command | Result |
|---|---|---|
| Blocking | `pytest tests/roster_intel/test_real_rosters.py -m 'not livedata' -q --co` | `no tests collected (22 deselected)` |
| Advisory | `pytest tests/roster_intel/test_real_rosters.py -m livedata -q -rs --tb=no` | `22 skipped in 0.11s` |
| Input tracked? | `git ls-files --error-unmatch data/public_league/nfl_players_full.json` | `Did you forget to 'git add'?` |

All three re-run and reproduced for this document. Sixteen named guards are inert, including
`test_fragility_varies_and_is_not_the_old_constant`,
`test_trajectory_axis_is_live_not_pinned` and
`test_eligibility_join_is_complete_on_the_real_league`.

What works: the two *other* inputs the fixture needs — `data/sleeper_last_good.json` and
`data/ros/aggregate/latest.json` — **are** tracked, so the gate that fires is precisely the
untracked one, and the skip message names it honestly.

---

## 3. What `tests/conftest.py` neutralises, and the live paths no test exercises

`tests/conftest.py` deliberately removes two production inputs from every test in the suite.
Both removals are correct in intent (keep the suite offline and independent of the
commissioner's Sleeper settings) and both are implemented at the *environment* level rather than
at the *seam*, which is why they take working code out of coverage rather than just taking the
network out.

| conftest line | What it does | Production code path that consequently runs in **zero** tests |
|---|---|---|
| `tests/conftest.py:43` — `os.environ.pop("SLEEPER_LEAGUE_ID", None)` | Clears the Sleeper league id | The live-derivation branch of `src/api/data_contract.py::_resolve_league_context` (`:6212-6248`) |
| `tests/conftest.py:52` — `LEAGUE_REGISTRY_PATH = "/nonexistent/path/for/tests.json"` | Points the registry at a missing file | Every consumer of the **shipped** `config/leagues/registry.json`, via `src/api/league_registry.py` |

conftest.py is honest about the first one — lines 31-35 state plainly *"the live derivation
branch is NOT exercised by this suite"* and *"the fallback below lands on the same numbers the
live league would produce today, so the suite agrees with reality by coincidence rather than by
construction."* W24-F005 quantifies that concession; it is not a discovery against a silent
codebase.

### 3.1 `_resolve_league_context` — the untested branch that sets all 72 slot-pick values (W24-F005)

Under the conftest environment the function returns its fallback dict at line 6218, **30 lines
before the network call**:

```
ctx: {'roster_count': 12, 'bonus_rec_te': 0.0, 'fetched_from_sleeper': False}
```

Re-run (reproduced for this document): import `tests.conftest`, clear
`data_contract._LEAGUE_CONTEXT_CACHE`, call `data_contract._resolve_league_context()`.
The finding's original probe additionally installed a `urllib.request.urlopen` spy that raises on
any call and recorded **zero calls attempted**.

Uncovered as a result: the URL construction, the `total_rosters` parse, the `bonus_rec_te` float
coercion, the `size > 0` guard, the 1 h cache fill, and the exception fallback.

`N` (roster count) is the divisor in the pick ladder — `pickLadderIndex = (round - 1) * N + slot`
(`data_contract.py:8356-8362`). The fallback `N=12` happens to equal `dynasty_main`'s real
`teamCount`, so **the board is correct today by coincidence**. `dynasty_new` already ships
`teamCount: 10` in `config/leagues/registry.json` (verified below). At N=10 a round-3 pick 1.01
should index rookie 21, not rookie 25 — and no test in the repository fails.

What works: `_derive_tep_multiplier_from_league` **is** properly unit-tested with injected
contexts, including the clamp and the `fetched_from_sleeper=False` distrust rule
(`tests/api/test_source_overrides.py:864-887`, `:1026-1031`). It is only ever fed a dict a test
built, never one this function produced.

### 3.2 The league registry — the test environment inverts the production answer (W24-F006)

| | Under `tests/conftest.py` | Live server (`:8000`) |
|---|---|---|
| `active_leagues()` | `[]` | `dynasty_main`, `dynasty_new` |
| `get_default_league()` | `None` | `dynasty_main` |
| `leagues_share_scoring('dynasty_main','dynasty_new')` | **`False`** | **`True`** (both `superflex_tep15_ppr1`) |
| `GET /api/leagues` | `{"leagues":[],"defaultKey":null}` | two full league blocks |

Re-run (both halves reproduced for this document): import `tests.conftest` then call
`src.api.league_registry`; and `curl -s http://127.0.0.1:8000/api/leagues`.

This inverts the CLAUDE.md rule under test — *"`/api/data`, `/api/rankings/overrides` — 503 only
when scoring profiles genuinely differ"* — between the test environment and production. The
shipped registry reaches the production parser in exactly one place,
`tests/api/test_config_parity.py:163-172`, which asserts only shape (non-zero leagues, profile
not literally `"default"`) and never routes a request through it.

The shipped file, verified from `config/leagues/registry.json`:

| key | scoringProfile | active | teamCount | idpEnabled |
|---|---|---|---|---|
| `dynasty_main` | `superflex_tep15_ppr1` | true | 12 | true |
| `dynasty_new` | `superflex_tep15_ppr1` | true | 10 | false |

A renamed `scoringProfile`, an `active: false`, or a malformed `rosterSettings` block changes
which league a request resolves to and whether `/api/data` 503s — with no routing test to notice,
because every routing test builds its own registry in `tmp_path`.

What works: `tests/api/test_league_routing.py` is thorough on the routing **logic** against three
separate synthetic registries, one of which deliberately encodes the two-same-one-different
profile shape. `tests/api/test_config_parity.py` correctly restores `LEAGUE_REGISTRY_PATH` in
`setUpClass`/`tearDownClass` so it does not leak.

---

## 4. The `livedata` tier — what runs advisory-only, and what would silently rot

`tests/conftest.py:137-144` adds the `livedata` marker **by file basename** (`item.path.name`
against the `_LIVEDATA_MODULES` frozenset at `:87-125`). `pr-validation.yml:164` is the hard gate
(`pytest tests/ -x -q -m "not livedata"`); `:166-180` is the advisory step and carries
`continue-on-error: true`.

**286 of 6,326 collected tests (4.5%) run only in the non-blocking step.**
Re-run: `.venv/bin/python -m pytest tests/ --co -q -m livedata | tail -1`
→ `286/6326 tests collected (6040 deselected)`.

### 4.1 W24-F003 as verified — the author's numbers were corrected

The adversarial verifier **rescoped** this finding (`evidence/verify/W24-F003.json`, verdict
`rescoped`, **P1 → P2**). Report the verified position, not the authored one:

| Claim | Authored | **Verified** |
|---|---|---|
| Tests proven pure by the I/O probe | 46 | **40** (the probe run itself printed `40 passed`) |
| Tests in *wholly* pure modules | — | **33** (`test_dlf_scraper.py` 9 + `test_fetch_flock_fantasy_rookies.py` 24) |
| 286 advisory tests attributable to the basename rule | all 286 | **240**; the other **46** come from explicit `@pytest.mark.livedata` / `pytestmark` decorators authors applied deliberately |
| `blastRadius.playersAffected` | 1,092 (whole board) | **516** — the union of live-contract rows carrying a `dlfSf` (277), `flockFantasySf` (378) or `dlfIdp` (139) vote |
| Priority | P1 | **P2** — a latent CI-integrity defect, not a live product defect |

The verifier also named two guards the finding omitted: `pr-validation.yml:170-174` keeps the
static `test_source_floor_invariant` hard gate and the deploy-time #451 served-board gate, both
of which **would** catch a gross parser breakage (zero or collapsed rows). What escapes is a
subtle mapping regression that keeps row counts plausible — e.g. `fetch_dlf.py`'s `_rank_of`
column preference picking the wrong rank column.

### 4.2 Per-module I/O audit-hook probe — what each exempted module actually opens

Measured with `sys.addaudithook('open')` over every `_LIVEDATA_MODULES` entry
(verifier's independent rerun, `evidence/verify/W24-F003.json`):

| Module | Paths opened under `exports/` `CSVs/` `data/` | Tests | Verdict |
|---|---|---|---|
| `tests/adapters/test_dlf_scraper.py` | **0** | 9 | Pure logic — misplaced |
| `tests/scripts/test_fetch_flock_fantasy_rookies.py` | **0** | 24 | Pure logic — misplaced |
| `tests/api/test_dlf_source.py` | 1 | 13 | 7 of them (the two temp-CSV classes) are pure; recorded as "STILL OPEN" in `tests/test_livedata_policy.py`'s own docstring |
| `tests/canonical/test_ktc_reconciliation.py` | 1 | 13 | Genuinely data-coupled (module-level KTC CSV load) |
| `tests/api/test_single_authority.py` | 48 | 9 | Correctly exempted |
| `tests/api/test_launch_readiness.py` | 46 | 26 | Correctly exempted |
| `tests/api/test_player_identity_regression.py` | 46 | 26 | Correctly exempted |
| `tests/api/test_single_curve_live.py` | 46 | 29 | Correctly exempted |
| `tests/api/test_source_monitoring.py` | 46 | 18 | Correctly exempted |
| `tests/api/test_picks_end_to_end.py` | 46 | 17 | Correctly exempted |
| `tests/api/test_pick_refinement.py` | 46 | 16 | Correctly exempted |
| `tests/api/test_fantasypros_idp_integration.py` | 45 | 26 | Correctly exempted |
| `tests/api/test_per_source_freshness.py` | 24 | 8 | Correctly exempted |
| `tests/api/test_pick_rookie_anchor.py` | 46 | 6 | Correctly exempted |

Re-run: `PYTHONPATH=docs/master-site-audit/evidence/W24 W24_IOPROBE_OUT=/tmp/io.txt
.venv/bin/python -m pytest <module> -p ioprobe -q --tb=no`. Probe source (40 lines):
`docs/master-site-audit/evidence/W24/ioprobe.py`.

**Eleven of fourteen basename-rule exemptions are correct.** The rule is not scattershot; it is
too coarse in exactly two places.

### 4.3 What would silently rot

The one case where the advisory tier already caused a live guard to fail invisibly is documented
inside the codebase itself, at `tests/canonical/test_hill_percentile_constants_tripwire.py:20-30`:
`tests/canonical/test_ktc_reconciliation.py` — then the only test pinning what the Hill
percentile constants produce — had **all 10 of its cases failing on `main`** as of 2026-07-30,
baselined 2026-04-20 against constants promoted since. Nobody saw it, because conftest
auto-marks that module `livedata` and CI runs it `continue-on-error`. That is the failure mode of
this tier, observed rather than hypothesised. It was repaired by adding a hard-gated tripwire
(see §6.1), not by un-marking the module.

Latent and not yet active: `_LIVEDATA_MODULES` is a basename set, so a future colliding basename
would exempt an unrelated module. Six basename collisions exist today (`test_calibration`,
`test_endpoint`, `test_replacement`, `test_scoring`, `test_service` ×5, `test_store`) — **none**
currently matches a livedata entry (W24-F003 `dependencies`).

---

## 5. Tests that pass without proving the claimed behaviour

An AST scan across **5,867 Python test functions** produced these totals
(`docs/master-site-audit/evidence/W24/vacuity-scan.json`; re-run:
`.venv/bin/python docs/master-site-audit/evidence/W24/vacuity_scan.py`):

| Class | Count | Share | Real problem? |
|---|---|---|---|
| Assert-free test bodies | 17 | 0.29% | **No — false alarm.** See below |
| Self-comparisons (`x == x`) | 3 | 0.05% | **1 of 3** is genuinely vacuous |
| Functions whose every assertion is shape-only (`assertIn` / `assertTrue` / `assertIsInstance` / `assertIsNotNone`) | 241 | 4.1% | Weak, not vacuous |
| Trivially-satisfiable assertions (mostly `assert a or b` disjunctions) | 16 | 0.27% | Mostly deliberate |
| Assertions that only grep source text | 104 | 1.8% | Weak — see §5.3 |
| Mock-echo (asserts a literal the test installed on a mock) | 4 | 0.07% | **No** — all 4 are legitimate pass-through contracts |

### 5.1 The 17 assert-free bodies are not vacuous — the scanner is AST-local

Spot-checked for this document: `tests/api/test_fantasypros_idp_integration.py:220-226`
(`test_dl_curve_monotone` / `_lb_` / `_db_`) delegate to `self._assert_family_monotone(family)`,
which asserts collapse-detection (`assertGreaterEqual(distinct, len(effs)//2)`).
`tests/api/test_pick_refinement.py:92-101` delegate to `self._check_round(year, rnd)`.
`tests/adapters/test_scraper_bridge_adapter.py:66` is a deliberate "constructor does not raise"
smoke test, paired with `test_invalid_signal_type_raises` on the next line.
`tests/api/test_single_curve_live.py:1024` re-invokes an import-time validator that raises.

**We found no vacuous assert-free test.** The scanner counts assertions in the test body only;
delegation to a helper is invisible to it.

### 5.2 The one genuinely vacuous test (W24-F008, P3)

`tests/consensus_edge/test_scoring.py:301`, in `test_param_set_id_is_stable`:

```python
self.assertEqual(params_mod.load()["paramSetId"], params_mod.load()["paramSetId"])
```

`params.load()` memoizes into a module-level `_CACHE` (`src/consensus_edge/params.py:25`) and
returns it verbatim when `path=None, refresh=False` (`:58-62`). Both sides are the same dict
object's same key. Verified for this document:

```
same object: True
```

Re-run: `.venv/bin/python -c "import tests.conftest; from src.consensus_edge import params;
a=params.load(); b=params.load(); print('same object:', a is b)"`

A `paramSetId` derived from `id()`, a timestamp, or unstable dict ordering passes this test
unchanged — the hash is computed exactly once. Impact is bounded: the `consensus_edge` flag
defaults off (ADR-023). Fix is one keyword: `params_mod.load(refresh=True)` on both sides.

The other two self-comparisons are legitimate:
`tests/api/test_golden_dataset_invariants.py:228` `assert v == v` is a documented NaN check, and
`tests/test_trade_suggestions.py:701` `rank_score(s) == rank_score(s)` genuinely fails if
`rank_score` becomes non-deterministic.

### 5.3 Grep tests — 104 Python, 39 frontend (W24-F010, P3)

104 Python test functions have assertions consisting *only* of substring membership against text
read via `read_text()` / `getsource()`. The frontend has **39** `expect(src).toContain(...)`-shape
assertions out of **3,708** total `expect` calls.

Re-run: `.venv/bin/python docs/master-site-audit/evidence/W24/greptests_scan.py | head -3`
→ `{"total_tests": 5867, "grep_tests": 104}`; and, from `frontend/`,
`grep -rnE 'expect\((src|source|page|pageSource|clientSource|route|text|css)[A-Za-z]*\)\.(toContain|toMatch|not)' __tests__ | wc -l`
→ **39** (the W24 shard recorded 40 at `e96c06ef`; the one-line drift is source churn, not a
methodology difference).

The **positive** greps are the weak half: `assert "canonicalConsensusRank" in src`
(`tests/api/test_rankings_our_rank.py:99-115`) passes if the identifier appears in a comment or
in a branch that never executes. Risk concentrates in the cross-file wiring tests —
`test_the_consumer_reads_the_key_the_producer_writes`
(`tests/consensus_edge/test_opportunity_wiring.py:52-70`),
`tests/deploy/test_sharp_records_bootstrap_wiring.py:20-51` — where a grep reads as proof that two
modules agree while proving only that a string is present in both.

The **negative** greps are well constructed: `tests/api/test_rankings_our_rank.py` strips comments
before asserting absence, and `tests/api/test_frontend_migration.py:37-40` matches on
`def {symbol}(` rather than a bare mention, for exactly that reason.

### 5.4 Two more "the test cannot fail on this" cases, found by other workstreams

| Finding | The test | Why it cannot fail |
|---|---|---|
| **W30-F005** (P2) | `src/trade/ktc_va.py`'s own parity test asserts agreement **"to ±1"** | Three Python ports of KTC's Value Adjustment ship simultaneously; `ktc_va.py` uses `round()` at `:116`/`:319` where the others use `floor(x+0.5)`. Over 20,000 random packages the results differ on 38 (0.19%) — **always by exactly 1**. The tolerance is exactly the size of the divergence |
| **W25-F002** (P2) | `tests/api/test_source_overrides.py:608-636` asserts `delta_bytes < 55_000` | It runs on a synthetic fixture **71× smaller than production**. Live measurement: `GET /api/data` = 11,953,535 b; `POST /api/rankings/overrides?view=delta` = 3,918,195 b (372,690 b gzipped). The test could never detect the drift, and its comment propagates the wrong figures |
| **W30-F010** (P3) | `test_consumer_and_live_duplicate_paths_resolve` (`tests/audit/test_formula_registry.py:112-133`) | It only asserts that the named **file** exists, so a registry entry naming a construct that was deleted from inside an existing file still passes |

---

## 6. Numeric pinning of the riskiest value-producing functions

The question that matters for a valuation platform: does a test pin a **numeric output**, or only
a shape? Measured per function against `CLAUDE.md`'s live pipeline steps.

| Pipeline step / function | Pin kind | Where | Tier |
|---|---|---|---|
| **3. `percentile_to_value`** (Hill percentile→value) | **NUMERIC — frozen at 10 ranks + all 8 scope constants** | `tests/canonical/test_hill_percentile_constants_tripwire.py:87-100`, `:135`, `:152-160` | **blocking** |
| Legacy `rank_to_value` (rank-history reconstruction) | NUMERIC at 10 ranks, but **self-regenerated by instruction** | `tests/canonical/test_player_valuation.py:118-146` | blocking |
| **7. Count-aware aggregation** | NUMERIC — exact centers/MADs | `tests/api/test_count_aware_blend.py` (14 tests, 23 numeric-literal assertions) | blocking |
| **10. Market corridor clamp** | NUMERIC — exact clamped outputs `4500`, `5500`, `5750`; stamp fields | `tests/api/test_market_corridor_clamp.py:267`, `:293`, `:385` (31 tests) | blocking |
| **12. Pick-year discount** | NUMERIC — exact `1000.0` / `900.0` ladder + ordering | `tests/api/test_pick_year_discount_gate.py:53-80` (5 tests) | blocking |
| **13. Pick tethering / rookie anchor** | NUMERIC — `4200`, `8990`, `5500`, `9000`, `2000` | `tests/api/test_pick_rookie_anchor_core.py:128-179` (9 tests) | blocking |
| Hampel pre-filter | NUMERIC — threshold + exclusion set | `tests/api/test_hampel_filter.py:46`, `:120` (18 tests) | blocking |
| **9. Single-source haircut** | Asserted **through the module constant** `_SINGLE_SOURCE_VALUE_RETENTION`, not a literal | `tests/api/test_golden_dataset_invariants.py` | blocking |
| **5a. TE basis conversion** | NUMERIC ceiling `9999 × 1.2092`; identity no-op pinned | `tests/api/test_te_lift_ceiling.py:70-73`; `tests/audit/test_formula_registry.py:177` | blocking |
| FAAB baseline bid (server + client) | **NUMERIC cross-language oracle, hand-derived** | `tests/fixtures/faab_bid_parity_cases.json` → `tests/trade/test_faab_bid_parity.py` + `frontend/__tests__/faab-bid-parity.test.js` | blocking |
| BDVM engine | **NUMERIC vs published reference** — 13 archetypes × 3 currencies at ±1.0, 7 replacement FPGs to 2 dp, 7 startable-slot counts exact | `tests/bdvm/test_engine_parity.py:280-363`; `tests/bdvm/test_reference_parity.py` (W13-F007) | blocking |
| KTC Value Adjustment | NUMERIC but **tolerance ±1 masks the live divergence** | W30-F005 | blocking |
| **`_resolve_league_context`** (roster count N, `bonus_rec_te`) | **NONE — 0 tests reach the branch** | W24-F005 | — |
| BDVM parameter values themselves | **NONE ever validated** — `params_v1.json` self-declares as un-backtested priors; `src/bdvm/backtest.py` (336 lines) is imported only by its own test | W13-F006 | — |

### 6.1 Correction: W24-F007's headline claim does not hold

**W24-F007 (P2) states that `percentile_to_value` "has zero absolute numeric assertions in 6,326
tests" and that the only absolute freeze guard in the tree pins the *legacy* `rank_to_value`
instead. That is wrong, and the correction matters because the function is the single most
load-bearing number in the repo.**

`tests/canonical/test_hill_percentile_constants_tripwire.py` — added 2026-07-30 as "audit debt
D16", precisely because of the invisible `test_ktc_reconciliation.py` failure described in §4.3 —
contains a hard-gated freeze guard on `percentile_to_value`'s **output**:

```python
_PINNED_OFFENSE_VALUES = {1: 9999, 5: 9481, 12: 8561, 24: 7242, 50: 5314,
                          100: 3419, 150: 2481, 200: 1931, 300: 1322, 400: 996}
...
def test_the_offense_curve_still_produces_the_pinned_values():
    actual = int(percentile_to_value((rank - 1) / denom))
```

plus `_PINNED` at `:87-100`, an equality assertion on **all eight** percentile-form master
constants (GLOBAL, OFFENSE, IDP, ROOKIE × C/S), and
`test_the_committed_source_matches_the_imported_values` which checks the registry's regex reader
agrees with the Python values.

Verified for this document:

```
$ .venv/bin/python -m pytest tests/canonical/test_hill_percentile_constants_tripwire.py -q -m "not livedata"
4 passed in 0.05s

live percentile_to_value at N=500:
{1: 9999, 5: 9481, 12: 8561, 24: 7242, 50: 5314, 100: 3419, 150: 2481, 200: 1931, 300: 1322, 400: 996}
```

— an exact match to the pinned dict. The guard is also **sensitive**: perturbing
`HILL_PERCENTILE_S` by 1% moves rank 5 from 9481 → 9495 and rank 200 from 1931 → 1909, both of
which would fail the assertion. So the finding's stated user impact — *"a sign flip in the
exponent, a wrong clamp bound, an off-by-one in the percentile denominator … and no test would
fail"* — is **false**; each of those three would fail this test, in the blocking tier.

**Why the finding missed it:** its detection command was
`grep -rn 'percentile_to_value' tests/ -A3 | grep -E '== [0-9]{3,}|approx\([0-9]'`. The pinned
dict sits ~65 lines *above* the call site, and the three lines following the call
(`if actual != expected: drifted.append(...)`) contain no numeric literal. A `-A3` window cannot
see it. The finding's own `requiredRepair` asks for the guard to be added *"beside the existing
tripwire in tests/canonical/test_hill_percentile_constants_tripwire.py"* — it is already inside
that file.

Re-run: `.venv/bin/python -m pytest tests/canonical/test_hill_percentile_constants_tripwire.py -q`
and `sed -n '87,100p;152,160p' tests/canonical/test_hill_percentile_constants_tripwire.py`.

**What survives from W24-F007:** the observation about `rank_to_value`. Its 10-value dict
(`tests/canonical/test_player_valuation.py:134-144`) carries the instruction *"regenerate this
dict from the constants rather than hand-editing it"* — a change detector by construction, not an
independent oracle. That remains accurate and is reflected in the table above.

The residual real gap is narrower than F007 claims: the **output-space** pin covers the OFFENSE
master only. GLOBAL / IDP / ROOKIE are pinned as constants, which catches a promotion or an edit
to those numbers, and any change to the sigmoid *formula* is caught via the OFFENSE pin since all
four scopes share it. Adding three more output rows would close it completely.

---

## 7. Frontend fixtures and E2E

### 7.1 Frontend fixtures are **not** tautological

We looked for the failure mode and did not find it (W24-F010 `whatWorks`, re-checked):

- `frontend/__tests__/fixtures/players.js` is hand-authored — it is the only fixture file under
  `frontend/__tests__/fixtures/`.
- The four shared parity fixtures — `tests/fixtures/faab_bid_parity_cases.json`,
  `signal_parity_cases.json`, `name_key_cases.json`, `trade_grade_parity_cases.json` — are
  cross-language oracles that **neither side may hardcode against**. The FAAB fixture's header
  states it explicitly: *"Neither test may hardcode an expectation of its own — if the two
  implementations disagree, exactly one of them fails against this file. Every `expected` below is
  hand-derived from the formula in `rounding`, not produced by running either implementation."*

Re-run: `head -8 tests/fixtures/faab_bid_parity_cases.json`; `ls frontend/__tests__/fixtures/`.

This is the strongest single piece of test design in the repository and is worth copying, not
just praising — see the missing-tests list, item 7.

### 7.2 E2E: 13 tests skipped in the only workflow that runs them (W24-F004, P1)

`.github/workflows/e2e.yml:210` sets `SKIP_VISUAL_REGRESSION: "1"`. The comment above it, at
`:207-209`, asserts: *"Visual-regression baselines are not committed to the repo, so pixel
comparisons are skipped; **the visual specs still run their structural chart/render
assertions**."* That is not what happens.

Both specs call `test.skip(!!process.env.SKIP_VISUAL_REGRESSION, ...)` in the **describe body**
(`chart-visual-regression.spec.js:173`, `public-league-visual.spec.js:121`), which in Playwright
is a **group-level** modifier. Runtime proof, reproduced for this document against a two-test
fixture using the identical pattern:

```
$ playwright test -c docs/master-site-audit/evidence/W24/pwrepro/pw.config.js
  2 passed (1.1s)
$ SKIP_VISUAL_REGRESSION=1 playwright test -c .../pw.config.js
  2 skipped
```

The fixture's two tests are named `structural assertion (NOT a screenshot)` and
`pixel assertion` — both skip.

| Spec | Tests | `toHaveScreenshot` calls | Skipped in CI |
|---|---|---|---|
| `tests/e2e/specs/chart-visual-regression.spec.js` | 9 | 8 | all 9 |
| `tests/e2e/specs/public-league-visual.spec.js` | 4 | 6 | all 4 |
| Committed `.png` baselines | — | — | **0** |

Re-run: `grep -c "^\s*test(" tests/e2e/specs/chart-visual-regression.spec.js
tests/e2e/specs/public-league-visual.spec.js`; `git ls-files 'tests/e2e/**/*.png' | wc -l`.

The env var **buys nothing**: the same command passes `--ignore-snapshots`, which already
neutralises all 14 `toHaveScreenshot` calls given zero committed baselines. It costs the
structural half — `Hill curve has axis + at least one path`, `Confidence scatter has enough
points`, and the four `/league` section content assertions (Records, Streaks, Awards, Recaps),
none of which take a screenshot.

Consequence: the Hill-curve methodology panel, tier-gap waterfall, confidence scatter,
matchup-margin histogram, trade-flow Sankey, activity heatmap and franchise trajectory can render
blank on `/rankings` and `/league` with no CI signal at any cadence. `e2e.yml` is the only
workflow that runs these specs; `prod-e2e-smoke.yml:101` runs only `public-league.spec.js`.

`tests/e2e/README.md:108` describes the flag correctly — *"Skip the two visual-regression specs
entirely"* — so the **workflow comment is the outlier**, which is what let this survive review.

### 7.3 The one remaining silent E2E skip

`tests/e2e/specs/journey-settings-overrides.spec.js:116` skips mid-test when the override endpoint
degrades to the base-contract fallback. It is the least bad instance of the pattern: the skip
reason names the degradation and states *"round-trip already asserted"*, and a preceding
assertion (`expect(await rows.count()).toBeGreaterThan(50)`) has already run. What it silently
drops is the custom-mix badge assertion on the very runs where the override path misbehaved.

**Everything else is a repair, not a gap.** Four `test.skip` sites across
`critical-smoke.spec.js`, `journey-trade.spec.js` and `public-league.spec.js` survive only as
comments recording their own removal (e.g. `public-league.spec.js:388` — *"Was
`test.skip(!first)`. The committed snapshot serves 158…"*). Re-run:
`grep -rn "test\.skip" tests/e2e/specs/`.

---

## 8. What the green legitimately proves

A list of only defects is not an audit. These were checked and hold:

1. **Every skip carries a human-readable reason.** No bare skips anywhere in 166 sites
   (`evidence/W24/skip-census.txt`).
2. **The blocking/advisory split is sound in principle and 11 of its 14 basename exemptions are
   correct** (§4.2). Its motivation is documented and real: a `yahooBoone` row-count dip stalled
   every open PR during this audit.
3. **`tests/test_livedata_policy.py` works as an exemption checker** for the two regressions it
   names, and it caught a dead exemption (`test_footballguys_source.py`, removed 2026-07-27).
   `tests/api/test_data_contract.py` — 33 tests over the core blend — was rescued from the
   advisory tier on 2026-08-04 as audit finding Q-1 and verified to pass with no data files
   present (`tests/conftest.py:103-118`).
4. **`percentile_to_value` is numerically frozen in the blocking tier** and the guard is sensitive
   to a 1% constant change (§6.1).
5. **The pick ladder, the corridor clamp, the count-aware blend, the Hampel filter and the
   pick-year discount all pin exact numbers,** not shapes (§6 table).
6. **The FAAB cross-language oracle is genuinely non-tautological** — hand-derived expectations
   neither implementation may hardcode against (§7.1).
7. **BDVM parity is against a published external reference, token for token.** W13-F007 verified
   all 13×3 trade values, 7 replacement FPGs and 7 startable-slot counts against
   `docs/research/bdvm-v1/reference/examples_output.txt`; 284 BDVM tests pass.
8. **The mock-echo class is effectively absent:** 4 hits across 5,867 test functions, all
   legitimate pass-through contracts (`evidence/W24/mock-echo-scan.json`).
9. **The 17 assert-free test bodies are helper delegation, not vacuity** (§5.1).
10. **Frontend fixtures are hand-authored, not generated from the code under test** (§7.1).
11. **The E2E suite is non-vacuous where it runs.** W24-F004 re-verified a sample of
    `docs/e2e-assertion-audit.md`'s own findings as remediated: `critical-smoke.spec.js:159-160`
    now asserts `expect(url).toContain('/login')` with the `|| body.length > 0` disjunction
    removed (A6); `signed-in-smoke.spec.js` anchors on page `<h1>`s and live-contract data rather
    than nav-label regexes (A1-A3); `journey-tools-health.spec.js:60-66` asserts both branches
    instead of skipping.
12. **`tests/api/test_golden_dataset_invariants.py` is well built and honest** — a 20-player
    hand-authored cross-section (suffixes, punctuation, accents, apostrophes, IDP families, a
    single-source player, a contested player, picks, an unrankable OL) with a docstring stating
    plainly that it pins invariants rather than magic numbers, routing constant checks through the
    module constant so a deliberate change updates one place.
13. **The shallow-clone skips are not a CI gap** — `pr-validation.yml:65` and `deploy.yml:43` both
    set `fetch-depth: 0` (§2.1).

---

## 9. One committed artifact that pretends to be coverage (W24-F009, P3)

`tests/fixtures/golden/baseline.json` — **722,671 bytes**, carrying `"inputExport":
"dynasty_data_2026-08-04.json"` and per-row `rankDerivedValue` / `anchorValue` /
`sourceRankSpread` for the whole board. It is generated by `scripts/golden_board.py` and consumed
only by `scripts/board_diff.py`, a manual developer tool.

**Automated consumers in `tests/` and `.github/`: 0.** Re-run (reproduced for this document):
`grep -rn 'baseline.json\|golden_board\|board_diff' tests/ .github/ --include=*.py --include=*.yml
| grep -v test_bdvm_build_baseline | wc -l` → `0`.

No user impact. The cost is misdirection: a reader auditing coverage sees a committed golden board
under `tests/fixtures/` and concludes the full board is regression-pinned. It is not.

---

## 10. Missing tests that would most raise confidence, in value order

| # | Test to add | Closes | Cost | Why it ranks here |
|---|---|---|---|---|
| 1 | **A `--collect-only` floor assertion in `pr-validation.yml`**: fail the gate if executed-test count drops below a committed floor | W24-F001 (and the whole latent class in §2.2) | XS | This is the single highest-leverage line in the document. A skipped test and a passing test are indistinguishable in `pytest -q`, and 139 of 166 skip sites are invisible to the current census. One assertion converts every future silent skip into a red PR |
| 2 | **Track `data/public_league/nfl_players_full.json`** (`git add -f` + `.gitignore` re-include, same class as the already-tracked `exports/latest/`), **and** assert the `livedata` tier reports **zero** skips | W24-F002 | S | Resurrects 22 tests whose entire purpose is catching a metric that collapses to a constant only on live data — a defect this codebase has already shipped once. The zero-skip assertion closes the class, not just the instance |
| 3 | **Drop `SKIP_VISUAL_REGRESSION: "1"` from `e2e.yml:210`** (`--ignore-snapshots` already suppresses pixel comparisons) and correct the workflow comment | W24-F004 | XS | Restores 13 structural assertions across 7 charts and 4 `/league` sections at zero new infrastructure. Currently the only nightly signal that these render at all |
| 4 | **Drive `_resolve_league_context`'s Sleeper branch** with a monkeypatched `urlopen` and a canned league payload: assert (a) `roster_count` from `total_rosters`, (b) `bonus_rec_te` coercion of string/None/negative, (c) `size > 0` rejects zero, (d) cache fills and TTL honoured, (e) exception → fallback. Then a pick-ladder test at **N=10 and N=14** | W24-F005 | M | The board is correct today only because the fallback `N=12` coincides with `dynasty_main`'s team count. `dynasty_new` already ships `teamCount: 10`. This sets all 72 slot-pick values |
| 5 | **Point `LEAGUE_REGISTRY_PATH` at the real `config/leagues/registry.json`** in conftest and block the network at the fetch seam instead (monkeypatch `urlopen` to raise) | W24-F006 | M | Keeps the suite offline while letting the existing, already-thorough `test_league_routing.py` run against the shipped file. Today `leagues_share_scoring` returns the opposite of production for the repo's two live leagues |
| 6 | **Move `test_dlf_scraper.py` and `test_fetch_flock_fantasy_rookies.py` out of `_LIVEDATA_MODULES`** (33 pure-logic tests), and **generalise `tests/test_livedata_policy.py`** to run the audit-hook probe over every exempted module, failing any that opens nothing under `exports/`/`CSVs/`/`data/` | W24-F003 (as rescoped, P2) | M | The probe is 40 lines and already written (`evidence/W24/ioprobe.py`). The generalisation is what makes the fix permanent rather than a one-off. Affects 516 board rows |
| 7 | **Replace the cross-file wiring greps with round-trip fixtures** — build the producer's payload in Python, write it to a fixture, have the vitest half read the key off that fixture | W24-F010 | M | The pattern is already proven in this repo by `faab_bid_parity_cases.json`. Converts "a string exists in both files" into "the consumer reads what the producer wrote" |
| 8 | **Extend `_PINNED_OFFENSE_VALUES` to the GLOBAL, IDP and ROOKIE masters** (3 more output rows in the existing tripwire) | Residual of W24-F007 (§6.1) | XS | The offense curve is frozen; the other three scopes are pinned only as constants. Three dict literals in a file that already exists and already hard-gates |
| 9 | **Re-derive `test_source_overrides.py`'s payload-size bounds from a production-scale fixture** (currently 71× too small, asserting `< 55_000` against a live 3.92 MB delta) | W25-F002 | S | The test cannot detect the drift it exists to detect, and its comment propagates the wrong figures into `CLAUDE.md` |
| 10 | **Tighten the KTC Value-Adjustment parity tolerance from ±1 to exact**, after unifying the three ports on `floor(x+0.5)` | W30-F005 | S | The tolerance is exactly the size of the live divergence (38 of 20,000 packages, always by 1) |
| 11 | **`params_mod.load(refresh=True)` on both sides of `test_param_set_id_is_stable`** | W24-F008 | XS | One keyword. Low value only because `consensus_edge` defaults off |
| 12 | **Either wire `tests/fixtures/golden/baseline.json` into a tolerance-band diff test, or move it out of `tests/fixtures/`** | W24-F009 | S | Removes a 722 KB false signal of board-level regression coverage |
| 13 | **Run the blocking suite on Python 3.12** to match CI and the pins | §0 | S | The archived 6,278-pass green is a 3.11 result; CI and `pyproject` are 3.12 |

---

## 11. What this document could not establish

- **5 of the 40 skips in the archived full run are unattributed.** The archived run used `-rf`
  (failures only), so `pytest-full.txt` records the count and no reasons. Re-running the 43
  skip-declaring files attributes 35 (22 + 10 + 3, §2.1); the `livedata` tier alone accounts for
  25 of those. A scan for other skip mechanisms (`importorskip`, `@unittest.skip`,
  `pytest.mark.skip`, conftest-level skips) found **none**, so the residual 5 are most likely
  ordering- or state-dependent. Resolve with `.venv/bin/python -m pytest tests/ -q -rs --tb=no`
  (32 min).
- **W24-F001, F002, F004, F005, F006, F007, F008, F009 and F010 carry no adversarial verdict.**
  Only W24-F003 was independently verified (`byVerificationVerdict`: 387 of 431 findings
  unverified). Each of the others was re-run for this document and reproduced, except W24-F007,
  whose headline claim is corrected in §6.1 on direct contrary evidence.
- **We did not measure line or branch coverage.** No coverage tool was run; every statement here
  about "no test exercises X" is a targeted runtime probe (audit hook, `urlopen` spy, marker
  deselection) or an AST/grep scan, each cited with its command. Absence of coverage
  instrumentation means there is no repo-wide number for uncovered production lines.
- **Frontend coverage was not analysed beyond assertion shape.** 1,754 vitest tests pass across
  104 files; we counted 3,708 `expect` calls and classified 39 as source-text greps. We did not
  establish which components have no test at all.
- **The 241 shape-only test functions were not individually triaged.** They are weak, not vacuous;
  distinguishing "shape is the correct contract here" from "this should pin a number" requires
  per-test judgment that was out of scope.
- **CI behaviour is inferred from workflow YAML, not from workflow run logs.** The
  `fetch-depth: 0` claim (§2.1), the `continue-on-error` placement (§4) and the
  `SKIP_VISUAL_REGRESSION` effect (§7.2) are read from `.github/workflows/` and, for the last one,
  proven by local Playwright repro — not by inspecting a GitHub Actions run.
