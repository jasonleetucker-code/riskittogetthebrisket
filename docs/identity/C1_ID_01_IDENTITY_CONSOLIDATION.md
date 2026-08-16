# C1-ID-01 — One player-identity owner

**Unit:** C1-U2 (`docs/C_SERIES_EXECUTION_MAP.md` §3) · **Manifest row:** `C1-ID-01`
(`docs/C_SERIES_SCOPE_MANIFEST.md` §4) · **Disposition:** CONSOLIDATE · **Profile:** P2
**Authorized:** owner authorization of C1A unit 2, 2026-08-16 (recorded in `docs/EXECUTION_PLAN.md` §0)
**Base:** `main` @ `83277e989fabc892fac8b7f5a34f38b209a94ce7`
**Status:** DUAL-READ LIVE — legacy answers served everywhere; cutover gated on the
production zero-divergence proof (§6)

---

## 1. What this unit is

Before this unit the repo carried **three independent player-identity matchers**, and
they disagreed on real players on the live board (§3). The manifest's end state:
*"Scraper and data-contract matching become adapters"* over the canonical owner
`src/identity/unified_mapper.py` + `src/utils/name_clean.py`, proven by a parity
harness, migrated dual-read → compare → cut over → retire — never a flag-day swap.

The three matchers, as measured on current `main` (they are decision *stacks*, not
single functions):

| # | stack | decides | production role |
|---|---|---|---|
| 1 | `Dynasty Scraper.py` — `clean_name` / `normalize_lookup_name` / `similarity` / `best_match` / `_is_safe_name_merge` + the run()-scope ladders (`_canonical_map`, `_resolve_sleeper_identity`, `match_all`, `_find_site_candidate`, dedupe + guarantee passes) | which scraped rows are one player; which Sleeper id every board row carries | **stamps `playerId` on every one of the 937 identified board rows** |
| 2 | `src/api/data_contract.py` — `_canonical_match_key` cascade in `_enrich_from_source_csvs` + `_pick_provider_id` sid-join + the validation/quarantine detectors | which source-CSV row feeds which board row | every CSV enrichment vote on the contract |
| 3 | `src/identity/unified_mapper.py::resolve_player` — the designated canonical owner | external ids/names → Sleeper directory entry | playerctx normalization; `server.py` realized-game-log + status diagnostics |

(`src/identity/matcher.py` is a fourth *implementation* but not a live decider — see §5.)

## 2. What was built

### 2.1 The canonical engine — `src/identity/resolution.py`

One engine owns resolution semantics through **named, versioned policies**:

- **`SCRAPER_SLEEPER_ATTACH_V1`** — exact transcription of the scraper's ladder,
  hazards included (unguarded initial+last rung, argmax homonym guessing). Exists to
  prove dual-read parity; retired at cutover.
- **`CONTRACT_CSV_JOIN_V1`** (`match_row_to_source_entry`) — exact transcription of the
  contract's sid-first + position-aware-key cascade. Deliberately fuzzy-free: measured
  on the live corpus, the exact join rejected all 544 unmatched CSV names with zero
  false merges (W06-F006 `whatWorks`).
- **`CANONICAL_V2`** — the destination semantics, **dark** (no production consumer)
  until the prod gate authorizes cutover. Repairs, each grounded in a measured defect:
  - fuzzy and initial-expansion rungs are guarded (`is_safe_name_merge` + exact-surname
    requirement) — kills the 3 live sibling false-merges and all 11 W06-F006 pairs;
  - homonym selection prefers the single candidate **currently rostered on an NFL
    team** (Sleeper's `active` flag marks retired Frank Gore Sr. active; `team`
    presence is the honest signal), then single-active as fallback;
  - unresolvable ambiguity is an explicit `UNRESOLVED/ambiguous` with candidates named
    — never a silent first-wins guess (MISSING IS NEVER ZERO, applied to identity);
  - position narrowing is **group-level** (OFFENSE/IDP/KICKER), because sources drift
    between DL and LB for the same human (measured: Byron Young is DL on the board and
    LB in Sleeper for the player the board serves);
  - fuzzy confidence is capped at 0.89, below every exact rung (W06-F006 required
    repair: "never report a fuzzy match above 0.90");
  - deterministic: V2's answer is invariant under directory insertion order
    (test-pinned); the legacy ladders are not (§3, Frank Gore).

