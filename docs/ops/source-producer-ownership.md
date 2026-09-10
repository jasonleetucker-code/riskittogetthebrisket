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
   check, not a per-request provider or large artifact read.
5. Enable the standalone source and league timers only with reviewed deployment
   authorization, then switch the server mode using its documented prepared-mode
   configuration. Keep GitHub scheduled refresh and additional feed jobs enabled.
   Verify installed unit schedules, successful receipts and freshness after the
   switch. A prepared process must fail startup if the gate fails, rather than
   silently spawning a competing embedded producer.
6. For rollback, stop the standalone source timer/service, restore the reviewed
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
