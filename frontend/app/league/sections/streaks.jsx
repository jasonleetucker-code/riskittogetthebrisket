"use client";

// StreaksSection — "Streaks" tab on /league.
//
// Sections rendered:
//   * "Records are falling" — records-in-reach: the all-time holder
//     plus the current-season chaser (if any), with a within-reach flag.
//   * "Notable this week" — the most recently scored week's games that
//     cracked the all-time top-5 in a category.
//   * "Longest win streaks" + "Longest losing streaks" — top-5 of each.
//   * "Active streaks" — every manager's current trailing W/L run.
//
// Reads strictly from ``sections.streaks`` of the public contract.

import { Avatar, Card, EmptyCard, nameFor } from "../shared.jsx";

function StreakTypeLabel(type) {
  switch (type) {
    case "winStreak":
      return { label: "Win streak", color: "#2ecc71", suffix: "W" };
    case "lossStreak":
      return { label: "Loss streak", color: "#ff6b6b", suffix: "L" };
    case "tie":
      return { label: "Tie", color: "var(--subtext)", suffix: "T" };
    case "none":
      return { label: "No games", color: "var(--subtext)", suffix: "" };
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

function LongestStreakRow({ s, managers, color, suffix }) {
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
        {s.start && s.end && (
          <span style={{ color: "var(--subtext)", marginLeft: 8, fontSize: "0.66rem" }}>
            {s.start.season} wk {s.start.week} → {s.end.season} wk {s.end.week}
          </span>
        )}
      </div>
      <div
        style={{
          fontFamily: "var(--mono)",
          color,
          fontWeight: 700,
          minWidth: 40,
          textAlign: "right",
        }}
      >
        {s.length}{suffix}
      </div>
    </div>
  );
}

function CurrentStreakRow({ s, managers }) {
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
        {s.start && (
          <span style={{ color: "var(--subtext)", marginLeft: 8, fontSize: "0.66rem" }}>
            since {s.start.season} wk {s.start.week}
          </span>
        )}
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
        {s.length > 0 ? `${s.length}${suffix}` : "—"}{" "}
        <span style={{ color: "var(--subtext)", fontWeight: 400, fontSize: "0.66rem" }}>{label}</span>
      </div>
    </div>
  );
}

export default function StreaksSection({ data, managers }) {
  if (!data) return <EmptyCard label="Streaks" />;
  const {
    longestWinStreaks = [],
    longestLossStreaks = [],
    currentStreaksByOwner = [],
    recordsInReach = [],
    notableThisWeek = [],
    latestWeek,
  } = data;

  const hasContent =
    longestWinStreaks.length +
      longestLossStreaks.length +
      currentStreaksByOwner.length +
      recordsInReach.length +
      notableThisWeek.length > 0;
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

      {(longestWinStreaks.length > 0 || longestLossStreaks.length > 0) && (
        <Card title="Longest streaks · top 5 each">
          <div className="row">
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Win streaks</div>
              {longestWinStreaks.length === 0 ? (
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>—</div>
              ) : (
                longestWinStreaks.map((s) => (
                  <LongestStreakRow
                    key={`win-${s.ownerId}`}
                    s={s}
                    managers={managers}
                    color="#2ecc71"
                    suffix="W"
                  />
                ))
              )}
            </div>
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Losing streaks</div>
              {longestLossStreaks.length === 0 ? (
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>—</div>
              ) : (
                longestLossStreaks.map((s) => (
                  <LongestStreakRow
                    key={`loss-${s.ownerId}`}
                    s={s}
                    managers={managers}
                    color="#ff6b6b"
                    suffix="L"
                  />
                ))
              )}
            </div>
          </div>
        </Card>
      )}

      {currentStreaksByOwner.length > 0 && (
        <Card title="Current streak by manager">
          <div>
            {currentStreaksByOwner.map((s) => (
              <CurrentStreakRow
                key={`cur-${s.ownerId}`}
                s={s}
                managers={managers}
              />
            ))}
          </div>
          <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 10 }}>
            Each manager's current trailing run from their most recent game. A tie ends both win and loss streaks.
          </div>
        </Card>
      )}
    </section>
  );
}
