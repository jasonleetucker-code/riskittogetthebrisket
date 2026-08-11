# B1.2 — coordinate vs tail policy, and model-governance hardening

**Status: EVIDENCE + SAFETY INFRASTRUCTURE. Nothing promoted, nothing
applied, no production model constant changed, no live tail behaviour
changed.** The champion in `src/canonical/player_valuation.py` still equals
registry v2 exactly.

Generated 2026-08-11 on the same pinned inputs as B1/B1.1
(`data/dynasty_data_2026-08-10.json`, eight fit CSVs, hashes re-verified at
this HEAD). Reproduce with `b1_1_model_set_measure.py` and
`b1_2_tail_policy_measure.py`; machine-readable output in
`b1_1_model_set_report.json` and `b1_2_tail_policy_report.json`.

**B1 and B1.1 are preserved unchanged.** `B1_CHALLENGER_EVIDENCE.md` and
`B1_1_MODEL_SET_EVIDENCE.md` remain as the record of what was measured
then. This file supersedes one of B1.1's conclusions and says which.

---

## 1. The audit claim — CONFIRMED

**Claim.** B1.1's reference-universe experiment fitted each scope under
N=400/500/800, then passed the resulting `c` straight to a holdout
evaluator that builds its percentiles at the canonical N=500 — comparing
parameters expressed in one unit against a scale defined in another.

### Algebra

```
V(p) = 9999 / (1 + (p/c)^s),      p = (rank − 1) / (N − 1)

p/c  = (rank − 1) / ((N − 1)·c)

⇒ V  = 9999 / (1 + ((rank − 1) / M)^s),      M = c · (N − 1)
```

Rank-space behaviour depends on **(M, s)** and not on (c, N) separately.
Refitting the same observations under a different N rescales `c` and leaves
the curve alone. The transform between universes is
`c₂ = c₁ · (N₁ − 1) / (N₂ − 1)`.

### Code trace

| step | where | what happens |
|---|---|---|
| fit | `b1_1_model_set_measure.fit_master(..., reference_n=N)` | percentiles from `rank_to_percentile(i+1, reference_n=N)` → `c` in N units |
| score | `holdout.evaluate_offense_master(c, s)` | → `_percentile_pairs` → `training_percentiles(n)` with the **default** `reference_n = PERCENTILE_REFERENCE_N = 500` |
| result | | an N=800 `c` is evaluated as an N=500 `c` |

`evaluate_offense_master` is not defective — scoring in the serving
coordinate is right for its job. The defect was handing it foreign-unit
parameters.

### The measured fits are one curve in three units

| scope | N=400 | N=500 | N=800 | M spread |
|---|---|---|---|---|
| OFFENSE | c=0.0960 → M 38.304 | c=0.0770 → M 38.423 | c=0.0480 → M 38.352 | **0.31%** |
| GLOBAL | c=0.1120 → M 44.688 | c=0.0890 → M 44.411 | c=0.0560 → M 44.744 | **0.75%** |
| IDP | c=0.0480 → M 19.152 | c=0.0380 → M 18.962 | c=0.0240 → M 19.176 | **1.13%** |

The residual is the fitter's own grid (c step 0.005 refined ±0.002, s step
0.02). And `transform_c(0.0480, from_n=800, to_n=500) = 0.0769` against the
challenger's 0.0770 — **the N=800 fit IS the challenger.**

### RED → GREEN

RED, 7 failed in `tests/audit/test_b1_2_reference_universe_evaluation.py`.
Numerically, OFFENSE criteria for three coordinate-equivalent candidates:

| | N=400 | N=500 | N=800 | spread |
|---|---|---|---|---|
| **before** (raw `c` to the evaluator) | 933.19 | 671.21 | 502.12 | **85.8%** |
| **after** (transformed first) | 664.81 | 671.21 | 669.64 | **0.96%** |

GREEN: 37 tests across the two new files.

### What this retracts

> **B1.1 §3's claim that "refitting under N=800 scores 502.12 and
> independently recovers the curve the holdout prefers" is WITHDRAWN.** It
> measured units. The three universes recover the same curve and score the
> same. `MORE EVIDENCE REQUIRED` was B1.1's verdict for other reasons and
> is unaffected; this specific line of argument is not evidence.

