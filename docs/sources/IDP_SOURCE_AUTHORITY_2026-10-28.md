# IDP source authority: why elite IDP rows keep about 37% of normal weight (2026-10-28)

**Status:** evidence report, one additive per-row diagnostic, and one additive evidence
recorder. No value, weight, vote, freshness rule, flag or hold was changed.
**Agent-OS-Receipt:** 47a8b19fff9d06da9b1a651aab5fb92f1e16d5f6
**Builds on:** `docs/ops/IDP_SOURCE_STALENESS_2026-10-25.md` (same question, three days
earlier) and `docs/sources/IDP_SHOW_RECOVERY_2026-10-17.md`. Every finding there was
re-measured here. All of them still hold.

## 1. Answer

The 37% is arithmetic over four IDP voting families, and three of them are stale **at the
vendor**:

```
retainedAuthority = (IDPTC 0.303 + IDP Show 0.000 + FantasyPros IDP 0.210 + DraftSharks IDP 1.000) / 4
                  = 1.513 / 4 = 0.378
```

Every collector is working, and every clock reads what the vendor states. **No ingestion,
parsing or timestamp bug was found.** So no served value can legitimately be restored by a
bug fix. Recovering more authority needs owner decisions (section 5).

DLF IDP is fresh, but the owner policy hold keeps it out of the vote. A held source is not
in the `retainedAuthority` denominator, so it does not cause the 37%. It is simply the one
fresh IDP board that is not voting.

## 2. Measurement

Board: `exports/archive/dynasty_export_20261028_090226.zip` (as-of `2026-10-28T09:02:26Z`,
byte-identical to `exports/latest/dynasty_data_2026-10-28.json`). It was rebuilt with
`build_api_data_contract` on `origin/main` `12b0f3209`, using this checkout's CSVs and
dataset state.

* **IDP rows:** 427 in total, 397 carrying `retainedAuthority`.
  * Median 0.378, mean 0.396.
  * States: 334 `SEVERELY_DEGRADED`, 52 `DEGRADED`, 11 `NORMAL`.
* **Top 24 IDP by rank:** median 0.378.

Per-source factors on one elite row, Myles Garrett (identical on every IDP row the four
families cover):

| source | base | freshness | applied | content clock | basis | value contribution |
|---|---|---|---|---|---|---|
| `idpTradeCalc` | 1.0 | 0.303 (439 h, learned cadence 127.9 h) | 0.303 | 2026-10-10 | observed content change | 5,399 |
| `idpShowCombined` | 1.0 | 0.0, quarantined (1,671 h vs 168 h) | 0 (withheld) | 2026-08-19 | vendor `lastModifiedAt` | (4,184) |
| `fantasyProsIdp` | 1.0 | 0.210 (1,302 h vs 325.5 h) | 0.210 | 2026-09-04 | vendor `last_updated_ts` (owner D5) | 3,677 |
| `draftSharksIdp` | 1.0 | 1.0 | 1.0 | 2026-10-28 | observed content change | 1,913 |
| `dlfIdp` | — | fresh (2026-10-24) | held | — | `dlf_offense_only_vote` (owner O3-1) | not voting |

Some rows have no IDP Show coverage, for example rookie Zakee Wheatley. On those rows the
denominator is 3, so authority is 0.504.

DraftSharks IDP is the only fresh voter, so it carries 66% of the normalized vote
(`dominantSource`). Its dynasty model values age-30 defenders low (Garrett 3D Value+ = 5).
That is a vendor methodology view, not a translation defect.

### Representative rows (current board, unchanged by this PR)

