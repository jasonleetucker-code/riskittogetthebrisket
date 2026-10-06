# CI release artifact

**State:** integration candidate. CI packaging, frontend artifact deployment
and the backend v2 wheelhouse cutover are implemented on the campaign train;
production deployment and served-identity proof remain pending. An uploaded
archive alone does not prove what the VPS is serving.

For normal artifact-mode targets, the production workflow's `validate` job
tests the resolved full Git SHA, installs the exact development lock, runs
backend and frontend gates, and builds Next. Immediately after those gates,
it writes `release-manifest.json` from the checked-out source and actual `.next` bytes,
then creates a tar archive and SHA-256 sidecar. The tar excludes `.next/cache`,
which is not served and measured 327 MB of a 344 MB local build. CI extracts
the tar into a fresh directory and verifies its contents before upload.

The manifest records:

- full Git SHA (checked against the checkout);
- Python and frontend lock SHA-256 digests;
- Python ABI, Node version, Next `BUILD_ID`;
- content digest of served `.next` files;
- content-derived artifact ID, separate from build time and workflow run ID;
- backend artifact SHA-256 for v2 releases; historical v1 releases retain an
  explicit `null` digest and unavailable reason.

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

The artifact is retained for three days by the current workflow. The
deployment job downloads that exact run artifact and compares its digest
with the validation job's output before transfer. On the VPS,
`scripts/stage_release_artifact.py` checks its digest, full commit, both locks,
Node major version, build ID and all frontend bytes before staging `.next.new`.
`deploy/deploy.sh` installs frontend dependencies from `package-lock.json`
with `npm ci`, then uses its existing atomic swap and probes. It archives a
successful release under the deploy state directory. A saved-artifact rollback
restores the tested frontend bytes without npm installation; historical
revisions with
no saved archive use the established rebuild path. Successful deploys retain
the eight newest complete archives plus the current and immediately previous
revisions, leaving unknown/incomplete files for operator inspection.
Before touching the live frontend, a same-revision redeploy checks any saved
archive and manifest. It preserves a complete, checksum-valid rollback archive
when the artifact ID matches and refuses a different artifact ID or incomplete
archive for that SHA. A new archive is copied and checksummed in a temporary
directory before its three saved files are published. An interrupted first save
may leave an incomplete triplet for operator inspection. The preservation
guarantee applies to the workflow's serialized deploy path; direct concurrent
on-box deploy or rollback invocations must be serialized by the operator.

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

This cutover remains **unverified in production** until the train passes its
final gates, merges, deploys, and the served frontend and backend identities
match CI. The public smoke checks asset HTTP availability, but does not yet
compare HTTP-served asset bytes with CI; that last equivalence remains
inferred. The v2 backend wheelhouse, isolated offline installer, runtime
receipt and offline rollback are described in
`docs/engineering/BACKEND_ARTIFACT_CUTOVER.md`. Historical v1 releases still
report the backend digest as unavailable.
