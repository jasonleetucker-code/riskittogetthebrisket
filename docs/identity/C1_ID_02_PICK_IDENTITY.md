# C1-ID-02 — One pick identity, end to end

**Unit:** C1-U3 · **Manifest row:** `C1-ID-02` · **Kind:** INFRA · **Deps:** C1-U2 (closed)
**Owner module:** `src/identity/picks.py` (created by this unit)
**Status:** design record written before implementation, per the census → RED → design →
owner → migration sequence. Census evidence: §2. RED reproductions: `tests/identity/test_pick_identity_red.py`.

---

## 1. What a draft pick actually IS — the semantic model

Every defect in the census reduces to the same conflation, so the model states the
distinction first:

**A. The league pick asset.** A claim on a selection in one league's season-N rookie
draft. It is *born* identified by whose draft position it represents — the
**originating franchise** — because that franchise's finish determines where the
selection lands. Sleeper's own data model says exactly this: a `traded_picks` row is
`(season, round, roster_id)` where `roster_id` is the origin, and `owner_id` is
merely who holds it now. The asset survives any number of trades unchanged; it
survives the draft-order becoming known unchanged; it is consumed (not destroyed) by
the draft executing.

**B. The market pick reference.** What ranking sources price: "2026 Pick 1.06",
"2027 Early 1st", "a 2028 2nd". Nobody owns these. They are *reference classes* at
three refinement levels — exact slot, tier, generic round — and they are
scoring-profile-scoped like every board value, not league-scoped. A league pick
**resolves to** a market reference for valuation; the resolution is a *function of
its state*, never part of its identity.

Everything measured broken conflates A with B, or serializes A through B's lossy
display grammar and then cannot get back:

- the intel ledger stores A-assets under a B-grade key (`pick:2027:2`) — two real
  2027 2nds collide;
- `team.picks` stores A-assets as B-labels (`"2027 1st"`) — N assets → 1 string;
- trade-history labels serialize A as B plus `"(from <team display name>)"` — origin
  becomes a mutable rename-able string;
- the B-resolution is computed at label-creation time and *baked into the string*,
  so when state advances (slot becomes known) or the wall clock rolls a year, the
  same asset re-serializes differently and no longer equals its stored form;
- the frontend re-derives B from the lossy string and fabricates exactness
  (tier-centre slot `.06`, default tier `Mid`) where the truth is "unknown".

## 1a. Identity vs mutable state

| DEFINES identity (frozen) | MUTABLE STATE (never identity) |
|---|---|
| `league_key` — registry key, never a raw Sleeper id | current owner franchise |
| `season` — the draft year (int) | slot: known `int` or **UNKNOWN** (`None`; never 0, never "Mid") |
| `round` — 1..n (int) | market resolution (which board row prices it, and on what basis) |
| `origin_franchise` — Sleeper `roster_id` of the originating team | canonical value (valuation is a different concept entirely) |
| | display labels (consumer presentation) |
| | provenance observations (who reported it, when) |

Two consequences the tests pin:

* **A trade cannot create a new asset.** Equality/hash use the four identity fields
  only; `owner` lives in state.
* **Slot realization cannot create a new asset.** The 2028 R1 from franchise 5
  exists in 2026 with `slot=None`; when the 2028 draft order lands it becomes
  `slot=7` — same canonical id, new state. Nothing that stored the id before the
  transition dangles after it.

**Origin is an identity dimension, verified rather than assumed:** Sleeper keys
traded picks by origin; two same-year-same-round picks from different origins are
separately tradeable and carry different expected slots (`src/ros/pick_projection.py`
projects a pick's slot from the ORIGIN team's projected finish, and C1-U7's
distributions will too); CE-18 lineage and C1-U8 cost basis require the origin chain.
A pick identity without origin cannot express any of that — it is exactly the
intel-ledger collision.

## 2. Census — every representation measured on current main

Counted at origin/main `e3b230e31` (2026-08-16). The manifest's estimate was ~7.
Seven parallel census sweeps yielded **97 raw representation records and 56 red
candidates**, deduplicating to **39 independent pick-identity definition sites**
in four families — 12 owned-asset structured shapes, 10 market/board shapes, 7
serialization grammars, 10 independent parser/detector definitions. The full
deduplicated census with per-site dispositions is
[`C1_ID_02_CENSUS.md`](C1_ID_02_CENSUS.md); the tables below are the core
subset this design was derived from.

### 2.1 Structured shapes

