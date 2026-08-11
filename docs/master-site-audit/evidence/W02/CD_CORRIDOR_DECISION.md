# Corridor dependency pass — decision

> **CORRECTED 2026-08-11.** §6 claimed the platform does not retain the
> inputs needed to characterise board-over-board behaviour. That was drawn
> from the export bundle alone and is **wrong** — git history retains all
> 24 per-source CSVs at every refresh, and **17 fully usable independent
> days** exist right now. See **§6a**, which supersedes it. §6 is kept
> verbatim rather than edited away: the shape of the error (concluding
> absence from an incomplete view) is the useful part.

## Recommendation — FINAL

**CORRIDOR DEPENDENCY RESOLVED — RETURN TO B4.**

The market corridor is **removed** and replaced by a structural
blend-integrity detector that flags and abstains rather than coerces.
#794, #795 and #796 are resolved by removal of the mechanism that made
them live, not by tuning it.

Sections 1-6a below are the research record that led here and are left as
written, including their superseded parts. §7a is the final selection.

## 7a. FINAL SELECTION AND IMPLEMENTATION

**Chosen: B + D — remove the value coercion, add a hull integrity
detector in ABSTAIN form.** Neither C (hull-clamp) nor E's enforcing
change-point was taken, and A was never the presumptive winner.

### Why not clamp (§5's question, answered)

A value outside its own contribution hull is impossible under correct
operation. Coercing it to the nearest boundary would convert pipeline
corruption into a clean, plausible number and destroy the only evidence
that anything was wrong. The row is stamped and left alone.

### What "abstain" means operationally (corrected 2026-08-11)

The first implementation stamped `blendIntegrityViolation`, set
`valueAltered: false`, and let the row continue through the pipeline
unchanged. **That is diagnostics, not abstention** — the value was proven
structurally impossible and every downstream consumer still read it as an
ordinary canonical number, because `blendIntegrityViolation` is a key
nothing consults.

Fixed by routing through the two fail-closed mechanisms the platform
already has, rather than inventing a third:

| level | mechanism (pre-existing) | effect |
|---|---|---|
| row | `anomalyFlags` → `_QUARANTINE_FLAGS` → `quarantined` | Consensus Edge returns `WITHHELD`; BDVM skips the row; /edge drops it; `confidenceBucket` degrades to `low`; mirrored to the legacy dict |
| build | `validate_api_data_contract` **error** | `scripts/validate_api_contract.py` (the "API data contract check" CI step) exits non-zero; `contractHealth.ok` stamped `False` |

Two deliberate boundaries:

* **Error, not warning, not `degraded`.** The CI gate keys on `ok` and
  ignores warnings entirely, so anything softer is a note nobody acts on.
* **It does not stop a running server publishing the generation.** That
  path already publishes `invalid` contracts; changing it is a far larger
  blast radius than this finding, and was not in scope.

The build-level scan covers the **whole** `playersArray`, not the
`[:1000]` prefix the per-row shape checks use — the board is ~1,094 rows
and the retired corridor did its work at ranks 691-740, so a prefix scan
would miss violations precisely where they are most likely.

### Placement, stated accurately

The detector runs after the blend and count-aware aggregation and
**before** the two-way-player boost and the Phase 5 pick passes. A source
comment previously claimed it ran "after all value-moving passes", which
was false.

The placement follows from what the invariant means — a *blend* cannot
leave the range of the contributions it was blended from, while those
later stages are overrides computing from a different population — and
**not** from a measured false-positive rate. Measured on the live board
both placements flag zero rows: Travis Hunter's boosted 4758 sits inside
his own (2538, 5637) hull, and every ranked pick carrying two
contributions sits inside its hull. Recorded that way rather than
claiming the later placement "would" misfire, which the evidence does not
show.

### What decided it — the upstream audit (§3)

The decisive measurement, and it corrected my own earlier synthetic
battery. Anomalies injected at the **source CSVs** with the whole
pipeline rebuilt:

