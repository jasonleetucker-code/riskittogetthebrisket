# Backend artifact cutover

The production `artifact` release now builds one Python 3.12 runtime wheelhouse
in the `Validate Build Inputs` job after the full test and frontend build gates.
`scripts/build_backend_wheelhouse.sh` is also used by the read-only PR proof.
It downloads only hash-allowed distributions from `requirements.lock.txt`,
builds source-only distributions with the pinned
`requirements-build.lock.txt` tools, installs the resulting wheels in a clean
CI virtual environment without an index, runs `pip check`, and creates a
content-addressed `backend-wheelhouse.tar`.

The calculator release manifest v2 binds the backend tar SHA-256 alongside the
frontend tree, both locks, toolchain and commit. The outer release archive
contains that backend tar. CI verifies the extracted archive before upload;
the deploy job verifies the transferred outer archive before running
`deploy/deploy.sh`. A remote free-space check requires the archive size plus
2 GiB before transfer. The host helper repeats the outer and inner checks,
compares the embedded lock and build lock to the checkout, checks Python ABI
and platform, and installs from per-wheel SHA-256 file URLs with `--no-index`
and `pip check`. It writes an install receipt only after that passes. The
runtime `/api/status` exposes the backend digest only when the manifest and
receipt match the running commit. The post-deploy smoke checks that digest
against the validation job's output.

`deploy/rollback.sh` uses the saved exact archive to reinstall a v2 backend
offline. Historical v1 releases continue their prior lock-based online install
and report the backend artifact as unavailable. A failed install never writes
a new success receipt; deployment's existing auto-rollback path remains armed.

The production virtual environment is currently updated in place. The
installer force-reinstalls every locked distribution from CI wheels, but does
not remove historical extra packages. This limits the claim to exact installed
package inputs, not a pristine runtime environment. Production free-space,
transfer, installer, rollback and served-status evidence are required before
calling this cutover verified.
