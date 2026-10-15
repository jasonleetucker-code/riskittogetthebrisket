"""The screenshot-import pipeline end to end, plus its response contract.

``extract_trade`` returns EXACTLY the payload documented below, and checks it
with :func:`validate_extraction` before returning — a payload that drifts
from the contract the UI is built against is a server defect, raised here
rather than shipped::

    {"ok": true, "imageIndex": int,
     "engine": {"name": "tesseract", "version": str|null},
     "layout": {"kind": "two_column"|"stacked"|"single"|"unknown", "confidence": float},
     "sides": [{"label": str, "labelSource": "anchor"|"position"|"none", "items": [ITEM]}],
     "unassigned": [ITEM],
     "ignored": [{"raw": str, "reason": str}],
     "warnings": [str]}

    ITEM = {"raw": str, "kind": "player"|"pick",
            "status": "resolved"|"needs_confirmation"|"unresolved",
            "boardName": str|null, "sleeperId": str|null,
            "candidates": [CANDIDATE], "suggestions": [CANDIDATE],
            "hints": {"position": str|null, "team": str|null},
            "reason": str|null, "lineIndex": int, "conf": float}
    CANDIDATE = {"sleeperId": str|null, "boardName": str,
                 "position": str|null, "team": str|null}

Text read from the image is DATA: it is only ever compared against the board
as a candidate asset string — never executed, evaluated or followed.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.trade.screenshot_import.image_input import png_dimensions
from src.trade.screenshot_import.layout import Layout, Line, build_lines, detect_layout
from src.trade.screenshot_import.ocr import (
    DEFAULT_TIMEOUT_S,
    ENGINE_NAME,
    OcrEngine,
    TesseractEngine,
    Word,
    run_ocr,
)
from src.trade.screenshot_import.parse import (
    NOTE_PICK_OWNER,
    ParsedItem,
    parse_hints_only,
    parse_line,
)
from src.trade.screenshot_import.resolve import ResolvedItem, resolve_items

LAYOUT_KINDS = ("two_column", "stacked", "single", "unknown")
LABEL_SOURCES = ("anchor", "position", "none")
ITEM_KINDS = ("player", "pick")
ITEM_STATUSES = ("resolved", "needs_confirmation", "unresolved")

WARN_MISSING_SIDE = "missing_side"
WARN_LOW_LAYOUT_CONFIDENCE = "low_layout_confidence"
WARN_POSSIBLY_CROPPED = "possibly_cropped"
WARN_NO_ASSETS = "no_assets_found"

_EDGE_FRACTION = 0.01


def default_engine() -> OcrEngine:
    return TesseractEngine()


class ExtractionSchemaError(ValueError):
    """The extraction payload does not match the published contract."""


# ── Assembly ────────────────────────────────────────────────────────────


def _item_dict(res: ResolvedItem, line: Line, line_index: int) -> dict:
    return {
        "raw": res.raw,
        "kind": res.kind,
        "status": res.status,
        "boardName": res.board_name,
        "sleeperId": res.sleeper_id,
        "candidates": [dict(c) for c in res.candidates],
        "suggestions": [dict(c) for c in res.suggestions],
        "hints": {
            "position": res.hints.get("position"),
            "team": res.hints.get("team"),
        },
        "reason": res.reason,
        "lineIndex": int(line_index),
        "conf": float(line.conf),
    }


def _touches_edge(line: Line, width: int, height: int) -> bool:
    if width <= 0 or height <= 0:
        return False
    return (
        line.top <= _EDGE_FRACTION * height
        or line.bottom >= (1 - _EDGE_FRACTION) * height
        or line.left <= _EDGE_FRACTION * width
        or line.right >= (1 - _EDGE_FRACTION) * width
    )


def build_extraction(
    words: Sequence[Word],
    *,
    width: int,
    height: int,
    identity_ctx: Any,
    contract: Mapping[str, Any] | None,
    image_index: int = 0,
    engine_version: str | None = None,
) -> dict:
    """Assemble and validate the payload from already-recognised words."""
    lines = build_lines(words)
    layout: Layout = detect_layout(lines, width)

    every_line: list[Line] = [ln for side in layout.sides for ln in side.lines]
    every_line += list(layout.unassigned)
    every_line += [ln for ln, _ in layout.ignored]
    every_line += list(layout.anchors)
    ordered = sorted({id(ln): ln for ln in every_line}.values(), key=lambda ln: (ln.row, ln.left))
    line_index = {id(ln): i for i, ln in enumerate(ordered)}

    ignored: list[tuple[Line, str]] = list(layout.ignored)
    # region -1 = unassigned; 0/1 = sides
    pending: list[tuple[int, Line, ParsedItem]] = []
    regions: list[tuple[int, Sequence[Line]]] = [
        (i, side.lines) for i, side in enumerate(layout.sides)
    ] + [(-1, layout.unassigned)]
    for region, region_lines in regions:
        last_player: tuple[Line, ParsedItem, int] | None = None  # (line, item, pending idx)
        for ln in region_lines:
            parsed = parse_line(ln.text)
            if parsed is None:
                hint = parse_hints_only(ln.text)
                if (
                    hint is not None
                    and last_player is not None
                    and last_player[0].row == ln.row
                    and last_player[0].right <= ln.left
                ):
                    merged = dict(last_player[1].hints)
                    for k in ("position", "team"):
                        if merged.get(k) is None and hint.get(k) is not None:
                            merged[k] = hint[k]
                    upd = ParsedItem(
                        kind=last_player[1].kind,
                        raw=last_player[1].raw,
                        market_ref=last_player[1].market_ref,
                        name=last_player[1].name,
                        hints=merged,
                        reason=last_player[1].reason,
                        notes=last_player[1].notes,
                        label=last_player[1].label,
                    )
                    pending[last_player[2]] = (region, last_player[0], upd)
                    last_player = (last_player[0], upd, last_player[2])
                    ignored.append((ln, "position_team_hint"))
                else:
                    ignored.append((ln, "not_an_asset"))
                continue
            pending.append((region, ln, parsed))
            last_player = (ln, parsed, len(pending) - 1) if parsed.kind == "player" else None

    resolved = resolve_items([p[2] for p in pending], identity_ctx=identity_ctx, contract=contract)

    side_items: list[list[dict]] = [[] for _ in layout.sides]
    unassigned_items: list[dict] = []
    warnings: list[str] = []
    cropped = False
    for (region, ln, _parsed), res in zip(pending, resolved):
        item = _item_dict(res, ln, line_index.get(id(ln), 0))
        if region >= 0:
            side_items[region].append(item)
        else:
            unassigned_items.append(item)
        if NOTE_PICK_OWNER in res.notes:
            warnings.append(NOTE_PICK_OWNER)
        if _touches_edge(ln, width, height):
            cropped = True

    total = len(pending)
    if total == 0:
        warnings.append(WARN_NO_ASSETS)
    else:
        populated = sum(1 for items in side_items if items)
        if populated < 2:
            warnings.append(WARN_MISSING_SIDE)
    if layout.confidence < 0.6:
        warnings.append(WARN_LOW_LAYOUT_CONFIDENCE)
    if cropped:
        warnings.append(WARN_POSSIBLY_CROPPED)
    seen: set[str] = set()
    warnings = [w for w in warnings if not (w in seen or seen.add(w))]

    ignored.sort(key=lambda it: (it[0].row, it[0].left))
    payload = {
        "ok": True,
        "imageIndex": int(image_index),
        "engine": {"name": ENGINE_NAME, "version": engine_version},
        "layout": {"kind": layout.kind, "confidence": float(layout.confidence)},
        "sides": [
            {"label": side.label, "labelSource": side.label_source, "items": side_items[i]}
            for i, side in enumerate(layout.sides)
        ],
        "unassigned": unassigned_items,
        "ignored": [{"raw": ln.text, "reason": reason} for ln, reason in ignored],
        "warnings": warnings,
    }
    validate_extraction(payload)
    return payload


def extract_trade(
    png: bytes,
    *,
    engine: OcrEngine,
    identity_ctx: Any,
    contract: Mapping[str, Any] | None,
    image_index: int = 0,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """OCR ``png`` through the single gateway and build the payload.

    OCR refusals (``OcrUnavailable`` / ``OcrBusy`` / ``OcrTimeout`` /
    ``OcrError``) propagate to the caller, which maps them to HTTP states.
    """
    dims = png_dimensions(png)
    width, height = dims if dims else (0, 0)
    words = run_ocr(engine, png, timeout_s=timeout_s)
    return build_extraction(
        words,
        width=width,
        height=height,
        identity_ctx=identity_ctx,
        contract=contract,
        image_index=image_index,
        engine_version=engine.availability().version,
    )


# ── Contract validator ──────────────────────────────────────────────────


def _fail(path: str, why: str) -> None:
    raise ExtractionSchemaError(f"{path}: {why}")


def _exact_keys(obj: Any, keys: set[str], path: str) -> None:
    if not isinstance(obj, dict):
        _fail(path, "must be an object")
    if set(obj.keys()) != keys:
        _fail(path, f"keys {sorted(obj.keys())} != {sorted(keys)}")


def _str(v: Any, path: str, *, nullable: bool = False) -> None:
    if v is None and nullable:
        return
    if not isinstance(v, str):
        _fail(path, "must be a string" + (" or null" if nullable else ""))


def _num(v: Any, path: str) -> None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _fail(path, "must be a number")


def _candidate(c: Any, path: str) -> None:
    _exact_keys(c, {"sleeperId", "boardName", "position", "team"}, path)
    _str(c["sleeperId"], f"{path}.sleeperId", nullable=True)
    _str(c["boardName"], f"{path}.boardName")
    _str(c["position"], f"{path}.position", nullable=True)
    _str(c["team"], f"{path}.team", nullable=True)


_ITEM_KEYS = {
    "raw",
    "kind",
    "status",
    "boardName",
    "sleeperId",
    "candidates",
    "suggestions",
    "hints",
    "reason",
    "lineIndex",
    "conf",
}


def _item(it: Any, path: str) -> None:
    _exact_keys(it, _ITEM_KEYS, path)
    _str(it["raw"], f"{path}.raw")
    if it["kind"] not in ITEM_KINDS:
        _fail(f"{path}.kind", f"{it['kind']!r} not in {ITEM_KINDS}")
    if it["status"] not in ITEM_STATUSES:
        _fail(f"{path}.status", f"{it['status']!r} not in {ITEM_STATUSES}")
    _str(it["boardName"], f"{path}.boardName", nullable=True)
    _str(it["sleeperId"], f"{path}.sleeperId", nullable=True)
    for key in ("candidates", "suggestions"):
        if not isinstance(it[key], list):
            _fail(f"{path}.{key}", "must be a list")
        for j, c in enumerate(it[key]):
            _candidate(c, f"{path}.{key}[{j}]")
    _exact_keys(it["hints"], {"position", "team"}, f"{path}.hints")
    _str(it["hints"]["position"], f"{path}.hints.position", nullable=True)
    _str(it["hints"]["team"], f"{path}.hints.team", nullable=True)
    _str(it["reason"], f"{path}.reason", nullable=True)
    if isinstance(it["lineIndex"], bool) or not isinstance(it["lineIndex"], int):
        _fail(f"{path}.lineIndex", "must be an integer")
    if it["lineIndex"] < 0:
        _fail(f"{path}.lineIndex", "must be >= 0")
    _num(it["conf"], f"{path}.conf")
    # Cross-field invariants: an answer must be stated, never implied.
    if it["status"] == "resolved" and not it["boardName"]:
        _fail(path, "resolved item without boardName")
    if it["status"] != "resolved" and it["boardName"] is not None:
        _fail(path, "only a resolved item may carry boardName")
    if it["status"] == "needs_confirmation" and not it["candidates"]:
        _fail(path, "needs_confirmation without candidates")
    if it["status"] == "unresolved" and not it["reason"]:
        _fail(path, "unresolved item without reason")


def validate_extraction(payload: Any) -> None:
    """Raise :class:`ExtractionSchemaError` on ANY deviation from the
    documented contract (extra keys included)."""
    _exact_keys(
        payload,
        {"ok", "imageIndex", "engine", "layout", "sides", "unassigned", "ignored", "warnings"},
        "$",
    )
    if payload["ok"] is not True:
        _fail("$.ok", "must be true")
    if isinstance(payload["imageIndex"], bool) or not isinstance(payload["imageIndex"], int):
        _fail("$.imageIndex", "must be an integer")
    _exact_keys(payload["engine"], {"name", "version"}, "$.engine")
    if payload["engine"]["name"] != ENGINE_NAME:
        _fail("$.engine.name", f"must be {ENGINE_NAME!r}")
    _str(payload["engine"]["version"], "$.engine.version", nullable=True)
    _exact_keys(payload["layout"], {"kind", "confidence"}, "$.layout")
    if payload["layout"]["kind"] not in LAYOUT_KINDS:
        _fail("$.layout.kind", f"not in {LAYOUT_KINDS}")
    _num(payload["layout"]["confidence"], "$.layout.confidence")
    if not 0.0 <= float(payload["layout"]["confidence"]) <= 1.0:
        _fail("$.layout.confidence", "must be within [0, 1]")
    sides = payload["sides"]
    if not isinstance(sides, list) or len(sides) > 2:
        _fail("$.sides", "must be a list of at most 2 sides")
    for i, side in enumerate(sides):
        _exact_keys(side, {"label", "labelSource", "items"}, f"$.sides[{i}]")
        _str(side["label"], f"$.sides[{i}].label")
        if side["labelSource"] not in LABEL_SOURCES:
            _fail(f"$.sides[{i}].labelSource", f"not in {LABEL_SOURCES}")
        if not isinstance(side["items"], list):
            _fail(f"$.sides[{i}].items", "must be a list")
        for j, it in enumerate(side["items"]):
            _item(it, f"$.sides[{i}].items[{j}]")
    if not isinstance(payload["unassigned"], list):
        _fail("$.unassigned", "must be a list")
    for j, it in enumerate(payload["unassigned"]):
        _item(it, f"$.unassigned[{j}]")
    if not isinstance(payload["ignored"], list):
        _fail("$.ignored", "must be a list")
    for j, ig in enumerate(payload["ignored"]):
        _exact_keys(ig, {"raw", "reason"}, f"$.ignored[{j}]")
        _str(ig["raw"], f"$.ignored[{j}].raw")
        _str(ig["reason"], f"$.ignored[{j}].reason")
    if not isinstance(payload["warnings"], list):
        _fail("$.warnings", "must be a list")
    for j, w in enumerate(payload["warnings"]):
        _str(w, f"$.warnings[{j}]")