Every result is a `Resolution` carrying real join provenance: `method` (which rung
fired), `confidence`, `candidates_considered`, `tie_detected`, `candidate_ids`,
`policy`, and an explicit `reason` when unresolved
(`empty_input` / `pick_name` / `no_candidate` / `ambiguous` / `below_threshold`).
Pick-shaped names are refused with `pick_name` — **pick identity is C1-ID-02 (unit
C1-U3), untouched here.**

### 2.2 The name primitives — `src/identity/name_primitives.py`

The scraper's matching primitives moved **verbatim** into the identity owner;
`Dynasty Scraper.py` imports them back (the adapter direction). Extraction proven
byte-faithful before the originals were deleted: 0 divergences over ~12k directory
names, every source-CSV name, 60k adversarial same-surname pairs and 2,000
`best_match` slates. The `_TEAM_CODES` literal is gone from the scraper;
`name_clean.NFL_TEAM_CODES` is the one table (ownership pinned by the rewritten
`tests/utils/test_team_codes_parity.py`, whose text-tripwire fired exactly as designed
when the literal moved).

The name-key FAMILY registry in `src/utils/name_clean.py` (four deliberate,
non-interchangeable vocabularies) is unchanged in substance; family 4's pointer now
names the new home. **Consolidating the vocabularies themselves is a semantic change
this unit deliberately does not make** — the two adapter sites keep their measured
vocabularies through V1 policies until an owner-gated semantic step.

### 2.3 The two adapters (dual-read, legacy served)

- **Scraper site** (`_resolve_sleeper_identity`): every call now also resolves through
  the engine (V1 + V2), tallies agreement, and serves the **legacy** answer. Artifact:
  `data/scrape_state/identity_dual_read.json`, committed by `scheduled-refresh.yml`
  every cycle, so the prod gate is observable off-box (the C1-RET-02 lesson). Memoized
  per (name, pos); the memo is dropped when the roster-position map is enriched
  mid-run, because that map is evidence the merge guard reads.
- **Contract site** (`_enrich_from_source_csvs`): every (row, source) join decision is
  compared against `match_row_to_source_entry`; the tally is stamped on the contract
  as `identityDualRead`. The inline cascade still serves.
- **Cutover flag:** `RISKIT_IDENTITY_CUTOVER=1` (default OFF) switches the scraper
  site to the engine's V1 answer. Kill-switch for the comparison itself:
  `RISKIT_IDENTITY_DUAL_READ=0` (cost control, not correctness).

## 3. The RED, measured

**"Two matchers disagreeing on a real player on the live board"** — measured
2026-08-16, live board (949 player rows) × the real Sleeper directory (12,219
players): **933 agree · 6 both-unresolved · 10 disagree**, in three classes:

| class | mechanism | cases | example |
|---|---|---|---|
| mapper serves the wrong homonym | `name_pos` rung is first-wins over dict insertion order | 5 | **Frank Gore RB** — mapper serves the retired father (232), scraper + board serve rostered Frank Gore Jr. (11573). The mapper's answer *flips with directory insertion order* (test-pinned) |
| mapper refuses where scraper resolves | no candidate scoring; `name_unique` needs exactly one | 2 | Chris Jones DL → scraper 3558 (served), mapper `None` |
| scraper false-merges absent players | the initial+last rung is **unguarded** | 3 | **Whit Weeks → West Weeks** (his actual brother); Rod Moore → Rahim Moore; Jamarion Miller → Jordan Miller. Only caller-side equality gates kept these off the board |

