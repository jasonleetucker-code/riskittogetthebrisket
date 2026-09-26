# Current production inventory for #1338

The existing C1A read-only workflow has an opt-in `performance-safe` scope.
Default `closure` behavior is unchanged. The new scope does not run the old
journal collector, install/start/stop services, fetch providers or read payloads,
environment values, command lines, cookies or credentials from the host.

After review and normal validation:

```text
gh workflow run c1a-closure-diagnostics.yml --ref <reviewed-reachable-ref> -f scope=performance-safe -f samples=3 -f interval_seconds=10
```

The existing pinned-host SSH credentials and production environment are reused.
The helper is sent over stdin, not installed. Bounded subprocess reads, output
caps and deadlines fail closed; the runner validates the entire fixed schema
before writing the sole uploaded artifact. Failures export a fixed status,
never raw remote stdout/stderr. Separate diagnostic concurrency preserves the
production deployment queue. Both new workflow steps are classified blocking.

## What the initial probe proves

It samples host memory/disk/CPU counters and named-unit states, MainPID identity,
RSS, FD count and cgroup memory/task properties for web, frontend, nginx, DLF
and Game Day owners. CPU ticks are cumulative counters, not utilization.
Observations are sequential, not an atomic simultaneous process-tree snapshot.
`complete` means the requested stable web-MainPID/host observations are present;
it does not imply every optional unit exists or that production is accepted.
Unknown PID and inaccessible/partially enumerated FDs remain null. They are not
zero or proof of a stopped process. Linux-only process evidence is skipped
honestly on Windows and executed on Linux CI.

Checkout before/after revision is separate from running-code identity.
`loadedProcessRevision` remains null: a checkout hash cannot prove which code
an already-running interpreter imported. No sustained memory/headroom, full
child census, recovery, queue, authenticated route or browser acceptance follows
from a three-observation metadata report. These remain #1338 requirements.

## Validation

Author: 25 focused/classification tests passed, one Linux-only skip. Independent
review: 21 focused tests passed, one Linux-only skip; the initial review rejected
unknown-PID and unreadable-FD coercions, then verified both corrections with
independent probes. Scoped Ruff and whitespace checks passed. Counts overlap.
See [exact reviewed hashes](evidence/production-probe-review-2026-09-26.json).
Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c.

No production run is claimed by this implementation record.
