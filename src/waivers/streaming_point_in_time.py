"""Point-in-time candidate universe and projection-timestamp audit for IDP
streaming research (shadow only).

A small, stable surface over the streaming backtest's leakage boundary
(:func:`src.waivers.streaming_backtest.build_decision_context`) so other
SHADOW research (e.g. the IDP opportunity challengers of issue #2039) can use
the same decision instant, the same candidate pool and the same timestamp
rules instead of re-deriving them.  It decides nothing and nothing live
imports it.

Rules it holds:

* the candidate universe at week ``w`` is what was knowable at week ``w``'s
  FIRST kickoff (``SeasonData.cutoffs[w]``): defenders on no other roster at
  the end of week ``w - 1`` (``masked`` also removes anyone another team
  rostered in week ``w`` -- a cleared-waivers $0 add);
* a projection row is a HISTORICAL FORECAST only if it is proven pre-kickoff:
  an immutable archive capture fetched before the cutoff, or a provider
  ``updated_at`` before the cutoff.  A row revised after kickoff is
  ``post_kickoff``; a row with no stamp is ``unstamped`` -- neither is ever
  treated as a forecast;
* a player who did not play is a separate state, never a 0.0 error sample
  unless the caller asks for the host's scoring rule explicitly.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.waivers.streaming_backtest import (
    DecisionContext,
    DynastyLookup,
    SeasonData,
    available_pool,
    build_decision_context,
)

__all__ = [
    "PRE_KICKOFF",
    "POST_KICKOFF",
    "UNSTAMPED",
    "ProjectionErrorRow",
    "archive_snapshot_audit",
    "candidate_universe",
    "classify_projection_timestamp",
    "decision_context_for",
    "error_summary",
    "projection_error_rows",
]

PRE_KICKOFF = "pre_kickoff"
POST_KICKOFF = "post_kickoff"
UNSTAMPED = "unstamped"


def candidate_universe(
    data: SeasonData, roster_id: int, week: int, idp_roster: Iterable[str], *, masked: bool = True
) -> frozenset[str]:
    """Defenders a team could have added at week ``week``'s cutoff."""
    return available_pool(data, roster_id, week, idp_roster, masked=masked)


def decision_context_for(
    data: SeasonData,
    roster_id: int,
    week: int,
    idp_roster: Iterable[str],
    *,
    masked: bool = True,
    max_swaps: int = 3,
    dynasty_lookup: DynastyLookup | None = None,
    dynasty_value_source: str | None = None,
    team_index: int = 0,
) -> DecisionContext:
    """The full point-in-time decision input (realized weeks < w only, week-w
    projection, value known before the cutoff) for one team-week."""
    roster = frozenset(idp_roster)
    return build_decision_context(
        data,
        week=week,
        team_index=team_index,
        idp_roster=roster,
        pool=candidate_universe(data, roster_id, week, roster, masked=masked),
        max_swaps=max_swaps,
        dynasty_lookup=dynasty_lookup,
        dynasty_value_source=dynasty_value_source,
        pool_dynasty_values=dynasty_lookup is not None,
    )


def classify_projection_timestamp(stamp: str | datetime | None, cutoff: datetime) -> str:
    """``pre_kickoff`` / ``post_kickoff`` / ``unstamped`` for one row or capture."""
    if stamp is None or stamp == "":
        return UNSTAMPED
    try:
        at = stamp if isinstance(stamp, datetime) else datetime.fromisoformat(str(stamp))
    except ValueError:
        return UNSTAMPED
    if at.tzinfo is None:
        return UNSTAMPED  # a naive stamp proves nothing about the instant
    return PRE_KICKOFF if at < cutoff else POST_KICKOFF


