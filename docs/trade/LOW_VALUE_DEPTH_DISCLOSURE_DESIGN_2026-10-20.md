# Low-value depth disclosure — trigger rules, copy and contract (DESIGN, 2026-10-20)

**Status: DESIGN ONLY — for owner review. Nothing is wired, activated or changed.**
No value, verdict, fairness threshold, package model or served response moves. The shadow
script below reads the board and writes one evidence file; it touches no served path.

**Authority:** `docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md` §1 (R-C approved,
"develop an optional, league-aware disclosure design in a separate workstream … bring the exact
copy and triggering rules for review before activation") and §5 (the public calculator stays a
neutral FAIR / NOT FAIR / UNABLE TO DETERMINE calculator with no proprietary numbers and no
roster-aware personalization).

**Inputs:** `docs/valuation/LOW_VALUE_ASSET_RESEARCH_2026-10-20.md` (§0, §2, §4, §6, §7.3, §10,
§11) and its evidence; the public advisor design and N-team spec on
`claude/advisor-public-backend` (#1861: `docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md`
Part 0, `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` §2.8, §4).

**Evidence:** `docs/trade/evidence/low_value_depth_disclosure_2026-10-20/disclosure_shadow.json`,
produced by `scripts/low_value_depth_disclosure_shadow.py` (aggregate-only, NFL names only;
checked with `assert_aggregate_only`). One run, ~50 s locally, on
`exports/archive/dynasty_export_20261020_052241.zip` — the same board as the research.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## 0. Summary for the owner

**Recommended trigger: rule A-guarded ("the result depends on the low-value depth").** For each
team, take the low-value depth pieces it *receives* (never its single most valuable piece).
Remove them, re-run the same package model and the same fairness band, and see whether that
team's fairness result changes. If it does, and that team's own legs (what it receives plus what
it gives) hold at least one piece that is not low-value depth, the note is shown.
- **Private surfaces:** the note fires when the team's fairness *region* changes
  (against / fair / in favour).
- **Public calculator: recommended no note (V4).** Any public variant leaks what the owner
  standard forbids. Because FAIR / NOT FAIR results are public, a user can build trades that are
  FAIR with an asset X and NOT FAIR without it; the note then fires exactly when X is low-value
  depth. Repeating this down the public market rank order reconstructs each position's cutoff
  `min(R_pos, S_pos)`: the replacement anchor or the lowest-starter line, whichever is lower
  (§9 R2). The note also often tells which team is behind within a FAIR result (§9 R1). A FAIR-only public variant is documented below as an
  **owner option** with these leaks stated plainly; it is not recommended.

**Interim piece threshold ("floor"):** a player is low-value depth only when his value is below
**both**:
- his position's replacement level in this league; and
- the lowest current starter at his position across the league's optimal lineups.

A pick is low-value depth below the league-wide replacement level. Under this threshold no
lineup starter can ever be called low-value depth. It also makes the rule nearly insensitive to
which replacement definition is used, which matters while the IDP anchors are under review.
**The floor was introduced in this workstream, after the prereg threshold's anchor sensitivity
had been measured.** It was not preregistered, and its robustness advantage is a post-hoc
comparison (§5.3, OD-2).

**Fire rates** (current anchors, floor threshold; full tables in §5):

