// Small muted caption carrying the owner-approved uncalibrated-odds
// disclosure (owner decision 9, 2026-11-01).  Display only: it changes no
// number.  Styling is the league sections' existing caption treatment
// (0.72rem, var(--subtext)) — not a new style.
import { ODDS_EXPERIMENTAL_DISCLOSURE } from "@/lib/odds-disclosure";

export default function OddsExperimentalNote({ style }) {
  return (
    <p
      role="note"
      data-testid="odds-experimental-note"
      style={{ fontSize: "0.72rem", color: "var(--subtext)", margin: "0 0 10px", ...style }}
    >
      {ODDS_EXPERIMENTAL_DISCLOSURE}
    </p>
  );
}