| # | representation | where | shape / example | origin? | owner? | slot? | league? | notes |
|---|---|---|---|---|---|---|---|---|
| S1 | Sleeper `traded_picks` row | Sleeper API (all fetchers) | `{season:"2027", round:1, roster_id:5, owner_id:9, previous_owner_id:…}` | yes (`roster_id`) | yes | no | implied by fetch URL | season is a **string** |
| S2 | scraper baked `pickDetails` | `Dynasty Scraper.py` run() ~838-956 → contract `sleeper.teams[].pickDetails` | `{season:2026(int), round, fromRosterId, fromTeam:"Blaine", ownerRosterId, slot, label:"2026 1.02 (own)", baseLabel}` | yes + display name | yes | when known | via contract | season is an **int** — S2≠S9 on type for the same asset |
| S3 | scraper `pick_identity` map | `Dynasty Scraper.py` (in-run) | `(season,round,origin_rid) → {baseLabel, fromTeam, slot}` | key | no | yes | in-run | the repo's own partial identity attempt; not exported |
| S4 | overlay `pickDetails` | `src/api/sleeper_overlay.py::_build_pick_ownership` | `{season:"2027"(str), round, slot:None, original_roster_id, owner_roster_id, label:"2027 1st"}` | yes | yes | **always None** (never fetches slots) | per call | field names differ from S2 (`fromRosterId` vs `original_roster_id`) |
| S5 | public-league ownership row | `src/public_league/draft.py::_pick_ownership_map` | `{season:"2027", round, originalOwnerId:<user id>, isTraded, label:"2027 R1"}` | as **user id** (not roster id) | implied by map key | no | snapshot | origin dimension in a different id-space than S1-S4 |
| S6 | draft-capital fallback pick | `src/api/draft_capital_fallback.py::SleeperDerivedPick` | `pick="1.01"`, per-(season,round,slot); ownership from reverse-standings **assumption** for future drafts | derived | yes | assumed | request | slots for future drafts are assumed, flagged in module docs |
| S7 | trade-tx `draft_picks` entry | Sleeper tx via `sleeper_overlay._build_trades_block` + `src/intel/crawler._events_from_tx` | `{season, round, roster_id, owner_id, previous_owner_id}` per traded asset in a tx | yes | yes | no | per league | consumed into L6/K1 lossily |

### 2.2 Label grammars (identity serialized as display strings)

| # | grammar | producer | example | lossy how |
|---|---|---|---|---|
| L1 | board slot row name | contract `_compute_unified_rankings` (`_PICK_SLOT_RE`) | `2026 Pick 1.06` | market-level only (correctly — it IS a market ref) |
| L2 | board tier row name | contract (`_PICK_TIER_RE`), incl. synthetic far-future clones | `2027 Early 1st` | market-level only |
| L3 | roster pick label | scraper baked + overlay `_format_pick_label` | `2026 1.02 (own)`, `2027 Mid 1st (from Team X)`, `2027 1st` | origin as display name or absent; tier **fabricated "Mid" when slot unknown**; format depends on wall-clock year |
| L4 | trade-history label | `_format_trade_pick_label` (duplicated: overlay + scraper inline) | `2027 Mid 1st (from Blaine)` | same as L3; stored in trade history, then re-generated fresh → drift across year/rename |
| L5 | pick-anchor key | scraper `pickAnchors` | `2026 1.01` | no "Pick" token — a third slot spelling |
| L6 | intel asset id | `src/intel/crawler.py` | `pick:2027:2` | **origin stripped — two real assets, one key; PERSISTED in SQLite** |

Plus the public-league presentation form `2027 R1` (from S5) and the KTC provider
form (KTC `playerID` ints with positionID=7 "RDP", named like L2) as provider
crosswalk inputs.

### 2.3 Independent pick-DETECTION heuristics (which rows even are picks)

