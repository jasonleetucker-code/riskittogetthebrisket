# Conflict log

Every contradiction this audit found, adjudicated. Four kinds: documentation against
code, documentation against other documentation, this audit against itself, and the
audit brief against decisions the repository has already made and written down.

A contradiction is only interesting if one side is wrong, or if both sides are right
about different things and nothing in the tree says so. Both outcomes are recorded
below; so is the third one — where a disagreement genuinely survives adjudication and
is left open rather than resolved by preference.

**Sources.** `evidence/W25/conflict-log.csv` (28 rows, C-01..C-28),
`evidence/W25/claude-md-claims.csv` (73 falsifiable claims),
`evidence/W25/measurements.json`, `evidence/W25/reconciliation.json`,
`evidence/W25/supersession-list.csv`, and `findings.json ->
filesWithContradictoryVerdicts` (46 files). Findings registry generated at commit
`fb4a15a0`; repository HEAD at writing is `29589255`; all runtime measurements taken
2026-08-04 against the local stack (API `:8000`, pages `:3000`).

| Part | Conflicts | Wrong side identified | Both right, unmarked | Left open |
|---|---|---|---|---|
| 1. Docs vs code | 24 of 73 CLAUDE.md claims + 3 other-doc | 21 | 3 | 3 (untestable here) |
| 2. Doc vs doc | 10 | 8 | 2 | 0 |
| 3. Audit-internal | 46 files | 45 adjudicated compatible | — | 1 |
| 4. Brief vs repo | 5 | 4 | 1 | 0 |

---

## Part 1 — Documentation against code

`CLAUDE.md` is the repository's authority document. W25 extracted every claim in it
that is falsifiable against the tree or the running stack — 73 of them — and tested
each one. Result:

| Verdict | Count |
|---|---|
| TRUE, unqualified | 40 |
| TRUE with a qualification (right in substance, wrong in a detail) | 9 |
| PARTIALLY TRUE | 9 |
| FALSE | 12 |
| UNVERIFIABLE in this container | 3 |

Forty-nine of 73 hold. The document's failure mode is narrow and consistent: **counts,
byte sizes, line numbers and status verbs drift; references and mechanisms do not.** All
52 file paths cited anywhere in CLAUDE.md exist (52/52, presence loop). Every one of the
twelve Live Value Pipeline mechanism claims verified exact against
`src/api/data_contract.py`.

*Re-run the census:* `python -c "import csv;[print(r['verdict'],'|',r['claim'][:80]) for r
in csv.DictReader(open('docs/master-site-audit/evidence/W25/claude-md-claims.csv'))]"`

### 1.1 The four a reader should act on first

**1. A code comment says a feature is live; the flag registry says it is off, and the
routes agree with the registry.** (C-01, W25-F001, P2)

`server.py:2686-2693`, at the Consensus Edge router mount — the natural place a
developer looks to answer "is this shipping?" — reads: *"the `consensus_edge` feature
flag … default **ON** since 2026-08-04."* `src/api/feature_flags.py:260` reads
`"consensus_edge": False`, under a 20-line comment ending *"Flipping this default back
to True requires the gate in `scripts/validate_consensus_edge_board.py` to pass on a
re-run, not a judgement call. See ADR-023."*

**feature_flags.py is right.** ADR-023 (`docs/consensus-edge/DECISIONS.md:546`) is
titled *"the flag goes back OFF, on the gate that turned it on."* The router comment
recorded the ON flip and was never updated for the same-day revert. Live confirmation:

```
GET /api/consensus-edge/players  -> 503 {"error":"feature_disabled","flag":"consensus_edge"}
GET /api/consensus-edge/top      -> 503
GET /api/consensus-edge/health   -> 503
GET /api/consensus-edge/methodology -> 200   (deliberately reachable; it explains the refusal)
GET /api/consensus-edge/board    -> 404      (no such route — see C-23)
```

User impact: zero, because the flag is correctly off. Maintenance impact: real. Both
statements are still present at HEAD `29589255` — verified by
`sed -n '2684,2695p' server.py` and `sed -n '258,262p' src/api/feature_flags.py`.

**2. The documented payload sizes are each about 3x low, and the test that supposedly
pins them runs on a fixture 71x smaller than production.** (C-07, C-08, W25-F002, P2)

| Measurement | CLAUDE.md:806-807 | Measured 2026-08-04 | Ratio |
|---|---|---|---|
| `GET /api/data` (full contract) | ~4 MB | 11,953,535 b (11.95 MB) | 2.99x |
| `POST /api/rankings/overrides?view=delta` | ~1.25 MB | 3,918,195 b (3.92 MB) | 3.13x |
| the same, gzipped over the wire | ~100 KB | 372,690 b (373 KB) | 3.73x |
| delta as a fraction of full | "~70% smaller" | 66.8% smaller | **correct** |

The *relative* claim survives; all three absolute figures do not.
`tests/api/test_source_overrides.py:635` asserts `delta_bytes < 55_000` on a synthetic
fixture and its own comment at `:631` repeats the wrong figures. That bound is three
orders of magnitude below the production payload, so no test in the suite could have
caught this drift, and the CLAUDE.md sentence claiming the test "pins … byte-size
bounds" reads as an assurance it does not provide.

*Re-run:* `curl -s -b /tmp/audit-cookies.txt -o /dev/null -w '%{size_download}\n'
http://127.0.0.1:8000/api/data`

**3. `docs/ARCHITECTURE.md` tells you to fetch a delta view that does not exist on that
route, and the route accepts the parameter silently.** (C-14, W25-F007, P2)

`docs/ARCHITECTURE.md:101-105` documents the page-load path as
`/api/data?view=delta -> build_rankings_delta_payload(...)`. Measured:
`GET /api/data?view=delta` returns 11,953,535 bytes — **byte-identical to no `view`
parameter at all** — stamps `payloadView: null`, and never calls
`build_rankings_delta_payload`. The delta view lives on
`POST /api/rankings/overrides?view=delta`, which CLAUDE.md:807 documents correctly.

