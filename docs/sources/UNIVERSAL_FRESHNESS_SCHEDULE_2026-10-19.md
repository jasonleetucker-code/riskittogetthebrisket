# Universal source freshness schedule and per-source voting status

**Owner directive 2026-10-19, "Universal Source Voting and Freshness Policy"**,
sections 2 (freshness schedule), 5 (26-source audit), 7 (no hidden weighting),
8 (source status) and 9 (board validation, freshness part). This record
covers the FRESHNESS lane only. Vote holds, provider families and the DLF IDP
restoration (§1, §3, §4) belong to PR #1817. The outlier filter (§6) belongs
to the outlier lane.

Evidence: `docs/sources/evidence/UNIVERSAL_FRESHNESS_2026-10-19/`. Board:
`exports/latest/dynasty_data_2026-10-19.json`, as of `2026-10-19T05:23:48Z`,
built from `origin/main` `b08f7230d1` data.

## 1. The schedule

| Whole days since the last genuine update | Voting power (multiplies the base weight) |
|---|---|
| 0–7 | 100% |
| 8–14 | 75% |
| 15–21 | 50% |
| 22–30 | 25% |
| more than 30 | 0% (not voting) |

* `effective = base x freshness x health x coverage`. Base weights are
  unchanged (1.0 for every registered source).
* **Day boundary.** `days = floor((boardAsOf - clock) / 24 h)`, measured
  between two UTC instants. It does not depend on time zones or calendar
  dates. A source updated 7 days 23 hours ago is in day 7 (100%). At exactly
  8 x 24 hours it is in day 8 (75%). A clock later than the board's own time
  counts as day 0. Boundary tests pin each edge exactly and one second before
  it: 7/8, 14/15, 21/22 and 30/31 days
  (`tests/sources/test_freshness_schedule_v2.py`).
* `boardAsOf` is the board's own scrape time (`scrapeTimestamp`), never the
  wall clock, so a board rebuilds identically.
* The numbers are in `config/sources/freshness_schedule_v2.json`. The loader
  refuses a malformed schedule: empty, non-ascending days, or rising
  freshness.
* **Flag:** `source_freshness_schedule_v2`, default **ON**. Rollback:
  `RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2=0` and restart. That restores
  the v1 cadence curve byte for byte (§7 below). The existing
  `source_freshness_weighting` flag still decides whether any freshness
  factor is applied at all.

## 2. The clock: the publisher's genuine update, never our download

The owner is `src/sources/freshness.py`. Content-change observation is owned
by `src/sources/dataset_state.py` and was not changed: it already met the
directive.

