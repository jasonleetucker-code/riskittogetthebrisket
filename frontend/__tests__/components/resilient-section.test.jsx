/**
 * ResilientSection — section-scoped error boundary.  Recovery depends on
 * what failed: a render crash may not recur, so "Retry" remounts; a failed
 * lazy chunk is cached by React.lazy, so only a page reload recovers it.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ResilientSection from "@/components/ResilientSection";

let reload;
const realLocation = window.location;

beforeEach(() => {
  vi.spyOn(console, "error").mockImplementation(() => {});
  reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...realLocation, reload },
  });
});

afterEach(() => {
  Object.defineProperty(window, "location", { configurable: true, value: realLocation });
  vi.restoreAllMocks();
});

function Boom({ error }) {
  throw error;
}

describe("ResilientSection", () => {
  it("renders children when nothing throws", () => {
    render(
      <ResilientSection name="Panel">
        <p>fine</p>
      </ResilientSection>,
    );
    expect(screen.getByText("fine")).toBeTruthy();
  });

  it("a render crash gets the design-system banner and a remounting retry", async () => {
    let fail = true;
    function Flaky() {
      if (fail) throw new Error("render crash");
      return <p>recovered</p>;
    }
    render(
      <ResilientSection name="Panel">
        <Flaky />
      </ResilientSection>,
    );
    const alert = screen.getByRole("alert");
    expect(alert.className).toMatch(/\bds-banner--negative\b/);
    expect(screen.getByText("Panel unavailable")).toBeTruthy();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry this section" }));
    expect(screen.getByText("recovered")).toBeTruthy();
    expect(reload).not.toHaveBeenCalled();
  });

  it('recovery="reload" offers a page reload instead of a retry', async () => {
    render(
      <ResilientSection name="Lazy panel" recovery="reload">
        <Boom error={new Error("anything")} />
      </ResilientSection>,
    );
    expect(screen.queryByRole("button", { name: "Retry this section" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Reload page" }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("a ChunkLoadError is recovered by reload even without recovery=reload", () => {
    const err = new Error("Loading chunk 123 failed.");
    err.name = "ChunkLoadError";
    render(
      <ResilientSection name="Panel">
        <Boom error={err} />
      </ResilientSection>,
    );
    expect(screen.getByRole("button", { name: "Reload page" })).toBeTruthy();
  });
});
