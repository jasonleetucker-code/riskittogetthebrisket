// Server-rendered rivalry page with OG metadata.
//
// Slug format: ``<ownerA>-vs-<ownerB>`` (either ordering).  We fetch
// the full rivalries section server-side and pick the pair — the
// section payload is already small enough that this is cheap.

import Link from "next/link";
import { Avatar, Card, MeetingCard, Stat } from "../../shared-server.jsx";
import { buildManagerLookup, fmtPoints, nameFor } from "../../shared-helpers.js";
import { EmptyState, PageHeader } from "@/components/ui";
import ShareButton from "../../ShareButton.jsx";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchRivalries() {
  const url = `${_backend()}/api/public/league/rivalries`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function parsePairSlug(slug) {
  if (!slug) return { a: "", b: "" };
  const decoded = decodeURIComponent(String(slug));
  const parts = decoded.includes("-vs-")
    ? decoded.split("-vs-")
    : decoded.includes(":")
    ? decoded.split(":")
    : [decoded];
  return { a: String(parts[0] || ""), b: String(parts[1] || "") };
}

function findDetail(payload, ownerA, ownerB) {
  const rivalries = payload?.data?.rivalries || [];
  return rivalries.find((r) => {
    const ids = new Set((r.ownerIds || []).map(String));
    return ids.has(ownerA) && ids.has(ownerB);
  });
}

export async function generateMetadata({ params }) {
  const { pair } = await params;
  const { a, b } = parsePairSlug(pair);
  const data = await fetchRivalries();
  const managers = buildManagerLookup(data?.league);
  const detail = findDetail(data, a, b);
  if (!detail) {
    return {
      title: "Rivalry · Brisket League",
      description: "Public head-to-head record for two managers in the Brisket dynasty league.",
    };
  }
  const [idA, idB] = detail.ownerIds;
  const nameA = nameFor(managers, idA);
  const nameB = nameFor(managers, idB);
  const title = `${nameA} vs ${nameB} — Rivalry Index ${detail.rivalryIndex}`;
  const record = `${detail.winsA}-${detail.winsB}${detail.ties ? `-${detail.ties}` : ""}`;
  const description =
    `${detail.totalMeetings} meetings · ${detail.playoffMeetings} playoff · ` +
    `Series ${record} · Closest margin ${detail.closestGame?.margin ?? "—"}.`;
  return {
    title,
    description,
    openGraph: { title, description, type: "article", siteName: "Risk It To Get The Brisket" },
    twitter: { card: "summary", title, description },
  };
}

export default async function RivalryPage({ params }) {
  const { pair } = await params;
  const { a, b } = parsePairSlug(pair);
  const data = await fetchRivalries();
  const managers = buildManagerLookup(data?.league);
  const detail = findDetail(data, a, b);

  if (!detail) {
    return (
      <section>
        <div className="card">
          <EmptyState
            title="Rivalry not found"
            message={
              a && b
                ? `No meetings between ${nameFor(managers, a)} and ${nameFor(managers, b)} in the last 2 seasons.`
                : "Rivalry slug must be of the form owner-a-vs-owner-b."
            }
          />
          <div style={{ marginTop: 10 }}>
            <Link href="/league?tab=rivalries" style={{ color: "var(--cyan)" }}>← All rivalries</Link>
          </div>
        </div>
      </section>
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
        <div style={{ marginBottom: 10 }}>
          <ShareButton
            label="Share rivalry"
            path={`/league/rivalry/${encodeURIComponent(`${idA}-vs-${idB}`)}`}
            text={
              `${nameFor(managers, idA)} vs ${nameFor(managers, idB)} — ` +
              `Rivalry Index ${detail.rivalryIndex} · ${detail.totalMeetings} meetings`
            }
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <Link
            href={`/league/franchise/${encodeURIComponent(idA)}`}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--cyan)" }}
          >
            <Avatar managers={managers} ownerId={idA} size={36} />
            <span style={{ fontWeight: 700 }}>{nameFor(managers, idA)}</span>
          </Link>
          <span style={{ color: "var(--subtext)", fontWeight: 700 }}>vs</span>
          <Link
            href={`/league/franchise/${encodeURIComponent(idB)}`}
            style={{ display: "inline-flex", alignItems: "center", gap: 6, color: "var(--cyan)" }}
          >
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
          <Stat
            label="Meetings"
            value={detail.totalMeetings}
            sub={`${detail.regularSeasonMeetings} reg · ${detail.playoffMeetings} playoff`}
          />
          <Stat
            label="Series"
            value={`${detail.winsA}–${detail.winsB}${detail.ties ? `–${detail.ties}` : ""}`}
            sub={
              detail.winsA > detail.winsB
                ? `${nameFor(managers, idA)} leads`
                : detail.winsB > detail.winsA
                  ? `${nameFor(managers, idB)} leads`
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
                ? `${nameFor(managers, idA)} +${fmtPoints(detail.pointsA - detail.pointsB)}`
                : detail.pointsB > detail.pointsA
                  ? `${nameFor(managers, idB)} +${fmtPoints(detail.pointsB - detail.pointsA)}`
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
                : undefined
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
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
            gap: 10,
          }}
        >
          <MeetingCard
            label="Closest"
            meeting={detail.closestGame}
            nameA={nameFor(managers, idA)}
            nameB={nameFor(managers, idB)}
          />
          <MeetingCard
            label="Biggest blowout"
            meeting={detail.biggestBlowout}
            nameA={nameFor(managers, idA)}
            nameB={nameFor(managers, idB)}
          />
          <MeetingCard
            label="Last meeting"
            meeting={detail.lastMeeting}
            nameA={nameFor(managers, idA)}
            nameB={nameFor(managers, idB)}
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
