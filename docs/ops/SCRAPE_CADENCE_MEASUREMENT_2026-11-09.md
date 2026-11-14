# Scrape cadence and startup-scrape measurement (2026-11-09)

Row MD-103 / owner directive 2026-11-08 Priority 8. **Measured, nothing changed:** no flag default, workflow or
threshold was touched. Source: `gh run list` over `scheduled-refresh.yml` (400 runs, 2026-08-21 .. 2026-11-09) and
`deploy.yml` (400 runs, 2026-10-14 .. 2026-11-09), plus the code named below. Windows are complete UTC days ending
2026-11-08 so a partial day cannot bias a rate.

## 1. Does scheduled refresh really run about 3.7 times a day?

Yes, about 3.6, and not the 12 a day the cron declares.

| window (complete UTC days) | `event=schedule` runs started | per day | declared (`42 */2 * * *`) | succeeded |
|---|---|---|---|---|
| last 7 | 24 | **3.43** | 12 | 24 / 24 |
| last 14 | 51 | **3.64** | 12 | 51 / 51 |
| last 30 | 124 | 4.13 | 12 | 100 / 124 |
| last 60 | 261 | 4.35 | 12 | 154 / 261 |

- The cron string asks for 12 runs a day. GitHub starts roughly a third of them. Recent days show 3 to 5 runs
  (2026-10-26 .. 2026-11-08: 4 4 4 3 4 5 3 3 4 3 3 3 5 3). A scheduled run is not guaranteed on the minute, or at all,
  under GitHub load; the repository cannot change that from inside the workflow.
- The gaps between runs are therefore about 6.6 hours on average, not 2.
- Failures before 2026-10-26 (the 30- and 60-day success rates) are a separate fault history and are not this
  question; the last 14 days are all green.
- What this changes: `config/source_staleness.json` said a 24 h threshold "catches ~12+ consecutive fetch failures".
  At the measured rate it catches about 3 to 4 consecutive missed or failed scheduled runs. That is still a sound
  "outage within a day" policy, so the threshold was **not** changed; only the comment that stated the wrong figure
  was corrected, as were two "runs every 2h" lines in `CLAUDE.md` (they now say declared 2 h, measured about 3.6/day).

Data freshness on the box does not depend on this cron: the backend's own loop scrapes every
`SCRAPE_INTERVAL_HOURS = 2` (`server.py:116`, `schedule_loop`), but each restart resets that loop to
`boot + interval` (below).

## 2. How often does the startup scrape run per deploy?

Once per backend start, and every successful deploy restarts the backend
(`restart_service` in `deploy/deploy.sh`; the post-deploy smoke step in `deploy.yml` itself documents that the restart
launches `initial_scrape` three seconds after boot). With the flag off every boot runs it, Chromium included
(`docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md` section 3.4: about 0.72 GiB of Chromium, around 5 minutes).

| window | successful `deploy.yml` runs | per day | by trigger |
|---|---|---|---|
| last 7 days | 43 | **6.14** | push 37 (5.29/day), data dispatch 6 (0.86/day) |
| last 14 days | 107 | **7.64** | push 78 (5.57/day), data dispatch 29 (2.07/day) |

So the box takes about **6 to 8 startup scrapes a day** on top of its own 2-hourly loop (12 a day if it is never
restarted). These windows include this campaign's burst of code merges; a quiet week is lower. Notes:

- 108 of 243 deploy runs in the last 14 days were `cancelled` (a newer push superseded them) and 28 `failed`; only
  successful runs are counted above, so this is a floor for restarts (a failed deploy can restart the service before
  it fails; the repository does not record which).
- Data-only commits do not deploy by themselves (`paths-ignore: data/**, exports/**` in `deploy.yml`);
  `scheduled-refresh.yml` dispatches a deploy after a scrape that changed data (`gh workflow run deploy.yml`), which is
  the "data dispatch" row (2.07/day against 3.64 refresh runs/day).
- Every restart also resets the in-process schedule to `boot + 2 h`, so with a restart every ~3 hours the 2-hourly
  scheduled scrape often never gets to fire before the next deploy: the startup scrape is frequently the only scrape
  of that process lifetime.

## 3. What would `conditional_startup_scrape` save?

The flag is registered `False` in `src/api/feature_flags.py` and was not changed. Behaviour when ON
(`server._startup_scrape_plan`): a boot skips its startup scrape only when a contract is primed, its
`contractHealth` is ok, and the board is less than one `SCRAPE_INTERVAL_HOURS` (2 h) old; the first scheduled scrape
then runs at `produced + interval`. Any other boot scrapes immediately, so the maximum served-board age is unchanged.

- **Upper bound:** every boot with a fresh healthy board, up to the 6.1 to 7.6 startup scrapes a day measured above,
  each with its Chromium launch.
- **Lower bound:** none, whenever the loaded board is already 2 h old or unhealthy.
- **Not measurable from the repository:** the fraction of boots that find a board under 2 h old. The board a box loads
  at boot is its own last scrape or, failing that, the checkout export, which the CI refresh (about 6.6 h apart,
  section 1) leaves up to hours old. With the flag off the code records no plan event, so there is no telemetry to
  count. Setting it ON for a week would record `startup_scrape_plan` events (`run_now`, `reason`, `board_age_hours`)
  and settle it, but flipping the default or the flag is reserved (the docstring cites the owner-reserved
  `MemoryHigh` canary), so no estimate beyond the bounds is claimed.

## Reproduce

```bash
gh run list --workflow scheduled-refresh.yml --limit 400 --json createdAt,event,conclusion
gh run list --workflow deploy.yml --limit 400 --json createdAt,event,conclusion
# count event=schedule per complete UTC day; count conclusion=success on deploy.yml per day, split by event
```
