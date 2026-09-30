# Value replay evidence — Jalen Coker and contrasts (2026-09-30)

**What this is:** a pinned local rebuild of the canonical board through the production
pipeline (`scripts/value_replay.py`, `src/api/value_replay.py`), with single-change
counterfactual rebuilds. Machine-readable: [`replay.json`](replay.json). Tables:
[`replay.md`](replay.md).

**Pins (all content-hashed in `replay.json`):**

| Pin | Value |
|---|---|
| Code revision | `6185e8bc5` (clean tree, including `data/scrape_state` and `exports/latest`) |
| Raw payload | `exports/latest/dynasty_data_2026-09-30.json`, sha256 `69a0f4b4e264…`, scrape `2026-09-30T13:04:04Z` (refresh commit `10c9d7429`) |
| Inputs | every `CSVs/site_raw` CSV, every `data/scrape_state/*_dataset.json` and fetch stamp, every file under `config/` (including Hill masters and the pick-year discount) |
| Local league snapshots | `data/leagues/*.json`, **gitignored**, hashed and flagged untracked. The draft-class snapshot tells the build the 2026 draft is complete, so 2026 picks retire: **1041 rows** here, **1131** from tracked files alone (independent review, reproduced) |
| Live network input | the Sleeper league context the build fetched: `roster_count 12`, `bonus_rec_te 0.0` |
| Flags | full snapshot in `replay.json`, including `multi_bridge_ladder` |
| Outlier filter | k 2.75, min n 4, min threshold 1000 |
| Single-source retention | 0.30 |

**Not established here:** production served `b512619f1` when this evidence was taken, and
its `/api/data` requires an owner login, which this session does not use. The replay
rebuilds from the tracked artifacts the refresh workflow commits and the deploy ships, plus
the local league snapshots above. It is **not** a capture of the live served response or of
the rendered Rankings/Trade UI. The pins are a manifest of the inputs known on 2026-09-30,
measured by auditing a build's file reads, not a proof that nothing else is read. The blend
self-check (below) is a stamp-consistency check: it runs the pipeline's own aggregator over
the pipeline's own stamped weights. It confirms the stamps explain the published value
within 1 point (integer truncation); it cannot detect an error in the weights or the
aggregator themselves.

## Jalen Coker (WR, CAR)

| Quantity | Value |
|---|---|
| Canonical value (`rankDerivedValue`) | **3286** |
| Overall rank / WR rank | 156 / 45 |
| Confidence | high |
| KTC Crowd (native) | 4620 (KTC rank 78) |
| KTC Trades (native) | 4184 → 4493 on the board scale |
| KTC Market benchmark (non-voting) | 4402 |
| Market gap | −1116 (−25.4%) |
| Outlier-dropped | **both KTC voters** — the only row on the board where that happens |
| Blend self-check | consistent (14 voters → 3286.55, published 3286; within 1 point) |

