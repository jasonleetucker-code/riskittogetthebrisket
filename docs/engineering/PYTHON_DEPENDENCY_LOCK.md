# Python dependency lock

`requirements.txt` and `requirements-dev.txt` declare update intent. The
committed `requirements.lock.txt` and `requirements-dev.lock.txt` are exact,
SHA-256-pinned installation inputs. `config/python-lock.json` records the
manifest and lock digests; `scripts/python_lock.py check` rejects missing or
changed inputs, missing package hashes, direct requirements outside their
declared ranges, and runtime/development version divergence.

Generate both locks with Python 3.12 and `uv==0.9.26`:

```sh
python scripts/python_lock.py refresh
python scripts/python_lock.py check
```

On Windows, invoke the same command with the installed `uv.exe` path through
`--uv` if it is not on `PATH`. Review the resulting manifest, both locks and
`config/python-lock.json` in one PR. A Dependabot edit to either manifest must
refresh both locks in that PR. Do not use `pip freeze` for these files.

The PR validation, release-candidate and current-revision production install
paths changed in this unit use `pip install --require-hashes -r <lock>`.
`scheduled-refresh.yml` still installs floating `requirements.txt`; PR #1627
owns that workflow, so full CI lock parity remains pending its reconciliation.
Rollback to a revision with a lock checks and installs that lock. A rollback
to a revision older than this contract explicitly uses its legacy
`requirements.txt`, so those historical revisions remain recoverable without
claiming a locked graph for them.
Developers can use `scripts/setup.sh` or, in PowerShell:

```powershell
python scripts/python_lock.py check
python -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock.txt
.venv\Scripts\python.exe -m pip check
```

The lock fixes Python package versions and accepted distribution bytes. It
does not by itself prove the exact deployed frontend or backend artifact, nor
remove packages already present in an old production virtual environment.
Those guarantees belong to the tested-artifact/deployment unit in the campaign.
