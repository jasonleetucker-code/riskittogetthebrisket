"""Team direction labels: Strong Buyer / Buyer / Selective Buyer /
Hold / Selective Seller / Seller / Strong Seller.

ONE OF TWO DIRECTION MODELS, AND THEY ARE NOT INTERCHANGEABLE
─────────────────────────────────────────────────────────────
The app deliberately keeps two, because they answer different
questions from different input families:

* **this module** — buyer/seller from SIMULATED playoff and
  championship odds. A statement about the season in progress.
* ``src/roster_intel/window.py`` (+ its frontend port
  ``frontend/lib/team-phase.js``) — a five-state distribution over
  measured roster shape: lineup competitiveness x value-weighted
  starter age. A statement about the roster's window.

Four such models used to ship at once and agreed on 3 of 12 live teams
(audit W20-F006). Two were deleted; these two remain and every
direction-bearing payload now stamps ``directionEngine`` so a consumer
can tell which claim it is holding. Do not add a third.

WHAT ACTUALLY MOVES A LABEL HERE
────────────────────────────────
Two inputs gate the bands, and the docstring used to imply four:

  - Playoff odds (from ros.playoff_sim)          — gates every band
  - Championship odds (from ros.championship)    — gates every band
  - Roster age profile                           — gates ONLY the
    "Strong Seller / Rebuilder" band (``vetCount >= 4``), joined from
    Sleeper's player dump by ``trade_deadline.teams_with_ages``
  - Team ROS strength (data/ros/team_strength/latest.json)
    — **reported as context, gates nothing.** It is in the summary line
    and in ``rosStrengthPercentile`` on the row, and that is all it
    does. The previous docstring claimed a team's "exact band can shift
    on age + roster strength"; for strength that was never true
    (``classify_team(playoff=0, champ=0, strength=0.0|0.5|1.0)``
    returned "Seller" in all three cases — W20-F016). Writing a
    strength threshold to make the sentence true would be inventing a
    band nobody specified, so the sentence went instead.

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
    playoff_odds_pct: float | None,
    championship_odds_pct: float | None,
    team_ros_strength_percentile: float | None,
    roster_age_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return ``{label, summary, recommendation}`` for one team.

    ``playoff_odds_pct`` / ``championship_odds_pct`` are ``None`` when the
    owner was not in the simulation at all — which is NOT the same as
    having been simulated and come out at 0%. Callers used to collapse the
    two with ``or 0.0``, and since the lowest band is
    ``playoff < 0.25 and championship < 0.02``, "we did not simulate you"
    rendered as "Seller — sell aging win-now players" over a summary line
    reading "Playoff odds 0%". On the live board that hit four of twelve
    managers, including the one with the strongest roster in the league.
    Audit findings W17-F002 / W20-F002.

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
    shift on age.  We resolve ambiguity by checking the strongest tier
    first and falling through to weaker tiers.

    ``team_ros_strength_percentile`` is REPORTED, not consumed — see the
    module docstring. It is reported honestly: ``None`` renders as
    "unavailable" rather than as a confident 0%, which is the same
    absence-as-zero mistake the odds guard below exists to prevent.
    """
    age_heavy = bool((roster_age_profile or {}).get("vetCount", 0) >= 4)

    # Abstain rather than classify. Every band below is a statement about
    # simulated odds; with no odds there is nothing to say, and saying
    # "Seller" anyway is the failure this guard exists to prevent.
    if playoff_odds_pct is None or championship_odds_pct is None:
        return {
            "label": "Not simulated",
            "summary": (
                "This team was not in the latest playoff simulation, so it has "
                "no buy/sell direction. This is missing input, not a 0% chance."
            ),
            "recommendation": (
                "No direction available. Re-run the ROS playoff simulation to " "get one."
            ),
            "ageProfile": roster_age_profile or {},
            "oddsSource": "owner_not_in_simulation",
        }

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
        rec = "Sell aging win-now players.  Prioritize 2026/2027 picks " "and 23-or-younger upside."
    elif 0.20 <= playoff_odds_pct < 0.40:
        label = "Selective Seller"
        rec = "Sell older short-term assets if strong offers arrive.  " "Hold the youth core."
    else:
        label = "Hold / Evaluate"
        rec = (
            "Avoid extreme buy/sell unless an offer is clearly "
            "asymmetric.  Re-evaluate weekly as standings shift."
        )

    strength_text = (
        f"{round(team_ros_strength_percentile * 100)}%"
        if team_ros_strength_percentile is not None
        else "unavailable"
    )
    summary = (
        f"Playoff odds {playoff_odds_pct * 100:.0f}% · "
        f"Championship odds {championship_odds_pct * 100:.1f}% · "
        f"ROS strength percentile {strength_text}"
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
