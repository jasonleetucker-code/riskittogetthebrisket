# SHARED INTERFACE SPEC: N-team trade engine, private and public trade APIs (2026-10-20)

- **Status:** FINAL. This is the binding interface contract for Lanes A–E of the owner directive
  `docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md`. That directive includes a same-day
  FAIRNESS-ONLY AMENDMENT for the public product.
  - The spec was revised after two independent reviews: an engine/methodology review (R1–R16)
    and a privacy/contract review (P-items).
  - §11 records how each review item was handled.
- **Product authority:** none of its own.
  - This spec turns the directive, the amendment and the CLAUDE.md invariants into shared
    interfaces.
  - Where it applies a safe default to an open owner decision, it says so (§10).
  - Where the directive and this spec disagree, the directive wins.
- **Baseline:** `origin/main` @ `1511ca1d08`, #1861 head `f712338086`, #1866 head `cb60fc20a3`.
- **Inputs:** the directive, plus the coordinator reconciliation reports (engine state, UI state,
  fairness threshold, privacy). Their conclusions are carried into this spec. The working files
  themselves are not committed.
- **Agent-OS-Receipt:** `cdca1dca8385f70c0989302dece8d1bd4ce4843c`

## 0. Fixed constraints (apply to every lane)

1. **One owner per concept.** No lane writes a second routine for valuation, package
   adjustment, fairness, decisions, ownership, roster freshness or the contract generation.
   - The N-team engine is a per-team loop over the EXISTING `analyze_service.simulate_for_team` +
     `analyze_for_team`.
   - Public results are a reduction of that result. They are not a separate engine.
   - Gates live in their existing owner (`trade_decision`). They are never applied afterwards by
     a projection module.
2. **`geom_q078_v1` (q = 0.78) stays the active package model.**
   - No lane edits `src/valuation_math/package_model.py`, `config/trade/package_model.json`, q,
     LP_150 or any player value.
   - The N-team engine refuses to run unless the active model is geom and
     `package_model.config_state() == "ok"`. The KTC rollback model has no defined N-team meaning.
3. **No new weights, thresholds or formulas.**
   - `fairness_bands_v1` (`src/valuation_math/fairness_bands.py` +
     `config/trade/fairness_bands.json`) is used unchanged.
   - No lane edits band numbers, basis, version or status (§8).
4. **Missing is never zero.**
   - An unpriced, off-board or unverifiable asset makes the affected team UNABLE TO DETERMINE /
     NOT ENOUGH EVIDENCE.
   - It is never priced at 0 and never guessed.
5. **Stale is never current.** Ownership is proven only by `current` rosters, as defined by
   `src/api/roster_freshness.py` (§2.3).
6. **Recommendation ≠ execution.**
   - Nothing here mutates a league.
   - Each per-team decision keeps `recommendationOnly: true` and `executes: false`.
7. **Public/private semantic boundary.**
   - Public output carries no proprietary number, band level, gap, value order, decision
     category or Team Context inference.
   - This is enforced by positive assertions (§4.6), not by the models alone.
8. **Flags.**
   - The public flag `brisket_trade_advisor` stays **OFF**. No lane enables it or any production
     default.
   - The new private flag `trade_multi_team_analysis` ships **OFF** (§6).
9. **Process.**
   - No merges, deploys, release-candidate dispatches or production load tests by any lane.
   - Sparse worktrees only. The main checkout's branch is never changed.

---

## 1. Vocabulary and identities

| term | definition |
|---|---|
| **team** | A league franchise, identified by its Sleeper **`rosterId`** (int ≥ 1), read from `contract.sleeper.teams[]` (`roster_id` / `rosterId`). Display names are presentation only and never decide identity. |
| **asset ref** (`assetId`) | Player: `p:<sleeperId>` (alphanumeric, ≤ 16 chars). Pick: the canonical league pick id `pick:<leagueKey>:<season>:r<round>:o<originRosterId>` from `src/identity/picks.py` (`parse_league_pick_id`). No other form is accepted. Labels never identify an asset. |
| **leg** | `{assetId, from, to}`: one directed transfer. `from` is the team that holds the asset in the snapshot, verified. `to` is the destination team. |
| **ledger** | The set of legs for one proposed trade, plus the set of participating teams. |
| **snapshot** | ONE captured contract for the whole request, plus its `generation` stamp. It holds board values, `sleeper.teams`, `playerIds`, `pickDetails`, roster settings and roster freshness. It is never re-read mid-request (§2.2). |
| **generation** | `src/api/trade_analyze_runtime.contract_generation(contract)`: the ONE existing reader. No lane defines another. |
| **G_i / R_i** | Team i's gives (every leg with `from = i`, to any destination) and receives (every leg with `to = i`, from any sender). |
| **per-team adjusted totals** | `(send_adj_i, recv_adj_i, send_va_i, recv_va_i) = package_model.adjusted_pair_totals(values(G_i), values(R_i))`. The first argument is the gives. This is exactly what `analyze_trade.equity_verdict(G_i, R_i)` computes; the market lens reads it from there. See the rules below the table. |
| **per-team gap** | `gap_i = recv_adj_i − send_adj_i`, defined ONLY this way. `largerAdjustedSide_i = max(send_adj_i, recv_adj_i)`. The band is `fairness_bands.classify(gap_i, largerAdjustedSide_i)`. |

Rules for the per-team adjusted totals:

- Only priced positive values enter. The owner's `_positive_desc` filtering applies; unpriced
  assets never enter as 0.
- **Empty-side rule:** if either side is empty after filtering, there is no adjustment:
  `send_adj = ΣG`, `recv_adj = ΣR`, and both VA terms are 0.
- Otherwise the adjustment (an integer, `js_round`-ed inside the owner) goes to the side that
  discarded LESS depth.

What the gap equals:

- **Both sides non-empty under geom:** `gap_i` equals `U(R_i) − U(G_i)` only up to that
  rounding (|difference| ≤ 0.5). Tests assert the U-identity only for both-non-empty cases, with
  that tolerance.
- **One-sided team** (a gift giver or a receive-only team): `gap_i = ±raw sum`, not ±U. Example:
  G = [3000, 2000], R = [] gives `gap = −5000`, while `U_R − U_G = −4560`.

---

## 2. The N-team engine (Lane A, Python)

### 2.1 Modules and owners

| module | status | owns |
|---|---|---|
| `src/trade/trade_ledger.py` | **NEW** | Snapshot build and memo, asset-ref parsing, ledger validation, ownership verification and `team_flows`. Moved from #1861's `public_advisor.py`: the ownership parts of `build_snapshot`, `_parse_asset_id`, `validate_trade` and `generation_for`. **Roster freshness is NOT moved:** the ledger calls the existing `src/api/roster_freshness.roster_freshness` (the one reader of the scraper's `rosterSource` / `rosterFetchedAt` stamp), and #1861's private duplicate `roster_freshness` is deleted (directive §14 "reconcile roster-freshness with its canonical owner"). The public module keeps only presentation (asset lists, reduction, copy). |
| `src/trade/analyze_service.py` | **EXTEND** | `analyze_trade_n(...)`, the one N-team composer. Two additions:<br>1. `simulate_for_team` gains `include_roster_capacity: bool = True` and `unverifiable_asset_ids: Sequence[str] = ()`, both passed through to `simulate_trade`.<br>2. `analyze_for_team` gains `comparables: Any = _UNSET`, the exact object the 2-team route passes today.<br>The defaults are byte-identical to today. The module docstring changes from "2-team" to "every team-attributed analysis, any N". |
| `src/trade/team_verdicts.py` | **NEW** | Pure projections over existing outputs: `team_category(decision)`, `team_fairness(...)`, `fairness_overall(...)`, `all_team_summary(...)`, `conservation(...)`. It computes no value and applies no gate. |
| `src/trade/trade_decision.py` | **SMALL REFACTOR** (non-PUBLIC section only, Lane A) | Three changes:<br>1. Split the asset half of `_evidence_gaps` into a public pure function `asset_evidence_gaps(simulation, market) -> list[gap]` plus the constant `ASSET_EVIDENCE_GATE_CODES = ("no_priced_assets", "off_board_assets", "unpriced_assets", "unheld_assets", "pick_ownership_unknown", "ownership_unverifiable", "quarantined_values", "stale_values")`. `_evidence_gaps` calls it.<br>2. **NEW gate `ownership_unverifiable`** in that asset half (R1), read from `simulation["ownershipEvidence"]["unverifiableAssetIds"]`. It is absent on every existing route, so their behaviour is unchanged.<br>3. A1 moves the body of `public_category_from_decision` into `team_verdicts.team_category` and leaves a one-line alias. Lane C later deletes that alias and the whole PUBLIC section (§7). |
| `src/api/trade_simulator.py` | **EXTEND** | Two new keywords:<br>- `include_roster_capacity: bool = True`. When False, it skips `rosterCapacity`, `finalRosterSimulation`, roster utility and the per-team before-roster (`trade_utility`) cache.<br>- `unverifiable_asset_ids: Sequence[str] = ()`. When non-empty, the result carries `ownershipEvidence: {"unverifiableAssetIds": [...sorted, only ids in this team's legs]}`. When empty, the key is ABSENT, so the default output is byte-identical.<br>Valuation, ownership and asset resolution stay on the same code path.<br>A1 also: `competitive_posture_for` is split into its two halves, `league_posture_bundle` + `posture_block_for` (the posture memo reads the bundle once; a block stays byte-identical), and `team_impact.compute` refusing two starters with one identity (only conflicting ownership records produce it) degrades to `teamImpact: {unavailable}` instead of a 500. |
| `src/trade/roster_capacity.py` | **EXTEND** | Match outgoing players by player id when ids are supplied. Name matching is the fallback only (B0-b parity). Implemented as `outgoing_roster_names(context, names, ids)` over a new `CapacityContext.roster_player_ids` (the id of each roster entry, position for position); `simulate_trade` translates its outgoing players through it before capacity, the final legal roster and the utility. |

### 2.2 Data types and the one snapshot (`trade_ledger.py`)

```python
PLAYER_PREFIX = "p:"
LEDGER_VERSION = "trade_ledger_v1"

@dataclass(frozen=True)
class LedgerPolicy:
    min_teams: int = 2
    max_teams: int = 4            # from config; also capped at snapshot.team_count
    max_legs: int = 128
    participation: Literal["any_leg", "send_and_receive"] = "any_leg"

@dataclass(frozen=True)
class TradeSnapshot:
    contract: Mapping[str, Any]            # the ONE captured contract
    league_key: str
    generation: str                        # trade_analyze_runtime.contract_generation(contract)
    teams_by_roster_id: Mapping[int, Mapping[str, Any]]
    team_count: int
    player_owners: Mapping[str, tuple[int, ...]]   # sleeperId -> roster ids holding it
    known_player_ids: frozenset[str]               # league universe (rosters ∪ idToPlayer)
    pick_owner_index: Any                          # picks.league_pick_owner_index(...)
    pick_details_by_id: Mapping[str, Mapping[str, Any]]
    rows_by_player_id: Mapping[str, Mapping[str, Any]]
    roster_settings: Mapping[str, Any]
    rosters_state: Literal["current", "stale", "unknown"]   # roster_freshness.roster_freshness
    rosters_as_of: str | None

@dataclass(frozen=True)
class Leg:
    asset_id: str
    from_roster_id: int
    to_roster_id: int

@dataclass(frozen=True)
class ValidatedLedger:
    teams: tuple[int, ...]                 # ascending rosterId (canonical)
    legs: tuple[Leg, ...]                  # canonical order: sorted by asset_id
    unverifiable_asset_ids: tuple[str, ...]  # sorted
    generation: str

class LedgerError(Exception):
    status: int                 # 400 or 409
    error: str                  # "invalid_trade" | "stale_assets"
    reason: str                 # §2.3 code
    asset_ids: tuple[str, ...]  # sorted, request-supplied only, capped at max_legs
    roster_ids: tuple[int, ...] # sorted, request-supplied only

def build_trade_snapshot(contract, *, league_key) -> TradeSnapshot
def snapshot_for(contract, *, league_key, roster_settings=None, now=None) -> TradeSnapshot
    # memo keyed by (id(contract), generation, league, roster-freshness state now, settings), LRU 2
def validate_ledger(snap, *, teams, legs, policy) -> ValidatedLedger   # raises LedgerError
def team_flows(ledger, roster_id) -> TeamFlows   # player ids in/out, pick ids in/out, sorted
```

