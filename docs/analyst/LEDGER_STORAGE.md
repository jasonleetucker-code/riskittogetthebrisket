# Analyst claim ledger — persistence and as-of query

**Owner module:** `src/analyst/` (`store.py`, `query.py`)
**Consumes, unchanged:** `src/analyst/claim.py`, `src/analyst/stance.py`
**Owner spec:** `OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md` §4.16, §4.19, §4.20
**Scope manifest:** `C6-ANA-01`
**Status:** storage + as-of query live, zero ingestion, zero consumers by design.

---

## 1. What this is, and what it deliberately is not

`docs/analyst/CLAIM_SCHEMA.md` defines what an analyst take **IS** —
`AnalystClaim` — and stops there on purpose: "schema only. No ingestion, no
consumers yet — by design." This unit is the next authorized step named in
that document: a place to **put** instances of that schema, and a way to
**ask what was known as of a given instant**, without leaking evidence
backward in time.

It is not a second schema. `AnalystClaim` and its `Stance`/`SourceLabel`
vocabulary are untouched — this unit imports them, wraps them, and stores
them.

It is not ingestion. No podcast/YouTube/X scraper, no transcript fetcher, no
extractor exists anywhere in this unit. Zero credentials are touched. A
future unit that needs them and finds them unavailable reports
`AUTH_REQUIRED` — not this one, which performs no acquisition at all.

It is not a valuation voter. See §5.

## 2. Why a fourth store, and why its shape follows `src/acquisition/`

Three existing append-only stores were read in full before writing a line of
this one:

* **`src.history.store`** — its `observations` table's own
  `validate_observation()` hard-requires `value is not None or rank is not
  None`. A pure stance/text claim has neither. This is not a lane
  difference; it is the wrong table shape.
* **`src.retention`** — states its own governing rule at
  `src/retention/__init__.py`: *"nothing here may be read by a decision
  path,"* full stop, with no read exception. That is **stricter** than this
  ledger needs. A future Manager Scout, Universal Player Profile, or Ask
  Brisket feature must be able to **read** claims — retention's rule would
  forbid that legitimate consumer, not just the illegitimate one (canonical
  valuation).
* **`src.acquisition`** — the right precedent. Its own `__init__.py`
  justifies being a fourth store precisely because it needed to be read by
  a decision path (unlike retention) while recording a different quantity
  than value/rank (unlike history). That is exactly this unit's situation.
  `src/analyst/store.py` follows its idiom directly: structured columns (a
  claim's fields are fully known upfront, unlike an arbitrary external
  scoring-card blob — so no content-addressed-payload-table indirection is
  needed the way `src.retention` uses one), a natural identity key, a
  `content_hash()` over the non-identity facts, and the same three-way
  `{inserted, unchanged, conflicts}` write outcome, conflicts surfaced and
  never silently applied.

## 3. Identity vs. content — the one place this deviates from a literal
   copy of `AcquisitionEvent`, and why

`AcquisitionEvent.content_hash()` hashes everything except the natural key
`(league_key, source_ref, asset_id)`. A first draft of this ledger mirrored
that literally: identity = `(analyst_id, content_id, platform, asset_key,
stance, take_type, said_at)`. On reflection this was wrong, and was changed
before writing tests against it:

**`claim_identity_key()` covers only the real-world coordinates of ONE
UTTERANCE** — analyst, content item, platform, asset, `said_at`. It
deliberately **excludes** `stance`. If two ingestion runs over the exact
same utterance disagree about what stance it expresses — a parser
regression, a genuinely improved extractor, a second human's read of an
ambiguous quote — that is exactly the case that must surface as a
**conflict** for a human to resolve, not silently become two rows for one
utterance (had stance been part of identity) and not silently overwrite one
reading with another (had there been no conflict check at all).
`content_hash()` covers everything else: the classification (`stance`,
`source_label`, `take_type`) and the qualifying context (`game_type`,
`asset_side`, `conditions`, `quote`, `thesis_id`, `discovered_at`,
`supersedes`, `notes`, `tags`).

Mutation-verified (§7): forcing the `unchanged` branch to fire regardless of
`content_hash` sends `test_reingesting_with_a_different_stance_is_a_conflict_never_applied`
RED.

## 4. The confidence / parser-version split

The owner spec (`OWNER_PRODUCT_BACKLOG_SPEC.md`, "ANALYST INTELLIGENCE"
section, "Preserve" list) requires "extraction confidence." This unit's own
governing brief additionally requires "parser version." Neither exists on
`AnalystClaim`.

Rather than adding them there, they live on `LedgerEntry` — the **ingestion
envelope** wrapping a claim. How confidently and by what process WE captured
the words is a fact about our extraction pipeline, not about what the
analyst said. This keeps `AnalystClaim` — "what a take IS" — untouched
(zero risk to its 57 existing tests), and keeps claim-vs-interpretation
separated at the **type level**, not merely by convention: a caller cannot
accidentally read `claim.extraction_confidence`, because it does not exist
there.