Two defects compound: the architecture doc is wrong, and `/api/data` accepts an unknown
`view` value rather than rejecting it, so a developer following the doc ships 11.95 MB
believing they asked for 3.92 MB and gets no signal either way.

**4. CLAUDE.md explains 239 client-numbered board rows with a limit the board never
reaches.** (C-09, W25-F003, P1 — the highest-severity documentation conflict)

CLAUDE.md:679-681 says the rows that carry a frontend-assigned ordinal are *"players
past the backend's `OVERALL_RANK_LIMIT` (800) — rows the backend deliberately left
unranked."* Measured on the live contract:

| quantity | value |
|---|---|
| `playersArray` rows | 1,092 |
| rows carrying `canonicalConsensusRank` | 740 |
| **maximum stamped rank** | **740** |
| unranked non-pick rows | 239 |
| of those, with `rankDerivedValue == null` | **239 / 239** |

The 800 limit is never reached, so no row is "past" it. Those 239 rows are rows the
board **could not price**. The documented framing turns a pricing gap into a deliberate
depth cutoff, which is the difference between "we stop at 800 on purpose" and "280 rows
have no value and we number them anyway."

### 1.2 The other doc-vs-code conflicts, with verdicts

| # | Claim (doc site) | Code / runtime | Verdict | Finding |
|---|---|---|---|---|
| C-03 | "no endpoint exposes raw Sleeper IDs to the UI" (CLAUDE.md:251) | `GET /api/data?view=app` serves `sleeper.leagueId = 1312006700437352448`, verbatim `config/leagues/registry.json:8`, plus `sleeper.teams[].ownerId` | **FALSE** as written; TRUE for `/api/leagues` only. CLAUDE.md:146 lists `sleeper.leagueId` as a contract field, so the document contradicts itself and the code follows L146 | — |
| C-05 | `meta.sleeperLoadedLeagueKey` is "diagnostic only, when `sleeperDataReady: false`" | On `?leagueKey=dynasty_new`: `sleeperDataReady: true`, `sleeperLoadedLeagueKey: "dynasty_main"`, and the `sleeper` block **is** dynasty_new's (leagueId 1320092771247222784, 10 teams) | **FALSE.** The field's meaning changed to "which league the base contract was built for" when the cross-league overlay landed (`server.py:3262`); the doc still describes the pre-overlay meaning. It now names the wrong league on a valid payload | W25-F005 (P2) |
| C-06 | "`/api/terminal`, `/api/trade/*`, `/api/angle/*` — 503 whenever the loaded contract's leagueKey doesn't match" | `POST /api/trade/finder` and `/api/angle/find` at `dynasty_new` → **503 `data_not_ready`** (doc correct). `GET /api/terminal?leagueKey=dynasty_new` → **200** with dynasty_new's own teams | **PARTIALLY TRUE.** Two of three hold. The code is inconsistent with itself and the doc groups all three | W25-F005 |
| C-12 | "The feature flag `bdvm_engine` defaults OFF" (`docs/research/bdvm-v1/IMPLEMENTATION_REPORT.md:129`, `:388`) | `src/api/feature_flags.py:225` `"bdvm_engine": True`, `_GATE_STATUS` LIVE at `:373`; endpoints answer rather than 503 | **FALSE.** CLAUDE.md names this report as BDVM's authority document, so the pointer leads to the false statement. Confirms prior finding PRIOR-A10-F06 at HEAD | — |
| C-16 | "Next.js 15 + React 19" (CLAUDE.md:20, README.md:8) | `frontend/package.json` → `next 16.2.12`, `react 19.2.8` | **PARTIALLY TRUE.** React right, Next a full major behind. Bumped by `7b21aba4` (2026-08-04), after CLAUDE.md's last internal date of 2026-07-31 | — |
| C-17 | "Single source of truth: `POSITION_ALIASES` in `src/utils/name_clean.py`. All modules import from there." | `src/league_intel/replacement.py:91` `_BASE_POSITION_ALIASES` (own 11-key literal); `src/bdvm/idpshow_projections.py:139` `_POSITION_ALIASES` (adds EDGE/DT/IDL/DI keys `name_clean` does not carry) | **PARTIALLY TRUE.** Two modules keep their own maps. `replacement.py`'s is behaviourally identical on IDP but diverges on K/P/PICK. **No live wrong number was demonstrated** — the invariant is false as stated, the consequence is not proven | — |
| C-02 | "Selenium/requests" as the production scraper's stack (CLAUDE.md:21 **and** :30) | `grep -c selenium 'Dynasty Scraper.py'` → 0; `grep -rln selenium --include=*.py .` → no hits repository-wide. Actual imports at `Dynasty Scraper.py:52-53`: `requests` + `playwright.async_api` | **FALSE, twice.** The "not legacy" half of L30 is correct — `server.py` imports it via importlib and `scheduled-refresh.yml:14` runs it every 2h | W25-F008 (P3) |
| C-10 | `buildRows` cited at `dynasty-data.js:1366` and `:1378` | Actual: `:1391` and `:1403` | **TRUE in substance, wrong line numbers** (25-line drift) | — |
| — | Six structural counts in the Directory Structure block | pages 38→**41**; bridge routes 28→**36**; `src/` modules ~250→**300**; `exports/` 141→**140**; `data/` ~7,900→**8,198**; routes ~100→**99 (correct)** | **FALSE ×5.** All five errors run in the direction that makes the codebase look smaller than it is | W25-F009 (P3) |
| — | `assetsUnpricedByBoard` "— 202 on a real payload" | Measured 186 | **PARTIALLY TRUE.** Mechanism right, illustrative count drifted 8% | W27-F011 (P3) |
| — | KTC↔IDPTradeCalc overlap "475 of 500 rows, median ratio 1.000, p10 0.888, p90 1.054" | Re-measured on the 2026-08-04 contract: overlap **453**, median **0.9877**, p10 **0.8601**, p90 **1.0644**. Both boards do cap at 9999 | **PARTIALLY TRUE.** Direction and magnitude hold within nine days of market drift; the overlap count is 22 low | W08-F014 (P3) |
| — | "the pick-year discount lowers 2027/2028 picks" | The live gate applies it only to synthetic 2029 rows | **Deprecated but still active** — the documented behaviour is not the live behaviour | W02-F007 (P3) |
| — | "`GET /api/rankings/sources` returns the authoritative Python registry" as the runtime lockstep check | The route serves the registry correctly (21 sources, all weight 1.0), but **nothing calls it at runtime** | Route works; the *check* it is named as does not run | W01-F011 (P3) |
| — | The adapter table claims `scraper_bridge_adapter.py` is live in `server.py` | No production caller | **FALSE** for that row; the other three rows of the table are correct and `src/adapters/` contains no phantom modules | W30-F014 (P3) |
| — | CLAUDE.md documents `src/intel/` | It documents none of it — 6,200 lines, seven routes, a page, a daily workflow, two migration scripts | **Missing**, not wrong | W16-F014 (P3) |

