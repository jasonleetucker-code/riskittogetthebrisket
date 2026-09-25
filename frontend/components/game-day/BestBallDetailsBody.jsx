/**
 * BestBallDetailsBody — the content of Game Day section 4 (the collapsed
 * "Best-ball details" panel). Loaded on first open (see BestBallDetails.jsx).
 *
 * Three lineup quantities, kept apart exactly as the backend keeps them:
 *   Currently counting   side.actualLineup — the CURRENT scoring lineup over
 *                        points already scored (live/final). An all-zero
 *                        pregame roster is never shown as a lineup:
 *                        lineupState "not_started" renders a sentence.
 *   Projected lineup     side.expectedLineup — ILLUSTRATIVE (basis
 *                        optimized_individual_means), pregame only, and
 *                        labelled as not the projected finish.
 *   Final-lineup chance  side.players[].finalLineupPct — share of simulation
 *                        draws in which the player is in the FINAL optimized
 *                        lineup ("Could enter", "Game finished").
 *
 * No slot-eligibility arrays: slots are named once, in the lineup table.
 */

import { DataTable } from "@/components/ds";
import {
  couldEnterPlayers,
  finishedPlayers,
  formatLineupPct,
  formatPoints,
  playerStateText,
  positionLabel,
  slotLabel,
} from "@/lib/game-day-view";
import styles from "./game-day.module.css";

function nameFor(side, playerId) {
  return (side?.players || []).find((p) => p.playerId === playerId)?.name || playerId;
}

function pctByPlayer(side) {
  const out = new Map();
  for (const p of side?.players || []) out.set(p.playerId, p.finalLineupPct);
  return out;
}

function CurrentLineup({ side, mode }) {
  const lineup = side?.actualLineup;
  const title = mode === "final" ? "Final lineup" : "Currently counting";
  if (!lineup) {
    return (
      <div>
        <h4 className={styles.subTitle}>{title}</h4>
        <p className={styles.note}>No scoring lineup was published for this team.</p>
      </div>
    );
  }
  const unknown = (side?.players || []).filter((p) => p.state === "unknown");
  const unknownNote = unknown.length ? (
    <p className={styles.note}>
      Game status unknown for {unknown.map((p) => p.name).join(", ")} — the live feed could not see
      their game{unknown.length === 1 ? "" : "s"}, so {unknown.length === 1 ? "he is" : "they are"}{" "}
      not seated here even if Sleeper shows points.
    </p>
  ) : null;
  if (lineup.lineupState === "not_started") {
    return (
      <div>
        <h4 className={styles.subTitle}>{title}</h4>
        {unknownNote || (
          <p className={styles.note}>No one on this roster has played yet, so no lineup is counting.</p>
        )}
      </div>
    );
  }
  const pct = pctByPlayer(side);
  const columns = [
    { key: "slot", header: "Slot", render: (s) => slotLabel(s.slot) },
    { key: "name", header: "Player", render: (s) => s.name },
    {
      key: "points",
      header: "Points",
      numeric: true,
      render: (s) => formatPoints(s.points) ?? "Unavailable",
    },
  ];
  if (mode === "live") {
    columns.push({
      key: "stay",
      header: "Stays in",
      numeric: true,
      headerInfo: "Chance this player is still in the final best-ball lineup once every game ends.",
      headerInfoLabel: "Stays in final lineup",
      render: (s) => formatLineupPct(pct.get(s.playerId)) ?? "—",
    });
  }
  const total = formatPoints(lineup.total);
  const missing = lineup.missingPlayerIds || [];
  return (
    <div>
      <h4 className={styles.subTitle}>{title}</h4>
      <DataTable
        caption={`${side.displayName}: ${title.toLowerCase()}`}
        columns={columns}
        rows={lineup.slots || []}
        rowKey={(s) => `${s.slotIndex}-${s.playerId}`}
        density="compact"
      />
      <p className={styles.note}>
        {total !== null
          ? `Counting total ${total}`
          : `Known subtotal ${formatPoints(lineup.knownSubtotal) ?? "unavailable"} — scoring missing for ${missing.length} player${missing.length === 1 ? "" : "s"}`}
        {lineup.notStartedPlayerIds?.length
          ? ` · ${lineup.notStartedPlayerIds.length} yet to play`
          : ""}
      </p>
      {unknownNote}
    </div>
  );
}

