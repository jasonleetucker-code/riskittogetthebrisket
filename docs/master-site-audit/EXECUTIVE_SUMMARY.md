# Master Site Audit — Executive Summary

**Audited commit** `e96c06ef` · **dates** 2026-08-04/05 · **method** 31 workstreams against a
running stack, 45 findings put through adversarial refutation.

---

## The one-paragraph answer

The engine is better than its reputation and the screen is worse than the engine. The blend
spine is deterministic, monotonic and largely correct; the test suite runs green at 6,278 Python
and 1,754 frontend tests; the production build passes its own bundle budgets. But **the board
`/rankings` renders is not the board `GET /api/data` serves**, because every page load silently
posts a TE-premium override that bypasses the backend's own measured curve — and that single
two-line defect accounts for three of the nine surviving P0 findings. A second one-line defect
makes every rest-of-season number a replay of a season that ended twenty months ago, and tells
the strongest roster in the league to sell. Both fixes are small: two diffs, sizes S and XS,
close six of the nine P0s. Most of what looks like a broken platform is a handful of bugs sitting
exactly where the user reads the output.

## Can the site be trusted for real decisions today?

**Not for the decisions it exists to support, until a small number of fixes land.**

| Decision | Verdict today |
|---|---|
| "What is this player worth?" (`/rankings`) | **No** — the rendered board disagrees with the served board on 627 of 740 ranks |
| "Should I make this trade?" (`/trade`) | **No** — every TE in every package is priced up to 21.2% below the canonical value |
| "How much should I bid?" (`/waivers`) | **No** — the RB anchor is inflated ~5x by unnormalized cross-season budgets |
| "Am I buying or selling?" (`/league → Trade Deadline`) | **No** — four of twelve managers get inverted advice |
| "What is the market doing?" (Sharp, Insider, Consensus Edge) | Partially — honest where data is absent; untestable here |
| Public league history | With labels — several all-time claims exceed the data |

## By the numbers

| | |
|---|---|
| Findings published | **431** (+1 refuted and withdrawn) |
| Surviving P0 / P1 / P2 / P3 | **9 / 86 / 180 / 156** |
| Findings verified as genuinely correct | **58** (`Implemented and verified`) |
| Genuinely absent features | **11** (`Missing`) |
| Brief sections covered | **44 of 44** — none empty |
| Schema violations at merge | **0** — every finding carries a re-runnable reproduction |
| Prior-audit findings: confirmed / refuted / not reproducible | **140 / 13 / 9** |
| Findings that are new | **174** |

## The nine surviving P0s — which are really five causes

**Cause 1 — the TE-premium override (three P0s, one fix, size S).**
`useSettings.js:35` defaults `tepMultiplier` to `1.15`, a concrete number.
`dynasty-data.js:919-923` treats *any* finite number as a deliberate operator override. So every
page load, for every user, posts `tep_multiplier=1.15`, flipping the request onto the override
path and bypassing the backend's measured ADR-015 TE-basis curve (1.209 at the top of the board
rising toward 2.05 down it). Measured: 627 of 740 ranks and 654 tiers differ from the served
contract, tight ends under-priced by up to 21.2%, and the response stamps `isCustomized: false`
while it happens. A migration at `useSettings.js:182-190` rewrites a genuine `null` ("auto") to
`1.15`, so users who *were* on the correct path were migrated off it permanently.
→ W03-F001, W07-F001, W08-F001.

**Cause 2 — the market gap is computed in rank space (one P0, size M).**
The `/rankings` Edge column labels **32 of 35 top-250 tight ends SELL, and every single SELL in
the top 250 is a tight end.** I initially assumed this was downstream of Cause 1 and said so; it
is not, and the correction is worth stating because it changes what fixing Cause 1 buys you. The
verifier re-ran the real materializer against a clean `GET /api/data` — no override in play — and
got the same distribution: TE {SELL 65, BUY 4, HOLD 4}. The reason is structural:
`marketGapDirection` is computed from **ordinal ranks** (`data_contract.py:3039-3056`) while the
ADR-015 basis conversion operates on **values** inside the blend (`:7674-7695`), so the gap never
sees it. `ktcSfTep` is the only source flagged retail and it is a TE++ board; the consensus it is
differenced against is dominated by base-TE boards. The column is measuring a positional level
offset between boards and calling it mispricing.
→ W12-F002, with W27-F005 as the same defect measured from the other side.

