"use client";

import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/ui/PageHeader";
import LoadingState from "@/components/ui/LoadingState";
import ErrorState from "@/components/ui/ErrorState";
import EmptyState from "@/components/ui/EmptyState";
import { useDynastyData } from "@/components/useDynastyData";

// ── /idptc-rookies — Hidden tab: top 72 rookies by IDPTC value ───────
// Linked discreetly from /more.  Lists every player flagged ``rookie``
// in the live contract, ranked by their raw ``canonicalSites.idpTradeCalc``
// value (descending), capped at 72.  Each row optionally shows a short
// fantasy-relevance blurb sourced from
// ``/public/idptc-rookies-blurbs.json`` (curated separately).  Includes
// CSV + Markdown exports.

const TOP_N = 72;
const BLURBS_URL = "/idptc-rookies-blurbs.json";

function csvEscape(s) {
  const str = String(s ?? "");
  return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

function downloadFile(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadCsv(rows) {
  const header = "Rank,Name,Pos,IDPTC Value,Fantasy Blurb";
  const lines = rows.map((r, i) =>
    [i + 1, csvEscape(r.name), csvEscape(r.pos), r.value, csvEscape(r.blurb || "")].join(","),
  );
  downloadFile(
    `idptc-top-${rows.length}-rookies.csv`,
    [header, ...lines].join("\n"),
    "text/csv;charset=utf-8;",
  );
}

function downloadMarkdown(rows) {
  const lines = [
    "# Top IDPTC Rookies — Fantasy Outlook",
    "",
    `Generated ${new Date().toISOString().slice(0, 10)} · ${rows.length} players · sorted by raw IDPTC value`,
    "",
  ];
  rows.forEach((r, i) => {
    lines.push(`## ${i + 1}. ${r.name} — ${r.pos || "?"} (IDPTC ${r.value.toLocaleString()})`);
    lines.push("");
    lines.push(r.blurb ? r.blurb : "_No blurb available._");
    lines.push("");
  });
  downloadFile(
    `idptc-top-${rows.length}-rookies.md`,
    lines.join("\n"),
    "text/markdown;charset=utf-8;",
  );
}

export default function IdptcRookiesPage() {
  const { loading, error, rows } = useDynastyData();
  const [blurbs, setBlurbs] = useState({});
  const [blurbsLoading, setBlurbsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch(BLURBS_URL, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : {}))
      .then((data) => {
        if (cancelled) return;
        setBlurbs(data && typeof data === "object" ? data : {});
      })
      .catch(() => {
        if (!cancelled) setBlurbs({});
      })
      .finally(() => {
        if (!cancelled) setBlurbsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const ranked = useMemo(() => {
    if (!Array.isArray(rows) || rows.length === 0) return [];
    const candidates = [];
    for (const r of rows) {
      if (!r?.rookie) continue;
      const raw = Number(r?.canonicalSites?.idpTradeCalc);
      if (!Number.isFinite(raw) || raw <= 0) continue;
      candidates.push({
        name: r.name,
        pos: r.pos || "?",
        value: Math.round(raw),
        blurb: blurbs?.[r.name] || "",
      });
    }
    candidates.sort((a, b) => b.value - a.value);
    return candidates.slice(0, TOP_N);
  }, [rows, blurbs]);

  if (loading) return <LoadingState message="Loading IDPTC rookies..." />;
  if (error) return <ErrorState message={`Failed to load: ${error}`} />;

  const blurbCount = ranked.filter((r) => r.blurb).length;

  return (
    <section>
      <PageHeader
        title="IDPTC Rookies — Top 72"
        subtitle={
          blurbsLoading
            ? "Rookies ranked by raw IDPTC value (descending)."
            : `Rookies ranked by raw IDPTC value (descending). ${blurbCount}/${ranked.length} have fantasy blurbs.`
        }
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="button"
              onClick={() => downloadMarkdown(ranked)}
              disabled={ranked.length === 0}
              title="Export ranked list + blurbs as Markdown"
            >
              Export Markdown
            </button>
            <button
              className="button button-primary"
              onClick={() => downloadCsv(ranked)}
              disabled={ranked.length === 0}
              title="Export rank, name, pos, value, blurb as CSV"
            >
              Export CSV
            </button>
          </div>
        }
      />

      {ranked.length === 0 ? (
        <EmptyState message="No rookies have an IDPTC value yet." />
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 48 }}>#</th>
                <th style={{ textAlign: "left", padding: "8px 12px" }}>Player</th>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 64 }}>Pos</th>
                <th style={{ textAlign: "right", padding: "8px 12px", width: 120 }}>IDPTC Value</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r, idx) => (
                <tr key={`${r.name}-${idx}`} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 12px", color: "var(--subtext)", verticalAlign: "top" }}>{idx + 1}</td>
                  <td style={{ padding: "8px 12px", verticalAlign: "top" }}>
                    <div style={{ fontWeight: 600 }}>{r.name}</div>
                    {r.blurb && (
                      <div
                        className="muted text-xs"
                        style={{ marginTop: 4, lineHeight: 1.45, maxWidth: 720 }}
                      >
                        {r.blurb}
                      </div>
                    )}
                  </td>
                  <td style={{ padding: "8px 12px", color: "var(--subtext)", verticalAlign: "top" }}>{r.pos}</td>
                  <td
                    style={{
                      padding: "8px 12px",
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      verticalAlign: "top",
                    }}
                  >
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