**One snapshot source for both products (R7).**

- The private route and the public route both obtain their snapshot through
  `trade_ledger.snapshot_for`.
- `roster_settings` is resolved inside `build_trade_snapshot` through `league_registry`, once.
- The private route passes the effective contract that `_prepare_trade_simulation` already
  produces, overlay splice included.
- The public route serves only when the loaded contract's `leagueKey` equals the public league,
  which is exactly the case where no splice applies. For the public league the two routes
  therefore read the same contract object and the same bytes.
- I11 builds both responses from ONE `TradeSnapshot` object.

### 2.3 Validation

Checks run in this order. The first failing check decides. That check lists every offending
request-supplied id, sorted and capped at `max_legs`.

| # | condition | status / error | reason |
|---|---|---|---|
| 1 | fewer than `min_teams` distinct teams | 400 `invalid_trade` | `too_few_teams` |
| 2 | a roster id listed twice | 400 `invalid_trade` | `duplicate_team` |
| 3 | more than `min(policy.max_teams, snap.team_count)` teams | 400 `invalid_trade` | `too_many_teams` |
| 4 | a roster id not in the snapshot league | 400 `invalid_trade` | `team_not_in_league` |
| 5 | no legs | 400 `invalid_trade` | `empty_trade` |
| 6 | more than `max_legs` legs (runs before any per-leg identity resolution, R9c) | 400 `invalid_trade` | `too_many_assets` |
| 7 | the id does not parse; a pick of another league; a player id outside `known_player_ids`; or a pick that no team in the league claims (`lookup_league_pick_owner` → absent): **nonexistent asset** | 400 `invalid_trade` | `unknown_asset` |
| 8 | the same asset id in more than one leg: **duplicate transfer** | 400 `invalid_trade` | `duplicate_asset` |
| 9 | `from` is not a participating team | 400 `invalid_trade` | `invalid_origin` |
| 10 | `to` is not a participating team: **invalid destination** | 400 `invalid_trade` | `invalid_destination` |
| 11 | `from == to` | 400 `invalid_trade` | `destination_is_origin` |
| 12 | a listed team with no leg at all: **non-participating team** | 400 `invalid_trade` | `idle_team` |
| 13 | policy `send_and_receive` only: a team that sends nothing or receives nothing | 400 `invalid_trade` | `one_sided_trade` |
| 14 | ownership mismatch, evaluated **only when `rosters_state == "current"`** (see the table below) | 409 `stale_assets` | `asset_not_owned` |

Precedence:

