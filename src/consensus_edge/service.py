"""Assemble one Consensus Edge board from a live contract.

The single place components are combined, so no frontend and no second
endpoint can reimplement the formula and drift from it — the failure the
repo already lived through with ``computeUnifiedRanks`` on the client.

Explanations are generated here too, from the structured evidence and
nothing else.  A sentence is only emitted when the number backing it is
present, so the prose cannot claim more than the data supports.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.consensus_edge import MODEL_VERSION, opportunity, params as params_mod, score as score_mod
from src.consensus_edge import identity_join, scoring_fit, sharp_flow as sf, validation_scope
from src.consensus_edge.fair_value import (
    MARKET_ANCHOR_BY_ASSET_CLASS,
    coverage as fv_coverage,
    fair_value_index,
)
from src.consensus_edge.mispricing import score_index

STATUS_OK = "ok"
STATUS_NO_CONTRACT = "no_contract"

# Labels that make a row eligible for a ranked list. Defined once, here,
# and stamped onto every row as ``qualified`` so no consumer re-derives
# it.
DIRECTIONAL_LABELS = frozenset(
    {score_mod.STRONG_BUY, score_mod.BUY, score_mod.SELL, score_mod.STRONG_SELL}
)


def resolve_hours_stale(contract: dict[str, Any] | None) -> float | None:
    """Age of the data the mispricing signal actually depends on.

    The contract already carries a full freshness block —
    ``dataFreshness.sourceTimestamps`` with per-source ``ageHours`` — and
    Consensus Edge ignored all of it, so ``score.confidence`` took its
    "unknown staleness" branch and pinned freshness at 0.5 for every
    player forever. Stale data was therefore not visibly degraded
    anywhere, which is the opposite of what this feature promises.

    **The MARKET ANCHORS are what matter**, not the mean source age. The
    mispricing score is a comparison against the anchor's published
    price; if that price is a day old the signal is a day old, however
    fresh eleven expert boards happen to be. So this takes the OLDEST
    anchor — the weakest link — and falls back to the board-wide maximum
    only when no anchor timestamp is available.

    Returns None when the contract carries no usable freshness data at
    all, which correctly routes back to the "unknown" branch rather than
    inventing a zero.
    """
    if not isinstance(contract, dict):
        return None
    freshness = contract.get("dataFreshness")
    if not isinstance(freshness, dict):
        return None
    timestamps = freshness.get("sourceTimestamps")
    if not isinstance(timestamps, dict) or not timestamps:
        return None

    def _age(entry: Any) -> float | None:
        if not isinstance(entry, dict):
            return None
        value = entry.get("ageHours")
        try:
            age = float(value)
        except (TypeError, ValueError):
            return None
        return age if age >= 0 else None

    anchor_ages = [
        age
        for key in set(MARKET_ANCHOR_BY_ASSET_CLASS.values())
        if (age := _age(timestamps.get(key))) is not None
    ]
    if anchor_ages:
        return max(anchor_ages)

    all_ages = [age for entry in timestamps.values() if (age := _age(entry)) is not None]
    return max(all_ages) if all_ages else None


def component_availability(
    players: list[dict[str, Any]],
    weights: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Which components actually contribute, and on how many rows.

    A component that is dark because its data source is empty looks
    exactly like a component that is dark because nobody wired it up.
    Both were true here at different times, and neither was visible.
    This makes the distinction a reported fact.

    **A zero-weight component is not available**, however many rows it
    values. Opportunity is exactly that case since 2026-08-04: measured
    against forward market movement, it made the ranking slightly worse,
    so its weight is zero. Counting it as live would raise the confidence
    ceiling — and with it make Strong labels reachable — on the strength
    of a component contributing nothing to any score. `rowsWithValue`
    still reports what it measured, because the evidence is real and is
    shown to users; only its status as *usable* evidence changes.
    """
    names = ("mispricing", "sharpFlow", "opportunity")
    weights = weights or {}
    scored = [r for r in players if r.get("score") is not None]
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        present = sum(
            1 for r in players if isinstance((r.get("components") or {}).get(name), (int, float))
        )
        weight = float(weights.get(name) or 0.0)
        entry: dict[str, Any] = {
            "available": present > 0 and weight > 0,
            "rowsWithValue": present,
            "rowsScored": len(scored),
            "weight": weight,
        }
        if present > 0 and weight <= 0:
            entry["unavailableReason"] = "zero_weight"
        elif present == 0:
            entry["unavailableReason"] = "no_data"
        out[name] = entry
    return out


