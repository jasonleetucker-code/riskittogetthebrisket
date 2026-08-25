"""Sharp-suite fixtures.

The cohort memo (``src/sharp/cohort.py``, W15-F017) keys on the platform
ledger's ``(mtime_ns, size)``.  That is exactly the freshness signal
production needs, but it is BLIND to a monkeypatch: many sharp tests
replace ``build_manager_records`` / ``curated_cohort_members`` and then
call ``cohort_members`` on the default ledger, so two tests can share a
key and fingerprint while expecting different patched cohorts.  Clearing
the memo before every test restores per-test isolation without weakening
the production invalidation rule (a real ledger write still changes the
fingerprint on its own).
"""

from __future__ import annotations

import pytest

from src.sharp import cohort as _cohort


@pytest.fixture(autouse=True)
def _reset_cohort_cache():
    _cohort.reset_cohort_cache()
    yield
    _cohort.reset_cohort_cache()
