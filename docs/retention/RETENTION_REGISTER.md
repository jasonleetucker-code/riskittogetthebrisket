# Retention Register — C1A irreversible-evidence streams

**Status:** live record for the authorized C1A tranche `C1-RET-01`…`C1-RET-08`.
**Authorization:** `docs/EXECUTION_PLAN.md` (C1A unit 1 only).
**Scope definition:** `docs/C_SERIES_SCOPE_MANIFEST.md` rows `C1-RET-01`…`C1-RET-08`.

---

## Production evidence — 2026-08-15

Deployed as merge `47d7d243` (validated head `ef76a425`), deploy run `31869441040` SUCCESS.

**FINAL strict `ALL` watchdog, run `31916149679`, 2026-08-16T00:00:29Z**, against the production data
directory. Growth columns are against the 06:48:36Z reading (`31870347342`), because two probes far apart
show a store is being *written to* — a single probe only shows it is non-empty:

| row | state | age | measured artifact | 06:48 → 00:00 |
|---|---|---|---|---|
| `C1-RET-01` | `ok` | 2.6 h | 2 accumulator files, **1,128 deduped rows** | 1,092 → 1,128 |
| `C1-RET-02` | `ok` | 24.0 h | **10,934 rows across 10 dates** | 9,842 / 9 dates → 10,934 / 10 |
| `C1-RET-03` | `ok` | 24.0 h | 27 snapshots, missingDays=0, **staleDays=1** | 27, staleDays 0 → 1 |
| `C1-RET-04` | `ok` | 0.1 h | **90 observations of 2 distinct cards across 2 leagues** | 4 → **90** |
| `C1-RET-05` | `ok` | 0.1 h | **4,500 observations across 45 snapshots** | 200 / 2 → **4,500 / 45** |
| `C1-RET-06` | `ok` | 0.1 h | **288 transactions, 288 trades, 4 leagues** | 285 → 288 |
| `C1-RET-07` | **`stale`** | **2,812.2 h** | 177 artifacts; newest `identity_report_20260420T194828Z.json` | still stale, +17.2 h |
| `C1-RET-08` | `ok` | 120.0 h | **2 snapshots**, newest `snapshot_2026-08-11.json` — **both now published off-box** | see below |

`ok=7 stale=1 missing=0 unknown=0` — **exit code 2**. The watchdog can fail, and did, on a genuinely stale
stream. It has **not** been weakened to obtain green; this is the same exit code it returned at 06:48, and
`C1-RET-07` is the same stale row.

**Six streams are demonstrably still accumulating.** `C1-RET-05` went 200 → 4,500 observations and
`C1-RET-04` 4 → 90, entirely on their own timers with no writer invoked by hand.

`C1-RET-02`'s 10,934 rows is the same number the restore proof counted inside the restored
`board_history.sqlite` — the health probe reads the live store and the proof reads a decompressed copy of the
backup, so the two agreeing is evidence the backup captured the live state rather than an older one.

**`C1-RET-08` did not move, and that is expected, not a stall.** Its producer is weekly
(`OnCalendar=Tue *-*-* 05:40 UTC`); `2026-08-11` was the most recent Tuesday. `staleDays`/`missingDays` from
`store.history_coverage()` are plain calendar-day counts — the shape `rank_history.coverage` uses for a DAILY
artifact — so on a weekly store they are non-zero even when healthy and must not be read as a halted producer.
The real defect on this row is publication, not production; see `C1-RET-08` below.

**Backup + restore.** The first real proof run (`31870387349`) **FAILED**, and refusing to claim success is
what it is for. All six retention artifacts were written —

```
sqlite ok: data/retention/evidence.sqlite
sqlite ok: data/retention/league_events.sqlite
sqlite ok: data/board_history.sqlite
file   ok: data/rank_history.jsonl
dir    ok: data/faab
dir    ok: data/identity
```

— but two directory archives errored and the script discarded the whole generation, all 14 artifacts:

- **`tar: playerctx_history: Cannot stat`** — the archive label added for `data/playerctx/history` was passed
  to tar as the *member* name. Introduced by this tranche.
- **`tar: intel/ledger.sqlite3-wal: file changed as we read it`** — GNU tar exits 1 for that and 2 for a fatal
  error; the script treated them alike, so one busy directory threw away every other artifact. **Pre-existing**,
  and it means the nightly generation has been at risk of discard whenever `intel` was being written.

Both fixed in #849 (`ce5e6128`), pinned by `tests/deploy/test_state_backup_dir_archiving.py`, which runs the
shipped `backup_dir` including a real write-while-tarring race.

**Five proof runs, and what each one settled:**

| run | result | what it established |
|---|---|---|
| `31870387349` | FAIL, 2 errors / 14 artifacts | both defects, and that all six retention artifacts write cleanly |
| `31871813972` | FAIL, 1 error / 15 artifacts | `intel` passed (race did not fire); `playerctx_history` failed identically → the box was still running the pre-#849 script |
| `31872429488` | FAIL | same shape, ~57 s — deploy of `ce5e6128` still had not landed |
| `31872681688` | FAIL — **backup succeeded, proof looked elsewhere** | the writer promoted 16 artifacts into the FALLBACK root and the proof read the empty primary. Two independent implementations of "where is the backup". Fixed by #852 (merge `a0feb1e04`) giving the question ONE owner, `deploy/backup/backup_root_lib.sh` |
| **`31906622971`** | **SUCCESS, exit 0** | **the first proven backup + isolated restore on production** |

