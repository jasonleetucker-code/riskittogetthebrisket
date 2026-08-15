# Owner Feature Addendum — Roster Age-Value Portfolio / Young Core Index

**Owner decision date:** 2026-08-14  
**GitHub tracking:** #838  
**Status:** APPROVED PRODUCT BACKLOG REQUIREMENT; NOT AUTHORIZATION TO PREEMPT ACTIVE FOUNDATION WORK

## Goal

Add a league-relative roster age/value intelligence surface to every fantasy-team profile/home page so a manager can answer:

- How is this roster's meaningful dynasty value distributed across player ages?
- Which position groups are older or younger than the rest of the league?
- Where does this roster need to get younger?
- Which team owns the strongest combination of young + valuable talent overall?
- Which team has the strongest young valuable QB, RB, WR, TE, DL/EDGE, LB, or DB group?

This should extend the existing value-concentration/portfolio thinking already approved for NFL-team exposure into an age/value portfolio view.

## Canonical guardrail

Do **not** create a second age-adjusted player valuation. Canonical dynasty value already embeds age and market expectations. This feature describes roster construction; it does not alter player value.

Inputs must be:

- canonical `My League` player value;
- canonical player identity;
- authoritative DOB/age with a consistent as-of date;
- canonical Team Strength meaningful-roster grouping for the primary/core view.

Missing age remains missing. Draft picks are excluded from age math rather than treated as age zero.

## Required outputs

### 1. Value-Weighted Core Age

Primary roster-age metric:

`sum(player_age * canonical_value) / sum(canonical_value)`

Use the canonical meaningful Team Strength group for the primary version so low-value young bench players cannot artificially make a roster look young. A full-roster version may be shown as secondary context.

### 2. Age-Value Distribution

Show how much canonical roster value sits at each age/age band. Recommended detailed visualization:

- X-axis: player age;
- Y-axis: canonical value;
- one point per player;
- aggregate value-by-age distribution / histogram or age-band share view;
- player tooltip/click with player, position, exact age, canonical value, and share of team value.

### 3. Position Group Profiles

For QB, RB, WR, TE, DL/EDGE, LB, and DB show:

- value-weighted age;
- age-value distribution;
- share of team value;
- league rank and percentile;
- difference from league median;
- clear indication when the group is meaningfully older than league peers.

### 4. League-Relative Comparison

Every fantasy team should receive league-relative overall and position-group ranks/percentiles. Provide an expanded comparison surface that can overlay/filter teams while keeping the default team profile compact.

### 5. Young Core Index

Create a 0–100 league-relative roster-construction index answering:

> Who owns the strongest concentration of meaningful young talent?

Requirements:

- reward both youth and meaningful canonical value;
- normalize youth by position so age expectations differ for QB vs RB vs other positions;
- weight youth by meaningful canonical value so low-value youth cannot dominate;
- aggregate the meaningful core, then league-percentile the result;
- expose component breakdown / explanation;
- validate the scalar against intuitive league examples before treating it as canonical;
- label it clearly as a roster-construction index, not a new player-value model.

A preferred starting formulation is position-relative youth percentile/score weighted by canonical value within the meaningful core, followed by league normalization. Exact formula should be validated against the real league before finalization.

### 6. Young Core by Position

Provide overall and positional leaderboards/rankings such as:

- Young Core — Overall
- Young QB Core
- Young RB Core
- Young WR Core
- Young TE Core
- Young DL/EDGE Core
- Young LB Core
- Young DB Core

The intent is “youngest **valuable** room,” not simply lowest arithmetic average age.

## Team-profile UX

Each team profile/home page should get a compact **Age & Value / Roster Window** module containing:

- Young Core Index + league rank;
- value-weighted core age;
- compact age-value chart;
- position rows with age/value context and league percentile;
- flags for position groups where the roster is old relative to the league;
- expansion into the detailed league comparison view.

## Future historical extension

Once canonical historical value snapshots exist, support trend views such as:

- “Roster became 0.8 years younger while retaining 94% of core value.”
- age/value distribution before vs after a trade;
- Young Core Index movement over time.

Historical trend is downstream of snapshot foundations and must not block the initial current-state feature.

## Canonical dependencies / sequencing

This feature belongs under **Canonical Roster Intelligence** and must reuse:

1. canonical player value;
2. canonical player identity / age data;
3. Team Strength meaningful-roster grouping;
4. Team Weakness / position model;
5. league settings / IDP position model;
6. historical value snapshots for later trends.

Place it after/with the C-series Team Strength + Team Weakness foundations, not before them.

## Master-document reconciliation

Before the C-series/product roadmap is considered fully reconciled, this requirement must be folded into:

- `docs/MASTER_PRODUCT_PLAN.md` — Canonical roster intelligence;
- `docs/OWNER_FEATURE_INVENTORY.md` — new roster-intelligence feature row;
- `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` — detailed methodology/UX requirements;
- the dependency-correct C-series sequencing / execution record.

Until those canonical documents are reconciled, this addendum plus owner instruction dated 2026-08-14 and GitHub issue #838 preserve the requirement without authorizing premature implementation.
