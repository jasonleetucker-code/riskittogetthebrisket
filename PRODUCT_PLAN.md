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

For the required repair of historical Trade History grading — separating **Current Grade**, **At-the-Time Grade**, and **How It Aged**, with contemporaneous player/pick snapshots, provenance, fail-closed missing-history behavior, and methodology-consistent aging — read:

**[`docs/TRADE_HISTORY_AGING_SPEC.md`](docs/TRADE_HISTORY_AGING_SPEC.md)**

That specification explicitly forbids using current values or future snapshots as if they were historical truth, requires first-class historical pick values, and makes the current fixed ±200 aging threshold evidence-gated rather than final methodology.

Do not select implementation work directly from old TODOs, addenda, competitor research, `UNIMPLEMENTED_BACKLOG.md`, or `docs/master-site-audit/NEXT_STEPS.md` / `REPAIR_ROADMAP.md`. Their durable requirements/evidence are subordinate to the hierarchy defined in the Master Product Plan.
