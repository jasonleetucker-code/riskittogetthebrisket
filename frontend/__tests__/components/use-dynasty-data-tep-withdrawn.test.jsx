/**
 * DEFECT-02 (held for owner approval): `useDynastyData` no longer forwards
 * the manual TE-premium knobs to `fetchDynastyData`.  A stale stored
 * `tepMultiplier` used to route the page onto the override POST with
 * `{tep_multiplier: ...}` and a non-canonical board; it must now take the
 * same path a fresh install does.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, waitFor } from "@testing-library/react";

const calls = vi.hoisted(() => []);

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    prefetchBaseContract: () => {},
    fetchDynastyData: vi.fn(async (opts) => {
      calls.push(opts);
      return { source: "test", data: null };
    }),
  };
});
vi.mock("@/components/useSettings", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    useSettings: () => ({
      settings: { ...actual.SETTINGS_DEFAULTS, tepMultiplier: 1.45, tepNativeMultiplier: 1.3 },
      hydrated: true,
    }),
  };
});

import { useDynastyData } from "@/components/useDynastyData";

function Probe() {
  useDynastyData();
  return null;
}

describe("useDynastyData and the withdrawn manual TE premium", () => {
  it("does not pass a stored manual TEP value to fetchDynastyData", async () => {
    render(<Probe />);
    await waitFor(() => expect(calls.length).toBeGreaterThan(0));
    for (const opts of calls) {
      expect(opts).not.toHaveProperty("tepMultiplier");
      expect(opts).not.toHaveProperty("tepNativeMultiplier");
    }
  });
});
