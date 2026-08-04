"""BDVM orchestration: contract + projection snapshot → versioned payload.

Reads the live contract READ-ONLY (player universe, ages, market values)
and the latest BDVM projection snapshot; computes fundamentals first,
market comparison strictly afterward; returns one versioned payload and
optionally persists it under ``data/bdvm/valuations/`` (dated files are
immutable; ``latest.json`` is a pointer that is only replaced by a
successful run — a failed run can never clobber last-known-good).

Missing-data behavior (§6.3): players without a usable projection or
without an age are returned in ``unpriced`` with an explicit reason —
never a silent zero, never an invented value.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from dataclasses import replace as _dc_replace

from src.bdvm import MODEL_VERSION
from src.bdvm.actuals import nfl_projection_season
from src.bdvm.context import PlayerContext
from src.bdvm.curves import compute_kappa
from src.bdvm.engine import DynastyEngine, PlayerInput, Valuation
from src.bdvm.events import PlayerEvent, apply_events, load_events_file
from src.bdvm.league_config import LeagueConfigError, from_contract
from src.bdvm.market import buy_hold_sell, market_comparison, market_view_for_row
from src.bdvm.params import ParamSet, load_param_set
from src.bdvm.picks import pick_values_all_strategies
from src.bdvm.pool import build_group_pools
from src.bdvm.projections import (
    ConsensusProjection,
    ProjectionRecord,
    blend_consensus,
    latest_snapshot_path,
    load_snapshot,
)
from src.bdvm.replacement import ReplacementEngine
from src.bdvm.ros import blend_ros_mu, ros_projection_weight, ros_value
from src.bdvm.scoring import is_idp_position
from src.bdvm.survival import RiskProfile
from src.utils.name_clean import normalize_player_name


def replace_risk(risk: RiskProfile, **fields: float) -> RiskProfile:
    """Frozen-dataclass update helper for context-driven risk fields."""
    return _dc_replace(risk, **fields)


REPO_ROOT = Path(__file__).resolve().parents[2]
VALUATION_DIR = REPO_ROOT / "data" / "bdvm" / "valuations"

_TRUE_POSITIONS_KNOWN = frozenset({"QB", "RB", "WR", "TE", "DT", "EDGE", "CB", "S", "LB"})
_UNSUPPORTED_POSITIONS = frozenset({"K", "PK", "DEF", "DST"})
_IDP_GROUPS = frozenset({"DL", "LB", "DB"})

# Provisional event-volatility priors by modelling position (documented
# judgment call: no per-player TD/sack/INT-dependence data is wired yet).
_EVENT_VOL_PRIOR = {
    "CB": 0.70,
    "EDGE": 0.55,
    "DT": 0.50,
    "S": 0.35,
    "LB": 0.20,
    "QB": 0.25,
    "RB": 0.35,
    "WR": 0.30,
    "TE": 0.35,
}

# Accepts both the bare "2026 1.04" form and the platform's canonical
# slot-pick displayName "2026 Pick 1.04" — the exact string the trade
# page and /api/data rows carry.  Without the optional token every
# canonical slot pick fell through to unparseable_pick_name and the
# whole current-year pick board (and any trade-eval ref to it) was
# unpriced.
_PICK_SLOT_RE = re.compile(
    r"(?P<year>20\d{2})\s+(?:pick\s+)?(?P<round>\d)\.(?P<slot>\d{1,2})", re.IGNORECASE
)
_PICK_TIER_RE = re.compile(
    r"(?P<year>20\d{2})\s+(?P<tier>Early|Mid|Late)\s+(?P<round>1st|2nd|3rd|4th)", re.IGNORECASE
)
_TIER_FRACTION = {"early": 0.21, "mid": 0.50, "late": 0.83}
_ROUND_WORD = {"1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Player-input assembly
# ---------------------------------------------------------------------------


def _risk_profile_for_row(
    row: Mapping[str, Any],
    modelling_pos: str,
    production_z: float,
    *,
    any_proxy: bool,
) -> RiskProfile:
    rookie = bool(row.get("rookie"))
    years_exp = row.get("yearsExp")
    years = int(years_exp) if isinstance(years_exp, (int, float)) else None
    role_uncertainty = 0.25
    small_sample = 0.0
    if rookie or years == 0:
        role_uncertainty, small_sample = 0.55, 1.0
    elif years == 1:
        role_uncertainty, small_sample = 0.35, 0.5
    if any_proxy:
        role_uncertainty = min(1.0, role_uncertainty + 0.10)
    return RiskProfile(
        role_security=0.55 if (rookie or years == 0) else 0.6,
        draft_capital=0.5,  # neutral: no draft-capital feed wired yet
        contract_security=0.6,  # neutral: contract feed (playerctx) not wired
        durability=0.6,  # neutral: injury-history feed not wired
        production_z=production_z,
        scheme_stability=0.6,
        role_uncertainty=role_uncertainty,
        event_volatility=_EVENT_VOL_PRIOR.get(modelling_pos, 0.30),
        small_sample=small_sample,
        designation_risk=0.0,  # no eligibility-scenario feed yet
    )


def _nfl_season_for_row(row: Mapping[str, Any]) -> tuple[int, bool]:
    """(nfl_season with 1 = rookie year, known?)"""
    years_exp = row.get("yearsExp")
    if isinstance(years_exp, (int, float)):
        return max(1, int(years_exp) + 1), True
    return (1, False) if row.get("rookie") else (3, False)


def _ros_for_player(
    v: Valuation,
    blended: ConsensusProjection,
    row: Mapping[str, Any],
    *,
    schedule_weeks: Mapping[str, list] | None,
    params: ParamSet,
    current_week: int | None = None,
    played_weeks: set[int] | None = None,
) -> dict[str, Any] | None:
    """Rest-of-season value (single horizon, no aging/survival).

    Requires the league schedule (byes) for the player's NFL team; when
    unavailable the field is None with no fabrication.  Preseason
    (``current_week`` None) sums the full slate and µ_ROS is the
    blended projection itself; in-season, ``blended`` already carries
    the §8.4 posterior and played weeks are banked points, not
    remaining value.

    Boundary week: ``current_week`` is global (max week observed
    league-wide + 1), but nflverse publishes game-by-game — after
    Thursday night the file already holds week-W rows while ~30 teams
    haven't played W yet.  For THIS player, week W counts as remaining
    unless it appears in ``played_weeks`` — otherwise one real week of
    value would vanish league-wide for three days every week.
    """
    if not schedule_weeks:
        return None
    team = str(row.get("team") or "").upper()
    weeks = schedule_weeks.get(team)
    if not weeks:
        return {"value": None, "reason": f"no_schedule_for_team:{team or 'FA'}"}
    if current_week is not None:
        boundary = current_week - 1
        played = played_weeks or set()
        weeks = [
            wk
            for wk in weeks
            if wk.week >= current_week or (wk.week == boundary and boundary not in played)
        ]
    sigma0 = v.seasons[0]["sigma"]
    replacement = v.raw["replacement"]
    out: dict[str, Any] = {"muRos": round(blended.mu_fpg, 3), "weeks": len(weeks)}
    for strategy in params.strategy_names():
        pw = float(params.strategy(strategy).get("playoff_weight", 0.0))
        out[strategy] = round(
            ros_value(blended.mu_fpg, sigma0, replacement, weeks, playoff_weight=pw), 1
        )
    return out


def _parse_pick_slot(display_name: str, teams: int) -> tuple[int, int] | None:
    """(overall_slot, pick_year) for a pick asset name, else None."""
    m = _PICK_SLOT_RE.search(display_name or "")
    if m:
        rnd, slot = int(m.group("round")), int(m.group("slot"))
        if rnd >= 1 and 1 <= slot <= teams:
            return (rnd - 1) * teams + slot, int(m.group("year"))
    m = _PICK_TIER_RE.search(display_name or "")
    if m:
        rnd = _ROUND_WORD[m.group("round").lower()]
        frac = _TIER_FRACTION[m.group("tier").lower()]
        slot = max(1, min(teams, round(frac * teams)))
        return (rnd - 1) * teams + slot, int(m.group("year"))
    return None


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


def run_valuation(
    contract: Mapping[str, Any],
    *,
    league_key: str,
    params: ParamSet | None = None,
    registry_roster_settings: Mapping[str, Any] | None = None,
    idp_enabled: bool = True,
    scoring_profile: str = "",
    projection_records: Iterable[ProjectionRecord] | None = None,
    snapshot_as_of: str | None = None,
    season: int | None = None,
    surplus_mode: str = "option",
    write_snapshot_files: bool = False,
    context: Mapping[str, "PlayerContext"] | None = None,
    events: Iterable["PlayerEvent"] | None = None,
    schedule_weeks: Mapping[str, list] | None = None,
    actuals: tuple[int | None, Mapping[str, list]] | None = None,
) -> dict[str, Any]:
    """Compute BDVM fundamental values for every priceable asset.

    ``projection_records`` overrides snapshot loading (tests, ad-hoc
    runs); otherwise the latest snapshot for ``season`` is used.  When
    no projections exist at all the payload reports
    ``status="no_projection_snapshot"`` — the engine refuses to invent
    a fundamental board out of nothing.

    ``context`` (age / draft capital / career load per player_key,
    ``src.bdvm.context``) enriches inputs when the contract row lacks
    them; ``events`` are structured §7 events (auto-loaded from
    ``data/bdvm/events/<season>.json`` when None); ``schedule_weeks``
    maps NFL team → RosWeek list for the ROS output.

    ``actuals`` is the in-season evidence feed:
    ``(current_week, player_key → [(week, points), ...])`` from
    ``src.bdvm.actuals``.  When present, each covered player's
    consensus is replaced by the §8.4 posterior — the preseason µ
    shrinks toward realized per-game production with weight
    ``n_prior/(n_prior + weeks_played)`` (``blend_ros_mu``), σ shrinks
    by the same evidence factor, and ROS sums only the REMAINING
    weeks.  ``(None, {})`` or omitted → exact preseason behavior.
    """
    params = params or load_param_set()
    as_of = _utc_now_iso()
    # ``season`` is the NFL SEASON these projections describe — the
    # snapshot to load, the events file to read, the season ages and
    # nfl_season are measured at, and the season the §8.4 actuals
    # posterior blends into.  It is NOT the contract's
    # ``currentDraftYear``, which is the upcoming ROOKIE-DRAFT year and
    # rolls to calendar+1 in May: from then through January the two name
    # different seasons, and using the draft year would have looked up
    # next season's (nonexistent) snapshot while blending this season's
    # realized points into it.  Both are stamped in meta.
    season = int(season) if season is not None else nfl_projection_season()
    rookie_draft_year = contract.get("currentDraftYear")
    try:
        rookie_draft_year = int(rookie_draft_year) if rookie_draft_year is not None else None
    except (TypeError, ValueError):
        rookie_draft_year = None

    waiver_cfg = params["replacement"]
    cfg = from_contract(
        contract,
        league_key=league_key,
        registry_roster_settings=registry_roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        waiver_buffer=waiver_cfg["waiver_buffer"],
        default_buffer=float(waiver_cfg["default_buffer"]),
    )

    meta: dict[str, Any] = {
        "modelVersion": MODEL_VERSION,
        **params.to_meta(),
        "leagueKey": league_key,
        "scoringProfile": scoring_profile,
        "configHash": cfg.config_hash,
        "configSource": cfg.source,
        "asOf": as_of,
        "season": season,  # NFL season the projections describe
        "rookieDraftYear": rookie_draft_year,  # contract's upcoming rookie draft
        "surplusMode": surplus_mode,
        "contractGeneratedAt": contract.get("generatedAt"),
        "marketReadAfterFundamental": True,
    }

    # ---- projections -----------------------------------------------------
    snapshot_path: Path | None = None
    if projection_records is None:
        snapshot_path = latest_snapshot_path(season)
        if snapshot_path is None:
            return {
                "status": "no_projection_snapshot",
                "meta": {**meta, "projectionSnapshot": None},
                "message": (
                    "BDVM has no projection snapshot for season "
                    f"{season}. Drop projection CSVs under data/bdvm/projections/manual/ "
                    "and build a snapshot, or generate the reconstructed baseline. "
                    "The fundamental engine does not fabricate projections."
                ),
                "players": [],
                "picks": [],
                "unpriced": [],
                "replacement": {},
            }
        snap_as_of, records = load_snapshot(snapshot_path)
        snapshot_as_of = snapshot_as_of or snap_as_of
    else:
        records = list(projection_records)
    snapshot_as_of = snapshot_as_of or as_of[:10]
    meta["projectionSnapshot"] = {
        "path": str(snapshot_path) if snapshot_path else None,
        "asOf": snapshot_as_of,
        "recordCount": len(records),
    }

    # ---- structured events (§7) -------------------------------------------
    if events is None:
        events = load_events_file(season)
    events_by_player: dict[str, list[PlayerEvent]] = {}
    for ev in events:
        events_by_player.setdefault(ev.player_key, []).append(ev)
    meta["eventCount"] = sum(len(v) for v in events_by_player.values())

    context = context or {}

    by_player: dict[str, list[ProjectionRecord]] = {}
    for r in records:
        by_player.setdefault(r.player_key, []).append(r)
    consensus: dict[str, ConsensusProjection] = {}
    for key, recs in by_player.items():
        blended = blend_consensus(
            recs,
            scoring_settings=cfg.scoring_settings,
            snapshot_as_of=snapshot_as_of,
            params=params,
        )
        if blended is not None:
            consensus[key] = blended

    # ---- in-season posterior update (§8.4) ---------------------------------
    # ONE mutation point, BEFORE pools/replacement: replacement levels,
    # group z-stats, engine µ/σ, and ROS all read from ``consensus``,
    # so updating here keeps every downstream number on the same
    # posterior.  µ shrinks toward realized production with weight
    # n_prior/(n_prior + weeks_played); σ shrinks by the same evidence
    # factor (more observed games → less cross-source uncertainty).
    # Players without observed weeks keep the preseason consensus
    # untouched — absence of evidence is never evidence of zero.
    current_week: int | None = None
    inseason_updated = 0
    # Per-player played weeks, for the ROS boundary-week rule (a week
    # some teams have played and others haven't is remaining for the
    # teams that haven't).
    actuals_played: dict[str, set[int]] = {}
    if actuals is not None:
        current_week, weekly_by_key = actuals
        if current_week is not None and weekly_by_key:
            actuals_played = {
                key: {wk for wk, _pts in samples} for key, samples in weekly_by_key.items()
            }
            for key, blended in list(consensus.items()):
                samples = weekly_by_key.get(key)
                if not samples:
                    continue
                weeks_played = float(len(samples))
                mu_recent = sum(pts for _wk, pts in samples) / weeks_played
                is_idp = is_idp_position(blended.position)
                mu_post = blend_ros_mu(
                    blended.mu_fpg,
                    mu_recent,
                    weeks_played,
                    is_idp=is_idp,
                    params=params,
                )
                w_prior = ros_projection_weight(weeks_played, is_idp=is_idp, params=params)
                sigma_post = blended.sigma_source * math.sqrt(w_prior)
                consensus[key] = _dc_replace(blended, mu_fpg=mu_post, sigma_source=sigma_post)
                inseason_updated += 1
    meta["inSeason"] = (
        {
            "currentWeek": current_week,
            "playersUpdated": inseason_updated,
            "source": "nflverse stats_player_week",
        }
        if current_week is not None
        else {"active": False}
    )

    # ---- pools + replacement (from projections only) ----------------------
    pools = build_group_pools(consensus.values(), cfg)
    repl = ReplacementEngine(cfg, pools)

    # ---- assemble player inputs -------------------------------------------
    rows = contract.get("playersArray") or []
    unpriced: list[dict[str, Any]] = []
    inputs: list[tuple[PlayerInput, Mapping[str, Any], ConsensusProjection]] = []
    extras_by_key: dict[str, dict[str, Any]] = {}

    # production z-scores by group over consensus FPG
    group_stats: dict[str, tuple[float, float]] = {}
    by_group_fpg: dict[str, list[float]] = {}
    for c in consensus.values():
        try:
            by_group_fpg.setdefault(cfg.group(c.position), []).append(c.mu_fpg)
        except LeagueConfigError:
            continue
    for g, vals in by_group_fpg.items():
        mean = statistics.fmean(vals)
        stdev = statistics.pstdev(vals) if len(vals) > 1 else 1.0
        group_stats[g] = (mean, stdev if stdev > 1e-9 else 1.0)

    pick_rows: list[Mapping[str, Any]] = []
    for row in rows:
        if row.get("quarantined"):
            continue
        asset_class = row.get("assetClass")
        if asset_class == "pick":
            pick_rows.append(row)
            continue
        display = row.get("displayName") or row.get("canonicalName") or ""
        # Contract canonicalName is the raw display name; projections and
        # events key on the normalized form — normalize before joining.
        name_key = normalize_player_name(str(row.get("canonicalName") or display))
        position = str(row.get("position") or "").upper()
        if not position or position in _UNSUPPORTED_POSITIONS:
            unpriced.append(
                {"name": display, "reason": "unsupported_position", "position": position}
            )
            continue
        if not idp_enabled and position in _IDP_GROUPS:
            unpriced.append(
                {"name": display, "reason": "idp_disabled_in_league", "position": position}
            )
            continue
        blended = consensus.get(name_key)
        if blended is None:
            unpriced.append({"name": display, "reason": "no_projection", "position": position})
            continue
        ctx = context.get(name_key)
        age = row.get("age")
        age_source = "contract"
        try:
            age_f = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_f = None
        if (age_f is None or age_f <= 0) and ctx is not None:
            age_f = ctx.age_at_season_start(season)
            age_source = "nflverse_birth_date"
        if age_f is None or age_f <= 0:
            unpriced.append({"name": display, "reason": "missing_age", "position": position})
            continue

        # Prefer the projection source's position when it is a true
        # position and the contract only has the platform group; the
        # nflverse listing is the next-best signal.
        pos_for_model = blended.position.upper()
        if pos_for_model not in _TRUE_POSITIONS_KNOWN and ctx is not None and ctx.true_position:
            pos_for_model = ctx.true_position
        if pos_for_model not in _TRUE_POSITIONS_KNOWN:
            pos_for_model = position
        true_known = pos_for_model in _TRUE_POSITIONS_KNOWN
        modelling_pos = params.modelling_position(pos_for_model)

        nfl_season, _season_known = _nfl_season_for_row(row)
        if ctx is not None:
            ctx_season = ctx.nfl_season_for(season)
            if ctx_season is not None:
                nfl_season = ctx_season
        try:
            grp = cfg.group(pos_for_model)
        except LeagueConfigError:
            unpriced.append({"name": display, "reason": "no_lineup_group", "position": position})
            continue
        if not repl.has_replacement(grp):
            # No measurable replacement level for this group (no projected
            # pool, or a replacement rank past the end of one).  R is the
            # ORIGIN of the value scale, so pricing this player anyway
            # would hand back his entire FPG as surplus in a payload that
            # looks exactly like a real one — §6.3 says say so instead.
            unpriced.append(
                {"name": display, "reason": "no_replacement_level", "position": position}
            )
            continue
        mean, stdev = group_stats.get(grp, (blended.mu_fpg, 1.0))
        production_z = max(-2.0, min(2.0, (blended.mu_fpg - mean) / stdev))
        risk = _risk_profile_for_row(row, modelling_pos, production_z, any_proxy=blended.any_proxy)
        career_load = 0.0
        dc_score = 0.0
        if ctx is not None:
            mileage = params.mileage(modelling_pos)
            if mileage is not None:
                career_load = ctx.career_load_for(mileage[0])
            dc_score = ctx.draft_capital_score
            risk_updates: dict[str, float] = {}
            if dc_score > 0.0:
                risk_updates["draft_capital"] = dc_score
            if ctx.position_ambiguous and grp in _IDP_GROUPS:
                risk_updates["designation_risk"] = max(risk.designation_risk, 0.30)
            if risk_updates:
                risk = replace_risk(risk, **risk_updates)
        kappa = compute_kappa(
            params,
            nfl_season=nfl_season,
            draft_capital_score=dc_score,
            college_score=0.0,  # no college feed yet — documented
            opportunity_score=0.0,  # no opportunity feed yet — documented
            incumbency=0.0,
        )
        p_in = PlayerInput(
            player_id=str(row.get("playerId") or name_key),
            name=display,
            position=pos_for_model,
            age=age_f,
            nfl_season=nfl_season,
            fpg=blended.mu_fpg,
            games=blended.games,
            sigma_source=blended.sigma_source,
            career_load=career_load,
            kappa=kappa,
            risk=risk,
            true_position_known=true_known,
            n_sources=blended.n_sources,
            any_proxy=blended.any_proxy,
            stale_source_count=len(blended.stale_sources),
        )
        event_audit: list[dict[str, Any]] = []
        evts = events_by_player.get(name_key)
        if evts:
            p_in, event_audit = apply_events(p_in, evts, as_of=snapshot_as_of)
        extras_by_key[name_key] = {
            "ageSource": age_source,
            "careerLoad": round(career_load, 1),
            "draftCapitalScore": round(dc_score, 3),
            "draftOverall": ctx.draft_overall if ctx is not None else None,
            "eventAudit": event_audit,
        }
        inputs.append((p_in, row, blended))

    # ---- fundamentals FIRST -----------------------------------------------
    engine = DynastyEngine(cfg, repl, params, pools=pools, surplus_mode=surplus_mode)
    engine.calibrate([p for p, _, _ in inputs])
    valuations: list[tuple[Valuation, Mapping[str, Any], ConsensusProjection, PlayerInput]] = [
        (engine.value(p), row, blended, p) for p, row, blended in inputs
    ]

    # dynasty 0-100 percentile score on balanced trade value
    balanced_sorted = sorted(v.trade_value.get("balanced", 0.0) for v, _, _, _ in valuations)
    n_priced = len(balanced_sorted)

    def _pct(v: float) -> float:
        if n_priced <= 1:
            return 100.0
        import bisect  # noqa: PLC0415

        return 100.0 * bisect.bisect_left(balanced_sorted, v) / (n_priced - 1)

    # ---- market layer SECOND ----------------------------------------------
    players_out: list[dict[str, Any]] = []
    for v, row, blended, p_in in valuations:
        view = market_view_for_row(row, v.group, params)
        market_out = market_comparison(
            v.trade_value,
            view,
            params,
            is_idp=v.group in _IDP_GROUPS,
            is_rookie=p_in.nfl_season <= 1,
            small_sample=p_in.risk.small_sample,
        )
        signal = buy_hold_sell(market_out, params, p_collapse_1y=v.probs.get("p_value_collapse_1y"))
        entry = v.to_dict()
        entry.update(
            {
                "projection": {
                    "fpg": round(blended.mu_fpg, 3),
                    "games": round(blended.games, 2),
                    "sigmaSource": round(blended.sigma_source, 3),
                    "sourceCount": blended.n_sources,
                    "sources": list(blended.sources),
                    "anyProxy": blended.any_proxy,
                    "staleSources": list(blended.stale_sources),
                    "vocabularyLimitedSources": list(blended.vocabulary_limited),
                },
                "replacement": {
                    "group": v.group,
                    "fpg": round(v.raw["replacement"], 3),
                    "method": "dynamic_vorp",
                },
                "market": market_out,
                "signal": signal,
                "dynastyScore0to100": round(_pct(v.trade_value.get("balanced", 0.0)), 1),
            }
        )
        extras = extras_by_key.get(
            normalize_player_name(str(row.get("canonicalName") or row.get("displayName") or "")),
            {},
        )
        entry["context"] = {
            "ageSource": extras.get("ageSource"),
            "careerLoad": extras.get("careerLoad", 0.0),
            "draftCapitalScore": extras.get("draftCapitalScore", 0.0),
            "draftOverall": extras.get("draftOverall"),
        }
        entry["events"] = extras.get("eventAudit", [])
        entry["ros"] = _ros_for_player(
            v,
            blended,
            row,
            schedule_weeks=schedule_weeks,
            params=params,
            current_week=current_week,
            played_weeks=actuals_played.get(
                normalize_player_name(str(row.get("canonicalName") or row.get("displayName") or ""))
            ),
        )
        players_out.append(entry)

    # ---- picks (distributions, market-anchored) ----------------------------
    picks_out: list[dict[str, Any]] = []
    for row in pick_rows:
        display = row.get("displayName") or row.get("canonicalName") or ""
        parsed = _parse_pick_slot(str(display), cfg.teams)
        view = market_view_for_row(row, "PICK", params)
        entry: dict[str, Any] = {
            "name": display,
            "assetClass": "pick",
            "market": {
                "marketValue": view.market_value,
                "marketSource": view.market_source,
                "liquidity": round(view.liquidity, 4),
            },
        }
        if parsed is not None:
            overall_slot, pick_year = parsed
            # Measured against the NFL SEASON, not the rookie-draft year:
            # a 2027 pick's class plays the 2027 season, so during the
            # 2026 season it is one season of discounting away.  (The two
            # agree before the draft-year roll and diverge after it.)
            years_out = max(0, pick_year - season)
            entry.update(
                {
                    "overallSlot": overall_slot,
                    "pickYear": pick_year,
                    "yearsOut": years_out,
                    "distribution": pick_values_all_strategies(
                        overall_slot, params, years_out=years_out
                    ),
                }
            )
        else:
            entry["distribution"] = None
            entry["reason"] = "unparseable_pick_name"
        picks_out.append(entry)

    unpriced_counts: dict[str, int] = {}
    for u in unpriced:
        unpriced_counts[u["reason"]] = unpriced_counts.get(u["reason"], 0) + 1

    payload: dict[str, Any] = {
        "status": "ok",
        "meta": {
            **meta,
            "counts": {
                "contractPlayers": sum(1 for r in rows if r.get("assetClass") != "pick"),
                "priced": n_priced,
                "unpriced": len(unpriced),
                "unpricedByReason": unpriced_counts,
                "picks": len(picks_out),
                "projectionPlayers": len(consensus),
                "contextEnriched": sum(
                    1
                    for e in extras_by_key.values()
                    if e.get("ageSource") != "contract"
                    or e.get("draftCapitalScore")
                    or e.get("careerLoad")
                ),
                "eventsApplied": sum(
                    1
                    for e in extras_by_key.values()
                    for a in e.get("eventAudit", [])
                    if a.get("applied")
                ),
            },
        },
        "replacement": repl.to_dict(),
        "players": players_out,
        "picks": picks_out,
        "unpriced": unpriced,
    }

    if write_snapshot_files:
        _persist_valuation(payload, league_key=league_key, as_of=as_of)

    return payload


def _persist_valuation(payload: Mapping[str, Any], *, league_key: str, as_of: str) -> Path:
    """Write the dated valuation file (immutable) + refresh latest.json."""
    root = VALUATION_DIR / league_key
    root.mkdir(parents=True, exist_ok=True)
    stamp = as_of.replace(":", "").replace("-", "")[:15]
    dated = root / f"bdvm_valuation_{stamp}.json"
    counter = 1
    while dated.exists():
        dated = root / f"bdvm_valuation_{stamp}_{counter}.json"
        counter += 1
    blob = json.dumps(payload, indent=1)
    dated.write_text(blob, encoding="utf-8")
    # latest.json is refreshed only after the dated write succeeded, so a
    # failed run can never destroy the last-known-good pointer.
    (root / "latest.json").write_text(blob, encoding="utf-8")
    return dated
