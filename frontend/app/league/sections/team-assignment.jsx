"use client";

// TeamAssignmentSection — "Team Assignment" tab on /league.
//
// NFL TEAM AFFINITY (2026-09-01 rewrite; coverage-maximizing selection
// added same day). Renders one card per fantasy team showing:
//   * Manager display name + avatar
//   * Favorite + up to 4 NFL teams (fixed count, no percentage
//     threshold) -- chosen to correlate with the manager's own roster
//     as closely as possible while maximizing how many of the 32 real
//     NFL teams are represented leaguewide; see
//     ``_assign_coverage_maximizing_teams`` in the backend module.
//   * Each NFL team chip with logo, full name, and tag ("Favorite" /
//     "Roster-Based" / "League Coverage" with Affinity Score + Share)
//   * Optional "Show breakdown" toggle that expands a per-player
//     canonical-value breakdown per NFL team (canonical value, the
//     starting-QB multiplier when it applied, and the weighted result)
//
// This section is now PRIVATE (B8): it publishes per-manager sums and
// per-player breakdowns of canonical dynasty value — the same class of
// per-manager decomposition that made ``rosTeamStrength`` require a
// session. It self-fetches ``/api/public/league/teamAssignment`` with
// same-origin credentials (so a signed-in session's cookie rides
// along), same pattern as ``ros-team-strength.jsx``. An anonymous
// visitor gets a 401 and a plain-language explanation rather than the
// data.
//
// Backend: ``src/api/team_assignment.py``. It computes nothing this
// component re-derives — every score, share, multiplier and canonical
// value is server-stamped; this file only formats and lays them out.
//
// ─────────────────────────────────────────────────────────────────────
// COMPATIBILITY (#815, carried forward) — an empty ``assignments`` list
// is only ever a real answer when the server says the section is
// available (``available: true``). ``unavailableReason`` /
// ``rosterScoringAvailable`` / ``qbSignalAvailable`` / per-assignment
// ``rosterScored`` all distinguish "we asked and nothing qualified"
// from "we could not ask" — this file must never assert a cause it has
// not measured.
// ─────────────────────────────────────────────────────────────────────

import { useEffect, useState } from "react";
import NflTeamLogo from "@/components/ui/NflTeamLogo";
import { LoadingState } from "@/components/ui";
import { FailureState } from "@/components/ds";
import { classifyContractFailure } from "@/lib/contract-failure";
import { Avatar, EmptyCard, nameFor } from "../shared.jsx";

// Machine-readable reason (from ``src/api/team_assignment.py``) → the
// sentence a reader can act on.  Kept as a lookup so an unknown reason
// falls back to an honest generic rather than to a fabricated cause.
const UNAVAILABLE_MESSAGES = {
  no_current_season:
    "Assignment is unavailable — Sleeper has not returned a current season for this league yet. This is a data-availability state, not an empty league.",
  no_rosters:
    "Assignment is unavailable — the current season carries no rosters yet.",
};

const DEGRADED_MESSAGES = {
  canonical_contract_unavailable:
    "Roster-based affinity is unavailable — the canonical player-value board is not loaded for this league right now. Favorite teams are still shown below.",
  qb_starter_signal_unavailable:
    "NFL starting-quarterback status is unavailable right now, so the starting-QB multiplier is not being applied to any player.",
};

const ROSTER_UNAVAILABLE_MESSAGES = {
  canonical_contract_unavailable:
    "Roster-based affinity unavailable — the canonical player-value board is not loaded. Only a configured favorite can be shown.",
  team_not_in_contract_pool:
    "Roster-based affinity unavailable for this team specifically — its roster could not be matched to the canonical board. Other managers may still be scored normally.",
};

const MULTIPLIER_LABELS = {
  nfl_starting_qb: "NFL starting-QB multiplier",
  qb_not_starting: "Not his NFL team's starting QB",
  starter_status_unknown: "Starter status unknown",
  not_qb: null, // no second line — canonical value alone explains it
};

// Module-level cache so tab-switching doesn't re-fetch on every mount.
// Same pattern the other private/self-fetching /league sections use
// (see ros-team-strength.jsx), except the failure half goes through
// ``classifyContractFailure`` + ``FailureState`` instead of a bare
// message string — a 401 ("sign in required") and a 503 ("degraded")
// are different situations that want different UI, not one generic
// error sentence.  See ``lib/contract-failure.js`` / ``components/ds/
// FailureState.jsx`` for why: a failure rendered through the EMPTY
// primitive tells a screen reader "there is nothing here" instead of
// "we could not find out", and offers no retry.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, failure: null, inflight: null, fetchedAt: 0 };

async function _fetchTeamAssignment({ force = false } = {}) {
  const fresh = !force && _cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _cache.data, failure: null };
  if (_cache.inflight) return _cache.inflight;

  const promise = fetch("/api/public/league/teamAssignment")
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

function fmtValue(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Math.round(Number(v)).toLocaleString();
}

function fmtShare(v) {
  if (v == null || !Number.isFinite(Number(v))) return null;
  return `${(Number(v) * 100).toFixed(1)}%`;
}

