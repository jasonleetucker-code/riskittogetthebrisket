# Game Day source access: evidence for an owner decision (2026-09-25)

**Status: evidence only. Nothing here is an authorization.** Both Game Day source candidates are
implemented behind default-off flags (`sleeper_weekly_projections`, `game_day_live_game_state`) and
are **not activated**. The owner has not approved either, and has not accepted any licensing or terms
risk (`docs/OWNER_REQUESTED_TODO.md`, Calculator campaign entry). Quotes are short excerpts with
their sources and were retrieved on 2026-09-25.

## 1. Sleeper weekly projections (RotoWire content)

- **Undocumented endpoint.** The official docs (https://docs.sleeper.com/) list user, league, draft,
  player, trending and state endpoints. They list no `/projections` or `/stats`.
- **Sleeper API terms.** The docs say "free to use for non-commercial purposes", and "For commercial
  use of the Sleeper API, please reach out to us directly to discuss licensing".
- **Sleeper Terms of Use** (support.sleeper.com, updated 2026-08-27): §9.2 grants a licence "for your
  personal and non-commercial use" and forbids redistributing it or creating derivative works.
- **Content owner.** Every row observed carries `company: "rotowire"`. RotoWire's Terms
  (rotowire.com/termsandconditions.php, updated 2026-09-19) provide content "only for your own
  personal, non-commercial use". They forbid reproducing or distributing content "obtained from or
  through the Services", and forbid collecting it "by any automated means".
- **Would be needed:** written permission from RotoWire (the content owner) and from Sleeper (the
  channel), or a directly licensed feed.

## 2. ESPN public scoreboard, and the existing ESPN integrations

- **Terms.** ESPN falls under the Disney Terms of Use (disneytermsofuse.com, updated 2024-05-24):
  - §2.B.x forbids access or extraction "using a robot, spider, script, or other automated means";
  - §2.A grants a licence "for your personal, noncommercial use only".
- **No public API.** ESPN closed its public developer API in 2014, so `site.api.espn.com` is
  documented only by community reverse-engineering.
- **Existing ESPN integrations, which run without any recorded authorization:**
  - the injury feed, `src/nfl_data/injury_feed.py`, polled every 4 hours;
  - depth charts, `src/nfl_data/depth_charts.py`, 32 calls nightly;
  - player news, `src/news/providers/espn_player.py`;
  - RSS, `src/news/providers/espn.py`;
  - the Mike Clay PDF from `g.espncdn.com`.
- **How they were switched on.** They were enabled in commits 96fc4a226 (2026-04-25) and 4230db191
  (2026-09-01). The only rationale on record is engineering risk:
  `docs/upgrade_phases_1_10.md:310`, "low risk, graceful degradation already proven".
- **No decision record.** No decision record, planning record or census entry records ESPN terms or
  permission.
- **So the scoreboard cannot inherit a class.** No authorized class exists to inherit, and live game
  polling is a different endpoint and usage class from those batch feeds.
- **Would be needed:** written permission from ESPN/Disney, or a licensed live feed.

## 3. Legitimate alternatives (facts, not recommendations)

**Weekly per-player projections**

| Source | Terms / cost (published) | Coverage |
|---|---|---|
| Fantasy Nerds API | Official; $499/yr Standard, $2,999/yr Extended Commercial (api.fantasynerds.com pricing) | Weekly stat projections Weeks 1–18, QB/RB/WR/TE/K; IDP detail unconfirmed |
| FantasyPros API | Official; personal-use tier, or a commercial tier with redistribution rights (custom price) | Weekly and ROS full stat lines; K/IDP unconfirmed |
| SportsDataIO | Official; production pricing via sales | Weekly stat-level plus points; IDP game projections |
| MySportsFeeds | Official; separate personal and commercial tiers, plus a PROJECTIONS add-on | Game-by-game stat projections |
| Yahoo Fantasy API | Official OAuth, API agreement plus attribution | Through league context; the consensus may include RotoWire |
| nflverse ffopportunity | Open (CC BY-SA 4.0) | Retrospective expected points, **not** a forward projection |
| The IDP Show | Subscription; automated-use scope unrecorded | In-season weekly IDP *rankings*, not stat lines |

**Live game clock and status**

- Licensed providers: Sportradar (status, quarter and clock), Genius Sports (the NFL's official
  distributor), SportsDataIO, MySportsFeeds.
- Free sources give no clock: nflverse schedules update status only, and Sleeper `/v1/state` gives
  season and week only.

## 4. Questions only the owner can answer

1. Does the site count as **commercial** for licensing purposes? Most of the terms above turn on this.
2. **Sleeper/RotoWire:** seek written permission, or keep the flag off permanently and choose another
   weekly source?
3. **Existing ESPN feeds** (injuries, depth charts, news): record a decision to continue, pause, or
   seek permission. This is a separate question from Game Day.
4. **ESPN scoreboard:** seek permission for live polling, or keep the flag off?
5. If licensed options are in scope: which positions and horizon are required (stat-level K and IDP?),
   and is a budget in scope? This asks about scope only, not a purchase.
6. **IDP Show:** does the subscription permit automated collection? The census reads
   `SUBSCRIPTION_SCOPE_UNRECORDED`.
7. Until these are resolved, Game Day runs on the labelled preseason fallback plus nflverse schedule
   status, with no observed clock. That is a fallback state, **not** completion of the live dashboard
   (owner requirement).

**Unverified:** Sleeper's appearance on RotoWire's partner page, Yahoo's full API agreement text (the
link returned 404), the NFL Fantasy API docs (the host did not resolve), FantasyPros K/IDP coverage,
and SportsDataIO trial terms.
