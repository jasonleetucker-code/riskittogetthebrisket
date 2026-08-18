# DraftSharks dynasty ingestion — repair record and live verification

**Status:** repair MERGED (#894, `77f037ef2`, 2026-08-18 09:32Z).
Live candidate verification COMPLETE. Production `scheduled-refresh` proof recorded in §6.

**Disposition:** see `docs/sources/SOURCE_CENSUS_2026-08-18.md` §S-4.

---

## 1. What was broken

`draftSharks` / `draftSharksIdp` last fetched successfully at **2026-08-05T18:13:02Z** and had
been failing every 2-hourly cycle since — **303.5 h (12.6 days)** at the time of this
verification. The committed boards in `CSVs/site_raw/` were therefore 12-day-old evidence
still voting at full weight in the canonical blend.

Two things hid it:

- The refresh's **scrape sanity** step counts rows in the file **on disk**, so it reported
  `draftSharksSf: 454 rows OK` and `draftSharksIdp: 410 rows OK` for a source that had not
  fetched in twelve days. A row count is not a fetch.
- `draftSharksRos_last_success` was **0.5 h** — the ROS feed is a *different endpoint* and
  works fine. A glance at "DraftSharks" in the state directory shows a healthy timestamp.

The freshness watchdog *did* catch it (`fail: 2 stale source(s), 20 fresh`), and that single
condition is the **only** reason the scheduled refresh had been red on six consecutive runs.

## 2. The ingestion defect itself

The dynasty board is delivered by **htmx** and parameterised by `#sharedParams`, whose
`fantasyPosition` control decides which families the table contains. The unfiltered board
returns **250 rows and no IDP at all**. The previous fetcher read that single unfiltered pass,
so it could only ever see a subset of one family group.

The repair drives the page's own `fantasyPosition` filter across every family on the **same
authenticated, league-scored session**, keyed on the vendor's stable `data-key` attribute.

Three fail-closed guards were the merge precondition:

| guard | what it refuses |
|---|---|
| **R1** — vendor-id union | any row that carries no `data-key`. Rows are unioned on the vendor id, never on name — a name-keyed union is how two people become one asset |
| **R2** — expected-family completeness | a run missing any of QB / RB / WR / TE / DL / LB / DB |
| **R3** — league-scoring proof per pass | a pass whose probed values have not been *observed* to move off the settled public baseline and settle there |

Plus an **exact `Decimal` equivalence** gate across every asset seen in more than one pass: the
same asset priced differently by two passes means the passes are not one currency, and the run
is refused rather than reconciled.

## 3. Live candidate run — measured

Run [`32122471032`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/32122471032),
`workflow_dispatch`, candidate mode, exit 0, 2 m 31 s. Artifact `9319129520`.

```
reconciliation: {"passes": {"all": 250, "QB": 52, "RB": 115, "WR": 185, "TE": 88,
                            "IDP": 410, "DL": 159, "LB": 89, "DB": 162},
                 "uniqueAssets": 850, "rowsWithoutVendorId": 0,
                 "overlappingAssets": 660, "overlapByFamily": {"offense": 250, "idp": 410},
                 "identityCollisions": [], "valueConflicts": [], "valueConflictCount": 0}
```

- **All seven expected families present.** Offense union 440 (QB 52 · RB 115 · WR 185 · TE 88);
  IDP union 410 (DL 159 · LB 89 · DB 162). 850 unique assets.
- **The multipass is what recovers them.** The `all` pass yields 250 rows; the per-family union
  yields 440. The 190-row gap is the defect, measured.
- **Identity: `rowsWithoutVendorId: 0`**, zero collisions. Every row joined on `data-key`; no
  name-keyed fallback was reachable.
- **League scoring proven for all 9 passes**, each sampling 40 comparable rows with **38–40**
  differing from the settled public default. Never 0.
- **Currency equivalence: 660 overlapping assets, 0 conflicts** — exact `Decimal`, not a
  tolerance.
- Per pass, `rows loaded` equals `extracted rows` exactly, and `hiddenRowContainers: 0`, so no
  pass was silently truncated.

### The traversal trigger is conditional, not unconditional

```
[DS] no IDP rows in the unfiltered board — traversing the page's own
     fantasyPosition filters on this same league-scored session
```

The multipass fires on a **measured absence**, so a vendor that starts returning a complete
unfiltered board does not silently keep paying for nine round-trips.

### Fixture and log hygiene

The sanitized fixture emitted alongside the CSVs was scanned: **0** occurrences of the league
id, the league name, or any email-shaped string; identities are synthetic (`data-key` 900001+,
`Synthetic Player NNNN`). Secrets appear as `***` in the log. The probe's
"Assert nothing in the repository was modified" step passed — *working tree clean, the probe
wrote only to `RUNNER_TEMP`*, so a diagnostic cannot become an unreviewed board change.

## 4. Candidate board vs the 12-day-old committed board

| | committed (2026-08-05) | candidate (2026-08-18) | Δ |
|---|---|---|---|
| offense rows | 454 | 440 | −14 |
| IDP rows | 410 | 410 | 0 |
| offense values changed | — | 274 of 440 common | median 1, p90 3, max 13 |
| IDP values changed | — | 16 of 410 common | median 1, p90 3, max 6 |

**The 14 dropped offense players are vendor pruning, not traversal loss**, and the distribution
proves it: **0 of the committed board's top 300 ranks were dropped**; all 14 sit at ranks
340–452 with 3D values from 8 down to −12, interleaved with 26 survivors rather than forming a
contiguous tail. Three carry `1yr. Proj = 0`. The names are the mid-August cutdown profile —
Nick Chubb (30.6), Joe Mixon (30.0), Taysom Hill (35.9), Antonio Gibson, Braxton Berrios,
Britain Covey, and six UDFA/late-round rookies. Zero players were **added**, consistent with a
prune rather than a re-crawl.

## 5. Canonical board effect — §25 classification

Pinned-input diff (`scripts/golden_board.py` → `scripts/board_diff.py`), identical export
fixture and identical other source CSVs; the DraftSharks pair is the only input that moved.

```
rows 1111 → 1111    ranked 740 → 740    priced 849 → 849    picks 162 → 162
VALUES: 418 moved, 3 newly priced, 3 newly unpriced
        |pct| p50 0.2%   p90 1.0%   max 6.9%
RANKS:  438 changed
LABELS: canonicalTierId 660 · confidenceBucket 15 · confidenceLabel 16
        marketGapDirection 4 · hasSourceDisagreement 5 · isSingleSource 1
SOURCE COVERAGE: 19 rows vote differently
```

**DraftSharks is not board-inert and is not claimed to be.** Replacing 12.6-day-old evidence
with current evidence is *supposed* to move the board.

| class | what | why |
|---|---|---|
| **EXPECTED REPAIR** | 418 value moves, 438 rank changes, 13 genuine vote changes, 15/16 confidence flips, 4 market-gap flips | current evidence replacing stale evidence. Largest movers are exactly the players whose DraftSharks row moved most (Justin Fields −3 → 10 on the vendor board → +3.4% on ours) |
| **INCIDENTAL BUT EXPLAINED** | 660 `canonicalTierId` flips | the board lost 3 tiers (132 → 129 distinct), so tier ids **renumber**. Deltas cluster at −1…−8 with 79 at +1 — a shift, not reassignment |
| **INCIDENTAL BUT EXPLAINED** | 3 newly priced / 3 newly unpriced | the `OVERALL_RANK_LIMIT` boundary. The bottom of the valued player board is a 7-point band (1150–1157) and six rows crossed it. Verified in the built contract: McAlister keeps `fantasyProsSf`/`flockFantasySf`/`flockFantasySfRookies`, Chubb keeps all five non-DraftSharks sources, Kenny Moore keeps all three — `canonicalSiteValues` and `sourceRanks` are intact for every one. Only the capped fields are withheld |
| **UNEXPECTED** | none | |

The 13 genuine vote changes are 12 × `draftSharks` and 1 × `fantasyProsIdp`: Hampel
inclusion/exclusion flips as the vendor's rank moves relative to its peers. `fantasyProsIdp`'s
own CSV did not change — its row for Jacob Rodriguez re-entered because the DraftSharks IDP
shift moved that row's median.

### One measurement-honesty note about the harness

`board_diff.py` reports "SOURCE COVERAGE: N rows vote differently" from
`effectiveSourceRanks`, which is **only stamped inside `OVERALL_RANK_LIMIT`**. Six of the 19
here are cap crossings, not vote changes. The comparison is sound; the label is looser than the
quantity. Read it as 13 vote changes + 6 boundary crossings.

## 6. Production proof — GREEN

Diagnostic success is not the proof. The repaired fetcher had to run inside the real
`scheduled-refresh.yml` path and clear the freshness watchdog.

Run [`32123775865`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/32123775865),
`workflow_dispatch` on `77f037ef2`, 2026-08-18 09:51–09:57Z. **Every gate passed** — scrape
sanity, DLF freshness, **staleness watchdog**, contract coverage — and the workflow closed its
own rolling tracking issue #765 with *"Scheduled data refresh is green again"*. This is the
first green refresh after **at least six consecutive failures**, and the DraftSharks staleness
was the sole condition failing all six.

| stamp | before | after |
|---|---|---|
| `draftSharks_last_success` | 2026-08-05T18:13:02Z — **303.5 h** | 2026-08-18T09:56:13Z — **0.03 h** |
| `draftSharksIdp_last_success` | 2026-08-05T18:13:02Z — **303.5 h** | 2026-08-18T09:56:13Z — **0.03 h** |

Committed to `main` as `3fce3b8d2` (stamps) + `e3853f3c0` (data).

**The production CSVs are byte-identical to the verified candidate** — 440 offense rows
(QB 52 · RB 115 · WR 185 · TE 88) and 410 IDP rows (DL 159 · LB 89 · DB 162), `cmp` clean on
both files. The §5 board diff is therefore the *exact* production movement, not an
approximation of it.

**Disposition: `ACTIVE — HEALTHY`.**

## 7. What this does not close

- The **scrape sanity** step counts rows in the file on disk, so it reported `OK` throughout the
  twelve-day outage. It cannot distinguish "the vendor answered" from "the file is still there".
  Tracked as census item **S-3** (health vocabulary must distinguish fetch-failed from
  vendor-unchanged from stale).
- `board_diff.py`'s source-coverage label counts rank-cap crossings as vote changes (§5).
