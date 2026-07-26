# Claude Session Audit Handoff

**Prepared for independent technical and strategic audit.**
Session date: 2026-07-26. Repository: `jasonleetucker-code/riskittogetthebrisket`.

---

## READ THIS FIRST — scope and reliability of this document

This document is written to be audited, so its own reliability must be
stated before its contents.

**1. Part of this session was context-compacted.** The early portion
(roughly: the competitor-parity roadmap, Phases 0–7, the redesign R0–R2
work, and much of the TE-premium investigation) survives to me as a
structured summary, not as full transcript. Where a claim rests on that
summary rather than on something I verified in the repository today, it is
marked **[from summary]**.

**2. Section 4 cannot be completed to the letter of the request, and I am
not going to fake it.** The request asks for *every* formula in the system
with exact logic, bounds, and missing-data behavior. The live valuation
pipeline alone (`src/api/data_contract.py::_compute_unified_rankings`) is a
twelve-stage process inside a file of ~8,000 lines, and there are further
formula sets in the ROS, FAAB, trade, intel and league-intel subsystems. I
did not read all of that code during this session. Reproducing it from
memory or inference would produce a document that *looks* authoritative and
misleads the auditor — the exact failure mode this session spent the day
cataloguing.

What Section 4 therefore contains:
- Formulas I **verified in code or measured on data today** — reproduced
  precisely with file and function references.
- Formulas **documented in `CLAUDE.md`** — reproduced as documentation,
  labelled as such, explicitly *not* re-verified against source.
- Everything else — **named, located by file/function, and marked
  `NOT VERIFIED THIS SESSION`**, with a pointer for the auditor.

**3. "Implemented" in this document means "exists on a named branch at a
named commit."** Almost nothing described here is merged to `main`. The
distinction is tracked per item.

**4. Six autonomous agents were still running when this was written.**
Their branches advance after this snapshot. Commit counts are as of
2026-07-26 ~19:45 UTC.

---

## 1. Original Objective

### Product vision

A private dynasty fantasy-football analytics platform for a **single
12-team Superflex IDP best-ball league on Sleeper**. The stated goal, in
the user's words, is to give them *"every possible edge in their league —
trades, waivers/FAAB, player evaluation, league-mate tendencies."*

This is not a commercial product. It has one user. That single fact drives
several architectural decisions that would be wrong for a SaaS product:
per-league tuning is legitimate; a 12-manager sample is the entire
population, not a sample of a larger one; and "polite" scraping cadence is
chosen for courtesy rather than scale.

### Problem it solves

Public dynasty valuation sites (KeepTradeCut, IDP Trade Calculator,
DynastyDaddy, FantasyCalc, etc.) price players for *generic* league
formats. This league is not generic:

| Setting | Value |
|---|---|
| Teams | 12 |
| Format | Superflex, **best ball** (no weekly lineup setting) |
| Starters | 21 — QB1 RB2 WR3 **TE2** FLEX2 SFLEX1 K1 **DL3 LB3 DB3** |
| Bench | 37 (roster 58) |
| Taxi / IR | 0 / 0 |
| Scoring keys | 141 active |
| TE premium | **removed for 2026** (`bonus_rec_te` = 0) |
| Playoffs | 7 teams from week 15 |
| Rookie draft | 6 rounds |
| FAAB | $100 |

The gap between "what KTC says a player is worth" and "what a player is
worth *here*" is the product.

### Target user

One person, the repository owner. Secondary read-only surface: a public
league hub for league-mates.

### Expected final experience

Per the master directives issued this session: a roster-intelligence
dashboard answering *how strong am I now / rest-of-season / 1-3 years out*,
*which positions are truly strong versus strong-by-name-value*, *who should
I target*, *which trades are market-fair but model-positive*, with every
number explainable and confidence-rated.

---

## 2. Chronological Session History

Reconstructed in order. **[from summary]** marks pre-compaction stages.

### Stage 1 — Competitor-parity roadmap **[from summary]**

**Requested:** a 37-item roadmap benchmarking against FantasyNavigator and
PlayForKeepsDynasty — player search/filters, competitor audits, two new
ranking sources, TEP normalization, FAAB optimization, Sleeper
intelligence, a real news system.

**Approach:** phased plan (Phase 0–7) recorded in the plan file
`prancy-rolling-wilkinson.md`. User chose **sources-first** ordering and a
**hybrid-parallel** execution mode: main session drives hot-file phases
sequentially, background agents build isolated ones concurrently.

**Outcome:** Phases 0–7.1 completed and merged **[from summary]** — new
sources (Fantasy Navigator, PFK), search/filters, FAAB v2, Sleeper intel /
Sharp Tracker, news tab, Pick Projector.

### Stage 2 — Around-the-clock automation **[from summary]**

**Requested:** *"I want claude constantly debugging and working on the site
even when I am asleep."*

**Implemented:** autonomous orchestration ticks, a liveness/resume loop for
agents killed by credit outages, and scheduled self-check-ins.

### Stage 3 — Reviewer agent **[from summary]**

**Asked:** whether a Claude reviewer is redundant when Claude wrote the
code. **My answer:** complementary — fresh eyes without authoring context —
with the honest caveat that same-model review is weaker on *shared* blind
spots. **This was validated repeatedly today**; see §12.

### Stage 4 — League Intelligence Engine directive **[from summary]**

A 46-section specification: market vs consensus vs league-adjusted value,
exact scoring engine, best-ball optimizer, replacement/scarcity,
champion-challenger MLOps, global valuation-mode toggle. Explicit
instruction: *"Do not stop after writing a plan… You must begin
implementing."* Every material departure requires an ADR. *"Never invent
precision, data access, licenses, historical projections, statistical
relationships, or completed integrations."*

**Result:** workstream WS-E, branch `claude/league-intel-foundation`,
PR #550. ADRs 001–009.

### Stage 5 — Master agent-orchestration directive **[from summary]**

**Requested:** audit and optimize every agent, workflow, worktree, branch
and coordination mechanism; operate as one engineering organization;
minimize git/PR overhead; **optimize for a complete product ~1 week out
rather than constant short-term stability.**

**Implemented:** `docs/ORCHESTRATION.md` — workstream ownership table,
revised git policy (one branch per *workstream*, not per task; PR only at
integration checkpoints), two integration windows, frozen shared contracts,
dependency graph.

**Direction change:** retired a per-task-PR loop that had produced ~13
merges/day.

### Stage 6 — TE premium investigation **[from summary, with today's corrections]**

**Requested:** *"we removed the TE premium in the scoring but now we start
2 TEs… I just want to account for the scarcity."* Then: apply KTC's curve
to sites that don't publish one; handle rank-only sources; allow a dynamic
premium; and *"most of the sites that have TEP baked in are usually
accounting for some sort of TEP scoring, not two tight ends."*

This became the session's longest analytical thread, and its conclusions
**moved repeatedly**:

| Stage | Premium | Why it changed |
|---|---|---|
| Initial derived | 1.592 | depth parameter 3.79 TE/team |
| KTC measured | 1.320 | external anchor |
| After flex-artifact fix | ~1.32 | see Stage 8 |
| **After endpoint symmetry fix** | **~1.12** | see Stage 8 — current |

**User correction accepted:** the user pointed out vendor TEP likely
encodes *scoring*, not *structure*. I had described three-method agreement
as "independent corroboration" and downgraded it to "sanity check." This
was the first of several such downgrades.

### Stage 7 — Live-roster scarcity idea (user)

