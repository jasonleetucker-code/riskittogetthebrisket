"""Competitive Posture (#840 / C7-POST-01) — PUSH / HOLD / RETOOL / REBUILD.

ONE canonical team-level strategic owner.  It CONSUMES the competitive window
(``src.roster_intel.window``) — that module already places each roster in
(competitiveness × trajectory) space as five softmax affinities, sourced from
the playoff simulator's championship odds when a fresh simulation exists and
from lineup-strength rank otherwise.  Nothing here re-derives either axis.
Binding record: ``docs/trade/ANALYZE_TRADE_COMPETITIVE_POSTURE_ADDENDUM_2026-08-14.md``.

What posture adds over the window
─────────────────────────────────
1. **One strategic axis.**  The window's five states sit on a contend↔rebuild
   axis (``window.STATE_ORDER``).  ``lean`` is the affinity-weighted position
   on that axis, in [-1, +1].
2. **Season timing.**  "A 25% playoff chance before Week 1 is not the same
   strategic state as 25% in deadline week."  The deadline AMPLIFIES the lean
   (a bubble team must commit as the window to act closes); after the deadline
   in-season trading is closed and the lean is DAMPED (decisions are for the
   offseason).  Timing is read from the league's own Sleeper settings
   (``leg`` / ``last_scored_leg`` / ``trade_deadline`` / ``playoff_week_start``).
3. **Own-pick ownership.**  A team that does not hold its own next first gains
   nothing from losing, so part of its REBUILD affinity moves to RETOOL.
4. **Four postures as affinities**, a softmax over distance to four anchors on
   the lean axis — no single hand-cut threshold, so a team a hair either side
   of a boundary does not flip while its neighbour stays put.

What posture is NOT
───────────────────
* **Not a vote.**  It is derived from playoff odds / lineup strength / age —
  the same lineages Analyze Trade already reads — so it never adds a direction
  of its own.  ``src.trade.analyze_trade`` uses it only to decide which of two
  DISAGREEING primary lenses carries the tie (current-season roster utility
  for PUSH; long-horizon canonical value for RETOOL / REBUILD; neither for
  HOLD or low confidence).
* **Not calibrated.**  Every anchor, multiplier and temperature below is a
  declared PRIOR; nothing has been scored against what teams actually did.
  The payload therefore publishes ``affinities`` (never "probabilities") and a
  ``calibration`` block saying so.
* **Not hard-coded to managers.**  Every input is measured from roster/team
  state; there is no manual override path here.
* **No draft-order claim.**  The league's non-playoff draft-order method (Max
  PF, record, consolation bracket) is not modelled by ``src.ros.pick_projection``
  and is not in the Sleeper settings this reads, so no projected own-pick slot
  is ever credited.  ``draftOrder`` says so on every payload.

Pure computation apart from :func:`load_playoff_odds` (one cached-file read).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.roster_intel.marginal import solve_summary
from src.roster_intel.window import (
    COMPETITIVE_STATES,
    CompetitiveWindow,
    compute_window,
)
from src.ros.lineup import RosterPlayer, lineup_position

__all__ = [
    "POSTURES",
    "POSTURE_VERSION",
    "PRIORS",
    "PostureResult",
    "SeasonTiming",
    "build_league_postures",
    "classify_posture",
    "load_playoff_odds",
    "own_first_asset_id",
    "posture_marginal",
    "season_timing",
]

POSTURE_VERSION = "posture_v1"
POSTURES = ("PUSH", "HOLD", "RETOOL", "REBUILD")

#: Every number that shapes a posture, published on the payload.  All PRIOR.
PRIORS: dict[str, Any] = {
    "class": "PRIOR",
    # Where each window state sits on the contend(+1) <-> rebuild(-1) axis.
    # ``window.ORDERING_CAVEAT``: retool vs productive_struggle is the soft
    # pair, so they sit close together.
    "stateLean": {
        "championship_contender": 1.0,
        "playoff_contender": 0.5,
        "retool": -0.3,
        "productive_struggle": -0.55,
        "rebuild": -1.0,
    },
    # Posture anchors on the same axis.
    "anchors": {"PUSH": 0.6, "HOLD": 0.0, "RETOOL": -0.4, "REBUILD": -0.8},
    "temperature": 0.06,
    # Lean multiplier by season phase.  Regular season ramps linearly from
    # ``regularSeasonStart`` at week 1 to ``regularSeasonDeadline`` at the
    # trade deadline.
    "timing": {
        "preseason": 1.0,
        "regularSeasonStart": 1.0,
        "regularSeasonDeadline": 1.8,
        "postDeadline": 0.6,
        "postseason": 0.6,
        "unknown": 1.0,
    },
    # Share of REBUILD affinity moved to RETOOL when the team does not hold
    # its own next first (losing improves no pick it owns).
    "noOwnFirstRebuildTransfer": 0.4,
    "confidence": {"highTop": 0.6, "highMargin": 0.25, "mediumTop": 0.45, "mediumMargin": 0.1},
}

_CALIBRATION = {
    "state": "uncalibrated",
    "note": (
        "Affinities, not probabilities: the anchors, timing multipliers and "
        "temperature are declared priors and have not been scored against "
        "realized team outcomes."
    ),
}

_DRAFT_ORDER = {
    "state": "unmodeled",
    "note": (
        "The league's non-playoff draft-order method (record / Max PF / "
        "consolation) is not modelled, so no projected own-pick slot is "
        "credited and losing is never treated as a draft-capital benefit."
    ),
}


# ── Season timing ─────────────────────────────────────────────────────────


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n


@dataclass(frozen=True)
class SeasonTiming:
    phase: str  # preseason | regular_season | post_deadline | postseason | unknown
    week: int | None
    last_scored_week: int | None
    trade_deadline: int | None
    playoff_week_start: int | None
    #: 0 at the season's start, 1 at the trade deadline; None outside the
    #: regular season.
    progress_to_deadline: float | None
    multiplier: float
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "week": self.week,
            "lastScoredWeek": self.last_scored_week,
            "tradeDeadlineWeek": self.trade_deadline,
            "playoffWeekStart": self.playoff_week_start,
            "progressToDeadline": (
                None if self.progress_to_deadline is None else round(self.progress_to_deadline, 3)
            ),
            "leanMultiplier": round(self.multiplier, 3),
            "source": "sleeper.leagueSettings",
            "notes": list(self.notes),
        }


def season_timing(league_settings: Mapping[str, Any] | None) -> SeasonTiming:
    """Where the league is in its season, from the host's own settings."""
    s = league_settings if isinstance(league_settings, Mapping) else {}
    t = PRIORS["timing"]
    week = _int(s.get("leg"))
    scored = _int(s.get("last_scored_leg"))
    deadline = _int(s.get("trade_deadline"))
    playoffs = _int(s.get("playoff_week_start"))
    start = _int(s.get("start_week")) or 1
    if playoffs is None or playoffs <= start or scored is None:
        return SeasonTiming(
            "unknown",
            week,
            scored,
            deadline,
            playoffs,
            None,
            float(t["unknown"]),
            ("season week or playoff start not published; timing is not applied",),
        )
    notes: list[str] = []
    # A deadline of 0 / missing / past the playoffs means "no in-season
    # deadline": the regular season itself is the trading window.
    horizon = deadline if deadline and start <= deadline < playoffs else playoffs - 1
    if not deadline:
        notes.append("league publishes no trade deadline; the regular season end is used")
    if scored < start:
        return SeasonTiming(
            "preseason", week, scored, deadline, playoffs, 0.0, float(t["preseason"]), tuple(notes)
        )
    if scored >= playoffs:
        return SeasonTiming(
            "postseason",
            week,
            scored,
            deadline,
            playoffs,
            None,
            float(t["postseason"]),
            tuple(notes),
        )
    current = week if week is not None else scored + 1
    if current > horizon:
        return SeasonTiming(
            "post_deadline",
            week,
            scored,
            deadline,
            playoffs,
            None,
            float(t["postDeadline"]),
            tuple(notes),
        )
    span = max(1, horizon - start + 1)
    progress = max(0.0, min(1.0, scored / span))
    mult = float(t["regularSeasonStart"]) + progress * (
        float(t["regularSeasonDeadline"]) - float(t["regularSeasonStart"])
    )
    return SeasonTiming(
        "regular_season", week, scored, deadline, playoffs, progress, mult, tuple(notes)
    )


