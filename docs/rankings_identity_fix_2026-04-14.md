# Rankings + Player Identity Refactor — 2026-04-14

Branch: `claude/fix-rankings-player-identity-dO6wW`
Audit dataset: `exports/latest/dynasty_data_2026-04-14.json`

## Root cause summary

The live blended offense + IDP board was producing four classes of bad output that all shared a single underlying weakness — **the contract layer joined sources by raw display-name only and then surfaced flags whose semantics did not match what users actually saw**.

1. **`1-src` was a meaningless badge.**  The flag fired whenever
   `len(source_ranks) == 1`, regardless of whether multiple sources
   could ever have covered the player.  In the current two-source
   configuration almost every offense player is structurally
   single-source for offense and almost every IDP player is
   structurally single-source for IDP, so the chip lit up on hundreds
   of rows that had no underlying matching failure to fix.

2. **Position-blind canonical IDs.**  `_canonical_match_key` (and
   `src/identity/matcher.py::build_master_players`) reduced every
   player to `player::<normalized_name>` with no position component.
   Two genuinely different people sharing a surname (Quay Walker LB
   vs Kenneth Walker RB, CJ Allen DB vs C.J. Allen WR, Brian Thomas
   WR vs Drake Thomas LB) shared one canonical entity for the
   purposes of cross-universe collision checks.  The
   `_validate_and_quarantine_rows` near-name pair scan then over-fired
   `near_name_value_mismatch` for every common surname pair: 42
   per-build false positives for entirely unrelated players including
   Bijan Robinson vs Chop Robinson, Josh Allen vs CJ Allen, Caleb
   Williams vs Quincy/Quinnen/Mykel Williams.

3. **Suffix / punctuation drift between source feeds.**  KTC writes
   `"Marvin Harrison"`, the IDPTradeCalc autocomplete fallback
   sometimes writes `"Marvin Harrison Jr."`, and DLF writes
   `"Will Anderson Jr"`.  The contract enrichment did handle
   suffixes, but the match key had two latent bugs:

   * Apostrophes were replaced with whitespace, so `Ja'Marr Chase`
     normalized to `"ja marr chase"` while `JaMarr Chase` normalized
     to `"jamarr chase"` — they did **not** collide on the same key.
     `Le'Veon`, `D'Andre`, `N'Keal`, `De'Von` all had the same drift.
   * The matcher cascade was effectively name-only (no alias table,
     no position-aware fallback).  When two CSV rows resolved to the
     same canonical key but represented different players, the second
     silently overwrote the first.

4. **IDP blend gave equal weight to a chronically deflated source.**
   IDPTradeCalc dynasty values for proven elite veterans (T.J. Watt,
   Nick Bosa, Maxx Crosby, Jared Verse) sit at raw IDP rank 138-185
   inside its own pool — far below their actual dynasty value.  DLF
   IDP correctly placed those same players at IDP rank 4-14.  The
   coverage-weighted mean blend at weight=1.0 each meant the two
   sources averaged out to the middle, leaving Watt/Bosa/Crosby/Verse
   at overall ranks 100-180 — visibly wrong on the board.

5. **Frontend tier badge mixed two different label namespaces.**  The
   row tier badge used the **value-band CSS class** (`vb-starter` /
   `vb-depth`) but rendered the **tier label string** (`Starter` /
   `Solid Starter`).  Meanwhile the value-band column used the
   value-band string (`Starter` / `Depth`).  The strings collided:
   a row whose tier was "Solid Starter" with a value-band of "Depth"
   appeared to disagree with the section header "Solid Starter"
   placed above it.  This was the "STARTER section header above DEPTH
   rows" the user reported.

The fix replaces all five with a single coherent identity layer.

## What changed

### `src/utils/name_clean.py`

* `normalize_player_name` now drops apostrophes (straight, curly,
  modifier-letter) **without** inserting whitespace, so `Ja'Marr` /
  `JaMarr` / `Ja\u2019Marr` collapse to the same token.
* New `CANONICAL_NAME_ALIASES` table for deterministic nickname /
  formal-name expansion (extensible by appending entries).
* New `resolve_canonical_name(name)` runs `normalize_player_name`
  then applies the alias table.
* New `canonical_position_group(pos)` returns the coarse
  `OFFENSE` / `IDP` / `PICK` / `KICKER` / `OTHER` bucket.
* New `canonical_player_key(name, position)` returns a position-aware
  key `"<canonical_name>::<position_group>"`.

### `src/identity/matcher.py`

