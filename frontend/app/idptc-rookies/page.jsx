"use client";

import { useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/ui/PageHeader";
import LoadingState from "@/components/ui/LoadingState";
import ErrorState from "@/components/ui/ErrorState";
import EmptyState from "@/components/ui/EmptyState";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";
import { PlayerNameButton } from "@/components/ds";

// ── /idptc-rookies — Combined IDPTC + KTC rookie board ───────────────
// Linked from /more → Lab.  Lists every player flagged ``rookie`` in
// the live contract that is actually on an NFL roster (has a Sleeper
// ID), ranked by ``max(idpTradeCalc, ktc)`` so KTC-only offensive
// rookies are interleaved with IDP-tilted IDPTC rookies and nothing
// gets dropped.  Each row optionally shows a short fantasy-relevance
// blurb sourced from ``/public/idptc-rookies-blurbs.json``.  Exports
// the full ranked list with both KTC + IDPTC values as CSV or
// Markdown.

const TOP_N = 120; // generous soft cap; current universe ~85 rookies
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

function fmtVal(v) {
  return v > 0 ? v.toLocaleString() : "—";
}

function downloadCsv(rows) {
  const header = "Rank,Name,Pos,KTC Value,IDPTC Value,Fantasy Blurb";
  const lines = rows.map((r, i) =>
    [
      i + 1,
      csvEscape(r.name),
      csvEscape(r.pos),
      r.ktc || "",
      r.idptc || "",
      csvEscape(r.blurb || ""),
    ].join(","),
  );
  downloadFile(
    `dynasty-rookie-board-${rows.length}.csv`,
    [header, ...lines].join("\n"),
    "text/csv;charset=utf-8;",
  );
}

function downloadMarkdown(rows) {
  const lines = [
    "# Dynasty Rookie Board — IDPTC + KTC",
    "",
    `Generated ${new Date().toISOString().slice(0, 10)} · ${rows.length} players · sorted by max(IDPTC, KTC) value`,
    "",
  ];
  rows.forEach((r, i) => {
    const vals = [
      r.ktc > 0 ? `KTC ${r.ktc.toLocaleString()}` : null,
      r.idptc > 0 ? `IDPTC ${r.idptc.toLocaleString()}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    lines.push(`## ${i + 1}. ${r.name} — ${r.pos || "?"} (${vals})`);
    lines.push("");
    lines.push(r.blurb ? r.blurb : "_No blurb available._");
    lines.push("");
  });
  downloadFile(
    `dynasty-rookie-board-${rows.length}.md`,
    lines.join("\n"),
    "text/markdown;charset=utf-8;",
  );
}

export default function IdptcRookiesPage() {
  const { loading, error, rows } = useDynastyData();
  const { openPlayerPopup } = useApp();
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
      // Sleeper ID is the cleanest "actually-on-an-NFL-roster" signal —
      // filters out college players who linger on prospect boards
      // (e.g. Trinidad Chambliss returning to Ole Miss).
      const sleeperId = r?.raw?._sleeperId || r?.raw?.playerId;
      if (!sleeperId) continue;
      const idptc = Math.max(0, Math.round(Number(r?.canonicalSites?.idpTradeCalc) || 0));
      // ``ktcSfTep`` is the post-2026-04-28 KTC source; ``ktc`` is the
      // legacy key kept for robustness.  Use the max so a player with
      // either stamp is captured.
      const ktc = Math.max(
        0,
        Math.round(
          Math.max(
            Number(r?.canonicalSites?.ktcSfTep) || 0,
            Number(r?.canonicalSites?.ktc) || 0,
          ),
        ),
      );
      if (idptc <= 0 && ktc <= 0) continue;
      candidates.push({
        name: r.name,
        pos: r.pos || "?",
        idptc,
        ktc,
        sortValue: Math.max(idptc, ktc),
        blurb: blurbs?.[r.name] || "",
      });
    }
    candidates.sort((a, b) => b.sortValue - a.sortValue);
    return candidates.slice(0, TOP_N);
  }, [rows, blurbs]);

  if (loading) return <LoadingState message="Loading rookie board..." />;
  if (error) return <ErrorState message={`Failed to load: ${error}`} />;

  const blurbCount = ranked.filter((r) => r.blurb).length;

  return (
    <section>
      <PageHeader
        title="Rookie Board"
        subtitle={
          blurbsLoading
            ? "Every rookie on either source, ranked by max(IDPTC, KTC) value."
            : `Every rookie on either source, ranked by max(IDPTC, KTC) value. ${blurbCount}/${ranked.length} have fantasy blurbs.`
        }
        actions={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="button"
              onClick={() => downloadMarkdown(ranked)}
              disabled={ranked.length === 0}
              title="Export ranked list + both values + blurbs as Markdown"
            >
              Export Markdown
            </button>
            <button
              className="button button-primary"
              onClick={() => downloadCsv(ranked)}
              disabled={ranked.length === 0}
              title="Export rank, name, pos, both values, blurb as CSV"
            >
              Export CSV
            </button>
          </div>
        }
      />

      {ranked.length === 0 ? (
        <EmptyState
          title="No rookies yet"
          message="Neither source has published a rookie board for this season yet."
        />
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <div className="table-wrap">
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 48 }}>#</th>
                <th style={{ textAlign: "left", padding: "8px 12px" }}>Player</th>
                <th style={{ textAlign: "left", padding: "8px 12px", width: 64 }}>Pos</th>
                <th style={{ textAlign: "right", padding: "8px 12px", width: 100 }}>KTC</th>
                <th style={{ textAlign: "right", padding: "8px 12px", width: 100 }}>IDPTC</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r, idx) => (
                <tr key={`${r.name}-${idx}`} style={{ borderTop: "1px solid var(--border)" }}>
                  <td style={{ padding: "8px 12px", color: "var(--subtext)", verticalAlign: "top" }}>{idx + 1}</td>
                  <td style={{ padding: "8px 12px", verticalAlign: "top" }}>
                    <div style={{ fontWeight: 600 }}>
                      <PlayerNameButton name={r.name} onOpen={openPlayerPopup} />
                    </div>
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
                      color: r.ktc > 0 ? "var(--text)" : "var(--subtext)",
                    }}
                  >
                    {fmtVal(r.ktc)}
                  </td>
                  <td
                    style={{
                      padding: "8px 12px",
                      textAlign: "right",
                      fontVariantNumeric: "tabular-nums",
                      verticalAlign: "top",
                      color: r.idptc > 0 ? "var(--text)" : "var(--subtext)",
                    }}
                  >
                    {fmtVal(r.idptc)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}
    </section>
  );
}
