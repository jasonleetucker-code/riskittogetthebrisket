# W1-03 / W1-04 — Wednesday 2026-09-09 capture runbook

**Authority:** owner decision recorded in
[`WEEK_1_LAUNCH_CONTRACT.md`](WEEK_1_LAUNCH_CONTRACT.md) § Named blockers —
a one-time Week 1 production capture on Wednesday 2026-09-09, *after waiver
processing is confirmed complete* and *before any NFL scoring begins*.

**Forbidden, restated so it travels with the procedure:** do not capture
before waivers settle; do not backdate; do not synthesize a snapshot; do not
weaken either acceptance criterion. The normal Thursday recurring timer is
preserved for future weeks — nothing here changes it.

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
W1-28 (FINAL state) is temporally unreachable by the Wednesday deadline and
W1-30 says "as temporally applicable".

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

The recurring Thursday timer still produces Week 2's capture on its normal
cadence. A missed Week 1 costs Week 1's evidence only.
