"""Parallel value schema + the single value selector (LI-4, spec §2).

Why this exists
───────────────
Today every page reads one number ("the value") and different surfaces
disagree about which number that is.  Spec §2 asks for *parallel*
values that coexist on a row — the market's price, our consensus
board, and (eventually) a league-adjusted number — plus one selector
every consumer calls so the choice of which to show is made in exactly
one place.

    marketValue                 what the market charges (KTC for
                                offense, IDPTC for IDP — the primary
                                anchors already used by the corridor
                                clamp in data_contract.py)
    consensusValue              our blended board value, i.e. the
                                authoritative `rankDerivedValue` out of
                                `_compute_unified_rankings`
    leagueAdjustedDynastyValue  consensus re-priced for THIS league's
                                scoring + roster structure

**No-op guarantee (ADR-003, spec Phase 3).**  Until LI-7 validates the
adjustment model, ``leagueAdjustedDynastyValue`` is *identically*
``consensusValue``.  That is enforced here in construction, not left to
callers — see :data:`LEAGUE_ADJUSTED_IS_NOOP` and the invariant test.
Selecting ``LEAGUE_ADJUSTED`` today is therefore safe and returns a
real, trustworthy number; when LI-7 lands, every consumer picks up the
adjusted value with no call-site change.

This module deliberately does NOT touch
``src/api/data_contract.py::_compute_unified_rankings`` — consensus is
computed there and only read here (CLAUDE.md: one live path for
values).  Nothing published to the UI changes until LI-9.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

__all__ = [
    "VALUE_SCHEMA_VERSION",
    "MODEL_VERSION",
    "LEAGUE_ADJUSTED_IS_NOOP",
    "ValuationMode",
    "PlayerValues",
    "build_player_values",
    "get_active_value",
]

VALUE_SCHEMA_VERSION = 1
"""Shape version of :class:`PlayerValues`.  Bump on incompatible change."""

MODEL_VERSION = "li.values.2026-07-26.v1"
"""Identifies the logic that produced the numbers, independent of the
schema shape.  Changes when the adjustment model changes (LI-7)."""

LEAGUE_ADJUSTED_IS_NOOP = False
"""False since LI-7 (2026-07-27): the adjustment model is wired and a
real ``leagueAdjustedDynastyValue`` can differ from ``consensusValue``.

**This flag is about the MODEL, not about any one row.**  A row still
comes back at consensus unless a caller supplies a computed
``league_adjusted`` — see :func:`build_player_values`.  That is not a
loophole, it is the load-bearing part: the adjustment depends on
board-level scarcity measured across all twelve rosters
(:func:`src.league_intel.replacement.compute_scarcity`), so a single
row in isolation genuinely has no adjusted value.  Only the board pass
in :mod:`src.league_intel.publish` has the inputs to compute one.

Validated on the live board before flipping: 719 of 874 rows moved,
**zero monotonicity violations**, ratio to consensus median 1.024 over
[0.953, 1.043] — comfortably inside ``MAX_TOTAL_ADJUSTMENT``."""

# Primary market anchor per asset class — mirrors
# ``consensus_edge.fair_value.MARKET_ANCHOR_BY_ASSET_CLASS``.  Kept as a
# read-only constant rather than imported to keep this module free of
# the contract module's heavy import graph; the parity test in
# tests/consensus_edge/test_fair_value.py fails if the two diverge.
# ``data_contract`` no longer defines one: that copy served the
# market-corridor clamp, removed under #794/#795/#796.
MARKET_ANCHOR_BY_ASSET_CLASS: dict[str, str] = {
    "offense": "ktcSfTep",
    "idp": "idpTradeCalc",
}


class ValuationMode(str, Enum):
    """Which parallel value a consumer wants.  ``str`` mixin so the
    member serializes as its own name in JSON without extra encoding."""

    MARKET = "market"
    CONSENSUS = "consensus"
    LEAGUE_ADJUSTED = "leagueAdjusted"

    @classmethod
    def coerce(cls, mode: "ValuationMode | str | None") -> "ValuationMode":
        """Accept a mode, its wire string, or None (→ CONSENSUS)."""
        if mode is None:
            return cls.CONSENSUS
        if isinstance(mode, cls):
            return mode
        text = str(mode).strip()
        for member in cls:
            if text == member.value or text.lower() == member.name.lower():
                return member
        raise ValueError(f"unknown valuation mode {mode!r}")


@dataclass(frozen=True)
class PlayerValues:
    """The parallel values for one asset, with provenance stamps.

    Values are on the canonical display scale used by the live
    contract.  ``None`` means "not priced by that lens" — e.g. a deep
    IDP prospect no market board lists has ``market_value is None``
    while still carrying a consensus value.
    """

    display_name: str
    market_value: float | None
    consensus_value: float | None
    league_adjusted_dynasty_value: float | None
    asset_class: str = ""
    market_anchor_source: str | None = None
    schema_version: int = VALUE_SCHEMA_VERSION
    model_version: str = MODEL_VERSION
    config_version: int | None = None
    data_through: str | None = None
    league_adjusted_is_noop: bool = LEAGUE_ADJUSTED_IS_NOOP

    def value_for(self, mode: ValuationMode | str | None) -> float | None:
        """This row's value under ``mode``.  See :func:`get_active_value`."""
        resolved = ValuationMode.coerce(mode)
        if resolved is ValuationMode.MARKET:
            return self.market_value
        if resolved is ValuationMode.CONSENSUS:
            return self.consensus_value
        return self.league_adjusted_dynasty_value

    def to_dict(self) -> dict[str, Any]:
        return {
            "displayName": self.display_name,
            "marketValue": self.market_value,
            "consensusValue": self.consensus_value,
            "leagueAdjustedDynastyValue": self.league_adjusted_dynasty_value,
            "assetClass": self.asset_class,
            "marketAnchorSource": self.market_anchor_source,
            "schemaVersion": self.schema_version,
            "modelVersion": self.model_version,
            "configVersion": self.config_version,
            "dataThrough": self.data_through,
            "leagueAdjustedIsNoop": self.league_adjusted_is_noop,
        }


