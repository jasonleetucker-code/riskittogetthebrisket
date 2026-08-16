# C1-ID-02 — Pick-identity census (evidence)

Measured on origin/main `e3b230e31` (2026-08-16) by seven parallel sweeps over the
contract pipeline, the Sleeper side, the trade engines, draft/BDVM/ROS, the
frontend, the scraper + scripts + persisted stores, and the identity/docs
cross-check. Raw yield: **97 representation records and 56 red candidates**
(overlapping across slices by design — each sweep reported everything it could
see). This file is the deduplicated census the design record
(`C1_ID_02_PICK_IDENTITY.md` §2) summarizes; dispositions are the design
record's §5, refined here after measurement.

The execution map's "7 representations" was an estimate. Deduplicated, the
census measures **39 independent pick-identity definition sites** in four
families — every one either adapted onto the owner in this unit, retained as a
provider wire format, or deferred with a written reason and (where drift is
possible) a lock.

## A. Owned-asset structured shapes (league side) — 12

| # | shape | where | disposition |
|---|---|---|---|
| A1 | Sleeper `/traded_picks` row (`season:str, round, roster_id=origin, owner_id`) | provider wire | RETAIN (consumed via owner constructors) |
| A2 | Sleeper tx `draft_picks` entry (+`previous_owner_id`) | provider wire | RETAIN (C1-U8 will stamp canonical ids at capture) |
| A3 | scraper baked `pickDetails` (camelCase, `season:int`, `fromRosterId`) | `Dynasty Scraper.py` | ADAPTED — fold+labels delegate; +`assetId` |
| A4 | scraper in-run `pick_identity` map | `Dynasty Scraper.py` | **RETIRED** (this unit) |
| A5 | overlay `pickDetails` (snake_case, `season:str`, `original_roster_id`) | `sleeper_overlay._build_pick_ownership` | ADAPTED — fold delegates; +`assetId` |
| A6 | public-league ownership row (origin as **user id**, label `"2027 R1"`) | `public_league/draft.py` | DEFER — bespoke multi-season fold (last-write-wins across season snapshots), origin retained; presentation-only labels |
| A7 | public draft-result pick (consumed pick + player + auction `amount`) | `public_league/draft.py::_normalize_pick` | RETAIN (execution record, not asset identity) |
| A8 | draft-capital `SleeperDerivedPick` (reverse-standings **assumed** slots) | `draft_capital_fallback.py` | ADAPTED (name grammar); the slot-assumption is documented, not identity |
| A9 | ROS pick-projection row (projected slot, origin-driven, dual-owner) | `src/ros/pick_projection.py` | RETAIN — projection layer; label fabrication recorded as follow-up F6 |
| A10 | live-draft pick event | `sleeper_overlay` draft polling | RETAIN (execution events) |
| A11 | retention league-events row (C1-RET-06 substrate) | `src/retention/league_events.py` | RETAIN (append-only evidence; C1-U8 consumer) |
| A12 | public-league snapshot persisted `traded_picks` | `public_league/snapshot*` | RETAIN (verbatim provider archive) |

## B. Market/board shapes — 10

| # | shape | where | disposition |
|---|---|---|---|
| B1 | composite `players` dict pick rows (scraper rebuild `_put_pick`) | scraper → export | RETAIN (names now = owner grammar) |
| B2 | `playersArray` canonical pick row (`assetClass="pick"`) | `data_contract` | RETAIN — the canonical market surface |
| B3 | `pickAnchors` keys (`"2026 1.01"` — no "Pick" token) | scraper export | RETAIN; owner's `parse_pick_label` covers the grammar |
| B4 | `pickAliases` tier→centre-slot map | `data_contract` | RETAIN; centres locked to frontend by parity test |
| B5 | synthetic far-future pick rows (cloned year identity) | `data_contract._inject_far_future_pick_sources` | RETAIN (C1-U6 territory) |
| B6 | `dlfRookieSf` synthetic slot stamps (rookie ordinal → pick name) | `data_contract` ~4175 | RETAIN, recorded (valuation-lane translation; F3) |
| B7 | BDVM pick parse (board name → overall slot; tier round 5-6 gap) | `src/bdvm/service.py` | DEFER (F4) — delegation would change BDVM acceptance, a value surface |
| B8 | frontend pick-stack `parsePickAsset` + slot-dollar grid | `frontend/lib/pick-stack.js` | DEFER (frontend family, locked) |
| B9 | KTC provider pick ids (`playerID`, positionID=7 "RDP") + `ktcIdMap` | `trade/ktc_import.py`, scraper | RETAIN (provider crosswalk) |
| B10 | draft-capital sheet-path pick rows + `rookieKtcValue` | `server.py` default-league path | RETAIN (valuation surface) |

