# Low-value-asset follow-ups: integration report and owner decision packages (2026-10-21)

**Status:** coordination record. It authorizes nothing and approves nothing. Every decision below is PENDING.
Merging a research document is not approval of its recommendations. `docs/EXECUTION_PLAN.md` remains the sole
implementation-authorization record.
**Inputs:** the master development directive of 2026-10-21 (integration, forced-drop correctness, fairness
consistency, research validation), the owner decisions of 2026-10-20
(`docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md`), and the independent reviews listed in section B.
**Agent-OS-Receipt:** cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## A. Executive summary

- Four research PRs were merged after independent review and green validation: #1889 (public fairness consistency
  audit), #1888 (IDP replacement research), #1887 (depth-disclosure design), #1899 (LI-5 consolidation design). So
  were #1897 (a research-script repair) and #1898 (the fairness v2 correction). #1900 (history grade versus fairness
  bands) was open and revalidating when this was written.
- No valuation, source weight, vote, fairness threshold, flag default, package model, public-advisor gate or launch
  gate changed. `geom_q078_v1` (q = 0.78) and `fairness_bands_v2` are untouched.
- **Forced-drop fix (#1890) is dormant and NOT merged.** Two independent mathematical reviews and one fresh final
  review accepted it for a dormant merge (flag `forced_drop_cheapest_legal` stays OFF; OFF output is byte-identical to
  pure main). Both reviewers and the owner's provisional preference favour mode V5-R (`roster_rational`).
- **Why the verdict changes are large:** the incumbent forced-drop charge was 55-60% of the fairness-band base and
  exceeded the whole package gap in 96% of at-cap trades that needed a cut. Cheapest-legal selection plus not charging
  unpriced players a whole waiver value explains 86-97% of the median shift. This is a correction of a large old
  error, not an aggressive new rule. Its sign mix depends on whether the cheapest single-source roster-tail values are
  real cut costs, which only the production-box replay can settle.
- **Research corrected, no rule outcome changed:** the low-value-asset filler-flip and disclosure figures had been
  classified on the retired v1 denominator. Re-measured under v2: R-A and R-B are still not met, R-B0 holds, R-C still
  follows. F2 is worse than recorded (40-53% against 31-42%) and the old naive-rule fire rates of 19% / 13% are
  about 10% / 7%.
- **Public versus historical fairness:** the historical trade grade ("Fair trade" below 3.0% of the larger adjusted
  side, no floor) and the advisor's FAIR disagree on at least 3.9% of real own-league sides (6 of 153), all from the
  250-point floor with the history grade stricter. Recommendation: relabel only.

## B. PR status

| PR | State | Head | Independent review | Notes |
|---|---|---|---|---|
| #1897 | merged `7dd8cb048` | `deed0aad0` | ACCEPT | repaired a dead `public_category_from_decision` call; scripts only |
| #1889 | merged `9c05f1e9f` | `bd51beafb` | ACCEPT WITH FIXES (applied) | public path is one function for 2/3/4 teams; no forced-drop cost can reach it |
| #1888 | merged `48d4e3cc0` | `ac07c3e16` | ACCEPT WITH FIXES (applied) | numbers are as of the evidence commit; HEAD drifts anchors up to about 3%, conclusions unchanged |
| #1887 | merged `eac2fbc16` | `984f12986` | ACCEPT WITH FIXES (applied) | "counts in full" copy corrected for the package model |
| #1899 | merged `7d1cc3f02` | `647553cee` | ACCEPT WITH FIXES (applied) | design only |
| #1898 | merged `5e7783a6d` | `b26325964` | ACCEPT WITH FIXES (applied) | additive v2 addendum, `--band-basis` switch, recurrence guard |
| #1900 | open, revalidating | `fd528c09d` | ACCEPT WITH FIXES (applied) | read-only measurement and OD-F6 options |
| #1890 | open, NOT merged | `dfe4345b6` | two math reviews + fresh final: ACCEPT for dormant merge | flag OFF; PR body refreshed |
| #1852, #1884, #1873 | other lanes, untouched | | | see section I |

## C. Implementation results

- **#1890** (`src/trade/forced_drop_selection.py` and the roster-capacity owner): exact lineup-legal cheapest-cut
  search, verified against independent brute force in over 1,400 random leagues across reviews (both modes,
  geometric and rollback package models, over-cap and unpriced cases). Review fixes F1-F8 and the final review items
  are in. Notable: V5-R is not net-monotone (documented and pinned by a test); above 64 acquired-piece subsets V5
  now uses V5-R selection with package charging and says so; the taxi-unknown lower bound on an already-over-cap
  roster is now 0 with a labelled reason; a credit clamp covers a sole incoming piece; a new flag-ON evidence gap
  fires when a release is required and the charge is unknown.
- **Box replay (prepared, NOT run):** `scripts/forced_drop_fix_replay.py --box` (read-only guard installed before any
  application import, 4 GiB cap, aggregate-only stdout, pinned archive, CSV tree and code SHA) and
  `docs/trade/FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md`. It needs your authorization and #1890 merged and
  deployed dormant first.
- **Fairness correction (#1898):** inventory of 35 fairness-level computations (14 production, 0 inconsistent with the
  band owner; research repaired), `--band-basis current|v1_legacy`, a guard test, evidence under
  `docs/valuation/evidence/low_value_assets_2026-10-20/v2_correction/`.

## D. Forced-drop recommendation (V5 versus V5-R)

**Recommend V5-R (`roster_rational`).** It chooses the cheapest cut by base x scarcity across existing and incoming
players, then prices it (an acquired cut at the package credit given up, an existing cut at full value).
- V5-R is exact and polynomial, has no search-bound discontinuity, is invariant to uniform scarcity and never releases
  a dearer new player while keeping a cheaper existing one (V5 does this on 49 of 65 War Room and 36 of 70 census
  selections).
- On the overstatement test (523 trades needing a cut) V5-R's mean favourable bias against a full-charge benchmark is
  +65 points (up to +185 on 4-piece packages); V5's is +159 (up to +504, 27.8% of band base at the maximum). Neither
  mode ever ended a trade one category lower than the benchmark.
- V5-R's cost: its published net is not monotone (a free better player lowered the net in 63 of 767 random cases, up
  to 1,298) and it is dominated by V5's net where the cut sets differ. Reverse anomalies are structurally excluded only
  for pieces ranked second or later in a package with a priced sending side; the top piece can exceed the minimum
  scarcity multiplier (credit ratio up to 0.99 / 0.94 / 0.88 in 2- / 3- / 4-piece packages), so the box replay must
  count both anomaly directions.
