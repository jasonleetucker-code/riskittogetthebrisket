# Version 1 Completion Contract

**Status:** COMPLETE AND PROPOSED — awaiting owner ratification.
**Published:** 2026-08-18 by the Integration Authority lane (Claude 5).
**Companions:** `docs/EXECUTION_PLAN.md` §0 (authorization) · `docs/C_SERIES_SCOPE_MANIFEST.md`
(scope) · `docs/OWNER_FEATURE_INVENTORY.md` (owner product record) ·
`docs/audit/POST_MERGE_C_SERIES_AUDIT_2026-08-18.md` (measured defects).

> **This document owns exactly one question: what must be true for V1 to be complete.**
> It does not authorize work — `docs/EXECUTION_PLAN.md` §0 does. It does not define the product —
> the owner records do. It does not replace the Scope Manifest; it *classifies* it.

---

## 0. How to read this

**The denominator is the V1 REQUIRED list in §3, and nothing else.** Completion is
`VERIFIED items ÷ V1 REQUIRED items`. Items in §4, §5 and §6 are out of the denominator by
classification, not by omission — every one of them is named, with the record it came from.

**Two failure modes this document exists to prevent**, both of which have already happened in
this repository:

1. **Manufacturing 100% by shrinking the denominator.** Moving a hard item to POST-V1 the week
   it turns out to be hard. Every classification below carries a rationale traceable to an owner
   record or to the boundary the owner set on 2026-08-18; a reclassification is an owner
   decision, recorded here with a date, never a silent edit.
2. **Counting a thing as done because code for it exists.** See §2.

**Nothing silently disappears.** Where this document classifies an item in a single line, the
itemised requirement remains in its canonical record and is cited. This is a classification
layer over those records — deliberately not a second copy of them, because a second copy is a
second roadmap and it will drift.

---

## 1. The V1 boundary (owner decision, 2026-08-18)

V1 REQUIRED is the **bounded V1-required subset** assigned across the six lanes — **not** every
capability those lanes are authorized to keep building afterwards. The lane assignments
deliberately include post-V1 continuation work so that no lane goes idle after finishing its V1
responsibilities. **That continuation work is not in the denominator.**

**V1 REQUIRED covers:**

- stability and false-green repairs
- canonical identity, value and history
- exact lineup and FLEX-first assignment
- replacement level, meaningful roster core, Team Strength, Team Weakness, basic Young Core
- canonical trade package / Value Adjustment / capacity / forced drops / team context /
  Analyze Trade **V1**
- trustworthy FAAB and Sharp **core**
- exact scoring **including individual special teams**
- required current-season-model correctness
- auth / admin
- mobile-desktop parity
- high-use Premium UI
- rankings performance / virtualization
- truthful degraded states
- source-health correctness
- CI / E2E
- production verification

**Explicitly NOT V1 REQUIRED**, even though one of the six lanes eventually owns it: the full
projection ensemble · Game Day · podcast / YouTube ingestion · the full analyst-intelligence
ecosystem · Manager Scout · full Ask Brisket / AI Front Office · advanced trade-market systems ·
full Public League Experience v3 · Wrapped / reporting · advanced WAR / VORP · other explicitly
post-V1 continuation work.

**Method.** All 290 owner-approved capabilities and the 288 C-Series units/items that carry them
were reconciled **individually** against that boundary. Where an item did not resolve cleanly it
is flagged **individually in §7** rather than absorbed by broadening the denominator.

---

## 2. Status vocabulary, and what may not be counted

| status | meaning |
|---|---|
| `NOT STARTED` | no implementation |
| `IN PROGRESS` | implementation begun, not merged |
| `IMPLEMENTED_UNVERIFIED` | merged, and its required verification has **not** been satisfied |
| `VERIFIED` | required verification satisfied at the stated level |
| `BLOCKED` | cannot proceed — dependency, external permission, or owner decision |
| `DEFERRED` | out of V1 by classification |
| `RETIRED` | superseded or withdrawn; must stay absent |

**Only `VERIFIED` counts toward V1 completion.**

**None of the following is verification**, and each has previously been mistaken for it here:

- the code exists;
- a PR exists;
- the PR merged;
- unit tests pass;
- CI was green;
- a document says it is done.

**The false-green test every item must answer:**

> Is the intended production consumer actually using the canonical implementation, with truthful
> data semantics?

Precedents this rule was written from, all real: the exact lineup solver existed while the
normal overlay discarded its output; DraftSharks sat 12.6 days stale while health read green; a
status denominator reported 2/2 for a board carried by 21 voters; the scrape-promotion gate
watched the retired `ktc` while the anchor that moves hundreds of offense values was
`ktcSfTep`; features shipped behind flags with no production consumer; `rosValue` looked like a
projection and was mostly rank-derived.

### Verification levels

| level | what satisfies it |
|---|---|
| **L1 — deterministic** | RED→GREEN test at exact head, plus green CI on the merge tree |
| **L2 — board/contract inert or measured** | L1 plus a measured statement of the effect on the live board or contract (0 rows, or the exact rows) |
| **L3 — production** | L1 plus the named checklist executed against the **deployed SHA**, evidence recorded |
| **L4 — production consumer** | L3 plus proof the intended user-facing surface consumes the canonical implementation with truthful semantics |

---

## 3. V1 REQUIRED — the denominator

Lane key: **L1** Roster Intelligence · **L2** Trade Intelligence · **L3** Season / Scoring /
Projections · **L4** Market / FAAB / Analyst · **L5** Integration / QA / CI / Governance ·
**L6** Premium UI / Frontend.

