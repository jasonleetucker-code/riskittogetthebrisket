# Pick class guard — evidence for the owner decision (2026-11-21)

**Status:** implemented behind the feature flag `pick_class_tether_guard`. The
flag is **OFF by default and owner-held**. With the flag OFF the board is
byte-identical to `main` (§3). Turning it on moves canonical pick values, so
it is the owner's decision. The deploy check `scripts/verify_owner_held_flags.py`
fails a production deploy whose effective flag is ON, and
`tests/api/test_pick_class_guard_hold_locked.py` is the lock.

## 1. The defect

`src/api/data_contract.py::_anchor_current_year_picks_to_rookies` (pipeline
step 13, "pick tethering") prices the slot picks of the active slot class from
the rookie pool. Pick `R.SS` takes the value of rookie number
`(R − 1) × 12 + SS` in the merged offense + IDP rookie list.

The active slot class is `current_rookie_draft_year()`: the lowest year that
still has `YYYY Pick R.SS` rows. Vendors publish next year's slots during the
season (IDP Trade Calculator published 48 `2027` slots, `published_slot`), so
from late September that year is **2027**. The pool, however, is every row with
`rookie == True`, and `rookie` means "zero NFL seasons today". In season those
players are the **2026** class, which was drafted in September.

So the board mapped one rookie class onto another:

* `2027 Pick 1.01` = 7121 (basis: Jeremiyah Love, a 2026 rookie);
* `2027 Pick 1.02` = 5584 (basis: Fernando Mendoza);
* and so on for all 72 slots.

C1-U6-D2 named this as a residual risk
(`docs/picks/C1_U6_D2_UNSLOTTED_DRAFT_CLASS.md` §5): "It would be caught by a
check that the pool's draft year equals the slot year. That needs the identity
owner's draft-year field." This unit is that check.

## 2. What changed (flag ON only)

| Concern | Owner used | Note |
|---|---|---|
| Which draft class a rookie belongs to | `src/draft/rookie_auction/class_snapshot.py::class_identity` | The existing class owner: "Class identity is decided here and nowhere else". An explicit `eligibleDraftYear` wins. Otherwise the class is `observed_nfl_season − yearsExp`. Otherwise the class is UNPROVABLE. Its docstring already names this exact trap: "in October [`rookie`] names the 2026 class, not the 2027 one (audit D5)". |
| Which NFL season the board's `yearsExp` describes | `src/bdvm/actuals.py::nfl_projection_season(boardDate)` | The repo's single resolver for "which NFL season is this date". It uses the board's own date claim (`raw_payload["date"]`), so it is deterministic per board. `src/waivers/drop_assessment.py` pairs it with `yearsExp` in the same way. If the date is unreadable, the season is unknown, every class is unprovable, and nothing is tethered. |

Behaviour with the flag ON:

1. **Tether.** A slot pick of year Y is tethered only to rookies whose class is
   proven to be Y. Rookies of other classes, and rookies whose class is
   unprovable, are left out of the pool and counted on the stamp.
2. **No same-class rookie.** The slot is NOT tethered. Each such slot is
   recorded with a reason:
   * `no_same_class_rookies` (the in-season case);
   * `same_class_pool_exhausted` (fewer class-Y rookies than slots);
   * `rookie_class_unprovable_observed_season_unknown`.