- **Dormant merge is safe** (flag OFF; byte-identical output; flag stays default OFF; deploy gate
  `scripts/verify_owner_held_flags.py` unchanged), whichever default the mode constant carries.
- **Activation is not recommended yet.** It is blocked on the mode choice, your approval of the production impact, the
  box replay (real scarcity, Component B, both anomaly directions) and the War Room "worth N" copy.
- Verdict-change figures (local pinned replay, not production): War Room 109 / 105 category changes of 180 steps
  (V5 / V5-R), census 125 / 127 of 278 trades; 43-47% are evidence-gate lifts (withheld to decided); every charge
  decrease is at or under the cap and every increase is the single over-cap roster; the confidence level never changes
  where it was stated before and after.

## E. Fairness research corrections (old v1 versus corrected v2)

| item | v1 (recorded) | v2, same board | v2, current main |
|---|---|---|---|
| F1 best B treatment, offense / mixed (needs 80%) | up to 23.1% | up to 24.6% | up to 25.2% |
| F2 B, offense / mixed (needs 2% or less) | 37.1-41.7% | 40.5-45.3% | 39.8-44.8% |
| F3 all treatments (25% or less) | 7.1-14.4% | 7.9-15.0% | 7.4-15.0% |
| naive disclosure fires, depth / starter | 18.7% / 12.8% | 9.9% / 7.2% | 9.8% / 7.2% |
| War Room flips / neutralised / over-corrected / survive | 133 / 85 / 43 / 5 | identical | identical |

