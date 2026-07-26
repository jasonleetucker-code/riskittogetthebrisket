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

> ### ⚠ Consequence for LI-7 — read this before assuming re-scoring is live
>
> **Projection re-scoring is BUILT but UNFED.** The pipeline in
> `src/league_intel/projections.py` is real, tested, and exercised
> end-to-end against a fixture — but as of this audit **there is no
> automated source supplying it**, because no provider permits automated
> access to raw statistical categories (§2). The only live input path is
> a human exporting a CSV from a subscription they already hold.
>
> The practical consequence: **league-adjusted values will initially rest
> on the market/consensus anchor plus the best-ball and replacement
> structure (LI-3 / LI-5), NOT on re-scored raw projections.** Any reader
> — human or agent — who sees `projections.py` and assumes re-scored
> stat lines are flowing into LI-7 is wrong until this section says
> otherwise.
>
> This is not a defect in LI-6. It is the honest state of what is
> obtainable without a licence, and it is exactly why the manual-import
> adapter was built first: the moment a licence or a subscriber export
> exists, the pipeline behind it is already validated.
>
> **Status: awaiting operator answer on §5.1 / §5.2.**

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

---

## 6. Manual import contract (operator-facing)

This is the unblocked ingestion path. Every source in §2 is either
subscriber-gated or licence-gated, so **a CSV you export by hand is the
input the pipeline is designed around** — not a workaround. A future
licensed feed becomes a thin adapter emitting the same objects.

Parser: `src/league_intel/projections.py::parse_manual_import`.
Worked example: `tests/league_intel/fixtures/manual_projection_import.csv`
(exercised end-to-end in `test_projections.py::TestEndToEnd`).

### 6.1 Columns

**Identity (required):**

| Column | Required | Notes |
|---|---|---|
| `player_name` | ✔ | Display name; resolved via `src/identity/unified_mapper.py` downstream |
| `position` | ✔ | `QB` / `RB` / `WR` / `TE` / `K` plus IDP positions |
| `team` | ✘ | NFL abbreviation — improves identity resolution, especially for name collisions |
| `week` | ✘ | Integer for weekly rows; **omit entirely for rest-of-season** |

**Stats:** any subset of the league's **Sleeper scoring keys**. Common
offensive ones: `pass_yd`, `pass_td`, `pass_int`, `pass_cmp`, `rush_att`,
`rush_yd`, `rush_td`, `rec`, `rec_yd`, `rec_td`, `fum_lost`.

Column headers must be the Sleeper key exactly. A header that isn't a
league scoring key is **reported as a warning, never silently dropped** —
an unrecognized column almost always means a mis-mapped export header,
and quietly ignoring it is how a scored category goes missing.

### 6.2 What you do NOT need to supply

You do not need `rec_0_4` … `rec_40p` or `bonus_fd_*`. Almost no provider
projects them, so LI-6 derives them (§3) from your projected volumes and
the player's realized play-by-play rates, tagging each with its
provenance tier. **Supply them only if your source genuinely projects
them** — a direct value always beats a derived one and will be kept.

### 6.3 Behaviour guarantees

* One malformed row never kills an import — it is skipped with a warning.
* Rows with no usable stats are skipped rather than scored as zero.
* `week` present → the row is treated as weekly; absent → rest-of-season.
* Nothing is fabricated: if you don't project `rec`, no reception bands
  or receiving first downs are invented for that player.

### 6.4 Example

```csv
player_name,position,team,rush_att,rush_yd,rush_td,rec,rec_yd,rec_td,fum_lost
Bijan Robinson,RB,ATL,272,1210,8,68,540,3,2
```

Re-scored under this league's rules, that row yields league points with
a full explainable breakdown, `bonus_fd_rb` derived from Robinson's own
carry/target first-down rates (tier B) and his reception bands
distributed from his realized catch-depth mix.

---

## 7. TE-premium paired-variant survey (calibration)

**Question.** The League Intelligence agent measured a depth-graded TE
premium (×1.287 TE1-12 → ×1.512 TE41+, median ×1.368) from KTC's
standard vs TE++ boards — 388 non-TE rows byte-identical, all 74 TE rows
differing. Best-evidenced number in the engine, but from **one
publisher**. If other publishers also ship paired variants, each is
another natural experiment, and we learn whether ×1.368 is a market
consensus or KTC's house view.

