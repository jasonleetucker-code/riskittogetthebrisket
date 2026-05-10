"use client";

import { useMemo } from "react";
import PageHeader from "@/components/ui/PageHeader";
import LoadingState from "@/components/ui/LoadingState";
import ErrorState from "@/components/ui/ErrorState";
import EmptyState from "@/components/ui/EmptyState";
import { useDynastyData } from "@/components/useDynastyData";

// ── /idptc-rookies — Hidden tab: top 72 rookies by IDPTC value ───────
// Linked discreetly from /more.  Lists every player flagged ``rookie``
// in the live contract, ranked by their raw ``canonicalSites.idpTradeCalc``
// value (descending), capped at 72.  Includes a one-click CSV export of
// "name,value" for the displayed list.

const TOP_N = 72;

function downloadCsv(rows) {
  const header = "Name,IDPTC Value";
  const lines = rows.map((r) => {
    const safeName = /[",\n]/.test(r.name) ? `"${r.name.replace(/"/g, '""')}"` : r.name;
    return `${safeName},${r.value}`;
  });
  const csv = [header, ...lines].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `idptc-top-${rows.length}-rookies.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function IdptcRookiesPage() {
  const { loading, error, rows } = useDynastyData();

  const ranked = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return [];
    const candidates = [];
    for (const r of rows) {
      if (!r?.rookie) continue;
      const raw = Number(r?.canonicalSites?.idpTradeCalc);
      if (!Number.isFinite(raw) || raw <= 0) continue;
      candidates.push({ name: r.name, pos: r.pos || "?", value: Math.round(raw) });
    }
    candidates.sort((a, b) => b.value - a.value);
    return candidates.slice(0, TOP_N);
  }, [rows]);

  if (loading) return <LoadingState message="Loading IDPTC rookies..." />;
  if (error) return <ErrorState message={`Failed to load: ${error}`} />;

  return (
    <section>
      <PageHeader
        title="IDPTC Rookies — Top 72"
        subtitle="Rookies ranked by raw IDPTC value (descending)."
        actions={
          <button
            className="button button-primary"
            onClick={() => downloadCsv(ranked)}
            disabled={ranked.length === 0}
          >
            Export CSV
          </button>
        }
      />

      {ranked.length === 0 ? (
        <EmptyState message="No rookies have an IDPTC value yet." />
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table className="rankings-table" style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 48 }}>#</th>
                <th style={{ textAlign: "left", padding: "8px 12px" }}>Player</th>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 64 }}>Pos</th>
                <th style={{ textAlign: "right", padding: "8px 12px" }}>IDPTC Value</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r, idx) => (
                <tr key={`${r.name}-${idx}`} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 12px", color: "var(--subtext)" }}>{idx + 1}</td>
                  <td style={{ padding: "8px 12px", fontWeight: 600 }}>{r.name}</td>
                  <td style={{ padding: "8px 12px", color: "var(--subtext)" }}>{r.pos}</td>
                  <td style={{ padding: "8px 12px", textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
                    {r.value.toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
