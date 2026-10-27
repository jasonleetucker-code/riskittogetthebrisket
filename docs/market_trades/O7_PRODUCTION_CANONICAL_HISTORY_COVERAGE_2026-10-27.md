# O7: production canonical-history coverage for own-league trades (2026-10-27)

**Status: COMPLETE (one run, read-only, aggregates only).** Research evidence for the IDP market directive
(IDPM-4, preregistration decision O7). It changes no value, flag, route or production file.

## Authorization and scope

- **Owner decision (2026-10-27):** "One strictly read-only, scoped production-server extraction of historical
  canonical values, with aggregates only leaving the server, no writes or configuration changes."
- **Measured:** how much point-in-time canonical evidence production holds for the 233 completed own-league trades in
  the census (`OWN_LEAGUE_HISTORY_CENSUS_2026-10-27.md`).
- **Not computed:** no residual, gap, premium, hypothesis statistic or value comparison. The preregistration is still a
  draft. A value was used only as "present and positive".

## What ran

| item | value |
|---|---|
| Deployed code | `44695ab61270fc6124c62190f895ec8171b0e239` (`git rev-parse HEAD` in the app directory at run time) |
| Authoritative store | the production temporal ledger (`data/temporal_ledger.sqlite` under the app root; schema v1, WAL journal, 2.28 GB), lane `canonical_board`; `board_history.sqlite` read only for its date span (the ledger migrates it, origin `migration:board_history`) |
| Query semantics | `src.history.asof.batch_known_before`, unchanged; only its connection opener was replaced (below) |
| Run | 2026-10-27 08:55:48Z → 08:57:44Z, one SSH session, `nice -n 19 ionice -c3 timeout 900 python3 -I -B -`, script on stdin (sha256 `394996c6…1fe80f`) |
| Inputs sent | per trade: season, completion instant, census classes and fit; per asset: kind, family, public Sleeper player key. No transaction, roster, manager, league or draft ids; trade order shuffled |
| Output | one aggregate JSON on stdout: `evidence/o7_production_canonical_coverage_2026-10-27.json` |
| Code | `scripts/research_o7/` (the committed copy is the run script after Ruff formatting, with the input placeholder quoted) |
| Reviews | independent pre-run review: APPROVE_WITH_FIXES (temp-file spill, deadlines, same-snapshot rule, value > 0); every fix applied; delta review: APPROVE_TO_RUN |

### Read-only guarantees, and how they were checked

| guarantee | mechanism | observed |
|---|---|---|
| no SQLite side files | `mode=ro&immutable=1`, `PRAGMA query_only`, `temp_store=MEMORY` (plain `mode=ro` on a WAL file with no `-shm` would create one) | no `-wal`, `-shm` or `-journal` before or after |
| ledger unread-while-written | size + mtime + side files compared pre/post; run placed between timer writes | unchanged (`ledgerChangedDuringRead: false`) |
| no bytecode or file writes | `-I -B`, `sys.dont_write_bytecode`; post-run `find -newermt <start>` outside `data/`, `exports/`, `logs/`, plus all `*.pyc` | 0 files, 0 `.pyc`; process block writes 0 |
| bounded load | 300 s pricing / 750 s total deadline via a progress handler | 115 s total (39 s pricing); 57 MB peak RSS; 1-min load 0.38 → 1.03 |
| aggregates only | small cells (1–4) published as `<5`; no ids, names, values or per-trade rows; output scanned for history keys and 9+ digit runs | clean (the only long digit runs are file sizes, mtimes and load averages) |

## Results

### 1. What production holds

- **Canonical lane:** 1,249,742 observations of 1,924 distinct assets on 100 board days, 2026-07-20 → 2026-10-27.
  - Live recording (`live:server`) starts **2026-08-16**: 1,095,952 rows over 72 days.
  - The earlier days come from migrations recorded on or after 2026-08-16: `migration:board_history` (79,032 rows,
    from 2026-08-06) and `migration:rank_history` (74,758 rows, from 2026-07-20, no instant).
- **No observation precedes the history floor** (2026-07-14). The corrections table is empty.
- **Per board day** (all recordings that day), the median count is 7,815 offense, 6,139 IDP and 1,332 pick rows.
  The daily IDP board needed by H6d's untraded comparison set exists.
