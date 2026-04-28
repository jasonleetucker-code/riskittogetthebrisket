"""Team direction labels: Strong Buyer / Buyer / Selective Buyer /
Hold / Selective Seller / Seller / Strong Seller.

Combines:
  - Playoff odds (from ros.playoff_sim)
  - Championship odds (from ros.championship)
  - Team ROS strength (from data/ros/team_strength/latest.json)
  - Roster age profile (computed from the live player pool)

Per spec, age thresholds are position-aware:
  QB 32+, RB 26+, WR 29+, TE 30+, DL/EDGE 30+, LB 29+, DB 29+

The classifier is deterministic — same inputs always produce the same
label.  No mutation of dynasty values, trade math, or the player
contract.  Read-only contender layer.
"""
from __future__ import annotations

from typing import Any

# Per-position age thresholds at which a player counts as "veteran"
# in the dynasty-age profile.  Spec values verbatim.
_VETERAN_AGE: dict[str, int] = {
    "QB": 32,
    "RB": 26,
    "WR": 29,
    "TE": 30,
    "DL": 30,
    "DE": 30,
    "DT": 30,
    "EDGE": 30,
    "LB": 29,
    "DB": 29,
    "S": 29,
    "CB": 29,
}


def _is_veteran(position: str | None, age: int | float | None) -> bool:
    if position is None or age is None:
        return False
    try:
        age_val = float(age)
    except (TypeError, ValueError):
        return False
    threshold = _VETERAN_AGE.get(str(position).upper().split("/")[0])
    if threshold is None:
        return False
    return age_val >= threshold


def classify_team(
    *,
    playoff_odds_pct: float,
    championship_odds_pct: float,
    team_ros_strength_percentile: float | None,
    roster_age_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``{label, summary, recommendation}`` for one team.

    Spec mapping (slightly adjusted for clarity):
      - Strong Buyer:        playoff >= 0.75 AND championship >= 0.10
      - Buyer:               playoff >= 0.60 AND championship >= 0.05
      - Selective Buyer:     0.45 <= playoff < 0.60
      - Hold:                0.35 <= playoff < 0.55 with low championship odds
      - Selective Seller:    0.20 <= playoff < 0.40 with low championship odds
      - Seller:              playoff < 0.25 AND championship < 0.02
      - Strong Seller / Rebuilder:
                             playoff < 0.10 AND championship < 0.01
                             AND age-heavy roster

    The spec's ranges overlap intentionally so a team's exact band can
    shift on age + roster strength.  We resolve ambiguity by checking
    the strongest tier first and falling through to weaker tiers.
    """
    age_heavy = bool((roster_age_profile or {}).get("vetCount", 0) >= 4)
    strength_pct = team_ros_strength_percentile or 0.0

    if playoff_odds_pct >= 0.75 and championship_odds_pct >= 0.10:
        label = "Strong Buyer"
        rec = (
            "Prioritize lineup-anchor upgrades.  Pay up for elite "
            "starters; avoid hoarding picks."
        )
    elif playoff_odds_pct >= 0.60 and championship_odds_pct >= 0.05:
        label = "Buyer"
        rec = (
            "Buy if the cost is reasonable.  Target undervalued "
            "starters that move your weekly ceiling."
        )
    elif 0.45 <= playoff_odds_pct < 0.60:
        label = "Selective Buyer"
        rec = (
            "Target undervalued starters; avoid all-in moves until "
            "championship odds rise above 5%."
        )
    elif playoff_odds_pct < 0.10 and championship_odds_pct < 0.01 and age_heavy:
        label = "Strong Seller / Rebuilder"
        rec = (
            "Sell aging veterans aggressively for picks + youth.  "
            "Expected finish suggests a true rebuild window."
        )
    elif playoff_odds_pct < 0.25 and championship_odds_pct < 0.02:
        label = "Seller"
        rec = (
            "Sell aging win-now players.  Prioritize 2026/2027 picks "
            "and 23-or-younger upside."
        )
    elif 0.20 <= playoff_odds_pct < 0.40:
        label = "Selective Seller"
        rec = (
            "Sell older short-term assets if strong offers arrive.  "
            "Hold the youth core."
        )
    else:
        label = "Hold / Evaluate"
        rec = (
            "Avoid extreme buy/sell unless an offer is clearly "
            "asymmetric.  Re-evaluate weekly as standings shift."
        )

    summary = (
        f"Playoff odds {playoff_odds_pct * 100:.0f}% · "
        f"Championship odds {championship_odds_pct * 100:.1f}% · "
        f"ROS strength percentile {round(strength_pct * 100)}%"
    )

    return {
        "label": label,
        "summary": summary,
        "recommendation": rec,
        "ageProfile": roster_age_profile or {},
    }


def build_roster_age_profile(roster: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize a team's roster by age bucket.

    ``roster`` entries must carry ``position`` + ``age``.  Missing ages
    are skipped (not counted as veteran or young).
    """
    vet_count = 0
    young_count = 0
    total = 0
    age_sum = 0.0
    age_n = 0
    for p in roster:
        pos = (p.get("position") or "").upper()
        age = p.get("age")
        total += 1
        if _is_veteran(pos, age):
            vet_count += 1
        try:
            n = float(age) if age is not None else None
        except (TypeError, ValueError):
            n = None
        if n is not None:
            age_sum += n
            age_n += 1
            if n <= 24:
                young_count += 1
    return {
        "totalPlayers": total,
        "vetCount": vet_count,
        "youngCount": young_count,
        "averageAge": round(age_sum / age_n, 1) if age_n else None,
    }
