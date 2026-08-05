# Prior-Audit Reconciliation

**What this settles:** the repository holds two recent audits that reach opposite-sounding
verdicts, with nothing in the tree marking their relationship, plus a 531-finding registry
that this audit was forbidden to inherit. This document reports which prior claims survived
contact with a running server, which did not, and which could not be tested.

Audited commit `e96c06ef`. Findings source: `docs/master-site-audit/findings.json`
(431 published + 1 withdrawn, `generatedAt` 2026-08-05T01:05:56Z, merge commit `fb4a15a0`).
Prior index: `docs/master-site-audit/evidence/prior-index.json`
(sha256 `3db6b393…c1d1c`, 531 findings, 26 areas).

---

## 1. The headline reconciliation

Two audits. Two verdicts. No cross-reference between them anywhere in the tree.

| Audit | Verdict, verbatim |
|---|---|
| `docs/audits/complete-codebase-audit-2026-07-29.md` §1 | "**Overall health: good, and better than the surrounding documentation suggested.**" … "Can the current rankings and values be trusted? **Yes, with one qualification.**" |
| `docs/audits/decision-intelligence-audit-2026-08-04.md` §1 | "Is the analytical architecture coherent? **No — not at the decision layer.**" … "Safe as a primary decision tool: **1** — the raw retail market values themselves." |

### The hypothesis W25 tested

That they scope **different objects**: the value **spine** (one canonical value, one blend
path, one materializer) versus the **decision layer** built on top of it (buy/sell labels,
trade engines, bid recommendations, alerts) — and are therefore both true.

Falsification conditions were declared before the evidence was gathered
(`evidence/W25/reconciliation.json`):

- **F1** — the two audits assert opposite verdicts about the *same named artefact*, with no
  scope difference to appeal to.
- **F2** — the 08-04 negative verdict rests materially on defects located *inside* the spine
  the 07-29 audit graded.

### Result: the hypothesis survives, on both conditions

**F1 not met.** The 08-04 audit concedes the 07-29 object in its own words — "There is a
genuinely well-built spine: one canonical value (`rankDerivedValue`), one blend path, a
correctly-reasoned scoring-profile/league-key split, a real and largely-held rule against a
frontend ranking engine" — and scopes its verdict inside the verdict sentence ("No — not at
the decision layer"). Its own registry entry `PRIOR-A11-F12` walked `CLAUDE.md`'s Live Value
Pipeline stage by stage and returned "CONFIRMED CORRECT" on twelve consecutive spine claims,
filed at severity Informational. W25-F010 reached the same twelve verdicts independently
before opening the index.

**F2 not met.** Of the 08-04 audit's seven systemic problems, six are located above the spine.
Exactly one — problem #2, the holdout-independence claim — sits on it, and this audit
**refuted** it (§4).

