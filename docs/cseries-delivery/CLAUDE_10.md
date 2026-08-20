# Claude 10 — C-Series Delivery Log

**Lane:** C4 (Market / Sharp / FAAB) + dependency-ready waiver- and draft-related C7, per
`docs/EXECUTION_PLAN.md`'s POST-V1 C-Series mass-build campaign lane table (authorized
2026-08-20): "Claude 10 — C4 + waiver/draft C7 | C4 Market / Sharp / FAAB · waiver- and
draft-related C7". Boundary with Claude 8 (new source acquisition, cross-position bridge
architecture, Dynasty Nerds / Dynasty Dealer / Draft Sharks bridge qualification, IDP Show /
Footballguys acquisition, source-family bridge semantics): not touched here.

**Merge posture:** This lane does not merge its own work — Claude 5 (Integration Authority) is
the sole shipping-tree authority (§0.4a). Slices are marked `READY_FOR_INTEGRATION`/
`FEATURE_GREEN` and handed off; per the "Build broadly. Integrate narrowly." campaign rule,
multiple independent bounded PRs are opened rather than one growing branch when file scopes don't
overlap.

**PRs from this lane:**

| PR | branch | scope | status |
|---|---|---|---|
| #961 | `claude/cseries-market-waiver-draft-2njtem` | `C4-WAIV-01`, `C4-MTL-01`, `C4-MTL-03` + read endpoints | see PR for live status |
| (this branch) | `claude/cseries-draft-snapshot-timer` | `C7-DRAFT-02` | below |

**Sandbox constraint that shapes every unit below:** no live network egress and no production
access from this session. Units are chosen so verification is possible entirely from
deterministic tests over synthetic fixtures and, where a unit is deploy/ops-shaped, from the
repo's own structural wiring gates — no unit here claims a production-only artifact (deployed
timers actually firing, live-crawl coverage) as complete.

---

## `C7-DRAFT-02` — pre-auction rookie draft snapshot, automated

**Manifest identity:** `C7-DRAFT-02`, deps `C1-HIST-01` (done). Final state: "Captured
automatically"; prior state: "PARTIAL — `--record-snapshot` exists, must be run before an
auction." Flagged `RET` (irreversible evidence) with a real deadline the V1 completion contract
itself names (appendix A-5): the 2026 rookie auction is one-shot and non-repeatable, and a missed
manual capture means Perfect Draft can never be backtested for that class — no code recovers an
observation nobody made (the same class of gap as `exports/archive/`'s permanent 2026-07-14
boundary, which is why `scripts/backtest_perfect_draft.py`'s own header calls out this exact step
as "the only one code can fix").

### What was built

`deploy/systemd/dynasty-draft-snapshot.{service,timer}.template`, wired into
`deploy/install-systemd-service.sh` via the shared `install_simple_timer` helper — the same
mechanism a prior lane-4 session used to fix the FAAB bid-history timer gap (V1-57). One new
`install_simple_timer "draft-snapshot" "pre-auction rookie draft snapshot"` line, no bespoke
installer logic. The service runs the existing `scripts/backtest_perfect_draft.py
--record-snapshot` **unmodified** — this unit is pure automation of an already-correct capture,
not a rewrite of it — daily at 07:20 UTC, between the canonical board-as-of snapshot (07:10) and
the consensus-edge snapshot (07:30), so it reads a stable, settled contract rather than one
mid-rewrite. `Persistent=true` so a box that happened to be down exactly when the auction started
still captures on boot, late.

The capture itself writes one file per UTC day (`data/draft_backtest/<date>-pre.json`) and never
overwrites a prior day's, so the daily cadence is purely additive and safe to leave running
forever — it doesn't require predicting the exact auction date, just guarantees the most recent
day's file before the auction actually starts is on disk.

Also updated `docs/perfect-draft.md`'s backtest section, which previously read as a manual-step
instruction ("Run it before the auction. That is the missing step") — now states the timer exists
and why the daily cadence is safe, while keeping the manual path documented as still valid for a
freshest-possible capture right before the auction starts.

### Why no bespoke test file

Unlike the consensus-edge snapshot (a hand-rolled unit with its own dedicated
`tests/deploy/test_consensus_edge_snapshot_timer_is_wired.py`, needed because it sits outside the
shared helper), this unit uses `install_simple_timer` exactly like `faab-history`, `crowd-faab`,
`sharp-activity`, `board-snapshot` and `sharp-cohort-snapshot` — so it's automatically covered by
the generic `tests/deploy/test_all_timers_are_wired.py` (template existence, installer wiring,
`User=`/`Group=` conventions via the shared helper, UTC schedule declaration, catch-up safety,
daemon-reload) the moment the template + installer line exist. A duplicate bespoke test would
just re-test the shared helper a sixth time.

### Deliberately NOT claimed

- Any change to `scripts/backtest_perfect_draft.py` itself — the capture logic is already correct
  (per its own extensive header documenting exactly what it does and doesn't solve); this unit
  only automates *calling* it.
- Any backtest scoring work — `score()` in the same script still correctly reports `SKIPPED` until
  a completed auction with realized prices exists; that's unrelated to whether the pre-draft half
  is captured on schedule.
- Production verification that the timer has actually fired (deploy-only, out of sandbox reach).

### Verification

```
bash -n deploy/install-systemd-service.sh
python3 -m pytest tests/deploy/ -q
```
→ bash syntax clean; 361 passed, 4 skipped (pre-existing, unrelated) across the full
`tests/deploy/` suite on current `main` — including every generic timer-wiring gate discovering
and validating the new unit automatically.

### Next candidates (not started this branch)

Back on the `C4-WAIV-01`/`C4-MTL-01`/`C4-MTL-03` lane (PR #961): `C4-FAAB-01` (FAAB Market Heat)
is next in strict dependency order, but is a materially different kind of unit — an approved
**extension of the live, 247-test-covered canonical FAAB engine** (`src/trade/faab_engine.py`),
not a new standalone module, whose own spec §11 requires backtest validation (compare
recommendations with/without the signal) this sandbox cannot produce without live Sleeper
trending data and real bid outcomes. Queued rather than half-validated. `C7-WAIV-01` (Perfect
Waivers) stays blocked on `C4-FAAB-01` plus two other-lane deps (`C2-DROP-01`, `C3-CON-01`),
neither of which exists yet. `C4-SHARP-01/02` are already diagnosed **BLOCKED on production admin
access** by a prior lane-4 session (`docs/lane4/LANE4_V1_RECONCILIATION.md`, already on `main`);
`C4-SHARP-03` already closed via #911.
