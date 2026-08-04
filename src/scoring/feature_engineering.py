from __future__ import annotations

from typing import Dict


# ── Yard-equivalents ───────────────────────────────────────────────
# Every ``*_dependency`` feature below is a SHARE of production, in
# [0, 1].  Counting stats (catches, scores) and yardage only become
# comparable once the counting stat is restated in yards, and fantasy
# scoring makes that conversion near-universal:
#
#     1 PPR reception  = 1.0 pt = 10 yards  (0.1 pt/yd)
#     1 touchdown      = 6.0 pt = 60 yards
#
# Restating in yards is what lets ONE threshold be applied across
# positions whose raw stat lines have nothing in common — the failure
# mode these constants fix was a WR feature in receptions-per-yard
# being checked against a threshold calibrated on an RB touch share.
_RECEPTION_YARD_EQUIVALENT = 10.0
_TD_YARD_EQUIVALENT = 60.0

# ── Tag thresholds ─────────────────────────────────────────────────
# ``reception_sensitive`` (this module) and ``receiving_rb``
# (``archetype_model``) read the SAME feature and used to cut it at
# 0.22 and 0.18 respectively, so a back could be a receiving_rb whom
# the tag said was not reception-sensitive.  One constant, imported by
# both, so they cannot drift again.
RECEPTION_DEPENDENCY_TAG = 0.22

# ``td_dependency`` was TDs per YARD, cut at 0.06 — six scores per
# hundred yards, which no player has ever produced, so the tag was
# dead.  On the production-share scale a league-typical skill player
# lands near 0.25 (RB 110 yd + 0.6 TD → 36/146 = 0.25; WR 60 yd +
# 0.4 TD → 24/84 = 0.29; QB 275 yd + 1.8 TD → 108/383 = 0.28) while a
# genuinely score-dependent one clears 0.45 (goal-line back 45 yd +
# 0.7 TD → 42/87 = 0.48).  0.40 is the line between them.
_TD_DEPENDENCY_TAG = 0.40

# ``te_premium_sensitive`` cut at 0.12 receptions-per-yard, i.e. a TE
# averaging no more than 8.33 yards a catch.  That same cut restated
# as a reception share is 10×0.12 / (10×0.12 + 1) — a change of
# variables, not a new threshold, so the tag still fires for exactly
# the stat lines it always did.
_TE_PREMIUM_DEPENDENCY_TAG = (_RECEPTION_YARD_EQUIVALENT * 0.12) / (
    _RECEPTION_YARD_EQUIVALENT * 0.12 + 1.0
)


def _f(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _production_share(component_yards: float, other_yards: float) -> float:
    """Fraction of yard-equivalent production contributed by
    ``component_yards``.  Zero production is 0.0, not a divide-by-zero
    and not an invented floor."""
    total = component_yards + other_yards
    if total <= 0:
        return 0.0
    return component_yards / total


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
    explosive_proxy = (
        _f(s.get("bonus_pass_td_50+"))
        + _f(s.get("bonus_rush_td_40+"))
        + _f(s.get("bonus_rec_td_40+"))
    )

    f = {
        "games_played": float(max(0, total_games)),
        "recent_games": float(max(0, recent_games)),
        "role_stability": max(0.0, min(1.0, float(depth_factor) * (0.8 if role_change else 1.0))),
        "first_down_dependency": max(0.0, rush_fd + rec_fd + _f(s.get("pass_fd"))),
        "td_dependency": _production_share(total_td * _TD_YARD_EQUIVALENT, total_yd),
        "yardage_bonus_sensitivity": explosive_proxy,
        "turnover_sensitivity": abs(pass_int) + abs(_f(s.get("fum_lost"))),
    }

    # Share of yard-equivalent production that comes from the catch
    # itself.  Defined identically for RB / WR / TE because ONE
    # threshold is applied to all three (``reception_sensitive``).
    # The RB used to measure a touch fraction — rec ÷ (rec + carries) —
    # which is degenerate for a WR (≈1.0, every touch is a catch), and
    # WR/TE used receptions-per-yard, which is not a fraction at all
    # and sat an order of magnitude below the shared threshold.
    reception_share = _production_share(rec * _RECEPTION_YARD_EQUIVALENT, rush_yd + rec_yd)

    if p == "QB":
        f.update(
            {
                "qb_rush_contribution": rush_yd / max(pass_yd + rush_yd, 1.0),
                "passing_td_dependency": pass_td / max(total_td, 1.0),
                # ``rush_yd`` is already per game (it comes out of
                # ``stats_per_game``); dividing by ``total_games`` a
                # second time turned 30 yd/g into 1.9 over a full season.
                "scramble_floor_proxy": rush_yd,
            }
        )
    elif p == "RB":
        f.update(
            {
                "carry_dependency": rush_yd / max(rush_yd + rec_yd, 1.0),
                "reception_dependency": reception_share,
                "goal_line_proxy": rush_td / max(total_td, 1.0),
            }
        )
    elif p == "WR":
        f.update(
            {
                "reception_dependency": reception_share,
                "field_stretcher_proxy": rec_yd / max(rec, 1.0),
                "red_zone_proxy": rec_td / max(total_td, 1.0),
            }
        )
    elif p == "TE":
        f.update(
            {
                # The TE branch never emitted ``reception_dependency``
                # at all, so the {RB, WR, TE} tag read a missing key as
                # 0.0 and could not fire for a tight end.
                "reception_dependency": reception_share,
                # The TE premium is a bonus paid PER RECEPTION, so a
                # TE's exposure to it is exactly their reception share.
                # Same number, read at a stricter cut — see
                # ``_TE_PREMIUM_DEPENDENCY_TAG``.
                "te_premium_dependency": reception_share,
                "chain_mover_proxy": rec_fd / max(rec, 1.0),
                "red_zone_proxy": rec_td / max(total_td, 1.0),
            }
        )
    elif p in {"DL", "LB", "DB"}:
        f.update(
            {
                "tackle_dependency": (_f(s.get("idp_tkl_solo")) + _f(s.get("idp_tkl_ast"))),
                "splash_dependency": (
                    _f(s.get("idp_sack"))
                    + _f(s.get("idp_int"))
                    + _f(s.get("idp_ff"))
                    + _f(s.get("idp_fum_rec"))
                ),
            }
        )
    return {k: round(float(v), 6) for k, v in f.items()}


def infer_scoring_tags(bucket: str, features: Dict[str, float]) -> list[str]:
    tags: list[str] = []
    p = str(bucket or "").upper()
    f = features or {}
    if f.get("td_dependency", 0.0) >= _TD_DEPENDENCY_TAG:
        tags.append("td_dependent")
    if f.get("first_down_dependency", 0.0) >= 4.0:
        tags.append("first_down_heavy")
    if p in {"RB", "WR", "TE"} and f.get("reception_dependency", 0.0) >= RECEPTION_DEPENDENCY_TAG:
        tags.append("reception_sensitive")
    if p == "TE" and f.get("te_premium_dependency", 0.0) >= _TE_PREMIUM_DEPENDENCY_TAG:
        tags.append("te_premium_sensitive")
    if p in {"DL", "LB", "DB"} and f.get("splash_dependency", 0.0) >= 1.0:
        tags.append("idp_splash")
    return tags
