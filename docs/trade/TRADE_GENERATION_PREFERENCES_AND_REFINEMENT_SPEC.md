# Trade Generation Preferences & Package Refinement

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from its planning branch by the
> post-B master reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). No content was changed.
> Its C-Series phase placement and completion evidence live in
> `docs/C_SERIES_SCOPE_MANIFEST.md`.


**Status:** OWNER-APPROVED PRODUCT REQUIREMENT  
**Owner direction captured:** 2026-08-14  
**Scope:** Private/authenticated generated-trade recommendations only  
**Canonical relationship:** Extends the shared Untouchable / excluded-player control, shared package-generation engine, Trade Finder/Suggestions, Package Builder, Golden Upgrades, Best Trade to Send Each Team, equalizers/counters, Trade Desk recommendations, and future generated-trade surfaces. It does not create another value model or package engine.

---

## 1. Goal

Generated trade recommendations should respect what the selected user is actually willing to trade and should let the user refine a proposed package without manually rebuilding it.

There are **two different classes of constraint** and they must remain separate:

1. **Persistent personal trade protection** — durable user + fantasy-league preferences such as an individual untouchable player or an NFL-team-wide outgoing protection.
2. **Temporary package refinement** — LOCK and EXCLUDE/X controls applied to the currently generated trade context and preserved until the user clears them.

Neither class changes canonical player values, external market values, Team Strength, or another user's recommendations.

---

## 2. Persistent personal trade protection

### 2.1 Scope and storage

Persistent protection is scoped to the authenticated **user + selected fantasy league**. It is not a global player flag and must never be hard-coded into canonical player data.

Support at least:

- individual-player untouchable/protected rules; and
- NFL-team outgoing protection.

### 2.2 Owner-specific Minnesota preference

For Jason's configured league preference, **Minnesota Vikings (MIN) players are protected from appearing on the OUTGOING side of automatically generated trade packages**.

This is a personal recommendation constraint, not a valuation rule:

- MIN players may still appear as INCOMING acquisition targets;
- MIN players retain their ordinary canonical value;
- KTC/IDP/market values are unchanged;
- other users without this preference may receive outgoing MIN recommendations;
- manual Trade Calculator what-if analysis remains free-form.

NFL-team protection follows canonical current NFL-team identity dynamically. A player who joins MIN becomes protected by the team rule; a player who leaves MIN stops being protected by that team rule unless an individual untouchable rule still applies.

### 2.3 Consumers

Every automatically generated trade surface must consume the same canonical outgoing-constraint owner during candidate generation, including at minimum:

- Trade Finder / arbitrage;
- Trade Suggestions;
- Golden Upgrades;
- Package Builder;
- Best Trade to Send Each Team;
- trade equalizers / counteroffer suggestions;
- Trade Desk recommendations; and
- future AI/generated trade-recommendation surfaces.

Do not implement page-local copies or post-filter protected players after ranking.

---

## 3. Generated-package LOCK and EXCLUDE/X

Every generated trade package should expose two separate controls for **outgoing players**.

### 3.1 LOCK

LOCK means:

> Keep this outgoing player in the next regenerated package for this current target/opponent/refinement context.

When the user locks Player A and regenerates, every candidate considered for the replacement result must include Player A on the outgoing side.

### 3.2 EXCLUDE / X

EXCLUDE/X means:

> Do not use this outgoing player in the next regenerated package for this current target/opponent/refinement context.

When the user excludes Player B and regenerates, Player B must not appear on the outgoing side of the replacement result.

### 3.3 Interaction rules

- LOCK and EXCLUDE are mutually exclusive for the same player.
- Selecting one for a player clears the opposite temporary state for that player.
- Multiple locks and exclusions may be active simultaneously where the parent feature can satisfy them.
- Clicking LOCK or EXCLUDE should immediately rerun the shared canonical package generator; a separate manual refresh may also preserve and rerun the same constraints.
- Active refinement state survives package regeneration and ordinary UI/data refreshes until the user explicitly clears/resets it.
- Provide a clear **Reset/Clear refinements** action and visible state for every active lock/exclusion.
- A temporary EXCLUDE/X does **not** silently become a permanent untouchable. The UI may separately offer an explicit action to promote it to persistent protection.
- Persistent protection outranks temporary refinement. A protected outgoing player cannot be forced into generated recommendations merely by a temporary LOCK unless the user intentionally changes/removes the persistent protection.

