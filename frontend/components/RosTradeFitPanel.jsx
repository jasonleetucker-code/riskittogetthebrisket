"use client";

// Trade-calculator ROS Fit panel.  Read-only contextual panel that
// surfaces buyer/seller direction + per-player ROS tags for the
// players in the trade.  NEVER mutates trade math — informational
// only, gated by ``settings.showRosTradePanel``.

import { useEffect, useState } from "react";
import { buildRosIndex, rosEntryForRow, tagsForPlayer } from "@/lib/ros-index";

const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, fetchedAt: 0, inflight: null };

async function _loadDirections() {
  if (_cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS) {
    return _cache.data;
  }
  if (_cache.inflight) return _cache.inflight;
  const promise = fetch("/api/public/league/rosTradeDeadline")
    .then((r) => (r.ok ? r.json() : null))
    .then((payload) => {
      const body = payload?.data || payload?.section || payload;
      _cache.data = body || { teams: [] };
      _cache.fetchedAt = Date.now();
      _cache.inflight = null;
      return _cache.data;
    })
    .catch(() => {
      _cache.inflight = null;
      return _cache.data || { teams: [] };
    });
  _cache.inflight = promise;
  return promise;
}

const TAG_COLOR = {
  "Win-now target": "var(--cyan)",
  "Contender upgrade": "var(--cyan)",
  "Seller cash-out": "var(--amber)",
  "Rebuilder hold": "var(--green)",
  "Avoid unless contending": "var(--red)",
  "Depth spike option": "var(--subtext)",
  "Best-ball boost": "var(--cyan)",
  "IDP contender target": "var(--cyan)",
  "Injury/bye cover": "var(--subtext)",
};

const LABEL_COLOR = {
  "Strong Buyer": "var(--cyan)",
  "Buyer": "var(--green)",
  "Selective Buyer": "var(--green)",
  "Hold / Evaluate": "var(--subtext)",
  "Selective Seller": "var(--amber)",
  "Seller": "var(--red)",
  "Strong Seller / Rebuilder": "var(--red)",
};

// Pure tag classifier — mirrors src/ros/tags.py::tags_for_player so
// the trade-calc can label players without a backend round-trip per
// row.  Stays in sync via the parity test (PR-future).
export default function RosTradeFitPanel({ sides, settings }) {
  const [directions, setDirections] = useState({ teams: [] });
  const [valuesByName, setValuesByName] = useState(() => new Map());

  useEffect(() => {
    if (settings?.showRosTradePanel === false) return;
    let active = true;
    _loadDirections().then((d) => {
      if (!active || !d) return;
      setDirections(d);
    });
    fetch("/api/ros/player-values?limit=2000")
      .then((r) => (r.ok ? r.json() : null))
      .then((payload) => {
        if (!active || !payload) return;
        // Canonical name KEY, not the raw string — see lib/ros-index.js.
        // The raw join here matched almost nothing, so `tagsForPlayer`
        // saw rosValue undefined for every asset and the panel below
        // dropped itself on essentially every trade.
        setValuesByName(buildRosIndex(payload.players));
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [settings?.showRosTradePanel]);

  if (settings?.showRosTradePanel === false) return null;
  if (!sides || sides.length < 2) return null;

  // Resolve incoming + outgoing players per side -> their ROS tags.
  const enriched = sides.map((side) => {
    const assets = side.assets || [];
    const tagged = assets.map((row) => {
      const name =
        row?.canonicalName || row?.name || row?.displayName || "";
      const ros = rosEntryForRow(valuesByName, row) || {};
      const tags = tagsForPlayer({
        position: row?.pos,
        age: row?.age,
        rosValue: ros.rosValue,
        rosPercentile: ros.rosPercentile,
        rosRank: ros.rosRank,
        dynastyPercentile: row?.canonicalPercentile ?? null,
        volatilityFlag: ros.volatilityFlag,
      });
      return { name, position: row?.pos, age: row?.age, ros, tags };
    });
    return { sideLabel: side.label || "?", tagged };
  });

  // Drop the panel entirely when no asset has a ROS read AND no team
  // direction is available — nothing useful to show.
  const hasAnyTags = enriched.some((s) => s.tagged.some((p) => p.tags.length));
  const hasDirections = (directions?.teams || []).length > 0;
  if (!hasAnyTags && !hasDirections) return null;

  return (
    <div
      className="card"
      style={{
        marginTop: 14,
        padding: "10px 14px",
        background: "rgba(79, 155, 236, 0.04)",
        border: "1px solid rgba(79, 155, 236, 0.15)",
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 4, fontSize: "0.84rem" }}>
        ROS Fit
      </div>
      <div
        style={{
          fontSize: "0.7rem",
          color: "var(--subtext)",
          marginBottom: 8,
        }}
      >
        Informational short-term context.  Does NOT change the trade math
        above — your dynasty value calculation is unaffected.
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: enriched.length === 2 ? "1fr 1fr" : "1fr",
          gap: 12,
        }}
      >
        {enriched.map((side, i) => (
          <div key={i}>
            <div style={{ fontWeight: 600, fontSize: "0.78rem", marginBottom: 4 }}>
              Side {side.sideLabel}
            </div>
            {side.tagged.length === 0 && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
                (No assets yet)
              </div>
            )}
            {side.tagged.map((p, j) => (
              <div key={j} style={{ marginBottom: 6, fontSize: "0.74rem" }}>
                <div style={{ fontWeight: 500 }}>{p.name || "—"}</div>
                {p.tags.length === 0 ? (
                  <div style={{ color: "var(--subtext)", fontSize: "0.66rem" }}>
                    No ROS tags · {p.ros?.rosValue ? `ROS value ${Math.round(p.ros.rosValue)}` : "no ROS read"}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {p.tags.map((tag) => (
                      <span
                        key={tag}
                        style={{
                          fontSize: "0.62rem",
                          padding: "1px 6px",
                          borderRadius: 4,
                          border: `1px solid ${TAG_COLOR[tag] || "var(--subtext)"}`,
                          color: TAG_COLOR[tag] || "var(--subtext)",
                        }}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
