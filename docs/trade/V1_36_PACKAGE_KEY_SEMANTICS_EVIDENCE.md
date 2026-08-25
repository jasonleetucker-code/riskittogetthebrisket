# V1-36 / C3-PKG-01 — `package_key` semantics: evidence packet

**Status: OWNER / INTEGRATION DECISION REQUIRED. No answer is proposed here.**

Prepared by Claude 2 (Trade Intelligence) in response to PR #1088, which
identified this as a question separate from the guard false-negative
(closed separately as Guard A). This document assembles the evidence and
deliberately stops short of choosing.

## The question, as #1088 put it

Does V1-36 require every specialized `suggestions.py` path to use canonical
two-sided `package_key(send, receive)` as its **entire** whole-package dedup
identity?

Or is consuming canonical `PackageAsset` / side identity while retaining a
specialized local search and dedup the accepted consolidation boundary?

---

## 1. Every current use of canonical `package_key`

| site | how it is used |
|---|---|
| `src/packages/construction.py:215` | the definition — `package_key(send, receive) -> (side_key(send), side_key(receive))`, docstring: *"THE dedup identity for a package. Directional."* |
| `src/packages/__init__.py:29,50` | re-export only |
| `src/roster_intel/packages.py:358-370` | `_package_key(c)` wraps the owner's `package_key` over a `PackageCandidate`'s two sides |
| `src/roster_intel/packages.py:325,345,823,844` | four call sites: frontier sort tiebreak, per-axis winner id, frontier membership set, near-miss exclusion |

**So exactly one consumer today** — `roster_intel/packages.py` — and it uses
the whole-package form for genuine whole-package identity (frontier
membership).

Neither `finder.py` nor `angle.py` calls `package_key` directly: they call
`enumerate_packages` / `enumerate_sides`, and the owner does dedup
internally via `side_key`/`package_key`.

## 2. Every local key in `suggestions.py` (post-#1079)

All are routed through the canonical owner already — the question is the
*grain*, not whether the owner is consumed.

| # | site | grain | canonical primitive |
|---|---|---|---|
| 1 | `_generate_buy_low:1261` `seen[key]`, tightest-gap dedup | **receive side only** | `_side_identity` → `side_key` |
| 2 | `_generate_consolidation:1297` `tried` already-visited pairs | **give side only** | `_side_identity` → `side_key` |
| 3 | `_apply_quality_filters` receive-target repetition cap | **receive side only** | `_side_identity` → `side_key` |
| 4 | `_apply_quality_filters` give-player appearance cap | **per asset** | `_identity_key` → `PackageAsset.key` |
| 5 | `analyze_roster`, sendable view, constraint block, balancer helpers | **per asset** | `_identity_key` → `PackageAsset.key` |

`package_key` itself has no call site in `suggestions.py`. That absence is
documented in-code at `suggestions.py:308` as a deliberate, recorded
statement rather than an oversight.

## 3. Concrete collision / non-collision example

Reproduced with live code (`_side_identity` vs `package_key`):

**Collision — the two disagree.** Two genuinely different proposals sharing
one receive side:

```
P1: give [Bijan Robinson]  receive [Ja'Marr Chase]
P2: give [Puka Nacua]      receive [Ja'Marr Chase]

local receive-side key   P1 == P2 ?  True   -> COLLIDE: one is dropped,
                                                tightest gap wins
whole-package key        P1 == P2 ?  False  -> DISTINCT: both survive
```

**Non-collision control — the two agree.** Different receive targets:

```
P1: give [Bijan Robinson]  receive [Ja'Marr Chase]
P3: give [Bijan Robinson]  receive [Josh Allen]

local: distinct.  whole-package: distinct.  No disagreement.
```

So the grain difference is real and reachable, and it bites exactly where
one target is attainable from several give-side pieces.

## 4. User-visible behaviour impact — measured, not argued

Real contract built through `build_api_data_contract` from the pinned,
committed `tests/fixtures/golden/input_export.json.gz`; all 12 real teams;
whole-package key simulated by neutralising the receive-side dedup (valid,
because each `(sell, target)` pair is generated once, so a whole-package key
collapses nothing).

| regime | `buyLow` today (local key) | `buyLow` with whole-package key | delta |
|---|---|---|---|
| `top150` (**production default**) | 3 | 2 | **−1** |
| `full_board` | 1 | 1 | 0 |
| `thinned` | 0 | 0 | 0 |

**Two things the owner should weigh, and the first is counterintuitive:**

1. **The change is not monotonic, and on the production default it produces
   FEWER suggestions, not more.** The naive expectation — "dedup less, get
   more" — is wrong. Likely mechanism (stated as a hypothesis, not a
   measured claim): `_apply_quality_filters` runs downstream, and its
   receive-target repetition cap and give-player appearance cap are
   budgets; feeding more raw candidates in changes which ones consume the
   budget and can shorten the final list. Anyone implementing this should
   re-measure rather than assume direction.
2. **The magnitude is small but non-zero on the surface users actually
   see.** This is not a no-op, so it cannot be adopted as a pure
   "canonicalisation with no behaviour change".

Only `buyLow` is affected: it is the only category whose dedup is keyed on a
single side in a way that can collapse distinct proposals. Sites 2 and 3
are budget/visited-set mechanics whose grain does not change which distinct
proposals exist.

## 5. Contract / manifest wording bearing on the decision

Both readings have textual support, which is precisely why this needs
adjudication rather than a lane decision.

**Supports "one generator, fully migrated":**
- V1 contract V1-36 capability: **"ONE shared package generator"**.
- V1-36 row: `suggestions.py` *"remains a **deliberate, un-migrated** holdout"* — framed as an outstanding gap, not an accepted boundary.
- Original scope note: *"4 generators to retire"*.

**Supports "specialized consumer is the accepted boundary":**
- Manifest `C3-PKG-01` (CORRECTED 2026-08-20): *"**3 of 4 generators already consume it** — `finder.py` and `angle.py` fully, `roster_intel/packages.py` **only for identity** (no capacity/constraint integration yet)"* — i.e. identity-only consumption is explicitly counted as consuming.
- Same row: *"**PARTIAL**, not the prior '4 independent generators'"* — the framing already moved off "independent generators".
- `roster_intel/packages.py` is allowlisted in the mechanics guard as a *"documented, deliberately-separate staged Pareto-frontier search"*, establishing precedent that a specialized search retaining its own algorithm still counts as consolidated.

**The unresolved tension in one line:** the manifest credits
`roster_intel/packages.py` as a consumer for identity-only use while keeping
its own search, but the V1 contract still calls `suggestions.py` an
un-migrated holdout for doing structurally the same thing. Those two
statements cannot both be the standard.

## 6. What is NOT in scope of this packet

- No product methodology change was made.
- No local key was replaced.
- V1-36 was not promoted.
- The `_generate_consolidation` IDP-exclusion deferred owner decision
  (`suggestions.py`, in-code flagged) is a **different** open question and is
  untouched here.
