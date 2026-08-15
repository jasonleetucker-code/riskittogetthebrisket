# Chase Upside — Owner Master Feature Backlog (104-Item Discussion Ledger)

> **RECONCILIATION AMENDMENT — 2026-08-14.** Promoted to `main` verbatim from PR #816 by the post-B master
> reconciliation (`docs/POST_B_RECONCILIATION_2026-08-14.md`). All 104 rows preserved; count re-verified programmatically as exactly 104, contiguous
> 1–104, no gaps and no duplicates.
>
> **Rows 102, 103 and 104 have a binding detailed spec:**
> `docs/trade/TRADE_GENERATION_PREFERENCES_AND_REFINEMENT_SPEC.md` (promoted from PR #835). The two records were
> authored independently and previously had no cross-reference in either direction. They are consistent; the spec
> is the normative long form and this ledger is the coverage row. **Row 101** likewise has
> `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md`.
>
> §O's rule holds and is now discharged: this ledger is **not** the whole product. It is one of twelve sources
> unioned into `docs/C_SERIES_SCOPE_MANIFEST.md`. Every one of the 104 rows is mapped there — see
> `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` §F.


**Status:** BINDING SCOPE INPUT FOR THE POST-B C-SERIES REPLAN  
**Recorded:** 2026-08-13; amended 2026-08-14  
**Purpose:** preserve the owner's accumulated feature discussions in repository form so the future C-series cannot lose requirements that were previously captured only in conversation/backlog form.

This is a **scope ledger**, not a standalone implementation specification and not an authorization to start C early. Detailed specs, canonical ownership, dependency order, and exact done criteria live in the feature-specific docs and must be reconciled under `C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`.

If an item already exists elsewhere, this row is a coverage reminder, not permission to build a duplicate engine.

---

# A. Data pipeline and app workflow

1. **Integrated data loading** — Pull the latest scraper/output data directly into the application so core workflows use real current data rather than manual or disconnected files.
2. **Automatic player lookup and source autofill** — Selecting a player resolves the canonical identity and available source observations automatically.
3. **Autocomplete player search** — Fast typeahead using canonical identity so input is consistent and lookup mistakes are reduced.
4. **Source list synced with actual data** — Only show source families that are really available; UI and ingestion may not drift.
5. **Live scaling/reference values from loaded data** — Calibration/reference metadata must derive from the actual active dataset instead of stale hard-coded assumptions.
6. **Automatic data load on app open** — Useful current/cached data is available without manual initialization.
7. **On-demand refresh/re-scrape where appropriate** — Support safe forced refresh through the canonical refresh owner without spawning duplicate global jobs.
8. **Scheduled data refresh** — Required source/data jobs run automatically with freshness/health visibility.
9. **Data readiness and freshness status** — The UI shows whether data is loaded/current/trustworthy and degrades honestly.
10. **Server-backed application architecture** — Production data/update state is served and managed centrally rather than relying on fragile local-file behavior.

# B. Valuation engine and trade logic

11. **Confidence-aware composite/consensus value** — Thin source coverage must not be presented with false certainty.
12. **Robust consensus calculation** — Outlier-resistant/weighted/adaptive consensus only where validated, with source independence and provenance.
13. **Position-aware elite value handling** — Top-end curves may differ by position, but methodology must be evidence-backed and canonical.
14. **Bundle discount / diminishing returns** — Multi-piece packages must not automatically defeat elite assets merely because raw values sum higher; preserve explicit package/VA methodology.
15. **Fairness adjustment suggestions** — Uneven trades should suggest realistic players/picks/packages that could balance them.
16. **Visual trade-balance indicator** — Clear readable presentation of fairness/gap without replacing numeric truth.
17. **Z-score/distribution normalization research/support** — Source distributions may be normalized for comparability where validated.
18. **Switchable normalization modes only when they represent legitimate separate analyses** — Do not create competing canonical truths; experimental/reference modes must be clearly non-canonical.
19. **Tunable normalization mapping for research/admin use** — Mapping controls must not become device-local canonical value overrides.
20. **Per-source statistical support for normalization** — Store/expose the source statistics needed to validate translation/normalization.

# C. Pick valuation and anchor system

21. **Automatic pick-anchor population** — Pick conversion anchors come from canonical/current pick evidence rather than manual-only configuration.
22. **Inference of missing pick anchor points** — Missing source points are estimated through documented methodology rather than breaking the pick system.
23. **Realistic interpolation for missing picks** — Use a curve that reflects actual dynasty pick-value decline rather than crude linear gaps.
24. **Extrapolation for deeper and future picks** — Continue producing usable values for valid supported deep/future assets, subject to the hard through-2029 canonical requirement.
25. **Manual/admin anchor reset from newest evidence** — Safe administrative ability to refresh anchor inputs without creating a second valuation owner.

# D. Rankings, rookie view, and player-list usability

26. **Position-based rookie filtering** — QB/RB/WR/TE/IDP and relevant subgroups.
27. **Rookie tier visualization** — Show meaningful value tiers/drop-offs, not only a flat list.
28. **Rookie consensus indicator** — Show source agreement/disagreement/coverage so polarizing rookies are visible.
29. **Clear position labeling in rankings/search** — Player identity is immediately understandable across rows/autocomplete/results.

# E. Team and roster intelligence

30. **Dedicated roster workspace** — Full-roster analysis separate from one-off trade entry.
31. **League-wide roster strength rankings** — Canonical Team Strength across all teams.
32. **Positional capital breakdown by team** — Visual value/strength by QB/RB/WR/TE/IDP groups using canonical roster math.
33. **Selected-team context** — The app consistently understands the selected team and personalizes decision surfaces accordingly.
34. **Trade Target Finder** — Identify realistic targets from other rosters based on needs, surplus, executability, and canonical trade logic.
35. **League-relative positional strength** — Show each team's strong/weak position groups relative to the league.
36. **Surplus-based player suggestions** — Convert roster imbalance into plausible target/outgoing names rather than only generic grades.
37. **Outgoing trade-chip identification** — Identify assets the selected roster can move most safely/logically.
38. **Roster-aware trade entry** — Participating team rosters/ownership prioritize and constrain asset selection.
39. **Realistic target filtering** — Avoid impossible stars, illegal ownership, and meaningless filler in recommendation output.

# F. League-wide analysis views

40. **Dedicated league command center** — Bring roster/market/comparison/league context together without duplicating engines.
41. **Power/strength heatmap** — Fast league visual by team and position, sourced from canonical strength/power owners.
42. **Single-team breakdown view** — Drill into one franchise's positional makeup and asset structure.
43. **Head-to-head team comparison** — Compare two teams side-by-side for strength, shape, needs, and trade fit.
44. **Multiple roster analysis lenses** — Full team + picks, players only, starters/meaningful roster, etc., as clearly labeled views rather than competing values.
45. **Flexible team breakdown organization** — Position-grouped or pure value/rank ordering depending on the task.
46. **Responsive league views** — League analysis remains genuinely usable on mobile.
47. **League/team selectors from real Sleeper data** — Context comes from canonical league information, not manual hardcoding.

# G. External market data and league behavior

48. **KTC market integration** — Use KTC where authorized as an external offensive market reference, not as Chase Upside's UI or sole truth.
49. **Waiver-market integration / add-drop market context** — Use legitimate external waiver interest evidence where available and useful.
50. **Sleeper market/league context retained alongside external market evidence** — External data supplements rather than replaces league-specific truth.
51. **Sleeper league trade-history grading** — Pull/normalize completed league trades and evaluate them with current and historical Chase Upside evidence.
52. **Trade performance tracking** — Roll historical trade outcomes into manager/franchise evidence while separating at-the-time and current grades.
53. **Waiver wire value finder** — Compare unrostered assets with the canonical player universe and selected-team need.

# H. Alerts and proactive utility

54. **Player value movement alerts** — Detect meaningful canonical value movement for watched/owned/relevant players.
55. **Optional email/push alerts for meaningful changes** — Thresholded, non-spammy proactive delivery using canonical changes and user preferences.

# I. IDP and source-conversion logic

56. **Separate IDP value-translation methodology** — Defensive rankings/values use a defensible IDP-specific translation rather than blindly sharing offensive curves.
57. **Tunable IDP conversion research/admin settings** — Controls exist only at the appropriate governed methodology layer, not device-local canonical overrides.
58. **Rank-based source conversion for ranking-only sources** — Convert rank observations into the unified scale with validated source/position logic.

# J. UX cleanup and speed

59. **Dashboard/workflow declutter** — Remove unnecessary friction/noise while preserving useful information density.
60. **Remove redundant controls and low-value outputs** — Retire duplicate actions/fields after canonical consolidation.
61. **Clearer result labeling and ordering** — Present trade/decision outputs in decision-useful hierarchy.
62. **Simplified settings workflow** — Clear labels; advanced controls collapsed/gated; no setting may create hidden canonical divergence.
63. **One-click side swap** — Reverse trade sides without rebuilding the deal.
64. **Compact quick-use layout** — Faster, denser calculator/workflow mode without losing correctness.
65. **Keyboard-optimized entry flow** — Fast focus/typeahead/add behavior for power users.
66. **Remembered team context** — Persist selected team/league through the canonical account/session model where appropriate.
67. **Better mobile usability for roster-heavy views** — Mobile is a real supported workflow, not a shrunken desktop afterthought.
68. **Polished visual feedback** — Clear interaction/refresh/error states consistent with Premium Sports Intelligence.

# K. Export, configuration, and maintainability

69. **Full player-data export** — Export the canonical/authorized player dataset with correct provenance/privacy.
70. **Configurable test/debug player list** — Development/test subsets without rewriting production logic.

---

# L. Trade Calculator, real-trade database, and market-intelligence expansion

The detailed binding behavior for 71–100 is in `TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md`.

71. **Two-sided asset trade builder with package composition summaries.**
72. **Explicit raw canonical total versus package/Value Adjustment.**
73. **Trade verdict and exact amount needed to even the deal.**
74. **Players and picks to even the trade, with recomputed full-package math.**
75. **Shareable trade URLs with stable asset identity and safe context.**
76. **One-action Clear Calculator with no stale analysis state.**
77. **Recent accepted dynasty trades inside the calculator.**
78. **Dedicated searchable Dynasty Trade Database.**
79. **Comparable/reference-trade matching using recency, overlapping assets, topology/value, and league-format similarity.**
80. **Visible league-format tags on real trades.**
81. **Total absolute value exchanged stacked visualization.**
82. **Consistent asset visual identity across trade analytics.**
83. **Multi-player/pick historical value trend comparison with 7D/30D/3M/6M/1Y/full windows when history supports them.**
84. **Quick Trade Facts comparison: value, pieces, average value/age/rank plus Chase Upside-specific context where valid.**
85. **Trade value-dispersion / concentration analysis.**
86. **Historical value-span analysis: high, low, current, and current location in range.**
87. **Biggest 30-day riser and faller market insights, with expandable horizons later.**
88. **Inline analytical explainers/help for canonical value, VA, equalizers, confidence, dispersion, spans, picks, and other non-obvious analytics.**
89. **Hard canonical pick-value completeness through 2029.** Every valid supported pick must have a finite non-missing canonical value; missing never means zero.
90. **Exact-slot draft-pick trade assets** everywhere the asset is supported once slot is known.
91. **Future generic-pick representation before slot is known** with documented methodology/uncertainty and safe transition to exact identity.
92. **Cross-surface pick-value parity** across Rankings, Trade, ownership, history, APIs, exports, mobile, desktop, and downstream engines.
93. **Mobile-first Trade Calculator capability parity** using the same canonical calculations as desktop.
94. **Dismissible product announcement / CTA banner** for important Chase Upside releases/events.
95. **Selective trusted market/community update embeds** as context, never standalone canonical valuation truth.
96. **About, FAQ, Contact, methodology, and optional support surfaces.**
97. **Responsive footer/mobile navigation support** for informational/support destinations.
98. **Optional non-intrusive monetization placements** that never block analytics or core controls; capability does not require ads to be enabled.
99. **KTC-reference workflow parity audit** before mature Trade Calculator completion: implemented / improved-replaced / owner-rejected / pending.
100. **Mature Trade Calculator end-state acceptance gate** requiring canonical values/picks through 2029, explicit adjustment, fairness/equalizers, real/comparable trades, analytics, sharing, mobile/desktop parity, performance, accessibility, automated regression coverage, and production browser proof.

---

# M. Historical Trade Replay / as-of decision review

101. **Historical Trade Replay / As-Of Team Fit** — A completed trade opened from Trade History must default to a historical replay context rather than evaluating the already-completed package against today's roster. Reconstruct the participating roster(s) immediately before the transaction, apply the trade once to produce the immediate-after state, and run the future canonical Team Fit / Analyze Trade machinery over those as-of states. Provide three explicitly separate lenses: **Original Decision / At the Time**, **Outcome Since**, and **Today's View**. Original Decision mode may use only information available as of the trade timestamp; current values, later performance/injuries, later pick outcomes, later roster moves, and other hindsight data may not leak backward. Historical values/projections/roster state must carry fidelity/provenance such as exact, nearest-prior, reconstructed, partial, or unavailable; missing evidence never becomes zero or today's value. Older trades made before this feature existed should be replayable retroactively where transaction/snapshot evidence permits, with honest degraded states where it does not. The Trade History `Open in Calculator` workflow must be time-context-aware on desktop and mobile. **Binding detailed spec:** `docs/trade/HISTORICAL_TRADE_REPLAY_AS_OF_ANALYSIS_SPEC.md`.

---

# N. Owner additions — 2026-08-14 trade generation and preferences

102. **Best Trade to Send Each Team** — For every other team in the selected league, return exactly one best mutually defensible **player-only** offer. The package must contain the same number of players each direction, no draft picks, grade as a win for the selected team on the canonical Chase Upside trade calculator, and grade as even or a win for the opponent on at least one approved external market calculator — KTC or IDP Trade Calculator — with complete native coverage of every player in the package. Missing/unsupported/imputed external coverage cannot manufacture qualification. Rank qualifying trades by real roster benefit, canonical edge/confidence, opponent roster fit, external acceptability, plausibility, and asset quality rather than the largest calculator discrepancy. If no package satisfies every hard rule, show an honest no-result state rather than relaxing them. This is recommendation only; never silently send a trade.
103. **Persistent personal trade protection** — Add one canonical **user + fantasy-league scoped outgoing-protection layer** that all automatically generated trade recommendations consume. It must support individual untouchable players and NFL-team protection without mutating canonical player data or values. For Jason's configured league preference, **MIN / Minnesota Vikings players are protected from appearing OUTGOING** in generated packages while remaining valid INCOMING acquisition targets. NFL-team protection follows canonical current NFL-team identity dynamically; a player joining/leaving MIN gains/loses team protection unless an individual untouchable rule also applies. Other users are unaffected. Manual Trade Calculator what-if analysis remains free-form. Persistent protection is distinct from temporary package refinement and must be honored by Trade Finder, Trade Suggestions, Golden Upgrades, Package Builder, Best Trade to Send Each Team, equalizers/counters, Trade Desk recommendations, and future generated-trade surfaces.
104. **Generated-package LOCK / EXCLUDE refinement** — Every automatically generated trade package must expose two separate outgoing-player refinement controls. **LOCK** makes that player required in the next regeneration for the current target/opponent/refinement context; the regenerated package must still include him. **EXCLUDE / X** makes that player forbidden in the next regeneration; the regenerated package must not include him. LOCK and EXCLUDE are mutually exclusive for the same player, support multiple active constraints where feasible, trigger immediate regeneration through the **shared canonical package generator**, and remain active through regeneration/ordinary UI refresh until explicitly cleared/reset. They are generation constraints, not post-filters. A temporary X must not silently become a permanent untouchable, though the UI may separately offer promotion to persistent protection. Persistent untouchable/team protection outranks temporary package refinement unless the user intentionally changes the persistent preference. Parent-feature hard rules remain hard: if active locks/exclusions make a qualifying package impossible, show **No qualifying trade found under current constraints** rather than dropping a lock, reintroducing an excluded player, adding picks, changing required package count, or accepting a losing trade. Controls require clear visible state plus accessible labels/tooltips/screen-reader names. Validation must prove locked players survive regeneration, excluded players stay out, contradictory state is impossible, multiple constraints work, honest no-result behavior, MIN protection is Jason+league-specific and outgoing-only, other users are unaffected, and canonical values remain unchanged.

---

# O. C-series zero-loss rule

This 104-item ledger is **not the whole Chase Upside product**. It is one binding source of owner intent that must be unioned with the broader Feature Inventory, Product Backlog Spec, Owner Feature Reconciliation/Appendix, feature-specific specs, Premium design direction, and every later owner addendum.

Before C1, the C-Series Scope Manifest must include or explicitly map every row above. By C completion, no row may remain silently missing/partial/disconnected. See `C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` for the binding completion standard.
