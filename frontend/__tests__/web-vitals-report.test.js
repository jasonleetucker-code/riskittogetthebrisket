import { describe, expect, it } from "vitest";
import { vitalsRouteTemplate, webVitalsPayload } from "@/lib/web-vitals-report";

describe("Web Vitals privacy boundary", () => {
  it("templates private entity paths and drops unknown routes", () => {
    expect(vitalsRouteTemplate("/players/private-name?leagueKey=secret")).toBe("/players/[playerId]");
    expect(vitalsRouteTemplate("/players/compare?p1=secret")).toBe("/players/compare");
    expect(vitalsRouteTemplate("/rankings/QB")).toBe("/rankings/[position]");
    expect(vitalsRouteTemplate("/unrecognized/private-id")).toBeNull();
  });
  it("emits only allowlisted finite measurements, preserving a measured zero", () => {
    const metric = { name: "CLS", value: 0, id: "v4-123-456", navigationType: "reload", entries: [{ name: "private" }], attribution: { url: "secret" } };
    expect(webVitalsPayload(metric, { route: "/rankings", device: "mobile" })).toEqual({
      name: "CLS", value: 0, id: "v4-123-456", navigationType: "reload", route: "/rankings", device: "mobile",
    });
    for (const value of [null, undefined, NaN, Infinity, -1]) {
      expect(webVitalsPayload({ ...metric, value }, { route: "/rankings" })).toBeNull();
    }
    expect(webVitalsPayload({ ...metric, name: "private" }, { route: "/rankings" })).toBeNull();
    expect(webVitalsPayload(metric, { route: "/players/private" })).toBeNull();
    expect(webVitalsPayload({ ...metric, id: "contains/private?value" }, { route: "/rankings" })).toBeNull();
  });
});
