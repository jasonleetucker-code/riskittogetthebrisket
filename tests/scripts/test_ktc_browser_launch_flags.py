"""Pin: the KTC/IDPTradeCalc Chromium launch must carry memory-mitigating flags.

THE INCIDENT
------------
Production (chaseupside.com) suffered a 9+ hour, repeating outage:
``/api/health``/``/api/status``/login all hit full TCP connection timeouts
(curl exit 28, 0 bytes -- not even a 502, meaning nothing was even
accepting connections) for 3+ minute stretches, always during
``current_step: source_start`` / ``Scraping KTC``. The server process then
restarted (a fresh ``trigger=startup`` scrape began seconds after the prior
one "completed"), and the pattern repeated.

Root cause: ``Dynasty Scraper.py``'s ``pw.chromium.launch(...)`` call
(inside ``run()``) had zero memory-mitigating launch args, rendering KTC's
heavy JS SPA with an unbounded RSS footprint. The whole ``server.py``
process shares ONE systemd cgroup (``deploy/systemd/dynasty.service.template``,
``MemoryMax=3G``) -- so a Chromium memory spike doesn't just crash the
browser, it can push the ENTIRE uvicorn process over the cgroup's hard
memory ceiling and get SIGKILLed outright by the kernel OOM killer. That
explains the total-unresponsiveness symptom (nginx got nothing back at all,
not a clean "connection refused") and, since a restart immediately begins a
fresh scrape that hits the same heavy KTC page again, the repeating crash
loop.

``--disable-dev-shm-usage`` is the standard, well-documented fix for
exactly this class of symptom: it makes Chromium use ``/tmp`` instead of a
(commonly small on a VPS) ``/dev/shm``, avoiding the memory/crash behavior
that triggers. ``--disable-gpu`` removes the GPU process/compositing
overhead a headless VPS never benefits from anyway.

This is a structural/contract test (source-text assertion, following the
house pattern in ``tests/scripts/test_fetcher_main_argv_contract.py``) --
no live browser or network needed -- so a future edit that reverts or
drops the flags fails fast and cheap.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRAPER_PY = REPO_ROOT / "Dynasty Scraper.py"


def _launch_call_source() -> str:
    src = SCRAPER_PY.read_text(encoding="utf-8")
    match = re.search(r"pw\.chromium\.launch\((.*?)\)\s*\n", src, re.DOTALL)
    assert match, "Dynasty Scraper.py no longer calls pw.chromium.launch(...)"
    return match.group(1)


def test_launch_passes_disable_dev_shm_usage() -> None:
    call_src = _launch_call_source()
    assert "--disable-dev-shm-usage" in call_src, (
        "pw.chromium.launch(...) dropped --disable-dev-shm-usage. This flag is "
        "the standard mitigation for Chromium's memory/crash behavior on hosts "
        "with a small /dev/shm -- removing it reopens the RSS-spike-to-OOM "
        "path that took production down for 9+ hours (see module docstring)."
    )


def test_launch_passes_disable_gpu() -> None:
    call_src = _launch_call_source()
    assert "--disable-gpu" in call_src, (
        "pw.chromium.launch(...) dropped --disable-gpu. No GPU exists on the "
        "production VPS; this flag avoids the GPU process's memory overhead "
        "for headless rendering."
    )


def test_launch_still_forwards_headless_and_proxy() -> None:
    """The memory-flag addition must not have displaced the existing args."""
    call_src = _launch_call_source()
    assert "headless=True" in call_src
    assert "proxy=_PLAYWRIGHT_PROXY" in call_src
