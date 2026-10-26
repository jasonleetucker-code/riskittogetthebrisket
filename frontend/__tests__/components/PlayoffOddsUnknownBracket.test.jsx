/**
 * V1-51 — "every probability is null" has more than one cause.
 *
 * The panel short-circuited on all-null probabilities and rendered
 * "Preseason — odds not yet simulated". That is a promise the numbers
 * arrive on their own. An unknown playoff bracket is not: the league has
 * not published how many teams qualify, so nothing populates until it
 * does, and telling a manager to wait is telling them to wait for
 * something that is not coming.
 */
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import PlayoffOddsChart from "@/components/graphs/PlayoffOddsChart";

const OWNERS = [
  { ownerId: "a", displayName: "Alice", playoffProbability: null },
  { ownerId: "b", displayName: "Bob", playoffProbability: null },
];

describe("PlayoffOddsChart — why the odds are missing", () => {
  it("names an unknown bracket instead of claiming preseason", () => {
    render(
      <PlayoffOddsChart
        data={{
          scheduleCertainty: "unknown_bracket",
          playoffSpots: null,
          numSims: 0,
          owners: OWNERS,
          unsimulable: {
            reason: "league_settings_omit_playoff_teams",
            detail: "this league's settings do not say how many teams make the playoffs.",
          },
        }}
      />,
    );
    expect(screen.getByText(/Playoff format not published/i)).toBeTruthy();
    expect(screen.queryByText(/Preseason/i)).toBeNull();
    expect(screen.getByText(/do not say how many teams/i)).toBeTruthy();
  });

  it("still says preseason when that is genuinely the reason", () => {
    render(
      <PlayoffOddsChart
        data={{
          scheduleCertainty: "preseason",
          playoffSpots: 7,
          numSims: 0,
          owners: OWNERS,
        }}
      />,
    );
    expect(screen.getByText(/Preseason — odds not yet simulated/i)).toBeTruthy();
    expect(screen.queryByText(/Playoff format not published/i)).toBeNull();
  });

  it("does not promise a top-N when it does not know the N", () => {
    render(
      <PlayoffOddsChart
        data={{
          scheduleCertainty: "unknown_bracket",
          playoffSpots: null,
          numSims: 0,
          owners: OWNERS,
          unsimulable: { reason: "league_settings_omit_playoff_teams", detail: "unknown." },
        }}
      />,
    );
    expect(screen.queryByText(/make playoffs/i)).toBeNull();
  });

  // C5-PLAY-01: the section is the ONE canonical engine's forecast, which
  // can refuse mid-season (e.g. no team evidence). That is neither a
  // preseason promise nor an unknown bracket — say what the backend said.
  it("names a mid-season refusal instead of claiming preseason", () => {
    render(
      <PlayoffOddsChart
        data={{
          scheduleCertainty: "posted",
          playoffSpots: 7,
          numSims: 0,
          simulated: false,
          owners: OWNERS,
          unsimulable: {
            reason: "team_strength_unavailable",
            detail: "ROS team strength is unavailable. This is not an equal chance for everyone.",
          },
        }}
      />,
    );
    expect(screen.getByText(/Playoff odds unavailable/i)).toBeTruthy();
    expect(screen.getByText(/not an equal chance/i)).toBeTruthy();
    expect(screen.queryByText(/Preseason/i)).toBeNull();
  });

  it("labels un-posted weeks as not simulated rather than round-robin", () => {
    const { container } = render(
      <PlayoffOddsChart
        data={{
          scheduleCertainty: "posted_weeks_only",
          playoffSpots: 7,
          numSims: 8000,
          weeksPlayed: 4,
          weeksRemaining: 10,
          owners: [
            { ownerId: "a", displayName: "Alice", playoffProbability: 0.8 },
            { ownerId: "b", displayName: "Bob", playoffProbability: 0.2 },
          ],
        }}
      />,
    );
    expect(container.textContent).toMatch(/Posted weeks only \(un-posted weeks not simulated\)/);
    expect(container.textContent).not.toMatch(/round-robin/i);
  });
});
