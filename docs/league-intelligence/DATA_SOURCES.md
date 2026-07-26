# Projection Source Audit (LI-6 · spec §7)

Status: audit complete, ingestion decisions pending coordinator sign-off
Owner: LI-6 (projections) · Territory: `src/league_intel/projections.py` +
this file. `src/league_intel/{config,scorer,values,replacement}.py` belong
to the League Intelligence workstream — LI-6 consumes `scorer.py`, never
edits it.

> **Evidence policy for this document.** Every claim below is tagged with
> how it was established: **[verified]** = observed directly from the
> source during this audit (HTTP probe, robots.txt, in-repo code read);
> **[documented]** = stated by the provider's own public pages;
> **[unverified]** = industry knowledge that a human must confirm before
> money or a contract depends on it. Pricing and redistribution terms are
> deliberately **not** asserted from memory — they change, and getting
> them wrong is how you end up in breach. Where a term matters, the row
> says "confirm with provider" rather than guessing.

---

## 1. What the repo already has (audit before building)

The coordinator's instruction was to audit `src/ros/sources/` before
adding ingestion. The finding materially reshapes LI-6.

### 1.1 Existing ROS ingestion — reusable machinery, wrong data shape

`src/ros/sources/__init__.py` is a well-built source registry (weights,
freshness thresholds, staleness, per-source enable/disable, user-override
plumbing, and a frontend parity test). Five adapters are registered:

| key | type | ROS? | IDP? | `is_projection_source` | weight |
|---|---|---|---|---|---|
| `draftSharksRosSf` | ros | ✔ | ✘ | **✔** | 1.25 |
| `fantasyProsRosOverall` | ros | ✔ | ✘ | ✘ | 1.15 |
| `fantasyProsRosIdp` | dynasty_proxy | ✘ | ✔ | ✘ | 1.05 |
| `fantasyProsRosSf` | dynasty_proxy | ✘ | ✘ | ✘ | 0.85 |
| `ffc2qbAdp` | adp | ✘ | ✘ | ✘ | 0.70 |

