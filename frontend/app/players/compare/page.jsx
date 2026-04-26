"use client";

// Player comparison view — /players/compare?p1=Name&p2=Name
//
// Side-by-side comparison of two players: value, blended consensus
// rank, source disagreement, age curve, recent rank trajectory.
// Drives the "is this trade fair?" decision faster than alt-tabbing
// between two PlayerPopup instances.
//
// Data flows entirely through ``useDynastyData`` — no new API.  URL
// query params seed the initial picks so the view is shareable; the
// search inputs let the user retarget without round-tripping through
// the rankings page.
//
// Unmatched names render an EmptyState; one match + one missing renders
// the matched side normally and a "search for a player" prompt on the
// other side.

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter } from "next/navigation";

import { useDynastyData } from "@/components/useDynastyData";
import { useSettings } from "@/components/useSettings";
import {
  PageHeader,
  LoadingState,
  EmptyState,
  PlayerImage,
} from "@/components/ui";
import {
  fmtNumber,
  fmtPoints,
} from "@/app/league/shared-helpers.js";
import { effectiveValue } from "@/lib/trade-logic";
import { posBadgeClass } from "@/lib/display-helpers";

function findRow(rows, query) {
  if (!query) return null;
  const q = String(query).trim().toLowerCase();
  if (!q) return null;
  // Exact then prefix then substring.
  let exact = null;
  let prefix = null;
  let sub = null;
  for (const r of rows) {
    const name = String(r.name || "").toLowerCase();
    if (!name) continue;
    if (name === q) {
      exact = r;
      break;
    }
    if (!prefix && name.startsWith(q)) prefix = r;
    if (!sub && name.includes(q)) sub = r;
  }
  return exact || prefix || sub || null;
}

