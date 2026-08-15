# Multi-Source Projection Ensemble Plan — 2026-08-15

**Status:** BINDING OWNER-APPROVED C-SERIES METHODOLOGY / SOURCE PLAN  
**Primary destination:** `C5-ROS-01` seasonal intelligence lane, with C1 history/provenance dependencies  
**Implementation authorization:** NONE — `docs/EXECUTION_PLAN.md` remains the only authorization record  
**Issue:** #854

## 1. Owner direction

Projection data must become a first-class **multi-source seasonal evidence system**, not a one-source or two-source accessory.

The site should collect and combine multiple independent projection/model families across the horizons that actually matter:

- weekly;
- rest of season (ROS);
- preseason / full season where useful;
- selected-weeks / remaining-schedule windows where a source exposes them.

This applies to both:

- offense / K / DST where relevant; and
- individual defense, especially DL/EDGE, LB and DB.

The projection ensemble is seasonal/current-football evidence. It must remain separate from canonical dynasty market value and must never directly change `rankDerivedValue` merely because a player is projected to score more this week or this season.

## 2. Current repository reality that this plan must fix

The current ROS registry has several inputs, but only DraftSharks is declared as a projection source. The others are rankings/proxies/ADP-style inputs.

`src/ros/aggregate.py` currently carries a `projection_value` field but intentionally does not consume it. Every row is converted to a normalized rank score. Therefore current `rosValue` is a multi-source ranking index, **not** a true multi-model exact-league projected-points consensus.

The required end state is a separate, explicit projection-evidence/ensemble contract rather than pretending the current ranking aggregate already solves projection consensus.

## 3. Owner-reported access / preferred starting source families

The owner reports permission/access suitable for investigating production ingestion from:

- **CBS Sports Fantasy**;
- **NFL Fantasy**;
- **FantasyPros**;
- **DraftSharks**.

The owner also has an **IDP Show subscription**, which should be investigated as a primary IDP projection source. Subscription access must not be silently equated with unrestricted automated acquisition/redistribution rights; the exact permitted technical path should be recorded before production automation.

**Mike Clay / ESPN projections** are an explicit desired source/model family and should be included in the source census. Record the actual authorized/stable acquisition path before production ingestion rather than assuming an undocumented endpoint is acceptable.

### Initial target ensemble

**Offense — target at least five independent families to evaluate:**

1. CBS Sports Fantasy;
2. NFL Fantasy;
3. FantasyPros;
4. DraftSharks;
5. Mike Clay / ESPN.

**IDP — target at least three strong independent families to evaluate:**

1. The IDP Show;
2. FantasyPros;
3. DraftSharks.

A future internally developed **Brisket projection model** is an approved challenger/additional family for both offense and IDP, provided it is trained/evaluated without temporal leakage and remains clearly labelled as our model rather than attributed to an external provider.

Do not add another paid vendor merely to increase source count. First prove whether the authorized/current-access ensemble is strong enough. Additional vendors such as RotoWire, PFF, FTN or Footballguys are challenger candidates only if they add measurable incremental accuracy, coverage or distribution information worth the cost/licensing burden.

### DFS and betting-market discovery lane

The source census must also actively look for **weekly DFS projection providers** and **sportsbook/player-prop markets** because both can provide useful short-horizon evidence that ordinary season-long fantasy platforms may not.

For DFS sources:

- distinguish actual projected player stat lines / fantasy-point projections from salary, ownership, optimizer output or rankings;
- preserve the DFS scoring system the projection was built for;
- where underlying football stats are available, rescore through Brisket exact-league scoring rather than using the provider's native DFS point total as if it were already comparable;
- treat multiple products from one DFS vendor as one model family unless there is evidence of genuinely independent underlying models;
- record authorized access/automation posture before production ingestion.

For sportsbook/player-prop evidence:

- player props are a **market-implied weekly evidence lane**, not another expert projection family;
- collect authorized, timestamped lines and prices for useful stat markets such as passing/rushing/receiving yards, receptions, attempts/carries, touchdowns, completions and, where offered, defensive tackle/sack/IDP-style props;
- preserve both the line and over/under prices so vig can be removed and the implied probability/quantile can be estimated;
- an over/under line near 50/50 after de-vig can be treated as a **median-like market threshold**, but must not be labelled a mathematically exact median or expected value without a distribution model;
- touchdown and other binary/event props should be converted to de-vigged event probabilities, not forced into a median-stat interpretation;
- if converting prop markets into expected fantasy points, use an explicit Brisket distribution/joint-stat model and preserve uncertainty/correlation rather than simply summing prop lines;
- multiple sportsbooks are often observing the same underlying betting market and must not be counted as independent projection-model votes merely because several books post similar numbers;
- line movement is itself useful timestamped evidence and should be archived where feasible;
- do not allow betting-market evidence to enter canonical dynasty market value.

