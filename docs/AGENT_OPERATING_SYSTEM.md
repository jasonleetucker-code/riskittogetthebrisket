# Agent Operating System

**Status:** canonical coordination/process layer for AI-assisted work in this repository.  
**Product authority:** **none.** This file cannot authorize a feature, methodology, production promotion, or scope change.

The purpose of this file is to make the repository carry the operating context that used to be repeated in giant continuation prompts.

## 1. Authority and precedence

This document governs **how agents work**, not **what the product should be**.

For product and implementation authority, follow the existing hierarchy:

1. owner decisions recorded in the repository;
2. `PRODUCT_PLAN.md` / `docs/MASTER_PRODUCT_PLAN.md`;
3. `docs/EXECUTION_PLAN.md` for current implementation authorization and lane ownership;
4. any active, owner-authorized fixed-denominator completion contract;
5. architecture/ADR/canonical-owner records;
6. live code and executable evidence for factual implementation status.

If this operating system conflicts with any higher-authority product or methodology record, **the higher-authority record wins**.

`CLAUDE.md` remains the detailed technical runbook. `AGENTS.md` remains the compact repo instruction file. `ASSISTANT_COORDINATION.md` remains the day-to-day branch/integration authority.

## 2. Session-start router

A material session begins by establishing **current state**, not replaying old chat history.

1. Update/read current `main`.
2. Read this file.
3. Read `docs/EXECUTION_PLAN.md`.
4. If an active completion contract exists, read it before selecting work.
5. Check `docs/WORK_CLAIMS.md` plus open PRs before editing overlapping files.
6. Read only the technical/domain documents needed for the selected unit.
7. Use `CLAUDE.md` as a technical reference, not as a substitute roadmap.

The existing Claude `SessionStart` hook in `.claude/health-check.sh` prints the active router and mechanically surfaces an incomplete Week 1 launch contract when present. This is intentional: the user should not need to paste a continuation prompt simply to tell Claude which completion contract is active.

### Current launch rule

While `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md` exists with fewer than all 30 rows literally `VERIFIED`, it is the active season-launch scoreboard.

- fixed denominator: 30;
- only literal `VERIFIED` counts;
- do not reopen V1;
- do not begin broad V2 while launch work is still authorized and incomplete;
- never improve the percentage by changing the denominator or weakening evidence.

When that contract reaches 30/30, stop the launch-completion campaign and fall back to the then-current execution plan.

## 3. Default operating posture

### Investigate before claiming

Never make a codebase claim from memory when the relevant file, route, workflow, PR, contract, or production evidence can be inspected.

Trace the **live execution path**, not merely helpers that look relevant.

### Default to bounded action when authorized

If the owner has asked for implementation or active traffic control and methodology is already settled:

- inspect;
- make the smallest correct change;
- test it;
- open/advance the PR;
- harvest CI/deploy/production evidence;
- update the canonical status record only when its acceptance criterion is satisfied.

Do not stop at “here is what somebody should do next” when the current role is authorized and able to perform that bounded action.

### Do not improvise product methodology

Stop the affected item when completion requires a genuine owner/methodology decision. Surface the **smallest exact decision** needed and continue unrelated dependency-ready work.

Never turn an evidence gap into a guessed constant, guessed host rule, guessed tie behavior, guessed scoring assumption, or silent fallback.

## 4. Roles: responsibility, not personality

Agent names do not create authority. A role exists only when the current execution plan/owner directive assigns it.

### Product owner

Owns:
- product intent;
- methodology choices that cannot be derived from approved records/evidence;
- irreversible or consequential tradeoffs the repo explicitly reserves for the owner.

Does not need to approve:
- routine tests;
- bounded bug fixes with settled semantics;
- ordinary exact-head integration once normal gates are satisfied.

### Implementation owner

Owns one bounded unit.

Responsibilities:
- claim the work;
- understand the canonical owner before editing;
- implement the smallest complete fix/feature;
- write/repair tests;
- establish `FEATURE_GREEN`;
- hand off rather than self-certifying production truth.

An implementation owner must not create a second canonical engine because the existing owner is inconvenient.

### Integration / traffic-control role

Owns repository flow, not product methodology.

Responsibilities:
- read live `main`, open PRs, claims, current contract and workflow evidence;
- reconcile exact-head CI;
- merge eligible bounded PRs through the protected path;
- harvest deployment/production proof;
- update completion contracts only from actual acceptance evidence;
- route failed work back to its implementation owner;
- maximize legitimate verified progress per hour.

Traffic control does **not** get a second product lane or a second implementation of the concept it reviews.

### Independent reviewer

A reviewer must be able to reject the author's claim.

Use the existing `reality-check-review` skill or an independent session for:
- false-completion checks;
- architecture-owner checks;
- missing/stale/degraded-state review;
- public/private leakage review;
- methodology-overreach review;
- live-path verification.

The reviewer identifies the exact failed acceptance condition and sends that unit back. It should not silently rewrite a competing implementation unless explicitly assigned ownership.

### Deterministic judge