### What survives untouched

The **unanimity sweep** varied `c` directly in the serving coordinate and
evaluated in that same coordinate, so it never mismatched. Its numbers
stand — see §4.

---

## 2. Reference N is a unit; the clamp is the model

Answering §82 directly.

**1. Is N substantively a model choice?** No. After correct transformation
it is a coordinate unit. Two `c` values under two N can be the same curve;
the same `c` under two N cannot be.

**2. What actually changes behaviour?** Where `p` saturates. A larger N
moves the saturation point, and *that* changes served values — not the
rescaling of `c`.

**3. Does clamping create the meaningful difference?** Yes, and it is the
only thing that does within the served range.

**4. Are N=500-continuous and transformed N=800 equivalent through the
served range?** **Proven equal, max |diff| exactly 0.0** at every sampled
rank through 800:

| rank | clamp N=500 | continuous N=500 | N=800 transformed | cont − deep |
|---|---|---|---|---|
| 100 | 2590.89 | 2590.89 | 2590.89 | 0.0000 |
| 400 | 692.77 | 692.77 | 692.77 | 0.0000 |
| 500 | 548.84 | 548.84 | 548.84 | 0.0000 |
| 600 | 548.84 | 452.68 | 452.68 | 0.0000 |
| 800 | 548.84 | 332.91 | 332.91 | 0.0000 |
| 900 | 548.84 | 293.26 | **332.91** | **−39.65** |

They part company only past 800, where the deeper universe clamps. So
"declare a bigger N" is precisely **"extrapolate, but stop at N₂"** — a
weaker statement than extrapolating, not a different mechanism.

**Top region untouched:** a pure tail change moves ranks 1..500 by
**0.0** across every scope and both curve sets. Measured, because if it
were not true the change would not be a tail policy.

**Structural note for any future repair:** the clamp is enforced in **two**
places — `rank_to_percentile`, and again inside `percentile_to_value` at
line 484. Both must move together or the second silently undoes the first.

---

## 3. The live clamp — what it destroys

On the real contract's `sourceRanks` (post-identity-join, observations that
actually vote):

| source | scope | clamped/obs | distinct ranks → one value | deepest | value at deepest |
|---|---|---|---|---|---|
| `idpTradeCalc` | IDP | 399/899 (44.4%) | **289** | 897 | 593.7 → 319.1 (**−46.3%**) |
| `draftSharksIdp` | IDP | 203/318 (63.8%) | **203** | 729 | 593.7 → 398.5 (−32.9%) |
| `idpShow` | IDP | 202/347 (58.2%) | **202** | 876 | 593.7 → 327.3 (−44.9%) |
| `draftSharks` | GLOBAL | 26/411 (6.3%) | 26 | 708 | 1697.6 → 1370.6 (−19.3%) |
| `dlfIdp` | IDP | 24/170 (14.1%) | 19 | 619 | 593.7 → 470.2 (−20.8%) |
| all others | — | **0** | — | — | — |

289 distinct ordinal positions in one source currently receive one
identical contribution.

### Board impact of clamp → continuous (champion curves)

| metric | value |
|---|---|
| rows changing value | 170 / 777 |
| rows reordered | 332 |
| mean \|rank shift\| | 8.16 |
| **median** | **0** |
| p90 | 28 |
| max | 96 |
| >5 / >10 / >25 / >50 | 216 / 164 / 84 / 44 |

By position — the effect lands exactly where the mechanism predicts:

| pos | rows | reordered | mean \|shift\| | max |
|---|---|---|---|---|
| **DB** | 79 | 49 | **18.85** | 88 |
| **DL** | 111 | 65 | **11.99** | 96 |
| **LB** | 78 | 39 | **11.97** | 83 |
| QB | 60 | 19 | 7.48 | 57 |
| WR | 158 | 64 | 6.83 | 68 |
| RB | 109 | 43 | 6.50 | 68 |
| TE | 79 | 23 | 1.96 | 49 |
| PICK | 103 | 30 | 1.86 | 52 |

