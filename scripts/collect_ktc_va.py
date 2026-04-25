#!/usr/bin/env python3
"""Collect KTC trade Value Adjustment observations for formula calibration.

Reads trade shapes from ``scripts/ktc_va_fixture.json`` and writes
observations to ``scripts/ktc_va_observations.json``.  Each observation
captures the raw piece values (as KTC currently stamps them) and the
``Value Adjustment`` KTC itself reports — so the ratios stay
internally consistent even if KTC's absolute values drift later.

**Must be run locally**, not from the Claude Code sandbox — the
sandbox's egress proxy cannot negotiate TLS with keeptradecut.com
(see ``scripts/check_ktc_health.py`` for the known failure mode).

Typical workflow:
    pip install playwright
    playwright install chromium

    # Collect observations (idempotent — re-run to pick up new
    # fixture entries without recapturing already-captured trades).
    python scripts/collect_ktc_va.py

    # Commit the generated observations so the calibration script
    # running in CI / in the sandbox can see them.
    git add scripts/ktc_va_observations.json
    git commit -m "data: refresh KTC VA observations"

    # Refit the formula against the baseline 13 anchors + new
    # observations.  Pick the winning V6/V7 params and port into
    # frontend/lib/trade-logic.js.
    python scripts/calibrate_va_formula.py

Options:
    --fixture PATH     alternative fixture JSON
    --output PATH      alternative output JSON
    --headed           run with visible browser (debugging)
    --throttle-ms N    delay between trades (default 2500)
    --only LABEL[,...] restrict to specific fixture labels
    --refresh          recompute trades even if already captured
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURE = REPO_ROOT / "scripts" / "ktc_va_fixture.json"
# Output lives alongside the fixture (inside ``scripts/``) instead of
# the gitignored ``data/`` dir so the captured observations can be
# committed and used by ``calibrate_va_formula.py``.
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / "ktc_va_observations.json"

KTC_URL = "https://keeptradecut.com/trade-calculator"

# ── DOM selectors ──────────────────────────────────────────────────────
# These target the 2026-era KTC trade calculator layout.  If KTC
# redesigns, adjust these four and the rest of the script keeps working.
SEL_SEARCH_INPUT = 'input[placeholder="Search for a player"]'
SEL_PLAYER_ROW = 'div.single-player-result, li.player-result, .trade-calc-player'
SEL_VALUE_CELL = '.playerValue, .player-value, [class*="Value"]'
SEL_VA_ROW = 'text=Value Adjustment'
# The VA amount is typically in the same row — use a relative query.


def load_fixture(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Fixture at {path} must be a JSON array")
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"Fixture entry {i} is not an object")
        for key in ("label", "team1", "team2"):
            if key not in entry:
                raise ValueError(f"Fixture entry {i} missing '{key}'")
    return data


def load_existing(path: Path) -> dict[str, dict]:
    # File-doesn't-exist is the legitimate "fresh run" state — return
    # an empty dict quietly.  Anything else (bad JSON, wrong shape,
    # IO error) is real corruption: surface it so the run aborts
    # before the next save_observations() overwrites the file with a
    # tiny new dataset and permanently loses prior captures.
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    observations = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(observations, list):
        raise ValueError(
            f"{path}: expected an 'observations' list (or top-level array); "
            f"got {type(observations).__name__}"
        )
    return {o.get("label"): o for o in observations if isinstance(o, dict) and o.get("label")}


def save_observations(path: Path, observations: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "https://keeptradecut.com/trade-calculator",
        "observations": sorted(observations.values(), key=lambda o: o.get("label", "")),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def _parse_int(text: str) -> int | None:
    if text is None:
        return None
    m = re.search(r"-?\d[\d,]*", text)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return None


async def _add_player(page, team_idx: int, player_name: str, *, timeout: int = 15000) -> None:
    """Add a single player to team_idx (0 or 1) via the search input."""
    inputs = page.locator(SEL_SEARCH_INPUT)
    count = await inputs.count()
    if count <= team_idx:
        raise RuntimeError(
            f"KTC page shows {count} search inputs; expected at least {team_idx + 1}"
        )
    box = inputs.nth(team_idx)
    await box.click()
    await box.fill("")
    await box.type(player_name, delay=40)
    # KTC shows an autocomplete dropdown.  Prefer an exact-text match on
    # the dropdown item to avoid picking the wrong autocomplete hit.
    option = page.locator(
        f'xpath=//*[self::li or self::div or self::button]'
        f'[contains(@class, "result") or contains(@class, "option") or contains(@class, "suggest")]'
        f'[.//text()[contains(., "{player_name}")] or normalize-space()="{player_name}"]'
    ).first
    await option.wait_for(state="visible", timeout=timeout)
    await option.click()
    # Give KTC a moment to stamp the row and recompute VA.
    await page.wait_for_timeout(600)


async def _clear_team(page, team_idx: int) -> None:
    """Remove every player currently in team_idx's list."""
    # KTC uses an 'x' button per row.  We look inside the section for
    # team_idx and click remove buttons until no rows remain.
    for _ in range(20):  # safety cap
        close_buttons = page.locator(
            f'xpath=(//*[contains(@class, "trade-calc-team") or contains(@class, "team-section")])[{team_idx + 1}]'
            f'//button[contains(@class, "close") or contains(@class, "remove") or @aria-label="Remove"]'
        )
        remaining = await close_buttons.count()
        if remaining == 0:
            return
        await close_buttons.first.click()
        await page.wait_for_timeout(200)