1. **A publisher-stated update time, where the source provides one.** A
   fetcher records the vendor's own time in `data/scrape_state/<key>_upstream.json`.
   `scripts/record_source_datasets.py` folds it into the dataset state as
   `upstream.publishedAt`. Under the schedule, that time is the clock for
   **every** source that records one, not only sources declared
   `EXPLICIT_UPSTREAM_TIMESTAMP` in the v1 config. Today that means:
   * The IDP Show (Datawrapper `lastModifiedAt`)
   * FantasyPros IDP (the page's `last_updated_ts`)
   * the Signals boards (the page's published time)

   The vendor time is never used when it is later than the last content
   change we observed: a cosmetic vendor edit moves the vendor's timestamp,
   not the data, so the clock is the earlier of the two. A vendor time in
   the future is ignored. The whole board then shares that one clock.
   * This is the same rule PR #1817's D5 uses for FantasyPros IDP
     (`min(vendor time, last broad change)`), so the two are compatible.
   * On `main` today, `fantasyProsIdp` is not declared EXPLICIT. The
     schedule still uses its recorded vendor time (2026-09-04). Once #1817
     merges, its config line only matters for the v1 rollback path.
2. **Otherwise, a recorded observation of an actual content change.**
   `dataset_state.observe` hashes every row's identity and value/rank. Rows
   are compared for content only: no markup, timestamps or ADP. The clock is
   `lastBroadDatasetChangeAt`, set when a change touches at least 5 rows and
   at least 2% of the board.
   * For BATCH, INCREMENTAL and UNKNOWN publication styles, a row whose own
     content changed more recently than the board ages from its own change.
     A vendor's 2-row revision refreshes exactly those 2 rows, as in v1.
   * On a board that prices offense and IDP together, each row's clock is
     capped at its own universe's clock (`source_universe_freshness`,
     unchanged).
3. **A successful re-download of unchanged content moves no clock.** An
   identical fingerprint is a no-op in `observe`. A FAILED or DEGRADED fetch
   moves no clock either. Pinned by
   `test_unchanged_redownload_never_resets_the_clock` (twenty daily
   unchanged re-downloads leave a 20-day-old board at 50%). We never
   fabricate a date: the clock is a vendor statement or an observed change.
4. **An update time we cannot establish for a source we are tracking is
   never fresh.** If the only clock is the first-observation baseline, the
   source votes at **0** (`unknownUpdateTimeFreshness`) with
   `clockBasis: "unknown"`.
   * The baseline is the fetch time the dataset state stamps when we first
     see a board. The content was published at some unknown time at or
     before it.
   * Its status is *Data Issue — Not Voting*, or *Stale* when even the
     lower-bound age is past 30 days.

   *Justification:* the directive forbids treating unknown as fresh. Using
   the fetch time would let a download reset the clock, and so would a
   lower-bound age, because a fresh fetch makes the lower bound 0 days.
   * The cost is small and self-correcting. A newly tracked source does not
     vote until its first observed publication. For a daily source that is
     about one refresh; for a weekly source, about a week.
   * On today's board **no registered source is in this state**. Every
     dataset state has a real content change after its baseline, or a
     vendor time.

   **A measurement gap is a different thing, and it is not zeroed.** Two
   cases have no freshness measurement at all:
   * the board predates every observation we hold for the source (a
     historical replay from before its tracking began);
   * the source has no recorded dataset state.

   Both keep the long-standing unmeasured posture, exactly as under v1: base
   weight, state `UNMEASURED`, `clockBasis: "not_tracked_at_board_time"`.
   That matches a board built with no dataset-state directory, which keeps
   base weights, stamped `sourceWeighting.unavailableReason`, validator
   `degraded`.
   * Zeroing these would read a gap in our own records as evidence about the
     source. It would also retroactively strip every source from every
     replay older than its tracking: KTC Crowd and Trades before 2026-09-09,
     for example.
   * CI found exactly that on the first push. The synthetic golden-dataset
     board (dated 2026-07-29) lost its KTC-only "Lonely Rookie" vote.
   * On a live board neither case applies to any tracked source. The status
     payload names the case ("freshness is not measured for this board")
     wherever it does.
5. **Scope.**
   * The schedule applies to every registered dynasty ranking source,
     offense, IDP and rookie. Each subset is on its own clock: player
     boards, and also the pick boards of KTC and the IDP Trade Calculator.
     A pick board older than 30 days stops voting on picks while the same
     vendor's fresh player board keeps voting.
   * The KTC Market benchmark (`ktcCrowdTradesSfTep`) is exempt
     (`exemptKeys`). It never votes, and its freshness only qualifies the
     market comparison, so it stays on v1.
   * The confidence gate's content-freshness floor is unchanged at 0.5
     (`freshForConfidence`). Votes at 100%, 75% and 50% count as fresh
     evidence; a vote at 25% does not.
6. **Rookie boards between draft classes.** These are declared through the
   existing seasonal owner (`src/sources/seasonal_policy.py`,
   `config/sources/seasonal_policy_v1.json`). A seasonally inactive board is
   removed from the active set, so it is never judged stale, and it shows as
   *Seasonal — Not Voting*.
   * Today that is `flockFantasySfRookies`: the 2026 class graduated and the
     board has been empty since 2026-10-01.
   * The first valid non-empty board reactivates it. A new class is a broad
     content change, so it votes at 100% at once.
   * A rookie board with no seasonal declaration that stops changing for 30
     days is stale. We fail closed rather than invent a window. Declaring a
     board is the route to seasonal status.

The state names keep the v1 vocabulary, so every existing reader works
unchanged. The v1 bands map the steps exactly:

| v2 freshness | state |
|---|---|
| 1.0 | ON_SCHEDULE |
| 0.75 | OVERDUE |
| 0.5 | STALE |
| 0.25 | SEVERELY_STALE |
| 0 | QUARANTINED |
| unknown (tracked, baseline only; votes at 0) | UNMEASURED |
| not tracked at the board's time (unmeasured; base weight) | UNMEASURED |

Each subset also carries additive fields: `freshnessSchedule`, `clockBasis`,
`lastGenuineUpdateAt`, `daysSinceGenuineUpdate`, `freshnessPct` and
`rowLevelClock`. These are absent under v1.

The report scripts compute weightings outside a board build:
`scripts/source_weighting_report.py`, `scripts/source_inventory.py`,
`scripts/check_source_health.py` and `scripts/source_census.py`. They now
call `freshness.active_schedule()`, so they cannot disagree with the board.
Callers that pin a rule keep passing their own. Those are the training-run
receipts (`src/model_registry/training_run.py`) and the robust-filter shadow
harness.

## 3. Per-source voting status (§8)

`src/sources/voting_status.py` builds one entry per registered source, in
registry order. It is stamped on the contract as `sourceVotingStatus` and
served additively as `votingStatus` on `GET /api/sources/weighting`.

* **Access.** That endpoint is auth-gated, like the Settings and Source
  Health pages that will render it. `/api/rankings/sources` is public and
  serves only the static registry, so nothing was added there.
* **Content.** The payload carries source metadata, dates, factors and row
  counts only. It never carries a player name or value, which is pinned by
  test.
* **Decides nothing.** Freshness comes from the `SourceWeighting` objects the
  blend applied. Holds, seasonal state and private-source state are read
  from the contract's `privateSourceAvailability` and `sourceSeasonalState`
  stamps. Rows voted, outlier drops, family supersession and freshness
  exclusions are read from each row's `sourceRankMeta`. Nothing is
  re-derived, so a vote hold or family rule added by #1817 shows up without
  a change here.

Fields per entry:

* identity: `key`, `displayName`, `provider`, `family`, `coverage`
  (offense / idp / rookie / combined);
* freshness: `lastGenuineUpdate` (ISO or null), `lastGenuineUpdateBasis`
  (`publisher_timestamp` / `content_change_observed` / `unknown` /
  `not_tracked_at_board_time`), `daysSinceUpdate`, `freshnessPct`
  (100/75/50/25/0, or null when not measured);
* weight: `baseWeight`, `effectiveWeight` (base x freshness x health x
  coverage, before any provider-family cap), `weightFactors`,
  `meanAppliedWeight` (the actual per-row weight after family caps and row
  clocks);
* contribution: `playersContributing`, `picksContributing`,
  `contributingByUniverse`, `notVotingRows` (reason → rows), `voting`;
* explanation: `status`, `statusLabel`, `reason` and `restoreRequirement`,
  in plain English;
* `voteHold` when one applies, and a `picks` block for sources that price
  picks.

Status rules (first match wins):

1. Seasonally inactive: *Seasonal*.
2. Shadow, owner-policy hold, or rollback: *Testing*.
3. Private source not provisioned on this host, or data file missing: *Data
   Issue*.
4. FAILED board: *Data Issue*.
5. Freshness not measured for this board (`not_tracked_at_board_time`):
   *Active — 100%* with that reason when it votes, *Data Issue* when it does
   not.
6. Unknown update time on a tracked source: *Data Issue*, or *Stale* when
   the lower bound is past 30 days.
7. Older than 30 days: *Stale*.
8. Fresh but no row used: *Data Issue*.
9. Otherwise *Active — 100 / 75 / 50 / 25%*.

## 4. The 26-source audit (§5)

Reproduce with `python scripts/source_voting_audit.py --format markdown`. It
builds through the real entry point from the newest export and prints input
hashes. Full output with reasons and restore requirements:
`evidence/.../source_voting_audit.md`. The JSON form is `source_voting_status.json`.

| Source | Key | Coverage | Last genuine update (basis) | Days | Freshness | Base → effective | Players / picks voted | Status |
|---|---|---|---|---|---|---|---|---|
| KeepTradeCut Crowd SF-TE++ | ktcCrowdSfTep | offense | 2026-10-19 (content) | 0 | 100% | 1 → 1 | 455 / 48 | Active — 100% |
| KeepTradeCut Trades SF-TE++ | ktcTradesSfTep | offense | 2026-10-19 (content) | 0 | 100% | 1 → 1 | 461 / 48 | Active — 100% |
| IDP Trade Calculator | idpTradeCalc | combined | 2026-10-10 (content) | 8 | 75% | 1 → 0.75 | 806 / 96 | Active — 75% |
| DLF Superflex | dlfSf | offense | 2026-10-18 (content) | 1 | 100% | 1 → 1 | 278 / 0 | Active — 100% |
| DLF Rookie SF | dlfRookieSf | rookie | 2026-10-15 (content) | 3 | 100% | 1 → 1 | 57 / 0 | Active — 100% |
| DLF IDP | dlfIdp | idp | 2026-10-18 (content) | 0 | 100% | 1 → 0 | 0 | Testing — Not Voting (owner-policy hold) |
| DLF Rookie IDP | dlfRookieIdp | rookie | 2026-10-18 (content) | 0 | 100% | 1 → 0 | 0 | Testing — Not Voting (owner-policy hold) |
| The IDP Show — Combined | idpShowCombined | combined | 2026-08-19 (publisher) | 60 | 0% | 1 → 0 | 0 | Stale — Not Voting |
| Dynasty Nerds SF-TEP | dynastyNerdsSfTep | offense | 2026-10-17 (content) | 1 | 100% | 1 → 1 | 282 / 0 | Active — 100% |
| FantasyCalc Dynasty SF | fantasyCalc | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 389 / 0 | Active — 100% |
| Signals Fantasy SF | signalsSf | offense | unknown here | — | — | 1 → 0 | 0 | Data Issue (private; not on this host) |
| Signals Fantasy IDP — DL | signalsIdpDl | idp | unknown here | — | — | 1 → 0 | 0 | Data Issue here; Testing (shadow) on production |
| Signals Fantasy IDP — LB | signalsIdpLb | idp | unknown here | — | — | 1 → 0 | 0 | Data Issue here; Testing (shadow) on production |
| Signals Fantasy IDP — DB | signalsIdpDb | idp | unknown here | — | — | 1 → 0 | 0 | Data Issue here; Testing (shadow) on production |
| OTC Fantasy Football SF | otcffbSf | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 444 / 0 | Active — 100% |
| Fantasy Navigator SF | fantasyNavigatorSf | offense | 2026-10-10 (content) | 8 | 75% | 1 → 0.75 | 445 / 0 | Active — 75% |
| Play for Keeps Dynasty | pfkDynasty | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 449 / 0 | Active — 100% |
| Dynasty Daddy Superflex | dynastyDaddySf | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 388 / 0 | Active — 100% |
| FantasyPros Dynasty SF | fantasyProsSf | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 406 / 0 | Active — 100% |
| FantasyPros Dynasty IDP | fantasyProsIdp | idp | 2026-09-04 (publisher) | 45 | 0% | 1 → 0 | 0 | Stale — Not Voting |
| FantasyPros / Fitzmaurice SF-TEP | fantasyProsFitzmaurice | offense | 2026-10-02 (content) | 16 | 50% | 1 → 0.5 | 291 / 0 | Active — 50% |
| Flock Fantasy Superflex | flockFantasySf | offense | 2026-10-18 (content) | 1 | 100% | 1 → 1 | 402 / 0 | Active — 100% |
| Flock Fantasy Rookie SF | flockFantasySfRookies | rookie | 2026-09-05 (content) | 43 | 0% (seasonal pause; not judged stale) | 1 → 0 | 0 | Seasonal — Not Voting |
| Yahoo / Justin Boone SF-TEP | yahooBoone | offense | 2026-10-14 (content) | 4 | 100% | 1 → 1 | 342 / 0 | Active — 100% |
| Draft Sharks Dynasty | draftSharks | offense | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 316 / 0 | Active — 100% |
| Draft Sharks IDP Dynasty | draftSharksIdp | idp | 2026-10-18 (content) | 0 | 100% | 1 → 1 | 320 / 0 | Active — 100% |

**Summary (this checkout).** 17 of 26 vote:

* 14 at 100%;
* 2 at 75% (IDP Trade Calculator, Fantasy Navigator);
* 1 at 50% (Fitzmaurice);
* none at 25%.

9 do not vote:

* **2 stale:** The IDP Show at 60 days and FantasyPros IDP at 45 days, both
  on the publisher's own timestamp;
* **2 testing:** DLF IDP and DLF Rookie IDP, under an owner-policy hold;
* **1 seasonal:** Flock Rookies;
* **4 data issue:** the private Signals boards, which are absent by design
  on every host but production.

On the production box, `signalsSf` votes at the step its recorded publisher
time gives, and the three Signals IDP boards show *Testing* (shadow). That is
an expectation from the code path; it was not observed from here
(UNRESOLVED 2).

### Exclusions from an older policy

Each one is re-evaluated under the 2026-10-19 directive.

| Source | Older rule that excluded or cut it | Status under this directive | What restores it / who owns it |
|---|---|---|---|
| `fantasyNavigatorSf` | **v1 cadence curve** (2026-09-23). It learned a ~24 h cadence, so 8 days without a snapshot quarantined it (freshness 0, 0 rows). | **Restored by this PR**: 8 days → 75%, votes on 445 rows. Still in the `ktcCrowd` family (measured KTC-derived lineage, not mere similarity), so it shares one provider cap with KTC Crowd. | Back to 100% on its next snapshot. |
| `fantasyProsFitzmaurice` | v1 curve judged it on a ~30-day cadence: freshness 1.0 at 16 days. | 16 days → **50%** under the schedule. Not an exclusion; this tightens the weight. | Next published update. |
| `fantasyProsIdp` | v1 curve on a content clock that a vendor revert had refreshed: 0.57. | **Stale (0%)**. The publisher's own update time is 2026-09-04, 45 days ago. Same clock as #1817 D5. | Votes again at 100% when FantasyPros' IDP experts publish. |
| `idpShowCombined` | v1 freshness quarantine (vendor chart unchanged since 2026-08-19). #1817 D2 adds a shared correlation cap with IDPTC on defensive rows. | **Stale (0%)** at 60 days on the vendor's own clock. That is a genuine age, not an exclusion by similarity. The D2 cap is #1817's call under directive §4. | Votes at 100% when the vendor republishes chart U8I37. |
| `dlfIdp`, `dlfRookieIdp` | Owner policy 2026-10-16, "DLF vote is offense-only" (`dlf_offense_only_vote`). | Fresh (100%). **The hold is rescinded by directive §1**. Lifting it is PR #1817's lane, together with the outlier fix. This PR does not touch the hold. | #1817 lifts the hold. The status then becomes Active automatically. |
| `signalsIdpDl/Lb/Db` | Shadow hold pending the shared-market crosswalk (`PRIVATE_SOURCE_VOTE_HOLDS`). The crosswalk failed round 1 on 2026-10-17. | **Testing**. Directive §5 asks for the normalization and validation to finish. It must not activate incompatible data, so this stays held. | The crosswalk passes its promotion gate (`signals_idp_shared_market`). |
| `idpTradeCalc` offense rows | #1817 D3 would exclude its offense vote. Not on `main`. | Directive §4 rescinds this: its offense values vote under the normal rules. #1817's lane. | — |
| `dlfValuesSfTep` | Unregistered / held (native-value normalization rejected). | #1817 D4 registers it as rank → Hill in the DLF family. It is not in `main`'s 26. | #1817. |
| `flockFantasySfRookies` | Seasonal policy (2026-10-03). | **Legitimate**, kept: *Seasonal*. | The next rookie class. |
| per-row outlier drops | Hampel filter: 101 dropped observations across 13 sources on the v2 board (98 on `main`). Draft Sharks has 52. | The outlier lane's (§6). | — |

Not exclusions: the KTC Market benchmark is never a vote, by design, and
`ktc` / `ktcSfTep` are same-crowd calibration states (directive §3: not
independent votes).

## 5. Hidden weighting audit (§7)

The effective weight of a vote is:

`base x freshness x health x coverage x familyAdjustment`

* **Base:** the registry weight, 1.0 everywhere. Unchanged.
* **Freshness:** the schedule (this PR).
* **familyAdjustment:** the approved provider-family cap
  (`cap_family_weights`, owner directive 2026-09-24). Correlated members
  share one provider's authority.

That leaves two factors, and both are documented here so neither is hidden.

**Health** (`config/sources/freshness_v1.json` `healthFactors`):
HEALTHY 1.0, DEGRADED 0.5, FAILED 0. It is judged on the source CSV on disk
by `dataset_integrity.parse_board`.

* **FAILED → 0 is a genuine data-validity gate. Keep it.** It covers an
  HTML, CAPTCHA, challenge or login page; an unreadable file; no
  recognizable columns; or no numeric rows. Those boards must never vote.
* **DEGRADED → 0.5 is a soft judgment with no measured basis.** It covers
  name coverage below 95%, numeric coverage below 80%, a duplicate-name
  explosion above 10%, a zero-value explosion above 25%, or a row count
  below 50% of the source's own rolling median.
  * A suspicious board votes at half weight.
  * The directive's eligibility rule is binary: the board passes reasonable
    integrity safeguards or it does not.
  * **Recommendation (owner/methodology decision, not made here):** make
    DEGRADED fail closed (0). A board our own integrity check calls
    suspicious should not half-vote.

**Coverage** (`coverage.floorFraction` 0.8): `factor = min(1, rows /
(0.8 x rolling median rows))`. It scales every row of a source whose last
accepted board is smaller than usual.

* **Measured** over each source's retained history (up to 30 accepted
  boards), it fired only on legitimate vendor size changes:
  * FantasyPros SF: 2 boards at 0.78–0.79 of median, factor ~0.98;
  * Flock Rookies, at class transitions: 0.70, 0.71 and 0.55, factor down
    to 0.69;
  * Yahoo/Boone list length: 0.64 and 0.79, factor down to 0.8.
