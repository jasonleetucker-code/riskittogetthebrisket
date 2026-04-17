// Server-safe UI primitives for /league pages.  These are purely
// declarative — no hooks, no onClick state closures — so they can be
// rendered either from a React Server Component or a Client Component.
//
// The client-only equivalents (with onClick handlers + useState-backed
// state) live in shared.jsx with a "use client" directive.

import { avatarUrlFor, nameFor, fmtPoints } from "./shared-helpers.js";

export function Avatar({ managers, ownerId, size = 24, title }) {
  const url = avatarUrlFor(managers, ownerId);
  const name = nameFor(managers, ownerId);
  const initials = name
    .split(/\s+/)
    .map((w) => w[0] || "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
  const style = {
    width: size,
    height: size,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--bg-soft)",
    border: "1px solid var(--border)",
    fontSize: Math.max(10, Math.floor(size * 0.42)),
    fontWeight: 700,
    overflow: "hidden",
    flexShrink: 0,
    verticalAlign: "middle",
  };
  if (url) {
    return (
      <img
        src={url}
        alt=""
        loading="lazy"
        width={size}
        height={size}
        style={{ ...style, background: "transparent" }}
        title={title || name}
      />
    );
  }
  return (
    <span style={style} title={title || name} aria-hidden>
      {initials || "?"}
    </span>
  );
}

export function Card({ title, subtitle, action, children, id }) {
  return (
    <div className="card" id={id} style={{ marginTop: "var(--space-md)" }}>
      {(title || action) && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: 10,
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <div>
            {title && <div style={{ fontWeight: 700 }}>{title}</div>}
            {subtitle && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
                {subtitle}
              </div>
            )}
          </div>
          {action}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

export function Stat({ label, value, sub }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        background: "rgba(15, 28, 59, 0.45)",
      }}
    >
      <div
        style={{
          fontSize: "0.65rem",
          color: "var(--subtext)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: "1.05rem",
          fontWeight: 700,
          fontFamily: "var(--mono)",
          marginTop: 2,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function MeetingCard({ label, meeting }) {
  if (!meeting) return null;
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.86rem", fontWeight: 700, marginTop: 2 }}>
        {meeting.season} · Wk {meeting.week}{meeting.isPlayoff ? " (P)" : ""}
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
        Margin {fmtPoints(meeting.margin)} · {fmtPoints(meeting.pointsA)} / {fmtPoints(meeting.pointsB)}
      </div>
    </div>
  );
}
