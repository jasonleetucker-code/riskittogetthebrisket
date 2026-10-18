"""Trade discovery filters and Most Impactful ordering — owner directive 2026-10-18.

ONE vocabulary for every discovery view on ``/arbitrage`` (Golden Upgrades,
Package Scan, Best Offer by Opponent, Package Builder):

* **Target Quality** — Top 100 / Top 250 / Top 500 / All Players over the
  CANONICAL overall dynasty rank (``canonicalConsensusRank``), plus an optional
  minimum incoming canonical value (``rankDerivedValue``).  It applies to what
  the user ACQUIRES, never to compensation sent: at least one incoming PLAYER
  must meet it (a draft pick never does), checked per asset during enumeration
  (``src.packages.enumerate_packages(receive_anchor=...)``) so a pile of
  low-value pieces can never satisfy it through combined value.  It is a
  different concept from the finder's per-market top-150
  (``finder.MARKET_TOP_N_FILTER``), which ranks PUBLIC markets and stays an
  engine gate exactly as before.
* **Players to target** — Offense / Defense (IDP) / Both.  Groups come from the
  canonical position owner (``src.utils.name_clean.POSITION_ALIASES`` via
  ``normalize_position``) and the lineup owner's slot eligibility
  (``src.ros.lineup.slot_eligible_positions``: offense = SUPER_FLEX-eligible,
  defense = IDP_FLEX-eligible).  No private position table.  A missing or
  ambiguous position (an offense + IDP mix such as ``WR/DB``) is never treated
  as offense: it is excluded from both narrowed modes and counted.  Picks are
  their own asset category and are never classified as offense or defense.
* **Sort** — Most Impactful (default) / Largest Absolute Value Gain / Highest
  Percentage Edge / Highest-Ranked Incoming Player.  Most Impactful is a
  DECLARED PRIOR (``config/trade/discovery_impact_prior.json``,
  ``PRIOR_UNVALIDATED``) over existing canonical components; see that file's
  ``independence`` note for why no evidence is counted twice.

Absent filters mean the engine's legacy behaviour: every other consumer of the
engines (and any request without a ``discovery`` object) is unchanged.  This
module ORDERS and FILTERS candidates; it never changes a canonical value, the
package Value Adjustment or any engine's qualification rule.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.ros.lineup import slot_eligible_positions
from src.utils.name_clean import normalize_position

__all__ = [
    "DEFAULT_QUALITY",
    "DEFAULT_SCOPE",
    "DEFAULT_SORT",
    "DISCOVERY_VERSION",
    "QUALITY_LEVELS",
    "SCOPES",
    "SORTS",
    "CanonicalIndex",
    "DiscoveryFilters",
    "DiscoveryReport",
    "broader_quality_levels",
    "candidate_metrics",
    "defense_positions",
    "filter_incoming",
    "incoming_quality",
    "load_impact_prior",
    "offense_positions",
    "parse_discovery_filters",
    "player_group",
    "quality_anchor",
    "score_impact",
    "sort_key",
    "why_it_matters",
]

DISCOVERY_VERSION = "trade-discovery.2026-10-18.v1"
_PRIOR_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "trade" / "discovery_impact_prior.json"
)

#: Ordered narrowest → broadest; ``None`` is "All Players".
QUALITY_LEVELS: dict[str, int | None] = {
    "top100": 100,
    "top250": 250,
    "top500": 500,
    "all": None,
}
DEFAULT_QUALITY = "top250"
SCOPES = ("both", "offense", "defense")
DEFAULT_SCOPE = "both"
SORTS = ("most_impactful", "absolute_gain", "percentage_edge", "incoming_rank")
DEFAULT_SORT = "most_impactful"
#: Largest accepted minimum incoming value (the canonical scale's ceiling).
MAX_MIN_INCOMING_VALUE = 9999

GROUP_OFFENSE = "offense"
GROUP_DEFENSE = "defense"
GROUP_PICK = "pick"
GROUP_UNKNOWN = "unknown"

_MULTI_SEP = re.compile(r"[/,|\s]+")


def offense_positions() -> frozenset[str]:
    """Canonical position families that are offense: the SUPER_FLEX pool."""
    return frozenset(slot_eligible_positions("SUPER_FLEX"))


def defense_positions() -> frozenset[str]:
    """Canonical position families that are defense: the IDP_FLEX pool."""
    return frozenset(slot_eligible_positions("IDP_FLEX"))


def _family_group(token: str) -> str:
    fam = normalize_position(token)
    if not fam:
        return GROUP_UNKNOWN
    if fam == "PICK":
        return GROUP_PICK
    if fam in offense_positions():
        return GROUP_OFFENSE
    if fam in defense_positions():
        return GROUP_DEFENSE
    return GROUP_UNKNOWN


def player_group(position: Any) -> str:
    """``offense`` / ``defense`` / ``pick`` / ``unknown`` for a raw position.

    A multi-position string resolves only when every part agrees on ONE group
    (``DL/LB`` → defense).  An offense + defense mix (``WR/DB``) is ambiguous
    and answers ``unknown`` — never silently offense.
    """
    raw = str(position or "").strip().upper()
    if not raw:
        return GROUP_UNKNOWN
    parts = [p for p in _MULTI_SEP.split(raw) if p]
    if len(parts) <= 1:
        return _family_group(raw)
    groups = {_family_group(p) for p in parts}
    groups.discard(GROUP_UNKNOWN)
    return groups.pop() if len(groups) == 1 else GROUP_UNKNOWN


# ── Filters ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DiscoveryFilters:
    """One request's discovery settings.  ``sort=None`` keeps the engine's
    legacy order (callers that send no ``discovery`` object)."""

    quality: str = "all"
    min_incoming_value: int | None = None
    scope: str = DEFAULT_SCOPE
    sort: str | None = None

    @property
    def rank_limit(self) -> int | None:
        return QUALITY_LEVELS.get(self.quality)

    @property
    def quality_active(self) -> bool:
        return self.rank_limit is not None or bool(self.min_incoming_value)

    @property
    def scope_active(self) -> bool:
        return self.scope != "both"

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetQuality": self.quality,
            "rankLimit": self.rank_limit,
            "minIncomingValue": self.min_incoming_value,
            "playersToTarget": self.scope,
            "sort": self.sort,
            "qualityBasis": "canonical overall dynasty rank (canonicalConsensusRank)",
            "qualityAppliesTo": "incoming players — at least one must meet it; picks never do",
        }


def parse_discovery_filters(
    body: Mapping[str, Any] | None,
) -> tuple[DiscoveryFilters | None, dict[str, Any] | None]:
    """``(filters, None)`` / ``(None, None)`` when absent / ``(None, error)``.

    Wire shape: ``{"discovery": {"targetQuality": "top250", "minIncomingValue":
    3000, "playersToTarget": "offense", "sort": "most_impactful"}}``.  Every
    field is optional; a present object defaults to Top 250 / Both / Most
    Impactful (the page defaults).  An unknown value is an error, never a
    silent fallback.
    """
    raw = (body or {}).get("discovery")
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        return None, {"error": "invalid_discovery", "message": "'discovery' must be an object."}
    quality = raw.get("targetQuality", DEFAULT_QUALITY)
    if quality not in QUALITY_LEVELS:
        return None, {
            "error": "invalid_discovery",
            "field": "targetQuality",
            "allowed": list(QUALITY_LEVELS),
        }
    scope = raw.get("playersToTarget", DEFAULT_SCOPE)
    if scope not in SCOPES:
        return None, {
            "error": "invalid_discovery",
            "field": "playersToTarget",
            "allowed": list(SCOPES),
        }
    sort = raw.get("sort", DEFAULT_SORT)
    if sort not in SORTS:
        return None, {"error": "invalid_discovery", "field": "sort", "allowed": list(SORTS)}
    min_value = raw.get("minIncomingValue")
    if min_value in (None, "", 0):
        min_value = None
    else:
        try:
            min_value = int(min_value)
        except (TypeError, ValueError):
            return None, {"error": "invalid_discovery", "field": "minIncomingValue"}
        if (
            isinstance(raw.get("minIncomingValue"), bool)
            or not 1 <= min_value <= MAX_MIN_INCOMING_VALUE
        ):
            return None, {
                "error": "invalid_discovery",
                "field": "minIncomingValue",
                "range": [1, MAX_MIN_INCOMING_VALUE],
            }
    return DiscoveryFilters(
        quality=quality, min_incoming_value=min_value, scope=scope, sort=sort
    ), None


def broader_quality_levels(quality: str) -> list[str]:
    """The levels broader than ``quality``, narrowest first (for one-click
    expansion from an empty result)."""
    order = list(QUALITY_LEVELS)
    if quality not in order:
        return []
    return order[order.index(quality) + 1 :]


# ── Canonical rows ─────────────────────────────────────────────────────


class CanonicalIndex:
    """Canonical rows keyed exactly as ``finder.board_values_from_contract``
    keys them (``legacyRef`` / ``canonicalName`` / ``displayName``), so an
    asset that resolved a board value resolves its rank from the same row."""

    def __init__(self, contract: Mapping[str, Any] | None):
        self._by: dict[str, Mapping[str, Any]] = {}
        self._ci: dict[str, Mapping[str, Any]] = {}
        for row in (contract or {}).get("playersArray") or []:
            if not isinstance(row, Mapping):
                continue
            for key in ("legacyRef", "canonicalName", "displayName"):
                name = row.get(key)
                if isinstance(name, str) and name:
                    self._by.setdefault(name, row)
                    self._ci.setdefault(name.strip().casefold(), row)

    def row(self, name: Any) -> Mapping[str, Any] | None:
        key = str(name or "")
        return self._by.get(key) or self._ci.get(key.strip().casefold())

    def rank(self, asset: Any) -> int | None:
        row = self.row(getattr(asset, "name", asset))
        value = (row or {}).get("canonicalConsensusRank")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 1:
            return None
        return int(value)

    def confidence(self, asset: Any) -> str | None:
        row = self.row(getattr(asset, "name", asset))
        bucket = (row or {}).get("confidenceBucket")
        return str(bucket) if bucket else None


def _is_pick(asset: Any) -> bool:
    return bool(getattr(asset, "is_pick", False))


def incoming_quality(
    asset: Any, filters: DiscoveryFilters, index: CanonicalIndex
) -> tuple[bool, str | None]:
    """Whether ``asset`` can be the qualifying incoming player, and if not why."""
    if _is_pick(asset):
        return False, "pick"
    if filters.min_incoming_value and int(asset.model_value) < int(filters.min_incoming_value):
        return False, "below_min_value"
    limit = filters.rank_limit
    if limit is None:
        return True, None
    rank = index.rank(asset)
    if rank is None:
        return False, "unranked"
    if rank > limit:
        return False, "outside_rank"
    return True, None


def quality_anchor(
    filters: DiscoveryFilters | None, index: CanonicalIndex
) -> Callable[[Any], bool] | None:
    """The receive-side anchor predicate, or ``None`` when quality is off."""
    if filters is None or not filters.quality_active:
        return None
    return lambda asset: incoming_quality(asset, filters, index)[0]


@dataclass
class DiscoveryReport:
    """Why a discovery list is short — counts, never a silent shrink."""

    excluded_by_scope: int = 0
    unknown_position: int = 0
    unknown_position_names: list[str] = field(default_factory=list)
    targets_considered: int = 0
    targets_meeting_quality: int = 0
    anchor_rejected: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "excludedByPlayersToTarget": self.excluded_by_scope,
            "unknownPosition": self.unknown_position,
            "unknownPositionNames": sorted(set(self.unknown_position_names))[:10],
            "incomingPlayersConsidered": self.targets_considered,
            "incomingPlayersMeetingQuality": self.targets_meeting_quality,
            "packagesWithoutQualifyingPlayer": self.anchor_rejected,
        }


def filter_incoming(
    assets: Iterable[Any],
    filters: DiscoveryFilters | None,
    index: CanonicalIndex,
    report: DiscoveryReport | None = None,
) -> list[Any]:
    """The incoming pool narrowed by Players to target, BEFORE enumeration.

    Every incoming PLAYER must be in scope; picks pass (their own controls
    decide them).  An unknown/ambiguous position is excluded from a narrowed
    mode and counted in every mode.  Quality is NOT a pool filter here — a
    qualifying player may bring a lesser second piece — it is the anchor.
    """
    kept: list[Any] = []
    for a in assets:
        if _is_pick(a):
            kept.append(a)
            continue
        group = player_group(getattr(a, "position", ""))
        if group == GROUP_UNKNOWN and report is not None:
            report.unknown_position += 1
            report.unknown_position_names.append(str(getattr(a, "name", "")))
        if filters is not None and filters.scope_active and group != filters.scope:
            if report is not None and group != GROUP_UNKNOWN:
                report.excluded_by_scope += 1
            continue
        if report is not None and filters is not None:
            report.targets_considered += 1
            if incoming_quality(a, filters, index)[0]:
                report.targets_meeting_quality += 1
        kept.append(a)
    return kept


# ── Most Impactful ─────────────────────────────────────────────────────


def load_impact_prior(path: Path | None = None) -> dict[str, Any]:
    """The declared Most Impactful prior.  Never tuned in code."""
    return json.loads((path or _PRIOR_PATH).read_text(encoding="utf-8"))


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _best_incoming(receive: Sequence[Any], index: CanonicalIndex) -> Any | None:
    players = [a for a in receive if not _is_pick(a)]
    if not players:
        return None
    return min(
        players,
        key=lambda a: (-int(a.model_value), _rank_or_last(index.rank(a)), str(a.name)),
    )


def lineup_fit(lineup: Mapping[str, Any] | None, prior: Mapping[str, Any]) -> float | None:
    """The canonical lineup solver's delta as a [-1, 1] factor (Best Offers'
    own normalization), or ``None`` when unavailable."""
    if not lineup or not lineup.get("available") or not lineup.get("ourBefore"):
        return None
    if lineup.get("ourDelta") is None:
        return None  # an unreadable delta is unknown, never a zero change
    scale = float((prior.get("scales") or {}).get("lineupDeltaScale", 10.0))
    base = max(float(lineup["ourBefore"]), 1.0)
    return round(_clip(float(lineup["ourDelta"]) / base * scale, -1.0, 1.0), 4)


def need_fit(receive: Sequence[Any], needs: set[str] | None) -> float | None:
    """Share of incoming players at a rated Team Weakness need, or ``None``."""
    if needs is None:
        return None
    players = [a for a in receive if not _is_pick(a)]
    if not players:
        return 0.0
    return round(sum(1 for a in players if a.position in needs) / len(players), 4)


def candidate_metrics(
    give: Sequence[Any],
    receive: Sequence[Any],
    *,
    index: CanonicalIndex,
    prior: Mapping[str, Any],
    filters: DiscoveryFilters | None = None,
    roster_fit: float | None = None,
    roster_fit_basis: str | None = None,
    counterparty: float | None = None,
    counterparty_basis: str | None = None,
    forced_drop: float | None = None,
    lineup: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Every number the discovery orderings read, for one candidate.

    The gain is the calculator's canonical equity verdict
    (``analyze_trade.equity_verdict``: ``rankDerivedValue`` + the ACTIVE
    package Value Adjustment) — consumed, never re-derived.
    """
    from src.trade.analyze_trade import equity_verdict  # noqa: PLC0415

    scales = prior.get("scales") or {}
    verdict = equity_verdict(
        [float(a.model_value) for a in give], [float(a.model_value) for a in receive]
    )
    gain = int(verdict["vaAdjustedGap"])
    base = max(float(verdict["sendingAdjusted"]), 1.0)
    pct = 100.0 * gain / base
    best = _best_incoming(receive, index)
    importance = (
        round(_clip(float(best.model_value) / float(scales.get("valueScaleMax", 9999))), 4)
        if best is not None
        else None
    )
    if gain > 0:
        abs_part = _clip(gain / float(scales.get("gainSaturation", 1500)))
        pct_part = _clip(pct / float(scales.get("gainPctSaturation", 25.0)))
        edge = round(math.sqrt(abs_part * pct_part), 4)
    else:
        edge = 0.0
    bucket = index.confidence(best) if best is not None else None
    multipliers = prior.get("evidenceMultipliers") or {}
    evidence = float(multipliers.get(bucket or "none", multipliers.get("none", 0.7)))
    best_rank = index.rank(best) if best is not None else None
    meets = (
        any(incoming_quality(a, filters, index)[0] for a in receive)
        if filters is not None and filters.quality_active
        else None
    )
    return {
        "gain": gain,
        "rawGain": int(verdict["rawGap"]),
        "gainPct": round(pct, 2),
        "verdict": verdict["magnitude"],
        "sendingAdjusted": verdict["sendingAdjusted"],
        "receivingAdjusted": verdict["receivingAdjusted"],
        "bestIncoming": (
            {
                "name": best.name,
                "position": best.position,
                "rank": best_rank,
                "value": int(best.model_value),
                "confidence": bucket,
            }
            if best is not None
            else None
        ),
        "otherIncoming": [a.name for a in receive if a is not best],
        "meetsTargetQuality": meets,
        "factors": {
            "incomingImportance": importance,
            "edge": edge,
            "rosterFit": roster_fit,
            "counterpartyPlausibility": (
                round(_clip(counterparty), 4) if counterparty is not None else None
            ),
            "forcedDropCost": round(_clip(forced_drop), 4) if forced_drop is not None else None,
        },
        "factorBasis": {
            "rosterFit": roster_fit_basis,
            "counterpartyPlausibility": counterparty_basis,
        },
        "evidenceMultiplier": evidence,
        "lineupImpact": dict(lineup) if lineup else None,
        "impact": None,
        "imputations": {},
    }


