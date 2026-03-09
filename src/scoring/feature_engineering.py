from __future__ import annotations

from typing import Dict


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def compute_profile_features(
    bucket: str,
    stats_per_game: Dict[str, float],
    *,
    total_games: int,
    recent_games: int,
    depth_factor: float,
    role_change: bool,
) -> Dict[str, float]:
    s = stats_per_game or {}
    p = str(bucket or "").upper()

    pass_yd = _f(s.get("pass_yd"))
    pass_td = _f(s.get("pass_td"))
    pass_int = _f(s.get("pass_int"))
    rush_yd = _f(s.get("rush_yd"))
    rush_td = _f(s.get("rush_td"))
    rec = _f(s.get("rec"))
    rec_yd = _f(s.get("rec_yd"))
    rec_td = _f(s.get("rec_td"))
    rush_fd = _f(s.get("rush_fd"))
    rec_fd = _f(s.get("rec_fd"))

    total_td = pass_td + rush_td + rec_td
    total_yd = pass_yd + rush_yd + rec_yd
    explosive_proxy = (_f(s.get("bonus_pass_td_50+")) + _f(s.get("bonus_rush_td_40+")) + _f(s.get("bonus_rec_td_40+")))

    f = {
        "games_played": float(max(0, total_games)),
        "recent_games": float(max(0, recent_games)),
        "role_stability": max(0.0, min(1.0, float(depth_factor) * (0.8 if role_change else 1.0))),
        "first_down_dependency": max(0.0, rush_fd + rec_fd + _f(s.get("pass_fd"))),
        "td_dependency": (total_td / max(total_yd, 1.0)),
        "yardage_bonus_sensitivity": explosive_proxy,
        "turnover_sensitivity": abs(pass_int) + abs(_f(s.get("fum_lost"))),
    }

    if p == "QB":
        f.update(
            {
                "qb_rush_contribution": rush_yd / max(pass_yd + rush_yd, 1.0),
                "passing_td_dependency": pass_td / max(total_td, 1.0),
                "scramble_floor_proxy": rush_yd / max(1.0, float(max(total_games, 1))),
            }
        )
    elif p == "RB":
        f.update(
            {
                "carry_dependency": rush_yd / max(rush_yd + rec_yd, 1.0),
                "reception_dependency": rec / max(rec + _f(s.get("rush_att")), 1.0),
                "goal_line_proxy": rush_td / max(total_td, 1.0),
            }
        )
    elif p == "WR":
        f.update(
            {
                "reception_dependency": rec / max(rec_yd, 1.0),
                "field_stretcher_proxy": rec_yd / max(rec, 1.0),
                "red_zone_proxy": rec_td / max(total_td, 1.0),
            }
        )
    elif p == "TE":
        f.update(
            {
                "te_premium_dependency": rec / max(rec_yd, 1.0),
                "chain_mover_proxy": rec_fd / max(rec, 1.0),
                "red_zone_proxy": rec_td / max(total_td, 1.0),
            }
        )
    elif p in {"DL", "LB", "DB"}:
        f.update(
            {
                "tackle_dependency": (_f(s.get("idp_tkl_solo")) + _f(s.get("idp_tkl_ast"))),
                "splash_dependency": (
                    _f(s.get("idp_sack")) + _f(s.get("idp_int")) + _f(s.get("idp_ff")) + _f(s.get("idp_fum_rec"))
                ),
            }
        )
    return {k: round(float(v), 6) for k, v in f.items()}


def infer_scoring_tags(bucket: str, features: Dict[str, float]) -> list[str]:
    tags: list[str] = []
    p = str(bucket or "").upper()
    f = features or {}
    if f.get("td_dependency", 0.0) >= 0.06:
        tags.append("td_dependent")
    if f.get("first_down_dependency", 0.0) >= 4.0:
        tags.append("first_down_heavy")
    if p in {"RB", "WR", "TE"} and f.get("reception_dependency", 0.0) >= 0.22:
        tags.append("reception_sensitive")
    if p == "TE" and f.get("te_premium_dependency", 0.0) >= 0.12:
        tags.append("te_premium_sensitive")
    if p in {"DL", "LB", "DB"} and f.get("splash_dependency", 0.0) >= 1.0:
        tags.append("idp_splash")
    return tags