// assignmentReason (from src/api/team_assignment.py) -> [label, color].
// "coverage_repair" gets its own color/label so a team assigned to
// maximize leaguewide NFL-team coverage never reads identically to one
// that was simply this manager's own highest-affinity pick.
const REASON_TAG = {
  favorite: ["Favorite", "var(--cyan)"],
  top_affinity: ["Roster-Based", "var(--green)"],
  coverage_repair: ["League Coverage", "var(--amber)"],
};

function NflTeamChip({ team }) {
  const share = fmtShare(team.affinityShare);
  const [label, color] = REASON_TAG[team.assignmentReason] || [
    team.isFavorite ? "Favorite" : "Roster-Based",
    team.isFavorite ? "var(--cyan)" : "var(--green)",
  ];
  return (
    <div
      className="card"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 12px",
        marginBottom: 6,
        borderLeft: `3px solid ${color}`,
      }}
    >
      <NflTeamLogo team={team.abbr} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: "0.92rem" }}>
          {team.display}
        </div>
        <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
          <span
            style={{
              color,
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
            }}
          >
            {label}
          </span>
          <span style={{ marginLeft: 8, fontFamily: "var(--mono)" }}>
            Affinity: {fmtValue(team.affinityScore)}
            {share ? ` · ${share}` : ""}
          </span>
        </div>
      </div>
    </div>
  );
}

