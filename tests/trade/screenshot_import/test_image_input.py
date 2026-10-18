"""decode_image: allowlist, caps, bombs, EXIF, dark mode, metadata stripping."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from src.trade.screenshot_import.image_input import (
    ImageRejected,
    decode_image,
    png_dimensions,
    sniff_type,
)


def _encode(img: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, **kw)
    return buf.getvalue()


def _code(data: bytes, **kw) -> str:
    with pytest.raises(ImageRejected) as exc:
        decode_image(data, **kw)
    return exc.value.code


def test_png_jpeg_webp_are_accepted():
    img = Image.new("RGB", (1200, 600), (255, 255, 255))
    for fmt, kind in (("PNG", "png"), ("JPEG", "jpeg"), ("WEBP", "webp")):
        data = _encode(img, fmt)
        assert sniff_type(data) == kind
        prep = decode_image(data)
        assert prep.png.startswith(b"\x89PNG")
        # Long edge under 2400 px: upscaled to it (at most 2x) for OCR.
        assert (prep.width, prep.height) == (2400, 1200)
        assert png_dimensions(prep.png) == (2400, 1200)
        assert prep.scaled == 2.0


def test_other_formats_are_refused_even_though_pillow_decodes_them():
    img = Image.new("RGB", (50, 50), (255, 255, 255))
    assert _code(_encode(img, "GIF")) == "unsupported_type"
    assert _code(_encode(img, "BMP")) == "unsupported_type"
    assert _code(b"<svg xmlns='http://www.w3.org/2000/svg'/>") == "unsupported_type"


def test_empty_and_oversize_bytes():
    assert _code(b"") == "empty"
    assert _code(b"\x89PNG\r\n\x1a\n" + b"\0" * 3_000_001) == "too_large"
    assert _code(b"\x89PNG\r\n\x1a\n" + b"\0" * 2000, max_bytes=1000) == "too_large"


def test_truncated_or_garbage_with_valid_magic_is_malformed():
    data = _encode(Image.new("RGB", (800, 800), (10, 200, 30)), "PNG")
    assert _code(data[: len(data) // 2]) == "malformed"
    assert _code(b"\x89PNG\r\n\x1a\n" + b"garbage" * 50) == "malformed"
    assert _code(b"\xff\xd8\xff" + b"\x00" * 100) == "malformed"


@pytest.mark.filterwarnings("ignore::PIL.Image.DecompressionBombWarning")
def test_decompression_bomb_by_declared_dimensions():
    # 5000 x 5000 = 25 MP of a 1-bit image: a few KB on the wire.
    huge = _encode(Image.new("1", (5000, 5000), 1), "PNG")
    assert len(huge) < 200_000
    assert _code(huge) == "bomb"
    # Above our pixel cap but below Pillow's hard error: our header check.
    assert _code(_encode(Image.new("1", (4000, 3200), 1), "PNG")) == "bomb"


def test_exif_rotation_is_applied():
    img = Image.new("RGB", (1200, 400), (255, 255, 255))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW on display
    data = _encode(img, "JPEG", exif=exif.tobytes())
    prep = decode_image(data)
    assert (prep.width, prep.height) == (800, 2400)  # rotated, then 2x upscaled (<1000 wide)
    assert prep.scaled == 2.0
    assert b"Exif" not in prep.png and b"eXIf" not in prep.png


def test_dark_mode_is_inverted_and_light_is_not():
    dark = decode_image(_encode(Image.new("RGB", (1200, 600), (20, 22, 30)), "PNG"))
    light = decode_image(_encode(Image.new("RGB", (1200, 600), (250, 250, 250)), "PNG"))
    assert dark.inverted is True and light.inverted is False
    px = Image.open(io.BytesIO(dark.png)).getpixel((5, 5))
    assert px > 200  # dark background became light


def test_transparent_background_is_flattened_to_white():
    prep = decode_image(_encode(Image.new("RGBA", (1200, 600), (0, 0, 0, 0)), "PNG"))
    assert prep.inverted is False


def test_downscaled_desktop_screenshot_is_upscaled_to_the_ocr_long_edge():
    # The browser sends a full-page desktop screenshot at a 1600 px long edge.
    prep = decode_image(_encode(Image.new("RGB", (1600, 1000), (255, 255, 255)), "PNG"))
    assert (prep.width, prep.height) == (2400, 1500)
    assert prep.scaled == 1.5
    # Already large enough: untouched.
    prep = decode_image(_encode(Image.new("RGB", (2560, 1440), (255, 255, 255)), "PNG"))
    assert (prep.width, prep.height) == (2560, 1440) and prep.scaled == 1.0


def test_large_images_are_scaled_to_max_side():
    prep = decode_image(_encode(Image.new("L", (6000, 1000), 255), "PNG"))
    assert max(prep.width, prep.height) == 4096
    assert prep.scaled < 1.0


def test_png_dimensions_rejects_non_png():
    assert png_dimensions(b"not a png") is None