* None of these was a broken scrape. A genuine collapse is already caught
  by DEGRADED, at below 50%.
* The rows still present are valid opinions; a shorter list does not make
  them less valid.
* **Recommendation (owner/methodology decision, not made here):** retire
  coverage from the weight and keep it as a reported diagnostic and alert.

**Board impact of either recommendation today: 0.** Every registered source
is HEALTHY. Every source that votes has coverage factor 1.0. The only
coverage factor below 1.0 is `flockFantasySfRookies` at 0.69 (48 rows
against its usual ~70), and it is seasonally inactive, so it casts no vote.
That case is itself a legitimate class-transition shrink. Neither factor
was changed in this PR.

## 6. Whole-board evidence (§9, freshness part)

The inputs are the same for every comparison:

* export `exports/latest/dynasty_data_2026-10-19.json`, sha256 `b639608f…`;
* the tracked `CSVs/site_raw` and `data/scrape_state` from `b08f7230d1`.

Reproduce:

* `scripts/golden_board.py` + `scripts/board_diff.py`, for the decision
  fields;
* `python scripts/freshness_schedule_impact.py --input exports/latest/dynasty_data_2026-10-19.json`,
  which builds both boards in one process and gives the richer report
  (`evidence/.../impact.md`, `impact.json`).

**Flag off is byte-identical to `main`.**