# ── Own-pick ownership ─────────────────────────────────────────────────────


def _rid(team: Mapping[str, Any]) -> int | None:
    for key in ("roster_id", "rosterId"):
        rid = _int(team.get(key))
        if rid is not None:
            return rid
    return None


def _upcoming_draft_year(teams: Sequence[Mapping[str, Any]]) -> int | None:
    """The earliest season in the league's own published pick inventory.

    The overlay publishes only the league's owned-pick seasons (Wave A's
    ``league_draft_years``), so its minimum IS the upcoming draft.
    """
    seasons = [
        _int(d.get("season"))
        for t in teams
        if isinstance(t, Mapping)
        for d in (t.get("pickDetails") or [])
        if isinstance(d, Mapping)
    ]
    seasons = [s for s in seasons if s is not None]
    return min(seasons) if seasons else None


def own_first_asset_id(league_key: str | None, season: int | None, rid: int | None) -> str | None:
    if not league_key or season is None or rid is None:
        return None
    return f"pick:{league_key}:{season}:r1:o{rid}"


def _owns_own_first(
    team: Mapping[str, Any], teams: Sequence[Mapping[str, Any]]
) -> tuple[bool | None, int | None, str | None]:
    """``(owns, upcoming_draft_year, asset_id)``; ``owns`` is None when unknowable."""
    rid = _rid(team)
    details = team.get("pickDetails")
    year = _upcoming_draft_year(teams)
    if rid is None or not isinstance(details, list) or year is None:
        return None, year, None
    aid = None
    for d in details:
        if not isinstance(d, Mapping):
            continue
        if (
            _int(d.get("season")) == year
            and _int(d.get("round")) == 1
            and _int(d.get("fromRosterId")) == rid
        ):
            return True, year, str(d.get("assetId") or "") or None
        if aid is None and str(d.get("assetId") or "").endswith(f":r1:o{rid}"):
            aid = str(d.get("assetId"))
    return False, year, aid


