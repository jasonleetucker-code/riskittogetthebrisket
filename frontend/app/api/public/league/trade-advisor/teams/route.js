import { forwardAdvisor } from "../_bridge.js";

// Dev-only bridge (404 in production) — see ../_bridge.js.
export async function GET(req) {
  return forwardAdvisor(req, "/api/public/league/trade-advisor/teams");
}
