# Source row-count floors and ingestion contracts (W05-F003 / W05-F004)

Owner requirement: master directive 2026-11-08 section 8 Priority 3. A registered source must not fail silently.

## Ingestion contract (`src/api/data_contract.py::_parse_source_csv_cached`)

One probe owns header validation for every registered source (the earlier four-source probe is kept first,
unchanged). The universal probe is the loader's own contract: a name alias column plus a value alias column
(value signal), a rank alias column (rank signal) or a value alias column (`rank_from: value_order`). It can fail
only where the row loop would have skipped every row anyway, so no value on a healthy board changes.

| `sourceParseErrors.error` | meaning | lane |
|---|---|---|
| `schema_mismatch` (+ `missingColumns`) | renamed or missing required column | source-health ERROR `source_ingest_failure:<key>:schema_mismatch` |
| `source_empty` | 0-byte file or header-only file | source-health ERROR `source_ingest_failure:<key>:source_empty` |
| `no_usable_rows` | rows present, none parseable | source-health ERROR `source_ingest_failure:<key>:no_usable_rows` |
| `parse_exception` (+ `detail`) | the parser raised (truncated/binary/undecodable file) | source-health ERROR `source_ingest_failure:<key>:parse_exception` |
| `invalid_numeric_fields` | >= 10% of data rows carry an unparseable number | warning only |
| `duplicate_rows` | >= 10% of data rows repeat an earlier (name, position) | warning only |

`source_ingest_failure:` is in `_SOURCE_HEALTH_ERROR_KINDS` (full lane only; never structural). Sources absent by design
(private, not provisioned) or inside their declared seasonal-inactive window are excused, exactly as `source_missing` is.
`duplicate_rows` / `invalid_numeric_fields` are report-only: they warn but do not flip `degraded`. Counters are reset on every parse (including every early-return path), so `sourceIngestHealth` never shows a previous good file's numbers for a now-broken one.
Per-CSV counters are stamped as `sourceIngestHealth` (dataRows, blankNames, invalidNumeric, duplicateNames).
The 10% thresholds are PRIORS: on the 2026-11-08 repo CSVs invalid numeric was 0% everywhere and duplicates peaked at
2.8% (fantasyProsIdp 9/319), because vendors genuinely list same-name players twice.

## Floor derivation

Evidence: every distinct committed version of each source CSV in git history (archives carry only KTC, IDPTC and
DraftSharks CSVs), counted with the contract's own parser.

    robust_min = min(history observations that are >= 50% of the history median)
    ratio      = min(1, matched board rows / raw usable rows) on the newest complete archived board
    fraction   = 0.8, or 0.5 for class-phase rookie sources (population follows the draft calendar)
    floor      = floor(fraction * ratio * robust_min)
    ceiling    = 2 * raw max   (report-only)

Reference board for the match ratios: `exports/archive/dynasty_export_20261108_064538.zip`,
sha256 `05e95134d5dc093263890f1369f6f0e060e2e48a76aad51b5193d7f00a7f74b3`, built against the repo CSVs at the
commit that added the floors. The 2x ceilings and the config write are produced by the same script
(`python scripts/derive_source_row_floors.py --keys <list> --write-config`); floors are only added where none exists.

Seasonal transitions: `dlfRookieSf`, `dlfRookieIdp` and `flockFantasySfRookies` describe class-phase populations and
thin together at a draft-season change. They keep their (0.5-fraction) floors and still emit `source_below_floor`
warnings, but are excluded from the "two or more sources below floor" `degraded` flip
(`_CLASS_PHASE_FLOOR_SOURCES`); a collapse to zero still raises `source_missing` unless the declared seasonal policy
excuses it.

Collapsed observations (a degraded scrape) are excluded from the minimum because they are exactly the event a floor
must catch. Reproduce: `python scripts/derive_source_row_floors.py`.

| source | CSV versions | raw min | raw median | raw max | collapsed (<50% median) | robust min | match ratio | fraction | floor | ceiling |
|---|---|---|---|---|---|---|---|---|---|---|
| dlfRookieIdp | 39 | 10 | 29 | 31 | 2 | 29 | 1.0 | 0.5 | 14 | 62 |
| dlfRookieSf | 87 | 10 | 57 | 62 | 2 | 54 | 1.0 | 0.5 | 27 | 124 |
| dlfValuesSfTep | 53 | 319 | 320 | 323 | 0 | 319 | 1.0 | 0.8 | 255 | 646 |
| fantasyCalc | 959 | 391 | 398 | 399 | 0 | 391 | 0.9874 | 0.8 | 308 | 798 |
| fantasyNavigatorSf | 23 | 758 | 769 | 770 | 0 | 758 | 0.5792 | 0.8 | 351 | 1540 |
| fantasyProsSf | 242 | 302 | 540 | 557 | 0 | 302 | 0.8667 | 0.8 | 209 | 1114 |
| flockFantasySfRookies | 365 | 48 | 87 | 103 | 0 | 48 | 0.9792 | 0.5 | 23 | 206 |
| otcffbSf | 231 | 345 | 458 | 474 | 0 | 345 | 0.9845 | 0.8 | 271 | 948 |
| pfkDynasty | 56 | 496 | 496 | 560 | 0 | 496 | 0.8089 | 0.8 | 320 | 1120 |

Rookie sources are pre-existing zero-checked and `flockFantasySfRookies` keeps its seasonal-inactive excusal.
