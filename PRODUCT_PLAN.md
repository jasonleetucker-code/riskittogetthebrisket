# Product Plan — Start Here

The canonical product/roadmap front door for **Risk It To Get The Brisket** is:

**[`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md)**

For current authorized execution order, read:

**[`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md)**

For the approved early-data / future-model direction for ingesting source-native 1QB/Superflex/TE-premium/IDP **dynasty** format variants and eventually normalizing external dynasty rankings to arbitrary league settings, read:

**[`docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md`](docs/MULTI_FORMAT_SOURCE_NORMALIZATION_SPEC.md)**

That specification explicitly separates **collect/archive alternate-format dynasty observations early** from **do not use them to change production values until the normalization methodology is validated and owner-approved**. It also preserves KTC's Off / TE+ / TE++ / TE+++ ladder as four same-source calibration states, not four independent consensus votes.

For the separate approved use of **redraft / rest-of-season / current-season** rankings and projections in seasonal competitive intelligence — including ROS Strength, playoff/championship probabilities, Pick Forecast inputs, contender/rebuilder classification, Game Day, and lineup/current-season modeling — read:

**[`docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md`](docs/REDRAFT_ROS_INTELLIGENCE_SPEC.md)**

The redraft/ROS domain is intentionally separate from dynasty valuation. Seasonal evidence may improve current-season predictions, but it is prohibited from leaking into canonical dynasty player/pick values or dynasty source consensus.

For the canonical **Playoff Predictor** requirement — deriving each connected league's real postseason structure and producing **Make Playoffs %**, **Earn Bye %**, and **Win Championship %** from one league-aware seasonal simulation rather than duplicated or hard-coded 6-team/2-bye logic — read:

**[`docs/PLAYOFF_PREDICTOR_SPEC.md`](docs/PLAYOFF_PREDICTOR_SPEC.md)**

That specification treats the existing playoff/championship simulation code as the starting point, requires one canonical probability owner, requires requested-league playoff settings/tiebreak/bracket fidelity, and makes the predictor a reusable seasonal output for public-safe league presentation, Pick Forecast, contender classification, and Game Day without leaking into canonical dynasty value. Sleeper/host data is the preferred source of truth for each connected league; the owner's primary league is explicitly confirmed as **7 playoff teams with one #1-seed bye**, with the confirmed rule serving only as a provenanced fallback/regression fixture rather than a universal default.

For **Game Day weekly probability intelligence** — keeping the existing matchup-win probability but auditing/calibrating it for maximum defensible accuracy, and adding **Beat League Median %** for leagues with the extra median result — read:

**[`docs/GAME_DAY_PROBABILITY_SPEC.md`](docs/GAME_DAY_PROBABILITY_SPEC.md)**

That specification requires `Win Matchup %` and `Beat Median %` to come from the same league-aware weekly score simulation where possible. In median-game leagues, every simulation draw must simulate the entire league week, derive that draw's median threshold from the league-wide scores, and then determine both the H2H and median outcomes. It also requires historical prediction archives and calibration testing rather than assuming the current matchup formula is already optimal.

For the Brisket Honors eligibility rules tying **League MVP** and **Manager of the Year** to actual competitive success while deliberately keeping **GM of the Year** and performance/rookie/positional awards separate, read:

**[`docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md`](docs/BRISKET_HONORS_ELIGIBILITY_SPEC.md)**

That specification requires League MVP and Manager of the Year candidates to be on a team currently/finally in the championship playoff field **and** above .500 under the requested league's real standings rules, while preserving Realized Lineup VORP as the player-performance foundation and allowing rebuilding teams to remain eligible for GM of the Year.

For the required repair of historical Trade History grading — separating **Current Grade**, **At-the-Time Grade**, and **How It Aged**, with contemporaneous player/pick snapshots, provenance, fail-closed missing-history behavior, and methodology-consistent aging — read:

**[`docs/TRADE_HISTORY_AGING_SPEC.md`](docs/TRADE_HISTORY_AGING_SPEC.md)**

That specification explicitly forbids using current values or future snapshots as if they were historical truth, requires first-class historical pick values, and makes the current fixed ±200 aging threshold evidence-gated rather than final methodology.

For the newly approved high-value **AI/front-office feature family** — **Ask Brisket, Roster Path Optimizer, Edge Alerts, Trade Liquidity & Market Depth, Negotiation Coach, and League Truth** — read:

**[`docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md`](docs/AI_FRONT_OFFICE_INTELLIGENCE_SPEC.md)**

Those features are orchestration/decision surfaces over canonical systems, not permission to build duplicate valuation, trade, playoff, manager, market, or roster engines. Ask Brisket's paid-LLM activation is explicitly cost-gated; the retrieval/orchestration architecture may be built independently.

For the expanded **CE-01 Market Trade Ledger / recent real-trades** methodology — format-aware recent trade filtering, exact/near/normalized comps, market liquidity, package realism, negotiation evidence, Market Pulse, and a future evidence-gated Real Trade Market Value signal — read:

**[`docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`](docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md)**

That specification requires comparable dynasty trades to preserve league-format metadata and recency, forbids naïve raw-trade averages from directly repricing canonical values, and keeps the broad Market ledger separate from Sharp and Insider populations. It also explicitly approves a **multi-source acquisition strategy**: discover/ingest known public Sleeper leagues using the same general account→league discovery pattern already used by the Sharp tracker; ingest KTC Trade Database data under the owner's confirmed permission and within the granted scope; support additional authorized sources later; and normalize all sources into one canonical ledger. Cross-source deduplication is mandatory: proven matches collapse to one underlying trade while ambiguous same-package/date matches remain explicitly unresolved rather than being blindly double-counted or falsely deleted.

For the owner-required **Sharp Tracker / Insider Trading experience and performance contract** — including the global **five-second maximum useful-state rule**, repair of the current Sharp cache-busting/no-store architecture, off-request-path materialization, validated Sharp-cohort methodology, and the connected Sharp → league-mate behavior → roster need → possible return → negotiation workflow inspired by useful competitor concepts — read:

**[`docs/SHARP_INSIDER_EXPERIENCE_PERFORMANCE_SPEC.md`](docs/SHARP_INSIDER_EXPERIENCE_PERFORMANCE_SPEC.md)**

That specification treats the current multi-minute Sharp Tracker latency as a high-priority product defect. Five seconds is an absolute failure ceiling rather than a normal target: warm/cached views should feel essentially immediate, expensive Sharp computation belongs off the user request path, stale-but-valid snapshots should be served while refresh happens, and no interactive screen may hide minutes of work behind a spinner. It preserves the distinction between global qualified-Sharp behavior and selected-league Insider behavior while expanding the actionable workflow to exact league settings, canonical team needs, full trade receipts/packages, manager drill-downs, similar-value/possible-return assets, Market Trade Ledger evidence, Trade Desk and Negotiation Coach.

For the owner's explicit policy on **competitor architecture / workflow reuse**, read:

**[`docs/COMPETITOR_REUSE_POLICY.md`](docs/COMPETITOR_REUSE_POLICY.md)**

Publicly observable architecture, workflows, UX patterns, feature concepts, and implementation ideas from free/public sites are fair game to reproduce, adapt, combine, or improve when they are the best fit for Brisket. There is no originality requirement and no requirement to make an architecture different merely because a competitor uses it. This policy supersedes older subordinate wording that said competitor architecture must not be copied.

Do not select implementation work directly from old TODOs, addenda, competitor research, `UNIMPLEMENTED_BACKLOG.md`, or `docs/master-site-audit/NEXT_STEPS.md` / `REPAIR_ROADMAP.md`. Their durable requirements/evidence are subordinate to the hierarchy defined in the Master Product Plan.
