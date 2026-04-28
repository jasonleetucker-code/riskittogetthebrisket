"""ROS source registry.

The single Python-side declaration of every ROS source.  Frontend mirror
lives at ``frontend/lib/ros-sources.js`` (parity test:
``tests/ros/test_sources_registry_parity.py``).

Adding a new source:

    1. Implement a scraper module under ``src/ros/sources/<key>.py`` that
       exposes ``scrape(*, output_path: Path) -> ScrapeResult``.
    2. Add an entry to ``ROS_SOURCES`` below.
    3. Mirror the entry in ``frontend/lib/ros-sources.js``.
    4. Add a fixture-based parser test under ``tests/adapters/``.
    5. Run the parity test.

Each entry is a dict with these fields (all required unless noted):

    key                      str   — canonical identifier; matches CSV stem
    display_name             str   — UI label
    source_url               str   — human-friendly source page URL
    source_type              str   — "ros" | "dynasty_proxy" | "adp" | "projection"
    scoring_format           str   — "ppr" | "half_ppr" | "standard"
    is_superflex             bool
    is_2qb                   bool
    is_te_premium            bool
    is_idp                   bool
    is_ros                   bool  — true for actual ROS pages, false for dynasty/season-long fallbacks
    is_dynasty               bool  — true if the source is dynasty-flavored (used as low-weight ROS proxy)
    is_projection_source     bool  — true if source provides per-player point projections
    base_weight              float — per-spec weights (DraftSharks ROS = 1.25, FantasyPros consensus = 1.15, etc.)
    stale_after_hours        int   — freshness threshold; older → marked stale
    scraper                  str   — module path (e.g. "src.ros.sources.fantasypros_ros_sf")
    enabled                  bool  — runtime gate; can be flipped via settings without removing the entry

The registry is import-time stable and read-only.  Per-source overrides
(weight tweaks, enable/disable) flow through the user settings layer at
``frontend/components/useSettings.js`` and arrive at the orchestrator as
a separate ``settings`` dict — they NEVER mutate this list.
"""
from __future__ import annotations

from typing import Any

# Registry — kept as a tuple so accidental mutation raises rather than
# silently corrupts global state.
ROS_SOURCES: tuple[dict[str, Any], ...] = (
    # ── PR 1 adapters ────────────────────────────────────────────────
    # FantasyPros Dynasty Superflex.  This is registered as a
    # ``dynasty_proxy`` (is_ros=False) because the ECR ROS Superflex
    # page sits behind a soft paywall — the existing dynasty SF feed
    # is the highest-quality free proxy for ROS Superflex direction.
    # Weight is intentionally low so when richer ROS sources land in
    # PR 2/PR 5, FantasyPros falls into background fallback.
    {
        "key": "fantasyProsRosSf",
        "display_name": "FantasyPros Dynasty SF (ROS proxy)",
        "source_url": "https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php",
        "source_type": "dynasty_proxy",
        "scoring_format": "ppr",
        "is_superflex": True,
        "is_2qb": False,
        "is_te_premium": False,
        "is_idp": False,
        "is_ros": False,
        "is_dynasty": True,
        "is_projection_source": False,
        "base_weight": 0.85,
        "stale_after_hours": 168,
        "scraper": "src.ros.sources.fantasypros_ros_sf",
        "enabled": True,
    },
    # DraftSharks SF + IDP ROS — premium login already wired for the
    # dynasty path (DRAFTSHARKS_EMAIL/PASSWORD env vars).  This is
    # the highest-confidence ROS source we have access to today.
    # Weight matches the user spec's "Draft Sharks PPR Superflex
    # ROS: 1.25" / "Draft Sharks IDP ROS: 1.25".
    {
        "key": "draftSharksRosSf",
        "display_name": "Draft Sharks ROS Superflex",
        "source_url": "https://www.draftsharks.com/rankings/rest-of-season",
        "source_type": "ros",
        "scoring_format": "ppr",
        "is_superflex": True,
        "is_2qb": False,
        "is_te_premium": False,
        "is_idp": False,
        "is_ros": True,
        "is_dynasty": False,
        "is_projection_source": True,
        "base_weight": 1.25,
        "stale_after_hours": 24,
        "scraper": "src.ros.sources.draftsharks_ros",
        "enabled": True,
    },
)


def ros_source_keys() -> list[str]:
    """Return the ordered list of ROS source keys."""
    return [str(s["key"]) for s in ROS_SOURCES]


def get_ros_source(key: str) -> dict[str, Any] | None:
    """Return the registry entry for a key, or None when unknown."""
    for src in ROS_SOURCES:
        if str(src.get("key")) == key:
            return dict(src)
    return None


def enabled_ros_sources(
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return ROS sources that are enabled, applying user overrides.

    ``overrides`` is the per-source settings dict the frontend POSTs in
    when the user toggles sources on /settings.  Shape:

        {"fantasyProsRosSf": {"enabled": False, "weight": 0.5}, ...}

    A copy is returned so callers can safely mutate the result list.
    """
    out: list[dict[str, Any]] = []
    for src in ROS_SOURCES:
        key = str(src.get("key") or "")
        ov = (overrides or {}).get(key) or {}
        if "enabled" in ov and not ov["enabled"]:
            continue
        if not src.get("enabled", True):
            continue
        copy = dict(src)
        if "weight" in ov:
            try:
                copy["base_weight"] = float(ov["weight"])
            except (TypeError, ValueError):
                pass
        out.append(copy)
    return out
