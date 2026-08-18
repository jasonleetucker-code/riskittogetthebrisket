# C1-U9 — multi-format dynasty source archive

**Unit:** `C1-U9` · **Rows:** `C1-SRC-01`, `C1-SRC-02`
**Owners:** `_RANKING_SOURCES` (game-type gate) · `src/source_archive/` (archive)
**Delivered:** 2026-08-17 · **Branch:** `claude/c-series-c1-u9` (stacked on `claude/c-series-c1-u8`)
**State:** `CLOSED-PENDING-PROD` — see §7.

---

## 1. `C1-SRC-02` was recorded COMPLETE and was not enforced

The manifest read **"COMPLETE for current sources"**, owner `_RANKING_SOURCES`, evidence
"existing tests". Verified against the code before writing anything:

- **no `game_type` field** anywhere in `_RANKING_SOURCES`, `server.py` or `Dynasty Scraper.py`;
- **no fail-closed behaviour**, because there was no state that could be unknown;
- **no test** — not one asserting the sources are dynasty, and not the regression fixture the
  spec's §16 item 8 explicitly asks for.

The dynasty-only property *was* true of the 21 registered sources — because whoever registered
each one hand-verified it **in a comment**. That is an unenforced convention: append an entry
with a CSV path and it votes on the next build, whatever board it came from.

So the row is **corrected to what was actually true**, and the guarantee is implemented for the
first time. This is the opposite of "blindly redoing SRC-02": the verification the owner asked
for is what showed there was nothing to redo.

### What now exists

A closed vocabulary — `DYNASTY`, `REDRAFT`, `REST_OF_SEASON`, `WEEKLY`, `BEST_BALL`, `KEEPER`,
`UNKNOWN`. Non-dynasty values are representable **on purpose**: a board identified as redraft is
a different fact from one nobody has checked, and quarantining the first is only possible if it
can be named.

Every one of the 21 sources carries `game_type: DYNASTY` **and `game_type_evidence`** — the
*how*, not just the label, because a claim nobody can re-check is the comment this replaced.
The evidence is source-specific and drawn from each entry's own documented endpoint, e.g.:

- `fantasyCalc` — "fetched with `isDynasty=true`; **the same endpoint serves redraft when that
  flag is false**, so the flag is the proof"
- `fantasyProsSf` — "`/nfl/rankings/dynasty-superflex.php` — FantasyPros exposes dynasty and
  redraft as **distinct URLs**; this is the dynasty one"
- `draftSharks` — "`/dynasty-rankings/…`; DS's ROS boards are a different route and are
  deliberately **NOT registered** (see the unregistered `draftSharksRosSf.csv`)"

Three of the 21 would be *wrong* under a provider-level assumption. That is the point.

### The gate

`_validate_source_game_types_invariant()` runs **at import**, beside its sibling
`_validate_value_based_sources_invariant()`, and refuses — naming the offending keys — a source
that declares no game type, one outside the vocabulary, one that is not `DYNASTY` (including
`UNKNOWN`), or a `DYNASTY` claim with no evidence.

**Raising rather than filtering** is deliberate. Silently dropping the offender from the blend
would leave a redraft board sitting in the registry *looking* registered while quietly not
voting, and the next reader would have to run the pipeline to learn which sources are real. A
registry that cannot be trusted by reading it is the condition this unit ends.

Proven to fire, not merely present:

```
REDRAFT  refused: are not DYNASTY: [('ktcRedraft', 'REDRAFT')]…
UNKNOWN  refused: are not DYNASTY: [('mystery', 'UNKNOWN')]…
absent   refused: declare no game_type: ['silent']…
no evid  refused: declare DYNASTY with no game_type_evidence: ['bare']…
```

`gameType` and `gameTypeEvidence` are exported on `get_ranking_source_registry()`, so a consumer
can check the claim instead of trusting the registry silently.

---

## 2. `C1-SRC-01` — the archive

`CSVs/site_raw/*.csv` is **overwritten in place on every fetch**, and the `data/raw*` trees have
been frozen since April 2026. No per-run version of any source board survives. §2 of the spec:
paired format observations "have option value that cannot reliably be recreated later".

The specific opportunity, measured: **KTC's four TE-premium states already ship in every scrape
response.** `Dynasty Scraper.py::_ktc_extract_tep` receives
`superflexValues: {value, tep, tepp, teppp}`, reads `tepp`, and discards three. Capturing the
ladder is a parse change, **not a new fetch**.

`src/source_archive/` stores one row per board, keyed
`(provider, endpoint, format_key, run_id, captured_date)`. The `run_id` is what makes variants
captured in one cycle **paired evidence** rather than snapshots from unknown different moments
(§8) — without it, a TE++-minus-Off comparison measures market drift as well as TE premium.
Native units are kept verbatim and never overwritten with our normalized value (§5).

Re-archiving an identical board is a no-op; the same identity with different content is
surfaced, never silently applied — the posture `src/history/store.py` and
`src/acquisition/store.py` already take.