**Median 0** — this is a surgical deep-tail change, not the board-wide
repricing a curve promotion is (challenger: mean 51.87).

### One result that must not be glossed

**A row can RISE.** Chris Jones (DL) goes 1204 → 1326 on *identical
sources and identical ranks*. Continuous `p` ≥ clamped `p` and V decreases
in p, so every per-source contribution fell or held. The rise comes from
the post-blend IDP stages — hierarchical anchor + α-shrinkage, and the
market-corridor clamp — which are **relative**.

Consequence: **board impact of a tail change cannot be predicted from
per-source deltas and must be measured.** Flagged for B2.

---

## 4. The `.068` candidate — validation status CORRECTED

B1.1 swept `c` at s=1.110 in the serving coordinate. That sweep is
methodologically sound and its numbers stand:

| region | c | criterion | every board better? |
|---|---|---|---|
| champion | 0.1100 | 1160.29 | — |
| unanimous band | 0.0680–0.1080 | best 579.69 at 0.0680 | yes |
| challenger | 0.0770 | 671.21 | yes |
| mean optimum | 0.0520 | 488.77 | no — PFKDynasty +326 |

**But the label was wrong.** Once the four holdout boards are used to
*select* c ≈ 0.068, they are no longer an untouched validation set for it.
They became a tuning set.

| candidate | how it was obtained | status |
|---|---|---|
| **c = 0.0770** (challenger) | fitted on six training boards, then scored on four boards it never saw | **externally validated** |
| **c ≈ 0.0680** | chosen *because those four boards said it was best* | **holdout-selected diagnostic candidate — NOT independently validated** |

Do not describe `.068` as validated, holdout-proven, or independently
superior. It is a candidate requiring fresh validation.

### §18 — is there a second validation layer? **No.**

Every value-publishing board in the corpus, classified:

| board | value column | role |
|---|---|---|
| ktc, dynastyDaddySf, dynastyNerdsSfTep, yahooBoone, fantasyProsFitzmaurice, draftSharksSf | yes | **training** |
| fantasyCalc, otcffbSf, pfkDynasty, fantasyNavigatorSf | yes | **current holdout** (already used to select `.068`) |
| `ktcSfTep` | yes | **sibling of a training source** — KeepTradeCut's own SF-TEP board, same market maker as `KTC`. ADR-008 already rules it out by name |
| `idpTradeCalc` | yes | GLOBAL/IDP scope, not offense |
| `fantasyProsIdp` | `normalizedValue` | **our own** hardcoded Hill applied to their ranks |
| dlfSf, dlfIdp, idpShow, flockFantasySf, fantasyProsSf, draftSharksRos* | rank / projection only | cannot score a value curve |

**No untouched validation set exists for `.068`.** Not manufactured.

### §53 — is a leakage-safe time split possible? **No.**

`exports/archive/` holds 140 dated bundles from 2026-07-14. Scanned all
140:

| archived source | present in |
|---|---|
| `site_raw/ktc.csv` | 140/140 |
| `site_raw/ktcSfTep.csv` | 140/140 |
| `site_raw/idpTradeCalc.csv` | 140/140 |
| **any of the four holdout boards** | **0/140** |

A curve cannot be evaluated on a historical holdout board that was never
stored. `data/raw_sources/` covers only 2026-04-17→20 and holds metadata
pointers, not values. The archived `dynasty_data_*.json` carries **our
blended** values plus synthetic rank encodings in `_canonicalSiteValues`,
not retail board values — reconstructing a "historical holdout" from those
would be inventing data, which §53 forbids.

**Time-split validation is blocked on data that was never captured.**
Capturing the four holdout CSVs into the archive from now on would make it
possible in future — a cheap change, and the only route to validating
`.068` or anything else selected against the current holdout.

---

## 5. `FIT_TOP_N` depth — a separate question, measured separately

Coordinate held fixed at the canonical reference; only training depth
moves.

