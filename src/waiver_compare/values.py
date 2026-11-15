"""The waiver-compare value: a plain average of two published values.

Owner request 2026-10-21 (unlisted Waiver Wire Comparison page):

* **KTC** — KeepTradeCut dynasty, Crowd+Trades value source, Superflex,
  TE++ (``ktcCrowdTradesSfTep``; settings owned by
  ``src/sources/ktc_value_sources.py``, value read through
  ``src/sources/ktc_market.market_raw_value``).
* **IDPTC** — IDP Trade Calculator, Superflex ON, TE Premium ON, offense and
  IDP on one board (``idpTradeCalc``; settings driven by
  ``Dynasty Scraper.py::scrape_idptradecalc``).

``combined = (ktc + idptc) / 2`` when both exist, the one value unchanged
when only one exists, ``None`` when neither does.  **Missing is never
zero**: a missing side is never averaged in as 0.

Values are the RAW published numbers the contract carries in
``canonicalSiteValues`` for these two keys (both are value-signal sources on
their native 0-9999 scale; no Hill curve, TE conversion, weighting or
league adjustment is applied to them).  Identity comes from the contract's
identity owner (``playerId`` = Sleeper id), so two players who share a name
are never merged.  Nothing here writes to the contract.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.sources.ktc_market import KTC_MARKET_KEY, market_raw_value

IDPTC_KEY = "idpTradeCalc"

#: Both sources publish on a native 0-9999 scale.  Anything above it is a
#: scrape glitch, not a price, and is treated as missing.
SOURCE_SCALE_MAX = 9999.0

SOURCE_SETTINGS = {
    "ktc": {
        "sourceKey": KTC_MARKET_KEY,
        "label": "KeepTradeCut",
        "settings": "Dynasty · Crowd+Trades · Superflex · TE++",
        "url": "https://keeptradecut.com/dynasty-rankings",
    },
    "idptc": {
        "sourceKey": IDPTC_KEY,
        "label": "IDP Trade Calculator",
        "settings": "Superflex · TE Premium · offense + IDP",
        "url": "https://idptradecalculator.com/",
    },
}


@dataclass(frozen=True)
class PlayerValue:
    player_id: str
    name: str
    position: str
    team: str | None
    age: float | None
    ktc: float | None
    idptc: float | None

    @property
    def combined(self) -> float | None:
        return combine(self.ktc, self.idptc)


def _published(value: Any) -> float | None:
    """A usable published value, or None.  Never coerces missing to 0."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0 or out > SOURCE_SCALE_MAX:
        return None
    return out


def combine(ktc: float | None, idptc: float | None) -> float | None:
    """Exactly 50/50 when both exist; the lone value when one does."""
    if ktc is not None and idptc is not None:
        return (ktc + idptc) / 2.0
    if ktc is not None:
        return ktc
    if idptc is not None:
        return idptc
    return None


def source_values(row: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """``(ktc, idptc)`` raw published values for one contract row."""
    sites = row.get("canonicalSiteValues")
    if not isinstance(sites, Mapping):
        return None, None
    return market_raw_value(sites), _published(sites.get(IDPTC_KEY))


def _age(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) and out > 0 else None


@dataclass
class ValueIndex:
    by_player_id: dict[str, PlayerValue]
    #: Valued rows the identity owner could not tie to a Sleeper id.  They
    #: cannot be matched to any roster, so they are excluded and counted.
    unidentified_rows: int
    #: Sleeper ids carried by more than one valued row with DIFFERENT values
    #: — a possible identity collision.  Withheld rather than guessed.
    conflicting_ids: list[str]


def build_value_index(players_array: Iterable[Mapping[str, Any]]) -> ValueIndex:
    """Index every non-pick contract row that carries either source value."""
    found: dict[str, list[PlayerValue]] = {}
    unidentified = 0
    for row in players_array or ():
        if not isinstance(row, Mapping):
            continue
        if str(row.get("assetClass") or "").lower() == "pick":
            continue
        ktc, idptc = source_values(row)
        if ktc is None and idptc is None:
            continue
        pid = str(row.get("playerId") or "").strip()
        if not pid:
            unidentified += 1
            continue
        found.setdefault(pid, []).append(
            PlayerValue(
                player_id=pid,
                name=str(row.get("displayName") or row.get("canonicalName") or ""),
                position=str(row.get("position") or "").upper(),
                team=(str(row["team"]) if row.get("team") else None),
                age=_age(row.get("age")),
                ktc=ktc,
                idptc=idptc,
            )
        )
    index: dict[str, PlayerValue] = {}
    conflicts: list[str] = []
    for pid, rows in found.items():
        distinct = {(r.ktc, r.idptc) for r in rows}
        if len(distinct) > 1:
            conflicts.append(pid)
            continue
        index[pid] = rows[0]
    return ValueIndex(
        by_player_id=index, unidentified_rows=unidentified, conflicting_ids=sorted(conflicts)
    )
