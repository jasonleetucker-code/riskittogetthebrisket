"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { PageHeader, LoadingState, EmptyState, PlayerImage } from "@/components/ui";
import {
  WINDOW_OPTIONS,
  DIRECTION_OPTIONS,
  computeMovers,
  filterByFamily,
  fmtDelta,
} from "@/lib/movers";

const FAMILY_OPTIONS = [
  { key: "ALL", label: "All" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

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
            style={{
              fontSize: "0.74rem",
              padding: "4px 10px",
              minHeight: 32,
              opacity: active ? 1 : 0.78,
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export default function TrendingPage() {
  const { rows, loading, error } = useApp();
  const [windowKey, setWindowKey] = useState("7d");
  const [direction, setDirection] = useState("all");
  const [family, setFamily] = useState("ALL");

  const movers = useMemo(() => {
    const window = WINDOW_OPTIONS.find((w) => w.key === windowKey) || WINDOW_OPTIONS[1];
    const all = computeMovers(rows || [], {
      windowDays: window.days,
      direction,
      limit: 200,
    });
    return filterByFamily(all, family);
  }, [rows, windowKey, direction, family]);

  if (loading) return <LoadingState message="Loading rank history…" />;
  if (error) {
    return (
      <section>
        <PageHeader title="Trending" subtitle="Biggest value movers across the board." />
        <div className="card">
          <EmptyState title="Couldn't load data" message={String(error)} />
        </div>
      </section>
    );
  }

  return (
    <section>
      <PageHeader
        title="Trending"
        subtitle="Biggest rank movers across the board — gainers and losers since the chosen window."
      />

      <div className="card" style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 10 }}>
        <div>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>Window</div>
          <FilterPills
            options={WINDOW_OPTIONS}
            value={windowKey}
            onChange={setWindowKey}
            ariaLabel="Time window"
          />
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>Direction</div>
          <FilterPills
            options={DIRECTION_OPTIONS}
            value={direction}
            onChange={setDirection}
            ariaLabel="Movement direction"
          />
        </div>
        <div>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>Position family</div>
          <FilterPills
            options={FAMILY_OPTIONS}
            value={family}
            onChange={setFamily}
            ariaLabel="Position family"
          />
        </div>
      </div>

      {movers.length === 0 ? (
        <div className="card">
          <EmptyState
            title="No movers in this window"
            message="Try widening the window or changing direction."
          />
        </div>
      ) : (
        <div className="card">
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 6 }}>
            {movers.length} player{movers.length === 1 ? "" : "s"} · sorted by absolute rank change
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Player</th>
                  <th style={{ textAlign: "left" }}>Pos</th>
                  <th style={{ textAlign: "right" }}>Rank</th>
                  <th style={{ textAlign: "right" }}>Δ rank</th>
                  <th style={{ textAlign: "right" }}>Value</th>
                </tr>
              </thead>
              <tbody>
                {movers.map((m) => {
                  const positive = m.delta > 0;
                  const color = positive ? "var(--green)" : "var(--red)";
                  return (
                    <tr key={`${m.name}::${m.pos}`}>
                      <td style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <PlayerImage name={m.name} sleeperId={m.sleeperId} size={22} />
                        <span style={{ fontWeight: 600 }}>{m.name}</span>
                        {m.teamAbbr && (
                          <span className="muted" style={{ fontSize: "0.66rem" }}>
                            {m.teamAbbr}
                          </span>
                        )}
                      </td>
                      <td>
                        <span className="badge" style={{ fontSize: "0.68rem" }}>{m.pos}</span>
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {m.currentRank ?? "—"}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color, fontWeight: 700 }}>
                        {fmtDelta(m.delta)}
                      </td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                        {Math.round(m.value).toLocaleString()}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
