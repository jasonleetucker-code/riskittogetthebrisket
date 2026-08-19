# #804 rank-digest capture — the cadence decision (owner)

**Status: awaiting an owner decision. Nothing is scheduled and nothing is on.**

The capture unit shipped in **#921** and its feature flag is **OFF**. This
document exists because the one thing left is not an engineering choice — it is
a storage/fidelity trade the owner should make, and it should not be smuggled in
as a default.

**This changes the V1 percentage by zero.** #804 capture is post-V1
infrastructure. No canonical value, ranking weight, source weight, confidence
level, B10 family assignment or decision surface depends on it, and no consumer
reads the series.

---

## What the capture is for

#804 is about **correlated / shared-lineage source movement**: sources that move
together are not independent votes, and correlated anomalies were measured
moving the blend by as much as **~48%** with no existing defence catching them.

Deciding a defensible correlation grouping needs **longitudinal per-source rank
observations** — the same sources, the same assets, over many days. That
evidence does not exist: 24 sources are live, 3 are archived, and 0 of 176
committed bundles retain more. Every day not captured is a day that cannot be
recovered later, which is the only reason this is time-sensitive at all.

**Capture is not analysis.** Correlation methodology, family weighting,
automatic downweighting and confidence changes all remain unauthorized.

---

## The measurement

Per build, on the live board:

| quantity | measured |
|---|---|
| observations | 7,245 |
| sources contributing | 21 |
| bytes per row (incl. index overhead) | 446 B |

Denormalization accounts for only **4–7%** of the per-row cost; index overhead
dominates. So schema tuning is not the lever — **cadence is**, and it is close
to linear in the number of builds retained.

| cadence | rows/day | bytes/day | 30 d | 90 d | 365 d |
|---|---|---|---|---|---|
| **every build** (12/day, the 2-hourly refresh) | ~87,000 | **38.8 MB** | 1.2 GB | 3.5 GB | **14.2 GB** |
| **daily** (1/day) | ~7,245 | **3.2 MB** | 97 MB | 291 MB | **~1.2 GB** |

---

## The trade, stated honestly

**Every build** captures intra-day co-movement. If two sources republish within
the same day and move together, only build-level capture can see it.

**Daily** costs ~8% of the storage and still answers the question #804 actually
poses — *do these sources repeatedly move together over weeks?* — because a
source's own publication cadence is daily at best for most of the pool.

What I can measure says daily is sufficient for the stated purpose. What I
cannot measure is whether a future analysis will want the intra-day resolution,
and that is a real cost of choosing daily: the resolution is not recoverable
afterwards.

**Recommendation: daily.** ~1.2 GB/year is a cost worth paying to stop losing
evidence, and it is small enough not to need a retention policy in the same
breath. Every-build is defensible if intra-day co-movement is expected to
matter, and it is the one that would need a retention decision alongside it.

---

## What is deliberately NOT proposed here

**No retention or compaction policy.** Deleting perishable evidence is an owner
decision, and inventing one unauthorized would be the same class of error the
capture exists to correct. The 365-day figures above are what *accumulates*, not
a claim that it must be kept.

If every-build is chosen, retention becomes a question that needs its own
decision — flagged, not answered.

---

## Turning it on

The flag defaults OFF and flag reads are cached per process, so a change needs a
restart. Whichever cadence is chosen, the switch is a scheduling decision plus
the flag; no code change is required for either option.

Confirm non-influence after enabling, the same way #921 proved it before
shipping: `scripts/golden_board.py` before and after with code as the only
variable, then `scripts/board_diff.py --expect-no-value-change`. #921's own
capture was byte-identical.
