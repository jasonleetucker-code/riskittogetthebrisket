"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { PageHeader, LoadingState, EmptyState, PlayerImage } from "@/components/ui";
import { FailureState } from "@/components/ds";
import { InfoTip, PlayerNameButton } from "@/components/ds";
import { ValueBasisNote } from "@/components/ds";
import {
  POS_GROUPS,
  OFFENSE_GROUPS,
  POS_GROUP_COLORS,
  POS_GROUP_LABELS,
  buildPlayerMetaMap,
  buildAllTeamSummaries,
  computeGroupAverages,
  findWaiverWireGems,
  buildLeagueEdgeMap,
  ordinal,
} from "@/lib/league-analysis";
import { readableTextOn, textSafe } from "@/lib/contrast";

// The surface these labels sit on.  `--card` / `--bg-soft` (#131519),
// NOT the page `--bg` (#0b0d10): the labels live inside panels, and
// panels are one step LIGHTER, so computing against the page would
// clear the floor on paper and miss it on screen — which is exactly
// what the first pass did, leaving LB at 4.36:1.  Passed explicitly
// rather than sniffed from the DOM so the value is identical on the
// server render and in the test that asserts it.
const PAGE_SURFACE = "#131519";
// Mark colours are chosen to be legible as SWATCHES (>=3:1).  Reused
// as words they fell short — DL at 3.91:1, LB at 3.11:1 — so the
// text variant is derived once here.  Six of the eight are returned
// unchanged; this is a floor, not a restyle.
const POS_TEXT_COLORS = Object.fromEntries(
  Object.entries(POS_GROUP_COLORS).map(([g, c]) => [g, textSafe(c, PAGE_SURFACE)]),
);
// V1-109 / W26-F017: /rosters shipped micro-type down to 9.0px at
// 390x844 — the smallest type of any route in the mobile audit. Every
// inline size that sat below the design-system floor now rides the token
// (docs/DESIGN-SYSTEM.md: "no micro-type below --font-size-2xs" = 11px).
// Pinned by tests/e2e/specs/mobile-type-floor.spec.js.
const FONT_2XS = "var(--font-size-2xs, 0.6875rem)";
import AgeCurveOverlay from "@/components/graphs/AgeCurveOverlay";
import TeamStrengthCard from "@/components/TeamStrengthCard";
import { useRosterIntelligence } from "@/components/useRosterIntelligence";
import { ownerIdForTeamName } from "@/lib/roster-intelligence";
import "./rosters.css";

/**
 * WHICH ASSETS to count in a team total — NOT which valuation to use.
 *
 * Renamed off `VALUE_MODES` / `valueMode` deliberately. `lib/trade-logic.js`
 * exports a DIFFERENT `VALUE_MODES` (`full` | `raw`) meaning which value
 * NUMBER to read, and this file previously shadowed that export with a
 * local const of the same name and incompatible semantics. Both use the
 * key `"full"`, so the collision is silent: swap one for the other and it
 * runs, type-checks, and produces plausible-but-wrong totals.
 *
 * Concretely, the "obvious consolidation" — importing the canonical
 * VALUE_MODES here — renders an "Our Value / Raw" dropdown wired into an
 * asset-scope branch, where `raw` is neither `"full"` nor `"starters"` and
 * so silently falls through to "all players, no picks". No error, wrong
 * numbers, on the page that ranks all 12 teams.
 *
 * Keep these names distinct.
 */
const ASSET_SCOPES = [
  { key: "full", label: "Players + Picks" },
  { key: "players", label: "Players only" },
  { key: "starters", label: "Starters only" },
];

