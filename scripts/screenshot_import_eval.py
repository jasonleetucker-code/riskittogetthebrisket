#!/usr/bin/env python3
"""Evaluate the screenshot-import pipeline over the committed fixtures.

Each fixture is a directory under ``tests/fixtures/screenshot_import/`` with
``image.png`` and ``expected.json`` (sides, the asset strings printed on each
side, and the board row each should map to).  Two questions are scored
SEPARATELY, because they fail for different reasons and are fixed in
different places:

* **extraction** — did OCR + layout read each asset string, on the right
  side?  ``recall`` = expected strings found on their side / expected;
  ``precision`` = extracted items that match an expected string on their
  side / all extracted items (sides + unassigned).
* **resolution** — of the strings that were extracted, how many mapped to
  the right board row (``status == resolved`` and the expected
  ``boardName``)?

These are numbers about THIS fixture set (synthetic screenshots), not a
universal accuracy claim for arbitrary screenshots.

Exit code is 0 whenever the evaluation ran (a missing tesseract binary is
reported and also exits 0 — there is nothing to measure, which is not a
failure of the pipeline).

    python scripts/screenshot_import_eval.py [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trade.market_trade_normalize import IdentityContext  # noqa: E402
from src.trade.screenshot_import.image_input import decode_image  # noqa: E402
from src.trade.screenshot_import.ocr import TesseractEngine  # noqa: E402
from src.trade.screenshot_import.service import extract_trade  # noqa: E402

DEFAULT_FIXTURES = ROOT / "tests" / "fixtures" / "screenshot_import"
DEFAULT_DIRECTORY = ROOT / "tests" / "fixtures" / "identity_directory_subset.json"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def score_fixture(expected: dict, out: dict) -> dict:
    extracted = [(i, it) for i, side in enumerate(out["sides"]) for it in side["items"]]
    extracted += [(None, it) for it in out["unassigned"]]
    used: set[int] = set()
    exp_total = matched = resolved_ok = 0
    misses: list[str] = []
    wrong_resolution: list[str] = []
    for side_idx, side in enumerate(expected["sides"]):
        for asset in side["assets"]:
            exp_total += 1
            hit = None
            for k, (got_side, it) in enumerate(extracted):
                if k in used or got_side != side_idx:
                    continue
                if _norm(asset["text"]) in _norm(it["raw"]):
                    hit = k
                    break
            if hit is None:
                misses.append(f"side{side_idx}:{asset['text']}")
                continue
            used.add(hit)
            matched += 1
            it = extracted[hit][1]
            want_status = asset.get("status", "resolved")
            if it["status"] == want_status and it["boardName"] == asset.get("boardName"):
                resolved_ok += 1
            else:
                wrong_resolution.append(f"{asset['text']} -> {it['status']}:{it['boardName']}")
    ignored_text = " ".join(ig["raw"] for ig in out["ignored"])
    leaked = [n for n in expected.get("mustBeIgnored", []) if n not in ignored_text]
    return {
        "layoutKind": out["layout"]["kind"],
        "layoutExpected": expected.get("layoutKind"),
        "expected": exp_total,
        "extracted": len(extracted),
        "matched": matched,
        "resolvedCorrect": resolved_ok,
        "misses": misses,
        "wrongResolution": wrong_resolution,
        "notIgnored": leaked,
        "warnings": out["warnings"],
    }


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument("--board", type=Path, default=None, help="default: <fixtures>/board.json")
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)

    engine = TesseractEngine()
    avail = engine.availability()
    if not avail.available:
        print(f"screenshot-import eval: OCR unavailable ({avail.reason}); nothing measured.")
        return 0

    board = json.loads((args.board or args.fixtures / "board.json").read_text(encoding="utf-8"))
    directory = json.loads(args.directory.read_text(encoding="utf-8"))
    directory = directory.get("players", directory)
    ctx = IdentityContext.from_directory(directory, source=str(args.directory))

    per_fixture: dict[str, dict] = {}
    for d in sorted(p for p in args.fixtures.iterdir() if p.is_dir()):
        image, exp = d / "image.png", d / "expected.json"
        if not (image.is_file() and exp.is_file()):
            continue
        expected = json.loads(exp.read_text(encoding="utf-8"))
        prepared = decode_image(image.read_bytes())
        out = extract_trade(prepared.png, engine=engine, identity_ctx=ctx, contract=board)
        per_fixture[d.name] = score_fixture(expected, out)

    tot = {k: sum(r[k] for r in per_fixture.values()) for k in ("expected", "extracted", "matched")}
    tot["resolvedCorrect"] = sum(r["resolvedCorrect"] for r in per_fixture.values())
    summary = {
        "engine": avail.to_dict(),
        "fixtures": len(per_fixture),
        "extraction": {
            "recall": _ratio(tot["matched"], tot["expected"]),
            "precision": _ratio(tot["matched"], tot["extracted"]),
            "layoutKindCorrect": sum(
                1 for r in per_fixture.values() if r["layoutKind"] == r["layoutExpected"]
            ),
        },
        "resolution": {
            "accuracyOfExtracted": _ratio(tot["resolvedCorrect"], tot["matched"]),
            "endToEnd": _ratio(tot["resolvedCorrect"], tot["expected"]),
        },
        "totals": tot,
        "perFixture": per_fixture,
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"screenshot-import eval — tesseract {avail.version} — {len(per_fixture)} fixtures")
    print(f"{'fixture':<24} {'layout':<11} {'exp':>4} {'got':>4} {'match':>5} {'resolved':>8}")
    for name, r in per_fixture.items():
        print(
            f"{name:<24} {r['layoutKind']:<11} {r['expected']:>4} {r['extracted']:>4} "
            f"{r['matched']:>5} {r['resolvedCorrect']:>8}"
        )
        for label, items in (
            ("missed", r["misses"]),
            ("wrong", r["wrongResolution"]),
            ("not ignored", r["notIgnored"]),
        ):
            if items:
                print(f"    {label}: {', '.join(items)}")
    ex, rs = summary["extraction"], summary["resolution"]
    print(
        f"EXTRACTION  recall {ex['recall']}  precision {ex['precision']}  "
        f"layout kind correct {ex['layoutKindCorrect']}/{len(per_fixture)}"
    )
    print(
        f"RESOLUTION  accuracy of extracted {rs['accuracyOfExtracted']}  "
        f"end-to-end {rs['endToEnd']}"
    )
    print("(synthetic fixture set — not a universal accuracy claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
