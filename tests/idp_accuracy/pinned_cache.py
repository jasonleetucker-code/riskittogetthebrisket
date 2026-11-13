"""The committed, trimmed copy of the pinned IDP-accuracy research cache.

``tests/fixtures/idp_accuracy/pinned_cache.zip`` replaces the gitignored ~33 MB
``data/idp_accuracy/cache`` for the three tests that read real rosters / stat
lines (it is built by ``tests/fixtures/idp_accuracy/build_pinned_cache.py`` and
holds public NFL facts plus whitelisted league fields only).  It is extracted
once per process into a temp directory laid out exactly like the live cache, so
the research ``Fetcher`` classes read it unchanged.
"""

from __future__ import annotations

import atexit
import shutil
import tempfile
import zipfile
from functools import lru_cache
from pathlib import Path

PINNED_ZIP = Path(__file__).resolve().parents[1] / "fixtures" / "idp_accuracy" / "pinned_cache.zip"


@lru_cache(maxsize=1)
def pinned_cache_dir() -> Path:
    """Extract the fixture once; the directory is removed at interpreter exit."""
    root = Path(tempfile.mkdtemp(prefix="idp_pinned_cache_"))
    atexit.register(shutil.rmtree, root, True)
    with zipfile.ZipFile(PINNED_ZIP) as zf:
        zf.extractall(root)
    return root
