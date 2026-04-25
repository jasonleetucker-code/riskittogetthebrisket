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
# These target the 2026-era KTC trade calculator layout.  KTC uses
# the easy-autocomplete jQuery plugin, with stable per-team IDs:
#
#   <input id="team-{one,two}-player-select">           — search box
#   <div id="eac-container-team-{one,two}-player-select">— dropdown
#     <ul style="display: {block,none}">
#       <li><div class="eac-item"><b>Player Name</b></div></li>
#     </ul>
#   <div id="team-{one,two}-player-list">              — added pieces
#   <div id="team-{one,two}-adjustment-block">         — VA, when nonzero
#   <div id="team-{one,two}-total">                    — sum of pieces
#
# If KTC redesigns, the per-team-id pattern is what to verify first —
# everything else falls out of it.
SEL_SEARCH_INPUT = "input.team-player-select"
SEL_VALUE_CELL = '.playerValue, .player-value, [class*="Value"]'
TEAM_WORDS = ("one", "two")  # KTC indexes teams as one/two, not 1/2 or 0/1


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


def _xpath_lit(s: str) -> str:
    """Encode a Python string as an XPath string literal safely.

    XPath has no escape syntax for quotes — strings must use one or the
    other.  ``Ja'Marr Chase`` (single quote) and ``"quoted"`` (double
    quotes) both need handling.  When the string contains both kinds,
    we splice it together with ``concat()``.
    """
    if "'" not in s:
        return f"'{s}'"
    if '"' not in s:
        return f'"{s}"'
    # Both kinds present: concat("foo", "'", "bar")
    parts = s.split("'")
    return "concat(" + ", \"'\", ".join(f"'{p}'" for p in parts) + ")"


async def _dump_debug_snapshot(page, tag: str) -> str:
    """Save a screenshot + page HTML for offline inspection.

    Returns the directory path so the caller can print it.  On any
    capture failure, returns the empty string and swallows — debug
    output should never mask the real error.
    """
    try:
        debug_dir = Path(__file__).resolve().parent / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        stem = f"{tag}_{ts}"
        await page.screenshot(path=str(debug_dir / f"{stem}.png"), full_page=True)
        html = await page.content()
        (debug_dir / f"{stem}.html").write_text(html, encoding="utf-8")
        return str(debug_dir)
    except Exception:
        return ""


def _safe_filename(s: str) -> str:
    """Make a string safe to embed in a debug filename (Windows-safe)."""
    return "".join(c if c.isalnum() else "_" for c in s)[:40]


