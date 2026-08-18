# Analyst claim schema and stance taxonomy

**Owner module:** `src/analyst/` (`stance.py`, `claim.py`)
**Owner spec:** `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` §4.16, §4.19, §4.20
**Tracked as:** T-NEW-10 (`OWNER_REQUESTED_TODO_SPEC_INDEX.md`) — *REQUIRED METHODOLOGY REFINEMENT*
**Status:** schema only. No ingestion, no consumers yet — by design, see §6.

---

## 1. Why the schema exists before the pipeline

The owner's sequencing is that the claim is defined before anything starts
storing claims. That is not tidiness. The questions that decide whether a take
may be used at all —

- *is this about dynasty, or redraft?*
- *did the analyst say that, or did we infer it?*
- *is this the same take he made last week, or a new argument?*

— are **not recoverable from a row written without their answers**. The
transcript may be gone, the episode may be re-cut, and a paraphrase becomes
indistinguishable from a quote the moment it is stored as one.

So this unit defines the record and its invariants, and stops.

## 2. Two vocabularies, deliberately separate

| | |
|---|---|
| `SourceLabel` | what the source said, in its own words — `BUY / SELL / HOLD / FADE / BREAKOUT / SLEEPER / STASH / INSUFFICIENT_SIGNAL` |
| `Stance` | the canonical category the platform reasons in — the nine of §4.16 |

Both are stored. Collapsing the label into the stance would lose the
distinction §4.16 spends a sentence protecting: *"SLEEPER is an undervalued
player with a meaningful upside/start case, not merely any deep bench name."*

`SLEEPER` therefore maps to `BUY`, **not** to `STASH` — demoting a real
start-case call would be as wrong as promoting a stash.

## 3. The rule the taxonomy exists to enforce

> **"STASH must not create false consensus with true conviction BUY calls."**

Held **structurally**, not by convention. Every stance declares a
`ConvictionClass`:

| class | stances |
|---|---|
| `conviction` | STRONG_BUY, BUY, SELL, STRONG_SELL |
| `conditional` | CONDITIONAL_BUY, CONDITIONAL_SELL |
| `speculative` | **STASH** |
| `neutral` | HOLD |
| `none` | NO_SIGNAL |

`tally()` returns a `StanceTally` that counts by class, and **there is
deliberately no `buys` accessor**. A caller wanting "how many are bullish" has
to choose `conviction()`, `conditional()` or `speculative()` — and say so at
the call site, where a reviewer can see the choice. A single combined counter
is exactly how the two would get summed, so the shape does not offer one.
Pinned by `test_there_is_no_combined_bullish_count_to_misread`.

A stash still reports on the buy side. It is separated, not discarded.

## 4. What a claim carries, and what each field prevents

| field | prevents |
|---|---|
| `SourceRef.analyst_id` / `content_id` / `platform` | an unattributable take entering the pool at all — all three are required |
| `provenance` | inference being presented as a quote. `quote` is refused on anything but `TRANSCRIPT_VERBATIM` |
| `game_type` | a redraft take reaching a dynasty conclusion. Defaults to `UNKNOWN`, and **only `DYNASTY` is dynasty evidence** |
| `asset_side` | offense-only evidence pricing an IDP asset — the same limitation the external FAAB market carries |
| `conditions` | "buy only if cheap" flattening into "buy". A conditional stance **cannot be constructed** without its trigger |
| `thesis_id` → `thesis_key` | one analyst's repeated take becoming several votes |
| `said_at` vs `discovered_at` | the discovery window being mistaken for the voting window (§4.19) |
| `supersedes` | a retraction being outvoted by its own original |
| `take_type` | freshness being a single global rule — see §5 |

### Fail-closed defaults

`GameType.UNKNOWN` and `AssetSide.UNKNOWN` are the defaults, and neither
qualifies for anything. Silence never becomes dynasty. This is the same
posture `CLAUDE.md`'s source-domain boundary takes for the ranking pipeline:
*unverified game type fails closed.*

## 5. One analyst, one vote

`independent_claims()` collapses to one claim per `thesis_key`, which is
`(analyst, asset, thesis)` — **hashed without the platform or the content
id**. Three consequences fall out of that one choice:

- repeating a take weekly does not manufacture agreement (§4.16);
- a podcast and its YouTube cut are one opinion, which is what §4.20 asks for,
  and it needs no YouTube-specific code;
- a genuinely changed mind gets a new `thesis_id` from extraction and counts
  again.

Where no `thesis_id` is supplied the fallback is the analyst's stance on that
asset. That direction is chosen on purpose: it **under-counts** a genuinely
new argument rather than inventing independent votes.

The survivor is the most recent by `said_at`, except that a claim explicitly
superseded by another in the set is dropped regardless of date.

## 6. What is deliberately absent

- **No ingestion.** No feed reader, transcript fetch or extraction.
- **No scoring or weighting.** How far a stance moves a recommendation is
  evidence-gated, and belongs to whatever engine consumes this — the same
  posture `faab_comparability` takes with its similarity tiers.
- **No freshness constants.** §4.19 makes decay take-type-aware, event-aware
  and season-aware, and explicitly *not* a universal weekly reset. That is a
  set of inputs, not a number. `TakeType` names the vocabulary a decay policy
  would key on; fitting the rates needs evidence this repo does not yet have,
  and baking a guess into the schema would make it permanent.
- **No IDP Guru, and The Run stays paused.** Both are standing owner
  decisions to wait. A schema is not a reason to revisit them.

**Nothing consumes this package yet, and that is the intended state.** Said
plainly because the repo already carries `src/news/unified_signal_engine.py`,
which describes itself as the "single entry point for every BUY/SELL/HOLD
decision" and is imported by nothing in production (see
`scratchpad/LANE4_SIGNAL_EMITTER_INVENTORY.md`). A module that claims to be
wired is worse than one that says it is not.

## 7. What consumes it next

In order, and each is a separate authorized unit:

1. **Extraction** — transcript → claims, which is where `thesis_id`,
   `provenance` and `game_type` are actually decided. The schema is the
   contract it has to satisfy.
2. **Freshness policy** — a decay keyed on `take_type` plus event
   supersession, fitted against evidence.
3. **Consensus Edge integration** — consuming `StanceTally` *by class*, which
   is the point at which the STASH rule earns its keep.

## 8. Verification

```bash
python -m pytest tests/analyst -q      # 57 deterministic tests, no network
```

The tests are the specification made checkable: the vocabulary matches §4.16
exactly, STASH cannot merge into conviction, a quote cannot carry non-verbatim
provenance, an unknown game type is not dynasty, a conditional stance without
its trigger will not construct, and syndicated or repeated takes collapse to
one vote.
