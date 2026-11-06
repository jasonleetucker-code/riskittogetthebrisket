from __future__ import annotations

import math
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


def _obs(s, key):
    """Observed finite float for ``key`` or ``None`` (absent / None / non-numeric /
    non-finite).  MISSING IS NEVER ZERO: an observed 0.0 stays 0.0."""
    v = s.get(key)
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _sum_obs(s, keys):
    """Sum of the observed components; ``None`` when NONE of them is observed.

    A stat dict is sparse (a back has no ``pass_yd``), so one absent
    component contributes nothing; but a feature none of whose inputs were
    observed is unknown, not 0.
    """
    vals = [v for v in (_obs(s, k) for k in keys) if v is not None]
    return sum(vals) if vals else None


def _production_share(component_yards, other_yards):
    """Fraction of yard-equivalent production contributed by
    ``component_yards``.  ``None`` (unknown) when either input is unknown
    or there was no production at all (a share of nothing is undefined,
    not 0.0)."""
    if component_yards is None or other_yards is None:
        return None
    total = component_yards + other_yards
    if total <= 0:
        return None
    return component_yards / total


def _ratio(num, den, floor):
    if num is None or den is None:
        return None
    return num / max(den, floor)


def compute_profile_features(
    bucket: str,
    stats_per_game: Dict[str, float],
    *,
    total_games: int,
    recent_games: int,
    depth_factor: float,
    role_change: bool,
) -> Dict[str, float]:
    """Profile features.  A feature whose inputs were not observed is OMITTED
    from the result (unknown), never emitted as 0.0; consumers
    (``infer_archetype`` / ``infer_scoring_tags``) already treat an absent
    feature as unknown."""
    s = stats_per_game or {}
    p = str(bucket or "").upper()

    rush_yd = _obs(s, "rush_yd")
    rec = _obs(s, "rec")
    rec_yd = _obs(s, "rec_yd")

    total_td = _sum_obs(s, ("pass_td", "rush_td", "rec_td"))
    total_yd = _sum_obs(s, ("pass_yd", "rush_yd", "rec_yd"))
    first_downs = _sum_obs(s, ("rush_fd", "rec_fd", "pass_fd"))
    explosive_proxy = _sum_obs(s, ("bonus_pass_td_50+", "bonus_rush_td_40+", "bonus_rec_td_40+"))
    turnovers = _sum_obs(s, ("pass_int", "fum_lost"))
    if turnovers is not None:
        # abs() per component, as before
        turnovers = sum(abs(v) for v in (_obs(s, "pass_int"), _obs(s, "fum_lost")) if v is not None)

    f: Dict[str, float | None] = {
        "games_played": float(max(0, total_games)),
        "recent_games": float(max(0, recent_games)),
        "role_stability": max(0.0, min(1.0, float(depth_factor) * (0.8 if role_change else 1.0))),
        "first_down_dependency": None if first_downs is None else max(0.0, first_downs),
        "td_dependency": _production_share(
            None if total_td is None else total_td * _TD_YARD_EQUIVALENT, total_yd
        ),
        "yardage_bonus_sensitivity": explosive_proxy,
        "turnover_sensitivity": turnovers,
    }

    # Share of yard-equivalent production that comes from the catch itself;
    # same definition for RB / WR / TE (one threshold).
    reception_share = _production_share(
        None if rec is None else rec * _RECEPTION_YARD_EQUIVALENT,
        _sum_obs(s, ("rush_yd", "rec_yd")),
    )

    if p == "QB":
        both = _sum_obs(s, ("pass_yd", "rush_yd"))
        f.update(
            {
                "qb_rush_contribution": (
                    None if rush_yd is None or both is None else rush_yd / max(both, 1.0)
                ),
                "passing_td_dependency": _ratio(_obs(s, "pass_td"), total_td, 1.0),
                # ``rush_yd`` is already per game.
                "scramble_floor_proxy": rush_yd,
            }
        )
    elif p == "RB":
        f.update(
            {
                "carry_dependency": _ratio(rush_yd, _sum_obs(s, ("rush_yd", "rec_yd")), 1.0),
                "reception_dependency": reception_share,
                "goal_line_proxy": _ratio(_obs(s, "rush_td"), total_td, 1.0),
            }
        )
    elif p == "WR":
        f.update(
            {
                "reception_dependency": reception_share,
                "field_stretcher_proxy": _ratio(rec_yd, rec, 1.0),
                "red_zone_proxy": _ratio(_obs(s, "rec_td"), total_td, 1.0),
            }
        )
    elif p == "TE":
        f.update(
            {
                "reception_dependency": reception_share,
                "te_premium_dependency": reception_share,
                "chain_mover_proxy": _ratio(_obs(s, "rec_fd"), rec, 1.0),
                "red_zone_proxy": _ratio(_obs(s, "rec_td"), total_td, 1.0),
            }
        )
    elif p in {"DL", "LB", "DB"}:
        f.update(
            {
                "tackle_dependency": _sum_obs(s, ("idp_tkl_solo", "idp_tkl_ast")),
                "splash_dependency": _sum_obs(s, ("idp_sack", "idp_int", "idp_ff", "idp_fum_rec")),
            }
        )
    return {k: round(float(v), 6) for k, v in f.items() if v is not None}


def _tag_rules(p: str):
    """(tag, feature key, cut) rules that apply to bucket ``p``."""
    rules = [
        ("td_dependent", "td_dependency", _TD_DEPENDENCY_TAG),
        ("first_down_heavy", "first_down_dependency", 4.0),
    ]
    if p in {"RB", "WR", "TE"}:
        rules.append(("reception_sensitive", "reception_dependency", RECEPTION_DEPENDENCY_TAG))
    if p == "TE":
        rules.append(("te_premium_sensitive", "te_premium_dependency", _TE_PREMIUM_DEPENDENCY_TAG))
    if p in {"DL", "LB", "DB"}:
        rules.append(("idp_splash", "splash_dependency", 1.0))
    return rules


def infer_scoring_tags(bucket: str, features: Dict[str, float]) -> list[str]:
    """Tags whose deciding feature is observed and clears its cut.  An
    unobserved feature never decides a tag; see
    :func:`scoring_tags_undecidable` for which tags were not decidable."""
    p = str(bucket or "").upper()
    f = features or {}
    tags: list[str] = []
    for tag, key, cut in _tag_rules(p):
        v = _obs(f, key)
        if v is not None and v >= cut:
            tags.append(tag)
    return tags


def scoring_tags_undecidable(bucket: str, features: Dict[str, float]) -> list[str]:
    """Tags that could not be decided because their feature was unobserved
    (absence from ``infer_scoring_tags`` means "lacks" only for tags NOT
    listed here)."""
    p = str(bucket or "").upper()
    f = features or {}
    return [tag for tag, key, _ in _tag_rules(p) if _obs(f, key) is None]
