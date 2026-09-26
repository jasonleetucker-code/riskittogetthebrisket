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

## Observed production metadata, 2026-09-26

[Workflow36271660914](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/36271660914) succeeded with three requested observations from reviewed helper7f3dfac15. Stable checkout27f246895560ef47285ffa2579d27e5e6a927c97 is not loaded-process proof. Actual host has4logicalCPUs and8,326,946,816bytes RAM; available memory was5,718,093,824–5,731,094,528bytes. Web MainPID RSS was1,837,793,280bytes with18FDs. Web cgroup memory was2,254,917,632bytes under an installed3,221,225,472byte limit. These are short observations, not selected limits or sustained acceptance.

DLF reported failed/exit1 and Game Day capture failed/exit3. Cause remains unknown: current DLF can fail after partial publication; capture checks the closed window before the already-captured condition, so a later refusal does not prove lost observations. Live collector inactive/exit2 is compatible with checked-in no-work semantics; installed success-code configuration still requires verification. No service was restarted or modified.

[Sanitized observations and follow-up review](evidence/linux-inventory-2026-09-26.json) preserve numeric evidence and limitations. The next bounded probe adds explicit systemd Result/exit/start/timer metadata and numeric success statuses. Optional default-path DLF written-key presence carries assumedDefaultPath=true; missing/unknown metadata is not cause attribution. It reads no credentials, environment, command lines, arbitrary logs or payloads. Capture coverage remains unknown.


## Bounded source-stage attribution

Follow-up run36272340282 proves installed Game Day live Result=success with
SuccessExitStatus=[2]; its inactive exit2 is not a failed service observation.
DLF's assumed-default written manifest lists only dlfValuesSfTep; the other four
boards are absent. This is partial manifest evidence, not proof of last invocation,
publication success, freshness or provider root cause. Capture still reports exit3.

The next reviewed helper revision reads only the two fixed service roles' bounded
latest-invocation journal on the host. It emits recognized categorical stages and
numeric counts; raw messages, invocation IDs, paths and exception text never leave
the host. Unit+invocation matching and a before/after identity check reject races.
Byte, line, message and time limits fail explicitly; unavailable/truncated logs
cannot be called complete. Even a complete bounded retained query does not prove
historical log completeness, loaded code identity or root cause. No service,
provider or configuration is changed. [Independent review](evidence/source-stage-review-2026-09-26.json)
records52passing tests,2Linux-only skips and five additional privacy discriminators.
