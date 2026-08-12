// A backend that answers /api/public/league/* with a valid payload.
//
// The counterpart to `hanging-backend.mjs`.  Together they let the
// /league route be checked at both ends of the 2026-08-12 incident
// without a real FastAPI process:
//
//   hanging-backend  → the build must still succeed, and a request must
//                      degrade in seconds rather than hang
//   mock-backend     → a healthy backend must still be server-rendered,
//                      because that is the behaviour the incident repair
//                      is not allowed to trade away
//
// The payload shape is the public contract's section envelope:
// {contractVersion, league, section, data} — see
// `app/league/page.jsx::fetchSection`, which rejects anything without a
// `league` block.
//
// Usage:
//   node scripts/mock-backend.mjs [port]

import http from "node:http";

const port = Number(process.argv[2] || 8124);

// Deliberately unmistakable: if these strings reach the served HTML,
// they can only have come from a server-side fetch of this process.
const LEAGUE_NAME = "MOCK LEAGUE SSR PROBE";
const SEASON_RANGE = "2024-2026";

function sectionPayload(section) {
  return {
    contractVersion: "mock.v1",
    league: {
      leagueName: LEAGUE_NAME,
      seasonsCovered: [2024, 2025, 2026],
      managers: [{ ownerId: "owner-1", displayName: "Mock Manager" }],
    },
    section,
    data: {
      seasonRangeLabel: SEASON_RANGE,
      currentChampion: { displayName: "Mock Champ" },
    },
  };
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const m = url.pathname.match(/^\/api\/public\/league\/([^/]+)$/);
  if (m) {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify(sectionPayload(decodeURIComponent(m[1]))));
    return;
  }
  if (url.pathname === "/api/public/league") {
    res.writeHead(200, { "content-type": "application/json" });
    res.end(JSON.stringify({ ...sectionPayload("overview"), sections: {} }));
    return;
  }
  res.writeHead(404, { "content-type": "application/json" });
  res.end(JSON.stringify({ error: "not_found" }));
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`mock-backend listening on 127.0.0.1:${port}\n`);
});

export { LEAGUE_NAME, SEASON_RANGE };