**Cause 3 — the ROS season sort key (three P0s, one fix, size XS).**
`sorted(snapshot.seasons, key=luck._season_sort_key)` passes objects to a function typed for
strings, so every season sorts equal and the simulator runs on the **oldest** loaded season,
2024. Every number on `/league → Championship` and `/league → Trade Deadline` describes a season
that ended ~20 months ago. Absence from that stale sim is then coerced to 0.0 playoff odds, so
Brent — 100th-percentile ROS strength, the best roster in the league — is told *"Seller: sell
aging win-now players, prioritize picks."*
→ W17-F001, W17-F002, W20-F002.

**Cause 4 — FAAB cross-season budget blending (one P0, size M).**
Position calibration blends raw dollar bids from three seasons whose budgets were **$1000, $200
and $100**, with no normalization. The RB anchor reads 43.0 against a budget-normalized 8.58 —
inflated ~5x — and is blended 50/50 into every recommendation for any position with 3+ historical
bids, which is all eight. Replacement-level running backs draw $22–$32 bids on a $100 budget.
This is the specific cause of the over-aggression you reported.
→ W11-F001.

**Cause 5 — the draft slot cap (one P0, size S).**
`mergeDraftCapitalTeams` hard-caps every team's slot count at 6. A team owning 31 of the 72 live
picks renders as "0/6 slots" with a 5.2x-wrong $/slot, and after six picks the app declares the
draft over for them. Your stated requirement — the rookie-auction optimizer has **no fixed slot
count, no minimum, no maximum** — is violated in the most literal way available.
→ W10-F002.

## What is genuinely strong

Worth stating, because a list of only defects is not an audit:

- **The blend spine.** Deterministic across rebuilds, monotonic, with the single-source haircut,
  count-aware aggregation and market-corridor clamp all doing what they claim.
- **Consensus Edge** is the best-evidenced subsystem here: no P0s, no P1s, four findings verified
  correct — and its own decision record honestly concluded the composite had not earned its place
  and switched the flag back off.
- **BDVM's structural isolation** from market inputs is real, and it returns "unpriced with a
  reason" rather than fabricating a normal-looking value.
- **Honest degradation** where data is absent: `/api/intel/*` returns a clean `data_not_ready`
  503 naming the league rather than rendering an empty state that reads as "no activity."
- **Auth** holds: the API 401s correctly across the board, admin routes 403 for a non-allowlisted
  session.
- **The test and build gates work** — and the audit ran them rather than taking their word for it.

One security item does not fit that list and should not wait for a roadmap: `_sanitize_next_path`
(`server.py:738-748`) does not reject a backslash, so `https://chaseupside.com/login?next=/\attacker.tld`
is a **working post-authentication open redirect on the real domain** — driven end to end in
Chromium. It shows the genuine login page, takes the real password, then hands the browser to the
attacker. Rated P1 on blast radius, but it is size XS and there is no reason to schedule it
behind anything (W22-F001).

## What is absent, not broken

Eleven things do not exist. Four matter:

- **The schedule generator does not exist** — no route, no module, no script, no solver anywhere
  in the repository. The 14-game / 3-division / no-back-to-back / Jason-vs-Michaela-week-4 spec
  has no implementation to audit.
- **There is no central Buy/Sell Tracker.** There are 16 label emitters, 14 reachable, with 5
  competing threshold sets and nothing reconciling them.
- **There is no Perfect Draft optimizer** — the only recommender is an unconstrained per-player
  sort, not a combinatorial optimizer.