**One genuine same-artefact contradiction exists**, and it resolves on chronology rather than
scope. The 07-29 audit treats the trade finder as repaired (§1, problem 2: "two scale errors …
Fixed"); the 08-04 audit says "the trade finder is still offense-only (the regression
`CLAUDE.md` says was fixed)". Both were right about their own commit:

```
git merge-base --is-ancestor a62af217 9c5d972f; echo "exit=$?"   # 1 = fix NOT in the audited commit
git log -1 --format='%H %ad %s' --date=iso a62af217
git log --oneline 9c5d972f..e96c06ef | wc -l
```

| Fact | Value |
|---|---|
| Commit the 08-04 audit read | `9c5d972f`, 2026-08-04 06:32 UTC |
| Commit that fixed the finder | `a62af217` "Fix the arbitrage finder dropping every IDP asset", 2026-08-04 **13:16 UTC** |
| Is the fix an ancestor of the audited SHA? | No (`--is-ancestor` exit 1) |
| Commits between the audited SHA and this audit's HEAD | **372** |

At HEAD the finder claim is refuted at runtime, not by reading code
(re-run: `curl -s -b /tmp/audit-cookies.txt -X POST http://127.0.0.1:8000/api/trade/finder -H 'Content-Type: application/json' -d '{"myTeam":"Jason","opponentTeams":["all"]}'`):

```
marketCoverage {'ktcSfTep': 132, 'ktc': 18, 'idpTradeCalc': 150}
valueSource     rankDerivedValue
positions in returned trades  DB 26, DL 23, TE 21, QB 19, RB 14, LB 11, WR 6
```

### The seven systemic problems, adjudicated

Every row is this audit's **verified** position. Where a verifier corrected the workstream
author's severity, the corrected value is what appears — authored values are preserved in
`findings.json` as `authoredPriority` and are not quoted here as fact.

| # | 08-04 systemic claim | This audit | Evidence |
|---|---|---|---|
| 1 | No output validated for accuracy; core constants tuned against a stability metric | **Confirmed in substance, narrowed.** The four tuning reports do optimize day-to-day board churn, and `reports/backtest_blend_params.md:8` really does say "Lower = more stable = probably better-calibrated". The sharpest sub-claim — three of five constants contradict their own report "with no note anywhere" — is false for all three; each carries an in-code justification. Backtests additionally replay today's 21-source registry against 2026-07-14 snapshots that only ever saw 3 sources. | W04-F008 (P3), W04-F009 (P2) |
| 2 | The benchmark grading the core curves is not independent of them | **REFUTED.** See §4. | W04-F001, overturned |
| 3 | Buy/sell direction unreliable at the mechanism level | **Confirmed and strengthened.** 32 of 35 top-250 TEs read SELL and every top-250 SELL is a TE; the verifier added the mirror artifact at QB (46 BUY vs 3 SELL of 71) and measured all 15 non-retail sources ranking TEs 31–62 ordinal places worse than KTC — unanimity that only a basis offset explains. | W12-F002 (**P0**, upheld), W03-F006 (P2) |
| 4 | Flagship engines silently degraded or inert | **Split.** Finder: **refuted** (above). Trade suggestions: **confirmed** — zero suggestions for 8 of 12 live teams, no diagnosis in the payload. TE-premium curve unreachable from the UI: **confirmed and raised** to P0. BDVM "never run in production": **not testable here** — `data/bdvm/` is absent from the container, all four routes answer `no_projection_snapshot` and every UI surface degrades correctly. | W09-F001 (P1), W07-F001 (**P0**), W13-F005 (Blocked by data) |
| 5 | Missing data resolves optimistically instead of abstaining | **Split.** Confidence raised by missing sources: **confirmed** — dropping one real source raises the published label on 237 of 679 rows. Unpriced players promoted into the Value column as raw scraper composites: **refuted** (§4). A new instance found instead: unpriced players draw $22–$25 FAAB recommendations. | W03-F004 (P1), W29-F006 (refuted), W11-F002 (P2) |
| 6 | The monitoring that should catch this is broken | **Confirmed, all three named mechanisms.** Each was rescoped downward from the authoring workstream's P1 to P2 — they are ops defects, not user-facing wrong numbers. | W23-F001, W23-F002, W23-F003 |
| 7 | Documentation asserts as settled fact things the code contradicts | **Confirmed and extended.** Its own count of this category is one of the things it got wrong — see below. | W25-F004, W25-F008, W25-F009, W25-F011, W02-F007 |

### Does this audit's own evidence support the split reading?

**Mostly yes.** Six of this audit's nine P0 findings sit unambiguously in the decision layer:
draft slot accounting (W10-F002), FAAB position calibration (W11-F001), the Edge buy/sell
column (W12-F002), the ROS playoff simulator (W17-F001), ROS buyer/seller direction
(W17-F002), and the /league Trade Deadline board (W20-F002). And the spine's arithmetic was
verified positively in five independent places, not merely left un-criticised:

| Finding | What was proved |
|---|---|
| W02-F012 | The blend is deterministic and exactly reproducible — an independent reimplementation matches `_blendedValueUncapped` on 800/800 rows; two in-process rebuilds hash identically |
| W02-F013 | Single-source haircut, TE basis conversion, pick tethering and board coherence all exact on the live board |
| W02-F014 | Missing data abstains; the only fabricated values on the board are 12 synthetic 2029 picks, whose provenance is disclosed in the payload and rendered |
| W03-F002 | The delta view round-trips every `_DELTA_PLAYER_FIELDS` field exactly — 0 mismatches over 1,092 rows × 43 fields |
| W05-F010 | All 21 registered ranking sources have a live fetcher, a fresh CSV and real votes on the served board |
| W04-F016 | The refit workflow structurally cannot ship constants, and the live curve is bit-exact to the registry champion |

**But the reading needs one boundary condition the 07-29 audit did not state.** Three of the
nine P0s are a single defect located exactly where the spine hands off to the client:
`SETTINGS_DEFAULTS.tepMultiplier = 1.15` makes every page load POST an explicit TE override,
which gates out the ADR-015 basis curve at `data_contract.py:6939`. The verifier's kill
attempt sharpened it: posting the *same number the contract already reports as its default*
reprices the board, because the gate keys on the presence of the key, not its value (an empty
body `{}` returns a byte-identical board).

| Measure | Value |
|---|---|
| Rows differing between the rendered board and `GET /api/data` | **786** (627 rank, 654 tier, 135 value) |
| Worst single value error | Tyler Conklin, **-21.2%** |
| Pages affected | 10 (every page calling `useDynastyData()`) |
| Warning shown to the user | none — the "Custom Mix" badge gates on `isCustomized`, which the backend stamps **false** for a TEP-only override |

So "there is exactly one live value path" is true of the code and false of the product: the
server-side engines price from `rankDerivedValue` on `/api/data` while the screen shows a
different board, and nothing on either surface says so. (W03-F001 P0, W07-F001 P0, W08-F001 P0
— all upheld or rescoped-and-sustained under adversarial verification.)

A second, smaller strain: **W02-F001** (P1, confirmed from `PRIOR-A11-F00`) is a genuine units
error inside the blend — IDP-only sources are handed a combined-pool percentile and scored on
an IDP-slice Hill master, so they vote at 46–48% of the IDP market at the same rank, measured
over 605 source votes. The verifier upheld the mechanism and found a *second* compounding
scale defect the finding did not name. That is spine arithmetic, and the 07-29 audit's "the
blend is mathematically sound" verdict does not cover it.

**Conclusion.** Neither audit should be overruled. 07-29 answers "is the number computed
correctly, and only once?" — yes, with two measured exceptions (the IDP branch, and the
client boundary). 08-04 answers "does the verb printed next to that number deserve a user's
money?" — mostly no, and six of its seven systemic problems survive. What is actually defective
is that both sit in `docs/audits/` with no scope line, no commit stamp on the older one, and no
pointer between them.

