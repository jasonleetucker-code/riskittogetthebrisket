/**
 * Builder state that matches a `fixtures/trade-multi/*.json` response: the
 * /trade sides (one per team, assets routed to their legs' destinations) and
 * the `sleeper.teams` that hold those assets.  Derived from the fixture's own
 * legs and per-team `gives`, so it cannot drift from the real-engine payload.
 */
import { tradeEntryKey } from "@/lib/trade-assets";

export function builderFromFixture(fixture) {
  const teamIds = fixture.teams.map((t) => t.rosterId);
  const sideOf = new Map(teamIds.map((rid, i) => [rid, i]));
  const sleeperTeams = fixture.teams.map((t) => ({
    roster_id: t.rosterId,
    name: t.team?.name || `Team ${t.rosterId}`,
    playerIds: [],
    pickDetails: [],
  }));
  const sides = fixture.teams.map((t, i) => ({
    id: i,
    label: "ABCDE"[i],
    assets: [],
    destinations: {},
  }));
  for (const t of fixture.teams) {
    const i = sideOf.get(t.rosterId);
    for (const g of t.gives) {
      const entry =
        g.kind === "pick"
          ? { name: g.label, assetId: g.assetId, assetLabel: g.label, pos: "PICK", values: { full: g.value ?? 0 } }
          : { name: g.label, playerId: g.assetId.slice(2), pos: "WR", values: { full: g.value ?? 0 } };
      sides[i].assets.push(entry);
      sides[i].destinations[tradeEntryKey(entry)] = sideOf.get(g.toRosterId);
      if (g.kind === "pick") sleeperTeams[i].pickDetails.push({ assetId: g.assetId });
      else sleeperTeams[i].playerIds.push(g.assetId.slice(2));
    }
  }
  return { sides, sleeperTeams, teamIds };
}