3. **Completion** (`_complete_future_pick_values`). A refused slot that a pick
   market priced keeps that market blend (`direct_market_blend`). No market
   prices rounds 5 and 6, so those slots are derived from the PREVIOUS slot in
   pick order using the approved `derivedRoundModel` round step, spread evenly
   over the round:
   * `factor = roundStep ** (1/12)`;
   * provenance `derived_round_step`, `appliedAs: "slot_continuation"`, with
     the basis named.

   As a result, a fully derived round ends exactly one round step below the
   previous round's last slot, and every later pick is worth less.

   A refused slot in rounds 1–4 that has NO slot market takes its **tier's**
   market blend. This happens when the only slot market is withheld, for
   example under the IDP Trade Calculator quarantine cutoff (owner 2026-10-07).
   * The tier values are captured before alias suppression clears them, and
     only while the flag is on.
   * The slot → tier map is `site_pick_map.slot_to_tier`.
   * This is the C1-U6-D2 `tier_of_unslotted_class` rule.
   * Provenance: `direct_market_blend`, `grade: "tier"`, the tier named as
     the basis. Its `pickEvidence` is the tier's.

   Without this fallback, all 72 slots went unpriced under the cutoff with the
   flag ON (measured by running `tests/api/test_idptc_cutoff_readiness.py`
   with the flag ON). With it, that module passes with the flag ON
   (23 passed, 1 skipped).

   The literal analogue of the tier rule (slot `5.s` from slot `4.s`) was
   measured and rejected. It priced `2027 Pick 5.01` (1598) above
   `2027 Pick 4.03..4.12`, which is the earlier-is-worth-less inversion class
   that F-1 fails the build for.
4. **Stamps.**
   * Every refused slot's `pickValueProvenance` carries
     `tetherWithheld: {reason, anchorYear}`.
   * A tethered slot's provenance carries `rookieClassYear` and
     `classIdentityOwner`.
   * `pickEvidence` follows the value basis (`market_blend` or `derived`, never
     `rookie_pool_tether` for an untethered slot).
   * The contract gains `pickClassTetherGuard` (the pool census, observed
     season, tethered / withheld / derived counts, and reasons).
5. **Census.** While `pickClassTetherGuard` is stamped,
   `validate_api_data_contract` extends the C1-PICK-01 census to the current
   year's slot rows. Every slot must be finite, greater than 0 and have
   provenance (a structural error otherwise). MISSING IS NEVER ZERO, and a
   previously tethered pick can never be left unpriced silently.

Flag OFF calls the incumbent pass with its incumbent arguments. It stamps
nothing and adds no contract key. `tests/api/test_pick_class_tether_guard.py`
checks this with a spy and with structural assertions.

## 3. Method

The boards were rebuilt offline with `build_api_data_contract` on the raw
payload. The script is
`docs/picks/evidence/pick_class_guard_2026-11-21/build_board.py`; the diffs come
from `diff_boards.py` and `doc_table.py` in the same directory.

* The clock is frozen at each board's scrape time and the temporal ledger is
  absent, so a mode built twice produces the same bytes.
* Three modes per board:
  * `head` — the pre-change `src/api/data_contract.py` from `110d1f54ce`,
    loaded as an overlay module;
  * `off` — this branch with the flag off;
  * `on` — this branch with the flag on.
* Three boards:

| Board | Inputs | Phase |
|---|---|---|
| `pinned` | `tests/fixtures/pinned_board` (2026-11-15, every input frozen) | in season, active slot class 2027 |
| `latest` | `exports/latest/dynasty_data_2026-11-21.json` and the tracked CSVs at `110d1f54ce` | in season, active slot class 2027 |
| `aug` | `exports/archive/dynasty_export_20260822_230108.zip` payload and today's tracked CSVs (mixed inputs, used only for the OFF vs ON comparison) | pre-draft, active slot class 2026 |

### 3a. Flag OFF is byte-identical to `main`

The sha256 is taken over the full contract, serialised with
`json.dumps(sort_keys=True)`.

| Board | `head` (pre-change code) | `off` (this branch) | Identical |
|---|---|---|---|
| pinned | `e37aa9e87e7ba7d657891e9c3e2b63819205453e6bec59e1e50dfd8eb8c25bf2` | same | yes |
| latest | `51d729849b7c238598fef9b589fda1c970aec4287cd59be39236e6d0dc24c97c` | same | yes |
| aug | `e1c7b83aa8532631e484de95b9a10c1f25dcc389ab7070ff58e470666886f161` | same | yes |

