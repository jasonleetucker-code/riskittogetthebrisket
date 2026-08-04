"""The FAAB recommendation engine — one centralized model.

This module is the ONLY place a FAAB dollar figure is derived.  Every
surface (the ``/waivers`` recommendation table, the manual add/drop
calculator, the ``/api/waiver/*`` endpoints) routes through
``recommend``; there is no second formula and no client-side port.

The design turns on one separation the previous implementation did not
make at all:

``objectiveCeiling``
    What the player is WORTH, as a share of the league's **original**
    full-season budget.  A function of the player and the league
    FORMAT.  It does not move when a manager spends, and it is the
    same number for every team in the league.

``recommendedBid``
    What THIS team should actually bid.  A function of the ceiling,
    the team's remaining balance, its roster and drop side, the point
    in the season, and — dominantly — the price the claim is expected
    to clear at.  Almost always far below the ceiling.

The old engine had neither: its "max" was just the team's remaining
balance, and its bid was ``0.05 + 0.25 x (value / best value on the
wire)`` of that balance, which made the best available free agent
worth 21% of the budget whether he graded 9999 or 900.

Model
─────

**Stage A — anchors** (``resolve_anchors``).  Two league-format-derived
reference values, recomputed per league per board refresh:

    V_allin  board value at rank (teamCount x startersPerTeam), the
             size of the league-wide STARTING pool.  A player at this
             line starts for every team in the league — the scarcity
             level at which committing the entire budget is rational.
    V_repl   what you can add for free instead: the format line at
             ``replacementSlotMultiple`` x starter slots, blended with
             the live pool's Nth-best unrostered player.

Neither hard-codes a player or a threshold, yet on the 2026-08-04
board they reproduce both human calibration anchors: the 10-team
league's starter line lands exactly on Josh Jacobs (3901), and the
12-team IDP league's line (2341) sits just under the peer's all-in
cluster (2661 / 2680 / 2938).

**Stage B — surplus** (``surplus_over_replacement``).  Value above
what is free: ``max(0, V - V_repl)``.  The drop side subtracts the
SAME way — ``max(0, V_drop - V_repl)`` — so dropping a below-
replacement player costs nothing and no factor is counted twice.

**Stage C — ceiling curve** (``objective_ceiling``).  A smootherstep
on ``s^toeExponent``, zero-slope at both ends so nothing jumps at a
threshold.  Saturates at 100% of the ORIGINAL budget at ``V_allin``.
An uncapped ``rawCeiling`` keeps growing above it so the market layer
can still distinguish a 2400 player from a 9999 player.

**Stage D — team layer** (``team_ceiling``).  Drop cost, positional
need, season option value (unspent FAAB expires worthless, so the
ceiling relaxes toward 100% late), competitive status, then a hard cap
at the team's remaining balance.

**Stage E — market** (``rival_bid_cdf`` / ``optimal_bid``).  Rival
bids are a zero-inflated lognormal, fitted against this league's real
Sleeper history where the median winning bid is $0 in every value band
and roughly half of all adds cost nothing.  The recommended bid
maximises expected surplus

    argmax_b  P(win | b) x (rawCeiling_team - b)

which is what produces "worth $100, bid $36" — bidding the ceiling
captures zero surplus by construction, so the optimum is always
strictly below it.

Every parameter lives in ``config/trade/faab.json``.  This module
contains no numeric literal that affects a recommendation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.utils.config_loader import load_json, repo_root

__all__ = [
    "current_nfl_week",
    "FaabConfig",
    "LeagueContext",
    "TeamContext",
    "RivalTeam",
    "PlayerInput",
    "Anchors",
    "load_faab_config",
    "resolve_anchors",
    "surplus_over_replacement",
    "objective_ceiling",
    "season_option_value",
    "recommend",
]


# ── Season clock ───────────────────────────────────────────────────


def current_nfl_week(today: date | None = None) -> tuple[int | None, bool]:
    """``(week, in_season)`` for the regular season, else ``(None, False)``.

    Week 1 opens on the Thursday after Labor Day (the first Monday in
    September), which has been the NFL's rule since 2002.  Weeks run
    Thursday-to-Wednesday so a Tuesday waiver run resolves under the
    week that just finished, which is how Sleeper numbers them.

    Outside the regular season this returns ``(None, False)`` and the
    engine applies its offseason option value rather than pretending a
    waiver clock is running.  The season here is the CALENDAR NFL
    season — never a draft year, which points a year ahead for the
    whole autumn and would put the season phase permanently in week 1.
    """
    d = today or datetime.now(timezone.utc).date()

    # Labor Day = first Monday in September of the relevant season.
    season_year = d.year if d.month >= 3 else d.year - 1
    sept = date(season_year, 9, 1)
    labor_day = sept + timedelta(days=(7 - sept.weekday()) % 7)
    kickoff = labor_day + timedelta(days=3)  # the Thursday after

    if d < kickoff:
        return None, False
    week = (d - kickoff).days // 7 + 1
    if week > 18:
        return None, False
    return int(week), True


# ── Config ─────────────────────────────────────────────────────────

_CONFIG_PATH = repo_root() / "config" / "trade" / "faab.json"
_CONFIG_CACHE: dict[str, Any] | None = None


def load_faab_config(path: Path | None = None, *, refresh: bool = False) -> dict[str, Any]:
    """Load ``config/trade/faab.json``.

    Cached per process (the file is static config, and the engine is
    called once per waiver row).  ``refresh=True`` re-reads it, which
    is what the calibration tests use when sweeping parameters.
    """
    global _CONFIG_CACHE
    if path is not None:
        return load_json(path, default={}) or {}
    if _CONFIG_CACHE is None or refresh:
        _CONFIG_CACHE = load_json(_CONFIG_PATH, default={}) or {}
    return _CONFIG_CACHE


class FaabConfig:
    """Thin typed accessor over the JSON config.

    Exists so the engine never reaches into raw dicts with string keys
    scattered through the math, and so a missing key resolves at the
    boundary instead of silently becoming ``None`` inside a formula.

    ``num`` SUBSTITUTES a caller-supplied default rather than raising.
    That is deliberate — a corrupt or partial ``faab.json`` degrades to
    documented behaviour instead of taking the waiver page down — but
    it means the in-code defaults are a second, silent source of truth.
    They are kept equal to the shipped config values, and
    ``tests/trade/test_faab_config_parity.py`` fails if they drift.
    """

    def __init__(self, raw: dict[str, Any] | None = None):
        self.raw = raw if raw is not None else load_faab_config()

    def section(self, name: str) -> dict[str, Any]:
        block = self.raw.get(name)
        return block if isinstance(block, dict) else {}

    def get(self, section: str, key: str, default: Any = None) -> Any:
        value = self.section(section).get(key)
        return default if value is None else value

    def num(self, section: str, key: str, default: float) -> float:
        value = self.section(section).get(key)
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return float(default)


# ── Inputs ─────────────────────────────────────────────────────────


@dataclass
class LeagueContext:
    """Everything about the league FORMAT and its current state.

    ``original_budget`` is the season's starting FAAB allowance — the
    denominator for every percentage the engine reports.  It is NOT
    any team's remaining balance; conflating the two is the specific
    defect that made the old engine's "objective" value shrink as a
    manager spent.
    """

    original_budget: int = 100
    team_count: int = 12
    starters_per_team: int = 20
    roster_size: int = 0
    min_bid: int = 0
    bid_increment: int = 1
    zero_bid_allowed: bool = True
    current_week: int | None = None
    playoff_week_start: int = 15
    in_season: bool = True
    faab_carries_over: bool = False
    league_key: str = ""


@dataclass
class TeamContext:
    """The SELECTED team.  Never hard-coded — the caller resolves
    which team is asking and passes it here."""

    owner_id: str = ""
    name: str = ""
    faab_remaining: int | None = None
    open_roster_spots: int = 0
    need_level: str = "neutral"
    competitive_status: str = "bubble"
    risk_posture: str = "balanced"
    faab_rank: int | None = None


@dataclass
class RivalTeam:
    """One opposing team, for the contention model."""

    owner_id: str = ""
    name: str = ""
    faab_remaining: int | None = None
    need_level: str = "neutral"
    aggression: float = 1.0
    low_sample: bool = True
    open_roster_spots: int = 1


@dataclass
class PlayerInput:
    """The add side, plus the drop side when a drop is required."""

    name: str = ""
    value: float = 0.0
    position: str | None = None
    player_id: str | None = None
    drop_name: str | None = None
    drop_value: float = 0.0


@dataclass
class Anchors:
    """Resolved league-format reference values (Stage A)."""

    v_allin: float
    v_repl: float
    band: float
    starter_slots: int
    source: str = "board"
    live_pool_repl: float | None = None
    format_repl: float | None = None
    widened: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "vAllIn": round(self.v_allin, 1),
            "vReplacement": round(self.v_repl, 1),
            "band": round(self.band, 1),
            "starterSlots": self.starter_slots,
            "source": self.source,
            "livePoolReplacement": (
                round(self.live_pool_repl, 1) if self.live_pool_repl is not None else None
            ),
            "formatReplacement": (
                round(self.format_repl, 1) if self.format_repl is not None else None
            ),
            "bandWidened": self.widened,
        }


# ── Stage A: anchors ───────────────────────────────────────────────


def _sorted_board_values(
    board_values: Iterable[float],
) -> list[float]:
    vals = [float(v) for v in board_values if isinstance(v, (int, float)) and v > 0]
    vals.sort(reverse=True)
    return vals


def _value_at_rank(sorted_values: Sequence[float], rank: int) -> float | None:
    """Board value at a 1-indexed rank.

    Past the end of the board the value is extrapolated toward zero
    rather than clamped to the last row: clamping would make a deep
    league's replacement anchor equal to its worst ranked player and
    silently collapse the band.
    """
    if not sorted_values:
        return None
    if rank < 1:
        rank = 1
    if rank <= len(sorted_values):
        return float(sorted_values[rank - 1])
    tail = float(sorted_values[-1])
    overshoot = rank - len(sorted_values)
    decay = max(0.0, 1.0 - overshoot / max(1, len(sorted_values)))
    return tail * decay


def resolve_anchors(
    board_values: Iterable[float],
    league: LeagueContext,
    *,
    available_values: Iterable[float] | None = None,
    config: FaabConfig | None = None,
) -> Anchors:
    """Stage A — the two league-format anchors.

    ``board_values`` is every rankable player value on the canonical
    board (picks / K / DEF already excluded by the caller).
    ``available_values`` is the same for UNROSTERED players only; it
    sharpens the replacement estimate but is optional.
    """
    cfg = config or FaabConfig()
    sorted_all = _sorted_board_values(board_values)

    slots = max(1, int(league.team_count) * int(league.starters_per_team))
    allin_mult = cfg.num("anchors", "allinSlotMultiple", 1.0)
    repl_mult = cfg.num("anchors", "replacementSlotMultiple", 2.0)

    v_allin = _value_at_rank(sorted_all, int(round(slots * allin_mult)))
    format_repl = _value_at_rank(sorted_all, int(round(slots * repl_mult)))

    # Live-pool replacement: the Nth-best genuinely available player.
    # Not the single best — that one is contested too, and using it
    # would make the anchor jump every time one player is added.
    live_repl: float | None = None
    if available_values is not None:
        avail = _sorted_board_values(available_values)
        if avail:
            idx = max(1, int(cfg.num("anchors", "replacementLivePoolRank", 12)))
            live_repl = float(avail[min(idx, len(avail)) - 1])

    source = "board"
    if v_allin is None:
        v_allin = cfg.num("anchors", "fallbackAllinValue", 2400)
        source = "fallback"
    if format_repl is None:
        format_repl = cfg.num("anchors", "fallbackReplacementValue", 1400)
        source = "fallback"

    if live_repl is not None:
        w = max(0.0, min(1.0, cfg.num("anchors", "replacementLivePoolWeight", 0.5)))
        v_repl = w * live_repl + (1.0 - w) * float(format_repl)
        source = "board+pool" if source == "board" else source
    else:
        v_repl = float(format_repl)

    # Guardrail: a pathologically barren board can push V_repl up
    # against V_allin, which would make the curve near-vertical and
    # violate "small value differences must not cause extreme jumps".
    # Widen DOWNWARD — V_allin is the well-anchored end.
    min_band = cfg.num("anchors", "minBandWidth", 700)
    widened = False
    if float(v_allin) - v_repl < min_band:
        v_repl = float(v_allin) - min_band
        widened = True
    v_repl = max(0.0, v_repl)

    return Anchors(
        v_allin=float(v_allin),
        v_repl=float(v_repl),
        band=max(1.0, float(v_allin) - v_repl),
        starter_slots=slots,
        source=source,
        live_pool_repl=live_repl,
        format_repl=float(format_repl),
        widened=widened,
    )


def position_family(position: str | None) -> str:
    """Normalize an IDP/offense position to its lineup family.

    Mirrors the roll-up the rest of the platform uses (``DT``/``DE``/
    ``EDGE``/``NT`` → ``DL`` and so on) so depth counting matches the
    slots a lineup actually has.
    """
    pos = str(position or "").upper()
    return _POSITION_FAMILY.get(pos, pos)


def starter_slots_for_position(
    position: str | None,
    starters: dict[str, Any] | None,
) -> float:
    """How many lineup slots this position must fill each week.

    Direct slots plus a share of every flex that accepts the position,
    so a 2-FLEX league genuinely requires more RB/WR/TE depth than a
    0-FLEX one.  Returns 0.0 for a position the lineup never starts.
    """
    if not position or not isinstance(starters, dict):
        return 0.0
    pos = str(position).upper()
    family = position_family(pos)
    total = float(starters.get(family) or starters.get(pos) or 0)

    for flex_key, eligible in _FLEX_ELIGIBILITY.items():
        slots = float(starters.get(flex_key) or 0)
        if slots > 0 and family in eligible:
            total += slots / len(eligible)
    return total


_POSITION_FAMILY = {
    "DT": "DL",
    "DE": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
}

_FLEX_ELIGIBILITY = {
    "FLEX": ("RB", "WR", "TE"),
    "SFLEX": ("QB", "RB", "WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "IDP_FLEX": ("DL", "LB", "DB"),
}


def classify_need(
    roster_values_at_position: Sequence[float],
    position: str | None,
    starters: dict[str, Any] | None,
    anchors: Anchors,
    *,
    config: FaabConfig | None = None,
) -> str:
    """Classify one roster's need at a position by STARTABLE DEPTH.

    Deliberately not ``src.trade.suggestions.analyze_roster``.  That
    helper answers a different question ("is this position a trade
    surplus"), and on this platform's real rosters it is measured to
    return ``surplus`` for 68 of 84 team/position pairs and ``need``
    exactly once — in a 58-man best-ball league every team is deep
    everywhere by that measure, so it cannot discriminate and the
    factor collapses to a constant.

    Startable depth is the question a waiver claim actually turns on:
    how many players at this position are better than what the wire
    hands out for free, against how many the lineup must start.
    """
    cfg = config or FaabConfig()
    required = starter_slots_for_position(position, starters)
    if required <= 0:
        return "neutral"

    startable = sum(1 for v in roster_values_at_position if float(v) > anchors.v_repl)
    spare = startable - required

    if spare < 0:
        return "starterHole"
    if spare < cfg.num("positionalNeed", "needSpareThreshold", 1.0):
        return "need"
    if spare >= cfg.num("positionalNeed", "surplusSpareThreshold", 3.0):
        return "surplus"
    return "neutral"


# ── Stage B/C: surplus and the ceiling curve ───────────────────────


def surplus_over_replacement(value: float, anchors: Anchors) -> float:
    """Value above what is freely available.  Floors at zero — a
    below-replacement player has no surplus, not negative surplus."""
    return max(0.0, float(value) - anchors.v_repl)


def _smootherstep(x: float) -> float:
    """6x^5 - 15x^4 + 10x^3 — zero first derivative at x=0 and x=1.

    Chosen over a logistic because it reaches exactly 0 and exactly 1
    at finite inputs (a logistic only approaches them), which is what
    lets "replacement level costs nothing" and "this player is worth
    the whole budget" both be exactly true rather than nearly true.
    """
    x = max(0.0, min(1.0, x))
    return x * x * x * (x * (x * 6.0 - 15.0) + 10.0)


def objective_ceiling(
    value: float,
    anchors: Anchors,
    *,
    config: FaabConfig | None = None,
) -> tuple[float, float]:
    """Stage C — ``(displayed_ceiling, raw_ceiling)`` in BUDGET UNITS.

    Both are multiples of the league's ORIGINAL budget, so 1.0 means
    "the whole season's allowance".  ``displayed`` is capped at 1.0 —
    a bid can never exceed the budget.  ``raw`` keeps climbing above
    the all-in line so the market layer can tell saturated players
    apart; a 9999 player must out-bid a 2400 player even though both
    are "worth everything".

    Deliberately independent of any team's remaining balance.
    """
    cfg = config or FaabConfig()
    surplus = surplus_over_replacement(value, anchors)
    if surplus <= 0:
        return 0.0, 0.0

    s = surplus / anchors.band
    gamma = cfg.num("ceilingCurve", "toeExponent", 2.2)
    displayed = _smootherstep(min(1.0, s**gamma))

    if s <= 1.0:
        raw = displayed
    else:
        slope = cfg.num("ceilingCurve", "aboveAllinSlope", 0.5)
        raw = 1.0 + (s - 1.0) * slope
    raw = min(raw, cfg.num("ceilingCurve", "rawCeilingCap", 6.0))
    return min(1.0, displayed), max(raw, displayed)


# ── Stage D: the team layer ────────────────────────────────────────


def season_option_value(
    league: LeagueContext,
    team: TeamContext,
    *,
    config: FaabConfig | None = None,
) -> tuple[float, str]:
    """Share of the ceiling this team should be willing to commit NOW.

    FAAB has option value: a dollar kept can win a later claim.  Early
    in the season most of the budget's worth is in future claims, so
    the ceiling is held back; by the final waiver period unspent
    budget expires worthless and the full ceiling is available.

    This relaxes the CEILING only.  It does not make players more
    expensive late — the recommended bid still comes from the market
    model, so it rises late only if rivals actually bid more.
    """
    cfg = config or FaabConfig()
    early = cfg.num("seasonPhase", "optionValueEarly", 0.55)
    late = cfg.num("seasonPhase", "optionValueLate", 1.0)
    exponent = cfg.num("seasonPhase", "optionValueExponent", 1.6)

    status = str(team.competitive_status or "bubble").lower()
    if status == "eliminated":
        factor = cfg.num("seasonPhase", "eliminatedOptionValue", 1.0)
        reason = "eliminated — unspent FAAB has no remaining use"
        return _apply_carryover(factor, league, cfg), reason

    if not league.in_season or league.current_week is None:
        factor = cfg.num("seasonPhase", "offseasonOptionValue", 0.45)
        return _apply_carryover(factor, league, cfg), "offseason — preserve budget for the season"

    last_waiver_week = max(1, int(league.playoff_week_start) - 1)
    week = max(1, int(league.current_week))
    if week >= last_waiver_week:
        progress = 1.0
        reason = "final waiver period — unspent FAAB expires"
    else:
        progress = (week - 1) / max(1, last_waiver_week - 1)
        reason = f"week {week} of {last_waiver_week} waiver periods"

    factor = early + (late - early) * (progress**exponent)

    status_mult = cfg.num("competitiveStatus", status, 1.0)
    factor *= status_mult
    if status_mult != 1.0:
        reason += f"; {status}"

    return _apply_carryover(max(0.0, min(1.0, factor)), league, cfg), reason


def _apply_carryover(factor: float, league: LeagueContext, cfg: FaabConfig) -> float:
    """Damp the late-season relaxation when FAAB carries over.

    Without carryover the budget is use-it-or-lose-it and the factor
    is allowed to reach 1.0 at the last waiver period.  With carryover
    a dollar kept still has future worth, so the relaxation is pulled
    back toward the early-season level by ``carryoverRetention``.
    """
    factor = max(0.0, min(1.0, factor))
    if not league.faab_carries_over:
        return factor
    retention = max(0.0, min(1.0, cfg.num("seasonPhase", "carryoverRetention", 0.5)))
    early = cfg.num("seasonPhase", "optionValueEarly", 0.55)
    return max(0.0, min(1.0, factor * (1.0 - retention) + early * retention))


def team_ceiling(
    player: PlayerInput,
    anchors: Anchors,
    league: LeagueContext,
    team: TeamContext,
    *,
    config: FaabConfig | None = None,
) -> dict[str, Any]:
    """Stage D — the team-specific ceiling, in dollars.

    Starts from the objective surplus, subtracts the drop side the
    same way it was added (surplus over replacement, so a below-
    replacement drop is free), applies roster need and season option
    value, and caps at the team's remaining balance.
    """
    cfg = config or FaabConfig()
    budget = max(1, int(league.original_budget))

    obj_pct, obj_raw = objective_ceiling(player.value, anchors, config=cfg)

    # Drop cost as surplus, so it is exactly the inverse of the add.
    add_surplus = surplus_over_replacement(player.value, anchors)
    if team.open_roster_spots > 0 or not player.drop_name:
        drop_surplus = cfg.num("dropCost", "openRosterSpotCost", 0.0)
        drop_note = (
            "open roster spot — no drop required"
            if team.open_roster_spots > 0
            else "no drop selected"
        )
    else:
        drop_surplus = surplus_over_replacement(player.drop_value, anchors) * cfg.num(
            "dropCost", "dropSurplusWeight", 1.0
        )
        drop_note = (
            f"drop {player.drop_name} costs {drop_surplus:.0f} of surplus"
            if drop_surplus > 0
            else f"drop {player.drop_name} is replacement level — free"
        )

    net_surplus = max(0.0, add_surplus - drop_surplus)
    net_value = anchors.v_repl + net_surplus
    net_pct, net_raw = objective_ceiling(net_value, anchors, config=cfg)

    need = str(team.need_level or "neutral")
    need_mult = cfg.num("positionalNeed", need, 1.0)

    option_factor, option_reason = season_option_value(league, team, config=cfg)

    team_pct = net_pct * need_mult * option_factor
    team_raw = net_raw * need_mult * option_factor

    remaining = team.faab_remaining if team.faab_remaining is not None else budget
    remaining = max(0, int(remaining))

    ceiling_dollars = min(float(remaining), team_pct * budget)
    # Deliberately NOT capped at ``remaining``.  This is "what he is
    # worth to us", which can exceed what we are able to pay, and it
    # is the numerator of the expected-surplus objective.  Capping it
    # would make surplus exactly zero at b = remaining, so the
    # optimiser could never recommend going all-in on a player who is
    # genuinely worth more than the budget.  The BID is capped by the
    # balance; the VALUE is not.
    raw_dollars = team_raw * budget

    return {
        "objectivePct": obj_pct,
        "objectiveRawPct": obj_raw,
        "objectiveDollars": obj_pct * budget,
        "netSurplus": net_surplus,
        "addSurplus": add_surplus,
        "dropSurplus": drop_surplus,
        "dropNote": drop_note,
        "needMultiplier": need_mult,
        "optionValueFactor": option_factor,
        "optionValueReason": option_reason,
        "teamCeilingDollars": max(0.0, ceiling_dollars),
        "teamRawCeilingDollars": max(0.0, raw_dollars),
        "remaining": remaining,
        "budget": budget,
    }


# ── Stage E: the market model ──────────────────────────────────────


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _rival_engagement(
    demand_signal: float,
    rival: RivalTeam,
    *,
    config: FaabConfig,
) -> float:
    """P(this rival bids at all).

    Anchored on the measured reality that roughly half of this
    league's completed adds cost $0 — most claims simply are not
    contested.  Engagement climbs with the player's demand signal and
    with the rival's own positional need.

    ``demand_signal`` is the player's CEILING share (0-1), not his raw
    surplus ratio.  The distinction matters: surplus is linear in
    value, so it rates a marginal TE3 as a third of an all-in player
    and predicts contested bidding on players this league demonstrably
    adds for $0.  The ceiling is the nonlinear "does anyone actually
    want him" signal, which is the one that matches the history.
    """
    base = config.num("market", "engagementBaseRate", 0.05)
    top = config.num("market", "engagementMaxRate", 0.7)
    exponent = config.num("market", "engagementExponent", 0.9)
    s = max(0.0, min(1.0, demand_signal))
    p = base + (top - base) * (s**exponent)

    need_mults = config.section("market").get("rivalNeedEngagementMultiplier") or {}
    mult = need_mults.get(str(rival.need_level or "neutral"), 1.0)
    try:
        p *= float(mult)
    except (TypeError, ValueError):
        pass

    if rival.faab_remaining is not None and rival.faab_remaining <= 0:
        return 0.0
    return max(0.0, min(1.0, p))


def rival_bid_cdf(
    bid: float,
    rivals: Sequence[RivalTeam],
    *,
    demand_signal: float,
    league: LeagueContext,
    config: FaabConfig,
) -> float:
    """P(every rival bids <= ``bid``) — i.e. P(we win at ``bid``).

    Each rival is a zero-inflated lognormal: with probability
    ``1 - p_i`` they do not contest at all, and otherwise their bid is
    lognormal around ``rivalMedianShareOfCeiling`` of THEIR ceiling.
    Managers bid well below their true maximum, which is the same
    behaviour this engine recommends.

    A rival with no visible balance is excluded outright — an
    unverifiable rival who might be broke must never raise the user's
    bid.  That is a hard invariant, not a setting: the config records
    it under ``_invariantNotAToggle_unknownBalanceAssumption`` so the
    behaviour is documented where the other market parameters live,
    but changing that string changes nothing.
    """
    budget = max(1, int(league.original_budget))
    median_share = config.num("market", "rivalDisciplineFactor", 1.0)
    sigma = max(1e-6, config.num("market", "rivalSigma", 1.1))
    tie_break = config.num("market", "tieBreakWinProbability", 0.5)
    lo, hi = (config.section("market").get("aggressionClamp") or [0.5, 2.0])[:2]

    win = 1.0
    for rival in rivals:
        if rival.faab_remaining is None:
            continue  # unverifiable — excluded by policy
        p = _rival_engagement(demand_signal, rival, config=config)
        if p <= 0.0:
            continue

        aggression = max(float(lo), min(float(hi), float(rival.aggression or 1.0)))
        # A rival's expected bid is a share of the ORIGINAL BUDGET
        # driven by league-wide demand for the player — NOT a share of
        # our own ceiling.  The two must stay decoupled: this league
        # demonstrably pays above what the value curve says a
        # 1700-2100 player is worth (observed p90 winning bid 15% of
        # budget against a ~5% ceiling).  Tying rival behaviour to our
        # ceiling would either import that overpayment into our own
        # recommendation or pretend rivals are as disciplined as we
        # are.  What the market PAYS and what the player is WORTH are
        # separate quantities, and this is where that separation lives.
        base_share = config.num("market", "rivalBaseSharePct", 1.5) / 100.0
        max_share = config.num("market", "rivalMaxSharePct", 45.0) / 100.0
        demand_exp = config.num("market", "rivalShareExponent", 1.3)
        share = base_share + (max_share - base_share) * (
            max(0.0, min(1.0, demand_signal)) ** demand_exp
        )
        median_bid = max(0.25, budget * share * median_share * aggression)
        median_bid = min(median_bid, float(rival.faab_remaining))

        if bid <= 0:
            # A $0 claim is legitimate on Sleeper and is how roughly
            # half of this league's adds are actually made, but it is
            # settled by waiver priority rather than by price.
            beat_prob = tie_break if rival.faab_remaining <= 0 else 0.0
        else:
            z = (math.log(max(bid, 1e-9)) - math.log(median_bid)) / sigma
            beat_prob = _normal_cdf(z)
            # A rival cannot bid more than they have.  Matching their
            # balance exactly is a TIE, broken by waiver priority —
            # not a certain win.  Treating it as certain is what makes
            # an all-in bid look risk-free when it is not.
            if bid > rival.faab_remaining:
                beat_prob = 1.0
            elif bid == rival.faab_remaining:
                beat_prob = max(beat_prob, tie_break)

        win *= (1.0 - p) + p * beat_prob
    return max(0.0, min(1.0, win))


def rival_expected_bids(
    rivals: Sequence[RivalTeam],
    *,
    demand_signal: float,
    league: LeagueContext,
    config: FaabConfig | None = None,
) -> list[dict[str, Any]]:
    """Per-rival expected bid, for the contention panel.

    Reports the MEDIAN of each rival's modelled bid distribution plus
    the probability they contest at all — the honest pair, since a
    rival who bids $40 one time in five is not the same threat as one
    who bids $40 every time.  A rival with no visible balance is
    reported with ``balanceUnknown`` and is excluded from the clearing
    math elsewhere.
    """
    cfg = config or FaabConfig()
    budget = max(1, int(league.original_budget))
    base_share = cfg.num("market", "rivalBaseSharePct", 1.5) / 100.0
    max_share = cfg.num("market", "rivalMaxSharePct", 45.0) / 100.0
    demand_exp = cfg.num("market", "rivalShareExponent", 1.3)
    discipline = cfg.num("market", "rivalDisciplineFactor", 1.0)
    lo, hi = (cfg.section("market").get("aggressionClamp") or [0.5, 2.0])[:2]

    share = base_share + (max_share - base_share) * (
        max(0.0, min(1.0, demand_signal)) ** demand_exp
    )

    out: list[dict[str, Any]] = []
    for rival in rivals:
        aggression = max(float(lo), min(float(hi), float(rival.aggression or 1.0)))
        median = budget * share * discipline * aggression
        if rival.faab_remaining is not None:
            median = min(median, float(rival.faab_remaining))
        p = _rival_engagement(demand_signal, rival, config=cfg)
        out.append(
            {
                "ownerId": rival.owner_id,
                "teamName": rival.name,
                "expBid": int(round(max(0.0, median))),
                "contestProbability": round(p, 3),
                "faabRemaining": rival.faab_remaining,
                "needLevel": rival.need_level,
                "aggression": round(aggression, 3),
                "lowSample": rival.low_sample,
                "balanceUnknown": rival.faab_remaining is None,
            }
        )
    out.sort(key=lambda r: -(r["expBid"] * max(r["contestProbability"], 0.01)))
    return out


def _bid_grid(max_bid: int, points: int) -> list[int]:
    """Integer candidate bids.  Dense at the bottom (where almost every
    real claim lands) and thinned above, so the search stays cheap on
    a $1000-budget league without losing resolution at $0-$5."""
    if max_bid <= 0:
        return [0]
    if max_bid <= points:
        return list(range(0, max_bid + 1))
    dense = list(range(0, min(max_bid, 40) + 1))
    remaining = points - len(dense)
    step = max(1, (max_bid - 40) // max(1, remaining))
    coarse = list(range(41, max_bid + 1, step))
    if coarse and coarse[-1] != max_bid:
        coarse.append(max_bid)
    return dense + coarse


def _market_clearing_price(
    rivals: Sequence[RivalTeam],
    *,
    demand_signal: float,
    league: LeagueContext,
    config: FaabConfig,
) -> int:
    """The price at which the top rival bid is as likely to be under
    as over — the median of the top-rival distribution.

    Scanned over the whole budget, independent of our own balance or
    ceiling: this is what the player will cost, not what we can pay.
    """
    budget = max(1, int(league.original_budget))
    for b in range(0, budget + 1):
        if (
            rival_bid_cdf(
                float(b),
                rivals,
                demand_signal=demand_signal,
                league=league,
                config=config,
            )
            >= 0.5
        ):
            return b
    return budget


def optimal_bid(
    rivals: Sequence[RivalTeam],
    *,
    raw_ceiling_dollars: float,
    display_ceiling_dollars: float,
    demand_signal: float,
    league: LeagueContext,
    team: TeamContext,
    config: FaabConfig,
) -> dict[str, Any]:
    """Stage E — the bid ladder from one expected-surplus curve.

    ``recommended = argmax_b P(win|b) x (rawCeiling - b)``.  Bidding
    the ceiling captures zero surplus by definition, so the optimum is
    always strictly below it: this is the mechanism that turns "worth
    $100" into "bid $36".

    Conservative / aggressive read the SAME win-probability curve at
    different targets, so all four numbers stay mutually consistent
    rather than being independent multiples of each other.
    """
    remaining = team.faab_remaining if team.faab_remaining is not None else league.original_budget
    remaining = max(0, int(remaining))
    # The ceiling that BOUNDS a bid is the RAW one.  The displayed
    # ceiling is capped at 100% of the original budget because that is
    # the honest way to report "what is he worth"; using it as the
    # search bound would make every player above the all-in line share
    # one cap and collapse the ladder — a 9999 player and a 2341
    # player would draw the same bid.
    hard_cap = int(min(remaining, math.floor(max(raw_ceiling_dollars, display_ceiling_dollars))))

    # The expected clearing price is a statement about the MARKET, not
    # about us, so it is scanned over the full budget rather than over
    # what we happen to be able to afford.  A broke team still needs to
    # be told what the player will go for — reporting $0 because our
    # balance is $0 would read as "nobody wants him".
    market_clearing = _market_clearing_price(
        rivals,
        demand_signal=demand_signal,
        league=league,
        config=config,
    )

    if hard_cap <= 0:
        return {
            "recommended": 0,
            "conservative": 0,
            "aggressive": 0,
            "maxRational": 0,
            "clearing": market_clearing,
            "winProbability": None,
            "curve": [],
        }

    points = int(config.num("bidPolicy", "searchGridPoints", 400))
    grid = _bid_grid(hard_cap, points)

    posture_map = config.section("bidPolicy").get("riskPosture") or {}
    posture = float(posture_map.get(str(team.risk_posture or "balanced"), 1.0) or 1.0)

    curve: list[tuple[int, float, float]] = []
    for b in grid:
        p_win = rival_bid_cdf(
            float(b),
            rivals,
            demand_signal=demand_signal,
            league=league,
            config=config,
        )
        ev = p_win * max(0.0, raw_ceiling_dollars - b)
        curve.append((b, p_win, ev))

    best_ev = max(ev for _, _, ev in curve)
    min_edge = config.num("bidPolicy", "minEdge", 0.02)

    # Cheapest bid within minEdge of the optimum — "the lowest rational
    # bid".  The EV curve is genuinely flat for an uncontested player,
    # and argmax alone would pick an arbitrary point on that plateau.
    threshold = best_ev * (1.0 - min_edge)
    recommended = next((b for b, _, ev in curve if ev >= threshold and best_ev > 0), 0)

    if posture != 1.0:
        recommended = int(round(recommended * posture))
    recommended = max(0, min(hard_cap, recommended))

    # Win probability is bounded by what this budget can actually buy:
    # against flush rivals on an elite player even an all-in bid may
    # only reach 40%.  Reading the targets ABSOLUTELY would then return
    # hard_cap for every one of them and collapse conservative,
    # aggressive and clearing onto the same number.  Scale each target
    # into the achievable range instead.
    max_win = max((p for _, p, _ in curve), default=0.0)

    def bid_at_win_target(target: float, *, relative: bool = True) -> int:
        goal = target * max_win if relative else target
        for b, p_win, _ in curve:
            if p_win >= goal:
                return min(b, hard_cap)
        return hard_cap

    conservative = min(
        recommended,
        bid_at_win_target(config.num("bidPolicy", "conservativeWinTarget", 0.35)),
    )
    aggressive = max(
        recommended,
        bid_at_win_target(config.num("bidPolicy", "aggressiveWinTarget", 0.85)),
    )
    aggressive = min(aggressive, hard_cap)

    clearing = market_clearing

    win_at_recommended = next(
        (p for b, p, _ in curve if b >= recommended),
        curve[-1][1] if curve else 0.0,
    )

    return {
        "recommended": int(recommended),
        "conservative": int(max(0, conservative)),
        "aggressive": int(aggressive),
        "maxRational": int(hard_cap),
        "clearing": int(clearing),
        "winProbability": round(float(win_at_recommended), 3),
        "curve": [{"bid": b, "winProb": round(p, 4)} for b, p, _ in curve[:60]],
    }


# ── Public entry point ─────────────────────────────────────────────


@dataclass
class _FactorRow:
    label: str
    contribution: str
    weight: float
    missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "contribution": self.contribution,
            "weight": self.weight,
            "missing": self.missing,
        }


def _confidence(factors: Sequence[_FactorRow], cfg: FaabConfig) -> str:
    total = sum(f.weight for f in factors)
    realized = sum(f.weight for f in factors if not f.missing)
    share = (realized / total) if total > 0 else 0.0
    if share >= cfg.num("confidence", "highThreshold", 0.85):
        return "high"
    if share >= cfg.num("confidence", "mediumThreshold", 0.55):
        return "medium"
    return "low"


def recommend(
    player: PlayerInput,
    league: LeagueContext,
    team: TeamContext,
    *,
    anchors: Anchors,
    rivals: Sequence[RivalTeam] = (),
    config: FaabConfig | None = None,
    extra_factors: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """The one FAAB recommendation call.

    Returns both halves of the answer, always separated:

    ``objective``  what the player is worth, as dollars AND as a share
                   of the league's ORIGINAL budget.  Identical for
                   every team; unaffected by what anyone has spent.
    ``bids``       what THIS team should do: recommended, conservative,
                   aggressive, max rational, expected clearing price,
                   and the win probability at the recommended bid.
    """
    cfg = config or FaabConfig()
    budget = max(1, int(league.original_budget))
    factors: list[_FactorRow] = []
    warnings: list[str] = []

    ceil = team_ceiling(player, anchors, league, team, config=cfg)

    factors.append(
        _FactorRow(
            "Value above replacement",
            f"{player.value:.0f} vs {anchors.v_repl:.0f} free-agent baseline",
            0.30,
        )
    )
    factors.append(
        _FactorRow(
            "League format",
            f"all-in line {anchors.v_allin:.0f} ({anchors.starter_slots} starter slots)",
            0.15,
        )
    )
    if player.drop_name:
        factors.append(_FactorRow("Drop cost", ceil["dropNote"], 0.15))
    elif team.open_roster_spots > 0:
        factors.append(_FactorRow("Roster space", "open spot — no drop needed", 0.15))
    factors.append(_FactorRow("Season timing", ceil["optionValueReason"], 0.15))

    usable_rivals = [r for r in rivals if r.faab_remaining is not None]
    if rivals and usable_rivals:
        factors.append(
            _FactorRow(
                "Expected competition",
                f"{len(usable_rivals)} rivals with visible balances",
                0.25,
            )
        )
    else:
        factors.append(
            _FactorRow("Expected competition", "no rival balances available", 0.25, missing=True)
        )

    # Rival demand keys on the OBJECTIVE ceiling — team-independent by
    # construction, so rival behaviour never becomes a function of our
    # roster or budget.  It reads the UNCAPPED raw ceiling, normalised
    # by ``demandSaturationBudgets``: the displayed ceiling saturates
    # at 1.0 for everyone above the all-in line, which would model a
    # marginal starter as drawing exactly as much competition as a
    # top-5 dynasty asset.  The raw signal keeps separating them.
    demand_signal = min(
        1.0,
        ceil["objectiveRawPct"] / max(1e-9, cfg.num("market", "demandSaturationBudgets", 2.5)),
    )

    bids = optimal_bid(
        usable_rivals,
        raw_ceiling_dollars=ceil["teamRawCeilingDollars"],
        display_ceiling_dollars=ceil["teamCeilingDollars"],
        demand_signal=demand_signal,
        league=league,
        team=team,
        config=cfg,
    )

    remaining = ceil["remaining"]
    if remaining <= 0:
        warnings.append("This team has no FAAB left — no bid is possible.")
    if ceil["objectiveDollars"] > remaining and remaining > 0:
        warnings.append(
            f"This player is worth more (${ceil['objectiveDollars']:.0f}) than this team "
            f"has left (${remaining}) — the bid is capped by the balance, not by value."
        )
    if player.drop_value > 0 and player.drop_value >= player.value:
        warnings.append(
            "The drop is worth as much as the add — this swap does not improve the roster."
        )
    if anchors.widened:
        warnings.append(
            "The board is unusually compressed here; the value curve was widened to keep "
            "recommendations stable."
        )

    for raw in extra_factors:
        if isinstance(raw, dict) and raw.get("label"):
            factors.append(
                _FactorRow(
                    str(raw.get("label")),
                    str(raw.get("contribution") or ""),
                    float(raw.get("weight") or 0.0),
                    bool(raw.get("missing")),
                )
            )

    explanation = _explain(player, ceil, bids, anchors, league, team, usable_rivals)

    return {
        "objective": {
            "dollars": int(round(ceil["objectiveDollars"])),
            "pctOfOriginalBudget": round(100.0 * ceil["objectivePct"], 1),
            "originalBudget": budget,
            "surplusOverReplacement": round(ceil["addSurplus"], 1),
        },
        "bids": {
            "recommended": bids["recommended"],
            "conservative": bids["conservative"],
            "aggressive": bids["aggressive"],
            "maxRational": bids["maxRational"],
            "clearing": bids["clearing"],
        },
        "pctOfOriginalBudget": round(100.0 * bids["recommended"] / budget, 1),
        "pctOfRemaining": (
            round(100.0 * bids["recommended"] / remaining, 1) if remaining > 0 else None
        ),
        "winProbability": bids["winProbability"],
        "confidence": _confidence(factors, cfg),
        "factors": [f.to_dict() for f in factors],
        "warnings": warnings,
        "explanation": explanation,
        "anchors": anchors.to_dict(),
        "teamCeilingDollars": int(round(ceil["teamCeilingDollars"])),
        "optionValueFactor": round(ceil["optionValueFactor"], 3),
        "needMultiplier": ceil["needMultiplier"],
        "riskPosture": team.risk_posture,
    }


def _explain(
    player: PlayerInput,
    ceil: dict[str, Any],
    bids: dict[str, Any],
    anchors: Anchors,
    league: LeagueContext,
    team: TeamContext,
    rivals: Sequence[RivalTeam],
) -> str:
    """One or two sentences naming the factors that actually moved this
    recommendation — not a restatement of the number."""
    rec = bids["recommended"]
    obj = ceil["objectiveDollars"]

    if ceil["addSurplus"] <= 0:
        return (
            f"No bid. {player.name or 'This player'} grades at or below the "
            f"{anchors.v_repl:.0f} free-agent baseline — comparable production is "
            "available for nothing."
        )

    parts: list[str] = []
    if rec <= 0:
        parts.append("A minimum or $0 claim is enough here")
    else:
        parts.append(f"Bid ${rec}")

    if obj >= league.original_budget * 0.95:
        parts.append(
            f"the player is worth up to the entire ${league.original_budget} budget, "
            f"but ${rec} is the lowest bid that still wins often enough to be worth it"
        )
    else:
        parts.append(f"worth up to ${obj:.0f} of the original ${league.original_budget}")

    contested = [r for r in rivals if str(r.need_level) in ("need", "starterHole")]
    if contested:
        parts.append(f"{len(contested)} rival(s) have a need at the position")
    elif rivals:
        parts.append("no rival shows a clear need at the position")

    if player.drop_name and ceil["dropSurplus"] > 0:
        parts.append(f"and you would give up real value dropping {player.drop_name}")
    elif team.open_roster_spots > 0:
        parts.append("and you have an open roster spot")

    return f"{parts[0]} — {', '.join(parts[1:])}."
