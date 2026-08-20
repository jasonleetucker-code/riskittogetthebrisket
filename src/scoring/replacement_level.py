"""Replacement-level / VORP math, source-agnostic.

Lifted from ``src/public_league/awards.py`` (where it powered the
League MVP / Playoff MVP awards) into a shared module so the new
IDP scoring-fit pipeline can reuse the same flex-aware replacement
algorithm.

Generic over the input rows: callers pass ``PlayerSeasonRow``s
they've built from whatever source (Sleeper matchup ``players_points``
in the awards path, nflverse-derived realized points in the
scoring-fit path, future projection sources in Phase 2+).

What this module owns
─────────────────────
1. ``replacement_per_game`` — per-position replacement-level
   points-per-game.  Defined as the average per-game pace of the
   five players ranked just *below* the league's starter cutoff
   (so injured starters don't anchor the baseline).  **This is the
   canonical owner of the fantasy-points replacement baseline**, and
   ``public_league/awards.py`` consumes it through a shim.
2. ``starter_slot_counts`` — maps a Sleeper ``roster_positions`` list
   plus team count to ``{position: int}``.  The flex split comes from
   the canonical lineup owner (``src/ros/lineup.slot_demand``), not
   from a table here; see the function for the REC_FLEX correction
   that came with it.  Currently unconsumed.

What this module does NOT own
─────────────────────────────
* No Sleeper roster fetch — caller passes already-built rows.
* No per-player VORP table.  ``vorp_table`` was retired by V1-29 —
  it had no production caller and no test, and its stated purpose
  (reuse by the IDP scoring-fit pipeline) never landed.  The live
  VORP is ``public_league/awards.py::_vorp_rows``, which is NOT a
  copy of it: it runs on STARTER-ONLY points and an award-convention
  slot table, and delegates only the baseline to this module.
* No fantasy-points computation — caller pre-computes
  ``points`` (e.g. via ``realized_points.compute_cumulative_points``).

This split is what makes the module reusable: every consumer
produces ``PlayerSeasonRow``s from a different source, then calls
the same VORP math.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from src.ros.lineup import slot_demand


# ── Public input contract ─────────────────────────────────────────
@dataclass(frozen=True)
class PlayerSeasonRow:
    """One player's (already-aggregated) season production.

    ``games`` is the games played count used to derive per-game
    pace; if ``games == 0`` the row is silently dropped (a
    no-game-played row would otherwise produce a div-by-zero in
    the per-game replacement math).
    """

    player_id: str
    position: str
    points: float
    games: int
    # Optional metadata — kept here so callers don't have to maintain
    # a parallel lookup; the VORP functions ignore it.
    player_name: str = ""


# ── Slot-counting (flex-aware) ────────────────────────────────────
def starter_slot_counts(
    roster_positions: Iterable[str] | None,
    num_teams: int,
) -> dict[str, int]:
    """Total starting slots per position across the entire league
    per week.

    Reads a Sleeper-style ``roster_positions`` list and counts both
    direct slots (``"QB"``) and flexes (``"FLEX"``, ``"SUPER_FLEX"``,
    ``"REC_FLEX"``, ``"IDP_FLEX"``) which contribute fractionally to
    multiple eligible positions.  Multiplied by ``num_teams``.

    Slot names, aliases and eligibility all come from the canonical
    owner ``src/ros/lineup.py`` (C2-U1).  One behaviour change came with
    that: ``REC_FLEX`` is a WR/TE flex and now splits two ways, where
    this module had split it three ways across WR/TE/RB.  Neither live
    league runs one.

    Flex contributions split evenly across eligible positions —
    close enough for a VORP baseline without overfitting; the
    proposal's "dynamic flex allocation" algorithm achieves the same
    result via iteration but yields essentially the same per-position
    counts at the league sizes we run.

    Returns at minimum 1 slot for any position that appears (so a
    division-by-zero never reaches the replacement-band picker).
    """
    teams = max(1, int(num_teams or 0))
    counts: dict[str, float] = defaultdict(float)
    # Reads the canonical :func:`slot_demand` contract's ``even_split``
    # (C2-U1) rather than re-deriving the split inline — this was one of
    # four independent copies of the same rule, and the only one that
    # spelled ``REC_FLEX``/``WRT`` as RB/WR/TE (a WR-TE flex is not a
    # full offensive flex).  Routing through the owner also fixes that.
    for pos, frac in slot_demand(list(roster_positions or [])).even_split.items():
        counts[pos] += frac
    for slot in roster_positions or []:
        if str(slot or "").strip().upper() == "DEF":
            counts["DEF"] += 1.0
    out: dict[str, int] = {}
    for pos, frac in counts.items():
        out[pos] = max(1, int(round(frac * teams)))
    return out


# ── Replacement-level baseline ────────────────────────────────────
def replacement_per_game(
    rows: Iterable[PlayerSeasonRow] | Iterable[dict],
    starter_slots: int,
    *,
    band_size: int = 5,
) -> float:
    """Replacement-level points-per-game at a single position.

    Defined as the mean per-game pace of the ``band_size`` players
    ranked just below the league's starter cutoff.  The
    just-below-the-cutoff band is the right baseline because:

    * It's what a manager would actually field if their starter
      went down — the next eligible body, not the worst rostered
      backup.
    * Per-game pace (not season total) means a half-injured starter
      who scored 80 points in 6 games doesn't anchor the baseline
      below replacement.

    Falls back to the worst player's per-game line if the position
    has fewer rostered players than ``starter_slots + band_size``.

    Accepts either ``PlayerSeasonRow`` or plain dicts (the awards
    path uses dicts; new callers should use the dataclass).
    """
    per_game: list[float] = []
    for r in rows or []:
        games = (
            r.games if isinstance(r, PlayerSeasonRow) else r.get("games") or r.get("gamesStarted")
        )
        points = (
            r.points
            if isinstance(r, PlayerSeasonRow)
            else r.get("points") or r.get("starterPoints")
        )
        try:
            g = int(games or 0)
            p = float(points or 0)
        except (TypeError, ValueError):
            continue
        if g <= 0:
            continue
        per_game.append(p / g)
    if not per_game:
        return 0.0
    per_game.sort(reverse=True)
    cutoff = max(0, int(starter_slots))
    band = per_game[cutoff : cutoff + max(1, band_size)]
    if not band:
        return per_game[-1]
    return sum(band) / len(band)
