"""KeepTradeCut value-source capture — one semantic owner.

KTC added three dynasty value-source modes on 2026-09-08: Crowdsourced,
Tradesourced, and Crowd+Trades. The controls change values throughout KTC.
This module owns source selection and preservation, not blend weighting.

The browser page is public. We drive the visible Value Source control instead
of guessing private query parameters or recreating KTC's proprietary blend.
If the control or selected value-board shape changes, capture fails closed.

For this league the selected board is read in Superflex + TE++ (level 2).
Base Superflex is retained beside TE++ so the historical Crowd base-to-TE++
calibration can remain a paired Crowd-only measurement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

KTC_CROWD = "crowd"
KTC_TRADES = "trades"
KTC_CROWD_TRADES = "crowd_trades"

KTC_VALUE_SOURCES: tuple[str, ...] = (KTC_CROWD, KTC_TRADES, KTC_CROWD_TRADES)
KTC_CANONICAL_MARKET_SOURCE = KTC_CROWD_TRADES

KTC_VALUE_SOURCE_LABELS: Mapping[str, str] = {
    KTC_CROWD: "Crowdsourced",
    KTC_TRADES: "Tradesourced",
    KTC_CROWD_TRADES: "Crowd+Trades",
}

# Live 2026-09-08 public control encoding, independently verified from all
# synchronized Value Source selects and updateArrayValues/updateSingleDynastyAsset.
KTC_CONTROL_VALUES: Mapping[str, str] = {
    KTC_CROWD: "1",
    KTC_CROWD_TRADES: "2",
    KTC_TRADES: "3",
}

KTC_TEPP_FIELD = "tepp"
KTC_TEPP_LEVEL = 2


class KtcValueSourceError(RuntimeError):
    """KTC's visible control or selected-board shape changed."""


@dataclass(frozen=True)
class KtcValueDivergence:
    """Crowd versus real-trade market disagreement for one asset."""

    name: str
    player_id: int | None
    crowd_value: float | None
    trades_value: float | None
    delta: float | None
    percent_delta: float | None
    direction: str | None


@dataclass(frozen=True)
class KtcValueObservation:
    """One source-native KTC asset observation."""

    name: str
    player_id: int | None
    position: str | None
    base_value: float | None
    base_rank: float | None
    tepp_value: float | None
    tepp_rank: float | None


@dataclass(frozen=True)
class KtcValueSourceCapture:
    """One selected KTC value source plus provenance."""

    value_source: str
    selected_label: str
    selected_value: str
    page_url: str
    captured_at: str
    superflex: bool
    te_premium: str
    te_premium_level: int
    row_count: int
    priced_count: int
    content_hash: str
    rows: tuple[KtcValueObservation, ...]

    def provenance_dict(self) -> dict[str, Any]:
        return {
            "provider": "KeepTradeCut",
            "valueSource": self.value_source,
            "selectedLabel": self.selected_label,
            "selectedControlValue": self.selected_value,
            "pageUrl": self.page_url,
            "capturedAt": self.captured_at,
            "gameType": "DYNASTY",
            "superflex": self.superflex,
            "tePremium": self.te_premium,
            "tePremiumLevel": self.te_premium_level,
            "rowCount": self.row_count,
            "pricedCount": self.priced_count,
            "contentHash": self.content_hash,
            "signalType": "native_value",
        }


