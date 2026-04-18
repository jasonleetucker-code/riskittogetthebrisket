"""Historical stats adapter layer for the IDP calibration lab.

The lab must remain working even if Sleeper's historical stats
endpoints are inconsistent. The adapter interface accepts a season
and returns ``list[PlayerSeason]`` — raw, un-scored stat lines keyed
by canonical stat names. The rest of the math layer depends on this
shape only.

Adapters:

* :class:`SleeperStatsAdapter` — probes
  ``https://api.sleeper.app/v1/stats/nfl/regular/{season}``. Raises
  :class:`AdapterUnavailable` on any HTTP/parse failure.
* :class:`LocalCSVStatsAdapter` — reads
  ``data/idp_calibration/stats/{season}.csv`` if present. The CSV is
  expected to have a header with ``player_id``, ``name``, ``position``,
  ``games``, and one column per canonical IDP stat.
* :class:`ManualFallbackAdapter` — returns an empty list and attaches
  a ``reason`` explaining that no stats source was reachable. The
  engine surfaces this loudly.

:func:`get_stats_adapter` picks the first adapter that can serve a
given season, preferring network -> local -> manual. The caller may
override the preference order by passing ``order=[...]``.
"""
from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from src.utils.config_loader import repo_root

log = logging.getLogger(__name__)


class AdapterUnavailable(RuntimeError):
    """Raised when an adapter cannot serve a given season."""


@dataclass
class PlayerSeason:
    player_id: str
    name: str
    position: str  # Canonical DL/LB/DB/OFF
    games: int = 0
    stats: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "games": self.games,
            "stats": dict(self.stats),
        }


class HistoricalStatsAdapter:
    """Abstract interface.

    Subclasses override :meth:`_fetch_impl`. :meth:`fetch` wraps it
    with a per-season memo so the adapter-selection probe
    (:func:`get_stats_adapter` calls :meth:`available` which calls
    :meth:`fetch`) does not cause a second full fetch when
    :func:`run_analysis` later asks for the same season's data. For
    a 4-season default run against ``SleeperStatsAdapter`` that's
    4 network calls instead of 8.
    """

    name = "abstract"

    def __init__(self) -> None:
        self._cache: dict[int, list[PlayerSeason]] = {}

    def fetch(self, season: int) -> list[PlayerSeason]:
        key = int(season)
        if key in self._cache:
            return self._cache[key]
        rows = self._fetch_impl(key)
        self._cache[key] = rows
        return rows

    def _fetch_impl(self, season: int) -> list[PlayerSeason]:
        raise NotImplementedError

    def available(self, season: int) -> bool:
        try:
            self.fetch(season)
            return True
        except AdapterUnavailable:
            return False


