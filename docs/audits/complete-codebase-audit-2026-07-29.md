# Complete codebase audit — 2026-07-29

**Scope:** repository-wide, with the rankings/valuation pipeline as the
priority.
**Branch:** `claude/complete-codebase-audit-fzp0ye` (from `main` @ `557f413`).
**Method:** every claim below was verified against the tree or measured
on the live `exports/latest/dynasty_data_2026-07-29.json` payload. Claims
inherited from prior surveys that turned out to be wrong are listed as
such rather than quietly dropped.

---

## 1. Executive summary

**Overall health: good, and better than the surrounding documentation
suggested.** The core architectural claims in `CLAUDE.md` hold up under
inspection: there is exactly one live value path
(`_compute_unified_rankings`), the frontend really is a materializer,
BDVM really is isolated from `rankDerivedValue`, the league-adjusted
overlay really is composed server-side, and the TE double-count guard is
structural rather than conventional. The test suite is large (≈5,000
pytest + 1,388 vitest) and the high-risk stages are directly covered.
There was no TODO/FIXME debt and no hardcoded secret in application code.

**Can the current rankings and values be trusted? Yes, with one
qualification.** The blend is mathematically sound: it is monotonic in
its inputs, bounded, deterministic, robust to a single dissenting source,
and it does not convert missing data into zeros. I verified this with a
new 29-invariant golden-dataset suite that passes against the live
pipeline, and by confirming that the entire audit changed **zero** player
values — all 1,094 rows of the default board are byte-identical before
and after. The qualification is not about the board: it is that several
things *around* the board were wrong (see §2), and that the depth-scaled
`coverageWeight` formula the API publishes is not the formula the blend
runs.

**The most serious problems found:**

1. **Source-weight sliders did nothing.** Any positive weight blended
   identically to 1.0. The API simultaneously published a weighting
   formula it never applied. Fixed; the default board is provably
   unchanged.
2. **The trade finder had two scale errors** — it counted unpriced
   assets against a threshold on the wrong scale, and it had the
   offense-only value wired into exactly the wrong branch, leaving that
   feature dead on the live path and mixing scales on the fallback.
3. **The frontend test suite ran in no CI job**, while a workflow
   comment claimed it did.
4. **`terminal.py` used the offense rank→value curve for IDP players**,
   answering a question `rank_history.py` answered differently.
5. **A real admin password was still spelled out in five committed
   documents**, and the E2E session endpoint defaulted to a real admin
   username.
6. **Documentation actively misreported risk** — the backlog's
   self-declared "highest risk item" was a non-problem.

**Ready for the next phase?** Yes — see §13. The blockers found were
fixed rather than deferred, and the one genuinely open modeling question
is documented with measurements instead of being resolved by guess.

---

## 2. Critical findings

### C1 — Source-weight overrides were a no-op

| | |
|---|---|
| **Location** | `src/api/data_contract.py::_active_sources`, `count_aware_mean_median_blend` |
| **Root cause** | Weights gated membership only; the blend took a bare list of values. `declared_weight` / `coverage_weight` were computed and stamped but never multiplied anything. |
| **User impact** | The `/settings` weight sliders were an on/off switch wearing a dial. Moving DLF to 0.25 did nothing unless you moved it to 0. |
| **Data impact** | None on the default board (all registry weights are 1.0). |
| **Fix** | `weighted_count_aware_mean_median_blend` keeps the count-aware shape on weighted statistics; weights thread through the row loop, the anchor/subgroup split and the Hampel-survivor rebuild. Delegates to the unweighted blend when all weights are equal, so the default is bit-for-bit identical. |
| **Tests** | `tests/api/test_weighted_blend.py` — equal-weight parity, weighted arithmetic per count bucket, monotonicity, observation-based trimming, degenerate inputs, end-to-end override behaviour. |
| **Residual risk** | Low. Trimming at n≥5 stays observation-based by design; that is what preserves exact parity. |

### C2 — Trade finder: unpriced-asset count on the wrong scale

| | |
|---|---|
| **Location** | `src/trade/finder.py::find_trades` |
| **Root cause** | The filter runs on composite-scale values (these rows have no board value by definition) but gated them with the board-scale `MIN_ASSET_VALUE = 700`. Composite runs 1.131× the board. |
| **User impact** | The "N assets are unpriced" warning over-reported: 202 where the function's own docstring says 189. |
| **Fix** | `_MIN_ASSET_VALUE_COMPOSITE_SCALE = round(700 / 0.875) = 800`, recovering the pre-migration gate by inverting the documented constant. |
| **Tests** | `TestUnpricedCountUsesTheCompositeScale` — including the 750 straddler that separates the two thresholds. |
| **Residual risk** | None. The code now matches the intent its docstring already stated. |

