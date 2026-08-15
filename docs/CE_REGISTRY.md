# Competitive Expansion (CE) Registry — the single canonical identifier namespace

**Status:** CANONICAL ACTIVE — ONE CONCEPT, ONE CANONICAL OWNER applied to identifiers
**Established:** 2026-08-14 by the post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`)
**Supersedes as a registry:** the alternate CE-01…CE-21 assignments that were authored on PR #816

---

## Why this file exists

A CE identifier is a name. Two documents that use the same name for different capabilities do not merely
disagree — they make every citation of that name ambiguous, including citations written before either document
existed. That is what happened here, and it was the single highest-severity finding of the post-B audit.

Measured on 2026-08-14: **18 of 22 CE identifiers meant two different capabilities** depending on which record
the reader opened. `main`'s registry said CE-19 is the Waiver Market / FAAB Market Ledger — which is what binding
owner decision 65 and issue #830 both cite by number. PR #816's registry said CE-19 is Personal Rankings. Under
that branch, decision 65's referent silently changed meaning. Three more branch-side collisions moved Draft Room,
Lineup Intelligence, Market Pulse, Share Renderer and Personal Rankings onto other numbers.

The branch was also inconsistent with itself: its §6.8 used `main`'s meaning of CE-20 (Game Day Command Center)
while its §10 list used another.

**This file is now the only place a CE identifier is defined.** Anything else that lists CE ids mirrors this file
and loses to it.

---

## Resolution rule applied

1. **`main`'s registry is canonical.** It is the product of the owner's 2026-08-12 reconciliation, it is the
   registry every binding owner decision on `main` cites by number, and it is mirrored consistently across the
   Feature Inventory §12/§13.5, the Master Product Plan §4.9, the Product Backlog Spec and the competitive
   research record.
2. **Capabilities were remapped by CONTENT, not by number.** Where PR #816 described a capability `main` already
   owns under a different id, the entry moved to `main`'s id.
3. **Genuinely new capabilities were given new identifiers (CE-22…CE-29)** rather than being dropped. This is the
   zero-loss half of the resolution: eight capabilities that existed only inside the colliding namespace now have
   a home.
4. **Provenance travels with every remapped entry.** `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` records the
   branch's original tag inline beneath each reconciled heading.

---

## Canonical registry

### CE-01 … CE-21 — established scope (unchanged from `main`)

| ID | Capability | Detailed spec |
|---|---|---|
| **CE-01** | Market Trade Ledger / Trade Database | `docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` |
| **CE-02** | Pick Forecast | `docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` §6.1 |
| **CE-03** | Manager Scout / Manager Intelligence | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §7 |
| **CE-04** | Dynasty Command Center | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| **CE-05** | Trade Desk | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md`; constraints via `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` |
| **CE-06** | Dynasty Portfolio / Exposure | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| **CE-07** | Market ADP | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| **CE-08** | Projections & Stats Hub | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| **CE-09** | League Replacement Value / PAR / WAR | `docs/PLAYER_IMPACT_WAR_MVP_SPEC.md` |
| **CE-10** | Share Renderer / Team Cards | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §9.10 |
| **CE-11** | Sleeper Action Gateway | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §13.7 |
| **CE-12** | Lineup Intelligence | `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` C3 |
| **CE-13** | Draft Room | `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` C4 |
| **CE-14** | Market Pulse | `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` D1 |
| **CE-14A** | Personal Rankings Overlay | `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` E4/E5 |
| **CE-15** | Portfolio Trade Campaign — no automatic bulk spam | `docs/OWNER_FEATURE_SPEC_APPENDIX_2026-08-13.md` F3 |
| **CE-16** | Trade Polls — optional/future | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` |
| **CE-17** | League Format / Utilization Lab | `docs/competitive/COMPETITIVE_EXPANSION_DYNASTY_DADDY_ADDENDUM.md` |
| **CE-18** | Trade Trees / Asset Lineage | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §9.8 |
| **CE-19** | Waiver Market / FAAB Market Ledger | `docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md` |
| **CE-20** | Game Day Command Center | `docs/GAME_DAY_PROBABILITY_SPEC.md` |
| **CE-21** | Dynasty Season Recap / Wrapped | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §9.8 |

### CE-22 … CE-29 — minted 2026-08-14 to preserve capabilities that had no non-colliding home

| ID | Capability | Origin | Owner-approval state |
|---|---|---|---|
| **CE-22** | Starter-relevance filter | PR #816 appendix A3 (was tagged CE-13) | Approved scope |
| **CE-23** | Roster-age windows | PR #816 appendix A4 (was tagged CE-01) | Approved scope |
| **CE-24** | League longevity / history | PR #816 appendix A5 (was tagged CE-02) | Approved scope |
| **CE-25** | Compare multi-select | PR #816 appendix B4 (was tagged CE-07) | Approved scope |
| **CE-26** | Cross-league trade / portfolio view | PR #816 appendix B7 (was tagged CE-10) | Approved scope |
| **CE-27** | League keeper / privacy mechanics | PR #816 appendix B8 (was tagged CE-11) | Approved scope |
| **CE-28** | User feedback / polling | PR #816 appendix E6 (was tagged CE-14A) | **NOT OWNER-APPROVED — see below** |
| **CE-29** | Push notifications | PR #816 appendix F1 (was tagged CE-08) | Existing implementation (VAPID live) |

**CE-28 carries no owner approval and must not be built on the strength of this row.** It exists in exactly two
lines in the entire repository, both authored on one branch, both inside the systematic reassignment above, with
a three-line body that is a methodology guardrail rather than a feature specification — no surface, no trigger,
no data contract, no acceptance criteria, no approval date. It is registered here so the idea is not lost, and
flagged so it cannot be mistaken for approved scope. Promoting it requires an owner decision
(`docs/C_SERIES_SCOPE_MANIFEST.md`, row `OD-06`).

---

## Rules for new code and new documents

- **Do not define a CE identifier anywhere but this file.** Other documents may cite ids; they may not assign them.
- **The next free identifier is CE-30.** Never reuse a retired one.
- **A capability that already has a canonical owner does not get a CE id merely because a competitor has the
  feature.** CE ids name product capabilities in the competitive-expansion roadmap; they are not a second
  ownership registry. The canonical-owner map lives in `docs/C_SERIES_SCOPE_MANIFEST.md`.
- **`scripts/check_planning_integrity.py` enforces uniqueness** — one id, one capability, checked in CI. A second
  contradictory registry now fails the build instead of surviving for a month.

## Mirrors that must agree with this file

- `docs/MASTER_PRODUCT_PLAN.md` §4.9
- `docs/OWNER_FEATURE_INVENTORY.md` §12 and §13.5
- `docs/C_SERIES_SCOPE_MANIFEST.md`

If a mirror disagrees, this file wins and the mirror is the defect.
