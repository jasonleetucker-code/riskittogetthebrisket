import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Two projects so the ~889 pure-logic tests keep running in the fast
// Node environment, untouched, while React component tests get a
// jsdom + Testing Library environment. The logic project explicitly
// excludes __tests__/components/** so component specs never run twice
// (and never pay the jsdom cost in the logic pass).
const alias = { "@": path.resolve(__dirname) };

// Date fixtures are written as UTC instants (``Date.UTC(...)``) and the
// helpers under test render them with ``toLocaleDateString`` in the
// process's local zone.  CI runners are UTC, so the expectations are UTC
// dates; a developer machine in, say, America/Chicago renders midnight
// UTC as the previous day and fails tests that pass in CI.  Pin the zone
// so local runs match CI.  An explicitly set ``TZ`` is respected, so a
// deliberate non-UTC run is still possible.  Worker processes inherit it.
if (!process.env.TZ) process.env.TZ = "UTC";

export default defineConfig({
  resolve: { alias },
  test: {
    projects: [
      {
        test: {
          name: "logic",
          environment: "node",
          include: ["__tests__/**/*.test.{js,jsx}"],
          exclude: ["__tests__/components/**", "**/node_modules/**"],
        },
        resolve: { alias },
      },
      {
        plugins: [react()],
        test: {
          name: "components",
          environment: "jsdom",
          include: ["__tests__/components/**/*.test.{jsx,js}"],
          setupFiles: ["./__tests__/setup/dom.js"],
        },
        resolve: { alias },
      },
    ],
  },
});
