# Risk It To Get The Brisket — Current Execution Plan

**Status:** CANONICAL SEQUENCING / AUTHORIZATION RECORD  
**Last reconciled:** 2026-08-12  
**Companion:** `docs/MASTER_PRODUCT_PLAN.md`

This file answers **what work should happen next**. It does not define long-term product intent; that lives in the Master Product Plan, Feature Inventory, and Product Backlog Spec.

> A feature being approved in the long-term plan does **not** authorize beginning it here.

---

# 1. CURRENT FOUNDATION PROGRAM

## Completed / accepted

### B4 — W30-F023 percentile-tail saturation

- VERIFIED FIXED / ACCEPTED.
- Canonical tail saturation boundary: **904**.
- PR #805 merged.
- No Hill promotion/refit authorized or performed.
- Do not reopen B4 absent new evidence.
- Future nonblocking safeguard: advisory detection if effective observed source rank exceeds the canonical boundary, rather than silently accumulating 905+ saturation.

### B5 — W06 canonical player identity

- PR #806 merged.
- W06-F001 fixed — ghost-row creation path.
- W06-F004 fixed — ID override precedence/merge semantics.
- W06-F007 fixed — directory index hoisted for batch resolution.
- W06-F009 fixed — SleeperId alias-token handling.
- W06-F002 refuted by executable evidence; retired near-name rule must not be re-enabled merely to satisfy the old finding.
- Residual explicitly noted by B5: ghost-row repair takes effect on the next scrape; do not falsely claim a historical/current board changed until that path actually runs.

### B6 — W18 league-configuration correctness

- **MERGED AND VERIFIED.** PR #810 merged 2026-08-13T11:16:43Z as merge commit
  `5c699afe6f325a7dab34f8c413a00f85c0bb7bf6`, whose second parent is the exact CI-validated head
  `e453889aed0c1f3ca0378c408d7b8b37985e3309` (run 31688810982, 24/24 steps). Deployed by run
  31694791900. Scope below is the authorization it was executed against.
- Production verification recorded in `docs/master-site-audit/B_SERIES_EXECUTION_LEDGER.md` §B7.0.
  The load-bearing live observation is public and unauthenticated: `/api/draft-capital` answers
  `rookieSource: "none"` for `dynasty_new` while keeping all 80 of its real picks, and
  `ours_filtered` for `dynasty_main` — the gate withholding a value it cannot justify without
  refusing the board. Independently, the two leagues' live Sleeper cards still fingerprint
  `sf1:b7ad1575925091f6` vs `sf1:82a5f8ef2bfdb098` (35 of 48 shared keys differ) under one
  identical `scoringProfile` label, both recorded against the current NFL season.
- **W18-F001 fixed.** Cross-league ranking reuse is decided by a factual `scoringFingerprint` over the league's actual scoring card, not by the `scoringProfile` label. `scoringProfile` keeps its existing config/model meaning and consumers. Unproven identity fails closed, in both directions. The nominal owner `leagues_share_scoring()` had **zero production callers** — six scattered comparisons in `server.py` (four of them fail-open on a missing loaded label) now route through one gate.
- **W18-F002 fixed.** The cross-league Sleeper merge has a name and an owner (`sleeper_overlay.merge_cross_league_sleeper_block`). League-specific fields (`scoringSettings`, `rosterPositions`, `leagueSettings`) come from the requested league's own config — published by the overlay from the league object it already fetched — or are left ABSENT with `sleeperDataReady: false`. NFL-wide maps are still reused.
- Measured on the shipped configuration (`docs/master-site-audit/evidence/W18/b6-validation.json`): both live leagues share the label and differ on 35 of 48 shared scoring keys. `/api/data` and `/api/terminal` for `dynasty_new` now 503 instead of serving `dynasty_main`'s board; `/api/draft-capital` stays 200 and drops only its 40 foreign-priced rookies (`rookieSource: "none"`), keeping all 80 of that league's real picks.
- **Operational requirement:** `data/leagues/scoring_<sleeperLeagueId>.json` must exist for a league to be provably compatible. The post-scrape warm pass writes it every cycle; on a cold deploy run `scripts/fetch_league_scoring.py` once, or cross-league requests fail closed until the first scrape.
  This requirement is now **verifiable**: dispatch the read-only `Scoring Snapshot Diagnostics`
  workflow (`.github/workflows/scoring-snapshot-diagnostics.yml`). It exists because the state was
  otherwise unobservable — `data/leagues/` is gitignored and is not among the paths
  `scheduled-refresh.yml` force-adds, and both fail-closed branches ("proven different scoring" and
  "no verified snapshot") produce byte-identical public responses. The same run reports whether the
  canonical board-history recorder is scheduled.