# ── Classification ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PostureResult:
    posture: str
    affinities: dict[str, float]
    confidence: str
    lean: float
    lean_raw: float
    timing: SeasonTiming
    owns_own_first: bool | None
    window: CompetitiveWindow
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def top(self) -> float:
        return self.affinities[self.posture]

    def to_dict(self) -> dict[str, Any]:
        return {
            "posture": self.posture,
            "confidence": self.confidence,
            "affinities": {k: round(v, 4) for k, v in self.affinities.items()},
            "lean": round(self.lean, 4),
            "components": {
                "windowLean": round(self.lean_raw, 4),
                "competitiveness": round(self.window.inputs.competitiveness, 4),
                "competitivenessSource": self.window.inputs.competitiveness_source,
                "trajectory": round(self.window.inputs.trajectory, 4),
                "trajectorySample": self.window.inputs.trajectory_sample,
                "windowAffinities": {k: round(v, 4) for k, v in self.window.probabilities.items()},
                "ownsOwnFirst": self.owns_own_first,
                "timing": self.timing.to_dict(),
            },
            "calibration": dict(_CALIBRATION),
            "draftOrder": dict(_DRAFT_ORDER),
            "countedAsVote": False,
            "notes": list(self.notes),
        }


def _softmax(scores: Mapping[str, float]) -> dict[str, float]:
    mx = max(scores.values())
    exps = {k: math.exp(v - mx) for k, v in scores.items()}
    total = sum(exps.values())
    return {k: v / total for k, v in exps.items()}


def _confidence(aff: Mapping[str, float]) -> str:
    ranked = sorted(aff.values(), reverse=True)
    top, second = ranked[0], (ranked[1] if len(ranked) > 1 else 0.0)
    c = PRIORS["confidence"]
    if top >= c["highTop"] and top - second >= c["highMargin"]:
        return "HIGH"
    if top >= c["mediumTop"] and top - second >= c["mediumMargin"]:
        return "MEDIUM"
    return "LOW"


