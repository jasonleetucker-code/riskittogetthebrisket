# V1-136 qualification slice — The IDP Show acquisition audit

**Status:** `FEATURE_GREEN` / `READY_FOR_INTEGRATION` (audit only — no code change)
**Lane:** 8 (Source Acquisition / Cross-Position Bridge)
**Scope:** Evidence toward `V1-136` ("Source acquisition is secure and its
auth state is explicit", `docs/VERSION_1_COMPLETION_CONTRACT.md` §3, owned by
L8, acceptance level L2, status `NOT STARTED`). **This document is evidence
for Integration's review. It does not mark V1-136 `VERIFIED`, does not edit
`VERSION_1_COMPLETION_CONTRACT.md`, and self-promotes nothing.**
**Prompted by:** repeated `chore(idpshow): automated refresh` commits on
`main` at ~2-hour intervals throughout 2026-08-20, making "IDP Show
acquisition is unavailable in production" an unsupportable blanket claim.
Confirmed at `origin/main` `8bf4cca66` ("chore(idpshow): automated refresh
2026-08-20T18:32:10Z") and the 19 preceding commits from the same bot
identity, exactly 2 hours apart, back through 2026-08-19T04:32.

## Answers to the nine audit questions

### 1. What mechanism performs the successful automated refresh?

A **dedicated production systemd timer**, not GitHub Actions and not
`server.py`'s in-scrape call (which exists as a secondary path — see §7).

```
deploy/systemd/dynasty-idpshow-fetch.timer   — OnCalendar=*-*-* 00/2:32:00 UTC
  → dynasty-idpshow-fetch.service            — oneshot, ExecStart=deploy/idpshow_fetch_and_push.sh
    → deploy/idpshow_fetch_and_push.sh       — dedicated clone at /var/lib/idpshow-fetch/repo
      → scripts/fetch_idpshow.py             — the actual scrape + parse
```

The timer's 2-hour cadence at minute :32 matches the observed commit cadence
exactly. The push script runs in an isolated clone (never the live deploy
directory), resets to `origin/main` before each run, and commits/pushes under
a dedicated identity (`IDP Show Fetch (prod) <idpshow-fetch@brisket-prod-1.local>`)
with its own SSH deploy key — separated from both the app's runtime identity
and the CI bot's.

### 2. Is the source public or credential-dependent?

**Credential-dependent**, precisely stated: the underlying data payload
(Datawrapper's `dataset.csv` CDN endpoint) is itself unauthenticated once its
chart ID is known — but reaching that chart ID requires a successful fetch of
`theidpshow.com/p/idp-dynasty-rankings`, which is paywalled by Substack. The
fetcher's control flow reads session cookies first and aborts before any
network call if none are present (`scripts/fetch_idpshow.py::main`, the
`SESSION_PATH.exists()` guard). So end to end, the acquisition path is
credential-dependent, and no code path bypasses that.

### 3. If credential-dependent, what explicit state is recorded when credentials disappear?

Two layers, and the honest finding is that they are **not fully unified**:

- **Fetch layer.** `_looks_paywalled()` detects Substack paywall sentinel
  strings and the fetcher exits 1 with a specific stderr message ("session
  appears expired — article still paywalled"). `idpshow_fetch_and_push.sh`
  catches any nonzero exit, logs to the systemd journal, and **does not touch
  the CSV or the success stamp** — last-good data persists untouched. This is
  real and correct fail-closed behavior.
- **Persisted/queryable layer.** Neither the CSV nor
  `data/scrape_state/idpShow_last_success` records *why* a cycle failed —
  only whether the stamp advanced. `config/source_staleness.json` closes part
  of that gap at the monitoring level: `idpShow` is `soft`-flagged with a
  24h threshold and a 72h `softEscalateHours` — a stale stamp is reported
  everywhere (site banner, alerts, freshness-watchdog summary) starting at
  24h and hard-fails `scheduled-refresh.yml` past 72h. That is an explicit,
  bounded staleness state, not silence.
- **The gap.** What is *not* recorded anywhere durable is the specific
  failure *class* — auth-expired vs. 0-rows-parsed vs. below-floor vs.
  network error all collapse to the same "stamp did not advance" signal at
  the persistence layer. The distinction exists only in transient VPS journal
  output, which is outside this repository and outside this audit's reach.
  `src.sources.acquisition_state.AcquisitionOutcome` (Lane 8 PR A) has the
  vocabulary to carry this distinction (`AUTH_REQUIRED` vs `UNAVAILABLE` vs
  `PARSE_FAILED`), but neither `fetch_idpshow.py` nor
  `idpshow_fetch_and_push.sh` emits it today. **This is the honest remaining
  V1-136 blocker** — see the summary below.

### 4. Are secrets supplied only through approved secret/env mechanisms?

Yes, on both paths that exist:

- **Production (the active path).** `idpshow_session.json` lives only at
  `$IDPSHOW_FETCH_WORK_DIR` (default `/var/lib/idpshow-fetch`) on the VPS,
  human-minted by an operator pasting browser cookies, never committed
  (`.gitignore:37` — `*_session.json`, covering this file by pattern). The
  push script copies it into the dedicated clone per run and copies it back
  unchanged (the fetcher only reads the jar). The GitHub push uses a
  dedicated SSH deploy key at a filesystem path, not an inline credential.
- **CI (dormant today).** `.github/workflows/scheduled-refresh.yml` reads a
  GitHub Actions secret `IDPSHOW_SESSION_JSON`, writes it to the same
  gitignored filename, validates its *shape* (non-empty `cookies` array)
  before spending a request, and wraps the whole block in
  `trap 'rm -f idpshow_session.json' EXIT` so the file is removed on every
  exit path — explicitly reasoned in the workflow's own comment: "relying on
  a gitignore entry to keep a live session cookie out of a public-ish commit
  is one edit away from leaking it." This path currently no-ops in this
  environment (no such secret is configured here — see §9's
  `LOCAL_AUTH_UNAVAILABLE` distinction).

No script constructs a credential from a literal, an argument, or a
committed file.

### 5. Can any token/cookie enter logs, committed artifacts, or error text?

No occurrence found. `grep`ed every `print`/`log`/`err`/`echo` call in
`scripts/fetch_idpshow.py` and `deploy/idpshow_fetch_and_push.sh` for cookie
or session-value leakage — zero hits. Diagnostic output is limited to
structural facts: chart ID, resolved Datawrapper version, row counts, and (on
a 0-row parse) the raw CSV **header** line for schema-drift diagnosis — never
row values, never cookie values. `_load_cookies()` sets cookie values
directly into the HTTP session object; nothing downstream serializes them.
The committed CSV (`name,position,rank`) and the success stamp (a bare epoch
integer) carry no credential material by construction.

### 6. What source_as_of/freshness evidence is retained?

`data/scrape_state/idpShow_last_success` — a Unix epoch of the last
*successful fetch*, stamped by the push script immediately before it commits.
This is **fetch freshness, not content freshness** (the same distinction
`config/source_staleness.json`'s `contentStaleness` block draws for other
sources): it proves a fetch succeeded, not that the vendor published
anything new. There is no vendor-stated `source_as_of` equivalent — unlike
`fetch_dynasty_nerds_idp.py` (Lane 8 PR C), which reads the vendor's own
JSON-LD `dateModified`, the Datawrapper CSV carries no publish-date field for
this fetcher to read, and none is invented.

### 7. Does a fetch/schema/auth failure remain explicit rather than producing a healthy empty CSV?

Yes, at every stage, verified by reading `scripts/fetch_idpshow.py::main` in
full:

| condition | result |
|---|---|
| no session file | exit 1, no fetch attempted |
| paywall detected | exit 1, no CSV write |
| Datawrapper iframe not found | exit 1, no CSV write |
| version-redirect chain broken | exit 1, no CSV write |
| dataset HTTP failure | exit 1, no CSV write |
| 0 rows parsed | exit 1, no CSV write, raw header printed for diagnosis |
| rows below the 150-row floor | exit 2, no CSV write, "preserving last-good CSV, not overwriting" |
| `--dry-run` | never writes, regardless of outcome |

`_write_csv` is reached on exactly one path: parsed rows ≥ 150. Combined with
the push script's "keep previous CSV/stamp on any nonzero exit," a failure of
any kind never produces a healthy-looking empty or truncated board.

### 8. Is the row count/provenance stamped truthfully?

The row count itself is truthful — the 150-row floor and the 0-row guard
both *prevent* writing rather than pad or fabricate, and `main()` logs the
real parsed count. But the **artifact carries no provenance fields**: the CSV
is bare `name,position,rank` with no source name, no per-row or file-level
timestamp, no row-count header. Row count is only visible via transient stdout
and by counting the file. This is weaker than the PR A/C archive model
(`ArchivedRow` + `AcquisitionOutcome`, which stamp `row_count`, `state`,
`reason`, `observed_at` as structured, queryable data) — `idpShow.csv` is
exactly the "de facto vocabulary" shape Lane 8's foundation work exists to
replace, just not yet migrated for this source.

### 9. Is the current ordinal-only nature preserved end to end?

Yes, confirmed at three independent points:

- **The fetcher.** `_parse_dataset()`'s docstring states explicitly: "drop
  every other column (combine metrics, college notes, etc.)." The written
  schema is exactly `name,position,rank` — no value column exists to leak
  into.
- **The registry.** `src/api/data_contract.py`'s `idpShow` entry (line
  ~1519) documents that the raw vendor feed *does* carry a `TRADE VALUE`
  column, and states why it was already rejected as a cardinal signal:
  *"the source's TRADE VALUE column is draft-pick-equivalent text ('1st +
  2nd', '3rd') rather than a numeric scale."* This closes the speculative
  question this audit was asked to check (is there a hidden cardinal
  quantity being discarded) — there is a discarded column, but it is
  non-numeric trade language, not a cardinal value. No further action is
  warranted per the explicit instruction not to add IDP Show to the bridge
  ladder without an independently proven cardinal quantity — none exists.
- **Production wiring.** `idpShow` is registered with `is_backbone: False`,
  `needs_shared_market_translation: True`, `weight: 1.0` — an ordinal,
  IDP-only specialist source whose within-IDP rank is translated into
  combined-market space by the bridge owner (Lane 8 PR A/B,
  `src/bridges/*`). It is **already** the exact class of source PR B's
  vote-withholding repair protects: when no usable bridge exists, `idpShow`'s
  vote is withheld rather than passed through untranslated (confirmed by
  code inspection of `src/api/data_contract.py`'s Phase 1 translation branch
  and by `tests/api/test_curve_routing_coordinate_pool.py`'s
  `TestUntranslatedIdpRankKeepsIdpCurve` suite, which names `idpShow`
  directly in its IDP-vet fixture set). No new wiring was needed or added by
  this audit.

## Summary answers, in the format requested

| field | value |
|---|---|
| exact head audited | `origin/main` `8bf4cca66` (and 19 preceding automated commits, same cadence) |
| acquisition mechanism classification | **prod systemd timer** (`dynasty-idpshow-fetch.timer` → `.service` → `deploy/idpshow_fetch_and_push.sh` → `scripts/fetch_idpshow.py`), isolated clone, dedicated bot identity and SSH key. Secondary, currently-functional path also exists in `server.py`'s in-scrape call; a third, CI-based path exists in `scheduled-refresh.yml` gated on the `IDPSHOW_SESSION_JSON` secret and self-skips without it |
| public / authenticated status | **authenticated end-to-end** (Substack paywalled article gates the credential-free Datawrapper CDN payload behind a cookie-authenticated first hop) |
| secret-handling proof | gitignore pattern `*_session.json` (verified, not merely asserted) + prod-local-file-only storage + CI secret written to the same gitignored filename with an unconditional `EXIT` trap; zero cookie/token value found in any log, print, or committed artifact across both scripts |
| failure-state semantics | fail-closed at every stage (8-row table above); **but not yet structured** — failures collapse to "stamp did not advance," differentiated only by ephemeral VPS journal text outside this repo. `soft`/`72h` staleness escalation at the monitoring layer is explicit and bounded |
| source_as_of | `data/scrape_state/idpShow_last_success`, a fetch-success epoch — **fetch freshness only**, no vendor-stated content date exists to read |
| evidence class | **ORDINAL** — confirmed at the fetcher, the registry comment (rejecting the vendor's own non-numeric `TRADE VALUE` column), and the pipeline wiring (`needs_shared_market_translation: True`, `is_backbone: False`) |
| mayVote (ordinal, translated) | **true** — already registered and already correctly protected by the Lane 8 PR B withholding repair; no change needed |
| mayVote (as a cardinal bridge) | **false / not applicable** — no cardinal quantity exists to prove, per the registry's own prior investigation of the vendor's `TRADE VALUE` column |
| L2 measurement available | yes — mechanism traced to its systemd/script source, cadence cross-checked against 20 real commits, ordinal-only schema confirmed by direct file inspection (`git show origin/main:CSVs/site_raw/idpShow.csv`), zero code changes required or made |
| remaining V1-136 blocker | **failure-state structuring**: migrate `fetch_idpshow.py` / `idpshow_fetch_and_push.sh` to emit an explicit `src.sources.acquisition_state.AcquisitionOutcome` (or an equivalent persisted record) distinguishing `AUTH_REQUIRED` from `UNAVAILABLE` / `PARSE_FAILED`, so "credential lapsed" and "vendor changed schema" and "network down" stop being one undifferentiated non-advancing stamp. This is a acquisition-layer instrumentation change, not a methodology decision, and is proposed here as evidence — not self-promoted, not implemented in this audit |

## Sandbox vs. production distinction

This session has **no** `idpshow_session.json` and **no**
`IDPSHOW_SESSION_JSON` environment variable — confirmed by direct filesystem
and environment inspection, no value printed. That is
**`LOCAL_AUTH_UNAVAILABLE`**, a property of this sandbox, and it is a
*different fact* from production, where the same mechanism has produced 20
consecutive successful automated commits at exactly its configured 2-hour
cadence — that is **`PRODUCTION_ACQUISITION_ACTIVE`**. The two states are
recorded separately here rather than collapsed to a single `AUTH_REQUIRED`,
per this audit's own instruction: an inability to authenticate *in this
environment* is not evidence about whether production can.

## What this audit did NOT do

- Did not convert `rank` → any `value` field, anywhere.
- Did not add `idpShow` (or its offense-side twin, which does not exist) to
  `config/bridges/bridges_v1.json` or any cardinal bridge candidacy.
- Did not choose bridge weights, precedence, confidence arbitration,
  tie-breaking, or touch `multi_bridge_ladder`.
- Did not touch Dynasty Dealer's `PENDING` status (unrelated to this slice;
  it remains `PENDING`, does not vote, per Lane 8 PR B).
- Did not mark `V1-136` `VERIFIED`, `IMPLEMENTED_UNVERIFIED`, or any other
  status, and did not edit `docs/VERSION_1_COMPLETION_CONTRACT.md`.
- Did not touch PR #993 (frozen, per instruction — Claude 5 owns its
  reconciliation with #983 and merge).
- No credential value of any kind appears anywhere in this document, in any
  commit on this branch, or in any test.