- **Observation instants:** 53,794 canonical rows carry a naive `observed_at` (the known legacy two-hour issue), and
  74,758 carry none.
- **Source lanes for comparison:** `idpTradeCalc` 1.34 M rows over 106 days from 2026-07-14. `ktcSfTep` runs
  2026-07-14 → 2026-10-27; `ktcCrowdSfTep` and `ktcTradesSfTep` start 2026-09-24.

### 2. Trades (census population: 233; 80 in 2026, 43 of them on or after the floor)

Primary rule = preregistration §2.4: knowledge cutoff = the trade instant ("strict"), so a row recorded after the
trade is invisible. The census's valid-time reading is shown for comparison.

| 2026 trades | strict | strict, age ≤ 7 d | valid-time |
|---|---:|---:|---:|
| fully priced, canonical | **11** | 11 | 17 |
| fully priced, IDP Trade Calculator | 11 | 11 | 17 |
| fully priced, canonical **and** IDPTC | — | 11 (10 on one snapshot date per lane) | — |
| fully priced canonical but **not** IDPTC (newly evaluable) | **0** | — | — |
| containing IDP | <5 of 19 | <5 | <5 |
| offense-for-IDP | <5 of 7 | <5 | <5 |
| IDP-for-IDP | 0 of <5 | 0 | 0 |
| IDP one-for-one, players only | 0 of 0 | 0 | 0 |

- **2024 and 2025: 0 trades priced** in any lane under either rule (all before the floor).
- **No previously unpriced trade becomes evaluable.** Every canonical-priced trade was already IDPTC-priced. What O7
  adds is the canonical lane for those same trades.
- **Strict loses 6 trades against valid-time.** Their only observations were recorded by the 2026-08-16 migrations,
  after the trade. Under §2.4 they are invisible.
- **At least one asset canonical-priced (strict):** 29 trades of 80.

### 3. Assets in 2026 trades (strict, canonical lane)

| | count |
|---|---:|
| priced | 109 (108 exact, <5 nearest-prior) |
| missing: before history boundary | 174 |
| missing: no prior observation (mostly before live recording began on 2026-08-16) | 43 |
| missing: league pick, unpriced by construction (Sleeper records season + round only, see census) | 53 |
| IDP legs priced / total | 18 / 38 |
| offense legs priced / total | 91 / 244 |

- **Observation age:** median 0 days, p75 0 days. Every priced asset is within the 7-day gate.
- **Selected origins:** `live:server` 108, `migration:rank_history` <5.
- **Recording after the trade instant:** none under strict, 43 under valid-time.

### 4. Research readiness

| hypothesis | gate | O7 evidence | status |
|---|---|---|---|
| H2 (canonical vs IDPTC on accepted 1-for-1 trades) | 55 trades plus the canonical lane | canonical lane now **available**. 8 structurally eligible 2026 trades; 5 priced in both lanes at age ≤ 7 d; <5 on one snapshot date. Format bracket not evaluated (the capture store is present on the box) | **H7: insufficient sample** (5 of 55); no longer `no_canonical_lane` |
| H6d (player selection) | an established discrepancy (T3 or T2) plus the canonical lane | lane available: 18 of 38 IDP legs priced; the daily canonical IDP board exists | **unavailable: discrepancy_undetermined** (H2 and H3 are H7) |
| H7 (global) | — | — | **supported** |

**What remains unavailable, and why.**
- Every trade before 2026-07-14 is outside retained history; nothing earlier survives on production either.
- Trades between the floor and 2026-08-16 have canonical rows only from migrations recorded later. Under the strict
  rule they are invisible; only valid-time can see them.
- League picks have no slot, so they cannot be priced. That waits on pick-rule decision O4.
- H1a's decoy gate, H3–H5 and per-manager floors are untouched by O7. They remain H7 per the preregistration §8.

## Uncertainties

- **Immutable reads skip uncommitted WAL frames.** None existed at the run; the pre/post comparison would have flagged
  a concurrent write.
- **The rendered script differs from the committed copy only by formatting.** The committed copy also adds the
  rendering placeholder. The executed bytes are pinned by their sha256 above.
- **Complementary suppression is not applied.** A difference of two published cells can reveal a count of 1–4. That
  reveals only whether some anonymous trades were priced, never a value or a manager.
- **Counts reflect the census's identity resolution and classification** (2 unresolved player ids; as-of position
  basis).
