"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useNews } from "@/components/useNews";
import { useUserState } from "@/components/useUserState";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { buildPublicActivityEvents, filterEvents } from "@/lib/activity-feed";
import { fetchPublicSection } from "@/lib/public-league-data";
import { FailureState } from "@/components/ds";
import { classifyContractFailure, classifyContractTimeout } from "@/lib/contract-failure";

/**
 * Classify a `fetchPublicSection` rejection.  That reader throws
 * `Public league fetch failed (<status>) for <url>` for an HTTP refusal — a
 * message this codebase writes, carrying only the status and a constant URL
 * (never server text) — a TimeoutError for its deadline, and the browser's
 * own TypeError when no response arrived; a body that is not JSON surfaces
 * as a SyntaxError.  Anything else is reported as an unclassified error, not
 * guessed at.
 */
export function activityFailure(err) {
  if (err?.name === "TimeoutError") return classifyContractTimeout();
  const status = /^Public league fetch failed \((\d{3})\)/.exec(err?.message || "")?.[1];
  if (status) return classifyContractFailure(Number(status), null);
  if (err instanceof TypeError) return classifyContractFailure(null, null);
  if (err instanceof SyntaxError) {
    return {
      kind: "no_data",
      code: "",
      message: "The server answered without readable activity data.",
      retryable: true,
    };
  }
  return { kind: "error", code: "", message: "Could not load league activity.", retryable: true };
}

const SCOPE_OPTIONS = [
  { key: "league", label: "League" },
  { key: "roster", label: "My roster" },
];

const TYPE_OPTIONS = [
  { key: "all", label: "All" },
  { key: "trade", label: "Trades" },
  { key: "news", label: "News" },
];