- **Money, Constitution and League Media** have zero code behind them.

## What this audit could not test

`data/bdvm/`, `data/intel/` and the sharp ledger do not exist in this container, so those
subsystems' numeric behaviour is **Blocked by data**, not broken — a distinction the brief insists
on and this audit enforced at merge time. There is also **no historical snapshot store anywhere**,
which means no claim of model validation on this platform is currently reproducible. See
`EVIDENCE_LOG.md` for the full list and what would unblock each.

## On the two prior audits

They do not contradict each other; they scope different objects. The 2026-07-29 audit graded the
**value spine** and found it good. The 2026-08-04 audit graded the **decision layer built on top
of it** and found it incoherent. This audit's findings support both readings — and add the
missing third fact: the spine is sound, the decision layer is weak, **and the display layer
silently overrides the spine before the user sees it**, which neither predecessor caught.

One headline prior claim did not survive. The 2026-08-04 audit's second systemic finding — that
the benchmark grading the Hill curves is not independent of the boards it grades — was
reproduced, then **overturned** by an independent refuter: `holdout.py:251-265` scores a
candidate curve against each holdout source's *own published value shape*, never against the
blended board, so registry membership is irrelevant. Details in
`PRIOR_AUDIT_RECONCILIATION.md`.

## A note on the method, because it changed the answer

Findings are proposals until something tries to kill them. Of the 45 highest-impact findings put
to independent refuters, **13 were upheld, 31 rescoped and 1 overturned** — and every severity
correction moved *downward* (5× P0→P1, 2× P0→P2, 14× P1→P2, 2× P1→P3). Unverified audit
severities in this codebase run hot, which is worth remembering when reading the earlier audits
too. Published priorities here are the verified ones; `authoredPriority` records what the
workstream originally claimed.

The audit also caught itself making a large error. The first browser capture pointed at `:3000`
directly and logged 222 console errors across 41 pages — all artifacts of running without nginx,
since Next carries bridge routes for only 36 of 100 backend operations. Those captures are
retained as `*-INVALID.json` and their symptoms were pre-declared as non-findings so no
workstream could report them as defects.

## Highest-value next action

**Fix the TEP default.** One line in `useSettings.js` plus the customization predicate in
`dynasty-data.js`. It closes three P0s and moves Rankings and the Trade Calculator off *Not
trustworthy* — which is prerequisite to trusting anything downstream of them. Then the ROS sort
key (size XS) closes three more.

Two small diffs take six of the nine P0s off the board. `FIRST_REPAIR_PROMPT.md` is the
copy-paste brief for the first one. Nothing was repaired during this audit.

One correction to my own analysis, recorded because the audit's rule applies to the audit: I
originally grouped the TE SELL-label defect (W12-F002) under the TEP override and wrote that
fixing one would fix both. The roadmap workstream tested that claim rather than inheriting it,
re-ran the labels against a clean `GET /api/data` with no override in play, and got the same 32
of 35. They are two defects in the same TE-basis family at two code sites, and the Edge column
needs its own fix. The first-repair prompt already carried an instruction to re-measure the Edge
column rather than assume — that instruction is now answered, and the answer is no.

---

### Where to read next

| Question | Document |
|---|---|
| Can I trust subsystem X? | `TRUST_RATINGS.md` |
| What is the full finding list? | `FEATURE_STATUS_MATRIX.md` · `findings.json` |
| What should be fixed, in what order? | `REPAIR_ROADMAP.md` |
| Does the chain actually work end to end? | `PROOF_CASES.md` |
| How was this measured, and can I re-run it? | `EVIDENCE_LOG.md` |
| Where do the values come from? | `VALUE_FLOW_MAP.md` · `FORMULA_INVENTORY.md` |
| What contradicts what? | `CONFLICT_LOG.md` |
| What about the previous audits? | `PRIOR_AUDIT_RECONCILIATION.md` |
