# V1_70_ATTACK_MATRIX

**Read-only independent audit. No code modified. No V1 status counted or promoted by this document.**
**Author: this repository's independent traffic-control/dispatch record (no lane number — see `docs/claude-dispatch/LANE_STATUS.json` governanceCorrection_C31). Delivered to Claude 5 / Integration via this file on PR #1000.**

Repository: `jasonleetucker-code/riskittogetthebrisket`
Baseline: 65 / 136 = 47.8% VERIFIED. Target: 96 / 136 = 70.6% (31 additional VERIFIED rows needed).
Rows audited: all 71 non-VERIFIED rows in `docs/VERSION_1_COMPLETION_CONTRACT.md` §3, as of `origin/main`
(contract self-check: VERIFIED=65, IMPLEMENTED_UNVERIFIED=19, IN PROGRESS=20, NOT STARTED=30, BLOCKED=2,
sum of non-VERIFIED = 71, denominator 136 -- confirmed internally consistent).

## Method and honesty notes

- Every row's data comes from (a) its own full text in the canonical contract on `origin/main` --
  this repo's documented convention front-loads PR numbers, checklist results, and named blockers
  directly into row text, so the row text is itself primary evidence in most cases; (b) targeted
  `git log` / `git ls-tree` verification performed this pass where flagged; (c) this dispatcher's
  own accumulated cross-cycle observation of merge timing across ~60 dispatch cycles this session.
- This is **not** exhaustive git archaeology on all 71 rows. A subset of rows reference a PR number
  whose exact current merge state could not be independently reconfirmed within this pass -- those
  are explicitly marked "RE-CHECK" or "pending confirmation" in their closure class rather than
  asserted with false confidence. Anyone acting on a RE-CHECK row should confirm the referenced PR's
  merge state first.
- Closure class legend: **A** = STATUS_STALE (proof already exists, contract just hasn't caught up)
  · **B** = VERIFICATION_ONLY (implementation exists, only a checklist/measurement run remains)
  · **C** = SMALL_REPAIR · **D** = BOUNDED_IMPLEMENTATION · **E** = SUBSTANTIVE
  · **F** = PRODUCTION_AUTH (needs on-box/deployed/authenticated access this dispatch role does not have)
  · **G** = OWNER_BLOCKED (needs a human/owner decision before any implementation is legitimate).
- Closure class distribution across all 71 rows: {'F': 6, 'B': 24, 'C': 19, 'D': 10, 'A': 2, 'E': 1, 'G': 9}
- Priority ordering below is closure class first (A easiest), then conflict risk, then whether the
  row needed a RE-CHECK flag. **This is a legitimate-closure prioritization, not a promotion list** --
  every row still needs its own required verification level satisfied before VERIFIED is honest.

## Cross-cutting findings (the "specially hunt for" list)

- **Stale blocker, independently confirmed:** V1-32's own row text names PR #1004 as an unmerged
  blocker. Verified this pass: `git log --oneline --all | grep -i 1004` shows
  `25ec0826a Merge pull request #1004 from .../claude/v1-32-weakness-single-owner-guard` is on `main`,
  and `tests/roster_intel/test_strength_weakness_single_owner.py` is present in the tree. The row's
  refutation is now stale exactly the way a stale promotion claim would be (per method rule (r),
  established earlier this session from the V1-88 precedent). Closure A.
- **Lane 4 on-box batch (V1-57, V1-60, V1-65, V1-129):** all four need only host/SSH-level access to
  a running production box (an existing scheduled unit firing, a live crowd-FAAB ledger accumulating,
  an eligibility census against a populated ledger) -- zero code change, all four run independently
  of each other and of everything else in this matrix.
- **L1 rows being treated like L3/L4:** none found this pass where a row's *required* level was
  inflated above what the contract's own §2 definitions justify; the inverse pattern (L4 rows sitting
  on stale `IMPLEMENTED_UNVERIFIED` after their implementation half already landed -- V1-83, V1-84,
  V1-111, V1-129, V1-65) is far more common and is the dominant closure-B pattern in this matrix.
- **Production checklists that can close multiple independent rows in one pass:** the C1-ACQ on-box
  checklist family (V1-15, V1-16, V1-17) is one checklist shape run against `data/retention/` and
  `data/intel/` on the deployed box; the Lane 4 on-box batch above is a second such cluster.
- **Duplicate work between Claudes 1-6/8 and 9-13:** V1-37 (VA consolidation) overlaps Claude 9's
  active C3 Trade Substrate work (#962, not reconfirmed merged this pass); V1-133/134/135/136 overlap
  Lane 8's very active bridge-owner session (#954, #971, #993, #1008, #1012) almost exactly --
  V1-136 in particular has an observed live branch `claude/lane8-v1-136-idpshow-audit` named for this
  exact row ID, making it the highest-confidence overlap in the whole matrix.
- **Old PRs containing useful current-valid instruments:** #909 (V1-83/V1-84 pair), #911 (V1-60,
  V1-65, V1-129 -- three separate rows off one merged PR), #912 (V1-101), #979 (V1-52 items A-C),
  #984 (V1-111) all already contain everything needed except the row's own required verification
  level -- no further code needed, only the checklist/measurement.

---

## TOP 10 -- easiest legitimate closures

