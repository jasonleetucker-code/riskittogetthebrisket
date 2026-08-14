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

from typing import Sequence

from src.api.thresholds import threshold
from src.ros.direction import _is_veteran


_IDP_POSITIONS = {"DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"}


def tags_for_player(
    *,
    canonical_name: str,
    position: str | None,
    age: int | float | None,
    ros_value: float | None,
    ros_percentile: float | None = None,
    ros_rank_overall: int | None = None,
    dynasty_percentile: float | None = None,
    confidence: float | None = None,
    volatility_flag: bool = False,
) -> list[str]:
    """Return the list of context tags that apply to one player.

    No tag fires when ``ros_value`` is None or zero (player isn't
    ranked by any ROS source) — that's a read failure, not a meaningful
    label.  Nor when ``ros_percentile`` is missing: every strength gate
    below is a STANDING within the ROS pool, and a standing cannot be
    computed from one player.  Returning no tags is the honest answer;
    guessing one from the raw index is what this function used to do.

    ``ros_percentile`` and ``dynasty_percentile`` are 0–100 with 100 =
    best, each measured within its OWN population.
    """
    if ros_value is None or ros_value <= 0:
        return []
    if ros_percentile is None:
        return []

    elite_cut = float(threshold("ROS_ELITE_PERCENTILE"))
    strong_cut = float(threshold("ROS_STRONG_PERCENTILE"))
    depth_low = float(threshold("ROS_DEPTH_BAND_LOW_PERCENTILE"))
    seller_gap = float(threshold("ROS_SELLER_PERCENTILE_GAP"))

    pos = (position or "").upper().split("/")[0]
    is_idp = pos in _IDP_POSITIONS
    is_strong = ros_percentile >= strong_cut
    is_elite = ros_percentile >= elite_cut
    is_starter_caliber = ros_rank_overall is not None and ros_rank_overall <= 100
    is_top_idp = is_idp and ros_rank_overall is not None and ros_rank_overall <= 50
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
    if (
        veteran
        and is_strong
        and dynasty_percentile is not None
        and (ros_percentile - dynasty_percentile) >= seller_gap
    ):
        # The dynasty market hasn't caught up to current ROS strength —
        # an aging vet with strong short-term value but weakening
        # long-term profile.  Sell window before regression.
        #
        # BOTH SIDES ARE STANDINGS.  This compared a 0-9999 dynasty board
        # value against the 0-100 ROS index (``dynasty_value <
        # ros_value * 0.7``), whose right-hand side maxes at 60.8 while
        # the board's lowest priced value is 1,134 — so it could not fire
        # for any of the 1,093 rows, and never had (W29-F005).
        tags.append("Seller cash-out")
    if young and not is_strong:
        tags.append("Rebuilder hold")
    if veteran and is_strong and not is_starter_caliber:
        tags.append("Avoid unless contending")
    if not is_starter_caliber and depth_low <= ros_percentile < strong_cut:
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


def ros_percentiles(values: Sequence[float | None]) -> list[float | None]:
    """Standing within the ROS pool, 0–100, 100 = best.

    Computed over the WHOLE pool and therefore only on the server:
    ``/api/ros/player-values`` truncates to ``limit`` (500 by default),
    so a client that ranked what it received would be measuring a
    standing within the top half of the board and calling it a
    percentile.

    Rows without a positive value are not ranked and come back ``None``
    — "unranked by every ROS source" is not "worst in the league".
    """
    ranked = sorted(
        (i for i, v in enumerate(values) if isinstance(v, (int, float)) and v and v > 0),
        key=lambda i: -float(values[i]),  # type: ignore[arg-type]
    )
    out: list[float | None] = [None] * len(values)
    n = len(ranked)
    if n == 1:
        out[ranked[0]] = 100.0
        return out
    for position, idx in enumerate(ranked):
        out[idx] = round(100.0 * (n - 1 - position) / (n - 1), 4)
    return out


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
