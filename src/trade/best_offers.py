"""Best Trade to Send Each Team — C7-BEST-TRADE (owner backlog spec §2.3).

For every other team in the league, exactly one best trade to send them, or an
honest "No qualifying trade found".  A CONSUMER, not a second trade finder:

* candidates come from the finder's own enumeration (``finder.generate_packages``
  over the canonical substrate, C3-TOPO-01 topology: player counts within one,
  picks not counted) and its posture-aware pick path (picks only when both
  teams' Competitive Posture makes them mutually beneficial — never filler);
* recommendation constraints (saved protections, LOCK / EXCLUDE) are the one
  owner's (``src/trade/constraints``), applied DURING enumeration;
* the canonical verdict is the calculator's own (``analyze_trade.equity_verdict``:
  ``rankDerivedValue`` + exact KTC Value Adjustment);
* external qualification is the market owner's
  (``cross_market.external_package_verdicts``): the opponent must be even or
  better on at least one approved calculator that natively prices EVERY asset;
* lineup impact is the canonical lineup solver's (``roster_intel.marginal``).

Hard rules (all must hold — they are filters, never weights):

1. topology ``abs(players_send - players_receive) <= 1``, picks excluded;
2. picks only through the posture-aware path;
3. a canonical WIN for us (an "even" calculator result does not qualify);
4. the opponent even or better on KTC Market or IDP Trade Calculator;
5. whole-package native coverage on that calculator — missing, derived or
   withheld values never count;
6. one result per opponent, or "No qualifying trade found".

RANKING among qualifying candidates is a **declared PRIOR**
(``config/trade/best_offers_prior.json``, status ``PRIOR_UNVALIDATED``): the
owner spec makes exact weights evidence-gated, so every factor, weight and the
config version are echoed on each offer, and each run is recorded for later
validation.  The prior prefers a mutually defensible offer over the largest
calculator exploit.

Recommendation only.  Nothing here sends, drafts on Sleeper, or mutates a
league.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from src.league_intel.cross_market import (
    CALCULATOR_LABELS,
    EXTERNAL_EVEN_TOLERANCE_PCT,
    best_qualifying_verdict,
    external_package_verdicts,
)
from src.trade import finder
from src.trade.analyze_trade import equity_verdict

__all__ = [
    "BEST_OFFERS_RUN_LOG_DIR",
    "BEST_OFFERS_VERSION",
    "BestOfferCandidate",
    "NO_RESULT_REASONS",
    "build_best_offers",
    "lineup_delta_from_bundle",
    "load_ranking_prior",
    "record_run",
]

BEST_OFFERS_VERSION = "best-offers.2026-10-14.v1"

_REPO = Path(__file__).resolve().parents[2]
_PRIOR_PATH = _REPO / "config" / "trade" / "best_offers_prior.json"

#: Box-local, gitignored native run log (append-only JSONL, one file per UTC
#: month).  The declared-prior ranking is evidence-gated, so every run records
#: what it knew: board stamp, prior id/weights, constraint fingerprint, every
#: opponent's qualifying count, the chosen package key and its factors.  It is
#: the producer's OWN store; an Adaptive Learning receipt (AL-P5) points into
#: it rather than copying it.  Private league data — never committed.
BEST_OFFERS_RUN_LOG_DIR = _REPO / "data" / "trade" / "best_offers"

#: Ordered: the FIRST reason that applies is the one reported, so a manager
#: reads the most fundamental blocker.
NO_RESULT_REASONS = (
    "no_priced_outgoing_assets",
    "all_outgoing_assets_constrained",
    "lock_conflicts_with_protection",
    "locked_player_unavailable",
    "opponent_roster_unresolved",
    "no_plausible_package",
    "no_canonical_win",
    "no_whole_package_coverage",
    "external_provider_withheld",
    "opponent_not_even_on_any_calculator",
)

_NO_RESULT_TEXT = {
    "no_priced_outgoing_assets": (
        "None of your players carries a market value in this scan, so nothing can be offered "
        "and checked against an external calculator."
    ),
    "all_outgoing_assets_constrained": (
        "Every asset you could send is protected or excluded for this league."
    ),
    "lock_conflicts_with_protection": (
        "A locked player is also protected, excluded or team-protected, so no package can "
        "include him."
    ),
    "locked_player_unavailable": "A locked player is not on your tradeable roster.",
    "opponent_roster_unresolved": "This team's roster could not be read.",
    "no_plausible_package": (
        "Every package this search could build failed the plausibility gates (fire-sale or "
        "junk shapes)."
    ),
    "no_canonical_win": (
        "No package is a clear win for you on the canonical board after the Value " "Adjustment."
    ),
    "no_whole_package_coverage": (
        "No approved external calculator prices every asset in the packages that win for "
        "you, so none can show the other side is treated fairly."
    ),
    "external_provider_withheld": (
        "The only calculator that covers these packages is currently withheld as stale."
    ),
    "opponent_not_even_on_any_calculator": (
        "Every package that wins for you leaves the other side behind on both approved "
        "calculators."
    ),
}


def load_ranking_prior(path: Path | None = None) -> dict[str, Any]:
    """The declared ranking prior.  Never tuned in code — edit the config."""
    data = json.loads((path or _PRIOR_PATH).read_text(encoding="utf-8"))
    weights = {str(k): float(v) for k, v in (data.get("weights") or {}).items()}
    return {**data, "weights": weights}


@dataclass
class BestOfferCandidate:
    """A qualifying candidate.  Field names mirror ``finder.TradeCandidate``
    where the finder's posture-aware pick path reads them."""

    give: list[Any]
    receive: list[Any]
    equity: dict[str, Any]
    external: Any
    external_all: list[Any]
    factors: dict[str, float | None]
    arbitrage_score: float = 0.0  # the prior score; named for the finder seam
    flags: list[str] = field(default_factory=list)
    ranking_factors: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    lineup: dict[str, Any] | None = None
    capacity: Any = None

    @property
    def has_pick(self) -> bool:
        return any(a.is_pick for a in (*self.give, *self.receive))

    def package_key(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return (
            tuple(sorted((a.asset_id or a.name) for a in self.give)),
            tuple(sorted((a.asset_id or a.name) for a in self.receive)),
        )


# ── Contract rows (for the external calculators) ──────────────────────────


def _row_index(contract: Mapping[str, Any] | None) -> dict[str, list[Mapping[str, Any]]]:
    out: dict[str, list[Mapping[str, Any]]] = {}
    for row in (contract or {}).get("playersArray") or []:
        if not isinstance(row, Mapping):
            continue
        for key in {row.get("displayName"), row.get("canonicalName")}:
            if key:
                out.setdefault(str(key).strip().lower(), []).append(row)
    return out


def _row_for(asset: Any, index: Mapping[str, list[Mapping[str, Any]]]) -> Mapping[str, Any] | None:
    """The canonical board row an asset is priced from, or ``None``.

    ``None`` — which makes every calculator ``incomplete`` — for a pick whose
    market side was DERIVED (unknown slot: a tier average, not a native price),
    for an asset with no row, and for a name shared by rows of different
    positions that the asset's own position cannot separate.  Fail closed:
    a guessed row would let the wrong player's price qualify a trade.
    """
    if getattr(asset, "market_derivation", None) is not None:
        return None
    name = str(getattr(asset, "board_row", None) or getattr(asset, "name", "") or "")
    rows = index.get(name.strip().lower()) or []
    if len(rows) == 1:
        return rows[0]
    position = str(getattr(asset, "position", "") or "").upper()
    matching = [r for r in rows if str(r.get("position") or "").upper() == position]
    return matching[0] if len(matching) == 1 else None


# ── Lineup impact (canonical lineup solver) ───────────────────────────────


def lineup_delta_from_bundle(bundle: Any) -> Callable[..., dict[str, Any] | None]:
    """``delta(our_owner, their_owner, give_names, receive_names)`` over the
    league bundle's rest-of-season pools, via ``roster_intel.marginal``.

    Each side's change in OPTIMAL STARTING-LINEUP points (the exact lineup
    solver, C2-U1).  Rest-of-season, so it is the seasonal lane — a separately
    named component, never mixed into canonical dynasty value.  Picks score
    nothing in a lineup.  A traded name the pool does not carry is reported,
    and the delta is withheld rather than computed on a guessed roster.
    """
    from src.roster_intel.marginal import optimal_score  # noqa: PLC0415

    slots = list(bundle.inputs.slots)
    before: dict[str, float] = {}

    def _score(owner: str, pool: Sequence[Any]) -> float:
        return optimal_score(list(pool), slots)

    def delta(
        our_owner: str, their_owner: str, give_names: Sequence[str], receive_names: Sequence[str]
    ) -> dict[str, Any] | None:
        ours, theirs = bundle.team(our_owner), bundle.team(their_owner)
        if ours is None or theirs is None:
            return None
        give = {n.strip().lower() for n in give_names}
        recv = {n.strip().lower() for n in receive_names}
        ours_by = {p.canonical_name.strip().lower(): p for p in ours.pool}
        theirs_by = {p.canonical_name.strip().lower(): p for p in theirs.pool}
        unmatched = sorted((give - ours_by.keys()) | (recv - theirs_by.keys()))
        if unmatched:
            return {"available": False, "reason": "player_not_in_lineup_pool", "names": unmatched}
        for owner, team in ((our_owner, ours), (their_owner, theirs)):
            if owner not in before:
                before[owner] = _score(owner, team.pool)
        our_after = [p for k, p in ours_by.items() if k not in give] + [theirs_by[k] for k in recv]
        their_after = [p for k, p in theirs_by.items() if k not in recv] + [
            ours_by[k] for k in give
        ]
        return {
            "available": True,
            "basis": "optimal starting lineup, rest-of-season points (canonical lineup solver)",
            "ourDelta": round(_score(our_owner, our_after) - before[our_owner], 2),
            "theirDelta": round(_score(their_owner, their_after) - before[their_owner], 2),
            "ourBefore": round(before[our_owner], 2),
            "theirBefore": round(before[their_owner], 2),
        }

    return delta


# ── The objective ─────────────────────────────────────────────────────────


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _need_fit(assets: Sequence[Any], needs: set[str] | None) -> float | None:
    """Share of the PLAYERS received that land on a rated need, or ``None``."""
    if needs is None:
        return None
    players = [a for a in assets if not a.is_pick]
    if not players:
        return 0.0
    return sum(1 for a in players if a.position in needs) / len(players)


def _factors(
    give: Sequence[Any],
    receive: Sequence[Any],
    equity: Mapping[str, Any],
    verdict: Any,
    prior: Mapping[str, Any],
    our_needs: set[str] | None,
    their_needs: set[str] | None,
) -> dict[str, float | None]:
    scale = prior.get("scales") or {}
    edge_pct = equity["vaAdjustedGap"] / max(float(equity["sendingAdjusted"]), 1.0)
    canonical = _clip01(edge_pct / float(scale.get("canonicalEdgeSaturationPct", 30.0)) * 100.0)
    # A qualifying verdict always carries a margin (best_qualifying_verdict
    # admits none without one), so it is read directly — never defaulted.
    comfort = _clip01(
        max(0.0, float(verdict.margin_pct)) / float(scale.get("externalComfortSaturationPct", 15.0))
    )
    sources = [a.source_count for a in (*give, *receive) if a.source_count > 0]
    confidence = (
        _clip01((sum(sources) / len(sources)) / float(scale.get("confidenceSourceBaseline", 8.0)))
        if sources
        else None
    )
    size = len(give) + len(receive)
    return {
        "canonicalEdge": round(canonical, 4),
        "externalComfort": round(comfort, 4),
        "mutualBalance": round(min(canonical, comfort), 4),
        "ourNeedFit": _need_fit(receive, our_needs),
        "theirNeedFit": _need_fit(give, their_needs),
        "simplicity": round(_clip01(1.0 - (size - 2) / 4.0), 4),
        "confidence": round(confidence, 4) if confidence is not None else None,
        "lineupImpact": None,
        "forcedDropCost": None,
    }


def _score(factors: Mapping[str, float | None], weights: Mapping[str, float]) -> float:
    """Σ wᵢ·fᵢ over AVAILABLE factors; a missing factor contributes nothing.

    ``forcedDropCost`` is a cost (its weight is applied as a subtraction), and
    an unknown cost is never read as free — it simply is not subtracted, and
    the offer's caveats say so.
    """
    total = 0.0
    for name, w in weights.items():
        f = factors.get(name)
        if f is None:
            continue
        total += -w * f if name == "forcedDropCost" else w * f
    return round(total, 6)


# ── Per-opponent search ───────────────────────────────────────────────────


def _new_diag() -> dict[str, Any]:
    return {
        "enumerated": 0,
        "plausible": 0,
        "canonicalWins": 0,
        "covered": 0,
        "qualified": 0,
        "rejectedBy": {
            "no_plausible_package": 0,
            "no_canonical_win": 0,
            "no_whole_package_coverage": 0,
            "external_provider_withheld": 0,
            "opponent_not_even_on_any_calculator": 0,
        },
    }


def _scorer(
    index: Mapping[str, list[Mapping[str, Any]]],
    prior: Mapping[str, Any],
    our_needs: set[str] | None,
    their_needs: set[str] | None,
    diag: dict[str, Any],
) -> Callable[[list[Any], list[Any]], BestOfferCandidate | None]:
    weights = prior["weights"]
    row_memo: dict[int, Mapping[str, Any] | None] = {}

    def row(asset: Any) -> Mapping[str, Any] | None:
        key = id(asset)
        if key not in row_memo:
            row_memo[key] = _row_for(asset, index)
        return row_memo[key]

    def score(give: list[Any], receive: list[Any]) -> BestOfferCandidate | None:
        diag["enumerated"] += 1
        ok, plaus_flags = finder.plausibility_check(give, receive)
        if not ok:
            diag["rejectedBy"]["no_plausible_package"] += 1
            return None
        diag["plausible"] += 1
        equity = equity_verdict(
            [float(a.model_value) for a in give], [float(a.model_value) for a in receive]
        )
        if not equity["win"]:
            diag["rejectedBy"]["no_canonical_win"] += 1
            return None
        diag["canonicalWins"] += 1
        verdicts = external_package_verdicts(
            [row(a) for a in give],  # the opponent RECEIVES what we give
            [row(a) for a in receive],
        )
        if not any(v.coverage == "complete" for v in verdicts):
            if any(v.coverage == "withheld" for v in verdicts):
                diag["rejectedBy"]["external_provider_withheld"] += 1
            else:
                diag["rejectedBy"]["no_whole_package_coverage"] += 1
            return None
        diag["covered"] += 1
        best = best_qualifying_verdict(verdicts)
        if best is None:
            diag["rejectedBy"]["opponent_not_even_on_any_calculator"] += 1
            return None
        diag["qualified"] += 1
        factors = _factors(give, receive, equity, best, prior, our_needs, their_needs)
        return BestOfferCandidate(
            give=list(give),
            receive=list(receive),
            equity=equity,
            external=best,
            external_all=verdicts,
            factors=factors,
            arbitrage_score=_score(factors, weights),
            flags=list(plaus_flags),
        )

    return score


def _no_result_reason(diag: Mapping[str, Any]) -> str:
    """The most fundamental blocker, in the order a manager would ask."""
    if diag["enumerated"] == 0:
        return "no_plausible_package"
    if diag["plausible"] == 0:
        return "no_plausible_package"
    if diag["canonicalWins"] == 0:
        return "no_canonical_win"
    if diag["covered"] == 0:
        if (
            diag["rejectedBy"]["external_provider_withheld"]
            and not diag["rejectedBy"]["no_whole_package_coverage"]
        ):
            return "external_provider_withheld"
        return "no_whole_package_coverage"
    return "opponent_not_even_on_any_calculator"


def _names(assets: Sequence[Any]) -> list[str]:
    return [str(getattr(a, "board_row", None) or a.name) for a in assets if not a.is_pick]


def _asset_dict(a: Any) -> dict[str, Any]:
    return {
        "name": a.name,
        "position": a.position,
        "team": a.team,
        "isPick": bool(a.is_pick),
        "modelValue": a.model_value,
        **({"boardRowName": a.board_row} if getattr(a, "board_row", None) else {}),
        **({"assetId": a.asset_id} if getattr(a, "asset_id", "") else {}),
    }


def _why_us(c: BestOfferCandidate, our_needs: set[str] | None) -> str:
    parts = [
        f"A clear win on our board: +{c.equity['vaAdjustedGap']:,} after the Value Adjustment "
        f"({c.equity['magnitude']})."
    ]
    if our_needs:
        filled = sorted(
            {a.position for a in c.receive if not a.is_pick and a.position in our_needs}
        )
        if filled:
            parts.append(f"Adds help at {', '.join(filled)}, a rated need.")
    if c.lineup and c.lineup.get("available") and c.lineup.get("ourDelta") is not None:
        d = c.lineup["ourDelta"]
        parts.append(f"Starting lineup {'+' if d >= 0 else ''}{d:.1f} rest-of-season points.")
    return " ".join(parts)


def _why_them(c: BestOfferCandidate, their_needs: set[str] | None, pair: str | None) -> str:
    v = c.external
    if v.result == "win":
        lead = f"{v.label} has them ahead by {v.margin_pct:.1f}% after its package adjustment."
    else:
        lead = f"{v.label} grades it even for them after its package adjustment."
    parts = [lead]
    if their_needs:
        filled = sorted({a.position for a in c.give if not a.is_pick and a.position in their_needs})
        if filled:
            parts.append(f"It sends them {', '.join(filled)}, where their roster is weak.")
    if pair and c.has_pick:
        parts.append(f"The pick fits the two teams' directions ({pair}).")
    return " ".join(parts)


def _caveats(c: BestOfferCandidate, prior: Mapping[str, Any]) -> list[str]:
    out = [
        f"Ranking is a declared prior ({prior.get('status')}), not a validated model.",
    ]
    if c.external.calculator != next(iter(CALCULATOR_LABELS)):
        out.append(
            "IDP Trade Calculator's own package rule is not published; its verdict uses the "
            "KTC Value Adjustment as a declared approximation."
        )
    if c.factors.get("forcedDropCost") is None and c.capacity is not None:
        out.append("The roster cost of any forced release could not be determined.")
    if c.lineup is not None and not c.lineup.get("available"):
        out.append("Lineup impact unavailable: " + str(c.lineup.get("reason")))
    for v in c.external_all:
        if v.coverage == "withheld":
            out.append(f"{v.label} is withheld as stale for an asset in this trade.")
    return out


def _confidence_label(c: BestOfferCandidate) -> str:
    covered = sum(1 for v in c.external_all if v.coverage == "complete")
    conf = c.factors.get("confidence")
    if conf is not None and conf >= 0.75 and covered >= 2:
        return "high"
    if conf is not None and conf >= 0.5:
        return "moderate"
    return "low"


def build_best_offers(
    players: dict[str, Any],
    my_team: str,
    sleeper_teams: list[dict[str, Any]],
    *,
    contract: Mapping[str, Any],
    constraints_for: Callable[[str], Any] | None = None,
    use_team_context: bool = True,
    postures: Mapping[str, str] | None = None,
    pick_forecasts: Mapping[int, Any] | None = None,
    needs_by_owner: Mapping[str, set[str]] | None = None,
    lineup_delta: Callable[..., dict[str, Any] | None] | None = None,
    capacity_for: Callable[[str, list[Any], list[Any]], tuple[Any, float | None]] | None = None,
    opponents: Sequence[str] | None = None,
    prior: Mapping[str, Any] | None = None,
    market_top_n: int | None = None,
) -> dict[str, Any]:
    """One best offer (or an explained no-result) per opponent.

    ``constraints_for(opponent)`` returns the requester's resolved constraints
    for that opponent's card (saved protections + that card's LOCK / EXCLUDE).
    ``needs_by_owner`` / ``postures`` / ``lineup_delta`` / ``capacity_for`` are
    Team Context and are ignored when ``use_team_context`` is False — Asset-only
    mode ranks on asset value and external acceptability alone.
    """
    from src.trade.constraints import (  # noqa: PLC0415
        blocked_outgoing,
        outgoing_eligibility,
        resolve_locked_outgoing,
    )

    prior = dict(prior or load_ranking_prior())
    weights = prior["weights"]
    top_k = int((prior.get("search") or {}).get("lineupRerankTopK", 5))

    board_values = finder.board_values_from_contract(contract)
    positions = finder.positions_from_contract(contract)
    pool = finder.build_asset_pool(
        players,
        market_top_n=finder.MARKET_TOP_N_FILTER if market_top_n is None else market_top_n,
        board_values=board_values,
        positions=positions,
    )
    pool_by_name = {a.name: a for a in pool}
    index = _row_index(contract)
    owner_of = {str(t.get("name") or ""): str(t.get("ownerId") or "") for t in sleeper_teams}

    my_roster = finder.resolve_roster(my_team, sleeper_teams, pool_by_name)
    team_exists = any(str(t.get("name") or "") == my_team for t in sleeper_teams)
    base = {
        "version": BEST_OFFERS_VERSION,
        "myTeam": my_team,
        "action": "recommend_only",
        "rankingMethod": {
            "id": prior.get("id"),
            "status": prior.get("status"),
            "weights": weights,
            "configPath": "config/trade/best_offers_prior.json",
        },
        "qualificationRules": {
            "canonicalWin": "VA-adjusted canonical gap > 0 and outside the even band",
            "externalCalculators": list(CALCULATOR_LABELS.values()),
            "evenTolerancePct": EXTERNAL_EVEN_TOLERANCE_PCT,
            "coverage": "whole-package native values on the qualifying calculator",
            "topology": "abs(players sent - players received) <= 1; picks not counted",
            "picks": "only via the posture-aware path, never as filler",
        },
        "teamContext": {"applied": bool(use_team_context)},
    }
    if not team_exists:
        return {**base, "error": "my_team_unresolved", "opponents": []}

    my_owner = owner_of.get(my_team, "")
    use_ctx = bool(use_team_context)
    our_needs = (needs_by_owner or {}).get(my_owner) if use_ctx and needs_by_owner else None
    pick_on = bool(use_ctx and postures and postures.get(my_team))
    my_picks_all: list[Any] = []
    unfiltered: dict[str, Any] | None = None
    if pick_on:
        unfiltered = {a.name: a for a in finder.build_asset_pool(players, market_top_n=0)}
        me_team = next((t for t in sleeper_teams if t.get("name") == my_team), None)
        my_picks_all, _stats = finder.owned_pick_assets(
            me_team, contract, players, pool_by_name, pick_forecasts, unfiltered
        )

    wanted = [
        str(t.get("name") or "")
        for t in sleeper_teams
        if str(t.get("name") or "") and str(t.get("name") or "") != my_team
    ]
    if opponents:
        allowed = set(opponents)
        wanted = [n for n in wanted if n in allowed]

    results: list[dict[str, Any]] = []
    if not my_roster:
        # The team exists but nothing on it is priced in the scan's market
        # pool: an explained card per opponent, never an empty page.
        for opp in wanted:
            results.append(
                {
                    "team": opp,
                    "posture": None,
                    "offer": None,
                    "refinement": None,
                    **_no_result("no_priced_outgoing_assets"),
                }
            )
        return {**base, "outgoingConcentration": {}, "opponents": results}
    for opp in wanted:
        constraints = constraints_for(opp) if constraints_for else None
        card: dict[str, Any] = {
            "team": opp,
            "posture": (postures or {}).get(opp) if use_ctx else None,
            "status": "no_result",
            "offer": None,
            "refinement": constraints.to_dict() if constraints is not None else None,
        }
        blocked = blocked_outgoing(my_roster, constraints)
        if my_roster and len(blocked) >= len(my_roster):
            card.update(_no_result("all_outgoing_assets_constrained", constrained=True))
            results.append(card)
            continue
        lock = resolve_locked_outgoing(my_roster, constraints)
        if not lock.satisfiable:
            card.update(_no_result(lock.no_result_reason, constrained=True))
            card["lockedOutgoing"] = lock.to_dict()
            results.append(card)
            continue
        opp_roster = finder.resolve_roster(opp, sleeper_teams, pool_by_name)
        owned = {a.name for a in my_roster}
        opp_roster = [a for a in opp_roster if a.name not in owned]
        if not opp_roster:
            card.update(_no_result("opponent_roster_unresolved"))
            results.append(card)
            continue

        policy = outgoing_eligibility(my_roster, constraints)
        their_needs = (needs_by_owner or {}).get(owner_of.get(opp, "")) if use_ctx else None
        diag = _new_diag()
        score = _scorer(index, prior, our_needs, their_needs, diag)
        cands, enum_report = finder.generate_packages(
            my_roster,
            opp_roster,
            policy,
            equal_count_only=False,
            **({"required_send": list(lock.required)} if lock.required else {}),
            score=score,
        )
        pair = None
        if pick_on and postures.get(opp):
            opp_picks: list[Any] = []
            if (
                postures.get(my_team) in finder.FUTURE_TILTING_POSTURES
                and postures.get(opp) == "PUSH"
            ):
                opp_team = next((t for t in sleeper_teams if t.get("name") == opp), None)
                opp_picks, _ = finder.owned_pick_assets(
                    opp_team, contract, players, pool_by_name, pick_forecasts, unfiltered
                )
            my_picks = [a for a in my_picks_all if constraints is None or constraints.may_send(a)]
            with_picks, pair = finder.posture_pick_packages(
                my_roster,
                opp_roster,
                my_picks,
                opp_picks,
                postures.get(my_team),
                postures.get(opp),
                policy,
                equal_count_only=False,
                **({"required_send": list(lock.required)} if lock.required else {}),
                score=score,
            )
            cands.extend(with_picks)

        # One per package (the pick path can re-find a player-only core).
        seen: dict[tuple, BestOfferCandidate] = {}
        for c in cands:
            k = c.package_key()
            if k not in seen or c.arbitrage_score > seen[k].arbitrage_score:
                seen[k] = c
        ranked = sorted(
            seen.values(),
            key=lambda c: (-c.arbitrage_score, c.has_pick, c.package_key()),
        )
        if not ranked:
            card.update(
                _no_result(
                    _no_result_reason(diag),
                    constrained=bool(blocked or (constraints and constraints.locked_outgoing)),
                )
            )
            card["diagnostics"] = {**diag, "enumeration": enum_report}
            results.append(card)
            continue

        # Roster-aware rerank of the top K: lineup impact (both sides) and the
        # cost of releases the trade forces.  Team Context only.
        head = ranked[:top_k]
        if use_ctx:
            for c in head:
                if lineup_delta is not None:
                    c.lineup = lineup_delta(
                        my_owner, owner_of.get(opp, ""), _names(c.give), _names(c.receive)
                    )
                    if c.lineup and c.lineup.get("available") and c.lineup.get("ourBefore"):
                        # A lineup with no recorded baseline is not scored at
                        # all (factor stays None) rather than against zero.
                        base_pts = max(float(c.lineup["ourBefore"]), 1.0)
                        c.factors["lineupImpact"] = round(
                            max(-1.0, min(1.0, float(c.lineup["ourDelta"]) / base_pts * 10.0)), 4
                        )
                if capacity_for is not None:
                    # ``capacity_for`` returns ``(RosterCapacity | None,
                    # forced-drop cost | None)`` — ``None`` cost is UNKNOWN,
                    # never free (``roster_capacity.forced_drop_cost``).
                    c.capacity, cost = capacity_for(opp, c.give, c.receive)
                    if cost is not None:
                        give_model = max(sum(a.model_value for a in c.give), 1)
                        c.factors["forcedDropCost"] = round(_clip01(cost / give_model), 4)
                c.arbitrage_score = _score(c.factors, weights)
            head.sort(key=lambda c: (-c.arbitrage_score, c.has_pick, c.package_key()))
        best = head[0]
        card.update(
            {
                "status": "qualified",
                "offer": _offer_dict(best, our_needs, their_needs, pair, prior),
                "diagnostics": {**diag, "enumeration": enum_report},
            }
        )
        results.append(card)

    # One player can only be traded once.  Each card is an independent best
    # offer, so the same outgoing asset may headline several; say so on every
    # card it appears in rather than presenting eleven offers as eleven
    # simultaneously available trades.
    usage: dict[str, int] = {}
    for r in results:
        for a in (r.get("offer") or {}).get("send") or []:
            usage[a["name"]] = usage.get(a["name"], 0) + 1
    for r in results:
        offer = r.get("offer")
        if offer:
            offer["outgoingAlsoOfferedTo"] = {
                a["name"]: usage[a["name"]] - 1 for a in offer["send"] if usage[a["name"]] > 1
            }
    concentration = {k: v for k, v in sorted(usage.items()) if v > 1}

    order = {"qualified": 0, "no_result": 1}
    results.sort(
        key=lambda r: (
            order.get(r["status"], 2),
            # No-result cards already sort last by status; only qualified
            # offers (which always carry a score) are ordered by it.
            -(r["offer"]["score"] if r.get("offer") else 0.0),
            r["team"],
        )
    )
    return {**base, "outgoingConcentration": concentration, "opponents": results}


def _no_result(reason: str | None, *, constrained: bool = False) -> dict[str, Any]:
    reason = reason or "no_plausible_package"
    return {
        "status": "no_result",
        "noResultReason": reason,
        "noResultLabel": (
            "No qualifying trade found under current constraints"
            if constrained
            else "No qualifying trade found"
        ),
        "noResultDetail": _NO_RESULT_TEXT.get(reason),
    }


def _offer_dict(
    c: BestOfferCandidate,
    our_needs: set[str] | None,
    their_needs: set[str] | None,
    pair: str | None,
    prior: Mapping[str, Any],
) -> dict[str, Any]:
    capacity = c.capacity
    return {
        "send": [_asset_dict(a) for a in c.give],
        "receive": [_asset_dict(a) for a in c.receive],
        "packageSize": finder._package_size_label(c.give, c.receive),
        "canonical": c.equity,
        "external": c.external.to_dict(),
        "externalAll": [v.to_dict() for v in c.external_all],
        "whyThisHelpsUs": _why_us(c, our_needs),
        "whyTheyMayAccept": _why_them(c, their_needs, pair),
        "lineupImpact": c.lineup,
        "rosterCapacity": capacity.to_dict() if hasattr(capacity, "to_dict") else None,
        "confidence": _confidence_label(c),
        "caveats": _caveats(c, prior),
        "rankingFactors": dict(c.factors),
        "score": c.arbitrage_score,
        "flags": list(c.flags),
        "pickPosturePair": pair if c.has_pick else None,
    }


def record_run(
    payload: Mapping[str, Any],
    *,
    league_key: str,
    board_stamp: str | None,
    log_dir: Path | None = None,
) -> str | None:
    """Append one run to the native log; returns the run id, or ``None``.

    Best effort by contract: a recommendation never fails because its record
    could not be written.  Point in time: ``recordedAt`` is stamped after the
    build, and ``boardStamp`` names the board the run read.
    """
    import hashlib  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    try:
        now = datetime.now(timezone.utc)
        body = {
            "version": BEST_OFFERS_VERSION,
            "recordedAt": now.isoformat(),
            "leagueKey": league_key,
            "boardStamp": board_stamp,
            "myTeam": payload.get("myTeam"),
            "rankingMethod": payload.get("rankingMethod"),
            "teamContext": payload.get("teamContext"),
            "opponents": [
                {
                    "team": o.get("team"),
                    "status": o.get("status"),
                    "noResultReason": o.get("noResultReason"),
                    "refinement": o.get("refinement"),
                    "qualified": (o.get("diagnostics") or {}).get("qualified"),
                    "offer": (
                        {
                            "send": [a.get("assetId") or a.get("name") for a in o["offer"]["send"]],
                            "receive": [
                                a.get("assetId") or a.get("name") for a in o["offer"]["receive"]
                            ],
                            "score": o["offer"].get("score"),
                            "rankingFactors": o["offer"].get("rankingFactors"),
                            "calculator": (o["offer"].get("external") or {}).get("calculator"),
                        }
                        if o.get("offer")
                        else None
                    ),
                }
                for o in payload.get("opponents") or []
            ],
        }
        line = json.dumps(body, sort_keys=True, default=str)
        run_id = hashlib.sha256(line.encode("utf-8")).hexdigest()[:20]
        body["runId"] = run_id
        target_dir = log_dir or BEST_OFFERS_RUN_LOG_DIR
        target_dir.mkdir(parents=True, exist_ok=True)
        with (target_dir / f"runs-{now:%Y-%m}.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(body, sort_keys=True, default=str) + "\n")
        return run_id
    except Exception:  # noqa: BLE001 — never fail a recommendation on its record
        return None
