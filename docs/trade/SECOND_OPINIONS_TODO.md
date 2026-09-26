# Second Opinions Aggregate TODO

Add a quick per-independent-vendor trade verdict summary above the detailed source breakdown. Native source coverage must be distinguished from canonical-value imputation; do not count imputed rows as independent external votes. See `TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md`.

## Coverage taxonomy + family tally — SHIPPED (2026-09-26, #791)

Owner observation: a trade with one IDP player read "KeepTradeCut Crowd —
Incomplete", which looked like a failure. KTC publishes no IDP; that is a fact
about the vendor, not a hole in our data. The same panel also published
winners for offense-only vendors on IDP-only trades built 100% from OUR
canonical value (measured: 9 vendor rows, native coverage 0/0).

Owner: `frontend/lib/second-opinions.js`. Per (vendor, asset):

| status | meaning | proven by |
|---|---|---|
| `NATIVE` | the vendor published a value | the value itself |
| `OUT_OF_SCOPE` | the vendor's **declared** registry scope does not admit the asset class | `scope` / `extraScopes` in `RANKING_SOURCES` |
| `NOT_PUBLISHED` | in scope, no value (`detail`: expected-but-unmatched vs not published) | `sourceAudit.unmatchedSources` |
| `UNRESOLVED` | no board row | absence of the row |

Picks and undeclared scopes are never out of scope by assumption — the
registry declares no pick coverage. Per vendor row:

| verdict | shown as | counted |
|---|---|---|
| `COUNTED` | Side X / Even | **yes** — the only vote |
| `ESTIMATE` | Side X (est.) + "n of m pieces use our value" | no |
| `NOT_APPLICABLE` | Not applicable + "Doesn't price IDP (1 of 3 pieces)" | no |
| `INCOMPLETE` | Incomplete + reason | no |
| `NO_COVERAGE` | leaves the table; named below it with the reason | no |

Tally: one vote per independent family (`correlationGroup`, else the vendor):
KTC Crowd + Fantasy Navigator vote once, FantasyPros + Fitzmaurice vote once,
and a family whose members disagree is one **Split**. Pinned by
`frontend/__tests__/components/second-opinions-coverage.test.jsx`.

Open (owner decisions, not implemented): the "Even" threshold is still the
historical `< 1` point (effectively unreachable); whether a partially covered
row may ever vote; a source-unavailable state (freshness exclusion is not
materialized onto frontend rows, so it cannot be told apart here yet).

**Stale statement corrected:** no external row applies the V13 Value
Adjustment any more (`packageAdjustment: "none"` since the KTC September 2026
calculator change); KTC-native values still may not be mixed with canonical
ones, for the unit reasons below.

---

## Scale contract — RESOLVED (Second Opinions Scale Audit, 2026-08-14)

**The basis is owned by `frontend/lib/second-opinions.js` and nothing else may set it.**

Every number entering a vendor's package array carries a declared basis, and only
compatible bases may be summed:

| basis | what it is |
|---|---|
| `CANONICAL_1_9999` | Chase Upside's `rankDerivedValue` |
| `NORMALIZED_VENDOR_1_9999` | a vendor signal after canonical normalization (`valueContribution`) |
| `KTC_NATIVE` | KTC's own published value — the basis V13 VA was calibrated on |
| `MISSING` | no comparable number exists; **never a quantity, never zero** |

`CANONICAL` and `NORMALIZED_VENDOR` are compatible. `KTC_NATIVE` is its own island.

### The defect that was fixed

The uncovered-asset fallback was `effectiveValue(row, valueMode)` — and `valueMode` is
the Trade Calculator's **display** toggle. Flipping it to "Raw" swapped the fallback onto
the legacy scraper composite while every vendor number beside it stayed canonical, then
fed the mixture to a **nonlinear** Value Adjustment.

Numeric range equality is not unit compatibility. Measured on the 2026-08-14 board,
`rawComposite / canonical` over 805 rows: median 1.063, p10 0.915, p90 1.262, **min 0.266,
max 2.082**. Both are "roughly 0–9999"; substituting one for the other is wrong by up to a
factor of two on one row.

`TradeSourceBreakdown` now takes **no `valueMode` at all**.

### Non-KTC vendors — canonical imputation is valid

Proven per source on the live board: all 21 registered sources' `valueContribution` lands
inside 1–9999, with median ratio to canonical between **0.874 and 1.196**. It is the same
comparison space, so filling an uncovered asset with `rankDerivedValue` is unit-correct.

`rawSourceValues` exists only for `ktcSfTep`, and no `canonicalSites` entry on the live
board exceeds 9999 — but both remain excluded by construction rather than by luck.

### KTC — imputation REFUSED, coverage reported instead

KTC's covered assets use KTC-native values because V13 VA was calibrated on them. Direct
canonical substitution was measured over the 385 players carrying both:

| region | n | median KTC-native / canonical |
|---|---|---|
| top (≥7000) | 28 | 0.947 |
| middle (3000–7000) | 103 | 1.027 |
| tail (<3000) | 254 | 1.142 |
| overall | 385 | 1.091 (min 0.400, max 1.491) |

Not identity, and **not a constant** — it drifts monotonically with board depth, so the
error's *direction* depends on where the player sits. Inside a nonlinear VA whose
suppression thresholds compare raw differences, that is not a rounding concern.

So an asset KTC does not cover makes KTC's opinion **incomplete**. We do not manufacture
KTC's view of a player it never published. A calibrated canonical → KTC-native crosswalk
may be defensible later; it would have to be derived, monotonic, tested and honest about
extrapolation, and inventing a multiplier to get there is explicitly out of bounds.

### Missing is not zero

An asset with neither vendor coverage nor a canonical value is **unresolved**. It does not
contribute `0` to the side array, and the vendor row renders **Incomplete** with no winner
and no margin rather than publishing a verdict built on a silent zero. This applies in
strict mode too: turning imputation off reports uncovered pieces as unresolved, where it
previously zero-filled them.

### Two kinds of weight

An imputed canonical value may complete the package **arithmetic**. It does not become an
independent external **opinion**. `nativeCounts`, `imputedCounts` and `unresolvedCounts`
are carried per side so the future aggregate can count native coverage only — the standing
ruling at the top of this file.

Pinned by `frontend/__tests__/components/second-opinions-scale.test.jsx` (8 tests:
raw-mode isolation, canonical fallback, no `rawComposite` leak, no foreign-native leak,
KTC incompleteness, missing-value handling, strict mode, multi-team).
