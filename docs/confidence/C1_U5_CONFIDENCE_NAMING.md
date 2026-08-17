# C1-U5 — Confidence naming migration (`C1-CONF-01`)

**Unit:** `C1-U5` · **Row:** `C1-CONF-01` · **Owner:** `src/api/confidence.py`
**Kind:** INFRA — **explicitly not a methodology change**
**Delivered:** 2026-08-17 · **Branch:** `claude/c-series-c1-u5` (stacked on `claude/c-series-c0-r`)

> The five-axis bottleneck is preserved verbatim, per
> `docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md` §7. What was wrong here was the
> *vocabulary*, and vocabulary is what every later consumer reads — which is why
> `docs/EXECUTION_PLAN.md` §1 requires this migration **before** any new confidence
> consumer is built, and why C2/C3/C6 wait behind it.

---

## 1. What was measured, before anything changed

All five defect classes were reproduced on the live payload through the production build
path (`build_api_data_contract` on the newest export — the same call `server.py` makes),
in `tests/api/test_confidence_naming_red.py`.

| RED | defect | measured |
|---|---|---|
| 1 | priced rows wearing the row-builder placeholder | **24 rows** with a finite positive `rankDerivedValue` and `confidenceLabel: "None — unranked"` — all 2026 round-5/6 slot picks, **all 24** carrying `pickRookieAnchor` |
| 2 | `"none"` meant four things at once | the same bucket on those 24 priced rows **and 261 genuinely unpriced** rows — 285 rows, one word |
| 3 | `identityConfidence` graded resolution, not evidence | exactly `{1.0, 0.95, 0.7}` across 1,110 rows (937 `canonical_id` / 162 `position_source_aligned` / 11 `name_only`) |
| 4 | `marketConfidence` could not express its own name | span `[0.3252, 0.59375]` — never enters the top 40% of a 0–1 scale |
| 5 | the owner imported its consumer | `_compute_pick_confidence` defined in `data_contract.py`, imported back by `confidence.py` |

### The mechanism behind RED-1, traced

A pick with **no voting source** never enters `row_normalized`. Phase 4 assesses only
`row_normalized[:OVERALL_RANK_LIMIT]`; the off-cap Phase 4b′ pass skips rows where
`derived <= 0`. So neither touches it — and then
`_anchor_current_year_picks_to_rookies` prices it anyway, **by design and with a comment
saying so**, while writing no confidence field. The row shipped wearing the constructor's
default.

The value was right. The label said the row was *unranked and therefore unconfident*,
when the truth was that nothing had ever looked at it. Both sibling passes
(`_complete_future_pick_values`, `_suppress_generic_pick_tiers_when_slots_exist`) already
stamped their own verdicts, so this was a consistency repair rather than a new rule.

---

## 2. The repair

### 2.1 `confidenceBasis` — a second axis, not a fifth level

`CONFIDENCE_LEVELS` stays at exactly **four**. The overall level is the *weakest* axis, so
adding a fifth would change what the bottleneck `min()` means for every axis at once.
What was missing was never a degree of confidence — it was **which owner decided it, from
what class of evidence**. So the fix is orthogonal:

```
evidence_gate · pick_dispersion · derived_round_step · derived_rookie_tether
derived_tier_values · unpriced · no_evidence · quarantine_degraded
```

Distribution on the live board after the change:

| basis | rows |
|---|---:|
| `evidence_gate` | 705 |
| `unpriced` | 261 |
| `pick_dispersion` | 84 |
| `derived_rookie_tether` | 24 |
| `derived_round_step` | 18 |
| `derived_tier_values` | 18 |

### 2.2 The hole, not just the rows that fell through it

`validate_api_data_contract` now **errors** on a priced row whose basis is missing,
unknown, or self-contradicting (`unpriced` / `no_evidence` on a row carrying a value).
Scanned over the **whole array**, not the shape checks' 1000-row prefix — the measured
population sat past it.

That makes the bad state *unrepresentable*: the next pass that prices a row without
saying why fails the build instead of shipping quietly, which is what happened here.

### 2.3 Scope discipline on the anchor pass

The anchor pass runs over **all 72** current-year slot picks, not only the 24 nothing had
assessed. A first cut stamped the tether basis on all of them — and that would have
downgraded 48 picks' real pick-market confidence to a derivation label. **That is a
methodology change wearing a rename's clothes**, so the stamp is scoped to rows still
carrying the unassessed default.