| failure | upstream defense | caught? | blend effect | old corridor | hull |
|---|---|---|---|---|---|
| one source ×5 | Hampel + count-aware blend | absorbed | ≤1.7% | **0/6** | 0/6 |
| one source ×20 | Hampel (3/6) + blend | absorbed | ≤1.7% | **0/6** | 0/6 |
| anchor ×5 | declared-range check (D-1) | **fully** | **0.0%** | **0/6** | 0/6 |
| correlated ×3 | Hampel (2/6), partial | **no** | med 5.7%, max 48% | **0/6** | 0/6 |
| correlated ×4 | Hampel (3/6), partial | **no** | med 5.7%, max 48% | **0/6** | 0/6 |

**The corridor fired on 0 of 6 victims in every scenario.** The
protection lost by removing it measures as zero. The earlier battery made
it look useful only because it perturbed the post-blend value directly,
bypassing every upstream layer.

**Remaining uncovered risk, named not hidden:** correlated multi-source
anomalies, up to 48% blend movement, caught by neither mechanism. Sources
agreeing on something wrong is indistinguishable from disagreement at the
blend, and no independent IDP reference exists to arbitrate — every
IDP-covering source votes. This gap is pre-existing; removal does not
create it.

**Tracked as [#804](https://github.com/jasonleetucker-code/riskittogetthebrisket/issues/804)**
— correlated-source / shared-lineage anomaly protection. Filed so the gap
outlives this PR rather than living only in a decision doc. It does not
reopen #794/#795/#796, does not justify restoring the corridor (which
fired 0/6 in exactly these scenarios), and must not be closed by
inventing source weights ahead of a measurement of which sources actually
move together.

### Board impact (§6)

| | current board | 17 historical days |
|---|---|---|
| values changed | **32** | 544 total |
| max abs change | 148 | 550 |
| offense affected | **0** | **0** |
| picks affected | **0** | 5 |
| top 50 / 100 / 200 changed | **0 / 0 / 0** | — |
| IDP top 50 / 100 / 200 changed | **0 / 0 / 0** | — |

All 32 are IDP, ranks 691-740, carrying 2-4 sources. Largest: Will
Johnson +148, Ji'Ayir Brown +116, DJ Wonnum +109. The corridor's entire
live effect was pushing thin-coverage deep-tail IDP rows *down* toward
`idpTradeCalc`.

### B4 coupling (§9)

On the implemented replacement: **0 integrity violations under both
`TAIL_SATURATION_RANK = None` and `= 903`**. The detector is silent on a
healthy board under either tail, so the B4 repair and this change do not
interact. 903 remains inactive.

### Change-point monitor (§10)

**Deferred — diagnostic only, not implemented.** 1 alarm in 9 healthy
holdout days is not an enforcement-grade false-positive rate, and the
instruction was not to force it into the value path for complementarity.
The fabricated reference is permanently retired.

### Confidence buckets (§11)

**Not recreated.** The detector has no confidence dependency at all, and
a test pins that bucket value cannot change enforcement.

### Limitation that travels with this (§14)

Historical healthy-board validation spans **17 independent offseason
days**, not an in-season NFL market regime. It is not hidden and it did
not block implementation, because the rule is a structural pipeline
invariant rather than a market-behaviour model: it asks whether a blend
fell outside its own inputs, which does not depend on NFL outcomes.

**Telemetry for the in-season check**: `blendIntegrityViolation` is
stamped on the row and mirrored to the legacy dict, so in-season
behaviour can be evaluated from ordinary boards without another
retrospective data-recovery exercise.

## Recommendation

**MORE CORRIDOR EVIDENCE REQUIRED** — but for a narrower reason than §6
gave, and *not* for want of available history. See §6a: what remains is
one market regime and an unwritten repair, not a collection wait.

The *diagnosis* is complete and decisive: **the market corridor in its
current form is not a defensible canonical safety mechanism**, and the
reasons are structural rather than tuning failures. What is not
established is the *replacement*, and the gap is specific and nameable —
see §6. Recommending a production swap on the evidence I have would mean
replacing a measured-bad mechanism with an insufficiently-measured one.

