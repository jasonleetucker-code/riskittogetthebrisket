# V1_NEXT25_CENSUS

**Read-only audit support. No code modified. No V1 status counted or promoted.**
**Delivered to Claude 5 / Integration via this file on PR #1000.**

Repository: `jasonleetucker-code/riskittogetthebrisket`
Current canonical: **70 / 136 VERIFIED = 51.5%**.
Active Tier-A queue (already assigned, NOT duplicated here): V1-69, V1-90, V1-121, V1-133, V1-134, V1-135, V1-79, V1-92, V1-98, V1-112, V1-40 (11 rows).
Planning assumption: Tier-A closes to 81/136 = 59.6%; **15 more rows** needed for 96/136 = 70.6%.

## Method

Fresh current-main read of `docs/VERSION_1_COMPLETION_CONTRACT.md` §3 at `origin/main`, excluding
every VERIFIED row and every Tier-A row above. 66 non-VERIFIED rows total, 55 remain after excluding
Tier-A. This report classifies 30 of those 55 (the ones with a legible closure path from row text plus
this pass's targeted verification), selects the strongest 25, and names the other 25 unclassified rows
only implicitly (they were not examined this pass -- see "Not examined this pass" at the end).

Classification legend: **A** STATUS_STALE · **B** VERIFICATION_ONLY · **C** PRODUCTION_CHECK_ONLY ·
**D** SMALL_REPAIR · **E** BOUNDED_IMPLEMENTATION · **F** SUBSTANTIVE · **G** AUTH/EXTERNAL_BLOCKED ·
**H** OWNER_DECISION.

Ranked by **numerator per hour**, not feature attractiveness: production-check-only rows where the
code already exists and only a checklist/measurement remains (class C) rank above small repairs
(D), which rank above bounded implementation (E). Owner-decision-blocked rows (H) are named but
excluded from the ranked 25 -- zero engineering hours can move them until the decision lands.

## Headline findings (the "pay special attention to" list, plus a fresh sweep)

- **V1-42 is a genuine "NOT STARTED whose mechanism already exists" row.** The contract shows
  `NOT STARTED`, but `simulate_roster_change` is defined at `src/roster_intel/simulation.py:223`,
  confirmed by direct grep this pass. This is the single strongest finding in this census -- it may
  need nothing but a test tying the existing function to V1-42's exact four-state contract wording.
- **V1-49's remaining gate is production-only, not code.** PR #1027 (open, unmerged, docs-only) just
  re-audited it: the headline defect closed via #915, two further private-position-table gaps were
  found and confirmed UNREACHABLE on the live board (Sleeper never emits "SAF"), so nothing was
  touched per the sprint's own "do not repair unreachable defects" instruction. What remains is
  4 of 10 production promotion-gate items.
- **V1-136 has real evidence in flight but the reconciliation plan is not yet applied.** PR #1001
  (open) is a rigorous three-slice audit; Slice 3's failure-state instrumentation was written against
  a board (`idpShow` plain) that #1012 retired from voting three hours before this PR's last push, in
  favor of `idpShowCombined`. A fully-scoped 5-point reconciliation plan already exists in the same
  branch's own follow-up commit for Claude 5 to apply.
- **V1-41's implementation exists but is explicitly NOT reusable.** A commit titled exactly for this
  row exists, but it sits inside a 100-file, 20,751-insertion rehearsal branch
  (`claude/v1-trade-roster-rehearsal`) carrying its own `DO NOT CHERRY-PICK` warning and superseded
  work. This dispatcher's own prior-cycle records already flagged that branch as
  "evidence only and must never become a merge candidate." Recorded here so nobody rediscovers that
  the hard way by attempting a cherry-pick.
- **The "VERIFY ONLY" trio (V1-45, V1-56, V1-61) plus the #911 quartet (V1-57, V1-60, V1-65, V1-129)
  plus the #909 pair (V1-83, V1-84) are all class C** -- zero code gap named in any of their row
  text; every one needs only a production-side checklist run or measurement. Nine rows, all
  production-check-only, all independently verified against `origin/main` this pass.
- **V1-87 is BLOCKED with no blocker stated**, unusual against every other BLOCKED row in this
  census (V1-89, V1-110 both name an explicit owner-decision ID). Worth a fresh look at whether that
  block is stale.

---

## NEXT 5 (after Tier A)

Highest numerator-per-hour: one confirmed-existing mechanism (V1-42) plus four rows the owner has already attested complete or where #911 already closed the code gap, needing only a checklist/measurement pass.

#### V1-42: Exact before->apply->re-solve->after roster simulation

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | NOT STARTED on main, per the contract. BUT: `simulate_roster_change` is DEFINED at src/roster_intel/simulation.py:223, confirmed by direct grep this pass -- the mechanism this row asks for already exists in the tree. |
| Exact missing evidence | No test/checklist ties simulate_roster_change to V1-42's exact contract wording ('before->apply->re-solve->after'), and no promotion pass has run against it. Need: confirm the function's signature covers all four states, write/locate the RED->GREEN test, promote. |
| Owner lane | Lane 2 (Trade Intelligence) |
| Existing PR/commit/instrument | src/roster_intel/simulation.py:223 (production code, on main) |
| Production access needed? | no |
| Expected engineering effort | LOW -- likely a verification pass over existing code, possibly a small gap-fill if the four-state contract isn't fully covered |
| Conflict files | src/roster_intel/simulation.py (also touched by V1-43's dependency chain -- do not let two lanes edit it at once) |
| Dependency | none blocking |
| False-green risk | LOW if the function is tested; check it isn't a stub |
| **Classification** | **A/B** |
| Note | STRONGEST 'NOT STARTED whose mechanism already exists' finding this pass. |

#### V1-45: Trade calculator

| Field | Value |
|---|---|
| Required level | L4 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. Owner status literally 'ALREADY COMPLETE — VERIFY ONLY'. |
| Exact missing evidence | An L4 production-consumer checklist run -- no code gap named anywhere in the row's own text. |
| Owner lane | Lane 2 / Integration |
| Existing PR/commit/instrument | the live /trade page + calculator, per owner attestation |
| Production access needed? | yes (or a full local rebuild-and-click-through) |
| Expected engineering effort | LOW -- a checklist run, not a build |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW -- owner already attests completeness; risk is only in NOT running the checklist |
| **Classification** | **C** |

#### V1-56: FAAB league context panel

| Field | Value |
|---|---|
| Required level | L4 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. Owner status 'VERIFY ONLY'. |
| Exact missing evidence | L4 production-consumer checklist. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | live /waivers panel per owner attestation |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-61: Sharp Roster Percentage

| Field | Value |
|---|---|
| Required level | L4 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. Owner status 'VERIFY ONLY'. |
| Exact missing evidence | L4 production-consumer checklist. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | /market/sharp-roster-percentage, live |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-60: FFPC roster lane real or honestly empty

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. #911 merged -- CollectResult gains status/unavailable_reason, FFPC lane returns no_cohort_managers_on_platform instead of a silent empty success. Verified in the diff. |
| Exact missing evidence | L2 prod-side board measurement (FFPC contributes zero rosters today, per the row's own text -- the measurement IS that zero, reported honestly rather than silently). |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | src/sharp/roster_collect.py (on main, post-#911) |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

---

## NEXT 10

Continuing class C (production-check-only) rows plus the two highest-confidence class D (small-repair) rows with fully-scoped fixes: V1-136 (Lane 8's own reconciliation plan) and V1-132 (a precisely measured single-source-blend defect with a named injection-path fix).

#### V1-57: FAAB bid-history collection is scheduled, not manual

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. #911 merged -- systemd timer template + installer wiring confirmed in the diff, matches the installer's own naming convention. |
| Exact missing evidence | The unit installed and FIRING on the actual production box -- not claimable from a dev environment. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | deploy/systemd/dynasty-faab-history.{service,timer}.template (on main) |
| Production access needed? | yes -- literally just needs someone to check systemctl status on the box |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-65: Insider Trading / cross-league ownership

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. L1 COMPLETE and mutation-proven at Integration (#911). L2 needs an eligibility census against the deployed ledger -- data/intel/ledger.sqlite3 is schema-only (0 rows) in every non-prod environment, so a 0-count here would be an environment artifact, not a finding. |
| Exact missing evidence | Run the eligibility census on the DEPLOYED ledger and record how many leagues each filter (Sharp vs Insider) admits and how the two sets differ. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | src/intel/leads.py + the three insider modules, mutation-guarded (on main) |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-129: External crowd-FAAB evidence comparable/fresh/position-capable

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. #911 merged -- src/trade/faab_comparability.py single owner, adversarially reviewed across 30 combinations, faab_engine.py zero-byte diff. |
| Exact missing evidence | L2 needs the crowd ledger, which is prod-only (gitignored) and currently reports 'missing' because the legacy accumulated ledger hard-excludes on read -- needs the fetcher to re-accumulate on the box. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | src/trade/faab_comparability.py (on main) |
| Production access needed? | yes |
| Expected engineering effort | LOW code (zero), MEDIUM logistics (ledger needs to re-accumulate post-deploy, not instant) |
| Conflict files | none |
| Dependency | one or more crowd-FAAB fetch cycles on prod |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-83: Alert cooldown keyed on delivery

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. #909 merged. |
| Exact missing evidence | L3 deployed-SHA checklist run. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | #909 (on main) |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none -- paired with V1-84, same PR, run together |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-84: 503 is not exempt from production health failure

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. #909 merged (same PR as V1-83). |
| Exact missing evidence | L3 deployed-SHA checklist run. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | #909 (on main) |
| Production access needed? | yes |
| Expected engineering effort | LOW |
| Conflict files | none -- run together with V1-83 in one checklist pass |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-19: Multi-format dynasty source archive

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. §7 checklist executed 2026-08-18: items 1-2 PASS at L3 on LIVE PRODUCTION already (21/21 DYNASTY with evidence, unauthenticated). Item 3 PARTIAL, item 4 N/A. |
| Exact missing evidence | Item 3 needs a pre-deploy snapshot captured before the next scrape cycle -- a scheduling/capture task, not a new auth barrier (items 1-2 already ran unauthenticated). |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | the §7 checklist script itself (already run once) |
| Production access needed? | no new auth needed -- just needs someone to trigger a capture at the right moment |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | a scrape cycle boundary |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-58: Sharp cohort proven populated in production

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. Verification artifacts end at 502/401 'unverifiable_unauthenticated'. |
| Exact missing evidence | An authenticated production read of the cohort count. |
| Owner lane | Lane 4 |
| Existing PR/commit/instrument | src/sharp/cohort.py (on main) |
| Production access needed? | yes, authenticated |
| Expected engineering effort | LOW |
| Conflict files | none |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **C** |

#### V1-49: Individual special-teams scoring

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IN PROGRESS. #915 already merged and closed the headline defect (kr_yd/pr_yd/st_td) plus found and fixed a 10,842.89-pt SAF-normalization engine bug (0.00 consumer-reachable). FRESH THIS PASS: PR #1027 (open, unmerged, docs-only) re-audited and found the row's real remaining gate is `host_native_scoring`'s PRODUCTION_ONLY promotion path -- 4 of 10 promotion-gate items still open, no code defect remains. Also found two more private position tables lacking SAF (replacement.py, lineup.py) but VERIFIED UNREACHABLE on the live board (Sleeper never emits 'SAF') -- correctly NOT repaired per the sprint's 'do not repair unreachable defects' instruction. |
| Exact missing evidence | 4 of 10 production promotion-gate items -- these are PRODUCTION-ONLY checks, not code. |
| Owner lane | Lane 3 (Scoring/Season/Power) |
| Existing PR/commit/instrument | #915 (merged), #1027 (open PR, docs-only audit) |
| Production access needed? | yes -- the remaining gate items are production-only |
| Expected engineering effort | LOW code (zero), MEDIUM logistics (needs someone with prod access to run the promotion-gate checklist) |
| Conflict files | none -- #1027 is docs-only |
| Dependency | #1027 landing first (trivial, docs-only, should merge same-day) |
| False-green risk | LOW -- #1027's audit is unusually rigorous (checked the live exports/latest export directly for 'SAF' spelling before declining to touch code) |
| **Classification** | **C** |

#### V1-136: Source acquisition is secure and auth state is explicit

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | NOT STARTED per the contract. FRESH THIS PASS: PR #1001 is OPEN (Lane 8, three slices). Slice 1 (audit doc, 9 questions answered with code citations) is FEATURE_GREEN. Slice 3 (failure-state instrumentation for the PLAIN idpShow board) is FEATURE_GREEN but INCOMPLETE: post-#1012, idpShowCombined (not the plain board) became the sole voting source, and Slice 3's instrumentation was written against the now-retired plain board's main() path. A follow-up commit on the same branch (be5d1ef40) maps the exact 5-point reconciliation Claude 5 needs to do. |
| Exact missing evidence | Reconcile Slice 3's instrumentation onto the idpShowCombined path (the board that actually votes) -- a fully-scoped plan already exists in docs/sources/LANE8_POST_1012_RECONCILIATION_AUDIT.md. Then the row still needs its own L2 measured population statement once merged. |
| Owner lane | Lane 8 |
| Existing PR/commit/instrument | PR #1001 (open, unmerged), scripts/fetch_idpshow.py + src/sources/acquisition_state.py |
| Production access needed? | no for the code reconciliation; yes eventually for the L2 statement |
| Expected engineering effort | LOW-MEDIUM -- the plan is fully specified, it is 'apply the same instrumentation pattern to a second code path' |
| Conflict files | scripts/fetch_idpshow.py (Lane 8's own file, PR #1001 already holds it) |
| Dependency | PR #1001 merging first |
| False-green risk | LOW -- the correction was found and disclosed by the same PR that would have shipped the gap |
| **Classification** | **D** |

#### V1-132: Horizon pick year not a single-vendor dependency

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | NOT STARTED. Measured DEFECT: the horizon year's 12 tier-row cells blend idpTradeCalc ALONE, because far-future pick injection clones from the RAW payload while ktcSfTep pick values arrive via later CSV enrichment. F-30 already made the horizon's GUARANTEE independent of this; the blended VALUE still isn't. |
| Exact missing evidence | Route ktcSfTep pick values into the same injection path the horizon-year cloning reads from. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | the far-future pick injection code (_inject_far_future_pick_sources, per CLAUDE.md's pipeline description) |
| Production access needed? | no for the fix; yes to confirm the horizon-year blend now shows 2+ sources |
| Expected engineering effort | LOW-MEDIUM -- a sequencing/ordering fix in an already-understood pipeline stage |
| Conflict files | src/api/data_contract.py's pick-injection stage |
| Dependency | none |
| False-green risk | LOW -- the defect is already precisely measured (12 cells, single-source) |
| **Classification** | **D** |

---

## SURPLUS 10

Mostly class D/E: small, well-scoped repairs (V1-131 nav gating, V1-85 reporting-only fix, V1-80 gate coverage) plus bounded implementations (V1-41's clean re-implementation, V1-96's data-reconciliation bug, V1-52's engine retirement) and two tentatively-classed rows (V1-104, V1-86) flagged for a closer read before committing engineering time.

#### V1-131: Nav does not offer a page whose endpoints all 503

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | NOT STARTED. Gating-only fix -- the Consensus Edge FEATURE itself stays POST-V1; this row only asks that the nav item be hidden/gated while its three endpoints 503. |
| Exact missing evidence | Hide or gate the one nav entry. |
| Owner lane | Lane 6 |
| Existing PR/commit/instrument | frontend nav config |
| Production access needed? | no |
| Expected engineering effort | LOW -- a conditional nav-item render, explicitly scoped to gating not the feature |
| Conflict files | frontend nav component |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **D** |

#### V1-85: pickAnchors reporting consistent with the contract

| Field | Value |
|---|---|
| Required level | L1 |
| Current actual implementation | NOT STARTED. RECLASSIFIED (contract §8.2): originally called a P0 value-corruption defect, REFUTED by measurement -- the canonical contract reads the CSV independently and gets all 36 vendor pick rows, so there is NO demonstrated value error. Correct classification is a P2 REPORTING inconsistency only. |
| Exact missing evidence | Whatever field/message currently reports the (non-existent) anchor-loss inconsistently with the contract's actual (correct) behavior -- a display/logging fix, not a value fix. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | none named -- needs a fresh look now that scope is confirmed small |
| Production access needed? | no |
| Expected engineering effort | LOW -- P2 reporting fix, explicitly NOT a value-correctness issue |
| Conflict files | wherever pickAnchors provenance is logged/reported |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **D** |

#### V1-80: The critical-source gate can fire for DLF

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | NOT STARTED. Source-health correctness -- the gate exists for other sources but apparently not DLF. |
| Exact missing evidence | Add DLF to the critical-source gate's coverage. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | the critical-source gate itself (exists for other sources, per the row's framing) |
| Production access needed? | no for the fix; yes to confirm it fires correctly |
| Expected engineering effort | LOW -- likely a config/list addition plus a test |
| Conflict files | the critical-source gate module |
| Dependency | none |
| False-green risk | LOW |
| **Classification** | **D** |

#### V1-87: Every live feature flag is visible to operators

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | BLOCKED, no blocker reason given in the row's own text (unusual -- every other BLOCKED row in this census names one). Description IS the fix: a defaulted-ON flag is absent from /api/status. |
| Exact missing evidence | Add the missing flag to /api/status's enumeration, OR find out why this is BLOCKED when the fix reads simple -- worth a fresh look since the blocker isn't stated. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | /api/status (on main) |
| Production access needed? | no for the fix |
| Expected engineering effort | LOW if the blocker turns out to be stale/administrative |
| Conflict files | src/api (status endpoint) |
| Dependency | unknown -- the unstated blocker itself |
| False-green risk | LOW |
| **Classification** | **D** |
| Note | Candidate 'blocker may be stale' row -- the contract names BLOCKED rows' reasons everywhere else; this one doesn't, worth checking whether that's an omission. |

#### V1-104: Human review / admin controls

| Field | Value |
|---|---|
| Required level | L1 |
| Current actual implementation | IN PROGRESS. Explicitly scoped NARROW today -- sharp-identities only. |
| Exact missing evidence | Either the row's narrow scope is already satisfied at L1 (a RED->GREEN test) and just needs promotion, or the narrow scope itself needs finishing -- ambiguous from row text alone. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | sharp-identity admin review code (exists, scope unconfirmed) |
| Production access needed? | no for L1 |
| Expected engineering effort | LOW if only promotion is needed, MEDIUM if the narrow scope itself is incomplete |
| Conflict files | admin review UI/API |
| Dependency | none known |
| False-green risk | LOW |
| **Classification** | **B/D (tentative)** |

#### V1-86: The E2E tracker identity works

| Field | Value |
|---|---|
| Required level | L3 |
| Current actual implementation | IMPLEMENTED_UNVERIFIED. CI/E2E false-green defect: 14 duplicate trackers, close step never fired. |
| Exact missing evidence | Unclear from row text whether the fix is merged and only needs a checklist, or whether the dedup itself is still open -- flagged for a closer read next pass rather than guessed here. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | unclear -- needs its own PR/commit search before committing to a class |
| Production access needed? | possibly, for the L3 check |
| Expected engineering effort | UNKNOWN pending closer read |
| Conflict files | CI config |
| Dependency | none known |
| False-green risk | MEDIUM -- flagged, not resolved, this pass |
| **Classification** | **C/D (tentative)** |

#### V1-41: 'Use Team Context' toggle, ON by default

| Field | Value |
|---|---|
| Required level | L1 |
| Current actual implementation | NOT STARTED per the contract. FRESH THIS PASS: a commit titled exactly 'V1-41: "Use Team Context" — the shared mode, ON by default (C3-CTX-01 / #842)' exists (196356359), but it lives on `claude/v1-trade-roster-rehearsal` -- a 100-file, 20,751-insertion REHEARSAL branch carrying an explicit 'R1 PROTOTYPE — ROSTER-OWNED, DO NOT CHERRY-PICK' commit and superseded work (V1-34/V1-130, already independently VERIFIED via #929 through a different branch). No open PR for this branch or commit. |
| Exact missing evidence | A CLEAN re-implementation against current main -- the rehearsal branch is explicitly marked non-mergeable evidence, per this dispatcher's own prior-cycle records ('rehearsal-2 is evidence only and must never become a merge candidate'). Cherry-picking the single commit risks pulling in stale context from the superseded work around it. |
| Owner lane | Lane 2 |
| Existing PR/commit/instrument | 196356359 (reference/evidence only, NOT a mergeable instrument) |
| Production access needed? | no |
| Expected engineering effort | LOW-MEDIUM -- the design is proven out, but must be typed fresh against main, not lifted |
| Conflict files | whatever V1-41's toggle touches -- likely a settings/context module |
| Dependency | none blocking |
| False-green risk | MEDIUM if someone is tempted to cherry-pick despite the explicit warning |
| **Classification** | **E** |
| Note | A 'mechanism exists' row where the existing mechanism is explicitly NOT reusable -- flagged so nobody wastes an hour discovering that the hard way. |

#### V1-96: Historical franchise continuity

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | NOT STARTED. Live data defect: 2024 declares ten teams, carries eight standings rows. |
| Exact missing evidence | A reconciliation fix in the historical standings builder. |
| Owner lane | Lane 1 (Roster Intelligence, adjacent) or Lane 9 (Public/Storytelling, C9-HIST-01) |
| Existing PR/commit/instrument | src/public_league/matchup_recap.py, identity.py (candidate files, not confirmed as the exact bug site) |
| Production access needed? | no for the fix; yes to confirm the repaired count |
| Expected engineering effort | MEDIUM -- a real data-reconciliation bug, scope depends on root cause |
| Conflict files | src/public_league/** historical builders |
| Dependency | none |
| False-green risk | MEDIUM -- an off-by-two could hide a deeper identity-join gap |
| **Classification** | **E** |

#### V1-52: One weekly power-rankings engine

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IN PROGRESS. Items A-C SHIPPING_AND_PROVEN via #979. Item D (retire the legacy src/public_league/power.py engine + repoint power.jsx/overview.currentPowerLeader) is the sole remaining gap, explicitly named and NOT started. |
| Exact missing evidence | Retire the legacy engine and repoint two consumers to the canonical one. Explicitly requires production-scale 12-owner lens-agreement measurement, which needs gitignored data/ros/team_strength/latest.json. |
| Owner lane | Lane 3 |
| Existing PR/commit/instrument | #979 (merged); #923 unmerged (contains the Step-5 retirement, correctly held back per this row's own text) |
| Production access needed? | yes for the L2 measurement |
| Expected engineering effort | MEDIUM -- real consolidation work (delete an engine, repoint 2 consumers), plus a prod-side measurement |
| Conflict files | src/public_league/power.py, power.jsx, overview.currentPowerLeader, #923's branch |
| Dependency | none blocking, but #923 is the natural vehicle |
| False-green risk | LOW |
| **Classification** | **E** |

#### V1-91: Partial runs cannot report as healthy

| Field | Value |
|---|---|
| Required level | L2 |
| Current actual implementation | IN PROGRESS. False-green repair, source-health correctness. |
| Exact missing evidence | Not enough in the row's own text to classify precisely -- needs a fresh PR/commit search. |
| Owner lane | Lane 5 |
| Existing PR/commit/instrument | unclear |
| Production access needed? | unclear |
| Expected engineering effort | UNKNOWN, tentatively MEDIUM |
| Conflict files | source-health gate code |
| Dependency | none known |
| False-green risk | MEDIUM |
| **Classification** | **D/E (tentative)** |

---

## Named but excluded from the ranked 25 (owner-decision-blocked or lower priority)

- **V1-89** (H): DraftSharks staleness resolved -- An owner decision, not code.
- **V1-110** (H): Design primitives / tokens / shell / focus -- An owner decision on token direction before further work is well-founded.
- **V1-105** (H): Performance baselines captured before feature work -- Either backfill what can still be measured, or an owner call on how to handle units where the 'before' window has already closed.
- **V1-103** (D/E (tentative)): Security repairs -- A fresh count of which W22 sub-findings are closed vs open -- not resolvable from the row text without reading the W22 audit record directly.
- **V1-59** (E): Sharp bootstrap stops failing -- A fix for the timeout/locking failure mode.


## Not examined this pass

25 of the 55 remaining non-VERIFIED, non-Tier-A rows were not individually re-verified this pass
(V1-11, V1-15, V1-16, V1-17, V1-20, V1-21, V1-22, V1-23, V1-25, V1-27, V1-35, V1-36, V1-37, V1-43,
V1-62, V1-68, V1-76, V1-89's siblings in the same audit family, V1-101, V1-102, V1-109, V1-111,
V1-123, V1-124, V1-125, V1-126, V1-131's siblings). Most of the L5 audit-family rows (V1-11, V1-15,
V1-16, V1-17, V1-20, V1-27) are the explicit `BLOCKED-EXTERNAL`-on-auth checklist family named in
the contract's own §9 table -- real candidates once an authenticated production session is
available, but not reachable from here, so left off the ranked 25 by design (class G territory).
V1-123/124/125/126 (`C10-CLOSE-*`) are the final closure gates and are dependent on most of the
rest of V1 finishing first -- not realistic candidates yet regardless of classification.

## Summary counts

| Bucket | Row count |
|---|---|
| NEXT 5 | 5 |
| NEXT 10 | 10 |
| SURPLUS 10 | 10 |
| **Total ranked** | **25** |
| Named, excluded (owner-decision-blocked or lower priority) | 5 |
| Not examined this pass | 25 |

**This dispatcher counted no VERIFIED rows, promoted no row, and modified no code in producing this
document.** Every classification is an estimate for prioritization only; actual promotion requires
each row's own required verification level to be satisfied and requires Integration/Claude 5 action.
