# W14 evidence — Consensus Edge

All API captures taken from a SEPARATE backend on port 8001 booted with
`RISKIT_FEATURE_CONSENSUS_EDGE=1` (the shared audit stack on :8000 was
never touched and still 503s these routes). Launcher:
`scratchpad/w14/launcher_8001.py` = the audit launcher with the port changed.

| file | what |
|---|---|
| `health.json` `methodology.json` `top.json` `players.json` `player-travis.json` | all 5 routes, flag ON, authenticated |
| `page-rendered.txt` | `/consensus-edge` rendered text, Playwright with `/api/*` intercepted to :8001 |
| `sharpflow-join-proof.txt` | 2,400 ledger-shaped movements over 400 board players -> 0 rows scored |
| `sharpflow-join-counterfactual.txt` | same movements keyed by displayName -> 400 rows scored |
| `anchor-free-proof.txt` | 0 surviving ktcSfTep/fantasyNavigatorSf votes; served fairValue == fresh LOO board on every priced row |
| `cohort-sign-inversion.txt` | cohort medians and the 28 negative-gap Buys |
| `pytest-consensus-edge.txt` | `pytest tests/consensus_edge/ -q` — 268 passed, 15 skipped (Python 3.11.15; CI pins 3.12) |