No production behaviour changed in this pass. `TAIL_SATURATION_RANK`
remains `None`; the 903 policy was enabled experimentally and restored.

## Pin

New pin on integrated `main` `8639e79f4` (board
`dynasty_data_2026-08-11.json`, 24 CSVs, champion registry v2). The B4
pin is historical and was neither reused nor overwritten; this pass
writes only to `cd_*` paths.

## 1. Anchor independence (#794) — no independent anchor exists

**Every member of every anchor chain votes in the blend it later
anchors.** IDP chain: `idpTradeCalc`, `dlfIdp`, `idpShow`,
`fantasyProsIdp` — four voters. The stage-3 median fallback is a median
*over that same chain*, so it is a second statistic of the same voters,
not an independent one.

All 32 clamps on this pin anchor on `idpTradeCalc`, which votes on all 32.

The incremental second influence, stated two ways because they differ in
size and both are true:

* **Structurally it is total.** A clamped value is `anchor × (1 ± band)`
  — a pure function of the anchor. The anchor's share of the row goes
  from a median **1/3** in the blend to **1.0** after the clamp.
* **Numerically it is currently modest.** The clamp moves the value a
  median 2.0% (max 10.7%), because the band is wide. Its first influence
  through the blend is a median 20.8%.

**A genuinely independent anchor is not constructible from this tree.**
Exactly one loaded source does not vote — `ktc` — and it is offense-only,
while the corridor clamps IDP only. Every source covering IDP votes.
Candidate family 4 is therefore reported as *not constructible* rather
than quietly dropped; it would require a new data source, which is out of
scope.

## 2. Band independence (#795) — a P90 cannot detect systemic drift

Not a calibration problem. A percentile threshold cuts the worst 10% of
**whatever distribution it is handed**, healthy or catastrophic.

Scaling every IDP blended value by `f` with anchors untouched — a
whole-board calibration failure, precisely what a rail exists for:

| f | band | fires | rate | same rows as f=1 |
|---|---|---|---|---|
| 1.0 | 0.6201 | 32 | 9.7% | — |
| 1.3 | 1.1061 | 32 | 9.7% | yes |
| 3.0 | 3.8602 | 32 | 9.7% | yes |
| 10.0 | 15.2005 | 32 | 9.7% | yes |

A **10× board-wide error is invisible**: identical rows, identical rate,
band scaled to match the defect.

From the other side — inflate a fraction `q` of rows 3×:

| q | broken | caught | detection |
|---|---|---|---|
| 2% | 6 | 6 | 100% |
| 10% | 32 | 32 | 100% |
| 20% | 65 | 33 | 50.8% |
| 80% | 263 | 33 | 12.5% |

The rail's capacity is fixed at ~33 rows however much is broken.

**So the current band is a fixed-rate outlier trimmer, not a
catastrophic-error rail.** It detects the class of problem it is least
needed for and is structurally blind to the class it was justified by.

## 3. Confidence dependency (#796) — the bands are ordered incoherently

| bucket | n | band | median drift |
|---|---|---|---|
| high | 36 | 0.6504 | 0.2071 |
| low | 174 | 0.6316 | 0.1951 |
| medium | 119 | 0.5183 | 0.0980 |

**HIGH confidence is permitted MORE disagreement than MEDIUM**, and
high-confidence rows drift further from the anchor than medium ones. That
is not a defensible basis for separate bands. Total spread is 0.1321, so
the dependency is also doing little work for the complexity it carries.

The recommendation is **abstention, not tuning**: any replacement should
decline to confidence-grade until the bucket methodology is independently
validated. No bucket constant was touched in this pass.

## 4. Necessity (Q4) — the stated purpose predeceased the mechanism

`_apply_market_corridor_clamp`'s docstring justifies it as containing
"the IDP calibration post-pass's 3-4× DB-bucket multipliers". **That
post-pass no longer exists** — it was retired, and neither the function
nor its config file is in the tree. The corridor is now justified by a
mechanism it outlived.