The ON contracts hash to `bd2e3fa4…` (pinned), `9ffc9ff5…` (latest) and
`0d4041bb…` (aug). They are expected to differ.

All six branch builds (OFF and ON) were repeated after the tier fallback (§2,
step 3) was added. Every hash came out the same. The fallback does not fire on
these boards because IDPTC prices every round-1–4 slot.

## 4. Flag ON — measured impact

### 4a. Summary

| | latest (2026-11-21) | pinned (2026-11-15) | aug (2026-08-22, pre-draft) |
|---|---|---|---|
| active slot class | 2027 | 2027 | 2026 |
| observed NFL season | 2026 | 2026 | 2026 |
| rookie pool considered / same class / other class | 158 / 0 / 158 (all class 2026) | 160 / 0 / 160 | 150 / 150 / 0 |
| unprovable rookies | 0 | 0 | 0 |
| slots tethered | 0 (OFF: 72) | 0 (OFF: 72) | 72 (OFF: 72) |
| pick rows whose value moved | **72** (every 2027 slot) | **72** | **0** (72 gain provenance stamps only) |
| non-pick rows whose value moved | 0 | 0 | 0 |
| rows whose rank or tier changed | 0 | 0 | 0 |
| top-50 / 100 / 200 membership change | none / none / none | none / none / none | none |
| max movement | `2027 Pick 1.02` 5584 → 8013 (+2429, +43.5%) | `2027 Pick 1.02` 5719 → 8013 (+2294, +40.1%) | — |
| moved up / down | 13 / 59 | 13 / 59 | — |
| sum of the 72 slot values | 202,581 → 184,868 (−8.7%) | 200,732 → 184,868 (−7.9%) | unchanged |
| contract validation | ok, no errors (OFF and ON) | ok, no errors (OFF and ON) | ok, no errors (OFF and ON) |
| ON: slots derived (rounds 5-6) / left unpriced | 24 / 0 | 24 / 0 | 0 / 0 |

Why no non-pick row moves: the compact pass (`compact_ranks_and_tiers`) already
gives current-year slot picks no rank slot, whether or not they are tethered.
Cross-market IDP translation reads the pick rows' vendor values, which the guard
does not touch, not their published values.

Pre-draft (aug), the guard is a no-op on value. Every rookie is the slot year's
class, so the same 72 rookies tether the same 72 slots. The only change is the
provenance class stamp.

### 4b. Per round (latest board)

| Round | OFF mean (range) | ON mean (range) | Δ mean |
|---|---|---|---|
| 1 | 4951 (7121–4129) | 5852 (8323–4409) | +18.2% |
| 2 | 3469 (4005–3126) | 3333 (3989–2749) | −3.9% |
| 3 | 2728 (3101–2268) | 2211 (2631–1766) | −18.9% |
| 4 | 2085 (2144–1946) | 1510 (1720–1352) | −27.6% |
| 5 | 1879 (1928–1817) | 1300 (1344–1256) | −30.8% |
| 6 | 1767 (1805–1712) | 1197 (1247–1150) | −32.2% |

### 4c. Market context the owner should weigh

Read this before deciding. With the flag ON, rounds 1–4 of the current year are
priced by **one provider**: IDP Trade Calculator's published 2027 slot board.

* KeepTradeCut publishes 2027 tiers, not slots. Its per-slot numbers on the raw
  `ktc` key are our own spread of its tiers (`derived_slot_from_tier`) and cast
  no vote.
* Every ON slot is therefore `pickEvidence.state: single_provider`, confidence
  "Low — single pick source". That is the same confidence these rows carry with
  the flag OFF, because the tether only restamps unassessed rows.
* IDPTC's own 1.01 (8013) and 1.02 (8323) are inverted. The board's slot-order
  pass (`_reassign_pick_slot_order`, unchanged) publishes them as 8323 / 8013.

