# #804 per-source rank capture (`source_rank` lane)

**Owner module:** `src/history/source_rank.py` · **Lane:** `store.LANE_SOURCE_RANK`
**Flag:** `RISKIT_FEATURE_SOURCE_RANK_CAPTURE` — **default OFF**
**Status:** POST-V1 capture infrastructure. **Changes the V1 percentage by zero.**

---

## 1. What this is, and firmly what it is not

**Capture only.** It records what each source ranked each asset, on each build,
into the canonical temporal ledger. Nothing reads the lane.

Explicitly **not** in this unit, and unauthorized until separately approved:
correlation methodology, source-family assignment, family weighting, automatic
downweighting, confidence changes, B10 logic, and any canonical value or
ranking movement.

## 2. Why the evidence has to be captured now

#804 is about **correlated / shared-lineage source movement**: injected
correlated anomalies moved the blend by as much as **~48%** while existing
defenses caught nothing, because sources agreeing on something wrong is
indistinguishable from agreement at the point of the blend.

Deciding whether two sources are genuinely independent needs their observations
**over time** — a correlation that holds every day is structural dependence;
one that appears on a single board is noise. That series does not exist:

| | |
|---|---|
| per-source rank maps published per build | **22–24** |
| source boards preserved in any archive | **3** |
| archive bundles carrying more than 3 | **0 of 176** |

Every build that goes unrecorded is a day of evidence no later effort can
reconstruct. That is the whole justification for capturing before the analysis
that will use it is designed.

## 3. Why a new lane, not `source_value`

A rank is an ordering **position**; a value is a **price**. They share no units,
are not convertible, and disagree about what "missing" means — a source can rank
an asset it publishes no value for. A query that had to guess which quantity a
row carried could answer neither question.

`store._validate_source_rank` enforces the separation: a `source_rank`
observation must carry an integer rank ≥ 1 and **may not carry a value at all**.

## 4. What one build records

One observation per (asset, source) the board says the source ranked:

| field | meaning |
|---|---|
| `rank` | the **effective** rank — the comparable coordinate a later correlation is computed on |
| `raw_rank` | what the source actually **published**, before ladder translation (a rookie board's #36 becomes #247 on the overall ladder — two different facts) |
| `rank_method` | how the effective rank was derived (`direct`, a ladder translation, …) |
| `rank_pool` | the coordinate pool; ranks from different pools are **not comparable** and must not be correlated |
| `shared_market_translated` | whether the source was projected onto another market's backbone |
| `source_key`, `asset_key`, `observed_date`, `observed_at`(+zone), `origin`, `scope`, `pipeline_version` | identity and provenance, inherited from the store |

`shared_market_translated` is the most important field here. A source projected
onto another market's backbone is correlated with that market **by
construction** — an independence analysis that missed it would "discover" a
correlation the pipeline itself created. Measured on one real board: **638 of
7,245** observations carry it.

### Missing is absence, never zero

A source that did not rank an asset contributes **no row**. Not rank 0, not
null, not a sentinel — the store refuses all three. Absence is the only encoding
a later pass can read correctly, because rank 0 sorts first on every board.
Booleans are refused too (`True` is an `int` in Python and would store as
rank 1).

## 5. Guarantees, inherited rather than reimplemented

The lane rides the existing store, so it gets these for free and cannot drift
from them:

- **append-only** — `INSERT OR IGNORE`; a conflicting re-record is *surfaced*
  and never applied, so a stored observation is never overwritten;
- **idempotent** — re-recording a build is a counted no-op (7,245 written, then
  7,245 duplicates / 0 conflicts on a real board);
- **`HISTORY_FLOOR`** — a pre-2026-07-14 observation is refused as fabricated;
- **never-future** — `asof` selection is lane-parameterised, so a future
  observation is structurally unselectable;
- **tz-aware `observed_at`** — through `record.contract_observed_instant`, the
  one owner of "when did this board happen", shared with the canonical lane so
  the two cannot drift into two definitions. A date-only stamp is **no instant**
  rather than midnight.

## 6. Non-influence — proven, not asserted

Same pinned input export on both sides; **code as the only variable**:

```
python scripts/golden_board.py --input pinned_input.json --out before.json   # origin/main
python scripts/golden_board.py --input pinned_input.json --out after.json    # this branch
python scripts/board_diff.py before.json after.json --expect-no-value-change
```

```
rows 1108 -> 1108 · ranked 740 -> 740 · priced 849 -> 849 · picks 162 · idp 396
VALUES: 0 moved, 0 newly priced, 0 newly unpriced
RANKS:  0 changed
ASSERTION OK: no value changed.
```

The two captures are **byte-identical** (`sha256 c1b9cde42f30021f` both sides).

Structurally reinforced by tests: no valuation or weighting module imports the
lane, the only production importer is the fresh-scrape call site in `server.py`,
the capture module imports no pricing module, and building observations does not
mutate the contract.

## 7. Storage — measured before proposing production

Measured on a real board (`dynasty_export_20260818_230211`), post-`VACUUM`,
minus the empty-schema baseline:

| | |
|---|---|
| observations per build | **7,245** across **21** sources |
| bytes per observation | **446 B** |
| builds/day (2-hourly scrape) | 12 |
| rows/day | **86,940** |
| **bytes/day** | **38.8 MB** |
| 30 days | ~1.16 GB (2.61 M rows) |
| 90 days | ~3.49 GB (7.82 M rows) |
| 1 year | **~14.2 GB** (31.7 M rows) |

**The cost is index overhead on the shared `observations` table, not payload.**
Stripping every denormalized string (`display_name`, `position`, `player_id`,
`scope`) saves only **4–7%** — 446 → 414 B/row. There is no cheap win in the row
shape.

### Cadence is the real lever

| cadence | builds/day | bytes/day | 1 year |
|---|---|---|---|
| every scrape (2-hourly) | 12 | 38.8 MB | ~14.2 GB |
| every 6 hours | 4 | 12.9 MB | ~4.7 GB |
| daily | 1 | 3.2 MB | ~1.2 GB |

Correlation between sources is a question about *days*, not hours, so a daily
capture very likely answers #804 at ~8% of the storage. **That is a judgement
for the owner, not a decision this unit takes** — which is exactly why the flag
ships OFF.

### Retention concern, named and not acted on

At 2-hourly cadence the ledger would outgrow a modest VPS disk within a year,
and `data/temporal_ledger.sqlite` is covered by `riskit-state-backup.sh`, so
backup size grows with it. **No retention or compaction policy is proposed
here** — inventing a destructive one is explicitly unauthorized. The options an
owner has (reduced cadence, a compaction pass, per-source sampling) are recorded
so the decision can be made with numbers rather than guesses.

## 8. Enabling it

```
RISKIT_FEATURE_SOURCE_RANK_CAPTURE=1   # and restart; flag reads are cached
```

Off, the fresh-scrape path records nothing and no response body differs. On, it
writes the lane and logs `source_rank_capture: recorded N observations across M
sources`. No response changes either way — that is what capture-only means.

## 9. Verification

```bash
python -m pytest tests/history -q          # 84 tests incl. the full capture suite
```