CI/tests/scripts should decide everything that does not require judgment:

- formatting/lint;
- syntax/imports;
- schema validity;
- exact-head test results;
- build success;
- invariant checks;
- deterministic contract counts;
- known auth/status codes;
- reproducible file/artifact existence.

Do not spend model judgment “deciding” facts a script can prove.

### Production verifier

Verification is evidence, not confidence.

A production verifier must distinguish:

`IMPLEMENTED -> FEATURE_GREEN -> READY_FOR_INTEGRATION -> INTEGRATION_GREEN -> MERGED -> DEPLOYED -> VERIFIED`

A later state cannot be inferred merely because an earlier state is true.

## 5. Work is a graph; each unit is a loop

### Graph rule

The active execution plan/completion contract is a dependency graph.

Agents should:
- run independent units in parallel when their ownership/files do not collide;
- respect dependency order;
- preserve completed branches when one sibling fails;
- never restart the whole program because one node is red;
- move to another dependency-ready node when one unit is genuinely blocked.

### Unit loop

Every bounded unit converges through this loop:

1. **Discover** — read authority, live path, existing owner, current evidence.
2. **Claim** — record file/defect scope before editing.
3. **Implement** — smallest complete change, no parallel owner.
4. **Validate** — feature-scoped tests + relevant invariants.
5. **Review** — independent challenge where the risk justifies it.
6. **Integrate** — current-main reconciliation and exact-head shipping gate.
7. **Deploy** — if required by the acceptance criterion.
8. **Verify** — observe the actual target surface/artifact/state.
9. **Record** — update the canonical contract/status and close the claim.

If a step fails, route the unit to the smallest prior step that can repair the failure. Do not discard already accepted sibling work.

### Retry budgets and exit conditions

A convergence loop needs both an **acceptance condition** and a **bounded exit condition**.

- Never repeat an identical failed action without new evidence, a changed input, or a changed hypothesis.
- For autonomous retries, define a bounded attempt/action budget appropriate to the unit; do not create an unbounded "keep trying until green" loop.
- A side-effecting retry must be proven idempotent or explicitly guarded against duplicate effects.
- When the budget is exhausted, preserve the exact last failure/evidence, mark the unit BLOCKED or truthfully degraded, and move to other dependency-ready work.
- Escalation is not failure: a loop should stop when the remaining uncertainty is genuinely an owner/methodology/external dependency.

### Root-cause debugging

Debug from the violated invariant backward, not from the visible exception forward:

1. reproduce the failure before theorizing when reproduction is possible;
2. identify the first point where the expected invariant becomes false;
3. separate **observed evidence** from the **root-cause conclusion**;
4. repair the canonical root cause rather than patching a downstream symptom;
5. when multiple causes remain plausible, name the evidence that would distinguish them;
6. after repair, prove the original reproduction is green and add the lightest durable learning edge that prevents recurrence.

### Model/effort routing and tool batching

Use capability and reasoning effort as resources, not status symbols.

- Use the lowest model/effort tier that reliably clears the unit's acceptance bar when routing is available.
- Escalate for ambiguous architecture, difficult root-cause analysis, methodology-sensitive review, or integration risk when evidence shows the cheaper route is insufficient.
- Re-evaluate routing after a model-generation change; do not preserve old "always use maximum reasoning" assumptions by inertia.
- Before a tool round, identify the independent evidence/actions needed next and batch/parallelize those that do not depend on one another.
- Serialize only genuine dependencies or state-changing actions whose ordering matters.

### Targeted edits over gratuitous rewrites

Prefer the smallest edit that repairs the live path.

Do not rewrite a whole file merely because the model can. A whole-file rewrite is justified only when the file's structure itself is the defect or the bounded replacement is demonstrably safer than a surgical edit. Preserve unrelated behavior and make review blast radius obvious.

## 6. Correction edges and learning edges

A **correction edge** fixes the current run.

Examples:
- CI finds a failing test -> return the PR to implementation.
- production serves `0.0` for an undefined average -> repair that data path.
- a PR is superseded -> close it.

A **learning edge** prevents the same rediscovery in future runs.

Use the lightest durable mechanism that fits:

- code comment for a local non-obvious invariant;
- test for deterministic behavior;
- PR/issue comment for disposition history;
- contract/status note for acceptance evidence;
- ADR/owner record for methodology;
- skill for a repeated bounded workflow;
- hook/script for a deterministic action that truly must happen every time.

**Rule:** if the same correction or instruction has to be repeated across sessions, do not keep enlarging the continuation prompt. Ask whether it should become a test, hook, skill, or canonical repo rule.

The #1239 season-launch incident is the model example:
- correction edge: close the superseded archive-caller PR;
- learning edge: record why it was closed so another session does not investigate the mystery again.

## 7. Skills: small specialists, not an instruction landfill

Skills are opt-in specialist playbooks.

A skill should:
- have one recognizable trigger domain;
- own one kind of reasoning/work;
- point to canonical owners rather than duplicating them;
- state explicit non-goals;
- stay short enough that its description does not compete with unrelated skills.

