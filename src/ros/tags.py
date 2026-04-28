"""Per-player short-term context tags.

Pure-function tag classifier.  Inputs are ``ros_value``, ``ros_rank``,
position, age, and (optionally) the player's dynasty value for the
"Win-now target" / "Avoid unless contending" age-vs-ROS-mismatch
labels.

Tags emitted:
    "Win-now target"           — strong ROS, older age, dynasty risk
    "Contender upgrade"        — strong ROS starter, helps playoff push
    "Seller cash-out"          — older + strong ROS + declining dynasty window
    "Rebuilder hold"           — young + moderate/weak ROS + good long-term profile
    "Avoid unless contending"  — short-term points, age + dynasty risk
    "Depth spike option"       — useful best-ball, not a true anchor
    "Best-ball boost"          — volatile weekly spike player
    "IDP contender target"     — strong ROS IDP starter for playoff push
    "Injury/bye cover"         — short-term coverage, low dynasty impact

Read-only:  these are informational labels.  No changes to dynasty
trade math, no changes to dynasty values.
"""
from __future__ import annotations

from typing import Any

from src.ros.direction import _is_veteran


_IDP_POSITIONS = {"DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"}


def tags_for_player(
    *,
    canonical_name: str,
    position: str | None,
    age: int | float | None,
    ros_value: float | None,
    ros_rank_overall: int | None = None,
    dynasty_value: float | None = None,
    confidence: float | None = None,
    volatility_flag: bool = False,
) -> list[str]:
    """Return the list of context tags that apply to one player.

    No tag fires when ``ros_value`` is None or zero (player isn't
    ranked by any ROS source) — that's a read failure, not a meaningful
    label.
    """
    if ros_value is None or ros_value <= 0:
        return []

    pos = (position or "").upper().split("/")[0]
    is_idp = pos in _IDP_POSITIONS
    is_strong = ros_value >= 60.0  # 0-100 normalized scale
    is_elite = ros_value >= 80.0
    is_starter_caliber = (
        ros_rank_overall is not None and ros_rank_overall <= 100
    )
    is_top_idp = (
        is_idp
        and ros_rank_overall is not None
        and ros_rank_overall <= 50
    )
    veteran = _is_veteran(pos, age)
    young = False
    try:
        young = (age is not None) and float(age) <= 24
    except (TypeError, ValueError):
        pass

    tags: list[str] = []

    if veteran and is_strong:
        tags.append("Win-now target")
    if is_elite and is_starter_caliber and not is_idp:
        tags.append("Contender upgrade")
    if veteran and is_strong and dynasty_value is not None and dynasty_value < ros_value * 0.7:
        # The dynasty market hasn't caught up to current ROS strength —
        # an aging vet with strong short-term value but weakening
        # long-term profile.  Sell window before regression.
        tags.append("Seller cash-out")
    if young and not is_strong:
        tags.append("Rebuilder hold")
    if veteran and is_strong and not is_starter_caliber:
        tags.append("Avoid unless contending")
    if not is_starter_caliber and ros_value >= 30 and ros_value < 60:
        tags.append("Depth spike option")
    if volatility_flag and is_starter_caliber:
        tags.append("Best-ball boost")
    if is_top_idp:
        tags.append("IDP contender target")
    if not is_strong and not young:
        # Short-term coverage candidate — useful for byes/injuries, no
        # dynasty upside.
        tags.append("Injury/bye cover")

    return tags


def tag_descriptions() -> dict[str, str]:
    """One-liner descriptions for the UI tooltip per tag."""
    return {
        "Win-now target": "Strong short-term value, but age limits dynasty upside. Best fit for buyers chasing the title.",
        "Contender upgrade": "Elite ROS starter who immediately raises a contender's weekly ceiling.",
        "Seller cash-out": "Older player with strong ROS value and a declining dynasty window. Sell now before regression.",
        "Rebuilder hold": "Young upside; long-term profile beats current ROS. Hold through development window.",
        "Avoid unless contending": "Age + dynasty risk only justified if the title odds boost is meaningful.",
        "Depth spike option": "Useful for best-ball spikes; not a true lineup anchor.",
        "Best-ball boost": "Volatile weekly player whose ceiling captures spike weeks in best ball.",
        "IDP contender target": "Strong ROS IDP starter — high-leverage piece for playoff pushes.",
        "Injury/bye cover": "Short-term coverage only; low dynasty impact.",
    }
