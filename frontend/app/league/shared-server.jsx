// Server-safe UI primitives for /league pages.  These are purely
// declarative — no hooks, no onClick state closures — so they can be
// rendered either from a React Server Component or a Client Component.
//
// The client-only equivalents (with onClick handlers + useState-backed
// state) live in shared.jsx with a "use client" directive.

import { avatarUrlFor, nameFor, fmtPoints } from "./shared-helpers.js";
// Imported from the MODULE, not the @/components/ds barrel, on purpose:
// the barrel re-exports CollapsiblePanel, which carries a client
// directive, and pulling that into this server module would drag it
// into the server graph for nothing.  ds Panel/StatTile are both
// hook-free and server-safe (Panel pinned by
// __tests__/components/ds/panel-server-safe.test.js; StatTile has no
// hooks or client-only APIs at all).
import { Panel } from "@/components/ds/Panel";
import { StatTile } from "@/components/ds/StatTile";
import styles from "./league-shared.module.css";

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

/**
 * The /league container. Now a thin adapter over ds `Panel` — R5 phase A.
 *
 * Every one of its ~70 call sites is unchanged: the prop shape is kept
 * (`action` singular maps to Panel's `actions`, `id` rides through), so
 * this one edit migrates the whole surface.
 *
 * `className="league-card"` carries the vertical rhythm that used to be
 * an inline `marginTop`. Panel sets no margins by design — spacing
 * belongs to the page — but the /league sections render sequential
 * Cards with no stack container, so dropping it would collapse the
 * spacing on all 70. The `.league-card` rule is explicitly INTERIM and
 * deletes in one line once phase B gives each section a real gap.
 *
 * Heading: Panel renders a real <h2> where this used to render a bare
 * bold div. Verified safe before switching — a depth scan of every
 * <Card>/</Card> pair across app/league found no nesting anywhere (max
 * depth 1), so these are all siblings under each page's <h1>.
 */
export function Card({ title, subtitle, action, children, id }) {
  return (
    <Panel
      className="league-card"
      id={id}
      title={title}
      subtitle={subtitle}
      actions={action}
    >
      {children}
    </Panel>
  );
}

/**
 * Thin adapter over ds `StatTile` — R5 phase B. Same prop shape every
 * call site already uses (`label` / `value` / `sub`); StatTile's `meta`
 * slot is the direct equivalent of `sub`. Presentation only: value/label
 * text is unchanged, only the box (tokens, radius, tabular-nums data
 * face) moves onto the shared primitive instead of a bespoke inline
 * style with a raw `rgba(15, 28, 59, 0.45)` fill.
 */
export function Stat({ label, value, sub }) {
  return <StatTile label={label} value={value} meta={sub} />;
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
    <div className={styles.miniCardPoints}>
      <span className={meeting.winnerSide === "A" ? styles.miniCardWinner : undefined}>
        {nameA} {fmtPoints(meeting.pointsA)}
      </span>
      {" · "}
      <span className={meeting.winnerSide === "B" ? styles.miniCardWinner : undefined}>
        {nameB} {fmtPoints(meeting.pointsB)}
      </span>
    </div>
  ) : (
    <div className={styles.miniCardPoints}>
      Margin {fmtPoints(meeting.margin)} · {fmtPoints(meeting.pointsA)} / {fmtPoints(meeting.pointsB)}
    </div>
  );
  return (
    <div className={styles.miniCard}>
      <div className={styles.miniCardLabel}>{label}</div>
      <div className={styles.miniCardValue}>
        {meeting.season} · {weekLabel}{meeting.isPlayoff ? " (P)" : ""}
      </div>
      {outcomeLine && (
        <div className={styles.miniCardAccent}>
          {outcomeLine} by {fmtPoints(meeting.margin)}
        </div>
      )}
      {pointsLine}
    </div>
  );
}
