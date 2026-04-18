"""Parse a Sleeper league's roster_positions into lineup demand.

The calibration lab uses this to compute effective replacement ranks
for every fantasy-scoring position (QB / RB / WR / TE / DL / LB / DB)
and to report an offense-vs-IDP demand summary so the reviewer can
see how much of the league's starting XI is defense.

The offense side is needed by the cross-family calibration layer:
without offense VOR we can't compare "IDP as a class vs offense as a
class" and the lab can only emit within-position shape signals.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

# Sleeper slot tokens we recognise. Anything else lands in "other".
OFFENSE_SLOTS = {"QB", "RB", "WR", "TE", "FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"}
OFFENSE_DIRECT_SLOTS = {"QB", "RB", "WR", "TE"}
# Plain FLEX is RB/WR/TE eligible (1/3 demand to each).
OFFENSE_FLEX_SLOTS = {"FLEX"}
# WRRB_FLEX is RB/WR only — TE is NOT eligible. Demand splits 50/50
# between RB and WR.
WRRB_FLEX_SLOTS = {"WRRB_FLEX", "RB_WR_FLEX", "RBWR_FLEX"}
# REC_FLEX is WR/TE only — RB is NOT eligible. Demand splits 50/50
# between WR and TE.
REC_FLEX_SLOTS = {"REC_FLEX", "WR_TE_FLEX", "WRTE_FLEX"}
# SUPER_FLEX adds QB to the RB/WR/TE pool — 25% demand to each.
SUPER_FLEX_SLOTS = {"SUPER_FLEX", "QB_RB_WR_TE"}
IDP_DIRECT_SLOTS = {"DL", "LB", "DB"}
IDP_FLEX_SLOTS = {"IDP_FLEX", "DB_LB", "DL_LB", "DL_DB", "DEF_FLEX", "IDP"}
BENCH_SLOTS = {"BN", "BENCH", "IR", "TAXI"}
SKIP_SLOTS = {"K", "DEF", "P"}

OFFENSE_FAMILY: tuple[str, ...] = ("QB", "RB", "WR", "TE")
IDP_FAMILY: tuple[str, ...] = ("DL", "LB", "DB")


@dataclass
class LineupDemand:
    league_id: str
    season: int | None
    team_count: int
    starter_slots: dict[str, int] = field(default_factory=dict)
    # IDP starter slot counts
    dl_starters: int = 0
    lb_starters: int = 0
    db_starters: int = 0
    idp_flex_starters: int = 0
    # Offense starter slot counts (split out for cross-family math)
    qb_starters: int = 0
    rb_starters: int = 0
    wr_starters: int = 0
    te_starters: int = 0
    offense_flex_starters: int = 0   # plain FLEX — RB/WR/TE eligible
    wrrb_flex_starters: int = 0      # RB/WR only — no TE
    rec_flex_starters: int = 0       # WR/TE only — no RB
    super_flex_starters: int = 0     # adds QB to the flex pool
    offense_starters: int = 0        # Aggregate — kept for backward compat
    bench_slots: int = 0

    # ── IDP demand (per-team fractional) ──
    @property
    def total_dl_demand(self) -> float:
        return float(self.dl_starters) + self.idp_flex_starters / 3.0

    @property
    def total_lb_demand(self) -> float:
        return float(self.lb_starters) + self.idp_flex_starters / 3.0

    @property
    def total_db_demand(self) -> float:
        return float(self.db_starters) + self.idp_flex_starters / 3.0

    # ── Offense demand (per-team fractional) ──
    # Each flex variant only contributes to the positions actually
    # eligible inside it:
    #   * Plain FLEX — RB/WR/TE eligible (1/3 each).
    #   * WRRB_FLEX — RB/WR only (1/2 each, NO TE).
    #   * REC_FLEX  — WR/TE only (1/2 each, NO RB).
    #   * SUPER_FLEX — QB/RB/WR/TE eligible (1/4 each).
    # Modelling restricted flexes as generic 3-way flex would distort
    # offense replacement ranks (and thus the offense VOR denominator
    # in family_scale).
    @property
    def total_qb_demand(self) -> float:
        return float(self.qb_starters) + self.super_flex_starters * 0.25

    @property
    def total_rb_demand(self) -> float:
        return (
            float(self.rb_starters)
            + self.offense_flex_starters / 3.0
            + self.wrrb_flex_starters / 2.0
            + self.super_flex_starters * 0.25
        )

    @property
    def total_wr_demand(self) -> float:
        return (
            float(self.wr_starters)
            + self.offense_flex_starters / 3.0
            + self.wrrb_flex_starters / 2.0
            + self.rec_flex_starters / 2.0
            + self.super_flex_starters * 0.25
        )

    @property
    def total_te_demand(self) -> float:
        return (
            float(self.te_starters)
            + self.offense_flex_starters / 3.0
            + self.rec_flex_starters / 2.0
            + self.super_flex_starters * 0.25
        )

    def replacement_rank(
        self, position: str, mode: str, buffer_pct: float, manual: int | None
    ) -> int:
        """Return the rank index just past the last startable player.

        * ``strict_starter``: team_count * positional demand, rounded up.
        * ``starter_plus_buffer``: adds ``ceil(team_count * buffer_pct)``
          to account for bye-week and injury depth.
        * ``manual``: uses ``manual`` directly, coerced to ``>= 1``.

        Handles both IDP positions (DL/LB/DB) and offense positions
        (QB/RB/WR/TE) — the cross-family calibration layer needs the
        same replacement-rank machinery for both sides.
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
            "QB": self.total_qb_demand,
            "RB": self.total_rb_demand,
            "WR": self.total_wr_demand,
            "TE": self.total_te_demand,
        }
        demand = demand_lookup.get(position.upper(), 0.0)
        base = int(math.ceil(self.team_count * demand))
        base = max(base, 1)
        if mode == "strict_starter":
            return base
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
            "qb_starters": self.qb_starters,
            "rb_starters": self.rb_starters,
            "wr_starters": self.wr_starters,
            "te_starters": self.te_starters,
            "offense_flex_starters": self.offense_flex_starters,
            "wrrb_flex_starters": self.wrrb_flex_starters,
            "rec_flex_starters": self.rec_flex_starters,
            "super_flex_starters": self.super_flex_starters,
            "offense_starters": self.offense_starters,
            "bench_slots": self.bench_slots,
            "total_dl_demand": self.total_dl_demand,
            "total_lb_demand": self.total_lb_demand,
            "total_db_demand": self.total_db_demand,
            "total_qb_demand": self.total_qb_demand,
            "total_rb_demand": self.total_rb_demand,
            "total_wr_demand": self.total_wr_demand,
            "total_te_demand": self.total_te_demand,
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
    dl = lb = db = idp_flex = 0
    qb = rb = wr = te = 0
    plain_flex = wrrb_flex = rec_flex = super_flex = 0
    offense_total = 0
    bench = 0
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
            idp_flex += 1
        elif slot == "QB":
            qb += 1
            offense_total += 1
        elif slot == "RB":
            rb += 1
            offense_total += 1
        elif slot == "WR":
            wr += 1
            offense_total += 1
        elif slot == "TE":
            te += 1
            offense_total += 1
        elif slot in SUPER_FLEX_SLOTS:
            super_flex += 1
            offense_total += 1
        elif slot in WRRB_FLEX_SLOTS:
            wrrb_flex += 1
            offense_total += 1
        elif slot in REC_FLEX_SLOTS:
            rec_flex += 1
            offense_total += 1
        elif slot in OFFENSE_FLEX_SLOTS:
            plain_flex += 1
            offense_total += 1
        elif slot in OFFENSE_SLOTS:
            offense_total += 1
    return LineupDemand(
        league_id=str(league.get("league_id") or ""),
        season=season,
        team_count=team_count,
        starter_slots=counts,
        dl_starters=dl,
        lb_starters=lb,
        db_starters=db,
        idp_flex_starters=idp_flex,
        qb_starters=qb,
        rb_starters=rb,
        wr_starters=wr,
        te_starters=te,
        offense_flex_starters=plain_flex,
        wrrb_flex_starters=wrrb_flex,
        rec_flex_starters=rec_flex,
        super_flex_starters=super_flex,
        offense_starters=offense_total,
        bench_slots=bench,
    )