### 3.1 Canonical identity, value and history

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-01 | One player-identity owner | `C1-ID-01` / inv 7.1 | L5 | `VERIFIED` | L3 | canonical identity. Cut over 2026-08-16; prod gate 2,016/2,016 and 24,024/24,024, board 0/1,092 |
| V1-02 | One pick identity, end to end | `C1-ID-02` / inv 2.7 | L5 | `VERIFIED` | L2 | canonical identity. PR #867; board inert 0/1,093 |
| V1-03 | One immutable as-of value/provenance ledger | `C1-HIST-01` | L5 | `VERIFIED` | L3 | canonical history. Prod run 31960075629, 169,896 rows / 34 dates |
| V1-04 | Historical pick values first-class | `C1-HIST-02` | L5 | `VERIFIED` | L1 | canonical history |
| V1-05 | Deterministic board-history `rankChange` | `C1-HIST-03` | L5 | `VERIFIED` | L1 | truthful degraded state — no comparator yields `None`, never 0 |
| V1-06 | Canonical value scale 1–9999 enforced | `F-VAL-01` / inv 7.5 | L5 | `VERIFIED` | L1 | canonical value. B9a |
| V1-07 | No second canonical board | `F-VAL-02` | L5 | `VERIFIED` | L2 | canonical value. B9a; measured 491/507 disagreement removed |
| V1-08 | `valuation_mode` withdrawn, ignored, stamped | `F-VAL-03` | L5 | `VERIFIED` | L1 | canonical value |
| V1-09 | Five-axis confidence, weakest axis wins | `F-CONF-01` / inv 7.4 | L5 | `VERIFIED` | L1 | canonical value. B11 |
| V1-10 | Provider families, one vote each | `F-SRC-01` / inv 7.6 | L5 | `VERIFIED` | L1 | canonical value. 21 keys → 13 families |
| V1-11 | Confidence naming migration | `C1-CONF-01` / `C1-U5` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical value. PR #876 merged; §6 checklist **unexecuted** |
| V1-12 | Pick value completeness through 2029 | `C1-PICK-01` / MFB-89 / inv 2.8 | L5 | `VERIFIED` | L2 | canonical value; owner hard requirement. PR #871 + D1 repair |
| V1-13 | Generic ↔ exact-slot transition, one asset | `C1-PICK-02` | L5 | `VERIFIED` | L1 | canonical identity |
| V1-14 | Per-source pick boards: no fabricated year anchors | `C1-U6-D1` | L5 | `VERIFIED` | L3 | false-green repair. Deployed `5a5f1507f`; 0 of 18 cells violating |
| V1-15 | Acquisition history / cost basis | `C1-ACQ-01` / inv 7.11 | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical history. PR #878; §8 checklist **unexecuted** |
| V1-16 | Historical roster reconstruction | `C1-ACQ-02` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical history |
| V1-17 | Pick lineage / trade trees | `C1-ACQ-03` / CE-18 | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical history |
| V1-18 | Irreversible-evidence retention | `C1-U1` / `C1-RET-01…08` | L5 | `VERIFIED` | L3 | perishable evidence; loss is unrecoverable. `C1-RET-07` honestly STALE |
| V1-19 | Multi-format dynasty source archive | `C1-SRC-01` / `C1-U9` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical value provenance. §7 checklist **unexecuted** |
| V1-20 | Game type proven per feed, fails closed | `C1-SRC-02` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | canonical value — dynasty lane purity |
| V1-21 | Model provenance stamps | inv 7.12 | L5 | `IN PROGRESS` | L1 | canonical value provenance; partial (W04-F011) |
| V1-22 | Hill curve / percentile→value correctness | inv 7.2 | L5 | `IN PROGRESS` | L2 | canonical value. B1 investigated, not implemented |
| V1-23 | IDP valuation correctness | inv 7.3 | L5 | `IN PROGRESS` | L2 | canonical value. W02-F001/F002 |
| V1-24 | Factual scoring identity, fails closed | `F-SCORE-01` / inv 7.7 | L5 | `VERIFIED` | L2 | canonical value; cross-league correctness. B6 |
| V1-25 | League-config consistency | inv 7.8 | L5 | `IN PROGRESS` | L1 | canonical value; residual drift W18-F005/F011 |
| V1-26 | KTC playerID → identity, one owner | `C4-KTC-01` | L4 | `VERIFIED` | L2 | canonical identity. Join 200/200, board inert |

### 3.2 Exact lineup, replacement, roster core, Team Strength / Weakness, Young Core

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-27 | One lineup / slot assignment owner | `C2-LINE-01` / `C2-U1` | L1 | `IMPLEMENTED_UNVERIFIED` | L3 | named V1 scope. PR #880; 10/10 vs Sleeper truth; §10 checklist **unexecuted** |
| V1-28 | FLEX / SF / IDP-FLEX starters assigned before reserve depth | `#899` addendum | L1 | `NOT STARTED` | L1 | binding owner decision 2026-08-18, decision 72 |
| V1-29 | One replacement level / PAR owner | `C2-REPL-01` / `C2-U2` | L1 | `NOT STARTED` | L2 | named V1 scope. 5 implementations to retire |
| V1-30 | Canonical meaningful roster core | `C2-CORE-01` / `C2-U6` / `#839` | L1 | `NOT STARTED` | L2 | named V1 scope. `M=1.5` ships as V1 champion labelled PRIOR, challenger pass required |
| V1-31 | Canonical Team Strength | `C2-STR-01` / `C2-U4` | L1 | `NOT STARTED` | L2 | named V1 scope. 4 competing notions to retire |
| V1-32 | Canonical Team Weakness / Need Priority | `C2-WEAK-01` / `C2-U5` | L1 | `NOT STARTED` | L2 | named V1 scope. ≥5 need definitions to retire |
| V1-33 | Basic Young Core Index | `C2-AGE-02` / inv 1.6 | L1 | `NOT STARTED` | L1 | **basic** Young Core named in V1 scope. Age buckets classified PRIOR |
| V1-34 | Untouchable / excluded-player control | inv 1.5 | L2 | `NOT STARTED` | L1 | owner control over recommendations; W09-F011 |
| V1-35 | Metric separation (asset value / roster strength / lineup / depth / power / playoff / championship) | decision 69 | L1 | `NOT STARTED` | L1 | binding owner decision — may not collapse into one team score |

