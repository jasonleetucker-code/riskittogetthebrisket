# Backend wheelhouse proof

The initial proof measured the Python artifact boundary before production
cutover. Its results informed the runtime implementation in
`docs/engineering/BACKEND_ARTIFACT_CUTOVER.md`.

The `Backend Wheelhouse Proof` PR workflow downloads hash-allowed Linux
distributions from `requirements-dev.lock.txt`. The first Linux probe found
that `http-ece==1.2.1` has no compatible published wheel, so a wheel-only
download cannot cover this lock. The revised proof builds wheels from locked
source archives in the credential-free CI runner, retains those archives,
then installs every resulting wheel in a fresh Python 3.12 virtual environment
from a generated exact-hash file with `--no-index`. It runs `pip check` and the
wheelhouse manifest tests before uploading a tarball. The manifest binds every
wheel and source archive's name, size and SHA-256 to the dev lock, Python ABI
and platform. `requirements-build.lock.txt` pins the build environment's
setuptools and wheel distributions by hash; the source build runs with build
isolation disabled so it cannot fetch a newer build tool. The manifest binds
that build lock too. It rejects symlinks, extra files, substituted bytes and
lock drift.

The proof workflow now runs both the original dev-lock measurement and a
runtime-lock wheelhouse build using the same builder as production. These are
CI results only; production verification is tracked separately in the cutover
document. No credentials or paid model service are used by this proof.