### C3 — Trade finder: offense-only value wired into the wrong branch

| | |
|---|---|
| **Location** | `src/trade/finder.py::build_asset_pool` |
| **Root cause** | `_offenseOnlyFinalAdjusted` is mirrored from `offenseOnlyRankDerivedValue` — the IDP-disabled run of the same pipeline — so it is **board**-scale (measured median ratio 0.994 vs `rankDerivedValue` over 522 assets). The board branch discarded it as "the board has no offense-only variant"; the composite branch consumed it next to a 1.131×-scale value. |
| **User impact** | All-offense trades were scored with IDP-influenced values on the live path (feature dead since the F-6 migration), and understated by ~12% per leg on the fallback path. |
| **Fix** | Branches swapped: board path reads it, composite path degrades to unavailable. |
| **Tests** | `TestOffenseOnlyValueIsBoardScale`, including an end-to-end case where the blended board ties and the offense-only board does not. |
| **Residual risk** | **This restores intended behaviour on a live path — all-offense trade suggestions will move.** Called out deliberately rather than buried. |

### C4 — Frontend tests ran in no CI job

| | |
|---|---|
| **Location** | `.github/workflows/pr-validation.yml` |
| **Root cause** | No vitest step existed in any workflow, while the job's own comment claimed "full pytest + vitest + lint gates". |
| **User impact** | ~1,388 assertions covering buildRows, the valuation overlay, waiver/trade math and the BDVM display layer were unverified on every PR. |
| **Fix** | `npm test` added, before the build so unit failures surface in seconds. Comment corrected. |
| **Residual risk** | None. Suite is green (81 files / 1,388 tests). |

### C5 — Two modules answered "value for this rank" differently

| | |
|---|---|
| **Location** | `src/api/terminal.py`, `src/api/rank_history.py` |
| **Root cause** | `rank_history` routed IDP rows to the IDP Hill constants; `terminal` ran every row — IDP and picks included — through the offense curve. |
| **Data impact** | Measured on the live board: offense curve on IDP rows scores RMSE **826**; the IDP curve scores **79**. A roster here starts nine IDP players, so historical roster sums were understated by ~800 points per defender. |
| **Fix** | One shared `player_valuation.rank_to_value_for_scope`. `terminal`'s second call site resolves scope from the `row_index` it already receives. |
| **Tests** | `tests/canonical/test_rank_to_value_scope.py` (14). |
| **Residual risk** | The *family* choice remains open — see §3 and `docs/legacy-rank-curve-backtest.md`. |

### C6 — Credential hygiene

| | |
|---|---|
| **Location** | `HANDOFF.md`, `audit/`, `docs/status/*`, `server.py:10490`, `.env.example` |
| **Finding** | The April incident's real admin password was still written out in **five committed documents**. Separately, `POST /api/test/create-session` resolved its username as `getenv("E2E_TEST_USERNAME") or "jasonleetucker"` — a real allowlisted admin account. `.env.example` shipped real league IDs and the real admin username. |
| **Mitigating** | The **code** was already fixed in April (`server.py:165-180` requires the env var and fails fast). The E2E endpoint is double-gated on `E2E_TEST_MODE` + a bearer secret, so it is invisible in production. |
| **Fix** | Password literal redacted to a pointer at the incident record; endpoint fails closed with `e2e_username_not_configured`; `.env.example` uses placeholders. `E2E_TEST_USERNAME` wired at both boot sites (nothing set it, so the suite was riding the fallback). |
| **Residual risk** | **The password remains in git history and must be treated as compromised.** If it has not been rotated since April, rotate it. This audit cannot rewrite history. |

### C7 — Documentation that misreported risk

`UNIMPLEMENTED_BACKLOG.md` §1.1 called itself "the highest risk item in
this file" because `/api/valuation/league-adjusted` allegedly had "no
test coverage of the HTTP path at all". It has **22** test functions.
§2.1 said the TE basis conversion was "BUILT, NOT WIRED"; it shipped
2026-07-27 and defaults on. Anyone triaging that file would have started
on a non-problem. Corrected in place with evidence, struck through
rather than deleted so the correction is visible. Full list in §11.

---

## 3. Rankings and formula audit

### Authoritative pipeline

`src/api/data_contract.py::_compute_unified_rankings` is the single
live path. Verified stage order (the doc had two stages reversed):

