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

export function MeetingCard({ label, meeting, nameA, nameB }) {
  if (!meeting) return null;
  // Multi-week championship (e.g. 2-week final spanning wk16+17) —
  // render as "Wk 16-17" so users see the combined scope instead of
  // a misleading single week number.
  const weekLabel = Array.isArray(meeting.combinedWeeks) && meeting.combinedWeeks.length > 1
    ? `Wk ${meeting.combinedWeeks[0]}-${meeting.combinedWeeks[meeting.combinedWeeks.length - 1]}`
    : `Wk ${meeting.week}`;
  // Who-won attribution — when the caller threads both manager
  // names through, render "{winner} def. {loser}" so the card
  // answers the natural "who did what" question up front.
  let outcomeLine = null;
  if (nameA && nameB) {
    if (meeting.winnerSide === "A") {
      outcomeLine = `${nameA} def. ${nameB}`;
    } else if (meeting.winnerSide === "B") {
      outcomeLine = `${nameB} def. ${nameA}`;
    } else if (meeting.winnerSide === "T") {
      outcomeLine = `${nameA} tied ${nameB}`;
    }
  }
  // Points line, winner bolded when names are available.
  const pointsLine = nameA && nameB ? (
    <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
      <span style={{ fontWeight: meeting.winnerSide === "A" ? 700 : 400, color: meeting.winnerSide === "A" ? "var(--text)" : undefined }}>
        {nameA} {fmtPoints(meeting.pointsA)}
      </span>
      {" · "}
      <span style={{ fontWeight: meeting.winnerSide === "B" ? 700 : 400, color: meeting.winnerSide === "B" ? "var(--text)" : undefined }}>
        {nameB} {fmtPoints(meeting.pointsB)}
      </span>
    </div>
  ) : (
    <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
      Margin {fmtPoints(meeting.margin)} · {fmtPoints(meeting.pointsA)} / {fmtPoints(meeting.pointsB)}
    </div>
  );
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.86rem", fontWeight: 700, marginTop: 2 }}>
        {meeting.season} · {weekLabel}{meeting.isPlayoff ? " (P)" : ""}
      </div>
      {outcomeLine && (
        <div style={{ fontSize: "0.74rem", marginTop: 2, color: "var(--cyan)" }}>
          {outcomeLine} by {fmtPoints(meeting.margin)}
        </div>
      )}
      {pointsLine}
    </div>
  );
}
