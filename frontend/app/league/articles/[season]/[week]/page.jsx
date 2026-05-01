// Weekly slate of AI-generated matchup previews + recaps.
//
// Public read-only — fetches whatever has been generated for the week
// from /api/league/articles. The cron generator
// (.github/workflows/weekly-narratives.yml) writes Wed previews and
// Tue recaps to disk; this page renders whatever's there.
//
// Each matchup card on the slate links into the individual article
// page at /league/articles/[season]/[week]/[matchupId]/[mode].

import Link from "next/link";
import { Card } from "../../../shared-server.jsx";
import { EmptyState, PageHeader } from "@/components/ui";

function backendUrl() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchSlate(season, week) {
  const url = `${backendUrl()}/api/league/articles?season=${encodeURIComponent(season)}&week=${encodeURIComponent(week)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 120 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { season, week } = await params;
  return {
    title: `Articles · ${season} Week ${week} — Brisket League`,
    description: `AI-generated previews and recaps for the ${season} Week ${week} matchup slate.`,
  };
}

function groupByMatchup(articles) {
  const map = new Map();
  for (const art of articles || []) {
    const key = art.matchupId;
    if (!map.has(key)) {
      map.set(key, { matchupId: key, preview: null, recap: null, home: art.home, away: art.away, isChampionship: art.isChampionship, roundLabel: art.roundLabel });
    }
    const slot = map.get(key);
    if (art.mode === "preview") slot.preview = art;
    else if (art.mode === "recap") slot.recap = art;
    if (art.home) slot.home = art.home;
    if (art.away) slot.away = art.away;
    if (art.isChampionship) slot.isChampionship = true;
    if (art.roundLabel) slot.roundLabel = art.roundLabel;
  }
  // Stable order: championship first, then by matchupId.
  return Array.from(map.values()).sort((a, b) => {
    if (a.isChampionship !== b.isChampionship) return a.isChampionship ? -1 : 1;
    return (a.matchupId || 0) - (b.matchupId || 0);
  });
}

export default async function WeekArticlesPage({ params }) {
  const { season, week } = await params;
  const payload = await fetchSlate(season, week);
  const articles = payload?.articles || [];
  const matchups = groupByMatchup(articles);

  return (
    <section>
      <Card>
        <PageHeader
          title={`Week ${week} · ${season}`}
          subtitle="Matchup previews & recaps"
        />
        <div style={{ display: "flex", gap: 8, marginTop: -4, marginBottom: 8 }}>
          <Link href="/league" style={{ color: "var(--cyan)", fontSize: "0.78rem", textDecoration: "none" }}>
            ← Back to /league
          </Link>
        </div>
        <p style={{ fontSize: "0.86rem", color: "var(--subtext)", marginTop: 4 }}>
          Wednesday-morning previews & Tuesday-morning recaps, written by Claude
          using live league data, season storylines, and real NFL context.
        </p>
      </Card>

      {matchups.length === 0 ? (
        <Card>
          <EmptyState
            title="No articles yet"
            message={`Nothing has been generated for ${season} Week ${week}. Check back Wednesday for previews, Tuesday for recaps.`}
          />
        </Card>
      ) : (
        matchups.map((m) => {
          const homeName = m.home?.teamName || m.home?.displayName || "—";
          const awayName = m.away?.teamName || m.away?.displayName || "—";
          const cardTitle = m.isChampionship
            ? `🏆 ${m.roundLabel || "Championship"}: ${homeName} vs ${awayName}`
            : `${m.roundLabel || ""} ${homeName} vs ${awayName}`.trim();
          return (
            <Card key={m.matchupId} title={cardTitle}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                <ArticlePreviewCard
                  article={m.preview}
                  label="Preview"
                  fallback="Preview pending — drops Wed AM."
                  href={`/league/articles/${season}/${week}/${m.matchupId}/preview`}
                />
                <ArticlePreviewCard
                  article={m.recap}
                  label="Recap"
                  fallback="Recap pending — drops Tue AM after Monday Night."
                  href={`/league/articles/${season}/${week}/${m.matchupId}/recap`}
                />
              </div>
            </Card>
          );
        })
      )}
    </section>
  );
}

function ArticlePreviewCard({ article, label, fallback, href }) {
  if (!article) {
    return (
      <div
        style={{
          border: "1px dashed var(--border)",
          borderRadius: 8,
          padding: 12,
          color: "var(--subtext)",
          fontSize: "0.84rem",
        }}
      >
        <div style={{ fontSize: "0.62rem", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6 }}>
          {label}
        </div>
        <div>{fallback}</div>
      </div>
    );
  }
  return (
    <Link
      href={href}
      style={{
        display: "block",
        border: "1px solid var(--border-bright)",
        borderRadius: 8,
        padding: 12,
        textDecoration: "none",
        color: "inherit",
        background: "rgba(255,255,255,0.02)",
      }}
    >
      <div style={{ fontSize: "0.62rem", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6, color: "var(--cyan)" }}>
        {label} · {article.angleUsed || ""}
      </div>
      <div style={{ fontSize: "1rem", fontWeight: 700, lineHeight: 1.3, marginBottom: 6 }}>
        {article.title}
      </div>
      {article.kicker && (
        <div style={{ fontSize: "0.84rem", lineHeight: 1.4, color: "var(--subtext)", fontStyle: "italic" }}>
          {article.kicker}
        </div>
      )}
      <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 8 }}>
        {article.wordCount || 0} words · {new Date(article.generatedAt).toLocaleString()}
      </div>
    </Link>
  );
}
