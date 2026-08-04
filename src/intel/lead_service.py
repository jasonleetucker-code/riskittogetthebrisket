"""Assembles Insider Trading leads from live league data.

Glue only.  Every number comes from an existing engine:

    who traded what, elsewhere    src.intel.ledger
    who is in my league           the crawl snapshot + sleeper teams
    positional need / window      src.roster_intel (via RosterSignal)
    partner fit                   src.roster_intel.partner.assess_partner
    the lead score itself         src.intel.leads

SELL MODE  ("I want to move X") ranks league-mates by how much they
           look like they want X.
BUY MODE   ("I want X") finds the CURRENT OWNER in this league, plus
           what they look likely to want back.

Both modes read the SAME observations from opposite sides — a manager
who acquired X elsewhere is a buyer in sell mode and a reluctant seller
in buy mode — which is why one ledger query serves both.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from src.intel import leads as leads_model
from src.intel import ledger, service, signals
from src.roster_intel import partner as partner_model

log = logging.getLogger(__name__)

# Leads look at a longer horizon than the board: a manager who traded
# for someone four months ago still plausibly wants him, and revealed
# preference decays by half-life inside the scorer rather than by a
# hard window cut here.
LEAD_WINDOW = "90d"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _interest_by_owner(
    asset_id: str,
    pool: Sequence[str],
    *,
    exclude_league_ids: Sequence[str] | None,
    now_ms: int,
) -> dict[str, leads_model.InterestObservation]:
    """Per-manager revealed preference for ONE asset, from elsewhere.

    ``exclude_league_ids`` drops the league being asked about: "has my
    league-mate bought this player ELSEWHERE" must not count a trade
    made in the very league we are looking at, or every current owner
    would score as an enthusiastic buyer of their own player.
    """
    if not pool:
        return {}
    since, until = signals.window_bounds(LEAD_WINDOW, now_ms)
    rows = ledger.manager_asset_activity(
        user_ids=list(pool),
        asset_id=asset_id,
        since_ms=since,
        until_ms=until,
        exclude_league_ids=exclude_league_ids,
    )
    return {
        str(r["userId"]): leads_model.InterestObservation(
            user_id=str(r["userId"]),
            asset_id=asset_id,
            buys=int(r["buys"] or 0),
            sells=int(r["sells"] or 0),
            unique_leagues=int(r["uniqueLeagues"] or 0),
            last_ts=r.get("lastTs"),
        )
        for r in rows
    }


def _trade_counts(pool: Sequence[str], now_ms: int) -> tuple[dict[str, int], float | None]:
    """Completed trades per manager, and the pool mean for shrinkage."""
    if not pool:
        return {}, None
    since, until = signals.window_bounds("90d", now_ms)
    rows = ledger.manager_asset_activity(user_ids=list(pool), since_ms=since, until_ms=until)
    per_user: dict[str, set] = {}
    for r in rows:
        per_user.setdefault(str(r["userId"]), set())
    counts = {
        uid: sum(int(r["tradeCount"] or 0) for r in rows if str(r["userId"]) == uid)
        for uid in per_user
    }
    mean = (sum(counts.values()) / len(counts)) if counts else None
    return counts, mean


def build_leads(
    *,
    league_key: str,
    asset_id: str,
    position: str | None = None,
    direction: str = "buy",
    roster_signals: Mapping[str, partner_model.RosterSignal] | None = None,
    our_roster: partner_model.RosterSignal | None = None,
    target_value: float | None = None,
    matchable_values_by_owner: Mapping[str, Sequence[float]] | None = None,
    owner_of_asset: str | None = None,
    home_league_ids: Sequence[str] | None = None,
    exclude_owner_ids: Sequence[str] | None = None,
    limit: int = 12,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Rank this league's managers as leads for one asset.

    ``direction="buy"`` = SELL MODE (who wants what I have).
    ``direction="sell"`` = BUY MODE (who would move what I want).
    """
    now_ms = now_ms or _now_ms()
    state = service.load_state_cached(league_key)
    service.ensure_ledger_synced(league_key, state)
    pool = [
        oid for oid in service._pool_member_ids(state) if oid not in set(exclude_owner_ids or ())
    ]
    names = state.get("memberNames") or {}

    interest = _interest_by_owner(asset_id, pool, exclude_league_ids=home_league_ids, now_ms=now_ms)
    trade_counts, mean_trades = _trade_counts(pool, now_ms)
    roster_signals = roster_signals or {}
    matchable = matchable_values_by_owner or {}

    built: list[leads_model.Lead] = []
    for owner_id in pool:
        their = roster_signals.get(owner_id)
        assessment = None
        if their is not None or our_roster is not None:
            try:
                assessment = partner_model.assess_partner(
                    partner_model.PartnerInputs(
                        owner_id=owner_id,
                        display_name=str(names.get(owner_id) or ""),
                        our_roster=our_roster,
                        their_roster=their,
                        trades_completed=int(trade_counts.get(owner_id, 0)),
                        league_mean_trades=mean_trades,
                    )
                )
            except Exception:  # noqa: BLE001 — a lead must survive a fit failure
                log.exception("leads: partner assessment failed for %s", owner_id)
                assessment = None

        built.append(
            leads_model.score_lead(
                owner_id=owner_id,
                display_name=str(names.get(owner_id) or ""),
                interest=interest.get(owner_id),
                partner=assessment,
                their_roster=their,
                position=position,
                target_value=target_value,
                their_matchable_values=matchable.get(owner_id),
                trades_completed=int(trade_counts.get(owner_id, 0)),
                league_mean_trades=mean_trades,
                now_ms=now_ms,
                direction=direction,
                owns_asset=(owner_id == owner_of_asset),
            )
        )

    ranked = leads_model.rank_leads(built, limit=limit)
    return {
        "leagueKey": league_key,
        "assetId": asset_id,
        "position": position,
        "mode": "sell" if direction == "buy" else "buy",
        "window": LEAD_WINDOW,
        "ownerOfAsset": owner_of_asset,
        "poolSize": len(pool),
        "leadsWithObservedInterest": sum(1 for lead in built if lead.interest),
        "leads": [lead.to_dict() for lead in ranked],
        "limitations": leads_model.describe_limitations(),
        "generatedAt": state.get("generatedAt"),
        "staleHours": service.snapshot_stale_hours(state),
    }