def confidence_ceiling(available_components: int, total_components: int = 3) -> float:
    """Highest confidence attainable given how many components are live.

    Confidence is a geometric mean over coverage, reliability and
    freshness. With only ``available_components`` of ``total_components``
    ever present, coverage is capped, and so is the whole score — which
    silently suppresses every Strong label. Publishing the ceiling means
    "why are there no Strong Buys" is answerable without reading source.

    Assumes the best case for the other two factors (both 1.0), so this
    is a genuine upper bound rather than an estimate.
    """
    if total_components <= 0:
        return 0.0
    coverage = max(0, available_components) / total_components
    return 100.0 * (coverage ** (1.0 / 3.0))


def _explain(row: dict[str, Any]) -> list[str]:
    """Plain-language reasons, each backed by a field on the row.

    Deliberately a list of independent sentences rather than one
    paragraph: the UI shows the first two and the card shows all of
    them, and a paragraph would have to be re-split to do that.
    """
    parts: list[str] = []
    mis = row.get("mispricing") or {}
    if mis.get("score") is not None and mis.get("pctGap") is not None:
        direction = "above" if mis["pctGap"] > 0 else "below"
        parts.append(
            f"Our anchor-free fair value is {abs(mis['pctGap']):.0%} {direction} the market "
            f"({mis['fairValue']:.0f} vs {mis['marketValue']:.0f})."
        )
        if mis.get("cohortLevel") == "family":
            parts.append(
                "Measured against a pooled position cohort rather than an exact "
                "value tier, because too few peers priced at this level."
            )

    flow = row.get("sharpFlow") or {}
    if flow.get("direction") is not None:
        verb = "acquiring" if flow["direction"] > 0 else "moving off"
        parts.append(
            f"Qualified managers have been net {verb} this player across "
            f"{flow.get('uniqueManagers', 0)} managers and "
            f"{flow.get('uniqueLeagues', 0)} leagues."
        )
    elif flow.get("reason"):
        parts.append("No qualified-manager activity supports or contradicts this.")

    opp = row.get("opportunity") or {}
    zero_weighted = "opportunity" in (row.get("componentsZeroWeight") or [])
    if opp.get("score") is None and opp.get("absentAxes"):
        parts.append("Role and usage evidence was not available, so this rests on price alone.")
    elif zero_weighted:
        # Shown, but explicitly not counted. A reader who sees a role
        # signal on the card and a score that ignores it deserves to be
        # told which of the two is the model's answer.
        parts.append(
            "Role and momentum evidence is shown below but does not move this "
            "score: measured against forward market movement it did not improve "
            "on price alone, so it carries no weight."
        )
    else:
        # Each axis carries its own sentence, because the two point in
        # opposite directions by design and a single combined number
        # would read as one finding when it is two.
        for axis in opp.get("axes") or []:
            if axis.get("score") is None or not axis.get("detail"):
                continue
            if axis.get("axis") == "snapTrend":
                verb = "growing" if axis["score"] > 0 else "shrinking"
                parts.append(f"His snap-share role is {verb} — {axis['detail']}.")
            elif axis.get("axis") == "boardMomentumRisk" and axis["score"] < 0:
                parts.append(
                    f"Tempered because the market is already closing this gap — {axis['detail']}."
                )

    conflict = row.get("conflict") or {}
    if conflict.get("conflicted"):
        parts.append("Components disagree, so no directional call is made until that resolves.")
    return parts


