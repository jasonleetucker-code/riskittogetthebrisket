# Weekly Report Studio — Manual External AI Architecture

**Owner decision date:** 2026-08-14  
**Tracking issue:** #829  
**Status:** APPROVED PLANNED PRODUCT / BINDING OWNER DIRECTION  
**Applies to:** weekly pregame reports, postgame recaps, Game of the Week, weekly overview/storytelling, weekly graphic copy, and related Public League Experience v3 / Game Day narrative surfaces.

---

## 1. Owner intent

The owner does **not** want to manually write weekly reports. The owner **does** want to manually trigger/generate them externally when desired so the site does not automatically consume recurring LLM/API credits.

The default architecture must therefore separate:

1. deterministic report data preparation;
2. AI prose generation;
3. structured import/validation;
4. branded rendering/publication.

The site must remain fully useful without an always-on paid LLM integration.

---

## 2. Default workflow

**Manual External AI is the default generation mode.**

Canonical flow:

`DATA -> PACKAGE -> EXTERNAL AI -> IMPORT -> VALIDATE -> RENDER -> PUBLISH`

Expected owner workflow:

1. Open **Weekly Report Studio**.
2. Choose the eligible season/week and pregame or postgame package.
3. Click **Prepare Week**.
4. Click **Copy AI Package**.
5. Paste the package into ChatGPT, Claude, or another chosen external AI service.
6. Generate the complete weekly report package externally.
7. Copy the returned structured output.
8. Paste/upload it into **Import AI Report Package**.
9. Site validates the package atomically.
10. Preview all reports/graphics.
11. Publish.

The owner must not have to manually type the report prose.

---

## 3. Generation modes

Weekly Report Studio must support one canonical pipeline with three interchangeable generation modes.

### 3.1 Manual External AI — DEFAULT

- Site prepares the prompt/data package.
- Site makes **zero** LLM/API calls.
- Owner performs the generation in an external AI product.
- Owner imports the structured response.
- No automatic generation job may spend AI credits while this mode is selected.

### 3.2 On-Demand API — OPTIONAL

- Explicit owner action such as **Generate with AI**.
- Uses configured site-side LLM/API credentials only after the owner presses the action.
- Must feed the result through the **same versioned output schema, validator, renderer, preview, and publication path** as Manual External AI.
- Clicking the button is a convenience choice, not a different report engine.

### 3.3 Automatic API — OPTIONAL / DISABLED BY DEFAULT

- Scheduled generation may be added later.
- It must remain disabled unless the owner explicitly enables it.
- Eligibility for a new week/report must never itself authorize credit spend.
- Automatic generation must still use the same canonical package and import/validation contract.

---

## 4. One package per weekly stage

Do not require the owner to run separate AI generations for each matchup unless a package is too large for the chosen provider.

### Pregame package should be capable of producing

- weekly overview;
- Game of the Week preview;
- all matchup previews;
- players to watch;
- upset/watch storylines;
- rivalry/division/standings/playoff implications;
- notable transaction/context notes where approved and public-safe;
- graphic headlines, subheads, captions, and bounded story copy;
- any other approved weekly pregame narrative fields.

### Postgame package should be capable of producing

- weekly recap;
- Game of the Week recap;
- all matchup recaps;
- player/team superlatives;
- biggest upset;
- bad beat / miracle result;
- biggest overperformers/underperformers where canonically measured;
- standings movement;
- playoff implications;
- rivalry/division consequences;
- graphic headlines, subheads, captions, and bounded story copy;
- any other approved weekly postgame narrative fields.

If provider context limits eventually require chunking, the site should chunk deterministically and preserve one logical weekly package/version rather than exposing six unrelated report workflows.

---

## 5. Deterministic data package

The site should precompute every objective fact it can from canonical owners before anything is sent to AI.

Potential inputs include, when trustworthy and public-safe:

- league/season/week identity;
- team names, owner/franchise identities, logos/branding;
- records, standings, division position;
- current/final matchup scores;
- projections and uncertainty;
- exact custom-scoring/best-ball outputs;
- pregame/live/final win probability where appropriate;
- matchup/rivalry history;
- previous results and streak context;
- playoff/championship implications;
- power/luck/public-safe context;
- transactions and roster changes;
- injuries/status/news from canonical sources;
- key performers;
- player/team projection deltas and realized over/underperformance;
- records/milestones;
- Game of the Week selection inputs;
- other approved public-safe facts.

**AI must narrate supplied facts; it must not be asked to rediscover canonical league truth.** Missing or unsupported data remains explicit and must never be silently invented or converted to zero.

Every package should include enough schema/documentation instructions to prevent the AI from returning unstructured prose or fabricating fields.

---

## 6. Versioned external-AI contract

Use a strict, versioned structured contract, preferably JSON.

At minimum preserve:

