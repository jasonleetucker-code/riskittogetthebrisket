import { render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import WebVitalsReporter from "@/components/WebVitalsReporter";

const hook = vi.hoisted(() => ({ report: null }));
vi.mock("next/web-vitals", () => ({ useReportWebVitals: (report) => { hook.report = report; } }));
afterEach(() => { vi.unstubAllGlobals(); });

it("sends only the safe payload and suppresses the private URL Referer", () => {
  window.history.replaceState({}, "", "/players/private-player?leagueKey=private-league");
  const fetcher = vi.fn(async () => ({ ok: true }));
  vi.stubGlobal("fetch", fetcher);
  render(<WebVitalsReporter />);
  hook.report({ name: "LCP", value: 234.5, id: "v4-123-456", navigationType: "navigate", entries: [{ url: "private" }] });
  const [url, options] = fetcher.mock.calls[0];
  expect(url).toBe("/api/telemetry/web-vitals");
  expect(options.referrerPolicy).toBe("no-referrer");
  expect(JSON.parse(options.body).route).toBe("/players/[playerId]");
  expect(options.body).not.toContain("private");
  window.history.replaceState({}, "", "/");
});
