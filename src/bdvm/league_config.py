"""BDVM league configuration contract.

One frozen object describing everything format-dependent: team count,
fixed lineup slots by group, flex slots with eligibility, waiver
buffers, position→group mapping, and the league's *exact* Sleeper
``scoring_settings`` dict.

Ground truth (per the Phase-0 audit): the live contract's ``sleeper``
block carries ``rosterPositions`` (the real slot list from Sleeper) and
``scoringSettings`` (the real 141-key scoring dict).  The registry's
``rosterSettings`` is advisory and known to drift, so it is only the
fallback.  ``config_hash`` stamps every valuation with the exact config
that produced it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.ros import lineup as lineup_owner

# Sleeper roster_positions vocabulary → (fixed group | flex definition).
# BN / TAXI / IR are bench-type slots and never start.
_FIXED_SLOTS = {"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB", "DEF"}
# Derived from the canonical owner (C2-U1) rather than restated — this
# was a second slot-eligibility table, and a second table is a second
# owner even while it agrees.  The KEYS name which slots this module
# treats as flex; the VALUES come from ``src/ros/lineup.py``.
_FLEX_SLOTS: dict[str, tuple[str, ...]] = {
    slot: lineup_owner.ordered_positions(lineup_owner.slot_eligible_positions(slot))
    for slot in ("FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX", "IDP_FLEX")
}
_BENCH_SLOTS = {"BN", "TAXI", "IR"}

# True football position → default platform lineup group.
DEFAULT_POS_GROUPS: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "DT": "DL",
    "EDGE": "DL",
    "DE": "DL",
    "DL": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
    "DB": "DB",
}


class LeagueConfigError(ValueError):
    """Raised when a league config cannot be constructed coherently."""


@dataclass(frozen=True)
class BdvmLeagueConfig:
    league_key: str
    teams: int
    # Fixed starting slots per lineup group, e.g. {"QB": 1, "RB": 2, ...}
    starters: Mapping[str, int]
    # Ordered flex slots: name -> (count_per_team, eligible groups)
    flex: Mapping[str, tuple[int, tuple[str, ...]]]
    # startable-quality players per team rostered beyond startable count
    waiver_buffer: Mapping[str, float]
    default_buffer: float
    # true position -> lineup group (configurable: DT-required, CB/S-split…)
    pos_groups: Mapping[str, str]
    scoring_settings: Mapping[str, float]
    roster_size: int = 0
    taxi_size: int = 0
    best_ball: bool = False
    idp_enabled: bool = True
    scoring_profile: str = ""
    source: str = ""  # "sleeper_block" | "registry" | "explicit"
    config_hash: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        if self.teams <= 1:
            raise LeagueConfigError(f"teams must be >= 2, got {self.teams}")
        for grp, n in self.starters.items():
            if n < 0:
                raise LeagueConfigError(f"negative starter count for {grp}")
        for name, (count, elig) in self.flex.items():
            if count < 0 or not elig:
                raise LeagueConfigError(f"malformed flex slot {name!r}")
        if not self.config_hash:
            object.__setattr__(self, "config_hash", self._compute_hash())

    def _compute_hash(self) -> str:
        blob = json.dumps(
            {
                "leagueKey": self.league_key,
                "teams": self.teams,
                "starters": dict(self.starters),
                "flex": {k: [c, list(e)] for k, (c, e) in self.flex.items()},
                "waiverBuffer": dict(self.waiver_buffer),
                "defaultBuffer": self.default_buffer,
                "posGroups": dict(self.pos_groups),
                "scoring": dict(self.scoring_settings),
                "rosterSize": self.roster_size,
                "bestBall": self.best_ball,
                "idpEnabled": self.idp_enabled,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:12]

    # ------------------------------------------------------------------
    def group(self, pos: str) -> str:
        p = (pos or "").upper()
        grp = self.pos_groups.get(p)
        if grp is None:
            raise LeagueConfigError(f"position {pos!r} has no lineup group in this config")
        return grp

    @property
    def superflex(self) -> bool:
        return any("QB" in elig for _, elig in self.flex.values())

    @property
    def te_premium(self) -> bool:
        return float(self.scoring_settings.get("bonus_rec_te", 0) or 0) > 0

    def startable_groups(self) -> list[str]:
        groups = set(self.starters)
        for _, elig in self.flex.values():
            groups.update(elig)
        return sorted(groups)

    def buffer_for(self, group: str) -> float:
        return float(self.waiver_buffer.get(group, self.default_buffer))

    def to_meta(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "teams": self.teams,
            "configHash": self.config_hash,
            "configSource": self.source,
            "superflex": self.superflex,
            "tePremium": self.te_premium,
            "idpEnabled": self.idp_enabled,
            "bestBall": self.best_ball,
            "starters": dict(self.starters),
            "flex": {k: {"count": c, "eligible": list(e)} for k, (c, e) in self.flex.items()},
        }


def _parse_roster_positions(
    roster_positions: list[str],
) -> tuple[dict[str, int], dict[str, tuple[int, tuple[str, ...]]]]:
    starters: dict[str, int] = {}
    flex: dict[str, tuple[int, tuple[str, ...]]] = {}
    for raw in roster_positions:
        slot = str(raw or "").upper()
        if not slot or slot in _BENCH_SLOTS:
            continue
        if slot in _FIXED_SLOTS:
            starters[slot] = starters.get(slot, 0) + 1
        elif slot in _FLEX_SLOTS:
            count, elig = flex.get(slot, (0, _FLEX_SLOTS[slot]))
            flex[slot] = (count + 1, elig)
        # Unknown slot labels are skipped deliberately: failing the whole
        # config on a vendor slot we don't model (e.g. "DST2") would take
        # valuations down for slots that carry no player value anyway.
    return starters, flex


def from_contract(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    registry_roster_settings: Mapping[str, Any] | None = None,
    idp_enabled: bool = True,
    best_ball: bool = False,
    scoring_profile: str = "",
    waiver_buffer: Mapping[str, float] | None = None,
    default_buffer: float = 0.5,
    pos_groups: Mapping[str, str] | None = None,
) -> BdvmLeagueConfig:
    """Build the BDVM league config from the live contract's sleeper block,
    falling back to the registry's advisory ``rosterSettings``.

    Raises ``LeagueConfigError`` when neither source can produce a lineup
    (fail loudly — a wrong lineup silently corrupts every value).
    """
    sleeper = contract.get("sleeper") or {}
    scoring = sleeper.get("scoringSettings") or {}
    roster_positions = sleeper.get("rosterPositions") or []
    league_settings = sleeper.get("leagueSettings") or {}

    starters: dict[str, int] = {}
    flex: dict[str, tuple[int, tuple[str, ...]]] = {}
    source = ""
    teams = 0
    roster_size = 0
    taxi_size = 0

    if roster_positions and scoring:
        starters, flex = _parse_roster_positions(list(roster_positions))
        teams = int(league_settings.get("num_teams") or 0)
        roster_size = len(roster_positions)
        taxi_size = int(league_settings.get("taxi_slots") or 0)
        best_ball = bool(league_settings.get("best_ball") or best_ball)
        source = "sleeper_block"

    if not starters and registry_roster_settings:
        rs = registry_roster_settings
        raw_starters = dict(rs.get("starters") or {})
        flex_map = {
            "FLEX": tuple(rs.get("flexEligible") or _FLEX_SLOTS["FLEX"]),
            "SFLEX": tuple(rs.get("sflexEligible") or _FLEX_SLOTS["SUPER_FLEX"]),
            # dynasty_new's host runs a WR/RB-only second flex (W18-F011).
            # Without this branch a registry ``WRRB_FLEX`` starter key fell
            # through to the fixed-slot bucket — a "position" no player maps
            # to — instead of a flex slot with its declared eligibility.
            "WRRB_FLEX": tuple(rs.get("wrrbFlexEligible") or _FLEX_SLOTS["WRRB_FLEX"]),
            "IDP_FLEX": tuple(rs.get("idpFlexEligible") or _FLEX_SLOTS["IDP_FLEX"]),
        }
        for slot, count in raw_starters.items():
            slot_u = str(slot).upper()
            n = int(count or 0)
            if n <= 0:
                continue
            if slot_u in ("FLEX", "SFLEX", "WRRB_FLEX", "IDP_FLEX"):
                canonical = "SUPER_FLEX" if slot_u == "SFLEX" else slot_u
                flex[canonical] = (n, tuple(g.upper() for g in flex_map[slot_u]))
            else:
                starters[slot_u] = n
        teams = int(rs.get("teamCount") or 0)
        roster_size = int(rs.get("rosterSize") or 0)
        taxi_size = int(rs.get("taxiSize") or 0)
        source = "registry"

    if not starters:
        raise LeagueConfigError(
            f"cannot build league config for {league_key!r}: no sleeper "
            "rosterPositions/scoringSettings on the contract and no registry "
            "rosterSettings fallback"
        )
    if teams <= 1:
        raise LeagueConfigError(f"cannot determine team count for {league_key!r}")
    if not scoring:
        raise LeagueConfigError(
            f"no scoringSettings available for {league_key!r}; BDVM requires "
            "exact league scoring (registry has none by design)"
        )

    if not idp_enabled:
        starters = {g: n for g, n in starters.items() if g not in ("DL", "LB", "DB")}
        flex = {k: v for k, v in flex.items() if k != "IDP_FLEX"}

    return BdvmLeagueConfig(
        league_key=league_key,
        teams=teams,
        starters=starters,
        flex=flex,
        waiver_buffer=dict(waiver_buffer or {}),
        default_buffer=default_buffer,
        pos_groups=dict(pos_groups or DEFAULT_POS_GROUPS),
        scoring_settings={str(k): float(v) for k, v in scoring.items() if _is_num(v)},
        roster_size=roster_size,
        taxi_size=taxi_size,
        best_ball=best_ball,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        source=source,
    )


def _is_num(v: Any) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