* `board_diff.py --expect-no-value-change`: 0 values, 0 ranks, 0 labels
  (`board_diff_flag_off.txt`).
* Whole-contract comparison: the only differences are the two `generatedAt`
  timestamps and the new additive `sourceVotingStatus` block. All 1,130
  rows are identical (`flag_off_contract_identity.txt`).

**v2 against `main`:**

| class | rows priced before | rows changed | median | p90 | p99 | max |
|---|---|---|---|---|---|---|
| offense | 402 | 391 | 0.79% | 3.27% | 19.21% | 42.86% |
| rookie | 86 | 69 | 0.80% | 2.50% | 5.63% | 9.24% |
| IDP | 397 | 321 | 1.28% | 4.33% | 8.80% | 11.95% |
| picks | 144 | 137 | 0.39% | 1.33% | 5.38% | 5.65% |
| **all** | 1,029 | 918 | 0.91% | 3.60% | 12.71% | 42.86% |

* **Top 50:** 1 entered, 1 left, 23 rank moves of at most 4 places. Value
  change median 0.54%, max 3.25%.
* **Top 200:** 1 entered, 1 left, 151 rank moves of at most 19 places. Max
  value change 7.02%.
* **Voting sources per priced player:** mean 6.31 → 6.51. Single-source
  rows: 58 → 58.
