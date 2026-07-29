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
import { InfoTip } from "./Help";

export function ValueBasisNote({ contract, className = "" }) {
  if (valuationBasisOf(contract) !== "leagueAdjusted") return null;
  // Two things stay VISIBLE because they change how you read the
  // numbers: which board this is, and that picks did not move with it.
  // The second is the lens's largest behavioural consequence —
  // `compute_scarcity` has no PICK key, so every player is repriced
  // against every pick — and burying it behind a click would be a
  // disclosure regression, not a decluttering win.  Only the
  // derivation detail (where the scarcity number comes from) moves into
  // the tip; that answers a question a user asks once, and it was
  // repeating on eight pages.
  return (
    <p className={`ds-value-basis-note ${className}`.trim()} role="note">
      <strong>Valued on your league&apos;s board.</strong> Picks stay at market
      value.
      <InfoTip label="your league&apos;s board">
        <p>
          Positional scarcity is measured from this league&apos;s actual
          rosters, so a position that runs thin here is worth more here.
        </p>
        <p>
          Draft picks carry no scarcity measurement, so they hold their market
          value while players move around them.
        </p>
      </InfoTip>
    </p>
  );
}
