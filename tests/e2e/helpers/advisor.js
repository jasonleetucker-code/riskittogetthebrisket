// Is the Brisket Trade Advisor served by the backend under test?
//
// `request` uses baseURL = the backend (:8000): the same answer the Next
// server got when it rendered /league.  Mirrors the hub's rule (R2-9):
// only a 200 — `classifyTeamsResult` "ready" (frontend/lib/
// trade-advisor-client.js) — offers the advisor.  A 503 (flag off →
// "disabled", launch gate closed → "not_ready"), a 404 or no answer is not
// served, and the hub must then equal main: Overview lands, labelled
// "Home", no advisor tab.
async function advisorServed(request) {
  const res = await request.get("/api/public/league/trade-advisor/teams").catch(() => null);
  if (!res || res.status() !== 200) return false;
  const body = await res.json().catch(() => null);
  return Boolean(body && Array.isArray(body.teams) && body.teams.length >= 2);
}

// The overview tab's label: "Overview" while the advisor is served (it is
// Home then), "Home" exactly as on main while it is not.
async function overviewTabLabel(request) {
  return (await advisorServed(request)) ? "Overview" : "Home";
}

module.exports = { advisorServed, overviewTabLabel };