Separately: the corridor runs *after* `canonicalConsensusRank` is
stamped, so it rewrites values and never reorders. **A clamped row keeps
the rank its unclamped value earned**, so its published value and
published rank come from different stages.

## 5. Candidate families, measured

Seven scenarios × nine families, on identical pinned inputs. Full tables
in `cd_corridor_candidates.txt` / `.json`.

Headline — detection vs false intervention:

| candidate | false-int (healthy) | whole-board drift | routing failure | stability |
|---|---|---|---|---|
| 1 current | **8.9%** | **8.9%** | **6.7%** | 0.751 |
| 2 leave-one-out anchor | 9.8% | 10.0% | 38.2% | 0.775 |
| 3 multi-source anchor | **52.9%** | 53.2% | 65.2% | 0.990 |
| 4 external anchor | *not constructible* | — | — | — |
| 5 historical band | 8.9% | 47.4% | 4.5% | 0.734 |
| 6 change-point | 0.0% | **100%** | 0.0% | 1.000 |
| 7 hull invariant | **0.0%** | 93.3% | **97.8%** | 1.000 |
| 8 hull + ABSTAIN | **0.0%** | 93.3% | **97.8%** | 1.000 |
| 9 none | 0.0% | 0.0% | 0.0% | 1.000 |

Readings:

* **Current is worse than absent on routing failure**: it intervenes on
  9.6% of healthy rows while catching 6.7% of broken ones.
* **Candidate 3 is disqualified** — 52.9% false intervention.
* **Candidate 2 fails where it matters most**: excluding the anchor makes
  an *anchor* fault invisible (11.8% detection).
* **The hull invariant is the mirror image of current.** "A blend cannot
  fall outside the range of its own inputs" is violated only by a
  pipeline/routing/calibration fault, never by disagreement however
  violent — which is exactly the distinction the corridor's stated
  purpose needs and its current form cannot make. It correctly scores 0%
  on single-source anomalies: one source being weird *is* disagreement.
* **Change-point** catches whole-board drift perfectly and nothing else.
  It is complementary to the hull, not a substitute.

Two corrections I made to my own harness, recorded because they changed
conclusions:

* the first `normal_disagreement` scenario perturbed the *blend*
  independently of its inputs, which violates the hull invariant **by
  construction** and scored the hull at 15.9% false intervention. Real
  disagreement moves the sources and the blend follows. Corrected, it is
  **1.9%**. The same bug inflated the stability probe.
* candidate D-style "per-source ceiling" is not a distinct candidate at
  all — it prices every rank identically to a shared ceiling and only
  moves where saturation begins.

The **2% hull tolerance does no policy work**: on the live board the
invariant holds with **0 violations at every tolerance from 0% to 10%**.

## 6a. CORRECTION — the historical replay (supersedes §6)

**W02-F018 verdict: A. HISTORICAL GIT REPLAY AVAILABLE.** No collection
wait is required. §6 below is retained as withdrawn reasoning.

`cd_historical_replay.py` replays **current code against historical
inputs** — never historical code, so methodology drift cannot be confused
with data drift. Four input classes are redirected and a leak guard makes
any current-tree market read or network access a hard failure; 17 of 17
replays passed it.

| | |
|---|---|
| refresh commits scanned | 1,099 over 140 days |
| **usable days** | **17** (2026-07-26 → 2026-08-11) |
| partial days | 123 — sources that did not yet exist |
| unusable | 0 |
| transitions with zero source change | **0 of 16** (7-15 of 22 sources change daily) |

Measured over 17 independent days / **5,931 IDP rows**:

| candidate | result on real independent boards |
|---|---|
| current corridor | trigger 8.7-9.2%, pinned near 10% on every board; **anchor also votes on 539 of 539 clamped rows (100%)**; `idpTradeCalc` anchors all 539, fallback chain never fires |
| **hull invariant** | **0 violations at every tolerance from 0.000% to 10%** |
| change-point | reference from a chronological TRAIN split (8 days), scored on a later HOLDOUT (9 days); 1 alarm in 9 |

Under the B4 tail (903) the ordering is unchanged: hull 0 violations
across 5,491 rows, corridor 8.2-9.1% with the anchor voting on 471 of 471.

