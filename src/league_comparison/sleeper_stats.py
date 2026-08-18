"""Fetch raw weekly NFL stats from the Sleeper API.

Used as a fallback for seasons that nflverse hasn't yet published.
The 2025 NFL season is the canonical example: nflverse may lag for
weeks or months after the season ends, but Sleeper's stat dump is
final within hours of each game.

Output: a list of stat-row dicts in the same shape that
:func:`src.nfl_data.ingest.fetch_weekly_stats` returns, so the
existing :mod:`src.nfl_data.realized_points` scoring engine — and
everything downstream of it — works on these rows unchanged.

Sleeper raw stat fields use short keys (``pass_yd``, ``rush_td``,
``idp_tkl``).  The realized-points engine reads nflverse long keys
(``passing_yards``, ``rushing_tds``, ``def_tackles``).  We translate
on the way out so callers don't have to know the difference.

Position metadata comes from ``/v1/players/nfl``, joined per player
on Sleeper's player_id.  Where a player has a ``gsis_id``, we use it
as the canonical ``player_id`` so the season-bucket key in
:mod:`src.league_comparison.scoring_engine` matches whatever nflverse
emits for the same player in adjacent seasons.

Caching: both the player index and per-(season, week) stat dumps are
cached on disk via :mod:`src.nfl_data.cache` with multi-day TTLs.
Once a NFL season is final, its weekly numbers don't change, so a
long TTL is safe.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Callable

from src.nfl_data import cache as _nfl_cache
from src.nfl_data.realized_points import is_host_player_entry

_LOGGER = logging.getLogger(__name__)


def _host_native_enabled() -> bool:
    """Is the host-native scoring challenger active? (#802)

    Imported lazily so this module keeps working in contexts where the
    flag registry is not importable, and read per call rather than at
    import time so a test can flip it with ``feature_flags.reload()``.
    """
    try:
        from src.api.feature_flags import is_enabled  # noqa: PLC0415

        return is_enabled("host_native_scoring")
    except Exception:  # noqa: BLE001
        return False

_SLEEPER_API_ROOT = "https://api.sleeper.app/v1"
_HTTP_TIMEOUT = 15.0
_PLAYER_INDEX_TTL = 7 * 24 * 3600  # 7 days
_WEEKLY_STATS_TTL = 7 * 24 * 3600  # 7 days

# League-comparison samples weeks 1-17 only.  Modern NFL regular
# seasons run 18 weeks (since 2021), but week 18 is starter-rest
# territory for most playoff-bound teams; trimming it makes the
# multi-year sample more apples-to-apples and shaves one HTTP fetch
# per season.
_REGULAR_WEEK_RANGE = range(1, 18)

# Sleeper short stat key → nflverse long key.  Mirrors the inverse of
# ``src.nfl_data.realized_points._SIMPLE_KEYS`` plus IDP and 2-pt keys
# so every scoring category the realized-points engine cares about is
# named correctly when these rows reach it.
_FIELD_MAP: dict[str, str] = {
    # Offense
    "pass_yd": "passing_yards",
    "pass_td": "passing_tds",
    "pass_int": "interceptions",
    "pass_sack": "sacks",
    "rush_yd": "rushing_yards",
    "rush_td": "rushing_tds",
    "rec": "receptions",
    "rec_yd": "receiving_yards",
    "rec_td": "receiving_tds",
    "fum_lost": "fumbles_lost",
    "pass_2pt": "passing_2pt_conversions",
    "rush_2pt": "rushing_2pt_conversions",
    "rec_2pt": "receiving_2pt_conversions",
    # IDP — Sleeper already prefixes these with "idp_"; nflverse uses
    # "def_*".  The realized-points engine reads from def_* columns.
    "idp_tkl_solo": "def_tackles_solo",
    "idp_tkl_ast": "def_tackle_assists",
    # ``idp_tkl`` is DELIBERATELY NOT MAPPED (2026-08-13, B7 / W18-F003).
    # It used to become ``def_tackles``, and the two do not mean the same
    # thing: Sleeper's ``idp_tkl`` is COMBINED tackles, while
    # ``realized_points._tackle_view`` reads a published ``def_tackles``
    # as the pre-2025 gamebook SOLO total.  Writing combined into the
    # solo slot inflated both — a 5-solo/3-assist line became solo 8,
    # combined 11 — on every row that reached the engine through this
    # fallback path.
    #
    # Nothing is lost by dropping it: ``_tackle_view`` derives combined
    # as solo + assists, and both of those map correctly above.
    "idp_tkl_loss": "def_tackles_for_loss",
    "idp_sack": "def_sacks",
    "idp_sack_yd": "def_sack_yards",
    "idp_qb_hit": "def_qb_hits",
    "idp_pd": "def_pass_defended",
    "idp_int": "def_interceptions",
    "idp_int_ret_yd": "def_interception_yards",
    "idp_ff": "def_fumbles_forced",
    "idp_fum_rec": "def_fumble_recovery_own",
    "idp_fum_ret_yd": "def_fumble_recovery_yards_own",
    "idp_def_td": "def_tds",
    "idp_safe": "def_safety",
}


# ── HTTP / cache primitives ───────────────────────────────────────────


def _http_get_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "riskit-league-compare/1.0"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read())


def _player_index(*, fetcher: Callable[[str], Any] | None = None) -> dict[str, dict[str, Any]]:
    """Return ``{sleeper_player_id: {full_name, position, gsis_id, ...}}``.

    Fetches ``/v1/players/nfl`` (a 12k-player, multi-MB dump) and slims
    each entry to the few fields we need before caching to disk.
    Cache TTL is 7 days — Sleeper updates positional data when a player
    changes teams or positions; a week of staleness is tolerable for a
    historical-comparison tool.
    """
    key = "sleeper_player_index"
    cached = _nfl_cache.get(key, ttl_seconds=_PLAYER_INDEX_TTL)
    if cached is not None:
        return cached
    fetch = fetcher or _http_get_json
    raw = fetch(f"{_SLEEPER_API_ROOT}/players/nfl")
    if not isinstance(raw, dict):
        return {}
    slim: dict[str, dict[str, Any]] = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        slim[str(pid)] = {
            "full_name": p.get("full_name"),
            "first_name": p.get("first_name"),
            "last_name": p.get("last_name"),
            "position": p.get("position"),
            "fantasy_positions": p.get("fantasy_positions"),
            "gsis_id": p.get("gsis_id"),
        }
    try:
        _nfl_cache.put(key, slim)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("sleeper_stats.player_index_cache_put_failed err=%r", exc)
    return slim


def _fetch_week_stats(
    season: int,
    week: int,
    *,
    fetcher: Callable[[str], Any] | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Fetch one week of stats; return ``None`` if the week doesn't
    exist (404), the response is malformed, or the call errors out.

    Distinguishes ``None`` (week genuinely missing) from ``{}`` (empty
    response — also treated as missing) so callers can iterate weeks
    1..N and stop counting as soon as the rest of the season is empty.
    """
    key = f"sleeper_weekly_stats:{season}:{week}"
    cached = _nfl_cache.get(key, ttl_seconds=_WEEKLY_STATS_TTL)
    if cached is not None:
        return cached
    fetch = fetcher or _http_get_json
    url = f"{_SLEEPER_API_ROOT}/stats/nfl/regular/{season}/{week}"
    try:
        raw = fetch(url)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        _LOGGER.warning(
            "sleeper_stats.week_http_error season=%d week=%d code=%s",
            season,
            week,
            exc.code,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning(
            "sleeper_stats.week_fetch_failed season=%d week=%d err=%r",
            season,
            week,
            exc,
        )
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    try:
        _nfl_cache.put(key, raw)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("sleeper_stats.week_cache_put_failed err=%r", exc)
    return raw


# ── Translation ───────────────────────────────────────────────────────


def _translate_stats(sleeper_stats: dict[str, Any]) -> dict[str, float]:
    """Translate a Sleeper raw-stats dict to nflverse field names.

    Unmapped keys pass through verbatim — the realized-points engine
    ignores anything it doesn't have a scoring rule for, so leaving
    extras in is harmless and keeps debug output discoverable.

    .. warning::

       This translation is **lossy**, and that is the defect #802 exists
       to close.  It renames the host's own short keys into nflverse
       column names so ``realized_points`` can rename them back.  A rule
       with no nflverse column cannot survive the round trip even though
       both ends of it speak the host's vocabulary: measured against
       dynasty_main's live card, 50 of the 85 rules it pays are published
       by the host and cannot traverse ``_FIELD_MAP`` — every player
       special-teams category, the whole kicker family, all six ``rec_*``
       distance bands, the first-down bonuses, ``pass_cmp``, ``pass_inc``,
       ``rush_att``, ``idp_pass_def`` and ``idp_blk_kick``.

       ``host_native_scoring`` replaces this with no translation at all.
       This function remains the champion path until that flag is
       promoted, and should be deleted with it — see
       ``docs/scoring/HOST_NATIVE_SCORING_VALIDATION.md``.
    """
    out: dict[str, float] = {}
    for k, v in sleeper_stats.items():
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        nflverse_key = _FIELD_MAP.get(k, k)
        out[nflverse_key] = num
        # Also retain the original Sleeper key so anyone inspecting raw
        # rows (debug logs, fixtures) can see the source field name.
        if nflverse_key != k:
            out[k] = num
    return out


# ── Public API ────────────────────────────────────────────────────────


def fetch_sleeper_weekly_stats(
    season: int,
    *,
    fetcher: Callable[[str], Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch all regular-season weekly stat rows for one season from
    Sleeper, in a shape compatible with the realized-points engine.

    Returns an empty list (not ``None``) on any failure — callers
    decide how to surface "no data" in the UI.  Logs a WARNING on
    every failure path so partial outages are debuggable from logs.

    ``fetcher`` is a hook for tests; if omitted, the real HTTP fetcher
    is used.  It receives a URL and returns parsed JSON.
    """
    season = int(season)
    try:
        index = _player_index(fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("sleeper_stats.index_fetch_failed err=%r", exc)
        return []
    if not index:
        _LOGGER.warning("sleeper_stats.empty_player_index season=%d", season)
        return []

    rows: list[dict[str, Any]] = []
    weeks_seen: set[int] = set()
    for week in _REGULAR_WEEK_RANGE:
        raw = _fetch_week_stats(season, week, fetcher=fetcher)
        if not raw:
            continue
        weeks_seen.add(week)
        for sleeper_pid, stats in raw.items():
            if not isinstance(stats, dict) or not stats:
                continue
            # TEAM DEFENSE entries share this dump with players, and two
            # keys (``st_tkl_solo``, ``kr_yd``) are published on BOTH under
            # one name meaning different things — the team's total and the
            # player's own.  Dropping them here rather than relying on the
            # position join is deliberate: Sleeper gives a DST the position
            # ``DEF``, which is non-empty, so the check below would let it
            # through.  Team defense is not an asset class this board
            # values (#802).
            if not is_host_player_entry(sleeper_pid):
                continue
            player = index.get(str(sleeper_pid)) or {}
            position = (player.get("position") or "").strip().upper()
            if not position:
                # No position info → can't classify → drop row.  Logged
                # at DEBUG so the volume doesn't drown real warnings.
                continue
            # Host-native mode emits the host's OWN vocabulary untouched, so
            # nothing has to survive a rename it has no target for.  The
            # row is tagged so ``compute_weekly_points`` knows which
            # vocabulary it is holding and never has to guess.
            if _host_native_enabled():
                translated = {
                    str(k): float(v)
                    for k, v in stats.items()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)
                }
            else:
                translated = _translate_stats(stats)
            gsis_id = (player.get("gsis_id") or "").strip()
            row: dict[str, Any] = {
                "player_id": gsis_id or str(sleeper_pid),
                "player_id_gsis": gsis_id,
                "player_id_sleeper": str(sleeper_pid),
                "player_name": player.get("full_name") or str(sleeper_pid),
                "player_display_name": player.get("full_name") or str(sleeper_pid),
                "position": position,
                "season": season,
                "week": week,
                # Which vocabulary the stat keys below are written in.
                # Consumers pass this straight to
                # ``compute_weekly_points(..., source=...)``; a row that
                # cannot say what it is holding is a row that gets guessed
                # at, which is how the round-trip lost 50 rules in silence.
                "source": "sleeper" if _host_native_enabled() else "nflverse",
            }
            row.update(translated)
            rows.append(row)
    if rows:
        _LOGGER.info(
            "sleeper_stats.fetched season=%d rows=%d weeks=%d",
            season,
            len(rows),
            len(weeks_seen),
        )
    else:
        _LOGGER.warning(
            "sleeper_stats.no_rows season=%d weeks_seen=%d",
            season,
            len(weeks_seen),
        )
    return rows
