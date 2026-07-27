/**
 * ValueBasisNote — names the board a page's numbers came from.
 *
 * Renders NOTHING on the market board. That is deliberate: market is the
 * default every user is on, and a permanent "these are market values"
 * strip on nine pages is noise that trains people to stop reading it.
 * The note appears only when the numbers are something other than what a
 * reader would assume.
 *
 * WHY THIS EXISTS
 * The valuation lens is set on /rankings and /trade but applies
 * everywhere — `fetchDynastyData` composes the overlay before any page
 * sees the contract. So /draft, /rosters, /edge and /waivers render
 * league-adjusted values with no toggle in sight and nothing saying the
 * board moved. The values are right; the silence is the defect.
 *
 * Pass the CONTRACT, not the setting. `valuationBasisOf` reads what the
 * board actually is, which diverges from what the user asked for
 * whenever the overlay fetch fails, the scrape-version pin refuses, or
 * the server finds no roster snapshot. Labelling off the setting would
 * assert "league-adjusted" over market numbers in exactly those cases —
 * the failure this component exists to prevent.
 */
"use client";

import React from "react";
import { valuationBasisOf } from "@/lib/dynasty-data";

export function ValueBasisNote({ contract, className = "" }) {
  if (valuationBasisOf(contract) !== "leagueAdjusted") return null;
  return (
    <p className={`ds-value-basis-note ${className}`.trim()} role="note">
      <strong>Valued on your league&apos;s board.</strong> Positional scarcity
      measured from this league&apos;s rosters. Draft picks carry no scarcity
      measurement, so they stay at market value while players move around them.
    </p>
  );
}
