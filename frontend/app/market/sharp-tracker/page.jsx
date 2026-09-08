"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  DataTable,
  Panel,
  PageHeader,
  Select,
  StatTile,
} from "@/components/ds";
import { LoadingState } from "@/components/ui";
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

// Same filter-row shape as /market/sharp-roster-percentage's `Dropdown` —
// kept local rather than extracted, since it is two call sites total
// across the two sharp pages and each has a slightly different label
// column width.
function Dropdown({ label, value, onChange, options, children }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 170 }}>
      <span className="muted" style={{ fontSize: "0.68rem", textTransform: "uppercase" }}>
        {label}
      </span>
      <Select value={value} onChange={(event) => onChange(event.target.value)}>
        {children ||
          options.map(([optionValue, optionLabel]) => (
            <option key={optionValue} value={optionValue}>
              {optionLabel}
            </option>
          ))}
      </Select>
    </label>
  );
}

function SourceBreakdown({ sources }) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {Object.entries(sources || {}).map(([name, row]) => (
        <div key={name} className="muted" style={{ fontSize: "0.72rem" }}>
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
  const [expandedAssetId, setExpandedAssetId] = useState(null);

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
    if (methods[0] === "curated_industry") return "Curated industry sharps";
    if (methods[0] === "both_curated_and_performance")
      return "Curated industry sharps with measured performance";
    return "Automated Sharp Score";
  }, [market]);

  const columns = useMemo(
    () => [
      {
        key: "displayName",
        header: "Player",
        sortable: true,
        accessor: (row) => row.displayName || row.assetId,
        render: (row) => (
          <div>
            <div style={{ fontWeight: 650 }}>{row.displayName || row.assetId}</div>
            <div className="muted" style={{ fontSize: "0.68rem" }}>
              {row.position || row.assetType}
              {row.nflTeam ? ` · ${row.nflTeam}` : ""}
            </div>
          </div>
        ),
      },
      {
        key: "signalStrength",
        header: "Signal",
        numeric: true,
        sortable: true,
        accessor: (row) => Number(row.signalStrength || 0),
        render: (row) => Number(row.signalStrength || 0).toFixed(1),
      },
      {
        key: "buys",
        header: "Buys",
        numeric: true,
        sortable: true,
        accessor: (row) => row.windows?.[windowName]?.buys || 0,
      },
      {
        key: "sells",
        header: "Sells",
        numeric: true,
        sortable: true,
        accessor: (row) => row.windows?.[windowName]?.sells || 0,
      },
      {
        key: "net",
        header: "Net",
        numeric: true,
        sortable: true,
        accessor: (row) => row.windows?.[windowName]?.net || 0,
        render: (row) => {
          const net = row.windows?.[windowName]?.net || 0;
          return `${net > 0 ? "+" : ""}${net}`;
        },
      },
      {
        key: "volume",
        header: "Volume",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (row) => row.windows?.[windowName]?.volume || 0,
      },
      {
        key: "uniqueManagers",
        header: "Sharp managers",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        accessor: (row) => row.windows?.[windowName]?.uniqueManagers || 0,
      },
      {
        key: "uniqueLeagues",
        header: "Leagues",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        accessor: (row) => row.windows?.[windowName]?.uniqueLeagues || 0,
      },
      {
        key: "velocity",
        header: "Velocity",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (row) => (row.velocity == null ? -Infinity : row.velocity),
        render: (row) => (row.velocity == null ? "—" : `${row.velocity.toFixed(2)}×`),
      },
      {
        key: "confidence",
        header: "Confidence",
        hideBelow: "lg",
        accessor: (row) => row.confidence,
      },
      {
        key: "sources",
        header: "Sources",
        render: (row) => (
          <span style={{ display: "inline-flex", gap: 4, flexWrap: "wrap" }}>
            {(row.sourceLabels || []).map((label) => (
              <Badge key={label} tone="outline">
                {label}
              </Badge>
            ))}
          </span>
        ),
      },
      {
        key: "lastTs",
        header: "Last activity",
        hideBelow: "md",
        accessor: (row) => row.lastTs || 0,
        render: (row) => (row.lastTs ? new Date(row.lastTs).toLocaleDateString() : "—"),
      },
    ],
    [windowName],
  );

  return (
    <main className="page">
      <PageHeader
        title="Sharp Tracker"
        description="One normalized market view combining qualified-manager activity from Sleeper and configured FFPC public sources."
      />

      <Panel title="At a glance" subtitle={`${qualificationLabel} · methodology ${market?.methodologyVersion || cohort?.methodologyVersion || "sharp-v2"}`} dense>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
          <StatTile
            label="Observable"
            value={cohortStats.observableManagers ?? "—"}
            meta="platform-scoped managers observed"
          />
          <StatTile
            label="Records"
            value={cohortStats.managersWithRecords ?? cohort?.records?.scoreableRecords ?? "—"}
            meta="complete evidence available"
          />
          <StatTile
            label="Automated"
            value={cohortStats.qualifiedManagers ?? "—"}
            meta="passed Sharp Score v2"
          />
          <StatTile
            label="Curated"
            value={cohortStats.curatedManagers ?? market?.cohort?.curatedManagers ?? "—"}
            meta="verified high-stakes cohort"
          />
          <StatTile
            label="Provisional"
            value={cohortStats.provisionalManagers ?? market?.cohort?.provisionalManagers ?? "—"}
            meta="public FFPC activity, not sharp-v2"
          />
          <StatTile label="Assets" value={assets.length} meta={`activity in ${windowName}`} />
        </div>
      </Panel>

      <Panel title="Filters" dense>
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "end" }}>
          <Dropdown label="Window" value={windowName} onChange={setWindowName}>
            {WINDOWS.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Dropdown>
          <Dropdown label="Source" value={source} onChange={setSource} options={SOURCES} />
          <Dropdown label="Sort" value={sort} onChange={setSort} options={SORTS} />
          <Dropdown label="Qualification" value={qualification} onChange={setQualification}>
            <option value="all">All allowed methods</option>
            <option value="automated">Automated only</option>
            <option value="curated">Curated FFPC high-stakes only</option>
            <option value="provisional">Provisional FFPC only</option>
            {/* Researched dynasty-industry people. Empty until an identity
                is explicitly verified through the review queue -- an honest
                state, rendered by DataTable's own empty state below. */}
            <option value="industry">Curated industry sharps only</option>
            <option value="super">Super Sharps only</option>
            <option value="both">Curated + performance qualified</option>
          </Dropdown>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            loading={loading}
            onClick={() => setRefreshToken((value) => value + 1)}
          >
            Refresh now
          </Button>
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
      </Panel>

      {marketError && market ? (
        <Banner tone="warning" title="Latest refresh failed">
          {marketError}. Showing the last successful result and retrying automatically.
        </Banner>
      ) : null}
      {cohortError ? (
        <Banner tone="warning" title="Cohort totals are retrying automatically">
          {cohortError}
        </Banner>
      ) : null}

      {marketError && !market ? (
        <Banner tone="negative" title="Sharp market temporarily unavailable">
          {marketError}. Retrying automatically…
        </Banner>
      ) : loading && !market ? (
        <LoadingState message="Loading unified Sharp market…" />
      ) : (
        <Panel title="Market activity">
          <DataTable
            columns={columns}
            rows={assets}
            rowKey={(row) => row.assetId}
            caption="Normalized sharp-cohort player movements: buys, sells, net flow, volume and velocity."
            density="compact"
            defaultSort={{ key: "signalStrength", direction: "desc" }}
            onRowClick={(row) =>
              setExpandedAssetId((current) => (current === row.assetId ? null : row.assetId))
            }
            renderAfterRow={(row) =>
              row.assetId === expandedAssetId ? (
                <tr key={`${row.assetId}-detail`}>
                  <td colSpan={columns.length} style={{ padding: "10px 12px" }}>
                    <SourceBreakdown sources={row.sources} />
                  </td>
                </tr>
              ) : null
            }
            emptyState={
              <div>
                <strong>
                  {market?.status === "cohort_building"
                    ? "The qualified cohort is still building"
                    : "No activity in this view"}
                </strong>
                <p className="muted">
                  {source === "ffpc" && coverage.ffpc?.enabled === false
                    ? "FFPC collection is disabled. Sleeper remains available and unchanged."
                    : "No normalized player movements matched the selected source, window, and qualification filters."}
                </p>
              </div>
            }
          />
        </Panel>
      )}

      <Panel title="Qualification guardrail" dense>
        <p className="muted" style={{ fontSize: "0.7rem", lineHeight: 1.6, margin: 0 }}>
          Automated managers passed the unchanged Sharp Score v2 evidence gates. Curated FFPC
          high-stakes managers and provisional public FFPC observations are separately labeled
          methods with configured weights. Provisional activity can populate the market table, but
          it is never presented as sharp-v2 qualification. Name-only or league-scoped FFPC
          identities cannot satisfy automated multi-league qualification.
        </p>
      </Panel>
    </main>
  );
}
