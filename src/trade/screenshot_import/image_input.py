"""Validate and normalise an uploaded screenshot before OCR.

Defensive by construction — the bytes come from a user:

* a magic-byte ALLOWLIST (PNG / JPEG / WEBP).  A file that Pillow could
  decode but that is not one of those three is still refused: the decoder
  surface we expose is the surface we chose, not everything Pillow knows;
* a byte cap, and a PIXEL cap enforced from the header before any pixel is
  decoded (plus Pillow's own ``MAX_IMAGE_PIXELS`` decompression-bomb guard,
  set to the same bound);
* ``verify()`` for structural integrity, then a fresh ``open`` (``verify``
  leaves the image unusable by design);
* EXIF orientation applied, so a rotated phone photo reads upright;
* converted to grayscale; a dark-mode screenshot (mean luminance < 110) is
  inverted so the OCR engine sees dark text on a light background;
* LOCAL polarity normalisation: on a light page, light-on-dark PATCHES
  (dark header bars, dark sidebars, buttons, browser chrome) are replaced by
  a polarity-free local-contrast map, so their text reads as dark-on-light
  too.  Tesseract binarises globally: a dark bar becomes one solid blob with
  the letters as holes and no text line is ever found there (the per-line
  inversion retry only applies to lines that WERE found).  Measured on a
  real full-page trade-calculator screenshot, both side headers were
  invisible without this (see ``docs/ops/SCREENSHOT_IMPORT_RUNBOOK.md``);
* small screenshots are upscaled 2x (OCR accuracy falls off sharply below
  ~1000 px wide), and anything whose long edge is under 2400 px is upscaled
  to it (at most 2x); anything over ``max_side`` on its longest edge is
  scaled down, so the OCR cost per request is bounded;
* re-encoded as PNG, which drops every metadata chunk (EXIF, GPS, ICC).

Pillow is imported lazily: a server without it reports the feature as
unavailable rather than failing to import.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

DEFAULT_MAX_BYTES = 3_000_000
DEFAULT_MAX_PIXELS = 12_000_000
DEFAULT_MAX_SIDE = 4096
DARK_MEAN_LUMINANCE = 110
UPSCALE_BELOW_WIDTH = 1000
# A full-page DESKTOP screenshot arrives downscaled by the browser to a
# 1600 px long edge (``frontend/lib/image-downscale.js``), which leaves body
# text ~13 px tall — below what Tesseract reads reliably (measured on a real
# full-browser trade screenshot: side labels read "cets"/"aets" for "gets",
# names garbled, and the read took longer).  So an image whose long edge is
# under OCR_MIN_LONG_EDGE is upscaled to it (at most 2x); the same page then
# reads cleanly at every browser size measured (1280-2560 px wide).  2000 was
# measured too and lost an asset at 1280 px.  The 4096 px cap still bounds
# the cost (~3 s of OCR for a 2400 x 1500 page on one core).
OCR_MIN_LONG_EDGE = 2400

# Local polarity normalisation (see the module docstring).  All in OCR-pixel
# units, applied after scaling.  The page is summarised in POLARITY_BLOCK px
# cells; a cell's background is the median over POLARITY_MEDIAN x
# POLARITY_MEDIAN cells (wider than any text stroke, so text never decides
# its own background) and it is "dark" below POLARITY_DARK.  A dark PATCH is
# area, not a glyph: at least POLARITY_PATCH_DENSITY/255 of the cells within
# POLARITY_PATCH_RADIUS must be dark (the inside of a heavy, upscaled glyph
# is a few isolated cells and fails this).  Holes up to POLARITY_CLOSE cells
# (the text band inside a header bar) are closed.  The patch's outer band of
# POLARITY_EDGE cells is painted white — a dark/light boundary would
# otherwise read as a frame glued to the text next to it — and inside it
# light pixels become dark at POLARITY_GAIN x their lift over the patch's
# own background.  Chosen from a sweep over the real full-page and cropped
# trade screenshots plus every synthetic fixture: the header bars are read
# for POLARITY_CLOSE 9-11 and POLARITY_GAIN 2-4; the values sit inside that.
POLARITY_BLOCK = 4
POLARITY_MEDIAN = 7
POLARITY_DARK = 128
POLARITY_PATCH_RADIUS = 7
POLARITY_PATCH_DENSITY = 115
POLARITY_CLOSE = 9
POLARITY_EDGE = 3
POLARITY_GAIN = 3

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class ImageRejected(ValueError):
    """The upload is not an image we will read.  ``code`` is one of
    ``unsupported_type``, ``too_large``, ``malformed``, ``bomb``, ``empty``."""

    CODES = ("unsupported_type", "too_large", "malformed", "bomb", "empty")

    def __init__(self, code: str, detail: str = ""):
        if code not in self.CODES:
            raise ValueError(f"unknown ImageRejected code: {code!r}")
        super().__init__(detail or code)
        self.code = code


class ImagingUnavailable(RuntimeError):
    """Pillow is not installed on this server."""


@dataclass(frozen=True)
class PreparedImage:
    png: bytes
    width: int
    height: int
    inverted: bool
    scaled: float
    local_polarity: bool = False  # some dark patches were normalised


def sniff_type(data: bytes) -> str | None:
    """``"png"`` / ``"jpeg"`` / ``"webp"`` from the leading bytes, else None."""
    if data.startswith(_PNG_MAGIC):
        return "png"
    if data.startswith(_JPEG_MAGIC):
        return "jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


_PIL_FORMAT = {"png": "PNG", "jpeg": "JPEG", "webp": "WEBP"}


def pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401, PLC0415
    except Exception:  # noqa: BLE001
        return False
    return True


def _pil():
    try:
        from PIL import Image, ImageOps, ImageStat  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise ImagingUnavailable("Pillow is not installed") from exc
    # This package is the only Pillow consumer in the process; the guard is
    # the same bound as our own header check (Pillow warns above it and
    # raises DecompressionBombError above twice it).
    Image.MAX_IMAGE_PIXELS = DEFAULT_MAX_PIXELS
    return Image, ImageOps, ImageStat


def decode_image(
    data: bytes,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_side: int = DEFAULT_MAX_SIDE,
) -> PreparedImage:
    """Validate ``data`` and return an OCR-ready grayscale PNG.

    Raises :class:`ImageRejected` (with a code) for anything we refuse and
    :class:`ImagingUnavailable` when Pillow is missing.
    """
    if not data:
        raise ImageRejected("empty")
    if len(data) > max_bytes:
        raise ImageRejected("too_large", f"{len(data)} bytes > {max_bytes}")
    kind = sniff_type(data)
    if kind is None:
        raise ImageRejected("unsupported_type")

    Image, ImageOps, ImageStat = _pil()
    bomb_error = getattr(Image, "DecompressionBombError", None)
    caught: tuple[type[BaseException], ...] = (bomb_error,) if bomb_error else ()

    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format != _PIL_FORMAT[kind]:
                raise ImageRejected("unsupported_type", f"declared {kind}, decoded {probe.format}")
            width, height = probe.size
            if width <= 0 or height <= 0:
                raise ImageRejected("malformed", "zero dimension")
            if width * height > max_pixels:
                raise ImageRejected("bomb", f"{width}x{height} > {max_pixels} pixels")
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            if img.mode in ("RGBA", "LA", "P", "PA"):
                # Flatten transparency onto white before grayscale, so a
                # transparent background does not read as black.
                rgba = img.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
                bg.alpha_composite(rgba)
                img = bg
            gray = img.convert("L")
    except ImageRejected:
        raise
    except caught as exc:
        raise ImageRejected("bomb", type(exc).__name__) from exc
    except Exception as exc:  # noqa: BLE001 — any decoder failure is "malformed"
        raise ImageRejected("malformed", type(exc).__name__) from exc

    mean = float(ImageStat.Stat(gray).mean[0])
    inverted = mean < DARK_MEAN_LUMINANCE
    if inverted:
        gray = ImageOps.invert(gray)

    w, h = gray.size
    scale = 1.0
    if w < UPSCALE_BELOW_WIDTH:
        scale = 2.0
    elif max(w, h) < OCR_MIN_LONG_EDGE:
        scale = min(2.0, OCR_MIN_LONG_EDGE / max(w, h))
    longest = max(w, h) * scale
    if longest > max_side:
        scale = max_side / max(w, h)
    if scale != 1.0:
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)

    gray, local = normalize_local_polarity(gray)

    out = io.BytesIO()
    gray.save(out, format="PNG", optimize=False)
    return PreparedImage(
        png=out.getvalue(),
        width=gray.size[0],
        height=gray.size[1],
        inverted=inverted,
        scaled=round(scale, 4),
        local_polarity=local,
    )


def normalize_local_polarity(gray):
    """``(image, changed)``: every dark-background PATCH of a light grayscale
    page rewritten as dark-on-white.

    Inside a patch, a pixel becomes ``255 - gain * (pixel - background)``
    (its lift over the patch's own dark background), so light text on a dark
    bar reads like ordinary text; the patch's outer band is painted white so
    no dark frame sits against that text.  Outside every patch the image is
    left byte-identical, and a page with no patch is returned unchanged.

    Needs numpy (a declared dependency); without it the image is returned
    unchanged, which is the pre-normalisation behaviour, never a failure.
    """
    try:
        import numpy as np  # noqa: PLC0415
        from PIL import Image, ImageChops, ImageFilter  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        return gray, False
    w, h = gray.size
    sw, sh = max(1, w // POLARITY_BLOCK), max(1, h // POLARITY_BLOCK)
    small = gray.resize((sw, sh), Image.Resampling.BOX).filter(
        ImageFilter.MedianFilter(POLARITY_MEDIAN)
    )
    dark = small.point(lambda v: 255 if v < POLARITY_DARK else 0)
    dense = dark.filter(ImageFilter.BoxBlur(POLARITY_PATCH_RADIUS)).point(
        lambda v: 255 if v >= POLARITY_PATCH_DENSITY else 0
    )
    if dense.getbbox() is None:
        return gray, False
    reach = dense.filter(ImageFilter.MaxFilter(2 * POLARITY_PATCH_RADIUS + 1))
    patch = ImageChops.multiply(dark, reach)
    patch = patch.filter(ImageFilter.MaxFilter(POLARITY_CLOSE)).filter(
        ImageFilter.MinFilter(POLARITY_CLOSE)
    )
    inner_cells = patch.filter(ImageFilter.MinFilter(POLARITY_EDGE))
    if inner_cells.getbbox() is None:
        return gray, False
    outer_cells = patch.filter(ImageFilter.MaxFilter(POLARITY_EDGE))
    inner = np.asarray(inner_cells.resize((w, h), Image.Resampling.NEAREST)) > 0
    outer = np.asarray(outer_cells.resize((w, h), Image.Resampling.NEAREST)) > 0
    # The patch's own background: the darkest local median near each cell,
    # so the text band (lighter in the median) is measured against the bar.
    background = np.asarray(
        small.filter(ImageFilter.MinFilter(POLARITY_MEDIAN)).resize(
            (w, h), Image.Resampling.BILINEAR
        ),
        dtype=np.int16,
    )
    pixels = np.asarray(gray, dtype=np.int16)
    lifted = 255 - np.clip((pixels - background) * POLARITY_GAIN, 0, 255)
    out = np.where(inner, lifted, np.where(outer, 255, pixels)).astype(np.uint8)
    return Image.fromarray(out, mode="L"), True


def png_dimensions(png: bytes) -> tuple[int, int] | None:
    """``(width, height)`` from a PNG's IHDR chunk, without decoding."""
    if len(png) < 24 or not png.startswith(_PNG_MAGIC) or png[12:16] != b"IHDR":
        return None
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height
