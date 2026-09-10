# Serving dependency manifests and safe reuse

`src/serving/input_manifest.py` computes content identities. Missing files are
explicit inputs; later creation, deletion and same-size rewrites invalidate
them even when a writer preserves mtime. `src/serving/coordinator.py` uses the
`DependencyRegistry` fingerprint to compare a candidate's complete inputs with
the manifest of the currently accepted artifact. No separate mutable success
cache can get ahead of validation and atomic publication.

## Canonical input inventory: partial; skipping disabled

The standalone source CLI records these groups before calling the existing
canonical builder. Each artifact's `inputGenerations` contains their identities,
`dependencyFingerprint` and `inputManifestComplete=false`. The private source
receipt/status also includes readable unknown-dependency reasons.

| Group | Actual live dependency and captured files |
| --- | --- |
| Raw content | `build_api_data_contract(raw)`; all raw fields except the root observation-only `scrapeTimestamp` |
| Source CSVs | Actual `_SOURCE_CSV_PATHS` registry is read using AST, including GitHub-owned feeds; all current `CSVs/` files additionally cover mirrors, fallback metadata and draft inputs |
| Configuration/models | All `config/`, including source floors, top-50 floors, confidence, bridges, model registry/champion, future-pick discounts, TE premium, identity overrides and league registry |
| Algorithm identity | All `src/**/*.py`, covering canonical valuation, identity/pick mapping, source joining, lineup, builder, schema and prepared projection owners |
| Source observations | `data/scrape_state/`; the contract's freshness builder reads source last-success records |
| Factual league state | `data/leagues/scoring_*.json`, configured `LEAGUE_SCORING_SNAPSHOT_DIR` and `LEAGUE_REGISTRY_PATH` overrides |
| Current history | `data/rank_history.jsonl`, `source_value_history.jsonl`, `temporal_ledger.sqlite` and its WAL/SHM companions |
| Runtime configuration | Relevant `RISKIT_FEATURE_*` and league-selection/path environment variables, represented only by hashes |

No `data/` archive, export archive or unrelated cache tree is traversed. This is
a conservative provenance inventory, not a proof that the whole canonical
builder is a pure function of these files. Four unresolved inputs prevent reuse:

- `data_contract._resolve_league_context` fetches live Sleeper roster count and
  TE premium, with an independent hour-long process cache. Disk snapshots alone
  do not identify the factual context that this function actually used.
- Source freshness, fallback draft year and rank-history windows depend on the
  clock. Those output/valuation boundaries have not been separated from value
  computation.
- The temporal SQLite database/WAL is mutable and is not captured as a shared
  database transaction; accepted-history recording changes inputs after build.
- Some config owners retain process caches. Hashing files does not prove which
  cached settings an already-running process consumed.

Consequently unchanged source observations still rebuild canonical data. The
CLI always follows build → validate/publish → accepted-history record. It does
not claim the canonical no-op migration is finished. The observed local Windows
inventory covered 25 registered source entries, 418 Python files and 45 config
files in about 2.1 seconds on a cold read; production timing is unmeasured.

## Prepared league views: scoped complete inputs

After collecting the factual scoring card and overlay, the league producer
calls `league_input_manifest(board, cfg, overlay, factual_scoring_fingerprint=...,`
`registry_defaults=league_registry.get_league_roster_settings(cfg.key))`.
The argument named `registry_defaults` captures the requested league's actual
effective settings, including the starter-slot fallback and flex eligibility.
The lineup container must carry that same `meta.leagueKey`.

The manifest identifies the logical accepted board, full league config, factual
scoring fingerprint, effective registry settings and complete overlay payload.
Only root `overlayFetchedAt` is observation metadata; roster membership,
transactions, scoring/league configuration, trade-window boundaries and nested
timestamps remain computation inputs. Whole-file hashes cover all projection,
overlay, registry, schema, lineup, data-contract stamp, serialization-helper and
artifact/coordinator owners plus dependency declarations. A missing owner,
missing factual scoring identity or unavailable settings disables skipping.
Source/cfg/overlay mutation detected before publication rejects the candidate.

`prepare_or_reobserve` holds a per-league process lease. Complete matching inputs
first validate the accepted bundle, then re-observe the same immutable bytes
using the new actual source timestamp. `sourceAsOf` and `observedAt` change in
the pointer; logical/physical content identity remains stable. No projection,
lineup computation or history recording runs on this path. Readers apply the
pointer's observation metadata when serving these immutable views.

Changed, unknown or invalid inputs take the existing builder and validating
publisher path. The publisher callback must forward the supplied manifest
identities to the artifact store. Its failure cannot record a successful
fingerprint in any independent cache. This coordinator does not collect providers,
start schedules or change canonical values; the existing league producer owns
those collection calls and the integration point.
