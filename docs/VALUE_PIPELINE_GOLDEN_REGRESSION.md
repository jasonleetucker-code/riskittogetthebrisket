# Value Pipeline Golden Regression

## Purpose
This suite prevents silent drift in the live value pipeline by locking a curated player set to expected behavior across:
- source presence
- identity merge
- normalized per-site values
- raw value band
- final adjusted value band

It is designed to catch both:
- source disappearance (ingestion/coverage regressions)
- formula drift (normalization and value-layer changes)

## Live Code Path Under Test
Golden regression executes the production authority path:
- `src/api/data_contract.py:build_api_data_contract`

This includes:
- canonical source map (`canonicalSiteValues`)
- source counting and coverage (`sourceCount`, `valueBundle.sourceCoverage`)
- value layer bundle (`rawValue`, `scoringAdjustedValue`, `scarcityAdjustedValue`, `bestBallAdjustedValue`, `fullValue`)
- final players output (`playersArray` + `players`)

## Fixtures
- Curated frozen input payload:
  - `tests/fixtures/value_pipeline_golden_input.json`
- Golden expectation spec:
  - `tests/fixtures/value_pipeline_golden.json`

Curated cases (`14`):
- elite QB / RB / WR / TE
- elite DL / LB / DB
- rookie offense
- rookie IDP
- aging veteran
- injured player (current proxy: `_formatFitLowSample`)
- draft pick
- partial source coverage
- conflicting source coverage

## Tests
- `tests/api/test_value_pipeline_golden.py`

Checks:
- Contract validity (`validate_api_data_contract`)
- Frozen golden case assertions on merge/source/normalized/value outputs
- Latest payload required-source coverage assertions (source disappearance guard)

## Run
```powershell
$env:PYTHONPATH='.'
python -m unittest tests.api.test_value_pipeline_golden -v
```

## Refresh Procedure (Intentional Formula Change)
Only refresh golden fixtures after business-rule approval for formula behavior changes.

1. Select approved source payload snapshot.
2. Regenerate fixtures:
```powershell
$env:PYTHONPATH='.'
python scripts/refresh_value_pipeline_golden.py --source-payload data/dynasty_data_YYYY-MM-DD.json
```
3. Re-run regression:
```powershell
$env:PYTHONPATH='.'
python -m unittest tests.api.test_value_pipeline_golden -v
```
4. Review diffs in:
- `tests/fixtures/value_pipeline_golden_input.json`
- `tests/fixtures/value_pipeline_golden.json`
5. Confirm change intent in PR notes:
- which formula/business rule changed
- expected impact by case category
- why band or source expectations changed

## Approval Gate
Do not accept golden fixture refreshes that:
- mask source outages
- hide identity merge failures
- absorb unexplained cross-position value shifts
- alter required source presence without explicit source-policy decision