### Collateral: five things measured about the 08-04 audit itself

These matter because they bound how much of its registry can be taken at face value.
Re-run: `evidence/W25/reconciliation.json` records each with its command.

| Claim in the 08-04 audit | Measured here |
|---|---|
| "documentation mismatch (56)" (line 30) vs "25 findings" (line 85) vs "(32 findings)" (line 712) | Its own registry says **56**. The other two figures are wrong. |
| "82 routes", "39 pages", "30 bridge routes", "Next.js 15" | **99 route operations over 97 paths** (`evidence/openapi.json`), **41** pages, **36** bridge routes, **next 16.2.12** |
| "pytest not installed here — suite not executable" | The suite runs clean in this container: **6,278 passed / 40 skipped / 0 failed** in 32m10s (`evidence/pytest-full.txt`) |
| "Database: None. No SQL, no ORM, no migrations" — used to declare the brief's SQL scope not applicable | **8 modules** import `sqlite3` with `CREATE TABLE` DDL, including `src/api/user_kv.py` — the "user KV store" the same sentence excuses |
| Severity field casing | Inconsistent across the 531 records (`Critical` ×27 + `critical` ×16, etc.), so any count over the registry must be case-folded |

Re-run the last three:

```bash
tail -1 docs/master-site-audit/evidence/pytest-full.txt
grep -rl 'import sqlite3' --include=*.py src/ server.py
.venv/bin/python -c "import json,collections; d=json.load(open('docs/audits/decision-intelligence-audit-2026-08-04.registry.json')); \
 w=lambda o:[s for k,v in (o.items() if isinstance(o,dict) else []) for s in ([v] if k=='severity' and isinstance(v,str) else w(v))] \
   if isinstance(o,dict) else [s for v in o for s in w(v)] if isinstance(o,list) else []; print(collections.Counter(w(d)))"
```

---

## 2. The crosswalk

Every published finding carries a `priorFinding.relation` assigned **after** the workstream did
its own analysis (AUDIT_PROTOCOL rule 5). These are read off `findings.json`, not restated from
any brief.

### This audit's 431 findings, by relation to the prior registry

| Relation | Findings | Meaning |
|---|---|---|
| `new` | **174** | No prior finding covers it |
| `confirmed` | **140** | Prior claim independently reproduced at HEAD |
| `partial` | **90** | Prior claim holds in part; scope, magnitude or cause corrected |
| `refuted` | **13** | Prior claim does not reproduce at HEAD (§4) |
| `not-reproducible` | **9** | Could not be reproduced; recorded as a negative result (§3) |
| `superseded` | **5** | The code the prior described no longer exists; a different finding replaces it |
| | **431** | |

### Coverage of the 531 prior findings

| | Count | Of 531 |
|---|---|---|
| Prior findings that received a verdict | **207** | 39% |
| …cited only as *adjacent but different* by a `new` finding | 8 | 2% |
| …never referenced by this audit | **316** | 60% |

Coverage was deliberately weighted toward the prior audit's own high-severity tail:

| Prior severity (case-folded) | In registry | Given a verdict | Coverage |
|---|---|---|---|
| Critical | 43 | 26 | 60% |
| High | 130 | 59 | 45% |
| Medium | 201 | 73 | 36% |
| Low | 147 | 43 | 29% |
| Informational | 10 | 6 | 60% |

Two notes on how to read these:

- **207 distinct prior IDs are covered by 257 findings** — one prior claim frequently splits
  across workstreams (`PRIOR-A20-F06` and `PRIOR-A04-F01` are each touched by three). 23 prior
  IDs carry more than one relation; 22 of those pair a `confirmed` with a `partial` from
  different workstreams, and in every case they address different legs of the same prior claim
  rather than disagreeing. The one apparent conflict — `PRIOR-A13-F14`, refuted by W04-F015 and
  partial by W23-F009 — is also two legs: the "no registry entry since 2026-07-29" leg is
  refuted, the "an alert nobody acts on" leg is extended.
- **60% of the prior registry was not tested.** That is a scope statement, not a verdict.
  Nothing in this document says an untested prior finding is wrong.

Re-run the whole crosswalk:

```bash
.venv/bin/python - <<'PY'
import json, collections, re
F = [f for f in json.load(open('docs/master-site-audit/findings.json'))['findings'] if f.get('published')]
P = {f['id'] for f in json.load(open('docs/master-site-audit/evidence/prior-index.json'))['findings']}
V = {'confirmed', 'partial', 'refuted', 'not-reproducible', 'superseded'}
print(collections.Counter(f['priorFinding']['relation'] for f in F))
seen = collections.defaultdict(set)
for f in F:
    rel = f['priorFinding']['relation']
    if rel in V:
        for p in re.split(r'[^A-Z0-9-]+', f['priorFinding'].get('match') or ''):
            if p in P:
                seen[rel].add(p)
allp = set().union(*seen.values())
print({k: len(v) for k, v in seen.items()}, 'distinct:', len(allp), 'untouched:', len(P - allp))
PY
```

