"use client";

// OverviewSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { Avatar, Card, EmptyCard, LinkButton, ManagerInline, Stat, fmtPoints, nameFor } from "../shared.jsx";

function streakTypeDescription(type, length) {
  switch (type) {
    case "winStreak":
      return `${length} straight wins`;
    case "lossStreak":
      return `${length} straight losses`;
    case "plus100Streak":
      return `${length} weeks ≥ 100 pts`;
    case "plus120Streak":
      return `${length} weeks ≥ 120 pts`;
    case "plus140Streak":
      return `${length} weeks ≥ 140 pts`;
    default:
      return `${length} in a row`;
  }
}

function OverviewSection({ managers, data, onNavigate }) {
  if (!data || Object.keys(data).length === 0) return <EmptyCard label="Overview" />;

  const champ = data.currentChampion;
  const rivalry = data.featuredRivalry;
  const records = data.topRecordCallouts || [];
  const recent = data.recentTrades || [];
  const draftLeader = data.draftCapitalLeader;
  const recap = data.latestWeeklyRecap;
  const decorated = data.mostDecoratedFranchise;
  const chaos = data.mostChaoticManager;
  const hottest = data.hottestRace;
  const vitals = data.leagueVitals || {};
  const hottestTrade = data.hottestTrade;
  // v2 Home callouts (PR #87).
  const powerLeader = data.currentPowerLeader;
  const luckyUnlucky = data.luckyUnluckyCurrent;
  const activeStreak = data.activeStreakHighlight;
  const recordInReach = data.recordInReach;
  const upcomingWeek = data.upcomingWeekPreview;
  const latestFullRecap = data.latestFullRecap;

  return (
    <>
      <Card title="At a glance" subtitle="Public snapshot across the last 2 dynasty seasons">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
          <Stat label="Seasons" value={vitals.seasonsCovered ?? "—"} sub={data.seasonRangeLabel} />
          <Stat label="Managers" value={vitals.managers ?? "—"} />
          <Stat label="Trades" value={vitals.totalTrades ?? "—"} />
          <Stat label="Waivers" value={vitals.totalWaivers ?? "—"} />
          <Stat label="Scored weeks" value={vitals.totalScoredWeeks ?? "—"} />
        </div>
      </Card>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {champ && (
          <div className="card" style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Defending champion
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={champ.ownerId} size={42} />
              <div>
                <div style={{ fontSize: "1.3rem", fontWeight: 800, lineHeight: 1.15 }}>
                  {champ.displayName}
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--subtext)" }}>
                  {champ.teamName} · {champ.season} title
                </div>
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("history")}>View championship history →</LinkButton>
            </div>
          </div>
        )}
        {rivalry && (
          <div className="card" style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Featured rivalry · hottest index
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={rivalry.ownerIds[0]} size={28} />
              <span style={{ color: "var(--subtext)", fontWeight: 700 }}>vs</span>
              <Avatar managers={managers} ownerId={rivalry.ownerIds[1]} size={28} />
              <span style={{ fontSize: "1rem", fontWeight: 800, marginLeft: 6 }}>
                {nameFor(managers, rivalry.ownerIds[0])} vs {nameFor(managers, rivalry.ownerIds[1])}
              </span>
            </div>
            <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginTop: 4 }}>
              {rivalry.totalMeetings} meetings · {rivalry.playoffMeetings} playoff · Rivalry Index {rivalry.rivalryIndex}
            </div>
            <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 4 }}>
              Series: {rivalry.winsA}–{rivalry.winsB}{rivalry.ties ? `–${rivalry.ties}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("rivalries")}>Explore rivalries →</LinkButton>
            </div>
          </div>
        )}
      </div>

      {/* v2 Home rail: This Week + current Power + Luck + Active Streak */}
      {(upcomingWeek || powerLeader || luckyUnlucky || activeStreak || recordInReach || latestFullRecap) && (
        <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
          {upcomingWeek && (
            <div className="card" style={{ flex: "1 1 300px", minWidth: 260 }}>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {upcomingWeek.mode === "preview"
                  ? `This week · ${upcomingWeek.season} Wk ${upcomingWeek.week}`
                  : `Most recent · ${upcomingWeek.season} Wk ${upcomingWeek.week}`}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                <Avatar managers={managers} ownerId={upcomingWeek.home?.ownerId} size={28} />
                <span style={{ color: "var(--subtext)", fontWeight: 700 }}>
                  {upcomingWeek.mode === "recap" ? "vs" : "@"}
                </span>
                <Avatar managers={managers} ownerId={upcomingWeek.away?.ownerId} size={28} />
              </div>
              <div style={{ fontSize: "0.98rem", fontWeight: 800, marginTop: 4 }}>
                {upcomingWeek.home?.displayName} vs {upcomingWeek.away?.displayName}
              </div>
              {upcomingWeek.h2h?.narrative && (
                <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4 }}>
                  {upcomingWeek.h2h.narrative}
                </div>
              )}
              <div style={{ marginTop: 10 }}>
                <LinkButton onClick={() => onNavigate("matchupPreview")}>Full H2H preview →</LinkButton>
              </div>
            </div>
          )}
          {powerLeader && (
            <div className="card" style={{ flex: "1 1 240px", minWidth: 220 }}>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Power rank #1
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                <Avatar managers={managers} ownerId={powerLeader.ownerId} size={36} />
                <div>
                  <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{powerLeader.displayName}</div>
                  <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>{powerLeader.teamName}</div>
                </div>
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.8rem", marginTop: 6 }}>
                Power <strong style={{ color: "#2ecc71" }}>{fmtPoints(powerLeader.power)}</strong>
                <span style={{ color: "var(--subtext)", marginLeft: 8 }}>{powerLeader.record}</span>
                {powerLeader.weekRankDelta > 0 && (
                  <span style={{ color: "#2ecc71", marginLeft: 8 }}>▲{powerLeader.weekRankDelta}</span>
                )}
                {powerLeader.weekRankDelta < 0 && (
                  <span style={{ color: "#ff6b6b", marginLeft: 8 }}>▼{Math.abs(powerLeader.weekRankDelta)}</span>
                )}
              </div>
              <div style={{ marginTop: 10 }}>
                <LinkButton onClick={() => onNavigate("power")}>Power rankings →</LinkButton>
              </div>
            </div>
          )}
          {luckyUnlucky && (
            <div className="card" style={{ flex: "1 1 240px", minWidth: 220 }}>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Luck Δ · {luckyUnlucky.season}
              </div>
              {luckyUnlucky.lucky && (
                <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  <Avatar managers={managers} ownerId={luckyUnlucky.lucky.ownerId} size={22} />
                  <div style={{ flex: 1, fontSize: "0.78rem" }}>
                    <strong>{luckyUnlucky.lucky.displayName}</strong>
                    <span style={{ color: "#2ecc71", marginLeft: 6, fontFamily: "var(--mono)" }}>
                      +{fmtPoints(luckyUnlucky.lucky.luckDelta)}
                    </span>
                  </div>
                </div>
              )}
              {luckyUnlucky.unlucky && (
                <div style={{ marginTop: 6, display: "flex", alignItems: "center", gap: 8 }}>
                  <Avatar managers={managers} ownerId={luckyUnlucky.unlucky.ownerId} size={22} />
                  <div style={{ flex: 1, fontSize: "0.78rem" }}>
                    <strong>{luckyUnlucky.unlucky.displayName}</strong>
                    <span style={{ color: "#ff6b6b", marginLeft: 6, fontFamily: "var(--mono)" }}>
                      {fmtPoints(luckyUnlucky.unlucky.luckDelta)}
                    </span>
                  </div>
                </div>
              )}
              <div style={{ marginTop: 10 }}>
                <LinkButton onClick={() => onNavigate("luck")}>Luck score →</LinkButton>
              </div>
            </div>
          )}
          {activeStreak && (
            <div className="card" style={{ flex: "1 1 240px", minWidth: 220 }}>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Longest active streak
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
                <Avatar managers={managers} ownerId={activeStreak.ownerId} size={32} />
                <div>
                  <div style={{ fontSize: "0.98rem", fontWeight: 800 }}>{activeStreak.displayName}</div>
                  <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
                    {streakTypeDescription(activeStreak.type, activeStreak.length)}
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 10 }}>
                <LinkButton onClick={() => onNavigate("streaks")}>All streaks →</LinkButton>
              </div>
            </div>
          )}
          {recordInReach && (
            <div
              className="card"
              style={{
                flex: "1 1 240px",
                minWidth: 220,
                borderLeft: (recordInReach.chaser?.withinReach ? "3px solid var(--amber)" : undefined),
              }}
            >
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {recordInReach.chaser?.withinReach ? "Record within reach" : "Record in the hunt"}
              </div>
              <div style={{ fontSize: "0.86rem", fontWeight: 700, marginTop: 4 }}>
                {recordInReach.label}
              </div>
              {recordInReach.holder && (
                <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4 }}>
                  Holder: <strong>{nameFor(managers, recordInReach.holder.ownerId) || recordInReach.holder.displayName}</strong>{" "}
                  ({recordInReach.holder.valueLabel})
                </div>
              )}
              {recordInReach.chaser && (
                <div style={{ fontSize: "0.72rem", color: "var(--amber)", marginTop: 2 }}>
                  Chaser: <strong>{nameFor(managers, recordInReach.chaser.ownerId) || recordInReach.chaser.displayName}</strong>{" "}
                  ({recordInReach.chaser.valueLabel})
                </div>
              )}
              <div style={{ marginTop: 10 }}>
                <LinkButton onClick={() => onNavigate("streaks")}>See all →</LinkButton>
              </div>
            </div>
          )}
          {latestFullRecap && (
            <div className="card" style={{ flex: "1 1 300px", minWidth: 260 }}>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Week in review · {latestFullRecap.season} Wk {latestFullRecap.week}
              </div>
              <div style={{ fontSize: "0.98rem", fontWeight: 800, marginTop: 4, lineHeight: 1.3 }}>
                {latestFullRecap.headline}
              </div>
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4, lineHeight: 1.45 }}>
                {latestFullRecap.summary}
              </div>
              <div style={{ marginTop: 10, display: "flex", gap: 8 }}>
                <LinkButton onClick={() => onNavigate("weeklyRecap")}>All recaps →</LinkButton>
              </div>
            </div>
          )}
        </div>
      )}

      {records.length > 0 && (
        <Card title="Headline records" subtitle="Biggest numbers in the last 2 seasons">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
            {records.map((r, i) => (
              <div key={i} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
                <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {r.label}
                </div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, fontFamily: "var(--mono)" }}>
                  {r.formattedValue}
                </div>
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 2 }}>
                  <ManagerInline managers={managers} ownerId={r.ownerId} compact />
                  {r.season ? <span style={{ marginLeft: 4 }}>· {r.season}</span> : null}
                  {r.week ? <span style={{ marginLeft: 4 }}>· Wk {r.week}</span> : null}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10 }}>
            <LinkButton onClick={() => onNavigate("records")}>Full record book →</LinkButton>
          </div>
        </Card>
      )}

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {hottest && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Hot race · season to date
            </div>
            <div style={{ fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>{hottest.label}</div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>{hottest.description}</div>
            <div style={{ marginTop: 10, fontSize: "0.9rem", fontWeight: 700 }}>
              <ManagerInline managers={managers} ownerId={hottest.topLeader?.ownerId} />
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("awards")}>See all races →</LinkButton>
            </div>
          </div>
        )}
        {decorated && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Most decorated franchise
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={decorated.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{decorated.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              {decorated.championships}× champ · {decorated.finalsAppearances} finals · {decorated.playoffAppearances} playoffs
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("franchise", { owner: decorated.ownerId })}>
                Open franchise page →
              </LinkButton>
            </div>
          </div>
        )}
        {chaos && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Most chaotic manager
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={chaos.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{chaos.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              Chaos score {chaos.score ?? "—"}{chaos.season ? ` · ${chaos.season}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("activity")}>See trade activity →</LinkButton>
            </div>
          </div>
        )}
      </div>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {draftLeader && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Best draft stockpile
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={draftLeader.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{draftLeader.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              {draftLeader.totalPicks} picks · Weighted score {draftLeader.weightedScore}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("draft", { owner: draftLeader.ownerId })}>
                Full draft center →
              </LinkButton>
            </div>
          </div>
        )}
        {recap && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Latest weekly recap
            </div>
            <div style={{ fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>
              {recap.season} · Week {recap.week}{recap.isPlayoff ? " (playoffs)" : ""}
            </div>
            {recap.gameOfTheWeek && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4 }}>
                Game of the week: {recap.gameOfTheWeek.home?.displayName} vs {recap.gameOfTheWeek.away?.displayName} (margin {fmtPoints(recap.gameOfTheWeek.margin)})
              </div>
            )}
            {recap.highestScorer && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
                Top scorer: {recap.highestScorer.displayName} ({fmtPoints(recap.highestScorer.points)})
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("weekly", { week: `${recap.season}:${recap.week}` })}>
                Open weekly recap →
              </LinkButton>
            </div>
          </div>
        )}
        {hottestTrade && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Hottest trade · biggest blockbuster
            </div>
            <div style={{ fontSize: "0.94rem", fontWeight: 700, marginTop: 4 }}>
              {hottestTrade.sides.map((s) => s.displayName).join(" ↔ ")}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
              {hottestTrade.totalAssets} total assets · {hottestTrade.season} {hottestTrade.week ? `Wk ${hottestTrade.week}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("activity")}>Open trade center →</LinkButton>
            </div>
          </div>
        )}
      </div>

      {recent.length > 0 && (
        <Card title="Recent trades" subtitle="Last 5 completed deals">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {recent.map((t) => (
              <div
                key={t.transactionId}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}
              >
                <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
                  {t.season} · Week {t.week ?? "—"} · {t.totalAssets} asset{t.totalAssets === 1 ? "" : "s"}
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
                  {t.sides.map((s, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Avatar managers={managers} ownerId={s.ownerId} size={18} />
                      <span style={{ fontWeight: 700 }}>{s.displayName}</span>
                      <span style={{ color: "var(--subtext)", marginLeft: 2, fontSize: "0.7rem" }}>
                        received {s.receivedPlayerCount} players · {s.receivedPickCount} picks
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10 }}>
            <LinkButton onClick={() => onNavigate("activity")}>View all trades →</LinkButton>
          </div>
        </Card>
      )}
    </>
  );
}

export default OverviewSection;
