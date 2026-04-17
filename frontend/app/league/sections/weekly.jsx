"use client";

// WeeklySection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useEffect, useState } from "react";
import Link from "next/link";
import { Card, EmptyCard, HighlightCard, LinkButton, SingleHighlight, fmtPoints, nameFor } from "../shared.jsx";

function WeeklySection({ data, managers, onNavigate, initialWeek, setWeek }) {
  const weeks = data?.weeks || [];
  const defaultKey = weeks[0] ? `${weeks[0].season}:${weeks[0].week}` : "";
  const initialKey = initialWeek && weeks.some((w) => `${w.season}:${w.week}` === initialWeek)
    ? initialWeek
    : defaultKey;
  const [selected, setSelectedInner] = useState(initialKey);
  useEffect(() => {
    if (initialWeek && weeks.some((w) => `${w.season}:${w.week}` === initialWeek) && initialWeek !== selected) {
      setSelectedInner(initialWeek);
    }
  }, [initialWeek]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!weeks.length) return <EmptyCard label="Weekly recap" />;
  const active = weeks.find((w) => `${w.season}:${w.week}` === selected) || weeks[0];
  const h = active.highlights || {};

  function changeWeek(key) {
    setSelectedInner(key);
    if (setWeek) setWeek(key);
  }

  return (
    <>
      <Card
        title={`${active.season} · Week ${active.week}${active.isPlayoff ? " (playoffs)" : ""}`}
        action={
          <select
            className="input"
            value={`${active.season}:${active.week}`}
            onChange={(e) => changeWeek(e.target.value)}
            style={{ minWidth: 180 }}
          >
            {weeks.map((w) => (
              <option key={`${w.season}:${w.week}`} value={`${w.season}:${w.week}`}>
                {w.season} Wk {w.week}{w.isPlayoff ? " (P)" : ""}
              </option>
            ))}
          </select>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginBottom: 14 }}>
          <HighlightCard
            label="Game of the week"
            caption={h.gameOfTheWeek ? `margin ${fmtPoints(h.gameOfTheWeek.margin)}` : "—"}
            teams={h.gameOfTheWeek ? [h.gameOfTheWeek.home, h.gameOfTheWeek.away] : null}
          />
          <HighlightCard
            label="Blowout of the week"
            caption={h.blowoutOfTheWeek ? `margin ${fmtPoints(h.blowoutOfTheWeek.margin)}` : "—"}
            teams={h.blowoutOfTheWeek ? [h.blowoutOfTheWeek.home, h.blowoutOfTheWeek.away] : null}
          />
          <HighlightCard
            label="Upset of the week"
            caption={h.upsetOfTheWeek
              ? `winner ${h.upsetOfTheWeek.winnerOwnerId ? nameFor(managers, h.upsetOfTheWeek.winnerOwnerId) : "—"}`
              : "No upsets"}
            teams={h.upsetOfTheWeek ? [h.upsetOfTheWeek.home, h.upsetOfTheWeek.away] : null}
          />
          <SingleHighlight
            label="Highest scorer"
            value={h.highestScorer ? `${h.highestScorer.displayName} (${fmtPoints(h.highestScorer.points)})` : "—"}
          />
          <SingleHighlight
            label="Lowest scorer"
            value={h.lowestScorer ? `${h.lowestScorer.displayName} (${fmtPoints(h.lowestScorer.points)})` : "—"}
          />
          {h.standingsMover && (
            <SingleHighlight
              label="Biggest standings mover"
              value={`${nameFor(managers, h.standingsMover.ownerId)} (${h.standingsMover.preRank} → ${h.standingsMover.postRank})`}
              sub={`Δ ${h.standingsMover.delta > 0 ? "+" : ""}${h.standingsMover.delta}`}
            />
          )}
          {h.rivalryResult && (
            <SingleHighlight
              label="Rivalry meeting"
              value={`${h.rivalryResult.home?.displayName} vs ${h.rivalryResult.away?.displayName}`}
              sub={`margin ${fmtPoints(h.rivalryResult.margin)}`}
            />
          )}
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Home</th>
                <th style={{ textAlign: "right" }}>Score</th>
                <th style={{ textAlign: "right" }}>Margin</th>
                <th style={{ textAlign: "right" }}>Score</th>
                <th>Away</th>
              </tr>
            </thead>
            <tbody>
              {(active.matchups || []).map((m, i) => {
                const winnerIsHome = m.winnerOwnerId === m.home?.ownerId;
                const winnerIsAway = m.winnerOwnerId === m.away?.ownerId;
                const hasMatchupId = m.matchupId !== null && m.matchupId !== undefined;
                const recapHref = hasMatchupId
                  ? `/league/weekly/${encodeURIComponent(active.season)}/${encodeURIComponent(active.week)}/${encodeURIComponent(m.matchupId)}`
                  : null;
                return (
                  <tr key={i}>
                    <td style={{ fontWeight: 600, color: winnerIsHome ? "var(--green)" : "var(--text)" }}>{m.home?.displayName}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(m.home?.points)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                      {recapHref ? (
                        <Link href={recapHref} style={{ color: "var(--cyan)" }} title="Open full recap">
                          {fmtPoints(m.margin)} →
                        </Link>
                      ) : (
                        fmtPoints(m.margin)
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(m.away?.points)}</td>
                    <td style={{ fontWeight: 600, color: winnerIsAway ? "var(--green)" : "var(--text)" }}>{m.away?.displayName}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: 12 }}>
          <LinkButton onClick={() => onNavigate("archives")}>Open matchup archive →</LinkButton>
        </div>
      </Card>
    </>
  );
}

export default WeeklySection;