So #794 and #795 are now confirmed on genuinely independent history
rather than on one board, and the hull's zero false-positive rate is
established on the evidence the earlier archive test only appeared to
provide.

**What still blocks implementation**, stated narrowly:

* **One regime.** All 17 days are late-July to mid-August, with no live
  NFL games. Hull's 0% false-positive rate is measured only there. That
  bounds generalisation — it does not bound availability, which is what
  W02-F018 was about.
* **The repair is not written.** Replacing a live post-blend safety
  mechanism changes served values on ~32 rows per board, and that is a
  production change this pass did not make.

The fabricated `HISTORICAL_BAND x 0.35` is retired: the change-point
candidate now takes a reference measured from real history or abstains.

## 6. Why this is not yet a recommendation to implement — WITHDRAWN, see §6a

Two gaps, both specific.

**(a) The replacement's false-positive rate rests on one board.** I
extended the hull test across 14 archived exports and got 0 violations in
5,027 IDP rows — then checked what those archives actually contain.
**The export bundle carries only 2 of the 21 voting sources' CSVs**
(`idpTradeCalc`, `ktcSfTep`); the pipeline reads the other 19 from the
working tree. So those 14 "historical boards" share ~90% of their inputs
with today's, and the near-identical outputs (359 rows, band 0.6201 on
nearly every one) are that contamination, not stability. **I withdraw
that test as evidence of cross-board behaviour.** It remains valid only
as what it is: one board, measured exactly.

**(b) Candidate 6's reference distribution was fabricated.** My
change-point implementation derives its reference median as
`HISTORICAL_BAND × 0.35` — a constant I invented because no stored
historical drift distribution exists. That is precisely the hand-set
constant this pass was told not to introduce. Its 100%/0% scores are
therefore indicative of the *shape* of a change-point rail, not evidence
for a specific one.

Both gaps have the same root: **the platform does not retain the inputs
needed to characterise a board-over-board distribution.** That is the
concrete unblocking work, and it is cheap: archive all 21 voting-source
CSVs in the export bundle (today: 2), or persist a per-build drift
summary. After ~2 weeks of genuinely independent boards, the hull's
false-positive rate and a real reference distribution can both be
measured, and this pass can conclude.

## 7. B4 coupling — the conclusion is robust to the tail repair

The whole battery was re-run with `TAIL_SATURATION_RANK = 903` enabled
experimentally (327 eligible rows vs 359; reference band 0.3834 vs
0.6201). The ordering is unchanged:

| candidate | false-int @903 | drift @903 | routing @903 |
|---|---|---|---|
| 1 current | 8.3% | 8.3% | 27.2% |
| 7/8 hull | **0.0%** | 91.7% | 92.6% |
| 6 change-point | 0.0% | **100%** | 0.0% |

So the corridor's defects are not artefacts of the saturated board, and
the replacement direction does not change under the value distribution
B4 intends to ship. 903 was restored to `None` after measurement.

## 8. What must NOT be concluded from this

* Not "remove `idpTradeCalc` from the blend" — explicitly out of scope
  and not required by any finding here.
* Not "restore the 0.15 cap" — the removed cap is not the problem; the
  self-derived band is.
* Not "the corridor caught nothing useful" — it does catch single-source
  and correlated anomalies at 70-82%. The objection is that it pays ~9%
  false intervention for that and is blind to the systemic failures it
  was justified by.
* Not a change to W02-F003. B3's repair is not reopened.

## 9. State of the three tracked items

| item | status after this pass |
|---|---|
| #794 anchor/voter circularity | **CONFIRMED, and stronger than stated** — no independent anchor is constructible without a new source |
| #795 self-derived band | **CONFIRMED as a tautology**, not a tuning defect |
| #796 confidence buckets | **CONFIRMED incoherent** (high band > medium band); recommendation is abstention, not tuning |

W30-F023 stays **BLOCKED**. B4 cannot return for closure until a corridor
methodology is settled, and settling it needs the retained inputs in §6.
