"""Sleeper username -> owner first-name resolution.

Sleeper's ``display_name`` field is the user-chosen username
(e.g. ``JasonLeeTucker``, ``killaKich00``), not the human first name
the rest of the league actually calls them.  This module reads a small
mapping from ``config/leagues/owner_names.json`` and returns the
preferred display label for any Sleeper user payload.

The mapping is case-insensitive: Sleeper preserves the case the user
typed, but the username is unique under case-folding.

The ``_byUserId`` block keys a name by the permanent Sleeper ``user_id`` and
wins over the display-name map.  A display name is user-chosen and can be
renamed (or, as with ``jstudle``/``jstuedle``, mistyped in config), and two
different managers can share a first name — only the user id is stable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from src.utils.config_loader import load_json, repo_root


_BY_USER_ID_KEY = "_byUserId"


@lru_cache(maxsize=1)
def _load_config() -> dict[str, Any]:
    path = repo_root() / "config" / "leagues" / "owner_names.json"
    return load_json(path, default={}) or {}


@lru_cache(maxsize=1)
def _load_mapping() -> dict[str, str]:
    """Display name (lower-cased) -> first name."""
    return {
        str(k).lower(): str(v)
        for k, v in _load_config().items()
        if k and isinstance(v, str) and v and not str(k).startswith("_")
    }


@lru_cache(maxsize=1)
def _load_user_id_mapping() -> dict[str, str]:
    """Sleeper user_id -> first name."""
    block = _load_config().get(_BY_USER_ID_KEY) or {}
    if not isinstance(block, dict):
        return {}
    return {str(k).strip(): str(v) for k, v in block.items() if str(k).strip() and v}


def owner_name_for_user_id(user_id: Any) -> str:
    """First name recorded for a Sleeper user_id, or ``""``."""
    return _load_user_id_mapping().get(str(user_id or "").strip(), "")


def owner_label(user: dict[str, Any] | None) -> str:
    """Return the owner's preferred first name for a Sleeper user payload.

    Resolution order:
      1. ``config/leagues/owner_names.json`` ``_byUserId`` lookup by ``user_id``
      2. ``config/leagues/owner_names.json`` lookup by ``display_name``
      3. raw ``display_name``
      4. league-set ``metadata.team_name``
      5. ``Team <user_id>`` placeholder
    """
    if not isinstance(user, dict):
        return ""
    by_id = owner_name_for_user_id(user.get("user_id"))
    if by_id:
        return by_id
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