| case | A-guarded (private) | public FAIR-only (owner option, leaks; not recommended) | naive rule (rejected) |
|---|---:|---:|---:|
| filler-caused flips (sweeteners cross a fairness region) | 61.2% | 3.8% | 66.8% |
| filler that turns an unfair result into FAIR ("made fair") | 89.5% | 89.5% | 86.0% |
| depth-sweetener cases | 1.2% | 0.1% | 18.7% |
| starter-sweetener cases | 1.3% | 0.1% | 12.8% |
| all-starter trades + starter / depth sweeteners (control) | 0.0% | 0.0% | 13.7% / 22.4% |
| realistic 2-team calculator trades | 1.9% | 0.9% | 32.9% |
| own-league completed trades, team sides (today's values) | 5.3% | 3.0% | 25.8% |

**Anchor sensitivity:** under the floor, filler-flip sensitivity is 61.2 / 58.5 / 58.3% for the
current, healthy-only and LI-5 replacement definitions. "Made fair" is 89.5 / 88.7 / 88.7%.
Under the prereg threshold (below the anchor, lineup starters excluded) it is 87.7 / 83.0 /
78.6%, and the calculator fire rate swings from 17.2% to 11.1%.

**Copy:** the exact strings are in §4.

**Open owner decisions** (§10):
- the rule;
- the threshold;
- whether picks are included;
- whether there is any public note (recommended: none, V4), given that every public variant
  measured leaks the replacement anchors (R2) and within-FAIR direction (R1);
- default visibility;
- the copy;
- which surfaces go first;
- the replacement-source switch.

## 1. What the disclosure is, and what it must never be

- **Informational only.**
  - It does not change any value, gap, verdict, band, threshold, ranking, Trade Finder order,
    Trade History grade or public category.
  - It is computed after the verdict, from the verdict's own inputs, and nothing reads it back.
- **Never an override.**
  - It sits outside the verdict badge, in neutral "info" styling, and never uses verdict colours.
  - Its copy states that the result above is unchanged and already counts the pieces in full.
- **Never "worthless".**
  - The research found 143 sub-2,000 players who beat free replacement (§2). The market discount
    is a general extra-piece convention, not a filler-specific fact (§7.3).
  - So the copy says trade partners *often give less credit*. It never says the pieces have no
    value, should not be counted, or should be removed.
- **League-aware.** Every line it uses comes from the requested league:
  - the replacement level by position;
  - the lowest optimal-lineup starter by position;
  - the pick replacement level.

  An unavailable league context means no note. There is never a home-league fallback.
- **Optional.** The user can hide it. Default visibility is an owner decision (§6).
- **Server-side only.**
  - One canonical owner computes it. The browser renders a state and a copy key.
  - There is no frontend engine and no JavaScript port.

## 2. Definitions

### 2.1 League depth lines

For league `L` on the served board:

| line | interim source (canonical owner, unchanged) | today, `dynasty_main` |
|---|---|---|
| `R_pos`, replacement level per position | `src/draft/displacement.waiver_values_by_position`: best unrostered `rankDerivedValue` at the position (the prereg §2 anchor) | QB 1,923 · RB 1,626 · WR 1,802 · TE 2,061 · DL 1,918 · LB 2,149 · DB 2,156 |
| `S_pos`, lowest current starter per position | min `rankDerivedValue` over `sleeper.teams[].optimalLineup.starters` (C2-U1 owner, `src/ros/lineup.py`) | QB 1,988 · RB 1,653 · WR 1,510 · TE 1,671 · DL 1,539 · LB 1,474 · DB 1,335 |
| `R_*`, pick and league-wide replacement | `src/trade/faab_engine.resolve_anchors(...).v_repl` (FAAB `V_repl`) | 1,687 |

The design never invents a replacement level.
- When investigation B (IDP replacement and league scoring) or a successor approves a canonical
  replacement owner, `R_pos` is read from that owner instead.
- That switch is one config key (§7.4).
- Every line is a league-level aggregate over all twelve rosters. No line depends on which
  manager is asking.

### 2.2 Low-value depth (LVD) piece

Each asset in a trade gets exactly one of three classes.

| asset | class |
|---|---|
| player, priced, position `p` with `R_p` and `S_p` | **LVD** iff `value < min(R_p, S_p)` (the **floor** threshold, recommended interim). Every optimal-lineup starter has `value ≥ S_p`, so **no starter can be LVD** |
| pick, priced | **LVD** iff `value < R_*`. A pick never has a starter line |
| no canonical value: off-board, unpriced, quarantined, a completed-draft pick | **UNKNOWN**. Never zero, never LVD, never "not LVD" |
| priced player whose position has no `R_p` or `S_p` (e.g. K, or a position missing from the lineup) | **UNKNOWN** |

**Alternative threshold ("prereg").** Measured but not recommended for the interim:
- LVD iff the player is not a genuine starter and `value < R_p`;
- this is the research's §3 "expendable filler" class;
- it is more sensitive, but it inherits the WR/TE inversion (starter line below the anchor) and
  the inflated IDP anchors (§5.3).

### 2.3 The quantities the rule reads

In the implementation, all of these are read from the existing owners and none is
re-implemented. (The shadow script re-implements the utility and adjusted totals and checks them
against the canonical dispatch; §5.)

- **Received and given packages.** For team `i` in a 2-, 3- or 4-team trade: `Rcv_i` (assets
  team `i` receives) and `Gv_i` (assets it gives), from the canonical ledger.
- **Package utility.** `U(·)` through the package-model dispatch
  (`src/valuation_math/package_model.py`, active `geom_q078_v1`).
- **Team gap.** `gap_i = U(Rcv_i) − U(Gv_i)`, exactly the per-team gap in N-team spec §1 and §2.8
  (locality: team `i`'s result depends only on its own legs).
- **Band.** `band_i = fairness_bands.classify(gap_i, max(adjusted sides))`, the market lens's own
  band. The real result is *read* from the market lens. Only the counterfactual is computed,
  through the same two functions.
- **Region.** `region_i = 0` if `band_i` is fair, else `sign(gap_i)` (−1 against team `i`,
  +1 in its favour).
- **Top piece.** `top(Rcv_i)` is the highest-valued received piece; ties go to the
  lowest canonical asset id.
- **LVD extras.** `E_i = { a ∈ Rcv_i : class(a) = LVD, a ≠ top(Rcv_i) }`.
- **Guard.** `mixed = ∃ a ∈ Rcv_i ∪ Gv_i with class(a) = not-LVD`. It is team-local: only team
  `i`'s own legs count (in a 2-team trade they are the whole trade; in a 3–4-team trade they are
  not). The shadow script implements exactly this.

## 3. Candidate trigger rules (deterministic, server-side)

**Preconditions for every rule.** The note is **not evaluated**, and nothing is shown, when any
of these hold:
1. any asset in `Rcv_i ∪ Gv_i` is UNKNOWN;
2. team `i`'s fairness state is UNABLE / NOT_ENOUGH_EVIDENCE;
3. the league's depth lines are unavailable (no rosters, `sleeperDataReady` false,
   league-scoring gate refused, or no lineups);
4. the flag is off.

**Why UNKNOWN blocks rather than skips.** The rule asks "would the result change without the LVD
pieces?". An unknown piece might be one of them, and treating it as either LVD or not would
guess. An unknown piece already makes the verdict UNABLE / NOT_ENOUGH_EVIDENCE on every
analyze surface (`trade_decision.asset_evidence_gaps`). So in practice this only matters where a
calculator shows a partial meter.

### 3.1 Rule A, verdict dependence (recommended, with the guard)

**Private, `A_guarded`:**
```
fires_i  ⇔  E_i ≠ ∅
         ∧  region(Rcv_i \ E_i, Gv_i) ≠ region(Rcv_i, Gv_i)
         ∧  mixed
```

**Public, `A_guarded_publicFairOnly`** (owner option only; not recommended, see §9):
```
fires_i  ⇔  E_i ≠ ∅
         ∧  band_i = fair
         ∧  band(Rcv_i \ E_i, Gv_i) ≠ fair
         ∧  mixed
```

**Why each element is there:**
- **"Depends on":** the note appears only when the low-value depth decides the result.
  - Filler sweeteners that do not move the result rarely cause a note. On filler cases that do
    not flip, `A_guarded` still fires on 9.3% (9.0–16.1% across the six variants), but only
    0.0–0.2% is attributable to the sweeteners. The rest comes from low-value pieces already in
    the base package, where the base result itself depends on them (§5.1).
  - Depth and starter sweeteners almost never trigger it (1.1–1.8%).
- **The top piece is never removed.** The market convention concerns *extra* pieces (M2). A
  1-for-1 of two low-value players is not a padding question.
- **The guard** suppresses a team whose own legs are all LVD pieces: two benches swapping
  filler. Without it, 40% of the unsweetened low-tier base trades fired; with it, 26.8%. This
  guard was added
  *after* seeing those base trades. It is reported separately (`A_dependence` vs `A_guarded`) so
  the owner can drop it.
- **Received side only.** A piece team `i` gives is a piece another team receives, and is
  evaluated there. In 2-team trades the two evaluations cover both directions.
