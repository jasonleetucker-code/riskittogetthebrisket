# Identity Audit — July 2026

Sweep of every source CSV in `_SOURCE_CSV_PATHS` for player votes lost
to name drift between vendor spellings and the Sleeper player pool.
Tooling: `scripts/audit_identity_matches.py` (new — replays the exact
`_canonical_match_key` join the contract build performs and fuzzy-scores
every unmatched row against the pool).  Payload audited:
`exports/latest/dynasty_data_2026-07-26.json` (1,095 pool rows after
far-future pick injection); numbers re-verified after the 2026-07-26
data refreshes and the Phase 3-6 merges (search/filters, playerctx,
news) — none of which changed the CSV → pool join this sweep fixes.

## Per-source match rates

Before → after adding the 18 alias entries below to
`CANONICAL_NAME_ALIASES` (`src/utils/name_clean.py`).  "id" = rows
recovered only by the sleeper_id join (pfkDynasty is the only CSV
carrying ids the parser recognizes today).

| Source | CSV rows | Matched before | Matched after | Recovered | Rate after |
|---|---|---|---|---|---|
| ktc | 500 | 497 | 499 | +2 | 99.8% |
| ktcSfTep | 500 | 497 | 499 | +2 | 99.8% |
| idpTradeCalc | 900 | 893 | 899 | +6 | 99.9% |
| dlfIdp | 172 | 171 | 172 | +1 | 100% |
| idpShow | 350 | 347 | 350 | +3 | 100% |
| dlfSf | 281 | 278 | 280 | +2 | 99.6% |
| dynastyNerdsSfTep | 295 | 289 | 290 | +1 | 98.3% |
| fantasyProsSf | 345 | 340 | 342 | +2 | 99.1% |
| fantasyProsIdp | 100 | 97 | 97 | 0 | 97.0% |
| fantasyCalc | 399 | 391 | 392 | +1 | 98.2% |
| otcffbSf | 462 | 460 | 460 | 0 | 99.6% |
| dynastyDaddySf | 307 | 307 | 307 | 0 | 100% |
| flockFantasySf | 440 | 415 | 416 | +1 | 94.5% |
| flockFantasySfRookies | 62 | 62 | 62 | 0 | 100% |
| yahooBoone | 410 | 380 | 380 | 0 | 92.7% |
| fantasyProsFitzmaurice | 299 | 299 | 299 | 0 | 100% |
| dlfRookieSf | 55 | 55 | 55 | 0 | 100% |
| dlfRookieIdp | 29 | 29 | 29 | 0 | 100% |
| draftSharks | 453 | 416 | 421 | +5 | 92.9% |
| draftSharksIdp | 411 | 313 | 321 | +8 | 78.1% |
| fantasyNavigatorSf | 758 | 457 | 457 | 0 | 60.3% |
| pfkDynasty | 496 | 476 (+1 id) | 477 | id→name | 96.2% |

Total: **34 rows recovered at the CSV join** (33 net-new; the
pfkDynasty Gainwell row moved from the id-join fallback to the primary
name join).

## Contract-level impact (full `build_api_data_contract` rebuild)

Verified by a full row-by-row diff of two complete contract builds
(alias table off vs on) on the 2026-07-26 payload: **16 player rows
gain 24 source votes; zero rows lose anything.**

| Source | Before | After | Δ |
|---|---|---|---|
| dlfIdp | 171 | 172 | +1 |
| idpShow | 346 | 349 | +3 |
| dlfSf | 278 | 280 | +2 |
| dynastyNerdsSfTep | 289 | 290 | +1 |
| fantasyCalc | 391 | 392 | +1 |
| fantasyProsSf | 340 | 342 | +2 |
| flockFantasySf | 414 | 415 | +1 |
| draftSharks | 409 | 414 | +5 |
| draftSharksIdp | 293 | 301 | +8 |
| **total** | | | **+24** |

The remaining 10 audit-level recoveries (ktc ×2, ktcSfTep ×2,
idpTradeCalc ×6) show no contract delta because the scraper's own
dashboard payload already carried those values under the Sleeper
spelling — for them the alias hardens the CSV *fallback* path (used
when a scrape fails and the CSV persists) and fixes
`sourceOriginalRanks` / `sourceNativeValues` / `sourceAudit` metadata
stamping, which previously missed on the drifted names.

Rows gained (source votes added by the aliases): Kenny Gainwell
(dlfSf, dynastyNerdsSfTep, fantasyProsSf, flockFantasySf,
draftSharks), Rob Henry (fantasyProsSf, draftSharks, fantasyCalc),
Dru Phillips (idpShow, draftSharksIdp), Cam Bynum (idpShow,
draftSharksIdp), Nnamdi Madubuike (dlfIdp), Nick Martin (idpShow),
Joshua Palmer (dlfSf), Cam Skattebo, Cam Ward, Donoven McCulley
(draftSharks), Nate Landman, Pat Surtain, Dax Hill,
C.J. Gardner-Johnson, Mike Jackson, Sauce Gardner (draftSharksIdp).