| scope | depth | c | s | M | holdout |
|---|---|---|---|---|---|
| OFFENSE | 400 | 0.0770 | 1.1100 | 38.423 | 671.21 |
| OFFENSE | 500 | 0.0770 | 1.1250 | **38.423** | **660.19** |
| GLOBAL | 400 | 0.0890 | 0.7200 | 44.411 | — |
| GLOBAL | 500 | 0.0910 | 0.7600 | 45.409 | — |
| GLOBAL | 800 | 0.0950 | 0.8250 | 47.405 | — |
| GLOBAL | 900 | 0.0950 | 0.8450 | 47.405 | — |

* **OFFENSE: M does not move at all** (38.423 → 38.423) when ranks 401–500
  are added; only `s` shifts 1.110 → 1.125, and the holdout improves 11
  points. Discarding KTC's ranks 401–500 costs very little.
* **GLOBAL: M moves +6.74%** across 400 → 800 and saturates by 800. GLOBAL
  *does* respond to depth — but it has no holdout, so "responds" is not
  "improves", and this is sensitivity evidence only.
* **IDP: skipped, correctly.** Its deepest value source is the 370-row
  IDPTC slice; there are no ranks 401+ to add, so the experiment would vary
  nothing. `FIT_TOP_N` is not what limits IDP.

No `FIT_TOP_N` change is proposed. Deeper ≠ better is not assumed in either
direction.

---

## 6. Governance repairs — RED → GREEN

All on temporary registries. `config/model_registry/` is unchanged.

### 6.1 An unreadable registry is not an absent one — **the most serious find**

`load_or_seed_registry` wrapped `ModelRegistry.load()` in a bare
`except RegistryError` and answered by seeding a fresh v1 champion and
calling `save()`. `load()` raises that error for a missing file — the
intended trigger — but **also** for any structural failure of a file that
exists. The two were indistinguishable, so a registry that merely failed
validation was replaced by a one-version seed, taking every recorded
promotion, rejection and rollback with it.

**It fired during this session.** An experimental `measuredAt` guard made
`load()` raise; inside one test run the real three-version registry became
a seeded single-version one — `championVersion` 2 → 1, versions [1,2,3] →
[1] — and had to be restored from git.

Fix: seed only when the path does not exist; an existing file that will not
load raises. RED verified by stashing the fix.

**Third instance of `ARCHITECTURE_HANDOFF` invariant 6** — "tools must not
destroy the evidence they maintain" — after the two closure-harness defects
in Phase A. That invariant's note says to assume a third exists. It did.

### 6.2 Scheduled refit now pins its snapshot

`RISKIT_FIT_SNAPSHOT` appeared nowhere under `.github/`, so
`_latest_snapshot()` selected by **mtime** and the IDP and ROOKIE scopes
trained against a board the run neither chose nor recorded. The workflow
gained a step that resolves the snapshot once, hashes it, exports the pin
and surfaces `path` + `sha256` as step outputs. The fitter already treats a
missing pin target as fatal, so a snapshot deleted mid-run fails the run.

### 6.3 Input fingerprinting: 6 → 9, derived not mirrored

`training_input_paths()` returned the six OFFENSE CSVs while versions
record eight constants across four scopes. Now derived from the fitter's
own tables and deduped by resolved path:

```
KTC, DynastyDaddy, DynastyNerds, Fitzmaurice, YahooBoone, DraftSharks,
GLOBAL:IDPTradeCalc, IDP:DraftSharks-IDP, boardSnapshot
```

Derivation rather than a hand-written mirror is deliberate — the B1 pin
instrument had exactly this defect and named three of six OFFENSE sources
within a day of being written.

### 6.4 `appliedAt` and `measuredAt`

* **`appliedAt` did not exist** — not "was null". ADR-008 split promote
  from apply so a human performs the second step, and the schema recorded
  only the first, so the registry could not answer "are the live constants
  the champion?" Added to `ModelVersion` with round-trip, plus the sentinel
  `UNKNOWN_HISTORICAL_APPLY_TIME` for state that is genuinely
  unreconstructable. **No date was fabricated.**
