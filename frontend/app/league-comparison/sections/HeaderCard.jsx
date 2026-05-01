"use client";

/**
 * HeaderCard — top-of-page metadata block.
 *
 * Shows both league names + IDs (truncated for paranoid users), the
 * seasons that were included vs unavailable, the version, and the
 * generated-at timestamp.
 */
export default function HeaderCard({ data }) {
  const meta = data?.meta || {};
  const my = meta.myLeague || {};
  const base = meta.baselineLeague || {};
  const available = meta.seasonsAvailable || [];
  const unavailable = meta.seasonsUnavailable || [];
  const generatedAt = meta.generatedAt
    ? new Date(meta.generatedAt).toLocaleString()
    : "—";

  return (
    <div className="card">
      <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr" }}>
        <LeagueBlock title="My League" league={my} accent="cyan" />
        <LeagueBlock title="Standard Baseline" league={base} accent="gold" />
      </div>

      <div
        style={{
          marginTop: "var(--space-md)",
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--space-sm)",
          fontSize: "0.85rem",
        }}
      >
        <Tag label="Seasons included">
          {available.length > 0 ? available.join(", ") : "—"}
        </Tag>
        {unavailable.length > 0 && (
          <Tag label="Unavailable" tone="amber">
            {unavailable.join(", ")}
          </Tag>
        )}
        <Tag label="Version">{meta.version || "—"}</Tag>
        <Tag label="Generated">{generatedAt}</Tag>
        {meta.cacheHit && <Tag tone="muted">Cached</Tag>}
        {!meta.cacheHit && meta.computeMs != null && (
          <Tag tone="muted">Computed in {meta.computeMs} ms</Tag>
        )}
      </div>
    </div>
  );
}

function LeagueBlock({ title, league, accent }) {
  const accentColor = accent === "gold" ? "var(--gold, #FFC704)" : "var(--cyan, #38bdf8)";
  const id = league?.id || "";
  const idTrunc = id ? `${id.slice(0, 6)}…${id.slice(-4)}` : "—";
  return (
    <div>
      <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
        {title}
      </div>
      <div style={{ fontSize: "1.1rem", fontWeight: 700, color: accentColor, marginTop: 2 }}>
        {league?.name || "(unnamed)"}
      </div>
      <div className="muted text-xs" style={{ marginTop: 2, fontFamily: "var(--mono)" }} title={id}>
        {league?.label || ""} · ID {idTrunc} · hash {league?.scoringHash || "—"}
      </div>
    </div>
  );
}

function Tag({ label, children, tone }) {
  const color = tone === "amber" ? "var(--amber, #facc15)" : tone === "muted" ? "var(--muted)" : "var(--text)";
  return (
    <span
      style={{
        background: "rgba(255,255,255,0.04)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius-sm, 4px)",
        padding: "4px 8px",
        color,
      }}
    >
      {label && <span className="muted" style={{ marginRight: 4 }}>{label}:</span>}
      <strong>{children}</strong>
    </span>
  );
}