1. Per-source ordinal rank (dense, `-value, name`)
1b. DraftSharks combined cross-market rank
1c. *(dormant — see §5)*
1d. Rookie-ladder translation
2. Percentile vs a fixed 500-rank reference → scope-master Hill curve;
   value-direct for `ktcSfTep` + `idpTradeCalc`
2a. TE basis conversion (base→tepp, KTC exempt, idempotent by construction)
2b. Per-player Hampel filter (k=2.75, n≥4, ≥2 survivors)
2c. Soft-fallback count *(diagnostic only)*
3. Hierarchical anchor + α=0.10 shrinkage for IDP/picks; flat
   count-aware blend for offense — **now weighted by declared weight**
3a. **Pick-year discount (pre-sort)**
4. Unified sort, rank stamp, cap at 800
— Market corridor clamp (IDP only)
— **Two-way player boost** (post-blend `max(offense, alt-family)` override)
5. Pick monotonize → generic-tier suppression → **rookie tethering
   (post-sort, overwrites `rankDerivedValue`)** → compaction

**Corrections made to the documented order:** the year discount is
applied *before* the sort and tethering *after* — `CLAUDE.md` listed
them the other way round. The two-way boost was absent from the doc
entirely despite being a genuine value override.

### Inputs

21 registered sources, **all at weight 1.0 by policy** — no source is
editorially favoured today. Two are value-direct (`ktcSfTep`,
`idpTradeCalc`); the rest vote via rank → percentile → Hill.
`draftSharks` / `draftSharksIdp` carry `signal: "value"` but do **not**
take the value-direct path — they route through a combined-rank
pre-pass. `is_rank_signal` means "the `canonicalSiteValues` slot is a
synthetic encoding", not "votes via rank"; that is a real trap for a
future reader and is now noted.

### Formulas verified

| formula | verdict |
|---|---|
| Percentile → Hill `V(p) = 9999/(1+(p/c)^s)` | correct; `p=0 → 9999`, bounded, monotone |
| Count-aware blend (n=1/2/3-4/≥5) | correct; new weighted variant proven equal at uniform weights |
| Weighted median | correct cumulative-weight definition with midpoint interpolation; reproduces the plain median at equal weights |
| α-shrinkage `anchor + 0.10·(subgroup − anchor)` | correct, applied to IDP + picks only |
| Single-source retention (0.30) | correct and observable (7,500 → 2,250 in the golden fixture) |
| Hampel (k·MAD, floor 1000) | correct; refuses to leave <2 survivors |
| TE basis conversion | correct; idempotent by construction, so double-counting is structurally impossible |
| Corridor clamp | correct for IDP; picks escape only because no `"pick"` anchor key exists — a latent footgun, documented |
| Pick-year discount | correct multiplicative, clamped [0.05, 1.0] |

### Mathematical errors found

- **C2/C3** (scale errors in the finder) — fixed.
- **C5** (wrong curve for IDP reconstruction) — fixed.
- **The published `methodology.formula` was a fossil**: it advertised a
  Hill curve with midpoint 45 / slope 1.10 — the retired *rank-form*
  curve that no live path uses. Any consumer trusting the contract's own
  description of its math was misled. Corrected to the percentile form,
  and the test that pinned the fossil was rewritten.

### Double-counting risks

None found in the live blend. The TE conversion is the one place where
double-counting was structurally possible, and it is guarded by
construction (`from == to` is a no-op) rather than by convention. A
source votes exactly once — pinned by a determinism test.

### Open modeling decisions (NOT resolved here)

> **Followed up 2026-07-29 — see `docs/open-modeling-decisions.md`.**
> Both questions below were under-specified: stated as choices without
> the measurements needed to make them. They are now closed to evidence.
> **(1) `coverageWeight`: do not apply** — measured at 297 rows moved /
> 221 ranks changed for a 3-source input change, with no accuracy
> evidence. **(2) the rank-form family: the "bring it under the model
> registry" proposal was WRONG** — the refit script is read-only and
> nothing runs it, so there is no automated promotion to gate; replaced
> with a tripwire test. A third question raised later (the
> `low_conf_unstable` threshold) turned out to be a broken metric, not a
> threshold — same document.

1. **Should `coverageWeight` be applied?** The depth-scaled factor is
   computed and published but never used. Applying it would down-weight
   the three depth-50 rookie sources and *change the default board*.
   That is a product call. The published text now says DIAGNOSTIC ONLY.