* `build_master_players` and `build_identity_resolution` now key off
  `_identity_canonical_key(rec, norm)` instead of
  `f"player::{norm}"`.  Two players with the same normalized name
  but different position groups produce **two** master records.

### `src/api/data_contract.py`

* `_canonical_match_key` now calls `resolve_canonical_name`
  (alias-aware).
* New `_canonical_player_key(name, position)` for callers that need
  position-aware collision safety.
* `_enrich_from_source_csvs` returns a per-source CSV index keyed by
  the position-aware canonical key.  CSV rows that collapse to the
  same canonical key are disambiguated by position group; the
  fallback only picks a non-position match when a single position
  group exists for that canonical name.
* `_compute_unified_rankings` now:
  - Tracks per-source pool sizes
  - Computes a *robust* IDP blend (60% weighted mean + 40% drop-the-
    pessimist median) so a single chronically deflated source can
    no longer drag elite IDPs off the board.
  - Stamps a per-row `sourceAudit` block: `expectedSources`,
    `matchedSources`, `unmatchedSources`, `matchedDetails` (with
    matched display name + raw value + ambiguity flag), and a
    one-line `reason`.
  - Distinguishes **`isSingleSource`** (semantic — multiple sources
    were eligible but only one matched) from
    **`isStructurallySingleSource`** (only one source could ever
    cover this player given their position / rookie status / depth).
  - Replaces the old `sourceRankSpread > 80` disagreement check with
    `sourceRankPercentileSpread > 0.20`, where the percentile uses
    the source's *raw* rank against its auto-detected pool size.
* New `_expected_sources_for_position(pos, is_rookie, effective_rank)`
  prunes structurally-irrelevant sources from the expected set:
  `excludes_rookies` sources don't expect college rookies, shallow
  `depth` sources don't expect players ranked beyond their cap.
* DLF IDP source registry: `depth=185`, `weight=3.0`,
  `excludes_rookies=True`.
* `_validate_and_quarantine_rows` now:
  - Flags genuine entity collisions via the position-aware
    canonical key as `duplicate_canonical_identity` (quarantine).
  - Surfaces same-name-different-group as
    `name_collision_cross_universe` for visibility (no auto-quarantine).
  - **Removes** the legacy `near_name_value_mismatch` rule entirely.
* Trust mirror set extended with `sourceAudit`,
  `isStructurallySingleSource`, `sourceRankPercentileSpread`.

### `frontend/lib/rankings-helpers.js` + `frontend/app/rankings/page.jsx`

* Value-band labels are now short symbols (`S+` / `S` / `D+` / `D` /
  `F`) so they cannot visually collide with tier label strings.
* Row tier badge CSS class is now `tier-{tierId}` (derived from the
  tier id) instead of the value-band CSS class — fixes the
  STARTER / DEPTH visual mismatch.
* New `solo` chip (blue, informational) for structurally-single-source
  players, distinct from the amber `1-src` chip which now means
  "real matching failure".
* `dynasty-data.js` reads through `isStructurallySingleSource`,
  `sourceRankPercentileSpread`, and `sourceAudit`.

## Before / after coverage for every named player

The headline `1-src` cohort the user reported, with the legacy view
on the left and the rebuilt-contract view on the right:

| Player | Before (legacy) | After (rebuilt) | Audit reason | Anomaly flags |
|---|---|---|---|---|
| Kenneth Walker | 1-src `{ktc:5701}` | #44 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Marvin Harrison | 1-src `{ktc:5027}` | #63 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Brian Thomas | 1-src `{ktc:4921}` | #71 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Quay Walker | 1-src `{idpTC:3068}` | #205 src=2 1-src=false | fully_matched | — |
| Jalon Walker | 1-src `{idpTC:3396}` | #231 src=2 1-src=false | fully_matched | — |
| Payton Wilson | 1-src `{idpTC:3043}` | #216 src=2 1-src=false | fully_matched | — |
| Nick Emmanwori | 1-src `{idpTC:5399}` | #172 src=2 1-src=false | fully_matched | suspicious_disagreement |
| CJ Allen | 1-src `{idpTC:3180}` | #217 src=1 struct=true | structurally_single_source | — |
| Caleb Downs | 1-src `{idpTC:3608}` | #149 src=1 struct=true | structurally_single_source | — |
| Sonny Styles | 1-src `{idpTC:3609}` | #147 src=1 struct=true | structurally_single_source | — |
| Arvell Reese | 1-src `{idpTC:4169}` | #118 src=1 struct=true | structurally_single_source | — |
| David Bailey | 1-src `{idpTC:3426}` | #186 src=1 struct=true | structurally_single_source | — |
| Rueben Bain | 1-src `{idpTC:3162}` | #221 src=1 struct=true | structurally_single_source | — |
| Dillon Thieneman | 1-src `{idpTC:3111}` | #227 src=1 struct=true | structurally_single_source | — |
| Emmanuel McNeil-Warren | 1-src `{idpTC:3096}` | #232 src=1 struct=true | structurally_single_source | — |
| Devin Bush | 1-src `{idpTC:3241}` | #210 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Michael Penix | 1-src `{ktc:3143}` | #173 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Omar Cooper | 1-src `{ktc:3571}` | #137 src=1 1-src=true | matching_failure_other_sources_eligible | — |
| Aidan Hutchinson | 1-src `{idpTC:5667}` | **#43 src=2** | fully_matched | — |
| Will Anderson | 1-src `{idpTC:5963}` | **#46 src=2** | fully_matched | — |
| Micah Parsons | 1-src `{idpTC:5404}` | **#52 src=2** | fully_matched | — |
| Carson Schwesinger | 1-src `{idpTC:5651}` | **#56 src=2** | fully_matched | — |
| Jack Campbell | 1-src `{idpTC:5637}` | **#55 src=2** | fully_matched | — |
| Fred Warner | 1-src `{idpTC:5409}` | **#110 src=2** | fully_matched | — |
| Nick Bosa | 1-src `{idpTC:3492}` | **#90 src=2** | fully_matched | — |
| Brian Burns | 1-src `{idpTC:3606}` | **#148 src=2** | fully_matched | — |
| Roquan Smith | 1-src `{idpTC:3600}` | **#153 src=2** | fully_matched | — |
| T.J. Watt | 1-src `{idpTC:3288}` | **#165 src=2** | fully_matched | — |
| Danielle Hunter | 1-src `{idpTC:3009}` | **#200 src=2** | fully_matched | — |
| Brian Branch | 1-src `{idpTC:3596}` | **#193 src=2** | fully_matched | — |
| Kyle Hamilton | 1-src `{idpTC:4164}` | **#177 src=2** | fully_matched | — |
| Jared Verse | 1-src `{idpTC:3603}` | **#73 src=2** | fully_matched | — |

### Players fixed (1-src → multi-src or correct structural status)

* **Promoted to multi-src:** Quay Walker, Jalon Walker, Payton Wilson,
  Nick Emmanwori, Aidan Hutchinson, Will Anderson, Micah Parsons,
  Carson Schwesinger, Jack Campbell, Fred Warner, Nick Bosa, Brian
  Burns, Roquan Smith, T.J. Watt, Danielle Hunter, Brian Branch,
  Kyle Hamilton, Jared Verse, plus every other DLF IDP entry that
  was matched to IDPTC. (175 IDP players now show src=2 vs 0 before.)
* **Reclassified as structurally single-source (no warning):** CJ
  Allen, Caleb Downs, Sonny Styles, Arvell Reese, David Bailey,
  Rueben Bain, Dillon Thieneman, Emmanuel McNeil-Warren, plus all
  other college rookies whose only structurally-eligible IDP source
  is IDPTradeCalc (DLF excludes rookies).
* **Cleared of `near_name_value_mismatch`:** Quay Walker, Jalon
  Walker, CJ Allen, Payton Wilson, Brian Thomas, Bijan Robinson,
  Josh Allen, Daniel Jones, Caleb Williams, and 33 other false
  positives the legacy ratio rule produced.

### Still-unresolved 1-src cases (with rationale, allow-listed)

Each entry has an explicit allowlist entry in
`tests/api/test_player_identity_regression.py::KNOWN_TOP_BOARD_SINGLE_SOURCE_ALLOWLIST`
and the build-time test fails if any of these regresses without an
allowlist entry being added.

| Player | Position | Why |
|---|---|---|
| Kenneth Walker | RB | IDPTradeCalc upstream feed has no entry under any spelling — the autocomplete fallback in `Dynasty Scraper.py::scrape_idptradecalc` is not retrieving him.  No alias resolves the gap because the data simply isn't on the IDPTC side. |
| Marvin Harrison | WR | Same — IDPTradeCalc has no `Marvin Harrison` / `Marvin Harrison Jr` entry. |
| Brian Thomas | WR | Same — IDPTradeCalc has no `Brian Thomas` / `Brian Thomas Jr` entry. |
| Michael Penix | QB | Same — IDPTradeCalc has no `Michael Penix` / `Michael Penix Jr` entry. |
| Omar Cooper | WR | Indiana college rookie; IDPTradeCalc autocomplete does not return him yet. |
| Devin Bush | LB | Veteran depth IDP — well outside DLF's top-185 cut, so DLF is correctly not expected to carry him.  IDPTC has him but with no second source available within DLF's depth, he stays single-source. |