| player | type | value | rank | retained | `sourceAuthorityReasons` |
|---|---|---|---|---|---|
| Aidan Hutchinson | elite DL | 4,268 | 92 | 0.378 | idpTradeCalc `stale=0.303@2026-10-10`, idpShowCombined `withheld:stale@2026-08-19`, fantasyProsIdp `stale=0.21@2026-09-04`, dlfIdp `held:owner_policy` |
| Myles Garrett | elite DL | 2,818 | 191 | 0.378 | same four codes |
| Jack Campbell | elite LB | 5,429 | 49 | 0.378 | same four codes |
| Fred Warner | elite LB | 4,272 | 91 | 0.378 | same four codes |
| Kyle Hamilton | elite DB | 2,604 | 218 | 0.378 | same four codes |
| Sonny Styles | rookie LB | 5,314 | 57 | 0.378 | same, plus dlfRookieIdp `held:owner_policy` |
| Caleb Downs | rookie DB | 3,632 | 124 | 0.378 | same, plus dlfRookieIdp `held:owner_policy` |
| Zakee Wheatley | rookie DB, deep | 1,246 | — | 0.504 | idpTradeCalc and fantasyProsIdp stale (no IDP Show / DLF coverage) |
| Alex Anzalone | deep LB | 1,457 | 598 | 0.378 | same four codes |

## 3. Per-source root cause (verified live, read-only, 2026-10-28)

### The IDP Show: the vendor stopped updating the board we vote

**Status: stale at the vendor; our clock is correct.**

* **Voting board.** The voting board is the combined dynasty post,
  `combined-idp-offense-dynasty-rankings-fantasy-football`.
  * Substack API: `updated_at` 2026-06-22.
  * Its full chart is Datawrapper `U8I37`. v4 is terminal (`lastModifiedAt`
    2026-08-19T17:50:16Z), and v5–v7 return 404.
  * The excerpt chart `gNM2r` v5 says the same: last modified 2026-08-19.
  * Our `idpShowCombined.csv` has not changed in content since its first observation on
    2026-08-20. It has exactly one commit.
* **The two-hourly `chore(idpshow)` commits** rewrite only
  `*_last_success` / `*_last_status.json`. They prove the fetch works. They do not prove
  the data is fresh, and the freshness clock correctly ignores them.
* **Newer posts.** The vendor's newer "combined" posts are not dynasty, and none of them
  embeds a replacement dynasty chart:
  * `2026-combined-idp-rankings-tiers-db-dl-lb`, 08-28: "2026 Combined IDP Rankings 3.0";
  * `2026-fantasy-football-rankings-combined-offense-plus-idp`, 08-29: a 2026 draft
    walkthrough;
  * the weekly and rest-of-season posts.

  Those posts are seasonal-lane evidence. They are barred from the dynasty pool.
* **IDP-only board.** The vendor **did** republish its **IDP-only** dynasty board
  (`idp-dynasty-rankings`, 2026-10-08). Our non-voting `idpShow.csv` changed 332 of 350
  rows on 2026-10-17. That board is fresh information. It does not vote, because the
  2026-08-20 owner decision made the combined board the family's sole voter.
* Same publisher, same paywalled-Substack + public-Datawrapper access path, same session
  jar.

### FantasyPros IDP: the "9/04" label is read correctly

**Status: stale at the vendor; clock correct under owner decision D5.**

* **Live pages.** All four pages the collector reads (`dynasty-idp`, `-dl`, `-lb`, `-db`)
  state `last_updated_ts = 1788489264`, which is 2026-09-04T02:34:24Z, with 6 of 6 experts
  included. The year comes from the unix timestamp; it is never inferred from the "9/04"
  label.
* **Offense page.** The offense page (`dynasty-overall`) says 10/27 through the same
  mechanism, so the IDP date is the vendor's own.
* **The 2026-10-23 broad content change is not a new publication.**
  * FantasyPros raised the included-expert set from 2 to 6.
  * The combined page grew from 119 to 192 directly ranked rows, and 115 of the 119
    reordered.
  * The page's newest expert update is still 09-04, so this is a re-blend of older
    opinions.
  * The 10-25 report read the six per-expert dates as 06-05 … 09-04.
  * Under D5 (`fantasypros_idp_upstream_clock`, clock = min(vendor time, last content
    change)) that is correctly not an update.