function fmtRelative(ts) {
  if (!ts) return "—";
  const diffMs = Date.now() - ts;
  if (diffMs < 0) return "just now";
  const minutes = diffMs / 60_000;
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${Math.round(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 30) return `${Math.round(days)}d ago`;
  return `${Math.round(days / 30)}mo ago`;
}

function severityChip(severity) {
  if (severity === "alert" || severity === "high") {
    return { label: "Alert", css: "badge-amber" };
  }
  if (severity === "injury") return { label: "Injury", css: "badge-red" };
  return null;
}

function FilterPills({ options, value, onChange, ariaLabel }) {
  return (
    <div role="tablist" aria-label={ariaLabel} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
      {options.map((opt) => {
        const active = opt.key === value;
        return (
          <button
            key={opt.key}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.key)}
            className={active ? "button" : "button-outline"}
            style={{ fontSize: "0.74rem", padding: "4px 10px", minHeight: 32 }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

function humanizeNewsReason(reason) {
  switch (reason) {
    case "fetch_failed":
      return "Could not reach the news endpoint. Check your connection and reload.";
    case "backend_unavailable":
      return "The news backend is temporarily unavailable. This feed will recover once it responds again — nothing is cached or simulated.";
    default:
      return "The news feed returned an unexpected response.";
  }
}

// `leagueHome`: the "← League home" href, decided on the server by
// ./page.jsx (`/league` exactly as main unless the Brisket Trade Advisor
// is confirmed served).  Defaults to main's `/league`.
export default function ActivityClient({ leagueHome = "/league" } = {}) {
  const { state: userState } = useUserState();
  const {
    items: newsItems,
    unavailable: newsUnavailable,
    reason: newsReason,
  } = useNews();
  const [scope, setScope] = useState("league");
  const [type, setType] = useState("all");

  // This page sits under the public-only route prefix, where AppShell
  // hard-codes ``rawData: null`` so the private contract can never
  // hydrate on a /league URL.  It used to read that null anyway, which
  // is why the trade half of the feed was always empty — even for
  // signed-in users.  Trades come from the public league pipeline
  // instead, which already publishes them with public-safe grade
  // badges.
  const [trades, setTrades] = useState(null);
  const [loading, setLoading] = useState(true);
  // A CLASSIFIED failure, never the raw thrown text; `reloadKey` is what
  // "Try again" bumps to re-run the fetch below.
  const [failure, setFailure] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailure(null);
    fetchPublicSection("activity")
      .then((payload) => {
        if (cancelled) return;
        setTrades(payload?.data?.feed || []);
      })
      .catch((err) => {
        if (cancelled) return;
        setTrades([]);
        setFailure(activityFailure(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  // Owner id is enough to scope the feed to "my" trades — the public
  // payload stamps ownerId on every side, so no roster snapshot (and
  // no private data) is needed to answer "was I in this trade?".
  const myOwnerId = userState?.selectedTeam?.ownerId || null;

  const allEvents = useMemo(
    () => buildPublicActivityEvents(trades, newsItems),
    [trades, newsItems],
  );

  const events = useMemo(
    () => filterEvents(allEvents, { scope, type, ownerId: myOwnerId }),
    [allEvents, scope, type, myOwnerId],
  );

  if (loading) return <LoadingState message="Loading league activity…" />;
  if (failure) {
    return (
      <section>
        <PageHeader title="Activity" subtitle="Trades + news in one feed." />
        <FailureState
          failure={failure}
          onRetry={() => setReloadKey((n) => n + 1)}
          context="league activity"
          variant="block"
        />
      </section>
    );
  }

  return (
    <section>
      <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
        <Link href={leagueHome} style={{ color: "var(--cyan)" }}>← League home</Link>
      </div>
      <PageHeader
        title="Activity"
        subtitle="Trades + news in one chronological feed.  Scope to your roster to see only events involving your players."
      />

      <div className="card" style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>Scope</div>
          <FilterPills options={SCOPE_OPTIONS} value={scope} onChange={setScope} ariaLabel="Scope" />
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>Type</div>
          <FilterPills options={TYPE_OPTIONS} value={type} onChange={setType} ariaLabel="Event type" />
        </div>
        {scope === "roster" && !myOwnerId && (
          <p className="muted" style={{ fontSize: "0.7rem", margin: 0, color: "var(--amber)" }}>
            Sign in and pick your team to use the &quot;My roster&quot; scope.
          </p>
        )}
      </div>

      {/* News-outage handling (same honest treatment as the News
          tab): the News-only view renders the explicit unavailable
          state instead of a misleading "No activity"; mixed views
          keep roster/transaction activity and just note that the
          news portion is missing. */}
      {newsUnavailable && type === "news" ? (
        <div className="card" role="alert" style={{ borderColor: "var(--red)" }}>
          <strong style={{ color: "var(--red)" }}>News unavailable</strong>
          <div className="muted" style={{ fontSize: "0.78rem", marginTop: 4 }}>
            {humanizeNewsReason(newsReason)}
          </div>
        </div>
      ) : events.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No activity in this view"
            message={
              newsUnavailable && type === "all"
                ? "News is unavailable right now, and no trades or roster activity match these filters."
                : "Try widening the scope or changing the type filter."
            }
          />
        </div>
      ) : (
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {newsUnavailable && type === "all" && (
            <div
              role="status"
              className="muted"
              style={{ fontSize: "0.72rem", color: "var(--amber)" }}
            >
              News unavailable right now — showing trades and roster
              activity only.
            </div>
          )}
          <div className="muted" style={{ fontSize: "0.7rem" }}>
            {events.length} event{events.length === 1 ? "" : "s"} · newest first
          </div>
          {events.slice(0, 80).map((e) => {
            const chip = severityChip(e.severity);
            const teamLine = (e.teamNames || []).slice(0, 4).join(" · ");
            const playerLine = (e.playerNames || []).slice(0, 6).join(" · ");
            return (
              <div
                key={e.id}
                style={{
                  padding: "10px 0",
                  borderTop: "1px solid var(--border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span
                    className={`badge ${e.type === "trade" ? "badge-amber" : "badge-blue"}`}
                    style={{ fontSize: "0.66rem" }}
                  >
                    {e.type === "trade" ? "TRADE" : "NEWS"}
                  </span>
                  {chip && (
                    <span className={`badge ${chip.css}`} style={{ fontSize: "0.66rem" }}>
                      {chip.label}
                    </span>
                  )}
                  <span className="muted" style={{ fontSize: "0.7rem" }}>{fmtRelative(e.ts)}</span>
                  {e.url ? (
                    <a
                      href={e.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{
                        marginLeft: "auto",
                        color: "var(--cyan)",
                        fontSize: "0.7rem",
                        textDecoration: "none",
                      }}
                    >
                      Read source →
                    </a>
                  ) : null}
                </div>
                <div style={{ fontSize: "0.86rem", fontWeight: 600 }}>{e.title}</div>
                {(teamLine || e.detail || playerLine) && (
                  <div className="muted" style={{ fontSize: "0.74rem" }}>
                    {teamLine && (
                      <div><strong>Teams:</strong> {teamLine}</div>
                    )}
                    {playerLine && e.type === "trade" && (
                      <div><strong>Players:</strong> {playerLine}</div>
                    )}
                    {e.detail && (
                      <div style={{ marginTop: 4 }}>{e.detail}</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
