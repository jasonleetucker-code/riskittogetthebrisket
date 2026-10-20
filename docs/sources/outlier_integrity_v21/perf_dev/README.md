# V2.1 R13 development measurement (not criteria 13-14)

`scripts/oiv21_perf.py dynasty_export_20260930_130404.zip OUT.json` on the DEV
board (E_DEV), the registered protocol (§10): each configuration in its own
process, one warm-up build, median of 5 warm builds; full contract as served,
its gzip, and the rankings-overrides delta.

* `before_run{1,2,3}.json` -- code at `f14ad7681d` (V2.1 Stage 1b), the script
  copied in.
* `after_run{1,2,3}.json` -- this unit (DEVIATIONS V21-C27..C31).

| | wall ratio | peak RSS delta | full | gzip | delta |
|---|---|---|---|---|---|
| before | 1.84 / 1.81 / 1.89 | +43.4 / +44.2 / +44.4 MB | 1.128 | 1.052 | 1.112 |
| after | 1.22 / 1.26 / 1.22 | +46.5 / +47.3 / +47.5 MB | 1.011 | 1.013 | 1.001 |
| budget | <= 1.25 | <= +50 MB | <= 1.02 | <= 1.02 | <= 1.02 |

Development evidence only. Criteria 13 and 14 are judged on pin2015 at Stage 3
and on G2 at Stage 4. Risks are named in DEVIATIONS V21-C31.
