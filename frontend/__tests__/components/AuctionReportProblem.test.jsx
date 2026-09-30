/**
 * Rehearsal "Report a problem": sends the room's revision with the report,
 * uses an Idempotency-Key, and shows the server's pinned revision back.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReportProblem from "@/components/auction/ReportProblem";

const view = {
  revision: 42,
  me: { role: "manager", seat: "S2" },
  public: { auctions: [{ id: "A1", player: "p1", status: "open" }] },
};

afterEach(() => vi.restoreAllMocks());

describe("ReportProblem", () => {
  it("files a report pinned to the current revision", async () => {
    const calls = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url, init = {}) => {
      calls.push({ url, init });
      const body =
        init.method === "POST"
          ? { id: 7, revision: 42, replayed: false }
          : { reports: [], codeSha: "x" };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    });
    render(<ReportProblem view={view} players={{ p1: { name: "Rookie One" } }} roomId="r_1" />);
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    fireEvent.change(screen.getByLabelText("What happened?"), { target: { value: "price jumped" } });
    fireEvent.change(screen.getByLabelText("Which lot? (optional)"), { target: { value: "A1" } });
    fireEvent.click(screen.getByRole("button", { name: "Send report" }));
    await waitFor(() => expect(screen.getByText(/Report #7 saved at room revision 42/)).toBeTruthy());
    const post = calls.find((c) => c.init.method === "POST");
    expect(post.url).toContain("/rooms/r_1/reports");
    expect(post.init.headers["Idempotency-Key"]).toBeTruthy();
    const sent = JSON.parse(post.init.body);
    expect(sent).toMatchObject({ what_happened: "price jumped", auction: "A1", player_label: "Rookie One", client_revision: 42 });
  });

  it("refuses an empty report without calling the server", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ reports: [] }), { status: 200 }));
    render(<ReportProblem view={view} players={{}} roomId="r_1" />);
    fireEvent.click(screen.getByRole("button", { name: "Report" }));
    fireEvent.click(screen.getByRole("button", { name: "Send report" }));
    expect(await screen.findByText("Say what happened.")).toBeTruthy();
    expect(spy.mock.calls.every(([, init]) => !init || init.method !== "POST")).toBe(true);
  });
});