2. **Should the legacy rank-form Hill family be retired?** Measured in
   `docs/legacy-rank-curve-backtest.md`. It sits outside the model
   registry with no out-of-sample gate. But the candidates have inverted
   error profiles — `percentile_global` is far better past rank 120 and
   ~2× worse in the top 24 — and switching moves user-visible history
   values. A refit fits best (RMSE 96 vs 670) but would re-create the
   unmanaged family unless brought under the registry.

**Confidence in current outputs: high** for the market board, on the
evidence that every invariant holds, the board is unchanged by this
audit, and the stages match their documentation now that the
documentation has been corrected.

---

## 4. Source-of-truth map

| concept | authoritative owner | notes |
|---|---|---|
| Player identity (live) | `src/identity/unified_mapper.py` | `src/identity/matcher.py` is script-only |
| Name normalization | `src/utils/name_clean.py` / `frontend/lib/player-name-match.js` | **≈9 backend + 4 frontend re-implementations still exist** — see §8 |
| Position → family | `src/utils/name_clean.py::POSITION_ALIASES`; frontend now `lib/position-family.js` | frontend duplication fixed this pass |
| League settings | `src/api/league_registry.py` (`config/leagues/registry.json`) | precedence fixed in two callers |
| Scoring settings | `config/league_comparison.json` + Sleeper overlay | |
| Projections | `data/bdvm/projections/` snapshots | absent in this container |
| Market values | `canonicalSiteValues` from `Dynasty Scraper.py` | |
| **Internal player value** | **`data_contract.py::_compute_unified_rankings` → `rankDerivedValue`** | single path, verified |
| Rankings | same; `compact_ranks_and_tiers` is the one ranker | |
| Trade value | `rankDerivedValue` via `board_values_from_contract` | now pinned by a test |
| Rank→value reconstruction | `player_valuation.rank_to_value_for_scope` | consolidated this pass |
| Fundamental value | `src/bdvm/` | isolated; never writes `rankDerivedValue` |
| League-adjusted lens | `src/league_intel/overlay.py` | server-side composition only |
| Waiver / FAAB | `src/trade/waiver.py` + `frontend/lib/waiver-logic.js` | **dual implementation** — see §8 |
| Buy/Sell/Hold signals | `src/api/terminal.py` + `frontend/lib/signal-engine.js` | **dual implementation, no parity test** — see §8 |
| News | `src/news/` providers | |
| Contender/rebuilder | `src/bdvm` strategies + trade suggestion thresholds | |
| Cache | per-surface; no central invalidation | see §10 |
| User preferences | `user_kv` | |

**Concepts still without a single source of truth:** name
normalization, waiver/FAAB math, and the Buy/Sell/Hold rule engine.
All three are flagged, none were consolidated in this pass because each
requires a behavioural decision rather than a mechanical merge.

---

## 5. Removed or consolidated code

| item | why safe |
|---|---|
| `player_valuation.py`: `run_valuation`, `compute_consensus_rank`, `compute_tier_adjustments`, `compute_volatility_adjustments`, `compute_display_anchor`, `_to_display`, `base_value_curve`, `build_player_inputs_from_*`, `valuation_result_to_asset_dicts`, `_collect_hyperparams`, `PlayerInput`/`PlayerValuation`/`ValuationResult`, `W_*`/`CLIFF_*`/`VOL_*` | The engine of the explicitly-retired offline canonical build. Zero production importers across `src/`, `scripts/`, `server.py`, `Dynasty Scraper.py`, `frontend/`, including dynamic-import scan. **948 → 375 lines.** |
| `src/canonical/__init__.py` re-exports | Kept the dead symbols reachable and claimed `data_contract.py` used them; it does not. Package now exports nothing. |
| ~68 tests covering only the above | Trimmed, not weakened. `TestTierDetection` / `TestBaseValueCurve` kept byte-identical; the calibration tripwire's fixture was rewritten to stamp its tag directly, which tightens it. |
| `frontend/lib/movers.js` + `activity-feed.js` duplicate `POS_FAMILY` | Consolidated to `lib/position-family.js`; the two copies disagreed on K/DEF. |
| `ManualAddDrop.jsx` local `normName` | Promoted to `waiver-logic.js::normalizeNameCompact`. |
| `server.py` deprecated `KTC_TOP_N_FILTER` imports | Switched to canonical names; wire contract untouched. |

**`TierBoundary` was on the removal list and kept** — it is the return
type of the live `detect_tiers`.

**Phase 1c (the FootballGuys CSV-rank restore) was NOT removed.** Its
key set is provably empty today, but the logic is generic, guarded, and
would auto-activate for any future rank-signal cross-market source. The
misleading part was the comment naming FBG as a current member; that was
corrected instead.

