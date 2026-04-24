/**
 * Tests for device-profile detection.
 *
 * We avoid the jsdom dep (not installed in this frontend) by
 * stubbing globalThis.window / navigator / document directly
 * and resetting between tests.  The module checks `typeof
 * window !== "undefined"` at module scope, so mutating globals
 * works.
 */
import { describe, it, expect, beforeEach, afterEach } from "vitest";
import {
  isMobileProfile,
  effectiveConnectionType,
  isSlowNetwork,
  isTabVisible,
  adjustedPollingMs,
  preferredDataView,
} from "../lib/device-profile.js";


function setWindow(opts = {}) {
  globalThis.window = { innerWidth: opts.innerWidth ?? 1920 };
  globalThis.navigator = {
    connection: opts.effectiveType ? { effectiveType: opts.effectiveType } : undefined,
    deviceMemory: opts.deviceMemory,
  };
  globalThis.document = { hidden: opts.hidden ?? false };
}


function resetGlobals() {
  delete globalThis.window;
  delete globalThis.navigator;
  delete globalThis.document;
}


describe("device-profile", () => {
  afterEach(() => resetGlobals());

  it("SSR (no window) → not mobile", () => {
    resetGlobals();
    expect(isMobileProfile()).toBe(false);
  });

  it("desktop viewport → not mobile", () => {
    setWindow({ innerWidth: 1920 });
    expect(isMobileProfile()).toBe(false);
  });

  it("small viewport → mobile", () => {
    setWindow({ innerWidth: 400 });
    expect(isMobileProfile()).toBe(true);
  });

  it("deviceMemory <= 4GB → mobile-class", () => {
    setWindow({ innerWidth: 1920, deviceMemory: 2 });
    expect(isMobileProfile()).toBe(true);
  });

  it("deviceMemory > 4GB keeps desktop", () => {
    setWindow({ innerWidth: 1920, deviceMemory: 16 });
    expect(isMobileProfile()).toBe(false);
  });

  it("slow network detected from effectiveType", () => {
    for (const t of ["slow-2g", "2g", "3g"]) {
      setWindow({ effectiveType: t });
      expect(isSlowNetwork()).toBe(true);
    }
    setWindow({ effectiveType: "4g" });
    expect(isSlowNetwork()).toBe(false);
    setWindow({});
    expect(isSlowNetwork()).toBe(false);
  });

  it("preferredDataView → compact on mobile", () => {
    setWindow({ innerWidth: 400 });
    expect(preferredDataView()).toBe("compact");
  });

  it("preferredDataView → delta on desktop", () => {
    setWindow({ innerWidth: 1920 });
    expect(preferredDataView()).toBe("delta");
  });

  it("preferredDataView → compact on slow network", () => {
    setWindow({ innerWidth: 1920, effectiveType: "3g" });
    expect(preferredDataView()).toBe("compact");
  });

  it("adjustedPollingMs unchanged on desktop foreground", () => {
    setWindow({ innerWidth: 1920, hidden: false });
    expect(adjustedPollingMs(30000)).toBe(30000);
  });

  it("adjustedPollingMs 2× on mobile foreground", () => {
    setWindow({ innerWidth: 400, hidden: false });
    expect(adjustedPollingMs(30000)).toBe(60000);
  });

  it("adjustedPollingMs 3× on slow network", () => {
    setWindow({ innerWidth: 1920, effectiveType: "3g", hidden: false });
    expect(adjustedPollingMs(30000)).toBe(90000);
  });

  it("adjustedPollingMs 10× when tab hidden", () => {
    setWindow({ innerWidth: 1920, hidden: true });
    expect(adjustedPollingMs(30000)).toBe(300000);
  });

  it("isTabVisible follows document.hidden", () => {
    setWindow({ hidden: false });
    expect(isTabVisible()).toBe(true);
    setWindow({ hidden: true });
    expect(isTabVisible()).toBe(false);
  });

  it("effectiveConnectionType returns the string", () => {
    setWindow({ effectiveType: "4g" });
    expect(effectiveConnectionType()).toBe("4g");
    setWindow({});
    expect(effectiveConnectionType()).toBe(undefined);
  });
});
