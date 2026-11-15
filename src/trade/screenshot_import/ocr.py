"""OCR gateway: the local ``tesseract`` binary, behind ONE call site.

Owner decision: free local OCR through the tesseract BINARY — no paid API, no
new credentials, no ``pytesseract``.  Production cannot apt-install through
the deploy pipeline, so a missing binary is an explicit UNAVAILABLE state
(``Availability(available=False, reason=...)``), never a crash and never a
silent empty result — the same posture as ``scripts/fetch_clay_projections.py``
soft-skipping without ``pdftotext``.

:func:`run_ocr` is the single gateway every caller goes through.  It:

* refuses when the engine is unavailable (:class:`OcrUnavailable`);
* bounds concurrency with a process-wide semaphore acquired NON-blocking — a
  third concurrent image gets :class:`OcrBusy` immediately rather than
  queueing threads behind a CPU-bound subprocess;
* enforces a wall-clock timeout (:class:`OcrTimeout`);
* counts outcomes (``ocr_counters()``) — counts only, never text.

The PNG goes to tesseract on stdin and the TSV comes back on stdout: no temp
files, nothing written to disk, and the text read is never logged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Protocol, Sequence

ENGINE_NAME = "tesseract"
DEFAULT_TIMEOUT_S = 12.0
MAX_CONCURRENT = 2
_AVAILABILITY_TTL_S = 60.0


@dataclass(frozen=True)
class Word:
    text: str
    conf: float  # 0..100, as tesseract reports it
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str | None
    engine: str
    version: str | None

    def to_dict(self) -> dict:
        return {
            "available": self.available,
            "reason": self.reason,
            "engine": self.engine,
            "version": self.version,
        }


class OcrError(RuntimeError):
    """Base class for gateway refusals."""


class OcrUnavailable(OcrError):
    def __init__(self, reason: str | None):
        super().__init__(reason or "unavailable")
        self.reason = reason


class OcrTimeout(OcrError):
    pass


class OcrBusy(OcrError):
    pass


class OcrEngine(Protocol):
    name: str

    def availability(self) -> Availability: ...

    def read(self, png: bytes, *, timeout_s: float) -> list[Word]: ...


# ── TSV parsing ──────────────────────────────────────────────────────────


def parse_tsv(tsv: str) -> list[Word]:
    """Word rows (level 5) from tesseract's TSV output.  Rows with
    ``conf == -1`` or empty text are structural, not words, and are skipped."""
    words: list[Word] = []
    lines = tsv.splitlines()
    if not lines:
        return words
    header = lines[0].split("\t")
    try:
        idx = {name: header.index(name) for name in ("level", "left", "top", "width", "height")}
        idx["conf"] = header.index("conf")
        idx["text"] = header.index("text")
    except ValueError:
        return words
    for raw in lines[1:]:
        cols = raw.split("\t")
        if len(cols) <= idx["text"]:
            continue
        try:
            level = int(cols[idx["level"]])
            conf = float(cols[idx["conf"]])
            left = int(cols[idx["left"]])
            top = int(cols[idx["top"]])
            width = int(cols[idx["width"]])
            height = int(cols[idx["height"]])
        except ValueError:
            continue
        text = cols[idx["text"]].strip()
        if level != 5 or conf < 0 or not text:
            continue
        words.append(Word(text=text, conf=conf, left=left, top=top, width=width, height=height))
    return words


# ── Tesseract engine ─────────────────────────────────────────────────────

_availability_lock = threading.Lock()
_availability_cache: dict[str, tuple[float, Availability]] = {}


def _probe_tesseract(path_hint: str | None) -> Availability:
    binary = shutil.which(path_hint or "tesseract")
    if not binary:
        return Availability(False, "tesseract_not_installed", ENGINE_NAME, None)
    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            timeout=5.0,
            env=_subprocess_env(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Availability(False, "tesseract_not_runnable", ENGINE_NAME, None)
    if proc.returncode != 0:
        return Availability(False, "tesseract_not_runnable", ENGINE_NAME, None)
    out = (proc.stdout or b"").decode("utf-8", "replace") + (proc.stderr or b"").decode(
        "utf-8", "replace"
    )
    version = None
    for line in out.splitlines():
        line = line.strip()
        if line.lower().startswith("tesseract"):
            parts = line.split()
            if len(parts) >= 2:
                version = parts[1].lstrip("v")
            break
    return Availability(True, None, ENGINE_NAME, version)


def _subprocess_env() -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "OMP_THREAD_LIMIT": "1"}
    for key in ("TESSDATA_PREFIX", "LANG", "LC_ALL"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    return env


class TesseractEngine:
    """The local tesseract CLI.  ``--psm 11`` (sparse text): screenshots are
    not paragraphs, and layout is reconstructed from word boxes by
    :mod:`.layout` rather than trusted from the engine."""

    name = ENGINE_NAME

    def __init__(self, tesseract_path: str | None = None, *, lang: str = "eng"):
        self.tesseract_path = tesseract_path
        self.lang = lang

    def availability(self) -> Availability:
        key = self.tesseract_path or "tesseract"
        now = time.monotonic()
        with _availability_lock:
            hit = _availability_cache.get(key)
            if hit is not None and now - hit[0] < _AVAILABILITY_TTL_S:
                return hit[1]
        result = _probe_tesseract(self.tesseract_path)
        with _availability_lock:
            _availability_cache[key] = (now, result)
        return result

    def read(self, png: bytes, *, timeout_s: float) -> list[Word]:
        binary = shutil.which(self.tesseract_path or "tesseract")
        if not binary:
            raise OcrUnavailable("tesseract_not_installed")
        cmd = [binary, "stdin", "stdout", "--psm", "11", "-l", self.lang, "tsv"]
        try:
            proc = subprocess.run(
                cmd,
                input=png,
                capture_output=True,
                timeout=timeout_s,
                env=_subprocess_env(),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise OcrTimeout(f"tesseract exceeded {timeout_s}s") from exc
        except OSError as exc:
            raise OcrUnavailable("tesseract_not_runnable") from exc
        if proc.returncode != 0:
            # stderr may echo engine diagnostics; never the recognised text.
            raise OcrError(f"tesseract exited {proc.returncode}")
        return parse_tsv((proc.stdout or b"").decode("utf-8", "replace"))


def clear_availability_cache() -> None:
    with _availability_lock:
        _availability_cache.clear()


# ── Fake engine (tests) ──────────────────────────────────────────────────


class FakeEngine:
    """Deterministic engine for tests: returns ``words`` (or raises)."""

    name = ENGINE_NAME

    def __init__(
        self,
        words: Sequence[Word] = (),
        *,
        available: bool = True,
        reason: str | None = None,
        version: str | None = "fake",
        delay_s: float = 0.0,
        raises: BaseException | None = None,
    ):
        self.words = list(words)
        self._availability = Availability(
            available, None if available else (reason or "fake_unavailable"), ENGINE_NAME, version
        )
        self.delay_s = delay_s
        self.raises = raises
        self.calls = 0

    def availability(self) -> Availability:
        return self._availability

    def read(self, png: bytes, *, timeout_s: float) -> list[Word]:
        self.calls += 1
        if self.delay_s:
            if self.delay_s > timeout_s:
                time.sleep(timeout_s)
                raise OcrTimeout(f"fake engine exceeded {timeout_s}s")
            time.sleep(self.delay_s)
        if self.raises is not None:
            raise self.raises
        return list(self.words)


# ── The single gateway ───────────────────────────────────────────────────

_semaphore = threading.BoundedSemaphore(MAX_CONCURRENT)
_counter_lock = threading.Lock()
_COUNTER_KEYS = ("requests", "ok", "unavailable", "timeout", "busy", "error")
_counters: dict[str, int] = {k: 0 for k in _COUNTER_KEYS}


def _count(key: str) -> None:
    with _counter_lock:
        _counters[key] = _counters[key] + 1


def ocr_counters() -> dict[str, int]:
    with _counter_lock:
        return dict(_counters)


def reset_counters_for_tests() -> None:
    with _counter_lock:
        for k in _COUNTER_KEYS:
            _counters[k] = 0


def run_ocr(engine: OcrEngine, png: bytes, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[Word]:
    """Read ``png`` through ``engine``.  The ONLY call site for OCR.

    Raises :class:`OcrUnavailable`, :class:`OcrBusy`, :class:`OcrTimeout`
    or :class:`OcrError`; returns the recognised words otherwise.
    """
    _count("requests")
    avail = engine.availability()
    if not avail.available:
        _count("unavailable")
        raise OcrUnavailable(avail.reason)
    if not _semaphore.acquire(blocking=False):
        _count("busy")
        raise OcrBusy("ocr concurrency limit reached")
    try:
        words = engine.read(png, timeout_s=timeout_s)
    except OcrTimeout:
        _count("timeout")
        raise
    except OcrUnavailable:
        _count("unavailable")
        raise
    except Exception as exc:
        _count("error")
        if isinstance(exc, OcrError):
            raise
        raise OcrError(type(exc).__name__) from exc
    finally:
        _semaphore.release()
    _count("ok")
    return words
