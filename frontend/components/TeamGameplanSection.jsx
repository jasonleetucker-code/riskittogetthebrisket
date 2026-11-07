"use client";

/**
 * TeamGameplanSection — /rosters' on-demand "Team Gameplan" for the SELECTED
 * team (owner decision 2026-11-07, W20-F001).
 *
 * Collapsed by default and requests NOTHING until the user expands it: the
 * payload is large and per-team, so there is no prefetch for any team.  Every
 * label comes from `GET /api/gameplan` through `lib/gameplan-view.js`; this
 * component decides nothing (no posture, no team score, no ranking).
 */

import { useId, useState } from "react";
import { Panel } from "@/components/ds/Panel";
import { FailureState } from "@/components/ds/FailureState";
import { useHydrated } from "@/components/ds/useHydrated";
import { EmptyState, LoadingState } from "@/components/ui";
import { useJsonEndpoint } from "@/components/useJsonEndpoint";
import { classifyContractFailure } from "@/lib/contract-failure";
import { gameplanView } from "@/lib/gameplan-view";

// Module-level on purpose: `classify` is an effect dependency of the hook.
const classifyGameplanFailure = (status, body) =>
  status >= 200 && status < 300 ? null : classifyContractFailure(status, body);

const FONT_2XS = "var(--font-size-2xs, 0.6875rem)";
const subtle = { fontSize: FONT_2XS, color: "var(--subtext)", lineHeight: 1.5 };
const rowLabel = { fontWeight: 700, fontSize: "0.72rem", margin: "12px 0 4px" };

function Unavailable({ what, reasonText }) {
  return (
    <p style={subtle}>
      {what}: not available ({reasonText}).
    </p>
  );
}

function Body({ view }) {
  const { posture, window: win, needs, strengths, opportunities } = view;
  return (
    <div className="team-gameplan-body">
      <h3 style={rowLabel}>Direction</h3>
      {posture.state === "ok" ? (
        <p style={{ margin: 0, fontSize: "0.8rem" }}>
          <strong>{posture.text}</strong>
          {posture.confidencePct !== null ? ` · ${posture.confidencePct}% leaning` : ""}
          <span style={subtle}>
            {" "}
            {posture.measured
              ? "Directional estimate, not a verdict."
              : "Not enough competitiveness evidence to lean either way."}
          </span>
        </p>
      ) : (
        <Unavailable what="Posture" reasonText={posture.reasonText} />
      )}
      {win.state === "ok" ? (
        <p style={{ ...subtle, margin: "4px 0 0" }}>
          Competitive window: closest match is <strong>{win.text}</strong>.
        </p>
      ) : (
        <Unavailable what="Competitive window" reasonText={win.reasonText} />
      )}

      <h3 style={rowLabel}>Strengths</h3>
      {strengths.state !== "ok" ? (
        <Unavailable what="Strengths" reasonText={strengths.reasonText} />
      ) : strengths.items.length === 0 ? (
        <p style={subtle}>No position currently carries tradeable surplus depth.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.75rem" }}>
          {strengths.items.map((s) => (
            <li key={s.position}>
              <strong>{s.position}</strong> surplus depth
              {s.surplusPlayers.length ? ` — ${s.surplusPlayers.join(", ")}` : ""}
            </li>
          ))}
        </ul>
      )}

      <h3 style={rowLabel}>Weaknesses</h3>
      {needs.state !== "ok" ? (
        <Unavailable what="Weaknesses" reasonText={needs.reasonText} />
      ) : needs.needPositions.length === 0 ? (
        <p style={subtle}>No position is flagged as a need.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.75rem" }}>
          {needs.needPositions.map((n) => (
            <li key={n.position}>
              <strong>{n.position}</strong> — {n.label}
              {needs.urgentPositions?.includes(n.position) ? " (urgent)" : ""}
            </li>
          ))}
        </ul>
      )}

      <h3 style={rowLabel}>Strategic opportunities</h3>
      {opportunities.state !== "ok" ? (
        <Unavailable what="Opportunities" reasonText={opportunities.reasonText} />
      ) : (
        <>
          {opportunities.positions.length === 0 ? (
            <p style={subtle}>No position currently has a viable upgrade target.</p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: 18, fontSize: "0.75rem" }}>
              {opportunities.positions.map((o) => (
                <li key={o.position}>
                  <strong>{o.position}</strong> upgrade is obtainable
                </li>
              ))}
            </ul>
          )}
          {opportunities.players.length > 0 && (
            <p style={{ ...subtle, margin: "6px 0 0" }}>
              Recommended targets:{" "}
              {opportunities.players.map((p) => `${p.name} (${p.position})`).join(", ")}
            </p>
          )}
          {opportunities.notMeasured.length > 0 && (
            <p style={{ ...subtle, margin: "6px 0 0" }}>
              Not measured: {opportunities.notMeasured.join(", ")} (no acquirable
              candidates were supplied &mdash; that is not the same as nothing being
              available).
            </p>
          )}
        </>
      )}

      {view.asOf && <p style={{ ...subtle, marginTop: 12 }}>As of {view.asOf}.</p>}
    </div>
  );
}

export default function TeamGameplanSection({ ownerId = "", teamName = "" }) {
  const [open, setOpen] = useState(false);
  const bodyId = useId();
  const hydrated = useHydrated();
  // `enabled` is the only thing that triggers a request: nothing is fetched
  // until the user expands, and a team switch while folded fetches nothing.
  const enabled = open && Boolean(ownerId);
  const { loading, data, failure, refetch } = useJsonEndpoint("/api/gameplan", {
    params: { team: ownerId },
    enabled,
    classify: classifyGameplanFailure,
  });

  let content = null;
  if (open) {
    if (!ownerId) {
      content = (
        <EmptyState
          title="Choose a team"
          message="Pick a team in “My team…” above to see its gameplan."
        />
      );
    } else if (failure) {
      content = <FailureState failure={failure} onRetry={refetch} variant="block" context="Team Gameplan" />;
    } else {
      const view = data ? gameplanView(data, { ownerId }) : null;
      if (loading || !view || view.state !== "ok") {
        content =
          view && view.state === "unavailable" && !loading ? (
            <EmptyState title="Team Gameplan not available" message={view.reasonText} />
          ) : (
            <LoadingState message="Building the gameplan..." />
          );
      } else {
        content = <Body view={view} />;
      }
    }
  }

  return (
    <div style={{ marginTop: "var(--space-md)" }} className="team-gameplan-section">
      <Panel
        title="Team Gameplan"
        subtitle={teamName ? `Direction, strengths, weaknesses and opportunities for ${teamName}.` : undefined}
        collapsible
        collapsed={!open}
        onToggleCollapsed={() => setOpen((v) => !v)}
        disclosurePending={!hydrated}
        bodyId={bodyId}
      >
        {content}
      </Panel>
    </div>
  );
}