## Aliases added (all in `CANONICAL_NAME_ALIASES`, `src/utils/name_clean.py`)

Verification rule: an alias was added only when position, age, and
team agree between the vendor row and the pool row.  Age pairs below
read *pool / DraftSharks* — DS is the only source publishing age, and
its figures are decimal and re-derived on every refresh, so they drift
~0.1 between snapshots (values here are the 2026-07-26 refresh).  Team
is the pool's `team` field; the 2026-07-26 DS refresh ships an **empty
Team column**, so DS-side team corroboration comes from the 2026-07-25
snapshot when the column was still populated.

| Vendor spelling (sources) | Pool spelling | Evidence |
|---|---|---|
| Kenneth Gainwell (ktc, ktcSfTep, idpTradeCalc, dlfSf, dynastyNerds, fantasyProsSf, flockFantasySf, draftSharks, pfkDynasty) | Kenny Gainwell | RB, TB, 27/27.3; pfkDynasty sleeper_id **7567** join already proved identity |
| Gabriel Davis (ktc, ktcSfTep, idpTradeCalc) | Gabe Davis | WR, FA, 27; KTC value 1071 consistent with the veteran WR |
| Alim McNeil (idpTradeCalc) | Alim McNeill | DL, DET, 26/26.2 — vendor single-l typo; draftSharksIdp spells it McNeill |
| Andru Phillips (idpTradeCalc, idpShow, draftSharksIdp) | Dru Phillips | DB, NYG, 24/24.6 |
| Camryn Bynum (idpTradeCalc, idpShow, draftSharksIdp) | Cam Bynum | DB, IND, 28/28.0 |
| Nickolas Martin (idpTradeCalc, idpShow) | Nick Martin | LB, SF, age 23 rules out the retired IND center |
| Josh Palmer (dlfSf) | Joshua Palmer | WR, BUF, 26 |
| Cameron Skattebo (draftSharks) | Cam Skattebo | RB, NYG, 24/24.4 |
| Cameron Ward (draftSharks) | Cam Ward | QB, TEN, 24/24.2 |
| Nathan Landman (draftSharksIdp) | Nate Landman | LB, LAR, 27/27.7 |
| Patrick Surtain II (draftSharksIdp) | Pat Surtain | CB, DEN, 26/26.3 |
| Daxton Hill (draftSharksIdp) | Dax Hill | DB, CIN, 25/25.8 |
| Donaven McCulley (draftSharks) | Donoven McCulley | WR, MIA UDFA, 23/23.5 — vendor a/o vowel drift |
| Chauncey Gardner-Johnson (draftSharksIdp) | C.J. Gardner-Johnson | DB, BUF, 28/28.6 — legal first name |
| Michael Jackson (draftSharksIdp) | Mike Jackson | CB, CAR, 29/29.5 |
| Ahmad Gardner (draftSharksIdp) | Sauce Gardner | DB, IND, 24/24.8 — legal first name |
| Justin Madubuike (dlfIdp) | Nnamdi Madubuike | DL, BAL, 28/28.7 — player renamed 2024; DLF IDP still uses the old name |
| Robert Henry Jr. (fantasyProsSf, draftSharks, fantasyCalc) | Rob Henry | RB, UTSA UDFA → WAS, 24/24.5 |

### Collision safety

`scripts/audit_identity_matches.py` computes an **alias
collision-delta** on every run: for each pool row it compares the
pre-alias name (`normalize_player_name`) with the post-alias name
(`resolve_canonical_name`), and reports any post-alias name that
absorbs more than one distinct pre-alias name — i.e. an alias, not the
normalizer, merged two real pool rows.  Result with all 18 entries:
**0 collisions**, so no whitelist is needed.

