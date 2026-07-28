"use client";

/**
 * BdvmTradePanel — the fundamental (BDVM) read on the CURRENT trade,
 * rendered beside the market grade on /trade.
 *
 * POSTs both sides' assets to /api/bdvm/trade-eval and shows the CES
 * package value per strategy currency. Pure display: every number is
 * backend-computed; this panel never touches sideTotals/TradeMeter
 * (fundamental is COMPARED against market, never merged — CLAUDE.md).
 *
 * Degrade contract (rankings gap-column precedent for add-on
 * surfaces): any 503 (flag off, no snapshot, wrong league), network
 * error, or non-ok status → the panel renders NOTHING. Assets the
 * fundamental board declines to price are listed, never zeroed
 * silently — the backend reports them per side.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Panel } from "@/components/ds";
import { BDVM_STRATEGIES, formatBdvmValue } from "@/lib/bdvm";

const LEAGUE_LOCAL_KEY = "next_active_league_v1";

function readActiveLeagueKey() {
  if (typeof window === "undefined") return "";
  try {
    return localStorage.getItem(LEAGUE_LOCAL_KEY) || "";
  } catch {
    return "";
  }
}

function sideRefs(side) {
  return (side?.assets || []).map((row) => ({
    playerId: String(row?.raw?.playerId ?? row?.playerId ?? "").trim() || undefined,
    name: row?.name || "",
  }));
}

export default function BdvmTradePanel({ sides, leagueKey }) {
  const [result, setResult] = useState(null);
  const abortRef = useRef(null);

  // Two-team trades only — the CES eval is a two-sided comparison.
  const twoTeam = Array.isArray(sides) && sides.length === 2;
  const refsA = useMemo(() => (twoTeam ? sideRefs(sides[0]) : []), [sides, twoTeam]);
  const refsB = useMemo(() => (twoTeam ? sideRefs(sides[1]) : []), [sides, twoTeam]);
  const signature = useMemo(
    () => JSON.stringify([refsA.map((r) => r.name), refsB.map((r) => r.name), leagueKey]),
    [refsA, refsB, leagueKey],
  );

  useEffect(() => {
    if (!twoTeam || refsA.length === 0 || refsB.length === 0) {
      setResult(null);
      return undefined;
    }
    const timer = setTimeout(async () => {
      abortRef.current?.abort();
      const ctl = new AbortController();
      abortRef.current = ctl;
      try {
        const res = await fetch("/api/bdvm/trade-eval", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          signal: ctl.signal,
          body: JSON.stringify({
            sideA: refsA,
            sideB: refsB,
            leagueKey: leagueKey || readActiveLeagueKey() || undefined,
          }),
        });
        const body = await res.json().catch(() => null);
        // Flag off / not ready / unavailable / anything non-ok →
        // vanish silently. Never a generic error on an add-on panel.
        if (!res.ok || !body || body.status !== "ok") {
          setResult(null);
          return;
        }
        setResult(body);
      } catch {
        setResult(null);
      }
    }, 600);
    return () => {
      clearTimeout(timer);
      abortRef.current?.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  if (!result) return null;
  const unresolved = [
    ...(result.unresolved?.sideA || []),
    ...(result.unresolved?.sideB || []),
  ];

  return (
    <Panel
      title="Fundamentals check (BDVM)"
      subtitle="CES package values per strategy currency — does NOT change the trade math above"
    >
      <table className="bdvm-trade-table" style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", padding: "4px 8px" }}>Strategy</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Side A</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Side B</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Edge (A−B)</th>
          </tr>
        </thead>
        <tbody>
          {BDVM_STRATEGIES.map(({ value, label }) => {
            const row = result.byStrategy?.[value];
            if (!row) return null;
            const edgeCss =
              row.edge > 0 ? "edge-buy" : row.edge < 0 ? "edge-sell" : "edge-hold";
            return (
              <tr key={value}>
                <td style={{ padding: "4px 8px" }}>{label}</td>
                <td style={{ textAlign: "right", padding: "4px 8px" }} data-numeric>
                  {formatBdvmValue(row.sideA)}
                </td>
                <td style={{ textAlign: "right", padding: "4px 8px" }} data-numeric>
                  {formatBdvmValue(row.sideB)}
                </td>
                <td style={{ textAlign: "right", padding: "4px 8px" }}>
                  <span
                    className={`edge-label ${edgeCss}`}
                    title={`${row.edgePct > 0 ? "+" : ""}${row.edgePct}%`}
                  >
                    {row.edge > 0 ? "+" : ""}
                    {formatBdvmValue(Math.abs(row.edge)) === "—"
                      ? "—"
                      : `${row.edge < 0 ? "−" : ""}${formatBdvmValue(Math.abs(row.edge))}`}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {unresolved.length > 0 ? (
        <p className="muted" style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-2xs)" }}>
          Not priced by the fundamental board: {unresolved.join(", ")}
        </p>
      ) : null}
      <p className="muted" style={{ margin: "var(--space-2) 0 0", fontSize: "var(--font-size-2xs)" }}>
        A trade can be right in one strategy currency and wrong in another — a
        contender and a rebuilder value the same package differently by design.
      </p>
    </Panel>
  );
}
