# Sitewide remediation inventory — 2026-11-06

Directive: `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`. Machine-readable inventory:
`inventory.json`; generated portfolio + traceability tables: `INVENTORY_TABLES.md`; both from
`build_inventory.py` (fails on any unmapped row). Delegated decisions: `DECISIONS.md`.

This is not a second roadmap. It maps every input row to one canonical work item (CW-01 … CW-47) and points at the
existing owners; authorization stays in `docs/EXECUTION_PLAN.md`.

## 1. Current-state baseline (Deliverable A) — evidence-dated

Measured 2026-11-06 12:30–13:20Z. "Live" = public `https://chaseupside.com` endpoints, read-only.

| fact | value | evidence |
|---|---|---|
| `origin/main` | `a2a21ebb` (all commits since 2026-11-04 are automation: DLF / IDP Show / data refreshes, Sharp smoke, Hill evidence) | `git log` |
| production build | `80c52dbf` (automated refresh, 2026-11-04 00:27Z) — production has not deployed since | live `/api/status` `build.commit` |
| Deploy Production | every run since 2026-11-05 02:27Z (#3723–#3729) failed `Validate Build Inputs` on the Sonny Styles test; a second failure (Mahomes, `test_idptc_cutoff_readiness::test_5`) was hidden behind it by `pytest -x` | Actions logs; PR #2061 comment |
| `/api/health` | **503 degraded**: data 34 h stale, scrape stalled at `browser/launch`, `source_health_ok: false` | live |
| scraper | 0 / 9 successful runs in 24 h; last success 2026-11-05 02:35Z; three `blocked` runs (KTC anchor `ktcSfTep` missing, up to 93 min), then every run `BrowserType.launch: Timeout 180000ms` with ~15–20 min wall clock per failure | live `last_n_scrapes`, `run_events` |
| GitHub-side collectors | KTC CSVs refreshed 2026-11-06 12:35Z — KTC is reachable from CI; the box-side failure is environmental | `git log -- CSVs/site_raw/ktc*.csv` |
| flags (live) | `waiver_advisor` ON, `idp_streaming` ON, `roster_construction` ON, `dlf_offense_only_vote` ON (hold), `brisket_trade_advisor` OFF, `source_freshness_schedule_v2` OFF, `trade_multi_team_analysis` OFF | live `/api/status.featureFlags` |
| security headers | HSTS, CSP `frame-ancestors 'self'`, XFO SAMEORIGIN, nosniff, Referrer-Policy, Permissions-Policy present; `Server: nginx` with no version; `/openapi.json` 404; `/api/docs` 401 | live `curl -I` |
| backups | `legacySqliteBackup` healthy 10.6 h; `stateBackup` canonical root `unverifiable / permission_denied`; writer-fallback root 56.8 h stale (14 generations) | live `backup_health` |
| served sources | 20 sources serving; `idpTradeCalc` picks byte-identical 26 days (severely stale); `idpShowCombined` and `fantasyNavigatorSf` quarantined by freshness; `fantasyProsIdp` severely stale | Validate PR source-health step |
| rehabilitation reviews | 7 plans past their review date (2026-10-31 / 11-01) + one source without an entry | Validate PR source-health warnings |
| open issues / PRs | 68 / 19 (+ 5 opened this session: #2061–#2065) | GitHub API |

### Supersession corrections (verified, not rebuilt)

All merged on `main`: Roster Construction readiness, activation and nav (#2040, #2041, #2044) and the
unfinalized-week fix (#2058) and nav-capability refresh (#2057); 2025 slots stay unavailable; #2006 deep-tail rookie
restore; #2031 / #2032; UX audit #2051; AMATH master #2054 (superseded #2053, never merged); Week 9 freeze receipts
(#2046 ROS, #2048 six-model); IDP Show library audit #2042; shadow IDP challengers #2043; streaming gap decomposition
#2045; nginx hardening #2049. Production now carries `roster_construction` ON. The 2026-11-01 handoff's "prod flag
`roster_construction` OFF" and "P-1 live nginx sends no headers" are superseded by the live readings above.

## 2. Wave 0 results (this session)

| lane | outcome | PR | state |
|---|---|---|---|
| W0-A deploy blocker 1 | Sonny Styles: the DLF-restore board's Hampel filter rejects two valid votes (CQ-65); the held board keeps them. The test invariant was incomplete; production correct. Tightened, not loosened | #2061 | reviewed APPROVE; CI red only on blocker 2 |
| W0-A deploy blocker 2 | Mahomes: withholding a source cures other Hampel rejections and raises confidence — a confidence-owner gap against the 2026-10-07 owner rule | branch `claude/confidence-cured-rejection-guard` | IMPLEMENTING |
| W0-B scraper | reaper only walked ppid descendants after a run; reparented Chromium in the service cgroup escaped it. Pre/post cgroup-scoped reap + numbers-only box diagnostics; review hardening (systemd-main-process scope, strict Chromium matcher, off-loop probe, MiB rounding) in progress | #2062 | reviewed APPROVE + hardening |
| W0-C capture | Week 10: capture timer Tue/Thu/Sat/Sun 14:10Z precedes the 2026-11-12 kickoff and is reconciled by every deploy; both preregistered receipts pushed 2026-11-06T12:46:58Z with byte-identical frozen and code blobs; Week 9 archive presence unknowable from git | #2065 | evidence pushed |
| W0-C auction | nothing ran `--record-snapshot` automatically; first-valid-wins daily capture added; review found a missing `SuccessExitStatus` (fix in progress) | #2063 | changes requested → fixing |
| W0-D backups | root writer `chmod 700`s the canonical root while the backend runs as `dynasty`; `analyst_ledger.sqlite` was unprotected; group-list 0750, analyst ledger, scratch restore verifier | #2064 | reviewed APPROVE |
| W0-D security | W22-F001 / F002 / F003 already fixed in code; W00-F001 public by documented design, 4.4 s cold / 0.9 s warm (was 13.2 s) | — | recorded (DD-06, DD-07) |

## 3. Master-site audit recount (the "268 open" figure)

Re-ran `docs/master-site-audit/tools/verify_closure.py --rerun` against current main on a local backend (225 s;
no production writes). **The August "268 open" never measured reproduction:** the tool's `open` means "no commit
claims to close it and the repro passed the read-only filter"; it never compares repro output with `expected`.

Layered classification of all 431 findings (P0 9, P1 85, P2 181, P3 156):

| class | count |
|---|---:|
| repro rotted (fixture, scratch script, `.venv`, `node_modules` or :3000 frontend gone) | 159 |
| ran clean, output changed or non-quantitative — not adjudicated | 126 |
| unsafe to re-run (writes / POSTs) | 94 |
| reproduces the August observation (≥ 80 % of numbers match) | 16 |
| repro exits non-zero | 14 |
| still open, manually confirmed | 12 |
| closed, manually confirmed | 10 |

**P0 + P1 (94):** 8 demonstrably closed, 8 demonstrably open, 78 unresolved (44 rotted, 22 unsafe, 12 unadjudicated).
Verified still open at P1: W00-F001 (public by design, DD-06), W06-F001 (split-identity ghost rows, e.g. Jamarion /
Jam Miller), W10-F003 (rookie optimizer 0 rows at budget advantage 1.0–3.0), W13-F003 (BDVM STRONG_SELL 570 of
699), W20-F005 (Terminal pick value ≠ league analysis), W27-F001 (IDP rows 100 % edge "none"), W30-F002 (playoff odds
at 0.0 / 1.0), W30-F008 (Hill percentile table byte-identical to August). Verified closed: W20-F002 (P0), W00-F002,
W06-F003, W11-F001, W19-F002, W26-F001, W27-F002, W30-F001. Per-finding classes: `master_audit_recount.json` (raw repro
output withheld because it carries local paths); adjudicating the 78 unresolved P0/P1 findings is CW-40 work
(rebuild rotted repros as committed fixtures, never re-trust the claim). Tool limitation recorded as NEW-02.

## 4. Closure and remaining-blocker report (Deliverable I) — as of this checkpoint

1. **Actively implementing:** CW-47 (confidence guard), CW-02 hardening (#2062), CW-04 fix (#2063); coordinator
   records.
2. **Dependency blocked:** Deploy Production → needs #2061 **and** the CW-47 PR; scraper recovery and the backup
   permission fix land on the box only through a successful deploy plus, for backups, an operator re-install.
3. **Awaiting statistical evidence:** CW-13, CW-15 – CW-17, CW-22, CW-30 – CW-36 (no promotion without the gates).
4. **Genuine external / owner action:** box operator — `bash deploy/backup/install_state_backup.sh`, then
   `scripts/verify_state_backup_restore.py` (commands in #2064); confirm `systemctl list-timers
   '*weekly-projection-capture*'` and the w9 / w10 archive timestamps (W0-C); confirm direct `:8000` exposure is closed
   (MD-24); decide whether `/api/draft-capital` pick dollars should stay public (DD-06 keeps today's documented
   behaviour). Optional off-host backup copy (`OFFBOX_RSYNC_DEST`) is operator opt-in.
5. **Explicitly paused:** CW-42 (League Tycoon, DFS, paid analyst feed).
6. **Rejected / superseded:** CW-44 (AMATH S51–S53 blocked, S59–S63 rejected); #2053.

Everything else has a named next unit in `INVENTORY_TABLES.md`.