- Check 2 runs before check 3, so `[1,1,2,3,4,5]` reports `duplicate_team`, never
  `too_many_teams`. `[3,3,3,3,3]` has one distinct id, so check 1 reports `too_few_teams`
  (corrected in A1; the draft's example contradicted check 1).
- Check 1 counts distinct ids.

Check 14 when `rosters_state == "current"`:

| holders of a player in the snapshot | outcome |
|---|---|
| exactly 1, and it is `from` | ok |
| exactly 1, and it is not `from` | 409 |
| 0 | 409 |
| ≥ 2, including `from` | **unverifiable** (not an error) |
| ≥ 2, excluding `from` | 409 |

- **Pick, owned:** ok when the owner is `from`, otherwise 409.
- **Pick, absent:** already caught by check 7.
- **Pick, `unknown`** (an unpublished inventory, #1618, or conflicting claims): **unverifiable**.
- The 409 never reveals the actual owner's rosterId.

**Unverifiable assets (not errors).** These are recorded in `unverifiable_asset_ids`. Through the
`ownership_unverifiable` decision gate (§2.7) they make every team the asset touches UNABLE /
NOT_ENOUGH_EVIDENCE. They are:

- a player held by ≥ 2 rosters including `from`;
- a pick whose ownership is `unknown`;
- **every** asset when `rosters_state` is `stale` or `unknown` (R9b, R13). Check 14 is then
  skipped, because rosters that are not current prove ownership in neither direction.
  - `stale` and `unknown` mean exactly what `src/api/roster_freshness.py` says: restored
    (`last_good`) rosters, or live rosters older than `SCORING_SNAPSHOT_MAX_AGE_HOURS`; and no
    provable stamp.

Further rules:

- The verified owner cannot be overridden: no request field can assert ownership.
- A perspective team (when one is supplied) is checked by the API layer, not the ledger:
  400 `invalid_trade` / `perspective_not_in_trade` (private §3.1 and public §4.5).
- **Duplicate copies.** A team-attributed ledger refuses duplicates (check 8). The unattributed
  hypothetical calculator on `/trade` keeps allowing copies (owner decision 2026-10-03, #1619),
  but those sides are not eligible for authoritative analysis (§5). Both rules hold at once, and
  that is stated rather than silently changed.

### 2.4 Simultaneous application

For every team i:

- `pre_i` = i's roster in the snapshot;
- `post_i = pre_i − G_i + R_i`, built from the SAME snapshot.

Team i's roster changes only through its own legs. Evaluating every team independently from one
snapshot is therefore simultaneous application by construction. No leg is ever applied
sequentially, and nothing models a chain of 2-team trades.

Forced drops for team i:

- are chosen from `post_i` by the existing `roster_capacity` owner;
- are disjoint from `G_i`;
- are never legs;
- are excluded from conservation and from `gives` / `receives` (I16).

### 2.5 Evaluation API (`analyze_service.py`)

```python
MULTI_TEAM_VERSION = "multi_team_v1"
Mode = Literal["team_context", "asset_only", "market_fairness"]

def analyze_trade_n(
    snap: TradeSnapshot,
    ledger: ValidatedLedger,
    *,
    mode: Mode,
    counterfactuals: bool,
    team_goals: Mapping[int, str] | None = None,     # private only; normalize_goal
    posture_resolver: Callable[..., Mapping | None] | None = None,
    comparables_provider: Callable[[TeamFlows, dict], Any] | None = None,   # R8a: (flows, simulation)
    stage: StageHook | None = None,
) -> MultiTeamAnalysis   # {"teams": {rosterId: TeamAnalysis}, "summary": ..., "ledger": ...}
```

`analyze_trade_n` is **not** gated by `trade_multi_team_analysis`. That flag gates only the
private route and UI. The public product therefore works with the private flag off. Tests force
the private route on regardless of the production flag state (§6.1).

**Per team i,** in ascending `rosterId` order (the order affects only timing):

1. `flows = team_flows(ledger, i)`.
2. Resolve player labels from `snap.rows_by_player_id` and pick labels from
   `snap.pick_details_by_id`. Labels are display only; identity resolution uses the ids.
3. Call `simulate_for_team` with:
   - `snap.contract`, `league_key`, `snap.roster_settings` and `resolved_team=team_i`;
   - `players_in/out=labels`, `player_ids_in/out=ids`, `picks_in/out=labels`,
     `pick_ids_in/out=ids`;
   - `team_context=...`, `for_analysis=True`, `posture_resolver=...`;
   - `include_roster_capacity=...`;
   - `unverifiable_asset_ids=[ids in ledger.unverifiable_asset_ids ∩ (G_i ∪ R_i)]`.
4. Call `analyze_for_team(sim, contract=snap.contract, team_goal=team_goals.get(i),
   counterfactuals=..., comparables=...)`, where `comparables` is
   `comparables_provider(flows)` if a provider is given, else the analyze_service default.

| mode | `team_context` | `include_roster_capacity` | posture | comparables | used by |
|---|---|---|---|---|---|
| `team_context` | True | True | memoised (see below) | N = 2: provider (same call as the 2-team route); N ≥ 3: §2.11 | private default |
| `asset_only` | False | True | resolver called with `build_if_missing=False`, as today | as above | private Team Context toggle |
| `market_fairness` | False | **False** | **explicit no-op resolver** (see below) | none | public advisor only |

**Posture memo (R8c).** In `team_context` mode, posture is resolved once per request by ONE
memoised call to `gameplan.league_competitive_postures` with the same arguments
`competitive_posture_for(build_if_missing=True)` would pass. Each team's block is then looked up
from it. A test pins that each team's posture block is byte-identical to
`competitive_posture_for(..., build_if_missing=True)` for that team.

**Posture identity (R15).** The league bundle is keyed by `ownerId`. If team i's `ownerId` is
empty, or is not unique among the snapshot's teams (orphan or co-owned), team i's posture is
`{"available": False, "unavailableReason": "owner_identity_ambiguous"}`, never another team's
block. In `team_context` mode that yields `posture_unknown` → NOT_ENOUGH_EVIDENCE. A test with
two orphan teams pins it.

**`market_fairness` posture (R6).** `simulate_for_team` does
`resolver = posture_resolver or competitive_posture_for`, so passing `None` would still call the
real resolver. The engine therefore passes this explicit no-op callable:

```python
def _no_posture(contract, league_key, team, *, build_if_missing):
    return {"available": False, "unavailableReason": "not_requested_market_fairness"}
```

**`market_fairness` writes nothing shared or persistent (P1).** This mode must not:

- call `record_decision`;
- write `PROGRESS`;
- read or write the `trade_utility` before-roster cache;
- read or write the posture bundle cache;
- persist anything.

A test patches those writers and readers to raise and runs a full public analyze.

**No valuation code is added.** Each asset's canonical value is the one the simulation resolves:

- players: `rankDerivedValue`;
- picks: `pick_value_resolution` (identity-first, the generic grade for an unknown slot).

That value is identical in every team's view (I13).

### 2.6 Per-team result (`TeamAnalysis`, private shape)

```jsonc
{
  "rosterId": 7,
  "team": {"rosterId": 7, "name": "…"},
  "gives":    [{"assetId": "p:4046", "kind": "player", "label": "…", "toRosterId": 3,
                "value": 5123 /* or null */, "valueState": "priced|unpriced|off_board|not_held"}],
  "receives": [{"assetId": "…", "kind": "pick", "label": "…", "fromRosterId": 11,
                "value": 4747, "valueState": "priced"}],
  "simulation": { /* simulate_for_team output, unchanged: before/after roster, lineup,
                     replacement, bench, rosterCapacity, forced drops, draft capital,
                     teamContext stamp, ownershipEvidence when non-empty */ },
  "analysis":   { /* analyze_for_team output, unchanged: decision (YES/NO/NO_TOO_CLOSE/
                     NOT_ENOUGH_EVIDENCE), market lens, roster lens, feasibility, posture,
                     confidence, reasons, missingEvidence, whatWouldChange */ },
  "category": "FAVORABLE",
  "categoryText": "Favorable",
  "fairness": {
    "state": "FAIR | NOT_FAIR | UNABLE",
    "level": "fair | slight | unfair | lopsided | null",
    "reasonCode": "within_fairness_threshold | outside_fairness_threshold | asset_not_evaluable | ownership_unverifiable | evaluation_unavailable",
    "gap": 610, "largerAdjustedSide": 9610, "relativePct": 6.35,     // private only
    "bands": "fairness_bands_v1"
  },
  "unverifiableAssetIds": []
}
```

The `fairness` numbers in the example are team A of I14, computed with main's `package_model`:

| quantity | value |
|---|---|
| G | [6000, 3000] |
| R | [7000, 2500] |
| `send_adj` | 9000 |
| `recv_adj` | 9610 (R discarded less depth and receives the 110 VA) |
| gap | +610 |
| larger side | 9610 |
| relative gap | 6.35% |
| level | `slight` |

Fixtures must never use a raw-sum denominator.

`gives` / `receives` values are copied from the simulation's resolved assets and never
recomputed. An unpriced asset has `value: null`, never 0.

### 2.7 One authoritative decision and category per team

- **The ONE authoritative decision** for team i is `analysis.decision.headline`: `YES` / `NO` /
  `NO_TOO_CLOSE` / `NOT_ENOUGH_EVIDENCE`.
  - It comes from `trade_decision.decide` run on team i alone.
  - There is no trade-level YES/NO.
  - No module overrides it afterwards. `team_verdicts` is a projection only.
- **Ownership gate (R1).** `trade_decision.asset_evidence_gaps` raises `ownership_unverifiable`
  whenever team i's simulation carries `ownershipEvidence.unverifiableAssetIds`. It sits in the
  asset half, so:
  - the decision is NOT_ENOUGH_EVIDENCE;
  - or it is `NO` from the pre-existing execution gate, because `decide` runs the execution
    gate before the evidence gates;
  - it is never YES in either case.

  Fairness sees the same gap through `asset_evidence_gaps`. There is no second check in
  `team_verdicts`.
- **5-level category:** `team_verdicts.team_category(decision)`.
  - Its body is today's `trade_decision.public_category_from_decision`, moved in A1 (§2.1).
  - It is the same at every N, because `decide` reads no counterparty.
  - It is **private only.**

| `decision.headline` | condition (A = `components.objectiveValue`) | category | `categoryText` |
|---|---|---|---|
| `NOT_ENOUGH_EVIDENCE` | n/a | `UNAVAILABLE` | Unavailable — insufficient evidence |
| `YES` | A favors AND A magnitude `large` AND `leaning == "MAKE"` | `STRONGLY_FAVORABLE` | Strongly favorable |
| `YES` | otherwise | `FAVORABLE` | Favorable |
| `NO_TOO_CLOSE` | n/a | `APPROXIMATELY_EVEN` | Approximately even |
| `NO` | `deciding == "executionGate"` (roster cannot fit) | `UNFAVORABLE` (reason `roster_limit`) | Unfavorable — roster can't fit this trade |
| `NO` | A opposes AND A `large` AND `leaning == "PASS"` | `STRONGLY_UNFAVORABLE` | Strongly unfavorable |
| `NO` | otherwise | `UNFAVORABLE` | Unfavorable |
| anything malformed | n/a | `UNAVAILABLE` | (as above) |

Further rules:

- If Team Context cannot be verified (`posture_unknown`, `roster_unknown`,
  `roster_limit_unknown`, …), the result is `NOT_ENOUGH_EVIDENCE` → `UNAVAILABLE` with the named
  gaps. It never silently falls back to an asset-only verdict.
- `trade_decision.public_category_from_net_band` (the old "3-4-team net band" path) must not be
  used by anything. Lane C deletes it.

### 2.8 Per-team fairness (`team_verdicts.team_fairness`)

Fairness is a **market quantity** that is identical in every mode. It reuses exactly the band
owner and the per-team gap of §1:

```
gaps = trade_decision.asset_evidence_gaps(simulation_i, market_i)
if gaps: code = gaps[0].code
   no_priced_assets | off_board_assets | unpriced_assets          -> UNABLE, asset_not_evaluable
   unheld_assets | pick_ownership_unknown | ownership_unverifiable -> UNABLE, ownership_unverifiable
   quarantined_values | stale_values | anything else              -> UNABLE, evaluation_unavailable
if analysis.lenses.market.available is not True                -> UNABLE, asset_not_evaluable
band = analysis["lenses"]["market"]["detail"]["band"]
       # the equity lens (analyze_trade._market_lens -> equity_verdict) for (G_i, R_i)
       # = fairness_bands.classify(gap_i, max(send_adj_i, recv_adj_i)); read, never recomputed
FAIR      iff band.level == "fair"         (OD-F1 default (a), §8)
NOT_FAIR  otherwise
```

Notes:

- **Gross, not net.** In `team_context` mode, `decision.components.objectiveValue` nets out a
  forced-release cost. Fairness does not read it. It reads the gross market band, so private
  fairness equals public fairness for the same ledger and snapshot (I11).
- Roster capacity never affects fairness (safe default, §10, OD-R).
- A non-participating team would classify `fair` (larger side ≤ 0). That is why check 12
  rejects such a team before evaluation.
- A private gift of value < 250 classifies FAIR, because of the band's absolute floor. That is
  current band behaviour and is pinned by a test (I19). It is not a defect. Public gifts are
  refused by `send_and_receive`.

**Category / fairness consistency (R5).** Category (from the decision) and fairness (the gross
band) are different quantities. In `team_context` mode they are **not** equivalent:

- `_objective_value` classifies `net = gap − forcedReleaseCost`;
- `_rule` can return YES or NO from the roster benefit when A is neutral.

So FAIR can sit beside YES or NO, and STRONGLY_UNFAVORABLE can sit beside FAIR (a market-fair
trade made bad by a forced cut). These are the only normative implications. Each one is tested:

| # | implication | holds in |
|---|---|---|
| C1 | `category == STRONGLY_FAVORABLE` ⇒ `fairness.state == NOT_FAIR` (net ≤ gap on the same denominator, and a `large` favourable net needs a non-`fair` gross band) | every mode |
| C2 | no gate fired ⇒ (`headline == NO_TOO_CLOSE` ⇔ `fairness.state == FAIR`) | `asset_only` and `market_fairness` only |
| C3 | `fairness.state == UNABLE` ⇒ `headline ∈ {NOT_ENOUGH_EVIDENCE, NO with deciding == executionGate}` | every mode |
| C4 | the private UI labels the gross band "Market fairness" and the decision "Decision" as separate answers, so FAIR beside NO never reads as two competing verdicts | private UI (Lane B test) |

Nothing else may be assumed. In particular, public FAIR equals private `fairness.state == FAIR`
and nothing else (§8, SD-1).

### 2.9 Trade-level fairness and all-team summary

**Trade-level fairness** (`fairness_overall`) uses three-valued (Kleene) AND. By locality (I10)
a team's state depends only on its own legs, so one definite NOT_FAIR already proves "not every
team is fair" (R2). Rules apply in order:

| per-team states | overall | reasonCode |
|---|---|---|
| any `NOT_FAIR` | `NOT_FAIR` | `not_all_teams_fair` |
| else any `UNABLE` | `UNABLE` | `evidence_insufficient` |
| else (all `FAIR`) | `FAIR` | `all_teams_fair` |

At N = 2 both teams' states are always equal, UNABLE included (I5/I18), so the overall equals
each team's state.

**All-team summary** (`all_team_summary`) is a pure projection of the per-team results. It is
never a second verdict. Every per-team array is in **ascending `rosterId`** order (R16a):

```jsonc
"summary": {
  "teamCount": 3, "legCount": 5,
  "perTeam": [{"rosterId": 3, "teamName": "…", "headline": "YES", "category": "FAVORABLE",
               "fairness": "NOT_FAIR"}],
  "lines": ["Team A: Favorable.", "Team B: Approximately even.", "Team C: Unfavorable."],
  "fairnessOverall": {"state": "NOT_FAIR", "reasonCode": "not_all_teams_fair"},
  "conservation": {"assetsSent": 5, "assetsReceived": 5,
                   "pricedRawSent": 23500, "pricedRawReceived": 23500, "balanced": true},
  "nonConservedNote": "Adjusted package gaps and roster utility are per-team quantities and need not sum to zero."
}
```

There is no `overallRecommendation`, `winner` or trade-level headline field. A trade may favour
more than one team.

No response field, UI element or summary line may add per-team adjusted gaps, VA or utilities
into a trade-level number (R14a). Only RAW priced totals are conserved, and only those appear in
`conservation`.

### 2.10 Invariants (each one has a test, Lane A + Lane E)

Property tests use seeded `random.Random` generation plus exhaustive permutations for N ≤ 4. No
new test dependency is added (`hypothesis` is not in `requirements-dev.txt`).

| id | invariant |
|---|---|
| I1 | **Team-order independence:** permuting the request's `teams` leaves the whole private response byte-identical, apart from the echoed `perspectiveRosterId` and the timing / receipt ids. Teams are canonicalised to ascending `rosterId`. |
| I2 | **Asset-order independence:** permuting legs leaves per-team results byte-identical (legs are canonicalised by `asset_id`). |
| I3 | **Determinism:** the same snapshot, ledger and mode give byte-identical per-team results, excluding `analysisTiming` and receipt ids. |
| I4 | **2-team equivalence (R8b).** *Implemented: `tests/api/test_trade_analyze_multi_route.py`; the one listed difference is an orphan team (no `ownerId`): the route says `team_not_in_league_bundle`, the engine `owner_identity_ambiguous` (R15); both raise `posture_unknown`.* For N = 2, team X's `simulation` + `analysis` from `analyze_trade_n` are byte-equal to the **existing `/api/trade/analyze` route**, driven by the War Room's real request shape: `labels`, `playerIdsIn/Out`, `pickAssetIdsIn/Out`, request order. Comparables are injected through `comparables_provider` with the route's own call (`comparable_trades(side_a=receiving, side_b=sending)`), so `marketCorroboration` and decision coverage are covered. It is pinned on the War Room fixtures and on real archived trades. `/api/trade/analyze` itself stays byte-identical. Any allowed difference (canonical leg order; id-only identity resolution) must be listed in the test with a justification as a correctness fix. Comparing against the ledger's own `simulate_for_team` call does not satisfy I4. |
| I5 | **Perspective reversal at N = 2:** `gap_B == −gap_A`, the same `largerAdjustedSide`, the same fairness level and the same state. |
| I6 | **Conservation:** every leg appears exactly once in its sender's `gives` and once in its receiver's `receives`. Each team's net asset set reconciles with the ledger. A violation fails closed: 500 on the private route, 503 `advisor_unavailable` / `upstream_unavailable` on the public route (§4.5). It is never published. |
| I7 | **No phantom or duplicate assets:** no asset id appears in a result unless it is in the ledger; duplicates are refused (check 8). |
| I8 | **Verified owner is not overridable:** a leg whose `from` is not the snapshot owner is 409 when rosters are current, and unverifiable otherwise. |
| I9 | **Renaming invariance:** changing team display names or asset labels changes no verdict (identity is rosterId / assetId). |
| I10 | **Locality (simultaneity):** adding a leg between teams j and k (neither is i) leaves team i's result byte-identical. |
| I11 | **Public = reduction of private.** For the same `TradeSnapshot` object and ledger, the public per-team `result` equals the private `fairness.state`, and the public overall equals the private `fairnessOverall`. The public payload is invariant to every Team Context input: posture, projections, capacity, forced drops (privacy M1). It is compared against `fairness.state`, never against the headline. |
| I12 | **Python/JS parity of the pure math (R11):** for every case in `tests/fixtures/multi_team_trade_parity_cases.json` (value arrays per team), the JS `packageAdjustedPairTotals`, per-team gap and level equal the Python ones. Value resolution is a separate seam and is out of I12's scope (§5.1). |
| I13 | **One canonical value per asset:** an asset's value is the same in every team's view and equals its board value. It never changes because another team is involved. A future pick with an unknown slot resolves to the same generic-grade value for its sender and its receiver, through `pick_value_resolution`, and is not an evidence gap. A pick whose provenance is `unavailable` is unpriced, giving UNABLE (R14d). |
| I14 | **Directional correctness.** One-to-many case: A sends 6000→B and 3000→C; B sends 7000→A; C sends 2500→A. Results: A +610 `slight` (6.35% of 9610); B −1000 `unfair` (14.29%); C +500 `unfair` (16.67%). Verified against main's `package_model`. This pins the defect in the current JS meter. |
| I15 | **Raw conservation (R14a):** Σ_i (raw_recv_i − raw_send_i) = 0 over priced assets. When every team sends and receives exactly one asset, Σ_i gap_i = 0 exactly (no VA on a 1-for-1). |
| I16 | **Forced drops (R14b):** team i's forced drops come from `post_i`, are disjoint from `G_i`, are never legs, and are excluded from conservation and from `gives` / `receives`. |
| I17 | **Ownership gate (R1):** with an unverifiable asset in team i's legs (multi-holder player, `unknown` pick, or stale/unknown rosters), team i's headline is NOT_ENOUGH_EVIDENCE, or NO from the pre-existing execution gate. It is never YES, and fairness is UNABLE `ownership_unverifiable`. |
| I18 | **N = 2 symmetry of states (R14c):** both teams' fairness states are always equal, UNABLE included. |
| I19 | **Band floor (R14e):** a private gift of value < 250 classifies FAIR. This is pinned as current behaviour. |
| I20 | **Category/fairness consistency (R5):** C1–C3 of §2.8 hold over the property generator. |

### 2.11 Performance (Lane A implements, Lane E measures)

- One snapshot per request (`trade_ledger.snapshot_for`).
- One posture bundle per request, in `team_context` mode only.
- The before-roster cache is reused per team, in private modes only (§2.5: `market_fairness`
  never touches it).
- `market_fairness` skips capacity, final-roster and utility work.
- Single-flight (`trade_analyze_runtime.AsyncSingleFlight`):
  - private flights are keyed on (session owner, league, generation, sha256 of the canonical
    ledger, mode, goals);
  - public flights are keyed on (`market_fairness`, league, generation, sha256 of the canonical
    ledger);
  - `perspectiveRosterId` is never part of either key;
  - a public flight never joins a private flight.
- A `StageClock` with per-team stages (`team:<rid>:posture|simulation|decision`).
- Comparables (the non-voting `marketCorroboration` lens):
  - computed exactly as today at N = 2, injected via `comparables_provider`;
  - at N ≥ 3, stamped `{"state": "not_computed_multi_team"}` unless Lane E's measurement shows
    the per-team lookup fits the budget.
- Monte Carlo trade (`/api/trade/simulate-mc`) stays 2-sided and out of scope.
- Measure p50/p95/p99 for representative and worst-case valid 2/3/4-team requests, locally
  under memory/CPU limits, in every mode. Never against production.

---

## 3. Private API (Lane A route, Lane B consumer)

### 3.1 `POST /api/trade/analyze-multi` (new; `/api/trade/analyze` unchanged)

The route:

- is gated by `trade_multi_team_analysis` (§6);
- reuses `_prepare_trade_simulation`'s auth, league resolution, overlay splice and league-match
  rules: 503 when the loaded contract's `leagueKey` ≠ the request, and 503 `data_not_ready` when
  `sleeperDataReady` is false;
- obtains its snapshot through `trade_ledger.snapshot_for` (§2.2);
- uses the same session and guest rules as `/api/trade/analyze`.

**Request:**

```jsonc
{
  "leagueKey": "dynasty_main",              // optional; the normal resolver order applies
  "teams": [3, 7, 11],                      // rosterIds, 2..maxTeams
  "assets": [                               // legs
    {"id": "p:4046", "from": 3, "to": 7},
    {"id": "pick:dynasty_main:2027:r1:o7", "from": 7, "to": 11},
    {"id": "p:9509", "from": 11, "to": 3}
  ],
  "useTeamContext": true,                   // default true -> mode team_context, false -> asset_only
  "teamGoals": {"3": "WIN_NOW"},            // optional per-team override
  "counterfactuals": true,                  // default true (as on the 2-team route)
  "perspectiveRosterId": 3,                 // optional; must be in teams; echoed only
  "expectedGeneration": "…"                 // optional; drives snapshotChanged
}
```

**Response 200** (`Cache-Control: no-store`, `Server-Timing`):

```jsonc
{
  "multiTeamVersion": "multi_team_v1",
  "leagueKey": "dynasty_main",
  "valuationMode": "market",
  "generation": "…",
  "snapshotChanged": false,                 // null when expectedGeneration was not sent
  "rosters": {"state": "current|stale|unknown", "asOf": "2026-10-20"},
  "mode": "team_context",
  "perspectiveRosterId": 3,
  "teamCount": 3,
  "teams": [ /* TeamAnalysis (§2.6), ascending rosterId */ ],
  "summary": { /* §2.9 */ },
  "ledger": {"legs": [{"id": "…", "from": 3, "to": 7}], "unverifiableAssetIds": []},
  "packageModel": { /* package_model.receipt() */ },
  "fairnessBands": { /* fairness_bands.receipt() */ },
  "decisionRunIds": {"3": "…", "7": "…", "11": "…"},  // record_decision once per team
  "tradeRunId": "…",                                  // groups the per-team receipts
  "analysisTiming": { /* per stage; guests get the total only */ }
}
```

**Errors.** All errors use the private `{error, message, reason?, assetIds?, rosterIds?}` shape
and are `no-store`.

| status | `error` | when |
|---|---|---|
| 400 | `invalid_request` | the body is not a JSON object, or a field has the wrong type |
| 400 | `invalid_trade` + a §2.3 reason, or `perspective_not_in_trade` | ledger validation; the perspective team is not in `teams` |
| 400 | `unknown_league` / `inactive_league` | league resolver |
| 401 | (existing auth error) | not signed in |
| 409 | `stale_assets` (reason `asset_not_owned`) | ownership mismatch |
| 500 | `internal_error` | invariant violation (I6), fail closed |
| 503 | `data_not_ready` | no contract loaded, league mismatch, or `sleeperDataReady` false |
| 503 | `package_model_unavailable` | the active model is not geom with `config_state == "ok"` |
| 503 | `multi_team_analysis_disabled` | the flag is off |

### 3.2 Private UI obligations (Lane B)

- Every `/trade` side that takes part in authoritative analysis is bound to a distinct league
  `rosterId`. The binding is by id, never by display-name matching.
- Each asset carries its `assetId`. Destinations are explicit.
- Unbound sides, or a hypothetical copy, show the preliminary indicator only, with a named reason
  ("Assign each side to a league team to analyze").
- The 3+-team War Room calls `/api/trade/analyze-multi` and renders, per team, all verbatim from
  the response:
  - "Decision" (headline and category) and "Market fairness" (fairness state), as two
    separately labelled answers (C4);
  - reasons, roster before/after, capacity / forced drops and confidence;
  - a perspective switcher (client-side, over the one response);
  - the all-team `summary.lines`.
- The 2-team War Room keeps calling `/api/trade/analyze`. No 2-team regression.
- New multi-team UI goes in a lazy `dyn()` chunk.
  - `/trade/page` has 5.1 KB of budget headroom. Lane B must fit within it with **no budget
    raise**.
  - If the chunk split renames a `/trade` entry, Lane B may edit only the `/trade` entries of
    `check-bundle-sizes.mjs`, and must not raise them.

---

## 4. Public API: fairness-only (Lane C route, Lane D consumer)

Routes stay under `/api/public/league/trade-advisor/` (from #1861).

- The pydantic models are strict in both directions (`extra="forbid"`).
- The inbound `teams` `max_length` comes from the config ceiling, not a hardcoded 4.
- Every body passes `assert_public_payload_safe` AND `assert_advisor_payload_value_free` (§4.6).
- Every response is `no-store`.
- The `brisket_trade_advisor` flag stays OFF, and the launch gate (§6.3) must also pass.

### 4.1 `GET …/teams`

Unchanged from #1861, except:

- the `multiTeam` field is **removed**;
- `limits.maxTeams` = `min(public config maxTeams, league team count)`. The frontend reads the
  team cap from here, not from a hardcoded 4.

### 4.2 `GET …/teams/{rosterId}/assets`: value-free ordering (privacy M2)

- `value_desc` and `value_asc` are **removed**. The only order is `position_alpha`. Any other
  `sort` → 400 `invalid_request` / `unsupported_sort`.
- Order key:
  - players: side group (offense → defense → other), then position (QB, RB, WR, TE, K, DL, LB,
    DB, then any other), then `casefold(label)`, then `id`;
  - picks after players: `season`, `round`, `originRosterId`, `id`.
- A test asserts that the order is a pure function of (side, position, label, id) and is
  invariant to board values.
- Fields stay as #1861: `id`, `kind`, `label`, `side`, `position`, `nflTeam`, `evaluable`;
  picks also carry `season`, `round`, `originRosterId` and `projection`.
- **`evaluable` comes from the same resolver as the engine (P2).**
  - It is computed through `trade_ledger` id resolution plus the simulator's asset resolution:
    the path that feeds `asset_evidence_gaps`.
  - It is NOT computed through #1861's label-based `_engine_resolve`, which is deleted along
    with `_player_row_for`.
  - Test: `evaluable == true` exactly when a single-asset probe does not produce
    `asset_not_evaluable`.
  - **Accepted low-bandwidth residual:** a quarantined or stale value gives
    `evaluation_unavailable` despite `evaluable == true`, which reveals the quarantine state.
- `projection` stays `null` while `pickProjectionLabels` is false.
- The response's `sort` literal is `"position_alpha"`.

### 4.3 `POST …/analyze`

**Request** (strict):

```jsonc
{
  "perspectiveRosterId": 3,              // must be in teams; selects the default view only
  "teams": [3, 7, 11],                   // 2..limits.maxTeams
  "assets": [{"id": "p:4046", "from": 3, "to": 7}, …],
  "expectedGeneration": "…"              // optional
}
```

**Server path:**

1. Charge the limiter (before validation, as today), and record `started`.
2. Steps 3–6 run inside `try`. In the `finally`, every outcome after the limiter charge is held
   until the measured floor has elapsed (§6.3). That covers success, 400, 409, 413/415 and 503,
   including invariant and assertion failures. A response exceeding the floor is logged.
3. Build the snapshot (`trade_ledger.snapshot_for`).
4. `validate_ledger(policy=public)`, with `participation="send_and_receive"` (privacy M5).
5. `analyze_trade_n(mode="market_fairness", counterfactuals=False)`.
6. Reduce the result with `public_advisor.reduce_fairness(...)`.
   - Its signature accepts only, per team, `{rosterId, fairness.state, fairness.reasonCode,
     unavailable ids}`, plus `fairnessOverall` and the canonical ledger.
   - It never receives `analysis` or `simulation`, so nothing from the decision engine can be
     routed into the public body (P1a).

**Response 200:** value-free. All team results come in ONE response (privacy M6).

```jsonc
{
  "status": "success",
  "leagueKey": "dynasty_main",
  "generation": "…",
  "fairnessVersion": "fairness_bands_v1",
  "snapshotChanged": false,
  "rosters": {"state": "current", "asOf": "2026-10-20"},
  "teamCount": 3,
  "perspectiveRosterId": 3,
  "overall": {
    "result": "FAIR | NOT_FAIR | UNABLE_TO_DETERMINE",
    "label": "FAIR TRADE | NOT FAIR | UNABLE TO DETERMINE",
    "reasonCode": "all_teams_fair | not_all_teams_fair | evidence_insufficient",
    "reasonText": "…",                    // fixed copy, §4.4
    "note": "A trade with more than two teams is fair only when it is fair for every team." // N >= 3 only
  },
  "teams": [
    {"rosterId": 3, "result": "NOT_FAIR", "label": "NOT FAIR FOR THIS TEAM",
     "reasonCode": "outside_fairness_threshold", "reasonText": "…",
     "unavailableAssetIds": []}
  ],
  "trade": [{"id": "p:4046", "from": 3, "to": 7}]
}
```

**Reduction rules:**

- Per-team `result` comes from `fairness.state`: FAIR → `FAIR`, NOT_FAIR → `NOT_FAIR`,
  UNABLE → `UNABLE_TO_DETERMINE`. `overall` comes from `fairnessOverall` (Kleene AND, §2.9).
- **Labels (P2).**
  - `FAIR TRADE` / `NOT FAIR` / `UNABLE TO DETERMINE` are reserved for `overall.label`.
  - Per-team rows use `FAIR FOR THIS TEAM` / `NOT FAIR FOR THIS TEAM` / `UNABLE TO DETERMINE`.
    A team row reading "FAIR TRADE" beside an overall "NOT FAIR" would contradict itself. This
    copy needs owner confirmation (§10).
- `unavailableAssetIds` is non-empty only for `asset_not_evaluable` / `ownership_unverifiable`,
  and holds ledger ids touching that team.
- **Canonical order (P1):**
  - `teams[]` in ascending `rosterId`;
  - `trade[]` sorted by asset id;
  - `unavailableAssetIds` sorted.
- Permuting the request's teams or assets, or changing `perspectiveRosterId` within `teams`,
  gives a byte-identical body apart from the perspective echo. A test pins this.
- A team's gives and receives are derived client-side from `trade`.

**Numbers allowed in public payloads:** `rosterId`, `rosterIds[]`, `originRosterId`,
`teamCount`, `season`, `round`, `minTeams`, `maxTeams`, `maxLegs`, `retryAfterSeconds`,
`maxBytes`. Nothing else, and no floats anywhere.

**Never public:**

- values, gaps, VA, band level (`slight` / `unfair` / `lopsided`), percentages;
- the 5-level category, YES/NO, ACCEPT/DECLINE/APPROVE/DENY;
- `roster_limit`, posture, projections, the direction of an imbalance (privacy M4, default off,
  §10);
- receipts, run ids and timing.

### 4.4 Reason and copy allowlist

This is the only public text. It lives in ONE server table in `src/trade/public_advisor.py`
(Lane C). `trade_decision.py` carries no public concept once Lane C lands (§7). The outbound
models enumerate the table.

| code | scope | text |
|---|---|---|
| `within_fairness_threshold` | team | This trade is within our fairness threshold for this team. |
| `outside_fairness_threshold` | team | This trade falls outside our fairness threshold for this team. |
| `asset_not_evaluable` | team | One or more assets this team sends or receives can't be valued right now. |
| `ownership_unverifiable` | team | We couldn't confirm who owns every asset this team sends or receives. |
| `evaluation_unavailable` | team | This trade can't be evaluated reliably right now. |
| `all_teams_fair` | overall | The trade is within our fairness threshold for every team. |
| `not_all_teams_fair` | overall | The trade falls outside our fairness threshold for at least one team. |
| `evidence_insufficient` | overall | There isn't enough reliable information to judge this whole trade. |

| label | used for |
|---|---|
| `FAIR TRADE`, `NOT FAIR`, `UNABLE TO DETERMINE` | overall |
| `FAIR FOR THIS TEAM`, `NOT FAIR FOR THIS TEAM`, `UNABLE TO DETERMINE` | per team |

**Error copy** (fixed; it never echoes request content beyond §4.5's id rule):

- #1861's "Your team must be one of the teams in the trade." becomes "The selected team must be
  part of the trade."
- `one_sided_trade`: "Every team in the trade must both send and receive at least one asset."
- New fixed copy for `too_few_teams`, `too_many_teams`, `empty_trade`, `team_not_in_league`,
  `duplicate_team`, `invalid_origin` and `destination_is_origin`. These are added to
  `_ERROR_MESSAGES`, so every §4.5 reason has an entry.

**Copy rules:**

- No closeness or magnitude wording ("narrowly", "by a lot", "close").
- No advice wording.
- No personalization.

**Forbidden-word scan (P2; Lane D + Lane E test).**

- **Where it applies:** the server copy table; the advisor components; League Hub tab and
  section copy; landing, sitemap and meta descriptions; empty, loading and error states; the
  built public chunks.
- **Words** (case-insensitive, word-boundary): `accept`, `decline`, `approve`, `deny`,
  `reject`, `should`, `recommend`, `advice`, `favorable`, `unfavorable`, `win`, `lose`, `smash`,
  `fleece`, `your roster`, `your lineup`.
- **Out of scope:** the product name "Brisket Trade Advisor" (see §10).

### 4.5 Public error codes

These keep #1861's `{error, message, reason?, field?, assetIds?, rosterIds?, …}` shape and its
fixed copy.

**Echo bounds (P3):**

- Errors echo only request-supplied `assetIds` / `rosterIds` that passed the inbound pattern
  `^[A-Za-z0-9:_-]{1,64}$`.
- The echo is capped at `maxLegs`.
- A 409 `asset_not_owned` never reveals the actual current owner's rosterId.

| status | `error` | reasons |
|---|---|---|
| 400 | `invalid_request` | `invalid_json`, `schema`, `unsupported_sort`, `invalid_roster_id` |
| 400 | `invalid_trade` | `perspective_not_in_trade` plus every §2.3 400 reason (`too_few_teams`, `duplicate_team`, `too_many_teams`, `team_not_in_league`, `empty_trade`, `too_many_assets`, `unknown_asset`, `duplicate_asset`, `invalid_origin`, `invalid_destination`, `destination_is_origin`, `idle_team`, `one_sided_trade`) |
| 409 | `stale_assets` | `asset_not_owned` |
| 400 / 404 | `unknown_league`, `inactive_league`, `league_not_public`, `unknown_team` (GET path roster id) | n/a |
| 413 / 415 | `payload_too_large`, `unsupported_media_type` | n/a |
| 429 | `rate_limited` | n/a |
| 503 | `advisor_unavailable` | `disabled`; `not_ready` (launch gate, package model not geom, no contract); `upstream_unavailable` (engine error, invariant violation I6, a failed `_safe_dump` assertion) |

- A public route never returns 500 or a trace.
- The floor (§4.3 step 2) applies to every row of this table except those that occur before the
  limiter charge (flag off).
- The ledger's 400 reason is `team_not_in_league`. It is renamed from #1861's `unknown_team` so
  that it cannot be confused with the GET 404 `unknown_team` (R16c).

**Removed:** the `multi_team_unsupported` reason and the `roster_limit` public reason, together
with their copy.

**Build-then-refuse (P2, directive §8).**

- Lane D enforces on the client, with the same fixed copy as the server, keeping Analyze
  disabled until each passes:
  - participation (`send_and_receive`);
  - team count;
  - destination validity;
  - no self-destination;
  - `maxLegs`.
- A public refusal under the `send_and_receive` product rule, e.g. the directive §11
  "multiple teams to one team" shape where one sender receives nothing, is an **availability
  difference excluded from parity, not a different conclusion**. It stays pending OD-8 (§10).

### 4.6 Positive value-free enforcement (P1)

The value-free property must not rest on the pydantic models alone. Lane C adds, and Lane E
tests:

1. **Reducer isolation:** `reduce_fairness` cannot see `analysis` / `simulation` (§4.3 step 6).
2. **`assert_advisor_payload_value_free(body)`,** called in `_safe_dump` after
   `assert_public_payload_safe`. It checks:
   - every int leaf's key is in the §4.3 numeric allowlist;
   - there is no float anywhere;
   - every `label`, `reasonText`, `message` and `note` equals an entry in the fixed tables
     (§4.4).
3. **An advisor-scoped key blocklist,** applied by the same function, of the private
   `TeamAnalysis` / `MultiTeamAnalysis` names: `value`, `valueState`, `gap`,
   `largerAdjustedSide`, `relativePct`, `band`, `level`, `category`, `categoryText`, `headline`,
   `decision`, `simulation`, `analysis`, `fairness`, `packageModel`, `fairnessBands`,
   `decisionRunIds`, `tradeRunId`, `analysisTiming`.
   - `value` is **not** added to the global `_PRIVATE_FIELD_BLOCKLIST`, because that would break
     existing public payloads.
4. **A schema-introspection test** over every outbound advisor pydantic model. It fails on any
   numeric or free-text field outside the allowlist.
5. **Serialized page data (Lane E e2e).** The /league server-rendered RSC flight data,
   `__NEXT_DATA__`, the advisor-bootstrap output, and every advisor network response across
   all perspectives:
   - contain only allowlisted numeric keys;
   - contain no board or value arrays.
6. **Bundle boundary.** `check-public-bundle-privacy.mjs` (Lane D) forbids, in public chunks:
   - `lib/trade-logic`, `lib/fairness-bands`, `lib/dynasty-data`, `lib/league-analysis`,
     `lib/edge-helpers` and package-model code;
   - `lib/trade-war-room.js`;
   - any `/api/trade/` client path;
   - `frontend/__tests__/fixtures/trade-multi/*` (private numbers).

---

## 5. JavaScript: what the browser may compute

### 5.1 Private `/trade` (Lane B)

**Allowed: a PRELIMINARY per-team indicator only,** labelled "Preliminary — the final result
comes from Analyze". For each side i with explicit destinations:

```
given_i    = values of assets side i sends
received_i = values of assets routed to side i
{sendAdj, recvAdj, sendVA, recvVA} = packageAdjustedPairTotals(given_i, received_i)
gap_i      = recvAdj − sendAdj
level_i    = classifyGap(gap_i, max(sendAdj, recvAdj))         // lib/fairness-bands.js, unchanged
```

1. **`packageAdjustedPairTotals` (new, R10a)** is the JS twin of Python
   `package_model.adjusted_pair_totals`. It wraps the existing `packageAdjustPair`, which
   returns `{value, side, displayed}`, and follows the same rules:
   - positive filtering (non-positive and non-finite values dropped);
   - an empty side gets no adjustment;
   - `side === 1` → the FIRST argument gets the VA;
   - VA applies only when `displayed && value > 0`.

   The parity fixture pins empty-side, depth-tie and 1-for-1 cases.
2. **This replaces the defective "union of everyone else" collapse.**
   - `computeMultiSideAdjustments` (`trade-logic.js:750`) is **deleted**, not deprecated, once
     its callers move.
   - Its consumers get these per-team shapes (R10b):

     | function | N = 2 | N ≥ 3 |
     |---|---|---|
     | `multiAdjustedSideTotals(sides)` | unchanged (one adjusted total per side) | `[{sendAdj, recvAdj, sendVA, recvVA}]` per side |
     | `valueAdjustmentFromSideArrays(sides)` (Second Opinions, dual VA) | unchanged | the same per-team array; no single per-side number exists |

   - `tradeImbalance(sides)` (R10c):
     - N = 2: unchanged scalar.
     - N ≥ 3: `{perTeam: [{gap, larger, level}], worst: {index, level, relPct}}`. `worst` is the
       team with the worst band level (lopsided > unfair > slight > fair), ties broken by
       larger |gap| / larger, then lower side index. It is the only scalar.
   - `computeSideFlows` (R10e):
     - routed flows are **RAW only**: `received_i = Σ raw given routed to i`;
     - the adjusted per-team quantities `sendAdj_i` / `recvAdj_i` / `gap_i` are per-team
       perspective values and are never shown as routed flows.
     - The N = 2 identity `nets[1] === tradeGapAdjusted(A, B)` still holds and stays pinned.
   - `multiTeamNetSummary` uses the per-team rule.
   - The band base becomes `max(sendAdj_i, recvAdj_i)`, not the phantom-inflated `given`.
3. **`findBalancers` at N ≥ 3 is disabled (R10d)**, showing "Balancing suggestions aren't
   available for trades with 3 or more teams". Adding an asset from team b to team d changes
   only gap_b and gap_d, so an N ≥ 3 objective is a methodology choice that is not yet decided
   (§10, SD-13). N = 2 is unchanged.
4. N = 2 results are unchanged everywhere.
5. This is a **directive-§6 correctness fix** ("do not collapse … into two imaginary sides").
   - The PR carries before/after evidence on I14 plus the 3-team and 4-team circular cases.
   - It is not flag-gated: a flag would keep a known-wrong number live.
   - It is listed in §10 for owner visibility.
6. **CLAUDE.md (R12).** In the same PR as the `trade-logic.js` change, Lane B rewrites CLAUDE.md's
   "One representation, every side count" paragraph (in "Trade comparison — raw canonical value
   vs contextual Value Adjustment"). That paragraph currently describes the deleted collapse:
   "each side's premium is spread proportionally across the assets it SENDS …
   given_i = raw_i + adjustment_i". The rewrite states the per-team rule, raw-only routed flows,
   and the pinned N = 2 identity, so the runbook never describes deleted code.
7. An invalid, missing or self destination is a **visible state that disables Analyze**. There
   is no silent re-route. `defaultDestination` may still seed the initial selection visibly.
8. Non-finite inputs give an indeterminate indicator. JS `classifyGap(NaN)` returns `fair` while
   Python returns `lopsided`, so the guard goes in the caller and `fairness-bands.js` stays
   untouched.
9. **Parity (I12) covers the pure math over the same value arrays only.**
   - vitest reads `tests/fixtures/multi_team_trade_parity_cases.json`, the same file pytest
     reads, following the `trade_package_equity_parity_cases.json` pattern.
   - Value resolution is a separate, known-divergent seam: Python resolves picks by canonical
     id, while the JS label grammar is a deferred migration.
10. **When an authoritative response exists for the current ledger and generation:**
    - the server result is the decision on display;
    - the preliminary indicator takes its per-asset values from the response's
      `gives[].value` / `receives[].value`.

    A mismatch after that substitution is a real parity defect and is logged as one. The
    preliminary indicator never presents a competing verdict.

**Never computed in the browser:** YES/NO, category, final fairness state, roster effects,
capacity / forced drops, posture, confidence.

### 5.2 Public League Hub (Lane D)

- **No value computation of any kind.**
- The bundle boundary of §4.6 item 6 is enforced by `check-public-bundle-privacy.mjs`.
- The frontend renders only allowlisted server fields:
  - the result label and fixed text verbatim;
  - perspective switching over the one response's `teams[]`;
  - an all-team summary list from `teams[]` + `overall`.
- Asset search and position filters are client-side over the server's `position_alpha` list.
- Client-side preconditions (§4.5 build-then-refuse) keep Analyze disabled until the ledger is
  valid.
- No value-derived ordering is shown. Nothing is stored in browser storage beyond identity-only
  draft state.

---

## 6. Flags and configuration

### 6.1 Private gate (Lane A)

- `trade_multi_team_analysis` in `src/api/feature_flags.py`:
  - `_DEFAULTS`: **default `False`**;
  - `_GATE_STATUS`: `LIVE` (the gate is in `server.py`).
- Rollback: `RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS=0` **and restart**.
- What it gates:
  - `/api/trade/analyze-multi` and the private multi-team War Room UI;
  - **not** `analyze_trade_n` itself (§2.5).

  The UI reads the flag through the existing frontend flag path; Lane B confirms which.
- Off means current behaviour: the 2-team War Room, plus the 3+-team static panel and the
  (corrected) preliminary meter.
- It is turned on only through the normal release process, after Lane E's regressions and
  independent review pass.
- **CI:** the public/private parity test (launch criterion 3) runs in CI against the private
  route with the flag forced on in tests, whatever the production flag state.

### 6.2 Private config (Lane A): `config/trade/multi_team.json` (new)

```json
{"version": "multi_team_v1", "maxTeams": 4, "maxLegs": 128, "participation": "any_leg"}
```

- The engine also caps teams at the league's team count.
- Raising `maxTeams` above 4 needs validation evidence (the §11-directive matrix at N = 5) and
  is an owner-visible change. No code change is needed.
- An unreadable file fails closed: `maxTeams` 2 (the multi-team route refuses N ≥ 3) and an
  error is logged.

### 6.3 Public (Lane C)

- `brisket_trade_advisor` stays **default `False`**. No lane changes it.
  - It does not exist on main yet; it arrives with #1861.
  - If an earlier merge has already added it, Lane C makes no edit to `feature_flags.py`.
- `config/trade/public_advisor.json`:
  - **remove** `multiTeamRecommendations`;
  - keep `pickProjectionLabels: false`;
  - keep limits `{maxTeams: 4, maxLegs: 128, maxBodyBytes: 16384}`;
  - keep `responseFloorMs: null`;
  - keep the limiter priors;
  - **add** `"approvedFairnessVersion": null`;
  - **add** `"approvedSourcePermissionRecord": null`, the repo path of the owner's OD-3 record
    (P3).
- **Launch gate** (`advisor_unavailable` / `not_ready` while false), checked on every request.
  All of the following must hold:
  - the flag is on;
  - `responseFloorMs` is a measured positive int, or a measured per-`teamCount` table;
  - `approvedFairnessVersion == fairness_bands.receipt()["version"]`;
  - fairness-bands `status != "PROVISIONAL"`;
  - `approvedSourcePermissionRecord` names a VALID owner record (R2-10,
    `src/trade/public_advisor_permission.py`): a `.json` file under `docs/owner/` (no path or
    symlink escape) with the exact `recordType` / `schemaVersion` / `scope`, a named approver,
    `approvedAt <= today <= reviewBy` (past the owner-set `reviewBy` it is stale), and every
    source registered to vote covered as `approved` by its own entry or its recorded provider's
    (deny / unknown anywhere refuses; an uncovered or provider-unknown source refuses). Merely
    naming an existing file no longer opens this leg;
  - the package model is geom with config state `ok`.
- **Admission control (R2-5)**, both analyze routes (public and private
  `/api/trade/analyze-multi`), one owner `src/api/compute_admission.py` reading
  `config/trade/analyze_admission.json`: at most `maxConcurrent` engine computations per route
  (joined single-flight waiters take no slot; a full route refuses at once), and each caller
  waits at most `timeoutSeconds` (the computation is not abandoned and keeps its slot until it
  finishes; an identical retry joins it). Refusals are retryable 503s with `Retry-After`
  (public `advisor_unavailable` / `busy` | `timeout`, fixed copy, held to the floor; private
  `analysis_busy` / `analysis_timeout`). Defaults public 2 / 5 s, private 2 / 30 s — **PENDING
  OWNER CONFIRMATION** (§16 gate 7).

  This makes "public launch blocked on the owner's threshold and source-permission decisions"
  executable, and it catches a silent band version bump.
- **Response floor calibration (P1):**
  - measured in `market_fairness` mode, at p99 of the worst-case valid request: N = maxTeams,
    maxLegs, every asset priced, cold snapshot memo;
  - or as a per-`teamCount` table measured the same way.

  Measurement is local, never against production.
- Charging: 1 unit per analyze, before validation (as today). Bit-weighted charging of N-team
  queries (privacy M7) needs owner approval.
- Probe telemetry (privacy M10) is log-only. It stores a keyed hash or truncated prefix of the
  client IP, never the raw IP. Asset lists keyed to a client are not kept beyond the detection
  window, and retention is bounded.

### 6.4 Rollback independence

- The public flag off disables only the public tool.
- The private flag off reverts only private N-team analysis.
- Neither touches valuation, the package model or the 2-team routes.

---

## 7. Lane boundaries (file ownership)

Each lane edits only its files. Cross-lane needs go through the spec owner. Shared files list
the exact section a lane may touch.

| lane | branch / PR | owns |
|---|---|---|
| **A** canonical backend | `claude/trade-nteam-engine`. A0 = this spec + the coordinator records; A1 = engine; A2 = route + flag. | **Python modules:**<br>- `src/trade/trade_ledger.py` (new) and `src/trade/team_verdicts.py` (new);<br>- `src/trade/analyze_service.py`;<br>- `src/trade/trade_decision.py`: **only** the `asset_evidence_gaps` / `ASSET_EVIDENCE_GATE_CODES` split, the `ownership_unverifiable` gate, and moving the `public_category_from_decision` body into `team_verdicts.team_category`, leaving a one-line alias;<br>- `src/api/trade_simulator.py`: `include_roster_capacity`, `unverifiable_asset_ids`;<br>- `src/trade/roster_capacity.py`: id matching.<br>**Shared files:**<br>- `server.py`: **only** the new `/api/trade/analyze-multi` route and its helpers;<br>- `src/api/feature_flags.py`: **only** the `trade_multi_team_analysis` entries.<br>**Config:** `config/trade/multi_team.json`.<br>**Tests:** `tests/trade/test_trade_ledger.py`, `tests/trade/test_analyze_multi_team.py`, `tests/trade/test_team_verdicts.py`, `tests/api/test_trade_analyze_multi_route.py`, and `tests/trade/test_analyze_service.py` (AST guard: `analyze_trade_n` is the only other composer).<br>**Fixtures:** `tests/fixtures/multi_team_trade_parity_cases.json`, `tests/fixtures/multi_team/ledger_cases.json`, and `frontend/__tests__/fixtures/trade-multi/*.json` (private responses generated by the real engine on an archived board).<br>**Docs:** `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` (this spec, kept current) and one additive CLAUDE.md section ("Multi-team trade analysis — one owner"). |
| **B** private calculator + War Room | new `claude/trade-multi-team-ui` | **Code:**<br>- `frontend/lib/trade-logic.js`: per-team VA/flows, `packageAdjustedPairTotals`, delete the union collapse, N ≥ 3 balancers disabled;<br>- `frontend/lib/trade-war-room.js`: ledger request builder;<br>- `frontend/components/trade/TradeWarRoom.jsx` + new lazy `frontend/components/trade/MultiTeamWarRoom.jsx`;<br>- `frontend/app/trade/page.jsx`, `trade-sections.jsx`, `trade-layout.jsx`, `trade-asset-sheet.jsx`;<br>- `frontend/lib/second-opinions.js`: N ≥ 3 per-team path only;<br>- the `/trade` entries of `frontend/scripts/check-bundle-sizes.mjs`, renames only, no raise.<br>**Docs:** the CLAUDE.md "One representation, every side count" paragraph rewrite (§5.1 item 6, same PR as `trade-logic.js`).<br>**Tests:** their vitest files, and the parity test reading Lane A's fixture.<br>**Does not edit:** `fairness-bands.js` or the `package-model` JS constants. |
| **C** public backend (reconcile #1861) | `claude/advisor-public-backend` (#1861), rebased onto A1 | **Code:**<br>- `src/trade/public_advisor.py`: presentation, `reduce_fairness`, the copy table, `assert_advisor_payload_value_free`; consumes `trade_ledger` + `analyze_trade_n(mode="market_fairness")`; deletes `validate_trade`, `_engine_analyze`, `_engine_resolve`, `_player_row_for`, the private `roster_freshness`, the value sorts and `multi_team_unsupported`;<br>- `src/api/public_trade_advisor_api.py`: floor in `finally`, error copy, `teams` max from config;<br>- `src/api/client_ip.py`, `src/api/rate_limit.py`;<br>- `config/trade/public_advisor.json`;<br>- `src/trade/trade_decision.py`: deletes the `public_category_from_decision` alias and the **entire PUBLIC section** (`PUBLIC_*`, `public_*`, ACCEPT/DECLINE copy, `public_category_from_net_band`, `roster_limit` public copy). This is a pure deletion, done after A1 lands.<br>**Shared files:**<br>- `server.py`: **only** the advisor router mount and the `_client_ip_from_request` delegation;<br>- `src/api/feature_flags.py`: **only** `brisket_trade_advisor`, which stays False; no edit if it already exists.<br>**Docs:** `docs/owner/BRISKET_TRADE_ADVISOR_DESIGN_2026-10-19.md`: rewrite to fairness-only; drop B1 `multi_side.py`; record OD-1 resolved.<br>**Tests:** public tests `tests/api/test_public_trade_advisor_*.py`.<br>**Fixtures:** **producer** of the public contract fixtures `frontend/__tests__/fixtures/trade-advisor/*`. |
| **D-net** (owner-visible, deploy-affecting) | its own branch and PR, **not** part of #1861 | An env-overridable loopback bind in `server.py` (`HOST`); `next start -H 127.0.0.1` in `frontend/package.json`; the systemd template. |
| **D** League Hub frontend (reconcile #1866) | `claude/advisor-hub-frontend` (#1866), rebased onto main then onto Lane C's contract | **Code:**<br>- `frontend/app/league/**` advisor files: `tabs.js`, `LeagueClient.jsx`, `page.jsx`, `advisor-bootstrap.js`, `sections/trade-advisor*`, `sections/_advisor-*`, the CSS module;<br>- `frontend/lib/trade-advisor.js`, `frontend/lib/trade-advisor-client.js`;<br>- `frontend/app/api/public/league/trade-advisor/*`;<br>- `frontend/components/ds/Combobox*` + its `ds/index.js` export + its ds.css rules;<br>- `frontend/scripts/check-public-bundle-privacy.mjs` (extended per §4.6 item 6);<br>- the `/league` entries of `frontend/scripts/check-bundle-sizes.mjs`: **revert** #1866's /league 50→53 raise and keep main's raises;<br>- the landing, sitemap and back-link files #1866 touches.<br>**Tests:** the e2e spec `league-trade-advisor.spec.js` (waits for hydration) and the client-side preconditions.<br>**Fixtures:** **consumes** Lane C's fixtures byte-for-byte and never edits them.<br>**Does not edit:** `docs/WORK_CLAIMS.md`; the coordinator resolves that conflict. |
| **E** quality / privacy / verification | test-only branches | **Tests:**<br>- `tests/trade/test_multi_team_properties.py`: I1–I20 and adversarial ledgers;<br>- `tests/parity/test_multi_team_surface_parity.py`: the private route vs `analyze_trade_n` vs the public reduction vs the War Room 2-team, from one snapshot, with the private flag forced on;<br>- `tests/api/test_public_advisor_privacy_multi.py`: M1/M2/M3/M5/M6, Team Context invariance, the value-free payload scan across all perspectives, the no-writes test, canonical public ordering;<br>- forbidden-word scan;<br>- e2e/a11y/mobile specs and screenshots, including the serialized page-data scan.<br>**Scripts:** `scripts/measure_trade_analyze_multi.py` (local latency/memory, every mode; never production).<br>**Reports:** independent review reports.<br>**No production code.** Defects go back to the owning lane. |
| **Coordinator** | records commit on Lane A's branch (A0) | `docs/WORK_CLAIMS.md`, `docs/EXECUTION_PLAN.md`, `docs/OWNER_REQUESTED_TODO.md`, `docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md`, and the stale #1853 claim row. |

### 7.1 Sequencing and merge rules

1. **A0 + A1 first.**
   - A0: the spec and the records.
   - A1: the ledger, `analyze_trade_n`, `team_verdicts`, the simulator / capacity extensions,
     the `asset_evidence_gaps` split with the `ownership_unverifiable` gate, the
     `team_category` move with its alias, and the parity fixtures.
   - No route and no flag. Nothing is user-visible.
2. **In parallel against this spec, using fixtures:**
   - B builds against `frontend/__tests__/fixtures/trade-multi/*`;
   - C rebases #1861 onto A1;
   - D rebases #1866 onto main (only the `docs/WORK_CLAIMS.md` conflict is textual).
3. **A2:** the private route plus the flag (OFF). Then B integrates.
4. **Shared `server.py`.** It is edited by A2 (route), C (router mount, `client_ip`) and D-net
   (`HOST`). Each lane edits only its named hunk, and each later PR rebases onto the earlier
   one. D-net ships separately and is owner-visible.
5. **C and D merge in the same release train,** or D after C, never D alone. An incompatible
   frontend and backend are never merged.
6. Lane E's review and invariant suite is a gate before each merge. All merges, deploys and
   activation go through the normal authorized process, never by a lane.
7. If a contract in this spec has to change, the change lands here first (spec owner), and then
   the producer lane regenerates its fixtures. Consumers never hand-edit fixtures.

---

## 8. Threshold

- **Used unchanged:** `fairness_bands_v1` (`status: "PROVISIONAL"`, basis
  `adjusted_package_totals`). Its bands are:

  | level | condition |
  |---|---|
  | fair | \|gap\| < 250, or relative gap < 3.5% |
  | slight | relative gap < 9% |
  | unfair | relative gap < 18% |
  | lopsided | otherwise |

  - Private surfaces keep using it exactly as today.
  - Public FAIR is `level == "fair"` (OD-F1 default (a)). It equals the private
    `fairness.state == FAIR` and nothing else.
  - It equals `NO — TOO CLOSE` only in `asset_only` / `market_fairness` mode with no gate fired
    (C2). In `team_context` mode the decision reads a value net of the forced-release cost.
- **Research verdict** (`fairness_threshold` reconciliation report): **unsuitable as the fixed
  public threshold as it stands.**
  - The 250-point floor decides 97.5% of assets.
  - The depth-inflated denominator loosens the test by ×1.36 at 4 pieces and ×2.73 at 12.
  - Pick and IDP behaviour is floor-driven.
  - It conflicts with the trade-history "Fair trade" grade.
  - It is officially unvalidated.
- **Therefore the public launch is BLOCKED on the owner's methodology decision** (OD-F1 to
  OD-F6). The block is enforced by the §6.3 launch gate: `approvedFairnessVersion` is null and
  status is PROVISIONAL.
- No lane changes the bands. Any owner-approved change:
  - ships as one version bump in the one owner;
  - is re-measured on every consumer (`scripts/measure_fairness_band_change.py`);
  - moves the Python and JS mirrors together.
- The public response always carries `fairnessVersion`, so a version is never published
  silently.

---

## 9. Test matrix ownership (directive §11 → lane)

| directive case | where |
|---|---|
| 2-team; 3/4-team circular; one-to-many; many-to-one; multi-player sides; offense+IDP; players+picks; picks-only; deep and unequal packages; elite vs depth; low-value filler; two-way player; unresolved player value; future pick with unknown slot | A (`test_analyze_multi_team.py`, using real archived boards via `tests/archive_fixtures.newest_complete_raw_payload()` and the real 3-team own-league trades in `data/sleeper_last_good.json`) + E (properties) |
| exceeding roster limits | A (private: capacity / forced drops per team, I16) + E (public: invariance, I11) |
| stale ownership; duplicate transfer; invalid destination; non-participating team; one-sided / gift | A (`ledger_cases.json`; I17 for stale/unknown rosters) + C (public 400/409 copy) + D (client preconditions) |
| changed source data mid-session | A / C (`snapshotChanged`, 409 on ownership) + D (refresh UX) |
| parity: private calculator / War Room / shared backend / public | E (`test_multi_team_surface_parity.py`, one snapshot) + B (vitest I12, math only) |
| invariance: team, asset and rename order; no double transfer; owner not overridable; 2-team ≡ engine; ledger reconciliation; simultaneity | A + E (I1–I10, I13, I15–I20) |
| browser E2E, mobile, a11y, hydration, screenshots | B (private), D (public), E (independent run, serialized page-data scan) |
| performance / concurrency / response floor | E (local measurement, every mode) → C (`responseFloorMs` from the measured `market_fairness` worst-case p99, not invented) |

---

## 10. Owner decisions vs safe defaults applied in this spec

**Applied as safe defaults** (implement as specified; the owner may override):

| # | default applied | basis |
|---|---|---|
| SD-1 | Public FAIR = band `fair` only (OD-F1a), which equals private `fairness.state == FAIR` and nothing else | fewest new semantics; C1–C4 state exactly how it relates to the decision |
| SD-2 | Trade-level fairness is a Kleene AND: any NOT_FAIR → NOT FAIR; else any UNABLE → UNABLE; else FAIR | the amendment ("otherwise NOT FAIR, provided sufficient evidence exists"); locality makes one NOT_FAIR sufficient evidence |
| SD-3 | Roster capacity / forced drops never affect public fairness and are not mentioned publicly (OD-R) | amendment: market fairness, not personalized; privacy M1 |
| SD-4 | No imbalance direction in public output (privacy M4) | minimal disclosure; owner UX choice |
| SD-5 | Public participation `send_and_receive`; private `any_leg` (gifts allowed privately, matching today's 2-team route) | privacy M5; no 2-team regression; the client enforces it before Analyze (§4.5) |
| SD-6 | Team-attributed ledgers refuse duplicates; the hypothetical calculator keeps copies, preliminary only | #1619 preserved |
| SD-7 | Ownership is proven only by `current` rosters (`src/api/roster_freshness.py`). `stale` and `unknown` make every asset unverifiable → UNABLE / NOT_ENOUGH_EVIDENCE | stale ≠ current; the amendment defines UNABLE as insufficient ownership evidence. **Tradeoff:** while the scraper serves restored or >6 h rosters, both products answer UNABLE / NOT ENOUGH EVIDENCE. The owner may relax this, but not silently. |
| SD-8 | Public asset lists are not value-ordered | privacy M2; §9 minimise disclosure |
| SD-9 | The JS 3+-team meter is replaced by the per-team rule, ungated, with before/after evidence | directive §6 text; it is a correctness fix. Also answers OD-5: Python owns N-team, JS is a labelled preliminary mirror |
| SD-10 | #1861 design unit B1 (`multi_side.py`, a JS transcription) is dropped | it would make the defect canonical in two languages |
| SD-11 | The N-team route refuses unless the package model is geom / ok (all N); the 2-team routes are unaffected | the KTC model has no N-team semantics |
| SD-12 | Comparables omitted at N ≥ 3 unless measured to fit | non-voting lens; honest `not_computed_multi_team` |
| SD-13 | Private `findBalancers` is disabled at N ≥ 3, with a named message | its objective at N ≥ 3 is an undecided methodology choice (§5.1 item 3) |
| SD-14 | Per-team public labels `FAIR FOR THIS TEAM` / `NOT FAIR FOR THIS TEAM` / `UNABLE TO DETERMINE`; the amendment's three labels are reserved for the overall result | avoids a self-contradicting display |

**Owner-reserved (blocking public launch only; none blocks Lanes A–E implementation):**

- **OD-F1 to OD-F6** (threshold):
  - FAIR level;
  - denominator basis;
  - the 250 floor;
  - validation target;
  - published version and status;
  - reconciling the trade-history "Fair trade" grade.

  Also: whether the 2026-10-20 amendment overrides #1861 design rule D8 ("do not reopen fairness
  classifications").
- **OD-3a to OD-3d** (source permission for a public derived verdict):
  - Signals;
  - KTC;
  - IDP Trade Calculator;
  - all other voting sources, including the credentialed DLF / DraftSharks / IDP Show / Flock.

  Parity forbids a public-only source subset, so each answer is "confirm" or "do not launch".
  The answer is recorded at `approvedSourcePermissionRecord` (§6.3).
- **Residual acceptance:** a fixed deterministic threshold allows slow, visible reconstruction
  (about 30k queries).
- **OD-8 extension:**
  - confirm SD-5 (including the excluded-from-parity "multiple teams to one team" refusal), SD-8
    and the limiter priors;
  - optionally approve bit-weighted N-team charging (privacy M7).
- **Confirmation requested, not blocking:**
  - SD-3 (roster limits outside public fairness);
  - SD-7 (stale rosters fail closed);
  - SD-9 (the owner sees the before/after of the private 3+-team meter fix);
  - SD-13 (N ≥ 3 balancers);
  - SD-14 (per-team copy);
  - raising private `maxTeams` above 4;
  - whether the product name "Brisket Trade Advisor" stays under the fairness-only amendment
    ("Advisor" implies advice).
- **Ops (production box, not lanes):**
  - the privacy §3.2 network checks (:8000 / :3000 reachability, firewall, CDN, nginx drift);
  - deploy of unit D-net;
  - the on-box measurement of the production-only (Signals) value delta.

---

## 11. Review disposition

Two independent reviews of the draft were run against `origin/main` `1511ca1d08`. One covered
the engine and methodology, and ran I14 through main's `package_model`. The other covered privacy
and the API contract. Every item is **accepted**. None is rejected.

| item | change | where |
|---|---|---|
| R1 | `ownership_unverifiable` gate in `trade_decision.asset_evidence_gaps`; `ownershipEvidence` simulation field; I17 | §2.1, §2.5, §2.7, §2.10 |
| R2 | Kleene AND for overall fairness; SD-2 rewritten | §2.9, §10 |
| R3 | gap defined only as `recv_adj − send_adj`; empty-side rule; U-identity only when both sides are non-empty | §1 |
| R4 | I14 team A example corrected (9610 / 6.35%) | §2.6, §2.10 |
| R5 | false FAIR ≡ NO_TOO_CLOSE removed; consistency table C1–C4; I20 | §2.8, §8, §10 |
| R6 | explicit no-op posture resolver; `include_roster_capacity` on `simulate_for_team` | §2.1, §2.5 |
| R7 | one `snapshot_for` for both routes; one generation reader (`src/api/trade_analyze_runtime.contract_generation`) | §1, §2.2 |
| R8 | `comparables_provider`; I4 against the real route with the War Room request shape; posture memo pinned | §2.5, §2.10 |
| R9 | check 14 holder table; non-current rosters skip check 14; `max_legs` moved to check 6 | §2.3 |
| R10 | `packageAdjustedPairTotals`; per-team return shapes; `tradeImbalance` N ≥ 3 shape; balancers disabled at N ≥ 3; raw-only routed flows | §5.1, SD-13 |
| R11 | I12 scoped to pure math; the preliminary indicator adopts server per-asset values | §2.10, §5.1 |
| R12 | CLAUDE.md paragraph rewrite assigned to Lane B, in the same PR | §5.1, §7 |
| R13 | stale rosters fail closed (via the R1 gate); tradeoff surfaced | §0, §2.3, SD-7 |
| R14 | I15–I19 added; no trade-level sum of adjusted quantities | §2.9, §2.10 |
| R15 | `ownerId` empty or non-unique → posture unknown; test with two orphan teams | §2.5 |
| R16 | ascending-`rosterId` order; private `perspective_not_in_trade`; `team_not_in_league` rename; `duplicate_team` before `too_many_teams` | §2.3, §2.9, §3.1, §4.5 |
| P1 value-free | reducer isolation; `assert_advisor_payload_value_free`; advisor blocklist; schema introspection | §4.3, §4.6 |
| P1 floor | floor in `finally` on every post-charge outcome; calibrated from `market_fairness` worst-case p99 | §4.3, §6.3, §9 |
| P1 no writes | `market_fairness` writes nothing shared or persistent; patched-writer test; public single-flight isolation | §2.5, §2.11 |
| P1 ordering | canonical public order; perspective-invariant body; perspective excluded from flight keys | §4.3, §2.11 |
| P1 equivalence | FAIR = `fairness.state == FAIR` only; Decision vs Market fairness labelled separately | §2.8, §3.2, §8 |
| P2 labels | distinct per-team labels (SD-14) | §4.3, §4.4 |
| P2 wording | forbidden-word scan; #1861 copy fixed; new reason copy; config-driven `max_length` | §4, §4.4 |
| P2 build-then-refuse | client preconditions; availability difference excluded from parity, pending OD-8 | §4.5, §5.2 |
| P2 page data / bundle | serialized page-data e2e; bundle ban extended | §4.6 |
| P2 lane conflict | A1 moves the body and leaves an alias; C deletes the alias and the PUBLIC section; copy table only in `public_advisor.py` | §2.1, §4.4, §7 |
| P2 evaluable | same resolver as the engine; probe test; residual documented | §4.2 |
| P2 invariant mapping | public 503 `upstream_unavailable`, never 500 | §2.10 I6, §4.5 |
| P3 echo | echo bounds; owner never revealed | §2.2, §4.5 |
| P3 sequencing | D-net its own PR; B fits the `/trade` budget with no raise; no `feature_flags` edit if the flag exists | §3.2, §6.3, §7 |
| P3 OD-3 gate | `approvedSourcePermissionRecord` in the launch gate | §6.3 |
| P3 flag / telemetry | `analyze_trade_n` not flag-gated; parity in CI with the flag forced on; hashed IP and bounded retention | §2.5, §6.1, §6.3 |

---


## 12. Implementation notes (A1 + A2, branch `claude/trade-nteam-engine`)

Recorded where the implementation made a choice the text above left open.
None changes a contract a consumer reads, except where marked **contract**.

- **Generation.** `TradeSnapshot.generation` is `contract_generation(contract)`, or the
  literal `"unknown"` when the board carries no stamp.
- **`analyze_trade_n` return.** `{"multiTeamVersion", "mode", "teams": {rosterId:
  TeamAnalysis} (ascending insertion), "summary", "ledger"}`. The private body is assembled by
  `analyze_service.multi_team_payload(...)` — one assembly shared by the route and Lane B's
  fixtures; the route adds only the receipts, `tradeRunId`, timing and the valuation stamp.
- **`TeamAnalysis` (contract, additive).** `categoryReason` (`roster_limit` or `null`, from
  `team_verdicts.team_category_reason`); at N ≥ 3 in private modes `comparables:
  {"state": "not_computed_multi_team"}` (SD-12) — the lens itself then reads
  `not_computed`; `valueState` gains `not_held` for a sent asset the simulation reports in
  `ownedPickChecks.notOwnedBySender` (only reachable when rosters are not current).
- **Comparables provider.** `(flows, simulation)`: the 2-team route's call needs the
  simulation's resolved `receiving` / `sending`, so the provider takes it (I4 holds exactly).
- **Conservation (I6/I13).** `analyze_service._assert_conserved` checks every leg once in its
  sender's `gives` and once in its receiver's `receives`, nothing else, and one value per asset
  in every view that prices it; a violation raises `ConservationViolation` (route 500). The
  summary's raw sums run over assets priced in BOTH views.
- **Private route body errors.** `400 invalid_request` carries `field` (the first malformed
  field). Server-Timing metric names replace `:` with `_` (a token cannot contain `:`); the JSON
  `analysisTiming` keeps `team:<rid>:<stage>`.
- **Fixtures.** `tests/fixtures/multi_team/ledger_cases.json` (validation table),
  `tests/fixtures/multi_team_trade_parity_cases.json` (I12; JS half
  `frontend/__tests__/multi-team-package-parity.test.js`, composed from the existing
  `packageAdjustPair` + `classifyGap` exports until Lane B lands `packageAdjustedPairTotals`),
  `frontend/__tests__/fixtures/trade-multi/*.json` (real-engine private bodies; checked by
  contract SHAPE because the real board moves with every valuation change).
- **Real archived data.** The archive's recorded 3-team own-league trades have all moved on
  since, so they are replayed by STRUCTURE (routing kept, assets the giver holds today,
  `multi_team_support.structure_replays`); 2-team trades replay in reverse exactly
  (`reverse_replays`).

## Completion result (this spec unit)

- **STATUS:** DONE
- **ACCEPTANCE:** the spec covers, precisely:
  1. the N-team engine API: input, validation codes and order, simultaneous application, the
     per-team result, the decision/category mapping, the ownership gate, fairness and its
     consistency with the decision, the Kleene overall, the summary, and invariants I1–I20;
  2. the private API contract;
  3. the public fairness-only contract: the reasons and labels allowlist, perspective,
     canonical order, positive value-free enforcement, error codes and echo bounds, value-free
     asset ordering, and the floor on every outcome;
  4. the JS boundary, with per-team shapes;
  5. flags and launch gates;
  6. lane file ownership and sequencing;
  7. the threshold, with the public launch blocked on the owner decision;
  8. the disposition of both reviews.
- **EVIDENCE:**
  - the binding directive and amendment, and the four reconciliation reports;
  - both independent reviews;
  - live code read at `origin/main` `1511ca1d08`:
    - `package_model.adjust_pair` / `adjusted_pair_totals`;
    - `analyze_trade.equity_verdict`;
    - `analyze_service.simulate_for_team` (the posture resolver fallback);
    - `trade_decision._evidence_gaps` and the PUBLIC block;
    - `src/api/roster_freshness.py`;
    - `src/api/trade_analyze_runtime.contract_generation`;
    - `feature_flags.py`;
    - the `server.py` `/api/trade/analyze` route;
  - #1861 `public_advisor.py` / `public_trade_advisor_api.py`.
- **UNRESOLVED:**
  - the §10 owner-reserved decisions (they block public launch, not implementation);
  - the frontend flag-exposure path, which Lane B confirms against code;
  - the comparables cost at N ≥ 3 (SD-12, pending measurement).
- **NEXT_ACTION:** Lane A starts A1. Lanes B, C and D start against this spec and its fixtures.
  The coordinator sends the §10 owner-reserved questions in one message.
