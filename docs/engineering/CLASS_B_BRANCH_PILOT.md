# Fixed Class-B branch pilot (2026-10-05)

The `Class B Branch Pilot` PR workflow runs a credential-free, fixed-task worker
in the same digest-pinned Linux Docker boundary. Its one allowed input is a
read-only copy of `docs/master-site-audit/PERFORMANCE_AUDIT.md` from the PR base.
The worker derives the missing numbered GitHub anchor from the actual heading,
executes an anchor-resolution check, and writes only a repaired document and a
small receipt to a 1 MB host tmpfs mounted as `/output`. It explicitly attempts
an out-of-scope path and command through its cooperative task policy; Docker's
`--network=none` is exercised by a real socket attempt. A separate host
verifier checks regular files, exact output set and size, input/output digests,
refusal evidence, and the *entire* permitted one-link diff. CI compares those
bytes to the PR document. The worker sees neither `.git` nor a token, host
filesystem, production address, Docker socket, or secret mount.

This is a real repair of an existing broken link, but it is **deterministic
Class-B execution**, not autonomous AI coding. The task ID and command are fixed
in code. The cooperative path and command functions are not a security boundary
against arbitrary code execution inside the container; the Docker mounts,
network namespace and resource limits carry that role. The local Windows run
proved task logic and verifier behavior, while the PR workflow supplies the
Linux isolation evidence. The trusted Codex host creates the branch and PR
after verification; no automated branch writer is activated. The repository's
main protection still permits direct fast-forward pushes, so a `contents:write`
coordinator would have merge/deploy-equivalent authority. `B_REVERSIBLE_BRANCH`
remains inactive until that credential boundary and a real authorized model
runtime are in place.
