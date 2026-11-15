"use client";

/**
 * TradeTargetsCard — /rosters' "Trade Targets", rendered from the canonical
 * need answer.
 *
 * WHICH positions are needs, how urgent, and which positions are strongest
 * all come from `GET /api/roster/intelligence`:
 *
 *   need positions   `team.weakness` (owner `src/roster_intel/weakness.py`),
 *                    worst-first, levels verbatim
 *   other teams      `leagueContext[].needLevelByPosition` / `urgentPositions`
 *   strongest        `team.strength.byPosition[].leagueRank`
 *
 * This card used to answer all three itself: each position's raw
 * full-roster `byGroup` sum divided by the league average, "weakest" = the
 * lowest ratio. That is a second need rule (C2-WEAK-01) — it counts bench
 * depth at full market value and ignores the league's lineup, so it could
 * call a room "weak" while the lineup solve says it starts two top-12
 * players. There is no fallback to it: when the need answer is unavailable
 * the card says so and names why.
 *
 * What it still does locally is LIST players — the other teams' players at
 * a served need position, and this roster's players at its strongest served
 * positions. Listing is presentation; deciding the position is not.
 */

import { PlayerImage } from "@/components/ui";
import { PlayerNameButton } from "@/components/ds";
import { POS_GROUP_COLORS } from "@/lib/league-analysis";
import { textSafe } from "@/lib/contrast";
import { leagueNeedIndex, ownerIdForTeamName, teamNeedDetail } from "@/lib/roster-intelligence";

// Same surface + floor rules as the rest of /rosters (see page.jsx).
const PAGE_SURFACE = "#131519";
const FONT_2XS = "var(--font-size-2xs, 0.6875rem)";
const posText = (g) => (POS_GROUP_COLORS[g] ? textSafe(POS_GROUP_COLORS[g], PAGE_SURFACE) : "var(--subtext)");

// Listing window for a trade TARGET (not a need rule): skip roster filler
// below and cornerstones above, as this card always has.
const TARGET_VALUE_MIN = 1200;
const TARGET_VALUE_MAX = 8000;
const CHIP_VALUE_MIN = 1500;

const NEED_TONE = {
  critical: "var(--red, #e5484d)",
  high: "var(--red, #e5484d)",
  moderate: "var(--amber)",
};

function PlayerLine({ p, color, onPlayerClick, trailing }) {
  return (
    <div className="trade-targets-row" style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "0.72rem", minWidth: 0 }}>
      <PlayerImage playerId={p.playerId} team={p.team} position={p.pos} name={p.name} size={22} />
      <span style={{ color, fontFamily: "var(--mono)", fontWeight: 700, width: 28, flexShrink: 0, fontSize: FONT_2XS }}>
        {p.pos}
      </span>
      <PlayerNameButton name={p.name} onOpen={onPlayerClick} style={{ flex: 1, minWidth: 0, fontWeight: 600 }} />
      <span style={{ fontFamily: "var(--mono)", width: 56, flexShrink: 0, textAlign: "right" }}>
        {Number(p.meta).toLocaleString()}
      </span>
      {trailing}
    </div>
  );
}

export default function TradeTargetsCard({
  myTeam,
  myOwnerId = "",
  teams,
  sleeperTeams,
  intelligence,
  onPlayerClick,
}) {
  const myTeamData = (teams || []).find((t) => t.name === myTeam);
  if (!myTeamData) return null;

  const { loading = false, data = null, failure = null } = intelligence || {};

  let body;
  if (loading && !data) {
    body = (
      <p className="trade-targets-state" role="status" style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
        Loading need priority…
      </p>
    );
  } else if (failure) {
    body = (
      <p className="trade-targets-state trade-targets-unavailable" role="note" style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
        <strong>Need priority unavailable.</strong>{" "}
        {failure.message || "Roster intelligence could not be loaded."} Trade targets are not
        computed without it.
      </p>
    );
  } else {
    const detail = teamNeedDetail(data, { ownerId: myOwnerId });
    if (detail.state !== "ok") {
      body = (
        <p className="trade-targets-state trade-targets-unavailable" role="note" style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
          <strong>Need priority unavailable</strong> — {detail.reasonText}. Trade targets are not
          computed without it.
        </p>
      );
    } else {
      body = (
        <ServedTargets
          detail={detail}
          needIndex={leagueNeedIndex(data)}
          myTeam={myTeam}
          myTeamData={myTeamData}
          teams={teams}
          sleeperTeams={sleeperTeams}
          onPlayerClick={onPlayerClick}
        />
      );
    }
  }

  return (
    <div className="card trade-targets-card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>Trade Targets</div>
      {body}
    </div>
  );
}

