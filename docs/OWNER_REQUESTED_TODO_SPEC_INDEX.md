# Chase Upside — Owner To-Do Specification Index

**Status:** BINDING COMPANION TO `docs/OWNER_REQUESTED_TODO.md`  
**Date:** 2026-08-13

`OWNER_REQUESTED_TODO.md` remains the compact durable tracking ledger. This file prevents a short row in that ledger from being mistaken for a complete implementation prompt.

## Rule

Before implementing any owner-requested item, Claude must read:

1. the matching row in `OWNER_REQUESTED_TODO.md`;
2. the matching detailed section in `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` or the older `OWNER_PRODUCT_BACKLOG_SPEC.md`;
3. any feature-specific canonical spec;
4. `EXECUTION_PLAN.md` to determine whether the work is authorized now;
5. current code/production evidence.

If the detailed behavior is still ambiguous after that, **stop for owner clarification rather than inventing product policy**.

A feature is not “specified” merely because its name exists in the to-do list.

---

# Detailed spec map

| Owner to-do / feature family | Detailed specification |
|---|---|
| Admin `fmtPassExpiry` crash | `OWNER_REQUESTED_TODO.md` binding decisions + reconciliation §4.31 |
| Temporary-password/pass generator | `OWNER_REQUESTED_TODO.md` + reconciliation §4.31 |
| Trade manual value edits / Reset Values | `OWNER_REQUESTED_TODO.md` + reconciliation §4.8 |
| YouTube Dynasty Intelligence | reconciliation §4.20 + Podcast architecture §4.19 |
| UPP unified intelligence/news | reconciliation §4.22–4.23 |
| Homepage Consensus ticker | reconciliation §4.17 |
| TE premium methodology audit | `OWNER_REQUESTED_TODO.md`; feed result into canonical valuation/league-fit owners, not a new value engine |
| NFL-team exposure | reconciliation §4.11 |
| X analyst feed | reconciliation §4.21 |
| Game Day Command Center | reconciliation §6.8 |
| Trade Monte Carlo audit | reconciliation §4.8 + binding Monte Carlo decisions in `OWNER_REQUESTED_TODO.md` |
| Trade Second Opinions | reconciliation §4.8 + `OWNER_REQUESTED_TODO.md` |
| Analyze Trade / Trade Desk | reconciliation §4.8–4.10 and §6.7 |
| Trade equalizer suggestions | reconciliation §4.8 |
| ETR source research | owner-paused in `OWNER_REQUESTED_TODO.md`; no implementation until explicit resume |
| Individual special-teams scoring | reconciliation §4.5; B7 scope |
| Player-specific scoring fit / prospect translation | existing backlog + reconciliation §7 model governance |
| CE-01–CE-21 competitive expansion | reconciliation §10; reconcile through canonical owners |
| Team Strength | reconciliation §4.6 |
| Team Weakness | reconciliation §4.7 |
| Trade Finder / Suggestions / Golden Upgrades / Package Builder | reconciliation §4.9 |
| 3-team trades | reconciliation §4.12 |
| Waivers / FAAB / Perfect Waivers / Dropability | reconciliation §4.13 |
| Perfect Draft / Draft Room | reconciliation §4.14 |
| Draft Capital / current Pick Projector | reconciliation §4.15 |
| Consensus Edge | reconciliation §4.16 |
| Sharp Tracker / Sharp Roster % / Ledger / Insider | reconciliation §4.18 |
| Podcast Intelligence | reconciliation §4.19 |
| Public League Experience | reconciliation §4.24 |
| Playoff Predictor | reconciliation §4.28 |
| Franchise / Acquisition History | reconciliation §4.29 |
| BDVM / fundamentals | reconciliation §4.30 |
| Compare / personalization / personal rankings | reconciliation §4.32 |
| Push / personalized feed | reconciliation §4.33 |
| Premium Sports Intelligence | reconciliation §5 |
| The Upside Report | reconciliation §6.2 |
| Weekly Power Rankings | reconciliation §6.3 |
| Awards & Honors | reconciliation §6.4 |
| Market Trade Ledger / Real Trade Market Value | reconciliation §6.5 |
| Manager Scout | reconciliation §6.6 |
| Command Center / Trade Desk / Portfolio | reconciliation §6.7 |
| Share Renderer | reconciliation §6.9 |
| PAR / Stats / ADP / Utilization | reconciliation §6.10 |
| League Format / Utilization Lab | reconciliation §6.11 |
| Trade Trees / Asset Lineage | reconciliation §6.12 |
| Waiver / FAAB Market Ledger | reconciliation §6.13 |
| Dynasty Season Recap / Wrapped | reconciliation §6.14 |
| ML / adaptive weighting / challenger lifecycle | reconciliation §7 |

---

# Newly added durable owner to-dos from the 2026-08-12/13 reconciliation

These are binding even if the older compact ledger has not yet assigned them a GitHub issue number.

## T-NEW-01 — Canonical Owned Future Pick Projection & Valuation

**Status:** PLANNED / C-REPLAN DEPENDENCY-GATED  
**Priority:** major canonical foundation/product enabler

Implement **one** owned-pick projection/value engine with stable real-pick identity, original-franchise landing logic, probability distributions over draft slots, expected canonical slot value, horizon-aware uncertainty, actual draft-order rules, near-term Monte Carlo, future-team-strength methodology, immutable trade-time snapshots, current-vs-trade value, Trade Calculator integration, Draft Capital integration, backtesting/calibration, and human-governed model promotion.