**User:** *"that is one way you can help measure scarcity for each
position, by using the number that are actually on each team in the sleeper
league at any given moment."* Dispatched as a measurement task.

### Stage 8 — TE flex-worthiness (verified today)

**User:** *"TEs CAN start in flex, I just don't know how to measure how
many are flex worthy. Maybe look at historical data with our league's
scoring?"*

**Finding — a real defect in the method.**
`src/league_intel/replacement.py::measure_endogenous_starters` ran the
exact optimizer on `rosValue`, a **season-long mean**. Its docstring
asserted *"FLEX never takes a TE at all"* as a finding. That is an artifact
of point estimates: best ball pays for weekly spikes, and a mean erases
them.

**Measured on actual 2025 weekly scoring**, all 17 weeks pulled from
Sleeper, re-solved under the current 21-slot vector:

| | projection path (means) | weekly actuals |
|---|---|---|
| FLEX → TE share | **0.0%** | **10.4%** (my pass: 11.8%) |
| TE started / team | **2.00** | **2.215** (my pass: 2.28) |

The two passes filter team-weeks differently (158 vs 170) and are **not
reconciled**; they agree on every conclusion.

**Then a larger error underneath.** The premium compares a 1-TE reference
against our 2-TE league. Every figure to date measured the *league*
endpoint from data while **assuming the reference was 1.0 TE/team**.
Re-solving the 1-TE vector on the same scores: **1.608 TE/team**. So the
structural demand change is **1.378×**, not 2.215× — an assumed reference
overstates it by **1.61×**.

| basis | ref | league | median premium |
|---|---|---|---|
| assumed 1.0 / naive 2.0 | TE12 | TE24 | 1.239 |
| assumed 1.0 / actual 2.215 | TE12 | TE27 | 1.316 |
| assumed 1.0 / rostership 2.71 | TE12 | TE33 | 1.416 |
| **symmetric 1.608 → 2.215** | **TE19** | **TE27** | **~1.12** |
| *KTC measured (external)* | | | *1.320* |

**⚠ The 1.316 row lands 0.004 from KTC and must never be cited as
validation** — it pairs a measured endpoint with an assumed one.

**Also retracted:** the `3.79` depth figure I had been quoting was never
`starters_per_team`; it was marginal-weighted effective depth, already
retired for a churn confound.

### Stage 9 — Ops incident: the domain was lost

**Trigger:** routine attempt to read server logs for the failing intel
cron. The user attempted `journalctl` on Windows; then SSH failed; then:
**"We dont own the riskittogetthebrisket domain anymore."**

**Consequences found:**

1. The domain resolves to **178.156.148.92**, a machine the user does not
   control.
2. Three workflows had a hardcoded fallback to that domain.
   `intel-refresh.yml` POSTs with `Authorization: Bearer
   INTEL_REFRESH_TOKEN` — so **that secret was sent to a third party on
   every scheduled run**.
3. The user was one keystroke from typing their server password into a
   stranger's SSH prompt. They backed out.

**Fixes:** fallbacks removed from all three workflows (fail loudly on unset
`PROD_PUBLIC_URL`); all alert links, uptime monitoring, Grafana, sitemap,
robots repointed to `http://169.58.50.224`; OG share-card footers rebranded
off the hostname; nginx config marked DO-NOT-APPLY; five stale runbook IP
references purged.

**Access recovery:** VPS was rebuilt 2026-07-20 so none of the user's four
local keys were present; Contabo's key store is **provisioning-only**
(applying a key requires a reinstall, which would wipe the server). A
one-shot `workflow_dispatch` workflow using existing deploy credentials
restored access. **I attempted to commit that workflow and a safety
classifier blocked it twice; I stopped rather than routing around it**, and
the user created it via the GitHub web UI instead.

**Issue #545 root cause — two stacked bugs, the first masking the second:**

| | |
|---|---|
| Workflow called a domain we don't own | fixed via `PROD_PUBLIC_URL` |
| `INTEL_REFRESH_TOKEN` **never present** in the service environment | fixed — predates the domain loss entirely |

Intel crawl now green (2m10s).

### Stage 10 — Roster & Trade Intelligence directive (WS-J)

A second large additive directive: Roster Intelligence Engine, Trade
Opportunity Engine, Target Position/Player engines, Trade Package
Generator, Partner Fit & Acceptance Model, Continuous Improvement system.
Explicitly additive to WS-E; must not duplicate.

**My Phase-1 audit produced F-1, which the fresh-eyes review then partially
refuted — see §12.**

### Stage 11 — "Run all agents until everything is ready"

**User:** *"Run all agents until everything is ready to go, and everything
is pushed and merged… None of them should be idle. Only bother me for truly
important decisions."* Stepping out for the day.

**Change of policy:** the Jul 29 integration window no longer gates merges;
merge when genuinely ready.

---

## 3. Current Product Architecture

**Merge status legend:** ✅ on `main` · 🔶 on a branch, unmerged · 📋 spec only