- **Public variant (owner option): FAIR only.** Removing received pieces can only move a team
  *against* itself, because the package utility is monotone (S6: "an added piece never hurts").
  So a NOT FAIR → FAIR counterfactual would reveal that the NOT FAIR result leans *toward* that
  team, and the lean of a NOT FAIR result is never public (spec §4.3, privacy M4). Restricting
  to FAIR results avoids that, but it does **not** make the note direction-free:
  - a note implies `gap_i < ΔU(E_i) − t`, where `ΔU(E_i) = U(Rcv_i) − U(Rcv_i \ E_i)` and `t` is
    the fairness threshold of the counterfactual package;
  - when `ΔU(E_i) < t` (small extras in a large package) this means team `i` is **behind**
    within the FAIR band; in a 2-team trade a note on one row therefore says which side leads;
  - this is a within-FAIR direction and gap signal (§9 R1), and the note is also a per-asset
    oracle for the replacement anchors (§9 R2). That is why no public note is recommended.

  The public case the variant was meant for is "FAIR, but made fair by padding", research §0
  question 4 (Hurts vs Egbuka + Hodgins).

### 3.2 Rule B, share of value in low-value depth (alternative)

```
fires_i  ⇔  |Rcv_i| ≥ 2  ∧  Σ_{a∈E_i} value(a) / Σ_{a∈Rcv_i} value(a)  ≥  X ,   X = 0.25 (PRIOR)
```

- X is a declared prior, "a quarter of the package". It was fixed before measurement and never
  tuned.
- The rule fires whether or not the pieces matter to the result:
  - on 51% of filler cases where the filler did not move the verdict;
  - on 13–14% of depth and starter cases, almost all from low-value pieces already in the base
    package (attributable: 0.8–1.1%).

### 3.3 Rule C, piece-count asymmetry with low-value extras (alternative)

```
fires_i  ⇔  |Rcv_i| > |Gv_i|  ∧  ∃ a ∈ (the |Rcv_i| − |Gv_i| lowest-valued pieces of Rcv_i) with class(a) = LVD
```

- It is the most sensitive rule: 91.6% of filler-caused flips.
- It is also the least specific: 23–24% of depth and starter cases, and 77% of filler cases that
  did not move the result.
- It is not a safe public variant either. In any k-for-(k+1) trade whose lowest piece is X it
  fires exactly when X is LVD, so it is the same per-asset oracle as rule A's public variant,
  without even needing a FAIR result (§9 R2).

### 3.4 Comparator: the rejected naive rule

The comparator fires when the `B_currency_replacement` treatment would change the signed level.
- It is reproduced exactly: 6,586 / 2,118 / 1,249 fires on filler / depth / starter cases, equal
  to the committed `shadow_replay.json`.
- It fires on 13.7–22.4% of the **all-starter** control trades and on a third of realistic
  calculator trades.
- On the research's real examples it fires on Wilson vs Ferguson + Kelce, the six-starter
  package, and Schwesinger vs Baun + Parsons. Rule A fires on none of them.

### 3.5 Multi-team and the surfaces

- **Multi-team.** The rules are per team, and team `i`'s result depends only on its own legs
  (spec I10). So the identical rule applies to 2-, 3- and 4-team trades. No 3–4-team market
  evidence exists; the box run excluded the 64 multi-team trades. Locally, only 3 own-league
  3-team trades enter §5.4.
- **War Room / analyze.** The rule reads the **market (asset-only) fairness**, the quantity the
  market convention is about, even when Team Context is on.
  - Team Context's forced-release charge is a roster consequence, not a market convention.
  - Mixing the two would double-count once investigation A's fix lands (research §5.3).
- **Trade Finder.** The note is attached to each finder candidate after ranking. It is never an
  input to ranking, filtering or the score (test §8).
- **Trade History.**
  - **Current Grade:** evaluated with today's lines.
  - **At-the-Time and How It Aged:** `not_evaluated: historical_lines_unavailable`. The temporal
    ledger stores no historical replacement lines, and today's lines are not the lines at the
    trade (missing ≠ current).

## 4. Exact copy

**Common rules** for every string:
- no numbers;
- no replacement levels, anchors, gaps, percentages or formulas;
- no "worthless", "no value" or "should";
- no closeness or magnitude wording.

The public strings also pass the advisor's forbidden-word scan:
- accept, decline, approve, deny, reject, should, recommend, advice, favorable, unfavorable,
  win, lose, smash, fleece, "your roster", "your lineup";
- the private strings avoid all of these except "your", which private surfaces may use.

**Wording choice.** Every string says **"lower-value depth"** rather than "low-value". It is the
same concept in softer wording that does not read as a judgement of the player.

### 4.1 Private (calculator, War Room, Trade Finder, Trade History current grade)

**Label (chip / heading):** `Depth note`

**One-sentence explanation.** There are three variants, chosen by the server from whose received
package fired. `{pieces}` is the comma-separated display names of `E_i`, which the private UI
already lists.

| copy key | when | text |
|---|---|---|
| `private.depth.you_receive` | the viewing team's received package fired | `Part of your side of this result comes from lower-value depth ({pieces}). It counts in full here, but trade partners often give depth like this less credit than its listed value.` |
| `private.depth.you_send` | the partner's received package fired (pieces the viewer would send) | `Part of the other side of this result comes from lower-value depth you would send ({pieces}). It counts in full here, but a trade partner may give depth like this less credit than its listed value.` |
| `private.depth.side` | calculator with no team perspective; `{side}` = "Side A" / "Side B" / the team name | `Part of {side}'s side of this result comes from lower-value depth ({pieces}). It counts in full here, but trade partners often give depth like this less credit than its listed value.` |

**War Room roster-context line.** Private only. It is appended to `private.depth.you_receive`
when Team Context is ON and the roster-capacity block reports ≥ 1 forced drop for this trade.
- Key: `private.depth.team_context`.
- Text: `With Team Context on, the Decision above also counts the roster spots these pieces would
  take.`
- It reads the existing roster-capacity block. It adds no new number, and is withheld while
  investigation A's fix is pending if the owner prefers (OD-9).

**Learn more** (`private.depth.learn_more`, expandable):

> **What counts as lower-value depth?** A player valued below both the replacement level at his
> position in this league (roughly, what is typically available on the waiver wire) and the
> lowest current starter at that position across the league's lineups. A draft pick counts when
> it is valued below the league's general replacement level.
>
> **Why this note appears.** It appears only when removing these pieces would change this
> side's fairness result. The values, the result and the fairness threshold shown above are
> unchanged. Depth like this has real value: many of these players start in some weeks. In
> real trades, though, managers tend to give extra pieces less credit than their listed value.
>
> You can hide depth notes in Settings.