**Method.** Survey *upstream*, not the repo: for each ingested source,
does the publisher expose a variant differing **only** on TE posture,
reachable by an automatable route we're permitted to use? Probes were
one request per candidate with a 1.5-2s gap, against endpoints the repo
already consumes. An accepted-but-ignored parameter is detectable as a
**byte-identical payload** — that is the FantasyCalc failure mode below
and it is why payload size is recorded rather than HTTP status alone.

### 7.1 Results

| Source | Paired TE variant? | Mechanism / evidence |
|---|---|---|
| **KTC** (`ktcSfTep`) | ✅ **YES** | `?sf=true&tep=0..3` query param. **[verified]** This is the existing measured pair — the only positive in the survey. |
| **OTCFFB** (`otcffbSf`) | ❌ **No** | `format` accepts exactly `sf` (50,627 B) and `1qb` (49,238 B); `te`, `tep`, `sf_te`, `sf_tep`, `sfte`, `superflex_te`, `te_premium`, `sf_te_premium` all → **HTTP 400 "Invalid format"**. **[verified]** |
| **FantasyNavigator** (`fantasyNavigatorSf`) | ❌ **No** | `platform` accepts only `sf` (603,876 B); every other value incl. `1qb` → **HTTP 500**. **[verified]** |
| **Dynasty Daddy** (`dynastyDaddySf`) | ❌ **No** | `tep=1`, `isTEPremium=true`, `teMultiplier=1.5`, `tePremium=true` each returned a **byte-identical 913,997 B** payload — accepted and ignored. **[verified]** |
| **FantasyCalc** (`fantasyCalc`) | ❌ **No** (public API) | `teMultiplier=1` vs `1.5` and `tePremium=1.5` all returned **byte-identical 369,801 B**; 0 of 475 shared rows differed. Scale *is* cardinal (1,738× dynamic range), so it would have passed the cardinal gate had a real variant existed. **[verified]** |
| **FantasyPros** (`fantasyProsSf`, `fantasyProsIdp`) | ⚠️ **Unmeasurable** | Rank-encoded (~1.05× dynamic range) — fails `CARDINAL_MIN_DYNAMIC_RANGE` **by construction**, so even a real pair could not be measured from it. Their raw-category/API routes are `robots.txt`-disallowed (§2.4). |
| **DLF** (`dlfSf`, `dlfIdp`, rookie variants) | 🔒 **Blocked** | Subscriber-gated. Manual-import path only. |
| **Dynasty Nerds** (`dynastyNerdsSfTep`) | 🔒 **Blocked** | Subscriber-gated. Note the key already says `Tep` — we ingest *only* their TE-premium variant, so the standard board is the missing half. Manual-import path only. |
| **Draft Sharks** (`draftSharks`, `draftSharksIdp`) | 🔒 **Blocked** | Login-gated. Credentials exist for the ROS product, which is a different board — using them to harvest a second dynasty variant is out of scope for a calibration probe. |
| **IDP Trade Calc** (`idpTradeCalc`) | ➖ **N/A** | IDP board — no TE rows to compare. |
| **PFK** (`pfkDynasty`), **Flock** (`flockFantasySf`), **Yahoo/Boone** (`yahooBoone`), **Fitzmaurice** | ⬜ **Not yet probed** | Deferred — see §7.3. |

### 7.2 What this means

**No second publisher corroborates the premium yet.** Of the four
sources probed with an automatable, permitted route, **all four
returned a definitive negative** — and two of those negatives
(FantasyCalc, Dynasty Daddy) are the "accepted but ignored parameter"
kind that would have looked like success if only HTTP status had been
checked.

So as of this survey, **×1.368 remains a single-publisher measurement.**
That is the decision-relevant answer: it is not yet demonstrable that
the structural premium is a market consensus rather than KTC's view.
The honest posture is the one ADR-009 already takes — measure where
measurable, refuse to extrapolate, and do not assign a premium by
analogy to sources that cannot be calibrated.

Notably, the publishers most likely to ship a genuine paired variant
(DLF, Dynasty Nerds — the latter already TE-premium on our side) are
exactly the subscriber-gated ones. **A single subscription would
convert the most promising remaining candidates into manual-import
pairs**, which is the same unlock §5.1 asks about for projections.

### 7.3 Not-yet-probed, and why

