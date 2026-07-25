"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";

// ── Sharp Tracker (Phase 5) ──────────────────────────────────────────
// Cross-league market intelligence over the league-mate pool: which
// assets your league-mates are buying/selling across ALL of their
// Sleeper leagues.  Backed by GET /api/intel/summary (board) and
// GET /api/intel/player (member-exposure drill-down).  All numbers
// are computed server-side at read time; this page is a pure renderer.

const WINDOW_COLUMNS = [
  { key: "48h", label: "48h" },
  { key: "7d", label: "7d" },
  { key: "14d", label: "14d" },
  { key: "30d", label: "30d" },
];

// Snapshot older than this renders the amber staleness banner.  The
// cron refreshes daily, so >30h means at least one missed run.
const STALE_WARN_HOURS = 30;

function fmtNet(net) {
  if (net > 0) return `+${net}`;
  return String(net);
}

function netColor(net) {
  if (net > 0) return "var(--green)";
  if (net < 0) return "var(--red)";
  return "var(--subtext)";
}

function StalenessBanner({ staleHours, generatedAt }) {
  if (staleHours == null) {
    return (
      <div
        className="card"
        style={{ marginBottom: 10, borderColor: "var(--amber)", fontSize: "0.78rem" }}
      >
        No intel snapshot yet — the first crawl hasn&apos;t run. Trigger a refresh or wait
        for the daily cron.
      </div>
    );
  }
  if (staleHours <= STALE_WARN_HOURS) return null;
  return (
    <div
      className="card"
      style={{ marginBottom: 10, borderColor: "var(--amber)", fontSize: "0.78rem" }}
    >
      <strong style={{ color: "var(--amber)" }}>Stale intel:</strong>{" "}
      snapshot is {Math.round(staleHours)}h old
      {generatedAt ? ` (generated ${new Date(generatedAt).toLocaleString()})` : ""} — the
      daily refresh may have failed.
    </div>
  );
}

