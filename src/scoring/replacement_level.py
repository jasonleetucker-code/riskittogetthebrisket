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
1. ``starter_slot_counts`` — maps a Sleeper ``roster_positions`` list
   plus team count to ``{position: int}``.  Splits FLEX (RB/WR/TE
   1/3 each), SUPER_FLEX (QB/RB/WR/TE 1/4 each), REC_FLEX (WR/TE/RB
   1/3 each), IDP_FLEX (DL/LB/DB 1/3 each).
2. ``replacement_per_game`` — per-position replacement-level
   points-per-game.  Defined as the average per-game pace of the
   five players ranked just *below* the league's starter cutoff
   (so injured starters don't anchor the baseline).
3. ``vorp_table`` — for each player: ``vorp = points - replacement
   * games``.  Returns sorted descending.

What this module does NOT own
─────────────────────────────
* No Sleeper roster fetch — caller passes already-built rows.
* No team / owner attribution — the input row is intentionally
  flat.  ``awards.py`` decorates with team / owner after calling
  ``vorp_table``.
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


@dataclass(frozen=True)
class VorpRow:
    player_id: str
    position: str
    player_name: str
    points: float
    games: int
    vorp: float
    replacement_per_game: float


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
    for slot in roster_positions or []:
        slot_norm = str(slot or "").upper()
        if slot_norm in {"BN", "TAXI", "IR", ""}:
            continue
        if slot_norm == "FLEX":
            for p in ("RB", "WR", "TE"):
                counts[p] += 1.0 / 3.0
        elif slot_norm in {"SUPER_FLEX", "SUPERFLEX", "SFLEX", "QFLEX"}:
            for p in ("QB", "RB", "WR", "TE"):
                counts[p] += 1.0 / 4.0
        elif slot_norm in {"REC_FLEX", "WRT", "WRRBTE"}:
            for p in ("WR", "TE", "RB"):
                counts[p] += 1.0 / 3.0
        elif slot_norm in {"IDP_FLEX"}:
            for p in ("DL", "LB", "DB"):
                counts[p] += 1.0 / 3.0
        elif slot_norm in {"DEF"}:
            counts["DEF"] += 1.0
        else:
            counts[slot_norm] += 1.0
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
        games = r.games if isinstance(r, PlayerSeasonRow) else r.get("games") or r.get("gamesStarted")
        points = r.points if isinstance(r, PlayerSeasonRow) else r.get("points") or r.get("starterPoints")
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


# ── Top-level VORP table ──────────────────────────────────────────
def vorp_table(
    rows: Iterable[PlayerSeasonRow],
    starter_slots_by_pos: dict[str, int],
    *,
    band_size: int = 5,
) -> list[VorpRow]:
    """Compute VORP per player, grouped by position.

    For each position present in ``rows``:

      * Look up the position's ``starter_slots`` from
        ``starter_slots_by_pos``.  Positions with no slot
        configured fall back to ``max(1, len(group)//2)`` so a
        single-game cameo doesn't outshine real full-season
        starters.
      * Compute the per-game replacement baseline via
        ``replacement_per_game``.
      * Per player: ``vorp = points - (replacement_per_game * games)``.

    Returns a single flat list of ``VorpRow``s sorted by ``vorp``
    descending.  Callers that want per-position views can group by
    ``row.position`` after the fact.
    """
    grouped: dict[str, list[PlayerSeasonRow]] = defaultdict(list)
    for r in rows or []:
        if not isinstance(r, PlayerSeasonRow):
            continue
        if not r.position:
            continue
        if r.games <= 0:
            continue
        grouped[r.position].append(r)

    out: list[VorpRow] = []
    for pos, group in grouped.items():
        slots = starter_slots_by_pos.get(pos, 0)
        if slots <= 0:
            slots = max(1, len(group) // 2)
        rpg = replacement_per_game(group, slots, band_size=band_size)
        for r in group:
            replacement_total = rpg * r.games
            vorp = r.points - replacement_total
            out.append(
                VorpRow(
                    player_id=r.player_id,
                    position=pos,
                    player_name=r.player_name,
                    points=round(r.points, 2),
                    games=r.games,
                    vorp=round(vorp, 2),
                    replacement_per_game=round(rpg, 2),
                )
            )
    out.sort(key=lambda v: -v.vorp)
    return out
