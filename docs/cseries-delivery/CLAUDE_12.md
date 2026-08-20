# Claude 12 delivery ledger — C6 (Analyst, Signal, Manager & AI Intelligence)

Maintained per assignment instructions. One entry per batch, oldest first.

**Reconciliation note for Claude 5:** a copy of this file with Batch 1's
entry also exists on `claude/cseries-intelligence-data-80btkq` (PR #970,
frozen, non-mergeable against moving `main`). This copy was recreated fresh
on `claude/c6-ana-01-evidence-ledger` (PR for `C6-ANA-01`, based on current
`main`, which does not yet contain #970's commit) because the file did not
exist on `main` at the time this branch was cut. When #970 is integrated,
these two copies will need a normal content merge — both batch entries are
real and neither should be dropped.

---

## Governance finding (read first)

Before writing any code in this lane, this session checked the repo's own
binding authorization record, `docs/VERSION_1_COMPLETION_CONTRACT.md`
(referenced as authoritative by `docs/EXECUTION_PLAN.md` §0), against the
assigned C6/C7 mandate.

**Every item in the assigned mandate is explicitly classified POST-V1**:

| Assignment | Classification |
|---|---|
| Central Buy/Sell reconciler + ticker (`C6-SIG-01/02`) | §4.2 — Lane-4 deferred continuation, not V1-required |
| Analyst claim/evidence ledger, podcast/YouTube/X ingestion, freshness/decay | §4.1 — named POST-V1 by the owner; the ledger itself is also §6 externally blocked (`C6-U2`, credentials absent) |
| Manager Scout (`C6-MGR-01`) | §4.1 — named POST-V1 by the owner |
| Consensus Edge (`C6-EDGE-01`) | §7.1 A-7 — split: only nav-gating truthfulness is V1 (owned by Lane 6/UI, not this session); the feature itself is POST-V1 |
| Universal Player Profile expansion | §4.3 / §7.2 Q2 — POST-V1, pending an open owner call on "high-use" status |
| Ask Brisket / AI Front Office, Edge Alerts | §4.1/§4.2 — named POST-V1 |

This was surfaced to the user rather than silently proceeding or silently
standing down. **The user explicitly authorized proceeding anyway (owner
override), overriding the V1 sprint's lane boundaries for this work.**
Confirmed still current per the 2026-08-20 mission brief for this lane: "Your
C6/C7 intelligence mandate is POST-V1. The owner explicitly authorized this
POST-V1 mass-build lane. Do not represent it as V1 numerator progress."

This does not relax any *methodology* invariant in `CLAUDE.md` — ONE
CONCEPT ONE CANONICAL OWNER, MISSING IS NEVER ZERO, signal independence,
champion-vs-challenger, and "recommendations and execution are separate"
all still bind.

---

## Batch 1 — `C6-SIG-01` Central Buy/Sell Reconciler + `C6-SIG-02` canonical ticker contract (backend/data only)

**PR #970**, branch `claude/cseries-intelligence-data-80btkq`. **FROZEN** as
of this batch — GitHub reports it non-mergeable against a moving `main` (48
commits ahead of the merge base); per explicit instruction this lane does
not chase `main` on that branch, and Claude 5/Integration owns its
reconciliation.

Scope, in full: new `src/signals/` package reconciling three independent
evidence families into one verdict per asset (`board_consensus_gap` from the
existing market-gap stamp, `bdvm_fundamental` from
`src.bdvm.market.buy_hold_sell`, `sharp_transaction` **read-only** from
`src.sharp.market.market_payload`), with a reserved `consensus_edge_composite`
slot that never fires (Consensus Edge stays flag-off; ADR-023's backtest
gate still says don't ship). Additive `movementWindows` field on every
`/api/data` row (7d/30d, ledger-sourced). New `GET /api/signals/market-ticker`
endpoint, not leagueKey-scoped. Deleted `src/news/unified_signal_engine.py`
(confirmed zero production callers) and its test. Reuses
`src.analyst.stance.Stance`/`Direction` as the canonical vocabulary rather
than declaring a parallel one — corrected mid-build after a closer read of
`src/analyst/__init__.py`.

Verification: 47 new tests, all passing; 4 manual mutation-proofs on
load-bearing precedence/guard branches, each confirmed RED then reverted;
full `tests/api/` suite (2273 passed, 32 skipped, 0 failed) confirmed clean
after the change.

Full design record: `docs/lane4/C6_SIG_01_RECONCILER.md`.

---

## Batch 2 — `C6-ANA-01` Analyst claim/evidence ledger: persistence + as-of query (zero ingestion)

**Branch `claude/c6-ana-01-evidence-ledger`**, based on fresh `main`
(`7c826f9c2` at the time this branch was cut) — deliberately NOT stacked on
the frozen #970 branch.

**Scope-defining finding, discovered before writing any code:** the schema
half of this unit already exists and is canonical.
`src/analyst/claim.py` + `src/analyst/stance.py` (already on `main`,
commit `5351e7150`) define `AnalystClaim`, `SourceRef`, `Provenance`,
`GameType`, `AssetSide`, `TakeType`, `Condition`, `thesis_key`-based dedup,
`independent_claims()`, `dynasty_claims()`, and the full
`Stance`/`SourceLabel`/`ConvictionClass`/`Direction` vocabulary — already
reused live by #970's `src/signals/reconciler.py`. `docs/analyst/CLAIM_SCHEMA.md`
documents it as "schema only. No ingestion, no consumers yet — by design."
Building a second schema here would have violated ONE CONCEPT ONE CANONICAL
OWNER. **This batch is therefore the persistence + as-of query layer around
the existing schema, not a new schema.**

**What shipped:** `src/analyst/store.py` (an `ExtractionConfidence`-enum
ingestion envelope, `LedgerEntry`, wrapping `AnalystClaim` without modifying
it — mirrors `src.acquisition.store`'s idiom: structured columns, a natural
identity key, `content_hash()` over the non-identity facts, three-way
`{inserted, unchanged, conflicts}` write outcome, conflicts surfaced and
never applied) and `src/analyst/query.py` (`claims_as_of` — a hand-rolled
sibling to `retention.evidence_store.scoring_card_at` /
`acquisition.roster.roster_at`, since no shared as-of library exists
independent of `src.history.asof`'s value/rank-hardcoded columns — with a
structural never-future guard: `effective_discovered_at = claim.discovered_at
or entry.recorded_at`, so a claim can never leak backward merely because an
extractor never populated `discovered_at`).

Full design record, including a documented mid-build refinement (the
identity/content-hash split deliberately excludes `stance` from identity,
unlike a literal copy of `AcquisitionEvent`'s pattern — see the doc for why)
and the mutation-verification log: `docs/analyst/LEDGER_STORAGE.md`.

**Verification performed:**
- 84 tests in `tests/analyst/` all passing (57 pre-existing + 27 new):
  `python -m pytest tests/analyst/ -q` → `84 passed`.
- 3 manual mutation-proofs, each confirmed RED against the relevant test(s)
  then reverted, working tree confirmed clean via `git diff` after each:
  (1) dropping the never-future discovery-boundary filter in `claims_as_of`
  — 3 of 5 `TestNeverFutureLeak` tests failed; (2) forcing `write_claims`'s
  conflict branch to always take `unchanged` — the conflict-surfacing test
  failed; (3) a fake `from src.analyst.store import write_claims` import
  prepended to `src/api/data_contract.py` — the non-influence guard failed,
  naming the file.
- `docs/C_SERIES_SCOPE_MANIFEST.md`'s `C6-ANA-01` row updated from ABSENT
  to PARTIAL (schema + ledger exist; ingestion/consumers still absent) —
  confirmed stale by the pre-build audit.

**Deliberately NOT claimed in this batch:** any ingestion (podcast/YouTube/X
scraper, transcript fetcher, extractor — zero credentials touched; a future
unit reports `AUTH_REQUIRED` if still blocked when it starts); scoring,
weighting, or source-family correlation *weights* (only lineage
*preservation* via the existing `thesis_key`); sentiment-to-value
conversion; freshness/decay policy (`C6-FRESH-01`); any consumer wiring
(Manager Scout, Universal Player Profile, Ask Brisket, Consensus Edge) —
ships inert; structured price/pick-cost context (owner spec also names this;
`conditions`/`notes` hold it as free text only); player-name-to-identity
resolution (a future extractor's job — `src.identity.resolution.resolve_canonical_v2`
exists but is currently DARK, unwired pending its own production gate).

---

## Roadmap — remaining C6/C7 units (not yet started)

In rough dependency order per `docs/C_SERIES_SCOPE_MANIFEST.md` §4 C6/C7:

1. **`C6-POD-01` / `C6-YT-01` / `C6-X-01`** — podcast/YouTube/X ingestion.
   Depends on Batch 2's ledger (now available) and on credentials that are
   externally blocked (`OD-03`) as of this writing. Per standing
   instruction: build the ingestion FRAMEWORK (schemas, replay fixtures,
   auth-state stubs, adapter interfaces) with zero live ingestion if
   credentials remain unavailable, and report `AUTH_REQUIRED` rather than
   fabricate data or bypass access controls.
2. **`C6-FRESH-01` freshness/decay for analyst takes.** Depends on Batch 2
   (now available — `said_at`/`discovered_at`/`recorded_at` are exactly
   what a decay policy would read). `src/signals/families.py`'s tri-state
   fresh/stale/unmeasurable idiom is the established pattern to extend.
3. **`C6-MGR-01` Manager Scout (CE-03).** Substrate exists
   (`src/intel/service.py::build_member_payload`, `src/intel/signals.py`,
   `src/acquisition/`, `src/sharp/platform_records.py`) but no
   tendency-dimension scoring exists anywhere. Manifest dependency
   `C4-MTL-01` (Market Trade Ledger) is itself POST-V1/externally blocked
   per the completion contract §6 — needs resolving or explicitly
   descoping before this unit can start.
4. **`C6-EDGE-01` Consensus Edge repair.** The engine is fully built and
   self-describing; the gap is its failed pre-registered ship gate (fixing
   the identity-join defect, W14-F001, and any other measured defect — not
   flipping the flag, which needs a genuine re-passing backtest per
   ADR-023, not a judgement call).
5. **`C6-UPP-01` Universal Player Profile expansion.** Only a public-safe
   league-journey page exists today; no private canonical per-player
   aggregation surface exists at all. A new aggregation layer over
   already-existing but siloed data, plus the still-absent multi-source
   news/intelligence feed this ledger is meant to eventually back.
6. **C7 consumers**, once their C6 inputs are stable: `C7-ALERT-01` Edge
   Alerts (consumes #970's reconciler output — no alerting/cooldown/delivery
   code exists yet), Command Center intelligence surfaces, Ask Brisket / AI
   Front Office scaffolding (per the AI rule: consumes canonical
   deterministic services, never becomes a second source of canonical
   valuation/math).

Each future unit gets its own dated batch entry above, its own bounded PR,
and its own explicit "not claimed" list.