### 3.3 Canonical trade intelligence (Analyze Trade V1)

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-36 | ONE shared package generator | `C3-PKG-01` / `C3-U1` | L2 | `NOT STARTED` | L2 | named V1 scope. 4 generators to retire |
| V1-37 | ONE Value Adjustment per runtime, parity proven | `C3-VA-01` / `C3-U2` / decision 70 | L2 | `NOT STARTED` | L2 | named V1 scope. 5 implementations, one via import-time monkeypatch |
| V1-38 | KTC VA stays an explicit labelled market lens | `C3-VA-02` | L2 | `VERIFIED` | L1 | truthful semantics; already complete |
| V1-39 | Roster capacity / forced-drop trade analysis | `C3-CAP-01` / `#843` | L2 | `NOT STARTED` | L1 | named V1 scope |
| V1-40 | Dropability / cut candidates consolidation | `C2-DROP-01` / `C2-U8` / inv 1.4 | L2 | `IN PROGRESS` | L2 | named V1 scope (forced drops); complete but not consolidated |
| V1-41 | "Use Team Context" toggle, ON by default | `C3-CTX-01` / `#842` | L2 | `NOT STARTED` | L1 | named V1 scope |
| V1-42 | Exact before→apply→re-solve→after roster simulation | `C2-SIM-01` / `C2-U3` / inv 1.3 | L2 | `NOT STARTED` | L2 | trade simulation, named V1 scope |
| V1-43 | Analyze Trade canonical recommendation (V1) | `C7-DESK-01` / `#792` | L2 | `NOT STARTED` | L1 | named V1 scope, explicitly at V1 depth. No double-counting of overlapping signals |
| V1-44 | Equalizers rank on the post-VA gap | `C3-EQ-01` / `#800` | L2 | `NOT STARTED` | L1 | P1 live trade correctness; `findBalancers` divergent in two runtimes |
| V1-45 | Trade calculator | inv 2.1 | L2 | `IMPLEMENTED_UNVERIFIED` | L4 | high-use surface; owner status "ALREADY COMPLETE — VERIFY ONLY" |
| V1-46 | Manual override UX: visually silent, one global reset | `C3-CALC-02` / `#781` | L6 | `NOT STARTED` | L1 | binding owner UX requirement, decisions 3–7 |
| V1-47 | Multi-team (3+) trade modelling preserved | `BS-3TEAM` | L2 | `VERIFIED` | L1 | owner requirement: "must never be simplified away" |

### 3.4 Exact scoring and required current-season-model correctness

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-48 | Realized scoring correctness | `F-SCORE-02` / inv 7.9 | L3 | `VERIFIED` | L2 | exact scoring. B7 |
| V1-49 | Individual special-teams scoring | `C5-ST-01` / `#802` | L3 | `NOT STARTED` | L2 | **named explicitly** in the V1 boundary |
| V1-50 | ROS projections honest about what they are | `F-ROS-01` | L3 | `VERIFIED` | L1 | truthful semantics — `rosValue` precedent |
| V1-51 | One playoff-probability engine | `C5-PLAY-01` / inv 6.1 | L3 | `NOT STARTED` | L2 | required current-season-model correctness: 2 engines disagree 7 vs 6 spots |
| V1-52 | One weekly power-rankings engine | `C5-POW-01` / inv 6.2 | L3 | `NOT STARTED` | L2 | required current-season-model correctness: 2 competing engines |
| V1-53 | Redraft / ROS seasonal lane stays separate from dynasty valuation | `C5-ROS-01` | L3 | `IN PROGRESS` | L1 | canonical value — source-domain boundary |
| V1-54 | BDVM fundamentals stay a separate concept | `C5-BDVM-01` / inv 8.1 | L3 | `VERIFIED` | L1 | canonical value separation; complete for declared scope |

### 3.5 Trustworthy FAAB and Sharp core

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-55 | One FAAB engine (ceiling vs recommended bid) | `F-FAAB-01` / inv 3.1 | L4 | `VERIFIED` | L2 | FAAB core. 247 tests; backtest 166/166 → 0/166 low-value overbids |
| V1-56 | FAAB league context panel | inv 3.2 | L4 | `IMPLEMENTED_UNVERIFIED` | L4 | FAAB core; owner status "VERIFY ONLY" |
| V1-57 | FAAB bid-history collection is scheduled, not a manual step | `C4-FAAB-02` | L4 | `NOT STARTED` | L3 | FAAB core trustworthiness — no timer today |
| V1-58 | Sharp cohort proven populated in production | `C4-SHARP-01` / `C4-U2` | L4 | `IMPLEMENTED_UNVERIFIED` | L3 | Sharp core. Verification artifacts end at 502/401/"unverifiable_unauthenticated" |
| V1-59 | Sharp bootstrap stops failing | `C4-SHARP-02` | L4 | `IN PROGRESS` | L3 | Sharp core. FFPC timeouts + SQLite locking |
| V1-60 | FFPC roster lane real or honestly empty | `C4-SHARP-03` | L4 | `IN PROGRESS` | L2 | truthful degraded state — must not read as zero rosters silently |
| V1-61 | Sharp Roster Percentage | inv 4.5 | L4 | `IMPLEMENTED_UNVERIFIED` | L4 | Sharp core; owner status "VERIFY ONLY" |
| V1-62 | Sharp Tracker | inv 4.4 | L4 | `IN PROGRESS` | L4 | Sharp core; live but W15-F017 no memoization |
| V1-63 | Manager-level Sharp concentration | inv 4.6 | L4 | `NOT STARTED` | L1 | Sharp core; missing field, W15-F009 P1 |
| V1-64 | Sharp event ledger surfaces adds/drops | inv 4.7 | L4 | `IN PROGRESS` | L1 | Sharp core; W15-F013 |
| V1-65 | Insider Trading / cross-league ownership | `C4-INS-01` / inv 4.8 | L4 | `IN PROGRESS` | L2 | Sharp core; complete, consolidation pending |

