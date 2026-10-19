"""Published shapes of the league fair value challenger (shadow only).

Two dataclasses cross a workstream boundary, and both serialise to camelCase
through ``to_dict()`` so a consumer's parity test can read the committed JSON
fixture under ``tests/fixtures/league_valuation/`` instead of importing this
package (batch-1 isolation rule):

* :class:`UtilityEvidence` -- what BDVM's own fundamental output says about one
  player's league utility, with explicit missing / stale / proxy states. It is
  the ONLY utility input the challenger reads.
* :class:`LeagueFairValue` -- one asset's challenger value on the canonical
  1-9999 scale, under its own field names.

Neither shape carries a canonical value field (``rankDerivedValue`` and the
other names in ``src.league_intel.overlay.CANONICAL_VALUE_FIELDS``). The market
value travels as ``marketValue`` -- a read of the canonical number, labelled as
such -- and the challenger's number as ``fairValue``. A consumer can never
mistake one for the other by field name.

States (the decision engine's vocabulary, so a later provider adapter is a
rename, not a translation):

* evidence ``state`` in :data:`EVIDENCE_STATES`. Only ``available`` may enter a
  population. ``partial`` is proxy-only evidence; ``stale`` is outside its
  freshness budget; ``unavailable`` is missing (no projection, no balanced
  strategy, BDVM unpriced the player, or the payload was not ``ok``).
* fair value ``state`` is ``available`` (the asset was in a scope population and
  went through quantile matching; its shrinkage may still be zero) or
  ``excluded`` (it never entered a population; ``fairValue`` equals
  ``marketValue`` exactly and ``excludedReason`` names why).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

#: Identity of this challenger. Never a canonical model id.
MODEL_VERSION = "league_fair_value_v1_shadow"

#: The decision engine's evidence vocabulary. Only ``available`` votes.
EVIDENCE_STATES: tuple[str, ...] = ("available", "partial", "stale", "unavailable")
FRESHNESS_STATES: tuple[str, ...] = ("fresh", "stale", "missing")
SCOPES: tuple[str, ...] = ("OFFENSE", "IDP")

FAIR_VALUE_STATE_AVAILABLE = "available"
FAIR_VALUE_STATE_EXCLUDED = "excluded"
FAIR_VALUE_STATES: tuple[str, ...] = (FAIR_VALUE_STATE_AVAILABLE, FAIR_VALUE_STATE_EXCLUDED)

#: Lineage member this artifact is declared under in ``src.evidence_lineage``
#: (correlation group ``league_scored_projection``; it descends from
#: ``bdvm_fundamental``). Opaque strings in batch 1, validated against the
#: registry in batch 2.
LINEAGE_MEMBER = "league_fair_value"
UTILITY_LINEAGE_MEMBER = "bdvm_fundamental"

#: Label carried by every TE row: the residual against the tepp-anchored market
#: IS the league TE-demand signal; nothing is added for TE.
TE_BASIS_LABEL = "te_basis_tepp"


class ContractError(ValueError):
    """A shape that must not exist (fail closed)."""


@dataclass(frozen=True)
class UtilityEvidence:
    """BDVM's league utility for one player, or an explicit absence of it.

    ``points_over_replacement`` is SIGNED (``fpg - R`` on BDVM's own
    ReplacementEngine level), never truncated: a player below replacement keeps a
    negative number and stays ordered, and that is a different statement from a
    missing projection (``None`` + ``state='unavailable'``).

    ``balanced_dv`` is BDVM's balanced-strategy discounted dynasty value (the
    multi-season fundamental). It is the PRIMARY utility order; the signed
    points over replacement break ties inside it -- notably the block BDVM's risk
    penalty truncates to zero -- so below-replacement players are not tied with
    each other or with missing ones.
    """

    asset_key: str
    player_id: str | None
    position: str
    scope: Literal["OFFENSE", "IDP"]
    points_over_replacement: float | None
    projection_families: int
    is_proxy: bool
    as_of: str | None
    freshness: Literal["fresh", "stale", "missing"]
    quality: float | None
    lineage_ids: tuple[str, ...]
    state: str
    reason: str | None
    balanced_dv: float | None = None
    strategy: str = "balanced"

    def __post_init__(self) -> None:
        if self.state not in EVIDENCE_STATES:
            raise ContractError(f"evidence state must be one of {EVIDENCE_STATES}: {self.state!r}")
        if self.freshness not in FRESHNESS_STATES:
            raise ContractError(f"freshness must be one of {FRESHNESS_STATES}: {self.freshness!r}")
        if self.scope not in SCOPES:
            raise ContractError(f"scope must be one of {SCOPES}: {self.scope!r}")
        if isinstance(self.projection_families, bool) or not isinstance(
            self.projection_families, int
        ):
            raise ContractError("projection_families must be an int")
        if self.projection_families < 0:
            raise ContractError("projection_families must be >= 0")
        if self.quality is not None and not (0.0 <= float(self.quality) <= 1.0):
            raise ContractError(f"quality must lie in [0, 1]: {self.quality!r}")
        if self.state == "available":
            # Missing is never zero: an available record carries every number
            # the challenger reads, or it is not available.
            if self.points_over_replacement is None or self.balanced_dv is None:
                raise ContractError("available evidence needs both utility components")
            if self.quality is None:
                raise ContractError("available evidence needs a quality")
            if self.freshness != "fresh":
                raise ContractError("only fresh evidence can be available")
            if self.is_proxy:
                raise ContractError("proxy-only evidence cannot be available")
        elif not str(self.reason or "").strip():
            raise ContractError("evidence that is not available must say why")

    @property
    def utility_key(self) -> tuple[float, float] | None:
        """The ordering key, or ``None`` when the evidence cannot order."""
        if self.balanced_dv is None or self.points_over_replacement is None:
            return None
        return (float(self.balanced_dv), float(self.points_over_replacement))

    def to_dict(self) -> dict[str, Any]:
        return {
            "assetKey": self.asset_key,
            "playerId": self.player_id,
            "position": self.position,
            "scope": self.scope,
            "pointsOverReplacement": self.points_over_replacement,
            "balancedDv": self.balanced_dv,
            "strategy": self.strategy,
            "projectionFamilies": self.projection_families,
            "isProxy": self.is_proxy,
            "asOf": self.as_of,
            "freshness": self.freshness,
            "quality": self.quality,
            "lineageIds": list(self.lineage_ids),
            "state": self.state,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LeagueFairValue:
    """One asset's challenger value. Never a canonical field.

    ``fair_value`` lies between ``market_value`` and the matched in-population
    value (``matched_value_exact``) and inside the canonical display scale, by
    construction. An excluded asset carries ``fair_value == market_value``
    exactly, with ``excluded_reason``.
    """

    asset_key: str
    player_id: str | None
    scope: str | None
    market_value: int | None
    fair_value: int | None
    matched_value: int | None
    k: float
    utility_rank: float | None
    market_rank: int | None
    excluded_reason: str | None
    model_version: str
    param_set_id: str
    pins: Mapping[str, str]
    state: str
    reason: str | None
    fair_value_exact: float | None = None
    matched_value_exact: float | None = None
    position: str | None = None
    name: str | None = None
    labels: tuple[str, ...] = ()
    fair_rank: int | None = None
    fair_tier: int | None = None
    lineage_ids: tuple[str, ...] = (LINEAGE_MEMBER,)

    def __post_init__(self) -> None:
        if self.state not in FAIR_VALUE_STATES:
            raise ContractError(f"fair value state must be one of {FAIR_VALUE_STATES}")
        if self.state == FAIR_VALUE_STATE_EXCLUDED:
            if not str(self.excluded_reason or "").strip():
                raise ContractError("an excluded asset must name its exclusion reason")
            if self.fair_value != self.market_value:
                raise ContractError("an excluded asset's fair value is its market value exactly")
            if self.k != 0.0:
                raise ContractError("an excluded asset has no shrinkage")
        if not (0.0 <= float(self.k) <= 1.0):
            raise ContractError(f"k must lie in [0, 1]: {self.k!r}")

    @property
    def moved(self) -> bool:
        return (
            self.fair_value is not None
            and self.market_value is not None
            and self.fair_value != self.market_value
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "assetKey": self.asset_key,
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "scope": self.scope,
            "marketValue": self.market_value,
            "fairValue": self.fair_value,
            "fairValueExact": self.fair_value_exact,
            "matchedValue": self.matched_value,
            "matchedValueExact": self.matched_value_exact,
            "k": self.k,
            "utilityRank": self.utility_rank,
            "marketRank": self.market_rank,
            "fairRank": self.fair_rank,
            "fairTier": self.fair_tier,
            "excludedReason": self.excluded_reason,
            "labels": list(self.labels),
            "modelVersion": self.model_version,
            "paramSetId": self.param_set_id,
            "pins": dict(sorted(self.pins.items())),
            "lineageIds": list(self.lineage_ids),
            "state": self.state,
            "reason": self.reason,
        }


# ── parameter set ────────────────────────────────────────────────────────────

#: The declared PRIOR parameter set. Nothing in it is fitted on a board.
DEFAULT_PARAMS_PATH = "config/league_valuation/fair_value_v1.json"
PARAM_SET_NAME = "league_fair_value_v1"


def param_set_id_for(payload: Mapping[str, Any]) -> str:
    """Content hash of a parameter payload, excluding its own ``paramSetId``.

    Same construction as ``src.bdvm.params`` (sorted-key compact JSON, sha256,
    12 hex). Any edit to a PRIOR changes the id, and the committed file must
    carry the id of its own content (pinned by test), so a silently edited
    constant cannot keep an old id in a receipt.
    """
    body = {k: v for k, v in payload.items() if k != "paramSetId"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{PARAM_SET_NAME}:{hashlib.sha256(blob).hexdigest()[:12]}"


def load_params(path: str | None = None) -> dict[str, Any]:
    """Load the PRIOR parameter set and verify its content-addressed id."""
    target = Path(path) if path else Path(__file__).resolve().parents[2] / DEFAULT_PARAMS_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    expected = param_set_id_for(payload)
    if payload.get("paramSetId") != expected:
        raise ContractError(
            f"{target}: paramSetId {payload.get('paramSetId')!r} does not match its content "
            f"({expected!r}); regenerate it with param_set_id_for()"
        )
    return payload
