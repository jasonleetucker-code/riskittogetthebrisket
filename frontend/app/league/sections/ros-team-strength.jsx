"use client";

// ROS Roster Strength section — first surface of the new ROS engine.
// Reads /api/public/league/rosTeamStrength (the public-contract lazy
// section that wraps the cached ROS team-strength snapshot) and
// renders one row per team with the composite score + lineup vs
// depth split + a "why" expandable.  /league is a PUBLIC route, so
// hitting the private /api/ros/team-strength endpoint here would
// 401 unauthenticated visitors; the public-contract path serves the
// same shape via the public allowlist.

import { useEffect, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";
import { FailureState } from "@/components/ds";
import { classifyContractFailure } from "@/lib/contract-failure";
import { EmptyCard } from "../shared.jsx";
import { Card } from "../shared-server.jsx";

// Module-level cache so tab-switching doesn't re-fetch on every mount.
// Same pattern + 30-min TTL that the other ROS sections use.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, failure: null, inflight: null, fetchedAt: 0 };

// Where an anonymous visitor is sent to sign in, and where they land after.
export const ROS_TEAM_STRENGTH_LOGIN_HREF = `/login?next=${encodeURIComponent(
  "/league?tab=rosTeamStrength",
)}`;

// 401 = signed out; 403 = signed in but not permitted.  This section is a
// PRIVATE section (src/public_league/public_contract.py
// PRIVATE_INTELLIGENCE_SECTIONS), so an anonymous 401 is the expected
// answer, not a fault and never a reason to keep spinning.
export function isAuthFailure(failure) {
  return failure?.kind === "auth" || failure?.kind === "forbidden";
}

export function _resetRosTeamStrengthCache() {
  _cache.data = null;
  _cache.failure = null;
  _cache.inflight = null;
  _cache.fetchedAt = 0;
}

async function _fetchRosTeamStrength({ force = false } = {}) {
  const fresh = !force && _cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _cache.data, failure: null };
  if (_cache.inflight) return _cache.inflight;

  const promise = fetch("/api/public/league/rosTeamStrength")
    .then(async (r) => {
      let body = null;
      try {
        body = await r.json();
      } catch {
        body = null;
      }
      if (!r.ok) return { failure: classifyContractFailure(r.status, body) };
      return { payload: body };
    })
    .catch(() => ({ failure: classifyContractFailure(null, null) }))
    .then((result) => {
      _cache.inflight = null;
      if (result.failure) {
        _cache.data = null;
        _cache.failure = result.failure;
        return { data: null, failure: result.failure };
      }
      const body = result.payload?.data || result.payload?.section || result.payload;
      _cache.data = body;
      _cache.failure = null;
      _cache.fetchedAt = Date.now();
      return { data: body, failure: null };
    });

  _cache.inflight = promise;
  return promise;
}

function fmtScore(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Math.round(Number(v)).toString();
}

function fmtConfidence(v) {
  if (v == null) return "—";
  return `${Math.round(Number(v) * 100)}%`;
}

