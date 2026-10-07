"""Championship / title odds — an ADAPTER over the one canonical engine.

C5-PLAY-01: this module no longer simulates.  It reshapes the canonical
forecast from :mod:`src.ros.playoff_sim` (playoff, championship, finals,
semifinal odds and expected finish, all recorded off ONE simulation's
seeding and bracket) into the ``/api/public/league/rosChampionship`` shape
and adds the presentation-only ``contenderTier`` label.

Shape (unchanged)::

    {
        "championshipOdds": [{ownerId, displayName,
                              championshipOdds, finalsOdds,
                              semifinalOdds, playoffOdds, expectedFinish,
                              contenderTier}],
        "n_simulations": int,
        "playoffSeeds": int,
        "byeSeeds": int,
        "playoffStructure": {...},
        "rosStrengthAvailable": bool,
        "unsimulable": {...},   # only when the canonical engine refused
    }

The retired second loop (fixed-pairing bracket, coin-flip playoff ties, fixed
10,000 draws, its own ``*_championship.json`` read) is deleted rather than
deprecated: a complete second simulator beside the live one is how this
surface came to publish different odds from ``rosPlayoffOdds``.
"""

from __future__ import annotations

import random
from typing import Any

from src.public_league.snapshot import PublicLeagueSnapshot
from src.ros import playoff_sim


# Contender-tier thresholds (per spec).
def _contender_tier(championship_odds: float, playoff_odds_pct: float) -> str:
    """Map odds to a contender label."""
    if championship_odds >= 0.20:
        return "Favorite"
    if championship_odds >= 0.10:
        return "Serious Contender"
    if championship_odds >= 0.05 or playoff_odds_pct >= 0.50:
        return "Dangerous Playoff Team"
    if playoff_odds_pct >= 0.30:
        return "Fringe Playoff Team"
    if playoff_odds_pct >= 0.10:
        return "Long Shot"
    return "Rebuilder / Seller"


#: Where every number on this surface comes from.
ENGINE = "src.ros.playoff_sim"

#: The row fields this surface publishes, each read from the canonical
#: forecast row of the same name.  ``contenderTier`` is the one derived field.
_ROW_FIELDS = (
    "championshipOdds",
    "finalsOdds",
    "semifinalOdds",
    "playoffOdds",
    "expectedFinish",
)


def championship_from_forecast(forecast: dict[str, Any]) -> dict[str, Any]:
    """Reshape the ONE canonical forecast into this section's shape.

    No simulation happens here (C5-PLAY-01).  This module used to run a
    second Monte Carlo over the same team distributions with its own bracket
    (fixed pairings, coin-flip ties, a fixed 10,000 draws), so the
    Championship tab's playoff and title odds were a different random sample
    — and on brackets with byes a different bracket — from the numbers
    ``rosPlayoffOdds`` published for the same league and week.  Every number
    below is the canonical engine's, field for field.

    A refusal passes through with its own ``unsimulable`` block and
    ``n_simulations: 0``.  A canonical row missing one of :data:`_ROW_FIELDS`
    publishes ``None`` for it and names the field in
    ``unavailableFields`` — never ``0``.
    """
    header = {
        "playoffSeeds": forecast.get("playoffSeeds"),
        "byeSeeds": forecast.get("byeSeeds"),
        "playoffStructure": forecast.get("playoffStructure"),
        "rosStrengthAvailable": forecast.get("rosStrengthAvailable"),
        "engine": ENGINE,
    }
    for key in ("computedAt", "cached", "season"):
        if key in forecast:
            header[key] = forecast[key]
    rows_in = forecast.get("playoffOdds") or []
    if forecast.get("unsimulable") or not rows_in:
        out = {"championshipOdds": [], "n_simulations": 0, **header}
        if forecast.get("unsimulable"):
            out["unsimulable"] = forecast["unsimulable"]
        return out

    rows: list[dict[str, Any]] = []
    for r in rows_in:
        row: dict[str, Any] = {
            "ownerId": r.get("ownerId"),
            "displayName": r.get("displayName"),
        }
        missing: list[str] = []
        for field in _ROW_FIELDS:
            value = r.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                value = None
                missing.append(field)
            row[field] = value
        champ, playoff = row["championshipOdds"], row["playoffOdds"]
        row["contenderTier"] = (
            _contender_tier(champ, playoff) if champ is not None and playoff is not None else None
        )
        if missing:
            row["unavailableFields"] = missing
        rows.append(row)
    rows.sort(key=lambda r: -(r["championshipOdds"] or 0.0))
    return {
        "championshipOdds": rows,
        "n_simulations": forecast.get("n_simulations") or 0,
        **header,
    }


def simulate_championship_odds(
    snapshot: PublicLeagueSnapshot,
    *,
    n_simulations: int | None = None,
    playoff_seeds: int | None = None,
    bye_seeds: int | None = None,
    best_ball: bool | None = None,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Championship odds for ``snapshot`` from ONE canonical simulation.

    Runs :func:`src.ros.playoff_sim.simulate_playoff_odds` with the same
    arguments and reshapes it.  ``n_simulations=None`` is the canonical
    engine's adaptive count (it used to default to a fixed 10,000 here, which
    is itself a second answer).  Production does not call this: the scheduled
    scrape reshapes the playoff forecast it already ran
    (:func:`championship_from_forecast`), and the lazy section reads
    :func:`src.ros.playoff_sim.canonical_forecast`.
    """
    return championship_from_forecast(
        playoff_sim.simulate_playoff_odds(
            snapshot,
            n_simulations=n_simulations,
            playoff_seeds=playoff_seeds,
            bye_seeds=bye_seeds,
            best_ball=best_ball,
            rng=rng,
        )
    )


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Lazy-section builder for /api/public/league/rosChampionship.

    The canonical forecast (the scheduled scrape's playoff file when it is
    fresh and describes this snapshot, else one shared live run), reshaped.
    It no longer reads ``*_championship.json``: that file is still written
    for the trade-deadline rollup and the AL-P6 forecast archive, from the
    same run, but reading the playoff forecast directly is what makes this
    surface and ``rosPlayoffOdds`` one answer by construction.
    """
    return championship_from_forecast(playoff_sim.canonical_forecast(snapshot))