---

## 6. Preserved unfinished work

| item | status | why kept | next step |
|---|---|---|---|
| `src/canonical/confidence_intervals.py`, `rank_history_band.py` | no production importer; flag-gated, default off | genuine planned feature behind `value_confidence_intervals` | decide: ship the flag or retire the modules |
| Phase 1c cross-market CSV restore | dormant, auto-activating | generic scaffolding, zero cost | leave; it is now documented as dormant |
| `HILL_ROOKIE_PERCENTILE_C/S` | refit weekly, **not routed** | refit tooling; routing is a live option | leave |
| `src/adapters/base.py` | test-only | the frozen adapter contract | leave |
| `src/model_registry/*` | script-only by design | human-gated promotion path (ADR-008) | leave |
| `src/league/` | empty placeholder | import-compat + a design warning, now pointing at `league_intel` | leave |
| `DEFAULT_SLEEPER_LEAGUE_ID` in the scraper | unreachable in CI/prod | removing it would turn a degraded standalone case from "scrapes default league" into "skips Sleeper entirely"; prod `.env` not inspectable | remove once prod env is confirmed |
| `_MAD_PENALTY_LAMBDA`, `softFallbackCount` | retired mechanisms, diagnostics only | documented as retired in `CLAUDE.md` | leave |

---

## 7. Incomplete / unimplemented features

**Started but incomplete**
1. `value_confidence_intervals` — two modules, flag off, no route.
2. TE premium **Axis B** (league-measured demand as the *target basis*)
   — `measure_te_demand` returns a basis and is deliberately not
   consulted by the blend; blocked on ADR-009.
3. BDVM in this environment — `data/bdvm/` does not exist, so all four
   endpoints degrade and the /rankings + /draft gap columns
   self-suppress. Working as designed, but **no BDVM path is
   exercisable end-to-end here** without running the baseline builder.

**Documented but not started**
4. Multi-league scrape (`POST /api/scrape` returns 501 for non-default).
5. Applying `coverageWeight` (open decision, §3).

**Backend-only / no UI caller**
6. `POST /api/waiver/suggestions` — acknowledged in `CLAUDE.md`.
7. Six `/api/scaffold/*` routes — documented, no consumer.

**Needing validation before trust**
8. The legacy rank-form curve family (§3, measured).
9. `src/api/chat.py`, `espn_schema_drift.py`, `unified_signal_engine.py`,
   `league_intel/{calibration,sim,twin}.py` — unreachable from any entry
   point; not touched this pass.

**Priority order:** 3 → 8 → 2 → 1 → 5 → 4 → the rest.

---

## 8. Technical-debt register

| # | item | severity | risk | scope | before new features? |
|---|---|---|---|---|---|
| D1 | **≈9 backend + 4 frontend name normalizers** | High | Silent join failures assign data to the wrong player or drop it | Large | Yes — pick one per side and migrate |
| ~~D2~~ | ~~`buildTopWaiverPool` keys ownership with trim+lowercase~~ **REFUTED — see below** | ~~High~~ none | premise measured false | none | No |
| D3 | **Buy/Sell/Hold implemented twice** (`terminal.py` + `signal-engine.js`), same 9 rules, no parity test | High | The two surfaces can disagree about the same player | Medium | Yes — at minimum add a parity test |
| D4 | FAAB math duplicated JS/Python; JS `Math.round` is half-up, Python `round` is banker's | Medium | Off-by-one bids on exact halves | Small | No |
| D5 | Tier boundaries + confidence thresholds mirrored by hand, no parity test | Medium | Frontend and backend disagree on tiers after a change | Small | No |
| D6 | `/api/rankings/sources` `columnLabel` differs from the UI on 19 of 21 sources | Low | A consumer trusting the "authoritative registry" renders different headers | Small | No |
| D7 | ~17 literal IDP/position sets across `src/` | Medium | A new position alias must be added in 17 places | Medium | No |
| D8 | Legacy rank-form Hill family outside the model registry | Medium | Drifts independently of the board (measured) | Medium | Decision first |
| D9 | Three never-invalidated module caches; `bdvm_api` keys on `id(contract)` | Medium | Stale values after a config change; id reuse after GC | Small | No |
| D10 | Two overlapping backup systems, four health probes | Low | Operational confusion | Small | No |
| D11 | 61 of ~100 routes undocumented; 18 with no frontend caller | Low | Unknown surface area | Medium | No |
| D12 | mypy configured, never run; ruff check changed-files-only | Low | Type debt accumulates unseen | Medium | No |
| D13 | ~205 pytest cases are `livedata`-advisory (`continue-on-error`) | Medium | Includes the primary blend test | Small | Re-litigate per module |
| D14 | ADR numbers collide across two DECISIONS files (two ADR-008s) | Low | Ambiguous citations | Small | No |

