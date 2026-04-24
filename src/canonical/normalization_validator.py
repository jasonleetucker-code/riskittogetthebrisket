"""Normalization validator + structured mismatch logger.

Runs over a contract payload to prove three invariants:

    1. Every player's `displayName` == `canonicalName` (no drift
       between the two fields consumers assume are equivalent).
    2. Every pick name matches our canonical ``YYYY (Early|Mid|Late)
       (1st|2nd|3rd|4th|5th|6th)`` or ``YYYY Pick R.SS`` shape.
    3. Every `assetClass` is one of {offense, idp, pick} and agrees
       with the position-to-class classifier.

Writes mismatches to a structured log line per row with enough
context to debug.  Return value is a summary dict:

    {"total": N, "playerNameDrift": int, "pickNameMalformed": int,
     "assetClassMismatch": int, "dupKeys": int, "samples": [...]}

Consumers:

* Called at contract-build time in ``data_contract.py`` after
  materialization — any invariant violation is surfaced via
  ``/api/status.normalizationValidator``.
* Called by the KTC import regression tests so we catch pick-
  mapping failures at test-time, not in prod.
* Available as ``/api/admin/normalization/check`` for on-demand
  validation of the live contract.

No silent failures — every mismatch logs a warning via the root
logger with a structured prefix ``normalization_mismatch=…``.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

_LOGGER = logging.getLogger(__name__)

# Two canonical pick shapes — both accepted.
_PICK_NAME_PATTERNS = [
    # "2027 Early 1st", "2026 Mid 4th", "2027 Late 3rd"
    re.compile(r"^20\d{2}\s+(Early|Mid|Late)\s+(1st|2nd|3rd|4th|5th|6th)$"),
    # "2026 Pick 1.01", "2027 Pick 2.12"
    re.compile(r"^20\d{2}\s+Pick\s+[1-6]\.\d{2}$"),
    # Legacy "2026 1st Round", "2027 2nd Round"
    re.compile(r"^20\d{2}\s+(1st|2nd|3rd|4th|5th|6th)\s+Round$"),
]

_VALID_ASSET_CLASSES = frozenset({"offense", "idp", "pick"})

# Position → class classifier mirrors frontend `classifyPos`.
_OFFENSE_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
_IDP_POSITIONS = frozenset({"DL", "LB", "DB", "CB", "S", "DE", "DT", "OLB", "ILB", "FS", "SS"})


@dataclass
class ValidationResult:
    total: int = 0
    player_name_drift: int = 0
    pick_name_malformed: int = 0
    asset_class_mismatch: int = 0
    dup_keys: int = 0
    samples: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "playerNameDrift": self.player_name_drift,
            "pickNameMalformed": self.pick_name_malformed,
            "assetClassMismatch": self.asset_class_mismatch,
            "dupKeys": self.dup_keys,
            "samples": list(self.samples[:20]),
            "healthy": (
                self.player_name_drift == 0
                and self.pick_name_malformed == 0
                and self.asset_class_mismatch == 0
                and self.dup_keys == 0
            ),
        }


def _classify_position(position: str) -> str:
    p = str(position or "").strip().upper()
    if p == "PICK":
        return "pick"
    if p in _OFFENSE_POSITIONS:
        return "offense"
    if p in _IDP_POSITIONS:
        return "idp"
    return "other"


def _log_mismatch(
    category: str, detail: str, row_snippet: dict[str, Any],
) -> None:
    """Emit a structured single-line warning.  Prefix makes grep
    triage fast:  ``grep normalization_mismatch= dynasty.log``."""
    _LOGGER.warning(
        "normalization_mismatch=%s detail=%r row=%s",
        category, detail,
        {k: row_snippet.get(k) for k in (
            "displayName", "canonicalName", "position", "assetClass", "playerId",
        )},
    )


def is_valid_pick_name(name: str) -> bool:
    if not isinstance(name, str) or not name.strip():
        return False
    return any(p.match(name.strip()) for p in _PICK_NAME_PATTERNS)


def validate_players_array(
    players_array: Iterable[dict[str, Any]] | None,
) -> ValidationResult:
    """Walk every player row and emit a mismatch log for each
    broken invariant.  Returns a summary for observability."""
    result = ValidationResult()
    if not players_array:
        return result

    seen_keys: dict[str, int] = {}
    for row in players_array:
        if not isinstance(row, dict):
            continue
        result.total += 1

        # 1. displayName / canonicalName drift.
        dn = row.get("displayName")
        cn = row.get("canonicalName")
        if dn is not None and cn is not None and dn != cn:
            result.player_name_drift += 1
            if len(result.samples) < 20:
                result.samples.append({
                    "category": "player_name_drift",
                    "displayName": dn, "canonicalName": cn,
                })
            _log_mismatch("player_name_drift", f"{dn!r} != {cn!r}", row)

        # 2. Pick-name shape.
        asset_class = str(row.get("assetClass") or "")
        if asset_class == "pick":
            if not is_valid_pick_name(dn or cn or ""):
                result.pick_name_malformed += 1
                if len(result.samples) < 20:
                    result.samples.append({
                        "category": "pick_name_malformed",
                        "name": dn or cn,
                    })
                _log_mismatch("pick_name_malformed", str(dn or cn), row)

        # 3. assetClass / position agreement.
        if asset_class:
            if asset_class not in _VALID_ASSET_CLASSES:
                result.asset_class_mismatch += 1
                if len(result.samples) < 20:
                    result.samples.append({
                        "category": "asset_class_unknown",
                        "assetClass": asset_class,
                        "name": dn or cn,
                    })
                _log_mismatch("asset_class_unknown", asset_class, row)
            else:
                expected = _classify_position(row.get("position") or "")
                if expected != "other" and expected != asset_class:
                    result.asset_class_mismatch += 1
                    if len(result.samples) < 20:
                        result.samples.append({
                            "category": "asset_class_mismatch",
                            "position": row.get("position"),
                            "expected": expected,
                            "got": asset_class,
                            "name": dn or cn,
                        })
                    _log_mismatch(
                        "asset_class_mismatch",
                        f"pos={row.get('position')} exp={expected} got={asset_class}",
                        row,
                    )

        # 4. Dup-key detection (displayName → rowCount).
        name_key = dn or cn
        if isinstance(name_key, str) and name_key:
            seen_keys[name_key] = seen_keys.get(name_key, 0) + 1

    for name_key, count in seen_keys.items():
        if count > 1:
            result.dup_keys += 1
            if len(result.samples) < 20:
                result.samples.append({
                    "category": "dup_key",
                    "name": name_key, "count": count,
                })
            _LOGGER.warning(
                "normalization_mismatch=dup_key detail=%r count=%d",
                name_key, count,
            )

    return result


def validate_legacy_players_dict(
    players: dict[str, Any] | None,
) -> ValidationResult:
    """Same invariants for the legacy ``players`` dict shape.

    Dict keys ARE the canonical name, so we check that every entry's
    inner ``_canonicalName`` field (when present) matches its key.
    """
    result = ValidationResult()
    if not players:
        return result
    for key, row in players.items():
        if not isinstance(row, dict):
            continue
        result.total += 1
        inner = row.get("_canonicalName") or row.get("displayName")
        if inner and inner != key:
            result.player_name_drift += 1
            if len(result.samples) < 20:
                result.samples.append({
                    "category": "player_name_drift",
                    "key": key, "inner": inner,
                })
            _log_mismatch("player_name_drift", f"{key!r} != {inner!r}", {"key": key, **row})
    return result


def validate_contract(contract: dict[str, Any] | None) -> dict[str, Any]:
    """Top-level entry: run both array + dict validations and
    return a combined dict with ``playersArray`` and ``playersDict``
    sub-summaries.  Safe on empty / malformed contracts."""
    contract = contract or {}
    arr_summary = validate_players_array(contract.get("playersArray"))
    dict_summary = validate_legacy_players_dict(contract.get("players"))
    healthy = arr_summary.to_dict()["healthy"] and dict_summary.to_dict()["healthy"]
    return {
        "healthy": healthy,
        "playersArray": arr_summary.to_dict(),
        "playersDict": dict_summary.to_dict(),
    }
