import { forwardAdvisor } from "../../../_bridge.js";

// Dev-only bridge (404 in production) — see ../../../_bridge.js.  The
// roster id is forwarded as text; the backend validates it.
export async function GET(req, { params }) {
  const { rosterId } = await params;
  return forwardAdvisor(
    req,
    `/api/public/league/trade-advisor/teams/${encodeURIComponent(String(rosterId))}/assets`,
  );
}
