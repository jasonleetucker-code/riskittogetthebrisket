# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-06 ~13:45Z.** Agent-OS-Receipt `47a8b19f`. Session `session_01BGLcxPv9489uMYWnm3GbTF`.

## Mode
- Owner directive 2026-11-06 ("MASTER SITEWIDE AUDIT REMEDIATION…"): structured record
  `docs/owner/SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`; intake MD-38 … MD-46; execution-plan section at the top
  of `docs/EXECUTION_PLAN.md`; register section "Sitewide remediation directive (2026-11-06)"; agent-made decisions
  `docs/audits/remediation_2026-11-06/DECISIONS.md` (DD-01 … DD-10).
- Inventory: `docs/audits/remediation_2026-11-06/` — 404 input rows (incl. MD-38…46) + 7 discovered → CW-01 … CW-47.
  Regenerate with `python docs/audits/remediation_2026-11-06/build_inventory.py` (fails on any unmapped row).

## Production (live, read-only, 2026-11-06 12:35Z)
- Build `80c52dbf` (2026-11-04 00:27Z). **No deploy since:** every Deploy Production run from 2026-11-05 02:27Z fails
  the hard gate. Two failures, the second hidden by `pytest -x`: Sonny Styles (fixed, #2061) and Patrick Mahomes
  (CW-47, confidence-owner gap; branch `claude/confidence-cured-rejection-guard`).
- `/api/health` 503: data 34 h stale; scraper 0/9 in 24 h, stuck at `browser/launch` (180 s launch timeout taking
  ~15–20 min). A deploy restarts `dynasty.service` — the reachable remedy (#2060).
- Flags: `roster_construction`, `waiver_advisor`, `idp_streaming`, `dlf_offense_only_vote` ON;
  `brisket_trade_advisor`, `source_freshness_schedule_v2`, `trade_multi_team_analysis` OFF. Security headers live.

## Open PRs this session (all subscribed)
| PR | content | state |
|---|---|---|
| #2061 | W0-A Sonny Styles test invariant (recovered evidence) | reviewed APPROVE; red only on Mahomes → **becomes the release train**: fold the reviewed CW-47 branch into it, then merge on green |
| CW-47 | confidence: withheld vote curing Hampel rejections; rollback flag; blast radius | worker implementing; needs independent review |
| #2062 | W0-B cgroup-scoped orphan reaping (opt-in `SCRAPE_REAP_SERVICE_CGROUP=1` in the unit), numbers-only box diagnostics | reviewed + delta reviewed APPROVE; CI red on base failure |
| #2063 | 2027 pre-auction snapshot automation (exit 5 terminal skip, 6 h board freshness) | delta re-review running |
| #2064 | backup group-list 0750, analyst ledger, restore verifier | reviewed APPROVE; CI red on base failure (commented) |
| #2065 | Week 10 freeze receipts (IDP six-model + ROS), pushed 2026-11-06T12:46:58Z | green; merge any time |
| coordinator | this handoff, inventory, intake, plan, register, claims | branch `claude/coord-remediation-inventory-2026-11-06` |

Merge order: #2065 → train (#2061 + CW-47) → confirm Deploy Production green and `/api/status` build advances → bring
#2062 / #2063 / #2064 up to date with main, re-run CI, merge → read live `box_resources` and `backup_health`.

## Box-operator actions (cannot be done from a session)
- `bash deploy/backup/install_state_backup.sh`, `systemctl start riskit-state-backup.service`, then
  `python3 scripts/verify_state_backup_restore.py --scratch-dir /var/tmp --only temporal_ledger --only intel_ledger`
  (#2064 body).
- `systemctl list-timers '*weekly-projection-capture*'`; `ls -l --time-style=full-iso
  data/projections/weekly_archive/2026/w9 …/w10` to confirm pre-kickoff captures.
- Confirm direct `:8000` exposure is closed (MD-24).

## Next dependency-ready units (after Wave A lands)
CW-07 low items (frontend login fallback hardening), CW-08 scoring parity census, CW-09 trade identity fixtures,
CW-10 FAAB fixtures, CW-19 hide Monte Carlo win-rate (owner decision ODR-SR-MC-WINRATE), CW-21 relabel "arbitrage",
CW-11 rehabilitation reviews (7 overdue), CW-16 prospective IDP evaluation runner (does not exist yet; NEW-07),
CW-40 adjudicate the 78 unresolved P0/P1 master-audit findings (`master_audit_recount.json`).

## Hazards
- Disk: each worker worktree is a full checkout; remove finished worktrees (`git worktree remove --force`) or the
  disk fills (it did once this session).
- Deploy and Validate PR run `pytest -x`: one data-coupled failure hides the next. Confidence/withholding subset:
  `pytest tests/api -m "not livedata" -k "confidence or cutoff or hold or withheld or dlf or idptc or freshness or
  family or signals or lost"` (~100 s).
- Local full hard gate is impractical here (~7 h with workers running); use CI.
- `pip install http-ece` needs `pip install --ignore-installed --upgrade setuptools` first in this container.
- Encoding guard: new Python text IO passes `encoding="utf-8"`. Never `git stash`. GitHub API quota is shared.
