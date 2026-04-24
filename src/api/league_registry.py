"""League registry — single source of truth for every configured league.

Why this module exists
──────────────────────
The app was originally built around one Sleeper dynasty league whose ID
lived in ``SLEEPER_LEAGUE_ID`` env var and was read at module load from
a dozen different places.  Adding a second league (different Sleeper
ID, different roster rules, no IDP) meant either (a) duplicating every
read-site or (b) routing every call through a central registry.  This
module is (b).

Design
──────
* A **stable internal key** (``"dynasty_main"``, ``"dynasty_new"``)
  identifies each league.  Keys are opaque strings — never show the
  Sleeper league ID in URLs or storage paths; use the key.
* The registry is loaded from ``config/leagues/registry.json`` on
  first use and cached for the process lifetime.  Reload is explicit
  via ``reload_registry()`` — callers in tests use this.
* If the registry file doesn't exist, we **synthesise a single-league
  registry from env vars** (``SLEEPER_LEAGUE_ID``).  This keeps every
  existing deployment working without a config-file migration step.
* The registry is **immutable at runtime** — no endpoint writes to it.
  Operators edit the JSON and restart (or call ``reload_registry()``
  from an admin endpoint).

Not in scope for v1
───────────────────
* Per-league scoring profiles (the ``scoring_profile`` field is a
  string marker for now; when two leagues need different scoring,
  wire ``config/scoring/<profile>.json`` off this key).
* Per-league rank engine branching (IDP gating, TEP override).  The
  registry holds the *data*; wiring it into ``data_contract.py`` is a
  separate refactor.
* Multi-user default-team mapping beyond a static map.  A user's
  chosen team comes from ``user_kv`` in practice; the registry's
  ``default_team_map`` is for unauthenticated cold-starts only.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default registry location.  Override with ``LEAGUE_REGISTRY_PATH``
# env var (useful in tests and for staging boxes that need to point
# at a non-default file).
_DEFAULT_REGISTRY_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "leagues" / "registry.json"
)


@dataclass(frozen=True)
class LeagueConfig:
    """Immutable snapshot of one league's configuration.

    ``key`` is the internal identifier — this is what endpoints and
    URLs use.  ``sleeper_league_id`` is an implementation detail we
    want to hide from the rest of the app.

    ``default_team_map`` maps a username to a ``{"ownerId", "teamName"}``
    dict so we can auto-select a team for a signed-in user on a fresh
    device without round-tripping to Sleeper.  Keys are lower-cased on
    read to be case-insensitive.
    """

    key: str
    display_name: str
    sleeper_league_id: str
    scoring_profile: str
    roster_settings: dict[str, Any]
    idp_enabled: bool
    default_team_map: dict[str, dict[str, str]] = field(default_factory=dict)
    active: bool = True
    # Aliases let operators reference a league by an old env-var name
    # or a friendly URL slug.  Matched case-insensitively by
    # ``get_league_by_key``.
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def public_dict(self) -> dict[str, Any]:
        """Safe payload for /api/leagues — no Sleeper ID leakage.

        The Sleeper league ID is technically public (anyone can fetch
        /v1/league/<id>), but the registry hides it behind the opaque
        key so we don't bake a league-identifier choice into URL
        formats and then struggle to swap leagues later.
        """
        return {
            "key": self.key,
            "displayName": self.display_name,
            "scoringProfile": self.scoring_profile,
            "idpEnabled": self.idp_enabled,
            "rosterSettings": dict(self.roster_settings),
            "active": self.active,
        }


# ── Internal state ────────────────────────────────────────────────
# Two caches:
#   * ``_FILE_LOADED`` / ``_FILE_DEFAULT_KEY`` — state read from a
#     ``registry.json`` on disk.  Cached for the process lifetime
#     because the file doesn't change without an explicit
#     ``reload_registry()``.
#   * No cache for the env-var fallback path — ``SLEEPER_LEAGUE_ID``
#     gets re-read on every call so tests that set it in
#     ``setUpClass`` see their change take effect immediately.  The
#     registry file "wins" over the env var when both are present,
#     matching the documented precedence in config/leagues/README.md.
_LOCK = threading.Lock()
_FILE_LOADED: dict[str, LeagueConfig] | None = None
_FILE_DEFAULT_KEY: str | None = None
_FILE_CHECKED: bool = False  # sentinel: True once we've tried the file


def _parse_league_entry(entry: dict[str, Any]) -> LeagueConfig:
    """Turn one JSON blob into a frozen ``LeagueConfig``.

    Validates required fields and normalizes the default-team map.
    Raises ``ValueError`` on a malformed entry — malformed registries
    should fail loud, not silently drop leagues.
    """
    key = str(entry.get("key") or "").strip()
    if not key:
        raise ValueError("league entry missing 'key'")
    sleeper_id = str(entry.get("sleeperLeagueId") or "").strip()
    if not sleeper_id:
        raise ValueError(f"league '{key}' missing sleeperLeagueId")
    display_name = str(entry.get("displayName") or key).strip()
    scoring_profile = str(entry.get("scoringProfile") or "default").strip()
    idp_enabled = bool(entry.get("idpEnabled", False))
    roster_settings = entry.get("rosterSettings") or {}
    if not isinstance(roster_settings, dict):
        raise ValueError(f"league '{key}' rosterSettings must be a dict")
    active = entry.get("active", True)
    if not isinstance(active, bool):
        active = str(active).lower() not in ("false", "0", "no", "")

    # Default team map: {"username": {"ownerId": "...", "teamName": "..."}}.
    # Usernames are lower-cased on storage so lookups are
    # case-insensitive without touching the caller.
    raw_map = entry.get("defaultTeamMap") or {}
    team_map: dict[str, dict[str, str]] = {}
    if isinstance(raw_map, dict):
        for username, spec in raw_map.items():
            if not isinstance(username, str) or not isinstance(spec, dict):
                continue
            owner_id = str(spec.get("ownerId") or "").strip()
            team_name = str(spec.get("teamName") or "").strip()
            if owner_id or team_name:
                team_map[username.lower()] = {
                    "ownerId": owner_id,
                    "teamName": team_name,
                }

    aliases_raw = entry.get("aliases") or []
    aliases = tuple(
        str(a).strip() for a in aliases_raw
        if isinstance(a, str) and a.strip()
    )

    return LeagueConfig(
        key=key,
        display_name=display_name,
        sleeper_league_id=sleeper_id,
        scoring_profile=scoring_profile,
        roster_settings=dict(roster_settings),
        idp_enabled=idp_enabled,
        default_team_map=team_map,
        active=active,
        aliases=aliases,
    )


def _synthesise_from_env() -> tuple[dict[str, LeagueConfig], str | None]:
    """Build a single-league registry from env vars.

    Backward-compat path: when no registry file exists, fall back to
    the legacy ``SLEEPER_LEAGUE_ID`` env var and pretend it's a
    one-league registry.  Keeps existing deployments working after
    this refactor with zero config changes.

    Returns an empty registry if no env var is set either — callers
    should handle the empty case gracefully (e.g.,
    ``get_default_league()`` returns None).
    """
    sleeper_id = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
    if not sleeper_id:
        return {}, None

    entry = LeagueConfig(
        key="default",
        display_name=os.getenv("SLEEPER_LEAGUE_NAME", "Dynasty League").strip() or "Dynasty League",
        sleeper_league_id=sleeper_id,
        scoring_profile="default",
        roster_settings={},
        idp_enabled=_env_bool("SLEEPER_LEAGUE_IDP_ENABLED", True),
        default_team_map={},
        active=True,
        aliases=("main",),
    )
    return {"default": entry}, "default"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _load_from_file(path: Path) -> tuple[dict[str, LeagueConfig], str | None]:
    """Parse the registry JSON and return ``({key: cfg}, default_key)``.

    ``default_key`` honours ``defaultLeagueKey`` in the file; if absent,
    uses the first active league; if still none, returns None.  The
    file format is documented in ``config/leagues/README.md``.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, None
    except json.JSONDecodeError as exc:
        log.error("league registry %s is not valid JSON: %s", path, exc)
        return {}, None

    entries = raw.get("leagues") or []
    if not isinstance(entries, list):
        log.error("league registry %s: 'leagues' must be a list", path)
        return {}, None

    registry: dict[str, LeagueConfig] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            cfg = _parse_league_entry(entry)
        except ValueError as exc:
            log.error("league registry %s: skipping malformed entry: %s", path, exc)
            continue
        if cfg.key in registry:
            log.error(
                "league registry %s: duplicate key %r, keeping first",
                path,
                cfg.key,
            )
            continue
        registry[cfg.key] = cfg

    default_key_raw = str(raw.get("defaultLeagueKey") or "").strip()
    default_key: str | None = None
    if default_key_raw and default_key_raw in registry:
        default_key = default_key_raw
    else:
        # Fall back to first active league; if nothing's active, first
        # listed.  Keeps the "default league" concept well-defined
        # even when operators forget to set it explicitly.
        for cfg in registry.values():
            if cfg.active:
                default_key = cfg.key
                break
        if default_key is None and registry:
            default_key = next(iter(registry.keys()))

    return registry, default_key


