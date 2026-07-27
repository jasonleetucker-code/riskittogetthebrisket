/**
 * A page must not assert a value basis its numbers do not have.
 *
 * The lens is set on /rankings and /trade but applies everywhere —
 * `fetchDynastyData` composes the overlay before any page sees the
 * contract. So /draft, /rosters, /edge and /waivers were rendering
 * league-adjusted values with no toggle in sight and nothing saying the
 * board had moved. The values were right; the silence was the defect.
 *
 * THE ASSERTION THAT MATTERS is that the basis is read off the CONTRACT
 * and not off `settings.valuationMode`. Those two diverge in three real
 * cases — a failed overlay fetch, the scrape-version pin refusing, and
 * the server finding no roster snapshot — and in every one of them the
 * setting still says "leagueAdjusted" while the numbers are market.
 * Labelling off the setting would put the wrong label on precisely the
 * boards that most need the right one, so there is a test for each.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { ValueBasisNote } from "@/components/ds/ValueBasisNote";
import {
  valuationBasisOf,
  valuationBasisLabel,
  mergeRankingsDelta,
} from "@/lib/dynasty-data";

describe("valuationBasisOf", () => {
  it("reads leagueAdjusted off a client-applied overlay", () => {
    expect(
      valuationBasisOf({ valuationOverlay: { mode: "leagueAdjusted" } })
    ).toBe("leagueAdjusted");
  });

  it("reads leagueAdjusted off the server-composed board", () => {
    // Custom weights + the lens is composed server-side and carries no
    // client-applied overlay object. Before this, /trade's banner gated
    // on `rawData.valuationOverlay` and went silent on exactly that
    // board — adjusted values, no label.
    const merged = mergeRankingsDelta(
      { playersArray: [{ displayName: "A", rankDerivedValue: 100 }] },
      {
        meta: { valuationMode: "leagueAdjusted" },
        valuationAdjustment: { adjustedCount: 1 },
        rankingsDelta: { playerKey: "displayName", players: [{ id: "A" }] },
      }
    );
    expect(valuationBasisOf(merged)).toBe("leagueAdjusted");
    // mergeRankingsDelta returns the {ok, source, data} envelope.
    expect(merged.data.valuationOverlay.serverComposed).toBe(true);
  });

  it("says market when the server degraded despite the request", () => {
    // No roster snapshot => scarcity unmeasurable => market values with
    // a note. The user's SETTING still says leagueAdjusted here; the
    // board does not, and the board is what gets labelled.
    const merged = mergeRankingsDelta(
      { playersArray: [{ displayName: "A", rankDerivedValue: 100 }] },
      {
        meta: { valuationNote: "league_adjusted_unavailable: no_roster_snapshot" },
        rankingsDelta: { playerKey: "displayName", players: [{ id: "A" }] },
      }
    );
    expect(valuationBasisOf(merged)).toBe("market");
    expect(merged.data.valuationNote).toContain("league_adjusted_unavailable");
  });

  it("defaults to market for an absent or empty contract", () => {
    expect(valuationBasisOf(null)).toBe("market");
    expect(valuationBasisOf(undefined)).toBe("market");
    expect(valuationBasisOf({})).toBe("market");
  });

  it("unwraps the {data} envelope", () => {
    expect(
      valuationBasisOf({ data: { valuationOverlay: { mode: "leagueAdjusted" } } })
    ).toBe("leagueAdjusted");
  });
});

describe("ValueBasisNote", () => {
  it("renders nothing on the market board", () => {
    // Deliberate: market is the default every user is on, and a
    // permanent "these are market values" strip on nine pages is noise
    // that trains people to stop reading it.
    const { container } = render(<ValueBasisNote contract={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the board when it is league-adjusted", () => {
    render(
      <ValueBasisNote contract={{ valuationOverlay: { mode: "leagueAdjusted" } }} />
    );
    expect(screen.getByRole("note")).toHaveTextContent(
      /Valued on your league's board/i
    );
  });

  it("discloses that picks do not move", () => {
    // The single largest behavioural consequence of the lens: scarcity
    // has no PICK key, so league-adjusted mode systematically reprices
    // every player against every pick. That belongs in UI copy.
    render(
      <ValueBasisNote contract={{ valuationOverlay: { mode: "leagueAdjusted" } }} />
    );
    expect(screen.getByRole("note")).toHaveTextContent(/picks/i);
  });

  it("stays silent when the contract is missing entirely", () => {
    const { container } = render(<ValueBasisNote contract={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("valuationBasisLabel", () => {
  it("never guesses — an unknown board reads as market, explicitly", () => {
    expect(valuationBasisLabel({})).toMatch(/Market/i);
  });

  it("is distinguishable in an export cell", () => {
    // The label ends up as a CSV column. Two boards that stringify the
    // same would defeat the column entirely.
    const market = valuationBasisLabel({});
    const adjusted = valuationBasisLabel({
      valuationOverlay: { mode: "leagueAdjusted" },
    });
    expect(market).not.toEqual(adjusted);
    expect(adjusted).toMatch(/league/i);
  });
});