* **`measuredAt` was already emitted** by `HoldoutResult.to_dict()` since
  `705cdc03e` (2026-08-05); all three stored versions predate it, so the
  nulls are a **historical gap, not a live defect** — a correction to the
  previous checkpoint, which framed it as a lifecycle failure. Added a
  guard on the **write path only**: enforcing it in `__post_init__` made
  the shipped registry unloadable, which is rewriting history rather than
  annotating it.

### 6.5 Scope-specific validation — the gate

`src/model_registry/scope_validation.py`. States:
`VALIDATED_EXTERNAL_HOLDOUT`, `VALIDATED_CROSS_VALIDATION_ONLY`,
`UNVALIDATED_NO_HOLDOUT`, `UNCHANGED_FROM_CHAMPION`, `NOT_ROUTED`,
`OVERRIDDEN_BY_OWNER`.

`assert_promotable` fails closed on any **changed, routed** scope without
its own evidence. Cross-validation is deliberately **not** promotable —
resampling shows a fit is stable, not that it generalizes, and collapsing
those is the evidence laundering §43 prohibits. An owner override exists,
because a permanently unpromotable model is its own failure mode, and it
requires a non-empty reason.

Kept out of `decide_promotion`: that function compares two criteria and is
correct at it; fusing them would make a two-scalar comparison secretly
depend on eight floats.

**This is not hypothetical protection.** The v1 → v2 promotion moved GLOBAL
0.113/0.87 → 0.112/0.725 (14% slope) and IDP 0.093/0.97 → 0.083/1.11 with
zero out-of-sample evidence. Under this gate that promotion would have
required an explicit, recorded override.

### 6.6 Unanimity — NOT implemented, by design

§44 required proving unanimity is the intended binding rule before
codifying it. **It is not.** ADR-008's Decision clause specifies a *mean*
per-source RMSE and a 25-point margin derived from a measured noise floor.
The only unanimity language is descriptive: v2's promotion note observes it
happened, and the margin derivation cites "zero sign flips in 29
consecutive pairs" as evidence the **paired delta** is stable — a noise
statement, not a gate. Codifying it would be inventing policy.

Left as an **owner decision**. The current rule is now asserted by test so
a future change has to be deliberate rather than arriving as an
undocumented tightening.

---

## 7. What is settled, and what is not

**Settled here:**

* reference N is a unit; B1.1's alt-N result was a units error (§1)
* the clamp is the substantive tail choice, and "bigger N" is bounded
  extrapolation (§2)
* the clamp collapses 289 distinct ranks in one source; board effect is
  surgical, IDP-shaped, and non-monotone through the blend (§3)
* `.068` is holdout-*selected*, not validated; no second validation layer
  and no time split exist in the corpus (§4)
* `FIT_TOP_N` barely matters for OFFENSE, matters for GLOBAL, is irrelevant
  for IDP (§5)
* five governance defects repaired, one of them actively destructive (§6)

**Not settled, and not settleable without new inputs:**

* an external holdout for GLOBAL and IDP
* independent validation of `.068`, or of anything else selected against
  the current holdout — blocked until the four holdout CSVs are archived
* whether continuous extrapolation is *correct* for deep IDP, as opposed
  to merely more differentiated than a clamp. Nothing here measures deep
  IDP values against reality, because nothing in the corpus can.

---

## 8. Ownership hand-off to B2

Findings that belong to B2, not to a Hill promotion:

1. **IDP master methodology** — two sources disagreeing ~6× at rank 400,
   one voting on 29% coverage across the full grid.
2. **Equal weighting of a shallow source** — `_fit_scope_master` averages
   per-source curves that are extrapolated to p≈0.995 regardless of
   observed depth.
3. **Deep-rank handling** — the tail policy itself, now measured but not
   decided.
4. **Post-blend IDP stages** — anchor/α-shrinkage/corridor make board
   impact non-monotone in per-source value (§3).
5. **Effective coverage** — `OVERALL_RANK_LIMIT = 800` publishes 300 ranks
   deeper than the coordinate resolves.
6. **OFFENSE source mix** — dropping KTC improves the holdout by 95 points
   (B1.1 §H). Source-mix *sensitivity* evidence only; no weight change is
   proposed and none was made.