async def _add_player(page, team_idx: int, player_name: str, *, timeout: int = 15000) -> None:
    """Add a single player to team_idx (0 or 1) via the search input.

    KTC uses the easy-autocomplete jQuery plugin.  After typing into
    ``#team-{one,two}-player-select``, the dropdown renders as:

        <div id="eac-container-team-one-player-select">
          <ul style="display: block;">         <!-- visible when results -->
            <li><div class="eac-item"><b>Player Name</b></div></li>
            ...
          </ul>
        </div>

    Click the <li> whose text matches the requested player.  After
    KTC stamps the row, verify it landed in
    ``#team-{one,two}-player-list``; if not, dump a debug snapshot
    rather than silently move on (the bug we just fixed).
    """
    if team_idx not in (0, 1):
        raise ValueError(f"team_idx must be 0 or 1, got {team_idx!r}")
    word = TEAM_WORDS[team_idx]
    input_id = f"team-{word}-player-select"
    container_id = f"eac-container-{input_id}"
    list_id = f"team-{word}-player-list"

    box = page.locator(f"#{input_id}")
    await box.wait_for(state="visible", timeout=5000)
    await box.click()
    await box.fill("")
    # Use type() (not fill) so jQuery's keyup-bound autocomplete fires.
    await box.type(player_name, delay=40)

    # Wait for the autocomplete dropdown <ul> to flip from
    # display:none to display:block, signalling KTC has results.
    visible_list = page.locator(f'#{container_id} ul[style*="display: block"]')
    try:
        await visible_list.wait_for(state="visible", timeout=timeout)
    except Exception:
        debug_path = await _dump_debug_snapshot(
            page, f"add_player_no_dropdown_team{team_idx}_{_safe_filename(player_name)}"
        )
        msg = f"autocomplete dropdown never appeared for {player_name!r} on team {team_idx}"
        if debug_path:
            msg += f" (debug snapshot: {debug_path})"
        raise RuntimeError(msg)

    # Click the <li> whose <b> text matches.  KTC sometimes shows
    # multiple suggestions for ambiguous searches; prefer exact match.
    items = visible_list.locator("li")
    n = await items.count()
    if n == 0:
        debug_path = await _dump_debug_snapshot(
            page, f"add_player_empty_dropdown_team{team_idx}_{_safe_filename(player_name)}"
        )
        msg = f"autocomplete dropdown is visible but has zero items for {player_name!r}"
        if debug_path:
            msg += f" (debug snapshot: {debug_path})"
        raise RuntimeError(msg)

    target = None
    for i in range(n):
        item = items.nth(i)
        text = (await item.inner_text()).strip()
        # Case-insensitive, whitespace-tolerant equality first; then containment.
        if text.lower() == player_name.lower() or player_name.lower() in text.lower():
            target = item
            break
    if target is None:
        # No textual match — likely the fixture has a name variant
        # (e.g. picks like "2026 Pick 1.09" can format slightly
        # differently in the dropdown).  Fall back to the first item
        # KTC ranked, but warn so the operator can verify.
        first_text = (await items.first.inner_text()).strip()
        print(
            f"    WARN: no exact match for {player_name!r} — "
            f"clicking first dropdown entry: {first_text!r}"
        )
        target = items.first

    await target.click()

    # Verify the player row landed in the team list.  This is the
    # check we should have had from day one — clicking the wrong
    # element succeeds silently otherwise (see bug history pre-#288).
    list_loc = page.locator(f"#{list_id}")
    try:
        # Wait up to 3s for at least one direct child to appear.
        await page.wait_for_function(
            f"document.querySelector('#{list_id}') && document.querySelector('#{list_id}').children.length > 0",
            timeout=3000,
        )
    except Exception:
        debug_path = await _dump_debug_snapshot(
            page, f"add_player_no_row_team{team_idx}_{_safe_filename(player_name)}"
        )
        msg = (
            f"clicked dropdown for {player_name!r} but no row appeared in #{list_id}"
        )
        if debug_path:
            msg += f" (debug snapshot: {debug_path})"
        raise RuntimeError(msg)

    # Settle: KTC recomputes totals + VA after each add.
    await page.wait_for_timeout(500)


async def _clear_team(page, team_idx: int) -> None:
    """Remove every player currently in team_idx's list.

    Player rows live inside ``#team-{one,two}-player-list``.  KTC
    renders a remove control per row — exact class isn't pinned by
    our debug snapshot (rows were empty), so we widen the locator to
    any clickable element with a "remove" / "close" / "×" affordance.
    """
    word = TEAM_WORDS[team_idx]
    list_id = f"team-{word}-player-list"
    for _ in range(20):  # safety cap against infinite loop
        close_buttons = page.locator(
            f'css=#{list_id} button, '
            f'css=#{list_id} [class*="remove"], '
            f'css=#{list_id} [class*="close"], '
            f'css=#{list_id} [aria-label="Remove"]'
        )
        remaining = await close_buttons.count()
        if remaining == 0:
            return
        try:
            await close_buttons.first.click(timeout=2000)
        except Exception:
            return  # row likely already removed by previous click
        await page.wait_for_timeout(200)


