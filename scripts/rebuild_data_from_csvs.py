"""Rebuild dynasty_data JSON using only KTC and IDPTradeCalc as active sources.

Recovers from a partial scrape by pre-populating FULL_DATA with:
  - KTC          from exports/latest/site_raw/ktc.csv (name,value)
  - IDPTradeCalc raw trade values from the existing dynasty_data_*.json
    (idpTradeCalc.csv stores ordinal ranks, not dollar values, so we
    read the dollar values back from the JSON's players[name]["idpTradeCalc"])

All other sources are intentionally excluded (adding one source at a time).

Usage:
    python scripts/rebuild_data_from_csvs.py

Outputs:
    dynasty_data_YYYY-MM-DD.json  — rebuilt with KTC + IDPTradeCalc
    dynasty_data.js               — same
    exports/latest/...            — refreshed bundle
"""
from __future__ import annotations

import asyncio
import csv
import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITE_RAW_DIR = REPO / "exports" / "latest" / "site_raw"

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
    if not _PLAYWRIGHT_EXEC:
        return
    import playwright.async_api as _pw_api
    _orig = _pw_api.async_playwright

    class _BT:
        def __init__(self, r): self._r = r
        async def launch(self, **kw):
            kw.setdefault("executable_path", _PLAYWRIGHT_EXEC)
            return await self._r.launch(**kw)
        def __getattr__(self, n): return getattr(self._r, n)

    class _PW:
        def __init__(self, r):
            self._r = r
            self.chromium = _BT(r.chromium)
        def __getattr__(self, n): return getattr(self._r, n)

    class _CM:
        def __init__(self, cm): self._cm = cm
        async def __aenter__(self): return _PW(await self._cm.__aenter__())
        async def __aexit__(self, *a): return await self._cm.__aexit__(*a)

    def _patched(): return _CM(_orig())
    mod.async_playwright = _patched
    _pw_api.async_playwright = _patched
    print(f"[rebuild] Chromium → {_PLAYWRIGHT_EXEC}")


def _load_ktc(clean_fn) -> dict[str, float]:
    path = SITE_RAW_DIR / "ktc.csv"
    if not path.exists():
        print(f"[rebuild] WARNING: ktc.csv not found at {path}")
        return {}
    result = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            raw = row.get("value") or row.get("rank")
            if not name or raw is None:
                continue
            try:
                val = float(raw)
            except (ValueError, TypeError):
                continue
            cn = clean_fn(name)
            if cn:
                result[cn] = val
    print(f"[rebuild] KTC: {len(result)} players loaded from ktc.csv")
    return result


def _load_idptradecalc(clean_fn) -> dict[str, float]:
    """Read IDPTradeCalc dollar values from the existing dynasty JSON."""
    candidates = sorted(REPO.glob("dynasty_data_*.json"), reverse=True)
    if not candidates:
        print("[rebuild] WARNING: no dynasty_data_*.json found — IDPTradeCalc will be empty")
        return {}
    json_path = candidates[0]
    print(f"[rebuild] IDPTradeCalc: reading raw values from {json_path.name}")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    players = data.get("players", {})
    result = {}
    for name, pdata in players.items():
        if not isinstance(pdata, dict):
            continue
        val = pdata.get("idpTradeCalc")
        if val is None:
            continue
        try:
            fval = float(val)
        except (ValueError, TypeError):
            continue
        if fval > 0:
            cn = clean_fn(name)
            if cn:
                result[cn] = fval
    print(f"[rebuild] IDPTradeCalc: {len(result)} players loaded from JSON")
    return result


def main():
    print("[rebuild] Loading Dynasty Scraper...")
    mod = _load_scraper()

    # Only KTC + IDPTradeCalc — adding sources one at a time
    ktc_data = _load_ktc(mod.clean_name)
    idptc_data = _load_idptradecalc(mod.clean_name)

    mod.FULL_DATA["KTC"] = ktc_data
    mod.FULL_DATA["IDPTradeCalc"] = idptc_data

    # Disable all live scraping
    for k in mod.SITES:
        mod.SITES[k] = False
    print(f"[rebuild] All SITES disabled — using pre-loaded FULL_DATA only")
    print(f"[rebuild] Active sources: KTC ({len(ktc_data)}), IDPTradeCalc ({len(idptc_data)})")

    _patch_chromium_launch(mod)

    print("[rebuild] Running pipeline (no live scraping)...")
    asyncio.run(mod.run())
    print("[rebuild] Done.")


if __name__ == "__main__":
    main()
