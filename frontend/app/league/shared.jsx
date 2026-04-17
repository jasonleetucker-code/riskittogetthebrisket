"use client";

// Shared UI helpers used by the tabbed /league page AND the dedicated
// /league/franchise/[owner] + /league/rivalry/[pair] routes.  Keeping
// formatters + Avatar + primitive cards in one place means the deep-
// linked routes and the tab views render identically.
//
// No private imports: see frontend/app/league/page.jsx for the
// isolation contract.  Only pulls from public-league-data.

export function buildManagerLookup(league) {
  const map = new Map();
  for (const m of league?.managers || []) {
    map.set(String(m.ownerId), m);
  }
  return map;
}

export function nameFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  return mgr?.displayName || mgr?.currentTeamName || ownerId || "Unknown";
}

export function avatarUrlFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  if (!mgr || !mgr.avatar) return "";
  const avatar = String(mgr.avatar);
  if (avatar.startsWith("http")) return avatar;
  return `https://sleepercdn.com/avatars/thumbs/${avatar}`;
}

export function fmtNumber(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtPoints(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(1);
}

export function fmtPercent(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n) * 100)}%`;
}

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
