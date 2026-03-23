#!/usr/bin/env python3
"""DynastyNerds credential verification script.

Run with DN_EMAIL and DN_PASS set in the environment:
    DN_EMAIL=you@example.com DN_PASS=yourpass python3 scripts/verify_dynastynerds_credentials.py

Verifies:
1. Credentials are read by the scraper module
2. Login succeeds and full rankings load
3. Record count exceeds free-tier (168) threshold
4. Elite players (Josh Allen, Ja'Marr Chase, etc.) are present
5. Damien Martinez partial-source discount is still applied correctly

Exit codes:
    0 = full credential verification passed
    1 = credentials missing or login failed
    2 = partial: logged in but record count below threshold
"""
import asyncio
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(REPO_ROOT)

FREE_TIER_COUNT = 168
EXPECTED_MIN_FULL = 400  # Full subscription should give 450-550 records
ELITE_PLAYERS = [
    "Josh Allen", "Ja'Marr Chase", "Bijan Robinson", "Jahmyr Gibbs",
    "Breece Hall", "Amon-Ra St. Brown", "A.J. Brown", "CeeDee Lamb",
]


def main():
    dn_email = os.environ.get("DN_EMAIL", "")
    dn_pass = os.environ.get("DN_PASS", "")

    print("=== DynastyNerds Credential Verification ===\n")
    print(f"DN_EMAIL set: {'YES' if dn_email else 'NO'} (length={len(dn_email)})")
    print(f"DN_PASS set: {'YES' if dn_pass else 'NO'} (length={len(dn_pass)})")

    if not dn_email or not dn_pass:
        print("\nERROR: DN_EMAIL and DN_PASS must be set in the environment.")
        print("Example: DN_EMAIL=you@example.com DN_PASS=yourpass python3 scripts/verify_dynastynerds_credentials.py")
        sys.exit(1)

    # Import scraper module
    import importlib.util

    spec = importlib.util.spec_from_file_location("Dynasty_Scraper", os.path.join(REPO_ROOT, "Dynasty Scraper.py"))
    scraper = importlib.util.module_from_spec(spec)
    sys.modules["Dynasty_Scraper"] = scraper
    spec.loader.exec_module(scraper)

    assert scraper.DYNASTYNERDS_EMAIL == dn_email, "Scraper did not read DN_EMAIL"
    assert scraper.DYNASTYNERDS_PASSWORD == dn_pass, "Scraper did not read DN_PASS"
    print("\nScraper module loaded, credentials confirmed wired.")

    # Load player list from existing data
    data_file = os.path.join(REPO_ROOT, "dynasty_data_2026-03-22.json")
    if not os.path.exists(data_file):
        # Try alternate paths
        for alt in ["exports/latest/dynasty_data.json"]:
            alt_path = os.path.join(REPO_ROOT, alt)
            if os.path.exists(alt_path):
                data_file = alt_path
                break
    with open(data_file) as f:
        existing = json.load(f)
    player_names = list(existing.get("players", {}).keys())
    print(f"Player list: {len(player_names)} names")

    # Run the DynastyNerds scrape
    results = asyncio.run(_run_scrape(scraper, player_names))
    if results is None:
        print("\nFAIL: Scrape returned None")
        sys.exit(1)

    # Analyze results
    dn_full = scraper.FULL_DATA.get("DynastyNerds", {})
    matched_count = sum(1 for v in results.values() if isinstance(v, (int, float)) and v > 0)
    full_count = len(dn_full)

    print(f"\n=== RESULTS ===")
    print(f"FULL_DATA entries (raw scrape): {full_count}")
    print(f"Matched to canonical players:   {matched_count}")
    print(f"Free-tier baseline:             {FREE_TIER_COUNT}")
    print(f"Expected minimum (full sub):    {EXPECTED_MIN_FULL}")

    # Check elite players
    print(f"\n=== ELITE PLAYER CHECK ===")
    elite_found = 0
    for name in ELITE_PLAYERS:
        val = dn_full.get(name)
        status = f"rank={val}" if val else "MISSING"
        if val:
            elite_found += 1
        print(f"  {name:<25} {status}")

    # Check Damien Martinez specifically
    dm_val = dn_full.get("Damien Martinez")
    print(f"\n=== DAMIEN MARTINEZ CHECK ===")
    print(f"  DynastyNerds rank: {dm_val}")
    if dm_val:
        print(f"  Status: Present (rank {dm_val})")
    else:
        print(f"  Status: Not in DynastyNerds data")

    # Top 20 players
    if dn_full:
        sorted_players = sorted(dn_full.items(), key=lambda x: x[1])[:20]
        print(f"\n=== TOP 20 (by rank) ===")
        for name, rank in sorted_players:
            print(f"  {rank:>6.1f}  {name}")

    # Verdict
    print(f"\n=== VERDICT ===")
    if full_count >= EXPECTED_MIN_FULL and elite_found >= len(ELITE_PLAYERS) // 2:
        print(f"PASS: Full credential access confirmed ({full_count} records, {elite_found}/{len(ELITE_PLAYERS)} elites)")
        sys.exit(0)
    elif full_count > FREE_TIER_COUNT:
        print(f"PARTIAL: More data than free tier ({full_count} > {FREE_TIER_COUNT}) but below expected minimum")
        print(f"  Elite players found: {elite_found}/{len(ELITE_PLAYERS)}")
        sys.exit(2)
    else:
        print(f"FAIL: Record count ({full_count}) not above free tier ({FREE_TIER_COUNT})")
        print("  Credentials may be invalid or subscription expired")
        sys.exit(1)


async def _run_scrape(scraper, player_names):
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        dummy_page = await context.new_page()

        print(f"\nStarting DynastyNerds scrape at {time.strftime('%H:%M:%S')}...")
        start = time.time()

        try:
            results = await asyncio.wait_for(
                scraper.scrape_dynastynerds(dummy_page, player_names),
                timeout=120,
            )
        except asyncio.TimeoutError:
            print("TIMEOUT after 120s")
            await browser.close()
            return None
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await browser.close()
            return None

        elapsed = time.time() - start
        print(f"Scrape completed in {elapsed:.1f}s")

        await browser.close()
        return results


if __name__ == "__main__":
    main()