def rank_history_key(player_key: str, asset_class: Any) -> str:
    """The key ``rank_history.load_history`` files this player under.

    The log is keyed ``{canonicalName}::{assetClass}`` — deliberately,
    because Sleeper allows one display name to mean two different humans
    on the offense and IDP boards. Looking a player up by bare name
    therefore misses **every** entry, which is exactly what this module
    did: the opportunity axis read a dict that could never contain its
    keys and reported "no history" for every player in every
    environment, production included.

    Mirrors ``rank_history._player_key`` for rows that carry
    ``assetClass`` — which every fair-value entry does, since it comes
    straight off the ``playersArray`` row that function prefers.
    ``tests/consensus_edge/test_wiring.py`` pins the two formats
    together rather than importing a private helper across packages.
    """
    asset = str(asset_class or "").strip().lower()
    return f"{player_key}::{asset or 'unknown'}"


def build_board(
    contract: dict[str, Any] | None,
    *,
    movements_by_asset: dict[str, Any] | None = None,
    rank_history_by_player: dict[str, list[dict[str, Any]]] | None = None,
    player_context_by_player: dict[str, dict[str, Any]] | None = None,
    params: dict[str, Any] | None = None,
    hours_stale: float | None = None,
    csv_root: "Path | None" = None,
    scoring_fit_board: Any = None,
) -> dict[str, Any]:
    """Score every player on the contract.

    ``movements_by_asset`` of ``None`` means no ledger — Sharp Flow is
    then reported unavailable and omitted from the composite rather than
    contributing a neutral zero.

    ``player_context_by_player`` is the playerctx snapshot joined to
    board keys (see :mod:`consensus_edge.identity_join`). Absent, the
    opportunity component falls back to the board-momentum risk axis
    alone, which can only ever subtract — so a missing snapshot cannot
    manufacture a buy.

    ``csv_root`` **must** be supplied when replaying a historical date.
    The pipeline enriches ``canonicalSiteValues`` from ``CSVs/site_raw``
    on disk, so omitting it silently mixes today's source values into a
    past board — the look-ahead leak that contaminated 682 of 692 rows
    the one time it happened (ADR-006), and which still produces a board
    that looks entirely valid. Its absence here is why both existing
    backtests bypass this function and rebuild the composite by hand;
    with it they no longer have to, and a study can score the board the
    site actually serves rather than a reimplementation of it.

    ``scoring_fit_board`` lets a caller supply an INERT fit rather than
    letting this measure one. Two reasons a replay needs that, and both
    are correctness rather than speed: ``scoring_fit.measure`` reaches
    nflverse over the network on a cache miss, and an *active* scoring
    fit is exactly the configuration divergence
    :mod:`consensus_edge.validation_scope` exists to flag — the
    published rho describes a board measured with the fit inert, so a
    replay that applies it is measuring something else.
    """
    if not contract:
        return {
            "status": STATUS_NO_CONTRACT,
            "message": "No contract loaded; Consensus Edge has nothing to score.",
            "players": [],
        }

    p = params or params_mod.load()
    # The contract IS the payload. ``build_api_data_contract`` copies the
    # raw top level through and only adds keys, so it is idempotent on
    # its own output and ``fair_value_index`` reads the same ``players``
    # dict either way — verified byte-identical over 973 rows. This used
    # to read a ``_rawPayload`` key that nothing in the repo ever wrote,
    # which documented an indirection that did not exist.
    # The reception-depth axis measures per-player multipliers keyed by
    # GSIS id and REFUSES to apply them without a join to board keys —
    # so supplying the join is what turns a measured-but-dark axis into
    # a live one. Resolved here, once, and handed to the scoring module
    # rather than resolved inside it: identity is the identity package's
    # job, and a second join grown inside a scoring module is how a repo
    # ends up with two answers to "which player is this".
    if scoring_fit_board is not None:
        fit_board = scoring_fit_board
    else:
        scoring_fit.set_gsis_join(identity_join.build_gsis_to_player_key(contract))
        fit_board = scoring_fit.measure(season=contract.get("currentDraftYear"))
    index = fair_value_index(contract, scoring_fit_board=fit_board, csv_root=csv_root)
    mispricing = score_index(index)
    flow = sf.sharp_flow_index(movements_by_asset, p)

    players: list[dict[str, Any]] = []
    for key, entry in index.items():
        mis = mispricing.get(key) or {}
        flow_entry = (flow.get("assets") or {}).get(key) or {}
        history = (rank_history_by_player or {}).get(rank_history_key(key, entry.get("assetClass")))
        opp = opportunity.assess(
            rank_history=history,
            player_context=(player_context_by_player or {}).get(key),
        )

        components: dict[str, float | None] = {
            "mispricing": mis.get("score"),
            "sharpFlow": flow_entry.get("direction"),
            "opportunity": opp.get("score"),
        }
        comp = score_mod.composite(components, p)
        conflict = score_mod.detect_conflict(components, p)
        conf = score_mod.confidence(
            params=p,
            components_present=len(comp["componentsPresent"]),
            components_possible=len(components),
            cohort_level=mis.get("cohortLevel"),
            source_count=int(entry.get("sourceCount") or 0),
            hours_stale=hours_stale,
        )
        label = score_mod.classify(
            comp["score"],
            conf["score"],
            conflict,
            p,
            has_market_price=entry.get("marketValue") is not None,
        )

        row = {
            "playerKey": key,
            "displayName": entry.get("displayName"),
            "position": entry.get("position"),
            "assetClass": entry.get("assetClass"),
            "score": comp["score"],
            "label": label["label"],
            "labelReason": label.get("reason"),
            "confidence": conf["score"],
            "confidenceFactors": conf["factors"],
            "components": components,
            "componentsAbsent": comp["componentsAbsent"],
            # Components that produced a value the model deliberately
            # does not act on. Distinct from absent: the evidence exists
            # and is shown, it just carries no weight. Collapsing the two
            # would make a measured-and-rejected signal indistinguishable
            # from a missing one.
            "componentsZeroWeight": comp.get("componentsZeroWeight") or [],
            "effectiveWeights": comp["effectiveWeights"],
            "mispricing": mis,
            "sharpFlow": flow_entry or {"reason": flow.get("status")},
            "opportunity": opp,
            "conflict": conflict,
            "fairValue": entry.get("fairValue"),
            "marketValue": entry.get("marketValue"),
            "anchorKey": entry.get("anchorKey"),
            "excludedSources": entry.get("excludedSources"),
            "unpricedReason": entry.get("unpricedReason"),
            # Whether this row is eligible for a ranked list. Stamped by
            # the backend so no client re-derives it: the frontend used
            # to keep its own copy of this label set, matched by English
            # string against Python constants, which is the same drift
            # the client-side rank fallback caused.
            "qualified": label["label"] in DIRECTIONAL_LABELS,
        }
        row["explanation"] = _explain(row)
        players.append(row)

    players.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0)))

    availability = component_availability(players, (p.get("composite") or {}).get("weights"))
    live_components = sum(1 for meta in availability.values() if meta["available"])
    ceiling = confidence_ceiling(live_components, len(availability))
    scope = validation_scope.scope_for_board(fit_board.to_meta())
    caveats = _caveats(scope)
    strong_threshold = float((p.get("classification") or {}).get("minConfidenceForStrong") or 70.0)

    return {
        "status": STATUS_OK,
        "modelVersion": MODEL_VERSION,
        "paramSetId": p.get("paramSetId"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "players": players,
        "coverage": fv_coverage(index),
        "sharpFlowStatus": flow.get("status"),
        "componentValidation": score_mod.COMPONENT_VALIDATION,
        # League scoring fit is applied INSIDE fair value, never as a
        # separate component. Reported here so a reader can see which
        # axes were measured and at what level, without being able to
        # mistake it for a fourth additive term.
        "scoringFit": fit_board.to_meta(),
        "componentAvailability": availability,
        # Published because it silently governs which labels can appear
        # at all: with one live component the ceiling sits below the
        # Strong threshold, so Strong Buy and Strong Sell are
        # unreachable. That is a legitimate state, but it must never
        # again be mistaken for the model simply not finding any.
        "confidenceCeiling": ceiling,
        # Published alongside the boolean because the UI explains the
        # boolean by naming the number. It used to hardcode 70 in JSX —
        # the same backend/frontend drift that produced the client-side
        # rank fallback, in miniature: change the threshold here and the
        # sentence on the page would keep quoting the old one.
        "strongLabelThreshold": strong_threshold,
        "strongLabelsReachable": ceiling >= strong_threshold,
        # What this board was actually handed. An input that never
        # arrived is the defect class this whole feature suffered from,
        # so the inputs are part of the payload, not an implementation
        # detail.
        "inputs": {
            "hoursStale": hours_stale,
            "sharpMovementAssets": len(movements_by_asset or {})
            if movements_by_asset is not None
            else None,
            "rankHistoryPlayers": len(rank_history_by_player or {})
            if rank_history_by_player is not None
            else None,
            "playerContextPlayers": len(player_context_by_player or {})
            if player_context_by_player is not None
            else None,
        },
        "experimental": True,
        # Whether this board is running the configuration the committed
        # measurements were produced under. The backtest measures fair
        # value with league scoring fit INERT; this path applies it. The
        # two agree today and would silently stop agreeing the moment a
        # real Sleeper directory reaches production.
        "validationScope": scope,
        "caveats": caveats,
    }


def _caveats(scope: dict[str, Any]) -> list[str]:
    """What this board does not claim. Configuration-aware.

    The first two are permanent properties of the model. The third
    appears only when the board has drifted off the measured
    configuration, because a caveat that is always present is one nobody
    reads — and this particular one needs to be read.
    """
    out = [
        "Sharp Flow's weight is a declared prior, not fitted. Opportunity was "
        "measured and carries zero weight: it is shown as evidence and does "
        "not move any score.",
        "Validated against market movement, not fantasy production.",
        # The panel every measurement rests on runs 2026-04-16 → 2026-08-03,
        # entirely between the draft and the season. Offseason repricing is
        # driven by rookie hype and ADP drift; in-season repricing by
        # injuries and usage. The measurements may not transfer, and the
        # re-run is scheduled rather than hoped for.
        "Measured over an offseason panel only — no in-season board history "
        "exists in this repository. Re-measure once in-season dates accrue.",
        # Measured, not asserted: docs/measurements/consensus-edge-board-
        # validation-2026-08-04-h14.json. Sell rows returned -0.04% median
        # cohort-excess with 0 of 7 folds positive (0 of 15 at a 7-day
        # horizon). The buy side carries the whole edge.
        "The sell side has no measured edge: sell-labelled rows were positive "
        "in 0 of 7 folds. Treat sells as unvalidated.",
    ]
    for difference in scope.get("differences") or []:
        out.append(f"This board is NOT running the configuration that was measured — {difference}.")
    return out


def top_movers(board: dict[str, Any], limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Qualified top buys and sells.

    Merit-ranked with no positional quota: a weak player promoted to
    represent his position would be labelled a buy because of a display
    rule, which is exactly the thing the brief forbids. Positions with
    nothing qualifying are simply absent, and the caller renders that as
    "no qualifying buy" rather than reaching further down the list.
    """
    qualified = [
        r for r in board.get("players") or [] if r.get("score") is not None and r.get("qualified")
    ]
    buys = [r for r in qualified if r["score"] > 0][:limit]
    sells = sorted((r for r in qualified if r["score"] < 0), key=lambda r: r["score"])[:limit]
    return {"buys": buys, "sells": sells}
