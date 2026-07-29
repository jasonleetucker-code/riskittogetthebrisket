/**
 * ServerStatusPanel — scraper/runtime status plus a manual scrape trigger.
 *
 * Moved out of /settings.  It lived there as a section called
 * "Data & Admin", between the watchlist and guest passes, on a page
 * every signed-in user opens to change their TEP setting — an operator
 * surface filed under preferences.  /admin is where the rest of the
 * operator tooling is, and where the server already enforces the
 * allowlist.
 */
"use client";

import { useCallback, useEffect, useState } from "react";

export default function ServerStatusPanel() {
  const [status, setStatus] = useState(null);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/status");
      if (res.ok) setStatus(await res.json());
      else setStatus({ error: `HTTP ${res.status}` });
    } catch {
      setStatus({ error: "Backend unreachable" });
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  async function triggerScrape() {
    setScraping(true);
    setScrapeMsg("");
    try {
      const res = await fetch("/api/scrape", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      setScrapeMsg(
        data.error
          ? `Error: ${data.error}`
          : "Refresh triggered. Data will update shortly.",
      );
      setTimeout(fetchStatus, 5000);
    } catch {
      setScrapeMsg("Failed to reach backend.");
    } finally {
      setScraping(false);
    }
  }

  const connected = status && !status.error;

  return (
    <div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 10,
        }}
      >
        <span
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: connected ? "var(--green)" : "var(--red)",
            display: "inline-block",
          }}
        />
        <span style={{ fontSize: "0.82rem", fontWeight: 600 }}>
          {connected ? "Backend Connected" : "Backend Offline"}
        </span>
      </div>

      {connected && (
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--subtext)",
            marginBottom: 10,
          }}
        >
          {status.player_count != null && (
            <div>Players: {status.player_count}</div>
          )}
          {status.last_scrape && <div>Last update: {status.last_scrape}</div>}
          {status.next_scrape && <div>Next update: {status.next_scrape}</div>}
          {status?.contract?.version && (
            <div>Contract: {status.contract.version}</div>
          )}
          {status?.uptime?.last_ok && (
            <div>
              Uptime monitor:{" "}
              {status.uptime.consecutive_failures > 0
                ? `${status.uptime.consecutive_failures} consecutive failures (last ok ${status.uptime.last_ok})`
                : `healthy (last ok ${status.uptime.last_ok})`}
            </div>
          )}
        </div>
      )}

      {status?.error && (
        <div
          style={{ fontSize: "0.72rem", color: "var(--red)", marginBottom: 10 }}
        >
          {status.error}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button
          className="button"
          onClick={triggerScrape}
          disabled={scraping}
          style={{ fontSize: "0.76rem" }}
        >
          {scraping ? "Refreshing..." : "Refresh Values"}
        </button>
        <button
          className="button"
          onClick={fetchStatus}
          style={{ fontSize: "0.76rem" }}
        >
          Check Status
        </button>
      </div>

      {scrapeMsg && (
        <div
          style={{
            fontSize: "0.72rem",
            marginTop: 6,
            color: scrapeMsg.startsWith("Error")
              ? "var(--red)"
              : "var(--green)",
          }}
        >
          {scrapeMsg}
        </div>
      )}
    </div>
  );
}