Both markets' 2027 TIER prices are on the board as suppressed aliases:

| 2027 tier | KTC Crowd | KTC Trades | IDPTC tier | ON slots it spans (IDPTC slots) | OFF slots (tether) |
|---|---:|---:|---:|---|---|
| Early 1st | 6584 | 5436 | 7017 | 1.01–1.04: 8323–6486 | 7121–5098 |
| Mid 1st | 5482 | 4527 | 5737 | 1.05–1.08: 5961–5200 | 5067–4575 |
| Late 1st | 4909 | 4053 | 5105 | 1.09–1.12: 4908–4409 | 4411–4129 |
| Early 4th | 2015 | 1857 | 1980 | 4.01–4.04: 1720–1556 | 2144–2132 |
| Late 4th | 1737 | 1601 | 1731 | 4.09–4.12: 1428–1352 | 2064–1946 |

IDPTC's slot board is steeper than both markets' tier boards, including IDPTC's
own tiers:

* the top of round 1 (1.01 / 1.02 at 8323 / 8013) sits well above every Early
  1st tier price (5436–7017);
* every round-4 slot sits below every round-4 tier price.

For comparison, the next class (2028, priced from tiers by both markets) shows:

| Row | Value |
|---|---:|
| 2028 Early 1st | 5286 |
| 2028 Early 4th | 1836 |
| 2028 Round 5 | 1571 |

So with the flag ON, a 2028 fourth or fifth is worth more than the matching
2027 slot. Both markets price the 2027 fourth-round tiers ABOVE their 2028
ones (KTC Crowd Early 4th: 2015 vs 1800), so this is a cross-year inversion
relative to the vendors' own tiers.

The guard fixes the class error (no 2026 rookie prices a 2027 pick). It does not
make the 2027 slots a two-market price.

An alternative the owner may prefer, **not implemented here**: price a slotted
year whose rookies are not yet known at TIER grade from both markets. That is
the C1-U6-D2 treatment of an unslotted class (slot → its tier row). It would be
a separate methodology decision, because it would also suppress IDPTC's published
slots as the year's evidence.

### 4d. Every pick row that changes (latest board, 2026-11-21)