The weekly ensemble should be able to compare three distinct evidence classes without pretending they are independent copies of the same thing: **projection models**, **DFS projection models**, and **betting-market-implied player outcomes**.

## 4. Canonical projection observation contract

Do not simply average whatever fantasy-point total each site displays.

Whenever possible ingest the source's **raw projected football stat line**, preserve the native total as a diagnostic, and rescore the source through Brisket's canonical league scoring engine.

Every projection observation should preserve at least:

- canonical player ID;
- native source player ID;
- provider/source family;
- model/expert ID where exposed;
- evidence class (`PROJECTION_MODEL`, `DFS_PROJECTION`, `BETTING_MARKET`, etc.);
- consensus ancestry/constituents where known;
- horizon (`WEEKLY`, `REST_OF_SEASON`, `PRESEASON_FULL_SEASON`, `SELECTED_WEEKS`, etc.);
- season and week/date range;
- `observed_at` and source-as-of timestamp where available;
- offense vs DL/EDGE/LB/DB/DST classification;
- raw projected football stat fields;
- native provider fantasy points, if supplied;
- provider scoring basis/preset;
- sportsbook market type, line and over/under prices where applicable;
- floor/median/ceiling/percentiles or distributions where available;
- freshness/update cadence;
- coverage and missing-state semantics;
- source permission/access posture;
- source/snapshot hash;
- parser/model version;
- provenance/run ID.

Missing projected categories remain missing/uncertain. They do not silently become zero.

## 5. Exact-league rescoring

The ensemble should compare sources in the same scoring units by applying the canonical league scoring configuration to each source's projected football stats wherever the required stat fields are available.

This is especially important for custom categories such as:

- five-point passing TDs and other custom QB scoring;
- points per carry;
- first downs;
- distance/big-play bonuses;
- TE reception/scoring differences;
- sacks;
- tackles / assisted tackles;
- tackles for loss;
- passes defended;
- interceptions;
- forced/recovered fumbles;
- return and individual special-teams scoring.

If a source does not project a scored category, preserve the coverage gap. A later Brisket estimator may model missing categories from historical conditional rates, but that modeled quantity must be explicitly attributed to Brisket and must not be presented as if the provider projected it.

Betting-market inputs require a separate transformation step: de-vig the market, estimate the relevant quantile/probability, then map the market-implied stat distribution through exact league scoring. The raw sportsbook line must remain visible in provenance so the derived Brisket quantity can be replayed.

## 6. Independence / lineage rules

The projection ensemble must count **independent model families**, not pages.

Examples:

- FantasyPros consensus and individual experts/models inside that consensus are not automatically independent votes;
- a platform consensus built partly from another model already ingested cannot receive a full extra vote without ancestry handling;
- multiple horizons from the same model are different forecasts, not independent providers for the same target;
- multiple offense/IDP pages from one provider are one provider family unless there is evidence they are genuinely independent models;
- several sportsbooks quoting the same efficient market are correlated market observations, not several independent projection models;
- a DFS site that licenses/derives projections from another already-ingested model must retain that ancestry rather than becoming another independent vote.

Start with simple robust family-level baselines rather than learned weights from a tiny sample:

- equal-family mean;
- median;
- trimmed/robust mean.

Reliability/adaptive weighting is challenger methodology only after sufficient leakage-safe history exists and it beats the simple champion out of sample.

Market-implied evidence should initially be evaluated as a separately named challenger/input class rather than silently receiving the same vote weight as an expert/statistical model.

## 7. Archive before learning

Projection snapshots are perishable evidence. Once a game starts or a source updates its ROS board, the exact pre-event forecast cannot reliably be reconstructed later.

Use the C1 identity/history/provenance substrate. Do not create another unrelated history system.

Archive at least:

- weekly pre-kickoff snapshots;
- ROS snapshots on a defined cadence;
- preseason/full-season baseline snapshots;
- DFS projection snapshots at a defined pre-kickoff cutoff when used;
- sportsbook/player-prop line + price snapshots and meaningful line movement where authorized/feasible;
- model/source version and freshness;
- the raw/stat inputs needed to replay Brisket rescoring and ensemble construction.

