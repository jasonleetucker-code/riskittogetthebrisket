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
POSIX modes. No distribution/package was installed. A subsequent bounded,
read-only SSH attempt using the existing configured host alias failed with
`Permission denied (publickey,password)` before remote commands could execute.
No credentials, SSH configuration, host files or units were changed. Installed
ownership and host-capacity measurements therefore remain inaccessible; this
was an authentication failure, not an automatic approval-review rejection.
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

Shadow startup/cache recovery primes the legacy memory representation only.
It cannot replace the durable accepted pointer while a standalone bootstrap is
attesting it. In `server.py`, durable shadow publication is admitted only by
the fresh source callback running under `producer.lock`; cache hydration never
qualifies, even if it carries a lease marker. A first shadow artifact therefore
waits for an accepted source cycle. Existing accepted artifacts survive startup.

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
    installer is changed by this historical rollout step. The default private
    layout requires the worker and server to share `RISKIT_SERVING_DIR` and its
    application user. The later opt-in reader-group layout below instead requires
    distinct producer/web UIDs and explicit provisioning. Keep either root
    outside every static HTTP mount; verify its actual directory permissions.
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

### Prepared league adoption

Canonical and league artifacts can arrive on separate schedules. The web
`LeagueServingReader` captures a bound canonical-board/league-bundle pair per
active league. Requests retain that pair through the response. A missing or
rejected replacement leaves the accepted pair available; a healthy league can
advance independently of another league's failure. Existing roster-context
expiry still applies off-request, including when a newer canonical load fails.
Startup primes the reader before accepting prepared requests. This is local
generation coherence, not evidence that a deployed worker or timer is running.

### Artifact maintenance and capacity

`src/serving/artifacts.py` remains the single storage owner. Automatic publication
admission and `python scripts/prune_serving_artifacts.py --root <private-root>`
use the same policy. The command defaults to dry-run; add `--apply` to execute
eligible deletion. A blocked report exits 2. Pins use
`--apply --pin ASSET KEY GENERATION LABEL`; removal uses `--apply --unpin LABEL`.
Review the bounded report before an operator maintenance application.

The default is 48 hours and at least three accepted generations per partition,
with a budget of the smaller of 4 GiB or 10% of filesystem capacity. The existing
free-space floor remains in force. `RISKIT_SERVING_MAX_BYTES` and
`RISKIT_SERVING_MIN_FREE_BYTES` apply consistently to web and all producers;
the maintenance CLI also accepts explicit byte limits. Age follows accepted
publication history, not refreshed observation timestamps. Unknown historical
acceptance time is protected, not guessed from mtime.

Current generations, the minimum accepted history, explicit rollback pins,
ownership proofs and their transitive canonical dependencies survive pruning.
Equivalent logical canonical variants are retained conservatively. Old eligible
generations are pruned first; pressure can shorten the 48-hour window only for
additional unprotected generations and reports that explicitly. If protected
bytes plus the candidate cannot fit, publication is rejected before deletion
and the accepted pointer stays selected. Corrupt or uncertain references block
pruning. Source archives, historical databases, forensic evidence and unrelated
unowned directories are outside this deletion owner.

The root store lock precedes partition publication locks. Readers copy complete
generation bytes under the root lock before deletion can occur; request handlers
continue using captured memory. Validation happens before locked admission and
uses private unlocked helpers inside the store, avoiding recursive acquisition.
Retention inventory hashes retained bytes under that lock; sustained overlap
measurements are required before claiming its cost is bounded on the host.

Admin-only `/api/performance` exposes cached artifact bytes/counts, oldest
retained publication, protection/capacity state and bounded failure diagnostics.
The background status reader consumes the bounded persisted maintenance report;
the HTTP request does not scan disk. Missing reports remain unobserved. Local
resource measurements do not authorize worker memory limits: measure the actual
Linux host and the combined service/worker peaks before assigning them.

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

## Prepared credential deployment prerequisites

The shared application user required by the compatibility instructions above is
not signer/verifier isolation. Do not install a producer private key in the shared
.env or claim that an omitted web variable removes same-user access. Do not change
unit users alone: current 0700 directories and 0600 files/locks prevent a separate
verifier from reading new artifacts and acquiring read/write store locks.

Split-user deployment uses the opt-in permission-aware creation in ArtifactStore
and the least-privilege queue layout in producer_status described below. Preserve private
defaults, safe path checks, atomic replacements, pending claims, stable lock inodes
and source/league ownership. A one-time chmod, UMask/default ACL alone or read-only
store mount is insufficient. Test new publication and replacement under actual
service UIDs. Web must read/traverse artifacts and acquire stable locks without
broad artifact-root rename/publication authority. Queue admission/claim must retain
same-filesystem atomic replacement and coalescing. Local and distinct-UID Linux CI
checks pass; installed service-context validation remains an activation gate.

Public pin and policy code require a trusted deployment owner, not web or artifact
publisher write authority. Producer-only private credentials stay outside store,
shared environment, frontend access and web process/privilege reach. Canonical and
league producers retain distinct duties; news is not automatically a signing owner.
No numerical worker resource limits follow from checked-in templates or Windows.

## Single-pin rotation and rollback preparation

There is one public pin, not a keyring. A new pin rejects old certificates, while
captured last-known-good memory is not reverified per request. Coordinated restart
is required for immediate withdrawal. Do not call key-file replacement revocation.

The existing --accepted-raw option only handles a missing canonical generation;
it cannot override an old-key verification failure in an existing store. Before
changing trust, verify and capture the accepted raw input using the old trusted
reader, record its private hash/identity, and prepare a fresh private store through
strict existing producer publication with the new matching key and pin. Input
handover is a reviewed private operation, not an invented rotation CLI. Never
select the newest archive or blindly re-sign unchecked bytes.

