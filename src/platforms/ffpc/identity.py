"""FFPC identity extraction with explicit scope and confidence."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from src.platforms.base import (
    IDENTITY_GLOBAL_UNVERIFIED,
    IDENTITY_GLOBAL_VERIFIED,
    IDENTITY_LEAGUE_SCOPED_TEAM,
    IDENTITY_NAME_ONLY,
    scoped_key,
)

_GLOBAL_QUERY_KEYS = ("siteuserid", "site_user_id", "userid", "user_id", "managerid")
_TEAM_QUERY_KEYS = ("teamid", "team_id", "entryid", "entry_id")


@dataclass(frozen=True)
class FFPCIdentity:
    source_manager_id: str
    manager_key: str
    identity_type: str
    identity_scope: str
    confidence: float
    global_id: str | None = None
    team_id: str | None = None


def _query_value(url: str | None, keys: tuple[str, ...]) -> str | None:
    if not url:
        return None
    parsed = parse_qs(urlparse(url).query)
    lower = {str(k).lower(): v for k, v in parsed.items()}
    for key in keys:
        values = lower.get(key)
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    return None


def resolve_identity(
    *,
    league_id: str,
    team_id: str | None,
    manager_name: str | None,
    profile_url: str | None = None,
    explicit_global_id: str | None = None,
    verified_global: bool = False,
) -> FFPCIdentity:
    global_id = str(explicit_global_id or "").strip() or _query_value(
        profile_url, _GLOBAL_QUERY_KEYS
    )
    if global_id:
        source = f"site-user-{global_id}"
        return FFPCIdentity(
            source_manager_id=source,
            manager_key=scoped_key("ffpc", source),
            identity_type=(
                IDENTITY_GLOBAL_VERIFIED if verified_global else IDENTITY_GLOBAL_UNVERIFIED
            ),
            identity_scope="platform",
            confidence=1.0 if verified_global else 0.85,
            global_id=global_id,
            team_id=str(team_id or "").strip() or None,
        )

    resolved_team = str(team_id or "").strip() or _query_value(profile_url, _TEAM_QUERY_KEYS)
    if resolved_team:
        source = f"league:{league_id}:team:{resolved_team}"
        return FFPCIdentity(
            source_manager_id=source,
            manager_key=scoped_key("ffpc", source),
            identity_type=IDENTITY_LEAGUE_SCOPED_TEAM,
            identity_scope=f"league:{league_id}",
            confidence=0.70,
            team_id=resolved_team,
        )

    # Name-only identities are deliberately scoped to a league and carry
    # a hash rather than the raw display name. They can be inspected, but
    # cannot satisfy automated multi-league qualification.
    normalized = re.sub(r"\s+", " ", str(manager_name or "").strip().lower())
    digest = hashlib.sha256(f"{league_id}\0{normalized}".encode()).hexdigest()[:16]
    source = f"league:{league_id}:name:{digest}"
    return FFPCIdentity(
        source_manager_id=source,
        manager_key=scoped_key("ffpc", source),
        identity_type=IDENTITY_NAME_ONLY,
        identity_scope=f"league:{league_id}",
        confidence=0.25,
    )