### D2 was wrong — recorded so it is not re-raised

**Addendum 2026-07-29, after this report shipped.** D2 was raised as a
High-severity correctness bug. It is not a bug, and the follow-up round
proved it by measurement rather than by re-reading the code.

The *mechanism* is exactly as D2 described: `buildTopWaiverPool`
(`waiver-logic.js:753-756`) and `buildCandidatePool` (`:322-327`) gate
roster ownership with `normalizeName` (trim + lowercase) on both sides,
and `src/trade/waiver.py::_normalize_name` is byte-identical.

The *premise* — that Sleeper roster strings and contract row names drift
on punctuation — is false by construction. `Dynasty Scraper.py:1210`
runs every Sleeper roster name through `clean_name()` before it reaches
the contract, and `_canonical_map` forces contract keys onto that same
Sleeper-derived vocabulary. A join harness over three real payloads
spanning four months measured it:

| payload | rows | rostered | join misses | collisions |
|---|---|---|---|---|
| `exports/latest/dynasty_data_2026-07-29.json` | 1076 | 665 | **0** | 0 |
| `data/legacy_data_2026-03-22.json` | 1163 | 566 | **0** | 0 |
| `audit/baseline/api_data.json` | 1069 | 564 | **0** | 0 |

Zero misses under `normalizeName`, `normalizeNameCompact` *and*
`normalizePlayerNameKey`. No code was changed and no test was added: a
test asserting a punctuation variant "now resolves as rostered" would
pin a fictional invariant and falsely imply this class of bug had been
found and fixed.

**The real hardening target, if one is wanted**, is elsewhere and was
found while disproving this: `src/api/sleeper_overlay.py::_resolve_player_label`
(`:788-804`) prefers the contract's `idToPlayer` map but falls back to
the raw Sleeper `full_name` with no `clean_name` applied — a foreign
vocabulary leaking into `sleeper.teams[].players`, which every
name-keyed consumer reads. Measured live exposure today: 1 of 666
rostered playerIds misses `idToPlayer`, and that id has no contract row,
so it currently hides nothing. One function, and it would harden
`waiver-logic.js`, `waiver.py`, `angle.py`, `replacement.py` and
`faab_contention.py` at once with no parity break.

**Lesson for future audit rounds:** D2 was derived from reading code and
reasoning about what *could* drift. The drift never occurs because an
upstream stage normalizes it away — a fact invisible at the call site.
Verify the premise, not just the mechanism.

---

## 9. Testing report

**Baseline (clean HEAD, git worktree):** 5,009 passed, 0 failed.
*(An earlier run showed 2 failures; those were self-inflicted — source
files were edited while the 5-minute suite was running. There is **no**
test-pollution defect. Verified by the clean-HEAD run.)*

**After the audit:** see §12 for the final gate results.

**Tests added**

| file | count | covers |
|---|---|---|
| `tests/api/test_golden_dataset_invariants.py` | 29 | 16-player cross-section: rank/value coherence, bounds, NaN/coercion, two-way monotonicity, zero-as-no-opinion, single-source haircut, outlier containment, determinism, finder/board agreement, identity edge cases |
| `tests/api/test_weighted_blend.py` | 22 | equal-weight parity, weighted arithmetic, monotonicity, trimming, degenerate inputs, end-to-end overrides |
| `tests/canonical/test_rank_to_value_scope.py` | 14 | scope routing, curve shape, both callers share it |
| `tests/trade/test_finder_canonical_board.py` (added) | 7 | composite-scale threshold, offense-only board scale |
| `tests/deploy/test_timers_are_utc.py` | ~4 | every `OnCalendar` is explicitly UTC |
| `tests/api/test_test_session_endpoint.py` (added) | 4 | E2E endpoint fails closed |

**Golden-dataset result:** all 29 invariants pass against the live
pipeline. The fixture is non-vacuous — it produces a real 15-row board
spanning 1,742–9,999, with OL correctly unranked and the single-source
haircut visibly applied (7,500 → 2,250 ≈ ×0.30).

**Coverage still lacking:** the three dual implementations in D1–D3;
the BDVM endpoints end-to-end (no snapshot in this environment); the
`/api/scaffold/*` family.

---

## 10. Data-quality report

