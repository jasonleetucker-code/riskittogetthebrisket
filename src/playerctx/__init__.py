"""Player-context data layer: contracts, snap share, depth charts.

Pre-builds the scouting-report-grade context the redesigned player
profiles will consume.  Sources are nflverse's public datasets
(github.com/nflverse/nflverse-data releases), joined to the Sleeper
player pool via ``src.identity.unified_mapper``.

Modules:
    fetch      — download raw datasets to ``data/playerctx/`` (gitignored)
    normalize  — parse + aggregate into compact per-player records
    store      — atomic JSON snapshot persistence
    service    — ``refresh_playerctx()`` / ``load_playerctx()`` entry points

This package is deliberately NOT wired into ``server.py`` or the
``/api/data`` contract yet — consumption wiring lands with the player
profile redesign (R2).  Nothing imports this at server runtime today.
"""

from __future__ import annotations

from src.playerctx.normalize import SchemaRegressionError
from src.playerctx.service import load_playerctx, refresh_playerctx

__all__ = [
    "SchemaRegressionError",
    "load_playerctx",
    "refresh_playerctx",
]
