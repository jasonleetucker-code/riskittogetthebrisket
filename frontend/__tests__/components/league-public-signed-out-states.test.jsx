// @vitest-environment jsdom
// Public /league, signed-out visitor (production walkthrough 2026-11-16):
//   * Trade Deadline read "Trade deadline unavailable" + a bare "401";
//   * Team Assignment said "Your session has expired" to someone who never
//     signed in, with the internal key 'teamAssignment' and "(auth_required)";
//   * Recaps titled the 2025 Week 17 slate "Week 17 recaps · 2025" with
//     present-tense copy while the 2026 season was under way.
// Each private section now says what it is and how to see it, the way Team
// Strength already did, and a slate with no known clock is "the most recent
// on file", never this week's.
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

function mockFetch(status, body) {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) }),
  );
}

async function fresh(path) {
  vi.resetModules();
  return import(path);
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Trade Deadline, signed out", () => {
  it("401 renders the sign-in state with a safe next link, never a bare status", async () => {
    mockFetch(401, { error: "auth_required" });
    const mod = await fresh("@/app/league/sections/ros-trade-deadline.jsx");
    const Section = mod.default;
    render(<Section />);
    await waitFor(() => screen.getByTestId("ros-trade-deadline-auth-required"));
    expect(screen.getByText(/available to signed-in league members/i)).toBeTruthy();
    const link = screen.getByRole("link", { name: /sign in/i });
    expect(link.getAttribute("href")).toBe("/login?next=%2Fleague%3Ftab%3DrosTradeDeadline");
    expect(mod.ROS_TRADE_DEADLINE_LOGIN_HREF).toBe(link.getAttribute("href"));
    expect(screen.queryByText(/^401$/)).toBeNull();
    expect(screen.queryByText(/Trade deadline unavailable/)).toBeNull();
  });

  it("a 503 says it could not load, in words, with the status only as detail", async () => {
    mockFetch(503, { error: "data_not_ready" });
    const { default: Section } = await fresh("@/app/league/sections/ros-trade-deadline.jsx");
    render(<Section />);
    await waitFor(() => screen.getByText("Trade deadline unavailable"));
    expect(screen.getByText(/could not be loaded right now/i)).toBeTruthy();
    expect(screen.queryByTestId("ros-trade-deadline-auth-required")).toBeNull();
  });
});

describe("Team Assignment, signed out", () => {
  it("401 renders the sign-in state: no 'session expired', no internal key", async () => {
    mockFetch(401, {
      error: "auth_required",
      message: "'teamAssignment' contains manager-specific intelligence and requires a session.",
    });
    const mod = await fresh("@/app/league/sections/team-assignment.jsx");
    const Section = mod.default;
    render(<Section />);
    await waitFor(() => screen.getByTestId("team-assignment-auth-required"));
    expect(screen.getByText(/available to signed-in league members/i)).toBeTruthy();
    const link = screen.getByRole("link", { name: /sign in/i });
    expect(link.getAttribute("href")).toBe("/login?next=%2Fleague%3Ftab%3DteamAssignment");
    expect(mod.TEAM_ASSIGNMENT_LOGIN_HREF).toBe(link.getAttribute("href"));
    const text = document.body.textContent;
    expect(text).not.toMatch(/session has expired/i);
    expect(text).not.toMatch(/'teamAssignment'/);
    expect(text).not.toMatch(/auth_required/);
  });

  it("a non-auth failure still renders the shared FailureState", async () => {
    mockFetch(503, { error: "data_not_ready" });
    const { default: Section } = await fresh("@/app/league/sections/team-assignment.jsx");
    render(<Section />);
    await waitFor(() => expect(screen.queryByText(/Loading team assignment/)).toBeNull());
    expect(screen.queryByTestId("team-assignment-auth-required")).toBeNull();
  });
});

describe("Recaps with no clock supplied", () => {
  const ARTICLES = {
    articles: [
      { season: "2025", week: 17, mode: "recap", matchupId: 1, title: "Champs", generatedAt: "2025-12-30T14:00:00Z" },
    ],
  };

  it("names the slate 'most recent on file', never this week's", async () => {
    mockFetch(200, ARTICLES);
    const { default: ArticlesSection } = await fresh("@/app/league/sections/articles.jsx");
    render(<ArticlesSection mode="recap" />);
    await waitFor(() => screen.getByText(/Most recent recaps · 2025 Week 17/));
    expect(screen.getByText(/The most recent recaps on file/)).toBeTruthy();
    expect(screen.queryByText(/^Week 17 recaps · 2025$/)).toBeNull();
    expect(screen.queryByText(/Tuesday-morning recaps\. Tap a card/)).toBeNull();
  });

  it("with a matching clock it is still this week's slate", async () => {
    mockFetch(200, ARTICLES);
    const { default: ArticlesSection } = await fresh("@/app/league/sections/articles.jsx");
    render(<ArticlesSection mode="recap" currentSeason="2025" currentWeek={17} />);
    await waitFor(() => screen.getByText(/Week 17 recaps · 2025/));
    expect(screen.getByText(/Tuesday-morning recaps\. Tap a card/)).toBeTruthy();
  });
});
