/**
 * C3-CON-02 — the persistent trade-protection editor.
 *
 * The component is a pure client of GET/PUT /api/user/trade-protections: it
 * collects names/teams, sends them for ONE named league, and renders what the
 * server stored.  Validation and meaning live in the backend constraint owner.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import TradeProtectionsEditor, { describeSaveError } from "@/components/TradeProtectionsEditor";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

const EMPTY = {
  leagueKey: "dynasty_main",
  configured: false,
  untouchables: [],
  nflTeams: [],
  nflTeamOptions: ["CIN", "MIN"],
  unresolvedUntouchables: [],
};

const PLAYERS = [
  { name: "Justin Jefferson", pos: "WR" },
  { name: "2027 Early 1st", pos: "PICK", assetClass: "pick" },
];

let fetchMock;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TradeProtectionsEditor", () => {
  it("asks anonymous users to sign in and never fetches", () => {
    render(<TradeProtectionsEditor enabled={false} leagueKey="dynasty_main" />);
    expect(screen.getByText(/Sign in to set trade protections/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires a league and never falls back to a default", () => {
    render(<TradeProtectionsEditor enabled leagueKey="" />);
    expect(screen.getByText(/Choose a league/)).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads the named league and explains outgoing-only, league-scoped semantics", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...EMPTY, configured: true, nflTeams: ["MIN"], untouchables: ["Ja'Marr Chase"] }),
    );
    render(
      <TradeProtectionsEditor enabled leagueKey="dynasty_main" leagueName="Main League" players={PLAYERS} />,
    );
    await screen.findByText("MIN");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/user/trade-protections?leagueKey=dynasty_main");
    expect(screen.getByText("Ja'Marr Chase")).toBeTruthy();
    expect(screen.getByText(/outgoing/).closest("p").textContent).toMatch(/Main League/);
    expect(screen.getByText(/keep their value/)).toBeTruthy();
    // Picks are not offered as player suggestions.
    const options = Array.from(document.querySelectorAll("#trade-protections-player-list option")).map(
      (o) => o.value,
    );
    expect(options).toEqual(["Justin Jefferson"]);
  });

  it("adds a team and a player, then PUTs exactly that block for the league", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(EMPTY));
    render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" players={PLAYERS} />);
    await screen.findByText(/No protected NFL teams/);

    const save = screen.getByRole("button", { name: /Save protections/ });
    expect(save.disabled).toBe(true); // nothing changed yet

    fireEvent.change(screen.getByLabelText(/Protect every player on an NFL team/), {
      target: { value: "MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add team" }));
    fireEvent.change(screen.getByLabelText("Protect a player"), {
      target: { value: "Justin Jefferson" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add player" }));

    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...EMPTY, configured: true, untouchables: ["Justin Jefferson"], nflTeams: ["MIN"] }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Save protections/ }));
    await screen.findByText("Saved.");

    const [url, init] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/user/trade-protections");
    expect(init.method).toBe("PUT");
    expect(JSON.parse(init.body)).toEqual({
      leagueKey: "dynasty_main",
      untouchables: ["Justin Jefferson"],
      nflTeams: ["MIN"],
    });
  });

  it("removes an entry and shows the server's rejection reason without pretending it saved", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...EMPTY, configured: true, nflTeams: ["MIN"] }));
    render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" />);
    await screen.findByText("MIN");
    fireEvent.click(screen.getByRole("button", { name: "Remove MIN" }));
    expect(screen.queryByRole("button", { name: "Remove MIN" })).toBeNull();
    expect(screen.getByText(/No protected NFL teams/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Protect a player"), { target: { value: "Nobody Real" } });
    fireEvent.click(screen.getByRole("button", { name: "Add player" }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse(
        {
          error: "invalid_protection",
          errors: [{ field: "untouchables", value: "Nobody Real", reason: "unknown_player" }],
        },
        400,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /Save protections/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/"Nobody Real" is not a player on the current board/);
    expect(screen.queryByText("Saved.")).toBeNull();
  });

  it("flags a stored player the board no longer carries, without dropping him", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        ...EMPTY,
        configured: true,
        untouchables: ["Retired Guy"],
        unresolvedUntouchables: ["Retired Guy"],
      }),
    );
    render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" />);
    await screen.findByText("Retired Guy");
    expect(screen.getByText(/Not on current board — still protected/)).toBeTruthy();
  });

  it("reloads when the selected league changes", async () => {
    fetchMock.mockResolvedValue(jsonResponse(EMPTY));
    const { rerender } = render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    rerender(<TradeProtectionsEditor enabled leagueKey="dynasty_new" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toBe("/api/user/trade-protections?leagueKey=dynasty_new");
  });

  it("ignores a save answer that arrives after the user switched league", async () => {
    let resolvePut;
    fetchMock.mockResolvedValueOnce(jsonResponse(EMPTY)); // GET league A
    const { rerender } = render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" />);
    await screen.findByText(/No protected NFL teams/);
    fireEvent.change(screen.getByLabelText(/Protect every player on an NFL team/), {
      target: { value: "MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add team" }));
    fetchMock.mockImplementationOnce(() => new Promise((r) => (resolvePut = r))); // PUT A
    fireEvent.click(screen.getByRole("button", { name: /Save protections/ }));

    fetchMock.mockResolvedValueOnce(jsonResponse({ ...EMPTY, leagueKey: "dynasty_new" })); // GET B
    rerender(<TradeProtectionsEditor enabled leagueKey="dynasty_new" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    await screen.findByText(/No protected NFL teams/);

    resolvePut(jsonResponse({ ...EMPTY, configured: true, nflTeams: ["MIN"] }));
    await new Promise((r) => setTimeout(r, 0));
    expect(screen.queryByText("Saved.")).toBeNull();
    expect(screen.queryByRole("button", { name: "Remove MIN" })).toBeNull();
  });

  it("refuses to display a save answer for a different league", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(EMPTY));
    render(<TradeProtectionsEditor enabled leagueKey="dynasty_main" />);
    await screen.findByText(/No protected NFL teams/);
    fireEvent.change(screen.getByLabelText(/Protect every player on an NFL team/), {
      target: { value: "MIN" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add team" }));
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ ...EMPTY, leagueKey: "dynasty_new", configured: true, nflTeams: ["MIN"] }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Save protections/ }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toMatch(/different league/);
    expect(screen.queryByText("Saved.")).toBeNull();
  });

  it("describes the no-board 503 and unknown team codes in plain words", () => {
    expect(describeSaveError({ error: "data_not_ready" }, 503)).toMatch(/No board is loaded/);
    expect(
      describeSaveError(
        { errors: [{ field: "nflTeams", value: "JAC", reason: "unknown_nfl_team" }] },
        400,
      ),
    ).toBe('"JAC" is not an NFL team code on the current board');
    expect(
      describeSaveError(
        {
          errors: [{ field: "untouchables", value: "A", reason: "unknown_player" }],
          errorsTruncated: 9,
        },
        400,
      ),
    ).toMatch(/and 9 more$/);
    expect(describeSaveError({ error: "guest_read_only", message: "Guest passes cannot save." }, 403)).toBe(
      "Guest passes cannot save.",
    );
  });
});
