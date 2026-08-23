import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ConductSection from "@/app/league/sections/conduct.jsx";

const managers = new Map([
  [
    "owner-A",
    {
      ownerId: "owner-A",
      displayName: "AAron",
      currentTeamName: "Brisket Bandits",
      avatar: "",
    },
  ],
  [
    "owner-B",
    {
      ownerId: "owner-B",
      displayName: "Bea",
      currentTeamName: "Bea's Beast Mode",
      avatar: "",
    },
  ],
]);

const methodology = {
  mainTally: "The main tally counts unique current-roster players.",
  breakdownCounts: "Breakdown categories overlap.",
  rosterScope: "Active, bench, reserve, and taxi slots; no picks.",
  sourceRule: "Every record requires a reliable source.",
  included: ["Domestic or sexual-assault allegations", "Serious criminal charges"],
  excluded: ["Rumors", "Drug/PED matters"],
  caveat:
    "This is a curated public-record index, not a complete background check. A listing is not a finding of guilt; read each status and disposition.",
};

const scoring = {
  version: "1.0",
  formula:
    "Team score = sum(category severity points × current-status multiplier + qualifying discipline bonus) + outcome-scaled repeat-incident bonuses",
  severityWeights: [
    { category: "domesticViolence", label: "Domestic violence", points: 50 },
    { category: "seriousCrime", label: "Other serious crime", points: 30 },
  ],
  outcomeMultipliers: [
    { status: "convicted", label: "Convicted", multiplier: 1 },
    { status: "allegedNoCharge", label: "Documented allegation; no charge", multiplier: 0.2 },
    { status: "acquitted", label: "Acquitted", multiplier: 0 },
  ],
  disciplineBonus: 10,
  repeatIncidentBonus: 10,
  repeatDefinition:
    "Each additional distinct reviewed incident adds up to 10 points, scaled by its outcome.",
  caveat: "The score ranks rosters and is not a finding of guilt or character.",
};

function incident(overrides = {}) {
  return {
    incidentId: "incident-one",
    date: "2025-01-01",
    dateLabel: "January 1, 2025",
    lastVerified: "2026-08-23",
    category: "domesticViolence",
    categoryLabel: "Domestic violence",
    summary: "A source-backed allegation was reported.",
    status: "allegedNoCharge",
    statusLabel: "Allegation; no criminal charge reported",
    disposition: "No criminal charge was reported.",
    denial: "The player denied the allegation.",
    discipline: null,
    qualifyingBasis: ["credibleAllegation"],
    score: 10,
    scoreBreakdown: {
      severityPoints: 50,
      outcomeMultiplier: 0.2,
      disciplineBonus: 0,
    },
    sources: [
      {
        label: "Associated Press — case report",
        url: "https://apnews.com/article/example",
      },
    ],
    ...overrides,
  };
}

function healthyData() {
  return {
    available: true,
    unavailableReason: null,
    asOf: "2026-08-23T12:00:00Z",
    registryLastReviewed: "2026-08-23",
    methodology,
    scoring,
    totals: {
      teams: 2,
      rosteredPlayers: 112,
      flaggedPlayers: 2,
      incidents: 4,
      score: 79.5,
      breakdown: {
        credibleAllegation: 2,
        formalLegalAction: 1,
        convictionOrPlea: 0,
        violenceRelatedDiscipline: 1,
      },
    },
    dataQuality: {
      acceptedPlayerCount: 2,
      acceptedIncidentCount: 4,
      rejectedPlayerCount: 0,
      rejectedIncidentCount: 0,
      matchedRegistryPlayerCount: 2,
      unrosteredRegistryPlayerCount: 0,
    },
    teams: [
      {
        rank: 1,
        ownerId: "owner-A",
        rosterId: 1,
        displayName: "AAron",
        teamName: "Brisket Bandits",
        rosteredPlayerCount: 58,
        flaggedPlayerCount: 2,
        incidentCount: 4,
        score: 79.5,
        breakdown: {
          credibleAllegation: 2,
          formalLegalAction: 1,
          convictionOrPlea: 0,
          violenceRelatedDiscipline: 1,
        },
        players: [
          {
            playerId: "p-1",
            playerName: "Example Player",
            position: "WR",
            nflTeam: "MIN",
            incidentCount: 3,
            qualifyingBasis: ["credibleAllegation", "formalLegalAction"],
            score: 27,
            incidentPoints: 25,
            repeatIncidentBonus: 2,
            isRepeatIncidentPlayer: true,
            incidents: [
              incident(),
              incident({
                incidentId: "incident-two",
                status: "acquitted",
                statusLabel: "Acquitted at trial",
                summary: "A separate criminal accusation went to trial.",
                disposition: "A jury returned a not-guilty verdict.",
                denial: "The player pleaded not guilty before the acquittal.",
                qualifyingBasis: ["credibleAllegation", "formalLegalAction"],
                score: 0,
                scoreBreakdown: {
                  severityPoints: 50,
                  outcomeMultiplier: 0,
                  disciplineBonus: 0,
                },
              }),
              incident({
                incidentId: "incident-four",
                status: "resolvedMixed",
                statusLabel: "Mixed resolution",
                summary: "A third documented matter had a mixed resolution.",
                disposition: "The cited record documents a mixed resolution.",
                score: 15,
                scoreBreakdown: {
                  severityPoints: 50,
                  outcomeMultiplier: 0.3,
                  disciplineBonus: 0,
                },
              }),
            ],
          },
          {
            playerId: "p-2",
            playerName: "Disciplined Player",
            position: "DL",
            nflTeam: "DET",
            incidentCount: 1,
            qualifyingBasis: ["credibleAllegation", "violenceRelatedDiscipline"],
            score: 52.5,
            incidentPoints: 52.5,
            repeatIncidentBonus: 0,
            isRepeatIncidentPlayer: false,
            incidents: [
              incident({
                incidentId: "incident-three",
                status: "leagueFinding",
                statusLabel: "NFL personal-conduct finding",
                discipline: {
                  organization: "NFL",
                  description: "Three-game suspension",
                  date: "2025-02-01",
                },
                qualifyingBasis: [
                  "credibleAllegation",
                  "violenceRelatedDiscipline",
                ],
                score: 52.5,
                scoreBreakdown: {
                  severityPoints: 50,
                  outcomeMultiplier: 0.85,
                  disciplineBonus: 10,
                },
              }),
            ],
          },
        ],
      },
      {
        rank: 2,
        ownerId: "owner-B",
        rosterId: 2,
        displayName: "Bea",
        teamName: "Bea's Beast Mode",
        rosteredPlayerCount: 54,
        flaggedPlayerCount: 0,
        incidentCount: 0,
        score: 0,
        breakdown: {
          credibleAllegation: 0,
          formalLegalAction: 0,
          convictionOrPlea: 0,
          violenceRelatedDiscipline: 0,
        },
        players: [],
      },
    ],
  };
}

