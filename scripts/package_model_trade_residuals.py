"""Completed own-league trades under every registered package model (owner VA
package 2026-10-17, PR 4).

A DIAGNOSTIC, not an accuracy score.  Both managers accepted each trade, so it
cleared at "even" by definition; the relative residual

    (adjusted_A - adjusted_B) / mean(adjusted_A, adjusted_B)

says how far a package model, applied to one vendor's point-in-time prices,
disagrees with that clearing.  A model with smaller residuals agrees better
with what these managers actually accepted.  It does NOT say a trade was fair,
who won, or that a model is right: completed trades are a selected sample
(rejected offers are unobserved), these are two leagues' managers only, and
the prices are one vendor's.

Point-in-time and observed only.  Each trade is priced from the vendor CSV
archived in ``exports/archive/`` strictly before the trade and no more than
``--max-lag-days`` before it — the vendor's own published number, never a
value re-derived with today's curve.  Coverage is all-or-nothing: a trade with
any asset the vendor did not price that day is excluded and counted, never
priced as a smaller side.  Same rule as ``src/trade/market_trade_eval.py``,
whose live archive (``data/intel``) is box-local and not available here.

Usage:
    python scripts/package_model_trade_residuals.py [--out PATH] [--max-lag-days 7]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.utils.name_clean import normalize_player_name  # noqa: E402
from src.valuation_math import package_model  # noqa: E402

ARCHIVE = REPO / "exports" / "archive"
TRADES = REPO / "data" / "sleeper_last_good.json"
# Vendor CSV inside each archive, by source label.  ``ktcSfTep`` is KTC's
# SF TE++ board (the incumbent VA's own calibration population); IDP Trade
# Calculator is the full-roster market (offense + IDP + picks).
SOURCES = {"ktcSfTep": "site_raw/ktcSfTep.csv", "idpTradeCalc": "site_raw/idpTradeCalc.csv"}
_ARCHIVE_RE = re.compile(r"dynasty_export_(\d{8})_(\d{6})\.zip$")
_FROM_RE = re.compile(r"\s*\(from [^)]*\)\s*$", re.IGNORECASE)
_PICK_RE = re.compile(r"^\d{4}\s")


def _archives() -> list[tuple[int, Path]]:
    out = []
    for p in ARCHIVE.glob("dynasty_export_*.zip"):
        m = _ARCHIVE_RE.search(p.name)
        if not m:
            continue
        dt = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        out.append((int(dt.timestamp() * 1000), p))
    return sorted(out)


def _key(label: str) -> str:
    name = _FROM_RE.sub("", str(label or "")).strip()
    if _PICK_RE.match(name):
        return "pick:" + " ".join(name.lower().split())
    return "player:" + normalize_player_name(name)


_BOARD_CACHE: dict[tuple[Path, str], dict[str, float] | None] = {}


def _board(path: Path, source: str) -> dict[str, float] | None:
    hit = _BOARD_CACHE.get((path, source))
    if hit is not None or (path, source) in _BOARD_CACHE:
        return hit
    board = None
    with zipfile.ZipFile(path) as zf:
        if SOURCES[source] in zf.namelist():
            rows = csv.DictReader(io.StringIO(zf.read(SOURCES[source]).decode("utf-8")))
            board = {}
            for r in rows:
                try:
                    v = float(r.get("value") or "")
                except ValueError:
                    continue
                if v > 0:
                    board[_key(r.get("name") or "")] = v
    _BOARD_CACHE[(path, source)] = board
    return board


def _summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    a = sorted(abs(x) for x in xs)
    return {
        "n": len(xs),
        "meanAbs": round(statistics.fmean(a), 4),
        "medianAbs": round(statistics.median(a), 4),
        "p90Abs": round(a[min(len(a) - 1, int(0.9 * len(a)))], 4),
        "beyond10pct": sum(1 for x in a if x > 0.10),
        "beyond20pct": sum(1 for x in a if x > 0.20),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--out", default="docs/valuation/evidence/package_model_2026-10-17/trade_residuals.json"
    )
    ap.add_argument("--max-lag-days", type=float, default=7.0)
    args = ap.parse_args()

    trades = json.loads(TRADES.read_text())["rosterData"].get("trades") or []
    archives = _archives()
    models = [package_model.active_model_id(), *package_model.shadow_model_ids()]
    census = {"trades": len(trades), "notTwoTeam": 0, "noArchiveBefore": 0, "boardTooOld": 0}
    per_source: dict[str, dict] = {}
    for source in SOURCES:
        excluded_unpriced = 0
        source_missing = 0
        rows = []
        for t in trades:
            sides = t.get("sides") or []
            if len(sides) != 2:
                if source == next(iter(SOURCES)):
                    census["notTwoTeam"] += 1
                continue
            ts = int(t.get("timestamp") or 0)
            prior = [a for a in archives if a[0] < ts]
            if not prior:
                if source == next(iter(SOURCES)):
                    census["noArchiveBefore"] += 1
                continue
            a_ts, a_path = prior[-1]
            if (ts - a_ts) / 86_400_000 > args.max_lag_days:
                if source == next(iter(SOURCES)):
                    census["boardTooOld"] += 1
                continue
            board = _board(a_path, source)
            if board is None:
                source_missing += 1
                continue
            got_a = [board.get(_key(x)) for x in sides[0].get("got") or []]
            got_b = [board.get(_key(x)) for x in sides[1].get("got") or []]
            if not got_a or not got_b or any(v is None for v in got_a + got_b):
                excluded_unpriced += 1
                continue
            row = {
                "week": t.get("week"),
                "shape": f"{len(got_a)}v{len(got_b)}",
                "boardLagDays": round((ts - a_ts) / 86_400_000, 2),
                "rawA": sum(got_a),
                "rawB": sum(got_b),
            }
            for m in models:
                adj_a, adj_b, _va_a, _va_b = package_model.adjusted_pair_totals(
                    got_a, got_b, model_id=m
                )
                mean = (adj_a + adj_b) / 2.0
                row[m] = (adj_a - adj_b) / mean if mean > 0 else None
            mean_raw = (row["rawA"] + row["rawB"]) / 2.0
            row["raw"] = (row["rawA"] - row["rawB"]) / mean_raw if mean_raw > 0 else None
            rows.append(row)
        by_model = {
            m: _summarize([r[m] for r in rows if r.get(m) is not None]) for m in ["raw", *models]
        }
        unequal = [r for r in rows if r["shape"].split("v")[0] != r["shape"].split("v")[1]]
        by_model_unequal = {
            m: _summarize([r[m] for r in unequal if r.get(m) is not None]) for m in ["raw", *models]
        }
        closer = {
            m: sum(1 for r in rows if abs(r[m]) < abs(r[models[0]]) - 1e-12) for m in models[1:]
        }
        per_source[source] = {
            "graded": len(rows),
            "excludedUnpricedAsset": excluded_unpriced,
            "sourceAbsentFromArchive": source_missing,
            "residualAll": by_model,
            "residualUnequalShapes": by_model_unequal,
            "challengerCloserToEvenThanIncumbent": closer,
            "shapes": {
                s: sum(1 for r in rows if r["shape"] == s)
                for s in sorted({r["shape"] for r in rows})
            },
        }
    out = {
        "purpose": "Diagnostic of disagreement with accepted trades. Not accuracy, not a promotion.",
        "generatedBy": "scripts/package_model_trade_residuals.py",
        "models": {m: package_model.receipt(m) for m in models},
        "maxBoardLagDays": args.max_lag_days,
        "archiveRange": [archives[0][1].name, archives[-1][1].name] if archives else None,
        "census": census,
        "bySource": per_source,
        "limitations": [
            "Own leagues only (dynasty_main trade window); a few dozen trades, not a market sample.",
            "Completed trades are a selected sample: rejected offers are unobserved, so this cannot measure acceptance.",
            "One vendor's prices per run; managers may have priced with other sources or roster context.",
            "Residual zero is not 'correct': a trade can be accepted while lopsided.",
            "market_trade_eval's Sharp/KTC trade archive (data/intel) is box-local and was not available.",
        ],
    }
    path = REPO / args.out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(
        json.dumps(
            {
                "out": str(path.relative_to(REPO)),
                "census": census,
                **{
                    s: {
                        k: v
                        for k, v in d.items()
                        if k
                        in (
                            "graded",
                            "excludedUnpricedAsset",
                            "residualAll",
                            "challengerCloserToEvenThanIncumbent",
                        )
                    }
                    for s, d in per_source.items()
                },
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