* **Newly unpriced:** 3 deep IDP players (Dee Alford, James Pierre, Kyle
  Dugger). FantasyPros IDP was their only voter and is now stale. They show
  as unpriced, never as 0 (missing is never zero).
* **Newly priced:** 1 (Chris Moore), because Fantasy Navigator voted again.
* **Confidence:** medium → low on 125 rows, mostly IDP rows that lost
  FantasyPros IDP. Losing evidence lowers confidence; it never raises it.
  Other transitions: low → medium 10, medium → high 8, high → medium 5,
  low → none 3, none → low 1.
* **Family weight totals:**
  * fantasyPros 550 → 408 (FP IDP stale, Fitzmaurice at 50%);
  * idpTradeCalc 764 → 677 (0.87 → 0.75);
  * ktcCrowd 505 → 513 (Fantasy Navigator back, capped with KTC Crowd at
    one provider: 0.571 + 0.429).
* **Outlier drops:** 98 → 101 observations. Per-source drops moved by at most 3.
* **Travis Hunter (two-way):** 3,738 → 3,801 (+1.7%):
  * Fantasy Navigator votes again at 0.43, inside the KTC Crowd family cap;
  * the FantasyPros family splits 0.67 / 0.33 (SF / Fitzmaurice) instead
    of 0.5 / 0.5;
  * the IDP Trade Calculator goes 0.87 → 0.75.

