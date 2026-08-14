"""LI-9: publish this league's adjusted board as a client-side overlay.

This is the only place a real ``leagueAdjustedDynastyValue`` is produced.

WHY AN OVERLAY AND NOT CONTRACT FIELDS
──────────────────────────────────────
CLAUDE.md's core split: *scoring profile controls rankings, league key
controls context.*  The consensus board is scoring-profile-scoped — two
leagues with identical scoring share one computed board and one cached
payload.  The adjustment here is driven by ``lineupScarcity``, measured
by :func:`src.league_intel.replacement.compute_scarcity` from **this
league's twelve rosters**.  Two leagues with identical scoring but
different rosters get different adjusted values.

So an adjusted value cannot live on the shared contract without
collapsing that split — one league's roster shape would silently reprice
another's board.  It is served per league and overlaid client-side.

WHY FACTORS, NOT ABSOLUTE VALUES
────────────────────────────────
``adjustment.build_adjustment`` computes ``adjusted = consensus ×
combined`` where ``combined`` is a product of axis factors.  The factor
depends only on **position** — it never reads the consensus value.  So a
factor composes exactly against *any* consensus board, including one
built with custom source weights.  An absolute value does not: it would
carry the default board's numbers into a board the user has re-weighted,
silently overwriting it.

WHY RANKS ARE DENSE AND FACTORS ARE NOT
───────────────────────────────────────
A player whose own factor is 1.0 still moves rank when the players
around him move.  Measured: a 4% relative shift displaces rank 500 by
~63 slots.  So nearly every rank changes and a "changed ranks only" diff
is the dense map minus a rounding error — while reintroducing the
three-state ambiguity (changed / unchanged / now-unranked) that
``activePlayerIds`` exists to paper over.  Dense ranks are ~7 KB gzip
against a ~100 KB gzip override delta.  Not worth the ambiguity.

WHAT MOVES A VALUE, AND WHAT DELIBERATELY DOES NOT
──────────────────────────────────────────────────
* **structuralScarcity** — live.  Positions whose starter demand exceeds
  the reference lift; deeper positions trim.  Measured from the exact
  lineup optimizer over real rosters, so it is evidence about this
  league rather than an opinion about leagues in general.
* **tePremium** — ABSENT.  The market anchor ``ktcSfTep`` **is** KTC's
  TE++ board, so the blend already embeds the structural 2-TE premium; a
  post-blend TE axis would double-count it
  (``tests/league_intel/test_te_premium_invariants.py`` pins this).
  Per-source *pre-blend* alignment is a different insertion point and a
  separate workstream.

  **That pre-blend half landed 2026-07-27** — ``data_contract.py`` now
  converts non-TEP sources' TE contributions onto the board's ``tepp``
  basis using ``te_premium.convert_te_value`` instead of a flat 1.15.
  That is Axis A (source alignment), and it is scoring-profile-safe
  because the target basis is a constant: the basis the board is already
  anchored on.

  Axis B — *which basis does THIS league need?* — is what would belong
  here, and it is genuinely league-scoped rather than merely
  conventionally so.  Measured on the live registry:
  ``measure_te_demand`` returns ``tepp`` for ``dynasty_main`` (2
  mandatory TE starters) and ``base`` for ``dynasty_new`` (1), and the
  two share the ``superflex_tep15_ppr1`` scoring profile.  A one-TE
  league on this board is therefore carrying a two-TE premium it does
  not want, and the only correct place to take it back off is an
  overlay — exactly like ``structuralScarcity``.  Wiring it needs the
  netting ADR-009 requires (the residual against what the blend now
  embeds, which is the measured curve rather than 1.15), so this stays
  ABSENT and named rather than half-applied.
* **projectionCorroboration** — ABSENT pending LI-6.

**Picks never move.**  ``compute_scarcity`` keys off rostered players and
has no ``PICK`` key, so pick rows get an ABSENT axis and factor 1.0.
League-adjusted mode therefore systematically re-prices every *player*
against every *pick*.  That is the single largest behavioural
consequence of this feature and it lands in the trade calculator, so it
belongs in the UI copy rather than buried here.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

from src.league_intel.adjustment import build_board_adjustments
from src.league_intel.values import MODEL_VERSION, VALUE_SCHEMA_VERSION

__all__ = ["build_league_adjusted_payload"]

# Below this the overlay is not worth carrying: a 0.1% move is inside
# the noise of the consensus blend it is applied to.
_MIN_RELATIVE_MOVE = 0.001


def _scarcity_to_mapping(scarcity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalise ``ScarcityComponents`` objects to their dict form."""
    if not scarcity:
        return None
    out: dict[str, Any] = {}
    for pos, comp in scarcity.items():
        out[str(pos).upper()] = comp.to_dict() if hasattr(comp, "to_dict") else comp
    return out


def _row_key(row: Mapping[str, Any]) -> str:
    return str(row.get("displayName") or row.get("canonicalName") or "").strip()


def _inactive_axes(
    scoring_fit: Any | None, reception_fit: Mapping[str, float] | None = None
) -> list[str]:
    """Which axes contributed nothing to this board, by name."""
    names = ["tePremium", "projectionCorroboration"]
    trusted = bool(
        scoring_fit is not None
        and any(
            getattr(f, "trusted", False) for f in getattr(scoring_fit, "positions", {}).values()
        )
    )
    if not trusted:
        names.append("scoringFit")
    if not reception_fit:
        names.append("receptionFit")
    return names


