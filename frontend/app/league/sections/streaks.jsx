"use client";

// StreaksSection — "Streaks" tab on /league.
//
// Three sections, top to bottom:
//   * "Records are falling" — records-in-reach: the all-time holder
//     plus the current-season chaser (if any), with a within-reach flag.
//   * "Notable this week" — the most recently scored week's games that
//     cracked the all-time top-5 in a category.
//   * "Active streaks" — per owner, their trailing W/L/100+/120+/140+
//     run of consecutive games.
//
// Reads strictly from ``sections.streaks`` of the public contract.

import { Avatar, Card, EmptyCard, nameFor } from "../shared.jsx";

function StreakTypeLabel(type) {
  switch (type) {
    case "winStreak":
      return { label: "Win streak", color: "#2ecc71", suffix: "W" };
    case "lossStreak":
      return { label: "Loss streak", color: "#ff6b6b", suffix: "L" };
    case "plus100Streak":
      return { label: "100+ streak", color: "#7bdfb3", suffix: "G" };
    case "plus120Streak":
      return { label: "120+ streak", color: "#4fc3f7", suffix: "G" };
    case "plus140Streak":
      return { label: "140+ streak", color: "#ffa726", suffix: "G" };
    default:
      return { label: type, color: "var(--subtext)", suffix: "" };
  }
}

function RecordCard({ rec, managers }) {
  const { holder, chaser, label } = rec;
  const inReach = chaser?.withinReach;
  return (
    <div
      className="card"
      style={{
        borderLeft: inReach ? "3px solid var(--amber)" : "3px solid transparent",
      }}
    >
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <Avatar managers={managers} ownerId={holder.ownerId} size={22} />
        <div style={{ flex: 1 }}>
          <div style={{ fontWeight: 700 }}>{nameFor(managers, holder.ownerId) || holder.displayName}</div>
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
            {holder.valueLabel}
            {holder.season && ` · ${holder.season}${holder.week ? ` wk ${holder.week}` : ""}`}
          </div>
        </div>
      </div>
      {chaser && (
        <div style={{ marginTop: 8, borderTop: "1px dashed var(--border)", paddingTop: 6 }}>
          <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase" }}>
            Closest chaser
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
            <Avatar managers={managers} ownerId={chaser.ownerId} size={18} />
            <div style={{ flex: 1, fontSize: "0.78rem" }}>
              <strong>{nameFor(managers, chaser.ownerId) || chaser.displayName}</strong>
              <span style={{ color: inReach ? "var(--amber)" : "var(--subtext)", marginLeft: 6 }}>
                {chaser.valueLabel}
              </span>
              {chaser.gap !== undefined && (
                <span style={{ color: "var(--subtext)", marginLeft: 6 }}>
                  ({chaser.gap > 0 ? `${chaser.gap} from record` : "tied or ahead"})
                </span>
              )}
            </div>
          </div>
          {inReach && (
            <div style={{ fontSize: "0.68rem", color: "var(--amber)", marginTop: 4, fontWeight: 700 }}>
              Within striking distance
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NotableRow({ n, managers }) {
  const cat = n.category;
  const color =
    cat === "highestSingleWeek" ? "#2ecc71"
    : cat === "lowestSingleWeek" ? "#ff6b6b"
    : cat === "biggestBlowout" ? "#4fc3f7"
    : cat === "badBeat" ? "#ffa726"
    : "var(--subtext)";
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <div style={{ color, fontFamily: "var(--mono)", fontWeight: 700, minWidth: 38, textAlign: "center" }}>
        #{n.rank}
      </div>
      <Avatar managers={managers} ownerId={n.ownerId} size={22} />
      <div style={{ flex: 1, fontSize: "0.78rem" }}>
        <strong>{nameFor(managers, n.ownerId) || n.displayName}</strong> —{" "}
        <span style={{ color: "var(--subtext)" }}>{n.label}</span>
      </div>
      <div style={{ fontFamily: "var(--mono)", color, fontWeight: 700 }}>
        {n.valueLabel}
      </div>
    </div>
  );
}

function ActiveStreakRow({ s, managers }) {
  const { label, color, suffix } = StreakTypeLabel(s.type);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "6px 0",
        borderBottom: "1px solid var(--border)",
      }}
    >
      <Avatar managers={managers} ownerId={s.ownerId} size={20} />
      <div style={{ flex: 1, fontSize: "0.78rem" }}>
        <strong>{nameFor(managers, s.ownerId) || s.displayName}</strong>
        <span style={{ color: "var(--subtext)", marginLeft: 8, fontSize: "0.66rem" }}>
          since {s.start?.season} wk {s.start?.week}
        </span>
      </div>
      <div
        style={{
          fontFamily: "var(--mono)",
          color,
          fontWeight: 700,
          minWidth: 64,
          textAlign: "right",
        }}
      >
        {s.length}{suffix} <span style={{ color: "var(--subtext)", fontWeight: 400, fontSize: "0.66rem" }}>{label}</span>
      </div>
    </div>
  );
}

export default function StreaksSection({ data, managers }) {
  if (!data) return <EmptyCard label="Streaks" />;
  const { activeStreaks = [], recordsInReach = [], notableThisWeek = [], latestWeek } = data;

  const hasContent = activeStreaks.length + recordsInReach.length + notableThisWeek.length > 0;
  if (!hasContent) return <EmptyCard label="Streaks" />;

  return (
    <section>
      {recordsInReach.length > 0 && (
        <Card
          title="Records are falling"
          action={
            <span style={{ fontSize: "0.62rem", color: "var(--subtext)" }}>
              Gold border = chaser is within striking distance
            </span>
          }
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 10,
            }}
          >
            {recordsInReach.map((r) => (
              <RecordCard key={r.category} rec={r} managers={managers} />
            ))}
          </div>
        </Card>
      )}

      {notableThisWeek.length > 0 && (
        <Card
          title={
            latestWeek
              ? `Notable from ${latestWeek.season} week ${latestWeek.week}`
              : "Notable from the latest week"
          }
        >
          <div>
            {notableThisWeek.map((n, i) => (
              <NotableRow key={`${n.category}-${n.ownerId}-${i}`} n={n} managers={managers} />
            ))}
          </div>
        </Card>
      )}

      {activeStreaks.length > 0 && (
        <Card title="Active streaks">
          <div>
            {activeStreaks.map((s) => (
              <ActiveStreakRow
                key={`${s.type}-${s.ownerId}`}
                s={s}
                managers={managers}
              />
            ))}
          </div>
          <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 10 }}>
            Trailing runs only — computed from each manager's most recent game, walking backwards until the streak breaks.
          </div>
        </Card>
      )}
    </section>
  );
}