### Verification pressure, and what it did to severities

45 of the highest-impact findings went to independent refuters instructed to default to
refuted. Verdicts: **13 upheld, 31 rescoped, 1 overturned**
(`evidence/verify/verdicts-*.jsonl`). Twenty-two severity corrections were applied and **all 22
moved downward** — `P0→P2` ×2, `P0→P1` ×5, `P1→P2` ×14, `P1→P3` ×2. Five of those twenty-two
are in the model-registry workstream alone (W04-F002/F003/F005/F008/F009, each authored P1,
each verified P2 or P3).

That pattern is the reason this document quotes no authored severity as fact, and it is worth
carrying to the earlier audits: unverified audit severities in this codebase run hot.

```bash
.venv/bin/python -c "import json; F=[f for f in json.load(open('docs/master-site-audit/findings.json'))['findings'] if f.get('published')]; \
 print([(f['id'],f['authoredPriority'],f['priority']) for f in F if f.get('authoredPriority') and f['authoredPriority']!=f['priority']])"
```

### The 5 superseded prior findings

The prior claim's *code* is gone; a different finding stands in its place.

| Prior | This audit | Position |
|---|---|---|
| `PRIOR-A11-F07` (Medium) — two-way boost "overrides the whole pipeline with a plain three-source mean and is live at +115%" | W02-F008 | Override characterisation holds; the **magnitude does not**. Aggregation is now `count_aware_mean_median_blend` over ladder-translated values; measured boost is **+43.7%** (Travis Hunter, 3062 → 4401, rank 89) |
| `PRIOR-A23-F07` (High) — `/api/movers` anchors on the first snapshot present, so a "14d" label can be a 2-day delta | W03-F011 | The code was rewritten: the anchor now resolves by date and the response reports `windowRequested` vs measured window. **Not runtime-verifiable here** — `data/rank_history.jsonl` does not exist in this container. Blocked by data |
| `PRIOR-A22-F02` (High) — realized-points route never fetches defensive stats, so IDP players return zero weeks | W18-F004 | Superseded by a larger defect: the route returns `unmapped_player` for **every** player of every position, because `sleeper_block.get("players")` names a key the block never has. Stat selection is never reached |
| `PRIOR-A21-F01` (High) — public trade grades apply linear thresholds to an α=1.65-transformed gap | W19-F009 | The cited code no longer exists (`grep -rn '_GRADE_ALPHA\|1.65' src/public_league/` returns nothing). Grading moved to `trade_grading.py`; served grades recomputed independently and matched byte for byte |
| *(no prior match)* | W17-F006 | Supersedes ADR-007's characterisation of the best-ball optimizer as greedy: it is **exact**. 360 randomized brute-force trials across three slot sets including non-laminar ones, zero deviations |

---

## 3. What I could not reproduce

Nine findings carry `relation: not-reproducible`. Non-reproduction is a result. Each names what
was looked at and what was found instead.