**What caused the largest moves.** Every top mover is explained in
`impact.md`.

* **Offense, up to +42.9%.** Fantasy Navigator, quarantined by v1 at 8 days
  old, votes again at 75%.
  * On deep offense rows with few voters (KTC Crowd, KTC Trades, OTC,
    Flock), it adds an opinion, often well above KTC.
  * In the largest case it also changes the Hampel verdict. LaJohntay
    Wester went 651 → 930 because Flock's 1,889 is no longer dropped once
    Navigator's 1,088 widens the spread.
  * That second effect is the outlier interaction directive §6 describes,
    and it is the outlier lane's. This lane does not tune it.
* **IDP, down to −12%.** FantasyPros IDP at 45 days stops voting, so those
  rows rest on the IDP Trade Calculator (now 75%) and Draft Sharks IDP.
* **Picks, at most 5.65%.** The IDP Trade Calculator's pick board was last
  changed 2026-10-10 and goes 0.87 → 0.75.

**Verification** (6,723 votes on the v2 board): **PASS**.

* Every vote's freshness factor is one of the schedule steps.
* No vote rests on evidence older than 30 days, and no voting source is
  older than 30 days.
* Every fresh vote from a healthy, full-coverage source carries exactly
  `base x familyAdjustment`. That is its full approved base weight, subject
  only to the provider-family cap.

