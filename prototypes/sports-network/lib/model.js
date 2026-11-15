import players from "../fixtures/players.json";
import stories from "../fixtures/news.json";
export { players, stories };
export const DEMO_CLOCK = "2026-11-07T18:00:00Z";
export const formats = ["Superflex", "1QB", "TE Premium"];
export const positions = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"];
export const number = (value) =>
  value == null ? "Unavailable" : value.toLocaleString("en-US");
export const signed = (value) => `${value > 0 ? "+" : ""}${number(value)}`;
export function selectPlayers({
  query = "",
  pos = "All",
  movement = "All",
  format = "Superflex",
  sort = "rank",
  direction = "asc",
} = {}) {
  const q = query.toLowerCase().trim();
  return players
    .map((p) => ({
      ...p,
      rank: p.ranks[format],
      posRank: p.positionRanks[format],
      history: p.histories[format],
    }))
    .filter(
      (p) =>
        (!q || `${p.name} ${p.team}`.toLowerCase().includes(q)) &&
        (pos === "All" || p.pos === pos) &&
        (movement === "All" ||
          (movement === "Risers"
            ? p.movement > 0
            : movement === "Fallers"
              ? p.movement < 0
              : p.movement === 0)),
    )
    .sort((a, b) => {
      const av = sort === "value" ? a.values[format] : a[sort];
      const bv = sort === "value" ? b.values[format] : b[sort];
      if (av == null) return bv == null ? 0 : 1;
      if (bv == null) return -1;
      const result = typeof av === "string" ? av.localeCompare(bv) : av - bv;
      return (direction === "asc" ? result : -result) || a.rank - b.rank;
    });
}
export function selectStories({
  query = "",
  team = "All",
  pos = "All",
  category = "All",
  source = "All",
  scope = "All",
} = {}) {
  return stories
    .filter((s) => {
      const p = players.find((p) => p.id === s.playerId);
      return (
        `${s.headline} ${p.name} ${s.summary}`
          .toLowerCase()
          .includes(query.toLowerCase().trim()) &&
        (team === "All" || p.team === team) &&
        (pos === "All" || p.pos === pos) &&
        (category === "All" || s.category === category) &&
        (source === "All" || s.source === source) &&
        (scope === "All" || p.roster)
      );
    })
    .sort((a, b) => b.publishedAt.localeCompare(a.publishedAt));
}
export function tickerStories() {
  const priority = {
    "Official confirmation": 0,
    "Credible reporting": 1,
    Analysis: 2,
    Unconfirmed: 3,
  };
  return stories
    .filter((s) => !s.stale && s.classification !== "Unconfirmed")
    .sort(
      (a, b) =>
        priority[a.classification] - priority[b.classification] ||
        b.importance - a.importance ||
        b.publishedAt.localeCompare(a.publishedAt),
    );
}
export function csvFor(rows, format) {
  const escape = (v) => `"${String(v ?? "Unavailable").replaceAll('"', '""')}"`;
  return [
    [
      "SYNTHETIC DEMO — NOT LIVE",
      "Rank",
      "Player",
      "Position",
      "Team",
      format,
      "7d change",
      "Disagreement",
      "Freshness",
    ],
    ...rows.map((p) => [
      "Synthetic",
      p.rank,
      p.name,
      p.pos,
      p.team,
      p.values[format],
      p.movement,
      p.disagreement,
      p.freshness,
    ]),
  ]
    .map((r) => r.map(escape).join(","))
    .join("\r\n");
}
export const tradeScenarios = {
  "demo-01": {
    title: "Explore a receiver-for-depth package",
    text: "Demo research handoff: compare Vale with Reed plus a future pick. Package value, roster impact and fairness are unavailable in this prototype. Production would request the canonical trade analysis contract.",
  },
  "demo-02": {
    title: "Explore a quarterback tier change",
    text: "Demo research handoff: compare Brooks with Ford. No trade verdict has been calculated. Production would preserve league scoring, roster capacity and canonical analysis.",
  },
};