The deeper question it exposes — the tether *overwrites* a value whose confidence was
measured from the pick market, so should those 48 still claim `pick_dispersion`? — is
real, and is recorded as a follow-up rather than decided inside a naming migration.

### 2.4 The renames, dual-written

| was | is | why |
|---|---|---|
| `identityConfidence` | `identityResolutionConfidence` | grades source-row→player *resolution* |
| `identityMethod` | `identityResolutionMethod` | travels with it; splitting the pair is worse than either name |
| `marketConfidence` | `marketBreadthAgreementIndex` | a bounded `site_score·0.65 + cv_score·0.35` blend of source **count** and **dispersion** |
| — | `marketBreadthScore`, `marketAgreementScore` | the two halves the scraper computed and **discarded** |

Publishing the two halves is what keeps the rename from being cosmetic: a reader can now
see *why* the index sits where it does, not merely that it does. The scraper change is an
identifier rename plus two extra return values — `conf` and `cv` are byte-identical,
which matters because `market_conf` is **not** purely diagnostic there: it feeds
`_elite_expansion_multiplier`, the single-source discount, the IDP cap headroom and
`elite_cap`.

**Migration mechanics, three lanes with different lifetimes:**

1. **Live payload** — additive dual-write; every legacy key carries its replacement's
   exact value. `CONTRACT_VERSION` deliberately does **not** bump: additive is not
   breaking, and bumping for an additive change trains consumers to ignore bumps. It
   bumps at alias *removal*.
2. **`meta.deprecations`** — the contract states its own deprecations machine-readably,
   each with a reason and a removal version.
3. **Archive readers stay bilingual permanently.** `exports/archive/*.zip` is immutable
   evidence written under the old spellings. An alias is a temporary promise to writers;
   bilingual reading is a permanent property of a reader of immutable history.

`tests/api/test_confidence_rename_aliases.py` pins the set in **three directions**: what
the contract declares, what a live-built row emits, and a frozen literal. Declaring an
unemitted alias, emitting an undeclared one, or drifting from the literal each fail —
because an undeclared alias is how a "temporary" dual-write becomes permanent.

### 2.5 One owner for the pick rule

`_compute_pick_confidence` moved to `confidence._pick_confidence_from_values`, verbatim.
The circular import is gone; the two remaining lazy imports (`correlation_group_for`,
`_source_precedence`) are source-registry concerns that legitimately live in
`data_contract`.

---

## 3. Blast radius, measured

Board rebuilt before and after on the same payload:

- **0 values moved.**
- **24 buckets moved**, `none` → `low` — every one a 2026 round-5/6 slot pick, exactly the
  population the RED identified. The other 48 anchored picks keep `pick_dispersion`.
- **0 rows** where a legacy alias disagrees with its replacement.

**Honest classification:** the map calls this INFRA and no value moves, but the confidence
chip text *does* change on 24 pick rows. Saying "no user-visible change" would be false.

---

## 4. Tests

| file | role |
|---|---|
| `tests/api/test_confidence_naming_red.py` | the reproduction, now inverted to verify each defect is gone — a permanent regression guard rather than a reproduction that rots on success |
| `tests/api/test_confidence_naming.py` | the positive contract: every priced row has a basis; `CONFIDENCE_LEVELS` is still four; the validator rejects a priced row with no basis |
| `tests/api/test_confidence_rename_aliases.py` | the three-way alias pin |

Suites: 33 confidence tests green · full `-m "not livedata"` gate · frontend 126 files /
2,051 tests green.

---

## 5. Deliberately not done

- **The tether-vs-market-confidence question** (§2.3) — a methodology decision, recorded
  not decided.
- **`marketBreadthScore` / `marketAgreementScore` are `None` on existing exports.** They
  populate from the next scrape. Missing, not zero — and the keys are present so the
  explanation cannot silently vanish.
- **Alias removal.** That is the breaking half and bumps `CONTRACT_VERSION`.
- **`scripts/crawl_ffpc_sharp.py`'s `identityConfidence`** is a **homonym**, not a
  consumer: it reads a `curatedManagers` config record feeding
  `platform_ledger.upsert_manager`. That is *manager*-identity confidence in a different
  domain, and renaming it would have been a real defect.
