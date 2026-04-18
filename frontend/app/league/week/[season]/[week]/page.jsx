// Server-rendered weekly-recap page with OG metadata.
//
// Fetches the full ``weeklyRecap`` section once, picks the specific
// week by the ``byKey`` map, and renders a long-form narrative page.
// Sharable URL pattern: ``/league/week/{season}/{week}``.

import Link from "next/link";
import { Avatar, Card } from "../../../shared-server.jsx";
import { buildManagerLookup, fmtPoints, fmtNumber, nameFor } from "../../../shared-helpers.js";
import { EmptyState, PageHeader } from "@/components/ui";
import ShareButton from "../../../ShareButton.jsx";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchRecap() {
  const url = `${_backend()}/api/public/league/weeklyRecap`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function findRecap(payload, season, week) {
  const byKey = payload?.data?.byKey || {};
  return byKey[`${season}:${week}`] || null;
}

// ── Metadata ────────────────────────────────────────────────────────────
export async function generateMetadata({ params }) {
  const { season, week } = await params;
  const payload = await fetchRecap();
  const recap = findRecap(payload, String(season), String(week));
  if (!recap) {
    return {
      title: `Week ${week} · ${season} recap`,
      description: `Weekly recap for the Brisket dynasty league, ${season} week ${week}.`,
    };
  }
  const title = recap.headline || `${season} Week ${week} recap`;
  const description = recap.summary || "";
  return {
    title: `${title} — ${season} Week ${week}`,
    description,
    openGraph: {
      title,
      description,
      type: "article",
      siteName: "Risk It To Get The Brisket",
    },
    twitter: { card: "summary_large_image", title, description },
  };
}

// ── Page ────────────────────────────────────────────────────────────────
export default async function WeeklyRecapPage({ params }) {
  const { season, week } = await params;
  const payload = await fetchRecap();
  const recap = findRecap(payload, String(season), String(week));
  const managers = buildManagerLookup(payload?.league);

  if (!recap) {
    return (
      <section>
        <div className="card">
          <EmptyState
            title="Recap not found"
            message={`No recap for ${season} week ${week} — the week may not be scored yet.`}
          />
          <div style={{ marginTop: 10 }}>
            <Link href="/league?tab=weeklyRecap" style={{ color: "var(--cyan)" }}>
              ← All recaps
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const { isPlayoff, headline, summary, matchups = [], mvp, bust, blowout, nailBiter, badBeat, trades = [] } = recap;

  return (
    <section>
      <Card>
        <PageHeader
          title={headline}
          subtitle={`${season} · Week ${week}${isPlayoff ? " (playoffs)" : ""}`}
        />
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8, marginTop: -8 }}>
          <Link
            href="/league?tab=weeklyRecap"
            style={{
              color: "var(--cyan)",
              fontSize: "0.74rem",
              textDecoration: "none",
              border: "1px solid var(--border-bright)",
              padding: "3px 10px",
              borderRadius: 6,
            }}
          >
            ← All recaps
          </Link>
          <ShareButton title={headline} text={summary} />
        </div>
        <p style={{ fontSize: "0.96rem", lineHeight: 1.55, marginTop: 4 }}>{summary}</p>
      </Card>

      {/* Superlatives strip */}
      <Card title="Superlatives">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 10,
          }}
        >
          {mvp && (
            <SuperlativeCard
              label="Weekly MVP"
              color="#2ecc71"
              managers={managers}
              ownerId={mvp.ownerId}
              displayName={mvp.displayName}
              teamName={mvp.teamName}
              value={`${fmtPoints(mvp.points)} pts`}
            />
          )}
          {blowout && (
            <SuperlativeCard
              label="Biggest blowout"
              color="#ffa726"
              managers={managers}
              ownerId={blowout.winner.ownerId}
              displayName={blowout.winner.displayName}
              teamName={blowout.winner.teamName}
              value={`+${fmtPoints(blowout.margin)} over ${blowout.loser.displayName}`}
            />
          )}
          {nailBiter && (
            <SuperlativeCard
              label="Nailbiter"
              color="#4fc3f7"
              managers={managers}
              ownerId={nailBiter.winner.ownerId}
              displayName={nailBiter.winner.displayName}
              teamName={nailBiter.winner.teamName}
              value={`${fmtNumber(nailBiter.margin, 2)} margin over ${nailBiter.loser.displayName}`}
            />
          )}
          {bust && (
            <SuperlativeCard
              label="Weekly bust"
              color="#ff6b6b"
              managers={managers}
              ownerId={bust.ownerId}
              displayName={bust.displayName}
              teamName={bust.teamName}
              value={`${fmtPoints(bust.points)} pts`}
            />
          )}
          {badBeat && (
            <SuperlativeCard
              label="Bad beat"
              color="#ec407a"
              managers={managers}
              ownerId={badBeat.ownerId}
              displayName={badBeat.displayName}
              teamName={badBeat.teamName}
              value={`${fmtPoints(badBeat.points)} pts in L (by ${fmtPoints(badBeat.marginOfLoss)})`}
            />
          )}
        </div>
      </Card>

      {/* Matchups */}
      <Card title={`${matchups.length} matchup${matchups.length === 1 ? "" : "s"}`}>
        <div>
          {matchups.map((m, i) => {
            const winner = m.winner;
            return (
              <div
                key={i}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto 1fr auto",
                  alignItems: "center",
                  gap: 10,
                  padding: "10px 0",
                  borderBottom: "1px solid var(--border)",
                }}
              >
                <SideBlock side={m.home} managers={managers} won={winner?.ownerId === m.home.ownerId} align="right" />
                <div
                  style={{
                    textAlign: "center",
                    fontFamily: "var(--mono)",
                    color: "var(--subtext)",
                    fontSize: "0.7rem",
                  }}
                >
                  vs
                </div>
                <SideBlock side={m.away} managers={managers} won={winner?.ownerId === m.away.ownerId} align="left" />
                <div
                  style={{
                    fontFamily: "var(--mono)",
                    textAlign: "right",
                    color: "var(--subtext)",
                    fontSize: "0.78rem",
                  }}
                >
                  margin {fmtPoints(m.margin)}
                </div>
                <div
                  style={{
                    gridColumn: "1 / -1",
                    fontSize: "0.78rem",
                    color: "var(--subtext)",
                    marginTop: -2,
                    fontStyle: "italic",
                  }}
                >
                  {m.oneliner}
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      {trades.length > 0 && (
        <Card title={`${trades.length} trade${trades.length === 1 ? "" : "s"} on the wire`}>
          <div>
            {trades.map((tx, i) => (
              <div
                key={tx.transactionId || i}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 0",
                  borderBottom: "1px solid var(--border)",
                  fontSize: "0.78rem",
                }}
              >
                <div style={{ flex: 1 }}>
                  {tx.parties?.map((p, j) => (
                    <span key={p.ownerId}>
                      <strong>{nameFor(managers, p.ownerId) || p.displayName}</strong>
                      {j < tx.parties.length - 1 ? " ⇄ " : ""}
                    </span>
                  ))}
                </div>
                <div style={{ color: "var(--subtext)", fontFamily: "var(--mono)", fontSize: "0.7rem" }}>
                  {tx.assetsMoved} asset{tx.assetsMoved === 1 ? "" : "s"}
                  {tx.picksMoved > 0 && ` · ${tx.picksMoved} pick${tx.picksMoved === 1 ? "" : "s"}`}
                </div>
                <Link href="/league?tab=activity" style={{ color: "var(--cyan)", fontSize: "0.7rem" }}>
                  Details →
                </Link>
              </div>
            ))}
          </div>
        </Card>
      )}
    </section>
  );
}

