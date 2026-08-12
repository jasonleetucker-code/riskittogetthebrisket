# Chase Upside — Premium Sports Intelligence Design North Star

**Status:** OWNER-APPROVED PERMANENT PRODUCT / DESIGN DIRECTION  
**Owner decision date:** 2026-08-12  
**Authority:** Newest explicit owner instruction; supersedes older visual-direction choices where they conflict.  
**Implementation status:** Visual direction approved. Production migration NOT yet authorized as a whole-application rewrite.

---

## 1. PERMANENT DESIGN DECISION

Chase Upside will migrate to the **Premium Sports Intelligence** visual system represented by **Direction A** of the Chase Upside Design Lab.

This is the permanent design north star unless Jason explicitly changes the decision later.

Reference prototype:

`https://chase-upside-design-lab.qcv6rxwgqc.chatgpt.site/`

Reference areas:

- Rankings
- Player Profile
- Mobile
- Design System

The other explored concepts are no longer competing directions. Isolated ideas may be borrowed when they improve the product, but Premium Sports Intelligence is authoritative for the overall visual and experiential language.

---

## 2. PRODUCT FEEL

The production site should feel like:

> **A premium football personnel and market-intelligence system built for serious dynasty managers.**

Core qualities:

- premium professional sports identity;
- editorial authority;
- front-office credibility;
- dense but calm information;
- strong typography;
- restrained application chrome;
- data-first composition;
- sophisticated player presentation;
- selective, purposeful player imagery;
- strong numerical hierarchy;
- tabular numerals;
- thin rules and separators;
- minimal radii;
- almost no decorative shadow;
- disciplined color;
- substantial information without visual chaos;
- visible speed;
- an experience that makes the user feel better informed than the other managers in the league.

The product remains an application, not a literal sports-news site.

---

## 3. ANTI-GOALS

Do not translate this direction into another generic AI/SaaS dashboard.

Explicitly avoid:

- excessive rounded cards;
- cards nested inside cards;
- large border radii;
- pill badges everywhere;
- default shadcn styling;
- default Tailwind dashboard styling;
- glassmorphism;
- purple/blue AI gradients;
- glowing borders;
- unnecessary shadows;
- decorative blobs;
- generic Lucide-icon saturation;
- every number in its own tile;
- giant empty areas;
- marketing-page headings inside the application;
- hiding useful information to manufacture whitespace;
- treating every desktop table row as a card;
- merely recoloring the current interface;
- copying the prototype superficially without adopting its hierarchy and information philosophy.

Typography, alignment, spacing, rules, hierarchy and table structure should perform most of the organizational work.

---

## 4. RELATIONSHIP TO THE CURRENT R0/R1 DESIGN SYSTEM

The repository already contains a substantial design-system and shell foundation documented as a **"War-room terminal"** direction (`docs/DESIGN-SYSTEM.md`, `frontend/app/tokens.css`, `frontend/app/ds.css`, `frontend/components/ds/*`, shell/navigation work).

That existing visual direction is now **superseded where it conflicts with Premium Sports Intelligence**.

This does NOT mean the underlying engineering should be discarded blindly.

Potentially reusable infrastructure includes:

- semantic-token architecture;
- accessibility contracts;
- DataTable behavior;
- movement/confidence semantics;
- shared modal/drawer/form primitives;
- command/search architecture;
- route-focus and keyboard behavior;
- responsive shell mechanics;
- public/private route gating;
- chart accessibility and semantic-color discipline;
- loading/error/stale/empty-state infrastructure;
- performance-aware component design.

Potentially superseded visual decisions include, subject to migration audit:

- terminal-first visual identity;
- mono-as-default UI typography;
- terminal-specific density choices;
- current accent/color philosophy where it conflicts with Direction A;
- current surface/panel treatment;
- any existing component styling that still reads as terminal/SaaS/AI rather than Premium Sports Intelligence.

**Do not throw away correct behavior merely because its current styling is no longer authoritative.** Separate behavioral contracts from presentation before replacing presentation.

---

## 5. TIMING CLASSIFICATION

### 5.1 BEGIN NOW — NO-REGRET PREPARATION

Allowed now, even while core architecture/feature work continues:

1. Preserve this decision in canonical planning records.
2. Inventory every major route/surface and classify its migration complexity.
3. Inventory shared UI primitives and identify which behavior is reusable vs visually superseded.
4. Identify repeated legacy patterns, one-off tables, filters, player rows, stat blocks, navigation variants and page shells.
5. Identify generic SaaS / AI-looking patterns that must eventually disappear.
6. Separate business/data logic from presentation when an active feature edit already touches tightly coupled code.
7. Prevent new features from creating new one-off visual systems.
8. Document semantic information priorities for rankings, players, trades, market, Sharp/Insider, league, Game Day, draft and waiver surfaces.
9. Document responsive/mobile information priorities.
10. Create a route-by-route migration map and explicit legacy-retirement plan.
11. Avoid spending major effort polishing visual patterns known to be temporary.
12. Preserve performance budgets and accessibility contracts as redesign invariants.

This phase is **audit/preparation**, not a production reskin.

### 5.2 BEGIN WHEN PREREQUISITES ARE READY — DESIGN-SYSTEM FOUNDATION

Start the real Premium Sports Intelligence foundation when most of these are true:

- canonical player identity is stable;
- rankings/value pipelines are substantially consolidated;
- league configuration/scoring identity is canonical and production-safe;
- major repeated presentation components are inventoried;
- application shell/routing/navigation architecture is understood;
- major performance defects are being solved architecturally rather than hidden by loaders;
- active feature work is no longer repeatedly restructuring the same core surfaces;
- information ownership for the major surfaces is sufficiently clear;
- route-by-route migration is possible without simultaneously rewriting business logic.

Then build/revise the real design foundation:

- semantic tokens;
- typography system;
- display/editorial typography;
- UI typography;
- numeric/data typography;
- color and semantic signal system;
- spacing/rhythm;
- borders/rules;
- near-zero-radius philosophy;
- restrained elevation;
- navigation shell;
- data-table primitives;
- player identity/presentation patterns;
- market movement;
- filters/search controls;
- charts;
- mobile/responsive behavior;
- loading/refresh/empty/error/stale/partial states;
- accessibility;
- performance constraints.

### 5.3 MIGRATE GRADUALLY — PRODUCTION ROLLOUT

No big-bang rewrite.

Preferred migration order:

1. Premium Sports Intelligence design-system foundation/shared primitives.
2. Global application shell/navigation.
3. Dynasty Rankings — first canonical production reference screen.
4. Universal Player Profile — second canonical reference screen.
5. Universal search / command experience.
6. Market + Sharp/Insider.
7. Trade Analyzer / Finder / Package Builder / Trade Desk.
8. Team Strength / Weakness / roster / league intelligence.
9. Draft / Waivers / Game Day / probability / remaining tools.
10. Final legacy-style removal and design-system enforcement.

Transitional coexistence is acceptable only with an explicit retirement plan.

Legacy implementation must not be deleted until replacement has feature parity, data parity, acceptable performance, responsive behavior, interaction coverage, accessibility coverage and owner visual approval.

---

## 6. FIRST REAL IMPLEMENTATION TRIGGER

The first real Premium Sports Intelligence implementation prompt should **not** be triggered merely by this design decision.

Trigger it when:

1. the current production-reliability incident is closed;
2. B6 league configuration/scoring identity is merged and production-verified;
3. the immediate canonical correctness work no longer risks reshaping every Rankings input contract;
4. a route/component inventory and migration map exists;
5. the existing R0/R1 design-system infrastructure has been audited into:
   - reusable behavioral primitives;
   - visually superseded primitives/tokens;
   - legacy-only pieces to retire;
6. performance baselines for the first reference route are captured.

At that checkpoint, the first implementation milestone should be **Premium Sports Intelligence foundation + a limited Rankings reference migration**, not a whole-app redesign.

If Rankings data contracts remain unstable at that moment, do foundation only and defer the Rankings route until its contract is ready.

---

## 7. CURRENT REPOSITORY READINESS — 2026-08-12

### Ready now

The repository is ready for **preparation/audit work** because it already has:

- a centralized app shell;
- centralized navigation/search concepts;
- a semantic token layer;
- a reusable component library;
- accessibility-focused primitives;
- a DataTable abstraction;
- mobile chrome;
- performance standards;
- enough existing design-system infrastructure to inventory rather than start from zero.