def build_league_adjusted_payload(
    rows: Sequence[Mapping[str, Any]],
    scarcity: Mapping[str, Any] | None,
    *,
    league_key: str,
    config_version: int | None = None,
    data_through: str | None = None,
    contract_version: str | None = None,
    scrape_timestamp: str | None = None,
    scoring_fit: Any | None = None,
    reception_fit: Mapping[str, float] | None = None,
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Compute this league's adjusted board as an overlay payload.

    ``factors`` is sparse — only rows the adjustment actually moved, so
    absence means "unchanged".  ``ranks`` and ``tiers`` are dense over
    the ranked board, for the reason in the module docstring.

    ``scarcity`` of ``None`` is a legitimate state, not an error: the
    roster snapshot was unavailable.  Every axis is then ABSENT and the
    board degrades to consensus rather than to a guess.

    The re-rank runs through
    :func:`src.api.data_contract.compact_ranks_and_tiers` — the same
    function the pipeline uses — on **shallow copies**.  Mutating the
    caller's rows would corrupt ``latest_contract_data``, which is a
    shared module global read by every other request.
    """
    from src.league_intel.overlay import (  # noqa: PLC0415 - heavy import graph
        adjusted_rows as apply_overlay_rows,
    )

    normalised = _scarcity_to_mapping(scarcity)
    board = build_board_adjustments(
        rows,
        scarcity=normalised,
        scoring_fit=scoring_fit,
        reception_fit=reception_fit,
        config_version=config_version,
        data_through=data_through,
    )

    factors: dict[str, float] = {}
    for exp in board.explanations:
        consensus = exp.consensus_value
        adjusted = exp.league_adjusted_value
        if not consensus or adjusted is None or consensus <= 0:
            continue
        if abs(adjusted - consensus) / consensus < _MIN_RELATIVE_MOVE:
            continue
        factors[exp.display_name] = round(float(adjusted) / float(consensus), 6)

    ranks: dict[str, int] = {}
    tiers: dict[str, int] = {}
    warnings: list[str] = []

    if factors:
        # ONE implementation of "apply factors and re-rank", shared with
        # the server-side engine path (``src.league_intel.overlay``).
        # Two copies of this would drift, and the failure would be
        # silent: the client would render one adjusted board while the
        # trade engines priced against a different one.
        ranked = apply_overlay_rows(rows, factors)

        if ranked is None:
            # Serving an incoherent board is worse than serving none:
            # the client would render ranks that contradict the values
            # next to them. Degrade to consensus and say why.
            logging.warning(
                "league-adjusted overlay incoherent for %s; serving no-op",
                league_key,
            )
            warnings.append("ranking incoherent; overlay suppressed")
            factors = {}
        else:
            # Read the EXPERIMENTAL rank/tier, not the canonical ones.
            #
            # ``adjusted_rows`` stopped writing canonical fields when this
            # methodology was rejected for canonical promotion (2026-08-14,
            # see docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md) —
            # the rows it returns now carry the canonical value and rank
            # untouched, with the adjusted ordering under its own names.
            # This publisher is the experimental board's publisher, so the
            # experimental ordering is exactly what it wants; reading the
            # canonical names here would silently publish the market
            # ordering under an "adjusted" label.
            from src.league_intel.overlay import (  # noqa: PLC0415 - avoid import cycle
                EXPERIMENTAL_RANK_FIELD,
                EXPERIMENTAL_TIER_FIELD,
            )

            for r in ranked:
                name = _row_key(r)
                if not name:
                    continue
                rank = r.get(EXPERIMENTAL_RANK_FIELD)
                tier = r.get(EXPERIMENTAL_TIER_FIELD)
                if isinstance(rank, int):
                    ranks[name] = rank
                if isinstance(tier, int):
                    tiers[name] = tier

    payload: dict[str, Any] = {
        "leagueKey": league_key,
        "schemaVersion": VALUE_SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "adjustmentModelVersion": board.model_version,
        "configVersion": config_version,
        "dataThrough": data_through,
        # Version pin. Overlay ranks are only valid against the contract
        # build they were computed from; a scrape landing between the
        # base fetch and the overlay fetch would otherwise apply board
        # B's ranks to board A's values. The client refuses on mismatch.
        "contractVersion": contract_version,
        "scrapeTimestamp": scrape_timestamp,
        "isNoop": not factors,
        "adjustedCount": len(factors),
        "playerCount": len(board.explanations),
        "rankedCount": len(ranks),
        "monotonicityViolations": [v.to_dict() for v in board.monotonicity_violations],
        "scarcity": normalised or {},
        "factors": factors,
        "ranks": ranks,
        "tiers": tiers,
        "warnings": warnings,
        # Named so a reader does not have to infer the omission from an
        # empty diff — see the module docstring for why TE is out.
        # Named so a reader does not have to infer an omission from an
        # empty diff.  scoringFit joins the list only when it is off or
        # unmeasured -- when it IS live it shows up in the axes instead,
        # and listing it in both places would be a contradiction.
        "inactiveAxes": _inactive_axes(scoring_fit, reception_fit),
    }
    if include_explanations:
        payload["explanations"] = [e.to_dict() for e in board.explanations]
    return payload
