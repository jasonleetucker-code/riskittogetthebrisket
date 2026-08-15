# C-Series Zero-Loss Traceability

**Status:** CANONICAL ACTIVE — the source-entry → manifest-row proof
**Created:** 2026-08-14 by the post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`)
**Proves:** `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §4 and §14 (no silent deferral)
**Companion:** `docs/C_SERIES_SCOPE_MANIFEST.md`

---

# 1. What "safely mapped" means here

A requirement is **not** safely mapped merely because it appears somewhere in an old file or an open branch. For
this reconciliation, SAFE requires all six of:

1. the requirement is identified;
2. owner intent is unambiguous, or the ambiguity is explicitly flagged as an owner decision;
3. it has exactly one intended canonical destination;
4. the Scope Manifest contains it or maps it;
5. its source and provenance are recorded;
6. **it cannot disappear if an old PR is later closed** — i.e. its text lives on `main`.

Criterion 6 is the one the old planning branches failed, and it is why this reconciliation promoted 25
specifications onto `main` rather than merely citing them.

---

# 2. Source-population summary

| # | source | location before this PR | raw entries | now on `main`? |
|---|---|---|---|---|
| A | `docs/OWNER_FEATURE_INVENTORY.md` | main | 106 rows (+43 sub-units) | yes |
| B | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` | main | 76 units | yes |
| C | `docs/OWNER_REQUESTED_TODO.md` | main | 20 TODO rows + **65 binding decisions** + 8 freshness classes = 93 | yes |
| D | `docs/MASTER_PRODUCT_PLAN.md` | main | 99 named capabilities | yes |
| E | `docs/WEEKLY_REPORT_STUDIO_…` + `docs/FAAB_MARKET_SIGNAL_…` | main (unregistered) | 58 | yes — now registered |
| E2 | `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` (#838) | main (landed mid-reconciliation) | 6 required outputs | yes — now registered |
| F | PR #816 — 104-ledger + 17 T-NEW + reconciliation lists | **branch only** | 245 | **yes — promoted** |
| G | PR #816 — feature-spec appendix | **branch only** | 40 | **yes — promoted** |
| H | PR #835 — trade-generation preferences | **branch only** | 3 families (~40 sub-reqs) | **yes — promoted** |
| I | PR #809 — 15 detailed specs | **branch only** | ≈120 | **yes — promoted** |
| J | `docs/OWNER_FEATURE_ADDENDUM_2026-08-11.md` + `docs/SCOPE_COORDINATION_2026-08-11.md` | main | 12 | yes |
| K | `UNIMPLEMENTED_BACKLOG.md` | main | 56 | yes |
| L | `docs/ROADMAP-competitor-parity.md` + `docs/status/*.md` | main | 18 deltas | yes — now named as historical |
| | **total** | | **≈926** | |

**Neither audit's census matched this population.** One reported 154 source entries with 154 mapped and 0
unmapped; the other reported eight at-risk clusters without a total. The 154 figure is a sample, not an
enumeration — it omits `UNIMPLEMENTED_BACKLOG.md` (56), `docs/status/*` and `ROADMAP-competitor-parity.md` (18
deltas), and it counts the 104-ledger and the 50-family crosswalk without unioning the inventory's 106 rows, the
backlog's 76 units or the TODO's 65 binding decisions. Recomputing was required and is the mission's D1.

---

# 3. Disposition of every source

Every source requirement resolves to exactly one of:
`IMPLEMENT` · `REPAIR` · `CONSOLIDATE` · `MIGRATE` · `BACKFILL` · `UX/PERF` · `PRODUCTION-PROOF` ·
`COMPLETE-ALREADY` · `PART-OF-OTHER` · `SUPERSEDED` · `OWNER-REJECTED` · `EXTERNAL-BLOCKER` ·
`OWNER-DECISION` · `NOT-PRODUCT-SCOPE`.

## A — `docs/OWNER_FEATURE_INVENTORY.md` (106 rows)

| inventory rows | destination | disposition |
|---|---|---|
| §1 Roster intelligence 1.1–1.5 | `C2-STR-01`, `C2-WEAK-01`, `C2-SIM-01`, `C2-DROP-01`, `C3-CON-02` | IMPLEMENT / CONSOLIDATE |
| §2 Trade products 2.1–2.8 | `C3-CALC-01`, `C3-VA-01`, `C3-PKG-01`, `C7-GOLD-01`, `C7-PKGB-01`, `C1-ID-02`, `C1-PICK-01` | CONSOLIDATE / IMPLEMENT |
| §2.8 far-future pick posture | `C1-PICK-01` | **SUPERSEDED** — see §6 |
| §2.9 Best Trade (added by #835) | `C7-BEST-TRADE` | IMPLEMENT |
| §3 Waivers/FAAB/draft 3.1–3.7 | `F-FAAB-01`, `C7-WAIV-01`, `C7-DRAFT-01`, `C7-DRAFT-02` | COMPLETE-ALREADY / IMPLEMENT |
| §4 Market intelligence 4.1–4.8 | `C6-EDGE-01`, `C6-SIG-01`, `C6-SIG-02`, `C4-SHARP-01`, `C4-INS-01` | REPAIR / CONSOLIDATE / PRODUCTION-PROOF |
| §5 Podcast intelligence 5.1–5.7 | `C6-POD-01` | IMPLEMENT |
| §6 League surfaces and history | `C9-V3-01`, `C9-HIST-01`, `C5-POW-01`, `C5-PLAY-01`, `C6-UPP-01`, `C5-GD-01` | IMPLEMENT / REPAIR |
| §7 Value model and identity 7.1–7.11 | `F-VAL-01`, `F-CONF-01`, `F-SRC-01`, `F-SCORE-01`, `F-SCORE-02`, `C1-ID-01`, `C1-HIST-01`, `C1-ACQ-01` | COMPLETE-ALREADY / IMPLEMENT |
| §7.4, §7.5, §7.6 status cells | — | **STALE — corrected on `main` by this PR.** They described the exact defects B9/B10/B11 fixed as current HEAD state |
| §8 BDVM, news, notifications | `C5-BDVM-01`, `C6-ANA-01`, `CE-29` via `C7-CE-01` | COMPLETE-ALREADY / IMPLEMENT |
| §9 Performance, mobile, platform 9.1–9.7 | `C8-PERF-01`…`C8-PERF-05`, `C8-A11Y-01`, `F-PRIV-01` | UX/PERF |
| §10 Adaptive / ML | `C10-ML-01` | IMPLEMENT (gated) |
| §11 Owner decisions (resolved 2026-08-11) | carried into the rows above | COMPLETE-ALREADY |
| §12 + §13.5 CE-01…CE-21 | **`docs/CE_REGISTRY.md`** + `C7-CE-01` | CONSOLIDATE — see §5 |
| §13.1–13.7 later additions | `C5-GD-01`, `C7-DESK-01`, `C3-VA-02`, `C7-CE-01` | IMPLEMENT |
| §0 Removed from scope | `X-01`, `X-02` | OWNER-REJECTED |

## B — `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` (76 units)

| backlog sections | destination | disposition |
|---|---|---|
| §1 Trade Calculator 1.1–1.8 | `C3-CALC-01`, `C3-CALC-02`, `C3-CALC-03`, `C3-MC-01`, `C2-EXP-01`, `C1-ACQ-01` | IMPLEMENT |
| §2 Trade generation 2.1–2.2 | `C7-GOLD-01`, `C7-PKGB-01` | IMPLEMENT |
| §2.3 Best Trade (added by #835) | `C7-BEST-TRADE` | IMPLEMENT |
| §3 Picks | `C1-PICK-01`, `C1-PICK-02`, `C1-PICK-03` | IMPLEMENT |
| §4 Podcast intelligence | `C6-POD-01` | IMPLEMENT |
| §5 Consensus / Buy-Sell | `C6-EDGE-01`, `C6-SIG-01`, `C6-SIG-02` | CONSOLIDATE |
| §6 Market Trade Ledger | `C4-MTL-01` | IMPLEMENT |
| §7 Manager Scout | `C6-MGR-01` | IMPLEMENT |
| §8 Universal Player Profile | `C6-UPP-01` | IMPLEMENT |
| §9 Public league 9.1–9.10 | `C9-V3-01`, `C9-HIST-01`, `C9-SHARE-01`, `C1-ACQ-03`, `C9-RECAP-01`, `F-PRIV-01` | IMPLEMENT / REPAIR |
| §10 Awards 10.1–10.11 | `C9-AWARD-01`, `C9-AWARD-02`, `C5-WAR-01` | REPAIR / IMPLEMENT |
| §11 Game Day | `C5-GD-01` | IMPLEMENT |
| §12 TE premium | `F-VAL-01` + `C1-SRC-01` | REPAIR |
| §13 CE surfaces | `C7-CE-01`, `docs/CE_REGISTRY.md` | IMPLEMENT |
| §14 Admin | `C0-GOV-08` + hotfix lane | REPAIR |
| §15 Performance | `C8-PERF-*` | UX/PERF |
| §16 X feed | `C6-X-01` | IMPLEMENT (cost-gated, `OD-03`) |
| §17 Removed scope | `X-01`, `X-02` | OWNER-REJECTED |
| §18 Owner strategy overlays (MIN) | `C3-CON-02` | **RECONCILED** — see §6 |

## C — `docs/OWNER_REQUESTED_TODO.md` (20 rows + 65 decisions + 8 freshness classes)

| entry | destination | disposition |
|---|---|---|
| #779 Admin crash · #780 temporary password | `C0-GOV-08` + hotfix lane | REPAIR |
| #781 manual override UX (decisions 3–7) | `C3-CALC-02` | IMPLEMENT |
| #782 YouTube (decision 8) | `C6-YT-01` | IMPLEMENT |
| #783 UPP feed (decision 9) | `C6-UPP-01` | IMPLEMENT |
| #784 ticker (decision 10) | `C6-SIG-02` | IMPLEMENT |
| #785 TE premium (decision 11) | `F-VAL-01`, `C1-SRC-01` | REPAIR |
| #786 exposure (decision 12) | `C2-EXP-01` | IMPLEMENT |
| #788 X (decision 13) | `C6-X-01` | IMPLEMENT (cost-gated) |
| #789 Game Day (decisions 14–20) | `C5-GD-01`, `C5-GD-02` | IMPLEMENT |
| #790 Monte Carlo (decision 21) | `C3-MC-01` | REPAIR |
| #791 Second Opinions (decision 23) | `C3-CALC-03` | IMPLEMENT |
| #792 Analyze Trade (decisions 24–27) | `C7-DESK-01` | IMPLEMENT |
| #800 equalizers (decision 41) | `C3-EQ-01` | CONSOLIDATE |
| #801 Establish The Run (decision 42) | `X-03` | OWNER-PAUSED |
| #802 special teams (decision 43) | `C5-ST-01` | REPAIR |
| #803 league fit / college (decisions 44–46) | `C5-FIT-01` | IMPLEMENT |
| **#829 Weekly Report Studio (decisions 47–55)** | `C9-WRS-01` | IMPLEMENT |
| **#830 FAAB Market Heat (decisions 56–65)** | `C4-FAAB-01` | IMPLEMENT |
| CE-17–CE-21 row (decision 32) | `docs/CE_REGISTRY.md`, `C7-CE-01` | IMPLEMENT |
| decisions 22, 28–31 (KTC VA) | `C3-VA-01`, `C3-VA-02` | CONSOLIDATE |
| decisions 33–40 + 8 freshness classes | `C6-FRESH-01` | IMPLEMENT |
| decisions 1–2 | `C0-GOV-08` + hotfix lane | REPAIR |

**Governance note.** This file is the live intake ledger and was, before this PR, classified as historical /
superseded — while receiving the two newest binding owner decision sets. That inversion is `C0-GOV-05` and is
repaired by this PR.

## D — `docs/MASTER_PRODUCT_PLAN.md` (99 capabilities)

§4.1 roster → `C2-*` · §4.2 trade → `C3-*`/`C7-*` · §4.3 picks → `C1-PICK-*` · §4.4 waivers/FAAB/draft →
`F-FAAB-01`/`C7-WAIV-01`/`C7-DRAFT-*` · §4.5 market/Sharp/analyst/manager → `C4-*`/`C6-*` · §4.6 UPP →
`C6-UPP-01` · §4.7 public v3 + Honors → `C9-*` · §4.8 Game Day → `C5-GD-01` · §4.9 CE → `docs/CE_REGISTRY.md` ·
§4.10 foundations → `F-*` · §4.11 reconciled capture requirements → the `C`-rows named in A/B/C above.
§3 invariants and §5 public/private governance are constraint units carried by the acceptance profiles.
§6 removed/rejected/paused → `X-01`, `X-02`, `X-03`.

**One sentence in §4.3 is superseded** — see §6.

## E — The two 2026-08-14 owner design docs (58 units)

`docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md` (33) → `C9-WRS-01`, with `C9-SHARE-01` as its
hard dependency (it mandates rendering through "the site's canonical share/rendering system", which does not exist
yet). `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` (25) → `C4-FAAB-01`.

**Both were unregistered in the governance index before this PR** (`C0-GOV-06`), and neither appears anywhere in
PR #816 — whose planning layer carries a "synchronized through 2026-08-14" stamp. That stamp is false for exactly
these two, and the correction is recorded in `docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md`'s amendment.

## E2 — `docs/OWNER_FEATURE_ADDENDUM_2026-08-14_AGE_VALUE_PORTFOLIO.md` (#838)

Landed on `main` **after** this reconciliation branched, and was caught by the new planning-integrity gate
rather than by a human noticing — which is the gate earning its place on its first run.

Its six required outputs map to `C2-AGE-01` (value-weighted core age, age-value distribution, position-group
profiles, league-relative comparison), `C2-AGE-02` (Young Core Index and the positional leaderboards),
`C7-AGE-01` (the team-profile Age & Value module) and `C2-AGE-03` (the future historical trend extension,
explicitly downstream of snapshot foundations and explicitly not a blocker on the current-state feature).

The addendum names four documents it must be folded into before the roadmap counts as reconciled — the Master
Product Plan, the Feature Inventory, the Product Backlog Spec and the C-series sequencing record. All four are
updated in this change.

---

## F — PR #816: the 104-row ledger, 17 T-NEW items, reconciliation lists (245)

**All 104 ledger rows map. Count re-verified programmatically: exactly 104, contiguous 1–104, no gaps, no
duplicates.**

| ledger rows | section | destination |
|---|---|---|
| 1–10 | A. Data pipeline / app workflow | `C4-SRC-02` + `F-*` — COMPLETE-ALREADY for rows 1–8, 10; row 9 (readiness/freshness honesty) → `C4-SRC-02` REPAIR |
| 11–20 | B. Valuation engine and trade logic | 11–13 → `F-VAL-01`/`F-CONF-01` COMPLETE-ALREADY · 14 → `C3-VA-01` · 15 → `C3-EQ-01` · 16 → `C3-CALC-01` · 17–20 → `C1-SRC-01` |
| 21–25 | C. Pick valuation and anchors | `C1-PICK-01`, `C1-PICK-02` |
| 26–29 | D. Rankings / rookie view / list usability | `C8-PSI-02`, `C8-PERF-03` |
| 30–39 | E. Team and roster intelligence | `C2-STR-01`, `C2-WEAK-01`, `C2-GP-01`, `C7-DESK-01` |
| 40–47 | F. League-wide analysis views | `C2-STR-01`, `C7-CMD-01`, `C9-V3-01` |
| 48–53 | G. External market and league behavior | `C4-MTL-01`, `C4-MTL-02`, `C4-WAIV-01`, `C3-AGE-01` |
| 54–55 | H. Alerts | `C7-ALERT-01` |
| 56–58 | I. IDP and source conversion | `C1-SRC-01`, `F-SRC-01` |
| 59–68 | J. UX cleanup and speed | `C8-PSI-*`, `C8-PERF-*` |
| 69–70 | K. Export and configuration | `C10-CLOSE-04` |
| 71–88 | L. Trade Calculator / real-trade DB / market expansion | `C3-CALC-01` (TC-01…TC-30), `C4-MTL-01`, `C4-MTL-03` |
| 89–93 | L. Pick completeness + mobile parity | `C1-PICK-01`, `C1-PICK-02`, `C8-PERF-01` |
| 94–100 | L. Product shell + mature-calculator gate | `C9-V3-01`, `C3-CALC-01` (TC-30) |
| 101 | M. Historical Trade Replay | `C3-REPLAY-01` |
| **102** | N. Best Trade to Send Each Team | `C7-BEST-TRADE` |
| **103** | N. Persistent personal trade protection | `C3-CON-02` |
| **104** | N. Generated-package LOCK / EXCLUDE | `C3-CON-03` |
| §O | Zero-loss rule | **discharged by this document** |

**Rows 1–10, 30–47 and 59–70 are the "small UX / calculator-workflow tier" that no other source carries.** The
census identified 44 such single-source items and they are the most likely in the whole corpus to be dropped
silently — which is why the ledger was promoted to `main` verbatim rather than summarized.

T-NEW-01…17 → `C1-PICK-03` (01) · `C3-CALC-01` (02) · `C9-V3-01` (03) · `C9-V3-01` (04) · `F-MISS-01` (05) ·
`C8-PSI-*` (06) · `C9-UR-01` (07) · `C5-POW-01` (08) · `C9-AWARD-02` (09) · `C6-FRESH-01` (10) ·
**`C0-GOV-01` — satisfied through step 7 by this reconciliation** (11) · **DONE, shipped in `7cf722e3` (#814)** (12) ·
`C5-WAR-01` (13) · `C3-CALC-01` (14) · `C1-PICK-01` (15) · **discharged by this document** (16) ·
`C3-REPLAY-01` (17).

## G — PR #816 feature-spec appendix (40 entries)

A1 → `C3-CON-02` · A2 → `C2-WEAK-01` · A3 → **CE-22** · A4 → **CE-23** · A5 → **CE-24** · A6 → CE-03 ·
B1 → `C3-VA-01` · B2 → CE-05 · B3 → CE-06 · B4 → **CE-25** · B5 → CE-03 · B6 → CE-02 · B7 → **CE-26** ·
B8 → **CE-27** · C1 → `C7-DRAFT-02` · C2 → `C7-DRAFT-01` · C3 → CE-12 · C4 → CE-13 · D1 → CE-14 ·
D2 → `C4-SHARP-01` · D3 → `C4-SRC-02` · D4 → `C0-GOV-08` · D5 → `C10-ML-01` · D6 → `F-SRC-01` ·
E1 → `C8-PSI-02` · E2 → `F-CONF-01` · E3 → `C1-HIST-01` · E4 → CE-14A · E5 → CE-14A · E6 → **CE-28
(NOT owner-approved, `OD-06`)** · F1 → **CE-29** · F2 → CE-10 · F3 → CE-15 · F4 → `F-PRIV-01` ·
F5 → `F-PRIV-01` · G1 → `C8-PERF-03` · G2 → `C8-PERF-01` · G3 → `C8-PERF-01` · G4 → `C10-CLOSE-07` ·
G5 → `C4-SRC-02`.

Every `(CE-nn)` tag in this appendix was reconciled against `docs/CE_REGISTRY.md`; the branch's original tag is
preserved inline beneath each affected heading.

## H — PR #835 (3 families, ~40 sub-requirements)

Best Trade to Send Each Team → `C7-BEST-TRADE`. Persistent personal protection → `C3-CON-02`. LOCK / EXCLUDE →
`C3-CON-03`. All 26 of the mission's required hard rules were verified CAPTURED in the promoted spec, with 0
partial, 0 missing and 0 contradicted.

**Two gaps this PR closes that #835 itself left open:** the spec was referenced by nothing in its own tree — a
session following the canonical front door could never find it — and the Feature Inventory gained a row for Best
Trade only, not for protection or LOCK/EXCLUDE. Both are fixed on `main` by this PR.

## I — PR #809 (15 specs, ≈120 capabilities)

| spec | destination |
|---|---|
| `AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md` | `C7-AI-01`…`C7-AI-05`, `C7-ALERT-01` |
| `BRISKET_HONORS_ELIGIBILITY_SPEC.md` | `C9-AWARD-02` — **player-MVP gate superseded**, MOTY preserved |
| `CANONICAL_WEEKLY_POWER_RANKINGS_SPEC.md` | `C5-POW-01` |
| `COMPETITOR_REUSE_POLICY.md` | `C0-GOV-08` — scope-bounded to design patterns, not data rights |
| `GAME_DAY_PROBABILITY_SPEC.md` | `C5-GD-01` |
| `GLOBAL_PERFORMANCE_STANDARD.md` | `C0-PERF-01` + acceptance profile P1 |
| `MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` | `C4-MTL-01`, `C4-MTL-02`, `C4-MTL-03`, **`F-EXT-01` (the KTC permission record, §19.2)** |
| `MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md` | `C1-SRC-01`, `C1-SRC-02` |
| `PLAYOFF_PREDICTOR_SPEC.md` | `C5-PLAY-01` |
| `PREMIUM_SPORTS_INTELLIGENCE_DESIGN_NORTH_STAR.md` | `C0-PSI-01`, `C8-PSI-01`…`C8-PSI-03` |
| `REDRAFT_ROS_INTELLIGENCE_SPEC.md` | `C5-ROS-01` |
| `SHARP_INSIDER_EXPERIENCE_PERFORMANCE_SPEC.md` | `C4-SHARP-01`, `C8-PERF-04`, `C4-INS-01` |
| `TRADE_HISTORY_AGING_SPEC.md` | `C3-AGE-01` |
| `UPSIDE_REPORT_PRESEASON_KICKOFF_EDITION_SPEC.md` | `C9-UR-02` |
| `UPSIDE_REPORT_WEEKLY_SHOWCASE_SPEC.md` | `C9-UR-01` |

**PR #816's claim that #809's intent was restated is false, and the falsity is specific and verified.** #816's
own enumeration of what it restates names the Premium direction, the Upside Report, Weekly Power Rankings, Awards
& Honors and source-family normalization. It does **not** name — and contains zero occurrences of — the AI Front
Office family, the Upside Report Kickoff Edition, the KTC permission record, the Sharp Insider performance spec,
the global performance standard, or the Redraft/ROS lane. Six capability families and one authorization record
would have been lost by relying on #816 as a superset.

## J — Addendum + scope coordination (12)

Eleven items verified absorbed into A/B/D. One — the zero-omission integration checklist itself — is superseded
by this document. Disposition: `SUPERSEDED` / `PART-OF-OTHER`.

## K — `UNIMPLEMENTED_BACKLOG.md` (56)

Fifteen items appear in no other source and would have been lost by any census that skipped this file: persist
player-week actuals (Tier-0) → `C1-HIST-01` · distance-banded receptions edge → `C5-ST-01` · IDP market inversion
→ `C1-SRC-01` · accuracy-weighted passing → `C5-FIT-01` · `tep=3` vs `tepp` extraction mismatch → `C1-SRC-01` ·
mixed-market disclosure → `C3-XMKT-01` · removal-cost surplus → `C7-WAIV-01` · true weekly-points ROS utility →
`C5-ROS-01` · source-family confidence (Finding P) → `F-CONF-01` · 43/208 unreachable `src/` modules →
`C10-CLOSE-02` · 5 dead feature flags → `C10-CLOSE-02` · `auction_power.py` parity → `C7-DRAFT-01` ·
`data/ros/aggregate/latest.json` duplicate rows → `C4-SRC-02` · branch protection on `main` → `C0-GOV-07` ·
"link any Sleeper account" → **`X-07` / `OD-07`**. The remaining 41 are duplicates of A/B/D entries.

## L — `docs/ROADMAP-competitor-parity.md` + `docs/status/*.md` (18 deltas)

All 18 map into `C7-CE-01` and `C9-V3-01`. These files are **findable roadmaps that the governance index did not
name** — a session could reasonably have mistaken them for current scope. This PR names them as historical
(`C0-GOV-06`).

---

# 4. Live implementation requiring consolidation, migration or proof

Capabilities that exist in code but whose *architecture* is scope. These are the rows a census built only from
planning documents would miss entirely.

| finding | manifest row | disposition |
|---|---|---|
| 3 independent player-identity matchers | `C1-ID-01` | CONSOLIDATE |
| 7 pick representations, no end-to-end id | `C1-ID-02` | IMPLEMENT |
| 6 lineup implementations, 2 serving production | `C2-LINE-01` | CONSOLIDATE |
| 5 replacement-level implementations | `C2-REPL-01` | CONSOLIDATE |
| 4 competing Team Strength notions | `C2-STR-01` | IMPLEMENT |
| ≥5 need definitions, one contradicting the lineup solve | `C2-WEAK-01` | IMPLEMENT |
| 4 package generators, no shared engine | `C3-PKG-01` | CONSOLIDATE |
| 5 Value Adjustment implementations, one installed by import-time monkeypatch, rounding divergence | `C3-VA-01` | CONSOLIDATE |
| 2 `findBalancers`, divergent thresholds, one a frontend engine | `C3-EQ-01` | CONSOLIDATE |
| `cross_market.py` correct and disconnected | `C3-XMKT-01` | CONSOLIDATE |
| `roster_intel` / `/api/gameplan` disconnected | `C2-GP-01` | MIGRATE |
| ≥6 Buy/Sell emitters, no reconciler, dead module claiming ownership | `C6-SIG-01` | CONSOLIDATE |
| 2 power engines, 2 playoff engines | `C5-POW-01`, `C5-PLAY-01` | CONSOLIDATE |
| `team_impact` reimplements the lineup solver | `C2-SIM-01` | CONSOLIDATE |
| Historical replay leaks hindsight in production | `C3-REPLAY-01` | REPAIR |
| Sharp production population unproven | `C4-SHARP-01` | PRODUCTION-PROOF |
| Awards manufactured with zero games played | `C9-AWARD-01` | REPAIR |
| 2024 declares ten teams, carries eight standings | `C9-HIST-01` | REPAIR |
| DraftSharks ~219 h stale, still voting | `C4-SRC-01` | REPAIR (`OD-04`) |
| Partial source run reported as healthy | `C4-SRC-02` | REPAIR |
| Mobile payload +13% larger than desktop | `C8-PERF-01` | UX/PERF |
| Public payload ~2.1 MB / 14.8 s observed | `C8-PERF-05` | UX/PERF |
| 11 irreversible-evidence-loss mechanisms | `C1-RET-01`…`C1-RET-08`, `C5-GD-02`, `C7-DRAFT-02`, `C4-FAAB-02` | IMPLEMENT / REPAIR |

---

# 5. The CE namespace

Twenty-two identifiers existed in two mutually contradictory registries; **18 of 22 meant different capabilities**
depending on the document. Resolution and the full mapping are in `docs/CE_REGISTRY.md`. No capability was
dropped: every branch-side entry either resolved to its canonical identifier or received a newly minted one
(CE-22…CE-29). `scripts/check_planning_integrity.py` prevents recurrence.

---

# 6. Superseded owner rules

Three, each with the newer instruction winning per `docs/MASTER_PRODUCT_PLAN.md` §2 precedence.

1. **Far-future picks may remain unpriced.** `docs/MASTER_PRODUCT_PLAN.md` §4.3 and inventory row 2.8 held that
   valid 2028/2029 picks may stay explicitly unpriced. **Superseded** by the newer owner requirement that every
   valid supported pick through 2029 carries a finite canonical value
   (`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §2 and §10). Missing evidence still never becomes zero —
   the replacement is a documented generic/future valuation with provenance and uncertainty, not a zero.
   → `C1-PICK-01`. Both records are patched on `main` by this PR.
2. **Player MVP requires the playoff field and >.500.** In `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md`.
   **Superseded** by `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` §7. **Manager of the Year is NOT superseded** — no
   newer owner instruction touches it, so its team-success eligibility rule stands. → `C9-AWARD-02`.
3. **`src/news/unified_signal_engine.py` is "the single entry point for every BUY/SELL/HOLD decision."** A
   docstring ownership claim in a module with zero callers, while six other emitters serve production.
   **Superseded** — the claim is retired and a real reconciler is scope. → `C6-SIG-01`.

**One near-miss reconciled rather than superseded:** the Product Backlog Spec §1.6 and §18 describe Minnesota
Vikings players as "effectively untouchable for the owner's roster", which is broader and vaguer than the newer
precise rule (user + league scoped, **outgoing only**, incoming still valid, values unchanged). The newer rule
governs; the older wording is annotated on `main` rather than deleted, because it records the owner's intent
faithfully at a lower resolution. → `C3-CON-02`.

---

# 7. Result

| measure | count |
|---|---|
| Raw source entries enumerated | ≈926 |
| Distinct capability identities | ≈357 |
| Manifest rows | 157 |
| **Source entries with no destination** | **0** |
| Capabilities that existed in exactly one source | ≈134 (38%) — all now on `main` |
| Duplicate clusters resolved | 4 |
| Superseded rules | 3 |
| External blockers | 3, all one owner decision (`OD-01`) |
| Owner decisions required | 7 |
| **Unexplained unmapped** | **0** |