| # | Prior claim | What was looked at | Result |
|---|---|---|---|
| 1 | `PRIOR-A10-F06` (medium) — a stale BDVM doc claiming the engine defaults OFF | W01-F009 tested the adjacent, stronger claim instead: `feature_flags._GATE_STATUS` says 7 of 15 flags cannot change a response. A **second backend was booted on :8001** with all seven forced ON and 1,092 contract rows diffed against a defaults boot | The gate-status claim is **true**: 0 rows changed `rankDerivedValue`, 0 changed `canonicalConsensusRank`, 0 fields appeared or disappeared. The only difference in the 12 MB payload was `rankChange`, which a third cold boot proved is a function of history depth since boot. The one stale detail found is cosmetic ("of 13 registered flags" while `_DEFAULTS` holds 15) |
| 2 | `PRIOR-A11-F04` (High) — the pick-year discount is applied on top of vendor values that already price the year | W02-F007 read `_apply_pick_year_discount_to_blend` and counted discounted rows on the live board | **Fixed at HEAD.** The stage gates on `_SYNTHETIC_FAR_FUTURE_PICK_NAMES`; exactly 12 rows carry `pickYearDiscount`, all 2029, all 0.53. No 2027/2028 row is discounted and the market's term structure is preserved (2027 Early 1st 7049 > 2026 Pick 1.02 6160). What survives is documentation drift in `CLAUDE.md` |
| 3 | `PRIOR-A22-F03` (High) — the realized-points route "emits a full array of 0.0-point weeks" | W06-F003 called the route on four real Sleeper ids (5859, 4984, 9509, 7567) and read `/api/status.idMappingCoverage` | The described behaviour is **downstream of a bail that always fires**: all four return `unmapped_player`, coverage 0.0%. The route never reaches the scoring stage for any player, so there are no zero-point weeks to emit. The upstream defect is confirmed and upheld at P1 |
| 4 | `PRIOR-A00-F17` (low) — draft-capital team totals sum workbook column Q while displayed dollars come from column L | W10-F016 opened `CSVs/Draft Data.xlsx` and compared `Q45:Q116` against `L2:L73` | The code divergence is **exactly as described and currently a no-op**: the two columns are identical in all 72 rows (max abs difference 0.0) and both sum to 1200.0. No defect is observable today. Recorded as `Unverifiable` rather than dismissed — the latent divergence is real |
| 5 | `PRIOR-A15-F10` (Medium) — `range.ceiling_p85` escapes the 0–10000 scale, up to 19,843 | W13-F011 ran the BDVM engine on a 699-player proxy-baseline snapshot and took the max | **Not reproducible.** Max `ceiling_p85` is exactly **9999**, 0 rows over cap. `to_trade_value` now applies a strictly increasing squash (not a `min()` clamp) that every scale output passes through, so the fix is structural rather than snapshot-dependent |
| 6 | `PRIOR-A17-F13` (Low) — `server.py`'s intel section header still documents the retired `trendScore` sort | W16-F016 ran `grep -n 'trendScore' server.py` | **False at HEAD.** Zero hits in `server.py`. The string survives only in `src/intel/signals.py` and `__init__.py`, in both cases as an explicit account of what was removed and why |
| 7 | `PRIOR-A19-F06` (High) — ROS `freshness_multiplier`/`staleFlag` are structurally unreachable | W17-F004 called `/api/ros/health` and rendered `/tools/ros-data-health` | The **aggregate-level** freshness classifier is correct and current: `aggregatedAt` 2026-08-04T18:21:21Z, 4.9 h old against a 2026-08-04 board, all 5 sources `ok`, classified `fresh`. **The per-source multiplier claim was not tested** — that leg is untested, not refuted |
| 8 | `PRIOR-A02-F01` (high) — two share-link producers feed the trade builder with opposite side semantics, so a trade opened from history simulates backwards | W08-F009 tested the *math* rather than the share-link producer: 20 real trades across four shapes plus 40,000 random 1–3 vs 1–3 trades | The verdict math is **exactly order-independent** — `gap(A,B) == -gap(B,A)` on 20 of 20 and 0 asymmetries in 40,000; the Monte Carlo endpoint independently reports `symmetryCheck` drift 0.0004 with `enforced: true`. **The share-link side-assignment claim was not probed and is neither confirmed nor refuted**; what is established is that any observed reversal must come from side assignment, not from the gap computation |
| 9 | 07-29 audit, problem 1 — "source-weight sliders did nothing" | W07-F007 drove the real `/settings` UI in a browser under the protocol's request-interception topology | **Does not reproduce.** Unchecking "Include KeepTradeCut SF-TE++" writes to `localStorage`, POSTs `{"ktcSfTep":{"include":false}}` and visibly changes the board (Josh Allen 9,988→9,987; the #4 slot flips from Ja'Marr Chase to Drake Maye). Server-side the same body moves 491 of 1,092 values and 582 ranks; disabling `idpTradeCalc` moves 782; `dlfSf` weight 3.0 moves 222 |

Two of these — #7 and #8 — are **partial** non-reproductions and are labelled as such in
`findings.json`. Neither should be read as clearing the prior claim.

Separately, and distinct from non-reproduction: **11 findings are `Blocked by data`** and
**3 are `Unverifiable`**. `data/bdvm/`, `data/intel/`, `data/rank_history.jsonl` and the
platform ledger DB do not exist in this container, so BDVM accuracy, intel signals and mover
deltas could not be tested at all. Those are gaps in this audit's coverage, not clean bills of
health.

---

## 4. What I refuted

### The lead: the Hill-curve benchmark IS independent of the boards it grades

The 08-04 audit's **second systemic problem** — "The benchmark that grades the core curves is
not independent of them … **Caps confidence at 49**" (`PRIOR-A13-F00`, Critical) — is the only
one of its seven located on the value spine. This audit's W04 workstream **confirmed** it,
reproduced it at runtime, and strengthened it with a leg the prior audit had not found. An
independent verifier then **overturned it outright**.

W04-F001 is published in `findings.json` with `published: false` and is the single
`refutedAndWithdrawn` record in the merge. The verdict is
`evidence/verify/verdicts-B6.jsonl`.

**What the author proved (and it is true):** all four boards in `OFFENSE_HOLDOUT_SOURCES`
(FantasyCalc, OTCFFB, PFKDynasty, FantasyNavigator) are registered entries in the live
`_RANKING_SOURCES` blend, weight 1.0, scope `overall_offense`. Five of the six *training*
boards are too. No board on either side of the split sits outside the pipeline.

```bash
.venv/bin/python -c "import sys;sys.path.insert(0,'.');import src.api.data_contract as dc;from src.model_registry import holdout;\
reg={s['key'] for s in dc._RANKING_SOURCES};cfg=dc._SOURCE_CSV_PATHS;f=lambda p:[k for k,v in cfg.items() if isinstance(v,dict) and v.get('path')==p];\
print([(l,f(p)[0] in reg) for l,(p,_c) in holdout.OFFENSE_HOLDOUT_SOURCES.items()])"
# [('FantasyCalc', True), ('OTCFFB', True), ('PFKDynasty', True), ('FantasyNavigator', True)]
```

**Why the conclusion does not follow — four arguments, each measured:**

