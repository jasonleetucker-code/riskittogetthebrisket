// Single AI-written matchup article (preview or recap).
//
// Server-rendered so first paint includes the full body — no
// loading flash, plus OG metadata that pulls the article's actual
// title and kicker for share previews.

import Link from "next/link";
import { Card } from "../../../../../shared-server.jsx";
import { EmptyState, PageHeader } from "@/components/ui";
import ShareButton from "../../../../../ShareButton.jsx";

function backendUrl() {
  const base = process.env.BACKEND_API_URL || "http://127.0.0.1:8000";
  try {
    const u = new URL(base);
    return `${u.protocol}//${u.host}`;
  } catch {
    return "http://127.0.0.1:8000";
  }
}

async function fetchArticle(season, week, matchupId, mode) {
  const url = `${backendUrl()}/api/league/articles/${encodeURIComponent(season)}/${encodeURIComponent(week)}/${encodeURIComponent(matchupId)}/${encodeURIComponent(mode)}`;
  try {
    const res = await fetch(url, { next: { revalidate: 300 } });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }) {
  const { season, week, matchupId, mode } = await params;
  const art = await fetchArticle(season, week, matchupId, mode);
  if (!art) {
    return {
      title: `Brisket League — ${season} W${week} ${mode}`,
      description: `Article for ${season} Week ${week}.`,
    };
  }
  const title = art.title || `${season} W${week} ${mode}`;
  const description = art.kicker || art.lede || "";
  return {
    title: `${title} — Brisket League`,
    description,
    openGraph: { title, description, type: "article", siteName: "Risk It To Get The Brisket" },
    twitter: { card: "summary_large_image", title, description },
  };
}

// Minimal markdown-to-HTML for body text. We only need: paragraphs,
// **bold**, *italics*, > blockquotes. Headers are explicitly disallowed
// by the prompt so we don't render them. No external dependency.
function renderMarkdown(text) {
  if (!text) return null;
  const blocks = text.split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  return blocks.map((block, i) => {
    if (block.startsWith("> ")) {
      const inner = block.replace(/^>\s?/gm, "").trim();
      return (
        <blockquote
          key={i}
          style={{
            borderLeft: "3px solid var(--cyan)",
            paddingLeft: 14,
            margin: "16px 0",
            color: "var(--subtext)",
            fontStyle: "italic",
          }}
          dangerouslySetInnerHTML={{ __html: applyInline(inner) }}
        />
      );
    }
    return (
      <p
        key={i}
        style={{ marginBottom: 14, lineHeight: 1.65, fontSize: "1.02rem" }}
        dangerouslySetInnerHTML={{ __html: applyInline(block) }}
      />
    );
  });
}

function applyInline(s) {
  // Escape angle brackets first, then apply bold/italic markdown.
  let out = s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/(^|[^*])\*([^*\n]+)\*([^*]|$)/g, "$1<em>$2</em>$3");
  return out;
}

export default async function ArticlePage({ params }) {
  const { season, week, matchupId, mode } = await params;
  const art = await fetchArticle(season, week, matchupId, mode);

  if (!art) {
    return (
      <section>
        <Card>
          <EmptyState
            title="Article not found"
            message={`No ${mode} on disk for ${season} Week ${week} matchup ${matchupId}. The cron may not have generated it yet.`}
          />
          <div style={{ marginTop: 10 }}>
            <Link href={`/league/articles/${season}/${week}`} style={{ color: "var(--cyan)" }}>
              ← Slate for Week {week}
            </Link>
          </div>
        </Card>
      </section>
    );
  }

  const subtitle = `${art.season} · Week ${art.week} · ${art.roundLabel || (art.isChampionship ? "Championship" : "Regular Season")} · ${mode === "preview" ? "Preview" : "Recap"}`;

  return (
    <section>
      <Card>
        <PageHeader title={art.title} subtitle={subtitle} />
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: -4, marginBottom: 16 }}>
          <Link
            href={`/league/articles/${season}/${week}`}
            style={{
              color: "var(--cyan)",
              fontSize: "0.74rem",
              textDecoration: "none",
              border: "1px solid var(--border-bright)",
              padding: "3px 10px",
              borderRadius: 6,
            }}
          >
            ← Slate
          </Link>
          <ShareButton title={art.title} text={art.kicker || art.lede || ""} />
          <span style={{ marginLeft: "auto", fontSize: "0.7rem", color: "var(--subtext)" }}>
            {art.angleUsed} · {art.persona} · {art.wordCount || 0} words
          </span>
        </div>

        <Matchup home={art.home} away={art.away} />

        {art.lede && (
          <p
            style={{
              fontSize: "1.18rem",
              lineHeight: 1.5,
              fontWeight: 600,
              borderLeft: "3px solid var(--cyan)",
              paddingLeft: 14,
              margin: "20px 0 22px",
            }}
          >
            {art.lede}
          </p>
        )}

        <article style={{ maxWidth: 720 }}>{renderMarkdown(art.body)}</article>

        {art.kicker && (
          <p
            style={{
              marginTop: 24,
              padding: 16,
              border: "1px solid var(--border-bright)",
              borderRadius: 8,
              fontSize: "1.04rem",
              fontWeight: 700,
              lineHeight: 1.45,
              background: "rgba(46, 204, 113, 0.05)",
            }}
          >
            {mode === "preview" ? "Bold prediction: " : "What it means: "}
            {art.kicker}
          </p>
        )}

        <p style={{ marginTop: 18, fontSize: "0.7rem", color: "var(--subtext)" }}>
          Generated {new Date(art.generatedAt).toLocaleString()} — {art.model}
        </p>
      </Card>
    </section>
  );
}

function Matchup({ home, away }) {
  if (!home && !away) return null;
  const sideStyle = { padding: "8px 12px", border: "1px solid var(--border)", borderRadius: 8, minWidth: 0 };
  const nameStyle = { fontSize: "0.96rem", fontWeight: 700 };
  const subStyle = { fontSize: "0.74rem", color: "var(--subtext)" };
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", alignItems: "center", gap: 10, marginBottom: 6 }}>
      <div style={sideStyle}>
        <div style={nameStyle}>{home?.teamName || home?.displayName || "—"}</div>
        <div style={subStyle}>{home?.displayName || ""}</div>
      </div>
      <div style={{ fontSize: "0.7rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>vs</div>
      <div style={sideStyle}>
        <div style={nameStyle}>{away?.teamName || away?.displayName || "—"}</div>
        <div style={subStyle}>{away?.displayName || ""}</div>
      </div>
    </div>
  );
}