def _num(value: Any) -> float | None:
    """Positive finite-looking number; missing/zero stays missing."""
    if isinstance(value, Mapping):
        value = value.get("value")
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out <= 0 or out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _rank(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("rank")
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def observations_from_players_array(
    rows: Sequence[Mapping[str, Any]],
    value_source: str = KTC_CROWD,
) -> tuple[KtcValueObservation, ...]:
    """Parse one KTC source mode from the shared ``playersArray`` payload.

    Live 2026-09-08 evidence shows KTC ships all three source-native fields in
    the same player object: ``value/rank`` = Crowdsourced,
    ``blendValue/blendRank`` = Crowd+Trades, and
    ``vftValue/vftRank`` = Tradesourced.  The visible Value Source selector
    chooses source code 1/2/3; we preserve the explicit fields rather than
    depending on whatever mode happened to be selected when the page loaded.
    Missing Tradesourced values remain None, never zero.
    """
    field_pairs = {
        KTC_CROWD: ("value", "rank"),
        KTC_CROWD_TRADES: ("blendValue", "blendRank"),
        KTC_TRADES: ("vftValue", "vftRank"),
    }
    if value_source not in field_pairs:
        raise KtcValueSourceError(f"unknown KTC value source: {value_source!r}")
    value_field, rank_field = field_pairs[value_source]
    out: list[KtcValueObservation] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("playerName") or row.get("name") or "").strip()
        if not name:
            continue

        sf = row.get("superflexValues")
        if not isinstance(sf, Mapping):
            sf = {}
        tepp = sf.get(KTC_TEPP_FIELD)
        if tepp is None:
            tepp = row.get(KTC_TEPP_FIELD)

        raw_id = row.get("playerID")
        try:
            player_id = int(raw_id) if raw_id not in (None, "") else None
        except (TypeError, ValueError):
            player_id = None

        out.append(
            KtcValueObservation(
                name=name,
                player_id=player_id,
                position=(str(row.get("position")).strip() or None)
                if row.get("position") is not None
                else None,
                base_value=_num(sf.get(value_field)),
                base_rank=_rank(sf.get(rank_field)),
                tepp_value=_num(tepp.get(value_field) if isinstance(tepp, Mapping) else tepp),
                tepp_rank=_rank(tepp.get(rank_field) if isinstance(tepp, Mapping) else tepp),
            )
        )
    return tuple(out)


