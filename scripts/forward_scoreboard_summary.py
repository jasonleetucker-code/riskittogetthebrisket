#!/usr/bin/env python3
"""Aggregate-only summary of a forward-validation scoreboard JSON (DYN10 V1b).

Run on the box by ``.github/workflows/forward-scoreboard-onbox.yml`` (read-only,
``workflow_dispatch``).  The workflow's log and step summary are PUBLIC, so this
prints a fixed WHITELIST of aggregate statistics -- nothing else.  Unknown
fields are dropped, never passed through: no player names, asset keys, ids or
file paths.  Per horizon, per series (the served board and each source), per
group it keeps origins used, n per origin, rho per origin, mean rho, sign
consistency, the momentum partial, the persistence baseline, the zero-gap
share, verdict strings and the inputs / caveats block.

An ``unavailable`` board is carried through as a state, never dropped.

Exit codes: 0 summary printed; 2 the input is not a scoreboard; 3 the summary
itself failed (only the exception class is printed).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

# Like scripts/market_trade_report_summary.py::_LABEL_RE but WITHOUT ":" so asset keys
# (player:1234, mpick:2027:r1) can never pass as labels: a map label
# must look like an enum value (starts with a letter).  Numeric ids are dropped.
_LABEL_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+-]{0,47}")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_TEXT_MAX = 700
# Free text is kept only when it cannot be naming a box path or a data file.
_PATHLIKE_RE = re.compile(
    r"(?:^|[\s(\"'])/[A-Za-z0-9_.-]+/|[A-Za-z]:\\|\\\\|"
    r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.[A-Za-z0-9]{2,6}\b|"
    r"\.(?:sqlite|zip|json|csv|db)\b"
)

_CELL_NUM = (
    "meanSpearman",
    "medianSpearman",
    "meanPartialR",
    "meanDeltaR2",
    "meanZeroGapShare",
    "meanUnchangedSincePriorShare",
)
_CELL_INT = ("foldsAttempted", "foldsUsable", "foldsPositive")
_FOLD_NUM = (
    "rho",
    "partialR",
    "deltaR2",
    "zeroGapShare",
    "unchangedSincePriorShare",
    "rhoGapOnMomentumRows",
    "rhoMomentum",
    "rhoGapVsPriorReturn",
    "partialRhoGivenMomentum",
)
_FOLD_INT = ("n", "distinctNonZeroGaps", "momentumN")
_MOMENTUM_NUM = (
    "meanRhoGap",
    "meanRhoMomentum",
    "meanRhoGapVsPriorReturn",
    "meanPartialRhoGivenMomentum",
)
_PERSISTENCE_NUM = ("spearmanLevel", "r2LogLevel", "medianAbsLogReturn", "unchangedShare")


def _label(raw: Any) -> str | None:
    text = str(raw)
    return text if _LABEL_RE.fullmatch(text) else None


def _int(raw: Any) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw) if raw == raw and abs(raw) != float("inf") else None


def _date(raw: Any) -> str | None:
    return raw if isinstance(raw, str) and _DATE_RE.fullmatch(raw) else None


def _text(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw or _PATHLIKE_RE.search(raw):
        return None
    return raw[:_TEXT_MAX]


def _pick(src: Any, nums: tuple[str, ...], ints: tuple[str, ...]) -> dict[str, Any]:
    src = src if isinstance(src, dict) else {}
    out: dict[str, Any] = {k: _num(src.get(k)) for k in nums}
    out.update({k: _int(src.get(k)) for k in ints})
    return out


def _fold_rows(raw: Any, *, with_reason: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {"origin": _date(item.get("origin"))}
        row.update(_pick(item, _FOLD_NUM, _FOLD_INT))
        if with_reason:
            row["reason"] = _text(item.get("reason"))
        rows.append(row)
    return rows


def whitelist_cell(cell: Any) -> dict[str, Any]:
    """One (series, group) summary.  Pure; unknown keys dropped."""
    cell = cell if isinstance(cell, dict) else {}
    out = _pick(cell, _CELL_NUM, _CELL_INT)
    out["verdict"] = _text(cell.get("verdict"))
    rng = cell.get("deltaR2Range")
    out["deltaR2Range"] = (
        [_num(x) for x in rng] if isinstance(rng, list) and len(rng) == 2 else None
    )
    bench = cell.get("benchmarks") if isinstance(cell.get("benchmarks"), dict) else {}
    out["benchmarks"] = {
        name: {
            "meanSpearman": _num(bench[name].get("meanSpearman")),
            "beatenInFolds": _int(bench[name].get("beatenInFolds")),
        }
        for name in ("marketValue", "random")
        if isinstance(bench.get(name), dict)
    }
    out["spearmanByFold"] = _fold_rows(cell.get("spearmanByFold"), with_reason=False)
    out["originsUnusable"] = _fold_rows(cell.get("originsUnusable"), with_reason=True)
    mom = cell.get("momentumControl") if isinstance(cell.get("momentumControl"), dict) else {}
    out["momentumControl"] = {
        **_pick(mom, _MOMENTUM_NUM, ("originsMeasured", "partialPositive")),
        "verdict": _text(mom.get("verdict")),
    }
    return out


def _by_group(raw: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(raw, dict):
        for g, cell in raw.items():
            label = _label(g)
            if label is not None:
                out[label] = whitelist_cell(cell)
    return dict(sorted(out.items()))


def _count_map(raw: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            label = _label(k)
            if label is not None and _int(v) is not None:
                out[label] = v
    return dict(sorted(out.items()))


def _whitelist_fold(fold: Any) -> dict[str, Any]:
    fold = fold if isinstance(fold, dict) else {}
    att = fold.get("attrition") if isinstance(fold.get("attrition"), dict) else {}
    pers = fold.get("persistence") if isinstance(fold.get("persistence"), dict) else {}
    persistence: dict[str, Any] = {}
    for g, block in pers.items():
        label = _label(g)
        if label is not None and isinstance(block, dict):
            persistence[label] = _pick(block, _PERSISTENCE_NUM, ("n",))
    return {
        "origin": _date(fold.get("origin")),
        "horizon": _date(fold.get("horizon")),
        "heldDays": _int(fold.get("heldDays")),
        "marketUniverse": _int(fold.get("marketUniverse")),
        "nByGroup": _count_map(fold.get("byGroup")),
        "boardObservationsAtOrigin": _int(fold.get("boardObservationsAtOrigin")),
        "attrition": {"dropped": _int(att.get("dropped")), "rate": _num(att.get("rate"))},
        "persistence": dict(sorted(persistence.items())),
    }


def _whitelist_horizon(block: Any) -> dict[str, Any]:
    block = block if isinstance(block, dict) else {}
    board = block.get("board") if isinstance(block.get("board"), dict) else {}
    status = board.get("status")
    board_out: dict[str, Any] = {
        "status": status if status in ("measured", "unavailable") else "unknown",
        "reason": _text(board.get("reason")),
    }
    if status == "measured":
        board_out["byGroup"] = _by_group(board.get("byGroup"))
    sources: dict[str, Any] = {}
    raw_sources = block.get("sources") if isinstance(block.get("sources"), dict) else {}
    for key, src in raw_sources.items():
        label = _label(key)
        if label is None or not isinstance(src, dict):
            continue
        sources[label] = {
            "provider": _label(src.get("provider")),
            "sameProviderAsOffenseTarget": src.get("sameProviderAsOffenseTarget") is True,
            "isIdpTarget": src.get("isIdpTarget") is True,
            "byGroup": _by_group(src.get("byGroup")),
        }
    folds = block.get("folds") if isinstance(block.get("folds"), list) else []
    return {
        "horizonDays": _int(block.get("horizonDays")),
        "foldsAttempted": _int(block.get("foldsAttempted")),
        "foldsNote": _text(block.get("foldsNote")),
        "folds": [_whitelist_fold(f) for f in folds],
        "board": board_out,
        "sources": dict(sorted(sources.items())),
    }


def whitelist_scoreboard(payload: Any) -> dict[str, Any]:
    """The aggregate whitelist of one scoreboard payload.  Pure."""
    payload = payload if isinstance(payload, dict) else {}
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    mode = inputs.get("mode")
    raw_h = payload.get("horizons") if isinstance(payload.get("horizons"), dict) else {}
    horizons = {
        str(h): _whitelist_horizon(b)
        for h, b in raw_h.items()
        if isinstance(h, str) and h.isdigit()
    }
    caveats_raw = payload.get("caveats") if isinstance(payload.get("caveats"), list) else []
    caveats = [t for t in (_text(c) for c in caveats_raw) if t is not None]
    panel = payload.get("panel") if isinstance(payload.get("panel"), dict) else {}
    cand = payload.get("independentValidationCandidate")
    cand = cand if isinstance(cand, dict) else {}
    sha = payload.get("codeSha")
    return {
        "schema": _text(payload.get("schema")),
        "measuredAt": _text(payload.get("measuredAt")),
        "codeSha": sha if isinstance(sha, str) and _SHA_RE.fullmatch(sha) else None,
        "codeDirty": payload["codeDirty"] if isinstance(payload.get("codeDirty"), bool) else None,
        "inputs": {
            "mode": mode if mode in ("archive", "ledger") else None,
            "ledgerCorrections": _int(inputs.get("ledgerCorrections")),
        },
        "panel": {
            "dates": _int(panel.get("dates")),
            "start": _date(panel.get("start")),
            "end": _date(panel.get("end")),
            "boardDates": _int(panel.get("boardDates")),
            "marketDates": _count_map(panel.get("marketDates")),
        },
        "minUsableOriginsForVerdict": _int(payload.get("minUsableOriginsForVerdict")),
        "minPairsPerCrossSection": _int(payload.get("minPairsPerCrossSection")),
        "maxZeroGapShare": _num(payload.get("maxZeroGapShare")),
        "horizons": dict(sorted(horizons.items(), key=lambda kv: int(kv[0]))),
        "independentValidationCandidate": {
            "registered": cand.get("registered") is True,
            "couldQualifyAsIs": cand.get("couldQualifyAsIs") is True,
        },
        "caveats": caveats,
        "caveatsDropped": len(caveats_raw) - len(caveats),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    head = (
        "### Forward validation scoreboard (on-box ledger)\n\n"
        f"- measured: {summary.get('measuredAt')}\n"
        f"- input mode: {(summary.get('inputs') or {}).get('mode')}\n"
    )
    for h, block in summary.get("horizons", {}).items():
        head += f"- horizon {h}d: board **{block['board']['status']}**\n"
    return head + "\n```json\n" + json.dumps(summary, indent=1, sort_keys=True) + "\n```\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", type=Path, help="scoreboard JSON")
    parser.add_argument("--markdown", action="store_true", help="emit step-summary markdown")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.json_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("horizons"), dict):
            print("summary failed: not a scoreboard")
            return 2
        summary = whitelist_scoreboard(payload)
        print(render_markdown(summary) if args.markdown else json.dumps(summary, indent=1))
    except Exception as exc:  # noqa: BLE001 -- the log is public: class name only
        print(f"summary failed: {type(exc).__name__}")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