function AffinityBreakdown({ team }) {
  const contributors = Array.isArray(team.contributors) ? team.contributors : [];
  if (!contributors.length) {
    return (
      <div
        className="muted"
        style={{ fontSize: "0.74rem", padding: "6px 10px" }}
      >
        No roster contribution.
      </div>
    );
  }
  // Sort by weighted contribution desc so the biggest signals show first.
  const sorted = [...contributors].sort(
    (a, b) => (Number(b.weightedValue) || 0) - (Number(a.weightedValue) || 0),
  );
  const share = fmtShare(team.affinityShare);
  return (
    <div
      style={{
        padding: "8px 12px 4px 40px",
        borderLeft: "1px dashed var(--border)",
        marginLeft: 14,
        marginBottom: 8,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          fontSize: "0.74rem",
          color: "var(--subtext)",
          marginBottom: 4,
        }}
      >
        {team.display} — {fmtValue(team.affinityScore)}
        {share ? ` · ${share}` : ""}
      </div>
      {sorted.map((c, idx) => {
        const multiplierLabel = MULTIPLIER_LABELS[c.multiplierReason];
        return (
          <div key={idx} style={{ padding: "3px 0" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: "0.74rem",
              }}
            >
              <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
                {c.canonicalName}
                {c.role === "reserve" ? (
                  <span className="muted" style={{ marginLeft: 6 }}>
                    (reserve)
                  </span>
                ) : null}
              </span>
              <span style={{ fontFamily: "var(--mono)", marginLeft: 8 }}>
                <span style={{ color: "var(--green)" }}>
                  {fmtValue(c.weightedValue)}
                </span>
              </span>
            </div>
            {multiplierLabel ? (
              <div
                className="muted"
                style={{ fontSize: "0.66rem", paddingLeft: 2 }}
              >
                {fmtValue(c.canonicalValue)} canonical value
                {c.multiplier && c.multiplier !== 1 ? ` × ${c.multiplier} ` : " "}
                {multiplierLabel}
              </div>
            ) : (
              <div className="muted" style={{ fontSize: "0.66rem", paddingLeft: 2 }}>
                {fmtValue(c.canonicalValue)} canonical value
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function ManagerCard({ assignment, managers, expanded, onToggle }) {
  const teams = Array.isArray(assignment.nflTeams) ? assignment.nflTeams : [];
  const hasContrib = teams.some(
    (t) => Array.isArray(t.contributors) && t.contributors.length,
  );
  return (
    <div
      className="card"
      style={{ marginBottom: 12, padding: "12px 14px" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 8,
        }}
      >
        <Avatar
          managers={managers}
          ownerId={assignment.ownerId}
          size={26}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: "0.96rem" }}>
            {nameFor(managers, assignment.ownerId) || assignment.displayName}
          </div>
          {assignment.teamName ? (
            <div
              style={{
                fontSize: "0.7rem",
                color: "var(--subtext)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {assignment.teamName}
            </div>
          ) : null}
        </div>
        {hasContrib ? (
          <button
            type="button"
            onClick={onToggle}
            className="button"
            style={{
              fontSize: "0.7rem",
              padding: "3px 8px",
            }}
            title="Toggle per-player affinity breakdown"
          >
            {expanded ? "Hide breakdown" : "Show breakdown"}
          </button>
        ) : null}
      </div>
      {assignment.rosterScored === false ? (
        <div
          className="muted"
          style={{ fontSize: "0.78rem", padding: "4px 0" }}
        >
          {ROSTER_UNAVAILABLE_MESSAGES[assignment.rosterUnavailableReason] ||
            "Roster-based assignment unavailable for this team. This is not a claim that no roster team qualified."}
        </div>
      ) : null}
      {teams.length === 0 && assignment.rosterScored !== false ? (
        <div
          className="muted"
          style={{ fontSize: "0.78rem", padding: "4px 0" }}
        >
          No NFL team assignments yet — favorite not configured and this
          manager's Meaningful Core touched no NFL team with real
          canonical value.
        </div>
      ) : (
        teams.map((t) => (
          <div key={t.abbr}>
            <NflTeamChip team={t} />
            {expanded ? <AffinityBreakdown team={t} /> : null}
          </div>
        ))
      )}
      {assignment.rosterScored === true && assignment.scoringComplete === false ? (
        <div
          className="muted"
          style={{ fontSize: "0.66rem", padding: "2px 0" }}
        >
          Partial roster read
          {assignment.unpricedCount ? ` — ${assignment.unpricedCount} unpriced player(s)` : ""}
          {assignment.unresolvedNflTeamCount
            ? `${assignment.unpricedCount ? "," : " —"} ${assignment.unresolvedNflTeamCount} player(s) with an unresolved NFL team`
            : ""}
          .
        </div>
      ) : null}
    </div>
  );
}

export default function TeamAssignmentSection({ managers }) {
  const [data, setData] = useState(() => _cache.data);
  const [failure, setFailure] = useState(_cache.failure);
  const [loading, setLoading] = useState(!_cache.data && !_cache.failure);
  const [expandedOwner, setExpandedOwner] = useState(null);

  const load = (opts) => {
    setLoading(true);
    _fetchTeamAssignment(opts).then(({ data: d, failure: f }) => {
      setData(d);
      setFailure(f);
      setLoading(false);
    });
  };

  useEffect(() => {
    let active = true;
    _fetchTeamAssignment().then(({ data: d, failure: f }) => {
      if (!active) return;
      setData(d);
      setFailure(f);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

  if (loading && !data) {
    return <LoadingState message="Loading team assignment..." />;
  }

  if (failure && !data) {
    return (
      <div className="card">
        <FailureState
          failure={failure}
          context="NFL Team Affinity"
          onRetry={() => load({ force: true })}
        />
      </div>
    );
  }

  if (!data) {
    return (
      <EmptyCard
        label="Team Assignment"
        message="Section not loaded yet — refresh to retry."
      />
    );
  }

  // #815: an empty ``assignments`` list is only a real answer when the
  // server says the section is available.
  if (data.available === false) {
    return (
      <EmptyCard
        label="Team Assignment"
        message={UNAVAILABLE_MESSAGES[data.unavailableReason] ||
          "Assignment is currently unavailable. It will return once Sleeper's league data is readable again."}
      />
    );
  }

  const assignments = Array.isArray(data.assignments) ? data.assignments : [];
  if (assignments.length === 0) {
    return (
      <EmptyCard
        label="Team Assignment"
        message={
          data.available === true
            ? "No assignments yet — the current season has no rosters."
            : "Assignment status is unknown for this response. Refresh to retry."
        }
      />
    );
  }

  const qbMultiplier = data.config?.weights?.nflStartingQbMultiplier ?? 2.0;
  const degraded = Array.isArray(data.degradedReasons) ? data.degradedReasons : [];
  const coverage = data.coverageSummary;

  return (
    <div>
      <div
        style={{
          fontSize: "0.72rem",
          color: "var(--subtext)",
          marginBottom: 12,
          lineHeight: 1.5,
        }}
      >
        Each manager is mapped to a favorite (if configured, from{" "}
        <code style={{ fontSize: "0.7rem" }}>config/team_assignment.json</code>
        ) plus up to 4 more NFL teams by NFL Team Affinity, ranked by the
        value of this team's canonical Meaningful Core players rostered
        from that NFL franchise (the same player population and
        canonical values Team Strength uses), with a {qbMultiplier}x
        weight for a player who is that NFL team's current starting
        quarterback. There is no percentage threshold — the 4 non-favorite
        teams are chosen to track each manager's own affinity as closely
        as possible while maximizing how many of the league's real NFL
        teams end up represented by someone (tagged{" "}
        <strong>League Coverage</strong> when a team is included for that
        reason rather than being this manager's own top pick). Click
        &quot;Show breakdown&quot; on any manager to see per-player value
        contributions.
        {coverage ? (
          <>
            {" "}
            {coverage.coveredTeams} of {coverage.totalNflTeams} NFL teams are
            represented across the league this week.
          </>
        ) : null}
      </div>

      {degraded.map((reason) =>
        DEGRADED_MESSAGES[reason] ? (
          <div
            key={reason}
            className="muted"
            style={{
              fontSize: "0.74rem",
              padding: "6px 10px",
              marginBottom: 10,
              border: "1px solid var(--border)",
              borderRadius: 6,
            }}
          >
            {DEGRADED_MESSAGES[reason]}
          </div>
        ) : null,
      )}

      {assignments.map((a) => (
        <ManagerCard
          key={a.ownerId}
          assignment={a}
          managers={managers}
          expanded={expandedOwner === a.ownerId}
          onToggle={() =>
            setExpandedOwner(expandedOwner === a.ownerId ? null : a.ownerId)
          }
        />
      ))}
    </div>
  );
}