**Why its own store rather than `src/history`:** that package's identity index is
`(asset_key, lane, source_key, observed_date, …)` with **no variant dimension**, so an
alternate-format board could only ride it by overloading `source_key` into a compound string —
making a format variant indistinguishable from a distinct source at exactly the layer that must
never confuse them.

---

## 3. The three hard rules, enforced structurally

**Archive ≠ production eligibility.** `ARCHIVE_ELIGIBLE` and `PRODUCTION_ELIGIBLE` are separate
sets and the latter is **empty** — the statement that archiving granted no production
capability. The real vote gate is membership of `_RANKING_SOURCES`, and a test asserts
`data_contract` **does not import** `src.source_archive`, so an archived variant is not one edit
away from voting. Not "nobody calls it yet" — that is the state C1-U8's audit already caught
being mistaken for a guarantee.

**KTC's four states are ONE provider family.** KTC applies its TE-premium values algorithmically
from one base crowd value (§4.2), so the four are calibration anchors on a single opinion.
Tested: every variant declares `provider_family: ktc`, and archiving the whole ladder leaves the
independent-family set that confidence and Consensus Edge count **unchanged**. Reopening the B10
circularity through a new door is the specific failure this guards.

**`UNKNOWN` ≠ `DYNASTY`, at the archive too.** `archive_board` applies the same fail-closed rule.
A board we cannot prove is dynasty does not become dynasty by being stored — and keeping one
"for diagnostics" inside the *dynasty* archive is how it later gets used.

---

## 4. Board inertness — measured

`scripts/golden_board.py` before and after, then `board_diff --expect-no-value-change`:

```
rows 1111 -> 1111 · VALUES: 0 moved · RANKS: 0 changed
ASSERTION OK: no value changed.
```

Expected, and worth measuring rather than assuming: the registry gained two descriptive fields
and a gate, and the archive is not wired to anything that prices.

---

## 5. Guards this unit had to not trip

`test_source_provenance.py::test_the_registry_is_the_only_place_a_family_is_named` (no provider
name literal inside the blend — so family membership stays *declared*, never hard-coded) ·
`tests/ros/test_isolation.py` (registry constants byte-stable) · `test_source_registry_parity.py`
(all weights 1.0; the Python/JS mirrors agree) · `test_family_aware_aggregation.py`. All pass.

---

## 6. Deliberately not done

No scraper change yet — the KTC ladder capture is a follow-up that writes into this store; the
store and its boundary had to exist and be proven inert first. No format-normalization model, no
learned response curves, no universal-league adapter, no production activation of any variant
(§19 forbids all of them during collection). No capability registry with the four availability
states — the archive records what was *captured*; declaring what each provider *exposes* is a
separate audit. **No change to `_build_site_pick_map`** — the 2029 year-substitution defect is
C1-U6's, recorded in `docs/picks/C1_U6_D1_FABRICATED_FUTURE_YEAR_ANCHORS.md`.

---

## 7. Why `CLOSED-PENDING-PROD`

The gate and the archive are proven on this box; nothing has yet run against a live scrape.
Production verification, on the deployed merge SHA:

1. Server boots — the import-time gate passes against the live registry.
2. `GET /api/rankings/sources` returns `gameType: "DYNASTY"` and non-empty `gameTypeEvidence`
   for all 21.
3. A scrape completes and the board is unchanged (`board_diff --expect-no-value-change`).
4. When the KTC ladder capture lands: four boards per run sharing one `run_id`, all
   `provider_family: ktc`, and the independent-family count still unchanged.

### 7a. Production verification record — 2026-08-18

Run against `https://chaseupside.com` (public endpoints; `/api/data` is 401 from the
integration session, so anything needing an authenticated payload is marked below rather
than guessed at).

| # | check | result | evidence |
|---|---|---|---|
| 1 | server boots, import-time gate passes against the live registry | **PASS** | `/api/rankings/sources` and `/api/status` both 200. The gate runs at import; a failure would prevent the process serving at all, so a served response IS the evidence |
| 2 | all 21 sources report `gameType: "DYNASTY"` with non-empty `gameTypeEvidence` | **PASS** | 21 sources returned; non-`DYNASTY` count **0**, empty-evidence count **0** |
| 3 | a scrape completes and the board is unchanged | **PARTIAL** | a post-deploy scrape completed at 17:32:33→17:34:35Z, `overall_status: complete`, `partial_run: false`, no failed/timed-out sources, and `contract.health` reports `ok: true` with `structuralErrors: []` / `sourceHealthErrors: []` over 1109 players. **Strict value-inertness is NOT re-measurable here**: `board_diff --expect-no-value-change` needs a pre-deploy production board snapshot, and none was taken. It was measured on this box pre-merge (§ inertness); that is what stands, and saying so is more useful than presenting a healthy scrape as if it were the same statement |
| 4 | KTC ladder capture | **N/A** | not landed yet; the check is written for a future unit |

Item 3's residue is a *process* gap worth naming, because it will recur for every unit whose
proof is "the board did not move": the snapshot has to be captured **before** the deploy, and
nothing currently does that. Same shape as `scripts/backtest_perfect_draft.py --record-snapshot`,
and the same lesson — no code recovers an observation nobody made.
