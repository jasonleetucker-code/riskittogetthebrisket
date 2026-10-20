"""Verified league format — one read of everything a league's rules ARE.

Composes three existing owners and adds no rule of its own:

* **scoring identity** — ``sf1`` fingerprint and its ``fresh`` / ``stale`` /
  ``missing`` evidence state, from :mod:`src.api.league_registry`
  (``scoring_fingerprint_for_league`` / ``scoring_evidence_state``).  The
  fingerprint is ``None`` unless the evidence is ``fresh``: a snapshot
  proves when it was taken, not that it is still true;
* **market format** — :func:`src.trade.market_trade_format.format_from_registry`
  (slots from the canonical lineup truth ladder, the card only when fresh,
  registry defaults never promoted to facts);
* **format fingerprint** — ``tmf1`` via
  :func:`src.trade.market_trade_format.format_fingerprint`, the one format
  hash.  No second format hash is defined here (pinned by test).

What this module adds is a VERDICT, not a value: which axes of the format
are known, and whether the whole format is verified.  An unknown axis stays
``None`` and is listed; it is never coerced to ``0`` / ``False``, and a
format with any unknown required axis gets ``format_fingerprint = None`` —
a fingerprint over an unknown would claim an identity nobody proved.

``league_key`` is REQUIRED.  There is no default league: a caller that does
not say which league it means gets an error, never the registry default
(so ``dynasty_new`` — or any league — is only ever resolved when named).

Batch-1 status: pure library, no production importer (pinned by an
import-graph test).  Nothing served reads it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from src.trade.market_trade_format import (
    SOURCE_UNKNOWN,
    TradeMarketFormat,
    format_fingerprint,
    format_from_registry,
)

__all__ = [
    "REQUIRED_FORMAT_AXES",
    "STATE_UNKNOWN_LEAGUE",
    "STATE_UNVERIFIED",
    "STATE_VERIFIED",
    "VerifiedLeagueFormat",
    "resolve_league_format",
]

STATE_VERIFIED = "verified"
STATE_UNVERIFIED = "unverified"
STATE_UNKNOWN_LEAGUE = "unknown_league"

EvidenceState = Literal["fresh", "stale", "missing"]

#: ``TradeMarketFormat`` attributes that must ALL be known for the format to
#: be verified (and fingerprinted).  ``season`` is deliberately absent:
#: ``format_from_registry`` never states it (registry entries carry no
#: season), so requiring it would make every format unverifiable.  The
#: season this module reports is the scoring card's VERIFIED season, and it
#: exists only when the card is fresh.
REQUIRED_FORMAT_AXES: tuple[str, ...] = (
    "dynasty_state",
    "teams",
    "roster_size",
    "taxi_size",
    "best_ball",
    "demand",
    "total_starters",
    "idp_enabled",
    "scoring",
)


@dataclass(frozen=True)
class VerifiedLeagueFormat:
    """One league's format, with what is and is not proven about it."""

    league_key: str
    #: The NFL season the scoring card is VERIFIED to describe; ``None``
    #: unless the scoring evidence is ``fresh`` (unknown is not "this year").
    season: int | None
    #: ``sf1`` scoring identity; ``None`` unless the evidence is ``fresh``.
    scoring_fingerprint: str | None
    scoring_evidence_state: EvidenceState
    market_format: TradeMarketFormat
    #: ``tmf1`` from ``market_trade_format.format_fingerprint``; ``None``
    #: whenever any :data:`REQUIRED_FORMAT_AXES` axis is unknown.
    format_fingerprint: str | None
    state: str
    reason: str | None
    unknown_axes: tuple[str, ...] = ()
    resolved_at: str | None = None
    #: Snapshot of the market format's own ``to_dict`` (fingerprint included)
    #: so the published view and the fingerprint come from one serialization.
    market_format_dict: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "season": self.season,
            "scoringFingerprint": self.scoring_fingerprint,
            "scoringEvidenceState": self.scoring_evidence_state,
            "formatFingerprint": self.format_fingerprint,
            "marketFormat": dict(self.market_format_dict),
            "unknownAxes": list(self.unknown_axes),
            "state": self.state,
            "reason": self.reason,
            "resolvedAt": self.resolved_at,
        }


def _unknown_axes(fmt: TradeMarketFormat) -> tuple[str, ...]:
    return tuple(axis for axis in REQUIRED_FORMAT_AXES if getattr(fmt, axis) is None)


def resolve_league_format(
    league_key: str,
    *,
    now: datetime | None = None,
    roster_positions: Sequence[str] | None = None,
) -> VerifiedLeagueFormat:
    """Resolve ``league_key``'s verified format from the canonical owners.

    ``roster_positions`` is the live host lineup when the caller holds it
    (passed straight to ``format_from_registry`` — the lineup truth ladder
    decides, not this function).  ``now`` stamps ``resolved_at`` only: the
    freshness verdict is the registry owner's, at its own clock, and is not
    re-derived here, so two clocks never decide one fact.

    Raises ``ValueError`` when ``league_key`` is empty — there is no default.
    An unknown key is not an error: it returns ``state = "unknown_league"``
    with every identity ``None``.
    """
    if not isinstance(league_key, str) or not league_key.strip():
        raise ValueError(
            "league_key is required; resolve_league_format never falls back to a default league"
        )
    key = league_key.strip()
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()

    from src.api import league_registry as reg  # noqa: PLC0415

    cfg = reg.get_league_by_key(key)
    if cfg is None:
        fmt = TradeMarketFormat(source=SOURCE_UNKNOWN)
        return VerifiedLeagueFormat(
            league_key=key,
            season=None,
            scoring_fingerprint=None,
            scoring_evidence_state="missing",
            market_format=fmt,
            format_fingerprint=None,
            state=STATE_UNKNOWN_LEAGUE,
            reason="league_key_not_in_registry",
            unknown_axes=REQUIRED_FORMAT_AXES,
            resolved_at=stamp,
            market_format_dict=fmt.to_dict(),
        )

    evidence: EvidenceState = reg.scoring_evidence_state(cfg)  # type: ignore[assignment]
    sf = reg.scoring_fingerprint_for_league(cfg) if evidence == "fresh" else None
    season: int | None = None
    if evidence == "fresh":
        # ``fresh`` already proved the card's recorded season equals the
        # projection season the registry resolved; name that same season.
        from src.bdvm.actuals import nfl_projection_season  # noqa: PLC0415

        season = int(nfl_projection_season())

    fmt = format_from_registry(cfg.key, roster_positions=roster_positions)
    fmt_dict = fmt.to_dict()
    unknown = _unknown_axes(fmt)
    tmf = None if unknown else format_fingerprint(fmt_dict)

    reasons: list[str] = []
    if evidence != "fresh":
        reasons.append(f"scoring_evidence_{evidence}")
    elif sf is None:
        # State and fingerprint are two registry reads; a snapshot crossing
        # its age budget (or rewritten) between them must not yield a
        # "verified" format with no proven scoring identity.
        reasons.append("scoring_fingerprint_unavailable")
    if unknown:
        reasons.append("unknown_axes:" + ",".join(unknown))
    return VerifiedLeagueFormat(
        league_key=cfg.key,
        season=season,
        scoring_fingerprint=sf,
        scoring_evidence_state=evidence,
        market_format=fmt,
        format_fingerprint=tmf,
        state=STATE_VERIFIED if not reasons else STATE_UNVERIFIED,
        reason=";".join(reasons) or None,
        unknown_axes=unknown,
        resolved_at=stamp,
        market_format_dict=fmt_dict,
    )
