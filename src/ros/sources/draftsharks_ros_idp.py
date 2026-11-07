"""Draft Sharks ROS IDP adapter (``draftSharksRosIdp``).

A registry entry point only: ``scrape.run_all`` invokes
``<module>.scrape(src_meta=...)``, and the superflex key already owns
``draftsharks_ros.scrape``.  The board logic, and the rule that keeps the
two keys on one rank basis each, live in ``src/ros/sources/draftsharks_ros.py``.
"""

from __future__ import annotations

from typing import Any

from src.ros.scrape import ScrapeResult
from src.ros.sources.draftsharks_ros import scrape_idp


def scrape(src_meta: dict[str, Any]) -> ScrapeResult:
    return scrape_idp(src_meta)