def archive_snapshot_audit(
    season: int,
    weeks: Sequence[int],
    cutoffs: Mapping[int, datetime],
    *,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Per week: immutable archive captures (``src.ros.weekly_projection_archive``)
    by source, split by fetch time against the week's first kickoff.  Only a
    ``pre_kickoff`` capture may be read as a historical forecast."""
    from src.ros import weekly_projection_archive as arch  # noqa: PLC0415

    root = base_dir or arch.ARCHIVE_ROOT
    out: dict[str, Any] = {"archiveRoot": str(root), "present": Path(root).is_dir(), "weeks": {}}
    for w in weeks:
        cell: dict[str, dict[str, int]] = {}
        for cap in arch.list_captures(season, w, base_dir=base_dir):
            label = (
                classify_projection_timestamp(cap.fetched_at, cutoffs[w])
                if cap.readable and w in cutoffs
                else UNSTAMPED
            )
            by = cell.setdefault(cap.source_key, {PRE_KICKOFF: 0, POST_KICKOFF: 0, UNSTAMPED: 0})
            by[label] += 1
        out["weeks"][str(w)] = cell
    return out


@dataclass(frozen=True)
class ProjectionErrorRow:
    week: int
    player_id: str
    group: str
    projected: float
    realized: float | None  # None = did not play (a separate state)
    timestamp_class: str
    rookie: bool | None
    after_bye: bool | None
    first_appearance: bool
    late_inactive: bool


def projection_error_rows(
    data: SeasonData, players_dump: Mapping[str, Any] | None = None
) -> list[ProjectionErrorRow]:
    """One row per projected defender-week.  Subgroup flags:

    * ``rookie`` -- ``years_exp == 0`` in the (today's) player dump; ``None``
      when the dump does not say;
    * ``after_bye`` -- the player's (today's) team had no player with a stat
      line in week ``w - 1``; ``None`` when the team is unknown or ``w`` is the
      first loaded week (a mid-season trade makes this an approximation);
    * ``first_appearance`` -- no stat line in any earlier loaded week (a proxy
      for an emerging rookie / new starter);
    * ``late_inactive`` -- projected above 0 but recorded no stat line.
    """
    dump = players_dump or {}
    team_of = {pid: (dump.get(pid) or {}).get("team") for pid in data.players}
    teams_played: dict[int, set[str]] = {}
    for w in data.weeks:
        teams_played[w] = {t for pid in data.played.get(w, ()) if (t := team_of.get(pid))}
    seen: set[str] = set()
    rows: list[ProjectionErrorRow] = []
    for w in sorted(data.weeks):
        cutoff = data.cutoffs.get(w)
        played = data.played.get(w, frozenset())
        for pid, proj in sorted(data.projections.get(w, {}).items()):
            info = data.players.get(pid)
            if not info or not info.group:
                continue
            exp = (dump.get(pid) or {}).get("years_exp")
            team = team_of.get(pid)
            prev = w - 1
            rows.append(
                ProjectionErrorRow(
                    week=w,
                    player_id=pid,
                    group=info.group,
                    projected=float(proj.points),
                    realized=data.realized(w, pid) if pid in played else None,
                    timestamp_class=(
                        classify_projection_timestamp(proj.provider_updated_at, cutoff)
                        if cutoff
                        else UNSTAMPED
                    ),
                    rookie=(exp == 0) if isinstance(exp, int) else None,
                    after_bye=(
                        (team not in teams_played[prev])
                        if team and prev in teams_played and teams_played[prev]
                        else None
                    ),
                    first_appearance=pid in played and pid not in seen,
                    late_inactive=pid not in played and proj.points > 0,
                )
            )
        seen |= set(played)
    return rows


def error_summary(errors: Sequence[float]) -> dict[str, Any]:
    """MAE / RMSE / bias (projected minus realized) for one cell."""
    n = len(errors)
    if not n:
        return {"n": 0, "mae": None, "rmse": None, "bias": None}
    return {
        "n": n,
        "mae": statistics.fmean(abs(e) for e in errors),
        "rmse": statistics.fmean(e * e for e in errors) ** 0.5,
        "bias": statistics.fmean(errors),
    }
