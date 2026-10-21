// /league/activity — server entry.  The page itself is the client
// component in ./ActivityClient.jsx (unchanged); this wrapper exists only
// to decide its "← League home" href on the server from the cached
// advisor bootstrap (./../advisor-bootstrap.js), so the browser never makes
// a teams request just to pick a back-link.  `/league` exactly as main
// unless the Brisket Trade Advisor is confirmed served.
import ActivityClient from "./ActivityClient.jsx";
import { leagueHomeHref } from "../advisor-bootstrap.js";

export default async function ActivityPage() {
  return <ActivityClient leagueHome={await leagueHomeHref()} />;
}
