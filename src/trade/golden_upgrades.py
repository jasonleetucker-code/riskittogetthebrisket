"""Golden Upgrades — C7-GOLD-01 (owner inventory row 2.5).

A distinct PRESENTATION over the canonical trade infrastructure, never a
second trade, arbitrage or value engine.  A Golden Upgrade is an owned-player
→ target pair where:

1. the owned player is on the selected team (and the constraint owner lets him
   go — saved protections and EXCLUDE apply, during enumeration);
2. the target is genuinely substitutable: the SAME position;
3. our canonical board prefers the target (``rankDerivedValue``);
4. the market prefers what you own — on that position's own market (KTC
   Market for offense, IDP Trade Calculator for IDP), NATIVE values only
   (``cross_market.native_calculator_value``: no legacy KTC key answers for
   KTC Market, and a provider withheld as stale for either player counts as
   no price);
5. the target is obtainable: on an opponent's roster;
6. the inversion is meaningful: both edges clear the declared minimums in
   ``config/trade/golden_upgrades.json`` (``PRIOR_UNVALIDATED``);
7. both players are market-relevant: inside their market's top-150 pool (the
   finder's own quality gate, ``finder.MARKET_TOP_N_FILTER``) — deep-bench
   pairs are not offered.  The pool is RANKED on the finder's market value,
   which for offense may fall back to a historical KTC key when KTC Market is
   absent; the preference test itself (4) reads native values only.

Ordering is by the weaker of the two edges, but an inversion whose two edges
together exceed ``exploitBandPct`` is a sign the two boards disagree about the
players rather than a clean upgrade: its strength decays to 0 at
``exploitZeroPct`` and it is flagged ``exploitRisk`` (same anti-exploit rule
as Best Offers, spec §2.3).

Candidates come from the finder's own enumeration (``finder.generate_packages``
over the canonical substrate); this module only states the six criteria as a
``score`` and orders what passes.  1-for-1 trades carry no Value Adjustment
(KTC suppresses it for single pieces), so the raw values ARE the adjusted ones.
Recommendation only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.league_intel.cross_market import (
    CALCULATOR_LABELS,
    MARKET_IDPTC,
    MARKET_KTC,
    native_calculator_value,
)
from src.trade import finder

__all__ = ["GOLDEN_VERSION", "GoldenCandidate", "find_golden_upgrades", "load_golden_config"]

GOLDEN_VERSION = "golden-upgrades.2026-10-14.v1"
_CONFIG = Path(__file__).resolve().parents[2] / "config" / "trade" / "golden_upgrades.json"


def _calculator_for(position: str) -> str:
    """The one market a position is priced on: IDP Trade Calculator for
    defenders, KTC Market for everyone else (never a legacy KTC key)."""
    return MARKET_IDPTC if position in finder.IDP_POSITIONS else MARKET_KTC


def load_golden_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or _CONFIG).read_text(encoding="utf-8"))


@dataclass
class GoldenCandidate:
    """Field names mirror ``finder.TradeCandidate`` where the seam reads them."""

    give: list[Any]
    receive: list[Any]
    board_gain_pct: float
    market_inversion_pct: float
    calculator: str = ""
    owned_market: float | None = None
    target_market: float | None = None
    arbitrage_score: float = 0.0
    flags: list[str] = field(default_factory=list)
    ranking_factors: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    counterparty: str | None = None


def _scorer(
    cfg: Mapping[str, Any],
    diag: dict[str, int],
    row_for: Callable[[Any], Mapping[str, Any] | None],
) -> Callable[[list, list], Any]:
    min_board = float(cfg["minBoardGainPct"])
    min_market = float(cfg["minMarketInversionPct"])
    band = float(cfg.get("exploitBandPct", 50.0))
    zero = float(cfg.get("exploitZeroPct", 100.0))

    def native(asset: Any, calc: str) -> tuple[float | None, bool]:
        row = row_for(asset)
        if row is None:
            return None, False
        if calc in (row.get("freshnessExcludedSources") or ()):
            return None, True
        return native_calculator_value(row, calc), False

    def score(give: list[Any], receive: list[Any]) -> GoldenCandidate | None:
        if len(give) != 1 or len(receive) != 1:
            return None
        owned, target = give[0], receive[0]
        if owned.is_pick or target.is_pick:
            return None
        diag["pairs"] += 1
        if not owned.position or owned.position != target.position:
            diag["notSubstitutable"] += 1
            return None
        if owned.model_value <= 0 or target.model_value <= owned.model_value:
            diag["boardDoesNotPreferTarget"] += 1
            return None
        # Native market values on the position's own market.  A missing,
        # legacy-key-only or withheld price is not a market preference.
        calc = _calculator_for(owned.position)
        owned_mv, owned_withheld = native(owned, calc)
        target_mv, target_withheld = native(target, calc)
        if owned_withheld or target_withheld:
            diag["marketWithheld"] += 1
            return None
        if owned_mv is None or target_mv is None:
            diag["marketUnpriced"] += 1
            return None
        if owned_mv <= target_mv:
            diag["marketDoesNotPreferOwned"] += 1
            return None
        board_gain = 100.0 * (target.model_value - owned.model_value) / owned.model_value
        market_inv = 100.0 * (owned_mv - target_mv) / target_mv
        if board_gain < min_board or market_inv < min_market:
            diag["inversionTooSmall"] += 1
            return None
        diag["golden"] += 1
        total = board_gain + market_inv
        decay = 1.0
        if total > band:
            decay = max(0.0, 1.0 - (total - band) / max(zero - band, 1e-9))
        return GoldenCandidate(
            give=[owned],
            receive=[target],
            board_gain_pct=round(board_gain, 2),
            market_inversion_pct=round(market_inv, 2),
            calculator=calc,
            owned_market=owned_mv,
            target_market=target_mv,
            # Order by the WEAKER of the two edges — a Golden Upgrade is only as
            # golden as its smaller inversion — decayed past the exploit band.
            arbitrage_score=round(min(board_gain, market_inv) * decay, 4),
            flags=["exploitRisk"] if total > band else [],
        )

    return score


def _asset(a: Any, market_value: float | None, calc: str) -> dict[str, Any]:
    return {
        "name": a.name,
        "position": a.position,
        "team": a.team,
        "boardValue": a.model_value,
        "marketValue": int(round(market_value)) if market_value is not None else None,
        "market": CALCULATOR_LABELS.get(calc, calc),
    }


def find_golden_upgrades(
    players: dict[str, Any],
    my_team: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    contract: Mapping[str, Any],
    constraints: Any | None = None,
    lineup_delta: Callable[..., dict[str, Any] | None] | None = None,
    opponents: Sequence[str] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Every Golden Upgrade for ``my_team``, strongest inversion first."""
    from src.trade.constraints import blocked_outgoing, outgoing_eligibility  # noqa: PLC0415

    cfg = dict(config or load_golden_config())
    board_values = finder.board_values_from_contract(contract)
    positions = finder.positions_from_contract(contract)
    pool = finder.build_asset_pool(
        players,
        market_top_n=finder.MARKET_TOP_N_FILTER,
        board_values=board_values,
        positions=positions,
    )
    pool_by_name = {a.name: a for a in pool}
    owner_of = {str(t.get("name") or ""): str(t.get("ownerId") or "") for t in sleeper_teams}
    base = {
        "version": GOLDEN_VERSION,
        "myTeam": my_team,
        "action": "recommend_only",
        "criteria": {
            "substitutable": "same position",
            "boardPrefersTarget": f"board gain >= {cfg['minBoardGainPct']}%",
            "marketPrefersOwned": (
                f"owned player's market value exceeds the target's by >= "
                f"{cfg['minMarketInversionPct']}% on that position's own market (native values)"
            ),
            "obtainable": "on an opponent roster; your protections and exclusions respected",
            "marketRelevant": "both players inside their market's top-150 pool",
            "exploitBand": (
                f"board gain + market inversion above {cfg.get('exploitBandPct', 50.0)}% is "
                "flagged and ranked down"
            ),
            "status": cfg.get("status"),
            "configPath": "config/trade/golden_upgrades.json",
        },
    }
    my_roster = finder.resolve_roster(my_team, sleeper_teams, pool_by_name)
    if not any(str(t.get("name") or "") == my_team for t in sleeper_teams):
        return {**base, "error": "my_team_unresolved", "upgrades": []}
    if not my_roster:
        return {**base, "upgrades": [], "noResultReason": "no_priced_outgoing_assets"}
    blocked = blocked_outgoing(my_roster, constraints)
    if len(blocked) >= len(my_roster):
        return {
            **base,
            "upgrades": [],
            "noResultReason": "all_outgoing_assets_constrained",
            "noResultLabel": "No Golden Upgrade found under current constraints",
        }
    policy = outgoing_eligibility(my_roster, constraints)
    owned_names = {a.name for a in my_roster}
    diag = {
        "pairs": 0,
        "notSubstitutable": 0,
        "boardDoesNotPreferTarget": 0,
        "marketUnpriced": 0,
        "marketWithheld": 0,
        "marketDoesNotPreferOwned": 0,
        "inversionTooSmall": 0,
        "golden": 0,
    }
    from src.trade.best_offers import _row_for, _row_index  # noqa: PLC0415 — one row resolver

    index = _row_index(contract)
    score = _scorer(cfg, diag, lambda a: _row_for(a, index))
    # LOCK narrows the owned side to the locked players: a Golden Upgrade is a
    # 1-for-1, so "this player must be in the package" means "upgrade him".
    from src.trade.constraints import resolve_locked_outgoing  # noqa: PLC0415

    locked = bool(
        constraints is not None and (constraints.locked_outgoing or constraints.lock_conflicts)
    )
    if locked:
        lock = resolve_locked_outgoing(my_roster, constraints)
        if not lock.satisfiable:
            return {
                **base,
                "upgrades": [],
                "lock": lock.to_dict(),
                "noResultReason": lock.no_result_reason,
                "noResultLabel": "No Golden Upgrade found under current constraints",
            }
        if len(lock.required) > 1:
            # LOCK means "in every package"; a 1-for-1 holds one player.
            return {
                **base,
                "upgrades": [],
                "lock": lock.to_dict(),
                "noResultReason": "locked_players_exceed_package_size",
                "noResultLabel": "No Golden Upgrade found under current constraints",
            }
        required = {id(a) for a in lock.required}
        my_roster = [a for a in my_roster if id(a) in required]
    found: list[GoldenCandidate] = []
    for t in sleeper_teams:
        opp = str(t.get("name") or "")
        if not opp or opp == my_team or (opponents and opp not in opponents):
            continue
        opp_roster = [
            a
            for a in finder.resolve_roster(opp, sleeper_teams, pool_by_name)
            if a.name not in owned_names
        ]
        if not opp_roster:
            continue
        cands, _report = finder.generate_packages(
            my_roster, opp_roster, policy, one_for_one_only=True, score=score
        )
        cands = sorted(cands, key=lambda c: (-c.arbitrage_score, c.give[0].name, c.receive[0].name))
        for c in cands[: int(cfg.get("perOpponentLimit", 5))]:
            c.counterparty = opp
            found.append(c)

    found.sort(
        key=lambda c: (-c.arbitrage_score, -c.board_gain_pct, c.give[0].name, c.receive[0].name)
    )
    found = found[: int(cfg.get("maxResults", 25))]
    upgrades = []
    for c in found:
        lineup = (
            lineup_delta(
                owner_of.get(my_team, ""),
                owner_of.get(c.counterparty or "", ""),
                [c.give[0].name],
                [c.receive[0].name],
            )
            if lineup_delta is not None
            else None
        )
        upgrades.append(
            {
                "owned": _asset(c.give[0], c.owned_market, c.calculator),
                "target": _asset(c.receive[0], c.target_market, c.calculator),
                "market": CALCULATOR_LABELS.get(c.calculator, c.calculator),
                "opponent": c.counterparty,
                "boardGainPct": c.board_gain_pct,
                "marketInversionPct": c.market_inversion_pct,
                "strength": c.arbitrage_score,
                "exploitRisk": "exploitRisk" in c.flags,
                "lineupImpact": lineup,
                "why": (
                    f"Our board values {c.receive[0].name} {c.board_gain_pct:.1f}% above "
                    f"{c.give[0].name}, while {CALCULATOR_LABELS.get(c.calculator, c.calculator)} "
                    f"values {c.give[0].name} {c.market_inversion_pct:.1f}% above "
                    f"{c.receive[0].name} — a swap the other side's own market favours."
                ),
            }
        )
    out = {**base, "upgrades": upgrades, "diagnostics": diag}
    if not upgrades:
        out["noResultReason"] = _no_result_reason(diag)
        out["noResultLabel"] = (
            "No Golden Upgrade found under current constraints"
            if blocked or locked
            else "No Golden Upgrade found"
        )
    return out


def _no_result_reason(diag: Mapping[str, int]) -> str:
    """Name what actually stopped every pair — "no price to judge" must not
    read as "no swap exists" (review S3)."""
    if diag["pairs"] == 0:
        return "no_comparable_pairs"
    priced_stage = diag["pairs"] - diag["notSubstitutable"] - diag["boardDoesNotPreferTarget"]
    if priced_stage <= 0:
        return "no_same_position_target_board_prefers"
    judged = diag["marketDoesNotPreferOwned"] + diag["inversionTooSmall"]
    if judged == 0:
        if diag["marketWithheld"] and not diag["marketUnpriced"]:
            return "market_withheld"
        return "market_prices_unavailable"
    return "no_inversion_meets_the_thresholds"