def classify_posture(
    window: CompetitiveWindow,
    timing: SeasonTiming,
    *,
    owns_own_first: bool | None,
) -> PostureResult:
    """Posture from a window, the season clock and own-pick ownership."""
    state_lean = PRIORS["stateLean"]
    lean_raw = sum(
        float(window.probabilities.get(s, 0.0)) * float(state_lean[s]) for s in COMPETITIVE_STATES
    )
    lean = max(-1.0, min(1.0, lean_raw * timing.multiplier))
    temp = float(PRIORS["temperature"])
    scores = {p: -((lean - float(a)) ** 2) / temp for p, a in PRIORS["anchors"].items()}
    aff = _softmax(scores)
    notes: list[str] = list(timing.notes)
    if owns_own_first is False:
        moved = aff["REBUILD"] * float(PRIORS["noOwnFirstRebuildTransfer"])
        aff["REBUILD"] -= moved
        aff["RETOOL"] += moved
        notes.append(
            "does not hold its own next first: losing improves no pick it owns, so "
            "part of the REBUILD affinity moves to RETOOL"
        )
    elif owns_own_first is None:
        notes.append("own-first ownership is unknown; no pick-ownership adjustment applied")
    if window.inputs.competitiveness_source != "championshipOdds":
        notes.append(
            "competitiveness from lineup-strength rank (structural proxy) — no fresh "
            "playoff simulation for this league"
        )
    posture = max(POSTURES, key=lambda p: (aff[p], -POSTURES.index(p)))
    return PostureResult(
        posture=posture,
        affinities={p: aff[p] for p in POSTURES},
        confidence=_confidence(aff),
        lean=lean,
        lean_raw=lean_raw,
        timing=timing,
        owns_own_first=owns_own_first,
        window=window,
        notes=tuple(notes),
    )


# ── Playoff-sim input (consumed, never recomputed) ─────────────────────────


