# V1-27 … V1-35 — evidence matrix

What each Roster row **requires**, what evidence exists at `fd70515`,
and the exact remaining step. Assembled 2026-08-19.

This is a reading of `docs/VERSION_1_COMPLETION_CONTRACT.md`, not an
amendment to it. **Only Claude 5 updates the contract's status column.**

---

## The finding that shapes the whole table

`docs/VERSION_1_COMPLETION_CONTRACT.md` §3.2 column 6 is the **required**
evidence level, not the current one. Read that way:

> **Only V1-27 requires production. Seven of the eight remaining Roster
> rows close at EVIDENCE-L1 or L2 — deterministically, in CI, with no
> deploy involved.**

Treating the whole lane as post-deploy work would have parked seven rows
behind an integration step none of them needs.

---

## Matrix

| row | capability | required | evidence held at `fd70515` | missing | exact next step |
|---|---|---|---|---|---|
| **V1-27** | One lineup / slot assignment owner | **L3** | L1: `tests/lineup/test_single_owner.py`, 10/10 vs Sleeper's own awarded best-ball lineups. L2: C2-U1 §10a items 1/3a/5 on a rebuilt board (12/12 solved from `sleeper_roster_positions`; 4 hybrids started in slots their primary alone forbids). Checks 03/05 of the pack add 36 flex slots and 240 starters | **L3** — items 2/3 remain `BLOCKED-EXTERNAL` on auth | run the pack against the deploy with `ROSTER_VERIFY_COOKIE` set. Note the SHA gap in §4 of the pack doc: the API publishes no commit, so the SHA is operator-asserted |
| **V1-28** | FLEX/SF/IDP-FLEX starters before reserve depth | **L1** | L1 in #914 (reserve demand is the same exact solver re-run over the survivors, so the ordering holds by construction). Pack check 05 measures the observable consequence — starter ∩ reserve = ∅ over **240 starters** — and check 03 proves the flex slots came from real config | none for L1 | **row is evidenced at its required level**; Claude 5 to confirm the status change |
| **V1-29** | One replacement level / PAR owner | **L2** | #914 designates the owner and publishes the boundary table. **No new implementation and no retirement** | the **5 duplicate implementations**. The contract says so itself: "the retirements are still owed, so this is begun, not done" | **this is the next Roster-only unit** — see §Next |
| **V1-30** | Canonical meaningful roster core | **L2** | L2: pack checks 04 (374 members), 05 (240), 06 (12 teams, `ceil(1.5·s) − s` re-derived per position). Built as two exact solves, which is what #899 §3 requires over independent greedy lists | the `M` challenger pass is run (#20) but `M = 1.5` remains **PRIOR** by decision 67 and stays labelled so | **evidenced at L2.** The PRIOR label is a standing disclosure, not missing evidence |
| **V1-31** | Canonical Team Strength | **L2** | L2: pack check 09 — groups and starter+reserve both re-sum to `total` across 12 teams. Owner built in #914 | **4 competing notions to retire** (V1-35 audit F-1/F-3 identifies two of them as live client-side formulas). Separately: **no frontend consumer** | **evidenced at L2.** L4 is blocked on handoff **H-1** (Claude 6). Row note should record the unconsumed-owner fact |
| **V1-32** | Canonical Team Weakness / Need Priority | **L2** | L2: pack checks 02 (216 rungs at `rung × teamCount`) and 10 (215 rung credits, no double-count) | ≥5 need definitions to retire; no frontend consumer | **evidenced at L2.** Same H-1 dependency for L4 |
| **V1-33** | Young Core Index + age-value portfolio | **L1** | L1 + L2: pack check 11 — `coverage.totalPlayers == \|core\|`, `coverage.totalValue == strength.total`, `youngCoreIndexStatus == "PRIOR"` across 12 portfolios. Validated against real league examples in #12 | none for L1 | **evidenced above its required level.** The `PRIOR` label is required by #838 and is asserted, not merely present |
| **V1-34** | Untouchable / excluded-player control | **L1** | none — `NOT STARTED`, and it is lane **L2 (Trade)**, not this lane | everything | **not this lane.** Listed for completeness |
| **V1-35** | Metric separation | **L1** | L1: `tests/roster_intel/test_metric_separation.py`, 10 tests, all mutation-proven — no collapsed team score in the canonical payload; the seven quantities separately named; probability relayed never derived; the ROS-production import guard | the **UI half**. Decision 69 says "in the model **and the UI**", and `/rosters` renders a collapsed score (audit F-1) | **model half evidenced at L1**; UI half is handoff **H-1**. Row should read `IN PROGRESS` with the model half recorded — **not `VERIFIED`** |

