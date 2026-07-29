"use client";

import { useEffect, useState, useCallback } from "react";
import PageHeader from "@/components/ui/PageHeader";
import SubNav from "@/components/ui/SubNav";
import HeaderCard from "./sections/HeaderCard";
import SummaryCards from "./sections/SummaryCards";
import PositionalTable from "./sections/PositionalTable";
import FlexComparison from "./sections/FlexComparison";
import ComparisonCharts from "./sections/Charts";
import YearByYear from "./sections/YearByYear";
import Methodology from "./sections/Methodology";
import { Panel } from "@/components/ds";

const TABS = [
  { key: "summary", label: "Summary" },
  { key: "positional", label: "Positional" },
  { key: "flex", label: "Flex" },
  { key: "yearly", label: "Year-by-Year" },
  { key: "methodology", label: "Methodology" },
];

export default function LeagueComparisonPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [tab, setTab] = useState("summary");
  const [method, setMethod] = useState("improved"); // "improved" | "legacy"
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async (refresh = false) => {
    if (refresh) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const url = refresh
        ? "/api/league-comparison?refresh=1"
        : "/api/league-comparison";
      const res = await fetch(url, { cache: "no-store" });
      const body = await res.json();
      if (!res.ok) {
        throw new Error(body?.detail || body?.error || `HTTP ${res.status}`);
      }
      setData(body);
    } catch (err) {
      setError(err?.message || String(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load(false);
  }, [load]);

  const subtitle =
    "Compares your custom league scoring against a standard baseline league " +
    "to detect whether positional value gets accidentally distorted.";

  return (
    <section>
      <PageHeader
        title="Scoring Comparison"
        subtitle={subtitle}
        actions={
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => load(true)}
            disabled={loading || refreshing}
            title="Bypass the cache and rebuild the comparison from scratch"
          >
            {refreshing ? "Recalculating…" : "Recalculate"}
          </button>
        }
      />

      {loading && (
        <div className="card loading-state">
          <div className="loading-spinner" />
          <span className="muted text-sm">
            Loading comparison data&hellip; (first hit may take 30+ seconds
            while historical NFL stats download)
          </span>
        </div>
      )}

      {error && !loading && (
        <Panel>
          <p className="text-red" style={{ fontWeight: 600 }}>
            League comparison unavailable
          </p>
          <p className="muted text-sm" style={{ marginTop: 6 }}>{error}</p>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ marginTop: 12 }}
            onClick={() => load(false)}
          >
            Retry
          </button>
        </Panel>
      )}

      {data && !loading && (
        <>
          <HeaderCard data={data} />

          {(data.warnings || []).length > 0 && (
            <div className="card" style={{ borderColor: "var(--amber)" }}>
              <p className="text-amber" style={{ fontWeight: 600 }}>
                Notes &amp; warnings
              </p>
              <ul style={{ marginTop: 6, paddingLeft: 18 }}>
                {data.warnings.map((w, i) => (
                  <li key={i} className="muted text-sm" style={{ marginBottom: 4 }}>
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="card" style={{ paddingTop: "var(--space-sm)", paddingBottom: "var(--space-sm)" }}>
            <SubNav items={TABS} active={tab} onChange={setTab} />
          </div>

          {tab === "summary" && (
            <>
              <SummaryCards data={data} method={method} setMethod={setMethod} />
              <ComparisonCharts data={data} method={method} />
            </>
          )}

          {tab === "positional" && (
            <PositionalTable data={data} method={method} setMethod={setMethod} />
          )}

          {tab === "flex" && <FlexComparison data={data} />}

          {tab === "yearly" && <YearByYear data={data} method={method} />}

          {tab === "methodology" && <Methodology data={data} />}
        </>
      )}
    </section>
  );
}