function TeamRow({ team, expanded, onToggle }) {
  const composite = fmtScore(team.teamRosStrength);
  const starting = fmtScore(team.startingLineupScore);
  const depth = fmtScore(team.benchDepthScore);
  return (
    <>
      <tr
        onClick={onToggle}
        style={{ cursor: "pointer" }}
        title="Click to see starting lineup + depth breakdown"
      >
        <td style={{ textAlign: "right", paddingRight: 8, color: "var(--subtext)" }}>
          {team.rank}
        </td>
        <td style={{ fontWeight: 600 }}>{team.teamName || "—"}</td>
        <td
          style={{
            textAlign: "right",
            fontFamily: "var(--mono)",
            fontWeight: 700,
            color: "var(--cyan)",
          }}
        >
          {composite}
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{starting}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{depth}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
          {team.unmappedPlayerCount > 0 ? `${team.unmappedPlayerCount}` : "0"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} style={{ background: "rgba(255,255,255,0.02)", padding: "8px 12px" }}>
            <div style={{ fontSize: "0.74rem" }}>
              <div style={{ marginBottom: 4 }}>
                <strong>Starting lineup ({fmtScore(team.startingLineupScore)}):</strong>{" "}
                {(team.startingLineup || []).map((row, i) => (
                  <span key={i} style={{ marginRight: 12 }}>
                    {row.slot}: {row.canonicalName} ({row.position}, {fmtScore(row.rosValue)})
                  </span>
                ))}
              </div>
              <div style={{ marginBottom: 4 }}>
                <strong>Bench depth ({fmtScore(team.benchDepthScore)}):</strong>{" "}
                {(team.benchDepth || []).map((row, i) => (
                  <span key={i} style={{ marginRight: 12 }}>
                    {row.canonicalName} ({row.position}, {fmtScore(row.depthContribution)})
                  </span>
                ))}
              </div>
              {team.unmappedPlayers && team.unmappedPlayers.length > 0 && (
                <div style={{ marginTop: 4, color: "var(--subtext)" }}>
                  Unmapped (no ROS read): {team.unmappedPlayers.join(", ")}
                  {team.unmappedPlayerCount > team.unmappedPlayers.length
                    ? ` … +${team.unmappedPlayerCount - team.unmappedPlayers.length} more`
                    : ""}
                </div>
              )}
              <div
                style={{
                  marginTop: 8,
                  fontSize: "0.68rem",
                  color: "var(--subtext)",
                }}
              >
                Composite ={" "}
                {Math.round((team.weights?.starting ?? 0.72) * 100)}% starting +{" "}
                {Math.round((team.weights?.depth ?? 0.18) * 100)}% best-ball depth +{" "}
                {Math.round((team.weights?.coverage ?? 0.05) * 100)}% positional coverage +{" "}
                {Math.round((team.weights?.health ?? 0.05) * 100)}% health/availability.
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function RosTeamStrengthSection() {
  const [data, setData] = useState(() => _cache.data);
  const [failure, setFailure] = useState(_cache.failure);
  const [loading, setLoading] = useState(!_cache.data && !_cache.failure);
  const [expanded, setExpanded] = useState(null);

  const load = (opts) => {
    setLoading(true);
    return _fetchRosTeamStrength(opts).then(({ data: d, failure: f }) => {
      setData(d);
      setFailure(f);
      setLoading(false);
    });
  };

  useEffect(() => {
    let active = true;
    _fetchRosTeamStrength().then(({ data: d, failure: f }) => {
      if (!active) return;
      setData(d);
      setFailure(f);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  if (loading && !data) return <LoadingState message="Loading ROS roster strength..." />;
  if (failure && !data) {
    if (isAuthFailure(failure)) {
      return (
        <Card>
          <div role="status" data-testid="ros-team-strength-auth-required">
            <EmptyState
              title="Team Strength is available to signed-in league members"
              message="This view breaks down each roster's lineup and depth, so it is not shown publicly."
            />
            <p style={{ textAlign: "center", marginTop: 8 }}>
              <a href={ROS_TEAM_STRENGTH_LOGIN_HREF}>Sign in to view Team Strength</a>
            </p>
          </div>
        </Card>
      );
    }
    return (
      <Card>
        <FailureState
          failure={failure}
          context="ROS roster strength"
          onRetry={() => load({ force: true })}
        />
      </Card>
    );
  }
  if (!data) return <EmptyCard label="ROS roster strength" />;
  const teams = Array.isArray(data.teams) ? data.teams : [];
  if (teams.length === 0) {
    return (
      <Card>
        <EmptyState
          title="ROS data not ready"
          message="The ROS pipeline hasn't produced a team-strength snapshot yet. The next scheduled scrape will populate it; admins can also POST /api/ros/refresh."
        />
      </Card>
    );
  }

  return (
    <Card title="ROS Roster Strength">
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
        Composite team strength for the rest of the season. 72% starting lineup + 18%
        best-ball depth + 5% positional coverage + 5% health. Read-only contender layer
        — does not affect dynasty values or trade math.
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
        <thead>
          <tr style={{ color: "var(--subtext)", fontSize: "0.7rem", textTransform: "uppercase" }}>
            <th style={{ textAlign: "right", padding: "4px 8px 4px 0" }}>#</th>
            <th style={{ textAlign: "left", padding: "4px 0" }}>Team</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Strength</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Starters</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Depth</th>
            <th style={{ textAlign: "right", padding: "4px 0" }}>Unmapped</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((team, i) => (
            <TeamRow
              key={`${team.ownerId || team.rosterId || i}`}
              team={team}
              expanded={expanded === i}
              onToggle={() => setExpanded(expanded === i ? null : i)}
            />
          ))}
        </tbody>
      </table>
    </Card>
  );
}