The check runs at **name granularity, not `name::position_group`
granularity**, and that distinction is load-bearing.  The CSV join in
`_enrich_from_source_csvs` keys `csv_lookup` by the name-only
`_canonical_match_key`; when one canonical name maps to pool rows in
several position groups it *replicates* the matched entry across all
of them (the `len(row_groups) > 1` branch).  A group-keyed check is
therefore blind to the worst case — an alias pulling two players of
different position families onto one name (a hypothetical WR "Michael
Jackson" absorbing CB Mike Jackson's draftSharksIdp vote).  An earlier
revision of this function keyed on `canonical_player_key` and reported
exactly that case clean; it now reports it as a collision with
`crossFamily: true`.  Pre-existing same-name collisions that occur
*without* any alias (e.g. "DJ Turner" WR vs "DJ Turner II" CB, merged
by the suffix stripper) are deliberately excluded — this is a delta
check, and that class is handled by the position-aware
`canonical_player_key` used elsewhere.

Pinned by `tests/scripts/test_audit_identity_matches.py` (same-family
merge detected, cross-family merge detected, pre-existing collision
correctly not attributed to the alias table, plus an end-to-end run
against the committed CSVs) and per-alias by
`tests/utils/test_name_clean.py::TestIdentitySweepAliases`.

### Where the invariant runs

`scheduled-refresh.yml` pushes new CSVs and exports to `main` every two
hours without running pytest, so the invariant would never be
evaluated against the data that actually changes.
`.github/workflows/audit-identity-matches.yml` closes that gap: it runs
this audit with `--fail-on-collision` on every push touching
`CSVs/site_raw/**` or `exports/latest/dynasty_data_*.json` (plus a
daily cron backstop), fails the job on any collision, and opens/updates
a rolling `identity-collision` issue.  It is a **separate** workflow by
design — an advisory data finding must never block the data refresh
itself.  Unmatched rows never fail the job; only collisions do.

### Blast radius beyond this audit

The audit only measures the `_SOURCE_CSV_PATHS` → player-pool join, but
`CANONICAL_NAME_ALIASES` is consumed more widely.  Other readers of the
same table (via `resolve_canonical_name` / `canonical_player_key`):

* `src/identity/matcher.py` — `_identity_canonical_key` builds master
  `player::<canon>::<group>` identity records from it.
* `src/ros/mapping.py` — rest-of-season projection name mapping.
* `src/api/data_contract.py` — `_canonical_match_key` /
  `_canonical_player_key`, used by enrichment joins beyond the CSV pass.

An alias is therefore correct only if it is correct for *all* of these,
not just for CSV match counts.  The collision-delta check is
pool-level, so it protects the shared identity space rather than any
one consumer — but a future alias should still be sanity-checked
against the identity matcher if it touches a player with master-record
history.

### Gotcha for anyone re-verifying this work

`src/api/data_contract._SOURCE_CSV_PARSE_CACHE` is keyed on
`(csv path, mtime)` and caches a lookup whose keys are **already
alias-resolved**.  An A/B contract build that mutates the alias table
in-process between arms reuses the first arm's resolved keys and
reports a false "0 delta".  Run each arm in a fresh interpreter (or
clear the cache between arms).  The before/after numbers in this
document were produced that way.

## Normalizer changes

None.  Every near-miss was nickname / legal-name / typo drift — the
deterministic alias table is the right layer.  No case was found that
`normalize_player_name` (suffix, punctuation, apostrophe, initials,
diacritics handling) should have collapsed but didn't.

## Remaining unmatched (categorized, after fix)

* **Genuinely absent from the pool (the overwhelming majority).**
  The pool is the live ~1,095-row board; deep vendor boards list
  players Sleeper's scrape no longer carries: retired / free-agent
  veterans (Russell Wilson, Amari Cooper, Odell Beckham, Taysom Hill,
  Miles Sanders, Vita Vea, Grady Jarrett…), deep IDP veterans
  (draftSharksIdp's remaining 90), and non-Sleeper prospects (Diego
  Pavia, Seydou Traore).  fantasyNavigatorSf's 301 unmatched (60.3%
  rate) are almost entirely this class — FN publishes ~800 rows
  including long-retired players; every one of its 15 fuzzy
  near-misses was verified to be a DIFFERENT player (e.g. Ian Thomas
  vs Brian Thomas, Eric Gray vs Cedric Gray, Amari vs Omar Cooper).
  No action possible or needed: no pool row exists to receive the vote.
* **Confusable but distinct (verified NOT aliased).**  Mike Williams
  (WR) vs Mykel Williams (DL), Austin Hooper (TE) vs Austin Booker
  (DL), A.J. Terrell vs brother Avieon Terrell, Cam Hart (CB) vs Cam
  Ward (QB), Jalon Daniels vs Jayden Daniels.  Left alone by design.
* **Same player, no pool row either way**: Zonovan "Bam" Knight
  (ktc/fantasyProsSf/yahooBoone say "Bam", fantasyCalc/flock say
  "Zonovan") — neither spelling exists in the pool, so an alias would
  recover nothing.  Revisit only if he re-enters the pool.

## Recommendations

1. **`dynastyNerdsSfTep.csv` carries a `SleeperId` column that is
   silently ignored** — `_SLEEPER_ID_ALIASES` in
   `src/api/data_contract.py` recognizes `sleeper_id` / `sleeperId` /
   `sleeper_player_id` but not `SleeperId`.  Adding the spelling would
   give Dynasty Nerds the same ID-grade drift immunity pfkDynasty has.
   Not done in this sweep (out of the additive-alias mandate for that
   file); one-token change for a follow-up.
2. Vendors could be asked/patched at the fetcher level to emit
   sleeper ids where their APIs expose them (fantasyNavigator rows
   carry `ktc_player_id` today, unused).
3. **DraftSharks stopped emitting its `Team` column** in the
   2026-07-26 refresh (header still declares `Team`, every value is
   empty).  Nothing in the pipeline reads it today, but it was the
   strongest corroborating field for alias verification — worth a
   fetcher-side check before the next identity sweep.
4. Re-run `python scripts/audit_identity_matches.py` after any scrape
   schema change or monthly; unmatched `near_miss` rows ≥0.84
   similarity are the triage queue.
