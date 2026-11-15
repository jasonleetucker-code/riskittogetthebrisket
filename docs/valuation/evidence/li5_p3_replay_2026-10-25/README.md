# LI-5 phase P3 — pinned replay evidence (2026-10-25)

Evidence for `docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md`
§6 (P3 row), §8 item 9 and §9, produced by `scripts/li5_replacement_replay.py`.
Flag `replacement_level_li5_consolidation` is **OFF and owner-held**; nothing here
authorizes activation (P4 is a separate owner approval).

| file | what it is |
|---|---|
| `identity_origin_main.json` | flag-OFF digests of every wired consumer's output on `origin/main@503f08581` (the commit before the wiring) |
| `identity_branch.json` | the same digests on the P3 branch (`96e6f4b19`); `combinedSha256` equal (`e203def2…`), 120 outputs: 12 teams, 48 seeded trades, both forced-drop states |
| `replay.json` | the stepwise table and consumer effects, flag OFF vs ON; re-stamped on `f23d0a2c1` (LI-5 P3 follow-ups, finding F-A) |

## Reproduce

Inputs are pinned: the board archive (sha256 stamped), the `CSVs` /
`data/scrape_state` / `config/weights` tree materialised from `--csv-rev` (its
content hash is stamped), scarcity held inert, every socket connect refused.

```
python scripts/li5_replacement_replay.py --mode replay \
    --archive exports/archive/dynasty_export_20261025_120337.zip \
    --csv-rev 503f08581 --as-of 2026-10-25 \
    --out docs/valuation/evidence/li5_p3_replay_2026-10-25/replay.json
```

Pins (these are also the script defaults, and are stamped in `provenance`):
archive sha256 `50fb251a…c8f6`, CSV tree revision `503f08581b7c…`, tree content
sha256 `8df07701…6367`, evaluation date 2026-10-25. Only `provenance.codeSha` /
`generatedAt` and the `latency` timings differ between runs.

## Follow-up F-A (2026-10-26): charge `state` transitions were hidden

The first `replay.json` summarised a forced-drop charge's basis by `basis.bound`
only, so `boundTransitions` read `[]` in both forced-drop states. Under LI-5 ON
with forced-drop **OFF** (`fds0`), three charges move `state: exact` ->
`state: lower_bound` **at 0.0**, with `bound` `None` on both sides:

| trade | charge, flag OFF | charge, flag ON |
|---|---:|---:|
| `team02/2for1` | 1817 | 0 |
| `team08/0for2` | 1688 | 0 |
| `team08/3for1` | 1688 | 0 |

`replay.json` now also carries `stateTransitions` (counts by kind) and
`stateTransitionTrades` (each changed trade with both charges and the basis's own
`lowerBoundReasons`) per forced-drop state. `fds0` has `{"exact->lower_bound": 3}`;
`fds1` has none. In all three the flag-ON side's reason is
`unpriced_forced_drops_excluded`: the drop set changes (`dropSetChanged`) and
now holds a release the board does not price, which `forced_drop_cost` leaves out
of the sum and labels a lower bound. Nothing else in the file changed (checked
field by field against the previous run; only `provenance.codeSha` /
`generatedAt` and the machine-dependent `latency` timings differ).

**P4 evidence must include these three charges.** A lower bound at 0.0 is "the
priced part of the cleanup is zero", not "releasing is free", and the same
charge was an exact, priced 1688-1817 with the flag OFF. The P4 package has to
state, per transition, which unpriced player enters the drop set and what each
consumer does with a lower bound (the Team Context forced-drop factor is derived
from this charge, so a 0.0 floor removes its penalty). It must not summarise the
charge change by `bound` or by mean delta alone: the `fds0` mean (-250.9) and
minimum (-1817.0) do not show the 0.0 floors. Any later replay must report
`stateTransitions` as well as `boundTransitions`.
