# BDVM v1.0 Reference Fixture (Appendices A–F)

**Status: reference-only. Nothing in this directory is imported by production code.
Do not modify these files** — they are the acceptance fixture for the BDVM
integration (`src/bdvm/`). Production adapters live elsewhere.

## Provenance

Extracted from `../BDVM_v1_complete.pdf` ("The Brisket Dynasty Valuation Model
(BDVM) v1.0", July 2026), Appendices A–F, on 2026-07-27. The PDF's embedded code
blocks were reconstructed to runnable form (the PDF-to-text step destroys
indentation and column alignment; logic, identifiers, constants and literals are
reproduced verbatim).

| File | Appendix | Notes |
|---|---|---|
| `dynasty_engine.py` | A | Stdlib-only reference engine, every Part-5 formula |
| `run_examples.py` | B | Driver reproducing the Part-10 worked examples |
| `examples_output.txt` | C | Output of `python3 run_examples.py` (verified, see below) |
| `schema.sql` | D | PostgreSQL schema (design reference; the platform is file-based today) |
| `league_config.example.json` | E | 12-team SF/TEP/PPR/IDP league as config |
| `player_payload.example.json` | F | API request/response contract example |

## Verification (2026-07-27)

`python3 run_examples.py` was executed and its output compared against the
PDF-embedded Appendix C token-by-token (whitespace-normalized, because PDF text
extraction mangles column padding): **956/956 tokens identical, 0 mismatches**.
Every number in the document's Part 10 worked examples — replacement levels
(QB 12.40 / RB 6.35 / WR 6.15 / TE 6.80 / DL 6.70 / LB 7.32 / DB 6.17), all 13
archetype valuations, probability outputs, decompositions, season paths, trade
math, pick values, and the full-precision roster report floats
(`77200.44208318304`, `52449.00468335995`, `1.471914339447432`) — reproduces
exactly. `examples_output.txt` here is the actual verified run output.

Reconstruction caveats (all cosmetic, none affect execution):

- Two JSON comment strings in Appendix E and the `narrative` string in
  Appendix F were truncated by the PDF page width; their endings
  ("…CB-required league.", "…tune it first.", "…weak link.") were completed
  editorially.
- Known quirk preserved as-is: in `run_examples.py` the 9th positional
  `RiskProfile` argument is `small_sample` per the dataclass field order, while
  the document prose (§4.10) describes the LB's `0.05` / safety's `0.35` as
  `designation_risk`. The code's positional semantics are what generated
  Appendix C (verified numerically), so the code wins.

## SHA-256

```
a056fee6aaa51ad72526b15df5ae20f566e6918fc1588432cb7c1ac41742ee21  ../BDVM_v1_complete.pdf
08820cfa545787c18c1a3f17737a1b08a292533c135a1fac30fdda10319f30ff  ../claude_code_bdvm_master_integration_prompt.pdf
1372cec999f8e405b2ce158360777dbe9848ec422e54099aa5d96a298d60e0ff  dynasty_engine.py
829d0d0a3960e1700f7cf7bb2c81aa4bd37f24bc8dede392a27a3b648462c7dc  run_examples.py
bef6f13c622fa36c29dcad4c4fde59066f302b2dd8d4110a7d645f339b12febb  examples_output.txt
7dd464ee209a0468718bfb545b64537e8256aef57f2f79e74112a93162f6ab26  schema.sql
f632d09bb3023ecaa125ba5615c7a86d92cfb8f2c41dff6e86a5ecde2a601cd1  league_config.example.json
ed791747243fbfc69f819023f2ab2c31bb30cdb1522df22c51ec9ebdc4580299  player_payload.example.json
```

Regression guard: `tests/bdvm/test_reference_parity.py` re-runs the reference
engine and asserts the golden numbers above, so any accidental edit to this
directory fails CI.
