# Forced-drop fix — production-box replay runbook (PREPARED, NOT RUN)

> **This replay has NOT been run, and it must not be run without the owner's explicit authorization.** Nothing in this
> document, the PR it belongs to, or the script it describes has touched production. The flag
> `forced_drop_cheapest_legal` stays **OFF**. This is the checklist for the one measurement the activation decision is
> still missing: the local replay ([`FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md`](FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md))
> ran with scarcity inert at 1.0, Component B abstaining and posture unknown for some teams.

**Authority:** record [`FORCED_DROP_FIX_2026-10-20.md`](FORCED_DROP_FIX_2026-10-20.md) §10 item 3 ("box replay with real
scarcity and Component B ... must report the currency anomaly in BOTH directions"). **Pattern:**
`scripts/package_model_phase3_research.py --box` and `scripts/low_value_asset_box.py --box`, with
`scripts/research_readonly_guard.py`. **Script:** `scripts/forced_drop_fix_replay.py --box` (support:
`scripts/forced_drop_box_support.py`; tests: `tests/trade/test_forced_drop_box_mode.py`).

## 0. Who must approve, and who runs it

| role | what |
|---|---|
| **Owner** | Authorizes the run in writing, in the session, before anyone logs in to the box. Nothing below is implied authorization. |
| **Operator** (someone with shell access to the production host) | Runs the commands in §3 as the **service user** (the user `dynasty.service` runs as — never root, never an interactive admin account), reads nothing but what §3 names, and hands back the one output file. |
| **Coordinator** | Fills the `<...>` placeholders in §2 with the final SHAs, checks the output against §5 and §6, and commits the evidence through a normal PR (§4 step 8). |

## 1. What the run is, and is not

* **Read-only.** The audit-hook guard (`research_readonly_guard.py`) is installed before any application import. The
  process cannot open a file for writing outside its own private scratch directory, cannot create, remove, rename or
  `chmod` anything, cannot open SQLite read-write, cannot open a network connection or resolve a host, and cannot start
  a subprocess. A refused attempt raises (the run fails closed) and is counted in the report
  (`readOnlyGuard.refusedWriteOrProcessAttempts`; exit code 3). The contract build's Sleeper lookup is refused the
  same way as in the Phase 3 and low-value-asset box runs (the build falls back to its defaults; those refusals are
  counted separately as `refusedNetworkAttempts` and are expected: 3 per board build).
* **The flag is toggled in-process only.** `forced_drop_cheapest_legal` is switched ON and OFF inside the process
  (environment variable + `feature_flags.reload()`, always restored). The service, its environment, its units and
  its files are untouched. There is no `--out`: the report goes to stdout and the operator's shell redirect writes
  it to a directory the operator created outside the application tree.
* **Pinned, not "whatever is current".** The board is a function of the archive **and** the CSV tree the contract
  build reads, and the box's working tree moves every two hours. The run therefore reads the pinned archive and a
  CSV tree **materialised at the pinned revision into a scratch directory** — never the live working tree — and
  refuses to start unless every pin matches (exit 2, nothing measured): archive sha256, the archive's JSON member
  sha256, CSV-tree content sha256, the deployed code commit, and (after the build) the built-board sha256.
* **Aggregates only.** The report is refused (exit 4, nothing printed) unless it contains counts and statistics only:
  no key naming an identifier or person, no 9+ digit run, no canonical asset id, no hex digest outside the named
  provenance fields, no over-long string, and **no token taken from the replayed league itself** (its Sleeper ids,
  team names, owner names, usernames). Per-trade and per-team detail (examples, illustrations, per-team finder rows) is
  dropped before the check. The repository is public.
* **What it adds over the local replay.** (1) the scarcity multipliers this host actually resolves
  (`scarcityObserved`); (2) Component B (the roster-utility lens) and posture as the box has them — a second census
  decided with the real lens instead of the not-applicable stand-in (`componentBCensus`); (3) both currency-anomaly
  directions, forward and reverse, in all four designs (`currencyAnomalyDirections` and inside
  `warRoom` / `census`); (4) the single-source stress (`singleSourceStress`): the census with every single-source
  player treated as unpriced, so the dependence of the favourable verdicts on the cheap tail is measured on real data;
  (5) the War Room charge shift (`warRoomChargeShift`); (6) the real Trade Finder (Team Context, top 20, 12 teams);
  (7) the review-fix receipts (`packageCreditClampApplied`, `searchBoundExceeded` in the census counts); (8) the band
  receipt, package-model receipt and config hashes.

## 2. Pins (fill the placeholders before the run)

| pin | value |
|---|---|
| Code under test | PR #1890 head **`<FINAL_PR_HEAD_SHA>`** (filled by the coordinator). The hashes below were refreshed on 2026-10-21 for the V5-R default (owner decision): `forced_drop_selection.py` and `forced_drop_fix_replay.py` changed, and the earlier `roster_capacity.py` pin was already stale at `dfe4345b6`, which changed that file after `557338a22` — the box must be running a deployment of this tree (the flag is OFF by default, so the PR can be merged and deployed dormant first). `--expect-code-sha` is the **deployed** commit: **`<DEPLOYED_SHA>`** (the merge commit if the PR is squash-merged, otherwise the PR head). |
| Script files (sha256 at `<FINAL_PR_HEAD_SHA>`) | `scripts/forced_drop_fix_replay.py` `92176ce07479008623b6e40ea487f94f37306aa87e31473e7a2761bdfe56505c`; `scripts/forced_drop_box_support.py` `4841ac8b241c43571cd0551c93bfd711dbcfec5213dc66bef66ddbfe02c67478`; `scripts/research_readonly_guard.py` `5c208fe8ee187d78ef7173330efc795a621b970f1ba69ff416c9edf836bc6f18`; `src/trade/forced_drop_selection.py` `eaa1ee4059850fb6db01e2ba8c498d780f1c1ef8c63a4f663fabaf791676d966`; `src/trade/roster_capacity.py` `ea2f65645411bc5b3b2bd4f38036071a446d75a764ebc1e00e1dce825d231c3e`; `src/trade/trade_decision.py` `325ed03514351a486e25daa5b8442f09f91d889ece58c84b9b179e745e661794`; `src/trade/analyze_trade.py` `6a3935bb66b41ca34e281bf85006397968c0a45ffb8384857081e4db44db776e` |
| Archive | `exports/archive/dynasty_export_20261020_052241.zip` — file sha256 `f660098f3c68eee3be24790d7674bd263616d4c97d330e92c24ed77d5dd6078e`; JSON member `dynasty_data_2026-10-20.json` sha256 `8e9b826a3a148bbb17636aec79b46eefe3e9138940976959c4342dc4774b198a` |
| CSV tree | revision `d5236546ff4df9294b6cf99c6b93e8db57e6ff36` (`CSVs`, `data/scrape_state`, `config/weights`), content sha256 `31687c60b2adc9f347eb58c8da2e15a1198a264d3b98200b1db3fa5f2345bd54` |
| Built board | `eed8df11637b17076b4d1aa10ff1c8bf2190cc08afa57e12e0ddc2fa5c290833` (1,003 priced assets; `fairness_bands_v2`, `geom_q078_v1`) |

The archive and the CSV tree are the ones every local figure in the record was measured on, so the box result differs
from the local one **only** by what the box has that the laptop does not (scarcity, Component B, posture, the live
league state in `data/`), never by the board.

## 3. The command

Run as the service user, from a shell where nothing else is deploying. All paths below are examples; `APP` is the
deployed application directory (the value the service uses for `RISKIT_APP_DIR` / its working directory), `PY` the
interpreter the service uses (see `ExecStart` in its unit file).

```bash
set -euo pipefail
APP=<application directory>            # deployed tree, commit = <DEPLOYED_SHA>
PY=<service interpreter>
CODE_SHA=<DEPLOYED_SHA>
CSV_REV=d5236546ff4df9294b6cf99c6b93e8db57e6ff36
ARCHIVE=exports/archive/dynasty_export_20261020_052241.zip

# 0. Preconditions (read-only).
test "$(git -C "$APP" rev-parse HEAD)" = "$CODE_SHA"
(cd "$APP" && sha256sum --check - <<'EOF'
92176ce07479008623b6e40ea487f94f37306aa87e31473e7a2761bdfe56505c  scripts/forced_drop_fix_replay.py
4841ac8b241c43571cd0551c93bfd711dbcfec5213dc66bef66ddbfe02c67478  scripts/forced_drop_box_support.py
5c208fe8ee187d78ef7173330efc795a621b970f1ba69ff416c9edf836bc6f18  scripts/research_readonly_guard.py
eaa1ee4059850fb6db01e2ba8c498d780f1c1ef8c63a4f663fabaf791676d966  src/trade/forced_drop_selection.py
ea2f65645411bc5b3b2bd4f38036071a446d75a764ebc1e00e1dce825d231c3e  src/trade/roster_capacity.py
325ed03514351a486e25daa5b8442f09f91d889ece58c84b9b179e745e661794  src/trade/trade_decision.py
6a3935bb66b41ca34e281bf85006397968c0a45ffb8384857081e4db44db776e  src/trade/analyze_trade.py
f660098f3c68eee3be24790d7674bd263616d4c97d330e92c24ed77d5dd6078e  exports/archive/dynasty_export_20261020_052241.zip
EOF
)

# 1. A private scratch tree OUTSIDE the application directory, and an output directory.
WORK=$(mktemp -d /var/tmp/fdr-box-XXXXXX)          # 0700 by mktemp
mkdir "$WORK/csvtree" "$WORK/out"
git -C "$APP" archive "$CSV_REV" CSVs data/scrape_state config/weights | tar -x -C "$WORK/csvtree"
#    (git archive only READS the repository. If the box has no object for $CSV_REV, copy the tree from a
#     workstation instead and let the run's CSV-tree sha256 pin prove it is the same tree.)

# 2. The guard's own refusals, no application code imported: exits 0 and prints one JSON line in which
#    writeOutsideScratch, mkdirOutsideScratch, networkConnect, subprocess and sqliteReadWrite are all "refused"
#    and writeInsideScratch is "allowed". Anything else: stop.
RISKIT_APP_DIR="$APP" "$PY" "$APP/scripts/forced_drop_fix_replay.py" --box --box-selftest

# 3. The replay (a non-zero exit is reported, not fatal to the shell, so the exit code is printed). nice, a wall-clock timeout, a 4 GiB address-space cap inside the process, single-threaded BLAS.
cd "$APP"
env RISKIT_APP_DIR="$APP" PYTHONDONTWRITEBYTECODE=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  nice -n 10 timeout 7500 "$PY" scripts/forced_drop_fix_replay.py --box \
    --archive "$ARCHIVE" \
    --archive-sha256 f660098f3c68eee3be24790d7674bd263616d4c97d330e92c24ed77d5dd6078e \
    --expect-member-sha256 8e9b826a3a148bbb17636aec79b46eefe3e9138940976959c4342dc4774b198a \
    --csv-root "$WORK/csvtree" --csv-rev "$CSV_REV" \
    --csv-tree-sha256 31687c60b2adc9f347eb58c8da2e15a1198a264d3b98200b1db3fa5f2345bd54 \
    --expect-code-sha "$CODE_SHA" \
    --expect-board-sha256 eed8df11637b17076b4d1aa10ff1c8bf2190cc08afa57e12e0ddc2fa5c290833 \
    --max-mem-gib 4 --max-cpu-seconds 5400 --wall-seconds 7200 \
  > "$WORK/out/forced_drop_box_replay.json" 2> "$WORK/out/stderr.txt" || RC=$?
echo "exit=${RC:-0}"
```

* **Expected duration.** Several times the local ~5 minutes (about 8 – 15 minutes on a development machine for these designs without Component B; allow up to 40 minutes on the box): the real Component B lens, the
  Component B census and the stress census each re-decide the census trades. The caps are 90 minutes of CPU and 120
  of wall clock; exceeding the wall-clock or memory cap stops the run (exit 5) and nothing is printed; a CPU-cap kill (SIGXCPU) ends the process by signal instead, also with nothing printed.
* **Optional smaller run** (to rehearse, same pins): add `--war-room-opps 2 --census-per-shape 2 --skip-finder`. Its
  numbers are not comparable with §5; the exit code, the pins and `readOnlyGuard` are.
* **Exit codes:** `0` ok · `2` an input pin or argument was refused (stderr names the pin and prints the observed
  digests; nothing measured) · `3` the guard refused a write or process start · `4` the report was refused as not
  aggregate-only (stderr names the path, never the value; nothing printed) · `5` a resource cap stopped the run.
  Anything but `0` means **no result** — do not retry with a looser cap or a different pin without the coordinator.

## 4. After the run

1. The run printed `exit=0` and `"$WORK/out/stderr.txt"` is empty (the guard's refusals are counted in the report,
   not printed).
2. `sha256sum "$WORK/out/forced_drop_box_replay.json"` — send the digest to the coordinator with the file.
3. Check the file locally is **only** aggregates: `python3 -c "import json;json.load(open(f))"`; the in-run check has
   already refused anything else, so this is a second look, not the safeguard.
4. Hand the single file `forced_drop_box_replay.json` to the coordinator (not the scratch tree, not stderr unless
   non-empty).
5. Clean up: `rm -rf "$WORK"` (the scratch directory the guard created under it is already deleted at exit).
6. Do not copy anything else off the box: no `data/`, no rosters, no logs.
7. Do not re-run to "fix" a number. A different result on a re-run is a finding, not noise.
8. **Coordinator:** compare with §5–§6, then commit the file as
   `docs/trade/evidence/forced_drop_fix_2026-10-20/box_replay.json` in a normal PR with the date and the digest in the
   message, and add the §5 comparison to the record. Do not change a flag default in that PR.

## 5. What to compare (local replay values; the box result is expected to differ only through §1's additions)

Paths are into `forced_drop_box_replay.json`. "Local" is the committed `replay.json` (archive `20261020_052241`, CSV tree
`d5236546f`, `fairness_bands_v2`, flag OFF vs ON, A-driven headline).

| field | local V5 | local V5-R | what the box tells us |
|---|---:|---:|---|
| `provenance.pinsMatch` | — | — | `true` (else the run did not happen) |
| `provenance.builtBoardSha256` / `csvTreeSha256` / `archiveSha256` | `eed8df11…` / `31687c60…` / `f660098f…` | | identical (they are pins) |
| `fairnessBands.version` · `packageModel.id` | `fairness_bands_v2` · `geom_q078_v1` | | identical |
| `scarcityObserved.inert` · `.min` · `.max` | `true` · 1.0 · 1.0 | | **`false`**, spread inside 0.85–1.15 — otherwise the box did not resolve scarcity and the run is not the test it was prepared for |
| `warRoom.analyzeVerdicts.publicCategoryChanged` (V5) · `warRoom.analyzeVerdictsRosterRational.…` (V5-R) | 109 | 105 | with real scarcity; large moves are sensitivity (verdict analysis §8) |
| `census.counts.publicCategoryChanged` (V5) · `census.rosterRational.counts.…` (V5-R) | 125 | 127 | same |
| `census.counts.chargeChanged` / `.dropSetChanged` | 174 / 174 | 174 / 174 | |
| `census.chargeDelta.median` (min … max) | −1,691 (−3,490 … +1,271) | −1,664 (−3,490 … +1,354) | median charge shift |
| `warRoomChargeShift.V5` · `.V5-R` (`medianDelta`, `down`, `up`) | −2,131; 131 / 0 | −1,888; 131 / 0 | War Room median charge shift (of the 131 changed steps) |
| `census.chargeDeltaByKind` | `atOrUnderCap:down` 159, `overLimitBefore:up` 15 | same | the flag must still never raise a charge at or under the cap |
| `warRoom.analyzeVerdicts.currencyAnomaly` forward (`currencyAnomalies` / `selectionsReleasingAnAcquiredPiece`) | 49 / 65 | 0 / 20 | |
| … reverse (`reverseCurrencyAnomalies` / `selectionsReleasingExistingWhileKeepingAnAcquiredPiece`) | 0 / 134 | 0 / 134 | **the one the local replay could not test** (structurally 0 at scarcity 1.0) |
| `census.currencyAnomaly` forward / reverse | 36 / 70 · 0 / 167 | 0 / 34 · 0 / 175 | same |
| `currencyAnomalyDirections` | the four of the above in one place | | |
| `warRoom.v5VsRosterRational` (`dropSetDiffers`, `v5rChargeHigher`, `categoryDiffers`) | | 49, 49, 20 | |
| `census.v5VsRosterRational` | | 36, 36, 9 | |
| `warRoom.analyzeVerdicts.stepsWithAnUnpricedForcedDrop` (off → on) | 49 → 0 | 49 → 0 | |
| `census.counts.packageCreditClampApplied` · `.searchBoundExceeded` | absent (0) | absent (0) | absent or small; reported either way |
| `finder` (`meanOverlapAtK`, `teamsIdenticalTopK`, `totalTradesChargedOff` → `On`) | 0.854, 4, 9 → 66 | identical to V5 on 12 / 12 | the real Finder |
| `perfectDraft.comparedOffVsOn` / `identicalOffVsOn` | 11 / 11 (+1 error in both modes) | | must be identical |
| `componentBCensus.componentBState.off` | all "B unavailable: …no_projection_snapshot" | | **mostly "B available"** on the box; the headline distribution then reflects Component B voting |
| `componentBCensus.vsOff.V5.categoryChanged` · `.V5-R` | n/a (stand-in) | | the category changes with the real lens |
| `singleSourceStress.categoryDistribution` base vs stress | Census V5 FAVORABLE 111 → 12 | 103 → 9 | **how much of the favourable mix survives if the cheap single-source tail is not real, on real data** |
| `readOnlyGuard.refusedWriteOrProcessAttempts` | — | — | **0** |
| `readOnlyGuard.refusedNetworkAttempts` | — | — | the contract build's Sleeper lookups (3 per board build); expected |
| `peakRssMb`, `resourceCaps`, `elapsedSec` | — | — | recorded |

## 6. What would make the owner stop

Stop (do not activate the flag; send the finding to the coordinator) if any of these is true:

1. **Any reverse anomaly** (`reverseCurrencyAnomalies > 0`) in either mode, in any design. V5-R's reverse count is 0 by
   construction, so a non-zero V5-R value is an implementation defect; a non-zero V5 value is the real-scarcity currency
   problem the local replay could not see (record §3a). Either way the selection mode needs a new decision.
2. **A forward anomaly in V5-R** (`currencyAnomalies > 0` under `analyzeVerdictsRosterRational` / `census.rosterRational`):
   by construction 0.
3. **The flag raises a charge at or under the cap** (`census.chargeDeltaByKind` has an `atOrUnderCap:up`, or
   `warRoomChargeShift.*.up > 0`).
4. **Category changes that depend on the single-source tail.** If `singleSourceStress` shows the ON verdicts collapsing
   (the favourable count falling by more than half, as in the local stress) *and* the owner is not prepared to accept
   the cheap-tail values as real, the correction is not established — the verdict analysis' class A rests on it.
5. **`scarcityObserved.inert` is `true`**, or a multiplier is outside 0.85–1.15: the run did not test what it was for.
6. **`componentBCensus.componentBState` shows Component B unavailable on almost every trade**: the box did not
   resolve the lens; the headline is still the stand-in.
7. **A new evidence gap** appears with the flag ON (`evidenceGapTransitions` lists a gap the OFF side did not have,
   e.g. `forced_drop_charge_unavailable`) on more than a handful of trades.
8. **Category changes move by more than the sensitivity band** of the verdict analysis §8 (95 – 112 War Room, 122 – 130
   Census) without a stated cause — read as an unexplained effect, not a refinement.
9. **`readOnlyGuard.refusedWriteOrProcessAttempts > 0`**, a non-zero exit code, a pin mismatch, or the report being
   refused: the run is void.

## 7. Precautions

* Run **only** after the owner's written authorization (§0). This runbook is not authorization.
* The guard is not a substitute for care: run as the service user, from a directory the operator created, with nothing
  else deploying (a deploy or the 2-hourly refresh rewriting `data/` mid-run would change the live inputs — scarcity,
  roster state, projections — between the measurements; if one starts, let it finish and start again).
* One heavy process at a time; the run is `nice -n 10`, single-threaded BLAS, a **4 GiB** address-space cap (inside
  the process, and so also the safety margin if the box is small), a 90-minute CPU cap and a 2-hour wall-clock cap.
* The report goes into a **public** repository: only the single output file leaves the box; never paste stderr that
  contains a digest of something other than the pins; never copy `data/`, rosters, transactions or logs.
* No flag is changed, no service is restarted, no file in the application tree is written, no database is opened
  read-write, no network call is made by the replay.
* The same pinned command can be re-run later (new board) only by changing the pins together, with the coordinator.

## 8. Status

**Prepared. Not run. Requires owner authorization.**

Rehearsal on a development machine, NOT production and saying nothing about production data: the same mode, the same
pins (archive, CSV tree, built board) and the guard installed, with small designs (`--war-room-opps 1
--census-per-shape 1`, with and without `--skip-finder`; the Finder at `--finder-top-k 3`). Results: exit 0; the
pins matched; `readOnlyGuard.refusedWriteOrProcessAttempts` **0** and `refusedNetworkAttempts` **3**, all from
`api/data_contract.py` (the contract build's Sleeper lookup, as in the Phase 3 and low-value-asset box runs);
`scarcityObserved.inert` `true` and Component B "unavailable: no projection snapshot" on every trade (this machine has
neither; the box is expected to differ — that is the point of the run); peak RSS about 115 MB and 164 s for the small
designs including the Finder. A wrong archive pin was refused with exit 2 before anything was measured, and a
report containing an un-allow-listed digest was refused with exit 4 with nothing printed. The full-size designs
(`--war-room-opps 5 --census-per-shape 8`, the defaults) reproduce the committed local `replay.json` aggregates when run
without `--box` (re-run 2026-10-21 after the review fixes: zero differing values).
