# Backend wheelhouse proof

The release artifact currently contains the tested Next build while production
installs Python packages from `requirements.lock.txt`. The hash lock fixes
allowed package bytes, but the CI-built Python dependency files are not yet
transferred to production. This unit measures the missing artifact boundary.

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

This is **build and validation evidence only**. The production deploy and
rollback paths still install from the runtime hash lock, and `/api/status`
correctly reports the backend artifact as unavailable. Production cutover needs
the tested wheel archive to be transferred, verified before extraction,
installed offline from the runtime subset, saved for exact rollback and
attested by the running process. The workflow reports the archive size so that
the VPS disk and release-retention impact can be judged before that cutover.
The production cutover still needs a separate runtime-only artifact and
verified offline installation and rollback. No credentials or paid model
service are used by this proof.
