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
from datetime import datetime, timezone
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
    # Best-ball mode — Sleeper exposes this on
    # ``league.settings.best_ball``.  Read from the registry JSON when
    # present (additive field; defaults False so existing entries
    # aren't broken).  Consumed only by ``src/ros/*`` so the lineup
    # optimizer can credit best-ball depth as well as starting
    # strength; dynasty rankings + trade calculator are unaffected.
    best_ball: bool = False

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
            "bestBall": self.best_ball,
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
    aliases = tuple(str(a).strip() for a in aliases_raw if isinstance(a, str) and a.strip())

    # ``bestBall`` is optional in the registry JSON so existing
    # registry files keep working with no edits; defaults False.
    best_ball = bool(entry.get("bestBall", False))

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
        best_ball=best_ball,
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


def get_scoring_profile(key: str | None = None) -> str | None:
    """Return the scoring-profile marker for a league, or the default's.

    The scoring profile is the identifier for "which set of rules
    produces this league's player values" — e.g.
    ``"superflex_tep15_ppr1"``.  **Rankings are keyed by scoring
    profile, not by league.**  When two leagues share a profile, they
    share the blended rank + value pipeline; when they differ, each
    profile runs its own pipeline.

    See ``config/leagues/README.md`` and ``CLAUDE.md`` ("League-aware
    routing" section) for the full split:

      * scoringProfile → controls rankings, values, rank-history
      * leagueKey      → controls teams, rosters, signals, context

    Returns None when no league is configured at all.
    """
    if key is None:
        cfg = get_default_league()
    else:
        cfg = get_league_by_key(key)
    return cfg.scoring_profile if cfg else None


# ── Factual scoring identity (W18-F001) ──────────────────────────────
#
# ``scoring_profile`` above is a config/model LABEL and stays one.  What
# decides whether one league's rankings may be served for another is the
# league's ACTUAL scoring card, fingerprinted.  The two live leagues both
# carry ``superflex_tep15_ppr1`` and differ on 35 of 48 shared keys, so
# the label answered the question wrong in production.
#
# The card is read from a SNAPSHOT on disk, never fetched inside a
# request.  An 8 s Sleeper round-trip in the ``/api/data`` gate would
# trade a correctness bug for a latency one; snapshots are refreshed off
# the request path (post-scrape warm + ``scripts/fetch_league_scoring.py``)
# and a league with no snapshot is UNVERIFIABLE, which fails closed.

_SCORING_SNAPSHOT_ENV = "LEAGUE_SCORING_SNAPSHOT_DIR"
_DEFAULT_SCORING_SNAPSHOT_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "leagues"

#: How old a scoring card may be and still prove CURRENT compatibility.
#:
#: A snapshot proves "this league had these rules when the fetch last
#: succeeded" — not "this league still has these rules".  Left unbounded,
#: a league whose commissioner changed scoring while every later refresh
#: failed would keep authorizing cross-league ranking reuse forever: the
#: W18-F001 fail-open reached through time instead of through a label.
#:
#: The number is DERIVED, not chosen.  ``scheduled-refresh.yml`` runs
#: ``42 */2 * * *`` and the post-scrape warm pass writes this snapshot on
#: that cadence, so it is a scrape-cadence artifact — and this repo already
#: has one staleness budget for those, stated twice and identically:
#: ``server.py`` calls the contract stale at ``SCRAPE_INTERVAL_HOURS * 3``
#: (2 × 3 = 6), and ``data_contract._SOURCE_MAX_AGE_HOURS`` gives every
#: source on that cadence a 6-hour budget.  Pinned against both in
#: ``tests/api/test_scoring_compatibility.py`` so it cannot drift away
#: from what derived it.
SCORING_SNAPSHOT_MAX_AGE_HOURS: int = 6

#: Three states, deliberately the same vocabulary
#: ``data_contract._build_source_timestamps`` already uses for source
#: freshness: a card we can trust, a card we still hold but may no longer
#: trust, and no card at all.  Only ``fresh`` authorizes ranking reuse;
#: ``stale`` is retained and readable for diagnostics, because a transient
#: Sleeper failure should not destroy evidence — it should only stop that
#: evidence being an unlimited authorization token.
SCORING_EVIDENCE_FRESH = "fresh"
SCORING_EVIDENCE_STALE = "stale"
SCORING_EVIDENCE_MISSING = "missing"

#: league_id → (snapshot mtime_ns, size, (fingerprint, fetchedAt epoch,
#: season)).  Re-reading a small JSON file per request is cheap but not
#: free, and this gate is on the hot path of ``/api/data``.
_scoring_fp_cache: dict[str, tuple[int, int, tuple[str | None, float | None, str]]] = {}
_scoring_fp_lock = threading.Lock()


