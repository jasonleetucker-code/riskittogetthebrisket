"""Per-team projections over the shared trade analysis (N-team engine, spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.7-§2.9).

Pure projections of outputs the canonical owners already produced.  Nothing
here computes a value, applies a package model, classifies a gap or fires a
gate:

* :func:`team_category` — the 5-level category of ONE team's own decision
  (``trade_decision.decide``).  The body moved here from
  ``trade_decision.public_category_from_decision`` (A1); it reads no
  counterparty, so it means the same at every team count.  PRIVATE only.
* :func:`team_fairness` — the team's MARKET fairness: the asset evidence
  gates (``trade_decision.asset_evidence_gaps``) and then the band the equity
  lens already classified (``fairness_bands.classify`` over that team's own
  adjusted package totals).  Gross, not net of any forced-release cost, so it
  is identical in every mode.
* :func:`fairness_overall` — three-valued (Kleene) AND over the teams.
* :func:`all_team_summary` / :func:`conservation` — the all-team summary, a
  projection of the per-team results; never a second verdict, and it never
  adds per-team adjusted quantities into a trade-level number.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable, Mapping, Sequence

from src.trade import trade_decision

CATEGORIES = (
    "STRONGLY_FAVORABLE",
    "FAVORABLE",
    "APPROXIMATELY_EVEN",
    "UNFAVORABLE",
    "STRONGLY_UNFAVORABLE",
    "UNAVAILABLE",
)

CATEGORY_TEXT = {
    "STRONGLY_FAVORABLE": "Strongly favorable",
    "FAVORABLE": "Favorable",
    "APPROXIMATELY_EVEN": "Approximately even",
    "UNFAVORABLE": "Unfavorable",
    "STRONGLY_UNFAVORABLE": "Strongly unfavorable",
    "UNAVAILABLE": "Unavailable — insufficient evidence",
}
ROSTER_LIMIT_TEXT = "Unfavorable — roster can't fit this trade"

FAIR = "FAIR"
NOT_FAIR = "NOT_FAIR"
UNABLE = "UNABLE"
FAIRNESS_STATES = (FAIR, NOT_FAIR, UNABLE)

#: Asset evidence gate -> fairness reason (spec §2.8).  Any code not listed
#: here (and any code added to the gates later) is ``evaluation_unavailable``.
_GAP_REASON = {
    "no_priced_assets": "asset_not_evaluable",
    "off_board_assets": "asset_not_evaluable",
    "unpriced_assets": "asset_not_evaluable",
    "unheld_assets": "ownership_unverifiable",
    "pick_ownership_unknown": "ownership_unverifiable",
    "ownership_unverifiable": "ownership_unverifiable",
}

NON_CONSERVED_NOTE = (
    "Adjusted package gaps and roster utility are per-team quantities and need not sum to zero."
)


# ── Category (one team's own decision) ─────────────────────────────────────


def _is_execution_gate(decision: Mapping[str, Any]) -> bool:
    return decision.get("headline") == "NO" and decision.get("deciding") == "executionGate"


def team_category(decision: Any) -> str:
    """The 5-level category for one :func:`trade_decision.decide` result.

    | headline | condition | category |
    |---|---|---|
    | NOT_ENOUGH_EVIDENCE | — | UNAVAILABLE |
    | YES | A favours, A large, leaning MAKE | STRONGLY_FAVORABLE |
    | YES | otherwise | FAVORABLE |
    | NO_TOO_CLOSE | — | APPROXIMATELY_EVEN |
    | NO | execution gate | UNFAVORABLE (reason ``roster_limit``) |
    | NO | A opposes, A large, leaning PASS | STRONGLY_UNFAVORABLE |
    | NO | otherwise | UNFAVORABLE |

    ``A`` is ``components.objectiveValue``.  Anything malformed or unknown is
    UNAVAILABLE — a confident category is never invented.
    """
    if not isinstance(decision, dict):
        return "UNAVAILABLE"
    headline = decision.get("headline")
    if headline == "NOT_ENOUGH_EVIDENCE":
        return "UNAVAILABLE"
    if headline == "NO_TOO_CLOSE":
        return "APPROXIMATELY_EVEN"
    if headline not in ("YES", "NO"):
        return "UNAVAILABLE"
    if _is_execution_gate(decision):
        return "UNFAVORABLE"
    comps = decision.get("components")
    a = comps.get("objectiveValue") if isinstance(comps, dict) else None
    a = a if isinstance(a, dict) else {}
    large = a.get("magnitude") == "large"
    lean = decision.get("leaning")
    if headline == "YES":
        if a.get("direction") == "favors" and large and lean == "MAKE":
            return "STRONGLY_FAVORABLE"
        return "FAVORABLE"
    if a.get("direction") == "opposes" and large and lean == "PASS":
        return "STRONGLY_UNFAVORABLE"
    return "UNFAVORABLE"


def team_category_reason(decision: Any) -> str | None:
    """``roster_limit`` for the execution gate, else ``None``."""
    return "roster_limit" if isinstance(decision, dict) and _is_execution_gate(decision) else None


def team_category_text(decision: Any) -> str:
    if team_category_reason(decision) == "roster_limit":
        return ROSTER_LIMIT_TEXT
    return CATEGORY_TEXT[team_category(decision)]


# ── Market fairness (one team) ─────────────────────────────────────────────


def _market_view(market: Any) -> SimpleNamespace:
    """The equity lens as ``asset_evidence_gaps`` reads it (``available`` /
    ``detail``), from its serialized ``to_dict`` form."""
    market = market if isinstance(market, Mapping) else {}
    detail = market.get("detail")
    return SimpleNamespace(
        available=market.get("available") is True,
        detail=dict(detail) if isinstance(detail, Mapping) else {},
    )


def _unable(reason: str) -> dict[str, Any]:
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    return {
        "state": UNABLE,
        "level": None,
        "reasonCode": reason,
        "gap": None,
        "largerAdjustedSide": None,
        "relativePct": None,
        "bands": fairness_bands.receipt()["version"],
    }


def team_fairness(simulation: Any, analysis: Any) -> dict[str, Any]:
    """One team's market fairness (spec §2.8).

    The asset evidence gates decide UNABLE first (the same gaps the decision
    sees — there is no second check here); otherwise the band the equity lens
    classified for THIS team's (gives, receives) decides: ``fair`` -> FAIR,
    anything else -> NOT_FAIR.  The band is read, never recomputed.
    """
    from src.valuation_math import fairness_bands  # noqa: PLC0415

    if not isinstance(simulation, dict) or not isinstance(analysis, dict):
        return _unable("evaluation_unavailable")
    lenses = analysis.get("lenses")
    market = lenses.get("market") if isinstance(lenses, Mapping) else None
    view = _market_view(market)
    gaps = trade_decision.asset_evidence_gaps(simulation, view)
    if gaps:
        return _unable(_GAP_REASON.get(str(gaps[0].get("code") or ""), "evaluation_unavailable"))
    if not view.available:
        return _unable("asset_not_evaluable")
    band = view.detail.get("band")
    level = band.get("level") if isinstance(band, Mapping) else None
    if level not in fairness_bands.LEVELS:
        return _unable("evaluation_unavailable")
    send_adj = view.detail.get("sendingAdjusted")
    recv_adj = view.detail.get("receivingAdjusted")
    larger = (
        max(float(send_adj), float(recv_adj))
        if isinstance(send_adj, (int, float)) and isinstance(recv_adj, (int, float))
        else None
    )
    fair = level == "fair"
    return {
        "state": FAIR if fair else NOT_FAIR,
        "level": level,
        "reasonCode": "within_fairness_threshold" if fair else "outside_fairness_threshold",
        "gap": view.detail.get("vaAdjustedGap"),
        "largerAdjustedSide": larger,
        "relativePct": band.get("relativePct"),
        "bands": str(band.get("bands") or fairness_bands.receipt()["version"]),
    }


# ── Trade level ────────────────────────────────────────────────────────────


def fairness_overall(states: Iterable[str]) -> dict[str, str]:
    """Kleene AND (spec §2.9): any NOT_FAIR -> NOT_FAIR (a team's state depends
    only on its own legs, so one definite NOT_FAIR already proves "not every
    team is fair"); else any UNABLE -> UNABLE; else FAIR.  No teams: UNABLE."""
    seen = list(states)
    if any(s == NOT_FAIR for s in seen):
        return {"state": NOT_FAIR, "reasonCode": "not_all_teams_fair"}
    if not seen or any(s != FAIR for s in seen):
        return {"state": UNABLE, "reasonCode": "evidence_insufficient"}
    return {"state": FAIR, "reasonCode": "all_teams_fair"}


def conservation(teams: Sequence[Mapping[str, Any]], leg_count: int) -> dict[str, Any]:
    """RAW conservation over the per-team ``gives`` / ``receives`` (I6, I15).

    Every leg is counted once as sent and once as received.  The raw sums run
    over the assets priced in BOTH the sender's and the receiver's view, each
    from its own view (an asset unpriced in either view is excluded, never
    counted as 0), so they agree exactly when every asset carries one value.
    Adjusted package quantities never appear here (R14a).
    """
    sent: dict[str, Mapping[str, Any]] = {}
    recv: dict[str, Mapping[str, Any]] = {}
    n_sent = n_recv = 0
    for t in teams:
        for g in t.get("gives") or []:
            n_sent += 1
            sent[str(g.get("assetId"))] = g
        for r in t.get("receives") or []:
            n_recv += 1
            recv[str(r.get("assetId"))] = r

    def _priced(x: Mapping[str, Any]) -> bool:
        v = x.get("value")
        return (
            x.get("valueState") == "priced"
            and isinstance(v, (int, float))
            and not isinstance(v, bool)
        )

    raw_sent = raw_recv = 0
    for aid in sorted(set(sent) & set(recv)):
        if _priced(sent[aid]) and _priced(recv[aid]):
            raw_sent += int(sent[aid]["value"])
            raw_recv += int(recv[aid]["value"])
    return {
        "assetsSent": n_sent,
        "assetsReceived": n_recv,
        "pricedRawSent": raw_sent,
        "pricedRawReceived": raw_recv,
        "balanced": n_sent == n_recv == int(leg_count)
        and set(sent) == set(recv)
        and raw_sent == raw_recv,
    }


def all_team_summary(
    teams: Sequence[Mapping[str, Any]],
    *,
    leg_count: int,
) -> dict[str, Any]:
    """The all-team summary: a projection of the per-team results, every array
    in ascending ``rosterId``.  No trade-level recommendation, winner or
    headline exists — a trade may favour more than one team."""
    ordered = sorted(teams, key=lambda t: int(t["rosterId"]))
    per_team = []
    lines = []
    for t in ordered:
        name = str((t.get("team") or {}).get("name") or f"Team {t['rosterId']}")
        decision = (t.get("analysis") or {}).get("decision") or {}
        per_team.append(
            {
                "rosterId": int(t["rosterId"]),
                "teamName": name,
                "headline": decision.get("headline"),
                "category": t.get("category"),
                "fairness": (t.get("fairness") or {}).get("state"),
            }
        )
        lines.append(f"{name}: {t.get('categoryText')}.")
    return {
        "teamCount": len(ordered),
        "legCount": int(leg_count),
        "perTeam": per_team,
        "lines": lines,
        "fairnessOverall": fairness_overall(
            [(t.get("fairness") or {}).get("state") for t in ordered]
        ),
        "conservation": conservation(ordered, leg_count),
        "nonConservedNote": NON_CONSERVED_NOTE,
    }
