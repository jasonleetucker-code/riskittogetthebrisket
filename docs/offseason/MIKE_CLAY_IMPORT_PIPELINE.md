# Mike Clay Offseason Import Pipeline

## Purpose
This pipeline ingests the yearly Mike Clay Projection Guide PDF into structured, canonical-ready artifacts for offseason formula integration.

It is intentionally isolated from live scraper code paths:
- Parser + normalization + matching lives in `src/offseason/mike_clay/`.
- CLI entrypoint is `scripts/import_mike_clay.py`.
- Output artifacts are written under `data/imports/mike_clay/`.

## Run An Import

```bash
python scripts/import_mike_clay.py --pdf data/imports/mike_clay/NFLDK2026_CS_ClayProjections2026.pdf
```

Optional flags:
- `--guide-year 2026` (or override for next-year dry runs)
- `--manual-overrides data/imports/mike_clay/manual_match_overrides.csv`
- `--dynasty-data data/dynasty_data_YYYY-MM-DD.json`
- `--no-csv` (JSON-only artifacts)

## Artifact Layout

Each run writes to:
`data/imports/mike_clay/<guide_year>/mike_clay_<guide_year>_<timestamp>/`

### Raw extraction
- `raw/pages.json`
- `raw/positional_rows.json|csv`
- `raw/team_rows.json|csv`
- `raw/sos_rows.json|csv`
- `raw/unit_grade_rows.json|csv`
- `raw/unit_rank_rows.json|csv`
- `raw/coaching_rows.json|csv`
- `raw/starter_rows.json|csv`

### Normalized outputs
- `normalized/mike_clay_players_normalized.json|csv`
- `normalized/mike_clay_teams_normalized.json|csv`

### Reports and QA
- `reports/import_summary.json`
- `reports/unmatched_players.json|csv`
- `reports/ambiguous_players.json|csv`
- `reports/low_confidence_matches.json|csv`
- `reports/identity_resolution_hardening_summary.json`
- `reports/identity_resolution_hardening_safely_resolved.csv`
- `reports/identity_resolution_hardening_still_unresolved_likely_resolvable.csv`
- `reports/identity_resolution_hardening_intentionally_left_high_risk.csv`
- `reports/duplicate_name_report.json`
- `reports/duplicate_source_rows.json`
- `reports/duplicate_canonical_matches.json`
- `reports/conflicting_positions.json`
- `reports/conflicting_source_identities.json`
- `reports/parse_anomaly_report.json|csv`
- `reports/counts_by_position_team_status.json`

### Review workflow
- `review/manual_match_review.csv`:
  - unresolved/ambiguous/fuzzy/manual-override rows for human review.
  - impact-ranked (`impact_tier`, `impact_score`) so high business impact rows are first.
  - includes explicit `review_reason` and `recommended_action` for non-technical review.
  - can be copied into `data/imports/mike_clay/manual_match_overrides.csv` and rerun.

### Identity hardening buckets
- `safely_resolved_this_pass`: deterministic manual overrides that were applied this run.
- `still_unresolved_likely_resolvable_with_more_canonical_inputs`: unresolved rows with meaningful business impact and no safe deterministic match.
- `intentionally_left_unresolved_high_risk`: unresolved rows where ambiguity/tie risk is too high to auto-resolve.

### Metadata and logs
- `import_metadata.json`
- `logs/import_log.json`

### Latest pointers
- `data/imports/mike_clay/mike_clay_import_latest.json`
- `data/validation/mike_clay_import_status_latest.json`

## Match Status Contract

Player identity resolution emits explicit states only:
- `exact_match`
- `deterministic_match`
- `fuzzy_match_reviewed`
- `unresolved`
- `ambiguous_duplicate`

No silent drops are allowed. Every row is retained with status + confidence.
Cross-family position fallback is blocked when source position is known (trust-first guardrail),
except `DL <-> LB` compatibility for EDGE taxonomy differences.

## Canonical Matching Strategy

1. Exact case-insensitive name match with position/team compatibility.
2. Normalized-name deterministic match (`normalize_player_name`).
3. Deterministic alias normalization (suffix/initial/nickname handling).
4. High-threshold fuzzy fallback with tie guard.
5. Manual override file (if provided) supersedes automatic match.

## Team/Position Normalization

- Team codes normalized from guide aliases (ex: `BLT->BAL`, `CLV->CLE`, `HST->HOU`, `ARZ->ARI`).
- Positions normalized to project taxonomy:
  - offense: `QB/RB/WR/TE`
  - IDP families: `DL/LB/DB` (from `DI/ED/LB/CB/S` source labels)

## Known Weak Points / Manual Review Focus

- Fringe players absent from current canonical universe (often FB/depth entries).
- New rookies or camp-battle names not yet present in current dynasty snapshot.
- Multi-role players (example: players appearing in both offense + IDP contexts).
- Two-way or renamed players may create low-confidence fuzzy candidates.

## Annual Reuse Process

1. Drop new guide PDF into `data/imports/mike_clay/`.
2. Run `scripts/import_mike_clay.py`.
3. Review `reports/import_summary.json`, unmatched/low-confidence reports.
4. Add manual overrides if needed and rerun.
5. Hand off normalized outputs for formula integration layer.

No code change should be required unless PDF table structure materially changes.

## Runtime Consumption

The normalized import is now consumed by the live value contract layer:
- `src/api/data_contract.py` (authoritative `valueBundle` path)
- `src/offseason/mike_clay/integration.py` (seasonal gating + signal/weight overlay)

That means rankings and trade calculator receive the same Clay-adjusted `fullValue`
from `/api/data` when the offseason gate is active.