### 3.6 Source-health correctness and stability / false-green repairs

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-66 | 2029 pick tier ordering not inverted | audit `F-1` | L5 | `VERIFIED` | L2 | data integrity |
| V1-67 | E2E board diagnostic reports a true root cause | audit `F-2` | L5 | `VERIFIED` | L1 | false-green repair (#893) |
| V1-68 | E2E suite verdict is read and true | audit `F-3` / `F-3a` / `F-3b` | L5 | `IN PROGRESS` | L2 | CI/E2E. Red on `main` 7 consecutive days |
| V1-69 | `value_as_of` accepts an ISO datetime | audit `F-5` | L5 | `NOT STARTED` | L1 | stability |
| V1-70 | A source cannot go unfetched while every surface reads OK | audit `F-6` | L5 | `VERIFIED` | L2 | source-health correctness. 12.6-day precedent |
| V1-71 | Source-health headline counts the real voter population | audit `F-7` / `C4-SRC-02` | L5 | `VERIFIED` | L2 | false-green repair — 2/2 for a 21-voter board |
| V1-72 | Build-check suppressions rest on sources that exist | audit `F-8` | L5 | `VERIFIED` | L1 | evidence integrity |
| V1-73 | Board-diff harness hashes all three inputs | audit `F-9` | L5 | `VERIFIED` | L1 | test integrity |
| V1-74 | The board's retail anchor is watched | audit `F-10` | L5 | `VERIFIED` | L2 | source-health correctness. `ktcSfTep`, not retired `ktc` |
| V1-75 | A source losing all evidence stays visible to the watchdog | audit `F-11` | L5 | `VERIFIED` | L1 | truthful degraded state |
| V1-76 | Failure attribution compares one vocabulary | audit `F-12` / census `S-2` | L5 | `NOT STARTED` | L2 | source-health correctness. **Design refuted — see §8** |
| V1-77 | `/api/dynasty-data` cannot answer 200 off disk when the backend says 401 | audit `F-14` | L5 | `VERIFIED` | L2 | security / data integrity |
| V1-78 | Row-floor guard covers every registered voter | audit `F-15` | L5 | `VERIFIED` | L2 | source-health correctness. 8 of 21 had opted out |
| V1-79 | A blocking gate bounds the production payload | audit `F-16` | L6 | `NOT STARTED` | L2 | performance / test integrity |
| V1-80 | The critical-source gate can fire for DLF | audit `F-17` | L5 | `NOT STARTED` | L2 | source-health correctness |
| V1-81 | Freshness budgets bound what the signal measures | audit `F-18` | L5 | `IMPLEMENTED_UNVERIFIED` | L2 | source-health correctness. #909 |
| V1-82 | Health/status/metrics/alerts report board age, not process age | audit `F-19` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | false-green repair. #909 |
| V1-83 | Alert cooldown keyed on delivery | audit `F-20` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | observability correctness. #909 |
| V1-84 | 503 is not exempt from production health failure | audit `F-21` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | false-green repair. #909 |
| V1-85 | `pickAnchors` reporting consistent with the contract | audit `F-22` | L5 | `NOT STARTED` | L1 | P2 reporting consistency — **reclassified, see §8** |
| V1-86 | The E2E tracker identity works | audit `F-23` | L5 | `IN PROGRESS` | L3 | CI/E2E false-green. 14 duplicate trackers; close step never fired |
| V1-87 | Every live feature flag is visible to operators | audit `F-24` | L5 | `NOT STARTED` | L1 | truthful degraded state — a defaulted-ON flag absent from `/api/status` |
| V1-88 | Flag documentation names the endpoint it actually gates | audit `F-26` | L5 | `NOT STARTED` | L1 | evidence integrity |
| V1-89 | DraftSharks staleness resolved | `C4-SRC-01` | L4 | `BLOCKED` | L3 | source-health correctness. **Owner decision `OD-04`**: re-mint / accept / retire |
| V1-90 | FootballGuys ghost stamps removed | `C4-SRC-03` | L5 | `NOT STARTED` | L1 | source-health correctness — stamps with no fetcher since 2026-05-24 |
| V1-91 | Partial runs cannot report as healthy | `C4-SRC-02` | L5 | `IN PROGRESS` | L2 | false-green repair |
| V1-92 | Freshness indicators complete | inv 6.8 | L6 | `IN PROGRESS` | L1 | truthful degraded state; W08-F011 |

### 3.7 Truthful degraded states

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-93 | Missing is never zero, on display | `F-MISS-01` | L5 | `VERIFIED` | L1 | governing invariant (#836) |
| V1-94 | `teamAssignment` degraded/missing is not served as `assignments: []` | `R-TEAMASSIGN` / `#815` | L1 | `NOT STARTED` | L2 | named correctness defect; HTTP 200 on a degraded snapshot |
| V1-95 | Awards do not exist before games are played | `C9-AWARD-01` | L3 | `NOT STARTED` | L2 | live production defect: eight awards manufactured with zero games |
| V1-96 | Historical franchise continuity | `C9-HIST-01` | L5 | `NOT STARTED` | L2 | live defect: 2024 declares ten teams, carries eight standings rows |
| V1-97 | Historical Trade Replay does not leak hindsight | `C3-REPLAY-01` | L2 | `NOT STARTED` | L2 | **wrong semantics in production** |
| V1-98 | Blended source rank renders or is honestly removed | inv 6.7 | L6 | `NOT STARTED` | L1 | truthful degraded state — currently blank |
| V1-99 | Public/private boundary holds on both channels | `F-PRIV-01` / `PL-BOUNDARY` | L5 | `VERIFIED` | L2 | governing product split. B8 |
| V1-100 | Unauthenticated draft-capital redaction | inv 9.7 | L5 | `VERIFIED` | L2 | owner decision 2026-08-11 |

### 3.8 Auth / admin

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-101 | `/admin` `fmtPassExpiry` crash repaired | `#779` | L6 | `NOT STARTED` | L4 | named V1 scope; live user-facing crash |
| V1-102 | Temporary-password generator with configurable expiry | `#780` | L6 | `NOT STARTED` | L4 | named V1 scope; owner workflow must work end-to-end |
| V1-103 | Security repairs | inv 9.6 | L5 | `IN PROGRESS` | L2 | named V1 scope. W22-F002/F003/F005/F007 |
| V1-104 | Human review / admin controls | inv 6.9 / `#779`-adjacent | L5 | `IN PROGRESS` | L1 | named V1 scope; narrow today (sharp-identities only) |

### 3.9 Performance, mobile parity, high-use Premium UI

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-105 | Performance baselines captured before feature work | `C0-PERF-01` / `C0-U2` | L6 | `NOT STARTED` | L2 | a baseline captured after the work cannot show what the work cost |
| V1-106 | Rankings board windowing / virtualization | `C8-PERF-03` / inv 9.1 | L6 | `IN PROGRESS` | L2 | **named explicitly** in the V1 boundary. PR #760 |
| V1-107 | Mobile payload smaller than desktop | `C8-PERF-01` / audit `F-13` | L6 | `NOT STARTED` | L2 | mobile-desktop parity. Mobile is +13% LARGER |
| V1-108 | Non-data routes stop fetching the contract | `C8-PERF-02` | L6 | `IN PROGRESS` | L2 | rankings/app performance. PR #759 |
| V1-109 | Mobile usability for roster-heavy views | inv 9.3 / MFB-67 / MFB-93 | L6 | `IN PROGRESS` | L4 | mobile-desktop parity |
| V1-110 | Design primitives / tokens / shell / focus | `C8-PSI-01` | L6 | `IN PROGRESS` | L2 | high-use Premium UI. **Owner decision `OD-05`** on token direction |
| V1-111 | Premium migration of the high-use routes (Rankings first) | `C8-PSI-02` / `R-PREMIUM` | L6 | `NOT STARTED` | L4 | **high-use** Premium UI only — route-by-route migration is post-V1 |
| V1-112 | Streaming SSR does not leave a duplicate DOM copy | `#730` | L6 | `NOT STARTED` | L2 | stability; page markup renders twice |
| V1-113 | Accessibility instrumentation in CI | `C8-A11Y-01` | L6 | `NOT STARTED` | L1 | accessibility not measured in CI regresses silently |

### 3.10 CI / E2E, governance and production verification

| # | capability | canonical id | lane | status | level | in V1 because |
|---|---|---|---|---|---|---|
| V1-114 | One authorization record matching merged reality | `C0-GOV-01` | L5 | `IN PROGRESS` | L1 | governance; this contract + EXECUTION_PLAN §0 |
| V1-115 | One CE identifier namespace | `C0-GOV-02` | L5 | `IN PROGRESS` | L1 | governance |
| V1-116 | Zero-loss scope census | `C0-GOV-03` / `C0-GOV-04` | L5 | `IN PROGRESS` | L1 | governance; this document is part of the deliverable |
| V1-117 | One intake mechanism for owner instructions | `C0-GOV-05` | L5 | `NOT STARTED` | L1 | governance; 65 binding decisions sit in a doc the index calls superseded |
| V1-118 | Governance index names every planning doc | `C0-GOV-06` | L5 | `IN PROGRESS` | L1 | governance |
| V1-119 | Planning-integrity validation in CI | `C0-GOV-07` | L5 | `IMPLEMENTED_UNVERIFIED` | L1 | CI |
| V1-120 | Governance / directive reconciliation | `C0-R` | L5 | `IMPLEMENTED_UNVERIFIED` | L3 | production verification. §7.2 checklist **unexecuted** |
| V1-121 | Release-gate classification: every check has a category | release discipline | L5 | `NOT STARTED` | L1 | CI. A real blocker must not be treated as noise, nor a detector block releases |
| V1-122 | Structural / source-health CI lanes stay separated | `docs/ops/STABILIZATION_2026-08-16.md` | L5 | `VERIFIED` | L1 | CI correctness |
| V1-123 | Browser / workflow matrix | `C10-CLOSE-03` | L5 | `NOT STARTED` | L4 | production verification |
| V1-124 | Background jobs and data proven in production | `C10-CLOSE-04` | L5 | `NOT STARTED` | L3 | production verification |
| V1-125 | Duplicate owners retired (every `retires` line zero) | `C10-CLOSE-02` | L5 | `NOT STARTED` | L2 | ONE CONCEPT, ONE CANONICAL OWNER |
| V1-126 | Final V1 regression green | `C10-CLOSE-07` | L5 | `NOT STARTED` | L1 | production verification |

**Denominator: 126 items.**

### 3.11 Standing tally

Measured 2026-08-18 at `main` + PR #909.

| status | count |
|---|---|
| `VERIFIED` | 36 |
| `IMPLEMENTED_UNVERIFIED` | 17 |
| `IN PROGRESS` | 25 |
| `NOT STARTED` | 47 |
| `BLOCKED` | 1 |
| **denominator** | **126** |

**V1 completion: 36 / 126 = 28.6%.**

Read that number carefully. The 17 `IMPLEMENTED_UNVERIFIED` items are *merged and deployed
code* — they are not missing, they are unproven, and five of them
(`V1-11`, `V1-15/16/17`, `V1-19/20`, `V1-27`, `V1-120`) are blocked behind exactly five
production checklists that have never been executed. Executing those five checklists is the
single largest available movement in this number, and it requires an authenticated production
session (§9).

---

## 4. POST-V1 DEFERRED

Approved product, deliberately out of the V1 denominator. **Every one of these is real, owner-
approved scope** and remains itemised in its canonical record; deferral is a scheduling
statement, never a withdrawal.

### 4.1 Named by the owner as out (2026-08-18)

| group | items | canonical record |
|---|---|---|
| Full projection ensemble | `C5-U1` and all six sub-units `C5-PROJ-A…F`; `#854` | Execution Map §7 |
| Game Day | `C5-GD-01` / `CE-20` / `#789`; `C5-GD-02` prediction archive | Manifest §4 C5 |
| Podcast / YouTube ingestion | inv 5.1–5.7; `C6-POD-01`; `C6-YT-01`; `#782` | Inventory §5 |
| Full analyst-intelligence ecosystem | `C6-ANA-01`; `C6-X-01`; `C6-FRESH-01`; `#788`; `#783`; freshness/decay decisions 33–40 | Manifest §4 C6 |
| Manager Scout | `C6-MGR-01` / `CE-03` | Manifest §4 C6 |
| Full Ask Brisket / AI Front Office | `C7-AI-01…05` | Manifest §4 C7 |
| Advanced trade-market systems | `C4-MTL-01/02/03` / `CE-01`; `CE-14` Market Pulse; `C4-FAAB-01` / `CE-19` / `#830`; `C4-WAIV-01`; MFB-77/78/79/80 | Manifest §4 C4 |
| Full Public League Experience v3 | `C9-V3-01`; `PL-IA6`; `PL-FRANCHISE`; `PL-RIVALRY`; `PL-RECEIPTS`; `PL-YEARBOOK`; `PL-HOF`; `PL-RINGHONOR`; `PL-CHAMPPATH`; `PL-ONTHISDAY`; `PL-WEEKHIST`; `PL-MILESTONE`; `PL-RECORDCHASE`; `PL-REUNION`; `PL-LEAGUECAST`; `PL-GOTW`; `PL-WPTIMELINE`; `PL-BADBEAT`; `PL-REDZONE`; `PL-PICKEM`; `PL-DRAFTCAST` | Backlog Spec §9 |
| Wrapped / reporting | `C9-RECAP-01` / `CE-21`; `C9-UR-01/02` Upside Report; `C9-WRS-01` / `#829`; `C9-SHARE-01` / `CE-10`; `weekly-narratives` | Manifest §4 C9 |
| Advanced WAR / VORP | `C5-WAR-01` / `CE-09`; `AW-VORP`; `AW-*` award family (`AW-FLAGSHIP`, `AW-POST`, `AW-TEAM`, `AW-MOTY`, `AW-GMOTY`, `AW-ALLBRISKET`, `AW-RACES`, `AW-TROPHY`, `AW-SECONDARY`, `AW-LEDGER`, `AW-COVERAGE`); `C9-AWARD-02` Brisket Honors v2 | Backlog Spec §10 |

> **Note on awards.** The award *family* is post-V1. `V1-95` — awards must not exist before games
> are played — is **in** V1, because it is a live truthful-degraded-state defect on a shipped
> surface, not new capability.

### 4.2 Lane continuation work (owned by a V1 lane, not V1-required)

| lane | deferred continuation |
|---|---|
| L1 | `C2-AGE-01` age-value portfolio · `C2-AGE-03` age/value trends · `C7-AGE-01` roster window surfaces · `C1-U7` / `C1-PICK-03` / `CE-02` owned-pick distributions (deps on Team Strength) |
| L2 | `C7-BEST-TRADE` / `#841` / `CE-05` Trade Desk · `C7-GOLD-01` Golden Upgrades · `C7-PKGB-01` Package Builder · `C7-POST-01` / `#840` Competitive Posture · `C7-PICKGEN-01` · `C3-CON-01/02/03` recommendation constraints · `C2-EXP-01` / `#786` NFL-team exposure · `C3-MC-01` / `#790` Monte Carlo revalidation · `C3-CALC-03` / `#791` Second Opinions tally · `C3-AGE-01` / `C3-U9` trade aging · `C3-TOPO-01` · `C3-XMKT-01` · `C7-WAIV-01` Perfect Waivers · `MFB-101` historical trade replay (beyond the `V1-97` semantics fix) |
| L3 | `C5-FIT-01` / `#803` player fit + college translation · `C5-U1` ensemble · projection-driven season models beyond `V1-51/52` |
| L4 | `C6-SIG-01/02` central Buy/Sell reconciler and ticker (`#784`, inv 4.2/4.3) · `C6-EDGE-01` Consensus Edge repair · `C7-ALERT-01` Edge Alerts · `#801` Establish The Run (owner-PAUSED) · `#830` FAAB Market Heat |
| L6 | `C8-PSI-03` route-by-route migration · `CE-25` compare multi-select · `CE-14A` personal rankings overlay · `CE-29` push (exists) · `MFB-94…98` informational/monetization surfaces |
| L5 | `C10-ML-01` adaptive source weighting (stays off by design) · `C10-U3` full prior census · `DEF-INTEL-REKEY` · `DEF-FE-PICKGRAMMAR` · `DEF-PUBLIC-PICKFOLD` · `DEF-KTC-STRAT2` · `DEF-TRADE-RETRO` · `DEF-RECONSTRUCTED` · `B4-SAFEGUARD` · `B9B-CONSTANTS` · `CANONICAL_V2` activation |

### 4.3 Remaining approved surfaces and ledger rows

`CE-04` Command Center · `CE-06` Portfolio · `CE-07` Market ADP · `CE-08` Projections & Stats Hub ·
`CE-11` Sleeper Action Gateway (`OD-02`) · `CE-12` Lineup Intelligence surface · `CE-13` Draft Room ·
`CE-15` Portfolio Trade Campaign · `CE-16` Trade Polls (optional) · `CE-17` Format/Utilization Lab ·
`CE-18` Trade Trees *surface* (the `C1-ACQ-03` engine is `V1-17`) · `CE-22`…`CE-27` ·
`C7-CE-01` aggregate · `C7-CMD-01` · `C9-TRUTH-01` · `C9-HIST-02` `PUBLIC_MAX_SEASONS` ·
`R-PICKENGINE` · `R-UPSIDE` · `R-POWERV3` (the consolidation itself is `V1-52`) · `R-STANCE` ·
`R-COMPARE` · `R-SYNC` · `R-NAV` · `R-MLGOV` · `MATH-CALIB` · `BS-COSTBASIS` · `BS-HANDCUFF` ·
`R-PICKQTY` · `PL-PRIVATIZE` · `PL-HISTGATE` · inv 2.5/2.6/2.9/2.10/2.11/2.12/2.14 ·
inv 3.3 Perfect Waivers · inv 3.4 · inv 6.3 franchise history · inv 6.6 Universal Player Profile ·
inv 8.3/8.4/8.5 news & signal hygiene · inv 10.2 adaptive weighting ·
MFB rows not otherwise cited (coverage rows for capabilities already classified above).

> **MFB coverage rows.** `MFB-1`…`MFB-104` are a ledger of approved scope in which most rows are
> coverage restatements of capabilities classified elsewhere in this document (e.g. `MFB-31`
> "league-wide roster strength rankings" is `V1-31`; `MFB-89` is `V1-12`). They are classified by
> the capability they restate, and are not separately counted — counting a capability twice
> would inflate the denominator as surely as dropping one deflates it.

---

## 5. RETIRED / SUPERSEDED

Must stay absent; `C10-U1` re-audits for reappearance.

| id | disposition |
|---|---|
| `X-01` / inv 0.1 | Schedule generator — **OWNER-REJECTED** |
| `X-02` / inv 6.5 | Money / dues / Constitution / League Media — **OWNER-REJECTED**, restated 2026-08-17 |
| `X-04` | Canonical Data Mode offline build — **SUPERSEDED**; the live contract is the source of truth |
| `X-05` | League-aware valuation overlay as canonical — **OWNER-REJECTED** on seven measured defects |
| `X-06` | `opportunity_stats.py` usage-signal engine — **SUPERSEDED** by `consensus_edge/opportunity.py` |
| `X-07` | General "link any Sleeper account" onboarding — **OWNER-REJECTED**, restated 2026-08-17 |
| `X-IDPGURU` | IDP Guru — out of scope by owner direction 2026-08-15. Not to be confused with The IDP Show / FantasyPros IDP / DraftSharks IDP, all still in scope |
| `ktc_crowd_faab.py` adapter | **RETIRED** 2026-08-18 — read a contract block present in 0 of 173 archives |
| market corridor clamp | **RETIRED** — anchor was a voter in the blend it corrected |
| `MFB-102` topology rules | players-only and exact-equal-player-count **WITHDRAWN**, superseded by `#841`/`#842` |
| `C2-GP-01` `/api/gameplan` | **DISCONNECTED** — measured zero frontend consumers. Outcome is binary: reachable or retired. Carried as an L2/L5 disposition, not V1 capability |

---

## 6. EXTERNALLY BLOCKED

Out of the denominator because no amount of engineering clears them.

| id | blocker |
|---|---|
| `F-EXT-01` | KTC data-use permission — owner-reported, **grant artifact not in the repository** (`OD-01`) |
| `F-EXT-02` | IDPTC authorization — **no record of any kind** (`OD-01`) |
| `F-EXT-03` | Credentialed / paywall-adjacent posture — 7 source keys behind credentials, zero recorded authorization (`OD-01`) |
| `F-U2` / `C4-U3` | Market Trade Ledger — blocked on the permission record above |
| `C6-U2` | Analyst ledger — credentials absent (`OD-03`) |
| `X-03` / `#801` | Establish The Run — **OWNER-PAUSED**; do not purchase or implement |
| `C7-GATE-01` / `CE-11` | Sleeper Action Gateway — gated on `OD-02` |
| `CE-28` | User feedback / polling — **not owner-approved**; needs `OD-06` |

---

## 7. Ambiguous items — flagged individually for owner decision

The owner's instruction was to flag the specific item rather than broaden the denominator. Each
of these is currently classified as shown; **the classification is a proposal, not a ruling.**

| # | item | classified | why it did not resolve cleanly |
|---|---|---|---|
| A-1 | `C2-AGE-01` roster age-value portfolio | POST-V1 | The boundary names "**basic** Young Core". `#838` treats the portfolio and the index as one approved feature, and the index is arguably not computable without the age-bucket work the portfolio carries. If they are one deliverable, `V1-33` should absorb `C2-AGE-01` |
| A-2 | `C3-CON-01` recommendation-constraint owner | POST-V1 | The boundary names capacity, forced drops and team context but not constraints — yet `V1-34` (untouchable control) and the owner's `#781`/2.10/2.11 decisions are constraint features, and `C3-CON-01` is their single owner. If `V1-34` is in, its owner arguably must be too |
| A-3 | `C5-U1` projection ensemble vs "required current-season-model correctness" | ensemble POST-V1; `V1-51`/`V1-52` in V1 | The boundary excludes the full ensemble but requires current-season-model correctness. I read that as: consolidate the two playoff engines and the two power-rankings engines onto what exists, without building the ensemble. If correctness is judged to *require* better projections, `V1-51`/`V1-52` become unreachable inside V1 |
| A-4 | `C5-PROJ-E` immutable projection archive | POST-V1 | It is **perishable**: an observation not made now cannot be made later, the same loss class as the `C1-RET-*` tranche which *is* V1. Deferring it is correct on scope and lossy on evidence. Recommend authorizing the archive alone, ahead of the ensemble |
| A-5 | `C7-DRAFT-02` pre-auction immutable snapshot | POST-V1 | Also perishable and **one-shot**: `--record-snapshot` must run before the 2026 rookie auction or Perfect Draft can never be backtested. Not a V1 capability, but it has a deadline V1 does not |
| A-6 | `C9-UR-02` Upside Report Preseason / Kickoff Edition | POST-V1 | Carries a hard publication date (Tuesday before Week 1). Deferred on scope; the date is not deferred |
| A-7 | `C6-EDGE-01` Consensus Edge | POST-V1 | The feature is post-V1, but `F-25` — nav offers a page whose three endpoints 503 — is a live truthful-degraded-state defect on a shipped surface. Recommend the **nav gating** enter V1 while the feature stays out |
| A-8 | inv 6.6 Universal Player Profile | POST-V1 | Named the second Premium migration reference route. If "high-use Premium UI" includes it, it moves into `V1-111` |
| A-9 | `C4-INS-01` Insider Trading | V1 (`V1-65`) | Included as Sharp core because it is live and cross-league ownership is the Sharp product. If "Sharp core" means only the cohort and roster-percentage boards, this is post-V1 |
| A-10 | `C3-REPLAY-01` historical trade replay | V1 (`V1-97`) | The **semantics fix** is in V1 as a live wrong-semantics defect; the full `MFB-101` three-lens replay feature is post-V1. The line between "stop lying" and "build the feature" is thin here |
| A-11 | `C9-HIST-01` franchise continuity | V1 (`V1-96`) | Included as a truthful-degraded-state defect. It sits inside Public League v3, which is explicitly post-V1 — but the defect is live today |
| A-12 | `C1-U7` owned-pick distributions | POST-V1 | Depends on Team Strength (`V1-31`), which is V1. Once `V1-31` lands, `C1-U7` becomes dependency-ready inside the V1 window; deferring it is a scope call, not a dependency one |

---

## 8. Preserved refutations

**Audit systems must themselves be auditable.** A conclusion that was wrong is corrected here in
place, with the original preserved. Erasing it would remove the evidence that the process works.

### 8.1 S-2 — the proposed design is REFUTED. Do not implement it more carefully.

**Original finding (stands):** failure attribution in the health UI compares two disjoint
vocabularies — scraper run names against registry keys — so a disposition does not round-trip and
a run-level "complete" does not decompose into which boards arrived (audit `F-12`, census `S-2`).
The underlying problem is real and remains open as `V1-76`.

**The proposed fix — emitting `playerCount: null` to distinguish "reported zero" from "did not
report" — is refuted at high confidence, and this session verified both halves directly at HEAD
rather than relaying them:**

1. `server.py:2855` computes
   `site_count = len([s for s in result.get("sites", []) if s.get("playerCount", 0) > 0])`.
   A **present** key defeats `dict.get`'s default, so `None > 0` is evaluated and raises
   `TypeError` — confirmed by execution, not by reading.
2. That line sits above the promotion decision, inside a handler whose enclosing
   `except Exception as e:` calls `_mark_scrape_failure(e, elapsed)`. The proposal would therefore
   mark whole scrapes **FAILED** and break the two-hourly refresh.

**A correction to the refutation's own wording.** It has been stated as "`failedSources` is empty
in 176/176 inspected archives". Measured here across all 176 committed export archives: the key is
**absent from every one**, not present-and-empty. That is a stronger statement and a different
one — the field has never been populated, so a detector keyed on it would observe nothing. The
degradation historically capable of taking the board down was timeout-related, which the proposal
would not have observed either.

**Required posture:** `V1-76` stays open. Any replacement must be designed from actual failure
data and adversarially tested before implementation. Any audit status still presenting S-2 as a
ready fix is stale and must be corrected.

### 8.2 F-22 — reclassified P0 → P2, on measurement

**Original framing:** discarded `ktcSfTep` pick anchors were called a *live value defect*.

**Refuted by measurement:** the canonical contract reads the CSV independently and obtains all 36
vendor pick rows. There is therefore **no demonstrated canonical pick-value error**.

**Correct classification:** a **P2 reporting inconsistency** (`V1-85`), not a P0 value-corruption
incident. Both the original finding and this refutation are retained.

---

## 9. What production verification remains

Five merged units are `IMPLEMENTED_UNVERIFIED` because their checklists have never been executed.
**Owner decision, 2026-08-18: these block V1 completion. They are not carved out as externally
blocked**, and `CLOSED-PENDING-PROD` is not closure (`docs/EXECUTION_PLAN.md` §0.2).

| unit | checklist | contract items |
|---|---|---|
| `C0-R` | `C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §7.2 (7 checks) | `V1-120` |
| `C1-U5` | `C1_U5_CONFIDENCE_NAMING.md` §6 | `V1-11` |
| `C1-U8` | `C1_U8_ACQUISITION_LEDGER.md` §8 | `V1-15`, `V1-16`, `V1-17` |
| `C1-U9` | `C1_U9_*` §7 | `V1-19`, `V1-20` |
| `C2-U1` | `C2_U1_CANONICAL_LINEUP.md` §10 | `V1-27` |

Each requires an authenticated production session. The Integration Authority executes every check
reachable without owner-held credentials and records the remainder as `BLOCKED-EXTERNAL` — never
as a pass. **An unreachable check is not a green one.**

---

## 10. Changing this document

- **Status changes** (e.g. `IMPLEMENTED_UNVERIFIED` → `VERIFIED`) are recorded by the Integration
  Authority with the evidence that satisfied the stated level. No other lane edits §3.
- **Denominator changes** — adding or removing a V1 REQUIRED item — are **owner decisions**,
  recorded here with a date and a reason. A genuine omission from already-approved V1 scope is a
  legitimate addition; a new idea is not, and goes to the long-term roadmap.
- **Reclassification out of V1 REQUIRED because an item proved hard is not permitted.** That is
  the failure mode in §0, and it is the one this document exists to make visible.

