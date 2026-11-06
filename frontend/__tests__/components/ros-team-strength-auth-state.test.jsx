// @vitest-environment jsdom
import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, waitFor } from "@testing-library/react";
import Section, {
  _resetRosTeamStrengthCache,
  ROS_TEAM_STRENGTH_LOGIN_HREF,
} from "../../app/league/sections/ros-team-strength.jsx";

function mockFetch(status, body) {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) }),
  );
}

afterEach(() => {
  cleanup();
  _resetRosTeamStrengthCache();
  vi.restoreAllMocks();
});

describe("ROS Team Strength section states", () => {
  it("401 renders an explicit sign-in state with a safe next link, not a spinner", async () => {
    mockFetch(401, { error: "auth_required" });
    render(<Section />);
    await waitFor(() => screen.getByTestId("ros-team-strength-auth-required"));
    expect(screen.getByText(/available to signed-in league members/i)).toBeTruthy();
    const link = screen.getByRole("link", { name: /sign in/i });
    expect(link.getAttribute("href")).toBe("/login?next=%2Fleague%3Ftab%3DrosTeamStrength");
    expect(ROS_TEAM_STRENGTH_LOGIN_HREF).toBe(link.getAttribute("href"));
    expect(screen.queryByText(/Loading/i)).toBeNull();
  });

  it("403 also renders the auth state", async () => {
    mockFetch(403, { error: "forbidden" });
    render(<Section />);
    await waitFor(() => screen.getByTestId("ros-team-strength-auth-required"));
  });

  it("500 renders an error state distinct from auth", async () => {
    mockFetch(500, { error: "boom" });
    render(<Section />);
    await waitFor(() => expect(screen.queryByText(/Loading/i)).toBeNull());
    expect(screen.queryByTestId("ros-team-strength-auth-required")).toBeNull();
    expect(screen.queryByText(/signed-in league members/i)).toBeNull();
  });

  it("pending renders loading", () => {
    global.fetch = vi.fn(() => new Promise(() => {}));
    render(<Section />);
    expect(screen.getByText(/Loading ROS roster strength/i)).toBeTruthy();
  });

  it("200 renders the table", async () => {
    mockFetch(200, { data: { teams: [{ rank: 1, teamName: "Alpha", teamRosStrength: 812 }] } });
    render(<Section />);
    await waitFor(() => screen.getByText("Alpha"));
    expect(screen.queryByTestId("ros-team-strength-auth-required")).toBeNull();
  });
});
