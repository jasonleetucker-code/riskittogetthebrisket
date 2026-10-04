# CI release artifact

**State:** CI packaging unit, stacked after the exact Python lock. The VPS
still rebuilds the frontend until the separate deployment cutover is reviewed,
merged and production verified. Do not infer artifact deployment from the
presence of an uploaded artifact.

The production workflow's `validate` job already tests the resolved full Git
SHA, installs the exact development lock, runs backend and frontend gates, and
builds Next. Immediately after those gates, it now writes
`release-manifest.json` from the checked-out source and actual `.next` bytes,
then creates a tar archive and SHA-256 sidecar. The tar excludes `.next/cache`,
which is not served and measured 327 MB of a 344 MB local build. CI extracts
the tar into a fresh directory and verifies its contents before upload.

The manifest records:

- full Git SHA (checked against the checkout);
- Python and frontend lock SHA-256 digests;
- Python ABI, Node version, Next `BUILD_ID`;
- content digest of served `.next` files;
- content-derived artifact ID, separate from build time and workflow run ID;
- explicit `null` backend artifact digest with an unavailable reason.

`src/api/build_identity.py` owns construction and verification. Run locally
from the repository root after a Next build:

```sh
python -m scripts.release_artifact create --commit "$(git rev-parse HEAD)" --node-version "$(node --version)"
python -m scripts.release_artifact verify --commit "$(git rev-parse HEAD)"
```

This checks the tree that exists locally; a dirty checkout is test evidence,
not a release candidate. The CI workflow asserts the exact resolved SHA before
creating the manifest. The tar's SHA-256 sidecar detects transport corruption;
manifest verification detects substituted locks, build IDs or built bytes.
PR Validation also packages its real Linux Next build into the deploy tar
layout, checks the archive checksum, extracts it and re-verifies the bytes.

The artifact is retained for three days by the current workflow. The stacked
deployment cutover downloads that exact run artifact and compares its digest
with the validation job's output before transfer. On the VPS,
`scripts/stage_release_artifact.py` checks its digest, full commit, both locks,
Node major version, build ID and all frontend bytes before staging `.next.new`.
`deploy/deploy.sh` installs frontend dependencies from `package-lock.json`
with `npm ci`, then uses its existing atomic swap and probes. It archives a
successful release under the deploy state directory. A rollback with a saved
archive stages the exact previous frontend bytes; historical revisions with
no saved archive use the established rebuild path. Successful deploys retain
the eight newest complete archives plus the current and immediately previous
revisions, leaving unknown/incomplete files for operator inspection.

The deploy script rechecks the live `.next` bytes before recording success,
and the workflow independently compares their artifact ID with CI's output
after its public smoke and live-contract checks.
Before restarting the backend, deploy writes the verified manifest to the
ignored `.release-manifest.json` in the checkout. `src/api/build_identity.py`
checks it against the process commit, locks and live frontend once at import;
`/api/status` exposes the resulting `build.release` block. Missing or invalid
evidence reports a null artifact ID and a reason. The public smoke compares
both `build.commit` and `build.release.frontend_artifact_id` with CI outputs.

The deploy workflow classifies the exact target before checkout. Normal push
deploys require the full artifact contract. A manual `workflow_dispatch` for a
historical target lacking that contract can use the legacy rebuild path only
with `allow_non_fast_forward=true`. That path still validates the target and
checks the served commit and frontend assets, but it cannot claim exact Python
locks or a tested frontend artifact for a commit that predates them.

This cutover remains **unverified in production** until its PR passes Linux
CI, integrates and the deployed Next build ID and artifact ID are observed
from the live service. The backend still installs the pinned lock on the VPS;
its built artifact digest is explicitly unknown. That backend build-once piece
remains open.