function ServedTargets({ detail, needIndex, myTeam, myTeamData, teams, sleeperTeams, onPlayerClick }) {
  const topNeed = detail.needPositions[0] || null;
  const strongest = detail.strongest[0] || null;
  const needSections = detail.needPositions.slice(0, 2).map((need) => {
    const targets = [];
    for (const otherTeam of teams) {
      if (otherTeam.name === myTeam) continue;
      const theirs = needIndex.get(ownerIdForTeamName(sleeperTeams, otherTeam.name));
      // Unmeasured is skipped, never guessed: only a team the owner rates
      // as having NO need at this position is offered as a seller.
      if (!theirs?.measured) continue;
      if (theirs.needLevelByPosition[need.position] !== "none") continue;
      const theirNeed = theirs.urgentPositions[0] || "";
      for (const p of otherTeam.players || []) {
        if (p.group !== need.position) continue;
        if (!(p.meta >= TARGET_VALUE_MIN && p.meta <= TARGET_VALUE_MAX)) continue;
        targets.push({ ...p, teamName: otherTeam.name, theirNeed });
      }
    }
    targets.sort((a, b) => b.meta - a.meta);
    return { need, targets: targets.slice(0, 8) };
  });

  const chipPositions = new Set(detail.strongest.slice(0, 2).map((s) => s.position));
  const surplus = (myTeamData.players || [])
    .filter((p) => chipPositions.has(p.group) && p.meta >= CHIP_VALUE_MIN)
    .sort((a, b) => b.meta - a.meta)
    .slice(0, 6);

  return (
    <>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        {strongest ? (
          <span className="badge" style={{ background: "var(--green-soft)", color: posText(strongest.position) }}>
            Strongest: {strongest.position} ({strongest.rankLabel} in league)
          </span>
        ) : null}
        <span
          className="badge trade-targets-top-need"
          style={{ background: "var(--red-soft, rgba(220,50,50,0.1))", color: topNeed ? posText(topNeed.position) : "var(--subtext)" }}
        >
          {topNeed ? `Top need: ${topNeed.position} (${topNeed.label})` : "No starting-slot need"}
        </span>
      </div>

      {needSections.length === 0 ? (
        <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 14 }}>
          Every starting rung clears its league bar — no position is a need right now.
        </div>
      ) : null}

      {needSections.map(({ need, targets }) => (
        <div key={need.position} className="trade-targets-need" style={{ marginBottom: 14 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px" }}>
            Need: {need.position}{" "}
            <span style={{ fontWeight: 600, fontSize: "0.7rem", color: NEED_TONE[need.level] || "var(--subtext)" }}>
              {need.label}
            </span>
          </h4>
          {need.reasons[0] ? (
            <div style={{ fontSize: FONT_2XS, color: "var(--subtext)", marginBottom: 4 }}>{need.reasons[0]}</div>
          ) : null}
          {targets.length === 0 ? (
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
              No clear trade targets — no other team is measured as set at {need.position}.
            </div>
          ) : (
            targets.map((t) => (
              <PlayerLine
                key={`${t.teamName}::${t.name}`}
                p={t}
                color={posText(need.position)}
                onPlayerClick={onPlayerClick}
                trailing={
                  <span className="trade-targets-team" style={{ fontSize: "0.64rem", color: "var(--subtext)", minWidth: 0, maxWidth: 120, overflowWrap: "anywhere" }}>
                    {t.teamName}
                    {t.theirNeed ? <span style={{ color: "var(--amber)" }}> (need {t.theirNeed})</span> : null}
                  </span>
                }
              />
            ))
          )}
        </div>
      ))}

      {surplus.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px", color: "var(--green)" }}>
            Your Trade Chips{" "}
            <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--subtext)" }}>
              (from your strongest positions)
            </span>
          </h4>
          {surplus.map((p) => (
            <PlayerLine
              key={p.name}
              p={p}
              color={posText(p.group)}
              onPlayerClick={onPlayerClick}
              trailing={<span style={{ fontSize: "0.64rem", color: "var(--green)", flexShrink: 0 }}>your roster</span>}
            />
          ))}
        </div>
      )}
    </>
  );
}
