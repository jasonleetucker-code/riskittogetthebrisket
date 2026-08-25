"""Comparable-trade matching — C4-MTL-03.

Answers "what recent real trades touched this asset, and how comparable is
each one's league format to the target league" — evidence for a human or a
downstream consumer, never a value. Per
``docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`` §3: "raw real trades
must not directly overwrite canonical dynasty value merely because they
occurred." This module returns classified trades and nothing else; no
function here computes, blends, or votes a price.

SCOPE: the own-league population only
──────────────────────────────────────
``C4-MTL-01`` currently populates only our own registered leagues' trades
(the broader cross-market population is ``C4-MTL-02``, gated on an
uncaptured permission grant). So today this module searches every ACTIVE
league in the registry — which, honestly, may be as few as one or two —
rather than a market-wide sample. The match-tier machinery is written
against the general spec so it needs no rework when ``C4-MTL-02`` adds a
second source lane; the population it draws from just grows.

MATCH TIERS, AND WHY ONE SPEC TIER IS DELIBERATELY UNUSED
───────────────────────────────────────────────────────────
Spec §4 names five tiers. Four are implemented here. The third —
"NORMALIZED COMPARABLE... converted through validated league-format
normalization" — requires an actual cross-format value-conversion model,
and none exists in this repository for the dimensions that matter here
(Superflex, TEP, IDP, team count). Silently treating a same-superflex,
different-TEP-severity trade as "normalized" without a normalization
function would be exactly the fabricated confidence the tier system
exists to prevent, so this module never emits it. If that model is ever
built, it slots in as a fifth branch in ``_classify`` without changing
this module's public shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.api.league_registry import active_leagues
from src.trade.faab_comparability import TargetFormat
from src.trade.ledger_sort import newest_first_key
from src.trade.market_trade_ledger import market_trades

TIER_EXACT = "EXACT_NATIVE_COMPARABLE"
TIER_NEAR = "NEAR_COMPARABLE"
TIER_BROAD = "BROAD_MARKET_CONTEXT"
TIER_UNSUPPORTED = "UNSUPPORTED_UNVERIFIED"

#: Dimensions that must all be KNOWN on both sides before any tier above
#: UNSUPPORTED can be assigned. An unknown dimension is not a match and
#: is not a mismatch — it is unproven, and unproven format compatibility
#: fails closed to UNSUPPORTED rather than defaulting to BROAD.
_REQUIRED_DIMENSIONS = ("superflex", "tep", "idp")


def _classify(target: dict[str, Any], source: dict[str, Any]) -> tuple[str, list[str]]:
    """One trade's format dict vs the target league's format dict.

    Both are the same shape ``market_trade_ledger._format_metadata``
    produces: ``teams``, ``superflex``, ``tep``, ``tepLevel``, ``is2Te``,
    ``idp``. Returns the tier plus the reasons that decided it, so a
    caller never has to reverse-engineer why two trades landed in
    different tiers.
    """
    if any(target.get(dim) is None or source.get(dim) is None for dim in _REQUIRED_DIMENSIONS):
        missing = [
            dim
            for dim in _REQUIRED_DIMENSIONS
            if target.get(dim) is None or source.get(dim) is None
        ]
        return TIER_UNSUPPORTED, [f"{dim} unknown on one or both sides" for dim in missing]

    reasons: list[str] = []
    core_match = all(target[dim] == source[dim] for dim in _REQUIRED_DIMENSIONS)
    if not core_match:
        mismatched = [dim for dim in _REQUIRED_DIMENSIONS if target[dim] != source[dim]]
        return TIER_BROAD, [f"{dim} differs" for dim in mismatched]

    reasons.append("superflex/TEP/IDP all match")

    teams_known = target.get("teams") is not None and source.get("teams") is not None
    teams_close = teams_known and abs(int(target["teams"]) - int(source["teams"])) <= 2
    is2te_known = target.get("is2Te") is not None and source.get("is2Te") is not None
    is2te_match = is2te_known and target["is2Te"] == source["is2Te"]

    if (
        teams_known
        and int(target["teams"]) == int(source["teams"])
        and (not is2te_known or is2te_match)
    ):
        reasons.append("team count matches")
        if is2te_known:
            reasons.append("2-TE starter status matches")
        return TIER_EXACT, reasons

    if teams_close:
        reasons.append("team count within 2")
        return TIER_NEAR, reasons

    reasons.append("team count unknown or differs by more than 2")
    return TIER_BROAD, reasons


def comparable_trades_for_asset(
    asset_id: str,
    target_league_key: str,
    *,
    path: Path | None = None,
) -> list[dict[str, Any]]:
    """Every recorded trade touching ``asset_id``, classified against the
    target league's format. Newest first — recency is what makes a comp
    useful, unlike the ledger modules' own oldest-first history views.

    Excludes trades sourced from the target league itself against its
    OWN format: a league is not evidence for itself, and every such row
    would trivially classify EXACT and drown out real external comps.
    """
    target_format = TargetFormat.from_registry(target_league_key)
    target_dict = {
        "teams": target_format.teams,
        "superflex": target_format.superflex,
        "tep": target_format.tep,
        "tepLevel": target_format.tep_level,
        "is2Te": target_format.is_2te,
        "idp": target_format.idp,
    }

    out: list[dict[str, Any]] = []
    for league in active_leagues():
        if league.key == target_league_key:
            continue
        for trade in market_trades(league.key, path=path):
            touched = any(
                asset_id in {a["assetId"] for a in side.get("received", []) + side.get("sent", [])}
                for side in trade["teams"].values()
            )
            if not touched:
                continue
            tier, reasons = _classify(target_dict, trade["format"])
            out.append(
                {
                    **trade,
                    "matchTier": tier,
                    "matchReasons": reasons,
                }
            )

    out.sort(key=lambda t: newest_first_key(t["occurredAtMs"]))
    return out
