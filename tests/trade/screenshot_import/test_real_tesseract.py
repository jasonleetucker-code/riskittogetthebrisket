"""The REAL local tesseract binary over synthetic screenshots.

Marked ``tesseract``; skipped where the binary is not installed (CI runners
and production boxes without ``tesseract-ocr``).  The images are the
committed fixtures under ``tests/fixtures/screenshot_import/`` (regenerate
with ``python -m tests.trade.screenshot_import.synthetic``), plus one
rendered on the fly to prove the full decode -> OCR path on fresh bytes.
"""

from __future__ import annotations

import io
import json
import shutil

import pytest

from src.trade.screenshot_import.image_input import decode_image
from src.trade.screenshot_import.ocr import TesseractEngine
from src.trade.screenshot_import.service import extract_trade

from .conftest import FIXTURES, fixture_image

pytestmark = [
    pytest.mark.tesseract,
    pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed"),
]

SCENARIOS = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def _extract(png_bytes, identity_ctx, board):
    prep = decode_image(png_bytes)
    return prep, extract_trade(
        prep.png, engine=TesseractEngine(), identity_ctx=identity_ctx, contract=board
    )


def test_fixture_set_is_present():
    assert {
        "light_two_column",
        "dark_two_column",
        "stacked_mobile",
        "ktc_fullpage_browser",
        "ktc_cropped",
        "fullpage_desktop_multi",
        "fullpage_mobile_stacked",
        "fullpage_single_header",
        "fullpage_no_headers",
        "mobile390_light_picks_idp",
        "mobile390_dark_picks_idp",
        "mobile390_multishot_1",
        "mobile390_multishot_2",
    } <= set(SCENARIOS)


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_screenshot_reads_sides_and_assets(name, identity_ctx, board):
    d = FIXTURES / name
    expected = json.loads((d / "expected.json").read_text(encoding="utf-8"))
    prep, out = _extract(fixture_image(d).read_bytes(), identity_ctx, board)
    assert out["engine"]["name"] == "tesseract" and out["engine"]["version"]
    assert out["layout"]["kind"] == expected["layoutKind"]
    assert [s["label"] for s in out["sides"]] == [s["label"] for s in expected["sides"]]
    if "anchorSlots" in expected:
        assert [s["anchorSlot"] for s in out["sides"]] == expected["anchorSlots"]
    for side, exp in zip(out["sides"], expected["sides"]):
        assert [it["boardName"] for it in side["items"]] == [a["boardName"] for a in exp["assets"]]
        assert [it["status"] for it in side["items"]] == [
            a.get("status", "resolved") for a in exp["assets"]
        ]
    # EXACTLY the expected "needs a side" items: page noise never lands there.
    assert sorted(str(it["boardName"]) for it in out["unassigned"]) == sorted(
        str(a["boardName"]) for a in expected.get("unassigned", [])
    )
    ignored_text = " | ".join(ig["raw"] for ig in out["ignored"])
    for name_ in expected["mustBeIgnored"]:
        assert name_ in ignored_text
    if expected["mustBeIgnored"]:
        # Other-site values never become items.
        assert any(ig["reason"] == "value_number" for ig in out["ignored"])
    for warning in expected.get("requiredWarnings", []):
        assert warning in out["warnings"]
    for warning in expected.get("forbiddenWarnings", []):
        assert warning not in out["warnings"]
    if expected.get("expectInverted", name.startswith("dark")):
        assert prep.inverted is True


def _stable(payload: dict) -> dict:
    """What the client's merge depends on, without engine noise (conf)."""
    item = lambda it: (it["raw"], it["kind"], it["status"], it["boardName"], it["sleeperId"])  # noqa: E731
    return {
        "layout": payload["layout"]["kind"],
        "sides": [
            (
                s["label"],
                s["labelSource"],
                s["anchorFamily"],
                s["anchorSlot"],
                [item(i) for i in s["items"]],
            )
            for s in payload["sides"]
        ],
        "unassigned": [item(i) for i in payload["unassigned"]],
        "ignoredReasons": sorted({ig["reason"] for ig in payload["ignored"]}),
        "warnings": payload["warnings"],
    }


def test_recorded_multishot_extractions_match_a_fresh_read(identity_ctx, board):
    """The frontend replays the committed ``extraction.json`` of the
    owner-trade screenshot pair; a fresh real read must still agree with it
    on everything the merge uses (re-record with ``python -m
    tests.trade.screenshot_import.synthetic --record-extractions``)."""
    from .synthetic import RECORDED_EXTRACTIONS

    for index, name in enumerate(RECORDED_EXTRACTIONS):
        d = FIXTURES / name
        recorded = json.loads((d / "extraction.json").read_text(encoding="utf-8"))
        prep = decode_image(fixture_image(d).read_bytes())
        fresh = extract_trade(
            prep.png,
            engine=TesseractEngine(),
            identity_ctx=identity_ctx,
            contract=board,
            image_index=index,
        )
        assert recorded["imageIndex"] == index
        assert _stable(fresh) == _stable(recorded), name


def test_fresh_render_end_to_end(identity_ctx, board):
    from PIL import Image, ImageDraw

    from .synthetic import _font

    img = Image.new("RGB", (1240, 520), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    font = _font(30)
    for text, x, y in (
        ("They give", 60, 60),
        ("They get", 680, 60),
        ("Byron Young", 60, 140),
        ("Bijan Robinson", 680, 140),
        ("2027 Early 1st", 680, 210),
    ):
        draw.text((x, y), text, font=font, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    _prep, out = _extract(buf.getvalue(), identity_ctx, board)
    give, get = out["sides"]
    assert give["items"][0]["status"] == "needs_confirmation"  # two Byron Youngs
    assert {c["sleeperId"] for c in give["items"][0]["candidates"]} == {"10917", "10925"}
    assert [it["boardName"] for it in get["items"]] == ["Bijan Robinson", "2027 Early 1st"]


def test_real_fullpage_fixture_is_redacted():
    """The committed real screenshot is a REDACTED derivative: the browser
    tab strip and bookmark bar are solid fill, so OCR finds no text there."""
    from PIL import Image

    path = fixture_image(FIXTURES / "ktc_fullpage_browser")
    with Image.open(path) as img:
        assert img.size == (2000, 1250)
    prep = decode_image(path.read_bytes())
    words = TesseractEngine().read(prep.png, timeout_s=30)
    assert words, "the fixture must still OCR"
    blanked = [(0, 55), (115, 166)]  # tab strip, bookmark bar (fixture pixels)
    leaked = [
        w
        for w in words
        if any(top <= (w.top + w.bottom) / 2 / prep.scaled <= bottom for top, bottom in blanked)
    ]
    assert leaked == []


def test_unreadable_images_import_nothing(identity_ctx, board):
    """Noise and an illegibly blurred screenshot: no side, nothing resolved —
    or, for pure noise, an explicit OCR timeout (a 504 to the user), never
    an invented asset."""
    import random

    from PIL import Image, ImageFilter

    from src.trade.screenshot_import.ocr import OcrTimeout

    rnd = random.Random(7)
    noise = Image.new("L", (400, 300))
    noise.putdata([rnd.randrange(256) for _ in range(400 * 300)])
    with Image.open(fixture_image(FIXTURES / "light_two_column")) as src:
        blurred = src.convert("L").filter(ImageFilter.GaussianBlur(9))
    for img in (noise, blurred):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        try:
            _prep, out = _extract(buf.getvalue(), identity_ctx, board)
        except OcrTimeout:
            continue
        assert out["sides"] == []
        assert all(it["status"] != "resolved" for it in out["unassigned"])
