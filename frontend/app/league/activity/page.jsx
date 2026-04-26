"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useApp } from "@/components/AppShell";
import { useNews } from "@/components/useNews";
import { useUserState } from "@/components/useUserState";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { buildActivityEvents, filterEvents } from "@/lib/activity-feed";

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

export default function ActivityPage() {
  const { rawData, loading, error } = useApp();
  const { state: userState } = useUserState();
  const { items: newsItems } = useNews();
  const [scope, setScope] = useState("league");
  const [type, setType] = useState("all");

  const myTeam = useMemo(() => {
    const ownerId = userState?.selectedTeam?.ownerId;
    if (!ownerId) return null;
    return (rawData?.sleeper?.teams || []).find(
      (t) => String(t?.ownerId) === String(ownerId),
    ) || null;
  }, [rawData, userState]);

  const allEvents = useMemo(
    () => buildActivityEvents(rawData, newsItems),
    [rawData, newsItems],
  );

  const events = useMemo(
    () => filterEvents(allEvents, {
      scope,
      type,
      rosterNames: myTeam?.players || [],
    }),
    [allEvents, scope, type, myTeam],
  );

  if (loading) return <LoadingState message="Loading league activity…" />;
  if (error) {
    return (
      <section>
        <PageHeader title="League activity" subtitle="Trades + news in one feed." />
        <div className="card">
          <EmptyState title="Couldn't load data" message={String(error)} />
        </div>
      </section>
    );
  }

  return (
    <section>
      <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
        <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
      </div>
      <PageHeader
        title="League activity"
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
        {scope === "roster" && !myTeam && (
          <p className="muted" style={{ fontSize: "0.7rem", margin: 0, color: "var(--amber)" }}>
            Pick your team on the league page to use the &quot;My roster&quot; scope.
          </p>
        )}
      </div>

      {events.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No activity in this view"
            message="Try widening the scope or changing the type filter."
          />
        </div>
      ) : (
        <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
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
