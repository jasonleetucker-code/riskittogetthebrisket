# Post-B Master Reconciliation — cross-auditor adjudication

**Status:** CANONICAL EVIDENCE — the adjudication record for the post-B replan
**Reconciled against `main`:** `678bf88a04e1384adbf732f729391c70efc7054c`
**Inputs:** two independent read-only audits, both dated 2026-08-14, referred to as AUDIT 1 and AUDIT 2
**Authorizes:** nothing. `docs/EXECUTION_PLAN.md` is the authorization record.

---

# 1. Repository anchor

Both audits reported a B-completion `main` of `79f47ff` and an audited `main` of `541bca7`. At the start of this
reconciliation `main` had advanced twice more, to **`678bf88`**.

`git diff --name-only 79f47ff..678bf88` returns **56 paths, every one under `data/`, `exports/` or `CSVs/`** —
automated scrape refreshes and freshness stamps. Zero production source, zero planning documents, zero workflows,
zero configuration, zero tests. **No audit conclusion is affected**, and `678bf88` is the reconciliation base.

---

# 2. Method

Twelve independent read-only evidence domains were verified directly against the repository, the three open
planning-PR heads (fetched as local refs, never checked out) and the merge graph. Every claim below that either
audit made was re-derived rather than accepted. Where the two audits disagreed, the disagreement was settled by
running a command, not by preferring the more detailed narrative.

Both audits are evidence inputs. **Neither is authority**, and both were wrong about something material.

---

# 3. Adjudication

## D1 — The zero-loss count

**AUDIT 1:** ~154 auditable source entries · 154 mapped · 0 unmapped · 2 owner decisions.
**AUDIT 2:** the "0 unmapped" conclusion is too optimistic; eight at-risk clusters.

**ADJUDICATED: AUDIT 2 is directionally right and AUDIT 1's census is not a census.** Both undercount the source
population, by roughly a factor of six.

