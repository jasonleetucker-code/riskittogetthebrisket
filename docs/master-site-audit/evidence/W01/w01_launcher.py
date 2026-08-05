from __future__ import annotations
import os
import sys

sys.path.insert(0, "/home/user/riskittogetthebrisket")
os.chdir("/home/user/riskittogetthebrisket")
import server  # noqa


async def _no_scrape(trigger: str = "manual"):
    print(f"[w01] SUPPRESSED scrape {trigger!r}", flush=True)
    return server.latest_data


server.run_scraper = _no_scrape
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("W01_PORT", "8001"))
    print(f"[w01] booting on 127.0.0.1:{port}", flush=True)
    uvicorn.run(server.app, host="127.0.0.1", port=port, log_level="warning")
