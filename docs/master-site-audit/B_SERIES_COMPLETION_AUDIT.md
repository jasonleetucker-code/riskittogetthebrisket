# B-Series Completion Audit

**Audited against:** `main` @ `460c9f9`, and production at
`https://chaseupside.com` after the `62f5a39` deploy.

**Method:** every requirement is answered by an observation of the live tree or the live
service, never by a claim in a document. The structural checks are executable —
`evidence/B-completion/audit.py`, output in `evidence/B-completion/results.md` — so the next
reader can re-run them rather than trust this page.

**A note on how this audit was conducted.** The first run reported five failures. All five
were the *checks* being wrong, not the code: a substring search that matched the comment
documenting a removal, a stamp looked for in `data_contract.py` when it correctly lives in
`server.py`, a memorised family count that was stale, a unit assertion that would have
failed the very discipline B9b established (`percentilePoints` is the right unit for a gap
between percentiles), and a `valueMode` match on a comment saying the component deliberately
takes no `valueMode`. They are recorded here because an audit that reports false failures is
worse than no audit, and because the corrections are themselves the evidence that the checks
now assert the right thing.

---

## Matrix

Legend: **PASS** — verified. **PARTIAL** — implemented, with a stated boundary.
**N/A** — out of B-Series scope by ruling.

### A. Canonical valuation ownership

| requirement | authority | owner | evidence | tests | prod | status |
|---|---|---|---|---|---|---|
| one canonical value per asset | MASTER_PRODUCT_PLAN §3.1; B9a | `_compute_unified_rankings` | no `offenseOnly*` / `*ExperimentalValue` key on any of 1,094 live rows | `test_one_canonical_value_per_asset.py` | contract validates on deploy | **PASS** |
| no offense-only second board | B9a (W29-F001) | — | `apply_valuation_factors` absent; pre-pass removed | same | — | **PASS** |
| rejected league-aware methodology stays retired | #822; `LEAGUE_AWARE_METHODOLOGY_REJECTION.md` | `server.py::_requested_valuation_mode` | request parsed, **ignored**, stamped `league_adjusted_withdrawn: not_canonical` at 2 sites; `valuation_factors` seam deleted from `data_contract` | `test_canonical_value_invariance.py` | — | **PASS** |
| canonical 1–9999 scale enforced | B9a | `player_valuation.DISPLAY_SCALE_*` | validator reads the same constants the board is built from; 812 priced rows all in `[1, 9999]` | `test_canonical_value_scale_contract.py` | "Validate live data contract" step SUCCESS | **PASS** |
| scale owner is singular | B9a | imported, never restated | `DISPLAY_SCALE_MAX as _CANONICAL_VALUE_MAX` | same | — | **PASS** |