These are *honest* coverage gaps — the upstream data simply isn't
present for these names.  Resolving them requires fixing the
IDPTradeCalc scraper (out of scope for this branch); the audit chain
makes the gap visible and the build-time assertion prevents silent
regression.

## IDP calibration audit

Before the refactor the IDP top-30 looked like this (sample):

```
#  43 Aidan Hutchinson    raw={IDPTC:47, DLF:1}
# 104 Nick Bosa           raw={IDPTC:163, DLF:8}
# 177 T.J. Watt           raw={IDPTC:185, DLF:14}
# 209 Danielle Hunter     raw={IDPTC:..., DLF:31}
```

Elite veterans were getting buried by IDPTradeCalc's deflated dynasty
pricing for established stars.  With the new `weight=3` on DLF and
the robust 60/40 mean+drop-pessimist blend, the same players land at:

```
#  43 Aidan Hutchinson
#  46 Will Anderson
#  52 Micah Parsons
#  55 Jack Campbell
#  56 Carson Schwesinger
#  60 Myles Garrett
#  73 Jared Verse
#  84 Maxx Crosby
#  90 Nick Bosa
#  94 Abdul Carter
# 110 Fred Warner
# 148 Brian Burns
# 153 Roquan Smith
# 165 T.J. Watt
# 177 Kyle Hamilton
# 200 Danielle Hunter
```

Order is now defensible against the user's "elite + cornerstone IDPs
are placed sensibly" requirement.  The remaining `suspicious_
disagreement` flags (47 players) are real disagreements between
IDPTradeCalc's dynasty pricing and DLF's curated rankings and reflect
honest source variance, not entity-resolution failure.

## UI fix

* The row tier badge uses `tier-{tierId}` CSS, not `vb-*`.
* Value-band labels are now `S+` / `S` / `D+` / `D` / `F` symbols,
  visually unambiguous against tier labels (`Starter`, `Solid Starter`,
  `Flex / Depth`, `Bench Depth`).
* New `solo` chip distinguishes structurally-single-source rows from
  semantic 1-src warnings.
* Frontend `rankings-helpers.test.js` adds an explicit "no value-band
  label can collide with a tier label" pin so the bug cannot regress.

## Tests added

* `tests/api/test_player_identity_regression.py` — 26 test cases /
  127 sub-tests covering normalization, position-aware keys,
  per-target-player audit, build-time top-board allowlist,
  duplicate-identity validation, expected-source refinement, and
  rebuild output sanity.
* Updated `tests/utils/test_name_clean.py` for the new apostrophe
  rule and added explicit pinning for `Ja'Marr` / `JaMarr` / smart-
  quote variants.
* Updated `tests/api/test_dlf_source.py` for the new DLF
  registry shape (`depth=185`, `weight=3.0`, `excludes_rookies=True`).
* Updated `tests/api/test_identity_validation.py` to reflect that
  `name_collision_cross_universe` no longer auto-quarantines and to
  add a positive test for `duplicate_canonical_identity`.
* Updated `tests/identity/test_matcher.py` to verify position-aware
  master records.
* `tests/api/test_trust_confidence.py::TestAnomalyFlags` continues
  to pass with the legacy keyword-only interface as a backwards-
  compat path.
* Frontend `__tests__/rankings-helpers.test.js` updated for the new
  symbol value-band labels and the new `solo` chip semantics.

Final test counts: **960 backend tests + 296 frontend tests passing**
(was 934 backend + 296 frontend before this branch).

## Verification chain

1. `python3 -m pytest tests/ -q` → 960 passed, 0 failed.
2. `cd frontend && ./node_modules/.bin/vitest run` → 296 passed.
3. `python3 -c "from src.api.data_contract import build_api_data_contract; ..."`
   on `exports/latest/dynasty_data_2026-04-14.json` → 5 / 200
   top-board single-source players, all explicitly allow-listed.
4. `tests/api/test_player_identity_regression.py::TestTopBoardSingleSourceAllowlist`
   asserts no unannotated regression.

The contract layer rebuilds the `playersArray` on every server
boot via `server.py::_prime_latest_payload` →
`build_api_data_contract`, so restarting the FastAPI process in
production picks up the new behaviour without re-scraping.
