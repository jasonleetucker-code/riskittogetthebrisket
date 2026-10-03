"""Use Team Context (#842 / C3-CTX-01) — the ONE mode contract.

Every trade evaluation and generation surface takes the same switch:
``/api/trade/simulate``, ``/api/trade/analyze``, ``/api/trade/finder``,
``/api/trade/suggestions``, ``/api/angle/find`` and ``/api/angle/packages``.
Before this module each route parsed ``useTeamContext`` itself (two did, four
did not) and each stamped its own shape, so "is team context in this answer?"
had as many answers as there were routes.

Binding records: ``docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md``
§3-§6 and ``docs/OWNER_FEATURE_ADDENDUM_2026-08-14_TRADE_CONTEXT_AND_TOPOLOGY.md``.

What the switch is
──────────────────
* **ON (default)** — team-specific evidence may influence the verdict or the
  ranking: roster capacity and forced drops for BOTH teams (#843), the final
  legal roster's lineup utility (#1173), Competitive Posture (#840), roster fit,
  and posture-directed pick flow (#841).
* **OFF — "Asset-Only Analysis"** — none of that may influence the verdict or
  ranking.  Canonical league-format asset value, package / Value Adjustment
  math, external market evidence, intrinsic age, pick value, uncertainty and
  hard user constraints still apply: OFF removes TEAM context, never the
  league's scoring or roster FORMAT (TEP / Superflex / IDP stay inside
  ``rankDerivedValue``).

Three rules this module exists to make structural
─────────────────────────────────────────────────
1. **Only an explicit boolean ``false`` turns it off.**  A missing, null,
   string or numeric value is the canonical default (ON).  A typo must never
   silently strip team context from an answer.
2. **Never a silent ON → OFF fallback.**  When a context dimension cannot be
   computed it is reported ``unavailable`` with a reason while the mode stays
   ``team``.  :func:`mode_block` has no code path that flips ``applied``.
3. **OFF labels, it does not hide.**  A team-context block a surface still
   shows for convenience carries ``includedInVerdict: false`` and the exact
   wording "not included in this verdict" (:func:`label_excluded`).

This is a contract, not an engine: it computes no value and decides nothing
about any trade.  The engines read the mode from here and own their dimensions.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

__all__ = [
    "ASSET_ONLY_LABEL",
    "CONTEXT_DIMENSIONS",
    "EXCLUDED_NOTE",
    "MODE_ASSET_ONLY",
    "MODE_TEAM",
    "TEAM_CONTEXT_FIELD",
    "TEAM_LABEL",
    "dimension_entry",
    "label_excluded",
    "mode_block",
    "parse_use_team_context",
]

#: The wire name every route reads, body field for POST.
TEAM_CONTEXT_FIELD = "useTeamContext"

MODE_TEAM = "team"
MODE_ASSET_ONLY = "asset_only"
TEAM_LABEL = "Team Context"
ASSET_ONLY_LABEL = "Asset-Only Analysis"
#: The supersession's exact wording (§4) for a team-context panel shown while OFF.
EXCLUDED_NOTE = "not included in this verdict"

#: The team-specific dimensions a surface may consult with context ON.  Keyed
#: so a payload can name exactly which ones it included, excluded or could not
#: compute; the labels are the user-facing words.
CONTEXT_DIMENSIONS: dict[str, str] = {
    "rosterCapacity": "Roster capacity / forced drops (your team)",
    "counterpartyCapacity": "Roster capacity / forced drops (their team)",
    "finalRoster": "Final legal roster (lineup, Team Strength)",
    "rosterUtility": "Best-ball lineup impact on the final legal roster",
    "rosterFit": "Positional fit / needs",
    "competitivePosture": "Competitive posture (PUSH / HOLD / RETOOL / REBUILD)",
    "currentSeasonEquity": "Playoff / championship odds change",
    "pickStrategy": "Posture-directed draft-pick flow",
}

#: ``included`` — counts toward the verdict / ranking;  ``context`` — computed
#: and shown, informs the explanation, never a vote;  ``excluded_by_mode`` —
#: switched off by Asset-Only;  ``unavailable`` — could not be computed (the
#: mode does NOT change because of it);  ``not_applicable`` — this surface
#: never consults it.
_STATES = ("included", "context", "excluded_by_mode", "unavailable", "not_applicable")


def parse_use_team_context(raw: Any) -> bool:
    """``True`` unless ``raw`` is literally the boolean ``False``.

    ``isinstance(raw, bool)`` first, so ``0`` / ``"false"`` / ``None`` are the
    default rather than an accidental OFF.
    """
    if isinstance(raw, bool):
        return raw
    return True


def dimension_entry(key: str, state: str, reason: str | None = None) -> dict[str, Any]:
    """One row of a mode block's ``dimensions`` list."""
    if state not in _STATES:
        raise ValueError(f"unknown dimension state {state!r}; expected one of {_STATES}")
    entry: dict[str, Any] = {
        "dimension": key,
        "label": CONTEXT_DIMENSIONS.get(key, key),
        "state": state,
        "includedInVerdict": state == "included",
    }
    if reason:
        entry["reason"] = reason
    if state == "excluded_by_mode":
        entry["note"] = EXCLUDED_NOTE
    elif state == "context":
        entry["note"] = "shown as context; not a vote"
    return entry


def mode_block(
    applied: bool,
    *,
    dimensions: Mapping[str, tuple[str, str | None] | str] | None = None,
    consulted: Iterable[str] | None = None,
) -> dict[str, Any]:
    """The ``teamContext`` block every trade route stamps.

    ``dimensions`` maps a dimension key to its state (or ``(state, reason)``)
    for a surface that measured it.  ``consulted`` lists the dimensions the
    surface WOULD consult with context ON; when OFF each of them is reported
    ``excluded_by_mode`` so the reader can see what was switched off.

    ``applied`` is echoed verbatim — this function never decides the mode.
    """
    applied = bool(applied)
    rows: dict[str, dict[str, Any]] = {}
    for key in consulted or ():
        rows[key] = dimension_entry(key, "included" if applied else "excluded_by_mode")
    for key, spec in (dimensions or {}).items():
        state, reason = (spec, None) if isinstance(spec, str) else spec
        if not applied and state in ("included", "context"):
            # An OFF answer cannot have used a team dimension: if a caller
            # says otherwise that is a bug to surface, not to paper over.
            raise ValueError(f"dimension {key!r} reported included while team context is OFF")
        rows[key] = dimension_entry(key, state, reason)
    return {
        "applied": applied,
        "mode": MODE_TEAM if applied else MODE_ASSET_ONLY,
        "label": TEAM_LABEL if applied else ASSET_ONLY_LABEL,
        "dimensions": list(rows.values()),
    }


def label_excluded(block: Any) -> Any:
    """Mark a team-context block a surface shows while OFF.

    Returns a shallow copy with ``includedInVerdict: false`` and the
    supersession's wording; a non-dict (absent / unavailable) passes through.
    """
    if not isinstance(block, dict):
        return block
    out = dict(block)
    out["includedInVerdict"] = False
    out["contextNote"] = EXCLUDED_NOTE
    return out