### 1.3 What holds

Stated plainly, because a list of only defects is not an audit. Every item below was
tested and reproduced.

- **The Live Value Pipeline description is accurate, stage by stage.** The fixed 500-rank
  percentile reference (`_PERCENTILE_REFERENCE_N = 500`), the value-direct source set
  (`frozenset({'ktcSfTep','idpTradeCalc'})`), α=0.10 shrinkage applied only to IDP and
  picks, the retired MAD penalty (`_MAD_PENALTY_LAMBDA = 0.0`), the 30% single-source
  haircut, the IDP-only corridor clamp (`{"idp": 0.15}` exactly), the two-way boost dict
  (`{"Travis Hunter": "DB"}`) and its call ordering, Phase 3a before the sort and pick
  tethering after it — all twelve verified against `src/api/data_contract.py`.
- **CLAUDE.md flags its own code's stale comment and is right to.** It says the corridor
  clamp's in-code rationale ("contains the IDP calibration runaway") is stale; the
  retired mechanism really is gone (`_apply_idp_calibration_post_pass` absent,
  `config/idp_calibration.json` absent) and the comment really does still say it.
- **The retired canonical-build path is genuinely retired** — all three modules absent,
  `CANONICAL_DATA_MODE` grep-clean.
- **The frontend runtime claims are exact:** a page path on `:8000` returns JSON 404;
  anonymous `/rankings` on `:3000` returns a Next 307 to `/login?next=%2Frankings`;
  `FRONTEND_RUNTIME` / `FRONTEND_URL` survive in `server.py` only as epitaph comments.
- **The D-2 draft-capital repair is real and correct on a foreign league.**
  `GET /api/draft-capital?leagueKey=dynasty_new` → `pricedPickCount: 40`,
  `unpricedPickCount: 40`, `unpricedPickYears: [2027]`, `coveredPickYears: [2026]`,
  `numTeams: 10`, `draftRounds: 4` — matching that league's registry entry, not the
  loaded dynasty_main contract's 12. The 40 priced picks sum to exactly $1200
  (W10-F009).
- **Blend weights are all 1.0** — 21 sources, zero exceptions, live from
  `/api/rankings/sources`. `config/weights/default_weights.json` is read by no production
  module (two tests read it).
