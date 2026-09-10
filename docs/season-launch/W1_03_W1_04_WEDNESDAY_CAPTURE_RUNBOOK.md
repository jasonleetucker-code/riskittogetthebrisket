# Week 1 final-five execution runbook (W1-03 / W1-04 / W1-27 / W1-28 / W1-30)

**Scope widened 2026-09-08.** This document started as the W1-03/W1-04
Wednesday capture procedure (§1-4 below, unchanged) and now also carries the
LIVE (§5), FINAL (§6) and final launch-tree (§7) sequences for the remaining
two rows and the closing verification row, so the whole final five has one
executable runbook rather than five separate investigations. Filename kept
as-is — it is linked directly from `WEEK_1_LAUNCH_CONTRACT.md` § Named
blockers and renaming it would break that reference for no benefit.

**Authority:** owner decision recorded in
[`WEEK_1_LAUNCH_CONTRACT.md`](WEEK_1_LAUNCH_CONTRACT.md) § Named blockers —
a one-time Week 1 production capture on Wednesday 2026-09-09, *after waiver
processing is confirmed complete* and *before any NFL scoring begins*.

**Forbidden, restated so it travels with the procedure:** do not capture
before waivers settle; do not backdate; do not synthesize a snapshot; do not
weaken either acceptance criterion. The recurring timer now fires every four
hours, while the capture script remains the authority that opens the real
schedule window and enforces the one-time Wednesday post-waiver guard.

This document exists so Wednesday is *execution*, not improvisation. Every
number below was measured on 2026-09-06, not assumed; each has its source
named so a stale one can be re-checked rather than trusted.

---

## 1. The window, measured

| bound | value | how it was measured |
|---|---|---|
| waivers complete | **~03:05 ET Wed 2026-09-09** | daily waiver batches on `dynasty_main` ran 03:02 / 03:01 / 03:01 / 03:11 ET on Sept 5 / 4 / 3 / 2 (Sleeper `transactions/1`, `type=waiver`, `status_updated`) |
| first Week 1 kickoff | **20:20 ET Wed 2026-09-09** (NE @ SEA) | nflverse 2026 schedule via `src.bdvm.schedule.fetch_schedule_rows`, 16 REG Week 1 games |

**Usable window: roughly 03:15 → 20:20 ET Wednesday — about 17 hours.**
It is wide. There is no need to run at 03:15, and running early buys nothing:
the archive is append-only and the FIRST capture for a
`(league, season, week, team, pregame)` tuple is the one that stands, so an
early run permanently consumes the slot with a staler roster. Aim for the
morning, not the boundary.