_BENEFITS = ("incomingImportance", "edge", "rosterFit", "counterpartyPlausibility")
_COSTS = ("forcedDropCost",)


def score_impact(metrics: Sequence[dict[str, Any]], prior: Mapping[str, Any]) -> None:
    """Stamp ``impact`` on every metrics dict of ONE ranked set, in place.

    ``evidenceMultiplier × Σ wᵢ·benefitᵢ − Σ wⱼ·costⱼ``.  Unknown benefits are
    imputed as ``min(worst known, 0)`` and unknown costs as the worst known
    cost, across the SAME set — an unreadable factor is never free.
    """
    weights = prior.get("weights") or {}
    stand_ins: dict[str, float] = {}
    for name in (*_BENEFITS, *_COSTS):
        known = [m["factors"][name] for m in metrics if m["factors"].get(name) is not None]
        if not known:
            continue
        stand_ins[name] = max(known) if name in _COSTS else min(min(known), 0.0)
    for m in metrics:
        imputed: dict[str, float] = {}
        benefit = 0.0
        for name in _BENEFITS:
            f = m["factors"].get(name)
            if f is None and name in stand_ins:
                f = imputed[name] = stand_ins[name]
            if f is not None:
                benefit += float(weights.get(name, 0.0)) * float(f)
        cost = 0.0
        for name in _COSTS:
            f = m["factors"].get(name)
            if f is None and name in stand_ins:
                f = imputed[name] = stand_ins[name]
            if f is not None:
                cost += float(weights.get(name, 0.0)) * float(f)
        m["imputations"] = imputed
        m["impact"] = round(float(m["evidenceMultiplier"]) * benefit - cost, 6)