def _ensure_file_loaded() -> None:
    """Cache the file-sourced registry on first access.

    This is the ONLY long-lived cache.  The env-var fallback is
    re-evaluated on every public call — see ``_resolve_registry()``
    — because tests (and operators) set ``SLEEPER_LEAGUE_ID`` at
    runtime and expect the change to take effect immediately.
    """
    global _FILE_LOADED, _FILE_DEFAULT_KEY, _FILE_CHECKED
    if _FILE_CHECKED:
        return
    with _LOCK:
        if _FILE_CHECKED:
            return
        override = os.getenv("LEAGUE_REGISTRY_PATH", "").strip()
        path = Path(override) if override else _DEFAULT_REGISTRY_PATH
        registry, default_key = _load_from_file(path)
        _FILE_LOADED = registry
        _FILE_DEFAULT_KEY = default_key
        _FILE_CHECKED = True


def _resolve_registry() -> tuple[dict[str, LeagueConfig], str | None]:
    """Return the effective registry + default key right now.

    Precedence:
      1. ``registry.json`` file (cached after first read)
      2. ``SLEEPER_LEAGUE_ID`` env var (re-read every call)
      3. empty

    This hot-reads the env var on every call so tests that mutate
    ``SLEEPER_LEAGUE_ID`` in ``setUpClass`` (e.g. the public-league
    route tests) see the change without calling ``reload_registry()``.
    """
    _ensure_file_loaded()
    if _FILE_LOADED:
        return _FILE_LOADED, _FILE_DEFAULT_KEY
    # File wasn't found / was empty — synthesise from env var live.
    return _synthesise_from_env()