function ProjectedLineup({ side }) {
  const lineup = side?.expectedLineup;
  if (!lineup?.slots?.length) {
    return (
      <div>
        <h4 className={styles.subTitle}>Projected lineup</h4>
        <p className={styles.note}>
          No projection covered enough of this roster to fill the starting slots.
        </p>
      </div>
    );
  }
  const columns = [
    { key: "slot", header: "Slot", render: (s) => slotLabel(s.slot) },
    { key: "name", header: "Player", render: (s) => s.name },
    {
      key: "proj",
      header: "Proj",
      numeric: true,
      render: (s) => formatPoints(s.projectedPoints) ?? "—",
    },
  ];
  const unpriced = lineup.unpricedPlayerIds || [];
  return (
    <div>
      <h4 className={styles.subTitle}>Projected lineup (illustrative)</h4>
      <DataTable
        caption={`${side.displayName}: illustrative projected lineup`}
        columns={columns}
        rows={lineup.slots}
        rowKey={(s) => `${s.slotIndex}-${s.playerId}`}
        density="compact"
      />
      <p className={styles.note}>
        The best lineup from each player&apos;s average projection. Projected finish averages the
        best lineup across every simulated week, so the two totals differ.
        {unpriced.length
          ? ` ${unpriced.length} player${unpriced.length === 1 ? " has" : "s have"} no projection and ${unpriced.length === 1 ? "is" : "are"} left out rather than counted as zero.`
          : ""}
      </p>
    </div>
  );
}

function CouldEnter({ side, mode }) {
  const rows = couldEnterPlayers(side, mode);
  if (!rows.length) return null;
  return (
    <div>
      <h4 className={styles.subTitle}>Could enter</h4>
      <DataTable
        caption={`${side.displayName}: players who could enter the final lineup`}
        columns={[
          {
            key: "name",
            header: "Player",
            render: (p) => (
              <span>
                {p.name}
                {positionLabel(p) ? <span className={styles.muted}> · {positionLabel(p)}</span> : null}
              </span>
            ),
          },
          { key: "state", header: "Status", render: (p) => playerStateText(p.state) },
          {
            key: "pct",
            header: "Final lineup",
            numeric: true,
            render: (p) => formatLineupPct(p.finalLineupPct),
          },
        ]}
        rows={rows}
        rowKey="playerId"
        density="compact"
      />
    </div>
  );
}

function GameFinished({ side, mode }) {
  if (mode !== "live") return null;
  const rows = finishedPlayers(side);
  if (!rows.length) return null;
  return (
    <div>
      <h4 className={styles.subTitle}>Game finished</h4>
      <DataTable
        caption={`${side.displayName}: players whose game is over`}
        columns={[
          { key: "name", header: "Player", render: (p) => p.name },
          {
            key: "pts",
            header: "Points",
            numeric: true,
            render: (p) => formatPoints(p.pointsScored) ?? "Unavailable",
          },
          {
            key: "pct",
            header: "Final lineup",
            numeric: true,
            render: (p) => formatLineupPct(p.finalLineupPct) ?? "—",
          },
        ]}
        rows={rows}
        rowKey="playerId"
        density="compact"
      />
      <p className={styles.note}>
        A finished player&apos;s points are locked; his place in the lineup is not — a teammate still
        to play can displace him.
      </p>
    </div>
  );
}

function Unpriced({ side }) {
  const ids = side?.unpricedPlayerIds || [];
  if (!ids.length) return null;
  return (
    <p className={styles.note}>
      No projection for {ids.length} player{ids.length === 1 ? "" : "s"} (
      {ids.map((id) => nameFor(side, id)).join(", ")}) — left out, not counted as zero.
    </p>
  );
}

function SideDetail({ side, mode, role }) {
  if (!side) return null;
  return (
    <div className={styles.sideBlock}>
      <h3 className={styles.sideBlockTitle}>
        {side.displayName} <span className={styles.muted}>· {role}</span>
      </h3>
      {mode === "pregame" ? <ProjectedLineup side={side} /> : <CurrentLineup side={side} mode={mode} />}
      {mode !== "final" ? <CouldEnter side={side} mode={mode} /> : null}
      <GameFinished side={side} mode={mode} />
      <Unpriced side={side} />
    </div>
  );
}

export default function BestBallDetailsBody({ payload }) {
  const mode = payload?.mode;
  return (
    <div className={styles.sides}>
      <SideDetail side={payload?.team} mode={mode} role="Selected team" />
      <SideDetail side={payload?.opponent} mode={mode} role="Opponent" />
    </div>
  );
}
