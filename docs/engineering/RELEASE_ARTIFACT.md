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

The artifact is retained for three days by the current workflow. The next
unit must download this exact run artifact, verify it before touching the VPS,
deploy its bytes without rebuilding, expose the served identity in
`/api/status`, and retain at least the previous known-good artifact for rollback.
No production artifact identity is claimed before that proof.
