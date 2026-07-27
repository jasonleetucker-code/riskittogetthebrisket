"""LI-9: publish league-adjusted values for one league.

This is the only place a real ``leagueAdjustedDynastyValue`` is
produced.  It exists as its own module, separate from the consensus
pipeline, for a reason that is architectural rather than cosmetic.

WHY THIS IS NOT STAMPED INTO THE CONTRACT
─────────────────────────────────────────
CLAUDE.md's core split: *scoring profile controls rankings, league key
controls context.*  The consensus board is scoring-profile-scoped —
two leagues with identical scoring share one computed board and one
cached payload.  The adjustment here is driven by
``lineupScarcity``, measured by
:func:`src.league_intel.replacement.compute_scarcity` from **this
league's twelve rosters**.  Two leagues with identical scoring but
different rosters get different adjusted values.

So an adjusted value cannot live on the shared contract without
collapsing that split — one league's roster shape would silently
reprice another's board.  It is served per league instead, and the
client overlays it, the same shape as the rankings-override delta.

WHAT MOVES A VALUE, AND WHAT DELIBERATELY DOES NOT
──────────────────────────────────────────────────
* **structuralScarcity** — live.  Positions whose starter demand
  exceeds the reference get a lift, deeper positions a trim.  Measured
  from the exact lineup optimizer over real rosters, so it is evidence
  about this league rather than an opinion about leagues in general.
* **tePremium** — ABSENT by design, and this is the load-bearing
  omission.  The market anchor ``ktcSfTep`` **is** KTC's TE++ board, so
  the consensus blend already carries the structural 2-TE premium.
  Applying a measured TE premium on top double-counts it —
  ``tests/league_intel/test_te_premium_invariants.py`` pins exactly
  this.  ADR-009 leaves the alignment-versus-scoring question open, and
  an axis that is wrong by ~15% on every TE is worse than an axis that
  contributes nothing.
* **projectionCorroboration** — ABSENT pending LI-6.  No repo source
  exposes raw statistical categories, so there is nothing to re-score.

Scoring settings reach the values through scarcity, not through a
separate scoring axis: the starter slots that
``measure_endogenous_starters`` solves over come from this league's
``rosterSettings``, and the canonical config's version is stamped on
the payload so a served value is always traceable to the rules that
produced it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.league_intel.adjustment import build_board_adjustments
from src.league_intel.values import MODEL_VERSION, VALUE_SCHEMA_VERSION

__all__ = ["build_league_adjusted_payload"]

# Below this the overlay is not worth a network round trip or the risk
# of churning the UI: a 0.1% move is inside the noise of the consensus
# blend it is applied to.
_MIN_RELATIVE_MOVE = 0.001


def _scarcity_to_mapping(scarcity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Normalise ``ScarcityComponents`` objects to their dict form.

    ``structural_scarcity_axis`` accepts either, but normalising here
    keeps the served diagnostics JSON-safe without a second pass.
    """
    if not scarcity:
        return None
    out: dict[str, Any] = {}
    for pos, comp in scarcity.items():
        out[str(pos).upper()] = comp.to_dict() if hasattr(comp, "to_dict") else comp
    return out


def build_league_adjusted_payload(
    rows: Sequence[Mapping[str, Any]],
    scarcity: Mapping[str, Any] | None,
    *,
    league_key: str,
    config_version: int | None = None,
    data_through: str | None = None,
    include_explanations: bool = False,
) -> dict[str, Any]:
    """Compute this league's adjusted board as an overlay payload.

    ``values`` carries **only rows whose value actually moved**, keyed
    by ``displayName``.  A client merges it over the consensus board and
    leaves everything else alone, so the payload stays small and an
    unmentioned player is unambiguously "unchanged" rather than
    "missing".

    ``scarcity`` of ``None`` is a legitimate state, not an error — it
    means the roster snapshot was unavailable.  Every axis is then
    ABSENT, ``values`` is empty, and ``isNoop`` is True: the board
    degrades to consensus rather than to a guess.
    """
    normalised = _scarcity_to_mapping(scarcity)
    board = build_board_adjustments(
        rows,
        scarcity=normalised,
        config_version=config_version,
        data_through=data_through,
    )

    values: dict[str, float] = {}
    for exp in board.explanations:
        consensus = exp.consensus_value
        adjusted = exp.league_adjusted_value
        if not consensus or adjusted is None or consensus <= 0:
            continue
        if abs(adjusted - consensus) / consensus < _MIN_RELATIVE_MOVE:
            continue
        values[exp.display_name] = round(float(adjusted), 2)

    payload: dict[str, Any] = {
        "leagueKey": league_key,
        "schemaVersion": VALUE_SCHEMA_VERSION,
        "modelVersion": MODEL_VERSION,
        "adjustmentModelVersion": board.model_version,
        "configVersion": config_version,
        "dataThrough": data_through,
        # ``isNoop`` reports the SERVED payload, so a client can trust
        # "nothing to overlay" without diffing the map itself.
        "isNoop": not values,
        "adjustedCount": len(values),
        "playerCount": len(board.explanations),
        "monotonicityViolations": [v.to_dict() for v in board.monotonicity_violations],
        "scarcity": normalised or {},
        "values": values,
        # Named so a reader does not have to infer the omission from an
        # empty diff — see this module's docstring for why TE is out.
        "inactiveAxes": ["tePremium", "projectionCorroboration"],
    }
    if include_explanations:
        payload["explanations"] = [e.to_dict() for e in board.explanations]
    return payload