def scoring_snapshot_dir() -> Path:
    """Where per-league scoring cards live.  Override for tests."""
    override = os.getenv(_SCORING_SNAPSHOT_ENV, "").strip()
    return Path(override) if override else _DEFAULT_SCORING_SNAPSHOT_DIR


def scoring_snapshot_path(sleeper_league_id: str) -> Path:
    """Keyed by Sleeper league id, not by registry key.

    The card is a property of the league on the host, so two registry
    entries pointing at the same Sleeper league share one snapshot and a
    registry rename does not orphan it.
    """
    return scoring_snapshot_dir() / f"scoring_{str(sleeper_league_id).strip()}.json"


def write_scoring_snapshot(sleeper_league_id: str, scoring: dict[str, Any], **extra: Any) -> Path:
    """Persist a league's scoring card.  Callers run OFF the request path."""
    path = scoring_snapshot_path(sleeper_league_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "sleeperLeagueId": str(sleeper_league_id),
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "scoringSettings": dict(scoring or {}),
    }
    payload.update({k: v for k, v in extra.items() if v is not None})
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    with _scoring_fp_lock:
        _scoring_fp_cache.pop(str(sleeper_league_id), None)
    return path


def _read_scoring_snapshot(cfg: LeagueConfig | None) -> dict[str, Any] | None:
    """The raw snapshot payload, or ``None``.  Never raises, never fetches."""
    if cfg is None or not getattr(cfg, "sleeper_league_id", ""):
        return None
    try:
        raw = json.loads(scoring_snapshot_path(cfg.sleeper_league_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def scoring_settings_for_league(cfg: LeagueConfig | None) -> dict[str, Any] | None:
    """A league's stored scoring card, whatever its age.

    Deliberately NOT freshness-gated: stale evidence is still evidence and
    stays readable for diagnostics.  What expires is its authority to
    prove current compatibility — see :func:`scoring_fingerprint_for_league`.
    """
    raw = _read_scoring_snapshot(cfg)
    scoring = raw.get("scoringSettings") if raw else None
    return scoring if isinstance(scoring, dict) else None


def _snapshot_cache_entry(cfg: LeagueConfig) -> tuple[str | None, float | None, str] | None:
    """``(fingerprint, fetched_at_epoch, season)`` for a league's snapshot.

    Cached on ``(mtime_ns, size)`` so the common path is one ``stat()`` plus
    a dict hit.  Note what is NOT cached: the freshness verdict.  Age is a
    function of wall clock, so a decision computed while the card was fresh
    would otherwise keep being served after it went stale.  Only
    content-derived facts live here.
    """
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    league_id = str(cfg.sleeper_league_id)
    try:
        stat = scoring_snapshot_path(league_id).stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        with _scoring_fp_lock:
            _scoring_fp_cache.pop(league_id, None)
        return None
    with _scoring_fp_lock:
        cached = _scoring_fp_cache.get(league_id)
        if cached is not None and cached[0] == stamp[0] and cached[1] == stamp[1]:
            return cached[2]

    raw = _read_scoring_snapshot(cfg) or {}
    scoring = raw.get("scoringSettings")
    fetched_at: float | None = None
    try:
        fetched_at = datetime.fromisoformat(str(raw.get("fetchedAt"))).timestamp()
    except (TypeError, ValueError):
        fetched_at = None
    entry = (
        scoring_fingerprint(scoring if isinstance(scoring, dict) else None),
        fetched_at,
        str(raw.get("season") or ""),
    )
    with _scoring_fp_lock:
        _scoring_fp_cache[league_id] = (stamp[0], stamp[1], entry)
    return entry


def _scoring_evidence(cfg: LeagueConfig | None) -> tuple[str, str | None]:
    """``(state, fingerprint)`` from ONE snapshot read.

    The two public helpers are thin wrappers over this so the common path
    stats the snapshot once rather than once per question.
    """
    if cfg is None or not getattr(cfg, "sleeper_league_id", ""):
        return SCORING_EVIDENCE_MISSING, None
    entry = _snapshot_cache_entry(cfg)
    if entry is None:
        return SCORING_EVIDENCE_MISSING, None
    fingerprint, fetched_at, season = entry
    if not fingerprint:
        return SCORING_EVIDENCE_MISSING, None
    if fetched_at is None:
        return SCORING_EVIDENCE_STALE, None
    age_hours = (datetime.now(timezone.utc).timestamp() - fetched_at) / 3600.0
    if age_hours > SCORING_SNAPSHOT_MAX_AGE_HOURS:
        return SCORING_EVIDENCE_STALE, None
    if season:
        try:
            from src.bdvm.actuals import nfl_projection_season  # noqa: PLC0415

            if str(nfl_projection_season()) != season:
                return SCORING_EVIDENCE_STALE, None
        except Exception:  # noqa: BLE001 — a season check must not break the gate
            pass
    return SCORING_EVIDENCE_FRESH, fingerprint


def scoring_evidence_state(cfg: LeagueConfig | None) -> str:
    """``"fresh"`` / ``"stale"`` / ``"missing"`` for a league's scoring card.

    ``fresh`` is the only state that proves CURRENT scoring identity.  A
    card goes stale two independent ways:

    * **age** — older than :data:`SCORING_SNAPSHOT_MAX_AGE_HOURS`, or
      carrying no readable ``fetchedAt`` at all (an undated card cannot be
      shown to be recent);
    * **season** — recorded against a different NFL season than the one we
      are in.  Sleeper leagues chain year to year under new ids, so a
      registry entry left pointing at last season's league would otherwise
      keep fetching a perfectly *fresh* card describing the wrong season.
      Age alone cannot catch that.
    """
    return _scoring_evidence(cfg)[0]


def scoring_fingerprint_for_league(cfg: LeagueConfig | None) -> str | None:
    """The PROVEN-CURRENT scoring identity of a configured league.

    ``None`` whenever the evidence is stale or missing, because this
    function's answer authorizes cross-league ranking reuse and unproven
    fails closed.  Callers that want the stored card regardless of age
    want :func:`scoring_settings_for_league` instead.
    """
    return _scoring_evidence(cfg)[1]


def refresh_scoring_snapshot(cfg: LeagueConfig | None) -> str | None:
    """Fetch a league's scoring card from the host and persist it.

    Returns the new fingerprint, or ``None`` on any failure — this runs
    OFF the request path (post-scrape warm, ``scripts/fetch_league_scoring.py``)
    and a failure must leave the previous snapshot in place rather than
    blank it: a stale-but-real card is still a truthful statement about
    the league, while no card at all takes cross-league requests down.
    """
    if cfg is None or not getattr(cfg, "sleeper_league_id", ""):
        return None
    try:
        from src.league_comparison.sleeper_scoring import (  # noqa: PLC0415
            fetch_league_scoring,
            scoring_fingerprint,
        )

        info = fetch_league_scoring(str(cfg.sleeper_league_id), refresh=True)
        fingerprint = scoring_fingerprint(info.scoring_settings)
        if not fingerprint:
            log.warning(
                "league_registry: %s scoring card is empty or unusable; snapshot not written",
                cfg.key,
            )
            return None
        write_scoring_snapshot(
            cfg.sleeper_league_id,
            info.scoring_settings,
            leagueKey=cfg.key,
            leagueName=info.name,
            season=info.season,
            scoringFingerprint=fingerprint,
        )
        return fingerprint
    except Exception as exc:  # noqa: BLE001 — never break the warm pass
        log.warning("league_registry: scoring snapshot refresh failed for %s: %s", cfg.key, exc)
        return None


def leagues_share_scoring(key_a: str | None, key_b: str | None) -> bool:
    """True iff two league keys are PROVEN to score players identically.

    The one canonical answer to "may the rankings built for league A be
    served for league B?".  Callers that hold a loaded contract should
    prefer its own stamped fingerprint over a registry lookup for the
    loaded side — see ``server.py::_scoring_identity_error``.

    Fails closed in every unproven case: an unknown key, a league with no
    scoring snapshot, or a snapshot too degenerate to fingerprint.  A
    ``503 data_not_ready`` is recoverable; one league's board published
    under another league's name is not visible at all.

    This used to compare ``scoring_profile`` — a hand-typed label — which
    returned ``True`` for the repo's two live leagues even though their
    hosts differ on 35 of 48 shared scoring keys (W18-F001).
    """
    cfg_a = get_league_by_key(key_a) if key_a else None
    cfg_b = get_league_by_key(key_b) if key_b else None
    if cfg_a is None or cfg_b is None:
        return False
    fp_a = scoring_fingerprint_for_league(cfg_a)
    fp_b = scoring_fingerprint_for_league(cfg_b)
    if not fp_a or not fp_b:
        return False
    return fp_a == fp_b


def default_league_key() -> str | None:
    """Return the default league's key, or None if none configured."""
    cfg = get_default_league()
    return cfg.key if cfg else None