### 4.2 Public (owner option only; recommended: no public note)

Fair / Not Fair calculator, per-team row, shown only when that team is FAIR. **Not
recommended:** whatever the copy says, the *firing* of this note leaks the replacement anchors
and within-FAIR direction (§9 R1, R2). The strings are written out so the owner can decide with
the exact text in front of them.

**Label:** `Depth note`

**One-sentence explanation** (`public.depth.fair_with_depth`):

> `Part of what this team receives is lower-value depth. It is counted in full in this result, but trade partners often give depth like this less credit.`

**Learn more** (`public.depth.learn_more`):

> `Lower-value depth is a player or pick that managers in this league can usually replace without a trade. These pieces still have real value and are counted in full. In real trades, managers often give extra pieces like these less credit than they are counted at here. This note is for information only and does not change the result above.`

**The public copy deliberately says nothing about dependence.** It does not say the result
"depends on" or "relies on" the pieces, because that is closeness wording. The trigger's
semantics still carry that information, and more; see §9 R1.

The public copy names no pieces, but **that does not protect the classification**. In a 1-for-2
the received extra is the only candidate, so whether the note fires is already a per-asset
read-out; repeated over assets it reconstructs the replacement anchors (§9 R2).

### 4.3 Placement and accessibility

| surface | placement |
|---|---|
| Private calculator (`/trade`) | Below `TradeMeter`, beside `TradeFairnessExplanation`, as an info callout. Not inside the meter or verdict text |
| War Room (`TradeWarRoom`) | Inside the "Market fairness" section (spec C4 keeps "Market fairness" and "Decision" separate). Never in the Decision headline |
| Trade Finder | A small `Depth note` chip on the candidate card with the sentence in a tooltip and popover. It never changes card order |
| Trade History | On the Current Grade row only |
| Public advisor (only if OD-4 adopts a public note) | Under the team row's `reasonText`, as a collapsed `<details>` labelled `Depth note`. Never inside the FAIR badge and never in the overall row |

**Accessibility:**
- The note is `role="note"`, tied to its team or side with `aria-describedby`, and placed after
  the verdict in reading order.
- It is not `aria-live`: it is not an alert.
- "Learn more" is a real `<button aria-expanded>` or `<details>`.
- An icon is always paired with text, and nothing is conveyed by colour alone. Contrast is
  ≥ 4.5:1.
- The hide control is labelled `Hide depth notes`.
- The note keeps the 44 px touch target on mobile and never truncates the verdict.

### 4.4 Worked examples (today's board; values are the canonical values already shown in the private UI)

"Favours the team receiving side B" is the evidence's `favours: B`: side B's package is the
larger one, so the team that *receives* it is ahead.

| # | trade (side A for side B) | GEOM_78 result | LVD pieces (floor) | private | public (owner option, not recommended) |
|---|---|---|---|---|---|
| 1 | Jalen Hurts (5,919) for Emeka Egbuka (5,197) + Isaiah Hodgins (897) | +22 **fair** | Hodgins | **shown** to the team receiving Egbuka + Hodgins: *"Part of your side of this result comes from lower-value depth (Isaiah Hodgins). It counts in full here, but trade partners often give depth like this less credit than its listed value."* To the team receiving Hurts: the *`you_send`* variant, naming Hodgins | **shown** on the team receiving Egbuka + Hodgins: FAIR FOR THIS TEAM + *"Part of what this team receives is lower-value depth. It is counted in full in this result, but trade partners often give depth like this less credit."* |
| 2 | Hurts for Egbuka + Hodgins, Frank Gore, Khalil Herbert, Mason Tipton (~900 each) | −1,300 **unfair; favours the team receiving side B** | the four fillers | **shown** (`you_receive` names all four): without them the team receiving side B would be behind, so its "in favour" result depends on them | **not shown**: NOT FAIR, and a note could only reveal the lean |
| 3 | Jahmyr Gibbs (9,864) for Bryce Young (5,493) + Tucker Kraft (5,439) | +129 fair | none | not shown | not shown |
| 4 | Garrett Wilson (6,472) for Jake Ferguson (3,529) + Travis Kelce (3,490) | +221 fair | none: Kelce is usable depth, far above the TE floor | not shown (**the naive rule fired here**) | not shown |
| 5 | Denzel Boston (4,204) for David Bailey (DL 3,475) + Jadon Canady (DB 1,124) + Zakee Wheatley (DB 1,125) | −832 unfair; favours the team receiving side B | Canady, Wheatley (below the DB floor, 1,335) | **shown** (`you_receive`, two DB names) | not shown (NOT FAIR) |
| 6 | 2027 Pick 1.04 (5,090) for 2027 Pick 1.12 (3,942) + 2029 Late 4th (1,325) + 2029 Mid 4th (1,452) | −791 unfair; favours the team receiving side B | both 2029 4ths (below `R_*` 1,687) | **shown** | not shown (NOT FAIR) |

Further non-firing checks, where the naive rule fires but rule A does not:
- Gibbs for six ~2,950 starters / usable depth (−564, fair);
- Carson Schwesinger for Zack Baun + Micah Parsons (+176, fair).

Under the floor threshold, every example gives the same answer for all three anchor definitions
(`workedExamples` in the evidence).

## 5. Shadow measurement

Unless stated otherwise:
- the figures are the share of cases on which the rule fires for either team;
- the current anchors are used, with the floor threshold;
- every rule is computed from the same verdict function.

**What the verdict function reuses, and what it re-implements.** Only the band classifier,
`fairness_bands.classify`, is the canonical function. The package utility is the research `owa`
(q = 0.78 hard-coded) and the adjusted totals are the research re-implementation
`P2.adjusted`. So the script checks **every** incumbent evaluation against the canonical
`src/valuation_math/package_model.py` dispatch for the active model (`geom_q078_v1`) and aborts on
any mismatch (`packageModelParity` in the evidence):
- **648,080** evaluations checked;
- the utility gap equals `geom_utility`'s to a relative float tolerance of 1e-9;
- the adjusted totals equal `adjusted_pair_totals`' within 0.5, because the canonical dispatch
  rounds the adjustment to a whole number and the research form does not;
- read on the canonical whole-number adjusted gap, the band agrees on 648,022 evaluations and
  differs on 58 (0.009%), all at a band edge, from that rounding alone.

The War Room population also re-runs the served engine (§5.5), which agrees on 180 / 180 steps.

