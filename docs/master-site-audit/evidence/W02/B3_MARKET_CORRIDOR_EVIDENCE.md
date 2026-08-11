# B3 — W02-F003: the IDP market corridor

**Phase**: B3 (authorized 2026-08-11, after PR #787 merged)
**Scope**: W02-F003 only.
**Not done, and not authorized**: no `promote`/`apply`, no Hill champion
constant change, no `PERCENTILE_REFERENCE_N` change, no W30-F023 tail-clamp
work, no source-weight change, no adaptive weighting, no B4. The B2
coordinate-pool architecture is untouched.

---

## 1. The B3 pin

B2 was integrated first (PR #787 merged as `2449af9ac`) and the branch
re-cut from it, so this is not another measurement on the stale B2
baseline.

| item | value |
|---|---|
| code | `2449af9ac` |
| board | `exports/latest/dynasty_data_2026-08-11.json` |
| board sha256₁₆ | `8fb6ede274171aee` (834,861 B) |
| scraped | 2026-08-11T11:32:57Z |
| source CSVs | 24, all hashed |
| champion model | registry v2 — GLOBAL 0.1120/0.725, OFFENSE 0.1100/1.110, IDP 0.0830/1.110, ROOKIE 0.1530/0.885 |

**This is a different board from B2's** (`a495c049fa69f141`). The B2
numbers remain attached to the B2 pin; nothing was recomputed across the
data refresh and presented as the same experiment. Every candidate below
was measured on this one pin.

Harnesses: `b3_corridor_measure.py` (`--pin` / `--reproduce`),
`b3_candidate_policies.py`. Raw output: `b3_corridor_reproduction.txt`
(before), `b3_corridor_after.txt` (after), `b3_candidate_policies.txt`,
`b3_corridor_report.json`, `b3_candidate_policies.json`.

## 2. Reproduction — W02-F003 CONFIRMED on the fresh pin

Identical to the B2 measurement, so the finding is not an artifact of
either snapshot:

- **183 of 329** ranked IDP rows clamped = **55.6%**
- `cappedByMaxBand` on **183/183 (100%)**
- landing exactly on the band edge on **183/183 (100%)**
- only `bandPct = 0.15` observed
- direction **23 up / 160 down** — predominantly a ceiling

Three things the finding did not record.

**The per-bucket machinery is unreachable on this board, not merely
dominated.** Empirical bands: high 0.6504 (n=36), low 0.6316 (n=173),
medium 0.5183 (n=120), overall 0.6201 — 3.5× to 4.3× the cap, in *every*
bucket, all three above the 30-row minimum so the small-sample fallback
never fires either.

**The corridor, not the blend, determined the value.** Unclamped distance
from the anchor was median 0.2264 / p90 0.6483 / max 0.8261; after the
clamp it was exactly 0.15 on every clamped row. 55.6% of the ranked IDP
board was served at precisely `idpTradeCalc × 0.85` or `× 1.15`. Served
effect: 193 rows differed with the corridor on, mean |14.45%|, p90 30.5%,
max 52.0%.

**The anchor is not independent evidence** (§5, mandatory). All four
members of the IDP anchor chain — `idpTradeCalc`, `dlfIdp`, `idpShow`,
`fantasyProsIdp` — are voting sources in the blend the corridor clamps.
In practice the fallback never fires: `idpTradeCalc` was the anchor on
**183/183** clamped rows, and on **183/183** it also voted in that row's
blend. So it received a direct contribution *and* a post-blend veto.

The vote-share isolate — computed from the stamped per-source
contributions, so the IDP ladder that `idpTradeCalc` also seeds as backbone
stays intact — puts its contribution at **0.721×** the median of the other
sources on those rows (p10 0.452, p90 1.184). It prices them below its
peers, which is why 160 of 183 clamps pulled values *down*. Clamped rows
were thin: median 3 stamped sources, minimum 2.

The whole-board leave-`idpTradeCalc`-out rebuild is reported as an **upper
bound only**: dropping it empties the shared-market ladder and changes
every other IDP source's coordinates, so it is not "the same model minus
one vote". The vote-share figure is the isolate.

## 3. The stale rationale — §6

Dated from the tree, not inferred:

| date | commit | event |
|---|---|---|
| 2026-04-21 | #198 | corridor added, rationale "contain the IDP calibration post-pass's 3-4× DB-bucket multipliers" |
| **2026-04-23** | **#251** | **"remove: retire IDP calibration end-to-end"** |
| 2026-05-02 | #375 | hard cap added at 0.25 |
| 2026-05-02 | #376 | cap tightened 0.25 → 0.15, same day |
| 2026-05-16 | #464 | offense exempted |
| 2026-05-19 | #496 | single-source haircut (retain 30%) — an anchor-free mechanism for the same hazard |
| 2026-08-04 | — | "never binds" note recorded |

**The mechanism the corridor exists to contain was retired two days after
the corridor was built**, and the cap that came to decide 100% of clamps
arrived nine days after that. Confirmed absent today: no
`_apply_idp_calibration_post_pass`, no `config/idp_calibration.json`, with
two existing test files asserting they stay gone.

So the corridor has been an orphaned safety mechanism for ~3.5 months, and
its docstring still names a dead mechanism as its sole purpose. Whether
*another* current mechanism requires it: the single-source explosion it
describes is now handled by `_SINGLE_SOURCE_VALUE_RETENTION` (#496), which
needs no anchor.

## 4. The confidence-bucket dependency — §7

**Not blocking, and the reason is measurable.** The corridor derives its
band per confidence bucket, but the derived number was discarded on every
row, so bucket quality could not invalidate a band that was never used. B3
is therefore not blocked by the separately-tracked confidence work. The
dependency becomes live the moment the empirical band decides anything —
which, after the repair in §6, it does. That is a stated consequence, not
a hidden one: the corridor's behaviour now depends on confidence-bucket
semantics for the first time in practice.

What the buckets showed about *who* was being clamped is the finding that
matters, because it is the inverse of what a safety mechanism should do:

| bucket | ranked IDP | clamped | rate | up/down |
|---|---|---|---|---|
| high | 36 | 23 | **63.9%** | 6/17 |
| medium | 120 | 55 | 45.8% | 11/44 |
| low | 173 | 105 | 60.7% | 6/99 |

"High" means two or more sources with a tight percentile spread. The
corridor overrode the board's **best-supported** IDP opinions at the
highest rate, toward the one source that disagreed — and that source was
one of the voters. By source count the concentration was sharper still:
3-source rows 100/112 = **89.3%**, 5-source 26.2%, 6-source 25.0%.

## 5. Evaluation criteria — declared before the candidates (§10)

Printed by the harness before any number and not adjusted afterwards:

1. **Pathology containment** — does it still catch a value that is *wrong*
   rather than merely contested?
2. **Preservation of well-evidenced disagreement** — a policy that
   overrides thick, agreeing rows at a *higher* rate than thin ones is
   inverted.
3. **No hidden second weighting of the anchor** — `idpTradeCalc` already
   votes; a second bite is a cost, not a feature.
4. **Robustness to one missing source.**
5. **Understandable provenance.**
6. **Low sensitivity to arbitrary constants.**
7. **Board coherence** — composition should not move for reasons unrelated
   to evidence.

Explicitly **not** a criterion: which board looks right. No per-player
ground truth for dynasty IDP value exists on this timeframe, so a candidate
selected on plausibility would be selected on nothing.

## 6. Candidate policies, measured on one pin (§9)

`A`, `B`, `E` are true pipeline runs (`E` via the existing
`suppress_market_corridor_clamp`; `B` by clearing the cap dict for one
in-process build, asserted restored). `C` and `D` are post-hoc derivations
from `B`'s drift data and are labelled as such — they do not exist in
production and B3 does not authorize shipping a candidate to measure it.

| | rows | share | up/down | median &#124;Δ&#124; | max | confidence high/med/low | zones top/mid/tail |
|---|---|---|---|---|---|---|---|
| **A** current, P90 capped at 0.15 | 183/329 | 55.6% | 23/160 | 8.3% | 52.0% | 63.9 / 45.8 / 60.7 | 25 / 64 / 94 |
| **B** P90, no hard cap | 32/329 | 9.7% | 0/32 | 2.0% | 10.7% | 8.3 / 10.0 / 9.8 | 0 / 0 / 32 |
| **C** evidence-gated (post-hoc) | 17/329 | 5.2% | 0/17 | 1.6% | 10.7% | 0 / 0 / 9.8 | 0 / 0 / 17 |
| **D** rail at 2× board P90 (post-hoc) | 0/329 | 0% | — | — | — | — | — |
| **E** no corridor | 0/329 | 0% | — | — | — | — | — |

Source-count incidence: **A** 3→100/112, 4→36/60, 5→32/122, 6→2/8.
**B** 3→26/112, 4→3/60, **5→0/122, 6→0/8**.

Board composition, true runs only — top-100 IDP **9** in all three;
top-200 **43** (A) vs **41** (B and E); top-400 **130** in all three.

**Candidate D returning zero is a result, not a null.** No row on this
board drifts more than 2× the board's own P90, so the runaway the corridor
was built to contain does not exist here.

Against the criteria: **B** dominates **A** on 1 (it still catches the tail
outliers; D shows there is nothing more extreme to catch), 2 (flat instead
of inverted), 3 (9.7% instead of 55.6% of the board decided by the anchor),
6 (no hand-set constant at all), and ties on 7. **C** is stricter still but
adds two new hand-set thresholds, losing on 6 to buy little on 2. **E**
gives up 1 entirely.

## 7. The repair

**Remove the IDP entry from `_MARKET_CORRIDOR_MAX_BAND_BY_ASSET_CLASS`.**
The dict is now empty; the facility is kept because the mechanism is
generic and a future asset class may need it.

Removing rather than retuning is the point. Criterion 6 was low sensitivity
to arbitrary constants, and `0.15` decided every clamp — replacing it with
a different hand-set number reproduces the defect at a new value.

Post-repair measurement on the same pin: **32 rows (9.7%)**, `cappedByMaxBand`
**0/32**, `bandPct` now varying by bucket (0.5183 / 0.6316 / 0.6504), all
32 on the band edge, all downward, clamp rate flat across buckets
(8.3 / 10.0 / 9.8%), **zero rows with five or more sources**. Served-value
effect: 32 rows differ, mean |3.27%|, median 1.95%, max 10.68% — the
largest being Will Johnson 1,386 → 1,238.

**RED → GREEN.** Seven characterization tests went red on the removal —
four in `test_market_corridor_characterization.py`, three in
`test_market_corridor_clamp.py` — and were rewritten against the measured
behaviour with the reason recorded in each assertion message. The
extreme-outlier test still passes: the Vikings-LB case is still caught, now
at the board's own band edge (2,520) instead of a constant's (3,060). 46
tests green across both files.

### What this deliberately is not

* **Not "the empirical machinery was dead."** A tighter synthetic board
  reaches it, pinned by `test_a_tight_board_uses_the_empirical_band_not_the_cap`.
  The cap's dominance was a property of this market's IDP disagreement.
* **Not removing the corridor.** Candidates D and E were measured; the tail
  rail is the behaviour the corridor was designed for and it survives.
* **Not a fix for the anchor lineage.** `idpTradeCalc` still both votes and
  anchors. The repair shrinks the second bite from 55.6% of the board to
  9.7%; it does not eliminate it. See §9.

### Residual, stated rather than hidden

The band is derived from the same drift distribution it bounds, so a board
that drifted *as a whole* would widen its own band and catch nothing. That
is a property of the empirical design, not of this removal, and it is why
the cap facility is kept rather than deleted.

## 8. Downstream (§14)

The change is a pure value change on 32 deep-tail IDP rows (max 10.7%),
flowing through `rankDerivedValue` — the single value every engine reads.
`consensus_edge/fair_value.py` already suppresses the corridor by design,
so it is unaffected. Rankings, `/api/data`, `/trade`, finder/suggestions,
waivers/FAAB, Team Strength inputs and value-history provenance all consume
the same field and are covered by the full suite in §10. Missing stays
missing: rows with no resolvable anchor are skipped, never clamped to a
substitute, and that is pinned by
`test_a_row_with_no_anchor_is_never_clamped`.

## 9. Still open after B3

* **The anchor is still a voter.** 9.7% of the ranked IDP board is still
  decided by a source that also votes in it. Whether the corridor should
  anchor on a leave-one-out blend, or on a genuinely external source, is a
  design question B3 did not have authorization to settle.
* **The confidence-bucket dependency is now live** (§4). The band that
  decides clamps is derived per bucket, and bucket semantics are tracked
  separately (W03-F004).
* **C17's other half** — the OFFENSE master at a median 0.76 of `ktcSfTep`
  raw — is untouched by both B2 and B3.
* **The IDP master's 1.552× fit-scale claim** remains un-derived, and now
  matters differently: after B2 that master prices zero rows on the default
  board.
* **W30-F023** (tail clamp) is untouched and open.

## 10. Gates

Recorded in the B3 checkpoint report; full Python hard gate, frontend
suite, build and bundle budgets, ruff, coercion ratchet, audit-status drift
and exact-HEAD CI.