# ══ Public API ══════════════════════════════════════════════════════


def reload_registry() -> None:
    """Drop the cache and re-read the registry on next access.

    Called from tests to point the registry at a fixture file, and
    from any future admin endpoint that rewrites the registry.json on
    disk.  Safe to call from any thread.
    """
    global _FILE_LOADED, _FILE_DEFAULT_KEY, _FILE_CHECKED
    with _LOCK:
        _FILE_LOADED = None
        _FILE_DEFAULT_KEY = None
        _FILE_CHECKED = False


def all_leagues() -> list[LeagueConfig]:
    """Return every registered league (active + inactive).

    Order is registry-file order — the first entry in the JSON comes
    first here too.  Don't sort; operators may rely on ordering for
    UI display.
    """
    registry, _ = _resolve_registry()
    return list(registry.values())


def active_leagues() -> list[LeagueConfig]:
    """Return only leagues with ``active: true``.

    Use this for endpoints that drive user-visible switchers — an
    ``active: false`` entry is typically a league the operator is
    wiring up but doesn't want users to land on yet.
    """
    return [cfg for cfg in all_leagues() if cfg.active]


def get_league_by_key(key: str | None) -> LeagueConfig | None:
    """Look up a league by its stable key or any alias.

    Returns None for an unknown key (no exception) so callers can
    defensively check + fall back to the default league.  Matching is
    case-insensitive on both the key and the aliases.
    """
    if not key:
        return None
    needle = str(key).strip().lower()
    if not needle:
        return None
    registry, _ = _resolve_registry()
    for cfg in registry.values():
        if cfg.key.lower() == needle:
            return cfg
        if any(alias.lower() == needle for alias in cfg.aliases):
            return cfg
    return None