### 5.1 Filler-flip study

The research's 32,180 cases were regenerated case for case and match the committed evidence
exactly:
- incumbent flips per class and category equal `shadow_replay.json`;
- the naive rule fires 6,586 / 2,118 / 1,249, equal to the committed counts.

| group (cases) | A_guarded | public FAIR-only (owner option) | B_share25 | C_extraPieces | naive_B |
|---|---:|---:|---:|---:|---:|
| filler, flip (9,273) | **61.2** | 3.8 | 65.8 | 91.6 | 66.8 |
| filler, made fair (399) | **89.5** | **89.5** | 19.3 | 91.7 | 86.0 |
| filler, no flip (1,867) | 9.3 (attrib. 0.2) | 1.5 | 51.2 | 76.7 | 21.2 |
| depth (11,300) | **1.2** (attrib. 0.8) | 0.1 | 14.1 | 23.4 | 18.7 |
| starter (9,740) | **1.3** (attrib. 0.7) | 0.1 | 12.9 | 24.4 | 12.8 |
| starter-only bases + depth sweeteners (4,460) | **0.0** | 0.0 | 0.0 | 0.0 | 22.4 |
| starter-only bases + starter sweeteners (4,460) | **0.0** | 0.0 | 0.0 | 0.0 | 13.7 |
| unsweetened base trades (2,825) | 20.5 | 15.9 | 18.4 | 21.3 | 37.4 |

- "attrib." = fires on the sweetened package and did not fire on that package before the
  sweeteners. The remaining depth and starter fires come from low-value pieces already in a base
  package, where the base result itself depends on them.
- The public FAIR-only rule rarely fires on "flips", because most study flips go
  fair → in favour (NOT FAIR). On the public-relevant subset, unfair → FAIR, it fires 89.5%.

**Filler-caused flips by asset class (A_guarded):**

| | offense | IDP | picks | mixed |
|---|---:|---:|---:|---:|
| floor | 65.8 | **42.1** | 100.0 | 56.4 |
| prereg | 87.3 | 81.9 | 100.0 | 88.1 |

The picks column is 100% by construction, not by evidence: the pick line `R_*` is exactly the
line the study used to label pick filler, and picks have no starter clamp. So every pick filler
sweetener is LVD, and removing the LVD extras restores the base result the flip came from.

The floor's lower IDP sensitivity is deliberate. The study's IDP "filler" includes DBs
1,335–2,156 and LBs 1,474–2,149 that sit above the lowest league starter. Investigation B found
those anchors are set by injured or non-producing free agents, and that 19 of 35 DB starters sit
below even the healthy DB anchor. The floor declines to call such players low-value depth.

### 5.2 Realistic 2-team calculator trades

Population: the research's S5a population, same seed. Assets come from the top-500; shapes are
1–3 vs na..na+4; raw gap is within 25%; n = 2,000.

| | all | FAIR results (429) | NOT FAIR (1,571) |
|---|---:|---:|---:|
| A_guarded, floor | 1.9 | 4.4 | 1.3 |
| public FAIR-only, floor (owner option) | 0.9 | 4.4 | 0.0 |
| A_guarded, prereg | 17.2 | 32.2 | 13.2 |
| naive_B | 32.9 | 33.3 | 32.7 |

- Top-500 trades rarely contain floor-LVD pieces.
- Under the floor, the 1.9% is entirely QBs and RBs between the healthy and current anchors
  (1,605–1,923). It falls to 0.0% under the healthy and LI-5 anchors. That is the one place the
  floor remains anchor-sensitive (QB: the current anchor is a player Sleeper lists as injured or inactive).

### 5.3 Anchor sensitivity (A_guarded)

| metric | current | healthy-only | LI-5 banded |
|---|---:|---:|---:|
| floor: filler-caused flips | 61.2 | 58.5 | 58.3 |
| floor: filler made fair | 89.5 | 88.7 | 88.7 |
| floor: depth / starter cases | 1.2 / 1.3 | 1.1 / 1.2 | 1.1 / 1.2 |
| floor: calculator sample | 1.9 | 0.0 | 0.0 |
| floor: War Room, 1 filler added | 57.8 | 55.6 | 55.6 |
| prereg: filler-caused flips | 87.7 | 83.0 | 78.6 |
| prereg: filler made fair | 100.0 | 99.2 | 96.5 |
| prereg: calculator sample | 17.2 | 14.2 | 11.1 |
| prereg: War Room, 1 filler added | 95.6 | 91.1 | 88.9 |

**The anchor definitions:**
- **Healthy-only:** investigation B's best unrostered player who is healthy today, on the same
  board. It is pinned from `idp_anomaly.json` H1: QB 1,648, RB 1,605, TE 1,855, DB 1,917; other
  positions are unchanged.
- **LI-5 banded:** S1's `li5_waiverBanded`.

**The floor thresholds are identical under all three** at WR, TE, DL, LB and DB, because the
lowest starter binds. They differ only at QB (1,923 / 1,648 / 1,661) and RB (1,626 / 1,605 /
1,569).

**This is the robustness argument for the interim rule.** Whichever replacement definition the
IDP review approves, the floor moves by at most a few points of sensitivity. The prereg
threshold moves by about 9 points and changes calculator exposure by about a third.

**Post-hoc disclosure.** The floor threshold was introduced in this workstream, after the prereg
threshold's anchor sensitivity had been measured, and was chosen partly *because* it is less
sensitive. It was not preregistered. The comparison above is therefore an argument for the
floor's construction (the lowest starter binds at five of seven positions on every anchor set),
not an independent test of it.

### 5.4 Own-league completed trades

Population:
- 107 trades: 104 with two teams, 3 with three teams;
- 217 team sides, valued with **today's** board.

85 sides are **not evaluated**, never priced at zero and never dropped:
- 63 contain an unpriced piece, mostly completed 2026 picks;
- 18 contain a quarantined piece (UNKNOWN, §2.2);
- 4 are one-sided: the team gives or receives nothing, so there is no gap to classify.

| rule | current | healthy | LI-5 |
|---|---:|---:|---:|
| A_guarded (floor) | 5.3 | 3.8 | 3.8 |
| public FAIR-only (floor; owner option) | 3.0 | 1.5 | 1.5 |
| naive_B | 25.8 | 25.8 | 25.8 |

All shares are of the 132 evaluated sides.