### Not ready now

The repository is **not** ready for a broad production Premium Sports Intelligence migration because:

- a production-reliability/FD-exhaustion incident is still being closed;
- B6 league-configuration correctness is parked/unmerged;
- B7 and subsequent canonical correctness work remain;
- major systems/features are still being consolidated;
- existing R0/R1 visual decisions conflict with the newly approved direction and need an explicit reuse-vs-replace audit;
- broad migration now would create needless merge conflict and visual churn while data/workflow contracts are still moving.

Therefore the current classification is:

> **BEGIN NOW: no-regret design migration preparation.**  
> **WAIT: real production redesign foundation and route migration until the trigger above is satisfied.**

---

## 8. MIGRATION METHOD

Every production migration milestone must be:

- route-by-route;
- reviewable;
- reversible during development;
- visually coherent at every checkpoint;
- compatible with ongoing feature delivery;
- responsive from the beginning;
- performance-measured;
- built from shared primitives;
- protected by behavior/data regression tests.

Use feature flags, parallel routes, controlled rollout or another safe mechanism where appropriate.

Do not leave the application indefinitely split between unrelated design systems.

---

## 9. PERFORMANCE IS NON-NEGOTIABLE

The redesign must not make Chase Upside slower.

Continue to enforce the global performance standard:

- warm/cached first useful data target <= 1 second;
- normal production p95 <= 2 seconds where architectural;
- preferred supported cold useful path <= 3 seconds;
- <= 5 seconds absolute interactive useful-state failure ceiling;
- already-loaded interactions should feel immediate/local where safe.

The interface should visibly reinforce speed:

- preserve valid content during refresh;
- avoid full-page spinners;
- use stable layouts;
- local sort/filter where safe;
- progressive rendering;
- prepared/cached imagery;
- pagination/virtualization when needed;
- no visual polish that conceals slow computation.

---

## 10. PROTOTYPE INTERPRETATION

Treat Direction A as:

- the approved visual/experiential north star;
- evidence of intended personality;
- a reference for typography, density, hierarchy, tables, navigation, player presentation and data treatment.

Do not treat the prototype as:

- production-ready code;
- an exhaustive component library;
- a complete information architecture;
- a requirement to preserve mock content;
- permission to hardcode data;
- permission to regress functionality, accessibility, league-specific behavior or performance.

Where a literal prototype detail conflicts with real production requirements, preserve the design philosophy and solve the production problem correctly.

---

## 11. REQUIRED VERIFICATION PER MIGRATED SURFACE

Every later production migration milestone must verify:

- visual fidelity to Premium Sports Intelligence;
- existing functionality preserved;
- no data-source regression;
- no duplicate business logic;
- loading/empty/error/stale/partial-data behavior;
- desktop/tablet/mobile;
- keyboard behavior;
- accessibility;
- before/after performance;
- no console errors;
- no unnecessary client requests;
- no hardcoded production values;
- league-specific settings compatibility;
- missing-data semantics;
- screenshots/visual proof for owner review.

---

## 12. CLAUDE TASK-SIZING RULE

Each Claude prompt should create one coherent, reviewable migration milestone.

Good scopes:

- audit + migration map only;
- design tokens/typography foundation only;
- shared table system only;
- shell behind a feature flag;
- Rankings migration;
- Universal Player Profile migration;
- Trade Desk migration.

Bad scope:

> Redesign the entire Chase Upside application.

---

## 13. OWNER DECISION SUMMARY

**APPROVED PERMANENT DIRECTION:** Premium Sports Intelligence / Direction A.

**BEGIN NOW:** preparation, inventory, migration mapping, reuse-vs-replace audit, and prevention of new visual debt.

**WAIT:** broad production styling changes while reliability/canonical architecture remains active.

**FIRST REAL IMPLEMENTATION TRIGGER:** production reliability closed + B6 merged/verified + core route contracts stable enough for a controlled foundation/Rankings milestone.

Once that trigger is reached, explicitly tell the owner:

> **Chase Upside has reached the point where the next Premium Sports Intelligence migration phase should begin.**