ProducerConfig.serving_root and producer.lock follow --artifact-root. Fresh-root
bootstrap does not share the old lease. Stop new old-root admissions and drain
embedded/standalone canonical work before this maintenance operation; preserve
queued refresh obligations and coordinate GitHub/deploy owners separately. Normal
same-root first bootstrap remains lease-serialized. Use the existing bounded
--artifact-root/--accepted-raw invocation only after verified handover and rollout
authorization. Require strict proof before lease release and coherent league
artifacts before readers switch pin/store together and restart/revalidate.

Deploy initially with RISKIT_SERVING_MODE=legacy and prepared frontend disabled; require healthy
legacy baseline and shadow parity/resources/recovery. Disable embedded recurrence
before standalone recurrence. Retain GitHub additional feeds and dedicated DLF/IDP
Show coverage. Verify authenticated scoring/league/stale/200/304 and queue behavior.
For ordinary rollback stop standalone recurrence first, restore compatible code,
pin, store and legacy configuration, restart and verify ownership/freshness. Keep
immutable generations and receipts. Do not restore a compromised key as rollback;
withdraw it and strictly rebuild trusted inputs. Never delete locks or run two
unrestricted owners. All production actions retain separate authorization gates.

### Opt-in reader-group filesystem layout

`RISKIT_SERVING_READER_GID` enables the POSIX-only group layout. Omit it to
retain the existing private store and root-level request markers. Use the same
numeric reader group for web and producers; the web UID must remain distinct
from the producer/provisioner UID. The frontend does not require store access.
This setting does not grant or create operating-system users/groups.

Provision a new store as the producer/provisioner, with an already traversable
parent, before starting readers:

```text
RISKIT_SERVING_READER_GID=<provisioned numeric group>
RISKIT_SERVING_DIR=<reviewed store path>
python scripts/prune_serving_artifacts.py --apply --provision-access
```

This explicit operation provisions the root with 2750, stable shared store and
request locks with 0660, and the `requests/` directory with 2770. Subsequent
producer publication creates immutable directories with 2750 and immutable,
pointer, observation, history and status files with 0640. Queue markers use 0660;
producer claims remain in the protected root with 0640.
Publisher/coordinator/source leases remain producer-owned. Explicit creation
modes apply to replacements too, rather than relying on UMask alone. Existing
incompatible permissions are rejected and never automatically widened.

Readers can copy accepted generations and create bounded request markers, but
the producer-owned root prevents them replacing accepted pointers, generation
directories or shared-lock inodes. Private signing keys and their parent must
remain producer-only outside this store; public pins and code must be immutable
to the web UID. A group or environment setting alone does not prove these UID,
parent-directory or process-environment boundaries.

The source/league path units watch both legacy and opt-in marker locations.
Enabling the group layout with a legacy root-level request still pending fails
closed, preserving that request. Drain and account for queued obligations under
the old owner before a reviewed offline store/permission migration; do not remove
markers to silence the refusal. A new store has a new source lease, so stop and
drain old ownership before bootstrap as described above. Do not switch only the
web environment while producers retain another queue layout.

The isolated `Prepared serving permissions` CI job runs actual distinct numeric
UIDs on Linux and refuses a skipped cross-UID test. Windows mode tests are not
permission proof. Before production activation, repeat allowed/denied access,
new-publication adoption, queue wakeup, key isolation and child/FD recovery under
the actual installed service identities. Shared flock participants can cause
bounded lock timeouts by holding a lease; this availability assumption does not
give the web signing authority.

### Install-only preparation with distinct principals

The existing installer accepts `--prepared-units-only`. Supply existing non-root
`PRODUCER_USER`, `WEB_USER`, `SERVING_READER_GROUP`, and reviewed absolute
`APP_DIR`, `VENV_DIR`, `PRODUCER_ENV_FILE`, `WEB_ENV_FILE`, `SERVING_DIR`,
`SIGNING_KEY_FILE`, and `PUBLIC_PIN_FILE` paths. Provision the opt-in store first.
The producer and web environment files must be distinct and external to the code
and store, as must the signing key and public pin. Keep the private credential
out of the web environment and outside web-readable or writable paths.

```text
bash deploy/install-systemd-service.sh --prepared-units-only
```

This mode renders and verifies seven prepared worker/timer/path units, installs
only into confirmed inactive and disabled/static (or absent) destinations, and
runs daemon-reload. It creates no accounts, enables or starts no unit, modifies
no web service or serving flag, and performs no ownership cutover. Managed store,
reader-group and key/pin paths are supplied after EnvironmentFile processing by
ExecStart's explicit environment assignments. Unknown/failed identity, access or
unit-state probes reject installation. Successful access probes check the actual
impersonated UID; a failed sudo command is not evidence of credential isolation.

These admission checks inspect files and immediate parents. Before activation,
verify every ancestor, service namespace, code/runtime path and environment under
the actual installed principals; the installer does not prove those boundaries.
Use a trusted deployment owner for code and the verification pin. Prepare the web
principal/drop-in separately, preserving legacy mode until its rollout gate opens.

Installation may fail after replacing an inactive subset. Preserve copies of the
previous unit files before the operation; restore those copies and daemon-reload,
or resolve the failure and rerun the reviewed install-only command. Never restart
or enable units as an implicit recovery action. An inactive static service is a
valid rerun destination. Active/enabled or unknown state requires a separate
reviewed maintenance/cutover action. Numerical limits remain subject to actual
host headroom measurements.