def _label_token(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def classify_control_label(text: str) -> str | None:
    """Map KTC visible option text to the stable source vocabulary.

    KTC currently uses compact page labels and longer nav labels ending in
    Value/Values. Normalize that optional suffix before classification.
    """
    token = _label_token(text)
    for suffix in ("values", "value"):
        if token.endswith(suffix):
            token = token[: -len(suffix)]
            break
    if token == "crowdsourced":
        return KTC_CROWD
    if token == "tradesourced":
        return KTC_TRADES
    if token in {"crowdtrades", "crowdtrade", "crowdsourcedtradesourced"}:
        return KTC_CROWD_TRADES
    return None


def _content_hash(rows: Sequence[KtcValueObservation]) -> str:
    canonical = [
        {
            "id": row.player_id,
            "name": row.name,
            "position": row.position,
            "baseValue": row.base_value,
            "baseRank": row.base_rank,
            "teppValue": row.tepp_value,
            "teppRank": row.tepp_rank,
        }
        for row in sorted(rows, key=lambda r: (r.player_id or 0, r.name.casefold()))
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


async def _value_source_controls(page: Any) -> list[dict[str, Any]]:
    controls = await page.evaluate(
        """() => Array.from(document.querySelectorAll('select')).map((select, index) => ({
          index,
          value: String(select.value ?? ''),
          options: Array.from(select.options).map((option, optionIndex) => ({
            optionIndex,
            text: String(option.textContent ?? '').trim(),
            value: String(option.value ?? '')
          }))
        }))"""
    )
    return controls if isinstance(controls, list) else []


async def value_source_options(page: Any) -> dict[str, dict[str, str]]:
    """Prove KTC exposes all three source modes and return their controls.

    The page currently contains several synchronized selects; some are hidden
    by the SumoSelect UI wrapper. We only need their first-party option
    labels/values because every source field is delivered in the same
    playersArray payload. Acquisition therefore does not depend on clicking a
    hidden control.
    """
    controls = await _value_source_controls(page)
    for control in controls:
        options = control.get("options") or []
        mapped: dict[str, dict[str, str]] = {}
        for option in options:
            source = classify_control_label(option.get("text", ""))
            if source:
                mapped[source] = {
                    "label": str(option.get("text") or "").strip(),
                    "value": str(option.get("value") or "").strip(),
                }
        if set(KTC_VALUE_SOURCES).issubset(mapped):
            return mapped
    seen = [
        [str(option.get("text") or "") for option in (control.get("options") or [])]
        for control in controls
    ]
    raise KtcValueSourceError(
        "KTC three-mode Value Source control not found; "
        f"expected Crowdsourced/Tradesourced/Crowd+Trades, saw {seen!r}"
    )


async def select_value_source(page: Any, source: str) -> dict[str, str]:
    """Select one of KTC's three visible Value Source modes."""
    if source not in KTC_VALUE_SOURCES:
        raise KtcValueSourceError(f"unknown KTC value source: {source!r}")

    controls = await _value_source_controls(page)
    for control in controls:
        options = control.get("options") or []
        mapped = {
            classify_control_label(option.get("text", "")): option
            for option in options
            if classify_control_label(option.get("text", ""))
        }
        if set(KTC_VALUE_SOURCES).issubset(mapped):
            option = mapped[source]
            locator = page.locator("select").nth(int(control["index"]))
            await locator.select_option(index=int(option["optionIndex"]))
            await page.wait_for_timeout(1200)
            selected = await locator.locator("option:checked").text_content()
            selected_label = str(selected or "").strip()
            if classify_control_label(selected_label) != source:
                raise KtcValueSourceError(
                    f"KTC Value Source control did not select {source}: {selected_label!r}"
                )
            return {"label": selected_label, "value": str(await locator.input_value())}

    seen = [
        [str(option.get("text") or "") for option in (control.get("options") or [])]
        for control in controls
    ]
    raise KtcValueSourceError(
        "KTC three-mode Value Source control not found; "
        f"expected Crowdsourced/Tradesourced/Crowd+Trades, saw {seen!r}"
    )


async def selected_players_array(page: Any) -> list[dict[str, Any]]:
    """Read the current selected-source value board from the public page."""
    rows = await page.evaluate(
        """() => {
          if (typeof playersArray !== 'undefined' && Array.isArray(playersArray)) {
            return playersArray;
          }
          if (Array.isArray(window.playersArray)) return window.playersArray;
          return [];
        }"""
    )
    if not isinstance(rows, list) or len(rows) < 100:
        size = len(rows) if isinstance(rows, list) else "non-list"
        raise KtcValueSourceError(f"KTC selected value board missing/partial: rows={size}")
    return rows


async def capture_value_source(page: Any, source: str) -> KtcValueSourceCapture:
    """Capture one explicit KTC source field from the shared public payload."""
    controls = await value_source_options(page)
    if source not in controls:
        raise KtcValueSourceError(f"KTC control missing source {source!r}")
    raw_rows = await selected_players_array(page)
    rows = observations_from_players_array(raw_rows, source)
    priced = sum(1 for row in rows if row.tepp_value is not None)
    floor = int(KTC_SOURCE_MIN_PRICED.get(source, 100))
    if len(rows) < 100 or priced < floor:
        raise KtcValueSourceError(
            f"KTC {source} board is partial: rows={len(rows)}, priced={priced}, floor={floor}"
        )
    control = controls[source]
    return KtcValueSourceCapture(
        value_source=source,
        selected_label=control["label"],
        selected_value=control["value"],
        page_url=str(page.url),
        captured_at=datetime.now(timezone.utc).isoformat(),
        superflex=True,
        te_premium="TE++",
        te_premium_level=KTC_TEPP_LEVEL,
        row_count=len(rows),
        priced_count=priced,
        content_hash=_content_hash(rows),
        rows=rows,
    )


def validate_capture_set(captures: Mapping[str, KtcValueSourceCapture]) -> None:
    """Prove that the three requested KTC modes were actually observed.

    A UI event that changes only a dropdown label while leaving the backing
    playersArray untouched is a plausible parser failure. Requiring at least
    two distinct whole-board hashes makes that failure loud without claiming
    every individual asset must differ across all three modes.
    """
    missing = set(KTC_VALUE_SOURCES) - set(captures)
    if missing:
        raise KtcValueSourceError(f"KTC value-source captures missing: {sorted(missing)}")
    hashes = {captures[source].content_hash for source in KTC_VALUE_SOURCES}
    if len(hashes) < 2:
        raise KtcValueSourceError(
            "KTC three-mode selector changed labels but all captured boards "
            "were byte-equivalent; selected-source data path was not proven"
        )
    selected_values = {captures[source].selected_value for source in KTC_VALUE_SOURCES}
    if len(selected_values) < 2:
        raise KtcValueSourceError(
            "KTC Value Source control did not expose distinct underlying option values"
        )
    for source, expected in KTC_CONTROL_VALUES.items():
        observed = str(captures[source].selected_value)
        if observed != expected:
            raise KtcValueSourceError(
                f"KTC {source} control value changed: observed={observed!r}, expected={expected!r}"
            )


async def capture_all_value_sources(page: Any) -> dict[str, KtcValueSourceCapture]:
    """Capture Crowd, Trades and Crowd+Trades from one first-party payload."""
    controls = await value_source_options(page)
    raw_rows = await selected_players_array(page)
    captured_at = datetime.now(timezone.utc).isoformat()
    captures: dict[str, KtcValueSourceCapture] = {}
    for source in KTC_VALUE_SOURCES:
        rows = observations_from_players_array(raw_rows, source)
        priced = sum(1 for row in rows if row.tepp_value is not None)
        floor = int(KTC_SOURCE_MIN_PRICED.get(source, 100))
        if len(rows) < 100 or priced < floor:
            raise KtcValueSourceError(
                f"KTC {source} board is partial: rows={len(rows)}, priced={priced}, floor={floor}"
            )
        control = controls[source]
        captures[source] = KtcValueSourceCapture(
            value_source=source,
            selected_label=control["label"],
            selected_value=control["value"],
            page_url=str(page.url),
            captured_at=captured_at,
            superflex=True,
            te_premium="TE++",
            te_premium_level=KTC_TEPP_LEVEL,
            row_count=len(rows),
            priced_count=priced,
            content_hash=_content_hash(rows),
            rows=rows,
        )
    validate_capture_set(captures)
    return captures


def value_divergence(
    crowd_value: float | None,
    trades_value: float | None,
) -> tuple[float | None, float | None, str | None]:
    """Return (Trades-Crowd delta, percent-of-Crowd, direction).

    This is the single arithmetic owner used by both capture-level and
    contract-row diagnostics. Missing stays missing; no threshold is invented.
    """
    if crowd_value is None or trades_value is None:
        return None, None, None
    delta = float(trades_value) - float(crowd_value)
    percent_delta = (delta / float(crowd_value)) * 100.0 if crowd_value else None
    if delta > 0:
        direction = "trade_premium"
    elif delta < 0:
        direction = "crowd_premium"
    else:
        direction = "aligned"
    return delta, percent_delta, direction


def crowd_trade_divergence(
    crowd: KtcValueSourceCapture,
    trades: KtcValueSourceCapture,
) -> tuple[KtcValueDivergence, ...]:
    """Return source-native Crowd-vs-Trades deltas on the TE++ board.

    No threshold is applied. Missing Tradesourced observations remain missing;
    they never become a zero-value crowd_premium.
    """

    def _key(row: KtcValueObservation) -> tuple[str, int | str]:
        if row.player_id is not None:
            return ("id", row.player_id)
        return ("name", row.name.casefold())

    crowd_rows = {_key(row): row for row in crowd.rows}
    trade_rows = {_key(row): row for row in trades.rows}
    out: list[KtcValueDivergence] = []
    for key in sorted(set(crowd_rows) | set(trade_rows), key=str):
        crowd_row = crowd_rows.get(key)
        trade_row = trade_rows.get(key)
        exemplar = crowd_row or trade_row
        assert exemplar is not None
        crowd_value = crowd_row.tepp_value if crowd_row is not None else None
        trades_value = trade_row.tepp_value if trade_row is not None else None
        delta, percent_delta, direction = value_divergence(crowd_value, trades_value)
        out.append(
            KtcValueDivergence(
                name=exemplar.name,
                player_id=exemplar.player_id,
                crowd_value=crowd_value,
                trades_value=trades_value,
                delta=delta,
                percent_delta=percent_delta,
                direction=direction,
            )
        )
    return tuple(out)


KTC_SOURCE_FILE_KEYS: Mapping[str, str] = {
    KTC_CROWD: "ktcCrowdSfTep",
    KTC_TRADES: "ktcTradesSfTep",
    KTC_CROWD_TRADES: "ktcCrowdTradesSfTep",
}

KTC_SOURCE_MIN_PRICED: Mapping[str, int] = {
    KTC_CROWD: 400,
    KTC_TRADES: 100,
    KTC_CROWD_TRADES: 400,
}


def write_capture_artifacts(
    captures: Mapping[str, KtcValueSourceCapture],
    *,
    site_raw_dir: Path,
    provenance_path: Path,
) -> set[str]:
    """Persist the three KTC source modes and one provenance sidecar.

    This is the ONE writer for KTC three-source artifacts. Crowd/Trades are
    diagnostic same-family observations; writing them does not register votes.
    Missing Tradesourced values are omitted from its CSV rather than zeroed.
    """
    validate_capture_set(captures)
    site_raw_dir.mkdir(parents=True, exist_ok=True)
    written: set[str] = set()
    for source in KTC_VALUE_SOURCES:
        capture = captures[source]
        priced_rows = [row for row in capture.rows if row.tepp_value is not None]
        floor = KTC_SOURCE_MIN_PRICED[source]
        if len(priced_rows) < floor:
            raise KtcValueSourceError(
                f"KTC {source} TE++ coverage {len(priced_rows)} below floor {floor}"
            )
        file_key = KTC_SOURCE_FILE_KEYS[source]
        out = site_raw_dir / f"{file_key}.csv"
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["name", "value", "rank", "player_id", "position"])
            for row in sorted(priced_rows, key=lambda item: item.name.casefold()):
                writer.writerow(
                    [
                        row.name,
                        row.tepp_value,
                        "" if row.tepp_rank is None else row.tepp_rank,
                        "" if row.player_id is None else row.player_id,
                        row.position or "",
                    ]
                )
        written.add(out.name)

    crowd = captures[KTC_CROWD]
    trades = captures[KTC_TRADES]
    divergence = crowd_trade_divergence(crowd, trades)
    provenance_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "KeepTradeCut",
        "canonicalMarketSource": KTC_CANONICAL_MARKET_SOURCE,
        "operatorFormat": {
            "gameType": "DYNASTY",
            "superflex": True,
            "tePremium": "TE++",
            "tePremiumLevel": KTC_TEPP_LEVEL,
        },
        "captures": {source: captures[source].provenance_dict() for source in KTC_VALUE_SOURCES},
        "crowdTradesDivergence": [
            {
                "name": row.name,
                "playerId": row.player_id,
                "crowdValue": row.crowd_value,
                "tradesValue": row.trades_value,
                "delta": row.delta,
                "percentDelta": row.percent_delta,
                "direction": row.direction,
            }
            for row in divergence
        ],
    }
    provenance_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return written


def serialise_capture(capture: KtcValueSourceCapture) -> dict[str, Any]:
    """JSON-friendly audit packet; values/ranks remain source-native."""
    return {
        **capture.provenance_dict(),
        "rows": [asdict(row) for row in capture.rows],
    }
