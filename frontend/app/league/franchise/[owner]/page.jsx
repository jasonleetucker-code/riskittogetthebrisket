"use client";

// Dedicated, deep-linkable /league/franchise/[owner] route.
//
// Hits GET /api/public/league/franchise?owner=<ownerId> which returns
// the index + detail map PLUS a narrowed ``franchiseDetail`` block so
// we don't need to download every franchise's detail to render one.
// Purely public data — see the isolation contract in page.jsx.

import { Suspense, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { LoadingState, EmptyState, PageHeader } from "@/components/ui";
import { fetchPublicSection } from "@/lib/public-league-data";
import {
  Avatar,
  Card,
  Stat,
  buildManagerLookup,
  fmtNumber,
} from "../../shared.jsx";

export default function FranchisePageRoute() {
  return (
    <Suspense fallback={<LoadingState message="Loading franchise..." />}>
      <FranchisePage />
    </Suspense>
  );
}

function FranchisePage() {
  const params = useParams();
  const ownerId = decodeURIComponent(String(params?.owner || ""));
  const [state, setState] = useState({ loading: true, error: "", payload: null });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const payload = await fetchPublicSection("franchise", { owner: ownerId });
        if (!active) return;
        setState({ loading: false, error: "", payload });
      } catch (err) {
        if (!active) return;
        setState({
          loading: false,
          error: err?.message || "Failed to load franchise data",
          payload: null,
        });
      }
    })();
    return () => {
      active = false;
    };
  }, [ownerId]);

  if (state.loading) return <LoadingState message="Loading franchise..." />;
  if (state.error) {
    return (
      <div className="card">
        <EmptyState title="Franchise unavailable" message={state.error} />
        <div style={{ marginTop: 10 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← Back to league</Link>
        </div>
      </div>
    );
  }

  const { league, franchiseDetail } = state.payload || {};
  const fr = franchiseDetail || state.payload?.data?.detail?.[ownerId] || null;
  const managers = buildManagerLookup(league);

  if (!fr) {
    return (
      <div className="card">
        <EmptyState title="Franchise not found" message={`No public franchise record for owner ${ownerId}.`} />
        <div style={{ marginTop: 10 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← Back to league</Link>
        </div>
      </div>
    );
  }

  return (
    <section>
      <div className="card">
        <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
          {" · "}
          <Link href="/league?tab=franchise" style={{ color: "var(--cyan)" }}>All franchises</Link>
        </div>
        <PageHeader
          title={fr.displayName}
          subtitle={`Current team: ${fr.currentTeamName || "—"}`}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Avatar managers={managers} ownerId={ownerId} size={64} />
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
            {fr.topRival && (
              <div>
                Top rival:{" "}
                <Link href={`/league/franchise/${encodeURIComponent(fr.topRival.ownerId)}`} style={{ color: "var(--cyan)" }}>
                  {fr.topRival.displayName}
                </Link>
                {" · Index "}{fr.topRival.rivalryIndex}
              </div>
            )}
            <div>
              Owner ID: <span style={{ fontFamily: "var(--mono)" }}>{ownerId}</span>
            </div>
          </div>
        </div>
      </div>

      <Card title="Cumulative">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
            gap: 10,
          }}
        >
          <Stat label="Seasons" value={fr.cumulative.seasonsPlayed} />
          <Stat
            label="Record"
            value={`${fr.cumulative.wins}-${fr.cumulative.losses}${fr.cumulative.ties ? `-${fr.cumulative.ties}` : ""}`}
          />
          <Stat label="Points for" value={fmtNumber(fr.cumulative.pointsFor, 1)} />
          <Stat
            label="Titles"
            value={fr.cumulative.championships}
            sub={`${fr.cumulative.finalsAppearances} finals`}
          />
          <Stat
            label="Playoffs"
            value={fr.cumulative.playoffAppearances}
            sub={`${fr.cumulative.regularSeasonFirstPlace} reg 1st`}
          />
          <Stat label="Trades" value={fr.tradeCount} sub={`${fr.waiverCount} waivers`} />
        </div>
      </Card>

      {fr.draftCapital && (
        <Card title="Draft capital">
          <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginBottom: 6 }}>
            Weighted score {fr.draftCapital.weightedScore} · {fr.draftCapital.totalPicks} owned picks
          </div>
          {(fr.draftCapital.picks || []).length > 0 && (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {(fr.draftCapital.picks || []).map((p, i) => (
                <span
                  key={i}
                  style={{
                    fontFamily: "var(--mono)",
                    fontSize: "0.7rem",
                    border: "1px solid var(--border)",
                    padding: "2px 6px",
                    borderRadius: 4,
                    color: p.isTraded ? "var(--amber)" : "var(--text)",
                  }}
                >
                  {p.label}{p.isTraded ? "*" : ""}
                </span>
              ))}
            </div>
          )}
          <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
            * acquired via trade ·{" "}
            <Link href="/league?tab=draft" style={{ color: "var(--cyan)" }}>
              Full draft center →
            </Link>
          </div>
        </Card>
      )}

      <Card title="Season results">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Season</th>
                <th>Team</th>
                <th style={{ textAlign: "right" }}>W-L-T</th>
                <th style={{ textAlign: "right" }}>PF</th>
                <th style={{ textAlign: "right" }}>PA</th>
                <th style={{ textAlign: "right" }}>Seed</th>
                <th style={{ textAlign: "right" }}>Final</th>
              </tr>
            </thead>
            <tbody>
              {(fr.seasonResults || []).map((r, i) => (
                <tr key={i}>
                  <td>{r.season}</td>
                  <td style={{ fontWeight: 600 }}>{r.teamName}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.wins}-{r.losses}{r.ties ? `-${r.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtNumber(r.pointsFor, 1)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtNumber(r.pointsAgainst, 1)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.standing}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {(fr.aliases || []).length > 1 && (
          <div style={{ marginTop: 14, fontSize: "0.72rem", color: "var(--subtext)" }}>
            Team-name history: {(fr.aliases || []).map((a) => `${a.teamName} (${a.season})`).join(" → ")}
          </div>
        )}
      </Card>
    </section>
  );
}