The retention artifacts wrote successfully on **every** run. What failed was, in order, the archiving of two
directories (#849) and then the agreement between the writer and the reader about which root held the result
(#852).

### Run `31906622971` — 2026-08-15T20:25:20Z–20:26:14Z, `RUN_BACKUP=1`

Deployed revision at the time of the run: merge **`a0feb1e04`** (PR #852), deploy run `31905743421` SUCCESS,
both jobs green.

| fact | measured value |
|---|---|
| effective backup root | `/home/<deploy-user>/backups/riskit-state` — **fallback** |
| primary root | `/var/backups/riskit-state` — not writable by the deploy user |
| exact generation proven | `…/backups/riskit-state/daily/2026-08-15` |
| generation size | 125 M |
| artifacts in the generation | **16** |
| retention artifacts restored **and verified** | **7** |
| restore target | `/tmp/retention-restore-3fvx4i` (throwaway; no path under `DATA_DIR` written) |
| exit code | **0** |

The generation was not searched for. The writer recorded its own result at `/tmp/retention-backup-result-*`
and the proof verified **that** generation — `[state-backup] effective backup root:` and
`[backup-proof] effective backup root:` name the same path in the same run. That agreement is the whole point
of #852, and it is now observed in production rather than argued from tests.

**What was restored and checked, from the restored copies rather than the live originals:**

| row | artifact | verification |
|---|---|---|
| `C1-RET-04` / `C1-RET-05` | `evidence.sqlite` | 733,184 B from 84,273 compressed; `PRAGMA integrity_check = ok`; `schema_version = 2`; `scoring_card_observations` 50, `scoring_card_payloads` 2, `trending_observations` 2,500 |
| `C1-RET-06` | `league_events.sqlite` (**PRIVATE**) | 282,624 B from 41,880; `integrity_check = ok`; `schema_version = 1`; `league_transactions` **287** — schema, counts and version only. No payload, manager name or roster reached the log |
| `C1-RET-02` | `board_history.sqlite` | 3,555,328 B from 686,240; `integrity_check = ok`; `schema_version = 1`; `board_history` **10,934** rows |
| `C1-RET-03` | `rank_history.jsonl` | `gzip -t` ok, 27 lines, **27 parseable / 0 unparseable** |
| `C1-RET-01` | `faab/` | 2 files restored — archive listed 2, source holds 2 |
| `C1-RET-07` | `identity/` | 177 files restored — archive listed 177, source holds 177 |
| `C1-RET-08` | `playerctx history/` | 2 files restored — archive listed 2, source holds 2 |

> **WHAT THIS RUN DOES NOT PROVE.** It exercised the **deploy user's FALLBACK lineage**, and the tool said so
> itself rather than leaving it to be inferred:
>
> ```
> [backup-proof][WARN] this proves the backup lineage written by <deploy-user> into the FALLBACK root.
> The nightly systemd job runs as root and writes /var/backups/riskit-state; those generations are not
> readable here and are NOT covered by this run.
> ```
>
> A green tick here must not be read as "the nightly's backups restore". See **The nightly lineage** below —
> that is a separate fact with separate evidence, and it is not established by this run.

### The nightly lineage — installed 2026-08-16, armed, exercised

The C1A state-backup line did not exist on production. Not stale — **absent**: no
`riskit-state-backup` unit, neither file under `/usr/local/lib/riskit/`, no
`/var/backups/riskit-state`. The registry corroborated it against a rename
(`riskit-backup.*` and `riskit-backup-restore-test.*` are enabled and are an
older, separate 3-database line, left untouched). So the seven retention
artifacts were covered by no scheduled job at all; the only backups that existed
were the ones a dispatched proof run created.

It could not be installed the canonical way. `deploy/apply_hardening.sh` needs a
full root shell, and the deploy account's NOPASSWD sudo is exactly
`systemctl / journalctl / install / chown` — **no `bash`** (preflight run
`31910753511`). That installer also rewrites the nginx site config, which can
silently revert certbot's TLS edits, so the price of a backup timer was a human
root session plus the one step with real blast radius.

`deploy/backup/install_state_backup.sh` now **owns** the four steps, and
`apply_hardening.sh` sources it rather than carrying a copy — two definitions of
"which files, in which order, with which modes" drift, and drift here installs a
writer without the library it hard-fails without. Bounded install run
**`31915897174`**, exit 0:

| fact | measured |
|---|---|
| `riskit-state-backup.timer` | `UnitFileState=enabled`, `ActiveState=active`, `Persistent=yes` |
| next elapse | **Sun 2026-08-16 04:30:00 CEST = 02:30 UTC** — the intended nightly |
| `ExecStart` | `/usr/local/lib/riskit/riskit-state-backup.sh` — the root-owned copy, **not** the deploy-user-writable checkout |
| manual oneshot | `Result=success`, `ExecMainStatus=0`, 35 s wall / 40 s CPU |

> **A MANUAL ONESHOT IS NOT A NIGHTLY FIRING, and this register will not say it
> was.** Starting the unit proves the *installed service path executes*. The
> timer being `enabled`/`active` with a next elapse at 02:30 UTC proves
> *scheduling is armed*. Those are two facts and neither is the other. No
> natural 02:30 firing has been observed; the first is due 2026-08-16.
>
> **What is still unmeasured:** the writer logs to
> `/var/log/riskit-state-backup.log` rather than the journal, and its generation
> lands under root-owned `/var/backups/riskit-state`. Neither is readable by the
> deploy account, so the effective root, generation and artifact count *for this
> lineage* are **not** evidenced here. The 35 s runtime is consistent with a real
> backup and is not proof of one. The fallback lineage's generation is fully
> evidenced above; do not read one as the other.

---

## What this document is

The eight rows in this tranche share one property that no other work in the
plan has: **deferring them does not postpone the work, it loses the
evidence.** A rolling source window turns over, an overwrite lands, a timer
quietly stops — and the thing that was true yesterday becomes unknowable
rather than merely unrecorded.

So every retained artifact needs an answer to eight questions before it counts
as retained, and this file is where those answers live. A store with no named
backup is not durable; a store with no health signal is not observable; a
store with no restore method is a backup nobody has proven.

**Four of these questions are about failure, not success.** "Where is the
backup", "how do I restore it", "what tells me it stopped" and "who is allowed
to read it" are the ones that go unanswered until the day they matter.

## The privacy rule, stated once

**Durable does not mean committed.** Every store below lives under `data/`,
which is gitignored, and is made durable by
`deploy/backup/riskit-state-backup.sh` — an on-box nightly with optional
off-box mirroring to the operator's own destination. None of them may be
force-added into public Git history, and the `private` ones may not reach any
`/api/public/*` surface. The B8 public/private boundary is semantic, not a
field-name denylist: factual retrospective league content is publishable only
through the public-league surfaces, which build from their own snapshots.

`C1-RET-06` is in a **separate database file** from `C1-RET-04` / `C1-RET-05`
for exactly this reason — so that "back this up" and "publish this" can never
be the same gesture by accident.

---

## `C1-RET-01` — KTC crowd-FAAB rolling window

| | |
|---|---|
| **Primary store** | `data/faab/crowd_history_<leagueKey>.json` |
| **Backup** | `riskit-state-backup.sh` → `dirs/faab.tar.gz` (nightly, guarded) |
| **Write owner** | `scripts/fetch_crowd_faab.py` → `src/trade/faab_history.py::merge_crowd_rows` |
| **Read owner** | `src/trade/faab_engine.py` market layer (rival engagement only — never the objective ceiling) |
| **Retention** | indefinite; accumulates, never truncates |
| **Privacy class** | **private** — `data/faab/` also holds `bid_history_<leagueKey>.json`, our own leagues' claim history |
| **Restore / replay** | restore the tarball. **Not re-fetchable**: KTC's waiver database is a ~5-day / ~200-row rolling window, so any day not captured is gone. A restore recovers the accumulator; nothing recovers a gap. |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-01`; budget 6 h (scrape cadence × 3) |

**Why it was at risk.** The accumulator and its timer both existed and worked —
the merge is idempotent (existing-wins, `firstSeenAt` preserved) and cannot
truncate (it exits 2 before writing when a fetch returns nothing). What was
missing was durability: the output is gitignored (`.gitignore:48`), absent from
`scheduled-refresh.yml`'s force-add list, and was absent from **both** backup
scripts — including the one whose header claims to cover "all irreplaceable
production state". A working accumulator with no backup is one disk away from a
season of crowd evidence that cannot be re-fetched.

**Fixed by** adding `data/faab` to the nightly backup and giving it a health
probe. No change to the fetcher or the merge — they were already correct.

---

## `C1-RET-02` — canonical board history

| | |
|---|---|
| **Primary store** | `data/board_history.sqlite` |
| **Backup** | `riskit-state-backup.sh` → `sqlite/board_history.sqlite.gz` (online backup, `PRAGMA integrity_check`ed) |
| **Write owner** | `scripts/snapshot_board.py` → `src/snapshots/board_store.py::write_board` |
| **Read owner** | operators and tests only (`coverage()`). **No decision path may read it** — a value that fed back into the board it records would make every measurement from it circular |
| **Retention** | indefinite; one row per `(as_of, player_key, contract_version)` |
| **Privacy class** | internal |
| **Restore / replay** | restore the gz, verify with `PRAGMA integrity_check`. **Not reconstructible**: the board it records was computed and discarded |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-02`; budget 48 h |

**Why it was at risk.** PROOF-REQUIRED, not broken. The recorder is correct and
its own docstring states the stakes — "every day it is not running is a day of
evidence that cannot be recovered later" — but whether it is *scheduled* was
unobservable from anywhere except the production host. `coverage()` had **zero
consumers**.

**Fixed by** giving `coverage()` a consumer that runs on a schedule and can
fail, plus backup coverage.

---

## `C1-RET-03` — rank history log

| | |
|---|---|
| **Primary store** | `data/rank_history.jsonl` |
| **Backup** | `riskit-state-backup.sh` → `files/rank_history.jsonl.gz` (nightly, guarded) |
| **Write owner** | `src/api/rank_history.py::append_snapshot`, called from `server.py` on **fresh scrape promotions only** |
| **Read owner** | `stamp_contract_with_history` (the /rankings history glyph) |
| **Retention** | capped by the caller's retention argument; append-only within it |
| **Privacy class** | internal |
| **Restore / replay** | restore the gz. Partially reconstructible for recent dates via `scripts/backfill_rank_history.py` from `data/dynasty_data_*.json` (45-day window), which is a **reconstruction, not the original observation** |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-03`; budget 48 h. `coverage()`'s `missingDays` is the gap detector; `staleDays` catches a stall in progress |

**Why it was at risk.** The append is best-effort and deliberately swallows its
own exception, so a write failure is invisible to the response and silent in
practice. Single copy, no backup.

**Fixed by** backup coverage and a health probe that reads the existing
`missingDays` / `staleDays`. The best-effort posture is **kept** — a history
write must not break the contract response — but it is no longer unobserved.

---

## `C1-RET-04` — scoring card history

| | |
|---|---|
| **Primary store** | `data/retention/evidence.sqlite` → `scoring_card_observations` + `scoring_card_payloads` |
| **Backup** | `riskit-state-backup.sh` → `sqlite/evidence.sqlite.gz` |
| **Write owner** | `src/retention/evidence_store.py::observe_scoring_card`, called from `league_registry.write_scoring_snapshot` **before** its overwrite |
| **Read owner** | operators, tests, `scoring_card_at()`. No decision path — the live W18-F001 gate keeps reading `data/leagues/scoring_<id>.json`, unchanged |
| **Retention** | indefinite; one row per **actual observation**, plus one payload row per distinct card |
| **Privacy class** | internal |
| **Restore / replay** | restore the gz. **Not reconstructible** — Sleeper serves the current card only |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-04`; budget 6 h |

**Why it was at risk.** ABSENT BY CONSTRUCTION, and literally so:
`write_scoring_snapshot` ends in `tmp.replace(path)`, so every refresh destroyed
the previous card. "What was this league scoring on 2026-03-01" was a question
the platform could not answer about its own past — and any retrospective
scoring a historical week under today's card silently measures the wrong league.

**Design note — observations are the storage; continuity is derived.** The
manifest's acceptance wording is "append-only history keyed by
(league, observed_at)", and that is exactly what is stored: one row per **actual
observation**. Nothing is merged or bridged at write time, because the write
path cannot know what happened while it was not looking.

> **An earlier draft stored intervals and owner review rejected it.** One row
> per distinct card, extended whenever a later observation matched the same
> hash — so `Jan 1: A` … *(a month with no observations)* … `Feb 1: A` produced
> a single window `Jan 1 → Feb 1` and answered "the card on Jan 15?" with **card
> A, fidelity `exact`**. That is not justified: during the unobserved month the
> true history could have been `A → B → A`, or collection could simply have been
> dead. A matching hash across a gap is not evidence of continuity.
> **UNOBSERVED MUST REMAIN UNOBSERVED.** Pinned by
> `test_a_same_card_observation_gap_is_not_exact`.

Recording every observation is cheap because the payload is **content-addressed**
in `scoring_card_payloads` and each observation stores only its hash.
Deduplicating identical *content* under its own hash loses no evidence — the hash
*is* the identity — while deduplicating *observations* would lose exactly the
evidence that decides fidelity. That is the smallest representation that
preserves the evidence.

`scoring_card_windows()` still reports runs of agreeing observations, but they
are **derived, never stored**, and each carries `maxGapHours` — the widest
unobserved span inside it. A window of two observations a month apart reads as
exactly that, never as a month of coverage. `A → B → A` is three windows.

**Fidelity is explicit and `exact` is the strict default.** `scoring_card_at()`
takes an `accept` tuple and returns nothing beyond `exact` unless a caller opts
in:

| fidelity | supported by |
|---|---|
| `exact` | an observation **at that instant** — never "the endpoints matched" |
| `reconstructed` | the observations immediately before and after both exist, are both **readable**, and **agree**; `bracketGapHours` states how wide the unobserved span is |
| `nearest_prior` | only a prior observation exists, **or** the bracketing pair disagree so the instant is genuinely indeterminate; bounded by `coverageGapEndsAt` |
| *(none)* | `None` — including when an observation is there but its payload is not |

An unknown fidelity name in `accept` **raises** rather than returning `None`: a
typo that reads as "no evidence" is indistinguishable from the store genuinely
having nothing, which is the confusion this whole surface exists to remove. A
bare string is refused for the same reason — `"exact" in "exact"` is true by
substring, so `accept="exact"` would quietly behave like a tuple.

**Contradicting evidence is refused, not absorbed.** Two different cards
reported for one instant is not a replay: at most one can be true and the store
cannot tell which. `observe_scoring_card` returns `action: "conflict"`, writes
nothing, and reports the hash actually on file alongside the one it declined.

**Reads take one snapshot and cannot fail open.** Both bracket endpoints are
read inside one transaction, so a write landing mid-read cannot produce a
bracket whose halves never coexisted. The payload join is a `LEFT JOIN`
deliberately: an inner join made an observation with a missing payload *vanish*,
and vanishing fails **open** — drop the middle of a disagreeing A / B / A and
the surviving endpoints agree, turning an indeterminate question into a
confident `reconstructed`. That is the invent-continuity defect arriving through
a different door.

**There is deliberately no gap threshold anywhere in the module.** A "gaps under
N hours bridge" rule would be a magic number standing in for a cadence guarantee
this platform does not have — the recorder is best-effort, the scrape cadence
drifts, and the whole reason the row exists is that collection stops silently.
The read path reports the bracket and its width; the caller applies its own
standard.

**No value of `accept` returns today's card for a historical date.**
`nearest_prior` looks strictly backwards, and a later observation can only
contribute as one endpoint of an *agreeing* bracket — never as a standalone
answer about the past.

---

## `C1-RET-05` — Sleeper trending-adds series

| | |
|---|---|
| **Primary store** | `data/retention/evidence.sqlite` → `trending_observations` |
| **Backup** | `riskit-state-backup.sh` → `sqlite/evidence.sqlite.gz` |
| **Write owner** | `src/retention/evidence_store.py::observe_trending_snapshot`, called from `server.py`'s post-scrape warm worker (off the request path, cache read — **no second round-trip**) |
| **Read owner** | operators and tests (`trending_series`). The FAAB market layer keeps reading the live adapter, unchanged |
| **Retention** | indefinite; one row per `(source, snapshot fetchedAt, player)` |
| **Privacy class** | internal — Sleeper's public trending feed, no league or user identity |
| **Restore / replay** | restore the gz. **Not re-fetchable**: the endpoint serves a rolling lookback window, not history |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-05`; budget 6 h |

**Why it was at risk.** ABSENT. `src/adapters/sleeper_trending.py` holds a
15-minute TTL cache and persists nothing, so the waiver-heat series has never
existed. The FAAB market layer already treats trending as demand evidence;
without a series there is no way to ask whether demand led or lagged a value
move.

**Idempotence.** Keyed on the snapshot's own `fetchedAt`, so re-recording the
adapter's cached snapshot collides on the primary key and writes nothing. The
adapter caches for 15 minutes and the scrape runs every 2 h, so a cached
snapshot *will* be offered more than once — dedupe is structural rather than a
matter of caller discipline.

---

## `C1-RET-06` — own-league transaction ledger

| | |
|---|---|
| **Primary store** | `data/retention/league_events.sqlite` → `league_transactions` |
| **Backup** | `riskit-state-backup.sh` → `sqlite/league_events.sqlite.gz`. On-box; off-box only to the operator's own configured rsync destination |
| **Write owner** | `src/retention/league_events.py::record_transactions`, called from `sleeper_overlay._build_trades_block` **before** its window cutoff |
| **Read owner** | nothing yet, by design. Trade History is **not authorized** — this keeps the option open, it does not open it |
| **Retention** | indefinite; one row per `(sleeper_league_id, transaction_id)` |
| **Privacy class** | **private** — real managers, real rosters, real trades |
| **Restore / replay** | restore the gz. **Not re-fetchable once Sleeper's own feed rolls past it** |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-06`; budget 48 h. `transaction_coverage()` reports counts and stamps only — **never payloads**, so checking liveness cannot move the privacy boundary |

**Why it was at risk.** PARTIAL, in two independent ways. The live path fetches
a **365-day rolling window** across a depth-2 league chain, and it emitted no
`transaction_id` at all — so a trade older than the window stopped being
fetched, and nothing downstream could say "this is the same trade I saw last
week". `docs/TRADE_HISTORY_AGING_SPEC.md` needs Current Grade, At-the-Time
Grade and How It Aged; none are reachable from a window that forgets.

**Capture point is load-bearing.** Recording happens **before** the
`window_days` cutoff, because that cutoff is *ours*, not Sleeper's: the fetch
still returns trades older than it, and our filter is the only reason they are
discarded. Capturing ahead of the cutoff, ahead of the `seen` dedup, and with
the raw payload intact is the difference between a recoverable history and a
permanently lost one.

**Why the whole payload.** Extracting only what today's consumer needs is how
the live path lost `transaction_id` in the first place.

---

## `C1-RET-07` — identity resolution evidence

**Repointed 2026-10-07 (#1676).** The stream now has TWO stores with different
contracts, and only the live one is graded for freshness.

| | live stream (graded) | legacy archive (frozen) |
|---|---|---|
| **Store** | `data/scrape_state/identity_dual_read.json` | `data/identity/identity_{resolution,report}_*.json` |
| **Write owner** | `Dynasty Scraper.py` — the C1-ID-01 dual-read record, rewritten every scrape cycle by the canonical identity owner (`src/identity/resolution.py`) | **none** — `scripts/identity_resolve.py` (retired Jenkins pipeline) last ran 2026-04-20; retired by #173 |
| **Freshness stamp** | the record's own `generatedAt` (never mtime — the file is git-tracked and a checkout rewrites mtime) | filename date, reported for information only |
| **Freshness budget** | `SCRAPE_BUDGET_H` (6 h) — the scrape cadence rule, because the scrape writes it | **none** — no producer exists, so no SLA can be met |
| **Retention** | the newest record on the box; every refresh commit keeps its history in git | **indefinite**: git-tracked, backed up nightly, never deleted |
| **Backup** | git history (`scheduled-refresh.yml` force-adds `data/scrape_state/`) | `riskit-state-backup.sh` → `dirs/identity.tar.gz` |
| **Read owner** | `scripts/identity_parity.py`; this probe | `GET /api/scaffold/identity` (private-auth, age-labelled) |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-07` state | `C1-RET-07.legacyArchive` (`state: frozen`, artifact count, newest, age) |
| **Privacy class** | internal | internal |
| **Restore / replay** | `git show <sha>:data/scrape_state/identity_dual_read.json` | restore the tarball, or check it out from git. Reports are derived from raw source snapshots, so a *reconstruction* is possible where those survive — it is not the original observation |

**Why the repoint is not a weakened check.** The old probe graded the frozen
archive against a 48 h budget that nothing could ever satisfy, so the nightly
watchdog was red every day from 2026-04-20 — and a watchdog that is always red
reports nothing new: `C1-RET-08` went stale 2026-09-23..27 and nobody saw it,
because the job was already failing. Identity evidence never stopped being
produced; it moved to the dual-read record at the C1-ID-01 cut-over. The probe
now grades that record (missing / unreadable / no `generatedAt` / zero
`calls` are all *not ok*), and the workflow runs one job per stream so one
known-bad stream can no longer mask another.

**Why it was at risk.** HALTED 2026-04-20. Measured on the live checkout at
2026-08-15: newest artifact `identity_report_20260420T194828Z.json`, **2,791.9
hours = 116.3 days** unrecorded — matching the audit exactly.
`/api/scaffold/identity` served that file with nothing to distinguish it from
one produced this morning.

**Repaired honestly, not fabricated.** The manifest's acceptance is "collection
resumed **or** the surface honestly labelled". Collection cannot be resumed
here — the producer is not in the tree, and no code recovers an observation
nobody made. So the response now carries `evidenceFreshness`
(`observedAt` / `ageHours` / `state` / `stampSource`), additive to every
existing key. Resuming collection is separate REPAIR work.

**Filename beats mtime, and this is where it was proven.** mtime put the newest
report at **4 days** old; its filename puts it at 116. A deploy, rsync, restore
or container rebuild rewrites mtime, so trusting it turns a four-month halt into
"fresh" — "stale = current", arrived at by accident. `health.artifact_stamp()`
is the single owner of that answer and the endpoint calls it.

---

## `C1-RET-08` — playerctx history snapshots

| | |
|---|---|
| **Primary store** | `data/playerctx/history/` (dated snapshots) |
| **Backup** | `riskit-state-backup.sh` → `dirs/playerctx_history.tar.gz`. The **history directory only** — `data/playerctx/` next door holds a 38 MB depth-chart CSV and a 14 MB Sleeper dump, both regenerable |
| **Write owner** | `scripts/refresh_playerctx.py` (producer) + `deploy/playerctx_history_push.sh` (pusher, weekly timer) |
| **Read owner** | `store.history_coverage()` |
| **Retention** | indefinite |
| **Privacy class** | internal |
| **Restore / replay** | restore the tarball; the pusher's glob takes **every** dated snapshot rather than the newest, so supplying the deploy key later backfills every missed week |
| **Health signal** | `scripts/retention_health.py` → `C1-RET-08`; budget 336 h (weekly × 2) |

**Why it was at risk, and what the cause actually was.** **0 snapshots ever
committed**, despite producer, pusher and weekly timer all being correctly wired.

The cause was NOT a missing credential. Measured 2026-08-15 (preflight
`31912677700`): all three pushers run as the same user with the same HOME,
`${HOME}/.ssh/github_deploy_key` is absent for all three, no `*_SSH_KEY`
override is configured for any of them — and DLF and IDP Show publish anyway,
because `~/.ssh/config` carries `IdentityFile ~/.ssh/github_push` with
`IdentitiesOnly yes`. **`-i` accumulates with the config's IdentityFile rather
than replacing it**, so the absent `-i` target contributes nothing and
`github_push` supplies the identity. Demonstrated non-mutatingly with
`git ls-remote` in that context: authentication succeeds both with the siblings'
exact `GIT_SSH_COMMAND` and with none at all.

**This script alone decided, on ssh's behalf and before ssh ran, that a push was
impossible — and then exited 0.** The unit went green every week while
publishing nothing, for two snapshots and counting. The earlier claim in this
register that "the measured failure is the deploy key" was wrong; the key path is
absent for the pushers that work.

**Repaired in #860.** The guard now selects: an explicit readable key is still
used as `-i` with `IdentitiesOnly`; otherwise it warns and lets ssh resolve an
identity by its own rules. The *outcome* is not relaxed — a real authentication
failure still fails the run, pinned by a test that points the script at an
unreachable remote and requires non-zero exit plus the absence of any
"pushed on attempt" claim.

**PUBLISHED 2026-08-16T01:58:32 CEST** by a dispatched one-shot start of
`dynasty-playerctx-history.service`; unit `Result=success`, `ExecMainStatus=0`,
ran 01:57:23 → 01:58:32 CEST:

```
[playerctx-history] no readable deploy key ... - falling back to ssh's own identity
[playerctx-history] first run - cloning ... into /var/lib/playerctx-history/repo
[playerctx-history] staging 2 snapshot(s)
[main 7730677eb] chore(playerctx): retain snapshot 2026-08-15T23:58:30Z
 2 files changed, 2 insertions(+)
 create mode 100644 data/playerctx/history/snapshot_2026-08-05.json
 create mode 100644 data/playerctx/history/snapshot_2026-08-11.json
   4a9a061ea..7730677eb  main -> main
[playerctx-history] pushed on attempt 1
```

Both dated snapshots are on `origin/main` as commit `7730677eb`, authored
`playerctx History (prod)`. **Local snapshots were never the acceptance
criterion; the off-box copies are, and they now exist.**

Two things this does NOT claim. The APP_DIR checkout still reports
`tracked count 0` and `/api/status` will still report `pendingPush: 2` until
that checkout advances past `7730677eb` — those read the LOCAL tree, which a
push does not change, so they lag by one deploy and are not evidence of a
failed publication. And the next natural firing is Tue 2026-08-18 08:45 CEST;
this run was started by hand.

---

## How the health signal is wired

| | |
|---|---|
| **Probe** | `src/retention/health.py::retention_health` — one state per stream, never raises |
| **CLI** | `scripts/retention_health.py` (`--json`, `--require`). Exit **0** all required streams ok · **1** the check could not run *as asked* — including an unknown stream id in `--require`, since a typo would otherwise be satisfied by nothing and pass silently · **2** a required stream is stale, missing or unknown |
| **Scheduled** | `.github/workflows/retention-health.yml`, 06:40 UTC daily, over SSH via `deploy/diagnostics/retention_health_probe.sh` |

**It runs on the production host**, because every store lives under `data/`,
which is gitignored. A runner's checkout holds none of them and would honestly
report eight missing streams — a true statement about the runner and a useless
one about production.

**Four states, and none of them is a silent pass.**

| state | meaning |
|---|---|
| `ok` | observed inside its freshness budget |
| `stale` | the store exists and has content, but the newest observation is past budget — something ran once and stopped |
| `missing` | the store does not exist. Nothing has ever run |
| `unknown` | the probe could not answer: a store that exists and holds **zero rows**, an unreadable **or partly unreadable** store, a stamp dated **ahead of the probe host's clock**, or a probe that raised |

Three of those `unknown` cases were watchdog bypasses found by adversarial
review of the fix itself, and each graded `ok` before:

- **a future-dated stamp** yields a *negative* age, and a negative age satisfies
  any budget — so a stream stopped in March graded healthy if one artifact was
  dated next year. Tolerance is `CLOCK_SKEW_TOLERANCE_H = 1.0`, small because
  the only legitimate future stamp is writer/prober clock skew.
- **one corrupt accumulator beside a healthy one** graded `ok` and did not even
  mention the corruption. Lost crowd evidence from a ~5-day rolling window
  cannot be re-fetched; "some of it parses" is not health.
- **an undated sibling file** (`identity_report_latest.json`, an editor backup)
  carries a fresh mtime and outranked every genuinely dated artifact — defeating
  the anti-mtime defence through its own fallback. Filename-dated artifacts are
  now considered first *as a group*; mtime is consulted only when nothing is
  dated.

A crashed probe keeps its `C1-RET` id. It used to report its function name, so
`--require C1-RET-04` failed with "unknown stream id" (exit 1) instead of exit 2
— a crash silently downgraded itself out of the required set.

**Missing is never zero.** "The recorder never ran", "the recorder ran and found
nothing", and "I could not tell" have different fixes, and collapsing them is
how a dead stream reads as a healthy one. An empty store is reported `unknown`,
never `ok`.

`allOk` requires **every** stream. An aggregate that averaged would let five
healthy streams hide three dead ones — the exact failure this exists for.

**The scheduled run requires the complete authorized tranche and fails when any
of it is unhealthy.** The invariant, stated once:

> **scheduled watchdog + unhealthy required artifact = FAILED CHECK** — never a
> green informational report.

A scheduled failure while production has not yet produced all eight artifacts is
**truthful and useful**, and it is not a reason to soften the check. The job
turns green when the retention system actually becomes healthy; that is the
signal.

**Where the rule lives is load-bearing.** It is in the probe *script*, not in a
GitHub Actions expression — and that placement is the fix for a real defect
found in owner review. The first version resolved `REQUIRE` from
`inputs.require`, which is **empty on a `schedule` event**, so the nightly
watchdog silently ran in report-only mode and would have stayed green with every
stream dead. A watchdog that cannot fail is the same
ships-then-stops-then-stays-quiet silence this tranche repairs, wearing a green
tick. In a shell script the rule is executable and therefore testable
end-to-end; in YAML it could only be regex-checked.

Manual `workflow_dispatch` keeps three modes: report-only (empty `require`),
selected streams, or `ALL`. A narrowing `require` passed to a *scheduled* run is
logged and ignored — the watchdog cannot be quietly scoped down to a stream that
happens to be fine.

Two further ways the watchdog could be silenced, both closed:

- **Argparse injection.** `REQUIRE` reaches the checker through an intentionally
  unquoted expansion because it is a *list*, so `REQUIRE='-h'` became
  `--require -h`, which argparse consumed as the help flag: usage printed, exit
  **0**, nothing checked. Every token is now validated as `C1-RET-nn` or `ALL`
  before it is passed on.
- **Concurrency cancellation.** The job shared the `production-deploy`
  concurrency group, and GitHub keeps only the newest *pending* run per group —
  so a deploy queued ahead of the nightly could supersede it, producing no
  signal on exactly the days something changed. It now has its own group. The
  deploy-overlap concern that motivated sharing does not apply: this probe reads
  files under gitignored `data/`, which a deploy never rewrites.

Pinned by `tests/retention/test_watchdog_semantics.py`, which executes the probe
against a temporary data directory and asserts the exit codes for every mode,
including that a missing checker or a missing app dir is an **error**, never a
pass.

---

## What this tranche did NOT do

Named explicitly, because a retention substrate is easy to over-read as
permission:

- **No decision path reads any of these stores.** Every read surface is for
  operators, health checks and tests.
- **No valuation, ranking, trade or FAAB behaviour changed.** The additions are
  a `transactionId` field on an existing trade shape, an `evidenceFreshness`
  block on one private-auth endpoint, and writes to new stores.
- **`C1-HIST-01` (Historical Replay) is not started.** This is the minimum
  substrate that stops loss, not the historical engine.
- **Trade History is not authorized** and none of its three questions is
  implemented. `C1-RET-06` records the events those questions would need.
- **Identity consolidation is not started.** `C1-RET-07` labels a stale surface
  honestly; it does not resume collection or resolve any identity.
- **Backups are proven for ONE lineage, not for the nightly.** Run
  `31906622971` restored and verified 7 retention artifacts out of a 16-artifact
  generation on production, exit 0 — so "configured, not proven" no longer
  describes the deploy user's fallback lineage. It still describes the
  **root-owned nightly**: `deploy/apply_hardening.sh` installs
  `/usr/local/lib/riskit/` and ordinary deploys deliberately never run it, so
  merging #852 did not by itself change what the 02:30 UTC timer executes.
  Treating one lineage's proof as the other's is exactly the substitution this
  tranche exists to refuse.

---

## Addendum — `data/game_day/` joined the backup set, 2026-09-04

**Not a C1A row.** This register's authorization and table are scoped to
`C1-RET-01`…`C1-RET-08`, and nothing here reclassifies them. This addendum
exists because the nightly backup set changed and a register that omits a
change to what it describes is not a live record.

`deploy/backup/riskit-state-backup.sh` now archives `data/game_day/` — the
C5-GD-02 Game Day pre-game prediction snapshots, written by
`scripts/capture_game_day_predictions.py` (merged 2026-09-04, `b60da42`).

It belongs in this class for a stronger reason than any existing row. Every
store in the table above records something that cannot be *re-fetched*; a
pregame capture records something that no longer *exists*. It is the state
that produced a prediction before the outcome was known, and once the week
scores, no amount of access to Sleeper can reconstruct it — which is why the
capture script refuses to write a `pregame` snapshot after kickoff rather
than reconstructing one. The loss window is hours, not days.

**Evidence status: NONE MEASURED.** No generation has yet been observed
containing a `game_day.tar.gz`, because no capture exists on production yet.
This is stated rather than inferred: the row is in the script and pinned by
`tests/deploy/test_state_backup_dir_archiving.py`, which is a repository fact,
not production evidence. Do not read it as a proven backup.

The same split the section above draws still applies and is not resolved
here: the deploy user's fallback lineage is proven, the **root-owned nightly**
is not, and installing this row changes neither.

---

## Addendum — `data/learning/receipts.sqlite` joined the backup set, 2026-10-01

**Not a C1A row**, for the same reason as the Game Day addendum above: the
backup set changed, so the register records it.

| | |
|---|---|
| **Primary store** | `data/learning/receipts.sqlite` (gitignored; inside the repository the store refuses every path not under `data/learning/` — checked first, wherever the checkout lives — and `data/ros/` explicitly, which the scheduled refresh force-adds; outside the repository it refuses everything unless a caller explicitly opts a root in via `EXTRA_ALLOWED_ROOTS`, which only the test suite does — there is no implicit temp-dir allowance) |
| **Backup** | `riskit-state-backup.sh` → `sqlite/receipts.sqlite.gz` (online backup, `PRAGMA integrity_check`ed) |
| **Write owner** | `src/model_registry/receipt_store.py::append_receipts` + `record_correction` — INSERT-only; UPDATE / DELETE / `INSERT OR REPLACE` (ABORT, never silently ignored) and `PROMOTION_RECORD` rows are refused by database triggers on `receipts`, `corrections` and `meta`; corrections additionally refuse self-, superseded- and cyclic supersession by trigger, with foreign keys enforced. A corrected outcome is a new revision linked by a `corrections` row; the original is never changed |
| **Read owner** | `receipt_store.iter_receipts` — operators, tests, and later AL units. **No serving path reads it** |
| **Retention** | indefinite; append-only |
| **Privacy class** | **private** — model evaluations, challengers and verdicts are decision intelligence (`MASTER_PRODUCT_PLAN.md` §5) |
| **Restore / replay** | restore the gz. Every receipt AL-0 itself derives is re-derivable from committed evidence (the Hill registry, the Hill trainer-repair demo, the #1589 source-quality archive) by `src/model_registry/learning_adapters.py`, byte-identically. Receipts that later units point at perishable stores (pregame captures, rolling windows) are not, which is why the store is backed up rather than declared rebuildable |
| **Health signal** | none yet: nothing writes the store on production in AL-0. A scheduled writer (AL-1a accumulation) adds its own signal |

Owner unit: Adaptive Learning AL-0 (`docs/EXECUTION_PLAN.md` §0;
`docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §23 A9). AL-3a is the serial
owner of `deploy/backup/`; no AL-3a claim was active when this line landed.

**Evidence status: NONE MEASURED.** No production generation has been observed
containing `receipts.sqlite.gz`, because no production writer exists yet. The row
is pinned in the script by `tests/deploy/test_state_backup_dir_archiving.py` — a
repository fact, not production evidence.

## Addendum — AL-P2: every irreplaceable evidence store joined the backup set; the nightly root copy now refreshes on deploy, 2026-10-01

**Not a C1A row**, like the two addenda above. Owner unit: Adaptive Learning
AL-P2 (`docs/EXECUTION_PLAN.md` §0, Wave 1 item 4; perishable audit
`docs/BRISKET_IDEAS.md` §13.4 rank 2, gap G7). Serial owner of `deploy/backup/`
for this change (the AL-3a backup half).

### 1. The stale nightly (measured read-only on production, 2026-10-02 ≈03:00 UTC)

`riskit-state-backup.service` executes `/usr/local/lib/riskit/riskit-state-backup.sh`
(root:root, dated **2026-08-16**, 600 lines). The checkout at the box's deployed
commit `b46eabe5f` carries 647 lines; `cmp` differs at line 27. `backup_root_lib.sh`
matched. The last nightly (02:30 UTC 2026-10-02) reported `Result=success` — a
**successful run of the wrong writer**: it omits `retention/acquisition.sqlite`,
`auction/auction.sqlite`, `game_day/` and `learning/receipts.sqlite`. Those were
covered only by the deploy user's post-deploy proof generation under
`/home/dynasty/backups/riskit-state/daily/` (≈227 MB each, 5 most recent
2026-09-28…10-02).

Cause: the root copy was refreshed only by `deploy/apply_hardening.sh` /
`deploy/backup/install_state_backup.sh` (`c1a-install-state-backup.yml`), never
by a deploy. **Fix:** `deploy/install-systemd-service.sh::refresh_state_backup_line`
— which every deploy runs — sources `install_state_backup.sh` (the one owner of
the file list, order, modes and service render) and calls its functions. Writes
happen only on content drift (unprivileged `cmp`, then `sudo -n install`; the
same allowlist #1594 established), daemon-reload + enable only when something
changed, and a post-install `cmp` proves the root copy equals the checkout. A
failed refresh is an ERROR in the deploy log and does not fail the deploy (the
previous root copy keeps producing generations). Privilege model unchanged: the
deploy account already held NOPASSWD `install` and already ran this installer.

**Evidence status: NOT YET MEASURED on production.** The refresh takes effect on
the first deploy after merge; the proof is a `cmp` of the root copy against the
checkout plus a nightly generation that contains the AL-P2 artifacts — the
nightly root under `/var/backups/riskit-state` is not readable by the deploy
account, so that half needs an operator (`sudo ls`) or the log.

### 2. Store table

Bk = how `riskit-state-backup.sh` captures it. Every new line is guarded
(absent → `skip (absent)`), never in `BACKUP_REQUIRED`, and every live SQLite
store goes through the online-backup helper.

| Store (verified path in code) | Writer | Retention | Backup | Rebuildable? |
|---|---|---|---|---|
| `data/market_trades/archive.sqlite` (`src/trade/market_trade_archive.py`) | `scripts/fetch_ktc_trades.py`, `dynasty-ktc-trades` | indefinite, append-only (abort triggers) | `sqlite/market_trades_archive.sqlite.gz` | **No** — KTC serves a ~200-row rolling window. PRIVATE |
| `data/market_trades/underlying_trades.sqlite` (`src/trade/market_trade_report.py`) | `build_ledger`, `dynasty-market-trade-ledger` | replaced wholesale each build | **not backed up** | **Yes** — a pure derivation rebuilt (temp + atomic rename) from the raw archive + the intel ledger + the own-league stores, all backed up; re-run `scripts/market_trade_ledger.py` (the `dynasty-market-trade-ledger` timer does it) |
| `data/market_trades/reports/` | same build | dated JSON | `dirs/market_trades_reports.tar.gz` | Partly — counts are re-derivable, but a dated report records what the archive held THAT day; cheap (KB), so kept |
| `data/consensus_edge.sqlite` (`src/consensus_edge/snapshot.py`) | `dynasty-consensus-edge-snapshot` daily | indefinite | `sqlite/consensus_edge.sqlite.gz` | **No** — a daily label is what the model said that day |
| `data/source_archive/boards.sqlite` (`src/source_archive/store.py`) | KTC format variants, #1603 | indefinite, append-only | `sqlite/source_archive_boards.sqlite.gz` | **No** — KTC publishes current values only |
| `data/leagues/own_league_format_captures.sqlite` (`src/trade/own_league_format_capture.py` → `league_registry.scoring_snapshot_dir()`) | transaction-crawl timer, third pass, #1607 | indefinite | `sqlite/own_league_format_captures.sqlite.gz` | **No** — dated captures + "unchanged since" re-observations; a later fetch cannot say what a season looked like on an earlier date |
| Sharp league-format captures (`sharp_league_format_captures` / `_observations`, inside `data/intel/ledger.sqlite3`) | discovery / roster crawl / catch-up | pruned with the intel ledger | `sqlite/intel_ledger.sqlite3.gz` — **now ONLINE**; `dirs/intel.tar.gz` keeps the rest of `data/intel/` and excludes `ledger.sqlite3{,-wal,-shm}` | No (dated observations). Previously only inside a tar of a live WAL database — a torn copy whenever the crawler wrote mid-read |
| `data/temporal_ledger.sqlite` (`src/history/store.py`) | live recorder at every fresh scrape + backfill/migrations | indefinite | `sqlite/temporal_ledger.sqlite.gz` | **No, not in full** — see §3 |
| `data/dfs/workspace.sqlite` (`src/dfs/store.py`) | `dynasty-dfs-auto-refresh` | no DELETE | `sqlite/dfs_workspace.sqlite.gz` | **No** — immutable slate snapshots. `data/dfs/raw/` is the overwritten latest provider pull (re-fetchable; its content is snapshotted in the workspace) and is not backed up |
| `data/bdvm/` (projections, events, context, valuations) | `dynasty-bdvm-refresh` + news events | immutable dated snapshots | `dirs/bdvm.tar.gz` | **No** — vendors (Mike Clay, IDP Show) publish the current edition only; events carry human edits |
| `data/forecast_archive/` (`src/ros/forecast_archive.py`, #1602) | refresh + post-deploy join | append-only monthly JSONL | `dirs/forecast_archive.tar.gz` | **No** — forecast as produced with its model identity |
| `data/pick_forecast_snapshots/` (`src/ros/pick_forecast_snapshot.py`, #1604) | `dynasty-pick-forecast-snapshot` | append-only monthly JSONL | `dirs/pick_forecast_snapshots.tar.gz` | **No** — the team-strength state of a week |
| `data/learning/receipts.sqlite` (AL-0, #1597) | AL units | indefinite | `sqlite/receipts.sqlite.gz` (already present — addendum above) | see above |
| `data/sparse_evidence_shadow/`, `data/robust_filter_shadow/` | shadow timers | append-only monthly JSONL | `dirs/<name>.tar.gz` | No — what each shadow run saw on its inputs that day; tiny |

`backup_sqlite` gained an optional output label (the second argument, like
`backup_dir`'s) because basenames are not unique: `archive.sqlite` and
`boards.sqlite` would otherwise be ambiguous on restore, and two stores with one
basename would overwrite each other inside one generation. A test now fails on
any duplicate artifact name.

### 3. The temporal ledger: INCLUDED, and why

§11 of `docs/history/C1_U4_TEMPORAL_LEDGER.md` declared the ledger rebuildable
from git-tracked `exports/archive/` + `board_history.sqlite` +
`rank_history.jsonl`. Measured on the production ledger 2026-10-02 (read-only):

| origin | lane | rows | dates |
|---|---|---|---|
| `backfill:archive` | scraper_blend / source_value | 638,434 / 559,760 | 2026-07-14 … 09-30 |
| `migration:board_history` | canonical_board | 53,766 | 08-06 … 10-01 |
| `migration:rank_history` | canonical_board | 56,489 | 07-20 … 10-02 |
| **`live:server`** | canonical_board | **756,995** | 08-16 … 10-02 |
| **`live:server`** | source_value | **1,245,049** | 08-16 … 10-02 |

The rebuild restores the first three origins (daily fidelity). The ~2.0 M
`live:server` rows are 2-hourly instants — including slot-pick values the
rank-gated `rank_history` log drops and source-value rows between daily archive
zips — and exist nowhere else. They are not "origin labels, which is cosmetic":
they are the intraday observations. So the ledger is primary evidence and is
backed up. Size: 1.50 GB raw, **220 MB gzipped** (gzip -6 of the live file, 38 s,
niced). An online backup is required (WAL). Rotation is the script's existing
14-day `KEEP_DAILY`; no separate rotation was added because the generation-level
keep window already bounds it.

### 4. Disk impact (measured 2026-10-02)

Gzipped sizes of the new artifacts: temporal ledger 220 MB, DFS workspace
11.4 MB, Consensus Edge 7.6 MB, bdvm 1.6 MB, KTC archive 0.1 MB, the rest
< 2 MB combined. The intel ledger (158 MB gz) was already inside `intel.tar.gz`
and moves to its own artifact — net ≈ 0. Per generation: ≈227 MB → **≈470 MB
(+≈241 MB)**. Two lineages keep 14 generations each (root nightly
`/var/backups/riskit-state`, deploy-user post-deploy proof
`/home/dynasty/backups/riskit-state`), both on `/dev/sda1` (96 G, **60 G free**):
≈ +6.7 GB, ≈13 GB total at steady state, reached over 14 days. Transient: one
uncompressed copy at a time in the staging dir (peak ≈1.5 GB, the temporal
ledger). Runtime: ≈ +1–2 min per run (online copy + `integrity_check` + gzip of
≈2.2 GB), inside the proof workflow's 20-minute timeout — estimate, not yet
measured end to end.

**Evidence status: NONE MEASURED for the new artifacts.** No generation has yet
been observed containing them; the rows are pinned by
`tests/deploy/test_state_backup_dir_archiving.py` (a repository fact). The
restore proof (`deploy/diagnostics/retention_backup_restore_proof.sh`) did not
restore-and-verify the AL-P2 artifacts at first; §5 adds the small ones.

### 5. Review fixes (PR #1611 review, 2026-10-01)

* **CORE vs OPTIONAL.** Every store that predates AL-P2 is CORE: a failure still
  discards the generation and exits 1. Every AL-P2 addition (the table in §2
  minus `receipts.sqlite`, which predates it) is OPTIONAL: a failure is a WARN,
  a row in `<generation>/optional_stores.tsv` (`name`, `status`, `detail`), and
  writer exit **3** — generation kept. The unit maps 3 to success
  (`SuccessExitStatus=3`, visible as `ExecMainStatus=3`). Corrected in §6: the
  post-deploy proof annotates its OWN run's exit 3 and, since the re-review,
  the nightly unit's last `ExecMainStatus` too; `c1a-install-state-backup.yml`
  annotates only the manual oneshot it starts.
  Reason: the intel ledger's corruption history on the box
  (`ledger.sqlite3.corrupt`, `recovery-20260801T012318Z/`) — latent corruption
  in one optional store must not stop `user_kv` / `session_store` being backed up.
* **Intel ledger fallback.** If the online copy is not in the generation (failed
  `integrity_check`, shed, skipped, absent) the raw `ledger.sqlite3*` files ride
  in `intel.tar.gz` exactly as before AL-P2, so a corrupt ledger still leaves
  bytes a recovery can work from.
* **Free-space guard.** Before writing, the writer needs
  `max(2 × newest generation, 5 GiB)` free on the backup filesystem, and per
  optional store `2 × source + 1 GiB`; short (or unmeasurable) → OPTIONAL stores
  are shed with a WARN and exit 3, CORE is still written. CORE runs first, the
  temporal ledger last.
* **Proof run.** The post-deploy proof (20-minute budget, deploy user, live box)
  skips the two large stores (`PROOF_SKIP_OPTIONAL`, default
  `temporal_ledger.sqlite intel_ledger.sqlite3`, recorded `skipped_requested`),
  runs under `nice -n 10` + `ionice -c2 -n7`, and restore-checks the SMALL AL-P2
  artifacts. It never restores the 1.5 GB / 0.7 GB ledgers. Consequence for §4:
  the deploy-user lineage stays ≈227 MB plus the small stores (≈+22 MB gz), so
  the steady-state increase is ≈ +3.4 GB (root lineage only), not +6.7 GB.
* **No mid-deploy backups.** `riskit-state-backup.timer` (and the
  `riskit-backup` / restore-test timers) lost `Requires=` on their services, and
  the installer runs `enable` + `start` on the timer, never `enable --now`
  against a Requires= timer — starting the timer used to start the service.
* **Bounded runs.** `TimeoutStartSec=2h` on the nightly; an EXIT/INT/TERM trap
  removes the run's own staging; the start-of-run sweep removes any staging dir
  no live process holds (per-run `flock` on `.staging-*.lock`, PID fallback)
  instead of `mtime +1`.

### 6. Re-review fixes (PR #1611 re-review, 2026-10-01)

* **Recording an optional failure can no longer discard CORE.** A failed
  optional store's partial artifact is removed *before* `store_failed` runs, and
  the `optional_stores.tsv` append is `|| warn`-guarded. Before, on ENOSPC the
  append failed under errexit, the run exited 1 and the EXIT trap deleted the
  staging directory holding `user_kv` / `session_store`.
* **Where a nightly exit 3 surfaces — corrected.** §5 said the post-deploy proof
  turns exit 3 into a warning; it only saw its OWN run, which skips
  `temporal_ledger.sqlite` and `intel_ledger.sqlite3`. The proof now also reads
  the nightly unit's last `Result` / `ExecMainStatus` (unprivileged
  `systemctl show`) and annotates a 3 or a failure. Latency: the next deploy.
  No box watchdog reads the root-only generation; `scripts/watchdog_freshness.py`
  runs in Actions and cannot see the box, so it was not extended.
* **Unmeasurable space sheds optional, never exits.** `df` / `du` failures in
  the run-level guard are `|| x=""`-guarded (they exited 1 under pipefail), and
  the per-store gate treats an unmeasurable source or free-space figure as short
  (`skipped_space_unmeasurable`, exit 3). The per-store estimate counts the
  store's `-wal`.
* **PID reuse.** A run removes a pre-existing staging dir carrying its own name
  (a SIGKILLed run's, PID reused the same day) before writing.
* **Proof accepts only known optional names** as explained absences, so a CORE
  artifact can never be excused by a forged or stray manifest row.
