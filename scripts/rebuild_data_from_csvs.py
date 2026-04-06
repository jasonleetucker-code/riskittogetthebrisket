"""Rebuild dynasty_data_YYYY-MM-DD.json from preserved site_raw CSVs.

This script recovers from a partial scrape (e.g., IDPTradeCalc-only run that
overwrote the main JSON) by re-populating FULL_DATA from the per-site CSVs in
exports/latest/site_raw/, then re-running the scraper pipeline in no-scrape
mode so it rebuilds composites, picks, and the full JSON output.

IDPTradeCalc raw values are recovered from the existing dynasty JSON (not from
idpTradeCalc.csv, which stores ordinal ranks, not dollar values).

Usage:
    python scripts/rebuild_data_from_csvs.py
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

# ── CSV file → scraper FULL_DATA key mapping ────────────────────────────────
CSV_TO_SCRAPER_KEY = {
    "ktc.csv":             "KTC",
    "fantasyCalc.csv":     "FantasyCalc",
    "dynastyDaddy.csv":    "DynastyDaddy",
    "fantasyPros.csv":     "FantasyPros",
    "draftSharks.csv":     "DraftSharks",
    "yahoo.csv":           "Yahoo",
    "dynastyNerds.csv":    "DynastyNerds",
    "dlfSf.csv":           "DLF_SF",
    "dlfIdp.csv":          "DLF_IDP",
    "dlfRsf.csv":          "DLF_RSF",
    "dlfRidp.csv":         "DLF_RIDP",
    "pffIdp.csv":          "PFF_IDP",
    "draftSharksIdp.csv":  "DraftSharks_IDP",
    "fantasyProsIdp.csv":  "FantasyPros_IDP",
    # idpTradeCalc.csv stores ordinal ranks, not dollar values — handled separately
}

# ── Chromium path patching (same as scrape_idptradecalc_only.py) ─────────────
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

    mod.async_playwright = _patched_async_playwright
    _pw_api.async_playwright = _patched_async_playwright
    print(f"[rebuild] Patched chromium executable_path → {_PLAYWRIGHT_EXEC}")


def _load_csv_values(csv_path: Path, clean_name_fn) -> dict[str, float]:
    """Read a name,value CSV and return {cleaned_name: float(value)}."""
    result: dict[str, float] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = row.get("name", "").strip()
            raw_val = row.get("value") or row.get("rank")
            if not name or raw_val is None:
                continue
            try:
                val = float(raw_val)
            except (ValueError, TypeError):
                continue
            cleaned = clean_name_fn(name)
            if cleaned:
                result[cleaned] = val
    return result


def _load_idptradecalc_from_json(json_path: Path, clean_name_fn) -> dict[str, float]:
    """Extract IDPTradeCalc raw values from an existing dynasty JSON output.

    The idpTradeCalc.csv stores ordinal RANKS (lower=better), not dollar values.
    The actual raw trade values are in dynasty_data JSON: players[name]["idpTradeCalc"].
    """
    if not json_path.exists():
        print(f"[rebuild] WARNING: {json_path} not found — IDPTradeCalc will be empty")
        return {}

    with open(json_path, encoding="utf-8") as fh:
        data = json.load(fh)

    players = data.get("players", {})
    result: dict[str, float] = {}
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
            cleaned = clean_name_fn(name)
            if cleaned:
                result[cleaned] = fval
    return result


def _find_dynasty_json(repo: Path) -> Path | None:
    """Find the most recent dynasty_data_*.json in the repo root."""
    candidates = sorted(repo.glob("dynasty_data_*.json"), reverse=True)
    return candidates[0] if candidates else None


def main():
    print("[rebuild] Loading Dynasty Scraper module...")
    mod = _load_scraper()

    clean = mod.clean_name  # name normalisation function

    # ── Load per-site CSVs into FULL_DATA ────────────────────────────────────
    loaded_summary: list[tuple[str, int]] = []

    for csv_filename, scraper_key in CSV_TO_SCRAPER_KEY.items():
        csv_path = SITE_RAW_DIR / csv_filename
        if not csv_path.exists():
            print(f"[rebuild] SKIP {csv_filename} — file not found")
            continue
        values = _load_csv_values(csv_path, clean)
        mod.FULL_DATA[scraper_key] = values
        loaded_summary.append((scraper_key, len(values)))
        print(f"[rebuild] Loaded {len(values):>4} players  ← {csv_filename} → FULL_DATA['{scraper_key}']")

    # ── Load IDPTradeCalc from existing dynasty JSON (not from CSV) ───────────
    dynasty_json = _find_dynasty_json(REPO)
    if dynasty_json:
        print(f"[rebuild] Loading IDPTradeCalc raw values from {dynasty_json.name}...")
        idp_values = _load_idptradecalc_from_json(dynasty_json, clean)
        mod.FULL_DATA["IDPTradeCalc"] = idp_values
        loaded_summary.append(("IDPTradeCalc", len(idp_values)))
        print(f"[rebuild] Loaded {len(idp_values):>4} players  ← {dynasty_json.name} → FULL_DATA['IDPTradeCalc']")
    else:
        print("[rebuild] WARNING: No dynasty JSON found — IDPTradeCalc will be empty")

    # ── Disable all live scraping ─────────────────────────────────────────────
    for k in mod.SITES:
        mod.SITES[k] = False
    print(f"[rebuild] All SITES disabled (no live scraping): {list(mod.SITES.keys())}")

    # ── Clear stale Sleeper positions so run() resolves them fresh ─────────────
    # The existing SLEEPER_ROSTER_DATA["positions"] may have wrong positions from
    # a previous partial run (e.g. "Josh Allen" → "G" instead of "QB").  Clearing
    # it forces _resolve_sleeper_identity() to pick the best candidate from
    # SLEEPER_ALL_NFL using search_rank, which correctly prefers the QB.
    if isinstance(mod.SLEEPER_ROSTER_DATA.get("positions"), dict):
        mod.SLEEPER_ROSTER_DATA["positions"].clear()
        print("[rebuild] Cleared stale SLEEPER_ROSTER_DATA['positions'] — will resolve fresh")

    # ── Apply chromium patch (needed even with no scraping, for Playwright init) ─
    _patch_chromium_launch(mod)

    # ── Summary ──────────────────────────────────────────────────────────────
    print("\n[rebuild] Source load summary:")
    print(f"  {'Source':<20} {'Players':>7}")
    print(f"  {'-'*20} {'-'*7}")
    for key, count in loaded_summary:
        print(f"  {key:<20} {count:>7}")
    total_unique = len({n for m in mod.FULL_DATA.values() for n in m})
    print(f"  {'TOTAL UNIQUE NAMES':<20} {total_unique:>7}")

    # ── Run the scraper pipeline (no-scrape mode: uses pre-populated FULL_DATA) ─
    print("\n[rebuild] Running scraper pipeline (data assembly only)...")
    asyncio.run(mod.run())
    print("[rebuild] Done.")


if __name__ == "__main__":
    main()