export default function RostersPage() {
  const { rows, rawData, loading, error, failure, retry, openPlayerPopup } =
    useApp();
  const { settings, update } = useSettings();
  const [assetScope, setAssetScope] = useState("full");
  const [activeGroups, setActiveGroups] = useState(new Set(POS_GROUPS));

  const sleeperTeams = rawData?.sleeper?.teams || [];
  const pickAliases = rawData?.pickAliases || null;
  const myTeam = settings.selectedTeam || "";
  // The league's actual lineup slots, straight off the contract's
  // leagueKey-stamped sleeper block.  This is what "Starters only"
  // means — it is a per-league fact, not a constant, and the two live
  // leagues run different lineups on the same scoring profile.
  const rosterPositions = rawData?.sleeper?.rosterPositions || null;

  const playerMeta = useMemo(() => buildPlayerMetaMap(rows), [rows]);

  const teams = useMemo(
    () =>
      buildAllTeamSummaries(
        sleeperTeams,
        playerMeta,
        rows,
        assetScope,
        pickAliases,
        rosterPositions,
      ),
    [sleeperTeams, playerMeta, rows, assetScope, pickAliases, rosterPositions],
  );

  // Say so rather than guessing a lineup.  This board ranks 12 teams
  // against each other, so an invented slot table doesn't just shift
  // the totals — it reorders the leaderboard, and nothing on screen
  // would indicate the order came from a guess.
  const starterSlotsUnavailable =
    assetScope === "starters" && teams.some((t) => t.starterSlotsUnavailable);

  // Sort by active group totals
  const sortedTeams = useMemo(() => {
    return teams
      .map((t) => ({
        ...t,
        activeTotal: POS_GROUPS.reduce(
          (s, g) => s + (activeGroups.has(g) ? (t.byGroup[g] || 0) : 0),
          0,
        ),
      }))
      .sort((a, b) => b.activeTotal - a.activeTotal);
  }, [teams, activeGroups]);

  const maxActiveTotal = sortedTeams[0]?.activeTotal || 1;

  const groupAvg = useMemo(() => computeGroupAverages(teams), [teams]);

  const waiverGems = useMemo(
    () => findWaiverWireGems(rows, sleeperTeams),
    [rows, sleeperTeams],
  );

  const leagueEdge = useMemo(
    () => buildLeagueEdgeMap(rows, sleeperTeams, myTeam),
    [rows, sleeperTeams, myTeam],
  );

  // Canonical Team Strength.  Fetched, never computed: the owner is
  // `src/roster_intel/strength.py` behind `GET /api/roster/intelligence`.
  // This page used to score teams itself — 0.7 x starters + 0.2 x depth
  // - 0.1 x picks, cut into contender / mid-tier / rebuilder thirds —
  // which put a second, contradictory ranking of the same twelve teams
  // on the same screen as the portfolio table below.
  //
  // An empty ownerId is not an error: the endpoint then answers for the
  // session's own team, which is the right default for a signed-in user
  // who has not picked one.
  const myOwnerId = useMemo(
    () => ownerIdForTeamName(sleeperTeams, myTeam),
    [sleeperTeams, myTeam],
  );
  const {
    loading: strengthLoading,
    data: strengthData,
    failure: strengthFailure,
  } = useRosterIntelligence({ ownerId: myOwnerId });

  function toggleGroup(g) {
    setActiveGroups((prev) => {
      const next = new Set(prev);
      if (next.has(g)) next.delete(g);
      else next.add(g);
      return next;
    });
  }

  if (loading) return <LoadingState message="Loading roster data..." />;
  // A failure is not an absence.  `EmptyState title="Error"` told a screen
  // reader "nothing here", offered no retry, and printed the raw thrown
  // string — which since contract failures carry their body is a JSON 503
  // payload rendered into the page.  FailureState classifies instead:
  // degraded reads as degraded, 403 offers no pointless retry, and the
  // server's own message leads.
  if (error) {
    // `failure` is set alongside `error` by useDynastyData, but a caller
    // that surfaces an error string without one must not render a blank
    // card — FailureState returns null on a falsy failure. So an
    // unclassified error becomes an explicit generic one rather than
    // disappearing, which is the same missing-is-never-zero rule the
    // contract applies to values.
    const state = failure || {
      kind: "error",
      code: null,
      message: error,
      retryable: true,
    };
    return (
      <div className="card">
        <FailureState failure={state} onRetry={retry} />
      </div>
    );
  }

  if (!sleeperTeams.length) {
    return (
      <div className="card">
        <PageHeader title="Team Strength" subtitle="Team strength rankings with position breakdowns." />
        <EmptyState title="No league data" message="Load dynasty data with a Sleeper league to see roster rankings." />
      </div>
    );
  }

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Team Strength"
          subtitle="Canonical team strength, roster value portfolio, waiver wire, and trade targets."
          actions={
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select
                className="input"
                aria-label="My team"
                value={myTeam}
                onChange={(e) => update("selectedTeam", e.target.value)}
                style={{ flex: 1, minWidth: 0 }}
              >
                <option value="">My team...</option>
                {sleeperTeams.map((t) => (
                  <option key={t.name} value={t.name}>{t.name}</option>
                ))}
              </select>
              <select
                className="input"
                aria-label="Assets counted in team totals"
                value={assetScope}
                onChange={(e) => setAssetScope(e.target.value)}
                style={{ flex: 1, minWidth: 0 }}
              >
                {ASSET_SCOPES.map((m) => (
                  <option key={m.key} value={m.key}>{m.label}</option>
                ))}
              </select>
            </div>
          }
        />

        <ValueBasisNote contract={rawData} />
      </div>

      {/* Canonical Team Strength — rendered from the backend owner.
          There is no client-side fallback on failure: a fallback score
          would be a second owner that only runs when nobody is looking. */}
      <TeamStrengthCard
        loading={strengthLoading}
        data={strengthData}
        failure={strengthFailure}
      />

      {/* Roster value portfolio — its own card, BELOW Team Strength.
          The order is the argument: the canonical measurement first,
          then the portfolio that answers a different question, with the
          filters that shape it. */}
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        {/* "Starters only" needs the league's lineup-slot array, and
            there is no honest default for it: this board ranks every
            team against every other, so a guessed slot table reorders
            the leaderboard rather than merely shifting the totals.
            Say what is missing instead. */}
        {starterSlotsUnavailable && (
          <p className="ds-value-basis-note starter-slots-unavailable" role="note">
            <strong>Starter totals unavailable.</strong> This league&rsquo;s lineup
            slots aren&rsquo;t in the current data, so there is no way to say which
            players start. Switch to &ldquo;Players only&rdquo; or &ldquo;Players +
            Picks&rdquo; for a complete comparison.
          </p>
        )}

        {/* Position filter — toggle chips.  The previous 13x13 native
            checkbox + 11px label was impossible to tap on mobile.
            Render each position as a segmented toggle button so the
            entire chip is the tap target (meets 44px HIG minimum on
            mobile) and still fits on a single row on phones. */}
        <div
          className="filter-bar roster-pos-filter"
          style={{ marginBottom: 12 }}
          role="group"
          aria-label="Filter by position"
        >
          <span
            style={{
              fontWeight: 600,
              fontSize: "0.72rem",
              color: "var(--subtext)",
            }}
          >
            Positions:
          </span>
          {POS_GROUPS.map((g) => {
            const active = activeGroups.has(g);
            const color = POS_GROUP_COLORS[g];
            return (
              <button
                key={g}
                type="button"
                className={`pos-chip${active ? " pos-chip-active" : ""}`}
                onClick={() => toggleGroup(g)}
                aria-pressed={active}
                title={`Toggle ${g}`}
                style={{
                  // Computed, not hardcoded "#fff": axe measured 57
                  // contrast failures here, down to 2.85:1 on TE, because
                  // white was assumed to work on every saturated
                  // background. `readableTextOn` picks whichever of black
                  // or white the colour actually supports — which also
                  // means a future palette change cannot silently
                  // reintroduce this. See lib/contrast.js.
                  color: active ? readableTextOn(color) : color,
                  background: active ? color : "transparent",
                  borderColor: color,
                }}
              >
                {g}
              </button>
            );
          })}
        </div>

        {/* Legend */}
        <div style={{ display: "flex", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
          {POS_GROUPS.filter((g) => activeGroups.has(g)).map((g) => (
            <div key={g} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: FONT_2XS }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: POS_GROUP_COLORS[g] }} />
              {g}
            </div>
          ))}
        </div>

        {/* Roster value PORTFOLIO, by position.  A different question
            from Team Strength above and deliberately kept separate
            (V1-35): this counts every asset the filters admit, at full
            market value, including bench depth and pick capital.

            It carries no "#" column any more.  It used to, sorted on
            the portfolio total, while the retired tier card printed a
            different "#rank" from a frontend score — two rankings of
            the same twelve teams, disagreeing for ten of them, four
            hundred pixels apart.  The order here is a sort of the
            column the user chose; the rank is the canonical one, in the
            Team Strength card above. */}
        <h3 className="team-strength-subtitle">Roster value portfolio</h3>
        <p className="roster-portfolio-note">
          Every asset the filters below admit, at full market value. Ordered by
          that total &mdash; a sort, not a rank. Team Strength is a different
          measurement, over the meaningful core, and is the card above.
        </p>
        {/* A horizontally-scrollable region has to be reachable without a
            pointer.  This table scrolls sideways on narrow viewports and had
            no way in from the keyboard at all — axe's
            `scrollable-region-focusable`.  `tabIndex={0}` makes it a tab stop
            so arrow keys can scroll it; `role="group"` + a name keep that stop
            from being an unlabelled one. */}
        <div
          className="table-wrap"
          tabIndex={0}
          role="group"
          aria-label="Roster value portfolio table, scrolls horizontally"
        >
          <table className="roster-portfolio-table">
            <thead>
              <tr>
                <th style={{ width: 140 }}>Team</th>
                <th style={{ width: 90, textAlign: "right" }}>Portfolio value</th>
                <th>Position Breakdown</th>
              </tr>
            </thead>
            <tbody>
              {sortedTeams.map((team) => {
                const isMe = team.name === myTeam;
                return (
                  <tr key={team.name} style={isMe ? { background: "rgba(200, 56, 3, 0.06)" } : undefined}>
                    <td style={{ fontWeight: 700, ...(isMe ? { color: "var(--cyan)" } : {}) }}>
                      {team.name}
                      <div style={{ fontSize: FONT_2XS, color: "var(--subtext)", fontWeight: 400 }}>
                        {team.playerCount} players{team.pickCount ? `, ${team.pickCount} picks` : ""}
                      </div>
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 600 }}>
                      {Math.round(team.activeTotal).toLocaleString()}
                    </td>
                    <td>
                      <div style={{ display: "flex", height: 20, borderRadius: 3, overflow: "hidden" }}>
                        {POS_GROUPS.filter((g) => activeGroups.has(g)).map((g) => {
                          const gVal = team.byGroup[g] || 0;
                          if (gVal <= 0) return null;
                          const pct = (gVal / maxActiveTotal) * 100;
                          return (
                            <div
                              key={g}
                              title={`${g}: ${Math.round(gVal).toLocaleString()}`}
                              style={{
                                width: `${pct.toFixed(1)}%`,
                                background: POS_GROUP_COLORS[g],
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                fontSize: FONT_2XS,
                                // Same rule as the chips above: the label
                                // sits ON the mark colour, so the readable
                                // foreground is computed rather than
                                // assumed white (PICKS was 2.19:1).
                                color: readableTextOn(POS_GROUP_COLORS[g]),
                                fontWeight: 700,
                                overflow: "hidden",
                                whiteSpace: "nowrap",
                              }}
                            >
                              {pct > 5 ? `${g} ${Math.round(gVal / 1000)}k` : ""}
                            </div>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* League Edge Map */}
      {leagueEdge.length > 0 && <LeagueEdgeCard edges={leagueEdge} />}

      {/* Age curve overlay — position typical age-value curves + my roster */}
      {myTeam && (() => {
        const me = sortedTeams.find((t) => t.name === myTeam);
        if (!me) return null;
        const rosterNames = new Set(
          (me.playerDetails || []).map((p) => String(p.name).toLowerCase()),
        );
        const boardRows = rows
          .filter((r) => r.pos !== "PICK" && r.pos !== "K")
          .map((r) => ({ pos: r.pos, age: r.age, rankDerivedValue: r.values?.full }));
        const rosterRows = rows
          .filter(
            (r) =>
              r.pos !== "PICK" &&
              r.pos !== "K" &&
              rosterNames.has(String(r.name).toLowerCase()),
          )
          .map((r) => ({
            pos: r.pos,
            age: r.age,
            rankDerivedValue: r.values?.full,
            name: r.name,
          }));
        return (
          <div className="card" style={{ padding: "var(--space-md)" }}>
            <h2 className="section-title">
              Age curves
              <InfoTip label="age curves">
                <p>
                  Typical value by age for each position, taken as the median of
                  the live board. Dots are players on your roster.
                </p>
                <p>
                  Use it to spot aging risk: a cluster of RBs past the
                  position&apos;s peak is a flag to sell; a cluster before it
                  means you are set up for the window.
                </p>
              </InfoTip>
            </h2>
            <AgeCurveOverlay boardRows={boardRows} rosterRows={rosterRows} />
          </div>
        );
      })()}

      {/* Trade Targets */}
      {myTeam && (
        <TradeTargetsCard
          myTeam={myTeam}
          teams={sortedTeams}
          groupAvg={groupAvg}
          onPlayerClick={openPlayerPopup}
        />
      )}

      {/* Waiver Wire Gems */}
      {waiverGems.length > 0 && (
        <WaiverWireCard gems={waiverGems} onPlayerClick={openPlayerPopup} />
      )}
    </section>
  );
}

function TradeTargetsCard({ myTeam, teams, groupAvg, onPlayerClick }) {
  const myTeamData = teams.find((t) => t.name === myTeam);
  if (!myTeamData) return null;

  const myStrengths = {};
  OFFENSE_GROUPS.forEach((g) => {
    myStrengths[g] = groupAvg[g] > 0 ? (myTeamData.byGroup[g] || 0) / groupAvg[g] : 1;
  });

  const weakest = OFFENSE_GROUPS.slice().sort((a, b) => myStrengths[a] - myStrengths[b]);
  const strongest = OFFENSE_GROUPS.slice().sort((a, b) => myStrengths[b] - myStrengths[a]);

  // Find trade targets at weakest positions
  const needPositions = weakest.slice(0, 2);
  const targetSections = needPositions.map((needPos) => {
    const pctOfAvg = (myStrengths[needPos] * 100).toFixed(0);
    const targets = [];

    for (const otherTeam of teams) {
      if (otherTeam.name === myTeam) continue;
      const otherStrength = groupAvg[needPos] > 0 ? (otherTeam.byGroup[needPos] || 0) / groupAvg[needPos] : 0;
      if (otherStrength < 1.0) continue;

      for (const p of otherTeam.players) {
        if (p.group !== needPos || p.meta < 1200 || p.meta > 8000) continue;

        // Find what the other team needs
        let theirNeed = "";
        let worstRatio = Infinity;
        for (const g of OFFENSE_GROUPS) {
          const ratio = groupAvg[g] > 0 ? (otherTeam.byGroup[g] || 0) / groupAvg[g] : 1;
          if (ratio < worstRatio) { worstRatio = ratio; theirNeed = g; }
        }

        targets.push({
          ...p,
          teamName: otherTeam.name,
          theirNeed: worstRatio < 1.0 ? theirNeed : "",
        });
      }
    }

    targets.sort((a, b) => b.meta - a.meta);
    return { needPos, pctOfAvg, targets: targets.slice(0, 8) };
  });

  // Surplus players from strongest positions
  const surplus = (myTeamData.players || [])
    .filter((p) => strongest.slice(0, 2).includes(p.group) && p.meta >= 1500)
    .sort((a, b) => b.meta - a.meta)
    .slice(0, 6);

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>Trade Targets</div>

      {/* Strength summary */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
        <span className="badge" style={{ background: "var(--green-soft)", color: POS_TEXT_COLORS[strongest[0]] }}>
          Strongest: {strongest[0]} ({(myStrengths[strongest[0]] * 100).toFixed(0)}%)
        </span>
        <span className="badge" style={{ background: "var(--red-soft, rgba(220,50,50,0.1))", color: POS_TEXT_COLORS[weakest[0]] }}>
          Weakest: {weakest[0]} ({(myStrengths[weakest[0]] * 100).toFixed(0)}%)
        </span>
      </div>

      {/* Need positions */}
      {targetSections.map(({ needPos, pctOfAvg, targets }) => (
        <div key={needPos} style={{ marginBottom: 14 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px" }}>
            Need: {needPos}{" "}
            <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--subtext)" }}>
              (you&apos;re at {pctOfAvg}% of league avg)
            </span>
          </h4>
          {targets.length === 0 ? (
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
              No clear trade targets — other teams are also thin here.
            </div>
          ) : (
            targets.map((t, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "0.72rem" }}>
                <PlayerImage
                  playerId={t.playerId}
                  team={t.team}
                  position={t.pos}
                  name={t.name}
                  size={22}
                />
                <span style={{ color: POS_TEXT_COLORS[needPos], fontFamily: "var(--mono)", fontWeight: 700, width: 28, fontSize: FONT_2XS }}>
                  {t.pos}
                </span>
                <PlayerNameButton
                  name={t.name}
                  onOpen={onPlayerClick}
                  style={{ flex: 1, fontWeight: 600 }}
                />
                <span style={{ fontFamily: "var(--mono)", width: 60, textAlign: "right" }}>{t.meta.toLocaleString()}</span>
                <span style={{ fontSize: "0.64rem", color: "var(--subtext)", minWidth: 100 }}>
                  {t.teamName}
                  {t.theirNeed && <span style={{ color: "var(--amber)" }}> (need {t.theirNeed})</span>}
                </span>
              </div>
            ))
          )}
        </div>
      ))}

      {/* Surplus */}
      {surplus.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <h4 style={{ fontSize: "0.78rem", margin: "0 0 6px", color: "var(--green)" }}>
            Your Trade Chips{" "}
            <span style={{ fontWeight: 400, fontSize: "0.7rem", color: "var(--subtext)" }}>
              (surplus from strong positions)
            </span>
          </h4>
          {surplus.map((p, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0", fontSize: "0.72rem" }}>
              <PlayerImage
                playerId={p.playerId}
                team={p.team}
                position={p.pos}
                name={p.name}
                size={22}
              />
              <span style={{ color: POS_TEXT_COLORS[p.group], fontFamily: "var(--mono)", fontWeight: 700, width: 28, fontSize: FONT_2XS }}>
                {p.pos}
              </span>
              <span style={{ flex: 1, fontWeight: 600 }}>{p.name}</span>
              <span style={{ fontFamily: "var(--mono)", width: 60, textAlign: "right" }}>{p.meta.toLocaleString()}</span>
              <span style={{ fontSize: "0.64rem", color: "var(--green)", minWidth: 100 }}>your roster</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function LeagueEdgeCard({ edges }) {
  const maxEdge = Math.max(1, ...edges.map((t) => Math.max(t.sellEdge, t.buyEdge)));

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>
        League Edge Map
        <InfoTip label="the league edge map">
          <p>Market price vs. our model, per team.</p>
          <p>
            <strong>Sell</strong> means the market overvalues their players —
            they are who you sell to. <strong>Buy</strong> means the market
            undervalues them.
          </p>
        </InfoTip>
      </div>
      {edges.map((t) => {
        const sellPct = Math.round((t.sellEdge / maxEdge) * 100);
        const buyPct = Math.round((t.buyEdge / maxEdge) * 100);
        return (
          <div
            key={t.name}
            style={{
              padding: "8px 10px",
              borderBottom: "1px solid var(--border-dim)",
              background: t.isMe ? "rgba(200,56,3,0.08)" : "",
              borderLeft: t.isMe ? "3px solid var(--cyan)" : "3px solid transparent",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
              <span style={{ fontWeight: 600, minWidth: 90, fontSize: "0.73rem" }} className="truncate">
                {t.name}{t.isMe ? " \u2B50" : ""}
              </span>
              <div style={{ flex: 1, display: "flex", gap: 4, alignItems: "center" }}>
                <div
                  style={{
                    width: `${sellPct}%`,
                    height: 10,
                    background: "var(--red)",
                    borderRadius: 2,
                    minWidth: t.sellEdge > 0 ? 2 : 0,
                  }}
                  title={`Market overvalues ${t.sellCount} of their players`}
                />
                <span style={{ fontSize: FONT_2XS, color: "var(--red)", fontFamily: "var(--mono)", minWidth: 40 }}>
                  {t.sellCount} sell
                </span>
                <div
                  style={{
                    width: `${buyPct}%`,
                    height: 10,
                    background: "var(--green)",
                    borderRadius: 2,
                    minWidth: t.buyEdge > 0 ? 2 : 0,
                  }}
                  title={`Market undervalues ${t.buyCount} of their players`}
                />
                <span style={{ fontSize: FONT_2XS, color: "var(--green)", fontFamily: "var(--mono)" }}>
                  {t.buyCount} buy
                </span>
              </div>
            </div>
            {(t.topSells.length > 0 || t.topBuys.length > 0) && (
              <div style={{ fontSize: FONT_2XS, color: "var(--subtext)", paddingLeft: 100 }}>
                {t.topSells.length > 0 && (
                  <span style={{ color: "var(--red)" }}>
                    Overvalued: {t.topSells.map((p) => `${p.name} +${p.pct}%`).join(", ")}
                  </span>
                )}
                {t.topSells.length > 0 && t.topBuys.length > 0 && " \u00B7 "}
                {t.topBuys.length > 0 && (
                  <span style={{ color: "var(--green)" }}>
                    Undervalued: {t.topBuys.map((p) => `${p.name} -${p.pct}%`).join(", ")}
                  </span>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function WaiverWireCard({ gems, onPlayerClick }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 6 }}>Waiver Wire Gems</div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginBottom: 8 }}>
        Players not on any roster with meaningful trade value.
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {gems.map((p) => (
          <div
            key={p.name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              padding: "5px 10px",
              border: "1px solid var(--border)",
              borderRadius: 6,
              fontSize: "0.72rem",
            }}
          >
            <PlayerImage
              playerId={p.playerId}
              team={p.team}
              position={p.pos}
              name={p.name}
              size={20}
            />
            <span style={{ color: POS_TEXT_COLORS[p.pos] || "var(--subtext)", fontWeight: 700, fontFamily: "var(--mono)", fontSize: FONT_2XS }}>
              {p.pos}
            </span>
            <PlayerNameButton
              name={p.name}
              onOpen={onPlayerClick}
              style={{ fontWeight: 600 }}
            />
            <span style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>{p.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
