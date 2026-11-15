# Outlier integrity v2: R constraint checks (pre-freeze)

**Constraint checks, never evidence** (preregistration §5.1, R_REGRESSION_PIN). Run before
the Stage 2 threshold freeze under deviation T1/T2 (`../DEVIATIONS.md`): provisional
thresholds (`tau_C` = ln 6), NO-HISTORY (B4 and B3a abstain; persistence never confirms).
They must be re-run at Stage 3 proper on the frozen thresholds.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Reproduce

Throwaway sparse worktree of the code commit, `CSVs/` + `data/` pinned with
`../rootcause/pin_inputs.sh`, then from that tree:

```bash
python scripts/oiv2_regression_boards.py PAYLOAD.json pin2015 OUT_DIR   # refresh d9680440a5
python scripts/oiv2_regression_boards.py PAYLOAD.json pin0527 OUT_DIR   # refresh eb10d3e12d
```

Payload sha256 (both match `../manifests/R_REGRESSION_PIN.json`): pin2015 `3ef54acd…9199`,
pin0527 `b639608f…e11c`. The pinned `CSVs/` and `data/` were byte-identical to each commit
except sparse-excluded `data/ros/aggregate/history/` files the build does not read.

Files: `r_pin2015.json`, `r_pin0527.json` (boards A, B, C, D, B′, C′, B″, C″, Bnf, B′nf:
regression pairs, D4 set, focus rows, drops by source, value changes, V2 stamps,
determinism); `D4_REGRESSION_SET.json` (membership by the registered rule). Test fixtures
(frozen pre-filter panels) live in `tests/fixtures/oiv2/`.

## Results

| check | pin2015 | pin0527 |
|---|---|---|
| 31 IDP votes dropped by the incumbent in B (DLF IDP restored) | 31 / 31 | 31 / 31 |
| retained in C (DLF restored + V2) | **31 / 31** | **31 / 31** |
| retained in C″ (DLF restored + D4 + V2) | **31 / 31** | **31 / 31** |
| D4 set by rule (B′ vs A′, DLF Values' own vote excluded) | 20 votes / 14 rows | 20 votes / 13 rows |
| D4 set retained in C′ and C″ | **20 / 20, 20 / 20** | **20 / 20, 20 / 20** |
| Theo Johnson Draft Sharks in the rule's set | **no** (see below) | no |
| determinism: C built twice, board digest and full `playersArray` sha | identical | identical |
| V2 drops on C / C′ / C″ / D (any layer) | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| incumbent drops on A (offense / IDP) | 99 / 0 | 98 / 0 |

Focus rows (pin2015 values; C = Bnf exactly, i.e. the only change from A is DLF IDP's own
vote): Trevin Wallace A 1937 · B 884 · C 1934; Myles Garrett 3555 · 5245 · 3469; Aidan
Hutchinson 4772 · 6422 · 4772. Draft Sharks votes in C on all three; the incumbent removed
it in B.

**Theo Johnson.** On both pins Draft Sharks votes 3001 / 3009 for Theo Johnson and the
incumbent keeps it in B′ (2186 → 2105 on pin2015, DLF Values' own vote), so the rule does not
produce him. The owner-named case (Draft Sharks 3182, 2184 → 2023) is on the PR #1817 lane's
board `dynasty_export_20261020_052241` (I_INDEPENDENT, not rebuilt here); it is covered by
the frozen panel `tests/fixtures/oiv2/panel_theo_johnson_pr1817_lane.json`, transcribed from
that lane's pre-registration dump, on which the incumbent reproduces the drop and Layer C
keeps the vote at every `tau_C` grid point.

**What these numbers do not show.** V2 drops nothing on these pins because no vote is
further than ln 6 from every other provider; `tau_C` = ln 4 (the registered floor) is not
built here. D vs A (V2 alone, DLF held): 189 rows change, median 0.14%, p90 2.6%, one row
≥ 10% (LaJohntay Wester 648 → 872, +34.6%: an incumbent offense drop V2 does not make —
to be attributed at Stage 3). This is the same mechanism the prereg predicts (§13: ~95–99
offense drops restored).
