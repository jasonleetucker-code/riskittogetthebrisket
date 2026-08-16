# Work Claims

> **2026-08-14 — post-B master reconciliation.** Any claim row below referencing pre-B-completion state is
> closed. The reconciliation touched planning and documentation only, on
> `claude/master-reconciliation-post-audit-ewgl00`. No C implementation is authorized.


**What you are about to work on, recorded before you start.**

One row per piece of work in flight. Add yours in your first commit; set it
`done` in your last. Check it before you begin:

```bash
python scripts/check_work_claims.py --files <paths you will change> --defect <ids>
```

That script also scans remote branches, because claims are voluntary and
branches are evidence.

---

## Open claims

| Claim | Paths | Defect ids | Branch | Status |
|---|---|---|---|---|
| C1A unit 6 — pick completeness through 2029 (`C1-PICK-01`/`C1-PICK-02` / map unit C1-U6). Owner-authorized 2026-08-16 at the C1-U4 checkpoint (C1-U5 deliberately deferred). Canonical future-pick value completeness in the `data_contract` pick pipeline: finite provenance-stamped canonical values for every valid pick through 2029 (year-step derivation replacing the uncalibrated clone-x0.53, round-step completion for future rounds 5-6, generic-grade board rows, cap-immune pick value stamping), the canonical MarketPickRef->value resolver, the generic<->exact-slot transition test, and the authorized trade-facing lookup repairs (draft-capital future-year pricing, simulator roster-pick identity join). Calibration per MATH_MODEL_CALIBRATION_POLICY §3.1: challenger-tested year-step family, PRIOR-classified, evidence pinned in docs/picks/. Deliberately NOT claiming: C1-U5 confidence renames, C1-U7 owned-pick distributions, C1-U8 lineage/re-key, trade-engine methodology, projections, UI redesign, scraper pick-model rebuild (rollover literal defect recorded as follow-up). NOTE path overlap: `src/api/data_contract.py` also named by the open `claude/dynasty-audit-consolidation-e75vdy` claim (curve routing / coordinate consumption — disjoint regions from the pick pipeline; EXECUTION_PLAN §4 serial-writer rule honored: this is the only active data_contract pipeline writer). | src/api/data_contract.py (pick pipeline), src/api/pick_value_resolution.py (new), src/identity/picks.py (generic-grade board-row name + parser only), src/api/draft_capital_fallback.py (future-year value resolution), src/api/trade_simulator.py (roster-pick identity join only), src/canonical/calibration.py (dormant pick pricer retirement), config/weights/pick_year_discount.json, scripts/calibrate_pick_year_step.py (new), tests/api/, tests/identity/, tests/trade/, docs/picks/, docs/EXECUTION_PLAN.md, docs/C_SERIES_EXECUTION_MAP.md, docs/C_SERIES_SCOPE_MANIFEST.md, docs/WORK_CLAIMS.md, PRODUCT_PLAN.md, CLAUDE.md | C1-PICK-01, C1-PICK-02, V-12/C-11 (the uncalibrated clone-discount prior) | claude/c-series-fable-implementation-u2ghlv | done |
| C1A unit 4 — one immutable as-of value/provenance ledger (`C1-HIST-01`/`-02`/`-03` / map unit C1-U4). Owner-authorized 2026-08-16 at the C1-U3 checkpoint. New canonical temporal owner under `src/history/` (as-of lookup, fidelity labels, missing semantics, rankChange derivation, player+pick namespaced keys via C1-U2/C1-U3 identity), backfill from `exports/archive/` (2026-07-14 boundary permanent, pre-boundary = missing), rankChange determinism repair at `data_contract._stamp_rank_changes`. Deliberately NOT claiming: valuation methodology, trade grading/replay (C3-U9), pick valuation (C1-U6/U7), acquisition lineage (C1-U8), confidence renames (C1-U5), projection/backtest engines (C5), any UI. | src/history/, src/api/data_contract.py (_stamp_rank_changes only), src/api/rank_history.py (adapter seam only), src/snapshots/board_store.py (read-owner integration only), server.py (recording call sites only), scripts/ (backfill + census helpers), tests/history/, docs/history/, docs/EXECUTION_PLAN.md, docs/C_SERIES_EXECUTION_MAP.md, docs/C_SERIES_SCOPE_MANIFEST.md, docs/WORK_CLAIMS.md, CLAUDE.md | C1-HIST-01, C1-HIST-02, C1-HIST-03 | claude/c1-u4-temporal-ledger-57beor | done |
| C1A unit 3 — one pick identity, end to end (`C1-ID-02` / map unit C1-U3). Owner-authorized 2026-08-16 at the C1-U2 checkpoint. Canonical owner `src/identity/picks.py` (league-pick identity = league_key+season+round+origin; market-pick refs at slot/tier/generic grades; generic→exact transition as pure state change; every legacy label grammar parsed, both legacy label grammars formatted by the owner with byte-parity pinned). Consumers adapted: data_contract pick regex/parse helpers delegate; sleeper_overlay fold+labels delegate (+additive `assetId` on pickDetails, fail-closed on unregistered league); scraper pick block delegates (S3 in-run map retired); draft_capital_fallback name formatting delegates; intel crawler pick asset-id strings route through the owner (persisted generic grade UNCHANGED — re-key is C1-U8). Board proven byte-inert (0/1093 rows, 0 values, 0 ranks via golden_board+board_diff). Deliberately NOT claiming: pick valuation (C1-PICK-01/02/03 pricing halves), the intel-ledger re-key (C1-ACQ-01/03), frontend lookup migration (needs C1-U6 generic rows; grammar-parity test pins lockstep), public_league fold (bespoke multi-season semantics, origin retained), C1-U4+, any trade-engine behavior. | src/identity/picks.py, src/api/data_contract.py (pick grammar delegation only), src/api/sleeper_overlay.py (pick fold/labels only), src/api/league_registry.py (league_key_for_sleeper_id only), src/api/draft_capital_fallback.py (_normalize_pick_name only), src/intel/crawler.py (asset-id strings only), Dynasty Scraper.py (pick block only), tests/identity/test_pick_identity*.py, tests/fixtures/pick_identity_live_subset.json, docs/identity/C1_ID_02_PICK_IDENTITY.md, docs/EXECUTION_PLAN.md, docs/C_SERIES_EXECUTION_MAP.md, docs/C_SERIES_SCOPE_MANIFEST.md, docs/WORK_CLAIMS.md, CLAUDE.md | C1-ID-02 | claude/c1-u3-pick-identity-c05p7s | done |
| Stage-A audit consolidation, now through B3: Phase A truth re-baseline + verified quick wins, the W30-F008 percentile-coordinate repair (fit/holdout/serving share one coordinate; **no production constant changed**), the /trade multi-team crash hotfix, and model-governance hardening (scope-specific promotion gate, snapshot pinning, complete input fingerprinting, appliedAt/measuredAt lifecycle, registry self-destruction fix), and the B2 curve-routing root cause (W02-F001: the Hill master is now chosen from the rank's coordinate pool, `src/canonical/rank_coordinates.py`, never from the source's registry declaration; **no Hill constant changed, nothing promoted or applied**), and the B3 market-corridor methodology repair (W02-F003: the arbitrary IDP 0.15 hard band cap removed so the corridor's board-derived per-bucket P90 decides again; three residuals tracked as W02-F015/F016/F017 rather than closed into the finding's narrative). Deliberately NOT claiming server.py, frontend/app/api/* bridge routes, or src/api/sleeper_overlay.py — those belong to the live `claude/bridge-timeout-root-cause` session (last push 2026-08-10 22:33Z); verified untouched by path intersection. **Overlap note:** `src/api/data_contract.py` is also touched by `origin/claude/league-intel-projections` and `origin/claude/league-intel-sim`; our change there is the `rank_to_percentile` consumption (~22 lines, B1) plus the B2 curve-routing repair (~120 lines in the Phase 1/1b/1c/1d translation passes and `_curve_for_rank`). Verified non-overlapping by diff: neither branch touches curve routing, the translation flags or the Hill constants — both are +43/-10 in unrelated regions. No shared defect. `frontend/__tests__/draft-logic.test.js` overlaps `origin/claude/rookie-draft-optimizer-386qyu` — same file, different defect (stale phantom imports). | docs/master-site-audit/ (claims-frozen file, re-baseline, W08+W30 evidence), docs/ARCHITECTURE_HANDOFF.md, docs/WORK_CLAIMS.md, docs/BRANCH_DISPOSITION_2026-08-11.md, docs/OWNER_FEATURE_INVENTORY.md, .github/workflows/refit-hill-curves.yml, src/canonical/player_valuation.py, src/canonical/rank_coordinates.py, src/api/data_contract.py (coordinate consumption + curve routing), src/model_registry/*, scripts/fit_hill_curve_percentile.py, tests/{canonical,model_registry,audit,api}/, frontend/__tests__/, frontend/components/waivers/ManualAddDrop.jsx, frontend/app/trade/page.jsx, frontend/lib/trade-logic.js | W31-F001, W11-F006, W08-F004, W30-F008 (coordinate half; challenger NOT promoted), W30-F023 (open, measured), W30-F024 (fixed), W02-F001 (fixed), W02-F001b (fixed), W02-F002 (resolved as a consequence; direction partially remains), W02-F003 (fixed in B3), W02-F015 / W02-F016 / W02-F017 (new, open) | claude/dynasty-audit-consolidation-e75vdy | open |
| C1A unit 2 — one player-identity owner (`C1-ID-01` / map unit C1-U2). Owner-authorized 2026-08-16. Canonical resolution engine (`src/identity/resolution.py`) + scraper name primitives moved verbatim into the owner (`src/identity/name_primitives.py`); dual-read adapters at the two consolidation sites (scraper `_resolve_sleeper_identity`, contract `_enrich_from_source_csvs`) serving the LEGACY answers — the board is provably inert (b5 metrics identical; contract-join dual-read 24,046/0). Deliberately NOT claiming pick identity (C1-ID-02/C1-U3), the confidence renames (C1-CONF-01/C1-U5), matcher.py's scaffold lane, pool/ros/playerctx/sharp resolver lanes (deferred per the census dispositions), or any C2+ work. | src/identity/, Dynasty Scraper.py (primitives block + _resolve_sleeper_identity + dual-read artifact), src/api/data_contract.py (_enrich_from_source_csvs instrumentation + identityDualRead stamp), src/utils/name_clean.py (registry pointer), tests/identity/, tests/fixtures/identity_directory_subset.json, tests/utils/test_team_codes_parity.py, scripts/identity_parity.py, docs/identity/, docs/EXECUTION_PLAN.md, docs/C_SERIES_EXECUTION_MAP.md, docs/WORK_CLAIMS.md, CLAUDE.md | C1-ID-01, W06-F006 (closed at the canonical API; legacy rung retained as named V1 compat pending consumer migration) | claude/c-series-c1a-u2-kergfj | done |
| C1A unit 1 — irreversible-evidence retention (`C1-RET-01`…`C1-RET-08`). Authorized by `docs/EXECUTION_PLAN.md`; scope is `docs/C_SERIES_SCOPE_MANIFEST.md`. New append-only substrate under `src/retention/` (INTERNAL evidence store for per-observation scoring-card history + Sleeper trending; a SEPARATE **private** ledger for own-league transactions), a health probe covering all eight streams with a schedulable CI check, backup coverage for the seven previously-unbacked stores, and honest freshness labelling on `/api/scaffold/identity`. **No decision path reads any of it**; no valuation, ranking, trade or FAAB behaviour changed. Deliberately NOT claiming `C1-HIST-01`, Trade History, identity consolidation, or any C1B/C2+ work — all unauthorized. Touch points in existing files are narrow and additive: `league_registry.write_scoring_snapshot` (record before the overwrite), `sleeper_overlay._build_trades_block` (emit `transactionId`, record before the window cutoff), `server.py` (post-scrape trending record + the identity freshness block). | src/retention/, tests/retention/, scripts/retention_health.py, deploy/diagnostics/retention_health_probe.sh, .github/workflows/retention-health.yml, deploy/backup/riskit-state-backup.sh, docs/retention/RETENTION_REGISTER.md, src/api/league_registry.py (write_scoring_snapshot only), src/api/sleeper_overlay.py (_build_trades_block only), server.py (post-scrape warm + /api/scaffold/identity only) | C1-RET-01 … C1-RET-08 | claude/master-reconciliation-post-audit-ewgl00 | open |
| Work-claim protocol | docs/WORK_CLAIMS.md, scripts/check_work_claims.py, ASSISTANT_COORDINATION.md | — | claude/work-claim-protocol | done |
| PR-backlog audit: repair of the /edge market-gap display half | frontend/app/edge/page.jsx, frontend/app/edge/edge-columns.jsx, frontend/lib/edge-helpers.js | C09 (S-3) | claude/fix-plan-uex7ug | done |

---

## Why this file exists

On 2026-08-05, five sessions independently solved the **same eight defects**
inside one working window, and in no case did anyone notice until a branch had
already merged:

| Defect | Solved in | And independently in |
|---|---|---|
| Market gap computed in rank space | #740 | #722 **and** #742 — three times |
| `tepMultiplier` default forces the override path | #740 | #722 |
| `_sanitize_next_path` accepts a backslash | #740 | #722 |
| FAAB budget-regime mixing | #740 | #707 |
| ROS absence coerced to 0.0 odds | #740 | #736 |
| Compact view drops `appliedWeight` | #740 | main |
| SSR streaming "duplicate" (#716) | #741 | #747 |

**Eight duplicated repairs across five sessions**, and the market-gap defect was
solved three separate times.

**#742 was pushed AFTER #740 merged.** Its branch does not contain `cef17703`, and
it touches the same three files the merged fix landed in. So this is not a tidy
retrospective about a bad afternoon — the collisions were still happening while
this document was being written.

Every individual collision was resolved sensibly — the better-documented
version was kept each time. The aggregate was not sensible: roughly a third
of a session's output was discarded, and **which version survived came down
to which branch happened to be mergeable first, not which was better.** In
at least one case nobody compared the two implementations at all.

`ASSISTANT_COORDINATION.md` already required branching, and already required
`git pull --ff-only origin main` before starting. Neither prevented any of
this, and it is worth being precise about why: **both rules are about where
your work goes, and none of them tells you what someone else is already
doing.** A branch you never listed is a branch you will duplicate.

So the missing step is not another rule about branching. It is a place to
look, and something worth looking at when you get there.

## The format, and why it is a markdown table

A markdown table is editable in the same commit as the work, readable in a
PR diff, and mergeable by hand. A JSON registry would conflict on every
concurrent claim — which is exactly the failure this is meant to reduce.

Columns:

- **Claim** — one line a human recognises. "FAAB budget regimes", not "fix bug".
- **Paths** — comma-separated files you expect to change. Approximate is fine;
  the point is overlap detection, not a manifest.
- **Defect ids** — `C12`, `W22-F001`, audit finding ids, `—` if none.
- **Branch** — where the work lives, so a collision has somewhere to go.
- **Status** — `open` while in flight, `done` once merged or abandoned.

## What to do when you hit an overlap

Not "stop". Overlap is often legitimate — two people fixing different bugs
in one large file collide on paths and not on meaning.

1. **Read the other branch.** `git diff origin/main..origin/<branch> -- <path>`.
2. **If it is the same defect:** do not write it again. Either take theirs and
   move on, or say concretely why yours should replace it — on the PR, before
   the work, not after.
3. **If it is a different defect in the same file:** carry on, and say so in
   your claim row so the next person does not have to re-derive it.

## Honest limits

- Nothing enforces this. `check_work_claims.py` exits 0 unless you pass
  `--strict`. A gate that cries wolf gets ignored, which is roughly how the
  previous coordination rules failed.
- It only helps if run *before* the work. Run afterwards it is a conflict
  report.
- A session that never fetches sees stale branches. The branch scan is only
  as current as your last `git fetch`.