def load_playoff_odds(
    league_key: str | None,
    *,
    last_scored_week: int | None,
    default_key: str | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    """The cached playoff simulation for ``league_key``, IF it is current.

    ``(rows, meta)``.  Rows are returned only when the cache's identity names
    this league AND the same last-scored week the league reports now; anything
    else is ``stale`` (kept out of posture, which falls back to lineup rank and
    says so) — a snapshot proves when it was taken, not that it is still true.
    """
    meta: dict[str, Any] = {"state": "missing", "source": "src/ros/playoff_sim.py cache"}
    try:
        from src.ros.scrape import playoff_sim_path  # noqa: PLC0415

        if default_key is None:
            from src.api.league_registry import default_league_key  # noqa: PLC0415

            default_key = default_league_key()
        playoff_path = playoff_sim_path(league_key, default_key)
    except Exception as exc:  # noqa: BLE001
        meta["state"] = "unavailable"
        meta["reason"] = type(exc).__name__
        return None, meta
    identity_path = playoff_path.with_name(playoff_path.stem + ".identity.json")
    try:
        payload = json.loads(playoff_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, meta
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        identity = {}
    meta["computedAt"] = payload.get("computedAt") if isinstance(payload, dict) else None
    sim_league = identity.get("leagueKey") if isinstance(identity, dict) else None
    sim_week = _int(identity.get("lastScoredWeek")) if isinstance(identity, dict) else None
    meta["simLastScoredWeek"] = sim_week
    meta["leagueLastScoredWeek"] = last_scored_week
    if league_key and sim_league and sim_league != league_key:
        meta["state"] = "stale"
        meta["reason"] = "league_mismatch"
        return None, meta
    if last_scored_week is None or sim_week is None or sim_week != last_scored_week:
        meta["state"] = "stale"
        meta["reason"] = "week_mismatch_or_unverified"
        return None, meta
    rows = payload.get("playoffOdds") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None, meta
    meta["state"] = "fresh"
    return [r for r in rows if isinstance(r, dict)], meta


# ── League-wide build ─────────────────────────────────────────────────────


def _player_meta(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    from src.api.roster_intelligence import _ages  # noqa: PLC0415 — the one age join

    return {name: {"age": age} for name, age in _ages(contract).items() if age is not None}


def _team_index(contract: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    from src.api.data_contract import roster_pool_key  # noqa: PLC0415

    teams = (
        ((contract.get("sleeper") or {}).get("teams")) if isinstance(contract, Mapping) else None
    )
    if not isinstance(teams, list):
        return []
    return [
        (roster_pool_key(teams, i, t), t) for i, t in enumerate(teams) if isinstance(t, Mapping)
    ]


def _odds_for(rows: Sequence[Mapping[str, Any]] | None, key: str) -> dict[str, Any] | None:
    for r in rows or ():
        if str(r.get("ownerId") or "") == key:
            return {
                "playoffOdds": r.get("playoffOdds"),
                "byeOdds": r.get("byeOdds"),
                "championshipOdds": r.get("championshipOdds"),
            }
    return None


def _odds_discriminate(rows: Sequence[Mapping[str, Any]] | None) -> tuple[bool, int]:
    """Whether championship odds can rank this league at all.

    The window places a team by its championship-odds PERCENTILE.  When most
    of the league shares one value (measured 2026-10-03 on ``dynasty_main``:
    eight of twelve teams at exactly 0.0) the percentile ties them and the
    axis carries no information for most teams.  Returns ``(ok, largest_tie)``;
    not ok when the largest tie exceeds a third of the league.
    """
    vals = [
        round(float(r.get("championshipOdds") or 0.0), 4)
        for r in rows or ()
        if isinstance(r, Mapping) and r.get("ownerId")
    ]
    if not vals:
        return False, 0
    largest = max(vals.count(v) for v in set(vals))
    return largest <= max(1, len(vals) // 3), largest


def build_league_postures(
    contract: Mapping[str, Any] | None,
    *,
    league_key: str | None = None,
    playoff_odds: Sequence[Mapping[str, Any]] | None = None,
    odds_meta: Mapping[str, Any] | None = None,
    roster_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Posture for EVERY team in one league (it is league-relative).

    ``playoff_odds`` is supplied by the caller (see :func:`load_playoff_odds`);
    ``None`` means the structural proxy, stamped on every team.
    """
    from src.api.data_contract import contract_roster_pools  # noqa: PLC0415

    contract = contract if isinstance(contract, Mapping) else {}
    pools, slots, slot_source = contract_roster_pools(
        dict(contract), roster_settings=dict(roster_settings) if roster_settings else None
    )
    if not pools or not slots:
        return {
            "version": POSTURE_VERSION,
            "available": False,
            "unavailableReason": "rosters_or_lineup_unresolved",
            "teams": {},
        }
    sleeper = contract.get("sleeper") or {}
    timing = season_timing(sleeper.get("leagueSettings"))
    odds_input = dict(
        odds_meta or {"state": "not_supplied" if playoff_odds is None else "supplied"}
    )
    if playoff_odds is not None:
        ok, largest_tie = _odds_discriminate(playoff_odds)
        if not ok:
            # Kept as season context, never as the ranking axis.
            odds_input["usedForCompetitiveness"] = False
            odds_input["reason"] = (
                f"championship odds tie {largest_tie} teams at one value, so they cannot "
                "rank the league; lineup-strength rank is used instead"
            )
        else:
            odds_input["usedForCompetitiveness"] = True
    window_odds = playoff_odds if odds_input.get("usedForCompetitiveness") else None
    meta = _player_meta(contract)
    lineup_scores = {k: solve_summary(p, slots).score for k, p in pools.items()}
    teams_list = [t for _, t in _team_index(contract)]
    out: dict[str, Any] = {}
    for key, team in _team_index(contract):
        pool = pools.get(key)
        if pool is None:
            continue
        window = compute_window(
            key,
            pool,
            slots,
            playoff_odds=window_odds,
            lineup_scores=lineup_scores,
            player_meta=meta,
        )
        owns, year, own_id = _owns_own_first(team, teams_list)
        result = classify_posture(window, timing, owns_own_first=owns)
        d = result.to_dict()
        d["teamName"] = str(team.get("name") or "")
        d["ownerId"] = str(team.get("ownerId") or "")
        d["components"]["upcomingDraftYear"] = year
        d["components"]["ownFirstAssetId"] = own_id
        d["components"]["seasonOdds"] = _odds_for(playoff_odds, key)
        out[key] = d
    return {
        "version": POSTURE_VERSION,
        "available": True,
        "timing": timing.to_dict(),
        "oddsInput": odds_input,
        "slotSource": slot_source,
        "priors": PRIORS,
        "calibration": dict(_CALIBRATION),
        "teams": out,
    }


# ── Marginal change caused by a trade ─────────────────────────────────────


def _pool_index(pools: Mapping[str, Sequence[RosterPlayer]]) -> dict[str, RosterPlayer]:
    out: dict[str, RosterPlayer] = {}
    for pool in pools.values():
        for p in pool:
            out.setdefault(p.player_id, p)
    return out


def _row_player(contract: Mapping[str, Any], name: str) -> RosterPlayer | None:
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        if name in (row.get("canonicalName"), row.get("displayName")):
            raw = row.get("rankDerivedValue")
            return RosterPlayer(
                player_id=name,
                canonical_name=name,
                position=lineup_position(str(row.get("position") or "")),
                ros_value=None if raw is None else float(raw),
            )
    return None


def posture_marginal(
    contract: Mapping[str, Any] | None,
    team_key: str,
    *,
    players_in: Sequence[str],
    players_out: Sequence[str],
    forced_drops: Sequence[str] = (),
    own_first_after: bool | None = None,
    roster_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Posture before → after this trade, on ONE basis for both states.

    The playoff simulator has no trade counterfactual wired, so the BEFORE
    state here is re-measured on the structural basis (lineup-strength rank)
    too — comparing sim-based "before" with structural "after" would measure
    the change of method, not the trade.  ``forced_drops`` leave the AFTER
    roster: the comparison is on the final LEGAL roster, never the
    intermediate over-limit one.
    """
    from src.api.data_contract import contract_roster_pools  # noqa: PLC0415

    contract = contract if isinstance(contract, Mapping) else {}
    pools, slots, _ = contract_roster_pools(
        dict(contract), roster_settings=dict(roster_settings) if roster_settings else None
    )
    if team_key not in pools or not slots:
        return {"available": False, "unavailableReason": "team_not_in_league_pools"}
    index = _pool_index(pools)
    out_set = {str(n) for n in players_out} | {str(n) for n in forced_drops}
    before_pool = list(pools[team_key])
    after_pool = [p for p in before_pool if p.player_id not in out_set]
    missing: list[str] = []
    for name in players_in:
        p = index.get(str(name)) or _row_player(contract, str(name))
        if p is None:
            missing.append(str(name))
            continue
        after_pool.append(p)
    meta = _player_meta(contract)
    timing = season_timing((contract.get("sleeper") or {}).get("leagueSettings"))
    scores_before = {k: solve_summary(p, slots).score for k, p in pools.items()}
    scores_after = dict(scores_before)
    scores_after[team_key] = solve_summary(after_pool, slots).score
    teams = [t for _, t in _team_index(contract)]
    team = next((t for k, t in _team_index(contract) if k == team_key), {})
    owns_before, _year, _aid = _owns_own_first(team, teams)
    owns_after = owns_before if own_first_after is None else own_first_after
    w_before = compute_window(
        team_key, before_pool, slots, lineup_scores=scores_before, player_meta=meta
    )
    w_after = compute_window(
        team_key, after_pool, slots, lineup_scores=scores_after, player_meta=meta
    )
    p_before = classify_posture(w_before, timing, owns_own_first=owns_before)
    p_after = classify_posture(w_after, timing, owns_own_first=owns_after)
    return {
        "available": True,
        "basis": "structural_lineup_rank",
        "basisNote": (
            "Measured on lineup-strength rank and lineup-entrant age for BOTH states: "
            "the playoff simulator has no trade counterfactual wired, so title-odds "
            "changes are not claimed."
        ),
        "postureBefore": p_before.posture,
        "postureAfter": p_after.posture,
        "leanBefore": round(p_before.lean, 4),
        "leanAfter": round(p_after.lean, 4),
        "leanDelta": round(p_after.lean - p_before.lean, 4),
        "competitivenessBefore": round(w_before.inputs.competitiveness, 4),
        "competitivenessAfter": round(w_after.inputs.competitiveness, 4),
        "trajectoryBefore": round(w_before.inputs.trajectory, 4),
        "trajectoryAfter": round(w_after.inputs.trajectory, 4),
        "lineupStrengthBefore": round(scores_before[team_key], 1),
        "lineupStrengthAfter": round(scores_after[team_key], 1),
        "ownsOwnFirstBefore": owns_before,
        "ownsOwnFirstAfter": owns_after,
        "forcedDropsApplied": sorted({str(n) for n in forced_drops}),
        "unresolvedIncoming": missing,
        "countedAsVote": False,
    }