- Architecture record: `docs/master-site-audit/evidence/W18/B6_SCORING_IDENTITY_DESIGN.md`.
- W18-F003 was NOT touched — it remains B7.

### B7 — realized-points correctness

- **MERGED AND VERIFIED.** PR #820 (`af761fc`). Validated head `0875da5`, run 31738127750.
- W18-F003 fixed; W18-F004 shipped with it by necessity.

### B8 — privacy / distribution / refresh boundary

- **MERGED.** PR #821 (`053f9e5`), 2026-08-14T03:09:30Z. Validated head `0cc95b9`, run 31764984203.
- W01-F010 and the W22 family closed on BOTH distribution channels (HTTP and git).

### B9 — canonical player value semantics

- **MERGED.** Two units.
- **B9a** — `offenseOnlyRankDerivedValue` retired: a second full run of
  `_compute_unified_rankings` whose output three engines substituted into `displayValue` /
  `modelValue` per TRADE. 491 of 507 comparable rows disagreed, up to 21.87%. Canonical
  board byte-identical after removal; contract build 0.62 s → 0.49 s. Closes W29-F001
  (W29-F002's overlay half closed by #822).
- **B9a** — the 1–9999 scale is now a contract the validator enforces. The last path that
  let the rejected league-aware methodology own `rankDerivedValue` published 10,160 on the
  real factor set and 12,471 at the cap; `apply_valuation_factors` deleted.
- **B9b** — threshold semantic units. W29-F005 closed: the "Seller cash-out" predicate
  compared 0–9999 against 0–100 and could not fire for any of 1,093 rows; it now fires for
  19. Four thresholds registered in `config/thresholds.json` with `unit` + `derivedFrom`.
  **Partial by design** — four BOARD-RELATIVE constants are classified and registered but
  not converted, because each changes which assets a recommendation surface offers. See
  `docs/valuation/THRESHOLD_UNIT_REGISTRY.md`.

---

### B10 — source independence / anti-circularity · IN PROGRESS

- **T1 (scraper KTC dedupe) — SATISFIED, nothing to remove.** The authorising premise
  ("ktc ≈1.3 + ktcSfTep ≈1.0 → ≈2.3 vs IDPTC 1.0") does not describe canonical
  aggregation: there is no `ktc` entry in `_RANKING_SOURCES`, the KTC family votes
  canonically once through `ktcSfTep`, and all 21 sources are weight 1.00. The `1.3` is
  `LEGACY_COMPOSITE_SITE_WEIGHTS` in `Dynasty Scraper.py`, scoped to `_composite`.
- **T2 (declare provenance) — MERGED.** PR #825 (`e015814`). 19 of 21 sources declared no
  family, so each counted as independent. **21 source keys → 13 provider families.**
  FantasyPros votes twice on 299 rows (`fantasyProsFitzmaurice` is one expert 100%
  contained in the `fantasyProsSf` consensus panel, r = 0.9297), Flock on 70, DLF on 52.
  Board provably inert: 0 values moved, 0 ranks changed.
- **T3 (family-aware aggregation) — NOT STARTED.** This is the unit that moves values: it
  decides how many votes a family gets and re-derives n-sensitive aggregation against the
  independent family count. Needs an immutable pre-change baseline and the movement
  envelope check before anything ships.

### B11 — confidence semantics · NOT STARTED

Reconnaissance recorded in the ledger. `_compute_confidence_bucket` reads exactly two
inputs — source count and percentile spread. Freshness, coverage, independence and
missingness are not inputs at all. **The monotonicity defect is confirmed and strict:**
removing `dlfSf` raises the bucket on 26 rows and lowers it on 0. The recorded "192 of 683"
figure is larger than today's measurement and should not be quoted without re-measuring.

---

---

# 2. NEXT AUTHORIZED FOUNDATION SCOPE

## B6 — League configuration / league-context correctness

**Scope chosen by owner:**

- **W18-F001** — scoring-profile identity is hand-authored rather than validated/derived from actual league scoring settings.
- **W18-F002** — cross-league Sleeper overlay can combine requested-league teams with another league's scoringSettings/rosterPositions/leagueSettings and incorrectly stamp `sleeperDataReady:true`.

Treat these as one league-configuration root-cause family.

Required posture:

1. reproduce both defects on current code/current host data;
2. establish RED coverage for the actual erroneous contracts;
3. identify the canonical owner of league scoring/config identity;
4. repair the root cause, not specific league-name exceptions;
5. scoring-profile equivalence must reflect actual scoring configuration, not merely matching strings;
6. no requested-league Sleeper block may contain another league's config fields and claim ready;
7. validate every configured league against its own host settings;
8. measure downstream behavior on `/api/data`, rankings/overrides, roster/team consumers, trade/waiver/draft contexts as relevant;
9. run normal broad gates and exact-head CI;
10. STOP for owner review.

**Explicit B6 non-scope:** W18-F003 realized-points scoring correctness. Do not mix the scoring-engine repair into B6.

---

# 3. QUEUED NEXT — NOT AUTOMATIC AUTHORIZATION

## B7 — Realized-points correctness

W18-F003 belongs here as an independent scoring-engine root cause. It has an NFL Week 1 urgency and should follow B6 without unnecessary delay, but B6 completion does not itself authorize starting B7.

Known W18-F003 evidence to revalidate on current HEAD includes:

- reception-distance scoring rules not represented correctly;
- renamed nflverse mappings for interception/sack/fumble-lost data;
- missing kicker scoring;
- requirement that every nonzero league scoring key be mapped or explicitly declared uncoverable rather than silently scored as zero.

Also reconcile the owner-requested individual special-teams requirement (`kr_yd`, `pr_yd`, supported `st_*`) when the realized-scoring work reaches the appropriate scope. Player special-teams scoring and DST `def_*` scoring must remain distinct.

## Subsequent foundation direction

The broader dependency direction remains:

- **B8** security/public-boundary correctness;
- **B9** canonical individual 1–9999 value-scale semantics/normalization;
- **B10** source independence / anti-circularity / leave-one-out;
- **B11** confidence semantics;
- then canonical C-series foundations such as Team Strength, Team Weakness, Acquisition History, historical value snapshots, package methodology, and stable pick identity according to dependencies/evidence.

Exact boundaries must be confirmed against current findings and owner authorization at each checkpoint rather than inferred from this shorthand.

---

# 4. PRODUCT WORK THAT MUST NOT PREEMPT FOUNDATIONS

The following are approved future scope but are **not authorized merely by being listed**:

- Public League Experience v3 implementation;
- Brisket Honors / Awards & Honors v2 implementation;
- Market Trade Ledger / Real Trade Market Value;
- Pick Forecast;
- Manager Scout;
- Command Center / Trade Desk / Portfolio;
- Analyst Intelligence podcast + YouTube expansion;
- Universal Player Profile expansion;
- Game Day Command Center;
- Share Renderer;
- PAR/Stats/ADP/Draft Room/Lineup Intelligence;
- competitive CE-01–CE-21 expansion;
- large X analyst feed;
- adaptive source weighting.

They may be read during foundation work to avoid architectural contradictions, but not opportunistically implemented.

---

# 5. SAFE HOTFIXES / OWNER DEFECTS

Owner-requested live defects such as the Admin `fmtPassExpiry` crash, temporary-password end-to-end repair, and Trade Calculator UX/correctness defects remain real work. Schedule them at a safe product-hotfix checkpoint or when one directly blocks the active phase; do not mix unrelated UI/product changes into a tightly scoped model/root-cause pass.

---

# 6. EXECUTION UPDATE RULE

At every owner-approved checkpoint:

1. update completed/accepted phase state here;
2. record the exact next authorized scope only after owner decision;
3. leave later approved product scope in `MASTER_PRODUCT_PLAN.md` rather than copying it here;
4. never let a stale phase statement in `ARCHITECTURE_HANDOFF.md`, an old audit roadmap, or a session capture override this file;
5. if current code/evidence disproves this execution state, reconcile the document before beginning another phase.

This file should stay short enough that a new implementation session can understand the current sequence in minutes.