"""Does the PARENT python process leak descriptors across Playwright cycles?

RESULT, 2026-08-12: NO.  Parent FDs return to baseline after every
cycle — normal, exception, and cancellation alike.

    baseline                       6  (pipe=2)
    mid-cycle, browser open        8  (pipe=4)   <- driver stdio pipes
    after close                    6  (pipe=2)
    after exception cycle x3       6  (pipe=2)
    after cancellation cycle x3    6  (pipe=2)
    11 cycles total                +0

The mid-cycle reading is why the flat line is trustworthy: it proves this
instrument CAN see Playwright's descriptors.  Without it, "6 forever"
would be indistinguishable from an instrument that sees nothing — the
same false-zero trap the fd_inventory readability guard exists for.

So `async with async_playwright()`'s __aexit__ reclaims the parent's
pipes even when control unwinds past `await browser.close()` — which it
does in `Dynasty Scraper.py`, where close() is the last statement of the
block rather than a finally.  A child Chromium orphan (the subject of
d7d4edff8) is a real and separate concern; it is not parent FD growth.

Not a CI gate: it needs a real browser and takes ~2 minutes.  Run by
hand if the lead is ever reopened.


Isolated local process. Never touches production, never runs the real
scraper. It reproduces only the lifecycle shape found in
`Dynasty Scraper.py`:

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(...)
        context = await browser.new_context(...)
        ...
        await browser.close()      # last statement, NOT a finally

The question is narrow and is the one the owner posed: a child Chromium
leak does not automatically explain FD growth in the FastAPI PARENT. So
measure the parent's own /proc/self/fd across repeated cycles, including
the paths that skip `close()`.
"""

from __future__ import annotations

import asyncio
import os
import sys
from collections import Counter

FD = f"/proc/{os.getpid()}/fd"


def snapshot() -> tuple[int, Counter]:
    kinds = Counter()
    total = 0
    for name in os.listdir(FD):
        try:
            tgt = os.readlink(os.path.join(FD, name))
        except OSError:
            continue
        total += 1
        if tgt.startswith("socket:"):
            kinds["socket"] += 1
        elif tgt.startswith("pipe:"):
            kinds["pipe"] += 1
        elif tgt.startswith("anon_inode:"):
            kinds["anon_inode"] += 1
        elif tgt.startswith("/dev/"):
            kinds["dev"] += 1
        else:
            kinds["file"] += 1
    return total, kinds


def report(label: str) -> int:
    total, kinds = snapshot()
    detail = " ".join(f"{k}={v}" for k, v in sorted(kinds.items()))
    print(f"  {label:<44} fds={total:<4} {detail}", flush=True)
    return total


async def cycle(mode: str) -> None:
    """One scrape-shaped browser cycle.

    mode:
      normal    launch -> context -> page -> close  (the happy path)
      raise     an exception between launch and close, so control unwinds
                past `await browser.close()` exactly as a mid-scrape
                failure would
      cancel    the task is cancelled mid-cycle — the 2-hourly scrape
                timeout path
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            executable_path="/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        )
        context = await browser.new_context(
            user_agent="probe", viewport={"width": 1280, "height": 900}
        )
        page = await context.new_page()
        await page.goto("about:blank")
        if mode == "normal" and os.environ.get("PROBE_MIDCYCLE"):
            # Sensitivity check.  A count that never moves could mean "no
            # leak" or "this instrument cannot see Playwright's
            # descriptors at all".  Measuring WITH the browser open
            # distinguishes them: if the number does not rise here, every
            # flat reading below is worthless.
            report("    >> MID-CYCLE (browser open)")
        if mode == "raise":
            raise RuntimeError("simulated mid-scrape failure")
        if mode == "cancel":
            await asyncio.sleep(3600)  # cancelled from outside
        await page.close()
        await browser.close()


async def main() -> int:
    print("Playwright parent-FD probe — isolated process, no production contact\n")
    base = report("baseline (before any playwright import)")

    print("\n-- normal cycles: launch -> context -> page -> close --")
    counts = []
    for i in range(1, 6):
        await cycle("normal")
        counts.append(report(f"after normal cycle {i}"))

    print("\n-- exception path: unwinds past `await browser.close()` --")
    for i in range(1, 4):
        try:
            await cycle("raise")
        except RuntimeError:
            pass
        counts.append(report(f"after exception cycle {i}"))

    print("\n-- cancellation path: the scrape-timeout shape --")
    for i in range(1, 4):
        task = asyncio.create_task(cycle("cancel"))
        await asyncio.sleep(4)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        counts.append(report(f"after cancelled cycle {i}"))

    await asyncio.sleep(2)
    final = report("\n  final, after settle")

    print("\n" + "=" * 72)
    steady = counts[2:6]  # ignore the first cycles' one-off driver setup
    print(f"baseline={base}  after-first-cycle={counts[0]}  final={final}")
    print(f"steady-state window across cycles 3..6: {steady}")
    growth = final - counts[0]
    print(f"growth after the first cycle: {growth:+d} fds over {len(counts)} cycles")
    verdict = "MONOTONIC GROWTH" if growth >= len(counts) else "NO MONOTONIC GROWTH"
    print(f"VERDICT: {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
