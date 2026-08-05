# Next Steps — what still needs doing

Written at the end of the audit-and-repair session on PR #722, so the state survives
the chat that produced it. Numbers measured, not remembered — regenerate any of them
with `tools/verify_closure.py` and `tools/merge_registry.py`.

## Do this first

```bash
.venv/bin/python -m pytest tests/ -q          # on a QUIESCENT tree — see below
```

**This is verification debt, and it is the one thing I would not skip.** The last ten
commits (repair wave D) were pushed with `ruff` clean and the frontend suite green
(116 files / 1,870 tests), but **without** a full Python run and **without** the
independent red-test spot-check I did for wave C. The last clean full-suite figure is
**6,553 passed / 0 real failures**, measured after wave C.

"Quiescent" is load-bearing: `inspect.getsource` reads files at call time, so running
the full suite while anything edits source produces phantom failures in untouched
modules. That cost three false alarms in this session before the rule was written
down (`REPAIR_PROTOCOL.md` rule 5).

## Where the work stands

**432 findings · 85 closed · 347 open** — but 347 is not 347 units of work:

| open bucket | n | what it actually is |
|---|---|---|
| Records of code that **works** | 57 | `Implemented and verified` — nothing to do |
| **Actual repair backlog** | **267** | 48 P1, remainder P2/P3 |
| Feature **builds**, not repairs | 11 | see below |
| **Blocked by data** | 9 | not schedulable until an input exists |
| Unverifiable without production | 3 | |

All **9 P0s are closed**, each with a measured before/after (see `CLOSURE_STATUS.md`
and the commit bodies).

### Open P1s, by where they sit

FAAB recommender (2) · waivers page (2) · then one each in: core value blend (scope
curve routing, per-player outlier reject, market corridor clamp), confidence buckets,
`rankChange` snapshot, trade verdict math, pick ownership / asset identity, trade
value modes, BDVM, draft-capital auth boundary.

### The 11 that are builds, not repairs

Sized, and deliberately last in the roadmap:

| id | size | what |
|---|---|---|
| W12-F003 | XL | central Buy/Sell Tracker (16 label emitters today, 5 threshold sets, nothing reconciling them) |
| W11-F013 | XL | FAAB context — season timing, roster need, contender posture |
| W23-F017 | XL | human review layer (approve / suppress / annotate / roll back) |
| W28-F001 | L | the 12-team / 14-week schedule generator + NFL-aware optimizer — **no code exists anywhere** |
| W10-F003 | L | perfect-draft optimizer (today: an unconstrained per-player sort) |
| W19-F007 | L | public Money / Constitution / League Media surfaces |
| W04-F011 | M | model version / param-set / as-of provenance stamps |
| W09-F011 | M | untouchable / excluded-player control |
| W08-F011, W01-F006, W16-F014 | S | freshness display, four dead vocabulary names, `src/intel/` docs |

### The 9 blocked by data

Each names its missing artifact: `data/rank_history.jsonl` (W03-F011), `data/bdvm/`
(W13-F005), `data/intel/snapshot_dynasty_main.json` (W11-F015, W16-F012), the sharp
platform ledger (W15-F001), `ktcCrowd` block (W11-F014), plus W10-F012, W14-F010,
W19-F014. None are defects to fix here — they need the input to exist first.

## Resume order

Dependency-correct, from `REPAIR_ROADMAP.md`:

**R13** source-failure visibility → **R14** identity → **R15** scoring duplication →
**R17** public-league franchise filter.

Display, payload, docs and accessibility stay **last** on purpose. `/settings` used to
render the value that *disabled* the measured TE curve as "Default 1.15×"; fixing that
copy before the underlying defect is exactly the inversion the roadmap warns about.

## How to run a repair wave

What worked, and is worth repeating:

1. `REPAIR_PROTOCOL.md` is the agent contract — hand it to every agent verbatim.
2. **One root cause per agent, one commit per root cause**, body saying
   `Closes W##-F###`. The closure tracker parses that sentence-scoped, so naming a
   finding you did *not* fix in the same sentence will over-claim.
3. Every fix ships a test the author **watched fail** against the pre-fix code
   (`git stash push -q <file>` → run → confirm red → `git stash pop -q`). Non-negotiable:
   the entire 1,754-test frontend suite passed *with* a P0 defect in place.
4. Measure before/after where the finding has numbers. Precedents: 627/654/135
   divergences → 0/0/0 · 48.0s → 0.57s · 32-of-35 TEs SELL → 14-of-35 · +187,512 pick
   capital restored.
5. Then `tools/verify_closure.py` to measure, not to assert.

## Two things a future pass must not undo

**The refusals are deliberate.** Some findings were examined and *not* fixed, with
reasons:

- **W08-F003** — the trade-meter non-monotonicity is KeepTradeCut's own published
  algorithm, ported verbatim in `src/trade/ktc_va.py` so our meter matches theirs.
  "Fixing" it breaks the parity the port exists for.
- **W20-F013** — accepting a query param no UI can set converts a missing feature into
  a hidden one.
- **W12-F007** — half its proposed repair was refused: it wanted the verb suppressed on
  low `confidenceBucket`, but that measures source *agreement* while the market gap
  measures source *disagreement*. Category error.
- **W04-F001** — **overturned entirely** under adversarial review. It had confirmed the
  2026-08-04 audit's claim that the Hill-curve gate isn't independent of the boards it
  grades; the gate actually scores a candidate curve against each holdout source's own
  published value shape, never against the blended board. It publishes as refuted with
  the argument attached (`published: false`), deliberately not deleted.

**Severities are the verified ones.** 45 findings went through independent refutation:
13 upheld, 31 rescoped, 1 overturned — and every correction moved *downward*.
`priority` is the verified value; `authoredPriority` preserves the original claim.
Repair what was verified.

## One open defect worth fixing early

**W31-F001** (P2, S) — the running backend rewrites `data/sleeper_last_good.json` and
`data/scrape_state/sleeper_last_success` on every Sleeper poll, and both are **tracked**
(a tracked file ignores `.gitignore`, so the bare `data/` rule misses them). A deployed
checkout goes dirty within minutes of boot, so `git pull --ff-only` on the deploy host
fails or silently stashes.

The write itself is correct — that cache is what lets the app degrade honestly when
Sleeper is unreachable — so the repair is `git rm --cached`, **not** removing the write.
Then check `git ls-files data/` for the same pattern: 8,198 files under `data/` are
tracked, and any the app writes at runtime has this defect.

## State at close

Branch `claude/fantasy-football-master-audit-umvex5`, PR #722. Tree clean, nothing
unpushed, local servers stopped. `ruff` clean. Frontend 1,870 passing.
