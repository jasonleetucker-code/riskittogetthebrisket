# Lane 4 — #804 correlated-source risk: what exists, and what blocks the rest

**Measured:** 2026-08-18. **No code changed from this document.**

The lane brief asks for seven things on #804. Four are already done in the
repo, one is honestly documented as uncovered, and the remaining two are
**blocked by an evidence-retention gap** measured below.

---

## 1. What already exists (do not rebuild)

| brief item | state |
|---|---|
| identify source families | **done** — `correlation_group` is a declared field on every entry in `_RANKING_SOURCES` (`src/api/data_contract.py`); `correlation_group_for()` / `expand_correlation_groups()` are the accessors |
| determine current weighting | **done** — every source is weight 1.0 by policy; `config/weights/default_weights.json` is documentation only and nothing loads it |
| improve protection where justified | **done for declared families** — B10-T3b collapses each correlation group to ONE value after Hampel and before the blend, by registry precedence. A **selection, never an average**: averaging quietly re-admits a derived source at 50%. Pinned by `tests/api/test_family_aware_aggregation.py` |
| distinguish independent information from correlated derivatives | **instrument exists** — `scripts/audit/measure_source_correlation.py` correlates each source's **residual from consensus**, not its raw ranks, which is the right statistic (raw Spearman is ~0.95 between any two dynasty boards and discriminates nothing) |

### The instrument's 2026-07-27 findings, which have not been superseded

```
raw Spearman      same-publisher +0.951   cross-publisher +0.952   (useless)
residual rho      same-publisher  median +0.199   cross-publisher median -0.040
```

Two conclusions that matter, and both cut against naive fixes:

- **Publisher-name clustering would be wrong in at least one case.**
  `fantasyProsFitzmaurice` / `fantasyProsSf` are **anti**-correlated on
  residuals (−0.664) — one analyst deliberately departing from the consensus
  his own employer publishes. Collapsing them loses genuine signal.
- **The strongest dependence in the whole matrix is cross-publisher and
  invisible to names:** `ktc / otcffbSf` **+0.891**, `idpTradeCalc / ktcSfTep`
  +0.698, `dynastyNerdsSfTep / fantasyProsFitzmaurice` +0.681,
  `idpShow / idpTradeCalc` +0.669.

The script shipped as a measurement rather than a confidence change because
four same-publisher pairs on one day is not enough to re-bucket a user-visible
field. Its own header says the clusters that look real "need a second season of
data before they are worth acting on."

## 2. The uncovered risk, already named in `CLAUDE.md`

> correlated multi-source anomalies (measured up to 48% blend movement) are
> caught by neither the old corridor nor this detector, because sources
> agreeing on something wrong is indistinguishable from disagreement at the
> blend. No independent IDP reference exists to arbitrate — every IDP-covering
> source votes.

That is the honest state, and this document does not weaken it.

## 3. What blocks the remaining two items — a measured evidence gap

The brief asks to **quantify common-mode risk** and **test adversarial
scenarios**. Both need the residual matrix as a **time series** — a correlation
that holds every day is structural dependence; one that appears on a single day
is noise. Distinguishing those is the whole question.

**That time series cannot be built, because the evidence is not retained.**

| | |
|---|---|
| per-source boards live today | **24** CSVs in `CSVs/site_raw/` |
| per-source boards preserved in each archive bundle | **3** — `ktc.csv`, `ktcSfTep.csv`, `idpTradeCalc.csv` |
| bundles in `exports/archive/` | **176**, 2026-07-14 → 2026-08-18 |
| bundles carrying more than 3 | **0 of 176** |

The archived payload's `_canonicalSiteValues` carries the same three and no
more. So `measure_source_correlation.py` can only ever run against *today's*
snapshot — the second season of data its own findings wait on is not being
kept, and will not exist however long we wait.

This also bounds the content-staleness check, which is why the measurements
recorded in `CLAUDE.md` name only `ktcSfTep` and `idpTradeCalc`.

### Costed options (measured, not estimated)

| option | per bundle | at ~5 bundles/day |
|---|---|---|
| today (3 CSVs, compressed) | 18 KB | — |
| all 24 CSVs, compressed | 173 KB (**+155 KB**) | ~+283 MB/year tracked |
| **name → rank digest for all 22 ranked sources**, compressed | 49 KB (**+31 KB**) | ~+57 MB/year tracked |
| digest written once daily instead of per bundle | 49 KB | ~+18 MB/year tracked |

The digest is sufficient for the residual-correlation statistic, which needs
only each source's ordering — it does not need the raw CSVs.

### Why this is not changed here

`exports/` and `data/scrape_state/` are force-added by `scheduled-refresh.yml`
every two hours and **deploy dispatch keys on those commit subjects**
(`CLAUDE.md`, W31-F001). Changing what each bundle contains touches the refresh
and deploy path, which is the integration/ops lane, not this one. Recommend it
as a small, separately-owned unit.

## 4. Recommended sequencing for this lane

1. **(other lane)** land per-source rank-digest retention — one small change, ~31 KB/bundle.
2. Wait for ~30 days of digests, then re-run the residual matrix as a time series.
3. Only then decide whether any undeclared pair (starting with `ktc / otcffbSf`)
   should be declared a correlation group. Declaring one is a **one-line
   registry change** that the existing B10-T3b collapse acts on immediately —
   the machinery is already built and tested. What is missing is the evidence
   to justify pulling that lever, not the lever.
4. Do **not** downweight anything in the meantime. The brief is explicit: do
   not create fictional independence, and do not arbitrarily downweight sources
   without evidence.