---

## Reading this honestly

Three things this table deliberately does **not** claim.

**A green suite is not a verified row.** The V1 contract is explicit that
"code exists", "unit tests pass" and "CI was green" are *not*
verification. What the pack adds is a measured statement with a
denominator — which is what EVIDENCE-L2 asks for — and the status column
is still Claude 5's to move.

**V1-29 and V1-31 have work outstanding that no test closes.** Their
required level is L2 and the L2 evidence exists, but both carry
*retirements* (5 replacement implementations; 4 Team Strength notions).
Evidence at the required level and a finished capability are not the
same statement, and this table separates them rather than letting an L2
pass imply the retirements happened.

**No production evidence is produced by this unit.** Everything above is
EVIDENCE-L1 or L2. The only row that *requires* more is V1-27, and
closing it needs a credentialed run against the deploy — Claude 5's step,
with the command in the pack doc §2.

---

## Next Roster-only unit

**V1-29 — retire the five duplicate replacement-level implementations.**

* required level **L2**, entirely inside `src/roster_intel/` +
  `src/league_intel/replacement.py`;
* needs no other lane and no deploy;
* it is the largest outstanding Roster debt, and the V1 contract names it
  in its own words: #914 "designates the owner and publishes the boundary
  table but adds **no new implementation** — the retirements are still
  owed, so this is begun, not done."

It is deliberately **not** the Team Strength consumer gap. That gap is
real and is the V1-35 audit's headline, but its repair is a frontend
change on `/rosters` — Claude 6's lane. Naming it as this lane's next
unit would be claiming another lane's files.

---

## Addendum, 2026-08-20 (superseding rows V1-29, V1-31, V1-32 above)

This table's body is from an earlier point in the same lane's work and is
now stale on three rows; rather than rewrite history, this addendum
records what changed and where the current record lives.

- **V1-29** is now `VERIFIED` at L2 (#987, merge `faa50ba9a`; L1 half
  confirmed by mutation at Integration — see
  `docs/VERSION_1_COMPLETION_CONTRACT.md`). The "Next Roster-only unit"
  section above is resolved and no longer describes outstanding work.
- **V1-31**: `/phases`' independent top-25-value × raw-age classifier
  (audit finding F-3 / handoff H-2) is retired and redirected onto this
  lane's own `teamStrengthLadder()` materializer (PR #1002). `/rosters`'
  `scoreTeamTiers` composite (F-1 / H-1) remains open and is still
  Claude 6's file.
- **V1-32**: a backend AST single-owner discovery guard for
  `TeamStrength` / `TeamWeakness` now exists
  (`tests/roster_intel/test_strength_weakness_single_owner.py`, PR
  #1004), and a census at the current tree confirms no live frontend
  Weakness duplicate exists to retire.
- **Whether V1-32 needs a frontend consumer to close was investigated
  and answered NO** — it is an **L4** question, V1-32's target is
  **L2**, and L2 is independently re-confirmed today (`V1_ROSTER_
  VERIFICATION_PACK.md` §3.1/§6, via the newly-committed
  `--offline` reproduction command). No frontend code was added for
  either row in this pass; building one would exceed both rows' actual
  acceptance bar and duplicate handoff H-1, already assigned to Claude 6.