async def _read_trade_state(page) -> dict:
    """Extract per-side player values and the KTC-reported VA.

    Reads from KTC's stable per-team IDs:

      * ``#team-{word}-player-list``  — populated piece rows
      * ``#team-{word}-adjustment-block`` — VA, populated when nonzero
      * ``#team-{word}-total``  — sum of all piece values on this side

    Per-piece values inside the player list aren't pinned by stable
    IDs, so we scan the rendered text of each row for the largest
    integer in [100, 9999] (KTC's value scale).  If a row layout
    drifts in the future, this still works as long as the value stays
    visible.

    Dumps a debug snapshot if both sides come back empty so we can
    pin the per-row structure from a real populated state.
    """
    side_values: list[list[int]] = [[], []]
    va_by_side: list[int] = [0, 0]

    for i, word in enumerate(TEAM_WORDS):
        list_loc = page.locator(f"#team-{word}-player-list")
        if await list_loc.count() == 0:
            continue
        # Each direct child of the player list is one piece row.
        rows = list_loc.locator("xpath=./*")
        nrows = await rows.count()
        for j in range(nrows):
            row_text = (await rows.nth(j).inner_text()).strip()
            # Pick the largest integer in the row's text within KTC's
            # 0-9999 scale — that's the piece value.  Smaller numbers
            # like jersey #s, ages, or pick rounds get filtered.
            best = None
            for m in re.finditer(r"\d[\d,]*", row_text):
                v = _parse_int(m.group(0))
                if v is None:
                    continue
                if 100 <= v <= 9999 and (best is None or v > best):
                    best = v
            if best is not None:
                side_values[i].append(best)

        # Value Adjustment block: text content holds the VA when nonzero.
        adj_loc = page.locator(f"#team-{word}-adjustment-block")
        if await adj_loc.count() > 0:
            adj_text = (await adj_loc.inner_text()).strip()
            v = _parse_int(adj_text)
            if v is not None:
                va_by_side[i] = v

    if not side_values[0] and not side_values[1]:
        debug_path = await _dump_debug_snapshot(page, "read_state_no_pieces")
        msg = "_read_trade_state found no piece values on either side"
        if debug_path:
            msg += f" (debug snapshot: {debug_path})"
        raise RuntimeError(msg)

    return {"sideValues": side_values, "valueAdjustments": va_by_side}


async def _dismiss_blocking_modals(page) -> None:
    """Dismiss KTC overlays that cover the search inputs.

    Observed in the wild (2026-04):

    1. **"Your Thoughts?" rookie-ranking modal** — KTC crowdsources
       its values by asking each visitor to rank three random rookies
       Keep / Trade / Cut.  This modal pops on (effectively) every
       fresh navigation to /trade-calculator and sits on top of the
       trade pane, so the search inputs aren't reachable.  Click the
       opt-out link "I don't know all of these players" rather than
       submitting a fake vote — that would pollute KTC's crowd values
       (which we then scrape and rely on, so we'd be poisoning our
       own data).

    2. **Generic close-button fallback** — any other modal/popup with
       a standard "X" / aria-label="Close" button.  Best-effort.

    Both clicks are wrapped in try/except: if the modal isn't present
    (cookie remembered the dismissal, A/B variant, etc.) we silently
    move on.  We re-run this on every goto because each navigation
    can resurrect the prompt.
    """
    # 1. "Your Thoughts?" rookie ranking modal
    try:
        opt_out = page.get_by_text("I don't know all of these players", exact=False)
        if await opt_out.count() > 0:
            await opt_out.first.click(timeout=3000)
            await page.wait_for_timeout(400)
    except Exception:
        pass

    # 2. Generic close-button fallback for any other dialog
    try:
        close = page.locator(
            'xpath=//*[contains(@class, "modal") or contains(@class, "popup") or @role="dialog"]'
            '//button[contains(@class, "close") or @aria-label="Close" or normalize-space()="×"]'
        )
        if await close.count() > 0:
            await close.first.click(timeout=2000)
            await page.wait_for_timeout(300)
    except Exception:
        pass


async def capture_trade(page, entry: dict) -> dict:
    """Navigate fresh, add both teams, capture the VA observation."""
    await page.goto(KTC_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(800)
    # KTC's "Your Thoughts?" modal blocks the search inputs on every
    # fresh navigation — must be dismissed before we can interact.
    await _dismiss_blocking_modals(page)
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