function SuperlativeCard({ label, color, managers, ownerId, displayName, teamName, value }) {
  return (
    <div
      style={{
        padding: 10,
        borderLeft: `3px solid ${color}`,
        background: "var(--bg-subtle)",
        borderRadius: 6,
      }}
    >
      <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
        {label}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
        <Avatar managers={managers} ownerId={ownerId} size={24} />
        <div>
          <div style={{ fontWeight: 700 }}>{nameFor(managers, ownerId) || displayName}</div>
          <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>{teamName}</div>
        </div>
      </div>
      <div style={{ fontFamily: "var(--mono)", color, fontWeight: 700, marginTop: 6 }}>
        {value}
      </div>
    </div>
  );
}

function SideBlock({ side, managers, won, align }) {
  return (
    <div style={{ textAlign: align }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: align === "right" ? "flex-end" : "flex-start",
          gap: 6,
        }}
      >
        {align === "left" && <Avatar managers={managers} ownerId={side.ownerId} size={20} />}
        <div style={{ textAlign: align }}>
          <div style={{ fontWeight: won ? 800 : 500, color: won ? "#2ecc71" : "inherit" }}>
            {nameFor(managers, side.ownerId)}
          </div>
          <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>{side.teamName}</div>
        </div>
        {align === "right" && <Avatar managers={managers} ownerId={side.ownerId} size={20} />}
      </div>
      <div
        style={{
          fontFamily: "var(--mono)",
          fontSize: "1rem",
          fontWeight: 800,
          color: won ? "#2ecc71" : "var(--subtext)",
          marginTop: 2,
        }}
      >
        {fmtPoints(side.points)}
      </div>
    </div>
  );
}
