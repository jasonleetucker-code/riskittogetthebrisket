// /rankings says its IDP values are not scored under the league's rules.
//
// Audit W27-F012.  The IDP family ordering on the board is inherited
// from generic IDP calculators — measured live, DB peaks at 3,159
// against DL 6,362 — in a league that pays 5.32 per pass defensed and
// 5.32 per interception against 1.33 per solo tackle.  Nothing in the
// live value path re-scores a defender under those settings.
//
// The contract now says so; this pins that the page renders what the
// contract says, and renders NOTHING when the contract stops saying it.
// Reading the flag rather than mirroring the sentence is the same rule
// the formula and confidence lines already follow in this component.
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { MethodologySection } from "@/app/rankings/board-sections";

const DISCLOSED = {
  idpTranslation: {
    formatSensitivity: {
      scoredUnderLeagueSettings: false,
      description:
        "IDP values on this board are FORMAT-GENERIC. For a scoring-exact fundamental valuation see /bdvm.",
    },
  },
};

describe("MethodologySection IDP format disclosure", () => {
  it("renders the contract's own words", () => {
    render(<MethodologySection methodology={DISCLOSED} />);
    expect(screen.getByText(/IDP values are format-generic/)).toBeTruthy();
    expect(screen.getByText(/scoring-exact fundamental valuation/)).toBeTruthy();
  });

  it("says nothing when the contract does not carry the flag", () => {
    render(<MethodologySection methodology={{}} />);
    expect(screen.queryByText(/format-generic/)).toBeNull();
  });

  it("disappears the day the board starts scoring IDP", () => {
    render(
      <MethodologySection
        methodology={{
          idpTranslation: {
            formatSensitivity: {
              scoredUnderLeagueSettings: true,
              description: "scored under this league's settings",
            },
          },
        }}
      />,
    );
    expect(screen.queryByText(/IDP values are format-generic/)).toBeNull();
  });

  it("renders with no methodology at all", () => {
    render(<MethodologySection />);
    expect(screen.queryByText(/format-generic/)).toBeNull();
  });
});