The C-Series detailed map should schedule projection archival capture as early as is safe **once explicitly authorized**, even if downstream Game Day/Playoff/UI consumers are not ready yet.

## 8. Validation / champion-challenger

Evaluate each source family and the ensemble against realized exact-league scoring by horizon and position.

At minimum measure:

- MAE;
- RMSE;
- signed bias/error;
- rank/order correlation;
- calibration/reliability when distributions or floor/ceiling probabilities exist;
- offense and IDP separately;
- QB/RB/WR/TE/DL-EDGE/LB/DB separately where sample permits;
- weekly vs ROS vs preseason/full-season separately;
- injury/inactive handling;
- tail/boom-bust behavior;
- freshness and missingness;
- DFS projection accuracy separately from conventional fantasy projection families;
- sportsbook implied-probability/quantile calibration and whether line movement adds signal;
- whether the ensemble actually beats the strongest simple single-source baseline out of sample;
- whether adding DFS and/or betting-market evidence measurably improves the projection-only champion rather than merely adding correlated noise.

Follow the site's P6 champion/challenger and pinned-input rules. Do not tune on hand-picked examples until the results merely look right.

## 9. C-Series decomposition

This work belongs primarily under `C5-ROS-01`, with C1 history/provenance dependencies and downstream consumers in C5/C7.

The detailed C-Series execution map should create bounded units equivalent to:

1. **C5-PROJ-A — source capability/access/lineage census**  
   Confirm horizon, coverage, raw-stat fields, offense/IDP positions, cadence, ancestry, and exact authorized acquisition path for CBS, NFL Fantasy, FantasyPros, DraftSharks, IDP Show and Mike Clay/ESPN; actively inventory DFS projection vendors and authorized sportsbook/player-prop data paths; record any source that is rankings-only rather than a true projection model.

2. **C5-PROJ-B — canonical projection-stat schema + exact-league rescoring**  
   One typed observation contract; one scoring owner; explicit missing categories; source/native vs Brisket-estimated fields kept separate; betting-market line/price observations retain their raw market provenance.

3. **C5-PROJ-C — weekly offense + IDP ensemble**  
   Independent-family consensus, disagreement, freshness, coverage and uncertainty, with DFS and betting-market evidence evaluated as separately lineage-aware weekly inputs rather than blindly pooled votes.

4. **C5-PROJ-D — ROS / full-season offense + IDP ensemble**  
   Horizon-matched source set and consumer contract; no weekly/ROS semantic mixing. DFS/betting weekly data does not masquerade as ROS evidence.

5. **C5-PROJ-E — immutable archive + leakage-safe backtesting**  
   Retain source/ensemble predictions and weekly market observations before outcomes; accuracy lab by horizon/position/source family/evidence class; champion/challenger evidence.

6. **C5-PROJ-F — consumer migration + production proof**  
   Migrate seasonal consumers to the canonical projection service; honest degraded states; source lineage/confidence; production freshness/performance proof.

These labels are execution-map decomposition guidance. They do not themselves authorize implementation, and reconciliation may convert them into manifest rows if that improves scope integrity.

## 10. Downstream consumers

Use the projection ensemble only where its horizon matches the quantity being predicted.

Intended consumers include:

- `C5-GD-01` Game Day Command Center — weekly player distributions and best-ball matchup simulation;
- `C5-PLAY-01` playoff/championship engine — ROS remaining-production distributions;
- `C5-POW-01` weekly power rankings — current-season projection component;
- `C1-PICK-03` owned-pick slot distribution — indirectly through team-strength/outcome projections;
- Competitive Posture/current-season contention context where explicitly named;
- CE-12 Lineup Intelligence;
- CE-08 Projections & Stats Hub;
- Universal Player Profile projection/stat section;
- waivers where future production is relevant;
- trade/Trade Desk current-season context only as a separately named seasonal dimension;
- public-safe Game Day / weekly reporting outputs where allowed.

No downstream consumer may quietly reimplement projection averaging, scoring conversion, source weighting, market de-vigging, prop-to-distribution conversion, or missing-data rules locally.

## 11. Product acceptance direction

By C completion, for an eligible player the site should be able to answer:

> What do several independent models expect this week / ROS, what does each forecast mean under this exact league scoring, what do DFS models and the betting market imply for the current week, how much do these evidence classes disagree, how fresh/complete is the evidence, and how accurate have the source models, market signals and Brisket ensemble actually been?

One provider's projection, one generic PPR fantasy-point total, or one sportsbook line is not sufficient.