1. **The gate never reads the board.** `holdout.py:251-265` loads each holdout board's **raw
   CSV**, converts it to `(percentile, value/top × 9999)` pairs via `_percentile_pairs`
   (`:131-145`), and takes the RMSE of the candidate Hill curve against *those* pairs
   (`:161-162`). The criterion is a shape comparison between a candidate `(c, s)` pair and a
   source's own published value curve. It never touches `rankDerivedValue`, the blend, or any
   pipeline output. "The benchmark is not independent of the board it grades" is a category
   error: the thing graded is a **curve**, and the board the finding means is downstream of and
   invisible to the criterion.

2. **The inference runs backwards.** Those four sources vote via rank → percentile → Hill. A
   curve that reproduces FantasyCalc's published *value shape* converts FantasyCalc's rank vote
   into a value closer to what FantasyCalc actually says — a **more** faithful translation of
   the vote, not a more circular one. Overfitting to the six training boards remains fully
   detectable, because the four holdout CSVs have their own decay shapes whether or not they
   are also registry entries.

3. **The strongest leg is measurably false.** The finding's sharpest point was that
   `fantasyNavigatorSf` carries `correlation_group='ktc'` with a registry comment saying its
   values are KTC-derived — so a KTC derivative sits in the holdout set while `holdout.py:69-73`
   excludes `ktcSfTep` for exactly that reason. Both facts are true. But the verifier tested
   contamination on **the quantity the gate actually computes** — RMSE of each board's
   normalized percentile→value curve against KTC's:

   | Board | Role | RMSE vs KTC | rows |
   |---|---|---|---|
   | Fitzmaurice | train | 659.9 | 299 |
   | PFKDynasty | **holdout** | 881.6 | 400 |
   | DraftSharks | train | 1001.2 | 400 |
   | YahooBoone | train | 1304.7 | 400 |
   | DynastyDaddy | train | 1391.9 | 367 |
   | FantasyCalc | **holdout** | 1504.5 | 399 |
   | OTCFFB | **holdout** | 1591.3 | 347 |
   | DynastyNerds | train | 1821.8 | 294 |
   | **FantasyNavigator** | **holdout** | **1933.2** | 400 |

   The alleged KTC derivative is the **furthest** board from KTC of all nine — further than
   every training board. Its per-source RMSE is the worst in every recorded verdict (1185.15 on
   v1, 1148.53 on v2). Provenance is KTC-derived; the value *shape*, which is the only thing
   scored, is not. It is the strictest board in the set, not a smuggled training source.

4. **The claim under test was a strawman.** The finding asserted "the word held-out is used
   throughout to mean independent". `holdout.py:33-40` says the opposite in its own words:
   "It does NOT measure accuracy against reality. Every holdout source is another consensus
   market, correlated with the training sources by construction … There is no ground truth."
   That text is not just a comment — it is serialized into every recorded verdict as
   `_semantics.doesNotMeasure` (`:193-203`) beside `criterionName: "mean_per_source_rmse"`. The
   finding's own proposed repair option (b), "rename the criterion to what it measures — cross-market
   shape agreement", is **already done** in the module and in
   `config/model_registry/hill_scope_masters.json`.

**Blast radius, corrected:** the withdrawn finding claimed 1,092 players / 100 routes / 38 pages
while its own `userImpact` said "nothing a user sees changes today". Corrected: **0 players, 0
routes, 0 pages**. The gate is a CI quality gate on a script-only path with a human promote step
(ADR-008, `docs/roster-trade-intelligence/DECISIONS.md`).

**What survives:** a P3 policy-consistency note. `holdout.py` excludes `ktcSfTep` by name for
KTC-derivation but includes `fantasyNavigatorSf`, which the same repo labels
`correlation_group='ktc'`. Measured to have zero effect on the criterion — an inconsistency in
stated policy, not a defective benchmark.

**And the context that makes this worth stating plainly:** the gate is live and has moved
production constants. `config/model_registry/hill_scope_masters.json` records v1 (criterion
819.73) retired, v2 (787.84) promoted 2026-07-29, v3 (775.05) rejected 2026-08-04. Had the
contamination been real, the impact would have been serious. It is not real.

### The other 12 refutations

Each refutes a specific prior claim at HEAD `e96c06ef`. Prior severity is the 08-04 audit's own
label, case-folded, quoted as their claim and not as this audit's assessment.

