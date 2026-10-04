# Class-B isolation boundary probe

**Status:** PROBE ONLY. No Class-B worker, branch writer, Git credential, model
runtime, or autonomous fan-out is enabled by this unit.

The `Class B Isolation Probe` GitHub workflow runs a fixed Python probe in a
digest-pinned container on a public GitHub-hosted Ubuntu runner. The container
has no network namespace route, a read-only root and source fixture, one small
writable output tmpfs, no Docker socket or inherited host canary, no Linux
capabilities, no-new-privileges, a non-root UID, and CPU/memory/process limits.
The probe performs real reads/writes and attempts denied actions. A failed
assertion fails the workflow; its JSON output records only check names and
booleans. The workflow also reruns the probe with network, source-mount, and
root-filesystem protections removed one at a time and requires the matching
assertion to fail.

This proves a candidate local container boundary on the runner that executes
the workflow. It does not prove protection on the Windows development host or
production VPS, enforce a command/path/domain allowlist for arbitrary agent
commands, bound disk consumption outside the tmpfs, issue branch-only Git
credentials, or produce a safe general worker API. Those are prerequisites for
the Class-B executor unit. The existing Steward controller remains Class-A
report-only.

The next unit must run a worker through this boundary with deterministic
command/path policy, auditable refusal events, bounded execution and retries,
isolated branch/worktree handling, and independent verification. A green probe
alone must not promote `B_REVERSIBLE_BRANCH` to active use.
