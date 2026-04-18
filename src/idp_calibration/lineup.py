"""Parse a Sleeper league's roster_positions into lineup demand.

The calibration lab uses this to compute effective replacement ranks
for DL/LB/DB and to report an offense-vs-IDP demand summary so the
reviewer can see how much of the league's starting XI is defense.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

# Sleeper slot tokens we recognise. Anything else lands in "other".
OFFENSE_SLOTS = {"QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"}
IDP_DIRECT_SLOTS = {"DL", "LB", "DB"}
IDP_FLEX_SLOTS = {"IDP_FLEX", "DB_LB", "DL_LB", "DL_DB", "DEF_FLEX", "IDP"}
BENCH_SLOTS = {"BN", "BENCH", "IR", "TAXI"}
SKIP_SLOTS = {"K", "DEF", "P"}


@dataclass
class LineupDemand:
    league_id: str
    season: int | None
    team_count: int
    starter_slots: dict[str, int] = field(default_factory=dict)
    dl_starters: int = 0
    lb_starters: int = 0
    db_starters: int = 0
    idp_flex_starters: int = 0
    offense_starters: int = 0
    bench_slots: int = 0

    @property
    def total_dl_demand(self) -> float:
        return float(self.dl_starters) + self.idp_flex_starters / 3.0

    @property
    def total_lb_demand(self) -> float:
        return float(self.lb_starters) + self.idp_flex_starters / 3.0

    @property
    def total_db_demand(self) -> float:
        return float(self.db_starters) + self.idp_flex_starters / 3.0

    def replacement_rank(self, position: str, mode: str, buffer_pct: float, manual: int | None) -> int:
        """Return the rank index just past the last startable player.

        * ``strict_starter``: team_count * positional demand, rounded up.
        * ``starter_plus_buffer``: adds ``ceil(team_count * buffer_pct)``
          to account for bye-week and injury depth.
        * ``manual``: uses ``manual`` directly, coerced to ``>= 1``.
        """
        if mode == "manual" and manual is not None:
            try:
                return max(1, int(manual))
            except (TypeError, ValueError):
                pass

        demand_lookup = {
            "DL": self.total_dl_demand,
            "LB": self.total_lb_demand,
            "DB": self.total_db_demand,
        }
        demand = demand_lookup.get(position.upper(), 0.0)
        # Ceiling, not round — a fractional IDP-flex demand like 13.33 must
        # produce 14 so the replacement player sits *past* every possible
        # starter slot. Rounding down would understate the starter pool and
        # inflate VOR (and downstream multipliers) in leagues where
        # team_count * demand isn't integer.
        base = int(math.ceil(self.team_count * demand))
        base = max(base, 1)
        if mode == "strict_starter":
            return base
        # starter_plus_buffer (default) — buffer also ceils for symmetry.
        buf = max(1, int(math.ceil(self.team_count * max(0.0, buffer_pct))))
        return base + buf

    def to_dict(self) -> dict[str, Any]:
        return {
            "league_id": self.league_id,
            "season": self.season,
            "team_count": self.team_count,
            "starter_slots": dict(self.starter_slots),
            "dl_starters": self.dl_starters,
            "lb_starters": self.lb_starters,
            "db_starters": self.db_starters,
            "idp_flex_starters": self.idp_flex_starters,
            "offense_starters": self.offense_starters,
            "bench_slots": self.bench_slots,
            "total_dl_demand": self.total_dl_demand,
            "total_lb_demand": self.total_lb_demand,
            "total_db_demand": self.total_db_demand,
        }


def _count_teams(league: dict[str, Any]) -> int:
    for key in ("total_rosters", "num_teams", "team_count"):
        value = league.get(key)
        try:
            iv = int(value)
            if iv > 0:
                return iv
        except (TypeError, ValueError):
            continue
    return 12  # Sleeper default; reported via warnings if we fall back.


def parse_lineup(league: dict[str, Any] | None) -> LineupDemand:
    if not isinstance(league, dict):
        return LineupDemand(league_id="", season=None, team_count=0)
    team_count = _count_teams(league)
    season = None
    try:
        season = int(str(league.get("season") or "").strip())
    except (TypeError, ValueError):
        season = None

    slots: Iterable[str] = league.get("roster_positions") or []
    counts: dict[str, int] = {}
    dl = lb = db = flex = offense = bench = 0
    for raw in slots:
        slot = str(raw or "").strip().upper()
        if not slot:
            continue
        counts[slot] = counts.get(slot, 0) + 1
        if slot in BENCH_SLOTS:
            bench += 1
            continue
        if slot in SKIP_SLOTS:
            continue
        if slot == "DL":
            dl += 1
        elif slot == "LB":
            lb += 1
        elif slot == "DB":
            db += 1
        elif slot in IDP_FLEX_SLOTS:
            flex += 1
        elif slot in OFFENSE_SLOTS:
            offense += 1
    return LineupDemand(
        league_id=str(league.get("league_id") or ""),
        season=season,
        team_count=team_count,
        starter_slots=counts,
        dl_starters=dl,
        lb_starters=lb,
        db_starters=db,
        idp_flex_starters=flex,
        offense_starters=offense,
        bench_slots=bench,
    )
