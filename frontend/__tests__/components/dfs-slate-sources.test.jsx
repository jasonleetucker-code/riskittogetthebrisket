import React from "react";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ProviderSlates, { DetectedFile, describeDetection } from "@/components/dfs/SlateSources";

const json = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body });

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const NFL_DK = { platform: "draftkings", sport: "nfl", format: "classic" };

describe("DetectedFile", () => {
  it("names what the file is and offers a switch instead of silently changing context", async () => {
    fetch.mockResolvedValue(
      json(200, {
        detection: { platform: "fanduel", sport: "nfl", format: "classic", reasons: [] },
        capability: { readiness: "research_only" },
      }),
    );
    const onSwitch = vi.fn();
    render(<DetectedFile text="Id,FPPG,Nickname" context={NFL_DK} onSwitch={onSwitch} />);
    await act(async () => vi.advanceTimersByTime(400));
    expect(await screen.findByText("Detected: FanDuel · NFL · Classic")).toBeInTheDocument();
    expect(onSwitch).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Switch to FanDuel · NFL · Classic" }));
    expect(onSwitch).toHaveBeenCalledWith({ platform: "fanduel", sport: "nfl", format: "classic" });
  });

  it("says a recognised MMA file cannot be built yet (no fake support)", async () => {
    fetch.mockResolvedValue(
      json(200, { detection: { platform: "draftkings", sport: "mma", format: "classic", reasons: [] }, capability: { readiness: "not_implemented" } }),
    );
    render(<DetectedFile text="x" context={NFL_DK} onSwitch={() => {}} />);
    await act(async () => vi.advanceTimersByTime(400));
    expect(await screen.findByText(/roster rules are not encoded yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("reports an unrecognised file with the evidence", async () => {
    fetch.mockResolvedValue(json(200, { detection: { platform: null, reasons: ["Header matches no supported platform file"] } }));
    render(<DetectedFile text="a,b" context={NFL_DK} onSwitch={() => {}} />);
    await act(async () => vi.advanceTimersByTime(400));
    expect(await screen.findByText("File not recognised")).toBeInTheDocument();
  });

  it("formats detections", () => {
    expect(describeDetection({ platform: "draftkings", sport: "nfl", format: "showdown_captain" })).toBe(
      "DraftKings · NFL · Showdown Captain",
    );
    expect(describeDetection({ platform: null })).toBe(null);
  });
});

describe("ProviderSlates", () => {
  const MATRIX = [{ platform: "draftkings", sport: "nfl", status: "blocked", reason: "Schema documented, not verified." }];

  it("shows an unconnected feed as unconnected and names the CSV fallback", async () => {
    fetch.mockResolvedValue(json(200, { matrix: MATRIX, status: { sportsdataio: { state: "no_credential", note: "SPORTSDATAIO_API_KEY is not set." } } }));
    render(<ProviderSlates sport="nfl" platform="draftkings" onImported={() => {}} />);
    expect(await screen.findByText(/SportsDataIO: not connected/)).toBeInTheDocument();
    expect(screen.getByText(/that path always works/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "List slates" })).not.toBeInTheDocument();
  });

  it("lists and loads provider slates when connected, and surfaces provider failures", async () => {
    const onImported = vi.fn();
    fetch.mockImplementation(async (url) => {
      const u = String(url);
      if (u.endsWith("/providers")) return json(200, { matrix: MATRIX, status: { sportsdataio: { state: "configured_unverified", note: "" } } });
      if (u.includes("/provider-slates?")) return json(200, { slates: [{ providerSlateId: 9001, name: "Main", games: 11, players: 176 }] });
      if (u.endsWith("/provider-slates/import")) return json(201, { snapshotId: "snap_x" });
      throw new Error(u);
    });
    render(<ProviderSlates sport="nfl" platform="draftkings" onImported={onImported} />);
    fireEvent.change(await screen.findByLabelText("Slate date"), { target: { value: "2026-10-04" } });
    fireEvent.click(screen.getByRole("button", { name: "List slates" }));
    expect(await screen.findByText(/Main · 11 games · 176 players/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Load" }));
    await act(async () => {});
    expect(onImported).toHaveBeenCalledWith({ snapshotId: "snap_x" });

    fetch.mockImplementation(async (url) =>
      String(url).includes("/provider-slates?")
        ? json(503, { error: "QUOTA_EXCEEDED", message: "SportsDataIO quota exceeded.", detail: { fallback: "Import the salary CSV." } })
        : json(200, {}),
    );
    fireEvent.click(screen.getByRole("button", { name: "List slates" }));
    expect(await screen.findByText(/quota exceeded\. Import the salary CSV\./)).toBeInTheDocument();
  });
});