### 5.5 Real-roster War Room trades (`/api/trade/analyze` sampling, same seed)

**Population:** 45 samples on rosters at the 58-player cap, with 0–3 opponent fillers added.

**Engine check.** The served engine was re-run.
- The market ordinal used here **agrees with the served asset-only lens on 180 / 180 steps**.
- The Team-Context outcomes reproduce the research exactly: 85 neutralised, 43 over-corrected,
  5 surviving, 2 no flip.

| fillers added | 0 | 1 | 2 | 3 |
|---|---:|---:|---:|---:|
| A_guarded, floor | 0.0 | 57.8 | 28.9 | 20.0 |
| A_guarded, prereg | 0.0 | 95.6 | 100.0 | 100.0 |
| public FAIR-only, floor (owner option) | 0.0 | 2.2 | 0.0 | 0.0 |

**Why the floor rate falls as fillers are added.**
- The War Room's fillers are §3 filler, below the current anchor. Many are IDP between the floor
  and the anchor.
- With more fillers, the non-floor ones alone carry the flip, so removing only the floor-LVD
  pieces no longer changes the region.
- The note then stays silent, because the result rests on pieces valued like league starters.

**Beside Team Context.**
- Every floor fire on a neutralised or over-corrected step sits next to a Team-Context Decision
  that already goes against the receiver: 33 / 33 and 13 / 13.
- The private copy is written to read correctly there. It says the market result counts the
  pieces in full; it never says the Decision is too generous.

## 6. Visibility options (owner decision OD-5)

| option | private surfaces | public |
|---|---|---|
| V1 | shown by default, with a persistent per-user `Hide depth notes` (the existing per-user settings store) | the `Depth note` label is visible; the sentence is behind the expand; anonymous hide stored in `localStorage` only (per-viewer convenience, try/catch, renders correctly without it) |
| V2 | shown by default | shown expanded by default |
| V3 | off by default; opt in under Settings | off by default; opt in per visit |
| **V4 (recommended)** | as V1: shown by default, with the persistent per-user `Hide depth notes` | **never shown** |

**Why V4.** Every public variant leaks the replacement anchors and within-FAIR direction through
*when* it fires (§9 R1, R2), and the owner standard (§5) forbids revealing replacement anchors.
Visibility settings cannot fix that: a hidden-by-default note still fires for anyone who expands
it. V1–V3's public column applies only if the owner explicitly accepts the leak (OD-4).

## 7. API and contract sketch (no code in this PR)

### 7.1 One canonical owner: `src/trade/depth_disclosure.py` (pure)

```python
DISCLOSURE_VERSION = "lvd_disclosure_v1"

@dataclass(frozen=True)
class DepthLines:                     # league-level, built once per (league, board generation)
    league_key: str
    replacement: Mapping[str, float]  # R_pos, from the configured replacement owner
    lowest_starter: Mapping[str, float]  # S_pos, from sleeper.teams[].optimalLineup
    pick_line: float                  # R_*, faab_engine.resolve_anchors(...).v_repl
    threshold: Literal["floor", "prereg"]
    source: Mapping[str, str]         # provenance: owner + version per line

def league_depth_lines(contract, league_key) -> DepthLines | Unavailable   # never a default league
def classify_piece(asset, lines) -> Literal["lvd", "not_lvd", "unknown"]
def team_depth_disclosure(received, given, lines, *, utility, classify_band) -> TeamDepthDisclosure
```

- `utility` and `classify_band` are *passed in* from `package_model` and `fairness_bands`. The
  module defines no threshold, no curve and no package maths; an AST test pins this.
- `TeamDepthDisclosure`:
  - `state`: `shown` | `not_shown` | `not_evaluated`;
  - `reason`: one of `no_low_value_depth`, `result_does_not_depend`, `only_low_value_pieces`,
    `unknown_piece`, `lines_unavailable`, `result_unavailable`,
    `historical_lines_unavailable`, `disabled`;
  - `public_fair_only`: bool;
  - `piece_ids`: tuple.

### 7.2 Where it runs, reusing existing owners

| surface | computed in | field |
|---|---|---|
| War Room / `POST /api/trade/analyze` | `analyze_service.analyze_for_team`, after the market lens, for both teams | `teams[i].depthDisclosure` (private) |
| `POST /api/trade/analyze-multi` | `analyze_service.analyze_trade_n`, per team beside `team_verdicts.team_fairness` | `teams[i].depthDisclosure` |
| Private calculator | the calculator already posts its packages to `/api/trade/analyze` for the War Room panel; for a team-less hypothetical, a thin read-only `POST /api/trade/depth-disclosure` (league key + asset ids per side) calls the same owner | same shape |
| Trade Finder | `finder.py` post-ranking decoration of the returned candidates only | `candidate.depthDisclosure` |
| Trade History | `src/api/trade_history_asof.py`, Current Grade only | `currentGrade.depthDisclosure` |
| Public advisor (only if OD-4 accepts the leak; not recommended) | `team_verdicts` computes it; `public_advisor.reduce_fairness` receives only the enum | `teams[i].depthNote` |

**Private shape:**
```jsonc
"depthDisclosure": {
  "version": "lvd_disclosure_v1",
  "state": "shown",                       // shown | not_shown | not_evaluated
  "reason": null,                         // see §7.1
  "copyKey": "private.depth.you_receive", // server-chosen; frontend maps key -> fixed string
  "pieces": [{"assetId": "…", "label": "Isaiah Hodgins"}]
}
```

It carries no line, anchor, gap or counterfactual value. Private numbers stay where the UI
already shows them.

**Public shape** (only if OD-4 accepts the leak; under the recommended V4 no public field is
added): one new nullable enum per team row, nothing else.
```jsonc
{"rosterId": 3, "result": "FAIR", "label": "FAIR FOR THIS TEAM",
 "reasonCode": "within_fairness_threshold", "reasonText": "…", "unavailableAssetIds": [],
 "depthNote": "LOWER_VALUE_DEPTH"}            // or null; null whenever result != "FAIR"
```

The copy comes from the fixed server copy table (`public.depth.*`). The frontend maps the enum
to the table text and never builds text.

### 7.3 Flags, configuration and rollback

