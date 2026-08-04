"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

const WINDOWS = ["48h", "7d", "14d", "30d", "90d", "all"];
const SOURCES = [
  ["all", "All sources"],
  ["sleeper", "Sleeper"],
  ["ffpc", "FFPC"],
];
const SORTS = [
  ["strength", "Signal"],
  ["net", "Net"],
  ["volume", "Volume"],
  ["velocity", "Velocity"],
  ["buys", "Buys"],
  ["sells", "Sells"],
];
const AUTO_REFRESH_MS = 60_000;
const RETRYABLE_STATUSES = new Set([404, 502, 503, 504]);

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function fetchFreshJson(path, { attempts = 3 } = {}) {
  let lastError = null;
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    const url = new URL(path, window.location.origin);
    url.searchParams.set("_sharpRefresh", String(Date.now()));
    try {
      const response = await fetch(url.toString(), {
        cache: "no-store",
        credentials: "same-origin",
        headers: {
          "Cache-Control": "no-cache, no-store, max-age=0",
          Pragma: "no-cache",
        },
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok) return payload;
      lastError = new Error(apiErrorMessage(payload, response.status));
      if (!RETRYABLE_STATUSES.has(response.status) || attempt === attempts) throw lastError;
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(apiErrorMessage(error));
      if (attempt === attempts) throw lastError;
    }
    await sleep(attempt * 750);
  }
  throw lastError || new Error("Request failed");
}

function Stat({ label, value, note }) {
  return (
    <div style={{ minWidth: 135 }}>
      <div className="muted" style={{ fontSize: "0.68rem", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontFamily: "var(--mono)", fontSize: "1.3rem", fontWeight: 700 }}>
        {value == null ? "—" : Number(value).toLocaleString()}
      </div>
      {note ? (
        <div className="muted" style={{ fontSize: "0.66rem" }}>
          {note}
        </div>
      ) : null}
    </div>
  );
}

function Badge({ children }) {
  return (
    <span
      style={{
        display: "inline-block",
        border: "1px solid var(--border-default)",
        borderRadius: 3,
        padding: "1px 5px",
        fontSize: "0.65rem",
        marginRight: 4,
      }}
    >
      {children}
    </span>
  );
}

function SourceBreakdown({ sources }) {
  return (
    <div style={{ display: "grid", gap: 6, marginTop: 8 }}>
      {Object.entries(sources || {}).map(([name, row]) => (
        <div key={name} className="muted" style={{ fontSize: "0.7rem" }}>
          <strong style={{ color: "var(--text-primary)" }}>
            {name === "ffpc" ? "FFPC" : "Sleeper"}
          </strong>{" "}
          · {row.buys} buys · {row.sells} sells · net {row.net > 0 ? "+" : ""}
          {row.net} · {row.volume} volume · {row.uniqueManagers} managers · {row.uniqueLeagues}{" "}
          leagues
        </div>
      ))}
    </div>
  );
}

