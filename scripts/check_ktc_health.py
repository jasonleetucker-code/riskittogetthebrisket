#!/usr/bin/env python3
"""KTC Health Check — verify KTC reachability and data extraction.

Run on production to confirm KTC is accessible before a full scrape.
Exits 0 if KTC is healthy, 1 if blocked.

Usage:
    python scripts/check_ktc_health.py          # quick connectivity test
    python scripts/check_ktc_health.py --full    # full extraction test (slower)
"""
import asyncio
import json
import os
import re
import sys

def _detect_proxy():
    from urllib.parse import urlparse
    raw = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or ""
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.hostname:
        return None
    proxy = {"server": f"http://{parsed.hostname}:{parsed.port or 3128}"}
    if parsed.username:
        proxy["username"] = parsed.username
    if parsed.password:
        proxy["password"] = parsed.password
    return proxy


async def check_ktc(full=False):
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("FAIL: playwright not installed")
        return False

    proxy = _detect_proxy()
    print(f"Proxy: {'configured' if proxy else 'none (direct)'}")

    async with async_playwright() as pw:
        launch_opts = {"headless": True}
        if proxy:
            launch_opts["proxy"] = proxy

        browser = await pw.chromium.launch(**launch_opts)
        ctx_opts = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 900},
        }
        if proxy:
            ctx_opts["ignore_https_errors"] = True
        context = await browser.new_context(**ctx_opts)
        page = await context.new_page()

        url = "https://keeptradecut.com/dynasty-rankings?sf=true&tep=2&filters=QB|WR|RB|TE|RDP"
        print(f"Loading: {url}")

        # Step 1: Can we reach KTC at all?
        try:
            resp = await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        except Exception as e:
            err = str(e).split("\n")[0][:100]
            print(f"FAIL: Navigation failed — {err}")
            if "Timeout" in err:
                print("BLOCKER: timeout (browser cannot reach KTC)")
            elif "ERR_CERT" in err:
                print("BLOCKER: tls_cert_error (proxy TLS interception issue)")
            await browser.close()
            return False

        status = resp.status if resp else None
        print(f"HTTP status: {status}")

        if status == 503:
            body = ""
            try:
                body = await page.inner_text("body")
            except Exception:
                pass
            if "TLS_error" in body or "TLSV1" in body:
                print("BLOCKER: proxy_tls_incompatible")
                print("  The egress proxy cannot negotiate TLS with keeptradecut.com.")
                print("  This site requires direct internet access (no MITM proxy).")
            elif "cloudflare" in body.lower() or "just a moment" in body.lower():
                print("BLOCKER: cloudflare_challenge")
                print("  KTC is serving a Cloudflare challenge page.")
            else:
                print(f"BLOCKER: http_503 — {body[:120]}")
            await browser.close()
            return False

        if status and status >= 400:
            print(f"BLOCKER: http_{status}")
            await browser.close()
            return False

        print(f"OK: KTC responded with status {status}")

        if not full:
            await browser.close()
            return True

        # Step 2: Full extraction test
        print("\n--- Full extraction test ---")
        await page.wait_for_timeout(3000)

        content = await page.content()
        print(f"Page content: {len(content)} bytes")

        # Strategy 1: Check for inline playersArray (current KTC format as of 2026-03)
        pa_match = re.search(
            r'var\s+playersArray\s*=\s*(\[.*?\]);\s*(?:var\s|\n)',
            content, re.DOTALL,
        )
        if pa_match:
            try:
                players = json.loads(pa_match.group(1))
                if isinstance(players, list) and len(players) > 100:
                    sample = players[0]
                    name = sample.get("playerName", "?")
                    sf_vals = sample.get("superflexValues", {})
                    val = sf_vals.get("value") if isinstance(sf_vals, dict) else sample.get("value")
                    print(f"playersArray: {len(players)} players")
                    print(f"  Sample keys: {list(sample.keys())[:8]}")
                    print(f"  Sample: {name} = {val}")
                    print(f"OK: KTC data extraction confirmed ({len(players)} players)")
                    await browser.close()
                    return True
                elif isinstance(players, list):
                    print(f"WARNING: playersArray has only {len(players)} players (expected 400+)")
            except json.JSONDecodeError as e:
                print(f"  playersArray JSON parse error: {e}")
        else:
            print("playersArray not found in page source")

        # Strategy 2: Check __NEXT_DATA__ (legacy KTC format)
        next_match = re.search(
            r'<script\s+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
            content, re.DOTALL,
        )
        if next_match:
            nd = next_match.group(1)
            pn_count = nd.count("playerName")
            sf_count = nd.count("superflexValues")
            print(f"__NEXT_DATA__: {len(nd)} bytes, playerName×{pn_count}, superflexValues×{sf_count}")

            try:
                data = json.loads(nd)
                players = (
                    data.get("props", {}).get("pageProps", {}).get("players", [])
                    or data.get("props", {}).get("pageProps", {}).get("rankings", [])
                )
                if players:
                    sample = players[0]
                    print(f"  Players array: {len(players)} items")
                    print(f"  Sample keys: {list(sample.keys())[:8]}")
                    name = sample.get("playerName", "?")
                    sf_vals = sample.get("superflexValues", {})
                    val = sf_vals.get("value") if isinstance(sf_vals, dict) else sample.get("value")
                    print(f"  Sample: {name} = {val}")
                    if len(players) > 100:
                        print(f"OK: KTC data extraction confirmed ({len(players)} players)")
                        await browser.close()
                        return True
                    else:
                        print(f"WARNING: Only {len(players)} players found (expected 400+)")
            except json.JSONDecodeError as e:
                print(f"  JSON parse error: {e}")
        else:
            print("__NEXT_DATA__ not found in page source")

        # Strategy 3: Check DOM elements
        dom_count = await page.evaluate(
            "document.querySelectorAll('[class*=\"player\"]').length"
        )
        print(f"DOM player elements: {dom_count}")

        if dom_count > 100:
            print(f"OK: KTC DOM rendering confirmed ({dom_count} elements)")
            await browser.close()
            return True

        # Strategy 4: Regex fallback — count playerName occurrences in source
        pn_count = content.count('"playerName"')
        if pn_count > 100:
            print(f"OK: KTC source contains {pn_count} playerName entries (regex-extractable)")
            await browser.close()
            return True

        print("WARNING: Could not extract sufficient player data")
        await browser.close()
        return False


if __name__ == "__main__":
    full = "--full" in sys.argv
    ok = asyncio.run(check_ktc(full=full))
    sys.exit(0 if ok else 1)