| item | value |
|---|---|
| private flag | `low_value_depth_disclosure`, default **OFF**; when OFF, `depthDisclosure = {state: "not_evaluated", reason: "disabled"}` |
| public flag | not built under the recommended V4. Only if OD-4 accepts the leak: `low_value_depth_disclosure_public`, default **OFF**; needs the advisor launch gate as well; when OFF, `depthNote: null` |
| config | `config/trade/depth_disclosure.json`: `{"version": "lvd_disclosure_v1", "threshold": "floor", "includePicks": true, "guard": true, "replacementSource": "displacement.waiver_values_by_position", "copyVersion": "…"}`. Every entry is an owner-approved choice; none is tuned to agreement |
| rollback | `RISKIT_FEATURE_LOW_VALUE_DEPTH_DISCLOSURE=0` (and `…_PUBLIC=0`) + restart. Because nothing reads the field back, rollback is display-only by construction |

### 7.4 Consuming a later approved replacement level

`replacementSource` names the owner of `R_pos`. When investigation B (or its successor) produces
an owner-approved canonical replacement level — healthy-only, rank-k or LI-5 banded — the switch
is one config value:
1. re-run `scripts/low_value_depth_disclosure_shadow.py` with that anchor added as a fourth set;
2. compare against §5.3;
3. bring the fire rates back to the owner.

The floor clamp `min(R_pos, S_pos)` stays unless the owner removes it. It is what makes the rule
robust to anchor revisions.

## 8. Test plan

| group | tests |
|---|---|
| Owner, unit | classification table (§2.2), incl. UNKNOWN for unpriced / quarantined / no-position / no-line; a pick at exactly `R_*` is not LVD; no optimal-lineup starter is ever LVD under the floor (property over the fixture board); the top piece is never in `E_i`; the guard; ties for top go to the lowest asset id |
| Owner, structure | AST: `depth_disclosure.py` defines no numeric threshold and calls `package_model` / `fairness_bands` only through the injected callables; no second band or utility |
| Invariance (the core promise) | flag ON vs OFF: every analyze, analyze-multi, finder, trade-history and public response is byte-identical **except** the new field; finder candidate order and scores identical; `rankDerivedValue` untouched (extends `tests/api/test_canonical_value_invariance.py`) |
| Locality / permutation | the per-team note depends only on that team's legs; permuting teams or assets yields an identical note (N ≤ 4 exhaustive, as spec I10) |
| Semantics | worked examples 1–6 on a fixture board (`tests/archive_fixtures.newest_complete_raw_payload()`), asserting the invariant (fires / does not fire), never live counts; monotonicity: removing received pieces never moves a team in its own favour (guards the NOT FAIR no-lean argument) |
| Public absence (recommended V4) | the public advisor's outbound model and every public response carry no depth field, enum or copy key (schema introspection + e2e body scan); the private owner is never imported by the public path |
| Public privacy (only if OD-4 adopts a public note) | `depthNote` is a `Literal` in the outbound model and `null` unless `result == "FAIR"` (direction test); copy strings are in `assert_advisor_payload_value_free`'s fixed tables; schema introspection finds no new numeric or free-text field; forbidden-word scan covers `public.depth.*`; no key in the advisor blocklist; e2e: no line or anchor value appears in RSC / `__NEXT_DATA__` / network bodies |
| Parity (only if OD-4 adopts a public note) | for the same ledger and snapshot, public `depthNote` ⇔ private `team_depth_disclosure(...).public_fair_only` (mirrors spec I11 for fairness) |
| Missing data | an unpriced piece gives `not_evaluated: unknown_piece`, never shown and never a zero; lines unavailable (no rosters / foreign-league contract) gives `lines_unavailable`, never the default league's lines |
| Frontend | renders outside the verdict badge; `role="note"`; `aria-expanded` on Learn more; the hide preference persists (private) and the page renders correctly without `localStorage` (public); the note component imports no valuation library (bundle check extends `check-public-bundle-privacy.mjs`) |
| Performance | ≤ 1 extra utility + band evaluation per team (≤ 4) plus a cached `DepthLines` per board generation; assert the analyze p95 does not move beyond noise |

**Engineering-reliability applicability:**

| priority | disposition |
|---|---|
| typed contract (Pydantic `Literal`, `extra="forbid"`) | APPLY_NOW |
| property tests (locality, monotonicity, invariance) | APPLY_NOW |
| privacy / adversarial contract tests | APPLY_NOW |
| package model and band owners | ALREADY_COVERED (reused) |
| scraping / replay | NOT_RELEVANT |
| production fire-rate counters | DEFERRED_BY_AUTHORITY (G3 below) |

## 9. Privacy review (public payload)

**Verdict: no public variant measured here meets the owner standard (§5: no replacement anchors,
gaps or formulas revealed). The recommendation is no public note (V4).** The review below is of
the FAIR-only public variant, kept as an owner option with its leaks stated plainly.

| check | result for the FAIR-only public variant |
|---|---|
| Numbers in the payload | none: one nullable enum, no float, no new integer key |
| Anchors, gaps, formulas in payload or copy | none written; the learn-more text describes the concept in words only |
| Anchors, gaps, formulas **inferable from when the note fires** | **yes: R2 reconstructs the replacement anchors; R1 bounds the gap** |
| Personalization / roster capacity / strategy | none. Team Context is off on the public path; the lines are league-wide aggregates (best unrostered by position, lowest starter across all twelve lineups); no manager's roster count, cap state, posture or needs enters the public trigger |
| Lean of a NOT FAIR result (M4) | not revealed: the note exists only on FAIR results |
| Direction *within* a FAIR result | **revealed** in many cases (R1) |
| Value-free ordering (M2) | unchanged; the note adds no ordering |
| Permutation / perspective invariance (M6) | holds by locality |

**Residual R1, within-FAIR direction and gap.** A FAIR result with a note implies "this team would
not be fair without its lower-value depth", i.e. `gap_i < ΔU(E_i) − t` (§3.1).
- When `ΔU(E_i) < t` (small extras in a large package) team `i` is **behind** within the FAIR
  band. In a 2-team trade a note on one row therefore says which side leads.
- In every case it is an upper bound on the team's gap, conveyed by when the note appears; the
  copy has no closeness wording, but that does not remove the information.

**Residual R2, replacement-anchor reconstruction.** This is the severe one, and it is not "a
single bit".
- Public FAIR / NOT FAIR results are visible, so a user can construct pairs of trades that are
  NOT FAIR without an asset X and FAIR with it (X added as the receiving team's extra piece next
  to a non-LVD top piece, which also satisfies the guard).
