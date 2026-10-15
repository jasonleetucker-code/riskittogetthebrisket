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
* small screenshots are upscaled 2x (OCR accuracy falls off sharply below
  ~1000 px wide); anything over ``max_side`` on its longest edge is scaled
  down, so the OCR cost per request is bounded;
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
    longest = max(w, h) * scale
    if longest > max_side:
        scale = max_side / max(w, h)
    if scale != 1.0:
        new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)

    out = io.BytesIO()
    gray.save(out, format="PNG", optimize=False)
    return PreparedImage(
        png=out.getvalue(),
        width=gray.size[0],
        height=gray.size[1],
        inverted=inverted,
        scaled=round(scale, 4),
    )


def png_dimensions(png: bytes) -> tuple[int, int] | None:
    """``(width, height)`` from a PNG's IHDR chunk, without decoding."""
    if len(png) < 24 or not png.startswith(_PNG_MAGIC) or png[12:16] != b"IHDR":
        return None
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height
