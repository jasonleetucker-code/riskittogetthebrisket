#!/usr/bin/env python3
"""Evaluate the screenshot-import pipeline over the committed fixtures.

Each fixture is a directory under ``tests/fixtures/screenshot_import/`` with
one image (``image.png`` / ``image.webp`` / ``image.jpg``) and
``expected.json``: the sides, the asset strings printed on each side and the
board row each should map to, optional ``unassigned`` (assets that must stay
unplaced because no trustworthy side exists for them) and ``mustBeIgnored``
(page text — other players in widgets / ads — that must never become an
item).  Four questions are scored SEPARATELY, because they fail for different
reasons and are fixed in different places:

* **trade region** — did the pipeline find the trade's area and keep the
  page out of it?  ``recall`` = expected side assets that landed on ANY side
  / expected side assets; ``precision`` = side items that are expected trade
  assets / all side items.  ``distractorLeaks`` counts ``mustBeIgnored``
  names that became an item anywhere (a side OR "needs a side").
* **extraction (OCR)** — was each expected asset string read at all,
  wherever it landed?  ``recall`` = expected strings found among the items /
  expected; ``precision`` = items matching an expected string / all items.
* **side** — of the expected assets that were extracted, how many are on the
  right side (or correctly left unassigned)?
* **identity** — of the expected assets that were extracted, how many
  resolved to the right board row (``status`` and ``boardName``)?

These are numbers about THIS fixture set (synthetic screenshots plus one
real, redacted full-page screenshot and its crop), not a universal accuracy
claim for arbitrary screenshots.

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
SUPPLEMENT_NAME = "directory_supplement.json"
IMAGE_NAMES = ("image.png", "image.webp", "image.jpg")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _image_of(d: Path) -> Path | None:
    for name in IMAGE_NAMES:
        if (d / name).is_file():
            return d / name
    return None


def score_fixture(expected: dict, out: dict) -> dict:
    """Score one extraction against its expectation (see the module doc).

    Areas are side indexes ``0`` / ``1`` or ``None`` for "needs a side"."""
    extracted = [(i, it) for i, side in enumerate(out["sides"]) for it in side["items"]]
    extracted += [(None, it) for it in out["unassigned"]]
    wanted = [
        (side_idx, asset)
        for side_idx, side in enumerate(expected["sides"])
        for asset in side["assets"]
    ] + [(None, asset) for asset in expected.get("unassigned", [])]

    used: set[int] = set()
    found = side_ok = identity_ok = region_tp = 0
    misses: list[str] = []
    wrong_side: list[str] = []
    wrong_identity: list[str] = []
    # An item matches an expected asset when its text contains the expected
    # string, or it resolved to the expected board row (OCR read "Ist" for
    # "1st" and the pick grammar repaired it).  Prefer a match in the
    # expected area, then anywhere (extraction is scored independently of
    # the side).
    for want_area, asset in wanted:
        key = _norm(asset["text"])
        hit = None
        for pass_same_area in (True, False):
            for k, (area, it) in enumerate(extracted):
                same_row = asset.get("boardName") and it["boardName"] == asset["boardName"]
                if k in used or not (key in _norm(it["raw"]) or same_row):
                    continue
                if pass_same_area and area != want_area:
                    continue
                hit = k
                break
            if hit is not None:
                break
        label = f"{'side' + str(want_area) if want_area is not None else 'unassigned'}:"
        if hit is None:
            misses.append(label + asset["text"])
            continue
        used.add(hit)
        found += 1
        area, it = extracted[hit]
        if area == want_area:
            side_ok += 1
        else:
            wrong_side.append(f"{asset['text']} -> {area}")
        if want_area is not None and area is not None:
            region_tp += 1
        if it["status"] == asset.get("status", "resolved") and it["boardName"] == asset.get(
            "boardName"
        ):
            identity_ok += 1
        else:
            wrong_identity.append(f"{asset['text']} -> {it['status']}:{it['boardName']}")

    side_items = sum(1 for area, _ in extracted if area is not None)
    expected_side_assets = sum(1 for area, _ in wanted if area is not None)
    item_text = " ".join(_norm(it["raw"]) for _, it in extracted)
    leaks = [n for n in expected.get("mustBeIgnored", []) if _norm(n) in item_text]
    ignored_text = " ".join(ig["raw"] for ig in out["ignored"])
    not_ignored = [n for n in expected.get("mustBeIgnored", []) if n not in ignored_text]
    return {
        "layoutKind": out["layout"]["kind"],
        "layoutExpected": expected.get("layoutKind"),
        "expected": len(wanted),
        "expectedSideAssets": expected_side_assets,
        "extracted": len(extracted),
        "sideItems": side_items,
        "found": found,
        "regionTruePositives": region_tp,
        "sideCorrect": side_ok,
        "identityCorrect": identity_ok,
        "misses": misses,
        "wrongSide": wrong_side,
        "wrongIdentity": wrong_identity,
        "distractorLeaks": leaks,
        "notIgnored": not_ignored,
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
    directory = dict(directory.get("players", directory))
    supplement = args.fixtures / SUPPLEMENT_NAME
    if supplement.is_file():
        directory.update(json.loads(supplement.read_text(encoding="utf-8"))["players"])
    ctx = IdentityContext.from_directory(directory, source=str(args.directory))

    per_fixture: dict[str, dict] = {}
    for d in sorted(p for p in args.fixtures.iterdir() if p.is_dir()):
        image, exp = _image_of(d), d / "expected.json"
        if image is None or not exp.is_file():
            continue
        expected = json.loads(exp.read_text(encoding="utf-8"))
        prepared = decode_image(image.read_bytes())
        out = extract_trade(prepared.png, engine=engine, identity_ctx=ctx, contract=board)
        per_fixture[d.name] = score_fixture(expected, out)

    keys = (
        "expected",
        "expectedSideAssets",
        "extracted",
        "sideItems",
        "found",
        "regionTruePositives",
        "sideCorrect",
        "identityCorrect",
    )
    tot = {k: sum(r[k] for r in per_fixture.values()) for k in keys}
    tot["distractorLeaks"] = sum(len(r["distractorLeaks"]) for r in per_fixture.values())
    summary = {
        "engine": avail.to_dict(),
        "fixtures": len(per_fixture),
        "tradeRegion": {
            "recall": _ratio(tot["regionTruePositives"], tot["expectedSideAssets"]),
            "precision": _ratio(tot["regionTruePositives"], tot["sideItems"]),
            "distractorLeaks": tot["distractorLeaks"],
            "layoutKindCorrect": sum(
                1 for r in per_fixture.values() if r["layoutKind"] == r["layoutExpected"]
            ),
        },
        "extraction": {
            "recall": _ratio(tot["found"], tot["expected"]),
            "precision": _ratio(tot["found"], tot["extracted"]),
        },
        "side": {"accuracyOfExtracted": _ratio(tot["sideCorrect"], tot["found"])},
        "identity": {
            "accuracyOfExtracted": _ratio(tot["identityCorrect"], tot["found"]),
            "endToEnd": _ratio(tot["identityCorrect"], tot["expected"]),
        },
        "totals": tot,
        "perFixture": per_fixture,
    }
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True))
        return 0
    print(f"screenshot-import eval — tesseract {avail.version} — {len(per_fixture)} fixtures")
    print(
        f"{'fixture':<26} {'layout':<11} {'exp':>4} {'items':>5} {'found':>5} "
        f"{'side':>5} {'ident':>5} {'leaks':>5}"
    )
    for name, r in per_fixture.items():
        print(
            f"{name:<26} {r['layoutKind']:<11} {r['expected']:>4} {r['extracted']:>5} "
            f"{r['found']:>5} {r['sideCorrect']:>5} {r['identityCorrect']:>5} "
            f"{len(r['distractorLeaks']):>5}"
        )
        for label, items in (
            ("missed", r["misses"]),
            ("wrong side", r["wrongSide"]),
            ("wrong identity", r["wrongIdentity"]),
            ("distractor leaked", r["distractorLeaks"]),
            ("not ignored", r["notIgnored"]),
        ):
            if items:
                print(f"    {label}: {', '.join(items)}")
    rg, ex = summary["tradeRegion"], summary["extraction"]
    sd, idn = summary["side"], summary["identity"]
    print(
        f"TRADE REGION  recall {rg['recall']}  precision {rg['precision']}  "
        f"distractor leaks {rg['distractorLeaks']}  "
        f"layout kind correct {rg['layoutKindCorrect']}/{len(per_fixture)}"
    )
    print(f"EXTRACTION    recall {ex['recall']}  precision {ex['precision']}")
    print(f"SIDE          accuracy of extracted {sd['accuracyOfExtracted']}")
    print(
        f"IDENTITY      accuracy of extracted {idn['accuracyOfExtracted']}  "
        f"end-to-end {idn['endToEnd']}"
    )
    print("(committed fixture set — not a universal accuracy claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