def get_default_league() -> LeagueConfig | None:
    """Return the primary league — what unauthenticated / cold-start
    callers should use.

    Resolves in this order:
      1. ``defaultLeagueKey`` in the registry JSON (if set + active)
      2. First active league in the registry
      3. First league in the registry (even if inactive)
      4. None (no leagues configured at all)

    The last case means no ``config/leagues/registry.json`` and no
    ``SLEEPER_LEAGUE_ID`` env var — a fresh developer machine with no
    setup.  Callers should treat this as "no Sleeper data available".
    """
    registry, default_key = _resolve_registry()
    if default_key and default_key in registry:
        return registry[default_key]
    for cfg in registry.values():
        if cfg.active:
            return cfg
    return next(iter(registry.values()), None)


def get_user_default_league(username: str | None) -> LeagueConfig | None:
    """Pick the right league to land a signed-in user on.

    Resolution order:
      1. Any active league whose ``default_team_map`` contains the
         user's username — this is the operator saying "Jason's team
         is in League A". Gives us a deterministic landing page on
         fresh devices without reading user_kv.
      2. ``get_default_league()`` fallback.

    A user's *last chosen* league (stored in ``user_kv``) is a
    different, higher-priority signal — it lives in user state, not in
    the registry.  Callers should check user_kv first and fall through
    to this function when no explicit choice is recorded.
    """
    if username:
        needle = str(username).strip().lower()
        for cfg in all_leagues():
            if not cfg.active:
                continue
            if needle in cfg.default_team_map:
                return cfg
    return get_default_league()


def get_league_roster_settings(key: str | None) -> dict[str, Any]:
    """Return the roster-settings dict for a league, or ``{}``.

    Shape is operator-defined in the JSON — the registry doesn't
    enforce a schema on ``rosterSettings`` beyond "it's a dict".  This
    is deliberate: some leagues care about IDP slots, some don't;
    some surface taxi/IR, some don't.  Callers should pull the fields
    they care about and ignore the rest.
    """
    cfg = get_league_by_key(key)
    if cfg is None:
        return {}
    # Return a shallow copy so callers can't mutate the cached dict.
    return dict(cfg.roster_settings)


def get_sleeper_league_id(key: str | None = None) -> str | None:
    """Return the Sleeper league ID for a given key, or the default's.

    ``key=None`` returns the default league's Sleeper ID — this is the
    back-compat drop-in replacement for
    ``os.getenv("SLEEPER_LEAGUE_ID")``.  Returns None only when no
    league is configured at all (fresh dev machine).

    Use this EVERYWHERE you previously read the env var directly.
    That way a future multi-league rollout can thread ``key`` through
    the callers without touching this helper.
    """
    if key is None:
        cfg = get_default_league()
    else:
        cfg = get_league_by_key(key)
    return cfg.sleeper_league_id if cfg else None


def default_league_key() -> str | None:
    """Return the default league's key, or None if none configured."""
    cfg = get_default_league()
    return cfg.key if cfg else None
