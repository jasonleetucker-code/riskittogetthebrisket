"use client";

// PreviewsSection — the public "Previews" tab.
//
// Composes two DIFFERENT things about the same week, in the order a
// reader wants them:
//
//   1. the STRUCTURED head-to-head preview for the CURRENT week, from
//      the canonical `matchupPreview` contract section;
//   2. the AI-written preview articles (`ArticlesSection`), which are
//      generated on a cron and may not exist yet for this week.
//
// Why (1) exists at all. The structured "This Week" tab was retired
// when the article tabs landed, on the reasoning — recorded in
// `../tabs.js` — that "the articles surface the same H2H + form data
// inline (the brief is built from it), so the structured-data tabs are
// redundant once articles are wired in." That is true whenever an
// article exists for the current week. It is NOT true otherwise, and
// the gap is not hypothetical: on 2026-09-05, Week 1 of the season,
// `/api/public/league/matchupPreview` served all six upcoming matchups
// with real H2H and form data while the Previews tab showed the 2025
// Week 17 articles, because narrative generation is blocked on a
// missing `ANTHROPIC_API_KEY`. The current week's pregame content was
// computed, served, correct — and reachable from no public surface.
//
// So this block is a FALLBACK PATH FOR A MISSING ARTICLE, not a second
// preview owner. It renders only while the contract reports
// `mode === "preview"` (the week is genuinely unscored); once the week
// scores, the recap surfaces own it and this disappears. It recomputes
// nothing — every number below is read verbatim from the section, the
// same materializer relationship the rest of /league has with the
// contract.
//
// Missing is never zero, throughout: a first-ever meeting renders as
// "First meeting" with NO margin (the contract answers `null`, and a
// margin over an empty series is undefined, not 0.0), and a manager
// with no prior games renders "No prior games" rather than "0-0".

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { LoadingState } from "@/components/ui";
import { Card } from "../shared-server.jsx";
import { Avatar } from "../shared.jsx";
import { buildManagerLookup, fmtPoints } from "../shared-helpers.js";

const ArticlesSection = dynamic(() => import("./articles.jsx"), {
  ssr: false,
  loading: () => <LoadingState message="Loading articles..." />,
});

// Module-level cache so tab-switching doesn't re-fetch. Same shape and
// TTL as ros-power.jsx's cache.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, error: null, inflight: null, fetchedAt: 0 };

async function _fetchPreview() {
  const fresh = _cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _cache.data, error: null };
  if (_cache.inflight) return _cache.inflight;

  const promise = fetch("/api/public/league/matchupPreview")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
    .then((body) => {
      _cache.data = body;
      _cache.error = null;
      _cache.fetchedAt = Date.now();
      _cache.inflight = null;
      return { data: body, error: null };
    })
    .catch((err) => {
      _cache.inflight = null;
      // Deliberately NOT cached: a transient 503 must not suppress the
      // block for the rest of the session.
      return { data: null, error: String(err) };
    });
  _cache.inflight = promise;
  return promise;
}

function seriesLine(h2h) {
  if (!h2h) return null;
  const total = h2h.totalMeetings || 0;
  if (total === 0) return "First meeting";
  const parts = [`${h2h.homeWins}-${h2h.awayWins}${h2h.ties ? `-${h2h.ties}` : ""}`];
  if (h2h.playoffMeetings) {
    parts.push(`${h2h.playoffMeetings} playoff`);
  }
  // `avgMargin` is null for a series with no meetings; guarded above,
  // but a null here must still never print as "0.0".
  if (h2h.avgMargin !== null && h2h.avgMargin !== undefined) {
    parts.push(`avg margin ${fmtPoints(h2h.avgMargin)}`);
  }
  return `${total} ${total === 1 ? "meeting" : "meetings"} · ${parts.join(" · ")}`;
}

function FormLine({ label, form }) {
  const games = (form && form.games) || [];
  if (!games.length) {
    return (
      <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
        {label}: <span style={{ fontStyle: "italic" }}>No prior games</span>
      </div>
    );
  }
  // `avgPoints` is null when the window is empty; that case is handled
  // above, so a value here is real.
  const avg = form.avgPoints === null || form.avgPoints === undefined ? null : fmtPoints(form.avgPoints);
  const scope = form.isPriorSeasonOnly ? " (prior season)" : "";
  return (
    <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
      {label}: {form.record}
      {avg ? ` · ${avg} avg` : ""}
      {scope}
      {" "}
      <span aria-hidden="true">
        {games.map((g) => (g.result === "W" ? "W" : g.result === "L" ? "L" : "T")).join("")}
      </span>
    </div>
  );
}

function MatchupCard({ matchup, managers }) {
  const home = matchup.home || {};
  const away = matchup.away || {};
  const h2h = matchup.h2h || {};
  const form = matchup.form || {};
  return (
    <div
      style={{
        border: "1px solid var(--border-bright)",
        borderRadius: 8,
        padding: 12,
        background: "rgba(255,255,255,0.02)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Avatar managers={managers} ownerId={home.ownerId} size={26} />
        <span style={{ color: "var(--subtext)", fontWeight: 700 }}>vs</span>
        <Avatar managers={managers} ownerId={away.ownerId} size={26} />
      </div>
      <div style={{ fontSize: "0.95rem", fontWeight: 800, marginTop: 6, lineHeight: 1.25 }}>
        {home.displayName} vs {away.displayName}
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
        {home.teamName} · {away.teamName}
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--cyan)", marginTop: 8 }}>{seriesLine(h2h)}</div>
      {h2h.narrative && (
        <div style={{ fontSize: "0.74rem", marginTop: 4, lineHeight: 1.35 }}>{h2h.narrative}</div>
      )}
      <div style={{ marginTop: 8, display: "grid", gap: 2 }}>
        <FormLine label={home.displayName} form={form.home} />
        <FormLine label={away.displayName} form={form.away} />
      </div>
    </div>
  );
}

export default function PreviewsSection() {
  const [state, setState] = useState({ loading: true, payload: null, error: "" });

  useEffect(() => {
    let active = true;
    _fetchPreview().then(({ data, error }) => {
      if (!active) return;
      setState({ loading: false, payload: data, error: error || "" });
    });
    return () => {
      active = false;
    };
  }, []);

  const data = state.payload && state.payload.data;
  // ``Avatar`` takes the lookup Map, not the contract's manager ARRAY.
  const managers = buildManagerLookup(state.payload && state.payload.league);
  const matchups = (data && data.matchups) || [];
  // Only an UNSCORED week gets the structured block. A scored week is
  // owned by the recap surfaces, and rendering both would be the second
  // owner this section exists to avoid.
  const showStructured = !state.loading && data && data.mode === "preview" && matchups.length > 0;

  return (
    <section>
      {state.loading && <LoadingState message="Loading this week's matchups..." />}
      {showStructured && (
        <Card
          title={`Week ${data.currentWeek} matchups · ${data.currentSeason}`}
          subtitle="Head-to-head history and recent form for every upcoming matchup."
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 12,
              marginTop: 10,
            }}
          >
            {matchups.map((m) => (
              <MatchupCard key={m.matchupId} matchup={m} managers={managers} />
            ))}
          </div>
        </Card>
      )}
      <div style={{ marginTop: showStructured ? "var(--space-md)" : 0 }}>
        <ArticlesSection
          mode="preview"
          currentSeason={data ? data.currentSeason : null}
          currentWeek={data ? data.currentWeek : null}
        />
      </div>
    </section>
  );
}