describe("Piece of Shit Rankings", () => {
  it("shows the unique-player headline, incident total, and every fantasy team", () => {
    render(<ConductSection data={healthyData()} managers={managers} />);

    expect(
      screen.getByRole("heading", { name: "Piece of Shit Rankings" }),
    ).toBeInTheDocument();
    expect(screen.getByText("unique flagged players")).toBeInTheDocument();
    expect(screen.getByText("documented records")).toBeInTheDocument();
    expect(screen.getByText("league ranking points")).toBeInTheDocument();
    expect(screen.getByLabelText("Ranking score formula")).toHaveTextContent(
      "category severity points × current-status multiplier",
    );
    expect(screen.getAllByText("79.5")).toHaveLength(2);
    expect(screen.getByText("AAron")).toBeInTheDocument();
    expect(screen.getByText("Brisket Bandits")).toBeInTheDocument();
    expect(screen.getByText("Bea")).toBeInTheDocument();
    expect(screen.getByText("Bea's Beast Mode")).toBeInTheDocument();
  });

  it("keeps allegation and acquittal labels distinct and links the evidence", () => {
    render(<ConductSection data={healthyData()} managers={managers} />);

    const teamSummary = screen.getByText("AAron").closest("summary");
    fireEvent.click(teamSummary);
    expect(teamSummary.closest("details")).toHaveAttribute("open");

    const playerSummary = screen.getByText("Example Player").closest("summary");
    fireEvent.click(playerSummary);
    expect(playerSummary.closest("details")).toHaveAttribute("open");
    expect(screen.getByText("27 pts")).toBeInTheDocument();
    expect(screen.getByText("3 records · +2 repeat")).toBeInTheDocument();
    expect(screen.getByText("+10 pts")).toBeInTheDocument();
    expect(screen.getByText("+0 pts")).toBeInTheDocument();
    expect(screen.getByText("50 severity × 0.2")).toBeInTheDocument();

    expect(
      screen.getByText("Allegation; no criminal charge reported"),
    ).toBeInTheDocument();
    expect(screen.getByText("Acquitted at trial")).toBeInTheDocument();
    expect(
      screen.getByText("A jury returned a not-guilty verdict."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The player pleaded not guilty before the acquittal."),
    ).toBeInTheDocument();
    const sourceLinks = screen.getAllByRole("link", {
      name: "Associated Press — case report",
    });
    expect(sourceLinks[0]).toHaveAttribute(
      "href",
      "https://apnews.com/article/example",
    );
  });

  it("does not turn a zero match into an exoneration claim", () => {
    render(<ConductSection data={healthyData()} managers={managers} />);

    const teamSummary = screen.getByText("Bea").closest("summary");
    fireEvent.click(teamSummary);

    expect(
      screen.getByText(/That is not a background-check result/),
    ).toBeInTheDocument();
  });

  it("withholds an invalid registry instead of rendering a false zero", () => {
    render(
      <ConductSection
        managers={managers}
        data={{ available: false, unavailableReason: "registryInvalid" }}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Piece of Shit Rankings unavailable" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/withheld rather than publishing/)).toBeInTheDocument();
    expect(screen.queryByText("unique flagged players")).not.toBeInTheDocument();
  });
});
