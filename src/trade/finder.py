"""
Trade Finder Engine
===================
Finds trades where:
  - Our model values favor my side (I receive more board value than I give)
  - KTC values show the opponent WINNING on market numbers (strictly positive gain)
  - The result is "board arbitrage" — good for me on our numbers,
    clearly appealing to them on market numbers.

Works against the live production data payload (players dict with
_rawComposite / _canonicalSiteValues fields).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

from src.utils.name_clean import POSITION_ALIASES as _POS_ALIASES

# ── Thresholds ──────────────────────────────────────────────────────────
MIN_ASSET_VALUE = 800          # Minimum model value to consider an asset tradeable
MIN_KTC_VALUE = 500            # Minimum KTC value to include in trade
MAX_BOARD_LOSS = -200          # Never suggest a trade where my board delta is worse than this
MAX_PACKAGE_SIZE = 3           # Max assets on either side
MAX_RESULTS = 40               # Cap returned results
JUNK_THRESHOLD = 400           # Assets below this are roster clog
SINGLE_SOURCE_DISCOUNT = 0.88  # Match frontend: 12% haircut for single-source assets
MULTI_FOR_ONE_MIN_RATIO = 0.55 # 2-for-1 give side must be >= 55% of receive model value

# ── KTC quality gates ──────────────────────────────────────────────────
EXCLUDED_POSITIONS = {"K", "PK", "DST", "DEF"}   # No real KTC support
PARTIAL_KTC_MAX_RANK = 15      # Partial-KTC trades cannot appear above this rank
PARTIAL_KTC_ARBITRAGE_CAP = 8.0  # Hard ceiling on partial-KTC arbitrage score

# ── KTC quality gate ──────────────────────────────────────────────────
# Hard filter: only players ranked inside the KTC top-N are eligible.
# Set to 0 to disable.
KTC_TOP_N_FILTER = 150

# ── Hardening-pass thresholds ────────────────────────────────────────────
ELITE_THRESHOLD = 7500         # Model value above which a player is "elite"
ELITE_MULTI_MIN_RATIO = 0.65   # Tighter ratio for elite targets in multi-for-one
PACKAGE_ANCHOR_MIN_PCT = 0.35  # Best give piece must be ≥35% of best receive piece
CONFIDENCE_SOURCE_BASELINE = 5 # Expected source count for full confidence
ROSTER_SURPLUS_THRESHOLD = 4   # ≥4 at a position = surplus (light fit bonus)
ROSTER_WEAK_THRESHOLD = 1      # ≤1 at a position = weakness (light fit bonus)

IDP_POSITIONS = {"DL", "LB", "DB"}


@dataclass
class Asset:
    """A tradeable asset with both model and KTC values."""
    name: str
    position: str
    team: str
    model_value: int        # Our board's value (with single-source discount)
    ktc_value: int | None   # KTC value (None = no KTC coverage)
    is_pick: bool = False
    source_count: int = 0   # Number of valuation sources
    ktc_rank: int | None = None  # 1-based KTC rank (None = no KTC data)

    @property
    def has_ktc(self) -> bool:
        return self.ktc_value is not None and self.ktc_value > 0


def _norm_pos(pos: str | None) -> str:
    if not pos:
        return ""
    p = str(pos).strip().upper()
    return _POS_ALIASES.get(p, p)


@dataclass
class TradeCandidate:
    """A scored trade proposal."""
    give: list[Asset]
    receive: list[Asset]
    give_model_total: int = 0
    receive_model_total: int = 0
    give_ktc_total: int = 0
    receive_ktc_total: int = 0
    board_delta: int = 0          # positive = good for me on our board
    ktc_delta: int = 0            # positive = opponent gives more KTC than they get
    opponent_ktc_appeal: float = 0.0   # how favorable for opponent on KTC (positive = they like it)
    arbitrage_score: float = 0.0  # composite ranking score
    ktc_coverage: str = "full"    # full / partial / none
    confidence_score: float = 1.0 # 0-1, source coverage × KTC coverage

    # ── Explainability fields ────────────────────────────────────────────
    confidence_tier: str = "high"    # "high" / "moderate" / "low"
    edge_label: str = ""             # "Strong Edge" / "Moderate Edge" / "Slight Edge"
    summary: str = ""                # Human-readable one-liner
    ranking_factors: dict = field(default_factory=dict)   # Score component breakdown
    flags: list[str] = field(default_factory=list)        # Active guards/bonuses

    def to_dict(self) -> dict[str, Any]:
        return {
            "give": [{"name": a.name, "position": a.position, "team": a.team,
                       "modelValue": a.model_value,
                       "ktcValue": a.ktc_value,
                       "ktcRank": a.ktc_rank} for a in self.give],
            "receive": [{"name": a.name, "position": a.position, "team": a.team,
                         "modelValue": a.model_value,
                         "ktcValue": a.ktc_value,
                         "ktcRank": a.ktc_rank} for a in self.receive],
            "giveModelTotal": self.give_model_total,
            "receiveModelTotal": self.receive_model_total,
            "giveKtcTotal": self.give_ktc_total,
            "receiveKtcTotal": self.receive_ktc_total,
            "boardDelta": self.board_delta,
            "ktcDelta": self.ktc_delta,
            "opponentKtcAppeal": round(self.opponent_ktc_appeal, 3),
            "arbitrageScore": round(self.arbitrage_score, 2),
            "ktcCoverage": self.ktc_coverage,
            "confidenceScore": round(self.confidence_score, 2),
            "confidenceTier": self.confidence_tier,
            "edgeLabel": self.edge_label,
            "summary": self.summary,
            "rankingFactors": self.ranking_factors,
            "flags": list(self.flags),
            "packageSize": f"{len(self.give)}-for-{len(self.receive)}",
        }


# ── Explainability helpers ────────────────────────────────────────────────

def _confidence_tier(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "moderate"
    return "low"


def _edge_label(board_gain_pct: float) -> str:
    if board_gain_pct >= 0.25:
        return "Strong Edge"
    if board_gain_pct >= 0.10:
        return "Moderate Edge"
    return "Slight Edge"


def _opp_appeal_phrase(appeal: float) -> str:
    if appeal > 0:
        return f"opponent gains {appeal:.0%} on KTC"
    return f"opponent gives up {abs(appeal):.0%} on KTC"


def _build_summary(
    board_delta: int,
    board_gain_pct: float,
    opp_appeal: float,
    coverage: str,
    confidence_tier: str,
    edge_label: str,
    pkg_size_str: str,
) -> str:
    parts = [
        f"{edge_label}: you gain {board_delta:,} board value (+{board_gain_pct:.0%})",
    ]
    # Only claim KTC opponent appeal when coverage is full
    if coverage == "full":
        parts.append(_opp_appeal_phrase(opp_appeal))
    elif coverage == "partial":
        parts.append("partial KTC — opponent view estimated only")
    else:
        parts.append("no KTC data — opponent view unavailable")
    parts.append(f"{confidence_tier} confidence")
    return ". ".join(parts) + f". ({pkg_size_str})"


def build_asset_pool(
    players: dict[str, Any],
    *,
    ktc_top_n: int = KTC_TOP_N_FILTER,
) -> list[Asset]:
    """Convert raw players dict into Asset objects with model + KTC values.

    Args:
        players: Raw players dict from the live data payload.
        ktc_top_n: Only include players ranked inside the KTC top N.
            Ranking is based on KTC value (descending). Set to 0 to disable.
    """
    pool: list[Asset] = []
    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        # Model value: prefer _finalAdjusted, then _rawComposite, then _composite.
        model = _int_or_none(pdata.get("_finalAdjusted"))
        if model is None:
            model = _int_or_none(pdata.get("_rawComposite"))
        if model is None:
            model = _int_or_none(pdata.get("_rawMarketValue"))
        if model is None:
            model = _int_or_none(pdata.get("_composite"))
        if model is None or model < 1:
            continue

        # Apply single-source discount to match frontend behavior
        source_count = _int_or_none(pdata.get("_sites")) or 0
        if source_count == 1:
            model = int(model * SINGLE_SOURCE_DISCOUNT)

        # KTC value from canonical site values
        csv = pdata.get("_canonicalSiteValues")
        ktc: int | None = None
        if isinstance(csv, dict):
            ktc = _int_or_none(csv.get("ktc"))
        if ktc is None:
            ktc = _int_or_none(pdata.get("ktc"))

        pos = _norm_pos(pdata.get("position", ""))
        team = pdata.get("team", "") or ""
        is_pick = bool(
            pos == "PICK"
            or name.startswith("20")
            or " pick " in name.lower()
            or " round " in name.lower()
        )
        if is_pick:
            pos = "PICK"

        # Exclude positions without meaningful KTC support
        if pos in EXCLUDED_POSITIONS:
            continue

        pool.append(Asset(
            name=name,
            position=pos,
            team=team if isinstance(team, str) else "",
            model_value=model,
            ktc_value=ktc,
            is_pick=is_pick,
            source_count=source_count,
        ))

    # ── Assign KTC rank and apply top-N filter ────────────────────
    # Rank by KTC value descending.  Players without KTC get no rank.
    with_ktc = [a for a in pool if a.has_ktc]
    with_ktc.sort(key=lambda a: -(a.ktc_value or 0))
    for i, a in enumerate(with_ktc):
        a.ktc_rank = i + 1

    if ktc_top_n > 0:
        eligible_names = {a.name for a in with_ktc if a.ktc_rank is not None and a.ktc_rank <= ktc_top_n}
        pool = [a for a in pool if a.name in eligible_names]

    return pool


def _int_or_none(v: Any) -> int | None:
    if v is None:
        return None
    try:
        n = int(v)
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def _resolve_roster(
    team_name: str,
    sleeper_teams: list[dict[str, Any]],
    pool_by_name: dict[str, Asset],
) -> list[Asset]:
    """Resolve a Sleeper team name to a list of Asset objects."""
    for t in sleeper_teams:
        if t.get("name") == team_name:
            players = t.get("players") or []
            result = []
            for pname in players:
                key = pname.strip()
                asset = pool_by_name.get(key)
                if asset is None:
                    # Try case-insensitive
                    for k, v in pool_by_name.items():
                        if k.lower() == key.lower():
                            asset = v
                            break
                if asset is not None:
                    result.append(asset)
            return result
    return []


def _score_trade(give: list[Asset], receive: list[Asset]) -> TradeCandidate | None:
    """Score a candidate trade. Returns None if the trade is nonsensical."""
    if not give or not receive:
        return None

    # No duplicate/self-trade
    give_names = {a.name for a in give}
    receive_names = {a.name for a in receive}
    if give_names & receive_names:
        return None

    # ── Outgoing KTC gate ────────────────────────────────────────────
    # Every outgoing asset MUST have a usable KTC value.  Without it we
    # cannot prove the deal looks plausible to the opponent, so offering
    # a no-KTC player for an elite return is nonsense.
    for a in give:
        if not a.has_ktc or a.ktc_value < MIN_KTC_VALUE:  # type: ignore[operator]
            return None

    # ── Receive-side KTC gate ─────────────────────────────────────────
    # At least one receive asset must have KTC so the opponent-appeal
    # calculation is grounded in real market data.
    recv_ktc_count = sum(1 for a in receive if a.has_ktc)
    if recv_ktc_count == 0:
        return None

    # ── IDP dilution guard ────────────────────────────────────────────
    # IDP assets without KTC must not constitute the majority of either
    # side — they distort the KTC-based opponent appeal calculation.
    for side, label in [(give, "give"), (receive, "receive")]:
        idp_no_ktc = [a for a in side if a.position in IDP_POSITIONS and not a.has_ktc]
        if len(idp_no_ktc) > 0 and len(idp_no_ktc) >= len(side) / 2:
            return None

    give_model = sum(a.model_value for a in give)
    recv_model = sum(a.model_value for a in receive)
    board_delta = recv_model - give_model

    # Must be positive on our board (we receive more model value than we give)
    if board_delta < MAX_BOARD_LOSS:
        return None

    # ── Multi-for-one fire sale guard ────────────────────────────────
    # Prevent suggesting two roster fillers for an elite target.
    # When giving more pieces than receiving, the give side's total model
    # value must be a meaningful fraction of the receive side.
    flags: list[str] = []

    if len(give) > len(receive):
        if give_model < recv_model * MULTI_FOR_ONE_MIN_RATIO:
            return None
        # ── Elite target protection (tighter ratio) ──────────────────
        max_recv = max(a.model_value for a in receive)
        if max_recv >= ELITE_THRESHOLD:
            if give_model < recv_model * ELITE_MULTI_MIN_RATIO:
                return None
            flags.append("elite_target")
        # ── Package anchor quality ───────────────────────────────────
        # At least one give piece must be a real starter-quality asset,
        # not just two bench stashes that happen to sum high enough.
        max_give = max(a.model_value for a in give)
        if max_give < max_recv * PACKAGE_ANCHOR_MIN_PCT:
            return None
        flags.append("anchor_verified")

    # KTC scoring
    give_ktc_assets = [a for a in give if a.has_ktc]
    recv_ktc_assets = [a for a in receive if a.has_ktc]
    all_have_ktc = len(give_ktc_assets) == len(give) and len(recv_ktc_assets) == len(receive)
    any_have_ktc = bool(give_ktc_assets) or bool(recv_ktc_assets)

    if not any_have_ktc:
        # No KTC on either side — cannot evaluate opponent plausibility at all
        return None
    elif all_have_ktc:
        coverage = "full"
        give_ktc = sum(a.ktc_value for a in give)  # type: ignore[arg-type]
        recv_ktc = sum(a.ktc_value for a in receive)  # type: ignore[arg-type]
        # Opponent gives recv_ktc to get give_ktc back
        # Opponent appeal = (what they get - what they give) / what they give
        opp_appeal = (give_ktc - recv_ktc) / max(recv_ktc, 1)
        flags.append("full_ktc")
    else:
        coverage = "partial"
        give_ktc = sum(a.ktc_value or 0 for a in give)
        recv_ktc = sum(a.ktc_value or 0 for a in receive)
        opp_appeal = (give_ktc - recv_ktc) / max(recv_ktc, 1) if recv_ktc > 0 else 0.0
        flags.append("partial_ktc")

    # The opponent must STRICTLY WIN on KTC — no break-even, no loss.
    if opp_appeal <= 0:
        return None

    # Filter out junk trades: at least one meaningful asset on each side
    if all(a.model_value < JUNK_THRESHOLD for a in give):
        return None
    if all(a.model_value < JUNK_THRESHOLD for a in receive):
        return None

    # Arbitrage score: how much we gain on our board while the opponent
    # sees a fair/favorable deal on KTC.
    # Higher = better arbitrage.
    board_gain_norm = board_delta / max(give_model, 1)
    ktc_delta = give_ktc - recv_ktc  # positive = opponent gets more KTC than they give

    # Core arbitrage: we win on model, opponent wins on KTC
    f_board_edge = board_gain_norm * 50
    f_ktc_appeal = opp_appeal * 30
    f_positive_bonus = (1.0 if board_delta > 0 else 0.0) * 10
    arbitrage = f_board_edge + f_ktc_appeal + f_positive_bonus

    # Partial coverage: severe demotion — these cannot compete with full-KTC trades
    if coverage == "partial":
        arbitrage *= 0.3
        arbitrage = min(arbitrage, PARTIAL_KTC_ARBITRAGE_CAP)

    # ── Confidence factor (source coverage × KTC coverage) ───────────
    all_assets = give + receive
    source_counts = [a.source_count for a in all_assets if a.source_count > 0]
    if source_counts:
        avg_sources = sum(source_counts) / len(source_counts)
        source_confidence = min(1.0, avg_sources / CONFIDENCE_SOURCE_BASELINE)
    else:
        # Unknown source counts — assume reasonable
        source_confidence = 1.0
    ktc_confidence = 1.0 if coverage == "full" else 0.7
    confidence = source_confidence * ktc_confidence

    # Apply confidence as a soft multiplier (floor at 0.7 to avoid killing trades)
    f_confidence_mult = 0.7 + 0.3 * confidence
    arbitrage *= f_confidence_mult

    # ── Absolute-value bonus ────────────────────────────────────────
    # Larger, more impactful trades rank above trivially small ones
    # with similar edge percentages.
    value_moved = min(give_model, recv_model)
    f_value_scale = min(1.0, value_moved / 5000) * 5
    arbitrage += f_value_scale

    # Penalize larger packages (simplicity bonus)
    pkg_size = len(give) + len(receive)
    f_simplicity = -(pkg_size - 2) * 3
    arbitrage += f_simplicity

    # ── Build explainability fields ──────────────────────────────────
    conf_tier = _confidence_tier(confidence)
    flags.append(f"{conf_tier}_confidence")
    edge_lbl = _edge_label(board_gain_norm)
    pkg_size_str = f"{len(give)}-for-{len(receive)}"
    summary = _build_summary(
        board_delta, board_gain_norm, opp_appeal,
        coverage, conf_tier, edge_lbl, pkg_size_str,
    )
    ranking_factors = {
        "boardEdge": round(f_board_edge, 2),
        "ktcAppeal": round(f_ktc_appeal, 2),
        "positiveBonus": round(f_positive_bonus, 2),
        "confidenceMultiplier": round(f_confidence_mult, 3),
        "valueScale": round(f_value_scale, 2),
        "simplicityPenalty": round(f_simplicity, 2),
        "rosterFitBonus": 0.0,  # populated in find_trades if applicable
    }

    tc = TradeCandidate(
        give=give,
        receive=receive,
        give_model_total=give_model,
        receive_model_total=recv_model,
        give_ktc_total=give_ktc,
        receive_ktc_total=recv_ktc,
        board_delta=board_delta,
        ktc_delta=ktc_delta,
        opponent_ktc_appeal=opp_appeal,
        arbitrage_score=arbitrage,
        ktc_coverage=coverage,
        confidence_score=confidence,
        confidence_tier=conf_tier,
        edge_label=edge_lbl,
        summary=summary,
        ranking_factors=ranking_factors,
        flags=flags,
    )
    return tc


def _generate_1for1(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate all viable 1-for-1 trades."""
    results: list[TradeCandidate] = []
    for mine in my_assets:
        if mine.model_value < MIN_ASSET_VALUE:
            continue
        for theirs in opp_assets:
            if theirs.model_value < MIN_ASSET_VALUE:
                continue
            tc = _score_trade([mine], [theirs])
            if tc is not None:
                results.append(tc)
    return results