## C. Identity serialization grammars — 7

| # | grammar | example | disposition |
|---|---|---|---|
| C1 | board slot/tier row names | `2026 Pick 1.06`, `2027 Early 1st` | **OWNER-OWNED** (moved verbatim; contract delegates) |
| C2 | roster labels, baked dialect | `2026 1.03 (own)`, `2027 Mid 1st (from Blaine)` | ADAPTED — formatted by owner, byte-parity |
| C3 | roster labels, overlay dialect | `2027 1.05`, `2027 1st` | ADAPTED — formatted by owner, byte-parity |
| C4 | trade-history labels (2 legacy copies → 1 owner implementation) | `2027 Mid 1st (from Blaine)` | ADAPTED |
| C5 | public-league labels | `2027 R1` | DEFER (presentation; owner parses) |
| C6 | intel persisted generic key | `pick:2027:2` | **DEFER to C1-U8** — persisted SQLite grade; strings now formatted by the owner with the origin collapse documented at the definition |
| C7 | scaffold pick-id grammar (dormant lane, halted 2026-04-20) | `pick::2026::1::UNKNOWN` (`identity/matcher.py`, `0001_identity_schema.sql`) | DEFER — not production; subsume when the scaffold lane resumes (C1-RET-07) |

Plus the canonical grammars this unit MINTED: `pick:<leagueKey>:<season>:r<N>:o<rid>`
and `mpick:<year>:r<N>[:s<slot>|:t<tier>]` — formally unambiguous against C6/C7.

## D. Independent parser/detector definitions — 10

