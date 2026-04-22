"use client";

// ArchivesSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useMemo, useState } from "react";
import Link from "next/link";
import { Card, EmptyCard, fmtNumber, fmtPoints } from "../shared.jsx";

function ArchivesSection({ data }) {
  const [kind, setKind] = useState("trades");
  const [query, setQuery] = useState("");
  const [season, setSeason] = useState("all");
  if (!data) return <EmptyCard label="Archives" />;

  const seasonsCovered = data.seasonsCovered || [];
  const rows = useMemo(() => data[kind] || [], [data, kind]);
  const filtered = useMemo(() => {
    let out = rows;
    if (season !== "all") {
      out = out.filter((r) => String(r.season || "") === season);
    }
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => archiveSearchTokens(r).includes(q));
    }
    return out.slice(0, 500);
  }, [rows, query, season]);

  return (
    <Card
      title="Public archives"
      subtitle="Full searchable history of trades, waivers, matchups, drafts, and season results"
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {ARCHIVE_KINDS.map((k) => (
          <button
            key={k.key}
            type="button"
            onClick={() => setKind(k.key)}
            style={{
              padding: "6px 10px",
              fontSize: "0.74rem",
              border: "1px solid",
              borderColor: kind === k.key ? "var(--cyan)" : "var(--border)",
              background: kind === k.key ? "rgba(255, 199, 4, 0.12)" : "transparent",
              borderRadius: 6,
              color: "var(--text)",
              cursor: "pointer",
            }}
          >
            {k.label} ({(data[k.key] || []).length})
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <input
          className="input"
          placeholder="Search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select
          className="input"
          value={season}
          onChange={(e) => setSeason(e.target.value)}
          style={{ minWidth: 140 }}
        >
          <option value="all">All seasons</option>
          {seasonsCovered.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 6 }}>
        {filtered.length} result{filtered.length === 1 ? "" : "s"}
        {rows.length > filtered.length ? ` of ${rows.length}` : ""}
      </div>

      <div className="table-wrap">
        <ArchiveTable kind={kind} rows={filtered} />
      </div>
    </Card>
  );
}

function ArchiveTable({ kind, rows }) {
  if (!rows.length) {
    return (
      <div style={{ fontSize: "0.74rem", color: "var(--subtext)", padding: 10 }}>
        No records match.
      </div>
    );
  }
  if (kind === "trades") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Teams</th>
            <th>Assets</th>
            <th>Positions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week ?? "—"}</td>
              <td>{(r.ownerIds || []).join(" ↔ ")}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.totalAssets}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.positions || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "waivers") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Type</th>
            <th>Manager</th>
            <th>Bid</th>
            <th>Added</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week ?? "—"}</td>
              <td style={{ fontFamily: "var(--mono)", fontSize: "0.7rem" }}>{r.type}</td>
              <td>{r.ownerId || "—"}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.bid ?? "—"}</td>
              <td style={{ fontSize: "0.72rem" }}>
                {(r.added || []).map((p) => `${p.playerName} (${p.position || "?"})`).join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "weeklyMatchups") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Home</th>
            <th style={{ textAlign: "right" }}>Score</th>
            <th style={{ textAlign: "right" }}>Score</th>
            <th>Away</th>
            <th>Tags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week}</td>
              <td>{r.homeOwnerId || "—"}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(r.homePoints)}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(r.awayPoints)}</td>
              <td>{r.awayOwnerId || "—"}</td>
              <td style={{ fontSize: "0.7rem" }}>{(r.tags || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "rookieDrafts") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Pick</th>
            <th>Player</th>
            <th>Pos</th>
            <th>NFL</th>
            <th>Drafted by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>
                {r.round}.{String(r.pickNo).padStart(2, "0")}
              </td>
              <td style={{ fontWeight: 600 }}>{r.playerName}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.position || ""}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.nflTeam || ""}</td>
              <td>{r.teamName}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "seasonResults") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Team</th>
            <th style={{ textAlign: "right" }}>W-L-T</th>
            <th style={{ textAlign: "right" }}>PF</th>
            <th style={{ textAlign: "right" }}>Seed</th>
            <th style={{ textAlign: "right" }}>Final</th>
            <th>Tags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontWeight: 600 }}>{r.teamName}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {r.wins}-{r.losses}{r.ties ? `-${r.ties}` : ""}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsFor, 1)}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.standing}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "—"}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.tags || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "managers") {
    return (
      <table>
        <thead>
          <tr>
            <th>Manager</th>
            <th>Current team</th>
            <th>Aliases</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 600 }}>{r.displayName}</td>
              <td>{r.currentTeamName}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.aliases || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "players") {
    return (
      <table>
        <thead>
          <tr>
            <th>Player</th>
            <th>Pos</th>
            <th style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>Player ID</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 600 }}>
                <Link
                  href={`/league/player/${encodeURIComponent(r.playerId)}`}
                  style={{ color: "var(--cyan)" }}
                >
                  {r.playerName}
                </Link>
              </td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.position || ""}</td>
              <td style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--subtext)" }}>
                {r.playerId}
              </td>
              <td style={{ textAlign: "right", fontSize: "0.7rem" }}>
                <Link
                  href={`/league/player/${encodeURIComponent(r.playerId)}`}
                  style={{ color: "var(--cyan)" }}
                >
                  Journey →
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return null;
}

function archiveSearchTokens(row) {
  const parts = [];
  for (const [, v] of Object.entries(row)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) {
      parts.push(
        v.map((x) => (typeof x === "object" && x !== null ? Object.values(x).join(" ") : x)).join(" "),
      );
    } else if (typeof v === "object") {
      parts.push(Object.values(v).join(" "));
    } else {
      parts.push(String(v));
    }
  }
  return parts.join(" ").toLowerCase();
}

const ARCHIVE_KINDS = [
  { key: "trades", label: "Trades" },
  { key: "waivers", label: "Waivers / FA" },
  { key: "weeklyMatchups", label: "Matchups" },
  { key: "rookieDrafts", label: "Rookie drafts" },
  { key: "seasonResults", label: "Season results" },
  { key: "players", label: "Players" },
  { key: "managers", label: "Managers" },
];

export default ArchivesSection;