| Component | Location | Status |
|---|---|---|
| Frontend | `frontend/` — Next.js 15 / React 19, App Router, port 3000 | ✅ |
| Design system | `frontend/components/ds/` | ✅ base; 🔶 `Confidence` |
| Backend | `server.py` (~10k lines), FastAPI/Uvicorn, port 8000 | ✅ |
| **Database** | **None.** JSON snapshots on disk (`data/`, `exports/`) | ✅ |
| Live valuation | `src/api/data_contract.py::_compute_unified_rankings` | ✅ |
| Source adapters | `src/adapters/`, `scripts/fetch_*.py` | ✅ |
| Identity | `src/identity/`, `src/utils/name_clean.py` | ✅ |
| League registry | `src/api/league_registry.py`, `config/leagues/registry.json` | ✅ |
| League Intelligence | `src/league_intel/` | 🔶 PR #550 |
| ROS / lineup | `src/ros/` | ✅ (exact optimizer 🔶) |
| Roster Intelligence | `src/roster_intel/` | 🔶 unmerged |
| Trade engines | `src/trade/` | ✅ (IDP fix 🔶 #556) |
| Sharp Tracker intel | `src/intel/` | ✅ |
| News | `src/news/`, `frontend/app/news/` | ✅ |
| Public league hub | `src/public_league/`, `frontend/app/league/` | ✅ |
| Auth | `server.py` + `frontend/components/useAuth.js` | ✅ (bug 🔶) |
| Deployment | `deploy/`, `.github/workflows/deploy.yml` | ✅ |
| Testing | `tests/` (~3,400 collected), `tests/e2e/` | ✅ |
| Monitoring | freshness/coverage watchdogs, `deploy/monitoring/` | ✅ |

### Notable architectural facts

- **No database.** Everything is JSON snapshots. An auditor should treat
  "database migrations" as N/A and question whether this scales to the
  proposed engines.
- **`FRONTEND_RUNTIME` is hardcoded to `next`**; page routes proxy to Next.
- **The backend page proxy is broken** — serves the anonymous shell to
  signed-in sessions; `/waivers`, `/news`, `/draft` absent from its
  hand-maintained route list (drifted three times). Issue #555. My
  recommendation is to declare it non-production-representative and delete
  it, since nginx bypasses it in production. **Decision open.**
- **Scoring profile vs league key split** (`CLAUDE.md`): rankings follow
  *scoring profile* and are shared across same-scoring leagues; rosters,
  teams, drafts follow *leagueKey*. Frozen contract.
- **Deployment: bare IP over HTTP, no TLS.** Login credentials cross the
  network in plaintext. Pending a new domain.

### API endpoints (from `CLAUDE.md`, not re-verified)

`/api/data`, `/api/status`, `/api/health`, `/api/scrape`,
`/api/scaffold/*`, `/api/trade/suggestions`, `/api/trade/finder`,
`/api/leagues`, `/api/rankings/overrides`, `/api/terminal`,
`/api/trade/simulate`, `/api/angle/*`, `/api/draft-capital`,
`/api/public/league/*`, `/api/intel/*`, `/api/news`,
`/api/ros/team-strength`, `/api/ros/pick-projections`.

---

## 4. Formulas and Scoring Models

**See the reliability note at the top of this document.** This section is
split by evidence level.

### 4A — Verified by me today (measurement or code read)

#### 4A.1 Endogenous flex allocation (defect + correction)

**File:** `src/league_intel/replacement.py::measure_endogenous_starters`

```
per_team[pos] = count(pos in optimal_lineup across teams) / n_teams
```

**Defect:** input was `rosValue` — a season-long mean 0–100 composite from
`src/ros/aggregate.py`. Best-ball value derives from weekly variance; a mean
erases it.

| Input | FLEX→TE | TE started/team |
|---|---|---|
| `rosValue` (mean) | 0.0% | 2.00 |
| actual 2025 weekly scores | 10.4% | 2.215 |

**Fix adopted (ADR):** calibrate the depth constant from actual weekly
outcomes. Rejected alternative: sample around projections using the
Gaussian model in `src/ros/playoff_sim.py:248-265` — rejected because
deriving a structural constant through an approximation embeds its error.

#### 4A.2 TE structural premium — symmetric endpoints

```
structural_demand_change = league_TE_per_team / reference_TE_per_team
                         = 2.215 / 1.608
                         = 1.378
premium(band) = value_at_rank(TE_ref_rank) / value_at_rank(TE_league_rank)
operative median premium ≈ 1.12   (TE1-12 band: 1.082)
```

**Status:** a **finding**, not a published value. Not applied to any live
value. TE axis remains `ABSENT` in `src/league_intel/adjustment.py`
specifically so it cannot stack on the blend's existing ×1.15.

**Unvalidated assumption:** the reference endpoint presumes KTC's standard
board targets a league like our 2025 one (superflex, 2 FLEX). A generic
1-TE league with one flex slot would lower the reference and *raise* the
premium.

#### 4A.3 Cross-market scale relation (measured)

**My independent verification, live data:**

```
players priced on BOTH ktcSfTep and idpTradeCalc : 475
pooled median  IDPTC / KTC                       : 1.0004
board maxima                                     : 9999 / 9999
```

WS-E measured 476 / 0.9997, Spearman 0.990. Per-position medians: QB 1.020,
RB 0.994, WR 1.012, PICK 1.000, **TE 0.895** (the TE-premium question, not
a scale artifact).

**Consequence:** `idpTradeCalc` is a *cross-market* board that prices
offense too. The pipeline's `raw / site_max × 9999` step is a **no-op**
between these two sources.

**Load-bearing unvalidated assumption**, stamped `SHARED_SCALE_ASSUMPTION`:
that IDPTC's internal offense↔IDP exchange rate is *correct*, not merely
self-consistent. Nothing validates it — there is no ground truth for what
an edge rusher is worth in WR points. The 475-player overlap is **by
construction offensive players**, so it calibrates one half of the bridge.

#### 4A.4 Package valuation gate (WS-E, current revision)

```
primary   : value each package entirely within ONE market
            (offense-only → ktcSfTep; any IDP → idpTradeCalc)
fallback  : convert fringe assets at measured per-position ratio
gate      : withhold a COMPARISON when the propagated band on
            market_gain_pct straddles DEFAULT_GATE_PCT (5.0,
            mirroring angle.py's max_market_gain_pct)
```

Revision history matters for the auditor:
- **v1:** suppress on *presence* of a cross-market asset → 15% suppression.
- **v2:** suppress on conversion band magnitude → still wrong; *a package in
  isolation has no decision boundary*.
- **v3 (current):** the verdict is a threshold crossing that only exists
  when two packages are compared, so the gate moved into
  `compare_packages()`.

Measured: 160% gain / 168-pt band → certain; 4.2% gain spanning [0.9%,7.6%]
→ withheld; exact-path 4.0% gain → certain.

#### 4A.5 Marginal positional strength (WS-J)

**File:** `src/roster_intel/marginal.py`

```
marginal(position) = S(full roster) − S(roster without that position)
   where S = exact best-ball lineup score (src/ros/lineup.py)
```

Measured on 12 real full rosters (53–58 players):

| metric | min | max | distinct |
|---|---|---|---|
| lineup score | 412.4 | 861.6 | 12/12 |
| QB marginal | 31.6 | 118.9 | 12/12 |
| RB marginal | 49.2 | 224.5 | 12/12 |

**Validating case:** Blaine has the league's **highest QB marginal (118.9,
nearly double the next)** while ranking **11th of 12** in lineup score. A
summed-value or count metric reports that roster as QB-strong.

**Self-caught defect:** fragility was first normalized by the position's
marginal contribution, which collapses to ~1/n and returned an identical
`0.3333` for a deep RB room and a thin WR room. Now normalized by mean
entrant value.

#### 4A.6 Competitive window (WS-J)

