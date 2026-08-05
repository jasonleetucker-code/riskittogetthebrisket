"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useDynastyData } from "@/components/useDynastyData";
import { useUserState } from "@/components/useUserState";
import { analyzeLeaguePhases, ORDERING_CAVEAT } from "@/lib/team-phase";

const TONE_COLOR = {
  up: "var(--green)",
  warn: "var(--amber)",
  down: "var(--red)",
};

function fmtPct(x) {
  if (x == null || !Number.isFinite(x)) return "—";
  return `${Math.round(x * 100)}`;
}

export default function TeamPhasePanel() {
  // This panel is the entire body of /phases.  It used to live at
  // /league/phases and needed this hook specifically because AppShell
  // refuses to hydrate the private contract under the ``/league``
  // prefix (PUBLIC_ONLY_ROUTE_PREFIXES), making ``useApp()`` there
  // permanently ``{rows: [], rawData: null}``.  That is exactly why
  // the route moved: contention classification is private analysis and
  // had no business on a public-prefixed URL.
  //
  // On /phases ``useApp()`` would now work too.  Keeping the direct
  // hook costs nothing — the fetch layer dedups and ``buildRows`` is
  // shared by contract identity through a WeakMap — and it keeps the
  // panel host-agnostic, which is the same reason RosterComparePanel
  // reads it directly on /league/franchise/[owner].  ``/api/data`` is
  // auth-gated, so an anonymous visitor gets a 401 and the explicit
  // message below rather than any leaked data.
  const { rows, rawData, loading } = useDynastyData();
  const { state: userState } = useUserState();

  const myOwnerId = userState?.selectedTeam?.ownerId
    ? String(userState.selectedTeam.ownerId)
    : null;

  const analysis = useMemo(
    () => analyzeLeaguePhases(rawData, rows),
    [rawData, rows],
  );

  // Never render nothing: this component owns a whole route, so a
  // silent null is indistinguishable from a broken page.
  if (loading) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        Loading league rosters…
      </p>
    );
  }
  if (!analysis.teams.length) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        League phases unavailable — no Sleeper rosters in the active league&apos;s
        data. Sign in and pick your team on the league page.
      </p>
    );
  }

  const myRow = myOwnerId
    ? analysis.teams.find((t) => t.ownerId === myOwnerId)
    : null;
  const myPartnerships = myOwnerId
    ? analysis.partnerships.filter(
        (p) => p.winnerOwnerId === myOwnerId || p.rebuilderOwnerId === myOwnerId,
      )
    : [];

  // The page's headline feature is the partner list, and it used to
  // render literally nothing when there was no pairing to show — on
  // live data that was ALWAYS, because the old classifier could not
  // produce a Rebuild team at all (audit W20-F008). Never render
  // nothing: say which of the three reasons applies.
  let partnerEmptyReason = null;
  if (!myPartnerships.length) {
    if (!myOwnerId) {
      partnerEmptyReason =
        "Pick your team on the league page to see natural trade partners.";
    } else if (!myRow) {
      partnerEmptyReason =
        "Your team isn't in this league's roster snapshot, so it has no direction to pair off.";
    } else if (["retool", "productive_struggle"].includes(myRow.mostLikely)) {
      partnerEmptyReason =
        `Your roster reads ${myRow.phase.label} — between the buying and selling ends of the league, so no lopsided pairing stands out. The complementary trades are with the teams at either end of the table.`;
    } else {
      const wanted = ["championship_contender", "playoff_contender"].includes(
        myRow.mostLikely,
      )
        ? "rebuilding"
        : "contending";
      partnerEmptyReason = `No ${wanted} team in this league is far enough from you on both axes to pair off right now.`;
    }
  }

  return (
    <div className="card" style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 10 }}>
      <div>
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>Win-now vs Rebuild</h3>
        <p className="muted" style={{ fontSize: "0.7rem", margin: "4px 0 0" }}>
          Two measured axes:{" "}
          <strong>competitiveness</strong> (
          {analysis.axes.competitivenessSource === "lineupScoreRank"
            ? "league percentile of the optimal starting lineup"
            : "league percentile of total player value — this league's lineup slots aren't in the current data, so no lineup could be solved"}
          ) and <strong>trajectory</strong> (value-weighted age of the players who
          enter that lineup). Placed against five anchored states, probabilities
          from a softmax — the same classifier the Team Strength page and the
          backend roster-intelligence engine use. {ORDERING_CAVEAT}
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
              · {Math.round(myRow.confidence * 100)}% · competitiveness{" "}
              {fmtPct(myRow.competitiveness)}/100 · trajectory{" "}
              {myRow.trajectorySample > 0 ? `${fmtPct(myRow.trajectory)}/100` : "unmeasured"}
            </span>
          </div>
        </div>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ textAlign: "left" }}>Team</th>
              <th style={{ textAlign: "left" }}>Direction</th>
              <th style={{ textAlign: "right" }}>Competitiveness</th>
              <th style={{ textAlign: "right" }}>Trajectory</th>
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
                      {t.ambiguous && (
                        <span className="muted" style={{ marginLeft: 4, fontWeight: 400 }}>
                          ?
                        </span>
                      )}
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtPct(t.competitiveness)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {t.trajectorySample > 0 ? fmtPct(t.trajectory) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {partnerEmptyReason && (
        <div>
          <strong style={{ fontSize: "0.84rem" }}>Natural trade partners for you</strong>
          <p className="muted" style={{ fontSize: "0.72rem", margin: "4px 0 0" }}>
            {partnerEmptyReason}
          </p>
        </div>
      )}

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