### IDP Trade Calculator: the vendor last updated on 10/10

**Status: stale at the vendor; clock correct.**

* The homepage reads "Updated: 10/10/2026" today.
* The dataset state shows broad changes through 2026-10-10T20:25Z. After that there is
  only 1-row name churn, on 10-14, 10-15 and 10-16.
* The 0.303 factor comes from the learned cadence of 127.9 h. That is a p75 over a bursty
  in-season sample.

### DraftSharks IDP: healthy

**Status: healthy and fresh.**

* Its last broad change was at 2026-10-28T01:50Z.
* The 10-25 collector outage (Ubuntu 26.04 runner) is repaired; the job is pinned to
  `ubuntu-24.04`, #1953.

### DLF IDP and DLF Rookie IDP: fresh but held

**Status: fresh and held from voting.**

* Content changed on 2026-10-24 (IDP) and 2026-10-27 (rookie).
* They observe 150 and 29 rows of this board.
* The hold is `dlf_offense_only_vote`:
  * owner decision O3-1, 2026-10-20 (`docs/OWNER_REQUESTED_TODO.md`);
  * `docs/EXECUTION_PLAN.md` §0, owner-reserved;
  * locked by `tests/api/test_dlf_idp_hold_locked.py` and
    `scripts/verify_owner_held_flags.py`.
* **What release requires:** a preregistered outlier-filter Version 2 that passes every
  mandatory gate (`docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md`), then explicit
  owner approval. The G2 source-integrity evidence is in
  `docs/valuation/idp_accuracy/g2_source_integrity/`. Its readiness packages are in
  `docs/sources/outlier_integrity_v2/dlf_readiness/`. This report prepares nothing beyond
  that.

### Signals IDP (DL / LB / DB): shadow only

**Status: shadow only, by owner decision.**

* It is `not_provisioned` where this board is built, and its vote flags default OFF.
* Activation is owner-reserved.

## 4. What this PR changes

1. **`sourceAuthorityReasons` (per row, additive, diagnostic).**
   * **Shape.** One compact code per source that carries less than its base authority on
     the row, or that observed the row while held from voting:

     | code | meaning |
     |---|---|
     | `stale=<f>@<date>` | voting at reduced freshness; `<date>` is the content clock |
     | `withheld:stale@<date>` | not voting because of staleness |
     | `withheld:health` | not voting because of health |
     | `health=<f>` | voting at reduced source health |
     | `coverage=<f>` | voting at reduced coverage |
     | `family_cap=<f>` | voting under a shared provider-family cap |
     | `outlier_dropped` | rejected by the outlier filter |
     | `superseded:<key>` | replaced by another member of its family |
     | `held:owner_policy` | observed the row but held from voting by an owner policy |

   * **Where it appears.**
     * `{}` means nothing was reduced.
     * It is mirrored onto the legacy `players` dict and the rankings delta, as
       `retainedAuthority` is.
     * It is built from the stamps the blend already wrote, and nothing reads it back.
   * **Proof of no value change.**
     * `scripts/golden_board.py` + `scripts/board_diff.py --expect-no-value-change` gives
       **0 values, 0 ranks, 0 labels** (1,103 rows, 427 IDP, 138 picks).
     * The whole contract is byte-identical apart from the new field and
       `dataFreshness.generatedAt`.
   * **Size.** About 340 KB raw (about 170 KB in `playersArray` and again in the legacy mirror) over 979 stamped rows. The production payload ceiling test
     passes.
   * **Tests.** Pinned by `tests/api/test_source_authority_reasons.py`:
     * unit tests for every code;
     * on a real archived board, every reduced source is named, every row below full
       authority has a weight reason, and a held source is named only where it observed
       the row.
