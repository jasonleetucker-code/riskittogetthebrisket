# Manager-lineage component census for the Chase Upside Trade Market holdout (2026-10-21)

**Status: census tool and local evidence DONE; the real census is PENDING an owner-authorized, read-only box run
(§7).**
- Q2 stays **`PROPOSED_PENDING_OWNER_Q2`**.
- No reserve has been drawn, persisted or exposed.
- No verbatim Q2 wording exists or is offered here.
- Nothing served, voted, weighted or flagged has changed.

Authority: owner decision Package 5A, 2026-10-21 (`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`, PR #1902):
- The owner's original intent for Q2 was to hold out entire leagues with chronological separation, to prevent
  leakage between training and evaluation.
- A permanent 20% manager-lineage reserve and the five-way allocation are **not approved**.
- First do the read-only census, then the owner chooses.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. Summary

1. **No real manager-lineage component size can be measured off the production box.** The stores it needs (the
   completed-trade ledger and the Sharp intel ledger) exist only there. The local intel ledger is an empty schema,
   and there is no local trade ledger. Real component sizes, concentration and coverage come from the pinned box
   command in §7.
2. **Real league-level numbers already exist** in the committed Phase 3 production report (2026-10-20):
   - 18,690 graded trades from **11,565 distinct leagues**;
   - the largest league holds **0.2%** of them and the top five **0.6%**.

   At the league level the population is highly unconcentrated, so a whole-league holdout has many small units to
   draw from.
3. **Three structural facts decide which policies are even possible** (§3):
   - The box ledger is built **without manager keys**. #1852's reserve, as written, cannot form components there.
   - **66% of ledger groups are KTC-database rows.** They name a league but no manager and no league chain, so
     their manager leakage is *unmeasurable, not zero*.
   - The Sharp lane is collected by **snowball discovery through shared managers**. That makes giant components
     likely.
4. **The trade-off, shown on labelled synthetic data (§5):**
   - **A lineage-component reserve** removes manager leakage by construction. Without a time split it leaks the
     future for every evaluation trade. Once a giant component exists, the realized holdout size swings wildly:
     for a 20% target, the 5th–95th percentile range was 73 to 4,397 trades.
   - **A whole-league holdout with a chronological split (the owner's intent)** has zero lineage and time
     leakage and a stable size. Its manager leakage is measurable: 6% at 2% per-seat overlap, 28% at 10%.
   - **No policy creates independent clusters that the data does not have.** With a giant component, every
     policy's effective number of evaluation clusters is about 2–4.
5. A provisional reading for the owner is in §6. **The owner chooses the policy.** This document recommends what
   to look at, not what to lock.

## 2. Definitions

A trade belongs to its season-league. Three nested component definitions show the effect of each kind of link:

| def | joins season-leagues through | meaning |
|---|---|---|
| **L** | `previous_league_id` (lineage), plus a record's `leagueMaturity.lineageId` once a maturity owner stamps one | "the same league across seasons": the owner's whole-league unit |
| **P** | L + every manager observed on a side of **any** ledger trade | the plan's manager-lineage component |
| **M** | P + every recorded member of any ledger league | a manager who knows a league without trading in it |

Links come from every ledger trade, not only the population being measured, so a component is what a
reserve built over all observed trades would see.

**Unknown linkage is not "no linkage."**
- A trade with no league is an unlinkable singleton.
- A trade is *partially observed* when fewer managers are seen than it has sides. For example, the Insider
  pool crawl records only pool members' movements.
- Every leakage share is computed over the evaluation trades it can check, and states the share it could not.
- `P_fullyObservedOnly` repeats the P concentration over completely observed trades only.

**Where participants come from.** The census joins the ledger's `hostTxId` to the intel ledger's
`asset_movements.user_id`. A Sleeper transaction id is globally unique, so the intel row also names the league
when a duplicate group's representative record came from KTC. `--participants side_keys` would use the ledger's
pseudonymous `sideEvidence.managerKey` instead, but on the box those are all null (§3.3). Raw ids stay in process
memory.

**Clock.** The chronological split uses `collectedAt`, the protocol's availability clock, by default.
`--clock occurred` is available. Coverage reports both clocks and the trades missing each.

Five populations are measured:
- `allProvenDedupe`: every ledger group except an unproven dedupe (`POSSIBLE_OVERLAP` / `UNRESOLVED`);
- `fitEligible`: groups that are not `unsuitable` under `market_trade_eval.fit_suitability`, which requires
  verified dynasty, a known QB format, two sides, no FAAB or unresolved assets, and so on;
- `fitEligibleSleeperObserved`: the subset in the Sleeper-observed lane, which the preregistration names for the
  first voting candidate;
- `estimatorEligible` / `estimatorEligibleSleeperObserved`: the estimator's own gate, an empty
  `estimator_evidence(...).hardExclusions`. It also drops undated and unknown-collection trades, multi-copy or
  unknown-exclusivity leagues, and trades with unattributed senders.

Policies are simulated on `fitEligibleSleeperObserved` and on both `estimatorEligible` populations.

Maturity (≥ 3 completed seasons) is **not** applied. Its owner is #1852, which is not merged. Cohorts can be
cross-tabulated once it lands.

Per definition and population, the census reports:
- component count;
- trades per component (mean, p50, p90, p99, max) and a size histogram;
- top-1/5/10/20/50 trade shares;
- HHI, the effective number of components (1/HHI) and the Gini coefficient;
- the largest component's share of trades, leagues and trading managers.

**Coverage** covers trades by lane and month (small cells print as `<5`), both clocks' date ranges, leagues,
lineages and trading managers.

**Linkage** covers:
- trades with no league;
- complete, partial and unobserved participants;
- the fully linkable share;
- population leagues present in the intel `leagues` table;
- leagues with a predecessor link, and links that point outside the table (a possible gap in the chain);
- leagues with a lineage stamp.

**Policy results are a distribution over 100 seeds**, given as mean, p5, p95, min and max, and never collapsed
to one number. Each one states `replicatesWithEval`: leakage and concentration are computed over replicates
whose holdout came out non-empty, while sizes include the empty ones.

Policy leakage metrics, computed on each evaluation set against its training set:
- `lineageLeak`: the evaluation trade's lineage also has training trades;
- `componentLeakP`: the same at P-component level;
- `participantLeak`: a manager of the evaluation trade is a manager on a training trade, among evaluation trades
  whose every side is observed. `participantLeakAnyObserved` also includes partly observed trades;
- `membershipLeak`: a participant or member of its league also trades in, or is a member of, a training league.
  Both kinds of key share one key space;
- `evalDatedBeforeTrainEnd`: temporal overlap;
- `participantPartialShare` / `participantUnobservedShare` / `leakageUnmeasurableShare`: evaluation trades for
  which the check is incomplete or impossible. These are never counted as zero.

## 3. What can be measured off the box (coverage labelled)

**3.1 Local stores: nothing real.**
- `data/intel/ledger.sqlite3` in the dev checkout has 0 rows in every table. It is schema only, last written
  2026-09-30.
- There is no local `data/market_trades/underlying_trades.sqlite`.
- No committed artifact carries manager or lineage links, and none should: they are private.

**3.2 Real aggregates already committed.** These come from the Phase 3 production run on 2026-10-20 at
`d7a881bc`, in `docs/valuation/evidence/package_model_phase3_2026-10-20/production_phase3_run_2026-10-20.json`.
League level only: no lineage and no manager links.

| quantity | value |
|---|---|
| ledger groups | 29,638 |
| source families: KTC trade database / Sharp Sleeper / own league (alone or with Sharp) / KTC and Sharp | 19,652 / 9,957 / 28 / 1 |
| two-team groups | 27,801 (1,753 empty, 84 with three or more teams) |
| graded trades (Phase 3's own filter, superflex basis) | 18,690 |
| distinct leagues among graded trades | 11,565 (about 1.6 trades per league) |
| largest league / top five leagues, share of graded trades | 0.2% / 0.6% |
| trade-date range | 2026-07-15 … 2026-10-20 |

Phase 3's graded population is not the census's `fitEligible`; the filters differ. The point is the order of
magnitude: thousands of leagues, each very small.

**3.3 Structural facts, verified in code at `main` `ce22d5de7`.**

1. **The box ledger has no manager keys.**
   - `deploy/systemd/dynasty-market-trade-ledger.service.template` runs `scripts/market_trade_ledger.py --no-board`
     with no `--side-key-secret-file`.
   - So every persisted Sleeper group carries `managerKeyState: side_key_secret_unprovisioned` and
     `managerKey: null` (`src/trade/market_trade_normalize.py`).
   - #1852's `market_trade_reserve.py` states that it "builds no component (that needs P2's private side keys)".
   - **Consequence:** under the current deployment, a manager-lineage reserve cannot be formed from the persisted
     ledger. Forming one needs either a provisioned side-key secret (an owner credential decision) or the
     in-memory join this census uses: ledger `hostTxId` to intel `asset_movements.user_id`.
   - The census prints neither key nor id.
2. **KTC-database rows are two-thirds of the ledger** and are structurally unlinkable:
   - KTC publishes the host league id but no transaction id, no managers and no predecessor chain
     (`normalize_ktc_row`).
   - For these rows a "component" is at most the league. Any component reserve degenerates to a league holdout,
     and its manager leakage is **unmeasurable**. The census reports it as `participantUnobservedShare`, never as
     0.
3. **The Sharp lane is a snowball sample.**
   - `scripts/discover_sharp_graph.py` expands from seeded managers to their leagues, to the members of those
     leagues, and on.
   - Under **M** its leagues are connected through the seed managers by construction, so expect one or a few
     giant M-components.
   - Whether **P** (only managers who actually traded) also collapses is the main open question the box run
     answers.
   - The synthetic power study (`CHASE_TRADE_MARKET_POWER_STUDY.md` §4.5) shows the collapse is steep: 10%
     per-seat overlap turns 160 leagues into 25 components.
4. **Lineage comes from the intel `leagues.previous_league_id`** link. Sleeper's `"0"` terminator is treated as
   "no predecessor", matching #1852's G3 fix, and loops terminate. Known limits, reported rather than hidden:
   - **A season missing from the table cuts the chain.** A 2026 league and its 2024 ancestor split into two
     lineages if 2025 was never crawled. That over-counts independent lineages; `predecessorLinksLeavingTheTable`
     measures it.
   - **Own-league and KTC leagues carry no chain** in this table.
   - **A redraft predecessor is not treated as ending the chain.** For leakage, merging more is the conservative
     direction, because the same people are in the league.
   - The canonical chain walker and store are #1852's (`league_filter.predecessor_league_id`,
     `ledger.league_season_chain`). When #1852 lands, the census should consume them; the record's
     `leagueMaturity.lineageId` is already read when present.

## 4. The tool

`scripts/lineage_component_census.py`:
- `--box`: production stores, read-only, under `scripts/research_readonly_guard.py`, which is installed before any
  application import;
- `--ledger PATH --intel PATH`: local copies;
- `--synthetic OVERLAP`: a labelled rehearsal on the power-study generator.

Properties:
- It **never draws, persists or exposes the reserve.** The policy simulations hash
  `census-sim|<seed>|<opaque unit>` with seeds 0…R−1. The reserve hashes `component ‖ 0x1f ‖ committed salt`.
  The reserve module, its config and its salt are never read; a test pins this.
- Every store is opened `mode=ro`. Nothing is written at the Python level. Raw ids exist only in process memory.
- **SQLite caveat.** The intel ledger runs in WAL mode, so SQLite's own C layer may open its `-shm` file, which
  the audit hook cannot see. A long read also delays the live writer's checkpoint. So run it as the service user
  and outside the timer windows.
- Its output is aggregate-only. `assert_aggregate_only` refuses any 9+ digit run and any `word:` / `L:` / `U:`
  key text, which covers `sleeper:`, `unknown:`, `mk:` and `utrade:`.
- `--box` refuses abbreviated flags, and refuses to run unless the guard is installed (exit 64).
- Exit codes: 0 ok; 2 the ledger or, in `--box`, the intel ledger is absent; 3 the guard refused a write or a
  process start; 64 bad invocation.

Tests: `tests/scripts/test_lineage_component_census.py`, 16 tests on synthetic ids. They cover:
- the three definitions on a hand-built graph;
- links taken from outside the population;
- loop safety;
- the concentration arithmetic, including a non-zero Gini;
- the hand-computed leakage arithmetic, with one key space and partial observation;
- that a component reserve never leaks, checked non-vacuously;
- that empty holdouts are counted;
- the window and purge boundaries;
- that the hybrid collapses to the whole-league holdout;
- the simulation hash framing;
- the id guard, plus a synthetic end-to-end run through it;
- `--box` refusing abbreviations and refusing to run without the guard;
- an end-to-end store run that resolves a duplicate group's league through the tx id, leaves both stores
  byte-identical and prints no id.

An independent review found 4 high-severity and 3 medium defects in the first version, among them hidden empty
holdouts, a `--bo` abbreviation that bypassed the guard, partial observation counted as observed, and the wrong
clock. All are fixed in the pinned commit.

A guarded `--box` rehearsal against fixture stores exited 0. The guard refused 0 writes or processes, and both
stores were byte-identical afterwards.

## 5. Candidate allocation policies: labelled SYNTHETIC rehearsal

**These are synthetic numbers from the power-study generator (`src/trade/market_trade_sim.py`): one season per
league, a 364-day span, every manager observed. They show how each policy behaves as overlap grows. They are not
evidence about real leagues.** The real equivalents come from §7.

The policies:

| id | policy | training | evaluation |
|---|---|---|---|
| **A** | whole-league (lineage) holdout + chronological split: the owner's intent | non-held lineages, dated ≤ end − window − 7-day purge | held lineages, inside the last window |
| **B** | lineage-component (P) reserve, no time split | every non-held component | every held component |
| **B′** | component reserve + chronological | as A, with P-components as the unit | |
| **C** | hybrid: P-components held whole, except inside a giant component (> 5% of trades), where the unit falls back to the lineage; plus chronological | | |
| **D** | chronological only (reference) | everything before the window | everything in the window |

Results: 20% held out, 56-day window, 100 seeds. Evaluation size is the mean with [p5–p95].

**Scenario S1:** 2% per-seat overlap, 160 leagues, 4,928 trades. The P-components are 131, top-1 share 4.1%,
effective 70.7; no giant component.

| | eval trades | eff. clusters (P) | largest share of eval | participant leak | membership leak | temporal overlap | unused |
|---|---|---|---|---|---|---|---|
| D | 728 | 63.2 | 0.04 | 0.99 | 1.00 | 0 | 89 |
| **A** | 152 [97–210] | 17.1 | 0.12 | **0.06** | 0.28 | 0 | 1,530 |
| B | 973 [612–1,379] | 15.1 | 0.15 | 0 | 0.01 | **1.00** | 0 |
| B′ | 144 [84–205] | 13.1 | 0.16 | 0 | 0.00 | 0 | 1,484 |
| C | 152 [102–206] | 13.8 | 0.15 | 0 | 0.00 | 0 | 1,515 |

**Scenario S2:** 10% overlap, 160 leagues, 5,600 trades. The P-components are 31, top-1 **74%**, effective 1.8;
M top-1 84%. Two giant components hold 81%.

| | eval trades | eff. clusters (P) | largest share of eval | participant leak | membership leak | temporal overlap | unused |
|---|---|---|---|---|---|---|---|
| D | 815 | 1.9 | 0.73 | 1.00 | 1.00 | 0 | 105 |
| **A** | 165 [106–227] | 1.9 | 0.73 | **0.28** | 0.83 | 0 | 1,704 |
| B | 936 **[73–4,397]** | 3.4 | 0.51 | 0 | 0.12 | **1.00** | 0 |
| B′ | 137 **[12–631]** | 3.6 | 0.49 | 0 | 0.12 | 0 | 1,564 |
| C | 166 [114–230] | 1.8 | 0.74 | 0.27 | 0.78 | 0 | 1,708 |

**Scenario S3:** 5% overlap, 640 leagues, 20,097 trades. The P-components are 348, top-1 10.9%, effective 41.5;
M top-1 25.8%, effective 13.7.

| | eval trades | eff. clusters (P) | largest share of eval | participant leak | membership leak | temporal overlap | unused |
|---|---|---|---|---|---|---|---|
| D | 3,077 | 41.0 | 0.11 | 1.00 | 1.00 | 0 | 357 |
| **A** | 611 [501–730] | 29.8 | 0.12 | **0.11** | 0.52 | 0 | 6,135 |
| B | 3,818 [2,426–5,737] | 19.1 | 0.22 | 0 | 0.06 | **1.00** | 0 |
| B′ | 585 [385–877] | 18.6 | 0.22 | 0 | 0.06 | 0 | 6,014 |
| C | 623 [480–818] | 19.7 | 0.15 | 0.04 | 0.21 | 0 | 6,224 |

In S1, the reserve's realized share at the target fraction (evaluation trades as a share of the population) was:
- 10%: 0.097, range 207–783 trades;
- 20%: 0.197;
- 30%: 0.300.

The single largest component lands in the reserve at about the target rate. In S2 that one draw decides whether
the reserve holds a few dozen trades or most of the data. At 10% in S2, 4 of the 100 seeds produced an empty
holdout.

### Trade-offs

| | leakage | statistical power | concentration of the held-out set | data cost |
|---|---|---|---|---|
| **A** whole-league + chronological | lineage 0, time 0; **manager leakage is real but measured** and can be removed as a sensitivity check (drop evaluation trades whose managers trade in training) | stable size: lineages are small, so p5–p95 is narrow; clusters for inference must still be P-components | low at the lineage level; inherits P-level clustering | the chronological design leaves about 30% of trades in neither set. The non-held post-cutoff trades can serve as a separate chronological validation set |
| **B** component reserve, no time split | manager 0 (for observed managers); **time leakage on every evaluation trade** | largest evaluation set, but **highly variable when a giant component exists**; few effective clusters | a permanent lock can capture a giant component and remove most training data | none, but the lock is permanent |
| **B′** component + chronological | manager 0, time 0 | smallest and most variable | as B | as A |
| **C** hybrid | equals B′ when nothing is giant; moves toward A inside giants | middle | bounded by the giant threshold | as A |
| **D** chronological only | lineage and manager leakage near 100% | large | inherits the population's concentration | small |
| any policy on **KTC-database rows** | manager leakage unmeasurable; only league holdout + chronological is possible | many tiny leagues, about 1.6 trades each | very low | — |

## 6. What the box numbers would decide (provisional reading, not a decision)

Read `populations.estimatorEligibleSleeperObserved.linkage` first, then its `components.P` and `components.P_fullyObservedOnly`:

- **If P has no giant component** (largest share ≲ 5%, effective components ≳ 50):
  - Component-level and league-level holdouts both work.
  - B′ or C add zero manager leakage at almost no cost relative to A.
  - The owner's chronological separation is kept either way.
- **If one P-component holds a large share** (≳ 25%):
  - A component reserve is effectively one coin flip. Either it locks most of the data permanently or it locks
    almost none.
  - **A (the owner's intent) is the robust choice.** Report its measured participant leakage, and run the
    "purge leaking evaluation trades" sensitivity check.
  - No policy can create independent clusters, so confidence intervals must cluster at P-component level whatever
    the allocation.
- **In every case:**
  - Keep the chronological split. A reserve without it leaks the future into training on every evaluation trade.
  - Keep the KTC lane on league holdout + chronological, with manager leakage reported as unmeasurable.

Separately, a permanent manager-lineage reserve would need either a provisioned side-key secret on the box or a
redesigned component key (§3.3.1). Both are owner decisions this census does not make.

## 7. Pinned box command (awaiting owner authorization; do not run without it)

Read-only and aggregate-only. Run it as the service user (`dynasty`), never root, outside the 04:20–06:30 and
08:45–09:15 UTC timer windows. From your own machine:

```bash
ssh -p <port> dynasty@<host> 'bash -s' < lineage_census_box.sh > lineage_census.json
```

`lineage_census_box.sh`, copied verbatim:

```bash
#!/usr/bin/env bash
# Manager-lineage component census (owner Package 5A).  READ-ONLY, aggregates only.
set -Eeuo pipefail
PIN=dc5ee632884277bb7e31a9a05d8fc8dfe15379d9
APP_DIR=/home/dynasty/trade-calculator
RAW="https://raw.githubusercontent.com/jasonleetucker-code/riskittogetthebrisket/$PIN/scripts"
[[ "$(id -un)" != root ]] || { echo "run as the service user, not root" >&2; exit 64; }
WORK="$(mktemp -d /tmp/lineage-census.XXXXXX)"
trap 'rm -rf -- "$WORK"' EXIT
cd "$WORK"
for f in lineage_component_census.py research_readonly_guard.py; do
  curl -fsSL --proto '=https' --max-time 60 "$RAW/$f" -o "$WORK/$f"
done
sha256sum --check --strict --quiet - >&2 <<'PINS'
67c16624d60a6f42308761a29b348393df303ea513c12d1f4f14e7ed1442acff  lineage_component_census.py
5c208fe8ee187d78ef7173330efc795a621b970f1ba69ff416c9edf836bc6f18  research_readonly_guard.py
PINS
PY=/home/dynasty/.venvs/trade-calculator/bin/python
[[ -x "$PY" ]] || PY="$APP_DIR/.venv/bin/python"
TMPDIR="$WORK" RISKIT_APP_DIR="$APP_DIR" OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  timeout 1800 nice -n 19 ionice -c3 \
  "$PY" -B "$WORK/lineage_component_census.py" --box --replicates 100
```

- The pinned commit `dc5ee632884…` is this PR's script commit, reachable through the PR ref.
- After merge, `main` carries byte-identical files. The sha256 check is what binds the run, and the guard file's
  hash is `main`'s current `scripts/research_readonly_guard.py`.
- Expected cost: about 2 minutes locally for 28.5k synthetic trades × 100 seeds × 3 policy populations. Budget
  30 minutes on the box. Python heap peaked at about 20 MB in that run; the raw-id sets add to that but stay well
  under 1 GB.

Acceptance checks on the output:
1. Exit 0, and `readOnlyGuard.refusedWriteOrProcessAttempts == 0`.
2. `inputs.intel.available` is true. Compare `inputs.intel.tradesFoundInIntel` with `tradesWithHostTxId`: a
   large gap means intel movements were pruned. Read each population's `linkage` block before its component
   numbers. Report both; neither is an error.
3. The output contains no 9+ digit run and no key text; the script asserts this.
4. Commit it byte-for-byte under `docs/market_trades/evidence/lineage_census_<date>.json`, and add the real
   tables to this document as an addendum.

## 8. Scope and status

- PR #1852 was **not rebased, merged or edited**. This census does not depend on it:
  - it reads the raw lineage link from the intel ledger and needs neither #1852's chain store nor its maturity
    owner;
  - it reads none of #1852's reserve config.
- Q2 stays `PROPOSED_PENDING_OWNER_Q2`. The reserve's share and allocation are the owner's to choose after the
  box run.
- Production is unchanged.

UNRESOLVED:
- (1) The real census. It needs the owner-authorized box run in §7.
- (2) Cross-tabulation by maturity cohort, after #1852 lands.
- (3) The owner's reserve-policy choice.