Recomputed by enumeration across twelve sources: **≈926 raw requirement entries → ≈357 distinct capability
identities**, plus ≈425 binding constraint/methodology units that are not capabilities. Per-source counts and the
de-duplication rule are in `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §2.

AUDIT 1's 154 is a *sample of source entries*, not an enumeration. It omits `UNIMPLEMENTED_BACKLOG.md` (56
items, 15 of them single-source), `docs/status/*` and `docs/ROADMAP-competitor-parity.md` (18 deltas), and it
counts the 104-row ledger and the 50-family crosswalk without unioning the Feature Inventory's 106 rows, the
Product Backlog Spec's 76 units, or the 65 binding owner decisions in the TODO.

The deeper problem is the standard. AUDIT 1 counted a requirement as mapped when it appeared *somewhere*. Under
this mission's definition, a requirement is safely mapped only when — among other things — **it cannot disappear
if an old PR is later closed.** By that standard AUDIT 1's "0 unmapped" was false for roughly 134 capabilities
that existed in exactly one source, most of them on unmerged branches.

**Resolution:** `docs/C_SERIES_SCOPE_MANIFEST.md` (153 rows) plus
`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`. Every source entry resolves to a disposition. **Unexplained
unmapped: 0** — and now genuinely so, because the 25 branch-only specifications were promoted onto `main`.

## D2 — AUDIT 2's eight at-risk clusters

All eight verified. Dispositions:

| # | cluster | verified location | disposition |
|---|---|---|---|
| 1 | **AI Front Office** — Ask Brisket, Roster Path Optimizer, Edge Alerts, Trade Liquidity & Market Depth, Negotiation Coach, League Truth | **#809 only.** Zero hits for all seven terms across `main`, #816 and #835 — the whole tree, not just `docs/` | **VERIFIED APPROVED** — explicit owner approval dated 2026-08-12, with per-feature gates. Spec promoted to `main`. → `C7-AI-01`…`C7-AI-05`, `C7-ALERT-01` |
| 2 | **Upside Report Preseason / Kickoff Edition** | **#809 only.** The parent feature is carried by #816 §6.2, but "Kickoff" appears zero times in #816 | **VERIFIED APPROVED** — the parent was safe, the dated timing requirement and the immutable-preseason-baseline semantics were not. Spec promoted. → `C9-UR-02` |
| 3 | **#829 Weekly Report Studio + #830 FAAB Market Heat + decisions 47–65** | **`main`** — TODO rows plus two standalone specs | **VERIFIED APPROVED, already canonical.** But #816's "synchronized through 2026-08-14" stamp is **false for exactly these**, and the two specs were unregistered in the governance index. Both corrected. → `C9-WRS-01`, `C4-FAAB-01`, `C0-GOV-06` |
| 4 | **Best Trade / personal protection / LOCK-EXCLUDE** | #835 spec (188 lines) **and** #816 ledger rows 102–104, with **no cross-reference in either direction** | **DUPLICATE — both preserved, now cross-referenced.** Consistent texts; the spec is the normative long form, the ledger rows are coverage rows. Spec promoted; ledger annotated. → `C7-BEST-TRADE`, `C3-CON-02`, `C3-CON-03` |
| 5 | **CE-11 Sleeper Action Gateway and CE-16 Trade Polls** | `main` canonical; #816 reassigns both | **VERIFIED APPROVED as features; the identifiers were the risk.** See D3. → `C7-GATE-01`, `C7-CE-01` |
| 6 | **CE-14A user feedback / polling** | **#816 only** — exactly two lines, both authored on that branch, inside the systematic reassignment; a three-line body with no surface, trigger, data contract, acceptance criteria or approval date | **OWNER DECISION REQUIRED** (`OD-06`). Registered as **CE-28** so the idea is not lost, and flagged **NOT owner-approved** so it cannot be mistaken for scope. CE-14A is restored to Personal Rankings Overlay |
| 7 | **KTC data-use / permission record** | **#809 only** — `MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §19.2. The **only** third-party data-use record anywhere in the repository | **VERIFIED APPROVED as a record; incomplete as an authorization.** Promoted to `main` regardless of #809's fate. The grant artifact is absent — see D9 and `OD-01`. → `F-EXT-01` |
| 8a | **Chat product decision** | Code live on `main` (`src/api/chat.py`); **no planning record anywhere** | **VERIFIED APPROVED** by implication and bound to its product home rather than left orphaned. → `C7-AI-01` (Ask Brisket) |
| 8b | **Usage / opportunity signal engine** | `main`, dead and defective; a live replacement exists (`src/consensus_edge/opportunity.py`) | **SUPERSEDED** → `X-06` |
| 8c | **"Link any Sleeper account" onboarding** | `UNIMPLEMENTED_BACKLOG.md`, classified historical on `main` **and** by #816 | **NOT PRODUCT SCOPE today** — recorded verbatim as a long-horizon goal, never owner-approved. → `X-07`, `OD-07` |

**Nothing disappeared.** All eight now have a destination on `main`.

## D3 — The CE identifier collision

**ADJUDICATED: AUDIT 2 is correct, and the collision is worse than reported.**

Verified: `main` and PR #816 both define CE-01…CE-21 plus CE-14A. **18 of 22 identifiers name a different
capability**; 3 partially conflict; 1 agrees. Full table in `docs/CE_REGISTRY.md`.

Three findings neither audit reached:

1. **#816 contains three CE registries in its own tree** — the inherited canonical one (in files it does not
   modify), plus two new mutually-consistent-but-contradictory ones in its reconciliation §10 and its appendix.
2. **#816 is internally inconsistent.** Its §6.8 uses `main`'s meaning of CE-20 (Game Day Command Center) while
   its §10 list assigns CE-20 to something else.
3. **#816 deletes the canonical mirror and demotes the surviving copy.** Its `MASTER_PRODUCT_PLAN.md` rewrite
   removes §4.9 outright, and its `PLANNING_DOCUMENT_STATUS.md` reclassifies `OWNER_FEATURE_INVENTORY.md` — the
   only remaining canonical registry — as "not roadmap authority", under a precedence ladder that ranks its own
   new documents higher. **Merging #816 would not have left two registries in tension; it would have flipped the
   namespace.**

The concrete harm: binding owner decision 65 and issue #830 both cite **CE-19** by number, canonically the
Waiver Market / FAAB Market Ledger. Under #816, CE-19 is Personal Rankings. The referent of a binding decision
would have changed silently.

**Resolution.** `main`'s registry is canonical — it is the owner's 2026-08-12 reconciliation and the registry
every binding decision cites. `docs/CE_REGISTRY.md` is now the single place a CE id is defined. #816's entries
were remapped **by content**: those describing a capability `main` already owns moved to `main`'s id; eight
genuinely new capabilities received **CE-22…CE-29** rather than being dropped. Provenance is preserved inline in
the appendix beneath each reconciled heading. `scripts/check_planning_integrity.py` fails CI on a duplicate CE
id with a different meaning, so this cannot recur.

## D4 — PR #835 disposition

**AUDIT 1:** absorb through current-main reconciliation, supersede the patch.
**AUDIT 2:** merge-tree is clean; merge #835 before #816.
Observed GitHub state during cross-auditor comparison: OPEN, `mergeable: false`.

**ADJUDICATED: AUDIT 2 is right about mergeability; AUDIT 1 is right about what has to happen anyway.**

Verified locally:

```
git merge-base HEAD refs/audit/pr835   → d50de556  (an ancestor of HEAD)
git merge-tree --write-tree HEAD refs/audit/pr835 → exit 0, no conflict
git log d50de556..HEAD -- <the 3 files #835 touches> → empty
```

Blob identity confirms `main` has not moved any file #835 touches. **#835 merges clean against `678bf88`.** The
`mergeable: false` and `mergeable_state: unknown` seen through the API are GitHub's asynchronous mergeability
computation, not a conflict — a local `merge-tree` is authoritative and it is green.

But mergeability was never the question. Verified against the mission's 26 required hard rules, #835's spec
scores **26 CAPTURED, 0 partial, 0 missing, 0 contradicted**. It also has three real gaps:

- **the spec is referenced by nothing in its own tree** — a session following the canonical front door could
  never discover the most binding content in the PR;
- the Feature Inventory gains a row for Best Trade only, not for protection or LOCK/EXCLUDE;
- Product Backlog Spec §1.6 and §18 still carry an older, vaguer MIN rule ("effectively untouchable") that #835
  does not reconcile against its own precise one.

**Resolution: absorbed, not merged.** The spec is promoted to `main` verbatim, cross-referenced from the
Inventory, the Backlog Spec, the Master Product Plan and the 104-ledger, given inventory rows for all three
subjects, and the older MIN wording is annotated rather than deleted. **#835 is left open and untouched** until
the owner approves this reconciliation.

Every approved behaviour is preserved: one best qualifying trade per opponent · players only · equal counts · no
picks · canonical WIN for us · opponent EVEN-or-better on KTC or IDPTC with whole-package native coverage · no
imputed approval · honest no-result · plausibility/roster-benefit ranking · recommendation ≠ execution ·
user+league-scoped protection · values unaffected · NFL-team protection · MIN outgoing-only with incoming still
allowed · dynamic current-team identity · individual permanent untouchables · LOCK requires · EXCLUDE forbids ·
mutually exclusive · multiple allowed · applied during generation · persists until cleared · temporary ≠
permanent · persistent outranks temporary · fail closed · parent hard rules never weaken · one constraint owner
for all eight generated-trade surfaces.

## D5 — PR #816 disposition

**Both audits agree: do not merge as-is.** AUDIT 1 leans supersede; AUDIT 2 leans rebase-and-surgically-reconcile.

**ADJUDICATED as a lifecycle question, as the mission directs.** The disagreement dissolves once you separate
*content* from *vehicle*: AUDIT 2 is right that the content must all land, AUDIT 1 is right that the branch is
not the way to land it.

Merging #816 — even after a rebase — would have done four things no one intended:

1. **Regressed the authorization record.** Its `EXECUTION_PLAN.md` authorizes "NEXT — B9a", already merged in
   #824. Worse, the file **auto-merges without a git conflict into a semantically broken result**: the merged
   320-line blob contains `### B9 — MERGED. Two units.` at line 71 and `## NEXT — B9a … AUTHORIZED NEXT
   FOUNDATION UNIT.` at line 124, plus duplicated B7 and B8 sections. Git's line-based merge cannot see it
   because the two records occupy disjoint line ranges.
2. **Deleted the technical runbook.** `CLAUDE.md` 1,754 → 439 lines, removing the Live Value Pipeline, Perfect
   Draft, BDVM, the FAAB engine, the B11 confidence gate, the `valuation_mode` withdrawal record, the sharp
   cohort and the endpoint tables. This is the one hard conflict git *does* report.
3. **Deleted `MASTER_PRODUCT_PLAN.md` §4** (594 → 294 lines), including the CE registry mirror and the §4.10 and
   §3.1 anchors that `CLAUDE.md` cites by number — so any conflict resolution keeping `main`'s CLAUDE.md ships
   dangling cross-references.
4. **Flipped the CE namespace** (D3).

It also carries **30 stale status claims across 10 of its 15 files**, every one pointing a reader at B9a as next.

**Resolution: absorb the durable content onto current `main`; leave the branch open.** Nine documents were
promoted with amendment blocks that correct the stale statements without deleting a line of the originals. The
104-row ledger came across verbatim, count re-verified as exactly 104 contiguous rows. Its three governance
rewrites were **not** imported; `main`'s equivalents were rewritten from merged reality instead.

Preserved in full: the B→C hard gate · the C-Series completion contract · the 104-row ledger · the feature
crosswalk · pick completeness through 2029 · Player Impact / WAR / MVP · the mature Trade Calculator spec ·
Historical Trade Replay · the specification-depth requirements · the Premium direction · the performance and
production-proof gates · the T-NEW items that remain valid.

**#816 may be closed only after the owner confirms this reconciliation carries everything.** The traceability
document is the proof.

## D6 — PR #809 unique content

**ADJUDICATED: AUDIT 2 is correct. #816's claim that #809 was restated is false, and the falsity is specific.**

#816's own enumeration of what it restates names the Premium direction, the Upside Report, Weekly Power
Rankings, Awards & Honors and source-family normalization. Verified by grep across every #816-authored document,
these appear **zero times**:

- the AI Front Office family (all six features, all seven search terms)
- the Upside Report Preseason / Kickoff Edition
- the KTC data-use permission record
- the Sharp Insider experience/performance spec
- the global performance standard
- the Redraft / ROS intelligence lane

**Six capability families and one authorization record would have been lost** by treating #816 as a superset.
All 15 #809 specifications are now on `main`; per-spec destinations are in the traceability document §I.

**The Player-MVP conflict is resolved in favour of the newer owner decision**, as the mission directs: player MVP
has **no** hard playoff-field or >.500 eligibility gate. Team success may be contextual or tie-break evidence.
The amendment is recorded in `docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md` itself, at the top, so it cannot be read
without it.

**Manager of the Year is deliberately NOT altered.** No newer owner instruction touches it, and the C-Series
contract explicitly preserves its right to a validated team-success rule. Silence is not supersession.

## D7 — The governance inversion

**ADJUDICATED: AUDIT 2 is correct, and the inversion is live.**

`docs/PLANNING_DOCUMENT_STATUS.md` lists `docs/OWNER_REQUESTED_TODO.md` under "HISTORICAL CAPTURE / SUPERSEDED AS
INDEPENDENT ROADMAP" — and that file carries **65 binding owner decisions**, of which decisions 47–65 (#829
Weekly Report Studio and #830 FAAB Market Heat) are the two newest binding decision sets in the entire
repository, dated 2026-08-14. The governance system says do not trust the file where the newest owner
instructions live. Its two companion specs were registered nowhere at all.

**Resolution — one intake mechanism, chosen: make the TODO the live intake ledger with a defined reconciliation
workflow.** The alternative — migrate everything out and forbid new additions — was rejected because it fights
how the owner actually works. Instructions arrive as issues and land in the TODO; a rule that forbids that
produces a second inversion within a month.

What changes: the TODO is reclassified **ACTIVE — OWNER INTAKE LEDGER**; a new entry is durable the moment it is
written; the reconciliation workflow (intake → canonical record → manifest row → execution plan) is stated in
the governance index; both 2026-08-14 specs are registered; and `scripts/check_planning_integrity.py` fails CI
when a numbered owner decision in the intake ledger has no manifest destination. The inversion cannot silently
recur.

## D8 — Implementation-status disagreements

Settled by inspecting code, not by preferring a label. Full per-row status is in
`docs/C_SERIES_SCOPE_MANIFEST.md`. Where the audits disagreed, the measured answer:

| system | AUDIT 1 | AUDIT 2 | **measured** |
|---|---|---|---|
| Trade Calculator | PARTIAL | COMPLETE for declared scope | **COMPLETE for declared scope AND requires expansion in C.** Both facts recorded separately (`C3-CALC-01`). 2–5 sides, KTC import, unpriced honesty all work; Analyze Trade, real-trade evidence, comparable trades and historical fidelity are absent |
| Player identity | PARTIAL / duplicated | HOLDS | **DUPLICATED — 3 independent matchers.** AUDIT 1 is right |
| Pick value | PARTIAL / 2029 absent | HOLDS, 2029-completeness pending | **Neither.** 2029 *is* priced — synthetically, as a verbatim value clone of the 2028 tier rows × 0.53, allowlisted past the single-source gate by name. 2030+ is absent entirely. Slot picks exist for 2026 only. That is a more specific finding than either audit's |
| Dropability | separate heuristics | HOLDS | **HOLDS.** `src/draft/displacement.py` is the owner. AUDIT 2 is right |
| Trade Finder | working but duplicated | working, 3 open defects | **Both true.** Gates are correct and deliberately distinct; generation is duplicated |
| Sharp | partial / not production-proven | production population unproven | **Agreed — PROOF-REQUIRED.** Code complete, 580 tests green, timers deployed; tracked verification artifacts end at 502/401/"unverifiable_unauthenticated" |
| Roster intelligence | working but disconnected | disconnected, W20-F001 still true | **Agreed — DISCONNECTED.** Zero frontend consumers of `/api/gameplan` |
| Monte Carlo | partial | partial, correlation matrix disconnected | **Agreed** |
| Perfect Draft | partial | COMPLETE, backtest honestly blocked | **COMPLETE for declared scope.** AUDIT 2 is right; the backtest exits 2 by design so "no data" cannot read as "passed" |

Three findings **neither** audit reached, all material to the C3 plan:

- **Value Adjustment has five implementations, not two** — plus a **rounding divergence**: Python banker's
  rounding in one, JS `Math.round` semantics in two others, with the parity test asserting only ±1.
- **`src/league_intel/cross_market.py` already implements whole-package native market coverage**, with measured
  evidence over 476 paired players, and has **zero production importers**. It is the correct owner for the gate
  Best Trade needs, and it is disconnected.
- **The lineup solver has six competitors, two of them serving production** — `starter-slots.js` on `/terminal`
  and `/rosters`, and `team_impact.py` on `/api/trade/simulate`.

## D9 — External grading / KTC / IDPTC

**AUDIT 1:** written KTC/IDP authorization not found. **AUDIT 2:** a KTC permission record exists on #809.

**ADJUDICATED: both are right about different objects, and both draw the wrong conclusion from it.**

A **record** exists, on #809 only: "The owner reports having received direct permission from KeepTradeCut to use
KTC data for this project." The **grant artifact** — evidence, contact, granted scope, permitted method, rate
expectations, attribution, redistribution limits, revocation terms — is not in the repository, and §19.2 itself
requires capturing it before production collection. AUDIT 2 found the record; AUDIT 1 looked for the artifact.

Then the substantive question, which both audits got wrong by assuming a mechanism that does not exist:

**There is no external whole-package grading endpoint at KTC or IDPTC, and there never was one.** Verified: the
repository scrapes per-player values and computes package math **locally**, via `src/trade/ktc_va.py` — a verbatim
Python translation of `frontend/lib/trade-logic.js`, itself a verbatim port of `keeptradecut.com/js/site.min.js`'s
`processV` / `reverseAdjust` / `adjustPackage`, parity-tested against real captures from the site.

So Best Trade's requirement — "opponent must grade EVEN or better on KTC or IDP Trade Calculator with
whole-package native coverage" — **does not need an external API**. It decomposes into two things the repository
can already do:

1. **native coverage of every asset** on the chosen market — `src/league_intel/cross_market.py`, which
   implements exactly this with measured evidence and is disconnected;
2. **faithful application of that market's own package algorithm** — the existing bit-for-bit port, once the
   five VA implementations are collapsed to one.

The spec's prohibition on "imputed-through-our-own-values" approval bites on **coverage**, not arithmetic: an
asset the external board does not price may not be given a value from our board and counted as external
approval. Running a market's published algorithm over that market's published values is not imputation — it is
what the market's own site does in the browser.

**Therefore Best Trade's external gate is NOT an external blocker.** It is `CONSOLIDATE` work on
`C3-XMKT-01` + `C3-VA-01`. Marking it EXTERNAL BLOCKER would have deferred a feature that is buildable and would
have hidden the real dependency.

What **is** open, and is tracked separately rather than folded in:

- the KTC grant artifact is absent (`F-EXT-01`);
- **IDPTC has no authorization record of any kind** (`F-EXT-02`) — while being the sole IDP market anchor and a
  co-equal approval authority in the Best Trade spec;
- seven source keys sit behind credentials or a paywall-adjacent path with zero recorded authorization, and the
  repository's one written terms posture is applied to FFPC alone (`F-EXT-03`).

All three are one owner decision, `OD-01`. **None blocks C1.** Coverage behaviour is already correct where it
matters: unpriced assets are excluded and counted, never imputed.

## D10 — The trade execution boundary

**ADJUDICATED: settled on the invariant, genuinely unresolved on the requirement.**

**Unanimous across `main` and all three PRs, with zero contradiction: NO SILENT EXECUTION.** Every statement is
a constraint on *how* execution may happen — authenticated, explicit league and team, previewed or confirmed,
idempotent, audited, routed through CE-11. Verified: the repository has **zero** Sleeper write paths; every one
of ~60 Sleeper URLs is a GET.

Unresolved: whether authenticated submission must **exist** by C completion. The two governing clauses point
opposite ways and sit in the same document: the completion contract's mature-calculator minimum omits submission
entirely, while its no-silent-deferral rule plus its CE-01–CE-21 census sweep CE-11 into required scope. Against
that, the Feature Inventory gates CE-11 on "only after core decision products are correct/stable and
security/auth architecture is ready" and places it in Tier 3, and the architecture handoff ranks a correct Trade
Calculator above send-to-Sleeper.

This is a scope question the records do not answer, not a documentation conflict to resolve. → **`OD-02`**.
CE-11 is an unbuilt "L"-sized new build; any C-completion claim including it is a from-scratch build.

## D11 — Production health and source issues

| issue | classification | why |
|---|---|---|
| **DraftSharks ~219 h stale**, session absent on prod, watchdog red every 2 h, 9-day-old values still voting | **OPERATIONS / HOTFIX OUTSIDE C** + `OD-04` | Degrades value quality today and needs fixing today. It does not block C1: the B11 freshness axis already discounts confidence on stale evidence, so the defect is visible in the contract rather than hidden. Fixing it is not C work and waiting for C would be wrong |
| **Partial source runs reported as healthy** — `total_sources: 2` while 21 keys are served | **EARLY-C FOUNDATION WORK** (`C4-SRC-02`) | Freshness, coverage and degraded state are the same honesty contract B established for values. It is foundation work, not a hotfix, because the fix is a contract change |
| **KTC TradeDB/WaiverDB identity mapping** yields unjoinable names | **NORMAL C FEATURE WORK** (`C4-KTC-01`) | Blocks the Market Trade Ledger lane, which is C4. The accumulator script is the live mitigation |
| **Sharp production proof / bootstrap failures** | **EARLY-C FOUNDATION WORK** (`C4-SHARP-01`, `C4-SHARP-02`) — and a **C4 entry gate** | A C4 plan that assumes a populated cohort inherits a fiction. Proof must precede the features that consume it |
| **Public payload latency** ~2.1 MB / 14.8 s observed | **NORMAL C FEATURE WORK** (`C8-PERF-05`) | Real and measured, but it is a performance gate on a public surface, not a foundation defect |
| **Public awards manufactured with zero games; 2024 declares ten teams with eight standings** | **NORMAL C FEATURE WORK** (`C9-AWARD-01`, `C9-HIST-01`) | Publicly wrong today and worth fixing early in C9's lane. Franchise continuity must precede any awards or WAR backfill |
| **11 irreversible-evidence-loss mechanisms** | **EARLY-C FOUNDATION WORK — the first thing C1 does** | See §4 |

---

# 4. Are there true pre-C blockers?

**NONE.**

A true pre-C blocker means beginning C1 would be unsafe, or would destroy or lose evidence. Every candidate was
tested against that definition:

| candidate | blocks C? | evidence |
|---|---|---|
| Four B residuals | **DOES NOT BLOCK C** | None writes a canonical value. The one that writes to disk clobbers a single-slot *derived cache*; the durable history is a separate append-only log that offline builds never write, so any past `rankChange` is reconstructible |
| Stale authorization record | **DOES NOT BLOCK C** — it *was* the blocker | Repaired by this PR. This is precisely what the reconciliation existed to fix |
| CE namespace collision | **DOES NOT BLOCK C** | Resolved by this PR |
| Branch-only owner intent | **DOES NOT BLOCK C** | Resolved by this PR — 25 specs promoted |
| DraftSharks outage | **DOES NOT BLOCK C** | Operational; degrades quality visibly rather than silently. Fix on the always-open lane |
| Sharp production unproven | **DOES NOT BLOCK C** | Blocks C4's *entry*, not C1's start. Recorded as a C4 gate |
| Duplicate engines | **DOES NOT BLOCK C** | They *are* C2/C3 scope. That is the plan, not an obstacle to it |
| **Ongoing irreversible evidence loss** | **DOES NOT BLOCK C — it is the reason to START C** | Eleven mechanisms are losing evidence right now: a ~5-day KTC crowd window with no durable output, a board recorder whose own docstring says "every day it is not running is a day of evidence that cannot be recovered later" and whose scheduling is unobservable off-host, scoring cards atomically overwritten so yesterday's is destroyed, Sleeper trending discarded every 15 minutes and never once recorded, trades on a 365-day rolling window with no stable id, raw-source and identity collection halted since 2026-04-20, and `playerctx` history with zero snapshots ever committed despite a timer |

That last row is the one the mission flags as the possible exception, so it deserves the explicit answer:
**ongoing evidence loss is an argument for authorizing C1 sooner, not for blocking it.** C1 is the phase that
starts retention. Blocking C1 to protect evidence would destroy the evidence it was protecting. The retention
items are therefore the *first* PR-sized units inside C1A, ahead of any schema work.

**Recommendation: C1 is safe to authorize the moment the owner approves this reconciliation.**

---

# 5. Recommended disposition of the old planning PRs

**AFTER — and only after — the owner approves this reconciliation.** All three are untouched by this PR.

| PR | recommendation | precondition |
|---|---|---|
| **#809** | **CLOSE as SUPERSEDED BY ABSORPTION.** All 15 specs are on `main`, one amended (Player MVP) and two scope-bounded (KTC permission, competitor reuse) | Owner confirms the traceability document §I covers everything |
| **#816** | **CLOSE as SUPERSEDED BY ABSORPTION.** Nine documents promoted with staleness corrected; CE numbering reconciled; the 104-row ledger verbatim. Its three governance rewrites were deliberately not imported — `main`'s were rewritten from merged reality instead | Owner confirms traceability §F and §G |
| **#835** | **CLOSE as SUPERSEDED BY ABSORPTION**, or merge first if the owner prefers its commit lineage on record. It still merges clean, and merging it after this PR would produce only trivial duplicate content, not a conflict | Owner preference |
| **#758–#763** | Unchanged by this reconciliation. #759, #760, #761 and #762 carry performance instruments C0 needs; landing them early gives C measurement tooling | Separate decision |

---

# 6. Owner decisions required

Seven. Each states options, a recommended default, consequences, and whether it blocks C1. **None blocks C1.**

### `OD-01` — External source authorization

**Question.** The KTC permission exists as an owner report, not as a captured grant. IDPTC has no record at all.
Seven source keys sit behind credentials with no recorded authorization, and the one written terms posture in the
repository applies to FFPC alone.

**Options.** (a) Capture the KTC grant artifact per §19.2, seek an equivalent IDPTC record, and write one posture
covering the credentialed sources. (b) Capture KTC only. (c) Change nothing and accept the gap.

**Recommended: (a).** It is the only option that makes the record match the practice, and §19.2 already requires
it before production collection.

**Consequences.** (a) unblocks the KTC Trade Database ingestion lane defensibly. (b) leaves the IDP anchor —
which the Best Trade spec names as a co-equal approval authority — with no authorization at all. (c) leaves the
repository's largest and second-largest data dependencies undocumented.

**Blocks C1? No.** It gates C4's ingestion lane. Note the ingestion in question is already live and
long-standing; this is about recording authority, not starting something new.

### `OD-02` — Is authenticated trade submission required for C completion?

**Question.** Must CE-11 exist by C completion, or is it an approved later capability? The records settle that
execution must never be silent; they do not settle whether it must exist.

**Options.** (a) Approved later capability — explicitly outside C completion. (b) Required for C completion.

**Recommended: (a).** CE-11 is an unbuilt "L"-sized new build with zero foundation today, the Feature Inventory
already gates it on core decision products being correct and the auth architecture being ready, and the
architecture record already ranks a correct Trade Calculator above send-to-Sleeper.

**Consequences.** (a) C can complete with recommendation-only surfaces, which is what every current record
describes. (b) adds a from-scratch authenticated mutation surface — with its own security model — to the critical
path of an already large program.

**Blocks C1? No.**

### `OD-03` — Analyst Intelligence cost posture

**Question.** C6 needs podcast/YouTube ingestion infrastructure, analyst identity and possibly paid
transcription. None exists — zero ingestion code, zero credentials, zero ASR tooling. X is already cost-gated by
owner decision 13.

**Options.** (a) Authorize a bounded budget and build C6 as planned. (b) Defer C6 past C completion. (c) Build
the claim/evidence substrate and the news lane now, defer paid media ingestion.

**Recommended: (c).** It unblocks the Central Buy/Sell reconciler and Universal Player Profile — which have
real dependents — without committing to recurring cost, and it keeps the substrate ready.

**Consequences.** (a) recurring cost on a small private site, which decision 13 already declined for X. (b)
several approved features stay unbuilt and the completion phrase becomes unreachable without an explicit
exception. (c) partial C6; the media lane needs a later decision.

**Blocks C1? No.**

### `OD-04` — DraftSharks

**Question.** Two source keys are ~219 hours stale against a 24-hour threshold, the production session file is
absent, the watchdog has been red every two hours, and nine-day-old values still vote in every blend. Note
`draftSharksRos` is fresh, which suggests login works and the dynasty-page scrape specifically is broken.

**Options.** (a) Re-mint the session and repair the dynasty scrape. (b) Keep the source but exclude stale values
from the blend rather than only discounting confidence. (c) Retire the source.

**Recommended: (a), with (b) as the standing safety net.** (a) restores two of thirteen evidence families.
(b) is worth having regardless — it is the honest generalization of MISSING IS NEVER ZERO to *stale*.

**Consequences.** (c) permanently drops a provider family and changes the blend on every row, which needs its
own before/after evidence.

**Blocks C1? No.** Operations, on the always-open lane.

### `OD-05` — Premium token direction

**Question.** Live design tokens have drifted *deeper* into the terminal aesthetic — mono as the default UI
typeface, signal blue with gold deleted, 2–3px radii — which are exactly the attributes the Premium Sports
Intelligence north star lists as superseded. Every new surface built on today's tokens widens the future
migration.

**Options.** (a) Confirm the north star and freeze new terminal-direction token work. (b) Update the north star
to absorb the retune. (c) Defer.

**Recommended: (a).** The north star is the newer explicit owner decision (2026-08-12) and the mission directs
preserving Direction A as the final design direction.

**Consequences.** (c) is the expensive one — it means building UI twice, which the mission explicitly warns
against.

**Blocks C1? No.** It blocks C8 foundation work, which is why it is asked now rather than later.

### `OD-06` — CE-28 user feedback / polling

**Question.** Approve as scope, or drop? It exists in two lines authored on one branch, with a three-line body
and no approval date, and it was tagged with an identifier that canonically means something else.

**Options.** (a) Approve as future scope with a real spec. (b) Drop.

**Recommended: (b) unless you recall approving it.** Nothing in the record shows an owner decision, and the
capability arrived attached to an identifier collision.

**Consequences.** Either way it is registered as CE-28 and cannot be silently lost.

**Blocks C1? No.**

### `OD-07` — "Link any Sleeper account" onboarding

**Question.** A long-horizon goal recorded verbatim in a file classified as historical by both `main` and #816.
Approve as scope, or leave as an aspiration?

**Options.** (a) Approve as C scope. (b) Leave recorded but out of scope.

**Recommended: (b).** It was never owner-approved, and it is a materially different product posture — multi-user
onboarding — from the current private/owner-scoped site.

**Blocks C1? No.**

---

# 7. What this reconciliation changed, and what it did not

**Changed:** planning and documentation only.

**Not changed — certified:** no C feature implemented · no production behaviour changed · no valuation
methodology changed · no trade behaviour changed · no product API changed · no data migration or backfill
performed · no old planning PR merged, closed or commented on · no workflow dispatched · nothing deployed.

**The reserved completion phrase is not used anywhere in this reconciliation**, and no C implementation is
authorized by it.