- `schemaVersion`;
- league/season/week identity;
- stage (`PREGAME` / `POSTGAME`);
- package/source snapshot identifier;
- generated-at/imported-at timestamps;
- optional provider/model metadata entered automatically or manually when available;
- report section identifiers;
- matchup/franchise identifiers rather than only display names;
- bounded headline/subheadline/caption fields;
- narrative body fields;
- graphic-copy fields;
- optional warnings/coverage notes;
- provenance back to the deterministic source package.

The contract must be provider-neutral so ChatGPT, Claude, or another provider can produce the same shape.

---

## 7. Import and validation

Import is a product feature, not a raw paste-to-database shortcut.

Requirements:

- validate schema version;
- validate season/week/stage identity;
- validate required report/matchup IDs;
- reject unknown/malformed structures where they could corrupt rendering;
- enforce field length/format constraints needed by graphics/templates;
- preserve missing fields explicitly;
- detect duplicate report IDs;
- prevent cross-week/cross-season accidental imports;
- surface validation errors clearly;
- support **Preview before Publish**;
- use atomic/all-or-nothing publication for a weekly package unless an explicit future partial-import workflow is designed;
- keep imported draft separate from currently published report until publish succeeds;
- preserve prior published version/revision history where practical so a bad new import can be rolled back.

Optional API generation modes must enter through this same validation boundary. They must not get a privileged bypass.

---

## 8. Graphics do not require generative-image AI

Weekly graphics should use deterministic reusable **Premium Sports Intelligence** templates through the site's canonical share/rendering system (HTML/CSS/SVG/Canvas or successor).

AI may supply bounded content such as:

- headline;
- subheadline;
- short storyline;
- caption;
- callout labels.

The renderer owns:

- layout;
- typography;
- colors;
- team/logo placement;
- score/value blocks;
- chart/graphic primitives;
- export dimensions;
- visual consistency.

Do **not** depend on generative-image credits for routine weekly graphics. Deterministic templates are cheaper, faster, more reliable, brand-consistent, and testable.

---

## 9. Canonical ownership and reuse

Do not create a parallel weekly-data or narrative truth system merely to support external generation.

Weekly Report Studio should consume existing/canonical owners for:

- public league snapshot/data contracts;
- weekly matchup data;
- weekly recap/narrative inputs;
- scoring and best-ball assignment;
- Game Day projection/win probability;
- standings/playoff context;
- rivalry/history;
- public-safe news/intelligence;
- public information classification;
- share/graphic rendering.

Existing weekly narrative scripts/routes (`src/public_league/weekly*`, matchup narrative/report surfaces, exports, and frontend weekly/article routes) should be audited and reused/consolidated where appropriate rather than ignored and duplicated.

---

## 10. Cost and safety invariants

1. **Manual External AI mode performs zero site-side LLM/API calls.**
2. No cron/scheduler/background eligibility event may spend LLM credits while Manual External AI is selected.
3. On-Demand API requires an explicit owner action.
4. Automatic API remains disabled by default and requires explicit owner enablement.
5. All modes share one package schema and one validation/render/publish pipeline.
6. Deterministic facts come from canonical data owners, not AI guesses.
7. Imported AI copy cannot silently mutate standings, scores, values, projections, or any canonical factual truth.
8. Report publication remains separate from league mutations/actions.

---

## 11. UX target

The eventual owner experience should feel like a lightweight editorial control room rather than a developer tool:

- Week/status selector;
- eligibility/readiness state;
- Prepare/Refresh deterministic package;
- Copy AI Package;
- clear stage-specific generation instructions;
- Import AI Report Package;
- validation result;
- preview of every report and graphic;
- publish/revise controls;
- visible generation mode and whether that mode can incur API cost.

The default workflow should require only copying/pasting and clicks, not manual report composition.

---

## 12. Acceptance criteria

The feature is not complete until all of the following are demonstrated:

- Manual External AI path makes zero site-side LLM/API calls.
- One pregame generation can cover the complete eligible week.
- One postgame generation can cover the complete eligible week.
- Site package contains the canonical deterministic facts needed by the reports.
- External AI output uses the documented versioned schema.
- Malformed/wrong-week/wrong-stage imports fail closed.
- Import is atomic or has an explicitly designed safe partial-state model.
- Preview accurately represents what will publish.
- Published report surfaces consume imported structured data correctly.
- Weekly graphics render deterministically from the canonical renderer/templates.
- Optional On-Demand/Automatic modes pass through the exact same validation contract.
- Automatic credit spending is disabled by default.
- Existing weekly/report code has been reconciled so there is one coherent report system, not a new parallel stack.

---

## 13. Execution placement

This is approved scope but should be implemented at the **natural Public League Experience v3 / weekly storytelling / Game Day / share-renderer checkpoint**, after the required canonical data contracts are sufficiently trustworthy.

Do not interrupt unrelated foundational repairs merely to build it early. When the relevant weekly/public implementation phase arrives, Claude must read this document and issue #829 before designing or modifying the report-generation pipeline.