- **The sharp cohort has exactly one membership definition** (W15-F015), the trade
  finder's per-market IDP gate works (`marketCoverage {ktcSfTep:132, ktc:18,
  idpTradeCalc:150}`; 60 IDP legs across 40 returned trades), and every engine response
  stamps `valuationMode` including `"market"`.
- **Every path CLAUDE.md cites exists.** 52/52.

### 1.4 Untestable in this container — recorded as a distinct result

Three claims could not be tested here, and that is not the same as failing:

| Claim | Why untestable |
|---|---|
| "the engine answers `status: ok` with 726 players priced and 222 honestly unpriced" (BDVM) | `data/bdvm/` does not exist in this container; endpoints correctly answer `no_projection_snapshot`. Pre-declared non-finding in `AUDIT_PROTOCOL.md`. The *degradation* was verified — no fabricated values were served |
| "Production constants move only via `scripts/model_registry.py promote` + `apply`, run by a human" | All artefacts present; auditing the workflow's commit behaviour needs a CI run. W04-F016 verified the adjacent claim — the refit **structurally cannot** ship constants, and the live curve is bit-exact to the registry champion |
| "unknown `leagueKey` → 400 `unknown_league`; **inactive** → 400 `inactive_league`" | `unknown_league` and the `main` alias verified live. `inactive_league` is unreachable: `config/leagues/registry.json` contains no inactive league |

`POST /api/scrape`'s documented 501 on a non-default `leagueKey` was not probed —
`AUDIT_PROTOCOL.md` forbids POSTing that route.

---

## Part 2 — Documentation against documentation

### 2.1 The ADR namespace collision (C-13, W25-F006, P2)

`ADR-001` through `ADR-015` exist **twice**, in two files, with unrelated subjects:

| id | `docs/league-intelligence/DECISIONS.md` (15 ADRs) | `docs/consensus-edge/DECISIONS.md` (25 ADRs) |
|---|---|---|
| ADR-008 | "replacement levels use endogenous flex allocation" | "the mispricing component earned its place" |
| ADR-015 | "the TE alignment is now a measured basis conversion" | "market movement is the right target" |

A third file, `docs/roster-trade-intelligence/DECISIONS.md`, contains **one** ADR,
numbered 008, with no 001-007 above it.

CLAUDE.md:400-403 states the rule that resolves this — *"the ADR numbers are per-file,
not global … Always cite ADRs with their file"* — and **36 of the 44 ADR citations in
`src/` + `server.py` break it**, across 24 modules. The single most-cited id, `ADR-009`
(14 citations), sits in the ambiguous range.

The rule is correct and unenforceable as written. Prefixing the ids by subsystem
(`LI-ADR-008`, `CE-ADR-008`, `RTI-ADR-008`) makes it greppable.

*Re-run:* `grep -rnoE 'ADR-0[0-9]{2}' --include=*.py src/ server.py | wc -l` → 44;
`grep -coE '^## ADR-[0-9]+' docs/*/DECISIONS.md` → 15 / 25 / 1.

### 2.2 CLAUDE.md against itself

| # | Conflict | Adjudication |
|---|---|---|
| C-02 | L21 calls `Dynasty Scraper.py` "legacy"; L30-31 ten lines later says "Not legacy despite its age" | L30 is right on "legacy"; **both are wrong on Selenium** |
| C-11 | L485-493: BDVM "default **ON** since 2026-07-28 … 2,815-record snapshot … 726 players priced". L550-553, sixty lines later: "no forward-looking statistical projection feed … stays dormant until snapshots exist" | The second paragraph is pre-flip text left in place below its own correction. The flag is genuinely `True` |
| C-03 | L251 "no endpoint exposes raw Sleeper IDs"; L146 lists `sleeper.leagueId` as a contract field | The code follows L146. L251 is false |

### 2.3 Prior audits and status documents

**The D-2 three-way (C-04, W25-F004, P2).** Three in-tree sources give two opposite
verdicts on whether Defect D-2 (`/api/draft-capital` 503 behaviour) is settled:

| Source | Position |
|---|---|
| `CLAUDE.md:188-190` | *"This resolves Defect D-2 … Fixing the doc is the answer, and this is it."* — **CLOSED** |
| `server.py:8270-8271`, `:8303-8305` | *"that is Defect D-2, an open decision, not settled here"*; *"an OPEN product decision"* — **OPEN** |
| `docs/python-coverage-audit.md:269` | *"### D-2 … (UNRESOLVED — documented, not fixed)"* — **OPEN** |

Two of three say open. CLAUDE.md unilaterally closed it without bringing the code
comment or the audit document along. **The behaviour itself is stable, defensible and
verified working** (W10-F009, §1.3 above) — only the status verb disagrees. This is the
cleanest example of the repository's dominant failure mode: the mechanism is right and
the metadata about the mechanism is not.

**The two prior audits are not in conflict (C-21, W25-F010, P1, verified).**
`docs/audits/complete-codebase-audit-2026-07-29.md` says *"Overall health: good."*
`docs/audits/decision-intelligence-audit-2026-08-04.md` says *"No — not at the decision
layer … Safe as a primary decision tool: 1."* They **scope different objects** and both
are true. A falsification test was run (`evidence/W25/reconciliation.json`) with two
pre-declared kill conditions:

- *F1 — same artefact, opposite verdicts?* Not met. The 08-04 audit's own §1 concedes
  the 07-29 object in its own words: *"There is a genuinely well-built spine."* Its own
  registry entry PRIOR-A11-F12 returned "CONFIRMED CORRECT" on twelve consecutive spine
  claims.
- *F2 — is the negative case located inside the spine?* Not met. Six of its seven
  systemic problems sit above the spine (labellers, engines, defaults, monitoring,
  docs). The seventh (#2, holdout boards) is an argument about the benchmark that grades
  the curve, not the curve arithmetic.

**The actual defect is that nothing in the tree marks the relationship** — no scope
line, no commit stamp on the older file, no pointer between them. A reader arriving cold
must reconstruct all of the above before using either.

**One same-artefact contradiction did exist, and chronology settles it (C-18).** The
07-29 audit treats the trade finder as repaired; the 08-04 audit says *"the trade finder
is still offense-only."* The 08-04 audit read commit `9c5d972f` (2026-08-04 06:32 UTC).
Commit `a62af217` — *"Fix the arbitrage finder dropping every IDP asset"* — landed
2026-08-04 13:16 UTC, **6h44m later**, and is not an ancestor of the audited SHA. Both
audits were correct about their own commit; at HEAD the claim is **refuted** (W09-F014,
W27-F010). The registry that finding belongs to is 372 commits behind the last
non-audit HEAD, over a diff of 59 files / 10,541 insertions in `src/` + `server.py`.
This is why `AUDIT_PROTOCOL.md` rule 5 ("reproduce or refute; never inherit") is
load-bearing rather than stylistic.

*Re-run:* `git merge-base --is-ancestor a62af217 9c5d972f; echo $?` → 1 (not an ancestor).

**The 08-04 audit contradicts itself on its own headline statistic (C-19).** "Largest
root-cause category | **documentation mismatch (56)**" at line 30; "25 findings with root
cause documentation mismatch, the single largest category" at line 86; "**single largest
root-cause category (32 findings)**" at line 712. Three numbers for one statistic in one
document. Its registry is the arbiter and was not re-counted here.

**Does this platform have a database? (C-15)** `docs/ARCHITECTURE.md:9` says
"FastAPI → SQLite". `docs/audits/decision-intelligence-audit-2026-08-04.md` says
"**Database** | **None.** No SQL, no ORM, no migrations. JSON files + a user KV store."
**ARCHITECTURE.md is right.** Eight modules use `sqlite3` with `CREATE TABLE` DDL —
`src/api/user_kv.py` (which *is* the "user KV store" the sentence excuses, with
`CREATE TABLE user_state` at `:41`), `session_store.py`, `guest_passes.py`,
`startup_validation.py`, `src/intel/ledger.py`, `src/intel/platform_ledger.py`,
`src/consensus_edge/snapshot.py`, `src/sharp/roster_store.py`. The audit then used "no
database" to declare the brief's SQL scope not applicable.

**The 08-04 audit's repository-state table drifted in every row measured (C-20).**

| Row | Stated | Measured |
|---|---|---|
| `server.py` routes | 82 | 99 (openapi operations) |
| Next pages | 39 | 41 |
| Bridge routes | 30 | 36 |
| Next.js | 15 | 16.2.12 |
| Testing | "**pytest not installed here** — suite not executable" | 6,278 passed / 40 skipped / 0 failed (`evidence/test-results-summary.txt`) |

The last row is the material one: that audit graded 807 systems without being able to
run the test suite, and said so. A reader who skips that line inherits unexercised
conclusions.

### 2.4 Filing and staleness conflicts

| # | Conflict | Adjudication |
|---|---|---|
| C-25 | `docs/audits/math-formula-audit-2026-07-30.md` — filename says 07-30; line 1 says "— 2026-08-04" | Content wins; the filename mis-sorts the file in a directory whose reader depends on chronology |
| C-26 | `UNIMPLEMENTED_BACKLOG.md:24-40` says "much of this file is already superseded … treat them with the same suspicion" — while sitting in the repository root, 41,601 bytes, beside `CLAUDE.md` and `README.md`, with no archived marker | A document whose own header says do-not-trust-me should not sit next to the authority. Archive or delete |
| C-27 | 22 files in `docs/status/`. Exactly **one** carries a STALE banner and one says "superseded"; the other twenty carry no marker — and twenty of the 22 have a latest internal date of 2026-04-28 or earlier, describing a pipeline that predates the Final Framework transition | The two markers imply the other twenty are current. They are not. Per-file disposition in `evidence/W25/supersession-list.csv` |

Census across all 144 tracked markdown files outside `node_modules/`, `frontend/` and
this audit directory: **81 keep, 48 archive, 10 retire, 5 review** — 58 of 144 documents
are superseded, stale or self-declared untrustworthy, carrying 794,145 bytes out of the
working set (W25-F011, P2). Git mtimes are useless for this: history was squashed
2026-08-03, so the census keys on each file's latest *internal* date.

---

## Part 3 — Audit-internal contradictions

`findings.json -> filesWithContradictoryVerdicts` lists **46 files where one workstream
recorded `Implemented and verified` and another recorded a defect on the same path.**
An audit that ships internal contradictions has no standing to report them in the code,
so every one is adjudicated below.

*Re-run:* `python -c "import json;d=json.load(open('docs/master-site-audit/findings.json'));
print(len(d['filesWithContradictoryVerdicts']))"`

### 3.1 What the flag actually detects

The flag is computed at **file granularity** over `codeRefs[].path`. It fires whenever
any two findings cite the same file with different verdict classes — it cannot tell
"verified line 200, defective line 8000" from a real disagreement. That is the right
default for a contradiction detector (better to over-report), but it means the raw count
of 46 is an upper bound, not a result.

Adjudicated: **45 of 46 are compatible**, in four distinct ways. One genuine
disagreement survives and is left open (§3.4).

| class | meaning | count |
|---|---|---|
| **A — different behaviour** | the verified claim and the defect concern different behaviours of the same file | 27 |
| **B — co-citation** | the file is cited as *context* by the defect; the defect lives elsewhere | 6 |
| **C — granularity** | file large enough (`server.py` 99 routes, `data_contract.py` 69 findings) that both verdicts are trivially compatible | 2 |
| **D — axis split** | verified on one request path, league or layer; defective on another. The interesting ones | 10 |
| **E — open** | genuine surviving disagreement | 1 |

### 3.2 The ten axis splits — where the same file is right and wrong at once

These are the adjudications worth reading, because in each case the split *is* the
finding.

**`src/league_intel/te_premium.py` + `src/api/data_contract.py` — verified on the API
path, defeated on the browser path.** W02-F013 and W27-F009 verified the TE basis
conversion exactly: 536 of 536 non-value-direct TE votes reproduce the stamped
contribution from the measured curve; no row carries both `tepBoostApplied` and
`tepNativeCorrectionApplied`; `ktcSfTep` carries neither on all 73 of its TE rows. That
is `GET /api/data`. W03-F001 and W07-F001 (both P0, both **rescoped and upheld** under
adversarial verification) show that every `/rankings` page load POSTs
`{"tep_multiplier": 1.15}`, which gates out the whole ADR-015 block at
`data_contract.py:6939` and substitutes the flat 1.15 the ADR retired — **627 of 740
ranks and 654 tiers differ from the board `/api/data` serves**, with
`isCustomized: false` on the response. Verification sharpened the mechanism: an *empty*
POST body returns a byte-identical board, so the divergence is caused by the **presence**
of the key, not its value. Both verdicts stand. The conversion is correct; the surface
users read does not use it.

**`frontend/app/rankings/page.jsx` — the pipe works, the default payload it carries does
not.** W07-F007 verified end-to-end that source toggles and weight edits on `/settings`
change displayed values, and that the valuation-mode toggle persists across reload. The
same page is the site of W07-F001. Mechanism verified; default input wrong.

**`config/leagues/registry.json` + `tests/league_intel/test_registry_consumers.py` —
right for one league, wrong for the other.** W18-F009 verified `dynasty_main` byte-exact
against its live Sleeper host: 141/141 scoring keys, 58/58 roster slots, 51/51 settings.
W18-F011 shows `dynasty_new` wrong against *its* host on every roster field it models
(rosterSize 24 vs 27, taxiSize 5 vs 3, a `WRRB_FLEX` slot the registry has no vocabulary
for), and no test or snapshot covers it. The test file appears on both sides honestly:
it is what verified one league and what fails to cover the other.

**`frontend/lib/dynasty-data.js` — different layers, both true.** W29-F006 refuted a
prior finding by verifying that the contract's `values` trio (`overall`,
`finalAdjusted`, `displayValue`) is null **exactly** when `rankDerivedValue` is null —
0 rows violate it, 280 rows carry the whole trio null. W11-F022 shows that on the
`view=app` payload `buildRows` takes the legacy-dict branch where
`full: backendValue || rawValues.full`, and `rawValues.full` is the raw scraper
composite — so 4 of 57 roster rows on a live team are priced off a number the canonical
pipeline declined to stamp (Devon Witherspoon 1935, Mason Graham 1874, Malaki Starks
1882, Will Reichard 375). The backend contract is clean; the frontend materializer
backfills from a different pipeline's number.

**`src/model_registry/hill_masters.py`, `config/model_registry/hill_scope_masters.json`,
`.github/workflows/refit-hill-curves.yml` — delivery integrity vs validation coverage.**
W04-F016 verified that the refit workflow **structurally cannot** ship constants and
that the live curve is bit-exact to the registry champion; W04-F015 verified the audit
trail is current (a v3 challenger scored and recorded 2026-08-04). W04-F003 says six of
the eight constants a promotion ships have no out-of-sample score at all. Nothing
overlaps: the pipeline is honest about *what it moves*, and thin on *what it checks*.

**`src/api/draft_capital_fallback.py` — same route, different property.** W10-F009
verified the unpriced-pick arithmetic ($1200 across exactly 40 priced picks, 40 unpriced
emitted with `dollarValue: null`). W00-F001 is about the same route returning 200 to an
unauthenticated caller in 13.2 s. Correctness and exposure are different questions.

**`src/sharp/cohort.py` — the model case: the author reconciled it in the finding
itself.** W15-F015 verified `cohort_members` is the single membership definition, then
wrote: *"The one exception found is a COVERAGE recount, not a second member list — see
W15-F008."* W15-F008 is that recount (`cohort_status` drops the `ffpc_enabled` conjunct).
This is what every one of the other 45 should have looked like.

**`src/ros/__init__.py` — orthogonal axes.** W17-F003 verified the cardinal rule holds
(no ROS value reaches `rankDerivedValue`, the trade calculator or the board, checked in
both directions at runtime). W17-F013 is about 857 MB of history tracked in git.
Nothing to reconcile.

**`src/public_league/records.py` / `awards.py` / `activity.py` /
`trade_grading.py` — mechanism verified, inputs defective.** W19-F009 verified the trade
grader now uses the canonical linear-ratio + KTC-value-adjustment formula and its served
grades reproduce exactly; W19-F010 verified the week-level roster-ownership join the
all-time claims require exists and is used. The defects are upstream data: a hardcoded
retired-owner list that erases 2 of 10 2024 franchises (W19-F001), 224 of 1,708 traded
asset slots silently dropped (W19-F003), eight 2026 awards manufactured from a season
with zero scored games (W19-F004).

**`src/api/feature_flags.py` — the registry is the *correct* side of its own conflict.**
W01-F009 verified `_GATE_STATUS`'s claim that 7 of 15 flags cannot change a response, by
booting a second backend with all seven forced ON and diffing 1,092 contract rows.
W14-F007 verified the consensus_edge flag is off and the code consistent with the
committed "do not ship yet" verdict. W00-F004 and W25-F001 cite this file only because it
is the *other* side of C-01 — where it is right and `server.py`'s comment is wrong.

### 3.3 The remaining 36, in one table

| File | Verified | Defect(s) | Class | Adjudication |
|---|---|---|---|---|
| `server.py` | W09-F014, W11-F019, W13-F010, W14-F006, W15-F014, W16-F011, W16-F016, W27-F010 | 100+ | C | 99 routes in one file. Verdicts do not interact |
| `src/api/data_contract.py` | W02-F008/012/013/014, W03-F002/014, W05-F010/011, W06-F013/014, W13-F008, W14-F004, W27-F009, W29-F006 | 55 | C, D | See §3.2 for the TE-basis split; the rest is granularity |
| `CLAUDE.md` | W10-F009 | 18 | A | One passage verified (the D-2 fallback shape), eighteen falsified. A document is not right or wrong as a unit |
| `src/trade/finder.py` | W09-F014, W25-F010, W27-F008, W27-F010 | 11 | A | IDP *coverage* is fixed and verified; the defects are *selection* — all-1-for-2 output, no dominance pruning, unreachable confidence tier, picks never resolvable |
| `frontend/lib/trade-logic.js` | W08-F009 (A→B/B→A symmetry exact over 40,000 random trades), W08-F010 (KTC parity, 0 diffs over 139 fixtures), W08-F013 (duplicate-asset guard) | 11 | A | Three narrow invariants proven; the defects are in what the values *mean* (value modes, tooltip semantics, pick identity) |
| `src/api/terminal.py` | W06-F013 | 13 | A | The Sleeper-ID re-derivation is correct; news filtering, alert cooldowns and roster strength are not |
| `frontend/app/trade/page.jsx` | W08-F013 | 7 | A | Duplicate protection works; pick search, pick identity and value-mode comparability do not |
| `src/sharp/market.py` | W14-F006, W16-F001 | 6 | A | Product separation verified; emptiness, per-player concentration and per-request rescoring are separate defects |
| `src/sharp/score.py` | W15-F015 | 8 | B | Membership *selection* verified; the defects are in the scoring components and the evidence they read |
| `src/sharp/platform_records.py` | W15-F015 | 5 | B | Same — selection correct, record-building incomplete |
| `src/sharp/service.py` | W15-F014 | 4 | A | Route registration present and triple-guarded; `cohort_status`'s weaker gate and per-GET rescoring are elsewhere in the file |
| `src/intel/ledger.py` | W16-F002 (counting rules correct under adversarial fixtures) | 7 | A | The ledger counts correctly; nothing downstream can reach half of what it stores |
| `src/intel/service.py` | W16-F001 | 6 | A | Separation verified; counting semantics, window receipts and disconnection are distinct |
| `src/intel/signals.py` | W16-F002 | 2 | A | Counting verified; `sample_confidence`'s documented calibration is unsatisfiable, and two shipped fields render nowhere |
| `src/bdvm/engine.py` | W13-F008/009/010/011 | 2 | A | Four mechanisms verified (market isolation, aging/survival split, `E[max(0,X−R)]`, ceiling cap at exactly 9999); the defects are calibration and strategy separation |
| `src/bdvm/market.py` | W12-F015, W13-F008, W13-F014 | 3 | A | Market isolation is structural; W12-F008's "KTC on both sides" is about a *different* comparison downstream |
| `config/bdvm/params_v1.json` | W13-F014 (STRONG_BUY reachable, liquidity direction corrected) | 4 | A | Two prior findings refuted; the file still self-declares as un-backtested priors |
| `config/bdvm/pick_outcomes_v1.json` | W13-F013 (38 distinct EVs across 48 slots — prior "all deep picks identical" refuted) | 2 | A | Table is differentiated, nobody has validated it, and no live route exposes the distribution |
| `src/bdvm/news_events.py` | W21-F002 (speculation clamp real — every news event emits `sigma_mult` only) | 2 | A | The clamp holds; the *filter* upstream admits roundups, and the event contract carries 6 of 11 fields |
| `src/consensus_edge/score.py` | W12-F015, W14-F005, W14-F007 | 1 | B | Verified to refuse rather than fabricate; W30-F012 is about `unified_signal_engine.py`'s self-description, citing this file as one emitter it fails to arbitrate |
| `frontend/app/consensus-edge/page.jsx` | W14-F005 (every served number reproduces from the payload) | 2 | A | Arithmetic verified; 28 of 73 buy-side rows are labelled Buy directly above text saying fair value is below market |
| `src/league_intel/cross_market.py` | W27-F008 | 1 | A | The comparability claim reproduces; the ±5% angle-finder gate being narrower than the boards' measured dispersion is a different quantity |
| `src/league_intel/config.py` | W18-F009 | 1 | A | Config byte-exact; the drift filter omits one bookkeeping counter |
| `src/trade/waiver.py` | W11-F020 (JS↔Python bid parity, 0 divergences over 800 cases) | 4 | A | The two implementations agree; what they agree *on* saturates |
| `frontend/lib/waiver-logic.js` | W11-F020 | 3 | A | Same parity; the filter-dependent denominator and the `values.full` fallback are separate |
| `frontend/lib/league-analysis.js` | W30-F021 (pick term sign corrected — prior finding refuted) | 6 | A | One classifier fixed; the defect is that six of them ship at once |
| `src/public_league/trade_grading.py` | W19-F009 | 3 | A | Formula canonical and reproducing; dropped asset slots and three coexisting ports are separate |
| `src/api/team_assignment.py` | W28-F002 (all 12 managers reproduced to the point) | 3 | A | Computation verified; the rookie draft-capital tier is structurally dead and the 15-point threshold leaves 5 of 12 managers with one team |
| `frontend/app/league/sections/team-assignment.jsx` | W28-F002 | 3 | A | Same, plus a header comment claiming a 30-minute cache against a 300-second TTL |
| `frontend/app/intel/page.jsx` | W16-F001 | 1 | A | Product separation verified; the page is reachable from no navigation |
| `frontend/app/rankings/page.jsx` | W07-F007, W13-F012, W29-F006 | 9 | D | See §3.2 |
| `docs/consensus-edge/DECISIONS.md` | W27-F008 (ADR-025 not in tension with the comparability claim) | 2 | B | Authority in two findings (ADR-023 is the correct side of C-01), defendant in one (the namespace collision) |
| `.github/workflows/refit-hill-curves.yml` | W04-F016 | 1 | A | Cannot ship constants (verified); opens undeduplicated GitHub issues (W23-F009). Unrelated |
| `src/model_registry/hill_masters.py` | W04-F016 | 1 | A | See §3.2 |
| `config/model_registry/hill_scope_masters.json` | W04-F015 | 1 | A | See §3.2 |
| `src/api/draft_capital_fallback.py` | W10-F009 | 1 | A/D | See §3.2 |

### 3.4 The one that stays open

**`src/league_intel/te_premium.py` — is the flat 1.10 for TEP-native sources a defect?**

W27-F009 (`Implemented and verified`, P3) established the facts: the eleven non-TEP
sources take the measured rank-dependent curve (`dlfSf` 1.2091–1.4403, `fantasyProsSf`
1.2092–1.5915, `flockFantasySfRookies` up to 1.6367), and the four registry-flagged
TEP-native sources take exactly **1.1000 on every row**. W30-F019
(`Duplicate or conflicting implementation`, P2) reports the same facts and calls them a
defect: *"one concept has two maths decided by source class."*

**No fact is in dispute.** The disagreement is over the verdict, and it is a real one.
CLAUDE.md's own position is that the flat 1.10 is deliberate — *"TEP-native sources keep
the flat 1.10 — only base ↔ tepp is measured"* — which is either an honest scope
limit (W27's reading) or an unmeasured prior wearing the same name as a measured curve
(W30's reading). Settling it needs a measurement nobody has taken: the TEP-native uplift
against a TE++ anchor, the way the base→tepp curve was measured. **Left open.** Both
findings ship.

### 3.5 Internal corrections — never quote an authored severity as fact

45 of 431 published findings went through adversarial verification. The results:

| verdict | count |
|---|---|
| upheld | 13 |
| **rescoped** | **31** |
| **overturned** | **1** |
| unverified (no verification pass run) | 387 |

Severity moved on 23 of the 45: `P1→P2` ×14, `P0→P1` ×5, `P0→P2` ×2, `P1→P3` ×2 —
**every single move downward.** The authored priority in `evidence/verify/*.json` is the
pre-verification copy; `findings.json` carries the verified one. Two examples of why the
distinction matters:

- **W04-F003** was authored P1 ("six of the eight Hill constants a promotion ships have
  no out-of-sample score"); verification confirmed the mechanism and rescoped it to
  **P2** — a real gap in validation coverage, not a live wrong number.
- **W27-F002** was authored P0 ("trade suggestions cannot propose a defensive back");
  verification confirmed the defect at HEAD (0 of 96 DBs survive the global top-150 cut)
  and rescoped it to **P1**, because the same panel renders `6 suggestions · 16/57
  matched` — a disclosure that the analysis covers a minority of the roster. It does not
  name the DB blind spot, which is why the finding survives; it defeats the P0 "no
  warning shown" clause.

**One finding was overturned outright and withdrawn from publication.** W04-F001 claimed
that all four "held-out" boards in the Hill promotion gate are registered live blend
sources, so the benchmark is not independent. The reproduction ran and its literal output
was correct; the inference was not. `holdout.py:251-265` loads each holdout board's **raw
CSV** and takes the RMSE of the Hill curve against that source's own published value
curve — it never reads the blended board, `rankDerivedValue`, or any pipeline output.
Registry membership changes nothing about the quantity computed, and the inference runs
backwards: a curve that reproduces FantasyCalc's published shape converts FantasyCalc's
rank vote *more* faithfully, not more circularly. Marked `published: false`, priority
dropped P1→P3, retained in `findings.json` so the correction is auditable. A P3 residual
was recorded from the same investigation: `holdout.py` excludes `ktcSfTep` by name for
KTC-derivation but includes `fantasyNavigatorSf`, which the same registry labels
`correlation_group='ktc'` — measured to have no effect on the criterion, so a policy
inconsistency, not a defective benchmark.

*Re-run:* `python -c "import json;d=json.load(open('docs/master-site-audit/findings.json'));
print(d['byVerificationVerdict'], d['severityDriftUnderVerification'])"`

---

## Part 4 — The audit brief against the repository

Five places where the brief's stated requirements conflict with something the repository
had already decided, measured, or documented.

**4.1 `AUDIT_PROTOCOL.md` instructs a re-measurement using a method it declares void
(C-22, P2).** Lines 36-49 establish the topology rule: a hand-rolled proxy was tried and
**abandoned** (`evidence/page-probe-via-proxy-INVALID.json` retained and invalid), and
*"any page-level observation not taken through request interception is void."* The
non-findings table at lines 98-99 then says: *"404s on `/api/*` when a page is loaded
from `:3000` | Wrong topology … **Re-measure on `:3001`**"* and *"Only a finding if it
reproduces on `:3001`."* The `:3001` rows are leftovers from the abandoned method — a
workstream following the table would produce void evidence. Both statements are still
present at HEAD. They should read "via request interception."

**4.2 The protocol's consensus-edge non-finding names a route that does not exist
(C-23, P3).** `AUDIT_PROTOCOL.md:91` reads *"`/api/consensus-edge/*` returns 503."*
Measured across all five real routes: `/board` → **404** (no such route), `/players`
503, `/top` 503, `/health` 503, `/methodology` → **200**. The repository made a
deliberate decision the protocol did not capture: `/methodology` stays reachable while
the feature is disabled, because it explains the refusal. A workstream probing `/board`
gets a 404 and could misreport it as a missing feature.

**4.3 The protocol pins a HEAD the audit has moved past (C-24, P3).**
`AUDIT_PROTOCOL.md:50` records HEAD `e96c06ef`. Actual HEAD is `29589255` — **8 commits
later**, all of them touching only `docs/master-site-audit/` (verified: no file outside
that directory appears in `git log --name-only e96c06ef..HEAD`). Harmless for code
claims, but it means "at HEAD" in one shard and another can differ. Cite SHAs
explicitly.

**4.4 The brief mis-states the `docs/status/` inventory (C-28, P3).** The brief said
*"~139 docs exist; 22 in `docs/status/` date to 2026-03-14 and three carry STALE
banners."* Measured: **144** tracked `.md` files outside `node_modules/`, `frontend/`
and this directory; `docs/status/` holds 22 files of which **three** date to 2026-03-14
and **one** carries a STALE banner. The `UNIMPLEMENTED_BACKLOG.md` half of the brief is
exactly right. Directionally correct, numerically off — recorded because a finding built
on the brief's numbers rather than re-measured ones inherits the error.

**4.5 The brief asks the audit to reconcile against a 531-finding prior registry the
repository has already moved past.** The registry is a claim set against commit
`9c5d972f` (2026-08-04 06:32 UTC), 372 commits behind the last non-audit HEAD, over a
`src/` + `server.py` diff of 59 files / 10,541 insertions / 759 deletions. At least one
Critical claim in it was remediated **in response to the audit itself**, 6h44m after the
SHA it read (§2.3, C-18). The repository's decision — reflected in
`AUDIT_PROTOCOL.md` rule 5, "reproduce or refute; never inherit" — is the correct one and
this audit followed it: of 431 published findings, 140 confirm a prior finding, 90
partially confirm, 13 **refute** one, 9 do not reproduce, 5 supersede, and 174 are new.
The conflict is not with the brief's intent but with any reading of it that treats prior
findings as inherited facts.

---

## What to fix, shortest first

| # | Fix | Cost | Conflict |
|---|---|---|---|
| 1 | Delete the "default ON" sentence from `server.py:2686-2693`; point at `feature_flags.py` | one comment | C-01 |
| 2 | Replace CLAUDE.md's `OVERALL_RANK_LIMIT (800)` sentence with the measured cause: rows the backend could not price, 239 of 1,092 | one sentence | C-09 |
| 3 | Correct the three payload figures and the stale comment in `test_source_overrides.py:631` | four numbers | C-07/08 |
| 4 | Point `docs/ARCHITECTURE.md:101-105` at `POST /api/rankings/overrides?view=delta`, and make `/api/data` **400** on an unknown `view` | two lines + one guard | C-14 |
| 5 | Fix the two `:3001` rows in `AUDIT_PROTOCOL.md`'s non-findings table to say "via request interception" | two cells | C-22 |
| 6 | Adjudicate D-2 once, in one place; make the other two sites point at it | one decision | C-04 |
| 7 | Prefix ADR ids by subsystem (`LI-`/`CE-`/`RTI-`), keep old numbers as aliases, sweep the 36 code citations | mechanical | C-13 |
| 8 | Generate the six Directory Structure counts in CI, or delete them | six shell lines | W25-F009 |
| 9 | Execute `evidence/W25/supersession-list.csv`: archive 48, retire 10, triage 5 | one pass | C-26/27 |
| 10 | Add to each prior audit header: object audited, SHA, pointer to the other | four lines | C-21 |
