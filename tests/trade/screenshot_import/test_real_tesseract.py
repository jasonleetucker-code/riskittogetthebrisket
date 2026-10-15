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

from .conftest import FIXTURES

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
    assert {"light_two_column", "dark_two_column", "stacked_mobile"} <= set(SCENARIOS)


@pytest.mark.parametrize("name", SCENARIOS)
def test_fixture_screenshot_reads_sides_and_assets(name, identity_ctx, board):
    d = FIXTURES / name
    expected = json.loads((d / "expected.json").read_text(encoding="utf-8"))
    prep, out = _extract((d / "image.png").read_bytes(), identity_ctx, board)
    assert out["engine"]["name"] == "tesseract" and out["engine"]["version"]
    assert out["layout"]["kind"] == expected["layoutKind"]
    assert [s["label"] for s in out["sides"]] == [s["label"] for s in expected["sides"]]
    for side, exp in zip(out["sides"], expected["sides"]):
        assert [it["boardName"] for it in side["items"]] == [a["boardName"] for a in exp["assets"]]
        assert [it["status"] for it in side["items"]] == [
            a.get("status", "resolved") for a in exp["assets"]
        ]
    assert out["unassigned"] == []
    ignored_text = " | ".join(ig["raw"] for ig in out["ignored"])
    for name_ in expected["mustBeIgnored"]:
        assert name_ in ignored_text
    if expected["mustBeIgnored"]:
        # Other-site values never become items.
        assert any(ig["reason"] == "value_number" for ig in out["ignored"])
    if name.startswith("dark"):
        assert prep.inverted is True


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