async def _read_trade_state(page) -> dict:
    """Extract per-side player values and the KTC-reported VA."""
    # Grab every player's displayed value, split by team section.
    teams = page.locator(
        'xpath=//*[contains(@class, "trade-calc-team") or contains(@class, "team-section")]'
    )
    team_count = await teams.count()
    if team_count < 2:
        raise RuntimeError(f"Expected 2 team sections, found {team_count}")

    side_values: list[list[int]] = [[], []]
    for i in range(min(2, team_count)):
        cells = teams.nth(i).locator(SEL_VALUE_CELL)
        n = await cells.count()
        for j in range(n):
            txt = (await cells.nth(j).inner_text()).strip()
            v = _parse_int(txt)
            if v is not None and v > 0:
                side_values[i].append(v)

    # VA is usually displayed in a row labeled "Value Adjustment" on the
    # side receiving it.  Grab all text with that label and parse the
    # sibling cell for a signed integer.
    va_by_side: list[int] = [0, 0]
    for i in range(2):
        row = teams.nth(i).locator('xpath=.//*[contains(text(), "Value Adjustment")]/..')
        if await row.count() == 0:
            continue
        va_text = await row.first.inner_text()
        v = _parse_int(va_text)
        if v is not None:
            va_by_side[i] = v

    return {"sideValues": side_values, "valueAdjustments": va_by_side}


async def capture_trade(page, entry: dict) -> dict:
    """Navigate fresh, add both teams, capture the VA observation."""
    await page.goto(KTC_URL, wait_until="domcontentloaded", timeout=30000)
    # Let any blocking modals/banners dismiss on their own.
    await page.wait_for_timeout(800)
    # KTC sometimes retains prior state — do a belt-and-suspenders clear.
    await _clear_team(page, 0)
    await _clear_team(page, 1)

    for name in entry.get("team1", []):
        await _add_player(page, 0, name)
    for name in entry.get("team2", []):
        await _add_player(page, 1, name)

    # Settle for VA recompute.
    await page.wait_for_timeout(900)
    state = await _read_trade_state(page)

    return {
        "label": entry["label"],
        "topology": entry.get("topology", ""),
        "notes": entry.get("notes", ""),
        "team1Names": entry.get("team1", []),
        "team2Names": entry.get("team2", []),
        "team1Values": state["sideValues"][0],
        "team2Values": state["sideValues"][1],
        "valueAdjustmentTeam1": state["valueAdjustments"][0],
        "valueAdjustmentTeam2": state["valueAdjustments"][1],
        "capturedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


async def run(args: argparse.Namespace) -> int:
    fixture = load_fixture(Path(args.fixture))
    if args.only:
        whitelist = {s.strip() for s in args.only.split(",")}
        fixture = [e for e in fixture if e["label"] in whitelist]
        if not fixture:
            print(f"No fixture entries match --only={args.only}")
            return 2

    # Always load prior observations — even on --refresh.  The
    # refresh flag controls *which fixture entries get re-captured*,
    # not whether to discard everything we've already saved.  Combined
    # with --only the previous behaviour rewrote the file from scratch
    # with only the filtered subset, silently deleting every other
    # label.
    existing = load_existing(Path(args.output))
    pending = [e for e in fixture if args.refresh or e["label"] not in existing]
    print(f"Fixture: {len(fixture)} trades  |  already captured: {len(fixture) - len(pending)}")

    if not pending:
        print("Nothing to do.  Use --refresh to recapture.")
        return 0

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("FAIL: playwright not installed.  Run: pip install playwright && playwright install chromium")
        return 1

    failures: list[tuple[str, str]] = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not args.headed)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        for idx, entry in enumerate(pending):
            label = entry["label"]
            print(f"[{idx + 1}/{len(pending)}] {label} ({entry.get('topology', '?')})")
            try:
                obs = await capture_trade(page, entry)
            except Exception as e:
                msg = f"{type(e).__name__}: {str(e)[:160]}"
                print(f"    FAIL: {msg}")
                failures.append((label, msg))
                continue

            t1 = sum(obs["team1Values"])
            t2 = sum(obs["team2Values"])
            va1 = obs["valueAdjustmentTeam1"]
            va2 = obs["valueAdjustmentTeam2"]
            print(
                f"    team1={obs['team1Values']} (Σ={t1})  "
                f"team2={obs['team2Values']} (Σ={t2})  "
                f"VA=[{va1}, {va2}]"
            )
            existing[label] = obs
            save_observations(Path(args.output), existing)
            await page.wait_for_timeout(args.throttle_ms)

        await browser.close()

    print(f"\nWrote {len(existing)} observations to {args.output}")
    if failures:
        print(f"\n{len(failures)} of {len(pending)} captures FAILED:")
        for label, msg in failures:
            print(f"  - {label}: {msg}")
        # Surface a nonzero exit code so shell scripts / CI / pre-commit
        # hooks don't treat a partial run as success and let an
        # incomplete observation set propagate into calibration.
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--headed", action="store_true", help="run with visible browser")
    parser.add_argument("--throttle-ms", type=int, default=2500, help="delay between trades")
    parser.add_argument("--only", default="", help="comma-separated labels to capture (default: all)")
    parser.add_argument("--refresh", action="store_true", help="recompute even if observation exists")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
