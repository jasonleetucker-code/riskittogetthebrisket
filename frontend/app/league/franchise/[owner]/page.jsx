// Server-rendered franchise page with Open Graph metadata.
//
// Fetches GET /api/public/league/franchise?owner=<ownerId> — which
// includes a narrowed ``franchiseDetail`` block so we don't ship every
// franchise's detail dict to a single-page visitor.

import Link from "next/link";
import { Avatar, Card, Stat } from "../../shared-server.jsx";
import { buildManagerLookup, fmtNumber } from "../../shared-helpers.js";
import { EmptyState, PageHeader } from "@/components/ui";
import ShareButton from "../../ShareButton.jsx";
import RosterComparePanel from "@/components/RosterComparePanel";

function _backend() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchFranchise(ownerId) {
  const url = `${_backend()}/api/public/league/franchise?owner=${encodeURIComponent(ownerId)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 60 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { owner } = await params;
  const ownerId = decodeURIComponent(String(owner || ""));
  const data = await fetchFranchise(ownerId);
  const fr = data?.franchiseDetail || data?.data?.detail?.[ownerId];
  if (!fr) {
    return {
      title: "Franchise · Brisket League",
      description: "Public franchise record for the Risk It To Get The Brisket dynasty league.",
    };
  }
  const cum = fr.cumulative || {};
  const record = `${cum.wins}-${cum.losses}${cum.ties ? `-${cum.ties}` : ""}`;
  const titleParts = [`${fr.displayName}`];
  if (cum.championships) titleParts.push(`${cum.championships}× Champ`);
  titleParts.push(`${record} across ${cum.seasonsPlayed || 0} seasons`);
  const title = titleParts.join(" — ");
  const descParts = [];
  if (cum.playoffAppearances) descParts.push(`${cum.playoffAppearances} playoff appearances`);
  if (cum.finalsAppearances) descParts.push(`${cum.finalsAppearances} finals`);
  if (fr.tradeCount) descParts.push(`${fr.tradeCount} trades`);
  if (fr.topRival) descParts.push(`Top rival: ${fr.topRival.displayName}`);
  const description = descParts.length
    ? descParts.join(" · ")
    : `Public franchise record for ${fr.displayName}.`;
  return {
    title,
    description,
    openGraph: { title, description, type: "profile", siteName: "Risk It To Get The Brisket" },
    twitter: { card: "summary", title, description },
  };
}

export default async function FranchisePage({ params }) {
  const { owner } = await params;
  const ownerId = decodeURIComponent(String(owner || ""));
  const data = await fetchFranchise(ownerId);
  const fr = data?.franchiseDetail || data?.data?.detail?.[ownerId] || null;
  const managers = buildManagerLookup(data?.league);

  if (!fr) {
    return (
      <section>
        <div className="card">
          <EmptyState title="Franchise not found" message={`No public franchise record for owner ${ownerId}.`} />
          <div style={{ marginTop: 10 }}>
            <Link href="/league" style={{ color: "var(--cyan)" }}>← Back to league</Link>
          </div>
        </div>
      </section>
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
        <div style={{ marginBottom: 10 }}>
          <ShareButton
            label="Share franchise"
            path={`/league/franchise/${encodeURIComponent(ownerId)}`}
            text={`${fr.displayName} — ${fr.cumulative.wins}-${fr.cumulative.losses}${fr.cumulative.championships ? ` · ${fr.cumulative.championships}x champ` : ""}`}
          />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Avatar managers={managers} ownerId={ownerId} size={64} />
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
            {fr.topRival && (
              <div>
                Top rival:{" "}
                <Link
                  href={`/league/franchise/${encodeURIComponent(fr.topRival.ownerId)}`}
                  style={{ color: "var(--cyan)" }}
                >
                  {fr.topRival.displayName}
                </Link>{" "}
                · Index {fr.topRival.rivalryIndex}
              </div>
            )}
            <div>
              Owner ID: <span style={{ fontFamily: "var(--mono)" }}>{ownerId}</span>
            </div>
          </div>
        </div>
      </div>

      <Card title="Compare to my roster">
        <RosterComparePanel ownerId={ownerId} />
      </Card>

      <Card title="Cumulative">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
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
