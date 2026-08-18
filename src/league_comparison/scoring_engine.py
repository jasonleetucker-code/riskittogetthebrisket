"""Apply a Sleeper ``scoring_settings`` dict to weekly NFL stat rows
and aggregate to per-player season totals.

This module is a thin orchestrator around the existing
:func:`src.nfl_data.realized_points.compute_weekly_points` — which is
already the single source of truth for Sleeper-format fantasy scoring.

Output: a list of :class:`PlayerSeasonScore` records, one per
``(player_id_gsis, position, season)`` triple, that downstream metrics
code can sort/filter/sample.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from src.nfl_data import pbp_weekly as _pbp_weekly
from src.nfl_data import realized_points as _rp
from src.utils.name_clean import POSITION_ALIASES

_LOGGER = logging.getLogger(__name__)


# Positions we report on (offense + IDP).  Anything else (kickers,
# team defenses, OL/HC/etc) is dropped — out of scope for a positional
# scoring-balance comparison.
_OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
_IDP_POSITIONS = frozenset({"DL", "LB", "DB"})
_TRACKED_POSITIONS = _OFFENSE_POSITIONS | _IDP_POSITIONS


# ── Blended score (volume + pace) ─────────────────────────────────────
#
# Every player's season is reduced to one number that mixes total
# fantasy points (volume — what they actually scored) with their
# per-game pace extrapolated to a 17-week season (pace — what they'd
# have done at full availability).  The blend rewards a player who
# missed a few weeks at an elite pace without erasing the volume signal
# that a workhorse 17-game starter brings.
#
# Formula: ``0.5 * total + 0.5 * (ppg * 17)`` when games_played >=
# ``MIN_GAMES_FOR_PPG``; otherwise total only.  The min-games gate
# prevents a 1-game outlier from dominating PPG.
#
# At games_played == 17 the two halves agree exactly: ppg*17 == total,
# so blended == total.  Tests that construct full-season fixtures
# don't need to know about the blend — they get back the same numbers.

#: Minimum games required for the PPG component to count.  Below this
#: the blended score equals total points, so a 2-game elite outlier
#: doesn't get extrapolated to a full-season equivalent.
MIN_GAMES_FOR_PPG: int = 8

#: Number of weeks we extrapolate per-game pace across.  Matches the
#: regular-season window from :mod:`historical_stats`.
FULL_SEASON_WEEKS: int = 17

#: Weight on total points vs ppg-extrapolated.  0.5/0.5 keeps both
#: signals equally important; tweaking this is a simple knob if the
#: balance ever needs to lean one way.
_TOTAL_WEIGHT: float = 0.5
_PACE_WEIGHT: float = 0.5


def compute_blended_score(total_points: float, games_played: int) -> float:
    """Mix total fantasy points and per-game pace into one number.

    See module docstring for the rationale.  Pure function — exposed at
    module scope so tests can pin the formula independent of any
    PlayerSeasonScore instance.
    """
    if games_played >= MIN_GAMES_FOR_PPG and games_played > 0:
        ppg = float(total_points) / float(games_played)
        extrapolated = ppg * FULL_SEASON_WEEKS
        return _TOTAL_WEIGHT * float(total_points) + _PACE_WEIGHT * extrapolated
    return float(total_points)


@dataclass(frozen=True)
class PlayerSeasonScore:
    player_id: str
    player_name: str
    position: str  # canonicalised: QB / RB / WR / TE / DL / LB / DB
    raw_position: str  # what nflverse reported (DT, EDGE, OLB, etc.)
    season: int
    total_points: float
    games_played: int

    unscored: tuple[tuple[str, float], ...] = ()
    """Configured NONZERO rules no source supplied for this season.

    Non-empty means :attr:`total_points` is a LOWER BOUND. Carried rather
    than dropped because a season total that silently omits a rule the
    league pays reads exactly like a season total that does not — which
    is the whole failure this engine's realized-points source exists to
    close, and dropping it here would reintroduce it one layer up.
    """

    @property
    def blended_score(self) -> float:
        """The volume+pace composite used for ranking and metrics."""
        return compute_blended_score(self.total_points, self.games_played)

    @property
    def points_per_game(self) -> float:
        """Per-game pace; 0.0 if no games (avoids div-by-zero)."""
        if not self.games_played:
            return 0.0
        return float(self.total_points) / float(self.games_played)


def _canonical_position(raw_pos: str | None) -> str | None:
    """Map a raw nflverse position to one of our tracked groups, or None.

    Uses ``POSITION_ALIASES`` from ``src.utils.name_clean`` for the
    standard offense aliases, and an explicit IDP collapse table since
    nflverse uses fine-grained labels (DT/DE/EDGE → DL, ILB/OLB/MLB →
    LB, CB/S/FS/SS → DB).
    """
    if not raw_pos:
        return None
    raw = str(raw_pos).strip().upper()
    if not raw:
        return None
    aliased = POSITION_ALIASES.get(raw, raw)
    if aliased in _OFFENSE_POSITIONS:
        return aliased
    # IDP collapse — keep this local to scoring_engine; not all callers
    # of POSITION_ALIASES want this collapse.
    if aliased in {"DL", "DT", "DE", "EDGE", "NT"}:
        return "DL"
    if aliased in {"LB", "ILB", "OLB", "MLB"}:
        return "LB"
    # ``SAF`` is nflverse's own spelling for a safety and appears on
    # 1,441 of the 11,540 persisted 2025 IDP player-weeks — the third
    # largest defensive group after LB and CB.  It was in neither
    # POSITION_ALIASES nor this table, so every safety was dropped from
    # every scoring comparison, silently: the only trace was a
    # ``unknown_positions_dropped`` warning listing it beside genuinely
    # untracked positions like K, P and OL.
    if aliased in {"DB", "CB", "S", "SAF", "FS", "SS"}:
        return "DB"
    return None


def compute_player_season_scores(
    rows: Iterable[dict[str, Any]],
    scoring_settings: dict[str, Any],
    *,
    season: int | None = None,
    pbp_for_season: Callable[[int], Any] | None = None,
) -> list[PlayerSeasonScore]:
    """Aggregate weekly rows to season totals under one league's scoring.

    ``rows`` is the output of ``fetch_weekly_stats`` — already a list of
    plain dicts.  ``scoring_settings`` is the Sleeper dict from
    ``LeagueScoringInfo.scoring_settings``.

    ``season`` is informational; if None we infer it from the rows.

    ``pbp_for_season`` resolves the play-by-play supplement — see
    :class:`src.nfl_data.pbp_weekly.SeasonPbpIndex`.  It is what makes the
    six reception bands and the player special-teams rules count here;
    without it they score nothing, and this function's whole purpose is
    comparing two cards, so a rule that is silently missing from BOTH
    sides still moves the comparison whenever the two price it
    differently.  Host-native rows never take a supplement (the host
    publishes these keys itself) and are skipped.
    """
    if not scoring_settings:
        return []

    # Group by (player_id, season) so a multi-team year stays unified
    # (player traded mid-season — rows from both teams roll into one
    # season total).
    bucket: dict[tuple[str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "name": "",
            "raw_position": "",
            "canonical": None,
            "total": 0.0,
            "games": 0,
            "unscored": {},
        }
    )

    unknown_positions: set[str] = set()

    for row in rows or []:
        pid = str(row.get("player_id") or row.get("player_id_gsis") or "").strip()
        if not pid:
            continue
        raw_pos = str(row.get("position") or "").strip().upper()
        canonical = _canonical_position(raw_pos)
        if canonical not in _TRACKED_POSITIONS:
            if raw_pos:
                unknown_positions.add(raw_pos)
            continue
        try:
            row_season = int(row.get("season") or season or 0)
        except (TypeError, ValueError):
            continue
        if row_season <= 0:
            continue

        # The row says which vocabulary it is written in (#802).  Rows from
        # nflverse are normalized; rows the LEAGUE HOST produced are already
        # in the scoring card's own vocabulary and are scored as-is, so no
        # rule is lost to a rename that has no target.  Absent stamp →
        # nflverse, which is every pre-existing producer.
        row_source = str(row.get("source") or "nflverse")
        if pbp_for_season is not None and row_source == "nflverse":
            row = _pbp_weekly.attach_supplement(row, pbp_for_season(row_season))
        rp = _rp.compute_weekly_points(
            row,
            scoring_settings,
            position=canonical,
            source=row_source,
        )
        if rp is None:
            continue
        pts = float(rp.fantasy_points)

        key = (pid, row_season)
        b = bucket[key]
        if not b["name"]:
            b["name"] = str(row.get("player_display_name") or row.get("player_name") or pid)
        if not b["raw_position"]:
            b["raw_position"] = raw_pos
        b["canonical"] = canonical
        b["total"] += pts
        # Union across weeks: one week that could not supply a rule makes
        # the season total a lower bound.
        for key, rate in rp.unscored:
            b["unscored"][key] = rate
        # Count any game where the player had a stat row, regardless
        # of whether they scored — matches the "games played" intuition
        # for sample sizes.
        b["games"] += 1

    out: list[PlayerSeasonScore] = []
    for (pid, yr), b in bucket.items():
        if b["canonical"] is None:
            continue
        out.append(
            PlayerSeasonScore(
                player_id=pid,
                player_name=b["name"],
                position=b["canonical"],
                raw_position=b["raw_position"],
                season=yr,
                total_points=round(float(b["total"]), 2),
                games_played=int(b["games"]),
                unscored=tuple(sorted(b["unscored"].items())),
            )
        )

    if unknown_positions:
        _LOGGER.warning(
            "scoring_engine.unknown_positions_dropped season=%s positions=%s",
            season,
            sorted(unknown_positions),
        )

    return out
