# External-league FAAB comparability

**Owner module:** `src/trade/faab_comparability.py`
**Consumers:** `scripts/fetch_crowd_faab.py`, `src/trade/faab_history.py`, `server.py::/api/faab/recommend`
**Owner spec:** [`FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md`](FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md) §3, §5, §7, §10
**Model reference:** [`faab-model.md`](faab-model.md)

---

## 1. What this owns, and what it can never touch

One question, asked of an observation that came from **somebody else's league**:

> Is this league's waiver market comparable to ours, and what is its bid worth
> on our budget scale?

It owns neither of the numbers it helps compute. The **objective FAAB ceiling**
is decided by `src/trade/faab_engine.py` *before* any external observation is
read and is structurally unable to move — everything here feeds the **market
layer**, which prices how *contested* a claim will be. A hype cycle can say a
claim will be expensive. It can never say the player is worth more.

That separation is pinned by
`tests/trade/test_faab_crowd.py::TestTheInvariantSurvivesTheRewire`.

---

## 2. Budget normalization (spec §3)

```
normalizedBidShare      = bid / originalStartingBudget
equivalentOnBudget(B)   = normalizedBidShare * B
```

`normalized_bid_share()` returns **`None`** — never `0.0`, never an assumed $100
denominator — when the original budget is absent, unparseable or non-positive.
The budget is the *denominator*: fabricating one produces a percentage wrong by
up to 10×, not slightly off. This is the same rule `faab_history.fetch_bid_history`
already applies to our own league's $1,000 / $200 / $100 eras.

A **$0 bid is a real observation** and returns `0.0`. Uncontested claims are the
modal outcome; dropping them is what made the legacy analytics read a quiet wire
as a contested one.

The denominator is always the **original starting budget**, never a manager's
remaining balance.

---

## 3. Measured evidence (live KTC feed, 2026-08-18, 200 rows / 86 leagues)

Gated to `dynasty_main` — 12 teams, superflex, TEP, 2 TE starters, IDP:

| population | n | leagues | median bidPct | zero-bid share |
|---|---|---|---|---|
| the previous gate (superflex + TEP-as-bool + teams ±2) | 106 | 50 | 0.65% | 29% |
| …of which `rostersPerPlayer > 1` | **39** | 12 | **0.20%** | 41% |
| …of which total budget < $10 | 7 | 2 | 0.00% | **100%** |
| single-copy only | 67 | 38 | **1.00%** | 22% |

Vendor settings distribution across all 200 rows:

| key | values observed | previously read? |
|---|---|---|
| `qBs` | 1 (73), 2 (127) | yes → `superflex` |
| `tep` | 0 (73), 1 (74), 2 (12), 3 (41) | **flattened to a bool** |
| `is2TE` | false (154), true (46) | **no** |
| `rostersPerPlayer` | 1 (159), 2 (26), 3 (7), 4 (8) | **no** |
| `teams` | 10 (6), 12 (179), 13 (1), 14 (14) | yes |
| `totalBlindBidWaiverAmount` | $1 … $1,000 | yes (as denominator) |
| `leagueStartingLineup.position[].name` | QB, RB, WR, TE, PK, **Def** | **no** |
| `dynastyPlatformType` | 1 (all 200) | stored, never used |

After this change the same feed yields **66 comparable rows** for `dynasty_main`
(A=16, B=40, C=10), with the exclusion census
`superflex_mismatch=76, tep_mismatch=76, multi_copy_league=39, degenerate_budget=5`
(a row can fail several rules; every failing reason is reported).

---

## 4. Hard exclusions — fail closed (spec §5)

A league we cannot **prove** comparable is excluded. Unknown is never treated as
a match.

| reason | rule | why |
|---|---|---|
| `multi_copy_league` | `rostersPerPlayer > 1` | the same player may sit on several rosters at once, so the league has no waiver scarcity and its claims clear near nothing — 5× lower median, from 37% of the admitted sample |
| `roster_exclusivity_unknown` | `rostersPerPlayer` unstated | silence is not evidence of exclusivity |
| `degenerate_budget` | budget < `minOriginalBudget` ($10) | a league whose entire FAAB is a dollar cannot express a price, only "claimed / did not" |
| `budget_unknown` | budget missing or ≤ 0 | no denominator, no percentage |
| `superflex_mismatch` / `superflex_unknown` | `qBs ≥ 2` vs the target | the single biggest driver of QB waiver demand |
| `tep_mismatch` / `tep_unknown` | `tep > 0` vs the target | TE premium on/off |
| `team_count_mismatch` / `team_count_unknown` | outside ±`teamCountTolerance` | how many rivals split the same finite pool |

The gate is **symmetric about the target**: a 1QB target excludes superflex
evidence, not the other way round. Comparator relevance is derived from the
target league's own canonical settings (`TargetFormat.from_registry`), never
hardcoded to Brisket — spec §7's "future target leagues" requirement.

### The parse-failure guard

If a vendor key is renamed, *every* row fails closed and the run would report
"0 comparable" as though the market were quiet. `fetch_crowd_faab.py` therefore
**raises** when all rows are unclassifiable on superflex/TEP or when all rows
lack `rostersPerPlayer`. A universal parse failure is a failure, not an empty
market.

---

## 5. Tiers — reported, never weighted (spec §7)

Among the survivors, soft mismatches demote a tier and **change no number**:

| tier | meaning |
|---|---|
| A | no soft mismatch — same 2-TE setting, same TEP severity band, exact team count |
| B | one soft mismatch |
| C | two or more |
| `unverified` | a row persisted before the format evidence was captured (see §7) |