### B. Source methodology

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| provider families declared | B10-T2 (#825) | `_RANKING_SOURCES.correlation_group` | 21 sources → **13 independent families**; 13 sources declared into 5 multi-board providers (dlf, draftSharks, fantasyPros, flockFantasy, ktc) | `test_source_provenance.py` | **PASS** |
| nested consensus does not double-vote | owner ruling on Fitzmaurice-in-FantasyPros | same | 299 players, 100% contained, r ≈ 0.9297; declared from source identity, corroborated by correlation | same | **PASS** |
| independent-family collapse | B10-T3b (#831) | `collapse_to_independent_families` | the blend calls it; no averaging inside it | `test_family_aware_aggregation.py` | **PASS** |
| family-head selection, not averaging | owner ruling | `_source_precedence` = registry order | selection verified structurally | same | **PASS** |
| no accidental duplicate votes | B10 | — | 455 values moved at T3b, zero top-100 churn; pick confidence made family-aware in B11 (0 of 144 live rows affected — a closed hole, not a moved number) | `test_confidence_gate.py::TestPickConfidenceIsFamilyAware` | **PASS** |

### C. Circularity

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| market gap stops measuring retail against itself | B10-T3a (#827) | `_compute_market_gap` | retail side expanded across correlation groups; 364 rows changed magnitude, **72 flipped direction** | `test_market_gap_independence.py` | **PASS** |
| no downstream path reintroduces self-confirmation | B10 | — | B11's agreement axis compares each family head to the blended value — the blend's own output, which is a *calibration* target, not an independent vote; it is explicitly not counted as evidence | `test_confidence_gate.py` | **PASS** |

### D. Threshold / unit correctness

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| threshold registry with declared units | B9b | `config/thresholds.json` + `src/api/thresholds.py` | 17 thresholds, every one carrying `unit` + `derivedFrom` | `test_threshold_parity.py` | **PASS** |
| frontend/backend parity | B9b | mirror + parity test | Python *loads* the JSON, so it cannot drift; the JS mirror is diffed | same | **PASS** |
| ROS percentile semantics | B9b | `src/ros/tags.py` | 3 percentile gates + 1 `percentilePoints` gap — the gap correctly carries a different unit | `test_tag_parity.py` | **PASS** |
| no cross-scale comparisons in B-owned paths | B9b | — | `THRESHOLD_UNIT_REGISTRY.md` classification | — | **PASS** |

### E. Second Opinions

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| declared value basis | Second Opinions scale audit (#828) | `frontend/lib/second-opinions.js` | `VALUE_BASIS` with `KTC_NATIVE` as its own island | `second-opinions-scale.test.jsx` | **PASS** |
| no mixed-scale imputation | owner ruling | `resolveVendorAssetValue` | the panel's CODE reads no display `valueMode`; KTC-uncovered assets report incomplete rather than borrowing a canonical value | same | **PASS** |

### F. Confidence / B11

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| multi-axis confidence owner | B11 ruling §4/§8 | `src/api/confidence.py` | five axes: independence, coverage, freshness, applicability, agreement | `test_confidence_gate.py` (35 tests) | **PASS** |
| the defective spread is retired | B11 §7 | — | `_compute_confidence_bucket` and all four threshold constants deleted | `test_trust_confidence.py::TestTheSpreadStatisticIsGoneFromThisModule` | **PASS** |
| duplicates do not create confidence | invariant 1 | family heads | an exact identity — a duplicate is not an input to any axis; `assess_confidence` raises on one | `test_a_duplicate_family_member_changes_nothing` | **PASS** |
| removing duplicates does not promote | invariant 2 | same | same identity | same | **PASS** |
| removing evidence does not promote mechanically | invariant 3 | coverage denominator = **eligible** families | an eligible family that goes silent stays in the denominator permanently | CASE D / CASE E | **PASS** |
| confidence is not value | invariant 4 | — | 0 of 1,094 rows moved value or rank; no non-confidence field changed | board diff | **PASS** |
| missing is not zero | invariant 5 | tri-state `fresh`; null shares | unknown freshness is not fresh; no consensus value is not agreement | `TestMissingIsNeverZero` | **PASS** |
| family-aware | invariant 6 | B10 owner | lineage consumed from `correlation_group_for`, never re-derived | `test_source_provenance.py` | **PASS** |
| freshness matters | invariant 7 | `_source_freshness_flags` | DraftSharks at 214h against a 6h budget — production confirms the session file is missing | CASE H | **PASS** |
| applicability matters | invariant 8 | translation method + TE basis | approximating translation is a full penalty; ADR-015's measured basis conversion costs one level | CASE I | **PASS** |
| disagreement is not max−min | invariant 9 | share within a material relative gap | pinned by a test that moves an interior family while holding the extremes | `test_no_axis_is_a_range_statistic` | **PASS** |
| explainable | invariant 10 | `confidenceAxes` + `confidenceReasons` | "12 independent evidence families · 11 of 12 families price within 15% of the published value" | `test_the_result_is_explainable_not_a_bare_score` | **PASS** |
| one owner, no frontend confidence math | B11 §8 | `confidence.py` | gate parameters deliberately absent from `thresholds.js` | `test_the_confidence_parameters_are_not_mirrored_to_the_frontend` | **PASS** |
| deterministic | B11 §9 | — | back-to-back builds identical on value, rank, bucket and axes | `test_it_is_deterministic` + audit check H | **PASS** |

### G. Missingness

| requirement | authority | owner | evidence | tests | status |
|---|---|---|---|---|---|
| `inferValueBundle` dispositioned | B11 prompt §13 | `frontend/lib/trade-logic.js` | every semantic use traced; the arithmetic neutral kept and disclosed, the labels fixed | `unpriced-is-not-zero.test.js` | **PASS** |
| missing ≠ zero on display | MASTER_PRODUCT_PLAN §3.2 | `formatBoardValue` | one formatter, so "not priced" cannot be "0" here and "—" there | same | **PASS** |
| no sort turns unknown into a real zero-valued asset | §13 | `displayValue` → null | an unpriced asset sorts last because it is unknown, not because it lost to 12 | same | **PASS** |
| the verdict admits what it could not price | §13 | `unpricedAssetsOnSide` | "Incomplete — N unpriced" on the side total, assets named in the tooltip | same | **PASS** |

### H. Board integrity

| requirement | evidence | status |
|---|---|---|
| canonical scale | 812 priced rows, all in `[1, 9999]` | **PASS** |
| deterministic board | back-to-back builds differ on nothing | **PASS** |
| no duplicate value owners | no second-value key on any row | **PASS** |
| source provenance | `sourceRankMeta` carries method, raw rank, weight, `supersededBy` | **PASS** |
| current value/rank sanity | 1,094 rows, 812 priced, 282 explicitly unpriced and published as `rowsUnpricedByBoard` | **PASS** |
| board-history recorder | writes on every build — see the boundary below | **PARTIAL** |

### I. Test / deployment integrity

| item | evidence | status |
|---|---|---|
| merged PRs | #824 B9 · #825 B10-T2 · #827 B10-T3a · #828 Second Opinions · #831 B10-T3b · #832 B11 prerequisite · #833 B11 diagnostic · **#834 B11** · **#836 missing-as-zero** | **PASS** |
| exact validated SHAs | #834: CI SUCCESS on `70e70ca` (run 31828347707), merge `d50de55`, **second parent = `70e70ca`**. #836: CI SUCCESS on `ef2cfa9` (run 31831875577), merge `62f5a39`, **second parent = `ef2cfa9`** | **PASS** |
| nothing unvalidated entered a merge | both merges' second parents equal their validated heads exactly; first parents were data-refresh commits | **PASS** |
| backend suite | **7,548 passed / 60 skipped**, re-run on `460c9f9` after every B-Series merge | **PASS** |
| frontend suite | **2,044 passed / 125 files**, re-run on `460c9f9` | **PASS** |
| deployment | Deploy Production SUCCESS on both merge commits; #836's run includes **post-deploy smoke** and **"Validate live data contract"**, both SUCCESS | **PASS** |
| production contract | `status: ok`, `contract_ok: true`, startup checks 8/8, no breaker open, scrape 0.1h old | **PASS** |

---

## PARTIAL — stated in full

**H: the board-history recorder is non-deterministic.** Two back-to-back builds of *identical
code* differ in `rankChange` on 740 rows: the recorder writes a snapshot each build and the
next build diffs against it. This is **pre-existing** and unrelated to any B-Series change —
it reproduces on `main` before B11 — but it is the one thing a board diff of any change will
show, so it is named here rather than left to be rediscovered and misattributed. It does not
touch `rankDerivedValue`, rank, or confidence.

**Does it block C?** No. It is a diagnostic field, not a decision surface.

---

## Deliberately out of scope, and why

Three naming defects were found during B11 and **not** fixed, because each is a rename with
its own consumer blast radius and none of them changes a number:

- `confidenceBucket: "none"` appears on 24 rows that ARE priced — the label says "unranked"
  on a ranked row;
- `identityConfidence` means "the player id resolved", not confidence in a value;
- `marketConfidence` is a bounded dispersion metric, not a confidence level.

They are recorded in the ledger's B11 section as open. None affects a canonical value, and
folding them into a confidence-methodology change would have been exactly the silent scope
drift §17 forbids.

---

## Verdict

All 20 executable checks PASS. Every requirement in the audit scope is PASS or a PARTIAL
whose boundary is stated and which does not block the next phase.

**PASS — C-Series may begin.**