function PlayerColumn({ row, settings, valueMode = "full" }) {
  if (!row) {
    return (
      <div className="card" style={{ flex: 1, minWidth: 280 }}>
        <EmptyState
          title="No player matched"
          message="Try a different spelling or pick from the search field above."
        />
      </div>
    );
  }
  const value = Math.round(effectiveValue(row, valueMode, settings) || 0);
  const rank = row.canonicalConsensusRank;
  const blended = row.blendedSourceRank;
  // Recent rank trajectory from the row's ``rankHistory`` series.
  const history = Array.isArray(row.rankHistory) ? row.rankHistory : null;
  const earliest = history && history.length > 0 ? history[0].rank : null;
  const latest = history && history.length > 0 ? history[history.length - 1].rank : null;
  const trajectory = (earliest && latest) ? earliest - latest : null;

  // Source disagreement — pull the per-source ranks so the user can
  // see who likes / dislikes this player most strongly.
  const sourceRanks = row.sourceOriginalRanks || row.sourceRanks || {};
  const sortedSourceRanks = Object.entries(sourceRanks)
    .filter(([, v]) => Number.isFinite(Number(v)))
    .sort((a, b) => Number(a[1]) - Number(b[1]));

  return (
    <div className="card" style={{ flex: 1, minWidth: 280 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.team}
          position={row.pos}
          name={row.name}
          size={56}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <h2 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700 }}>{row.name}</h2>
          <div style={{ fontSize: "0.74rem", color: "var(--subtext)", display: "flex", gap: 6, alignItems: "center", marginTop: 2 }}>
            <span className={posBadgeClass(row)}>{row.pos}</span>
            {row.team && <span>{row.team}</span>}
            {row.age && <span>· {row.age} yo</span>}
            {row.rookie && <span style={{ color: "var(--cyan)" }}>· rookie</span>}
          </div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 12 }}>
        <Stat label="Value" value={value.toLocaleString()} accent />
        <Stat label="Consensus rank" value={rank ? `#${rank}` : "—"} />
        <Stat label="Blended rank" value={blended != null ? blended.toFixed(1) : "—"} />
        <Stat
          label="30d trend"
          value={
            trajectory == null
              ? "—"
              : trajectory > 0
                ? `▲ ${trajectory}`
                : trajectory < 0
                  ? `▼ ${Math.abs(trajectory)}`
                  : "flat"
          }
          color={
            trajectory == null
              ? "var(--text)"
              : trajectory > 0
                ? "var(--green)"
                : trajectory < 0
                  ? "var(--red)"
                  : "var(--subtext)"
          }
        />
      </div>

      <div>
        <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
          Per-source ranks · best on top
        </div>
        {sortedSourceRanks.length === 0 ? (
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>—</div>
        ) : (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4, fontSize: "0.62rem", fontFamily: "var(--mono)" }}>
            {sortedSourceRanks.map(([src, r]) => (
              <span
                key={src}
                style={{
                  background: "rgba(255, 199, 4, 0.06)",
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  padding: "2px 6px",
                }}
                title={`${src}: rank ${r}`}
              >
                <span style={{ color: "var(--subtext)" }}>{src}</span>{" "}
                <span style={{ color: "var(--cyan)" }}>#{r}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {row.confidenceLabel && (
        <div style={{ marginTop: 10, fontSize: "0.7rem", color: "var(--subtext)" }}>
          Confidence: <span style={{ color: "var(--text)", fontWeight: 600 }}>{row.confidenceLabel}</span>
          {(row.anomalyFlags || []).length > 0 && (
            <span style={{ color: "var(--amber)", marginLeft: 6 }}>· anomalies: {row.anomalyFlags.join(", ")}</span>
          )}
        </div>
      )}

      {(row.marketGapDirection && row.marketGapDirection !== "none") && (
        <div style={{ marginTop: 6, fontSize: "0.7rem", color: "var(--subtext)" }}>
          Market gap:{" "}
          <span style={{ color: row.marketGapDirection === "buy" ? "var(--green)" : "var(--red)", fontWeight: 600 }}>
            {row.marketGapDirection.toUpperCase()}
          </span>
          {row.marketGapMagnitude != null && (
            <span> · magnitude {fmtPoints(row.marketGapMagnitude)}</span>
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color, accent }) {
  return (
    <div
      style={{
        background: "rgba(8, 19, 44, 0.45)",
        border: "1px solid var(--border)",
        borderRadius: 6,
        padding: "6px 8px",
      }}
    >
      <div style={{ fontSize: "0.6rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--mono)",
          fontWeight: 700,
          fontSize: accent ? "1.05rem" : "0.92rem",
          marginTop: 2,
          color: color || (accent ? "var(--cyan)" : "var(--text)"),
        }}
      >
        {value}
      </div>
    </div>
  );
}

// Inline small "search-and-pick" input.  Type a name, see top 6
// matches, click to set.
function PlayerSearch({ rows, value, onChange, label }) {
  const [open, setOpen] = useState(false);
  const matches = useMemo(() => {
    const q = String(value || "").trim().toLowerCase();
    if (!q) return [];
    return rows
      .filter((r) => String(r.name || "").toLowerCase().includes(q))
      .slice(0, 8);
  }, [rows, value]);
  return (
    <div style={{ position: "relative", flex: "1 1 240px", minWidth: 220 }}>
      <label style={{ fontSize: "0.66rem", color: "var(--subtext)", display: "block", marginBottom: 2 }}>
        {label}
      </label>
      <input
        type="search"
        className="input"
        placeholder="Type a player name…"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        style={{ width: "100%" }}
      />
      {open && matches.length > 0 && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 30,
            marginTop: 4,
            background: "rgba(8, 19, 44, 0.96)",
            border: "1px solid var(--border-bright)",
            borderRadius: 6,
            padding: 4,
            maxHeight: 220,
            overflowY: "auto",
          }}
        >
          {matches.map((r) => (
            <button
              key={r.name}
              type="button"
              className="button-reset"
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(r.name);
                setOpen(false);
              }}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                width: "100%",
                padding: "4px 6px",
                fontSize: "0.74rem",
                cursor: "pointer",
                borderRadius: 4,
              }}
            >
              <PlayerImage
                playerId={r.raw?.playerId}
                team={r.team}
                position={r.pos}
                name={r.name}
                size={20}
              />
              <span style={{ fontWeight: 600 }}>{r.name}</span>
              <span style={{ color: "var(--subtext)", fontSize: "0.66rem" }}>
                {r.pos}
                {r.team ? ` · ${r.team}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ComparePlayersPage() {
  // ``useSearchParams`` requires a Suspense boundary during static
  // prerender (Next 15 enforces this).  Wrap the actual page body
  // in ``Suspense`` and let the fallback show during the brief CSR
  // bail-out on first paint.
  return (
    <Suspense fallback={<LoadingState message="Loading player comparison…" />}>
      <ComparePageBody />
    </Suspense>
  );
}

function ComparePageBody() {
  const { rows, loading, error } = useDynastyData();
  const settings = useSettings();
  const searchParams = useSearchParams();
  const router = useRouter();

  const [p1, setP1] = useState("");
  const [p2, setP2] = useState("");

  // Seed from URL on first load.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const a = searchParams.get("p1") || "";
    const b = searchParams.get("p2") || "";
    if (a && !p1) setP1(a);
    if (b && !p2) setP2(b);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  // Push updates to URL so the view is shareable + back-stack
  // navigable.  Replace rather than push so rapid keystrokes don't
  // pollute history.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams();
    if (p1) params.set("p1", p1);
    if (p2) params.set("p2", p2);
    const qs = params.toString();
    const url = qs ? `/players/compare?${qs}` : "/players/compare";
    router.replace(url);
  }, [p1, p2, router]);

  const row1 = useMemo(() => findRow(rows, p1), [rows, p1]);
  const row2 = useMemo(() => findRow(rows, p2), [rows, p2]);

  if (loading) return <LoadingState message="Loading player pool…" />;
  if (error) return <EmptyState title="Error" message={error} />;

  return (
    <section>
      <div className="card" style={{ marginBottom: "var(--space-md)" }}>
        <PageHeader
          title="Player comparison"
          subtitle="Side-by-side value, ranks, source agreement, and trajectory.  Share via URL."
        />
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, marginTop: 8 }}>
          <PlayerSearch rows={rows} value={p1} onChange={setP1} label="Player 1" />
          <PlayerSearch rows={rows} value={p2} onChange={setP2} label="Player 2" />
        </div>
      </div>

      <div className="row" style={{ gap: 12, alignItems: "stretch" }}>
        <PlayerColumn row={row1} settings={settings} valueMode="full" />
        <PlayerColumn row={row2} settings={settings} valueMode="full" />
      </div>

      {row1 && row2 && (
        <div className="card" style={{ marginTop: "var(--space-md)" }}>
          <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>
            Quick verdict
          </div>
          {(() => {
            const v1 = effectiveValue(row1, "full", settings) || 0;
            const v2 = effectiveValue(row2, "full", settings) || 0;
            const diff = Math.round(Math.abs(v1 - v2));
            const winnerName = v1 > v2 ? row1.name : v2 > v1 ? row2.name : null;
            const pctGap = Math.round((diff / Math.max(v1, v2)) * 100);
            if (!winnerName) {
              return (
                <div style={{ fontSize: "0.86rem" }}>
                  Dead even — both at {fmtNumber(v1, 0)}.
                </div>
              );
            }
            const tone = pctGap < 5 ? "var(--cyan)" : pctGap < 12 ? "var(--amber)" : "var(--red)";
            return (
              <div style={{ fontSize: "0.86rem" }}>
                <strong style={{ color: tone }}>{winnerName}</strong> leads by{" "}
                <strong>{diff.toLocaleString()}</strong> ({pctGap}%).{" "}
                <span style={{ color: "var(--subtext)" }}>
                  {pctGap < 5
                    ? "Effectively even — fair 1-for-1."
                    : pctGap < 12
                      ? "Slight lean — small balancer would close the gap."
                      : "Stretch — needs a meaningful add-on to balance."}
                </span>
              </div>
            );
          })()}
        </div>
      )}
    </section>
  );
}
