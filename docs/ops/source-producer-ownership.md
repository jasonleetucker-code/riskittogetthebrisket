# Source producer ownership and cutover

These are opt-in source and league worker templates, not evidence of installed
units or a production cutover. The shared source cycle is
`src/serving/producer.py:run_source_cycle`; its standalone caller is
`scripts/run_source_producer.py`. Importing either starts no scraper and imports
no web server. The legacy server wrapper must delegate to this same cycle.

## Ownership inventory

| Work | Existing owner | Standalone owner / cutover scope |
| --- | --- | --- |
| Core `Dynasty Scraper.py:run` | `server.run_scraper`, GitHub scheduled refresh | Source worker replaces only the server cycle; uses the unchanged scraper `SITES` policy (currently KTC and IDPTradeCalc enabled) |
| Six anchor CSV mirrors | Server cycle | Same files: `ktc.csv`, `ktcSfTep.csv`, `ktcCrowdSfTep.csv`, `ktcTradesSfTep.csv`, `ktcCrowdTradesSfTep.csv`, `idpTradeCalc.csv` |
| Dynasty Nerds SF-TEP, FantasyPros SF, FantasyPros IDP | Server cycle and GitHub scheduled refresh | Same three `scripts/fetch_*.py:main(["--mirror-data-dir"])` calls; schema exit 2 remains an error event, other failures warnings |
| IDP Show | Server cycle when local session exists; GitHub when secret staged; dedicated VPS fetch/push template | Same conditional `fetch_idpshow.main([])`; absence is recorded without reading credentials |
| Canonical board, rankings/trade/catalog prepared bytes | Shared canonical builder/publisher | Worker publishes one validated accepted generation; records rank/source/temporal history only after acceptance |
| Active league facts, overlay and prepared views | Shared `refresh_league_serving` | Runs after canonical publication and from the separate ten-minute league template; failure does not revoke accepted canonical data |
| Initial source-history backfill | Legacy startup | Explicit `--backfill-history`, only if the existing history is empty; shares source lease and existing history implementation |
| Additional sources and deployment | `.github/workflows/scheduled-refresh.yml` | Retained; **not replaced** by this source worker |

The GitHub job runs at `42 */2 * * *`. Its additional fetchers include Dynasty
Daddy, FantasyCalc, OTCFFB, Fantasy Navigator, PFK, Flock and Flock rookies,
DraftSharks and DraftSharks ROS, FP Fitzmaurice, Yahoo Boone, plus shared fetchers.
It also owns draft workbook sync, ROS scraping, metadata/sanity, git publication
and deployment steps. Dedicated DLF, IDP Show, BDVM, player-context, depth-chart,
game-day and other existing jobs keep their current ownership. This change does
not enable, disable or consolidate those jobs. GitHub and VPS are distinct
machines; the local source lease does not serialize a GitHub run or its deploy.

`docs/ops/schedules-and-cadence.md` contains older Jenkins cadence claims. The
checked-in Jenkinsfile currently has no scheduled trigger; use actual workflow
and installed unit evidence before changing ownership. Template presence does
not establish that a job runs in production.

### Deployment audit: repository wiring versus installed state

Read-only audit at parent baseline `5445a62dc` found that
`deploy/deploy.sh::ensure_systemd_service` globbed all timer templates, while
`deploy/install-systemd-service.sh` explicitly installs its known timer owners.
The installer has no source-producer, league-serving or prepared-news branch.
The presence probe now skips only `source-producer` and `league-serving`, so an
ordinary legacy deployment does not repeatedly report staged workers missing.
All existing installer-owned timer checks and reconciliation remain enabled.
No automatic worker installation, activation or serving-mode change was added.

| Owner | Checked-in mechanism | Installed/running evidence in this audit |
| --- | --- | --- |
| Legacy web source cycle | `server.py` defaults to legacy; shared `run_source_cycle` and two-hour completion cadence | Unverified; no host configuration read |
| Standalone canonical source | `dynasty-source-producer.service/timer/path.template`; shared private root, 9000s admission wait, 18000s unit limit | Templates only; bootstrap proof does not prove timer enablement or future liveness |
| League serving | `dynasty-league-serving.service/timer/path.template`; 10-minute timer and separate league lease | Templates only |
| Prepared news | `dynasty-prepared-news.service.template`; persistent `--watch` process | Template only |
| Existing BDVM and other supplementary jobs | Explicit installer blocks / `install_simple_timer` calls | Installation wiring exists; present host state unverified |
| GitHub source/deploy owner | `.github/workflows/scheduled-refresh.yml`, separate runner and source set | Workflow definition verified; no current run or host mutation performed |

Local environment check on 2026-09-10 (America/New_York): `wsl --list --verbose`
reported WSL not installed; Docker was absent from PATH. Git Bash is available
for shell contract tests on Windows, not evidence of Linux locks, systemd or
POSIX modes. No distribution/package was installed and no remote host contacted.
Before an authorized cutover, collect installed unit contents, enable/active
state, last/next triggers, accepted artifact and proof identities, and a completed
worker journal from the actual target host. Keep credentials and raw payloads
out of that evidence. Those checks remain outstanding.