Highest-confidence, lowest-conflict rows. Several are pure verification passes against already-merged code; the strongest (V1-32) is an independently-confirmed stale refutation.

#### V1-32: Canonical Team Weakness / Need Priority

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L1 |
| Actual current-main state | L2 evidence is STRONG and already measured: #1007's offline verify gives 216 rungs PASS, 215 rung-credits PASS at EVIDENCE-L2, 0 violations, 11/0/2 pass/fail/unmeasurable, plus tests/roster_intel/test_verify_offline.py 5/5. Row's OWN text names the sole remaining blocker as '#1004, which is not on main (checked, not assumed)'. |
| Open PRs | none open under #1004 (already merged) |
| Merged commits/PRs | **VERIFIED THIS PASS, TWO WAYS: #1004 (`25ec0826a`) IS ON MAIN** (`git merge-base --is-ancestor 25ec0826a origin/main` => true), guard file `tests/roster_intel/test_strength_weakness_single_owner.py` present in the tree. **STRONGER FINDING: the row text asserting '#1004 not on main' was itself written by #1010 (`bd9519871`), whose OWN first parent IS #1004's merge commit** (`git show bd9519871 -m` confirms `#1004` is #1010's base) -- so the claim was false at the moment it was written against #1010's own tree, not merely stale from later drift. This is a sharper instance of the stale-refutation defect class than ordinary time-lag (cf. V1-88): here the refuting PR's own ancestry already contained the fix it claimed was absent. Self-correction note: this dispatcher's own cycle-55 LANE_STATUS record ('V1-32 correctly stayed IN PROGRESS... same discipline this record has praised') accepted the row's claim at face value and did not check #1010's merge parentage -- that check is what this pass adds. |
| Test evidence | tests/roster_intel/test_strength_weakness_single_owner.py is a structural AST scan (not a live-injected mutation) over every OWNER_SYMBOL_PATHS entry across src/, scripts/, server.py -- confirmed by reading its content this pass. It inherently catches any second definition anywhere in scan scope without per-run setup, but the row's own close condition asks for a 'reperform the single-owner mutation' -- i.e. an applied decoy-module confirmation in the MC1/MC2/MC3 style used elsewhere this session (inject a decoy owner symbol, confirm RED, remove, confirm GREEN). That is a bounded verification action, not new production code. |
| Production evidence | 216 rungs / 215 credits / 0 violations, per #1007's offline verify script, already measured |
| Exact missing requirement | Nothing structural. The row's OWN stated close condition (land #1004, reperform the single-owner mutation test) has its first half satisfied by #1004's existence on main; the second half is running one applied-mutation confirmation against the now-present guard test and writing the promotion. This is a status-stale row with one small bounded verification step, not an implementation gap. |
| Active work claim | none found |
| Conflict risk | none -- #1004 already merged cleanly |
| **Estimated closure class** | **A/B -- STATUS_STALE plus one bounded verification step (apply/confirm the single-owner mutation against the guard already on main).** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none -- ready right now |
| Can run in parallel with | almost anything |
| DO_NOT_TOUCH_FILES | none -- read-only verification task |

#### V1-42: Exact before->apply->re-solve->after roster simulation

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L2 |
| Actual current-main state | This dispatcher tracked, across MANY cycles this session, that #913's W3 already supplies the consumer (simulate_roster_change) this row lacked -- yet the row remains NOT STARTED on main. This is the single most persistent stale-status finding across the whole session. |
| Open PRs | none currently open under #913 (its state after merge needs re-confirmation) |
| Merged commits/PRs | #913 -- believed merged earlier in the session (tracked repeatedly in dispatch cycles 1-20) but its relationship to closing V1-42 specifically was never confirmed by this dispatcher, only flagged as worth checking |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm whether #913's W3 consumer is sufficient to promote this row; if so this is class A, not D |
| Active work claim | none found |
| Conflict risk | medium -- trade simulation is single-writer territory |
| **Estimated closure class** | **A/B pending confirmation -- HIGH PRIORITY RE-CHECK, flagged repeatedly this session and never resolved** |
| NUMERATOR_VALUE | 1 |
| Dependencies | confirm #913's current state |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/trade/trade_simulator.py |

