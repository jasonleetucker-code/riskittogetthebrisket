import json
import re
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

SCR = Path(
    "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad"
)
secret = (SCR / "e2e_secret.txt").read_text().strip()
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/test/create-session",
    method="POST",
    headers={"Authorization": f"Bearer {secret}"},
)
resp = urllib.request.urlopen(req)
raw = resp.headers.get_all("Set-Cookie") or []
cookies = []
for c in raw:
    nv = c.split(";")[0]
    n, _, v = nv.partition("=")
    cookies.append({"name": n.strip(), "value": v.strip(), "domain": "127.0.0.1", "path": "/"})
print("cookies", [c["name"] for c in cookies])

out = {}
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context()
    ctx.add_cookies(cookies)

    def route(r):
        u = r.request.url
        if "/api/" in u and u.startswith("http://127.0.0.1:3000"):
            r.continue_(url=u.replace("http://127.0.0.1:3000", "http://127.0.0.1:8000"))
        else:
            r.continue_()

    ctx.route("**/*", route)
    for path in ("/market/sharp-roster-percentage", "/market/sharp-tracker"):
        page = ctx.new_page()
        errs = []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        r = page.goto("http://127.0.0.1:3000" + path, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(2500)
        txt = page.evaluate("document.body.innerText")
        out[path] = {
            "status": r.status,
            "finalUrl": page.url,
            "consoleErrors": errs[:8],
            "h1": (page.locator("h1").first.text_content() if page.locator("h1").count() else None),
            "tableRows": page.locator("table tbody tr").count(),
            "bodyText": re.sub(r"\n{2,}", "\n", txt)[:4000],
        }
        page.close()
    b.close()
(SCR / "w15" / "pages.json").write_text(json.dumps(out, indent=2))
print(json.dumps(out, indent=2)[:7000])
