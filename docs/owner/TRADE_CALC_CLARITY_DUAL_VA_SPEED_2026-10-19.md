# Owner directive 2026-10-19 — Chase Upside — Trade Calculator Clarity, Dual Value Adjustment & Speed
Repository: jasonleetucker-code/riskittogetthebrisket

> Verbatim owner directive, received in the coordination session 2026-10-19. Delivered in
> separate lanes (War Room clarity, dual Value Adjustment + Second Opinions, analyze speed).
> Capture is not implementation authorization beyond what the directive itself says
> (`docs/EXECUTION_PLAN.md` §0); every named evidence gate still applies. Intake:
> `docs/OWNER_REQUESTED_TODO.md` ("Added 2026-10-19 — Trade Calculator clarity, dual Value
> Adjustment and speed").

Owner directive
Improve the Trade Calculator in three coordinated areas:
1. Make the Trade War Room dramatically easier to understand.
2. Expose both Chase Upside's approved Value Adjustment and the existing KeepTradeCut adjustment for comparison, including throughout Second Opinions.
3. Diagnose and materially improve the Trade War Room's long wait times.
This is a non-DFS, already-active Calculator feature. Coordinate with the current Trade Calculator completion lanes and avoid competing modifications to canonical owners.

1. Simplify the Trade War Room
Use the Premium Sports Intelligence Direction A design system.
The page should answer these questions immediately:
* Would I make this trade?
* Am I gaining or losing market value?
* Does it help or hurt my projected weekly lineup?
* Does it fit my roster?
* What's the biggest reason for the recommendation?
Make the existing canonical backend decision the only official recommendation. Do not construct another recommendation in the UI from the displayed metrics.
Use plain-English copy. Examples:
* "Market" → "Trade value"
* "Roster" → "Impact on your team"
* "Feasibility" → "Does it fit your roster?"
* "−5.7 best-ball pts/week" → "Your projected lineup scores about 5.7 fewer points per week"
* "Roster 58 → 58 of 58" → "The trade fits. No player cut needed."
* "Expected legal-lineup scoring, ±0.5 simulation error" → keep the uncertainty accessible in the detailed methodology view, explained appropriately as a model estimate.
Don't hide material uncertainty or missing data; simply explain it better.
Reorganize the view:
Immediately visible:
* One recommendation and its confidence.
* Two concise, genuinely distinct reasons.
* Trade value difference.
* Projected weekly points impact.
* Roster legality and any required cut.
* A compact entry point for Value Adjustment comparison.
Expandable:
* Player-by-player lineup impact.
* Before/after lineup projection.
* Supporting arguments, objections, and uncertainty.
* Exact source inputs, limitations, simulations and methodology.
* Detailed Value Adjustment calculations.
Don't repeat identical conclusions in several panels. Remove redundant explanatory language, excessive all-caps labels, and unnecessary technical jargon.
Use readable tables where comparison helps; retain mobile parity and accessibility. No decorative cards, gradients, unnecessary rounded panels, or excessive vertical spacing.

2. Add both Value Adjustment methods
Both models already exist:
* Active: geom_q078_v1, q = 0.78.
* KTC comparator: ktc_2026_04.
Reuse the existing canonical dispatch in frontend/lib/trade-logic.js and src/valuation_math/package_model.py. Do not duplicate either mathematical implementation.
Chase Upside remains the active authoritative model. KTC is a read-only analytical comparator, not a second final verdict or a combined weighting factor.
Provide a compact comparison showing, when available:
* Raw totals for each side.
* Chase Upside adjustment and adjusted totals.
* KTC-method adjustment and adjusted totals.
* The resulting gap under each method.
* Whether the methods disagree about which side has more adjusted value.
When the methods agree, say so simply. When a one-for-one trade receives no adjustment under either method, explain that instead of filling the screen with duplicate numbers.
Label the alternate method "KTC adjustment method", and clearly distinguish applying that method to Chase Upside values from viewing actual KTC-native values.
Never blend the two adjustments, add them together, average their outputs, or change an asset's canonical value.

3. Extend this throughout Second Opinions
Update the canonical Second Opinions row-building and evaluation owners, not an independent UI-only approximation.
For each vendor opinion, calculate both models using the same eligible, normalized, per-asset inputs for that vendor's trade comparison. Compute them as two alternative whole-package adjustments, not sequential adjustments.
Preserve all existing coverage rules:
* A source's eligible normalized value where actually published and eligible.
* The exact published Chase Upside canonical fallback where the source lacks a usable value.
* Honest unavailable/incomplete status if an asset cannot be priced.
* FULL_SOURCE, HYBRID_ESTIMATE and CHASE_ONLY_BASELINE distinctions.
* One independent vote per correlation family.
* No independent voting credit from canonical fallback.
* No change to the active source tally merely because the KTC comparison was enabled.
The KTC-method comparison must not be misrepresented as that vendor's own proprietary package-adjustment policy.
The default Second Opinions display stays compact. A single "Compare adjustments" control reveals the additional model's values for all source rows, with per-source expanded details when useful.
Desktop can use an additional comparison column. Mobile must remain easy to scan.
Add comparison indicators only for meaningful disagreement; don't fill every row with badges.
Support offense, IDP, picks, multiple assets, canonical fallbacks, incomplete sources and unpriced assets. Where a comparison cannot be computed reliably, show an explicit unavailable state rather than zero.

4. Diagnose and speed up trade analysis
The owner observed /api/trade/analyze taking approximately one minute for a trade, after initially showing a load failure during another attempt.
First reproduce and instrument the real request path to identify where the time goes:
* Request and authentication handling.
* League and team resolution.
* Sleeper overlay retrieval where required.
* Valuation and contract preparation.
* Competitive-posture preparation.
* Roster and best-ball simulation.
* Comparable-trade retrieval.
* Decision synthesis, JSON serialization and response delivery.
* Browser request and render time.
The frontend currently has a 700 ms debounce; that alone doesn't explain a one-minute response. Find the actual bottleneck instead of guessing.
Make safe, measurable improvements through appropriate caching, request deduplication, indexed reads, shared immutable computations, nonblocking tasks and removal of unnecessary repeat calculations.
Do not reduce simulation correctness, sampling integrity, league-specific scoring accuracy or evidence requirements merely to improve speed.
Prefer displaying the already-computed trade-value summary immediately while deeper personalized analysis completes. Do not present an unofficial provisional YES/NO recommendation.
Improve the loading experience:
* Show meaningful progress states where the server can truthfully provide them.
* Preserve the existing trade while loading.
* Cancel or invalidate stale requests after changes.
* Handle temporary failure with a clear Retry option.
* Avoid infinite loading states.
* Show unavailable supporting analysis honestly while preserving completed results.
* Do not leak private league data through shared caches or logs.
Measure warm and cold response latency on production-shaped inputs, including the p50 and p95. Aim for single-digit-second completion, ideally under five seconds for ordinary warm analysis if achievable without sacrificing accuracy. Report actual results rather than claiming an unsupported performance target was reached.

5. Tests and release acceptance
Use the live War Room screenshot example of A.J. Brown coming in and Justin Herbert going out.
The current displayed observations are:
* Receive 4,654 of value.
* Send 5,848 of value.
* Difference −1,194.
* Projected team impact −5.7 points per week.
* Legal roster size unchanged at 58 of 58.
* A.J. Brown appearing in the optimal lineup in 61% of the simulated weeks.
These are observed UI values, not universal expected outputs. Validate against the current canonical test contract and data version; don't hardcode the example.
Verify that the plain-English presentation preserves the exact underlying calculations.
Test the alternate KTC comparison against existing KTC parity fixtures, including known non-monotone cases. Test the approved geometric model independently. Confirm the normal official decision does not change when comparison is toggled.
Add Second Opinions cross-model tests with multiple source families, fallback-covered assets, IDP/picks, and unavailable evidence.
Run full desktop/mobile visual and accessibility tests, targeted performance tests, independent review, current exact-head CI, and production verification.
Produce separate PRs if that reduces conflicts between the War Room performance owner, Second Opinions model owner and shared UI owner.

Required outcome
Deliver a faster, simpler Trade Calculator where a new user can understand the trade recommendation at a glance, and an experienced dynasty user can compare Chase Upside's package adjustment with KTC's familiar method at every relevant level without confusion.
The official model remains geometric q = 0.78. No silent valuation changes, no duplicate recommendation engines, no hidden evidence gaps, and no unnecessary owner questions.
