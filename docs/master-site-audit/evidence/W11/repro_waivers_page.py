"""W11 evidence — render /waivers in a real browser and read the FAAB hint column.

Follows AUDIT_PROTOCOL.md: pages come from Next on :3000, and only ``/api/*``
is re-routed to FastAPI on :8000 via request interception.  Read-only.

Mint the cookie first::

    SECRET=$(cat "$SCRATCH/e2e_secret.txt")
    curl -s -c /tmp/audit-cookies-W11.txt -X POST \
      http://127.0.0.1:8000/api/test/create-session -H "Authorization: Bearer $SECRET"

Then::

    .venv/bin/python docs/master-site-audit/evidence/W11/repro_waivers_page.py

Writes ``waivers-hint-by-filter.json`` beside this file.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
COOKIE_JAR = Path("/tmp/audit-cookies-W11.txt")
TEAM_PREFIX = "Jason"

READ_BEST_MOVES = """() => {
  const t = Array.from(document.querySelectorAll('table')).find(
    (x) => (x.querySelector('caption') || {}).textContent?.includes('add/drop upgrades'));
  if (!t) return null;
  return Array.from(t.querySelectorAll('tbody tr')).slice(0, 6).map(
    (r) => Array.from(r.querySelectorAll('td')).map((c) => c.innerText.replace(/\\n/g, ' | ').trim()));
}"""


def load_cookies() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for line in COOKIE_JAR.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if line.startswith("#") and "HttpOnly" not in line:
            continue
        parts = line.replace("#HttpOnly_", "").split("\t")
        if len(parts) >= 7:
            out.append(
                {"name": parts[5], "value": parts[6].strip(), "domain": "127.0.0.1", "path": "/"}
            )
    return out


async def run() -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1500, "height": 1200})
        await ctx.add_cookies(load_cookies())

        async def reroute(route: object) -> None:
            url = route.request.url  # type: ignore[attr-defined]
            if "/api/" in url and url.startswith("http://127.0.0.1:3000"):
                await route.continue_(  # type: ignore[attr-defined]
                    url=url.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000")
                )
            else:
                await route.continue_()  # type: ignore[attr-defined]

        await ctx.route("**/*", reroute)
        page = await ctx.new_page()
        await page.goto(
            "http://127.0.0.1:3000/waivers", wait_until="domcontentloaded", timeout=90000
        )
        await page.wait_for_timeout(14000)

        for button in await page.query_selector_all("button"):
            if "Pick your team" in ((await button.inner_text()) or ""):
                await button.click()
                break
        await page.wait_for_timeout(2500)
        for item in await page.query_selector_all("[role=option], [role=menuitem], li, button"):
            if ((await item.inner_text()) or "").strip().startswith(TEAM_PREFIX):
                await item.click()
                break
        await page.wait_for_timeout(9000)

        out: dict[str, object] = {"ALL": await page.evaluate(READ_BEST_MOVES)}
        for pos in ("QB", "RB", "TE"):
            await page.select_option("#waiver-pos", pos)
            await page.wait_for_timeout(3000)
            out[pos] = await page.evaluate(READ_BEST_MOVES)

        await page.screenshot(path=str(HERE / "waivers-page.png"), full_page=True)
        (HERE / "waivers-hint-by-filter.json").write_text(
            json.dumps(out, indent=1), encoding="utf-8"
        )
        print(json.dumps(out, indent=1))
        await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
