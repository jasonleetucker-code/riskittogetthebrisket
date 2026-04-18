"use client";

// WeeklyRecapSection — "Recaps" tab on /league.
//
// Grid of per-week recap cards ordered newest first.  Each card links
// to the full dedicated recap page at ``/league/week/[season]/[week]``.

import Link from "next/link";
import { Avatar, Card, EmptyCard, fmtNumber, nameFor } from "../shared.jsx";

function RecapCard({ recap, managers }) {
  const { season, week, isPlayoff, headline, summary, mvp, blowout, nailBiter, badBeat, matchups, trades } = recap;
  return (
    <Link
      href={`/league/week/${encodeURIComponent(season)}/${encodeURIComponent(week)}`}
      style={{
        textDecoration: "none",
        color: "inherit",
        display: "block",
      }}
    >
      <div
        className="card"
        style={{
          cursor: "pointer",
          transition: "border-color 0.15s",
          height: "100%",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 8,
          }}
        >
          <div>
            <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {season} · Week {week}{isPlayoff ? " · playoffs" : ""}
            </div>
            <div style={{ fontSize: "1.02rem", fontWeight: 700, marginTop: 2, lineHeight: 1.25 }}>
              {headline}
            </div>
          </div>
          <span
            style={{
              background: "var(--bg-subtle)",
              color: "var(--cyan)",
              padding: "3px 8px",
              borderRadius: 10,
              fontSize: "0.62rem",
              whiteSpace: "nowrap",
            }}
          >
            Read →
          </span>
        </div>

        <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginTop: 8, lineHeight: 1.45 }}>
          {summary}
        </div>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 8,
            marginTop: 10,
          }}
        >
          {mvp && (
            <MiniStat
              label="Weekly MVP"
              color="#2ecc71"
              managers={managers}
              ownerId={mvp.ownerId}
              value={`${fmtNumber(mvp.points, 1)} pts`}
            />
          )}
          {blowout && (
            <MiniStat
              label="Blowout"
              color="#ffa726"
              managers={managers}
              ownerId={blowout.winner.ownerId}
              value={`+${fmtNumber(blowout.margin, 1)}`}
            />
          )}
          {nailBiter && (
            <MiniStat
              label="Nailbiter"
              color="#4fc3f7"
              managers={managers}
              ownerId={nailBiter.winner.ownerId}
              value={`${fmtNumber(nailBiter.margin, 2)} margin`}
            />
          )}
          {badBeat && (
            <MiniStat
              label="Bad beat"
              color="#ff6b6b"
              managers={managers}
              ownerId={badBeat.ownerId}
              value={`${fmtNumber(badBeat.points, 1)} in L`}
            />
          )}
        </div>

        <div
          style={{
            fontSize: "0.64rem",
            color: "var(--subtext)",
            marginTop: 8,
            display: "flex",
            gap: 10,
          }}
        >
          <span>
            {matchups?.length || 0} matchup{(matchups?.length || 0) === 1 ? "" : "s"}
          </span>
          {(trades?.length || 0) > 0 && (
            <span style={{ color: "var(--cyan)" }}>
              · {trades.length} trade{trades.length === 1 ? "" : "s"} on the wire
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}

function MiniStat({ label, color, managers, ownerId, value }) {
  return (
    <div
      style={{
        padding: 6,
        borderLeft: `3px solid ${color}`,
        background: "var(--bg-subtle)",
        borderRadius: 4,
      }}
    >
      <div style={{ fontSize: "0.58rem", color: "var(--subtext)", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
        {ownerId && <Avatar managers={managers} ownerId={ownerId} size={18} />}
        <span style={{ fontSize: "0.74rem" }}>
          <strong>{nameFor(managers, ownerId)}</strong>{" "}
          <span style={{ color, fontFamily: "var(--mono)" }}>{value}</span>
        </span>
      </div>
    </div>
  );
}

export default function WeeklyRecapSection({ data, managers }) {
  if (!data || !data.weeks?.length) return <EmptyCard label="Weekly recaps" />;

  return (
    <section>
      <Card
        title="Weekly recaps"
        action={
          <span style={{ fontSize: "0.62rem", color: "var(--subtext)" }}>
            Click any card to read the full recap
          </span>
        }
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
            gap: 10,
          }}
        >
          {data.weeks.map((recap) => (
            <RecapCard
              key={`${recap.season}:${recap.week}`}
              recap={recap}
              managers={managers}
            />
          ))}
        </div>
      </Card>
    </section>
  );
}