Every per-source raw value, transformed value, path (value-direct vs rank→Hill),
applied weight, freshness factor, family adjustment and exclusion reason is in
[`replay.md`](replay.md#jalen-coker-wr-offense).

**Counterfactual sensitivities.** Each is one change, rebuilt through the real pipeline.
They are not additive shares.

| Change | Coker | Board effect |
|---|---|---|
| Outlier filter off (diagnostic) | +120 → 3406 | 115 rows change; 8 top-200 membership changes |
| KTC native values taken as ranks on the Hill curve (diagnostic) | +158 → 3444 | 910 rows; 34 top-200 changes |
| Freshness weighting off | −20 → 3266 | 768 rows |
| Leave out KTC Crowd or KTC Trades | 0 | both are already excluded for this row |
| Drop the three voters whose data predates the 2026 season (Fitzmaurice 09-01, Yahoo/Boone 09-03, IDP Show 08-19) — `leave_out_set:pre_season_data` | **+196 → 3482**, rank 142; KTC Trades stops being an outlier and votes | 698 rows; 6 top-200 changes |
| The same, plus outlier filter off | +210 → 3496 | ad hoc; not in `replay.json` |

**Football context**, dated. Coker opened 2026 with 18-222-2 on 22 targets. He left the
Week 3 game (2026-09-27) with what the team called a minor quadriceps strain, after an
ankle roll in Week 1 that he said would not cost time. Sources: RotoWire player page,
Panthers.com injury note of 2026-09-28, both read 2026-09-30. Contract and snap-share
detail were not verified in this pass and are not used.

**Conclusion — why the board sits ~1100 below KTC Market:**

1. **Defensible, current market disagreement (largest part).** Boards republished after
   his breakout still rank him about 86–122 (DLF 09-29, FantasyCalc/DynastyDaddy/Flock/
   FantasyPros 09-30, DraftSharks 09-30, PFK 09-29). The fresh evidence genuinely prices
   him below KTC's crowd. This is not a defect, and nothing here justifies moving him to KTC.
2. **Information age, not fetch age (lead V2-2, VERIFIED here).** Three voters carry data
   from before the season (Aug 19 – Sep 3). They are counted as on schedule because their
   cadence is monthly. Applied weights: Yahoo/Boone 1.0, Fitzmaurice 0.5 (family-capped
   with FantasyPros SF), IDP Show 0.057 (stale). Removing them is worth +196, and it changes
   which observations the outlier filter rejects.
3. **Scale mixing (lead V2-5, VERIFIED as measurement, cause UNKNOWN).** KTC votes on its
   native value, while the other sources vote through rank→Hill. For ranks 51–400, KTC
   Crowd's native values sit 14–45% above the Hill value of its own rank, and KTC Trades'
   sit 22–60% above (`board.nativeVsHill`). That makes KTC look like an outlier next to the
   rank sources. IDP Trade Calculator reads 1.8–5.9× in the same buckets, but its rank is
   taken over a combined offense+IDP+picks population. So the metric partly measures which
   population a rank is drawn from, not only scale; the alignment audit must separate the
   two. This belongs to the
   owner-requested Hill-curve / source-authority alignment audit (2026-09-24), not a
   Coker-specific patch.
4. **Outlier exclusion of the whole market view.** The fixed 1000-point threshold removes
   both KTC observations here. Weights are all 1.0, so this is **not** the weight-blind
   defect (lead V2-3). That defect is characterized separately
   (`tests/api/test_value_replay.py`) and is latent on this board.

Not supported by the evidence: BDVM age/survival logic (the market board does not read
BDVM), identity errors (all joins exact), and freshness weighting of KTC (factor 1.0).

## Contrast set (data-chosen, `scripts/value_replay.py --contrast`)

| Asset | Class | Value | Rank | Note |
|---|---|---|---|---|
| Michael Mayer | TE | 2507 | 240 | below KTC Market 3145; DraftSharks outlier-dropped |
| Travis Hunter | WR/DB | 4024 | 105 | above KTC Market 2450; two-way boost override; taking native values as ranks moves −974 |
| Jeremiyah Love | RB (rookie) | 7819 | 16 | above KTC 7083 |
| Brock Purdy | QB | 6786 | 28 | above KTC 6546 |
| Fernando Mendoza, Cam Ward, Tua Tagovailoa | QB | 5337 / 4164 / 2228 | 57 / 98 / 285 | small market gaps; disagreement that should persist |
| Aidan Hutchinson, Will Anderson | IDP DL | 6411 / 5928 | 34 / 42 | IDP Trade Calculator-anchored by design: leaving it out moves −2977 / −2828 |
| 2027 Round 1 | pick | 5643 | — | leaving out KTC Crowd −323, KTC Trades +323 |

The IDP and pick rows use the anchor+shrinkage path, so the blend self-check reports
`not_applicable` rather than a number it cannot reproduce.

## Reproduce

```bash
python scripts/value_replay.py --asset "Jalen Coker" --contrast --json replay.json --markdown replay.md
```