2. **The IDP Show IDP-only board's vendor clock is now recorded.**
   * **What.** `scripts/fetch_idpshow.py` writes the plain board's Datawrapper
     `lastModifiedAt` / `publishedAt` to `data/scrape_state/idpShow_upstream.json`, and
     `deploy/idpshow_fetch_and_push.sh` commits it.
   * **Effect today: none.** It is evidence only. `idpShow` is unregistered and nothing
     reads the file.
   * **Why now.** If the owner ever lets the IDP-only board vote, its first clock must be
     the vendor's stated time. Without one it is a first-observation baseline, or an
     unmeasured factor of 1.0, and either would manufacture freshness. The vendor's
     metadata for older chart versions is not recoverable later.

## 5. Decisions only the owner can make (smallest exact decision each)

### D-A. Which IDP Show board votes

Should the family vote move from the stale combined board to the IDP-only board? The family
still casts one vote either way.

**Analysis-only what-if.** The `idpShow` key was voted in-process on the same board. It was
weighted at 0.419, which is the C4 factor at the vendor post date 10-08, and at 1.0. Nothing
was committed.

**At weight 0.419:**

* IDP median `retainedAuthority` rises from 0.378 to 0.565.
* 402 rows move value: 345 IDP, 56 picks (through the rookie tether) and 1 offense.
* The median IDP move is 1.2%, and 40 rows move more than 10%.

**Why it is not a simple restore:**

* **Outlier filter.** A fourth voter makes the incumbent outlier filter drop 21
  DraftSharks IDP and 15 FantasyPros IDP votes on IDP rows; today it drops none. Two
  examples:
  * Aidan Hutchinson: 4,268 to 6,422, with authority falling to 0.385 because the fresh
    DraftSharks vote is dropped;
  * Kyle Hamilton: 2,604 to 3,574.

  This is the same interaction that keeps DLF IDP held.
* **Single-source haircut.** Deep single-source rows swing −70% to +254% as the haircut
  switches on or off.

**Prerequisites, from the IDP Show recovery doc §3.4:**

* identity / coverage / position check;
* lineage check against IDPTC;
* at least one recorded vendor clock (from item 2 above);
* realistically, the outlier-filter V2 gate.

**Smallest decision:** "Gate an IDP Show board switch on outlier-integrity V2, like DLF
IDP — yes / no."

### D-B. IDPTC cadence clamp

**Question:** should IDP Trade Calculator's expected cadence be its learned 127.9 h
(today's rule), or the configured `maxHours` 240 h?

* At 240 h the factor would be 0.771 instead of 0.303, and IDP median retention would rise
  from 0.378 to about 0.495 (+31%).
* This is the freshness-threshold question the 10-25 report already named.
* It is a rule change, so it is owner-reserved.

### D-C. FantasyPros IDP

**No decision needed.** D5 is applied correctly, and the vendor is genuinely stale.

### D-D. DLF IDP release

**No new decision.** It stays held under O3-1 until outlier-integrity V2 passes and the
owner approves.

## 6. Result

**STATUS:** DONE. Diagnosis is complete. The diagnostic and the evidence recorder are
implemented, with no value change.

**ACCEPTANCE:**

* per-source data age and cause;
* a measured decomposition of the 37%;
* legitimate restoration attempted: none is possible without a rule or vote change, so
  decisions are packaged instead;
* per-row reasons exposed, with no value change;
* this document.

**EVIDENCE:**

* board rebuild;
* live vendor pages and APIs: Substack archive and post API, Datawrapper chart versions,
  FantasyPros `ecrData`, IDPTC homepage;
* dataset-state change histories;
* golden board diff;
* new tests and related contract tests.

**UNRESOLVED:**

* `idpShow_upstream.json` first appears after the next production `dynasty-idpshow-fetch`
  run following deploy. Not yet observed.
* The D-A what-if treats the IDP-only board as freshness-unmeasured with an emulated
  weight. Its identity matching and position mapping were not audited.
* Owner decisions D-A and D-B are open.
