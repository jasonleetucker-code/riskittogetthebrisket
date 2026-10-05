# Backend wheelhouse proof

The release artifact currently contains the tested Next build while production
installs Python packages from `requirements.lock.txt`. The hash lock fixes
allowed package bytes, but the CI-built Python dependency files are not yet
transferred to production. This unit measures the missing artifact boundary.

The `Backend Wheelhouse Proof` PR workflow downloads only hash-allowed Linux
wheels from `requirements-dev.lock.txt`, installs them in a fresh Python 3.12
virtual environment with `--no-index`, runs `pip check` and the wheelhouse
manifest tests, and uploads a tarball. `scripts/backend_wheelhouse.py` binds
every wheel's name, size and SHA-256 to the dev lock, Python ABI and platform.
It rejects symlinks, extra files, substituted bytes and lock drift.

This is **build and validation evidence only**. The production deploy and
rollback paths still install from the runtime hash lock, and `/api/status`
correctly reports the backend artifact as unavailable. Production cutover needs
the tested wheel archive to be transferred, verified before extraction,
installed offline from the runtime subset, saved for exact rollback and
attested by the running process. The workflow reports the archive size so that
the VPS disk and release-retention impact can be judged before that cutover.
No credentials or paid model service are used by this proof.