- **Active sources:** 21 registered, all weight 1.0. Per-source freshness
  stamps in `data/scrape_state/` were current (all but three
  `footballGuys*` stamps, which belong to a **removed** source — a
  leftover worth pruning).
- **Removed source still named as active in ~51 comments:**
  FootballGuys. It is not in the registry; comments described it as a
  live cross-market anchor. Corrected at the load-bearing site; the rest
  are cosmetic but numerous.
- **Freshness:** the health check's contract-age probe works; the live
  payload was 3–4h old against a 24h threshold.
- **Stale-overwrite risk:** three independent writers push to `main` on
  overlapping 2-hour cadences (`scheduled-refresh.yml`, and the DLF /
  IDP-Show systemd fetchers). The GH Actions side has a concurrency
  group; the two timers share no lock with it or each other. **The
  suspicion that `git pull --rebase -X theirs` discards the fresh fetch
  is FALSE** — proven with three controlled runs: rebase inverts
  ours/theirs, `-X theirs` keeps this run's data, and `-X ours` would be
  the destructive variant. No change needed.
- **Player mapping:** the BDVM Fund-gap column joined on a bare
  `toLowerCase()` — the loosest key in the repo, driving a user-visible
  column. Fixed to the canonical normalizer.
- **Missing data:** verified the pipeline does not convert missing to
  zero — a 0 from a source is treated as no opinion, pinned by test.
- **Recommended monitoring:** a per-source coverage alert when a
  registered source's row count drops sharply, and a parity check
  between the two Buy/Sell/Hold engines (D3).

---

## 11. Change log

Nine commits, 52 files, +3,149 / −2,071.

1. **`0b26931` Make source-weight overrides actually weight the blend** —
   `weighted_count_aware_mean_median_blend` + `_weighted_median_sorted`;
   weights threaded through the row loop, anchor/subgroup split and
   Hampel rebuild; `appliedWeight` stamped; `methodology.formula`
   corrected from the retired rank-form fossil to the live percentile
   form; `coverageWeight` labelled diagnostic-only; `blendWeights` block
   added; `_active_sources` / `_anchor_key_sets` docstrings corrected.
2. **`c27eb1e` Fix two scale errors in the trade finder** —
   `_MIN_ASSET_VALUE_COMPOSITE_SCALE`; offense-only branches swapped.
3. **`1115826` Share one name key and one position-family map** —
   `bdvm.js` uses `normalizePlayerNameKey`; new `lib/position-family.js`;
   `normalizeNameCompact` promoted out of `ManualAddDrop.jsx`.
4. **`5ad8103` Backtest the legacy rank curve; share one scope-aware
   implementation** — new `scripts/backtest_legacy_rank_curve.py`;
   `rank_to_value_for_scope`; `terminal.py` both call sites made
   scope-aware; `docs/legacy-rank-curve-backtest.md` + measurements JSON.
5. **`9d0c34c` Correct documentation that contradicts the code** —
   `CLAUDE.md` (pipeline step order, two-way boost, scraper label,
   directory map, buildRows nuance, ADR citations), `UNIMPLEMENTED_BACKLOG.md`
   §1.1/§2.1, `src/league/README.md`, `src/bdvm/__init__.py`,
   `league_intel/adjustment.py`, README/HANDOFF/runbook retirements,
   password literal redacted from five documents.
6. **`ac113b1` Run the frontend tests in CI; add a golden-dataset
   invariant suite** — vitest step in `pr-validation.yml`;
   `test_golden_dataset_invariants.py`.
7. **`4c9b513` Fail closed on the E2E session endpoint; fix config
   precedence** — E2E username required; `E2E_TEST_USERNAME` wired;
   `.env.example` placeholders; snapshot script registry-first;
   `_resolve_league_context` docstring; canonical top-N imports; UTC
   timers + test.
8. **`4b0aab8` Resolve the scraper's league ID registry-first** —
   `Dynasty Scraper.py` precedence inverted to match its own comment;
   verified against a bogus env var.
9. **`7227575` Remove the retired offline valuation pipeline** —
   `player_valuation.py` 948 → 375 lines; `__init__.py` exports nothing;
   ~68 dead tests trimmed.

Plus this report and the `live-value-pipeline-trace.md` correction.

---

## 12. Verification

All gates run on the final tree, with no edits in flight.

