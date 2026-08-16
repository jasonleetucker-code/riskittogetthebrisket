# C-Series Execution Map

**Status:** CANONICAL ACTIVE — the bounded-unit decomposition of the C-Series census
**Created:** 2026-08-15
**Decomposes:** `docs/C_SERIES_SCOPE_MANIFEST.md` (**163 rows** — 142 C-phase, 14 completed
foundations, 7 explicitly out of scope)
**Binding methodology inputs:** `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`,
`docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md` (PR #853)
**Authorization:** **THIS FILE AUTHORIZES NOTHING.** `docs/EXECUTION_PLAN.md` alone
answers "what may I build now?" Today that answer is **nothing** — C1A units 1 and 2
both closed on 2026-08-16 and the next unit awaits an owner decision.

---

# 0. What this file is, and what it is not

The manifest is a **census** — it proves nothing is lost. This file is the
**decomposition** — it turns 163 census rows into bounded units a session can
actually execute, in an order that does not require improvising architecture
halfway through.

It exists because the failure mode it prevents is specific and has already
happened elsewhere in this repo: a later session, holding a row like
"Canonical Team Strength", invents a lineup solver because the canonical one was
not obviously reachable, and the codebase gains a fifth competing notion of the
same concept. Every unit below therefore names its **canonical owner** and the
**duplicates it retires**, not just its outcome.

**Mapping is not authorization.** §18 restates the boundary in full.

## 0.1 Unit identifier scheme

`<phase>-U<n>` — e.g. `C2-U4`. Stable, never renumbered, never reused. A unit is
the grain at which work is authorized, branched, reviewed and merged. Manifest row
ids keep their own identity and are never renamed to match a unit.

## 0.2 Fields carried by every unit

| field | meaning |
|---|---|
| **rows** | the manifest rows this unit discharges — **exactly one unit per row** |
| **owner** | the canonical module/service that owns the concept afterwards |
| **retires** | duplicate implementations that must be gone when the unit closes |
| **deps** | units that must close first (hard) |
| **kind** | `INFRA` (no user-visible change) or `PRODUCT` (user-visible) |
| **RED→GREEN** | the failure that must be reproduced before the fix |
| **CI gate** | what exact-head CI must prove |
| **prod gate** | what production must prove, measured, before the unit is closed |
| **consumers** | who reads the output afterwards |

## 0.3 The three standing rules every unit inherits

1. **One concept, one canonical owner.** A unit that leaves two implementations
   alive has not closed, whatever its tests say.
2. **Missing is never zero.** Every unit preserves explicit missing / stale /
   insufficient / unavailable states end to end. A unit may not close by making an
   unknown look like a number.
3. **No hidden fallback.** A degraded path must be *named* in the payload and
   visible to the consumer. Silent substitution is the defect class this whole
   series exists to remove — see `C1-RET-08` and the backup-root repair (#852) for
   two independent instances of exactly that shape.

---

# 1. Phase-level dependency spine

```
C0 governance ─┬─> C1 identity + temporal substrate ─┬─> C2 roster math ─┬─> C3 trade substrate
               │                                     │                   │
               │                                     │                   ├─> C7 decision products
               │                                     │                   │
               │                                     ├─> C4 market/sharp ─┤
               │                                     │                   │
               │                                     ├─> C5 seasonal ────┤
               │                                     │                   │
               │                                     └─> C6 intelligence ┘
               │
               └─> C8 perf/design (parallel-safe throughout) ──> C9 public/storytelling ──> C10 closure
```

**The one non-negotiable ordering rule**, from the calibration policy §8: *do the
math at its canonical owner before high-order products consume it.* C7 may not
begin against a provisional C2/C3 formula, because tuning a product around a
temporary formula is how the formula becomes permanent.

---

# 2. C0 — Governance (11 rows, 3 units)

Mostly discharged by the post-B reconciliation; listed so the census closes.

### C0-U1 — Governance closure
- **rows** `C0-GOV-01` `C0-GOV-02` `C0-GOV-03` `C0-GOV-04` `C0-GOV-05` `C0-GOV-06` `C0-GOV-07` `C0-GOV-08` `C0-GOV-09`
- **owner** `docs/EXECUTION_PLAN.md` + `scripts/check_planning_integrity.py`
- **kind** INFRA · **deps** none
- **CI gate** planning-integrity gate green; CE namespace collision-free
- **status** substantially COMPLETE via #845; `C0-GOV-09` reopens whenever owner
  intent lands on an unmerged branch (it did again today — PR #853)

### C0-U2 — Performance baselines before feature work
- **rows** `C0-PERF-01` · **owner** `tests/e2e` + bundle budget · **kind** INFRA
- **deps** none — **parallel-safe with everything** (read-only measurement)
- **why first** a baseline captured after C7 lands cannot show what C7 cost

### C0-U3 — PSI no-regret design prep
- **rows** `C0-PSI-01` · **owner** design tokens · **kind** INFRA · **deps** none
- **parallel-safe**; must not begin route migration (that is `C8-U2`)

---

# 3. C1 — Identity, temporal substrate, retention (22 rows, 9 units)

The foundation everything else consumes. **No unit in this map is authorized today** —
C1-U1 and C1-U2 both closed on 2026-08-16; the next authorization is an owner decision.

### C1-U1 — Irreversible-evidence retention  ← **CLOSED (C1A unit 1)**
- **rows** `C1-RET-01` … `C1-RET-08`
- **owner** `src/retention/` (`evidence_store.py`, `league_events.py`, `health.py`)
- **kind** INFRA · **deps** none
- **RED→GREEN** each stream demonstrably losing evidence before the fix
- **CI gate** `tests/retention/` + `tests/deploy/`; watchdog exit-code semantics
- **prod gate** daily watchdog with scheduled `REQUIRE=ALL`; real backup **and
  isolated restore** proof; per-row acceptance evidence
- **consumers** none by design — **zero decision paths read retention** and that is
  a deliberate invariant, not an oversight
- **state** per-row disposition is recorded in PR #851, not here; RET-07 is
  STALE-by-design and RET-08 BLOCKED pending production observation

### C1-U2 — One player-identity owner  ← **CLOSED (C1A unit 2)**
- **rows** `C1-ID-01` · **owner** `src/identity/unified_mapper.py`
- **retires** 3 independent matchers · **kind** INFRA · **deps** C1-U1 (schema
  stability only)
- **RED→GREEN** two matchers disagreeing on a real player on the live board
- **prod gate** dual-read adapter shows zero divergence over a full refresh cycle
- **migration** dual-read → compare → cut over → retire. Never a flag-day swap.
- **state** CLOSED 2026-08-16. Cut over and retired: the canonical owner decides at
  both sites, legacy ladders deleted, no flag or fallback. Prod gate passed with zero
  divergence (scraper 2,016/2,016 over a full cycle; contract 24,024/24,024); board
  inert (0 of 1,092 rows moved). `CANONICAL_V2` measured but NOT served — it would
  regress the first-name-variant class; that repair needs its own unit. Record:
  `docs/identity/C1_ID_01_IDENTITY_CONSOLIDATION.md` §5a, §9

### C1-U3 — One pick identity, end to end  ← **CLOSED at the owner checkpoint 2026-08-16** (PR #867 merge `22ce424f`; bookkeeping PR #868)
- **rows** `C1-ID-02` · **owner** `src/identity/picks.py` (created)
- **retires/adapts** measured **39** independent definition sites, 97 raw census records
  (map's 7 was an estimate; `docs/identity/C1_ID_02_CENSUS.md`) · **kind** INFRA · **deps** C1-U2
- **RED→GREEN** the same pick failing to round-trip across two representations —
  reproduced on real league data (`tests/identity/test_pick_identity_red.py`, six
  defect classes) and closed by the owner (`test_pick_identity.py`)
- **note** `DO NOT PARALLELIZE` with C1-U6/U7 per EXECUTION_PLAN §4
- **state** DELIVERED 2026-08-16. League-pick identity = league+season+round+origin
  (owner/slot are state); market refs at slot/tier/generic grades; generic→exact is a
  pure state change; consumers adapted with byte-parity (board inert 0/1093, 144 picks
  intact). Deferred with record: intel-ledger re-key (C1-U8), frontend lookup
  migration (needs C1-U6), public-league fold. Record:
  `docs/identity/C1_ID_02_PICK_IDENTITY.md`

### C1-U4 — One immutable as-of value/provenance ledger  ← **DELIVERED 2026-08-16 (C1A unit 4, checkpoint pending)**
- **rows** `C1-HIST-01` `C1-HIST-02` `C1-HIST-03`
- **owner** `src/history/` (created) · **retires** the fragmented as-of semantics of
  **5** measured decision paths (map's 4 was an estimate; the fifth is the frontend
  aging helper, deferred to C3-U9 by this map's own decomposition) — raw stores
  remain as recording evidence feeds per the retention rows
- **kind** INFRA · **deps** C1-U2, C1-U3
- **RED→GREEN** both map REDs reproduced on real production data and closed
  (`tests/history/test_temporal_red.py` — 5 defect classes — →
  `test_temporal_ledger.py`): rankChange self-reference (740-row back-to-back
  divergence) → ledger-derived, read-only, deterministic; slot-pick values (72
  live rows) unrecoverable → first-class rank-less observations
- **backfill** from `exports/archive/` done: 34/34 dates from 2026-07-14, 138,127
  observations, deterministic + idempotent — **the pre-2026-07-14 gap is permanent,
  enforced at write AND query (`before_history_boundary`), never interpolated**
- **consumers** C3-U9 replay/aging, C5 backtesting, C9 history — substrate
  interfaces documented in `docs/history/C1_U4_TEMPORAL_LEDGER.md` §14
- **state** DELIVERED 2026-08-16. Awaiting its §3 owner checkpoint.

### C1-U5 — Confidence naming migration
- **rows** `C1-CONF-01` · **owner** `src/api/confidence.py` · **kind** INFRA
- **deps** none · **explicitly NOT a methodology change** — the five-axis
  bottleneck is preserved verbatim per calibration policy §7
- **scope** `confidenceBucket:"none"` on 24 priced rows; `identityConfidence` and
  `marketConfidence` renamed to what they mean

### C1-U6 — Pick completeness through 2029
- **rows** `C1-PICK-01` `C1-PICK-02` · **owner** `data_contract` pick pipeline
- **kind** INFRA · **deps** C1-U3
- **calibration** future-year discount is a **PRIOR** — challenger-test discount
  families against real market evidence; **never `0` for an unknown future pick**
- **RED→GREEN** a valid 2029 pick with no finite canonical value

### C1-U7 — Owned-pick outcome distributions
- **rows** `C1-PICK-03` · **owner** same · **kind** INFRA · **deps** C1-U6, C2-U4
- **required end state** distribution over slots, not only a point estimate;
  expected value + credible range + uncertainty + current owner + the ordering rule
- **guard** a manager's outlook may not improve from roster decay on a pick they no
  longer own

### C1-U8 — Acquisition history / cost basis / pick lineage
- **rows** `C1-ACQ-01` `C1-ACQ-02` `C1-ACQ-03` · **owner** transaction ledger
- **kind** INFRA · **deps** C1-U3, C1-U4 · **feeds** CE-18 trade trees
- **privacy** PRIVATE class — own-league transactions, same posture as `C1-RET-06`

### C1-U9 — Multi-format dynasty source archive
- **rows** `C1-SRC-01` `C1-SRC-02` · **owner** `_RANKING_SOURCES` + ingest
- **kind** INFRA · **deps** C1-U4
- **hard rule** archiving alternate boards does **not** authorize using them to
  alter production values; KTC Off/TE+/TE++/TE+++ remain **one** provider family

---

# 4. C2 — Roster math (12 rows, 10 units)

Calibration policy §4 governs this phase. Canonical dynasty value is **not**
recomputed anywhere here — this is roster-impact math.

### C2-U1 — One lineup / slot assignment
- **rows** `C2-LINE-01` · **owner** `src/ros/lineup.py::solve_optimal_assignment`
- **retires** 6 competing greedy fills (2 in production) · **kind** INFRA
- **deps** C1-U2 · **the root of the whole phase** — everything below consumes it
- **RED→GREEN** a roster where a greedy fill and the exact solver disagree

### C2-U2 — One replacement level / PAR owner
- **rows** `C2-REPL-01` · **owner** *(to consolidate)* · **retires** 5 implementations
- **kind** INFRA · **deps** C2-U1
- **calibration** empirical, from the actual league environment — league size,
  starters, flex/SF eligibility, depth, pool, realistic FA availability, IDP
  structure. Different defensible definitions must be **named as different views**,
  never the same label over different formulas.

### C2-U3 — Exact roster simulation
- **rows** `C2-SIM-01` · **owner** *(to create)* on C2-U1 · **kind** INFRA
- **deps** C2-U1, C2-U2
- **contract** `before → apply → enforce legal capacity → optimal cleanup →
  re-solve → after`. **Never** approximate forced-drop cost as package delta minus
  the lowest raw-value player.

### C2-U4 — Canonical Team Strength
- **rows** `C2-STR-01` · **owner** `src/ros/team_strength.py` · **retires** 4 notions
- **kind** INFRA · **deps** C2-U1, C2-U2, C2-U3
- **calibration** lineup- and replacement-aware; **diminishing marginal depth** is
  required, not optional — a WR6 may not count like a WR1

### C2-U5 — Canonical Team Weakness / Need Priority
- **rows** `C2-WEAK-01` · **retires** ≥5 need definitions · **deps** C2-U4
- **parallel-conditional** with C2-U4 *after* the shared roster interface freezes

### C2-U6 — Canonical Meaningful Roster Core
- **rows** `C2-CORE-01` · **deps** C2-U2
- **calibration** `ceil(1.5 × starter demand)` ships as the **V1 champion, labelled
  PRIOR**; challenger pass at 1.25× / 1.50× / 1.75× / data-derived cutoff before it
  is frozen. Do not tune until a few rosters "look right."

### C2-U7 — Roster age-value portfolio + Young Core Index
- **rows** `C2-AGE-01` `C2-AGE-02` `C2-AGE-03` · **deps** C2-U6 · **kind** PRODUCT
- **calibration** continuous **position-normalized** age curves, not universal
  buckets — a 26-year-old RB and QB are not the same youth signal. Picks excluded
  from age math; canonical value never age-adjusted twice.

### C2-U8 — Dropability consolidation
- **rows** `C2-DROP-01` · **owner** `src/draft/displacement.py` (HOLDS) · **deps** C2-U1

### C2-U9 — Value-weighted NFL-team exposure
- **rows** `C2-EXP-01` (CE-06) · **kind** PRODUCT · **deps** C2-U3

### C2-U10 — `roster_intel` / `/api/gameplan` disposition
- **rows** `C2-GP-01` · **kind** INFRA · **deps** C2-U4
- **outcome is binary**: reaches a user, or is retired. Not left DISCONNECTED.

---

# 5. C3 — Trade substrate (17 rows, 9 units)

`trade` is a **SERIAL lane — one writer only**.

### C3-U1 — ONE shared package generator
- **rows** `C3-PKG-01` · **owner** *(to create)* under `src/trade/`
- **retires** 4 independent generators · **kind** INFRA · **deps** C2-U3, C2-U4
- **the gate for all of C7** — no page-local generator may survive

### C3-U2 — ONE Value Adjustment, parity proven
- **rows** `C3-VA-01` `C3-VA-02` · **owner** `src/trade/ktc_va.py`
- **retires** 5 implementations incl. one installed by import-time monkeypatch
- **hard rule** KTC VA is an **exact external market lens**. Consolidate and prove
  parity; **do not "improve" it**. Parity proves agreement, not correctness.

### C3-U3 — ONE recommendation-constraint owner
- **rows** `C3-CON-01` `C3-CON-02` `C3-CON-03` · **deps** C3-U1
- **scope** user+league constraint service; persistent personal protection;
  generated-package LOCK/EXCLUDE

### C3-U4 — Roster capacity / forced-drop contract
- **rows** `C3-CAP-01` (#843) · **deps** C2-U3, C3-U1

### C3-U5 — Trade Calculator maturity
- **rows** `C3-CALC-01` `C3-CALC-02` `C3-CALC-03` · **kind** PRODUCT · **deps** C3-U1, C3-U2
- **calibration** internal fairness language must be **scale-aware** — a 500-point
  gap at the elite tier is not a 500-point gap deep on the board. Relative gap,
  package size, tier/curve slope, uncertainty, topology. Symmetry preserved.

### C3-U6 — Whole-package market coverage + equalizers
- **rows** `C3-XMKT-01` `C3-EQ-01` · **owner** `src/league_intel/cross_market.py`
  (correct today, **DISCONNECTED — zero production importers**) · **deps** C3-U2

### C3-U7 — Monte Carlo revalidation
- **rows** `C3-MC-01` · **deps** C1-U4, C3-U1
- **calibration** ±15% synthetic bands are a **PRIOR**. Estimate uncertainty from
  retained history; stratify by position/tier/age/horizon/status/coverage; measure
  or bound correlation. **Label the output a scenario win rate, not a probability**,
  until validation supports the literal reading.

### C3-U8 — Trade context toggle + topology
- **rows** `C3-CTX-01` `C3-TOPO-01` · **kind** PRODUCT · **deps** C2-U4, C3-U1
- **Use Team Context** is ONE shared toggle, ON by default (#842)

### C3-U9 — Historical trade replay / "How It Aged"
- **rows** `C3-REPLAY-01` `C3-AGE-01` · **deps** C1-U4 (hard)
- **three distinct questions**, per `docs/TRADE_HISTORY_AGING_SPEC.md`: Current
  Grade · At-the-Time Grade (nearest valid snapshot **at or before**, never a future
  one) · How It Aged (**same methodology on both timestamps**). A missing historical
  value is not today's value. The ±200 threshold is evidence-gated, not finished.

---

# 6. C4 — Market, sharp, FAAB (14 rows, 6 units)

### C4-U1 — Source health repairs
- **rows** `C4-SRC-01` `C4-SRC-02` `C4-SRC-03` · **kind** INFRA · **deps** none
- **always-open lane** — DraftSharks staleness is operations, not C scope, but
  needs owner disposition (`OD-04`)

### C4-U2 — Sharp cohort proven in production
- **rows** `C4-SHARP-01` `C4-SHARP-02` `C4-SHARP-03` · **owner** `src/sharp/cohort.py`
- **prod gate** the three staggered crawl passes measurably populate; FFPC lane is
  real **or honestly empty** — not silently zero

### C4-U3 — Market Trade Ledger
- **rows** `C4-MTL-01` `C4-MTL-02` `C4-MTL-03` `C4-KTC-01` (CE-01)
- **deps** C1-U2, C1-U3 (identity must settle before external trades are joined)
- **external** F-U2 permission record must resolve first

### C4-U4 — FAAB market heat
- **rows** `C4-FAAB-01` `C4-FAAB-02` (CE-19) · **owner** `src/trade/faab_engine.py`
- **hard rule** crowd evidence prices the **market**, never the player — it may not
  reach the objective ceiling, which is computed before any crowd data is read

### C4-U5 — Waiver ledger · **rows** `C4-WAIV-01` · **deps** C1-U8
### C4-U6 — Insider trading / cross-league consolidation · **rows** `C4-INS-01`

---

# 7. C5 — Seasonal intelligence (9 rows, 8 units)

Governed by `docs/PROJECTION_ENSEMBLE_PLAN_2026-08-15.md`. **Seasonal evidence must
never directly modify canonical dynasty `rankDerivedValue`.**

### C5-U1 — Multi-source projection ensemble  *(the largest single unit; six sub-units)*
- **rows** `C5-ROS-01` · **owner** *(to create)* projection service · **deps** C1-U4
- **sub-units, executed in order:**
  | id | scope |
  |---|---|
  | `C5-PROJ-A` | source capability / access / lineage census — CBS, NFL Fantasy, FantasyPros, DraftSharks, Mike Clay/ESPN (offense); **The IDP Show**, FantasyPros, DraftSharks (IDP); plus DFS and sportsbook discovery lanes. Record the authorized acquisition path *before* automation. Flag any source that is rankings-only rather than a true projection model. |
  | `C5-PROJ-B` | canonical projection-stat schema + **exact-league rescoring** — ingest raw projected stat lines, keep the native total as a diagnostic only, rescore through the canonical scoring engine. Missing categories stay missing. |
  | `C5-PROJ-C` | weekly offense + IDP ensemble |
  | `C5-PROJ-D` | ROS / full-season ensemble — horizon-matched; no weekly/ROS semantic mixing |
  | `C5-PROJ-E` | immutable archive + **leakage-safe** backtesting |
  | `C5-PROJ-F` | consumer migration + production proof |
- **three distinct evidence classes**, never pooled as equal votes:
  `PROJECTION_MODEL` · `DFS_PROJECTION` · `BETTING_MARKET`
- **independence** FantasyPros consensus and its constituent experts are not
  independent votes; several sportsbooks quoting one efficient market are one
  correlated observation, not several models
- **player props** preserve line **and** both prices; de-vig; a balanced O/U is a
  **median-like threshold**, not an expected value; binary props → probabilities;
  props → fantasy points requires an explicit distribution/joint-stat model
- **⚠ SCHEDULING NOTE** projection snapshots are **perishable**. `C5-PROJ-E`'s
  archival capture should be scheduled as early as is safe once authorized, even
  though its consumers are far downstream — the pre-event forecast cannot be
  reconstructed after the fact. This is the same class of loss as `C1-RET-*`.

### C5-U2 — Game Day Command Center
- **rows** `C5-GD-01` `C5-GD-02` (CE-20) · **kind** PRODUCT · **deps** C5-U1 (C, E)
### C5-U3 — One playoff-probability engine · **rows** `C5-PLAY-01` · **deps** C5-U1(D), C2-U4
### C5-U4 — One weekly power-rankings engine · **rows** `C5-POW-01` · **deps** C2-U4, C5-U1(C)
### C5-U5 — Player Impact / WAR / VORP / WAB · **rows** `C5-WAR-01` · **deps** C2-U2
### C5-U6 — Player special-teams scoring · **rows** `C5-ST-01` · **deps** none
### C5-U7 — BDVM fundamentals · **rows** `C5-BDVM-01` — COMPLETE-ALREADY; stays a
  **separate fundamental-value concept**, compared with the market board, never merged into it
### C5-U8 — League-specific player fit / college translation · **rows** `C5-FIT-01`

---

# 8. C6 — Analyst & signal intelligence (10 rows, 6 units)

### C6-U1 — ONE Central Buy/Sell reconciler
- **rows** `C6-SIG-01` `C6-SIG-02` · **retires** ≥6 emitters with no reconciler;
  one dead module currently *claims* ownership · **deps** C1-U2
### C6-U2 — Analyst claim/evidence ledger + freshness/decay
- **rows** `C6-ANA-01` `C6-FRESH-01` · **deps** C1-U4 · **external** credentials absent today
### C6-U3 — Podcast / YouTube / X ingestion
- **rows** `C6-POD-01` `C6-YT-01` `C6-X-01` · **deps** C6-U2 (one ledger, three feeds)
### C6-U4 — Manager Scout · **rows** `C6-MGR-01` (CE-03) · **deps** C1-U8
### C6-U5 — Consensus Edge repair · **rows** `C6-EDGE-01` · **deps** C1-U5
### C6-U6 — Universal Player Profile expansion · **rows** `C6-UPP-01` · **kind** PRODUCT
  · **deps** C5-U1, C6-U1 — the widest consumer in the map; sequence it late

---

# 9. C7 — Decision products (18 rows, 11 units)

**Every unit here is a consumer.** None may reimplement a C2/C3 formula. The
calibration policy's dependency principle binds this entire phase.

### C7-U1 — Analyze Trade + Trade Desk · **rows** `C7-DESK-01` (CE-05) · **deps** C3-U1, C3-U3, C3-U5
### C7-U2 — Best Trade to Send Each Team / Golden Upgrades · **rows** `C7-BEST-TRADE` `C7-GOLD-01` · **deps** C3-U1, C3-U3, C3-U6, C7-U4, C2-U4
  — topology superseded 2026-08-14 (#841/#842): the `no draft picks` and exact-equal-player-count
  rules are **WITHDRAWN**. Picks are valid when posture makes them mutually beneficial, never as
  filler; player counts may differ by at most one and picks do not count as players. A source that
  cannot natively evaluate a pick-inclusive package is marked **incomplete, never approval**
  — **do not tune around a temporary Team Strength formula**
### C7-U3 — Package Builder · **rows** `C7-PKGB-01` · **deps** C3-U1, C3-U3
### C7-U4 — Competitive Posture + posture-aware pick generation · **rows** `C7-POST-01` `C7-PICKGEN-01` (#840, #841) · **deps** C2-U4, C5-U3
### C7-U5 — Perfect Waivers · **rows** `C7-WAIV-01` · **deps** C4-U4, C4-U5, C2-U3
### C7-U6 — Draft tools · **rows** `C7-DRAFT-01` `C7-DRAFT-02` · **deps** C2-U2
  — `C7-DRAFT-02` pre-auction immutable snapshot is **perishable evidence**; schedule with C5-PROJ-E discipline
### C7-U7 — Dynasty Command Center + Age/Window on team profiles · **rows** `C7-CMD-01` `C7-AGE-01` · **deps** C2-U7
### C7-U8 — Remaining CE consumer surfaces · **rows** `C7-CE-01` (names 16 CE surfaces inline) · **deps** phase-wide
### C7-U9 — Ask Brisket / AI Front Office · **rows** `C7-AI-01` … `C7-AI-05` · **deps** substantially all of C2/C3/C5
  — Ask Brisket, Roster Path Optimizer, Trade Liquidity & Market Depth, Negotiation Coach, League Truth
### C7-U10 — Edge Alerts · **rows** `C7-ALERT-01` · **deps** C6-U1
### C7-U11 — Sleeper Action Gateway · **rows** `C7-GATE-01` (CE-11) · **deps** C3-U3
  — **recommendation ≠ execution.** Mutations require auth, explicit league/team,
  preview or confirmation, idempotency, and an audit trail.

---

# 10. C8 / C9 / C10 (26 rows, 12 units)

### C8-U1 — Performance · **rows** `C8-PERF-01` … `C8-PERF-05` · **deps** C0-U2 · **parallel-safe**
### C8-U2 — Premium design system + route migration · **rows** `C8-PSI-01` `C8-PSI-02` `C8-PSI-03` · **deps** C0-U3
  — route migration is **parallel-conditional**: only after each route's data contract stabilizes
### C8-U3 — Accessibility instrumentation · **rows** `C8-A11Y-01` · **deps** C8-U2 · **lane** `psi`
  — a structural ratchet exists today but no axe-core. **CI gate:** automated a11y checks per route,
  axe in CI — accessibility that is not measured in CI regresses silently

### C9-U1 — Public history correctness · **rows** `C9-HIST-01` `C9-HIST-02`
### C9-U2 — Awards · **rows** `C9-AWARD-01` `C9-AWARD-02` — awards may not exist before games are played
### C9-U3 — Canonical Share Renderer · **rows** `C9-SHARE-01` (CE-10)
### C9-U4 — Reports · **rows** `C9-UR-01` `C9-UR-02` `C9-WRS-01` · **deps** C5-U1
### C9-U5 — Season Recap / Wrapped · **rows** `C9-RECAP-01` (CE-21) · **deps** C9-U1
### C9-U6 — League Truth public view · **rows** `C9-TRUTH-01` · **deps** F-U1 (privacy boundary)
### C9-U7 — Public League Experience v3 · **rows** `C9-V3-01` · **deps** C9-U1, C8-U2
  — 29 modules live on the old UX; six hubs, Franchise Passport, storytelling. The widest single
  migration in C9, so it follows the design system rather than racing it

**All of C9 is gated by the public/private semantic boundary**: factual and
retrospective content is public; proprietary values, edges, targets, weaknesses,
forecasts and manager tendencies are private.

### C10-U1 — Zero-loss re-audit against the manifest · **rows** `C10-CLOSE-01`
### C10-U2 — Duplicate owners retired · **rows** `C10-CLOSE-02`
  — the closing proof of rule 1; every `retires` line above is checked here
### C10-U3 — Prior census + adaptive weighting stays off · **rows** `C10-ML-01`
  — every surviving numerical prior is **validated / deliberately retained with
  bounds / removed**. No consequential magic number survives on seniority.
### C10-U4 — Final gates · **rows** `C10-CLOSE-03` … `C10-CLOSE-07`
  — browser/workflow matrix · background jobs proven · performance gates ·
  security/privacy/auth · final regression

---

# 11. F — Standing invariants (14 rows, 2 units)

### F-U1 — Standing invariant guards (regression-only)
- **rows** `F-CONF-01` `F-FAAB-01` `F-MISS-01` `F-PRIV-01` `F-ROS-01` `F-SCORE-01`
  `F-SCORE-02` `F-SRC-01` `F-VAL-01` `F-VAL-02` `F-VAL-03`
- These **HOLD today**. They are not work; they are properties every later unit
  must not break, each already pinned by a test. Any unit that touches them
  inherits their regression suite as an additional CI gate.

### X-U1 — Explicitly out of scope (NO implementation unit)
- **rows** `X-01` … `X-07`
- **kind** neither INFRA nor PRODUCT — these are **dispositions**, recorded so they are not
  silently re-added by a later session that mistakes absence for an oversight.
- `X-01` Schedule generator — OWNER-REJECTED
- `X-02` Money / dues / Constitution / League Media — OWNER-REJECTED
- `X-03` Establish The Run paid source — **OWNER-PAUSED**; research preserved, do not purchase or
  implement until the owner resumes. Paused is not rejected, and it is not authorization either.
- `X-04` Canonical Data Mode offline build — SUPERSEDED; the live contract is the single source of truth
- `X-05` League-aware valuation overlay as canonical — OWNER-REJECTED on seven measured defects; may
  not own a canonical field
- `X-06` `src/api/opportunity_stats.py` usage-signal engine — SUPERSEDED by `src/consensus_edge/opportunity.py`
- `X-07` "Link any Sleeper account" general onboarding — NOT-PRODUCT-SCOPE today
- **the closing check** `C10-U1`'s zero-loss re-audit must confirm every one of these is still absent
  from the product, not quietly reintroduced under another name.

### F-U2 — External permission records (OWNER-DECISION)
- **rows** `F-EXT-01` (KTC) `F-EXT-02` (IDPTC) `F-EXT-03` (credentialed/paywall posture)
- **blocks** C4-U3 and parts of C5-U1. Subscription access is **not** automatic
  automation/redistribution rights — record the permitted technical path first.

---

# 12. Complete manifest-row → unit mapping

Every one of the 153 rows appears exactly once.

| unit | rows | n |
|---|---|---|
| C0-U1 | C0-GOV-01…09 | 9 |
| C0-U2 | C0-PERF-01 | 1 |
| C0-U3 | C0-PSI-01 | 1 |
| C1-U1 | C1-RET-01…08 | 8 |
| C1-U2 | C1-ID-01 | 1 |
| C1-U3 | C1-ID-02 | 1 |
| C1-U4 | C1-HIST-01, -02, -03 | 3 |
| C1-U5 | C1-CONF-01 | 1 |
| C1-U6 | C1-PICK-01, -02 | 2 |
| C1-U7 | C1-PICK-03 | 1 |
| C1-U8 | C1-ACQ-01, -02, -03 | 3 |
| C1-U9 | C1-SRC-01, -02 | 2 |
| C2-U1…U10 | C2-LINE-01 · C2-REPL-01 · C2-SIM-01 · C2-STR-01 · C2-WEAK-01 · C2-CORE-01 · C2-AGE-01/-02/-03 · C2-DROP-01 · C2-EXP-01 · C2-GP-01 | 12 |
| C3-U1…U9 | C3-PKG-01 · C3-VA-01/-02 · C3-CON-01/-02/-03 · C3-CAP-01 · C3-CALC-01/-02/-03 · C3-XMKT-01/C3-EQ-01 · C3-MC-01 · C3-CTX-01/C3-TOPO-01 · C3-REPLAY-01/C3-AGE-01 | 17 |
| C4-U1…U6 | C4-SRC-01/-02/-03 · C4-SHARP-01/-02/-03 · C4-MTL-01/-02/-03/C4-KTC-01 · C4-FAAB-01/-02 · C4-WAIV-01 · C4-INS-01 | 14 |
| C5-U1…U8 | C5-ROS-01 · C5-GD-01/-02 · C5-PLAY-01 · C5-POW-01 · C5-WAR-01 · C5-ST-01 · C5-BDVM-01 · C5-FIT-01 | 9 |
| C6-U1…U6 | C6-SIG-01/-02 · C6-ANA-01/C6-FRESH-01 · C6-POD-01/C6-YT-01/C6-X-01 · C6-MGR-01 · C6-EDGE-01 · C6-UPP-01 | 10 |
| C7-U1…U11 | C7-DESK-01 · C7-GOLD-01 · C7-PKGB-01 · C7-POST-01/C7-PICKGEN-01 · C7-WAIV-01 · C7-DRAFT-01/-02 · C7-CMD-01/C7-AGE-01 · C7-CE-01 · C7-AI-01…05 · C7-ALERT-01 · C7-GATE-01 | 18 |
| C8-U1, C8-U2 | C8-PERF-01…05 · C8-PSI-01/-02/-03 | 8 |
| C9-U1…U6 | C9-HIST-01/-02 · C9-AWARD-01/-02 · C9-SHARE-01 · C9-UR-01/-02/C9-WRS-01 · C9-RECAP-01 · C9-TRUTH-01 | 10 |
| C10-U1…U4 | C10-CLOSE-01 · -02 · C10-ML-01 · C10-CLOSE-03…07 | 8 |
| F-U1, F-U2 | 11 invariant rows + 3 permission rows | 14 |
| | **total** | **153** |

---

# 13. Duplicate implementations to retire

The consolidation ledger. `C10-U2` closes only when every line is zero.

| concept | today | retires in |
|---|---|---|
| Player identity | 3 independent matchers | C1-U2 |
| Pick identity | 7 representations, no end-to-end id | C1-U3 |
| Historical value | 4 fragmented stores, 1 with no history | C1-U4 |
| Lineup / slot assignment | 6 competing greedy fills (2 in prod) | C2-U1 |
| Replacement level / PAR | 5 implementations | C2-U2 |
| Team Strength | 4 competing notions | C2-U4 |
| Team Weakness / need | ≥5 definitions | C2-U5 |
| Package generation | 4 independent generators | C3-U1 |
| Value Adjustment | 5, one via import-time monkeypatch | C3-U2 |
| Central Buy/Sell | ≥6 emitters, no reconciler | C6-U1 |

---

# 14. Safe parallelism

**Parallel-safe (any time):** C0-U2 · C0-U3 · C1-U1 · C4-U1 · C8-U1 · C5-U6

**Parallel after their interface freezes:** C1-U5 ∥ C1-U6 · C2-U4 ∥ C2-U5 · the
three C6-U3 feeds ∥ each other · per-ledger C4 collectors

**SERIAL — one writer only:** `gov` (C0-U1) · `trade` (all of C3) · anything in
`data_contract.py`'s pipeline core · the CE registry

**DO NOT PARALLELIZE:**
- two agents on CE numbering or backlog reconciliation — this exact collision has
  already occurred
- anything creating a second package / lineup / replacement / value engine
- C1-U6 pick valuation together with C1-U8 pick-history backfill while C1-U3 pick
  identity is unsettled
- `CLAUDE.md` edits from two branches
- schema migrations on the intel ledger from two workstreams

---

# 15. Migrations and backfills

| unit | migration | irreversible-loss risk |
|---|---|---|
| C1-U2 | dual-read player identity → compare → cut over | none |
| C1-U4 | board history → immutable ledger | **pre-2026-07-14 is unrecoverable — record as missing** |
| C1-U6 | pick value backfill | historical pick values must be first-class, never today's value |
| C5-U1(E) | projection archive | **perishable — the pre-event forecast cannot be rebuilt** |
| C7-DRAFT-02 | pre-auction snapshot | **perishable — capture before the auction or never** |
| C8-U2 | route-by-route design migration | none, but reversible per route |

---

# 16. When each product becomes usable

| milestone | requires | what the user can finally do |
|---|---|---|
| **M1 — evidence is safe** | C1-U1 | nothing new is visible; nothing more is lost |
| **M2 — assets have identity** | C1-U2, C1-U3, C1-U4 | history and provenance become answerable |
| **M3 — rosters are understood** | C2-U1…U6 | Team Strength / Weakness / Core are one number each, league-aware |
| **M4 — trades are real** | C3-U1…U5 | Trade Calculator, Analyze Trade, package generation on one engine |
| **M5 — the season is modelled** | C5-U1, C5-U3, C5-U4 | weekly/ROS projections, playoff odds, power rankings |
| **M6 — decisions are products** | C7-U1…U7 | Trade Desk, Golden Upgrades, Package Builder, Perfect Waivers, Command Center |
| **M7 — the league has a story** | C9 | recaps, awards, public reporting |
| **M8 — closure** | C10 | every duplicate retired, every prior censused |

---

# 17. Calibration classification schedule

Per `MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §2, every consequential tunable is
`MEASURED / VALIDATED`, `MECHANICALLY REQUIRED`, or `PRIOR / HEURISTIC`.

| tunable | class today | validated in |
|---|---|---|
| future-pick year discount | PRIOR | C1-U6 |
| `ceil(1.5 × starter demand)` core | PRIOR (approved V1 champion) | C2-U6 |
| Young Core age buckets | PRIOR | C2-U7 |
| trade fairness raw-point thresholds | PRIOR | C3-U5 |
| min-upgrade ratio / stretch tolerance | PRIOR | C3-U1 |
| Monte Carlo ±15% bands, correlation | PRIOR | C3-U7 |
| TE league-demand → basis mapping | PRIOR | C1-U9 / #785 |
| TE source-basis conversion (1.209→2.05) | MEASURED | holds |
| five-axis confidence bottleneck | MECHANICAL (blend rungs 5/3) | preserved, not reopened |
| equal family weighting | MEASURED champion | C10-U3 |
| aging ±200 threshold | PRIOR | C3-U9 |

A prior may ship in a bounded V1 only when labelled, sensitivity-measured, not
self-promoting, and carrying a named challenger task before C10.

---

# 18. Authorization boundary

**Authorized today:** **nothing.** `C1-U1` and `C1-U2` both closed on 2026-08-16, per
`docs/EXECUTION_PLAN.md` §0.

**Not authorized by this file or any other:** C1-U3 (`C1-ID-02`) · every other C1
unit · all of C2, C3, C4, C5, C6, C7, C8, C9, C10 · any projection-source
implementation · any product UI work · **`CANONICAL_V2` activation**, which C1-U2
measured and deliberately deferred.

Producing this map does not start any of it. The next authorization comes from the
owner reviewing completed C1-U2 evidence at the
`C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §3 checkpoint.

---

# 19. Out of scope — recorded so it is not rediscovered

**IDP Guru / idpguru.com is not part of the product plan.** It is not a rankings
source, not a projection source, not a future placeholder, and has no manifest row,
execution unit or backlog item. It was removed from `docs/ros-engine.md`'s future
source list on 2026-08-15 by owner direction. Do not reintroduce it.

**This does not affect, and must not be confused with:** **The IDP Show** (an
approved IDP projection source candidate — `C5-PROJ-A`), **FantasyPros IDP**, or
**DraftSharks IDP**. All three remain in scope exactly as planned.

---

# 20. Appendix — every manifest row, explicitly

Derived from `docs/C_SERIES_SCOPE_MANIFEST.md` §4, not hand-listed. All **163** ids appear exactly once; `scripts/check_planning_integrity.py` recomputes both sets and fails CI on any drift.

| row | unit |
|---|---|
| `C0-GOV-01` | C0-U1 |
| `C0-GOV-02` | C0-U1 |
| `C0-GOV-03` | C0-U1 |
| `C0-GOV-04` | C0-U1 |
| `C0-GOV-05` | C0-U1 |
| `C0-GOV-06` | C0-U1 |
| `C0-GOV-07` | C0-U1 |
| `C0-GOV-08` | C0-U1 |
| `C0-GOV-09` | C0-U1 |
| `C0-PERF-01` | C0-U2 |
| `C0-PSI-01` | C0-U3 |
| `C1-RET-01` | C1-U1 |
| `C1-RET-02` | C1-U1 |
| `C1-RET-03` | C1-U1 |
| `C1-RET-04` | C1-U1 |
| `C1-RET-05` | C1-U1 |
| `C1-RET-06` | C1-U1 |
| `C1-RET-07` | C1-U1 |
| `C1-RET-08` | C1-U1 |
| `C1-ID-01` | C1-U2 |
| `C1-ID-02` | C1-U3 |
| `C1-PICK-01` | C1-U6 |
| `C1-PICK-02` | C1-U6 |
| `C1-PICK-03` | C1-U7 |
| `C1-HIST-01` | C1-U4 |
| `C1-HIST-02` | C1-U4 |
| `C1-HIST-03` | C1-U4 |
| `C1-ACQ-01` | C1-U8 |
| `C1-ACQ-02` | C1-U8 |
| `C1-ACQ-03` | C1-U8 |
| `C1-CONF-01` | C1-U5 |
| `C1-SRC-01` | C1-U9 |
| `C1-SRC-02` | C1-U9 |
| `C2-LINE-01` | C2-U1 |
| `C2-REPL-01` | C2-U2 |
| `C2-STR-01` | C2-U4 |
| `C2-WEAK-01` | C2-U5 |
| `C2-CORE-01` | C2-U6 |
| `C2-SIM-01` | C2-U3 |
| `C2-DROP-01` | C2-U8 |
| `C2-GP-01` | C2-U10 |
| `C2-AGE-01` | C2-U7 |
| `C2-AGE-02` | C2-U7 |
| `C2-AGE-03` | C2-U7 |
| `C2-EXP-01` | C2-U9 |
| `C3-PKG-01` | C3-U1 |
| `C3-VA-01` | C3-U2 |
| `C3-VA-02` | C3-U2 |
| `C3-CON-01` | C3-U3 |
| `C3-CON-02` | C3-U3 |
| `C3-CON-03` | C3-U3 |
| `C3-XMKT-01` | C3-U6 |
| `C3-EQ-01` | C3-U6 |
| `C3-CTX-01` | C3-U8 |
| `C3-CAP-01` | C3-U4 |
| `C3-TOPO-01` | C3-U8 |
| `C3-CALC-01` | C3-U5 |
| `C3-CALC-02` | C3-U5 |
| `C3-CALC-03` | C3-U5 |
| `C3-MC-01` | C3-U7 |
| `C3-REPLAY-01` | C3-U9 |
| `C3-AGE-01` | C3-U9 |
| `C4-MTL-01` | C4-U3 |
| `C4-MTL-02` | C4-U3 |
| `C4-MTL-03` | C4-U3 |
| `C4-KTC-01` | C4-U3 |
| `C4-FAAB-01` | C4-U4 |
| `C4-FAAB-02` | C4-U4 |
| `C4-SHARP-01` | C4-U2 |
| `C4-SHARP-02` | C4-U2 |
| `C4-SHARP-03` | C4-U2 |
| `C4-INS-01` | C4-U6 |
| `C4-WAIV-01` | C4-U5 |
| `C4-SRC-01` | C4-U1 |
| `C4-SRC-02` | C4-U1 |
| `C4-SRC-03` | C4-U1 |
| `C5-POW-01` | C5-U4 |
| `C5-PLAY-01` | C5-U3 |
| `C5-GD-01` | C5-U2 |
| `C5-GD-02` | C5-U2 |
| `C5-WAR-01` | C5-U5 |
| `C5-ROS-01` | C5-U1 |
| `C5-BDVM-01` | C5-U7 |
| `C5-FIT-01` | C5-U8 |
| `C5-ST-01` | C5-U6 |
| `C6-ANA-01` | C6-U2 |
| `C6-POD-01` | C6-U3 |
| `C6-YT-01` | C6-U3 |
| `C6-X-01` | C6-U3 |
| `C6-FRESH-01` | C6-U2 |
| `C6-SIG-01` | C6-U1 |
| `C6-SIG-02` | C6-U1 |
| `C6-MGR-01` | C6-U4 |
| `C6-UPP-01` | C6-U6 |
| `C6-EDGE-01` | C6-U5 |
| `C7-BEST-TRADE` | C7-U2 |
| `C7-POST-01` | C7-U4 |
| `C7-PICKGEN-01` | C7-U4 |
| `C7-GOLD-01` | C7-U2 |
| `C7-PKGB-01` | C7-U3 |
| `C7-DESK-01` | C7-U1 |
| `C7-GATE-01` | C7-U11 |
| `C7-WAIV-01` | C7-U5 |
| `C7-DRAFT-01` | C7-U6 |
| `C7-DRAFT-02` | C7-U6 |
| `C7-ALERT-01` | C7-U10 |
| `C7-AI-01` | C7-U9 |
| `C7-AI-02` | C7-U9 |
| `C7-AI-03` | C7-U9 |
| `C7-AI-04` | C7-U9 |
| `C7-AI-05` | C7-U9 |
| `C7-AGE-01` | C7-U7 |
| `C7-CMD-01` | C7-U7 |
| `C7-CE-01` | C7-U8 |
| `C8-PSI-01` | C8-U2 |
| `C8-PSI-02` | C8-U2 |
| `C8-PSI-03` | C8-U2 |
| `C8-PERF-01` | C8-U1 |
| `C8-PERF-02` | C8-U1 |
| `C8-PERF-03` | C8-U1 |
| `C8-PERF-04` | C8-U1 |
| `C8-PERF-05` | C8-U1 |
| `C8-A11Y-01` | C8-U3 |
| `C9-AWARD-01` | C9-U2 |
| `C9-AWARD-02` | C9-U2 |
| `C9-HIST-01` | C9-U1 |
| `C9-HIST-02` | C9-U1 |
| `C9-SHARE-01` | C9-U3 |
| `C9-WRS-01` | C9-U4 |
| `C9-UR-01` | C9-U4 |
| `C9-UR-02` | C9-U4 |
| `C9-V3-01` | C9-U7 |
| `C9-RECAP-01` | C9-U5 |
| `C9-TRUTH-01` | C9-U6 |
| `C10-CLOSE-01` | C10-U1 |
| `C10-CLOSE-02` | C10-U2 |
| `C10-CLOSE-03` | C10-U4 |
| `C10-CLOSE-04` | C10-U4 |
| `C10-CLOSE-05` | C10-U4 |
| `C10-CLOSE-06` | C10-U4 |
| `C10-CLOSE-07` | C10-U4 |
| `C10-ML-01` | C10-U3 |
| `F-VAL-01` | F-U1 |
| `F-VAL-02` | F-U1 |
| `F-VAL-03` | F-U1 |
| `F-CONF-01` | F-U1 |
| `F-SRC-01` | F-U1 |
| `F-SCORE-01` | F-U1 |
| `F-SCORE-02` | F-U1 |
| `F-PRIV-01` | F-U1 |
| `F-MISS-01` | F-U1 |
| `F-FAAB-01` | F-U1 |
| `F-ROS-01` | F-U1 |
| `F-EXT-01` | F-U2 |
| `F-EXT-02` | F-U2 |
| `F-EXT-03` | F-U2 |
| `X-01` | X-U1 |
| `X-02` | X-U1 |
| `X-03` | X-U1 |
| `X-04` | X-U1 |
| `X-05` | X-U1 |
| `X-06` | X-U1 |
| `X-07` | X-U1 |
