"use client";

// ArticlesSection — renders the slate of AI-generated previews or recaps
// for the most recent week with articles on disk.  Used by both the
// "Previews" and "Recaps" tabs on /league via the ``mode`` prop.
//
// Fetches /api/league/articles once and picks the most recent
// (season, week) group that has at least one article in the requested
// mode.  Off-season this lands on the prior season's championship
// week; in-season it lands on whatever the cron most recently wrote.

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card, EmptyCard } from "../shared.jsx";

// ``currentSeason`` / ``currentWeek`` are optional and come from the
// canonical ``matchupPreview`` contract section (see
// ./matchup-previews.jsx) — this component does NOT resolve the clock
// itself, because a second answer to "what week is it" is exactly the
// kind of duplicate owner /league avoids. When they are supplied and
// the newest slate on disk is for an older week, say so: the heading
// already named the season and week, but the subhead read
// "Wednesday-morning previews" in the present tense with nothing
// distinguishing "this week\'s articles" from "the last articles we
// have". Stale is not current.
export default function ArticlesSection({ mode, currentSeason = null, currentWeek = null }) {
  const [state, setState] = useState({ loading: true, error: "", articles: [] });

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const res = await fetch("/api/league/articles", { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = await res.json();
        if (!active) return;
        setState({ loading: false, error: "", articles: body.articles || [] });
      } catch (err) {
        if (!active) return;
        setState({ loading: false, error: String(err), articles: [] });
      }
    })();
    return () => { active = false; };
  }, []);

  if (state.loading) {
    return (
      <Card>
        <div style={{ padding: 20, color: "var(--subtext)" }}>Loading articles…</div>
      </Card>
    );
  }
  if (state.error) {
    return <EmptyCard label={`Failed to load articles: ${state.error}`} />;
  }

  // Filter to the requested mode, then group by (season, week).
  const filtered = state.articles.filter((a) => a.mode === mode);
  if (filtered.length === 0) {
    return (
      <EmptyCard
        label={mode === "preview" ? "No previews yet" : "No recaps yet"}
        message={
          mode === "preview"
            ? "Wednesday-morning previews will land here once the cron runs."
            : "Tuesday-morning recaps will land here once the week wraps."
        }
      />
    );
  }

  // Pick the most recent (season DESC, week DESC) group.
  const byKey = new Map();
  for (const a of filtered) {
    const k = `${a.season}:${a.week}`;
    if (!byKey.has(k)) byKey.set(k, []);
    byKey.get(k).push(a);
  }
  const groups = Array.from(byKey.entries())
    .map(([k, arts]) => {
      const [season, week] = k.split(":");
      return { season, week: Number(week), arts };
    })
    .sort((a, b) => {
      if (a.season !== b.season) return a.season < b.season ? 1 : -1;
      return b.week - a.week;
    });
  const latest = groups[0];
  const slate = latest.arts.sort((a, b) => {
    if (a.isChampionship !== b.isChampionship) return a.isChampionship ? -1 : 1;
    return (a.matchupId || 0) - (b.matchupId || 0);
  });

  // Known only when the caller supplied the clock; an unknown clock
  // must not be reported as a match, so the check requires both.
  const clockKnown = currentSeason !== null && currentWeek !== null;
  const isCurrentWeek =
    clockKnown && String(latest.season) === String(currentSeason) && latest.week === Number(currentWeek);
  const isOlderSlate = clockKnown && !isCurrentWeek;

  const heading = isOlderSlate
    ? mode === "preview"
      ? `Most recent previews · ${latest.season} Week ${latest.week}`
      : `Most recent recaps · ${latest.season} Week ${latest.week}`
    : mode === "preview"
      ? `Week ${latest.week} previews · ${latest.season}`
      : `Week ${latest.week} recaps · ${latest.season}`;
  const subhead = isOlderSlate
    ? `No ${mode === "preview" ? "previews" : "recaps"} written yet for ${currentSeason} Week ${currentWeek} — these are the most recent on file.`
    : mode === "preview"
      ? "Wednesday-morning previews. Tap a card for the full article."
      : "Tuesday-morning recaps. Tap a card for the full article.";

  return (
    <section>
      <Card title={heading}>
        <p style={{ fontSize: "0.84rem", color: "var(--subtext)", marginTop: -4 }}>{subhead}</p>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12, marginTop: 10 }}>
          {slate.map((art) => (
            <ArticleCard key={`${art.matchupId}-${art.mode}`} article={art} />
          ))}
        </div>
        <div style={{ marginTop: 16 }}>
          <Link
            href={`/league/articles/${latest.season}/${latest.week}`}
            style={{ color: "var(--cyan)", fontSize: "0.78rem" }}
          >
            View full slate page →
          </Link>
        </div>
      </Card>
    </section>
  );
}

function ArticleCard({ article }) {
  const homeName = article.home?.teamName || article.home?.displayName || "—";
  const awayName = article.away?.teamName || article.away?.displayName || "—";
  const href = `/league/articles/${article.season}/${article.week}/${article.matchupId}/${article.mode}`;
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
        background: article.isChampionship ? "rgba(255, 215, 0, 0.04)" : "rgba(255,255,255,0.02)",
      }}
    >
      <div style={{ fontSize: "0.62rem", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 6, color: "var(--cyan)" }}>
        {article.isChampionship ? "🏆 Championship" : (article.roundLabel || "")} {article.angleUsed ? `· ${article.angleUsed}` : ""}
      </div>
      <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginBottom: 8 }}>
        {homeName} vs {awayName}
      </div>
      <div style={{ fontSize: "0.98rem", fontWeight: 700, lineHeight: 1.3, marginBottom: 6 }}>
        {article.title}
      </div>
      {article.kicker && (
        <div style={{ fontSize: "0.8rem", lineHeight: 1.4, color: "var(--subtext)", fontStyle: "italic" }}>
          {article.kicker}
        </div>
      )}
      <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 8 }}>
        {article.wordCount || 0} words · {new Date(article.generatedAt).toLocaleDateString()}
      </div>
    </Link>
  );
}