Do **not** create a new skill merely because a task happened once.

Existing specialist skills:
- `blueprint-auditor`
- `design-taste-director`
- `performance-optimizer`
- `reality-check-review`
- `scraper-ops`
- `value-pipeline-auditor`

Added by this operating-system pass:
- `season-launch-traffic-control` — fixed-denominator launch integration/evidence traffic control;
- `repo-harness-auditor` — prompt/skill/hook/coordination audit and pruning.

When two skills overlap materially, merge/narrow them instead of adding routing prose to make both fire.

## 8. Persistent memory: what belongs in the repo

Write durable state when losing it would cause real rework or incorrect action.

Good durable state:
- owner decision;
- canonical ownership boundary;
- measured blocker;
- accepted methodology;
- PR disposition;
- production evidence;
- completion-row evidence;
- non-obvious incident root cause;
- next dependency-ready unit at handoff.

Bad durable state:
- conversational filler;
- speculative ideas presented as decisions;
- duplicate copies of roadmaps;
- giant session transcripts;
- self-congratulating progress summaries;
- a second tally that can disagree with the canonical tally.

Prefer a pointer to the authoritative record over copying its contents into another file.

## 9. Human approval belongs at consequence boundaries

Do not ask the owner to approve every reversible engineering step.

Escalate when the action is:
- destructive or hard to reverse;
- a product/methodology choice not settled by authority/evidence;
- a credential/secret operation requiring owner access;
- a public/private exposure change;
- an irreversible evidence-timing tradeoff;
- a production action the repo explicitly reserves for the owner.

Continue independent work while a single node waits for that decision.

## 10. Core invariants every role preserves

These remain non-negotiable regardless of model generation:

- **ONE CONCEPT / ONE CANONICAL OWNER**
- **missing != zero**
- **stale != current**
- unknown != false
- exact league scoring and factual scoring identity
- canonical best-ball lineup behavior
- signal independence / no manufactured double counting
- champion != challenger
- recommendation != execution
- auth boundaries
- provenance and timestamps
- public/private semantic boundary
- no silent home-league fallback
- no implementation/merge/deploy/verification collapse

These are product/system truths, not “babysitting prompts,” and should not be removed merely because a newer model is better.

## 11. Instruction pruning policy

Modern models follow instructions more literally. Old defensive prompting can become an obstacle.

During a harness audit, classify every repeated instruction as one of:

1. **Domain truth** — keep. Example: missing is not zero.
2. **Authority/risk boundary** — keep, preferably once in a canonical place.
3. **Deterministic check** — move to test/hook/script where practical.
4. **Specialist workflow** — move to one small skill.
5. **Historical workaround for weaker models** — delete if current evidence says it no longer helps.
6. **Duplicate** — replace with a pointer to the canonical statement.
7. **Contradictory/stale** — repair immediately.

Do not grow `CLAUDE.md`, `AGENTS.md`, and continuation prompts with three copies of the same rule.

### CLAUDE.md pruning constraint

`CLAUDE.md` is unusually large and heavily cross-referenced by code comments, tests, audit evidence, and historical docs. Do **not** perform a blind “make it tiny” rewrite during launch work.

The `repo-harness-auditor` skill owns the safe follow-up:
- inventory semantic/section references;
- identify content already canonical elsewhere;
- move only redundant detail;
- preserve stable section anchors or update references in the same bounded PR;
- prove coordination/docs tests still agree.

Until that migration is proven, this file is the small front-door operating layer and `CLAUDE.md` remains the detailed technical reference.

## 12. Handoff contract

A useful handoff is structured state, not narrative.

Always include:
- unit/contract row;
- branch + PR;
- exact head SHA when relevant;
- files/live path touched;
- tests and exact result;
- implementation state;
- integration/deploy/production state;
- unresolved blocker/decision;
- next dependency-ready action.

For completion-contract work, include the mechanically counted numerator/denominator and identify newly verified rows.

## 13. Close protocol

Before a session declares a bounded unit complete:

1. check the diff is only the intended scope;
2. run the required feature/invariant tests;
3. confirm no duplicated canonical owner was introduced;
4. distinguish what is only implemented from what is actually deployed/verified;
5. update/close the work claim;
6. leave a durable disposition if abandoning/superseding a PR;
7. update the canonical completion record only when its evidence bar is actually met.

If the active fixed-denominator contract reaches its terminal state, report the exact terminal phrase defined by that contract and stop that completion campaign.

## 14. Why this system exists

This design deliberately combines four useful patterns:

- **small front desk + specialist skills + deterministic hooks:** recurring instructions should live in the harness, not be pasted every session;
- **loops inside graphs:** each work unit converges locally while the program routes dependencies and parallel work globally;
- **agent organization:** roles, ownership, structured handoffs and independent review matter more than simply opening more parallel sessions;
- **model-generation hygiene:** stronger instruction-following makes contradictory, duplicated and obsolete prompts more costly, so periodically prune the harness instead of only adding to it.

The operating system should become **smaller and more deterministic over time**, not larger.
