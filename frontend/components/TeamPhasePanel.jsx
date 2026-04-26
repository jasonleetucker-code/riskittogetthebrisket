"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useApp } from "@/components/AppShell";
import { useUserState } from "@/components/useUserState";
import { analyzeLeaguePhases } from "@/lib/team-phase";

const TONE_COLOR = {
  up: "var(--green)",
  warn: "var(--amber)",
  down: "var(--red)",
};

function fmtAge(a) {
  if (a == null || !Number.isFinite(a)) return "—";
  return a.toFixed(1);
}

function fmtValue(v) {
  if (!Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString();
}

export default function TeamPhasePanel() {
  const { rows, rawData, loading } = useApp();
  const { state: userState } = useUserState();

  const myOwnerId = userState?.selectedTeam?.ownerId
    ? String(userState.selectedTeam.ownerId)
    : null;

  const analysis = useMemo(
    () => analyzeLeaguePhases(rawData, rows),
    [rawData, rows],
  );

  if (loading) return null;
  if (!analysis.teams.length) return null;

  const myRow = myOwnerId
    ? analysis.teams.find((t) => t.ownerId === myOwnerId)
    : null;
  const myPartnerships = myOwnerId
    ? analysis.partnerships.filter(
        (p) => p.winnerOwnerId === myOwnerId || p.rebuilderOwnerId === myOwnerId,
      )
    : [];

  return (
    <div className="card" style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>Win-now vs Rebuild</h3>
        <p className="muted" style={{ fontSize: "0.7rem", margin: "4px 0 0" }}>
          Each team classified by top-25 roster value × median age, against the league medians
          ({fmtValue(analysis.leagueMedians.value)} value · {fmtAge(analysis.leagueMedians.age)} age).
        </p>
      </div>

      {myRow && (
        <div style={{ padding: 8, borderRadius: 4, border: "1px solid var(--border)" }}>
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>You are:</div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <strong style={{ fontSize: "0.96rem", color: TONE_COLOR[myRow.phase.tone] }}>
              {myRow.phase.label}
            </strong>
            <span className="muted" style={{ fontSize: "0.74rem" }}>
              · top-25 value {fmtValue(myRow.totalValue)} · median age {fmtAge(myRow.medianAge)}
            </span>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Team</th>
              <th style={{ textAlign: "left" }}>Phase</th>
              <th style={{ textAlign: "right" }}>Top-25 value</th>
              <th style={{ textAlign: "right" }}>Median age</th>
            </tr>
          </thead>
          <tbody>
            {analysis.teams.map((t) => {
              const isMe = myOwnerId && t.ownerId === myOwnerId;
              return (
                <tr key={t.ownerId || t.name}>
                  <td style={{ fontWeight: isMe ? 700 : 500 }}>
                    {t.ownerId ? (
                      <Link
                        href={`/league/franchise/${encodeURIComponent(t.ownerId)}`}
                        style={{ color: "var(--cyan)", textDecoration: "none" }}
                      >
                        {t.name}
                        {isMe && (
                          <span className="muted" style={{ marginLeft: 6, fontSize: "0.66rem" }}>
                            (you)
                          </span>
                        )}
                      </Link>
                    ) : (
                      t.name
                    )}
                  </td>
                  <td>
                    <span
                      className="badge"
                      style={{
                        backgroundColor: "var(--surface-2)",
                        color: TONE_COLOR[t.phase.tone],
                        fontSize: "0.7rem",
                      }}
                    >
                      {t.phase.label}
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtValue(t.totalValue)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtAge(t.medianAge)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {myPartnerships.length > 0 && (
        <div>
          <strong style={{ fontSize: "0.84rem" }}>Natural trade partners for you</strong>
          <ul style={{ margin: "4px 0 0 16px", padding: 0, fontSize: "0.78rem" }}>
            {myPartnerships.slice(0, 3).map((p) => {
              const otherName =
                p.winnerOwnerId === myOwnerId ? p.rebuilderName : p.winnerName;
              const otherId =
                p.winnerOwnerId === myOwnerId ? p.rebuilderOwnerId : p.winnerOwnerId;
              const direction =
                p.winnerOwnerId === myOwnerId
                  ? "buy older star talent from"
                  : "sell veterans to";
              return (
                <li key={otherId} style={{ marginBottom: 2 }}>
                  {direction}{" "}
                  <Link
                    href={`/league/franchise/${encodeURIComponent(otherId)}`}
                    style={{ color: "var(--cyan)" }}
                  >
                    {otherName}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}