**File:** `src/roster_intel/window.py`. **Softmax over competitiveness and
trajectory**, deliberately not thresholds (a threshold flips a team one
point either side of a cut while its neighbour doesn't move).

Measured, all 12 distinct, sum-to-1 exact to <1e-9:

| team | comp | traj | champ | playoff | retool | prod-strug | rebuild |
|---|---|---|---|---|---|---|---|
| Brent | 0.96 | 0.51 | **.652** | .316 | .031 | .002 | .000 |
| Kich | 0.46 | **0.23** | .060 | **.403** | .336 | .116 | .084 |
| jstuedle | 0.04 | 0.56 | .000 | .005 | .089 | .284 | **.622** |

**Trajectory earns its place:** Kich is mid-pack on competitiveness with the
league's oldest lineup and reads *playoff_contender* rather than *retool*.

**Ordering caveat shipped in the payload** (`STATE_ORDER`,
`ORDERING_CAVEAT`): the ends are ordered; **`retool` vs
`productive_struggle` is not** — they are different strategies at similar
competitiveness.

#### 4A.7 Acceptance model — structurally unidentifiable

**File:** `src/roster_intel/partner.py`

```
tradeAcceptanceEstimate =
    plausibility_prior (0.18, an ASSUMPTION, not a fit)
  + market fairness
  + roster fit (two-sided)
  + competitive-window fit
  + league-history adjustment
  + manager-specific term  ← GATED, never fires
```

**The gate does not clear and structurally cannot.**
`src/api/sleeper_overlay.py` filters `if tx.get("status") != "complete"` —
only accepted trades are ingested. **A declined offer leaves no record in
Sleeper's public API.** We hold the numerator of an acceptance rate and
never the denominator.

Gate conditions: ≥30 accept/**reject** decisions (SE of a binary rate ≈
0.073 at n=30, p≈0.2; at actual league volume SE ≈ ±0.2, wider than the
effect claimed), **and** |z| ≥ 2.0 from baseline.

`tradeAcceptanceEstimate` is a **plausibility score wearing probability
units**; confidence never exceeds 0.45.

**Deliberately removed:** `team_aggression` from `faab_analytics.py` — FAAB
spend is waiver behaviour, and an aggressive bidder may be aggressive
*because* they don't trade.

### 4B — Documented in `CLAUDE.md`, NOT re-verified this session

Reproduced as documentation. **The auditor should verify each against
source.**

**Live pipeline** (`src/api/data_contract.py::_compute_unified_rankings`):

1. Common 0–9999 internal scale
2. Percentile normalization against a **fixed 500-rank** reference
   (`_PERCENTILE_REFERENCE_N`); ranks past 500 clamp to the tail
3. Hill-style percentile→value via scope master curves
   (`src/canonical/player_valuation.py`)
4. Value-direct voting for `_VALUE_BASED_SOURCES` (exactly `ktcSfTep` +
   `idpTradeCalc`): `raw / site_max × 9999`. All others vote via
   rank→percentile→Hill
5. Scope routing: cross-market → GLOBAL, overall IDP → IDP, else OFFENSE
6. Hierarchical anchor + α-shrinkage (**α = 0.10**) for IDP and picks only;
   offense uses flat count-aware mean-median
7. Count-aware aggregation: n=1 passthrough · n=2 mean · n=3–4 untrimmed
   mean-median · n≥5 trimmed
8. **RETIRED:** λ·MAD volatility penalty (`_MAD_PENALTY_LAMBDA = 0.0` since
   2026-04-20). `sourceSpread` is a pure diagnostic
9. **Single-source haircut:** non-pick rows on one post-Hampel source keep
   **30%** (`_SINGLE_SOURCE_VALUE_RETENTION = 0.30`)
10. IDP calibration post-pass (`config/idp_calibration.json`) inside a
    market corridor clamp (P90 drift band)
11. Pick tethering — current-year slot picks inherit merged rookie pool
12. Multiplicative future-year pick discount
    (`config/weights/pick_year_discount.json`)

**TEP multipliers** (`src/api/data_contract.py`):

```
_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15   (slider-clamped [1.0, 1.5])
_TE_BLANKET_NATIVE_MULTIPLIER     = 1.10
_TE_BLANKET_KTC_EXEMPT_KEYS       = {"ktc", "ktcSfTep"}
```

Routing verified today: `is_tep_premium: True` → 1.10 native nudge;
`False` → 1.15. **The double-counting I suspected for
`fantasyProsFitzmaurice` does not exist** — the flag is set and consumed
correctly.

**Blend weights:** all 1.0 by policy in `_RANKING_SOURCES`.
`config/weights/default_weights.json` is historical documentation only —
**nothing loads it**.

**Master curves** auto-refit weekly by
`.github/workflows/refit-hill-curves.yml`.

### 4C — Vendor TEP uplifts (measured today, three publishers)

At the only reliable band (TE1-12):

| Publisher | Uplift |
|---|---|
| KTC | ×1.287 |
| Fitzmaurice | ×1.198 |
| Boone | ×1.421 |

**Shape corroborated** (all monotonically increasing with depth, matching
our replacement math by a different method). **Level is not** — ~18%
spread, no consensus.

**Two cautions recorded:**
- Deep bands are unusable — both charts hit small integers at the tail
  (Fitz 4→6, Boone 1→2), so one rounding unit is 20–25%. The apparent
  KTC/Fitz agreement at TE41+ (1.512 vs 1.500) is **coincidence on a coarse
  grid**.
- **Controls are absent, not at unity.** Both publish a TEP column only for
  TEs, so controls appear unchanged *by construction*. These are
  **published uplifts**, not differentials between independently generated
  boards — a weaker evidentiary class.

**The axis question is unresolved.** Neither publisher states whether TEP
means premium *scoring* or 2-TE *structure*.

### 4D — Named but NOT VERIFIED THIS SESSION

The auditor should treat every item here as unread by me.

| System | File / function |
|---|---|
| Exact scoring engine (141 keys) | `src/league_intel/scorer.py::score_stat_line` |
| Best-ball optimizer | `src/ros/lineup.py::optimize_lineup`, `solve_optimal_assignment` |
| Replacement levels, scarcity | `src/league_intel/replacement.py` |
| Guardrails, evidence tiers | `src/league_intel/adjustment.py` |
| Value schema, selector | `src/league_intel/values.py::get_active_value` |
| ROS aggregation | `src/ros/aggregate.py` |
| Team strength composite | `src/ros/team_strength.py` |
| Playoff/championship sim | `src/ros/playoff_sim.py` |
| Pick projection | `src/ros/pick_projection.py` |
| FAAB recommender | `src/trade/faab_recommender.py::recommend_faab` |
| FAAB contention | `src/trade/faab_contention.py::estimate_rival_bids` |
| Trade suggestions | `src/trade/suggestions.py` |
| KTC arbitrage finder | `src/trade/finder.py` |
| Counter-package builder | `src/trade/angle.py` |
| Monte Carlo trade sim | `src/trade/monte_carlo.py` |
| Value adjustment (VA) | `src/trade/angle.py::_adjusted_pair_totals` |
| Intel aggregation | `src/intel/aggregate.py` |
| Signal engine | `frontend/lib/signal-engine.js` |

---

## 5. Roster Analysis System

**Status: partially implemented, unmerged, on `claude/ws-j-roster-intel`
(24 commits).**

### Implemented and measured

| Capability | File | Notes |
|---|---|---|
| Marginal positional strength | `marginal.py` | leave-one-out on exact optimizer |
| Lineup-entry rate, clogger value | `marginal.py` | all vary across 12 |
| Fragility | `marginal.py` | defect self-caught and fixed |
| Full-roster eligibility join | `roster_source.py` | `eligibility` is a **required** kwarg |
| Per-position profiles | `profiles.py` | tiers, age/injury/bye, replacement gap, surplus, need |
| Competitive window | `window.py` | five probabilities, softmax |

**The eligibility join reproduced LI-3's published figures independently** —
6 of 12 teams improved, mean +3.40, max +13.75, via a different data path.
This is *genuine* corroboration (two measured paths), in contrast to the
six false corroborations catalogued in §12.

**Counter-intuitive result, correctly explained:** individual IDP marginals
often *fall* after the eligibility fix (Brent DL 138.6 → 77.3) because
hybrids backfill the slots. The position's marginal drops *because the
roster became more robust*.

### Three judgements the auditor should check

1. Tiers are against **league** replacement levels, not roster-relative
   (roster-relative crowns every team's best player — that is how
   "everyone is 100.00" is born).
2. Surplus is **non-entering value**, not excess headcount.
3. **FLEX/SUPER_FLEX are not attributed to any position** — LI-5 measured
   QB taking SUPER_FLEX 9 times in 12 and TE taking FLEX zero, so splitting
   by assumption is a ~40% error at QB.

### Not built

Roster-level value rollups; `playoff_sim` wiring; draft capital
integration; taxi squad (N/A — league has 0 taxi slots); target position
and target player engines (in progress on `ws-j-partner-fit`).

### Known measurement caveat

The first run used `startingLineup + benchDepth` (26 players) rather than
real 58-man rosters. **A truncation guard test now fails if that source is
reconnected.** My prediction that full rosters would materially reduce
fragility was **wrong** — it barely moved, because backfill players were
already inside the top-8 bench slice.

---

## 6. Trade Recommendation System

### Current state — three engines, divergent

| Engine | File | Purpose | Status |
|---|---|---|---|
| Suggestions | `src/trade/suggestions.py` | sell-high / buy-low / consolidation / upgrades | ✅ live |
| Finder | `src/trade/finder.py` | KTC arbitrage: board vs market | ✅ live, **was broken** |
| Angle | `src/trade/angle.py` | counter-package builder | ✅ live |

### P1 defect found and fixed today — the finder was offense-only

`finder.py` built `with_ktc = [a for a in pool if a.has_ktc]` and dropped
everything outside the KTC top-150. **KTC's board contains zero IDP
defenders** — verified: Hutchinson, Parsons, Garrett, Carter, Verse,
Campbell all absent. `EXCLUDED_POSITIONS` is only `{K,PK,DST,DEF}`, so IDP
entered the pool and was then silently removed.

**In a league with nine IDP starters, the arbitrage finder returned offense
and picks only, with no warning.**

Worse, the old `ktcCoveragePercent` reported **100%** throughout, because
the missing rows were filtered out *before* it counted them.

**Fix (PR #556):** per-market gate — each asset anchored on the board its
counterparty consults, and **ranked within its own market's population**.
That last part is load-bearing: one ranked list buries every defender
regardless of which values are read, because offense runs to 9999 while the
best defender sits at 6444.

### Second P1 — `suggestions.py`'s "KTC filter" never read KTC

`_assign_ktc_ranks` enumerated a pool already sorted by `display_value`, so
`ktc_rank` was the **blended-board rank**. Docstring false, constant
misnamed, `metadata["ktcTopNFilter"]` misreporting. **`CLAUDE.md` was wrong
about both engines.**

**Deliberate decision: the engines should NOT share a definition.**
`finder.py` arbitrages against retail and needs a real retail anchor;
`suggestions.py` only needs an asset-quality gate, and our blended board
covers IDP and picks that no single retail board does. Unifying them would
reimport the exact blind spot just removed. Renamed with deprecated
aliases; behaviour unchanged.

### Market-fair / model-positive identification

The primary feature. Offense → KTC; defense → IDPTC; mixed → the exact-path
strategy (§4A.4). **`angle.py` is deliberately NOT yet rewired** — the
reachable defect is on the *offer* side (`offer_rows`, ungated), not the
counter side (`include_idp`, which the frontend never sends).

### Not implemented

Trade shapes beyond what exists (3-for-1, 3-for-2 etc.), Pareto ranking,
championship-probability deltas per trade, the explanation/pitch surface,
the rejection heuristics for unrealistic trades, and user controls. **All
of §6's more advanced requirements in the directive are specification
only.**

---

## 7. External Inspiration and Feature Parity

| Source | Feature | Status |
|---|---|---|
| KeepTradeCut | Offensive market anchor (`ktcSfTep`) | ✅ implemented |
| KeepTradeCut | Value Adjustment curve for packages | ✅ (applied to IDPTC too — **unverified**, F-2) |
| KeepTradeCut | TE++ board as TEP reference | ✅ measured ×1.287 |
| IDP Trade Calculator | Defensive market anchor | ✅ implemented |
| IDP Trade Calculator | Cross-market bridge (prices offense too) | ✅ **discovered today** |
| Fantasy Navigator | Rankings source | ✅ **[from summary]** — note values are KTC-derived, partially correlated |
| PlayForKeepsDynasty | Rankings source via Supabase `pfk_dynasty_rankings` | ✅ **[from summary]** |
| PlayForKeepsDynasty | Sharp Tracker (cross-league buy/sell) | ✅ `src/intel/` |
| PlayForKeepsDynasty | Pick Projector | ✅ `src/ros/pick_projection.py` |
| PlayForKeepsDynasty | `pfk_ktc_values` table | ❌ **rejected** — a KTC mirror, we have KTC |
| PlayForKeepsDynasty | Articles as a news provider | 📋 planned |
| Sleeper | Rosters, matchups, transactions, trending, players | ✅ |
| Sleeper | "Suggested FAAB" field | ❌ **does not exist** — re-framed as a derived anchor |
| ESPN / CBS / RotoWire / FantasyPros | News providers | ✅ `src/news/providers/` |
| FantasyPros (Fitzmaurice) | TEP side-by-side chart | ✅ measured ×1.198 |
| Yahoo (Boone) | TEP side-by-side chart | ✅ measured ×1.421 |
| Draft Sharks | Rankings + ROS | ✅ (paid subscription, authenticated fetcher) |
| Draft Sharks | Raw per-category projections | ❓ **unknown — needs investigation** |
| Stock-market platforms | Value/spread scatter, movers, tickers | ✅ `/edge`, dashboard |
| Underdog | Best-ball ADP | 📋 planned |
| nflverse | Historical stats | 📋 planned |

**Legal / ToS:** all fetches are public/unauthenticated except Draft Sharks
(paid subscription, user's own credentials) and IDP Show (Substack
subscriber cookies, run on the user's own VPS). Cadence is deliberately one
request per source per cycle. **An auditor should review whether the Draft
Sharks and IDP Show authenticated fetches comply with those services'
terms** — this was not reviewed in-session.

---

## 8. Autonomous Agent System

### Live agents at time of writing

| Agent | Purpose | Branch | Status |
|---|---|---|---|
| league-intel | WS-E; normalization; LI-8 sim | `claude/league-intel-foundation` (21) | working |
| roster-intel | WS-J roster engine | `claude/ws-j-roster-intel` (24) | working |
| partner-fit | WS-J partner + target engines | `claude/ws-j-partner-fit` (29) | working |
| reviewer | audit → now owns trade-engine fixes | `claude/ws-j-trade-engine-fixes` (6) | working |
| e2e | E2E suite; now `useAuth` fix | `claude/auth-proxy-fixes` | working |
| design custodian | ds/, R5, `/league` migration | `claude/redesign-r5-polish` (7) | working |

Plus ~12 completed agents from earlier phases.

### Scheduled workflows

| Workflow | Trigger | Status |
|---|---|---|
| `scheduled-refresh.yml` | 2h cron | ✅ working |
| `intel-refresh.yml` | daily 09:10 UTC | ✅ **fixed today** |
| `deploy.yml` | push + dispatch | ✅ working |
| `refit-hill-curves.yml` | weekly | ✅ **[from summary]** |
| `pr-validation.yml` | PR | ✅ — format gate + **blocking changed-files lint** |
| `e2e.yml` | nightly | ⚠️ **expected-red** until #554 lands |
| `health-check.yml`, `smoke-test.yml`, `prod-e2e-smoke.yml`, `public-league-warmup.yml`, `audit-*.yml`, `weekly-narratives.yml` | various | not audited today |
| VPS systemd timers: `dynasty-dlf-fetch`, `dynasty-idpshow-fetch` | 2h | ✅ (Cloudflare/CAPTCHA workarounds) |

### Coordination problems observed **today**, with evidence

1. **Reviewer had no worktree.** Spawned read-only, then given
   implementation work; it edited the *shared* main checkout and switched
   its branch. Caused two false "uncommitted changes" alarms.
   **Fix: give any agent that may write a worktree at spawn.**
2. **Force-push on a shared branch.** The E2E agent force-updated a SEL
   commit on R3 (`0c579ea4` → `21222e76`, identical trees). Harmless but
   against policy §2.6.
3. **A revert that undid another agent's fix.** The custodian's
   `be183b17` reverted the `journey.js` defuse and was pushed; the E2E
   agent re-landed it. Detected only because the E2E agent reported it.
4. **Duplicate independent work.** Two agents independently fixed the same
   `critical-smoke` red. One fix was never committed, so no conflict — by
   luck.
5. **Cross-agent messaging failure.** The E2E agent could not resolve the
   custodian's name and had to route through me.

### Overlap / consolidation candidates

- `suggestions.py` vs `finder.py` — **deliberately kept separate** (see §6).
- Three IDP position sets: `angle.py:34` (14), `finder.py:50` (3),
  `monte_carlo.py:343` (5). Contradicts `CLAUDE.md`'s single-source-of-truth
  claim.
- `/rosters` vs planned `/gameplan` — resolved as a **scope split**, not a
  merge (league-comparison vs roster-depth). The genuinely duplicated piece
  is `TradeTargetsCard`.

---

## 9. Work Actually Completed

**Nothing in this section is merged to `main` unless stated.**

### `claude/this-keeps-happening-ly8avw` (mine) — 20 commits, PR #553

| File | Change | Tested |
|---|---|---|
| `docs/ORCHESTRATION.md` | canonical plan; §2b evidentiary rule; merge queue; ops incident | docs |
| `docs/roster-trade-intelligence/AUDIT.md` | WS-J registration; F-1→F-7 | docs |
| `docs/league-intelligence/*` | MASTER_PLAN, SETTINGS_AUDIT, DECISIONS (ADR 001-009), STATUS, TASK_REGISTRY | docs |
| `.github/workflows/intel-refresh.yml` | **removed hardcoded domain fallback** | CI |
| `.github/workflows/prod-e2e-smoke.yml` | same | CI |
| `.github/workflows/public-league-warmup.yml` | same | CI |
| `src/api/ops_alerts.py`, `signal_alerts.py`, `source_health_alerts.py` | repointed alert links to new IP | ruff ✅ |
| `deploy/monitoring/uptime_check.sh` | `SITE_URL` default | bash -n ✅ |
| `deploy/apply_hardening.sh` | `NGINX_SITE` → service name | bash -n ✅ |
| `deploy/grafana/public-league-dashboard.json` | metrics URL | JSON valid ✅ |
| `deploy/nginx/*.conf` | **DO-NOT-APPLY warning**, directives untouched | n/a |
| `frontend/app/sitemap.js`, `robots.js` | origin fallback | build ✅ |
| 4 × `opengraph-image.js` | rebranded off lost hostname | build ✅ |
| 4 runbooks + `PRODUCTION_BOOTSTRAP.md` | purged stale IP | docs |

### Other branches (agent-owned, verified present)

| Branch | Commits | Key files |
|---|---|---|
| `claude/ws-j-roster-intel` | 24 | `src/roster_intel/{marginal,profiles,roster_source,window}.py` + 4 test modules |
| `claude/ws-j-partner-fit` | 29 | `src/roster_intel/partner.py`, `tests/roster_intel/test_partner.py` |
| `claude/ws-j-trade-engine-fixes` | 6 | `src/trade/{finder,suggestions}.py`, `CLAUDE.md`, `docs/.../F-6-finder-valuation-path.md` |
| `claude/league-intel-foundation` | 21 | `src/league_intel/*`, normalization, LI-7 axes |
| `claude/redesign-r5-polish` | 7 | `ds/Badge.jsx` (`Confidence`), R5 purge plan, UI spec |
| `claude/redesign-r3-surfaces` | — | PR #551 |
| `claude/redesign-r4-warroom` | — | PR #552 |
| `claude/e2e-r1-reconcile` | — | PR #554 |

### Pull requests

| PR | Content | CI | Merged |
|---|---|---|---|
| #550 | LI-1..LI-7 | ✅ | ❌ |
| #551 | Redesign R3 | ✅ | ❌ |
| #552 | Redesign R4 | ✅ | ❌ |
| #553 | orchestration docs | ✅ | ❌ |
| #554 | E2E suite | ✅ | ❌ |
| #556 | **IDP trade-finder fix** | 🔄 re-running | ❌ |

### Issues

- **#545** intel refresh — **resolved**, comment posted; **close blocked by
  GitHub API rate limit, still open**.
- **#555** auth/proxy defects — open, being worked.
- **#531** scheduled refresh — open, likely stale.

### Test results (as reported by agents / observed)

| Suite | Result |
|---|---|
| E2E, full stacked redesign | **149 passed / 0 failed / 29 gated skips** |
| vitest (R3/R4/ds) | 1188 passed |
| `tests/league_intel/` | 299 passed |
| `tests/roster_intel/` | 86 passed |
| `tests/roster_intel/test_partner.py` | 56 passed |
| trade suites | 265 (289 incl. FAAB) |
| Full pytest (LI-8 gate) | 3290 passed / 0 failed |
| Collected total | ~3,428 |

### Environment / external services

`PROD_PUBLIC_URL` (**set today**), `INTEL_REFRESH_TOKEN` (**rotated
today**), `DEPLOY_HOST/USER/PORT/SSH_PRIVATE_KEY/KNOWN_HOSTS`,
`JASON_LOGIN_PASSWORD`, `ALLOW_DEFAULT_LOGIN_DEV`, `E2E_TEST_MODE`,
`RATE_LIMIT_BYPASS_IPS`, `DRAFTSHARKS_EMAIL/PASSWORD`,
`SLEEPER_LEAGUE_ID`, `BASELINE_LEAGUE_ID`.

**Database migrations: none. There is no database.**

**Deployment results:** deploys green through the day (latest 15:48 UTC).
Production healthy on `169.58.50.224` — `has_data: true`, scrape 1.2h old.

---

## 10. Unfinished Work and Technical Debt

### Critical

| Item | Evidence |
|---|---|
| **No TLS in production.** Login credentials cross the network in plaintext | `https://169.58.50.224` does not respond |
| **`grant-ssh-access.yml` is a standing production-shell path** for anyone with repo access | user created via web UI; not yet deleted |
| **`useAuth` resolves *terminally* to unauthenticated after a 5s timeout, no retry** — strands a valid session on the anonymous shell for the page's life | #555 |
| **F-6: `finder.py` values assets off the raw scraper composite**, not `_compute_unified_rankings`, contradicting `CLAUDE.md`'s "one and only code path" | `docs/.../F-6-finder-valuation-path.md` |
| **Nothing is merged.** Six PRs, all unmerged | — |

### High

| Item | Notes |
|---|---|
| Backend page proxy serves anonymous shell to signed-in sessions | #555 |
| `/waivers`, `/news`, `/draft` missing from proxy route list | drifted 3× |
| `/league` SSR 7–19s against a 5s proxy timeout | #555 |
| `critical-smoke` red on `main` since R1 | fix only on #554 |
| **48 files still on `.card`**, 86 occurrences in `/league`+`/league-comparison`, using a hardcoded pre-redesign navy gradient | visible product seam once R2-R4 land |
| F-2: KTC-derived VA curve applied unchanged to IDPTC totals | no paired observation exists |
| Three divergent IDP position sets | contradicts `CLAUDE.md` |
| LI-6 blocked: no raw per-category projection source | Draft Sharks gives a point total under *their* scoring |
| TE axis blocked on paired-board evidence | axis ambiguity unresolved |

### Medium

Next dying under load (1 of 4 managed E2E runs, SIGKILL from outside,
correlates with process ownership); `_positional_coverage` fix moves
composites ≤0.46 (correct but weak); 6 duplicate rows + 40/666 join
failures in `data/ros/aggregate/latest.json`; health-check hook reads CSV
mtime instead of freshness stamps (false stale warnings every session);
`valueMode`/`VALUE_MODES` name collision in `/rosters` (fixed on branch);
two suppression-threshold revisions superseded.

### Low

`MoversPanel` rows non-focusable; focus restores to `document.body` on
unmounted opener; `waivers-smoke` vacuous first assertion (fixed);
orphaned `.panel*` CSS (~90 lines).

### Described in conversation but never implemented

The entire Trade Package Generator (multi-asset search, Pareto ranking),
trade explanation/pitch surface, unrealistic-trade rejection heuristics,
user controls, admin review tools, champion-challenger infrastructure,
historical backtesting, monitoring for the new engines, the `/gameplan`
surface, target position/player engines (in progress), and the continuous
recalibration schedule.

---

## 11. Contradictions and Unresolved Decisions

| # | Contradiction | Currently controlling |
|---|---|---|
| 1 | `CLAUDE.md` says both trade engines enforce a KTC top-150 filter | **Wrong about both.** Fixed on #556; engines deliberately differ |
| 2 | `CLAUDE.md` says `_compute_unified_rankings` is "the one and only code path" | **False** — `finder.py` uses a parallel board (F-6). Documentation wins on paper; code wins in production |
| 3 | `CLAUDE.md` names `name_clean.py` as the single source of position truth | **False for IDP** — three divergent sets |
| 4 | Integration window (Jul 29) vs "merge when ready" | **User's later instruction controls** |
| 5 | "Don't create PRs merely because a task exists" vs harness rule to always PR after push | Resolved: long-lived workstream PRs, not per-task |
| 6 | Internal model vs market rankings | Market is the **fairness anchor**; internal is the **edge**. Never presented as market consensus |
| 7 | TE premium: 1.592 → 1.320 → **~1.12** | Symmetric-endpoint ~1.12 controls; **unpublished** |
| 8 | Suppression: 15% (WS-E) vs over-correction (review) | **Resolved** — materiality + boundary proximity |
| 9 | Offense vs IDP treatment | Was **silently offense-only** in the finder; fixed on #556 |
| 10 | Autonomous development vs branch safety | Multiple violations (§8). Policy unchanged, enforcement weak |
| 11 | "Everything is ready" vs reality | **Nothing merged**; §10 lists 5 critical items |
| 12 | Page proxy: fix or delete | **OPEN — needs user decision** |
| 13 | R5 as "polish" | **Mis-scoped** — `.card` migration is a third of the app |

---

## 12. Claude's Self-Audit

Adversarial, as requested.

### Mistakes I made and had corrected

| # | My error | Who caught it | Consequence if unchecked |
|---|---|---|---|
| 1 | Called mixed-market summation "an addition with no defined meaning"; made normalization the gating dependency | reviewer | Workstream scoped around a P3 as if it were P1 |
| 2 | Proposed league trades (12 managers) as the normalization anchor; concluded sample size was binding | WS-E | Would have declared a solvable problem unsolvable. **The anchor — 475 paired players — was in data I already had** |
| 3 | Located F-1 on the counter side; that path needs `include_idp`, which the frontend never sends | reviewer | Fix would have landed on unreachable code |
| 4 | Suggested removing `finder.py`'s 0.88 haircut as "the likely fix" | reviewer | **Would have left single-source assets undiscounted** — a live distortion introduced by a fix |
| 5 | Quoted a `3.79` depth figure repeatedly; it was never `starters_per_team` and was already retired | WS-E | Propagated a wrong parameter into the premium narrative |
| 6 | Predicted full rosters would materially reduce fragility | roster-intel | Wrong; it barely moved |
| 7 | Told the user `idpTradeCalc` was 22h stale and treated it as an ops incident | myself | It was a **false positive** — the hook reads CSV mtime, meaningless after checkout |
| 8 | Claimed I had replaced a stale IP in a runbook; I had not, and it was in **five** places | myself, later | Told the user something false about my own work |
| 9 | Asserted the IP was "the decommissioned Hetzner box" without verifying | user | It was the live server's address at the time |
| 10 | Wrote a `printf "\n…"` that PowerShell mangled into literal `n` characters | myself, after a round trip | Created a variable named `nINTEL_REFRESH_TOKEN` |
| 11 | **Verified that with an unanchored `grep -c`**, which matched the substring and reported success | myself | A vacuous check, in the middle of a day spent cataloguing vacuous checks |
| 12 | Compared two `git show` outputs that both failed and got "identical" from two empty-string hashes | myself | Nearly reported a merge invariant as verified on no evidence |
| 13 | Counted `journey.js` conflicts by grepping context lines rather than conflict markers | myself | Reported "2 conflicts" for both branches; truth was 0 and 1 |
| 14 | Specified an order-guard test that is red when the code is *correct* | design custodian | Could only be written after the purge — i.e. after the landmine fired |
| 15 | Told the custodian to fold `valueMode` into the global toggle | custodian | **Would have produced silently wrong totals** — two `VALUE_MODES` both using key `"full"` |
| 16 | Decided per-position strength "moves" from `/rosters` to `/gameplan` | custodian | It can't — different denominators (league average vs own roster) |
| 17 | Started rewriting a 244-line production nginx config, referencing a snippet file that doesn't exist | myself | Would have been invalid nginx on a server the user can't easily debug |
| 18 | Suspected TEP double-counting for Fitzmaurice | news agent | False alarm; flag set and consumed correctly |

**That is eighteen corrections in one session, twelve of which I caught
myself and six of which required another agent or the user.** An auditor
should weight my unverified claims accordingly.

### Unsupported assumptions still in the system

- `SHARED_SCALE_ASSUMPTION` — IDPTC's internal offense↔IDP exchange rate is
  *correct*, not merely self-consistent. **Nothing validates it.**
- The TE reference endpoint assumes KTC's board targets a 2-FLEX superflex
  league.
- F-2 — the KTC VA curve applies to IDPTC totals.
- The `0.18` acceptance prior is an assumption, not a fit.
- `_PERCENTILE_REFERENCE_N = 500` clamping (deliberate, but unexamined
  today).

### Overengineering

- Five-plus confidence dimensions per value, when nothing consumes them yet.
- Three revisions of a suppression gate before the right question was asked.
- The orchestration doc has grown to a size where agents may not read it all.

### Underengineering

- **No database**, while proposing snapshot/versioning/champion-challenger
  infrastructure. An auditor should challenge whether JSON-on-disk survives
  §16 and §24 of the WS-J directive.
- No champion-challenger infrastructure exists despite being required.
- No backtesting harness.
- Agent coordination is prose in a markdown file, not enforced.

### Work that should be rewritten or removed

- `angle.py`'s two near-duplicate `_make_candidate` implementations.
- `finder.py`'s valuation path (F-6) — but as a deliberate recalibration,
  since `MIN_ASSET_VALUE`, `MAX_BOARD_LOSS`, `JUNK_THRESHOLD`,
  `ELITE_THRESHOLD`, `MULTI_FOR_ONE_MIN_RATIO` were tuned against
  composite-scale numbers.
- The backend page proxy — delete rather than fix.
- The health-check hook's staleness signal.

### Where I claimed more progress than existed

I told the user early on that the TE premium had "independent corroboration
from three methods." It did not — the vendor evidence is *published
uplifts* with controls absent by construction, and the shape agreement
survives while the level does not. I downgraded this twice, both times
after being pushed.

---

## 13. Recommended Next Steps (7 days)

Ordered per the requested priority: data/formula correctness → agent
coordination → core functionality → testing → performance → UI →
deployment.

### Day 1 — Correctness and merge the backlog

1. **Merge in dependency order:** #551 → #552 → #550 → #554 → #556 → #553.
   Verify the `journey.js` invariant before each redesign merge; expect one
   known safe conflict in `journey-trade.spec.js`.
2. **Delete `grant-ssh-access.yml`** (critical).
3. Close #545.
4. **Resolve the page-proxy decision** (fix vs delete).

### Day 2 — Formula correctness

5. **F-6 investigation** with before/after numbers on every threshold.
   This is the single highest-value correctness item outstanding.
6. Unify the three IDP position sets; correct `CLAUDE.md`.
7. Fix the `data/ros/aggregate` duplicate rows and 40/666 join failures.

### Day 3 — Agent coordination

8. Give every writing agent a worktree at spawn.
9. Make the ownership registry enforced, not documented.
10. Fix the health-check hook to read freshness stamps.

### Day 4-5 — Core functionality

11. Target position/player engines to completion.
12. Roster rollups + `playoff_sim` wiring.
13. Trade Package Generator on the corrected market path.
14. Rewire `angle.py` — **offer side first**.

### Day 6 — Testing and performance

15. E2E green on the merged stack; investigate the Next SIGKILL.
16. `/league` SSR 7–19s.

### Day 7 — UI and deployment

17. `/league` + `/league-comparison` `.card` migration (**re-scope R5**).
18. `/gameplan` surface.
19. **New domain + Let's Encrypt TLS.**

---

## 14. Questions for the Independent Reviewer

**Mathematics**
1. Is the symmetric-endpoint TE premium (~1.12) correct, and is the
   reference-endpoint assumption defensible?
2. Does the exact-path package strategy actually avoid the cross-market
   problem, or does it relocate it into `SHARED_SCALE_ASSUMPTION`?
3. Is a 5% materiality gate right, and should it be per-position given
   TE 0.895?
4. Is softmax over competitiveness × trajectory the right window model?
5. Is marginal-over-replacement the right strength definition for best ball,
   or should it be distributional?

**Code**
6. **F-6** — is the `finder.py` parallel valuation path as serious as
   recorded?
7. Is `_PERCENTILE_REFERENCE_N = 500` clamping distorting deep IDP?
8. Is α = 0.10 shrinkage justified for IDP and picks but not offense?
9. Does the 30% single-source haircut interact correctly with the new
   per-market gate?

**Architecture**
10. **Can JSON-on-disk support the versioning, snapshot and
    champion-challenger requirements, or is a database now mandatory?**
11. Should the three trade engines converge, or is the divergence correct?
12. Is `/gameplan` vs `/rosters` the right split?

**Process**
13. Given eighteen corrections in one session, is the agent architecture
    net-positive, or is it manufacturing work?
14. Is same-model review producing genuine independence?

**Legal**
15. Do the Draft Sharks and IDP Show authenticated fetches comply with those
    services' terms?

---

## 15. Source Appendix

### Key paths

```
server.py
src/api/data_contract.py        _compute_unified_rankings, _RANKING_SOURCES
src/api/league_registry.py
src/league_intel/{config,scorer,values,replacement,adjustment,calibration}.py
src/roster_intel/{marginal,profiles,roster_source,window,partner}.py
src/ros/{lineup,aggregate,team_strength,playoff_sim,pick_projection}.py
src/trade/{finder,suggestions,angle,monte_carlo,faab_recommender,faab_contention}.py
src/intel/{crawler,aggregate,store,service}.py
src/news/service.py, src/news/providers/
src/identity/, src/utils/name_clean.py       POSITION_ALIASES
frontend/lib/dynasty-data.js                 RANKING_SOURCES, buildRows
frontend/components/ds/, useAuth.js
tests/e2e/helpers/journey.js                 SEL, NAME
config/leagues/registry.json
config/league_intel/sleeper_league_snapshot_2026-07-26.json
config/{idp_calibration,source_staleness}.json
config/weights/pick_year_discount.json
```

### Constants referenced

`_TE_BLANKET_NON_NATIVE_MULTIPLIER` 1.15 · `_TE_BLANKET_NATIVE_MULTIPLIER`
1.10 · `_SINGLE_SOURCE_VALUE_RETENTION` 0.30 · `SINGLE_SOURCE_DISCOUNT`
0.88 · `_MAD_PENALTY_LAMBDA` 0.0 · `_PERCENTILE_REFERENCE_N` 500 · α 0.10 ·
`DEFAULT_GATE_PCT` 5.0 · `BOARD_TOP_N_FILTER` 150 · acceptance prior 0.18

### External URLs

- Sleeper API — `https://api.sleeper.app/v1/`
  (league `1312006700437352448`; 2025 `1180092661344120832`)
- Production — `http://169.58.50.224` (**no TLS**)
- **Lost domain** — `riskittogetthebrisket.org` → `178.156.148.92`
  (third-party controlled)
- KeepTradeCut, IDP Trade Calculator, DynastyDaddy, FantasyCalc, OTCFFB,
  Draft Sharks, DLF, Flock Fantasy, IDP Show (Substack), FantasyPros,
  Yahoo, Fantasy Navigator (`fantasy-navigator-latest.onrender.com/ranks`),
  PlayForKeepsDynasty (Supabase `pfk_dynasty_rankings`)

### User requirements that materially shaped the design

> "I want claude constantly debugging and working on the site even when I am asleep."

> "Never invent precision, data access, licenses, historical projections, statistical relationships, or completed integrations."

> "I do not need the site to remain fully functional… optimize for the quality and completeness of the final integrated system."

> "Yes we removed the TE premium in the scoring but now we start 2 TE's… I just want to account for the scarcity."

> "Remember most of the sites that have TEP baked in are usually accounting for some sort of TEP scoring, not two tight ends."

> "TE's CAN start in flex, I just don't know how to measure how many are flex worthy. Maybe look at historical data with our league's scoring?"

> "that is one way you can help measure scarcity for each position, by using the number that are actually on each team in the sleeper league at any given moment"

> "We dont own the riskittogetthebrisket domain anymore."

> "Run all agents until everything is ready to go, and everything is pushed and merged… None of them should be idle."

> "Do not present low-confidence output as precise." / "The purpose is to identify defensible, actionable advantages—not manufacture trade wins."

---

## Section completion status

| § | Section | Status |
|---|---|---|
| 1 | Original Objective | ✅ complete |
| 2 | Chronological History | ⚠️ complete for the visible session; early stages **[from summary]** |
| 3 | Architecture | ✅ complete, with merge status per component |
| 4 | Formulas | ⚠️ **PARTIAL BY DESIGN** — verified / documented / unverified, explicitly separated |
| 5 | Roster Analysis | ✅ complete for what exists; gaps named |
| 6 | Trade Recommendation | ✅ complete for what exists; most of the directive is spec-only |
| 7 | External Inspiration | ✅ complete |
| 8 | Agent System | ✅ complete, with coordination failures evidenced |
| 9 | Work Completed | ✅ complete, verified against the repository |
| 10 | Unfinished Work | ✅ complete, prioritized |
| 11 | Contradictions | ✅ complete |
| 12 | Self-Audit | ✅ complete — 18 corrections listed |
| 13 | Next Steps | ✅ complete |
| 14 | Reviewer Questions | ✅ complete |
| 15 | Appendix | ✅ complete |