- On such a pair the note fires **if and only if X is low-value depth**. That is a per-asset
  oracle for "is `value(X) < min(R_pos, S_pos)`?".
- Iterating over assets of one position in public market-rank order (a binary search needs only
  a handful of probes) finds the boundary, to the resolution of that ordering: each position's
  cutoff `min(R_pos, S_pos)`, the league's replacement anchor or lowest-starter line, which the
  owner forbade revealing. For picks it reveals `R_*`.
- "Names no pieces" does not help: in a 1-for-2 the received extra is the only candidate.
- Rate limiting slows this; it does not prevent it.
- Rule C is the same oracle, more directly: in any k-for-(k+1) trade whose lowest received piece
  is X, it fires exactly when X is LVD, with no FAIR result needed. It is not a safe public
  alternative.

**OD-4.** No public note (V4), unless the owner explicitly accepts R1 and R2 as stated above.

## 10. Rollout plan and owner decisions

**Gates.** No gate is passed by this document.

| gate | content |
|---|---|
| G1 | owner approves the rule, threshold, picks, copy and visibility (this document) |
| G2 | implement the owner module and the private fields behind the private flag, default OFF (the public flag and field only if OD-4 accepts the leak); L0/L1 during coding, L2 at the PR; the invariance and privacy (or public-absence) suites are mandatory |
| G3 | shadow in production: the flag stays OFF for display while an aggregate-only counter records the would-fire rate per surface; no user-visible change. A short owner-chosen window |
| G4 | owner reviews the production fire rates against §5 and approves private activation |
| G5 | private flag ON (calculator + War Room first, then Trade Finder and Trade History if approved) |
| G6 | under the recommended V4: none (no public note). Only if the owner explicitly accepts R1 and R2 (the replacement-anchor leak included): public flag ON after the advisor launch gate (spec §6.3) passes |

**Owner decisions requested:**

| # | decision | recommendation |
|---|---|---|
| OD-1 | trigger rule | **A-guarded** (verdict dependence + guard); alternatives B (share ≥ 25%) and C (extra pieces) measured in §5 |
| OD-2 | interim piece threshold | **floor** `min(R_pos, S_pos)`: anchor-robust, never flags a starter; prereg is more sensitive but anchor-sensitive. Disclosure: the floor was introduced in this workstream after the prereg threshold's anchor sensitivity was seen; it was not preregistered (§5.3) |
| OD-3 | include picks (line `R_*`) | **yes**, on the strength of M2, which found the extra-piece discount strongest for picks (0.105 vs 0.174 for offense players at 1,000–2,499). Rule A's 100% on pick-class filler flips is **not** evidence: it is tautological, because `R_*` is the study's own pick filler line (§5.1) |
| OD-4 | any public note | **no public note (V4)**. The FAIR-only public variant leaks the replacement anchors (R2, a per-asset oracle) and within-FAIR direction (R1), which the owner standard forbids; it is available only if the owner explicitly accepts both leaks. Rule C is the same oracle and is not an alternative (§9) |
| OD-5 | default visibility | **V4** (§6): private shown by default with a per-user hide; no public note |
| OD-6 | exact copy | §4 as written |
| OD-7 | first surfaces | private calculator + War Room; Trade Finder and Trade History in a second step |
| OD-8 | replacement source when investigation B lands | re-run §5 with the approved level, then decide; keep the floor clamp |
| OD-9 | War Room Team-Context line (`private.depth.team_context`) | include, or hold until investigation A's forced-drop fix ships |
| OD-10 | the guard (`A_guarded` vs `A_dependence`) | keep: it removes notes on all-filler swaps; added after seeing the data, reported separately |

## 11. Limits

- **One board and one league** (`dynasty_main`, 2026-10-20). Every population is exploratory: the
  synthetic flip study, the S5a calculator sample, own-league trades on today's values, and 45
  War Room samples.
- **No 3–4-team market evidence.** Multi-team behaviour follows from locality, not from
  measurement.
- **Partly tautological sensitivity.** For rule A on the flip study's own filler, sensitivity is
  close to tautological under the prereg threshold, because the trigger asks the same
  counterfactual the study measures. The informative numbers are:
  - the false-alarm rates;
  - the starter-only control;
  - the realistic and own-league fire rates;
  - the anchor sensitivity.
- **Unvalidated against users.** Whether the copy helps managers is not measured. G3–G4 measure
  only how often the note would appear.
- **QB anchor.** The floor's only remaining anchor sensitivity is QB, where the current anchor is
  a player Sleeper lists as injured or inactive (§5.2).
- **Post-hoc threshold.** The floor was chosen in this workstream after the prereg threshold's
  anchor sensitivity was seen (§5.3). Its robustness is partly by construction.
- **Verdict re-implementation.** The shadow verdict uses the research utility and adjusted-total
  code, checked against the canonical dispatch on all 648,080 evaluations; the band read on the
  canonical whole-number adjusted gap differs on 58 of them, from rounding alone (§5).

## Completion result

- **STATUS:** DONE (design deliverable). Activation is out of scope.
- **ACCEPTANCE:**
  - 2–3 candidate rules, precisely defined, with the handling of picks, IDP, unpriced pieces and
    multi-team trades (§2–§3);
  - shadow fire rates with specificity and anchor sensitivity, and a recommended rule (§0, §5);
  - exact private and public copy, placement, accessibility and worked examples (§4);
  - an API sketch, test plan, privacy review and rollout (§7–§10).
- **EVIDENCE:**
  - `scripts/low_value_depth_disclosure_shadow.py` reproduces the committed flip-study counts
    exactly and agrees with the served asset-only lens on 180 / 180 War Room steps;
  - every one of its 648,080 incumbent evaluations matches the canonical `package_model`
    dispatch for `geom_q078_v1` (utility gap to float tolerance, adjusted totals within the
    canonical whole-number rounding);
  - output in `docs/trade/evidence/low_value_depth_disclosure_2026-10-20/disclosure_shadow.json`;
  - `bash scripts/format_python_changes.sh` is GREEN.
- **UNRESOLVED:**
  - owner decisions OD-1 to OD-10;
  - no implementation exists;
  - no production fire-rate evidence (G3);
  - no 3–4-team evidence;
  - the replacement level awaits investigation B.
- **BLOCKERS:** owner review (G1).
- **NEXT_ACTION:** owner review of §0, §4 and §10. On approval, implement G2 behind flags that
  default OFF.