PFK, Flock, Yahoo/Boone, and Fitzmaurice were deferred rather than
guessed at: PFK is Supabase-backed (its table surface needs its own
careful read), and the remaining three need their live fetch shape
confirmed before a probe is meaningful. They are recorded as unknown
rather than assumed negative — an unprobed source is not evidence of
absence, and this table should not imply otherwise.

### 7.4 Constraints honoured

* **Calibration only.** Nothing here is registered as a ranking source.
  `_RANKING_SOURCES`, `_SOURCE_CSV_PATHS`, and `data_contract.py` are
  untouched; no blend behaviour changed.
* **Gates consumed, not reinvented.** Any measured pair goes through
  `src/league_intel/calibration.py::measure_paired_te_premium`, which
  enforces both the controls-at-unity and cardinal-scale conditions.
  A source failing either reports **unmeasurable**, never a fallback
  number.
* **Polite.** One request per candidate per run, 1.5-2s spacing, against
  endpoints already in use. No account-gated or robots-disallowed
  surface was touched; blocked sources are recorded as blocked with a
  manual-import path.

---

## 8. CORRECTION to §7 — Dynasty Nerds is not blocked, and what its pair shows

**§7 classified Dynasty Nerds as "subscriber-gated / blocked". That was
wrong**, and the error was mine: I asserted the access posture from the
source's reputation instead of reading our own fetcher, whose docstring
says plainly *"No JS execution, no auth, and no paywall bypass are
needed."*

DN embeds its whole dataset inline in the page HTML:

```
window.DR_DATA = { PPR: [...], SFLEX: [...], STD: [...], SFLEXTEP: [...], _meta: {...} }
```

`scripts/fetch_dynasty_nerds.py` already downloads that payload every
refresh and extracts **only** `SFLEXTEP`. **`SFLEX` is the same board
without the TE premium** — the paired variant, from the same publisher,
in bytes we were already fetching and discarding.

`scripts/extract_te_calibration_pairs.py` now caches all four variants
to `data/calibration/te_pairs/` at **zero additional HTTP cost**: it
imports the existing fetcher's `_fetch_html` / `_extract_dr_data` /
`_build_rows` (already parameterized by key) and pulls every array out
of one response. The fetcher is imported, never modified. Nothing is
registered as a ranking source.

### 8.1 Result: the value pair is real but **confounded**

294 rows per variant, 281 joined on SleeperId. Running
`measure_paired_te_premium`:

| Gate | Result |
|---|---|
| **Cardinal scale** | ✅ **PASS** — 955× dynamic range (values 10 … 9,558). Not a rank encoding. |
| **Controls at unity** | ❌ **FAIL** — control drift 6.83%, control ratio 0.952 |
| Verdict | `usable: false`, `tePremium: None` |

