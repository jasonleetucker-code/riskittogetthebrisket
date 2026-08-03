# Curated Industry Sharp Model: audit and implementation

## Scope

This change extends the existing platform-neutral Sharp Model. It does not create a second tracker or replace Sharp Score v2. The workbook is treated as a researched person universe, while Sleeper and FFPC remain observable platform-account and activity sources.

The imported workbook contains eight sheets and is parsed dynamically:

| Sheet | Data rows used |
|---|---:|
| Final 100 | 100 |
| Candidate Pool | 247 |
| Sharp Tracker | 40 |
| FFPC & High Stakes | 16 |
| Near Misses | 30 |
| Sources | 35 |
| Methodology & QC | inspected |
| Category Summary | inspected |

The final 100 become `curated_industry_sharp`. Near misses are retained as research/watchlist people, with inactive or insufficient-identity states where appropriate. Screened-out candidates remain stored for reconciliation but do not influence the model.

## Existing Sharp architecture

Before this extension, the operational path was:

1. Sleeper's public graph discovers users and leagues.
2. `src/sharp/records.py` collects completed season records.
3. `src/sharp/platform_records.py` converts platform evidence into `ManagerRecord`.
4. `src/sharp/score.py` applies Sharp Score v2.
5. `src/sharp/market.py` selects qualified managers and aggregates normalized `asset_movements` from the platform ledger.
6. FFPC public pages contribute automated evidence where complete, configured curated high-stakes identities where explicitly verified, and separately labeled provisional public activity.

### Existing empirical qualification

Sharp Score v2 remains unchanged:

- at least two completed seasons;
- at least two qualifying dynasty leagues, each at least two seasons old;
- at least 24 completed games;
- at least 52% observed win rate;
- acceptable abandoned-roster rate;
- recent activity;
- top quartile of the evaluable population by score;
- at least 0.55 evidence confidence.

Its positive components are performance (36%), roster quality (22%), multi-league consistency (22%), longevity (12%), and sustained activity (8%). Championships are beta-binomial shrunk and provide a bounded preference bonus rather than a hard gate. Keeper and first-year dynasty leagues do not certify dynasty skill.

## Audit findings

### 1. Curation was platform-specific rather than person-first

The existing `curated` pathway was a small FFPC configuration list keyed directly to an FFPC manager key. It could not represent an untrackable analyst, multiple accounts belonging to one person, a changed handle, or a person who was both curated and empirically qualified.

### 2. Identity was not an explicit reviewable product

`manager_identity_links` already supported canonical identities, but there was no person catalog, alias/evidence store, candidate queue, or approve/reject workflow. A username resemblance therefore had nowhere safe to live except as an untracked note.

### 3. Raw activity could overweight visible portfolios

Movement IDs were already canonical and deduplicated, and each rolling window was independently queried. The suspected 30-day/90-day additive double count was not present in the unified implementation. However, raw buys and drops still represented observations. A person visible in ten leagues could create ten movements and influence the signal more than a person visible in one league.

The new consensus layer keeps raw activity for auditing but creates one net directional vote per canonical person, with a square-root discount for people sharing the same affiliation/network. Multiple accounts and multiple leagues remain evidence, not independent experts.

### 4. Missing data needed a first-class representation

The empirical model correctly leaves insufficient history unevaluable, but there was no independent curated expertise dimension. The extension preserves NULL winning percentages, championships, and empirical scores when unknown. It never writes a neutral 50% win rate.

### 5. Redraft and dynasty evidence needed visible separation

Sharp Score v2 already uses dynasty-only qualification. The person/evidence model stores broader high-stakes accomplishments without relabeling them as dynasty performance. `sharp_performance_metrics.league_type` preserves the observed format, and only qualifying dynasty records drive the existing empirical flag.

## New person architecture

The additive schema lives in the same SQLite ledger:

- `sharp_people`
- `sharp_aliases`
- `sharp_platform_accounts`
- `sharp_identity_candidates`
- `sharp_identity_evidence`
- `sharp_model_membership`
- `sharp_performance_metrics`
- `sharp_review_decisions`
- `sharp_import_runs`
- `sharp_activity_events` view over canonical platform movements

The existing `manager_identity_links` table remains the authority connecting a platform manager key to a canonical person ID.

### Membership states

- `curated_only`
- `trackable_curated_sharp`
- `performance_qualified_only`
- `both_curated_and_performance`
- research/watchlist/screening states

`verified_super_sharp` means a curated person has a verified, usable fantasy-platform identity. It is a trackability label, not an objective claim of superiority.

## Scores and missing data

Three dimensions stay independently visible:

- **Curated expertise**: workbook confidence, Final-100 selection, specialist/Tracker/high-stakes evidence, source quality, and current activity.
- **Empirical performance**: unchanged Sharp Score v2 when linked public dynasty evidence exists.
- **Trackability**: verified account, observable decisions, public league/portfolio coverage, and refreshability.

Combined influence is an application weight, not a substitute for those dimensions:

- with empirical evidence: 60% curated + 30% empirical + 10% trackability;
- without empirical evidence: 85% curated + 15% trackability.

Only verified fantasy accounts contribute behavioral market signals. Untrackable curated people remain visible in the model and people APIs but cannot manufacture transactions.

## Identity-resolution rules

**The import verifies no fantasy identity. None. The Super Sharp population
therefore starts at zero and grows only through explicit review.**

This is a correction, not a limitation. The workbook's `Verified Sleeper
username` column reads literally **"Not publicly verified" for 92 of the 100
people**. The eight rows that do carry a username attach *podcast and company
URLs* as their evidence — those establish why the **person** belongs in the
universe and say nothing about who holds the handle. Four of the eight
(`carpentiernfl`, `mattykiwoom`, `raygque`, `charleschillffb`) are exact
lowercase transforms of the person's own X handle, which is the
handle-equals-username inference this model explicitly forbids.

An earlier revision of this document described those eight as "ownership
evidence", and the importer stamped all 96 platform accounts
`verification_status: "verified", confidence: 1.0`. That was a
mis-transcription of the source, and it is fixed:

- Each of the eight enters as a **candidate** with
  `candidate_generation_method: "workbook_claimed_username"`, or
  `"workbook_claimed_username_matching_public_handle"` for the four that merely
  echo the X handle — ranked below the other four (0.25 vs 0.35) because a
  handle transform is weaker evidence than an independently sourced name.
- Exact public handles are generated only as candidates.
- X handles remain `verified` **accounts**: a public handle is a public
  identifier, and no fantasy behaviour hangs off it.
- Account existence or a similar display name may raise a candidate to probable, never verified.
- **The queried username can never corroborate itself.** We search Sleeper *by*
  username, so the API echoes it back in the `username` field. Including it on
  both sides of the name-overlap test made that test a tautology — on the first
  live sweep it promoted **all 42** existing accounts to
  `high_confidence_probable`, among them `hrr5010` for Hasan Rahim and
  `amicsta` for Anthony Amico, where nothing corresponds at all. Corroboration
  now means the **person's name** matches what the account actually shows.

### First live sweep (92 Sleeper candidates)

| | |
|---|---|
| checked | 92 |
| exists on Sleeper | 42 |
| not found | 50 |
| cross-person conflicts | 0 |
| raised to `high_confidence_probable` | **6** |
| **verified** | **0** |

The six that corroborate: `GrahamBarfield`, `jjzachariason`, `justinboone`,
`JustinHerzig`, `mattykiwoom` (via the pseudonym split on "Matty Kiwoom") and
`MattWaldman`. All 36 other existing accounts stay `possible` — someone holds
the handle, and that is all we know.

Of the eight usernames the workbook claimed, all eight exist, **two** corroborate
by name, and **none** is verified. `carpentiernfl` does not match "Cody
Carpentier" and correctly stays `possible` — it is the X handle, which is how it
was generated in the first place.
- FFPC display/team/entry names are matched against already ingested public FFPC managers and remain probable until explicitly reviewed.
- One verified platform account cannot be linked to two people.
- Co-managed entries are represented as separate people/accounts/evidence and are never collapsed into a team name.
- A renamed or deleted verified account is marked stale rather than reassigned.

## Event and rolling-window integrity

The system continues using one normalized event table with unique platform-scoped movement and transaction fingerprints. A movement 20 days old is selected independently by both 30-day and 90-day queries but is never summed into a lifetime total. Person consensus is derived from those canonical rows per requested window.

## Operational flow

1. Parse the workbook (`config/sharp/workbooks/*.xlsx`, tracked so the import is
   reproducible) or read the committed normalized snapshot. The snapshot stamps
   `workbook_sha256` and a `sheet_inventory`, so a hand-edited snapshot is
   distinguishable from a parsed one.
2. Upsert all people, aliases, evidence, accounts, candidates, and memberships.
3. Re-resolve any already-verified Sleeper accounts (starts empty by design —
   `resolve_verified_sleeper_accounts` walks accounts the **review queue**
   verified, and the workbook can no longer put one there).
4. Inspect a bounded number of candidates against the public Sleeper endpoint.
5. Match FFPC public identifiers against ingested FFPC managers.
6. Refresh empirical links and membership states.
7. Export reconciliation CSV/JSON artifacts.
8. Run daily under an isolated systemd timer.

All network work is GET-only, public, bounded, cached by the underlying platform collectors where available, and does not use private credentials.
