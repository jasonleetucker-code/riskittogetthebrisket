"""run_ocr: the single gateway — availability, busy, timeout, counters."""

from __future__ import annotations

import subprocess

import pytest

from src.trade.screenshot_import import ocr
from src.trade.screenshot_import.ocr import (
    FakeEngine,
    OcrBusy,
    OcrError,
    OcrTimeout,
    OcrUnavailable,
    TesseractEngine,
    Word,
    parse_tsv,
    run_ocr,
)

TSV = (
    "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    "1\t1\t0\t0\t0\t0\t0\t0\t1200\t700\t-1\t\n"
    "4\t1\t1\t1\t1\t0\t60\t45\t115\t27\t-1\t\n"
    "5\t1\t1\t1\t1\t1\t60\t46\t46\t20\t96.8\tYou\n"
    "5\t1\t1\t1\t1\t2\t119\t45\t56\t27\t96.5\tgive\n"
    "5\t1\t1\t1\t1\t3\t180\t45\t10\t27\t-1\t\n"
    "5\t1\t1\t1\t1\t4\t190\t45\t10\t27\t40\t \n"
)


@pytest.fixture(autouse=True)
def _reset():
    ocr.reset_counters_for_tests()
    ocr.clear_availability_cache()
    yield
    ocr.reset_counters_for_tests()
    ocr.clear_availability_cache()


def test_parse_tsv_keeps_only_word_rows():
    words = parse_tsv(TSV)
    assert [w.text for w in words] == ["You", "give"]
    assert words[0] == Word("You", 96.8, 60, 46, 46, 20)
    assert parse_tsv("") == [] and parse_tsv("garbage") == []


def test_ok_path_counts():
    words = [Word("Bijan", 95.0, 0, 0, 10, 10)]
    assert run_ocr(FakeEngine(words), b"png") == words
    c = ocr.ocr_counters()
    assert c["requests"] == 1 and c["ok"] == 1


def test_timeout():
    with pytest.raises(OcrTimeout):
        run_ocr(FakeEngine([], delay_s=0.2), b"png", timeout_s=0.05)
    assert ocr.ocr_counters()["timeout"] == 1


def test_unavailable_engine_is_refused_before_reading():
    eng = FakeEngine([], available=False, reason="tesseract_not_installed")
    with pytest.raises(OcrUnavailable) as exc:
        run_ocr(eng, b"png")
    assert exc.value.reason == "tesseract_not_installed"
    assert eng.calls == 0
    assert ocr.ocr_counters()["unavailable"] == 1


def test_missing_binary_is_an_explicit_unavailable_state(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda _name: None)
    avail = TesseractEngine().availability()
    assert avail.available is False
    assert avail.reason == "tesseract_not_installed"
    assert avail.engine == "tesseract" and avail.version is None
    with pytest.raises(OcrUnavailable):
        run_ocr(TesseractEngine(), b"png")


def test_busy_when_concurrency_slots_are_taken():
    taken = 0
    try:
        while ocr._semaphore.acquire(blocking=False):
            taken += 1
        assert taken == ocr.MAX_CONCURRENT
        with pytest.raises(OcrBusy):
            run_ocr(FakeEngine([]), b"png")
        assert ocr.ocr_counters()["busy"] == 1
    finally:
        for _ in range(taken):
            ocr._semaphore.release()
    # Slots come back after release (and after a failed read).
    with pytest.raises(OcrError):
        run_ocr(FakeEngine([], raises=RuntimeError("boom")), b"png")
    assert run_ocr(FakeEngine([]), b"png") == []
    assert ocr.ocr_counters()["error"] == 1


def test_tesseract_invocation_uses_stdin_stdout_and_one_thread(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, stdout=TSV.encode(), stderr=b"")

    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    words = TesseractEngine().read(b"PNGDATA", timeout_s=3.0)
    assert [w.text for w in words] == ["You", "give"]
    assert seen["cmd"][1:] == ["stdin", "stdout", "--psm", "11", "-l", "eng", "tsv"]
    assert seen["kw"]["input"] == b"PNGDATA"
    assert seen["kw"]["timeout"] == 3.0
    assert seen["kw"]["env"]["OMP_THREAD_LIMIT"] == "1"


def test_tesseract_subprocess_timeout_maps_to_ocr_timeout(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr.subprocess, "run", fake_run)
    with pytest.raises(OcrTimeout):
        TesseractEngine().read(b"x", timeout_s=0.1)


def test_tesseract_nonzero_exit_is_an_error(monkeypatch):
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")
    monkeypatch.setattr(
        ocr.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"bad"),
    )
    with pytest.raises(OcrError):
        TesseractEngine().read(b"x", timeout_s=1.0)


def test_availability_is_cached(monkeypatch):
    calls = []
    real = ocr._probe_tesseract

    def counting(path):
        calls.append(path)
        return real(path)

    monkeypatch.setattr(ocr, "_probe_tesseract", counting)
    eng = TesseractEngine()
    eng.availability()
    eng.availability()
    assert len(calls) == 1
