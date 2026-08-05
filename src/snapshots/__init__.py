"""As-of history of the canonical board.

Records only.  Nothing here is read by a decision path, and nothing
here may become one — see :mod:`src.snapshots.board_store`.
"""

from __future__ import annotations

from src.snapshots.board_store import (
    DB_PATH,
    SCHEMA_VERSION,
    connect,
    coverage,
    write_board,
)

__all__ = [
    "DB_PATH",
    "SCHEMA_VERSION",
    "connect",
    "coverage",
    "write_board",
]