| Pick | OFF | ON | Δ | Δ% | OFF provenance (tethered rookie) | ON provenance | IDPTC slot (votes) | KTC slot, spread from tier (no vote) |
|---|---:|---:|---:|---:|---|---|---:|---:|
| 2027 Pick 1.01 | 7121 | 8323 | +1202 | +16.9% | rookie_pool_tether (Jeremiyah Love) | direct_market_blend | 8013 | 7901 |
| 2027 Pick 1.02 | 5584 | 8013 | +2429 | +43.5% | rookie_pool_tether (Fernando Mendoza) | direct_market_blend | 8323 | 7023 |
| 2027 Pick 1.03 | 5359 | 6647 | +1288 | +24.0% | rookie_pool_tether (Carnell Tate) | direct_market_blend | 6647 | 6145 |
| 2027 Pick 1.04 | 5098 | 6486 | +1388 | +27.2% | rookie_pool_tether (Arvell Reese) | direct_market_blend | 6486 | 5267 |
| 2027 Pick 1.05 | 5067 | 5961 | +894 | +17.6% | rookie_pool_tether (Sonny Styles) | direct_market_blend | 5961 | 6249 |
| 2027 Pick 1.06 | 4956 | 5575 | +619 | +12.5% | rookie_pool_tether (Jordyn Tyson) | direct_market_blend | 5575 | 5738 |
| 2027 Pick 1.07 | 4591 | 5312 | +721 | +15.7% | rookie_pool_tether (Jacob Rodriguez) | direct_market_blend | 5312 | 5226 |
| 2027 Pick 1.08 | 4575 | 5200 | +625 | +13.7% | rookie_pool_tether (Kenyon Sadiq) | direct_market_blend | 5200 | 4715 |
| 2027 Pick 1.09 | 4411 | 4908 | +497 | +11.3% | rookie_pool_tether (Jonah Coleman) | direct_market_blend | 4908 | 5498 |
| 2027 Pick 1.10 | 4391 | 4845 | +454 | +10.3% | rookie_pool_tether (KC Concepcion) | direct_market_blend | 4845 | 5105 |
| 2027 Pick 1.11 | 4139 | 4553 | +414 | +10.0% | rookie_pool_tether (Denzel Boston) | direct_market_blend | 4553 | 4713 |
| 2027 Pick 1.12 | 4129 | 4409 | +280 | +6.8% | rookie_pool_tether (Makai Lemon) | direct_market_blend | 4409 | 4320 |
| 2027 Pick 2.01 | 4005 | 3989 | -16 | -0.4% | rookie_pool_tether (Jadarian Price) | direct_market_blend | 3990 | 4838 |
| 2027 Pick 2.02 | 3886 | 3863 | -23 | -0.6% | rookie_pool_tether (David Bailey) | direct_market_blend | 3863 | 4301 |
| 2027 Pick 2.03 | 3865 | 3685 | -180 | -4.7% | rookie_pool_tether (Omar Cooper) | direct_market_blend | 3685 | 3763 |
| 2027 Pick 2.04 | 3624 | 3528 | -96 | -2.6% | rookie_pool_tether (Caleb Downs) | direct_market_blend | 3528 | 3226 |
| 2027 Pick 2.05 | 3401 | 3430 | +29 | +0.9% | rookie_pool_tether (Eli Stowers) | direct_market_blend | 3430 | 3988 |
| 2027 Pick 2.06 | 3367 | 3308 | -59 | -1.8% | rookie_pool_tether (Dillon Thieneman) | direct_market_blend | 3308 | 3661 |
| 2027 Pick 2.07 | 3315 | 3261 | -54 | -1.6% | rookie_pool_tether (Ty Simpson) | direct_market_blend | 3261 | 3335 |
| 2027 Pick 2.08 | 3314 | 3144 | -170 | -5.1% | rookie_pool_tether (Germie Bernard) | direct_market_blend | 3144 | 3008 |
| 2027 Pick 2.09 | 3277 | 3087 | -190 | -5.8% | rookie_pool_tether (Eli Raridon) | direct_market_blend | 3088 | 3618 |
| 2027 Pick 2.10 | 3269 | 3031 | -238 | -7.3% | rookie_pool_tether (Emmett Johnson) | direct_market_blend | 3031 | 3359 |
| 2027 Pick 2.11 | 3190 | 2925 | -265 | -8.3% | rookie_pool_tether (Caleb Douglas) | direct_market_blend | 2925 | 3101 |
| 2027 Pick 2.12 | 3126 | 2749 | -377 | -12.1% | rookie_pool_tether (Antonio Williams) | direct_market_blend | 2749 | 2842 |
| 2027 Pick 3.01 | 3101 | 2631 | -470 | -15.2% | rookie_pool_tether (De'Zhaun Stribling) | direct_market_blend | 2631 | 3228 |
| 2027 Pick 3.02 | 2995 | 2476 | -519 | -17.3% | rookie_pool_tether (Anthony Hill) | direct_market_blend | 2476 | 2869 |
| 2027 Pick 3.03 | 2985 | 2388 | -597 | -20.0% | rookie_pool_tether (CJ Allen) | direct_market_blend | 2388 | 2511 |
| 2027 Pick 3.04 | 2935 | 2350 | -585 | -19.9% | rookie_pool_tether (Josiah Trotter) | direct_market_blend | 2350 | 2152 |
| 2027 Pick 3.05 | 2831 | 2328 | -503 | -17.8% | rookie_pool_tether (Kaelon Black) | direct_market_blend | 2328 | 3050 |
| 2027 Pick 3.06 | 2794 | 2285 | -509 | -18.2% | rookie_pool_tether (Ja'Kobi Lane) | direct_market_blend | 2285 | 2800 |
| 2027 Pick 3.07 | 2777 | 2243 | -534 | -19.2% | rookie_pool_tether (Mike Washington) | direct_market_blend | 2243 | 2550 |
| 2027 Pick 3.08 | 2695 | 2140 | -555 | -20.6% | rookie_pool_tether (Chris Bell) | direct_market_blend | 2140 | 2300 |
| 2027 Pick 3.09 | 2542 | 2062 | -480 | -18.9% | rookie_pool_tether (Malachi Fields) | direct_market_blend | 2062 | 2855 |
| 2027 Pick 3.10 | 2443 | 1962 | -481 | -19.7% | rookie_pool_tether (Carson Beck) | direct_market_blend | 1962 | 2651 |
| 2027 Pick 3.11 | 2372 | 1912 | -460 | -19.4% | rookie_pool_tether (Max Klare) | direct_market_blend | 1912 | 2447 |
| 2027 Pick 3.12 | 2268 | 1766 | -502 | -22.1% | rookie_pool_tether (Oscar Delp) | direct_market_blend | 1766 | 2243 |
| 2027 Pick 4.01 | 2144 | 1720 | -424 | -19.8% | rookie_pool_tether (Ted Hurst) | direct_market_blend | 1720 | 2418 |
| 2027 Pick 4.02 | 2134 | 1637 | -497 | -23.3% | rookie_pool_tether (Kaleb Elarms-Orr) | direct_market_blend | 1637 | 2149 |
| 2027 Pick 4.03 | 2133 | 1587 | -546 | -25.6% | rookie_pool_tether (Seth McGowan) | direct_market_blend | 1587 | 1881 |
| 2027 Pick 4.04 | 2132 | 1556 | -576 | -27.0% | rookie_pool_tether (Keionte Scott) | direct_market_blend | 1556 | 1612 |
| 2027 Pick 4.05 | 2120 | 1543 | -577 | -27.2% | rookie_pool_tether (Nicholas Singleton) | direct_market_blend | 1544 | 2164 |
| 2027 Pick 4.06 | 2109 | 1524 | -585 | -27.7% | rookie_pool_tether (Matt Hibner) | direct_market_blend | 1524 | 1987 |
| 2027 Pick 4.07 | 2093 | 1502 | -591 | -28.2% | rookie_pool_tether (Rueben Bain) | direct_market_blend | 1502 | 1809 |
| 2027 Pick 4.08 | 2074 | 1478 | -596 | -28.7% | rookie_pool_tether (Emmanuel McNeil-Warren) | direct_market_blend | 1478 | 1632 |
| 2027 Pick 4.09 | 2064 | 1428 | -636 | -30.8% | rookie_pool_tether (Jake Golday) | direct_market_blend | 1428 | 1945 |
| 2027 Pick 4.10 | 2064 | 1412 | -652 | -31.6% | rookie_pool_tether (A.J. Haulcy) | direct_market_blend | 1412 | 1806 |
| 2027 Pick 4.11 | 2008 | 1381 | -627 | -31.2% | rookie_pool_tether (Treydan Stukes) | direct_market_blend | 1381 | 1668 |
| 2027 Pick 4.12 | 1946 | 1352 | -594 | -30.5% | rookie_pool_tether (Akheem Mesidor) | direct_market_blend | 1352 | 1529 |
| 2027 Pick 5.01 | 1928 | 1344 | -584 | -30.3% | rookie_pool_tether (Zachariah Branch) | derived_round_step from 2027 Pick 4.12 | – | – |
| 2027 Pick 5.02 | 1914 | 1336 | -578 | -30.2% | rookie_pool_tether (Kendal Daniels) | derived_round_step from 2027 Pick 5.01 | – | – |
| 2027 Pick 5.03 | 1914 | 1328 | -586 | -30.6% | rookie_pool_tether (Justin Joly) | derived_round_step from 2027 Pick 5.02 | – | – |
| 2027 Pick 5.04 | 1896 | 1320 | -576 | -30.4% | rookie_pool_tether (Jaishawn Barham) | derived_round_step from 2027 Pick 5.03 | – | – |
| 2027 Pick 5.05 | 1889 | 1312 | -577 | -30.5% | rookie_pool_tether (Malachi Lawrence) | derived_round_step from 2027 Pick 5.04 | – | – |
| 2027 Pick 5.06 | 1889 | 1304 | -585 | -31.0% | rookie_pool_tether (Nate Boerkircher) | derived_round_step from 2027 Pick 5.05 | – | – |
| 2027 Pick 5.07 | 1885 | 1296 | -589 | -31.2% | rookie_pool_tether (Derrick Moore) | derived_round_step from 2027 Pick 5.06 | – | – |
| 2027 Pick 5.08 | 1870 | 1288 | -582 | -31.1% | rookie_pool_tether (Marlin Klein) | derived_round_step from 2027 Pick 5.07 | – | – |
| 2027 Pick 5.09 | 1863 | 1280 | -583 | -31.3% | rookie_pool_tether (Cashius Howell) | derived_round_step from 2027 Pick 5.08 | – | – |
| 2027 Pick 5.10 | 1863 | 1272 | -591 | -31.7% | rookie_pool_tether (Cyrus Allen) | derived_round_step from 2027 Pick 5.09 | – | – |
| 2027 Pick 5.11 | 1829 | 1264 | -565 | -30.9% | rookie_pool_tether (Drew Allar) | derived_round_step from 2027 Pick 5.10 | – | – |
| 2027 Pick 5.12 | 1817 | 1256 | -561 | -30.9% | rookie_pool_tether (Keldric Faulk) | derived_round_step from 2027 Pick 5.11 | – | – |
| 2027 Pick 6.01 | 1805 | 1247 | -558 | -30.9% | rookie_pool_tether (Sam Roush) | derived_round_step from 2027 Pick 5.12 | – | – |
| 2027 Pick 6.02 | 1805 | 1238 | -567 | -31.4% | rookie_pool_tether (Josh Cuevas) | derived_round_step from 2027 Pick 6.01 | – | – |
| 2027 Pick 6.03 | 1797 | 1229 | -568 | -31.6% | rookie_pool_tether (Kyle Louis) | derived_round_step from 2027 Pick 6.02 | – | – |
| 2027 Pick 6.04 | 1787 | 1220 | -567 | -31.7% | rookie_pool_tether (Jack Endries) | derived_round_step from 2027 Pick 6.03 | – | – |
| 2027 Pick 6.05 | 1786 | 1211 | -575 | -32.2% | rookie_pool_tether (Michael Trigg) | derived_round_step from 2027 Pick 6.04 | – | – |
| 2027 Pick 6.06 | 1782 | 1202 | -580 | -32.5% | rookie_pool_tether (RJ Maryland) | derived_round_step from 2027 Pick 6.05 | – | – |
| 2027 Pick 6.07 | 1753 | 1193 | -560 | -31.9% | rookie_pool_tether (Jalon Daniels) | derived_round_step from 2027 Pick 6.06 | – | – |
| 2027 Pick 6.08 | 1750 | 1184 | -566 | -32.3% | rookie_pool_tether (Chris Brazzell) | derived_round_step from 2027 Pick 6.07 | – | – |
| 2027 Pick 6.09 | 1745 | 1175 | -570 | -32.7% | rookie_pool_tether (Joe Royer) | derived_round_step from 2027 Pick 6.08 | – | – |
| 2027 Pick 6.10 | 1744 | 1166 | -578 | -33.1% | rookie_pool_tether (Mansoor Delane) | derived_round_step from 2027 Pick 6.09 | – | – |
| 2027 Pick 6.11 | 1739 | 1158 | -581 | -33.4% | rookie_pool_tether (John Michael Gyllenborg) | derived_round_step from 2027 Pick 6.10 | – | – |
| 2027 Pick 6.12 | 1712 | 1150 | -562 | -32.8% | rookie_pool_tether (Skyler Bell) | derived_round_step from 2027 Pick 6.11 | – | – |

On the pinned board (2026-11-15) the ON values are identical to the table
above: the IDPTC slot board did not change between the two dates. The OFF values
differ slightly because the 2026 rookie ladder moved. The max movement there is
`2027 Pick 1.02` 5719 → 8013 (+40.1%).

## 5. Residual risks (named, not fixed here)

* **February–April.** `nfl_projection_season` turns to the new year on
  February 1. If Sleeper still reports the just-finished class at
  `years_exp == 0` until the NFL draft, those rookies read as the NEW class
  during that window. They would be tethered to the new year's slots, which is
  exactly today's behaviour, so it is no worse than OFF. No tracked archive
  predates 2026-07-14, so Sleeper's roll timing could not be measured. The
  repo already tolerates ±1 here (`drop_assessment.py`). A Sleeper
  `/state/nfl` season captured into the payload would close it.
* **Unprovable rookies leave the pool when the flag is ON.**
  * Who: rookies with no `yearsExp` and no `eligibleDraftYear` — for example
    must-have prospects not yet in Sleeper's player database.
  * Effect: they shift the tether ladder for the slots after them.
  * Measured: 0 on all three boards.
  * Visibility: counted per reason on `pickClassTetherGuard.rookiePool`.
* **An unpriced round-1–4 slot fails the build while the flag is ON.** If a
  market stops publishing one slot of rounds 1–4, there is no approved slot
  derivation for those rounds. The census then reports a structural error
  rather than inventing a number.
* **The board keeps the 2027 tier rows suppressed** as aliases of the slots.
  That is unchanged from OFF; see §4c for the alternative.
* **ON reopens audit W05-F006 in season** (single-vendor slot picks).
  `tests/api/test_audit_cw40_batch_m1_regression.py::test_w05_f006_slot_picks_are_no_longer_anchored_on_one_vendor`
  pins "every slot is `rookie_pool_tether`", and the tether is what had closed
  W05-F006. With the flag ON the 2027 slots are priced by IDPTC alone.
* **Tests that encode the in-season tether.** Running the pick, tether and
  rookie tests (`tests/api` + `tests/picks`, `-k "pick or tether or rookie"`)
  with the flag ON produced 7 failures out of 508. Each one asserts the
  incumbent tether or the OFF default:
  * `test_audit_cw40_batch_m1_regression::test_w05_f006_…`;
  * `test_confidence_naming::…::test_tethered_rows_report_the_tether_as_their_basis`;
  * `test_confidence_naming_red::…::test_the_measured_population_now_reports_its_tether`;
  * `test_pick_rookie_anchor::TestAnchorEndToEnd` ×2 (`livedata`);
  * `test_pick_class_tether_guard::test_the_flag_is_registered_default_off`;
  * `test_idptc_cutoff_readiness::test_1_…` — fixed by the tier fallback above.

  On activation, the remaining tests need an owner-approved update in the same
  change. They are not defects of the guard; they are the tether's own pins.

## 6. Rollback / activation

* **Activation is owner-reserved:**
  * flip `_DEFAULTS["pick_class_tether_guard"]` in `src/api/feature_flags.py`;
  * change the lock (`tests/api/test_pick_class_guard_hold_locked.py`);
  * change the deploy check entry in `scripts/verify_owner_held_flags.py`.

  Changing any of these IS the activation decision.
* **Rollback once on:** set `RISKIT_FEATURE_PICK_CLASS_TETHER_GUARD=0` and
  restart. Flag reads are cached per process.
