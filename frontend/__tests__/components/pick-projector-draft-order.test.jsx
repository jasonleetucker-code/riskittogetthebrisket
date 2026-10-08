/**
 * Pick Projector v2 — slots come from the season simulation under the
 * league's draft-order rule, and only the next class is forecast.  A pick
 * with no slot forecast is shown as such, never as a guessed slot or as a
 * "low" confidence reading.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import PickProjectorPanel, {
  slotForecastReasonText,
} from "@/app/league/sections/_pick-projector.jsx";

afterEach(() => {
  vi.unstubAllGlobals();
});

const PICK = (over = {}) => ({
  season: 2027,
  round: 1,
  seasonsOut: 1,
  projectedSlot: 1,
  projectedPickNumber: 1,
  label: "2027 1.01",
  confidence: "high",
  slotConfidence: "high",
  expectedSlot: 1.2,
  slotDistribution: [0.8, 0.2],
  slotForecastUnavailableReason: null,
  ownerRosterId: 1,
  ownerTeam: "Rebuilders",
  originalRosterId: 1,
  originalTeam: "Rebuilders",
  ...over,
});

describe("slotForecastReasonText", () => {
  it("names every backend reason in plain language", () => {
    for (const reason of [
      "class_beyond_simulated_season",
      "no_draft_order_rule_for_league",
      "no_fresh_season_simulation",
      "simulation_published_no_slot_distribution",
      "simulated_season_unknown",
      "originating_team_not_in_simulation",
      "season_simulation_unsimulable",
      "simulation_rule_differs_from_league_rule",
      "simulation_owner_join_incomplete",
      "class_before_simulated_season",
    ]) {
      const text = slotForecastReasonText(reason);
      expect(text).toBeTruthy();
      expect(text).not.toMatch(/_/);
    }
  });

  it("reads the simulation's own refusal behind the unsimulable prefix", () => {
    expect(
      slotForecastReasonText(
        "season_simulation_unsimulable:no_games_played_and_none_scheduled",
      ),
    ).toMatch(/can't be simulated/);
  });

  it("is null when a slot exists and generic for an unknown reason", () => {
    expect(slotForecastReasonText(null)).toBeNull();
    expect(slotForecastReasonText("new_reason")).toBe(
      "No slot forecast is available.",
    );
  });
});

describe("PickProjectorPanel (draft-order rule)", () => {
  it("renders a forecast class with its slot and a later class without one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          projectedOrder: [],
          picks: [
            PICK(),
            PICK({
              season: 2028,
              seasonsOut: 2,
              projectedSlot: null,
              projectedPickNumber: null,
              label: "2028 Round 1",
              confidence: null,
              slotConfidence: null,
              slotForecastUnavailableReason: "class_beyond_simulated_season",
            }),
          ],
          meta: {
            pickOwnershipState: "observed",
            unprojectablePicks: 0,
            draftOrderRule: "reverse_record_lower_pf",
          },
        }),
      })),
    );
    render(<PickProjectorPanel leagueKey="dynasty_main" />);
    await waitFor(() => expect(screen.getByText("2027 1.01")).toBeTruthy());
    expect(screen.getByText("2028 Round 1")).toBeTruthy();
    const noSlot = screen.getByTestId("pick-projector-no-slot");
    expect(noSlot.textContent).toBe("No slot forecast");
    expect(noSlot.getAttribute("title")).toMatch(/Only next season/);
    expect(screen.getByText(/worst final record picks first/)).toBeTruthy();
    expect(screen.queryByText(/roster strength/)).toBeNull();
  });
});

describe("PickProjectorPanel — league with no slot forecast", () => {
  it("states the reason once, visibly, not only in a tooltip", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          projectedOrder: [],
          picks: [
            PICK({
              projectedSlot: null,
              projectedPickNumber: null,
              label: "2027 Round 1",
              confidence: null,
              slotConfidence: null,
              slotForecastUnavailableReason: "no_draft_order_rule_for_league",
            }),
          ],
          meta: {
            pickOwnershipState: "observed",
            unprojectablePicks: 0,
            slotForecastUnavailableReason: "no_draft_order_rule_for_league",
          },
        }),
      })),
    );
    render(<PickProjectorPanel leagueKey="dynasty_new" />);
    const note = await screen.findByTestId("pick-projector-no-forecast-note");
    expect(note.textContent).toMatch(/no recorded draft-order rule/);
    // The header does not describe a rule the league does not have.
    expect(screen.queryByText(/worst final record picks first/)).toBeNull();
  });
});