**The critical finding [verified]:** the ROS layer's row contract is
`canonicalName, sourceName, position, team, rank, total_ranked, projection`
— a **single scalar** `projection` (DraftSharks' "3D Value +"), not a
statistical line. Only one of five sources sets `is_projection_source`,
and even that one emits points-in-their-scoring, not raw categories.

This matters because the LI-2 scorer is a pure dot product over **Sleeper
stat keys**:

```
points = Σ  stat_line[k] × scoring_settings[k]
       k ∈ stat_line ∩ scoring_settings
```

You cannot re-score a scalar. Re-scoring requires `pass_yd`, `rush_yd`,
`rec`, `rec_fd`, … per player. **No source in the repo supplies that
today.** LI-6's ingestion question is therefore not "which adapter do I
extend" but "which provider will license us raw categories at all" —
which is exactly what §7 asks.

### 1.2 What to reuse verbatim (do NOT rebuild)

| Need | Existing implementation | Verdict |
|---|---|---|
| Source registry, weights, enable/disable, user overrides | `src/ros/sources/__init__.py` | **Reuse pattern**; LI-6 adds a projection-source registry in the same shape rather than a novel one |
| Freshness / completeness / availability confidence multipliers | `src/ros/parse.py` (`freshness_multiplier`, `completeness_multiplier`, `availability_multiplier`, `effective_source_weight`) | **Reuse directly** — this is exactly the confidence machinery LI-6 needs, already tested |
| Multi-source blending | `src/ros/aggregate.py` | **Reuse** for projection blending |
| Player identity resolution | `src/identity/unified_mapper.py` (sleeper↔gsis↔espn ladder, confidence-scored) | **Reuse directly** — solves the player-id-quality column for every source |
| Historical actuals for priors | `src/nfl_data/ingest.py` + `nflverse_direct.py` (weekly, defensive, snaps, **PBP**) | **Reuse** |
| **First downs from play-by-play** | `src/nfl_data/opportunity_stats.py` — already parses `first_down` out of nflverse PBP | **Reuse — this is the derived-category substrate, already built** |
| Exact scoring | `src/league_intel/scorer.py` (LI-2, golden-validated) | **Import, never touch** |

That last PBP finding is the happy one: the league scores first downs and
reception-distance bands, almost nobody projects them, and the repo
*already* extracts first-down events per player from nflverse PBP. The
derived-category work (§3 below) is priors on top of data we already
ingest, not a new pipeline.

### 1.3 What genuinely needs building

1. `src/league_intel/projections.py` — projection normalization to Sleeper
   stat keys, re-scoring through LI-2, derived-category estimation with
   provenance tiers, and the source-disagreement metric.
2. A **raw-category projection source** that we are permitted to ingest.
   Section 2 is the search for one; section 4 is the honest answer.
3. Provenance-tier tracking — nothing in the repo records *how* a number
   was arrived at today.

---

## 2. Source matrix (spec §7)

Legend — Access: **open** = publicly reachable and not disallowed ·
**paywall** = subscriber content · **licensed API** = commercial
agreement required · **blocked** = automated access not permitted.

### 2.1 Footballguys

| Field | Finding |
|---|---|
| Raw stats vs rankings | Both — projections are published as full statistical lines (the format LI-6 wants) **[documented]** |
| Offense / IDP / K | Offense ✔, IDP ✔, K ✔ — one of the few with genuine IDP projection depth **[documented]** |
| First downs / distance bands | ✘ — not projected **[unverified, no contrary evidence found]** |
| Weekly / ROS | Both **[documented]** |
| Cadence | Weekly in-season, more often around news **[documented]** |
| Historical snapshots | Not offered as a product; we would have to snapshot ourselves |
| API / export | Subscriber CSV/XLS export exists; no documented public API **[documented]** |
| **Automated access permitted?** | **No `robots.txt` at all (404) [verified]** — absence is not permission. Content is subscriber-gated; their ToS governs. **Treat as blocked for scraping.** |
| Redistribution | Confirm with provider — assume no redistribution |
| Cost | Subscription; confirm current tier pricing with provider |
| Player-id quality | Names + team/pos; no public cross-id. Resolvable via `unified_mapper` at ~name+team+pos confidence |
| **Verdict** | **Blocked adapter · manual-import path.** Best raw-category + IDP fit of any candidate. A subscriber may export CSV by hand; LI-6 will accept that file. No scraping. |

### 2.2 RotoWire

| Field | Finding |
|---|---|
| Raw stats vs rankings | Both — statistical projections are a core product **[documented]** |
| Offense / IDP / K | Offense ✔, K ✔, IDP ✔ (thinner than FBG) **[documented]** |
| First downs / distance bands | ✘ |
| Weekly / ROS | Both **[documented]** |
| Cadence | Continuous — among the fastest news-to-projection turnarounds |
| Historical snapshots | Not offered publicly |
| API / export | **Commercial data-feed licensing is an advertised business line** — this is the cleanest *legitimate* route to raw categories **[documented]** |
| **Automated access permitted?** | `robots.txt` blocks a named-crawler list, not `/*` **[verified]**; publishes an `llms.txt` policy inviting factual, attributed use and forbidding fabrication **[verified]**. Scraping projections is still outside that policy's intent — **the licensed feed is the correct door.** |
| Redistribution | Governed by the feed contract — confirm |
| Cost | Commercial; confirm with provider |
| Player-id quality | Feed carries stable ids (a licensing advantage over scraped names) **[unverified — confirm in contract]** |
| **Verdict** | **Licensed-API candidate · recommended commercial route.** Blocked adapter until a contract exists; the adapter shape is worth writing against the documented feed schema so it's ready. |

### 2.3 FTN Fantasy

| Field | Finding |
|---|---|
| Raw stats vs rankings | Both; analytics-forward (DVOA lineage) **[documented]** |
| Offense / IDP / K | Offense ✔; IDP limited **[unverified]** |
| First downs / distance bands | ✘ projected, but their charting data is closer to this than most **[unverified]** |
| Weekly / ROS | Both **[documented]** |
| API / export | Subscriber tools; data licensing exists for partners **[unverified]** |
| **Automated access permitted?** | Subscriber-gated — **blocked for scraping** |
| **Verdict** | **Blocked · low priority.** Overlaps RotoWire/FBG without a decisive advantage for our scoring quirks. Revisit only if their charting exposes first-down/air-yard detail under licence. |

### 2.4 FantasyPros

| Field | Finding |
|---|---|
| Raw stats vs rankings | **Both** — ECR rankings (already ingested) *and* consensus statistical projections **[documented]** |
| Offense / IDP / K | Offense ✔, K ✔, IDP ✔ |
| First downs / distance bands | ✘ |
| Weekly / ROS | Both |
| Cadence | Weekly ECR refresh; projections track it |
| Historical snapshots | Not public |
| API / export | Documented partner API + subscriber CSV export |
| **Automated access permitted?** | **Partially, and precisely: `robots.txt` sets `Crawl-delay: 5` and disallows `/ajax/`, `/nfl/ranker/`, `/api/`, `/json/`, `/xml/` [verified].** The public *ranking pages* (`/nfl/rankings/*.php`) are **not** disallowed — which is what our three existing adapters already read, so **the repo is currently compliant**. The machine-readable endpoints that would carry raw categories are exactly the disallowed ones. |
| Redistribution | Attribution expected; confirm for any republished number |
| Cost | Free tier for ranking pages (in use); API/premium requires agreement |
| Player-id quality | Their own ids in the API; names on public pages |
| **Verdict** | **Split.** Rankings: **already ingested, keep as-is, stays a ranking signal.** Raw categories: **licensed API only — do not scrape `/api/` or `/json/`.** Record as a blocked adapter with a partner-API path. |

### 2.5 Sharp Football Analysis

| Field | Finding |
|---|---|
| Raw stats vs rankings | Primarily analysis + situational splits rather than a full projection set **[documented]** |
| Offense / IDP / K | Offense-leaning |
| First downs / distance bands | Their situational/tendency work is genuinely relevant to **archetype priors** even though they don't project the categories |
| **Automated access permitted?** | Subscriber content — **blocked for scraping** |
| **Verdict** | **Not a projection source.** Possible future input to archetype priors (§3 tier C) via manual reading. Not an adapter. |

### 2.6 ESPN

| Field | Finding |
|---|---|
| Raw stats vs rankings | Both; projections drive their own fantasy product **[documented]** |
| Offense / IDP / K | Offense ✔, K ✔; IDP ✔ for their formats |
| First downs / distance bands | ✘ |
| Weekly / ROS | Both |
| API / export | Undocumented internal fantasy endpoints exist and are widely used by hobby projects — **that is not the same as permitted**. No public terms grant automated access. |
| **Automated access permitted?** | **No documented grant. Treat as blocked.** The repo already uses ESPN's *public news* endpoint for per-player news (`src/news/providers/espn_player.py`), which is a different, publicly-served surface — that precedent does **not** extend to the fantasy projection endpoints. |
| Player-id quality | **Excellent** — `espn_id` is already in our identity ladder (`unified_mapper`), so if access were ever licensed, joins are solved |
| **Verdict** | **Blocked.** Do not build against undocumented internal endpoints. Note the id-quality upside for any future licensed route. |

### 2.7 Establish The Run

| Field | Finding |
|---|---|
| Raw stats vs rankings | Projections are the core paid product **[documented]** |
| Offense / IDP / K | Offense ✔, K ✔; IDP thin |
| Weekly / ROS | Both |
| API / export | Subscriber export; no public API |
| **Automated access permitted?** | `robots.txt` disallows only `/feed/` **[verified]**, but the projections themselves are **subscriber-gated** — the permissive robots line does not unlock paid content. **Blocked for scraping.** |
| **Verdict** | **Blocked adapter · manual-import path** for a subscriber. |

### 2.8 Additional candidates considered (per "any reputable candidate")

| Source | Why considered | Verdict |
|---|---|---|
| **nflverse / nfl_data_py** | **Already ingested [verified].** Not a projection source — it is *historical actuals*, including **play-by-play with `first_down`**. | **The single most valuable data asset we already own for LI-6.** It cannot project, but it is the ground truth every derived category and every backtest needs. |
| **Sleeper** | Already integrated; supplies the scoring settings + host-awarded points the scorer is validated against | Keep as validation ground truth, not a projection source |
| **4for4** | Full statistical projections, respected accuracy record | Subscriber-gated → blocked; manual-import candidate if a subscription exists |
| **FantasyLife / Dwain McFarland** | Strong IDP + opportunity modelling | Subscriber-gated → blocked |
| **NFELO / open models** | Open methodology, some open data | Worth a follow-up probe — the only category where an *open-licensed* raw-category projection might exist |

---

## 3. Derived categories — provenance tiers

The league scores **first downs** and **reception-distance bands**; no
audited source projects them. LI-6 estimates them, and every estimate
carries its tier so LI-7 can weight confidence honestly.

| Tier | Name | Method | Confidence |
|---|---|---|---|
| A | `direct` | Source projected the category outright | highest |
| B | `derived-player-history` | Player's own realized rate from nflverse PBP (e.g. first-downs-per-reception over trailing N games) applied to a projected volume | high |
| C | `derived-archetype` | Rate borrowed from the player's role/archetype cohort (slot WR, early-down RB, …) when personal history is thin | medium |
| D | `derived-position` | Position-level league-average rate — the floor for rookies and role-changers | low |
| E | `manual` | Operator-entered override | pinned, audited |

Rules:

1. **A derived value never outranks a direct one.** Confidence is
   monotonically decreasing A → D.
2. **Tier is recorded per category, per player, per source** — not per
   projection. A row can be `direct` for `rec` and `derived-position`
   for `rec_fd`.
3. **Volume comes from the source; rate comes from history.** We never
   invent a volume. If a source doesn't project receptions, we do not
   synthesize reception first downs from nothing.
4. Tier B/C/D rates derive from `src/nfl_data/opportunity_stats.py` PBP
   extraction — already built, already tested.

---

## 4. Conclusions and recommended posture

1. **No permitted raw-category projection source exists today.** Every
   candidate with real statistical projections is either subscriber-gated
   (FBG, ETR, FTN, 4for4), licence-gated (RotoWire, FantasyPros API), or
   undocumented-and-therefore-off-limits (ESPN internal). This is the
   honest answer to §7 and it should shape LI-7's expectations: **the
   re-scoring path is real but its input is currently manual or
   commercial.**

2. **Recommended route, in order:**
   - **RotoWire commercial feed** — the only candidate whose licensing is
     an advertised business line, with stable ids. Cleanest legitimate path.
   - **FantasyPros partner API** — we already consume their free ranking
     pages compliantly; extending to the licensed API is a natural upgrade.
   - **Manual subscriber import (Footballguys)** — best IDP + raw-category
     coverage; zero engineering risk; needs a human export.

3. **What LI-6 builds now, independent of that decision:**
   - The normalization + re-scoring pipeline itself, driven by a
     **manual-import adapter** (CSV → Sleeper stat keys → LI-2 scorer).
     This makes every blocked source usable the moment a human drops a
     file in, and makes every licensed source a thin adapter later.
   - Derived categories on nflverse PBP with provenance tiers.
   - Source disagreement, computed over whatever sources are present.
   - Rankings-only sources (our three FantasyPros feeds, DraftSharks) stay
     **ranking signals and disagreement inputs — never fabricated stat
     lines.**

4. **Nothing in this audit authorizes new scraping.** Every blocked source
   above is recorded as blocked with a manual-import path, per the
   instruction not to work around access controls.

---

## 5. Open questions for the operator

1. Do we hold any current subscription among Footballguys / ETR / 4for4 /
   FTN? A single existing subscription unblocks the manual-import path
   immediately.
2. Is there appetite for a commercial data licence (RotoWire or
   FantasyPros)? That decision gates whether the automated adapter is
   worth writing.
3. Confirm redistribution posture: league-adjusted values derived from a
   licensed feed are a *derived work* — most feed contracts permit
   internal use but restrict republication. Our values are shown only to
   league members, which is likely fine, but it must be confirmed rather
   than assumed.