class SleeperStatsAdapter(HistoricalStatsAdapter):
    """Probe Sleeper's historical stats endpoint.

    Sleeper publishes (undocumented) season aggregates at
    ``/v1/stats/nfl/regular/{season}``. When the endpoint is
    reachable the payload is a dict keyed by player_id with per-stat
    counts under names that closely match our canonical set (e.g.
    ``idp_tkl_solo``, ``idp_sack``). We only consume IDP stats.
    """

    name = "sleeper"
    base_url = "https://api.sleeper.app/v1/stats/nfl/regular"

    def __init__(self, players_map: dict[str, Any] | None = None) -> None:
        super().__init__()
        self._players_map = players_map

    def _resolve_players_map(self) -> dict[str, Any]:
        if self._players_map is not None:
            return self._players_map
        try:
            from .sleeper_client import fetch_nfl_players

            self._players_map = fetch_nfl_players() or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("SleeperStatsAdapter: player map unavailable: %s", exc)
            self._players_map = {}
        return self._players_map

    def _fetch_impl(self, season: int) -> list[PlayerSeason]:
        try:
            import requests
        except ImportError as exc:
            raise AdapterUnavailable(f"requests library not available: {exc}")
        url = f"{self.base_url}/{int(season)}"
        try:
            resp = requests.get(url, timeout=10)
        except Exception as exc:  # noqa: BLE001
            raise AdapterUnavailable(f"Sleeper stats HTTP failure for {season}: {exc}")
        if resp.status_code != 200:
            raise AdapterUnavailable(
                f"Sleeper stats returned HTTP {resp.status_code} for {season}"
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AdapterUnavailable(f"Sleeper stats payload parse failed for {season}: {exc}")
        if not isinstance(payload, dict) or not payload:
            raise AdapterUnavailable(
                f"Sleeper stats payload empty or unexpected shape for {season}"
            )
        players_map = self._resolve_players_map()
        out: list[PlayerSeason] = []
        for pid, stats in payload.items():
            if not isinstance(stats, dict):
                continue
            meta = players_map.get(str(pid)) or {}
            pos_raw = str(meta.get("position") or "").upper()
            canonical = _canonical_position(pos_raw)
            if canonical not in {"DL", "LB", "DB"}:
                continue
            games = _coerce_int(stats.get("gp") or stats.get("games") or 0)
            scored: dict[str, float] = {}
            # Mirror IDP_STAT_KEYS from src/idp_calibration/scoring.py
            # and accept a couple of legacy Sleeper payload aliases.
            # The loop collapses payload keys to canonical names so
            # downstream weight × stat dot-products match regardless
            # of whether the season aggregate uses the old or new
            # Sleeper naming.
            _STAT_KEY_MAP = {
                # canonical → list of payload keys to sum (first match wins)
                "idp_tkl_solo": ("idp_tkl_solo", "idp_solo"),
                "idp_tkl_ast": ("idp_tkl_ast", "idp_ast"),
                "idp_tkl": ("idp_tkl",),
                "idp_tkl_loss": ("idp_tkl_loss", "idp_tfl"),
                "idp_tkl_ast_loss": ("idp_tkl_ast_loss",),
                "idp_sack": ("idp_sack",),
                "idp_sack_yd": ("idp_sack_yd",),
                "idp_qb_hit": ("idp_qb_hit", "idp_hit"),
                "idp_int": ("idp_int",),
                "idp_int_ret_yd": ("idp_int_ret_yd",),
                "idp_pd": ("idp_pd", "idp_pass_def"),
                "idp_ff": ("idp_ff",),
                "idp_fum_rec": ("idp_fum_rec", "idp_fr"),
                "idp_fum_ret_yd": ("idp_fum_ret_yd",),
                "idp_def_td": ("idp_def_td", "idp_td"),
                "idp_safe": ("idp_safe",),
                "idp_blk_kick": ("idp_blk_kick", "idp_blk_punt"),
                "idp_def_pr_td": ("idp_def_pr_td",),
                "idp_def_kr_td": ("idp_def_kr_td",),
                "idp_tkl_10p": ("idp_tkl_10p",),
                "idp_tkl_5p": ("idp_tkl_5p",),
            }
            for canonical, payload_keys in _STAT_KEY_MAP.items():
                for pk in payload_keys:
                    val = _coerce_float(stats.get(pk))
                    if val is not None:
                        scored[canonical] = val
                        break
            out.append(
                PlayerSeason(
                    player_id=str(pid),
                    name=str(meta.get("full_name") or meta.get("first_name") or pid),
                    position=canonical,
                    games=games,
                    stats=scored,
                )
            )
        if not out:
            raise AdapterUnavailable(
                f"Sleeper stats for {season} contained zero IDP rows."
            )
        return out


class LocalCSVStatsAdapter(HistoricalStatsAdapter):
    """Read season stats from ``data/idp_calibration/stats/{season}.csv``.

    The CSV header must include ``player_id``, ``name``, ``position`` and
    any subset of the canonical IDP stat columns. Extra columns are
    ignored. ``games`` is optional.
    """

    name = "local_csv"

    def __init__(self, base_dir: Path | None = None) -> None:
        super().__init__()
        self._base_dir = base_dir or (
            repo_root() / "data" / "idp_calibration" / "stats"
        )

    def _path(self, season: int) -> Path:
        return self._base_dir / f"{int(season)}.csv"

    def _fetch_impl(self, season: int) -> list[PlayerSeason]:
        path = self._path(season)
        if not path.exists():
            raise AdapterUnavailable(f"No local stats CSV at {path}")
        out: list[PlayerSeason] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    pid = str(row.get("player_id") or "").strip()
                    if not pid:
                        continue
                    pos = _canonical_position(str(row.get("position") or "").upper())
                    if pos not in {"DL", "LB", "DB"}:
                        continue
                    stats: dict[str, float] = {}
                    # Accept every canonical IDP stat column plus a
                    # couple of legacy column names. Extra columns are
                    # ignored; missing columns are treated as zero.
                    _CSV_STAT_MAP = {
                        "idp_tkl_solo": ("idp_tkl_solo", "idp_solo"),
                        "idp_tkl_ast": ("idp_tkl_ast", "idp_ast"),
                        "idp_tkl": ("idp_tkl",),
                        "idp_tkl_loss": ("idp_tkl_loss", "idp_tfl"),
                        "idp_tkl_ast_loss": ("idp_tkl_ast_loss",),
                        "idp_sack": ("idp_sack",),
                        "idp_sack_yd": ("idp_sack_yd",),
                        "idp_qb_hit": ("idp_qb_hit", "idp_hit"),
                        "idp_int": ("idp_int",),
                        "idp_int_ret_yd": ("idp_int_ret_yd",),
                        "idp_pd": ("idp_pd", "idp_pass_def"),
                        "idp_ff": ("idp_ff",),
                        "idp_fum_rec": ("idp_fum_rec", "idp_fr"),
                        "idp_fum_ret_yd": ("idp_fum_ret_yd",),
                        "idp_def_td": ("idp_def_td", "idp_td"),
                        "idp_safe": ("idp_safe",),
                        "idp_blk_kick": ("idp_blk_kick", "idp_blk_punt"),
                        "idp_def_pr_td": ("idp_def_pr_td",),
                        "idp_def_kr_td": ("idp_def_kr_td",),
                        "idp_tkl_10p": ("idp_tkl_10p",),
                        "idp_tkl_5p": ("idp_tkl_5p",),
                    }
                    for canonical, column_names in _CSV_STAT_MAP.items():
                        for col in column_names:
                            val = _coerce_float(row.get(col))
                            if val is not None:
                                stats[canonical] = val
                                break
                    out.append(
                        PlayerSeason(
                            player_id=pid,
                            name=str(row.get("name") or pid),
                            position=pos,
                            games=_coerce_int(row.get("games") or 0),
                            stats=stats,
                        )
                    )
        except OSError as exc:
            raise AdapterUnavailable(f"Failed reading {path}: {exc}") from exc
        if not out:
            raise AdapterUnavailable(f"Local CSV at {path} contained no IDP rows.")
        return out


class ManualFallbackAdapter(HistoricalStatsAdapter):
    """No-op adapter that exposes a clear reason.

    Returned by :func:`get_stats_adapter` only when no real adapter
    can serve the season. The engine surfaces this loudly in the
    ``warnings`` block so the reviewer cannot miss it.
    """

    name = "manual_fallback"

    def __init__(self, reason: str = "No stats adapter available.") -> None:
        super().__init__()
        self.reason = reason

    def _fetch_impl(self, season: int) -> list[PlayerSeason]:
        return []

    def available(self, season: int) -> bool:
        return True


_ADAPTER_ORDER = ("sleeper", "local_csv", "manual_fallback")


def _detect_test_context() -> bool:
    """Heuristic: are we running under pytest?

    Checking ``sys.modules`` is the cheapest reliable signal — pytest
    always imports itself before any test collects, and production
    server processes never import it. We use this to default network
    *off* under tests while keeping it *on* in production so the live
    lab works without operator env-var plumbing.
    """
    import sys as _sys

    if "pytest" in _sys.modules:
        return True
    if os.getenv("PYTEST_CURRENT_TEST"):
        return True
    return False


def get_stats_adapter(
    season: int,
    *,
    order: Iterable[str] | None = None,
    allow_network: bool | None = None,
) -> tuple[HistoricalStatsAdapter, list[str]]:
    """Return the first available adapter for ``season``.

    ``allow_network`` resolves in this order:

    1. Explicit caller argument wins.
    2. ``IDP_CALIBRATION_ALLOW_NETWORK`` env var — ``"1"`` / ``"true"``
       / ``"yes"`` / ``"on"`` enables; ``"0"`` / ``"false"`` / ``"no"``
       / ``"off"`` disables.
    3. Otherwise, **default on in production, off under pytest**. This
       lets a freshly-deployed production backend probe Sleeper without
       requiring the operator to edit ``.env`` by hand, while keeping
       the unit-test suite network-free by default.
    """
    if allow_network is None:
        env_val = str(os.getenv("IDP_CALIBRATION_ALLOW_NETWORK", "")).strip().lower()
        if env_val in {"1", "true", "yes", "on"}:
            allow_network = True
        elif env_val in {"0", "false", "no", "off"}:
            allow_network = False
        else:
            allow_network = not _detect_test_context()
    attempted: list[str] = []
    for name in order or _ADAPTER_ORDER:
        if name == "sleeper":
            if not allow_network:
                attempted.append("sleeper:skipped (network disabled)")
                continue
            adapter = SleeperStatsAdapter()
        elif name == "local_csv":
            adapter = LocalCSVStatsAdapter()
        elif name == "manual_fallback":
            adapter = ManualFallbackAdapter()
        else:
            continue
        try:
            if adapter.available(season):
                attempted.append(f"{name}:ok")
                return adapter, attempted
            attempted.append(f"{name}:unavailable")
        except AdapterUnavailable as exc:
            attempted.append(f"{name}:{exc}")
    return (
        ManualFallbackAdapter(
            reason=f"All adapters unavailable for {season}. Tried: {attempted}"
        ),
        attempted,
    )


def _canonical_position(pos: str) -> str:
    pos = (pos or "").strip().upper()
    if pos in {"DE", "DT", "EDGE", "NT", "DL"}:
        return "DL"
    if pos in {"ILB", "OLB", "MLB", "LB"}:
        return "LB"
    if pos in {"CB", "S", "SS", "FS", "DB"}:
        return "DB"
    return pos


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0