**Full binding spec:** `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` §6.1.

Do not implement as a second scale beside canonical pick values and do not keep the current simplistic Pick Projector as a conflicting long-term answer.

## T-NEW-02 — Trade Calculator Generic Pick Quantities

**Status:** TODO / safe product-correctness checkpoint

Generic hypothetical picks must support unlimited quantity on both sides with quantity-aware serialization and downstream math. Real owned league picks remain unique and non-duplicable.

**Full binding spec:** reconciliation §4.8, “Generic-pick quantity correctness.”

## T-NEW-03 — Public League Manual Sleeper Sync / Freshness

**Status:** PLANNED / post-foundation product UX

Add a prominent `Sync Sleeper / Refresh League Data` action using the existing public-league forced-refresh path, current-section re-fetch, explicit Syncing/Updated/Failed state, LKG preservation, `generatedAt` freshness display, 30–60 s cooldown/debounce plus server dedupe, and no global-scraper trigger.

**Full binding spec:** reconciliation §4.25.

## T-NEW-04 — Authenticated Top-Level League Navigation

**Status:** TODO / shell/navigation requirement

Authenticated desktop/mobile must expose one-action top-level **League** navigation to canonical `/league`, preserving session and avoiding duplicate public/authenticated league implementations. Must survive Premium migration.

**Full binding spec:** reconciliation §4.26.

## T-NEW-05 — `teamAssignment` Missing-Data-as-Zero Correctness

**Status:** TODO / production correctness

Intermittent degraded/cold snapshot state currently can surface HTTP-success `assignments: []`. Introduce an explicit unavailable/degraded/not-ready contract (plus LKG where defensible) so missing season/roster data does not masquerade as legitimate zero assignments.

**Full binding spec:** reconciliation §4.27.

## T-NEW-06 — Premium Sports Intelligence Migration

**Status:** APPROVED DIRECTION / MIGRATION-GATED

Direction A of the Chase Upside Design Lab is the permanent visual north star unless the owner changes it. Do not treat this as a generic recolor or shadcn reskin. Rankings is first reference route, UPP second, after the explicit migration gate.

**Full binding spec:** reconciliation §5.

## T-NEW-07 — The Upside Report

**Status:** PLANNED / dependency-gated

Build the deterministic weekly Interestingness Engine + immutable weekly report artifacts answering “What was actually interesting about this week in our league?”, with exact best-ball Game Changer re-solves, replacement-relative Player Impact, waiver marginal impact, upset/bad-beat/escape semantics, AI narrative only over deterministic facts, and public/private separation.

**Full binding spec:** reconciliation §6.2.

## T-NEW-08 — Canonical Weekly Power Rankings

**Status:** PLANNED / consolidate existing engines

Create one current-season Power engine distinct from Team Strength, Playoff Predictor, and Standings; consolidate current competing engines; validate the candidate multi-component model with rolling-origin no-lookahead evaluation.

**Full binding spec:** reconciliation §6.3.

## T-NEW-09 — Awards & Honors

**Status:** PLANNED / dependency-gated

Objective institutional awards using realized lineup VORP/replacement baselines, explicit eligibility, postseason/championship awards, MOTY vs GMOTY separation, top races, immutable historical methodology, and no fabricated retro inputs.

**Full binding spec:** reconciliation §6.4.

## T-NEW-10 — Analyst Intelligence Stance/Freshness Taxonomy

**Status:** REQUIRED METHODOLOGY REFINEMENT

Preserve `STASH / SPECULATIVE BUY` separately from true BUY conviction; preserve SLEEPER vs STASH semantics, contextual price/roster triggers, same-analyst thesis dedupe, take-type/event/season-aware freshness, and inactive historical analysis that may remain visible without continuing to vote.

**Full binding spec:** reconciliation §4.16 and §4.19–4.20.

## T-NEW-11 — B→C Complete Replanning Gate

**Status:** BINDING FUTURE EXECUTION GATE

After B11: **STOP**, put Claude in Plan Mode, completely rewrite the C-series from actual repo/product state, reconcile every current/planned/new feature in detail, optimize dependencies/parallelism/consolidation/PR boundaries, then obtain Jason + ChatGPT approval before C1.

**Full binding spec:** reconciliation §8 and `EXECUTION_PLAN.md` hard gate.

## T-NEW-12 — Post-Incident Watchdog `infinity` False-Negative

**Status:** IMMEDIATE NARROW RELIABILITY FOLLOW-UP BEFORE B6 RESUMES

Production observed `NextElapseUSecMonotonic=infinity` while the watchdog oneshot was actively executing. Fix the verifier so legitimate executing-service `infinity` can pass only when live systemd evidence proves the recurring monotonic timer contract remains configured; inactive/failed/no-schedule `infinity` must still fail closed.

**Full binding spec:** reconciliation §11.2.

This is post-incident reliability work. It does **not** reopen the formally closed FD/resilience incident.

---

# Maintenance rule

When the owner materially changes a feature, do not merely add another one-line row. Update the detailed spec source and this index if the canonical pointer changes. The goal is that a fresh Claude Code session can recover **what the owner actually meant** without relying on conversational memory.
