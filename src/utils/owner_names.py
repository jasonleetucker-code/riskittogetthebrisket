"""Sleeper username -> owner first-name resolution.

Sleeper's ``display_name`` field is the user-chosen username
(e.g. ``JasonLeeTucker``, ``killaKich00``), not the human first name
the rest of the league actually calls them.  This module reads a small
mapping from ``config/leagues/owner_names.json`` and returns the
preferred display label for any Sleeper user payload.

The mapping is case-insensitive: Sleeper preserves the case the user
typed, but the username is unique under case-folding.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.utils.config_loader import load_json, repo_root


@lru_cache(maxsize=1)
def _load_mapping() -> dict[str, str]:
    path = repo_root() / "config" / "leagues" / "owner_names.json"
    data = load_json(path, default={}) or {}
    return {str(k).lower(): str(v) for k, v in data.items() if k and v}


def owner_label(user: dict[str, Any] | None) -> str:
    """Return the owner's preferred first name for a Sleeper user payload.

    Resolution order:
      1. ``config/leagues/owner_names.json`` lookup by ``display_name``
      2. raw ``display_name``
      3. league-set ``metadata.team_name``
      4. ``Team <user_id>`` placeholder
    """
    if not isinstance(user, dict):
        return ""
    display = str(user.get("display_name") or "").strip()
    mapping = _load_mapping()
    mapped = mapping.get(display.lower())
    if mapped:
        return mapped
    if display:
        return display
    meta_name = ""
    meta = user.get("metadata")
    if isinstance(meta, dict):
        meta_name = str(meta.get("team_name") or "").strip()
    if meta_name:
        return meta_name
    uid = str(user.get("user_id") or "")
    return f"Team {uid}" if uid else ""
