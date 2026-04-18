from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Dict, Iterable, Optional, Tuple

import requests

from .types import ScoringConfig


SLEEPER_API_ROOT = "https://api.sleeper.app/v1"
SLEEPER_SCORING_VERSION = "sleeper-normalized-v2-2026-03-09"


KEY_ALIASES: Dict[str, str] = {
    "pass_yd": "pass_yd",
    "pass_td": "pass_td",
    "pass_int": "pass_int",
    "pass_cmp": "pass_cmp",
    "pass_inc": "pass_inc",
    "pass_fd": "pass_fd",
    "rush_yd": "rush_yd",
    "rush_td": "rush_td",
    "rush_fd": "rush_fd",
    "rec": "rec",
    "rec_yd": "rec_yd",
    "rec_td": "rec_td",
    "rec_fd": "rec_fd",
    "bonus_rec_rb": "bonus_rec_rb",
    "bonus_rec_wr": "bonus_rec_wr",
    "bonus_rec_te": "bonus_rec_te",
    "bonus_fd_qb": "bonus_fd_qb",
    "bonus_fd_rb": "bonus_fd_rb",
    "bonus_fd_wr": "bonus_fd_wr",
    "bonus_fd_te": "bonus_fd_te",
    "fum": "fum",
    "fum_lost": "fum_lost",
    "bonus_pass_yd_300": "bonus_pass_yd_300",
    "bonus_rush_yd_100": "bonus_rush_yd_100",
    "bonus_rec_yd_100": "bonus_rec_yd_100",
    "bonus_pass_td_50+": "bonus_pass_td_50+",
    "bonus_rush_td_40+": "bonus_rush_td_40+",
    "bonus_rec_td_40+": "bonus_rec_td_40+",
    "kick_ret_td": "kick_ret_td",
    "punt_ret_td": "punt_ret_td",
    "idp_tkl_solo": "idp_tkl_solo",
    "idp_solo": "idp_tkl_solo",
    "idp_tkl_ast": "idp_tkl_ast",
    "idp_ast": "idp_tkl_ast",
    # Combined tackle stat — some Sleeper leagues score "Tackle" as a
    # single line item instead of splitting solo/assisted. Map to a
    # dedicated canonical so the calibration layer can treat it as a
    # blended stat rather than double-counting solo.
    "idp_tkl": "idp_tkl",
    "idp_tkl_loss": "idp_tkl_loss",
    "idp_tfl": "idp_tkl_loss",
    "idp_tkl_ast_loss": "idp_tkl_ast_loss",
    "idp_sack": "idp_sack",
    "idp_sack_yd": "idp_sack_yd",
    # QB hit — Sleeper UIs label this "Hit on QB". Keep the canonical
    # key as ``idp_hit`` so baseline_config / scoring_delta (which
    # consume this normalized map) continue to find it unchanged;
    # newer Sleeper payloads that use ``idp_qb_hit`` fold into the
    # same canonical.
    "idp_hit": "idp_hit",
    "idp_qb_hit": "idp_hit",
    "idp_int": "idp_int",
    "idp_int_ret_yd": "idp_int_ret_yd",
    "idp_pd": "idp_pd",
    "idp_pass_def": "idp_pd",
    # "Pass Defended — 3+ players" variant; rare. Kept as its own
    # canonical rather than folded into idp_pd so leagues that set
    # distinct weights for each don't double-count.
    "idp_pass_def_3p": "idp_pass_def_3p",
    "idp_ff": "idp_ff",
    "idp_fum_rec": "idp_fum_rec",
    "idp_fr": "idp_fum_rec",
    "idp_fum_ret_yd": "idp_fum_ret_yd",
    # Defensive touchdowns — older Sleeper leagues use `idp_td`, newer
    # ones `idp_def_td`. Both flow to the same canonical.
    "idp_def_td": "idp_def_td",
    "idp_td": "idp_def_td",
    "idp_safe": "idp_safe",
    "idp_blk_kick": "idp_blk_kick",
    "idp_blk_punt": "idp_blk_kick",
    # Tackle volume bonuses (some leagues reward high-tackle performances).
    "idp_tkl_10p": "idp_tkl_10p",
    "idp_tkl_5p": "idp_tkl_5p",
    "idp_def_pr_td": "idp_def_pr_td",
    "idp_def_kr_td": "idp_def_kr_td",
}


def _to_float(value, default: Optional[float] = 0.0) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return default


def fetch_league(league_id: str, timeout: int = 12, session: Optional[requests.Session] = None) -> Optional[Dict[str, object]]:
    if not league_id:
        return None
    http = session or requests
    try:
        resp = http.get(f"{SLEEPER_API_ROOT}/league/{league_id}", timeout=timeout)
        if not resp.ok:
            return None
        payload = resp.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def extract_scoring_settings(league_json: Optional[Dict[str, object]]) -> Dict[str, float]:
    if not isinstance(league_json, dict):
        return {}
    scoring_raw = league_json.get("scoring_settings")
    if not isinstance(scoring_raw, dict):
        return {}
    out: Dict[str, float] = {}
    for raw_key, raw_val in scoring_raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        fv = _to_float(raw_val, None)
        if fv is None:
            continue
        out[key] = float(fv)
    return out


def normalize_scoring_settings(
    raw_scoring_settings: Dict[str, float],
    roster_positions: Optional[Iterable[str]] = None,
    *,
    league_id: str = "",
    season: Optional[int] = None,
    scoring_version: str = SLEEPER_SCORING_VERSION,
) -> ScoringConfig:
    normalized: Dict[str, float] = {}
    unknown: Dict[str, float] = {}

    if not isinstance(raw_scoring_settings, dict):
        raw_scoring_settings = {}

    for raw_key, raw_val in raw_scoring_settings.items():
        k = str(raw_key or "").strip()
        if not k:
            continue
        fv = _to_float(raw_val, None)
        if fv is None:
            continue
        canonical = KEY_ALIASES.get(k)
        if canonical:
            normalized[canonical] = float(fv)
        else:
            # Unknown Sleeper key is preserved in metadata for diagnostics.
            unknown[k] = float(fv)

    # Ensure deterministic key presence for downstream feature logic.
    for canonical_key in sorted(set(KEY_ALIASES.values())):
        normalized.setdefault(canonical_key, 0.0)

    rp = [str(p).strip() for p in (roster_positions or []) if str(p).strip()]
    return ScoringConfig(
        scoring_version=scoring_version,
        league_id=str(league_id or ""),
        season=season,
        roster_positions=rp,
        scoring_map=normalized,
        metadata={
            "unknownSleeperKeys": unknown,
            "unknownSleeperKeyCount": len(unknown),
            "normalizedAtUtc": datetime.now(timezone.utc).isoformat(),
        },
    )


def persist_scoring_config(path: str, config: ScoringConfig) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)


def build_league_scoring_config(league_id: str, timeout: int = 12, session: Optional[requests.Session] = None) -> Tuple[Optional[ScoringConfig], Optional[Dict[str, object]]]:
    league = fetch_league(league_id, timeout=timeout, session=session)
    if not isinstance(league, dict):
        return None, None
    raw_scoring = extract_scoring_settings(league)
    season = None
    try:
        season = int(str(league.get("season") or "").strip())
    except Exception:
        season = None
    config = normalize_scoring_settings(
        raw_scoring,
        league.get("roster_positions") or [],
        league_id=str(league_id),
        season=season,
    )
    return config, league

