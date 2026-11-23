// "Championship rings" card on the public player journey (owner directive
// 2026-11-23, "BUILD THE RING CLUB").
//
// Server-rendered, like the rest of this page, and styled the way this page
// already is (inline styles on the shared League Hub tokens) — no CSS module
// and no client component, so the route ships no new JavaScript.  The
// backend owns the ring count, the championships and the Ring Club
// membership; this card renders them and renders nothing for zero rings or
// an older payload without the block.

import Link from "next/link";
import { Avatar, Card } from "../../shared-server.jsx";
import { playerCoverageNote, ringCount, ringsAriaLabel, trophyRun } from "@/lib/ring-club";

export default function ChampionshipRingsCard({ championshipRings, managers }) {
  const cr = championshipRings;
  if (!cr || typeof cr !== "object") return null;
  const n = ringCount(cr.rings);
  if (n < 1) return null;
  const championships = Array.isArray(cr.championships) ? cr.championships : [];
  const note = playerCoverageNote(cr);

  return (
    <Card
      title="Championship rings"
      subtitle="One ring for each season on the championship-winning roster when the title was decided"
    >
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <span style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>Championship Rings:</span>
        <span
          role="img"
          aria-label={ringsAriaLabel(n)}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: "1rem" }}
        >
          <span style={{ fontWeight: 800, fontFamily: "var(--mono)" }}>{n}</span>
          <span style={{ letterSpacing: 1 }}>{trophyRun(n)}</span>
        </span>
        {/* The ds Badge's own markup rather than the component: Badge.jsx is
            a "use client" module, and its client reference put ~13 KB of JS
            on this server-rendered route (measured).  Same classes and
            tokens, no JS. */}
        {cr.ringClubMember === true ? (
          <span className="ds-badge ds-badge--accent">Ring Club member</span>
        ) : null}
      </div>

      {championships.length > 0 && (
        <ul
          aria-label="Championship seasons"
          style={{ listStyle: "none", margin: "10px 0 0", padding: 0, display: "flex", flexDirection: "column", gap: 6 }}
        >
          {championships.map((c, i) => {
            const label = (
              <>
                <span style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>{c.season}</span>
                {c.ownerId && managers ? <Avatar managers={managers} ownerId={c.ownerId} size={22} /> : null}
                <span>{c.teamName || "—"}</span>
                {c.displayName ? (
                  <span style={{ color: "var(--subtext)", fontWeight: 500 }}>{c.displayName}</span>
                ) : null}
              </>
            );
            const rowStyle = { display: "inline-flex", alignItems: "center", flexWrap: "wrap", gap: 8 };
            return (
              <li key={`${c.season}-${c.ownerId || i}`}>
                {c.ownerId ? (
                  <Link
                    href={`/league/franchise/${encodeURIComponent(c.ownerId)}`}
                    style={{ ...rowStyle, color: "var(--cyan)", fontWeight: 600 }}
                  >
                    {label}
                  </Link>
                ) : (
                  <span style={rowStyle}>{label}</span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {note && (
        <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 10 }}>{note}</div>
      )}
    </Card>
  );
}
