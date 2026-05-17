import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Two projects so the ~889 pure-logic tests keep running in the fast
// Node environment, untouched, while React component tests get a
// jsdom + Testing Library environment. The logic project explicitly
// excludes __tests__/components/** so component specs never run twice
// (and never pay the jsdom cost in the logic pass).
const alias = { "@": path.resolve(__dirname) };

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