`ExtractionConfidence.UNKNOWN` is the default and is not a numeric midpoint.
An extractor that has not published a confidence signal says so explicitly
— the same MISSING-IS-NEVER-ZERO rule this codebase applies everywhere else
a quantity can be unmeasured.

## 5. Non-influence on canonical valuation

Structural, not aspirational: `tests/analyst/test_non_influence.py` scans
`src/api/data_contract.py`, `src/canonical/`, and `src/trade/ktc_va.py` (the
modules that decide canonical player/pick value) for any import of
`src.analyst.store` or `src.analyst.query`, asserting the scan itself is
non-vacuous (mirrors `tests/api/test_canonical_ownership_protections.py`'s
own stated rule: "a static check that silently stops matching is worse than
no check"). A second test checks the reverse direction (the store/query
modules never import the canonical-value writer). A third proves the public
functions (`write_claims`, `claims_as_of`) run correctly with no server
state, no contract global, and no canonical-value dependency at all.

Mutation-verified (§7): adding a fake `from src.analyst.store import
write_claims` line to the top of `src/api/data_contract.py` sends the first
guard RED, naming the offending file.

## 6. Never-future — the as-of query's central guarantee

A claim is visible as of instant D only when **both**:

* `said_at <= D` — the analyst had said it by D, and
* `effective_discovered_at <= D`, where
  `effective_discovered_at = claim.discovered_at or entry.recorded_at`.

The second condition is the one worth restating: an analyst could have said
something on Monday that this platform did not ingest until Thursday, and a
query for "Tuesday" must not see it (owner spec §4.19: "discovery window is
not voting window"). `entry.recorded_at` — the ledger's own insertion
instant, always stamped by the store, never optional — is the fallback when
a claim carries no `discovered_at` of its own, so the guarantee holds even
before any extractor exists to populate that field. There is no code path
where a missing `discovered_at` degrades into "skip the check."

Supersession is evaluated the same way: a retraction claim that is not
itself yet visible as of D cannot hide the original at D — "as of Tuesday,
we didn't know about Thursday's retraction yet" is the correct answer, not
a stale one.

## 7. Mutation verification performed (build-time check, not a permanent
   self-mutating test)

Three branches manually mutated, confirmed RED against the relevant test,
reverted, working tree confirmed clean via `git diff` after each:

1. `src/analyst/query.py`: dropped the `_effective_discovered_at` filter
   from `claims_as_of`, keeping only `said_at <= on_instant` →
   `TestNeverFutureLeak` failed 3 of 5 (a claim discovered late leaked into
   an as-of-the-past query).
2. `src/analyst/store.py`: forced `write_claims`'s conflict branch to always
   take the `unchanged` path regardless of `content_hash` comparison →
   `test_reingesting_with_a_different_stance_is_a_conflict_never_applied`
   failed (a differently-classified re-read of the same utterance was
   silently accepted instead of surfaced).
3. `src/api/data_contract.py`: prepended a fake
   `from src.analyst.store import write_claims` import →
   `test_canonical_valuation_modules_never_import_the_analyst_ledger`
   failed, naming the file.

## 8. Open items (named, not resolved here)

1. **Ingestion** (`C6-POD-01`, `C6-YT-01`, `C6-X-01`) — source registry,
   episode discovery, transcript/authorized-text fetch, take extraction.
   Credentials for podcast/YouTube/X sources are unavailable in this
   environment (`OD-03`); a future unit reports `AUTH_REQUIRED` if that
   remains true when it starts.
2. **Freshness/decay** (`C6-FRESH-01`) — take-type-aware, event-aware,
   season-aware decay. This ledger's `said_at`/`discovered_at`/`recorded_at`
   fields are exactly what such a policy would read; no decay curve is
   implemented here, per the owner spec's own instruction that fitting decay
   rates is evidence-gated work for whatever engine consumes the schema.
3. **Identity resolution for free-text player mentions.** `asset_key` is
   supplied by the caller; this unit does not resolve a name mention to a
   canonical player id. `src.identity.resolution.resolve_canonical_v2`
   exists and would be the natural function for a future extractor to call,
   but is currently DARK (unwired, pending its own dual-read production
   gate) — a future ingestion unit inherits that as a real dependency
   decision, not one this unit makes for it.
4. **No consumer wiring.** Manager Scout, Universal Player Profile, Ask
   Brisket, Consensus Edge all read nothing from this ledger yet. It ships
   inert, per the mission brief's own instruction that the first ledger PR
   must be inert with respect to canonical valuation — and, more broadly,
   inert with respect to every consumer, since none exist yet.
5. **Price/pick-cost context and structured "reasoning."** The owner spec's
   "Preserve" list also names "price context" and "exact pick/player cost
   when explicitly stated," which `AnalystClaim.conditions`/`notes` can hold
   as free text but does not structure. Not addressed here — a smaller,
   separate addition to `claim.py` if a future extraction unit needs it
   structured rather than free-text.