This is a **third case** the gate design didn't anticipate: not
rank-compressed (FantasyPros' failure mode), but *cardinal and
confounded*. The diagnosis is not a uniform renormalization — I checked:

* Control medians cluster tightly (QB 0.954 / RB 0.932 / WR 0.952,
  only 2.25pp apart), which *looks* like a global rescale…
* …but only **27 of 240** control rows are identical (KTC: **388 of
  388**, byte-identical), and top control players move in **both
  directions** — Mahomes ×0.910, Lamar ×0.977, Gibbs ×1.024, London
  ×1.073. Applying a value floor tightens dispersion (sd 0.13 → 0.04)
  but the between-position spread does **not** converge to zero.

A renormalization moves every control player by the *same* factor.
These don't. **SFLEX and SFLEXTEP are separately-maintained boards, not
one board with a TE knob.** The gate correctly rejected the pair, and
the value-ratio method is genuinely unavailable here — the ×1.368
cannot be corroborated in value space from this source.

### 8.2 ⚠ Finding for the LI agent building `measure_rank_displacement()`

**A controls-at-zero-displacement gate can never pass on a combined
ranking list, by construction.** Rank displacement is zero-sum:

```
TE total displacement      :  -925 rank-positions   (41 TEs, mean -22.6)
control total displacement :  +934 rank-positions   (240 controls, mean +3.9)
net                        :    +9   (0.5% of ~1,850 positions moved)
```

When 41 TEs climb, the non-TEs they pass **must** fall by the same
total. The +3.9 control drift is the *mechanical consequence* of the TE
premium, not evidence of confounding. Porting the value path's
controls-at-unity condition directly into the ordinal path would reject
every honest measurement.

The ordinal gate needs to be one of:

* **within-position rank** (TE rank among TEs, which is invariant to
  cross-position reshuffling), or
* **expected-drift-adjusted**: compare observed control drift against
  the drift mechanically implied by the observed TE movement, and flag
  only the *residual*.

Flagging rather than implementing — `calibration.py` is the LI agent's
file and the ordinal path is their work in progress. Happy to supply
this dataset as a fixture.

### 8.3 What DN *does* corroborate: the **shape**

Depth-graded TE rank displacement (negative = gains rank under TEP),
in the same bands as the KTC measurement:

| Band | n | DN median rank gain | KTC value premium |
|---|---|---|---|
| TE1-12 | 12 | −15.0 | ×1.287 |
| TE13-24 | 12 | −16.5 | (KTC mid bands) |
| TE25-40 | 16 | −28.0 | |
| TE41+ | 1 | −30.0 | ×1.512 |

Levels are **not** comparable — one is rank displacement, the other a
value ratio — but the **shape is**: both publishers say the TE premium
**grows with depth**, monotonically. Elite TEs are already priced near
their premium value; the premium bites hardest on mid/back-end TEs.

That is genuine independent corroboration of the *structure* of the
KTC curve, from a second publisher, even though it cannot corroborate
the *level*. Materially better than "single-publisher number we can't
corroborate" — and materially short of "two publishers agree on
×1.368".

**Power caveat:** DN's TE sample is 41 rows (vs KTC's 74), and the
TE41+ band has **n=1** — that band's −30 is a single player, not an
estimate. The DN gradient should be read as three usable bands.

### 8.4 PPR / STD: no TE contrast (checked, not assumed)

| Contrast | Control drift | Reading |
|---|---|---|
| `PPR` → `STD` | 13.2% (QB 1.048 / RB 0.868 / WR 1.049, **TE 1.048**) | Varies reception scoring. TE moves *identically to QB/WR* — no TE-specific signal. |
| `SFLEX` → `PPR` | 64.0% (QB **0.360**, RB 1.076, WR 1.183, TE 1.414) | Varies superflex. QB collapses as expected; nowhere near TE-isolating. |

Neither contrast isolates TE posture. Confirmed rather than assumed, as
instructed. They remain cached in case a future question wants the
scoring-format axis.

### 8.5 Re-examining the other "blocked" calls

Applying the tell — *a fetcher whose docstring says no auth is needed*:

| Source | §7 said | Actually | Note |
|---|---|---|---|
| **Dynasty Nerds** | blocked | ✅ **public, pair measured** | corrected above |
| **DLF** | blocked | ⚠️ **auth-gated, but we hold credentials** | `fetch_dlf.py` authenticates with `DLF_USERNAME`/`DLF_PASSWORD`. "Blocked" was right about the gate, wrong about the consequence — **we are already through it.** If DLF publishes a TE-premium variant, it is reachable on the session we already establish. Worth a probe. |
| **Draft Sharks** | blocked | 🔴 **strong candidate — likely mis-classified** | `fetch_draftsharks.py` already scrapes **`/dynasty-rankings/te-premium-superflex`** — a TE-premium *URL path*. A sibling non-TEP superflex path would be the same pattern as KTC's `tep=` param. We already have a working authenticated Playwright fetch against this exact board. |
| Flock, Yahoo/Boone, IDP Show, PFK | not probed | **all publicly fetched today** | Their fetchers describe public JSON / public Datawrapper CSV / public Supabase. Whether any ships a *TE variant* is still unprobed — but none is access-blocked. |

**Two of my three "blocked" calls were wrong in substance.** The
pattern in both: I reasoned from what the publisher sells rather than
from what our code already reaches. The corrected posture is that
access-blocked is rarer than assumed, and the repo's own fetchers are
the authority on it.

### 8.6 Recommended next probes, in order

1. **Draft Sharks** — highest expected value. Same board we already
   fetch, TE-premium already in the URL path; needs the sibling path
   confirmed. Uses an authenticated session we already maintain, so
   this needs a coordinator call on scope before I run it.
2. **DLF** — credentials already held; check for a TE-premium variant.
3. **Flock / PFK / Yahoo-Boone / IDP Show** — public, cheap to probe.