Week 1 does not end until **Mon 2026-09-14 20:15 ET** (DEN @ KC). That is why
W1-28 (FINAL state) is temporally unreachable until Week 1 actually concludes
and W1-30 says "as temporally applicable". (CORRECTED 2026-09-10: the
Wednesday 03:15-20:20 ET window above is the W1-03/W1-04 *pregame-capture*
window only — it does not bound W1-27, which §5 below can execute during any
genuine Week 1 LIVE window, Wednesday's NE@SEA or any later game.)

`daily_waivers = 1`, `daily_waivers_hour = 0`, `waiver_clear_days = 1`,
`waiver_day_of_week = 2`. **The hour field is not interpreted here.** Sleeper's
timezone semantics for `daily_waivers_hour` are not documented in this repo and
guessing them is the same class of error W1-23 is blocked on. The observable
check in step 1 replaces it entirely — observe the batch, do not compute it.

---

## 2. Order is load-bearing: capture FIRST, then prove

`deploy/backup/riskit-state-backup.sh:427` backs up `${DATA_DIR}/game_day`
through `backup_dir`, and `backup_dir` **skips a source that does not exist**
(`:342`, `log "skip dir (absent): ${src}"`). A skipped source is not a failure —
that guard is deliberate, so a not-yet-provisioned stream cannot turn the
retention proof red.

The consequence is the whole reason this ordering is written down: **run the
backup before the capture and you get a green retention proof with no
`game_day.tar.gz` in it.** It would look like success and prove nothing, and
W1-03 would have been "verified" against a generation that does not contain the
artifact the row is about.

    capture  →  data/game_day/ now exists  →  backup  →  game_day.tar.gz in the generation

---

## 3. Procedure

### Step 1 — confirm waivers are complete (observe, do not compute)

```
python3 - <<'PY'
import json, urllib.request, datetime, zoneinfo
LID = "1312006700437352448"          # dynasty_main
ET = zoneinfo.ZoneInfo("America/New_York")
txns = json.load(urllib.request.urlopen(
    f"https://api.sleeper.app/v1/league/{LID}/transactions/1", timeout=25))
pending = [t for t in txns if t.get("status") == "pending"]
waivers = sorted((t for t in txns if t.get("type") == "waiver" and t.get("status_updated")),
                 key=lambda t: t["status_updated"], reverse=True)
newest = datetime.datetime.fromtimestamp(waivers[0]["status_updated"] / 1000, ET)
print("pending:", len(pending))
print("newest waiver batch (ET):", newest)
print("now (ET):", datetime.datetime.now(ET))
PY
```

**Proceed only when BOTH hold:**

1. `pending: 0` — no claim is still queued, and
2. the newest waiver batch timestamp is **Wednesday 2026-09-09, after ~03:00 ET**.

A newest batch still dated Tuesday means Wednesday's has not run. Wait; do not
capture. This is the step the owner decision turns on, and it is the one that
must not be shortcut on a timetable.

### Step 2 — dry-run the capture (writes nothing)

Dispatch **`Game Day Capture (on-box)`** with `write` **unchecked** (the
default). It runs the real script on the box with `--dry-run` and reports
coverage plus whether the pregame window is still open.

Read the output for: every ACTIVE league resolved, Week 1 resolved, and the
window reported open. If the dry run reports the window CLOSED, stop — Sleeper
is already reporting scores and a `pregame` capture would be refused (exit 3),
which is correct behaviour, not a problem to route around.

### Step 3 — the authentic capture

Dispatch **`Game Day Capture (on-box)`** again with:

- `write` = **true**
- `capture_kind` = `pregame`
- `league` = blank (every ACTIVE league)

Exit codes: `0` captured (newly, or already was) · `1` a league failed ·
`2` nothing to do · `3` refused, window closed. The script is idempotent — the
archive refuses a duplicate tuple and reports it as an already-captured skip —
so a retry inside the window is safe.

**This is the W1-04 evidence.** Record the run URL, the exit code, and the
per-league captured counts.

### Step 4 — retention backup + restore proof

Dispatch **`Retention backup + restore proof`** with `run_backup` = **true**.

It runs the real production backup, then restores the retained artifacts into a
throwaway directory and verifies them. It never touches live state.

**This is the W1-03 evidence,** and only if the verified generation actually
contains `game_day.tar.gz`. A green run whose log says
`skip dir (absent): …/game_day` is a *failed* W1-03 regardless of its
conclusion — read the log, not the badge.

### Step 5 — promote the rows

Only after steps 3 and 4 both produced their evidence:

- **W1-04 → VERIFIED** — an authentic pre-kickoff Week 1 production capture
  exists, harvested before outcomes were known.
- **W1-03 → VERIFIED** — that capture is durably retained and the retention has
  been *restored and verified*, not merely written.

Then recount the literal `VERIFIED` rows mechanically and update the tally
block. Denominator stays 30.

---

## 4. What to do if the window is missed

Say so, and leave both rows unVERIFIED.

A Week 1 pregame observation is **perishable** — that is the stated reason
`src/ros/game_day_archive.py` exists. Once Week 1 is scored, the pre-event
state that produced any prediction is gone. It cannot be reconstructed, and a
snapshot rebuilt afterwards and labelled `pregame` is worse than a missing one
because nothing downstream could tell the difference. The script enforces this
itself (exit 3); do not work around it.

The four-hourly recurring timer continues to probe future schedule-derived
capture windows. A missed Week 1 costs Week 1's evidence only.


## 2026-09-07 timing reconciliation

PR #1263 replaced the Thursday timer with a four-hourly timer and a generic
30-hour pre-kickoff window. That generic window opens on Tuesday for Week 1
and does not itself establish Wednesday waiver completion. The explicit owner
instruction above still governs: the capture CLI now refuses a 2026 Week 1
pregame write outside Wednesday or without an observed terminal Wednesday
waiver batch after 03:00 ET and no pending claims. `--ignore-window` cannot
bypass this exception or the kickoff refusal. Dry-run preparation writes nothing.
Verify the actual installed timer after deployment. The script guard preserves
Wednesday timing independently of the timer cadence.

---

## 5. LIVE evidence — W1-27

**Owner methodology decision made, 2026-09-09: in-progress remaining
production is TIME-PRORATED** (Option A — pregame estimate scaled by the
fraction of an assumed game duration not yet elapsed since evidenced kickoff;
`src/ros/game_day_week.py`; see `docs/game-day/GAME_DAY_WEEK_RESOLVER.md`).
The row's own acceptance text asks for the LIVE state to be
"production-usable and update ... probabilities truthfully" — a truthful
prorated number satisfies that, and so does the narrower degraded state below
when evidence is genuinely missing. `LIVE_PROGRESS_UNAVAILABLE` (an
in-progress player's remaining could not be time-prorated for lack of
reliable kickoff/game-progress evidence) is the correct, honest answer when
that evidence is missing, not a blocker to VERIFIED — it replaces the retired
`OWNER_POLICY_REQUIRED` seam, which is now closed.

**Instrument:** `tests/e2e/specs/prod-auth/w1-16-game-day.spec.js`'s "the
page's numbers are the endpoint's numbers" test, dispatched via the existing
`.github/workflows/v1-authenticated-verification.yml` — the same instrument
that already produced W1-12/14/15/16/25/26's evidence. No new workflow.
Fixed 2026-09-08: the test previously assumed `/api/matchup/intel` still
refuses a started week with HTTP 409 (`WeekInProgress`), which was true
before #1271 shipped `resolve_scoring_week` and is dead code today — the
endpoint now resolves and returns live/final state instead of refusing. The
test now branches on `body.mode` / `body.probabilityState` and asserts the
real shape (score, lineup, and one of the three truthful probability states)
instead of a refusal that can no longer happen.

### Procedure

1. Confirm a real NFL game covering at least one rostered player in the
   target league is actually **underway** — not merely "the calendar says
   Week 1 has begun". `week_has_begun` (`src/ros/game_day_week.py`) reads
   Sleeper's own scores, so the safest external check is the same one: any
   nonzero score on `GET https://api.sleeper.app/v1/league/<id>/matchups/1`.
2. Dispatch **`v1-authenticated-verification.yml`** (`workflow_dispatch`,
   default inputs — runs both the API and browser Playwright halves).
3. Download the `prod-auth-results.json` and `prod-auth-browser.txt`
   artifacts from the run.
4. Find the `w1-16-game-day.spec.js` → "the page's numbers are the
   endpoint's numbers" result and read its annotations:
   - `w1-27-mode` — must read `live` (still `pregame` means the window has
     not actually opened yet from the endpoint's perspective; wait and
     re-check step 1).
   - `w1-27-probability-state` — one of `AVAILABLE` / `LIVE_PROGRESS_UNAVAILABLE`
     / `GAME_STATE_OR_SCORING_UNAVAILABLE` / `UNAVAILABLE`.
   - `w1-27-branch` — the exact truthful state the run observed, in prose.
5. Test **PASSED** with `w1-27-mode: live` → the row's acceptance text is
   satisfied by whatever truthful state was observed. **W1-27 → VERIFIED.**
   Record the run URL, the two annotation values, and the timestamp as the
   row's evidence.
6. Test **FAILED** → read exactly what failed (a fabricated number, a
   missing label, a crash) before touching the row. That is a real defect in
   the LIVE path, not evidence to discard — fix it, validate, redeploy, and
   re-dispatch. Do not promote on a red run.

## 6. FINAL evidence — W1-28

Same instrument as §5, same test. **Only reachable once Week 1 has actually
finished** — measured 2026-09-06 from the real schedule at
Monday 2026-09-14 20:15 ET (DEN @ KC, see "THE WEEK 1 CLOCK" above), five
days after this contract's Wednesday 2026-09-09 23:59 CT deadline. This
section exists so the sequence is ready to execute the moment that real state
exists; it is not expected to run before the deadline, and the contract
already records W1-28 as temporally unreachable by then.

### Procedure

1. Confirm the applicable matchup is genuinely over — every rostered player
   relevant to the matchup reports `state: "completed"`, or the host
   otherwise reports the week as final.
2. Dispatch `v1-authenticated-verification.yml` again.
3. Read the same test's `w1-28-branch` and `w1-28-recap` annotations (and
   `w1-27-mode`, which should now read `final`).