1. `data_contract._is_pick_name` (3 regexes) + `assetClass == "pick"` stamp;
2. `finder.py`: `pos == "PICK" or name.startswith("20") or " pick "/" round " in name`;
3. frontend `parsePickToken` (its own 2 regexes);
4. `identity/…` pick-shaped-name refusal (player-identity's guard, C1-U2).

### 2.4 Divergent interpretations measured (same question, different answers)

- **Tier boundaries:** backend `_slot_to_tier_label` is league-size-aware
  (`per_tier = size // 3`); frontend hardcodes 12-team thirds (`slot<=4` early).
  A 10-team league's slot-4 pick is "Mid" to the backend and "early" to the frontend.
- **Unknown slot:** backend labels it tier "Mid"; frontend lookup fabricates
  tier-centre slot `.06`; `pick_projection` (correctly) projects it from team
  strength; S4 stores `None`.
- **Season type:** S1/S4/S5 strings, S2 ints — `(season, round, origin)` joins
  fail across representations without coercion.
- **Origin id-space:** S2/S4 roster ids, S5 user ids, L3/L4 display names.

## 3. The canonical contract

### 3.1 Canonical identifiers

```
league pick:  pick:<leagueKey>:<season>:r<round>:o<originRosterId>
              pick:dynasty_main:2027:r1:o5

market ref:   mpick:<year>:r<round>            (generic — slot & tier unknown)
              mpick:<year>:r<round>:t<early|mid|late>   (tier)
              mpick:<year>:r<round>:s<slot>    (exact slot)
```

Properties, each load-bearing:

- **STABLE** — no owner, no slot, no display name, no wall-clock input. An id minted
  at trade time resolves forever.
- **DETERMINISTIC** — pure function of identity fields; no `datetime.now()` anywhere
  in identity construction (the census found wall-clock dependence in L3/L4 label
  *formats*; formats are presentation, ids are not).
- **ROUND-TRIPPABLE** — `parse_*` are exact inverses of `format_*`; property-tested.
- **LEAGUE-SAFE** — `leagueKey` is a component; identical-looking picks in two
  leagues cannot collide. The key is the registry key, never a raw Sleeper league id
  (the registry owns that mapping, and league ids chain year-over-year while the
  registry key is stable).
- **TEMPORALLY SAFE / EXPLICIT ABOUT UNKNOWN** — slot is absent from identity, so
  realization is a state change; unknown slot is `None` and serializes as the
  *generic* market form, never a fabricated tier or slot.
- **NON-AMBIGUOUS** — origin is a component, so the L6/L3 collisions are
  unrepresentable.

### 3.2 Owner module surface (`src/identity/picks.py`)

- `LeaguePickIdentity` (frozen dataclass): `league_key, season, round, origin_roster_id`;
  `.canonical_id`; `parse_league_pick_id()` inverse.
- `MarketPickRef` (frozen dataclass): `year, round, refinement` (slot | tier |
  generic, exactly one); `.canonical_id`; `parse_market_pick_id()`;
  `board_row_name()` ↔ `parse_board_pick_name()` (owns today's `_PICK_SLOT_RE` /
  `_PICK_TIER_RE` grammar), `parse_pick_label()` for every legacy grammar
  (L1-L5 + "(own)/(from …)" annotations + `R1` + KTC names) returning what the
  label PROVES plus explicit `unresolved` reasons — never a guess.
- `LeaguePickState`: `owner_roster_id`, `slot: int | None`, provenance fields.
- `build_pick_ownership(league_key, roster_ids, traded_picks, *, seasons, rounds)`
  — THE default-ownership + traded-diff fold, written once (today it exists 4×:
  scraper, overlay, public-league, draft-capital fallback).
- `market_resolution(identity_or_fields, *, slot, current_draft_year, league_size)
  → PickMarketResolution(ref, basis)` with basis ∈ `exact_slot` /
  `tier_from_slot` / `unknown_slot`. The generic→exact transition IS this function
  changing its answer as `slot` and `current_draft_year` move — identity untouched.
- `slot_tier(slot, league_size)` — the league-size-aware tier rule (backend
  semantics win; the frontend's 12-team hardcode is one of the defects).
- Label formatting for the legacy surfaces (`format_roster_pick_label`,
  `format_trade_pick_label`) — presentation produced BY the owner so every producer
  emits one grammar; the legacy "unknown → Mid" fabrication survives ONLY inside
  these explicitly-named legacy formatters (output parity), never in identity,
  and each stamps the structured truth alongside.

### 3.3 Ownership + lineage semantics

Current owner is state, held next to identity, updated by the traded-pick fold or a
transaction event. `previous_owner_id` on S7 rows gives single-hop lineage today;
the full chain is C1-U8's ledger. **This unit's interface for C1-U8:** every
transaction pick asset can be stamped with `canonical_id` at capture time, so the
future ledger references a stable key instead of a label. This unit does NOT build
the ledger.

### 3.4 Provenance

Provider references ride along, never overwrite: Sleeper's triple IS our identity
key (no separate id exists to preserve); KTC pick entries (`playerID`,
positionID=7) crosswalk to `MarketPickRef` and keep their id in `providerRefs`.

### 3.5 Historical / replay semantics

A canonical id stored at time T parses identically at time T+n: no component decays
(components are birth facts). Labels stored historically (trade history) remain
parseable via `parse_pick_label`, with honesty about what they prove: a stored
`"2027 Mid 1st (from Blaine)"` proves year/tier/round and an origin *display name*;
`parse_pick_label` surfaces `origin_team_name` and leaves roster-id resolution to
the caller's roster map, returning UNRESOLVED rather than fuzzy-matching names.
Missing historical identity stays explicitly missing.

## 4. Migration strategy (this unit)

**No persisted-id rewrite. No flag day. No valuation change.**

1. Owner module + exhaustive tests land first (RED tests prove today's failures on
   the real shapes; GREEN proves the owner closes them).
2. Backend producers route through the owner where the change is behavior-identical
   (verified by parity): the contract's pick regex/parse helpers become imports of
   the owner; the overlay's + scraper's label/tier/ownership logic delegate to the
   owner; the fallback's `_normalize_pick_name` delegates.
3. **Additive identity stamping:** S2/S4 pickDetails and trade pick items gain
   `assetId` (canonical league-pick id) + normalized `season:int`; board pick rows
   already carry `assetClass="pick"` and gain nothing (they are market refs whose
   name IS the canonical market display form). Purely additive; every existing
   field byte-identical.
4. Legacy readers keep working: nothing removed this unit; retirement below.

**Deliberately deferred, recorded not hidden:**

- **Intel ledger key `pick:<season>:<round>` (L6)** — persisted in prod SQLite;
  re-keying is a destructive migration owned by C1-U8 (`C1-ACQ-01/03`), and
  changing only new writes would split joins inside one store. The owner ships
  `parse/format` for this grade with the collision documented at the definition.
- **Frontend lookup grammar (`parsePickToken` / `buildPickLookupCandidates`)** —
  its *output behavior* is valuation-lookup, pinned by existing tests; migrating it
  to stamped ids requires generic-ref board rows (C1-U6) to avoid re-inventing
  tier-centre conventions client-side. This unit adds the stamped fields it will
  read and a Python↔JS grammar-parity test (same pattern as
  `test_source_registry_parity.py`), so the two grammars cannot drift silently
  while the migration waits.
- **S5's user-id origin and S6's reverse-standings slot assumption** — consumers of
  a public page and a widget; both documented, neither is an identity owner.

## 5. Retirement / disposition table

| representation | disposition | mechanism |
|---|---|---|
| S1 Sleeper traded_picks | RETAIN (provider input) | consumed via owner constructors |
| S2 scraper pickDetails | ADAPT | label/tier/fold logic delegates to owner; +`assetId`; shape kept |
| S3 scraper `pick_identity` map | RETIRE | replaced by owner identity (it was the in-run half-version) |
| S4 overlay pickDetails | ADAPT | same as S2 (and S2/S4 now provably serialize one asset identically) |
| S5 public-league ownership | ADAPT (consume owner fold) — presentation label retained | |
| S6 draft-capital fallback | ADAPT (name formatting via owner) | assumption documented |
| S7 tx draft_picks | RETAIN input; stamped with canonical id for C1-U8 | |
| L1/L2 board names | RETAIN — canonical market display grammar, owner-owned | contract imports owner |
| L3/L4 labels | ADAPT — produced by owner formatters, structured truth stamped alongside | |
| L5 anchor keys | RETAIN (scraper-internal), owner parses | |
| L6 intel key | DEFER to C1-U8 (persisted; documented collision) | |
| detection heuristics (2.3) | CONSOLIDATE onto owner predicates where behavior-identical; finder's kept-but-documented (its universe filter is engine-scoped) | |

## 6. Interfaces handed to later units (designed, not built)

- **C1-U4 (as-of ledger):** historical pick values key on `MarketPickRef.canonical_id`
  (market evidence) and `LeaguePickIdentity.canonical_id` (owned-asset history).
- **C1-U6 (completeness):** the generic `mpick:<year>:r<round>` form is the row
  key for "every valid pick has a value"; `market_resolution` already emits it for
  unknown slots, so completeness = every emitted ref resolves to a priced row.
- **C1-U7 (distributions):** distributions attach to a league pick's identity;
  origin franchise is the distribution's driver — present in the id.
- **C1-U8 (acquisition/lineage):** transaction assets stamped with canonical ids;
  the ledger chains them; L6 re-key happens there.
- **C4-MTL (market trade ledger):** external trades join through
  `parse_pick_label` + provider crosswalk, never through player-name machinery.

## 7. RED → GREEN evidence

See `tests/identity/test_pick_identity_red.py` (failures reproduced on real shapes
from the live export + live code paths) and `tests/identity/test_pick_identity.py`
(the owner's contract: round-trips, equality, transition, league-safety,
determinism, unknown-slot honesty, property tests). Board parity:
`scripts/board_diff.py --expect-no-value-change` before/after consumer adaptation.

## 8. Out of scope, enforced

No valuation change (C1-PICK-01/-02/-03 untouched; the 2029 discount untouched; no
pick value moves — pinned by board parity). No trade-engine behavior change. No
player-identity reopening (`CANONICAL_V2` stays dark). No C1-U4/U6/U7/U8 work
beyond the interfaces named in §6. IDP Guru remains out of scope.
