"""Run only the IDPTradeCalc scraper, skipping all other sources.

Usage:
    python scripts/scrape_idptradecalc_only.py
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Point playwright at the pre-installed chromium when the expected revision
# is missing (common in CI/sandbox environments).
_CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
]
_PLAYWRIGHT_EXEC = next((p for p in _CHROMIUM_CANDIDATES if Path(p).exists()), None)


def _load_scraper():
    spec = importlib.util.spec_from_file_location(
        "dynasty_scraper",
        REPO / "Dynasty Scraper.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dynasty_scraper"] = mod
    spec.loader.exec_module(mod)
    return mod


def _patch_chromium_launch(mod):
    """Monkey-patch pw.chromium.launch() to inject executable_path."""
    if not _PLAYWRIGHT_EXEC:
        return

    import playwright.async_api as _pw_api
    _orig_async_playwright = _pw_api.async_playwright

    class _PatchedBrowserType:
        def __init__(self, real):
            self._real = real

        async def launch(self, **kwargs):
            if "executable_path" not in kwargs:
                kwargs["executable_path"] = _PLAYWRIGHT_EXEC
            return await self._real.launch(**kwargs)

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _PatchedPlaywright:
        def __init__(self, real):
            self._real = real
            self.chromium = _PatchedBrowserType(real.chromium)

        def __getattr__(self, name):
            return getattr(self._real, name)

    class _PatchedAsyncContextManager:
        def __init__(self, real_cm):
            self._real_cm = real_cm

        async def __aenter__(self):
            real = await self._real_cm.__aenter__()
            return _PatchedPlaywright(real)

        async def __aexit__(self, *args):
            return await self._real_cm.__aexit__(*args)

    def _patched_async_playwright():
        return _PatchedAsyncContextManager(_orig_async_playwright())

    # Patch in the scraper module's namespace
    mod.async_playwright = _patched_async_playwright
    # Also patch the global import in playwright itself so nested imports work
    _pw_api.async_playwright = _patched_async_playwright
    print(f"[scrape_idptradecalc_only] Patched chromium executable_path → {_PLAYWRIGHT_EXEC}")


def main():
    print("[scrape_idptradecalc_only] Loading Dynasty Scraper...")
    mod = _load_scraper()

    # Disable every source except IDPTradeCalc
    for key in list(mod.SITES.keys()):
        mod.SITES[key] = (key == "IDPTradeCalc")

    print(f"[scrape_idptradecalc_only] SITES = {mod.SITES}")

    _patch_chromium_launch(mod)

    print("[scrape_idptradecalc_only] Running scraper (IDPTradeCalc only)...")
    asyncio.run(mod.run())
    print("[scrape_idptradecalc_only] Done.")


if __name__ == "__main__":
    main()