GitHub metadata checked 2026-09-11 UTC: [Deploy Production run 34539524729](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34539524729)
completed successfully for main `53b87921a115751c16c9749fa84ddbb40b118224`, updated
2026-09-10T23:36:06Z. Its remote deploy, smoke and live-contract steps all report
success. This is workflow evidence for that main revision, **not** deployment
evidence for local campaign baseline `5445a62dc` or this change. No workflow logs,
remote unit state, process RSS/FD, candidate route p95 or refresh-overlap provider
counts were collected. The Windows fixture timings cannot fill those gaps.

## Publication and failure behavior

Both embedded and standalone source callers acquire
`RISKIT_SERVING_DIR/producer.lock` (default `data/private_serving/producer.lock`)
for collection, mirrors, supplements, validation, publication and receipt writes.
The OS releases the lease on process exit; stale lock files are not deleted.
Different web processes cannot start duplicate source cycles. The standalone
unit uses `KillMode=control-group` so service stop, timeout or exit cleans up its
Chromium descendants; the legacy wrapper retains its existing scoped reaper.

Before collection, the standalone caller loads the accepted serving artifact
under the lease. It never treats the newest raw export as last-known-good data:
the scraper can write a rejected candidate before the guard runs. Promotion
retains the missing-anchor, fewer-than-half-sites, and 75% player-retention
guards. The CLI additionally requires the existing disk floor (default 500 MB,
`DISK_SPACE_MIN_MB` override) because serving publication requires disk; the
legacy memory mode retains its warning behavior. Failed canonical builds and
failed artifact validation preserve the previous accepted generation. Only
after successful publication is the accepted raw export mirrored for recovery.
Source `producedAt` comes from `scrapeTimestamp`, never load time.

Supplemental source failures still warn and allow canonical publication, as in
the existing cycle. They cannot establish initial cutover readiness. The private
bounded status file records phases, the last 200 event names/severities, counts,
source outcomes and league-refresh outcome. It excludes raw rows, rosters,
cookies and arbitrary provider messages. The receipt identifies the source
contract, script digests, exact source attempts, conditional mirror outcomes and
the physical accepted artifact ID. The cycle pins the contract before loading
the scraper and rejects a source-script change detected before publication.
The receipt retains that pinned identity, so a later deploy cannot label old
execution as proof for changed source code.

## Operator cutover and rollback

1. Render the templates using the existing `__APP_DIR__`, `__APP_USER__`,
   `__VENV_DIR__`, `__SERVICE_NAME__` substitutions and inspect them. No deploy or
   installer is changed by this work. The worker and server must share the same
   private `RISKIT_SERVING_DIR` and application user. Keep that root outside any
   static HTTP mount; use a private directory/ACL.
2. Review `python scripts/run_source_producer.py --dry-run`. This prints the
   source contract without creating files, importing the scraper or fetching.
3. Run one source cycle. For first-generation bootstrap only, supply
   `--accepted-raw /path/to/verified-accepted-legacy-input.json`; choose the raw
   input underlying the currently accepted board. There is deliberately no
   automatic newest-file fallback. Subsequent runs load the accepted artifact.
   A busy exit (3) proves only that another owner holds the lease; retry after
   that cycle, and do not count it as a completed refresh.
4. Confirm the resulting accepted generation, source evidence, frontend value
   parity and freshness. `source_receipt_ready(store)` fails closed for missing,
   malformed, mismatched or stale receipt/generation evidence; default maximum
   age is four hours for both completion and the actual source timestamp.
   Required supplements must have succeeded; IDP Show may be explicitly skipped
   only when its local session was absent. This gate is required before prepared
   server mode can disable the embedded source owner. It is a startup cutover
   check, not a per-request provider or large artifact read. The first successful
   standalone completion stores the exact verified receipt as an immutable
   `source-ownership/standalone` proof **before releasing `producer.lock`**.
   For an older healthy receipt without proof, `enforce_source_ownership` acquires
   that same lease (default wait 2s; keyword range 0–30s), rechecks the current
   accepted generation and receipt after admission, and persists proof before
   release. Contention or failed proof publication refuses bootstrap. It never
   treats an existing lock file as evidence that the lease is currently held.
   Later restarts validate that
   proof and separately load the accepted canonical generation; an upstream
   outage or old source timestamp does not make last-good serving unavailable.
   Changed source scripts/policy or corrupt proof require a new healthy current
   receipt to renew ownership. `source_receipt_ready` remains the strict freshness
   diagnostic and can correctly return false while durable ownership is valid.
   A valid durable proof does not wait for an active source cycle. Standalone
   journal `sourceOwnership` reports `verified`, `retained` or `unverified`:
   healthy recurring cycles retain the existing valid proof; only missing,
   invalid or changed-policy proof is renewed. Every fresh proof references a
   canonical board protected by retention, so ordinary cycles must not create
   an accumulating chain of pinned boards. Source receipts still update normally.
   Expected supplemental degradation may still accept a canonical board, but
   cannot mint proof. A proof-write failure fails the worker run without dropping
   its already accepted board or adding a false successful run-history entry.