4. Test **PASSED** with `w1-28-branch: "final — result WIN/LOSS/TIE"` →
   **W1-28 → VERIFIED.** Record the run URL, the result, and whether a recap
   URL was present (the recap article itself is a separate, already-VERIFIED
   pipeline — W1-06/W1-09 — this only checks the link renders).
5. Test **FAILED** → same rule as §5 step 6: root-cause and fix before
   promoting anything.

## 7. W1-30 — final launch-tree verification

Not a generic "the deploy workflow was green" checkbox. The row asks for
archive capture (W1-01-04), all six pregames (W1-05-13), the private owner
experience (W1-14-16), and Game Day scheduled/live/final "as temporally
applicable" (W1-17-28) to all be true **together, on one production tree**.

### Procedure

1. Mechanically recount `docs/season-launch/WEEK_1_LAUNCH_CONTRACT.md`.
   Confirm every row through W1-26 is already `VERIFIED`, plus whichever of
   W1-03/W1-04/W1-27/W1-28 this runbook's earlier sections have promoted by
   this point.
2. Record the exact deployed production SHA: `ssh <prod> "cd <APP_DIR> && git
   rev-parse HEAD"`, or read it from the most recent successful `Deploy
   Production` workflow run's summary.
3. Dispatch `v1-authenticated-verification.yml` **one final time** against
   that same SHA — a W1-30 promotion must rest on one verification pass, not
   evidence pieced together from separate historical runs against different
   deployed trees.
4. Confirm zero unexpected failures in `prod-auth-results.json`. The two
   `v1-123-*` mobile-only failures noted in the contract's
   "Row movements, 2026-09-06 (second)" section are the one known,
   out-of-scope exception — re-confirm they are still exactly those two and
   still unrelated to any Week 1 row before excluding them; a new failure
   anywhere is not automatically the same known issue.
5. "As temporally applicable" governs W1-27/W1-28 specifically: if Week 1 is
   still live or has not started at verification time, W1-30 promotes on the
   subset that IS temporally applicable (scheduled, and live if live evidence
   already exists) — it does not wait for a FINAL state the clock has already
   ruled out by the deadline.
6. **W1-30 → VERIFIED** only when every temporally-applicable component above
   is confirmed together in this one pass against the one recorded SHA.
7. Recount the full 30-row contract mechanically and update the tally block
   in the same bounded change.