Neither legacy matcher is uniformly right — which is why the engine absorbs the
scraper's candidate scoring AND repairs the guards, rather than crowning either
legacy ladder as-is. Pinned by `tests/identity/test_matcher_disagreement_red.py` on
`tests/fixtures/identity_directory_subset.json` (a curated subset of the real
directory, live dump order preserved because it is load-bearing).

## 4. Parity evidence (the GREEN, local half)

| measurement | result |
|---|---|
| primitives extraction vs originals (12k names + all CSV names + 60k pairs + 2k slates) | **0 divergences** |
| engine `SCRAPER_ATTACH_V1` vs an independent transcription of the legacy ladder, 9,465 real inputs (board + every CSV name, with position hints) | **0 divergences** |
| contract-join dual-read over the live build (every row × every source) | **24,046 decisions, 0 divergences** (now asserted on every CI run by `tests/identity/test_dual_read_zero_divergence.py`) |
| board after the change (`b5_identity_metrics.py --compare c1u2_baseline c1u2_after`) | **every numeric metric identical** |
| W06-F006's 11 false-merge pairs under `CANONICAL_V2` | **0 false merges** (each input resolves to the *correct* same-named player or refuses) |
| `CANONICAL_V2` vs legacy over the board vocabulary (1,075 names) | **10 differ** — 6 explicit ambiguity refusals of genuine multi-rostered homonym families, 4 explicit refusals of absent players the legacy ladder hands to siblings. This is the measured cost of the future, owner-gated semantic step — recorded, not applied |

Harness: `scripts/identity_parity.py` (exit 0 green / 1 divergence / 2 required
evidence missing; `--require-scraper-artifact` is the prod-gate mode;
`--directory <sleeper dump>` adds the V2 sweep).

## 5. Census dispositions

Full identity census (7-agent sweep + first-hand verification, 2026-08-16). Rules for
this table: RETAINED = stays as-is; ADAPTER = now calls the owner; DEFERRED = its
migration belongs to a later authorized unit and touching it here would cross the
unit boundary.

| implementation | disposition |
|---|---|
| `src/identity/resolution.py` (new) | **CANONICAL OWNER** — all resolution semantics |
| `src/identity/name_primitives.py` (new) | **CANONICAL OWNER** — scraper-family primitives |
| `Dynasty Scraper.py` primitives | **ADAPTER** (imports the owner; local defs deleted) |
| `Dynasty Scraper.py::_resolve_sleeper_identity` | **DUAL-READ** → cutover → retire (this unit, prod-gated) |
| `data_contract._enrich_from_source_csvs` cascade | **DUAL-READ** → cutover → retire (this unit, prod-gated) |
| `unified_mapper.resolve_player` | **RETAINED as legacy-V1 compat** for its 3 existing consumers; canonical API is `resolution.resolve_canonical_v2`; no new consumers (docstring enforces); consumer migration is a staged step after cutover |
| Other scraper ladder sites (`match_all`, `_canonical_map`, `_find_site_candidate`, dedupe/guarantee passes) | **STAGED** — they now consume owner-owned primitives; converting each site's ladder to an engine policy follows the same dual-read pattern after the first cutover proves out (recorded below, §7) |
| `src/identity/matcher.py` (`build_identity_resolution`) | **RETAINED, dormant** — library of the halted C1-RET-07 scaffold-report producer; not a live decision path; its fate belongs with the C1-RET-07 resumption decision, not silently here |
| `src/pool/builder.py` `pool_clean_name`/`pool_normalize_lookup` | **DEFERRED** — deliberate mirrors (team codes already shared); folding onto `name_primitives` is a staged follow-up |
| `src/ros/mapping.py::resolve_player` | **DEFERRED** — seasonal-lane resolver; consolidation belongs to the C5 lane (it already consumes `name_clean` family 1 + the alias table) |
| `src/playerctx/normalize.py` | **DEFERRED** — mapper consumer with its own team-decisive layer; migrates with the mapper-consumer step. Its private `_load_overrides` import is a recorded contract smell |
| `src/platforms/assets.py::AssetResolver` | **DEFERRED** — C4 sharp-lane (FFPC↔Sleeper) resolver with its own durable crosswalk |
| `src/consensus_edge/identity_join.py` | **RETAINED** — exact id-chain join, refuses rather than guessing; already conformant |
| news/BDVM/compact/loose name-key lanes | **RETAINED** per the name-key family registry — different vocabularies by design, documented there |