**CI findings on the first push, root-caused.**

1. `test_golden_dataset_invariants::test_single_source_player_takes_the_haircut`
   is in the hard gate.
   * The synthetic board is dated 2026-07-29 and is built against this
     checkout's dataset state. KTC Crowd's tracking began 2026-09-09.
   * The first push treated "no clock at the board's time" as unknown and
     set it to 0. The KTC-only "Lonely Rookie" therefore had no vote and the
     haircut never ran.
   * **This was a defect in the rule, not in the fixture.** A board that
     predates our tracking is a measurement gap.
   * **Fixed:** the not-tracked posture of §2 item 4. The test passes
     unchanged.
2. `test_single_curve_live::test_anchor_plus_shrunk_subgroup_matches_rank_derived_value`
   is livedata and advisory. On today's board 0 IDP rows have a subgroup
   (non-anchor) voter, against 249 on `main`.
   * The only non-anchor IDP voter on `main` was FantasyPros IDP. Its own
     vendor clock is 45 days old, so it correctly stops voting.
   * DLF IDP, the other non-anchor member, is held by the 2026-10-16 owner
     policy.
   * The IDP anchors are intact on 394 of 394 priced IDP rows. The IDP Trade
     Calculator votes at 75%, not 0.
   * The invariant itself still holds under v2 whenever a fresh subgroup
     voter exists:
     * with `RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0` (DLF IDP voting, which
       is what directive §1 / #1817 restores), all 29 tests in the file pass
       under v2;
     * the deterministic counterpart
       `test_valuation_pipeline_stages::test_idp_row_combines_anchor_and_subgroup_at_alpha`
       passes.
   * The live guard's precondition comes back when #1817 lifts the DLF IDP
     hold, or when FantasyPros IDP republishes. The test is not changed.
   * **Not failing on `main`.** On `main`, FantasyPros IDP still votes at
     0.57 under the v1 curve, so the guard passes there. This is a
     consequence of this PR on today's data: the schedule correctly retires
     a 45-day-old board. It is not a code defect.
   * **Ordering consequence:** land #1817 (which lifts the DLF IDP hold)
     before or with this PR, and the guard stays green. Verified: with the
     hold lifted by flag, the file passes under v2.
3. `test_signals_active_source::TestExpiredSession::test_a_few_days_stale_still_votes_at_a_decayed_weight`
   is in the hard gate.
   * It staged a Signals board 60 hours old and asserted that it votes at a
     reduced weight. That is the v1 cadence curve (a 24-hour cadence).
   * Under the owner's schedule, 60 hours is day 2: full weight, so no
     reduction is stamped. The test encoded the superseded methodology.
   * **Updated, nothing dropped.** Under the schedule it now pins:
     * 60 h → full weight;
     * 10 days → 0.75 with the stamped age;
     * 35 days → no vote, evidence kept.

     The original v1 assertions run unchanged under the rollback flag:
     60 h decays, 20 days stops.

## 7. Rollback and coordination

* **Rollback:** `RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2=0` and restart.
  It is proven byte-identical on decision fields and on every row, as in §6.
* **PR #1817** (vote holds, families, D2–D5):
  * D5's clock rule is the schedule's clock rule for any source with a
    recorded vendor time. If #1817 lands first, nothing changes here.
  * The DLF IDP and IDPTC-offense changes the directive requires are #1817's.
    The status payload reads their stamps.
  * The `feature_flags.py` count lines (README / ARCHITECTURE / docstring)
    will conflict textually. Whichever lands second recounts.
* **Outlier lane:** the Navigator-driven Hampel flips above are evidence for
  that lane. This PR changes no outlier math.

## 8. UNRESOLVED

1. **Owner/methodology decisions, recommended and not made:** DEGRADED health
   → 0, and retiring the coverage factor (§5). Board impact today is 0.
2. **Production observation is pending:** the Signals rows (provisioned only
   on the box), and the deployed board's `sourceVotingStatus`. Pending a
   deploy.
3. **Picks are on the schedule, each subset on its own clock.** The
   directive names offense, IDP and rookie sources; picks follow from "the
   entire dynasty valuation system". If the owner wants picks excluded, that
   takes a small per-subset exemption (today `exemptKeys` is per source).
4. **Release ordering with #1817.** Until DLF IDP's hold is lifted, today's
   board has no non-anchor IDP voter, because FantasyPros IDP is stale. The
   advisory livedata anchor-chain guard therefore stays red. Landing #1817
   first, or in the same train, resolves it.