5. With reviewed deployment authorization, switch the web process to prepared
   mode and confirm the embedded loop is disabled, then enable the standalone
   source timer/path and the independent league/news owners. The one-shot
   bootstrap in step 3 is serialized with legacy work; do not leave two recurring
   VPS source owners enabled. Keep GitHub scheduled refresh and additional feed
   jobs enabled.
   Verify installed unit schedules, successful receipts and freshness after the
   switch. A prepared process must fail startup if neither the durable proof nor
   a healthy first-cutover/renewal receipt validates; it never silently starts a
   competing embedded producer. Start the prepared news worker as well before
   enabling prepared news reads.
6. For rollback, stop the standalone source timer/path/service, restore the reviewed
   legacy server mode and restart it. The accepted artifact remains available;
   no deletion or raw-file promotion is required. Check legacy cycle and alert
   wiring after rollback. The shared lease also protects a brief overlap.

An explicit `--backfill-history` invocation performs only empty-history
maintenance and returns; it does not scrape or create a cutover receipt. Source
worker exit codes are 0 (accepted), 1 (failed/blocked), 3 (busy); CLI argument
errors use argparse's exit 2. The source template treats only 3 as an additional
successful unit exit, and uses the legacy two-hours-after-completion cadence.
No installed service, timer, deployment, provider availability or production
latency is verified by these templates and offline tests alone.

Regressions: `tests/serving/test_producer_status.py` checks strict attestation
under the lease, bounded contention, generation changes while waiting, corrupt
renewal and stale-proof restart; `tests/serving/test_producer_cli.py` covers proof
before cycle release, degraded supplements and proof-write failure. Deployment
contracts in `tests/deploy/test_all_timers_are_wired.py` and
`tests/deploy/test_staged_source_ownership.py` keep the opt-in list explicit and
execute the actual presence-probe loop against stub systemctl calls.

## Manual refresh in prepared mode

The web process calls `request_source_refresh(store, trigger="manual")`. It writes
only a private, atomic `source-refresh.request` marker and returns `queued` with
an opaque request ID. Repeated pending requests coalesce. The separate
`dynasty-source-producer.path.template` watches the marker and starts the same
standalone service as the timer. Render its `__SERVING_DIR__` to the exact private
root used by the web process and worker; systemd path files do not read `.env`.

The worker acknowledges/removes the marker only after acquiring the source
lease. Status records its claim; requests arriving during that cycle remain
queued for the next invocation. A malformed marker is acknowledged as invalid
without copying its payload into status. `pending_source_refresh(store)` reads
bounded queued metadata for status endpoints. No subprocess is spawned by the
web handler. The service waits up to 9000 seconds for admission (CLI default is
still immediate busy exit), with an 18000-second total service timeout.

`PathExists` recovers a marker present before unit startup and rechecks after
service exit. The bounded admission wait avoids a rapid busy-exit loop during
the normal overlap window; an abnormal lock holder beyond that limit still
requires operator attention. See the upstream [systemd path-unit specification](https://github.com/systemd/systemd/blob/main/man/systemd.path.xml).


For a nondefault registered league, the same authenticated admin endpoint
`POST /api/scrape?leagueKey=...` queues `league-refresh.request` instead of a full
source collection. Both branches return HTTP 202 and an opaque request ID with
no web-process provider work. The league worker refreshes active compatible
leagues and uses `league-producer.lock`; source-cycle follow-up and independent
league invocations cannot run that work concurrently. The league path template
must be rendered with the same exact private root as the source path template.
`refresh_league_serving.py --lease-wait-seconds 600` claims only the marker present
after admission, preserving a later request for the next run. The service's
1,200-second timeout bounds that wait and processing; busy exits preserve pending
work. The ten-minute timer remains the regular refresh owner.

## Status and prepared news

`src/serving/status.py::ProducerStatusReader` polls private bounded status files
outside requests. `/api/status` uses its cached source outcome, queue wait,
progress, pending source/league requests, recent run history and 24-hour success
rate. A journal that says running without the process lease is reported as
interrupted. Malformed progress cannot kill the reader; recovery clears errors.
The reader routes each newly observed failed/blocked/interrupted run through the
existing alert owner, preserving its global cooldown. It is polling-based and
does not promise delivery of every event while the web process is offline.
`/api/performance` is admin-only and includes cached producer/generation state;
no request parses the private artifacts to produce that response.

The separate `dynasty-prepared-news.service.template` runs
`python scripts/refresh_prepared_news.py --watch`. Keep the process alive so the
existing ESPN target rotation and Sleeper directory cache survive successive
refreshes. Its default healthy cadence is ten minutes, with a bounded retry
delay after failure. Each result records actual provider attempts and last
success; cached items never turn a failed attempted refresh into fresh success.
The web reader performs local filtering over the accepted news snapshot.
Missing/all-provider-failed evidence returns the existing unavailable behavior;
a bad newer artifact does not discard a previously valid reader snapshot.
This service is a template only and must be observed on the target host before
claiming that ordinary prepared news reads have an active producer.
