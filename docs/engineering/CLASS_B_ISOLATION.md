# Class-B isolation boundary probe

**Status:** PROBE ONLY. No Class-B worker, branch writer, Git credential, model
runtime, or autonomous fan-out is enabled by this unit.

The `Class B Isolation Probe` GitHub workflow runs a fixed Python probe in a
digest-pinned container on a public GitHub-hosted Ubuntu runner. The container
has no network namespace route, a read-only root and source fixture, bounded
writable `/tmp` and `/output` tmpfs mounts, no Docker socket or inherited host canary, no Linux
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

The Linux probe passed on PR #1643 at head `d05ad1c40fda49450c23b6167bde8d4112a607ab`
([workflow run 37168180381](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/37168180381)):
all 15 enforced checks were true and each of the three sabotage runs failed
its matching check. Docker's default `/dev/shm` and other writable container
surfaces were not bounded or tested by this probe.

The next unit must run a worker through this boundary with deterministic
command/path policy, auditable refusal events, bounded execution and retries,
isolated branch/worktree handling, and independent verification. A green probe
alone must not promote `B_REVERSIBLE_BRANCH` to active use.

## Activation gate found after the probe

Read-only GitHub API inspection on 2026-10-04 found active ruleset
`main-protection` (`19976839`) on the default branch. Its enforced rules are
deletion and non-fast-forward only. It does not require a pull request or CI
checks for a fast-forward push. Repository Actions default permissions are
`write`, though this probe workflow explicitly requests `contents: read` and
checkout does not persist credentials. A future worker container must not
receive a repository write token: the token would have more authority than a
Class-B branch writer may exercise.

The current Windows development host has no Docker or Podman command; `wsl.exe`
exists, but WSL is not installed. The GitHub-hosted runner proved the container
boundary, but this probe installs and proves no authorized model runtime inside
it. The present Codex agent tools run on the host, not inside this container, so a
claim that they are isolated by this workflow would be false.

An activation design must keep any Git credential outside the untrusted worker
and use a reviewed coordinator to validate the worker's output, path and
command policy, exact branch target, and PR-only handoff. The coordinator must
be unable to let worker content choose a privileged Git ref or executable
command. `main` governance and scheduled direct-push refreshes must be
reconciled before granting that coordinator repository write permission. The
runtime/model choice and that repository authority boundary require an owner
decision. Until then, `B_REVERSIBLE_BRANCH` stays inactive and the controller
continues to reject it.

This is an observed repository configuration, not an assertion about all
GitHub repositories. Recheck the ruleset and Actions permissions at activation
time; neither API response is immutable.