| gate | result |
|---|---|
| **Default-board invariance** | **1,094/1,094 rows byte-identical to pre-audit HEAD** |
| pytest (`-m "not livedata"`) | **5,012 passed, 0 failed** (baseline 5,009) |
| vitest | **81 files / 1,388 tests passed** |
| `next build` | succeeded |
| bundle-size budgets | all pages under budget |
| `ruff format --check` | 685 files already formatted |
| `ruff check` | pre-existing debt **reduced** (F841 8→6, E402 7→6, E741 unchanged); zero new |
| model-registry regex | `read_committed_constants()` returns all 8 |
| `import server` | clean |
| backtest scripts | both import and run |

The test count rising from 5,009 to 5,012 while ~68 dead tests were
removed reflects ~71 added: the golden-dataset suite (29), the weighted
blend (22), scope routing (14), plus finder, timer and E2E-endpoint
cases. Net coverage moved from the retired offline engine onto the live
pipeline.

---

## 13. Next-upgrade roadmap

> **Status update 2026-07-29 (follow-up round).** Items 2, 3 and 5 below
> have been actioned: **D3 done** (parity test shipped, two real
> divergences fixed), **D2 refuted** (see the addendum in §8), **D1 done**
> (three merges, three live defects fixed). The follow-up also surfaced
> **three NEW items**, listed under "Must complete" — they are bigger
> than the ones they replaced.

**Must complete before major new features**
1. **Rotate the admin password** if not already done since April (C6).
2. **N1 — `signal-engine.js` history lookup is broken.** It looks up
   history by bare lowercased name while `/api/data/rank-history`
   returns composite `"Name::assetClass"` keys, so the frontend engine
   sees **zero history for every player** and every verdict collapses to
   HOLD. The Signals panel and TopSignalsRail are inert today. The fix
   is `buildHistoryLookup` from `value-history.js` (already used by three
   other call sites), but it changes what those panels show for
   essentially every user — it needs its own review, which is why the
   parity round did not fold it in.
3. **N2 — `low_conf_unstable` is dead server-side.** `terminal.py:764`
   reads `row["confidence"]`; contracts stamp `marketConfidence`. The
   rule has never fired in the alert path, and MONITOR is in
   `ACTIONABLE_SIGNALS` — so fixing it naively would email every user at
   once on the first sweep. It needs the silent baseline-seeding pass
   that `bdvm_signal_alerts.py` already models.
4. **Decide the `coverageWeight` question** (§3.1). It is now honestly
   labelled, but leaving a published formula unapplied indefinitely
   invites the next reader to "fix" it and move every value.

**Highest-value next upgrades**
5. **N3 — `sleeper_overlay._resolve_player_label` fallback.** The real
   name-hygiene target that disproving D2 uncovered (see §8 addendum).
   One function; hardens five consumers at once.
6. **Legacy-curve decision** (§3.2) using the committed backtest.
   Depends on 4 only in the sense that both are curve-governance calls.
7. **BDVM end-to-end validation** once a projection snapshot exists.

**Medium priority**
8. D13 (re-litigate the livedata exemptions), D5/D6 (parity tests),
   D7 (centralize position sets), D9 (cache invalidation).

**Longer-term architecture**
9. D11 (route inventory + retire the unused), D12 (turn on mypy),
   D10 (converge the backup systems), a central env/settings object.

**Defer**
10. Multi-league scrape; TE Axis B (blocked on ADR-009);
    `value_confidence_intervals`.

---

## 14. Final readiness verdict

### ✅ Ready for the next development phase — with two conditions

The valuation pipeline is coherent, its math checks out under
independent testing, and it produces exactly one answer per player.
Every confirmed defect found in this audit was fixed rather than
deferred, and the fixes are provably value-neutral on the default board.
The documentation now matches the code, which was the largest single
source of risk going in: a reader could previously have trusted a
published formula that was never applied, a backlog that misreported its
own highest risk, and a pipeline description with two stages in the
wrong order.

**The two conditions are not blockers to starting, but should not be
carried far:**

1. **Rotate the credential** in git history (C6). Nothing in this audit
   can do it, and it is the only finding with a real-world blast radius.
2. **Add the Buy/Sell/Hold parity test** (D3) before building anything
   new on either signal surface. Two independent engines producing
   user-facing recommendations, with no test binding them together, is
   the most likely place for the next silent divergence — exactly the
   class of problem this audit was commissioned to find.

**Not blockers:** the dual name normalizers (D1) and waiver keying (D2)
are real and should be scheduled, but they are long-standing, bounded,
and now documented rather than hidden.

One deliberate non-decision is recorded rather than resolved: whether to
retire the legacy rank-form Hill curve family. It is measured, written
up, and left to a product call, because the evidence does not favour
either option cleanly and changing it moves numbers users have seen.
