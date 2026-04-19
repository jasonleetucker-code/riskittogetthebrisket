"use client";

// RivalriesSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useState } from "react";
import { Avatar, Card, EmptyCard, LinkButton, MeetingCard, Stat, fmtPoints, nameFor } from "../shared.jsx";

function RivalriesSection({ managers, data, onNavigate }) {
  const rows = data?.rivalries || [];
  const [selected, setSelected] = useState(0);
  if (!rows.length) return <EmptyCard label="Rivalries" />;

  const featured = rows.slice(0, 3);
  const detail = rows[selected] || null;

  return (
    <>
      <Card title="Top rivalries" subtitle="Ranked by rivalry index (playoffs + close games + splits + meetings)">
        <div className="row">
          {featured.map((r, i) => (
            <div
              key={i}
              className="card"
              style={{
                flex: "1 1 240px",
                cursor: "pointer",
                borderColor: selected === i ? "var(--cyan)" : "var(--border)",
              }}
              onClick={() => setSelected(i)}
            >
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)" }}>Rivalry Index {r.rivalryIndex}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                <Avatar managers={managers} ownerId={r.ownerIds[0]} size={22} />
                <span style={{ fontWeight: 700, fontSize: "0.9rem" }}>
                  {nameFor(managers, r.ownerIds[0])} vs {nameFor(managers, r.ownerIds[1])}
                </span>
                <Avatar managers={managers} ownerId={r.ownerIds[1]} size={22} />
              </div>
              <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 2 }}>
                {r.totalMeetings} meet · {r.playoffMeetings} playoff · Split seasons {r.seasonsWhereSeriesSplit}
              </div>
              <div style={{ fontSize: "0.72rem", marginTop: 4 }}>
                Series: {r.winsA}–{r.winsB}{r.ties ? `–${r.ties}` : ""}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {detail && (
        <Card
          title={`${nameFor(managers, detail.ownerIds[0])} vs ${nameFor(managers, detail.ownerIds[1])}`}
          subtitle="Head-to-head detail"
          action={
            <div style={{ display: "flex", gap: 6 }}>
              <LinkButton onClick={() => onNavigate("franchise", { owner: detail.ownerIds[0] })}>
                {nameFor(managers, detail.ownerIds[0])} page →
              </LinkButton>
              <LinkButton onClick={() => onNavigate("franchise", { owner: detail.ownerIds[1] })}>
                {nameFor(managers, detail.ownerIds[1])} page →
              </LinkButton>
            </div>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 14 }}>
            <Stat label="Meetings" value={detail.totalMeetings} sub={`${detail.regularSeasonMeetings} reg · ${detail.playoffMeetings} playoff`} />
            <Stat
              label="Series"
              value={`${detail.winsA}–${detail.winsB}${detail.ties ? `–${detail.ties}` : ""}`}
              sub={
                detail.winsA > detail.winsB
                  ? `${nameFor(managers, detail.ownerIds[0])} leads`
                  : detail.winsB > detail.winsA
                    ? `${nameFor(managers, detail.ownerIds[1])} leads`
                    : detail.totalMeetings > 0
                      ? "Tied"
                      : undefined
              }
            />
            <Stat
              label="Points"
              value={`${fmtPoints(detail.pointsA)} / ${fmtPoints(detail.pointsB)}`}
              sub={
                detail.pointsA > detail.pointsB
                  ? `${nameFor(managers, detail.ownerIds[0])} +${fmtPoints(detail.pointsA - detail.pointsB)}`
                  : detail.pointsB > detail.pointsA
                    ? `${nameFor(managers, detail.ownerIds[1])} +${fmtPoints(detail.pointsB - detail.pointsA)}`
                    : detail.totalMeetings > 0
                      ? "Even"
                      : undefined
              }
            />
            <Stat
              label="Close (≤5 pts)"
              value={detail.gamesDecidedByFive}
              sub={
                detail.gamesDecidedByFive === 0 && detail.totalMeetings > 0
                  ? "No nail-biters"
                  : "most decisive closeness band"
              }
            />
            <Stat
              label="Close (≤10 pts)"
              value={detail.gamesDecidedByTen}
              sub={
                detail.gamesDecidedByTen === 0 && detail.totalMeetings > 0
                  ? "No close games"
                  : undefined
              }
            />
          </div>

          <div style={{ fontWeight: 600, marginBottom: 6 }}>Memorable meetings</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
            <MeetingCard
              label="Closest"
              meeting={detail.closestGame}
              nameA={nameFor(managers, detail.ownerIds[0])}
              nameB={nameFor(managers, detail.ownerIds[1])}
            />
            <MeetingCard
              label="Biggest blowout"
              meeting={detail.biggestBlowout}
              nameA={nameFor(managers, detail.ownerIds[0])}
              nameB={nameFor(managers, detail.ownerIds[1])}
            />
            <MeetingCard
              label="Last meeting"
              meeting={detail.lastMeeting}
              nameA={nameFor(managers, detail.ownerIds[0])}
              nameB={nameFor(managers, detail.ownerIds[1])}
            />
          </div>

          {detail.seasonSplits && Object.keys(detail.seasonSplits).length > 0 && (
            <>
              <div style={{ fontWeight: 600, marginTop: 14, marginBottom: 6 }}>Season splits</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Season</th>
                      <th style={{ textAlign: "right" }}>{nameFor(managers, detail.ownerIds[0])} wins</th>
                      <th style={{ textAlign: "right" }}>{nameFor(managers, detail.ownerIds[1])} wins</th>
                      <th style={{ textAlign: "right" }}>Ties</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detail.seasonSplits).map(([season, split]) => (
                      <tr key={season}>
                        <td>{season}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.winsA}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.winsB}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.ties}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}

      <Card title="All rivalries" subtitle="Every pair that has met">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th style={{ textAlign: "right" }}>Index</th>
                <th style={{ textAlign: "right" }}>Meet</th>
                <th style={{ textAlign: "right" }}>Playoff</th>
                <th style={{ textAlign: "right" }}>Series</th>
                <th style={{ textAlign: "right" }}>Points</th>
                <th style={{ textAlign: "right" }}>Closest</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => setSelected(i)}>
                  <td style={{ fontWeight: 600 }}>
                    {nameFor(managers, r.ownerIds[0])} vs {nameFor(managers, r.ownerIds[1])}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.rivalryIndex}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.totalMeetings}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.playoffMeetings}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.winsA}-{r.winsB}{r.ties ? `-${r.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtPoints(r.pointsA)} / {fmtPoints(r.pointsB)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.closestGame ? fmtPoints(r.closestGame.margin) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

export default RivalriesSection;