| # | definition | where | disposition |
|---|---|---|---|
| D1 | `_is_pick_name` + `_parse_pick_slot`/`_parse_pick_tier`/`_pick_year_from_name` | `data_contract` | **ADAPTED — delegate to owner** |
| D2 | scraper `_parse_pick_label` (vendor labels; coerces bare rounds to MID tier + assumed year) | scraper ~4759 | RETAIN, recorded (ingestion translation, valuation lane; F5) |
| D3 | scraper `_looks_like_pick_name` (+ its verbatim transcription in `identity/resolution.py`'s `pick_name` refusal) | scraper / owner package | RETAIN — one definition, two pinned copies (C1-U2 parity) |
| D4 | finder.py name sniff (`startswith("20")` / `" pick "` / `" round "`) | `trade/finder.py` | RETAIN, recorded — engine-scoped universe filter (F7) |
| D5 | rank-history `_PICK_NAME_PATTERNS` (accepts `2027 R2`; rejects bare slot) | `src/api/rank_history.py` | DEFER — exclusion set gates PERSISTED history; unification would change what is recorded (C1-HIST-02 owns the pick-history question) |
| D6 | normalization-validator patterns (incl. a legacy `"2026 1st Round"` grammar) | `src/canonical/normalization_validator.py` | DEFER — validator acceptance change = build-gate change |
| D7 | calibration legacy pick curve + parser | `src/canonical/calibration.py` | dead code — RECORD for deletion follow-up (F8) |
| D8 | frontend `parsePickToken` / `buildPickLookupCandidates` / `normalizePickLabel` | `frontend/lib/trade-logic.js` | DEFER — locked by `test_pick_grammar_frontend_parity.py`; migration needs C1-U6 generic rows |
| D9 | frontend legacy `PICK_RE` (materializer + delta synthesis) | `frontend/lib/dynasty-data.js` | DEFER (same lock family) |
| D10 | scripts predicate family (audit_identity_matches, backtest_ktc_volatility tier-only, prep_scoring_data.R, generate_test_seeds substring) | `scripts/` | RECORD — tooling; each divergence now named (F9) |

## RED candidates disposition

Six defect classes were promoted to pinned RED tests
(`tests/identity/test_pick_identity_red.py`) — the execution-map round-trip
failure, N-assets-one-label, wall-clock/rename serialization drift,
unknown-slot-fabricated-as-Mid, the intel origin-stripping key, and league-free
shapes. The remaining census reds fall into three buckets:

* **Closed structurally by the owner** (join-by-type failures, dialect
  mismatches, origin-as-display-text) — the GREEN suite covers the class.
* **Valuation-lane defects, out of C1-U3 scope, recorded as follow-ups** (F1-F9
  below) — e.g. `_put_pick` stamping a synthetic `ktc` vote, the tier→12-slot
  synthetic fan published as raw observations, tier-geometry disagreement
  between the scraper's rebuild (hardcoded 1-4/5-8/9-12) and the ownership
  labeler (league-size thirds), horizon mismatch leaving 2029-owned picks
  unpriceable (C1-U6), `roster_intel` stamping `pickValue: 0.0` (MISSING as
  ZERO), suggestions/angle ownership blindness (C3 territory), VA tooling's
  generic-tier fallback.
* **Known-and-tracked elsewhere**: picks excluded from `rank_history`
  (`C1-HIST-02`), public-league `_pick_ownership_map` cross-season
  last-write-wins ordering, `_most_traded_pick` counting rows-not-moves
  (CE-18 / C1-U8 lineage).

## Follow-ups recorded, NOT blocking C1-U3 (do not fix without authorization)

* **F1** `_put_pick` fabricates a `ktc` provider vote equal to the model output
  when KTC contributed nothing (scraper ~6486) — provenance defect, valuation lane.
* **F2** `_build_site_pick_map` fans one tier quote into 12 per-slot
  "observations" — synthetic published as raw.
* **F3** `dlfRookieSf` fabricated slot stamps mix rookie-ordinal identity into
  pick-name space.
* **F4** BDVM cannot parse tier picks for rounds 5-6; slot-vs-tier rows of one
  market ref price independently; trade-eval resolves picks by raw string.
* **F5** scraper `_parse_pick_label` coerces bare vendor rounds to MID tier and
  assumes year — ingestion fabrication.
* **F6** `pick_projection` emits PROJECTED slots in the exact-slot label
  grammar (`"2027 1.03"`) — projection colonizing the exactness namespace.
* **F7** finder's `name.startswith("20")` pick sniff.
* **F8** `calibration.py` legacy pick curve is dead code still in tree.
* **F9** scripts predicate family divergences (tier-only volatility backtest
  misses slot rows; seed generator substring-matches player names containing
  "Early" etc.).
* **F10** `_most_traded_pick` counts traded_picks rows across the season chain
  as "moves"; movement trail emits one row per season-snapshot appearance.
* **F11** `roster_intel` stamps `pickValue: 0.0` — MISSING IS NEVER ZERO.
* **F12** overlay `_build_pick_ownership` hardcodes `num_rounds=6, num_years=3`
  vs the league's actual `draft_rounds` (three different answers to "which
  rounds exist" across overlay/scraper/crawler).
* **F13** `resolution.looks_like_pick_name` (C1-U2's frozen refusal rung) misses
  four real production label grammars (`2027 R1`, `2027 Round 2`,
  `2026 1.02 (own)`, `2027 Mid 1st (from Blaine)`) and diverges from
  `picks.is_pick_name` on 5 of 9 measured forms — different questions, both
  pinned; the relationship is now documented at both definitions. Widening the
  refusal is a player-identity behavior change requiring its own authorization.
* **F14** the contract's CSV-enrichment join runs every PICK row through the
  player-name normalizer (`resolve_canonical_name`), which splits one real pick
  across three normalized keys (`2026 pick 1 06` / `2026 pick 1 6` /
  `2026 1 06`); live joins survive only because both sides emit the same
  canonical spelling today.
* **F15** the dormant identity-scaffold bridge (`scraper_bridge_adapter.py`)
  stamped every CSV row `asset_type='player'`, so the stale 2026-04-20 artifact
  served by `/api/scaffold/identity` carries **84 pick-shaped master-player
  records** (e.g. `player::2026 early 1st::OTHER`) — pick strings minted as
  players in the halted lane (C1-RET-07 adjacency).

## The manifest's "collapse is documented in 3 places", located

1. **W08-F005** (master-site-audit): 216 league picks → 163 distinct trade-asset
   names, 53 unrepresentable; one manager's EIGHT 2027 firsts (origins
   {1,2,3,6,8,9,10,12}) all rendering `2027 Mid 1st` at one price.
2. **`docs/TRADE_HISTORY_AGING_SPEC.md`** :32/:120/§7 — stored trade-history
   pick labels regenerate from the wall clock + current team names; "today's
   pick value presented as historical pick value" is a named forbidden fallback.
3. **`C1-ACQ-03` / intel ledger** — `originalOwnerId` is one hop, not a chain;
   the ledger's persisted asset id strips origin.
