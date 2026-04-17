"use client";

// Dedicated, deep-linkable /league/rivalry/[pair] route.
//
// ``pair`` is an URL-encoded string of the form ``<ownerA>-vs-<ownerB>``.
// We find the matching rivalry in the public rivalries section (which
// already returns every pair) and render the same detail view the
// tabbed page shows.
//
// No private imports — see isolation contract in page.jsx.

import { Suspense, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { LoadingState, EmptyState, PageHeader } from "@/components/ui";
import { fetchPublicSection } from "@/lib/public-league-data";
import {
  Avatar,
  Card,
  MeetingCard,
  Stat,
  buildManagerLookup,
  fmtPoints,
  nameFor,
} from "../../shared.jsx";

export default function RivalryPageRoute() {
  return (
    <Suspense fallback={<LoadingState message="Loading rivalry..." />}>
      <RivalryPage />
    </Suspense>
  );
}

function parsePairSlug(slug) {
  if (!slug) return { a: "", b: "" };
  const decoded = decodeURIComponent(String(slug));
  // Support either "a-vs-b" or "a:b" forms.
  const parts = decoded.includes("-vs-")
    ? decoded.split("-vs-")
    : decoded.includes(":")
    ? decoded.split(":")
    : [decoded];
  return { a: String(parts[0] || ""), b: String(parts[1] || "") };
}

function RivalryPage() {
  const params = useParams();
  const { a: ownerA, b: ownerB } = parsePairSlug(params?.pair);
  const [state, setState] = useState({ loading: true, error: "", payload: null });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const payload = await fetchPublicSection("rivalries");
        if (!active) return;
        setState({ loading: false, error: "", payload });
      } catch (err) {
        if (!active) return;
        setState({
          loading: false,
          error: err?.message || "Failed to load rivalry data",
          payload: null,
        });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  // Hooks must run on every render — compute managers before any early
  // return branches below.
  const { league, data } = state.payload || {};
  const managers = useMemo(() => buildManagerLookup(league), [league]);
  const rivalries = data?.rivalries || [];

  if (state.loading) return <LoadingState message="Loading rivalry..." />;
  if (state.error) {
    return (
      <div className="card">
        <EmptyState title="Rivalry unavailable" message={state.error} />
        <div style={{ marginTop: 10 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← Back to league</Link>
        </div>
      </div>
    );
  }

  // Find the pair regardless of ordering.
  const detail = rivalries.find((r) => {
    const ids = new Set((r.ownerIds || []).map(String));
    return ids.has(ownerA) && ids.has(ownerB);
  });

  if (!detail) {
    return (
      <div className="card">
        <EmptyState
          title="Rivalry not found"
          message={
            ownerA && ownerB
              ? `No meetings between ${nameFor(managers, ownerA)} and ${nameFor(managers, ownerB)} in the last 2 seasons.`
              : "Rivalry slug must be of the form owner-a-vs-owner-b."
          }
        />
        <div style={{ marginTop: 10 }}>
          <Link href="/league?tab=rivalries" style={{ color: "var(--cyan)" }}>← All rivalries</Link>
        </div>
      </div>
    );
  }

  const [idA, idB] = detail.ownerIds;

  return (
    <section>
      <div className="card">
        <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
          <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
          {" · "}
          <Link href="/league?tab=rivalries" style={{ color: "var(--cyan)" }}>All rivalries</Link>
        </div>
        <PageHeader
          title={`${nameFor(managers, idA)} vs ${nameFor(managers, idB)}`}
          subtitle={`Rivalry Index ${detail.rivalryIndex} · Head-to-head detail`}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Link href={`/league/franchise/${encodeURIComponent(idA)}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--cyan)" }}>
            <Avatar managers={managers} ownerId={idA} size={36} />
            <span style={{ fontWeight: 700 }}>{nameFor(managers, idA)}</span>
          </Link>
          <span style={{ color: "var(--subtext)", fontWeight: 700 }}>vs</span>
          <Link href={`/league/franchise/${encodeURIComponent(idB)}`} style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--cyan)" }}>
            <Avatar managers={managers} ownerId={idB} size={36} />
            <span style={{ fontWeight: 700 }}>{nameFor(managers, idB)}</span>
          </Link>
        </div>
      </div>

      <Card title="Head-to-head">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 10,
            marginBottom: 14,
          }}
        >
          <Stat label="Meetings" value={detail.totalMeetings} sub={`${detail.regularSeasonMeetings} reg · ${detail.playoffMeetings} playoff`} />
          <Stat label="Series" value={`${detail.winsA}–${detail.winsB}${detail.ties ? `–${detail.ties}` : ""}`} />
          <Stat label="Points" value={`${fmtPoints(detail.pointsA)} / ${fmtPoints(detail.pointsB)}`} />
          <Stat label="Close (≤5 pts)" value={detail.gamesDecidedByFive} />
          <Stat label="Close (≤10 pts)" value={detail.gamesDecidedByTen} />
        </div>

        <div style={{ fontWeight: 600, marginBottom: 6 }}>Memorable meetings</div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 10,
          }}
        >
          <MeetingCard label="Closest" meeting={detail.closestGame} />
          <MeetingCard label="Biggest blowout" meeting={detail.biggestBlowout} />
          <MeetingCard label="Last meeting" meeting={detail.lastMeeting} />
        </div>

        {detail.seasonSplits && Object.keys(detail.seasonSplits).length > 0 && (
          <>
            <div style={{ fontWeight: 600, marginTop: 14, marginBottom: 6 }}>Season splits</div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Season</th>
                    <th style={{ textAlign: "right" }}>{nameFor(managers, idA)} wins</th>
                    <th style={{ textAlign: "right" }}>{nameFor(managers, idB)} wins</th>
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
    </section>
  );
}