R-A and R-B are not met (unchanged), R-B0 holds (the 250-point floor decides fair or not at these base sizes, so the
denominators cannot move the crossing), R-C still holds. B's "fixes" are weaker in one real case (Gibbs plus four
fillers lands on "slight" instead of "fair"). Whether to re-measure the Phase 1-3 package-model research (also
recorded on v1) is an open scope question; the package-model KEEP does not depend on it.

## F. Public versus historical fairness consistency (workstream D, PR #1900)

Three rule differences: fair cut 3.0 against 3.5, no 250 floor against 250, and the denominator (larger adjusted side
against larger package utility). On real own-league trades (current board, gradable subset: 76 of 105 trades, 153
sides) they disagree on 6 sides (3.9%), all from the floor, history stricter; none is history-fair while the advisor
says NOT FAIR. On a labelled-illustrative synthetic grid they disagree on 7.4% (cut +62, floor +184, denominator -28).
The at-the-time population the public timeline shows is unmeasured (the temporal ledger is box-local), so 3.9% is a
lower bound. Recommendation A: relabel the history tier "Fair trade" to "Even outcome", state the value basis, define
the 3% once; zero grade changes. It does not resolve the "win" word collision.

## G. IDP replacement recommendations (#1888, #1899)

- Research (#1888): the displacement waiver anchor is the best unrostered player and is inflated by injured or
  rookie free agents at some positions; wire-order correlations are not significant at DB / LB / DL, and the evidence
  neither establishes a defect nor rules one out. No IDP value, source, weight or curve change is proposed.
- Design (#1899, PENDING): consolidate the anchor into a unit-agnostic LI-5 helper behind a new default-OFF flag,
  health filter via the existing availability and waiver-add-pool owners, scarcity (0.85-1.15) kept separate and
  inert. The code phase that touches #1890's files waits for #1890 to merge.

## H. Disclosure recommendation (#1887)

**V4: private-only, no public note, per-user hide, informational, default OFF.** Rule A-guarded with the floor
threshold; shadow counters in production before any display.
- Why no public note: the note fires if and only if a piece is below min(replacement level, lowest starter) on a pair
  that is NOT FAIR without it and FAIR with it, so rank-order probing recovers the position cutoffs. The leak is in
  when it fires, not in the words.
- Measured fire rates (A-guarded, floor, v2): private calculator 1.6% of 2,000 realistic trades (2.9% of FAIR
  results); own-league completed trades 4.5% (132 evaluated of 217 sides); War Room engineered samples 57.8% with one
  filler added; unsweetened synthetic base trades 21.1%; Trade Finder and Trade History unmeasured.
- Exact copy (after review fixes):
  - Label: `Depth note`.
  - `private.depth.you_receive`: "Part of your side of this result comes from lower-value depth ({pieces}). It is
    included in the result above, which is unchanged, but trade partners often give depth like this less credit than
    its listed value."
  - Learn more: depth is "a player valued below both the replacement level at his position in this league (roughly,
    the best player usually available without a trade) and the lowest current starter at that position across the
    league's lineups"; it appears only when removing these pieces would change this side's fairness result; "Depth
    like this can still matter for injuries, bye weeks and roster flexibility. In real trades, though, managers tend
    to give any extra piece less credit than its listed value."
- Weak evidence to know about: no user or outcome evidence the note helps; picks inclusion is nearly moot today (5 of
  120 picks are low-value, 37 unquantifiable); the floor threshold was introduced after the preregistered threshold's
  anchor sensitivity was seen (disclosed).

## I. Cross-project dependencies

- **#1852 (Chase Trade Market, census / maturity / reserve):** the original text of owner question Q2 was not found
  anywhere in the repository or on GitHub; only the implementing session's paraphrase exists ("lock about 20% of
  manager-lineage components permanently, split into five sub-reserves"; config status `PROPOSED_PENDING_OWNER_Q2`).
  Q2 blocks only persisting a reserve draw (and the preregistration's "Reserve share" placeholder); the census does not
  depend on it. The branch is 420 commits behind main with two trivial conflicts and its last two heads were never
  validated at L2. It needs reconciliation with main and a revalidation before it can be treated as green.
- **#1884 (outlier integrity V2 / V2.1):** verdict MORE RESEARCH REQUIRED; V2.1 dev stage NOT READY; earliest-ready
  date 2026-11-25. Six file conflicts with main and a stale PR body. All its flags stay OFF. Safe independent work:
  reconcile and revalidate, identity-evidence stamps (zero value change), independent review of the stale body.
- **#1873 (on-box research workflow):** keep open, do not merge or close. 2 of 3 pinned script hashes are stale
  against main, it runs the Phase 2 script rather than Phase 3, merging it would trigger a production deploy, and the
  prospective re-run it serves is optional (about two weeks after 2026-10-20).
- **Outlier blockers for #1890 / disclosure:** none directly; `source_freshness_schedule_v2` and the outlier flags
  stay OFF and are not touched here.

## J. Owner decision packages (all PENDING; nothing here is approved)

### Package 1: Forced-drop fix (#1890)
- **Decision:** (1a) choose the selection mode; (1b) approve the dormant merge; (1c) authorize the read-only
  production-box replay.
- **Recommended choice:** V5-R; yes; yes, after (1b) and a deploy of the dormant merge.
- **Reasoning:** V5-R is exact, has no discontinuity, is scarcity-robust and half as biased toward favourable verdicts
  on deep packages; the dormant merge is byte-identical to main with the flag OFF; the box replay is the only way to
  measure real scarcity, Component B and both anomaly directions.
- **Impact:** none until the flag is turned on. The replay reads the deployed checkout only and prints aggregates.
- **Risk:** V5-R's net is not monotone (documented). The replay uses the full-power deploy key path and prints to a
  public-repo-adjacent log, mitigated by the read-only guard and the aggregate-only output check.
- **Dependencies:** (1c) needs (1b) merged and deployed dormant; activation later also needs your approval of the
  production impact and the War Room copy change.
- **Default if unanswered:** stay as is: mode constant unchanged, #1890 unmerged, no replay.
- **Ready-to-use answer:** "Package 1: V5-R. Approve the dormant merge of #1890 with the flag OFF. After it is
  deployed, I authorize the read-only box replay in the runbook, run as the service user, aggregate output only. No
  activation yet."

### Package 2: Fairness consistency and the history grade (OD-F6)
- **Decision:** (2a) OD-F6 option; (2b) whether to re-measure the Phase 1-3 package-model research under v2.
- **Recommended choice:** (2a) option A, relabel only; (2b) yes, as a low-priority research task.
- **Reasoning:** A removes the shared word at no numeric risk; the measured disagreement is small, one-directional and
  from the floor; B on its own leaves a non-monotone grade; C needs OD-F4 evidence first. (2b) closes the last v1
  denominators in research at low cost and cannot change the package-model KEEP.
- **Impact:** A changes one displayed word (and a served policy field if a flag is used); no grade changes.
- **Risk:** low; A does not resolve the "win" collision.
- **Dependencies:** C depends on OD-F4 post-launch evidence.
- **Default:** no change to the history grade; no re-measurement.
- **Ready-to-use answer:** "OD-F6: option A (relabel tier 0 to 'Even outcome', state the basis, define the 3% once, no
  grade change). Yes, re-measure Phase 1-3 under v2 as research only."

### Package 3: IDP / LI-5 replacement-level consolidation (#1899)
- **Decision:** D1-D8 of the design. In short: (D1) which question the ladder answers; (D2) authorize design phases
  P1-P2 behind a default-OFF flag; (D3) reconcile the earlier "distinct" boundary; (D4-D8) band, candidates,
  populations, sequencing, scarcity.
- **Recommended choice:** D1 = A (this-season lineup replacement, health-filtered, with B kept as a non-served shadow
  lens); D2 = yes (P1-P2 now, P3 only after #1890 merges); D3 = yes; D4 = keep band ranks 1-3; D5 = candidates are
  add-pool-eligible players the availability owner reports available or uncertain, health not applied when the league
  week is unknown; D6 = preserve each consumer's rostered and auction-rookie populations; D7 = as above; D8 = scarcity
  stays inert at 1.0.
- **Reasoning:** consolidation was already the manifest's stated target (C2-REPL-01); the evidence neither proves nor
  rules out a defect, so this builds the instrument and measures before anything is served.
- **Impact:** none until a later activation decision on a replay's numbers.
- **Risk:** touches the same files as #1890 in P3; the health owners have documented gaps (no-team players, week
  relativity).
- **Dependencies:** P3 after #1890; activation never in the same release as #1890's.
- **Default:** no implementation.
- **Ready-to-use answer:** "Package 3: D1 A with B as a shadow lens; D2 yes (P1-P2 now, P3 after #1890 merges); D3
  yes; D4 keep the band; D5 as recommended; D6 preserve rostered and auction-rookie populations; D7 as recommended; D8
  scarcity stays inert."

### Package 4: Low-value depth disclosure (#1887)
- **Decision:** OD-1 to OD-10 of the design as one package.
- **Recommended choice:** V4 with rule A-guarded, floor threshold, picks included, calculator and War Room first, copy
  as in section H, keep the guard, keep the War Room Team Context line on hold until #1890 resolves; authorize only
  the default-OFF shadow counters (no display).
- **Reasoning:** a public note is a structural oracle for the replacement anchors; the private note is informational
  and has a measured low fire rate on realistic trades.
- **Impact:** none until counters are reviewed and a display decision is made.
- **Risk:** no outcome or user evidence the note helps; a private probing route needs auth, league membership and a
  rate limit.
- **Dependencies:** replacement-level evidence (Package 3) for the final anchor.
- **Default:** no implementation.
- **Ready-to-use answer:** "Package 4: V4 (private only, no public note). Rule A-guarded, floor threshold, picks
  included, copy as revised, keep the guard. Authorize the shadow counters behind a default-OFF flag; no display
  until I review them."

### Package 5: Other lanes
- **Decision:** (5a) Q2 of #1852; (5b) who owns reconciling #1884; (5c) the fate of #1873.
- **Recommended choice:** (5a) re-send the original Q2 wording; until then it stays PROPOSED and no reserve is drawn
  (if the paraphrase is right, approve only after the manager-lineage components exist and the census shows the 20%
  reserve is not concentrated in a few giant components); (5b) the session owning #1884 reconciles with main and
  revalidates; no flag changes; (5c) keep open, do not merge, redo the pinned manual command in early November.
- **Reasoning:** the original wording is not in the repository, so it cannot be recovered without guessing.
- **Impact:** none on served behaviour.
- **Risk:** a long-stale branch hides unvalidated heads.
- **Dependencies:** #1884's O-2 decision and fresh held-out boards (earliest 2026-11-25).
- **Default:** all three stay as they are.
- **Ready-to-use answer:** "Package 5: here is Q2 verbatim: <paste>. #1884's owner reconciles and revalidates, no flag
  changes. Keep #1873 open and unmerged; I will run the pinned manual command in early November instead."

## K. Next development phase (no new authorization implied)

1. On your Package 1 answer: merge #1890 dormant, deploy, then run the box replay and report both anomaly directions
   and Component B.
2. Independent work that can proceed now without any decision: reconcile #1852 and #1884 with main and revalidate;
   the LI-5 helper design phases P1-P2 only after Package 3 is answered.
3. Keep research and engineering aimed at better trade decisions, not more features: the box replay settles whether
   the forced-drop fix improves verdicts or only moves them, and that decision comes before anything is activated.
