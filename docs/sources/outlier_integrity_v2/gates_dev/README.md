# Outlier integrity v2: directive §5 gates, full pipeline — DEVELOPMENT run

**Not the gate of record.** Deviation T3/T4 (`../DEVIATIONS.md`): run on the E_DEV board
`dynasty_export_20260930_130404` (already the Stage 1 development board) at the
**provisional** thresholds (`tau_C` = ln 6, `tau_board` / `tau_c` empty) and NO-HISTORY. The
gate of record is Stage 4 (registered V gate board, frozen thresholds) and Stage 5 (newest
I board); `scripts/oiv2_gates.py` refuses those boards until then. No threshold was changed
after this run, and none may be chosen from it (selection is Stage 2's registered rules on
E_DEV with seed 20261020).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

Reproduce (clean tree at code `0a8d2b906f`, ~13 min sequential on 4 cores):

```bash
python scripts/oiv2_gates.py --board dynasty_export_20260930_130404.zip --out edev_20260930_130404.json
```

Exit 1 (at least one gate failed). Seed 2033. Zip and payload sha256 checked against
`../manifests/E_DEV.json`. Release-default DLF state (DLF IDP held, D4 off).

## What each gate measures

Every corrupted observation enters through `data_contract._ADVERSARIAL_VOTE_TRANSFORM`
after pricing and before every integrity layer, the filter, the family cap and the blend;
the whole board is rebuilt per batch and configuration (none / incumbent / V2). Layer A, B0
and B2 have no signature to read by construction (a correctly formatted, correctly
attributed number both copies agree on). AD3 = B3 on a board-wide vote transform.
Material = no-filter board moves the row ≥ 0.10 log; pass = excluded by any layer or own
board moves < 0.10.

## Results (V2 primary configuration, NO-HISTORY)

| gate | bar | cases / material | **V2** | incumbent | V2 by family count 3 / 4–5 / ≥6 | verdict |
|---|---|---|---|---|---|---|
| AD1a ×5 | 90% | 756 / 288 | **56.3%** | 79.2% | 50.0 / 63.2 / 34.2 | **FAIL** |
| AD1b ×0.2 | 90% | 756 / 184 | **11.4%** | 51.1% | 21.6 / 7.8 / 0.0 | **FAIL** |
| AD1c ×20 | 95% | 756 / 326 | **92.6%** | 78.2% | 86.1 / 93.8 / 97.1 | **FAIL** |
| AD1d ×0.05 | 95% | 756 / 224 | **94.2%** | 58.0% | 82.1 / 99.3 / 100 | **FAIL** |
| AD2 wrong player | 90% | 669 / 131 | **1.5%** | 37.4% | 0.0 / 1.1 / 16.7 | **FAIL** |
| AD4 spike | 95% | 228 / 69 | **76.8%** | 88.4% | 100 / 73.2 / 75.0 | **FAIL** |
| AD3 wrong scale | 16 / 16 | 16 boards | **4 / 16** | — | only the four `reversed` boards (B3b direction) | **FAIL** |

AD3: ranks ×2 / ×5 preserve order, so without history B3b's direction test cannot fire and
B3's scale tests need a baseline; values ×0.01 is not flagged as a board but Layer C
removes 233–403 of the corrupted votes row by row (not "flagged before voting").

Batch contamination: the only uncorrupted row that moved > 0.01 log in any batch is Travis
Hunter (8 of 177 batches, up to 0.77 log), the two-way row whose alternate-position value
reads the IDP pool. It is a real pipeline coupling, recorded rather than removed.

These are development numbers at provisional thresholds and are consistent with the
preregistration's stated expectation (§13: AD1b, AD3 and wrong-player fail under
NO-HISTORY; expected verdict MORE RESEARCH REQUIRED). AD1a, AD1c, AD1d and AD4 also fall
below their bars here.
