"""Per-pair FAAB bid recommender for the manual add/drop calculator.

Sister module to ``src/trade/waiver.py`` — does not rewrite the
existing ``_compute_faab_bid`` formula (which the recommendation
engine on /waivers still uses for each ``bestMoves`` row's hint).
Instead, ``recommend_faab`` composes that baseline with four
additional signals so a single user-driven add/drop pair gets a
high-fidelity recommendation:

  1. ``_compute_faab_bid``         baseline (aggressive/reasonable/lowball)
  2. Value-gain modifier           (net gain ÷ drop value, clamped)
  3. Sleeper trending kicker       (top-N most-added in 24h)
  4. League analytics calibration  (blend with historical bid-by-pos+tier)
  5. Team FAAB cap                 (never recommend more than they have)
  6. Marginal-upgrade floor        (net gain ≤ 0 ⇒ floor at $0)

FAAB v2 (contention-aware) layers two optional inputs on top:

  7. Budget-environment scaling    (league bid temperature; skipped
                                    whenever step 4's per-position
                                    calibration already fired)
  8. Contention clearing           (sealed first-price auction: bid
                                    the minimum that clears the
                                    projected top rival — see
                                    ``src/trade/faab_contention.py`` —
                                    gated by replaceability, capped
                                    at the player's value ceiling)

plus a pacing warning whenever the standard bid exceeds 40% of the
remaining budget.

Each input is optional.  Missing inputs drop the confidence and
surface a ``factors[].missing=true`` row so the UI can explain
"this recommendation has lower confidence because we don't have
trending data this week".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.trade.waiver import _compute_faab_bid
from src.utils.name_clean import compact_name_key


# ── Tunables ───────────────────────────────────────────────────

# Value-gain modifier clamps.  A small upgrade still recommends
# something (we don't want to whiff on a real-but-modest add); a
# big upgrade gets boosted but caps so we don't runaway-bid into
# the marginal-utility wall.
_VALUE_MOD_FLOOR = 0.5
_VALUE_MOD_CEILING = 1.8

# Trending kicker — applied when Sleeper trending count is in the
# top tier of the recent 24h window.  ``trending_count`` is the
# raw "X people added" number from the Sleeper API.
_TRENDING_TIER_BREAKPOINTS = (
    (10000, 0.20),  # top trending: +20% to standard bid
    (5000, 0.15),  # very hot
    (1000, 0.10),  # warm
)

# League-analytics calibration blend.  A 50/50 blend keeps the
# formula honest in leagues where users overpay (e.g. a league
# that always wins WR2 bids at $40+) without letting the
# historical noise overwhelm the math.
_LEAGUE_CALIBRATION_BLEND = 0.5

# ── FAAB v2 (contention-aware) tunables ────────────────────────

# Replaceability gate: chase the projected clearing price only when
# the add is meaningfully better than the next-best same-position
# free agent.  dropoff = (add_value − next_best_FA) ÷ add_value.
_DROPOFF_GATE = 0.15

# Value ceiling scaling with irreplaceability:
# ceiling = aggressive × (1 + 0.5 × clamp(dropoff, 0, 0.5)).
_CEILING_DROPOFF_CLAMP = 0.5
_CEILING_DROPOFF_SCALE = 0.5

# Budget-environment scaling: leagues where the median winning bid
# is a big share of the budget bid hot everywhere; scale the value
# bid by clamp((median ÷ budget) ÷ 0.08, 0.6, 1.6).  Requires at
# least 10 analyzed bids, and applies ONLY when the per-position
# calibration did NOT (positionBids[pos].count < 3) — otherwise the
# league's bid temperature would be counted twice (review-caught
# double-count bug; pinned by a regression test).
_ENV_SCALE_TARGET_SHARE = 0.08
_ENV_SCALE_CLAMP = (0.6, 1.6)
_ENV_MIN_BIDS_ANALYZED = 10
_POSITION_CALIBRATION_MIN_COUNT = 3

# Pacing warning: flag any standard bid above this share of the
# team's remaining budget.
_PACING_WARN_SHARE = 0.40


@dataclass
class _Factor:
    """One row of the recommendation breakdown.

    ``contribution`` is a human-readable short string ("+3 to
    standard", "−$2 cap", "missing").  The full numeric impact is
    folded into the final bids; ``contribution`` is for the UI
    transparency tooltip.
    """

    label: str
    contribution: str
    weight: float
    missing: bool = False


def compute_confidence(factors: list[Any]) -> str:
    """Weighted realized-share confidence bucket over factor rows.

    Accepts ``_Factor`` objects or plain dicts (the serialized
    ``factors`` shape from a ``recommend_faab`` response) so callers
    that append factor rows AFTER the recommendation — e.g. the
    endpoint's contention-missing note — can recompute the bucket and
    keep the reported confidence honest about the full factor set.
    """
    total_weight = 0.0
    realized_weight = 0.0
    for f in factors:
        if isinstance(f, _Factor):
            weight, missing = f.weight, f.missing
        elif isinstance(f, dict):
            try:
                weight = float(f.get("weight") or 0.0)
            except (TypeError, ValueError):
                continue
            missing = bool(f.get("missing"))
        else:
            continue
        total_weight += weight
        if not missing:
            realized_weight += weight
    realized_share = (realized_weight / total_weight) if total_weight > 0 else 0.0
    if realized_share >= 0.85:
        return "high"
    if realized_share >= 0.55:
        return "medium"
    return "low"


def _value_gain_modifier(add_value: float, drop_value: float) -> float:
    """1 + (netGain ÷ drop_value) × 0.5, clamped to [0.5, 1.8].

    Bigger upgrade ⇒ higher modifier.  Drop value of 0 (FA-only
    add, no drop required) returns 1.0 (no boost, no penalty)."""
    if drop_value <= 0:
        return 1.0
    net = add_value - drop_value
    raw = 1.0 + (net / drop_value) * 0.5
    return max(_VALUE_MOD_FLOOR, min(_VALUE_MOD_CEILING, raw))


def _trending_kicker(trending_count: int | None) -> float:
    """Return the multiplicative kicker (1.0 to 1.20) based on the
    Sleeper trending count for the player.  None ⇒ 1.0 (neutral)."""
    if trending_count is None or trending_count <= 0:
        return 1.0
    for threshold, bump in _TRENDING_TIER_BREAKPOINTS:
        if trending_count >= threshold:
            return 1.0 + bump
    return 1.0


def _position_calibration(
    league_faab_summary: dict[str, Any] | None,
    position: str | None,
    bid_estimate: float,
) -> float:
    """Blend ``bid_estimate`` 50/50 with the league's historical
    average winning bid for ``position``.  Returns ``bid_estimate``
    unchanged when the analytics block is missing or the position
    has no historical data.

    Returns a FLOAT — this is one link in the recommendation chain,
    not the recommendation.  ``recommend_faab`` rounds once at the
    end; see the comment at step 2 there."""
    if not league_faab_summary or not position:
        return bid_estimate
    pos_bids = (league_faab_summary.get("positionBids") or {}).get(position) or {}
    avg_for_pos = pos_bids.get("avg")
    count_for_pos = pos_bids.get("count") or 0
    if not isinstance(avg_for_pos, (int, float)) or count_for_pos < _POSITION_CALIBRATION_MIN_COUNT:
        # Need at least 3 historical bids for the calibration to
        # be meaningful; otherwise we'd be calibrating against
        # noise.
        return bid_estimate
    blended = _LEAGUE_CALIBRATION_BLEND * float(avg_for_pos) + (
        1.0 - _LEAGUE_CALIBRATION_BLEND
    ) * float(bid_estimate)
    return max(0.0, blended)


def _env_scale_factor(
    league_faab_summary: dict[str, Any] | None,
    position: str | None,
    league_budget: int,
) -> float | None:
    """Budget-environment multiplier, or ``None`` when it must not
    apply.

    Applies only when:
      * the league has ≥ ``_ENV_MIN_BIDS_ANALYZED`` analyzed bids
        (otherwise the median is noise), AND
      * the per-position calibration did NOT fire for ``position``
        (``positionBids[pos].count < 3``).  When the position blend
        already pulled the bid towards the league's real prices,
        scaling again would double-count the league's bid
        temperature.
    """
    if not league_faab_summary or league_budget <= 0:
        return None
    try:
        total_bids = int(league_faab_summary.get("totalBidsAnalyzed") or 0)
    except (TypeError, ValueError):
        total_bids = 0
    if total_bids < _ENV_MIN_BIDS_ANALYZED:
        return None
    median = league_faab_summary.get("leagueMedianWinningBid")
    if not isinstance(median, (int, float)) or median <= 0:
        return None
    # Position calibration takes precedence — see docstring.
    if position:
        pos_bids = (league_faab_summary.get("positionBids") or {}).get(position) or {}
        try:
            pos_count = int(pos_bids.get("count") or 0)
        except (TypeError, ValueError):
            pos_count = 0
        if pos_count >= _POSITION_CALIBRATION_MIN_COUNT:
            return None
    share = float(median) / float(league_budget)
    lo, hi = _ENV_SCALE_CLAMP
    return max(lo, min(hi, share / _ENV_SCALE_TARGET_SHARE))


def _ktc_crowd_blend(
    ktc_crowd_bids: dict[str, Any] | None,
    player_name: str | None,
    league_budget: int,
    bid_estimate: float,
) -> float:
    """Blend with the KTC crowd-sourced waiver-bid % when present.
    The value is a percent-of-budget median bid that league members
    assigned to this player.  Returns ``bid_estimate`` unchanged when
    the crowd map is empty or the player isn't covered.

    The map is keyed by ``name_clean.compact_name_key`` — the key
    ``src/adapters/ktc_crowd_faab.build_crowd_bid_map`` builds it with.
    Until 2026-07-29 this looked up with a bare ``strip().lower()``
    instead, which can only collide with the compact key on a
    single-token unpunctuated name; the server passes a spaced display
    name, so the crowd calibration factor never fired in production.
    Producer and consumer now call the same helper — do not
    re-introduce a local key here."""
    if not ktc_crowd_bids or not player_name:
        return bid_estimate
    norm = compact_name_key(player_name)
    crowd_pct = ktc_crowd_bids.get(norm)
    if not isinstance(crowd_pct, (int, float)) or crowd_pct <= 0:
        return bid_estimate
    crowd_bid = max(1.0, float(crowd_pct) / 100.0 * league_budget)
    # 70/30 blend: trust our composite a bit more than the crowd
    # since the crowd's number doesn't account for the user's
    # specific drop side.
    return 0.7 * bid_estimate + 0.3 * crowd_bid


def recommend_faab(
    *,
    add_player_value: float,
    drop_player_value: float = 0.0,
    add_player_position: str | None = None,
    add_player_name: str | None = None,
    team_faab_remaining: int | None = None,
    league_faab_summary: dict[str, Any] | None = None,
    sleeper_trending: dict[str, Any] | None = None,
    ktc_crowd_bids: dict[str, Any] | None = None,
    league_budget: int = 100,
    top_value_in_pool: float | None = None,
    contention: dict[str, Any] | None = None,
    next_best_fa_value: float | None = None,
) -> dict[str, Any]:
    """Recommend a FAAB bid for a single add/drop pair.

    All inputs are keyword-only so callers can pass exactly what
    they have; missing inputs degrade confidence rather than crash.

    FAAB v2 (contention-aware) inputs — both optional, both
    additive to the original behavior:

    ``contention``
        Output of ``src.trade.faab_contention.estimate_rival_bids``
        (needs ``clearing`` + ``topRival``).  Sealed first-price
        auction policy: raise the standard bid to the projected
        clearing price, never above the player's value ceiling.
    ``next_best_fa_value``
        Value of the next-best same-position free agent — powers
        the replaceability gate.  ``dropoff = (add − next_best) ÷
        add``; below ``_DROPOFF_GATE`` the clearing price is NOT
        chased (a replaceable player only merits a value bid).

    Returns a dict with::
        {
            "conservative": int,     # ~70% of standard
            "standard":     int,     # the recommended bid
            "aggressive":   int,     # ~140% of standard
            "max":          int,     # ceiling = team's faabRemaining
            "confidence":   "low" | "medium" | "high",
            "factors":      [{"label", "contribution", "weight",
                              "missing"}, ...],
            "warnings":     [str, ...],
            "explanation":  str,     # one-line plain-English summary
        }
    """
    factors: list[_Factor] = []
    warnings: list[str] = []

    # 1. Baseline from the existing _compute_faab_bid formula.
    aggressive_base, reasonable_base, lowball_base = _compute_faab_bid(
        candidate_value=float(add_player_value),
        # The helper's ``budget`` is whatever pool the caller wants the
        # bid sized against; here that's the league's full season
        # budget — step 7 below caps the result at the team's own
        # remaining balance.
        budget=int(league_budget),
        top_value_in_pool=top_value_in_pool,
    )
    factors.append(
        _Factor(
            label="Player value baseline",
            contribution=f"start at ${reasonable_base}",
            weight=0.35,
        )
    )

    # 2. Value-gain modifier.
    #
    # ``standard`` is carried as a FLOAT from here through step 6 and
    # rounded exactly ONCE, just before the team-FAAB cap.  Every stage
    # below used to round, so each stage's ±$0.50 was fed to the next as
    # though it were the real number: a value-gain result of $37.80
    # became $38, which the trending kicker multiplied, which the league
    # blend averaged against, which the budget-environment scale
    # multiplied again — three round-ups compounding into a dollar of
    # pure drift.  Whole dollars are a property of the ANSWER, not of
    # the intermediate arithmetic.
    mod = _value_gain_modifier(float(add_player_value), float(drop_player_value or 0))
    standard = max(0.0, reasonable_base * mod)
    if drop_player_value > 0:
        if mod > 1.05:
            factors.append(
                _Factor(
                    label="Net upgrade boost",
                    contribution=f"×{mod:.2f}",
                    weight=0.20,
                )
            )
        elif mod < 0.95:
            factors.append(
                _Factor(
                    label="Marginal-upgrade penalty",
                    contribution=f"×{mod:.2f}",
                    weight=0.20,
                )
            )

    # 3. Trending kicker.
    trending_count = None
    if isinstance(sleeper_trending, dict):
        trending_count = sleeper_trending.get("count")
        if trending_count is not None:
            try:
                trending_count = int(trending_count)
            except (TypeError, ValueError):
                trending_count = None
    kicker = _trending_kicker(trending_count)
    if kicker > 1.0:
        standard = standard * kicker
        factors.append(
            _Factor(
                label="Trending bump",
                contribution=f"×{kicker:.2f}",
                weight=0.15,
            )
        )
    elif sleeper_trending is None:
        factors.append(
            _Factor(
                label="Trending data",
                contribution="missing",
                weight=0.15,
                missing=True,
            )
        )
    else:
        # Present-but-neutral: we HAVE trending data, it just doesn't
        # clear the lowest breakpoint.  The row must still be emitted —
        # ``compute_confidence`` divides by the SUM of the weights it is
        # handed, so dropping a present factor silently rewrites the
        # denominator and makes the same recommendation score a
        # different confidence purely because the player is cold.
        factors.append(
            _Factor(
                label="Trending bump",
                contribution="none — below the lowest breakpoint",
                weight=0.15,
            )
        )

    # 4. League-analytics calibration (per-position blend).
    if league_faab_summary:
        before = standard
        standard = _position_calibration(league_faab_summary, add_player_position, standard)
        if standard != before:
            # Whole-dollar delta for the tooltip only; the chain keeps
            # the unrounded value.
            delta = round(standard) - round(before)
            sign = "+" if delta > 0 else ""
            factors.append(
                _Factor(
                    label="League historical calibration",
                    contribution=f"{sign}${delta}",
                    weight=0.20,
                )
            )
        else:
            factors.append(
                _Factor(
                    label="League historical data",
                    contribution="insufficient samples",
                    weight=0.20,
                    missing=True,
                )
            )
    else:
        factors.append(
            _Factor(
                label="League historical analytics",
                contribution="missing",
                weight=0.20,
                missing=True,
            )
        )

    # 4b. KTC crowd blend (optional, B7).
    if ktc_crowd_bids:
        before = standard
        standard = _ktc_crowd_blend(ktc_crowd_bids, add_player_name, league_budget, standard)
        if standard != before:
            delta = round(standard) - round(before)
            sign = "+" if delta > 0 else ""
            factors.append(
                _Factor(
                    label="KTC crowd-sourced calibration",
                    contribution=f"{sign}${delta}",
                    weight=0.10,
                )
            )

    # 4c. Budget-environment scaling (FAAB v2).  Hot-bidding leagues
    # (median winning bid a big share of budget) get scaled up, cold
    # leagues down — but ONLY when the per-position calibration did
    # not already anchor the bid to league prices (double-count
    # guard, see _env_scale_factor).
    env = _env_scale_factor(league_faab_summary, add_player_position, int(league_budget))
    if env is not None and standard > 0 and abs(env - 1.0) > 1e-9:
        standard = max(0.0, standard * env)
        factors.append(
            _Factor(
                label="Budget environment",
                contribution=f"×{env:.2f}",
                weight=0.10,
            )
        )

    # 4d. Contention clearing (FAAB v2).  Sealed first-price auction
    # policy: bid the minimum that clears the projected top rival —
    # never above the player's own value ceiling.
    if isinstance(contention, dict) and standard > 0:
        clearing_raw = contention.get("clearing")
        if isinstance(clearing_raw, (int, float)) and clearing_raw > 0:
            dropoff: float | None = None
            if next_best_fa_value is not None and add_player_value > 0:
                dropoff = max(
                    0.0,
                    (float(add_player_value) - max(0.0, float(next_best_fa_value)))
                    / float(add_player_value),
                )
            if dropoff is not None and dropoff < _DROPOFF_GATE:
                # Replaceability gate: the next-best FA is close —
                # chasing a clearing price on a replaceable player
                # is how budgets die.  Value bid only.
                factors.append(
                    _Factor(
                        label="Replaceable at position",
                        contribution=(
                            f"dropoff {dropoff:.0%} < {_DROPOFF_GATE:.0%} — value bid only"
                        ),
                        weight=0.15,
                    )
                )
            else:
                d = max(0.0, min(_CEILING_DROPOFF_CLAMP, dropoff if dropoff is not None else 0.0))
                # The ceiling is derived from the running (unrounded)
                # bid; only the rival's projected clearing price is a
                # real whole-dollar figure.
                pre_aggressive = max(0.0, standard * 1.40)
                ceiling = pre_aggressive * (1.0 + _CEILING_DROPOFF_SCALE * d)
                clearing = int(round(float(clearing_raw)))
                if clearing <= standard:
                    factors.append(
                        _Factor(
                            label="Rival contention",
                            contribution=(
                                f"value bid already clears projected top rival "
                                f"(${int(contention.get('topRival') or (clearing - 1))})"
                            ),
                            weight=0.15,
                        )
                    )
                elif clearing <= ceiling:
                    factors.append(
                        _Factor(
                            label="Rival contention",
                            contribution=f"+${clearing - round(standard)} to clear top rival",
                            weight=0.15,
                        )
                    )
                    standard = float(clearing)
                else:
                    factors.append(
                        _Factor(
                            label="Rival contention",
                            contribution=f"stopped at value ceiling ${round(ceiling)}",
                            weight=0.15,
                        )
                    )
                    warnings.append(
                        f"Likely outbid — projected clearing price ${clearing} "
                        f"exceeds this player's value ceiling ${round(ceiling)}."
                    )
                    standard = max(standard, ceiling)

    # 5. Marginal-upgrade floor: when the swap is even or negative,
    # bidding more than $1-$2 over reasonable_base is rarely worth
    # it.  We let the user see ``standard`` come down to $1 (a
    # token claim on the priority order), not to $0 — Sleeper
    # treats $0 as a bid which still gets contested.
    if drop_player_value > 0 and add_player_value <= drop_player_value:
        warnings.append(
            "This is a marginal upgrade — your drop is worth as much as your add.  Don't overspend."
        )
        # Re-anchors on the untouched baseline, not on the running bid.
        standard = min(standard, max(1.0, reasonable_base * 0.5))

    # 6. Floor at $0 if the swap is strictly negative.
    if drop_player_value > 0 and add_player_value < drop_player_value:
        warnings.append("Your drop is worth more than your add — don't bid.")
        standard = 0.0

    # ── Round ONCE.  Everything above is arithmetic; everything below
    # compares the recommendation against real whole-dollar balances.
    standard = max(0, round(standard))

    # 7. Cap at team's faabRemaining.  When unknown, use the
    # league budget as a soft ceiling (defensive — better to
    # under-recommend than to suggest a bid the user can't make).
    cap_source = team_faab_remaining if team_faab_remaining is not None else league_budget
    cap_source = max(0, int(cap_source))
    if standard > cap_source:
        warnings.append(f"Capped at team's remaining FAAB (${cap_source}).")
        standard = cap_source
        factors.append(
            _Factor(
                label="Team FAAB cap",
                contribution=f"clipped to ${cap_source}",
                weight=0.10,
            )
        )

    # Derive the conservative / aggressive bracket from the final
    # ``standard`` so all three pills move together.
    conservative = max(0, round(standard * 0.70))
    aggressive = max(0, min(cap_source, round(standard * 1.40)))
    max_bid = cap_source

    # Budget pacing (FAAB v2): flag any bid that eats more than 40%
    # of the remaining budget so the user consciously accepts the
    # season-long tradeoff.
    if standard > 0 and cap_source > 0 and standard > _PACING_WARN_SHARE * cap_source:
        warnings.append(
            f"Pacing: this bid is over {int(_PACING_WARN_SHARE * 100)}% of the "
            f"remaining budget (${cap_source})."
        )

    # Confidence: counts non-missing factors, weighted.
    confidence = compute_confidence(factors)

    # Plain-English summary of the recommendation.
    if standard == 0:
        explanation = (
            "We don't recommend bidding on this swap — the drop is worth more than the add."
        )
    elif standard <= 2:
        explanation = (
            f"Token bid (${standard}).  Marginal upgrade or low league budget — keep it cheap."
        )
    elif drop_player_value > 0:
        net = add_player_value - drop_player_value
        explanation = (
            f"Bid ${standard} — your add is worth ~{int(net)} more "
            "than your drop, league history "
            f"{'and' if league_faab_summary else 'is missing but'} the "
            "value-gap math supports it."
        )
    else:
        explanation = (
            f"Bid ${standard} — strong free-agent target.  Cap at "
            f"${aggressive} if you want the priority claim."
        )

    return {
        "conservative": conservative,
        "standard": standard,
        "aggressive": aggressive,
        "max": max_bid,
        "confidence": confidence,
        "factors": [
            {
                "label": f.label,
                "contribution": f.contribution,
                "weight": f.weight,
                "missing": f.missing,
            }
            for f in factors
        ],
        "warnings": warnings,
        "explanation": explanation,
    }