def sort_key(sort: str | None, metrics: Mapping[str, Any], tiebreak: Any = "") -> tuple:
    """Deterministic order for one of the four sorts (best first).

    A missing number sorts LAST — it is never read as a zero.
    """
    impact = _desc(metrics.get("impact"))
    gain = _desc(metrics.get("gain"))
    pct = _desc(metrics.get("gainPct"))
    best = metrics.get("bestIncoming") or {}
    rank = _rank_or_last(best.get("rank"))
    if sort == "absolute_gain":
        return (gain, impact, rank, tiebreak)
    if sort == "percentage_edge":
        return (pct, impact, rank, tiebreak)
    if sort == "incoming_rank":
        return (rank, impact, gain, tiebreak)
    return (impact, gain, rank, tiebreak)


def _desc(value: Any) -> float:
    """Sort key for 'larger first'; an absent value sorts after every number."""
    return -float(value) if isinstance(value, (int, float)) else math.inf


def _rank_or_last(rank: Any) -> float:
    return float(rank) if isinstance(rank, (int, float)) else math.inf


def anchor_rejections(enum_report: Mapping[str, Any] | None) -> int:
    """Packages the Target Quality anchor refused, summed over a finder
    enumeration report's shape groups (absent counts contribute nothing)."""
    total = 0
    for group in (enum_report or {}).values():
        if isinstance(group, Mapping):
            n = group.get("receiveAnchorRejected")
            if isinstance(n, int):
                total += n
    return total


def why_it_matters(metrics: Mapping[str, Any], *, need_positions: Iterable[str] = ()) -> str:
    """One concise sentence from the published numbers only."""
    best = metrics.get("bestIncoming") or {}
    parts: list[str] = []
    if best:
        rank = f"#{best['rank']} overall" if best.get("rank") else "unranked overall"
        parts.append(f"Brings back {best['name']} ({rank}, {int(best['value']):,})")
    gain = int(metrics["gain"])
    verb = "for" if gain >= 0 else "at a cost of"
    parts.append(
        f"{verb} {'+' if gain >= 0 else ''}{gain:,} canonical value after the Value Adjustment "
        f"({float(metrics['gainPct']):+.1f}%)"
    )
    sentence = " ".join(parts) + "."
    lineup = metrics.get("lineupImpact") or {}
    if lineup.get("available") and lineup.get("ourDelta") is not None:
        d = float(lineup["ourDelta"])
        sentence += f" Starting lineup {'+' if d >= 0 else ''}{d:.1f} rest-of-season points."
    filled = sorted({p for p in need_positions if best and best.get("position") == p})
    if filled:
        sentence += f" Fills a rated need at {', '.join(filled)}."
    return sentence