Soft mismatch reasons: `two_te_mismatch`, `two_te_unknown`, `tep_severity_gap`
(|Δ`tep`| ≥ 2, only measurable when the target's own level is known), and
`team_count_offset`.

**Why no weights.** The owner spec is explicit: *"Do not invent final numeric
weights merely from these labels. Validate them empirically against Brisket
historical clearing prices."* No outcome data exists to fit them yet, so a tier
is carried as metadata for that future validation and for the explanation
surface. `tests/trade/test_faab_crowd.py::test_a_tier_changes_no_number` pins
this.

---

## 6. Position comparability — the IDP gate (spec §7)

Across all 200 rows the starting-lineup slot names are exactly
`QB / RB / WR / TE / PK / Def`. **`Def` is a team D/ST**, and **zero** rows carry
a `DL` / `LB` / `DB` slot. So this population is offense-only, and spec §7 is
explicit that "offense-only leagues are invalid player-level FAAB comps for IDP
assets".

`crowd_evidence_for(market, name, position)` therefore **refuses** a DL/LB/DB
claim with `population_cannot_price_idp` rather than quoting a median drawn from
leagues that do not roster the position.

The gate is **derived from what the retained rows actually contain**, not
hardcoded: `market.prices_idp` is true as soon as one retained row comes from a
league with an individual-defender slot, so it self-corrects the day KTC carries
one.

---

## 7. Freshness, and the legacy-row policy (spec §10)

The ledger is **accumulated** — the feed is a ~5-day rolling window, so a single
fetch is a snapshot, not a history.

`build_crowd_market()` reports a `state`:

| state | meaning |
|---|---|
| `fresh` | updated inside `maxFileAgeDays` (7) — the only state that authorises pricing today's market |
| `stale` | exists, not refreshed inside the budget, **or has no `updatedAt` at all** — unmeasurable freshness is not freshness |
| `missing` | no ledger, or nothing survived classification |

Stale evidence is **retained and readable**; only its authority expires — the
same posture `league_registry.scoring_evidence_state` takes.

**Classification runs on read as well as at fetch.** The ledger outlives any
single fetch, so re-classifying means tightening the policy applies to rows
already stored instead of requiring the ledger to be thrown away and rebuilt
over months.

**Legacy rows** persisted before the format evidence was captured carry no
readable settings. They are retained and labelled `unverified` rather than
discarded: they are real observations collected under the older, broader gate,
and `CROWD_RETENTION_DAYS` (120) ages them out on its own. What they may not do
is pass as verified.

---

## 8. Dynasty provenance

Dynasty status of this feed is a **source-level claim** — the feed is published
at `keeptradecut.com/dynasty/waiver-database`. It is *not* verified per league:
`dynastyPlatformType` is `1` on every row measured and identifies the platform
(MyFantasyLeague), not the format.

Every retained row and the market payload carry
`DYNASTY_PROVENANCE_SOURCE_LEVEL`, so a consumer can see which kind of evidence
it holds rather than inferring dynasty from a URL fragment.

---

## 9. Response surface

`POST /api/faab/recommend` gains a `crowdMarket` block:

```json
{
  "state": "fresh",
  "asOf": "2026-08-18T…",
  "ageDays": 0.1,
  "rowsTotal": 412, "rowsUsed": 366,
  "tierCounts": {"A": 96, "B": 210, "C": 60},
  "excludedCounts": {"multi_copy_league": 39, "degenerate_budget": 5},
  "pricesIdp": false,
  "pricedPlayers": 214,
  "dynastyProvenance": "source_level_claim:ktc_dynasty_waiver_database",
  "refusalReason": null,
  "playerHasEvidence": true
}
```

`refusalReason` is one of `no_crowd_ledger`, `crowd_ledger_stale`,
`population_cannot_price_idp`, `crowd_lookup_failed`, or `null`. **"We have no
crowd price for this player" and "we refused to quote one" must not read the
same** — `playerHasEvidence` separates them.

No UI consumes this yet; that is the UI lane's call.

---

## 10. Known limitations — named, not papered over

1. **No IDP population exists.** External clearing-price evidence for defenders
   is unavailable, not zero. The gate reports the refusal; it does not
   substitute offense evidence.
2. **Tier weights are unvalidated.** Tiers change no number today. Validating
   them needs Brisket's own realized clearing prices joined to contemporaneous
   crowd observations — `scripts/faab_backtest.py` is the natural home.
3. **Dynasty is a source-level claim** (§8), not per-league verification.
4. **Legacy rows stay `unverified`** until the 120-day retention window clears
   them.
5. **TEP severity is carried but rarely actionable** — `TargetFormat.tep_level`
   is `None` for our leagues because our registry records TEP through the
   scoring-profile label rather than a KTC-style 0-3 level. The gap check is
   therefore dormant for Brisket and only fires for a target whose level is
   known. Recording the level anyway means the evidence is there when a
   scoring-derived level lands.
6. **Sample size per player stays small** (often 1-6 claims), which the
   `crowdBlendWeight` of 0.6 already accounts for; this change makes the sample
   *cleaner*, not larger.
7. **Sleeper most-added/dropped market heat is not implemented** — spec §4 says
   the exact production transform is evidence-gated and needs a backtest.

---

## 11. Verification

```bash
python -m pytest tests/trade/test_faab_comparability.py tests/trade/test_faab_crowd.py \
                 tests/trade/test_faab_config_parity.py -q
python scripts/fetch_crowd_faab.py --league dynasty_main --dry-run   # exclusion census
```

**Production checks (for the integration lane):** after the first real run on
prod, confirm rows in `data/faab/crowd_history_<leagueKey>.json` carry a
`comparability` block and a `rostersPerPlayer` setting, and that
`/api/faab/recommend` reports `crowdMarket.state: "fresh"`. If it reports
`stale`, the `dynasty-crowd-faab` timer has stopped — that is the condition this
change makes visible.