| Prior (severity) | Prior claim | This audit's verified position | Finding |
|---|---|---|---|
| `PRIOR-A14-F00` (Critical) | "The trade finder receives no position data on the live path … still offense-only" | **Refuted at runtime.** `server.py:6188` passes `contract=` into `find_trades`; `positions_from_contract()` rebuilds the map from `playersArray`. Gated pool = 300 assets (150 offense-market + 150 IDP-market); `marketCoverage {ktcSfTep:132, ktc:18, idpTradeCalc:150}`; 60 of 120 assets in returned trades are IDP. Fixed by `a62af217`, 6h44m after the audited SHA | W09-F014, W27-F010, W25-F010 |
| `PRIOR-A14-F01` (Critical) | "The finder's IDP-blindness warning cannot fire" | **Refuted — I made it fire.** Deleting `idpTradeCalc` from a deep copy of the players dict makes `find_trades` emit "No IDP asset carries an IDPTradeCalc value, so this result is offense-only." It stays correctly silent on live data because `idp_priced` is 150, not 0 | W09-F014 |
| `PRIOR-A14-F02` (Critical) | "The finder applies KTC's package Value Adjustment to the market side only" | **Refuted.** The current `finder.py` imports no VA at all; `angle.py` applies `_adjusted_pair_totals` symmetrically to both sides (lines 778 and 798) | W09-F014 |
| `PRIOR-A01-F00` (critical) | "The Value column silently switches to the raw scraper composite for **260 rows**, 158 of them larger than the deepest genuinely-priced player" | **Refuted, 260 → 0.** `data_contract.py:9229-9236` writes `overall`, `finalAdjusted` and `displayValue` together in one branch gated on `rdv is not None and rdv > 0`. Live: **0** rows have `displayValue` null while `overall`/`finalAdjusted` are set; 280 rows have the whole trio null. Devin Bush — the prior's own example — reads all three null. Simulating `_materializePlayerArrayRow` over all 1,092 rows: 0 rows would display a value with a null `rankDerivedValue`. The prior cited `exports/latest/dynasty_data.js` — the **scraper output**, where `_finalAdjusted` is present on all 1,074 rows — not the contract | W29-F006 |
| `PRIOR-A00-F04` (critical) | "Sleeper-derived draft capital fabricates 52% of the board on live data" | **Refuted.** The hardcoded 7000/4000/2000/1200-by-round table is gone. Live non-default league: 40 priced 2026 picks summing to **exactly 1200.0**, 40 unpriced 2027 picks with `dollarValue: null` + `isUnpriced: true` and real Sleeper ownership retained; `teamTotals` sums to exactly 1200; no fabricated value anywhere in the payload. Its secondary claim (the 503 does not fire on a league mismatch) is **true but deliberate** — the documented D-2 resolution | W10-F009 |
| `PRIOR-A04-F00` (critical) | "The live FAAB bid is a share of a **draft pick's** value — every bid ~2.4× too low" | **Refuted.** `server.py:5130` now skips pick-class rows when choosing the pool anchor. The free-agent-only maximum is 1908.0 (Marlin Klein, TE) and the endpoint's own baseline row reads "start at $21" = `100 × (0.05 + 0.25×1.0) × 0.70` against a 1908 denominator. The prior's *remedy prediction* was accurate | W11-F019 |
| `PRIOR-A04-F04` (medium) | "`computeFaabHint` is not a faithful port — 10.8% of the grid returns different dollars" | **Refuted.** Both implementations derive all three tiers from the unrounded aggressive figure and both spell out half-up (`floor(v+0.5)`). Executed over budgets 50/100/200/1000 × 200 share steps: **0 divergences in 800 cases**, and `tests/fixtures/faab_bid_parity_cases.json` now pins it | W11-F020 |
| `PRIOR-A05-F12` / `PRIOR-A23-F08` (high) | "MoversPanel labels risers as buy-low and fallers as sell-high — both inverted" | **Refuted.** `MoversPanel.jsx:196-215` reads "Risers — sell-high candidates" / "Fallers — buy-low candidates", carries a comment recording the correction, and the rendered DOM confirms it. **A larger problem replaces it**: the corrected polarity is now the exact opposite of the signal engine on the same page (Movers: riser → sell-high at a 15-rank threshold; `signal-engine.js` `buy.uptrend_controlled`: +3 ranks → BUY). Same page, same input, opposite verbs | W12-F009 |
| `PRIOR-A03-F00` (high) | "`scoreTeamTiers`' pick term has the wrong net sign: picks **increase** contender score by +0.1" | **Refuted.** `league-analysis.js:1128` reads `const depthValue = totalValue - starterValue - pickValue;` so the net coefficient is **−0.1** as documented, verified numerically (Jason's score reproduces to 66,760.3 only with the −0.1 net). **The page-level problem it sat inside is not fixed**: `/rosters` still shows two contradictory orderings of the same 12 teams on one screen — Jason #1 in the power table, #5 "Mid-Tier" in the cards 400px below, differing for 10 of 12 teams | W20-F007, W30-F021 |
| `PRIOR-A10-F01` / `PRIOR-A09-F01` (high/medium) | "The contract publishes the wrong confidence-bucket rule; it misclassifies a third of the board" | **Refuted.** The live `methodology.confidenceBuckets` block publishes the percentile rule as primary with the 30/80 pair nested under `fallbackRule` and labelled "NOT the live /api/data path". Recomputing every stamped bucket from the row's own `sourceRankPercentileSpread`: **0 mismatches over 709 rows**. The 33.3% figure reproduces (34.0% here) but it is the rate at which the *legacy* rule would disagree with the live one — a difference between two rules, not a misclassification | W03-F014 |
| `PRIOR-A15-F02` (High) | "`STRONG_BUY` is structurally unreachable in production" | **Refuted.** 10 players carry `STRONG_BUY` on a real 699-player board, and `test_strong_buy_is_reachable_without_gap_history` sits beside the persistence test. Note this does **not** make the signal layer healthy — the same board reads `STRONG_SELL` on 81.5% of players (W13-F003) | W13-F014 |
| `PRIOR-A15-F07` (High) | "`liquidity` increases with market **disagreement** — inverted semantics" | **Refuted.** The config reads `liquidity = clip(base − dispersion_coeff × dispersion, lo, hi)` with base 1.0, coeff 1.6, and a comment stating the sign was corrected. Live: A.J. Brown dispersion 0.0225 → liquidity 0.964, matching `clip(1.0 − 1.6×0.0225, 0.2, 1.0)` to 3 decimals | W13-F014 |
| `PRIOR-A15-F12` (Medium) | "The `/rankings` and `/draft` Fund-gap columns strip the proxy flag" | **Refuted by code read.** `buildBdvmIndex` carries `anyProxy` per entry; the renderer appends `*` and a tooltip reading "PROXY: fundamental is the reconstructed baseline … not a real projection". **Could not be confirmed in the DOM** — the container has no BDVM snapshot, so the column is correctly absent | W13-F012 |
| `PRIOR-A13-F14` / `PRIOR-A07-F14` (Informational/medium) | "No registry entry recorded since 2026-07-29 / no refit audit-trail entry since 2026-07-28" | **Refuted.** `hill_scope_masters.json` carries a version 3 fitted 2026-08-04T09:11:58Z, status `rejected`, with a full holdout block and the verdict "improvement +22.4 does not clear the 25-point margin", committed by the workflow as `f828a9da`. The other leg — "6 of 13 scheduled runs failed" — is a GitHub Actions history claim this container **cannot check** and is left unverified | W04-F015 |
| `PRIOR-A09-F07` (medium) | "`values.displayValue` is read by two modules and produced by none" | **Refuted.** It is produced at `data_contract.py:9233` and is non-null on 812 rows. Only `_canonicalDisplayValue` is unproduced, and nothing reads it any more | W29-F006 |
| `PRIOR-A14-F14` (Medium) | "The finder's rationale keys on an empty position string, producing 'fills  need'" | **Refuted.** The live rationale reads "sheds DL surplus, fills DB need" | W09-F014 |
| `PRIOR-A14-F20` (Medium) | "CLAUDE.md states the finder's per-market gate, IDP warning and unpriced-asset count as verified facts; all three disagree with the code" | **Two of three refuted.** The per-market gate and the IDP warning are correct as documented. Only the third survives: `assetsUnpricedByBoard` is **186** live, against 189/202 in the docstring | W09-F014, W27-F011 |

Counted as relations: **13 findings against 11 distinct prior IDs**, with 9 further prior IDs
refuted as secondary claims inside those findings' notes.

Two of these refutations deserve emphasis because they were *critical* in the prior audit and
are *zero* here: `PRIOR-A01-F00` (260 rows → 0) and `PRIOR-A00-F04` (52% of a board fabricated →
0 fabricated values, exact $1200 normalization). Both were code-read claims. Both fall to a
runtime measurement.

---

## 5. How to read the two prior audits going forward

1. **Neither is superseded, and neither should be deleted.** 07-29 is a spine audit. 08-04 is a
   decision-layer audit. Six of 08-04's seven systemic problems survive independent
   reproduction; 07-29's core architectural claims survive too, and were re-verified positively
   here in six separate measurements. The correct fix is a two-line scope header on each and a
   pointer between them — the actual defect is that nothing in the tree marks their
   relationship.

2. **The 08-04 registry is a claim set against `9c5d972f`, 372 commits behind this audit's
   HEAD** (59 files / +10,541 / −759 across `src/` and `server.py`). At least one Critical
   finding was remediated 6h44m after the SHA it read, *in response to* the audit. Any of its
   531 findings must be re-measured before it is acted on. `AUDIT_PROTOCOL.md` rule 5
   ("reproduce or refute; never inherit") is load-bearing here, not stylistic.

3. **Its severities and structural counts run hot, and its coverage statement understates its
   own reach.** It reported the suite as non-executable ("pytest not installed here") and
   declared the SQL scope not applicable on a repository with eight `sqlite3` modules — so
   whatever it concluded about 807 systems, it concluded without running a test. Its repo-state
   table is stale in every row measured here. Its own headline root-cause count appears three
   times with three different values.

4. **Case-fold before counting.** Its severity field is inconsistently cased across the 531
   records (`Critical` ×27 + `critical` ×16, `High` ×83 + `high` ×47, etc.). Any tally that
   does not case-fold is wrong by construction.

5. **60% of the prior registry is still untested.** 316 of 531 prior findings were never
   referenced by this audit, and 8 more only as adjacent-but-different. Untested is not
   cleared. Coverage was weighted toward severity (60% of Criticals, 45% of Highs), so the
   untested remainder skews Medium/Low — but it includes 17 Criticals and 71 Highs.

6. **The pattern that produced all of this is still live.** 58 of 144 tracked markdown
   documents are superseded, stale or self-declared untrustworthy, and only two of the 22 files
   in `docs/status/` say so (W25-F011). Adding audit documents without retiring the ones they
   supersede is how a repository arrives at two unmarked, apparently contradictory verdicts in
   the same directory.

---

*Every relation count in this document is derived from `findings.json` by the snippet in §2 and
is reproducible without a model in the loop. Where a verifier corrected an authoring
workstream, the verified position is what is reported; authored severities are preserved in
`findings.json` as `authoredPriority` and are quoted nowhere as fact.*