export default function SharpTrackerPage() {
  const [cohort, setCohort] = useState(null);
  const [market, setMarket] = useState(null);
  const [loading, setLoading] = useState(true);
  const [marketError, setMarketError] = useState(null);
  const [cohortError, setCohortError] = useState(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [windowName, setWindowName] = useState("30d");
  const [source, setSource] = useState("all");
  const [sort, setSort] = useState("strength");
  const [qualification, setQualification] = useState("all");

  const loadCohort = useCallback(async () => {
    try {
      const payload = await fetchFreshJson("/api/sharp/cohort");
      setCohort(payload);
      setCohortError(null);
    } catch (error) {
      setCohortError(apiErrorMessage(error));
    }
  }, []);

  const loadMarket = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({
      window: windowName,
      platform: source,
      sort,
      qualification,
      assetType: "player",
      limit: "100",
    });
    try {
      const payload = await fetchFreshJson(`/api/sharp/market?${params.toString()}`);
      setMarket(payload);
      setMarketError(null);
      setLastRefreshedAt(Date.now());
    } catch (error) {
      setMarketError(apiErrorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [qualification, sort, source, windowName]);

  useEffect(() => {
    loadCohort();
    const timer = window.setInterval(loadCohort, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadCohort, refreshToken]);

  useEffect(() => {
    loadMarket();
    const timer = window.setInterval(loadMarket, AUTO_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [loadMarket, refreshToken]);

  const cohortStats = cohort?.cohort || {};
  const assets = (market?.assets || []).filter(
    (asset) =>
      asset?.assetType !== "pick" &&
      asset?.position !== "PICK" &&
      !String(asset?.assetId || "").startsWith("pick:"),
  );
  const coverage = market?.coverage?.platforms || cohort?.coverage?.platforms || {};
  const qualificationLabel = useMemo(() => {
    const methods = market?.cohort?.qualificationMethods || [];
    if (methods.length > 1) return "Mixed cohort";
    if (methods[0] === "curated_high_stakes") return "Curated FFPC high-stakes cohort";
    if (methods[0] === "provisional_public") return "Provisional public FFPC activity";
    return "Automated Sharp Score";
  }, [market]);

  return (
    <section>
      <PageHeader
        title="Sharp Tracker"
        subtitle="One normalized market view combining qualified-manager activity from Sleeper and configured FFPC public sources."
      />

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          <Stat
            label="Observable"
            value={cohortStats.observableManagers}
            note="platform-scoped managers observed"
          />
          <Stat
            label="Records"
            value={cohortStats.managersWithRecords ?? cohort?.records?.scoreableRecords}
            note="complete evidence available"
          />
          <Stat
            label="Automated"
            value={cohortStats.qualifiedManagers}
            note="passed Sharp Score v2"
          />
          <Stat
            label="Curated"
            value={cohortStats.curatedManagers ?? market?.cohort?.curatedManagers}
            note="verified high-stakes cohort"
          />
          <Stat
            label="Provisional"
            value={cohortStats.provisionalManagers ?? market?.cohort?.provisionalManagers}
            note="public FFPC activity, not sharp-v2"
          />
          <Stat label="Assets" value={assets.length} note={`activity in ${windowName}`} />
        </div>
        <div className="muted" style={{ fontSize: "0.68rem", marginTop: 9 }}>
          {qualificationLabel} · methodology{" "}
          {market?.methodologyVersion || cohort?.methodologyVersion || "sharp-v2"}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "end" }}>
          <label style={{ fontSize: "0.7rem" }}>
            Window
            <br />
            <select value={windowName} onChange={(event) => setWindowName(event.target.value)}>
              {WINDOWS.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.7rem" }}>
            Source
            <br />
            <select value={source} onChange={(event) => setSource(event.target.value)}>
              {SOURCES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.7rem" }}>
            Sort
            <br />
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              {SORTS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label style={{ fontSize: "0.7rem" }}>
            Qualification
            <br />
            <select
              value={qualification}
              onChange={(event) => setQualification(event.target.value)}
            >
              <option value="all">All allowed methods</option>
              <option value="automated">Automated only</option>
              <option value="curated">Curated only</option>
              <option value="provisional">Provisional FFPC only</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => setRefreshToken((value) => value + 1)}
            disabled={loading}
          >
            {loading ? "Refreshing…" : "Refresh now"}
          </button>
        </div>
        <div className="muted" style={{ fontSize: "0.68rem", marginTop: 9 }}>
          Sleeper: {coverage.sleeper?.status || "unknown"} · {coverage.sleeper?.movements || 0}{" "}
          movements{" | "}
          FFPC:{" "}
          {coverage.ffpc?.status || (coverage.ffpc?.enabled === false ? "disabled" : "unknown")} ·{" "}
          {coverage.ffpc?.movements || 0} movements
          {(market?.coverage?.unmappedAssets || 0) > 0
            ? ` · ${market.coverage.unmappedAssets} FFPC assets awaiting mapping`
            : ""}
          {lastRefreshedAt
            ? ` · refreshed ${new Date(lastRefreshedAt).toLocaleTimeString()}`
            : ""}
        </div>
        {marketError && market ? (
          <div className="muted" style={{ fontSize: "0.68rem", marginTop: 6 }}>
            Latest refresh failed ({marketError}); showing the last successful result and retrying
            automatically.
          </div>
        ) : null}
        {cohortError ? (
          <div className="muted" style={{ fontSize: "0.68rem", marginTop: 6 }}>
            Cohort totals are retrying automatically: {cohortError}
          </div>
        ) : null}
      </div>

      {marketError && !market ? (
        <div className="card">
          <EmptyState
            title="Sharp market temporarily unavailable"
            message={`${marketError}. Retrying automatically…`}
          />
        </div>
      ) : null}
      {loading && !market ? <LoadingState message="Loading unified Sharp market…" /> : null}
      {!loading && !marketError && !assets.length ? (
        <div className="card">
          <EmptyState
            title={
              market?.status === "cohort_building"
                ? "The qualified cohort is still building"
                : "No activity in this view"
            }
            message={
              source === "ffpc" && coverage.ffpc?.enabled === false
                ? "FFPC collection is disabled. Sleeper remains available and unchanged."
                : "No normalized player movements matched the selected source, window, and qualification filters."
            }
          />
        </div>
      ) : null}

      {assets.length ? (
        <div className="card" style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.72rem" }}>
            <thead>
              <tr>
                {[
                  "Player",
                  "Signal",
                  "Buys",
                  "Sells",
                  "Net",
                  "Volume",
                  "Sharp managers",
                  "Leagues",
                  "Velocity",
                  "Confidence",
                  "Sources",
                  "Last activity",
                ].map((label) => (
                  <th
                    key={label}
                    style={{
                      textAlign: "left",
                      padding: "7px 6px",
                      borderBottom: "1px solid var(--border-default)",
                      whiteSpace: "nowrap",
                    }}
                  >
                    {label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {assets.map((asset) => {
                const row = asset.windows?.[windowName] || {};
                return (
                  <tr key={asset.assetId}>
                    <td
                      style={{
                        padding: "8px 6px",
                        borderBottom: "1px solid var(--border-default)",
                        minWidth: 180,
                      }}
                    >
                      <details>
                        <summary style={{ cursor: "pointer", fontWeight: 650 }}>
                          {asset.displayName || asset.assetId}
                        </summary>
                        <div className="muted" style={{ marginTop: 4 }}>
                          {asset.position || asset.assetType}
                          {asset.nflTeam ? ` · ${asset.nflTeam}` : ""} · {asset.assetId}
                        </div>
                        <SourceBreakdown sources={asset.sources} />
                      </details>
                    </td>
                    <td>{Number(asset.signalStrength || 0).toFixed(1)}</td>
                    <td>{row.buys || 0}</td>
                    <td>{row.sells || 0}</td>
                    <td>
                      {row.net > 0 ? "+" : ""}
                      {row.net || 0}
                    </td>
                    <td>{row.volume || 0}</td>
                    <td>{row.uniqueManagers || 0}</td>
                    <td>{row.uniqueLeagues || 0}</td>
                    <td>{asset.velocity == null ? "—" : `${asset.velocity.toFixed(2)}×`}</td>
                    <td>{asset.confidence}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {(asset.sourceLabels || []).map((label) => (
                        <Badge key={label}>{label}</Badge>
                      ))}
                    </td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      {asset.lastTs ? new Date(asset.lastTs).toLocaleDateString() : "—"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="card" style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 600, fontSize: "0.82rem", marginBottom: 5 }}>
          Qualification guardrail
        </div>
        <div className="muted" style={{ fontSize: "0.7rem", lineHeight: 1.6 }}>
          Automated managers passed the unchanged Sharp Score v2 evidence gates. Curated FFPC
          high-stakes managers and provisional public FFPC observations are separately labeled
          methods with configured weights. Provisional activity can populate the market table, but
          it is never presented as sharp-v2 qualification. Name-only or league-scoped FFPC
          identities cannot satisfy automated multi-league qualification.
        </div>
      </div>
    </section>
  );
}
