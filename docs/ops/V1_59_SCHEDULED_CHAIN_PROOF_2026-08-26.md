# V1-59 scheduled production-chain proof — 2026-08-26

This record preserves the production evidence named by V1-59 in `docs/VERSION_1_COMPLETION_CONTRACT.md`. It does not alter methodology, scope, authentication, or any product behavior.

## Evidence source

GitHub Actions run **32950526742**, workflow **Temporary V1-59 Post-Deploy Production Proof**, job **98120655588**, completed successfully on 2026-08-26. The proof used the repository's existing production SSH lane with strict host-key checking and performed read-only `systemctl`/`journalctl` inspection. It verified that production contained required repair SHA `c30b8d6ba1ef2fa604ecb1cfe1e44dd6130ede44` and that this SHA was the deployed HEAD at proof time.

The proof intentionally uses systemd's configured success semantics. The Sharp discovery, records, and rosters units each declare `SuccessExitStatus=0 2`; exit 2 is the existing resumable budget-exhaustion state, not failure. The earlier probe that required `ExecMainStatus=0` was therefore superseded rather than used to manufacture a pass.

## Scheduled chain observed

The latest timer triggers were in the required order:

- discovery: 2026-08-26 06:21:07 CEST; `Result=success`; exited 06:35:25 CEST with status 2 after the configured budget was exhausted.
- records: 2026-08-26 08:13:33 CEST; the corresponding scheduled crawl reached its normal budgeted completion record at 08:38:42/08:38:45 CEST. A later records execution was active when the proof sampled `systemctl`, so the proof relied on the journal from the latest scheduled timer trigger plus systemd success semantics rather than falsely treating an in-progress later execution as that scheduled run's exit.
- rosters: 2026-08-26 09:34:31 CEST; `Result=success`; exited 09:53:20 CEST with status 2 after the configured budget was exhausted. The collector reported `status: ok` for both Sleeper and FFPC result objects.

The probe asserted `discovery < records < rosters` and emitted `SCHEDULED_CHAIN_ORDER=discovery<records<rosters`.

For every unit, the journal slice beginning at its latest timer trigger was rejected if it contained any of the V1-59 failure signatures: `database is locked`, `status=15/TERM`, `Failed with result`, `Traceback`, `watchdog`, or `start operation timed out`. None were present in the qualifying slices. Upstream Sleeper 404/read-timeout warnings and budget exhaustion remained visible and were not coerced into zero or erased; they are different from the crashloop/SQLite writer-lock failure V1-59 names.

The proof also checked the FFPC Sharp unit independently over the preceding 24 hours: `Result=success`, `NRestarts=0`, and no named V1-59 failure signature was found. The job ended with `V1_59_SERVICE_CHAIN_PROOF=PASS`.

## Contract implication

V1-59's current contract row says that after repairs #1102 and #1113 were merged and deployed, **“The next scheduled bootstrap is the evidence.”** Run 32950526742 is that naturally scheduled production evidence. It is therefore sufficient evidence for the row's already-set L3 verification bar; recording the status/tally promotion in the canonical completion contract is a separate ledger update and must preserve the immutable denominator of 136.

No inference here promotes any other V1 row. In particular, this does not satisfy the separate L4 user-facing Sharp consumer verification required by V1-61/V1-62.