# Game Day source access (2026-09-25)

## Canonical access posture: OWNER_ATTESTED_AUTHORIZED

**Owner attestation (2026-09-25, explicit, in writing):** The owner explicitly attests that permission
exists for Calculator's current automated ingestion and project use of the sources already integrated,
or intentionally being integrated, into the existing source portfolio. Public terms are not the basis
for that permission. The repository does not hold or reproduce any private permission correspondence
unless it is separately provided.

**Named sources** include, but are not limited to: Sleeper, RotoWire, ESPN, IDP Show, Fantasy Nerds,
SportsDataIO, FantasyPros, DraftSharks, IDP Trade Calculator, DLF, FantasyCalc, Dynasty Daddy,
Fantasy Navigator, PFK and related existing feeds, Flock Fantasy, Yahoo/Boone where currently used,
and every other source already part of Calculator's ingestion/source system.

**Consequence.** These sources are no longer "owner decision required", and they are not treated as
unauthorized because public-facing terms do not document the owner's private permission. They need no
per-source re-approval. The Game Day source-access blocker is removed.

**Scope boundary.**

- This is not blanket permission to discover and ingest arbitrary new websites. A genuinely new
  provider, outside the existing portfolio and not explicitly owner-directed, still goes through
  normal source intake and permission verification.
- Materially broadening an existing provider into a different product, feed or use case than the
  intended integration must be recorded as an expansion; it must not be done silently.
- A new permission decision is surfaced only when:
  - the provider is genuinely new;
  - the access mechanism or use case is materially outside the intended integration; or
  - the owner changes or revokes the authorization.

**Credentials are separate from permission.** Several named sources are keyed or subscription APIs
(for example Fantasy Nerds, SportsDataIO and FantasyPros). The attestation covers permission. Where
the repository has no configured credential for a source, the owner configures it through the
environment or secrets; agents never enter or handle credentials themselves.

## Background evidence: public terms (context only, not the basis of permission)

Public terms do not supersede or define the private permission the owner states he possesses. They are
kept here only as context, retrieved 2026-09-25, with short excerpts.

- **Sleeper.**
  - Documented API: "free to use for non-commercial purposes", with commercial use handled through
    licensing (https://docs.sleeper.com/).
  - The `/projections` and `/stats` endpoints are undocumented.
  - Rows carry `company: "rotowire"`.
- **RotoWire.** The public terms (rotowire.com/termsandconditions.php) describe personal,
  non-commercial use.
- **ESPN.** Falls under the Disney Terms of Use (disneytermsofuse.com). ESPN's public developer API
  closed in 2014, and `site.api.espn.com` is documented only by the community. The repo's existing
  ESPN integrations are:
  - injuries, `src/nfl_data/injury_feed.py`;
  - depth charts, `src/nfl_data/depth_charts.py`;
  - news, `src/news/providers/espn*.py`;
  - the Mike Clay PDF.
- **Keyed and licensed providers.**
  - Fantasy Nerds: api.fantasynerds.com; weekly stat projections, Weeks 1–18.
  - SportsDataIO: sportsdata.io; weekly stat-level projections plus live game data.
  - FantasyPros: fantasypros.com/api-data; weekly and ROS stat lines.
  - Sportradar and MySportsFeeds: live status, quarter and clock.
- **Not currently wired.** Coverage details for these providers (K/IDP depth, cadence) are recorded
  on each source's census entry once it is wired. Live game state from ESPN or SportsDataIO, and
  multi-source weekly projections, are the Game Day inputs to build next.

## Game Day source roles (one owner each)

| Concern | Owner module | Candidate authorized sources |
|---|---|---|
| Live game state (status, period, clock, OT, delay, postponement, final) | `src/nfl_data/live_game_state.py` | ESPN scoreboard; SportsDataIO where configured |
| Factual live player stats and corrections | `src/nfl_data/sleeper_live_stats.py` | Sleeper stats; SportsDataIO where configured |
| Weekly projection ensemble | `src/ros/projection_ensemble.py` + weekly sources | RotoWire via Sleeper, Fantasy Nerds, SportsDataIO, FantasyPros, DraftSharks, IDP Show where appropriate. Independence is recorded by source family and ancestry, so there is no double counting of an aggregator and its constituents, or of several horizons from one model |
| Exact league scoring | `src/league_intel/scorer.py` | Stat-level projections are rescored here. Uncovered categories are preserved as uncovered, or estimated by a separately validated estimator labelled as OUR estimate; never zero |
| Best-ball lineup | `src/ros/lineup.py` | — |
| Game Day simulation | `src/ros/game_day_sim.py` | — |
