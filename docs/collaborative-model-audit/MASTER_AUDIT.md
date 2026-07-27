# Collaborative model audit — master record

**Started:** 2026-07-27 · **Branch:** `claude/fantasy-football-audit-53l3g7`
**Base:** `a6edd364` (`origin/main` at session start)

An external reviewer supplied a large audit (findings A–S) covering the ROS utility
model, roster intelligence, TE scarcity, trade engines, source independence, storage and
security, explicitly framed as **hypotheses to verify, not directives**. This directory
is the durable record of what survived verification.

## Companion files

| file | contents |
|---|---|
| `CLAIM_REGISTRY.md` | every material claim, its classification, and the evidence |
| `FORMULA_REGISTRY.md` | old → new for every formula or constant that changed |
| `EXPERIMENT_LOG.md` | experiments run, including the ones that failed |
| `IMPLEMENTATION_STATUS.md` | what landed, what was deferred, what was rejected |
| `results/` | reproducible artifacts (before/after snapshots, migration write-up) |

## The headline

**The prompt's own framing was stale.** It assumed a fan-out of unmerged branches
carrying the findings. In fact `origin/main` == `HEAD` == `a6edd364`, exactly one
unrelated PR was open (#583, a rebrand), and PRs #553–#582 had all merged — several of
which already fixed findings the audit raised as open.

Adjudication of ~15 material claims:

| outcome | count | which |
|---|---|---|
| **confirmed** | 7 | A (rosValue units), E (surplus), K (finder value path), N (mixed markets), J (fit-score range), P (source families), Q (no persisted actuals), S (security) |
| **already fixed / already handled** | 3 | C (tier ladder), D (strength vs dependency), I (unidentifiability) |
| **dead code** | 2 | G (`lineupScarcity`), and the whole LI-7 league-adjustment apparatus |
| **partially confirmed** | 1 | L (negative delta — latent, filtered before output) |
| **disputed with my own sub-reviewer** | 1 | O (KTC VA on `rankDerivedValue`) |
| **raised independently, not in the prompt** | 2 | nflverse 2025 URL is stale; conftest contradicts the code it isolates |

## Three things worth carrying forward

**1. A refuted finding is a deliverable.** C, D, G and I were raised as defects and are
not. Each is recorded with the evidence that closed it, so the next reviewer does not
spend a day re-deriving that the tier ladder was fixed before `4f9cb05b` merged.

**2. Verify the reviewer, not just the code.** Finding O was reported to me as a
significant defect — KTC's scale-sensitive VA (`t = 10041`) applied to
`rankDerivedValue`. The call sites are real. But that board tops out at 9999 against
KTC's 10000/10041 — the endpoints are 0.4% apart, so the formula behaves almost
identically on either. Downgraded to a documentation note. Writing a comment beats
"fixing" a formula whose inputs are within half a percent of what it was built for.

**3. The measurement changed the answer twice.**

* On TE: the plan was to replace the flat 1.15 with a measured curve. Measuring first
  showed 1.15 sits *below the entire observed range* of KTC's own TE++ uplift
  (1.209–2.053) — it under-corrects for every tight end, which is the opposite of the
  "over-correction" the prior documentation worried about.

**4. And one of my own conclusions had to be retracted mid-flight.** I measured the
league's TE demand from *scoring keys* — found `bonus_rec_te = 0.0` with every TE key
matched by its WR/RB equivalent — and concluded the premium was "exactly 1.000", implying
TE values should come DOWN. The league starts **two mandatory tight ends**. Structural
demand is demand whether or not a scoring key rewards it, and I had confused the
mechanism with the thing itself. Corrected: the target basis is TE++, the live direction
was right, and the correction moves TE values **up**.

The failure mode is worth naming because it is the one this audit kept finding in other
people's work: a number that is *correct about what it measures* and wrong about what it
is taken to mean. `measure_league_te_premium` returned an accurate scoring measurement
under a name that claimed more. It now returns a target *basis* instead of a multiplier,
so the same mistake cannot be made numerically — a basis cannot be multiplied into
anything.
* On F-6: the doc predicted the migration "moves every number the endpoint emits". It
  moved the levels slightly and the ordering barely at all — the top recommendation was
  unchanged for 0 of 12 teams, because the dominant score term is a ratio and a
  near-uniform rescale cancels.

Neither of those is what anyone expected going in, including me.

## Standing limitations

* No ground truth exists for dynasty asset value. Nothing here makes any value
  "correct"; it makes the paths coherent and the labels honest.
* ρ = 0.9626 between the two finder value paths is **not** independent corroboration —
  both descend from the same scrape.
* KTC's TE++ curve is measured *within* KTC's board. Applying it to another publisher
  assumes their TEs sit at a comparable base. Better founded than 1.15, still an
  assumption.
* The system cannot backtest its own value changes: no player-week actuals are
  persisted (finding Q). That is the root cause of `PROJECTION_CORROBORATED` being an
  unreachable evidence tier, and it bounds what any of this work can claim.