Adjacent defects found and deliberately **not** fixed here (recorded, out of the
smallest-correct-change set): W06-F011 (rostered-unpriced player erased from identity
maps), W06-F012 (no collision guard on `player_id_map`), the BDVM
baseline/context name-collision asymmetry, and the `identityConfidence` semantics
(rename owned by C1-CONF-01 / unit C1-U5 — its "1.00 canonical_id means a name-matched
id" trust-laundering is documented in W06-F005 and untouched).

## 6. The prod gate and the remaining stages

Per the execution map: **dual-read → compare → cut over → retire.** This PR delivers
dual-read + compare, provably inert (the served board is unchanged — §4).

1. **Observe** (next): each production scrape writes
   `data/scrape_state/identity_dual_read.json`; each contract build stamps
   `identityDualRead`. Gate: **`v1Diverge == 0` over a full refresh cycle** on both
   sites. `scripts/identity_parity.py --require-scraper-artifact` is the check.
2. **Cut over** (after the gate): set `RISKIT_IDENTITY_CUTOVER=1` in the production
   environment; the scraper site serves the engine's V1 answers (identical by proof);
   the contract site's inline cascade is replaced by the owned function (zero-diff by
   CI pin).
3. **Retire** (same window): delete `_resolve_sleeper_identity_legacy` and the inline
   cascade; drop the flag. The unit's "retires 3 independent matchers" line closes
   here.
4. **Semantic step** (separate, owner-gated, NOT part of this unit's closure):
   activating `CANONICAL_V2` at the scraper site changes 10 board-vocabulary
   resolutions (§4) — every one an explicit refusal replacing a guess. That is a
   product decision on how the board renders `ambiguous`/`unresolved`, and it waits
   for the owner.

## 7. Follow-up ledger (non-blocking)

- Convert the remaining scraper ladder sites (`match_all`, `_canonical_map`,
  `_find_site_candidate`, dedupe/guarantee passes) to engine policies, one dual-read
  at a time, after the first cutover proves the pattern.
- Migrate the mapper's 3 consumers to `resolution.resolve_canonical_v2`; then retire
  `resolve_player`'s raw-fuzzy rung (closing W06-F006 at every layer, not just at the
  canonical API).
- Fold `pool_clean_name`/`pool_normalize_lookup` onto `name_primitives`.
- W06-F011 / W06-F012 repairs (identity-map construction hazards in the scraper).
- `playerctx`'s private `_load_overrides` import → a public seam on the owner.

## 8. Invariants this unit holds (and tests that pin them)

- The board is byte-inert: `b5_metrics` numeric-identical; contract-join dual-read
  24,046/0; full backend suite green.
- The W06-F002 near-name detector **stays retired** — nothing here reintroduces it.
- Unresolved identity ≠ best fuzzy guess: `CANONICAL_V2` refuses with named reasons
  and named candidates (`test_matcher_disagreement_red.py`,
  `test_resolution_engine.py`).
- One owner: the scraper carries no private name-matching definitions
  (`test_team_codes_parity.py` structural pins), and the CSV-join transcription
  cannot drift from the inline cascade unnoticed
  (`test_dual_read_zero_divergence.py`, every CI run).
- Pick identity untouched (C1-ID-02): pick-shaped names refuse with `pick_name`.