#### V1-101: /admin fmtPassExpiry crash repaired

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L4 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text: fixed via #912, which this session confirmed MERGED long ago (multiple prior dispatch cycles reference #912 as landed and closing several other rows) |
| Open PRs | none -- #912 already merged and heavily verified this session |
| Merged commits/PRs | #912 (b3ea4cf5a, confirmed merged early this session) |
| Test evidence | not independently re-checked for this specific crash fix this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | L4 needs the deployed build serving this fix and a real admin-page consumer check -- likely close given #912's broader verification this session |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-19: Multi-format dynasty source archive

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L5 |
| Actual current-main state | §7 checklist executed 2026-08-18: items 1-2 PASS AT L3 ON LIVE PRODUCTION (21/21 DYNASTY with evidence). Item 3 PARTIAL, item 4 N/A. |
| Open PRs | none found |
| Merged commits/PRs | not stated (checklist-only row) |
| Test evidence | checklist-based |
| Production evidence | 21/21 DYNASTY-verified sources confirmed live in production |
| Exact missing requirement | Item 3 needs a PRE-DEPLOY snapshot captured before the next scrape cycle -- nobody has captured one yet. This is a scheduling/capture task, not new code. |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | a scrape cycle where someone captures the pre-deploy snapshot |
| Can run in parallel with | most other rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-20: Game type proven per feed, fails closed

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L5 |
| Actual current-main state | Same C1-SRC family as V1-19; no independent checklist text in this row |
| Open PRs | none found |
| Merged commits/PRs | not verified this pass |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Likely closeable alongside V1-19's §7 checklist if scope overlaps -- needs confirmation |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | V1-19's checklist artifact, if shared |
| Can run in parallel with | V1-19 |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-45: Trade calculator

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L4 |
| Canonical owner lane | L2 |
| Actual current-main state | Row's OWN text: owner status 'ALREADY COMPLETE -- VERIFY ONLY' |
| Open PRs | none found |
| Merged commits/PRs | presumed complete per owner status |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | The L4 production-consumer proof only -- no implementation gap per the owner's own classification |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-56: FAAB league context panel

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L4 |
| Canonical owner lane | L4 |
| Actual current-main state | Row's OWN text: owner status 'VERIFY ONLY' |
| Open PRs | none found |
| Merged commits/PRs | presumed complete per owner status |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | L4 production-consumer proof only |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-61: Sharp Roster Percentage

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L4 |
| Canonical owner lane | L4 |
| Actual current-main state | Row's OWN text: owner status 'VERIFY ONLY' |
| Open PRs | none found |
| Merged commits/PRs | presumed complete per owner status |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | L4 production-consumer proof only |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-83: Alert cooldown keyed on delivery

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L5 |
| Actual current-main state | #909 merged (row text) |
| Open PRs | none -- merged |
| Merged commits/PRs | #909 |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | L3 deployed-SHA checklist run |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access |
| Can run in parallel with | V1-84 (same #909) |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-84: 503 is not exempt from production health failure

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L5 |
| Actual current-main state | #909 merged (row text) -- same PR as V1-83 |
| Open PRs | none -- merged |
| Merged commits/PRs | #909 |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | L3 deployed-SHA checklist run, likely the SAME session as V1-83's |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | deployed verification access -- pair with V1-83 |
| Can run in parallel with | V1-83 |
| DO_NOT_TOUCH_FILES | none -- pure verification |

---

## NEXT 10

Still closure class A/B in the majority, slightly higher conflict risk or a RE-CHECK flag on the referenced PR's exact merge state.

#### V1-111: Premium migration of the high-use routes (Rankings first)

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L4 |
| Canonical owner lane | L6 |
| Actual current-main state | EXTREMELY well-documented row (own text): #984 merged (5c43da9e8), Rankings reference route + Universal Player Profile both ship on an additive .psi-editorial token scope. Independently measured at Integration: 0 WCAG contrast failures (down from 11, agreeing with a separate 187-node axe run), zero prototype constants, both CI gates green at the merged head. Status explicitly corrected NOT STARTED->IMPLEMENTED_UNVERIFIED, and explicitly NOT promoted further because L4 needs a PRODUCTION consumer, not a merge. |
| Open PRs | none -- #984 already merged and heavily documented |
| Merged commits/PRs | #984 (5c43da9e8) |
| Test evidence | docs/psi/PR_A_VISUAL_VERIFICATION_2026-08-20.md (full record, independently measured, not just claimed) |
| Production evidence | none yet -- this IS the missing piece |
| Exact missing requirement | Deploy the build serving these routes to production, and confirm a real consumer exists there. This is the CLEANEST L4 gap in the whole matrix: everything below L4 is already done and independently measured. |
| Active work claim | none found |
| Conflict risk | none |
| **Estimated closure class** | **B -- pure deployment + production consumer confirmation, zero code change needed** |
| NUMERATOR_VALUE | 1 |
| Dependencies | a production deploy |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none -- pure verification once deployed |

#### V1-129: External crowd-FAAB evidence is comparable, fresh and position-capable

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L2 |
| Canonical owner lane | L4 |
| Actual current-main state | #911 merged 2026-08-19. src/trade/faab_comparability.py is the single owner. Adversarial review confirmed the headline invariant across 30 combinations. Same Lane-4 on-box batch as V1-57/V1-60. |
| Open PRs | none -- already merged |
| Merged commits/PRs | #911 |
| Test evidence | adversarial review, 30 combinations, every leaf key diffed (own row text) |
| Production evidence | needs the prod-only crowd ledger (gitignored) |
| Exact missing requirement | Host access to read the crowd ledger and confirm crowdMarket is not stuck on 'missing' post-fetcher-reaccumulation |
| Active work claim | none found |
| Conflict risk | none |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | host/SSH access |
| Can run in parallel with | V1-57, V1-60, V1-65 (same batch) |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-133: Multi-bridge cross-position translation

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L8 |
| Actual current-main state | Owner decision 2026-08-20, #954. This session tracked Lane 8 as VERY active (multiple merged PRs: #954 itself, #971, #993, #1008, #1012) building exactly this bridge infrastructure. |
| Open PRs | check current Lane 8 PRs -- claude/lane8-multi-bridge-translation and claude/lane8-v1-136-idpshow-audit branches observed active this session |
| Merged commits/PRs | #954 (foundation), #993 ('Lane 8 PR B: multi-bridge cross-position translation owner (production valuation change)') -- #993's title matches this row almost exactly |
| Test evidence | not independently re-read this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm whether #993 already satisfies this row -- title match is strong. RE-CHECK, likely close to class A/B rather than D. |
| Active work claim | active Lane 8 work |
| Conflict risk | none -- Lane 8 owns this outright per the row's own L8 tag |
| **Estimated closure class** | **B (if #993 covers it) or D (if not)** |
| NUMERATOR_VALUE | 1 |
| Dependencies | Lane 8's own sequencing |
| Can run in parallel with | nothing outside Lane 8 should touch this |
| DO_NOT_TOUCH_FILES | Lane 8's bridge files -- do not duplicate, Lane 8 owns this |

#### V1-136: Source acquisition is secure and its auth state is explicit

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L8 |
| Actual current-main state | Same Lane 8 program -- credential-dependent sources must be UNVERIFIABLE, never healthy/zero. claude/lane8-v1-136-idpshow-audit branch name directly matches this row's ID, strongly suggesting active work. |
| Open PRs | claude/lane8-v1-136-idpshow-audit -- observed active multiple times this session |
| Merged commits/PRs | not yet confirmed as merged |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm this branch's current PR state -- the branch NAME directly targets this row |
| Active work claim | active Lane 8 work, branch literally named for this row |
| Conflict risk | none -- Lane 8 owns this outright |
| **Estimated closure class** | **B -- HIGH CONFIDENCE, branch is purpose-built for exactly this row** |
| NUMERATOR_VALUE | 1 |
| Dependencies | that branch landing |
| Can run in parallel with | nothing outside Lane 8 |
| DO_NOT_TOUCH_FILES | Lane 8's bridge/acquisition files |

#### V1-31: Canonical Team Strength

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L1 |
| Actual current-main state | Row text: '#914 builds the owner' -- #914's merge status not independently confirmed this pass (a commit '45fd06f0f V1-31: retire /phases duplicate Team Strength inputs' exists in history, subject matches this row's scope but PR number for it is unclear) |
| Open PRs | none found under #914 specifically |
| Merged commits/PRs | possibly related work already landed under a different PR number -- needs confirmation |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm #914 (or its actual PR number) is merged and reaches L2 measured board consistency |
| Active work claim | none found |
| Conflict risk | medium -- shares src/roster_intel/ with V1-32 |
| **Estimated closure class** | **B (if #914-equivalent is in fact merged) or D (if not)** |
| NUMERATOR_VALUE | 1 |
| Dependencies | resolve #914's true merge state first |
| Can run in parallel with | V1-32 shares infrastructure -- coordinate, don't duplicate |
| DO_NOT_TOUCH_FILES | src/roster_intel/strength.py-equivalent (verify exact path) |

#### V1-49: Individual special-teams scoring

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L3 |
| Actual current-main state | #915 measured the headline defect ALREADY CLOSED (B7/W18-F003 wired kr_yd/pr_yd/st_td, re-verified 1,280 rows/2,239.40pts) and found a bigger defect underneath: SAF scored a well-formed 0.000 (10,842.89-pt engine defect, 2025 REG) but was 0.00 CONSUMER-REACHABLE because both consumers already normalized SAF privately. Consumer-visible delta of repairs: 218.12 pts / 0.167%. |
| Open PRs | check #915's current merge state -- not re-verified this pass |
| Merged commits/PRs | #915 contains the measurement; unclear if the SAF fix itself has landed |
| Test evidence | not verified this pass |
| Production evidence | 1,280-row re-verification already performed |
| Exact missing requirement | Confirm whether #915's SAF fix is merged; if so, this needs only the L2 measured statement written up |
| Active work claim | none found |
| Conflict risk | medium -- canonical scoring engine |
| **Estimated closure class** | **B (if #915 landed) or C (if not)** |
| NUMERATOR_VALUE | 1 |
| Dependencies | #915's merge state |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/scoring/ (canonical scoring engine) |

#### V1-57: FAAB bid-history collection is scheduled, not a manual step

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L4 |
| Actual current-main state | #911 merged 2026-08-19. Scheduler unit verified in the diff, matches installer naming convention, fires 07:40 UTC clear of other jobs. This dispatcher's Lane-4 on-box batch (V1-57/V1-129/V1-60) has been named repeatedly this session as the cheapest remaining conversion -- host access only, no HTTP auth needed. |
| Open PRs | none -- already merged |
| Merged commits/PRs | #911 (edc726ef1) |
| Test evidence | diff-verified against installer convention |
| Production evidence | not yet -- needs the unit confirmed installed and firing on the deployed host |
| Exact missing requirement | Log into the production host, confirm dynasty-faab-history.timer is installed and has fired at least once. NO code change. |
| Active work claim | none found |
| Conflict risk | none |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | host/SSH access only |
| Can run in parallel with | V1-129, V1-60 (same batch, same access requirement) |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-60: FFPC roster lane real or honestly empty

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L2 |
| Canonical owner lane | L4 |
| Actual current-main state | #911 merged 2026-08-19. CollectResult gains status/unavailable_reason, verified in the diff. Same Lane-4 on-box batch as V1-57. |
| Open PRs | none -- already merged |
| Merged commits/PRs | #911 |
| Test evidence | diff-verified |
| Production evidence | FFPC contributes zero rosters today, needs prod-side measurement |
| Exact missing requirement | Prod-side board measurement -- host access only, no code change |
| Active work claim | none found |
| Conflict risk | none |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | host/SSH access only |
| Can run in parallel with | V1-57, V1-129 |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-65: Insider Trading / cross-league ownership

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L2 |
| Canonical owner lane | L4 |
| Actual current-main state | L1 COMPLETE and mutation-proven at Integration 2026-08-20 (own row text). L2 explicitly UNMEASURABLE in dev -- the ledger tables all hold 0 rows in this environment, and the row correctly refuses to treat that as a finding. |
| Open PRs | none -- #911 already merged |
| Merged commits/PRs | #911 |
| Test evidence | tests/intel/test_insider_never_claims_sharp.py, 5 tests, mutation-proven (own row text quotes the mutation) |
| Production evidence | none obtainable here -- needs on-box census of data/intel/ledger.sqlite3 |
| Exact missing requirement | Run the eligibility census ON the deployed ledger and record how many leagues each filter admits -- host access only, no code change |
| Active work claim | none found |
| Conflict risk | none |
| **Estimated closure class** | **B** |
| NUMERATOR_VALUE | 1 |
| Dependencies | host/SSH access to the deployed ledger |
| Can run in parallel with | V1-57, V1-60, V1-129 (same access class) |
| DO_NOT_TOUCH_FILES | none -- pure verification |

#### V1-94: teamAssignment degraded/missing is not served as assignments: []

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L1 |
| Actual current-main state | Row text is extremely detailed: #914 fixes the named defect AND reports a second missing-as-zero bug found alongside. The E2E spec (tests/e2e/specs/public-league.spec.js:533) was ALREADY REWRITTEN this session to pin the correct contract (explicit available/unavailableReason, one slot per manager) instead of the over-asserting original. The underlying favorite-resolution defect stays tracked separately in #815. |
| Open PRs | #914's exact current state not independently re-confirmed this pass |
| Merged commits/PRs | the E2E rewrite is confirmed done (row text describes it in past tense as already landed) |
| Test evidence | tests/e2e/specs/public-league.spec.js:533 rewritten and pinned, per row text |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm #914's merge state for the underlying defect fix itself, separate from the already-landed E2E rewrite |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **B (if #914 landed) or D (if not)** |
| NUMERATOR_VALUE | 1 |
| Dependencies | #914's state |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/public_league/ (public league snapshot builder) |

---

## NEXT 15

Mix of B/C/D closures -- verification-only rows with more moving parts, plus small repairs and bounded implementations with a clear scope.

#### V1-105: Performance baselines captured before feature work

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L6 |
| Actual current-main state | This session tracked #966 (Claude 11, C5-PROJ-A) opening under a similar name (V1-105-perf-baseline-audit branch observed this session) -- possible active work not reflected in row text |
| Open PRs | claude/v1-105-perf-baseline-audit branch observed active this session -- check its PR number |
| Merged commits/PRs | not confirmed |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm the v1-105-perf-baseline-audit branch's actual state and whether it closes this row |
| Active work claim | active branch observed this session -- coordinate before duplicating |
| Conflict risk | high if duplicated |
| **Estimated closure class** | **B (if that branch lands) or D (if not) -- RE-CHECK** |
| NUMERATOR_VALUE | 1 |
| Dependencies | that branch's PR state |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | whatever files that branch touches |

#### V1-121: Release-gate classification: every check has a category

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | This session directly observed #948's CI-reliability work (docs/CI_RELIABILITY_LANE.md, tests like test_no_workflow_exits_green_on_missing_secrets.py) landing via #948/#994/#995 -- strongly overlapping scope with this row's 'a real blocker must not be treated as noise' requirement |
| Open PRs | none currently -- #948 and successors already merged this session |
| Merged commits/PRs | #948 and its follow-on work, tracked by this dispatcher across cycles 32-54 |
| Test evidence | tests/ops/test_sharp_smoke_record.py, tests/deploy/test_no_workflow_exits_green_on_missing_secrets.py -- exist per this session's own tracking, not re-read this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm whether #948's classification work actually satisfies THIS row's specific claim (every check categorized) -- likely close but not 1:1 confirmed |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **B -- RE-CHECK, may already be class A** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | .github/workflows/ |

#### V1-134: A missing or unproven bridge fails closed, and says so

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L8 |
| Actual current-main state | Same Lane 8 program as V1-133 -- PENDING may not vote, untranslatable sources must be reported as such |
| Open PRs | same Lane 8 branches as V1-133 |
| Merged commits/PRs | possibly covered by #954/#993's fail-closed design -- not confirmed |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm against #954/#993's actual fail-closed behavior |
| Active work claim | active Lane 8 work |
| Conflict risk | none -- Lane 8 owns this |
| **Estimated closure class** | **B/D pending confirmation** |
| NUMERATOR_VALUE | 1 |
| Dependencies | Lane 8's sequencing |
| Can run in parallel with | nothing outside Lane 8 |
| DO_NOT_TOUCH_FILES | Lane 8's bridge files |

#### V1-135: Source-native ordinal vs cardinal semantics are preserved

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L8 |
| Actual current-main state | Same Lane 8 program |
| Open PRs | same Lane 8 branches |
| Merged commits/PRs | possibly covered by the same bridge foundation |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm against Lane 8's current bridge implementation |
| Active work claim | active Lane 8 work |
| Conflict risk | none -- Lane 8 owns this |
| **Estimated closure class** | **B/D pending confirmation** |
| NUMERATOR_VALUE | 1 |
| Dependencies | Lane 8's sequencing |
| Can run in parallel with | nothing outside Lane 8 |
| DO_NOT_TOUCH_FILES | Lane 8's bridge files |

#### V1-37: ONE Value Adjustment per runtime, parity proven

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L2 |
| Actual current-main state | 5 implementations exist, one via import-time monkeypatch, per row text. NOTE: this session tracked #962 (Claude 9, 'C3 Trade Substrate -- VA consolidation') as active/merged work in this exact space this session -- the row may be stale relative to that. |
| Open PRs | check #962's current state -- not re-verified this pass, but this session observed it as an active Claude-9 PR earlier in the sprint |
| Merged commits/PRs | possibly #962 -- needs confirmation this cycle |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm whether #962 already closes this row's implementation gap; if so this may already be class A/B |
| Active work claim | none found |
| Conflict risk | high if #962 is still open -- do not fork a second VA implementation |
| **Estimated closure class** | **B (if #962 landed) or D (if not) -- FLAG FOR RE-CHECK, likely closer than the row text suggests** |
| NUMERATOR_VALUE | 1 |
| Dependencies | #962's actual merge state |
| Can run in parallel with | most rows outside src/trade/ktc_va.py |
| DO_NOT_TOUCH_FILES | src/trade/ktc_va.py, frontend/lib/trade-logic.js::ktcAdjustPackage (single owner per CLAUDE.md) |

#### V1-68: E2E suite verdict is read and true

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: 'Red on main 7 consecutive days' at time of writing -- this dispatcher observed E2E stabilization work landing this session (V1-94's row references a rewrite of over-asserting E2E specs) |
| Open PRs | none found |
| Merged commits/PRs | possibly related to the E2E stabilization work tracked this session under other rows |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Confirm current E2E red/green streak on main -- may already be resolved given V1-94's cross-reference |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **B/C -- RE-CHECK, may be closer than text suggests** |
| NUMERATOR_VALUE | 1 |
| Dependencies | current CI state |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | tests/e2e/ |

#### V1-104: Human review / admin controls

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: 'narrow today (sharp-identities only)' -- partial implementation, L1 bar |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Widen coverage beyond sharp-identities, or confirm L1's bar is already met for the named scope |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-112: Streaming SSR does not leave a duplicate DOM copy

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text: page markup renders twice -- #730 referenced |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | the defect itself is the evidence |
| Exact missing requirement | Fix the duplicate-render defect plus a measured statement |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-117: One intake mechanism for owner instructions

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: 65 binding decisions sit in a doc the index calls superseded -- governance/doc consolidation, not code |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Consolidate the 65 decisions into the live index, plus a mechanism preventing future drift. L1 is the lowest bar -- likely closeable with a doc pass + a lint-style check. |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified -- but coordinate on docs/ to avoid edit collisions |

#### V1-131: Nav does not offer a page whose endpoints all 503

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L3 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text is explicit: 'Gating only -- the Consensus Edge FEATURE stays POST-V1'. This narrows scope hugely: only the NAV LINK needs conditional hiding, not the feature itself. |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | the defect (nav offers a 503ing page) is presumably still live |
| Exact missing requirement | Gate the nav item behind an endpoint-health check -- a small, scoped frontend change given the explicit gating-only framing |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | frontend/components/nav (or equivalent) |

#### V1-21: Model provenance stamps

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | Partial per W04-F011; L1 is the lowest bar (deterministic RED->GREEN + green CI) |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | n/a at L1 |
| Exact missing requirement | A deterministic test proving the stamp is present on every priced row, RED without it |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most other rows |
| DO_NOT_TOUCH_FILES | src/canonical/player_valuation.py (per CLAUDE.md, canonical curve owner) |

#### V1-25: League-config consistency

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | Residual drift per W18-F005/F011; L1 bar |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | n/a at L1 |
| Exact missing requirement | A deterministic test closing the residual drift, RED without the fix |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most other rows |
| DO_NOT_TOUCH_FILES | src/api/league_registry.py |

#### V1-41: Use Team Context toggle, ON by default

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L2 |
| Actual current-main state | No implementation found this pass |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | The toggle itself, defaulted ON, plus an L1 test |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-46: Manual override UX: visually silent, one global reset

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L6 |
| Actual current-main state | Binding owner UX requirement, decisions 3-7. No implementation found this pass. |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | UI implementation + L1 test |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-62: Sharp Tracker

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L4 |
| Canonical owner lane | L4 |
| Actual current-main state | Row text: 'live but W15-F017 no memoization' -- a real perf defect, not a verification gap |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | already live |
| Exact missing requirement | Add memoization to close W15-F017 |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/sharp/market.py |

---

## SURPLUS 15 -- extra candidates so 31 can close even if several block

Deliberately oversized past the 31 needed for TOP10+NEXT10+NEXT15=35 (already 4 over 31; this bucket adds 15 more, 50 total considered, so the sprint has real headroom if any close turn out to be blocked, contested, or the RE-CHECK flags resolve unfavorably).

#### V1-69: value_as_of accepts an ISO datetime

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | No implementation found this pass. L1 is the lowest bar -- likely a small, bounded fix. |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | n/a |
| Exact missing requirement | Parse+accept an ISO datetime where the row's target field currently doesn't |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-79: A blocking gate bounds the production payload

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L6 |
| Actual current-main state | No implementation found this pass |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Implement the payload-size gate plus a board measurement |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-80: The critical-source gate can fire for DLF

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L5 |
| Actual current-main state | No implementation found this pass |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Add DLF to the critical-source gate's coverage plus a measured statement |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | scripts/check_source_health.py |

#### V1-90: FootballGuys ghost stamps removed

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L5 |
| Actual current-main state | Stamps with no fetcher since 2026-05-24 per row text -- looks like simple cleanup |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Remove the ghost stamps, add an L1 guard against reintroduction |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | data/scrape_state/ |

#### V1-92: Freshness indicators complete

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L1 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text: 'W08-F011' -- named partial defect, L1 is the lowest bar |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified |
| Production evidence | n/a |
| Exact missing requirement | Close W08-F011 with a deterministic test |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-98: Blended source rank renders or is honestly removed

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text: 'currently blank' -- a simple frontend truthful-degraded-state fix, L1 bar |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Either render the blended rank or explicitly show it's unavailable, plus an L1 test |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | frontend/lib/dynasty-data.js (buildRows materializer) |

#### V1-132: The horizon pick year is not a single-vendor dependency

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L5 |
| Actual current-main state | Measured precisely in the row's own text: 2026/27/28 tier rows blend idpTradeCalc+ktcSfTep; the horizon year blends idpTradeCalc ALONE on all 12 cells, because injection clones from the raw payload while ktcSfTep pick values arrive via later CSV enrichment. F-30 already fixed the GUARANTEE independence; the VALUE still isn't independent. |
| Open PRs | none found |
| Merged commits/PRs | F-30 (partial -- guarantee only) |
| Test evidence | not verified this pass |
| Production evidence | the 12-cell measurement IS the evidence, already done |
| Exact missing requirement | Route ktcSfTep's enrichment into the horizon-year injection path so the VALUE (not just the guarantee) becomes multi-vendor |
| Active work claim | none found |
| Conflict risk | medium -- pick pricing is single-writer territory |
| **Estimated closure class** | **C -- the defect is precisely located, this reads like a scoped fix** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/api/pick_value_resolution.py, src/picks/site_pick_map.py |

#### V1-40: Dropability / cut candidates consolidation

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L2 |
| Actual current-main state | Row text: 'complete but not consolidated' -- functionality exists, ownership is fragmented |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Consolidate existing forced-drop logic onto the single owner named in CLAUDE.md (src/trade/roster_capacity.py) |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/trade/roster_capacity.py |

#### V1-59: Sharp bootstrap stops failing

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L3 |
| Canonical owner lane | L4 |
| Actual current-main state | FFPC timeouts + SQLite locking -- real defects, not verification gaps |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Fix the timeout/locking defects |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | src/sharp/ (per CLAUDE.md single-owner cohort module) |

#### V1-86: The E2E tracker identity works

| Field | Value |
|---|---|
| Status (canonical) | `IMPLEMENTED_UNVERIFIED` |
| Required level | L3 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: '14 duplicate trackers; close step never fired' -- a real defect underneath, not pure verification |
| Open PRs | none found |
| Merged commits/PRs | unclear |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Fix the close-step-never-fires defect, then the L3 checklist |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **C** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | tests/e2e/ tracker infrastructure |

#### V1-102: Temporary-password generator with configurable expiry

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L4 |
| Canonical owner lane | L6 |
| Actual current-main state | No implementation found this pass -- named owner workflow, must work end-to-end |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Full implementation: generator + expiry config + admin UI + end-to-end deployed proof |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **D** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-43: Analyze Trade canonical recommendation (V1)

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L1 |
| Canonical owner lane | L2 |
| Actual current-main state | No implementation found this pass. This dispatcher tracked an assignment (L2-2026-08-19-02) for this row that was never delivered to Lane 2 across the entire session -- Lane 2 sat ACTIONABLE_IDLE for 20+ hours with this exact row as its next unstarted, unblocked task. |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | none |
| Exact missing requirement | Full implementation: canonical recommendation logic with no double-counting of overlapping signals |
| Active work claim | none found -- this is exactly why it never got picked up |
| Conflict risk | low |
| **Estimated closure class** | **D** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none blocking -- unblocked on plain main the entire session |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified -- READY TO ASSIGN, was never delivery-blocked by anything but assignment logistics |

#### V1-96: Historical franchise continuity

| Field | Value |
|---|---|
| Status (canonical) | `NOT STARTED` |
| Required level | L2 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: live defect -- 2024 declares ten teams, carries eight standings rows |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | none |
| Production evidence | the defect itself is the evidence |
| Exact missing requirement | Root-cause and fix the ten-vs-eight team discrepancy, then a board measurement |
| Active work claim | none found |
| Conflict risk | low |
| **Estimated closure class** | **D** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-103: Security repairs

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L2 |
| Canonical owner lane | L5 |
| Actual current-main state | Row text: W22-F002/F003/F005/F007 -- multiple named defects, real work remaining |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Close the four named defects plus a measured statement |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **D** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | none identified |

#### V1-109: Mobile usability for roster-heavy views

| Field | Value |
|---|---|
| Status (canonical) | `IN PROGRESS` |
| Required level | L4 |
| Canonical owner lane | L6 |
| Actual current-main state | Row text: mobile-desktop parity, inv 9.3 / MFB-67 / MFB-93 |
| Open PRs | none found |
| Merged commits/PRs | none found |
| Test evidence | not verified this pass |
| Production evidence | not verified this pass |
| Exact missing requirement | Real mobile UI work plus L4 deployed-consumer proof |
| Active work claim | none found |
| Conflict risk | medium |
| **Estimated closure class** | **D** |
| NUMERATOR_VALUE | 1 |
| Dependencies | none |
| Can run in parallel with | most rows |
| DO_NOT_TOUCH_FILES | frontend/components/ (roster views) |

---

## Remaining 21 rows (F/G closure classes -- not attack-list priority)

These rows are closure class F (needs on-box/deployed/authenticated production access no dispatch-role Claude has) or G (needs an explicit owner/human decision before implementation is legitimate -- e.g. OD-04, OD-05, a design reclassification per contract §8, or a downstream dependency on most of the rest of V1 closing first). Listed for completeness, not omitted, but they are not realistic targets for the 70% push without a prerequisite (host access or an owner decision) landing first.

- **V1-22** (D): Hill curve / percentile-to-value correctness -- The B1 investigation's proposed fix, actually implemented
- **V1-23** (D): IDP valuation correctness -- Repair for W02-F001/F002 plus a board-measured statement
- **V1-35** (D): Metric separation (asset/roster/lineup/depth/power/playoff/championship) -- Full separation implementation across the named metric surfaces
- **V1-52** (D): One weekly power-rankings engine -- Item D: retire the legacy engine. This is real, scoped implementation work (not verification), explicitly gated on solving the weekRankDelta MISSING-IS-NEVER-ZERO problem first.
- **V1-91** (D): Partial runs cannot report as healthy -- Complete the repair plus a board measurement
- **V1-36** (E): ONE shared package generator -- The actual consolidation of 4 package generators into one, plus retirement of the other 3
- **V1-11** (F): Confidence naming migration -- L3 needs the 2 BLOCKED-EXTERNAL items run against an authenticated deployed session -- on-box/auth access only
- **V1-15** (F): Acquisition history / cost basis -- Full §8 checklist run on-box where data/retention and data/intel exist
- **V1-16** (F): Historical roster reconstruction -- Same-shape §8-style checklist run against on-box data stores as V1-15
- **V1-17** (F): Pick lineage / trade trees -- Same-shape on-box checklist as V1-15
- **V1-27** (F): One lineup / slot assignment owner -- L3 needs the 2 auth-gated checklist items plus item 4 completed against a deployed session
- **V1-58** (F): Sharp cohort proven populated in production -- Authenticated production check of the Sharp cohort population
- **V1-123** (G): Browser / workflow matrix -- This is a FINAL-SPRINT closure gate, not independent work -- likely depends on most other rows being done first
- **V1-124** (G): Background jobs and data proven in production -- Same as V1-123 -- late-sprint closure gate
- **V1-125** (G): Duplicate owners retired (every retires line zero) -- All named duplicate-owner retirements across the codebase completed first
- **V1-76** (G): Failure attribution compares one vocabulary -- A NEW design, since the original was refuted -- this needs owner input on direction before implementation
- **V1-85** (G -- needs the §8 reclassification read before any work is planned): pickAnchors reporting consistent with the contract -- Check §8 reclassification -- this row may already be non-blocking or descoped
- **V1-87** (G): Every live feature flag is visible to operators -- Whatever the row's own BLOCKED reason names (not fully quoted in extracted text)
- **V1-89** (G): DraftSharks staleness resolved -- Owner decision OD-04, then whichever path it selects
- **V1-126** (G): Final V1 regression green -- Everything else
- **V1-110** (G (pending OD-05) with a possible reclassify to B if #984 already satisfies it -- RE-CHECK): Design primitives / tokens / shell / focus -- OD-05's resolution, then whichever token direction it selects


---

## Summary counts

| Bucket | Row count | Cumulative |
|---|---|---|
| TOP 10 | 10 | 10 |
| NEXT 10 | 10 | 20 |
| NEXT 15 | 15 | 35 |
| SURPLUS 15 | 15 | 50 |
| Remainder (F/G) | 21 | 71 |

31 closures are needed to hit 96/136. TOP10+NEXT10+NEXT15 alone is 35
candidates against a target of 31 -- already surplus. Adding SURPLUS15 brings the considered pool to
50, so the sprint can absorb blocked/contested/RE-CHECK-failed
rows well past the first 31 without falling short.

**This dispatcher counted no VERIFIED rows, promoted no row, and modified no code in producing this
document. All closure classes are estimates for prioritization only -- actual promotion requires each
row's own required verification level to be satisfied and requires Integration/Claude 5 action, not
this dispatcher's.**
