// `/` — server entry.  The page itself is the client component in
// ./HomeClient.jsx (unchanged); this wrapper exists only to tell it
// whether the Brisket Trade Advisor is CONFIRMED served, from the cached
// server read in ./league/advisor-bootstrap.js.  Off or unknown, the
// landing card reads exactly as main (no browser request is involved).
import HomeClient from "./HomeClient.jsx";
import { advisorConfirmedServed } from "./league/advisor-bootstrap.js";

export default async function HomePage() {
  return <HomeClient advisorServed={await advisorConfirmedServed()} />;
}
