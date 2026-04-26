"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useUserState } from "@/components/useUserState";
import {
  POSITION_FAMILIES,
  buildValueIndex,
  totalsByFamily,
  grandTotal,
} from "@/lib/roster-compare";

function fmtValue(v) {
  if (!Number.isFinite(v)) return "—";
  return Math.round(v).toLocaleString();
}

function fmtDelta(v) {
  if (!Number.isFinite(v)) return "—";
  const n = Math.round(v);
  if (n === 0) return "·";
  return n > 0 ? `+${n.toLocaleString()}` : n.toLocaleString();
}

export default function RosterComparePanel({ ownerId }) {
  const { rows, rawData, loading } = useDynastyData();
  const { state: userState } = useUserState();
  const [open, setOpen] = useState(false);

  const myOwnerId = userState?.selectedTeam?.ownerId
    ? String(userState.selectedTeam.ownerId)
    : null;
  const sameAsSelf = myOwnerId && String(ownerId) === myOwnerId;

  const compare = useMemo(() => {
    if (!rawData?.sleeper?.teams || !Array.isArray(rawData.sleeper.teams)) return null;
    const teams = rawData.sleeper.teams;
    const themTeam = teams.find((t) => String(t?.ownerId) === String(ownerId));
    const meTeam = myOwnerId
      ? teams.find((t) => String(t?.ownerId) === myOwnerId)
      : null;
    if (!themTeam || !meTeam) return null;

    const valueIndex = buildValueIndex(rows);
    const themTotals = totalsByFamily(themTeam.players, valueIndex);
    const meTotals = totalsByFamily(meTeam.players, valueIndex);

    const themGrand = grandTotal(themTotals);
    const meGrand = grandTotal(meTotals);

    return {
      themName: themTeam.name || "Their team",
      meName: meTeam.name || "Your team",
      themTotals,
      meTotals,
      themGrand,
      meGrand,
    };
  }, [rawData, rows, ownerId, myOwnerId]);

  if (sameAsSelf) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        This is your own franchise — nothing to compare against.
      </p>
    );
  }

  if (loading) {
    return <p className="muted" style={{ fontSize: "0.72rem" }}>Loading rosters…</p>;
  }

  if (!myOwnerId) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        Pick your team on the league page to compare against this franchise.
      </p>
    );
  }

  if (!compare) {
    return (
      <p className="muted" style={{ fontSize: "0.72rem", margin: "8px 0" }}>
        Roster comparison unavailable — neither team is in the active league&apos;s Sleeper data.
      </p>
    );
  }

  if (!open) {
    return (
      <button className="button" onClick={() => setOpen(true)} style={{ fontSize: "0.78rem" }}>
        Compare to my roster
      </button>
    );
  }

  const grandDelta = compare.meGrand - compare.themGrand;
  const grandColor = grandDelta > 0 ? "var(--green)" : grandDelta < 0 ? "var(--red)" : "var(--text)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
        <strong style={{ fontSize: "0.84rem" }}>Roster comparison</strong>
        <button
          className="button"
          onClick={() => setOpen(false)}
          style={{ fontSize: "0.7rem", padding: "2px 8px" }}
        >
          Hide
        </button>
        <span className="muted" style={{ fontSize: "0.7rem" }}>
          (consensus value totals, by position family)
        </span>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Position</th>
              <th style={{ textAlign: "right" }}>{compare.meName}</th>
              <th style={{ textAlign: "right" }}>{compare.themName}</th>
              <th style={{ textAlign: "right" }}>Net (you − them)</th>
            </tr>
          </thead>
          <tbody>
            {POSITION_FAMILIES.map((f) => {
              const me = compare.meTotals[f.key];
              const them = compare.themTotals[f.key];
              if (me.count === 0 && them.count === 0) return null;
              const delta = me.total - them.total;
              const color = delta > 0 ? "var(--green)" : delta < 0 ? "var(--red)" : "var(--text)";
              return (
                <tr key={f.key}>
                  <td style={{ fontWeight: 600 }}>{f.label}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtValue(me.total)}{" "}
                    <span className="muted" style={{ fontSize: "0.66rem" }}>
                      ({me.count})
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtValue(them.total)}{" "}
                    <span className="muted" style={{ fontSize: "0.66rem" }}>
                      ({them.count})
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color }}>
                    {fmtDelta(delta)}
                  </td>
                </tr>
              );
            })}
            <tr style={{ borderTop: "2px solid var(--border)" }}>
              <td style={{ fontWeight: 700 }}>Total</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 700 }}>
                {fmtValue(compare.meGrand)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 700 }}>
                {fmtValue(compare.themGrand)}
              </td>
              <td
                style={{
                  textAlign: "right",
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  color: grandColor,
                }}
              >
                {fmtDelta(grandDelta)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p className="muted" style={{ fontSize: "0.66rem", margin: 0 }}>
        Totals sum <code>rankDerivedValue</code> across each team&apos;s current Sleeper roster.
        A positive net means your roster carries more consensus value at that position family.
      </p>
    </div>
  );
}
