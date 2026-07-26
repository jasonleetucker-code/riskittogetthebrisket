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
(where the CSV carries it) team agree between the vendor row and the
pool row.  Ages below are pool vs DraftSharks CSV (the only source
publishing age).

| Vendor spelling (sources) | Pool spelling | Evidence |
|---|---|---|
| Kenneth Gainwell (ktc, ktcSfTep, idpTradeCalc, dlfSf, dynastyNerds, fantasyProsSf, flockFantasySf, draftSharks, pfkDynasty) | Kenny Gainwell | RB, TB, 27/27.3; pfkDynasty sleeper_id 7567 join already proved identity |
| Gabriel Davis (ktc, ktcSfTep, idpTradeCalc) | Gabe Davis | WR, 27; KTC value 1074 consistent with the veteran WR |
| Alim McNeil (idpTradeCalc) | Alim McNeill | DL, DET, 26/26.1 — vendor single-l typo; draftSharksIdp spells it McNeill |
| Andru Phillips (idpTradeCalc, idpShow, draftSharksIdp) | Dru Phillips | CB, NYG, 24/24.5 |
| Camryn Bynum (idpTradeCalc, idpShow, draftSharksIdp) | Cam Bynum | S, IND, 28/27.9 |
| Nickolas Martin (idpTradeCalc, idpShow) | Nick Martin | LB, SF, age 23 rules out the retired IND center |
| Josh Palmer (dlfSf) | Joshua Palmer | WR, BUF, 26 |
| Cameron Skattebo (draftSharks) | Cam Skattebo | RB, NYG, 24/24.3 |
| Cameron Ward (draftSharks) | Cam Ward | QB, TEN, 24/24.0 |
| Nathan Landman (draftSharksIdp) | Nate Landman | LB, LAR, 27/27.6 |
| Patrick Surtain II (draftSharksIdp) | Pat Surtain | CB, DEN, 26/26.2 |
| Daxton Hill (draftSharksIdp) | Dax Hill | S, CIN, 25/25.7 |
| Donaven McCulley (draftSharks) | Donoven McCulley | WR, MIA UDFA, 23/23.4 — vendor a/o vowel drift |
| Chauncey Gardner-Johnson (draftSharksIdp) | C.J. Gardner-Johnson | DB, BUF, 28/28.5 — legal first name |
| Michael Jackson (draftSharksIdp) | Mike Jackson | CB, CAR, 29/29.4 |
| Ahmad Gardner (draftSharksIdp) | Sauce Gardner | CB, IND, 24/24.8 — legal first name |
| Justin Madubuike (dlfIdp) | Nnamdi Madubuike | DL, BAL, 28/28.6 — player renamed 2024; DLF IDP still uses the old name |
| Robert Henry Jr. (fantasyProsSf, draftSharks, fantasyCalc) | Rob Henry | RB, UTSA UDFA → WAS, 24/24.4 |

Collision safety: `scripts/audit_identity_matches.py` computes an
**alias collision-delta** on every run — a post-alias
`canonical_player_key` that absorbs more than one pre-alias pool key
would mean the table merged two real players.  Result with all 18
entries: **0 collisions**.  The invariant is pinned by
`tests/scripts/test_audit_identity_matches.py` (including a synthetic
proof the detector fires when a merge IS present) and the per-alias
collapses by `tests/utils/test_name_clean.py::TestIdentitySweepAliases`.

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
3. Re-run `python scripts/audit_identity_matches.py` after any scrape
   schema change or monthly; unmatched `near_miss` rows ≥0.84
   similarity are the triage queue.