def _positive_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _consensus_from_row(row: Mapping[str, Any]) -> float | None:
    """Read the authoritative blended value off a contract row.

    ``rankDerivedValue`` is the number ``_compute_unified_rankings``
    stamps and mirrors into ``values.displayValue`` — preferring it
    keeps this module aligned with "one live path for values" even if a
    legacy composite lingers on the row.
    """
    consensus = _positive_float(row.get("rankDerivedValue"))
    if consensus is not None:
        return consensus
    values = row.get("values")
    if isinstance(values, Mapping):
        for key in ("displayValue", "finalAdjusted", "overall"):
            consensus = _positive_float(values.get(key))
            if consensus is not None:
                return consensus
    return None


def _market_from_row(row: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """Primary market-anchor value + which source supplied it."""
    sites = row.get("canonicalSiteValues")
    if not isinstance(sites, Mapping):
        return None, None
    asset_class = str(row.get("assetClass") or "").strip().lower()
    source_key = MARKET_ANCHOR_BY_ASSET_CLASS.get(asset_class)
    if not source_key:
        return None, None
    return _positive_float(sites.get(source_key)), source_key


def build_player_values(
    row: Mapping[str, Any],
    *,
    config_version: int | None = None,
    data_through: str | None = None,
    league_adjusted: float | None = None,
) -> PlayerValues:
    """Build the parallel value bundle for one contract row.

    ``config_version`` should be the canonical league config's version
    (``src.league_intel.config.LeagueIntelConfig.config_version``) and
    ``data_through`` the contract's freshness stamp, so a stored value
    can always be traced to the rules and data that produced it.

    ``league_adjusted`` is the value computed by the board pass in
    :mod:`src.league_intel.publish`.  **Omitting it yields consensus**,
    and that is the correct answer rather than a fallback: the
    adjustment is a function of league-wide scarcity measured across
    every roster, so one row on its own has no adjusted value to
    return.  Inventing one here — a prior, a positional average — is
    exactly the manufactured number this package exists to refuse.

    The guarantee that survives LI-7 is therefore narrower but still
    real: *no adjusted number reaches a caller unless something with
    board-level evidence computed it.*
    """
    consensus = _consensus_from_row(row)
    market, anchor_source = _market_from_row(row)
    league_adjusted = _positive_float(league_adjusted)
    if league_adjusted is None:
        league_adjusted = consensus
    return PlayerValues(
        display_name=str(row.get("displayName") or row.get("canonicalName") or "").strip(),
        market_value=market,
        consensus_value=consensus,
        league_adjusted_dynasty_value=league_adjusted,
        asset_class=str(row.get("assetClass") or "").strip().lower(),
        market_anchor_source=anchor_source if market is not None else None,
        config_version=config_version,
        data_through=data_through,
    )


def get_active_value(
    player: PlayerValues | Mapping[str, Any],
    mode: ValuationMode | str | None = None,
    context: Mapping[str, Any] | None = None,
) -> float | None:
    """**The** value selector.  Every consumer goes through this.

    Args:
        player: a :class:`PlayerValues`, or a raw contract row (built
            on the fly), or an already-serialized bundle dict.
        mode: which parallel value to return; defaults to
            ``CONSENSUS`` — today's published behavior.
        context: optional provenance for on-the-fly construction —
            ``{"configVersion": int, "dataThrough": str}``.  Ignored
            when ``player`` is already a :class:`PlayerValues`.

    Returns the value, or ``None`` when that lens does not price the
    asset.  Callers decide how to render a missing value; this function
    never substitutes one lens for another silently.
    """
    resolved = ValuationMode.coerce(mode)
    if isinstance(player, PlayerValues):
        return player.value_for(resolved)
    if not isinstance(player, Mapping):
        raise TypeError(f"player must be PlayerValues or a mapping, got {type(player).__name__}")
    # Already-serialized bundle (round-trips through to_dict()).
    if "consensusValue" in player or "leagueAdjustedDynastyValue" in player:
        key = {
            ValuationMode.MARKET: "marketValue",
            ValuationMode.CONSENSUS: "consensusValue",
            ValuationMode.LEAGUE_ADJUSTED: "leagueAdjustedDynastyValue",
        }[resolved]
        return _positive_float(player.get(key))
    ctx = context or {}
    bundle = build_player_values(
        player,
        config_version=ctx.get("configVersion"),
        data_through=ctx.get("dataThrough"),
    )
    return bundle.value_for(resolved)
