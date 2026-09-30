# DFS — sources, independence and acquisition policy

## 1. Registry

`config/dfs/source_seeds.json` preserves every owner-supplied seed verbatim: 74 websites
(Appendix A), 6 sportsbooks (B), 29 podcasts (C) — 109 entries with stable `seedId`s
(`A-001`…, `B-001`…, `C-001`…). Seeds start `accessState: "unverified"` /
`sourceCategory: "unknown"`: **a seed is a name to investigate, not an integration.**
`tests/dfs/test_source_seeds.py` pins the counts and refuses any non-`unverified` state or live
connector without recorded evidence. Websites and podcasts are resolved (§5, §6); sportsbooks are not.

Resolving a seed fills: canonical identity + aliases (`aliasOf`, never deletion), official domain,
owner, sports/platforms, category, independence group, access state, acquisition method, license
assessment (collection / retention / transformation / display / training / redistribution),
cost/quota, cadence, connector state. Known duplicate names across appendices ("One Week Season"
site + podcast; DraftKings/FanDuel as books and as DFS platforms) are separate seeds by kind.

## 2. Independence

A source count is not an accuracy score. Before any source contributes to an ensemble, record its
upstream lineage and correlation group. A model sold through two storefronts is one forecast
(e.g. THE BLITZ via FantasyLabs); a host repeating a beat reporter is one report. Unknown
independence is treated conservatively (grouped).

## 3. Acquisition rules

Preferred order: official/authorized API → licensed feed → publisher export/RSS/transcript →
owner-authorized file import → permitted page acquisition within terms. Never evade paywalls,
CAPTCHA, rate limits, geo restrictions or bot prohibitions; robots.txt is not a license. No
billable trial or purchase without owner approval. On 2026-09-30 the DraftKings and FanDuel rules
pages returned 403 to automated fetch and the in-app browser refused the DraftKings domain; that
is recorded as a blocker, not worked around.

## 4. Competitor research protocol (DFS-§3)

Per observation: product, capability, sport/platform coverage, evidence URL/location, date,
access level, evidence class (`observed_hands_on` / `vendor_docs` / `vendor_marketing` /
`unverified_claim`), confidence, adoption decision (`reuse` / `implement` / `adapt` /
`experiment` / `defer` / `reject`). Never record a paywalled feature as hands-on. Time-boxed
batches of ~10 products; findings land in `docs/dfs/COMPETITOR_MATRIX.md` (created by the first
batch — nothing has been observed yet, so no matrix is published with empty claims).

## 5. Podcast resolution (2026-09-30)

All 29 podcast seeds resolved to real public RSS feeds (Apple directory lookup + direct feed fetch;
two re-verified independently): **23 available_public, 6 inactive**, 0 paywalled, 0 unresolved,
no two seeds sharing one feed. **4 feeds carry `podcast:transcript` tags** — both RotoGrinders
shows on every episode (C-009, C-010); Run Pure Sports (C-004) and Ship Chasing (C-017) only on
older episodes. Stokastic's umbrella feed (C-006) reposts its NFL/NBA/NHL feeds, so the four share
one independence group. "Theory of DFS" (C-026) is now titled "Unexpected Value". Several seeds are
season-long or betting shows rather than DFS. **Rights are unassessed for every show**: a public
feed is not permission to download, transcribe, retain or train on audio; the first acquisition
step is a terms review per show, starting with the transcript-publishing feeds (which need no
transcription at all).


## 6. Website resolution (2026-09-30)

All 74 website seeds were researched (public pages + search; search-snippet-only claims are
labelled in each entry's notes). `accessState` records **our current authorised path, not how open
the site is**: 28 paid sites are `permission_required` (no subscription is held), 25 free/freemium
sites are `manual_import_only` until a terms review is recorded, 14 stay `unverified` (pricing not
determined), 6 are `unresolved_identity` (LineupIQ, Bet The Line, Sharp AI Proptimizer, NFL Data
Edge, SportsPredict, Prediktor — owner clarification needed) and Statz.ai is `out_of_scope`
(soccer/cricket only). Licences are unassessed for every site.

- **Aliases:** numberFire (A-031) redirects into FanDuel Research (A-030) — one source.
- **Shared data → one independence group:** FantasyData + DraftDashboard (SportsDataIO data);
  THE BLITZ + EV Analytics (the same Derek Carty projections — also resold on RotoGrinders and the
  FantasyLabs marketplace, recorded in notes).
- **Shared ownership is recorded as `corporateParent`, NOT merged into one group:** Better
  Collective (RotoGrinders, FantasyLabs, Action Network), Marzen Media (FantasyPros, BettingPros),
  Gambling.com Group (RotoWire, OddsJam), FanDuel. Two models under one parent are still two
  models unless evidence shows shared inputs.
- **Documented public APIs** (`acquisitionMethod: api_candidate`, terms and keys still required):
  DailyAmbush, Diamond DFS, PFF, Opta, Unabated, OddsJam. **12** sites document a CSV export
  (`owner_csv_export` — the owner exports from their own account and imports the file).
