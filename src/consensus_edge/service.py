"""Assemble one Consensus Edge board from a live contract.

The single place components are combined, so no frontend and no second
endpoint can reimplement the formula and drift from it — the failure the
repo already lived through with ``computeUnifiedRanks`` on the client.

Explanations are generated here too, from the structured evidence and
nothing else.  A sentence is only emitted when the number backing it is
present, so the prose cannot claim more than the data supports.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.consensus_edge import MODEL_VERSION, opportunity, params as params_mod, score as score_mod
from src.consensus_edge import identity_join, scoring_fit, sharp_flow as sf, validation_scope
from src.consensus_edge import fair_value
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

# Labels where the model declined to make a call, as distinct from
# calling it neutral. ``Neutral`` is a finding — the evidence points
# nowhere — so it is deliberately NOT in here.
#
# Stamped per row as ``withheld`` for the same reason ``qualified`` is:
# the /consensus-edge page kept its own JS copy of this set, matched by
# English string against these Python constants. That is the drift the
# no-frontend-ranker rule exists to prevent, in miniature — rename a
# label here and the page's Withheld tab silently empties, with no test
# failing because the test read the LIB and the copy was in the PAGE.
REFUSAL_LABELS = frozenset(
    {
        score_mod.CONFLICTED,
        score_mod.INSUFFICIENT,
        score_mod.NO_MARKET_PRICE,
        score_mod.WITHHELD,
    }
)

# The sell side was measured and found to carry nothing. Stamped on every
# payload so no consumer has to know this from a doc, and so the UI can
# say it where a user is about to act on it. Kept as data rather than
# prose because the numbers should move if the next re-measure moves —
# and on 2026-08-04 they did, in both directions at once.
SELL_SIDE_VALIDATION: dict[str, Any] = {
    "validated": False,
    "measured": True,
    "outcome": "null",
    "evidence": "docs/measurements/consensus-edge-board-validation-2026-08-04-h14.json",
    "note": (
        "Measured over 18 non-overlapping folds. On the scale-repaired board sell "
        "rows do at least move the right way — median -0.31% cohort-excess at a "
        "14-day horizon (4 of 6 folds negative) and -0.09% at 7 days (10 of 12) — "
        "where before the repair they moved +0.02%, the wrong sign entirely. That "
        "is NOT a validation: no random benchmark was pre-registered for the sell "
        "side, and a third of a percent is inside the noise the buy side's failure "
        "sits in. The buy side no longer distinguishes itself either (top-20 buys "
        "-1.01%, beating a random draw in 0 of 6), so this is not the weak half of "
        "a working board — neither half has a measured edge, which is why the "
        "feature is behind a flag defaulting OFF."
    ),
}


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


def confidence_ceiling(
    available_components: int,
    total_components: int = 3,
    freshness: float = 1.0,
) -> float:
    """Highest confidence attainable on this board, as it stands.

    Confidence is a geometric mean over coverage, reliability and
    freshness. With only ``available_components`` of
    ``total_components`` ever present, coverage is capped, and so is the
    whole score — which silently suppresses every Strong label.
    Publishing the ceiling means "why are there no Strong Buys" is
    answerable without reading source.

    ``freshness`` is a KNOWN factor, not an assumed one, and that
    distinction was a bug. Reliability varies per player, so assuming
    its best case keeps this an upper bound. Freshness does not: it is
    one number for the whole board, and when staleness is unknown it is
    pinned at 0.5. Assuming 1.0 there published a ceiling of 79.37 and
    promised Strong labels on a board where every row was capped at
    62.996 and none could earn one. Caller passes what it actually used.
    """
    if total_components <= 0:
        return 0.0
    coverage = max(0, available_components) / total_components
    return 100.0 * ((coverage * max(0.0, min(1.0, freshness))) ** (1.0 / 3.0))


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
    movements_unavailable_reason: str | None = None,
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
    flow = sf.sharp_flow_index(
        movements_by_asset, p, unavailable_reason=movements_unavailable_reason
    )

    # How many components could contribute at all, given the weights.
    # Guarded at 1 so a params file that zeroed everything divides by
    # something rather than reporting perfect coverage of nothing.
    _weights = (p.get("composite") or {}).get("weights") or {}
    weighted_components = max(
        1,
        sum(
            1
            for name in ("mispricing", "sharpFlow", "opportunity")
            if float(_weights.get(name) or 0.0) > 0.0
        ),
    )

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
            # Only components that CAN contribute count toward coverage.
            # This was inconsistent: zero-weight components were excluded
            # from the numerator (they cannot raise coverage) but left in
            # the denominator, so every row was penalised for a component
            # we measured and deliberately removed — a deficit no amount
            # of data could ever close, which is not information about
            # the player. With opportunity zeroed the ceiling was 69.34,
            # under the Strong threshold of 70, which suppressed the
            # best-performing group on the board: rows demoted out of
            # Strong Buy returned +2.53% cohort-excess at 6 of 6 folds,
            # the strongest bucket measured. Excluding it from both sides
            # lifts the ceiling to 79.37 and lets those rows say what
            # they are.
            components_possible=weighted_components,
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
            # ``classify`` has had this branch since day one and nothing
            # ever passed it True, because ``fair_value`` dropped the
            # flag the contract had already computed. A quarantined row
            # is one whose identity join is suspect, which means its
            # market price and its fair value may describe two different
            # players — so it is Withheld, not scored with a caveat.
            quarantined=bool(entry.get("quarantined")),
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
            # Every cause, not just the headline one — a row can lose two
            # dependencies at once and `asset_class_coverage` counts this.
            "unpricedReasons": entry.get("unpricedReasons") or [],
            # How many sources priced this row. Already feeds confidence;
            # stamped so a reader (and the snapshot store) can see the
            # evidence depth behind a call rather than only its effect.
            "sourceCount": entry.get("sourceCount"),
            # Why a Withheld row is withheld, and how sure the pipeline
            # is about who this player even is.
            "quarantined": bool(entry.get("quarantined")),
            "identityConfidence": entry.get("identityConfidence"),
            # Whether this row is eligible for a ranked list. Stamped by
            # the backend so no client re-derives it: the frontend used
            # to keep its own copy of this label set, matched by English
            # string against Python constants, which is the same drift
            # the client-side rank fallback caused.
            "qualified": label["label"] in DIRECTIONAL_LABELS,
            # The refusal states, likewise stamped rather than
            # re-derived. Note ``qualified`` and ``withheld`` are not
            # complements: a Neutral row is neither.
            "withheld": label["label"] in REFUSAL_LABELS,
        }
        row["explanation"] = _explain(row)
        # The ranking key, stamped so nothing downstream re-derives it.
        # ``top_movers`` ranked on this while ``players`` — the list the
        # page actually fetches — was ordered by raw score, so the study
        # that justified shipping measured an ordering no user ever saw.
        # See ADR-022.
        row["conviction"] = conviction(row)
        players.append(row)

    # Conviction descending: biggest buys first, biggest sells last,
    # unscored rows after both. Same key ``top_movers`` uses and the same
    # key ``validate_consensus_edge_board.py`` measures — pinned by
    # ``test_served_order_is_the_measured_order``.
    players.sort(key=lambda r: (r["score"] is None, -(r["conviction"] or 0.0)))

    availability = component_availability(players, (p.get("composite") or {}).get("weights"))
    live_components = sum(1 for meta in availability.values() if meta["available"])
    # Same denominator as the per-row confidence, or the published
    # ceiling would not describe the confidences actually on the board.
    # Freshness is a board-wide known, so the ceiling reflects it rather
    # than assuming its best case. Mirrors score.confidence's own branch:
    # unknown staleness is treated as stale (0.5), not as fresh.
    _half_life = float((p.get("confidence") or {}).get("stalenessHalfLifeHours") or 48.0)
    board_freshness = (
        0.5
        if hours_stale is None
        else math.exp(-math.log(2.0) * max(0.0, float(hours_stale)) / _half_life)
    )
    ceiling = confidence_ceiling(live_components, weighted_components, board_freshness)
    scope = validation_scope.scope_for_board(fit_board.to_meta())
    class_coverage = asset_class_coverage(players)
    caveats = _caveats(scope, class_coverage)
    strong_threshold = float((p.get("classification") or {}).get("minConfidenceForStrong") or 70.0)

    return {
        "status": STATUS_OK,
        "modelVersion": MODEL_VERSION,
        "paramSetId": p.get("paramSetId"),
        # When this board was BUILT — which is not when its data was
        # gathered, and the package docstring's claim that payloads carry
        # "the timestamps of the data it was computed from" was only true
        # of ``inputs.hoursStale``. A user reading a freshly-generated
        # timestamp beside day-old prices is being told the wrong thing.
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        # When the DATA was gathered. Copied off the contract rather than
        # recomputed, so it is the same instant the rest of the site
        # shows.
        "contractScrapedAt": (contract or {}).get("scrapeTimestamp"),
        "players": players,
        "coverage": fv_coverage(index),
        "sharpFlowStatus": flow.get("status"),
        "componentValidation": score_mod.COMPONENT_VALIDATION,
        # Buys and sells are not equally grounded and must not render as
        # though they were.
        "sellSideValidation": SELL_SIDE_VALIDATION,
        # League scoring fit is applied INSIDE fair value, never as a
        # separate component. Reported here so a reader can see which
        # axes were measured and at what level, without being able to
        # mistake it for a fourth additive term.
        "scoringFit": fit_board.to_meta(),
        "componentAvailability": availability,
        # Which asset classes this board can actually score, and why the
        # rest cannot. Not a diagnostic: IDP carries no score at all
        # today (the anchor-free board has no IDP scale — see
        # ``fair_value``), and an offense-only list of buys looks
        # identical whether that is deliberate or a join that silently
        # dropped every defender. That exact ambiguity ran in
        # ``trade/finder.py`` for months.
        "assetClassCoverage": class_coverage,
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


def asset_class_coverage(players: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per asset class: rows present, rows scored, and why the rest are not.

    ``{assetClass: {"rows": n, "scored": n, "unscored": n,
    "unpricedReasons": {reason: n}}}``

    ``rows == scored + unscored`` is exact. ``unpricedReasons`` is a
    separate tally that can sum ABOVE ``unscored``, because a row can
    lose two dependencies and is counted under both.

    An asset class that is present but wholly unscored is a real state
    and has to be a legible one. Today ``idp`` is exactly that: the
    leave-one-out board loses the IDP backbone when its only cross-market
    IDP source is excluded, so every defender comes back unpriced rather
    than priced in units the rest of the board does not share. A consumer
    reading only ``players`` sees an offense-only list and cannot tell
    that from a broken identity join.

    Counts every reason a row carries, so the per-class reason counts can
    sum above that class's unscored row count. Counting only the singular
    ``unpricedReason`` meant a row that lost both the IDP backbone and
    the rookie ladder was recorded under the backbone alone, and the
    caveat prose then named one dependency when two had failed.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in players:
        cls = str(row.get("assetClass") or "unknown")
        bucket = out.setdefault(cls, {"rows": 0, "scored": 0, "unscored": 0, "unpricedReasons": {}})
        bucket["rows"] += 1
        if row.get("score") is not None:
            bucket["scored"] += 1
            continue
        bucket["unscored"] += 1
        reasons = [str(r) for r in (row.get("unpricedReasons") or []) if r]
        if not reasons:
            reasons = [str(row.get("unpricedReason") or "unscored")]
        for reason in reasons:
            bucket["unpricedReasons"][reason] = bucket["unpricedReasons"].get(reason, 0) + 1
    return dict(sorted(out.items()))


# Machine reason codes rendered for a human. Kept beside the caveat
# builder rather than in the UI because the caveats are prose the backend
# authors — a client that had to translate these would be re-deriving a
# claim about the model, which is the drift this package keeps closing.
_UNPRICED_IN_ENGLISH: dict[str, str] = {
    fair_value.UNPRICED_NO_ANCHOR: (
        "no retail source publishes a market price for this asset class, so there is "
        "nothing to call the market wrong about"
    ),
    fair_value.UNPRICED_SCALE_IDP_BACKBONE: (
        "the only cross-market IDP source is the one being judged, so removing it "
        "leaves no scale to price defenders on"
    ),
    fair_value.UNPRICED_SCALE_ROOKIE_LADDER: (
        "the rookie ranks on this board are calibrated by the source being judged, so "
        "removing it leaves them uncalibrated"
    ),
    fair_value.UNPRICED_NOT_ON_BOARD: "the anchor-free board did not price these rows",
    fair_value.UNPRICED_NO_MARKET_VALUE: "the market anchor publishes no value for these rows",
}


def _caveats(
    scope: dict[str, Any],
    class_coverage: dict[str, dict[str, Any]] | None = None,
) -> list[str]:
    """What this board does not claim. Configuration- and coverage-aware.

    The first four are permanent properties of the model. The last two
    appear only when their condition holds — a wholly unscored asset
    class, or a board that has drifted off the measured configuration —
    because a caveat that is always present is one nobody reads, and
    these two need to be read.
    """
    # Derived from COMPONENT_VALIDATION rather than written out, so a
    # component that gains or loses a result changes this sentence
    # without anyone remembering to. The first form of this caveat was
    # prose naming mispricing as the validated one; it stayed accurate
    # for about a day.
    _validated = sorted(n for n, m in score_mod.COMPONENT_VALIDATION.items() if m.get("validated"))
    _nulls = sorted(
        n
        for n, m in score_mod.COMPONENT_VALIDATION.items()
        if m.get("measured") and m.get("outcome") == "null"
    )
    if _validated:
        _headline = f"Validated components: {', '.join(_validated)}."
    else:
        _headline = (
            "NO component on this board has a positive out-of-sample result. "
            "The board still ranks and labels players; nothing measured says "
            "it does so usefully."
        )
    if _nulls:
        _headline += f" Measured and returned a null: {', '.join(_nulls)}."
    out = [
        _headline,
        "Sharp Flow's weight is a declared prior, not fitted. Opportunity "
        "carries zero weight: it is shown as evidence and does not move any "
        "score.",
        "Validated against market movement, not fantasy production.",
        # The panel every measurement rests on runs 2026-04-16 → 2026-08-03,
        # entirely between the draft and the season. Offseason repricing is
        # driven by rookie hype and ADP drift; in-season repricing by
        # injuries and usage. The measurements may not transfer, and the
        # re-run is scheduled rather than hoped for.
        "Measured over an offseason panel only — no in-season board history "
        "exists in this repository. Re-measure once in-season dates accrue.",
        # Measured, not asserted: docs/measurements/consensus-edge-board-
        # validation-2026-08-04-h14.json. The top-20 buy list returned
        # -1.01% median cohort-excess and beat a random-20 draw from the
        # same priced universe in 0 of 6 folds (0 of 12 at 7 days).
        "The top-20 buy list did not beat a random draw from the same priced "
        "universe in any measured fold. This is why the feature flag defaults "
        "OFF; you are looking at it because someone turned it on to evaluate it.",
    ]
    # Derived from the board, never asserted: a caveat that outlives the
    # condition it describes is worse than no caveat, and the IDP line
    # lifts by itself the day a second IDP cross-market source is
    # registered. ``pick`` is included even though its condition is
    # permanent — a dynasty user scanning a buy list with no picks in it
    # is owed the reason, and "no retail pick market exists" is a claim
    # about the world rather than a note about our plumbing.
    for cls, meta in sorted((class_coverage or {}).items()):
        if cls == "unknown" or meta.get("scored") or not meta.get("rows"):
            continue
        dominant = max(
            (meta.get("unpricedReasons") or {}).items(), key=lambda kv: kv[1], default=("", 0)
        )[0]
        out.append(
            f"No {cls.upper()} row on this board carries a score "
            f"({meta['rows']} present): {_UNPRICED_IN_ENGLISH.get(dominant, dominant)}. "
            f"This is a stated refusal, not a missing join."
        )
    for difference in scope.get("differences") or []:
        out.append(f"This board is NOT running the configuration that was measured — {difference}.")
    return out


def conviction(row: dict[str, Any]) -> float:
    """Score shrunk by its own confidence — the ranking key.

    A score is a point estimate and confidence is its precision, and
    ranking on the estimate alone throws the precision away. That is not
    an abstraction: the board computes both, and the top-20 was sorted
    on score only, which systematically surfaced the thinnest-evidence
    rows. Measured over 7 fold origins, the published top-20 buys had a
    median reliability of **0.75** against **1.00** for the board as a
    whole — the highest scores were coming from the least-sourced
    players, because fewer sources means a wider spread against the
    anchor and therefore a bigger z.

    Shrinking by confidence more than doubled the measured edge on the
    board as it then stood — 14d +1.57% to +3.59%, 7d +0.92% to +1.51%,
    replicating at both horizons.

    **That comparison no longer stands and is not why this is still
    here.** It was measured on a board whose IDP fair values came from a
    leave-one-out build with no IDP backbone, i.e. on no scale at all
    (ADR-021). With those rows refused the top-20 is negative under
    *either* ordering, so "which ranking is better" has no useful answer
    on this panel and re-running it would produce a comparison of two
    failures.

    What keeps conviction as the ranking key is the argument that
    motivated it rather than the number that followed: a score is a point
    estimate, confidence is its precision, and ranking on the estimate
    alone throws the precision away. It introduces no new constant — as
    against a confidence *threshold* (``conf >= 65``, which scored
    similarly), which is a tuned one — and it degrades smoothly instead
    of falling off a cliff at an arbitrary line. It is also what every
    committed measurement ranks on, so changing it would re-open the
    served-vs-measured gap ADR-022 closed.
    """
    score = float(row.get("score") or 0.0)
    conf = row.get("confidence")
    if not isinstance(conf, (int, float)):
        return 0.0
    return score * (float(conf) / 100.0)


def top_movers(board: dict[str, Any], limit: int = 20) -> dict[str, list[dict[str, Any]]]:
    """Qualified top buys and sells, ranked by conviction.

    Merit-ranked with no positional quota: a weak player promoted to
    represent his position would be labelled a buy because of a display
    rule, which is exactly the thing the brief forbids. Positions with
    nothing qualifying are simply absent, and the caller renders that as
    "no qualifying buy" rather than reaching further down the list.

    **The sell list has no measured edge** and the caller must not
    present it as the buy list's equal — see ``SELL_SIDE_VALIDATION``.
    It is still returned, because suppressing the model's output is a
    bigger claim than labelling it, and a user who wants it should be
    told what it is worth rather than shown nothing.
    """
    qualified = [
        r for r in board.get("players") or [] if r.get("score") is not None and r.get("qualified")
    ]
    buys = sorted((r for r in qualified if r["score"] > 0), key=conviction, reverse=True)[:limit]
    sells = sorted((r for r in qualified if r["score"] < 0), key=conviction)[:limit]
    return {"buys": buys, "sells": sells}