function MemberExposure({ assetId }) {
  const [detail, setDetail] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setDetail(null);
    setFailed(false);
    fetch(`/api/intel/player?playerId=${encodeURIComponent(assetId)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        if (!active) return;
        if (payload) setDetail(payload);
        else setFailed(true);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [assetId]);

  if (failed) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        No member detail available for this asset.
      </div>
    );
  }
  if (!detail) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        Loading member exposure…
      </div>
    );
  }
  const exposure = detail.memberExposure || [];
  if (exposure.length === 0) {
    return (
      <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
        No league-mate holds or traded this asset in the tracked pool.
      </div>
    );
  }
  return (
    <div style={{ padding: "4px 0 8px" }}>
      <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>
        {detail.holderCount} league-mate{detail.holderCount === 1 ? "" : "s"} hold this asset
        across {detail.heldLeagueTotal} league slot{detail.heldLeagueTotal === 1 ? "" : "s"}
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>League-mate</th>
              <th style={{ textAlign: "right" }}>Holds in</th>
              <th style={{ textAlign: "right" }}>Buys 30d</th>
              <th style={{ textAlign: "right" }}>Sells 30d</th>
              <th style={{ textAlign: "right" }}>Net 30d</th>
            </tr>
          </thead>
          <tbody>
            {exposure.map((m) => (
              <tr key={m.ownerId}>
                <td style={{ fontWeight: 600 }}>{m.displayName || `Owner ${m.ownerId}`}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                  {m.heldLeagueCount} league{m.heldLeagueCount === 1 ? "" : "s"}
                </td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{m.buys30d}</td>
                <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{m.sells30d}</td>
                <td
                  style={{
                    textAlign: "right",
                    fontFamily: "var(--mono)",
                    fontWeight: 700,
                    color: netColor(m.net30d),
                  }}
                >
                  {fmtNet(m.net30d)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function IntelPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expandedAsset, setExpandedAsset] = useState(null);
  const [typeFilter, setTypeFilter] = useState("all");

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    fetch("/api/intel/summary?limit=200")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((payload) => {
        setData(payload);
        setLoading(false);
      })
      .catch((err) => {
        setError(String(err?.message || err));
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const assets = useMemo(() => {
    const all = data?.assets || [];
    if (typeFilter === "all") return all;
    return all.filter((a) => a.assetType === typeFilter);
  }, [data, typeFilter]);

  if (loading) return <LoadingState message="Loading Sharp Tracker…" />;
  if (error) {
    return (
      <section>
        <PageHeader title="Sharp Tracker" subtitle="League-mate market intelligence." />
        <div className="card">
          <EmptyState title="Couldn't load intel" message={error} />
        </div>
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title="Sharp Tracker"
        subtitle={
          `What your league-mates are buying and selling across all of their Sleeper ` +
          `leagues — ${data?.memberCount ?? 0} managers, ${data?.leagueCount ?? 0} leagues tracked.`
        }
      />

      <StalenessBanner staleHours={data?.staleHours} generatedAt={data?.generatedAt} />

      {data?.truncatedMemberCount > 0 && (
        <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 8 }}>
          {data.truncatedMemberCount} manager{data.truncatedMemberCount === 1 ? "" : "s"} above
          the 25-league crawl cap — their deepest leagues aren&apos;t tracked.
        </div>
      )}

      <div className="card" style={{ marginBottom: 10, display: "flex", gap: 4, flexWrap: "wrap" }}>
        {[
          { key: "all", label: "All assets" },
          { key: "player", label: "Players" },
          { key: "pick", label: "Picks" },
        ].map((opt) => {
          const active = opt.key === typeFilter;
          return (
            <button
              key={opt.key}
              onClick={() => setTypeFilter(opt.key)}
              className={active ? "button" : "button-outline"}
              style={{ fontSize: "0.74rem", padding: "4px 10px", minHeight: 32, opacity: active ? 1 : 0.78 }}
            >
              {opt.label}
            </button>
          );
        })}
      </div>

      {assets.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No tracked activity yet"
            message="No buy/sell events in the rolling windows. Check back after the next crawl."
          />
        </div>
      ) : (
        <div className="card">
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 6 }}>
            {assets.length} asset{assets.length === 1 ? "" : "s"} · sorted by trend score
            (3·net48h + 2·net7d + 1·net30d) · click a row for member exposure
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Asset</th>
                  <th style={{ textAlign: "right" }}>Trend</th>
                  {WINDOW_COLUMNS.map((w) => (
                    <th key={w.key} style={{ textAlign: "right" }}>
                      Net {w.label}
                    </th>
                  ))}
                  <th style={{ textAlign: "right" }}>Leagues</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => {
                  const expanded = expandedAsset === asset.assetId;
                  return [
                    <tr
                      key={asset.assetId}
                      onClick={() =>
                        setExpandedAsset(expanded ? null : asset.assetId)
                      }
                      style={{ cursor: "pointer" }}
                    >
                      <td style={{ fontWeight: 600 }}>
                        <span style={{ marginRight: 6 }}>{expanded ? "▼" : "▶"}</span>
                        {asset.displayName}
                        {asset.assetType === "pick" && (
                          <span className="badge" style={{ marginLeft: 6, fontSize: "0.64rem" }}>
                            PICK
                          </span>
                        )}
                      </td>
                      <td
                        style={{
                          textAlign: "right",
                          fontFamily: "var(--mono)",
                          fontWeight: 700,
                          color: netColor(asset.trendScore),
                        }}
                      >
                        {fmtNet(asset.trendScore)}
                      </td>
                      {WINDOW_COLUMNS.map((w) => {
                        const win = asset.windows?.[w.key] || { buys: 0, sells: 0, net: 0 };
                        return (
                          <td
                            key={w.key}
                            style={{ textAlign: "right", fontFamily: "var(--mono)" }}
                            title={`${win.buys} buys / ${win.sells} sells`}
                          >
                            <span style={{ color: netColor(win.net), fontWeight: 600 }}>
                              {fmtNet(win.net)}
                            </span>
                            <span className="muted" style={{ fontSize: "0.64rem", marginLeft: 4 }}>
                              ({win.buys}/{win.sells})
                            </span>
                          </td>
                        );
                      })}
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {asset.leagueCount}
                      </td>
                    </tr>,
                    expanded ? (
                      <tr key={`${asset.assetId}::detail`}>
                        <td colSpan={3 + WINDOW_COLUMNS.length} style={{ background: "rgba(255,255,255,0.02)" }}>
                          <MemberExposure assetId={asset.assetId} />
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
