"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useDynastyData } from "@/components/useDynastyData";
import { useSettings } from "@/components/useSettings";
import Panel from "./Panel";

/**
 * Scoring-fit targets — fit-positive IDPs the user doesn't own.
 *
 * Direct trade-target generator: filters the live IDP universe to
 * players where ``idpScoringFitDelta >= 1500`` AND
 * ``confidence in {high, medium}`` AND the player is NOT on the
 * user's roster.  These are the most actionable buy-low candidates
 * — the lens says "buy" AND they're still acquirable.
 *
 * Auto-hides when the global Apply Scoring Fit toggle is off.
 *
 * Read-only — clicking a row opens the player popup so the user
 * can drill into the breakdown then jump to /trade or /angle.
 */

const _MIN_DELTA = 1500;
const _MAX_DISPLAY = 12;

export default function ScoringFitTargetsPanel() {
  const { openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const { rows } = useDynastyData();
  const { settings } = useSettings();

  const targets = useMemo(() => {
    if (!Array.isArray(rows)) return [];
    const ownedSet = new Set(
      (selectedTeam?.players || []).map((n) => String(n).trim().toLowerCase())
    );
    const out = [];
    for (const r of rows) {
      if (r.assetClass !== "idp") continue;
      const delta = Number(r.idpScoringFitDelta);
      if (!Number.isFinite(delta) || delta < _MIN_DELTA) continue;
      const conf = r.idpScoringFitConfidence;
      if (conf !== "high" && conf !== "medium") continue;
      const nameKey = String(r.name || "").trim().toLowerCase();
      if (ownedSet.has(nameKey)) continue;
      out.push(r);
    }
    out.sort((a, b) =>
      (Number(b.idpScoringFitDelta) || 0) - (Number(a.idpScoringFitDelta) || 0)
    );
    return out.slice(0, _MAX_DISPLAY);
  }, [rows, selectedTeam?.players]);

  if (!settings?.applyScoringFit) return null;

  return (
    <Panel
      title="Scoring-fit targets"
      subtitle="Fit-positive IDPs not on your roster · acquirable buy-lows"
      actions={
        targets.length > 0 ? (
          <span className="muted" style={{ fontSize: "0.68rem" }}>
            {targets.length} target{targets.length === 1 ? "" : "s"}
          </span>
        ) : null
      }
    >
      {targets.length === 0 ? (
        <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>
          No fit-positive IDPs available — either you already own them
          or the lens hasn&apos;t found any (delta ≥ 1,500 with high/medium
          confidence).
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          {targets.map((r) => {
            const delta = Math.round(Number(r.idpScoringFitDelta) || 0);
            return (
              <div
                key={r.name}
                role="button"
                tabIndex={0}
                onClick={() => openPlayerPopup?.(r)}
                onKeyDown={(e) => { if (e.key === "Enter") openPlayerPopup?.(r); }}
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr auto auto",
                  gap: 8,
                  alignItems: "center",
                  padding: "4px 6px",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontSize: "0.78rem",
                }}
                title={`${r.name} · ${r.pos} · league overvalues consensus by +${delta.toLocaleString()}`}
              >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  <strong>{r.name}</strong>
                  <span className="muted" style={{ fontSize: "0.66rem", marginLeft: 6 }}>
                    {r.pos}
                  </span>
                </span>
                <span className="muted" style={{ fontSize: "0.68rem", fontFamily: "var(--mono, monospace)" }}>
                  {r.idpScoringFitTier ? r.idpScoringFitTier.replace(/_/g, " ") : ""}
                </span>
                <span style={{
                  fontFamily: "var(--mono, monospace)",
                  color: "var(--green, #4ade80)",
                  fontWeight: 600,
                }}>
                  +{delta.toLocaleString()}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
