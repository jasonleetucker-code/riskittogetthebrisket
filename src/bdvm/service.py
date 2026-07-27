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
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.bdvm import MODEL_VERSION
from src.bdvm.curves import compute_kappa
from src.bdvm.engine import DynastyEngine, PlayerInput, Valuation
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
from src.bdvm.survival import RiskProfile

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

_PICK_SLOT_RE = re.compile(r"(?P<year>20\d{2})\s+(?P<round>\d)\.(?P<slot>\d{2})")
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
) -> dict[str, Any]:
    """Compute BDVM fundamental values for every priceable asset.

    ``projection_records`` overrides snapshot loading (tests, ad-hoc
    runs); otherwise the latest snapshot for ``season`` is used.  When
    no projections exist at all the payload reports
    ``status="no_projection_snapshot"`` — the engine refuses to invent
    a fundamental board out of nothing.
    """
    params = params or load_param_set()
    as_of = _utc_now_iso()
    season = int(season or contract.get("currentDraftYear") or datetime.now(timezone.utc).year)

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
        "season": season,
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

    # ---- pools + replacement (from projections only) ----------------------
    pools = build_group_pools(consensus.values(), cfg)
    repl = ReplacementEngine(cfg, pools)

    # ---- assemble player inputs -------------------------------------------
    rows = contract.get("playersArray") or []
    unpriced: list[dict[str, Any]] = []
    inputs: list[tuple[PlayerInput, Mapping[str, Any], ConsensusProjection]] = []

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
        name_key = row.get("canonicalName") or ""
        display = row.get("displayName") or name_key
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
        age = row.get("age")
        try:
            age_f = float(age) if age is not None else None
        except (TypeError, ValueError):
            age_f = None
        if age_f is None or age_f <= 0:
            unpriced.append({"name": display, "reason": "missing_age", "position": position})
            continue

        # Prefer the projection source's position when it is a true
        # position and the contract only has the platform group.
        pos_for_model = blended.position.upper()
        if pos_for_model not in _TRUE_POSITIONS_KNOWN:
            pos_for_model = position
        true_known = pos_for_model in _TRUE_POSITIONS_KNOWN
        modelling_pos = params.modelling_position(pos_for_model)

        nfl_season, _season_known = _nfl_season_for_row(row)
        try:
            grp = cfg.group(pos_for_model)
        except LeagueConfigError:
            unpriced.append({"name": display, "reason": "no_lineup_group", "position": position})
            continue
        mean, stdev = group_stats.get(grp, (blended.mu_fpg, 1.0))
        production_z = max(-2.0, min(2.0, (blended.mu_fpg - mean) / stdev))
        risk = _risk_profile_for_row(row, modelling_pos, production_z, any_proxy=blended.any_proxy)
        kappa = compute_kappa(
            params,
            nfl_season=nfl_season,
            draft_capital_score=0.0,  # no feed yet — documented
            college_score=0.0,
            opportunity_score=0.0,
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
            career_load=0.0,  # career-load feed not wired; mileage inert
            kappa=kappa,
            risk=risk,
            true_position_known=true_known,
            n_sources=blended.n_sources,
            any_proxy=blended.any_proxy,
            stale_source_count=len(blended.stale_sources),
        )
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
