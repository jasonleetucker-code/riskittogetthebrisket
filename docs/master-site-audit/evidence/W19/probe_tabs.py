"""Probe every /league tab in a real browser with API request interception."""

import asyncio
import json
import os
import re

from playwright.async_api import async_playwright

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")

TABS = [
    "overview",
    "previews",
    "recaps",
    "power",
    "rosTeamStrength",
    "rosChampionship",
    "rosTradeDeadline",
    "luck",
    "streaks",
    "history",
    "rivalries",
    "awards",
    "records",
    "franchise",
    "activity",
    "draft",
    "weekly",
    "superlatives",
    "archives",
    "teamAssignment",
    "draft-capital",
]

OUT = "/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/tab-probe.json"


async def main() -> None:
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1200})

        async def route(r):
            u = r.request.url
            if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
                await r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
            else:
                await r.continue_()

        await ctx.route("**/*", route)
        for tab in TABS:
            page = await ctx.new_page()
            errs = []
            failed = []
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda rq: failed.append(rq.url))
            url = f"http://127.0.0.1:3000/league?tab={tab}"
            status = None
            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=45000)
                status = resp.status if resp else None
            except Exception as exc:  # noqa: BLE001
                errs.append(f"NAV:{exc}")
            await page.wait_for_timeout(1200)
            try:
                body = await page.inner_text("body")
            except Exception:  # noqa: BLE001
                body = ""
            html = await page.content()
            text = re.sub(r"\s+", " ", body).strip()
            results.append(
                {
                    "tab": tab,
                    "status": status,
                    "htmlBytes": len(html),
                    "textChars": len(text),
                    "tables": html.count("<table"),
                    "rows": html.count("<tr"),
                    "hasNoData": bool(
                        re.search(
                            r"no data|not available|nothing yet|coming soon|unavailable|"
                            r"couldn't load|failed to load|no results|empty",
                            text,
                            re.I,
                        )
                    ),
                    "consoleErrors": errs[:6],
                    "failedRequests": failed[:6],
                    "textHead": text[:900],
                }
            )
            await page.screenshot(
                path=f"/home/user/riskittogetthebrisket/docs/master-site-audit/evidence/W19/tab-{tab}.png",
                full_page=False,
            )
            await page.close()
        await browser.close()
    with open(OUT, "w") as fh:
        json.dump(results, fh, indent=1)
    for r in results:
        print(
            f"{r['tab']:20s} st={r['status']} html={r['htmlBytes']:8d} "
            f"text={r['textChars']:6d} rows={r['rows']:4d} nodata={r['hasNoData']} "
            f"errs={len(r['consoleErrors'])}"
        )


asyncio.run(main())
