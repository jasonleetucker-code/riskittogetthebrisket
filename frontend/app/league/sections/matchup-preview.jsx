"use client";

// MatchupPreviewSection — "This Week" tab on /league.
//
// Renders the head-to-head matchup preview for the current (or most
// recently completed) week.  Each card shows both teams, all-time H2H
// summary, the last 5 meetings, and each side's recent-form capsule.

import { Avatar, Card, EmptyCard, fmtNumber, nameFor } from "../shared.jsx";

function FormCapsule({ label, form, managers, ownerId }) {
  if (!form) return null;
  const games = form.games || [];
  return (
    <div style={{ flex: 1, padding: 8, borderRadius: "var(--radius)", background: "var(--bg-subtle)" }}>
      <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
        <Avatar managers={managers} ownerId={ownerId} size={18} />
        <span style={{ fontSize: "0.78rem", fontWeight: 700 }}>
          {nameFor(managers, ownerId)}
        </span>
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 6, fontSize: "0.7rem" }}>
        <div>
          <div style={{ color: "var(--subtext)", fontSize: "0.6rem" }}>Last 3</div>
          <div style={{ fontFamily: "var(--mono)" }}>{form.record || "—"}</div>
        </div>
        <div>
          <div style={{ color: "var(--subtext)", fontSize: "0.6rem" }}>Avg pts</div>
          <div style={{ fontFamily: "var(--mono)" }}>{fmtNumber(form.avgPoints, 1)}</div>
        </div>
      </div>
      {games.length > 0 && (
        <div style={{ display: "flex", gap: 4, marginTop: 6 }}>
          {games.map((g, i) => (
            <span
              key={i}
              title={`${g.season} wk ${g.week} · ${g.points} vs ${g.opponentPoints}`}
              style={{
                display: "inline-block",
                width: 14,
                height: 14,
                borderRadius: 2,
                background:
                  g.result === "W"
                    ? "#2ecc71"
                    : g.result === "L"
                      ? "#ff6b6b"
                      : "var(--subtext)",
                color: "white",
                fontSize: 9,
                textAlign: "center",
                lineHeight: "14px",
                fontWeight: 700,
              }}
            >
              {g.result}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function MeetingRow({ m, sideAOwnerId, sideBOwnerId, managers }) {
  const aligned = m.sideAOwnerId === sideAOwnerId;
  const aPts = aligned ? m.sideAPoints : m.sideBPoints;
  const bPts = aligned ? m.sideBPoints : m.sideAPoints;
  const winnerAligned = m.winnerOwnerId === sideAOwnerId;
  const winnerNeitherAligned = !m.winnerOwnerId;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "56px 1fr 1fr",
        gap: 6,
        padding: "4px 0",
        borderBottom: "1px solid var(--border)",
        fontSize: "0.72rem",
      }}
    >
      <div style={{ color: "var(--subtext)", fontFamily: "var(--mono)" }}>
        {m.season} wk{m.week}
        {m.isPlayoff && <span style={{ color: "var(--amber)" }}> P</span>}
      </div>
      <div
        style={{
          textAlign: "right",
          color: winnerAligned ? "#2ecc71" : winnerNeitherAligned ? "var(--subtext)" : "var(--subtext)",
          fontWeight: winnerAligned ? 700 : 400,
          fontFamily: "var(--mono)",
        }}
      >
        {nameFor(managers, sideAOwnerId)} {fmtNumber(aPts, 1)}
      </div>
      <div
        style={{
          color: !winnerAligned && !winnerNeitherAligned ? "#2ecc71" : winnerNeitherAligned ? "var(--subtext)" : "var(--subtext)",
          fontWeight: !winnerAligned && !winnerNeitherAligned ? 700 : 400,
          fontFamily: "var(--mono)",
        }}
      >
        {fmtNumber(bPts, 1)} {nameFor(managers, sideBOwnerId)}
      </div>
    </div>
  );
}

function MatchupCard({ m, managers, mode }) {
  const { home, away, h2h, form } = m;
  const isRecap = mode === "recap";
  const winnerSide =
    isRecap && home.points != null && away.points != null
      ? home.points > away.points
        ? "home"
        : away.points > home.points
          ? "away"
          : null
      : null;

  return (
    <div className="card" style={{ padding: 14 }}>
      {/* Matchup header */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 60px 1fr",
          alignItems: "center",
          gap: 12,
        }}
      >
        <TeamSide side={home} managers={managers} isWinner={winnerSide === "home"} isRecap={isRecap} align="right" />
        <div style={{ textAlign: "center", fontWeight: 700, color: "var(--subtext)" }}>
          {isRecap ? "vs" : "@"}
        </div>
        <TeamSide side={away} managers={managers} isWinner={winnerSide === "away"} isRecap={isRecap} align="left" />
      </div>

      {/* H2H narrative */}
      <div
        style={{
          marginTop: 10,
          padding: "6px 10px",
          background: "var(--bg-subtle)",
          borderRadius: 6,
          fontSize: "0.72rem",
          color: "var(--subtext)",
        }}
      >
        {h2h?.narrative}
      </div>

      {/* H2H summary row + form */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 10,
          marginTop: 10,
        }}
      >
        <div>
          <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase" }}>
            Series
          </div>
          <div style={{ fontSize: "0.85rem", fontWeight: 700, marginTop: 2 }}>
            {h2h.homeWins}-{h2h.awayWins}
            {h2h.ties > 0 && `-${h2h.ties}`}
          </div>
          <div style={{ fontSize: "0.64rem", color: "var(--subtext)", marginTop: 2 }}>
            {h2h.totalMeetings} meeting{h2h.totalMeetings === 1 ? "" : "s"}
            {h2h.playoffMeetings > 0 && ` · ${h2h.playoffMeetings} playoff`}
          </div>
        </div>
        <div>
          <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase" }}>
            Avg margin
          </div>
          <div style={{ fontSize: "0.85rem", fontWeight: 700, marginTop: 2 }}>
            {fmtNumber(h2h.avgMargin, 1)} pts
          </div>
          <div style={{ fontSize: "0.64rem", color: "var(--subtext)", marginTop: 2 }}>
            biggest {fmtNumber(h2h.biggestMargin, 1)}
          </div>
        </div>
        <FormCapsule label="Home form" form={form.home} managers={managers} ownerId={home.ownerId} />
        <FormCapsule label="Away form" form={form.away} managers={managers} ownerId={away.ownerId} />
      </div>

      {/* Last 5 meetings */}
      {h2h.last5 && h2h.last5.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase", marginBottom: 4 }}>
            Last {h2h.last5.length} meeting{h2h.last5.length === 1 ? "" : "s"}
          </div>
          <div>
            {h2h.last5.map((meet, i) => (
              <MeetingRow
                key={`${meet.season}-${meet.week}-${i}`}
                m={meet}
                sideAOwnerId={home.ownerId}
                sideBOwnerId={away.ownerId}
                managers={managers}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TeamSide({ side, managers, isWinner, isRecap, align }) {
  return (
    <div style={{ textAlign: align }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: align === "right" ? "flex-end" : "flex-start",
          gap: 8,
        }}
      >
        {align === "left" && <Avatar managers={managers} ownerId={side.ownerId} size={28} />}
        <div style={{ textAlign: align }}>
          <div style={{ fontWeight: 700 }}>{nameFor(managers, side.ownerId)}</div>
          <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>{side.teamName}</div>
        </div>
        {align === "right" && <Avatar managers={managers} ownerId={side.ownerId} size={28} />}
      </div>
      {isRecap && side.points != null && (
        <div
          style={{
            fontFamily: "var(--mono)",
            fontSize: "1.3rem",
            fontWeight: 800,
            color: isWinner ? "#2ecc71" : "var(--subtext)",
            marginTop: 4,
          }}
        >
          {fmtNumber(side.points, 1)}
        </div>
      )}
    </div>
  );
}

export default function MatchupPreviewSection({ data, managers, onNavigate }) {
  if (!data || !data.matchups?.length) return <EmptyCard label="This week's matchups" />;
  const { currentSeason, currentWeek, mode, isPlayoff, matchups } = data;

  const title =
    mode === "preview"
      ? `${currentSeason} · Week ${currentWeek} preview`
      : `${currentSeason} · Week ${currentWeek}${isPlayoff ? " (playoffs)" : ""} — results`;

  return (
    <section>
      <Card
        title={title}
        action={
          <span style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
            {mode === "preview"
              ? "Head-to-head history + recent form for the upcoming slate"
              : "Head-to-head context for the most recently completed week"}
          </span>
        }
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            gap: 12,
          }}
        >
          {matchups.map((m) => (
            <MatchupCard
              key={`${m.home.ownerId}-${m.away.ownerId}`}
              m={m}
              managers={managers}
              mode={mode}
            />
          ))}
        </div>
      </Card>
    </section>
  );
}