def _generate_2for1(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate viable 2-for-1 trades (I give 2, get 1)."""
    results: list[TradeCandidate] = []
    # Limit combinations for performance
    my_tradeable = [a for a in my_assets if a.model_value >= MIN_ASSET_VALUE]
    opp_tradeable = [a for a in opp_assets if a.model_value >= MIN_ASSET_VALUE]
    if len(my_tradeable) < 2:
        return results

    for pair in combinations(my_tradeable[:30], 2):
        for theirs in opp_tradeable[:30]:
            tc = _score_trade(list(pair), [theirs])
            if tc is not None:
                results.append(tc)
    return results


def _generate_1for2(
    my_assets: list[Asset],
    opp_assets: list[Asset],
) -> list[TradeCandidate]:
    """Generate viable 1-for-2 trades (I give 1, get 2)."""
    results: list[TradeCandidate] = []
    my_tradeable = [a for a in my_assets if a.model_value >= MIN_ASSET_VALUE]
    opp_tradeable = [a for a in opp_assets if a.model_value >= MIN_ASSET_VALUE]
    if len(opp_tradeable) < 2:
        return results

    for mine in my_tradeable[:30]:
        for pair in combinations(opp_tradeable[:30], 2):
            tc = _score_trade([mine], list(pair))
            if tc is not None:
                results.append(tc)
    return results


def _deduplicate(trades: list[TradeCandidate]) -> list[TradeCandidate]:
    """Remove duplicate trade packages (same assets, different order)."""
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    result: list[TradeCandidate] = []
    for tc in trades:
        key = (
            tuple(sorted(a.name for a in tc.give)),
            tuple(sorted(a.name for a in tc.receive)),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(tc)
    return result


def find_trades(
    players: dict[str, Any],
    my_team: str,
    opponent_teams: list[str],
    sleeper_teams: list[dict[str, Any]],
    *,
    max_results: int = MAX_RESULTS,
    ktc_top_n: int = KTC_TOP_N_FILTER,
) -> dict[str, Any]:
    """
    Find board-arbitrage trades.

    Parameters
    ----------
    players : dict
        Raw players dict from the live data payload.
    my_team : str
        Name of my Sleeper team.
    opponent_teams : list[str]
        Names of opponent teams to trade with.
    sleeper_teams : list[dict]
        Full Sleeper teams array from the data payload.
    max_results : int
        Maximum number of results to return.
    ktc_top_n : int
        Only include players ranked in the KTC top N. Set to 0 to disable.

    Returns
    -------
    dict with trades, metadata, and any warnings.
    """
    pool = build_asset_pool(players, ktc_top_n=ktc_top_n)
    pool_by_name: dict[str, Asset] = {}
    for a in pool:
        pool_by_name[a.name] = a

    my_roster = _resolve_roster(my_team, sleeper_teams, pool_by_name)
    if not my_roster:
        return {"error": f"Could not resolve team '{my_team}' or roster is empty.",
                "trades": [], "metadata": {}}

    my_names = {a.name for a in my_roster}
    all_trades: list[TradeCandidate] = []
    opponents_analyzed = 0
    warnings: list[str] = []

    # Track KTC coverage
    ktc_coverage_count = sum(1 for a in pool if a.has_ktc)
    ktc_coverage_pct = ktc_coverage_count / max(len(pool), 1)
    if ktc_coverage_pct < 0.5:
        warnings.append(
            f"KTC coverage is low ({ktc_coverage_pct:.0%} of assets). "
            "Some trades may have partial or no KTC scoring."
        )

    for opp_name in opponent_teams:
        if opp_name == my_team:
            continue
        opp_roster = _resolve_roster(opp_name, sleeper_teams, pool_by_name)
        if not opp_roster:
            warnings.append(f"Could not resolve opponent team '{opp_name}'.")
            continue

        # Exclude any assets that are on my team from opponent pool
        opp_filtered = [a for a in opp_roster if a.name not in my_names]
        if not opp_filtered:
            continue
        opponents_analyzed += 1

        # Generate candidates for each trade shape
        all_trades.extend(_generate_1for1(my_roster, opp_filtered))
        all_trades.extend(_generate_2for1(my_roster, opp_filtered))
        all_trades.extend(_generate_1for2(my_roster, opp_filtered))

    # Deduplicate
    all_trades = _deduplicate(all_trades)

    # ── Light roster-fit adjustment ──────────────────────────────────
    # Slightly reward trades that shed surplus positions or fill weak ones.
    my_pos_counts: dict[str, int] = {}
    for a in my_roster:
        if a.position:
            my_pos_counts[a.position] = my_pos_counts.get(a.position, 0) + 1

    for tc in all_trades:
        fit_bonus = 0.0
        fit_reasons: list[str] = []
        for a in tc.give:
            if my_pos_counts.get(a.position, 0) >= ROSTER_SURPLUS_THRESHOLD:
                fit_bonus += 1.0
                fit_reasons.append(f"sheds {a.position} surplus")
        for a in tc.receive:
            if my_pos_counts.get(a.position, 0) <= ROSTER_WEAK_THRESHOLD:
                fit_bonus += 1.5
                fit_reasons.append(f"fills {a.position} need")
        if fit_bonus > 0:
            tc.arbitrage_score += fit_bonus
            tc.flags.append("roster_fit")
            tc.ranking_factors["rosterFitBonus"] = round(fit_bonus, 2)
            tc.summary += " Roster fit: " + ", ".join(fit_reasons) + "."

    # Rank
    all_trades.sort(key=lambda t: t.arbitrage_score, reverse=True)

    # Keep only positive-arbitrage trades with positive board delta
    ranked = [t for t in all_trades if t.arbitrage_score > 0 and t.board_delta > 0]

    # ── Enforce full-KTC priority in top results ─────────────────────
    # Partial-KTC trades are pushed below PARTIAL_KTC_MAX_RANK so
    # premium recommendation slots are reserved for trustworthy trades.
    full_ktc = [t for t in ranked if t.ktc_coverage == "full"]
    partial_ktc = [t for t in ranked if t.ktc_coverage != "full"]
    if len(full_ktc) >= PARTIAL_KTC_MAX_RANK:
        # Enough full-KTC trades to fill top slots — append partials after
        ranked = full_ktc + partial_ktc
    else:
        # Not enough full-KTC — partials fill remaining slots after the full ones
        ranked = full_ktc + partial_ktc

    capped = ranked[:max_results]

    return {
        "trades": [t.to_dict() for t in capped],
        "metadata": {
            "myTeam": my_team,
            "opponentTeams": opponent_teams,
            "opponentsAnalyzed": opponents_analyzed,
            "myRosterSize": len(my_roster),
            "totalCandidatesEvaluated": len(all_trades),
            "totalQualified": len(ranked),
            "returned": len(capped),
            "assetPoolSize": len(pool),
            "ktcTopNFilter": ktc_top_n,
            "ktcCoveragePercent": round(ktc_coverage_pct * 100, 1),
        },
        "warnings": warnings,
    }