---

## 4. Parent-feature constraints remain hard

LOCK/EXCLUDE refines the feasible candidate set. It never weakens the parent feature's qualification rules.

For **Best Trade to Send Each Team**, a regenerated candidate still must satisfy all of its hard requirements:

- players only;
- equal player counts each direction;
- canonical win for the selected team;
- opponent even/win on at least one approved external calculator (KTC or IDP Trade Calculator);
- whole-package native external coverage;
- one best qualifying result per opponent.

If active locks/exclusions make those conditions impossible, return an explicit state such as:

**No qualifying trade found under current constraints.**

Never solve the conflict by silently:

- dropping a lock;
- reintroducing an excluded/protected player;
- adding a draft pick;
- changing required package count;
- accepting a canonical loss/even result when a win is required; or
- treating missing external coverage as approval.

The same fail-closed principle applies to hard requirements on other generated-trade surfaces.

---

## 5. UX contract

Each outgoing player in a generated package should expose accessible controls for:

- **LOCK** — visually indicates the player is required for regeneration;
- **EXCLUDE / X** — visually indicates the player is forbidden for regeneration.

Icons may be used, but each control needs an unambiguous text/tooltip and screen-reader label. State must not rely on color alone.

Regeneration should be immediate enough to feel like refining a proposal, not restarting the workflow. Preserve the selected opponent/target and all compatible active constraints.

Manual Trade Calculator entry is intentionally different: the user may manually inspect any trade, including a protected player, because manual analysis is not an automated recommendation.

---

## 6. Canonical implementation rule

Apply persistent protections and temporary LOCK/EXCLUDE constraints **during shared candidate generation, before package scoring/ranking**.

Conceptually:

1. resolve selected user + league;
2. resolve persistent outgoing protections;
3. resolve active temporary locks/exclusions for the current refinement context;
4. reject contradictory/forbidden state;
5. generate only feasible packages satisfying those constraints;
6. apply the parent feature's hard qualification rules;
7. rank the remaining qualifying packages with the canonical objective;
8. return the best result or an honest no-result state.

Do not generate everything first and hide forbidden packages afterward. That wastes work and can return the wrong 'best' result.

---

## 7. Validation / acceptance

At minimum prove:

1. a locked outgoing player survives regeneration;
2. an excluded outgoing player disappears and remains excluded on subsequent regeneration;
3. LOCK and EXCLUDE cannot be active simultaneously for the same player;
4. multiple locks/exclusions are honored together when feasible;
5. impossible constraints return an honest no-result state without weakening parent rules;
6. Reset/Clear removes temporary refinement state;
7. persistent individual protection applies across every generated-trade surface;
8. Jason's MIN team protection applies only to his configured user+league context;
9. MIN players are blocked outgoing but remain valid incoming targets;
10. a different user without MIN protection can receive outgoing MIN recommendations;
11. a player joining/leaving MIN updates team-rule protection through canonical NFL-team identity;
12. manual Trade Calculator analysis can still include protected players;
13. canonical player values and external market values are unchanged by preference state;
14. every generated-trade surface consumes the same canonical constraint owner rather than a page-local implementation;
15. future trade execution remains separate, requires explicit confirmation, and cannot silently bypass persistent protection.

---

## 8. Method status

**FINAL / OWNER-DECIDED PRODUCT BEHAVIOR:** persistent-vs-temporary distinction, outgoing-only MIN preference, LOCK semantics, EXCLUDE semantics, shared-generator application, fail-closed no-result behavior, and recommendation/execution separation.

**IMPLEMENTATION DETAIL TO VALIDATE:** exact persistence/storage schema, refinement-context identifier, UI placement/iconography, and performance strategy. Those choices may not change the owner-decided semantics above.
