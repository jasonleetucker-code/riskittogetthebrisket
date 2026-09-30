# DFS — sources, independence and acquisition policy

## 1. Registry

`config/dfs/source_seeds.json` preserves every owner-supplied seed verbatim: 74 websites
(Appendix A), 6 sportsbooks (B), 29 podcasts (C) — 109 entries with stable `seedId`s
(`A-001`…, `B-001`…, `C-001`…). All are `accessState: "unverified"` and
`sourceCategory: "unknown"`: **a seed is a name to investigate, not an integration.**
`tests/dfs/test_source_seeds.py` pins the counts and refuses any non-`unverified` state or live
connector without recorded evidence.

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
