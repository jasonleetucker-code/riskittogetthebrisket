// Is the Brisket Trade Advisor served by the backend under test?
//
// `request` uses baseURL = the backend (:8000): the same answer the Next
// server got when it rendered /league.  Mirrors `classifyTeamsResult`
// (frontend/lib/trade-advisor-client.js): 200 → served; 503 with
// reason "disabled", 404 or no answer → not served (flag
// `brisket_trade_advisor` off or route absent).  With the flag off the hub
// must equal main: Overview lands, labelled "Home", no advisor tab.
async function advisorServed(request) {
  const res = await request.get("/api/public/league/trade-advisor/teams").catch(() => null);
  if (!res) return false;
  if (res.status() === 200) return true;
  if (res.status() === 503) {
    const body = await res.json().catch(() => ({}));
    return body.reason !== "disabled";
  }
  return false;
}

// The overview tab's label: "Overview" while the advisor is served (it is
// Home then), "Home" exactly as on main while it is not.
async function overviewTabLabel(request) {
  return (await advisorServed(request)) ? "Overview" : "Home";
}

module.exports = { advisorServed, overviewTabLabel };
